"""
Lambda handler for WebSocket 'typingStatus' action.
Broadcasts typing indicators to the other chat participant.
"""

import json
import os
import sys
from typing import Any, Dict
from aws_lambda_powertools import Logger

# Add shared layer
sys.path.append('/opt/python')

from ws_manager import WebSocketManager
from db_manager import ChatDBManager

logger = Logger()


def _broadcast_typing(user_id: str, chat_id: str, is_typing: bool, version: str) -> Dict[str, Any]:
    """Logica comune typing status: broadcast all'altro partecipante."""
    db_manager = ChatDBManager()
    chat = db_manager.get_chat(chat_id)

    if not chat:
        return {'statusCode': 404, 'body': json.dumps({'error': 'Chat not found', 'code': 4303})}

    if user_id not in [chat.worker_id, chat.company_representative_id]:
        return {'statusCode': 403, 'body': json.dumps({'error': 'Not authorized for this chat', 'code': 4304})}

    ws_manager = WebSocketManager()
    stats = ws_manager.broadcast_to_chat(
        chat_id=chat_id,
        sender_id=user_id,
        data={
            'action': 'typing_status',
            'version': version,
            'chatId': chat_id,
            'userId': user_id,
            'isTyping': is_typing,
        }
    )

    logger.info(
        "Typing status broadcasted",
        extra={"chatId": chat_id, "userId": user_id, "isTyping": is_typing, "version": version, "stats": stats}
    )
    return {'statusCode': 200, 'body': json.dumps({'message': 'Typing status sent', 'code': 3085})}


def handle_legacy(user_id: str, chat_id: str, is_typing: bool) -> Dict[str, Any]:
    """Handler typingStatus — versione legacy."""
    return _broadcast_typing(user_id, chat_id, is_typing, version='legacy')


def handle_v1(user_id: str, chat_id: str, is_typing: bool) -> Dict[str, Any]:
    """Handler typingStatus — versione v1. Attualmente identico a legacy."""
    return _broadcast_typing(user_id, chat_id, is_typing, version='v1')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle typing status events from WebSocket.

    Il client può specificare la versione nel body:
      {"action": "typingStatus", "chatId": "...", "isTyping": true}          → legacy
      {"action": "typingStatus", "chatId": "...", "isTyping": true, "version": "1"} → v1

    Broadcasts to the other participant:
      {"action": "typing_status", "version": "legacy"|"v1", "chatId": "...", "userId": "...", "isTyping": true}
    """
    logger.info("Typing status event", extra={"event": event})

    try:
        connection_id = event['requestContext']['connectionId']

        authorizer = event['requestContext'].get('authorizer', {})
        user_id = authorizer.get('sub') or authorizer.get('principalId')

        if not user_id:
            ws_manager_lookup = WebSocketManager()
            user_id = ws_manager_lookup.get_user_id_by_connection(connection_id)

        if not user_id:
            logger.error("No user_id found for connection", extra={"connectionId": connection_id})
            return {'statusCode': 401, 'body': json.dumps({'error': 'Unauthorized', 'code': 4305})}

        body = json.loads(event.get('body', '{}'))
        chat_id = body.get('chatId')
        is_typing = body.get('isTyping', False)

        if not chat_id:
            return {'statusCode': 400, 'body': json.dumps({'error': 'chatId is required', 'code': 4306})}

        # Routing per versione
        version = WebSocketManager.get_ws_version(body)
        logger.info(f"typingStatus routing to version={version}")

        if version == 'v1':
            return handle_v1(user_id, chat_id, is_typing)
        else:
            return handle_legacy(user_id, chat_id, is_typing)

    except KeyError as e:
        logger.exception("Missing required field", extra={"error": str(e)})
        return {'statusCode': 400, 'body': json.dumps({'error': f'Missing field: {str(e)}', 'code': 4307})}

    except Exception as e:
        logger.exception("Unexpected error", extra={"error": str(e)})
        return {'statusCode': 500, 'body': json.dumps({'error': 'Internal server error', 'code': 5085})}
