"""
Create Booking Handler

This Lambda function creates a new booking/application for a job listing.
Validates:
- Listing availability
- Date overlap with existing bookings
- Blackout periods
- Position limits

Worker users only.
"""

import json
import os
import uuid
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

# Initialize DynamoDB and Lambda
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])
user_profiles_table = dynamodb.Table(os.environ.get('USER_PROFILES_TABLE_NAME', 'dev-UserProfiles'))

# Configuration
MINIMUM_ADVANCE_BOOKING_DAYS = int(os.environ.get('MINIMUM_ADVANCE_BOOKING_DAYS', 5))
CREATE_CHAT_FUNCTION_NAME = os.environ.get('CREATE_CHAT_FUNCTION_NAME', 'dev-chat-create')


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
        start1, end1: First date range (ISO strings)
        start2, end2: Second date range (ISO strings)
        
    Returns:
        bool: True if ranges overlap
    """
    # Helper to convert date strings to datetime
    def to_datetime(date_str):
        # Add time component if date-only format (YYYY-MM-DD)
        if len(date_str) == 10 and date_str.count('-') == 2:
            date_str += 'T00:00:00Z'
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    
    s1 = to_datetime(start1)
    e1 = to_datetime(end1)
    s2 = to_datetime(start2)
    e2 = to_datetime(end2)
    
    return s1 < e2 and s2 < e1


def to_utc_datetime(date_str):
    """
    Normalize ISO date/datetime strings to timezone-aware UTC datetimes.
    """
    value = date_str
    if len(value) == 10 and value.count('-') == 2:
        value += 'T00:00:00Z'
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_listing_compensation(listing):
    """
    Derive a numeric compensation value from listing fields.
    """
    salary = listing.get('salary')
    if salary is not None:
        try:
            return float(salary)
        except (TypeError, ValueError):
            pass

    contract = listing.get('contract') or {}
    calculation = contract.get('calculation') or {}
    base_pay = calculation.get('grossBasePay')
    try:
        base_pay = float(base_pay) if base_pay is not None else 0.0
    except (TypeError, ValueError):
        base_pay = 0.0

    superminimo = (contract.get('superminimo') or {}).get('amount', 0)
    try:
        superminimo = float(superminimo)
    except (TypeError, ValueError):
        superminimo = 0.0

    return base_pay + superminimo


def get_worker_display_name(user_id, claims=None):
    """
    Resolve worker display name from UserProfiles.
    """
    profile_item = None
    try:
        response = user_profiles_table.get_item(Key={'user_id': user_id})
        profile_item = response.get('Item')
    except Exception as e:
        print(f"Warning: Could not fetch worker profile by user_id: {str(e)}")

    if not profile_item:
        try:
            response = user_profiles_table.get_item(Key={'userId': user_id})
            profile_item = response.get('Item')
        except Exception as e:
            print(f"Warning: Could not fetch worker profile by userId: {str(e)}")

    if not profile_item:
        profile_item = {}

    profile_data = profile_item.get('profile', {})
    first_name = (
        profile_data.get('given_name')
        or profile_item.get('firstName')
        or profile_item.get('given_name')
        or ''
    )
    last_name = (
        profile_data.get('family_name')
        or profile_item.get('lastName')
        or profile_item.get('family_name')
        or ''
    )
    if (not first_name and not last_name) and claims:
        first_name = claims.get('given_name', '')
        last_name = claims.get('family_name', '')
        if not first_name and not last_name:
            full_name = claims.get('name') or ''
            if full_name:
                parts = full_name.split()
                first_name = parts[0] if parts else ''
                last_name = parts[-1] if len(parts) > 1 else ''
        if not first_name and not last_name:
            email = claims.get('email', '')
            if email and '@' in email:
                first_name = email.split('@', 1)[0]
    first_name = first_name.strip()
    last_name = last_name.strip()
    display_name = f"{first_name} {last_name}".strip()
    return display_name or 'Worker'


def get_listing_bookings(listing_id, start_date, end_date):
    """
    Get all confirmed/pending bookings and blackouts for a listing in date range
    
    Args:
        listing_id: Job listing ID
        start_date: Start date (ISO string)
        end_date: End date (ISO string)
        
    Returns:
        tuple: (bookings_list, blackouts_list)
    """
    try:
        # Query bookings by listing and date range
        response = bookings_table.query(
            IndexName='listingId-startDate-index',
            KeyConditionExpression=Key('listingId').eq(listing_id) & Key('startDate').lte(end_date),
            FilterExpression=Attr('endDate').gte(start_date) & Attr('status').is_in(['pending', 'confirmed'])
        )
        
        bookings = [b for b in response.get('Items', []) if b.get('bookingType') == 'booking']
        blackouts = [b for b in response.get('Items', []) if b.get('bookingType') == 'blackout']
        
        return bookings, blackouts
        
    except Exception as e:
        print(f"Error getting listing bookings: {str(e)}")
        return [], []


def validate_booking_dates(listing, start_date, end_date):
    """
    Validate booking dates against existing bookings, blackouts, and listing requirements
    Also checks minimum advance booking requirement and listing-specific constraints
    
    Args:
        listing: Job listing object with requirements (minNoticeDays, minConsecutiveDays)
        start_date: Requested start date (ISO string)
        end_date: Requested end date (ISO string)
        
    Returns:
        tuple: (is_valid, error_message, error_code_string, error_code_numeric)
    """
    listing_id = listing['listingId']
    
    # Parse dates
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
    
    # NEW: Check listing-specific minimum notice days (overrides global setting if present)
    min_notice_days = listing.get('minNoticeDays')
    if min_notice_days is not None and min_notice_days > 0:
        min_notice_days = int(float(min_notice_days))  # Handle Decimal type from DynamoDB
        min_allowed_date = today + timedelta(days=min_notice_days)
        if start_dt < min_allowed_date:
            return False, f"This job listing requires bookings to be made at least {min_notice_days} days in advance. Earliest available date: {min_allowed_date.isoformat()}", "BOOKING_MINIMUM_NOTICE_NOT_MET", 4006
    else:
        # Fallback to global minimum advance booking requirement
        min_allowed_date = today + timedelta(days=MINIMUM_ADVANCE_BOOKING_DAYS)
        if start_dt < min_allowed_date:
            return False, f"Bookings must be made at least {MINIMUM_ADVANCE_BOOKING_DAYS} days in advance. Earliest available date: {min_allowed_date.isoformat()}", "BOOKING_MINIMUM_NOTICE_NOT_MET", 4006
    
    # NEW: Check listing-specific minimum consecutive days
    min_consecutive_days = listing.get('minConsecutiveDays')
    if min_consecutive_days is not None and min_consecutive_days > 0:
        min_consecutive_days = int(float(min_consecutive_days))  # Handle Decimal type from DynamoDB
        booking_days = (end_dt - start_dt).days + 1  # +1 to include both start and end date
        if booking_days < min_consecutive_days:
            return False, f"This job listing requires a minimum booking period of {min_consecutive_days} consecutive days. Your booking is only {booking_days} days.", "BOOKING_MINIMUM_DURATION_NOT_MET", 4006
    
    # Get existing bookings and blackouts
    bookings, blackouts = get_listing_bookings(listing_id, start_date, end_date)
    
    # Check against blackout periods
    for blackout in blackouts:
        if check_date_overlap(start_date, end_date, blackout['startDate'], blackout['endDate']):
            return False, f"Date range overlaps with blackout period ({blackout['startDate']} to {blackout['endDate']})", "BOOKING_BLACKOUT_CONFLICT", 4007
    
    # Check against confirmed bookings (if all positions are filled for overlapping dates)
    # Note: This is a simplified check - full validation would check day-by-day availability
    overlapping_bookings = [b for b in bookings if check_date_overlap(start_date, end_date, b['startDate'], b['endDate'])]
    
    if overlapping_bookings:
        # This is handled at listing level by checking positionsFilled vs positions
        # Here we just inform that there are existing bookings
        pass
    
    # Return success
    return True, None, None, None


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    POST /bookings
    
    Required fields in body:
    - listingId: Job listing to book
    - startDate: Booking start date (ISO 8601)
    - endDate: Booking end date (ISO 8601)
    - message: Optional message to company
    
    Authorization: Cognito JWT (worker user only)
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
                    'code': 4009,
                    'error': 'Forbidden',
                    'message': 'Only worker users can create bookings'
                })
            }
        
        # Parse request body
        body = json.loads(event['body'])
        
        # Validate required fields
        required_fields = ['listingId', 'startDate', 'endDate']
        missing_fields = [field for field in required_fields if field not in body]
        
        if missing_fields:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4001,
                    'error': 'Bad Request',
                    'message': f'Missing required fields: {", ".join(missing_fields)}'
                })
            }
        
        listing_id = body['listingId']
        start_date = body['startDate']
        end_date = body['endDate']
        message = body.get('message', '')
        
        # Validate dates
        try:
            # Handle both date-only (YYYY-MM-DD) and datetime formats
            start_str = start_date
            end_str = end_date
            
            # Add time component if date-only format
            if len(start_str) == 10 and start_str.count('-') == 2:
                start_str += 'T00:00:00Z'
            if len(end_str) == 10 and end_str.count('-') == 2:
                end_str += 'T00:00:00Z'
            
            start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            
            if end_dt <= start_dt:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4002,
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
                    'code': 4003,
                    'error': 'Bad Request',
                    'message': 'Invalid date format. Use ISO 8601 (YYYY-MM-DD)'
                })
            }
        
        # Get job listing
        try:
            listing_response = job_listings_table.get_item(Key={'listingId': listing_id})
            if 'Item' not in listing_response:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4011,
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
                    'code': 5004,
                    'error': 'Internal Server Error',
                    'message': 'Error fetching job listing'
                })
            }
        
        # Validate listing status
        if listing.get('status') != 'published':
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4004,
                    'error': 'Bad Request',
                    'message': 'Job listing is not published'
                })
            }
        
        # Validate dates are within listing period
        listing_start = datetime.fromisoformat(listing['startDate'].replace('Z', '+00:00')).date()
        listing_end = datetime.fromisoformat(listing['endDate'].replace('Z', '+00:00')).date()
        
        if start_dt.date() < listing_start or end_dt.date() > listing_end:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4005,
                    'error': 'Bad Request',
                    'message': f'Booking dates must be within listing period ({listing["startDate"]} to {listing["endDate"]})'
                })
            }
        
        # Validate against blackouts, existing bookings, and listing-specific requirements
        is_valid, error_msg, error_code, numeric_code = validate_booking_dates(listing, start_date, end_date)
        if not is_valid:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': numeric_code,
                    'error': error_code or 'Bad Request',
                    'message': error_msg
                })
            }
        
        # Check if positions are available for these SPECIFIC dates
        # Only count bookings that overlap with the requested date range
        positions_available = int(listing.get('positions', 1))
        
        try:
            # Query bookings for this listing
            response = bookings_table.query(
                IndexName='listingId-startDate-index',
                KeyConditionExpression='listingId = :listing_id',
                ExpressionAttributeValues={
                    ':listing_id': listing_id
                }
            )
            
            existing_bookings = response.get('Items', [])

            start_dt = start_dt if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc)
            end_dt = end_dt if end_dt.tzinfo else end_dt.replace(tzinfo=timezone.utc)
            
            # Count bookings that overlap with requested dates.
            # Only CONFIRMED/COMPLETED/NO_SHOW bookings consume a position slot.
            # PENDING bookings do NOT block new applications — the slot is only
            # considered taken once the company actually accepts the worker.
            overlapping_count = 0
            for booking in existing_bookings:
                booking_status = booking.get('status')
                if booking_status in ['confirmed', 'completed', 'no_show']:
                    booking_start = to_utc_datetime(booking['startDate'])
                    booking_end = to_utc_datetime(booking['endDate'])
                    
                    # Check if dates overlap: s1 < e2 AND s2 < e1
                    if start_dt < booking_end and booking_start < end_dt:
                        overlapping_count += 1
            
            # If all positions are filled for these dates, reject
            if overlapping_count >= positions_available:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4008,
                        'error': 'Bad Request',
                        'message': f'All {positions_available} positions for this listing are filled for the requested dates ({start_date} to {end_date}). Currently {overlapping_count} bookings scheduled.'
                    })
                }
        except Exception as e:
            print(f'Error checking position availability: {str(e)}')
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5003,
                    'error': 'Internal Server Error',
                    'message': 'Error checking position availability'
                })
            }
        
        # ============================================
        # NEW BOOKING VALIDATION LOGIC
        # ============================================
        # Check worker's existing bookings for this listing in the requested date range
        # Rules:
        # 1. Worker can book same job listing in different dates without constraints
        # 2. If worker has PENDING booking for same listing in overlapping dates -> ERROR
        # 3. If worker has REJECTED booking for same listing in overlapping dates -> ALLOWED (can rebook after rejection)
        # 4. If worker has any booking (except CANCELLED or REJECTED) for same listing in overlapping dates -> ERROR
        # 5. Only CANCELLED and REJECTED bookings allow rebooking in same date range
        # 6. Worker can have multiple bookings for different listings in same date range (only 1 CONFIRMED at a time)
        try:
            # Get all worker's bookings for this specific listing
            existing_bookings = bookings_table.query(
                IndexName='workerId-startDate-index',
                KeyConditionExpression=Key('workerId').eq(user_id),
                FilterExpression=Attr('listingId').eq(listing_id) & Attr('bookingType').eq('booking')
            )
            
            # Check for date overlaps with existing bookings
            for existing_booking in existing_bookings.get('Items', []):
                existing_status = existing_booking.get('status')
                existing_start = existing_booking.get('startDate')
                existing_end = existing_booking.get('endDate')
                
                # Check if dates overlap
                if check_date_overlap(start_date, end_date, existing_start, existing_end):
                    # RULE 2: Cannot book if there's a PENDING booking in same date range
                    if existing_status == 'pending':
                        return {
                            'statusCode': 409,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'code': 4012,
                                'error': 'Conflict',
                                'message': f'You already have a pending booking for this job listing in the requested dates ({existing_start} to {existing_end}). Please wait for the company\'s response or cancel the existing booking before creating a new one.',
                                'conflictingBookingId': existing_booking.get('bookingId'),
                                'conflictingStatus': 'pending',
                                'conflictingDates': {
                                    'startDate': existing_start,
                                    'endDate': existing_end
                                }
                            })
                        }
                    
                    # RULE 3: REJECTED bookings allow rebooking - no error, proceed
                    if existing_status == 'rejected':
                        print(f"Found rejected booking {existing_booking.get('bookingId')} in overlapping dates - allowing rebook")
                        continue

                    # RULE 4: Cannot book if there's a CONFIRMED booking in same date range
                    if existing_status == 'confirmed':
                        return {
                            'statusCode': 409,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'code': 4013,
                                'error': 'Conflict',
                                'message': f'You already have a confirmed booking for this job listing in the requested dates ({existing_start} to {existing_end}). You cannot create multiple confirmed bookings for the same period.',
                                'conflictingBookingId': existing_booking.get('bookingId'),
                                'conflictingStatus': 'confirmed',
                                'conflictingDates': {
                                    'startDate': existing_start,
                                    'endDate': existing_end
                                }
                            })
                        }
                    
                    # RULE 5: CANCELLED bookings allow rebooking - no error, proceed
                    # If status is 'cancelled', we allow creating a new booking
                    if existing_status == 'cancelled':
                        print(f"Found cancelled booking {existing_booking.get('bookingId')} in overlapping dates - allowing rebook")
                        continue
                    
                    # Any other status (completed, no_show, etc.) - block rebooking
                    if existing_status not in ['cancelled', 'rejected']:
                        return {
                            'statusCode': 409,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'code': 4015,
                                'error': 'Conflict',
                                'message': f'You already have a booking with status "{existing_status}" for this job listing in the requested dates ({existing_start} to {existing_end}). You can only rebook if the previous booking was cancelled.',
                                'conflictingBookingId': existing_booking.get('bookingId'),
                                'conflictingStatus': existing_status,
                                'conflictingDates': {
                                    'startDate': existing_start,
                                    'endDate': existing_end
                                }
                            })
                        }
            
            # RULE 6: Check for confirmed bookings in other listings during the same date range
            # A worker can only have ONE confirmed booking across all listings at any given time
            all_worker_bookings = bookings_table.query(
                IndexName='workerId-startDate-index',
                KeyConditionExpression=Key('workerId').eq(user_id),
                FilterExpression=Attr('status').eq('confirmed') & Attr('bookingType').eq('booking')
            )
            
            for other_booking in all_worker_bookings.get('Items', []):
                other_start = other_booking.get('startDate')
                other_end = other_booking.get('endDate')
                
                # Check if dates overlap with another confirmed booking
                if check_date_overlap(start_date, end_date, other_start, other_end):
                    return {
                        'statusCode': 409,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'code': 4014,
                            'error': 'Conflict',
                            'message': f'You cannot create a new booking because you already have a confirmed booking for another job listing during these dates ({other_start} to {other_end}). You can only have one confirmed booking at a time.',
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
            print(f"Error checking existing bookings: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5003,
                    'error': 'Internal Server Error',
                    'message': 'Error checking existing bookings'
                })
            }
        
        # Generate IDs and timestamps
        booking_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # Get worker profile for metadata
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        worker_name = get_worker_display_name(user_id, claims=claims)
        
        # Get company name for metadata
        company_name = ''
        try:
            company_response = companies_table.query(
                IndexName='companyId-index',
                KeyConditionExpression=Key('companyId').eq(listing['companyId']),
                Limit=1
            )
            if company_response.get('Items'):
                company = company_response['Items'][0]
                company_name = company.get('businessName', '')
        except Exception as e:
            print(f"Warning: Could not fetch company name for metadata: {str(e)}")
        
        # Create booking item
        booking = {
            'bookingId': booking_id,
            'bookingType': 'booking',  # 'booking' or 'blackout'
            'listingId': listing_id,
            'companyId': listing['companyId'],
            'workerId': user_id,
            'startDate': start_date,
            'endDate': end_date,
            'status': 'pending',  # pending, confirmed, rejected, cancelled
            'message': message,
            'preferredShift': body.get('preferredShift'),
            'createdAt': now,
            'updatedAt': now,
            # Metadata cache
            'metadata': {
                'listingTitle': listing.get('title', ''),
                'listingCategory': listing.get('category', ''),
                'companyName': company_name,
                'workerName': worker_name
            }
        }
        
        # Save to DynamoDB
        bookings_table.put_item(Item=booking)
        
        print(f"Booking created: {booking_id} for listing {listing_id}")
        
        # ============================================
        # INVOKE CREATE-CHAT LAMBDA (SYNCHRONOUS)
        # ============================================
        chat_id = None
        chat_created = False
        
        try:
            # Get company info for chat
            # Query using companyId-index to find the company record
            company_response = companies_table.query(
                IndexName='companyId-index',
                KeyConditionExpression=Key('companyId').eq(listing['companyId']),
                Limit=1
            )
            
            company_user_id = None
            company_name = 'Azienda'
            
            if company_response.get('Items'):
                company = company_response['Items'][0]
                company_user_id = company.get('userId')  # Get the actual userId (Cognito sub)
                company_name = company.get('businessName', 'Azienda')
            else:
                print(f"Warning: Company not found for companyId {listing['companyId']}")
            
            # Prepare payload for create-chat Lambda
            compensation_value = get_listing_compensation(listing)
            compensation_text = f"{compensation_value:.2f}".rstrip('0').rstrip('.')
            if compensation_text == "":
                compensation_text = "0"

            chat_payload = {
                'body': json.dumps({
                    'booking_id': booking_id,
                    'worker_id': user_id,
                    'company_representative_id': company_user_id,  # Use the actual userId (Cognito sub)
                    'booking_details': {
                        'job_title': listing.get('title', 'N/A'),
                        'company_name': company_name,
                        'worker_name': worker_name,
                        'listing_id': listing_id,
                        'start_date': start_date,
                        'end_date': end_date,
                        'compensation': compensation_text,
                        'booking_status': 'pending'  # Initial booking status
                    }
                })
            }
            
            # Invoke create-chat Lambda SYNCHRONOUSLY to get chatId
            response = lambda_client.invoke(
                FunctionName=CREATE_CHAT_FUNCTION_NAME,
                InvocationType='RequestResponse',  # Sync invocation
                Payload=json.dumps(chat_payload)
            )
            
            # Parse response
            response_payload = json.loads(response['Payload'].read())
            
            if response_payload.get('statusCode') == 201:
                chat_response = json.loads(response_payload['body'])
                chat_id = chat_response.get('chat', {}).get('chatId')  # Fixed: camelCase
                chat_created = True
                print(f"Chat created successfully: {chat_id}")
            elif response_payload.get('statusCode') == 409:
                # Chat già esiste per questo booking
                chat_response = json.loads(response_payload['body'])
                chat_id = chat_response.get('chat', {}).get('chatId')  # Fixed: camelCase
                chat_created = True
                print(f"Chat already exists: {chat_id}")
            else:
                print(f"Create-chat returned non-success: {response_payload.get('statusCode')}")
            
        except Exception as e:
            # Non-blocking: se la chat fallisce, il booking è comunque creato
            print(f"Warning: Failed to create chat: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Convert Decimal back to float for JSON response
        response_booking = json.loads(json.dumps(booking, cls=DecimalEncoder))
        
        # Enrich booking with listing and company details for response
        # ListingSummary
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
        
        # CompanySummary - Get company info
        try:
            company_response = companies_table.query(
                IndexName='companyId-index',
                KeyConditionExpression=Key('companyId').eq(listing['companyId']),
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
            else:
                # Fallback if company not found
                response_booking['company'] = {
                    'companyId': listing['companyId'],
                    'businessName': listing.get('companyName', 'Unknown Company'),
                    'logoUrl': '',
                    'rating': 0.0
                }
        except Exception as e:
            print(f"Error fetching company details: {str(e)}")
            response_booking['company'] = {
                'companyId': listing['companyId'],
                'businessName': 'Unknown Company',
                'logoUrl': '',
                'rating': 0.0
            }
        
        # Build response with chatId if available
        response_body = {
            'code': 3001,
            'message': 'Booking created successfully',
            'booking': response_booking
        }
        
        if chat_id:
            response_body['chatId'] = chat_id
            response_body['chatCreated'] = chat_created
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_body)
        }
        
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 4001,
                'error': 'Bad Request',
                'message': 'Invalid JSON in request body'
            })
        }
    
    except Exception as e:
        print(f"Error creating booking: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 5005,
                'error': 'Internal Server Error',
                'message': 'An error occurred while creating the booking'
            })
        }