"""
Matchups API - Create Matchup
Crea una sfida (matchup) dentro una battle. Solo l'host della battle può farlo.
Ogni partecipante è o un utente registrato (participant.user_id) o un ospite
(participant.guest_name) — mutuamente esclusivi. Solo i partecipanti
registrati ricevono aggiornamenti di aura_stats alla chiusura del matchup.
"""
import json
import os
import uuid
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'POST,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }


def _parse_participant(value, label):
    """Valida un partecipante: esattamente uno fra user_id e guest_name.

    Ritorna (participant_dict, errore).
    """
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


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        battle_id = event['pathParameters']['battleId']
        body = json.loads(event.get('body') or '{}')

        battle = battles_table.get_item(Key={'battle_id': battle_id}).get('Item')
        if not battle:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Battle not found'})

        if battle['host_id'] != user_id:
            return _cors_response(403, {'error': 'Forbidden', 'message': 'Only the host can create matchups for this battle'})

        participant_a, error_a = _parse_participant(body.get('participant_a'), 'participant_a')
        if error_a:
            return _cors_response(400, {'error': 'Bad Request', 'message': error_a})

        participant_b, error_b = _parse_participant(body.get('participant_b'), 'participant_b')
        if error_b:
            return _cors_response(400, {'error': 'Bad Request', 'message': error_b})

        now = datetime.utcnow().isoformat() + 'Z'
        matchup_id = str(uuid.uuid4())

        matchup = {
            'matchup_id': matchup_id,
            'battle_id': battle_id,
            'participant_a': participant_a,
            'participant_b': participant_b,
            'votes_a': 0,
            'votes_b': 0,
            'status': 'published',
            'winner': None,
            'created_at': now,
            'updated_at': now,
        }

        matchups_table.put_item(Item=matchup)

        return _cors_response(201, matchup)

    except Exception as e:
        print(f"[create-matchup] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
