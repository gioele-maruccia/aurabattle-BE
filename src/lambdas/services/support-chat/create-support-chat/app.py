"""
Lambda: Create Support Chat

Crea una nuova chat di supporto/assistenza.
Solo worker e company representative possono creare.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

from db_manager import ChatDBManager
from models import SupportChat, SupportChatStatus, SupportChatType, get_current_timestamp


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principale
    
    Expected request body:
    {
        "requesterType": "worker" | "company",
        "subject": "Titolo del supporto richiesto"
    }
    
    Risposta:
    {
        "supportChatId": "support_...",
        "status": "open",
        "createdAt": "ISO 8601"
    }
    """
    
    try:
        # 1. Estrai user ID dal token Cognito (authorizer)
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required', 'code': 4187})
            }
        
        # Estrai il ruolo dell'utente
        user_roles = claims.get('cognito:groups', [])
        
        # 2. Parse body
        body = json.loads(event.get('body', '{}'))
        requester_type_str = body.get('requesterType', '').lower()
        subject = body.get('subject', '')
        
        # Validazione
        if requester_type_str not in ['worker', 'company']:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'Invalid requesterType. Must be worker or company', 'code': 4186})
            }
        
        if not subject or len(subject) < 5:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'Subject is required and must be at least 5 characters', 'code': 4245})
            }
        
        # 3. Autorizzazione: verifica che l'utente abbia il ruolo corretto
        requester_type = SupportChatType[requester_type_str.upper()]
        
        if requester_type == SupportChatType.WORKER:
            if 'workers' not in user_roles:
                return {
                    'statusCode': 403,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({'error': 'Forbidden', 'message': 'Only workers can create worker support chats', 'code': 4246})
                }
        elif requester_type == SupportChatType.COMPANY:
            if 'company_representatives' not in user_roles and 'companies' not in user_roles:
                return {
                    'statusCode': 403,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({'error': 'Forbidden', 'message': 'Only company representatives can create company support chats', 'code': 4247})
                }
        
        # 4. Crea chat di supporto
        db_manager = ChatDBManager()
        
        support_chat_id = f"support_{uuid.uuid4().hex[:16]}"
        
        support_chat = SupportChat(
            support_chat_id=support_chat_id,
            requester_id=user_id,
            requester_type=requester_type,
            created_at=get_current_timestamp(),
            status=SupportChatStatus.OPEN,
            subject=subject
        )
        
        db_manager.create_support_chat(support_chat)
        
        # 5. Risposta
        return {
            'statusCode': 201,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'supportChatId': support_chat_id,
                'requesterType': requester_type.value,
                'subject': subject,
                'status': SupportChatStatus.OPEN.value,
                'createdAt': support_chat.created_at,
                'code': 3057
            })
        }
        
    except ValueError as e:
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': str(e), 'code': 4248})
        }
    except Exception as e:
        print(f"Error in create_support_chat: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5072})
        }
