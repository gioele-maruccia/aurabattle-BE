"""
Weekly Company No-Listing Cron Lambda

Runs every Monday at 08:00 UTC.
Finds company/company_representative users who have NEVER created a job listing
and sends a nudge following an exponential back-off schedule anchored to the
date the user requested their company upgrade (profile_type_changed_at):

    Day 1 → Day 3 → Day 7 → Day 14 → Day 30 → Day 60 → Day 90 (then stop)

Once a user has at least one listing the emails stop regardless of schedule.

DynamoDB tracking field (written after every successful send):
    email_reminders.company: {"count": N, "last_sent": "YYYY-MM-DD"}

Environment variables:
    USER_PROFILES_TABLE   – DynamoDB table
    JOB_LISTINGS_TABLE    – DynamoDB table
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
JOB_LISTINGS_TABLE = os.environ["JOB_LISTINGS_TABLE"]
COMPANIES_TABLE = os.environ["COMPANIES_TABLE"]
SEND_EMAIL_FUNCTION = os.environ["SEND_EMAIL_FUNCTION"]

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")
profiles_table = dynamodb.Table(USER_PROFILES_TABLE)
listings_table = dynamodb.Table(JOB_LISTINGS_TABLE)
companies_table = dynamodb.Table(COMPANIES_TABLE)

from email_templates import build_company_no_listing_email
from reminder_schedule import is_due, reminder_data, build_update_expression

REMINDER_TYPE = "company"


def _get_company_users() -> list[dict]:
    results = []
    scan_kwargs = {
        "ProjectionExpression": "user_id, email, #p, profile_type, created_at, profile_type_changed_at, email_reminders",
        "ExpressionAttributeNames": {"#p": "profile"},
        "FilterExpression": (
            (Attr("profile_type").eq("company") | Attr("profile_type").eq("company_representative"))
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


def _has_listings(user_id: str) -> bool:
    # The companyId stored in job listings is a separate UUID from the user's
    # Cognito sub (user_id). Resolve it from the Companies table first.
    company_resp = companies_table.get_item(
        Key={"userId": user_id},
        ProjectionExpression="companyId",
    )
    company_item = company_resp.get("Item")
    if not company_item:
        # No company record → user hasn't completed company setup → no listings.
        return False
    company_id = company_item.get("companyId")
    if not company_id:
        return False
    resp = listings_table.query(
        IndexName="companyId-createdAt-index",
        KeyConditionExpression=Key("companyId").eq(company_id),
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
    companies = _get_company_users()
    logger.info(f"Evaluating company no-listing reminder for {len(companies)} company users")

    sent = 0
    failed = 0
    skipped_has_listing = 0
    skipped_schedule = 0
    skipped_exhausted = 0

    for company in companies:
        count, _ = reminder_data(company, REMINDER_TYPE)

        if count >= 7:  # MAX_REMINDERS
            skipped_exhausted += 1
            continue

        if _has_listings(company["user_id"]):
            skipped_has_listing += 1
            continue

        if not company["anchor"] or not is_due(company["anchor"], count):
            skipped_schedule += 1
            continue

        subject, html_body = build_company_no_listing_email(company["first_name"])
        ok = _send(company["email"], subject, html_body)
        if ok:
            _mark_sent(company["user_id"], company["email_reminders"], count + 1)
            sent += 1
        else:
            failed += 1

    summary = {
        "total_companies": len(companies),
        "sent": sent,
        "failed": failed,
        "skipped_already_has_listings": skipped_has_listing,
        "skipped_not_due": skipped_schedule,
        "skipped_sequence_complete": skipped_exhausted,
    }
    logger.info(f"Company no-listing batch complete: {summary}")
    return {"statusCode": 200, "body": json.dumps(summary)}
