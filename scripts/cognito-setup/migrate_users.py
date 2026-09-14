#!/usr/bin/env python3
"""
Script per migrare utenti e gruppi da un User Pool Cognito esistente a uno nuovo.
Include migrazione di: utenti, attributi, gruppi, e appartenenza ai gruppi.
"""

import boto3
import json
import sys
from botocore.exceptions import ClientError
import time
from datetime import datetime

# Configurazione
OLD_USER_POOL_ID = 'eu-south-1_gBimsNm2Y'  # Vecchio pool
NEW_USER_POOL_ID = 'eu-south-1_0oK9agPYd'  # Dal SAM output
REGION = 'eu-south-1'

# Client Cognito
cognito = boto3.client('cognito-idp', region_name=REGION)

# ==================== FUNZIONI UTENTI ====================

def get_all_users(user_pool_id):
    """Recupera tutti gli utenti dal User Pool"""
    users = []
    paginator = cognito.get_paginator('list_users')
    
    try:
        for page in paginator.paginate(UserPoolId=user_pool_id):
            users.extend(page['Users'])
            print(f"Trovati {len(page['Users'])} utenti in questa pagina...")
    except ClientError as e:
        print(f"Errore nel recupero utenti: {e}")
        return []
    
    print(f"Totale utenti trovati: {len(users)}")
    return users

def extract_user_attributes(user):
    """Estrae e organizza gli attributi dell'utente"""
    attributes = {}
    user_email = None
    
    for attr in user.get('Attributes', []):
        attr_name = attr['Name']
        attr_value = attr['Value']
        
        if attr_name == 'email':
            user_email = attr_value
        
        # Mantieni attributi custom con prefisso custom:
        attributes[attr_name] = attr_value
    
    return {
        'username': user['Username'],
        'email': user_email,
        'attributes': attributes,
        'user_status': user.get('UserStatus', 'CONFIRMED'),
        'enabled': user.get('Enabled', True),
        'creation_date': user.get('UserCreateDate'),
        'last_modified': user.get('UserLastModifiedDate')
    }

def create_user_in_new_pool(user_data):
    """Crea un utente nel nuovo User Pool"""
    try:
        user_attributes = []
        
        for attr_name, attr_value in user_data['attributes'].items():
            if attr_name == 'sub':
                continue  # Skip sub (auto-generated)
            
            user_attributes.append({
                'Name': attr_name,
                'Value': str(attr_value)
            })
        
        # IMPORTANTE: Usa EMAIL come username (nuovo pool richiede email)
        username = user_data['email']
        
        # Crea utente
        response = cognito.admin_create_user(
            UserPoolId=NEW_USER_POOL_ID,
            Username=username,  # Email invece di UUID
            UserAttributes=user_attributes,
            MessageAction='SUPPRESS',
            TemporaryPassword='TempPass123!'
        )
        
        # Se l'utente era confermato nel vecchio pool
        if user_data['user_status'] == 'CONFIRMED':
            # Imposta password permanente (questo conferma automaticamente l'utente)
            cognito.admin_set_user_password(
                UserPoolId=NEW_USER_POOL_ID,
                Username=username,
                Password='TempPass123!',
                Permanent=False  # False = utente deve cambiarla al login
            )
        
        print(f"✅ Utente {username} (ex-UUID: {user_data['username']}) migrato")
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        username = user_data['email']  # Email come username
        
        if error_code == 'UsernameExistsException':
            print(f"⚠️  Utente {username} già esistente")
            return True
        else:
            print(f"❌ Errore migrazione {username}: {e}")
            return False

# ==================== FUNZIONI GRUPPI ====================

def get_all_groups(user_pool_id):
    """Recupera tutti i gruppi dal User Pool"""
    groups = []
    paginator = cognito.get_paginator('list_groups')
    
    try:
        for page in paginator.paginate(UserPoolId=user_pool_id):
            groups.extend(page['Groups'])
    except ClientError as e:
        print(f"Errore nel recupero gruppi: {e}")
        return []
    
    print(f"Totale gruppi trovati: {len(groups)}")
    return groups

def create_group_in_new_pool(group_data):
    """Crea un gruppo nel nuovo User Pool"""
    try:
        params = {
            'UserPoolId': NEW_USER_POOL_ID,
            'GroupName': group_data['GroupName'],
            'Description': group_data.get('Description', ''),
        }
        
        # Aggiungi precedence se esiste
        if 'Precedence' in group_data:
            params['Precedence'] = group_data['Precedence']
        
        # Aggiungi role ARN se esiste
        if 'RoleArn' in group_data:
            params['RoleArn'] = group_data['RoleArn']
        
        cognito.create_group(**params)
        print(f"✅ Gruppo '{group_data['GroupName']}' creato")
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        
        if error_code == 'GroupExistsException':
            print(f"⚠️  Gruppo '{group_data['GroupName']}' già esistente")
            return True
        else:
            print(f"❌ Errore creazione gruppo '{group_data['GroupName']}': {e}")
            return False

def get_users_in_group(user_pool_id, group_name):
    """Recupera tutti gli utenti in un gruppo"""
    users = []
    paginator = cognito.get_paginator('list_users_in_group')
    
    try:
        for page in paginator.paginate(
            UserPoolId=user_pool_id,
            GroupName=group_name
        ):
            users.extend(page['Users'])
    except ClientError as e:
        print(f"Errore recupero utenti nel gruppo {group_name}: {e}")
        return []
    
    return users

def add_user_to_group(user_pool_id, username, group_name):
    """Aggiunge un utente a un gruppo"""
    try:
        cognito.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=username,
            GroupName=group_name
        )
        return True
    except ClientError as e:
        print(f"❌ Errore aggiunta {username} al gruppo {group_name}: {e}")
        return False

def migrate_groups():
    """Migra tutti i gruppi"""
    print("\n🔐 MIGRAZIONE GRUPPI")
    print("="*50)
    
    old_groups = get_all_groups(OLD_USER_POOL_ID)
    
    if not old_groups:
        print("⚠️  Nessun gruppo da migrare")
        return
    
    migrated_count = 0
    
    for group in old_groups:
        print(f"\n📁 Migrando gruppo: {group['GroupName']}")
        if create_group_in_new_pool(group):
            migrated_count += 1
        time.sleep(0.3)
    
    print(f"\n✅ Gruppi migrati: {migrated_count}/{len(old_groups)}")
    return old_groups

def migrate_group_memberships(old_groups):
    """Migra l'appartenenza degli utenti ai gruppi"""
    print("\n👥 MIGRAZIONE APPARTENENZA GRUPPI")
    print("="*50)
    
    # Crea mapping UUID -> Email dal vecchio pool
    print("📋 Creando mapping UUID -> Email...")
    old_users = get_all_users(OLD_USER_POOL_ID)
    uuid_to_email = {}
    
    for user in old_users:
        uuid = user['Username']
        email = None
        for attr in user.get('Attributes', []):
            if attr['Name'] == 'email':
                email = attr['Value']
                break
        if email:
            uuid_to_email[uuid] = email
    
    print(f"✅ Mappati {len(uuid_to_email)} utenti")
    
    total_memberships = 0
    migrated_memberships = 0
    
    for group in old_groups:
        group_name = group['GroupName']
        print(f"\n📁 Gruppo: {group_name}")
        
        # Ottieni utenti nel gruppo vecchio
        users_in_group = get_users_in_group(OLD_USER_POOL_ID, group_name)
        
        if not users_in_group:
            print(f"   ⚠️  Nessun utente nel gruppo")
            continue
        
        print(f"   Trovati {len(users_in_group)} utenti")
        
        for user in users_in_group:
            old_username = user['Username']  # UUID
            new_username = uuid_to_email.get(old_username)  # Email
            
            if not new_username:
                print(f"   ❌ Email non trovata per UUID {old_username}")
                continue
            
            total_memberships += 1
            
            # Aggiungi al gruppo nel nuovo pool usando EMAIL
            if add_user_to_group(NEW_USER_POOL_ID, new_username, group_name):
                migrated_memberships += 1
                print(f"   ✅ {new_username} aggiunto a {group_name}")
            else:
                print(f"   ❌ Errore aggiunta {new_username} a {group_name}")
            
            time.sleep(0.2)
    
    print(f"\n✅ Appartenenze migrate: {migrated_memberships}/{total_memberships}")

# ==================== FUNZIONI PRINCIPALI ====================

def migrate_all():
    """Migrazione completa: gruppi, utenti, appartenenze"""
    print("🚀 MIGRAZIONE COMPLETA")
    print("="*50)
    print(f"Da: {OLD_USER_POOL_ID}")
    print(f"A: {NEW_USER_POOL_ID}")
    print("-" * 50)
    
    # Verifica configurazione
    if 'INSERISCI' in NEW_USER_POOL_ID:
        print("❌ ERRORE: Devi aggiornare NEW_USER_POOL_ID!")
        sys.exit(1)
    
    # Step 1: Migra gruppi
    print("\n📍 STEP 1: Migrazione Gruppi")
    old_groups = migrate_groups()
    
    # Step 2: Migra utenti
    print("\n📍 STEP 2: Migrazione Utenti")
    print("="*50)
    
    old_users = get_all_users(OLD_USER_POOL_ID)
    
    if not old_users:
        print("❌ Nessun utente trovato")
        sys.exit(1)
    
    migrated_count = 0
    failed_count = 0
    
    for user in old_users:
        print(f"\n📋 Processando: {user['Username']}")
        
        user_data = extract_user_attributes(user)
        print(f"   📧 {user_data['email']}")
        print(f"   📊 Status: {user_data['user_status']}")
        
        if create_user_in_new_pool(user_data):
            migrated_count += 1
        else:
            failed_count += 1
        
        time.sleep(0.5)
    
    # Step 3: Migra appartenenze gruppi
    print("\n📍 STEP 3: Migrazione Appartenenza Gruppi")
    if old_groups:
        migrate_group_memberships(old_groups)
    
    # Report finale
    print("\n" + "="*50)
    print("📊 REPORT FINALE")
    print("="*50)
    print(f"👥 Gruppi migrati: {len(old_groups) if old_groups else 0}")
    print(f"✅ Utenti migrati: {migrated_count}")
    print(f"❌ Utenti falliti: {failed_count}")
    print(f"📊 Totale processati: {len(old_users)}")
    
    if failed_count == 0:
        print("\n🎉 Migrazione completata con successo!")
    else:
        print(f"\n⚠️  Completata con {failed_count} errori")

def compare_pools():
    """Confronta utenti e gruppi nei due pool"""
    print("👥 CONFRONTO POOL")
    print("="*50)
    
    # Confronto utenti
    old_users = get_all_users(OLD_USER_POOL_ID)
    new_users = get_all_users(NEW_USER_POOL_ID)
    
    print(f"\n🏠 Pool Vecchio: {len(old_users)} utenti")
    print(f"🆕 Pool Nuovo: {len(new_users)} utenti")
    
    old_usernames = {u['Username'] for u in old_users}
    new_usernames = {u['Username'] for u in new_users}
    
    missing_users = old_usernames - new_usernames
    if missing_users:
        print(f"\n❌ Utenti mancanti: {len(missing_users)}")
        for username in list(missing_users)[:5]:
            print(f"   - {username}")
    else:
        print("\n✅ Tutti gli utenti migrati!")
    
    # Confronto gruppi
    old_groups = get_all_groups(OLD_USER_POOL_ID)
    new_groups = get_all_groups(NEW_USER_POOL_ID)
    
    print(f"\n🔐 Pool Vecchio: {len(old_groups)} gruppi")
    print(f"🔐 Pool Nuovo: {len(new_groups)} gruppi")
    
    old_group_names = {g['GroupName'] for g in old_groups}
    new_group_names = {g['GroupName'] for g in new_groups}
    
    missing_groups = old_group_names - new_group_names
    if missing_groups:
        print(f"\n❌ Gruppi mancanti: {missing_groups}")
    else:
        print("\n✅ Tutti i gruppi migrati!")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "migrate":
            migrate_all()
        elif command == "compare":
            compare_pools()
        elif command == "groups-only":
            old_groups = migrate_groups()
            if old_groups:
                migrate_group_memberships(old_groups)
        else:
            print("Comando non riconosciuto")
            print("Uso: python migrate_cognito.py [migrate|compare|groups-only]")
    else:
        print("🔄 Script Migrazione Cognito")
        print("="*50)
        print("Comandi disponibili:")
        print("  migrate      - Migrazione completa (gruppi + utenti + appartenenze)")
        print("  compare      - Confronta i due pool")
        print("  groups-only  - Migra solo gruppi e appartenenze")
        print("\nUso: python migrate_cognito.py [comando]")