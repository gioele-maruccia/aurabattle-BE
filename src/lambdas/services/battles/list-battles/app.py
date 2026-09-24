"""
Battles API - List Battles
Lista pubblica delle battle pubblicate, ordinate per data evento. Endpoint pubblico.
Supporta paginazione via cursore (next_cursor).
"""
import json
import os
import base64
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


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

        result = {
            'items': response.get('Items', []),
            'count': response.get('Count', 0),
        }

        last_evaluated_key = response.get('LastEvaluatedKey')
        if last_evaluated_key:
            result['next_cursor'] = _encode_cursor(last_evaluated_key)

        return _cors_response(200, result)

    except Exception as e:
        print(f"[list-battles] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
