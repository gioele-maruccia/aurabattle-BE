# Create Job Listing API

## Overview

Lambda function that creates a new job listing for seasonal work positions. This endpoint is restricted to company users only and requires a valid company profile.

## Endpoint

```
POST /listings
```

## Authentication

**Required:** Yes  
**Type:** AWS Cognito JWT Token  
**Header:** `Authorization: Bearer <token>`

**User Requirements:**
- User must be authenticated via Cognito
- User must belong to the `company` group
- User must have an existing company profile in the system

## Request

### Headers

```
Content-Type: application/json
Authorization: Bearer <cognito-jwt-token>
```

### Body Parameters

#### Required Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `title` | string | Job title | `"Cameriere per stagione estiva"` |
| `startDate` | string (ISO 8601) | Job start date | `"2025-06-01"` |
| `endDate` | string (ISO 8601) | Job end date | `"2025-09-30"` |
| `positions` | integer | Number of available positions | `3` |
| `category` | string | Job category | `"Food & Beverage"` |
| `location` | object | Job location details | See below |
| `salary` | object | Salary information | See below |

#### Location Object (Required)

```json
{
  "address": "Via Roma 123",        // optional
  "city": "Milano",                 // required
  "province": "MI",                 // optional
  "postalCode": "20100",           // optional
  "country": "Italy",              // required
  "coordinates": {                  // required
    "lat": 45.4642,
    "lon": 9.1900
  }
}
```

#### Salary Object (Required)

```json
{
  "min": 15,                    // optional (number)
  "max": 25,                    // optional (number)
  "currency": "EUR",            // required (default: "EUR")
  "period": "hour"              // required (values: "hour", "day", "week", "month", "fixed")
}
```

#### Optional Fields

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `description` | string | Detailed job description | `""` |
| `status` | string | Initial status: `draft` or `published` | `"draft"` |
| `schedule` | object | Work schedule details | `{}` |
| `employment` | object | Employment type information | `{}` |
| `responsibilities` | array[string] | List of job responsibilities | `[]` |
| `benefits` | array[string] | List of benefits offered | `[]` |
| `requirements` | array[string] | List of job requirements | `[]` |
| `tags` | array[string] | Searchable tags (lowercase-hyphen-separated) | `[]` |
| `features` | array[string] | Quick feature badges | `[]` |
| `expiresAt` | string (ISO 8601) | Optional expiration timestamp | `null` |

#### Schedule Object (Optional)

```json
{
  "hoursPerWeek": 20,
  "flexibility": "immediate",     // values: "immediate", "flexible", "fixed"
  "shiftType": "day"             // values: "day", "night", "mixed", "rotating"
}
```
  //TODO: verificare che interpretazione dare al campo "flexibility"


#### Employment Object (Optional)

```json
{
  "type": "part-time",           // values: "full-time", "part-time", "temporary", "seasonal"
  "contractType": "seasonal"     // values: "permanent", "fixed-term", "seasonal", "temporary"
}
```
    //TODO: verificare sulla base dello studio del consulente del lavoro
    //TODO: creare delle tabelle apposite indicando tutti gli enumerativi che l'app può utilizzare. Esporre poi delle api per ognuno di essi. (enum)

#### Available Categories

- `"Food & Beverage"`
- `"Hospitality"`
- `"Retail"`
- `"Tourism"`
- `"Agriculture"`
- `"Events"`
- `"Entertainment"`
- `"Other"`
// TODO: verificare sulla base dello studio del consulente del lavoro
//TODO: creare enum in backend 

#### Available Features

- `"immediate-start"`
- `"part-time"` //TODO: perché?
- `"full-time"` //TODO: perché? è un duplicato.
- `"housing-provided"`
- `"transportation"` //TODO: non è necessario
- `"meals-included"`
- `"experience-required"`
- `"no-experience"` //TODO: mutuamente esclusivo con quello di prima. Usare un campo separato.
- `"flexible-schedule"` //TODO: cioé?
- `"tips-included"`
- `"bonus-available"` //TODO: da quantificare oppure da rimuovere. 

### Example Request Body

```json
{
  "title": "Cameriere per stagione estiva",
  "description": "Cerchiamo cameriere motivato per la stagione estiva. Esperienza preferibile ma non obbligatoria.",
  "startDate": "2025-06-01",
  "endDate": "2025-09-30",
  "positions": 3,
  "category": "Food & Beverage",
  "status": "published",
  "location": {
    "address": "Via Roma 123",
    "city": "Milano",
    "province": "MI",
    "postalCode": "20100",
    "country": "Italy",
    "coordinates": {
      "lat": 45.4642,
      "lon": 9.1900
    }
  },
  "salary": {
    "min": 15,
    "max": 25,
    "currency": "EUR",
    "period": "hour"
  },
  "schedule": {
    "hoursPerWeek": 20,
    "flexibility": "immediate",
    "shiftType": "day"
  },
  "employment": {
    "type": "part-time",
    "contractType": "seasonal"
  },
  "responsibilities": [
    "Accogliere i clienti con cortesia",
    "Prendere le ordinazioni in modo accurato",
    "Servire cibo e bevande"
  ],
  "benefits": [
    "Paga oraria competitiva più mance",
    "Orari flessibili",
    "Pasti inclusi durante il turno"
  ],
  "requirements": [
    "Esperienza pregressa nel settore ristorazione preferibile",
    "Attitudine friendly ed energica",
    "Disponibilità weekend"
  ],
  "tags": ["cameriere", "stagionale", "part-time", "milano"],
  "features": ["immediate-start", "part-time", "flexible-schedule", "meals-included"]
}
```

## Response

### Success Response

**Status Code:** `201 Created`

**Body:**
//TODO: una risposta così dettagliata non è necessaria, meglio ottimizzare. 
```json
{
  "message": "Job listing created successfully",
  "listing": {
    "listingId": "550e8400-e29b-41d4-a716-446655440000",
    "companyId": "123e4567-e89b-12d3-a456-426614174000",
    "title": "Cameriere per stagione estiva",
    "description": "Cerchiamo cameriere motivato...",
    "startDate": "2025-06-01",
    "endDate": "2025-09-30",
    "positions": 3,
    "category": "Food & Beverage",
    "status": "published",
    "location": {
      "address": "Via Roma 123",
      "city": "Milano",
      "province": "MI",
      "postalCode": "20100",
      "country": "Italy",
      "coordinates": {
        "lat": 45.4642,
        "lon": 9.1900
      }
    },
    "salary": {
      "min": 15.0,
      "max": 25.0,
      "currency": "EUR",
      "period": "hour"
    },
    "schedule": {
      "hoursPerWeek": 20,
      "flexibility": "immediate",
      "shiftType": "day"
    },
    "employment": {
      "type": "part-time",
      "contractType": "seasonal"
    },
    "responsibilities": ["..."],
    "benefits": ["..."],
    "requirements": ["..."],
    "tags": ["cameriere", "stagionale", "part-time", "milano"],
    "features": ["immediate-start", "part-time", "flexible-schedule", "meals-included"],
    "viewsCount": 0,
    "applicationsCount": 0,
    "publishedAt": "2025-06-01T10:00:00Z",
    "createdAt": "2025-06-01T10:00:00Z",
    "updatedAt": "2025-06-01T10:00:00Z"
  }
}
```

### Error Responses

#### 400 Bad Request - Missing Required Fields

```json
{
  "error": "Bad Request",
  "message": "Missing required fields: title, startDate, endDate"
}
```

#### 400 Bad Request - Invalid Date Range

```json
{
  "error": "Bad Request",
  "message": "End date must be after start date"
}
```

#### 400 Bad Request - Invalid JSON

```json
{
  "error": "Bad Request",
  "message": "Invalid JSON in request body"
}
```

#### 403 Forbidden - Not a Company User

```json
{
  "error": "Forbidden",
  "message": "Only company users can create job listings"
}
```

#### 404 Not Found - Company Profile Missing

```json
{
  "error": "Not Found",
  "message": "Company profile not found. Please create a company profile first."
}
```

#### 500 Internal Server Error

```json
{
  "error": "Internal Server Error",
  "message": "An error occurred while creating the job listing"
}
```

## Business Logic

### Workflow

1. **Authentication Check**
   - Validates Cognito JWT token
   - Extracts user ID and groups from token claims

2. **Authorization Check**
   - Verifies user belongs to `company` group
   - Returns 403 if not authorized

3. **Request Validation**
   - Checks all required fields are present
   - Validates date range (endDate > startDate)
   - Returns 400 if validation fails

4. **Company Lookup**
   - Fetches company profile using user's Cognito sub ID
   - Returns 404 if company profile doesn't exist
   - Extracts `companyId` for the listing

5. **Status Determination**
   - If `status` is set to `"published"`, sets `publishedAt` to current timestamp
   - If `status` is `"draft"` or omitted, `publishedAt` is null

6. **ID Generation**
   - Generates UUID v4 for `listingId`
   - Uses UTC timestamp for `createdAt` and `updatedAt`

7. **Data Preparation**
   - Converts salary numbers to Decimal (DynamoDB requirement)
   - Sets default values for optional fields
   - Initializes counters: `viewsCount: 0`, `applicationsCount: 0`

8. **Database Save**
   - Saves item to DynamoDB `JobListings` table
   - Returns 500 if save fails

9. **Response**
   - Converts Decimal back to float for JSON response
   - Returns 201 with created listing

## Database Schema

### DynamoDB Table: JobListings

**Primary Key:** `listingId` (String)

**Global Secondary Indexes:**
1. `companyId-publishedAt-index` - Query all listings by company
2. `status-publishedAt-index` - Query published listings
3. `status-startDate-index` - Filter by start date
4. `category-publishedAt-index` - Filter by category

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `JOB_LISTINGS_TABLE_NAME` | DynamoDB table name for job listings | `dev-JobListings` |
| `COMPANIES_TABLE_NAME` | DynamoDB table name for companies | `dev-Companies` |

## Testing

### Using cURL

```bash
# Get your JWT token first
TOKEN="your-cognito-jwt-token"
API_URL="https://your-api-id.execute-api.eu-south-1.amazonaws.com/dev"

# Create a job listing
curl -X POST "${API_URL}/listings" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Cameriere per stagione estiva",
    "description": "Cerchiamo cameriere motivato",
    "startDate": "2025-06-01",
    "endDate": "2025-09-30",
    "positions": 3,
    "category": "Food & Beverage",
    "status": "published",
    "location": {
      "city": "Milano",
      "country": "Italy",
      "coordinates": {
        "lat": 45.4642,
        "lon": 9.1900
      }
    },
    "salary": {
      "min": 15,
      "max": 25,
      "currency": "EUR",
      "period": "hour"
    },
    "tags": ["cameriere", "stagionale"],
    "features": ["immediate-start", "part-time"]
  }'
```

### Using Test Framework

```bash
cd tests
./scripts/test-runner.sh --suite job-listings --test create-listing-valid --env dev
```

## Security Considerations

1. **Authentication:** All requests must include valid Cognito JWT token
2. **Authorization:** Only users in `company` group can create listings
3. **Company Ownership:** Listings are automatically associated with authenticated user's company
4. **Input Validation:** All required fields are validated before processing
5. **CORS:** Enabled for all origins (`*`) - restrict in production

## Performance

- **Cold Start:** ~1-2 seconds (first invocation)
- **Warm Start:** ~50-200ms (subsequent invocations)
- **Memory:** 512 MB allocated
- **Timeout:** 30 seconds
- **Concurrent Executions:** Scales automatically with AWS Lambda

## Error Handling

All errors are logged to CloudWatch Logs with the following format:
```
Error creating job listing: <error_message>
Error fetching company: <error_message>
```

## Future Enhancements

- [ ] Add image upload support for job listings
- [ ] Implement TTL for automatic expiration
- [ ] Add validation for salary ranges
- [ ] Implement duplicate detection
- [ ] Add support for multiple locations
- [ ] Rich text formatting for descriptions
- [ ] Draft auto-save functionality
- [ ] Listing templates for recurring positions

## Related APIs

- `GET /listings/{listingId}` - Get listing details
- `PUT /listings/{listingId}` - Update listing
- `DELETE /listings/{listingId}` - Delete listing
- `PATCH /listings/{listingId}/publish` - Publish draft
- `POST /listings/search` - Search listings

## Support

For issues or questions:
- Check CloudWatch Logs for error details
- Verify company profile exists before creating listings
- Ensure all required fields are provided
- Validate JWT token is not expired