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
        
        if not user_id:
            return {
                'statusCode': 401,
                'body': json.dumps({'error': 'Unauthorized'})
            }
        
        # 2. Estrai path parameters
        path_params = event.get('pathParameters', {})
        support_chat_id = path_params.get('supportChatId')
        message_id = path_params.get('messageId')
        
        if not support_chat_id or not message_id:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'supportChatId and messageId are required'})
            }
        
        # 3. Verifica autorizzazione
        db_manager = ChatDBManager()
        support_chat = db_manager.get_support_chat(support_chat_id)
        
        if not support_chat:
            return {
                'statusCode': 404,
                'body': json.dumps({'error': 'Support chat not found'})
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
                'body': json.dumps({'error': 'Forbidden'})
            }
        
        # 4. Parse body
        body = json.loads(event.get('body', '{}'))
        state_str = body.get('state', '').lower()
        
        # Valida stato
        valid_states = ['sent', 'delivered', 'read']
        if state_str not in valid_states:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': f'Invalid state. Must be one of: {valid_states}'})
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
                'statusCode': 404,
                'body': json.dumps({'error': str(e)})
            }
        
        # 6. Risposta
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'status': 'updated',
                'messageId': message_id,
                'newState': state_str
            })
        }
        
    except Exception as e:
        print(f"Error in update_support_message_state: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }
