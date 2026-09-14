"""
Delete Chat Lambda

Questa Lambda gestisce la "cancellazione" logica di una chat,
impostando lo stato a "deleted" invece di rimuoverla fisicamente dal DB.

Endpoint: DELETE /chats/{chat_id}
Auth: Cognito JWT (solo partecipanti della chat possono cancellarla)
"""

import json
import os
from typing import Dict, Any

# Layer imports
from models import ChatStatus
from db_manager import ChatDBManager


def get_user_id_from_event(event: Dict[str, Any]) -> str:
    """Estrae l'user ID dal token Cognito"""
    try:
        claims = event['requestContext']['authorizer']['claims']
        return claims.get('sub', claims.get('cognito:username', ''))
    except (KeyError, TypeError):
        return ''


def create_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Crea una risposta API Gateway formattata"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
            'Access-Control-Allow-Methods': 'DELETE,OPTIONS'
        },
        'body': json.dumps(body)
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler per DELETE /chats/{chat_id}
    
    Imposta lo stato della chat a "deleted" (soft delete).
    Solo i partecipanti della chat possono cancellarla.
    """
    print(f"Delete chat event: {json.dumps(event)}")
    
    try:
        # Estrai chat_id dal path
        chat_id = event.get('pathParameters', {}).get('chat_id')
        if not chat_id:
            return create_response(400, {
                'error': 'Missing chat_id in path'
            })
        
        # Estrai user_id dal token
        user_id = get_user_id_from_event(event)
        if not user_id:
            return create_response(401, {
                'error': 'Unauthorized - Invalid token'
            })
        
        print(f"User {user_id} requesting to delete chat {chat_id}")
        
        # Inizializza DB manager
        db_manager = ChatDBManager()
        
        # Recupera la chat
        chat = db_manager.get_chat(chat_id)
        if not chat:
            return create_response(404, {
                'error': 'Chat not found'
            })
        
        # Verifica che l'utente sia un partecipante della chat
        is_worker = (user_id == chat.worker_id)
        is_company_rep = (user_id == chat.company_representative_id)
        
        if not is_worker and not is_company_rep:
            return create_response(403, {
                'error': 'Forbidden - You are not a participant of this chat'
            })
        
        # Verifica che la chat non sia già deleted
        if chat.status == ChatStatus.DELETED:
            return create_response(400, {
                'error': 'Chat is already deleted'
            })
        
        # Aggiorna lo stato a "deleted"
        db_manager.update_chat_status(chat_id, ChatStatus.DELETED)
        
        print(f"Chat {chat_id} marked as deleted by user {user_id}")
        
        return create_response(200, {
            'message': 'Chat deleted successfully',
            'chatId': chat_id,
            'status': 'deleted'
        })
        
    except ValueError as e:
        print(f"Validation error: {e}")
        return create_response(400, {
            'error': str(e)
        })
    except Exception as e:
        print(f"Error deleting chat: {e}")
        return create_response(500, {
            'error': 'Internal server error',
            'details': str(e)
        })
