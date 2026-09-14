# List Job Listings Lambda Function

## Overview

This Lambda function handles listing and searching job listings with advanced filtering, sorting, and pagination capabilities. It's a **public endpoint** (no authentication required) that enriches job listing data with company information for optimal UI/UX display.

## Key Features

- 🔍 **Advanced Filtering**: Status, category, location (city/province/country), company, date ranges
- 📊 **Multiple Sorting Options**: By publishedAt, startDate, or salary
- 📄 **Cursor-based Pagination**: Efficient pagination using DynamoDB LastEvaluatedKey
- 🏢 **Company Data Enrichment**: Automatically fetches and includes company logo, name, rating
- ⚡ **Optimized Performance**: Uses DynamoDB GSIs for efficient queries
- 🎨 **UI-Ready Format**: Returns data pre-formatted for mobile/web display

## Endpoint
```
GET /listings
```

**Authentication**: None (Public endpoint)

## Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer | No | 20 | Items per page (max: 50) |
| `cursor` | string | No | - | Base64-encoded pagination cursor |
| `status` | string | No | `published` | Filter by status |
| `category` | string | No | - | Filter by job category |
| `city` | string | No | - | Filter by city |
| `location` | string | No | - | Filter by location (searches city, province, or region) |
| `province` | string | No | - | Filter by province |
| `country` | string | No | - | Filter by country |
| `companyId` | string | No | - | Filter by specific company |
| `startDateFrom` | date | No | - | Filter listings starting from date |
| `startDateTo` | date | No | - | Filter listings starting before date |
| `sortBy` | string | No | `publishedAt` | Sort field (`publishedAt`, `startDate`) |
| `sortOrder` | string | No | `desc` | Sort order (`asc`, `desc`) |

## Request Examples

### Basic Request (Published Listings)
```bash
GET /listings?limit=20
```

### Filter by Category
```bash
GET /listings?category=Food%20%26%20Beverage&limit=10
```

### Filter by Location
```bash
GET /listings?city=Milano&country=Italy
```

### Search by Location (City, Province or Region)
```bash
# Searches in city, province, or region fields
GET /listings?location=Lombardia
GET /listings?location=Milano
GET /listings?location=RM
```

### Filter by Company
```bash
GET /listings?companyId=12345678-1234-1234-1234-123456789012
```

### Date Range Filter
```bash
GET /listings?startDateFrom=2025-06-01&startDateTo=2025-09-30
```

### Sort by Start Date
```bash
GET /listings?sortBy=startDate&sortOrder=asc
```

### Pagination (Next Page)
```bash
GET /listings?limit=20&cursor=eyJsaXN0aW5nSWQiOiJqb2JfMjAyNV9hYmMxMjMifQ==
```

## Response Format

### Success Response (200)
```json
{
  "success": true,
  "data": {
    "listings": [
      {
        "listingId": "job_2025_abc123",
        "title": "Looking for a part-time waiter for a fast food chain",
        "description": "Placeholder for the description of the job...",
        "company": {
          "companyId": "uuid-456",
          "name": "KFC Belgium",
          "logoUrl": "https://s3.amazonaws.com/...",
          "rating": 4.8,
          "reviewsCount": 129
        },
        "location": {
          "city": "Mechelen",
          "country": "Belgium",
          "displayText": "Mechelen, Belgium"
        },
        "salary": {
          "min": 15,
          "max": 25,
          "currency": "EUR",
          "period": "hour",
          "displayText": "€15-€25/hr"
        },
        "schedule": {
          "hoursPerWeek": 20,
          "shift": "day",
          "displayText": "20 hrs/week"
        },
        "startDate": "2025-06-01",
        "endDate": "2025-09-30",
        "category": "Food & Beverage",
        "tags": ["part-time", "day-shift", "Fast food", "Waiter"],
        "positions": 3,
        "publishedAt": "2025-01-17T10:30:00Z",
        "viewsCount": 145,
        "applicationsCount": 12
      }
    ],
    "count": 20,
    "hasMore": true,
    "nextCursor": "eyJsaXN0aW5nSWQiOiJqb2JfMjAyNV9hYmMxMjMifQ=="
  },
  "meta": {
    "limit": 20,
    "filters": {
      "status": "published",
      "category": "Food & Beverage",
      "city": null,
      "province": null,
      "country": null,
      "companyId": null
    }
  }
}
```

### Error Responses

#### 400 Bad Request
```json
{
  "error": "Bad Request",
  "message": "Invalid pagination cursor"
}
```

#### 500 Internal Server Error
```json
{
  "error": "Internal Server Error",
  "message": "An unexpected error occurred"
}
```

## DynamoDB Query Strategy

The function uses different Global Secondary Indexes (GSIs) based on filters:

### GSI Selection Logic

1. **category-publishedAt-index**
   - Used when: `category` is specified
   - Key: `category` (PK) + `publishedAt` (SK)
   - Example: All Food & Beverage jobs sorted by published date

2. **status-publishedAt-index**
   - Used when: `status` is specified, `sortBy=publishedAt`
   - Key: `status` (PK) + `publishedAt` (SK)
   - Example: All published jobs sorted by published date

3. **status-startDate-index**
   - Used when: `status` is specified, `sortBy=startDate`
   - Key: `status` (PK) + `startDate` (SK)
   - Example: All published jobs sorted by start date

4. **Fallback: Table Scan**
   - Used when: No suitable GSI available
   - ⚠️ Less efficient, avoid in production

### Additional Filters

After initial GSI query, additional filters are applied using `FilterExpression`:
- Location filters (city, province, country)
- Company filter
- Date range filters

## Company Data Enrichment

### Two-Step Process

1. **Query Job Listings**: Get listings from JobListings table
2. **Batch Fetch Companies**: Fetch company data for all unique `companyId` values

### Company Data Fetched
```python
{
    'companyId': 'uuid-456',
    'businessName': 'KFC Belgium',
    'logoUrl': 'https://s3.amazonaws.com/...',
    'averageRating': 4.8,
    'totalReviews': 129,
    'city': 'Mechelen',
    'country': 'Belgium'
}
```

### Performance Considerations

- **Current Implementation**: Individual queries via `companyId-index` GSI
- **Limitation**: Max 100 companies per request (pagination handles this)
- **TODO**: Implement caching layer (Redis/ElastiCache) for company data
- **Recommendation**: Add CloudFront caching for public endpoints

## Response Formatting

The function transforms raw DynamoDB data into UI-friendly format:

### Transformations Applied

1. **Truncated Descriptions**: Limited to 150 characters with "..."
2. **Display Texts**: Pre-formatted strings for salary, location, schedule
3. **Limited Tags**: Max 4 tags for UI display
4. **Decimal to Float**: All Decimal values converted to floats
5. **Employment Tags**: Automatically extracted from employment/schedule objects

### Example Transformation

**DynamoDB Data:**
```json
{
  "salary": {
    "min": 15,
    "max": 25,
    "currency": "EUR",
    "period": "hour"
  }
}
```

**UI-Ready Data:**
```json
{
  "salary": {
    "min": 15,
    "max": 25,
    "currency": "EUR",
    "period": "hour",
    "displayText": "€15-€25/hr"
  }
}
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `JOB_LISTINGS_TABLE_NAME` | DynamoDB JobListings table name | `dev-JobListings` |
| `COMPANIES_TABLE_NAME` | DynamoDB Companies table name | `dev-Companies` |

## IAM Permissions Required
```yaml
- DynamoDBReadPolicy:
    TableName: ${Environment}-JobListings
- DynamoDBReadPolicy:
    TableName: ${Environment}-Companies
- Statement:
    - Effect: Allow
      Action:
        - dynamodb:Query
      Resource:
        - arn:aws:dynamodb:${Region}:${Account}:table/${Environment}-Companies/index/companyId-index
        - arn:aws:dynamodb:${Region}:${Account}:table/${Environment}-JobListings/index/*
```

## Performance Optimization

### Current Optimizations

✅ **GSI-based queries** instead of scans
✅ **Cursor-based pagination** for efficient large datasets
✅ **Response caching** (5 minutes via `Cache-Control` header)
✅ **Limited result sets** (max 50 items per request)

### Future Optimizations

🔄 **Redis/ElastiCache** for company data
🔄 **CloudFront CDN** for static responses
🔄 **DynamoDB DAX** for ultra-low latency
🔄 **Elasticsearch** for advanced full-text search
🔄 **Lambda@Edge** for geo-distributed caching

## Error Handling

The function handles various error scenarios:

1. **Invalid Cursor**: Returns 400 with clear message
2. **Invalid Parameters**: Returns 400 with parameter name
3. **DynamoDB Errors**: Logged and returns 500
4. **Company Fetch Failures**: Uses placeholder data, doesn't fail entire request

## Logging

Logs include:
- Query parameters received
- GSI selection decision
- Company fetch operations
- Warning when falling back to scan
- Full stack traces for unexpected errors

## Testing Examples

### Test Published Listings
```bash
curl -X GET "https://api.example.com/listings?status=published&limit=10"
```

### Test Category Filter
```bash
curl -X GET "https://api.example.com/listings?category=Food%20%26%20Beverage"
```

### Test Location Filter
```bash
curl -X GET "https://api.example.com/listings?city=Milano&country=Italy"
```

### Test Date Range
```bash
curl -X GET "https://api.example.com/listings?startDateFrom=2025-06-01&startDateTo=2025-09-30"
```

### Test Pagination
```bash
# First page
RESPONSE=$(curl -X GET "https://api.example.com/listings?limit=5")
CURSOR=$(echo $RESPONSE | jq -r '.data.nextCursor')

# Second page
curl -X GET "https://api.example.com/listings?limit=5&cursor=$CURSOR"
```

## Related Documentation

- [Create Job Listing](./create-listing.md)
- [Job Listings API Overview](./README.md)
- [DynamoDB Schema](../../database/job-listings-schema.md)
- [Companies API](../../companies/README.md)

## Changelog

### Version 1.1.0 (Current)
- ✅ Added company data enrichment
- ✅ UI-ready response formatting
- ✅ Cursor-based pagination
- ✅ Multiple GSI support
- ✅ Response caching headers

### Version 1.0.0
- Initial implementation
- Basic listing and filtering

---

**Last Updated**: January 2025  
**Maintained By**: Backend Team  
**Status**: ✅ Production Ready