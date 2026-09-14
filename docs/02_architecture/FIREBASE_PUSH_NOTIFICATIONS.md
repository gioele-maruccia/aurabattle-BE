# Firebase Push Notifications - Implementazione Completa

## 📋 Overview

Implementazione completa delle notifiche push Firebase Cloud Messaging (FCM) per:
1. **Nuovi messaggi in chat** - Notifica quando un utente riceve un nuovo messaggio
2. **Conferma/rifiuto upgrade profilo** - Notifica quando il backoffice approva o respinge i documenti

---

## 🏗️ Architettura

### Componenti Implementati

```
┌─────────────────────────────────────────────────────────────┐
│                    FIREBASE ADMIN SDK LAYER                  │
│  - firebase_notifications.py (modulo comune)                 │
│  - firebase-admin SDK (versione 6.4.0)                       │
│  - Service Account JSON (beebusy-b0a51-9aaf1bddae28.json)   │
└─────────────────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────┴─────────────────────┐
        │                                             │
┌───────▼──────────┐                    ┌────────────▼─────────┐
│  USER-API        │                    │   CHAT SERVICE       │
│                  │                    │                      │
│  POST /users/    │                    │  POST /chats/{id}/   │
│  {userId}/       │                    │  messages            │
│  fcm-token       │                    │                      │
│                  │                    │  • Invia notifica    │
│  • Registra FCM  │                    │    al destinatario   │
│    token in DB   │                    │  • Include nome      │
│                  │                    │    mittente e        │
└──────────────────┘                    │    anteprima         │
                                        └──────────────────────┘
        ┌─────────────────────┐
        │  BACKOFFICE SERVICE  │
        │                      │
        │  PUT /documents/     │
        │  {user}/{doc}/status │
        │                      │
        │  • Approva/respinge  │
        │    documenti         │
        │  • Invia notifica    │
        │    upgrade profilo   │
        └──────────────────────┘
```

---

## 📦 File Creati/Modificati

### 1. Layer Firebase Admin SDK
**Path**: `src/lambdas/layers/firebase-admin/`

```
firebase-admin/
├── python/
│   └── firebase_notifications.py    # Modulo con funzioni di notifica
├── requirements.txt                  # firebase-admin==6.4.0
└── beebusy-b0a51-9aaf1bddae28.json  # Service Account (da copiare)
```

**Funzioni disponibili**:
- `send_chat_message_notification()` - Notifica nuovo messaggio
- `send_profile_upgrade_notification()` - Notifica upgrade profilo
- `send_notification()` - Funzione generica

### 2. Endpoint Registrazione FCM Token
**Path**: `src/lambdas/services/user-api/register-fcm-token/`

**Endpoint**: `POST /users/{userId}/fcm-token`

```json
Request Body:
{
  "fcm_token": "fcm-device-token-from-firebase"
}

Response:
{
  "message": "FCM token registered successfully",
  "user_id": "cognito-user-id",
  "fcm_token_updated_at": "2026-01-16T10:00:00Z"
}
```

### 3. Lambda Chat - Send Message
**Path**: `src/lambdas/services/chat/send-message/app.py`

**Modifiche**:
- Import Firebase layer
- Lettura FCM token dal destinatario in UserProfiles table
- Invio notifica push (best-effort, non bloccante)

**Payload notifica**:
```json
{
  "notification": {
    "title": "Mario Rossi",
    "body": "Ciao! Come va il lavoro?"
  },
  "data": {
    "actionType": "chat",
    "chatId": "chat_123",
    "senderId": "user_456",
    "senderName": "Mario Rossi",
    "messagePreview": "Ciao! Come va...",
    "timestamp": "1737024000000"
  }
}
```

### 4. Lambda Backoffice - Update Document Status
**Path**: `src/lambdas/services/backoffice/backoffice-update-document-status/app.py`

**Modifiche**:
- Import Firebase layer
- Lettura FCM token da UserProfiles table
- Invio notifica quando `verification_status` cambia a `approved` o `rejected`

**Payload notifica (approved)**:
```json
{
  "notification": {
    "title": "Profilo verificato!",
    "body": "La verifica del tuo profilo come lavoratore è andata a buon fine."
  },
  "data": {
    "actionType": "upgrade",
    "profileType": "worker",
    "verificationStatus": "approved"
  }
}
```

**Payload notifica (rejected)**:
```json
{
  "notification": {
    "title": "Verifica profilo respinta",
    "body": "La verifica del tuo profilo non è andata a buon fine. Controlla i documenti e riprova."
  },
  "data": {
    "actionType": "upgrade",
    "profileType": "worker",
    "verificationStatus": "rejected"
  }
}
```

---

## 🚀 Deployment

### 1. Preparazione Firebase Service Account

```powershell
# Il file è già in modules, copialo nel layer
Copy-Item `
  "modules/beebusy-b0a51-9aaf1bddae28.json" `
  "src/lambdas/layers/firebase-admin/python/beebusy-b0a51-9aaf1bddae28.json"
```

**⚠️ IMPORTANTE**: Non committare mai il file service account!

### 2. Build del Layer Firebase

```powershell
cd src/lambdas/layers/firebase-admin

# Installa dipendenze nel layer
pip install -r requirements.txt -t python/

# Il layer deve avere questa struttura:
# firebase-admin/
#   ├── python/
#   │   ├── firebase_notifications.py
#   │   ├── firebase_admin/          (da pip)
#   │   ├── google/                  (da pip)
#   │   └── beebusy-b0a51-9aaf1bddae28.json
#   └── requirements.txt
```

### 3. Deploy dei Servizi

```powershell
# 1. Deploy User API (endpoint FCM token)
cd infra/services/user-api
sam build
sam deploy --guided

# 2. Deploy Chat Service (notifiche messaggi)
cd ../chat
sam build
sam deploy --guided

# 3. Deploy Backoffice Service (notifiche upgrade)
cd ../backoffice
sam build
sam deploy --guided
```

---

## 🔧 Configurazione Database

### DynamoDB UserProfiles - Nuovi Campi

La tabella `{Environment}-UserProfiles` ora include:

```
user_id (PK)
├── fcm_token: string                   # FCM token del device
├── fcm_token_updated_at: string        # Timestamp ultimo aggiornamento
└── ... (altri campi esistenti)
```

**Nota**: I campi vengono creati automaticamente al primo `POST /users/{userId}/fcm-token`

---

## 📱 Integrazione Frontend

### 1. Login Flow - Registrazione Token

```dart
// Dopo il login dell'utente
Future<void> registerFcmToken() async {
  // 1. Ottieni FCM token da Firebase
  final fcmToken = await FirebaseMessaging.instance.getToken();
  
  // 2. Ottieni userId dal JWT Cognito
  final userId = await getUserIdFromToken();
  
  // 3. Registra token sul backend
  final response = await http.post(
    Uri.parse('$apiUrl/users/$userId/fcm-token'),
    headers: {
      'Authorization': 'Bearer $jwtToken',
      'Content-Type': 'application/json',
    },
    body: jsonEncode({
      'fcm_token': fcmToken,
    }),
  );
  
  if (response.statusCode == 200) {
    print('FCM token registered successfully');
  }
}
```

### 2. Gestione Notifiche in Arrivo

```dart
// Setup Firebase Messaging listener
FirebaseMessaging.onMessage.listen((RemoteMessage message) {
  print('Notification received: ${message.notification?.title}');
  
  // Estrai actionType dal payload
  final actionType = message.data['actionType'];
  
  if (actionType == 'chat') {
    // Naviga alla chat
    final chatId = message.data['chatId'];
    Navigator.pushNamed(context, '/chat/$chatId');
  }
  else if (actionType == 'upgrade') {
    // Mostra dialog profilo verificato
    final status = message.data['verificationStatus'];
    showUpgradeStatusDialog(status);
  }
});

// Notifiche in background/terminated
FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
  handleNotificationTap(message);
});
```

---

## 🧪 Testing

### 1. Test Registrazione Token

```powershell
# Richiesta
$JWT_TOKEN = "eyJraWQ..."  # JWT da Cognito
$USER_ID = "12345678-1234-1234-1234-123456789abc"
$FCM_TOKEN = "fcm-token-from-firebase-app"

curl -X POST `
  "https://api.beezey.com/users/$USER_ID/fcm-token" `
  -H "Authorization: Bearer $JWT_TOKEN" `
  -H "Content-Type: application/json" `
  -d "{\"fcm_token\": \"$FCM_TOKEN\"}"

# Risposta attesa (200 OK)
{
  "message": "FCM token registered successfully",
  "user_id": "12345678-1234-1234-1234-123456789abc",
  "fcm_token_updated_at": "2026-01-16T10:00:00Z"
}
```

### 2. Test Notifica Chat

```powershell
# 1. Utente A registra il suo FCM token
# 2. Utente B invia un messaggio nella chat

curl -X POST `
  "https://api.beezey.com/chats/$CHAT_ID/messages" `
  -H "Authorization: Bearer $JWT_TOKEN_B" `
  -H "Content-Type: application/json" `
  -d '{
    "message_text": "Ciao! Come va?"
  }'

# Risultato: Utente A riceve notifica push
```

### 3. Test Notifica Upgrade Profilo

```powershell
# 1. Utente carica documenti
# 2. Backoffice approva un documento

curl -X PUT `
  "https://api.beezey.com/documents/$USER_SUB/$DOC_ID/status" `
  -H "Authorization: Bearer $ADMIN_JWT_TOKEN" `
  -H "Content-Type: application/json" `
  -d '{
    "status": "APPROVED"
  }'

# Risultato: Se tutti i documenti sono approvati, utente riceve notifica
```

---

## 🔍 Troubleshooting

### Notifiche non arrivano

**1. Verifica FCM Token registrato**
```sql
-- DynamoDB query
SELECT fcm_token, fcm_token_updated_at 
FROM UserProfiles 
WHERE user_id = 'xxx'
```

**2. Verifica Layer Firebase caricato**
```powershell
# Lambda deve avere layer firebase-admin-layer
aws lambda get-function --function-name dev-chat-send-message
```

**3. Controlla CloudWatch Logs**
```
Cerca:
- "Firebase layer not available" → Layer non caricato
- "FCM token is invalid or unregistered" → Token scaduto
- "User xxx has no FCM token registered" → Token non salvato
```

### Errori Firebase

**`UnregisteredError`**: Token FCM non valido o scaduto
- Soluzione: App deve registrare nuovo token

**`ImportError: firebase_admin`**: Layer non caricato correttamente
- Soluzione: Rebuilda layer e rideploya Lambda

---

## 📊 Monitoring

### CloudWatch Metrics da Monitorare

1. **Successo invio notifiche**
   - Log: `"Push notification sent successfully"`
   - Metric: Custom metric `PushNotificationSuccess`

2. **Fallimento invio notifiche**
   - Log: `"Failed to send push notification"`
   - Metric: Custom metric `PushNotificationFailure`

3. **Token non registrati**
   - Log: `"has no FCM token registered"`
   - Metric: Custom metric `MissingFcmToken`

---

## 🔐 Sicurezza

### Service Account

- ✅ File NON committato nel repository
- ✅ Incluso nel `.gitignore`
- ✅ Copiato manualmente nel layer durante deployment
- ✅ Caricato come parte del layer Lambda (non esposto)

### Permissions

Le Lambda hanno solo permessi per:
- ✅ Leggere FCM token da UserProfiles (read-only)
- ✅ Inviare notifiche via Firebase SDK
- ❌ NON possono modificare FCM token (solo endpoint dedicato)

---

## 📚 Reference

- Firebase Admin SDK: https://firebase.google.com/docs/admin/setup
- Cloud Messaging: https://firebase.google.com/docs/cloud-messaging/admin/send-messages
- Flutter FCM: https://firebase.flutter.dev/docs/messaging/usage

---

## ✅ Checklist Deployment

Prima di andare in produzione:

- [ ] File service account copiato nel layer
- [ ] Layer buildato con `pip install`
- [ ] Template SAM aggiornati (chat, backoffice, user-api)
- [ ] SAM build completato senza errori
- [ ] SAM deploy completato senza errori
- [ ] Endpoint `/users/{userId}/fcm-token` testato
- [ ] Notifica chat testata
- [ ] Notifica upgrade profilo testata
- [ ] CloudWatch logs verificati
- [ ] Frontend configurato per ricevere notifiche
- [ ] Documentazione condivisa con team frontend

---

## 🆘 Support

Per problemi o domande:
1. Verifica CloudWatch Logs delle Lambda
2. Testa con Postman/curl prima dell'app
3. Verifica che FCM token sia registrato in DB
4. Controlla che Firebase project sia configurato correttamente
