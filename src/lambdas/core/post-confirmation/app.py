"""
Cognito Post-Confirmation Trigger
Crea automaticamente il profilo DynamoDB quando l'utente conferma l'email
"""
import os
import boto3
from datetime import datetime
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

def lambda_handler(event, context):
    """
    Triggered by Cognito after user confirms email
    
    Event structure:
    {
        "request": {
            "userAttributes": {
                "sub": "uuid",
                "email": "user@example.com",
                "given_name": "Mario",
                "family_name": "Rossi",
                "birthdate": "1990-01-15",
                "phone_number": "+39...",
                ...
            }
        },
        "response": {}
    }
    """
    try:
        # Estrai attributi utente
        attrs = event['request']['userAttributes']
        user_id = attrs['sub']
        email = attrs['email']
        
        print(f"[PostConfirmation] Triggered for user: {user_id} ({email})")
        
        # Crea profilo con valori di default
        profile_data = {
            'user_id': user_id,
            'email': email,
            
            # Profilo base da Cognito
            'profile': {
                'given_name': attrs.get('given_name', ''),
                'family_name': attrs.get('family_name', ''),
                'birthdate': attrs.get('birthdate', ''),
                'phone_number': attrs.get('phone_number', '')
            },

            # Nome pubblico mostrato agli altri utenti (default: given_name)
            'display_name': attrs.get('given_name', ''),
            'avatar_url': None,

            # Stato account (per moderazione)
            'account_status': 'active',

            # Contatori denormalizzati (aggiornati quando esisterà la tabella Battles)
            'hosted_battles_count': 0,
            'joined_battles_count': 0,

            # Stato verifiche
            'verifications': {
                'email_verified': True,  # Email già confermata da Cognito
                'phone_verified': False
            },

            # Statistiche aura (placeholder, da definire con le regole delle battle)
            'aura_stats': {
                'level': 0,
                'wins': 0,
                'losses': 0
            },

            # Preferenze notifiche (default)
            'notification_preferences': {
                'email_enabled': False,
                'push_enabled': False,
                'channels': {
                    'new_battles': False,
                    'battle_reminders': False,
                    'messages': False,
                    'marketing': False
                }
            },

            # Localizzazione (default Italia)
            'localization': {
                'preferred_language': 'it',
                'timezone': 'Europe/Rome'
            },

            # Battle salvate nei bookmark (aura battle a cui l'utente vuole assistere/partecipare)
            'bookmarked_battles': [],

            # Timestamp
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }
        
        # Salva in DynamoDB - ConditionExpression garantisce idempotency in un solo round-trip
        # (evita get_item + put_item separati che rallentano il trigger Cognito)
        try:
            table.put_item(
                Item=profile_data,
                ConditionExpression=Attr('user_id').not_exists()
            )
            print(f"[PostConfirmation] ✅ Profile created successfully for {user_id}")
        except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            print(f"[PostConfirmation] Profile already exists for {user_id}, skipping")
        
        # IMPORTANTE: Ritorna sempre l'event originale
        return event
        
    except Exception as e:
        # Log errore ma NON bloccare la registrazione
        print(f"[PostConfirmation] ❌ Error: {str(e)}")
        print(f"[PostConfirmation] Event: {event}")
        
        # Ritorna event anche in caso di errore
        # Così l'utente può comunque completare la registrazione
        return event