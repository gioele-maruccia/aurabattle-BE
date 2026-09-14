# Guida Test Profile Upgrade su Swagger

## Panoramica

Questa guida spiega come testare il flusso completo di profile upgrade su Swagger, inclusi caricamento documenti, verifica selfie e confronto facciale.

## Prerequisiti

1. **Swagger UI in esecuzione**
   ```bash
   cd swagger
   ./launch-swagger.sh dev
   ```

2. **Account Cognito** - Devi avere un utente app registrato
3. **Immagini di test**:
   - `id_card_front.jpg` - Documento d'identità fronte (con volto visibile)
   - `id_card_back.jpg` - Documento d'identità retro
   - `selfie.jpg` - Selfie dell'utente (stesso volto del documento)

## Flusso Completo di Test

### Step 1: Autenticazione

1. Apri Swagger UI: http://localhost:8080
2. Vai a **POST /auth/login/users**
3. Inserisci le credenziali:
   ```json
   {
     "username": "user@example.com",
     "password": "YourPassword123!"
   }
   ```
4. Copia il valore di `idToken` dalla risposta
5. Clicca sul pulsante **🔓 Authorize** in alto
6. Incolla il token e clicca **Authorize**

### Step 2: Initiate Profile Upgrade

**Endpoint:** `POST /initiate-upgrade`

**Body:**
```json
{
  "username": "user@example.com",
  "upgrade_type": "worker"
}
```

**Risultato atteso:**
```json
{
  "username": "user@example.com",
  "profile_type": "worker",
  "verification_status": "pending_documents",
  "group": "workers",
  "timestamp": "2025-12-05T10:00:00Z",
  "message": "Profile upgrade initiated successfully"
}
```

### Step 3: Upload Documento Identità (Fronte)

#### 3a. Richiedi Presigned URL

**Endpoint:** `POST /documents/upload-url`

**Body:**
```json
{
  "docType": "id_card_front",
  "mime": "image/jpeg",
  "size": 2048000
}
```

**Risultato atteso:**
```json
{
  "uploadUrl": "https://beezey-dev-user-documents.s3.amazonaws.com/...",
  "documentId": "doc_123456789",
  "expiresIn": 3600
}
```

#### 3b. Upload dell'immagine su S3

**IMPORTANTE:** Questo step **non** si fa su Swagger, ma con `curl` o Postman.

```bash
# Su terminale WSL o PowerShell
curl -X PUT "https://beezey-dev-user-documents.s3.amazonaws.com/..." \
  -H "Content-Type: image/jpeg" \
  --data-binary @id_card_front.jpg
```

**PowerShell:**
```powershell
$imageBytes = [System.IO.File]::ReadAllBytes("C:\path\to\id_card_front.jpg")
Invoke-RestMethod -Uri "https://beezey-dev-user-documents.s3.amazonaws.com/..." `
  -Method PUT -Body $imageBytes -ContentType "image/jpeg"
```

**Risultato atteso:** HTTP 200 (nessun body)

### Step 4: Upload Documento Identità (Retro)

Ripeti Step 3 con:
```json
{
  "docType": "id_card_back",
  "mime": "image/jpeg",
  "size": 2048000
}
```

### Step 5: Verifica Selfie con Face Recognition

**Endpoint:** `POST /documents/verify-face`

**Preparazione del selfie:**

1. Converti l'immagine in base64:

**PowerShell:**
```powershell
$selfieBytes = [System.IO.File]::ReadAllBytes("C:\path\to\selfie.jpg")
$selfieBase64 = [Convert]::ToBase64String($selfieBytes)
$selfieBase64 | Set-Clipboard  # Copia negli appunti
```

**WSL:**
```bash
base64 -w 0 selfie.jpg > selfie_base64.txt
```

2. Chiama l'API su Swagger:

**Body:**
```json
{
  "selfie_base64": "INCOLLA_QUI_LA_STRINGA_BASE64"
}
```

#### Possibili Risultati

**✅ Success - Volto corrispondente:**
```json
{
  "success": true,
  "verification": {
    "face_detected": true,
    "face_confidence": 99.5,
    "face_match": true,
    "similarity": 95.2,
    "quality_check": "passed",
    "threshold_used": 80.0
  },
  "message": "Verifica completata con successo. Puoi procedere con il caricamento."
}
```

**❌ Error - Nessun volto rilevato:**
```json
{
  "success": false,
  "error_code": "FACE_NOT_DETECTED",
  "message": "Nessun volto rilevato nel selfie. Assicurati di essere ben inquadrato."
}
```

**❌ Error - Volti non corrispondenti:**
```json
{
  "success": false,
  "error_code": "FACE_MISMATCH",
  "message": "Il volto nel selfie non corrisponde al documento. Similarità: 45.2%",
  "details": {
    "similarity": 45.2,
    "threshold": 80.0
  }
}
```

**❌ Error - Documento non caricato:**
```json
{
  "success": false,
  "error_code": "ID_CARD_NOT_FOUND",
  "message": "Documento identità (fronte) non trovato. Caricalo prima di verificare il selfie."
}
```

### Step 6: Upload Selfie Definitivo

**Solo se Step 5 ha avuto successo!**

Ripeti Step 3 con:
```json
{
  "docType": "selfie",
  "mime": "image/jpeg",
  "size": 2048000
}
```

### Step 7: Verifica Stato Documenti

**Endpoint:** `GET /user/{user_sub}/documents/status`

**Path Parameter:**
- `user_sub`: Il tuo Cognito sub (UUID) - lo trovi nel token JWT o nella risposta di login

**Risultato atteso:**
```json
{
  "documents": [
    {
      "document_id": "doc_123",
      "document_type": "id_card_front",
      "status": "AWAITING_REVIEW",
      "uploaded_at": "2025-12-05T10:05:00Z"
    },
    {
      "document_id": "doc_124",
      "document_type": "id_card_back",
      "status": "AWAITING_REVIEW",
      "uploaded_at": "2025-12-05T10:06:00Z"
    },
    {
      "document_id": "doc_125",
      "document_type": "selfie",
      "status": "AWAITING_REVIEW",
      "uploaded_at": "2025-12-05T10:10:00Z"
    }
  ],
  "summary": {
    "total": 3,
    "approved": 0,
    "rejected": 0,
    "awaiting_review": 3
  }
}
```

## Script PowerShell Automatico

Per un test completo automatizzato, usa lo script esistente:

```powershell
cd scripts\profile-upgrade-documents
.\test-face-verification.ps1 `
  -IdCardPath "C:\path\to\id_card_front.jpg" `
  -SelfiePath "C:\path\to\selfie.jpg" `
  -Environment dev `
  -Username "user@example.com" `
  -Password "YourPassword123!"
```

Questo script esegue automaticamente tutti gli step e mostra i risultati.

## Troubleshooting

### Token scaduto
**Sintomo:** HTTP 401 Unauthorized  
**Soluzione:** Rifare login (Step 1) e aggiornare l'authorization

### Selfie troppo grande
**Sintomo:** `IMAGE_TOO_LARGE` error  
**Soluzione:** Ridimensiona l'immagine sotto i 5MB

### Volti non corrispondono con immagini corrette
**Sintomo:** `FACE_MISMATCH` con similarity < 80%  
**Possibili cause:**
- Illuminazione molto diversa tra foto e selfie
- Angolazione del volto diversa
- Occhiali/accessori presenti solo in una foto
- Foto del documento di bassa qualità

### Nessun volto rilevato
**Sintomo:** `FACE_NOT_DETECTED`  
**Possibili cause:**
- Volto troppo piccolo nell'immagine
- Illuminazione insufficiente
- Volto parzialmente coperto
- Immagine sfocata

## Note Tecniche

### AWS Rekognition
- **Region:** eu-west-1 (Rekognition non disponibile in eu-south-1)
- **Similarity Threshold:** 80%
- **Max Image Size:** 5MB
- **Supported Formats:** JPEG, PNG

### S3 Presigned URLs
- **Expiration:** 1 ora
- **Method:** PUT
- **Headers richiesti:** Content-Type

### Cognito Token
- **Expiration:** 1 ora
- **Type:** JWT IdToken
- **Header:** `Authorization: Bearer <token>`

## Testing su Postman

Se preferisci Postman a Swagger:

1. Importa la collection dalla variabile d'ambiente Swagger
2. Crea variabile `{{token}}` con il JWT
3. Usa gli stessi endpoint documentati sopra
4. Per l'upload S3, usa il tab "Body" > "binary" e seleziona il file

## Riferimenti

- [Face Verification API Documentation](./FACE_VERIFICATION_API.md)
- [Profile Upgrade Scripts](../../scripts/profile-upgrade-documents/)
- [Swagger API](../../swagger/)
