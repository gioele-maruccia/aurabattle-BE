"""
Confirm Booking Dates Handler

This Lambda function allows a company representative to confirm proposed date changes.
Company only - confirms dates proposed by worker via update-booking-dates API.

NEW WORKFLOW (v2):
- Worker proposes dates via PATCH /bookings/{id}/dates (validates, sends message with payload)
- Company confirms via THIS API: PATCH /bookings/{id}/confirm-dates
- This API updates booking dates AND chat dates
- Updates chat.booking_state with current booking status

Validations:
- Booking must exist and be in 'pending' status
- Only company representative of the booking's company can confirm
- Dates from message payload must still be valid (within listing period, positions available)

When successful:
- Updates booking start_date and end_date
- Updates chat dates (jobName, startDate, endDate)
- Updates chat.booking_state
- Sends confirmation message to chat
"""

import json
import os
import sys
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

# Add chat shared layer to path (if available)
sys.path.append('/opt/python')

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def get_listing_bookings_in_range(listing_id, start_date, end_date, exclude_booking_id=None):
    """
    Get all confirmed/pending bookings in a date range for a listing
    
    Args:
        listing_id: Job listing ID
        start_date: Start date (ISO string)
        end_date: End date (ISO string)
        exclude_booking_id: Booking ID to exclude from count (current booking being modified)
        
    Returns:
        list: List of overlapping bookings
    """
    try:
        response = bookings_table.query(
            IndexName='listingId-startDate-index',
            KeyConditionExpression=Key('listingId').eq(listing_id) & Key('startDate').lte(end_date),
            FilterExpression=Attr('endDate').gte(start_date) & 
                            Attr('status').is_in(['pending', 'confirmed']) &
                            Attr('bookingType').eq('booking')
        )
        
        bookings = response.get('Items', [])
        
        if exclude_booking_id:
            bookings = [b for b in bookings if b['bookingId'] != exclude_booking_id]
        
        return bookings
        
    except Exception as e:
        print(f"Error getting listing bookings: {str(e)}")
        return []


def check_positions_availability(listing_id, start_date, end_date, exclude_booking_id=None):
    """
    Check if positions are available in the new date range
    
    Args:
        listing_id: Job listing ID
        start_date: Start date (ISO string)
        end_date: End date (ISO string)
        exclude_booking_id: Booking ID to exclude (current booking)
        
    Returns:
        tuple: (is_available, error_message)
    """
    try:
        listing_response = job_listings_table.get_item(Key={'listingId': listing_id})
        if 'Item' not in listing_response:
            return False, "Job listing not found"
        
        listing = listing_response['Item']
        total_positions = int(listing.get('positions', 1))
        
        overlapping_bookings = get_listing_bookings_in_range(
            listing_id, 
            start_date, 
            end_date,
            exclude_booking_id
        )
        
        positions_taken = len(overlapping_bookings)
        
        if positions_taken >= total_positions:
            return False, f"No positions available in the date range ({positions_taken}/{total_positions} positions taken)"
        
        return True, None
        
    except Exception as e:
        print(f"Error checking positions availability: {str(e)}")
        return False, f"Error checking availability: {str(e)}"


def update_chat_and_send_confirmation(booking_id, new_start_date, new_end_date, job_title, booking_status):
    """
    Update chat with confirmed booking dates and send confirmation message
    
    Args:
        booking_id: ID of the booking
        new_start_date: Confirmed start date (ISO string)
        new_end_date: Confirmed end date (ISO string)
        job_title: Job title for message context
        booking_status: Current booking status
    """
    try:
        from db_manager import ChatDBManager
        from models import Message, MessageType, SenderType, MessageState
        import uuid
        
        db_manager = ChatDBManager()
        
        # Get chat associated with this booking
        chat = db_manager.get_chat_by_booking(booking_id)
        
        if not chat:
            print(f"No chat found for booking {booking_id}, skipping chat update")
            return
        
        # Update chat dates AND booking_state
        db_manager.update_chat_dates(
            chat_id=chat.chat_id,
            start_date=new_start_date,
            end_date=new_end_date,
            job_name=job_title
        )
        
        # Update booking_state in chat
        db_manager.update_booking_state(chat.chat_id, booking_status)
        print(f"Chat {chat.chat_id} dates and booking_state updated")
        
        # Format dates for message
        start_dt = datetime.fromisoformat(new_start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(new_end_date.replace('Z', '+00:00'))
        start_formatted = start_dt.strftime('%d/%m/%Y')
        end_formatted = end_dt.strftime('%d/%m/%Y')
        
        # Create confirmation message
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        message = Message(
            chat_id=chat.chat_id,
            message_id=str(uuid.uuid4()),
            sender_id="beezey_system",
            sender_type=SenderType.BEEZEY,
            message_text=f"L'azienda ha confermato le nuove date. Date confermate: {start_formatted} - {end_formatted}.",
            timestamp=now,
            state=MessageState.SENT,
            message_type=MessageType.TEXT
        )
        
        db_manager.create_message(message)
        print(f"Confirmation message sent to chat {chat.chat_id}")
        
        # Try to broadcast via WebSocket
        try:
            from ws_manager import WebSocketManager
            ws_manager = WebSocketManager()
            ws_manager.broadcast_to_all_chat_participants(
                chat_id=chat.chat_id,
                data={
                    'action': 'new_message',
                    'sender_id': message.sender_id,
                    'message': message.to_api_response()
                }
            )
            ws_manager.broadcast_personalized_chat_update(chat_id=chat.chat_id)
        except Exception as ws_error:
            print(f"WebSocket broadcast error (non-critical): {str(ws_error)}")
        
    except ImportError as e:
        print(f"Chat modules not available: {str(e)}")
    except Exception as e:
        print(f"Error updating chat and sending confirmation: {str(e)}")


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    PATCH /bookings/{bookingId}/confirm-dates
    
    Required fields in body:
    - startDate: Date to confirm (ISO 8601)
    - endDate: Date to confirm (ISO 8601)
    
    Authorization: Cognito JWT (company representative only)
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
                    'error': 'Forbidden',
                    'message': 'Only company representatives can confirm booking dates',
                    'code': 4233
                })
            }
        
        # Get booking ID from path
        booking_id = event['pathParameters']['bookingId']
        
        # Parse request body
        body = json.loads(event['body'])
        
        # Validate required fields
        required_fields = ['startDate', 'endDate']
        missing_fields = [field for field in required_fields if field not in body]
        
        if missing_fields:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Missing required fields: {", ".join(missing_fields)}',
                    'code': 4234
                })
            }
        
        confirmed_start_date = body['startDate']
        confirmed_end_date = body['endDate']
        
        # Validate dates
        try:
            start_dt = datetime.fromisoformat(confirmed_start_date.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(confirmed_end_date.replace('Z', '+00:00'))
            
            if end_dt <= start_dt:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'End date must be after start date',
                        'code': 4235
                    })
                }
        except ValueError:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'Invalid date format. Use ISO 8601 (YYYY-MM-DD)',
                    'code': 4236
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
                        'error': 'Not Found',
                        'message': 'Booking not found',
                        'code': 4237
                    })
                }
            
            booking = booking_response['Item']
            
            # Check booking type
            if booking.get('bookingType') != 'booking':
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'Cannot confirm dates of non-booking items',
                        'code': 4238
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
                    'error': 'Internal Server Error',
                    'message': 'Error fetching booking',
                    'code': 5068
                })
            }
        
        # Get job listing to verify company ownership
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
                        'error': 'Not Found',
                        'message': 'Job listing not found',
                        'code': 4239
                    })
                }
            
            listing = listing_response['Item']
            
            # Verify company representative belongs to the listing's company
            # Get company rep's companyId from user profile
            from db_manager import UserProfileDBManager
            user_db = UserProfileDBManager()
            company_rep_profile = user_db.get_user_profile(user_id)
            
            if not company_rep_profile or company_rep_profile.get('companyId') != listing.get('companyId'):
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'You can only confirm dates for your company\'s bookings',
                        'code': 4240
                    })
                }
            
        except ImportError:
            print("UserProfileDBManager not available - skipping company ownership check")
        except Exception as e:
            print(f"Error fetching listing or verifying company: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error verifying company ownership',
                    'code': 5069
                })
            }
        
        # Check booking status - must be 'pending'
        current_status = booking.get('status')
        if current_status != 'pending':
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Can only confirm dates of pending bookings. Current status: {current_status}',
                    'code': 4241
                })
            }
        
        # Validate confirmed dates are within listing period
        listing_start = datetime.fromisoformat(listing['startDate'].replace('Z', '+00:00'))
        listing_end = datetime.fromisoformat(listing['endDate'].replace('Z', '+00:00'))
        
        if start_dt < listing_start or end_dt > listing_end:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Confirmed dates must be within job listing period ({listing["startDate"]} to {listing["endDate"]})',
                    'code': 4242
                })
            }
        
        # Check position availability in confirmed date range
        is_available, availability_error = check_positions_availability(
            listing_id=booking['listingId'],
            start_date=confirmed_start_date,
            end_date=confirmed_end_date,
            exclude_booking_id=booking_id
        )
        
        if not is_available:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Dates no longer available: {availability_error}',
                    'code': 4243
                })
            }
        
        # Update booking dates
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        try:
            bookings_table.update_item(
                Key={'bookingId': booking_id},
                UpdateExpression='SET startDate = :start, endDate = :end, updatedAt = :updated',
                ExpressionAttributeValues={
                    ':start': confirmed_start_date,
                    ':end': confirmed_end_date,
                    ':updated': now
                }
            )
            
            # Update booking object for response
            booking['startDate'] = confirmed_start_date
            booking['endDate'] = confirmed_end_date
            booking['updatedAt'] = now
            
            print(f"Booking {booking_id} dates confirmed and updated: {confirmed_start_date} to {confirmed_end_date}")
            
        except Exception as e:
            print(f"Error updating booking: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error confirming booking dates',
                    'code': 5070
                })
            }
        
        # Update chat and send confirmation message (non-blocking)
        try:
            update_chat_and_send_confirmation(
                booking_id=booking_id,
                new_start_date=confirmed_start_date,
                new_end_date=confirmed_end_date,
                job_title=listing.get('title', 'N/A'),
                booking_status=current_status
            )
        except Exception as e:
            print(f"Warning: Failed to update chat (non-critical): {str(e)}")
        
        # Convert Decimal for JSON response
        response_booking = json.loads(json.dumps(booking, cls=DecimalEncoder))
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Booking dates confirmed and updated successfully',
                'booking': response_booking,
                'code': 3075
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
                'error': 'Bad Request',
                'message': 'Invalid JSON in request body',
                'code': 4244
            })
        }
    
    except Exception as e:
        print(f"Error confirming booking dates: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': 'An error occurred while confirming booking dates',
                'code': 5071
            })
        }
