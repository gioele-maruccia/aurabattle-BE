# Booking Schema - MVP Simplified

## 🎯 Design Principles

1. **Chat replaces coverLetter/notes** - Tutta la comunicazione in un sistema dedicato
2. **Ratings are separate** - Reviews su Companies/Workers, non legati al booking
3. **Keep it simple** - Solo dati essenziali per gestire il booking
4. **Blackout support** - bookingType per distinguere application vs blackout

---

## 📊 Simplified Schema

```json
{
  // ============================================
  // CORE IDENTIFIERS
  // ============================================
  "bookingId": "book_20250117_a1b2c3d4",
  "listingId": "job_2025_abc123",
  "companyId": "uuid-company",
  "workerId": "cognito-sub-worker",  // or companyId for blackout
  
  // ============================================
  // TYPE & CLASSIFICATION
  // ============================================
  "bookingType": "application",  // "application" | "blackout"
  
  // ============================================
  // WORKER INFO (denormalized for quick display)
  // Only for bookingType = "application"
  // Null for blackout
  // ============================================
  "workerName": "Mario Rossi",
  "workerEmail": "mario.rossi@example.com",
  
  // ============================================
  // DATES & PERIOD
  // ============================================
  "startDate": "2025-06-01",
  "endDate": "2025-09-30",
  "daysCount": 122,
  
  // ============================================
  // STATUS & STATE
  // ============================================
  "status": "pending",  // pending | accepted | rejected | cancelled | completed | blocked
  "createdAt": "2025-01-17T10:30:00Z",
  "updatedAt": "2025-01-17T10:30:00Z",
  "statusUpdatedAt": "2025-01-17T10:30:00Z",
  
  // Status-specific timestamps
  "acceptedAt": null,      // When company accepted
  "rejectedAt": null,      // When company rejected
  "cancelledAt": null,     // When worker cancelled
  "completedAt": null,     // When period ended and marked complete
  
  // ============================================
  // BLACKOUT SPECIFIC (only if bookingType = "blackout")
  // ============================================
  "blackoutReason": null,  // "Ferragosto - Closed" | null
  "blackoutType": null,    // "holiday" | "event" | "overstaffed" | "other" | null
  
  // ============================================
  // REJECTION (only if status = "rejected")
  // ============================================
  "rejectionReason": null,  // Optional reason from company
  "reviewedBy": null,       // Company userId who accepted/rejected
  
  // ============================================
  // JOB INFO (denormalized)
  // ============================================
  "jobTitle": "Cameriere per stagione estiva",
  "jobCategory": "Food & Beverage",
  "jobLocation": {
    "city": "Milano",
    "province": "MI",
    "country": "Italy"
  },
  
  // ============================================
  // COMPANY INFO (denormalized)
  // ============================================
  "companyName": "KFC Milano",
  
  // ============================================
  // METADATA
  // ============================================
  "source": "mobile-app",  // mobile-app | web-app | backoffice
  "isActive": true,        // false if cancelled/rejected/completed
  
  // ============================================
  // FUTURE: References to other systems
  // ============================================
  "chatRoomId": null,      // Reference to Chat system (future)
  "contractId": null       // Reference to Contract system (future)
}
```

---

## 🔄 Status Values (Simplified)

```
Application Flow:
pending → accepted → completed
        ↓
        rejected
        ↓  
        cancelled

Blackout Flow:
blocked (permanent until deleted)
```

### Status Definitions

| Status | Description | Can transition to |
|--------|-------------|-------------------|
| `pending` | Application submitted, awaiting company decision | accepted, rejected, cancelled |
| `accepted` | Company accepted the worker | completed, cancelled |
| `rejected` | Company rejected the application | - |
| `cancelled` | Worker cancelled their application | - |
| `completed` | Job period ended successfully | - |
| `blocked` | Blackout period (bookingType = blackout only) | - |

---

## 📝 Removed Fields (and where they go)

### ❌ Removed from Booking

1. **coverLetter** → Moved to **Chat System**
   - First message in chat can be the application message
   - More natural conversation flow
   - Can attach documents, images, etc.

2. **notes** → Moved to **Chat System**
   - Company can add internal notes in chat
   - Or use separate CompanyNotes table if needed
   - Better: use chat with "internal" flag

3. **statusHistory** → Not needed for MVP
   - We have `statusUpdatedAt` timestamp
   - Can add later if needed for audit
   - For now: `status` + timestamps is enough

4. **rating** → Moved to **Reviews System**
   - Separate `CompanyReviews` table
   - Separate `WorkerReviews` table
   - Reviews are about the entity, not the booking
   - One worker can leave ONE review per company (not per booking)

5. **metadata** (complex) → Simplified to just `source`
   - Don't need deviceInfo, ipAddress for MVP
   - Just track where it came from

---

## 🔗 Separate Tables/Systems

### 1. Chat System (Future)
```json
{
  "chatRoomId": "chat_company-uuid_worker-uuid",
  "participants": ["company-uuid", "worker-uuid"],
  "bookingId": "book_20250117_a1b2c3d4",  // Reference
  "messages": [...]
}
```

**Benefits:**
- One chat room can span multiple bookings
- Natural conversation flow
- Can attach files
- Push notifications
- Read receipts
- Type indicators

### 2. Reviews System (Future)
```json
// CompanyReviews table
{
  "reviewId": "rev_123",
  "companyId": "uuid-company",
  "workerId": "cognito-sub-worker",
  "rating": 4.8,
  "comment": "Great place to work!",
  "createdAt": "2025-09-30T10:00:00Z",
  
  // Optional: can reference booking but not required
  "bookingId": "book_20250117_a1b2c3d4"  
}

// WorkerReviews table  
{
  "reviewId": "rev_456",
  "workerId": "cognito-sub-worker",
  "companyId": "uuid-company",
  "rating": 4.5,
  "comment": "Reliable worker",
  "createdAt": "2025-09-30T11:00:00Z",
  
  "bookingId": "book_20250117_a1b2c3d4"
}
```

**Benefits:**
- One review per company/worker pair
- Not tied to specific booking
- Aggregate ratings easily
- Can review even without booking (future: general reviews)

---

## 🎯 MVP Booking Schema - Final

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Booking - MVP Simplified",
  "description": "Simplified booking schema for MVP",
  "type": "object",
  "required": [
    "bookingId",
    "listingId", 
    "companyId",
    "workerId",
    "bookingType",
    "startDate",
    "endDate",
    "daysCount",
    "status",
    "createdAt"
  ],
  "properties": {
    "bookingId": {
      "type": "string",
      "description": "Unique identifier (format: book_YYYYMMDD_xxxxxxxx)",
      "example": "book_20250117_a1b2c3d4"
    },
    "listingId": {
      "type": "string",
      "description": "Reference to job listing",
      "example": "job_2025_abc123"
    },
    "companyId": {
      "type": "string",
      "format": "uuid",
      "description": "Reference to company"
    },
    "workerId": {
      "type": "string",
      "description": "Worker's Cognito sub (or companyId for blackout)",
      "example": "cognito-sub-worker"
    },
    "bookingType": {
      "type": "string",
      "enum": ["application", "blackout"],
      "description": "Type of booking",
      "default": "application"
    },
    
    // Worker info (null for blackout)
    "workerName": {
      "type": ["string", "null"],
      "minLength": 2,
      "maxLength": 200,
      "example": "Mario Rossi"
    },
    "workerEmail": {
      "type": ["string", "null"],
      "format": "email",
      "example": "mario.rossi@example.com"
    },

    // Dates
    "startDate": {
      "type": "string",
      "format": "date",
      "example": "2025-06-01"
    },
    "endDate": {
      "type": "string",
      "format": "date",
      "example": "2025-09-30"
    },
    "daysCount": {
      "type": "integer",
      "minimum": 1,
      "example": 122
    },
    
    // Status
    "status": {
      "type": "string",
      "enum": ["pending", "accepted", "rejected", "cancelled", "completed", "blocked"],
      "description": "Current status",
      "default": "pending"
    },
    
    // Timestamps
    "createdAt": {
      "type": "string",
      "format": "date-time",
      "example": "2025-01-17T10:30:00Z"
    },
    "updatedAt": {
      "type": "string",
      "format": "date-time",
      "example": "2025-01-17T10:30:00Z"
    },
    "statusUpdatedAt": {
      "type": "string",
      "format": "date-time",
      "example": "2025-01-17T10:30:00Z"
    },
    "acceptedAt": {
      "type": ["string", "null"],
      "format": "date-time"
    },
    "rejectedAt": {
      "type": ["string", "null"],
      "format": "date-time"
    },
    "cancelledAt": {
      "type": ["string", "null"],
      "format": "date-time"
    },
    "completedAt": {
      "type": ["string", "null"],
      "format": "date-time"
    },
    
    // Blackout specific
    "blackoutReason": {
      "type": ["string", "null"],
      "maxLength": 500,
      "example": "Ferragosto - Closed"
    },
    "blackoutType": {
      "type": ["string", "null"],
      "enum": ["holiday", "event", "overstaffed", "maintenance", "other", null],
      "example": "holiday"
    },
    
    // Rejection
    "rejectionReason": {
      "type": ["string", "null"],
      "maxLength": 1000,
      "example": "Position has been filled"
    },
    "reviewedBy": {
      "type": ["string", "null"],
      "description": "Company userId who accepted/rejected"
    },
    
    // Denormalized job info
    "jobTitle": {
      "type": "string",
      "example": "Cameriere per stagione estiva"
    },
    "jobCategory": {
      "type": "string",
      "example": "Food & Beverage"
    },
    "jobLocation": {
      "type": "object",
      "properties": {
        "city": {"type": "string"},
        "province": {"type": "string"},
        "country": {"type": "string"}
      }
    },
    
    // Denormalized company info
    "companyName": {
      "type": "string",
      "example": "KFC Milano"
    },
    
    // Metadata
    "source": {
      "type": "string",
      "enum": ["mobile-app", "web-app", "backoffice"],
      "default": "mobile-app"
    },
    "isActive": {
      "type": "boolean",
      "description": "False if cancelled/rejected/completed",
      "default": true
    },
    
    // Future references
    "chatRoomId": {
      "type": ["string", "null"],
      "description": "Reference to chat system (future)"
    },
    "contractId": {
      "type": ["string", "null"],
      "description": "Reference to contract (future)"
    }
  }
}
```

---

## 📊 Comparison: Before vs After

| Feature | Old Schema | New MVP Schema | Where it goes |
|---------|-----------|----------------|---------------|
| Cover Letter | ❌ In booking | ✅ Removed | → Chat (first message) |
| Internal Notes | ❌ In booking | ✅ Removed | → Chat (internal) |
| Status History | ❌ Array of changes | ✅ Removed | MVP doesn't need |
| Rating | ❌ Nested object | ✅ Removed | → Reviews table |
| Metadata | ❌ Complex object | ✅ Simple `source` | Simplified |
| Blackout support | ❌ Not supported | ✅ `bookingType` | Added! |

---

## 🎯 Benefits of Simplified Schema

### 1. **Cleaner Data Model**
- ✅ Only essential booking data
- ✅ No nested complexity
- ✅ Easy to query and display

### 2. **Better Separation of Concerns**
```
Bookings Table → Job assignment data
Chat System → Communication
Reviews System → Ratings & feedback
```

### 3. **More Flexible**
- Chat can exist independent of bookings
- Reviews aren't tied to specific booking
- Worker can review company even without booking (future)

### 4. **Easier to Scale**
- Separate systems can scale independently
- Chat can use different DB (maybe MongoDB for messages)
- Reviews can be cached separately

### 5. **Better UX**
- Chat feels natural (not a static cover letter)
- Reviews are about entities (company/worker), not bookings
- Simpler booking flow

---

## 🚀 Migration Path

### Phase 1: MVP (Now)
- ✅ Bookings with simplified schema
- ✅ Blackout support
- ❌ No chat (can add application message in UI)
- ❌ No reviews

### Phase 2: Chat System
- Add chat tables
- Link to bookings via `bookingId`
- Move application message to chat

### Phase 3: Reviews
- Add reviews tables
- Aggregate ratings to Companies/Workers
- Optional: link to bookings

---

## 💡 Application Message Solution for MVP

Since we removed coverLetter but Chat isn't ready yet:

### Option 1: Temporary field (recommended)
```json
{
  "applicationMessage": "I'm very interested...",  // Temporary, moves to chat later
  "applicationMessageAt": "2025-01-17T10:30:00Z"
}
```

### Option 2: Use rejectionReason pattern
```json
{
  "initialMessage": "I'm very interested...",  // Read-only after creation
  "companyResponse": null  // Company can respond before chat
}
```

### Option 3: Skip for MVP
- Worker just applies without message
- Chat system comes in Phase 2
- Simplest approach

---

## ✅ Recommendations

1. **Use simplified schema** - Much cleaner for MVP
2. **Add `applicationMessage` temporary field** - Nice to have for MVP
3. **Plan for Chat system** - But don't build it now
4. **Keep reviews separate** - Better data model
5. **Support blackouts** - With `bookingType` field

**This schema is production-ready for MVP! 🚀**

---

## 📝 Updated Lambda Example

```python
# apply_to_job_lambda.py - Simplified

booking = {
    # Core
    'bookingId': booking_id,
    'listingId': listing_id,
    'companyId': listing['companyId'],
    'workerId': worker_id,
    'bookingType': 'application',
    
    # Worker info (from Cognito + Worker profile)
    'workerName': worker_name,
    'workerEmail': worker_email,
    'workerPhone': worker_phone,
    'workerProfileImage': worker_profile_image,
    
    # Dates
    'startDate': listing['startDate'],
    'endDate': listing['endDate'],
    'daysCount': days_count,
    
    # Status
    'status': 'pending',
    'createdAt': now,
    'updatedAt': now,
    'statusUpdatedAt': now,
    'acceptedAt': None,
    'rejectedAt': None,
    'cancelledAt': None,
    'completedAt': None,
    
    # Blackout (null for application)
    'blackoutReason': None,
    'blackoutType': None,
    
    # Rejection (null initially)
    'rejectionReason': None,
    'reviewedBy': None,
    
    # Denormalized job/company info
    'jobTitle': listing['title'],
    'jobCategory': listing['category'],
    'jobLocation': listing['location'],
    'companyName': company['businessName'],
    'companyLogo': company['media']['profileImageUrl'],
    
    # Metadata
    'source': 'mobile-app',
    'isActive': True,
    
    # Future
    'chatRoomId': None,
    'contractId': None,
    
    # MVP: Optional application message
    'applicationMessage': body.get('message', None)
}
```

Much cleaner! 🎉