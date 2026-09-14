"""
Chat System Models

Questo modulo contiene tutti i modelli di dati per il sistema di chat.
Include Chat, Message, Attachment e tutti gli Enum necessari.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid


# ============================================
# ENUMS
# ============================================

class SenderType(Enum):
    """Tipo di mittente del messaggio"""
    WORKER = "worker"
    COMPANY = "company"
    BEEZEY = "beezey"


class MessageState(Enum):
    """Stato di lettura del messaggio"""
    SENT = "sent"           # Inviato ma non ancora consegnato
    DELIVERED = "delivered" # Consegnato al destinatario
    READ = "read"          # Letto dal destinatario


class StickerTag(Enum):
    """Sticker/reazioni disponibili sui messaggi"""
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    HEART = "heart"
    SMILE = "smile"
    FIRE = "fire"
    CHECK = "check"
    QUESTION = "question"


class MessageType(Enum):
    """Tipo di messaggio per gestire il rendering nel frontend"""
    TEXT = "text"                                  # Messaggio testuale normale (con o senza allegati)
    COMPANY_ACCEPT_DATES = "company_accept_dates"  # Messaggio che richiede all'azienda di accettare nuove date proposte
    ASK_REVIEW = "ask_review"                      # Richiesta di recensione (sia worker che company vedono lo stesso messaggio)


# Mappa di retrocompatibilità per vecchi valori enum MessageType
MESSAGE_TYPE_LEGACY_MAP = {
    "company_action": "company_accept_dates",
    "worker_review": "ask_worker_review",
    "company_review": "ask_company_review"
}


class ChatStatus(Enum):
    """Stato della chat"""
    ACTIVE = "active"       # Chat attiva
    ARCHIVED = "archived"   # Chat archiviata (booking completato)
    CLOSED = "closed"       # Chat chiusa (booking cancellato/rifiutato)
    DELETED = "deleted"     # Chat cancellata (soft delete)


class SupportChatType(Enum):
    """Tipo di supporto richiedente"""
    WORKER = "worker"       # Supporto da worker
    COMPANY = "company"     # Supporto da company representative


class SupportChatStatus(Enum):
    """Stato della chat di supporto"""
    OPEN = "open"           # Chat aperta e attiva
    IN_PROGRESS = "in_progress"  # Presa in carico
    RESOLVED = "resolved"   # Risolta
    CLOSED = "closed"       # Chiusa
    ARCHIVED = "archived"   # Archiviata


# ============================================
# DATA CLASSES
# ============================================

@dataclass
class Attachment:
    """Allegato di un messaggio"""
    file_name: str
    file_size: int
    file_type: str  # MIME type
    s3_url: str     # URL completo S3
    uploaded_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte in dizionario per DynamoDB"""
        return {
            'fileName': self.file_name,
            'fileSize': self.file_size,
            'fileType': self.file_type,
            's3Url': self.s3_url,
            'uploadedAt': self.uploaded_at
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Attachment':
        """Crea Attachment da dizionario DynamoDB"""
        return Attachment(
            file_name=data['fileName'],
            file_size=int(data['fileSize']),
            file_type=data['fileType'],
            s3_url=data['s3Url'],
            uploaded_at=data['uploadedAt']
        )


@dataclass
class Message:
    """Messaggio in una chat"""
    chat_id: str
    message_id: str
    sender_id: str
    sender_type: SenderType
    message_text: str
    timestamp: str
    state: MessageState
    message_type: MessageType = MessageType.TEXT  # Tipo di messaggio (default: text)
    payload: Optional[Dict[str, Any]] = None  # Payload opzionale per dati aggiuntivi (es. date proposte)
    attachments: List[Attachment] = field(default_factory=list)
    sticker: Optional[StickerTag] = None
    # Campi di lettura per messaggi beezey_system (entrambi True → state = 'read')
    read_worker: bool = False
    read_company: bool = False
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Converte in item DynamoDB"""
        item = {
            'chatId': self.chat_id,
            'messageId': self.message_id,
            'senderId': self.sender_id,
            'senderType': self.sender_type.value,
            'messageText': self.message_text,
            'timestamp': self.timestamp,
            'state': self.state.value,
            'messageType': self.message_type.value,  # Aggiungi message_type
            'attachments': [att.to_dict() for att in self.attachments]  # Sempre presente, anche se vuoto
        }
        
        # Aggiungi payload se presente
        if self.payload:
            item['payload'] = self.payload
        
        # Aggiungi sticker se presente
        if self.sticker:
            item['sticker'] = self.sticker.value

        # Campi di lettura per messaggi beezey_system
        item['readWorker'] = self.read_worker
        item['readCompany'] = self.read_company
            
        return item
    
    @staticmethod
    def from_dynamodb_item(item: Dict[str, Any]) -> 'Message':
        """Crea Message da item DynamoDB"""
        # Parse attachments
        attachments = []
        if 'attachments' in item and item['attachments']:
            attachments = [Attachment.from_dict(att) for att in item['attachments']]
        
        # Parse sticker
        sticker = None
        if 'sticker' in item:
            sticker = StickerTag(item['sticker'])
        
        # Parse message_type (default to TEXT for backward compatibility)
        message_type = MessageType.TEXT
        if 'messageType' in item and item['messageType']:  # Check if exists AND not None
            raw_type = item['messageType']
            # Mappa vecchi valori ai nuovi per retrocompatibilità
            if raw_type in MESSAGE_TYPE_LEGACY_MAP:
                raw_type = MESSAGE_TYPE_LEGACY_MAP[raw_type]
            message_type = MessageType(raw_type)
        
        # Parse payload (optional)
        payload = None
        if 'payload' in item and item['payload']:
            payload = item['payload']
        
        # Parse read flags for beezey_system messages (default False for backward compat)
        read_worker = bool(item.get('readWorker', False))
        read_company = bool(item.get('readCompany', False))

        return Message(
            chat_id=item['chatId'],
            message_id=item['messageId'],
            sender_id=item['senderId'],
            sender_type=SenderType(item['senderType']),
            message_text=item['messageText'],
            timestamp=item['timestamp'],
            state=MessageState(item['state']),
            message_type=message_type,
            payload=payload,
            attachments=attachments,
            sticker=sticker,
            read_worker=read_worker,
            read_company=read_company
        )
    
    def to_api_response(self) -> Dict[str, Any]:
        """Converte in formato per risposta API"""
        response = {
            'chatId': self.chat_id,
            'messageId': self.message_id,
            'senderId': self.sender_id,
            'senderType': self.sender_type.value,
            'messageText': self.message_text,
            'timestamp': self.timestamp,
            'state': self.state.value,
            'messageType': self.message_type.value,  # Aggiungi message_type
            'attachments': [att.to_dict() for att in self.attachments]  # Sempre presente, anche se vuoto
        }
        
        if self.payload:
            response['payload'] = self.payload
        
        if self.sticker:
            response['sticker'] = self.sticker.value

        # Campi di lettura per messaggi beezey_system
        response['readWorker'] = self.read_worker
        response['readCompany'] = self.read_company
            
        return response


@dataclass
class Chat:
    """Chat tra worker e rappresentante company"""
    chat_id: str
    booking_id: str
    worker_id: str
    company_representative_id: str  # User ID del rappresentante aziendale
    created_at: str
    status: ChatStatus
    last_message_at: Optional[str] = None
    last_message_preview: Optional[str] = None
    last_message_state: Optional[MessageState] = None  # Stato ultimo messaggio
    last_message_sender_id: Optional[str] = None  # ID mittente ultimo messaggio
    backoffice_operator_id: Optional[str] = None  # ID operatore backoffice assegnato (se presente)
    booking_state: Optional[str] = None  # Stato del booking ridondato per evitare join
    listing_id: Optional[str] = None  # ID del job listing
    # Nuovi campi per evitare chiamate API aggiuntive dal frontend
    job_name: Optional[str] = None  # Nome del job listing
    start_date: Optional[str] = None  # Data inizio booking
    end_date: Optional[str] = None  # Data fine booking
    # Flag di lettura dell'ultimo messaggio (ridondati dal messaggio per la chat list)
    # None = non applicabile (beezey_system non è il mittente → entrambi True)
    # False/True = flag effettivo dall'ultimo messaggio beezey_system
    last_message_read_worker: Optional[bool] = None
    last_message_read_company: Optional[bool] = None
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Converte in item DynamoDB"""
        item = {
            'chatId': self.chat_id,
            'bookingId': self.booking_id,
            'workerId': self.worker_id,
            'companyRepresentativeId': self.company_representative_id,
            'createdAt': self.created_at,
            'status': self.status.value,
        }
        
        if self.last_message_at:
            item['lastMessageAt'] = self.last_message_at
        
        if self.last_message_preview:
            item['lastMessagePreview'] = self.last_message_preview
        
        if self.last_message_state:
            item['lastMessageState'] = self.last_message_state.value
        
        if self.last_message_sender_id:
            item['lastMessageSenderId'] = self.last_message_sender_id
        
        if self.backoffice_operator_id:
            item['backofficeOperatorId'] = self.backoffice_operator_id
        
        # Stato booking ridondato
        if self.booking_state:
            item['bookingState'] = self.booking_state
        
        # Listing ID
        if self.listing_id:
            item['listingId'] = self.listing_id
        
        # Nuovi campi per job_name, start_date, end_date
        if self.job_name:
            item['jobName'] = self.job_name
        
        if self.start_date:
            item['startDate'] = self.start_date
        
        if self.end_date:
            item['endDate'] = self.end_date

        # Flag di lettura last message (ridondati per la chat list)
        # Salviamo sempre il valore (anche False), quindi usiamo "is not None"
        if self.last_message_read_worker is not None:
            item['lastMessageReadWorker'] = self.last_message_read_worker
        if self.last_message_read_company is not None:
            item['lastMessageReadCompany'] = self.last_message_read_company
            
        return item
    
    @staticmethod
    def from_dynamodb_item(item: Dict[str, Any]) -> 'Chat':
        """Crea Chat da item DynamoDB"""
        last_msg_state = None
        if 'lastMessageState' in item:
            last_msg_state = MessageState(item['lastMessageState'])
        
        return Chat(
            chat_id=item['chatId'],
            booking_id=item['bookingId'],
            worker_id=item['workerId'],
            company_representative_id=item['companyRepresentativeId'],
            created_at=item['createdAt'],
            status=ChatStatus(item['status']),
            last_message_at=item.get('lastMessageAt'),
            last_message_preview=item.get('lastMessagePreview'),
            last_message_state=last_msg_state,
            last_message_sender_id=item.get('lastMessageSenderId'),
            backoffice_operator_id=item.get('backofficeOperatorId'),
            booking_state=item.get('bookingState'),
            listing_id=item.get('listingId'),
            job_name=item.get('jobName'),
            start_date=item.get('startDate'),
            end_date=item.get('endDate'),
            last_message_read_worker=item.get('lastMessageReadWorker'),
            last_message_read_company=item.get('lastMessageReadCompany'),
        )
    
    def to_api_response(self) -> Dict[str, Any]:
        """Converte in formato per risposta API"""
        response = {
            'chatId': self.chat_id,
            'bookingId': self.booking_id,
            'workerId': self.worker_id,
            'companyRepresentativeId': self.company_representative_id,
            'createdAt': self.created_at,
            'status': self.status.value,
        }
        
        if self.last_message_at:
            response['lastMessageAt'] = self.last_message_at
        
        if self.last_message_preview:
            response['lastMessagePreview'] = self.last_message_preview
        
        if self.last_message_state:
            response['lastMessageState'] = self.last_message_state.value
        
        if self.last_message_sender_id:
            response['lastMessageSenderId'] = self.last_message_sender_id
        
        if self.backoffice_operator_id:
            response['backofficeOperatorId'] = self.backoffice_operator_id
        
        if self.booking_state:
            response['bookingState'] = self.booking_state
        
        if self.listing_id:
            response['listingId'] = self.listing_id
        
        # Nuovi campi per job_name, start_date, end_date
        if self.job_name:
            response['jobName'] = self.job_name
        
        if self.start_date:
            response['startDate'] = self.start_date
        
        if self.end_date:
            response['endDate'] = self.end_date
            
        return response


@dataclass
class SupportMessage:
    """Messaggio in una chat di supporto/assistenza"""
    support_chat_id: str
    message_id: str
    sender_id: str
    sender_type: SenderType  # worker, company, o beezey
    message_text: str
    timestamp: str
    state: MessageState
    message_type: MessageType = MessageType.TEXT  # Tipo di messaggio (default: text)
    attachments: List[Attachment] = field(default_factory=list)
    sticker: Optional[StickerTag] = None
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Converte in item DynamoDB"""
        item = {
            'supportChatId': self.support_chat_id,
            'messageId': self.message_id,
            'senderId': self.sender_id,
            'senderType': self.sender_type.value,
            'messageText': self.message_text,
            'timestamp': self.timestamp,
            'state': self.state.value,
            'messageType': self.message_type.value,  # Aggiungi message_type
            'attachments': [att.to_dict() for att in self.attachments]
        }
        
        if self.sticker:
            item['sticker'] = self.sticker.value
            
        return item
    
    @staticmethod
    def from_dynamodb_item(item: Dict[str, Any]) -> 'SupportMessage':
        """Crea SupportMessage da item DynamoDB"""
        attachments = []
        if 'attachments' in item and item['attachments']:
            attachments = [Attachment.from_dict(att) for att in item['attachments']]
        
        sticker = None
        if 'sticker' in item:
            sticker = StickerTag(item['sticker'])
        
        # Parse message_type (default to TEXT for backward compatibility)
        message_type = MessageType.TEXT
        if 'messageType' in item and item['messageType']:  # Check if exists AND not None
            message_type = MessageType(item['messageType'])
        
        return SupportMessage(
            support_chat_id=item['supportChatId'],
            message_id=item['messageId'],
            sender_id=item['senderId'],
            sender_type=SenderType(item['senderType']),
            message_text=item['messageText'],
            timestamp=item['timestamp'],
            state=MessageState(item['state']),
            message_type=message_type,
            attachments=attachments,
            sticker=sticker
        )
    
    def to_api_response(self) -> Dict[str, Any]:
        """Converte in formato per risposta API"""
        response = {
            'supportChatId': self.support_chat_id,
            'messageId': self.message_id,
            'senderId': self.sender_id,
            'senderType': self.sender_type.value,
            'messageText': self.message_text,
            'timestamp': self.timestamp,
            'state': self.state.value,
            'messageType': self.message_type.value,  # Aggiungi message_type
            'attachments': [att.to_dict() for att in self.attachments]
        }
        
        if self.sticker:
            response['sticker'] = self.sticker.value
            
        return response


@dataclass
class SupportChat:
    """Chat di supporto/assistenza tra worker/company e beebusy support team"""
    support_chat_id: str
    requester_id: str  # Chi ha aperto il supporto (worker o company rep)
    requester_type: SupportChatType  # WORKER o COMPANY
    created_at: str
    status: SupportChatStatus
    subject: Optional[str] = None  # Oggetto/argomento del supporto
    last_message_at: Optional[str] = None
    last_message_preview: Optional[str] = None
    last_message_state: Optional[MessageState] = None
    last_message_sender_id: Optional[str] = None  # ID mittente ultimo messaggio
    assigned_to: Optional[str] = None  # User ID di chi gestisce il supporto (beebusy staff)
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Converte in item DynamoDB"""
        item = {
            'supportChatId': self.support_chat_id,
            'requesterId': self.requester_id,
            'requesterType': self.requester_type.value,
            'createdAt': self.created_at,
            'status': self.status.value,
        }
        
        if self.subject:
            item['subject'] = self.subject
        
        if self.last_message_at:
            item['lastMessageAt'] = self.last_message_at
        
        if self.last_message_preview:
            item['lastMessagePreview'] = self.last_message_preview
        
        if self.last_message_state:
            item['lastMessageState'] = self.last_message_state.value
        
        if self.last_message_sender_id:
            item['lastMessageSenderId'] = self.last_message_sender_id
        
        if self.assigned_to:
            item['assignedTo'] = self.assigned_to
            
        return item
    
    @staticmethod
    def from_dynamodb_item(item: Dict[str, Any]) -> 'SupportChat':
        """Crea SupportChat da item DynamoDB"""
        last_msg_state = None
        if 'lastMessageState' in item:
            last_msg_state = MessageState(item['lastMessageState'])
        
        return SupportChat(
            support_chat_id=item['supportChatId'],
            requester_id=item['requesterId'],
            requester_type=SupportChatType(item['requesterType']),
            created_at=item['createdAt'],
            status=SupportChatStatus(item['status']),
            subject=item.get('subject'),
            last_message_at=item.get('lastMessageAt'),
            last_message_preview=item.get('lastMessagePreview'),
            last_message_state=last_msg_state,
            last_message_sender_id=item.get('lastMessageSenderId'),
            assigned_to=item.get('assignedTo')
        )
    
    def to_api_response(self) -> Dict[str, Any]:
        """Converte in formato per risposta API"""
        response = {
            'supportChatId': self.support_chat_id,
            'requesterId': self.requester_id,
            'requesterType': self.requester_type.value,
            'createdAt': self.created_at,
            'status': self.status.value,
        }
        
        if self.subject:
            response['subject'] = self.subject
        
        if self.last_message_at:
            response['lastMessageAt'] = self.last_message_at
        
        if self.last_message_preview:
            response['lastMessagePreview'] = self.last_message_preview
        
        if self.last_message_state:
            response['lastMessageState'] = self.last_message_state.value
        
        if self.last_message_sender_id:
            response['lastMessageSenderId'] = self.last_message_sender_id
        
        if self.assigned_to:
            response['assignedTo'] = self.assigned_to
            
        return response


# ============================================
# UTILITY FUNCTIONS
# ============================================

def format_date(date_str: str) -> str:
    """
    Converte una stringa data (ISO 8601 o YYYY-MM-DD) nel formato GG-MM-AAAA.
    Ritorna la stringa originale se il parsing fallisce.
    """
    if not date_str or date_str == 'N/A':
        return date_str
    try:
        # Tronca a 10 caratteri per gestire sia 'YYYY-MM-DD' che 'YYYY-MM-DDTHH:MM:SS...'
        date_part = str(date_str)[:10]
        parts = date_part.split('-')
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    except Exception:
        pass
    return date_str


def generate_chat_id() -> str:
    """Genera un UUID per una nuova chat"""
    return f"chat_{uuid.uuid4().hex[:16]}"


def generate_message_id() -> str:
    """Genera un UUID per un nuovo messaggio"""
    return f"msg_{uuid.uuid4().hex[:16]}"


def get_current_timestamp() -> str:
    """Restituisce timestamp ISO 8601 corrente in UTC"""
    return datetime.now(timezone.utc).isoformat()


def generate_beezey_welcome_message(chat: Chat, booking_details: Dict[str, Any]) -> Message:
    """
    Genera il messaggio di benvenuto automatico di BeeBusy.
    IMPORTANTE: Questo messaggio è di tipo COMPANY_ACCEPT_DATES perché permette all'azienda
    di accettare o rifiutare il booking direttamente dalla chat.
    
    Args:
        chat: La chat appena creata
        booking_details: Dettagli del booking (job_title, company_name, start_date, etc.)
    
    Returns:
        Message object con il messaggio di benvenuto (tipo COMPANY_ACCEPT_DATES)
    """
    
    # Calcola compenso in base alla durata del periodo
    compensation_raw = booking_details.get('compensation', 'N/A')
    start_date_raw = booking_details.get('start_date', 'N/A')
    end_date_raw = booking_details.get('end_date', 'N/A')
    comp_display = f"€{compensation_raw}/mese (reddito lordo)"
    try:
        monthly_comp = float(compensation_raw)
        start_dt = datetime.fromisoformat(str(start_date_raw)[:10])
        end_dt = datetime.fromisoformat(str(end_date_raw)[:10])
        num_days = (end_dt - start_dt).days + 1
        period_total = monthly_comp / 30 * num_days
        if num_days < 30:
            daily_gross = monthly_comp / 30
            comp_display = f"€{period_total:.2f} lordo sul periodo (€{daily_gross:.2f}/giorno lordo)"
        else:
            comp_display = f"€{period_total:.2f} lordo sul periodo (€{monthly_comp:.2f}/mese lordo)"
    except Exception:
        pass  # mantieni comp_display di fallback

    # Costruisci il messaggio di benvenuto
    welcome_text = f"""👋 Benvenuto nella chat!

📋 **Riepilogo della tua candidatura:**

👤 **Candidato:** {booking_details.get('worker_name', 'N/A')}
🏢 **Azienda:** {booking_details.get('company_name', 'N/A')}
💼 **Posizione:** {booking_details.get('job_title', 'N/A')}
📅 **Periodo:** {format_date(booking_details.get('start_date', 'N/A'))} - {format_date(booking_details.get('end_date', 'N/A'))}
💰 **Compenso:** {comp_display}

Questa è la tua chat dedicata con l'azienda.

Se hai bisogno di assistenza, contatta il team di beebusy direttamente su WhatsApp 🆘

Buona fortuna! 🍀"""
    
    return Message(
        chat_id=chat.chat_id,
        message_id=generate_message_id(),
        sender_id="beezey_system",
        sender_type=SenderType.BEEZEY,
        message_text=welcome_text,
        timestamp=get_current_timestamp(),
        state=MessageState.SENT,  # beebusy messages sono sempre "sent"
        message_type=MessageType.COMPANY_ACCEPT_DATES,  # Richiede azione dall'azienda (Accept/Reject)
        attachments=[]
    )


def generate_booking_status_message(
    chat: Chat, 
    booking_status: str, 
    rejection_reason: str = None,
    booking_details: Dict[str, Any] = None
) -> Message:
    """
    Genera un messaggio automatico di aggiornamento stato booking
    
    Args:
        chat: La chat in cui inviare il messaggio
        booking_status: Nuovo stato del booking ('confirmed', 'rejected', 'cancelled', 'completed', 'booking-update')
        rejection_reason: Motivo del rifiuto (se status è 'rejected')
        booking_details: Dettagli aggiuntivi del booking (opzionale)
    
    Returns:
        Message object con il messaggio di aggiornamento stato
    """
    
    booking_details = booking_details or {}
    
    # Determina il tipo di messaggio (default: TEXT)
    message_type = MessageType.TEXT
    
    # Genera il testo del messaggio in base allo stato
    if booking_status == 'confirmed':
        message_type = MessageType.TEXT
        message_text = f"""✅ **Candidatura Confermata!**

Congratulazioni! La tua candidatura è stata accettata dall'azienda.

🏢 **Azienda:** {booking_details.get('company_name', 'N/A')}
💼 **Posizione:** {booking_details.get('job_title', 'N/A')}
📅 **Inizio:** {format_date(booking_details.get('start_date', 'N/A'))}

In bocca al lupo! 🍀"""
    
    elif booking_status == 'rejected':
        message_type = MessageType.TEXT
        message_text = f"""❌ **Candidatura Non Accettata**

Purtroppo l'azienda ha scelto altri candidati per questa posizione.

"""
        if rejection_reason:
            message_text += f"""💬 **Motivo:** {rejection_reason}

"""
        
        message_text += """📋 **Non ti scoraggiare!**
• Continua a cercare altre opportunità nell'app

Troverai sicuramente l'opportunità giusta per te! 💪"""
    
    elif booking_status == 'cancelled':
        message_type = MessageType.TEXT
        message_text = f"""🚫 **Booking Annullato**

Il booking è stato annullato.

📋 **Cosa succede ora:**
• La posizione è di nuovo disponibile per altre candidature
• Puoi cercare altre opportunità nell'app

Per informazioni, contatta il supporto beebusy."""
    
    elif booking_status == 'completed':
        message_type = MessageType.ASK_REVIEW     #Mettere type review_request per mostrare il form recensione lato FE
        message_text = f"""🎉 **Booking Completato!**

Il lavoro è stato completato con successo!

📋 **Prossimi passi:**
• Ricordati di lasciare una recensione sull'azienda o sul worker per aiutare la community
• Controlla nuove opportunità nell'app

Grazie per aver usato beebusy!"""
    
    elif booking_status == 'booking-update':
        # Messaggio per notificare modifica date booking (richiede azione dall'azienda)
        message_type = MessageType.COMPANY_ACCEPT_DATES
        message_text = f"""📅 **Richiesta Modifica Date Booking**

Il worker ha richiesto una modifica delle date del booking.

📋 **Nuove date proposte:**
📅 **Inizio:** {format_date(booking_details.get('start_date', 'N/A'))}
📅 **Fine:** {format_date(booking_details.get('end_date', 'N/A'))}

🏢 **Azienda:** {booking_details.get('company_name', 'N/A')}
💼 **Posizione:** {booking_details.get('job_title', 'N/A')}

⚠️ **Prossimo Passo:** L'azienda potrà accettare o rifiutare la prenotazione sulla base delle nuove date proposte."""
    
    elif booking_status == 'auto_cancelled':
        message_type = MessageType.TEXT
        message_text = f"""⚠️ **Booking Annullato Automaticamente**

Il tuo booking in attesa è stato annullato automaticamente perché le date del lavoro sono state modificate dall'azienda e non includono più il periodo richiesto.

📋 **Cosa puoi fare:**
• Invia una nuova candidatura per il periodo aggiornato
• Contatta l'azienda tramite la chat per chiarimenti

🏢 **Azienda:** {booking_details.get('company_name', 'N/A')}
💼 **Posizione:** {booking_details.get('job_title', 'N/A')}

Siamo spiacenti per l'inconveniente. Continua a cercare nuove opportunità! 💪"""

    else:
        # Messaggio generico per stati non previsti
        message_type = MessageType.TEXT
        message_text = f"""📬 **Aggiornamento Booking**

Lo stato del tuo booking è cambiato a: **{booking_status}**

Per maggiori dettagli, controlla la sezione "Candidature" nell'app."""
    
    return Message(
        chat_id=chat.chat_id,
        message_id=generate_message_id(),
        sender_id="beezey_system",
        sender_type=SenderType.BEEZEY,
        message_text=message_text,
        timestamp=get_current_timestamp(),
        state=MessageState.SENT,
        message_type=message_type,  # Usa il tipo determinato
        attachments=[]
    )

def generate_review_reminder_message(
    chat: Chat,
    booking_details: Dict[str, Any] = None
) -> Message:
    """
    Genera un messaggio automatico UNICO per invitare a lasciare una recensione.
    Sia il worker che l'azienda vedono lo stesso messaggio nella chat condivisa.
    Sarà il frontend a mostrare il form corretto in base a chi è loggato.
    
    Args:
        chat: La chat in cui inviare il messaggio
        booking_details: Dettagli aggiuntivi del booking (company_name, job_title, ecc)
    
    Returns:
        Message object con il messaggio di richiesta recensione
    """
    
    booking_details = booking_details or {}
    company_name = booking_details.get('company_name', 'l\'azienda')
    job_title = booking_details.get('job_title', 'il lavoro')
    
    # Messaggio UNICO visibile a entrambe le parti
    message_text = f"""⭐ **Lascia una Recensione**

Il lavoro "{job_title}" presso {company_name} è stato completato!

Ci piacerebbe conoscere la tua esperienza:

👤 **Worker:** valuta l'azienda su flessibilità oraria e clima aziendale
🏢 **Azienda:** valuta il worker su affidabilità e capacità di lavorare in squadra

💬 Puoi anche aggiungere una descrizione per aiutare la community!

📊 Le recensioni sono importanti per migliorare la piattaforma e garantire una scelta equa e trasparente per tutti.
"""
    
    return Message(
        chat_id=chat.chat_id,
        message_id=generate_message_id(),
        sender_id="beezey_system",
        sender_type=SenderType.BEEZEY,
        message_text=message_text,
        timestamp=get_current_timestamp(),
        state=MessageState.SENT,
        message_type=MessageType.ASK_REVIEW,  # Tipo unico
        attachments=[]
    )