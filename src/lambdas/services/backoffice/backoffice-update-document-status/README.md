# Document Review Lambda Function

## Overview
This Lambda function handles the review and approval workflow for user-uploaded documents. It allows authorized reviewers to approve or reject documents that are awaiting review, automatically managing user verification status and Cognito group membership based on document approval states. The function updates DynamoDB records, S3 object tags, Cognito user attributes, and group assignments.

## Purpose
The function serves as the backend endpoint for a document verification system where reviewers can:
- **Approve** documents that meet verification requirements
- **Reject** documents that don't meet requirements (with mandatory rejection reason)

## Technical Specifications

### Environment Variables
- `TABLE_NAME` - DynamoDB table containing document records
- `BUCKET_NAME` - S3 bucket storing the actual document files
- `REGION` - AWS region for DynamoDB and S3 operations
- `USER_POOL_ID` - Cognito User Pool ID for user management

### API Endpoint
- **Method**: PUT
- **Path**: `/users/{user_sub}/documents/{doc_id}/status`
- **Authentication**: Cognito JWT authorizer (reviewer identity extracted from claims)

### Request Body
```json
{
  "status": "APPROVED | REJECTED",
  "rejectionReason": "Required only if status is REJECTED (min 10 characters)"
}
```

## Workflow

### 1. Request Validation
- Validates path parameters (`user_sub`, `doc_id`)
- Validates request body contains required `status` field
- Ensures status is either `APPROVED` or `REJECTED`
- For rejections: validates that `rejectionReason` is provided and at least 10 characters long

### 2. Document ID Parsing
- Document ID format: `{timestamp}_{doc_type}`
- Example: `1696234567890_identity_card`
- Parsed into timestamp and document type components

### 3. Status Verification
- Retrieves current document from DynamoDB
- **Critical**: Document must be in `AWAITING_REVIEW` status
- Returns `409 Conflict` if document is in any other status
- Returns `404 Not Found` if document doesn't exist

### 4. DynamoDB Update
Updates the document record with:
- `status` - New status (APPROVED or REJECTED)
- `reviewedAt` - Current UTC timestamp
- `reviewedBy` - Reviewer's email (extracted from Cognito JWT)
- `rejectionReason` - Only added if status is REJECTED

**DynamoDB Key Structure:**
- **PK**: `USER#{user_sub}`
- **SK**: `DOC#{doc_type}#{timestamp}`

**Conditional Update**: Uses a condition expression to ensure:
- Document exists (`attribute_exists(pk)`)
- Current status is `AWAITING_REVIEW`

### 5. S3 Tags Update (Best Effort)
Updates S3 object tags with:
- `DocumentStatus` - New status
- `ReviewedBy` - Reviewer email
- `ReviewedAt` - Review timestamp

Note: S3 tagging errors are logged but don't fail the operation.

### 6. **User Verification & Auto-Promotion** (NEW)
After updating the document status, the function automatically checks if the user should be promoted or demoted:

#### Profile Types & Requirements
- **basic**: No documents required, default group `basic_users`
- **worker**: Requires `id_card_front` + `id_card_back`, promotes to `workers` group
- **company**: Requires `id_card_front` + `id_card_back` + `visura`, promotes to `companies` group

#### Automatic Actions Based on Document Status

**Case A: All Required Documents Approved** ✅
- Updates Cognito attribute: `custom:verification_status = "approved"`
- Removes user from all other groups
- Adds user to target group (`workers` or `companies`)
- Returns promotion info in response

**Case B: At Least One Document Rejected** ❌
- Updates Cognito attribute: `custom:verification_status = "rejected"`
- Removes user from all other groups
- Adds user to `pending_review` group
- User must re-upload rejected documents

**Case C: Documents Still Pending Review** ⏳
- Updates Cognito attribute: `custom:verification_status = "in_review"`
- Ensures user is in `pending_review` group
- Waits for all documents to be reviewed

#### Verification Logic
1. Fetches user's `custom:profile_type` from Cognito
2. Determines required documents based on profile type
3. Retrieves all user documents from DynamoDB
4. Groups documents by type (keeps only latest for each type)
5. Counts APPROVED, REJECTED, and PENDING documents
6. Takes appropriate action based on document statuses
7. Updates Cognito groups and attributes accordingly

### 7. Audit Logging
Logs the complete audit trail:
- Document ID
- User sub
- Status transition (from → to)
- Reviewer identity
- Verification action taken
- TimestampITING_REVIEW`

### 5. S3 Tags Update (Best Effort)
Updates S3 object tags with:
- `DocumentStatus` - New status
- `ReviewedBy` - Reviewer email
- `ReviewedAt` - Review timestamp

Note: S3 tagging errors are logged but don't fail the operation.

### 6. Audit Logging
Logs the complete audit trail:
- Document ID
- User sub
- Status transition (from → to)
- Reviewer identity
- Timestamp

## Response Formats

### Success (200)
```json
{
  "success": true,
  "documentId": "1696234567890_identity_card",
  "userSub": "cognito-sub-uuid",
  "previousStatus": "AWAITING_REVIEW",
  "newStatus": "APPROVED",
  "reviewedBy": "reviewer@example.com",
  "reviewedAt": "2025-09-30T14:30:00Z",
  "message": "Document status updated from AWAITING_REVIEW to APPROVED",
  "rejectionReason": "Optional field, only present if rejected",
  "userVerification": {
    "action": "promoted",
    "profile_type": "worker",
    "verification_status": "approved",
    "group": "workers",
    "reason": "All required documents approved"
  }
}
```

**Possible `userVerification.action` values:**
- `"promoted"` - User promoted to workers/companies group (all docs approved)
- `"rejected"` - User moved to pending_review group (at least one doc rejected)
- `"pending"` - User remains in pending_review (some docs still awaiting review)
- `"none"` - No action taken (basic profile or unknown profile type)
- `"error"` - Error during verification check

### Error Responses

**400 Bad Request** - Invalid input data
```json
{
  "error": "Missing rejection reason",
  "message": "rejectionReason is required when status is REJECTED"
}
```

**404 Not Found** - Document doesn't exist
```json
{
  "error": "Document not found",
  "message": "Document not found: {doc_id} for user {user_sub}"
}
```

**409 Conflict** - Document not in correct status
```json
{
  "error": "Invalid document status",
  "message": "Document status is 'APPROVED', but must be 'AWAITING_REVIEW' to be updated",
  "currentStatus": "APPROVED",
  "requiredStatus": "AWAITING_REVIEW"
}
```

**500 Internal Server Error** - Unexpected errors
```json
{
  "error": "Internal server error",
  "message": "Error details"
}
```

## Security Features

### Cognito Groups Hierarchy
The function manages four user groups with different precedence levels:

| Group | Precedence | Description | Access Level |
|-------|-----------|-------------|--------------|
| `companies` | 1 (highest) | Verified companies with all docs approved | Full company features |
| `workers` | 2 | Verified workers with all docs approved | Full worker features |
| `basic_users` | 3 | Registered users, no verification | Basic features only |
| `pending_review` | 4 (lowest) | Users awaiting document review | Limited access |

**Group Management Rules:**
- Users can only be in ONE group at a time
- Promotion removes user from all other groups first
- Demotion (rejection) moves user back to `pending_review`
- Basic users stay in `basic_users` until they request upgrade

### Reviewer Identity Tracking
- Extracts reviewer information from Cognito JWT claims:
  - `sub` - Unique reviewer ID
  - `email` - Reviewer email (stored in records)
  - `name` or `cognito:username` - Reviewer display name

### Authorization
- Requires valid Cognito JWT token
- Reviewer identity automatically extracted and recorded
- Provides complete audit trail of who reviewed what

### Data Integrity
- Conditional updates prevent race conditions
- Only documents in `AWAITING_REVIEW` status can be updated
- Prevents accidental re-review of already processed documents

## CORS Configuration
Allows cross-origin requests with:
- **Origin**: `*` (all origins)
- **Headers**: Content-Type, Authorization
- **Methods**: PUT, OPTIONS

## Error Handling

### Graceful Degradation
- S3 tagging failures don't abort the operation (logged as warnings)
- Missing reviewer information defaults to 'unknown' rather than failing

### Informative Error Messages
- Clear distinction between different error types
- Includes current document status in conflict responses
- Provides specific validation error messages

## Use Cases

### Scenario 1: Approving All Worker Documents ✅
1. User uploads `id_card_front` and `id_card_back`
2. Both documents enter `AWAITING_REVIEW` status
3. Reviewer approves first document → User stays in `pending_review`
4. Reviewer approves second document → **User automatically promoted to `workers` group**
5. `custom:verification_status` updated to `"approved"`
6. User can now access worker features

### Scenario 2: Rejecting a Company Document ❌
1. Company user uploads `id_card_front`, `id_card_back`, and `visura`
2. All three documents in `AWAITING_REVIEW`
3. Reviewer approves `id_card_front` and `id_card_back`
4. Reviewer rejects `visura` with reason "Document expired"
5. **User automatically moved to `pending_review` group**
6. `custom:verification_status` updated to `"rejected"`
7. User receives notification to re-upload correct `visura`
8. After re-upload, process restarts

### Scenario 3: Partial Review Progress ⏳
1. Worker user uploads both required documents
2. Reviewer approves `id_card_front`
3. Second document (`id_card_back`) still `AWAITING_REVIEW`
4. User remains in `pending_review` group
5. `custom:verification_status` remains `"in_review"`
6. Once second document approved → User promoted to `workers` group

### Scenario 4: Basic User (No Action)
1. User registers with `profile_type: "basic"`
2. User is in `basic_users` group
3. No documents uploaded
4. No verification check performed
5. User can use basic features only

## Integration Points

### Connected Systems
- **DynamoDB**: Document metadata storage and query
- **S3**: Document file storage with tagging
- **Cognito User Pool**: 
  - User authentication
  - Custom attributes (`profile_type`, `verification_status`)
  - Group membership management (`basic_users`, `pending_review`, `workers`, `companies`)
- **CloudWatch Logs**: Audit trail and debugging

### Expected Workflow
1. User registers → Profile: `basic`, Group: `basic_users`
2. User requests upgrade to `worker` or `company`
3. User uploads required documents → Status: `PENDING`
4. System processes uploads → Status: `AWAITING_REVIEW`, User moved to `pending_review` group
5. **This Lambda**: Reviewer approves/rejects documents
   - All approved → User promoted to `workers` or `companies` group
   - Any rejected → User stays in `pending_review`, must re-upload
   - Partial → User stays in `pending_review`, waits for remaining reviews
6. If rejected → User re-uploads → Loop back to step 4
7. If all approved → User verification complete, gains full access

## Monitoring & Observability

### Required IAM Permissions
The Lambda execution role must have the following permissions:

**DynamoDB:**
```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:UpdateItem",
    "dynamodb:Query"
  ],
  "Resource": "arn:aws:dynamodb:REGION:ACCOUNT:table/TABLE_NAME"
}
```

**S3:**
```json
{
  "Effect": "Allow",
  "Action": [
    "s3:GetObjectTagging",
    "s3:PutObjectTagging"
  ],
  "Resource": "arn:aws:s3:::BUCKET_NAME/*"
}
```

**Cognito (NEW):**
```json
{
  "Effect": "Allow",
  "Action": [
    "cognito-idp:AdminGetUser",
    "cognito-idp:AdminUpdateUserAttributes",
    "cognito-idp:AdminListGroupsForUser",
    "cognito-idp:AdminAddUserToGroup",
    "cognito-idp:AdminRemoveUserFromGroup"
  ],
  "Resource": "arn:aws:cognito-idp:REGION:ACCOUNT:userpool/USER_POOL_ID"
}
```

### CloudWatch Logs
- All operations logged with INFO level
- Errors logged with ERROR level
- Audit trail includes: user, document, reviewer, timestamps

### Key Metrics to Monitor
- Success rate of status updates
- Number of approvals vs rejections
- User promotion rate (promoted/rejected/pending)
- Time to complete verification per profile type
- S3 tagging failure rate
- Cognito update failure rate
- Average processing time
- 409 conflicts (indicating workflow issues)
- Group membership changes over time