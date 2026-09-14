# Infrastructure Details

## 🧭 Navigation

**[← Back: System Overview](./01-overview.md)** | **[Architecture Home](./README.md)** | **[Main Documentation](../../README.md)** | **[Next: Data Model →](./03-data-model.md)**

---

This document provides detailed information about the AWS infrastructure, SAM templates, resource naming conventions, and deployment architecture.

## 📋 Table of Contents

- [CloudFormation Stack Organization](#cloudformation-stack-organization)
- [SAM Template Structure](#sam-template-structure)
- [Resource Naming Conventions](#resource-naming-conventions)
- [IAM Roles and Policies](#iam-roles-and-policies)
- [API Gateway Configuration](#api-gateway-configuration)
- [Lambda Configuration](#lambda-configuration)
- [DynamoDB Configuration](#dynamodb-configuration)
- [S3 Configuration](#s3-configuration)
- [Environment Variables](#environment-variables)
- [Outputs and Exports](#outputs-and-exports)

---

## CloudFormation Stack Organization

### Stack Hierarchy

```
beezey-backend/
├── Core Stacks (infra/core/)
│   └── cognito-setup
│       └── Cognito User Pools and Identity Pools
│
├── Data Stacks (infra/data/)
│   ├── companies
│   │   └── DynamoDB: {env}-Companies
│   ├── job-listings
│   │   └── DynamoDB: JobListings-{env}
│   └── bookings
│       └── DynamoDB: Bookings-{env}
│
└── Service Stacks (infra/services/)
    ├── companies
    │   └── Stack: {env}-companies-api
    ├── job-listings
    │   └── Stack: seasonal-jobs-joblistings-services-{env}
    ├── bookings
    │   └── Stack: seasonal-jobs-bookings-services-{env}
    ├── docs-upload
    │   └── Stack: documents-upload-{env}
    ├── backoffice-api-sam
    │   └── Stack: backoffice-api-{env}
    └── user-verification-workflow
        └── Stack: user-verification-{env}
```

### Stack Dependencies

```
┌─────────────────┐
│  Cognito User   │  (Created first, ARN used by all services)
│     Pool        │
└────────┬────────┘
         │
    ┌────┴─────────────────────────┐
    │                              │
┌───▼──────────┐          ┌────────▼───────┐
│  DynamoDB    │          │  S3 Buckets    │
│   Tables     │          │  + KMS Keys    │
└───┬──────────┘          └────────┬───────┘
    │                              │
    └──────────┬───────────────────┘
               │
    ┌──────────▼──────────┐
    │  Service Stacks     │
    │  (Lambda + API GW)  │
    └─────────────────────┘
```

**Deployment Order**:
1. Cognito User Pool (manual or via core/cognito-setup)
2. Data resources (DynamoDB tables, S3 buckets, KMS keys)
3. Service stacks (reference existing Cognito ARN via parameters)

---

## SAM Template Structure

### Standard Template Anatomy

Every service follows this structure:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Service description

Parameters:
  Environment:
    Type: String
    Default: dev
    AllowedValues: [dev, staging, prod]
  
  CognitoUserPoolArn:
    Type: String
    Description: ARN of existing Cognito User Pool

Globals:
  Function:
    Runtime: python3.11  # or python3.13
    Timeout: 30
    MemorySize: 512
    Environment:
      Variables:
        ENVIRONMENT: !Ref Environment
        # Service-specific variables

Resources:
  # API Gateway
  # Lambda Functions
  # IAM Roles
  # DynamoDB Tables (if not separate stack)

Outputs:
  ApiUrl:
    Description: API Gateway endpoint URL
    Value: !Sub 'https://${ApiId}.execute-api.${AWS::Region}.amazonaws.com/${Environment}'
    Export:
      Name: !Sub '${Environment}-ServiceApiUrl'
```

### Example: Job Listings Template

**Location**: `infra/services/job-listings/template.yaml`

Key sections:

```yaml
Parameters:
  Environment:
    Type: String
    Default: dev
  
  CognitoUserPoolArn:
    Type: String
    Description: Pre-existing Cognito User Pool ARN

Globals:
  Function:
    Runtime: python3.11
    Timeout: 30
    MemorySize: 512
    Environment:
      Variables:
        ENVIRONMENT: !Ref Environment
        JOB_LISTINGS_TABLE_NAME: !Sub 'JobListings-${Environment}'

Resources:
  # API Gateway with Cognito Authorizer
  JobListingsHttpApi:
    Type: AWS::Serverless::HttpApi
    Properties:
      CorsConfiguration:
        AllowMethods: [GET, POST, PUT, DELETE, OPTIONS]
        AllowHeaders: [authorization, content-type]
        AllowOrigin: ['*']
      Auth:
        Authorizers:
          CognitoAuthorizer:
            IdentitySource: $request.header.Authorization
            JwtConfiguration:
              Issuer: !Sub 'https://cognito-idp.${AWS::Region}.amazonaws.com/${CognitoUserPoolId}'
              Audience: [!Ref CognitoUserPoolClientId]

  # Lambda Functions
  CreateListingFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub '${Environment}-create-listing'
      CodeUri: ../../../src/lambdas/services/job-listings/create-listing/
      Handler: app.lambda_handler
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Sub 'JobListings-${Environment}'
      Events:
        CreateApi:
          Type: HttpApi
          Properties:
            ApiId: !Ref JobListingsHttpApi
            Path: /listings
            Method: POST
```

### Example: Documents Upload Template

**Location**: `infra/services/docs-upload/template.yaml`

**Special Features**:
- Uses REST API (not HTTP API) for more control
- References existing S3 bucket and KMS key (created separately)
- EventBridge integration for scheduled cleanup
- S3 event trigger configuration

```yaml
Parameters:
  ExistingBucketName:
    Type: String
    Default: 4seasonsjob-dev-userdocs-eusouth1
    Description: Pre-existing S3 bucket name

  ExistingTableName:
    Type: String
    Default: UserDocuments2
    Description: Pre-existing DynamoDB table

  ExistingUserPoolId:
    Type: String
    Default: eu-south-1_0oK9agPYd
    Description: Cognito User Pool ID

  ExistingKMSKeyId:
    Type: String
    Default: "7f604da7-7b4a-45ca-9708-630fcee29ecd"
    Description: KMS Key ID for S3 encryption

Globals:
  Function:
    Runtime: python3.13
    Timeout: 10
    MemorySize: 256
    Environment:
      Variables:
        REGION: !Ref AWS::Region
        BUCKET_REGION: !Ref AWS::Region

Resources:
  # REST API (not HTTP API)
  DocumentsApi:
    Type: AWS::Serverless::Api
    Properties:
      Name: !Sub "${AWS::StackName}-api"
      StageName: !Ref StageName
      EndpointConfiguration:
        Type: REGIONAL
      Auth:
        DefaultAuthorizer: CognitoAuth
        Authorizers:
          CognitoAuth:
            UserPoolArn: !Sub 'arn:aws:cognito-idp:${AWS::Region}:${AWS::AccountId}:userpool/${ExistingUserPoolId}'

  # Presign URL Lambda
  PresignUrlFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: docs-presign-url-v2
      CodeUri: ../../../src/lambdas/services/docs-upload/presign-url/
      Handler: app.lambda_handler
      Environment:
        Variables:
          BUCKET: !Ref ExistingBucketName
          KMS_KEY_ID: !Ref ExistingKMSKeyId
          TABLE_NAME: !Ref ExistingTableName
          CLEANUP_FUNCTION_NAME: !Ref CleanupExpiredUploadsFunction
      Events:
        PresignUrlApi:
          Type: Api
          Properties:
            Path: /documents/upload-url
            Method: post
            RestApiId: !Ref DocumentsApi
            Auth:
              Authorizer: CognitoAuth
      Policies:
        - Version: '2012-10-17'
          Statement:
            - Sid: S3PresignedUrl
              Effect: Allow
              Action: [s3:PutObject, s3:PutObjectAcl]
              Resource: !Sub 'arn:aws:s3:::${ExistingBucketName}/*'
            
            - Sid: DdbWrite
              Effect: Allow
              Action: [dynamodb:PutItem, dynamodb:DescribeTable]
              Resource: !Sub 'arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${ExistingTableName}'
            
            - Sid: KMSEncrypt
              Effect: Allow
              Action: [kms:Encrypt, kms:Decrypt, kms:GenerateDataKey*, kms:DescribeKey]
              Resource: !Sub 'arn:aws:kms:${AWS::Region}:${AWS::AccountId}:key/${ExistingKMSKeyId}'
            
            - Sid: EventBridgeScheduling
              Effect: Allow
              Action: [events:PutRule, events:PutTargets, events:DeleteRule]
              Resource: !Sub "arn:aws:events:${AWS::Region}:${AWS::AccountId}:rule/cleanup-*"

  # S3 Event Trigger Lambda
  DocReceivedFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: doc-received
      CodeUri: ../../../src/lambdas/services/docs-upload/doc-received/
      Handler: app.lambda_handler
      Environment:
        Variables:
          TABLE_NAME: !Ref ExistingTableName
          DOC_SCAN_FUNCTION_NAME: !Ref DocScanFunction
      Policies:
        - Version: '2012-10-17'
          Statement:
            - Sid: DdbWriteMinimal
              Effect: Allow
              Action: [dynamodb:UpdateItem, dynamodb:GetItem]
              Resource: !Sub 'arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${ExistingTableName}'
            
            - Sid: InvokeDocScan
              Effect: Allow
              Action: lambda:InvokeFunction
              Resource: !GetAtt DocScanFunction.Arn

  # S3 Permission for Lambda
  DocReceivedS3Permission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref DocReceivedFunction
      Action: lambda:InvokeFunction
      Principal: s3.amazonaws.com
      SourceArn: !Sub 'arn:aws:s3:::${ExistingBucketName}'

  # EventBridge Permission for Cleanup Lambda
  CleanupExpiredUploadsEventBridgePermission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref CleanupExpiredUploadsFunction
      Action: lambda:InvokeFunction
      Principal: events.amazonaws.com
      SourceArn: !Sub "arn:aws:events:${AWS::Region}:${AWS::AccountId}:rule/cleanup-*"
```

### Example: Companies Template

**Location**: `infra/services/companies/template.yaml`

**Special Features**:
- Uses SAM policy templates (DynamoDBCrudPolicy, S3CrudPolicy)
- TracingEnabled for X-Ray
- Public endpoint (no auth) for company profiles

```yaml
Resources:
  CompaniesApi:
    Type: AWS::Serverless::Api
    Properties:
      Name: !Sub '${Environment}-companies-api'
      StageName: !Ref Environment
      Cors:
        AllowMethods: "'GET,POST,PUT,DELETE,OPTIONS'"
        AllowHeaders: "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
        AllowOrigin: "'*'"
      Auth:
        DefaultAuthorizer: CognitoAuthorizer
        Authorizers:
          CognitoAuthorizer:
            UserPoolArn: !Ref CognitoUserPoolArn
      TracingEnabled: true

  # Public endpoint (no auth)
  GetCompanyByIdFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub '${Environment}-companies-get-by-id'
      CodeUri: ../../../src/lambdas/services/companies/get-company-by-id/
      Handler: app.lambda_handler
      Events:
        GetCompanyById:
          Type: Api
          Properties:
            RestApiId: !Ref CompaniesApi
            Path: /companies/public/{companyId}
            Method: GET
            Auth:
              Authorizer: NONE  # ← No authentication required
```

---

## Resource Naming Conventions

### Stack Names

| Service | Dev Stack Name | Prod Stack Name |
|---------|---------------|-----------------|
| Companies | `dev-companies-api` | `prod-companies-api` |
| Job Listings | `seasonal-jobs-joblistings-services-dev` | `seasonal-jobs-joblistings-services-prod` |
| Bookings | `seasonal-jobs-bookings-services-dev` | `seasonal-jobs-bookings-services-prod` |
| Docs Upload | `documents-upload-dev` | `documents-upload-prod` |
| Backoffice | `backoffice-api-dev` | `backoffice-api-prod` |

### Lambda Function Names

**Pattern**: `{environment}-{service}-{action}` or `{action}` (if unique)

Examples:
- `dev-companies-create`
- `dev-companies-get`
- `docs-presign-url-v2`
- `doc-received`
- `doc-scan`
- `cleanup-expired-uploads`

### DynamoDB Table Names

**Pattern**: `{TableName}-{environment}` or `{environment}-{TableName}`

Examples:
- `JobListings-dev` / `JobListings-prod`
- `Bookings-dev` / `Bookings-prod`
- `dev-Companies` / `prod-Companies`
- `UserDocuments2` (no environment suffix in this case)

### S3 Bucket Names

**Pattern**: `{environment}-{purpose}-{region}` (must be globally unique)

Examples:
- `4seasonsjob-dev-userdocs-eusouth1`
- `dev-beezey-companies-assets`
- `prod-beezey-companies-assets`

### API Gateway Names

**Pattern**: `{environment}-{service}-api`

Examples:
- `dev-companies-api`
- `seasonal-jobs-joblistings-services-dev-api`
- `documents-upload-dev-api`

---

## IAM Roles and Policies

### Lambda Execution Roles

Each Lambda function gets an auto-generated execution role from SAM.

**Base Permissions** (all Lambdas):
- CloudWatch Logs (CreateLogGroup, CreateLogStream, PutLogEvents)
- X-Ray (if TracingEnabled: true)

**Additional Permissions** (via Policies):

#### SAM Policy Templates (Simplified)

```yaml
Policies:
  # Full CRUD on DynamoDB table
  - DynamoDBCrudPolicy:
      TableName: !Sub 'Companies-${Environment}'
  
  # Read-only on DynamoDB
  - DynamoDBReadPolicy:
      TableName: !Sub 'Companies-${Environment}'
  
  # Full S3 access
  - S3CrudPolicy:
      BucketName: !Sub '${Environment}-beezey-companies-assets'
  
  # Read-only S3
  - S3ReadPolicy:
      BucketName: !Sub '${Environment}-beezey-companies-assets'
```

#### Custom Inline Policies

**Example: Presign URL Lambda**

```yaml
Policies:
  - Version: '2012-10-17'
    Statement:
      # S3 Presigned URL generation
      - Sid: S3PresignedUrl
        Effect: Allow
        Action:
          - s3:PutObject
          - s3:PutObjectAcl
        Resource: !Sub 'arn:aws:s3:::${ExistingBucketName}/*'
      
      # DynamoDB write access
      - Sid: DdbWrite
        Effect: Allow
        Action:
          - dynamodb:PutItem
          - dynamodb:DescribeTable
        Resource: !Sub 'arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${ExistingTableName}'
      
      # KMS encryption for S3
      - Sid: KMSEncrypt
        Effect: Allow
        Action:
          - kms:Encrypt
          - kms:Decrypt
          - kms:GenerateDataKey*
          - kms:DescribeKey
        Resource: !Sub 'arn:aws:kms:${AWS::Region}:${AWS::AccountId}:key/${ExistingKMSKeyId}'
      
      # EventBridge rule creation
      - Sid: EventBridgeScheduling
        Effect: Allow
        Action:
          - events:PutRule
          - events:PutTargets
          - events:DeleteRule
          - events:RemoveTargets
          - sts:GetCallerIdentity
        Resource: 
          - !Sub "arn:aws:events:${AWS::Region}:${AWS::AccountId}:rule/cleanup-*"
          - "*"
```

### Resource-Based Policies

**S3 → Lambda Permission**:

```yaml
DocReceivedS3Permission:
  Type: AWS::Lambda::Permission
  Properties:
    FunctionName: !Ref DocReceivedFunction
    Action: lambda:InvokeFunction
    Principal: s3.amazonaws.com
    SourceArn: !Sub 'arn:aws:s3:::${ExistingBucketName}'
```

**EventBridge → Lambda Permission**:

```yaml
CleanupExpiredUploadsEventBridgePermission:
  Type: AWS::Lambda::Permission
  Properties:
    FunctionName: !Ref CleanupExpiredUploadsFunction
    Action: lambda:InvokeFunction
    Principal: events.amazonaws.com
    SourceArn: !Sub "arn:aws:events:${AWS::Region}:${AWS::AccountId}:rule/cleanup-*"
```

### API Gateway Execution Role

Some services create an API Gateway CloudWatch role:

```yaml
CompaniesApiRole:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: apigateway.amazonaws.com
          Action: sts:AssumeRole
    ManagedPolicyArns:
      - arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs
```

---

## API Gateway Configuration

### HTTP API vs REST API

| Feature | HTTP API | REST API |
|---------|----------|----------|
| **Services Using** | Job Listings, Bookings | Companies, Docs Upload, Backoffice |
| **Cost** | Cheaper (~70% less) | More expensive |
| **Authorizers** | JWT (Cognito) | Cognito User Pool, Lambda, IAM |
| **Request Validation** | Basic | Advanced with models |
| **Usage Plans** | No | Yes |
| **API Keys** | No | Yes |
| **When to use** | Simple JWT auth | Complex auth, throttling |

### Cognito Authorizer Configuration

**REST API (Companies, Docs Upload)**:

```yaml
CompaniesApi:
  Type: AWS::Serverless::Api
  Properties:
    Auth:
      DefaultAuthorizer: CognitoAuthorizer
      Authorizers:
        CognitoAuthorizer:
          UserPoolArn: !Ref CognitoUserPoolArn
```

**HTTP API (Job Listings)**:

```yaml
JobListingsHttpApi:
  Type: AWS::Serverless::HttpApi
  Properties:
    Auth:
      Authorizers:
        CognitoAuthorizer:
          IdentitySource: $request.header.Authorization
          JwtConfiguration:
            Issuer: !Sub 'https://cognito-idp.${AWS::Region}.amazonaws.com/${CognitoUserPoolId}'
            Audience: [!Ref CognitoUserPoolClientId]
```

### CORS Configuration

**Permissive CORS (Dev)**:

```yaml
Cors:
  AllowMethods: "'GET,POST,PUT,DELETE,OPTIONS'"
  AllowHeaders: "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
  AllowOrigin: "'*'"
  MaxAge: "'600'"
```

**Note**: In production, replace `'*'` with specific domains.

### Endpoint Types

All APIs use **REGIONAL** endpoints:

```yaml
EndpointConfiguration:
  Type: REGIONAL
```

**Why REGIONAL?**
- Lower latency (no global routing)
- Simpler setup (no custom domain needed)
- Cost-effective for single-region deployment

---

## Lambda Configuration

### Runtime Versions

| Service | Runtime | Reason |
|---------|---------|--------|
| Docs Upload | Python 3.13 | Latest features, testing compatibility |
| Companies | Python 3.11 | Stable, well-tested |
| Job Listings | Python 3.11 | Stable, well-tested |
| Bookings | Python 3.11 | Stable, well-tested |

### Memory and Timeout Settings

| Function Type | Memory | Timeout | Use Case |
|--------------|--------|---------|----------|
| Simple CRUD | 256-512 MB | 10-30s | Get, create, list |
| Complex Logic | 512 MB | 30s | Search, validation |
| File Processing | 1024 MB | 60s | Document scan |
| Async Workers | 256 MB | 60s | Cleanup, background |

**Example Configuration**:

```yaml
Globals:
  Function:
    Runtime: python3.11
    Timeout: 30
    MemorySize: 512
```

**Function-Specific Override**:

```yaml
DocScanFunction:
  Type: AWS::Serverless::Function
  Properties:
    Timeout: 60        # Override: longer timeout
    MemorySize: 1024   # Override: more memory for file processing
```

### Environment Variables

**Global Variables** (all functions in stack):

```yaml
Globals:
  Function:
    Environment:
      Variables:
        ENVIRONMENT: !Ref Environment
        REGION: !Ref AWS::Region
        TABLE_NAME: !Sub '${Environment}-Companies'
        LOG_LEVEL: INFO
```

**Function-Specific Variables**:

```yaml
PresignUrlFunction:
  Type: AWS::Serverless::Function
  Properties:
    Environment:
      Variables:
        BUCKET: !Ref ExistingBucketName
        KMS_KEY_ID: !Ref ExistingKMSKeyId
        CLEANUP_FUNCTION_NAME: !Ref CleanupExpiredUploadsFunction
```

### Lambda Layers

**Not currently used** in MVP. Future consideration:
- Shared libraries (boto3 updates, custom packages)
- Common utilities across functions
- Reduces deployment package size

---

## DynamoDB Configuration

### Table Creation

**Option 1: Separate Data Stack** (Recommended)

```yaml
# infra/data/companies/template.yaml
Resources:
  CompaniesTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub '${Environment}-Companies'
      BillingMode: PAY_PER_REQUEST  # On-demand
      AttributeDefinitions:
        - AttributeName: userId
          AttributeType: S
      KeySchema:
        - AttributeName: userId
          KeyType: HASH
      PointInTimeRecoverySpecification:
        PointInTimeRecoveryEnabled: false  # Enable in prod
      SSESpecification:
        SSEEnabled: true  # AWS-managed encryption
      Tags:
        - Key: Environment
          Value: !Ref Environment
```

**Option 2: Inline in Service Stack**

Referenced by ARN if pre-existing, or created if needed.

### Billing Mode

**PAY_PER_REQUEST (On-Demand)**:
- ✅ No capacity planning needed
- ✅ Auto-scales with traffic
- ✅ Cost-effective for unpredictable workloads
- ❌ Slightly more expensive per request

Used for all tables in MVP.

### Encryption

**Server-Side Encryption**:
- **Type**: AWS-managed keys (default)
- **At Rest**: Always enabled
- **In Transit**: TLS 1.2+

**Future**: Customer-managed KMS keys for enhanced control.

### Backup and Recovery

**Dev Environment**:
- Point-in-Time Recovery: **Disabled**
- On-Demand Backups: **Manual only**

**Prod Environment** (to enable):
- Point-in-Time Recovery: **Enabled** (35-day retention)
- On-Demand Backups: **Automated** (daily)

---

## S3 Configuration

### User Documents Bucket

**Name**: `4seasonsjob-dev-userdocs-eusouth1`

**Configuration**:

```yaml
Resources:
  UserDocsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: 4seasonsjob-dev-userdocs-eusouth1
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: aws:kms
              KMSMasterKeyID: !Ref DocumentsKMSKey
      VersioningConfiguration:
        Status: Enabled
      LifecycleConfiguration:
        Rules:
          - Id: DeleteExpiredDocs
            Status: Enabled
            ExpirationInDays: 365  # Delete after 1 year
      NotificationConfiguration:
        LambdaConfigurations:
          - Event: s3:ObjectCreated:*
            Function: !GetAtt DocReceivedFunction.Arn
            Filter:
              S3Key:
                Rules:
                  - Name: prefix
                    Value: docs/
```

**KMS Key for Encryption**:

```yaml
DocumentsKMSKey:
  Type: AWS::KMS::Key
  Properties:
    Description: KMS key for user documents encryption
    KeyPolicy:
      Version: '2012-10-17'
      Statement:
        - Sid: Enable IAM User Permissions
          Effect: Allow
          Principal:
            AWS: !Sub 'arn:aws:iam::${AWS::AccountId}:root'
          Action: 'kms:*'
          Resource: '*'
        
        - Sid: Allow Lambda to use key
          Effect: Allow
          Principal:
            Service: lambda.amazonaws.com
          Action:
            - kms:Decrypt
            - kms:GenerateDataKey
          Resource: '*'
          Condition:
            StringEquals:
              kms:ViaService: !Sub 's3.${AWS::Region}.amazonaws.com'

DocumentsKMSKeyAlias:
  Type: AWS::KMS::Alias
  Properties:
    AliasName: alias/4seasonsjob-userdocs
    TargetKeyId: !Ref DocumentsKMSKey
```

### Company Assets Bucket

**Name**: `{env}-beezey-companies-assets`

**Configuration**:
- Public Access: Blocked
- Encryption: AWS-managed
- CORS: Enabled for web uploads
- Lifecycle: No expiration (keep indefinitely)

---

## Environment Variables

### Standard Variables (All Lambdas)

| Variable | Value | Purpose |
|----------|-------|---------|
| `ENVIRONMENT` | `dev` / `prod` | Current environment |
| `REGION` | `eu-south-1` | AWS region |
| `AWS_REGION` | `eu-south-1` | SDK default region |

### Service-Specific Variables

**Companies Service**:
- `COMPANIES_TABLE_NAME`: `{env}-Companies`
- `COMPANIES_BUCKET_NAME`: `{env}-beezey-companies-assets`
- `LOG_LEVEL`: `INFO`

**Job Listings Service**:
- `JOB_LISTINGS_TABLE_NAME`: `JobListings-{env}`

**Docs Upload Service**:
- `BUCKET`: `4seasonsjob-dev-userdocs-eusouth1`
- `BUCKET_REGION`: `eu-south-1`
- `KMS_KEY_ID`: `7f604da7-7b4a-45ca-9708-630fcee29ecd`
- `TABLE_NAME`: `UserDocuments2`
- `CLEANUP_FUNCTION_NAME`: `cleanup-expired-uploads`
- `DOC_SCAN_FUNCTION_NAME`: `doc-scan`

---

## Outputs and Exports

### Stack Outputs

Every service stack exports key values for cross-stack references:

```yaml
Outputs:
  # API Gateway URL
  CompaniesApiUrl:
    Description: API Gateway endpoint URL for Companies API
    Value: !Sub 'https://${CompaniesApi}.execute-api.${AWS::Region}.amazonaws.com/${Environment}'
    Export:
      Name: !Sub '${Environment}-CompaniesApiUrl'

  # API Gateway ID
  CompaniesApiId:
    Description: API Gateway ID
    Value: !Ref CompaniesApi
    Export:
      Name: !Sub '${Environment}-CompaniesApiId'

  # Lambda ARN
  CreateCompanyFunctionArn:
    Description: ARN of CreateCompany Lambda function
    Value: !GetAtt CreateCompanyFunction.Arn
    Export:
      Name: !Sub '${Environment}-CreateCompanyFunctionArn'
```

### Using Exports in Other Stacks

```yaml
# In another stack, reference exported value
CompaniesApiUrl:
  Type: String
  Default: !ImportValue dev-CompaniesApiUrl
```

### Docs Upload Service Outputs

```yaml
Outputs:
  PresignUrlEndpoint:
    Description: "Presign URL API Endpoint"
    Value: !Sub "https://${DocumentsApi}.execute-api.${AWS::Region}.amazonaws.com/${StageName}/documents/upload-url"
  
  GetUserDocsStatusEndpoint:
    Description: "Get User Documents Status API Endpoint"
    Value: !Sub "https://${DocumentsApi}.execute-api.${AWS::Region}.amazonaws.com/${StageName}/user/{userId}/documents/status"
  
  ApiGatewayEndpoint:
    Description: "API Gateway Base URL"
    Value: !Sub "https://${DocumentsApi}.execute-api.${AWS::Region}.amazonaws.com/${StageName}/"
  
  KMSKeyId:
    Description: "KMS Key ID used for S3 encryption"
    Value: !Ref ExistingKMSKeyId
    Export:
      Name: !Sub "${AWS::StackName}-KMSKeyId"
```

---

## 📚 Next Steps

Continue to the data model documentation:

**[Next: Data Model →](./03-data-model.md)**

Learn about DynamoDB table schemas, access patterns, and key design.

---

## 🧭 Navigation

- **[← Back: System Overview](./01-overview.md)**
- **[Architecture Home](./README.md)**
- **[Main Documentation](../../README.md)**
- **[Next: Data Model →](./03-data-model.md)**