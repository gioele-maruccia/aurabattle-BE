"""
Battles API - Get Battle
Recupera una singola battle per ID. Endpoint pubblico (nessuna auth richiesta).
"""
import json
import os
import boto3

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])


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
        battle_id = event['pathParameters']['battleId']

        response = battles_table.get_item(Key={'battle_id': battle_id})
        battle = response.get('Item')

        if not battle:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Battle not found'})

        return _cors_response(200, battle)

    except Exception as e:
        print(f"[get-battle] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
