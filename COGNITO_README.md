# 🔐 COGNITO CONFIGURATION - GUIDA DEFINITIVA

## ⚠️ IMPORTANTE: LEGGI QUESTO PRIMA DI QUALSIASI COSA

**QUESTO FILE È LA TUA SALVEZZA!** Non cercare mai più gli ID di Cognito in giro.

---

## 📍 DOVE TROVARE I CLIENT ID E USER POOL ID

### File Di Configurazione Centralizzato:
```
cognito_config.py
```

**Questo file contiene:**
- ✅ User Pool IDs (dev e prod)
- ✅ Client IDs (dev e prod)  
- ✅ ARN dei User Pool
- ✅ Region
- ✅ Helper functions per Amplify config

---

## 🚀 COME USARLO NEI TUOI SCRIPT

### Python Scripts:
```python
from cognito_config import COGNITO_DEV, COGNITO_PROD

# Per development:
pool_id = COGNITO_DEV['user_pool_id']
client_id = COGNITO_DEV['client_id']

# Per production:
pool_id = COGNITO_PROD['user_pool_id']
client_id = COGNITO_PROD['client_id']
```

### PowerShell Scripts:
```powershell
# Importa dal config Python
$CognitoConfig = python -c "from cognito_config import COGNITO_PROD; import json; print(json.dumps(COGNITO_PROD))" | ConvertFrom-Json

$UserPoolId = $CognitoConfig.user_pool_id
$ClientId = $CognitoConfig.client_id
```

---

## 📱 CONFIGURAZIONE FRONTEND (Flutter/React)

### Ottenere la config per Amplify:
```python
from cognito_config import get_amplify_config

# Genera config per ambiente prod:
config = get_amplify_config('prod')
print(json.dumps(config, indent=2))
```

### Output per Flutter:
```json
{
  "auth": {
    "plugins": {
      "awsCognitoAuthPlugin": {
        "CognitoUserPool": {
          "Default": {
            "PoolId": "eu-south-1_iCBtUlJO6",
            "AppClientId": "61aa1ldskboni1e18unp49cl57",
            "Region": "eu-south-1"
          }
        }
      }
    }
  }
}
```

---

## 🔧 VALORI ATTUALI (Febbraio 2026)

### DEVELOPMENT:
- **User Pool ID:** `eu-south-1_0oK9agPYd`
- **Client ID:** `79g67hnuepfuoh1fnk4d98jfpu`
- **Region:** `eu-south-1`

### PRODUCTION:
- **User Pool ID:** `eu-south-1_iCBtUlJO6`
- **Client ID:** `61aa1ldskboni1e18unp49cl57` ⚠️ NUOVO!
- **Region:** `eu-south-1`

#### ⚠️ Storia del Client ID Production:
- **Vecchio:** `20gudbvdh3hesbge0c8od0202b` (Eliminato il 2026-02-18 alle 10:44:31)
- **Nuovo:** `61aa1ldskboni1e18unp49cl57` (Creato il 2026-02-18 alle 11:19:02)

**Motivo cambio:** Il vecchio client è stato accidentalmente eliminato da CloudFormation durante un deploy. Il nuovo client ha configurazione identica.

---

##  ❌ COSA NON FARE MAI PIÙ

### 1. NON hardcodare mai Client ID negli script:
```python
# ❌ SBAGLIATO:
CLIENT_ID = "20gudbvdh3hesbge0c8od0202b"

# ✅ GIUSTO:
from cognito_config import COGNITO_PROD
CLIENT_ID = COGNITO_PROD['client_id']
```

### 2. NON deployare infra/core/cognito-setup senza capire cosa fa:
Il template in `infra/core/cognito-setup/template.yaml` ora deploya **SOLO** la Lambda PostConfirmation. Non crea mai più User Pool o Client nuovi.

### 3. NON modificare manualmente User Pool o Client in AWS Console:
Se devi cambiare qualcosa, documentalo qui e aggiorna `cognito_config.py`

---

## 📂 FILE AGGIORNATI CON IL NUOVO CONFIG

Tutti questi file ora usano `cognito_config.py`:
- ✅ `test-reject-real.py`
- ✅ `test-company-listings-local.py`
- ✅ `test-applicable-job-roles-local.py`
- ✅ `test-booking-metadata-fix.py`
- ✅ `test-chat-send-with-name.py`
- ✅ `test-chat-notification-simple.py`
- ✅ `test-chat-notification-complete.py`
- ✅ `test-chat-message-lambda.py`
- ✅ `test-chat-message-notification.py`

---

## 🔄 SE DEVI CAMBIARE IL CLIENT ID IN FUTURO

### 1. Crea nuovo client in AWS Console o via CLI:
```bash
aws cognito-idp create-user-pool-client \
  --user-pool-id eu-south-1_iCBtUlJO6 \
  --client-name prod-BeezeyUserPoolClient \
  --no-generate-secret \
  --explicit-auth-flows ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH ALLOW_USER_PASSWORD_AUTH \
  --prevent-user-existence-errors ENABLED \
  --region eu-south-1
```

### 2. Aggiorna SOLO cognito_config.py:
```python
COGNITO_PROD = {
    'client_id': 'IL_NUOVO_CLIENT_ID_QUI',
    # ... resto rimane uguale
}
```

### 3. FINE! Tutti gli script useranno automaticamente il nuovo ID!

---

## 🧪 TEST CHE TUTTO FUNZIONA

### Test rapido:
```bash
python cognito_config.py
```

Dovrebbe stampare i valori corretti per dev e prod.

### Test con uno script:
```bash
python test-reject-real.py
```

Se logghi correttamente, il config funziona!

---

## 🚨 IN CASO DI EMERGENZA

### Il login non funziona in prod?
1. Verifica che il Client ID sia corretto in AWS Console:
   ```bash
   aws cognito-idp list-user-pool-clients --user-pool-id eu-south-1_iCBtUlJO6 --region eu-south-1
   ```

2. Se il Client ID è diverso da quello in `cognito_config.py`, aggiorna il file!

3. Se il User Pool non esiste, **NON FARE NIENTE** e chiama subito chi ha accesso AWS per capire cosa è successo.

---

## 📞 CHI AGGIORNARE QUANDO CAMBI IL CLIENT ID

1. **Backend Python scripts:** Automaticamente aggiornati (usano tutti `cognito_config.py`)
2. **Frontend Flutter:** Aggiorna `amplifyconfiguration.dart` con il nuovo Client ID
3. **CI/CD Pipelines:** Se hai config Cognito in variabili d'ambiente, aggiornale
4. **Documentazione:** Aggiorna questo README con la nuova data/ID

---

## ✅ CHECKLIST DEPLOY COGNITO

Prima di fare deploy di `infra/core/cognito-setup`:

- [ ] Ho letto questo README
- [ ] Ho capito che il deploy NON crea User Pool nuovi
- [ ] Ho verificato che UserPoolId e UserPoolArn nei parametri sono corretti
- [ ] Ho fatto backup del Client ID attuale (è in `cognito_config.py`)
- [ ] Ho testato in dev prima di andare in prod
- [ ] Ho avvisato il team che farò un deploy su Cognito

---

## 🎯 MORALE DELLA STORIA

**UNA SOLA FONTE DI VERITÀ:** `cognito_config.py`

Se vedi un Client ID hardcoded da qualche parte → **RIMUOVILO** e usa il config!

---

**Ultimo aggiornamento:** 2026-02-18  
**Autore fix definitivo:** GitHub Copilot + Alessandro (dopo un sacco di bestemmie)  
**Mai più problemi:** Si spera 🙏
