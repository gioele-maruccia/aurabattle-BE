"""
Battles API - Update Battle
Aggiorna una battle. Solo l'host può modificarla.
"""
import json
import os
import boto3
from datetime import datetime
from decimal import Decimal, InvalidOperation

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])

UPDATABLE_FIELDS = ['title', 'description', 'location', 'latitude', 'longitude', 'event_datetime', 'status']
ALLOWED_STATUSES = ['published', 'closed']


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'PUT,OPTIONS',
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
        battle_id = event['pathParameters']['battleId']
        body = json.loads(event.get('body') or '{}', parse_float=Decimal)

        existing = battles_table.get_item(Key={'battle_id': battle_id}).get('Item')
        if not existing:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Battle not found'})

        if existing['host_id'] != user_id:
            return _cors_response(403, {'error': 'Forbidden', 'message': 'Only the host can update this battle'})

        if 'status' in body and body['status'] not in ALLOWED_STATUSES:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': f'status must be one of: {", ".join(ALLOWED_STATUSES)}'
            })

        if 'latitude' in body:
            latitude = _parse_coordinate(body['latitude'], -90, 90)
            if latitude is None:
                return _cors_response(400, {'error': 'Bad Request', 'message': 'latitude must be a number between -90 and 90'})
            body['latitude'] = latitude

        if 'longitude' in body:
            longitude = _parse_coordinate(body['longitude'], -180, 180)
            if longitude is None:
                return _cors_response(400, {'error': 'Bad Request', 'message': 'longitude must be a number between -180 and 180'})
            body['longitude'] = longitude

        update_parts = []
        expr_values = {':now': datetime.utcnow().isoformat() + 'Z'}
        expr_names = {}

        for field in UPDATABLE_FIELDS:
            if field in body:
                placeholder = f'#{field}' if field == 'status' else field
                if field == 'status':
                    expr_names['#status'] = 'status'
                update_parts.append(f'{placeholder} = :{field}')
                expr_values[f':{field}'] = body[field]

        if not update_parts:
            return _cors_response(400, {'error': 'Bad Request', 'message': 'No fields to update'})

        update_parts.append('updated_at = :now')

        kwargs = {
            'Key': {'battle_id': battle_id},
            'UpdateExpression': 'SET ' + ', '.join(update_parts),
            'ExpressionAttributeValues': expr_values,
            'ReturnValues': 'ALL_NEW',
        }
        if expr_names:
            kwargs['ExpressionAttributeNames'] = expr_names

        result = battles_table.update_item(**kwargs)

        return _cors_response(200, result['Attributes'])

    except Exception as e:
        print(f"[update-battle] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
