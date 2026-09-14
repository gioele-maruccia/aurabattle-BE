"""
Lambda handler for WebSocket $connect route.
Saves connectionId to DynamoDB ConnectionManager table.

Autenticazione: supporta due modalità (in ordine di priorità):
  1. Cognito Authorizer configurato sul route (requestContext.authorizer.sub)
  2. Token JWT passato come query parameter `token` (fallback per WebSocket senza authorizer)
"""

import base64
import json
import os
import time
from typing import Any, Dict, Optional
from aws_lambda_powertools import Logger

import boto3
from botocore.exceptions import ClientError

logger = Logger()
dynamodb = boto3.resource('dynamodb')

CONNECTION_MANAGER_TABLE_NAME = os.environ['CONNECTION_MANAGER_TABLE_NAME']
connection_table = dynamodb.Table(CONNECTION_MANAGER_TABLE_NAME)


def decode_jwt_sub(token: str) -> Optional[str]:
    """
    Decodifica un JWT e restituisce il claim 'sub' (senza verifica della firma).
    Usato come fallback quando non c'è un Cognito Authorizer sul route.
    """
    try:
        payload_b64 = token.split('.')[1]
        # Aggiungi padding se necessario
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.b64decode(payload_b64))
        return payload.get('sub')
    except Exception as e:
        logger.warning(f"Could not decode JWT: {e}")
        return None


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle WebSocket connection.

    Accetta il token in due modi:
      1. Cognito Authorizer (requestContext.authorizer.sub)
      2. Query parameter: wss://...?token={idToken}
    """
    logger.info("WebSocket connect event", extra={"event": event})
    
    try:
        # Extract connectionId and userId
        connection_id = event['requestContext']['connectionId']
        
        # Estrategia 1: Cognito Authorizer configurato sul route
        authorizer = event['requestContext'].get('authorizer', {})
        user_id = authorizer.get('sub') or authorizer.get('principalId')
        
        # Strategia 2: token JWT nella query string (?token=...)
        if not user_id:
            query_params = event.get('queryStringParameters') or {}
            token = query_params.get('token')
            if token:
                user_id = decode_jwt_sub(token)
                if user_id:
                    logger.info("user_id extracted from JWT query param")
                else:
                    logger.warning("JWT query param present but sub not found")
        
        if not user_id:
            logger.error("No user_id found in authorizer or token query param")
            return {
                'statusCode': 401,
                'body': json.dumps({'error': 'Unauthorized', 'message': 'Unauthorized: provide token query parameter', 'code': 4301})
            }
        
        # Save connection to DynamoDB with TTL (24 hours)
        ttl = int(time.time()) + 86400

        # Rimuovi eventuali connessioni stale dello stesso utente prima di registrarne
        # una nuova. Questo previene il caso in cui un'app non disconnette la WS al
        # cambio account, lasciando connectionId "zombie" registrati con il vecchio userId.
        try:
            from boto3.dynamodb.conditions import Key
            existing = connection_table.query(
                IndexName='userId-index',
                KeyConditionExpression=Key('userId').eq(user_id)
            )
            for old_item in existing.get('Items', []):
                old_conn_id = old_item.get('connectionId')
                if old_conn_id and old_conn_id != connection_id:
                    connection_table.delete_item(Key={'connectionId': old_conn_id})
                    logger.info(f"Removed stale connection {old_conn_id} for user {user_id}")
        except Exception as cleanup_err:
            logger.warning(f"Could not clean up old connections for user {user_id}: {cleanup_err}")

        connection_table.put_item(
            Item={
                'connectionId': connection_id,
                'userId': user_id,
                'connectedAt': int(time.time()),
                'ttl': ttl
            }
        )
        
        logger.info(
            "Connection saved successfully",
            extra={
                "connectionId": connection_id,
                "userId": user_id
            }
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Connected', 'code': 3084})
        }
        
    except KeyError as e:
        logger.exception("Missing required field in event", extra={"error": str(e)})
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Missing field: {str(e)}', 'code': 4302})
        }
        
    except ClientError as e:
        logger.exception("DynamoDB error", extra={"error": str(e)})
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5083})
        }
        
    except Exception as e:
        logger.exception("Unexpected error", extra={"error": str(e)})
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal Server Error', 'message': 'Internal server error', 'code': 5084})
        }
