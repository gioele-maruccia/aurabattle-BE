"""
Delete Blackout Period Handler

This Lambda function deletes a blackout period.
Company owner only.
"""

import json
import os
import boto3
from decimal import Decimal

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
    
    DELETE /bookings/blackout/{bookingId}
    
    Deletes a blackout period. Only the company owner can delete.
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
                    'message': 'Only company users can delete blackout periods'
                })
            }
        
        # Get blackout ID from path
        blackout_id = event['pathParameters']['bookingId']
        
        # Get blackout
        try:
            blackout_response = bookings_table.get_item(Key={'bookingId': blackout_id})
            if 'Item' not in blackout_response:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Not Found',
                        'message': 'Blackout period not found'
                    })
                }
            
            blackout = blackout_response['Item']
            
            # Verify it's a blackout, not a regular booking
            if blackout.get('bookingType') != 'blackout':
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'This is not a blackout period'
                    })
                }
            
        except Exception as e:
            print(f"Error fetching blackout: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error fetching blackout period'
                })
            }
        
        # Verify user owns the listing's company
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
            
            if company['companyId'] != blackout['companyId']:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'You can only delete blackouts for your own listings'
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
        
        # Delete blackout
        try:
            bookings_table.delete_item(Key={'bookingId': blackout_id})
            print(f"Blackout deleted: {blackout_id}")
            
        except Exception as e:
            print(f"Error deleting blackout: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error deleting blackout period'
                })
            }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Blackout period deleted successfully',
                'blackoutId': blackout_id
            })
        }
        
    except Exception as e:
        print(f"Error deleting blackout: {str(e)}")
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
                'message': 'An error occurred while deleting the blackout period'
            })
        }
