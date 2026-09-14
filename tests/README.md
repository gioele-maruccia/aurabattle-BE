# API Testing Framework

Comprehensive testing framework for all Beezey platform APIs with automatic authentication, dynamic parameters, and detailed reporting.

## Directory Structure

```
tests/
├── README.md                          # This file
├── setup.sh                           # Initial setup script
├── run-tests.sh                       # Helper to run from any location
├── config/
│   ├── env.dev.json                   # Dev environment config
│   ├── env.prod.json                  # Prod environment config
│   └── auth.json                      # Auth tokens (gitignored)
├── test-suites/
│   ├── job-listings/
│   │   ├── suite.json                 # Test suite definition
│   │   ├── README.md                  # Suite-specific documentation
│   │   └── payloads/                  # Test payload files
│   ├── companies/
│   │   ├── suite.json                 # 23 comprehensive tests
│   │   ├── README.md                  # Companies API documentation
│   │   └── payloads/                  # 10 payload files
│   └── bookings/
│       ├── suite.json
│       └── payloads/
├── scripts/
│   ├── test-runner.sh                 # Main test runner
│   ├── auth-helper.sh                 # Get and manage tokens
│   └── utils.sh                       # Utility functions
└── results/
    └── .gitkeep                       # Test results (gitignored)
```

## Available Test Suites

### 📦 Companies API (23 tests)
Complete CRUD operations for company profiles:
- **Create**: Minimal profile with businessName and vatNumber
- **Update**: Description, location, images (with presigned URLs)
- **Get**: By userId (authenticated) and companyId (public)
- **Delete**: Soft delete with status preservation

**Coverage**: Creation (7), Updates (8), Retrieval (4), Deletion (4)

### 📋 Job Listings API
Job posting management with status transitions:
- Create, publish, pause, and republish listings
- Multiple status workflows (draft → published → paused)
- Authorization and validation tests

### 📅 Bookings API
Booking management and workflows (coming soon)

## Quick Start

### 1. Initial Setup
```bash
cd tests
chmod +x setup.sh
./setup.sh
```

This will:
- ✓ Check dependencies (curl, jq, aws-cli)
- ✓ Create directory structure
- ✓ Generate config templates
- ✓ Create payload examples
- ✓ Set up .gitignore

### 2. Configure Environment

Edit `config/env.dev.json`:
- Update test user email addresses
- Verify API Gateway URLs
- Configure Cognito User Pool details

**Get API URLs from CloudFormation:**

```bash
# Companies API
aws cloudformation describe-stacks \
  --stack-name dev-companies-api \
  --query 'Stacks[0].Outputs[?OutputKey==`CompaniesApiUrl`].OutputValue' \
  --output text \
  --region eu-south-1

# Job Listings API
aws cloudformation describe-stacks \
  --stack-name seasonal-jobs-joblistings-services-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`JobListingsApiUrl`].OutputValue' \
  --output text \
  --region eu-south-1
```

### 3. Authenticate Test Users

```bash
# IMPORTANT: Run from tests directory
cd tests

# Primary company user
./scripts/auth-helper.sh login --type company --env dev

# Secondary company user (for authorization tests)
./scripts/auth-helper.sh login --type company2 --env dev

# Worker user
./scripts/auth-helper.sh login --type worker --env dev

# Backoffice operator
./scripts/auth-helper.sh login --type backoffice --env dev
```

### 4. Run Tests

```bash
# Option 1: Using helper wrapper (works from any directory)
./run-tests.sh --suite companies --env dev

# Option 2: Direct call (must be in tests directory)
cd tests
./scripts/test-runner.sh --suite companies --env dev
```

## Usage Examples

### Run All Tests in a Suite
```bash
# Companies API - all 23 tests
./run-tests.sh --suite companies --env dev

# Job Listings API - all tests
./run-tests.sh --suite job-listings --env dev
```

### Run Specific Test
```bash
# Companies - create test only
./run-tests.sh --suite companies --test create-company-valid --env dev

# Job Listings - specific test
./run-tests.sh --suite job-listings --test create-listing-valid --env dev
```

### Verbose Mode (See Full Requests/Responses)
```bash
./run-tests.sh --suite companies --env dev --verbose
```

### Generate Test Report
```bash
./run-tests.sh --suite companies --env dev --report
```

### Debug Mode (Maximum Detail)
```bash
./run-tests.sh --suite companies --env dev --debug --verbose
```

### Specify Authentication Type
```bash
./run-tests.sh --suite companies --env dev --auth company
```

## Configuration Files

### env.{environment}.json
Environment-specific configuration:
- **APIs**: Base URLs and stack names for all services
- **Cognito**: User Pool IDs and Client IDs
- **Test Users**: Email addresses and groups
- **AWS Resources**: S3 buckets, DynamoDB tables

Example structure:
```json
{
  "environment": "dev",
  "region": "eu-south-1",
  "cognito": {
    "users": { "userPoolId": "...", "clientId": "..." }
  },
  "apis": {
    "companies": { "baseUrl": "https://..." },
    "jobListings": { "baseUrl": "https://..." }
  },
  "testUsers": {
    "company": { "username": "company@example.com" },
    "worker": { "username": "worker@example.com" }
  }
}
```

### auth.json (gitignored)
Stores authentication tokens:
- JWT tokens for different user types
- Refresh tokens for automatic renewal
- Token expiration timestamps

**Never commit this file** - it contains sensitive authentication data.

### suite.json
Defines test cases for a specific API:
- Test metadata (id, name, description)
- HTTP method and endpoint
- Authentication requirements
- Request payload references
- Expected status codes
- Response assertions
- Dynamic parameter mappings

## Test Suite Features

### Dynamic Parameters
Tests can reference results from previous tests:

```json
{
  "endpoint": "/companies/{userId}",
  "dynamicParams": {
    "userId": "fromPreviousTest:create-company-valid:$.company.userId"
  }
}
```

This allows complex test workflows like:
1. Create company → stores companyId
2. Update company → uses companyId from step 1
3. Get company → verifies updates from step 2
4. Delete company → removes company from step 1

### Multiple Authentication Types
- **company**: Primary company user (creates/manages companies)
- **company2**: Secondary company user (for authorization tests)
- **worker**: Worker user (should be denied company operations)
- **backoffice**: Backoffice operator (admin operations)
- **none**: No authentication (public endpoints)

### Comprehensive Assertions
```json
{
  "assertions": [
    {
      "type": "status",
      "value": 201
    },
    {
      "type": "jsonPath",
      "path": "$.company.companyId",
      "exists": true
    },
    {
      "type": "jsonPath",
      "path": "$.company.status",
      "value": "active"
    }
  ]
}
```

## Troubleshooting

### "Config file not found" error

**Problem:** Scripts can't find config files

**Solution:** Always run from tests directory or use the wrapper

```bash
# ✓ Correct - using wrapper
cd tests
./run-tests.sh --suite companies --env dev

# ✓ Correct - direct from tests/
cd tests
./scripts/test-runner.sh --suite companies --env dev

# ✗ Wrong - from wrong directory
cd /some/other/path
./tests/scripts/test-runner.sh --suite companies --env dev
```

### "Could not get authentication token"

**Problem:** Token expired or not present

**Solution:** Re-authenticate
```bash
cd tests
./scripts/auth-helper.sh login --type company --env dev
```

**Check token status:**
```bash
jq '.dev.company' config/auth.json
```

### "Could not resolve dynamic param"

**Problem:** Referenced test hasn't run or failed

**Solution:** Run tests in order or run full suite
```bash
# Run full suite (handles dependencies automatically)
./run-tests.sh --suite companies --env dev

# Or run tests in dependency order
./run-tests.sh --suite companies --test create-company-valid --env dev
./run-tests.sh --suite companies --test update-company-description --env dev
```

### "Missing required dependencies"

**Problem:** curl, jq, or aws-cli not installed

**Solution:** Install missing tools
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install curl jq
pip install awscli

# macOS
brew install curl jq
pip install awscli

# Verify installation
curl --version
jq --version
aws --version
```

### "API Gateway URL contains placeholder"

**Problem:** Environment config not updated with actual URLs

**Solution:** Get URL from CloudFormation and update config
```bash
# Get actual API URL
aws cloudformation describe-stacks \
  --stack-name dev-companies-api \
  --query 'Stacks[0].Outputs[?OutputKey==`CompaniesApiUrl`].OutputValue' \
  --output text \
  --region eu-south-1

# Update config/env.dev.json with the actual URL
```

### "403 Forbidden" on authorization tests

**Problem:** company2 user not configured or not logged in

**Solution:** Set up and authenticate second company user
```bash
# 1. Add company2 email to config/env.dev.json
# 2. Login as company2
./scripts/auth-helper.sh login --type company2 --env dev
```

## Suite-Specific Documentation

Each test suite has detailed documentation:

- **Companies API**: `test-suites/companies/README.md`
  - Complete workflow examples
  - Image upload process
  - Validation rules
  - All 23 tests explained

- **Job Listings API**: `test-suites/job-listings/README.md`
  - Status transitions
  - Publishing workflows
  - Booking integration

## Advanced Features

### Test Reports
Generate detailed test reports:
```bash
./run-tests.sh --suite companies --env dev --report
```

Report includes:
- Total/Passed/Failed/Skipped counts
- Execution timestamp
- Test duration
- Detailed results

Reports saved to: `results/companies_dev_YYYYMMDD_HHMMSS.txt`

### Continuous Integration

Example GitHub Actions workflow:
```yaml
name: API Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup
        run: cd tests && ./setup.sh
      - name: Authenticate
        run: cd tests && ./scripts/auth-helper.sh login --type company --env dev
        env:
          COMPANY_PASSWORD: ${{ secrets.COMPANY_TEST_PASSWORD }}
      - name: Run Tests
        run: cd tests && ./run-tests.sh --suite companies --env dev --report
```

### Performance Testing
Measure API response times:
```bash
# Run with timing
time ./run-tests.sh --suite companies --env dev

# Individual test timing
time ./run-tests.sh --suite companies --test create-company-valid --env dev
```

## Best Practices

### Directory Navigation
Always work from the `tests/` directory:
```bash
cd tests
./run-tests.sh [options]
./scripts/auth-helper.sh [options]
```

### Token Management
- Tokens expire after 1 hour
- Use refresh tokens when possible
- Re-authenticate if tests fail with 401

### Test Dependencies
- Run full suite for first-time testing
- Use specific tests for debugging
- Check suite README for test dependencies

### Security
- Never commit `config/auth.json`
- Keep test user credentials secure
- Use separate test users for each environment
- Rotate test user passwords regularly

## File Structure Guidelines

### Payload Files
- JSON format
- Descriptive names (create-company-valid.json)
- Valid examples for success cases
- Invalid examples for error cases
- Keep under 100 lines for readability

### Test Suites
- One suite per API/domain
- Group related tests together
- Use descriptive test IDs
- Document test dependencies
- Maintain ~20-30 tests per suite max

## Getting Help

### Documentation
- General framework: `tests/README.md` (this file)
- Suite-specific: `test-suites/{suite}/README.md`
- Script help: `./scripts/test-runner.sh --help`

### Debug Information
```bash
# Enable debug mode
./run-tests.sh --suite companies --env dev --debug

# Check logs
cat results/*.txt
tail -f proxy.log  # If using swagger proxy

# Verify configuration
jq '.' config/env.dev.json
jq '.' config/auth.json
```

### Common Commands Reference
```bash
# Setup
./setup.sh

# Authenticate
./scripts/auth-helper.sh login --type company --env dev

# Run all tests
./run-tests.sh --suite companies --env dev

# Run specific test
./run-tests.sh --suite companies --test create-company-valid --env dev

# Verbose mode
./run-tests.sh --suite companies --env dev --verbose

# Generate report
./run-tests.sh --suite companies --env dev --report

# Debug mode
./run-tests.sh --suite companies --env dev --debug --verbose
```

## Contributing

### Adding New Test Suites

1. Create directory structure:
```bash
mkdir -p test-suites/new-api/payloads
```

2. Create suite.json with test definitions

3. Create payload files in payloads/

4. Create suite-specific README.md

5. Update config/env.dev.json with API URL

6. Test the suite:
```bash
./run-tests.sh --suite new-api --env dev
```

### Adding New Tests

1. Add test definition to suite.json
2. Create payload file if needed
3. Run test to verify:
```bash
./run-tests.sh --suite {suite} --test {test-id} --env dev --verbose
```

---

**Framework Version**: 1.0  
**Last Updated**: January 2025  
**Supported APIs**: Companies, Job Listings, Bookings (coming soon)