"""
List Listing Bookings Handler

This Lambda function lists all bookings for a specific job listing.
Shows all applications/bookings for that listing.

Company owner only.
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


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /bookings/listing/{listingId}?status=pending&limit=20
    
    Query Parameters:
    - status: Filter by status (pending, confirmed, rejected, cancelled)
    - limit: Items per page (default: 20, max: 50)
    - lastKey: Pagination token
    
    Returns:
        200: List of listing bookings
        403: Forbidden (trying to access another company's listing)
        404: Listing not found
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
                    'code': 4144,
                    'error': 'Forbidden',
                    'message': 'Only companies can access this endpoint'
                })
            }
        
        # Get listing ID from path
        listing_id = event['pathParameters']['listingId']
        
        # Get listing to verify ownership
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
                        'message': 'Job listing not found',
                        'code': 4145
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
                    'message': 'Error fetching listing',
                    'code': 5037
                })
            }
        
        # Verify user owns the listing's company
        try:
            company_response = companies_table.get_item(Key={'companyId': user_id})
            if 'Item' not in company_response:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'Company profile not found',
                        'code': 4068
                    })
                }
            
            company = company_response['Item']

            if company['companyId'] != listing['companyId']:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'You can only view bookings for your own listings',
                        'code': 4068
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
                    'message': 'Error verifying ownership',
                    'code': 5037
                })
            }
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        status_filter = params.get('status')
        limit = min(int(params.get('limit', 20)), 50)
        last_key = params.get('lastKey')
        
        print(f"List bookings for listing: {listing_id}, status: {status_filter}")
        
        # Build query parameters
        query_params = {
            'IndexName': 'listingId-startDate-index',
            'KeyConditionExpression': Key('listingId').eq(listing_id),
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
                    'message': 'Error querying bookings',
                    'code': 5037
                })
            }
        
        # Calculate statistics
        stats = {
            'total': len(bookings),
            'pending': sum(1 for b in bookings if b.get('status') == 'pending'),
            'confirmed': sum(1 for b in bookings if b.get('status') == 'confirmed'),
            'rejected': sum(1 for b in bookings if b.get('status') == 'rejected'),
            'cancelled': sum(1 for b in bookings if b.get('status') == 'cancelled')
        }
        
        # Build pagination cursor
        next_cursor = None
        if response.get('LastEvaluatedKey'):
            import base64
            cursor_json = json.dumps(response['LastEvaluatedKey'])
            next_cursor = base64.b64encode(cursor_json.encode('utf-8')).decode('utf-8')
        
        # Build response
        response_body = {
            'listingId': listing_id,
            'listingTitle': listing.get('title'),
            'listingStatus': listing.get('status'),
            'positions': {
                'total': int(listing.get('positions', 1)),
                'filled': int(listing.get('positionsFilled', 0)),
                'available': int(listing.get('positions', 1)) - int(listing.get('positionsFilled', 0))
            },
            'bookings': bookings,
            'count': len(bookings),
            'stats': stats,
            'hasMore': next_cursor is not None,
            'nextCursor': next_cursor,
            'code': 3039
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
        print(f"Error listing listing bookings: {str(e)}")
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
                'message': 'An error occurred while listing bookings',
                'code': 5037
            })
        }