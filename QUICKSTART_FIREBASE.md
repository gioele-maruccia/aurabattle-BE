# 🚀 Quick Start - Firebase Push Notifications

## Per Backend Developer

### Deploy Immediato

```powershell
# 1. Esegui script automatico
.\scripts\deploy-firebase-notifications.ps1 -Environment dev

# 2. Verifica deployment
# Controlla CloudWatch Logs per conferma
```

### Test Manuale

```powershell
# Test endpoint FCM token
$TOKEN = "your-jwt-token"
$USER_ID = "user-id-from-cognito"

curl -X POST "https://api.beezey.com/users/$USER_ID/fcm-token" `
  -H "Authorization: Bearer $TOKEN" `
  -H "Content-Type: application/json" `
  -d '{"fcm_token": "test-fcm-token-123"}'
```

---

## Per Frontend Developer

### 1. Registra FCM Token (dopo login)

```dart
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:http/http.dart' as http;

Future<void> registerFcmToken(String userId, String jwtToken) async {
  // Ottieni token da Firebase
  final fcmToken = await FirebaseMessaging.instance.getToken();
  if (fcmToken == null) return;
  
  // Registra sul backend
  await http.post(
    Uri.parse('$apiBaseUrl/users/$userId/fcm-token'),
    headers: {
      'Authorization': 'Bearer $jwtToken',
      'Content-Type': 'application/json',
    },
    body: jsonEncode({'fcm_token': fcmToken}),
  );
}

// Chiamare dopo ogni login
await registerFcmToken(currentUser.id, authToken);
```

### 2. Gestisci Notifiche in Arrivo

```dart
void setupFirebaseMessaging() {
  // Notifiche in foreground
  FirebaseMessaging.onMessage.listen((RemoteMessage message) {
    final actionType = message.data['actionType'];
    
    if (actionType == 'chat') {
      // Naviga alla chat
      final chatId = message.data['chatId'];
      navigatorKey.currentState?.pushNamed('/chat/$chatId');
    }
    else if (actionType == 'upgrade') {
      // Mostra dialog profilo verificato
      final status = message.data['verificationStatus'];
      if (status == 'approved') {
        showSuccessDialog('Profilo verificato!');
      } else {
        showErrorDialog('Verifica respinta');
      }
    }
  });
  
  // Notifiche in background (tap per aprire app)
  FirebaseMessaging.onMessageOpenedApp.listen((message) {
    handleNotificationTap(message);
  });
}
```

### Esempio Payload

**Chat Message**:
```json
{
  "notification": {
    "title": "Mario Rossi",
    "body": "Ciao! Come va il lavoro?"
  },
  "data": {
    "actionType": "chat",
    "chatId": "chat_abc123",
    "senderId": "user_456",
    "senderName": "Mario Rossi",
    "messagePreview": "Ciao! Come va...",
    "timestamp": "1737024000000"
  }
}
```

**Profile Upgrade**:
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

---

## Per DevOps

### Monitoring CloudWatch

Cerca questi pattern nei log:

**✅ Successo**:
- `"FCM token registered for user"`
- `"Push notification sent successfully"`

**❌ Errore**:
- `"Firebase layer not available"` → Rebuilda layer
- `"has no FCM token registered"` → User non ha fatto login/registrato token
- `"FCM token is invalid"` → Token scaduto, app deve re-registrare

### Metriche da Monitorare

- Rate di successo notifiche (`PushNotificationSuccess`)
- Rate di fallimento (`PushNotificationFailure`)
- Utenti senza FCM token (`MissingFcmToken`)

---

## 📚 Documentazione Completa

- **Setup & Troubleshooting**: [docs/02_architecture/FIREBASE_PUSH_NOTIFICATIONS.md](docs/02_architecture/FIREBASE_PUSH_NOTIFICATIONS.md)
- **Layer Firebase**: [src/lambdas/layers/firebase-admin/README.md](src/lambdas/layers/firebase-admin/README.md)
- **Summary**: [FIREBASE_IMPLEMENTATION_SUMMARY.md](FIREBASE_IMPLEMENTATION_SUMMARY.md)

---

## ⚠️ IMPORTANTE

1. **Service Account**: File `beebusy-b0a51-9aaf1bddae28.json` è SENSIBILE
   - NON committare mai
   - Già in `.gitignore`
   - Copiare manualmente prima del deploy

2. **Token FCM**: Viene registrato ad ogni login
   - Può cambiare ad ogni login
   - Backend sovrascrive automaticamente il vecchio

3. **Notifiche Best-Effort**: Non bloccanti
   - Se falliscono, non interrompono l'operazione principale
   - Loggato in CloudWatch per debugging
