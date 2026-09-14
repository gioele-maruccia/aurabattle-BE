"""
Lambda: Support Chat WebSocket $disconnect

Rimuove connectionId dal DynamoDB quando client si disconnette.
"""

import json
import os
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')

CONNECTION_MANAGER_TABLE_NAME = os.environ['CONNECTION_MANAGER_TABLE_NAME']
connection_table = dynamodb.Table(CONNECTION_MANAGER_TABLE_NAME)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle WebSocket disconnect per support chat.
    
    Event structure:
    {
        "requestContext": {
            "connectionId": "abc123"
        }
    }
    """
    
    try:
        connection_id = event['requestContext']['connectionId']
        
        # Rimuovi connection da DynamoDB
        connection_table.delete_item(
            Key={'connectionId': connection_id}
        )
        
        print(f"Support chat connection removed: {connection_id}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Disconnected from support chat'})
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
