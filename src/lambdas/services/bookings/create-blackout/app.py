"""
Create Blackout Period Handler

This Lambda function creates a blackout period for a job listing.
Blackout periods prevent bookings during specific dates (holidays, maintenance, etc.)

Company owner only.
"""

import json
import os
import uuid
import boto3
from datetime import datetime, timezone
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


def check_existing_bookings(listing_id, start_date, end_date):
    """
    Check if there are confirmed bookings in the blackout period
    
    Args:
        listing_id: Job listing ID
        start_date: Blackout start date (ISO string)
        end_date: Blackout end date (ISO string)
        
    Returns:
        list: List of conflicting bookings
    """
    try:
        # Query bookings by listing and date range
        response = bookings_table.query(
            IndexName='listingId-startDate-index',
            KeyConditionExpression=Key('listingId').eq(listing_id) & Key('startDate').lte(end_date),
            FilterExpression=Attr('endDate').gte(start_date) & 
                           Attr('status').eq('confirmed') & 
                           Attr('bookingType').eq('booking')
        )
        
        return response.get('Items', [])
        
    except Exception as e:
        print(f"Error checking existing bookings: {str(e)}")
        return []


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    POST /bookings/blackout
    
    Required fields in body:
    - listingId: Job listing to apply blackout
    - startDate: Blackout start date (ISO 8601)
    - endDate: Blackout end date (ISO 8601)
    - reason: Reason for blackout (optional)
    
    Authorization: Cognito JWT (company owner only)
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
                    'message': 'Only company users can create blackout periods'
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
                    'error': 'Bad Request',
                    'message': f'Missing required fields: {", ".join(missing_fields)}'
                })
            }
        
        listing_id = body['listingId']
        start_date = body['startDate']
        end_date = body['endDate']
        reason = body.get('reason', 'Unavailable')
        
        # Validate dates
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            
            if end_dt <= start_dt:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
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
        
        # Verify user owns the listing's company
        try:
            # Query Companies table using userId-index (GSI)
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
                        'error': 'Forbidden',
                        'message': 'Company profile not found'
                    })
                }
            
            company = company_response['Items'][0]
            
            if company['companyId'] != listing['companyId']:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'You can only create blackouts for your own listings'
                    })
                }
                
        except Exception as e:
            print(f"Error verifying ownership (GSI query): {str(e)}")
            # Fallback: try direct get_item if userId is partition key
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
                
                if company['companyId'] != listing['companyId']:
                    return {
                        'statusCode': 403,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'error': 'Forbidden',
                            'message': 'You can only create blackouts for your own listings'
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
                        'error': 'Internal Server Error',
                        'message': 'Error verifying ownership'
                    })
                }
        
        # Validate dates are within listing period
        listing_start = datetime.fromisoformat(listing['startDate'].replace('Z', '+00:00'))
        listing_end = datetime.fromisoformat(listing['endDate'].replace('Z', '+00:00'))
        
        if start_dt < listing_start or end_dt > listing_end:
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
        
        # Check for existing confirmed bookings in this period
        conflicting_bookings = check_existing_bookings(listing_id, start_date, end_date)
        
        if conflicting_bookings:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Cannot create blackout: {len(conflicting_bookings)} confirmed booking(s) exist in this period',
                    'conflictingBookings': [b['bookingId'] for b in conflicting_bookings]
                })
            }
        
        # Generate IDs and timestamps
        blackout_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # Create blackout item (stored as special booking type)
        # Note: workerId is set to company userId (Cognito sub) for blackouts to satisfy GSI requirements
        # and allow querying blackouts by company using workerId-startDate-index
        blackout = {
            'bookingId': blackout_id,
            'bookingType': 'blackout',  # Distinguishes from regular bookings
            'listingId': listing_id,
            'companyId': listing['companyId'],
            'workerId': company['userId'],  # Use company's userId (Cognito sub) for GSI compatibility
            'startDate': start_date,
            'endDate': end_date,
            'status': 'blocked',  # Blackouts are always blocked
            'reason': reason,
            'createdBy': user_id,
            'listing': {
                'title': listing.get('title', ''),
                'category': listing.get('category', '')
            },
            'createdAt': now,
            'updatedAt': now
        }
        
        # Save to DynamoDB
        bookings_table.put_item(Item=blackout)
        
        print(f"Blackout created: {blackout_id} for listing {listing_id}")
        
        # Convert Decimal back to float for JSON response
        response_blackout = json.loads(json.dumps(blackout, cls=DecimalEncoder))
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
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