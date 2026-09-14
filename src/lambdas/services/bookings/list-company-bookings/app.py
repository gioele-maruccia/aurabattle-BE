"""
List Company Bookings Handler

This Lambda function lists all bookings for a company.
Includes filters by status and listing, with pagination.

Company owner only.
"""

import json
import os
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

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


def enrich_bookings_with_details(bookings):
    """
    Enrich bookings with worker profile and listing details per swagger
    
    Args:
        bookings: List of booking items
        
    Returns:
        List of enriched bookings with WorkerProfile and ListingSummary
    """
    # Get unique listing IDs and worker IDs
    listing_ids = list(set([b.get('listingId') for b in bookings if b.get('listingId')]))
    worker_ids = list(set([b.get('workerId') for b in bookings if b.get('workerId')]))
    
    # Import user profiles table
    user_profiles_table = dynamodb.Table(os.environ.get('USER_PROFILES_TABLE_NAME', 'dev-user-profiles'))
    
    # Fetch listings
    listings_map = {}
    for listing_id in listing_ids[:50]:  # Limit to first 50
        try:
            response = job_listings_table.get_item(Key={'listingId': listing_id})
            if 'Item' in response:
                listing = response['Item']
                listings_map[listing_id] = {
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
            print(f"Error fetching listing {listing_id}: {str(e)}")
    
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

    # Fetch worker profiles
    workers_map = {}
    for worker_id in worker_ids[:50]:  # Limit to first 50
        try:
            response = user_profiles_table.get_item(Key={'user_id': worker_id})
            if 'Item' in response:
                worker = response['Item']
                workers_map[worker_id] = build_worker_profile(worker, worker_id)
            else:
                response = user_profiles_table.get_item(Key={'userId': worker_id})
                if 'Item' in response:
                    worker = response['Item']
                    workers_map[worker_id] = build_worker_profile(worker, worker_id)
                # If not found in user_profiles, will use metadata fallback later
        except Exception as e:
            print(f"Error fetching worker {worker_id}: {str(e)}")
    
    # Enrich bookings
    enriched = []
    for booking in bookings:
        enriched_booking = dict(booking)
        
        # Add listing details (ListingSummary)
        listing_id = booking.get('listingId')
        if listing_id and listing_id in listings_map:
            enriched_booking['listing'] = listings_map[listing_id]
        else:
            # Fallback
            enriched_booking['listing'] = {
                'listingId': listing_id or '',
                'title': booking.get('metadata', {}).get('listingTitle', 'Unknown Listing'),
                'category': booking.get('metadata', {}).get('listingCategory', ''),
                'positions': 0,
                'positionsFilled': 0,
                'positionsRemaining': 0,
                'startDate': '',
                'endDate': '',
                'status': 'unknown'
            }
        
        # Add worker profile (WorkerProfile)
        worker_id = booking.get('workerId')
        if worker_id and worker_id in workers_map:
            enriched_booking['worker'] = workers_map[worker_id]
            
            # IMPORTANT: Check if profile data is incomplete and use fallbacks
            first_name = enriched_booking['worker'].get('firstName', '')
            last_name = enriched_booking['worker'].get('lastName', '')
            
            # If firstName/lastName are empty or default values, try Cognito then metadata
            if (not first_name or first_name == 'Unknown' or 
                not last_name or last_name == 'Worker'):
                
                # Try Cognito first
                try:
                    cognito_user = cognito.admin_get_user(
                        UserPoolId=USER_POOL_ID,
                        Username=worker_id
                    )
                    for attr in cognito_user.get('UserAttributes', []):
                        if attr['Name'] == 'given_name':
                            enriched_booking['worker']['firstName'] = attr['Value']
                        elif attr['Name'] == 'family_name':
                            enriched_booking['worker']['lastName'] = attr['Value']
                except Exception as e:
                    print(f"Could not fetch from Cognito for {worker_id}: {e}")
                    # Fallback to metadata if Cognito fails
                    worker_name_fallback = booking.get('metadata', {}).get('workerName', '')
                    if worker_name_fallback:
                        parts = worker_name_fallback.split()
                        if parts:
                            enriched_booking['worker']['firstName'] = parts[0]
                            enriched_booking['worker']['lastName'] = parts[-1] if len(parts) > 1 else ''
        else:
            # Fallback using metadata workerName
            worker_name_fallback = booking.get('metadata', {}).get('workerName', '')
            first_name = 'Unknown'
            last_name = 'Worker'
            
            if worker_name_fallback:
                parts = worker_name_fallback.split()
                if parts:
                    first_name = parts[0]
                    last_name = parts[-1] if len(parts) > 1 else ''
            
            enriched_booking['worker'] = {
                'userId': worker_id or '',
                'firstName': first_name,
                'lastName': last_name,
                'profileImage': booking.get('metadata', {}).get('workerProfileImage', ''),
                'rating': 0.0,
                'completedJobs': 0,
                'languages': [],
                'experience': {'years': 0, 'relevant': False},
                'badges': []
            }

        worker_name_fallback = booking.get('metadata', {}).get('workerName')
        if worker_name_fallback and enriched_booking.get('worker'):
            first_name = enriched_booking['worker'].get('firstName')
            last_name = enriched_booking['worker'].get('lastName')
            if not first_name or first_name == 'Unknown' or last_name == 'Worker':
                parts = worker_name_fallback.split()
                enriched_booking['worker']['firstName'] = parts[0] if parts else 'Unknown'
                enriched_booking['worker']['lastName'] = parts[-1] if len(parts) > 1 else 'Worker'
        
        enriched.append(enriched_booking)
    
    return enriched


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /bookings/company/{companyId}?status=pending&listingId=xxx&limit=20
    
    Query Parameters:
    - status: Filter by status (pending, confirmed, rejected, cancelled)
    - listingId: Filter by specific listing
    - limit: Items per page (default: 20, max: 50)
    - lastKey: Pagination token
    
    Returns:
        200: List of company bookings
        403: Forbidden (trying to access another company's bookings)
        500: Internal server error
    """
    
    try:
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Check if user is a company
        if 'companies' not in user_groups:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4066,
                    'error': 'Forbidden',
                    'message': 'Only companies can access this endpoint'
                })
            }
        
        # Get company ID from path
        company_id = event['pathParameters']['companyId']
        
        # Verify user owns this company
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
                        'error': 'Forbidden',
                        'message': 'Company profile not found'
                    })
                }
            
            company = company_response['Item']
            
            if company['companyId'] != company_id:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'You can only view bookings for your own company'
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
                    'error': 'Internal Server Error',
                    'message': 'Error verifying ownership'
                })
            }
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        status_filter = params.get('status')
        listing_id_filter = params.get('listingId')
        limit = min(int(params.get('limit', 20)), 50)
        last_key = params.get('lastKey')
        
        print(f"List bookings for company: {company_id}, status: {status_filter}, listing: {listing_id_filter}")
        
        # Choose index based on filters
        if status_filter:
            # Use companyId-status-index
            query_params = {
                'IndexName': 'companyId-status-index',
                'KeyConditionExpression': Key('companyId').eq(company_id) & Key('status').eq(status_filter),
                'Limit': limit,
                'ScanIndexForward': False
            }
            
            # Add listing filter if provided
            if listing_id_filter:
                query_params['FilterExpression'] = Attr('listingId').eq(listing_id_filter) & Attr('bookingType').eq('booking')
            else:
                query_params['FilterExpression'] = Attr('bookingType').eq('booking')
        else:
            # Use companyId-createdAt-index
            query_params = {
                'IndexName': 'companyId-createdAt-index',
                'KeyConditionExpression': Key('companyId').eq(company_id),
                'Limit': limit,
                'ScanIndexForward': False  # Most recent first
            }
            
            # Add filters
            filter_expressions = [Attr('bookingType').eq('booking')]
            if listing_id_filter:
                filter_expressions.append(Attr('listingId').eq(listing_id_filter))
            
            if len(filter_expressions) > 1:
                query_params['FilterExpression'] = filter_expressions[0]
                for expr in filter_expressions[1:]:
                    query_params['FilterExpression'] = query_params['FilterExpression'] & expr
            else:
                query_params['FilterExpression'] = filter_expressions[0]
        
        # Add pagination
        if last_key:
            try:
                import base64
                decoded_key = base64.b64decode(last_key).decode('utf-8')
                query_params['ExclusiveStartKey'] = json.loads(decoded_key)
            except Exception as e:
                print(f"Invalid lastKey: {str(e)}")
        
        # Query bookings
        try:
            response = bookings_table.query(**query_params)
            bookings = response.get('Items', [])
            
        except Exception as e:
            print(f"Error querying bookings: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error querying bookings'
                })
            }
        
        # Enrich with listing and worker details
        enriched_bookings = enrich_bookings_with_details(bookings)
        
        # Calculate statistics
        stats = {
            'total': len(enriched_bookings),
            'pending': sum(1 for b in enriched_bookings if b.get('status') == 'pending'),
            'confirmed': sum(1 for b in enriched_bookings if b.get('status') == 'confirmed'),
            'rejected': sum(1 for b in enriched_bookings if b.get('status') == 'rejected'),
            'cancelled': sum(1 for b in enriched_bookings if b.get('status') == 'cancelled'),
            'completed': sum(1 for b in enriched_bookings if b.get('status') == 'completed'),
            'no_show': sum(1 for b in enriched_bookings if b.get('status') == 'no_show')
        }
        
        # Build pagination cursor
        next_cursor = None
        if response.get('LastEvaluatedKey'):
            import base64
            cursor_json = json.dumps(response['LastEvaluatedKey'])
            next_cursor = base64.b64encode(cursor_json.encode('utf-8')).decode('utf-8')
        
        # Build response (aligned with swagger)
        response_body = {
            'statusCode': 200,
            'bookings': enriched_bookings,
            'count': len(enriched_bookings),
            'stats': stats,
            'lastKey': next_cursor
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_body, cls=DecimalEncoder)
        }
        
    except Exception as e:
        print(f"Error listing company bookings: {str(e)}")
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
                'message': 'An error occurred while listing bookings'
            })
        }