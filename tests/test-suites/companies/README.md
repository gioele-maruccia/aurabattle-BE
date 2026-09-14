# Companies API Test Suite

Complete test suite for the Companies API, covering all CRUD operations and edge cases.

## Overview

This test suite covers:
- **Create Company**: Minimal profile creation with businessName and vatNumber
- **Update Company**: Add description, location, and manage images
- **Get Company**: Retrieve by userId (authenticated) and companyId (public)
- **Delete Company**: Soft delete functionality

## Test Coverage

### Create Company Tests (7 tests)
- ✅ Valid company creation
- ✅ Duplicate prevention (409 conflict)
- ✅ Invalid VAT number format
- ✅ Missing required fields
- ✅ Business name too short
- ✅ Unauthorized worker attempt
- ✅ No authentication

### Update Company Tests (8 tests)
- ✅ Add description and location
- ✅ Request presigned URLs for images
- ✅ Save media URLs after upload
- ✅ Invalid coordinates validation
- ✅ Missing required location fields
- ✅ Description too long (>2000 chars)
- ✅ Authorization check (not owner)
- ✅ Company not found

### Get Company Tests (4 tests)
- ✅ Get by userId (authenticated)
- ✅ Get by userId - not found
- ✅ Get by companyId (public, no auth)
- ✅ Get by companyId - not found

### Delete Company Tests (4 tests)
- ✅ Soft delete success
- ✅ Already deleted
- ✅ Authorization check (not owner)
- ✅ Company not found

**Total: 23 comprehensive tests**

## Prerequisites

### 1. Environment Setup

Update `config/env.dev.json` with Companies API URL:

```bash
# Get API URL from CloudFormation
aws cloudformation describe-stacks \
  --stack-name dev-companies-api \
  --query 'Stacks[0].Outputs[?OutputKey==`CompaniesApiUrl`].OutputValue' \
  --output text \
  --region eu-south-1
```

Add to `config/env.dev.json`:
```json
{
  "apis": {
    "companies": {
      "baseUrl": "https://YOUR_API_ID.execute-api.eu-south-1.amazonaws.com/dev",
      "stackName": "dev-companies-api"
    }
  }
}
```

### 2. Authentication

You need TWO company users for authorization tests:

```bash
cd tests

# Login as primary company user
./scripts/auth-helper.sh login --type company --env dev

# Login as secondary company user (for authorization tests)
./scripts/auth-helper.sh login --type company2 --env dev
```

### 3. Test User Configuration

Add to `config/env.dev.json`:

```json
{
  "testUsers": {
    "company": {
      "username": "company1@example.com"
    },
    "company2": {
      "username": "company2@example.com"
    },
    "worker": {
      "username": "worker@example.com"
    }
  }
}
```

## Running Tests

### Run All Companies Tests
```bash
cd tests
./run-tests.sh --suite companies --env dev
```

### Run Specific Test
```bash
./run-tests.sh --suite companies --test create-company-valid --env dev
```

### Verbose Mode (See Detailed Requests/Responses)
```bash
./run-tests.sh --suite companies --env dev --verbose
```

### Generate Report
```bash
./run-tests.sh --suite companies --env dev --report
```

### Debug Mode
```bash
./run-tests.sh --suite companies --env dev --debug
```

## Test Flow and Dependencies

The test suite is designed with **dynamic parameters** that reference previous test results:

```
1. create-company-valid
   └─> Stores: companyId, userId
       │
       ├─> update-company-description (uses userId)
       ├─> update-company-request-images (uses userId)
       ├─> update-company-save-media (uses userId)
       ├─> get-company-by-userid (uses userId)
       ├─> get-company-public (uses companyId)
       └─> delete-company-success (uses userId)
           └─> delete-company-already-deleted (uses same userId)
```

### Test Dependencies

**Independent tests** (can run alone):
- All validation error tests
- create-company-valid (creates new company)
- create-company-duplicate (depends on previous creation)

**Dependent tests** (require create-company-valid):
- All update-company-* tests
- All get-company-* tests  
- All delete-company-* tests

## Payload Files Structure

```
test-suites/companies/payloads/
├── create-company-valid.json              # Valid minimal company
├── create-company-invalid-vat.json        # Invalid VAT format
├── create-company-missing-fields.json     # Missing required fields
├── create-company-short-name.json         # Name too short
├── update-company-description.json        # Add description + location
├── update-company-request-images.json     # Request presigned URLs
├── update-company-save-media.json         # Save uploaded image URLs
├── update-company-invalid-coordinates.json # Invalid lat/lon
├── update-company-missing-city.json       # Location without city
└── update-company-description-too-long.json # Description > 2000 chars
```

## Expected Results by Test Category

### ✅ Success Cases (201/200 Status)
- **create-company-valid**: Returns companyId, userId, businessName, vatNumber
- **update-company-description**: Returns updated company with location
- **update-company-request-images**: Returns presigned URLs (uploadUrl, key, publicUrl)
- **update-company-save-media**: Returns company with saved media URLs
- **get-company-by-userid**: Returns full company profile
- **get-company-public**: Returns public company info (no sensitive data)
- **delete-company-success**: Returns confirmation with deletedAt timestamp

### ❌ Validation Errors (400 Status)
- **create-company-invalid-vat**: "vatNumber must follow format: 2 uppercase letters + 10 digits"
- **create-company-missing-fields**: "Missing required field: vatNumber"
- **create-company-short-name**: "businessName must be between 2 and 200 characters"
- **update-company-invalid-coordinates**: "latitude must be between -90 and 90"
- **update-company-missing-city**: "location.city is required when location is provided"
- **update-company-description-too-long**: "description must not exceed 2000 characters"

### 🚫 Authorization Errors (403 Status)
- **create-company-unauthorized-worker**: Workers cannot create companies
- **update-company-not-owner**: Cannot update another company's profile
- **delete-company-not-owner**: Cannot delete another company's profile

### 🔒 Authentication Errors (401 Status)
- **create-company-no-auth**: Missing authentication token

### 🔍 Not Found Errors (404 Status)
- **update-company-not-found**: Company profile not found
- **get-company-by-userid-not-found**: Company not found
- **get-company-public-not-found**: Company not found
- **delete-company-not-found**: Company profile not found

### ⚠️ Conflict Errors (409 Status)
- **create-company-duplicate**: Company already exists for this user

## Troubleshooting

### Common Issues

#### 1. "Could not resolve dynamic param"
**Problem**: A test depends on a previous test that hasn't run or failed

**Solution**: Run the full suite, or run dependent tests in order:
```bash
# Run all tests in sequence
./run-tests.sh --suite companies --env dev

# Or run specific tests in order
./run-tests.sh --suite companies --test create-company-valid --env dev
./run-tests.sh --suite companies --test update-company-description --env dev
```

#### 2. "Could not get authentication token"
**Problem**: Token expired or not present

**Solution**: Login again:
```bash
cd tests
./scripts/auth-helper.sh login --type company --env dev
```

#### 3. "Company already exists" on first run
**Problem**: Test user already has a company profile from previous test runs

**Solution**: Either:
- Delete the company via API or DynamoDB console
- Use a different test user
- Run the full suite which handles duplicates

#### 4. "Authorization failed" tests
**Problem**: company2 user not configured

**Solution**: Configure and login as company2:
```bash
# Add company2 to config/env.dev.json
# Then login
./scripts/auth-helper.sh login --type company2 --env dev
```

#### 5. "API Gateway routing" issues
**Problem**: Requests going to wrong API Gateway

**Solution**: Check `swagger/auth-proxy.js` routing configuration:
```javascript
routeMapping: {
  '/companies/public/': 'companies',
  '/companies': 'companies',
  // ...
}
```

## Manual Testing Examples

### Using curl (with auth-proxy running)

```bash
# Set your token
TOKEN="your-jwt-token-here"

# Create company
curl -X POST http://localhost:8081/companies \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "businessName": "Test Company",
    "vatNumber": "IT1234567890"
  }'

# Update company
curl -X PUT http://localhost:8081/companies/USER_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "A great company",
    "location": {
      "city": "Milan",
      "country": "Italy",
      "coordinates": {"lat": 45.4642, "lon": 9.1900}
    }
  }'

# Get company by userId (authenticated)
curl -X GET http://localhost:8081/companies/USER_ID \
  -H "Authorization: Bearer $TOKEN"

# Get company by companyId (public, no auth needed)
curl -X GET http://localhost:8081/companies/public/COMPANY_ID

# Request image upload URLs
curl -X PUT http://localhost:8081/companies/USER_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "requestProfileImage": true,
    "requestGalleryImages": 3
  }'

# Delete company (soft delete)
curl -X DELETE http://localhost:8081/companies/USER_ID \
  -H "Authorization: Bearer $TOKEN"
```

## Integration with Other Services

### Companies API integrates with:

1. **Job Listings API**
   - Job listings reference companyId
   - Companies must be approved before creating listings

2. **User Verification Workflow**
   - Users must be in "companies" Cognito group
   - Profile type must be "company"

3. **S3 Bucket**
   - Profile images: `companies/{companyId}/profile.jpg`
   - Gallery images: `companies/{companyId}/gallery/{1-5}.jpg`

## Image Upload Workflow

The complete workflow for uploading images:

```bash
# Step 1: Create company (minimal)
POST /companies
{
  "businessName": "Test Company",
  "vatNumber": "IT1234567890"
}
# Returns: companyId, userId

# Step 2: Add description and location
PUT /companies/{userId}
{
  "description": "Our company description",
  "location": { "city": "Milan", "country": "Italy" }
}

# Step 3: Request presigned URLs
PUT /companies/{userId}
{
  "requestProfileImage": true,
  "requestGalleryImages": 3
}
# Returns: uploadUrls with presigned S3 URLs

# Step 4: Upload images to S3 using presigned URLs
# (Use PUT method with Content-Type: image/jpeg)
curl -X PUT "PRESIGNED_URL" \
  -H "Content-Type: image/jpeg" \
  --data-binary @image.jpg

# Step 5: Save image URLs to company profile
PUT /companies/{userId}
{
  "media": {
    "profileImageUrl": "https://bucket.s3.amazonaws.com/companies/uuid/profile.jpg",
    "galleryImages": ["url1", "url2", "url3"]
  }
}
```

## Test Execution Order (Recommended)

For best results, run tests in this sequence:

### Phase 1: Creation Tests
1. create-company-valid ✓
2. create-company-duplicate ✓
3. create-company-invalid-vat ✓
4. create-company-missing-fields ✓
5. create-company-short-name ✓
6. create-company-unauthorized-worker ✓
7. create-company-no-auth ✓

### Phase 2: Update Tests
8. update-company-description ✓
9. update-company-request-images ✓
10. update-company-save-media ✓
11. update-company-invalid-coordinates ✓
12. update-company-missing-city ✓
13. update-company-description-too-long ✓
14. update-company-not-owner ✓
15. update-company-not-found ✓

### Phase 3: Retrieval Tests
16. get-company-by-userid ✓
17. get-company-by-userid-not-found ✓
18. get-company-public ✓
19. get-company-public-not-found ✓

### Phase 4: Deletion Tests
20. delete-company-success ✓
21. delete-company-already-deleted ✓
22. delete-company-not-owner ✓
23. delete-company-not-found ✓

## Validation Rules Reference

### BusinessName
- **Required**: Yes
- **Min length**: 2 characters
- **Max length**: 200 characters
- **Format**: Any string

### VAT Number
- **Required**: Yes
- **Format**: `^[A-Z]{2}[0-9]{10}# Companies API Test Suite

Complete test suite for the Companies API, covering all CRUD operations and edge cases.

## Overview

This test suite covers:
- **Create Company**: Minimal profile creation with businessName and vatNumber
- **Update Company**: Add description, location, and manage images
- **Get Company**: Retrieve by userId (authenticated) and companyId (public)
- **Delete Company**: Soft delete functionality

## Test Coverage

### Create Company Tests (7 tests)
- ✅ Valid company creation
- ✅ Duplicate prevention (409 conflict)
- ✅ Invalid VAT number format
- ✅ Missing required fields
- ✅ Business name too short
- ✅ Unauthorized worker attempt
- ✅ No authentication

### Update Company Tests (8 tests)
- ✅ Add description and location
- ✅ Request presigned URLs for images
- ✅ Save media URLs after upload
- ✅ Invalid coordinates validation
- ✅ Missing required location fields
- ✅ Description too long (>2000 chars)
- ✅ Authorization check (not owner)
- ✅ Company not found

### Get Company Tests (4 tests)
- ✅ Get by userId (authenticated)
- ✅ Get by userId - not found
- ✅ Get by companyId (public, no auth)
- ✅ Get by companyId - not found

### Delete Company Tests (4 tests)
- ✅ Soft delete success
- ✅ Already deleted
- ✅ Authorization check (not owner)
- ✅ Company not found

**Total: 23 comprehensive tests**

## Prerequisites

### 1. Environment Setup

Update `config/env.dev.json` with Companies API URL:

```bash
# Get API URL from CloudFormation
aws cloudformation describe-stacks \
  --stack-name dev-companies-api \
  --query 'Stacks[0].Outputs[?OutputKey==`CompaniesApiUrl`].OutputValue' \
  --output text \
  --region eu-south-1
```

Add to `config/env.dev.json`:
```json
{
  "apis": {
    "companies": {
      "baseUrl": "https://YOUR_API_ID.execute-api.eu-south-1.amazonaws.com/dev",
      "stackName": "dev-companies-api"
    }
  }
}
```

### 2. Authentication

You need TWO company users for authorization tests:

```bash
cd tests

# Login as primary company user
./scripts/auth-helper.sh login --type company --env dev

# Login as secondary company user (for authorization tests)
./scripts/auth-helper.sh login --type company2 --env dev
```

### 3. Test User Configuration

Add to `config/env.dev.json`:

```json
{
  "testUsers": {
    "company": {
      "username": "company1@example.com"
    },
    "company2": {
      "username": "company2@example.com"
    },
    "worker": {
      "username": "worker@example.com"
    }
  }
}
```

## Running Tests

### Run All Companies Tests
```bash
cd tests
./run-tests.sh --suite companies --env dev
```

### Run Specific Test
```bash
./run-tests.sh --suite companies --test create-company-valid --env dev
```

### Verbose Mode (See Detailed Requests/Responses)
```bash
./run-tests.sh --suite companies --env dev --verbose
```

### Generate Report
```bash
./run-tests.sh --suite companies --env dev --report
```

### Debug Mode
```bash
./run-tests.sh --suite companies --env dev --debug
```

## Test Flow and Dependencies

The test suite is designed with **dynamic parameters** that reference previous test results:

```
1. create-company-valid
   └─> Stores: companyId, userId
       │
       ├─> update-company-description (uses userId)
       ├─> update-company-request-images (uses userId)
       ├─> update-company-save-media (uses userId)
       ├─> get-company-by-userid (uses userId)
       ├─> get-company-public (uses companyId)
       └─> delete-company-success (uses userId)
           └─> delete-company-already-deleted (uses same userId)
```

### Test Dependencies

**Independent tests** (can run alone):
- All validation error tests
- create-company-valid (creates new company)
- create-company-duplicate (depends on previous creation)

**Dependent tests** (require create-company-valid):
- All update-company-* tests
- All get-company-* tests  
- All delete-company-* tests

## Payload Files Structure


- **Example**: BE0123456789, IT1234567890
- **Description**: 2 uppercase letters (country code) + 10 digits

### Description
- **Required**: No
- **Max length**: 2000 characters

### Location
- **Required**: No
- **Fields**: When provided, city and country are required
  - `city`: Required if location provided
  - `country`: Required if location provided
  - `coordinates`: Optional
    - `lat`: -90 to 90
    - `lon`: -180 to 180

### Media
- **Profile Image**: 1 image max
- **Gallery Images**: 5 images max
- **Format**: JPEG
- **Presigned URL expiration**: 3600 seconds (1 hour)

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Companies API Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  api-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: eu-south-1
      
      - name: Setup test environment
        run: |
          cd tests
          chmod +x setup.sh
          ./setup.sh
      
      - name: Login and get tokens
        run: |
          cd tests
          ./scripts/auth-helper.sh login --type company --env dev
        env:
          COMPANY_PASSWORD: ${{ secrets.COMPANY_TEST_PASSWORD }}
      
      - name: Run Companies API tests
        run: |
          cd tests
          ./run-tests.sh --suite companies --env dev --report
      
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-results
          path: tests/results/
```

## Metrics and Reporting

After running tests, check the results directory:

```bash
tests/results/companies_dev_20250117_143022.txt
```

Example report:
```
==========================================
Test Report: companies
Environment: dev
Date: 2025-01-17 14:30:22
==========================================

Total Tests: 23
Passed: 23
Failed: 0
Skipped: 0

Result: ✓ ALL TESTS PASSED
```

## Support and Contact

If you encounter issues:

1. Check the **Troubleshooting** section above
2. Review test logs: `tests/results/`
3. Check proxy logs: `tests/proxy.log`
4. Verify API Gateway URL in config
5. Ensure authentication tokens are valid

## Next Steps

After Companies API tests pass:

1. ✅ Run Job Listings tests (depend on Companies)
2. ✅ Run Bookings tests (depend on both)
3. ✅ Integration tests across all services
4. ✅ Load/stress testing
5. ✅ Security testing

---

**Last Updated**: January 2025  
**Version**: 1.0  
**Maintainer**: DevOps Team