"""
Lambda: Delete Support Chat

Elimina (soft delete) una chat di supporto.
Solo il richiedente può eliminare la propria chat.
"""

import json
from typing import Dict, Any

from db_manager import ChatDBManager


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principale
    
    Path parameters:
    - supportChatId: ID della chat
    
    Risposta:
    {
        "status": "deleted",
        "supportChatId": "support_..."
    }
    """
    
    try:
        # 1. Estrai user ID
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required', 'code': 4255})
            }
        
        # 2. Estrai supportChatId
        path_params = event.get('pathParameters', {})
        support_chat_id = path_params.get('supportChatId')
        
        if not support_chat_id:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'supportChatId is required', 'code': 4256})
            }
        
        # 3. Verifica esistenza e autorizzazione
        db_manager = ChatDBManager()
        support_chat = db_manager.get_support_chat(support_chat_id)
        
        if not support_chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Support chat not found', 'code': 4257})
            }
        
        # Solo il richiedente può eliminare (o admin staff)
        user_roles = claims.get('cognito:groups', [])
        if (user_id != support_chat.requester_id and 
            'beezey_admin' not in user_roles):
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Forbidden', 'message': 'You are not authorized to delete this chat', 'code': 4258})
            }
        
        # 4. Elimina (soft delete)
        db_manager.delete_support_chat(support_chat_id)
        
        # 5. Risposta
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'status': 'deleted',
                'supportChatId': support_chat_id,
                'code': 3077
            })
        }
        
    except Exception as e:
        print(f"Error in delete_support_chat: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5075})
        }
