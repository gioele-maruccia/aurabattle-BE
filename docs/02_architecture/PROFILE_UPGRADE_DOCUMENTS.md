# Profile Upgrade Documents - Complete Setup & How It Works

## 🎯 Overview

Il servizio **Profile Upgrade Documents** gestisce l'upload e la validazione di documenti per il profilo utente (carta d'identità, visura, ecc.). I documenti vengono sottoposti a revisione dal backoffice.

## ⚡ Quick Start

### Setup Automatico (Scelta Consigliata)
```powershell
# Deploya tutto in un comando (CloudFormation + S3 Events)
.\scripts\profile-upgrade-documents\deploy.ps1 -Environment dev
```

Questo script:
- ✅ Deploya lo stack CloudFormation
- ✅ Configura automaticamente gli S3 event notifications
- ✅ Verifica che tutto sia corretto

### Test
```powershell
# Testa il flusso completo
.\scripts\profile-upgrade-documents\test-upload.ps1 -Environment dev
```

---

## 🔄 Come Funziona (Flusso Completo)

### Fase 1: Richiesta Presigned URL
```
Client (Frontend)
  ↓ POST /documents/upload-url
  │ {docType: "id_card_front", mime: "image/jpeg", size: 2048576}
  │
  ▼
Lambda: presign-url
  ├─ ✅ Valida JWT token Cognito → estrae user_sub
  ├─ ✅ Valida docType (id_card_front, id_card_back, visura)
  ├─ ✅ Valida mime (image/jpeg, image/png, application/pdf)
  ├─ ✅ Valida dimensione (< 10 MB)
  ├─ ✅ Genera S3 key: docs/{user_sub}/{timestamp}_{docType}.{ext}
  ├─ 📝 Crea record DynamoDB:
  │  └─ PK: USER#{user_sub}
  │  └─ SK: DOC#{docType}#{timestamp}
  │  └─ status: "PENDING" ← STATO INIZIALE
  ├─ 🔗 Schedula cleanup automatico (EventBridge, 5.5 min)
  └─ ↩️  Ritorna presigned URL al client
```

**Variabili d'ambiente:**
- `BUCKET`: beezey-dev-user-documents
- `TABLE_NAME`: dev-UserDocuments
- `KMS_KEY_ID`: chiave per encryption

---

### Fase 2: Upload File
```
Client
  ↓ PUT {presigned_url}
  │ [File bytes] + Headers KMS
  │
  ▼
S3 Bucket
  ├─ Riceve file
  ├─ Applica KMS encryption
  ├─ Salva: docs/{user_sub}/{timestamp}_{docType}.jpg
  │
  ✅ TRIGGER S3 EVENT ← **ORA CONFIGURATO AUTOMATICAMENTE!**
  │
  ▼
EventBridge Notification
  └─ Invoca Lambda: doc-received
```

---

### Fase 3: Processing Documento
```
Lambda: doc-received
  ├─ 📖 Legge S3 event (bucket, key, size)
  ├─ 🔍 Estrae PK/SK dal nome file:
  │  └─ PK: USER#{user_sub}
  │  └─ SK: DOC#{docType}#{timestamp}
  ├─ 📝 Update DynamoDB:
  │  └─ status: "UPLOADED" ← STATO INTERMEDIO
  ├─ 🔗 Invoca Lambda: doc-scan (async)
  └─ ✅ Ritorna {"ok": true}
           ↓
Lambda: doc-scan
  ├─ 🔍 Scansiona il file:
  │  ├─ Estensione (.jpg, .png, .pdf) ✅
  │  ├─ Dimensione (< 10 MB) ✅
  │  ├─ No doppia estensione (.pdf.exe) ✅
  │  └─ No whitespace sospetto ✅
  │
  ├─ 📝 Update DynamoDB in base al risultato:
  │  ├─ SE OK: status = "AWAITING_REVIEW" ✅ BACKOFFICE PUÒ VEDERLO
  │  └─ SE BLOCCATO: status = "REJECTED" + reason
  │
  └─ ✅ Ritorna {"ok": true, "result": "clean"}
```

---

### Fase 4: Backoffice Review
```
Lambda: profile-upgrade-request
  ├─ Legge documento da DynamoDB (status = "AWAITING_REVIEW")
  │
  ├─ Backoffice ACCETTA:
  │  ├─ 📝 Update status: "APPROVED"
  │  └─ 🎉 Profilo utente aggiornato
  │
  └─ Backoffice RIFIUTA:
     ├─ 📝 Update status: "REJECTED"
     ├─ 💬 Aggiunge reason (es: "invalid_document")
     └─ 👤 Utente può ricaricare nuovo documento
```

---

### Fase 5: Cleanup (Timeout)
```
EventBridge Rule: cleanup-{timestamp}
  ├─ Trigger: dopo 5.5 minuti (presigned URL scaduto)
  │
  ▼
Lambda: cleanup-expired-uploads
  ├─ Controlla DynamoDB: se status === "PENDING" (mai uploadato)
  │  ├─ ✅ Cancella file da S3
  │  ├─ 📝 Update status: "EXPIRED"
  │  └─ 🔗 Rimuove EventBridge rule
  │
  └─ Altrimenti: niente da fare (file è in gestione backoffice)
```

---

## 📊 Document Status Flow

| Status | Significato | Durata | Azioni Possibili |
|--------|-------------|--------|-----------------|
| **PENDING** | URL richiesto, in attesa upload | Max 5 min | Upload file |
| **UPLOADED** | File caricato, scansione in corso | < 1 sec | (automatico) |
| **AWAITING_REVIEW** | Pronto per backoffice | Variable | Accept/Reject |
| **APPROVED** | Accettato dal backoffice | Permanente | Profilo aggiornato |
| **REJECTED** | Rifiutato (scansione o backoffice) | Permanente | Ricaricare nuovo |
| **EXPIRED** | Timeout (5.5 min senza upload) | Permanente | Ricaricare nuovo |

---

## 🏗️ Architettura & Lambda Functions

### Lambda Functions
```
presign-url          → API Gateway
├─ Genera presigned URL
├─ Crea record DynamoDB
└─ Schedula cleanup

doc-received         → S3 Event (Trigger Automatico)
├─ Processa S3 upload
├─ Aggiorna DynamoDB
└─ Invoca doc-scan

doc-scan             → Invocato da doc-received
├─ Valida file (estensione, size, etc)
├─ Aggiorna status (AWAITING_REVIEW o REJECTED)
└─ Richiede permesso per spostare file in folders

cleanup-expired-uploads → EventBridge (Time-based)
├─ Cancella upload scaduti
└─ Ripulisce DynamoDB

get-user-docs-status → API Gateway
├─ Legge status documenti utente
└─ Ritorna lista con info upload
```

### DynamoDB Table Schema
```
Table: dev-UserDocuments (or prod-UserDocuments)

Primary Key:
  PK: USER#{user_sub}           (Partition Key)
  SK: DOC#{docType}#{timestamp} (Sort Key)

Attributes:
  status          : String (PENDING, UPLOADED, AWAITING_REVIEW, etc)
  docType         : String (id_card_front, id_card_back, visura)
  s3Key           : String (docs/user_sub/timestamp_docType.ext)
  mime            : String (image/jpeg, image/png, application/pdf)
  size            : Number (bytes)
  uploadedAt      : String (ISO-8601 timestamp)
  ttl             : Number (30 days expiry)
  approvedAt      : String (optional, when backoffice approves)
  reason          : String (optional, when rejected)
```

### S3 Bucket Structure
```
s3://beezey-dev-user-documents/
├─ docs/                    ← Tutti i documenti uploadati
│  └─ {user_sub}/
│     ├─ 1733312018891_id_card_front.jpg      ← Naming: {timestamp}_{docType}.{ext}
│     ├─ 1733312018892_id_card_back.jpg
│     └─ 1733312018893_visura.pdf
│
├─ clean/                   ← (Optional) Documenti approvati
└─ quarantine/              ← (Optional) Documenti bloccati
```

---

## ⚙️ Setup Dettagliato

### 1. Deploy Automatico (Consigliato)
```powershell
.\scripts\profile-upgrade-documents\deploy.ps1 -Environment dev
```

Questo fa tutto in un comando:
- ✅ Deploya template SAM
- ✅ Configura S3 events (tramite Custom Resource Lambda)
- ✅ Verifica Lambda ARN
- ✅ Configura bucket notification

**Output atteso:**
```
[1/4] Verifying AWS credentials...
✅ AWS Account: 123456789012

[2/4] Deploying CloudFormation stack 'dev-docs-upload'...
Running: sam deploy --config-env dev --no-confirm-changeset
...
✅ Stack deployed successfully

[3/4] Retrieving Lambda ARN from stack outputs...
✅ Lambda ARN: arn:aws:lambda:eu-south-1:123456789012:function:dev-doc-received

[4/4] Configuring S3 event notification...
✅ S3 event notification configured

========================================
✅ SETUP COMPLETE!
========================================
```

### 2. Verifica Manuale (se necessario)
```bash
# Controlla che S3 event sia configurato
aws s3api get-bucket-notification-configuration \
  --bucket beezey-dev-user-documents \
  --region eu-south-1

# Output atteso:
{
  "LambdaFunctionConfigurations": [
    {
      "LambdaFunctionArn": "arn:aws:lambda:eu-south-1:...:function:dev-doc-received",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "docs/"}]}}
    }
  ]
}
```

---

## 🧪 Testing

### Test Quick
```powershell
# Legge dati da DynamoDB e API
.\scripts\profile-upgrade-documents\test-upload.ps1 -Environment dev

# Output:
# ✅ API: https://...execute-api.eu-south-1.amazonaws.com/dev/
# ✅ Presigned URL generated
# ✅ Found 5 document(s) in DynamoDB:
#    User: user123 | DocType: id_card_front | Status: AWAITING_REVIEW
#    User: user456 | DocType: visura | Status: PENDING
```

### CloudWatch Logs
```bash
# Segui i log di doc-received
aws logs tail /aws/lambda/dev-doc-received --follow

# Segui i log di doc-scan
aws logs tail /aws/lambda/dev-doc-scan --follow

# Segui i log di presign-url
aws logs tail /aws/lambda/dev-docs-presign-url --follow
```

---

## 🐛 Troubleshooting

### ❌ Documenti rimangono in PENDING
```bash
# 1. Verifica S3 event notification
aws s3api get-bucket-notification-configuration \
  --bucket beezey-dev-user-documents \
  --region eu-south-1

# Dovrebbe mostrare LambdaFunctionConfigurations non vuoto
# Se vuoto, esegui deploy.ps1 di nuovo

# 2. Controlla CloudWatch logs
aws logs tail /aws/lambda/dev-doc-received --follow

# Dovrebbe mostrare invocazioni quando file viene uploadato
```

### ❌ AWS CLI non trovato
```powershell
# Installa AWS CLI
choco install awscli  # Con Chocolatey
# o scarica da https://aws.amazon.com/cli/
```

### ❌ Credenziali AWS non trovate
```powershell
# Configura AWS credentials
aws configure

# Verifica che funzioni
aws sts get-caller-identity
```

### ❌ Stack CloudFormation fallisce
```bash
# Controlla stack status
aws cloudformation describe-stacks \
  --stack-name dev-docs-upload \
  --region eu-south-1

# Controlla stack events
aws cloudformation describe-stack-events \
  --stack-name dev-docs-upload \
  --region eu-south-1 | jq '.StackEvents[] | {Timestamp, ResourceStatus, ResourceStatusReason}'
```

---

## 🔧 Configurazione Ambiente

### Development
```
Environment:     dev
Bucket:          beezey-dev-user-documents
Table:           dev-UserDocuments
Lambda Prefix:   dev-
User Pool:       eu-south-1_0oK9agPYd
Region:          eu-south-1
```

### Production
```
Environment:     prod
Bucket:          beezey-prod-user-documents
Table:           prod-UserDocuments
Lambda Prefix:   prod-
User Pool:       eu-south-1_iCBtUlJO6
Region:          eu-south-1
```

---

## 📋 IAM Permissions

Tutte le lambda hanno permessi corretti nel template SAM:

| Lambda | Permessi | Scopo |
|--------|----------|-------|
| **presign-url** | S3:PutObject, DDB:PutItem, KMS:Encrypt, Events:PutRule | Genera URL e schedula cleanup |
| **doc-received** | DDB:UpdateItem, Lambda:InvokeFunction, KMS:Decrypt | Processa S3 event |
| **doc-scan** | S3:GetObject, DDB:UpdateItem, KMS:Decrypt | Scansiona e valida file |
| **cleanup-expired-uploads** | S3:HeadObject, DDB:UpdateItem, Events:DeleteRule | Ripulisce timeout |
| **get-user-docs-status** | DDB:Query, S3:HeadObject, KMS:Decrypt | Legge status |
| **configure-s3-events** | S3:PutBucketNotificationConfiguration | Configura S3 events |

---

## 📝 File Importanti

```
infra/services/profile-upgrade-documents/
├── template.yaml          ← SAM template con tutte le lambda e Custom Resource
└── samconfig.toml         ← Config per dev/prod deployment

src/lambdas/services/profile-upgrade-documents/
├── presign-url/           ← Genera presigned URL
├── doc-received/          ← Triggerato da S3 event
├── doc-scan/              ← Valida file
├── cleanup-expired-uploads/
└── get-user-docs-status/

scripts/profile-upgrade-documents/
├── deploy.ps1             ← Deploy automatico (ScriptPrincipale)
└── test-upload.ps1        ← Test rapido flusso
```

---

## 🚀 Workflow Deploy → Test

```powershell
# 1. Deploy tutto (CloudFormation + S3 events)
.\scripts\profile-upgrade-documents\deploy.ps1 -Environment dev

# 2. Test
.\scripts\profile-upgrade-documents\test-upload.ps1 -Environment dev

# 3. Se tutto OK, documenti inizieranno a passare PENDING → AWAITING_REVIEW
```

---

## 📞 Support

### Verifiche rapide
```bash
# Stack esiste?
aws cloudformation list-stacks --region eu-south-1 | grep dev-docs-upload

# Lambda esiste?
aws lambda list-functions --region eu-south-1 | grep doc-received

# DynamoDB table esiste?
aws dynamodb list-tables --region eu-south-1

# S3 bucket esiste?
aws s3 ls | grep beezey-dev-user-documents
```

### Debug completo
```bash
# Leggi stack template
aws cloudformation get-template --stack-name dev-docs-upload --region eu-south-1

# Leggi tutti i log
for func in presign-url doc-received doc-scan cleanup-expired-uploads; do
  echo "=== $func ==="
  aws logs tail /aws/lambda/dev-$func --region eu-south-1
done
```

---

## ✅ Checklist Post-Deploy

- [ ] Script deploy.ps1 eseguito con successo
- [ ] S3 event notification verificato (`get-bucket-notification-configuration`)
- [ ] Test script test-upload.ps1 eseguito
- [ ] DynamoDB contiene documenti con stato AWAITING_REVIEW
- [ ] CloudWatch logs mostrano invocazioni Lambda
- [ ] Backoffice può leggere documenti da profile-upgrade-request

---

## 🎯 Prossimi Step

1. **Dopo primo deploy:** Verifica con `test-upload.ps1`
2. **Integrazione con Frontend:** Usa presigned URL per upload
3. **Integrazione Backoffice:** Leggi AWAITING_REVIEW da profile-upgrade-request
4. **Monitoring:** Setup CloudWatch alarms per lambda errors

---

**Status:** ✅ Risolto - S3 events sono ora configurati automaticamente dal template SAM
