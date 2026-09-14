"""
List Reviews Handler

This Lambda function returns all reviews for a specific target with complete details.
Includes reviewer info, ratings, descriptions, and averages.

Example response:
{
  "targetId": "company-123",
  "reviewCount": 15,
  "averageRating": 4.2,
  "reviews": [
    {
      "reviewId": "review-123",
      "bookingId": "booking-123",
      "reviewType": "worker-to-company",
      "rating1": 5,
      "rating2": 4,
      "averageRating": 4.5,
      "description": "Great company!",
      "reviewerFirstName": "John",
      "reviewerPhotoUrl": "https://...",
      "createdAt": "2026-01-28T10:30:00Z"
    }
  ]
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
    
    GET /reviews/target/{targetId}
    
    Query parameters:
    - limit: Maximum number of reviews to return (default 50, max 100)
    - lastKey: For pagination - the reviewId of the last item from previous request
    
    Path parameters:
    - targetId: company_id or worker_id
    
    Returns:
    - All reviews for the target with complete details
    - Pagination support
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
                    'code': 4062,
                    'error': 'Bad Request',
                    'message': 'targetId is required'
                })
            }
        
        # Get query parameters for pagination
        query_params = event.get('queryStringParameters') or {}
        try:
            limit = int(query_params.get('limit', '50'))
            if limit < 1 or limit > 100:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4063,
                        'error': 'Bad Request',
                        'message': 'Invalid pagination parameters. Limit must be 1-100'
                    })
                }
            limit = min(limit, 100)
        except ValueError:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4063,
                    'error': 'Bad Request',
                    'message': 'Invalid pagination parameters. Limit must be 1-100'
                })
            }
        
        # Query all reviews for this target
        try:
            query_kwargs = {
                'IndexName': 'targetId-createdAt-index',
                'KeyConditionExpression': 'targetId = :target_id',
                'ExpressionAttributeValues': {
                    ':target_id': target_id
                },
                'Limit': limit,
                'ScanIndexForward': False  # Most recent first
            }
            
            # Add pagination if provided
            if query_params.get('lastKey'):
                try:
                    last_key = json.loads(query_params.get('lastKey'))
                    query_kwargs['ExclusiveStartKey'] = last_key
                except:
                    return {
                        'statusCode': 400,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'code': 4064,
                            'error': 'Bad Request',
                            'message': 'Invalid lastKey pagination token'
                        })
                    }
            
            query_response = reviews_table.query(**query_kwargs)
            
            reviews = query_response.get('Items', [])
            
            # Format reviews for response
            formatted_reviews = []
            for review in reviews:
                formatted_review = {
                    'reviewId': review.get('reviewId'),
                    'bookingId': review.get('bookingId'),
                    'reviewType': review.get('reviewType'),
                    'rating1': int(review.get('rating1', 0)),
                    'rating2': int(review.get('rating2', 0)),
                    'averageRating': float(review.get('averageRating', 0)),
                    'description': review.get('description', ''),
                    'reviewerFirstName': review.get('reviewerFirstName', 'Anonymous'),
                    'reviewerPhotoUrl': review.get('reviewerPhotoUrl'),
                    'createdAt': review.get('createdAt')
                }
                formatted_reviews.append(formatted_review)
            
            # Calculate overall average
            if formatted_reviews:
                overall_average = sum(r['averageRating'] for r in formatted_reviews) / len(formatted_reviews)
                response_code = 3018
            else:
                overall_average = None
                response_code = 3019
            
            response = {
                'code': response_code,
                'targetId': target_id,
                'reviewCount': len(formatted_reviews),
                'averageRating': round(overall_average, 2) if overall_average else None,
                'reviews': formatted_reviews
            }
            
            # Add pagination token if there are more results
            if 'LastEvaluatedKey' in query_response:
                response['nextPageToken'] = json.dumps(query_response['LastEvaluatedKey'])
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps(response, cls=DecimalEncoder)
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
                    'code': 5017,
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
                'code': 5017,
                'error': 'Internal Server Error',
                'message': str(e)
            })
        }
