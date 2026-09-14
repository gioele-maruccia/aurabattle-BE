"""
Lambda: Get My Chats
Restituisce la lista delle chat personali dell'utente con foto profili e dettagli
"""

import json
import os
import boto3
from typing import Dict, Any, List, Optional
from botocore.exceptions import ClientError

# Import dal layer condiviso
from models import Chat, ChatStatus, MessageState
from db_manager import ChatDBManager

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')
cognito_client = boto3.client('cognito-idp')

# Environment variables
CHATS_TABLE_NAME = os.environ['CHATS_TABLE_NAME']
COMPANIES_TABLE_NAME = os.environ.get('COMPANIES_TABLE_NAME', 'dev-Companies')
BOOKINGS_TABLE_NAME = os.environ.get('BOOKINGS_TABLE_NAME', 'dev-Bookings')
JOB_LISTINGS_TABLE_NAME = os.environ.get('JOB_LISTINGS_TABLE_NAME', 'dev-JobListings')
USER_POOL_ID = os.environ.get('USER_POOL_ID', '')

# Initialize DB manager
db_manager = ChatDBManager()
bookings_table = dynamodb.Table(BOOKINGS_TABLE_NAME)
job_listings_table = dynamodb.Table(JOB_LISTINGS_TABLE_NAME)


def get_user_profile_photo(user_id: str, user_type: str) -> Optional[str]:
    """
    Recupera l'URL della foto profilo utente da S3 o DynamoDB
    
    Args:
        user_id: ID utente
        user_type: 'worker' o 'company'
    
    Returns:
        URL foto profilo o None
    """
    try:
        if user_type == 'company':
            # Per company representative, cerca nella tabella Companies
            companies_table = dynamodb.Table(COMPANIES_TABLE_NAME)
            response = companies_table.get_item(
                Key={'userId': user_id}
            )
            
            if 'Item' in response:
                item = response['Item']
                # Restituisci logo aziendale se presente
                if 'logoUrl' in item and item['logoUrl']:
                    return item['logoUrl']
        
        # Fallback: cerca foto profilo generica dell'utente in S3
        # Pattern: profiles/{userId}/avatar.jpg
        bucket_name = os.environ.get('PROFILE_PHOTOS_BUCKET', 'dev-beezey-profiles')
        key = f"profiles/{user_id}/avatar.jpg"
        
        # Genera presigned URL valido per 1 ora
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': key},
            ExpiresIn=3600
        )
        return url
        
    except ClientError as e:
        print(f"Error getting profile photo for {user_id}: {e}")
        return None


def get_user_name_from_cognito(user_id: str) -> str:
    """
    Recupera il nome dell'utente da Cognito User Pool
    
    Args:
        user_id: Cognito user sub (UUID)
    
    Returns:
        Nome completo (given_name + family_name) o fallback se non trovato
    """
    try:
        if not USER_POOL_ID:
            print("USER_POOL_ID not configured, returning generic name")
            return 'User'
        
        # Recupera gli attributi dell'utente da Cognito
        response = cognito_client.admin_get_user(
            UserPoolId=USER_POOL_ID,
            Username=user_id
        )
        
        # Estrai given_name e family_name
        user_attributes = {}
        for attr in response.get('UserAttributes', []):
            user_attributes[attr['Name']] = attr['Value']
        
        given_name = user_attributes.get('given_name', '')
        family_name = user_attributes.get('family_name', '')
        full_name_attr = user_attributes.get('name', '')
        email_attr = user_attributes.get('email', '')
        
        # Componi il nome completo
        if given_name and family_name:
            return f"{given_name} {family_name}"
        elif given_name:
            return given_name
        elif family_name:
            return family_name
        elif full_name_attr:
            return full_name_attr
        elif email_attr:
            return email_attr
        else:
            return 'User'
    
    except ClientError as e:
        print(f"Error getting user name from Cognito for {user_id}: {e}")
        return 'User'
    except Exception as e:
        print(f"Unexpected error getting user name for {user_id}: {e}")
        return 'User'


def get_company_info(company_representative_id: str) -> Dict[str, Any]:
    """
    Recupera informazioni azienda dal rappresentante
    
    Args:
        company_representative_id: User ID del rappresentante
    
    Returns:
        Dict con companyId, companyName, companyLogo
    """
    try:
        companies_table = dynamodb.Table(COMPANIES_TABLE_NAME)
        response = companies_table.get_item(
            Key={'userId': company_representative_id}
        )
        
        if 'Item' in response:
            item = response['Item']
            return {
                'companyId': item.get('companyId'),
                'companyName': item.get('businessName', 'Azienda'),
                'companyLogo': item.get('logoUrl')
            }
    except ClientError as e:
        print(f"Error getting company info: {e}")
    
    return {
        'companyId': None,
        'companyName': 'Azienda',
        'companyLogo': None
    }


def get_booking_details(booking_id: str) -> Dict[str, Any]:
    """
    Recupera dettagli del booking DINAMICAMENTE dalla tabella Bookings
    Questo garantisce che le date siano sempre aggiornate
    
    Args:
        booking_id: ID del booking
    
    Returns:
        Dict con startDate, endDate, status del booking
    """
    try:
        response = bookings_table.get_item(
            Key={'bookingId': booking_id}
        )
        
        if 'Item' in response:
            booking = response['Item']
            return {
                'startDate': booking.get('startDate'),
                'endDate': booking.get('endDate'),
                'status': booking.get('status')
            }
    except ClientError as e:
        print(f"Error getting booking details for {booking_id}: {e}")
    except Exception as e:
        print(f"Unexpected error getting booking details: {e}")
    
    return {
        'startDate': None,
        'endDate': None,
        'status': None
    }


def get_job_name_from_listing(listing_id: str) -> Optional[str]:
    """
    Recupera il titolo del job listing dalla tabella JobListings.
    Usato come fallback quando jobName non è in cache nel record Chat
    (es. chat create prima dell'introduzione del campo jobName).

    Args:
        listing_id: ID del job listing

    Returns:
        Titolo del listing o None se non trovato
    """
    try:
        response = job_listings_table.get_item(
            Key={'listingId': listing_id}
        )
        if 'Item' in response:
            return response['Item'].get('title')
    except Exception as e:
        print(f"Error getting job name for listing {listing_id}: {e}")
    return None


def enrich_chat_with_profiles(chat: Chat, current_user_id: str) -> Dict[str, Any]:
    """
    Costruisce il payload ChatListItem (swagger) per una chat.
    Restituisce SOLO i campi definiti in swagger/components/schemas/chat.yml#ChatListItem.
    Nessun campo interno (workerId, companyRepresentativeId, ecc.) viene esposto.

    Args:
        chat: Oggetto Chat
        current_user_id: ID utente corrente

    Returns:
        Dict con i soli campi ChatListItem dello swagger
    """
    # Recupera date booking DINAMICAMENTE (sempre aggiornate)
    booking_details = get_booking_details(chat.booking_id)

    # jobName: usa il campo della chat oppure lo recupera da JobListings
    job_name = chat.job_name
    if not job_name and chat.listing_id:
        job_name = get_job_name_from_listing(chat.listing_id)

    # Stato ultimo messaggio come stringa
    last_message_state = chat.last_message_state.value if chat.last_message_state else None

    # Flag di lettura dell'ultimo messaggio:
    # - mittente != beezey_system → entrambi True (il campo non è applicabile)
    # - mittente == beezey_system → rispecchia i flag reali del messaggio
    if chat.last_message_sender_id != 'beezey_system':
        last_msg_read_worker  = True
        last_msg_read_company = True
    else:
        last_msg_read_worker  = bool(chat.last_message_read_worker)   # None → False
        last_msg_read_company = bool(chat.last_message_read_company)  # None → False

    # Determina chi è l'interlocutore e costruisce la risposta
    if current_user_id == chat.worker_id:
        # L'utente è il worker → l'interlocutore è il company representative
        interlocutor_id = chat.company_representative_id
        company_info = get_company_info(interlocutor_id)

        return {
            # ── Campi ChatListItem ──────────────────────────────────────────
            'chatId': chat.chat_id,
            'bookingId': chat.booking_id,
            'listingId': chat.listing_id,
            'status': chat.status.value,
            'jobName': job_name,
            'startDate': booking_details['startDate'],
            'endDate': booking_details['endDate'],
            'bookingStatus': booking_details['status'],
            'createdAt': chat.created_at,
            'lastMessageAt': chat.last_message_at,
            'lastMessagePreview': chat.last_message_preview,
            'lastMessageState': last_message_state,
            'lastMessageSenderId': chat.last_message_sender_id,            'lastMessageReadWorker': last_msg_read_worker,
            'lastMessageReadCompany': last_msg_read_company,            # ── Solo per la vista worker ─────────────────────────────────────
            'companyId': company_info['companyId'],
            'companyName': company_info['companyName'],
            'companyLogo': company_info['companyLogo'],
            # ── Interlocutore ───────────────────────────────────────────────
            'interlocutorId': interlocutor_id,
            'interlocutorName': get_user_name_from_cognito(interlocutor_id),
            'interlocutorPhoto': get_user_profile_photo(interlocutor_id, 'company'),
        }

    else:
        # L'utente è il company representative → l'interlocutore è il worker
        interlocutor_id = chat.worker_id

        return {
            # ── Campi ChatListItem ──────────────────────────────────────────
            'chatId': chat.chat_id,
            'bookingId': chat.booking_id,
            'listingId': chat.listing_id,
            'status': chat.status.value,
            'jobName': job_name,
            'startDate': booking_details['startDate'],
            'endDate': booking_details['endDate'],
            'bookingStatus': booking_details['status'],
            'createdAt': chat.created_at,
            'lastMessageAt': chat.last_message_at,
            'lastMessagePreview': chat.last_message_preview,
            'lastMessageState': last_message_state,
            'lastMessageSenderId': chat.last_message_sender_id,            'lastMessageReadWorker': last_msg_read_worker,
            'lastMessageReadCompany': last_msg_read_company,            # companyId/companyName/companyLogo NON inclusi nella vista company
            # ── Interlocutore ───────────────────────────────────────────────
            'interlocutorId': interlocutor_id,
            'interlocutorName': get_user_name_from_cognito(interlocutor_id),
            'interlocutorPhoto': get_user_profile_photo(interlocutor_id, 'worker'),
        }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler Lambda per GET /chats
    Restituisce lista chat personali dell'utente
    """
    try:
        print(f"Event: {json.dumps(event)}")
        
        # Estrai user_id dal token Cognito
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        
        if not user_id:
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Unauthorized', 'message': 'User ID not found in token'})
            }
        
        print(f"Getting chats for user: {user_id}")
        
        try:
            # Cerca chat come worker
            worker_chats = db_manager.get_chats_by_worker(user_id)
        except Exception as e:
            print(f"Error getting worker chats: {e}")
            worker_chats = []
        
        try:
            # Cerca chat come company representative
            company_chats = db_manager.get_chats_by_company_representative(user_id)
        except Exception as e:
            print(f"Error getting company chats: {e}")
            # Fallback: scansione diretta tabella con filtro (più lento ma sicuro)
            company_chats = db_manager.get_chats_by_company_representative_scan(user_id)
        
        # Unisci le liste e filtra le chat deleted
        all_chats = [
            chat for chat in worker_chats + company_chats
            if chat.status != ChatStatus.DELETED
        ]
        
        # Ordina per ultimo messaggio (più recente prima)
        all_chats.sort(
            key=lambda c: c.last_message_at or c.created_at,
            reverse=True
        )
        
        # Arricchisci con foto profili
        enriched_chats = [
            enrich_chat_with_profiles(chat, user_id)
            for chat in all_chats
        ]
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'chats': enriched_chats,
                'count': len(enriched_chats)
            })
        }
    
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': str(e)
            })
        }
