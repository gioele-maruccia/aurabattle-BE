"""
Battles API - Set Battle Closed
Triggerata da EventBridge Scheduler all'orario di end_datetime della battle
(e da update-battle quando l'host la chiude a mano).

1. Porta la battle a 'closed' (se non lo è già).
2. Chiude tutti i suoi matchup non ancora chiusi, con la stessa logica di
   update-matchup: il vincitore si calcola dai voti correnti (più A -> 'A',
   più B -> 'B', pari -> 'tie'), e solo per i partecipanti REGISTRATI si
   aggiorna aura_stats.wins / aura_stats.losses. I guest non si toccano.
   Un matchup già chiuso non si ricalcola: le statistiche si applicano una
   sola volta.
3. Per ogni matchup chiuso manda un `matchup_update` ai client WebSocket
   connessi (best-effort).

Idempotente: rieseguirla non ha effetti.
"""
import json
import os
import boto3
from datetime import datetime
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
connections_table = dynamodb.Table(os.environ['MATCHUP_CONNECTIONS_TABLE'])

WEBSOCKET_API_ENDPOINT = os.environ.get('WEBSOCKET_API_ENDPOINT', '')
apigw_management = (
    boto3.client('apigatewaymanagementapi', endpoint_url=WEBSOCKET_API_ENDPOINT)
    if WEBSOCKET_API_ENDPOINT else None
)

# Quante volte rileggere un matchup se un voto arriva mentre lo si chiude.
MAX_CLOSE_ATTEMPTS = 5


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _set_battle_closed(battle_id):
    try:
        battles_table.update_item(
            Key={'battle_id': battle_id},
            UpdateExpression='SET #status = :closed, updated_at = :now',
            ConditionExpression='attribute_exists(battle_id) AND #status <> :closed',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':closed': 'closed', ':now': _now_iso()},
        )
        print(f"[set-battle-closed] Battle {battle_id} is now closed")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"[set-battle-closed] Battle {battle_id} missing or already closed — skipping the flip")
        else:
            print(f"[set-battle-closed] Error updating battle {battle_id}: {e}")
            raise


def _matchups_of(battle_id):
    items = []
    kwargs = {
        'IndexName': 'battle_id-index',
        'KeyConditionExpression': Key('battle_id').eq(battle_id),
    }
    while True:
        response = matchups_table.query(**kwargs)
        items.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            return items
        kwargs['ExclusiveStartKey'] = last_key


def _apply_stat(user_id, field):
    try:
        user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression=f'ADD aura_stats.{field} :inc',
            ExpressionAttributeValues={':inc': 1},
        )
    except Exception as e:
        print(f"[set-battle-closed] Warning: could not update {field} for {user_id}: {e}")


def _winner_of(votes_a, votes_b):
    if votes_a > votes_b:
        return 'A'
    if votes_b > votes_a:
        return 'B'
    return 'tie'


def _close_matchup(matchup_id):
    """Chiude un matchup e ritorna l'item aggiornato, o None se era già chiuso
    (o non esiste più).

    La scrittura è condizionata allo stato *e* ai voti letti: se un voto arriva
    fra la lettura e la scrittura la condizione fallisce, si rilegge e il
    vincitore viene calcolato sui voti definitivi.
    """
    for _ in range(MAX_CLOSE_ATTEMPTS):
        matchup = matchups_table.get_item(Key={'matchup_id': matchup_id}).get('Item')
        if not matchup or matchup.get('status') == 'closed':
            return None

        votes_a = int(matchup.get('votes_a', 0))
        votes_b = int(matchup.get('votes_b', 0))
        winner = _winner_of(votes_a, votes_b)

        try:
            result = matchups_table.update_item(
                Key={'matchup_id': matchup_id},
                UpdateExpression='SET #status = :closed, #winner = :winner, updated_at = :now',
                ConditionExpression=(
                    '#status <> :closed '
                    'AND (attribute_not_exists(votes_a) OR votes_a = :va) '
                    'AND (attribute_not_exists(votes_b) OR votes_b = :vb)'
                ),
                ExpressionAttributeNames={'#status': 'status', '#winner': 'winner'},
                ExpressionAttributeValues={
                    ':closed': 'closed',
                    ':winner': winner,
                    ':va': votes_a,
                    ':vb': votes_b,
                    ':now': _now_iso(),
                },
                ReturnValues='ALL_NEW',
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                continue
            raise

        # Le statistiche solo dopo che la chiusura è andata a segno: è quello
        # che garantisce che si applichino una volta sola.
        if winner != 'tie':
            winning = matchup['participant_a'] if winner == 'A' else matchup['participant_b']
            losing = matchup['participant_b'] if winner == 'A' else matchup['participant_a']
            if 'user_id' in winning:
                _apply_stat(winning['user_id'], 'wins')
            if 'user_id' in losing:
                _apply_stat(losing['user_id'], 'losses')

        return result['Attributes']

    print(f"[set-battle-closed] Warning: could not close matchup {matchup_id}: votes kept changing")
    return None


def _broadcast_matchup_update(matchup):
    if apigw_management is None:
        return
    matchup_id = matchup['matchup_id']
    try:
        response = connections_table.query(
            IndexName='matchupId-index',
            KeyConditionExpression=Key('matchupId').eq(matchup_id),
        )
    except Exception as e:
        print(f"[set-battle-closed] Warning: could not query connections for {matchup_id}: {e}")
        return

    payload = json.dumps({
        'action': 'matchup_update',
        'matchup_id': matchup_id,
        'status': 'closed',
        'winner': matchup.get('winner'),
        'votes_a': int(matchup.get('votes_a', 0)),
        'votes_b': int(matchup.get('votes_b', 0)),
    }).encode('utf-8')

    for item in response.get('Items', []):
        connection_id = item['connectionId']
        try:
            apigw_management.post_to_connection(ConnectionId=connection_id, Data=payload)
        except apigw_management.exceptions.GoneException:
            try:
                connections_table.delete_item(Key={'connectionId': connection_id})
            except Exception:
                pass
        except Exception as e:
            print(f"[set-battle-closed] Warning: could not send to connection {connection_id}: {e}")


def handler(event, context):
    battle_id = event.get('battle_id')
    if not battle_id:
        print(f"[set-battle-closed] Missing battle_id in event: {event}")
        return

    _set_battle_closed(battle_id)

    # Anche se il flip non c'è stato (già chiusa a mano), i matchup rimasti
    # aperti vanno chiusi: una battle chiusa non deve accettare voti.
    battle = battles_table.get_item(Key={'battle_id': battle_id}).get('Item')
    if not battle or battle.get('status') != 'closed':
        return

    closed = 0
    for matchup in _matchups_of(battle_id):
        if matchup.get('status') == 'closed':
            continue
        updated = _close_matchup(matchup['matchup_id'])
        if updated is None:
            continue
        closed += 1
        _broadcast_matchup_update(updated)
    print(f"[set-battle-closed] Battle {battle_id}: closed {closed} matchup(s)")
