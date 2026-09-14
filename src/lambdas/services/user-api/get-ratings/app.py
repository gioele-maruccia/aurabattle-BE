import json
import os
import boto3
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

# ✅ Helper per convertire Decimal in float
def decimal_to_float(obj):
    """Converte Decimal in float per JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    return obj

def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Get user profile
        response = table.get_item(Key={'user_id': user_id})
        
        if 'Item' not in response:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Profile not found'})
            }
        
        profile = response['Item']
        
        # Get ratings (con default se non esistono)
        ratings = profile.get('ratings', {
            'average': 0,
            'count': 0,
            'as_worker': {'average': 0, 'count': 0},
            'as_employer': {'average': 0, 'count': 0}
        })
        
        # ✅ Converti Decimal in float
        ratings = decimal_to_float(ratings)
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(ratings)
        }
        
    except Exception as e:
        print(f"Error getting ratings: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': str(e)})
        }