# Prerequisites

## 🧭 Navigation

**[← Back to Getting Started](./README.md)** | **[Main Documentation](../../README.md)** | **[Next: Environment Setup →](./02-environment-setup.md)**

---

Before you can develop and deploy Beezey backend services, you need to set up your development environment with the required tools and accounts.

## 🔧 Required Tools

### 1. AWS CLI

The AWS Command Line Interface is essential for interacting with AWS services.

**Installation:**

- **macOS (Homebrew):**
  ```bash
  brew install awscli
  ```

- **Linux:**
  ```bash
  curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
  unzip awscliv2.zip
  sudo ./aws/install
  ```

- **Windows:**
  Download and run the [AWS CLI MSI installer](https://awscli.amazonaws.com/AWSCLIV2.msi)

**Verify installation:**
```bash
aws --version
# Expected output: aws-cli/2.x.x Python/3.x.x ...
```

### 2. AWS SAM CLI

The Serverless Application Model CLI is used to build and deploy SAM templates.

**Installation:**

- **macOS (Homebrew):**
  ```bash
  brew tap aws/tap
  brew install aws-sam-cli
  ```

- **Linux:**
  ```bash
  # Download the installer
  wget https://github.com/aws/aws-sam-cli/releases/latest/download/aws-sam-cli-linux-x86_64.zip
  unzip aws-sam-cli-linux-x86_64.zip -d sam-installation
  sudo ./sam-installation/install
  ```

- **Windows:**
  Download and run the [SAM CLI MSI installer](https://github.com/aws/aws-sam-cli/releases/latest/download/AWS_SAM_CLI_64_PY3.msi)

**Verify installation:**
```bash
sam --version
# Expected output: SAM CLI, version 1.x.x
```

### 3. Python

Lambda functions are written in Python.

**Required version:** Python 3.9 or higher

**Installation:**

- **macOS (Homebrew):**
  ```bash
  brew install python@3.9
  ```

- **Linux (Ubuntu/Debian):**
  ```bash
  sudo apt update
  sudo apt install python3.9 python3-pip
  ```

- **Windows:**
  Download from [python.org](https://www.python.org/downloads/)

**Verify installation:**
```bash
python3 --version
# Expected output: Python 3.9.x or higher
```

### 4. Git

Version control for the codebase.

**Installation:**

- **macOS:** Pre-installed or via Homebrew:
  ```bash
  brew install git
  ```

- **Linux:**
  ```bash
  sudo apt install git
  ```

- **Windows:**
  Download from [git-scm.com](https://git-scm.com/download/win)

**Verify installation:**
```bash
git --version
# Expected output: git version 2.x.x
```

### 5. Text Editor / IDE

Recommended options:
- **VS Code** (with AWS Toolkit extension)
- **PyCharm**
- **Vim/Neovim**

## ☁️ AWS Account Requirements

### AWS Account Access

You need an AWS account with appropriate permissions. Contact your team administrator to obtain:

1. **AWS Account ID**: `881962383770`
2. **IAM User credentials** or **IAM Role** with permissions for:
   - Lambda (create, update, invoke)
   - API Gateway (create, update, deploy)
   - DynamoDB (create tables, read, write)
   - S3 (create buckets, put objects, get objects)
   - CloudFormation (create, update, delete stacks)
   - IAM (create roles and policies for Lambda)
   - EventBridge (create rules and targets)
   - Cognito (read user pools)
   - CloudWatch Logs (create log groups, put logs)

### AWS Region

The project uses **eu-south-1 (Milan)** as the default region for all services.

Make sure your AWS credentials have access to this region.

## 🔑 Access Credentials

You will need to configure:

1. **AWS Access Key ID**
2. **AWS Secret Access Key**
3. (Optional) **Session Token** - if using temporary credentials

These will be configured in the next step: [Environment Setup](./02-environment-setup.md)

## ⚠️ Important Notes

### Do NOT Use Root User

- Never use the AWS root account for development
- Always use an IAM user with limited permissions
- Enable MFA (Multi-Factor Authentication) for production access

### Costs

- Most services are in the AWS free tier during development
- Be mindful of:
  - Lambda invocations (>1M per month)
  - DynamoDB read/write capacity
  - S3 storage and requests
  - API Gateway requests
- Always clean up unused resources

### Region Compliance

- The eu-south-1 region ensures GDPR compliance
- Do not deploy to other regions without approval
- User data must remain in EU

## ✅ Checklist

Before proceeding, ensure you have:

- [ ] AWS CLI installed and working
- [ ] SAM CLI installed and working
- [ ] Python 3.9+ installed
- [ ] Git installed
- [ ] Text editor/IDE ready
- [ ] AWS account access confirmed
- [ ] IAM user credentials ready (or know how to obtain them)

## 📚 Next Steps

All tools installed? Continue to **[Environment Setup](./02-environment-setup.md)** →

---

## 🧭 Navigation

- **[← Back to Getting Started](./README.md)**
- **[Main Documentation](../../README.md)**
- **[Next: Environment Setup →](./02-environment-setup.md)**