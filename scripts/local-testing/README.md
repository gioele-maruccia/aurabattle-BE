# 🧪 Test API in Locale - ZERO Rischio per DB Dev

Sistema definitivo per testare **TUTTE le API** in locale usando dati reali dal DB dev ma **SENZA MAI modificarlo**!

## 🎯 Obiettivi

- ✅ Testare Lambda/API in locale
- ✅ Usare dati reali dal DB dev (solo lettura)
- ✅ **ZERO rischio** di modificare il DB dev
- ✅ Trovare bug senza impatto sull'ambiente dev
- ✅ Setup riutilizzabile per qualsiasi API

## 🛠️ Come Funziona

Usa **moto** per creare un ambiente AWS completamente mockato in locale:
- DynamoDB locale (simulato)
- S3 locale (simulato)
- **NESSUNA connessione** ai servizi AWS reali durante i test

## 📋 Requisiti

- Python 3.8+
- pip
- AWS CLI configurato (solo per export dati, non per i test)

Le dipendenze vengono installate automaticamente:
```bash
pip install moto boto3
```

## 🚀 Quick Start

### 1. Setup Iniziale (UNA VOLTA)

```powershell
cd scripts\local-testing
.\quick-test.ps1 setup
```

Questo crea:
- Directory `events/` per gli eventi di test
- Directory `exported-data/` per i dati dal dev
- File `.gitignore` per non committare dati sensibili

### 2. Esporta Dati dal Dev (Opzionale ma Consigliato)

```powershell
# Esporta tutti i dati
.\quick-test.ps1 export

# O manualmente per tabelle specifiche
python export-dev-data.py UserProfiles
python export-dev-data.py JobListings --limit 100
```

**⚠️ IMPORTANTE**: Questo comando è **READ-ONLY** - legge solo dal DB dev, **NON lo modifica mai**!

### 3. Testa le tue API

#### Opzione A: Modalità Interattiva (FACILE) 🎮

```powershell
.\quick-test.ps1 interactive
```

Ti guida passo-passo:
1. Scegli quale Lambda testare
2. Specifica l'evento (o lascia vuoto)
3. Decidi se caricare dati dal dev
4. Imposta variabili d'ambiente
5. 🚀 Esegui il test!

#### Opzione B: Comando Diretto ⚡

```powershell
# Test con DB vuoto
.\quick-test.ps1 test -Lambda user-api/update-profile -Event events/test.json

# Test con dati dal dev
.\quick-test.ps1 test -Lambda user-api/update-profile -Event events/test.json -LoadData
```

#### Opzione C: Python Diretto (Avanzato) 🔧

```bash
# Test base
python test-api-local.py \
  --lambda ../../src/lambdas/services/user-api/update-profile \
  --event events/update-profile.json

# Test con dati caricati
python test-api-local.py \
  --lambda ../../src/lambdas/services/user-api/update-profile \
  --event events/update-profile.json \
  --load-data

# Con variabili d'ambiente
python test-api-local.py \
  --lambda ../../src/lambdas/services/companies/create-company \
  --event events/create-company.json \
  --load-data \
  --env TABLE_NAME=Companies \
  --env BUCKET=test-beebusy-images
```

## 📂 Struttura Directory

```
scripts/local-testing/
├── config.json                  # Configurazione (tabelle, bucket, ecc)
├── quick-test.ps1              # Script PowerShell per uso rapido
├── export-dev-data.py          # Export dati dal dev (READ-ONLY)
├── setup-local-env.py          # Setup ambiente moto
├── test-api-local.py           # Template test universale
├── README.md                   # Questa documentazione
├── events/                     # Eventi JSON per test
│   ├── update-profile.json
│   ├── create-company.json
│   └── ...
└── exported-data/              # Dati esportati dal dev (gitignored)
    ├── UserProfiles_latest.json
    ├── JobListings_latest.json
    └── ...
```

## 📝 Esempi di Eventi

### Esempio: Update Profile

Crea `events/update-profile.json`:

```json
{
  "requestContext": {
    "authorizer": {
      "claims": {
        "sub": "123e4567-e89b-12d3-a456-426614174000",
        "email": "test@example.com"
      }
    }
  },
  "body": "{\"firstName\":\"Mario\",\"lastName\":\"Rossi\",\"phoneNumber\":\"+393331234567\"}"
}
```

### Esempio: Create Job Listing

Crea `events/create-job-listing.json`:

```json
{
  "requestContext": {
    "authorizer": {
      "claims": {
        "sub": "company-user-id"
      }
    }
  },
  "body": "{\"title\":\"Software Developer\",\"description\":\"Looking for a Python developer\",\"location\":\"Milano\",\"salary\":45000}"
}
```

## 🔧 Configurazione Avanzata

### Modificare le Tabelle da Esportare

Edita `config.json`:

```json
{
  "dev_environment": {
    "tables_to_export": {
      "UserProfiles": "dev-UserProfiles",
      "MiaNuovaTabella": "dev-MiaNuovaTabella"
    }
  },
  "local_mock": {
    "tables": [
      "UserProfiles",
      "MiaNuovaTabella"
    ]
  }
}
```

### Aggiungere Bucket S3

Edita `config.json`:

```json
{
  "local_mock": {
    "buckets": [
      "test-beebusy-documents",
      "test-mio-nuovo-bucket"
    ]
  }
}
```

## 🎓 Workflow Consigliato

### Per Testare una Nuova API

1. **Esporta dati freschi** (se necessario):
   ```powershell
   .\quick-test.ps1 export
   ```

2. **Crea evento di test** in `events/`:
   ```json
   // events/my-test.json
   {
     "requestContext": {...},
     "body": "{...}"
   }
   ```

3. **Testa in modalità interattiva**:
   ```powershell
   .\quick-test.ps1 interactive
   ```

4. **Itera** fino a quando l'API funziona correttamente

5. **Deploy** con fiducia! 🚀

### Per Trovare Bug

1. **Esporta dati che riproducono il problema**:
   ```bash
   python export-dev-data.py UserProfiles --limit 10
   ```

2. **Testa con dati reali**:
   ```powershell
   .\quick-test.ps1 test -Lambda path/to/lambda -Event events/test.json -LoadData
   ```

3. **Debug** localmente senza paura

4. **Verifica la fix** ri-testando

## 🔐 Sicurezza

### Il DB Dev È Sempre Sicuro

- ✅ **Export**: Solo operazioni READ (`scan`, `query`) - nessuna scrittura
- ✅ **Test**: Usa **solo moto mock** - ZERO connessione ad AWS
- ✅ **Dati esportati**: Salvati in locale, gitignored

### Cosa NON Viene Mai Modificato

Durante i test con moto:
- ❌ DynamoDB dev
- ❌ S3 dev
- ❌ Cognito
- ❌ Qualsiasi servizio AWS reale

## 🐛 Troubleshooting

### "moto not found"

```powershell
pip install moto boto3
```

### "Lambda not found"

Verifica il path relativo:
```powershell
# Corretto
.\quick-test.ps1 test -Lambda user-api/update-profile -Event events/test.json

# Il path completo viene costruito automaticamente
```

### "No module named 'app'"

Assicurati che la directory Lambda contenga `app.py`:
```
src/lambdas/services/user-api/update-profile/
└── app.py  # ✅ Deve esistere
```

### "Event file not found"

Il file evento deve essere:
- In `events/` directory, oppure
- Specificato con path assoluto/relativo

```powershell
# Questi funzionano entrambi
-Event events/test.json
-Event C:\path\to\test.json
```

### Errori di Importazione nella Lambda

Se la tua Lambda usa moduli custom, aggiungi al PYTHONPATH:

```bash
$env:PYTHONPATH = "C:\path\to\modules;$env:PYTHONPATH"
python test-api-local.py --lambda ...
```

## 📚 Script Disponibili

### `quick-test.ps1` 
Script PowerShell all-in-one
- `setup`: Setup iniziale
- `export`: Esporta dati dal dev
- `test`: Testa una Lambda
- `interactive`: Modalità guidata

### `export-dev-data.py`
Esporta dati dal DB dev (READ-ONLY)
```bash
python export-dev-data.py [table] [--limit N] [--scan-all]
```

### `setup-local-env.py`
Setup ambiente moto (uso interno)
```bash
python setup-local-env.py [--load-data] [--tables TABLE1,TABLE2]
```

### `test-api-local.py`
Template universale per test
```bash
python test-api-local.py --lambda <path> --event <json> [--load-data] [--env KEY=VALUE]
```

## 🎯 Best Practices

### ✅ DO

- Esporta dati prima di testare modifiche importanti
- Usa nomi descrittivi per gli eventi (`events/bug-123-reproduce.json`)
- Testa sempre con `--load-data` prima del deploy
- Crea eventi di test per casi edge
- Mantieni `config.json` aggiornato con nuove tabelle

### ❌ DON'T

- Non committare dati esportati (sono gitignored)
- Non modificare `config.json` in prod
- Non usare credenziali reali negli eventi di test
- Non fare test direttamente sul DB dev (usa questo tool!)

## 🔄 Aggiornamenti Futuri

Quando aggiungi nuove Lambda o tabelle:

1. Aggiorna `config.json`:
   ```json
   {
     "dev_environment": {
       "tables_to_export": {
         "NuovaTabella": "dev-NuovaTabella"
       }
     }
   }
   ```

2. Esporta i nuovi dati:
   ```powershell
   .\quick-test.ps1 export
   ```

3. Testa come sempre! 🚀

## 💡 Tips & Tricks

### Test Rapidi con Alias

Aggiungi al tuo PowerShell profile:

```powershell
# $PROFILE
function Test-API {
    param($Lambda, $Event)
    cd C:\path\to\scripts\local-testing
    .\quick-test.ps1 test -Lambda $Lambda -Event $Event -LoadData
}

# Uso: Test-API user-api/update-profile events/test.json
```

### Debug con VSCode

Crea `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Test API Local",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/scripts/local-testing/test-api-local.py",
      "args": [
        "--lambda", "../../src/lambdas/services/user-api/update-profile",
        "--event", "events/test.json",
        "--load-data"
      ],
      "console": "integratedTerminal"
    }
  ]
}
```

### Backup Dati Esportati

```powershell
# Backup periodico
$date = Get-Date -Format "yyyyMMdd"
Copy-Item exported-data exported-data-backup-$date -Recurse
```

## 📞 Supporto

Problemi o domande?

1. Controlla la sezione [Troubleshooting](#-troubleshooting)
2. Verifica i requisiti in [Requisiti](#-requisiti)
3. Esegui `.\quick-test.ps1 -Help` per opzioni

## 🎉 Conclusione

Ora hai un sistema completo per testare le API in locale senza rischi!

**Ricorda:**
- 🔒 Il DB dev è **sempre sicuro**
- 🧪 Testa **quanto vuoi** in locale
- 🐛 Trova bug **prima** del deploy
- 🚀 Deploy con **fiducia**

**Usalo SEMPRE prima di modificare API o fare deploy!**

---

Made with ❤️ for beebusy Development Team
