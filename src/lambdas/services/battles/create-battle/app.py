"""
Battles API - Create Battle
Crea una nuova battle. L'utente autenticato ne diventa l'host.
"""
import json
import os
import uuid
import boto3
from datetime import datetime
from decimal import Decimal, InvalidOperation

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

REQUIRED_FIELDS = ['title', 'event_datetime', 'location', 'latitude', 'longitude']


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'POST,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }


def _parse_coordinate(value, min_value, max_value):
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None
    if decimal_value < min_value or decimal_value > max_value:
        return None
    return decimal_value


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        body = json.loads(event.get('body') or '{}', parse_float=Decimal)

        missing = [f for f in REQUIRED_FIELDS if body.get(f) is None or body.get(f) == '']
        if missing:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': f'Missing required fields: {", ".join(missing)}'
            })

        latitude = _parse_coordinate(body['latitude'], -90, 90)
        if latitude is None:
            return _cors_response(400, {'error': 'Bad Request', 'message': 'latitude must be a number between -90 and 90'})

        longitude = _parse_coordinate(body['longitude'], -180, 180)
        if longitude is None:
            return _cors_response(400, {'error': 'Bad Request', 'message': 'longitude must be a number between -180 and 180'})

        now = datetime.utcnow().isoformat() + 'Z'
        battle_id = str(uuid.uuid4())

        battle = {
            'battle_id': battle_id,
            'host_id': user_id,
            'title': body['title'],
            'description': body.get('description', ''),
            'location': body['location'],
            'latitude': latitude,
            'longitude': longitude,
            'event_datetime': body['event_datetime'],
            'status': 'published',
            'created_at': now,
            'updated_at': now,
        }

        battles_table.put_item(Item=battle)

        # Aggiorna il contatore denormalizzato sul profilo utente (best-effort)
        try:
            user_profiles_table.update_item(
                Key={'user_id': user_id},
                UpdateExpression='ADD hosted_battles_count :inc',
                ExpressionAttributeValues={':inc': 1}
            )
        except Exception as e:
            print(f"[create-battle] Warning: could not update hosted_battles_count: {e}")

        return _cors_response(201, battle)

    except Exception as e:
        print(f"[create-battle] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
