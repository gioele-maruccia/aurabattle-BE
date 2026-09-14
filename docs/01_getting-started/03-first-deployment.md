# First Deployment

## 🧭 Navigation

**[← Back: Environment Setup](./02-environment-setup.md)** | **[Getting Started Home](./README.md)** | **[Main Documentation](../../README.md)** | **[Next: Verify Setup →](./04-verify-setup.md)**

---

This guide walks you through deploying your first service to AWS. We'll use the **job-listings** service as it's well-documented and relatively simple.

## 🎯 What You'll Deploy

The job-listings service includes:
- **DynamoDB table** for storing job listings
- **11 Lambda functions** for CRUD operations
- **API Gateway** endpoints with Cognito authentication
- **IAM roles and policies** for Lambda execution

## 📂 Navigate to the Service

```bash
cd infra/services/job-listings
```

You should see:
```
job-listings/
├── samconfig.toml      # Deployment configuration
├── template.yaml       # SAM infrastructure definition
└── schema.json         # DynamoDB schema reference
```

## 🔍 Understanding the SAM Template

Let's examine the key components of `template.yaml`:

### 1. Parameters

```yaml
Parameters:
  Environment:
    Type: String
    Default: dev
    AllowedValues: [dev, prod]
  
  CognitoUserPoolArn:
    Type: String
    Description: ARN of the Cognito User Pool for API authorization
```

These are passed via `samconfig.toml` during deployment.

### 2. Resources

The template defines:
- **DynamoDB Table**: Stores job listings data
- **Lambda Functions**: Business logic (create, list, update, delete, etc.)
- **API Gateway**: HTTP API with Cognito authorization
- **IAM Roles**: Permissions for Lambda to access DynamoDB

### 3. Outputs

```yaml
Outputs:
  JobListingsApiUrl:
    Description: "API Gateway endpoint URL"
    Value: !Sub "https://${JobListingsHttpApi}.execute-api.${AWS::Region}.amazonaws.com"
```

This URL is used to call your API.

## 🏗️ Step 1: Build the Service

The build command packages Lambda functions and dependencies and is already present inside the build.bat script. Before running it, you should comment/uncomment the interested section.

```bash
.\scripts\build.bat
```

**What happens:**
1. SAM reads `template.yaml`
2. Finds all Lambda functions
3. Installs Python dependencies from `requirements.txt`
4. Creates `.aws-sam/build/` directory with packaged code

**Expected output:**
```
Building codeuri: ../../../src/lambdas/services/job-listings/create-listing runtime: python3.9
...
Build Succeeded

Built Artifacts  : .aws-sam/build
Built Template   : .aws-sam/build/template.yaml
```

**Build time:** ~1-3 minutes depending on dependencies

## 🚀 Step 2: Deploy to AWS

Deploy the built artifacts to AWS:

```bash
.\scripts\deploy-dev.bat
```

**What happens:**
1. SAM packages code and uploads to S3
2. Creates CloudFormation change set
3. Prompts for confirmation
4. Deploys all resources
5. Outputs API endpoint URL

**Interactive prompts:**

```
Previewing CloudFormation changeset before deployment
======================================================
Deploy this changeset? [y/N]: y
```

Type `y` and press Enter.

**Deployment stages:**
```
CloudFormation events:
---------------------------------------------------------------------------------------
ResourceStatus                ResourceType                  LogicalResourceId
---------------------------------------------------------------------------------------
CREATE_IN_PROGRESS           AWS::CloudFormation::Stack    seasonal-jobs-joblistings-services-dev
CREATE_IN_PROGRESS           AWS::DynamoDB::Table          JobListingsTable
CREATE_IN_PROGRESS           AWS::IAM::Role                CreateListingFunctionRole
...
CREATE_COMPLETE              AWS::Lambda::Function         CreateListingFunction
CREATE_COMPLETE              AWS::ApiGatewayV2::Api        JobListingsHttpApi
...
CREATE_COMPLETE              AWS::CloudFormation::Stack    seasonal-jobs-joblistings-services-dev
---------------------------------------------------------------------------------------
```

**Deployment time:** ~3-5 minutes

### Expected Output

```
CloudFormation outputs from deployed stack
---------------------------------------------------------------------------------------
Outputs
---------------------------------------------------------------------------------------
Key                 JobListingsApiUrl
Description         API Gateway endpoint URL
Value               https://abc123xyz.execute-api.eu-south-1.amazonaws.com
---------------------------------------------------------------------------------------

Successfully created/updated stack - seasonal-jobs-joblistings-services-dev in eu-south-1
```

**Save this API URL!** You'll need it for testing.

## 📋 Step 3: Verify Deployment in AWS Console

### Check CloudFormation Stack

1. Open [AWS CloudFormation Console](https://eu-south-1.console.aws.amazon.com/cloudformation)
2. Select region: **eu-south-1**
3. Find stack: `seasonal-jobs-joblistings-services-dev`
4. Status should be: **CREATE_COMPLETE** ✅

### Check Lambda Functions

1. Open [AWS Lambda Console](https://eu-south-1.console.aws.amazon.com/lambda)
2. You should see 11 new functions:
   - `CreateListingFunction`
   - `ListListingsFunction`
   - `GetListingFunction`
   - `UpdateListingFunction`
   - `DeleteListingFunction`
   - `PublishListingFunction`
   - `PauseListingFunction`
   - `CloseListingFunction`
   - `SearchListingsFunction`
   - `GetMyListingsFunction`
   - `GetCompanyListingsFunction`

### Check DynamoDB Table

1. Open [DynamoDB Console](https://eu-south-1.console.aws.amazon.com/dynamodb)
2. Find table: `JobListings-dev`
3. Should be empty (no items yet)

### Check API Gateway

1. Open [API Gateway Console](https://eu-south-1.console.aws.amazon.com/apigateway)
2. Find API: `JobListings-API-dev`
3. Check routes are configured

## 🔄 Updating the Deployment

To update an existing stack after code changes:

```bash
# 1. Rebuild
sam build

# 2. Deploy (will update existing resources)
sam deploy --config-env default
```

SAM only updates changed resources, making updates faster than initial deployment.

## 🗑️ Cleaning Up (Optional)

To delete all deployed resources:

```bash
sam delete --stack-name seasonal-jobs-joblistings-services-dev --region eu-south-1
```

**Warning:** This permanently deletes:
- All Lambda functions
- DynamoDB table and all data
- API Gateway endpoints
- IAM roles

## 🎛️ Advanced: Deploy to Production

When ready for production:

### 1. Update Production Parameters

Edit `samconfig.toml` under `[prod]` section:
```toml
[prod.deploy.parameters]
parameter_overrides = "Environment=\"prod\" CognitoUserPoolArn=\"arn:aws:cognito-idp:eu-south-1:YOUR_ACCOUNT_ID:userpool/YOUR_PROD_POOL_ID\""
```

### 2. Deploy

```bash
sam build
sam deploy --config-env prod
```

This creates a separate stack: `seasonal-jobs-joblistings-services-prod`

## 📊 Understanding the Deployment

### Resource Naming Convention

- **Stacks**: `seasonal-jobs-{service}-services-{env}`
- **Tables**: `{ResourceName}-{env}`
- **Functions**: `{FunctionName}` (with stack prefix)

### Cost Estimates (Development)

For dev environment with minimal traffic:
- DynamoDB: ~$0.25/month (on-demand pricing)
- Lambda: Free tier (1M requests/month)
- API Gateway: Free tier (1M requests/month)
- CloudWatch Logs: ~$0.50/month

**Total: <$1/month** for light development usage

## 🐛 Troubleshooting

### "Stack already exists"

If deployment fails midway:
```bash
# Delete and retry
sam delete --stack-name seasonal-jobs-joblistings-services-dev --region eu-south-1
sam deploy --config-env default
```

### "Insufficient permissions"

Contact AWS administrator to grant CloudFormation deployment permissions.

### "Template format error"

Validate template syntax:
```bash
sam validate
```

### "Resource limit exceeded"

AWS has soft limits on resources per region. Request increase via AWS Support.

## ✅ Deployment Checklist

After deployment, verify:

- [ ] CloudFormation stack status: CREATE_COMPLETE
- [ ] All 11 Lambda functions visible in console
- [ ] DynamoDB table created
- [ ] API Gateway endpoint URL obtained
- [ ] No error messages in deployment log

## 📚 Next Steps

Deployment successful? Let's test it! Continue to **[Verify Setup](./04-verify-setup.md)** →

---

## 🧭 Navigation

- **[← Back: Environment Setup](./02-environment-setup.md)**
- **[Getting Started Home](./README.md)**
- **[Main Documentation](../../README.md)**
- **[Next: Verify Setup →](./04-verify-setup.md)**