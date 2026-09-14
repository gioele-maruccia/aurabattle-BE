"""
Weekly Upgrade Reminder Cron Lambda

Runs every Thursday at 09:00 UTC.
Sends a "upgrade to Premium" email to basic users following an exponential
back-off schedule anchored to the user's account creation date:

    Day 1 → Day 3 → Day 7 → Day 14 → Day 30 → Day 60 → Day 90 (then stop)

Only basic users are targeted (worker/company users receive their own
reminder series from separate Lambdas).

DynamoDB tracking field (written after every successful send):
    email_reminders.upgrade: {"count": N, "last_sent": "YYYY-MM-DD"}

Environment variables:
    USER_PROFILES_TABLE   – DynamoDB table name
    SEND_EMAIL_FUNCTION   – ARN/name of the send-email Lambda
    ENVIRONMENT           – dev / dev-be / prod
"""

import json
import os
import logging
import boto3
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)

USER_PROFILES_TABLE = os.environ["USER_PROFILES_TABLE"]
SEND_EMAIL_FUNCTION = os.environ["SEND_EMAIL_FUNCTION"]

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")
profiles_table = dynamodb.Table(USER_PROFILES_TABLE)

from email_templates import build_upgrade_reminder_email
from reminder_schedule import is_due, reminder_data, build_update_expression

REMINDER_TYPE = "upgrade"


def _get_basic_users() -> list[dict]:
    results = []
    scan_kwargs = {
        "ProjectionExpression": "user_id, email, #p, created_at, email_reminders",
        "ExpressionAttributeNames": {"#p": "profile"},
        "FilterExpression": (
            Attr("profile_type").eq("basic")
            & Attr("account_status").ne("to_be_deleted")
            & Attr("email").exists()
        ),
    }
    while True:
        resp = profiles_table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            email = item.get("email")
            if email:
                first_name = ""
                profile = item.get("profile")
                if isinstance(profile, dict):
                    first_name = profile.get("given_name", "")
                results.append({
                    "user_id": item["user_id"],
                    "email": email,
                    "first_name": first_name,
                    "created_at": item.get("created_at", ""),
                    "email_reminders": item.get("email_reminders"),
                })
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return results


def _mark_sent(user_id: str, current_reminders: dict | None, new_count: int) -> None:
    update = build_update_expression(REMINDER_TYPE, new_count, current_reminders)
    profiles_table.update_item(Key={"user_id": user_id}, **update)


def _send(to_email: str, subject: str, html_body: str) -> bool:
    payload = json.dumps({"to": to_email, "subject": subject, "html_body": html_body})
    resp = lambda_client.invoke(
        FunctionName=SEND_EMAIL_FUNCTION,
        InvocationType="RequestResponse",
        Payload=payload.encode(),
    )
    result = json.loads(resp["Payload"].read())
    return result.get("success", False)


def lambda_handler(event, context):
    users = _get_basic_users()
    logger.info(f"Evaluating upgrade reminder for {len(users)} basic users")

    sent = 0
    failed = 0
    skipped_schedule = 0
    skipped_exhausted = 0

    for user in users:
        count, _ = reminder_data(user, REMINDER_TYPE)

        if count >= 7:  # MAX_REMINDERS
            skipped_exhausted += 1
            continue

        anchor = user.get("created_at", "")
        if not anchor or not is_due(anchor, count):
            skipped_schedule += 1
            continue

        subject, html_body = build_upgrade_reminder_email(user["first_name"])
        ok = _send(user["email"], subject, html_body)
        if ok:
            _mark_sent(user["user_id"], user["email_reminders"], count + 1)
            sent += 1
        else:
            failed += 1

    summary = {
        "total": len(users),
        "sent": sent,
        "failed": failed,
        "skipped_not_due": skipped_schedule,
        "skipped_sequence_complete": skipped_exhausted,
    }
    logger.info(f"Upgrade reminder batch complete: {summary}")
    return {"statusCode": 200, "body": json.dumps(summary)}
