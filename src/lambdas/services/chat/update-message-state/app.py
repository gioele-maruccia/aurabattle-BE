import json
import sys
import os

# Add shared layer to path
sys.path.append('/opt/python')

# Architecture Note:
# Chat lambdas use ChatDBManager (shared layer) instead of direct boto3.
# This provides consistent data access patterns across all chat operations.
from models import MessageState
from db_manager import ChatDBManager
from ws_manager import WebSocketManager


def lambda_handler(event, context):
    """
    Update message state (sent -> delivered -> read)
    
    Path parameters:
    - chat_id: The chat ID
    - message_id: The message ID
    
    Expected input:
    {
        "state": "read"
        "timestamp": "2024-01-15T10:30:00Z"  # Optional - auto-generated if omitted
    }
    
    Authorization header contains JWT with user info
    """
    try:
        # Get path parameters
        chat_id = event['pathParameters']['chat_id']
        message_id = event['pathParameters']['message_id']
        
        # Get user info from authorizer context
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Parse request body
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', {})
        
        # Validate required fields
        if 'state' not in body:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'state is required', 'code': 4182})
            }
        
        # Use provided timestamp or current time
        from datetime import datetime
        timestamp = body.get('timestamp', datetime.utcnow().isoformat() + 'Z')
        
        # Validate state value
        try:
            new_state = MessageState(body['state'])
        except ValueError:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Invalid state. Must be one of: {[s.value for s in MessageState]}',
                    'code': 4296
                })
            }
        
        db_manager = ChatDBManager()
        
        # Verify chat exists and user has access
        chat = db_manager.get_chat(chat_id)
        if not chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Chat not found', 'code': 4297})
            }
        
        # Verify user is participant in this chat
        if user_id not in [chat.worker_id, chat.company_representative_id]:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Forbidden', 'message': 'You are not authorized to update messages in this chat', 'code': 4183})
            }
        
        # Get the message to verify it exists and user is not the sender
        # Non passiamo il timestamp - usa il nuovo GSI messageId-index
        message = db_manager.get_message(chat_id, message_id)
        if not message:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Message not found', 'code': 4184})
            }
        
        # Users can only update state of messages they didn't send
        if message.sender_id == user_id:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Forbidden', 'message': 'Cannot update state of your own messages', 'code': 4298})
            }
        
        # Update message state depending on sender type
        # ─────────────────────────────────────────────────────────────────────
        # Messaggi inviati da beezey_system vengono letti in modo indipendente
        # da worker e company: ogni partecipante imposta il proprio flag di
        # lettura (read_worker / read_company).  Solo quando ENTRAMBI i flag
        # sono True il campo «state» standard viene portato a «read».
        # Per tutti gli altri messaggi si usa il comportamento classico.
        # ─────────────────────────────────────────────────────────────────────

        if message.sender_id == 'beezey_system':
            # Determina il ruolo dell'utente corrente in questa chat
            is_worker  = (user_id == chat.worker_id)
            is_company = (user_id == chat.company_representative_id)

            # Aggiorna il flag corrispondente (non sovrascrivere un True già presente)
            new_read_worker  = message.read_worker  or is_worker
            new_read_company = message.read_company or is_company

            effective_state = db_manager.update_beezey_message_read_flags(
                chat_id=chat_id,
                message_id=message_id,
                timestamp=message.timestamp,
                new_read_worker=new_read_worker,
                new_read_company=new_read_company,
            )

            # ── WebSocket broadcast (best effort) ──────────────────────────
            try:
                ws_manager = WebSocketManager()

                ws_payload = {
                    'action': 'message_state_updated',
                    'chatId': chat_id,
                    'messageId': message_id,
                    'readWorker': new_read_worker,
                    'readCompany': new_read_company,
                }
                if effective_state:
                    ws_payload['newState'] = effective_state.value

                ws_manager.broadcast_to_all_chat_participants(
                    chat_id=chat_id,
                    data=ws_payload,
                )
                ws_manager.broadcast_personalized_chat_update(chat_id=chat_id)
            except Exception as ws_error:
                print(f"WebSocket broadcast error (non-critical): {str(ws_error)}")
            # ───────────────────────────────────────────────────────────────

            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'message': 'Message read flags updated successfully',
                    'message_id': message_id,
                    'read_worker': new_read_worker,
                    'read_company': new_read_company,
                    'new_state': effective_state.value if effective_state else message.state.value,
                    'code': 3083
                })
            }

        # Comportamento classico per messaggi normali (non beezey_system)
        db_manager.update_message_state(
            chat_id=chat_id,
            message_id=message_id,
            timestamp=message.timestamp,
            new_state=new_state
        )

        # ── WebSocket broadcast (best effort) ────────────────────────────────
        # 1) Notifica a tutti i partecipanti che lo stato del messaggio è cambiato
        #    (il mittente vede la spunta "read", il ricevente conferma la lettura)
        # 2) Aggiorna la lista chat (lastMessageState) su tutti i device
        try:
            ws_manager = WebSocketManager()

            # Invia a TUTTI i partecipanti (incluso chi ha appena letto)
            ws_manager.broadcast_to_all_chat_participants(
                chat_id=chat_id,
                data={
                    'action': 'message_state_updated',
                    'chatId': chat_id,
                    'messageId': message_id,
                    'newState': new_state.value,
                }
            )

            # Invia chat_updated PERSONALIZZATO a ciascun partecipante con tutti i campi
            # di GET /chats (date dal Booking live, interlocutorName da Cognito, ecc.)
            # → rimuove il pallino notifica e aggiorna la lista chat correttamente
            ws_manager.broadcast_personalized_chat_update(chat_id=chat_id)
        except Exception as ws_error:
            print(f"WebSocket broadcast error (non-critical): {str(ws_error)}")
        # ─────────────────────────────────────────────────────────────────────

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'message': 'Message state updated successfully',
                'message_id': message_id,
                'new_state': new_state.value,
                'code': 3055
            })
        }
        
    except KeyError as e:
        print(f"Missing required parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': f'Missing required parameter: {str(e)}', 'code': 4299})
        }
    
    except ValueError as e:
        print(f"Validation error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': str(e), 'code': 4300})
        }
    
    except Exception as e:
        print(f"Error updating message state: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5052})
        }