"""
Cognito Post-Confirmation Trigger
Crea automaticamente il profilo DynamoDB quando l'utente conferma l'email
"""
import os
import re
import uuid
import boto3
from datetime import datetime
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
usernames_table = dynamodb.Table(os.environ['USERNAMES_TABLE'])

# Username univoco, case-insensitive (salvato sempre lowercase).
# L'unicita' e' garantita dalla tabella Usernames (chiave = username) con put
# condizionale; UserProfiles.user_id resta sempre e solo l'UUID Cognito.
USERNAME_PATTERN = re.compile(r'^[a-z0-9_.]{3,20}$')
RESERVED_USERNAMES = {'admin', 'administrator', 'aurabattle', 'support', 'moderator', 'root', 'system', 'staff'}


def _is_valid_username(value):
    return bool(USERNAME_PATTERN.match(value)) and value not in RESERVED_USERNAMES


def _reserve_username(username, owner_id):
    """Riserva lo username per owner_id. True se riservato (o gia' suo)."""
    try:
        usernames_table.put_item(
            Item={
                'username': username,
                'user_id': owner_id,
                'status': 'active',
                'created_at': datetime.utcnow().isoformat() + 'Z',
            },
            ConditionExpression=Attr('username').not_exists()
        )
        return True
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        existing = usernames_table.get_item(Key={'username': username}).get('Item') or {}
        return existing.get('user_id') == owner_id


def _confirm_reservation(username, owner_id, email):
    """Rende definitiva la riserva fatta dal PreSignUp (stesso username + stessa email).
    True se la riserva era di questo utente e ora e' attiva (senza scadenza)."""
    try:
        usernames_table.update_item(
            Key={'username': username},
            UpdateExpression='SET user_id = :uid, #s = :active, confirmed_at = :now REMOVE expires_at',
            ConditionExpression='attribute_exists(username) AND (email = :email OR user_id = :uid)',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':uid': owner_id,
                ':active': 'active',
                ':email': email,
                ':now': datetime.utcnow().isoformat() + 'Z',
            },
        )
        return True
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def _resolve_username(requested, given_name, user_id, email):
    """Conferma lo username riservato dal PreSignUp.

    Il PreSignUp rifiuta la registrazione se lo username e' occupato, quindi qui
    la riserva esiste gia'. Il ripiego generato resta solo come ultima risorsa
    (riserva scaduta e username preso nel frattempo) e viene sempre loggato.
    """
    requested = (requested or '').strip().lower()
    if requested and _is_valid_username(requested):
        if _confirm_reservation(requested, user_id, email):
            return requested
        # Riserva scaduta e ripulita dal TTL: riprova a prenderlo se ancora libero
        if _reserve_username(requested, user_id):
            return requested

    print(f"[PostConfirmation] WARNING: username '{requested}' non disponibile per {user_id}, uso un ripiego generato")
    base = re.sub(r'[^a-z0-9_.]', '', (given_name or '').lower())[:12] or 'user'
    sub_hex = user_id.replace('-', '')
    for size in (4, 6, 8):
        candidate = f"{base}_{sub_hex[:size]}"
        if _is_valid_username(candidate) and _reserve_username(candidate, user_id):
            return candidate
    while True:
        candidate = f"user_{uuid.uuid4().hex[:12]}"
        if _reserve_username(candidate, user_id):
            return candidate

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

        username = _resolve_username(attrs.get('custom:username'), attrs.get('given_name', ''), user_id, email)
        
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

            # Username univoco (lowercase): identificativo principale per ricerca,
            # selezione partecipanti e visualizzazione nelle sfide
            'username': username,

            # Nome pubblico mostrato agli altri utenti (default: given_name)
            'display_name': attrs.get('given_name', ''),
            'display_name_lower': attrs.get('given_name', '').lower(),
            'family_name_lower': attrs.get('family_name', '').lower(),
            'search_bucket': 'ALL',  # indice fisso per la ricerca utenti (picker partecipanti)
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