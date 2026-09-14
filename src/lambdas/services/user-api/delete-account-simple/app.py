"""
delete-account-simple — Stub API
POST /profile/delete-account-simple

Returns a fixed message confirming that the account will be deleted in 15 days.
This is a temporary placeholder for frontend integration until the full
request-account-deletion flow is wired up.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    logger.info("delete-account-simple invoked")

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps({
            "message": "account marked to be deleted in 15gg"
        }),
    }
