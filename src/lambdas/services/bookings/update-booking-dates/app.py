"""
Update Booking Dates Handler

This Lambda function allows a worker to update dates for a PENDING booking.
Worker only - can update dates before company accepts the booking.

WORKFLOW:
- Validates the new dates
- Updates booking dates immediately in DB
- Sends informative message to chat about the change

Validations:
- Booking must be in 'pending' status
- Only the worker who created the booking can modify it
- New dates must be within job listing period
- Position availability must be checked for new date range

When successful:
- Updates booking with new dates
- Sends informative message to chat
- Returns updated booking data
"""

import json
import os
import sys
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

# Add chat shared layer to path (if available)
sys.path.append('/opt/python')

# Initialize DynamoDB and Lambda
dynamodb = boto3.resource('dynamodb')
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def check_date_overlap(start1, end1, start2, end2):
    """
    Check if two date ranges overlap
    
    Args:
        start1, end1: First date range (ISO strings or datetime objects)
        start2, end2: Second date range (ISO strings or datetime objects)
        
    Returns:
        bool: True if ranges overlap
    """
    # Convert to datetime if strings
    def to_datetime(date_val):
        if isinstance(date_val, datetime):
            # Ensure timezone aware
            if date_val.tzinfo is None:
                return date_val.replace(tzinfo=timezone.utc)
            return date_val
        # Parse string
        date_str = str(date_val)
        # Handle date-only format (YYYY-MM-DD) - add time component
        if len(date_str) == 10 and date_str.count('-') == 2:
            date_str = date_str + 'T00:00:00Z'
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt
    
    s1 = to_datetime(start1)
    e1 = to_datetime(end1)
    s2 = to_datetime(start2)
    e2 = to_datetime(end2)
    
    return s1 < e2 and s2 < e1


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
        # Query bookings by listing and date range
        response = bookings_table.query(
            IndexName='listingId-startDate-index',
            KeyConditionExpression=Key('listingId').eq(listing_id) & Key('startDate').lte(end_date),
            FilterExpression=Attr('endDate').gte(start_date) & 
                            Attr('status').is_in(['pending', 'confirmed']) &
                            Attr('bookingType').eq('booking')
        )
        
        bookings = response.get('Items', [])
        
        # Exclude the current booking being modified
        if exclude_booking_id:
            bookings = [b for b in bookings if b['bookingId'] != exclude_booking_id]
        
        return bookings
        
    except Exception as e:
        print(f"Error getting listing bookings: {str(e)}")
        return []


def check_positions_availability(listing_id, start_date, end_date, exclude_booking_id=None):
    """
    Check if positions are available in the new date range
    Also validates listing-specific booking requirements (minConsecutiveDays, minNoticeDays)
    
    Args:
        listing_id: Job listing ID
        start_date: Start date (ISO string)
        end_date: End date (ISO string)
        exclude_booking_id: Booking ID to exclude (current booking)
        
    Returns:
        tuple: (is_available, error_message, error_code)
    """
    try:
        # Get job listing
        listing_response = job_listings_table.get_item(Key={'listingId': listing_id})
        if 'Item' not in listing_response:
            return False, "Job listing not found", "LISTING_NOT_FOUND"
        
        listing = listing_response['Item']
        
        # Parse dates for validation
        today = datetime.now(timezone.utc).date()
        
        # Handle both date-only (YYYY-MM-DD) and datetime formats
        start_str = start_date
        end_str = end_date
        
        # Add time component if date-only format
        if len(start_str) == 10 and start_str.count('-') == 2:
            start_str += 'T00:00:00Z'
        if len(end_str) == 10 and end_str.count('-') == 2:
            end_str += 'T00:00:00Z'
        
        start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
        end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()
        
        # NEW: Check listing-specific minimum notice days
        min_notice_days = listing.get('minNoticeDays')
        if min_notice_days is not None and min_notice_days > 0:
            min_notice_days = int(float(min_notice_days))  # Handle Decimal type from DynamoDB
            min_allowed_date = today + timedelta(days=min_notice_days)
            if start_dt < min_allowed_date:
                return False, f"This job listing requires bookings to be made at least {min_notice_days} days in advance. Earliest available date: {min_allowed_date.isoformat()}", "BOOKING_MINIMUM_NOTICE_NOT_MET"
        
        # NEW: Check listing-specific minimum consecutive days
        min_consecutive_days = listing.get('minConsecutiveDays')
        if min_consecutive_days is not None and min_consecutive_days > 0:
            min_consecutive_days = int(float(min_consecutive_days))  # Handle Decimal type from DynamoDB
            booking_days = (end_dt - start_dt).days + 1  # +1 to include both start and end date
            if booking_days < min_consecutive_days:
                return False, f"This job listing requires a minimum booking period of {min_consecutive_days} consecutive days. Your booking is only {booking_days} days.", "BOOKING_MINIMUM_DURATION_NOT_MET"
        
        # Get total positions available
        total_positions = int(listing.get('positions', 1))
        
        # Get overlapping bookings in the new date range
        overlapping_bookings = get_listing_bookings_in_range(
            listing_id, 
            start_date, 
            end_date,
            exclude_booking_id
        )
        
        # Count how many positions are taken in overlapping period
        # NOTE: This is a simplified check - a full implementation would check day-by-day
        positions_taken = len(overlapping_bookings)
        
        if positions_taken >= total_positions:
            return False, f"No positions available in the new date range ({positions_taken}/{total_positions} positions taken)", "POSITIONS_NOT_AVAILABLE"
        
        return True, None, None
        
    except Exception as e:
        print(f"Error checking positions availability: {str(e)}")
        return False, f"Error checking availability: {str(e)}", "INTERNAL_ERROR"


def get_company_name(company_id):
    """
    Get company name from company ID
    
    Args:
        company_id: Company ID to lookup
        
    Returns:
        str: Company business name or 'Azienda' as fallback
    """
    try:
        companies_table = dynamodb.Table(os.environ.get('COMPANIES_TABLE_NAME', 'dev-Companies'))
        response = companies_table.query(
            IndexName='companyId-index',
            KeyConditionExpression=Key('companyId').eq(company_id),
            Limit=1
        )
        
        if response.get('Items'):
            company = response['Items'][0]
            return company.get('businessName', 'Azienda')
        
        print(f"Company not found for companyId {company_id}")
        return 'Azienda'
        
    except Exception as e:
        print(f"Error getting company name: {str(e)}")
        return 'Azienda'


def send_date_change_proposal_message(booking_id, proposed_start_date, proposed_end_date, job_title, company_name):
    """
    Send message to chat with proposed date changes
    
    Args:
        booking_id: ID of the booking
        proposed_start_date: Proposed start date (ISO string)
        proposed_end_date: Proposed end date (ISO string)
        job_title: Job title for message context
        company_name: Company name for message context
    """
    try:
        # Import chat modules (they're in the shared layer)
        from db_manager import ChatDBManager
        from models import Message, MessageType, SenderType, MessageState
        import uuid
        
        db_manager = ChatDBManager()
        
        # Get chat associated with this booking
        chat = db_manager.get_chat_by_booking(booking_id)
        
        if not chat:
            print(f"No chat found for booking {booking_id}, skipping chat message")
            return
        
        # Format dates for payload (dd/mm/yyyy)
        start_dt = datetime.fromisoformat(proposed_start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(proposed_end_date.replace('Z', '+00:00'))
        start_formatted = start_dt.strftime('%d/%m/%Y')
        end_formatted = end_dt.strftime('%d/%m/%Y')
        
        # Create payload with proposed dates
        payload = {
            'start': start_formatted,
            'end': end_formatted,
            'startDate': proposed_start_date,  # Keep ISO format for backend use
            'endDate': proposed_end_date
        }
        
        # Create message with COMPANY_ACCEPT_DATES type (requires action)
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        message_text = (
            f"📅 **Richiesta Modifica Date Booking**\n\n"
            f"Il worker ha richiesto una modifica delle date del booking.\n\n"
            f"📋 **Nuove date proposte:**\n"
            f"📅 **Inizio:** {start_formatted}\n"
            f"📅 **Fine:** {end_formatted}\n\n"
            f"🏢 **Azienda:** {company_name}\n"
            f"💼 **Posizione:** {job_title}\n\n"
            f"⚠️ **Prossimo Passo:** L'azienda potrà accettare o rifiutare la prenotazione sulla base delle nuove date proposte."
        )
        
        message = Message(
            chat_id=chat.chat_id,
            message_id=str(uuid.uuid4()),
            sender_id="beezey_system",
            sender_type=SenderType.BEEZEY,
            message_text=message_text,
            timestamp=now,
            state=MessageState.SENT,
            message_type=MessageType.COMPANY_ACCEPT_DATES,
            payload=payload
        )
        
        # Save message to chat
        db_manager.create_message(message)
        print(f"Date change proposal message sent to chat {chat.chat_id}")
        
        # Try to broadcast via WebSocket (best effort)
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
        print(f"Chat modules not available (layer not attached?): {str(e)}")
        print("Skipping chat message - this is expected if chat layer is not attached")
    except Exception as e:
        print(f"Error sending date change proposal message: {str(e)}")
        # Don't fail the entire request if chat message fails


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    PATCH /bookings/{bookingId}/dates
    
    Required fields in body:
    - startDate: New start date (ISO 8601)
    - endDate: New end date (ISO 8601)
    
    Authorization: Cognito JWT (worker only, must own the booking)
    """
    
    try:
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Check if user is in 'workers' group
        if 'workers' not in user_groups:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4023,
                    'error': 'Forbidden',
                    'message': 'Only worker users can update booking dates'
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
                    'code': 4016,
                    'error': 'Bad Request',
                    'message': f'Missing required fields: {", ".join(missing_fields)}'
                })
            }
        
        new_start_date = body['startDate']
        new_end_date = body['endDate']
        
        # Validate dates
        try:
            # Handle both date-only (YYYY-MM-DD) and datetime formats
            new_start_str = new_start_date
            new_end_str = new_end_date
            
            # Add time component if date-only format
            if len(new_start_str) == 10 and new_start_str.count('-') == 2:
                new_start_str += 'T00:00:00Z'
            if len(new_end_str) == 10 and new_end_str.count('-') == 2:
                new_end_str += 'T00:00:00Z'
            
            start_dt = datetime.fromisoformat(new_start_str.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(new_end_str.replace('Z', '+00:00'))
            
            if end_dt <= start_dt:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4018,
                        'error': 'Bad Request',
                        'message': 'End date must be after start date'
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
                    'code': 4017,
                    'error': 'Bad Request',
                    'message': 'Invalid date format. Use ISO 8601 (YYYY-MM-DD)'
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
                        'code': 4026,
                        'error': 'Not Found',
                        'message': 'Booking not found'
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
                        'code': 4022,
                        'error': 'Bad Request',
                        'message': 'Cannot update dates of non-booking items'
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
                    'code': 5007,
                    'error': 'Internal Server Error',
                    'message': 'Error fetching booking'
                })
            }
        
        # Verify user owns the booking
        if booking['workerId'] != user_id:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4024,
                    'error': 'Forbidden',
                    'message': 'You can only update your own bookings'
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
                    'code': 4019,
                    'error': 'Bad Request',
                    'message': f'Can only update dates of pending bookings. Current status: {current_status}'
                })
            }
        
        # ============================================
        # ENHANCED VALIDATION: Check for conflicts with other worker's bookings
        # Apply same business rules as create-booking
        # ============================================
        try:
            # Get all bookings for this specific listing (excluding current booking)
            # Query using workerId index, then filter by listingId
            existing_bookings = bookings_table.query(
                IndexName='workerId-startDate-index',
                KeyConditionExpression=Key('workerId').eq(user_id),
                FilterExpression=Attr('listingId').eq(booking['listingId']) & 
                                Attr('bookingType').eq('booking') &
                                Attr('bookingId').ne(booking_id)
            )
            
            # Check for date overlaps with existing bookings for same listing
            for existing_booking in existing_bookings.get('Items', []):
                existing_status = existing_booking.get('status')
                existing_start = existing_booking.get('startDate')
                existing_end = existing_booking.get('endDate')
                
                # Check if new dates overlap with existing booking
                if check_date_overlap(new_start_date, new_end_date, existing_start, existing_end):
                    # Cannot update if there's a PENDING booking in new date range
                    if existing_status == 'pending':
                        return {
                            'statusCode': 409,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'code': 4028,
                                'error': 'Conflict',
                                'message': f'You already have another pending booking for this job listing in the new dates ({existing_start} to {existing_end}). Cancel that booking first or choose different dates.',
                                'conflictingBookingId': existing_booking.get('bookingId'),
                                'conflictingStatus': 'pending',
                                'conflictingDates': {
                                    'startDate': existing_start,
                                    'endDate': existing_end
                                }
                            })
                        }
                    
                    # Cannot update to dates that overlap with REJECTED booking
                    if existing_status == 'rejected':
                        return {
                            'statusCode': 403,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'code': 4025,
                                'error': 'Forbidden',
                                'message': f'You cannot update to these dates ({new_start_date} to {new_end_date}) because you have a previously rejected booking in this date range ({existing_start} to {existing_end}). Choose different dates that do not overlap with the rejection.',
                                'conflictingBookingId': existing_booking.get('bookingId'),
                                'conflictingStatus': 'rejected',
                                'conflictingDates': {
                                    'startDate': existing_start,
                                    'endDate': existing_end
                                }
                            })
                        }
                    
                    # Cannot update to dates that overlap with CONFIRMED booking
                    if existing_status == 'confirmed':
                        return {
                            'statusCode': 409,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'code': 4029,
                                'error': 'Conflict',
                                'message': f'You already have a confirmed booking for this job listing in the new dates ({existing_start} to {existing_end}). You cannot have overlapping confirmed bookings.',
                                'conflictingBookingId': existing_booking.get('bookingId'),
                                'conflictingStatus': 'confirmed',
                                'conflictingDates': {
                                    'startDate': existing_start,
                                    'endDate': existing_end
                                }
                            })
                        }
                    
                    # CANCELLED bookings allow date change
                    if existing_status == 'cancelled':
                        print(f"Found cancelled booking {existing_booking.get('bookingId')} in new date range - allowing update")
                        continue
                    
                    # Any other status blocks update
                    if existing_status not in ['cancelled']:
                        return {
                            'statusCode': 409,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'code': 4031,
                                'error': 'Conflict',
                                'message': f'You have another booking with status "{existing_status}" in the new date range ({existing_start} to {existing_end}). Choose dates that do not conflict with existing bookings.',
                                'conflictingBookingId': existing_booking.get('bookingId'),
                                'conflictingStatus': existing_status,
                                'conflictingDates': {
                                    'startDate': existing_start,
                                    'endDate': existing_end
                                }
                            })
                        }
            
            # Check for confirmed bookings in OTHER listings during new date range
            all_worker_bookings = bookings_table.query(
                IndexName='workerId-startDate-index',
                KeyConditionExpression=Key('workerId').eq(user_id),
                FilterExpression=Attr('status').eq('confirmed') & 
                                Attr('bookingType').eq('booking') &
                                Attr('bookingId').ne(booking_id)
            )
            
            for other_booking in all_worker_bookings.get('Items', []):
                other_start = other_booking.get('startDate')
                other_end = other_booking.get('endDate')
                
                # Check if new dates overlap with confirmed booking in another listing
                if check_date_overlap(new_start_date, new_end_date, other_start, other_end):
                    return {
                        'statusCode': 409,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'code': 4030,
                            'error': 'Conflict',
                            'message': f'You cannot update to these dates because you already have a confirmed booking for another job listing during this period ({other_start} to {other_end}). You can only have one confirmed booking at a time.',
                            'conflictingBookingId': other_booking.get('bookingId'),
                            'conflictingListingId': other_booking.get('listingId'),
                            'conflictingStatus': 'confirmed',
                            'conflictingDates': {
                                'startDate': other_start,
                                'endDate': other_end
                            }
                        })
                    }
        
        except Exception as e:
            print(f"Error checking booking conflicts: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5006,
                    'error': 'Internal Server Error',
                    'message': 'Error validating booking date conflicts'
                })
            }
        
        # Get job listing to validate dates
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
                        'code': 4027,
                        'error': 'Not Found',
                        'message': 'Job listing not found'
                    })
                }
            
            listing = listing_response['Item']
            
        except Exception as e:
            print(f"Error fetching listing: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5008,
                    'error': 'Internal Server Error',
                    'message': 'Error fetching job listing'
                })
            }
        
        # Validate new dates are within listing period
        # Handle both date-only (YYYY-MM-DD) and datetime formats
        listing_start_str = listing['startDate']
        listing_end_str = listing['endDate']
        
        # Add time component if date-only format
        if len(listing_start_str) == 10:
            listing_start_str += 'T00:00:00Z'
        if len(listing_end_str) == 10:
            listing_end_str += 'T00:00:00Z'
            
        listing_start = datetime.fromisoformat(listing_start_str.replace('Z', '+00:00'))
        listing_end = datetime.fromisoformat(listing_end_str.replace('Z', '+00:00'))
        
        if start_dt < listing_start or end_dt > listing_end:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4020,
                    'error': 'Bad Request',
                    'message': f'New dates must be within job listing period ({listing["startDate"]} to {listing["endDate"]})'
                })
            }
        
        # Check position availability in new date range
        is_available, availability_error, error_code = check_positions_availability(
            listing_id=booking['listingId'],
            start_date=new_start_date,
            end_date=new_end_date,
            exclude_booking_id=booking_id
        )
        
        if not is_available:
            return {
                'statusCode': 409,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4021,
                    'error': error_code or 'Bad Request',
                    'message': availability_error
                })
            }
        
        # All validations passed - UPDATE booking dates in DB
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        bookings_table.update_item(
            Key={'bookingId': booking_id},
            UpdateExpression='SET startDate = :start, endDate = :end, updatedAt = :updated',
            ExpressionAttributeValues={
                ':start': new_start_date,
                ':end': new_end_date,
                ':updated': now
            }
        )
        
        print(f"Booking {booking_id} dates updated: {new_start_date} to {new_end_date}")
        
        # Send informative message to chat about date change
        try:
            # Get company name from listing companyId
            company_name = get_company_name(listing.get('companyId', ''))
            
            send_date_change_proposal_message(
                booking_id=booking_id,
                proposed_start_date=new_start_date,
                proposed_end_date=new_end_date,
                job_title=listing.get('title', 'N/A'),
                company_name=company_name
            )
        except Exception as e:
            # Log but don't fail if chat message fails
            print(f"Warning: Failed to send date change message (non-critical): {str(e)}")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 3002,
                'message': 'Booking dates updated successfully',
                'booking': {
                    'bookingId': booking_id,
                    'startDate': new_start_date,
                    'endDate': new_end_date,
                    'updatedAt': now
                }
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
                'code': 4016,
                'error': 'Bad Request',
                'message': 'Invalid JSON in request body'
            })
        }
    
    except Exception as e:
        print(f"Error updating booking dates: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 5009,
                'error': 'Internal Server Error',
                'message': 'An error occurred while updating booking dates'
            })
        }
