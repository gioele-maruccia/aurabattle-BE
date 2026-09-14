"""
Create Blackout Period Handler

Company creates a blackout period on a job listing.
Blackout is a special booking where workerId = companyId.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
import boto3
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


def parse_date(date_str):
    """Parse ISO date string to datetime"""
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except:
        return datetime.strptime(date_str, '%Y-%m-%d')


def check_date_overlap(start1, end1, start2, end2):
    """Check if two date ranges overlap"""
    return start1 <= end2 and end1 >= start2


def check_existing_bookings(listing_id, start_date, end_date):
    """
    Check if any ACCEPTED worker bookings exist in the proposed blackout period.
    Can't create blackout if workers are already booked!
    """
    try:
        response = bookings_table.query(
            IndexName='listingId-startDate-index',
            KeyConditionExpression=Key('listingId').eq(listing_id),
            FilterExpression=Attr('bookingType').eq('application') & Attr('status').eq('accepted')
        )
        
        conflicts = []
        for booking in response.get('Items', []):
            booking_start = parse_date(booking['startDate'])
            booking_end = parse_date(booking['endDate'])
            if check_date_overlap(start_date, end_date, booking_start, booking_end):
                conflicts.append(booking)
        
        return conflicts
    except Exception as e:
        print(f"Error checking existing bookings: {str(e)}")
        return []


def calculate_days(start_date, end_date):
    """Calculate number of days between two dates"""
    delta = end_date - start_date
    return delta.days + 1


def lambda_handler(event, context):
    """
    Create a blackout period for a job listing
    
    POST /bookings/blackout
    
    Request body:
    {
        "listingId": "job_2025_abc123",
        "startDate": "2025-08-15",
        "endDate": "2025-08-17",
        "reason": "Ferragosto - Ristorante chiuso",
        "type": "holiday"  // holiday | event | overstaffed | maintenance | other
    }
    
    Authorization: Cognito JWT (company only)
    """
    
    try:
        # Get user info from Cognito authorizer
        claims = event['requestContext']['authorizer']['claims']
        user_id = claims['sub']
        user_groups = claims.get('cognito:groups', '')
        
        # Check if user is a company
        if 'companies' not in user_groups:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4068,
                    'error': 'Forbidden',
                    'message': 'Only companies can create blackout periods'
                })
            }
        
        # Parse request body
        body = json.loads(event['body'])
        listing_id = body.get('listingId')
        start_date_str = body.get('startDate')
        end_date_str = body.get('endDate')
        reason = body.get('reason', 'Period not available')
        blackout_type = body.get('type', 'other')
        
        # Validate required fields
        if not listing_id or not start_date_str or not end_date_str:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'listingId, startDate, and endDate are required'
                })
            }
        
        # Validate blackout type
        valid_types = ['holiday', 'event', 'overstaffed', 'maintenance', 'other']
        if blackout_type not in valid_types:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Invalid type. Must be one of: {", ".join(valid_types)}'
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
        
        # TODO: Verify user owns this company (check Companies table)
        # For now we trust the companyId from listing
        company_id = listing['companyId']
        
        # Parse and validate dates
        try:
            start_date = parse_date(start_date_str)
            end_date = parse_date(end_date_str)
            listing_start = parse_date(listing['startDate'])
            listing_end = parse_date(listing['endDate'])
        except Exception as e:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'Invalid date format. Use YYYY-MM-DD'
                })
            }
        
        # Validate dates are within listing period
        if start_date < listing_start or end_date > listing_end:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Blackout dates must be within listing period ({listing["startDate"]} to {listing["endDate"]})'
                })
            }
        
        # Validate end_date >= start_date
        if end_date < start_date:
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
        
        # Check for existing accepted bookings in this period
        conflicts = check_existing_bookings(listing_id, start_date, end_date)
        if conflicts:
            conflict_workers = [b.get('workerName', 'Worker') for b in conflicts[:3]]
            return {
                'statusCode': 409,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Conflict',
                    'message': f'Cannot create blackout: {len(conflicts)} worker(s) already booked for this period',
                    'conflictingWorkers': conflict_workers,
                    'suggestion': 'Cancel existing bookings first or choose different dates'
                })
            }
        
        # Create blackout booking
        booking_id = f"book_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{str(uuid.uuid4())[:8]}"
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        days_count = calculate_days(start_date, end_date)
        
        blackout = {
            # Core identifiers
            'bookingId': booking_id,
            'listingId': listing_id,
            'companyId': company_id,
            'workerId': company_id,  # 🔑 KEY: workerId = companyId for blackout!
            'bookingType': 'blackout',
            
            # Worker info - null for blackout
            'workerName': None,
            'workerEmail': None,
            'workerPhone': None,
            'workerProfileImage': None,
            
            # Dates
            'startDate': start_date_str,
            'endDate': end_date_str,
            'daysCount': days_count,
            
            # Status
            'status': 'blocked',  # Permanent status for blackout
            'createdAt': now,
            'updatedAt': now,
            'statusUpdatedAt': now,
            'acceptedAt': None,
            'rejectedAt': None,
            'cancelledAt': None,
            'completedAt': None,
            
            # Blackout specific
            'blackoutReason': reason,
            'blackoutType': blackout_type,
            
            # Rejection - null for blackout
            'rejectionReason': None,
            'reviewedBy': user_id,  # Who created the blackout
            
            # Denormalized job info
            'jobTitle': listing.get('title', ''),
            'jobCategory': listing.get('category', ''),
            'jobLocation': listing.get('location', {}),
            
            # Denormalized company info
            'companyName': '',  # TODO: fetch from Companies table
            'companyLogo': '',
            
            # Metadata
            'source': 'web-app',
            'isActive': True,
            
            # Future references
            'chatRoomId': None,
            'contractId': None,
            
            # Application message - null for blackout
            'applicationMessage': None
        }
        
        # Save blackout to DynamoDB
        bookings_table.put_item(Item=blackout)
        
        # Convert Decimal for JSON response
        response_blackout = json.loads(json.dumps(blackout, cls=DecimalEncoder))
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': True,
                'message': 'Blackout period created successfully',
                'blackout': response_blackout
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
                'message': 'Invalid JSON in request body'
            })
        }
    except Exception as e:
        print(f"Error creating blackout: {str(e)}")
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
                'message': 'An error occurred while creating the blackout period'
            })
        }