"""
Lambda: Get My Support Chats

Recupera tutte le chat di supporto dell'utente corrente.
Paginazione supportata via lastKey.
"""

import json
import os
import boto3
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError

from db_manager import ChatDBManager

# AWS clients/config
cognito_client = boto3.client('cognito-idp')
s3_client = boto3.client('s3')

USER_POOL_ID = os.environ.get('USER_POOL_ID', '')
PROFILE_PHOTOS_BUCKET = os.environ.get('PROFILE_PHOTOS_BUCKET', 'dev-beezey-profiles')


def get_user_name_from_cognito(user_id: str) -> str:
    """Recupera nome utente da Cognito con fallback su email."""
    try:
        if not USER_POOL_ID:
            return 'User'

        response = cognito_client.admin_get_user(
            UserPoolId=USER_POOL_ID,
            Username=user_id
        )

        user_attributes = {attr['Name']: attr['Value'] for attr in response.get('UserAttributes', [])}

        given_name = user_attributes.get('given_name', '')
        family_name = user_attributes.get('family_name', '')
        full_name_attr = user_attributes.get('name', '')
        email_attr = user_attributes.get('email', '')

        if given_name and family_name:
            return f"{given_name} {family_name}"
        if given_name:
            return given_name
        if family_name:
            return family_name
        if full_name_attr:
            return full_name_attr
        if email_attr:
            return email_attr
        return 'User'
    except ClientError as e:
        print(f"Error getting user name from Cognito for {user_id}: {e}")
        return 'User'
    except Exception as e:
        print(f"Unexpected error getting user name for {user_id}: {e}")
        return 'User'


def get_user_profile_photo(user_id: str) -> Optional[str]:
    """Genera un presigned URL per la foto profilo se esiste."""
    try:
        key = f"profiles/{user_id}/avatar.jpg"
        return s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': PROFILE_PHOTOS_BUCKET, 'Key': key},
            ExpiresIn=3600
        )
    except ClientError as e:
        print(f"Error generating profile photo URL for {user_id}: {e}")
        return None


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principale
    
    Query parameters:
    - limit: numero di chat da recuperare (default 20, max 100)
    - lastKey: chiave di paginazione
    
    Risposta:
    {
        "chats": [
            {
                "supportChatId": "support_...",
                "requesterType": "worker",
                "subject": "...",
                "status": "open",
                "createdAt": "ISO 8601",
                "lastMessageAt": "ISO 8601",
                "lastMessagePreview": "Testo...",
                "lastMessageState": "read"
            }
        ],
        "lastKey": "..." (se presente)
    }
    """
    
    try:
        # 1. Estrai user ID dal token Cognito
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Authentication required', 'code': 4277})
            }
        
        # 2. Parse query parameters
        query_params = event.get('queryStringParameters', {}) or {}
        
        limit = int(query_params.get('limit', 20))
        limit = min(limit, 100)  # Max 100
        limit = max(limit, 1)    # Min 1
        
        last_key_str = query_params.get('lastKey')
        last_key = None
        if last_key_str:
            try:
                # last_key è un JSON string encodato
                import base64
                last_key = json.loads(base64.b64decode(last_key_str).decode())
            except:
                last_key = None
        
        # 3. Query chat di supporto
        db_manager = ChatDBManager()
        chats, next_last_key = db_manager.get_support_chats_by_requester(
            user_id,
            limit=limit,
            last_key=last_key
        )
        
        # 4. Enrich con info interlocutore
        enriched_chats = []
        for chat in chats:
            chat_data = chat.to_api_response()

            if user_id == chat.requester_id:
                interlocutor_id = chat.assigned_to or 'beezey_support'
                if chat.assigned_to:
                    interlocutor_name = get_user_name_from_cognito(interlocutor_id)
                    interlocutor_photo = get_user_profile_photo(interlocutor_id)
                else:
                    interlocutor_name = 'Beezey Support'
                    interlocutor_photo = None
            else:
                interlocutor_id = chat.requester_id
                interlocutor_name = get_user_name_from_cognito(interlocutor_id)
                interlocutor_photo = get_user_profile_photo(interlocutor_id)

            chat_data['interlocutorId'] = interlocutor_id
            chat_data['interlocutorName'] = interlocutor_name
            if interlocutor_photo:
                chat_data['interlocutorPhoto'] = interlocutor_photo

            enriched_chats.append(chat_data)
        
        # 5. Encoding last_key per paginazione
        response_body = {
            'chats': enriched_chats,
            'code': 3081
        }
        
        if next_last_key:
            import base64
            encoded_key = base64.b64encode(json.dumps(next_last_key).encode()).decode()
            response_body['lastKey'] = encoded_key
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(response_body)
        }
        
    except Exception as e:
        print(f"Error in get_my_support_chats: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5080})
        }
