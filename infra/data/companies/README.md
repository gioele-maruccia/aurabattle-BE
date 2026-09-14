# Companies Table

Tabella DynamoDB e S3 Bucket per la gestione dei profili aziendali sulla piattaforma Beezey.

## Risorse Create

### 1. DynamoDB Table: `{Environment}-Companies`
Tabella per memorizzare i dati delle companies.

### 2. S3 Bucket: `beezey-{Environment}-companies-assets`
Bucket per memorizzare le immagini delle companies (logo e gallery).

## Schema Dati

### Primary Key
- **PK**: `userId` (String) - Il `sub` dell'utente da Cognito User Pool

### Attributi

```json
{
  "userId": "cognito-sub-uuid",
  "companyId": "uuid",
  "businessName": "KFC Belgium",
  "vatNumber": "BE0123456789",
  "description": "KFC is a dynamic and fast-food chain dedicated to delivering quick, high-quality meals with excellent customer service.",
  
  "sector": "Food & Beverage",
  "category": "Restaurant",
  
  "location": {
    "street": "Via Roma 123",
    "city": "Mechelen",
    "province": "Antwerp",
    "postalCode": "2800",
    "country": "Belgium",
    "coordinates": {
      "lat": 51.0259,
      "lon": 4.4773
    }
  },
  
  "media": {
    "logoUrl": "s3://bucket/companies/uuid/logo.jpg",
    "coverImageUrl": "s3://bucket/companies/uuid/cover.jpg",
    "galleryImages": [
      "s3://bucket/companies/uuid/gallery/1.jpg",
      "s3://bucket/companies/uuid/gallery/2.jpg"
    ]
  },
  
  "contact": {
    "email": "info@kfc.be",
    "phone": "+32 15 123456",
    "website": "https://www.kfc.be"
  },
  
  "stats": {
    "averageRating": 4.8,
    "totalReviews": 129,
    "ratingDistribution": {
      "5": 89,
      "4": 25,
      "3": 10,
      "2": 3,
      "1": 2
    },
    "activeListingsCount": 3,
    "totalHires": 45
  },
  
  "status": "active",
  "verificationStatus": "verified",
  
  "createdAt": "2024-01-15T10:30:00Z",
  "updatedAt": "2024-03-20T14:22:00Z"
}
```

## Access Patterns

### 1. Get Company by userId (Primary Key)
```javascript
// Quando l'utente company fa login
const company = await dynamodb.get({
  TableName: 'dev-Companies',
  Key: { userId: 'cognito-sub-uuid' }
});
```

### 2. Get Company by companyId (GSI)
```javascript
// Quando vuoi info company da un annuncio o recensione
const result = await dynamodb.query({
  TableName: 'dev-Companies',
  IndexName: 'companyId-index',
  KeyConditionExpression: 'companyId = :companyId',
  ExpressionAttributeValues: {
    ':companyId': 'company-uuid'
  }
});
```

### 3. Update Company Profile
```javascript
await dynamodb.update({
  TableName: 'dev-Companies',
  Key: { userId: 'cognito-sub-uuid' },
  UpdateExpression: 'SET description = :desc, updatedAt = :now',
  ExpressionAttributeValues: {
    ':desc': 'New description',
    ':now': new Date().toISOString()
  }
});
```

### 4. Update Rating Stats (da Lambda trigger Reviews)
```javascript
await dynamodb.update({
  TableName: 'dev-Companies',
  Key: { userId: 'cognito-sub-uuid' },
  UpdateExpression: 'SET stats.totalReviews = stats.totalReviews + :one, stats.averageRating = :newAvg',
  ExpressionAttributeValues: {
    ':one': 1,
    ':newAvg': 4.9
  }
});
```

## Deploy

### Development
```bash
cd infra/data/companies
sam build
sam deploy --config-env default
```

### Staging
```bash
sam build
sam deploy --config-env staging
```

### Production
```bash
sam build
sam deploy --config-env prod
```

## Costi Stimati (MVP)

Con **PAY_PER_REQUEST**:
- Write: $1.25 per milione di write
- Read: $0.25 per milione di read
- Storage: $0.25 per GB/mese

**Esempio**: 1000 aziende, 10k read/giorno, 100 write/giorno
- Read: 300k/mese × $0.25 = $0.075
- Write: 3k/mese × $1.25 = $0.004
- Storage: ~10MB × $0.25 = ~$0
- **Totale: ~$0.08/mese** 💰

## Note

- La tabella ha **DynamoDB Streams** abilitato per futuri trigger (es: aggiornamento automatico rating)
- **Point-in-Time Recovery** abilitato per backup automatici (ultimi 35 giorni)
- **Deletion Protection** abilitata solo in production
- Per production considera **PROVISIONED** billing se hai traffico prevedibile

## TODO Future

- [ ] Aggiungere TTL per soft-delete
- [ ] Lambda trigger per aggregazione stats in tempo reale
- [ ] Cache con DAX se query > 1000/sec
- [ ] Backup automatico cross-region per disaster recovery