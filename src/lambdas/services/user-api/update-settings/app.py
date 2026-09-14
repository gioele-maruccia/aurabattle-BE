import json
import os
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        body = json.loads(event['body'])
        
        # Get current profile
        response = table.get_item(Key={'user_id': user_id})
        
        if 'Item' not in response:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Profile not found', 'code': 4129})
            }
        
        update_parts = []
        expr_values = {':now': datetime.utcnow().isoformat() + 'Z'}
        
        # 1. Aggiorna notification_preferences
        if 'notification_preferences' in body:
            current_prefs = response['Item'].get('notification_preferences', {})
            new_prefs = body['notification_preferences']
            
            # Merge
            if 'email_enabled' in new_prefs:
                current_prefs['email_enabled'] = new_prefs['email_enabled']
            if 'push_enabled' in new_prefs:
                current_prefs['push_enabled'] = new_prefs['push_enabled']
            if 'sms_enabled' in new_prefs:
                current_prefs['sms_enabled'] = new_prefs['sms_enabled']
            if 'channels' in new_prefs:
                current_prefs.setdefault('channels', {}).update(new_prefs['channels'])
            
            update_parts.append('notification_preferences = :notif')
            expr_values[':notif'] = current_prefs
        
        # 2. Aggiorna localization (lingua, timezone, currency, auto_translation_enabled)
        if 'localization' in body:
            current_local = response['Item'].get('localization', {})
            new_local = body['localization']
            
            # Merge
            if 'preferred_language' in new_local:
                current_local['preferred_language'] = new_local['preferred_language']
            if 'timezone' in new_local:
                current_local['timezone'] = new_local['timezone']
            if 'currency' in new_local:
                current_local['currency'] = new_local['currency']
            if 'auto_translation_enabled' in new_local:
                current_local['auto_translation_enabled'] = new_local['auto_translation_enabled']
            
            update_parts.append('localization = :local')
            expr_values[':local'] = current_local
        
        # 3. Aggiorna payment_preferences
        if 'payment_preferences' in body:
            current_payment = response['Item'].get('payment_preferences', {})
            new_payment = body['payment_preferences']
            
            # Merge
            if 'default_payment_method' in new_payment:
                current_payment['default_payment_method'] = new_payment['default_payment_method']
            if 'billing_address' in new_payment:
                current_payment['billing_address'] = new_payment['billing_address']
            if 'auto_renew' in new_payment:
                current_payment['auto_renew'] = new_payment['auto_renew']
            
            update_parts.append('payment_preferences = :payment')
            expr_values[':payment'] = current_payment
        
        if not update_parts:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'No settings to update', 'code': 4128})
            }
        
        # Aggiungi updated_at
        update_parts.append('updated_at = :now')
        
        update_expr = 'SET ' + ', '.join(update_parts)
        
        table.update_item(
            Key={'user_id': user_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values
        )
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'success': True, 'message': 'Settings updated successfully', 'code': 3030})
        }
        
    except Exception as e:
        print(f"Error updating settings: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': str(e), 'code': 5029})
        }