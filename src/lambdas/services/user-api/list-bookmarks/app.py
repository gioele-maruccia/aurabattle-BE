"""
User API - List Battle Bookmarks
Recupera le battle salvate nei bookmark dell'utente autenticato (dati completi).
"""
import json
import os
import boto3

dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
battles_table_name = os.environ['BATTLES_TABLE']

BATCH_SIZE = 100  # limite di BatchGetItem


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


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']

        profile = user_profiles_table.get_item(Key={'user_id': user_id}).get('Item')
        bookmark_ids = (profile or {}).get('bookmarked_battles', [])

        if not bookmark_ids:
            return _cors_response(200, {'items': [], 'count': 0})

        battles = []
        for i in range(0, len(bookmark_ids), BATCH_SIZE):
            chunk = bookmark_ids[i:i + BATCH_SIZE]
            response = dynamodb.batch_get_item(
                RequestItems={
                    battles_table_name: {
                        'Keys': [{'battle_id': bid} for bid in chunk]
                    }
                }
            )
            battles.extend(response.get('Responses', {}).get(battles_table_name, []))

        return _cors_response(200, {'items': battles, 'count': len(battles)})

    except Exception as e:
        print(f"[list-bookmarks] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
