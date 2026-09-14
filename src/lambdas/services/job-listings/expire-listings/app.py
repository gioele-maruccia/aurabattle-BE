import json
import os
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Attr, Key

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])

def check_active_bookings(listing_id):
    """
    Check if a listing has any active bookings (pending or confirmed).
    
    Args:
        listing_id: The job listing ID to check
        
    Returns:
        list: List of active booking IDs, empty if none
    """
    try:
        # Query bookings using GSI listingId-startDate-index
        response = bookings_table.query(
            IndexName='listingId-startDate-index',
            KeyConditionExpression=Key('listingId').eq(listing_id),
            FilterExpression=Attr('status').is_in(['pending', 'confirmed'])
        )
        
        active_bookings = response.get('Items', [])
        booking_ids = [b['bookingId'] for b in active_bookings]
        
        if booking_ids:
            print(f"  Found {len(booking_ids)} active booking(s) for listing {listing_id}")
        
        return booking_ids
        
    except Exception as e:
        print(f"  Error checking bookings for listing {listing_id}: {str(e)}")
        return []

def expire_bookings(booking_ids, listing_id):
    """
    Expire all bookings associated with a listing.
    
    Args:
        booking_ids: List of booking IDs to expire
        listing_id: The job listing ID (for logging)
        
    Returns:
        tuple: (success_count, error_count)
    """
    success_count = 0
    error_count = 0
    
    for booking_id in booking_ids:
        try:
            bookings_table.update_item(
                Key={'bookingId': booking_id},
                UpdateExpression='SET #status = :expired_status, updatedAt = :updated_at, statusUpdatedAt = :status_updated_at, completedAt = :completed_at',
                ExpressionAttributeNames={
                    '#status': 'status'
                },
                ExpressionAttributeValues={
                    ':expired_status': 'completed',
                    ':updated_at': datetime.now(timezone.utc).isoformat(),
                    ':status_updated_at': datetime.now(timezone.utc).isoformat(),
                    ':completed_at': datetime.now(timezone.utc).isoformat(),
                    ':pending': 'pending',
                    ':confirmed': 'confirmed'
                },
                ConditionExpression='#status IN (:pending, :confirmed)'
            )
            success_count += 1
            print(f"  Completed booking: {booking_id}")
            
        except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            print(f"  Skipped booking {booking_id} - status already changed")
            
        except Exception as e:
            error_count += 1
            print(f"  Error completing booking {booking_id}: {str(e)}")
    
    return success_count, error_count

def lambda_handler(event, context):
    """
    Expire job listings that have reached or passed their end date.
    
    This function is triggered daily by EventBridge.
    It scans for all job listings with status 'published' or 'paused'.
    - If endDate < today (yesterday or before) OR endDate == today with NO active bookings: expire immediately
    - If endDate == today with active bookings: expire the day after (wait until tomorrow)
    
    When expiring a listing, also completes all active bookings (pending/confirmed).
    
    Returns:
        dict: Response with count of expired listings and bookings
    """
    
    try:
        # Get today's date in ISO format (YYYY-MM-DD)
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        print(f"Running expire-listings job for date: {today}")
        
        expired_count = 0
        skipped_count = 0
        error_count = 0
        bookings_completed = 0
        bookings_errors = 0
        
        # Scan for listings that need to be expired
        # We look for listings with status 'published' or 'paused' and endDate <= today
        scan_kwargs = {
            'FilterExpression': (
                Attr('endDate').lte(today) & 
                (Attr('status').eq('published') | Attr('status').eq('paused'))
            ),
            'ProjectionExpression': 'listingId, companyId, title, endDate, #status',
            'ExpressionAttributeNames': {
                '#status': 'status'
            }
        }
        
        # Handle pagination
        while True:
            response = job_listings_table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            print(f"Found {len(items)} listings to process in this batch")
            
            # Update each listing
            for listing in items:
                listing_id = listing['listingId']
                end_date = listing.get('endDate')
                
                try:
                    # Check if listing has active bookings
                    active_booking_ids = check_active_bookings(listing_id)
                    
                    # Determine if we should expire this listing
                    should_expire = False
                    
                    if end_date < today:
                        # endDate is in the past (yesterday or before) - expire regardless
                        should_expire = True
                        print(f"  Listing {listing_id}: endDate {end_date} is before today, expiring")
                    elif end_date == today:
                        if len(active_booking_ids) > 0:
                            # endDate is today with active bookings - wait until tomorrow
                            should_expire = False
                            skipped_count += 1
                            print(f"  Listing {listing_id}: endDate is today with {len(active_booking_ids)} active bookings, skipping (will expire tomorrow)")
                        else:
                            # endDate is today with no active bookings - expire now
                            should_expire = True
                            print(f"  Listing {listing_id}: endDate is today with no active bookings, expiring")
                    
                    if not should_expire:
                        continue
                    
                    # First, expire/complete all active bookings if any
                    if len(active_booking_ids) > 0:
                        print(f"  Completing {len(active_booking_ids)} booking(s) for listing {listing_id}")
                        b_success, b_errors = expire_bookings(active_booking_ids, listing_id)
                        bookings_completed += b_success
                        bookings_errors += b_errors
                    
                    # Now expire the listing
                    update_response = job_listings_table.update_item(
                        Key={'listingId': listing_id},
                        UpdateExpression='SET #status = :expired_status, updatedAt = :updated_at',
                        ExpressionAttributeNames={
                            '#status': 'status'
                        },
                        ExpressionAttributeValues={
                            ':expired_status': 'expired',
                            ':updated_at': datetime.now(timezone.utc).isoformat(),
                            ':old_status_1': 'published',
                            ':old_status_2': 'paused'
                        },
                        ConditionExpression='#status IN (:old_status_1, :old_status_2)',
                        ReturnValues='UPDATED_NEW'
                    )
                    
                    expired_count += 1
                    print(f"  ✓ Expired listing: {listing_id} (title: {listing.get('title', 'N/A')}, endDate: {end_date})")
                    
                except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
                    # Listing was already updated by another process or status changed
                    print(f"  Skipped listing {listing_id} - status no longer matches condition")
                    
                except Exception as e:
                    error_count += 1
                    print(f"  Error processing listing {listing_id}: {str(e)}")
            
            # Check if there are more items to scan
            if 'LastEvaluatedKey' not in response:
                break
            
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        # Prepare response
        result = {
            'date': today,
            'expired_count': expired_count,
            'skipped_count': skipped_count,
            'error_count': error_count,
            'bookings_completed': bookings_completed,
            'bookings_errors': bookings_errors,
            'status': 'success' if error_count == 0 and bookings_errors == 0 else 'partial_success'
        }
        
        print(f"Expire listings job completed: {json.dumps(result)}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
        
    except Exception as e:
        error_message = f"Error in expire-listings job: {str(e)}"
        print(error_message)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': error_message,
                'status': 'failed'
            })
        }
