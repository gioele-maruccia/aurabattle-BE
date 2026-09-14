"""
Lambda: Get Support Messages

Recupera i messaggi di una chat di supporto con paginazione.
"""

import json
from typing import Dict, Any

from db_manager import ChatDBManager


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principale
    
    Path parameters:
    - supportChatId: ID della chat
    
    Query parameters:
    - limit: numero di messaggi (default 50, max 200)
    - lastKey: per paginazione
    
    Risposta:
    {
        "messages": [
            {
                "supportChatId": "support_...",
                "messageId": "msg_...",
                "senderId": "user_id",
                "senderType": "worker",
                "messageText": "...",
                "timestamp": "ISO 8601",
                "state": "read",
                "attachments": [],
                "sticker": "heart"  (opzionale)
            }
        ],
        "lastKey": "..." (se presente)
    }
    """
    
    try:
        # 1. Estrai user ID e roles
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        user_roles = claims.get('cognito:groups', [])
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required', 'code': 4193})
            }
        
        # 2. Estrai supportChatId dal path
        path_params = event.get('pathParameters', {})
        support_chat_id = path_params.get('supportChatId')
        
        if not support_chat_id:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'supportChatId is required', 'code': 4192})
            }
        
        # 3. Parse query parameters
        query_params = event.get('queryStringParameters', {}) or {}
        limit = int(query_params.get('limit', 50))
        limit = min(limit, 200)
        limit = max(limit, 1)
        
        last_key_str = query_params.get('lastKey')
        last_key = None
        if last_key_str:
            try:
                import base64
                last_key = json.loads(base64.b64decode(last_key_str).decode())
            except:
                last_key = None
        
        # 4. Verifica autorizzazione: l'utente deve essere il richiedente della chat
        db_manager = ChatDBManager()
        support_chat = db_manager.get_support_chat(support_chat_id)
        
        if not support_chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Support chat not found', 'code': 4195})
            }
        
        if support_chat.requester_id != user_id:
            # Gli assegnatari e staff possono anche visualizzare
            is_authorized = (
                support_chat.assigned_to == user_id or
                'beezey_staff' in user_roles or
                'beezey_admin' in user_roles or
                'admins' in user_roles
            )
            if not is_authorized:
                return {
                    'statusCode': 403,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({'error': 'Forbidden', 'message': 'You are not authorized to access this chat', 'code': 4194})
                }
        
        # 5. Query messaggi
        messages, next_last_key = db_manager.get_support_messages(
            support_chat_id,
            limit=limit,
            last_key=last_key
        )
        
        # 6. Risposta
        messages_response = [msg.to_api_response() for msg in messages]
        
        # Encode next cursor
        import base64
        next_cursor = None
        if next_last_key:
            cursor_str = json.dumps(next_last_key)
            next_cursor = base64.b64encode(cursor_str.encode('utf-8')).decode('utf-8')
        
        response_body = {
            'success': True,
            'data': {
                'messages': messages_response,
                'count': len(messages),
                'hasMore': next_cursor is not None,
                'nextCursor': next_cursor
            },
            'meta': {
                'limit': limit
            },
            'code': 3059
        }
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(response_body)
        }
        
    except Exception as e:
        print(f"Error in get_support_messages: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5055})
        }
