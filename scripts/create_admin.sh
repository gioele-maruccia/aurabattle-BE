#!/bin/bash

# Script semplice per creare admin attivo
# Usage: ./create-admin.sh admin@example.com

EMAIL=$1
PASSWORD="Password@1"
USER_POOL_ID="eu-south-1_0oK9agPYd"

if [ -z "$EMAIL" ]; then
  echo "Usage: $0 <email>"
  exit 1
fi

echo "Creating admin: $EMAIL"

# Crea utente
aws cognito-idp admin-create-user \
  --user-pool-id $USER_POOL_ID \
  --username $EMAIL \
  --user-attributes \
    Name=email,Value=$EMAIL \
    Name=email_verified,Value=true \
    Name=given_name,Value=Admin \
    Name=family_name,Value=User \
    Name=birthdate,Value=1994-12-08 \
  --message-action SUPPRESS \
  --region eu-south-1

# Conferma account PRIMA di impostare la password
aws cognito-idp admin-confirm-sign-up \
  --user-pool-id $USER_POOL_ID \
  --username $EMAIL \
  --region eu-south-1 2>/dev/null

# Imposta password permanente
aws cognito-idp admin-set-user-password \
  --user-pool-id $USER_POOL_ID \
  --username $EMAIL \
  --password "$PASSWORD" \
  --permanent \
  --region eu-south-1

# Rimuovi flag FORCE_CHANGE_PASSWORD (se presente)
aws cognito-idp admin-update-user-attributes \
  --user-pool-id $USER_POOL_ID \
  --username $EMAIL \
  --user-attributes Name=email_verified,Value=true \
  --region eu-south-1 2>/dev/null

# Aggiungi al gruppo admins
aws cognito-idp admin-add-user-to-group \
  --user-pool-id $USER_POOL_ID \
  --username $EMAIL \
  --group-name admins \
  --region eu-south-1

echo ""
echo "✅ Admin created and activated!"
echo "Email: $EMAIL"
echo "Password: $PASSWORD"
echo ""