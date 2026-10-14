"""
User API - Search Users
Ricerca utenti registrati per username (priorita': match esatto, poi prefix),
poi display_name e family_name (prefix match, case-insensitive) o email
(match esatto). Pensato per il picker partecipanti quando un host crea un
matchup — ritorna solo dati pubblici (user_id, username, display_name,
avatar_url), mai email o stato account. Richiede
autenticazione, ma qualsiasi utente loggato può usarlo (non è un endpoint
admin).
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
usernames_table = dynamodb.Table(os.environ['USERNAMES_TABLE'])

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


def _public_fields(item):
    return {
        'user_id': item['user_id'],
        'username': item.get('username'),
        'display_name': item.get('display_name', ''),
        'avatar_url': item.get('avatar_url'),
    }


def _search_by_email(email, limit):
    # Match esatto: l'email e' hash key dell'indice, quindi non enumera
    # digitando un prefisso (es. "a@") e resta un modo corretto di cercare
    # per email senza mai restituirla in risposta.
    response = user_profiles_table.query(
        IndexName='email-index',
        KeyConditionExpression=Key('email').eq(email),
        Limit=limit,
    )
    return [_public_fields(item) for item in response.get('Items', [])]


def _search_by_username_exact(username_lower):
    # Gli username sono univoci: l'esatto e' una get_item su Usernames
    # + lettura del profilo proprietario, risultato sempre in cima.
    owner = usernames_table.get_item(Key={'username': username_lower}).get('Item')
    if not owner:
        return []
    profile = user_profiles_table.get_item(Key={'user_id': owner['user_id']}).get('Item')
    return [_public_fields(profile)] if profile else []


def _search_by_prefix(index_name, sort_key_name, query_lower, limit):
    response = user_profiles_table.query(
        IndexName=index_name,
        KeyConditionExpression=Key('search_bucket').eq('ALL') & Key(sort_key_name).begins_with(query_lower),
        Limit=limit,
    )
    return [_public_fields(item) for item in response.get('Items', [])]


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

        if '@' in query:
            items = _search_by_email(query, limit)
        else:
            query_lower = query.lower()
            exact = _search_by_username_exact(query_lower)
            by_username = _search_by_prefix('search_bucket-username-index', 'username', query_lower, limit)
            by_name = _search_by_prefix('search_bucket-display_name_lower-index', 'display_name_lower', query_lower, limit)
            by_surname = _search_by_prefix('search_bucket-family_name_lower-index', 'family_name_lower', query_lower, limit)

            seen = set()
            items = []
            for item in exact + by_username + by_name + by_surname:
                if item['user_id'] not in seen:
                    seen.add(item['user_id'])
                    items.append(item)
            items = items[:limit]

        return _cors_response(200, {'items': items, 'count': len(items)})

    except Exception as e:
        print(f"[search-users] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
