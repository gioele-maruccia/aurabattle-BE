"""
User API - Search Users
Ricerca utenti registrati per display_name (prefix match, case-insensitive).
Pensato per il picker partecipanti quando un host crea un matchup — ritorna
solo dati pubblici (user_id, display_name, avatar_url), mai email o stato
account. Richiede autenticazione, ma qualsiasi utente loggato può usarlo
(non è un endpoint admin).
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

MIN_QUERY_LENGTH = 2
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


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
        params = event.get('queryStringParameters') or {}
        query = (params.get('q') or '').strip()

        if len(query) < MIN_QUERY_LENGTH:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': f'q must be at least {MIN_QUERY_LENGTH} characters'
            })

        try:
            limit = min(int(params.get('limit', DEFAULT_LIMIT)), MAX_LIMIT)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT

        query_lower = query.lower()

        response = user_profiles_table.query(
            IndexName='search_bucket-display_name_lower-index',
            KeyConditionExpression=Key('search_bucket').eq('ALL') & Key('display_name_lower').begins_with(query_lower),
            Limit=limit,
        )

        items = [
            {
                'user_id': item['user_id'],
                'display_name': item.get('display_name', ''),
                'avatar_url': item.get('avatar_url'),
            }
            for item in response.get('Items', [])
        ]

        return _cors_response(200, {'items': items, 'count': len(items)})

    except Exception as e:
        print(f"[search-users] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
