"""
Lambda handler for WebSocket 'getChats' action.

Client invia:
  {"action": "getChats"}
  oppure con token opzionale per override identità (necessario se la WS connection
  è stata registrata con un userId diverso, es. dopo cambio account senza reconnect):
  {"action": "getChats", "token": "eyJ..."}

Server risponde sul WebSocket del client:
  {
    "action": "chats_list",
    "userId": "<userId-corrente>",
    "chats": [...],
    "count": N
  }

La struttura di ogni chat nella lista è identica alla risposta REST GET /chats,
tranne per 'interlocutorPhoto' che non viene inclusa (gli URL presigned scadono).

NOTA SICUREZZA: il token nel body NON viene verificato crittograficamente (firma),
ma viene usato solo il claim 'sub'. La sicurezza vera è garantita dalla connessione
WSS e dal JWT al $connect. Usare solo come workaround per connessioni stale.
"""

import base64
import json
import os
import sys
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger

# Add shared layer to path
sys.path.append('/opt/python')

from ws_manager import WebSocketManager
from db_manager import ChatDBManager
from models import Chat, ChatStatus

logger = Logger()


def decode_jwt_sub(token: str) -> Optional[str]:
    """
    Decodifica un JWT e restituisce il claim 'sub' (SENZA verifica firma).
    Usato come fallback per identificare l'utente quando la connectionId è stale
    (es. app non ha disconnesso WS al cambio account).
    """
    try:
        payload_b64 = token.split('.')[1]
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.b64decode(payload_b64))
        return payload.get('sub')
    except Exception as e:
        logger.warning(f"Could not decode JWT from message body: {e}")
        return None


# AWS clients
dynamodb = boto3.resource('dynamodb')
cognito_client = boto3.client('cognito-idp')

# Environment variables
COMPANIES_TABLE_NAME = os.environ.get('COMPANIES_TABLE_NAME', 'dev-Companies')
BOOKINGS_TABLE_NAME = os.environ.get('BOOKINGS_TABLE_NAME', 'dev-Bookings')
JOB_LISTINGS_TABLE_NAME = os.environ.get('JOB_LISTINGS_TABLE_NAME', 'dev-JobListings')
USER_POOL_ID = os.environ.get('USER_POOL_ID', '')

bookings_table = dynamodb.Table(BOOKINGS_TABLE_NAME)
job_listings_table = dynamodb.Table(JOB_LISTINGS_TABLE_NAME)


def get_user_name_from_cognito(user_id: str) -> str:
    """Recupera il nome dell'utente da Cognito."""
    try:
        if not USER_POOL_ID:
            return 'User'
        response = cognito_client.admin_get_user(
            UserPoolId=USER_POOL_ID,
            Username=user_id
        )
        attrs = {a['Name']: a['Value'] for a in response.get('UserAttributes', [])}
        given = attrs.get('given_name', '').strip()
        family = attrs.get('family_name', '').strip()
        if given or family:
            return f"{given} {family}".strip()
        return attrs.get('name', attrs.get('email', 'User'))
    except Exception as e:
        logger.warning(f"Could not get name from Cognito for {user_id}: {e}")
        return 'User'


def get_company_info(company_representative_id: str) -> Dict:
    """Recupera informazioni azienda dal rappresentante."""
    try:
        companies_table = dynamodb.Table(COMPANIES_TABLE_NAME)
        response = companies_table.get_item(Key={'userId': company_representative_id})
        if 'Item' in response:
            item = response['Item']
            return {
                'companyId': item.get('companyId'),
                'companyName': item.get('businessName', 'Azienda'),
                'companyLogo': item.get('logoUrl'),
            }
    except Exception as e:
        logger.warning(f"Could not get company info for {company_representative_id}: {e}")
    return {'companyId': None, 'companyName': 'Azienda', 'companyLogo': None}


def get_booking_details(booking_id: str) -> Dict:
    """Recupera dettagli del booking."""
    try:
        response = bookings_table.get_item(Key={'bookingId': booking_id})
        if 'Item' in response:
            b = response['Item']
            return {
                'startDate': b.get('startDate'),
                'endDate': b.get('endDate'),
                'status': b.get('status'),
            }
    except Exception as e:
        logger.warning(f"Could not get booking details for {booking_id}: {e}")
    return {'startDate': None, 'endDate': None, 'status': None}


def get_job_name_from_listing(listing_id: str) -> Optional[str]:
    """
    Recupera il titolo del job listing dalla tabella JobListings.
    Usato come fallback quando jobName non è in cache nel record Chat
    (es. chat create prima dell'introduzione del campo jobName).
    """
    try:
        response = job_listings_table.get_item(Key={'listingId': listing_id})
        if 'Item' in response:
            return response['Item'].get('title')
    except Exception as e:
        logger.warning(f"Could not get job name for listing {listing_id}: {e}")
    return None


def enrich_chat(chat: Chat, current_user_id: str) -> Dict:
    """
    Costruisce il payload ChatListItem (swagger) per una chat — versione WebSocket.
    Identica alla REST GET /chats, tranne per 'interlocutorPhoto' che è sempre None
    (gli URL presigned S3 scadono e non sono inviabili via WebSocket).
    Restituisce SOLO i campi definiti in swagger ChatListItem.
    """
    # Date booking sempre aggiornate
    booking = get_booking_details(chat.booking_id)

    # jobName con fallback su JobListings
    job_name = chat.job_name
    if not job_name and chat.listing_id:
        job_name = get_job_name_from_listing(chat.listing_id)

    last_state = chat.last_message_state.value if chat.last_message_state else None

    # Flag di lettura dell'ultimo messaggio:
    # - mittente != beezey_system → entrambi True (campo non applicabile)
    # - mittente == beezey_system → rispecchia i flag reali del messaggio
    if chat.last_message_sender_id != 'beezey_system':
        last_msg_read_worker  = True
        last_msg_read_company = True
    else:
        last_msg_read_worker  = bool(chat.last_message_read_worker)   # None → False
        last_msg_read_company = bool(chat.last_message_read_company)  # None → False

    if current_user_id == chat.worker_id:
        # Vista worker → interlocutore = company representative
        interlocutor_id = chat.company_representative_id
        company_info = get_company_info(interlocutor_id)
        return {
            'chatId': chat.chat_id,
            'bookingId': chat.booking_id,
            'workerId': chat.worker_id,
            'companyRepresentativeId': chat.company_representative_id,
            'listingId': chat.listing_id,
            'status': chat.status.value,
            'jobName': job_name,
            'startDate': booking['startDate'],
            'endDate': booking['endDate'],
            'bookingStatus': booking['status'],
            'createdAt': chat.created_at,
            'lastMessageAt': chat.last_message_at,
            'lastMessagePreview': chat.last_message_preview,
            'lastMessageState': last_state,
            'lastMessageSenderId': chat.last_message_sender_id,
            'lastMessageReadWorker': last_msg_read_worker,
            'lastMessageReadCompany': last_msg_read_company,
            'companyId': company_info['companyId'],
            'companyName': company_info['companyName'],
            'companyLogo': company_info['companyLogo'],
            'interlocutorId': interlocutor_id,
            'interlocutorName': get_user_name_from_cognito(interlocutor_id),
            'interlocutorPhoto': None,  # presigned URL non inviabile via WS
        }
    else:
        # Vista company representative → interlocutore = worker
        interlocutor_id = chat.worker_id
        return {
            'chatId': chat.chat_id,
            'bookingId': chat.booking_id,
            'workerId': chat.worker_id,
            'companyRepresentativeId': chat.company_representative_id,
            'listingId': chat.listing_id,
            'status': chat.status.value,
            'jobName': job_name,
            'startDate': booking['startDate'],
            'endDate': booking['endDate'],
            'bookingStatus': booking['status'],
            'createdAt': chat.created_at,
            'lastMessageAt': chat.last_message_at,
            'lastMessagePreview': chat.last_message_preview,
            'lastMessageState': last_state,
            'lastMessageSenderId': chat.last_message_sender_id,
            'lastMessageReadWorker': last_msg_read_worker,
            'lastMessageReadCompany': last_msg_read_company,
            'interlocutorId': interlocutor_id,
            'interlocutorName': get_user_name_from_cognito(interlocutor_id),
            'interlocutorPhoto': None,
        }


def _fetch_and_send_chats(user_id: str, connection_id: str, ws_manager: WebSocketManager, version: str) -> Dict[str, Any]:
    """
    Logica comune getChats: recupera, arricchisce e invia le chat al client.
    `version` è passato per logging / future differenze comportamentali.
    """
    db_manager = ChatDBManager()

    try:
        worker_chats = db_manager.get_chats_by_worker(user_id)
    except Exception as e:
        logger.warning(f"Error getting worker chats for {user_id}: {e}")
        worker_chats = []

    try:
        company_chats = db_manager.get_chats_by_company_representative(user_id)
    except Exception as e:
        logger.warning(f"Error getting company chats (index) for {user_id}: {e}")
        try:
            company_chats = db_manager.get_chats_by_company_representative_scan(user_id)
        except Exception as e2:
            logger.warning(f"Error getting company chats (scan) for {user_id}: {e2}")
            company_chats = []

    all_chats = [
        c for c in worker_chats + company_chats
        if c.status != ChatStatus.DELETED
    ]
    all_chats.sort(key=lambda c: c.last_message_at or c.created_at, reverse=True)
    enriched = [enrich_chat(c, user_id) for c in all_chats]

    ws_manager.send_to_connection(connection_id, {
        'action': 'chats_list',
        'version': version,
        'userId': user_id,
        'chats': enriched,
        'count': len(enriched),
    })

    logger.info(f"[{version}] Sent {len(enriched)} chats to connection {connection_id}")
    return {'statusCode': 200, 'body': json.dumps({'message': 'Chats sent'})}


def handle_legacy(user_id: str, connection_id: str, ws_manager: WebSocketManager) -> Dict[str, Any]:
    """Handler getChats — versione legacy (senza prefisso /v1)."""
    return _fetch_and_send_chats(user_id, connection_id, ws_manager, version='legacy')


def handle_v1(user_id: str, connection_id: str, ws_manager: WebSocketManager) -> Dict[str, Any]:
    """Handler getChats — versione v1. Attualmente identico a legacy."""
    return _fetch_and_send_chats(user_id, connection_id, ws_manager, version='v1')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle WebSocket 'getChats' action.

    Il client può specificare la versione nel body:
      {"action": "getChats"}              → legacy
      {"action": "getChats", "version": "1"}  → v1

    Event structure (API Gateway WebSocket):
    {
        "requestContext": {
            "connectionId": "abc123",
            "routeKey": "getChats",
            "authorizer": {"sub": "cognito-user-sub"}
        },
        "body": "{\"action\": \"getChats\", \"version\": \"1\"}"
    }
    """
    logger.info("getChats WebSocket event", extra={"event": event})

    connection_id = event['requestContext']['connectionId']
    authorizer = event['requestContext'].get('authorizer', {})
    user_id = authorizer.get('sub') or authorizer.get('principalId')

    ws_manager = WebSocketManager()

    # Parse body subito (serve sia per token che per version)
    body_raw = event.get('body') or '{}'
    try:
        body = json.loads(body_raw)
    except Exception:
        body = {}

    # Priorità 1: sub dall'authorizer Cognito
    # Priorità 2: token JWT nel body del messaggio (connessioni stale dopo cambio account)
    # Priorità 3: lookup userId dalla ConnectionManager table
    if not user_id:
        token_in_body = body.get('token')
        if token_in_body:
            user_id_from_token = decode_jwt_sub(token_in_body)
            if user_id_from_token:
                user_id = user_id_from_token
                logger.info(f"user_id resolved from JWT in message body: {user_id}")

    if not user_id:
        user_id = ws_manager.get_user_id_by_connection(connection_id)
        if user_id:
            logger.info(f"user_id resolved from ConnectionManager: {user_id}")

    if not user_id:
        logger.error("No user_id in authorizer, body token, or ConnectionManager")
        return {'statusCode': 401, 'body': json.dumps({'error': 'Unauthorized'})}

    # Routing per versione
    version = WebSocketManager.get_ws_version(body)
    logger.info(f"getChats routing to version={version}")

    try:
        if version == 'v1':
            return handle_v1(user_id, connection_id, ws_manager)
        else:
            return handle_legacy(user_id, connection_id, ws_manager)

    except Exception as e:
        logger.exception(f"Error in getChats handler: {e}")
        try:
            ws_manager.send_to_connection(connection_id, {
                'action': 'error',
                'code': 5000,
                'message': 'Errore interno nel recupero delle chat',
            })
        except Exception:
            pass
        return {'statusCode': 500, 'body': json.dumps({'error': 'Internal server error'})}
