# Chat System - Backoffice Operator e Aggiornamenti Booking

## 📋 Overview

Questo documento descrive due nuove funzionalità implementate nel sistema di chat:

1. **Assegnazione automatica operatore backoffice con @BeeBusy**
2. **Messaggi automatici per cambio stato booking**

---

## 🆘 Feature 1: Operatore Backoffice con @BeeBusy

### Comportamento

Quando un utente (worker o company) scrive un messaggio contenente `@beebusy` (case insensitive) nella chat:

1. **Il sistema assegna automaticamente un operatore backoffice alla chat**
2. **L'operatore ottiene accesso completo** alla chat come terzo interlocutore
3. **Un messaggio automatico conferma** l'assegnazione dell'operatore

### Implementazione Tecnica

#### Modello Chat Aggiornato

```python
@dataclass
class Chat:
    # ... campi esistenti ...
    backoffice_operator_id: Optional[str] = None  # ID operatore backoffice assegnato
```

#### Metodi ChatDBManager

```python
def assign_backoffice_operator(self, chat_id: str, operator_id: str) -> None:
    """Assegna un operatore backoffice a una chat"""

def remove_backoffice_operator(self, chat_id: str) -> None:
    """Rimuove l'operatore backoffice da una chat"""
```

#### Logica in send-message Lambda

```python
# Rileva @beebusy nel messaggio
if message_text and '@beebusy' in message_text.lower():
    if not chat.backoffice_operator_id:
        # Assegna operatore
        operator_id = os.environ.get('DEFAULT_BACKOFFICE_OPERATOR_ID', 'backoffice_operator_default')
        db_manager.assign_backoffice_operator(chat_id, operator_id)
        
        # Invia messaggio di conferma
        notification = Message(
            sender_id="beezey_system",
            sender_type=SenderType.BEEZEY,
            message_text="🆘 **Supporto Beezey Attivato**\n\nUn operatore del nostro team..."
        )
        db_manager.create_message(notification)
```

### Autorizzazioni

Gli operatori backoffice assegnati possono:
- ✅ Leggere tutti i messaggi (`get-messages`)
- ✅ Inviare messaggi come BEEZEY (`send-message`)
- ✅ Vedere la chat nelle loro liste

### Configurazione

**Variabile d'ambiente richiesta:**

```yaml
DEFAULT_BACKOFFICE_OPERATOR_ID: "user_id_operatore_backoffice"
```

**Impostare nella Lambda `send-message`:**

```yaml
Environment:
  Variables:
    DEFAULT_BACKOFFICE_OPERATOR_ID: !Ref BackofficeOperatorUserId
```

---

## 📬 Feature 2: Messaggi Automatici Cambio Stato Booking

### Comportamento

Quando una company aggiorna lo stato di un booking (`PATCH /bookings/{bookingId}/status`), il sistema invia **automaticamente un messaggio nella chat** associata al booking con i dettagli del cambio stato.

### Stati Supportati

#### ✅ **Confirmed** (Candidatura Accettata)

```
✅ **Candidatura Confermata!**

Congratulazioni! La tua candidatura è stata accettata dall'azienda.

📋 **Prossimi passi:**
• Controlla i dettagli del contratto nella sezione "I miei booking"
• Completa i documenti richiesti (se presenti)
• Presentati puntuale alla data concordata

🏢 **Azienda:** [Nome Azienda]
💼 **Posizione:** [Titolo Job]
📅 **Inizio:** [Data Inizio]

In bocca al lupo! 🍀
```

#### ❌ **Rejected** (Candidatura Rifiutata)

```
❌ **Candidatura Non Accettata**

Purtroppo l'azienda ha scelto altri candidati per questa posizione.

💬 **Motivo:** [Motivo del rifiuto se fornito]

📋 **Non ti scoraggiare!**
• Continua a cercare altre opportunità nell'app
• Aggiorna il tuo profilo per renderlo più attraente
• Migliora le tue competenze e certificazioni

Troverai sicuramente l'opportunità giusta per te! 💪
```

#### 🚫 **Cancelled** (Booking Annullato)

```
🚫 **Booking Annullato**

Il booking è stato annullato.

📋 **Cosa succede ora:**
• La posizione è di nuovo disponibile per altre candidature
• Puoi cercare altre opportunità nell'app
• Il tuo profilo rimane attivo
```

#### 🎉 **Completed** (Booking Completato)

```
🎉 **Booking Completato!**

Il lavoro è stato completato con successo!

📋 **Prossimi passi:**
• Il pagamento sarà elaborato secondo i termini concordati
• Lascia una recensione sull'esperienza (opzionale)
• Controlla nuove opportunità nell'app

Grazie per aver usato Beezey!
```

### Implementazione Tecnica

#### Funzione Helper in models.py

```python
def generate_booking_status_message(
    chat: Chat, 
    booking_status: str, 
    rejection_reason: str = None,
    booking_details: Dict[str, Any] = None
) -> Message:
    """Genera un messaggio automatico di aggiornamento stato booking"""
```

#### Integrazione in update-booking-status Lambda

```python
# Dopo l'aggiornamento del booking in DynamoDB
send_booking_status_message_to_chat(
    booking_id=booking_id,
    new_status=new_status,
    rejection_reason=rejection_reason if new_status == 'rejected' else None,
    booking_details={
        'company_name': company.get('companyName'),
        'job_title': listing.get('jobTitle'),
        'start_date': booking.get('startDate')
    }
)
```

#### Funzione Helper in update-booking-status/app.py

```python
def send_booking_status_message_to_chat(booking_id, new_status, rejection_reason=None, booking_details=None):
    """
    Send automatic message to chat when booking status changes
    
    1. Trova la chat associata al booking (get_chat_by_booking)
    2. Genera il messaggio con generate_booking_status_message()
    3. Salva il messaggio nella chat
    4. Broadcast via WebSocket (best effort)
    """
```

### Configurazione Lambda

**Template SAM aggiornato per `UpdateBookingStatusFunction`:**

```yaml
UpdateBookingStatusFunction:
  Type: AWS::Serverless::Function
  Properties:
    Environment:
      Variables:
        CHATS_TABLE_NAME: !Sub '${Environment}-Chats'
        MESSAGES_TABLE_NAME: !Sub '${Environment}-Messages'
    Layers:
      # Aggiunto ChatSharedLayer
      - !Sub 'arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:layer:${Environment}-chat-shared-layer:1'
    Policies:
      # Aggiunte policy per accesso chat
      - DynamoDBReadPolicy:
          TableName: !Sub '${Environment}-Chats'
      - DynamoDBCrudPolicy:
          TableName: !Sub '${Environment}-Messages'
      - Statement:
          - Effect: Allow
            Action:
              - dynamodb:Query
            Resource:
              - !Sub 'arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${Environment}-Chats/index/*'
```

---

## 🧪 Testing

### Test 1: Assegnazione Operatore Backoffice

#### Setup
1. Creare una chat tra worker e company
2. Ottenere JWT token del worker o company

#### Test Steps
```powershell
# 1. Invia messaggio con @beebusy
$chatId = "chat_xxx"
$token = [System.IO.File]::ReadAllText("jwt-token.txt").Trim()

curl.exe -X POST "https://[API_URL]/chats/$chatId/messages" `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"message_text": "Ciao @beebusy, ho bisogno di aiuto!"}'

# 2. Verifica risposta - dovrebbe contenere:
# - Il messaggio dell'utente con @beebusy
# - Messaggio automatico di conferma assegnazione operatore

# 3. Controlla DynamoDB - la chat ora ha backofficeOperatorId
aws dynamodb get-item `
  --table-name dev-Chats `
  --key '{"chatId":{"S":"chat_xxx"}}' `
  --region eu-south-1
```

#### Expected Results
- ✅ Messaggio dell'utente salvato
- ✅ Campo `backofficeOperatorId` popolato nella chat
- ✅ Messaggio automatico "🆘 Supporto Beezey Attivato" inserito in chat
- ✅ Broadcast WebSocket inviato

### Test 2: Messaggi Booking Status

#### Setup
1. Avere un booking in stato "pending" con chat associata
2. Ottenere JWT token del company owner

#### Test Steps - Conferma Booking
```powershell
$bookingId = "booking_xxx"
$token = [System.IO.File]::ReadAllText("jwt-token.txt").Trim()

# Conferma il booking
curl.exe -X PATCH "https://[API_URL]/bookings/$bookingId/status" `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"status": "confirmed"}'

# Verifica messaggi nella chat
$chatId = "chat_associated_with_booking"
curl.exe -X GET "https://[API_URL]/chats/$chatId/messages" `
  -H "Authorization: Bearer $token"
```

#### Expected Results
- ✅ Booking status aggiornato a "confirmed"
- ✅ Messaggio automatico "✅ Candidatura Confermata!" in chat
- ✅ Messaggio contiene dettagli azienda, posizione, data inizio
- ✅ Broadcast WebSocket inviato

#### Test Steps - Rigetta Booking
```powershell
# Rigetta il booking con motivo
curl.exe -X PATCH "https://[API_URL]/bookings/$bookingId/status" `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"status": "rejected", "rejectionReason": "Abbiamo scelto altri candidati con più esperienza"}'
```

#### Expected Results
- ✅ Booking status aggiornato a "rejected"
- ✅ Messaggio automatico "❌ Candidatura Non Accettata" in chat
- ✅ Messaggio include il `rejectionReason`
- ✅ Broadcast WebSocket inviato

---

## 🚀 Deployment

### 1. Deploy Chat Service (per aggiornare layer)
```powershell
cd C:\Users\miner\Desktop\Beezey\beezey-BE\scripts
.\deploy-chat-system.bat
```

### 2. Deploy Bookings Service (con nuovo layer e policy)
```powershell
cd C:\Users\miner\Desktop\Beezey\beezey-BE\infra\services\bookings
sam build
sam deploy --config-file samconfig.toml
```

### 3. Configurare DEFAULT_BACKOFFICE_OPERATOR_ID

**Opzione A: Via Console AWS Lambda**
1. Vai su Lambda Console
2. Seleziona `dev-chat-send-message`
3. Configuration → Environment Variables
4. Aggiungi: `DEFAULT_BACKOFFICE_OPERATOR_ID` = `[user_id_operatore]`

**Opzione B: Aggiornare template.yaml**
```yaml
SendMessageFunction:
  Properties:
    Environment:
      Variables:
        DEFAULT_BACKOFFICE_OPERATOR_ID: !Ref BackofficeOperatorUserId
```

---

## 📊 Monitoring

### CloudWatch Logs

**Per operatore backoffice:**
```
"Backoffice operator assigned to chat [chat_id] due to @beebusy mention"
```

**Per messaggi booking status:**
```
"Booking status message sent to chat [chat_id]"
```

### Metriche da Monitorare

1. **Numero di assegnazioni operatore** - CloudWatch custom metric
2. **Tempo di risposta operatori** - Dal messaggio @beebusy alla prima risposta
3. **Messaggi booking status inviati** - Count per tipo (confirmed, rejected, etc.)
4. **Errori nelle integrazioni chat** - Log errors non-critical

---

## 🔧 Troubleshooting

### Operatore non viene assegnato

**Possibili cause:**
1. ❌ `DEFAULT_BACKOFFICE_OPERATOR_ID` non configurato
2. ❌ Lambda send-message non ha policy DynamoDB per update chat
3. ❌ Typo nel messaggio (deve contenere `@beebusy`)

**Soluzione:**
- Controlla CloudWatch Logs per errori
- Verifica configurazione environment variable
- Testa con `@beebusy` minuscolo

### Messaggi booking status non vengono inviati

**Possibili cause:**
1. ❌ ChatSharedLayer non attachato a update-booking-status
2. ❌ Policy DynamoDB mancanti per Chats/Messages tables
3. ❌ Nessuna chat associata al booking
4. ❌ Indice `bookingId-index` non presente su Chats table

**Soluzione:**
- Verifica che il layer sia attachato: `aws lambda get-function --function-name dev-bookings-update-status`
- Controlla che esista la chat: `aws dynamodb query --table-name dev-Chats --index-name bookingId-index ...`
- Verifica CloudWatch Logs per import errors

### Operatore non può leggere/scrivere messaggi

**Possibili cause:**
1. ❌ Lambda get-messages non verifica `has_backoffice_access`
2. ❌ Lambda send-message non permette operatore come sender

**Soluzione:**
- Verificare logica autorizzazione in entrambe le Lambda
- Testare con user_id corrispondente al backofficeOperatorId

---

## 📝 Note Implementative

### Performance
- ✅ Assegnazione operatore è **non-blocking** - se fallisce, il messaggio dell'utente viene comunque salvato
- ✅ Invio messaggi booking status è **non-blocking** - se fallisce, l'update del booking procede comunque

### Sicurezza
- ✅ Solo utenti con cognito:groups `beezey_staff`, `beezey_admin`, `admins` possono essere operatori
- ✅ Gli operatori backoffice vedono TUTTE le conversazioni della chat (come terzo interlocutore)

### Scalabilità
- 🔄 **TODO**: Implementare load balancing tra più operatori (attualmente usa DEFAULT_BACKOFFICE_OPERATOR_ID fisso)
- 🔄 **TODO**: Sistema di rotazione/assegnazione intelligente basato su workload

### Estensioni Future
- 📌 Sistema di ticket per tracking richieste supporto
- 📌 Dashboard backoffice per gestire chat assegnate
- 📌 Metriche di performance operatori (tempo risposta, soddisfazione)
- 📌 Escalation automatica se operatore non risponde entro X minuti
