import json
import os
import sys
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

# Add shared layer to path
sys.path.append('/opt/python')

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


def decimal_default(obj):
    """JSON encoder for Decimal objects"""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError


def lambda_handler(event, context):
    """
    Generate presigned download URLs for support chat attachments
    
    Path parameters:
    - supportChatId: The support chat ID
    
    Query parameters:
    - messageId: The message ID containing the attachment
    
    Returns:
    {
        "downloadUrl": "https://s3.../file.pdf?X-Amz-Algorithm=...",
        "fileName": "file.pdf",
        "expiresIn": 3600
    }
    
    Authorization header contains JWT with user info
    """
    try:
        # Get supportChatId from path parameters
        support_chat_id = event['pathParameters']['supportChatId']
        
        # Get user info from authorizer context
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_roles = event['requestContext']['authorizer']['claims'].get('cognito:groups', [])
        
        # Get query parameters
        query_params = event.get('queryStringParameters', {}) or {}
        message_id = query_params.get('messageId')
        
        # Validate required fields
        if not message_id:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Missing required parameter: messageId'})
            }
        
        db_manager = ChatDBManager()
        
        # Verify support chat exists and user has access
        support_chat = db_manager.get_support_chat(support_chat_id)
        if not support_chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Support chat not found'})
            }
        
        # Verify user is authorized to access this chat
        is_authorized = (
            user_id == support_chat.requester_id or
            user_id == support_chat.assigned_to or
            'beezey_staff' in user_roles or
            'beezey_admin' in user_roles or
            'admins' in user_roles
        )
        
        if not is_authorized:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'You are not authorized to access this chat'})
            }
        
        # Get the message to find the attachment
        # Query by messageId using GSI
        support_messages_table = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'eu-south-1')).Table(
            os.environ['SUPPORT_MESSAGES_TABLE_NAME']
        )
        
        response = support_messages_table.query(
            IndexName='messageId-timestamp-index',
            KeyConditionExpression='messageId = :messageId',
            ExpressionAttributeValues={':messageId': message_id}
        )
        
        if not response['Items']:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Message not found'})
            }
        
        message_item = response['Items'][0]
        
        # Verify this message belongs to the requested support chat
        if message_item.get('supportChatId') != support_chat_id:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Message does not belong to this chat'})
            }
        
        # Check if message has attachments
        attachments = message_item.get('attachments', [])
        if not attachments:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Message has no attachments'})
            }
        
        # If multiple attachments, return presigned URLs for all
        bucket_name = os.environ['CHAT_ATTACHMENTS_BUCKET']
        
        # Use module-level S3 client with proper signature configuration
        # Generate presigned URLs for each attachment
        presigned_urls = []
        for att in attachments:
            # Extract the file key from the s3_url
            # Format: https://bucket.s3.region.amazonaws.com/support-chat/support_chat_id/filename
            s3_url = att.get('s3Url', '')
            if not s3_url:
                continue
            
            # Extract the key part (everything after the domain)
            # e.g., "support-chat/support_chat_123/20251212_163901_xxx_file.pdf"
            try:
                key = s3_url.split('.amazonaws.com/')[-1]
            except:
                continue
            
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': bucket_name,
                    'Key': key
                },
                ExpiresIn=3600  # 1 hour
            )
            
            presigned_urls.append({
                'fileName': att.get('fileName', 'attachment'),
                'fileType': att.get('fileType', 'application/octet-stream'),
                'fileSize': att.get('fileSize', 0),
                'downloadUrl': presigned_url
            })
        
        if not presigned_urls:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Could not generate download URLs'})
            }
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'attachments': presigned_urls,
                'expiresIn': 3600
            }, default=decimal_default)
        }
        
    except ClientError as e:
        print(f"AWS error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Failed to generate download URL'})
        }
    
    except KeyError as e:
        print(f"Missing required parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': f'Missing required parameter: {str(e)}'})
        }
    
    except Exception as e:
        print(f"Error generating download URL: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Internal server error'})
        }
