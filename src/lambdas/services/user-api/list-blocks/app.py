"""
User API - List Blocks
GET /v1/blocks

Utenti bloccati dall'utente loggato, dal piu' recente, con i soli dati
pubblici (come search-users). Chi nel frattempo ha eliminato l'account
compare senza nome: il client lo mostra come "Utente eliminato".
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
blocks_table = dynamodb.Table(os.environ['USER_BLOCKS_TABLE'])
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


def _query_all_blocks(user_id):
    items = []
    kwargs = {'KeyConditionExpression': Key('blocker_id').eq(user_id)}
    while True:
        response = blocks_table.query(**kwargs)
        items.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            return items
        kwargs['ExclusiveStartKey'] = last_key


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']

        blocks = sorted(_query_all_blocks(user_id), key=lambda b: b.get('created_at', ''), reverse=True)

        items = []
        for block in blocks:
            profile = user_profiles_table.get_item(
                Key={'user_id': block['blocked_id']},
                ProjectionExpression='username, display_name, avatar_url',
            ).get('Item') or {}
            items.append({
                'user_id': block['blocked_id'],
                'username': profile.get('username'),
                'display_name': profile.get('display_name', ''),
                'avatar_url': profile.get('avatar_url'),
                'created_at': block.get('created_at'),
            })

        return _cors_response(200, {'items': items, 'count': len(items)})

    except Exception as e:
        print(f"[list-blocks] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
