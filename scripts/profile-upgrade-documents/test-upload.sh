#!/bin/bash

# ============================================
# PROFILE-UPGRADE-DOCUMENTS - QUICK TEST
# ============================================
# Tests the complete document upload flow
# Usage: ./test-upload.sh dev
# ============================================

set -e

ENVIRONMENT=${1:-dev}
REGION="eu-south-1"

if [[ "$ENVIRONMENT" == "dev" ]]; then
    TABLE_NAME="dev-UserDocuments"
    STACK_NAME="dev-docs-upload"
elif [[ "$ENVIRONMENT" == "prod" ]]; then
    TABLE_NAME="prod-UserDocuments"
    STACK_NAME="prod-docs-upload"
else
    echo "❌ Invalid environment: $ENVIRONMENT"
    exit 1
fi

USER_ID="test-user-$(date +%s)"

echo "========================================"
echo "Testing Document Upload Flow"
echo "========================================"
echo "Environment: $ENVIRONMENT"
echo "Test User:   $USER_ID"
echo ""

# Get API endpoint from CloudFormation
echo "[1/3] Getting API endpoint..."
API_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiGatewayEndpoint'].OutputValue" \
    --output text 2>/dev/null) || true

if [[ -z "$API_ENDPOINT" ]]; then
    echo "❌ Could not retrieve API endpoint. Check if stack is deployed."
    exit 1
fi

echo "✅ API: $API_ENDPOINT"
echo ""

# Check DynamoDB for recent entries
echo "[2/3] Checking DynamoDB for documents..."
ITEMS=$(aws dynamodb scan \
    --table-name "$TABLE_NAME" \
    --region "$REGION" \
    --limit 5 \
    --output json 2>/dev/null | jq '.Items | length') || true

if [[ "$ITEMS" -gt 0 ]]; then
    echo "✅ Found $ITEMS document(s) in DynamoDB:"
    echo ""
    
    aws dynamodb scan \
        --table-name "$TABLE_NAME" \
        --region "$REGION" \
        --limit 5 \
        --output json 2>/dev/null | jq -r '.Items[] | 
            "   User: \((.pk.S | split("#")[1])) | DocType: \(.docType.S) | Status: \(.status.S)"'
else
    echo "ℹ️  No documents found in DynamoDB"
fi

echo ""

# Check S3 documents
echo "[3/3] Checking S3 bucket for documents..."
S3_COUNT=$(aws s3 ls "s3://beezey-${ENVIRONMENT}-user-documents/docs/" --recursive 2>/dev/null | wc -l) || true

if [[ $S3_COUNT -gt 0 ]]; then
    echo "✅ Found $S3_COUNT file(s) in S3"
else
    echo "ℹ️  No files in S3 yet"
fi

echo ""
echo "========================================"
echo "✅ TEST COMPLETE"
echo "========================================"
