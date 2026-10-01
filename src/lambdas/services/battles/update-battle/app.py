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

UPDATABLE_FIELDS = ['title', 'description', 'location', 'latitude', 'longitude', 'event_datetime', 'status', 'cover']
ALLOWED_STATUSES = ['published', 'closed']

ALLOWED_COVERS = {
    'arena', 'crowd', 'soundwave', 'turntable', 'mic',
    'versus', 'city', 'street', 'spark', 'aura',
}


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

        # cover: null (o stringa vuota) e' gestito piu' sotto come REMOVE.
        # Qui valido solo un valore non vuoto contro la whitelist.
        if 'cover' in body and body['cover'] not in (None, ''):
            if not isinstance(body['cover'], str) or body['cover'] not in ALLOWED_COVERS:
                return _cors_response(400, {
                    'error': 'Bad Request',
                    'message': f'cover must be one of: {", ".join(sorted(ALLOWED_COVERS))}'
                })

        update_parts = []
        remove_parts = []
        expr_values = {':now': datetime.utcnow().isoformat() + 'Z'}
        expr_names = {}

        for field in UPDATABLE_FIELDS:
            if field not in body:
                continue

            # `cover: null` (o stringa vuota) significa "togli la copertina".
            if field == 'cover' and (body[field] is None or body[field] == ''):
                expr_names['#cover'] = 'cover'
                remove_parts.append('#cover')
                continue

            expr_names[f'#{field}'] = field
            update_parts.append(f'#{field} = :{field}')
            expr_values[f':{field}'] = body[field]

        if not update_parts and not remove_parts:
            return _cors_response(400, {'error': 'Bad Request', 'message': 'No fields to update'})

        expr_names['#updated_at'] = 'updated_at'
        update_parts.append('#updated_at = :now')

        update_expression = 'SET ' + ', '.join(update_parts)
        if remove_parts:
            update_expression += ' REMOVE ' + ', '.join(remove_parts)

        result = battles_table.update_item(
            Key={'battle_id': battle_id},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names,
            ReturnValues='ALL_NEW',
        )

        return _cors_response(200, result['Attributes'])

    except Exception as e:
        print(f"[update-battle] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
