"""
Lambda: Set Support Message Sticker

Aggiunge uno sticker/reazione a un messaggio di supporto.
"""

import json
from typing import Dict, Any

from db_manager import ChatDBManager
from models import StickerTag


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principale
    
    Path parameters:
    - supportChatId: ID della chat
    - messageId: ID del messaggio
    
    Body:
    {
        "sticker": "thumbs_up | heart | smile | fire | check | question"
    }
    
    Risposta:
    {
        "status": "updated",
        "sticker": "heart"
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
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required', 'code': 4200})
            }
        
        # 2. Estrai path parameters
        path_params = event.get('pathParameters', {})
        support_chat_id = path_params.get('supportChatId')
        message_id = path_params.get('messageId')
        
        if not support_chat_id or not message_id:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'supportChatId and messageId are required', 'code': 4199})
            }
        
        # 3. Verifica autorizzazione
        db_manager = ChatDBManager()
        support_chat = db_manager.get_support_chat(support_chat_id)
        
        if not support_chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Support chat not found', 'code': 4202})
            }
        
        # Solo il richiedente, l'assegnatario o staff possono aggiungere sticker
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
                'body': json.dumps({'error': 'Forbidden', 'message': 'You are not authorized to add stickers in this chat', 'code': 4201})
            }
        
        # 4. Parse body
        body = json.loads(event.get('body', '{}'))
        sticker_str = body.get('sticker', '').lower()
        
        # Valida sticker
        valid_stickers = [s.value for s in StickerTag]
        if sticker_str not in valid_stickers:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': f'Invalid sticker. Valid values: {valid_stickers}', 'code': 4075})
            }
        
        # 5. Aggiorna sticker (timestamp opzionale - fa lookup tramite GSI se non fornito)
        try:
            db_manager.add_sticker_to_support_message(
                support_chat_id,
                message_id,
                sticker_str
            )
        except ValueError as e:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': str(e), 'code': 4254})
            }
        
        # 6. Risposta
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'status': 'updated',
                'messageId': message_id,
                'sticker': sticker_str,
                'code': 3060
            })
        }
        
    except Exception as e:
        print(f"Error in set_support_sticker: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5056})
        }
