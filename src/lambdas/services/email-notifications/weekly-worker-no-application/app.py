"""
Weekly Worker No-Application Cron Lambda

Runs every Friday at 08:00 UTC.
Finds worker users (profile_type == 'worker' ONLY — basic users receive the
separate upgrade-reminder series) who have NEVER applied to any job listing
and sends a nudge following an exponential back-off schedule anchored to the
date the user requested their worker upgrade (profile_type_changed_at):

    Day 1 → Day 3 → Day 7 → Day 14 → Day 30 → Day 60 → Day 90 (then stop)

Once a user has at least one booking the emails stop regardless of schedule.

DynamoDB tracking field (written after every successful send):
    email_reminders.worker: {"count": N, "last_sent": "YYYY-MM-DD"}

Environment variables:
    USER_PROFILES_TABLE   – DynamoDB table
    BOOKINGS_TABLE        – DynamoDB table  (e.g. dev-be-Bookings)
    SEND_EMAIL_FUNCTION   – ARN/name of send-email Lambda
    ENVIRONMENT           – dev / dev-be / prod
"""

import json
import os
import logging
import boto3
from boto3.dynamodb.conditions import Attr, Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

USER_PROFILES_TABLE = os.environ["USER_PROFILES_TABLE"]
BOOKINGS_TABLE = os.environ["BOOKINGS_TABLE"]
SEND_EMAIL_FUNCTION = os.environ["SEND_EMAIL_FUNCTION"]

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")
profiles_table = dynamodb.Table(USER_PROFILES_TABLE)
bookings_table = dynamodb.Table(BOOKINGS_TABLE)

from email_templates import build_worker_no_application_email
from reminder_schedule import is_due, reminder_data, build_update_expression

REMINDER_TYPE = "worker"


def _get_worker_users() -> list[dict]:
    results = []
    filter_expr = (
        Attr("profile_type").eq("worker")
        & Attr("account_status").ne("to_be_deleted")
        & Attr("email").exists()
    )
    scan_kwargs = {
        "ProjectionExpression": "user_id, email, #p, profile_type, created_at, profile_type_changed_at, email_reminders",
        "ExpressionAttributeNames": {"#p": "profile"},
        "FilterExpression": filter_expr,
    }
    while True:
        resp = profiles_table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            email = item.get("email")
            if email:
                first_name = ""
                profile_data = item.get("profile")
                if isinstance(profile_data, dict):
                    first_name = profile_data.get("given_name", "")
                results.append({
                    "user_id": item["user_id"],
                    "email": email,
                    "first_name": first_name,
                    # Prefer upgrade date; fall back to account creation date.
                    "anchor": item.get("profile_type_changed_at") or item.get("created_at", ""),
                    "email_reminders": item.get("email_reminders"),
                })
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return results


def _has_applied(user_id: str) -> bool:
    resp = bookings_table.query(
        IndexName="workerId-startDate-index",
        KeyConditionExpression=Key("workerId").eq(user_id),
        Limit=1,
        Select="COUNT",
    )
    return resp.get("Count", 0) > 0


def _send(to_email: str, subject: str, html_body: str) -> bool:
    payload = json.dumps({"to": to_email, "subject": subject, "html_body": html_body})
    resp = lambda_client.invoke(
        FunctionName=SEND_EMAIL_FUNCTION,
        InvocationType="RequestResponse",
        Payload=payload.encode(),
    )
    result = json.loads(resp["Payload"].read())
    return result.get("success", False)


def _mark_sent(user_id: str, current_reminders: dict | None, new_count: int) -> None:
    update = build_update_expression(REMINDER_TYPE, new_count, current_reminders)
    profiles_table.update_item(Key={"user_id": user_id}, **update)


def lambda_handler(event, context):
    workers = _get_worker_users()
    logger.info(f"Evaluating worker no-application reminder for {len(workers)} worker users")

    sent = 0
    failed = 0
    skipped_applied = 0
    skipped_schedule = 0
    skipped_exhausted = 0

    for worker in workers:
        count, _ = reminder_data(worker, REMINDER_TYPE)

        if count >= 7:  # MAX_REMINDERS
            skipped_exhausted += 1
            continue

        if _has_applied(worker["user_id"]):
            skipped_applied += 1
            continue

        if not worker["anchor"] or not is_due(worker["anchor"], count):
            skipped_schedule += 1
            continue

        subject, html_body = build_worker_no_application_email(worker["first_name"])
        ok = _send(worker["email"], subject, html_body)
        if ok:
            _mark_sent(worker["user_id"], worker["email_reminders"], count + 1)
            sent += 1
        else:
            failed += 1

    summary = {
        "total_workers": len(workers),
        "sent": sent,
        "failed": failed,
        "skipped_already_applied": skipped_applied,
        "skipped_not_due": skipped_schedule,
        "skipped_sequence_complete": skipped_exhausted,
    }
    logger.info(f"Worker no-application batch complete: {summary}")
    return {"statusCode": 200, "body": json.dumps(summary)}
