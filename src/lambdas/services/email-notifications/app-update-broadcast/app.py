"""
App Update Broadcast Lambda

Triggered manually (or via EventBridge rule enabled on demand) to send
an "app update" email to ALL users in the UserProfiles table.

HOW TO TRIGGER FROM AWS CONSOLE
================================
1. Go to Lambda → {env}-email-app-update-broadcast → Test
2. Provide a JSON payload:
   {
       "version": "2.5.0",
       "notes_html": "<ul><li>Nuova schermata home</li><li>Bug fix notifiche</li></ul>"
   }
3. Click "Test" — that's it.

Alternatively add an EventBridge rule in the future to trigger it automatically
when a new app version is released (e.g. tied to a CodePipeline stage completion).

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
from email_templates import build_app_update_email

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
USER_PROFILES_TABLE = os.environ["USER_PROFILES_TABLE"]
SEND_EMAIL_FUNCTION = os.environ["SEND_EMAIL_FUNCTION"]

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")

profiles_table = dynamodb.Table(USER_PROFILES_TABLE)


def _get_all_active_emails() -> list[dict]:
    """Scan UserProfiles and return list of {email, first_name} for active accounts."""
    results = []
    scan_kwargs = {
        "ProjectionExpression": "user_id, email, #p",
        "ExpressionAttributeNames": {"#p": "profile"},
        "FilterExpression": (
            Attr("account_status").ne("to_be_deleted") | Attr("account_status").not_exists()
        ) & Attr("email").exists(),
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
                results.append({"email": email, "first_name": first_name})
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return results


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
    version = event.get("version", "").strip()
    notes_html = event.get("notes_html", "").strip()

    if not version or not notes_html:
        msg = "Payload must include 'version' and 'notes_html'"
        logger.error(msg)
        return {"statusCode": 400, "body": msg}

    subject, html_body = build_app_update_email(version, notes_html)

    users = _get_all_active_emails()
    logger.info(f"Sending app-update email (v{version}) to {len(users)} users")

    sent = 0
    failed = 0
    for user in users:
        ok = _send(user["email"], subject, html_body)
        if ok:
            sent += 1
        else:
            failed += 1

    summary = {"version": version, "total": len(users), "sent": sent, "failed": failed}
    logger.info(f"Broadcast complete: {summary}")
    return {"statusCode": 200, "body": json.dumps(summary)}
