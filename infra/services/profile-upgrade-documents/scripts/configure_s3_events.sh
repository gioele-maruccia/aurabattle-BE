#!/bin/bash

# Script to configure S3 Event Notifications for DocReceived Lambda
# Auto-detects environment from bucket name

set -e

REGION="eu-south-1"
BUCKET_NAME=${1}

if [ -z "$BUCKET_NAME" ]; then
    echo "Usage: $0 <bucket-name>"
    echo ""
    echo "Examples:"
    echo "  $0 beezey-dev-user-documents"
    echo "  $0 beezey-prod-user-documents"
    exit 1
fi

# Detect environment from bucket name
if [[ "$BUCKET_NAME" == *"-dev-"* ]]; then
    ENVIRONMENT="dev"
    STACK_NAME="dev-docs-upload"
elif [[ "$BUCKET_NAME" == *"-prod-"* ]]; then
    ENVIRONMENT="prod"
    STACK_NAME="prod-docs-upload"
else
    echo "❌ Cannot detect environment from bucket name: $BUCKET_NAME"
    echo "   Expected 'dev' or 'prod' in the bucket name"
    exit 1
fi

echo "=== Configuring S3 Event Notifications ==="
echo "Bucket: ${BUCKET_NAME}"
echo "Environment: ${ENVIRONMENT}"
echo "Stack: ${STACK_NAME}"
echo "Region: ${REGION}"
echo ""

# Verify bucket exists
echo "Checking if bucket exists..."
if ! aws s3api head-bucket --bucket "${BUCKET_NAME}" --region ${REGION} 2>/dev/null; then
    echo "❌ Error: Bucket ${BUCKET_NAME} does not exist or is not accessible"
    exit 1
fi
echo "✅ Bucket exists"
echo ""

# Get Lambda function ARN from CloudFormation stack
echo "Retrieving Lambda function ARN from stack ${STACK_NAME}..."
FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region ${REGION} \
    --query 'Stacks[0].Outputs[?OutputKey==`DocReceivedFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

if [ -z "$FUNCTION_ARN" ] || [ "$FUNCTION_ARN" == "None" ]; then
    echo "❌ Error: Could not find DocReceivedFunctionArn from stack ${STACK_NAME}"
    echo ""
    echo "Available stacks:"
    aws cloudformation list-stacks --region ${REGION} \
        --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
        --query 'StackSummaries[?contains(StackName, `docs`)].StackName' \
        --output table
    exit 1
fi

echo "✅ Function ARN: ${FUNCTION_ARN}"
echo ""

# Create notification configuration JSON
cat > /tmp/s3-notification-config.json <<EOF
{
  "LambdaFunctionConfigurations": [
    {
      "Id": "${ENVIRONMENT}-doc-received-trigger",
      "LambdaFunctionArn": "${FUNCTION_ARN}",
      "Events": [
        "s3:ObjectCreated:Put",
        "s3:ObjectCreated:Post",
        "s3:ObjectCreated:CompleteMultipartUpload"
      ],
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

echo "Applying S3 event notification configuration..."
aws s3api put-bucket-notification-configuration \
    --bucket ${BUCKET_NAME} \
    --notification-configuration file:///tmp/s3-notification-config.json \
    --region ${REGION}

echo ""
echo "✅ S3 Event Notifications configured successfully!"
echo ""
echo "Configuration details:"
echo "  - Trigger: uploads/* (Put, Post, CompleteMultipartUpload)"
echo "  - Target: ${FUNCTION_ARN}"
echo ""
echo "Test with:"
echo "  aws s3 cp test.pdf s3://${BUCKET_NAME}/uploads/test-\$(date +%s).pdf --region ${REGION}"