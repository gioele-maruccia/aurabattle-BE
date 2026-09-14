#!/bin/bash

echo "=== Cleanup Script per risorse vecchie ==="
echo ""
echo "⚠️  ATTENZIONE: Questo script eliminerà risorse!"
echo "    Esegui solo se sei sicuro di voler procedere."
echo ""
read -p "Vuoi procedere con la pulizia? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Operazione annullata."
    exit 0
fi

REGION="eu-south-1"
OLD_BUCKET="4seasonsjob-dev-userdocs-eusouth1"

echo ""
echo "1. Svuotamento bucket vecchio: $OLD_BUCKET"
echo "   Questo potrebbe richiedere alcuni minuti..."
aws s3 rm s3://$OLD_BUCKET --recursive --region $REGION

echo ""
echo "2. Eliminazione bucket vecchio: $OLD_BUCKET"
aws s3api delete-bucket --bucket $OLD_BUCKET --region $REGION

echo ""
echo "✅ Pulizia completata!"
echo ""
echo "Ora puoi deployare il nuovo stack con:"
echo "  sam deploy --config-file samconfig-final.toml --config-env dev --template-file template-final.yaml"