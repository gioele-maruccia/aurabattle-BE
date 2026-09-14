"""
Lambda: Update Support Message State

Aggiorna lo stato di un messaggio di supporto (sent -> delivered -> read).
"""

import json
from typing import Dict, Any

from db_manager import ChatDBManager
from models import MessageState


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principale
    
    Path parameters:
    - supportChatId: ID della chat
    - messageId: ID del messaggio
    
    Body:
    {
        "state": "sent | delivered | read"
    }
    
    Risposta:
    {
        "status": "updated"
    }
    """
    
    try:
        # 1. Estrai user ID e roles
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        user_roles = claims.get('cognito:groups', [])
        
        # Converti stringa in lista se necessario
        if isinstance(user_roles, str):
            user_roles = [user_roles] if user_roles else []
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required', 'code': 4271})
            }
        
        # 2. Estrai path parameters
        path_params = event.get('pathParameters', {})
        support_chat_id = path_params.get('supportChatId')
        message_id = path_params.get('messageId')
        
        if not support_chat_id or not message_id:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'supportChatId and messageId are required', 'code': 4272})
            }
        
        # 3. Verifica autorizzazione
        db_manager = ChatDBManager()
        support_chat = db_manager.get_support_chat(support_chat_id)
        
        if not support_chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Support chat not found', 'code': 4273})
            }
        
        # Solo il richiedente, l'assegnatario o staff possono aggiornare stato
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
                'body': json.dumps({'error': 'Forbidden', 'message': 'You are not authorized to update message state in this chat', 'code': 4274})
            }
        
        # 4. Parse body
        body = json.loads(event.get('body', '{}'))
        state_str = body.get('state', '').lower()
        
        # Valida stato
        valid_states = ['sent', 'delivered', 'read']
        if state_str not in valid_states:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': f'Invalid state. Must be one of: {valid_states}', 'code': 4275})
            }
        
        new_state = MessageState[state_str.upper()]
        
        # 5. Aggiorna stato (timestamp opzionale - fa lookup tramite GSI se non fornito)
        try:
            db_manager.update_support_message_state(
                support_chat_id,
                message_id,
                new_state
            )
        except ValueError as e:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': str(e), 'code': 4276})
            }
        
        # 6. Risposta
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'status': 'updated',
                'messageId': message_id,
                'newState': state_str,
                'code': 3080
            })
        }
        
    except Exception as e:
        print(f"Error in update_support_message_state: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5079})
        }
