import json
import os
import sys
import boto3

# Add shared layer to path
sys.path.append('/opt/python')


# Architecture Note:
# This Lambda uses ChatDBManager (from shared layer) instead of direct boto3 calls.
# This provides better separation of concerns, testability, and maintainability.
# The manager abstracts DynamoDB operations and is shared across all chat lambdas.
from models import (
    Chat, ChatStatus, generate_chat_id, 
    get_current_timestamp, generate_beezey_welcome_message
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

# DynamoDB for user profiles (to get FCM token)
dynamodb = boto3.resource('dynamodb')
USER_PROFILES_TABLE = os.environ.get('USER_PROFILES_TABLE', 'dev-UserProfiles')
user_profiles_table = dynamodb.Table(USER_PROFILES_TABLE)

# Cognito client for fallback name retrieval
cognito = boto3.client('cognito-idp')
USER_POOL_ID = os.environ.get('USER_POOL_ID')


def get_user_name(user_id, profile=None):
    """
    Extract display name for a user from their DynamoDB profile (already fetched),
    falling back to Cognito attributes.
    """
    if profile:
        name = profile.get('full_name', '').strip()
        if name:
            return name
        profile_obj = profile.get('profile', {}) or {}
        given = profile_obj.get('given_name', '').strip()
        family = profile_obj.get('family_name', '').strip()
        if given or family:
            return f"{given} {family}".strip()
        nome = profile.get('nome', '').strip()
        cognome = profile.get('cognome', '').strip()
        if nome or cognome:
            return f"{nome} {cognome}".strip()

    # Cognito fallback
    if USER_POOL_ID:
        try:
            response = cognito.admin_get_user(UserPoolId=USER_POOL_ID, Username=user_id)
            attrs = {a['Name']: a['Value'] for a in response.get('UserAttributes', [])}
            given = attrs.get('given_name', '').strip()
            family = attrs.get('family_name', '').strip()
            if given or family:
                return f"{given} {family}".strip()
            full = attrs.get('name', '').strip()
            if full:
                return full
        except Exception as e:
            print(f"Cognito lookup failed for {user_id}: {e}")

    return None


def lambda_handler(event, context):
    """
    Create a new chat when a worker applies for a job
    
    Expected input:
    {
        "booking_id": "uuid",
        "worker_id": "uuid",
        "company_representative_id": "uuid",  # User ID del rappresentante aziendale
        "booking_details": {
            "job_title": "...",
            "company_name": "...",
            "start_date": "...",
            "compensation": "..."
        }
    }
    """
    try:
        # Parse request
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', {})
        
        # Validate required fields
        required_fields = ['booking_id', 'worker_id', 'company_representative_id', 'booking_details']
        for field in required_fields:
            if field not in body:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({'error': 'Bad Request', 'message': f'Missing required field: {field}', 'code': 4172})
                }
        
        db_manager = ChatDBManager()
        
        # Check if chat already exists for this booking
        existing_chat = db_manager.get_chat_by_booking(body['booking_id'])
        if existing_chat:
            return {
                'statusCode': 409,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'error': 'Conflict',
                    'message': 'Chat already exists for this booking',
                    'chat': existing_chat.to_api_response(),
                    'code': 4174
                })
            }
        
        # Create chat
        chat = Chat(
            chat_id=generate_chat_id(),
            booking_id=body['booking_id'],
            worker_id=body['worker_id'],
            company_representative_id=body['company_representative_id'],
            created_at=get_current_timestamp(),
            status=ChatStatus.ACTIVE,
            booking_state=body['booking_details'].get('booking_status', 'pending'),  # Initialize from booking
            listing_id=body['booking_details'].get('listing_id'),  # Job listing ID
            # Nuovi campi per evitare chiamate API aggiuntive dal frontend
            job_name=body['booking_details'].get('job_title'),
            start_date=body['booking_details'].get('start_date'),
            end_date=body['booking_details'].get('end_date')
        )
        
        # Save chat to database
        db_manager.create_chat(chat)
        
        # Generate and save Beezey welcome message
        welcome_message = generate_beezey_welcome_message(
            chat=chat,
            booking_details=body['booking_details']
        )
        # La chat è creata dal worker: il messaggio di benvenuto Beezey è
        # già "letto" per il worker (è lui che ha avviato il booking).
        # La company invece non lo ha ancora visto → read_company rimane False.
        welcome_message.read_worker = True
        db_manager.create_message(welcome_message)

        # =====================================================================
        # WEBSOCKET BROADCAST - Notifica entrambi i partecipanti tramite WS
        # =====================================================================
        # Invia chat_updated a worker e company così la nuova chat appare
        # immediatamente nella lista senza che il frontend debba fare getChats.
        try:
            ws_manager = WebSocketManager()
            ws_manager.broadcast_personalized_chat_update(chat.chat_id)
            print(f"WebSocket chat_updated broadcast sent for new chat {chat.chat_id}")
        except Exception as ws_error:
            print(f"WebSocket broadcast error (non-critical): {ws_error}")

        # =====================================================================
        # PUSH NOTIFICATIONS - Send FCM notification to company representative
        # =====================================================================
        # Notify the company that a new booking/application was received
        if FIREBASE_AVAILABLE:
            try:
                recipient_id = chat.company_representative_id
                
                if recipient_id:
                    # Get recipient's profile to fetch FCM token
                    try:
                        recipient_profile = user_profiles_table.get_item(
                            Key={'user_id': recipient_id}
                        ).get('Item')
                        
                        if recipient_profile:
                            recipient_fcm_token = recipient_profile.get('fcm_token')
                            
                            if recipient_fcm_token:
                                # Build message preview from welcome message
                                message_preview = "📋 Nuova candidatura ricevuta! Un lavoratore ha fatto domanda per una tua posizione."
                                
                                # Prepare booking range if dates are available
                                booking_range = None
                                if chat.start_date and chat.end_date:
                                    try:
                                        from datetime import datetime as dt
                                        start = dt.strptime(chat.start_date, '%Y-%m-%d')
                                        end = dt.strptime(chat.end_date, '%Y-%m-%d')
                                        booking_range = f"{start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}"
                                    except:
                                        booking_range = f"{chat.start_date} - {chat.end_date}"
                                
                                # The company gets notified about the worker's application.
                                # Use the worker's name so the FE shows the correct chat title.
                                worker_profile = user_profiles_table.get_item(
                                    Key={'user_id': chat.worker_id}
                                ).get('Item')
                                interlocutor_name = get_user_name(chat.worker_id, worker_profile) or 'Candidato'
                                
                                # Send Firebase notification with all booking context
                                notification_sent = send_chat_message_notification(
                                    fcm_token=recipient_fcm_token,
                                    sender_name=interlocutor_name,
                                    message_preview=message_preview,
                                    chat_id=chat.chat_id,
                                    sender_id="beezey_system",
                                    booking_id=chat.booking_id,
                                    booking_status=chat.booking_state,
                                    job_listing_id=chat.listing_id,
                                    job_listing_title=chat.job_name,
                                    booking_range=booking_range
                                )
                                
                                if notification_sent:
                                    print(f"Push notification sent to company {recipient_id} for new booking")
                                else:
                                    print(f"Failed to send push notification to company {recipient_id}")
                            else:
                                print(f"Company representative {recipient_id} has no FCM token registered")
                        else:
                            print(f"Could not fetch profile for company representative {recipient_id}")
                    
                    except Exception as profile_error:
                        print(f"Error fetching company profile for notification: {profile_error}")
                
            except Exception as notif_error:
                # Log error but don't fail the request (notifications are best-effort)
                print(f"Push notification error (non-critical): {notif_error}")
        
        return {
            'statusCode': 201,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'chat': chat.to_api_response(),
                'welcome_message': welcome_message.to_api_response(),
                'code': 3051
            })
        }
        
    except ValueError as e:
        print(f"Validation error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': str(e), 'code': 4292})
        }
    
    except Exception as e:
        print(f"Error creating chat: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5048})
        }