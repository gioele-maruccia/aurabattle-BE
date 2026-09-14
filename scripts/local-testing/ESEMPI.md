# 🧪 Esempi Pratici di Test API in Locale

## Esempio 1: Test Update Profile

### 1. Crea l'evento di test

`events/update-profile-test.json`:
```json
{
  "requestContext": {
    "authorizer": {
      "claims": {
        "sub": "user-123",
        "email": "test@example.com"
      }
    }
  },
  "body": "{\"firstName\":\"Mario\",\"lastName\":\"Rossi\"}"
}
```

### 2. Esegui il test

```powershell
cd scripts\local-testing

# Con dati dal dev
.\quick-test.ps1 test `
  -Lambda user-api/update-profile `
  -Event events/update-profile-test.json `
  -LoadData

# Oppure modalità interattiva
.\quick-test.ps1 interactive
```

## Esempio 2: Test Create Job Listing

### 1. Prepara evento

`events/create-job-listing.json`:
```json
{
  "requestContext": {
    "authorizer": {
      "claims": {
        "sub": "company-user-id"
      }
    }
  },
  "body": "{\"title\":\"Software Developer\",\"description\":\"Python developer needed\",\"salary\":45000}"
}
```

### 2. Test

```powershell
.\quick-test.ps1 test `
  -Lambda job-listings/create-listing `
  -Event events/create-job-listing.json `
  -LoadData
```

## Esempio 3: Workflow Completo per Bug Fix

### Scenario: Bug nell'aggiornamento profilo

```powershell
# 1. Esporta dati che riproducono il bug
python export-dev-data.py UserProfiles --limit 50

# 2. Crea evento che riproduce il problema
# events/bug-fix-test.json

# 3. Test per confermare il bug
.\quick-test.ps1 test `
  -Lambda user-api/update-profile `
  -Event events/bug-fix-test.json `
  -LoadData

# 4. Fixa il codice in src/lambdas/...

# 5. Ri-testa per confermare la fix
.\quick-test.ps1 test `
  -Lambda user-api/update-profile `
  -Event events/bug-fix-test.json `
  -LoadData

# 6. Deploy con fiducia! 🚀
```

## Esempio 4: Test con Variabili d'Ambiente Custom

```bash
# Python diretto con env vars
python test-api-local.py \
  --lambda ../../src/lambdas/services/profile-upgrade-documents/presign-url \
  --event events/presign-test.json \
  --load-data \
  --env TABLE_NAME=UserDocuments \
  --env BUCKET=test-beebusy-documents \
  --env USER_PROFILES_TABLE=UserProfiles
```

## Esempio 5: Export Selettivo

```bash
# Solo una tabella
python export-dev-data.py UserProfiles

# Con limite
python export-dev-data.py JobListings --limit 100

# Tutte le tabelle
python export-dev-data.py --scan-all
```

## Tips per Eventi di Test

### Template Base

```json
{
  "requestContext": {
    "authorizer": {
      "claims": {
        "sub": "user-id",
        "email": "user@example.com"
      }
    },
    "requestId": "test-request",
    "identity": {
      "sourceIp": "127.0.0.1"
    }
  },
  "httpMethod": "POST",
  "path": "/api/endpoint",
  "headers": {
    "Content-Type": "application/json"
  },
  "body": "{...}"
}
```

### Con Path Parameters

```json
{
  "requestContext": { ... },
  "pathParameters": {
    "userId": "123",
    "id": "456"
  },
  "body": "{...}"
}
```

### Con Query Parameters

```json
{
  "requestContext": { ... },
  "queryStringParameters": {
    "limit": "10",
    "offset": "0",
    "status": "active"
  }
}
```

## Script PowerShell Custom

Crea il tuo script personalizzato:

```powershell
# test-my-api.ps1
function Test-MyAPI {
    param(
        [string]$TestCase = "default"
    )
    
    cd scripts\local-testing
    
    switch ($TestCase) {
        "create" {
            .\quick-test.ps1 test `
                -Lambda my-service/create `
                -Event events/my-create.json `
                -LoadData
        }
        "update" {
            .\quick-test.ps1 test `
                -Lambda my-service/update `
                -Event events/my-update.json `
                -LoadData
        }
        default {
            .\quick-test.ps1 interactive
        }
    }
}

# Uso:
# .\test-my-api.ps1 create
# .\test-my-api.ps1 update
```

## Debug con VSCode

`.vscode/launch.json`:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Debug API Test",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/scripts/local-testing/test-api-local.py",
      "args": [
        "--lambda",
        "${workspaceFolder}/src/lambdas/services/user-api/update-profile",
        "--event",
        "${workspaceFolder}/scripts/local-testing/events/test.json",
        "--load-data"
      ],
      "console": "integratedTerminal",
      "justMyCode": false
    }
  ]
}
```

Premi F5 per debuggare! 🐛

## Checklist Pre-Deploy

- [ ] Esportati dati freschi dal dev
- [ ] Testata l'API con dati reali
- [ ] Verificati tutti i casi edge
- [ ] Testati scenari di errore
- [ ] Controllato che il DB dev sia intatto
- [ ] Pronto per il deploy! 🚀

---

Per più informazioni: [README.md](README.md)
