"""
Matchups API - Update Matchup
Aggiorna un matchup. Solo l'host della battle può modificarlo.

Alla transizione verso 'closed' (solo la prima volta), il vincitore viene
calcolato automaticamente dai voti correnti:
- più voti A -> 'A', più voti B -> 'B', pari -> 'tie' (nessun winner/loser)
Per ogni partecipante REGISTRATO (user_id, non guest) coinvolto, aggiorna
aura_stats.wins / aura_stats.losses su UserProfiles. I guest non vengono toccati.
"""
import json
import os
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

ALLOWED_STATUSES = ['published', 'live', 'closed']


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
        ProjectionExpression='display_name, avatar_url'
    ).get('Item')
    if not profile:
        return participant
    return {
        **participant,
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

        if 'status' in body and body['status'] not in ALLOWED_STATUSES:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': f'status must be one of: {", ".join(ALLOWED_STATUSES)}'
            })

        update_parts = []
        expr_values = {':now': datetime.utcnow().isoformat() + 'Z'}
        expr_names = {'#updated_at': 'updated_at'}
        update_parts.append('#updated_at = :now')

        if 'participant_a' in body:
            participant_a, error = _parse_participant(body['participant_a'], 'participant_a')
            if error:
                return _cors_response(400, {'error': 'Bad Request', 'message': error})
            expr_names['#participant_a'] = 'participant_a'
            update_parts.append('#participant_a = :participant_a')
            expr_values[':participant_a'] = participant_a

        if 'participant_b' in body:
            participant_b, error = _parse_participant(body['participant_b'], 'participant_b')
            if error:
                return _cors_response(400, {'error': 'Bad Request', 'message': error})
            expr_names['#participant_b'] = 'participant_b'
            update_parts.append('#participant_b = :participant_b')
            expr_values[':participant_b'] = participant_b

        closing_now = body.get('status') == 'closed' and existing.get('status') != 'closed'

        if 'status' in body:
            expr_names['#status'] = 'status'
            update_parts.append('#status = :status')
            expr_values[':status'] = body['status']

        if closing_now:
            votes_a = int(existing.get('votes_a', 0))
            votes_b = int(existing.get('votes_b', 0))

            if votes_a > votes_b:
                winner = 'A'
            elif votes_b > votes_a:
                winner = 'B'
            else:
                winner = 'tie'

            expr_names['#winner'] = 'winner'
            update_parts.append('#winner = :winner')
            expr_values[':winner'] = winner

            if winner != 'tie':
                winning_participant = existing['participant_a'] if winner == 'A' else existing['participant_b']
                losing_participant = existing['participant_b'] if winner == 'A' else existing['participant_a']

                if 'user_id' in winning_participant:
                    _apply_stat(winning_participant['user_id'], 'wins')
                if 'user_id' in losing_participant:
                    _apply_stat(losing_participant['user_id'], 'losses')

        result = matchups_table.update_item(
            Key={'matchup_id': matchup_id},
            UpdateExpression='SET ' + ', '.join(update_parts),
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names,
            ReturnValues='ALL_NEW',
        )

        updated = result['Attributes']
        updated['participant_a'] = _enrich_participant(updated.get('participant_a'))
        updated['participant_b'] = _enrich_participant(updated.get('participant_b'))

        return _cors_response(200, updated)

    except Exception as e:
        print(f"[update-matchup] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
