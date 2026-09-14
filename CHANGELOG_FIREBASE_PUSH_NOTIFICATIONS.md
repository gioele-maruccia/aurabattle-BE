# Changelog - Firebase Push Notifications

## [2026-01-16] - Firebase Push Notifications Implementation

### ✨ Added

#### New Features
- **Firebase Cloud Messaging (FCM) Push Notifications**
  - Automatic push notifications for new chat messages
  - Automatic push notifications for profile upgrade status changes
  - Best-effort delivery (non-blocking, failures logged but don't interrupt main flow)

#### New Endpoints
- **POST /users/{userId}/fcm-token**
  - Register/update FCM token for authenticated user
  - Called after each login (token can change)
  - Stores token in UserProfiles DynamoDB table

#### New Lambda Functions
- **register-fcm-token** (user-api service)
  - Validates user authentication
  - Stores FCM token in DynamoDB
  - Updates `fcm_token` and `fcm_token_updated_at` fields

#### New Lambda Layer
- **firebase-admin-layer**
  - Firebase Admin SDK (v6.4.0)
  - Custom notification module (`firebase_notifications.py`)
  - Service account authentication
  - Functions:
    - `send_chat_message_notification()`
    - `send_profile_upgrade_notification()`
    - `send_notification()` (generic)

### 🔧 Modified

#### Lambda Functions
- **send-message** (chat service)
  - Added Firebase layer integration
  - Reads recipient FCM token from UserProfiles
  - Sends push notification after message saved
  - Includes sender name and message preview in notification

- **backoffice-update-document-status** (backoffice service)
  - Added Firebase layer integration
  - Reads user FCM token from UserProfiles
  - Sends notification when verification_status changes to approved/rejected
  - Different messages for approved vs rejected status

#### SAM Templates
- **infra/services/user-api/template.yaml**
  - Added RegisterFcmTokenFunction
  - Added route POST /users/{userId}/fcm-token

- **infra/services/chat/template.yaml**
  - Added FirebaseAdminLayer resource
  - SendMessageFunction now uses FirebaseAdminLayer
  - Added USER_PROFILES_TABLE environment variable
  - Added DynamoDB read permission for UserProfiles table

- **infra/services/backoffice/template.yaml**
  - Added FirebaseAdminLayer resource
  - UpdateDocumentStatusFunction now uses FirebaseAdminLayer
  - Added USER_PROFILES_TABLE environment variable
  - Added DynamoDB read permission for UserProfiles table

#### Database Schema
- **UserProfiles DynamoDB Table**
  - Added field: `fcm_token` (string) - FCM device token
  - Added field: `fcm_token_updated_at` (string) - ISO timestamp of last update

#### Configuration
- **.gitignore**
  - Added patterns to exclude Firebase service account files
  - Patterns: `beebusy-*.json`, `*-firebase-adminsdk-*.json`

### 📚 Documentation

#### New Documents
- **docs/02_architecture/FIREBASE_PUSH_NOTIFICATIONS.md**
  - Complete setup guide
  - Architecture overview
  - Deployment instructions
  - Frontend integration examples
  - Troubleshooting guide
  - Monitoring best practices

- **src/lambdas/layers/firebase-admin/README.md**
  - Layer structure and usage
  - Build and deploy instructions
  - Function reference
  - Security notes
  - Troubleshooting

- **FIREBASE_IMPLEMENTATION_SUMMARY.md**
  - High-level overview of changes
  - Quick deployment steps
  - Testing guidelines
  - Pre-production checklist

- **QUICKSTART_FIREBASE.md**
  - Quick start guide for developers
  - Code examples for backend, frontend, and DevOps
  - Monitoring tips

- **swagger/paths/user-api/register-fcm-token.yml**
  - OpenAPI specification for new endpoint
  - Request/response schemas
  - Security requirements

#### New Scripts
- **scripts/deploy-firebase-notifications.ps1**
  - Automated deployment script
  - Copies service account to layer
  - Builds Firebase layer with dependencies
  - Deploys all affected services (user-api, chat, backoffice)

### 🔐 Security

- Firebase service account file protected by .gitignore
- FCM tokens stored securely in DynamoDB
- Lambda functions have minimal permissions (read-only on UserProfiles)
- User can only register token for their own profile
- Service account only has permissions to send FCM notifications

### 🔄 Breaking Changes

**None** - This is a purely additive feature. Existing functionality unchanged.

### 📦 Dependencies

- **New**: `firebase-admin==6.4.0` (Python package)
- Firebase project: `beebusy-b0a51`
- Service account: `beebusy-b0a51-9aaf1bddae28.json` (not in repo, manual copy required)

### 🧪 Testing

All functionality tested:
- ✅ FCM token registration endpoint
- ✅ Chat message notifications
- ✅ Profile upgrade notifications (approved)
- ✅ Profile upgrade notifications (rejected)
- ✅ Error handling and logging
- ✅ CloudWatch logs verification

### 🚀 Deployment

Deploy with:
```powershell
.\scripts\deploy-firebase-notifications.ps1 -Environment dev
```

Or manually:
1. Copy service account to layer
2. Build Firebase layer
3. Deploy user-api, chat, backoffice services

### 📊 Monitoring

CloudWatch logs to monitor:
- `"FCM token registered for user"` - Token registration success
- `"Push notification sent successfully"` - Notification delivered
- `"Failed to send push notification"` - Notification failure (non-critical)
- `"has no FCM token registered"` - User hasn't registered token yet

### 🐛 Known Issues

**None**

### 🔮 Future Enhancements

Potential improvements for future versions:
- Custom notification sounds per action type
- Badge count management
- Silent notifications for background sync
- Rich notifications with images
- Notification history/log in database
- User preferences for notification types
- Multiple device support (array of FCM tokens)

---

## Migration Guide

### For Existing Users

No migration needed - feature is opt-in:
1. User logs in with app
2. App obtains FCM token from Firebase
3. App calls POST /users/{userId}/fcm-token
4. User starts receiving push notifications

### For Developers

Backend changes are backwards compatible. To enable notifications:

1. **Deploy Backend**:
   ```powershell
   .\scripts\deploy-firebase-notifications.ps1 -Environment dev
   ```

2. **Update Frontend**:
   - Add Firebase Messaging to Flutter app
   - Call `/users/{userId}/fcm-token` after login
   - Handle notification tap events

See [QUICKSTART_FIREBASE.md](QUICKSTART_FIREBASE.md) for code examples.

---

## Contributors

- Implementation: GitHub Copilot + Development Team
- Documentation: Complete
- Testing: Verified
- Review: Pending

---

## References

- [Firebase Cloud Messaging](https://firebase.google.com/docs/cloud-messaging)
- [Firebase Admin SDK Python](https://firebase.google.com/docs/reference/admin/python)
- [AWS Lambda Layers](https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html)
