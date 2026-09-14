# Pulizia Documenti Dopo Upload Rifiutato

## Descrizione

Quando un utente ricarica i documenti dopo che la verifica del profilo è stata rifiutata dal backoffice, il sistema rimuove automaticamente i vecchi documenti non richiesti per il tipo di utente.

Questo assicura che:
- Un **worker** abbia sempre e solo: carta identità fronte, carta identità retro e selfie
- Una **company** abbia sempre e solo: visura catastale, carta identità fronte, carta identità retro e selfie

## Flusso

### 1. Upload Iniziale (Rifiutato)
```
User → Upload documenti → Backoffice verifica → Rifiuta
```

### 2. Re-Upload (Automatica Pulizia)
```
User → Ricarica documento
       ↓
       Presign URL Lambda:
       1. Recupera tipo utente (worker/company)
       2. Cancella TUTTI i documenti vecchi
       3. Mantiene solo i tipi richiesti
       4. Genera URL presigned per nuovo upload
```

## Implementazione

### File Modificato
- [presign-url/app.py](../../../src/lambdas/services/profile-upgrade-documents/presign-url/app.py)

### Funzioni Aggiunte

#### `_get_user_profile_type(user_sub: str) -> str | None`
Recupera il tipo di profilo dell'utente dal database UserProfiles.
- Ritorna: `'worker'` o `'company'`
- Ritorna `None` se l'utente non esiste

#### `_cleanup_old_documents(user_sub: str, user_type: str, keep_doc_types: list)`
Elimina tutti i documenti eccetto quelli nella lista di mantenimento.
- Elimina i file S3
- Elimina i record DynamoDB
- Log di ogni eliminazione
- Continua anche se un'eliminazione fallisce

#### `_cleanup_documents_on_rejected_upload(user_sub: str)`
Orchestrale la pulizia in base al tipo di utente:
- **Worker**: mantiene `['id_card_front', 'id_card_back', 'selfie']`
- **Company**: mantiene `['visura', 'id_card_front', 'id_card_back', 'selfie']`

### Chiamata nel Flusso
La pulizia viene invocata nella `lambda_handler` dopo la validazione dei parametri:

```python
# =====================================================================
# CLEANUP: When user uploads new documents, remove old ones
# This ensures only required documents remain after re-upload
# =====================================================================
logger.info(f"Triggering document cleanup for user {user_sub} on new upload")
_cleanup_documents_on_rejected_upload(user_sub)
```

## Gestione Errori

- Se la pulizia fallisce, il processo di upload continua normalmente
- Gli errori di pulizia vengono loggati ma non bloccano l'upload
- Se non si riesce a determinare il tipo di utente, nessuna pulizia avviene (log warning)

## Logging

Tutti gli step vengono loggati su CloudWatch:

```
INFO: User 12345 type: worker
INFO: Found 6 documents for user 12345
INFO: Deleted S3 object: docs/12345/1640995200000_passport.pdf
INFO: Deleted DynamoDB item: DOC#passport#1640995200000
INFO: Deleted S3 object: docs/12345/1640995200001_drivers_license.png
INFO: Deleted DynamoDB item: DOC#drivers_license#1640995200001
INFO: Cleanup completed: deleted 2 old documents for worker user 12345
```

## Documenti Richiesti per Tipo Utente

### Worker
```
- id_card_front (Carta Identità Fronte)
- id_card_back (Carta Identità Retro)
- selfie (Selfie)
```

### Company
```
- visura (Visura Catastale)
- id_card_front (Carta Identità Fronte)
- id_card_back (Carta Identità Retro)
- selfie (Selfie)
```

## Documenti Facoltativi (Rimossi)
- `passport` (Passaporto) - Alternativa a carta d'identità
- `drivers_license` (Patente) - Alternativa a carta d'identità

## Considerazioni di Sicurezza

- L'operazione è basata su `user_sub` dal JWT (non manipolabile dal client)
- Solo i documenti dell'utente autenticato vengono elaborati
- S3 è protetto da KMS encryption
- DynamoDB ha TTL di 30 giorni per i documenti pendenti

## Test

Per testare il comportamento:

1. Login come worker
2. Upload documenti (es: id_card_front, passport, selfie)
3. Backoffice rifiuta la verifica
4. Login nuovamente con lo stesso user
5. Upload nuovo documento (es: id_card_back)
6. Verificare in CloudWatch che `passport` sia stato eliminato
7. Verificare nel database che rimangono solo: id_card_front, id_card_back, selfie
