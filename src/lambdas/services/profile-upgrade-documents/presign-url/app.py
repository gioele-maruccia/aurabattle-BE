import json
import os
import time
import logging
import base64

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "eu-south-1")
BUCKET = os.environ["BUCKET"]
KMS_KEY_ID = os.environ["KMS_KEY_ID"]
TABLE_NAME = os.environ["TABLE_NAME"]
USER_PROFILES_TABLE = os.environ.get("USER_PROFILES_TABLE", "dev-UserProfiles")

s3 = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"}
    ),
)

ddb = boto3.client("dynamodb", region_name=REGION)

# TODO: re-aggiungere 'visura' e 'selfie' quando verranno richiesti di nuovo
# 'visura' e 'selfie' temporaneamente rimossi dal flusso di upload
# ALLOWED_TYPES = ("id_card_front", "id_card_back", "passport", "drivers_license", "visura", "selfie")
ALLOWED_TYPES = ("id_card_front", "id_card_back", "passport", "drivers_license")
ALLOWED_TYPES_SET = set(ALLOWED_TYPES)
ALLOWED_MIME = {"image/jpeg", "image/png", "application/pdf"}
MAX_SIZE = 10 * 1024 * 1024  # 10 MB
PRESIGNED_URL_EXPIRY = 300  # 5 minutes=300 


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body),
    }


def _ext_from_mime(mime: str) -> str:
    if mime == "application/pdf":
        return ".pdf"
    if mime == "image/png":
        return ".png"
    return ".jpg"


def _get_user_profile_type(user_sub: str) -> str | None:
    """
    Fetch user type from UserProfiles table.
    Returns: 'worker' or 'company', None if user not found or type not set
    """
    try:
        dynamodb_resource = boto3.resource('dynamodb', region_name=REGION)
        profiles_table = dynamodb_resource.Table(USER_PROFILES_TABLE)
        
        response = profiles_table.get_item(Key={'user_id': user_sub})
        item = response.get('Item', {})
        
        user_type = item.get('user_type') or item.get('profile_type')
        logger.info(f"User {user_sub} type: {user_type}")
        return user_type
    except Exception as e:
        logger.error(f"Failed to get user profile type: {e}")
        return None


def _cleanup_old_documents(user_sub: str, user_type: str, keep_doc_types: list):
    """
    Delete all documents except those in keep_doc_types list.
    
    Args:
        user_sub: User ID
        user_type: 'worker' or 'company'
        keep_doc_types: List of document types to keep (e.g., ['id_card_front', 'id_card_back', 'selfie'])
    """
    try:
        dynamodb_resource = boto3.resource('dynamodb', region_name=REGION)
        docs_table = dynamodb_resource.Table(TABLE_NAME)
        s3_client = boto3.client('s3', region_name=REGION)
        
        pk = f"USER#{user_sub}"
        
        # Query all documents for this user
        response = docs_table.query(
            KeyConditionExpression='pk = :pk AND begins_with(sk, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': pk,
                ':sk_prefix': 'DOC#'
            }
        )
        
        items = response.get('Items', [])
        logger.info(f"Found {len(items)} documents for user {user_sub}")
        
        deleted_count = 0
        for item in items:
            sk = item.get('sk', '')
            parts = sk.split('#')
            
            if len(parts) < 2:
                continue
            
            doc_type = parts[1]
            
            # If this document type should NOT be kept, delete it
            if doc_type not in keep_doc_types:
                try:
                    s3_key = item.get('s3Key')
                    
                    # Delete from S3
                    if s3_key:
                        s3_client.delete_object(Bucket=BUCKET, Key=s3_key)
                        logger.info(f"Deleted S3 object: {s3_key}")
                    
                    # Delete from DynamoDB
                    docs_table.delete_item(Key={'pk': pk, 'sk': sk})
                    logger.info(f"Deleted DynamoDB item: {sk}")
                    deleted_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to delete document {sk}: {e}")
                    # Continue with next item
                    continue
        
        logger.info(f"Cleanup completed: deleted {deleted_count} old documents for {user_type} user {user_sub}")
        return deleted_count
        
    except Exception as e:
        logger.error(f"Cleanup failed for user {user_sub}: {e}")
        # Don't fail the upload due to cleanup failure
        return 0


def _delete_existing_documents_of_type(user_sub: str, doc_type: str):
    """
    Delete ALL existing documents of the same type for a user.
    This ensures proper overwrite when user re-uploads documents.
    
    Args:
        user_sub: User ID
        doc_type: Document type to delete (e.g., 'id_card_front', 'visura')
    
    Returns:
        Number of documents deleted
    """
    try:
        dynamodb_resource = boto3.resource('dynamodb', region_name=REGION)
        docs_table = dynamodb_resource.Table(TABLE_NAME)
        s3_client = boto3.client('s3', region_name=REGION)
        
        pk = f"USER#{user_sub}"
        sk_prefix = f"DOC#{doc_type}#"
        
        logger.info(f"OVERWRITE CHECK: Querying for existing documents with pk={pk}, sk_prefix={sk_prefix}")
        
        # Query all documents of this type for this user
        response = docs_table.query(
            KeyConditionExpression='pk = :pk AND begins_with(sk, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': pk,
                ':sk_prefix': sk_prefix
            }
        )
        
        items = response.get('Items', [])
        deleted_count = 0
        
        if not items:
            logger.info(f"[OK] No existing {doc_type} documents found for user {user_sub} - clean slate")
            return 0
        
        logger.warning(f"[OVERWRITE] Found {len(items)} existing {doc_type} documents for user {user_sub}, deleting them NOW")
        
        for item in items:
            try:
                sk = item.get('sk', '')
                s3_key = item.get('s3Key')
                status = item.get('status', 'UNKNOWN')
                
                logger.info(f"   [DELETE] Deleting document: {sk} (status: {status}, s3_key: {s3_key})")
                
                # Delete from S3
                if s3_key:
                    try:
                        s3_client.delete_object(Bucket=BUCKET, Key=s3_key)
                        logger.info(f"     [OK] Deleted S3 object: {s3_key}")
                    except Exception as s3_err:
                        logger.error(f"     [ERROR] Failed to delete S3 object {s3_key}: {s3_err}")
                        # Continue anyway to delete from DynamoDB
                
                # Delete from DynamoDB
                docs_table.delete_item(Key={'pk': pk, 'sk': sk})
                logger.info(f"     [OK] Deleted DynamoDB item: {sk}")
                deleted_count += 1
                
            except Exception as e:
                logger.error(f"     [ERROR] Failed to delete document {item.get('sk')}: {e}")
                # Continue with next item
                continue
        
        logger.warning(f"[OVERWRITE COMPLETE] Deleted {deleted_count} existing {doc_type} documents for user {user_sub}")
        return deleted_count
        
    except Exception as e:
        logger.error(f"[OVERWRITE FAILED] Could not delete existing {doc_type} documents for user {user_sub}: {e}")
        logger.exception("Full traceback:")
        # Don't fail the upload due to cleanup failure, but log it
        # Don't fail the upload due to cleanup failure, but log it
        return 0


def _cleanup_documents_on_rejected_upload(user_sub: str):
    """
    When user uploads new documents after rejection, clean up old ones
    to ensure only required documents remain.
    
    - Worker: keep only id_card_front, id_card_back
    - Company: keep only id_card_front, id_card_back
    TODO: re-aggiungere selfie (worker/company) e visura (company) quando richiesti di nuovo
    """
    try:
        user_type = _get_user_profile_type(user_sub)
        
        if not user_type:
            logger.warning(f"Could not determine user type for {user_sub}, skipping cleanup")
            return
        
        if user_type == 'worker':
            # TODO: re-aggiungere 'selfie' quando richiesto di nuovo
            # keep_types = ['id_card_front', 'id_card_back', 'selfie']
            keep_types = ['id_card_front', 'id_card_back']
        elif user_type == 'company':
            # TODO: re-aggiungere 'visura' e 'selfie' quando richiesti di nuovo
            # keep_types = ['visura', 'id_card_front', 'id_card_back', 'selfie']
            keep_types = ['id_card_front', 'id_card_back']
        else:
            logger.warning(f"Unknown user type: {user_type}, skipping cleanup")
            return
        
        logger.info(f"Cleaning up old documents for {user_type} user {user_sub}. Keeping: {keep_types}")
        _cleanup_old_documents(user_sub, user_type, keep_types)
        
    except Exception as e:
        logger.error(f"Document cleanup failed: {e}")
        # Don't fail the request due to cleanup failure


def lambda_handler(event, context):
    try:
        logger.info("Event: %s", json.dumps(event))
        
        # Extract user from JWT claims
        # With Cognito User Pool Authorizer, claims are in requestContext.authorizer.claims
        claims = (event.get("requestContext", {})
                  .get("authorizer", {})
                  .get("claims", {}))
        
        user_sub = claims.get("sub")
        
        # Debug logging
        logger.info(f"RequestContext: {event.get('requestContext', {})}")
        logger.info(f"Authorizer: {event.get('requestContext', {}).get('authorizer', {})}")
        logger.info(f"Claims: {claims}")
        logger.info(f"User sub: {user_sub}")
        
        if not user_sub:
            logger.warning("Missing user sub in JWT claims")
            logger.warning(f"Full authorizer structure: {json.dumps(event.get('requestContext', {}).get('authorizer', {}), indent=2)}")
            return _resp(401, {"message": "Unauthorized"})

        # Parse body
        body_raw = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            try:
                body_raw = base64.b64decode(body_raw).decode("utf-8", "ignore")
            except Exception as e:
                logger.exception("Base64 decode failed")
                return _resp(400, {"message": "Invalid request body", "detail": str(e)})

        try:
            body = json.loads(body_raw)
        except json.JSONDecodeError as e:
            logger.info("Body that failed JSON parse: %r", body_raw[:1000])
            return _resp(400, {"message": "Invalid JSON body", "detail": str(e)})

        # Validate parameters
        doc_type = body.get("docType")
        mime = body.get("mime")
        size = body.get("size")

        if doc_type not in ALLOWED_TYPES_SET:
            return _resp(400, {"message": f"Invalid docType. Allowed: {list(ALLOWED_TYPES)}"})
        
        if mime not in ALLOWED_MIME:
            return _resp(400, {"message": f"Invalid mime type. Allowed: {list(ALLOWED_MIME)}"})

        if not isinstance(size, (int, float)) or size <= 0 or size > MAX_SIZE:
            return _resp(413, {"message": f"File size must be between 1 and {MAX_SIZE} bytes"})

        # =====================================================================
        # OVERWRITE: Delete existing documents of the same type
        # This ensures proper overwrite when user re-uploads the same document
        # =====================================================================
        logger.warning(f"[OVERWRITE START] User {user_sub} is uploading {doc_type} - checking for existing documents to delete")
        deleted_count = _delete_existing_documents_of_type(user_sub, doc_type)
        if deleted_count > 0:
            logger.warning(f"[OVERWRITE SUCCESS] Overwritten {deleted_count} existing {doc_type} document(s) for user {user_sub}")
        else:
            logger.info(f"[OVERWRITE INFO] No existing {doc_type} documents to overwrite for user {user_sub}")

        # Generate unique S3 key
        ts_ms = int(time.time() * 1000)
        ext = _ext_from_mime(mime)
        key = f"docs/{user_sub}/{ts_ms}_{doc_type}{ext}"
        pk = f"USER#{user_sub}"
        sk = f"DOC#{doc_type}#{ts_ms}"

        # Parameters for presigned URL
        params = {
            "Bucket": BUCKET,
            "Key": key,
            "ContentType": mime,
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": KMS_KEY_ID,
            "Metadata": {
                "userSub": user_sub, 
                "docType": doc_type,
                "uploadTimestamp": str(ts_ms)
            },
        }

        # Generate presigned URL
        upload_url = s3.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=PRESIGNED_URL_EXPIRY,
            HttpMethod="PUT",
        )

        # Required headers for upload (DEVE includere TUTTI i parametri del presigned URL)
        required_headers = {
            "Content-Type": mime,
            "x-amz-server-side-encryption": "aws:kms",
            "x-amz-server-side-encryption-aws-kms-key-id": KMS_KEY_ID,
            # Aggiungi i metadata come header
            "x-amz-meta-userSub": user_sub,
            "x-amz-meta-docType": doc_type,
            "x-amz-meta-uploadTimestamp": str(ts_ms)
        }

        # Save metadata in DynamoDB
        # Note: No ConditionExpression needed since we already deleted old documents above
        ddb.put_item(
            TableName=TABLE_NAME,
            Item={
                "pk": {"S": pk},
                "sk": {"S": sk},
                "s3Key": {"S": key},
                "docType": {"S": doc_type},
                "mime": {"S": mime},
                "size": {"N": str(int(size))},
                "status": {"S": "PENDING"},
                "uploadedAt": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                "ttl": {"N": str(int(time.time()) + 86400 * 30)},  # TTL 30 days
            }
        )

        logger.info(f"Generated presigned URL for user {user_sub}, docType {doc_type}")

        return _resp(200, {
            "uploadUrl": upload_url,
            "key": key,
            "expiresSec": PRESIGNED_URL_EXPIRY,
            "requiredHeaders": required_headers,
            "docType": doc_type,
            "size": int(size),
        })

    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.exception(f"AWS ClientError: {error_code}")
        return _resp(500, {"message": "AWS service error", "code": error_code})
    except Exception as e:
        logger.exception("Unhandled error")
        return _resp(500, {"message": "Internal server error", "detail": str(e)})