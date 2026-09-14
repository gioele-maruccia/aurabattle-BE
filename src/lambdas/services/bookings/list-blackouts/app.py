"""
List Blackouts Handler

This Lambda function lists all blackout periods for a job listing.
Used by workers to see unavailable dates before booking.

Public endpoint - no authentication required.
"""

import json
import os
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
bookings_table = dynamodb.Table(os.environ['BOOKINGS_TABLE_NAME'])


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /bookings/blackout/listing/{listingId}
    
    Returns all blackout periods for the specified listing.
    Public endpoint for workers to check availability.
    """
    
    try:
        # Get listing ID from path
        listing_id = event['pathParameters']['listingId']
        
        print(f"Listing blackouts for listing: {listing_id}")
        
        # Query all blackouts for this listing
        try:
            response = bookings_table.query(
                IndexName='listingId-startDate-index',
                KeyConditionExpression=Key('listingId').eq(listing_id),
                FilterExpression=Attr('bookingType').eq('blackout')
            )
            
            blackouts = response.get('Items', [])
            
            # Sort by start date
            blackouts.sort(key=lambda x: x.get('startDate', ''))
            
        except Exception as e:
            print(f"Error fetching blackouts: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error fetching blackout periods'
                })
            }
        
        # Format blackouts for response
        formatted_blackouts = [
            {
                'blackoutId': b['bookingId'],
                'listingId': b['listingId'],
                'startDate': b['startDate'],
                'endDate': b['endDate'],
                'reason': b.get('reason', 'Unavailable'),
                'createdAt': b.get('createdAt')
            }
            for b in blackouts
        ]
        
        response_body = {
            'listingId': listing_id,
            'blackouts': formatted_blackouts,
            'count': len(formatted_blackouts)
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=300'  # Cache for 5 minutes
            },
            'body': json.dumps(response_body, cls=DecimalEncoder)
        }
        
    except Exception as e:
        print(f"Error listing blackouts: {str(e)}")
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
                'message': 'An error occurred while listing blackouts'
            })
        }