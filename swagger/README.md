# Swagger - Aura Battle API

Guida per avviare e usare Swagger UI in locale per testare le API del backend.

## Prerequisiti

- **Docker Desktop** installato e avviato (serve per Swagger UI)
- **Node.js** installato (serve per il proxy di autenticazione)
- **AWS CLI** installato e configurato (`aws configure`) con un utente/profilo che abbia permessi Cognito sull'account `881962383770`, region `eu-south-1`

Il proxy usa l'AWS CLI sotto il cofano per parlare con Cognito (signup, conferma, login) — senza credenziali configurate queste chiamate falliscono.

## 1. Avvia Swagger UI

In un terminale, dalla cartella `swagger/`:

```powershell
.\launch-swagger.ps1
```

Si apre su **http://localhost:8080**.

## 2. Avvia il proxy di autenticazione

In un **secondo** terminale, sempre da `swagger/`:

```powershell
node auth-proxy.js
```

Resta acceso finché lo usi: instrada le chiamate di Swagger verso le vere API AWS e gestisce login/signup con Cognito. Punta **dev-aurabattle** e ascolta su `:8081`.

### Vuoi testare anche PROD? ⚠️

Per lavorare/verificare su produzione (dati e utenti **reali**), avvia un **secondo** proxy in un terzo terminale:

```powershell
$env:ENV = "prod-aurabattle"
node auth-proxy.js
```

Ascolta su `:8082` (porta diversa apposta, così puoi tenere dev e prod aperti insieme senza rischiare di confonderli). Il banner di avvio del proxy ti dice sempre chiaramente quale ambiente stai colpendo.

## 3. Seleziona il server giusto

Apri **http://localhost:8080**, in alto trovi il dropdown "Servers":

```
[DEV] http://localhost:8081 — Local Development (via Auth Proxy)        ← default, usalo per lo sviluppo quotidiano
[PROD] http://localhost:8082 — ⚠️ PRODUZIONE REALE                       ← solo se sai cosa stai facendo
```

Il server selezionato **è** l'ambiente su cui agisci: se scegli `:8082` stai creando/modificando utenti e dati veri. Se per sbaglio selezioni `host.docker.internal:8081` le chiamate falliscono con `NetworkError`, perché quell'indirizzo lo risolve solo Docker, non il browser.

## 4. Rigenera la spec dopo un aggiornamento

Se il backend ti dice che ha aggiunto/modificato endpoint, va ribuildata la spec bundle prima di vederla in UI:

```powershell
npx -y @apidevtools/swagger-cli bundle swagger.yml -o swagger-bundled.yml -t yaml
```

poi ricarica la pagina (o `docker restart swagger-ui-docs-dev` se non si aggiorna da sola).

## 5. Crea un account e testa gli endpoint

1. **POST /auth/signup** — email, password, nome, cognome (lascia `auto_confirm` non impostato: replica il flusso reale, riceverai una mail con un codice)
2. **POST /auth/confirm** — stessa email + codice ricevuto via mail
3. **POST /auth/login/users** — stesse credenziali → copia il valore `idToken` dalla risposta
4. Click sul lucchetto **"Authorize"** in alto a destra → incolla l'`idToken` → Authorize
5. Ora puoi provare `GET/PUT /profile`, `PATCH /settings`, ecc. — il token dura 1 ora, poi rifai il login

> Nota: `auto_confirm: true` in `/auth/signup` esiste solo come scorciatoia per creare velocemente account di test (salta la mail) — nell'app reale questo passaggio non esiste, il flusso è sempre quello dei punti 1-2.
