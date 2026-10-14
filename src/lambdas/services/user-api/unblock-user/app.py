"""
User API - Unblock User
DELETE /v1/blocks/{userId}

Sblocca un utente. Idempotente: sbloccare chi non era bloccato risponde 200.
La segnalazione creata al momento del blocco resta: la decisione sul
contenuto spetta comunque al super admin.
"""
import json
import os
import boto3

dynamodb = boto3.resource('dynamodb')
blocks_table = dynamodb.Table(os.environ['USER_BLOCKS_TABLE'])


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
        blocked_id = event['pathParameters']['userId']

        blocks_table.delete_item(Key={'blocker_id': user_id, 'blocked_id': blocked_id})

        return _cors_response(200, {'success': True})

    except Exception as e:
        print(f"[unblock-user] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
