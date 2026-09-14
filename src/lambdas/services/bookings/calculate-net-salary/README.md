# Calculate Net Salary Lambda

Calcola lo stipendio netto per un worker basandosi sui giorni lavorati, considerando tutte le trattenute fiscali italiane per RAL < €15.000.

## 🎯 Scopo

Questa Lambda viene chiamata dal frontend quando un worker seleziona le date per un booking, per mostrare:
- Stipendio lordo proporzionato ai giorni lavorati
- Stipendio netto stimato (dopo trattenute)
- Dettaglio completo di tutte le trattenute fiscali

## 📊 Input

**Metodo preferito** — il backend legge il lordo dal job listing:
```json
{
  "userId": "cognito-sub-abc123",
  "jobListingId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "startDate": "2025-06-01",
  "endDate": "2025-12-31"
}
```

**Fallback** (retrocompatibilità, se jobListingId non è disponibile):
```json
{
  "userId": "cognito-sub-abc123",
  "monthlyGrossSalary": 1400.00,
  "superminimo": 100.00,
  "daysWorked": 182
}
```

Il lordo mensile usato per il calcolo è sempre:
`totalMonthlyGross = grossBasePay + superminimo`

> Con `jobListingId`: entrambi i valori vengono letti dal DynamoDB `JobListings`.
> Senza: `monthlyGrossSalary` = grossBasePay, `superminimo` = superminimo (default 0).

## 📤 Output

```json
{
  "grossSalaryForPeriod": 750.00,
  "netSalaryForPeriod": 623.45,
  "daysWorked": 15,
  "daysInMonth": 30,
  "annualGrossEstimate": 18000.00,
  "deductions": {
    "irpef": { ... },
    "inps": { ... },
    "addizionaleRegionale": { ... },
    "addizionaleComunale": { ... },
    "total": 140.41
  },
  "deductionPercentage": 18.72,
  "location": {
    "province": "MI",
    "city": "Milano"
  }
}
```

## 🔧 Trattenute Calcolate

1. **IRPEF** (23% con detrazione €1.880)
2. **INPS** (9,19%)
3. **Addizionale Regionale** (varia per regione: 1,23% - 2,33%)
4. **Addizionale Comunale** (varia per comune: 0,3% - 0,9%)

## 📍 Dati Fiscali

I dati fiscali sono caricati da `italian_tax_data.json` che contiene:
- Aliquote IRPEF e detrazioni
- Contributi INPS
- Addizionali regionali per tutte le 21 regioni/province autonome
- Addizionali comunali per tutti i 107 capoluoghi di provincia
- Medie provinciali come fallback

## 💾 Dipendenze

- **DynamoDB Table**: `UserProfiles` (lettura della residenza utente)
- **DynamoDB Table**: `JobListings` (lettura grossBasePay + superminimo quando si passa `jobListingId`)
- **DynamoDB Table**: `TaxCache` (cache addizionali comunali — legacy, mantenuto)
- **File**: `italian_tax_data.json` (dati fiscali: IRPEF, INPS, addizionali regionali/comunali)
- **Env vars**: `USER_PROFILES_TABLE`, `JOB_LISTINGS_TABLE_NAME`, `TAX_CACHE_TABLE`

## 🧪 Testing

### Test Locale MEF Fetcher
```bash
# Test diretto del fetcher MEF (senza Lambda)
cd src/lambdas/services/bookings/calculate-net-salary
python test_mef_fetcher.py
```

Questo script testa il fetching da vari comuni e salva gli HTML per debug.

### Test Lambda Completa
```bash
# Test con comuni random da diverse province
.\scripts\bookings\test-mef-comuni-random.ps1
```

Questo script:
- Testa 10 comuni casuali
- Mostra quale data source è stato usato (MEF/cache/local)
- Fornisce link per verifica manuale sul sito MEF

## 🚀 Deploy

```bash
sam build
sam deploy --guided
```

## 📝 Note

- Calcolo ottimizzato per **RAL < €15.000**
- Usa la **città specifica** se disponibile, altrimenti la **media provinciale**
- Include disclaimer che il calcolo è una stima

## 📚 Documentazione Completa

Vedi: `docs/02_architecture/CALCULATE_NET_SALARY.md`
