import os
import time
import logging
import boto3
from datetime import datetime, timezone
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "eu-south-1")
BUCKET = os.environ["BUCKET"]
TABLE_NAME = os.environ["TABLE_NAME"]

# How old (seconds) a PENDING record must be before we check it.
# Default: 1 week = 604800s
STALE_THRESHOLD_SECONDS = int(os.environ.get("STALE_THRESHOLD_SECONDS", "604800"))

s3 = boto3.client("s3", region_name=REGION)
ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE_NAME)


def _age_seconds(item: dict) -> float:
    """
    Derive upload age from the sk (DOC#<type>#<ts_ms>) or fallback to uploadedAt.
    """
    sk = item.get("sk", "")
    try:
        ts_ms = int(sk.split("#")[-1])
        return (time.time() * 1000 - ts_ms) / 1000
    except (ValueError, IndexError):
        pass

    uploaded_at = item.get("uploadedAt", "")
    if uploaded_at:
        try:
            upload_time = datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - upload_time).total_seconds()
        except Exception:
            pass

    # Can't determine age; assume it is stale so we check it.
    return float("inf")


def _mark_expired(pk: str, sk: str) -> bool:
    """
    Set status=EXPIRED only if record is still PENDING (conditional write).
    Returns True if the update succeeded.
    """
    try:
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #status = :expired, expiredAt = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":expired": "EXPIRED",
                ":pending": "PENDING",
                ":now": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            ConditionExpression="#status = :pending",
        )
        logger.info(f"Marked EXPIRED: {pk} / {sk}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info(f"Already processed (no longer PENDING): {pk} / {sk}")
        else:
            logger.error(f"DynamoDB error for {pk}/{sk}: {e}")
        return False


def lambda_handler(event, context):
    logger.info("Starting scan-pending-uploads run")

    expired_count = 0
    scanned_count = 0
    skipped_count = 0

    # Scan DynamoDB for all PENDING items.
    # A full-table scan is acceptable given typical document volumes.
    scan_kwargs: dict = {
        "FilterExpression": "#status = :pending",
        "ExpressionAttributeNames": {"#status": "status"},
        "ExpressionAttributeValues": {":pending": "PENDING"},
    }

    while True:
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])
        scanned_count += len(items)

        for item in items:
            pk = item.get("pk", "")
            sk = item.get("sk", "")
            s3_key = item.get("s3Key")

            age = _age_seconds(item)
            if age < STALE_THRESHOLD_SECONDS:
                logger.debug(f"Not yet stale ({age:.0f}s): {pk} / {sk}")
                skipped_count += 1
                continue

            if not s3_key:
                logger.warning(f"No s3Key for {pk}/{sk} — marking EXPIRED")
                if _mark_expired(pk, sk):
                    expired_count += 1
                continue

            # Check whether the file actually reached S3
            try:
                s3.head_object(Bucket=BUCKET, Key=s3_key)
                # File exists. doc-received should have updated status; leave as is.
                logger.info(f"File present in S3, skipping: {s3_key}")
                skipped_count += 1
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code in ("404", "403"):
                    logger.info(f"File missing in S3: {s3_key} — marking EXPIRED")
                    if _mark_expired(pk, sk):
                        expired_count += 1
                else:
                    logger.error(f"Unexpected S3 error for {s3_key}: {e}")

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    logger.info(
        f"Scan complete — scanned={scanned_count}, "
        f"expired={expired_count}, skipped={skipped_count}"
    )
    return {
        "statusCode": 200,
        "scanned": scanned_count,
        "expired": expired_count,
        "skipped": skipped_count,
    }
