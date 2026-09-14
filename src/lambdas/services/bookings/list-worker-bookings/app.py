"""
List Worker Bookings Handler

This Lambda function lists all bookings for a specific worker.
Includes filters by status and pagination.

Worker can only see their own bookings.
"""

import json
import os
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def enrich_bookings_with_details(bookings):
    """
    Enrich bookings with listing and company details per swagger schema
    
    Args:
        bookings: List of booking items
        
    Returns:
        List of enriched bookings with ListingSummary and CompanySummary
    """
    # Get unique listing IDs and company IDs
    listing_ids = list(set([b.get('listingId') for b in bookings if b.get('listingId')]))
    company_ids = list(set([b.get('companyId') for b in bookings if b.get('companyId')]))
    
    # Fetch listings (simplified - in production use batch get)
    listings_map = {}
    for listing_id in listing_ids[:20]:  # Limit to first 20
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
    
    # Fetch companies (simplified)
    companies_map = {}
    for company_id in company_ids[:20]:  # Limit to first 20
        try:
            response = companies_table.query(
                IndexName='companyId-index',
                KeyConditionExpression=Key('companyId').eq(company_id),
                Limit=1
            )
            if response.get('Items'):
                company = response['Items'][0]
                companies_map[company_id] = {
                    'companyId': company.get('companyId'),
                    'businessName': company.get('businessName'),
                    'logoUrl': company.get('media', {}).get('profileImageUrl', ''),
                    'rating': float(company.get('stats', {}).get('averageRating', 0))
                }
        except Exception as e:
            print(f"Error fetching company {company_id}: {str(e)}")
    
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
        
        # Add company details (CompanySummary)
        company_id = booking.get('companyId')
        if company_id and company_id in companies_map:
            enriched_booking['company'] = companies_map[company_id]
        else:
            # Fallback - handle empty string in metadata
            metadata_company_name = booking.get('metadata', {}).get('companyName', '')
            enriched_booking['company'] = {
                'companyId': company_id or '',
                'businessName': metadata_company_name if metadata_company_name else 'Unknown Company',
                'logoUrl': '',
                'rating': 0.0
            }
        
        enriched.append(enriched_booking)
    
    return enriched


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /bookings/worker/{workerId}?status=pending&limit=20
    
    Query Parameters:
    - status: Filter by status (pending, confirmed, rejected, cancelled)
    - limit: Items per page (default: 20, max: 50)
    - lastKey: Pagination token
    
    Returns:
        200: List of worker bookings
        403: Forbidden (trying to access another worker's bookings)
        500: Internal server error
    """
    
    try:
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Check if user is a worker
        if 'workers' not in user_groups:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4065,
                    'error': 'Forbidden',
                    'message': 'Only workers can access this endpoint'
                })
            }
        
        # Get worker ID from path
        worker_id = event['pathParameters']['workerId']
        
        # Workers can only see their own bookings
        if worker_id != user_id:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4069,
                    'error': 'Forbidden',
                    'message': 'You can only view your own bookings'
                })
            }
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        status_filter = params.get('status')
        limit = min(int(params.get('limit', 20)), 50)
        last_key = params.get('lastKey')
        range_start_param = params.get('startDate')
        range_end_param = params.get('endDate')
        
        print(f"List bookings for worker: {worker_id}, status: {status_filter}, range: {range_start_param} to {range_end_param}")
        
        # ---------------------------------------------------------------
        # Date-range mode: conflict detection for the booking flow
        # Called with ?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
        # Returns all confirmed/contracted bookings that overlap with the
        # given range (clamped to today so past conflicts are excluded).
        # ---------------------------------------------------------------
        if range_start_param and range_end_param:
            from datetime import date
            today = date.today().isoformat()
            # Only care about overlaps from today onward
            effective_start = max(range_start_param, today)
            
            conflict_query = {
                'IndexName': 'workerId-startDate-index',
                # All bookings that START at or before the range end (could overlap)
                'KeyConditionExpression': Key('workerId').eq(worker_id) & Key('startDate').lte(range_end_param),
                # Keep only those that END at or after our effective start,
                # are real bookings (not blackouts), and are accepted
                'FilterExpression': (
                    Attr('endDate').gte(effective_start) &
                    Attr('bookingType').eq('booking') &
                    (Attr('status').eq('confirmed') | Attr('status').eq('contracted'))
                )
            }
            
            conflict_bookings = []
            try:
                while True:
                    resp = bookings_table.query(**conflict_query)
                    conflict_bookings.extend(resp.get('Items', []))
                    if not resp.get('LastEvaluatedKey'):
                        break
                    conflict_query['ExclusiveStartKey'] = resp['LastEvaluatedKey']
            except Exception as e:
                print(f"Error querying conflict bookings: {str(e)}")
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
            
            print(f"Found {len(conflict_bookings)} conflicting bookings for worker {worker_id}")
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'bookings': conflict_bookings,
                    'count': len(conflict_bookings)
                }, cls=DecimalEncoder)
            }
        
        # ---------------------------------------------------------------
        # Standard mode: paginated list of all worker bookings
        # ---------------------------------------------------------------
        # Build query parameters
        query_params = {
            'IndexName': 'workerId-startDate-index',
            'KeyConditionExpression': Key('workerId').eq(worker_id),
            'Limit': limit,
            'ScanIndexForward': False  # Most recent first
        }
        
        # Add status filter
        if status_filter:
            query_params['FilterExpression'] = Attr('status').eq(status_filter) & Attr('bookingType').eq('booking')
        else:
            query_params['FilterExpression'] = Attr('bookingType').eq('booking')
        
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
        
        # Enrich with listing and company details
        enriched_bookings = enrich_bookings_with_details(bookings)
        
        # Calculate statistics (as per swagger)
        stats = {
            'total': len(enriched_bookings),
            'pending': sum(1 for b in enriched_bookings if b.get('status') == 'pending'),
            'confirmed': sum(1 for b in enriched_bookings if b.get('status') == 'confirmed'),
            'rejected': sum(1 for b in enriched_bookings if b.get('status') == 'rejected'),
            'completed': sum(1 for b in enriched_bookings if b.get('status') == 'completed')
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
        print(f"Error listing worker bookings: {str(e)}")
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