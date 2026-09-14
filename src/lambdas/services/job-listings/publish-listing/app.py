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
    Publish a job listing (change status from draft to published)
    
    PATCH /listings/{listingId}/publish
    
    Authorization: Cognito JWT (company owner only)
    """
    
    print("[PUBLISH] ===== START PUBLISH LISTING REQUEST =====")
    
    try:
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        print(f"[PUBLISH] User ID: {user_id}")
        print(f"[PUBLISH] User groups: {user_groups}")
        
        # Check if user is in 'companies' group
        if 'companies' not in user_groups:
            print("[PUBLISH] ✗ User not in companies group")
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Forbidden',
                    'message': 'Only company users can publish job listings'
                })
            }
        
        # Get listingId from path parameters
        listing_id = event['pathParameters']['listingId']
        print(f"[PUBLISH] Listing ID: {listing_id}")
        
        # Get company info to verify ownership
        print(f"[PUBLISH] Fetching company for user {user_id}...")
        try:
            company_response = companies_table.get_item(Key={'userId': user_id})
            if 'Item' not in company_response:
                print("[PUBLISH] ✗ Company profile not found")
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
            print(f"[PUBLISH] ✓ Company ID: {company_id}")
            
        except Exception as e:
            print(f"[PUBLISH] ✗ Error fetching company: {str(e)}")
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
        print(f"[PUBLISH] Fetching listing {listing_id}...")
        try:
            listing_response = job_listings_table.get_item(Key={'listingId': listing_id})
            
            if 'Item' not in listing_response:
                print(f"[PUBLISH] ✗ Listing {listing_id} not found")
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
            print(f"[PUBLISH] ✓ Listing found")
            print(f"[PUBLISH]   - Title: {listing.get('title')}")
            print(f"[PUBLISH]   - Company ID: {listing.get('companyId')}")
            print(f"[PUBLISH]   - Current status: {listing.get('status')}")
            print(f"[PUBLISH]   - CCNL Type: {listing.get('ccnlType', 'turismo')}")
            
            # Verify ownership
            if listing['companyId'] != company_id:
                print(f"[PUBLISH] ✗ Ownership verification failed")
                print(f"[PUBLISH]   Listing company: {listing['companyId']}")
                print(f"[PUBLISH]   User company: {company_id}")
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'You can only publish your own job listings'
                    })
                }
            
            # Check current status
            current_status = listing.get('status')
            print(f"[PUBLISH] Current status check: {current_status}")
            
            if current_status == 'published':
                print("[PUBLISH] ✗ Listing already published")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'Job listing is already published'
                    })
                }
            
            if current_status not in ['draft', 'paused']:
                print(f"[PUBLISH] ✗ Invalid status for publishing: {current_status}")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': f'Cannot publish listing with status: {current_status}'
                    })
                }
            
            print(f"[PUBLISH] ✓ Status valid for publishing")
            
        except Exception as e:
            print(f"[PUBLISH] ✗ Error fetching listing: {str(e)}")
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
        
        # Update listing status to published
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        print(f"[PUBLISH] Updating listing to published status...")
        print(f"[PUBLISH] Timestamp: {now}")
        
        try:
            update_response = job_listings_table.update_item(
                Key={'listingId': listing_id},
                UpdateExpression='SET #status = :status, publishedAt = :publishedAt, updatedAt = :updatedAt',
                ExpressionAttributeNames={
                    '#status': 'status'
                },
                ExpressionAttributeValues={
                    ':status': 'published',
                    ':publishedAt': now,
                    ':updatedAt': now
                },
                ReturnValues='ALL_NEW'
            )
            
            updated_listing = update_response['Attributes']
            print(f"[PUBLISH] ✓ Listing published successfully")
            print(f"[PUBLISH]   - Status: {updated_listing.get('status')}")
            print(f"[PUBLISH]   - Published at: {updated_listing.get('publishedAt')}")
            
        except Exception as e:
            print(f"[PUBLISH] ✗ Error updating listing: {str(e)}")
            print(f"[PUBLISH] Error type: {type(e).__name__}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error publishing job listing'
                })
            }
        
        # Convert Decimal to float for JSON response
        response_listing = json.loads(json.dumps(updated_listing, default=decimal_default))
        
        print(f"[PUBLISH] ===== PUBLISH COMPLETED SUCCESSFULLY =====")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Job listing published successfully',
                'listing': response_listing
            })
        }
        
    except KeyError as e:
        print(f"[PUBLISH] ✗ KeyError: {str(e)}")
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
        print(f"[PUBLISH] ✗ Unexpected error: {str(e)}")
        print(f"[PUBLISH] Error type: {type(e).__name__}")
        import traceback
        print(f"[PUBLISH] Traceback: {traceback.format_exc()}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': 'An error occurred while publishing the job listing'
            })
        }