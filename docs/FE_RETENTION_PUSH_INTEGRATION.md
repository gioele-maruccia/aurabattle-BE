# FE Integration Guide — 3-Touch Retention Push Notifications

**Data:** Aprile 2026  
**Destinatari:** Team Flutter (Frontend)  
**Scope:** Integrazione eventi di lifecycle per il sistema di push notification di retention

---

## Contesto

Il BE ha implementato un sistema di 3 push notifications di retention per utenti "basic" che non hanno ancora completato la registrazione azienda. Le push vengono inviate a T1 (+3h), T2 (+24h da T1), T3 (+72h da T2), con un **KILL SWITCH** automatico quando l'utente completa la registrazione.

Il FE deve:
1. Notificare al BE i lifecycle event del flusso di registrazione azienda
2. Gestire la navigazione da push notification ricevuta

---

## 1. Nessuna Azione su Login

Il timer T1 viene schedulato automaticamente dal BE quando l'utente registra il token FCM (`POST /users/{userId}/fcm-token`). Il FE **non deve fare nulla di speciale al login**.

---

## 2. Endpoint da Chiamare

```
POST /v1/users/{userId}/retention-event
Authorization: Bearer {CognitoIdToken}
Content-Type: application/json

Body:
{
  "event_type": "upgrade_flow_started" | "upgrade_flow_abandoned" | "upgrade_flow_completed"
}
```

**Risposta attesa (successo):**
```json
HTTP 200
{
  "message": "ok",
  "event_type": "upgrade_flow_started"
}
```

L'endpoint è **fire-and-forget**: se fallisce, non bloccare il flusso utente.

---

## 3. Quando Inviare Ogni Evento

### 3.1 `upgrade_flow_started`

**Quando:** L'utente apre la schermata/form di registrazione azienda.

**Dove nel codice:** `initState()` della pagina di registrazione azienda.

**Effetto BE:** Il timer T1 viene rimandato di +3h dal momento della ricezione (evita push durante la compilazione del form).

```dart
@override
void initState() {
  super.initState();
  RetentionEventApi.trackEvent(
    userId: currentUser.id,
    eventType: 'upgrade_flow_started',
  );
}
```

---

### 3.2 `upgrade_flow_abandoned`

**Quando:** L'utente **chiude il form senza completarlo**. Casi da coprire:
- Back button / swipe back
- App in background per > 30 minuti (opzionale, see note)
- App kill (se tecnicamente possibile via `AppLifecycleState.detached`)

**Dove nel codice:** `WillPopScope` / `PopScope` on the registration page + `AppLifecycleListener`.

**Effetto BE:** Il prossimo push T1 userà il template "Hai bisogno di aiuto?" (recovery).

```dart
// Back press handler
PopScope(
  canPop: false,
  onPopInvoked: (didPop) async {
    if (!didPop) {
      // Send abandoned event before popping
      await RetentionEventApi.trackEvent(
        userId: currentUser.id,
        eventType: 'upgrade_flow_abandoned',
      );
      Navigator.of(context).pop();
    }
  },
  child: /* form widget */,
)
```

```dart
// App lifecycle (app goes to background while on registration page)
class _CompanyRegistrationPageState extends State<CompanyRegistrationPage>
    with WidgetsBindingObserver {

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    RetentionEventApi.trackEvent(
      userId: currentUser.id,
      eventType: 'upgrade_flow_started',
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      // Fire-and-forget — don't await
      RetentionEventApi.trackEvent(
        userId: currentUser.id,
        eventType: 'upgrade_flow_abandoned',
      );
    }
  }
}
```

> **Nota:** `upgrade_flow_abandoned` può essere inviato più volte senza problemi (idempotente). L'importante è inviarlo almeno una volta prima che T1 scatti se l'utente ha abbandonato.

---

### 3.3 `upgrade_flow_completed`

**Quando:** Il form è stato inviato con successo (risposta `200` dall'API di registrazione azienda).

**Effetto BE:** **KILL SWITCH** — tutti i job T1/T2/T3 vengono cancellati immediatamente. Nessuna altra push verrà inviata.

```dart
try {
  final response = await companyApi.registerCompany(formData);
  if (response.statusCode == 200) {
    // KILL SWITCH: inform BE that user completed the upgrade
    await RetentionEventApi.trackEvent(
      userId: currentUser.id,
      eventType: 'upgrade_flow_completed',
    );
    // Navigate to success page
    Navigator.pushReplacementNamed(context, '/company-dashboard');
  }
} catch (e) {
  // handle error
}
```

---

## 4. Classe Helper Consigliata

```dart
import 'package:flutter/foundation.dart';

class RetentionEventApi {
  static Future<void> trackEvent({
    required String userId,
    required String eventType,
  }) async {
    try {
      final token = await AuthService.getIdToken();
      await ApiClient.post(
        '/v1/users/$userId/retention-event',
        body: {'event_type': eventType},
        headers: {'Authorization': 'Bearer $token'},
      );
      debugPrint('[Retention] Event tracked: $eventType');
    } catch (e) {
      // Fire-and-forget: non bloccare il flusso utente
      debugPrint('[Retention] Event tracking failed (non-critical): $e');
    }
  }
}
```

---

## 5. Gestione Push Ricevuta (Deep Link)

Le push di retention hanno `actionType: "upgrade_reminder"`. Il FE deve navigare alla schermata di registrazione azienda.

**Payload della push:**
```json
{
  "notification": {
    "title": "Serve aiuto con i dati aziendali?",
    "body": "Registra la tua azienda su BeeBusy e inizia a trovare personale qualificato."
  },
  "data": {
    "actionType": "upgrade_reminder",
    "step": "T1",
    "variant": "default",
    "deepLinkTarget": "company_registration"
  }
}
```

**Handler da aggiungere/aggiornare:**

```dart
void handlePushNotification(RemoteMessage message) {
  final actionType = message.data['actionType'];

  switch (actionType) {
    case 'upgrade_reminder':
      // Navigate to company registration page
      Navigator.pushNamed(context, '/company-registration');
      // Optional: log that user clicked the push (for KPI tracking)
      RetentionEventApi.trackEvent(
        userId: currentUser.id,
        eventType: 'upgrade_flow_started',  // re-send started on click
      );
      break;

    case 'chat':
      // existing handler...
      break;

    case 'upgrade':
      // existing handler...
      break;
  }
}
```

> Se l'app è in foreground quando arriva la push, mostrare un in-app banner e navigare solo se l'utente lo tappa.

---

## 6. Riepilogo Rapido

| Evento | Dove | Quando |
|---|---|---|
| `upgrade_flow_started` | `initState()` della pagina registrazione | All'apertura del form |
| `upgrade_flow_abandoned` | `PopScope` + `didChangeAppLifecycleState` | Back press / app in background |
| `upgrade_flow_completed` | Callback successo API registrazione | Dopo `200` dall'API |

---

## 7. Cose che il FE **NON** deve fare

- ❌ Schedulare timer lato FE
- ❌ Inviare eventi al login (lo fa il BE su register-fcm-token)
- ❌ Bloccare il flusso se la chiamata `retention-event` fallisce (fire-and-forget)
- ❌ Gestire la logica di quale template/copia verrà inviata (è tutto BE)

---

## 8. Endpoint di Riferimento Completo

| Campo | Valore |
|---|---|
| Method | `POST` |
| Path | `/v1/users/{userId}/retention-event` |
| Auth | `Authorization: Bearer {CognitoIdToken}` |
| Body | `{ "event_type": "<tipo>" }` |
| Successo | `200 { "message": "ok" }` |
| Errore body | `400` se `event_type` non valido |
| Errore auth | `403` se `userId` non corrisponde al token |

---

## 9. Testing

Per verificare il flusso in ambiente `dev-be`:

1. Registra il token FCM (`POST /v1/users/{id}/fcm-token`) → dopo 3h arriverà T1
2. Apri il form registrazione → `upgrade_flow_started` → controlla che T1 venga rimandato di 3h nei CloudWatch logs di `dev-be-user-api-track-retention-event`
3. Chiudi il form → `upgrade_flow_abandoned` → controlla che `retention_state.template_override = "recovery"` in DynamoDB
4. Completa la registrazione → `upgrade_flow_completed` → controlla nei logs che i job scheduler vengano cancellati

---

*Per domande tecniche contattare il team BE.*
