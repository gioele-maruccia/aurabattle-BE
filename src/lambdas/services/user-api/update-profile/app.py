import json
import os
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
cognito = boto3.client('cognito-idp')
table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
user_pool_id = os.environ['USER_POOL_ID']

def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        body = json.loads(event['body'])
        
        # 1. Update Cognito attributes (se presenti)
        cognito_updates = []
        
        if 'profile' in body:
            profile = body['profile']
            
            if 'given_name' in profile:
                cognito_updates.append({'Name': 'given_name', 'Value': profile['given_name']})
            if 'family_name' in profile:
                cognito_updates.append({'Name': 'family_name', 'Value': profile['family_name']})
            if 'phone_number' in profile:
                cognito_updates.append({'Name': 'phone_number', 'Value': profile['phone_number']})
        
        # Aggiorna Cognito se ci sono cambiamenti
        if cognito_updates:
            cognito.admin_update_user_attributes(
                UserPoolId=user_pool_id,
                Username=user_id,
                UserAttributes=cognito_updates
            )
        
        # 2. Update DynamoDB
        update_parts = []
        expr_values = {':now': datetime.utcnow().isoformat() + 'Z'}
        
        # Aggiorna profile (nome, cognome, telefono)
        # IMPORTANT: merge with existing profile to avoid wiping fields not included in this request
        if 'profile' in body:
            existing_resp = table.get_item(
                Key={'user_id': user_id},
                ProjectionExpression='profile'
            )
            existing_profile = existing_resp.get('Item', {}).get('profile', {})
            merged_profile = {**existing_profile, **body['profile']}
            update_parts.append('profile = :profile')
            expr_values[':profile'] = merged_profile
        
        # Aggiorna address
        if 'address' in body:
            address = body['address']
            # Assicurati che country sia presente
            if 'country' not in address:
                address['country'] = 'IT'
            update_parts.append('address = :address')
            expr_values[':address'] = address

        # Aggiorna display_name (nome pubblico)
        if 'display_name' in body:
            update_parts.append('display_name = :display_name')
            expr_values[':display_name'] = body['display_name']

        # Aggiorna avatar_url
        if 'avatar_url' in body:
            update_parts.append('avatar_url = :avatar_url')
            expr_values[':avatar_url'] = body['avatar_url']

        if not update_parts:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'No fields to update'})
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
            'body': json.dumps({'success': True, 'message': 'Profile updated successfully'})
        }
        
    except cognito.exceptions.UserNotFoundException:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Not Found', 'message': 'User not found in Cognito'})
        }
    except Exception as e:
        print(f"Error updating profile: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': str(e)})
        }