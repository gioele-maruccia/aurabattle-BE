# Flusso Contratto & Stipendio — Guida FE

> **TL;DR** — `calculate-base-pay` calcola il lordo e **include già il superminimo in `grossBasePay`**.
> Quello stesso valore deve essere mandato invariato nel body di `POST /listings` e `PUT /listings/{id}`.
> Non ricalcolare niente lato frontend.

---

## Indice

1. [I due attori](#1-i-due-attori)
2. [Step 1 — Calcola il lordo (`POST /contracts/calculate-base-pay`)](#2-step-1--calcola-il-lordo)
3. [Step 2 — Crea/aggiorna il listing (`POST` o `PUT /listings`)](#3-step-2--creaaggiorna-il-listing)
4. [La regola d'oro: cosa va in `grossBasePay`](#4-la-regola-doro-cosa-va-in-grossbasepay)
5. [Comportamento per aziende non-FIPE (modalità manuale)](#5-modalità-manuale)
6. [Errori frequenti e come riconoscerli](#6-errori-frequenti)
7. [Cheat-sheet campi obbligatori](#7-cheat-sheet-campi-obbligatori)

---

## 1. I due attori

| Lambda | Endpoint | Quando si chiama |
|--------|----------|-----------------|
| `calculate-base-pay` | `POST /contracts/calculate-base-pay` | Ogni volta che l'utente cambia livello, paragrafo, superminimo o data |
| `create-listing` | `POST /listings` | Alla creazione del listing |
| `update-listing` | `PUT /listings/{listingId}` | Ad ogni modifica del listing |

Il FE **non calcola mai** importi salariali: li ottiene da `calculate-base-pay` e li passa tali e quali ai listing.

---

## 2. Step 1 — Calcola il lordo

### Request

```
POST /contracts/calculate-base-pay
Authorization: Bearer <id_token>
Content-Type: application/json
```

```json
{
  "level": "1",
  "superminimo": 150.00,
  "referenceDate": "2026-04-02"
}
```

| Campo | Tipo | Obbligatorio | Note |
|-------|------|:---:|-------|
| `level` | string | ✅ | `Qa`, `Qb`, `1`–`7`, `6S` |
| `superminimo` | number | ❌ | Se assente o 0 non viene applicato |
| `referenceDate` | string ISO | ❌ | Default = oggi. Usare solo per preview storica |

### Response 200

```json
{
  "message": "Base pay calculated successfully",
  "calculation": {
    "basePay": 1517.61,
    "contingencyAllowance": 536.71,
    "article162Reduction": 0.0,
    "grossBasePay": 2204.32,
    "formula": "1517.61 + 536.71 + 150.00 (superminimo) = 2204.32 €",
    "explanation": "...",
    "estimatedNetSalary": 1690.15
  },
  "companyInfo": {
    "businessName": "Ristorante Da Mario",
    "fipeArticle": "Art. 1, I",
    "paragraph": "I",
    "isSmallBusiness": false,
    "fipeCategory": "pubblici_esercizi"
  },
  "contractInfo": {
    "level": "1",
    "levelName": "Livello 1",
    "ccnlType": "turismo",
    "description": "..."
  },
  "calculationDate": "2026-04-02T00:00:00Z"
}
```

### ⚠️ IMPORTANTE: `grossBasePay` include già il superminimo

```
grossBasePay = basePay + contingencyAllowance - article162Reduction + superminimo
```

Se `superminimo = 150`, il server lo aggiunge internamente e restituisce `grossBasePay = 2204.32`.
Il FE **non deve** fare `grossBasePay + superminimo` da solo.

### Errori possibili

| Status | `error` | Causa | Azione FE |
|--------|---------|-------|-----------|
| 400 | `ManualEntryRequired` | L'azienda non ha FIPE (settore non-turismo) | Mostrare la modalità manuale |
| 400 | `ValidationError` | `level` mancante o `referenceDate` malformata | Fix nel form |
| 404 | `CompanyNotFound` | Nessun profilo azienda per l'utente | Redirect a creazione profilo |
| 404 | `ContractNotFound` | Level non valido | Validi: `Qa`, `Qb`, `1`–`7`, `6S` |

---

## 3. Step 2 — Crea/aggiorna il listing

### Struttura `contract` nel body

Il FE deve copiare i campi della response di `calculate-base-pay` **così come arrivano**, senza modificarli.

```json
{
  "contract": {
    "contractId": "CCNL#turismo#1",
    "ccnlType": "turismo",
    "level": "1",
    "levelName": "Livello 1",
    "description": "...",
    "paragraph": "I",

    "calculation": {
      "basePay": 1517.61,
      "contingencyAllowance": 536.71,
      "article162Reduction": 0.0,
      "grossBasePay": 2204.32,
      "calculationDate": "2026-04-02",
      "formula": "1517.61 + 536.71 + 150.00 (superminimo) = 2204.32 €",
      "explanation": "..."
    },

    "superminimo": {
      "amount": 150.00,
      "currency": "EUR",
      "description": ""
    }
  }
}
```

### Mappatura response → body listing

| Campo nel body | Fonte |
|----------------|-------|
| `contract.calculation.basePay` | `response.calculation.basePay` |
| `contract.calculation.contingencyAllowance` | `response.calculation.contingencyAllowance` |
| `contract.calculation.article162Reduction` | `response.calculation.article162Reduction` |
| `contract.calculation.grossBasePay` | `response.calculation.grossBasePay` ← **già include superminimo** |
| `contract.calculation.formula` | `response.calculation.formula` |
| `contract.calculation.explanation` | `response.calculation.explanation` |
| `contract.calculation.calculationDate` | `response.calculationDate` (solo la parte `YYYY-MM-DD`) |
| `contract.paragraph` | `response.companyInfo.paragraph` |
| `contract.superminimo.amount` | importo inserito dall'utente nel form |
| `contract.contractId` | `"CCNL#turismo#" + livello` |

> **Nota**: `contract.calculation.calculationDate` è solo la data (`"2026-04-02"`), non il datetime con `Z`.

### Regola di validazione lato BE

Il backend ricalcola e verifica:

```
expected = basePay + contingencyAllowance - article162Reduction + superminimo.amount
```

Se `abs(expected - grossBasePay) > 0.01` → risponde `400 Validation Error: Gross base pay calculation mismatch`.

---

## 4. La regola d'oro: cosa va in `grossBasePay`

```
grossBasePay (nel listing) = basePay + contingencyAllowance − article162Reduction + superminimo
```

| Caso | `grossBasePay` da mandare |
|------|--------------------------|
| Solo CCNL, nessun superminimo | `1517.61 + 536.71 = 2054.32` |
| CCNL + superminimo 150 | `1517.61 + 536.71 + 150.00 = 2204.32` |
| CCNL + art.162 (−3.36), nessun superminimo | `1127.75 + 524.94 − 3.36 = 1649.33` |
| CCNL + art.162 (−3.36) + superminimo 100 | `1127.75 + 524.94 − 3.36 + 100.00 = 1749.33` |

In tutti i casi: **usa il valore che restituisce `calculate-base-pay`, non ricalcolarlo**.

---

## 5. Modalità manuale

Se l'azienda non ha `fipeArticle` (settore non-turismo), `calculate-base-pay` risponde `400 ManualEntryRequired`.

In quel caso il listing viene creato in **modalità semplificata**:

- `jobRole` e `contract` possono essere `null`
- `salary` (float) è obbligatorio al loro posto
- La validazione `grossBasePay` non viene applicata

```json
{
  "title": "Barista",
  "salary": 1500.00,
  "jobRole": null,
  "contract": null,
  "category": "food_beverage",
  ...
}
```

---

## 6. Errori frequenti

### `Gross base pay calculation mismatch: expected X, got Y`

**Causa più comune**: il FE ha mandato `grossBasePay = basePay + contingency` ma il superminimo era > 0.

**Fix**: usare sempre il `grossBasePay` dalla response di `calculate-base-pay`, non ricalcolarlo.

---

### `Invalid contractId format. Expected to start with: CCNL#turismo#1`

**Causa**: il `contractId` non segue il formato `CCNL#<ccnlType>#<level>`.

**Fix**:
```dart
final contractId = 'CCNL#turismo#${level}'; // es. "CCNL#turismo#1"
```

---

### `Missing required field: contract.calculation.calculationDate`

**Causa**: il campo `calculationDate` non è presente o è il datetime completo con `Z`.

**Fix**: passare solo `YYYY-MM-DD`:
```dart
final calculationDate = response.calculationDate.substring(0, 10); // "2026-04-02"
```

---

### `Contract 'CCNL#turismo#1' is not active`

**Causa**: il contratto esiste in DynamoDB ma ha `status != 'active'`. Contattare il BE.

---

## 7. Cheat-sheet campi obbligatori

### `POST /listings` e `PUT /listings/{id}` — modalità CCNL

| Campo | Tipo | Note |
|-------|------|------|
| `title` | string | |
| `description` | string | |
| `startDate` | `YYYY-MM-DD` | Max 30 giorni nel passato |
| `endDate` | `YYYY-MM-DD` | Max 2 anni nel futuro |
| `positions` | int | ≥ 1 |
| `category` | string | Da reference table `JobCategories` |
| `status` | string | `draft` \| `published` \| `closed` \| `archived` |
| `jobRole.roleId` | string | |
| `jobRole.roleName` | string | |
| `jobRole.category` | string | |
| `contract.contractId` | string | Formato `CCNL#turismo#<level>` |
| `contract.ccnlType` | string | `turismo` \| `manuale` |
| `contract.level` | string | `Qa`, `Qb`, `1`–`7`, `6S` |
| `contract.levelName` | string | |
| `contract.description` | string | |
| `contract.paragraph` | string | `I` \| `II` |
| `contract.calculation.basePay` | float | Da `calculate-base-pay` |
| `contract.calculation.contingencyAllowance` | float | Da `calculate-base-pay` |
| `contract.calculation.grossBasePay` | float | Da `calculate-base-pay` — **include superminimo** |
| `contract.calculation.calculationDate` | `YYYY-MM-DD` | Da `calculate-base-pay` |
| `location.city` | string | |
| `location.country` | string | |
| `schedule.hoursPerWeek` | int | 1–168 |
| `schedule.workTimeSlots` | array | Vedi struttura sotto |
| `employment.typeId` | string | Da reference table `EmploymentTypes` |
| `employment.contractDuration` | string | |

### Struttura `workTimeSlots`

```json
[
  {
    "type": "single",
    "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "slots": [
      { "start": "09:00", "end": "18:00" }
    ]
  }
]
```

`type`: `single` | `split` | `flexible`

---

*Ultimo aggiornamento: 2026-04-02. In caso di dubbi contattare il BE prima di implementare workaround lato client.*
