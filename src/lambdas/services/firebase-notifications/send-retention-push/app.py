"""
Firebase Notifications - Send Retention Push
Triggered by EventBridge Scheduler for T1, T2, T3 retention push notification steps.

Event payload (from Scheduler):
{
    "user_id": "cognito-sub-uuid",
    "step": "T1"   # "T1", "T2", "T3"
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

# Firebase layer import (required — this Lambda exists only to send pushes)
sys.path.append('/opt/python')
try:
    from firebase_notifications import send_notification
    FIREBASE_AVAILABLE = True
except ImportError:
    logger.error("Firebase layer not available — push notifications disabled")
    FIREBASE_AVAILABLE = False

USER_PROFILES_TABLE = os.environ['USER_PROFILES_TABLE']
SCHEDULER_ROLE_ARN = os.environ['SCHEDULER_ROLE_ARN']
SEND_RETENTION_PUSH_FUNCTION_ARN = os.environ['SEND_RETENTION_PUSH_FUNCTION_ARN']
AWS_REGION = os.environ.get('AWS_REGION', 'eu-south-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
user_profiles_table = dynamodb.Table(USER_PROFILES_TABLE)
scheduler_client = boto3.client('scheduler', region_name=AWS_REGION)

# Silence window: 22:00 – 08:00 local time (no pytz in layer, use UTC offset heuristic)
SILENCE_START_HOUR = 22  # 22:00 local
SILENCE_END_HOUR = 8     # 08:00 local
DEFAULT_TIMEZONE_OFFSET = 2  # CEST +2 (Italy summer); fallback

# Step timing
STEP_DELAYS = {
    'T1': None,          # T1 is scheduled externally (not from here)
    'T2': timedelta(hours=24),
    'T3': timedelta(hours=72),
}

# Push copy — Italian
PUSH_TEMPLATES = {
    'T1': {
        'default': {
            'title': 'Serve aiuto con i dati aziendali?',
            'body': 'Registra la tua azienda su BeeBusy e inizia a trovare personale qualificato.',
        },
        'recovery': {
            'title': 'Hai bisogno di aiuto per completare la registrazione?',
            'body': 'Siamo qui per supportarti. Riprendi da dove hai lasciato.',
        },
    },
    'T2': {
        'default': {
            'title': 'Registrati ora per sbloccare i report avanzati',
            'body': "È il modo più veloce per trovare il personale giusto. Non aspettare.",
        },
        'recovery': {
            'title': 'Registrati ora per sbloccare i report avanzati',
            'body': "È il modo più veloce per trovare il personale giusto. Non aspettare.",
        },
    },
    'T3': {
        'default': {
            'title': "Cosa manca nell'app per la tua azienda?",
            'body': 'Dicci la tua, ci aiuta a crescere.',
        },
        'recovery': {
            'title': "Cosa manca nell'app per la tua azienda?",
            'body': 'Dicci la tua, ci aiuta a crescere.',
        },
    },
}

STEP_VARIANTS = {
    'T1': 'default',           # overridden by template_override
    'T2': 'benefit_fomo',
    'T3': 'feedback_validation',
}


def _apply_silence_window(dt_utc: datetime, utc_offset_hours: int) -> datetime:
    """Shift dt_utc to 09:00 local if it falls in the silence window (22:00–08:00 local)."""
    dt_local = dt_utc + timedelta(hours=utc_offset_hours)
    hour = dt_local.hour
    if hour >= SILENCE_START_HOUR or hour < SILENCE_END_HOUR:
        if hour >= SILENCE_START_HOUR:
            target_date = dt_local.date() + timedelta(days=1)
        else:
            target_date = dt_local.date()
        target_local = datetime(
            target_date.year, target_date.month, target_date.day,
            9, 0, 0, tzinfo=timezone.utc
        ) - timedelta(hours=utc_offset_hours)
        return target_local
    return dt_utc


def _get_utc_offset(timezone_str: str) -> int:
    """Very simple UTC offset resolver for Italy only — expand if needed."""
    # Italy: CET +1 (winter), CEST +2 (summer)
    # For simplicity use +2 (CEST) as default since most activity is summer
    tz_offsets = {
        'Europe/Rome': 2,
        'Europe/London': 1,
        'Europe/Berlin': 2,
        'Europe/Paris': 2,
        'UTC': 0,
    }
    return tz_offsets.get(timezone_str or 'Europe/Rome', DEFAULT_TIMEZONE_OFFSET)


def _get_user_profile(user_id: str) -> dict | None:
    try:
        resp = user_profiles_table.get_item(Key={'user_id': user_id})
        return resp.get('Item')
    except ClientError as e:
        logger.error(f"DynamoDB error fetching user {user_id}: {e}")
        return None


def _mark_step_sent(user_id: str, step: str, retention: dict) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    step_key = step.lower()
    try:
        new_retention = dict(retention)
        new_retention[f'{step_key}_sent_at'] = now_iso
        new_retention['current_step'] = step
        user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='SET retention_state = :rs',
            ExpressionAttributeValues={':rs': new_retention},
        )
    except ClientError as e:
        logger.error(f"DynamoDB error marking step sent for {user_id}: {e}")


def _schedule_next_step(user_id: str, current_step: str, retention: dict) -> None:
    next_map = {'T1': 'T2', 'T2': 'T3', 'T3': None}
    next_step = next_map.get(current_step)
    if not next_step:
        logger.info(f"No next step after {current_step} for user {user_id}")
        # Mark as done
        try:
            new_retention = dict(retention)
            new_retention['current_step'] = 'done'
            user_profiles_table.update_item(
                Key={'user_id': user_id},
                UpdateExpression='SET retention_state = :rs',
                ExpressionAttributeValues={':rs': new_retention},
            )
        except ClientError as e:
            logger.error(f"DynamoDB error marking done for {user_id}: {e}")
        return

    delay = STEP_DELAYS[next_step]
    now_utc = datetime.now(timezone.utc)
    scheduled_utc = now_utc + delay

    # Apply silence window
    user_profile_for_tz = _get_user_profile(user_id)
    tz_str = (user_profile_for_tz or {}).get('localization', {}).get('timezone', 'Europe/Rome')
    utc_offset = _get_utc_offset(tz_str)
    scheduled_utc = _apply_silence_window(scheduled_utc, utc_offset)

    job_id = f'task_upgrade_reminder_{user_id}_{next_step}'
    schedule_expression = f"at({scheduled_utc.strftime('%Y-%m-%dT%H:%M:%S')})"

    try:
        scheduler_client.create_schedule(
            Name=job_id,
            ScheduleExpression=schedule_expression,
            ScheduleExpressionTimezone='UTC',
            FlexibleTimeWindow={'Mode': 'OFF'},
            Target={
                'Arn': SEND_RETENTION_PUSH_FUNCTION_ARN,
                'RoleArn': SCHEDULER_ROLE_ARN,
                'Input': json.dumps({'user_id': user_id, 'step': next_step}),
            },
            ActionAfterCompletion='DELETE',
        )
        logger.info(f"Scheduled {next_step} for user {user_id} at {scheduled_utc.isoformat()}")

        # Update retention_state with next job info
        new_retention = dict(retention)
        step_key = next_step.lower()
        new_retention[f'{step_key}_job_id'] = job_id
        new_retention[f'{step_key}_scheduled_at'] = scheduled_utc.isoformat()
        user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='SET retention_state = :rs',
            ExpressionAttributeValues={':rs': new_retention},
        )
    except scheduler_client.exceptions.ConflictException:
        logger.warning(f"Scheduler job {job_id} already exists — skipping")
    except ClientError as e:
        logger.error(f"Scheduler error for {user_id} {next_step}: {e}")


def _handle_invalid_token(user_id: str) -> None:
    """Remove invalid FCM token to avoid future failed sends."""
    try:
        user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='REMOVE fcm_token',
        )
        logger.info(f"Removed invalid FCM token for user {user_id}")
    except ClientError as e:
        logger.error(f"Error removing FCM token for {user_id}: {e}")


def lambda_handler(event: dict, context) -> None:
    user_id = event.get('user_id')
    step = event.get('step')  # "T1", "T2", "T3"

    if not user_id or not step:
        logger.error(f"Missing user_id or step in event: {event}")
        return

    logger.info(f"Processing retention push {step} for user {user_id}")

    # 1. Fetch user profile
    user = _get_user_profile(user_id)
    if not user:
        logger.warning(f"User {user_id} not found — skipping retention push")
        return

    retention = user.get('retention_state', {})

    # 2. Kill switch check
    if retention.get('completed'):
        logger.info(f"User {user_id} completed upgrade — skipping push")
        return

    # Also check profile_type: if already "company" (upgraded without sending event), skip
    if user.get('profile_type') == 'company':
        logger.info(f"User {user_id} is already a company — skipping retention push")
        return

    # 3. Push preferences check
    notif_prefs = user.get('notification_preferences', {})
    if notif_prefs.get('push_enabled') is False:
        logger.info(f"User {user_id} has push disabled — skipping")
        return

    # 4. FCM token check
    fcm_token = user.get('fcm_token')
    if not fcm_token:
        logger.info(f"User {user_id} has no FCM token — skipping push")
        return

    if not FIREBASE_AVAILABLE:
        logger.error("Firebase not available — cannot send push")
        return

    # 5. Determine template and variant
    template_override = retention.get('template_override')
    variant = template_override if (step == 'T1' and template_override) else STEP_VARIANTS.get(step, 'default')

    step_templates = PUSH_TEMPLATES.get(step, {})
    copy = step_templates.get(variant) or step_templates.get('default', {})
    title = copy.get('title', 'BeeBusy')
    body = copy.get('body', '')

    # 6. Send push
    success = send_notification(
        fcm_token=fcm_token,
        title=title,
        body=body,
        data={
            'actionType': 'upgrade_reminder',
            'step': step,
            'variant': variant,
            'deepLinkTarget': 'company_registration',
        },
    )

    if not success:
        # Check if it might be an invalid token (best effort — firebase_notifications already logs)
        logger.warning(f"Push failed for user {user_id} step {step}")
        # We still schedule next step: token may be temporarily unavailable
    else:
        logger.info(f"Retention push {step} sent to user {user_id} (variant={variant})")

    # 7. Mark step sent + schedule next step
    _mark_step_sent(user_id, step, retention)
    _schedule_next_step(user_id, step, retention)
