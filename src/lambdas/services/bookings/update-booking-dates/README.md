# Update Booking Dates Lambda

## Descrizione
Lambda che permette a un worker di modificare le date (inizio e fine) di un booking in stato PENDING.

## Funzionalità

### Permessi
- **Solo WORKER**: Solo l'utente worker che ha creato il booking può modificare le date
- **Solo PENDING**: La modifica è permessa solo per booking in stato `pending` (non ancora accettati dall'azienda)

### Validazioni
1. **Booking Status**: Il booking deve essere in stato `pending`
2. **Ownership**: Solo il worker proprietario del booking può modificarlo
3. **Date Range**: Le nuove date devono essere all'interno del periodo del job listing
4. **Disponibilità**: Verifica che ci siano posizioni disponibili nel nuovo range di date

### Azioni Automatiche
Quando le date vengono modificate con successo:

1. **Aggiorna Booking**: Modifica `startDate` e `endDate` nel database
2. **Aggiorna Chat**: Aggiorna i campi `startDate`, `endDate`, e `jobName` nella chat associata
3. **Invia Messaggio**: Crea un messaggio automatico nella chat con:
   - Tipo: `company_action` (richiede azione dall'azienda)
   - Contenuto: Notifica la richiesta di modifica date
   - Scopo: L'azienda deve accettare o rifiutare le nuove date

## Endpoint

### Request
```
PATCH /bookings/{bookingId}/dates
```

**Path Parameters:**
- `bookingId` (string, required): ID del booking da modificare

**Body (JSON):**
```json
{
  "startDate": "2024-03-01",
  "endDate": "2024-03-31"
}
```

**Headers:**
- `Authorization`: Bearer token JWT (Cognito)
- `Content-Type`: application/json

### Response

#### Success (200 OK)
```json
{
  "message": "Booking dates updated successfully",
  "booking": {
    "bookingId": "uuid",
    "listingId": "uuid",
    "workerId": "uuid",
    "companyId": "uuid",
    "startDate": "2024-03-01",
    "endDate": "2024-03-31",
    "status": "pending",
    "updatedAt": "2024-02-15T10:30:00Z",
    ...
  }
}
```

#### Errors

**400 Bad Request**
```json
{
  "error": "Bad Request",
  "message": "End date must be after start date"
}
```
O
```json
{
  "error": "Bad Request",
  "message": "Can only update dates of pending bookings. Current status: confirmed"
}
```
O
```json
{
  "error": "Bad Request",
  "message": "New dates must be within job listing period (2024-01-01 to 2024-12-31)"
}
```
O
```json
{
  "error": "Bad Request",
  "message": "No positions available in the new date range (5/5 positions taken)"
}
```

**403 Forbidden**
```json
{
  "error": "Forbidden",
  "message": "Only worker users can update booking dates"
}
```
O
```json
{
  "error": "Forbidden",
  "message": "You can only update your own bookings"
}
```

**404 Not Found**
```json
{
  "error": "Not Found",
  "message": "Booking not found"
}
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `BOOKINGS_TABLE_NAME` | Nome tabella DynamoDB bookings | `dev-Bookings` |
| `JOB_LISTINGS_TABLE_NAME` | Nome tabella DynamoDB job listings | `dev-JobListings` |
| `CHATS_TABLE_NAME` | Nome tabella DynamoDB chats | `dev-Chats` |
| `MESSAGES_TABLE_NAME` | Nome tabella DynamoDB messages | `dev-Messages` |

## Dependencies

### Layers
- **chat-shared**: Layer contenente i moduli condivisi per chat
  - `models.py`: Modelli Chat, Message, etc.
  - `db_manager.py`: Manager per operazioni DynamoDB
  - `ws_manager.py`: Manager per WebSocket

## Testing

### Test Case 1: Modifica date valida
```bash
curl -X PATCH https://api.example.com/bookings/{bookingId}/dates \
  -H "Authorization: Bearer {worker-token}" \
  -H "Content-Type: application/json" \
  -d '{
    "startDate": "2024-03-01",
    "endDate": "2024-03-31"
  }'
```

**Expected**: 200 OK con booking aggiornato

### Test Case 2: Worker non autorizzato
```bash
curl -X PATCH https://api.example.com/bookings/{other-worker-booking}/dates \
  -H "Authorization: Bearer {worker-token}" \
  -H "Content-Type: application/json" \
  -d '{
    "startDate": "2024-03-01",
    "endDate": "2024-03-31"
  }'
```

**Expected**: 403 Forbidden

### Test Case 3: Booking già confermato
Tentare di modificare un booking con status `confirmed`.

**Expected**: 400 Bad Request - "Can only update dates of pending bookings"

### Test Case 4: Date fuori range job listing
```bash
curl -X PATCH https://api.example.com/bookings/{bookingId}/dates \
  -H "Authorization: Bearer {worker-token}" \
  -H "Content-Type: application/json" \
  -d '{
    "startDate": "2025-01-01",
    "endDate": "2025-12-31"
  }'
```

**Expected**: 400 Bad Request - "New dates must be within job listing period"

### Test Case 5: Posizioni non disponibili
Tentare di modificare in un periodo dove tutte le posizioni sono già occupate.

**Expected**: 400 Bad Request - "No positions available in the new date range"

## Integration Flow

```
1. Worker richiede modifica date
   ↓
2. Lambda valida: status=pending, ownership, date range, disponibilità
   ↓
3. Aggiorna booking in DynamoDB
   ↓
4. Recupera chat associata al booking
   ↓
5. Aggiorna chat con nuove date (startDate, endDate, jobName)
   ↓
6. Crea messaggio automatico tipo "company_action" nella chat
   ↓
7. Invia messaggio via WebSocket (best effort)
   ↓
8. Response 200 OK al worker
```

## Notes

- La validazione delle posizioni disponibili è semplificata (conta booking overlapping)
- Una implementazione completa dovrebbe verificare disponibilità giorno per giorno
- L'aggiornamento della chat è non-blocking: se fallisce, il booking viene comunque aggiornato
- Il messaggio WebSocket è best-effort: se fallisce, viene solo loggato l'errore
- Le date devono essere in formato ISO 8601 (YYYY-MM-DD o YYYY-MM-DDTHH:MM:SSZ)

## Related Endpoints

- `POST /bookings` - Crea nuovo booking (e chat associata)
- `PATCH /bookings/{bookingId}/status` - Company accetta/rifiuta booking
- `GET /chats/{chatId}` - Recupera chat con date aggiornate
- `GET /chats/{chatId}/messages` - Visualizza messaggio di richiesta modifica

## Changelog

### v1.0.0 (2024-01-10)
- Implementazione iniziale
- Validazioni: status, ownership, date range, disponibilità
- Integrazione con sistema chat
- Messaggio automatico tipo "company_action"
