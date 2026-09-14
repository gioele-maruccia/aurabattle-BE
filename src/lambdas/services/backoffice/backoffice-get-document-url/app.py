import json
import os
import boto3
import logging
from datetime import datetime, timedelta, timezone
from botocore.exceptions import ClientError
from typing import Dict, Any, Tuple

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ["BUCKET_NAME"]
REGION = os.environ["REGION"]

# IMPORTANTE: Configurazione esplicita delle regioni
# La regione del bucket DEVE essere specificata correttamente
BUCKET_REGION = os.environ.get("BUCKET_REGION", REGION)

logger.info(f"Using DynamoDB region: {REGION}")
logger.info(f"Using S3 bucket region: {BUCKET_REGION}")

# Create clients with explicit regions and endpoint URL for eu-south-1
dynamodb = boto3.resource('dynamodb', region_name=REGION)

# Per eu-south-1, forza l'endpoint regionale specifico
if BUCKET_REGION == 'eu-south-1':
    s3_client = boto3.client(
        's3',
        region_name=BUCKET_REGION,
        endpoint_url=f'https://s3.{BUCKET_REGION}.amazonaws.com',
        config=boto3.session.Config(
            signature_version='s3v4',
            s3={'addressing_style': 'virtual'}
        )
    )
else:
    s3_client = boto3.client('s3', region_name=BUCKET_REGION)

table = dynamodb.Table(TABLE_NAME)

def _cors_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Standardized CORS response format"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS"
        },
        "body": json.dumps(body)
    }

def _parse_doc_id(doc_id: str) -> Tuple[str, str]:
    """Parse document ID into timestamp and doc_type
    
    Args:
        doc_id: Format like '1757399658891_id_card_front'
        
    Returns:
        tuple: (timestamp, doc_type)
    """
    try:
        parts = doc_id.split('_', 1)
        if len(parts) != 2:
            raise ValueError("Invalid format")
        return parts[0], parts[1]
    except (ValueError, IndexError):
        raise ValueError(f"Invalid document ID format: {doc_id}. Expected format: 'timestamp_doc_type'")

def _extract_reviewer_info(event: Dict[str, Any]) -> Dict[str, str]:
    """Extract reviewer information from Cognito claims"""
    try:
        # Extract from Cognito authorizer
        authorizer = event.get('requestContext', {}).get('authorizer', {})
        claims = authorizer.get('jwt', {}).get('claims', {})
        
        return {
            'reviewerId': claims.get('sub', 'unknown'),
            'reviewerEmail': claims.get('email', 'unknown'),
            'reviewerName': claims.get('name', claims.get('cognito:username', 'unknown'))
        }
    except Exception as e:
        logger.warning(f"Could not extract reviewer info: {str(e)}")
        return {
            'reviewerId': 'unknown',
            'reviewerEmail': 'unknown', 
            'reviewerName': 'unknown'
        }

def get_document_metadata(user_sub: str, doc_id: str) -> Dict[str, Any]:
    """Get document metadata from DynamoDB"""
    try:
        timestamp, doc_type = _parse_doc_id(doc_id)
        
        pk = f"USER#{user_sub}"
        sk = f"DOC#{doc_type}#{timestamp}"
        
        response = table.get_item(
            Key={
                'pk': pk,
                'sk': sk
            }
        )
        
        if 'Item' not in response:
            raise ValueError(f"Document not found: {doc_id} for user {user_sub}")
        
        return response['Item']
        
    except ValueError:
        # Re-raise ValueError as is
        raise
    except Exception as e:
        logger.error(f"Error getting document metadata: {str(e)}")
        raise ValueError(f"Database error: {str(e)}")

def verify_document_access_permissions(doc_metadata: Dict[str, Any], reviewer_info: Dict[str, str]) -> bool:
    """Verify if reviewer has permission to access this document type"""
    
    doc_type = doc_metadata.get('docType', '')
    status = doc_metadata.get('status', '')
    
    # Check for restricted statuses
    restricted_statuses = ['DELETED', 'CORRUPTED', 'QUARANTINED']
    if status in restricted_statuses:
        logger.warning(f"Access denied to document with status {status} by {reviewer_info['reviewerEmail']}")
        return False
    
    # Add more sophisticated access control here based on your requirements
    # For example, check reviewer roles, document sensitivity, etc.
    
    return True

def log_document_access(user_sub: str, doc_id: str, reviewer_info: Dict[str, str], action: str = "download"):
    """Log document access for audit purposes"""
    try:
        current_time = datetime.now(timezone.utc).isoformat()
        
        log_entry = {
            "event": "document_access",
            "action": action,
            "user_sub": user_sub,
            "document_id": doc_id,
            "reviewer_id": reviewer_info['reviewerId'],
            "reviewer_email": reviewer_info['reviewerEmail'],
            "timestamp": current_time,
            "dynamodb_region": REGION,
            "bucket_region": BUCKET_REGION
        }
        
        logger.info(json.dumps(log_entry))
        
    except Exception as e:
        logger.error(f"Failed to log document access: {str(e)}")

def generate_presigned_download_url(s3_key: str, expires_in: int = 3600, filename: str = None) -> Tuple[str, str, int]:
    """Generate presigned URL for document download with proper headers"""
    try:
        logger.info(f"Generating presigned URL for key: {s3_key} in bucket region: {BUCKET_REGION}")
        logger.info(f"S3 client endpoint: {s3_client._endpoint.host}")
        
        # Verify object exists and get metadata
        head_response = s3_client.head_object(Bucket=BUCKET_NAME, Key=s3_key)
        content_type = head_response.get('ContentType', 'application/octet-stream')
        content_length = head_response.get('ContentLength', 0)
        
        logger.info(f"Object exists: {s3_key}, Content-Type: {content_type}, Size: {content_length}")
        
        # Prepare basic parameters
        params = {
            'Bucket': BUCKET_NAME, 
            'Key': s3_key
        }
        
        # Add filename parameter if provided
        if filename:
            params['ResponseContentDisposition'] = f'attachment; filename="{filename}"'
        
        # For eu-south-1, explicitly set the region in the request
        if BUCKET_REGION == 'eu-south-1':
            logger.info("Using special configuration for eu-south-1")
        
        # Generate presigned URL
        url = s3_client.generate_presigned_url(
            'get_object',
            Params=params,
            ExpiresIn=expires_in
        )
        
        logger.info(f"Generated URL: {url[:100]}...")
        
        # Check if URL contains the correct region endpoint
        expected_endpoint = f"s3.{BUCKET_REGION}.amazonaws.com"
        if expected_endpoint in url:
            logger.info(f"✅ URL contains correct regional endpoint: {expected_endpoint}")
        else:
            logger.warning(f"⚠️  URL does not contain expected endpoint: {expected_endpoint}")
            logger.warning(f"URL starts with: {url[:100]}")
        
        return url, content_type, content_length
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"S3 ClientError: {error_code} - {str(e)}")
        
        if error_code == 'NoSuchKey':
            raise ValueError(f"Document not found in S3: {s3_key}")
        elif error_code == 'NoSuchBucket':
            raise ValueError(f"Bucket not found: {BUCKET_NAME}")
        elif error_code == 'AccessDenied':
            raise ValueError(f"Access denied to document: {s3_key}")
        else:
            raise ValueError(f"S3 error: {error_code}")
            
    except Exception as e:
        logger.error(f"Unexpected error generating presigned URL: {str(e)}")
        raise ValueError(f"Failed to generate download URL: {str(e)}")

def verify_admin_access(event: Dict[str, Any]) -> tuple[bool, str, Dict[str, str]]:
    """Verifica che l'utente autenticato sia nel gruppo admins"""
    try:
        authorizer = event.get('requestContext', {}).get('authorizer', {})
        claims = authorizer.get('jwt', {}).get('claims', {}) or authorizer.get('claims', {})
        
        user_sub = claims.get('sub', 'unknown')
        user_email = claims.get('email', 'unknown')
        user_name = claims.get('name', claims.get('cognito:username', 'unknown'))
        
        groups = claims.get('cognito:groups', [])
        if isinstance(groups, str):
            groups = [groups]
        
        logger.info(f"User {user_email} (sub: {user_sub}) attempting access with groups: {groups}")
        
        if 'admins' not in groups:
            logger.warning(f"Access denied for user {user_email} - not in admins group")
            return False, "Access denied: admin privileges required", {}
        
        user_info = {
            'sub': user_sub,
            'email': user_email,
            'name': user_name,
            'groups': groups
        }
        
        logger.info(f"Admin access granted for user {user_email}")
        return True, "", user_info
        
    except Exception as e:
        logger.error(f"Error verifying admin access: {str(e)}")
        return False, f"Authorization error: {str(e)}", {}

def lambda_handler(event, context):
    try:
        # Handle CORS preflight
        if event.get('httpMethod') == 'OPTIONS':
            return _cors_response(200, {"message": "OK"})
        
        # ========================================
        # VERIFICA ACCESSO ADMIN
        # ========================================
        is_admin, error_msg, admin_info = verify_admin_access(event)
        if not is_admin:
            return _cors_response(403, {
                "error": "Forbidden",
                "message": error_msg,
                "code": 4224
            })
        
        logger.info(f"Document download request: {json.dumps(event, default=str)}")
        logger.info(f"Admin {admin_info.get('email')} requesting document download")
        logger.info(f"Using DynamoDB region: {REGION}, S3 bucket region: {BUCKET_REGION}")
        
        # Extract path parameters
        path_params = event.get('pathParameters') or {}
        user_sub = path_params.get('user_sub')
        doc_id = path_params.get('doc_id')
        
        if not user_sub or not doc_id:
            return _cors_response(400, {
                'error': 'Bad Request',
                "message": "user_sub and doc_id are required",
                "code": 4223
            })
        
        # Validate input format
        try:
            _parse_doc_id(doc_id)  # Validate doc_id format
        except ValueError as e:
            return _cors_response(400, {
                'error': 'Bad Request',
                "message": str(e),
                "code": 4345
            })
        
        # Extract reviewer information
        reviewer_info = _extract_reviewer_info(event)
        
        # Parse request body for options
        body = {}
        if event.get('body'):
            try:
                body = json.loads(event['body'])
            except json.JSONDecodeError:
                return _cors_response(400, {
                    'error': 'Bad Request',
                    'message': "Invalid JSON in request body",
                    'code': 4346
                })
        
        # Validate and sanitize expires_in
        expires_in = body.get('expiresIn', 3600)
        try:
            expires_in = int(expires_in)
            if expires_in > 7200:  # Max 2 hours
                expires_in = 7200
            if expires_in < 300:   # Min 5 minutes
                expires_in = 300
        except (ValueError, TypeError):
            expires_in = 3600
            
        custom_filename = body.get('filename', '').strip()
        download_reason = body.get('reason', 'review').strip()
        
        # Get document metadata
        try:
            doc_metadata = get_document_metadata(user_sub, doc_id)
        except ValueError as e:
            return _cors_response(404, {
                'error': 'Not Found',
                "message": str(e),
                "code": 4225
            })
        
        # Verify access permissions
        if not verify_document_access_permissions(doc_metadata, reviewer_info):
            return _cors_response(403, {
                'error': 'Forbidden',
                "message": "Insufficient permissions to access this document",
                "code": 4347
            })
        
        s3_key = doc_metadata.get('s3Key')
        if not s3_key:
            return _cors_response(500, {
                'error': 'Internal Server Error',
                "message": "S3 key not found in document record",
                "code": 5099
            })
        
        # Generate presigned URL
        try:
            download_url, content_type, content_length = generate_presigned_download_url(
                s3_key, expires_in, custom_filename or None
            )
        except ValueError as e:
            return _cors_response(404, {
                'error': 'Not Found',
                "message": str(e),
                "code": 4225
            })
        
        # Log access for audit
        log_document_access(user_sub, doc_id, reviewer_info, f"download_{download_reason}")
        
        # Calculate actual expiry time
        expiry_time = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        # Prepare response with comprehensive document info
        response_data = {
            "downloadUrl": download_url,
            "expiresIn": expires_in,
            "expiresAt": expiry_time.isoformat(),
            "contentType": content_type,
            "contentLength": content_length,
            "dynamodbRegion": REGION,
            "bucketRegion": BUCKET_REGION,
            "documentInfo": {
                "docId": doc_id,
                "userSub": user_sub,
                "docType": doc_metadata.get('docType'),
                "status": doc_metadata.get('status'),
                "mime": doc_metadata.get('mime'),
                "size": int(doc_metadata.get('size', 0)),
                "uploadedAt": doc_metadata.get('uploadedAt'),
                "s3Key": s3_key,
                "reviewedAt": doc_metadata.get('reviewedAt'),
                "reviewedBy": doc_metadata.get('reviewedBy'),
                "reason": doc_metadata.get('reason')
            },
            "downloadInfo": {
                "requestedBy": reviewer_info['reviewerEmail'],
                "requestedAt": datetime.now(timezone.utc).isoformat(),
                "reason": download_reason,
                "customFilename": custom_filename or None
            }
        }
        
        return _cors_response(200, {**response_data, 'code': 3072})
        
    except Exception as e:
        logger.error(f"Unexpected error in download handler: {str(e)}")
        return _cors_response(500, {
            'error': 'Internal Server Error',
            "message": "An unexpected error occurred",
            "code": 5066
        })