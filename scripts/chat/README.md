# Chat System Testing

## Interactive Chat Clients (Live Demo)

Per testare la chat in tempo reale con due terminali separati:

### Worker Chat Client

```powershell
.\worker-chat.ps1
```

- Crea o si connette a una chat esistente
- Invia messaggi come worker
- Vede i messaggi della company in tempo reale
- Comandi disponibili:
  - `/refresh` - Ricarica i messaggi
  - `/help` - Richiede aiuto a Beezey
  - `/quit` - Esce dalla chat

### Company Chat Client

```powershell
.\company-chat.ps1
```

- Si connette a una chat esistente (inserisci il Chat ID dal worker)
- Invia messaggi come company
- Vede i messaggi del worker in tempo reale
- Comandi disponibili:
  - `/refresh` - Ricarica i messaggi
  - `/mark <msg_id>` - Marca un messaggio come letto
  - `/quit` - Esce dalla chat

### Come testare la chat live

1. Apri **due terminali PowerShell separati**
2. Nel **primo terminale** (Worker):
   ```powershell
   cd scripts\chat
   .\worker-chat.ps1
   ```
   - Premi INVIO quando chiede il Chat ID (creerà una nuova chat)
   - Copia il **Chat ID** mostrato (es. `chat_abc123...`)

3. Nel **secondo terminale** (Company):
   ```powershell
   cd scripts\chat
   .\company-chat.ps1
   ```
   - Incolla il **Chat ID** copiato dal worker

4. **Invia messaggi** da entrambi i terminali e vedili apparire in tempo reale! 🎉

---

## Complete Test Setup

Lo script `complete-test-setup.ps1` esegue un test end-to-end completo del sistema di chat Beezey.

### Cosa fa lo script

1. **Crea utenti test** in Cognito (se non esistono già):
   - Worker: `worker.test@beezey.local` (password: `TestWorker123!`)
   - Company: `company.test@beezey.local` (password: `TestCompany123!`)

2. **Autentica entrambi gli utenti** e ottiene i token JWT

3. **Crea una nuova chat** con booking details di test

4. **Invia un messaggio** di test dal worker

5. **Esegue 6 test completi**:
   - ✅ Get messages (worker view)
   - ✅ Get messages (company view)
   - ✅ Send message (company reply)
   - ✅ Update message state (mark as read)
   - ✅ Get upload URL for attachments
   - ✅ Request Beezey help (automatic response)

### Come eseguire

```powershell
cd scripts\chat
.\complete-test-setup.ps1
```

### Requisiti

- AWS CLI configurato
- PowerShell 5.1+
- Accesso al Cognito User Pool: `eu-south-1_0oK9agPYd`
- API Gateway endpoint: `https://ivs8m2z7bh.execute-api.eu-south-1.amazonaws.com/dev`

### Output

Lo script mostra un report dettagliato con:
- Stato di ogni step (creazione utenti, autenticazione, chat, messaggio)
- Risultati dei 6 test (PASSED/FAILED)
- Sommario finale con count dei test passati/falliti
- Informazioni sull'environment di test (user IDs, chat ID)

### Note

- Gli utenti test vengono creati solo una volta e riutilizzati nelle esecuzioni successive
- Ogni esecuzione crea una nuova chat con un nuovo booking_id random
- I file temporanei JSON vengono creati durante l'esecuzione e rimossi automaticamente
- Lo script usa file temporanei senza BOM per evitare problemi di encoding con curl

---

## Test Endpoint Specifici

### Test Upload File S3

Test completo del caricamento di allegati su S3:

```powershell
.\test-file-upload.ps1
```

**Cosa testa:**
1. Autenticazione worker
2. Creazione chat
3. Creazione file di test (PDF)
4. Richiesta presigned URL
5. Upload file su S3 con encryption AES256
6. Verifica file in S3 con `aws s3api head-object`
7. Invio messaggio con attachment
8. Verifica messaggio con attachment in DynamoDB

### Test Set Sticker

Test completo dell'aggiunta di sticker/reazioni ai messaggi:

```powershell
.\test-set-sticker.ps1
```

**Cosa testa:**
1. Autenticazione worker e company
2. Creazione chat
3. Invio messaggio da worker
4. Aggiunta sticker `thumbs_up` da company
5. Verifica sticker nel messaggio
6. Cambio sticker a `heart`
7. Rimozione sticker (stringa vuota)

**Sticker disponibili:**
- `thumbs_up` 👍
- `thumbs_down` 👎
- `heart` ❤️
- `smile` 😊
- `fire` 🔥
- `check` ✅
- `question` ❓

### Test Get My Chats

Test della nuova API per ottenere la lista delle chat personali:

```powershell
.\test-get-my-chats.ps1
```

**Cosa testa:**
1. GET /chats come worker (vede logo azienda + foto rappresentante)
2. GET /chats come company representative (vede foto worker)

**Response include:**
- Chat metadata (ID, booking ID, status, timestamp)
- Ultimo messaggio (preview, stato, timestamp)
- Foto profilo interlocutore
- Per worker: Logo azienda + Nome azienda + Foto rappresentante
- Per company: Foto worker

**Campi risposta:**
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
      "companyId": "comp_456",           // Solo worker view
      "companyName": "Hotel Bella Vista", // Solo worker view
      "companyLogo": "https://...",       // Solo worker view
      "interlocutorId": "user_789",
      "interlocutorName": "Marco Rossi",
      "interlocutorPhoto": "https://..."
    }
  ],
  "count": 1
}
```
