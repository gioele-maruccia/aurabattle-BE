import json
import sys
import base64

# Add shared layer to path
sys.path.append('/opt/python')

# Architecture Note:
# ChatDBManager provides a clean abstraction layer over DynamoDB operations.
# Unlike legacy services that use boto3 directly, this approach centralizes
# database logic in the shared layer for better maintainability.
from db_manager import ChatDBManager
from models import MessageState


def lambda_handler(event, context):
    """
    Get messages for a chat with pagination
    
    Path parameters:
    - chat_id: The chat ID
    
    Query parameters:
    - limit: Number of messages to return (default: 25, max: 100)
    - cursor: Base64-encoded pagination cursor (optional)
    
    Authorization header contains JWT with user info
    """
    try:
        # Get chat_id from path parameters
        chat_id = event['pathParameters']['chat_id']
        
        # Get user info from authorizer context
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Parse Cognito groups
        if isinstance(user_groups, str):
            user_groups = [g.strip() for g in user_groups.split(',')] if user_groups else []
        
        # Check if user is Beezey staff
        is_beezey_staff = any(group in user_groups for group in ['beezey_staff', 'beezey_admin', 'admins'])
        
        # Get query parameters
        query_params = event.get('queryStringParameters') or {}
        limit = int(query_params.get('limit', 25))
        cursor = query_params.get('cursor')
        
        # Validate limit
        if limit < 1 or limit > 100:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'limit must be between 1 and 100', 'code': 4175})
            }
        
        db_manager = ChatDBManager()
        
        # Verify chat exists and user has access
        chat = db_manager.get_chat(chat_id)
        if not chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Chat not found', 'code': 4177})
            }
        
        # Authorization: Allow participants OR Beezey staff OR backoffice operator
        is_participant = user_id in [chat.worker_id, chat.company_representative_id]
        has_backoffice_access = chat.backoffice_operator_id and user_id == chat.backoffice_operator_id
        
        if not is_participant and not is_beezey_staff and not has_backoffice_access:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Forbidden', 'message': 'You are not authorized to view this chat', 'code': 4176})
            }
        
        # Decode cursor if provided
        last_evaluated_key = None
        if cursor:
            try:
                cursor_data = base64.b64decode(cursor).decode('utf-8')
                last_evaluated_key = json.loads(cursor_data)
            except Exception as e:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({'error': 'Bad Request', 'message': 'Invalid cursor format', 'code': 4293})
                }
        
        # Get messages
        messages, next_key = db_manager.get_messages(
            chat_id=chat_id,
            limit=limit,
            last_evaluated_key=last_evaluated_key
        )
        
        # Encode next cursor
        next_cursor = None
        if next_key:
            cursor_str = json.dumps(next_key)
            next_cursor = base64.b64encode(cursor_str.encode('utf-8')).decode('utf-8')
        
        # Get unread count for this user
        is_worker = (user_id == chat.worker_id)

        # ── Apertura chat: marca tutti i messaggi beezey_system come letti ──
        # Il frontend non chiama update-message-state in modo affidabile per i
        # messaggi di sistema, quindi lo facciamo qua server-side al momento della
        # lettura.  Solo per partecipanti reali (non staff/backoffice).
        if is_participant:
            try:
                db_manager.mark_all_beezey_messages_read_for_role(
                    chat_id=chat_id,
                    is_company=(not is_worker),
                )
            except Exception as e:
                print(f"Could not auto-mark beezey messages as read (non-critical): {e}")

        unread_count = db_manager.get_unread_count(chat_id, user_id, is_worker=is_worker)
        
        # Mark messages as delivered if they're in 'sent' state and not from current user
        for message in messages:
            if message.sender_id != user_id and message.state.value == 'sent':
                db_manager.update_message_state(
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    timestamp=message.timestamp,
                    new_state=MessageState.DELIVERED
                )
                message.state = MessageState.DELIVERED
        
        # Return response
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'success': True,
                'data': {
                    'chat': chat.to_api_response(),
                    'messages': [msg.to_api_response() for msg in messages],
                    'count': len(messages),
                    'hasMore': next_cursor is not None,
                    'nextCursor': next_cursor,
                    'unreadCount': unread_count
                },
                'meta': {
                    'limit': limit
                },
                'code': 3052
            })
        }
        
    except KeyError as e:
        print(f"Missing required parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': f'Missing required parameter: {str(e)}', 'code': 4294})
        }
    
    except ValueError as e:
        print(f"Validation error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': str(e), 'code': 4295})
        }
    
    except Exception as e:
        print(f"Error getting messages: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5049})
        }