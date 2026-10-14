"""
User API - Block User
PUT /v1/blocks/{userId}

Blocca un utente. Idempotente. Il blocco agisce solo su cosa vede chi blocca
(il client nasconde battle e matchup del bloccato; search-users e i matchup
ne tengono conto): non e' un'azione di moderazione.

Apple chiede che il blocco avvisi anche il team: per questo ogni blocco crea
una segnalazione (reason=blocked) che il super admin vede nel backoffice.
"""
import hashlib
import json
import os
import boto3
from datetime import datetime
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
blocks_table = dynamodb.Table(os.environ['USER_BLOCKS_TABLE'])
reports_table = dynamodb.Table(os.environ['REPORTS_TABLE'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])


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


def _report_block(blocker_id, blocked_profile, now):
    """Segnalazione automatica del blocco. Ha un'identita' diversa da una
    segnalazione "a mano" della stessa persona, cosi' le due non si
    sovrascrivono e il super admin le vede entrambe."""
    blocked_id = blocked_profile['user_id']
    target_key = f'user#{blocked_id}'
    identity = f'{target_key}||user#{blocker_id}|blocked'
    report_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]
    try:
        reports_table.put_item(
            Item={
                'report_id': report_id,
                'target_type': 'user',
                'target_id': blocked_id,
                'target_key': target_key,
                'target_owner_id': blocked_id,
                'reason': 'blocked',
                'status': 'open',
                'reporter_id': blocker_id,
                'snapshot': {
                    'username': blocked_profile.get('username'),
                    'display_name': blocked_profile.get('display_name'),
                    'avatar_url': blocked_profile.get('avatar_url'),
                },
                'created_at': now,
            },
            ConditionExpression='attribute_not_exists(report_id) OR #status <> :open',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':open': 'open'},
        )
    except ClientError as e:
        if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
            raise


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        blocked_id = event['pathParameters']['userId']

        if blocked_id == user_id:
            return _cors_response(400, {'error': 'Bad Request', 'message': 'You cannot block yourself'})

        profile = user_profiles_table.get_item(Key={'user_id': blocked_id}).get('Item')
        if not profile:
            return _cors_response(404, {'error': 'Not Found', 'message': 'User not found'})

        now = datetime.utcnow().isoformat() + 'Z'

        try:
            blocks_table.put_item(
                Item={'blocker_id': user_id, 'blocked_id': blocked_id, 'created_at': now},
                ConditionExpression='attribute_not_exists(blocked_id)',
            )
            created = True
        except ClientError as e:
            if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                raise
            created = False

        if created:
            _report_block(user_id, profile, now)

        return _cors_response(200, {
            'user_id': blocked_id,
            'username': profile.get('username'),
            'display_name': profile.get('display_name', ''),
            'avatar_url': profile.get('avatar_url'),
            'created_at': now,
        })

    except Exception as e:
        print(f"[block-user] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
