"""
Update Support Chat Status Lambda

Questa Lambda gestisce l'aggiornamento dello stato di una support chat.

Endpoint: PATCH /support-chats/{support_chat_id}/status
Auth: Cognito JWT (requester o staff girolavoro possono modificare lo stato)
"""

import json
from typing import Dict, Any

# Layer imports
from models import SupportChatStatus
from db_manager import ChatDBManager


def get_user_info_from_event(event: Dict[str, Any]) -> tuple[str, list]:
    """Estrae user ID e gruppi dal token Cognito"""
    try:
        claims = event['requestContext']['authorizer']['claims']
        user_id = claims.get('sub', claims.get('cognito:username', ''))
        groups = claims.get('cognito:groups', [])
        if isinstance(groups, str):
            groups = [groups]
        return user_id, groups
    except (KeyError, TypeError):
        return '', []


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


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler per PATCH /support-chats/{support_chat_id}/status
    
    Body:
    {
        "status": "open" | "in_progress" | "resolved" | "closed" | "archived"
    }
    
    Il requester può modificare la propria chat.
    Lo staff girolavoro può modificare qualsiasi support chat.
    """
    print(f"Update support chat status event: {json.dumps(event)}")
    
    try:
        # Estrai support_chat_id dal path
        support_chat_id = event.get('pathParameters', {}).get('supportChatId')
        if not support_chat_id:
            return create_response(400, {
                'error': 'Missing supportChatId in path',
                'code': 4278
            })
        
        # Estrai user_id e gruppi dal token
        user_id, user_groups = get_user_info_from_event(event)
        if not user_id:
            return create_response(401, {
                'error': 'Unauthorized - Invalid token',
                'code': 4279
            })
        
        # Verifica se è staff girolavoro
        is_staff = 'beezey_staff' in user_groups or 'beezey_admin' in user_groups
        
        # Estrai body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return create_response(400, {
                'error': 'Invalid JSON in request body',
                'code': 4280
            })
        
        new_status_str = body.get('status')
        if not new_status_str:
            return create_response(400, {
                'error': 'Missing status in request body',
                'code': 4281
            })
        
        # Valida lo stato
        valid_statuses = ['open', 'in_progress', 'resolved', 'closed', 'archived']
        if new_status_str not in valid_statuses:
            return create_response(400, {
                'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}',
                'code': 4282
            })
        
        # Converti in enum
        try:
            new_status = SupportChatStatus[new_status_str.upper().replace('-', '_')]
        except KeyError:
            new_status = SupportChatStatus.IN_PROGRESS if new_status_str == 'in_progress' else None
            if not new_status:
                return create_response(400, {
                    'error': f'Invalid status value: {new_status_str}',
                    'code': 4283
                })
        
        print(f"User {user_id} (staff={is_staff}) requesting to update support chat {support_chat_id} to status {new_status_str}")
        
        # Inizializza DB manager
        db_manager = ChatDBManager()
        
        # Recupera la support chat
        support_chat = db_manager.get_support_chat(support_chat_id)
        if not support_chat:
            return create_response(404, {
                'error': 'Support chat not found',
                'code': 4284
            })
        
        # Verifica autorizzazione
        is_requester = (user_id == support_chat.requester_id)
        
        if not is_requester and not is_staff:
            return create_response(403, {
                'error': 'Forbidden - You are not authorized to modify this support chat',
                'code': 4285
            })
        
        # Verifica che lo stato sia diverso da quello attuale
        if support_chat.status == new_status:
            return create_response(400, {
                'error': f'Support chat already has status {new_status_str}',
                'code': 4286
            })
        
        # Aggiorna lo stato
        db_manager.update_support_chat_status(support_chat_id, new_status)
        
        print(f"Support chat {support_chat_id} status updated to {new_status_str} by user {user_id}")
        
        return create_response(200, {
            'message': 'Support chat status updated successfully',
            'supportChatId': support_chat_id,
            'status': new_status_str,
            'previousStatus': support_chat.status.value,
            'code': 3082
        })
        
    except ValueError as e:
        print(f"Validation error: {e}")
        return create_response(400, {
            'error': str(e),
            'code': 4287
        })
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return create_response(500, {
            'error': 'Internal server error',
            'code': 5081
        })
