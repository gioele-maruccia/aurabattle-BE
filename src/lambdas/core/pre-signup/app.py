"""
Cognito Pre-Sign-up Trigger
Rifiuta la registrazione se custom:username non e' valido o e' gia' occupato, e
riserva lo username (con scadenza) nella tabella Usernames.

L'unicita' dell'email e' gia' garantita da Cognito (UsernameAttributes=email).
La riserva e' "pending" con expires_at: PostConfirmation la rende definitiva alla
conferma dell'email; se l'utente non conferma, scade e lo username si libera.

Errori (arrivano al client come UserLambdaValidationException):
  USERNAME_INVALID, USERNAME_RESERVED, USERNAME_TAKEN
"""
import os
import re
import time
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
usernames_table = dynamodb.Table(os.environ['USERNAMES_TABLE'])

USERNAME_PATTERN = re.compile(r'^[a-z0-9_.]{3,20}$')
RESERVED_USERNAMES = {'admin', 'administrator', 'aurabattle', 'support', 'moderator', 'root', 'system', 'staff'}

# Il codice di conferma Cognito vale 24h: la riserva dura un'ora in piu'
RESERVATION_TTL_SECONDS = 25 * 60 * 60


def lambda_handler(event, context):
    attrs = event['request'].get('userAttributes', {})
    username = (attrs.get('custom:username') or '').strip().lower()
    email = (attrs.get('email') or '').strip().lower()

    if not USERNAME_PATTERN.match(username):
        raise Exception('USERNAME_INVALID')
    if username in RESERVED_USERNAMES:
        raise Exception('USERNAME_RESERVED')

    now = int(time.time())
    try:
        usernames_table.put_item(
            Item={
                'username': username,
                'email': email,
                'status': 'pending',
                'expires_at': now + RESERVATION_TTL_SECONDS,
                'created_at': datetime.utcnow().isoformat() + 'Z',
            },
            # Libero, oppure riserva pending scaduta (il TTL di DynamoDB e' lazy),
            # oppure riserva pending della stessa email (retry della registrazione)
            ConditionExpression=(
                'attribute_not_exists(username) OR '
                '(#s = :pending AND (expires_at < :now OR email = :email))'
            ),
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':pending': 'pending', ':now': now, ':email': email},
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        print(f"[PreSignUp] username '{username}' gia' occupato")
        raise Exception('USERNAME_TAKEN')

    print(f"[PreSignUp] username '{username}' riservato per {email}")
    # Non auto-confermare: l'utente deve verificare l'email
    return event
