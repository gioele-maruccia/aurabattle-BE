# 📱 IMPORTANTE: AGGIORNAMENTO FRONTEND COGNITO

## ⚠️ DEVI CAMBIARE IL CLIENT ID NELL'APP FLUTTER!

Il vecchio Client ID è stato eliminato. Devi aggiornare il frontend con il nuovo.

---

## 🔴 VECCHIO CLIENT ID (NON FUNZIONA PIÙ):
```
20gudbvdh3hesbge0c8od0202b
```

## 🟢 NUOVO CLIENT ID (USA QUESTO):
```
61aa1ldskboni1e18unp49cl57
```

---

## 📝 COSA CAMBIARE NEL CODICE FLUTTER

### File da modificare:
Cerca il file di configurazione Amplify nella tua app Flutter. Di solito si chiama:
- `amplifyconfiguration.dart`  
- `aws-exports.dart`
- o simile

### Cerca questa sezione:
```dart
{
  "auth": {
    "plugins": {
      "awsCognitoAuthPlugin": {
        "CognitoUserPool": {
          "Default": {
            "PoolId": "eu-south-1_iCBtUlJO6",
            "AppClientId": "20gudbvdh3hesbge0c8od0202b",  // ← CAMBIA QUESTO
            "Region": "eu-south-1"
          }
        }
      }
    }
  }
}
```

### Sostituisci con:
```dart
{
  "auth": {
    "plugins": {
      "awsCognitoAuthPlugin": {
        "CognitoUserPool": {
          "Default": {
            "PoolId": "eu-south-1_iCBtUlJO6",          // ← NON cambiare
            "AppClientId": "61aa1ldskboni1e18unp49cl57", // ← NUOVO!
            "Region": "eu-south-1"                      // ← NON cambiare
          }
        }
      }
    }
  }
}
```

---

## ✅ DOPO L'AGGIORNAMENTO

1. **Rebuild l'app Flutter:**
   ```bash
   flutter clean
   flutter pub get
   flutter run
   ```

2. **Testa il login:**
   - Prova a loggarti con un utente esistente
   - Verifica che la registrazione funzioni
   - Controlla che il codice di verifica email non dia errori

3. **Se il login non funziona:**
   - Verifica di aver cambiato il Client ID corretto
   - Controlla che il User Pool ID sia rimasto `eu-south-1_iCBtUlJO6`
   - Prova a fare logout/login
   - Cancella la cache dell'app

---

## 🚀 PER IL DEPLOY

Quando fai il deploy della nuova versione dell'app:

### iOS:
- Incrementa build number
- Testa su TestFlight prima di andare in produzione
- **IMPORTANTE:** Gli utenti già loggati potrebbero dover fare logout/login dopo l'update

### Android:
- Incrementa versionCode
- Testa su Internal Testing
- **IMPORTANTE:** Gli utenti già loggati potrebbero dover fare logout/login dopo l'update

---

## 🔐 INFORMAZIONI COMPLETE COGNITO PROD

Se hai bisogno di altri dettagli:

### User Pool:
- **ID:** `eu-south-1_iCBtUlJO6`
- **Nome:** `prod-BeezeyUserPool`
- **Region:** `eu-south-1`
- **ARN:** `arn:aws:cognito-idp:eu-south-1:881962383770:userpool/eu-south-1_iCBtUlJO6`

### App Client:
- **ID:** `61aa1ldskboni1e18unp49cl57`
- **Nome:** `prod-BeezeyUserPoolClient`  
- **Creato:** 2026-02-18 11:19:02
- **Auth Flows:** USER_SRP_AUTH, REFRESH_TOKEN_AUTH, USER_PASSWORD_AUTH
- **Secret:** Nessuno (public client)

---

## 📞 IN CASO DI PROBLEMI

Se dopo l'aggiornamento qualcosa non funziona:

1. Controlla i log dell'app per errori Cognito
2. Verifica che il Client ID sia stato cambiato correttamente
3. Prova a cancellare completamente l'app e reinstallarla
4. Controlla che il backend backend-BE stia usando gli stessi ID (ora usa `cognito_config.py`)

---

## 🎯 NOTA IMPORTANTE

**User Pool ID NON È CAMBIATO!**  
Solo il Client ID è nuovo. Questo significa che:
- ✅ Tutti gli utenti esistenti sono ancora lì
- ✅ Le password funzionano ancora
- ✅ I gruppi (admins, companies, workers) sono intatti
- ✅ I token vecchi potrebbero non funzionare (logout/login risolve)

---

**Aggiornato:** 2026-02-18  
**Nuovo Client ID:** `61aa1ldskboni1e18unp49cl57`  
**Backend già aggiornato:** ✅ SÌ

---

---

# 📱 AGGIORNAMENTO RICHIESTO: calculate-net-salary

**Data:** 2026-03-30  
**Priorità:** ALTA — il calcolo senza questa fix non include il superminimo

## Il problema

Il FE chiama `calculate-net-salary` passando il lordo estratto dalla risposta listing:

```dart
// ❌ VECCHIO — leggeva solo basePay, superminimo ignorato
final body = {
  "userId": userId,
  "monthlyGrossSalary": listing.compensation.basePay,  // es. 1543.86 — MANCA superminimo!
  "startDate": startDate,
  "endDate": endDate,
};
```

Il risultato è **sbagliato** perché il superminimo (es. €300) non viene incluso nel calcolo.

## La fix

Il FE ha già il `listingId` dalla response precedente. Passalo direttamente — il backend legge `grossBasePay + superminimo` da DynamoDB da solo:

```dart
// ✅ NUOVO — passa solo jobListingId, il backend fa tutto
final body = {
  "userId": userId,
  "jobListingId": listing.listingId,   // ← unica modifica necessaria
  "startDate": startDate,
  "endDate": endDate,
  // monthlyGrossSalary NON serve più
};
```

## Endpoint

- **DEV:** `https://abala746ia.execute-api.eu-south-1.amazonaws.com/dev/v1/bookings/calculate-net-salary`
- **PROD:** `https://abala746ia.execute-api.eu-south-1.amazonaws.com/prod/v1/bookings/calculate-net-salary`  
  ⚠️ PROD non ancora aggiornato — deploy pendente.

## Fallback temporaneo (se non è possibile aggiornare subito)

Se vuoi mantenere la vecchia chiamata nel frattempo, usa `compensation.totalMonthly` (che include già superminimo) invece di `compensation.basePay`:

```dart
// ⚠️ TEMPORANEO — usa totalMonthly che include già il superminimo
final body = {
  "userId": userId,
  "monthlyGrossSalary": listing.compensation.totalMonthly,  // es. 1843.86 (basePay + superminimo)
  "startDate": startDate,
  "endDate": endDate,
};
```

## Campi disponibili nella response GET /listings/{id}

```json
"compensation": {
  "basePay": 1543.86,        ← lordo base senza superminimo (NON usare questo da solo)
  "superminimo": 300.0,      ← superminimo
  "totalMonthly": 1843.86,   ← basePay + superminimo (usare questo se fallback)
  "currency": "EUR"
},
"listingId": "27716f6a-..."  ← passare questo all'endpoint (soluzione preferita)
```
