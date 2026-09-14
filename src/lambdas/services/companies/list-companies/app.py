"""
List Companies Handler (PLACEHOLDER)

This Lambda function lists all companies (for backoffice use).
"""

import json
import os
import boto3
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
    
    GET /companies?limit=20&lastKey=xxx
    List all companies with pagination
    
    Returns:
        200: Companies list
        500: Internal server error
    """
    try:
        # Get query parameters
        query_params = event.get('queryStringParameters') or {}
        limit = int(query_params.get('limit', 20))
        last_key = query_params.get('lastKey')
        
        print(f"Listing companies with limit: {limit}")
        
        # Scan parameters
        scan_kwargs = {
            'Limit': limit
        }
        
        # Add pagination if lastKey provided
        if last_key:
            # Decode lastKey (in production, use base64 decode)
            scan_kwargs['ExclusiveStartKey'] = {'userId': last_key}
        
        # Scan table
        response = table.scan(**scan_kwargs)
        
        companies = response.get('Items', [])
        last_evaluated_key = response.get('LastEvaluatedKey')
        
        result = {
            'companies': companies,
            'count': len(companies)
        }
        
        if last_evaluated_key:
            result['lastKey'] = last_evaluated_key['userId']
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result, cls=DecimalEncoder)
        }
        
    except Exception as e:
        print(f"Error listing companies: {str(e)}")
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