"""
Lambda: Initiate Support Chat (Beezey → User)

Permette al backoffice Beezey di avviare una chat di supporto con un utente
(worker o company) conoscendo la sua email. Utile quando l'utente contatta
il supporto telefonico e il supporto vuole continuare via chat.
"""

import json
import sys
import os
import uuid
import boto3

sys.path.append('/opt/python')

from db_manager import ChatDBManager
from models import SupportChat, SupportChatStatus, SupportChatType, SupportMessage, MessageState, SenderType, generate_message_id, get_current_timestamp


def handler(event, context):
    """
    Handler principale - Backoffice avvia chat con un utente
    
    Body:
    {
        "targetUserEmail": "user@example.com",
        "subject": "Subject della chat",
        "requesterType": "worker" | "company",
        "initialMessage": "Messaggio iniziale opzionale da girolavoro"
    }
    
    Risposta:
    {
        "supportChatId": "support_...",
        "requesterId": "user-id",
        "requesterType": "worker",
        "subject": "...",
        "status": "open",
        "createdAt": "...",
        "messageId": "msg_..." (se initialMessage fornito)
    }
    """
    
    try:
        # 1. Verifica autorizzazione - solo backoffice può iniziare chat
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        user_roles = claims.get('cognito:groups', [])
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required', 'code': 4263})
            }
        
        # Solo staff Beezey può iniziare chat per gli utenti
        if not any(role in user_roles for role in ['admins', 'beezey_staff', 'beezey_admin']):
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Forbidden', 'message': 'Only girolavoro staff can initiate support chats', 'code': 4264})
            }
        
        # 2. Parse body
        body = json.loads(event.get('body', '{}'))
        target_user_email = body.get('targetUserEmail', '').strip()
        subject = body.get('subject', '').strip()
        requester_type_str = body.get('requesterType', '').lower()
        initial_message = body.get('initialMessage', '').strip()
        
        # Validazione
        if not target_user_email:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'targetUserEmail is required', 'code': 4265})
            }
        
        if requester_type_str not in ['worker', 'company']:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'Invalid requesterType. Must be worker or company', 'code': 4266})
            }
        
        if not subject or len(subject) < 5:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'Subject is required and must be at least 5 characters', 'code': 4267})
            }
        
        requester_type = SupportChatType[requester_type_str.upper()]
        
        # 3. Cerca utente target nel Cognito
        cognito = boto3.client('cognito-idp', region_name=os.environ.get('AWS_REGION', 'eu-south-1'))
        user_pool_id = os.environ.get('COGNITO_USER_POOL_ID')
        
        try:
            response = cognito.admin_get_user(
                UserPoolId=user_pool_id,
                Username=target_user_email
            )
            
            target_user_id = None
            target_profile_type = None
            
            for attr in response['UserAttributes']:
                if attr['Name'] == 'sub':
                    target_user_id = attr['Value']
                elif attr['Name'] == 'custom:profile_type':
                    target_profile_type = attr['Value']
            
            if not target_user_id:
                return {
                    'statusCode': 404,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({'error': 'Not Found', 'message': 'User not found', 'code': 4268})
                }
            
            # Verifica che il tipo corrisponda
            if target_profile_type != requester_type_str:
                return {
                    'statusCode': 409,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({'error': 'Conflict', 'message': f'User is {target_profile_type}, but requesterType is {requester_type_str}. They must match.', 'code': 4269})
                }
        
        except cognito.exceptions.UserNotFoundException:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': f'User {target_user_email} not found in system', 'code': 4270})
            }
        except Exception as e:
            print(f"Error finding user in Cognito: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Internal Server Error', 'message': 'Error looking up user', 'code': 5077})
            }
        
        # 4. Crea chat di supporto
        db_manager = ChatDBManager()
        
        support_chat_id = f"support_{uuid.uuid4().hex[:16]}"
        
        support_chat = SupportChat(
            support_chat_id=support_chat_id,
            requester_id=target_user_id,
            requester_type=requester_type,
            subject=subject,
            status=SupportChatStatus.OPEN,
            assigned_to=None,  # Non assegnata ancora
            created_at=get_current_timestamp(),
            last_message_at=get_current_timestamp()
        )
        
        db_manager.create_support_chat(support_chat)
        
        response_data = {
            'supportChatId': support_chat_id,
            'requesterId': target_user_id,
            'requesterType': requester_type_str,
            'subject': subject,
            'status': 'open',
            'createdAt': support_chat.created_at
        }
        
        # 5. Se c'è un messaggio iniziale, crealo
        if initial_message:
            message = SupportMessage(
                support_chat_id=support_chat_id,
                message_id=generate_message_id(),
                sender_id=user_id,  # Beezey staff che ha iniziato la chat
                sender_type=SenderType.BEEZEY,
                message_text=initial_message,
                timestamp=get_current_timestamp(),
                state=MessageState.SENT,
                attachments=[],
                sticker=None
            )
            
            db_manager.create_support_message(message)
            response_data['messageId'] = message.message_id
            response_data['initialMessage'] = initial_message
        
        return {
            'statusCode': 201,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({**response_data, 'code': 3079})
        }
    
    except Exception as e:
        print(f"Error in initiate_support_chat: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5078})
        }
