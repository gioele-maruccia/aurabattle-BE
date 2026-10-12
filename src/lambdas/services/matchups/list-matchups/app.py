"""
Matchups API - List Matchups
Lista i matchup di una battle. Endpoint pubblico.
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])


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

        response = matchups_table.query(
            IndexName='battle_id-index',
            KeyConditionExpression=Key('battle_id').eq(battle_id)
        )

        items = sorted(response.get('Items', []), key=lambda m: m.get('created_at', ''))

        return _cors_response(200, {'items': items, 'count': len(items)})

    except Exception as e:
        print(f"[list-matchups] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
