"""
delete-account-simple — Richiesta di eliminazione account
POST /profile/delete-account-simple

Non cancella nulla: registra la richiesta (account_status =
'deletion_requested', deletion_requested_at). Il super admin la vede nel
backoffice e cancella l'account a mano entro 15 giorni (utente Cognito e
profilo), poi la segna come eseguita.

Idempotente: una seconda richiesta non sposta la data della prima.
"""

import json
import os
import logging
import boto3
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

DELETION_DAYS = 15


def _cors_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        now = datetime.utcnow().isoformat() + 'Z'

        try:
            user_profiles_table.update_item(
                Key={'user_id': user_id},
                UpdateExpression=(
                    'SET account_status = :requested, updated_at = :now, '
                    'deletion_requested_at = if_not_exists(deletion_requested_at, :now)'
                ),
                ConditionExpression='attribute_exists(user_id)',
                ExpressionAttributeValues={':requested': 'deletion_requested', ':now': now},
            )
        except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Profile not found'})

        logger.info(f"delete-account-simple: deletion requested for {user_id}")

        return _cors_response(200, {
            "message": f"account marked to be deleted in {DELETION_DAYS}gg",
            "deletion_days": DELETION_DAYS,
        })

    except Exception as e:
        logger.error(f"delete-account-simple error: {e}", exc_info=True)
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
