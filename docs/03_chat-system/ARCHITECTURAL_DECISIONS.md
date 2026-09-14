# 🏗️ Architettura Tecnica - Sistema Chat Beezey

## 📋 Tabella dei Contenuti

1. [Overview](#overview)
2. [Scelte Architetturali](#scelte-architetturali)
3. [Schema Database](#schema-database)
4. [Access Patterns](#access-patterns)
5. [Sicurezza](#sicurezza)
6. [Performance & Scalabilità](#performance--scalabilità)
7. [Costi](#costi)

---

## 🎯 Overview

### Requisiti Funzionali

- ✅ Chat 1:1 tra worker e company per ogni booking
- ✅ Messaggio automatico Beezey all'inizio
- ✅ Upload allegati (max 10MB)
- ✅ Sticker/reazioni su messaggi
- ✅ Stati messaggi (sent/delivered/read)
- ✅ Paginazione dinamica messaggi
- ✅ Assistente Beezey con FAQ
- ✅ Notifiche push (Firebase)

### Requisiti Non Funzionali

- **Latenza**: < 500ms per send-message
- **Throughput**: 1000 msg/minuto
- **Availability**: 99.9%
- **Durabilità**: 99.999999999% (11 nines con DynamoDB)
- **Costo**: < $50/mese per 10k utenti attivi

---

## 🎨 Scelte Architetturali

### 1. ChatDBManager vs Boto3 Diretto

**Decisione**: Il sistema chat utilizza un **ChatDBManager** custom (nel Lambda Layer) invece di chiamare boto3 direttamente.

#### Confronto con servizi legacy

| Aspetto | Chat (Nuovo) | Job-Listings/Companies (Legacy) |
|---------|--------------|----------------------------------|
| **Accesso DB** | `ChatDBManager` (abstraction layer) | `boto3.resource('dynamodb')` diretto |
| **Ubicazione codice** | Shared Lambda Layer (`/opt/python`) | Inline in ogni Lambda |
| **Riusabilità** | Condiviso tra tutte le 7 Lambda | Duplicato in ogni funzione |
| **Testabilità** | Facile mockare il manager | Difficile mockare boto3 |
| **Manutenibilità** | Cambio schema in un solo posto | Cambio richiede modifica di N Lambda |

#### Vantaggi del ChatDBManager

```python
# ✅ Approccio Chat (con ChatDBManager)
from db_manager import ChatDBManager

db_manager = ChatDBManager()
chat = db_manager.get_chat(chat_id)  # Metodo high-level
messages = db_manager.get_messages(chat_id, limit=50)

# ❌ Approccio Legacy (boto3 diretto)
import boto3
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('Chats')
response = table.get_item(Key={'chatId': chat_id})
# Parsing manuale, gestione errori inline...
```

**Benefici:**
1. **Separazione delle responsabilità**: La logica del database è isolata
2. **DRY (Don't Repeat Yourself)**: Codice condiviso via Lambda Layer
3. **Type safety**: Usa modelli Pydantic per validazione
4. **Testing**: Facile creare mock del manager nei test
5. **Refactoring**: Cambio struttura DB in un solo file

#### Perché non usato nei servizi legacy?

I servizi esistenti (job-listings, companies, bookings) furono sviluppati prima dell'adozione del pattern Lambda Layer. Funzionano correttamente ma:
- Duplicano codice di accesso DB
- Più difficili da testare
- Refactoring richiede modifiche multiple

**Roadmap futura**: Migrazione graduale dei servizi legacy al pattern ChatDBManager.

---

### 2. Lambda Layer Strategy

**Decisione**: Usare un Lambda Layer condiviso per models e db_manager.

#### Struttura Layer

```
chat-shared-layer/
└── python/
    ├── models.py          # Modelli Pydantic (Chat, Message, etc.)
    ├── db_manager.py      # ChatDBManager
    └── requirements.txt   # Dipendenze (boto3, pydantic)
```

#### Benefici

1. **Dimensione Lambda ridotta**: ~5KB invece di ~500KB
2. **Deploy più veloce**: Layer cached, solo codice Lambda cambia
3. **Versioning centralizzato**: Un layer = una versione di models
4. **Cold start migliore**: Layer pre-warmed da AWS

#### Deployment Layer

```bash
sam build
sam deploy --config-file infra/services/chat/samconfig.toml

# Layer automaticamente:
# - Buildato in .aws-sam/build/ChatSharedLayer/
# - Deployato come Lambda Layer
# - Attachato a tutte le 7 Lambda
```

---

### 3. Modelli Pydantic per Validazione

**Decisione**: Usare Pydantic invece di validazione manuale.

#### Esempio

```python
# ✅ Con Pydantic (Chat)
from models import Message, MessageState

message = Message(
    chat_id="chat_123",
    message_id="msg_456",
    sender_id="user_789",
    sender_type="worker",  # Enum validation automatica
    message_text="Hello",
    timestamp="2025-11-23T10:00:00Z",
    state=MessageState.SENT  # Type-safe enum
)

# Validazione automatica:
# - sender_type deve essere "worker" | "company" | "beezey"
# - state deve essere MessageState enum
# - timestamp formato ISO 8601

# ❌ Senza Pydantic (Legacy)
message = {
    'chatId': chat_id,
    'messageId': msg_id,
    # Validazione manuale inline...
    'senderType': sender_type if sender_type in ['worker','company','beezey'] else raise_error()
}
```

**Benefici:**
- Validazione automatica a runtime
- Type hints per IDE
- Serializzazione/deserializzazione sicura
- Documentazione auto-generata

---

### 4. Enum per Stati e Tipi

**Decisione**: Usare Enum Python invece di stringhe raw.

#### Esempio

```python
from enum import Enum

class MessageState(str, Enum):
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"

# ✅ Type-safe
state = MessageState.SENT

# ❌ Error-prone
state = "sent"  # Typo? "snet"? "Send"?
```

**Benefici:**
- Autocomplete in IDE
- Typo impossibili
- Refactoring sicuro
- Documentazione chiara

---

### 5. API Response Consistency

**Decisione**: Metodo `to_api_response()` in ogni modello per formato consistente.

#### Esempio

```python
class Chat:
    def to_api_response(self) -> dict:
        return {
            'chatId': self.chat_id,
            'bookingId': self.booking_id,
            'workerId': self.worker_id,
            'companyId': self.company_id,
            'status': self.status.value,
            'createdAt': self.created_at,
            'lastMessageAt': self.last_message_at
        }

# In Lambda:
return {
    'statusCode': 200,
    'body': json.dumps(chat.to_api_response())
}
```

**Benefici:**
- Formato API consistente
- Facile aggiungere/rimuovere campi
- Separazione modello interno vs API pubblica

---

### 6. Gestione Errori Centralizzata

**Decisione**: Exception handling consistente in tutte le Lambda.

#### Pattern

```python
try:
    # Business logic
    db_manager = ChatDBManager()
    chat = db_manager.get_chat(chat_id)
    
except ValueError as e:
    # Errori di validazione
    return {
        'statusCode': 400,
        'body': json.dumps({'error': str(e)})
    }
    
except Exception as e:
    # Errori generici
    print(f"Error: {str(e)}")
    return {
        'statusCode': 500,
        'body': json.dumps({'error': 'Internal server error'})
    }
```

**Benefici:**
- Error handling prevedibile
- Log strutturati in CloudWatch
- Response codes HTTP standard

---

### 7. Timestamp Strategy

**Decisione**: Usare ISO 8601 con timezone UTC per tutti i timestamp.

#### Formato

```python
from datetime import datetime, timezone

def get_current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

# Output: "2025-11-23T10:30:45.123456+00:00"
```

**Benefici:**
- Standard internazionale
- Timezone esplicito
- Sortable lexicographically
- Compatibile con JavaScript Date()

---

### 8. DynamoDB Sort Key Strategy

**Decisione**: Usare timestamp come Sort Key nella tabella Messages.

#### Vantaggi

```python
# Query messaggi per chat (già ordinati)
messages = table.query(
    KeyConditionExpression='chatId = :chatId',
    ScanIndexForward=False,  # Ultimi messaggi primi
    Limit=50
)
```

- Ordinamento automatico (no sorting in Lambda)
- Paginazione efficiente
- Range query possibili (messaggi dopo X timestamp)

---

### Riassunto Decisioni Architetturali

| Decisione | Motivo | Trade-off |
|-----------|--------|-----------|
| ChatDBManager | Riusabilità, testabilità | Layer da deployare |
| Lambda Layer | Deploy veloce, cache | Versioning layer complesso |
| Pydantic | Type safety, validazione | Overhead runtime minimo |
| Enum | Type safety | Boilerplate codice |
| to_api_response() | Consistency API | Metodo extra da mantenere |
| ISO 8601 timestamps | Standard, sortable | String invece di epoch |
| Timestamp SK | Auto-sorting DynamoDB | Granularità millisecond needed |

---

## 🗄️ Schema Database

### Tabella: Chats

```
┌─────────────────────────────────────────────────────┐
│                    Chats Table                       │
├─────────────────────────────────────────────────────┤
│ PK: chatId (STRING)                                  │
├─────────────────────────────────────────────────────┤
│ Attributes:                                          │
│   - bookingId: STRING                                │
│   - workerId: STRING                                 │
│   - companyId: STRING                                │
│   - status: STRING (active|archived|closed)          │
│   - createdAt: STRING (ISO 8601)                     │
│   - lastMessageAt: STRING (ISO 8601)                 │
│   - lastMessagePreview: STRING (max 100 chars)       │
├─────────────────────────────────────────────────────┤
│ GSI: bookingId-index                                 │
│   PK: bookingId                                      │
│   Uso: Trovare chat da booking (1:1)                 │
├─────────────────────────────────────────────────────┤
│ GSI: workerId-lastMessageAt-index                    │
│   PK: workerId, SK: lastMessageAt                    │
│   Uso: Lista chat worker (ordine cronologico)        │
├─────────────────────────────────────────────────────┤
│ GSI: companyId-lastMessageAt-index                   │
│   PK: companyId, SK: lastMessageAt                   │
│   Uso: Lista chat company (ordine cronologico)       │
└─────────────────────────────────────────────────────┘
```

**Esempio Item:**
```json
{
  "chatId": "chat_a1b2c3d4e5f6",
  "bookingId": "booking_12345",
  "workerId": "user_worker_abc",
  "companyId": "user_company_xyz",
  "status": "active",
  "createdAt": "2025-11-23T10:30:00Z",
  "lastMessageAt": "2025-11-23T11:45:00Z",
  "lastMessagePreview": "Grazie per la risposta..."
}
```

### Tabella: Messages

```
┌─────────────────────────────────────────────────────┐
│                  Messages Table                      │
├─────────────────────────────────────────────────────┤
│ PK: chatId (STRING)                                  │
│ SK: timestamp (STRING, ISO 8601 con precisione ms)  │
├─────────────────────────────────────────────────────┤
│ Attributes:                                          │
│   - messageId: STRING (uuid)                         │
│   - senderId: STRING                                 │
│   - senderType: STRING (worker|company|beezey)       │
│   - messageText: STRING                              │
│   - state: STRING (sent|delivered|read)              │
│   - attachments: LIST<MAP>                           │
│       - fileName: STRING                             │
│       - fileSize: NUMBER                             │
│       - fileType: STRING                             │
│       - s3Url: STRING                                │
│       - uploadedAt: STRING                           │
│   - sticker: STRING? (thumbs_up|heart|...)           │
├──────────────────────────────────────────────────────┤
│ GSI: messageId-timestamp-index                       │
│   PK: messageId, SK: timestamp                       │
│   Uso: Update messaggio specifico (stato, sticker)   │
└─────────────────────────────────────────────────────┘
```

**Esempio Item:**
```json
{
  "chatId": "chat_a1b2c3d4e5f6",
  "timestamp": "2025-11-23T11:45:32.123Z",
  "messageId": "msg_xyz789abc",
  "senderId": "user_worker_abc",
  "senderType": "worker",
  "messageText": "Buongiorno, ho una domanda sugli orari",
  "state": "delivered",
  "attachments": [],
  "sticker": null
}
```

---

## 🔍 Access Patterns

### Pattern 1: Creare Chat da Booking
```python
# Quando: Worker applica a job listing
# Query: bookingId-index
response = chats_table.query(
    IndexName='bookingId-index',
    KeyConditionExpression=Key('bookingId').eq(booking_id)
)
# Costo: 0.5 RCU (eventual consistency)
```

### Pattern 2: Lista Chat Worker
```python
# Quando: Worker apre app e vede lista chat
# Query: workerId-lastMessageAt-index
response = chats_table.query(
    IndexName='workerId-lastMessageAt-index',
    KeyConditionExpression=Key('workerId').eq(worker_id),
    ScanIndexForward=False,  # Ordine decrescente
    Limit=20
)
# Costo: ~1 RCU per 4KB (~ 5-10 chat)
```

### Pattern 3: Lista Chat Company
```python
# Quando: Company apre dashboard chat
# Query: companyId-lastMessageAt-index
response = chats_table.query(
    IndexName='companyId-lastMessageAt-index',
    KeyConditionExpression=Key('companyId').eq(company_id),
    ScanIndexForward=False,
    Limit=20
)
```

### Pattern 4: Get Messaggi con Paginazione
```python
# Quando: Utente apre chat e scrolla
# Query: Primary key (chatId + timestamp)
response = messages_table.query(
    KeyConditionExpression=Key('chatId').eq(chat_id),
    ScanIndexForward=False,  # Più recenti primi
    Limit=50,
    ExclusiveStartKey=last_evaluated_key  # Cursore
)
# Costo: ~2.5 RCU per 50 messaggi (10KB)
```

### Pattern 5: Send Message
```python
# Quando: Utente invia messaggio
# Write: 2 operazioni (Messages + update Chat)
messages_table.put_item(Item=message)
chats_table.update_item(
    Key={'chatId': chat_id},
    UpdateExpression='SET lastMessageAt = :t, lastMessagePreview = :p'
)
# Costo: 2 WCU (1 KB write)
```

### Pattern 6: Update Message State
```python
# Quando: Destinatario legge messaggio
# Query GSI + Update
response = messages_table.query(
    IndexName='messageId-timestamp-index',
    KeyConditionExpression=Key('messageId').eq(message_id)
)
messages_table.update_item(
    Key={'chatId': chat_id, 'timestamp': timestamp},
    UpdateExpression='SET #state = :s',
    ExpressionAttributeNames={'#state': 'state'},
    ExpressionAttributeValues={':s': 'read'}
)
# Costo: 0.5 RCU + 1 WCU
```

---

## 🔐 Sicurezza

### Autenticazione: Cognito JWT

```
┌─────────────┐      JWT Token      ┌────────────────┐
│ Mobile App  │ ──────────────────> │  API Gateway   │
└─────────────┘                      └────────┬───────┘
                                             │
                                    Validate JWT
                                             │
                                             ▼
                                    ┌──────────────────┐
                                    │ Lambda Function  │
                                    │ event.requestContext │
                                    │   .authorizer.claims │
                                    └──────────────────┘
```

**Claims Disponibili:**
- `sub` - User ID
- `cognito:groups` - workers, companies, admins
- `custom:user_type` - worker, company
- `email` - Email utente

### Autorizzazione: Policy Check

```python
def authorize_chat_access(user_id, chat):
    """Verifica che utente possa accedere alla chat"""
    if user_id not in [chat.worker_id, chat.company_id]:
        raise ForbiddenError("Not a participant")
```

### S3 Presigned URLs

```python
# Generazione upload URL (Lambda)
presigned_url = s3_client.generate_presigned_url(
    'put_object',
    Params={
        'Bucket': bucket,
        'Key': file_key,
        'ContentType': mime_type
    },
    ExpiresIn=300  # 5 minuti
)

# Client carica direttamente su S3
# NO passaggio tramite Lambda (scalabilità)
```

### Encryption

- **At Rest**: DynamoDB encryption by default (AWS managed)
- **In Transit**: TLS 1.2+ obbligatorio
- **S3**: Server-side encryption (AES256)

---

## ⚡ Performance & Scalabilità

### DynamoDB Capacity

**Billing Mode**: PAY_PER_REQUEST (on-demand)

**Vantaggi:**
- Auto-scaling automatico
- No capacity planning
- Ideale per workload imprevedibili
- Burst fino a 40k RCU / 40k WCU

**Svantaggi:**
- Costo leggermente superiore per RCU/WCU costanti

**Quando passare a Provisioned:**
- Quando superati 10k utenti attivi mensili
- Con pattern di traffico prevedibili
- Per ridurre costi del 40-60%

### Lambda Concurrency

**Configurazione Attuale:**
- Timeout: 30s
- Memory: 512MB
- Concurrent executions: Unlimited (account limit: 1000)

**Auto-scaling:**
```
Invocations per second × Duration (seconds) = Concurrency needed

Esempio:
100 req/s × 0.5s = 50 concurrent executions
```

**Reserved Concurrency (Prod):**
- send-message: 100
- get-messages: 50
- Altri: 20

### API Gateway Throttling

**Limiti Default:**
- 10,000 requests/second steady state
- 5,000 burst requests

**Custom Throttling (Prod):**
```yaml
UsagePlan:
  Throttle:
    RateLimit: 1000  # req/s
    BurstLimit: 2000
```

### Caching Strategy

**API Gateway Cache (Opzionale):**
- Cache GET /messages per 5 secondi
- Riduce carico DynamoDB del 70%
- Costo: $0.020/hour per GB

**Client-Side Cache:**
- App memorizza ultimi 100 messaggi
- Invalida cache su nuovo messaggio
- Sync background ogni 30s

---

## 💰 Costi

### Stima Mensile (10k utenti attivi)

**Assunzioni:**
- 10k utenti attivi/mese
- 5 chat per utente
- 20 messaggi/giorno per chat
- 10% messaggi con allegati

#### DynamoDB

```
Read Capacity Units (RCU):
- Lista chat: 10k users × 2 req/day × 1 RCU = 20k RCU/day
- Get messages: 50k chats × 5 opens/day × 2.5 RCU = 625k RCU/day
- Totale: ~20M RCU/mese
- Costo: 20M × $0.25/1M = $5/mese

Write Capacity Units (WCU):
- Send message: 50k chats × 20 msg/day × 2 WCU = 2M WCU/day
- Totale: ~60M WCU/mese
- Costo: 60M × $1.25/1M = $75/mese

Storage:
- Chats: 50k × 1KB = 50MB
- Messages: 50k × 20 × 30 × 0.5KB = 15GB
- Costo: 15GB × $0.25/GB = $3.75/mese

DynamoDB Totale: ~$84/mese
```

#### Lambda

```
Invocations:
- 60M invocations/mese
- Costo: 60M × $0.20/1M = $12/mese

Compute:
- 60M × 0.5s × 512MB = 15M GB-seconds
- Costo: 15M × $0.0000166667 = $250/mese

Lambda Totale: ~$262/mese
```

#### S3

```
Storage:
- 10% msg con allegati = 6M files/mese
- Avg size: 500KB
- Storage: 6M × 0.5MB = 3TB
- Costo: 3000GB × $0.023/GB = $69/mese

Requests:
- PUT: 6M × $0.005/1k = $30/mese
- GET: 6M × $0.0004/1k = $2.4/mese

S3 Totale: ~$101/mese
```

#### API Gateway

```
Requests:
- 60M requests/mese
- Costo: 60M × $3.50/1M = $210/mese
```

#### CloudWatch Logs

```
- 500MB logs/mese
- Costo: ~$2.5/mese
```

### 💵 Totale Stimato

```
┌──────────────────────┬──────────┐
│ Servizio             │ Costo    │
├──────────────────────┼──────────┤
│ DynamoDB             │ $84      │
│ Lambda               │ $262     │
│ S3                   │ $101     │
│ API Gateway          │ $210     │
│ CloudWatch           │ $2.5     │
├──────────────────────┼──────────┤
│ TOTALE MENSILE       │ $659.50  │
└──────────────────────┴──────────┘

Per utente attivo: $0.066/mese
```

### Ottimizzazioni Costo

1. **API Gateway → ALB** (-60%): $210 → $84
2. **DynamoDB Provisioned** (-40%): $84 → $50
3. **S3 Intelligent-Tiering** (-30%): $101 → $70
4. **Lambda Reserved Concurrency** (-20%): $262 → $210

**Totale Ottimizzato: ~$416/mese** ($0.042/utente)

---

## 🚀 Scalabilità

### Limiti Attuali

| Risorsa | Limite Soft | Limite Hard |
|---------|-------------|-------------|
| DynamoDB RCU | 40,000 | ∞ (on-demand) |
| DynamoDB WCU | 40,000 | ∞ (on-demand) |
| Lambda concurrent | 1,000 | 3,000 (richiedibile) |
| API Gateway RPS | 10,000 | 10,000 |
| S3 requests/s | 5,500 | ∞ |

### Bottleneck Analysis

**Scenario: 100k utenti attivi**

1. **API Gateway** ✅ OK (10k RPS)
2. **Lambda** ✅ OK (concurrency ~500)
3. **DynamoDB** ⚠️ Attenzione (provisioned consigliato)
4. **S3** ✅ OK (5.5k RPS)

### Horizontal Scaling

```
┌────────────────────────────────────────┐
│         CloudFront (CDN)               │
│    Cache static assets + S3 downloads  │
└─────────────────┬──────────────────────┘
                  │
    ┌─────────────┴─────────────┐
    ▼                           ▼
┌────────────┐            ┌────────────┐
│ API GW     │            │ API GW     │
│ Region 1   │            │ Region 2   │
└─────┬──────┘            └──────┬─────┘
      │                          │
      ▼                          ▼
┌────────────┐            ┌────────────┐
│ DynamoDB   │ <──────> │ DynamoDB   │
│ Global     │  Repl.   │ Global     │
│ Table      │          │ Table      │
└────────────┘          └────────────┘
```

**DynamoDB Global Tables**: Replicazione multi-region automatica

---

## 📊 Monitoring

### Key Metrics

**Lambda:**
- Invocations (count)
- Errors (count)
- Duration (p50, p90, p99)
- Throttles (count)

**DynamoDB:**
- ConsumedReadCapacityUnits
- ConsumedWriteCapacityUnits
- UserErrors (4xx)
- SystemErrors (5xx)

**API Gateway:**
- 4XXError
- 5XXError
- Latency (p50, p90, p99)
- Count (requests)

### Alarms

```yaml
HighErrorRateAlarm:
  Metric: Errors
  Threshold: > 10/5min
  Action: SNS → Email/Slack

HighLatencyAlarm:
  Metric: Duration
  Threshold: p99 > 2000ms
  Action: SNS

ThrottlingAlarm:
  Metric: Throttles
  Threshold: > 5/5min
  Action: SNS → Increase concurrency
```

---

## 🎯 Conclusioni

### Punti di Forza

✅ **Serverless** - Zero gestione infrastruttura
✅ **Scalabile** - Auto-scaling automatico
✅ **Resiliente** - Multi-AZ by default
✅ **Economico** - Pay-per-use
✅ **Sicuro** - IAM + Cognito + Encryption

### Prossimi Miglioramenti

1. **WebSocket** - Chat real-time (API Gateway WebSocket)
2. **Read Receipts** - Notifiche lettura in tempo reale
3. **Typing Indicators** - "Sta scrivendo..."
4. **Message Reactions** - Più sticker (usando DynamoDB Maps)
5. **Search** - ElasticSearch per ricerca messaggi
6. **Analytics** - Athena per analytics su DynamoDB Streams

---

**Fine Documento Architettura** 🚀
