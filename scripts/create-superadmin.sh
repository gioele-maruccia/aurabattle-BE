#!/bin/bash
# ============================================================
# Crea l'unico utente super admin di Aura Battle (una tantum, a mano).
#
# Usage: ./create-superadmin.sh <dev-aurabattle|prod-aurabattle> <email> [username]
#
# - Crea il gruppo Cognito `superadmins` se non esiste.
# - Crea l'utente e gli imposta la password chiesta da terminale (non viene
#   salvata da nessuna parte). La password e' definitiva: il login dell'app
#   non gestisce il passaggio "nuova password obbligatoria" di Cognito.
# - Aggiunge l'utente al gruppo.
#
# Il ruolo e' il gruppo, non un attributo: l'utente non puo' modificarlo
# dal proprio token. Nessuna API dell'app assegna ruoli.
# ============================================================
set -euo pipefail

ENVIRONMENT=${1:-}
EMAIL=${2:-}
# Il trigger PreSignUp scatta anche per admin-create-user e rifiuta chi non ha
# custom:username valido (3-20 caratteri a-z 0-9 _ . e non riservato).
USERNAME=${3:-aurabattle_team}
REGION="eu-south-1"
GROUP="superadmins"

case "$ENVIRONMENT" in
  dev-aurabattle)  USER_POOL_ID="eu-south-1_ULXAFvzY9" ;;
  prod-aurabattle) USER_POOL_ID="eu-south-1_BKPMyjxEF" ;;
  *) echo "Usage: $0 <dev-aurabattle|prod-aurabattle> <email> [username]"; exit 1 ;;
esac

if [ -z "$EMAIL" ]; then
  echo "Usage: $0 <dev-aurabattle|prod-aurabattle> <email> [username]"
  exit 1
fi

read -r -s -p "Password del super admin: " PASSWORD; echo
read -r -s -p "Ripeti la password: " PASSWORD_CONFIRM; echo
if [ -z "$PASSWORD" ] || [ "$PASSWORD" != "$PASSWORD_CONFIRM" ]; then
  echo "Le password sono vuote o non coincidono."
  exit 1
fi

echo "Pool:  $USER_POOL_ID ($ENVIRONMENT)"
echo "Email: $EMAIL"
echo ""

if ! aws cognito-idp get-group --user-pool-id "$USER_POOL_ID" --group-name "$GROUP" --region "$REGION" >/dev/null 2>&1; then
  echo "Creo il gruppo $GROUP..."
  aws cognito-idp create-group \
    --user-pool-id "$USER_POOL_ID" \
    --group-name "$GROUP" \
    --description "Super admin Aura Battle (backoffice di moderazione)" \
    --region "$REGION" >/dev/null
fi

echo "Creo l'utente..."
aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$EMAIL" \
  --user-attributes \
    Name=email,Value="$EMAIL" \
    Name=email_verified,Value=true \
    Name=given_name,Value=Admin \
    Name=family_name,Value=AuraBattle \
    Name=custom:username,Value="$USERNAME" \
  --message-action SUPPRESS \
  --region "$REGION" >/dev/null

echo "Imposto la password..."
aws cognito-idp admin-set-user-password \
  --user-pool-id "$USER_POOL_ID" \
  --username "$EMAIL" \
  --password "$PASSWORD" \
  --permanent \
  --region "$REGION"

echo "Aggiungo al gruppo $GROUP..."
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$USER_POOL_ID" \
  --username "$EMAIL" \
  --group-name "$GROUP" \
  --region "$REGION"

echo ""
echo "Super admin creato: $EMAIL (gruppo $GROUP)."
echo ""
echo "NOTA: admin-create-user non passa dal trigger PostConfirmation, quindi"
echo "il profilo DynamoDB non viene creato: al super admin serve solo per il"
echo "backoffice web, che non lo legge."
