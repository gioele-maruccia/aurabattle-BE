#!/bin/bash

# ============================================
# PROFILE-UPGRADE-DOCUMENTS - AUTOMATIC SETUP
# ============================================
# Deploys CloudFormation stack AND configures
# S3 event notifications automatically.
#
# Single command deployment - no manual steps!
# Usage: ./deploy.sh dev
# ============================================

set -e

ENVIRONMENT=${1:-dev}
REGION="eu-south-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
INFRA_DIR="$REPO_ROOT/infra/services/profile-upgrade-documents"

echo "========================================"
echo "Profile Upgrade Documents - Auto Setup"
echo "========================================"
echo "Environment: $ENVIRONMENT"
echo ""

# Validate environment
if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
    echo "❌ Invalid environment: $ENVIRONMENT"
    echo "Must be 'dev' or 'prod'"
    exit 1
fi

# Determine configuration
if [[ "$ENVIRONMENT" == "dev" ]]; then
    BUCKET="beezey-dev-user-documents"
    LAMBDA_FUNC="dev-doc-received"
    STACK_NAME="dev-docs-upload"
else
    BUCKET="beezey-prod-user-documents"
    LAMBDA_FUNC="prod-doc-received"
    STACK_NAME="prod-docs-upload"
fi

echo "Bucket: $BUCKET"
echo "Lambda: $LAMBDA_FUNC"
echo "Stack: $STACK_NAME"
echo ""

# Step 1: Check AWS credentials
echo "[1/4] Verifying AWS credentials..." 
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || {
    echo "❌ AWS CLI not configured. Run: aws configure"
    exit 1
}
echo "✅ AWS Account: $ACCOUNT_ID"
echo ""

# Step 2: Deploy CloudFormation Stack
echo "[2/4] Deploying CloudFormation stack '$STACK_NAME'..."
cd "$INFRA_DIR"

sam deploy --config-env "$ENVIRONMENT" --no-confirm-changeset || {
    echo "❌ CloudFormation deployment failed"
    exit 1
}
echo "✅ Stack deployed successfully"
echo ""

# Step 3: Get Lambda ARN from CloudFormation outputs
echo "[3/4] Retrieving Lambda ARN from stack outputs..."

LAMBDA_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='DocReceivedFunctionArn'].OutputValue" \
    --output text 2>/dev/null) || true

if [[ -z "$LAMBDA_ARN" ]]; then
    echo "❌ Could not retrieve DocReceivedFunctionArn from stack outputs"
    exit 1
fi

echo "✅ Lambda ARN: $LAMBDA_ARN"
echo ""

# Step 4: Configure S3 Event Notification
echo "[4/4] Configuring S3 event notification..."

# Create temporary file with notification config
TEMP_FILE=$(mktemp)
trap "rm -f $TEMP_FILE" EXIT

cat > "$TEMP_FILE" << EOF
{
    "LambdaFunctionConfigurations": [
        {
            "LambdaFunctionArn": "$LAMBDA_ARN",
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {
                "Key": {
                    "FilterRules": [
                        {
                            "Name": "prefix",
                            "Value": "docs/"
                        }
                    ]
                }
            }
        }
    ]
}
EOF

aws s3api put-bucket-notification-configuration \
    --bucket "$BUCKET" \
    --notification-configuration file://"$TEMP_FILE" \
    --region "$REGION" 2>/dev/null || {
    echo "❌ Failed to configure S3 event notification"
    exit 1
}

echo "✅ S3 event notification configured"
echo ""

# Success
echo "========================================"
echo "✅ SETUP COMPLETE!"
echo "========================================"
echo ""
echo "Summary:"
echo "  Stack Name:        $STACK_NAME"
echo "  Bucket:            $BUCKET"
echo "  Lambda:            $LAMBDA_FUNC"
echo "  Region:            $REGION"
echo "  S3 Event Status:   ✅ Configured"
echo ""
echo "Next steps:"
echo "  1. Test upload: ./test-upload.sh $ENVIRONMENT"
echo "  2. Check logs:  aws logs tail /aws/lambda/$LAMBDA_FUNC --follow"
echo ""
