import json
import os
import sys
import uuid
import mimetypes
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

# Add shared layer to path
sys.path.append('/opt/python')

# Architecture Note:
# This Lambda uses both ChatDBManager (for chat validation) and boto3 (for S3 presigned URLs).
# ChatDBManager handles all DynamoDB operations, while boto3 is used only for S3-specific tasks.
from db_manager import ChatDBManager

# Initialize S3 client at module level for better performance and signature compatibility
REGION = os.environ.get('AWS_REGION', 'eu-south-1')
s3_client = boto3.client(
    's3',
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(
        signature_version='s3v4',
        s3={'addressing_style': 'virtual'}
    )
)


# Allowed file types and max size
ALLOWED_MIME_TYPES = {
    # Images
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    # Documents
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    # Archives
    'application/zip',
    # Text
    'text/plain'
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def lambda_handler(event, context):
    """
    Generate a presigned URL for uploading a file to S3
    
    Path parameters:
    - chat_id: The chat ID
    
    Query parameters (GET):
    - fileName: Original filename with extension
    - mimeType: File MIME type
    
    Returns:
    {
        "uploadUrl": "https://...",
        "fileUrl": "https://...",
        "expiresIn": 300
    }
    """
    try:
        # Get chat_id from path parameters
        chat_id = event['pathParameters']['chat_id']
        
        # Get user info from authorizer context
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Get query parameters
        query_params = event.get('queryStringParameters', {}) or {}
        file_name = query_params.get('fileName')
        file_type = query_params.get('mimeType')
        
        # Validate required fields
        if not file_name:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'Missing required parameter: fileName', 'code': 4316})
            }
        
        if not file_type:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'Missing required parameter: mimeType', 'code': 4317})
            }
        
        # Validate file type
        if file_type not in ALLOWED_MIME_TYPES:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'File type not allowed',
                    'allowed_types': list(ALLOWED_MIME_TYPES),
                    'code': 4318
                })
            }
        
        db_manager = ChatDBManager()
        
        # Verify chat exists and user has access
        chat = db_manager.get_chat(chat_id)
        if not chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Chat not found', 'code': 4319})
            }
        
        # Verify user is participant in this chat
        if user_id not in [chat.worker_id, chat.company_representative_id]:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Forbidden', 'message': 'You are not authorized to upload files in this chat', 'code': 4320})
            }
        
        # Generate unique file key
        file_extension = mimetypes.guess_extension(file_type) or ''
        unique_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Sanitize filename
        safe_filename = ''.join(c for c in file_name if c.isalnum() or c in '.-_ ')
        
        file_key = f"{chat_id}/{timestamp}_{unique_id}_{safe_filename}"
        
        # Use module-level S3 client with proper signature configuration
        bucket_name = os.environ['CHAT_ATTACHMENTS_BUCKET']
        
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': bucket_name,
                'Key': file_key,
                'ContentType': file_type,
                'ServerSideEncryption': 'AES256'  # Bucket policy requires this header on PUT
            },
            ExpiresIn=300  # 5 minutes
        )
        
        # Generate the download URL (this will be saved in the message)
        download_url = f"https://{bucket_name}.s3.{REGION}.amazonaws.com/{file_key}"
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'uploadUrl': presigned_url,
                'fileUrl': download_url,
                'expiresIn': 300,
                'code': 3087
            })
        }
        
    except ClientError as e:
        print(f"S3 error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Failed to generate upload URL', 'code': 5088})
        }
    
    except KeyError as e:
        print(f"Missing required parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': f'Missing required parameter: {str(e)}', 'code': 4321})
        }
    
    except Exception as e:
        print(f"Error generating upload URL: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5089})
        }