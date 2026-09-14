"""
Get Booking Handler

This Lambda function retrieves a single booking by ID.
Returns full booking details including listing and company info.

Worker (own bookings) or Company (own listings) only.
"""

import json
import os
import boto3
from boto3.dynamodb.conditions import Key
from decimal import Decimal

# Initialize DynamoDB and Cognito
dynamodb = boto3.resource('dynamodb')
cognito = boto3.client('cognito-idp')
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])

# Cognito User Pool ID
USER_POOL_ID = os.environ.get('USER_POOL_ID', 'eu-south-1_iCBtUlJO6')


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /bookings/{bookingId}
    
    Returns booking details with enriched data.
    Only accessible by:
    - Worker who created the booking
    - Company owner of the listing
    
    Authorization: Cognito JWT (worker or company)
    """
    
    try:
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Get booking ID from path
        booking_id = event['pathParameters']['bookingId']
        
        print(f"Get booking: {booking_id} for user: {user_id}")
        
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
                    'error': 'Internal Server Error',
                    'message': 'Error fetching booking'
                })
            }
        
        # Check if it's a blackout
        if booking.get('bookingType') == 'blackout':
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'This is a blackout period, not a booking'
                })
            }
        
        # Verify user has access to this booking
        is_worker = 'workers' in user_groups
        is_company = 'companies' in user_groups
        
        has_access = False
        
        print(f"User groups: {user_groups}, is_worker: {is_worker}, is_company: {is_company}")
        print(f"Booking companyId: {booking.get('companyId')}, workerId: {booking.get('workerId')}")
        
        # Worker can only see their own bookings
        if is_worker and booking.get('workerId') == user_id:
            has_access = True
            print(f"Access granted: worker owns booking")
        
        # Company can see bookings for their listings
        # Check both via companyId match and via chat participation (companyRepresentativeId)
        if is_company:
            try:
                # Try to get company record
                company_response = companies_table.get_item(Key={'userId': user_id})
                print(f"Company lookup response: {company_response.get('Item') is not None}")
                
                if 'Item' in company_response:
                    company = company_response['Item']
                    company_id = company.get('companyId')
                    print(f"Found company with companyId: {company_id}")
                    
                    # Check if companyId matches booking
                    if company_id == booking.get('companyId'):
                        has_access = True
                        print(f"Access granted: company owns booking")
                else:
                    # Fallback: query by companyId-index to find company
                    print(f"Company record not found by userId, trying companyId-index")
                    company_query = companies_table.query(
                        IndexName='companyId-index',
                        KeyConditionExpression='companyId = :companyId',
                        ExpressionAttributeValues={':companyId': booking.get('companyId')},
                        Limit=1
                    )
                    if company_query.get('Items'):
                        # Check if any of the company representatives match the current user
                        for comp_item in company_query['Items']:
                            if comp_item.get('userId') == user_id:
                                has_access = True
                                print(f"Access granted: user is company representative")
                                break
            except Exception as e:
                print(f"Error checking company access: {str(e)}")
                import traceback
                traceback.print_exc()
        
        if not has_access:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Forbidden',
                    'message': 'You do not have access to this booking'
                })
            }
        
        # Enrich booking with full listing details (ListingSummary)
        try:
            listing_response = job_listings_table.get_item(Key={'listingId': booking['listingId']})
            if 'Item' in listing_response:
                listing = listing_response['Item']
                booking['listing'] = {
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
            # Fallback with minimal info
            booking['listing'] = {
                'listingId': booking.get('listingId'),
                'title': booking.get('metadata', {}).get('listingTitle', 'Unknown Listing'),
                'category': booking.get('metadata', {}).get('listingCategory', ''),
                'positions': 0,
                'positionsFilled': 0,
                'positionsRemaining': 0,
                'startDate': '',
                'endDate': '',
                'status': 'unknown'
            }
        
        # Enrich with company details (CompanySummary)
        try:
            company_response = companies_table.query(
                IndexName='companyId-index',
                KeyConditionExpression=Key('companyId').eq(booking['companyId']),
                Limit=1
            )
            
            if company_response.get('Items'):
                company = company_response['Items'][0]
                booking['company'] = {
                    'companyId': company.get('companyId'),
                    'businessName': company.get('businessName'),
                    'logoUrl': company.get('media', {}).get('profileImageUrl', ''),
                    'rating': float(company.get('stats', {}).get('averageRating', 0))
                }
            else:
                # Fallback
                booking['company'] = {
                    'companyId': booking.get('companyId'),
                    'businessName': booking.get('metadata', {}).get('companyName', 'Unknown Company'),
                    'logoUrl': '',
                    'rating': 0.0
                }
        except Exception as e:
            print(f"Error fetching company details: {str(e)}")
            booking['company'] = {
                'companyId': booking.get('companyId'),
                'businessName': 'Unknown Company',
                'logoUrl': '',
                'rating': 0.0
            }
        
        # Enrich with worker profile (WorkerProfile) - if company is viewing
        if is_company:
            try:
                # Import user profiles table
                user_profiles_table = dynamodb.Table(os.environ.get('USER_PROFILES_TABLE_NAME', 'dev-user-profiles'))
                
                def build_worker_profile(worker, worker_id):
                    profile_data = worker.get('profile', {}) if isinstance(worker, dict) else {}
                    first_name = (
                        profile_data.get('given_name')
                        or worker.get('firstName')
                        or worker.get('given_name')
                        or 'Unknown'
                    )
                    last_name = (
                        profile_data.get('family_name')
                        or worker.get('lastName')
                        or worker.get('family_name')
                        or 'Worker'
                    )
                    profile_image = (
                        worker.get('profile_photo_url')
                        or worker.get('photoUrl')
                        or worker.get('profileImage')
                        or ''
                    )
                    return {
                        'userId': worker.get('userId', worker_id),
                        'firstName': first_name,
                        'lastName': last_name,
                        'profileImage': profile_image,
                        'rating': float(worker.get('rating', 0)),
                        'completedJobs': int(worker.get('completedJobs', 0)),
                        'languages': worker.get('languages', []),
                        'experience': worker.get('experience', {}),
                        'badges': worker.get('badges', [])
                    }

                worker_response = user_profiles_table.get_item(Key={'user_id': booking['workerId']})
                if 'Item' in worker_response:
                    worker = worker_response['Item']
                    booking['worker'] = build_worker_profile(worker, booking['workerId'])
                else:
                    worker_response = user_profiles_table.get_item(Key={'userId': booking['workerId']})
                    if 'Item' in worker_response:
                        worker = worker_response['Item']
                        booking['worker'] = build_worker_profile(worker, booking['workerId'])
                    else:
                        # Profile not found - use metadata workerName
                        booking['worker'] = {
                            'userId': booking['workerId'],
                            'firstName': 'Unknown',
                            'lastName': 'Worker',
                            'profileImage': '',
                            'rating': 0.0,
                            'completedJobs': 0,
                            'languages': [],
                            'experience': {'years': 0, 'relevant': False},
                            'badges': []
                        }
                
                # IMPORTANT: Check if profile data is incomplete and use fallbacks
                if booking.get('worker'):
                    first_name = booking['worker'].get('firstName', '')
                    last_name = booking['worker'].get('lastName', '')
                    
                    # If firstName/lastName are empty or default values, try Cognito then metadata
                    if (not first_name or first_name == 'Unknown' or 
                        not last_name or last_name == 'Worker'):
                        
                        # Try Cognito first
                        try:
                            cognito_user = cognito.admin_get_user(
                                UserPoolId=USER_POOL_ID,
                                Username=booking['workerId']
                            )
                            for attr in cognito_user.get('UserAttributes', []):
                                if attr['Name'] == 'given_name':
                                    booking['worker']['firstName'] = attr['Value']
                                elif attr['Name'] == 'family_name':
                                    booking['worker']['lastName'] = attr['Value']
                            print(f"Retrieved worker name from Cognito: {booking['worker']['firstName']} {booking['worker']['lastName']}")
                        except Exception as e:
                            print(f"Could not fetch from Cognito: {e}")
                            # Fallback to metadata if Cognito fails
                            worker_name_fallback = booking.get('metadata', {}).get('workerName', '')
                            if worker_name_fallback:
                                parts = worker_name_fallback.split()
                                if parts:
                                    booking['worker']['firstName'] = parts[0]
                                    booking['worker']['lastName'] = parts[-1] if len(parts) > 1 else ''
            except Exception as e:
                print(f"Error fetching worker profile: {str(e)}")
                booking['worker'] = {
                    'userId': booking['workerId'],
                    'firstName': 'Unknown',
                    'lastName': 'Worker',
                    'profileImage': '',
                    'rating': 0.0,
                    'completedJobs': 0,
                    'languages': [],
                    'experience': {'years': 0, 'relevant': False},
                    'badges': []
                }
        
        # Convert Decimal back to float for JSON response
        response_booking = json.loads(json.dumps(booking, cls=DecimalEncoder))
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'booking': response_booking
            })
        }
        
    except Exception as e:
        print(f"Error getting booking: {str(e)}")
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
                'message': 'An error occurred while fetching the booking'
            })
        }