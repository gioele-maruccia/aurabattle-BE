"""
Cancel Booking Handler - Updated Version

This Lambda function cancels a booking or removes a blackout period.
Can be cancelled by:
- Worker (who created it) - with restrictions on 'accepted' status
- Company owner (of the listing) - always allowed

Effects:
- Sets booking status to 'cancelled'
- If booking was 'accepted', decrements listing positionsFilled
- If blackout (status='blocked'), deletes the period entirely
- Records who cancelled and when
- Tracks late cancellations for behavioral analytics

Status Cancellation Rules:
- pending: ✅ Always cancellable by both parties
- accepted: ⚠️ Conditional (see logic below)
- blocked: ⚠️ Only company can delete (blackout periods)
- contracted: ❌ Cannot cancel (must contact support)
- completed: ❌ Cannot cancel
- cancelled/rejected: ❌ Already in final state
"""

import json
import os
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])

# Configuration
MINIMUM_CANCELLATION_NOTICE_DAYS = int(os.environ.get('MINIMUM_CANCELLATION_NOTICE_DAYS', 7))


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def validate_accepted_cancellation(booking, cancelled_by_role):
    """
    Validates if an 'accepted' booking can be cancelled based on role and timing.
    
    Rules:
    - Company: Always allowed (with late cancellation flag if < 7 days)
    - Worker: Only if >= 7 days before start date
    
    Args:
        booking: Booking DynamoDB item
        cancelled_by_role: 'worker' or 'company'
        
    Returns:
        dict: {
            'allowed': bool,
            'message': str,
            'metadata': dict (days_until_start, late_cancellation, etc.)
        }
    """
    try:
        start_date = datetime.fromisoformat(booking['startDate'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        days_until_start = (start_date - now).days
        
        # Booking already started or passed
        if days_until_start < 0:
            return {
                'allowed': False,
                'message': 'Cannot cancel booking that has already started or passed',
                'metadata': {'days_until_start': days_until_start}
            }
        
        # COMPANY: Always allowed
        if cancelled_by_role == 'company':
            metadata = {'days_until_start': days_until_start}
            
            # Flag late cancellation for tracking
            if days_until_start < MINIMUM_CANCELLATION_NOTICE_DAYS:
                metadata['late_cancellation'] = True
                metadata['notify_backoffice'] = True
            
            return {
                'allowed': True,
                'message': 'Company cancellation allowed',
                'metadata': metadata
            }
        
        # WORKER: Must respect minimum notice period
        if cancelled_by_role == 'worker':
            if days_until_start < MINIMUM_CANCELLATION_NOTICE_DAYS:
                return {
                    'allowed': False,
                    'message': f'Workers must cancel at least {MINIMUM_CANCELLATION_NOTICE_DAYS} days before the start date. Please contact support.',
                    'metadata': {
                        'days_until_start': days_until_start,
                        'minimum_required_days': MINIMUM_CANCELLATION_NOTICE_DAYS,
                        'support_email': 'support@4seasonsjob.com',
                        'support_required': True
                    }
                }
            
            # Allowed
            return {
                'allowed': True,
                'message': 'Worker cancellation allowed',
                'metadata': {'days_until_start': days_until_start}
            }
        
        # Unknown role
        return {
            'allowed': False,
            'message': 'Invalid user role',
            'metadata': {}
        }
        
    except Exception as e:
        print(f"Error validating cancellation: {str(e)}")
        return {
            'allowed': False,
            'message': 'Error validating cancellation timing',
            'metadata': {}
        }


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    PATCH /bookings/{bookingId}/cancel
    
    Optional fields in body:
    - reason: Cancellation reason
    
    Authorization: Cognito JWT (worker or company owner)
    """
    
    try:
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Get booking ID from path
        booking_id = event['pathParameters']['bookingId']
        
        # Parse request body (optional)
        body = {}
        if event.get('body'):
            try:
                body = json.loads(event['body'])
            except json.JSONDecodeError:
                pass
        
        cancellation_reason = body.get('reason', '')
        
        print(f"Cancel booking: {booking_id} by user: {user_id}")
        
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
                        'code': 4042,
                        'error': 'Not Found',
                        'message': 'Booking not found'
                    })
                }
            
            booking = booking_response['Item']
            
        except Exception as e:
            print(f"Error fetching booking: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5010,
                    'error': 'Internal Server Error',
                    'message': 'Error fetching booking'
                })
            }
        
        # Check current status - Block final states
        current_status = booking.get('status')
        
        # ⭐ SPECIAL: Handle 'blocked' status (blackout periods)
        # Only company can delete blackout periods
        if current_status == 'blocked':
            # Verify it's a blackout booking
            if booking.get('bookingType') != 'blackout':
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4040,
                        'error': 'Bad Request',
                        'message': 'Invalid booking state: status is blocked but bookingType is not blackout'
                    })
                }
            
            # Check if user is company owner
            is_company = 'companies' in user_groups
            if not is_company:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4041,
                        'error': 'Forbidden',
                        'message': 'Only company owners can delete blackout periods'
                    })
                }
            
            # Verify company ownership
            try:
                # Query Companies table using userId-index (GSI) or scan
                company_response = companies_table.query(
                    IndexName='userId-index',
                    KeyConditionExpression=Key('userId').eq(user_id),
                    Limit=1
                )
                
                if not company_response.get('Items'):
                    return {
                        'statusCode': 403,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'code': 4041,
                            'error': 'Forbidden',
                            'message': 'Company profile not found'
                        })
                    }
                
                company = company_response['Items'][0]
                if company['companyId'] != booking.get('companyId'):
                    return {
                        'statusCode': 403,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'code': 4041,
                            'error': 'Forbidden',
                            'message': 'You can only delete blackout periods for your own listings'
                        })
                    }
            except Exception as e:
                print(f"Error verifying company ownership: {str(e)}")
                # Fallback: try direct get_item
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
                                'code': 4041,
                                'error': 'Forbidden',
                                'message': 'Company profile not found'
                            })
                        }
                    
                    company = company_response['Item']
                    if company['companyId'] != booking.get('companyId'):
                        return {
                            'statusCode': 403,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'code': 4041,
                                'error': 'Forbidden',
                                'message': 'You can only delete blackout periods for your own listings'
                            })
                        }
                except Exception as e2:
                    print(f"Error in fallback ownership check: {str(e2)}")
                    return {
                        'statusCode': 500,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'code': 5010,
                            'error': 'Internal Server Error',
                            'message': 'Error verifying ownership'
                        })
                    }
            
            # Delete the blackout period (hard delete)
            try:
                bookings_table.delete_item(Key={'bookingId': booking_id})
                print(f"Blackout period deleted: {booking_id} by company: {company['companyId']}")
                
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 3004,
                        'message': 'Blackout period deleted successfully',
                        'booking_id': booking_id,
                        'blackout_type': booking.get('blackoutType'),
                        'period': {
                            'start_date': booking.get('startDate'),
                            'end_date': booking.get('endDate')
                        }
                    })
                }
            except Exception as e:
                print(f"Error deleting blackout: {str(e)}")
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 5010,
                        'error': 'Internal Server Error',
                        'message': 'Error deleting blackout period'
                    })
                }
        
        # Special handling for 'contracted' status
        if current_status == 'contracted':
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4040,
                    'error': 'Bad Request',
                    'message': 'Cannot cancel booking with active contract. Please contact support.',
                    'contract_id': booking.get('contractId'),
                    'support_email': 'support@4seasonsjob.com',
                    'support_phone': '+39 XXX XXX XXXX'
                })
            }
        
        # Block other final states
        if current_status in ['cancelled', 'rejected', 'completed']:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4040,
                    'error': 'Bad Request',
                    'message': f'Cannot cancel booking with status: {current_status}'
                })
            }
        
        # Verify user has permission to cancel
        is_worker = 'workers' in user_groups
        is_company = 'companies' in user_groups
        is_admin = 'admins' in user_groups
        
        can_cancel = False
        cancelled_by_role = None
        
        # Admin (backoffice) can cancel any booking
        if is_admin:
            can_cancel = True
            cancelled_by_role = 'admin'
        
        # Worker can cancel their own booking
        if is_worker and booking.get('workerId') == user_id:
            can_cancel = True
            cancelled_by_role = 'worker'
        
        # Company can cancel bookings for their listings
        if is_company:
            try:
                # Query Companies table using userId-index (GSI) or scan
                # Assuming Companies table has a GSI on userId
                company_response = companies_table.query(
                    IndexName='userId-index',
                    KeyConditionExpression=Key('userId').eq(user_id),
                    Limit=1
                )
                
                if company_response.get('Items'):
                    company = company_response['Items'][0]
                    if company['companyId'] == booking.get('companyId'):
                        can_cancel = True
                        cancelled_by_role = 'company'
            except Exception as e:
                print(f"Error checking company: {str(e)}")
                # Fallback: try direct get_item if userId is the partition key
                try:
                    company_response = companies_table.get_item(Key={'userId': user_id})
                    if 'Item' in company_response:
                        company = company_response['Item']
                        if company['companyId'] == booking.get('companyId'):
                            can_cancel = True
                            cancelled_by_role = 'company'
                except Exception as e2:
                    print(f"Error in fallback company check: {str(e2)}")
        
        if not can_cancel:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4041,
                    'error': 'Forbidden',
                    'message': 'You do not have permission to cancel this booking'
                })
            }
        
        # ⭐ NEW: Special validation for 'accepted' status
        cancellation_metadata = {}
        if current_status == 'accepted' and cancelled_by_role != 'admin':
            validation_result = validate_accepted_cancellation(booking, cancelled_by_role)
            
            if not validation_result['allowed']:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4040,
                        'error': 'Bad Request',
                        'message': validation_result['message'],
                        **validation_result['metadata']
                    })
                }
            
            # Store metadata for tracking
            cancellation_metadata = validation_result['metadata']
        
        # Check if booking was accepted/confirmed (need to update listing counter)
        # Note: Only 'accepted' status affects positionsFilled
        was_accepted = (current_status == 'accepted')
        
        # Update booking status
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        update_expression = 'SET #status = :status, updatedAt = :updatedAt, cancelledAt = :cancelledAt, cancelledBy = :cancelledBy, cancelledByRole = :cancelledByRole'
        expression_values = {
            ':status': 'cancelled',
            ':updatedAt': now,
            ':cancelledAt': now,
            ':cancelledBy': user_id,
            ':cancelledByRole': cancelled_by_role
        }
        expression_names = {
            '#status': 'status'
        }
        
        # Add cancellation reason if provided
        if cancellation_reason:
            update_expression += ', cancellationReason = :cancellationReason'
            expression_values[':cancellationReason'] = cancellation_reason
        
        # Add cancellation metadata (days_until_start, late_cancellation, etc.)
        if cancellation_metadata:
            update_expression += ', cancellationMetadata = :cancellationMetadata'
            expression_values[':cancellationMetadata'] = cancellation_metadata
        
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
                    'code': 5010,
                    'error': 'Internal Server Error',
                    'message': 'Error cancelling booking'
                })
            }
        
        # If booking was accepted, decrement listing positionsFilled
        if was_accepted:
            try:
                # Use ADD with negative value to decrement
                job_listings_table.update_item(
                    Key={'listingId': booking['listingId']},
                    UpdateExpression='ADD positionsFilled :dec',
                    ExpressionAttributeValues={':dec': -1}
                )
                print(f"Decremented positionsFilled for listing {booking['listingId']}")
                
            except Exception as e:
                print(f"Error updating listing positions: {str(e)}")
                # Non-critical error, booking is already cancelled
        
        # TODO: Send notification to the other party
        # if cancelled_by_role == 'worker':
        #     notify_company(booking['companyId'], booking_id)
        # else:
        #     notify_worker(booking['workerId'], booking_id)
        
        # Get updated booking
        updated_booking = bookings_table.get_item(Key={'bookingId': booking_id})['Item']
        
        print(f"Booking {booking_id} cancelled by {cancelled_by_role}")
        
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
                'code': 3004,
                'message': 'Booking cancelled successfully',
                'booking': response_booking
            })
        }
        
    except Exception as e:
        print(f"Error cancelling booking: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 5010,
                'error': 'Internal Server Error',
                'message': 'An error occurred while cancelling the booking'
            })
        }