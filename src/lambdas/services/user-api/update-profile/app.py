import json
import os
import re
import boto3
from datetime import datetime
from boto3.dynamodb.types import TypeSerializer

dynamodb = boto3.resource('dynamodb')
# Client a basso livello per la transazione: i valori sono serializzati a mano
# (TypeSerializer). Il client del resource li serializza da solo e li
# avvolgerebbe due volte (stringa -> Map).
dynamodb_client = boto3.client('dynamodb')
cognito = boto3.client('cognito-idp')
table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
user_pool_id = os.environ['USER_POOL_ID']

# Stesse regole di post-confirmation: username lowercase, univoco tramite la
# tabella Usernames (chiave = username).
usernames_table_name = os.environ['USERNAMES_TABLE']
USERNAME_PATTERN = re.compile(r'^[a-z0-9_.]{3,20}$')
RESERVED_USERNAMES = {'admin', 'administrator', 'aurabattle', 'support', 'moderator', 'root', 'system', 'staff'}


def _json_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
        'body': json.dumps(body)
    }

def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        body = json.loads(event['body'])
        
        # 0. Validazione username (prima di qualsiasi scrittura)
        new_username = None
        if 'username' in body:
            new_username = str(body['username'] or '').strip().lower()
            if not USERNAME_PATTERN.match(new_username):
                return _json_response(400, {
                    'error': 'Bad Request',
                    'message': 'username must be 3-20 characters: a-z, 0-9, "_" or "."'
                })
            if new_username in RESERVED_USERNAMES:
                return _json_response(400, {'error': 'Bad Request', 'message': 'username is reserved'})

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

            # family_name e' annidato in profile, quindi non indicizzabile
            # direttamente: lo duplichiamo top-level per l'indice di ricerca
            # utenti (picker partecipanti), stesso pattern di display_name_lower
            if 'family_name' in body['profile']:
                update_parts.append('family_name_lower = :family_name_lower')
                expr_values[':family_name_lower'] = body['profile']['family_name'].lower()
        
        # Aggiorna address
        if 'address' in body:
            address = body['address']
            # Assicurati che country sia presente
            if 'country' not in address:
                address['country'] = 'IT'
            update_parts.append('address = :address')
            expr_values[':address'] = address

        # Aggiorna display_name (nome pubblico) + la sua versione lowercase,
        # usata dall'indice di ricerca utenti (picker partecipanti)
        if 'display_name' in body:
            update_parts.append('display_name = :display_name')
            expr_values[':display_name'] = body['display_name']
            update_parts.append('display_name_lower = :display_name_lower')
            expr_values[':display_name_lower'] = body['display_name'].lower()

        # Aggiorna avatar_url
        if 'avatar_url' in body:
            update_parts.append('avatar_url = :avatar_url')
            expr_values[':avatar_url'] = body['avatar_url']

        if not update_parts and new_username is None:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Bad Request', 'message': 'No fields to update'})
            }
        
        # Self-heal: i profili creati prima di search_bucket non compaiono negli
        # indici di ricerca (sparsi). Qualunque salvataggio li rimette in ricerca.
        update_parts.append('search_bucket = if_not_exists(search_bucket, :all_bucket)')
        expr_values[':all_bucket'] = 'ALL'

        # Aggiungi updated_at
        update_parts.append('updated_at = :now')

        update_expr = 'SET ' + ', '.join(update_parts)

        if new_username is None:
            table.update_item(
                Key={'user_id': user_id},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values
            )
        else:
            # Cambio username atomico: riserva il nuovo, rilascia il vecchio,
            # aggiorna il profilo. Fallisce interamente se il nuovo e' preso.
            current = table.get_item(
                Key={'user_id': user_id},
                ProjectionExpression='username'
            ).get('Item', {})
            old_username = current.get('username')

            if old_username == new_username:
                if update_parts != ['updated_at = :now']:
                    table.update_item(
                        Key={'user_id': user_id},
                        UpdateExpression=update_expr,
                        ExpressionAttributeValues=expr_values
                    )
            else:
                table_name = table.name
                serializer = TypeSerializer()
                update_parts.append('username = :username')
                expr_values[':username'] = new_username
                items = [
                    {'Put': {
                        'TableName': usernames_table_name,
                        'Item': {k: serializer.serialize(v) for k, v in {
                            'username': new_username,
                            'user_id': user_id,
                            'created_at': datetime.utcnow().isoformat() + 'Z',
                        }.items()},
                        'ConditionExpression': 'attribute_not_exists(username)',
                    }},
                    {'Update': {
                        'TableName': table_name,
                        'Key': {'user_id': {'S': user_id}},
                        'UpdateExpression': 'SET ' + ', '.join(update_parts),
                        'ExpressionAttributeValues': {k: serializer.serialize(v) for k, v in expr_values.items()},
                    }},
                ]
                if old_username:
                    items.append({'Delete': {
                        'TableName': usernames_table_name,
                        'Key': {'username': {'S': old_username}},
                    }})
                try:
                    dynamodb_client.transact_write_items(TransactItems=items)
                except dynamodb_client.exceptions.TransactionCanceledException as e:
                    # Una transazione annullata non vuol dire per forza "username preso":
                    # solo la condizione sul Put (indice 0) lo e'. Gli altri motivi
                    # (validazione, conflitto di transazione...) restano errori veri.
                    reasons = e.response.get('CancellationReasons') or []
                    print(f"[update-profile] Transaction cancelled: {reasons}")
                    if reasons and reasons[0].get('Code') == 'ConditionalCheckFailed':
                        return _json_response(409, {'error': 'Conflict', 'message': 'username already taken'})
                    raise
        
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