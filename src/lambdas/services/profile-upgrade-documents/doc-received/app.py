import os
import json
import logging
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import boto3

dynamodb = boto3.client("dynamodb")
lambda_client = boto3.client('lambda', region_name="eu-south-1")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
DOC_SCAN_FUNCTION_NAME = os.environ['DOC_SCAN_FUNCTION_NAME']

def _parse_pk_sk_from_key(s3_key: str):
    """
    Example S3 key:
      docs/USER123/1757399658891_id_card_front.png

    Returns:
      pk = USER#USER123
      sk = DOC#id_card_front#1757399658891
    """
    parts = s3_key.split("/")
    if len(parts) < 3 or parts[0] != "docs":
        raise ValueError(f"Unexpected key format: {s3_key}")

    user_sub = parts[1]
    filename_no_ext = parts[-1].rsplit(".", 1)[0]  # "1757399658891_id_card_front"

    # Split into timestamp and doc name
    try:
        ts, doc_name = filename_no_ext.split("_", 1)
    except ValueError:
        raise ValueError(f"Filename does not match <ts>_<doc>: {filename_no_ext}")

    pk = f"USER#{user_sub}"
    sk = f"DOC#{doc_name}#{ts}"
    return pk, sk

def _now_iso_z() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _update_uploaded(pk: str, sk: str, key: str, size: int | None):
    """
    Updates DynamoDB record:
      - status = 'UPLOADED'
      - uploadedAt = current ISO-8601 UTC timestamp
      - size = set only if missing
      - s3Key = updated (optional, remove if you don’t want it)
      - docType and mime remain untouched
    """
    set_clauses = [
        "#st = :uploaded",
        "#uploadedAt = :iso",
        "#s3Key = :k",
        "#size = if_not_exists(#size, :size)" if size is not None else None,
    ]
    update_expr = "SET " + ", ".join([c for c in set_clauses if c])

    expr_names = {
        "#st": "status",
        "#uploadedAt": "uploadedAt",
        "#s3Key": "s3Key",
        "#size": "size",
    }

    expr_vals = {
        ":uploaded": {"S": "UPLOADED"},
        ":iso": {"S": _now_iso_z()},
        ":k": {"S": key},
    }
    if size is not None:
        expr_vals[":size"] = {"N": str(size)}

    dynamodb.update_item(
        TableName=TABLE_NAME,
        Key={"pk": {"S": pk}, "sk": {"S": sk}},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_vals,
        ReturnValues="NONE",
    )

def lambda_handler(event, context):
    processed = 0
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        raw_key = record["s3"]["object"]["key"]
        key = unquote_plus(raw_key)
        size = record["s3"]["object"].get("size")

        logger.info({"msg": "doc-received", "bucket": bucket, "key": key, "size": size})

        pk, sk = _parse_pk_sk_from_key(key)
        _update_uploaded(pk, sk, key, size)
        processed += 1

    # 2) Invoke doc-scan asynchronously (order of execution is guaranteed)
    try:
        payload = json.dumps({
            "detail": {
                "bucket": {
                    "name": bucket
                },
                "object": {
                    "key": key
                },
                "size": size
            }
        }).encode("utf-8")

        lambda_client.invoke(
            FunctionName=DOC_SCAN_FUNCTION_NAME,
            InvocationType='Event',  # fire-and-forget
            Payload=payload
        )
        print(f"[doc-received] Invoked '{DOC_SCAN_FUNCTION_NAME}' per key={key}")
    except Exception as e:
        print("[doc-received] Error while invoking doc-scan:", repr(e))
        # In MVP: logga; se vuoi affidabilità maggiore, valuta retry/event bus custom.
        return {"ok": False, "error": "scan_invoke_failed"}  

    return {"ok": True, "processed": processed}
