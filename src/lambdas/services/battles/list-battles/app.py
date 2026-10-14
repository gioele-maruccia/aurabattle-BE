"""
Battles API - List Battles
Lista pubblica delle battle live e pubblicate. Endpoint pubblico.
Esclude le battle rimosse dal super admin (moderation_state = 'removed').
Le battle live sono sempre in testa (restituite solo nella prima pagina, sono poche);
le published sono ordinate per data evento e paginate via cursore (next_cursor).
"""
import json
import os
import base64
import boto3
from boto3.dynamodb.conditions import Attr, Key

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# Le battle rimosse dal super admin non compaiono. Il filtro si applica dopo
# il Limit, quindi una pagina puo' avere meno elementi: il cursore resta
# corretto.
VISIBLE = Attr('moderation_state').not_exists() | Attr('moderation_state').ne('removed')


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


def _encode_cursor(last_evaluated_key):
    raw = json.dumps(last_evaluated_key).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('utf-8')


def _decode_cursor(cursor):
    raw = base64.urlsafe_b64decode(cursor.encode('utf-8'))
    return json.loads(raw)


def _query_all_live():
    """Tutte le battle in stato live, ordinate per data evento."""
    items = []
    kwargs = {
        'IndexName': 'status-event_datetime-index',
        'KeyConditionExpression': Key('status').eq('live'),
        'FilterExpression': VISIBLE,
        'ScanIndexForward': True,
    }
    while True:
        response = battles_table.query(**kwargs)
        items.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            return items
        kwargs['ExclusiveStartKey'] = last_key


def handler(event, context):
    try:
        params = event.get('queryStringParameters') or {}

        try:
            limit = min(int(params.get('limit', DEFAULT_LIMIT)), MAX_LIMIT)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT

        query_kwargs = {
            'IndexName': 'status-event_datetime-index',
            'KeyConditionExpression': Key('status').eq('published'),
            'FilterExpression': VISIBLE,
            'Limit': limit,
            'ScanIndexForward': True,  # dalla più vicina alla più lontana nel tempo
        }

        cursor = params.get('cursor')
        if cursor:
            try:
                query_kwargs['ExclusiveStartKey'] = _decode_cursor(cursor)
            except Exception:
                return _cors_response(400, {'error': 'Bad Request', 'message': 'Invalid cursor'})

        response = battles_table.query(**query_kwargs)

        # Le live vanno solo nella prima pagina, davanti alle published
        live_items = _query_all_live() if not cursor else []
        items = live_items + response.get('Items', [])

        result = {
            'items': items,
            'count': len(items),
        }

        last_evaluated_key = response.get('LastEvaluatedKey')
        if last_evaluated_key:
            result['next_cursor'] = _encode_cursor(last_evaluated_key)

        return _cors_response(200, result)

    except Exception as e:
        print(f"[list-battles] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
