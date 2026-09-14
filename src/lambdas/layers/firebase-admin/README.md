# Firebase Admin SDK Layer

Lambda Layer per gestire le notifiche push Firebase Cloud Messaging (FCM) in Beezey.

## 📦 Struttura

```
firebase-admin/
├── python/
│   ├── firebase_notifications.py         # Modulo con funzioni di notifica
│   ├── firebase_admin/                    # Firebase Admin SDK (da pip)
│   ├── google/                            # Google libs (da pip)
│   └── beebusy-99d60-firebase-adminsdk-fbsvc-b37bca6781.json   # Service account (NON committare!)
├── requirements.txt                       # Dipendenze Python
└── README.md                             # Questo file
```

## 🚀 Build & Deploy

### Build Locale

```powershell
# Installa dipendenze nel layer
pip install -r requirements.txt -t python/

# Copia service account dal folder modules
Copy-Item ..\..\..\..\modules\beebusy-99d60-firebase-adminsdk-fbsvc-b37bca6781.json python\
```

### Deploy con SAM

Il layer viene deployato automaticamente quando si builda un servizio che lo utilizza:

```powershell
cd infra/services/chat
sam build
sam deploy
```

## 📚 Utilizzo nelle Lambda

### 1. Aggiungi Layer al Template SAM

```yaml
Resources:
  FirebaseAdminLayer:
    Type: AWS::Serverless::LayerVersion
    Properties:
      LayerName: !Sub '${Environment}-firebase-admin-layer'
      ContentUri: ../../../src/lambdas/layers/firebase-admin/
      CompatibleRuntimes:
        - python3.13
      RetentionPolicy: Retain
    Metadata:
      BuildMethod: python3.13

  MyFunction:
    Type: AWS::Serverless::Function
    Properties:
      Layers:
        - !Ref FirebaseAdminLayer
      Environment:
        Variables:
          FIREBASE_SERVICE_ACCOUNT_PATH: /opt/firebase/beebusy-99d60-firebase-adminsdk-fbsvc-b37bca6781.json
```

### 2. Import nel Codice Lambda

```python
import sys
sys.path.append('/opt/firebase')

from firebase_notifications import (
    send_chat_message_notification,
    send_profile_upgrade_notification
)

# Invia notifica chat
send_chat_message_notification(
    fcm_token="user-fcm-token",
    sender_name="Mario Rossi",
    message_preview="Ciao! Come va?",
    chat_id="chat_123",
    sender_id="user_456"
)

# Invia notifica upgrade profilo
send_profile_upgrade_notification(
    fcm_token="user-fcm-token",
    profile_type="worker",
    verification_status="approved"
)
```

## 🔐 Sicurezza

### Service Account

**⚠️ IMPORTANTE**: Il file `beebusy-99d60-firebase-adminsdk-fbsvc-b37bca6781.json` contiene credenziali sensibili!

- ✅ NON committare mai nel repository
- ✅ Incluso nel `.gitignore`
- ✅ Copiare manualmente prima del build
- ✅ Viene caricato nel layer Lambda (non esposto pubblicamente)

### Permissions

Il service account ha permessi per:
- ✅ Inviare notifiche FCM
- ✅ Accesso Firebase project `beebusy-b0a51`
- ❌ NON può modificare progetti Firebase
- ❌ NON può accedere ad altri servizi Google Cloud

## 🔧 Funzioni Disponibili

### `send_chat_message_notification()`

Invia notifica per nuovo messaggio in chat.

**Parametri**:
- `fcm_token` (str): Token FCM del dispositivo destinatario
- `sender_name` (str): Nome del mittente
- `message_preview` (str): Anteprima del messaggio (max 100 caratteri)
- `chat_id` (str): ID della chat
- `sender_id` (str): ID del mittente

**Ritorna**: `bool` - True se inviata con successo

**Payload notifica**:
```json
{
  "notification": {
    "title": "Mario Rossi",
    "body": "Ciao! Come va?"
  },
  "data": {
    "actionType": "chat",
    "chatId": "chat_123",
    "senderId": "user_456",
    "senderName": "Mario Rossi",
    "messagePreview": "Ciao! Come va?",
    "timestamp": "1737024000000"
  }
}
```

### `send_profile_upgrade_notification()`

Invia notifica per cambio stato verifica profilo.

**Parametri**:
- `fcm_token` (str): Token FCM del dispositivo utente
- `profile_type` (str): Tipo profilo ('worker' o 'company')
- `verification_status` (str): Stato ('approved' o 'rejected')

**Ritorna**: `bool` - True se inviata con successo

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

### `send_notification()`

Funzione generica per inviare notifiche custom.

**Parametri**:
- `fcm_token` (str): Token FCM destinatario
- `title` (str): Titolo notifica
- `body` (str): Corpo notifica
- `data` (dict, optional): Payload custom

**Ritorna**: `bool` - True se inviata con successo

## 🧪 Testing

### Test Locale (Richiede Firebase Project)

```python
# test_firebase.py
from firebase_notifications import send_notification

# Test con token reale da app
test_token = "fcm-token-from-real-device"

success = send_notification(
    fcm_token=test_token,
    title="Test Notification",
    body="This is a test",
    data={"test": "true"}
)

print(f"Notification sent: {success}")
```

## 🐛 Troubleshooting

### `ImportError: No module named 'firebase_admin'`

**Causa**: Dipendenze non installate nel layer

**Soluzione**:
```powershell
pip install -r requirements.txt -t python/
```

### `FileNotFoundError: Service account not found`

**Causa**: File service account non copiato nel layer

**Soluzione**:
```powershell
Copy-Item ..\..\..\..\modules\beebusy-99d60-firebase-adminsdk-fbsvc-b37bca6781.json python\
```

### `UnregisteredError: FCM token is invalid`

**Causa**: Token FCM scaduto o non valido

**Soluzione**: App deve registrare nuovo token via `POST /users/{userId}/fcm-token`

## 📊 Monitoring

### CloudWatch Logs

Cerca questi pattern nei log Lambda:

**Successo**:
```
"Firebase Admin SDK initialized successfully"
"Chat notification sent successfully. Message ID: ..."
"Profile upgrade notification sent successfully. Message ID: ..."
```

**Errore**:
```
"Failed to initialize Firebase: ..."
"FCM token is invalid or unregistered: ..."
"Error sending notification: ..."
```

## 🔄 Aggiornamenti

### Update Firebase Admin SDK

```powershell
# Aggiorna versione in requirements.txt
echo "firebase-admin==6.5.0" > requirements.txt

# Reinstalla
pip install -r requirements.txt -t python/ --upgrade
```

### Rebuild Layer

Dopo modifiche a `firebase_notifications.py` o aggiornamento SDK:

```powershell
cd infra/services/chat
sam build
sam deploy
```

## 📚 Reference

- [Firebase Admin SDK Python](https://firebase.google.com/docs/reference/admin/python)
- [Cloud Messaging Admin](https://firebase.google.com/docs/cloud-messaging/admin/send-messages)
- [AWS Lambda Layers](https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html)
