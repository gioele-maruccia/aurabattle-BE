import json
import sys

# Add shared layer to path
sys.path.append('/opt/python')

# Architecture Note:
# Chat system uses ChatDBManager for all database operations.
# This abstraction layer (in shared Lambda layer) ensures consistent data access
# and makes the codebase easier to maintain than direct boto3 usage.

from models import (
    Message, SenderType, MessageState,
    generate_message_id, get_current_timestamp
)
from db_manager import ChatDBManager


def generate_beezey_response(user_question: str, chat_context: dict) -> str:
    """
    Generate Beezey's response based on user question
    
    In a production environment, you could:
    1. Use AWS Bedrock to generate intelligent responses
    2. Use a custom trained model
    3. Use predefined templates based on question categories
    
    For now, we'll use simple templates
    """
    question_lower = user_question.lower()
    
    # FAQ responses
    if any(word in question_lower for word in ['orario', 'orari', 'quando']):
        return """📅 Per quanto riguarda gli orari di lavoro:

Gli orari sono stati concordati nella tua candidatura. Puoi sempre:
• Discuterli direttamente con l'azienda in questa chat
• Richiedere modifiche se necessario
• Verificare i dettagli nel tuo profilo booking

C'è altro in cui posso aiutarti?"""
    
    elif any(word in question_lower for word in ['pagamento', 'paga', 'compenso', 'stipendio']):
        return """💰 Informazioni sul pagamento:

Il compenso concordato è specificato nei dettagli della tua application. 
• I pagamenti vengono processati secondo i termini del contratto
• Per modifiche o chiarimenti, contatta direttamente l'azienda
• Per problemi di pagamento, contatta il supporto girolavoro

Posso aiutarti con altro?"""
    
    elif any(word in question_lower for word in ['contratto', 'documenti', 'documento']):
        return """📄 Documentazione e contratto:

• Il contratto sarà disponibile nella sezione "I miei booking"
• Assicurati di aver completato tutti i documenti richiesti
• Per documenti specifici, chiedi direttamente all'azienda

Serve altro?"""
    
    elif any(word in question_lower for word in ['problemi', 'problema', 'aiuto', 'help']):
        return """🆘 Supporto girolavoro:

Sono qui per aiutarti! Puoi:
• Fare domande specifiche qui in chat
• Contattare il supporto tramite l'app: Menu → Supporto
• Email: support@beezey.app
• Chat live disponibile dal lunedì al venerdì, 9-18

Come posso assisterti meglio?"""
    
    elif any(word in question_lower for word in ['modifica', 'cambiare', 'cambio']):
        return """✏️ Modifiche alla candidatura:

Per modificare i dettagli della tua application:
• Discutili con l'azienda in questa chat
• Se concordate modifiche, l'azienda può aggiornare il booking
• Per modifiche importanti, contatta il supporto girolavoro

Cosa vorresti modificare?"""
    
    elif any(word in question_lower for word in ['cancella', 'annulla', 'ritirar']):
        return """❌ Cancellazione application:

Se devi cancellare la tua candidatura:
• Informa subito l'azienda tramite questa chat
• Vai su "I miei booking" → Annulla booking
• Ricorda: cancellazioni frequenti possono influire sul tuo profilo

Sei sicuro di voler procedere?"""
    
    else:
        # Generic response
        return f"""👋 Ciao! Ho visto la tua domanda: "{user_question}"

Sono girolavoro e sono qui per assisterti. Per aiutarti meglio, posso:

📋 Fornirti informazioni su:
• Orari e condizioni di lavoro
• Pagamenti e compensi
• Documentazione e contratti
• Modifiche alla candidatura

💬 Suggerimenti:
• Puoi discutere i dettagli specifici con l'azienda in questa chat
• Per questioni urgenti, contatta il supporto girolavoro
• Controlla sempre la sezione "I miei booking" per aggiornamenti

Come posso aiutarti meglio? Fai una domanda più specifica!"""


def lambda_handler(event, context):
    """
    Handle request for Beezey assistance
    
    Path parameters:
    - chat_id: The chat ID
    
    Expected input:
    {
        "question": "User's question to Beezey"
    }
    
    Authorization header contains JWT with user info
    """
    try:
        # Get chat_id from path parameters
        chat_id = event['pathParameters']['chat_id']
        
        # Get user info from authorizer context
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Parse request body
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', {})
        
        # Validate required fields
        if 'question' not in body or not body['question'].strip():
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'question is required and cannot be empty', 'code': 4322})
            }
        
        db_manager = ChatDBManager()
        
        # Verify chat exists and user has access
        chat = db_manager.get_chat(chat_id)
        if not chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Chat not found', 'code': 4323})
            }
        
        # Verify user is participant in this chat
        if user_id not in [chat.worker_id, chat.company_representative_id]:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Forbidden', 'message': 'You are not authorized to request help in this chat', 'code': 4324})
            }
        
        # Create user's question message
        user_message = Message(
            chat_id=chat_id,
            message_id=generate_message_id(),
            sender_id=user_id,
            sender_type=SenderType.WORKER if user_id == chat.worker_id else SenderType.COMPANY,
            message_text=f"@girolavoro {body['question'].strip()}",
            timestamp=get_current_timestamp(),
            state=MessageState.SENT,
            attachments=[]
        )
        
        # Save user's question
        db_manager.create_message(user_message)
        
        # Generate Beezey's response
        chat_context = {
            'booking_id': chat.booking_id,
            'worker_id': chat.worker_id,
            'company_id': chat.company_representative_id
        }
        
        beezey_response_text = generate_beezey_response(
            user_question=body['question'].strip(),
            chat_context=chat_context
        )
        
        # Create Beezey's response message
        beezey_message = Message(
            chat_id=chat_id,
            message_id=generate_message_id(),
            sender_id="beezey_system",
            sender_type=SenderType.BEEZEY,
            message_text=beezey_response_text,
            timestamp=get_current_timestamp(),
            state=MessageState.SENT,
            attachments=[]
        )
        
        # Save Beezey's response
        db_manager.create_message(beezey_message)

        # WebSocket broadcast (best effort):
        # - user_message solo all'altro partecipante
        # - beezey_message a entrambi
        # - chat_updated personalizzato per entrambi
        try:
            from ws_manager import WebSocketManager
            ws_manager = WebSocketManager()
            ws_manager.broadcast_to_chat(
                chat_id=chat_id,
                sender_id=user_id,
                data={
                    'action': 'new_message',
                    'sender_id': user_message.sender_id,
                    'message': user_message.to_api_response()
                }
            )
            ws_manager.broadcast_to_all_chat_participants(
                chat_id=chat_id,
                data={
                    'action': 'new_message',
                    'sender_id': beezey_message.sender_id,
                    'message': beezey_message.to_api_response()
                }
            )
            ws_manager.broadcast_personalized_chat_update(chat_id=chat_id)
        except Exception as ws_error:
            print(f"WebSocket broadcast error (non-critical): {str(ws_error)}")
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'user_message': user_message.to_api_response(),
                'beezey_response': beezey_message.to_api_response(),
                'code': 3088
            })
        }
        
    except KeyError as e:
        print(f"Missing required parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': f'Missing required parameter: {str(e)}', 'code': 4325})
        }
    
    except ValueError as e:
        print(f"Validation error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': str(e), 'code': 4326})
        }
    
    except Exception as e:
        print(f"Error requesting girolavoro help: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5090})
        }