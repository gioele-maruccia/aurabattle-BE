"""
Create Review Handler

This Lambda function creates a new review for a completed booking.
Both workers can review companies and companies can review workers.

Review data:
- For worker->company: rates flexibility, work climate, work conditions
- For company->worker: rates reliability, team working

Both types include optional text description and reviewer profile info.
"""

import json
import os
import sys
import boto3
import uuid
from datetime import datetime, timezone
from decimal import Decimal

sys.path.append('/opt/python')

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
reviews_table = dynamodb.Table(os.environ['REVIEWS_TABLE_NAME'])
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE_NAME'])
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
    
    POST /bookings/{bookingId}/review
    
    Required fields in body:
    - rating1: First rating (1-5) - flexibility/reliability
    - rating2: Second rating (1-5) - climate/team working
    - description: Optional text description
    
    Authorization: Cognito JWT (worker or company user)
    """
    
    try:
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Get booking ID from path
        booking_id = event['pathParameters']['bookingId']
        
        # Parse request body
        body = json.loads(event['body'])
        
        # Validate required fields
        if 'rating1' not in body or 'rating2' not in body:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4056,
                    'error': 'Bad Request',
                    'message': 'Missing required fields: rating1, rating2'
                })
            }
        
        # Validate rating values
        try:
            rating1 = int(body['rating1'])
            rating2 = int(body['rating2'])
            
            if not (1 <= rating1 <= 5) or not (1 <= rating2 <= 5):
                raise ValueError("Ratings must be between 1 and 5")
        except (ValueError, TypeError) as e:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4055,
                    'error': 'Bad Request',
                    'message': f'Invalid ratings: {str(e)}'
                })
            }
        
        description = body.get('description', '').strip() if body.get('description') else ''
        
        # Get booking details
        try:
            booking_response = bookings_table.get_item(Key={'bookingId': booking_id})
            if 'Item' not in booking_response:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4059,
                        'error': 'Not Found',
                        'message': 'Booking not found'
                    })
                }
            
            booking = booking_response['Item']
            
            # Check if booking is completed
            if booking.get('status') != 'completed':
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4057,
                        'error': 'Bad Request',
                        'message': f"Can only review completed bookings. Current status: {booking.get('status')}"
                    })
                }
            
        except Exception as e:
            print(f"Error fetching booking: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5015,
                    'error': 'Internal Server Error',
                    'message': 'Error fetching booking'
                })
            }
        
        # Determine if reviewer is worker or company
        worker_id = booking.get('workerId')
        company_id = booking.get('companyId')
        
        is_worker = 'workers' in user_groups
        is_company = 'companies' in user_groups
        
        if is_worker and user_id == worker_id:
            # Worker reviewing company
            target_id = company_id
            review_type = 'worker-to-company'
            reviewer_name_field = 'firstName'
            reviewer_profile_table = user_profiles_table
        elif is_company and user_id == company_id:
            # Company reviewing worker
            target_id = worker_id
            review_type = 'company-to-worker'
            reviewer_name_field = 'companyName'
            reviewer_profile_table = companies_table
        else:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 4058,
                    'error': 'Forbidden',
                    'message': 'You can only review your own bookings'
                })
            }
        
        # Check if review already exists for this booking and reviewer
        try:
            query_response = reviews_table.query(
                IndexName='reviewerId-createdAt-index',
                KeyConditionExpression='reviewerId = :reviewer_id',
                FilterExpression='bookingId = :booking_id',
                ExpressionAttributeValues={
                    ':reviewer_id': user_id,
                    ':booking_id': booking_id
                }
            )
            
            if query_response.get('Items'):
                return {
                    'statusCode': 409,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'code': 4058,
                        'error': 'Bad Request',
                        'message': 'You have already reviewed this booking'
                    })
                }
        except Exception as e:
            print(f"Error checking existing review: {str(e)}")
            # Continue anyway - it's not critical
        
        # Get reviewer profile info
        reviewer_first_name = 'Anonymous'
        reviewer_photo_url = None
        
        try:
            if is_worker:
                profile_response = user_profiles_table.get_item(Key={'userId': user_id})
                if 'Item' in profile_response:
                    profile = profile_response['Item']
                    reviewer_first_name = profile.get('firstName', 'Anonymous')
                    reviewer_photo_url = profile.get('photoUrl')
            else:  # is_company
                profile_response = companies_table.get_item(Key={'companyId': company_id})
                if 'Item' in profile_response:
                    profile = profile_response['Item']
                    reviewer_first_name = profile.get('companyName', 'Anonymous')
                    reviewer_photo_url = profile.get('logoUrl')
        except Exception as e:
            print(f"Warning: Could not fetch reviewer profile: {str(e)}")
            # Continue with defaults
        
        # Create review record
        review_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        average_rating = (rating1 + rating2) / 2
        
        review_item = {
            'reviewId': review_id,
            'bookingId': booking_id,
            'targetId': target_id,
            'reviewerId': user_id,
            'reviewType': review_type,
            'rating1': Decimal(str(rating1)),
            'rating2': Decimal(str(rating2)),
            'averageRating': Decimal(str(average_rating)),
            'description': description,
            'reviewerFirstName': reviewer_first_name,
            'reviewerPhotoUrl': reviewer_photo_url if reviewer_photo_url else None,
            'createdAt': now,
            'updatedAt': now
        }
        
        # Save to DynamoDB
        try:
            reviews_table.put_item(Item=review_item)
            print(f"Review created successfully: {review_id}")
        except Exception as e:
            print(f"Error saving review: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'code': 5015,
                    'error': 'Internal Server Error',
                    'message': 'Error saving review'
                })
            }
        
        # Return created review
        response_item = {
            'reviewId': review_id,
            'bookingId': booking_id,
            'targetId': target_id,
            'reviewType': review_type,
            'rating1': int(rating1),
            'rating2': int(rating2),
            'averageRating': float(average_rating),
            'description': description,
            'reviewerFirstName': reviewer_first_name,
            'reviewerPhotoUrl': reviewer_photo_url,
            'createdAt': now
        }
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 3015,
                **response_item
            }, cls=DecimalEncoder)
        }
        
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'code': 4056,
                'error': 'Bad Request',
                'message': 'Invalid JSON body'
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
                'code': 5015,
                'error': 'Internal Server Error',
                'message': str(e)
            })
        }
