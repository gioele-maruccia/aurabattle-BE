# 🧪 Test Locale - Document Overwrite

Test completo della funzionalità di overwrite dei documenti **SENZA** toccare il database AWS reale!

## 🎯 Cosa testa

1. **Delete Existing Documents**: Verifica che la funzione `_delete_existing_documents_of_type` elimini correttamente tutti i documenti esistenti di un tipo specifico
2. **Complete Overwrite Flow**: Testa il flusso completo di upload con overwrite automatico
3. **Document Type Isolation**: Verifica che l'eliminazione di un tipo non affetti altri tipi di documenti

## 🚀 Quick Start

### Opzione 1: Script PowerShell (Raccomandato)

```powershell
# Installa dipendenze e esegui test
.\scripts\profile-upgrade-documents\run-local-test.ps1 -InstallDeps

# Oppure, se hai già le dipendenze installate:
.\scripts\profile-upgrade-documents\run-local-test.ps1
```

### Opzione 2: Python Diretto

```bash
# Installa dipendenze
pip install moto boto3

# Esegui test
python scripts/profile-upgrade-documents/test-overwrite-local.py
```

## 📋 Requisiti

- Python 3.8+
- `moto` - Mock AWS services
- `boto3` - AWS SDK per Python

## 🔍 Come Funziona

Il test usa **moto** per creare una versione mock completa di:
- ✅ DynamoDB (tabelle UserDocuments e UserProfiles)
- ✅ S3 (bucket per i documenti)
- ✅ EventBridge (per lo scheduling cleanup)

**NESSUN dato viene scritto o letto da AWS reale!**

## 📊 Output Esempio

```
======================================================================
  🧪 LOCAL TEST - Document Overwrite Feature
======================================================================

ℹ️  Testing WITHOUT touching AWS databases!
ℹ️  Using moto to mock DynamoDB and S3

======================================================================
  Setup Mock AWS Resources
======================================================================

✅ Created mock DynamoDB table: test-UserDocuments
✅ Created mock DynamoDB table: test-UserProfiles
✅ Created mock S3 bucket: test-bucket

======================================================================
  Test 1: Delete Existing Documents Function
======================================================================

ℹ️  Inserting 3 existing 'id_card_front' documents for user test-user-123
   Document 1: DOC#id_card_front#1707523456789
   Document 2: DOC#id_card_front#1707523446789
   Document 3: DOC#id_card_front#1707523436789
✅ Inserted 3 existing documents
ℹ️  Documents in DB before delete: 3
ℹ️  Files in S3 before delete: 3
ℹ️  Calling _delete_existing_documents_of_type...
ℹ️  Documents in DB after delete: 0
ℹ️  Files in S3 after delete: 0
ℹ️  Deleted count returned: 3
✅ All documents deleted successfully!

======================================================================
  📊 Test Summary
======================================================================
✅ PASSED - Delete Existing Documents
✅ PASSED - Complete Overwrite Flow
✅ PASSED - Document Type Isolation

======================================================================
  Results: 3/3 tests passed
======================================================================

✅ All tests passed! 🎉
```

## 🔧 Struttura Test

### Test 1: Delete Function
- Crea 3 documenti esistenti dello stesso tipo
- Chiama `_delete_existing_documents_of_type()`
- Verifica che tutti siano stati eliminati da DB e S3

### Test 2: Complete Flow
- Crea 2 documenti esistenti
- Simula una chiamata API completa (lambda_handler)
- Verifica che i vecchi documenti siano eliminati
- Verifica che il nuovo documento sia stato creato

### Test 3: Isolation
- Crea documenti di 3 tipi diversi
- Elimina solo un tipo
- Verifica che gli altri tipi non siano stati toccati

## ⚠️ Note

- I test sono completamente isolati e non richiedono connessione ad AWS
- Ogni test crea il proprio ambiente mock pulito
- Non è necessario avere credenziali AWS configurate
- Perfetto per CI/CD e sviluppo locale

## 🐛 Troubleshooting

### Errore: "moto not found"
```powershell
pip install moto boto3
```

### Errore: "Python not found"
Installa Python 3.8+ da python.org

### Test falliscono
Verifica che il codice in `src/lambdas/services/profile-upgrade-documents/presign-url/app.py` sia aggiornato con le modifiche per l'overwrite.
