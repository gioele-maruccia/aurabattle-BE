# User Profile Upgrade Lambda Function

## Overview

This Lambda function initiates the user profile upgrade process when a user submits documents for verification. It's triggered from the Flutter mobile app after the user uploads their verification documents to S3.

## Purpose

The function handles the transition of users from basic profiles to verified worker or company profiles by:
- Updating user attributes in AWS Cognito
- Managing user group memberships
- Setting the verification status to begin the review workflow

## Workflow

```
1. User uploads documents to S3 (Flutter app)
   ↓
2. App calls this Lambda function
   ↓
3. Lambda updates Cognito attributes and groups
   ↓
4. User enters "pending_review" state
   ↓
5. Backoffice admin reviews documents
   ↓
6. Status updated to "approved" or "rejected"
```

## Function Actions

### 1. Input Validation
- Validates `username` (user sub/UUID from Cognito)
- Validates `upgrade_type` (must be "worker" or "company")

### 2. Cognito Attribute Updates
Updates three custom attributes:
- `custom:profile_type` → Set to "worker" or "company"
- `custom:verification_status` → Set to "in_review"
- `custom:upgrade_requested_at` → ISO timestamp of the request

### 3. Group Management
- **Removes user from:** basic_users, workers, companies
- **Adds user to:** pending_review

## API Endpoint

### Request

**Method:** `POST`  
**Path:** `/initiate-upgrade`  
**Authentication:** Cognito User Pool (Bearer token)

**Headers:**
```
Content-Type: application/json
Authorization: Bearer <COGNITO_ID_TOKEN>
```

**Body:**
```json
{
  "username": "user-sub-uuid",
  "upgrade_type": "worker"
}
```

### Response

**Success (200):**
```json
{
  "success": true,
  "message": "Upgrade process initiated",
  "username": "user-sub-uuid",
  "profile_type": "worker",
  "verification_status": "in_review",
  "group": "pending_review",
  "timestamp": "2025-10-01T10:30:00.123456"
}
```

**Error (400/404/500):**
```json
{
  "error": "Error description",
  "message": "Additional details"
}
```

## Verification Status States

| Status | Description | Set By |
|--------|-------------|--------|
| `in_review` | Documents uploaded, awaiting verification | **This Lambda** |
| `approved` | Documents approved, user verified | Backoffice Lambda |
| `rejected` | Documents rejected, user must resubmit | Backoffice Lambda |

## User Groups

| Group | Description | Precedence |
|-------|-------------|------------|
| `basic_users` | Default users, no verification | 3 |
| `pending_review` | Documents under review | 4 |
| `workers` | Verified workers | 2 |
| `companies` | Verified companies | 1 |

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `USER_POOL_ID` | Cognito User Pool ID | `eu-south-1_XXXXXXXXX` |
| `ENVIRONMENT` | Deployment environment | `dev`, `staging`, `prod` |

## IAM Permissions Required

```json
{
  "Effect": "Allow",
  "Action": [
    "cognito-idp:AdminUpdateUserAttributes",
    "cognito-idp:AdminAddUserToGroup",
    "cognito-idp:AdminRemoveUserFromGroup",
    "cognito-idp:AdminGetUser",
    "cognito-idp:AdminListGroupsForUser"
  ],
  "Resource": "arn:aws:cognito-idp:region:account:userpool/poolId"
}
```

## Error Handling

The function handles the following error scenarios:

- **400 Bad Request:** Missing or invalid parameters
- **404 Not Found:** User does not exist in Cognito
- **500 Internal Server Error:** Unexpected errors (Cognito API failures, etc.)

All errors are logged to CloudWatch Logs with full stack traces for debugging.

## Logging

The function logs the following information:
- Incoming event data (sanitized)
- User existence checks
- Attribute update operations
- Group membership changes
- Success/failure outcomes

Log level: `INFO`

## Testing

### Manual Test with AWS CLI

```bash
aws lambda invoke \
  --function-name user-profile-upgrade-function \
  --payload '{
    "body": "{\"username\":\"test-user-123\",\"upgrade_type\":\"worker\"}"
  }' \
  response.json

cat response.json
```

### Test with API Gateway

```bash
curl -X POST https://your-api-id.execute-api.eu-south-1.amazonaws.com/dev/initiate-upgrade \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_COGNITO_TOKEN" \
  -d '{
    "username": "test-user-123",
    "upgrade_type": "worker"
  }'
```

## Flutter Integration Example

```dart
import 'package:amplify_flutter/amplify_flutter.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';

Future<Map<String, dynamic>> initiateUpgrade(
  String username, 
  String upgradeType
) async {
  // Get Cognito token
  final session = await Amplify.Auth.fetchAuthSession();
  final idToken = session.userPoolTokens?.idToken.toString();
  
  // Call API
  final response = await http.post(
    Uri.parse('YOUR_API_ENDPOINT/initiate-upgrade'),
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $idToken',
    },
    body: jsonEncode({
      'username': username,
      'upgrade_type': upgradeType,
    }),
  );
  
  return jsonDecode(response.body);
}
```

## Deployment

See the CloudFormation template (`user-profile-upgrade.yaml`) for deployment instructions.

## Dependencies

- **Runtime:** Python 3.11
- **AWS SDK:** boto3 (provided by Lambda runtime)
- **Standard Library:** json, os, logging, datetime, typing

## Performance

- **Timeout:** 30 seconds
- **Memory:** 256 MB
- **Cold Start:** ~500ms
- **Warm Execution:** ~100-200ms

## Security Considerations

1. **Authentication:** API Gateway validates Cognito JWT tokens
2. **Authorization:** Users can only upgrade their own profile (validate in app)
3. **Input Validation:** All inputs are validated before processing
4. **Error Messages:** Generic error messages to prevent information leakage
5. **Logging:** No sensitive data (passwords, tokens) logged

## Monitoring

Monitor the function using CloudWatch metrics:
- Invocation count
- Error rate
- Duration
- Throttles

Set up alarms for:
- Error rate > 5%
- Duration > 10 seconds
- Throttled requests > 0

## Related Functions

- **Document Verification Lambda:** Reviews uploaded documents and sets final approval/rejection status
- **Document Upload Lambda:** Handles S3 presigned URL generation for document uploads

## Support

For issues or questions, contact the development team or check CloudWatch Logs for detailed error information.

## License

Internal use only - Proprietary