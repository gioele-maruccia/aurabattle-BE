# Test Events per SAM Local

Questa directory contiene eventi di test per testare le Lambda localmente con `sam local invoke`.

## Eventi disponibili

### test-get-my-listings.json
Simula una richiesta GET a `/listings/my` da parte di un'azienda autenticata.

**Campi da personalizzare:**
- `requestContext.authorizer.claims.sub` - L'ID utente Cognito dell'azienda
- `queryStringParameters` - Opzionale: filtri come `status`, `limit`, ecc.

## Come usare

### Metodo 1: Script PowerShell (consigliato)
```powershell
cd .\infra\services\job-listings\
.\test-local.ps1 -Function GetMyListingsFunction -Event events\test-get-my-listings.json
```

### Metodo 2: SAM CLI diretto
```powershell
sam local invoke GetMyListingsFunction `
    --event events\test-get-my-listings.json `
    --template template.yaml `
    --region eu-south-1 `
    --parameter-overrides "Environment=dev CognitoUserPoolArn=arn:aws:cognito-idp:eu-south-1:123456789012:userpool/test"
```

### Metodo 3: Start API locale (test completo API Gateway)
```powershell
# Avvia API Gateway locale sulla porta 3000
sam local start-api --region eu-south-1 --parameter-overrides "Environment=dev CognitoUserPoolArn=arn:aws:cognito-idp:eu-south-1:123456789012:userpool/test"

# In un altro terminale, testa l'API
curl http://localhost:3000/listings/my -H "Authorization: Bearer token"
```

## Note importanti

1. **Accesso DynamoDB**: SAM local usa le tue credenziali AWS reali per accedere alle tabelle DynamoDB. Assicurati di:
   - Avere le credenziali AWS configurate (`aws configure`)
   - Avere accesso alle tabelle dell'ambiente specificato (dev/prod)

2. **Modifica userId**: Cambia il `sub` nell'evento con un userId reale del tuo ambiente per vedere dati reali

3. **Docker**: SAM local richiede Docker in esecuzione per creare il container Lambda

## Testing senza AWS (Unit Test)

Se vuoi testare solo la logica senza accesso AWS:
```powershell
cd ..\..\..\..\src\lambdas\services\job-listings\get-my-listings\
python -m pytest test_app.py -v
```
