"""
Check Availability Handler - FIXED VERSION

This Lambda function checks availability for a job listing.
Returns available slots considering:
- Confirmed bookings
- Blackout periods
- Position limits

Public endpoint - no authentication required.

FIXES:
1. Improved date parsing to handle both date and datetime formats
2. Better query logic to catch all overlapping bookings
3. Added debug logging
4. Fixed timezone handling
"""

import json
import os
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

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


def parse_date_safe(date_string):
    """
    Safely parse a date string to a date object.
    Handles both ISO date (YYYY-MM-DD) and ISO datetime (YYYY-MM-DDTHH:MM:SSZ) formats.
    
    Args:
        date_string: Date string in ISO format
        
    Returns:
        date: Python date object
    """
    try:
        # Remove 'Z' and handle timezone
        clean_string = date_string.replace('Z', '+00:00')
        
        # Parse to datetime first
        dt = datetime.fromisoformat(clean_string)
        
        # Return just the date part
        return dt.date()
    except Exception as e:
        print(f"Error parsing date '{date_string}': {str(e)}")
        # Fallback: try parsing as date only
        try:
            return datetime.strptime(date_string.split('T')[0], '%Y-%m-%d').date()
        except:
            raise ValueError(f"Cannot parse date: {date_string}")


def get_date_range_days(start_date, end_date):
    """
    Generate list of dates between start and end (inclusive)
    
    Args:
        start_date: Start date string (ISO format)
        end_date: End date string (ISO format)
        
    Returns:
        list: List of date strings in YYYY-MM-DD format
    """
    start = parse_date_safe(start_date)
    end = parse_date_safe(end_date)
    
    dates = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    
    return dates


def normalize_date_for_storage(date_string):
    """
    Normalize a date string to YYYY-MM-DD format for consistent storage/comparison.
    
    Args:
        date_string: Date string in ISO format (date or datetime)
        
    Returns:
        str: Normalized date string in YYYY-MM-DD format
    """
    return parse_date_safe(date_string).isoformat()


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /bookings/availability/{listingId}?startDate=2025-06-01&endDate=2025-06-30
    
    Query Parameters:
    - startDate: Start date to check (ISO 8601) - optional, defaults to listing start
    - endDate: End date to check (ISO 8601) - optional, defaults to listing end
    
    Returns:
        200: Availability information
        404: Listing not found
        500: Internal server error
    """
    
    try:
        # Get listing ID from path
        listing_id = event['pathParameters']['listingId']
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        query_start = params.get('startDate')
        query_end = params.get('endDate')
        
        print(f"Check availability for listing: {listing_id}")
        
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
                    'error': 'Internal Server Error',
                    'message': 'Error fetching job listing'
                })
            }
        
        # Use listing dates if not provided in query
        # Normalize to YYYY-MM-DD format
        start_date = normalize_date_for_storage(query_start or listing['startDate'])
        end_date = normalize_date_for_storage(query_end or listing['endDate'])
        
        print(f"Date range: {start_date} to {end_date}")
        
        # Validate dates
        try:
            start_dt = parse_date_safe(start_date)
            end_dt = parse_date_safe(end_date)
            
            if end_dt < start_dt:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'End date must be on or after start date'
                    })
                }
        except ValueError as e:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Invalid date format: {str(e)}'
                })
            }
        
        # Get all bookings and blackouts for this listing
        # IMPORTANT: We need to fetch ALL bookings that could possibly overlap with our date range
        # This includes bookings that:
        # 1. Start before our range but end during/after it
        # 2. Start during our range
        # 3. Start during our range and end after it
        #
        # The query uses listingId-startDate-index, so we can efficiently get all bookings
        # that start at or before our end_date, then filter for those that end at or after start_date
        
        try:
            print(f"Querying bookings with listingId={listing_id}, startDate <= {end_date}")
            
            response = bookings_table.query(
                IndexName='listingId-startDate-index',
                KeyConditionExpression=Key('listingId').eq(listing_id) & Key('startDate').lte(end_date),
                FilterExpression=Attr('endDate').gte(start_date)
            )
            
            all_items = response.get('Items', [])
            print(f"Found {len(all_items)} total items (bookings + blackouts)")
            
            # Separate bookings and blackouts
            # Only count 'confirmed' and 'pending' bookings (NOT 'cancelled', 'rejected', etc.)
            confirmed_bookings = [
                item for item in all_items 
                if item.get('bookingType') == 'booking' and item.get('status') in ['confirmed', 'pending']
            ]
            
            blackout_periods = [
                item for item in all_items 
                if item.get('bookingType') == 'blackout'
            ]
            
            print(f"Confirmed/Pending bookings: {len(confirmed_bookings)}")
            print(f"Blackout periods: {len(blackout_periods)}")
            
            # Debug: log booking details
            for booking in confirmed_bookings:
                print(f"  Booking {booking['bookingId']}: {booking['startDate']} to {booking['endDate']} (status: {booking.get('status')})")
            
        except Exception as e:
            print(f"Error fetching bookings: {str(e)}")
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
                    'message': 'Error fetching bookings'
                })
            }
        
        # Calculate availability
        total_positions = int(listing.get('positions', 1))
        
        # Build day-by-day availability
        all_days = get_date_range_days(start_date, end_date)
        availability_calendar = {}
        
        print(f"Building calendar for {len(all_days)} days")
        
        for day in all_days:
            day_date = parse_date_safe(day)
            
            # Check if day is in blackout
            is_blackout = False
            blackout_reason = None
            
            for blackout in blackout_periods:
                blackout_start = parse_date_safe(blackout['startDate'])
                blackout_end = parse_date_safe(blackout['endDate'])
                
                if blackout_start <= day_date <= blackout_end:
                    is_blackout = True
                    blackout_reason = blackout.get('reason', 'Unavailable')
                    print(f"  {day}: BLACKOUT ({blackout_reason})")
                    break
            
            if is_blackout:
                availability_calendar[day] = {
                    'available': False,
                    'reason': 'blackout',
                    'blackoutReason': blackout_reason,
                    'positionsAvailable': 0,
                    'positionsTotal': total_positions
                }
                continue
            
            # Count bookings on this day
            bookings_on_day = 0
            booking_ids_on_day = []  # For debug
            
            for booking in confirmed_bookings:
                booking_start = parse_date_safe(booking['startDate'])
                booking_end = parse_date_safe(booking['endDate'])
                
                # Check if booking overlaps with this day
                if booking_start <= day_date <= booking_end:
                    bookings_on_day += 1
                    booking_ids_on_day.append(booking['bookingId'][:8])  # Short ID for debug
            
            positions_available = total_positions - bookings_on_day
            
            # Debug logging for days with bookings
            if bookings_on_day > 0:
                print(f"  {day}: {bookings_on_day} bookings ({', '.join(booking_ids_on_day)}), {positions_available}/{total_positions} available")
            
            availability_calendar[day] = {
                'available': positions_available > 0,
                'reason': 'available' if positions_available > 0 else 'fully_booked',
                'positionsAvailable': positions_available,
                'positionsTotal': total_positions,
                'currentBookings': bookings_on_day
            }
        
        # Calculate summary
        available_days = sum(1 for day in availability_calendar.values() if day['available'])
        blackout_days = sum(1 for day in availability_calendar.values() if day.get('reason') == 'blackout')
        fully_booked_days = sum(1 for day in availability_calendar.values() if day.get('reason') == 'fully_booked')
        
        # Calculate effective availability in this range
        days_without_blackout = len(all_days) - blackout_days
        total_capacity_in_range = days_without_blackout * total_positions
        
        # Count total booking-days in this range (how many position-days are occupied)
        total_booking_days = sum(
            day_info['currentBookings'] 
            for day_info in availability_calendar.values() 
            if day_info.get('reason') != 'blackout'
        )
        
        available_capacity = total_capacity_in_range - total_booking_days
        
        print(f"Summary: {available_days} available, {blackout_days} blackout, {fully_booked_days} fully booked")
        print(f"Capacity: {total_capacity_in_range} total, {total_booking_days} booked, {available_capacity} free")
        
        response_body = {
            'listingId': listing_id,
            'period': {
                'startDate': start_date,
                'endDate': end_date,
                'totalDays': len(all_days)
            },
            'positions': {
                'total': total_positions,
                'globalFilled': int(listing.get('positionsFilled', 0)),  # Global confirmed positions
                'globalAvailable': total_positions - int(listing.get('positionsFilled', 0)),
                'inRangeCapacity': {
                    'totalSlots': total_capacity_in_range,  # Days without blackout * positions
                    'bookedSlots': total_booking_days,      # How many position-days are booked
                    'availableSlots': available_capacity,   # Free position-days
                    'daysWithoutBlackout': days_without_blackout,
                    'daysWithBlackout': blackout_days
                }
            },
            'summary': {
                'availableDays': available_days,
                'blackoutDays': blackout_days,
                'fullyBookedDays': fully_booked_days
            },
            'calendar': availability_calendar,
            'blackoutPeriods': [
                {
                    'startDate': bp['startDate'],
                    'endDate': bp['endDate'],
                    'reason': bp.get('reason', 'Unavailable')
                }
                for bp in blackout_periods
            ],
            'debug': {
                'totalBookingsFound': len(confirmed_bookings),
                'totalBlackoutsFound': len(blackout_periods),
                'queryRange': {
                    'start': start_date,
                    'end': end_date
                }
            }
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=300'  # Cache for 5 minutes
            },
            'body': json.dumps(response_body, cls=DecimalEncoder)
        }
        
    except Exception as e:
        print(f"Error checking availability: {str(e)}")
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
                'message': 'An error occurred while checking availability',
                'details': str(e)
            })
        }