"""
cleanup-dev-db.py
=================
Pulisce tutti i dati di DEV da DynamoDB E da Cognito, preservando SOLO l'admin:
  gioelemaruccia8@gmail.com

Cognito (dev-UserPool eu-south-1_0oK9agPYd):
  - Elimina tutti gli utenti tranne l'admin

Tabelle DynamoDB AZZERATE (dati utente):
  - dev-UserProfiles       (eccetto admin)
  - dev-UserDocuments      (eccetto admin)
  - dev-Bookings
  - dev-Companies
  - dev-JobListings
  - dev-Chats
  - dev-Messages
  - dev-ConnectionManager
  - dev-SupportChats
  - dev-SupportMessages
  - dev-Reviews
  - dev-TaxCache

Tabelle INTOCCATE (dati di riferimento):
  - dev-JobRoles
  - dev-Contracts
  - dev-EmploymentTypes
  - dev-AtecoMapping

USO:
  python scripts/cleanup-dev-db.py
  python scripts/cleanup-dev-db.py --dry-run    # solo preview, nessuna cancellazione
"""

import boto3
import argparse
from botocore.exceptions import ClientError

# ── Config ────────────────────────────────────────────────────────────────────
REGION              = 'eu-south-1'
ADMIN_EMAIL         = 'gioelemaruccia8@gmail.com'
COGNITO_USER_POOL   = 'eu-south-1_0oK9agPYd'

# Tabelle da azzerare completamente (nessun record preservato)
TABLES_FULL_DELETE = [
    'dev-Bookings',
    'dev-Companies',
    'dev-JobListings',
    'dev-Chats',
    'dev-Messages',
    'dev-ConnectionManager',
    'dev-SupportChats',
    'dev-SupportMessages',
    'dev-Reviews',
    'dev-TaxCache',
]

# Tabelle di riferimento: non toccare
TABLES_SKIP = [
    'dev-JobRoles',
    'dev-Contracts',
    'dev-EmploymentTypes',
    'dev-AtecoMapping',
]

# ── Helper ────────────────────────────────────────────────────────────────────

def get_table_key_schema(dynamodb_client, table_name):
    """Ritorna la lista di attributi che compongono la PK (HASH + eventuale RANGE)."""
    resp = dynamodb_client.describe_table(TableName=table_name)
    return resp['Table']['KeySchema']  # [{'AttributeName': ..., 'KeyType': 'HASH'}, ...]


def scan_all(table):
    """Fa scan completo di una tabella, gestendo la paginazione."""
    items = []
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get('Items', []))
        last = resp.get('LastEvaluatedKey')
        if not last:
            break
        kwargs['ExclusiveStartKey'] = last
    return items


def delete_all_items(table, key_schema, items, dry_run, label=''):
    """Cancella tutti gli item passati dalla tabella."""
    key_attrs = [k['AttributeName'] for k in key_schema]
    deleted = 0
    for item in items:
        key = {attr: item[attr] for attr in key_attrs if attr in item}
        if not key:
            print(f'  [SKIP] Impossibile costruire la PK per item: {item}')
            continue
        if dry_run:
            print(f'  [DRY-RUN] Cancellerei: {key}')
        else:
            table.delete_item(Key=key)
            deleted += 1
    return deleted


# ── Routine per UserProfiles ──────────────────────────────────────────────────

def cleanup_user_profiles(dynamodb, dynamodb_client, dry_run):
    table_name = 'dev-UserProfiles'
    print(f'\n{"=" * 60}')
    print(f'Tabella: {table_name}')
    print(f'  Preservo solo: {ADMIN_EMAIL}')

    try:
        table      = dynamodb.Table(table_name)
        key_schema = get_table_key_schema(dynamodb_client, table_name)
        items      = scan_all(table)

        to_delete = [i for i in items if i.get('email') != ADMIN_EMAIL]
        to_keep   = [i for i in items if i.get('email') == ADMIN_EMAIL]

        print(f'  Trovati: {len(items)} record  |  Da cancellare: {len(to_delete)}  |  Da tenere: {len(to_keep)}')

        if not to_delete:
            print('  Niente da cancellare.')
            return

        deleted = delete_all_items(table, key_schema, to_delete, dry_run)
        if not dry_run:
            print(f'  ✓ Cancellati {deleted} record.')

    except ClientError as e:
        print(f'  [ERROR] {e.response["Error"]["Message"]}')


# ── Routine per UserDocuments ─────────────────────────────────────────────────

def cleanup_user_documents(dynamodb, dynamodb_client, dry_run, admin_user_id):
    """
    dev-UserDocuments ha PK: pk (HASH) + sk (RANGE)
    Il campo pk di solito è nel formato "USER#<userId>"
    Cancelliamo tutti i record la cui pk NON corrisponde all'admin.
    """
    table_name = 'dev-UserDocuments'
    print(f'\n{"=" * 60}')
    print(f'Tabella: {table_name}')

    try:
        table      = dynamodb.Table(table_name)
        key_schema = get_table_key_schema(dynamodb_client, table_name)
        items      = scan_all(table)

        if admin_user_id:
            # Preserva documenti dell'admin (pk contiene il suo userId)
            to_delete = [
                i for i in items
                if admin_user_id not in str(i.get('pk', '')) and admin_user_id not in str(i.get('userId', ''))
            ]
            to_keep = len(items) - len(to_delete)
            print(f'  Admin userId: {admin_user_id}')
        else:
            # Se non riusciamo a trovare l'admin userId, cancelliamo tutto
            print('  [WARNING] Admin userId non trovato - cancello tutti i documenti')
            to_delete = items
            to_keep = 0

        print(f'  Trovati: {len(items)} record  |  Da cancellare: {len(to_delete)}  |  Da tenere: {to_keep}')

        if not to_delete:
            print('  Niente da cancellare.')
            return

        deleted = delete_all_items(table, key_schema, to_delete, dry_run)
        if not dry_run:
            print(f'  ✓ Cancellati {deleted} record.')

    except ClientError as e:
        print(f'  [ERROR] {e.response["Error"]["Message"]}')


# ── Routine generica per tabella full-delete ──────────────────────────────────

def cleanup_table_full(dynamodb, dynamodb_client, table_name, dry_run):
    print(f'\n{"=" * 60}')
    print(f'Tabella: {table_name}  [FULL DELETE]')

    try:
        table      = dynamodb.Table(table_name)
        key_schema = get_table_key_schema(dynamodb_client, table_name)
        items      = scan_all(table)

        print(f'  Trovati: {len(items)} record')

        if not items:
            print('  Già vuota.')
            return

        deleted = delete_all_items(table, key_schema, items, dry_run)
        if not dry_run:
            print(f'  ✓ Cancellati {deleted} record.')
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            print(f'  [SKIP] Tabella non trovata (forse non ancora creata).')
        else:
            print(f'  [ERROR] {e.response["Error"]["Message"]}')


# ── Trova lo userId dell'admin da UserProfiles ────────────────────────────────

def get_admin_user_id(dynamodb):
    """Cerca il record con email = ADMIN_EMAIL e ritorna lo user_id."""
    try:
        table = dynamodb.Table('dev-UserProfiles')
        resp  = table.query(
            IndexName='email-index',
            KeyConditionExpression=boto3.dynamodb.conditions.Key('email').eq(ADMIN_EMAIL),
            Limit=1
        )
        items = resp.get('Items', [])
        if items:
            return items[0].get('user_id')
    except Exception:
        pass

    # Fallback: scan
    try:
        table = dynamodb.Table('dev-UserProfiles')
        items = scan_all(table)
        for i in items:
            if i.get('email') == ADMIN_EMAIL:
                return i.get('user_id')
    except Exception:
        pass

    return None


# ── Cognito cleanup ───────────────────────────────────────────────────────────

def cleanup_cognito(dry_run):
    """
    Elimina tutti gli utenti dal User Pool DEV tranne l'admin.
    """
    print(f'\n{"=" * 60}')
    print(f'Cognito User Pool: {COGNITO_USER_POOL}')
    print(f'  Preservo solo: {ADMIN_EMAIL}')

    client = boto3.client('cognito-idp', region_name=REGION)

    users_to_delete = []
    kwargs = {'UserPoolId': COGNITO_USER_POOL, 'Limit': 60}

    # Pagina su tutti gli utenti
    while True:
        resp = client.list_users(**kwargs)
        for user in resp.get('Users', []):
            email = ''
            for attr in user.get('Attributes', []):
                if attr['Name'] == 'email':
                    email = attr['Value']
                    break
            username = user['Username']

            if email.lower() == ADMIN_EMAIL.lower():
                print(f'  [KEEP]   {username}  ({email})')
            else:
                users_to_delete.append((username, email))

        token = resp.get('PaginationToken')
        if not token:
            break
        kwargs['PaginationToken'] = token

    print(f'  Da eliminare: {len(users_to_delete)} utenti')

    deleted = 0
    for username, email in users_to_delete:
        if dry_run:
            print(f'  [DRY-RUN] Eliminerei Cognito user: {username}  ({email})')
        else:
            try:
                client.admin_delete_user(UserPoolId=COGNITO_USER_POOL, Username=username)
                print(f'  [DEL]    {username}  ({email})')
                deleted += 1
            except ClientError as e:
                print(f'  [ERROR]  {username}: {e.response["Error"]["Message"]}')

    if not dry_run:
        print(f'  [OK] Eliminati {deleted} utenti Cognito.')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Cleanup DEV DynamoDB tables')
    parser.add_argument('--dry-run', action='store_true',
                        help='Mostra cosa verrebbe cancellato senza fare nulla')
    parser.add_argument('--confirm', action='store_true',
                        help='Salta la richiesta di conferma interattiva (usare con cautela)')
    args = parser.parse_args()

    dry_run = args.dry_run

    print('=' * 60)
    print('  BeeBusy DEV - DB + Cognito Cleanup Script')
    print('=' * 60)
    print(f'  Modalità  : {"DRY-RUN (nessuna cancellazione)" if dry_run else "LIVE - cancellazione reale"}')
    print(f'  Admin keep: {ADMIN_EMAIL}')
    print(f'  Cognito   : {COGNITO_USER_POOL}')
    print(f'  Regione   : {REGION}')
    print('=' * 60)

    if not dry_run:
        if args.confirm:
            print('\n[--confirm passato] Procedo senza richiesta interattiva.')
        else:
            confirm = input('\n⚠️  Stai per CANCELLARE dati in DEV. Digita "SI" per confermare: ')
            if confirm.strip() != 'SI':
                print('Operazione annullata.')
                return

    session        = boto3.Session(region_name=REGION)
    dynamodb       = session.resource('dynamodb')
    dynamodb_client = session.client('dynamodb')

    # 0. Cognito: elimina tutti gli utenti tranne l'admin
    cleanup_cognito(dry_run)

    # 1. Recupera lo userId dell'admin prima di modificare nulla
    print('\nRecupero userId dell\'admin...')
    admin_user_id = get_admin_user_id(dynamodb)
    if admin_user_id:
        print(f'  Admin user_id: {admin_user_id}')
    else:
        print(f'  [WARNING] Admin non trovato in UserProfiles - UserDocuments verrà svuotata completamente')

    # 2. UserProfiles (preserva admin)
    cleanup_user_profiles(dynamodb, dynamodb_client, dry_run)

    # 3. UserDocuments (preserva documenti admin)
    cleanup_user_documents(dynamodb, dynamodb_client, dry_run, admin_user_id)

    # 4. Full-delete tabelle dati utente
    for table_name in TABLES_FULL_DELETE:
        cleanup_table_full(dynamodb, dynamodb_client, table_name, dry_run)

    # 5. Tabelle di riferimento: skip
    print(f'\n{"=" * 60}')
    print('Tabelle di riferimento SKIPPATE (non modificate):')
    for t in TABLES_SKIP:
        print(f'  - {t}')

    print(f'\n{"=" * 60}')
    if dry_run:
        print('  DRY-RUN completato. Nessun dato è stato modificato.')
    else:
        print('  ✅  Cleanup completato!')
    print('=' * 60)


if __name__ == '__main__':
    main()
