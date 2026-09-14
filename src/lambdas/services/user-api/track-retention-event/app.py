"""
User API - Track Retention Event
Receives FE lifecycle events to drive the 3-Touch push notification system.

POST /users/{userId}/retention-event
Authorization: Bearer {CognitoJWT}

Body:
{
    "event_type": "upgrade_flow_started" | "upgrade_flow_abandoned" | "upgrade_flow_completed",
    "timestamp": "2026-04-13T10:30:00Z"   // optional, BE uses server time
}
"""
import json
import os
import sys
import boto3
import logging
from datetime import datetime, timedelta, timezone
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

USER_PROFILES_TABLE = os.environ['USER_PROFILES_TABLE']
SCHEDULER_ROLE_ARN = os.environ['SCHEDULER_ROLE_ARN']
SEND_RETENTION_PUSH_FUNCTION_ARN = os.environ['SEND_RETENTION_PUSH_FUNCTION_ARN']
AWS_REGION = os.environ.get('AWS_REGION', 'eu-south-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
user_profiles_table = dynamodb.Table(USER_PROFILES_TABLE)
scheduler_client = boto3.client('scheduler', region_name=AWS_REGION)

VALID_EVENTS = {'upgrade_flow_started', 'upgrade_flow_abandoned', 'upgrade_flow_completed'}

# Silence window constants (same as send-retention-push)
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


def _cors_response(status_code: int, body: dict) -> dict:
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body),
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


def _get_user_profile(user_id: str) -> dict | None:
    try:
        resp = user_profiles_table.get_item(Key={'user_id': user_id})
        return resp.get('Item')
    except ClientError as e:
        logger.error(f"DynamoDB error fetching user {user_id}: {e}")
        return None


def _cancel_scheduler_job(job_id: str) -> None:
    try:
        scheduler_client.delete_schedule(Name=job_id)
        logger.info(f"Cancelled scheduler job: {job_id}")
    except scheduler_client.exceptions.ResourceNotFoundException:
        logger.info(f"Scheduler job not found (already fired or never existed): {job_id}")
    except ClientError as e:
        logger.warning(f"Could not cancel scheduler job {job_id}: {e}")


def _update_retention_state(user_id: str, updates: dict) -> None:
    """Merge updates into retention_state map atomically.
    Initialises retention_state to {} if the attribute doesn't exist yet,
    then sets each sub-key in the same expression to avoid ValidationException.
    """
    if not updates:
        return

    set_expressions = ['retention_state = if_not_exists(retention_state, :_rs_init)']
    expr_values = {':_rs_init': {}}
    for key, value in updates.items():
        placeholder = f':rs_{key}'
        set_expressions.append(f'retention_state.{key} = {placeholder}')
        expr_values[placeholder] = value

    try:
        user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='SET ' + ', '.join(set_expressions),
            ExpressionAttributeValues=expr_values,
        )
    except ClientError as e:
        logger.error(f"DynamoDB update_retention_state error for {user_id}: {e}")
        raise


def _reschedule_t1(user_id: str, retention: dict, utc_offset: int) -> None:
    """Update the existing T1 scheduler job to fire 3h from now."""
    job_id = retention.get('t1_job_id')
    if not job_id:
        logger.warning(f"No T1 job_id found for user {user_id} — cannot reschedule")
        return

    new_time = datetime.now(timezone.utc) + timedelta(hours=3)
    new_time = _apply_silence_window(new_time, utc_offset)
    schedule_expression = f"at({new_time.strftime('%Y-%m-%dT%H:%M:%S')})"

    try:
        scheduler_client.update_schedule(
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
        logger.info(f"Rescheduled T1 for user {user_id} at {new_time.isoformat()}")
        _update_retention_state(user_id, {'t1_scheduled_at': new_time.isoformat()})
    except scheduler_client.exceptions.ResourceNotFoundException:
        logger.warning(f"T1 job {job_id} not found for rescheduling — may have already fired")
    except ClientError as e:
        logger.error(f"Error rescheduling T1 for {user_id}: {e}")


def _handle_flow_started(user_id: str, retention: dict, user: dict) -> None:
    tz_str = user.get('localization', {}).get('timezone', 'Europe/Rome')
    utc_offset = TZ_OFFSETS.get(tz_str, DEFAULT_TZ_OFFSET)
    now_iso = datetime.now(timezone.utc).isoformat()

    _reschedule_t1(user_id, retention, utc_offset)
    _update_retention_state(user_id, {
        'last_event': 'upgrade_flow_started',
        'last_event_at': now_iso,
    })


def _handle_flow_abandoned(user_id: str, retention: dict) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    _update_retention_state(user_id, {
        'template_override': 'recovery',
        'last_event': 'upgrade_flow_abandoned',
        'last_event_at': now_iso,
    })


def _handle_flow_completed(user_id: str, retention: dict) -> None:
    # KILL SWITCH: cancel all pending scheduler jobs
    for step in ['T1', 'T2', 'T3']:
        job_id = retention.get(f'{step.lower()}_job_id')
        if job_id:
            _cancel_scheduler_job(job_id)

    now_iso = datetime.now(timezone.utc).isoformat()
    _update_retention_state(user_id, {
        'completed': True,
        'current_step': 'done',
        'last_event': 'upgrade_flow_completed',
        'last_event_at': now_iso,
    })


def handler(event: dict, context) -> dict:
    try:
        # Auth: verify user can only track their own events
        user_id = event['requestContext']['authorizer']['claims']['sub']
        path_user_id = event['pathParameters']['userId']

        if user_id != path_user_id:
            return _cors_response(403, {'error': 'Forbidden'})

        # Parse body
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else (event.get('body') or {})
        event_type = body.get('event_type', '').strip()

        if event_type not in VALID_EVENTS:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': f"event_type must be one of: {', '.join(sorted(VALID_EVENTS))}",
            })

        # Load user profile
        user = _get_user_profile(user_id)
        if not user:
            logger.warning(f"User {user_id} not found")
            return _cors_response(404, {'error': 'User not found'})

        retention = user.get('retention_state', {})

        # Already completed — nothing to do (idempotent)
        if retention.get('completed') and event_type != 'upgrade_flow_completed':
            logger.info(f"User {user_id} retention already completed — ignoring event {event_type}")
            return _cors_response(200, {'message': 'acknowledged'})

        logger.info(f"Received retention event '{event_type}' for user {user_id}")

        if event_type == 'upgrade_flow_started':
            _handle_flow_started(user_id, retention, user)
        elif event_type == 'upgrade_flow_abandoned':
            _handle_flow_abandoned(user_id, retention)
        elif event_type == 'upgrade_flow_completed':
            _handle_flow_completed(user_id, retention)

        return _cors_response(200, {'message': 'ok', 'event_type': event_type})

    except KeyError as e:
        logger.error(f"Missing field: {e}")
        return _cors_response(400, {'error': 'Bad Request', 'message': f'Missing field: {e}'})
    except Exception as e:
        logger.error(f"Unexpected error in track-retention-event: {e}", exc_info=True)
        return _cors_response(500, {'error': 'Internal Server Error'})
