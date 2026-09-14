"""
Database Manager per il sistema di chat

Gestisce tutte le operazioni CRUD su DynamoDB per Chat e Messages.
"""

import os
from typing import List, Optional, Tuple, Dict, Any
import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from models import Chat, Message, MessageState, ChatStatus, SupportChat, SupportMessage, SupportChatStatus, SupportChatType


class ChatDBManager:
    """Manager per operazioni database su Chat e Messages"""
    
    def __init__(self):
        """Inizializza connessione a DynamoDB"""
        self.dynamodb = boto3.resource('dynamodb')
        
        # Ottieni nomi tabelle dalle variabili d'ambiente
        self.chats_table_name = os.environ.get('CHATS_TABLE_NAME', 'dev-Chats')
        self.messages_table_name = os.environ.get('MESSAGES_TABLE_NAME', 'dev-Messages')
        self.support_chats_table_name = os.environ.get('SUPPORT_CHATS_TABLE_NAME', 'dev-SupportChats')
        self.support_messages_table_name = os.environ.get('SUPPORT_MESSAGES_TABLE_NAME', 'dev-SupportMessages')
        
        # Riferimenti alle tabelle
        self.chats_table = self.dynamodb.Table(self.chats_table_name)
        self.messages_table = self.dynamodb.Table(self.messages_table_name)
        self.support_chats_table = self.dynamodb.Table(self.support_chats_table_name)
        self.support_messages_table = self.dynamodb.Table(self.support_messages_table_name)
    
    # ============================================
    # CHAT OPERATIONS
    # ============================================
    
    def create_chat(self, chat: Chat) -> None:
        """
        Crea una nuova chat
        
        Args:
            chat: Oggetto Chat da creare
            
        Raises:
            ClientError: Se c'è un errore DynamoDB
        """
        try:
            self.chats_table.put_item(
                Item=chat.to_dynamodb_item(),
                ConditionExpression='attribute_not_exists(chatId)'  # Previene duplicati
            )
            print(f"Chat created successfully: {chat.chat_id}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise ValueError(f"Chat {chat.chat_id} already exists")
            raise
    
    def get_chat(self, chat_id: str) -> Optional[Chat]:
        """
        Recupera una chat per ID
        
        Args:
            chat_id: ID della chat
            
        Returns:
            Chat object o None se non trovata
        """
        try:
            response = self.chats_table.get_item(Key={'chatId': chat_id})
            
            if 'Item' in response:
                return Chat.from_dynamodb_item(response['Item'])
            return None
        except ClientError as e:
            print(f"Error getting chat {chat_id}: {e}")
            raise
    
    def get_chat_by_booking(self, booking_id: str) -> Optional[Chat]:
        """
        Recupera una chat associata a un booking
        
        Args:
            booking_id: ID del booking
            
        Returns:
            Chat object o None se non trovata
        """
        try:
            response = self.chats_table.query(
                IndexName='bookingId-index',
                KeyConditionExpression=Key('bookingId').eq(booking_id)
            )
            
            if response['Items']:
                return Chat.from_dynamodb_item(response['Items'][0])
            return None
        except ClientError as e:
            print(f"Error getting chat by booking {booking_id}: {e}")
            raise
    
    def get_chats_by_worker(self, worker_id: str) -> List[Chat]:
        """
        Recupera tutte le chat di un worker
        
        Args:
            worker_id: ID del worker
            
        Returns:
            Lista di Chat
        """
        try:
            response = self.chats_table.query(
                IndexName='workerId-lastMessageAt-index',
                KeyConditionExpression=Key('workerId').eq(worker_id),
                ScanIndexForward=False  # Ordine decrescente (più recenti primi)
            )
            
            return [Chat.from_dynamodb_item(item) for item in response['Items']]
        except ClientError as e:
            print(f"Error getting worker chats: {e}")
            raise
    
    def get_chats_by_company_representative(self, company_rep_id: str) -> List[Chat]:
        """
        Recupera tutte le chat di un rappresentante aziendale
        
        Args:
            company_rep_id: ID del rappresentante aziendale
            
        Returns:
            Lista di Chat
        """
        try:
            response = self.chats_table.query(
                IndexName='companyRepresentativeId-lastMessageAt-index',
                KeyConditionExpression=Key('companyRepresentativeId').eq(company_rep_id),
                ScanIndexForward=False  # Ordine decrescente (più recenti primi)
            )
            
            return [Chat.from_dynamodb_item(item) for item in response['Items']]
        except ClientError as e:
            print(f"Error getting company representative chats: {e}")
            raise
    
    def get_chats_by_company_representative_scan(self, company_rep_id: str) -> List[Chat]:
        """
        Fallback: Recupera chat di un rappresentante usando Scan + FilterExpression
        Più lento di Query ma garantisce di trovare tutti i risultati anche con dati incompleti
        
        Args:
            company_rep_id: ID del rappresentante aziendale
            
        Returns:
            Lista di Chat ordinata per ultimo messaggio
        """
        try:
            response = self.chats_table.scan(
                FilterExpression=Attr('companyRepresentativeId').eq(company_rep_id)
            )
            
            chats = [Chat.from_dynamodb_item(item) for item in response['Items']]
            
            # Ordina manualmente per ultimo messaggio (decrescente)
            chats.sort(
                key=lambda c: c.last_message_at or c.created_at,
                reverse=True
            )
            
            return chats
        except ClientError as e:
            print(f"Error scanning company representative chats: {e}")
            raise
    
    def list_user_chats(
        self, 
        user_id: str, 
        user_type: str,
        limit: int = 20,
        last_evaluated_key: Optional[Dict] = None
    ) -> Tuple[List[Chat], Optional[Dict]]:
        """
        Lista tutte le chat di un utente (worker o company representative)
        
        Args:
            user_id: ID dell'utente
            user_type: "worker" o "company"
            limit: Numero massimo di risultati
            last_evaluated_key: Chiave per paginazione
            
        Returns:
            Tupla (lista di Chat, chiave per prossima pagina)
        """
        try:
            # Determina quale indice usare
            if user_type == 'worker':
                index_name = 'workerId-lastMessageAt-index'
                key_condition = Key('workerId').eq(user_id)
            else:  # company representative
                index_name = 'companyRepresentativeId-lastMessageAt-index'
                key_condition = Key('companyRepresentativeId').eq(user_id)
            
            # Query parameters
            query_params = {
                'IndexName': index_name,
                'KeyConditionExpression': key_condition,
                'Limit': limit,
                'ScanIndexForward': False  # Ordine decrescente (più recenti primi)
            }
            
            if last_evaluated_key:
                query_params['ExclusiveStartKey'] = last_evaluated_key
            
            response = self.chats_table.query(**query_params)
            
            # Converti items in Chat objects
            chats = [Chat.from_dynamodb_item(item) for item in response['Items']]
            
            # Gestisci paginazione
            next_key = response.get('LastEvaluatedKey')
            
            return chats, next_key
            
        except ClientError as e:
            print(f"Error listing chats for user {user_id}: {e}")
            raise
    
    def update_chat_last_message(
        self,
        chat_id: str,
        last_message_at: str,
        last_message_preview: str,
        last_message_state: MessageState = None,
        last_message_sender_id: str = None,
        last_message_read_worker: bool = None,
        last_message_read_company: bool = None,
    ) -> None:
        """
        Aggiorna timestamp, preview e (se disponibile) stato dell'ultimo messaggio.
        Aggiorna anche i flag di lettura ridondati (lastMessageReadWorker/Company),
        che vengono esposti nella chat list senza dover rileggere il messaggio.

        Regola:
        - mittente != beezey_system  →  entrambi i flag = True  (il mittente ha 
          già 'letto' il proprio messaggio; il destinatario è da notificare, ma
          il flag qui rappresenta se il beezey_system è stato letto da entrambi,
          non se il normale messaggio è stato letto.  Per i messaggi normali sia
          worker che company sono considerati True perché il campo non è applicabile.)
        - mittente == beezey_system  →  all'invio entrambi False; si aggiornano
          progressivamente con update_beezey_message_read_flags().

        Args:
            chat_id: ID della chat
            last_message_at: Timestamp ultimo messaggio
            last_message_preview: Anteprima testo (primi 100 caratteri)
            last_message_state: Stato ultimo messaggio (opzionale)
            last_message_sender_id: ID mittente ultimo messaggio (opzionale)
            last_message_read_worker: Flag lettura worker nell'ultimo messaggio (opzionale)
            last_message_read_company: Flag lettura company nell'ultimo messaggio (opzionale)
        """
        try:
            update_expr = 'SET lastMessageAt = :lma, lastMessagePreview = :lmp'
            expr_values = {
                ':lma': last_message_at,
                ':lmp': last_message_preview[:100]  # Limita a 100 caratteri
            }
            expr_names = {}

            if last_message_state:
                update_expr += ', lastMessageState = :lms'
                expr_values[':lms'] = last_message_state.value

            if last_message_sender_id:
                update_expr += ', lastMessageSenderId = :lmsi'
                expr_values[':lmsi'] = last_message_sender_id

            if last_message_read_worker is not None:
                update_expr += ', lastMessageReadWorker = :lmrw'
                expr_values[':lmrw'] = last_message_read_worker

            if last_message_read_company is not None:
                update_expr += ', lastMessageReadCompany = :lmrc'
                expr_values[':lmrc'] = last_message_read_company

            update_kwargs = {
                'Key': {'chatId': chat_id},
                'UpdateExpression': update_expr,
                'ExpressionAttributeValues': expr_values
            }

            if expr_names:
                update_kwargs['ExpressionAttributeNames'] = expr_names

            self.chats_table.update_item(**update_kwargs)
        except ClientError as e:
            print(f"Error updating chat last message: {e}")
            raise
    
    def update_chat_status(self, chat_id: str, new_status: ChatStatus) -> None:
        """
        Aggiorna lo stato di una chat
        
        Args:
            chat_id: ID della chat
            new_status: Nuovo stato
        """
        try:
            self.chats_table.update_item(
                Key={'chatId': chat_id},
                UpdateExpression='SET #status = :s',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':s': new_status.value}
            )
        except ClientError as e:
            print(f"Error updating chat status: {e}")
            raise
    
    def assign_backoffice_operator(self, chat_id: str, operator_id: str) -> None:
        """
        Assegna un operatore backoffice a una chat
        
        Args:
            chat_id: ID della chat
            operator_id: ID dell'operatore backoffice da assegnare
        """
        try:
            self.chats_table.update_item(
                Key={'chatId': chat_id},
                UpdateExpression='SET backofficeOperatorId = :oid',
                ExpressionAttributeValues={':oid': operator_id}
            )
            print(f"Backoffice operator {operator_id} assigned to chat {chat_id}")
        except ClientError as e:
            print(f"Error assigning backoffice operator: {e}")
            raise
    
    def remove_backoffice_operator(self, chat_id: str) -> None:
        """
        Rimuove l'operatore backoffice da una chat
        
        Args:
            chat_id: ID della chat
        """
        try:
            self.chats_table.update_item(
                Key={'chatId': chat_id},
                UpdateExpression='REMOVE backofficeOperatorId'
            )
            print(f"Backoffice operator removed from chat {chat_id}")
        except ClientError as e:
            print(f"Error removing backoffice operator: {e}")
            raise
    
    def update_chat_dates(self, chat_id: str, start_date: str, end_date: str, job_name: str = None) -> None:
        """
        Aggiorna le date del booking nella chat
        
        Args:
            chat_id: ID della chat
            start_date: Nuova data inizio (ISO string)
            end_date: Nuova data fine (ISO string)
            job_name: Nome del job (opzionale, se vogliamo aggiornare anche questo)
        """
        try:
            update_expression = 'SET startDate = :start, endDate = :end'
            expression_values = {
                ':start': start_date,
                ':end': end_date
            }
            
            if job_name:
                update_expression += ', jobName = :job'
                expression_values[':job'] = job_name
            
            self.chats_table.update_item(
                Key={'chatId': chat_id},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values
            )
            print(f"Chat {chat_id} dates updated: {start_date} to {end_date}")
        except ClientError as e:
            print(f"Error updating chat dates: {e}")
            raise
    
    def update_booking_state(self, chat_id: str, booking_state: str) -> None:
        """
        Aggiorna lo stato del booking nella chat (campo ridondato)
        
        Args:
            chat_id: ID della chat
            booking_state: Nuovo stato del booking (pending, confirmed, completed, cancelled, etc.)
        """
        try:
            self.chats_table.update_item(
                Key={'chatId': chat_id},
                UpdateExpression='SET bookingState = :state',
                ExpressionAttributeValues={
                    ':state': booking_state
                }
            )
            print(f"Chat {chat_id} booking_state updated to: {booking_state}")
        except ClientError as e:
            print(f"Error updating chat booking_state: {e}")
            raise
    
    # ============================================
    # MESSAGE OPERATIONS
    # ============================================
    
    def create_message(self, message: Message) -> None:
        """
        Crea un nuovo messaggio
        
        Args:
            message: Oggetto Message da creare
        """
        try:
            # Salva messaggio
            self.messages_table.put_item(Item=message.to_dynamodb_item())
            
            # Aggiorna chat con ultimo messaggio e stato
            preview = (message.message_text or '').strip()
            if not preview and message.attachments:
                preview = 'Allegato'

            # Flag di lettura: per messaggi normali entrambi True (campo non
            # applicabile); per beezey_system usa i flag già impostati sul
            # messaggio stesso, così il chiamante può pre-marcare come letto
            # il ruolo che ha generato l'evento (es. worker che crea la chat).
            is_beezey = (message.sender_id == 'beezey_system')
            read_worker  = message.read_worker  if is_beezey else True
            read_company = message.read_company if is_beezey else True

            self.update_chat_last_message(
                chat_id=message.chat_id,
                last_message_at=message.timestamp,
                last_message_preview=preview,
                last_message_state=message.state,
                last_message_sender_id=message.sender_id,
                last_message_read_worker=read_worker,
                last_message_read_company=read_company,
            )
            
            print(f"Message created successfully: {message.message_id}")
        except ClientError as e:
            print(f"Error creating message: {e}")
            raise
    
    def get_message(
        self, 
        chat_id: str, 
        message_id: str, 
        timestamp: str = None
    ) -> Optional[Message]:
        """
        Recupera un messaggio specifico
        
        Args:
            chat_id: ID della chat
            message_id: ID del messaggio
            timestamp: Timestamp del messaggio (opzionale - se omesso, usa GSI messageId-index)
            
        Returns:
            Message object o None se non trovato
        """
        try:
            # Se abbiamo il timestamp, usa il GSI messageId-timestamp-index (più efficiente)
            if timestamp:
                response = self.messages_table.query(
                    IndexName='messageId-timestamp-index',
                    KeyConditionExpression=Key('messageId').eq(message_id) & Key('timestamp').eq(timestamp)
                )
                
                if response['Items']:
                    # Verifica che appartenga alla chat corretta
                    item = response['Items'][0]
                    if item['chatId'] == chat_id:
                        return Message.from_dynamodb_item(item)
            else:
                # Usa il nuovo GSI messageId-index (solo messageId)
                response = self.messages_table.query(
                    IndexName='messageId-index',
                    KeyConditionExpression=Key('messageId').eq(message_id)
                )
                
                # Filtra per chat_id (potrebbero esserci messaggi con stesso ID in chat diverse)
                for item in response['Items']:
                    if item['chatId'] == chat_id:
                        return Message.from_dynamodb_item(item)
            
            return None
        except ClientError as e:
            print(f"Error getting message: {e}")
            raise
    
    def get_messages(
        self, 
        chat_id: str, 
        limit: int = 50,
        last_evaluated_key: Optional[Dict] = None
    ) -> Tuple[List[Message], Optional[Dict]]:
        """
        Recupera messaggi di una chat con paginazione
        
        Args:
            chat_id: ID della chat
            limit: Numero massimo di messaggi (max 100)
            last_evaluated_key: Chiave per paginazione
            
        Returns:
            Tupla (lista di Message, chiave per prossima pagina)
        """
        try:
            query_params = {
                'KeyConditionExpression': Key('chatId').eq(chat_id),
                'Limit': min(limit, 100),  # Max 100
                'ScanIndexForward': False  # Ordine decrescente (più recenti primi)
            }
            
            if last_evaluated_key:
                query_params['ExclusiveStartKey'] = last_evaluated_key
            
            response = self.messages_table.query(**query_params)
            
            # Converti items in Message objects
            messages = [Message.from_dynamodb_item(item) for item in response['Items']]
            
            # Gestisci paginazione
            next_key = response.get('LastEvaluatedKey')
            
            return messages, next_key
            
        except ClientError as e:
            print(f"Error getting messages for chat {chat_id}: {e}")
            raise
    
    def update_message_state(
        self, 
        chat_id: str, 
        message_id: str,
        timestamp: str,
        new_state: MessageState
    ) -> None:
        """
        Aggiorna lo stato di un messaggio (sent -> delivered -> read)
        
        Args:
            chat_id: ID della chat
            message_id: ID del messaggio
            timestamp: Timestamp del messaggio
            new_state: Nuovo stato
        """
        try:
            self.messages_table.update_item(
                Key={
                    'chatId': chat_id,
                    'timestamp': timestamp
                },
                UpdateExpression='SET #state = :s',
                ExpressionAttributeNames={'#state': 'state'},
                ConditionExpression='messageId = :mid',
                ExpressionAttributeValues={
                    ':s': new_state.value,
                    ':mid': message_id
                }
            )

            # Aggiorna lastMessageState nella Chat SOLO se questo messaggio è l'ultimo
            # (confrontiamo il timestamp del messaggio con lastMessageAt della chat)
            try:
                self.chats_table.update_item(
                    Key={'chatId': chat_id},
                    UpdateExpression='SET lastMessageState = :s',
                    ConditionExpression='lastMessageAt = :ts',
                    ExpressionAttributeValues={
                        ':s': new_state.value,
                        ':ts': timestamp
                    }
                )
                print(f"Chat {chat_id} lastMessageState updated to {new_state.value} (last message)")
            except ClientError as cond_error:
                if cond_error.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    # Questo messaggio non è l'ultimo, quindi non aggiorniamo lastMessageState
                    print(f"Message {message_id} is not the last message in chat {chat_id}, lastMessageState not updated")
                else:
                    raise
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise ValueError(f"Message {message_id} not found")
            print(f"Error updating message state: {e}")
            raise
    
    def update_beezey_message_read_flags(
        self,
        chat_id: str,
        message_id: str,
        timestamp: str,
        new_read_worker: bool,
        new_read_company: bool
    ):
        """
        Aggiorna i flag di lettura readWorker / readCompany per messaggi inviati
        da beezey_system.  Quando ENTRAMBI i flag diventano True aggiorna anche
        lo stato del messaggio a 'read' e, se si tratta dell'ultimo messaggio della
        chat, aggiorna lastMessageState.

        Args:
            chat_id: ID della chat
            message_id: ID del messaggio (usato come guard nella ConditionExpression)
            timestamp: Timestamp del messaggio (chiave di ordinamento in DynamoDB)
            new_read_worker: Nuovo valore per readWorker
            new_read_company: Nuovo valore per readCompany

        Returns:
            Il MessageState effettivamente impostato (MessageState.READ se entrambi
            True, altrimenti None).
        """
        try:
            effective_state = MessageState.READ if (new_read_worker and new_read_company) else None

            update_expr = 'SET readWorker = :rw, readCompany = :rc'
            expr_values: dict = {
                ':rw': new_read_worker,
                ':rc': new_read_company,
                ':mid': message_id,
            }
            expr_names: dict = {}

            if effective_state:
                update_expr += ', #state = :s'
                expr_values[':s'] = effective_state.value
                expr_names['#state'] = 'state'

            params: dict = {
                'Key': {'chatId': chat_id, 'timestamp': timestamp},
                'UpdateExpression': update_expr,
                'ConditionExpression': 'messageId = :mid',
                'ExpressionAttributeValues': expr_values,
            }
            if expr_names:
                params['ExpressionAttributeNames'] = expr_names

            self.messages_table.update_item(**params)
            print(f"Beezey message {message_id} read flags updated: worker={new_read_worker}, company={new_read_company}")

            # Aggiorna la Chat SOLO se questo è l'ultimo messaggio (conditional update
            # su lastMessageAt = timestamp).
            # Sincronizza sia lastMessageState (se cambiato) che i flag di lettura.
            try:
                chat_update_expr = 'SET lastMessageReadWorker = :rw, lastMessageReadCompany = :rc'
                chat_expr_values: dict = {
                    ':rw': new_read_worker,
                    ':rc': new_read_company,
                    ':ts': timestamp,
                }
                chat_expr_names: dict = {}

                if effective_state:
                    chat_update_expr += ', lastMessageState = :s'
                    chat_expr_values[':s'] = effective_state.value

                self.chats_table.update_item(
                    Key={'chatId': chat_id},
                    UpdateExpression=chat_update_expr,
                    ConditionExpression='lastMessageAt = :ts',
                    ExpressionAttributeValues=chat_expr_values,
                )
                print(f"Chat {chat_id} read flags updated: worker={new_read_worker}, company={new_read_company}")
                if effective_state:
                    print(f"Chat {chat_id} lastMessageState updated to {effective_state.value}")
            except ClientError as cond_err:
                if cond_err.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    print(f"Message {message_id} is not the last message, chat fields not updated")
                else:
                    raise

            return effective_state

        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise ValueError(f"Message {message_id} not found")
            print(f"Error updating beezey message read flags: {e}")
            raise

    def add_sticker_to_message(
        self, 
        chat_id: str,
        message_id: str,
        timestamp: str,
        sticker: str
    ) -> None:
        """
        Aggiunge uno sticker a un messaggio
        
        Args:
            chat_id: ID della chat
            message_id: ID del messaggio
            timestamp: Timestamp del messaggio
            sticker: Nome dello sticker
        """
        try:
            self.messages_table.update_item(
                Key={
                    'chatId': chat_id,
                    'timestamp': timestamp
                },
                UpdateExpression='SET sticker = :sticker',
                ConditionExpression='messageId = :mid',
                ExpressionAttributeValues={
                    ':sticker': sticker,
                    ':mid': message_id
                }
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise ValueError(f"Message {message_id} not found")
            print(f"Error adding sticker: {e}")
            raise
    
    def mark_all_beezey_messages_read_for_role(self, chat_id: str, is_company: bool) -> int:
        """
        Marca TUTTI i messaggi beezey_system di una chat come letti per un ruolo.
        Usato quando un utente compie un'azione (conferma/rifiuta/cancella) che
        implica che ha già "visto" tutti i messaggi automatici precedenti.

        Args:
            chat_id:    ID della chat
            is_company: True se l'attore è il company representative, False se è il worker

        Returns:
            Numero di messaggi aggiornati
        """
        flag_attr = 'readCompany' if is_company else 'readWorker'
        try:
            # Recupera tutti i messaggi beezey_system dove il flag del ruolo è False
            items = []
            resp = self.messages_table.query(
                KeyConditionExpression=Key('chatId').eq(chat_id),
                FilterExpression=(
                    Attr('senderId').eq('beezey_system') &
                    Attr(flag_attr).eq(False)
                )
            )
            items.extend(resp.get('Items', []))
            while 'LastEvaluatedKey' in resp:
                resp = self.messages_table.query(
                    KeyConditionExpression=Key('chatId').eq(chat_id),
                    FilterExpression=(
                        Attr('senderId').eq('beezey_system') &
                        Attr(flag_attr).eq(False)
                    ),
                    ExclusiveStartKey=resp['LastEvaluatedKey']
                )
                items.extend(resp.get('Items', []))

            updated = 0
            for item in items:
                try:
                    new_rw = bool(item.get('readWorker', False)) or (not is_company)
                    new_rc = bool(item.get('readCompany', False)) or is_company
                    self.update_beezey_message_read_flags(
                        chat_id=chat_id,
                        message_id=item['messageId'],
                        timestamp=item['timestamp'],
                        new_read_worker=new_rw,
                        new_read_company=new_rc,
                    )
                    updated += 1
                except Exception as e:
                    print(f"Could not update beezey message {item.get('messageId')}: {e}")

            print(f"mark_all_beezey_messages_read_for_role: {updated} messages updated in chat {chat_id} (is_company={is_company})")
            return updated
        except ClientError as e:
            print(f"Error marking all beezey messages read for role in chat {chat_id}: {e}")
            return 0

    def get_unread_count(self, chat_id: str, user_id: str, is_worker: Optional[bool] = None) -> int:
        """
        Conta i messaggi non letti RICEVUTI dall'utente in una chat.

        Vengono contati SOLO i messaggi il cui mittente (senderId) è diverso
        dall'utente corrente, ovvero messaggi ricevuti, non inviati.
        Per i messaggi normali usa il campo `state` (sent/delivered = unread).
        Per i messaggi di beezey_system usa i flag readWorker/readCompany basati
        sul ruolo dell'utente (is_worker=True → readWorker, False → readCompany).
        Se is_worker è None si ricade sul solo campo state (può sovrastimare).

        Args:
            chat_id:   ID della chat
            user_id:   ID dell'utente
            is_worker: True se l'utente è il worker nella chat, False se è
                       il company representative, None se non noto.

        Returns:
            Numero di messaggi non letti ricevuti dall'utente
        """
        try:
            # ── Messaggi normali (non beezey_system) ────────────────────────
            # IMPORTANTE: senderId != user_id garantisce che contiamo solo
            # messaggi RICEVUTI dall'utente, non quelli da lui inviati.
            count = 0
            regular_filter = (
                Attr('senderId').ne(user_id) &
                Attr('senderId').ne('beezey_system') &
                (Attr('state').eq('sent') | Attr('state').eq('delivered'))
            )
            regular_resp = self.messages_table.query(
                KeyConditionExpression=Key('chatId').eq(chat_id),
                FilterExpression=regular_filter
            )
            count += len(regular_resp['Items'])
            while 'LastEvaluatedKey' in regular_resp:
                regular_resp = self.messages_table.query(
                    KeyConditionExpression=Key('chatId').eq(chat_id),
                    FilterExpression=regular_filter,
                    ExclusiveStartKey=regular_resp['LastEvaluatedKey']
                )
                count += len(regular_resp['Items'])

            # ── Messaggi beezey_system ───────────────────────────────────────
            if is_worker is not None:
                # Controlla il flag specifico del ruolo dell'utente
                flag_attr = 'readWorker' if is_worker else 'readCompany'
                beezey_filter = (
                    Attr('senderId').eq('beezey_system') &
                    Attr(flag_attr).eq(False)
                )
            else:
                # Fallback senza ruolo: usa lo state (può sovrastimare)
                beezey_filter = (
                    Attr('senderId').eq('beezey_system') &
                    (Attr('state').eq('sent') | Attr('state').eq('delivered'))
                )
            beezey_resp = self.messages_table.query(
                KeyConditionExpression=Key('chatId').eq(chat_id),
                FilterExpression=beezey_filter
            )
            count += len(beezey_resp['Items'])
            while 'LastEvaluatedKey' in beezey_resp:
                beezey_resp = self.messages_table.query(
                    KeyConditionExpression=Key('chatId').eq(chat_id),
                    FilterExpression=beezey_filter,
                    ExclusiveStartKey=beezey_resp['LastEvaluatedKey']
                )
                count += len(beezey_resp['Items'])

            return count

        except ClientError as e:
            print(f"Error counting unread messages: {e}")
            return 0

    def heal_stale_unread_if_last_read(
        self, chat_id: str, user_id: str, is_worker: bool
    ) -> int:
        """
        Auto-corregge flag unread "bloccati" nella chat.

        Controlla l'ultimo messaggio RICEVUTO dall'utente (senderId != user_id).
        Se quell'ultimo messaggio risulta già letto (state='read' per i messaggi
        normali, o readWorker/readCompany=True per i messaggi beezey_system), allora
        tutti i messaggi ricevuti precedenti con flag non aggiornato vengono marcati
        come letti.

        Questo corregge il caso in cui il client ha mostrato i messaggi ma non ha
        chiamato l'endpoint di aggiornamento stato, lasciando flag 'sent'/'delivered'
        o readWorker/readCompany=False su messaggi già visti.

        Returns:
            Numero di messaggi risanati (0 se nessun intervento necessario).
        """
        flag_attr = 'readWorker' if is_worker else 'readCompany'

        # 1. Recupera tutti i messaggi della chat, dal più recente al meno recente
        all_messages: list = []
        try:
            resp = self.messages_table.query(
                KeyConditionExpression=Key('chatId').eq(chat_id),
                ScanIndexForward=False
            )
            all_messages.extend(resp.get('Items', []))
            while 'LastEvaluatedKey' in resp:
                resp = self.messages_table.query(
                    KeyConditionExpression=Key('chatId').eq(chat_id),
                    ScanIndexForward=False,
                    ExclusiveStartKey=resp['LastEvaluatedKey']
                )
                all_messages.extend(resp.get('Items', []))
        except ClientError as e:
            print(f"[HEAL] Error fetching messages for chat {chat_id}: {e}")
            return 0

        # 2. Trova l'ultimo messaggio RICEVUTO (senderId != user_id)
        last_received = None
        for msg in all_messages:  # ordinato DESC per timestamp
            if msg.get('senderId') != user_id:
                last_received = msg
                break

        if not last_received:
            return 0  # nessun messaggio ricevuto in questa chat

        # 3. Verifica se l'ultimo messaggio ricevuto è già 'read'
        if last_received.get('senderId') == 'beezey_system':
            last_is_read = bool(last_received.get(flag_attr, False))
        else:
            last_is_read = last_received.get('state') == 'read'

        if not last_is_read:
            # L'ultimo messaggio ricevuto non è ancora letto → niente da sanare
            return 0

        # 4. Sana tutti i messaggi ricevuti con flag/stato non aggiornato
        healed = 0
        for msg in all_messages:
            sender = msg.get('senderId')
            if sender == user_id:
                continue  # messaggi inviati dall'utente: skip

            if sender == 'beezey_system':
                if not bool(msg.get(flag_attr, True)):
                    # Preserva il flag dell'altro ruolo, aggiorna solo quello dell'utente
                    new_rw = True if is_worker else bool(msg.get('readWorker', False))
                    new_rc = True if not is_worker else bool(msg.get('readCompany', False))
                    try:
                        self.update_beezey_message_read_flags(
                            chat_id=chat_id,
                            message_id=msg['messageId'],
                            timestamp=msg['timestamp'],
                            new_read_worker=new_rw,
                            new_read_company=new_rc,
                        )
                        healed += 1
                    except Exception as e:
                        print(f"[HEAL] Cannot update beezey msg {msg.get('messageId')}: {e}")
            else:
                if msg.get('state') in ('sent', 'delivered'):
                    try:
                        self.update_message_state(
                            chat_id=chat_id,
                            message_id=msg['messageId'],
                            timestamp=msg['timestamp'],
                            new_state=MessageState.READ
                        )
                        healed += 1
                    except Exception as e:
                        print(f"[HEAL] Cannot update msg {msg.get('messageId')}: {e}")

        if healed > 0:
            print(f"[HEAL] Auto-healed {healed} stale unread msgs in chat {chat_id} for user {user_id}")
        return healed

    # ============================================
    # SUPPORT CHAT OPERATIONS
    # ============================================
    
    def create_support_chat(self, support_chat: SupportChat) -> None:
        """
        Crea una nuova chat di supporto
        
        Args:
            support_chat: Oggetto SupportChat da creare
            
        Raises:
            ClientError: Se c'è un errore DynamoDB
        """
        try:
            self.support_chats_table.put_item(
                Item=support_chat.to_dynamodb_item(),
                ConditionExpression='attribute_not_exists(supportChatId)'
            )
            print(f"Support chat created successfully: {support_chat.support_chat_id}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise ValueError(f"Support chat {support_chat.support_chat_id} already exists")
            raise
    
    def get_support_chat(self, support_chat_id: str) -> Optional[SupportChat]:
        """
        Recupera una chat di supporto per ID
        
        Args:
            support_chat_id: ID della chat di supporto
            
        Returns:
            SupportChat object o None se non trovata
        """
        try:
            response = self.support_chats_table.get_item(Key={'supportChatId': support_chat_id})
            
            if 'Item' in response:
                return SupportChat.from_dynamodb_item(response['Item'])
            return None
        except ClientError as e:
            print(f"Error getting support chat {support_chat_id}: {e}")
            raise
    
    def get_support_chats_by_requester(
        self, 
        requester_id: str,
        limit: int = 50,
        last_key: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[SupportChat], Optional[Dict[str, Any]]]:
        """
        Recupera chat di supporto di un richiedente (worker o company rep)
        Ordinate per ultimo messaggio (più recenti prima)
        
        Args:
            requester_id: ID del richiedente
            limit: Numero di chat da recuperare
            last_key: Per paginazione, chiave dell'ultimo elemento
            
        Returns:
            Tupla (lista di SupportChat, last_key per paginazione)
        """
        try:
            kwargs = {
                'IndexName': 'requesterId-lastMessageAt-index',
                'KeyConditionExpression': Key('requesterId').eq(requester_id),
                'ScanIndexForward': False,  # Ordine decrescente (più recenti prima)
                'Limit': limit
            }
            
            if last_key:
                kwargs['ExclusiveStartKey'] = last_key
            
            response = self.support_chats_table.query(**kwargs)
            
            chats = [SupportChat.from_dynamodb_item(item) for item in response['Items']]
            last_key = response.get('LastEvaluatedKey')
            
            return chats, last_key
        except ClientError as e:
            print(f"Error getting support chats by requester: {e}")
            raise
    
    def update_support_chat_status(
        self,
        support_chat_id: str,
        new_status: SupportChatStatus
    ) -> None:
        """
        Aggiorna lo stato di una chat di supporto
        
        Args:
            support_chat_id: ID della chat
            new_status: Nuovo stato
        """
        try:
            self.support_chats_table.update_item(
                Key={'supportChatId': support_chat_id},
                UpdateExpression='SET #status = :s',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':s': new_status.value}
            )
        except ClientError as e:
            print(f"Error updating support chat status: {e}")
            raise
    
    def assign_support_chat(
        self,
        support_chat_id: str,
        assigned_to_id: str
    ) -> None:
        """
        Assegna una chat di supporto a uno staff member
        
        Args:
            support_chat_id: ID della chat
            assigned_to_id: User ID del staff member
        """
        try:
            self.support_chats_table.update_item(
                Key={'supportChatId': support_chat_id},
                UpdateExpression='SET assignedTo = :staff, #status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':staff': assigned_to_id,
                    ':status': SupportChatStatus.IN_PROGRESS.value
                }
            )
        except ClientError as e:
            print(f"Error assigning support chat: {e}")
            raise
    
    # ============================================
    # SUPPORT MESSAGE OPERATIONS
    # ============================================
    
    def create_support_message(self, message: SupportMessage) -> None:
        """
        Crea un nuovo messaggio in una chat di supporto
        
        Args:
            message: Oggetto SupportMessage da creare
            
        Raises:
            ClientError: Se c'è un errore DynamoDB
        """
        try:
            self.support_messages_table.put_item(Item=message.to_dynamodb_item())
            
            # Aggiorna lastMessageAt, preview e stato nella chat di supporto
            preview = (message.message_text or '').strip()
            if not preview and message.attachments:
                preview = 'Allegato'

            self.support_chats_table.update_item(
                Key={'supportChatId': message.support_chat_id},
                UpdateExpression='SET lastMessageAt = :ts, lastMessagePreview = :preview, lastMessageState = :state, lastMessageSenderId = :sender',
                ExpressionAttributeValues={
                    ':ts': message.timestamp,
                    ':preview': preview[:100],  # Prime 100 caratteri
                    ':state': message.state.value,
                    ':sender': message.sender_id
                }
            )
            
            print(f"Support message created: {message.message_id}")
        except ClientError as e:
            print(f"Error creating support message: {e}")
            raise
    
    def get_support_message(
        self,
        support_chat_id: str,
        message_id: str,
        timestamp: str = None
    ) -> Optional[SupportMessage]:
        """
        Recupera un messaggio di supporto specifico
        
        Args:
            support_chat_id: ID della chat
            message_id: ID del messaggio
            timestamp: Timestamp del messaggio (opzionale - se omesso, usa GSI messageId-index)
            
        Returns:
            SupportMessage object o None se non trovato
        """
        try:
            # Se abbiamo il timestamp, usa il GSI messageId-timestamp-index (più efficiente)
            if timestamp:
                response = self.support_messages_table.query(
                    IndexName='messageId-timestamp-index',
                    KeyConditionExpression=Key('messageId').eq(message_id) & Key('timestamp').eq(timestamp)
                )
                
                if response['Items']:
                    # Verifica che appartenga alla chat corretta
                    item = response['Items'][0]
                    if item['supportChatId'] == support_chat_id:
                        return SupportMessage.from_dynamodb_item(item)
            else:
                # Usa il nuovo GSI messageId-index (solo messageId)
                response = self.support_messages_table.query(
                    IndexName='messageId-index',
                    KeyConditionExpression=Key('messageId').eq(message_id)
                )
                
                # Filtra per support_chat_id (potrebbero esserci messaggi con stesso ID in chat diverse)
                for item in response['Items']:
                    if item['supportChatId'] == support_chat_id:
                        return SupportMessage.from_dynamodb_item(item)
            
            return None
        except ClientError as e:
            print(f"Error getting support message: {e}")
            raise
    
    def get_support_messages(
        self,
        support_chat_id: str,
        limit: int = 50,
        last_key: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[SupportMessage], Optional[Dict[str, Any]]]:
        """
        Recupera messaggi di una chat di supporto con paginazione
        
        Args:
            support_chat_id: ID della chat
            limit: Numero di messaggi
            last_key: Per paginazione
            
        Returns:
            Tupla (lista di SupportMessage, last_key)
        """
        try:
            kwargs = {
                'KeyConditionExpression': Key('supportChatId').eq(support_chat_id),
                'ScanIndexForward': False,  # Ordine decrescente (più recenti prima)
                'Limit': limit
            }
            
            if last_key:
                kwargs['ExclusiveStartKey'] = last_key
            
            response = self.support_messages_table.query(**kwargs)
            
            messages = [SupportMessage.from_dynamodb_item(item) for item in response['Items']]
            messages.reverse()  # Inverti per avere ordine cronologico (meno recenti prima)
            
            last_key = response.get('LastEvaluatedKey')
            
            return messages, last_key
        except ClientError as e:
            print(f"Error getting support messages: {e}")
            raise
    
    def update_support_message_state(
        self,
        support_chat_id: str,
        message_id: str,
        new_state: MessageState,
        timestamp: str = None
    ) -> None:
        """
        Aggiorna lo stato di un messaggio di supporto
        
        Args:
            support_chat_id: ID della chat
            message_id: ID del messaggio
            new_state: Nuovo stato
            timestamp: Timestamp del messaggio (opzionale - se omesso, fa lookup via GSI)
        """
        try:
            # Se timestamp non è fornito, lo recuperiamo tramite get_support_message
            if not timestamp:
                message = self.get_support_message(support_chat_id, message_id)
                if not message:
                    raise ValueError(f"Message {message_id} not found")
                timestamp = message.timestamp
            
            self.support_messages_table.update_item(
                Key={
                    'supportChatId': support_chat_id,
                    'timestamp': timestamp
                },
                UpdateExpression='SET #state = :s',
                ConditionExpression='messageId = :mid',
                ExpressionAttributeNames={'#state': 'state'},
                ExpressionAttributeValues={
                    ':s': new_state.value,
                    ':mid': message_id
                }
            )

            # Aggiorna lo stato dell'ultimo messaggio nella chat di supporto (solo se è l'ultimo)
            try:
                self.support_chats_table.update_item(
                    Key={'supportChatId': support_chat_id},
                    UpdateExpression='SET lastMessageState = :s',
                    ConditionExpression='attribute_not_exists(lastMessageAt) OR lastMessageAt = :ts',
                    ExpressionAttributeValues={
                        ':s': new_state.value,
                        ':ts': timestamp
                    }
                )
            except ClientError as e:
                if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                    print(f"Error syncing support chat lastMessageState: {e}")
                    raise
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise ValueError(f"Message {message_id} not found")
            print(f"Error updating support message state: {e}")
            raise
    
    def add_sticker_to_support_message(
        self,
        support_chat_id: str,
        message_id: str,
        sticker: str,
        timestamp: str = None
    ) -> None:
        """
        Aggiunge uno sticker a un messaggio di supporto
        
        Args:
            support_chat_id: ID della chat
            message_id: ID del messaggio
            sticker: Nome dello sticker
            timestamp: Timestamp del messaggio (opzionale - se omesso, fa lookup via GSI)
        """
        try:
            # Se timestamp non è fornito, lo recuperiamo tramite get_support_message
            if not timestamp:
                message = self.get_support_message(support_chat_id, message_id)
                if not message:
                    raise ValueError(f"Message {message_id} not found")
                timestamp = message.timestamp
            
            self.support_messages_table.update_item(
                Key={
                    'supportChatId': support_chat_id,
                    'timestamp': timestamp
                },
                UpdateExpression='SET sticker = :sticker',
                ConditionExpression='messageId = :mid',
                ExpressionAttributeValues={
                    ':sticker': sticker,
                    ':mid': message_id
                }
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise ValueError(f"Message {message_id} not found")
            print(f"Error adding sticker to support message: {e}")
            raise
    
    def delete_support_chat(self, support_chat_id: str) -> None:
        """
        Soft delete di una chat di supporto (imposta status a 'CLOSED')
        
        Args:
            support_chat_id: ID della chat da eliminare
        """
        try:
            self.support_chats_table.update_item(
                Key={'supportChatId': support_chat_id},
                UpdateExpression='SET #status = :s',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':s': SupportChatStatus.CLOSED.value}
            )
        except ClientError as e:
            print(f"Error deleting support chat: {e}")
            raise