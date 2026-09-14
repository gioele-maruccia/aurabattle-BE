"""
Lambda: Send Support Message

Invia un messaggio in una chat di supporto con WebSocket broadcast.
"""

import json
import sys
import os

sys.path.append('/opt/python')

from db_manager import ChatDBManager
from models import SupportMessage, MessageState, SenderType, Attachment, generate_message_id, get_current_timestamp
from ws_manager import WebSocketManager


def handler(event, context):
    """
    Handler principale
    
    Path parameters:
    - supportChatId: ID della chat
    
    Body:
    {
        "messageText": "Testo del messaggio",
        "attachments": [
            {
                "fileName": "documento.pdf",
                "fileSize": 12345,
                "fileType": "application/pdf",
                "s3Url": "https://..."
            }
        ]
    }
    """
    
    try:
        # 1. Estrai user info da Cognito JWT
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        user_roles = claims.get('cognito:groups', [])
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required', 'code': 4189})
            }
        
        # Determina sender type
        sender_type = SenderType.BEEZEY  # default
        if 'workers' in user_roles:
            sender_type = SenderType.WORKER
        elif 'company_representatives' in user_roles or 'companies' in user_roles:
            sender_type = SenderType.COMPANY
        elif 'beezey_staff' in user_roles or 'beezey_admin' in user_roles or 'admins' in user_roles:
            sender_type = SenderType.BEEZEY
        
        # 2. Estrai supportChatId
        path_params = event.get('pathParameters', {})
        support_chat_id = path_params.get('supportChatId')
        
        if not support_chat_id:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'supportChatId is required', 'code': 4188})
            }
        
        # 3. Verifica chat e autorizzazione
        db_manager = ChatDBManager()
        support_chat = db_manager.get_support_chat(support_chat_id)
        
        if not support_chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Support chat not found', 'code': 4191})
            }
        
        # Autorizzazione: requester, assegnatario, o staff
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
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Forbidden', 'message': 'You are not authorized to send messages in this chat', 'code': 4190})
            }
        
        # 4. Parse body
        body = json.loads(event.get('body', '{}'))
        message_text = body.get('messageText', '').strip()
        attachments_list = body.get('attachments', [])
        
        if not message_text and not attachments_list:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'Message text or attachments are required', 'code': 4074})
            }
        
        # 5. Crea oggetti Attachment
        attachments = []
        for att in attachments_list:
            attachment = Attachment(
                file_name=att.get('fileName'),
                file_size=att.get('fileSize', 0),
                file_type=att.get('fileType'),
                s3_url=att.get('s3Url'),
                uploaded_at=get_current_timestamp()
            )
            attachments.append(attachment)
        
        # 6. Crea messaggio
        message = SupportMessage(
            support_chat_id=support_chat_id,
            message_id=generate_message_id(),
            sender_id=user_id,
            sender_type=sender_type,
            message_text=message_text,
            timestamp=get_current_timestamp(),
            state=MessageState.SENT,
            attachments=attachments
        )
        
        # 7. Salva nel database
        db_manager.create_support_message(message)
        
        # 8. Broadcast via WebSocket (best effort, non blocking)
        try:
            ws_manager = WebSocketManager()
            
            # Invia a requester
            ws_manager.send_to_user(
                user_id=support_chat.requester_id,
                data={
                    'action': 'new_support_message',
                    'supportChatId': support_chat_id,
                    'message': message.to_api_response()
                }
            )
            
            # Invia a assegnatario se presente
            if support_chat.assigned_to:
                ws_manager.send_to_user(
                    user_id=support_chat.assigned_to,
                    data={
                        'action': 'new_support_message',
                        'supportChatId': support_chat_id,
                        'message': message.to_api_response()
                    }
                )
        except Exception as ws_error:
            # Log ma non fallire
            print(f"WebSocket broadcast error (non-critical): {str(ws_error)}")
        
        # 9. Response
        return {
            'statusCode': 201,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'message': message.to_api_response(),
                'code': 3058
            })
        }
        
    except Exception as e:
        print(f"Error in send_support_message: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5054})
        }
