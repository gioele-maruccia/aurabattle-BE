# Chat System - Migrazione a Company Representative

## Modifiche Schema Database

### Tabella: dev-Chats

**BREAKING CHANGE**: Il campo `companyId` è stato rinominato in `companyRepresentativeId`.

#### Prima (vecchio schema):
```
companyId: UUID della company
```

#### Dopo (nuovo schema):
```
companyRepresentativeId: UUID dell'utente rappresentante aziendale
```

### GSI Modificato

- **Vecchio**: `companyId-lastMessageAt-index`
- **Nuovo**: `companyRepresentativeId-lastMessageAt-index`

### Campi Aggiunti

- `lastMessageState`: Enum (sent/delivered/read) - Stato dell'ultimo messaggio

## Impatto sui Dati Esistenti

### ⚠️ Chat Esistenti

Le chat create con il vecchio schema (`companyId`) **non sono compatibili** con il nuovo schema.

**Opzioni di migrazione:**

### Opzione 1: Ricreazione Chat (CONSIGLIATA per dev)
1. Backup chat esistenti (opzionale in dev)
2. Cancella tutte le chat esistenti da `dev-Chats`
3. Deploy nuovo schema
4. Le chat verranno ricreate al prossimo booking

```bash
# Backup (opzionale)
aws dynamodb scan --table-name dev-Chats > backup-chats.json

# Cancella dati
aws dynamodb scan --table-name dev-Chats --attributes-to-get chatId | \
  jq -r '.Items[].chatId.S' | \
  xargs -I {} aws dynamodb delete-item --table-name dev-Chats --key '{"chatId":{"S":"{}"}}'
```

### Opzione 2: Script di Migrazione
```python
# migrate_chats.py
import boto3

dynamodb = boto3.resource('dynamodb')
chats_table = dynamodb.Table('dev-Chats')
companies_table = dynamodb.Table('dev-Companies')

# Per ogni chat esistente
response = chats_table.scan()
for item in response['Items']:
    company_id = item.get('companyId')
    
    # Trova il rappresentante principale della company
    company_response = companies_table.query(
        IndexName='companyId-index',
        KeyConditionExpression='companyId = :cid',
        ExpressionAttributeValues={':cid': company_id},
        Limit=1
    )
    
    if company_response['Items']:
        representative_id = company_response['Items'][0]['userId']
        
        # Aggiorna la chat
        chats_table.update_item(
            Key={'chatId': item['chatId']},
            UpdateExpression='SET companyRepresentativeId = :rid REMOVE companyId',
            ExpressionAttributeValues={':rid': representative_id}
        )
```

## Modifiche API

### POST /chats (Create Chat)

**Request body modificato:**

```json
// VECCHIO
{
  "booking_id": "uuid",
  "worker_id": "uuid",
  "company_id": "uuid",      // ❌ RIMOSSO
  "booking_details": {...}
}

// NUOVO
{
  "booking_id": "uuid",
  "worker_id": "uuid",
  "company_representative_id": "uuid",  // ✅ NUOVO
  "booking_details": {...}
}
```

### GET /chats (NUOVO ENDPOINT)

Lista tutte le chat personali dell'utente con dettagli arricchiti.

**Response:**

```json
{
  "chats": [
    {
      "chatId": "chat_abc123",
      "bookingId": "booking_xyz789",
      "status": "active",
      "lastMessageAt": "2025-11-27T14:30:00Z",
      "lastMessagePreview": "Il contratto è pronto",
      "lastMessageState": "read",
      
      // Solo per worker view:
      "companyId": "comp_456",
      "companyName": "Hotel Bella Vista",
      "companyLogo": "https://s3.../logo.jpg",
      
      // Sempre presente:
      "interlocutorId": "user_789",
      "interlocutorName": "Marco Rossi",
      "interlocutorPhoto": "https://s3.../avatar.jpg"
    }
  ],
  "count": 1
}
```

## Lambda Functions Modificate

### 1. create-chat
- Accetta `company_representative_id` invece di `company_id`
- Validazione aggiornata

### 2. get-my-chats (NUOVA)
- Recupera lista chat personali
- Query su GSI `workerId-lastMessageAt-index` e `companyRepresentativeId-lastMessageAt-index`
- Arricchisce con foto profili da S3
- Integrazione con tabella `dev-Companies` per info azienda

### Layer Condiviso
- `models.py`: Chat model aggiornato
- `db_manager.py`: Nuovi metodi `get_chats_by_worker()` e `get_chats_by_company_representative()`

## Deployment

### 1. Verifica Pre-Deploy
```bash
scripts\verify-chat-structure.bat
```

### 2. Deploy Infrastruttura
```bash
scripts\deploy-chat.bat
```

Questo eseguirà:
1. Deploy data layer (DynamoDB + S3) con nuovo schema
2. Deploy service layer (8 Lambda functions + API Gateway)

### 3. Verifica Post-Deploy

```bash
# Test endpoint esistenti
scripts\chat\complete-test-setup.ps1

# Test nuovo endpoint GET /chats
scripts\chat\test-get-my-chats.ps1
```

## Environment Variables Richieste

### Lambda get-my-chats
```yaml
CHATS_TABLE_NAME: dev-Chats
MESSAGES_TABLE_NAME: dev-Messages
COMPANIES_TABLE_NAME: dev-Companies        # NUOVO
PROFILE_PHOTOS_BUCKET: dev-beezey-profiles # NUOVO
```

### Permissions Richieste
- DynamoDB: Read su `dev-Chats`, `dev-Companies`
- DynamoDB: Query su GSI `workerId-lastMessageAt-index`, `companyRepresentativeId-lastMessageAt-index`
- S3: Read su bucket `dev-beezey-profiles`

## Testing

### Test Automatici
```powershell
# Setup completo (6 test)
.\scripts\chat\complete-test-setup.ps1

# Test GET /chats
.\scripts\chat\test-get-my-chats.ps1

# Test upload file
.\scripts\chat\test-file-upload.ps1

# Test sticker
.\scripts\chat\test-set-sticker.ps1
```

### Test Manuali (Swagger UI)
```bash
cd swagger
.\launch-swagger.sh
```

Accedi a http://localhost:8080 e testa:
- GET /chats
- POST /chats (con `company_representative_id`)

## Rollback

Se necessario tornare al vecchio schema:

1. Restore backup DynamoDB
2. Checkout commit precedente
3. Redeploy vecchio stack

```bash
git checkout <commit-precedente>
scripts\deploy-chat.bat
```

## Checklist Deploy

- [ ] Backup chat esistenti (se necessario)
- [ ] Verifica struttura: `verify-chat-structure.bat`
- [ ] Deploy data layer
- [ ] Deploy service layer
- [ ] Test endpoint esistenti: `complete-test-setup.ps1`
- [ ] Test nuovo endpoint: `test-get-my-chats.ps1`
- [ ] Verifica CloudWatch logs
- [ ] Test Swagger UI
- [ ] Aggiorna documentazione frontend

## Note Importanti

1. **Breaking Change**: Il campo `companyId` non esiste più nella tabella Chats
2. **Migrazione Dati**: Chat esistenti devono essere migrate o ricreate
3. **API Changes**: Frontend deve aggiornare chiamata POST /chats
4. **Nuovo Endpoint**: Frontend può ora usare GET /chats per lista chat personali
5. **Foto Profili**: Richiede bucket S3 `dev-beezey-profiles` configurato

## Support

Per problemi o domande:
- Verifica CloudWatch logs: `/aws/lambda/dev-chat-*`
- Controlla DynamoDB streams per chat
- Test con script PowerShell in `scripts/chat/`
