"""
Matchups API - Get Matchup
Recupera un singolo matchup. Endpoint pubblico. I partecipanti registrati
vengono arricchiti al volo con username/display_name/avatar_url (letti da
UserProfiles, mai salvati nel matchup: restano sempre aggiornati anche se
l'utente si rinomina dopo la creazione).
"""
import json
import os
import boto3

dynamodb = boto3.resource('dynamodb')
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }


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


def handler(event, context):
    try:
        matchup_id = event['pathParameters']['matchupId']

        matchup = matchups_table.get_item(Key={'matchup_id': matchup_id}).get('Item')
        if not matchup or matchup.get('moderation_state') == 'removed':
            return _cors_response(404, {'error': 'Not Found', 'message': 'Matchup not found'})

        matchup['participant_a'] = _enrich_participant(matchup.get('participant_a'))
        matchup['participant_b'] = _enrich_participant(matchup.get('participant_b'))

        return _cors_response(200, matchup)

    except Exception as e:
        print(f"[get-matchup] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
