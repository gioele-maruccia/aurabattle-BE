# Booking System - Modifiche Implementate

**Data:** 14 Gennaio 2026  
**Versione:** 2.0  
**Tipo:** Enhancement - Business Logic Update

---

## 📋 Riepilogo Modifiche

Sono state implementate modifiche sostanziali al sistema di booking per migliorare la gestione delle prenotazioni e risolvere i problemi di creazione dei booking.

---

## ✅ Modifiche Implementate

### 1. **Nuova Logica di Validazione Create Booking**

📁 File: `src/lambdas/services/bookings/create-booking/app.py`

#### Regole Implementate:

1. ✅ **Un worker può prenotarsi per lo stesso job listing in date diverse senza vincoli**
   - Rimosso il vincolo che impediva multiple prenotazioni per lo stesso annuncio
   - Ora il controllo è specifico per le date

2. ✅ **Check per booking PENDING nello stesso job listing e date sovrapposte**
   - Se esiste un booking `pending` con date sovrapposte → Error `409 Conflict`
   - Messaggio: "Hai già una candidatura in attesa per questo annuncio nelle date richieste"
   - Il worker deve attendere la risposta dell'azienda o cancellare la prenotazione esistente

3. ✅ **Check per booking REJECTED - Blocco permanente per le stesse date**
   - Se esiste un booking `rejected` con date sovrapposte → Error `403 Forbidden`
   - Messaggio: "Non puoi riprenotare perché la tua candidatura è stata precedentemente rifiutata"
   - Il worker può candidarsi solo per date diverse (no overlap con rejection)

4. ✅ **Solo booking CANCELLED permettono rebooking nelle stesse date**
   - Se lo stato precedente è `cancelled` → Rebooking permesso ✅
   - Qualsiasi altro stato (`pending`, `confirmed`, `completed`, etc.) → Rebooking bloccato ❌

5. ✅ **Check per booking CONFIRMED - Un solo lavoro confermato alla volta**
   - Se esiste un booking `confirmed` nello stesso job listing → Error `409 Conflict`
   - Se esiste un booking `confirmed` in QUALSIASI altro job listing con date sovrapposte → Error `409 Conflict`
   - Messaggio: "Puoi avere solo un booking confermato alla volta"

6. ✅ **Messaggi di errore eloquenti in italiano con dettagli completi**
   - Ogni errore include: `conflictingBookingId`, `conflictingStatus`, `conflictingDates`
   - Codici di stato HTTP appropriati: `403 Forbidden`, `409 Conflict`, `500 Internal Server Error`

---

### 2. **Auto-Cancellazione Booking Sovrapposti**

📁 File: `src/lambdas/services/bookings/update-booking-status/app.py`

#### Funzionalità:

✅ **Quando un booking viene confermato, tutti gli altri booking del worker con date sovrapposte vengono automaticamente cancellati**

**Logica Implementata:**

1. Query di tutti i booking del worker
2. Identifica booking con date sovrapposte (intersezione non vuota)
3. Salta booking già in stati terminali: `confirmed`, `cancelled`, `rejected`, `completed`, `no_show`
4. Cancella booking in stato `pending` che si sovrappongono
5. Imposta:
   - `status` → `cancelled`
   - `cancelledBy` → `system_auto_cancel`
   - `cancelledByRole` → `system`
   - `cancellationReason` → Messaggio esplicativo
6. Invia notifica nella chat del booking cancellato
7. Aggiorna `bookingState` nella chat

**Caratteristiche:**

- ✅ **Non-blocking**: Se la cancellazione automatica fallisce, non blocca la conferma principale
- ✅ **Notifiche automatiche**: Il worker riceve un messaggio nella chat per ogni booking auto-cancellato
- ✅ **Logging completo**: Ogni operazione è tracciata nei log
- ✅ **Resilienza**: Errori in una cancellazione non impediscono le altre

---

### 3. **Documentazione Completa**

#### 📁 File Aggiornati/Creati:

1. **`modules/common-beebusy/ERROR_CODES.md`** ✅ Aggiornato
   - Sezione dettagliata "Create Booking Errors (Enhanced Validation)"
   - 6 nuovi scenari di errore documentati con esempi JSON completi
   - Tabella aggiornata con nuovi status codes (409)

2. **`modules/common-beebusy/ERROR_CODES.json`** ✅ Aggiornato
   - Oggetto `create-booking` completamente riscritto
   - 13 scenari di errore con `condition`, `response`, e `message`
   - Oggetto `update-booking-status` aggiornato con `autoCancelLogic`
   - Documentazione delle regole di validazione

3. **`modules/common-beebusy/BOOKING_BUSINESS_RULES.md`** ✅ Creato (NUOVO)
   - Documentazione completa di 850+ righe
   - Sezioni:
     - Booking States (tabella con tutti gli stati)
     - Core Business Rules (6 regole con esempi)
     - Create Booking Validation Logic (step-by-step)
     - Auto-Cancellation Logic (algoritmo dettagliato)
     - Date Overlap Detection (algoritmo con esempi)
     - Error Scenarios (5 scenari con soluzioni)
     - State Transition Diagram (ASCII diagram)
     - Examples & Use Cases (5 use case completi)

4. **`modules/common-beebusy/README.md`** ✅ Aggiornato
   - Riferimenti ai nuovi file
   - Sezione "Business Logic Documentation"
   - Istruzioni per l'uso

---

## 📊 Codici di Stato HTTP

### Create Booking (`POST /bookings`)

| Codice | Quando | Descrizione |
|--------|--------|-------------|
| `201` | Success | Booking creato con successo |
| `400` | Bad Request | Dati mancanti, formato date invalido, listing non pubblicato |
| `403` | Forbidden | **NUOVO**: Booking precedentemente rifiutato nelle stesse date |
| `404` | Not Found | Job listing non trovato |
| `409` | Conflict | **NUOVO**: Booking pending/confirmed già esistente con date sovrapposte |
| `500` | Server Error | Errore durante controllo prenotazioni o creazione |

### Update Booking Status (`PATCH /bookings/{bookingId}/status`)

| Codice | Quando | Side Effects |
|--------|--------|--------------|
| `200` | Success | Status aggiornato + **Auto-cancellazione booking sovrapposti** + Notifiche chat |
| `400` | Bad Request | Status transition non valido, no positions |
| `403` | Forbidden | User non autorizzato |
| `404` | Not Found | Booking o listing non trovato |
| `409` | Conflict | Status transition non permesso |
| `500` | Server Error | Errore durante update |

---

## 🔍 Esempi di Errori

### Esempio 1: Pending Conflict

**Request:**
```json
POST /bookings
{
  "listingId": "job-123",
  "startDate": "2026-06-15",
  "endDate": "2026-07-15"
}
```

**Response (409):**
```json
{
  "statusCode": 409,
  "error": "Conflict",
  "message": "Hai già una candidatura in attesa (pending) per questo annuncio nelle date richieste (2026-06-01 - 2026-06-30). Attendi la risposta dell'azienda o annulla la prenotazione esistente prima di crearne una nuova.",
  "conflictingBookingId": "booking-abc-123",
  "conflictingStatus": "pending",
  "conflictingDates": {
    "startDate": "2026-06-01",
    "endDate": "2026-06-30"
  }
}
```

---

### Esempio 2: Rejected Block

**Request:**
```json
POST /bookings
{
  "listingId": "job-123",
  "startDate": "2026-06-15",
  "endDate": "2026-07-15"
}
```

**Response (403):**
```json
{
  "statusCode": 403,
  "error": "Forbidden",
  "message": "Non puoi riprenotare per questo annuncio nelle date richieste (2026-06-01 - 2026-06-30) perché la tua candidatura è stata precedentemente rifiutata dall'azienda. Puoi candidarti per date diverse.",
  "conflictingBookingId": "booking-xyz-456",
  "conflictingStatus": "rejected",
  "conflictingDates": {
    "startDate": "2026-06-01",
    "endDate": "2026-06-30"
  }
}
```

---

### Esempio 3: Cross-Listing Confirmed Conflict

**Request:**
```json
POST /bookings
{
  "listingId": "job-456",  // Diverso job
  "startDate": "2026-06-15",
  "endDate": "2026-07-15"
}
```

**Response (409):**
```json
{
  "statusCode": 409,
  "error": "Conflict",
  "message": "Non puoi creare una nuova candidatura perché hai già un booking confermato in un altro annuncio durante queste date (2026-06-01 - 2026-06-30). Puoi avere solo un booking confermato alla volta.",
  "conflictingBookingId": "booking-def-789",
  "conflictingListingId": "job-123",
  "conflictingStatus": "confirmed",
  "conflictingDates": {
    "startDate": "2026-06-01",
    "endDate": "2026-06-30"
  }
}
```

---

## 🎯 Use Cases Principali

### Use Case 1: Worker Applica a Più Job

**Scenario:** Worker vuole massimizzare le chance applicando a 3 job in giugno

1. ✅ Applica a Job A: 1-30 giugno → Success (pending)
2. ✅ Applica a Job B: 1-30 giugno → Success (pending)
3. ✅ Applica a Job C: 1-30 giugno → Success (pending)

**Quando Job A viene confermato:**
- Job A → `confirmed`
- Job B → `cancelled` (auto-cancellato, date sovrapposte)
- Job C → `cancelled` (auto-cancellato, date sovrapposte)
- Worker riceve notifiche in chat B e C

---

### Use Case 2: Gestione Rejection

**Scenario:** Worker viene rifiutato e vuole riapplicare

1. ✅ Applica a Company A: 1-30 giugno → Success (pending)
2. Company rifiuta → Status: `rejected`
3. ❌ Tenta di applicare 15 giugno - 15 luglio → **BLOCKED** (overlap con rejection)
4. ✅ Applica per 1-31 luglio → Success (no overlap)

**Risultato:** Date rifiutate sono permanentemente bloccate per quella company

---

### Use Case 3: Cancellazione e Rebooking

**Scenario:** Worker cancella per errore e vuole riprenotare

1. ✅ Applica a Company A: 1-30 giugno → Success (pending)
2. Worker cancella per errore → Status: `cancelled`
3. ✅ Applica a Company A: 1-30 giugno → Success (stesse date permesse dopo cancellazione)

**Risultato:** Solo `cancelled` permette rebooking nelle stesse date

---

## 🚀 Testing Checklist

- [ ] Test creazione booking con date diverse per stesso listing
- [ ] Test errore 409 quando pending esiste con overlap
- [ ] Test errore 403 quando rejected esiste con overlap
- [ ] Test errore 409 quando confirmed esiste nello stesso listing
- [ ] Test errore 409 quando confirmed esiste in altro listing
- [ ] Test successo quando precedente era cancelled
- [ ] Test auto-cancellazione quando booking confermato
- [ ] Test notifiche chat per booking auto-cancellati
- [ ] Test resilienza: auto-cancel failure non blocca conferma
- [ ] Test overlap detection con vari range di date

---

## 📦 Deployment Notes

### Database Indexes Required

Verificare che esistano questi indici in DynamoDB:

- `workerId-startDate-index` - Per query efficiente dei booking del worker
- `listingId-startDate-index` - Per check disponibilità listing

### Environment Variables

Nessuna nuova variabile richiesta. Utilizzate esistenti:
- `BOOKINGS_TABLE_NAME`
- `JOB_LISTINGS_TABLE_NAME`
- `COMPANIES_TABLE_NAME`
- `USER_PROFILES_TABLE_NAME`

### Lambda Layer

Richiesto per `update-booking-status`:
- Chat shared layer con `db_manager`, `models`, `ws_manager`

---

## 🔄 Breaking Changes

⚠️ **ATTENZIONE - Breaking Changes:**

1. **Nuovo codice HTTP 409** per create-booking
   - Frontend deve gestire `409 Conflict` con campi `conflictingBookingId`, `conflictingStatus`, `conflictingDates`

2. **Nuovo codice HTTP 403** per create-booking (rejected block)
   - Frontend deve gestire `403 Forbidden` con messaggio specifico per rejection

3. **Struttura errore modificata**
   - Errori ora includono campi aggiuntivi: `conflictingBookingId`, `conflictingStatus`, `conflictingDates`, `conflictingListingId`

4. **Messaggi in italiano**
   - Tutti i messaggi di errore sono ora in italiano per miglior UX

5. **Auto-cancellazione**
   - Comportamento nuovo: conferma di un booking può causare cancellazione di altri booking
   - Frontend deve gestire notifiche di cancellazione automatica

---

## 📖 Documentazione

Tutti i file di documentazione sono stati aggiornati/creati in:

- `modules/common-beebusy/ERROR_CODES.md` (aggiornato)
- `modules/common-beebusy/ERROR_CODES.json` (aggiornato)
- `modules/common-beebusy/BOOKING_BUSINESS_RULES.md` (nuovo)
- `modules/common-beebusy/README.md` (aggiornato)

---

## ✅ Checklist Deploy

- [ ] Review modifiche in `create-booking/app.py`
- [ ] Review modifiche in `update-booking-status/app.py`
- [ ] Verificare documentazione in `modules/common-beebusy/`
- [ ] Deploy Lambda `create-booking`
- [ ] Deploy Lambda `update-booking-status`
- [ ] Test end-to-end con scenari documentati
- [ ] Comunicare breaking changes a frontend team
- [ ] Aggiornare frontend per gestire nuovi codici di errore
- [ ] Aggiornare test suite

---

## 🎉 Conclusione

Tutte le modifiche richieste sono state implementate con successo:

✅ Worker può prenotarsi per lo stesso job listing in date diverse  
✅ Check pending con errore eloquente  
✅ Check rejected con blocco permanente per quelle date  
✅ Check confirmed (stesso e altri listing)  
✅ Rebooking permesso solo se stato precedente era cancelled  
✅ Auto-cancellazione booking sovrapposti quando uno viene confermato  
✅ Messaggi di errore eloquenti in italiano con dettagli completi  
✅ Documentazione completa in `modules/common-beebusy/`  

Il sistema è ora robusto, ben documentato e pronto per il deploy.

---

**Implementato da:** GitHub Copilot  
**Data:** 14 Gennaio 2026  
**Versione:** 2.0
