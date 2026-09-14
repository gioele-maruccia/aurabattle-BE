# Verify Setup

## 🧭 Navigation

**[← Back: First Deployment](./03-first-deployment.md)** | **[Getting Started Home](./README.md)** | **[Main Documentation](../../README.md)**

---

Now that you've deployed your first service, let's verify everything works correctly by testing the API endpoints.

## 🎯 What You'll Test

We'll test the job-listings service by:
1. Getting a Cognito authentication token
2. Creating a job listing
3. Retrieving the listing
4. Listing all listings

## 🔐 Step 1: Get Cognito Authentication Token

All API endpoints require a valid JWT token from Cognito.

### Option A: Using AWS CLI (Recommended for Testing)

If you have test user credentials:

```bash
aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id YOUR_CLIENT_ID \
  --auth-parameters USERNAME=test@example.com,PASSWORD=YourPassword123! \
  --region eu-south-1
```

This returns a JSON response. Extract the `IdToken`:

```json
{
  "AuthenticationResult": {
    "IdToken": "eyJraWQ...",
    "AccessToken": "eyJraWQ...",
    "RefreshToken": "eyJjdHk...",
    "ExpiresIn": 3600
  }
}
```

Save the `IdToken` to a file for convenience:

```bash
# Save to file
echo "eyJraWQ..." > jwt-token.txt

# Or export as environment variable
export JWT_TOKEN="eyJraWQ..."
```

### Option B: Using the Mobile App

1. Register/login via the Beezey mobile app
2. The app stores the JWT token
3. Extract it from app storage or network inspector
4. Not recommended for development - use Option A instead

### Understanding JWT Claims

The JWT contains user information used by Lambda functions:

```json
{
  "sub": "e65e8250-c061-7022-db46-cc947249f3dc",
  "email": "test@example.com",
  "custom:user_type": "company",
  "cognito:username": "e65e8250-c061-7022-db46-cc947249f3dc"
}
```

The `sub` (subject) is the unique user ID used across all services.

## 🧪 Step 2: Test API Endpoints

### Get Your API URL

From the deployment output, you should have:
```
https://abc123xyz.execute-api.eu-south-1.amazonaws.com
```

If you lost it, retrieve it from CloudFormation:

```bash
aws cloudformation describe-stacks \
  --stack-name seasonal-jobs-joblistings-services-dev \
  --region eu-south-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`JobListingsApiUrl`].OutputValue' \
  --output text
```

### Test 1: Create a Job Listing

**Endpoint:** `POST /listings`

```bash
curl -X POST "https://YOUR_API_URL/listings" \
  -H "Authorization: Bearer $(cat jwt-token.txt)" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Summer Waiter Position",
    "description": "Looking for experienced waiter for summer season",
    "companyId": "company-uuid-here",
    "location": {
      "city": "Milan",
      "region": "Lombardy",
      "country": "IT",
      "address": "Via Roma 123",
      "coordinates": {
        "lat": 45.4642,
        "lon": 9.1900
      }
    },
    "requirements": {
      "minAge": 18,
      "maxAge": 35,
      "experience": "1-2 years",
      "languages": ["Italian", "English"]
    },
    "compensation": {
      "type": "hourly",
      "amount": 12.5,
      "currency": "EUR"
    },
    "workSchedule": {
      "startDate": "2025-06-01",
      "endDate": "2025-09-30",
      "hoursPerWeek": 40
    },
    "positions": {
      "total": 3,
      "filled": 0
    }
  }'
```

**Expected Response (201 Created):**
```json
{
  "message": "Job listing created successfully",
  "listing": {
    "listingId": "123e4567-e89b-12d3-a456-426614174000",
    "companyId": "company-uuid-here",
    "title": "Summer Waiter Position",
    "status": "draft",
    "createdAt": "2025-10-31T10:30:00Z",
    "updatedAt": "2025-10-31T10:30:00Z"
  }
}
```

**Save the `listingId`** for the next tests!

### Test 2: Get the Listing

**Endpoint:** `GET /listings/{listingId}`

```bash
curl -X GET "https://YOUR_API_URL/listings/123e4567-e89b-12d3-a456-426614174000" \
  -H "Authorization: Bearer $(cat jwt-token.txt)"
```

**Expected Response (200 OK):**
```json
{
  "listingId": "123e4567-e89b-12d3-a456-426614174000",
  "companyId": "company-uuid-here",
  "title": "Summer Waiter Position",
  "description": "Looking for experienced waiter for summer season",
  "status": "draft",
  "location": { ... },
  "requirements": { ... },
  "compensation": { ... },
  "workSchedule": { ... },
  "positions": { ... },
  "createdAt": "2025-10-31T10:30:00Z",
  "updatedAt": "2025-10-31T10:30:00Z"
}
```

### Test 3: List All Listings

**Endpoint:** `GET /listings`

```bash
curl -X GET "https://YOUR_API_URL/listings?limit=10&status=draft" \
  -H "Authorization: Bearer $(cat jwt-token.txt)"
```

**Expected Response (200 OK):**
```json
{
  "items": [
    {
      "listingId": "123e4567-e89b-12d3-a456-426614174000",
      "title": "Summer Waiter Position",
      "companyId": "company-uuid-here",
      "status": "draft",
      "createdAt": "2025-10-31T10:30:00Z"
    }
  ],
  "count": 1,
  "lastEvaluatedKey": null
}
```

### Test 4: Update the Listing

**Endpoint:** `PUT /listings/{listingId}`

```bash
curl -X PUT "https://YOUR_API_URL/listings/123e4567-e89b-12d3-a456-426614174000" \
  -H "Authorization: Bearer $(cat jwt-token.txt)" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Summer Waiter Position - Updated",
    "description": "Updated description with more details"
  }'
```

### Test 5: Publish the Listing

**Endpoint:** `POST /listings/{listingId}/publish`

```bash
curl -X POST "https://YOUR_API_URL/listings/123e4567-e89b-12d3-a456-426614174000/publish" \
  -H "Authorization: Bearer $(cat jwt-token.txt)"
```

This changes status from `draft` to `published`.

## 🧪 Testing Other Services

### Test Document Upload (docs-upload service)

The docs-upload service uses a presigned URL flow:

**Step 1: Request presigned URL**
```bash
curl -X POST "https://YOUR_DOCS_API_URL/uploads/presign" \
  -H "Authorization: Bearer $(cat jwt-token.txt)" \
  -H "Content-Type: application/json" \
  -d '{
    "docType": "id_card_front",
    "mime": "image/jpeg",
    "size": 123456
  }'
```

**Response:**
```json
{
  "uploadUrl": "https://4seasonsjob-dev-userdocs-eusouth1.s3.eu-south-1.amazonaws.com/docs/USER_SUB/timestamp_id_card_front.jpg?X-Amz-Algorithm=...",
  "key": "docs/USER_SUB/timestamp_id_card_front.jpg",
  "expiresSec": 300,
  "requiredHeaders": {
    "Content-Type": "image/jpeg",
    "x-amz-server-side-encryption": "aws:kms",
    "x-amz-server-side-encryption-aws-kms-key-id": "arn:aws:kms:...",
    "x-amz-meta-userSub": "USER_SUB",
    "x-amz-meta-docType": "id_card_front",
    "x-amz-meta-uploadTimestamp": "1757336875508"
  }
}
```

**Step 2: Upload file to S3**
```bash
curl -X PUT "PRESIGNED_URL_FROM_RESPONSE" \
  -H "Content-Type: image/jpeg" \
  -H "x-amz-server-side-encryption: aws:kms" \
  -H "x-amz-server-side-encryption-aws-kms-key-id: KMS_KEY_ARN" \
  -H "x-amz-meta-userSub: USER_SUB" \
  -H "x-amz-meta-docType: id_card_front" \
  -H "x-amz-meta-uploadTimestamp: TIMESTAMP" \
  --data-binary "@test.jpg"
```

**Step 3: Check document status**
```bash
curl -X GET "https://YOUR_DOCS_API_URL/uploads/status" \
  -H "Authorization: Bearer $(cat jwt-token.txt)"
```

### Test Company Creation (companies service)

```bash
curl -X POST "https://YOUR_COMPANIES_API_URL/companies" \
  -H "Authorization: Bearer $(cat jwt-token.txt)" \
  -H "Content-Type: application/json" \
  -d '{
    "businessName": "KFC Belgium",
    "vatNumber": "BE0123456789"
  }'
```

**Response:**
```json
{
  "message": "Company created successfully. Use PUT /companies/{userId} to complete the profile.",
  "company": {
    "userId": "e65e8250-c061-7022-db46-cc947249f3dc",
    "companyId": "f89b4567-e12d-34a5-b678-426614174000",
    "businessName": "KFC Belgium",
    "vatNumber": "BE0123456789",
    "status": "active",
    "createdAt": "2025-10-31T10:30:00Z"
  },
  "nextSteps": {
    "endpoint": "/companies/e65e8250-c061-7022-db46-cc947249f3dc",
    "method": "PUT",
    "description": "Complete your company profile with description, location, and images"
  }
}
```

## 📊 Verify in AWS Console

### Check DynamoDB Data

1. Open [DynamoDB Console](https://eu-south-1.console.aws.amazon.com/dynamodb)
2. Select table: `JobListings-dev`
3. Click **Explore table items**
4. You should see your created listing

### Check Lambda Logs

1. Open [CloudWatch Console](https://eu-south-1.console.aws.amazon.com/cloudwatch)
2. Navigate to **Logs > Log groups**
3. Find: `/aws/lambda/CreateListingFunction`
4. Check recent logs for your API call

### Check API Gateway Metrics

1. Open [API Gateway Console](https://eu-south-1.console.aws.amazon.com/apigateway)
2. Select your API
3. Go to **Monitoring**
4. View request count, latency, errors

## 🐛 Troubleshooting

### 401 Unauthorized

**Cause:** Invalid or expired JWT token

**Solution:**
- Generate new token with `aws cognito-idp initiate-auth`
- Verify token not expired (valid for 1 hour)
- Check `Authorization: Bearer TOKEN` header is correct

### 403 Forbidden

**Cause:** User doesn't have permission for this resource

**Solution:**
- Verify Cognito User Pool ARN in deployment
- Check user belongs to correct user pool
- Verify API Gateway authorizer configuration

### 500 Internal Server Error

**Cause:** Lambda function error

**Solution:**
- Check CloudWatch Logs for Lambda function
- Look for Python exceptions
- Verify environment variables are set correctly

### 404 Not Found

**Cause:** Wrong API URL or endpoint path

**Solution:**
- Verify API Gateway URL from CloudFormation outputs
- Check endpoint path matches template.yaml routes
- Ensure stack deployed successfully

### No Response / Timeout

**Cause:** Lambda cold start or network issue

**Solution:**
- Wait 30 seconds and retry (first invocation is slower)
- Check AWS service health dashboard
- Verify security group rules if using VPC

## 📝 Test Script Template

Create a reusable test script `test-api.sh`:

```bash
#!/bin/bash

# Configuration
API_URL="https://YOUR_API_URL"
JWT_TOKEN=$(cat jwt-token.txt)

# Test create listing
echo "Creating job listing..."
LISTING_ID=$(curl -s -X POST "$API_URL/listings" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test Listing","companyId":"test-company"}' \
  | jq -r '.listing.listingId')

echo "Created listing: $LISTING_ID"

# Test get listing
echo "Retrieving listing..."
curl -s -X GET "$API_URL/listings/$LISTING_ID" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  | jq '.'

echo "Tests complete!"
```

Make executable:
```bash
chmod +x test-api.sh
./test-api.sh
```

## ✅ Verification Checklist

Your setup is complete when:

- [ ] JWT token obtained successfully
- [ ] Create listing returns 201 with listingId
- [ ] Get listing returns 200 with full data
- [ ] List listings returns 200 with array
- [ ] DynamoDB table contains your test data
- [ ] CloudWatch logs show successful Lambda invocations
- [ ] No 401, 403, or 500 errors

## 🎉 Success!

Congratulations! You've successfully:
- Deployed a serverless service to AWS
- Authenticated with Cognito
- Created and retrieved data via API
- Verified the deployment works end-to-end

## 📚 Next Steps

Now that your environment is working:

1. **Explore other services**: Deploy bookings, companies, docs-upload
2. **Read architecture docs**: [System Architecture](../architecture/overview.md)
3. **Review API docs**: [API Reference](../api/endpoints-reference.md)
4. **Start developing**: Make changes and redeploy with `sam build && sam deploy`

## 🆘 Still Having Issues?

- Check [Troubleshooting Guide](../operations/troubleshooting.md)
- Review [CloudWatch Logs](https://eu-south-1.console.aws.amazon.com/cloudwatch/home?region=eu-south-1#logsV2:log-groups)
- Ask in team Slack channel #backend-support

---

## 🧭 Navigation

- **[← Back: First Deployment](./03-first-deployment.md)**
- **[Getting Started Home](./README.md)**
- **[Main Documentation](../../README.md)**

### 📚 Continue Learning

- **[System Architecture](../architecture/overview.md)** - Understand the full architecture
- **[API Reference](../api/endpoints-reference.md)** - Complete API documentation
- **[Services Documentation](../services/)** - Deep dive into each microservice
- **[Operations Guide](../operations/)** - Deployment, monitoring, troubleshooting