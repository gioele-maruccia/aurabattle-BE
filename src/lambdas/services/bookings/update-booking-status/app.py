"""
Update Booking Status Handler

This Lambda function updates a booking status (accept/reject).
Company owner only - can accept or reject worker applications.

When accepting:
- Updates booking status to 'confirmed'
- Increments listing positionsFilled counter
- Sends automatic message in chat

When rejecting:
- Updates booking status to 'rejected'
- Optionally records rejection reason
- Sends automatic message in chat with rejection reason
"""

import json
import os
import sys
import boto3
from datetime import datetime, timezone
from decimal import Decimal

# Add chat shared layer to path (if available)
sys.path.append('/opt/python')

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])
user_profiles_table = dynamodb.Table(os.environ.get('USER_PROFILES_TABLE_NAME', 'prod-UserProfiles'))

# Firebase notifications (optional, best-effort)
try:
    from firebase_notifications import send_chat_message_notification
    FIREBASE_AVAILABLE = True
except ImportError:
    print("Firebase layer not available - push notifications disabled")
    FIREBASE_AVAILABLE = False


def _extract_name_from_profile(profile):
    """Extract display name from a DynamoDB UserProfile item."""
    if not profile:
        return None
    name = profile.get('full_name', '').strip()
    if name:
        return name
    p = profile.get('profile', {}) or {}
    given = p.get('given_name', '').strip()
    family = p.get('family_name', '').strip()
    if given or family:
        return f"{given} {family}".strip()
    nome = profile.get('nome', '').strip()
    cognome = profile.get('cognome', '').strip()
    if nome or cognome:
        return f"{nome} {cognome}".strip()
    return None


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def send_booking_status_message_to_chat(
    booking_id,
    new_status,
    rejection_reason=None,
    booking_details=None,
    booking_obj=None,
    actor_is_company=None,
):
    """
    Send automatic message to chat when booking status changes.
    Also sends review reminder messages when booking is completed.
    
    Args:
        booking_id: ID of the booking
        new_status: New status ('confirmed', 'rejected', 'completed', etc.)
        rejection_reason: Reason for rejection (if applicable)
        booking_details: Additional booking details for message context
        booking_obj: Full booking object (needed for review messages)
        actor_is_company: True se l'azione è stata eseguita dalla company,
                          False se dal worker, None se non noto.
                          Usato per pre-marcare il flag di lettura dell'attore
                          (l'attore ha già 'visto' il risultato della propria azione).
    """
    try:
        # Import chat modules (they're in the shared layer)
        from db_manager import ChatDBManager
        from models import generate_booking_status_message
        
        db_manager = ChatDBManager()
        
        # Get chat associated with this booking
        chat = db_manager.get_chat_by_booking(booking_id)
        
        if not chat:
            print(f"No chat found for booking {booking_id}, skipping status message")
            return
        
        # Generate status message
        status_message = generate_booking_status_message(
            chat=chat,
            booking_status=new_status,
            rejection_reason=rejection_reason,
            booking_details=booking_details
        )
        
        # Pre-marca il flag di lettura dell'attore:
        # chi ha triggered l'azione ha già 'visto' il risultato → non conta come unread per loro.
        # L'altra parte invece deve ancora vedere il messaggio → flag rimane False.
        if actor_is_company is True:
            status_message.read_company = True
        elif actor_is_company is False:
            status_message.read_worker = True

        # Save message to chat
        db_manager.create_message(status_message)
        print(f"Booking status message sent to chat {chat.chat_id}")

        # Marca anche i messaggi beezey precedenti (es. welcome COMPANY_ACCEPT_DATES)
        # come letti per l'attore, poiché ha già operato sulla chat.
        if actor_is_company is not None:
            try:
                db_manager.mark_all_beezey_messages_read_for_role(
                    chat_id=chat.chat_id,
                    is_company=actor_is_company,
                )
            except Exception as mark_err:
                print(f"Could not mark previous beezey messages as read (non-critical): {mark_err}")

        def _broadcast_message_to_chat(message_obj):
            """Best-effort WebSocket broadcast for automatic chat messages."""
            try:
                from ws_manager import WebSocketManager
                ws_manager = WebSocketManager()

                # Send the new message event to both participants.
                ws_manager.broadcast_to_all_chat_participants(
                    chat_id=chat.chat_id,
                    data={
                        'action': 'new_message',
                        'sender_id': message_obj.sender_id,
                        'message': message_obj.to_api_response()
                    }
                )

                # Keep both chat list items in sync with latest booking/chat data.
                ws_manager.broadcast_personalized_chat_update(chat_id=chat.chat_id)
            except Exception as ws_error:
                print(f"WebSocket broadcast error (non-critical): {str(ws_error)}")
        
        # =====================================================================
        # PUSH NOTIFICATIONS - Send FCM notification to recipient
        # =====================================================================
        # Send notification when booking status changes (confirm/reject)
        if FIREBASE_AVAILABLE and new_status in ['confirmed', 'rejected']:
            try:
                # Recipient is the worker (status updates come from company)
                recipient_id = chat.worker_id
                
                if recipient_id:
                    # Get recipient's profile to fetch FCM token
                    try:
                        recipient_profile = user_profiles_table.get_item(
                            Key={'user_id': recipient_id}
                        ).get('Item')
                        
                        if recipient_profile:
                            recipient_fcm_token = recipient_profile.get('fcm_token')
                            
                            if recipient_fcm_token:
                                # Build message preview based on status
                                if new_status == 'confirmed':
                                    message_preview = "✅ La tua candidatura è stata accettata!"
                                elif new_status == 'rejected':
                                    message_preview = f"❌ Candidatura rifiutata"
                                    if rejection_reason:
                                        message_preview += f": {rejection_reason[:50]}"
                                else:
                                    message_preview = f"📋 Candidatura: {new_status}"
                                
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
                                
                                # Status updates come from the company → the worker's interlocutor
                                # is the company representative. Use their name so the FE shows
                                # the correct chat title when opening from the notification.
                                company_profile = user_profiles_table.get_item(
                                    Key={'user_id': chat.company_representative_id}
                                ).get('Item')
                                interlocutor_name = _extract_name_from_profile(company_profile) or 'Azienda'
                                
                                # Send notification with all booking context
                                notification_sent = send_chat_message_notification(
                                    fcm_token=recipient_fcm_token,
                                    sender_name=interlocutor_name,
                                    message_preview=message_preview,
                                    chat_id=chat.chat_id,
                                    sender_id="beezey_system",
                                    booking_id=chat.booking_id,
                                    booking_status=new_status,
                                    job_listing_id=chat.listing_id,
                                    job_listing_title=chat.job_name,
                                    booking_range=booking_range
                                )
                                
                                if notification_sent:
                                    print(f"Push notification sent to worker {recipient_id} for booking status: {new_status}")
                                else:
                                    print(f"Failed to send push notification to worker {recipient_id}")
                            else:
                                print(f"Worker {recipient_id} has no FCM token registered")
                        else:
                            print(f"Could not fetch profile for worker {recipient_id}")
                    
                    except Exception as profile_error:
                        print(f"Error fetching worker profile for notification: {profile_error}")
                
            except Exception as notif_error:
                # Log error but don't fail the request (notifications are best-effort)
                print(f"Push notification error (non-critical): {notif_error}")
        
        # If booking is completed, send ONE review reminder message (visible to both parties)
        if new_status == 'completed' and booking_obj:
            try:
                try:
                    from models import generate_review_reminder_message
                except ImportError as import_error:
                    print(f"Review reminder message not available in layer: {str(import_error)}")
                else:
                    # Send ONE review reminder message to chat
                    review_message = generate_review_reminder_message(
                        chat=chat,
                        booking_details=booking_details
                    )
                    db_manager.create_message(review_message)
                    print(f"Review reminder message sent to chat {chat.chat_id}")

                    # Broadcast review reminder message in real-time to both participants.
                    _broadcast_message_to_chat(review_message)
                    
                    # =====================================================================
                    # PUSH NOTIFICATIONS - Send to both participants about review reminder
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
                            
                            message_preview = "⭐ Lavoro completato! Lascia una recensione per aiutare altri utenti."
                            
                            # Send notification to both worker and company
                            for recipient_id in [chat.worker_id, chat.company_representative_id]:
                                try:
                                    recipient_profile = user_profiles_table.get_item(
                                        Key={'user_id': recipient_id}
                                    ).get('Item')
                                    
                                    if recipient_profile:
                                        recipient_fcm_token = recipient_profile.get('fcm_token')
                                        
                                        if recipient_fcm_token:
                                            # Use the interlocutor's name so the FE shows
                                            # the correct chat title when opening from notification.
                                            interlocutor_id = (
                                                chat.company_representative_id
                                                if recipient_id == chat.worker_id
                                                else chat.worker_id
                                            )
                                            interlocutor_profile = user_profiles_table.get_item(
                                                Key={'user_id': interlocutor_id}
                                            ).get('Item')
                                            interlocutor_name = _extract_name_from_profile(interlocutor_profile) or 'Utente Beezey'

                                            notification_sent = send_chat_message_notification(
                                                fcm_token=recipient_fcm_token,
                                                sender_name=interlocutor_name,
                                                message_preview=message_preview,
                                                chat_id=chat.chat_id,
                                                sender_id="beezey_system",
                                                booking_id=chat.booking_id,
                                                booking_status=new_status,
                                                job_listing_id=chat.listing_id,
                                                job_listing_title=chat.job_name,
                                                booking_range=booking_range
                                            )
                                            
                                            if notification_sent:
                                                print(f"Review reminder notification sent to {recipient_id}")
                                            else:
                                                print(f"Failed to send review reminder notification to {recipient_id}")
                                        else:
                                            print(f"User {recipient_id} has no FCM token registered")
                                    else:
                                        print(f"Could not fetch profile for user {recipient_id}")
                                
                                except Exception as profile_error:
                                    print(f"Error fetching profile for review notification (non-critical): {profile_error}")
                        
                        except Exception as notif_error:
                            print(f"Push notification error for review reminder (non-critical): {notif_error}")
                
            except Exception as review_msg_error:
                print(f"Error sending review reminder message (non-critical): {str(review_msg_error)}")
                # Don't fail the entire operation if review message fails
        
        # Broadcast the main status message in real-time to both participants.
        _broadcast_message_to_chat(status_message)
        
    except ImportError as e:
        print(f"Chat modules not available (layer not attached?): {str(e)}")
        print("Skipping chat message - this is expected if chat layer is not attached")
    except Exception as e:
        print(f"Error sending booking status message to chat: {str(e)}")
        # Don't fail the entire request if chat message fails


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    PATCH /bookings/{bookingId}/status
    
    Required fields in body:
    - status: New status ('confirmed' or 'rejected')
    - rejectionReason: Required if status is 'rejected'
    
    Authorization: Cognito JWT (company owner only)
    """
    
    try:
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Check if user is in 'companies' group
        if 'companies' not in user_groups:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4035,
                    'error': 'Forbidden',
                    'message': 'Only company users can update booking status'
                })
            }
        
        # Get booking ID from path
        booking_id = event['pathParameters']['bookingId']
        
        # Parse request body
        body = json.loads(event['body'])
        
        # Validate required fields
        if 'status' not in body:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'Missing required field: status'
                })
            }
        
        new_status = body['status']
        rejection_reason = body.get('rejectionReason')
        
        # Validate status value
        if new_status not in ['confirmed', 'rejected']:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4032,
                    'error': 'Bad Request',
                    'message': 'Status must be "confirmed" or "rejected"'
                })
            }
        
        # Require rejection reason if rejecting
        if new_status == 'rejected' and not rejection_reason:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4032,
                    'error': 'Bad Request',
                    'message': 'rejectionReason is required when rejecting a booking'
                })
            }
        
        # Get booking
        try:
            booking_response = bookings_table.get_item(Key={'bookingId': booking_id})
            if 'Item' not in booking_response:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4037,
                        'error': 'Not Found',
                        'message': 'Booking not found'
                    })
                }
            
            booking = booking_response['Item']
            
            # Check booking type
            if booking.get('bookingType') == 'blackout':
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4032,
                        'error': 'Bad Request',
                        'message': 'Cannot update status of blackout period'
                    })
                }
            
        except Exception as e:
            print(f"Error fetching booking: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5000,
                    'error': 'Internal Server Error',
                    'message': 'Error fetching booking'
                })
            }
        
        # Verify user owns the booking's company
        try:
            company_response = companies_table.get_item(Key={'userId': user_id})
            if 'Item' not in company_response:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4035,
                        'error': 'Forbidden',
                        'message': 'Company profile not found'
                    })
                }
            
            company = company_response['Item']
            
            if company['companyId'] != booking['companyId']:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4036,
                        'error': 'Forbidden',
                        'message': 'You can only update bookings for your own listings'
                    })
                }
                
        except Exception as e:
            print(f"Error verifying ownership: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5000,
                    'error': 'Internal Server Error',
                    'message': 'Error verifying ownership'
                })
            }
        
        # Check current status
        current_status = booking.get('status')
        if current_status != 'pending':
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4033,
                    'error': 'Bad Request',
                    'message': f'Can only update pending bookings. Current status: {current_status}'
                })
            }
        
        # If confirming, check if positions still available
        if new_status == 'confirmed':
            try:
                listing_response = job_listings_table.get_item(Key={'listingId': booking['listingId']})
                if 'Item' not in listing_response:
                    return {
                        'statusCode': 404,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'code': 4038,
                            'error': 'Not Found',
                            'message': 'Job listing not found'
                        })
                    }
                
                listing = listing_response['Item']
                positions_available = int(listing.get('positions', 1))

                # Count confirmed bookings whose date range overlaps with this booking.
                # Two ranges [A_start, A_end] and [B_start, B_end] overlap when:
                #   A_start <= B_end  AND  B_start <= A_end
                # We query the GSI for all bookings with startDate <= booking_end,
                # then filter those whose endDate >= booking_start and status = confirmed.
                from boto3.dynamodb.conditions import Key as _Key, Attr as _Attr
                booking_start = booking.get('startDate', '')
                booking_end = booking.get('endDate', '')
                overlap_resp = bookings_table.query(
                    IndexName='listingId-startDate-index',
                    KeyConditionExpression=_Key('listingId').eq(booking['listingId']) & _Key('startDate').lte(booking_end),
                    FilterExpression=_Attr('endDate').gte(booking_start) & _Attr('status').eq('confirmed'),
                    Select='COUNT'
                )
                overlapping_confirmed = overlap_resp.get('Count', 0)
                print(f"Overlapping confirmed bookings for listing {booking['listingId']} in [{booking_start}, {booking_end}]: {overlapping_confirmed} / {positions_available}")

                if overlapping_confirmed >= positions_available:
                    return {
                        'statusCode': 400,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'code': 4034,
                            'error': 'Bad Request',
                            'message': 'All positions are already filled for the requested dates'
                        })
                    }
                
            except Exception as e:
                print(f"Error checking positions: {str(e)}")
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 5000,
                        'error': 'Internal Server Error',
                        'message': 'Error checking position availability'
                    })
                }
        
        # Update booking status
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        update_expression = 'SET #status = :status, updatedAt = :updatedAt, reviewedBy = :reviewedBy, reviewedAt = :reviewedAt'
        expression_values = {
            ':status': new_status,
            ':updatedAt': now,
            ':reviewedBy': user_id,
            ':reviewedAt': now
        }
        expression_names = {
            '#status': 'status'
        }
        
        if new_status == 'rejected':
            update_expression += ', rejectionReason = :rejectionReason'
            expression_values[':rejectionReason'] = rejection_reason
        
        try:
            bookings_table.update_item(
                Key={'bookingId': booking_id},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
                ExpressionAttributeNames=expression_names
            )
            
        except Exception as e:
            print(f"Error updating booking: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5000,
                    'error': 'Internal Server Error',
                    'message': 'Error updating booking'
                })
            }
        
        # If confirmed, increment listing positionsFilled
        if new_status == 'confirmed':
            try:
                job_listings_table.update_item(
                    Key={'listingId': booking['listingId']},
                    UpdateExpression='ADD positionsFilled :inc',
                    ExpressionAttributeValues={':inc': 1}
                )
                print(f"Incremented positionsFilled for listing {booking['listingId']}")
                
            except Exception as e:
                print(f"Error updating listing positions: {str(e)}")
                # Non-critical error, continue
            
            # ============================================
            # AUTO-CANCEL OVERLAPPING BOOKINGS
            # 1. Cancel all other pending bookings of the SAME WORKER that overlap
            #    in dates (a worker can only hold one confirmed booking at a time).
            # 2. If confirming this booking fills the last available position for
            #    those dates, also cancel all OTHER workers' pending bookings for
            #    the same listing (no more slots available).
            # ============================================
            try:
                from boto3.dynamodb.conditions import Key, Attr
                
                # Helper function to check date overlap
                def check_overlap(start1, end1, start2, end2):
                    from datetime import datetime
                    s1 = datetime.fromisoformat(start1.replace('Z', '+00:00'))
                    e1 = datetime.fromisoformat(end1.replace('Z', '+00:00'))
                    s2 = datetime.fromisoformat(start2.replace('Z', '+00:00'))
                    e2 = datetime.fromisoformat(end2.replace('Z', '+00:00'))
                    return s1 < e2 and s2 < e1

                def _do_cancel_booking(bid, reason_msg):
                    """Cancel a booking by id and send chat notification."""
                    cancel_update_expr = (
                        'SET #status = :cancelled, updatedAt = :updatedAt, '
                        'cancelledAt = :cancelledAt, cancelledBy = :system, '
                        'cancelledByRole = :system_role, cancellationReason = :reason'
                    )
                    cancel_values = {
                        ':cancelled': 'cancelled',
                        ':updatedAt': now,
                        ':cancelledAt': now,
                        ':system': 'system_auto_cancel',
                        ':system_role': 'system',
                        ':reason': reason_msg,
                    }
                    bookings_table.update_item(
                        Key={'bookingId': bid},
                        UpdateExpression=cancel_update_expr,
                        ExpressionAttributeValues=cancel_values,
                        ExpressionAttributeNames={'#status': 'status'}
                    )
                    try:
                        from db_manager import ChatDBManager
                        from models import generate_booking_status_message
                        db_manager = ChatDBManager()
                        other_chat = db_manager.get_chat_by_booking(bid)
                        if other_chat:
                            cancel_message = generate_booking_status_message(
                                chat=other_chat,
                                booking_status='cancelled',
                                rejection_reason=None,
                                booking_details={'reason': reason_msg}
                            )
                            # La cancellazione è triggerata dalla company → pre-marca
                            # readCompany=True (la company è già al corrente).
                            # Il worker invece deve ancora vedere il messaggio.
                            cancel_message.read_company = True
                            db_manager.create_message(cancel_message)
                            db_manager.update_booking_state(other_chat.chat_id, 'cancelled')
                            try:
                                from ws_manager import WebSocketManager
                                ws_manager = WebSocketManager()
                                ws_manager.broadcast_to_all_chat_participants(
                                    chat_id=other_chat.chat_id,
                                    data={
                                        'action': 'new_message',
                                        'sender_id': cancel_message.sender_id,
                                        'message': cancel_message.to_api_response()
                                    }
                                )
                                ws_manager.broadcast_personalized_chat_update(chat_id=other_chat.chat_id)
                            except Exception as ws_error:
                                print(f"WebSocket broadcast error for auto-cancel (non-critical): {str(ws_error)}")
                    except Exception as chat_err:
                        print(f"Error sending cancellation message (non-critical): {str(chat_err)}")

                confirmed_start = booking['startDate']
                confirmed_end = booking['endDate']
                listing_id_for_cancel = booking['listingId']
                worker_id = booking['workerId']
                cancelled_count = 0

                # --- PART 1: cancel same-worker overlapping bookings ---
                worker_bookings = bookings_table.query(
                    IndexName='workerId-startDate-index',
                    KeyConditionExpression=Key('workerId').eq(worker_id),
                    FilterExpression=Attr('bookingType').eq('booking')
                )
                for other_booking in worker_bookings.get('Items', []):
                    other_booking_id = other_booking.get('bookingId')
                    other_status = other_booking.get('status')
                    other_start = other_booking.get('startDate')
                    other_end = other_booking.get('endDate')
                    if other_booking_id == booking_id:
                        continue
                    if other_status in ['confirmed', 'cancelled', 'rejected', 'completed', 'no_show']:
                        continue
                    if check_overlap(confirmed_start, confirmed_end, other_start, other_end):
                        try:
                            _do_cancel_booking(
                                other_booking_id,
                                f'Booking automaticamente annullato perché hai confermato un altro booking ({booking_id}) nello stesso periodo di date.'
                            )
                            cancelled_count += 1
                            print(f"Auto-cancelled same-worker overlapping booking {other_booking_id} (status was {other_status})")
                        except Exception as cancel_err:
                            print(f"Error auto-cancelling booking {other_booking_id}: {str(cancel_err)}")

                # --- PART 2: if positions are now full, cancel other workers' pending bookings ---
                try:
                    listing_resp = job_listings_table.get_item(Key={'listingId': listing_id_for_cancel})
                    listing_item = listing_resp.get('Item', {})
                    positions_total = int(listing_item.get('positions', 1))

                    # Count confirmed bookings overlapping with the just-confirmed booking
                    overlap_resp = bookings_table.query(
                        IndexName='listingId-startDate-index',
                        KeyConditionExpression=Key('listingId').eq(listing_id_for_cancel) & Key('startDate').lte(confirmed_end),
                        FilterExpression=Attr('endDate').gte(confirmed_start) & Attr('status').eq('confirmed'),
                        Select='COUNT'
                    )
                    confirmed_count = overlap_resp.get('Count', 0)
                    print(f"After confirmation: {confirmed_count}/{positions_total} positions filled for listing {listing_id_for_cancel} in [{confirmed_start}, {confirmed_end}]")

                    if confirmed_count >= positions_total:
                        # All positions filled — cancel every pending booking for this listing
                        # that overlaps these dates from other workers
                        pending_resp = bookings_table.query(
                            IndexName='listingId-startDate-index',
                            KeyConditionExpression=Key('listingId').eq(listing_id_for_cancel) & Key('startDate').lte(confirmed_end),
                            FilterExpression=Attr('endDate').gte(confirmed_start) & Attr('status').eq('pending') & Attr('bookingType').eq('booking')
                        )
                        for pending_booking in pending_resp.get('Items', []):
                            pending_id = pending_booking.get('bookingId')
                            pending_worker = pending_booking.get('workerId')
                            if pending_id == booking_id or pending_worker == worker_id:
                                continue  # already handled above or just confirmed
                            try:
                                _do_cancel_booking(
                                    pending_id,
                                    'Tutte le posizioni disponibili per questo annuncio sono state occupate. La tua candidatura è stata annullata automaticamente.'
                                )
                                cancelled_count += 1
                                print(f"Auto-cancelled pending booking {pending_id} from worker {pending_worker} — positions full")
                            except Exception as cancel_err:
                                print(f"Error auto-cancelling pending booking {pending_id}: {str(cancel_err)}")

                except Exception as pos_err:
                    print(f"Error in positions-full auto-cancel (non-critical): {str(pos_err)}")

                if cancelled_count > 0:
                    print(f"Auto-cancelled {cancelled_count} bookings after confirming {booking_id}")

            except Exception as auto_cancel_err:
                print(f"Error in auto-cancel logic (non-critical): {str(auto_cancel_err)}")
                import traceback
                traceback.print_exc()
                # Don't fail the main request if auto-cancel fails
        
        # Get updated booking
        updated_booking = bookings_table.get_item(Key={'bookingId': booking_id})['Item']
        
        print(f"Booking {booking_id} status updated to {new_status}")
        
        # Send automatic message to chat about status change AND sync booking_state
        try:
            # Get listing and company details for message context
            listing_response = job_listings_table.get_item(Key={'listingId': booking['listingId']})
            listing = listing_response.get('Item', {})
            
            company_response = companies_table.query(
                IndexName='companyId-index',
                KeyConditionExpression='companyId = :cid',
                ExpressionAttributeValues={':cid': booking['companyId']},
                Limit=1
            )
            company = company_response['Items'][0] if company_response.get('Items') else {}
            
            booking_details_for_message = {
                'company_name': company.get('businessName', 'N/A'),  # FIX: Campo corretto è businessName
                'job_title': listing.get('title', 'N/A'),  # FIX: Campo corretto è title
                'start_date': booking.get('startDate', 'N/A')
            }
            
            send_booking_status_message_to_chat(
                booking_id=booking_id,
                new_status=new_status,
                rejection_reason=rejection_reason if new_status == 'rejected' else None,
                booking_details=booking_details_for_message,
                booking_obj=booking,
                # Solo company può chiamare questo endpoint → l'attore è sempre la company.
                # Questo pre-marca readCompany=True sul messaggio di stato E su tutti
                # i messaggi beezey precedenti (es. welcome COMPANY_ACCEPT_DATES),
                # azzerando così il contatore unread per la company.
                actor_is_company=True,
            )
            
            # Sync booking_state in chat
            from db_manager import ChatDBManager
            db_manager = ChatDBManager()
            chat = db_manager.get_chat_by_booking(booking_id)
            if chat:
                db_manager.update_booking_state(chat.chat_id, new_status)
                print(f"Chat {chat.chat_id} booking_state synced to: {new_status}")
            
        except Exception as chat_msg_error:
            print(f"Error sending chat message or syncing state (non-critical): {str(chat_msg_error)}")
            # Don't fail the request if chat operations fail
        
        # Convert Decimal back to float for JSON response
        response_booking = json.loads(json.dumps(updated_booking, cls=DecimalEncoder))
        
        # Enrich with listing and company details for response (ListingSummary & CompanySummary)
        try:
            listing_response = job_listings_table.get_item(Key={'listingId': updated_booking['listingId']})
            if 'Item' in listing_response:
                listing = listing_response['Item']
                response_booking['listing'] = {
                    'listingId': listing.get('listingId'),
                    'title': listing.get('title'),
                    'category': listing.get('category'),
                    'positions': int(listing.get('positions', 1)),
                    'positionsFilled': int(listing.get('positionsFilled', 0)),
                    'positionsRemaining': int(listing.get('positions', 1)) - int(listing.get('positionsFilled', 0)),
                    'startDate': listing.get('startDate'),
                    'endDate': listing.get('endDate'),
                    'status': listing.get('status', 'published')
                }
        except Exception as e:
            print(f"Error fetching listing details: {str(e)}")
        
        try:
            from boto3.dynamodb.conditions import Key
            company_response = companies_table.query(
                IndexName='companyId-index',
                KeyConditionExpression=Key('companyId').eq(updated_booking['companyId']),
                Limit=1
            )
            if company_response.get('Items'):
                company = company_response['Items'][0]
                response_booking['company'] = {
                    'companyId': company.get('companyId'),
                    'businessName': company.get('businessName'),
                    'logoUrl': company.get('media', {}).get('profileImageUrl', ''),
                    'rating': float(company.get('stats', {}).get('averageRating', 0))
                }
        except Exception as e:
            print(f"Error fetching company details: {str(e)}")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 3003,
                'statusCode': 200,
                'message': f'Booking {new_status} successfully',
                'booking': response_booking
            })
        }
        
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 4032,
                'error': 'Bad Request',
                'message': 'Invalid JSON in request body'
            })
        }
    
    except Exception as e:
        print(f"Error updating booking status: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 5000,
                'error': 'Internal Server Error',
                'message': 'An error occurred while updating booking status'
            })
        }