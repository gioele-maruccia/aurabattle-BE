import json
import sys
import os
import boto3

# Add shared layer to path
sys.path.append('/opt/python')

# Architecture Note:
# Chat service uses ChatDBManager (shared layer) for database operations.
# This pattern provides better abstraction than direct boto3 calls used in legacy services.

from models import (
    Message, SenderType, MessageState, Attachment,
    generate_message_id, get_current_timestamp
)
from db_manager import ChatDBManager
from ws_manager import WebSocketManager

# Firebase notifications (optional, best-effort)
try:
    from firebase_notifications import send_chat_message_notification
    FIREBASE_AVAILABLE = True
except ImportError as e:
    print(f"Firebase layer not available - push notifications disabled: {e}")
    FIREBASE_AVAILABLE = False

# DynamoDB for user profiles (to get FCM token and names)
dynamodb = boto3.resource('dynamodb')
USER_PROFILES_TABLE = os.environ.get('USER_PROFILES_TABLE', 'dev-UserProfiles')
user_profiles_table = dynamodb.Table(USER_PROFILES_TABLE)

# Cognito client for fallback name retrieval
cognito = boto3.client('cognito-idp')
USER_POOL_ID = os.environ.get('USER_POOL_ID')

def get_name_from_cognito(user_id):
    """
    Fetch user name from Cognito as fallback if missing in DynamoDB
    """
    if not USER_POOL_ID:
        print("WARNING: USER_POOL_ID not set, skipping Cognito lookup")
        return None
        
    try:
        response = cognito.admin_get_user(
            UserPoolId=USER_POOL_ID,
            Username=user_id
        )
        attributes = {attr['Name']: attr['Value'] for attr in response.get('UserAttributes', [])}
        
        given_name = attributes.get('given_name', '').strip()
        family_name = attributes.get('family_name', '').strip()
        
        if given_name or family_name:
            return f"{given_name} {family_name}".strip()
            
        # Try 'name' attribute
        full_name = attributes.get('name', '').strip()
        if full_name:
            return full_name
            
        # Try 'email' as last resort? No, better use generic name
        return None
            
    except Exception as e:
        print(f"Error fetching user {user_id} from Cognito: {str(e)}")
        return None

def lambda_handler(event, context):
    """
    Send a message in a chat
    
    Path parameters:
    - chat_id: The chat ID
    
    Expected input:
    {
        "message_text": "Hello!",
        "attachments": [
            {
                "file_name": "document.pdf",
                "file_size": 12345,
                "file_type": "application/pdf",
                "s3_url": "https://..."
            }
        ]
    }
    
    Authorization header contains JWT with user info
    """
    try:
        # Get chat_id from path parameters
        chat_id = event['pathParameters']['chat_id']
        
        # Get user info from authorizer context (Cognito)
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_type = event['requestContext']['authorizer']['claims'].get('custom:user_type', 'worker')
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Parse Cognito groups (can be comma-separated string or list)
        if isinstance(user_groups, str):
            user_groups = [g.strip() for g in user_groups.split(',')] if user_groups else []
        
        # Check if user is Beezey staff
        is_beezey_staff = any(group in user_groups for group in ['beezey_staff', 'beezey_admin', 'admins'])
        
        # Parse request body
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', {})
        
        # Get message text and attachments
        message_text = body.get('message_text', '').strip()
        attachments_data = body.get('attachments', [])
        
        # Validate: either message_text OR attachments must be present
        if not message_text and not attachments_data:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'code': 4045,
                    'error': 'Bad Request',
                    'message': 'Either message_text or attachments is required'
                })
            }
        
        
        db_manager = ChatDBManager()
        
        # Verify chat exists and user has access
        chat = db_manager.get_chat(chat_id)
        if not chat:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'code': 4047,
                    'error': 'Not Found',
                    'message': 'Chat not found'
                })
            }
        
        # Authorization: Allow participants OR Beezey staff
        is_participant = user_id in [chat.worker_id, chat.company_representative_id]
        
        # Check if backoffice operator is assigned
        has_backoffice_access = chat.backoffice_operator_id and user_id == chat.backoffice_operator_id
        
        if not is_participant and not is_beezey_staff and not has_backoffice_access:
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'code': 4046,
                    'error': 'Forbidden',
                    'message': 'You are not authorized to send messages in this chat'
                })
            }
        
        # Determine sender type
        if is_beezey_staff or has_backoffice_access:
            # Beezey staff and backoffice operators always send as BEEZEY type
            sender_type = SenderType.BEEZEY
        elif user_id == chat.worker_id:
            sender_type = SenderType.WORKER
        elif user_id == chat.company_representative_id:
            sender_type = SenderType.COMPANY
        else:
            sender_type = SenderType(user_type)
        
        # Parse attachments
        attachments = []
        if attachments_data:
            print(f"DEBUG: Received {len(attachments_data)} attachments: {json.dumps(attachments_data)}")
            for att_data in attachments_data:
                attachment = Attachment(
                    file_name=att_data['file_name'],
                    file_size=att_data['file_size'],
                    file_type=att_data['file_type'],
                    s3_url=att_data['s3_url'],
                    uploaded_at=get_current_timestamp()
                )
                attachments.append(attachment)
            print(f"DEBUG: Created {len(attachments)} Attachment objects")
        else:
            print(f"DEBUG: No attachments in request")
        
        # Create message
        message = Message(
            chat_id=chat_id,
            message_id=generate_message_id(),
            sender_id=user_id,
            sender_type=sender_type,
            message_text=message_text,
            timestamp=get_current_timestamp(),
            state=MessageState.SENT,
            attachments=attachments
        )
        
        # Save message to database
        db_manager.create_message(message)
        
        # Track if backoffice operator was assigned (for response code)
        operator_assigned = False
        
        # Check if message contains @girolavoro mention (case insensitive)
        # If so, assign a backoffice operator to the chat automatically
        if message_text and '@girolavoro' in message_text.lower():
            # Check if operator not already assigned
            if not chat.backoffice_operator_id:
                # Use hardcoded admin user ID (gioelemaruccia8@gmail.com)
                default_operator_id = 'b63ee210-60f1-7072-682c-1a394a67d7e0'
                
                try:
                    db_manager.assign_backoffice_operator(chat_id, default_operator_id)
                    operator_assigned = True
                    print(f"Backoffice operator assigned to chat {chat_id} due to @girolavoro mention")
                    
                    # Send automatic notification message
                    operator_notification = Message(
                        chat_id=chat_id,
                        message_id=generate_message_id(),
                        sender_id="beezey_system",
                        sender_type=SenderType.BEEZEY,
                        message_text="🆘 **Supporto girolavoro Attivato**\n\nUn operatore del nostro team è stato assegnato a questa chat e ti risponderà al più presto.\n\nGrazie per la pazienza!",
                        timestamp=get_current_timestamp(),
                        state=MessageState.SENT,
                        attachments=[]
                    )
                    db_manager.create_message(operator_notification)
                    
                    # Broadcast operator notification via WebSocket
                    try:
                        ws_manager = WebSocketManager()
                        ws_manager.broadcast_to_chat(
                            chat_id=chat_id,
                            sender_id="beezey_system",
                            data={
                                'action': 'new_message',
                                'message': operator_notification.to_api_response()
                            }
                        )
                        ws_manager.broadcast_to_all_chat_participants(
                            chat_id=chat_id,
                            data={
                                'action': 'chat_updated',
                                'chatId': chat_id,
                                'lastMessagePreview': operator_notification.message_text[:100],
                                'lastMessageAt': operator_notification.timestamp,
                                'lastMessageSenderId': 'beezey_system',
                                'lastMessageState': operator_notification.state.value,
                                # Campi aggiuntivi 1:1 con GET /chats
                                'jobName': chat.job_name,
                                'startDate': chat.start_date,
                                'endDate': chat.end_date,
                                'bookingStatus': chat.booking_state,
                                'interlocutorPhoto': None,  # user-specific, non inviabile via broadcast
                            }
                        )
                    except Exception as ws_error:
                        print(f"WebSocket broadcast error for operator notification (non-critical): {str(ws_error)}")
                    
                    # =====================================================================
                    # PUSH NOTIFICATIONS - Send to both participants about operator assignment
                    # =====================================================================
                    if FIREBASE_AVAILABLE:
                        try:
                            # Prepare booking range
                            booking_range = None
                            if chat.start_date and chat.end_date:
                                try:
                                    from datetime import datetime as dt
                                    start = dt.strptime(chat.start_date, '%Y-%m-%d')
                                    end = dt.strptime(chat.end_date, '%Y-%m-%d')
                                    booking_range = f"{start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}"
                                except:
                                    booking_range = f"{chat.start_date} - {chat.end_date}"
                            
                            message_preview = "🆘 Supporto girolavoro attivato! Un operatore del nostro team ti risponderà al più presto."
                            
                            # Send notification to both worker and company
                            for recipient_id in [chat.worker_id, chat.company_representative_id]:
                                try:
                                    recipient_profile = user_profiles_table.get_item(
                                        Key={'user_id': recipient_id}
                                    ).get('Item')
                                    
                                    if recipient_profile:
                                        recipient_fcm_token = recipient_profile.get('fcm_token')
                                        
                                        if recipient_fcm_token:
                                            # Use the interlocutor's name (the other human participant)
                                            # so the FE shows the correct chat title when opening from notification.
                                            interlocutor_id = (
                                                chat.company_representative_id
                                                if recipient_id == chat.worker_id
                                                else chat.worker_id
                                            )
                                            interlocutor_profile = user_profiles_table.get_item(
                                                Key={'user_id': interlocutor_id}
                                            ).get('Item')
                                            interlocutor_name = None
                                            if interlocutor_profile:
                                                interlocutor_name = interlocutor_profile.get('full_name', '').strip() or None
                                                if not interlocutor_name:
                                                    p = interlocutor_profile.get('profile', {}) or {}
                                                    g = p.get('given_name', '').strip()
                                                    f = p.get('family_name', '').strip()
                                                    if g or f:
                                                        interlocutor_name = f"{g} {f}".strip()
                                                if not interlocutor_name:
                                                    n = interlocutor_profile.get('nome', '').strip()
                                                    c = interlocutor_profile.get('cognome', '').strip()
                                                    if n or c:
                                                        interlocutor_name = f"{n} {c}".strip()
                                            if not interlocutor_name:
                                                interlocutor_name = get_name_from_cognito(interlocutor_id) or 'Utente Beezey'

                                            notification_sent = send_chat_message_notification(
                                                fcm_token=recipient_fcm_token,
                                                sender_name=interlocutor_name,
                                                message_preview=message_preview,
                                                chat_id=chat_id,
                                                sender_id="beezey_system",
                                                booking_id=chat.booking_id,
                                                booking_status=chat.booking_state,
                                                job_listing_id=chat.listing_id,
                                                job_listing_title=chat.job_name,
                                                booking_range=booking_range
                                            )
                                            
                                            if notification_sent:
                                                print(f"Push notification sent to {recipient_id} for operator assignment")
                                            else:
                                                print(f"Failed to send push notification to {recipient_id}")
                                        else:
                                            print(f"User {recipient_id} has no FCM token registered")
                                    else:
                                        print(f"Could not fetch profile for user {recipient_id}")
                                
                                except Exception as profile_error:
                                    print(f"Error fetching profile for notification (non-critical): {profile_error}")
                        
                        except Exception as notif_error:
                            print(f"Push notification error for operator assignment (non-critical): {notif_error}")
                    
                except Exception as assign_error:
                    print(f"Error assigning backoffice operator (non-critical): {str(assign_error)}")
                    # Don't fail the request if operator assignment fails
        
        # Broadcast message via WebSocket (Opzione A: best effort, non blocking)
        try:
            ws_manager = WebSocketManager()
            # 1) Invia il messaggio completo all'altro partecipante
            ws_manager.broadcast_to_chat(
                chat_id=chat_id,
                sender_id=user_id,
                data={
                    'action': 'new_message',
                    'message': message.to_api_response()
                }
            )
            # 2) Invia chat_updated personalizzato a ciascun partecipante (incluso sender)
            #    con TUTTI i campi di GET /chats: date dal Booking live, interlocutorName
            #    da Cognito, companyName, ecc. — così il frontend non perde dati corretti
            ws_manager.broadcast_personalized_chat_update(chat_id=chat_id)
        except Exception as ws_error:
            # Log error but don't fail the request (WebSocket is best-effort)
            print(f"WebSocket broadcast error (non-critical): {str(ws_error)}")
        
        # =====================================================================
        # PUSH NOTIFICATIONS - Send FCM notification to recipient
        # =====================================================================
        # Send notification for: message text OR attachments (or both)
        if FIREBASE_AVAILABLE and (message_text or attachments):
            try:
                # Determine recipient (the other participant in the chat)
                recipient_id = None
                if user_id == chat.worker_id:
                    recipient_id = chat.company_representative_id
                elif user_id == chat.company_representative_id:
                    recipient_id = chat.worker_id
                
                if recipient_id:
                    # Get recipient's profile to fetch FCM token and sender name
                    try:
                        recipient_profile = user_profiles_table.get_item(
                            Key={'user_id': recipient_id}
                        ).get('Item')
                        
                        sender_profile = user_profiles_table.get_item(
                            Key={'user_id': user_id}
                        ).get('Item')
                        
                        print(f"DEBUG - Sender profile full data: {json.dumps(sender_profile, default=str)}")
                        
                        if recipient_profile and sender_profile:
                            recipient_fcm_token = recipient_profile.get('fcm_token')
                            
                            # Extract sender name from profile - try multiple fields
                            sender_name = sender_profile.get('full_name')
                            print(f"DEBUG - full_name attempt: '{sender_name}'")
                            if not sender_name or sender_name.strip() == '':
                                # Try nested profile object (given_name + family_name)
                                profile_obj = sender_profile.get('profile', {})
                                print(f"DEBUG - profile_obj: {profile_obj}")
                                given_name = profile_obj.get('given_name', '').strip()
                                family_name = profile_obj.get('family_name', '').strip()
                                print(f"DEBUG - given_name: '{given_name}', family_name: '{family_name}'")
                                if given_name or family_name:
                                    sender_name = f"{given_name} {family_name}".strip()
                                    print(f"DEBUG - sender_name from nested profile: '{sender_name}'")
                            
                            if not sender_name or sender_name.strip() == '':
                                # Try nome + cognome
                                nome = sender_profile.get('nome', '').strip()
                                cognome = sender_profile.get('cognome', '').strip()
                                print(f"DEBUG - nome: '{nome}', cognome: '{cognome}'")
                                sender_name = f"{nome} {cognome}".strip()
                            
                            # Fallback to Cognito if DynamoDB has no name
                            if not sender_name or sender_name.strip() == '':
                                print("DEBUG - Name missing in DynamoDB, trying Cognito fallback...")
                                cognito_name = get_name_from_cognito(user_id)
                                if cognito_name:
                                    sender_name = cognito_name
                                    print(f"DEBUG - Found name in Cognito: '{sender_name}'")

                            # Fallback only if really empty
                            if not sender_name or sender_name.strip() == '':
                                sender_name = 'Utente Beezey'
                            
                            print(f"DEBUG - FINAL sender_name: '{sender_name}'")
                            
                            if recipient_fcm_token:
                                # Build message preview (text or attachment count)
                                if message_text:
                                    message_preview = message_text[:100]
                                    if len(message_text) > 100:
                                        message_preview += "..."
                                elif attachments:
                                    # Se solo allegati, crea preview basato sul numero e tipo
                                    if len(attachments) == 1:
                                        att = attachments[0]
                                        message_preview = f"📎 {att.file_name}"
                                    else:
                                        message_preview = f"📎 {len(attachments)} allegati"
                                else:
                                    message_preview = "Nuovo messaggio"
                                
                                # Prepare booking range if dates are available - convert format to DD/MM/YYYY
                                booking_range = None
                                if chat.start_date and chat.end_date:
                                    try:
                                        # Parse dates (assuming format YYYY-MM-DD)
                                        from datetime import datetime as dt
                                        start = dt.strptime(chat.start_date, '%Y-%m-%d')
                                        end = dt.strptime(chat.end_date, '%Y-%m-%d')
                                        booking_range = f"{start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}"
                                    except:
                                        booking_range = f"{chat.start_date} - {chat.end_date}"
                                
                                # Get sender avatar if available
                                avatar_url = sender_profile.get('profile_photo_url')
                                
                                # Send Firebase notification with all booking context
                                notification_sent = send_chat_message_notification(
                                    fcm_token=recipient_fcm_token,
                                    sender_name=sender_name,
                                    message_preview=message_preview,
                                    chat_id=chat_id,
                                    sender_id=user_id,
                                    booking_id=chat.booking_id,
                                    booking_status=chat.booking_state,
                                    job_listing_id=chat.listing_id,
                                    job_listing_title=chat.job_name,
                                    booking_range=booking_range
                                )
                                
                                if notification_sent:
                                    print(f"Push notification sent to {recipient_id}")
                                else:
                                    print(f"Failed to send push notification to {recipient_id}")
                            else:
                                print(f"Recipient {recipient_id} has no FCM token registered")
                        else:
                            print(f"Could not fetch profiles for sender or recipient")
                    
                    except Exception as profile_error:
                        print(f"Error fetching user profiles for notification: {profile_error}")
                
            except Exception as notif_error:
                # Log error but don't fail the request (notifications are best-effort)
                print(f"Push notification error (non-critical): {notif_error}")
        
        # Return response
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 3007 if operator_assigned else 3006,
                'message': message.to_api_response()
            })
        }
        
    except KeyError as e:
        print(f"Missing required parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 4045,
                'error': 'Bad Request',
                'message': f'Missing required parameter: {str(e)}'
            })
        }
    
    except ValueError as e:
        print(f"Validation error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 4045,
                'error': 'Bad Request',
                'message': str(e)
            })
        }
    
    except Exception as e:
        print(f"Error sending message: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 5011,
                'error': 'Internal Server Error',
                'message': 'Internal server error'
            })
        }