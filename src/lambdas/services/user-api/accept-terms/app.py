"""
User API - Accept Terms
POST /v1/profile/accept-terms   body: {"version": "2026-10"}

Registra quale versione dei Termini d'uso l'utente ha accettato e quando.
Il client confronta terms_version_accepted (in GET /profile) con la versione
corrente e, se e' piu' vecchia, chiede di riaccettare.
"""
import json
import os
import re
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

VERSION_PATTERN = re.compile(r'^[0-9A-Za-z._-]{1,20}$')


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


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        body = json.loads(event.get('body') or '{}')

        version = body.get('version')
        if not isinstance(version, str) or not VERSION_PATTERN.match(version):
            return _cors_response(400, {'error': 'Bad Request', 'message': 'version is required (e.g. "2026-10")'})

        now = datetime.utcnow().isoformat() + 'Z'
        try:
            user_profiles_table.update_item(
                Key={'user_id': user_id},
                UpdateExpression='SET terms_version_accepted = :v, terms_accepted_at = :now, updated_at = :now',
                ConditionExpression='attribute_exists(user_id)',
                ExpressionAttributeValues={':v': version, ':now': now},
            )
        except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Profile not found'})

        return _cors_response(200, {'terms_version_accepted': version, 'terms_accepted_at': now})

    except Exception as e:
        print(f"[accept-terms] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
