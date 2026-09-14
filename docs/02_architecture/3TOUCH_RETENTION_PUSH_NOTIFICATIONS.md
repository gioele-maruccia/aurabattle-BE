# Analisi: Sistema "3-Touch Validation" — Push Notifications di Retention

**Data:** Aprile 2026  
**Autore:** Analisi tecnica BE/FE  
**Scope:** Notifiche Firebase di retention basate su eventi, in parallelo al sistema email già esistente

---

## 1. Obiettivo e Differenze vs Sistema Email

Il sistema email di reminder esistente usa un **cron settimanale** che scansiona tutti gli utenti e invia in base a una cadenza esponenziale (Giorno 1 → 3 → 7 → 14 → 30 → 60 → 90) anchorata alla data di creazione/upgrade.

Il sistema **3-Touch Push** è fondamentalmente diverso:

| Caratteristica | Email Cron | Push 3-Touch |
|---|---|---|
| Trigger | Cron EventBridge (settimanale) | Evento esplicito dal FE |
| Timer | Relativo alla data account | Relativo all'ultimo evento utente |
| Countdown | Giorni | Ore (3h → +24h → +72h) |
| Cancellazione | Esaurimento contatore (7 step) | Kill-switch su `upgrade_flow_completed` |
| Personalizzazione | Template fisso per tipo | Template cambia in base agli eventi ricevuti |
| Persistenza scheduler | DynamoDB counter | Job schedulato con ID univoco |

---

## 2. Architettura del Sistema

### 2.1 Schema dei Componenti

```
┌─────────────────────────────────────────────────────────────────┐
│                         FLUTTER APP (FE)                        │
│                                                                  │
│  • Invia evento: upgrade_flow_started / abandoned / completed   │
│  • Riceve push e naviga a pagina registrazione azienda           │
│  • Registra fcm_token in UserProfiles                           │
└───────────────────────────┬─────────────────────────────────────┘
                             │  POST /users/{userId}/retention-event
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              LAMBDA: track-retention-event (nuovo)              │
│                                                                  │
│  1. Riceve l'evento dal FE                                       │
│  2. Aggiorna DynamoDB UserProfiles                               │
│     retention_state.{event_type} = timestamp + stato            │
│  3. Manipola la Job Queue:                                       │
│     - upgrade_flow_started  → Rimanda T1 di +3h                 │
│     - upgrade_flow_abandoned → Cambia template T1 a "recovery"  │
│     - upgrade_flow_completed → KILL SWITCH: cancella T1/T2/T3   │
│  4. Se primo evento (login/account creation):                    │
│     → Schedula EventBridge Scheduler job T1 (+3h)               │
└───────────────────────────┬─────────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
┌─────────────────────┐       ┌─────────────────────────────────┐
│  AWS EventBridge    │       │  DynamoDB: prod-UserProfiles     │
│  Scheduler          │       │                                  │
│                     │       │  retention_state: {              │
│  Job: task_upgrade_ │       │    status: "interested"|"active" │
│  reminder_{userId}  │       │    template_override: "recovery" │
│  (one-time, per     │       │    t1_scheduled_at: ISO          │
│   utente)           │       │    t2_scheduled_at: ISO (opt)    │
│                     │       │    t3_scheduled_at: ISO (opt)    │
│  T1 → fire → Lambda │       │    completed: false              │
│  T2 → fire → Lambda │       │  }                              │
│  T3 → fire → Lambda │       └─────────────────────────────────┘
└─────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────┐
│         LAMBDA: send-retention-push (nuovo)                     │
│                                                                  │
│  Invocata da EventBridge Scheduler per T1, T2, T3               │
│  1. Legge retention_state dal profilo utente                    │
│  2. Verifica: completed = FALSE (kill switch)                   │
│  3. Verifica: orario di silenzio (22:00-08:00 fuso utente)      │
│     → Se in silenzio: reschedula alle 09:00 del mattino         │
│  4. Determina template: default o "recovery"                    │
│  5. Invia push Firebase con actionType: "upgrade_reminder"      │
│  6. Schedula il prossimo step (T2 o T3)                         │
│  7. Aggiorna retention_state (step inviato)                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Definizione degli Eventi FE → BE

### 3.1 Evento di Ingresso: Login / Creazione Account

Questo non richiede un evento esplicito: il BE lo gestisce in modo autonomo.

**Dove intercettare:**
- **Post-Confirmation Lambda** (Cognito trigger) → già esiste nel progetto
- **Oppure:** nella Lambda `register-fcm-token` quando l'utente si autentica la prima volta e invia il token FCM

**Logica:** Se `profile_type == "basic"` e `Azienda_Registrata == FALSE` (cioè non c'è record in `prod-Companies`), schedula T1 a `now + 3h`.

> ℹ️ `Azienda_Registrata = FALSE` si traduce in: `profile_type` è `"basic"` (non ancora `"company"`).

---

### 3.2 Endpoint BE per Ricezione degli Eventi FE

**Proposta:** Un unico endpoint REST polimorfco.

```
POST /users/{userId}/retention-event
Authorization: Bearer {CognitoJWT}

Body:
{
  "event_type": "upgrade_flow_started" | "upgrade_flow_abandoned" | "upgrade_flow_completed",
  "timestamp": "2026-04-13T10:30:00Z"   // ISO8601, opzionale (BE usa il suo)
}
```

**Alternative valutate:**

| Approccio | Pro | Contro |
|---|---|---|
| Endpoint REST dedicato (consigliato) | Semplice, testabile, traccibile | +1 endpoint |
| Aggiornare endpoint esistente `/users/{id}/profile` | Riusa infra | Accoppia logica eterogenea |
| WebSocket (canale già esistente) | Real-time bidirezionale | Complesso, WS non persiste |

---

### 3.3 Mapping Evento → Azione BE

| Evento Ricevuto | Azione BE | Effetto su Push |
|---|---|---|
| `upgrade_flow_started` | Postpone job T1 di +3h dalla ricezione | Non interrompe il flusso, evita push durante compilazione |
| `upgrade_flow_abandoned` | Imposta `template_override = "recovery"` su retention_state | T1 (quando sparato) usa template "Supporto/Recupero" invece di "Educational" |
| `upgrade_flow_completed` | **KILL SWITCH**: cancella job T1, T2, T3 da EventBridge Scheduler + imposta `completed = true` | Non vengono mai più inviati push |

---

## 4. Schema DynamoDB: Campo `retention_state`

### 4.1 Dove Salvare

In **`prod-UserProfiles`**, aggiungiamo un nuovo campo `retention_state` (Map) accanto all'esistente `email_reminders`.

```json
{
  "user_id": "cognito-sub-uuid",
  "email": "user@example.com",
  "profile_type": "basic",
  "fcm_token": "fcm-token-string",
  "email_reminders": { ... },
  
  "retention_state": {
    "push_enabled": true,
    "completed": false,
    "template_override": null,
    "current_step": "T1",
    "t1_job_id": "task_upgrade_reminder_abc123_T1",
    "t2_job_id": null,
    "t3_job_id": null,
    "t1_scheduled_at": "2026-04-13T13:30:00Z",
    "t2_scheduled_at": null,
    "t3_scheduled_at": null,
    "t1_sent_at": null,
    "t2_sent_at": null,
    "t3_sent_at": null,
    "last_event": "upgrade_flow_started",
    "last_event_at": "2026-04-13T10:30:00Z"
  }
}
```

### 4.2 Dettaglio Campi

| Campo | Tipo | Descrizione |
|---|---|---|
| `push_enabled` | Boolean | Rispetta le `notification_preferences` dell'utente |
| `completed` | Boolean | KILL SWITCH: true = non inviare più push |
| `template_override` | String\|null | `"recovery"` se l'utente ha abbandonato il flusso |
| `current_step` | String\|null | `"T1"`, `"T2"`, `"T3"`, `"done"` |
| `t{n}_job_id` | String\|null | ID univoco del job EventBridge Scheduler (usato per cancellarlo) |
| `t{n}_scheduled_at` | ISO String\|null | Quando è schedulato il job |
| `t{n}_sent_at` | ISO String\|null | Quando è stata inviata la push (audit) |
| `last_event` | String\|null | Ultimo evento ricevuto dal FE |
| `last_event_at` | ISO String\|null | Timestamp ultimo evento |

---

## 5. Workflow delle Notifiche

### 5.1 Scheduling: AWS EventBridge Scheduler (NON cron)

Per supportare la cancellazione tramite ID univoco, il sistema email basato su cron settimanale **non è adatto**. Serve **AWS EventBridge Scheduler** con schedule **one-time** per ogni job.

**Job ID convention:**
```
task_upgrade_reminder_{userId}_T1
task_upgrade_reminder_{userId}_T2
task_upgrade_reminder_{userId}_T3
```

Questo permette al BE di chiamare `scheduler.delete_schedule(Name=job_id)` al KILL SWITCH.

### 5.2 Timing e Condizioni

| Step | Timing | Condizione | Template |
|---|---|---|---|
| **T1** | +3h dall'inattività (default) | `completed == False` | `default` o `recovery` se `template_override == "recovery"` |
| **T2** | +24h da invio T1 | `completed == False` | `benefit_fomo` |  
| **T3** | +72h da invio T2 | `completed == False` | `feedback_validation` |

**Regola Silenzio:** 22:00–08:00 fuso orario utente (`localization.timezone` in UserProfiles, default `"Europe/Rome"`).  
Se il job scade in questo intervallo → reschedula a `oggi 09:00` oppure `domani 09:00`.

---

## 6. Contenuti delle Notifiche (Copy Italiano)

### T1 — Template `default` (Educational/Assistenza)

```json
{
  "notification": {
    "title": "Serve aiuto con i dati aziendali?",
    "body": "Registra la tua azienda su BeeBusy e inizia a trovare personale qualificato."
  },
  "data": {
    "actionType": "upgrade_reminder",
    "step": "T1",
    "variant": "default"
  }
}
```

**Variante:** *(alternare random o A/B)*
```json
{
  "notification": {
    "title": "Sapevi che puoi fare X con l'azienda?",
    "body": "Registra la tua azienda e accedi a lavoratori verificati nella tua zona."
  }
}
```

---

### T1 — Template `recovery` (Supporto/Recupero — post `upgrade_flow_abandoned`)

```json
{
  "notification": {
    "title": "Hai bisogno di aiuto per completare la registrazione?",
    "body": "Siamo qui per supportarti. Riprendi da dove hai lasciato."
  },
  "data": {
    "actionType": "upgrade_reminder",
    "step": "T1",
    "variant": "recovery"
  }
}
```

---

### T2 — Template `benefit_fomo` (+24h da T1)

```json
{
  "notification": {
    "title": "Registrati ora per sbloccare i report avanzati",
    "body": "È il modo più veloce per trovare il personale giusto. Non aspettare."
  },
  "data": {
    "actionType": "upgrade_reminder",
    "step": "T2",
    "variant": "benefit_fomo"
  }
}
```

---

### T3 — Template `feedback_validation` (+72h da T2)

```json
{
  "notification": {
    "title": "Cosa manca nell'app per la tua azienda?",
    "body": "Dicci la tua, ci aiuta a crescere."
  },
  "data": {
    "actionType": "upgrade_reminder",
    "step": "T3",
    "variant": "feedback_validation"
  }
}
```

---

## 7. Deep Linking (Payload Navigation)

Nel campo `data` della push va aggiunto il payload per reindirizzare l'utente alla pagina di registrazione azienda. L'`actionType: "upgrade_reminder"` è già documentato in `modules/common-beebusy/common-docs/PUSH_NOTIFICATIONS_SYSTEM.md` e già gestito dal FE.

**Nessun campo aggiuntivo necessario** per il routing: il FE usa `actionType == "upgrade_reminder"` per navigare alla pagina corretta.

Se si vuole passare info aggiuntiva per il deep-link (es. step form di arrivo):

```json
"data": {
  "actionType": "upgrade_reminder",
  "step": "T1",
  "variant": "recovery",
  "deepLinkTarget": "company_registration"
}
```

---

## 8. Implementazione BE: File da Creare / Modificare

### 8.1 Nuova Lambda: `track-retention-event`

**Path:** `src/lambdas/services/user-api/track-retention-event/app.py`

```python
"""
POST /users/{userId}/retention-event

Riceve eventi dal FE relativi al flusso di upgrade:
- upgrade_flow_started   → Rimanda T1 di +3h
- upgrade_flow_abandoned → Cambia template T1 a "recovery"
- upgrade_flow_completed → KILL SWITCH (cancella tutti i job scheduler)
"""
```

**Logica core:**
```python
def handle_event(user_id, event_type, retention_state):
    if event_type == "upgrade_flow_completed":
        # KILL SWITCH
        for step in ["T1", "T2", "T3"]:
            job_id = retention_state.get(f"{step.lower()}_job_id")
            if job_id:
                cancel_scheduler_job(job_id)
        update_retention_state(user_id, {"completed": True, "current_step": "done"})

    elif event_type == "upgrade_flow_abandoned":
        update_retention_state(user_id, {
            "template_override": "recovery",
            "last_event": event_type,
            "last_event_at": now_iso()
        })

    elif event_type == "upgrade_flow_started":
        # Rimanda T1 di +3h dal momento corrente
        new_time = now() + timedelta(hours=3)
        new_time = apply_silence_window(new_time, user_timezone)
        reschedule_job(retention_state["t1_job_id"], new_time)
        update_retention_state(user_id, {
            "t1_scheduled_at": new_time.isoformat(),
            "last_event": event_type,
            "last_event_at": now_iso()
        })
```

---

### 8.2 Nuova Lambda: `send-retention-push`

**Path:** `src/lambdas/services/firebase-notifications/send-retention-push/app.py`

**Trigger:** EventBridge Scheduler (one-time per ogni step T1/T2/T3)

**Event payload da Scheduler:**
```json
{
  "user_id": "cognito-sub-uuid",
  "step": "T1"
}
```

**Logica core:**
```python
def lambda_handler(event, context):
    user_id = event["user_id"]
    step = event["step"]  # "T1", "T2", "T3"
    
    # 1. Leggi profilo
    user = get_user_profile(user_id)
    retention = user.get("retention_state", {})
    
    # 2. Kill switch check
    if retention.get("completed"):
        return  # User completato il flow, non inviare
    
    # 3. Check push preferences
    if not user.get("notification_preferences", {}).get("push_enabled", True):
        return
    
    # 4. Check fcm_token presente
    fcm_token = user.get("fcm_token")
    if not fcm_token:
        return  # Non registrato alle push
    
    # 5. Determina template
    variant = determine_template_variant(step, retention)
    title, body = get_push_copy(step, variant)
    
    # 6. Invia push
    success = send_notification(
        fcm_token=fcm_token,
        title=title,
        body=body,
        data={
            "actionType": "upgrade_reminder",
            "step": step,
            "variant": variant
        }
    )
    
    # 7. Aggiorna retention_state e schedula prossimo step
    if success:
        mark_step_sent(user_id, step)
        schedule_next_step(user_id, step, retention)
```

---

### 8.3 Helper: Silence Window + Timezone

```python
from datetime import datetime, timedelta
import pytz

SILENCE_START = 22  # 22:00
SILENCE_END = 8     # 08:00

def apply_silence_window(dt: datetime, timezone_str: str) -> datetime:
    """Sposta dt alle 09:00 se cade in fascia di silenzio."""
    tz = pytz.timezone(timezone_str or "Europe/Rome")
    dt_local = dt.astimezone(tz)
    
    hour = dt_local.hour
    if hour >= SILENCE_START or hour < SILENCE_END:
        # Sposta a 09:00 del mattino successivo (o stesso giorno se < 08:00)
        if hour >= SILENCE_START:
            next_day = dt_local.date() + timedelta(days=1)
        else:
            next_day = dt_local.date()
        
        target = tz.localize(datetime(next_day.year, next_day.month, next_day.day, 9, 0, 0))
        return target.astimezone(pytz.utc)
    
    return dt
```

---

### 8.4 Modifiche a Lambda Esistente: `register-fcm-token`

**File:** `src/lambdas/services/user-api/register-fcm-token/app.py`

Quando viene registrato un token FCM **per la prima volta** (o quando `retention_state` è assente):
- Se `profile_type == "basic"` → schedula job T1 a `now + 3h`
- Inizializza `retention_state` in DynamoDB

```python
# Aggiunta al handler esistente dopo la scrittura del token:
if not existing_fcm_token and profile_type == "basic":
    schedule_retention_t1(user_id, user_profile)
```

> ℹ️ **Alternativa:** gestire in Post-Confirmation Lambda Cognito (già esistente), ma lì non c'è ancora il fcm_token. Meglio su `register-fcm-token`.

---

### 8.5 Infra SAM: Nuovo Template `firebase-notifications/template.yaml`

```yaml
Resources:

  # EventBridge Scheduler Role
  SchedulerExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Statement:
          - Effect: Allow
            Principal:
              Service: scheduler.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: InvokeSendRetentionPush
          PolicyDocument:
            Statement:
              - Effect: Allow
                Action: lambda:InvokeFunction
                Resource: !GetAtt SendRetentionPushFunction.Arn

  SendRetentionPushFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub '${Environment}-firebase-send-retention-push'
      CodeUri: ../../../src/lambdas/services/firebase-notifications/send-retention-push/
      Handler: app.lambda_handler
      Layers:
        - !Ref FirebaseAdminLayerArn
      Environment:
        Variables:
          USER_PROFILES_TABLE: !Ref UserProfilesTableName
          SCHEDULER_ROLE_ARN: !GetAtt SchedulerExecutionRole.Arn
          FIREBASE_SERVICE_ACCOUNT_PATH: /opt/python/beebusy-99d60-firebase-adminsdk-fbsvc-b37bca6781.json
      Policies:
        - DynamoDBReadPolicy:
            TableName: !Ref UserProfilesTableName
        - Statement:
            - Effect: Allow
              Action:
                - dynamodb:UpdateItem
                - dynamodb:GetItem
              Resource: !Sub 'arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${UserProfilesTableName}'
            - Effect: Allow
              Action:
                - scheduler:CreateSchedule
                - scheduler:DeleteSchedule
                - scheduler:UpdateSchedule
              Resource: '*'
            - Effect: Allow
              Action: iam:PassRole
              Resource: !GetAtt SchedulerExecutionRole.Arn

  TrackRetentionEventFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub '${Environment}-firebase-track-retention-event'
      CodeUri: ../../../src/lambdas/services/user-api/track-retention-event/
      Handler: app.lambda_handler
      Events:
        Api:
          Type: Api
          Properties:
            RestApiId: !Ref UserApiId
            Path: /users/{userId}/retention-event
            Method: POST
            Auth:
              Authorizer: CognitoAuthorizer
```

---

## 9. Implementazione FE (Flutter)

### 9.1 Quando Inviare gli Eventi

Il FE deve inviare eventi nelle seguenti situazioni:

| Evento | Quando | Metodo Consigliato |
|---|---|---|
| **Attivazione Workflow** | Al login se `Azienda_Registrata == false` — gestito dal BE su `register-fcm-token` | Nessun evento FE necessario |
| `upgrade_flow_started` | L'utente apre la schermata/form di registrazione azienda | In `initState()` della pagina di registrazione |
| `upgrade_flow_abandoned` | L'utente chiude il form senza completare (backpress, app in background > 30 min, kill app) | `WillPopScope` + `AppLifecycleListener` |
| `upgrade_flow_completed` | Il form è stato inviato con successo (risposta 200 dall'API) | Nel blocco `then()` della chiamata API |

### 9.2 Gestione "Inattività > 30 min"

Come da specifica, il timer T1 si avvia quando l'utente smette di inviare eventi. La gestione ottimale:

```dart
// In AppLifecycleObserver o equivalente
class RetentionEventService {
  static const _inactivityThreshold = Duration(minutes: 30);
  Timer? _inactivityTimer;

  void onUserActivity() {
    _inactivityTimer?.cancel();
    _inactivityTimer = Timer(_inactivityThreshold, _onInactive);
  }

  void _onInactive() {
    // L'utente è inattivo: il BE gestirà il countdown da solo
    // Invia "app_backgrounded" se necessario
  }

  void onAppKilled() {
    // AppLifecycleState.detached
    // Invia upgrade_flow_abandoned se l'utente era nel form
    _sendRetentionEvent("upgrade_flow_abandoned");
  }
}
```

> **Nota:** Il documento di specifica suggerisce che il FE possa inviare un evento alla chiusura dell'app (kill o background). Questo è gestibile con `AppLifecycleListener.onDetach` (Flutter 3.13+) o con `WorkManager` per task in background su Android.

### 9.3 Chiamata API

```dart
class RetentionEventApi {
  static Future<void> trackEvent({
    required String userId,
    required String eventType,  // "upgrade_flow_started" | "abandoned" | "completed"
  }) async {
    try {
      await apiClient.post(
        '/users/$userId/retention-event',
        body: {
          'event_type': eventType,
          'timestamp': DateTime.now().toUtc().toIso8601String(),
        },
        headers: {'Authorization': 'Bearer ${await getIdToken()}'},
      );
    } catch (e) {
      // Fire-and-forget: non bloccare il flusso utente per un errore di tracking
      debugPrint('Retention event tracking failed: $e');
    }
  }
}
```

### 9.4 Ricezione Push e Navigation

La push già usa `actionType: "upgrade_reminder"`, già documentato e (presumibilmente) già gestito dal FE nella notification handler. 

Se non ancora implementato il deep link per questo tipo:

```dart
void handlePushNotification(RemoteMessage message) {
  final actionType = message.data['actionType'];
  
  switch (actionType) {
    case 'upgrade_reminder':
      Navigator.pushNamed(context, '/company-registration');
      break;
    // ... altri casi già esistenti
  }
}
```

---

## 10. Flusso Completo End-to-End

```
[FE] Utente fa login, basic user
         │
         ▼
[BE] register-fcm-token → profile_type == "basic"?
         │ Sì
         ▼
[BE] EventBridge Scheduler: crea job "task_upgrade_reminder_{id}_T1"
     scheduled_at = now + 3h (con silent window check)
     Scrive retention_state in DynamoDB
         │
         │ [FE] Utente apre form registrazione azienda
         ▼
[BE] POST /retention-event: "upgrade_flow_started"
     → Rimanda T1: scheduled_at = now + 3h (aggiorna job Scheduler)
         │
         │ [FE] Utente chiude app / abbandona form
         ▼
[BE] POST /retention-event: "upgrade_flow_abandoned"
     → template_override = "recovery" in DynamoDB
         │
         │ [Scheduler] T1 scatta
         ▼
[BE] send-retention-push invocata
     → Check completed = false ✓
     → Check fcm_token presente ✓
     → Check silent window ✓
     → template = "recovery" (perché abandoned)
     → Invia push FCM
     → Schedula T2 (now + 24h, con silent window)
         │
         │ [FE] Utente clicca su push, apre app
         ▼
[FE] navigate to /company-registration (deep link da actionType)
         │
         │ [FE] Utente completa registrazione
         ▼
[BE] POST /retention-event: "upgrade_flow_completed"
     → KILL SWITCH: cancella job T2, T3 da Scheduler
     → completed = true in DynamoDB
     ✓ Nessuna altra push verrà inviata
```

---

## 11. Casi Edge da Gestire

| Scenario | Gestione |
|---|---|
| Utente senza `fcm_token` | Skip silenzioso — nessuna push, retention_state salvato comunque |
| `notification_preferences.push_enabled = false` | Skip silenzioso |
| Utente completa upgrade prima di T1 | `profile_type` diventa "company" → KILL SWITCH automatico anche nel flusso esistente |
| Job T1 scade ma T2/T3 non schedulati (lambda crash) | Il campo `current_step` in DynamoDB permette recovery manuale o re-schedule con un cron di cleanup |
| Token FCM scaduto/invalido (`UnregisteredError`) | Catch eccezione, logga, rimuovi `fcm_token` da DynamoDB per evitare retry inutili |
| Utente esegue upgrade ma non ha mai mandato `upgrade_flow_completed` | La Lambda `backoffice-update-document-status` (che già esiste) imposta il profilo su "company" → aggiungere qui il KILL SWITCH push |
| Doppio login su due dispositivi | Il `fcm_token` viene sovrascPititto dall'ultimo device che registra → normale, FCM invia solo all'ultimo device registrato |
| Reinstallazione app | Nuovo `fcm_token` → `register-fcm-token` update senza ri-schedulare T1 se `retention_state` già esiste |

---

## 12. Monitoring e KPI

### 12.1 CloudWatch Metrics da Tracciare

```
retention_push_t1_sent        (counter per step)
retention_push_t2_sent
retention_push_t3_sent
retention_push_skipped_completed    (kill switch attivo)
retention_push_skipped_no_token     (nessun FCM token)
retention_push_skipped_silent_rescheduled
retention_event_received_{event_type}
```

### 12.2 KPI di Business (come da specifica)

1. **Click-Through Rate (CTR):** % utenti che aprono la push T1/T2/T3
   - Tracciabile via `upgrade_flow_started` ricevuto entro X minuti dalla push
   
2. **Conversion Rate post-click:** % utenti che completano la registrazione dopo aver cliccato
   - `upgrade_flow_completed` ricevuto dopo T1/T2/T3

3. **Abbandono Critico:** volume di `upgrade_flow_abandoned` post-T1 → segnale che il form è troppo complesso

---

## 13. Ordine di Sviluppo Suggerito

### Fase 1 — Infrastruttura Base
1. Aggiungere campo `retention_state` al modello DynamoDB UserProfiles
2. Creare Lambda `send-retention-push` con logica di send + silence window
3. Creare Lambda `track-retention-event` con logica KILL SWITCH
4. Aggiornare template SAM `firebase-notifications`
5. Aggiungere IAM permissions per EventBridge Scheduler

### Fase 2 — Trigger Iniziale
6. Modificare `register-fcm-token` per inizializzare `retention_state` e schedulare T1
7. Test end-to-end in ambiente dev-be

### Fase 3 — FE
8. Implementare `RetentionEventApi.trackEvent()`
9. Integrare chiamata `upgrade_flow_started` nella pagina form registrazione
10. Integrare chiamata `upgrade_flow_abandoned` su backpress/lifecycle
11. Integrare chiamata `upgrade_flow_completed` dopo successo API
12. Verificare deep link su `actionType: "upgrade_reminder"`

### Fase 4 — KILL SWITCH Automatico
13. Modificare `backoffice-update-document-status` per cancellare i job push quando approva l'upgrade (profile_type = "company")

### Fase 5 — Monitoring
14. Aggiungere CloudWatch metrics custom
15. Dashboard Grafana/CloudWatch con KPI business

---

## 14. Note Architetturali Importanti

### Perché EventBridge Scheduler e non SQS con Delay

- **SQS delay max = 15 minuti** → insufficiente per T1 (3h), T2 (27h totali), T3 (99h totali)
- **EventBridge Scheduler** supporta one-time schedule a qualsiasi ora, con cancellazione tramite nome univoco ✓

### Perché non usare il Cron esistente (email-style)

Il sistema email cron scansiona **tutti gli utenti ogni settimana**. Per il 3-Touch push:
- La granularità è oraria (3h) → un cron settimanale non funziona
- La cancellazione tramite kill-switch richiede job individuali

### Compatibilità con Email Reminders

I due sistemi operano in parallelo e **non si sovrappongono**:
- Email cron: cadenza esponenziale in giorni, anchorata alla creazione account
- Push 3-Touch: T1→T2→T3 in ore/giorni, anchorata all'inattività, cancellabile da eventi FE

Non è necessario disabilitare le email quando le push sono attive (diversi canali, complementari).
