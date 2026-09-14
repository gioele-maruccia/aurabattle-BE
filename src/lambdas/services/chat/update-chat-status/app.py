"""
Update Chat Status Lambda

Questa Lambda gestisce l'aggiornamento dello stato di una chat.

Endpoint: PATCH /chats/{chat_id}/status
Auth: Cognito JWT (solo partecipanti della chat possono modificare lo stato)
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
            'Access-Control-Allow-Methods': 'PATCH,OPTIONS'
        },
        'body': json.dumps(body)
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler per PATCH /chats/{chat_id}/status
    
    Body:
    {
        "status": "active" | "archived" | "closed" | "deleted"
    }
    
    Solo i partecipanti della chat possono modificare lo stato.
    """
    print(f"Update chat status event: {json.dumps(event)}")
    
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
        
        # Estrai body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return create_response(400, {
                'error': 'Invalid JSON in request body'
            })
        
        new_status_str = body.get('status')
        if not new_status_str:
            return create_response(400, {
                'error': 'Missing status in request body'
            })
        
        # Valida lo stato
        valid_statuses = ['active', 'archived', 'closed', 'deleted']
        if new_status_str not in valid_statuses:
            return create_response(400, {
                'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
            })
        
        # Converti in enum
        new_status = ChatStatus[new_status_str.upper()]
        
        print(f"User {user_id} requesting to update chat {chat_id} to status {new_status_str}")
        
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
        
        # Verifica che lo stato sia diverso da quello attuale
        if chat.status == new_status:
            return create_response(400, {
                'error': f'Chat already has status {new_status_str}'
            })
        
        # Aggiorna lo stato
        db_manager.update_chat_status(chat_id, new_status)
        
        print(f"Chat {chat_id} status updated to {new_status_str} by user {user_id}")
        
        return create_response(200, {
            'message': 'Chat status updated successfully',
            'chatId': chat_id,
            'status': new_status_str,
            'previousStatus': chat.status.value
        })
        
    except ValueError as e:
        print(f"Validation error: {e}")
        return create_response(400, {
            'error': str(e)
        })
    except Exception as e:
        print(f"Unexpected error: {e}")
        return create_response(500, {
            'error': 'Internal server error'
        })
