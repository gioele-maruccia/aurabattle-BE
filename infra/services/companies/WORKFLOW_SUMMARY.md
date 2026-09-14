# Company Profile Creation Workflow

## Overview

The company profile creation is split into two main operations:

1. **POST /companies** - Create minimal profile (required data only)
2. **PUT /companies/{userId}** - Complete profile (description, location, images)

This approach allows for a cleaner onboarding flow where users can create their account first, then gradually complete their profile.

---

## Step-by-Step Process

### Step 1: Create Minimal Company Profile

**Endpoint:** `POST /companies`

**Required Data:**
- `businessName` (2-200 chars)
- `vatNumber` (format: XX0000000000)

**Example:**
```json
POST /companies
{
  "businessName": "KFC Belgium",
  "vatNumber": "BE0123456789"
}
```

**What happens:**
- ✅ Company record created in DynamoDB
- ✅ Unique `companyId` generated (UUID)
- ✅ Empty placeholders for description, location, media
- ✅ Stats initialized to zero

**Response:**
```json
{
  "company": {
    "userId": "cognito-sub",
    "companyId": "uuid",
    "businessName": "KFC Belgium",
    "vatNumber": "BE0123456789",
    "description": "",
    "location": {},
    "media": {
      "profileImageUrl": "",
      "galleryImages": []
    }
  },
  "nextSteps": {
    "endpoint": "/companies/{userId}",
    "method": "PUT"
  }
}
```

---

### Step 2: Add Description and Location

**Endpoint:** `PUT /companies/{userId}`

**Optional Data:**
- `description` (max 2000 chars)
- `location` object with city, country, coordinates

**Example:**
```json
PUT /companies/cognito-sub
{
  "description": "Fast food chain dedicated to quality",
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

**What happens:**
- ✅ Description saved
- ✅ Location saved
- ✅ `updatedAt` timestamp updated

---

### Step 3: Request Presigned URLs for Images

**Endpoint:** `PUT /companies/{userId}`

**Request:**
```json
PUT /companies/cognito-sub
{
  "requestProfileImage": true,
  "requestGalleryImages": 3
}
```

**What happens:**
- ✅ Generates presigned S3 URLs for:
  - 1 profile image (logo)
  - 3 gallery images (max 5)
- ✅ URLs valid for 1 hour
- ✅ Returns upload instructions

**Response:**
```json
{
  "uploadUrls": {
    "profileImage": {
      "uploadUrl": "https://presigned...",
      "key": "companies/uuid/profile.jpg",
      "publicUrl": "https://bucket.s3.amazonaws.com/companies/uuid/profile.jpg"
    },
    "galleryImages": [
      {
        "uploadUrl": "https://presigned...",
        "key": "companies/uuid/gallery/1.jpg",
        "publicUrl": "https://bucket.s3.amazonaws.com/companies/uuid/gallery/1.jpg",
        "index": 1
      }
    ]
  },
  "uploadInstructions": {
    "expiresIn": 3600,
    "method": "PUT",
    "contentType": "image/jpeg"
  }
}
```

---

### Step 4: Upload Images to S3

**Direct upload to S3 using presigned URLs**

```bash
# Upload profile image
curl -X PUT "https://presigned-url..." \
  -H "Content-Type: image/jpeg" \
  --data-binary @logo.jpg

# Upload gallery image 1
curl -X PUT "https://presigned-url-2..." \
  -H "Content-Type: image/jpeg" \
  --data-binary @image1.jpg
```

**What happens:**
- ✅ Images uploaded directly to S3
- ✅ No Lambda processing needed
- ✅ Fast and efficient

---

### Step 5: Save Image URLs in Database

**Endpoint:** `PUT /companies/{userId}`

**Request:**
```json
PUT /companies/cognito-sub
{
  "media": {
    "profileImageUrl": "https://bucket.s3.amazonaws.com/companies/uuid/profile.jpg",
    "galleryImages": [
      "https://bucket.s3.amazonaws.com/companies/uuid/gallery/1.jpg",
      "https://bucket.s3.amazonaws.com/companies/uuid/gallery/2.jpg",
      "https://bucket.s3.amazonaws.com/companies/uuid/gallery/3.jpg"
    ]
  }
}
```

**What happens:**
- ✅ Public S3 URLs saved in DynamoDB
- ✅ Company profile now complete
- ✅ Images accessible for display in app

---

## Why This Approach?

### ✅ Advantages

1. **Separation of Concerns**
   - Minimal creation (POST) is fast and simple
   - Profile completion (PUT) can be done gradually
   - Images handled separately via S3 presigned URLs

2. **Better UX**
   - User can create account quickly
   - Profile can be completed step-by-step
   - No large payloads in single request

3. **Scalability**
   - Direct S3 uploads (no Lambda payload limits)
   - Lambda only handles metadata, not binary data
   - Efficient resource usage

4. **Flexibility**
   - User can update any field independently
   - Can request new presigned URLs anytime
   - Easy to add new fields later

5. **Security**
   - Authorization check on every update
   - User can only update their own profile
   - Presigned URLs expire after 1 hour

### 📦 S3 Structure

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

---

## Lambda Functions Status

| Function | Method | Endpoint | Status |
|----------|--------|----------|--------|
| create-company | POST | /companies | ✅ DONE |
| update-company | PUT | /companies/{userId} | ✅ DONE |
| get-company | GET | /companies/{userId} | ⏳ TODO |
| get-company-by-id | GET | /companies/public/{companyId} | ⏳ TODO |
| list-companies | GET | /companies | ⏳ TODO |
| delete-company | DELETE | /companies/{userId} | ⏳ TODO |

---

## Next Steps

1. ✅ Create minimal company profile (POST) - **DONE**
2. ✅ Update company profile with all data (PUT) - **DONE**
3. ⏳ Implement GET endpoints for retrieving companies
4. ⏳ Implement LIST for backoffice
5. ⏳ Implement DELETE (soft delete)
6. 🔜 Deploy and test end-to-end
7. 🔜 Integrate with Flutter app