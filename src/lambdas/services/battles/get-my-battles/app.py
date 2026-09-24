"""
Battles API - Get My Battles
Lista le battle create dall'utente autenticato (qualsiasi stato).
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

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
        user_id = event['requestContext']['authorizer']['claims']['sub']

        response = battles_table.query(
            IndexName='host_id-index',
            KeyConditionExpression=Key('host_id').eq(user_id)
        )

        return _cors_response(200, {
            'items': response.get('Items', []),
            'count': response.get('Count', 0),
        })

    except Exception as e:
        print(f"[get-my-battles] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
