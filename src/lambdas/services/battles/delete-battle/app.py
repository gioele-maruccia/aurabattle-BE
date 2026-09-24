"""
Battles API - Delete Battle
Elimina una battle. Solo l'host può eliminarla.
"""
import json
import os
import boto3

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'DELETE,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        battle_id = event['pathParameters']['battleId']

        existing = battles_table.get_item(Key={'battle_id': battle_id}).get('Item')
        if not existing:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Battle not found'})

        if existing['host_id'] != user_id:
            return _cors_response(403, {'error': 'Forbidden', 'message': 'Only the host can delete this battle'})

        battles_table.delete_item(Key={'battle_id': battle_id})

        try:
            user_profiles_table.update_item(
                Key={'user_id': user_id},
                UpdateExpression='ADD hosted_battles_count :dec',
                ExpressionAttributeValues={':dec': -1}
            )
        except Exception as e:
            print(f"[delete-battle] Warning: could not update hosted_battles_count: {e}")

        return _cors_response(200, {'success': True, 'message': 'Battle deleted successfully'})

    except Exception as e:
        print(f"[delete-battle] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
