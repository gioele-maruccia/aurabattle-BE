import json
import os
from datetime import datetime, timezone
from decimal import Decimal
import boto3
import uuid

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])
bookings_table = dynamodb.Table(os.environ.get('BOOKINGS_TABLE_NAME', f'{ENVIRONMENT}-Bookings'))
chats_table = dynamodb.Table(os.environ.get('CHATS_TABLE_NAME', f'{ENVIRONMENT}-Chats'))

# Helper function to convert Decimal to float for JSON response
def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def get_active_bookings_for_listing(listing_id):
    """Get all active bookings (pending/confirmed) for a job listing"""
    try:
        from boto3.dynamodb.conditions import Key, Attr
        
        response = bookings_table.query(
            IndexName='listingId-startDate-index',
            KeyConditionExpression=Key('listingId').eq(listing_id),
            FilterExpression=Attr('status').is_in(['pending', 'confirmed']) & Attr('bookingType').eq('booking')
        )
        return response.get('Items', [])
    except Exception as e:
        print(f"Error fetching bookings for listing {listing_id}: {str(e)}")
        return []


def check_confirmed_bookings(listing_id):
    """
    Check if listing has any confirmed bookings.
    BLOCKS deletion if confirmed bookings exist.
    
    Returns:
        tuple: (has_confirmed, confirmed_count, confirmed_details, pending_count)
    """
    try:
        bookings = get_active_bookings_for_listing(listing_id)
        
        if not bookings:
            return False, 0, [], 0
        
        confirmed_bookings = [b for b in bookings if b['status'] == 'confirmed']
        pending_bookings = [b for b in bookings if b['status'] == 'pending']
        
        confirmed_details = []
        for booking in confirmed_bookings[:3]:  # Show max 3 examples
            confirmed_details.append({
                'bookingId': booking['bookingId'],
                'workerName': booking.get('metadata', {}).get('workerName', 'Unknown'),
                'startDate': booking['startDate'],
                'endDate': booking['endDate']
            })
        
        return len(confirmed_bookings) > 0, len(confirmed_bookings), confirmed_details, len(pending_bookings)
    except Exception as e:
        print(f"Error checking confirmed bookings: {str(e)}")
        return False, 0, [], 0


def cancel_pending_bookings_for_deleted_listing(listing_id, listing_title):
    """
    Cancel all PENDING bookings for a deleted listing.
    Confirmed bookings should be handled manually - deletion is blocked if they exist.
    
    Returns:
        int: Number of bookings cancelled
    """
    try:
        bookings = get_active_bookings_for_listing(listing_id)
        
        if not bookings:
            print(f"No active bookings found for listing {listing_id}")
            return 0
        
        # Only cancel pending bookings
        pending_bookings = [b for b in bookings if b['status'] == 'pending']
        
        print(f"Found {len(pending_bookings)} pending bookings to cancel for listing {listing_id}")
        
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        cancelled_count = 0
        
        for booking in pending_bookings:
            booking_id = booking['bookingId']
            booking_status = booking['status']
            
            try:
                # Cancel booking
                reason = f"The job listing '{listing_title}' has been deleted by the company."
                
                bookings_table.update_item(
                    Key={'bookingId': booking_id},
                    UpdateExpression='SET #status = :cancelled, updatedAt = :now, cancelledAt = :now, cancelledBy = :by, cancelledByRole = :role, cancellationReason = :reason',
                    ExpressionAttributeNames={
                        '#status': 'status'
                    },
                    ExpressionAttributeValues={
                        ':cancelled': 'cancelled',
                        ':now': now,
                        ':by': 'system_listing_deleted',
                        ':role': 'system',
                        ':reason': reason
                    }
                )
                
                print(f"Cancelled pending booking {booking_id}")
                cancelled_count += 1
                
                # Update chat booking_state (non-blocking)
                try:
                    chat_id = booking.get('chatId')
                    if chat_id:
                        chats_table.update_item(
                            Key={'chatId': chat_id},
                            UpdateExpression='SET booking_state = :cancelled, updatedAt = :now',
                            ExpressionAttributeValues={
                                ':cancelled': 'cancelled',
                                ':now': now
                            }
                        )
                        print(f"Updated chat {chat_id} booking_state to cancelled")
                except Exception as e:
                    print(f"Warning: Could not update chat for booking {booking_id}: {str(e)}")
                
            except Exception as e:
                print(f"Error cancelling pending booking {booking_id}: {str(e)}")
                continue
        
        print(f"Successfully cancelled {cancelled_count} pending bookings for deleted listing {listing_id}")
        return cancelled_count
        
    except Exception as e:
        print(f"Error in cancel_pending_bookings_for_deleted_listing: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0

def lambda_handler(event, context):
    """
    Delete a job listing (soft delete)
    
    DELETE /listings/{listingId}
    
    Authorization: Cognito JWT (company owner only)
    
    Soft delete: Sets status to 'deleted' and adds deletedAt timestamp
    Does not actually remove the item from DynamoDB
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
                    'message': 'Only company users can delete job listings'
                })
            }
        
        # Get listingId from path parameters
        listing_id = event['pathParameters']['listingId']
        
        # Get company info to verify ownership
        try:
            company_response = companies_table.get_item(Key={'userId': user_id})
            if 'Item' not in company_response:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Not Found',
                        'message': 'Company profile not found'
                    })
                }
            
            company = company_response['Item']
            company_id = company['companyId']
            
        except Exception as e:
            print(f"Error fetching company: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error fetching company information'
                })
            }
        
        # Get the listing to verify ownership
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
            
            # Check if listing belongs to this company
            if listing.get('companyId') != company_id:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'You can only delete your own job listings'
                    })
                }
            
            # Check if already deleted
            if listing.get('status') == 'deleted':
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'Job listing is already deleted'
                    })
                }
            
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
        
        # Check for confirmed bookings - BLOCK deletion if they exist
        print(f"Checking for confirmed bookings for listing {listing_id}...")
        has_confirmed, confirmed_count, confirmed_details, pending_count = check_confirmed_bookings(listing_id)
        
        if has_confirmed:
            print(f"BLOCKING: Listing has {confirmed_count} confirmed booking(s)")
            
            # Build error message with booking details
            booking_info = []
            for b in confirmed_details:
                booking_info.append(f"- Worker: {b['workerName']}, Dates: {b['startDate']} to {b['endDate']}")
            
            error_msg = f"Cannot delete listing: {confirmed_count} confirmed booking(s) exist. Please coordinate with workers to cancel their bookings first.\n"
            error_msg += "\n".join(booking_info)
            if confirmed_count > 3:
                error_msg += f"\n... and {confirmed_count - 3} more"
            
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'code': 4065,
                    'message': error_msg,
                    'confirmedBookingsCount': confirmed_count,
                    'pendingBookingsCount': pending_count
                })
            }
        
        # No confirmed bookings - cancel pending bookings and proceed
        listing_title = listing.get('title', 'Untitled Job')
        cancelled_bookings_count = cancel_pending_bookings_for_deleted_listing(listing_id, listing_title)
        
        if cancelled_bookings_count > 0:
            print(f"Cancelled {cancelled_bookings_count} pending bookings before deleting listing")
        
        # Perform soft delete: update status to 'deleted' and add deletedAt timestamp
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        try:
            job_listings_table.update_item(
                Key={'listingId': listing_id},
                UpdateExpression='SET #status = :status, deletedAt = :deletedAt, updatedAt = :updatedAt',
                ExpressionAttributeNames={
                    '#status': 'status'
                },
                ExpressionAttributeValues={
                    ':status': 'deleted',
                    ':deletedAt': now,
                    ':updatedAt': now
                }
            )
            
            print(f"Soft deleted listing: {listing_id}")
            
        except Exception as e:
            print(f"Error deleting listing: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error deleting job listing'
                })
            }
        
        # Build response
        response_body = {
            'message': 'Job listing deleted successfully',
            'listingId': listing_id,
            'deletedAt': now
        }
        
        # Add info about cancelled bookings if any
        if cancelled_bookings_count > 0:
            response_body['cancelledBookingsCount'] = cancelled_bookings_count
            response_body['cancelledBookingsReason'] = 'All active bookings were cancelled because the job listing was deleted'
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_body)
        }
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'message': f'Missing required parameter: {str(e)}'
            })
        }
    
    except Exception as e:
        print(f"Error in delete listing: {str(e)}")
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
                'message': 'An error occurred while deleting the job listing'
            })
        }