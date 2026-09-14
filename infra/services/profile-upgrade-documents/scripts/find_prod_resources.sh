#!/bin/bash

# Script per trovare gli ID delle risorse necessarie per l'ambiente PROD

REGION="eu-south-1"
SELECTED_POOL_ID=""
SELECTED_KMS_ID=""

echo "========================================="
echo "  TROVA RISORSE PROD per samconfig.toml"
echo "========================================="
echo ""

# 1. Cognito User Pool
echo "1️⃣  COGNITO USER POOL ID"
echo "-------------------------------------------"
echo "Cercando Cognito User Pools in ${REGION}..."
echo ""

POOLS=$(aws cognito-idp list-user-pools --max-results 20 --region ${REGION} 2>/dev/null)

if [ $? -eq 0 ]; then
    # Mostra i pool in formato tabellare
    echo "Pool disponibili:"
    echo ""
    echo "$POOLS" | jq -r '.UserPools[] | "\(.Name)\t\(.Id)"' | column -t -s $'\t'
    
    echo ""
    echo "-------------------------------------------"
    read -p "Inserisci il POOL ID per PROD (es. eu-south-1_XXXXXXXXX): " SELECTED_POOL_ID
    
    if [ -z "$SELECTED_POOL_ID" ]; then
        echo "⚠️  Nessun Pool ID inserito. Lo dovrai aggiungere manualmente."
    else
        echo "✅ Pool ID selezionato: $SELECTED_POOL_ID"
    fi
else
    echo "❌ Errore nel recuperare i Cognito User Pools"
    echo "   Comando manuale: aws cognito-idp list-user-pools --max-results 20 --region ${REGION}"
    echo ""
    read -p "Inserisci manualmente il POOL ID per PROD: " SELECTED_POOL_ID
fi

echo ""
echo "========================================="
echo ""

# 2. KMS Key
echo "2️⃣  KMS KEY ID"
echo "-------------------------------------------"
echo "Cercando KMS Keys in ${REGION}..."
echo ""

# Prima cerchiamo tramite gli alias
echo "🔍 Opzione 1: Cercando KMS Key tramite alias..."
ALIASES=$(aws kms list-aliases --region ${REGION} 2>/dev/null)

if [ $? -eq 0 ]; then
    # Cerca alias che contengono "prod" o "user-documents"
    FOUND_ALIASES=$(echo "$ALIASES" | jq -r '.Aliases[] | select(.AliasName | contains("prod") or contains("user-documents")) | "\(.AliasName)\t\(.TargetKeyId)"')
    
    if [ -n "$FOUND_ALIASES" ]; then
        echo "Alias trovati:"
        echo ""
        echo "$FOUND_ALIASES" | column -t -s $'\t'
        echo ""
    else
        echo "Nessun alias trovato con 'prod' o 'user-documents'"
        echo ""
    fi
fi

# Ora verifichiamo se esiste uno stack CloudFormation per prod
echo "🔍 Opzione 2: Cercando negli stack CloudFormation di prod..."
PROD_STACK_KMS=$(aws cloudformation describe-stacks \
    --stack-name user-documents-table-prod \
    --region ${REGION} \
    --query 'Stacks[0].Outputs[?OutputKey==`KMSKeyId`].OutputValue' \
    --output text 2>/dev/null)

if [ -n "$PROD_STACK_KMS" ] && [ "$PROD_STACK_KMS" != "None" ]; then
    echo "✅ Trovato KMS Key ID dallo stack 'user-documents-table-prod':"
    echo "   ${PROD_STACK_KMS}"
    echo ""
    echo "💡 Questo è probabilmente il valore corretto!"
    echo ""
    read -p "Vuoi usare questo KMS Key ID? (s/n): " USE_STACK_KMS
    if [ "$USE_STACK_KMS" = "s" ] || [ "$USE_STACK_KMS" = "S" ]; then
        SELECTED_KMS_ID="$PROD_STACK_KMS"
        echo "✅ KMS Key ID selezionato: $SELECTED_KMS_ID"
    fi
else
    echo "⚠️  Stack 'user-documents-table-prod' non trovato"
    echo ""
fi

if [ -z "$SELECTED_KMS_ID" ]; then
    echo "-------------------------------------------"
    echo "💡 Il KMS Key ID ha questo formato: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    echo "   (è un UUID, NON un ARN)"
    echo ""
    read -p "Inserisci il KMS KEY ID per PROD (o premi INVIO per saltare): " SELECTED_KMS_ID
    
    if [ -z "$SELECTED_KMS_ID" ]; then
        echo "⚠️  Nessun KMS Key ID inserito. Lo dovrai aggiungere manualmente."
    else
        echo "✅ KMS Key ID selezionato: $SELECTED_KMS_ID"
    fi
fi

echo ""
echo "========================================="
echo ""

# 3. Verifica bucket S3
echo "3️⃣  VERIFICA S3 BUCKET (opzionale)"
echo "-------------------------------------------"
BUCKET_NAME="beezey-prod-user-documents"

aws s3api head-bucket --bucket ${BUCKET_NAME} --region ${REGION} 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ Il bucket '${BUCKET_NAME}' esiste"
    
    # Prova a ottenere la configurazione di encryption
    ENCRYPTION=$(aws s3api get-bucket-encryption --bucket ${BUCKET_NAME} --region ${REGION} 2>/dev/null)
    if [ $? -eq 0 ]; then
        KMS_FROM_BUCKET=$(echo "$ENCRYPTION" | jq -r '.ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.KMSMasterKeyID // empty')
        if [ -n "$KMS_FROM_BUCKET" ]; then
            echo "   Usa KMS Key: ${KMS_FROM_BUCKET##*/}"
        fi
    fi
else
    echo "⚠️  Il bucket '${BUCKET_NAME}' non esiste ancora"
    echo "   Verrà creato quando deployi lo stack user-documents per prod"
fi

echo ""
echo "========================================="
echo ""
echo "📝 RIASSUNTO - Valori da inserire in samconfig.toml:"
echo "========================================="
echo ""

if [ -n "$SELECTED_POOL_ID" ] && [ -n "$SELECTED_KMS_ID" ]; then
    echo "✅ Tutti i valori sono stati selezionati!"
    echo ""
    echo "Copia questo nel tuo samconfig.toml (sezione [prod]):"
    echo ""
    echo "[prod.deploy.parameters]"
    echo "parameter_overrides = ["
    echo "    \"Environment=prod\","
    echo "    \"ExistingBucketName=beezey-prod-user-documents\","
    echo "    \"ExistingUserPoolId=$SELECTED_POOL_ID\","
    echo "    \"ExistingKMSKeyId=$SELECTED_KMS_ID\""
    echo "]"
    echo ""
    
    # Salva in un file per comodità
    cat > /tmp/prod-config.txt <<EOF
[prod.deploy.parameters]
parameter_overrides = [
    "Environment=prod",
    "ExistingBucketName=beezey-prod-user-documents",
    "ExistingUserPoolId=$SELECTED_POOL_ID",
    "ExistingKMSKeyId=$SELECTED_KMS_ID"
]
EOF
    echo "💾 Salvato anche in: /tmp/prod-config.txt"
    echo ""
elif [ -n "$SELECTED_POOL_ID" ] || [ -n "$SELECTED_KMS_ID" ]; then
    echo "⚠️  Alcuni valori mancano ancora:"
    echo ""
    echo "[prod.deploy.parameters]"
    echo "parameter_overrides = ["
    echo "    \"Environment=prod\","
    echo "    \"ExistingBucketName=beezey-prod-user-documents\","
    if [ -n "$SELECTED_POOL_ID" ]; then
        echo "    \"ExistingUserPoolId=$SELECTED_POOL_ID\","
    else
        echo "    \"ExistingUserPoolId=<INSERISCI_QUI_IL_POOL_ID>\","
    fi
    if [ -n "$SELECTED_KMS_ID" ]; then
        echo "    \"ExistingKMSKeyId=$SELECTED_KMS_ID\""
    else
        echo "    \"ExistingKMSKeyId=<INSERISCI_QUI_IL_KMS_KEY_ID>\""
    fi
    echo "]"
else
    echo "⚠️  Nessun valore selezionato. Template di esempio:"
    echo ""
    echo "[prod.deploy.parameters]"
    echo "parameter_overrides = ["
    echo "    \"Environment=prod\","
    echo "    \"ExistingBucketName=beezey-prod-user-documents\","
    echo "    \"ExistingUserPoolId=<INSERISCI_QUI_IL_POOL_ID>\","
    echo "    \"ExistingKMSKeyId=<INSERISCI_QUI_IL_KMS_KEY_ID>\""
    echo "]"
fi
echo ""
echo "========================================="
echo ""
echo "🚀 PROSSIMI PASSI:"
echo ""
echo "1. Se NON hai ancora le risorse base in prod:"
echo "   cd infra/data/user-documents"
echo "   sam deploy --config-env prod --template-file template-final.yaml"
echo ""
echo "2. Ottieni i valori creati:"
echo "   aws cloudformation describe-stacks --stack-name user-documents-table-prod --region eu-south-1 --query 'Stacks[0].Outputs'"
echo ""
echo "3. Aggiorna samconfig.toml con i valori trovati"
echo ""
echo "4. Deploy del service stack:"
echo "   cd infra/services/profile-upgrade-documents"
echo "   sam deploy --config-env prod"
echo ""