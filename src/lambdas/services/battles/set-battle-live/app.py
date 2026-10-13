"""
Battles API - Set Battle Live
Triggerata da EventBridge Scheduler all'orario di event_datetime della battle
(e da update-battle quando l'host porta la battle a 'live' a mano).

1. Passa la battle da 'published' a 'live'. La ConditionExpression garantisce
   che non tocchi mai una battle già 'live' o 'closed' (es. host che l'ha
   chiusa manualmente in anticipo, o schedule rimasto orfano).
2. Se la battle è 'live', apre i suoi matchup: tutti quelli ancora
   'published' passano a 'live', così il voto si abilita insieme alla battle.
   Un matchup già 'live' o 'closed' non viene toccato. Il passo è idempotente:
   rieseguirlo non ha effetti.
3. Per ogni matchup aperto manda un `matchup_update` ai client WebSocket
   connessi (best-effort), così chi sta guardando lo vede subito.
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
connections_table = dynamodb.Table(os.environ['MATCHUP_CONNECTIONS_TABLE'])

# Vuoto finché lo stack matchups non è stato deployato: in quel caso i client
# non ricevono il push, ma i matchup si aprono comunque.
WEBSOCKET_API_ENDPOINT = os.environ.get('WEBSOCKET_API_ENDPOINT', '')
apigw_management = (
    boto3.client('apigatewaymanagementapi', endpoint_url=WEBSOCKET_API_ENDPOINT)
    if WEBSOCKET_API_ENDPOINT else None
)


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _set_battle_live(battle_id):
    try:
        battles_table.update_item(
            Key={'battle_id': battle_id},
            UpdateExpression='SET #status = :live, updated_at = :now',
            ConditionExpression='#status = :published',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':live': 'live',
                ':published': 'published',
                ':now': _now_iso(),
            },
        )
        print(f"[set-battle-live] Battle {battle_id} is now live")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"[set-battle-live] Battle {battle_id} not in 'published' status anymore — skipping the flip")
        else:
            print(f"[set-battle-live] Error updating battle {battle_id}: {e}")
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
        print(f"[set-battle-live] Warning: could not query connections for {matchup_id}: {e}")
        return

    payload = json.dumps({
        'action': 'matchup_update',
        'matchup_id': matchup_id,
        'status': 'live',
        'winner': None,
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
            print(f"[set-battle-live] Warning: could not send to connection {connection_id}: {e}")


def _open_matchups(battle_id):
    opened = 0
    for matchup in _matchups_of(battle_id):
        if matchup.get('status') != 'published':
            continue
        try:
            result = matchups_table.update_item(
                Key={'matchup_id': matchup['matchup_id']},
                UpdateExpression='SET #status = :live, updated_at = :now',
                ConditionExpression='#status = :published',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':live': 'live',
                    ':published': 'published',
                    ':now': _now_iso(),
                },
                ReturnValues='ALL_NEW',
            )
        except ClientError as e:
            # Aperto o chiuso da qualcun altro nel frattempo: va bene così.
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                continue
            print(f"[set-battle-live] Warning: could not open matchup {matchup['matchup_id']}: {e}")
            continue
        opened += 1
        _broadcast_matchup_update(result['Attributes'])
    print(f"[set-battle-live] Battle {battle_id}: opened {opened} matchup(s)")


def handler(event, context):
    battle_id = event.get('battle_id')
    if not battle_id:
        print(f"[set-battle-live] Missing battle_id in event: {event}")
        return

    _set_battle_live(battle_id)

    # Si guarda lo stato reale, non l'esito del flip: se l'host aveva già
    # portato la battle a 'live' a mano, i matchup vanno aperti comunque.
    battle = battles_table.get_item(Key={'battle_id': battle_id}).get('Item')
    if not battle or battle.get('status') != 'live':
        return

    _open_matchups(battle_id)
