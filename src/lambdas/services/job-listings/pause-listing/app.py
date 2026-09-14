import json
import os
from datetime import datetime, timezone
from decimal import Decimal
import boto3

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])

# Helper function to convert Decimal to float for JSON response
def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def lambda_handler(event, context):
    """
    Pause a job listing (change status from published to paused)
    
    PATCH /listings/{listingId}/pause
    
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
                    'message': 'Only company users can pause job listings'
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
            
            company_id = company_response['Item']['companyId']
            
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
        
        # Get job listing and verify ownership
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
            
            # Verify ownership
            if listing['companyId'] != company_id:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'You can only pause your own job listings'
                    })
                }
            
            # Check current status
            current_status = listing.get('status')
            if current_status == 'paused':
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'Job listing is already paused'
                    })
                }
            
            if current_status != 'published':
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': f'Can only pause published listings. Current status: {current_status}'
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
        
        # Update listing status to paused
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        try:
            update_response = job_listings_table.update_item(
                Key={'listingId': listing_id},
                UpdateExpression='SET #status = :status, updatedAt = :updatedAt',
                ExpressionAttributeNames={
                    '#status': 'status'
                },
                ExpressionAttributeValues={
                    ':status': 'paused',
                    ':updatedAt': now
                },
                ReturnValues='ALL_NEW'
            )
            
            updated_listing = update_response['Attributes']
            
        except Exception as e:
            print(f"Error updating listing: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error pausing job listing'
                })
            }
        
        # Convert Decimal to float for JSON response
        response_listing = json.loads(json.dumps(updated_listing, default=decimal_default))
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Job listing paused successfully',
                'listing': response_listing
            })
        }
        
    except KeyError as e:
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
        print(f"Error pausing listing: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': 'An error occurred while pausing the job listing'
            })
        }