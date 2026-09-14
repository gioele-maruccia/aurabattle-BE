import json
import sys
from datetime import datetime, timezone

# Add shared layer to path
sys.path.append('/opt/python')

# Architecture Note:
# ChatDBManager (shared layer) provides abstracted database operations.
# This is preferred over direct boto3 calls for better code organization and testability.

from models import StickerTag
from db_manager import ChatDBManager


def lambda_handler(event, context):
    """
    Set a sticker/reaction on a message
    
    Path parameters:
    - chat_id: The chat ID
    - message_id: The message ID
    
    Expected input:
    {
        "sticker": "thumbs_up"
    }
    
    Authorization header contains JWT with user info
    """
    try:
        # Get path parameters
        chat_id = event['pathParameters']['chat_id']
        message_id = event['pathParameters']['message_id']
        
        # Get user info from authorizer context
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Parse request body
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', {})
        
        # Validate required fields - only sticker is required
        if 'sticker' not in body:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'code': 4048,
                    'error': 'Bad Request',
                    'message': 'sticker is required'
                })
            }
        
        # Validate sticker value
        try:
            sticker_tag = StickerTag(body['sticker'])
        except ValueError:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'code': 4048,
                    'error': 'Bad Request',
                    'message': f'Invalid sticker. Must be one of: {[s.value for s in StickerTag]}'
                })
            }
        
        db_manager = ChatDBManager()
        
        # Verify chat exists and user has access
        chat = db_manager.get_chat(chat_id)
        if not chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'code': 4047,
                    'error': 'Not Found',
                    'message': 'Chat not found'
                })
            }
        
        # Verify user is participant in this chat
        if user_id not in [chat.worker_id, chat.company_representative_id]:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'code': 4046,
                    'error': 'Forbidden',
                    'message': 'You are not authorized to set stickers in this chat'
                })
            }
        
        # Find the message to get its timestamp (needed for DynamoDB update)
        message = db_manager.get_message(chat_id, message_id)
        if not message:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'code': 4049,
                    'error': 'Not Found',
                    'message': 'Message not found'
                })
            }
        
        # Set sticker on message
        db_manager.add_sticker_to_message(
            chat_id=chat_id,
            message_id=message_id,
            timestamp=message.timestamp,
            sticker=sticker_tag.value
        )
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 3008,
                'message': 'Sticker set successfully',
                'message_id': message_id,
                'sticker': sticker_tag.value
            })
        }
        
    except KeyError as e:
        print(f"Missing required parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 4048,
                'error': 'Bad Request',
                'message': f'Missing required parameter: {str(e)}'
            })
        }
    
    except ValueError as e:
        print(f"Validation error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 4048,
                'error': 'Bad Request',
                'message': str(e)
            })
        }
    
    except Exception as e:
        print(f"Error setting sticker: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 5000,
                'error': 'Internal Server Error',
                'message': 'Internal server error'
            })
        }