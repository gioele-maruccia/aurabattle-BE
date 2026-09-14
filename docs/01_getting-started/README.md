# Getting Started with Beezey Backend

Welcome to the Beezey backend documentation! This guide will help you set up your local development environment and deploy your first service to AWS.

## 📋 Overview

Beezey is a serverless backend built on AWS using:
- **AWS SAM (Serverless Application Model)** for infrastructure as code
- **Python 3.x** for Lambda functions
- **DynamoDB** for NoSQL data storage
- **S3** for file storage (documents, images)
- **AWS Cognito** for authentication
- **API Gateway** for REST API endpoints
- **EventBridge** for scheduled tasks

The architecture follows a microservices pattern, with each service (bookings, companies, job-listings, docs-upload, etc.) deployed independently.

## 🗺️ Documentation Structure

Follow these guides in order:

1. **[Prerequisites](./01-prerequisites.md)** - Required tools and accounts
2. **[Environment Setup](./02-environment-setup.md)** - Configure AWS credentials and local environment
3. **[First Deployment](./03-first-deployment.md)** - Deploy a service to AWS dev environment
4. **[Verify Setup](./04-verify-setup.md)** - Test that everything works correctly

## 🎯 Quick Start (TL;DR)

For experienced developers:

```bash
# 1. Install AWS CLI and SAM CLI
# 2. Configure AWS credentials
aws configure

# 3. Navigate to a service
cd infra/services/job-listings

# 4. Build the service
sam build

# 5. Deploy to dev
sam deploy --config-env default

# 6. Test the deployment
# See 04-verify-setup.md for test scripts
```

## 📂 Project Structure

```
beezey-backend/
├── infra/                    # SAM templates and infrastructure
│   ├── core/                 # Core services (Cognito, etc.)
│   ├── data/                 # DynamoDB table definitions
│   └── services/             # Lambda services
│       ├── bookings/
│       ├── companies/
│       ├── job-listings/     # Start here!
│       ├── docs-upload/
│       └── user-verification-workflow/
├── src/lambdas/              # Lambda function source code
│   └── services/
│       ├── bookings/
│       ├── companies/
│       ├── job-listings/
│       └── docs-upload/
├── scripts/                  # Deployment and test scripts
├── tests/                    # Integration test suites
└── docs/                     # Documentation (you are here!)
```

## 🌍 AWS Regions

The project uses **eu-south-1 (Milan)** as the primary region for:
- Compliance with EU data regulations
- Proximity to target users
- Lower latency for European customers

## 🔐 Security Notes

- **Never commit AWS credentials** to Git
- All resources use **least-privilege IAM policies**
- S3 buckets have **public access blocked** by default
- Data at rest is **encrypted with KMS**
- API endpoints require **Cognito JWT authentication**

## 🆘 Need Help?

- Check the [Troubleshooting Guide](../operations/troubleshooting.md)
- Review service-specific README files in `infra/services/`
- Consult the [API Documentation](../api/endpoints-reference.md)

## 📚 Next Steps

Ready to begin? Head to **[Prerequisites](./01-prerequisites.md)** →

---

## 🧭 Navigation

- **[← Back to Main Documentation](../../README.md)**
- **[Next: Prerequisites →](./01-prerequisites.md)**