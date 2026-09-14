# Environment Setup

## 🧭 Navigation

**[← Back: Prerequisites](./01-prerequisites.md)** | **[Getting Started Home](./README.md)** | **[Main Documentation](../../README.md)** | **[Next: First Deployment →](./03-first-deployment.md)**

---

This guide walks you through configuring your local development environment to work with Beezey backend services.

## 🔐 AWS Credentials Configuration

### Method 1: AWS CLI Configure (Recommended for Beginners)

The simplest way to set up credentials:

```bash
aws configure
```

You'll be prompted to enter:

```
AWS Access Key ID [None]: YOUR_ACCESS_KEY_ID
AWS Secret Access Key [None]: YOUR_SECRET_ACCESS_KEY
Default region name [None]: eu-south-1
Default output format [None]: json
```

This creates two files:
- `~/.aws/credentials` - Contains your access keys
- `~/.aws/config` - Contains region and output format

### Method 2: Manual Configuration

Create or edit these files manually:

**~/.aws/credentials:**
```ini
[default]
aws_access_key_id = YOUR_ACCESS_KEY_ID
aws_secret_access_key = YOUR_SECRET_ACCESS_KEY
```

**~/.aws/config:**
```ini
[default]
region = eu-south-1
output = json
```

### Method 3: Environment Variables

For temporary sessions or CI/CD:

```bash
export AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=YOUR_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION=eu-south-1
```

Add these to your shell profile (`~/.bashrc`, `~/.zshrc`) for persistence.

## ✅ Verify AWS Credentials

Test your credentials are working:

```bash
# Check your identity
aws sts get-caller-identity
```

Expected output:
```json
{
    "UserId": "AIDAI...",
    "Account": "881962383770",
    "Arn": "arn:aws:iam::881962383770:user/your-username"
}
```

## 📁 Clone the Repository

If you haven't already, clone the Beezey backend repository:

```bash
git clone <repository-url>
cd beezey-backend
```

## 🏗️ Project Structure Overview

Familiarize yourself with the key directories:

```
beezey-backend/
├── infra/                       # Infrastructure as Code
│   ├── core/                    # Cognito and core services
│   │   └── cognito-setup/
│   ├── data/                    # DynamoDB table definitions
│   │   ├── bookings/
│   │   ├── companies/
│   │   └── job-listings/
│   └── services/                # Lambda service stacks
│       ├── bookings/
│       ├── companies/
│       ├── job-listings/        # ← We'll deploy this first
│       ├── docs-upload/
│       └── user-verification-workflow/
├── src/lambdas/                 # Lambda function code
│   └── services/
│       ├── bookings/
│       ├── companies/
│       ├── job-listings/
│       └── docs-upload/
├── scripts/                     # Deployment & test scripts
└── tests/                       # Integration tests
```

## 🔍 Understanding SAM Configuration

Each service has a `samconfig.toml` file that defines deployment parameters.

**Example: `infra/services/job-listings/samconfig.toml`**

```toml
[default.global.parameters]
stack_name = "seasonal-jobs-joblistings-services-dev"

[default.deploy.parameters]
capabilities = "CAPABILITY_IAM"
region = "eu-south-1"
parameter_overrides = "Environment=\"dev\" CognitoUserPoolArn=\"arn:aws:cognito-idp:eu-south-1:881962383770:userpool/eu-south-1_0oK9agPYd\""
```

Key points:
- **stack_name**: Unique CloudFormation stack identifier
- **region**: Always `eu-south-1` for this project
- **parameter_overrides**: Environment variables passed to the template
- **Environment**: `dev` or `prod`
- **CognitoUserPoolArn**: Pre-existing Cognito User Pool for authentication

## 🧪 Python Dependencies

Lambda functions have their own `requirements.txt` files.

**Example: `src/lambdas/services/docs-upload/presign-url/requirements.txt`**

```
boto3>=1.26.0
```

SAM automatically installs these during the build process.

## 🎯 Environment-Specific Configuration

The project supports two environments:

### Development (default)
- Stack name suffix: `-dev`
- Cognito User Pool: `eu-south-1_0oK9agPYd`
- Used for: Testing, development, staging

### Production (prod)
- Stack name suffix: `-prod`
- Separate Cognito User Pool
- Used for: Live user traffic

To deploy to a specific environment:

```bash
# Development (default)
sam deploy --config-env default

# Production
sam deploy --config-env prod
```

## 🔒 Security Best Practices

### Never Commit Credentials

Add to `.gitignore` (should already be there):
```
.aws/
*.env
credentials.json
access-token.txt
jwt-token.txt
```

### Use IAM Roles in Production

For production deployments, use IAM roles instead of access keys:
- EC2 instance roles
- ECS task roles
- GitHub Actions OIDC roles

## 🧰 Useful AWS CLI Commands

```bash
# List all CloudFormation stacks
aws cloudformation list-stacks --region eu-south-1

# List Lambda functions
aws lambda list-functions --region eu-south-1

# List DynamoDB tables
aws dynamodb list-tables --region eu-south-1

# Get Cognito User Pool details
aws cognito-idp describe-user-pool \
  --user-pool-id eu-south-1_0oK9agPYd \
  --region eu-south-1
```

## 🐍 Python Virtual Environment (Optional)

For local development and testing:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

## ✅ Verification Checklist

Before moving to deployment, verify:

- [ ] AWS credentials configured
- [ ] `aws sts get-caller-identity` returns correct account
- [ ] Repository cloned
- [ ] Familiar with project structure
- [ ] SAM CLI installed and working (`sam --version`)
- [ ] Python 3.9+ available (`python3 --version`)

## 🚨 Troubleshooting

### "Unable to locate credentials"

**Solution:** Run `aws configure` again or check `~/.aws/credentials`

### "Region not specified"

**Solution:** Add region to `~/.aws/config`:
```ini
[default]
region = eu-south-1
```

### "Access Denied" errors

**Solution:** Contact your AWS administrator to verify IAM permissions

### SAM CLI not found

**Solution:** Reinstall SAM CLI or add to PATH:
```bash
export PATH=$PATH:~/sam-installation/bin
```

## 📚 Next Steps

Environment configured? Time to deploy your first service! Continue to **[First Deployment](./03-first-deployment.md)** →

---

## 🧭 Navigation

- **[← Back: Prerequisites](./01-prerequisites.md)**
- **[Getting Started Home](./README.md)**
- **[Main Documentation](../../README.md)**
- **[Next: First Deployment →](./03-first-deployment.md)**