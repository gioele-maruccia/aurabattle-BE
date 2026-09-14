"""
WebSocket Manager - Helper per gestire connessioni WebSocket e broadcast messaggi.
Usa API Gateway Management API per inviare messaggi ai client connessi.
"""

import json
import os
from typing import Any, Dict, List, Optional
from aws_lambda_powertools import Logger

import boto3
from botocore.exceptions import ClientError

logger = Logger()
dynamodb = boto3.resource('dynamodb')

CONNECTION_MANAGER_TABLE_NAME = os.environ.get('CONNECTION_MANAGER_TABLE_NAME')
WEBSOCKET_API_ENDPOINT = os.environ.get('WEBSOCKET_API_ENDPOINT')


class WebSocketManager:
    """Manager per connessioni WebSocket e broadcast messaggi."""
    
    def __init__(self):
        self.connection_table = dynamodb.Table(CONNECTION_MANAGER_TABLE_NAME)
        
        # API Gateway Management API client
        # endpoint_url deve essere: https://{api-id}.execute-api.{region}.amazonaws.com/{stage}
        self.apigw_management = boto3.client(
            'apigatewaymanagementapi',
            endpoint_url=WEBSOCKET_API_ENDPOINT
        )
    
    @staticmethod
    def get_ws_version(body: Dict[str, Any]) -> str:
        """
        Legge il campo 'version' dal body del messaggio WS.
        Valori accettati per v1: '1', 'v1'.
        Qualsiasi altro valore (o campo assente) = 'legacy'.

        Esempio client:
          {"action": "getChats", "version": "1"}   → v1
          {"action": "getChats"}                   → legacy
        """
        version = str(body.get('version', '')).lower().strip()
        return 'v1' if version in ('1', 'v1') else 'legacy'

    def get_user_id_by_connection(self, connection_id: str) -> Optional[str]:
        """
        Recupera l'userId associato a una connectionId.
        Utilizzato dai route handler WebSocket che non ricevono il Cognito authorizer
        (solo $connect riceve il contesto dell'authorizer).

        Args:
            connection_id: ID della connessione WebSocket

        Returns:
            userId o None se non trovato
        """
        try:
            response = self.connection_table.get_item(
                Key={'connectionId': connection_id}
            )
            item = response.get('Item')
            if item:
                return item.get('userId')
            logger.warning(f"Connection {connection_id} not found in ConnectionManager")
            return None
        except ClientError as e:
            logger.exception(f"Error looking up connection {connection_id}", extra={"error": str(e)})
            return None

    def get_user_connections(self, user_id: str) -> List[str]:
        """
        Ottieni tutte le connessioni attive di un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Lista di connectionId attivi
        """
        try:
            response = self.connection_table.query(
                IndexName='userId-index',
                KeyConditionExpression='userId = :uid',
                ExpressionAttributeValues={':uid': user_id}
            )
            
            connections = [item['connectionId'] for item in response.get('Items', [])]
            logger.info(f"Found {len(connections)} connections for user {user_id}")
            return connections
            
        except ClientError as e:
            logger.exception(f"Error querying connections for user {user_id}", extra={"error": str(e)})
            return []
    
    def send_to_connection(self, connection_id: str, data: Dict[str, Any]) -> bool:
        """
        Invia un messaggio a una connessione specifica.
        
        Args:
            connection_id: ID della connessione WebSocket
            data: Payload da inviare (sarà convertito in JSON)
            
        Returns:
            True se inviato con successo, False altrimenti
        """
        try:
            payload = self._normalize_ws_payload(data)
            self.apigw_management.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps(payload).encode('utf-8')
            )
            logger.debug(f"Message sent to connection {connection_id}")
            return True
            
        except self.apigw_management.exceptions.GoneException:
            # Connessione non più valida, rimuovila dal DB
            logger.warning(f"Connection {connection_id} is gone, removing from DB")
            self._remove_stale_connection(connection_id)
            return False
            
        except ClientError as e:
            logger.exception(f"Error sending to connection {connection_id}", extra={"error": str(e)})
            return False
    
    def broadcast_to_user(self, user_id: str, data: Dict[str, Any]) -> int:
        """
        Invia un messaggio a tutte le connessioni attive di un utente.
        
        Args:
            user_id: ID dell'utente destinatario
            data: Payload da inviare
            
        Returns:
            Numero di connessioni a cui è stato inviato con successo
        """
        connections = self.get_user_connections(user_id)
        successful = 0
        
        for conn_id in connections:
            if self.send_to_connection(conn_id, data):
                successful += 1
        
        logger.info(f"Broadcast to user {user_id}: {successful}/{len(connections)} successful")
        return successful
    
    def broadcast_to_chat(self, chat_id: str, sender_id: str, data: Dict[str, Any]) -> Dict[str, int]:
        """
        Invia un messaggio a tutti i partecipanti di una chat (escluso sender).
        
        Args:
            chat_id: ID della chat
            sender_id: ID del mittente (escluso dal broadcast)
            data: Payload da inviare
            
        Returns:
            Dict con statistiche: {'worker': count, 'company': count}
        """
        from db_manager import ChatDBManager
        from models import Chat
        
        db_manager = ChatDBManager()
        
        try:
            # Ottieni info chat per determinare worker e company
            chat = db_manager.get_chat(chat_id)
            if not chat:
                logger.error(f"Chat {chat_id} not found")
                return {'worker': 0, 'company': 0}
            
            stats = {'worker': 0, 'company': 0}
            
            # Broadcast a worker (se non è il sender)
            if chat.worker_id != sender_id:
                count = self.broadcast_to_user(chat.worker_id, data)
                stats['worker'] = count
            
            # Broadcast a company representative (se non è il sender)
            if chat.company_representative_id != sender_id:
                count = self.broadcast_to_user(chat.company_representative_id, data)
                stats['company'] = count
            
            logger.info(
                f"Broadcast to chat {chat_id} completed",
                extra={"stats": stats}
            )
            return stats
            
        except Exception as e:
            logger.exception(f"Error broadcasting to chat {chat_id}", extra={"error": str(e)})
            return {'worker': 0, 'company': 0}

    def broadcast_to_all_chat_participants(self, chat_id: str, data: Dict[str, Any]) -> Dict[str, int]:
        """
        Invia un messaggio a TUTTI i partecipanti di una chat (incluso il sender).
        Utile per eventi come 'chat_updated' dove tutti i dispositivi devono aggiornarsi.
        
        Args:
            chat_id: ID della chat
            data: Payload da inviare
            
        Returns:
            Dict con statistiche: {'worker': count, 'company': count}
        """
        from db_manager import ChatDBManager
        
        db_manager = ChatDBManager()
        
        try:
            chat = db_manager.get_chat(chat_id)
            if not chat:
                logger.error(f"Chat {chat_id} not found for broadcast_to_all")
                return {'worker': 0, 'company': 0}
            
            stats = {
                'worker': self.broadcast_to_user(chat.worker_id, data),
                'company': self.broadcast_to_user(chat.company_representative_id, data),
            }
            
            logger.info(
                f"Broadcast to all participants of chat {chat_id} completed",
                extra={"stats": stats}
            )
            return stats
            
        except Exception as e:
            logger.exception(f"Error broadcasting to all participants of chat {chat_id}", extra={"error": str(e)})
            return {'worker': 0, 'company': 0}

    def broadcast_personalized_chat_update(self, chat_id: str, extra_fields: Optional[Dict[str, Any]] = None) -> None:
        """
        Invia 'chat_updated' personalizzato a ciascun partecipante con TUTTI i campi
        che GET /chats restituisce: date dal Booking live, nome interlocutore da Cognito,
        info azienda da Companies, ecc.

        Questo sostituisce il semplice broadcast_to_all_chat_participants per 'chat_updated'
        in modo da non sovrascrivere dati corretti con dati parziali/sbagliati.

        Args:
            chat_id: ID della chat
            extra_fields: campi aggiuntivi da includere nel payload (es. bookingStatus aggiornato)
        """
        from db_manager import ChatDBManager
        try:
            db = ChatDBManager()
            chat = db.get_chat(chat_id)
            if not chat:
                logger.error(f"Chat {chat_id} not found for personalized broadcast")
                return

            # Dati freschi da tabelle esterne
            booking   = self._fetch_booking_details(chat.booking_id)
            company   = self._fetch_company_info(chat.company_representative_id)
            job_name  = chat.job_name or self._fetch_job_name(chat.listing_id)
            worker_name  = self._fetch_user_name(chat.worker_id)
            company_rep_name = self._fetch_user_name(chat.company_representative_id)

            last_state = chat.last_message_state.value if chat.last_message_state else None
            chat_status = chat.status.value if hasattr(chat.status, 'value') else str(chat.status) if chat.status else None

            # Flag di lettura dell'ultimo messaggio (stessa logica di GET /chats):
            # - mittente != beezey_system → entrambi True (campo non applicabile)
            # - mittente == beezey_system → usa i flag ridondati nella Chat
            if chat.last_message_sender_id != 'beezey_system':
                last_msg_read_worker  = True
                last_msg_read_company = True
            else:
                last_msg_read_worker  = bool(chat.last_message_read_worker)
                last_msg_read_company = bool(chat.last_message_read_company)

            # Campi comuni a ChatListItem per entrambi i ruoli.
            # DEVE essere 1:1 con la risposta REST GET /chats
            common_fields = {
                'action': 'chat_updated',
                'chatId': chat_id,
                'bookingId': chat.booking_id,
                'workerId': chat.worker_id,
                'companyRepresentativeId': chat.company_representative_id,
                'listingId': chat.listing_id,
                'status': chat_status,
                'jobName': job_name,
                'startDate': booking.get('startDate'),
                'endDate': booking.get('endDate'),
                'bookingStatus': booking.get('status'),
                'createdAt': chat.created_at,
                'lastMessageAt': chat.last_message_at,
                'lastMessagePreview': chat.last_message_preview,
                'lastMessageState': last_state,
                'lastMessageSenderId': chat.last_message_sender_id,
                'lastMessageReadWorker': last_msg_read_worker,
                'lastMessageReadCompany': last_msg_read_company,
                **(extra_fields or {}),
            }

            # Payload per il WORKER:
            #   - include companyId/companyName/companyLogo (solo per la vista worker)
            #   - interlocutore = company representative
            #   - recipientUserId: il frontend lo usa per scartare eventi non destinati
            #     all'utente corrente (protezione contro connessioni WebSocket stale)
            self.broadcast_to_user(chat.worker_id, {
                **common_fields,
                'recipientUserId': chat.worker_id,
                'companyId': company.get('companyId'),
                'companyName': company.get('companyName'),
                'companyLogo': company.get('companyLogo'),
                'interlocutorId': chat.company_representative_id,
                'interlocutorName': company_rep_name,
                'interlocutorPhoto': None,  # presigned URL — non inviabile in broadcast
            })

            # Payload per il COMPANY REPRESENTATIVE:
            #   - NO companyId/companyName/companyLogo
            #   - interlocutore = worker
            #   - recipientUserId: il frontend lo usa per scartare eventi non destinati
            #     all'utente corrente (protezione contro connessioni WebSocket stale)
            self.broadcast_to_user(chat.company_representative_id, {
                **common_fields,
                'recipientUserId': chat.company_representative_id,
                'interlocutorId': chat.worker_id,
                'interlocutorName': worker_name,
                'interlocutorPhoto': None,
            })

            logger.info(f"Personalized chat_updated sent for chat {chat_id}")

        except Exception as e:
            logger.exception(
                f"Error in broadcast_personalized_chat_update for chat {chat_id}",
                extra={"error": str(e)}
            )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _normalize_ws_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalizza il payload WS prima dell'invio.

        Regola attuale:
        - Per action='new_message' aggiunge sempre 'sender_id' top-level
          se ricavabile da message.senderId / message.sender_id.
        """
        if not isinstance(data, dict):
            return data

        action = data.get('action')
        if action != 'new_message':
            return data

        if data.get('sender_id'):
            return data

        message = data.get('message') if isinstance(data.get('message'), dict) else {}
        sender_id = message.get('senderId') or message.get('sender_id')
        if not sender_id:
            return data

        normalized = dict(data)
        normalized['sender_id'] = sender_id
        return normalized

    def _fetch_booking_details(self, booking_id: Optional[str]) -> Dict[str, Any]:
        """Legge startDate, endDate, status dalla tabella Bookings."""
        table_name = os.environ.get('BOOKINGS_TABLE_NAME')
        if not booking_id or not table_name:
            return {}
        try:
            table = dynamodb.Table(table_name)
            item = table.get_item(Key={'bookingId': booking_id}).get('Item', {})
            return {
                'startDate': item.get('startDate'),
                'endDate': item.get('endDate'),
                'status': item.get('status'),
            }
        except Exception as e:
            logger.warning(f"Could not fetch booking {booking_id}: {e}")
            return {}

    def _fetch_company_info(self, company_rep_id: Optional[str]) -> Dict[str, Any]:
        """Legge companyId, companyName, companyLogo dalla tabella Companies."""
        table_name = os.environ.get('COMPANIES_TABLE_NAME')
        if not company_rep_id or not table_name:
            return {}
        try:
            table = dynamodb.Table(table_name)
            item = table.get_item(Key={'userId': company_rep_id}).get('Item', {})
            return {
                'companyId': item.get('companyId'),
                'companyName': item.get('businessName', 'Azienda'),
                'companyLogo': item.get('logoUrl'),
            }
        except Exception as e:
            logger.warning(f"Could not fetch company for rep {company_rep_id}: {e}")
            return {}

    def _fetch_user_name(self, user_id: Optional[str]) -> Optional[str]:
        """Legge given_name + family_name da Cognito."""
        pool_id = os.environ.get('USER_POOL_ID')
        if not user_id or not pool_id:
            return None
        try:
            cog = boto3.client('cognito-idp')
            resp = cog.admin_get_user(UserPoolId=pool_id, Username=user_id)
            attrs = {a['Name']: a['Value'] for a in resp.get('UserAttributes', [])}
            given  = attrs.get('given_name', '').strip()
            family = attrs.get('family_name', '').strip()
            if given or family:
                return f"{given} {family}".strip()
            return attrs.get('name') or attrs.get('email') or None
        except Exception as e:
            logger.warning(f"Could not fetch user name for {user_id}: {e}")
            return None

    def _fetch_job_name(self, listing_id: Optional[str]) -> Optional[str]:
        """Legge title dalla tabella JobListings."""
        table_name = os.environ.get('JOB_LISTINGS_TABLE_NAME')
        if not listing_id or not table_name:
            return None
        try:
            table = dynamodb.Table(table_name)
            return table.get_item(Key={'listingId': listing_id}).get('Item', {}).get('title')
        except Exception as e:
            logger.warning(f"Could not fetch job name for listing {listing_id}: {e}")
            return None

    def _remove_stale_connection(self, connection_id: str) -> None:
        """Rimuovi connessione stale dal DB."""
        try:
            self.connection_table.delete_item(
                Key={'connectionId': connection_id}
            )
            logger.info(f"Removed stale connection {connection_id}")
        except ClientError as e:
            logger.exception(f"Error removing stale connection {connection_id}", extra={"error": str(e)})
