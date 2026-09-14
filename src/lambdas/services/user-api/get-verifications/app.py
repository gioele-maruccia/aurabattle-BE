import json
import os
import boto3

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        response = table.get_item(
            Key={'user_id': user_id},
            ProjectionExpression='verifications'
        )
        
        if 'Item' not in response:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Profile not found'})
            }
        
        verifications = response['Item'].get('verifications', {
            'email_verified': False,
            'phone_verified': False,
            'identity_verified': False,
            'payment_verified': False
        })
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(verifications)
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': str(e)})
        }