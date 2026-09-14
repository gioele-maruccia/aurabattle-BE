# Companies API Service

REST API for managing company profiles on the seasonal job platform.

## Architecture

```
API Gateway (REST API)
    ↓
Cognito Authorizer (validates JWT token)
    ↓
Lambda Functions (Python 3.11)
    ↓
DynamoDB (Companies table) + S3 (Images)
```

## Data Schema

Company profiles follow this JSON schema:

```json
{
  "userId": "string (Cognito sub)",
  "companyId": "string (UUID)",
  "businessName": "string (2-200 chars) - REQUIRED",
  "vatNumber": "string (format: XX0000000000)",
  "description": "string (max 2000 chars)",
  "location": {
    "city": "string - REQUIRED",
    "country": "string - REQUIRED",
    "coordinates": {
      "lat": "number (-90 to 90)",
      "lon": "number (-180 to 180)"
    }
  },
  "media": {
    "profileImageUrl": "string (S3 URL)",
    "galleryImages": ["array of S3 URLs (max 5)"]
  },
  "stats": {
    "averageRating": "decimal",
    "totalReviews": "number",
    "activeListingsCount": "number"
  },
  "status": "string (active/inactive/deleted)",
  "createdAt": "ISO 8601 timestamp",
  "updatedAt": "ISO 8601 timestamp"
}
```

## Endpoints

### 1. Create Company Profile (Minimal)
**POST** `/companies`

Creates a minimal company profile with only businessName and vatNumber.
All other data (description, location, images) will be added via PUT /companies/{userId}.

**Authentication:** Required (Cognito JWT token)

**Request Body:**
```json
{
  "businessName": "KFC Belgium",
  "vatNumber": "BE0123456789"
}
```

**Required Fields:**
- `businessName` (2-200 characters)
- `vatNumber` (format: 2 uppercase letters + 10 digits, e.g., IT1234567890)

**Response 201:**
```json
{
  "message": "Company created successfully. Use PUT /companies/{userId} to complete the profile.",
  "company": {
    "userId": "cognito-sub-uuid",
    "companyId": "generated-uuid",
    "businessName": "KFC Belgium",
    "vatNumber": "BE0123456789",
    "description": "",
    "location": {},
    "media": {
      "profileImageUrl": "",
      "galleryImages": []
    },
    "stats": {
      "averageRating": 0,
      "totalReviews": 0,
      "activeListingsCount": 0
    },
    "status": "active",
    "createdAt": "2024-03-20T10:30:00Z",
    "updatedAt": "2024-03-20T10:30:00Z"
  },
  "nextSteps": {
    "endpoint": "/companies/{userId}",
    "method": "PUT",
    "description": "Complete your company profile with description, location, and images"
  }
}
```

**Error Responses:**
- **400:** Validation error (missing fields, invalid format)
- **409:** Company already exists for this user
- **500:** Internal server error

---

### 2. Update Company Profile (Complete)
**PUT** `/companies/{userId}`

Updates company profile with description, location, and generates presigned URLs for image uploads.
This endpoint should be called after creating the company to complete the profile.

**Authentication:** Required (user can only update their own profile)

**Request Body Examples:**

**Step 1 - Add description and location:**
```json
{
  "description": "Fast food chain dedicated to quality meals",
  "location": {
    "city": "Mechelen",
    "country": "Belgium",
    "coordinates": {
      "lat": 51.0259,
      "lon": 4.4773
    }
  }
}
```

**Step 2 - Request presigned URLs for images:**
```json
{
  "requestProfileImage": true,
  "requestGalleryImages": 3
}
```

**Step 3 - Save uploaded image URLs:**
```json
{
  "media": {
    "profileImageUrl": "https://bucket.s3.amazonaws.com/companies/uuid/profile.jpg",
    "galleryImages": [
      "https://bucket.s3.amazonaws.com/companies/uuid/gallery/1.jpg",
      "https://bucket.s3.amazonaws.com/companies/uuid/gallery/2.jpg"
    ]
  }
}
```

**Response 200 (with presigned URLs):**
```json
{
  "message": "Company updated successfully",
  "company": {
    "userId": "cognito-sub-uuid",
    "companyId": "uuid",
    "businessName": "KFC Belgium",
    "description": "Fast food chain...",
    "location": { ... },
    "media": { ... },
    "updatedAt": "2024-03-20T11:00:00Z"
  },
  "uploadUrls": {
    "profileImage": {
      "uploadUrl": "https://s3.amazonaws.com/presigned-url...",
      "key": "companies/uuid/profile.jpg",
      "publicUrl": "https://bucket.s3.amazonaws.com/companies/uuid/profile.jpg"
    },
    "galleryImages": [
      {
        "uploadUrl": "https://s3.amazonaws.com/presigned-url...",
        "key": "companies/uuid/gallery/1.jpg",
        "publicUrl": "https://bucket.s3.amazonaws.com/companies/uuid/gallery/1.jpg",
        "index": 1
      }
    ]
  },
  "uploadInstructions": {
    "expiresIn": 3600,
    "method": "PUT",
    "contentType": "image/jpeg",
    "note": "Use the uploadUrl to PUT your image. After successful upload, call PUT /companies/{userId} again with the media URLs to save them."
  }
}
```

**Error Responses:**
- **400:** Validation error
- **403:** User not authorized (trying to update another user's company)
- **404:** Company not found
- **500:** Internal server error

---
    "galleryImages": [
      {
        "uploadUrl": "https://s3.amazonaws.com/presigned-url...",
        "key": "companies/uuid/gallery/1.jpg",
        "publicUrl": "https://bucket.s3.amazonaws.com/companies/uuid/gallery/1.jpg"
      },
      {
        "uploadUrl": "https://s3.amazonaws.com/presigned-url...",
        "key": "companies/uuid/gallery/2.jpg",
        "publicUrl": "https://bucket.s3.amazonaws.com/companies/uuid/gallery/2.jpg"
      },
      {
        "uploadUrl": "https://s3.amazonaws.com/presigned-url...",
        "key": "companies/uuid/gallery/3.jpg",
        "publicUrl": "https://bucket.s3.amazonaws.com/companies/uuid/gallery/3.jpg"
      }
    ]
  },
  "uploadInstructions": {
    "expiresIn": 3600,
    "method": "PUT",
    "contentType": "image/jpeg",
    "note": "Use the uploadUrl to PUT your image. After successful upload, call PATCH /companies/{userId} to update the media URLs."
  }
}
```

**Error Responses:**
- **400:** Validation error (missing fields, invalid format)
- **409:** Company already exists for this user
- **500:** Internal server error

**Upload Workflow:**
1. Call POST /companies with `requestProfileImage: true` and/or `requestGalleryImages: N`
2. Receive company data + presigned URLs
3. Upload images directly to S3 using the presigned URLs (PUT request)
4. Call PATCH /companies/{userId} to update media URLs in the company profile

**Example image upload with curl:**
```bash
# Upload profile image
curl -X PUT "presigned-upload-url" \
  -H "Content-Type: image/jpeg" \
  --data-binary @logo.jpg

# Then update company with the public URL
curl -X PATCH "$API_URL/companies/{userId}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "media": {
      "profileImageUrl": "https://bucket.s3.amazonaws.com/companies/uuid/profile.jpg"
    }
  }'
```

---

### 3. Get Company Profile (by userId)
**GET** `/companies/{userId}`

Retrieves company profile by Cognito userId.

**Authentication:** Required

**Response 200:**
```json
{
  "userId": "cognito-sub-uuid",
  "companyId": "uuid",
  "businessName": "KFC Belgium",
  "vatNumber": "BE0123456789",
  "location": { ... },
  "media": { ... },
  "stats": { ... }
}
```

---

### 3. Get Company Profile (by companyId - Public)
**GET** `/companies/public/{companyId}`

Public endpoint to retrieve company info (used in app when viewing company details).

**Authentication:** None (public)

**Response 200:**
```json
{
  "companyId": "uuid",
  "businessName": "KFC Belgium",
  "description": "...",
  "location": { ... },
  "media": { ... },
  "stats": {
    "averageRating": 4.8,
    "totalReviews": 129,
    "activeListingsCount": 3
  }
}
```

---

### 4. Update Company Profile
**PUT** `/companies/{userId}`

Updates company profile. Only the authenticated user can update their own company.

**Authentication:** Required

**Request Body:** (partial update supported)
```json
{
  "description": "Updated description",
  "location": {
    "city": "Brussels"
  },
  "media": {
    "profileImageUrl": "https://bucket.s3.amazonaws.com/companies/uuid/profile.jpg",
    "galleryImages": [
      "https://bucket.s3.amazonaws.com/companies/uuid/gallery/1.jpg",
      "https://bucket.s3.amazonaws.com/companies/uuid/gallery/2.jpg"
    ]
  }
}
```

**Response 200:**
```json
{
  "message": "Company updated successfully",
  "company": { ... }
}
```

---

### 5. List Companies
**GET** `/companies?limit=20&lastKey=xxx`

Lists all companies (for backoffice use).

**Authentication:** Required (admin only)

**Query Parameters:**
- `limit` (optional): Number of items per page (default: 20)
- `lastKey` (optional): Pagination token from previous response

**Response 200:**
```json
{
  "companies": [ ... ],
  "lastKey": "base64-encoded-key",
  "count": 20
}
```

---

### 6. Delete Company
**DELETE** `/companies/{userId}`

Soft deletes a company (sets status to 'deleted').

**Authentication:** Required

**Response 200:**
```json
{
  "message": "Company deleted successfully"
}
```

---

## S3 Bucket Structure

```
{environment}-seasonal-jobs-companies-assets/
└── companies/
    └── {companyId}/
        ├── profile.jpg           # Profile image (logo)
        └── gallery/
            ├── 1.jpg
            ├── 2.jpg
            ├── 3.jpg
            ├── 4.jpg
            └── 5.jpg             # Max 5 gallery images
```

## Project Structure

```
AWS-BE/
├── infra/
│   └── services/
│       └── companies/
│           ├── template.yaml
│           ├── samconfig.toml
│           └── README.md (this file)
└── src/
    └── lambdas/
        └── services/
            └── companies/
                ├── create-company/
                │   ├── handler.py         ✅ DONE
                │   └── requirements.txt
                ├── get-company/           ⏳ TODO
                ├── get-company-by-id/     ⏳ TODO
                ├── update-company/        ⏳ TODO
                ├── list-companies/        ⏳ TODO
                └── delete-company/        ⏳ TODO
```

## Deploy

### Prerequisites
1. Companies DynamoDB table deployed (`infra/data/companies`)
2. S3 bucket created: `{env}-seasonal-jobs-companies-assets`
3. Cognito User Pool ARN

### Steps

```bash
# 1. Create S3 bucket (if not exists)
aws s3 mb s3://dev-seasonal-jobs-companies-assets --region eu-south-1

# 2. Configure CORS for S3 bucket (for direct uploads from browser)
aws s3api put-bucket-cors --bucket dev-seasonal-jobs-companies-assets --cors-configuration file://cors-config.json

# 3. Navigate to service directory
cd infra/services/companies

# 4. Update samconfig.toml with your Cognito User Pool ARN

# 5. Build and deploy
sam build
sam deploy --config-env default
```

**cors-config.json:**
```json
{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["PUT", "GET"],
      "AllowedHeaders": ["*"],
      "MaxAgeSeconds": 3000
    }
  ]
}
```

## Validation Rules

- **businessName:** 2-200 characters (required)
- **vatNumber:** Format `XX0000000000` (2 letters + 10 digits)
- **description:** Max 2000 characters
- **location.city:** Required if location provided
- **location.country:** Required if location provided
- **coordinates.lat:** -90 to 90
- **coordinates.lon:** -180 to 180
- **Gallery images:** Maximum 5 images

## Next Steps

- [ ] Implement remaining Lambda handlers
- [ ] Add PATCH endpoint for partial updates
- [ ] Add authorization checks (verify user owns the resource)
- [ ] Add CloudFront in front of S3 for CDN
- [ ] Add image optimization (resize, compress)
- [ ] Add integration tests