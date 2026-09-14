#!/bin/bash

echo "=== Checking for existing resources in eu-south-1 ==="
echo ""

echo "1. Checking S3 buckets..."
aws s3api list-buckets --region eu-south-1 --query 'Buckets[?contains(Name, `beezey`) || contains(Name, `4seasonsjob`)].Name' --output table 2>/dev/null || echo "Could not list buckets"

echo ""
echo "2. Checking DynamoDB tables..."
aws dynamodb list-tables --region eu-south-1 --query 'TableNames[?contains(@, `UserDocuments`)]' --output table 2>/dev/null || echo "Could not list tables"

echo ""
echo "3. Checking KMS aliases..."
aws kms list-aliases --region eu-south-1 --query 'Aliases[?contains(AliasName, `user-documents`)].AliasName' --output table 2>/dev/null || echo "Could not list KMS aliases"

echo ""
echo "4. Checking CloudFormation stacks..."
aws cloudformation list-stacks --region eu-south-1 --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query 'StackSummaries[?contains(StackName, `user-documents`)].{Name:StackName,Status:StackStatus}' --output table 2>/dev/null || echo "Could not list stacks"

echo ""
echo "=== Check complete ==="