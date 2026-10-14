"""
User API - Check Username
Verifica formato e disponibilita' di uno username (case-insensitive).
Endpoint pubblico (usato anche in fase di registrazione, prima del login).
Ritorna solo { username, available, reason? }: nessun dato dell'utente.
"""
import json
import os
import re
import boto3

dynamodb = boto3.resource('dynamodb')
usernames_table = dynamodb.Table(os.environ['USERNAMES_TABLE'])

USERNAME_PATTERN = re.compile(r'^[a-z0-9_.]{3,20}$')
RESERVED_USERNAMES = {'admin', 'administrator', 'aurabattle', 'support', 'moderator', 'root', 'system', 'staff'}


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,OPTIONS',
        },
        'body': json.dumps(body),
    }


def handler(event, context):
    try:
        params = event.get('queryStringParameters') or {}
        username = (params.get('u') or '').strip().lower()

        if not USERNAME_PATTERN.match(username):
            return _cors_response(200, {'username': username, 'available': False, 'reason': 'invalid_format'})
        if username in RESERVED_USERNAMES:
            return _cors_response(200, {'username': username, 'available': False, 'reason': 'reserved'})

        taken = usernames_table.get_item(
            Key={'username': username},
            ProjectionExpression='username'
        ).get('Item')
        if taken:
            return _cors_response(200, {'username': username, 'available': False, 'reason': 'taken'})

        return _cors_response(200, {'username': username, 'available': True})

    except Exception as e:
        print(f"[check-username] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
