# Companies API - Complete Payload Files

## Directory Structure

```
test-suites/companies/payloads/
├── create-company-valid.json
├── create-company-invalid-vat.json
├── create-company-missing-fields.json
├── create-company-short-name.json
├── update-company-description.json
├── update-company-request-images.json
├── update-company-save-media.json
├── update-company-invalid-coordinates.json
├── update-company-missing-city.json
└── update-company-description-too-long.json
```

---

## Create Company Payloads

### create-company-valid.json
✅ **Valid minimal company creation**

```json
{
  "businessName": "KFC Belgium Test",
  "vatNumber": "BE0123456789"
}
```

**Expected Result**: 201 Created
- Creates new company with active status
- Returns companyId and userId
- Empty description, location, and media

---

### create-company-invalid-vat.json
❌ **Invalid VAT number format**

```json
{
  "businessName": "Test Company",
  "vatNumber": "INVALID123"
}
```

**Expected Result**: 400 Bad Request
- Error: "vatNumber must follow format: 2 uppercase letters + 10 digits"

---

### create-company-missing-fields.json
❌ **Missing required field (vatNumber)**

```json
{
  "businessName": "Test Company"
}
```

**Expected Result**: 400 Bad Request
- Error: "Missing required field: vatNumber"

---

### create-company-short-name.json
❌ **Business name too short**

```json
{
  "businessName": "A",
  "vatNumber": "BE0123456789"
}
```

**Expected Result**: 400 Bad Request
- Error: "businessName must be between 2 and 200 characters"

---

## Update Company Payloads

### update-company-description.json
✅ **Add description and location with coordinates**

```json
{
  "description": "Fast food chain dedicated to quality meals and excellent customer service",
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

**Expected Result**: 200 OK
- Updates company with description and location
- Coordinates are properly stored as Decimal in DynamoDB

---

### update-company-request-images.json
✅ **Request presigned URLs for image uploads**

```json
{
  "requestProfileImage": true,
  "requestGalleryImages": 3
}
```

**Expected Result**: 200 OK
- Returns uploadUrls object with:
  - `profileImage`: { uploadUrl, key, publicUrl }
  - `galleryImages`: Array of 3 objects with uploadUrl, key, publicUrl, index
- Returns uploadInstructions with:
  - expiresIn: 3600
  - method: "PUT"
  - contentType: "image/jpeg"

**Response Example**:
```json
{
  "message": "Company updated successfully",
  "company": { ... },
  "uploadUrls": {
    "profileImage": {
      "uploadUrl": "https://s3.amazonaws.com/presigned-url...",
      "key": "companies/uuid/profile.jpg",
      "publicUrl": "https://dev-beezey-companies-assets.s3.amazonaws.com/companies/uuid/profile.jpg"
    },
    "galleryImages": [
      {
        "uploadUrl": "https://s3.amazonaws.com/presigned-url-1...",
        "key": "companies/uuid/gallery/1.jpg",
        "publicUrl": "https://dev-beezey-companies-assets.s3.amazonaws.com/companies/uuid/gallery/1.jpg",
        "index": 1
      },
      {
        "uploadUrl": "https://s3.amazonaws.com/presigned-url-2...",
        "key": "companies/uuid/gallery/2.jpg",
        "publicUrl": "https://dev-beezey-companies-assets.s3.amazonaws.com/companies/uuid/gallery/2.jpg",
        "index": 2
      },
      {
        "uploadUrl": "https://s3.amazonaws.com/presigned-url-3...",
        "key": "companies/uuid/gallery/3.jpg",
        "publicUrl": "https://dev-beezey-companies-assets.s3.amazonaws.com/companies/uuid/gallery/3.jpg",
        "index": 3
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

---

### update-company-save-media.json
✅ **Save uploaded image URLs to company profile**

```json
{
  "media": {
    "profileImageUrl": "https://dev-beezey-companies-assets.s3.eu-south-1.amazonaws.com/companies/test-uuid/profile.jpg",
    "galleryImages": [
      "https://dev-beezey-companies-assets.s3.eu-south-1.amazonaws.com/companies/test-uuid/gallery/1.jpg",
      "https://dev-beezey-companies-assets.s3.eu-south-1.amazonaws.com/companies/test-uuid/gallery/2.jpg",
      "https://dev-beezey-companies-assets.s3.eu-south-1.amazonaws.com/companies/test-uuid/gallery/3.jpg"
    ]
  }
}
```

**Expected Result**: 200 OK
- Saves image URLs to company profile
- Media URLs are now stored in DynamoDB
- When retrieved, these URLs will be converted to presigned download URLs

---

### update-company-invalid-coordinates.json
❌ **Invalid latitude value**

```json
{
  "location": {
    "city": "Brussels",
    "country": "Belgium",
    "coordinates": {
      "lat": 999.0,
      "lon": 4.3517
    }
  }
}
```

**Expected Result**: 400 Bad Request
- Error: "latitude must be between -90 and 90"

**Other invalid coordinate examples**:
- lat: -999.0 (too low)
- lat: 91.0 (too high)
- lon: -181.0 (too low)
- lon: 181.0 (too high)

---

### update-company-missing-city.json
❌ **Location provided without required city field**

```json
{
  "location": {
    "country": "Belgium",
    "coordinates": {
      "lat": 50.8503,
      "lon": 4.3517
    }
  }
}
```

**Expected Result**: 400 Bad Request
- Error: "location.city is required when location is provided"

**Note**: When location object is provided, both `city` and `country` are required. Coordinates are optional.

---

### update-company-description-too-long.json
❌ **Description exceeds 2000 characters**

```json
{
  "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit, sed quia consequuntur magni dolores eos qui ratione voluptatem sequi nesciunt. Neque porro quisquam est, qui dolorem ipsum quia dolor sit amet, consectetur, adipisci velit, sed quia non numquam eius modi tempora incidunt ut labore et dolore magnam aliquam quaerat voluptatem. Ut enim ad minima veniam, quis nostrum exercitationem ullam corporis suscipit laboriosam, nisi ut aliquid ex ea commodi consequatur? Quis autem vel eum iure reprehenderit qui in ea voluptate velit esse quam nihil molestiae consequatur, vel illum qui dolorem eum fugiat quo voluptas nulla pariatur? At vero eos et accusamus et iusto odio dignissimos ducimus qui blanditiis praesentium voluptatum deleniti atque corrupti quos dolores et quas molestias excepturi sint occaecati cupiditate non provident, similique sunt in culpa qui officia deserunt mollitia animi, id est laborum et dolorum fuga. Et harum quidem rerum facilis est et expedita distinctio. Nam libero tempore, cum soluta nobis est eligendi optio cumque nihil impedit quo minus id quod maxime placeat facere possimus, omnis voluptas assumenda est, omnis dolor repellendus. Temporibus autem quibusdam et aut officiis debitis aut rerum necessitatibus saepe eveniet ut et voluptates repudiandae sint et molestiae non recusandae. Itaque earum rerum hic tenetur a sapiente delectus, ut aut reiciendis voluptatibus maiores alias consequatur aut perferendis doloribus asperiores repellat. This text is now over 2000 characters and should trigger the validation error."
}
```

**Expected Result**: 400 Bad Request
- Error: "description must not exceed 2000 characters"

**Note**: The description field has a maximum length of 2000 characters to ensure reasonable storage and display requirements.

---

## Complete Image Upload Workflow Example

Here's a complete workflow showing all the steps:

```bash
# Step 1: Create minimal company
POST /companies
{
  "businessName": "My Restaurant",
  "vatNumber": "IT1234567890"
}

# Response:
{
  "message": "Company created successfully",
  "company": {
    "userId": "user-123",
    "companyId": "company-456",
    "businessName": "My Restaurant",
    "vatNumber": "IT1234567890",
    "description": "",
    "location": {},
    "media": {
      "profileImageUrl": "",
      "galleryImages": []
    },
    "status": "active"
  }
}

# Step 2: Add description and location
PUT /companies/user-123
{
  "description": "Italian restaurant specializing in traditional cuisine",
  "location": {
    "city": "Rome",
    "country": "Italy",
    "coordinates": {
      "lat": 41.9028,
      "lon": 12.4964
    }
  }
}

# Step 3: Request presigned URLs
PUT /companies/user-123
{
  "requestProfileImage": true,
  "requestGalleryImages": 2
}

# Response includes uploadUrls:
{
  "uploadUrls": {
    "profileImage": {
      "uploadUrl": "https://s3.amazonaws.com/presigned-url-profile...",
      "key": "companies/company-456/profile.jpg",
      "publicUrl": "https://bucket.s3.amazonaws.com/companies/company-456/profile.jpg"
    },
    "galleryImages": [
      {
        "uploadUrl": "https://s3.amazonaws.com/presigned-url-gallery-1...",
        "key": "companies/company-456/gallery/1.jpg",
        "publicUrl": "https://bucket.s3.amazonaws.com/companies/company-456/gallery/1.jpg",
        "index": 1
      },
      {
        "uploadUrl": "https://s3.amazonaws.com/presigned-url-gallery-2...",
        "key": "companies/company-456/gallery/2.jpg",
        "publicUrl": "https://bucket.s3.amazonaws.com/companies/company-456/gallery/2.jpg",
        "index": 2
      }
    ]
  }
}

# Step 4: Upload images to S3 (using presigned URLs)
# Use PUT method with Content-Type: image/jpeg
curl -X PUT "PRESIGNED_URL" \
  -H "Content-Type: image/jpeg" \
  --data-binary @logo.jpg

# Step 5: Save image URLs to profile
PUT /companies/user-123
{
  "media": {
    "profileImageUrl": "https://bucket.s3.amazonaws.com/companies/company-456/profile.jpg",
    "galleryImages": [
      "https://bucket.s3.amazonaws.com/companies/company-456/gallery/1.jpg",
      "https://bucket.s3.amazonaws.com/companies/company-456/gallery/2.jpg"
    ]
  }
}

# Done! Company profile is now complete with images
```

---

## Validation Rules Summary

| Field | Required | Min | Max | Format |
|-------|----------|-----|-----|--------|
| businessName | Yes | 2 | 200 | Any string |
| vatNumber | Yes | - | - | `^[A-Z]{2}[0-9]{10}$` |
| description | No | - | 2000 | Any string |
| location.city | Conditional* | - | - | Any string |
| location.country | Conditional* | - | - | Any string |
| location.coordinates.lat | No | -90 | 90 | Number |
| location.coordinates.lon | No | -180 | 180 | Number |
| media.profileImageUrl | No | - | - | URL string |
| media.galleryImages | No | - | 5 items | Array of URL strings |

\* Required when location object is provided

---

## Test Data Tips

### Valid VAT Numbers by Country
- **Belgium**: BE0123456789
- **Italy**: IT1234567890
- **France**: FR12345678901
- **Germany**: DE123456789
- **Netherlands**: NL123456789B01
- **Spain**: ES12345678901

### Valid Coordinates
- **Brussels**: 50.8503, 4.3517
- **Rome**: 41.9028, 12.4964
- **Paris**: 48.8566, 2.3522
- **Berlin**: 52.5200, 13.4050
- **Amsterdam**: 52.3676, 4.9041
- **Madrid**: 40.4168, -3.7038

### Common Business Names for Testing
- Fast food: "McDonald's Belgium", "KFC Italia", "Burger King España"
- Restaurants: "Ristorante Roma", "Le Petit Bistro", "La Terrazza"
- Retail: "Fashion Store Milano", "Tech Shop Brussels"
- Services: "City Cleaning Services", "Professional Consulting Ltd"

---

**Last Updated**: January 2025  
**Version**: 1.0