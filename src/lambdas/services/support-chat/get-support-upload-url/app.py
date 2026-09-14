"""
Lambda: Get Support Upload URL

Genera un URL presigned di S3 per l'upload di allegati nelle chat di supporto.
Max 10MB per file.
"""

import json
import os
import uuid
from typing import Dict, Any
import boto3
from botocore.config import Config


# Initialize S3 client at module level for proper signature handling
REGION = os.environ.get('AWS_REGION', 'eu-south-1')
s3_client = boto3.client(
    's3',
    region_name=REGION,
    endpoint_url=f'https://s3.{REGION}.amazonaws.com',
    config=Config(
        signature_version='s3v4',
        s3={'addressing_style': 'virtual'}
    )
)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principale
    
    Path parameters:
    - supportChatId: ID della chat
    
    Body:
    {
        "fileName": "documento.pdf",
        "fileType": "application/pdf",
        "fileSize": 12345
    }
    
    Risposta:
    {
        "uploadUrl": "https://...",
        "downloadUrl": "https://...",
        "fileName": "documento.pdf"
    }
    """
    
    try:
        # 1. Estrai user ID
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required', 'code': 4259})
            }
        
        # 2. Estrai supportChatId
        path_params = event.get('pathParameters', {})
        support_chat_id = path_params.get('supportChatId')
        
        if not support_chat_id:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'supportChatId is required', 'code': 4260})
            }
        
        # 3. Parse body
        body = json.loads(event.get('body', '{}'))
        file_name = body.get('fileName', '')
        file_type = body.get('fileType', '')
        file_size = int(body.get('fileSize', 0))
        
        if not file_name or not file_type or file_size == 0:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'fileName, fileType, and fileSize are required', 'code': 4261})
            }
        
        # Validazione dimensione (max 10MB)
        MAX_SIZE = 10 * 1024 * 1024  # 10MB
        if file_size > MAX_SIZE:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': f'File too large. Max size is {MAX_SIZE / 1024 / 1024}MB', 'code': 4262})
            }
        
        # 4. Genera presigned URL per upload
        bucket_name = os.environ.get('CHAT_ATTACHMENTS_BUCKET_NAME', 'dev-beezey-chat-attachments')
        environment = os.environ.get('ENVIRONMENT', 'dev')
        
        # S3 key: support-chat/<supportChatId>/<timestamp>_<uuid>_<filename>
        import time
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()
        unique_id = uuid.uuid4().hex[:8]
        s3_key = f"support-chat/{support_chat_id}/{timestamp}_{unique_id}_{file_name}"
        
        # Presigned URL per PUT (upload)
        upload_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': bucket_name,
                'Key': s3_key,
                'ContentType': file_type,
                'ServerSideEncryption': 'AES256'  # Required by bucket policy
            },
            ExpiresIn=300  # 5 minuti
        )
        
        # URL statico per download (come nella chat normale)
        # Il frontend usa questo URL e poi chiama get-download-url per ottenere il presigned URL
        download_url = f"https://{bucket_name}.s3.{REGION}.amazonaws.com/{s3_key}"
        
        # 5. Risposta
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'uploadUrl': upload_url,
                'downloadUrl': download_url,
                'fileName': file_name,
                's3Key': s3_key,
                'code': 3078
            })
        }
        
    except Exception as e:
        print(f"Error in get_support_upload_url: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5076})
        }
