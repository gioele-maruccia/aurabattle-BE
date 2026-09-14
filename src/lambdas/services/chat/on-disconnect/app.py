"""
Lambda handler for WebSocket $disconnect route.
Removes connectionId from DynamoDB ConnectionManager table.
"""

import json
import os
from typing import Any, Dict
from aws_lambda_powertools import Logger

import boto3
from botocore.exceptions import ClientError

logger = Logger()
dynamodb = boto3.resource('dynamodb')

CONNECTION_MANAGER_TABLE_NAME = os.environ['CONNECTION_MANAGER_TABLE_NAME']
connection_table = dynamodb.Table(CONNECTION_MANAGER_TABLE_NAME)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle WebSocket disconnection.
    
    Event structure:
    {
        "requestContext": {
            "connectionId": "abc123"
        }
    }
    """
    logger.info("WebSocket disconnect event", extra={"event": event})
    
    try:
        # Extract connectionId
        connection_id = event['requestContext']['connectionId']
        
        # Delete connection from DynamoDB
        connection_table.delete_item(
            Key={
                'connectionId': connection_id
            }
        )
        
        logger.info(
            "Connection removed successfully",
            extra={"connectionId": connection_id}
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Disconnected'})
        }
        
    except KeyError as e:
        logger.exception("Missing required field in event", extra={"error": str(e)})
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Missing field: {str(e)}'})
        }
        
    except ClientError as e:
        logger.exception("DynamoDB error", extra={"error": str(e)})
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }
        
    except Exception as e:
        logger.exception("Unexpected error", extra={"error": str(e)})
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }
