"""
Lambda: Get Total Unread Count
Returns the number of chats with at least one unread message for the logged-in user.
"""

import json

from db_manager import ChatDBManager
from models import ChatStatus


def lambda_handler(event, context):
    try:
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')

        if not user_id:
            return {
                'statusCode': 401,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Unauthorized',
                    'message': 'User ID not found in token'
                })
            }

        db_manager = ChatDBManager()

        try:
            worker_chats = db_manager.get_chats_by_worker(user_id)
        except Exception as e:
            print(f"Error getting worker chats: {e}")
            worker_chats = []

        try:
            company_chats = db_manager.get_chats_by_company_representative(user_id)
        except Exception as e:
            print(f"Error getting company chats: {e}")
            company_chats = db_manager.get_chats_by_company_representative_scan(user_id)

        worker_chat_ids = {
            chat.chat_id for chat in worker_chats
            if chat.status != ChatStatus.DELETED
        }
        all_chats = [
            chat for chat in worker_chats + company_chats
            if chat.status != ChatStatus.DELETED
        ]

        seen_chat_ids = set()
        chats_with_unread = 0

        for chat in all_chats:
            if chat.chat_id in seen_chat_ids:
                continue
            seen_chat_ids.add(chat.chat_id)
            is_worker = chat.chat_id in worker_chat_ids
            unread = db_manager.get_unread_count(chat.chat_id, user_id, is_worker=is_worker)
            if unread > 0:
                # Se ci sono messaggi apparentemente non letti, prova l'auto-heal:
                # se l'ultimo messaggio RICEVUTO è già 'read', allora i flag precedenti
                # sono inconsistenti e vengono corretti automaticamente.
                healed = db_manager.heal_stale_unread_if_last_read(chat.chat_id, user_id, is_worker)
                if healed > 0:
                    # I messaggi erano obsoleti e sono stati sanati → chat ora letta
                    unread = 0
            if unread > 0:
                chats_with_unread += 1

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'unreadCount': chats_with_unread
            })
        }

    except Exception as e:
        print(f"Error calculating total unread count: {e}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': 'Internal server error'
            })
        }
