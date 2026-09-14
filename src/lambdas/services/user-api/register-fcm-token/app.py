"""
User API - Register FCM Token
Registers or updates the Firebase Cloud Messaging token for push notifications.
On first registration for basic users, initialises the retention_state and
schedules T1 of the 3-Touch push notification system.
"""
import json
import os
import boto3
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

SCHEDULER_ROLE_ARN = os.environ.get('SCHEDULER_ROLE_ARN', '')
SEND_RETENTION_PUSH_FUNCTION_ARN = os.environ.get('SEND_RETENTION_PUSH_FUNCTION_ARN', '')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-south-1')

scheduler_client = boto3.client('scheduler', region_name=AWS_REGION)

# Silence window
SILENCE_START_HOUR = 22
SILENCE_END_HOUR = 8
DEFAULT_TZ_OFFSET = 2
TZ_OFFSETS = {
    'Europe/Rome': 2,
    'Europe/London': 1,
    'Europe/Berlin': 2,
    'Europe/Paris': 2,
    'UTC': 0,
}


def _apply_silence_window(dt_utc: datetime, utc_offset: int) -> datetime:
    dt_local = dt_utc + timedelta(hours=utc_offset)
    hour = dt_local.hour
    if hour >= SILENCE_START_HOUR or hour < SILENCE_END_HOUR:
        if hour >= SILENCE_START_HOUR:
            target_date = dt_local.date() + timedelta(days=1)
        else:
            target_date = dt_local.date()
        target_local = datetime(
            target_date.year, target_date.month, target_date.day,
            9, 0, 0, tzinfo=timezone.utc
        ) - timedelta(hours=utc_offset)
        return target_local
    return dt_utc


def _schedule_retention_t1(user_id: str, user_profile: dict) -> None:
    """Schedule T1 retention push (+3h) for a basic user registering FCM token for the first time."""
    if not SCHEDULER_ROLE_ARN or not SEND_RETENTION_PUSH_FUNCTION_ARN:
        logger.warning("Retention scheduler env vars not configured — skipping T1 schedule")
        return

    tz_str = user_profile.get('localization', {}).get('timezone', 'Europe/Rome')
    utc_offset = TZ_OFFSETS.get(tz_str, DEFAULT_TZ_OFFSET)

    now_utc = datetime.now(timezone.utc)
    t1_time = _apply_silence_window(now_utc + timedelta(hours=3), utc_offset)
    job_id = f'task_upgrade_reminder_{user_id}_T1'
    schedule_expression = f"at({t1_time.strftime('%Y-%m-%dT%H:%M:%S')})"

    try:
        scheduler_client.create_schedule(
            Name=job_id,
            ScheduleExpression=schedule_expression,
            ScheduleExpressionTimezone='UTC',
            FlexibleTimeWindow={'Mode': 'OFF'},
            Target={
                'Arn': SEND_RETENTION_PUSH_FUNCTION_ARN,
                'RoleArn': SCHEDULER_ROLE_ARN,
                'Input': json.dumps({'user_id': user_id, 'step': 'T1'}),
            },
            ActionAfterCompletion='DELETE',
        )
        logger.info(f"Scheduled retention T1 for user {user_id} at {t1_time.isoformat()}")
    except scheduler_client.exceptions.ConflictException:
        logger.info(f"Retention T1 job already exists for user {user_id} — skipping")
        return
    except Exception as e:
        logger.error(f"Failed to schedule retention T1 for {user_id}: {e}")
        return

    # Initialise retention_state in DynamoDB
    now_iso = now_utc.isoformat()
    retention_state = {
        'push_enabled': True,
        'completed': False,
        'template_override': None,
        'current_step': 'T1',
        't1_job_id': job_id,
        't2_job_id': None,
        't3_job_id': None,
        't1_scheduled_at': t1_time.isoformat(),
        't2_scheduled_at': None,
        't3_scheduled_at': None,
        't1_sent_at': None,
        't2_sent_at': None,
        't3_sent_at': None,
        'last_event': None,
        'last_event_at': None,
        'initialized_at': now_iso,
    }
    try:
        user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='SET retention_state = :rs',
            ExpressionAttributeValues={':rs': retention_state},
        )
    except Exception as e:
        logger.error(f"Failed to write retention_state for {user_id}: {e}")


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    POST /users/{userId}/fcm-token
    
    Register or update FCM token for push notifications.
    The token can change on each login, so it's updated every time.
    
    Request body:
    {
        "fcm_token": "fcm-device-token-from-firebase"
    }
    """
    try:
        # Get user_id from Cognito JWT token
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Get userId from path parameters
        path_user_id = event['pathParameters']['userId']
        
        # Security: User can only register token for their own profile
        if user_id != path_user_id:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Forbidden',
                    'message': 'You can only register FCM token for your own profile'
                })
            }
        
        # Parse request body
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', {})
        fcm_token = body.get('fcm_token', '').strip()
        
        if not fcm_token:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'fcm_token is required'
                })
            }
        
        # Fetch existing profile to decide whether to initialise retention
        existing_profile_resp = user_profiles_table.get_item(Key={'user_id': user_id})
        existing_profile = existing_profile_resp.get('Item', {})
        is_first_token = not existing_profile.get('fcm_token')
        has_retention = bool(existing_profile.get('retention_state'))

        # Update user profile with new FCM token
        timestamp = datetime.utcnow().isoformat() + 'Z'
        
        user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='SET fcm_token = :token, fcm_token_updated_at = :updated_at',
            ExpressionAttributeValues={
                ':token': fcm_token,
                ':updated_at': timestamp
            },
        )
        
        logger.info(f"FCM token registered for user {user_id}")

        # Schedule retention T1 only on first token registration for basic users
        # (not if retention_state already exists — avoids double-scheduling on reinstall)
        profile_type = existing_profile.get('profile_type', 'basic')
        if is_first_token and not has_retention and profile_type == 'basic':
            _schedule_retention_t1(user_id, existing_profile)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'FCM token registered successfully',
                'user_id': user_id,
                'fcm_token_updated_at': timestamp
            })
        }
    
    except KeyError as e:
        print(f"Missing required field: {e}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'message': f'Missing required field: {str(e)}'
            })
        }
    
    except Exception as e:
        print(f"Error registering FCM token: {e}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': 'Failed to register FCM token'
            })
        }
