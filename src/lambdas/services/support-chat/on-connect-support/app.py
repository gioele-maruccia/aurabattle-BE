"""
Lambda: Support Chat WebSocket $connect

Salva connectionId a DynamoDB quando client si connette al WebSocket.
"""

import json
import os
import time
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')

CONNECTION_MANAGER_TABLE_NAME = os.environ['CONNECTION_MANAGER_TABLE_NAME']
connection_table = dynamodb.Table(CONNECTION_MANAGER_TABLE_NAME)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle WebSocket connection per support chat.
    
    Event structure:
    {
        "requestContext": {
            "connectionId": "abc123",
            "authorizer": {
                "sub": "user-id-from-cognito"
            }
        }
    }
    """
    
    try:
        # Estrai connectionId e userId
        connection_id = event['requestContext']['connectionId']
        
        authorizer = event['requestContext'].get('authorizer', {})
        user_id = authorizer.get('sub') or authorizer.get('principalId')
        
        if not user_id:
            print("ERROR: No user_id found in authorizer")
            return {
                'statusCode': 401,
                'body': json.dumps({'error': 'Unauthorized'})
            }
        
        # Salva connection a DynamoDB con TTL (24 ore)
        ttl = int(time.time()) + 86400
        
        connection_table.put_item(
            Item={
                'connectionId': connection_id,
                'userId': user_id,
                'chatType': 'support',  # Marker per support chat
                'connectedAt': int(time.time()),
                'ttl': ttl
            }
        )
        
        print(f"Support chat connection saved: {connection_id} for user {user_id}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Connected to support chat'})
        }
        
    except KeyError as e:
        print(f"ERROR: Missing required field in event: {str(e)}")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Missing field: {str(e)}'})
        }
        
    except ClientError as e:
        print(f"ERROR: DynamoDB error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }
        
    except Exception as e:
        print(f"ERROR: Unexpected error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }
