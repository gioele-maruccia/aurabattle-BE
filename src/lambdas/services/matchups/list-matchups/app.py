"""
Matchups API - List Matchups
Lista i matchup di una battle. Endpoint pubblico. I partecipanti registrati
vengono arricchiti al volo con username/display_name/avatar_url (vedi get-matchup).
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

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


def _enrich_participant(participant, profiles_cache):
    if not participant or 'user_id' not in participant:
        return participant
    user_id = participant['user_id']
    if user_id not in profiles_cache:
        profiles_cache[user_id] = user_profiles_table.get_item(
            Key={'user_id': user_id},
            ProjectionExpression='username, display_name, avatar_url'
        ).get('Item')
    profile = profiles_cache[user_id]
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
        battle_id = event['pathParameters']['battleId']

        response = matchups_table.query(
            IndexName='battle_id-index',
            KeyConditionExpression=Key('battle_id').eq(battle_id)
        )

        items = sorted(response.get('Items', []), key=lambda m: m.get('created_at', ''))

        # Cache per evitare letture ripetute dello stesso profilo in piu' matchup
        profiles_cache = {}
        for item in items:
            item['participant_a'] = _enrich_participant(item.get('participant_a'), profiles_cache)
            item['participant_b'] = _enrich_participant(item.get('participant_b'), profiles_cache)

        return _cors_response(200, {'items': items, 'count': len(items)})

    except Exception as e:
        print(f"[list-matchups] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
