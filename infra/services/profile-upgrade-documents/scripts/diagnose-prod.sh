#!/bin/bash

REGION="eu-south-1"

echo "========================================="
echo "  DIAGNOSTICA RISORSE PROD"
echo "========================================="
echo ""

# 1. Verifica bucket
echo "1️⃣  Verifica Bucket S3"
echo "-------------------------------------------"
BUCKET="beezey-prod-user-documents"
if aws s3api head-bucket --bucket "$BUCKET" --region $REGION 2>/dev/null; then
    echo "✅ Bucket $BUCKET esiste"
else
    echo "❌ Bucket $BUCKET NON esiste o non è accessibile"
fi
echo ""

# 2. Verifica tabella DynamoDB
echo "2️⃣  Verifica Tabella DynamoDB"
echo "-------------------------------------------"
TABLE="prod-UserDocuments"
if aws dynamodb describe-table --table-name "$TABLE" --region $REGION &>/dev/null; then
    echo "✅ Tabella $TABLE esiste"
else
    echo "❌ Tabella $TABLE NON esiste"
fi
echo ""

# 3. Verifica KMS Key
echo "3️⃣  Verifica KMS Key"
echo "-------------------------------------------"
read -p "Inserisci il KMS Key ID che stai usando: " KMS_ID
if [ -n "$KMS_ID" ]; then
    if aws kms describe-key --key-id "$KMS_ID" --region $REGION &>/dev/null; then
        echo "✅ KMS Key $KMS_ID esiste"
    else
        echo "❌ KMS Key $KMS_ID NON esiste o non è accessibile"
    fi
fi
echo ""

# 4. Verifica Cognito User Pool
echo "4️⃣  Verifica Cognito User Pool"
echo "-------------------------------------------"
read -p "Inserisci il User Pool ID che stai usando: " POOL_ID
if [ -n "$POOL_ID" ]; then
    if aws cognito-idp describe-user-pool --user-pool-id "$POOL_ID" --region $REGION &>/dev/null; then
        echo "✅ User Pool $POOL_ID esiste"
    else
        echo "❌ User Pool $POOL_ID NON esiste o non è accessibile"
    fi
fi
echo ""

# 5. Verifica CloudFormation Exports in conflitto
echo "5️⃣  Verifica CloudFormation Exports"
echo "-------------------------------------------"
echo "Cercando exports che potrebbero essere in conflitto..."
echo ""

EXPORTS=$(aws cloudformation list-exports --region $REGION --query 'Exports[?contains(Name, `prod`) && contains(Name, `Docs`)].Name' --output text 2>/dev/null)

if [ -n "$EXPORTS" ]; then
    echo "⚠️  Trovati exports esistenti:"
    for export in $EXPORTS; do
        echo "  - $export"
    done
    echo ""
    echo "Questi potrebbero causare conflitti se lo stack prova a crearli di nuovo."
    echo ""
    
    # Trova da quale stack vengono
    echo "Provenienza degli exports:"
    for export in $EXPORTS; do
        STACK=$(aws cloudformation list-exports --region $REGION --query "Exports[?Name=='$export'].ExportingStackId" --output text 2>/dev/null | cut -d'/' -f2)
        echo "  - $export → Stack: $STACK"
    done
else
    echo "✅ Nessun export in conflitto trovato"
fi
echo ""

# 6. Verifica stack esistenti
echo "6️⃣  Stack CloudFormation Esistenti"
echo "-------------------------------------------"
aws cloudformation list-stacks \
    --region $REGION \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
    --query 'StackSummaries[?contains(StackName, `prod`)].{Name:StackName,Status:StackStatus}' \
    --output table

echo ""
echo "========================================="
echo ""
echo "💡 SUGGERIMENTI:"
echo ""
echo "Se vedi exports in conflitto, hai due opzioni:"
echo "  1. Elimina lo stack che li sta esportando"
echo "  2. Modifica il template per non creare quegli exports"
echo ""
echo "Se una risorsa non esiste:"
echo "  - Deploy prima lo stack user-documents per prod"
echo "  - Verifica i permessi IAM"
echo ""