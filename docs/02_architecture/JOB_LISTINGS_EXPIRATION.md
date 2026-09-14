# Job Listings Expiration System

Sistema automatico per la scadenza dei job listings basato su AWS EventBridge e Lambda.

## 📋 Overview

Il sistema controlla quotidianamente tutti i job listings e gestisce la loro scadenza considerando la presenza di booking attivi:

- **Senza booking attivi**: Aggiorna lo status da `published`/`paused` a `expired` quando `endDate` è raggiunta o superata
- **Con booking attivi**: Aspetta fino al giorno dopo l'`endDate` prima di scadere il listing, per permettere ai worker di completare il lavoro
- **Scadenza booking**: Quando un listing viene scaduto, tutti i booking associati attivi (status `pending` o `confirmed`) vengono completati (status `completed`)

## 🏗️ Architettura

- **Lambda Function**: `dev-job-listings-expire`
- **EventBridge Rule**: `dev-expire-job-listings-daily`
- **Schedule**: Ogni giorno alle 2:00 AM UTC (`cron(0 2 * * ? *)`)
- **Timeout**: 5 minuti (per processare molti listings e bookings)
- **Memory**: 512 MB
- **Tables**: `JobListings`, `Bookings`

## 🔄 Funzionamento

### Logica di Scadenza

1. **Trigger**: EventBridge esegue la Lambda ogni giorno alle 2:00 AM UTC
2. **Scan**: La Lambda esegue uno scan della tabella `JobListings`
3. **Filter**: Trova tutti i listing con:
   - `status` = `published` o `paused`
   - `endDate` <= data corrente
4. **Check Bookings**: Per ogni listing trovato:
   - Query alla tabella `Bookings` (usando GSI `listingId-startDate-index`)
   - Cerca booking con status `pending` o `confirmed`
5. **Decisione di Scadenza**:
   - **Se `endDate` < oggi** (passato): Scade immediatamente, indipendentemente dai booking
   - **Se `endDate` == oggi CON booking attivi**: Salta e riprova domani (grace period)
   - **Se `endDate` == oggi SENZA booking attivi**: Scade immediatamente
6. **Expire Bookings**: Prima di scadere il listing, completa tutti i booking attivi:
   - Aggiorna status da `pending`/`confirmed` a `completed`
   - Setta `completedAt` timestamp
7. **Expire Listing**: Aggiorna lo `status` a `expired` e il timestamp `updatedAt`
8. **Report**: Ritorna il conteggio di listing scaduti, saltati, booking completati

## 📂 File Structure

```
src/lambdas/services/job-listings/expire-listings/
├── app.py              # Codice Lambda principale
└── requirements.txt    # Dipendenze Python

infra/services/job-listings/
└── template.yaml       # Configurazione SAM (risorsa ExpireJobListingsFunction)
```

## 🚀 Deploy

```powershell
# Build
sam build -t infra/services/job-listings/template.yaml

# Deploy su dev
sam deploy --config-file infra/services/job-listings/samconfig.toml --config-env dev

# Deploy su prod
sam deploy --config-file infra/services/job-listings/samconfig.toml --config-env prod
```

## 🔧 Configurazione

### Modificare l'orario di esecuzione

Modifica il parametro `Schedule` in `template.yaml`:

```yaml
Schedule: cron(0 2 * * ? *)  # Attuale: 2:00 AM UTC
```

Esempi:
- Mezzanotte UTC: `cron(0 0 * * ? *)`
- 6:00 AM UTC: `cron(0 6 * * ? *)`
- Ogni 12 ore: `cron(0 */12 * * ? *)`

### Testare manualmente

```powershell
# Invocare la Lambda manualmente
aws lambda invoke --function-name dev-job-listings-expire --region eu-south-1 response.json
cat response.json
```

## 📊 Monitoring

### CloudWatch Logs

```powershell
# Visualizza i log recenti
aws logs tail /aws/lambda/dev-job-listings-expire --region eu-south-1 --follow
```

### Metriche

La Lambda logga:
- Data di esecuzione
- Numero di listing trovati in ogni batch
- Dettagli di ogni listing scaduto (ID, titolo, endDate)
- Conteggio finale (scaduti con successo, errori)

### Verificare le esecuzioni

```powershell
# Lista delle ultime esecuzioni EventBridge
aws events list-rule-names-by-target --target-arn arn:aws:lambda:eu-south-1:881962383770:function:dev-job-listings-expire --region eu-south-1
```

## 🔒 Permessi IAM

La Lambda ha i seguenti permessi:
- `DynamoDBCrudPolicy` sulla tabella `JobListings`
- `DynamoDBCrudPolicy` sulla tabella `Bookings`
- `dynamodb:Scan` sulla tabella `JobListings`
- `dynamodb:Query` sull'indice `listingId-startDate-index` della tabella `Bookings`

## ⚠️ Note Importanti

1. **Grace Period**: Se un listing ha booking attivi il giorno della scadenza, viene dato 1 giorno extra (grace period)
2. **Booking Completion**: I booking vengono marcati come `completed` (non cancellati), preservando lo storico
3. **Conditional Updates**: La Lambda usa `ConditionExpression` per evitare race conditions
4. **Paginazione**: Gestisce automaticamente scan paginati per grandi volumi
5. **Idempotenza**: Può essere eseguita più volte senza problemi
6. **Status validi**: 
   - Listing: Solo `published` o `paused` vengono scaduti a `expired`
   - Booking: Solo `pending` o `confirmed` vengono completati a `completed`

## 📝 Esempio Output

```json
{
  "date": "2025-12-24",
  "expired_count": 15,
  "skipped_count": 3,
  "error_count": 0,
  "bookings_completed": 8,
  "bookings_errors": 0,
  "status": "success"
}
```

Dove:
- `expired_count`: Numero di job listings scaduti
- `skipped_count`: Numero di listing saltati (hanno booking attivi e endDate == oggi)
- `bookings_completed`: Numero di booking completati
- `bookings_errors`: Numero di errori nel completamento dei booking

## 🐛 Troubleshooting

### La Lambda non si esegue automaticamente

```powershell
# Verifica che la rule sia abilitata
aws events describe-rule --name dev-expire-job-listings-daily --region eu-south-1

# Verifica i target della rule
aws events list-targets-by-rule --rule dev-expire-job-listings-daily --region eu-south-1
```

### Errori di timeout

Se ci sono troppi listing da processare, aumenta il `Timeout` in `template.yaml` (attualmente 300 secondi).

### Verificare che l'attributo endDate sia corretto

```powershell
# Query DynamoDB per vedere i listing da scadere
aws dynamodb scan --table-name dev-JobListings --filter-expression "endDate <= :today AND (#status = :published OR #status = :paused)" --expression-attribute-names '{"#status":"status"}' --expression-attribute-values '{":today":{"S":"2025-12-24"},":published":{"S":"published"},":paused":{"S":"paused"}}' --region eu-south-1
```

## 🔄 Cleanup Rules Script

Se incontri il limite di EventBridge rules, usa lo script di cleanup:

```powershell
.\scripts\cleanup-eventbridge-rules.ps1
```

Questo script elimina automaticamente tutte le rules obsolete che iniziano con `cleanup-`.
