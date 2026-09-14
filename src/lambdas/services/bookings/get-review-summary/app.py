"""
Get Review Summary Handler

This Lambda function returns a summary of all reviews for a specific target.
Returns only the average ratings across all reviews.

Example response:
{
  "targetId": "company-123",
  "reviewCount": 15,
  "averageRating": 4.2,
  "workerReviewsCount": 10,
  "companyReviewsCount": 5
}
"""

import json
import os
import sys
import boto3
from decimal import Decimal

sys.path.append('/opt/python')

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
reviews_table = dynamodb.Table(os.environ['REVIEWS_TABLE_NAME'])


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /reviews/target/{targetId}/summary
    
    Path parameters:
    - targetId: company_id or worker_id
    
    Returns:
    - Average rating across all reviews
    - Number of reviews
    - Breakdown by review type
    """
    
    try:
        # Get target ID from path
        target_id = event['pathParameters']['targetId']
        
        if not target_id or target_id.strip() == '':
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4061,
                    'error': 'Bad Request',
                    'message': 'targetId is required'
                })
            }
        
        # Query all reviews for this target
        try:
            query_response = reviews_table.query(
                IndexName='targetId-createdAt-index',
                KeyConditionExpression='targetId = :target_id',
                ExpressionAttributeValues={
                    ':target_id': target_id
                }
            )
            
            reviews = query_response.get('Items', [])
            
            if not reviews:
                # No reviews found
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 3017,
                        'targetId': target_id,
                        'reviewCount': 0,
                        'averageRating': None,
                        'workerReviewsCount': 0,
                        'companyReviewsCount': 0
                    })
                }
            
            # Calculate averages
            total_average = 0
            worker_to_company_count = 0
            company_to_worker_count = 0
            
            for review in reviews:
                avg = float(review.get('averageRating', 0))
                total_average += avg
                
                if review.get('reviewType') == 'worker-to-company':
                    worker_to_company_count += 1
                elif review.get('reviewType') == 'company-to-worker':
                    company_to_worker_count += 1
            
            final_average = total_average / len(reviews) if reviews else 0
            
            response = {
                'targetId': target_id,
                'reviewCount': len(reviews),
                'averageRating': round(final_average, 2),
                'workerReviewsCount': worker_to_company_count,
                'companyReviewsCount': company_to_worker_count
            }
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 3016,
                    **response
                }, cls=DecimalEncoder)
            }
            
        except Exception as e:
            print(f"Error querying reviews: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5016,
                    'error': 'Internal Server Error',
                    'message': 'Error fetching reviews'
                })
            }
        
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 5016,
                'error': 'Internal Server Error',
                'message': str(e)
            })
        }
