"""
cleanup-prod-db.py
==================
⚠️  ATTENZIONE: SCRIPT DI PRODUZIONE ⚠️
Pulisce tutti i dati di PROD da DynamoDB e da Cognito, preservando SOLO
gli account le cui email vengono passate via argomento --keep-emails.

Cognito (prod-UserPool eu-south-1_iCBtUlJO6):
  - Elimina tutti gli utenti tranne quelli specificati

Tabelle DynamoDB AZZERATE (dati utente):
  - prod-UserProfiles       (eccetto gli utenti specificati)
  - prod-UserDocuments      (eccetto i documenti degli utenti specificati)
  - prod-Bookings
  - prod-Companies
  - prod-JobListings
  - prod-Chats
  - prod-Messages
  - prod-ConnectionManager
  - prod-SupportChats
  - prod-SupportMessages
  - prod-Reviews
  - prod-TaxCache

Tabelle INTOCCATE (dati di riferimento):
  - prod-JobRoles
  - prod-Contracts
  - prod-EmploymentTypes
  - prod-AtecoMapping

USO:
  python scripts/cleanup-prod-db.py --keep-emails admin@example.com altro@example.com
  python scripts/cleanup-prod-db.py --keep-emails admin@example.com --dry-run
  python scripts/cleanup-prod-db.py --keep-emails admin@example.com --confirm
"""

import sys
import boto3
import argparse
from botocore.exceptions import ClientError

# ── Config ────────────────────────────────────────────────────────────────────
REGION            = 'eu-south-1'
COGNITO_USER_POOL = 'eu-south-1_iCBtUlJO6'

# Tabelle da azzerare completamente (nessun record preservato)
TABLES_FULL_DELETE = [
    'prod-Bookings',
    'prod-Companies',
    'prod-JobListings',
    'prod-Chats',
    'prod-Messages',
    'prod-ConnectionManager',
    'prod-SupportChats',
    'prod-SupportMessages',
    'prod-Reviews',
    'prod-TaxCache',
]

# Tabelle di riferimento: non toccare
TABLES_SKIP = [
    'prod-JobRoles',
    'prod-Contracts',
    'prod-EmploymentTypes',
    'prod-AtecoMapping',
]

# ── Helper ────────────────────────────────────────────────────────────────────

def normalize_emails(emails):
    """Normalizza le email in lowercase per confronti case-insensitive."""
    return {e.strip().lower() for e in emails if e.strip()}


def get_table_key_schema(dynamodb_client, table_name):
    """Ritorna la lista di attributi che compongono la PK (HASH + eventuale RANGE)."""
    resp = dynamodb_client.describe_table(TableName=table_name)
    return resp['Table']['KeySchema']


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


def delete_all_items(table, key_schema, items, dry_run):
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

def cleanup_user_profiles(dynamodb, dynamodb_client, dry_run, keep_emails_lower):
    table_name = 'prod-UserProfiles'
    print(f'\n{"=" * 60}')
    print(f'Tabella: {table_name}')
    print(f'  Preservo email: {", ".join(sorted(keep_emails_lower))}')

    try:
        table      = dynamodb.Table(table_name)
        key_schema = get_table_key_schema(dynamodb_client, table_name)
        items      = scan_all(table)

        to_delete = [i for i in items if i.get('email', '').lower() not in keep_emails_lower]
        to_keep   = [i for i in items if i.get('email', '').lower() in keep_emails_lower]

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

def cleanup_user_documents(dynamodb, dynamodb_client, dry_run, keep_user_ids):
    """
    prod-UserDocuments ha PK: pk (HASH) + sk (RANGE).
    Il campo pk di solito è nel formato "USER#<userId>".
    Cancelliamo tutti i record la cui pk NON contiene uno degli userId da preservare.
    """
    table_name = 'prod-UserDocuments'
    print(f'\n{"=" * 60}')
    print(f'Tabella: {table_name}')

    try:
        table      = dynamodb.Table(table_name)
        key_schema = get_table_key_schema(dynamodb_client, table_name)
        items      = scan_all(table)

        if keep_user_ids:
            def should_keep(item):
                for uid in keep_user_ids:
                    if uid and (uid in str(item.get('pk', '')) or uid in str(item.get('userId', ''))):
                        return True
                return False

            to_delete = [i for i in items if not should_keep(i)]
            to_keep   = len(items) - len(to_delete)
            print(f'  User IDs preservati: {", ".join(uid for uid in keep_user_ids if uid)}')
        else:
            print('  [WARNING] Nessun userId trovato per gli utenti da preservare - cancello tutti i documenti')
            to_delete = items
            to_keep   = 0

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
            print(f'  [SKIP] Tabella non trovata.')
        else:
            print(f'  [ERROR] {e.response["Error"]["Message"]}')


# ── Trova gli userId degli utenti da preservare ───────────────────────────────

def get_user_ids_to_keep(dynamodb, keep_emails_lower):
    """
    Cerca i record con email in keep_emails e ritorna i loro user_id.
    Ritorna una lista (può essere vuota se nessuno è trovato in UserProfiles).
    """
    user_ids = []

    # Prova prima via email-index
    table = dynamodb.Table('prod-UserProfiles')
    for email in keep_emails_lower:
        found = False
        try:
            resp  = table.query(
                IndexName='email-index',
                KeyConditionExpression=boto3.dynamodb.conditions.Key('email').eq(email),
                Limit=5
            )
            for item in resp.get('Items', []):
                uid = item.get('user_id')
                if uid:
                    print(f'  Trovato userId per {email}: {uid}')
                    user_ids.append(uid)
                    found = True
        except Exception:
            pass

        if not found:
            # Fallback: scan completo
            try:
                items = scan_all(table)
                for i in items:
                    if i.get('email', '').lower() == email:
                        uid = i.get('user_id')
                        if uid:
                            print(f'  Trovato userId (scan) per {email}: {uid}')
                            user_ids.append(uid)
                            found = True
                            break
            except Exception:
                pass

        if not found:
            print(f'  [WARNING] Utente non trovato in UserProfiles per email: {email}')

    return user_ids


# ── Cognito cleanup ───────────────────────────────────────────────────────────

def cleanup_cognito(dry_run, keep_emails_lower):
    """Elimina tutti gli utenti dal User Pool PROD tranne quelli specificati."""
    print(f'\n{"=" * 60}')
    print(f'Cognito User Pool: {COGNITO_USER_POOL}')
    print(f'  Preservo email: {", ".join(sorted(keep_emails_lower))}')

    client = boto3.client('cognito-idp', region_name=REGION)

    users_to_delete = []
    kwargs = {'UserPoolId': COGNITO_USER_POOL, 'Limit': 60}

    while True:
        resp = client.list_users(**kwargs)
        for user in resp.get('Users', []):
            email = ''
            for attr in user.get('Attributes', []):
                if attr['Name'] == 'email':
                    email = attr['Value']
                    break
            username = user['Username']

            if email.lower() in keep_emails_lower:
                print(f'  [KEEP]   {username}  ({email})')
            else:
                users_to_delete.append((username, email))

        token = resp.get('PaginationToken')
        if not token:
            break
        kwargs['PaginationToken'] = token

    print(f'  Da eliminare: {len(users_to_delete)} utenti Cognito')

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
    parser = argparse.ArgumentParser(
        description='⚠️  Cleanup PRODUZIONE: DynamoDB + Cognito (preserva email specificate)'
    )
    parser.add_argument(
        '--keep-emails',
        nargs='+',
        required=True,
        metavar='EMAIL',
        help='Una o più email da PRESERVARE (tutti gli altri verranno eliminati)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Mostra cosa verrebbe cancellato senza fare nulla'
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Salta la richiesta di conferma interattiva (usare con massima cautela)'
    )
    args = parser.parse_args()

    dry_run          = args.dry_run
    keep_emails_lower = normalize_emails(args.keep_emails)

    if not keep_emails_lower:
        print('[ERROR] Devi specificare almeno una email con --keep-emails.')
        sys.exit(1)

    print('=' * 60)
    print('  ⚠️   BeeBusy PRODUZIONE - DB + Cognito Cleanup Script  ⚠️')
    print('=' * 60)
    print(f'  Modalità   : {"DRY-RUN (nessuna cancellazione)" if dry_run else "🔴 LIVE - cancellazione REALE su PROD"}')
    print(f'  Email mantenute:')
    for e in sorted(keep_emails_lower):
        print(f'    ✔  {e}')
    print(f'  Cognito    : {COGNITO_USER_POOL}')
    print(f'  Regione    : {REGION}')
    print('=' * 60)

    if not dry_run:
        if args.confirm:
            print('\n[--confirm passato] Procedo senza richiesta interattiva.')
        else:
            print('\n⚠️  Stai per CANCELLARE dati REALI di PRODUZIONE.')
            print('   Questa operazione è IRREVERSIBILE.')
            confirm = input('\n   Digita "PROD" per confermare: ')
            if confirm.strip() != 'PROD':
                print('Operazione annullata.')
                return

    session         = boto3.Session(region_name=REGION)
    dynamodb        = session.resource('dynamodb')
    dynamodb_client = session.client('dynamodb')

    # 0. Cognito: elimina tutti gli utenti tranne quelli specificati
    cleanup_cognito(dry_run, keep_emails_lower)

    # 1. Recupera gli userId degli utenti da preservare
    print('\nRecupero userId degli utenti da preservare...')
    keep_user_ids = get_user_ids_to_keep(dynamodb, keep_emails_lower)
    if keep_user_ids:
        print(f'  User IDs da preservare: {keep_user_ids}')
    else:
        print('  [WARNING] Nessun userId trovato - UserDocuments verrà svuotata completamente')

    # 2. UserProfiles (preserva utenti specificati)
    cleanup_user_profiles(dynamodb, dynamodb_client, dry_run, keep_emails_lower)

    # 3. UserDocuments (preserva documenti degli utenti specificati)
    cleanup_user_documents(dynamodb, dynamodb_client, dry_run, keep_user_ids)

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
        print('  ✅  Cleanup PROD completato!')
    print('=' * 60)


if __name__ == '__main__':
    main()
