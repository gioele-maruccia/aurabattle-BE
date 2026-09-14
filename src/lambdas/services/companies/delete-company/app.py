"""
Delete Company Profile Handler

Soft deletes a company profile by setting status to 'deleted'.
This preserves data for audit/recovery while hiding from public view.
"""

import json
import os
import boto3
from datetime import datetime
from decimal import Decimal

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    DELETE /companies/{userId}
    Soft delete a company profile (sets status to 'deleted')
    
    Returns:
        200: Company deleted successfully
        403: User not authorized to delete this company
        404: Company not found
        500: Internal server error
    """
    try:
        # Get user ID from Cognito authorizer
        claims = event['requestContext']['authorizer']['claims']
        user_id = claims['sub']
        
        # Get userId from path parameters
        path_user_id = event['pathParameters']['userId']
        
        print(f"Delete company request from user: {user_id} for path user: {path_user_id}")
        
        # Authorization check: user can only delete their own company
        if user_id != path_user_id:
            print(f"Authorization failed: user {user_id} cannot delete company for user {path_user_id}")
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Forbidden',
                    'message': 'You can only delete your own company profile'
                })
            }
        
        # Check if company exists
        try:
            response = table.get_item(Key={'userId': user_id})
            if 'Item' not in response:
                print(f"Company not found for user: {user_id}")
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
            
            company = response['Item']
            company_id = company['companyId']
            
            # Check if already deleted
            if company.get('status') == 'deleted':
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'message': 'Company already deleted',
                        'companyId': company_id
                    })
                }
            
        except Exception as e:
            print(f"Error fetching company: {str(e)}")
            raise
        
        # Soft delete: update status to 'deleted'
        now = datetime.utcnow().isoformat() + 'Z'
        
        update_response = table.update_item(
            Key={'userId': user_id},
            UpdateExpression='SET #status = :deleted, deletedAt = :now, updatedAt = :now',
            ExpressionAttributeNames={
                '#status': 'status'
            },
            ExpressionAttributeValues={
                ':deleted': 'deleted',
                ':now': now
            },
            ReturnValues='ALL_NEW'
        )
        
        print(f"Company soft deleted successfully: {company_id}")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Company deleted successfully',
                'companyId': company_id,
                'deletedAt': now,
                'note': 'This is a soft delete. Contact support within 30 days to restore your profile.'
            }, cls=DecimalEncoder)
        }
        
    except KeyError as e:
        print(f"Missing required field: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'message': f'Missing required field: {str(e)}'
            })
        }
    except Exception as e:
        print(f"Unexpected error deleting company: {str(e)}")
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
                'message': 'An unexpected error occurred'
            })
        }