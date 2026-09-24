"""
User API - Add Battle Bookmark
Salva una battle nei bookmark dell'utente autenticato.
"""
import json
import os
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])


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


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        battle_id = event['pathParameters']['battleId']

        battle = battles_table.get_item(Key={'battle_id': battle_id}).get('Item')
        if not battle:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Battle not found'})

        profile = user_profiles_table.get_item(Key={'user_id': user_id}).get('Item')
        if not profile:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Profile not found'})

        bookmarks = profile.get('bookmarked_battles', [])
        if battle_id not in bookmarks:
            bookmarks.append(battle_id)
            user_profiles_table.update_item(
                Key={'user_id': user_id},
                UpdateExpression='SET bookmarked_battles = :bookmarks, updated_at = :now',
                ExpressionAttributeValues={
                    ':bookmarks': bookmarks,
                    ':now': datetime.utcnow().isoformat() + 'Z',
                }
            )

        return _cors_response(200, {'success': True, 'bookmarked_battles': bookmarks})

    except Exception as e:
        print(f"[add-bookmark] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
