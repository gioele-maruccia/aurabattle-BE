# Get User Documents Status Lambda

## Overview

This AWS Lambda function retrieves and returns the status of document uploads for a specific user. It provides information about document verification status, metadata, and generates pre-signed URLs for approved documents stored in S3.

## Functionality

### Authentication & Authorization
- Validates JWT claims from API Gateway authorizer
- Ensures users can only access their own documents (`sub` must match `userId`)
- Returns `401` for unauthenticated requests and `403` for unauthorized access

### Document Types Supported
- `id_card_front` - Front side of ID card
- `id_card_back` - Back side of ID card  
- `visura` - Visura document

### Core Operations

1. **Document Retrieval**: Queries DynamoDB table for user documents using pattern:
   - Primary Key: `USER#{userId}`
   - Sort Key: `DOC#{document_type}#{timestamp}`

2. **Version Management**: For each document type, returns the most recent version based on timestamp

3. **Status Tracking**: Tracks document processing status:
   - `NOT_UPLOADED` - Document not yet uploaded
   - `AWAITING_REVIEW` - Uploaded, pending review
   - `UNDER_REVIEW` - Currently being processed
   - `APPROVED` - Approved and accessible
   - `REJECTED` - Rejected during review

4. **Pre-signed URL Generation**: For approved documents, generates secure S3 download URLs (900s expiration)

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TABLE_NAME` | Yes | - | DynamoDB table name |
| `BUCKET_NAME` | No | - | S3 bucket for document storage |
| `ENVIRONMENT` | No | `dev` | Environment identifier |
| `REGION` | No | `eu-south-1` | AWS region for DynamoDB |
| `BUCKET_REGION` | No | `REGION` value | AWS region for S3 bucket |

## API Response Format

```json
{
  "userId": "string",
  "documents": {
    "id_card_front": {
      "status": "APPROVED|REJECTED|AWAITING_REVIEW|UNDER_REVIEW|NOT_UPLOADED",
      "timestamp": 1234567890,
      "uploadedAt": "2024-01-01T12:00:00Z",
      "lastUpdated": "2024-01-01T12:00:00Z",
      "fileName": "document.jpg",
      "s3Key": "path/to/document.jpg",
      "imageUrl": "https://presigned-url...",
      "urlExpiresIn": 900
    },
    "id_card_back": { /* ... */ },
    "visura": { /* ... */ }
  },
  "overallStatus": "ALL_APPROVED|SOME_REJECTED|UNDER_REVIEW|NO_DOCUMENTS|MIXED",
  "totalDocuments": 2
}
```

## Overall Status Logic

- `NO_DOCUMENTS` - No documents uploaded
- `ALL_APPROVED` - All uploaded documents are approved
- `SOME_REJECTED` - At least one document is rejected
- `UNDER_REVIEW` - Documents are pending/under review
- `MIXED` - Mixed statuses not covered by above

## Error Handling

- **400**: Missing `userId` path parameter
- **401**: Unauthorized (missing/invalid JWT claims)
- **403**: Forbidden (accessing another user's documents)
- **500**: Internal server error (DynamoDB/S3 issues)

## Dependencies

- `boto3` - AWS SDK for Python
- DynamoDB table with composite key structure
- S3 bucket for document storage
- API Gateway with JWT authorizer

## Security Features

- JWT-based authentication
- User isolation (users can only access own documents)
- Pre-signed URLs with short expiration (15 minutes)
- Minimal S3 permissions (only signed headers: `host`)

## Local Testing

The function includes a local test harness at the bottom of the file that can be run with:

```python
python lambda_function.py
```