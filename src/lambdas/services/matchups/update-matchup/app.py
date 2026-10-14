"""
Matchups API - Update Matchup
Aggiorna un matchup. Solo l'host della battle può modificarlo.

Lo stato va solo avanti: published -> live -> closed. Un matchup chiuso è
definitivo e non si modifica più. Un matchup si apre (live) solo mentre la
sua battle è live: il voto parte insieme alla battle.

Alla transizione verso 'closed' il vincitore viene calcolato dai voti
definitivi, con la stessa logica di set-battle-closed:
- più voti A -> 'A', più voti B -> 'B', pari -> 'tie' (nessun winner/loser)
Per ogni partecipante REGISTRATO (user_id, non guest) coinvolto, aggiorna
aura_stats.wins / aura_stats.losses su UserProfiles. I guest non vengono toccati.

Ogni cambio di stato manda un `matchup_update` ai client WebSocket connessi
(best-effort).
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
apigw_management = boto3.client('apigatewaymanagementapi', endpoint_url=os.environ['WEBSOCKET_API_ENDPOINT'])

ALLOWED_STATUSES = ['published', 'live', 'closed']
STATUS_ORDER = {'published': 0, 'live': 1, 'closed': 2}

# Quante volte rileggere un matchup se un voto arriva mentre lo si chiude.
MAX_CLOSE_ATTEMPTS = 5


class _Conflict(Exception):
    pass


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'PUT,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }


def _conflict(message):
    return _cors_response(409, {'error': 'Conflict', 'message': message})


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _parse_participant(value, label):
    if not isinstance(value, dict):
        return None, f'{label} must be an object with either user_id or guest_name'

    user_id = (value.get('user_id') or '').strip()
    guest_name = (value.get('guest_name') or '').strip()

    if bool(user_id) == bool(guest_name):
        return None, f'{label} must have exactly one of user_id or guest_name'

    if user_id:
        profile = user_profiles_table.get_item(Key={'user_id': user_id}).get('Item')
        if not profile:
            return None, f'{label}.user_id does not refer to an existing user'
        return {'user_id': user_id}, None

    return {'guest_name': guest_name}, None


def _enrich_participant(participant):
    if not participant or 'user_id' not in participant:
        return participant
    profile = user_profiles_table.get_item(
        Key={'user_id': participant['user_id']},
        ProjectionExpression='username, display_name, avatar_url'
    ).get('Item')
    if not profile:
        return participant
    return {
        **participant,
        'username': profile.get('username'),
        'display_name': profile.get('display_name', ''),
        'avatar_url': profile.get('avatar_url'),
    }


def _apply_stat(user_id, field):
    try:
        user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression=f'ADD aura_stats.{field} :inc',
            ExpressionAttributeValues={':inc': 1}
        )
    except Exception as e:
        print(f"[update-matchup] Warning: could not update {field} for {user_id}: {e}")


def _winner_of(votes_a, votes_b):
    if votes_a > votes_b:
        return 'A'
    if votes_b > votes_a:
        return 'B'
    return 'tie'


def _update_fields(matchup_id, fields):
    """Scrive i campi non di chiusura. Condizionata a 'non chiuso': se il
    matchup viene chiuso (a mano o da set-battle-closed) fra la lettura e la
    scrittura, la modifica non deve passare.
    """
    expr_names = {'#status': 'status', '#updated_at': 'updated_at'}
    expr_values = {':closed': 'closed', ':now': _now_iso()}
    update_parts = ['#updated_at = :now']
    for field, value in fields.items():
        expr_names[f'#{field}'] = field
        expr_values[f':{field}'] = value
        update_parts.append(f'#{field} = :{field}')

    try:
        result = matchups_table.update_item(
            Key={'matchup_id': matchup_id},
            UpdateExpression='SET ' + ', '.join(update_parts),
            ConditionExpression='#status <> :closed',
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues='ALL_NEW',
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            raise _Conflict('The matchup has been closed in the meantime')
        raise
    return result['Attributes']


def _close_matchup(matchup_id):
    """Chiude il matchup e ritorna l'item aggiornato.

    La scrittura è condizionata allo stato *e* ai voti letti: se un voto arriva
    fra la lettura e la scrittura la condizione fallisce, si rilegge e il
    vincitore viene calcolato sui voti definitivi. Le statistiche si applicano
    solo dopo che la chiusura è andata a segno, quindi una volta sola anche con
    due chiusure in parallelo.
    """
    for _ in range(MAX_CLOSE_ATTEMPTS):
        matchup = matchups_table.get_item(Key={'matchup_id': matchup_id}).get('Item')
        if not matchup or matchup.get('status') == 'closed':
            raise _Conflict('The matchup has been closed in the meantime')

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

        if winner != 'tie':
            winning = matchup['participant_a'] if winner == 'A' else matchup['participant_b']
            losing = matchup['participant_b'] if winner == 'A' else matchup['participant_a']
            if 'user_id' in winning:
                _apply_stat(winning['user_id'], 'wins')
            if 'user_id' in losing:
                _apply_stat(losing['user_id'], 'losses')

        return result['Attributes']

    raise _Conflict('Votes kept changing while closing the matchup, try again')


def _broadcast_matchup_update(matchup):
    """Best-effort: un errore qui non deve far fallire la modifica, che è già
    persistita.
    """
    matchup_id = matchup['matchup_id']
    try:
        response = connections_table.query(
            IndexName='matchupId-index',
            KeyConditionExpression=Key('matchupId').eq(matchup_id),
        )
    except Exception as e:
        print(f"[update-matchup] Warning: could not query connections for {matchup_id}: {e}")
        return

    payload = json.dumps({
        'action': 'matchup_update',
        'matchup_id': matchup_id,
        'status': matchup.get('status'),
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
            print(f"[update-matchup] Warning: could not send to connection {connection_id}: {e}")


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        matchup_id = event['pathParameters']['matchupId']
        body = json.loads(event.get('body') or '{}')

        existing = matchups_table.get_item(Key={'matchup_id': matchup_id}).get('Item')
        if not existing:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Matchup not found'})

        battle = battles_table.get_item(Key={'battle_id': existing['battle_id']}).get('Item')
        if not battle or battle['host_id'] != user_id:
            return _cors_response(403, {'error': 'Forbidden', 'message': 'Only the host of the battle can update this matchup'})

        if existing.get('status') == 'closed':
            return _conflict('A closed matchup cannot be modified')

        new_status = body.get('status')
        if 'status' in body and new_status not in ALLOWED_STATUSES:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': f'status must be one of: {", ".join(ALLOWED_STATUSES)}'
            })

        current_status = existing.get('status', 'published')
        if new_status is not None and STATUS_ORDER[new_status] < STATUS_ORDER[current_status]:
            return _conflict(f'status can only move forward (published -> live -> closed), it is {current_status}')

        if new_status == 'live' and current_status != 'live' and battle.get('status') != 'live':
            return _conflict('A matchup can only be opened while its battle is live')

        fields = {}
        if 'participant_a' in body:
            participant_a, error = _parse_participant(body['participant_a'], 'participant_a')
            if error:
                return _cors_response(400, {'error': 'Bad Request', 'message': error})
            fields['participant_a'] = participant_a

        if 'participant_b' in body:
            participant_b, error = _parse_participant(body['participant_b'], 'participant_b')
            if error:
                return _cors_response(400, {'error': 'Bad Request', 'message': error})
            fields['participant_b'] = participant_b

        if new_status in ('published', 'live'):
            fields['status'] = new_status

        # Una chiusura senza altri campi non passa da _update_fields: e' la
        # chiusura stessa a scrivere.
        try:
            updated = existing
            if fields or new_status != 'closed':
                updated = _update_fields(matchup_id, fields)
            if new_status == 'closed':
                updated = _close_matchup(matchup_id)
        except _Conflict as e:
            return _conflict(str(e))

        if updated.get('status') != current_status:
            _broadcast_matchup_update(updated)

        updated['participant_a'] = _enrich_participant(updated.get('participant_a'))
        updated['participant_b'] = _enrich_participant(updated.get('participant_b'))

        return _cors_response(200, updated)

    except Exception as e:
        print(f"[update-matchup] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
