# Backoffice Reset Profile Lambda

Lambda function for resetting user profiles to "basic" from the backoffice.

## Functionality

This Lambda handles profile reset requests and performs the following actions based on user profile type:

### For Worker Profiles

1. **Validation**: Checks for active bookings (status = "pending" or "accepted")
   - If active bookings exist → Rejects the reset request
   - Inactive bookings (rejected, cancelled, completed, blocked) can be deleted
   
2. **Data Deletion**:
   - Deletes all INACTIVE bookings 
   - Deletes all user documents
   
3. **Cognito Reset**:
   - Sets `custom:profile_type` to "basic"
   - Sets `custom:verification_status` to "none"
   - Removes from all groups
   - Adds to "basic_users" group

### For Company/Company Representative Profiles

1. **Validation**: Checks all job listings for active status or active bookings
   - Active job listing statuses: "published", "paused"
   - Inactive job listing statuses: "draft", "deleted", "closed", "cancelled"
   - If ANY job listing is active OR has active bookings → Rejects the reset request
   - Active booking statuses: "pending", "accepted"
   - Inactive booking statuses: "rejected", "cancelled", "completed", "blocked"
   
2. **Data Deletion**:
   - Deletes all INACTIVE job listings (draft, deleted, closed, cancelled)
   - Deletes all bookings associated with inactive job listings
   - Deletes company record from Companies table
   - Deletes all company documents
   
3. **Cognito Reset**: Same as worker

## API Endpoint

**POST** `/backoffice/reset-profile`

### Request Body
```json
{
  "userSub": "cognito-user-sub-uuid"
}
```

### Response Codes

- **200 OK**: Profile reset successfully
- **400 Bad Request**: 
  - Missing userSub parameter
  - User has active bookings/job listings (cannot reset)
  - User is already basic
- **404 Not Found**: User not found in Cognito
- **500 Internal Server Error**: Unexpected error

### Success Response
```json
{
  "message": "Profile reset to basic successfully",
  "summary": {
    "userSub": "abc-123-def",
    "previousProfileType": "worker",
    "resetTimestamp": "2025-01-17T10:30:00Z",
    "deletedItems": {
      "bookings": 3,
      "documents": 5
    }
  }
}
```

### Error Response - Worker with Active Bookings
```json
{
  "error": "Cannot reset profile: worker has active bookings",
  "activeBookings": [
    {
      "bookingId": "book_20250117_a1b2c3d4",
      "listingId": "job_2025_abc123",
      "jobTitle": "Cameriere per stagione estiva",
      "startDate": "2025-06-01",
      "endDate": "2025-09-30",
      "companyName": "KFC Milano",
      "status": "accepted"
    }
  ],
  "message": "Please cancel or complete all active bookings before resetting the profile. Active bookings: pending and accepted."
}
```

### Error Response - Company with Active Job Listings
```json
{
  "error": "Cannot reset profile: company has active job listings or active bookings",
  "activeListings": [
    {
      "listingId": "job_2025_abc123",
      "jobTitle": "Cameriere di Sala",
      "status": "published"
    }
  ],
  "activeBookings": [
    {
      "bookingId": "book_20250117_xyz",
      "listingId": "job_2025_abc123",
      "jobTitle": "Cameriere di Sala",
      "workerName": "Mario Rossi",
      "status": "pending",
      "startDate": "2025-06-01",
      "endDate": "2025-09-30"
    }
  ],
  "message": "Please close or delete all active job listings (published/paused) and cancel all active bookings (pending/accepted) before resetting the profile."
}
```

## Environment Variables

- `REGION`: AWS region (e.g., eu-south-1)
- `COGNITO_USER_POOL_ID`: Cognito User Pool ID
- `ENVIRONMENT`: Environment name (dev/prod) - used to construct table names
- `BOOKINGS_TABLE`: DynamoDB Bookings table name (optional, defaults to `{ENVIRONMENT}-Bookings`)
- `JOB_LISTINGS_TABLE`: DynamoDB JobListings table name (optional, defaults to `{ENVIRONMENT}-JobListings`)
- `COMPANIES_TABLE`: DynamoDB Companies table name (optional, defaults to `{ENVIRONMENT}-Companies`)
- `DOCUMENTS_TABLE`: DynamoDB UserDocuments table name (optional, defaults to `{ENVIRONMENT}-UserDocuments`)

## IAM Permissions Required

```yaml
- dynamodb:Query
- dynamodb:DeleteItem
- cognito-idp:AdminGetUser
- cognito-idp:AdminListGroupsForUser
- cognito-idp:AdminUpdateUserAttributes
- cognito-idp:AdminRemoveUserFromGroup
- cognito-idp:AdminAddUserToGroup
```

## Job Listing and Booking States

### Job Listing States

**Active States** (block profile reset):
- `published` - Listed on platform, accepting applications
- `paused` - Temporarily hidden but still active

**Inactive States** (safe to delete during reset):
- `draft` - Not yet published
- `deleted` - Soft deleted
- `closed` - Filled or no longer accepting
- `cancelled` - Cancelled by company

### Booking States

**Active States** (block profile reset):
- `pending` - Application submitted, awaiting decision
- `accepted` - Company accepted, employment confirmed

**Inactive States** (can be deleted during reset):
- `rejected` - Application was rejected
- `cancelled` - Booking was cancelled by worker
- `completed` - Job period ended successfully
- `blocked` - Blackout period (no longer relevant)

## Testing

See test scripts:
- `scripts/backoffice/test-profile-reset-setup.ps1` - Setup test users and data
- `scripts/backoffice/test-profile-reset.ps1` - Test the reset functionality

