# Firebase Push Notifications - Implementation Summary

## ✅ Implementazione Completata

L'implementazione delle notifiche push Firebase è stata completata con successo!

### 🎯 Funzionalità Implementate

1. **Notifiche Chat** ✅
   - Invio automatico quando arriva un nuovo messaggio
   - Include nome mittente e anteprima messaggio
   - Payload con `actionType: 'chat'` per navigazione app

2. **Notifiche Profile Upgrade** ✅
   - Invio quando backoffice approva/respinge documenti
   - Messaggi diversi per approved/rejected
   - Payload con `actionType: 'upgrade'`

3. **Endpoint Registrazione Token** ✅
   - `POST /users/{userId}/fcm-token`
   - Salva FCM token nel profilo utente
   - Aggiornato ad ogni login

---

## 📁 File Creati

### Layer Firebase Admin SDK
```
src/lambdas/layers/firebase-admin/
├── python/
│   └── firebase_notifications.py      # Funzioni notifiche
├── requirements.txt                    # firebase-admin==6.4.0
└── README.md                          # Documentazione layer
```

### Lambda Endpoint FCM Token
```
src/lambdas/services/user-api/register-fcm-token/
└── app.py                             # POST /users/{userId}/fcm-token
```

### Documentazione
```
docs/02_architecture/
└── FIREBASE_PUSH_NOTIFICATIONS.md     # Guida completa setup e test

scripts/
└── deploy-firebase-notifications.ps1  # Script deployment automatico
```

---

## 🔧 File Modificati

### Templates SAM

1. **`infra/services/user-api/template.yaml`**
   - Aggiunta Lambda `RegisterFcmTokenFunction`
   - Endpoint `POST /users/{userId}/fcm-token`

2. **`infra/services/chat/template.yaml`**
   - Aggiunto `FirebaseAdminLayer`
   - Lambda `SendMessageFunction` usa layer Firebase
   - Aggiunte permissions per leggere UserProfiles

3. **`infra/services/backoffice/template.yaml`**
   - Aggiunto `FirebaseAdminLayer`
   - Lambda `UpdateDocumentStatusFunction` usa layer Firebase
   - Aggiunte permissions per leggere UserProfiles

### Lambda Functions

1. **`src/lambdas/services/chat/send-message/app.py`**
   - Import Firebase notifications
   - Lettura FCM token destinatario da DB
   - Invio notifica dopo salvataggio messaggio (best-effort)

2. **`src/lambdas/services/backoffice/backoffice-update-document-status/app.py`**
   - Import Firebase notifications
   - Lettura FCM token da UserProfiles
   - Invio notifica quando verification_status cambia

### Configurazione

1. **`.gitignore`**
   - Aggiunto pattern per escludere service account files
   - Pattern: `beebusy-*.json`, `*-firebase-adminsdk-*.json`

---

## 🚀 Deployment

### Quick Start

```powershell
# Script automatico (raccomandato)
.\scripts\deploy-firebase-notifications.ps1 -Environment dev

# Oppure manuale:
# 1. Copia service account nel layer
Copy-Item modules\beebusy-b0a51-9aaf1bddae28.json `
  src\lambdas\layers\firebase-admin\python\

# 2. Build layer
cd src\lambdas\layers\firebase-admin
pip install -r requirements.txt -t python/

# 3. Deploy servizi
cd infra\services\user-api
sam build && sam deploy

cd ..\chat
sam build && sam deploy

cd ..\backoffice
sam build && sam deploy
```

---

## 📱 Integrazione Frontend

Il frontend deve implementare:

### 1. Registrazione Token (dopo login)

```dart
// Ottieni FCM token
final fcmToken = await FirebaseMessaging.instance.getToken();

// Registra sul backend
await http.post(
  Uri.parse('$apiUrl/users/$userId/fcm-token'),
  headers: {'Authorization': 'Bearer $jwtToken'},
  body: jsonEncode({'fcm_token': fcmToken}),
);
```

### 2. Gestione Notifiche

```dart
// Foreground
FirebaseMessaging.onMessage.listen((message) {
  if (message.data['actionType'] == 'chat') {
    // Naviga a chat
    Navigator.pushNamed(context, '/chat/${message.data['chatId']}');
  }
  else if (message.data['actionType'] == 'upgrade') {
    // Mostra dialog upgrade
    showUpgradeDialog(message.data['verificationStatus']);
  }
});

// Background/terminated
FirebaseMessaging.onMessageOpenedApp.listen(handleNotification);
```

---

## 🧪 Testing

### Test 1: Registrazione Token

```powershell
curl -X POST `
  "https://api.beezey.com/users/$USER_ID/fcm-token" `
  -H "Authorization: Bearer $JWT_TOKEN" `
  -H "Content-Type: application/json" `
  -d '{"fcm_token": "test-token-123"}'
```

**Expected**: HTTP 200, token salvato in UserProfiles

### Test 2: Notifica Chat

1. Utente A registra FCM token
2. Utente B invia messaggio nella chat
3. Utente A riceve notifica push

**CloudWatch Log**: `"Push notification sent to {userId}"`

### Test 3: Notifica Upgrade

1. Utente carica documenti
2. Backoffice approva documenti
3. Utente riceve notifica "Profilo verificato!"

**CloudWatch Log**: `"Profile upgrade notification sent to user {userId}"`

---

## 🔍 Monitoring

### CloudWatch Logs - Pattern da Cercare

**Successo**:
- `"FCM token registered for user"`
- `"Push notification sent successfully"`
- `"Profile upgrade notification sent"`

**Errore**:
- `"Firebase layer not available"` → Layer non caricato
- `"has no FCM token registered"` → Token non salvato
- `"FCM token is invalid or unregistered"` → Token scaduto

---

## 📊 Database Schema

### UserProfiles Table - Nuovi Campi

```
user_id: string (PK)
├── fcm_token: string                  # FCM token device
├── fcm_token_updated_at: string       # ISO timestamp
└── ... (altri campi esistenti)
```

**Nota**: Campi creati automaticamente al primo POST

---

## 🔐 Sicurezza

### Service Account File

- ✅ File NON committato (protetto da .gitignore)
- ✅ Caricato solo nel layer Lambda
- ✅ Non esposto pubblicamente
- ❌ Da copiare manualmente prima deployment

### Permissions Lambda

- ✅ Read-only su UserProfiles (solo FCM token)
- ✅ Invio notifiche via Firebase SDK
- ❌ NON può modificare FCM token (solo endpoint dedicato)

---

## 📚 Documentazione

### Per Sviluppatori Backend
- [docs/02_architecture/FIREBASE_PUSH_NOTIFICATIONS.md](../docs/02_architecture/FIREBASE_PUSH_NOTIFICATIONS.md)
  - Setup completo
  - Troubleshooting
  - Testing
  - Monitoring

### Per Sviluppatori Frontend
- Payload notifiche dettagliati
- Esempi integrazione Flutter
- Gestione actionType

### Per DevOps
- Script deployment automatico
- Template SAM aggiornati
- CloudWatch monitoring

---

## ✅ Checklist Pre-Production

Prima di deployare in produzione:

- [ ] Service account copiato nel layer
- [ ] Layer buildato con dipendenze
- [ ] Tutti i servizi deployati correttamente
- [ ] Endpoint FCM token testato
- [ ] Notifiche chat testate
- [ ] Notifiche upgrade profilo testate
- [ ] CloudWatch logs verificati
- [ ] Frontend configurato per ricevere notifiche
- [ ] Documentazione condivisa con team

---

## 🆘 Support & Issues

**Per problemi tecnici**:
1. Verifica CloudWatch Logs delle Lambda
2. Controlla che FCM token sia salvato in DB
3. Testa con Postman/curl prima dell'app
4. Verifica layer Firebase caricato correttamente

**Documentazione**:
- README Layer: [src/lambdas/layers/firebase-admin/README.md](../src/lambdas/layers/firebase-admin/README.md)
- Guida Completa: [docs/02_architecture/FIREBASE_PUSH_NOTIFICATIONS.md](../docs/02_architecture/FIREBASE_PUSH_NOTIFICATIONS.md)

---

## 🎉 Conclusione

L'implementazione è completa e pronta per il testing!

**Prossimi Step**:
1. Deploy in ambiente dev
2. Testing con app Flutter
3. Monitoring primi giorni
4. Deploy in produzione

**Domande?** Consulta la documentazione o contatta il team backend.
