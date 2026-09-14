"""
Lambda: Backoffice - Get Chats With Beezey Help Requested

Lista chat dove è stato richiesto l'aiuto di Beezey.
Solo staff Beezey può accedere.
"""

import json
import sys
from typing import Dict, Any, List

sys.path.append('/opt/python')

from db_manager import ChatDBManager
from models import MessageState


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principale
    
    Ritorna lista di chat dove ci sono messaggi con @Beezey
    
    Query params:
    - limit: max results (default 50)
    """
    
    try:
        # 1. Verifica autorizzazione BACKOFFICE
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        user_groups = claims.get('cognito:groups', '')
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required'})
            }
        
        # Parse Cognito groups
        if isinstance(user_groups, str):
            user_groups = [g.strip() for g in user_groups.split(',')] if user_groups else []
        
        # Solo staff Beezey può accedere
        is_staff = any(role in user_groups for role in ['beezey_staff', 'beezey_admin', 'admins'])
        if not is_staff:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Forbidden', 'message': 'Only girolavoro staff can access this endpoint'})
            }
        
        # 2. Parse query params
        query_params = event.get('queryStringParameters') or {}
        limit = int(query_params.get('limit', '50'))
        
        # 3. Get tutte le chat e filtra quelle con messaggi @Beezey
        db_manager = ChatDBManager()
        
        # Scan tutte le chat
        all_chats = db_manager.chats_table.scan()
        
        print(f"Found {len(all_chats.get('Items', []))} total items in chats table")
        
        chats_with_help = []
        chats_scanned = 0
        
        for item in all_chats.get('Items', []):
            # La tabella Chats usa chatId direttamente, non PK
            chat_id = item.get('chatId')
            if not chat_id:
                continue
            
            chats_scanned += 1
            
            # Get messaggi di questa chat per verificare se c'è @Beezey
            # get_messages restituisce (messages, next_key)
            messages, _ = db_manager.get_messages(chat_id, limit=100)
            print(f"Chat {chat_id}: found {len(messages)} messages")
            
            # Cerca messaggi con @Beezey (case insensitive)
            has_beezey_request = False
            beezey_messages = []
            
            for msg in messages:
                msg_text = msg.message_text if hasattr(msg, 'message_text') else str(msg)
                if '@girolavoro' in msg_text.lower():
                    has_beezey_request = True
                    beezey_messages.append(msg)
            
            if has_beezey_request:
                # Ordina i messaggi @Beezey per timestamp DESC per prendere il più recente
                beezey_messages.sort(
                    key=lambda m: m.timestamp if hasattr(m, 'timestamp') else '',
                    reverse=True
                )
                last_beezey_msg = beezey_messages[0] if beezey_messages else None
                
                # Converti il messaggio in formato API leggibile
                beezey_msg_dict = None
                if last_beezey_msg:
                    if hasattr(last_beezey_msg, 'to_api_response'):
                        beezey_msg_dict = last_beezey_msg.to_api_response()
                    elif isinstance(last_beezey_msg, dict):
                        beezey_msg_dict = last_beezey_msg
                    else:
                        # Fallback: estrai i campi manualmente se è un oggetto Message
                        beezey_msg_dict = {
                            'message_id': getattr(last_beezey_msg, 'message_id', None),
                            'sender_id': getattr(last_beezey_msg, 'sender_id', None),
                            'sender_type': str(getattr(last_beezey_msg, 'sender_type', None)),
                            'message_text': getattr(last_beezey_msg, 'message_text', ''),
                            'timestamp': getattr(last_beezey_msg, 'timestamp', None),
                            'state': str(getattr(last_beezey_msg, 'state', None))
                        }
                
                chats_with_help.append({
                    'chat_id': chat_id,
                    'worker_id': item.get('workerId'),
                    'company_representative_id': item.get('companyRepresentativeId'),
                    'booking_id': item.get('bookingId'),
                    'created_at': item.get('createdAt'),
                    'last_message_at': item.get('lastMessageAt'),
                    'last_beezey_request': beezey_msg_dict,
                    'message_count': len(messages),
                    'status': item.get('status')
                })
            
            # Limit risultati
            if len(chats_with_help) >= limit:
                break
        
        print(f"Scanned {chats_scanned} chats, found {len(chats_with_help)} with @Beezey requests")
        
        # 4. Ordina per timestamp più recente
        chats_with_help.sort(
            key=lambda x: x.get('last_beezey_request', {}).get('timestamp', ''),
            reverse=True
        )
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'chats': chats_with_help,
                'count': len(chats_with_help)
            })
        }
        
    except Exception as e:
        print(f"Error getting chats with help requests: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error'})
        }
