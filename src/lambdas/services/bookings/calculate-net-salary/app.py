"""
Lambda: Calculate Net Salary
Calcola lo stipendio netto per un worker basandosi su:
- Stipendio lordo mensile del job listing
- Numero di giorni lavorati
- RAL < 15.000 euro
- Addizionali regionali e comunali basate sulla residenza dell'utente
"""

import os
import json
import boto3
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

dynamodb = boto3.resource('dynamodb')
user_table_name = os.environ.get('USER_PROFILES_TABLE', 'dev-UserProfiles')
user_profiles_table = dynamodb.Table(user_table_name)
job_listings_table = dynamodb.Table(os.environ.get('JOB_LISTINGS_TABLE_NAME', 'dev-JobListings'))

# Nota: il DynamoDB TaxCache non è più usato a runtime.
# Le addizionali vengono lette esclusivamente da italian_tax_data.json
# (aggiornato ogni anno a febbraio via scripts/aggiorna-addizionali.py).

# Carica i dati fiscali italiani
# In produzione, questi dati potrebbero essere caricati da S3 o da un altro servizio
TAX_DATA_PATH = os.path.join(os.path.dirname(__file__), 'italian_tax_data.json')

def load_tax_data() -> Dict:
    """Carica i dati fiscali dal file JSON"""
    try:
        with open(TAX_DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # Se il file non esiste localmente, usa dati hardcoded
        # In produzione, questi dati dovrebbero essere in S3 o DynamoDB
        print("[WARNING] Tax data file not found, using minimal hardcoded data")
        return {
            "irpef": {"aliquota": 0.23, "detrazioniLavoroDipendente": {"importoBase": 1880}},
            "contributiInps": {"aliquota": 0.0919},
            "addizionaliRegionali": {},
            "addizionaliComunali": {},
            "mappingProvinceToRegion": {}
        }


def parse_iso_date(date_value: str) -> datetime:
    """Parse ISO-8601 date/datetime string into datetime."""
    if not date_value or not isinstance(date_value, str):
        raise ValueError("Invalid date value")
    return datetime.fromisoformat(date_value.replace('Z', '+00:00'))


def get_user_location(user_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Recupera provincia e città dall'utente
    Returns: (provincia, city)
    """
    try:
        response = user_profiles_table.get_item(Key={'user_id': user_id})
        
        if 'Item' not in response:
            print(f"[ERROR] User {user_id} not found in UserProfiles")
            return None, None
        
        user = response['Item']
        address = user.get('address', {})
        
        province = address.get('province', '')
        city = address.get('city', '')
        
        return province.upper() if province else None, city
        
    except Exception as e:
        print(f"[ERROR] Failed to get user location: {str(e)}")
        return None, None


def resolve_location(city: Optional[str], province_hint: Optional[str], tax_data: Dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Ricava la sigla provincia canonica e il nome regione a partire dalla città inserita
    dall'utente, usando province_hint solo come fallback.

    Strategia (in ordine di priorità):
      1. Cerca la città in tutti i comuni del JSON → se trovata estrae sigla + regione
      2. Se province_hint è già una sigla valida nel JSON → usala direttamente
      3. Se province_hint è un nome di provincia (es. 'Lecce') → convertilo in sigla
      4. Se province_hint è un nome di regione (es. 'Puglia') → usa l'aliquota regionale
      5. Fallback: (None, None)

    Returns:
        (sigla_provincia, nome_regione) — entrambi canonici come chiavi nel JSON
    """
    addiz_com = tax_data.get('addizionaliComunali', {})
    mapping = tax_data.get('mappingProvinceToRegion', {})
    addiz_reg = tax_data.get('addizionaliRegionali', {})

    # --- STEP 1: ricerca dalla città (massima affidabilità) ---
    if city:
        city_norm = city.strip().upper()
        for sigla, pd in addiz_com.items():
            for nome in pd.get('comuni', {}):
                if nome.upper() == city_norm:
                    regione = mapping.get(sigla)
                    print(f"[LOC] '{city}' trovata in prov. {sigla} → regione {regione}")
                    return sigla, regione

    # --- STEP 2/3: prova province_hint come sigla o nome di provincia ---
    if province_hint:
        hint_up = province_hint.upper().strip()

        # Sigla diretta (2 car. alfa) presente nel JSON
        if len(hint_up) == 2 and hint_up.isalpha() and hint_up in addiz_com:
            regione = mapping.get(hint_up)
            print(f"[LOC] Sigla '{hint_up}' valida → regione {regione}")
            return hint_up, regione

        # Nome provincia → sigla tramite mapping statico
        prov_name_map = {
            'AGRIGENTO': 'AG', 'ALESSANDRIA': 'AL', 'ANCONA': 'AN', 'AOSTA': 'AO',
            'AREZZO': 'AR', 'ASCOLI PICENO': 'AP', 'ASTI': 'AT', 'AVELLINO': 'AV',
            'BARI': 'BA', 'BELLUNO': 'BL', 'BENEVENTO': 'BN', 'BERGAMO': 'BG',
            'BIELLA': 'BI', 'BOLOGNA': 'BO', 'BOLZANO': 'BZ', 'BRESCIA': 'BS',
            'BRINDISI': 'BR', 'CAGLIARI': 'CA', 'CALTANISSETTA': 'CL', 'CAMPOBASSO': 'CB',
            'CASERTA': 'CE', 'CATANIA': 'CT', 'CATANZARO': 'CZ', 'CHIETI': 'CH',
            'COMO': 'CO', 'COSENZA': 'CS', 'CREMONA': 'CR', 'CROTONE': 'KR',
            'CUNEO': 'CN', 'ENNA': 'EN', 'FERMO': 'FM', 'FERRARA': 'FE',
            'FIRENZE': 'FI', 'FOGGIA': 'FG', 'FORLI CESENA': 'FC', 'FORLÌ-CESENA': 'FC',
            'FROSINONE': 'FR', 'GENOVA': 'GE', 'GORIZIA': 'GO', 'GROSSETO': 'GR',
            'IMPERIA': 'IM', 'ISERNIA': 'IS', 'L AQUILA': 'AQ', "L'AQUILA": 'AQ',
            'LA SPEZIA': 'SP', 'LATINA': 'LT', 'LECCE': 'LE', 'LECCO': 'LC',
            'LIVORNO': 'LI', 'LODI': 'LO', 'LUCCA': 'LU', 'MACERATA': 'MC',
            'MANTOVA': 'MN', 'MASSA CARRARA': 'MS', 'MATERA': 'MT', 'MESSINA': 'ME',
            'MILANO': 'MI', 'MODENA': 'MO', 'MONZA E BRIANZA': 'MB', 'MONZA BRIANZA': 'MB',
            'NAPOLI': 'NA', 'NOVARA': 'NO', 'NUORO': 'NU', 'ORISTANO': 'OR',
            'PADOVA': 'PD', 'PALERMO': 'PA', 'PARMA': 'PR', 'PAVIA': 'PV',
            'PERUGIA': 'PG', 'PESARO E URBINO': 'PU', 'PESARO URBINO': 'PU',
            'PESCARA': 'PE', 'PIACENZA': 'PC', 'PISA': 'PI', 'PISTOIA': 'PT',
            'PORDENONE': 'PN', 'POTENZA': 'PZ', 'PRATO': 'PO', 'RAGUSA': 'RG',
            'RAVENNA': 'RA', 'REGGIO CALABRIA': 'RC', 'REGGIO EMILIA': 'RE',
            'RIETI': 'RI', 'RIMINI': 'RN', 'ROMA': 'RM', 'ROVIGO': 'RO',
            'SALERNO': 'SA', 'SASSARI': 'SS', 'SAVONA': 'SV', 'SIENA': 'SI',
            'SIRACUSA': 'SR', 'SONDRIO': 'SO', 'SUD SARDEGNA': 'SU', 'TARANTO': 'TA',
            'TERAMO': 'TE', 'TERNI': 'TR', 'TORINO': 'TO', 'TRAPANI': 'TP',
            'TRENTO': 'TN', 'TREVISO': 'TV', 'TRIESTE': 'TS', 'UDINE': 'UD',
            'VARESE': 'VA', 'VENEZIA': 'VE', 'VERBANO CUSIO OSSOLA': 'VB',
            'VERCELLI': 'VC', 'VERONA': 'VR', 'VIBO VALENTIA': 'VV',
            'VICENZA': 'VI', 'VITERBO': 'VT',
        }
        sigla = prov_name_map.get(hint_up)
        if sigla and sigla in addiz_com:
            regione = mapping.get(sigla)
            print(f"[LOC] Nome provincia '{province_hint}' → sigla {sigla} → regione {regione}")
            return sigla, regione

        # --- STEP 4: province_hint è un nome di regione ---
        for nome_regione in addiz_reg:
            if nome_regione.upper() == hint_up:
                # La sigla non è recuperabile senza la città, ma la regione è nota
                print(f"[LOC] '{province_hint}' è un nome di regione: {nome_regione} (sigla provincia sconosciuta)")
                return None, nome_regione

    print(f"[LOC] Impossibile risolvere: city={city!r} province_hint={province_hint!r}")
    return None, None


def get_addizionale_regionale(nome_regione: Optional[str], tax_data: Dict) -> Tuple[float, str]:
    """
    Legge l'addizionale regionale dal JSON tramite nome regione canonico.
    Ritorna (aliquota, nome_regione).
    """
    if not nome_regione:
        return 0.0, ''
    aliquota = (
        tax_data.get('addizionaliRegionali', {})
        .get(nome_regione, {})
        .get('aliquota', 0.0)
    )
    return aliquota, nome_regione


def get_addizionale_comunale(city: Optional[str], sigla_provincia: Optional[str], tax_data: Dict) -> Tuple[float, str]:
    """
    Legge l'addizionale comunale dal JSON tramite sigla provincia canonica.
    Priorità: città esatta → media provinciale → 0.
    Ritorna (aliquota, fonte).
    """
    if not sigla_provincia:
        return 0.0, 'provincia non risolta'

    prov_data = tax_data.get('addizionaliComunali', {}).get(sigla_provincia)
    if not prov_data:
        return 0.0, f'provincia {sigla_provincia} non in JSON'

    if city:
        city_norm = city.strip().upper()
        for nome, aliquota in prov_data.get('comuni', {}).items():
            if nome.upper() == city_norm:
                return aliquota, f'{nome} (comune esatto)'

    media = prov_data.get('mediaProvinciale', 0.008)
    return media, f'media provinciale {sigla_provincia}'


def get_gross_from_listing(listing_id: str) -> Tuple[float, float]:
    """
    Recupera gross_base_pay e superminimo dal job listing in DynamoDB.
    Returns: (gross_base_pay, superminimo_amount)
    Raises: ValueError se il listing non esiste.
    """
    try:
        response = job_listings_table.get_item(Key={'listingId': listing_id})
        if 'Item' not in response:
            raise ValueError(f"Job listing '{listing_id}' not found")

        listing = response['Item']
        contract = listing.get('contract')

        if not contract:
            # Listing manuale: usa il campo salary
            salary = float(listing.get('salary', 0))
            return salary, 0.0

        # Listing CCNL: grossBasePay + superminimo
        calculation = contract.get('calculation') or {}
        gross_base_pay = float(calculation.get('grossBasePay', 0))

        superminimo = contract.get('superminimo') or {}
        superminimo_amount = float(superminimo.get('amount', 0))

        return gross_base_pay, superminimo_amount

    except ValueError:
        raise
    except Exception as e:
        print(f"[ERROR] Failed to get listing gross for '{listing_id}': {str(e)}")
        raise


def calculate_net_salary(monthly_gross, days_worked, days_in_month, province, city, tax_data):
    """
    Calcola lo stipendio netto totale per l'intera esperienza lavorativa
    
    Args:
        monthly_gross: Stipendio lordo mensile
        days_worked: Numero totale di giorni lavorati (può essere > 30)
        days_in_month: Parametro deprecato, mantenuto per retrocompatibilità (non più usato)
        province: Provincia di residenza (es: 'MI', 'RM' o 'MILANO', 'ROMA')
        city: Città di residenza
        tax_data: Dati fiscali caricati dal JSON
    
    Returns:
        Dictionary con il dettaglio del calcolo per il periodo totale
    """
    
    # Risolvi provincia e regione partendo dalla città (gestisce dati errati nel profilo)
    sigla_provincia, nome_regione = resolve_location(city, province, tax_data)

    # Normalizza il nome città per i lookup successivi
    city = city.upper().strip() if city else None
    
    # Calcola mesi equivalenti (convenzione: 1 mese = 30 giorni)
    months_worked = days_worked / 30.0
    
    # Calcola lo stipendio lordo totale per l'intero periodo
    gross_for_period = monthly_gross * months_worked
    
    # Calcola la RAL annuale stimata (assumendo 12 mensilità)
    # Per RAL < 15.000 usiamo questo come riferimento
    annual_gross = monthly_gross * 12
    
    # 1. IRPEF (23% per RAL < 15.000)
    irpef_rate = tax_data['irpef']['aliquota']
    irpef_annual = annual_gross * irpef_rate
    
    # Detrazione lavoro dipendente (€1.880 per RAL <= 15.000)
    detrazione_lavoro = tax_data['irpef']['detrazioniLavoroDipendente']['importoBase']
    
    # IRPEF netta annuale
    irpef_net_annual = max(0, irpef_annual - detrazione_lavoro)
    
    # Aliquota IRPEF effettiva (usata per TFR e tredicesima)
    effective_irpef_rate = irpef_net_annual / annual_gross if annual_gross > 0 else 0.0
    
    # IRPEF mensile
    irpef_monthly = irpef_net_annual / 12
    
    # IRPEF per il periodo totale
    irpef_for_period = irpef_monthly * months_worked
    
    # 2. Contributi INPS (9.19%)
    inps_rate = tax_data['contributiInps']['aliquota']
    inps_for_period = gross_for_period * inps_rate

    # 3. Addizionale regionale (offline, da JSON)
    addiz_reg_rate, regione_nome = get_addizionale_regionale(nome_regione, tax_data)
    addiz_reg_annual = annual_gross * addiz_reg_rate
    addiz_reg_monthly = addiz_reg_annual / 12
    addiz_reg_for_period = addiz_reg_monthly * months_worked

    # 4. Addizionale comunale (offline, da JSON)
    addiz_com_rate, addiz_com_fonte = get_addizionale_comunale(city, sigla_provincia, tax_data)
    addiz_com_annual = annual_gross * addiz_com_rate
    addiz_com_monthly = addiz_com_annual / 12
    addiz_com_for_period = addiz_com_monthly * months_worked

    # Totale trattenute (IRPEF + INPS + addizionali)
    total_deductions = irpef_for_period + inps_for_period + addiz_reg_for_period + addiz_com_for_period

    # Stipendio netto
    net_salary = gross_for_period - total_deductions

    # Percentuale totale di trattenute
    deduction_percentage = (total_deductions / gross_for_period * 100) if gross_for_period > 0 else 0
    
    # --- TFR (Trattamento di Fine Rapporto) ---
    # Quota mensile = stipendio mensile lordo / 13.5 (formula legale italiana)
    tfr_monthly_accrual = monthly_gross / 13.5
    tfr_gross_for_period = tfr_monthly_accrual * months_worked
    # Il TFR è soggetto a tassazione separata: si applica l'aliquota IRPEF effettiva
    # (non sono dovuti contributi INPS sulla quota liquidata al lavoratore)
    tfr_irpef_amount = tfr_gross_for_period * effective_irpef_rate
    tfr_net_for_period = tfr_gross_for_period - tfr_irpef_amount
    
    # --- Tredicesima mensilità ---
    # Pari a 1 mensilità lorda per anno, proporzionale ai mesi lavorati
    tredicesima_gross_for_period = monthly_gross * (months_worked / 12.0)
    # Soggetta a IRPEF (aliquota effettiva) e contributi INPS, come la retribuzione ordinaria
    tredicesima_inps_amount = tredicesima_gross_for_period * inps_rate
    tredicesima_irpef_amount = tredicesima_gross_for_period * effective_irpef_rate
    tredicesima_net_for_period = tredicesima_gross_for_period - tredicesima_inps_amount - tredicesima_irpef_amount
    
    return {
        # --- Retribuzione nel periodo selezionato ---
        'monthlyGross': round(monthly_gross, 2),
        'monthsWorked': round(months_worked, 4),
        'grossSalaryForPeriod': round(gross_for_period, 2),
        'netSalaryForPeriod': round(net_salary, 2),
        'daysWorked': days_worked,
        'daysInMonth': days_in_month,
        'annualGrossEstimate': round(annual_gross, 2),
        
        # --- TFR maturato nel periodo ---
        'tfrForPeriod': {
            'grossAmount': round(tfr_gross_for_period, 2),
            'netAmount': round(tfr_net_for_period, 2),
            'monthlyAccrual': round(tfr_monthly_accrual, 2),
            'irpefAmount': round(tfr_irpef_amount, 2),
            'effectiveIrpefRatePct': round(effective_irpef_rate * 100, 4),
            'description': 'TFR maturato nel periodo (tassazione separata, no INPS alla liquidazione)',
            'note': "Stima con aliquota IRPEF effettiva. Il TFR reale dipende da rivalutazione annua e anticipi."
        },
        
        # --- Tredicesima maturata nel periodo ---
        'tredicesima': {
            'grossAmount': round(tredicesima_gross_for_period, 2),
            'netAmount': round(tredicesima_net_for_period, 2),
            'inpsAmount': round(tredicesima_inps_amount, 2),
            'irpefAmount': round(tredicesima_irpef_amount, 2),
            'effectiveIrpefRatePct': round(effective_irpef_rate * 100, 4),
            'description': 'Tredicesima mensilità maturata nel periodo (soggetta a IRPEF e INPS)'
        },
        
        # --- Trattenute sulla retribuzione ordinaria ---
        'deductions': {
            'irpef': {
                'amount': round(irpef_for_period, 2),
                'rate': irpef_rate,
                'effectiveRatePct': round(effective_irpef_rate * 100, 4),
                'description': 'IRPEF (23% con detrazione lavoro dipendente)'
            },
            'inps': {
                'amount': round(inps_for_period, 2),
                'rate': inps_rate,
                'description': 'Contributi previdenziali INPS'
            },
            'addizionaleRegionale': {
                'amount': round(addiz_reg_for_period, 2),
                'rate': addiz_reg_rate,
                'regione': regione_nome,
                'description': f'Addizionale regionale IRPEF – {regione_nome}'
            } if addiz_reg_rate > 0 else None,
            'addizionaleComunale': {
                'amount': round(addiz_com_for_period, 2),
                'rate': addiz_com_rate,
                'fonte': addiz_com_fonte,
                'description': f'Addizionale comunale IRPEF ({addiz_com_fonte})'
            } if addiz_com_rate > 0 else None,
            'total': round(total_deductions, 2)
        },
        'deductionPercentage': round(deduction_percentage, 2),
        'disclaimer': (
            'Calcolo stimato per il periodo selezionato (1 mese = 30 giorni). '
            'Include IRPEF (con detrazione lavoro dipendente), contributi INPS, '
            'addizionale regionale e comunale basate sulla residenza. '
            'Il calcolo effettivo potrebbe variare in base a situazioni individuali.'
        )
    }


def lambda_handler(event, context):
    """
    Handler della Lambda - Calcola stipendio netto totale per l'intera esperienza

    Expected input (POST body) — metodo preferito:
    {
        "userId": "cognito-sub-123",
        "jobListingId": "listing-uuid-123",  // Il backend recupera gross + superminimo dal listing
        "daysWorked": 182,                   // Total days - can be any value > 0
        "daysInMonth": 30,                   // DEPRECATED - no longer used
        "startDate": "2025-06-01",          // optional, used to derive daysWorked
        "endDate": "2025-12-31"             // optional, used to derive daysWorked
    }

    Fallback (retrocompatibilità, se jobListingId non è disponibile):
    {
        "userId": "cognito-sub-123",
        "monthlyGrossSalary": 1400.00,  // Paga base + indennità di contingenza
        "superminimo": 100.00,          // Superminimo individuale (opzionale, default 0)
        ...
    }
    
    Returns:
    {
        "body": {
            "monthlyGross": 1500.00,           // Stipendio lordo mensile
            "monthsWorked": 6.0333,            // Mesi equivalenti lavorati
            "grossSalaryForPeriod": 9100.00,   // Lordo totale per il periodo
            "netSalaryForPeriod": 7800.00,     // Netto totale per il periodo (dopo IRPEF, INPS, addizionali)
            "tfrForPeriod": {
                "grossAmount": 672.22,          // TFR lordo maturato nel periodo
                "netAmount": 620.00,            // TFR netto (tassazione separata, no INPS)
                "monthlyAccrual": 111.11,       // Quota TFR mensile
                "irpefAmount": 52.22,           // IRPEF sul TFR
                "effectiveIrpefRatePct": 7.76, // Aliquota effettiva %
                "description": "...",
                "note": "..."
            },
            "tredicesima": {
                "grossAmount": 750.00,          // Tredicesima lorda maturata
                "netAmount": 610.00,            // Tredicesima netta
                "inpsAmount": 68.93,            // INPS sulla tredicesima
                "irpefAmount": 58.22,           // IRPEF sulla tredicesima
                "effectiveIrpefRatePct": 7.76, // Aliquota effettiva %
                "description": "..."
            },
            "deductions": {...},
            ...
        }
    }
    """
    
    try:
        # Parse body
        body = json.loads(event.get('body', '{}'))

        # Valida input
        user_id = body.get('userId')
        job_listing_id = body.get('jobListingId')
        days_worked = body.get('daysWorked')
        days_in_month = body.get('daysInMonth', 30)
        start_date = body.get('startDate')
        end_date = body.get('endDate')
        derived_from_dates = False

        if not user_id:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'code': 4050, 'error': 'Bad Request', 'message': 'Missing required field: userId'})
            }

        # --- Recupera il lordo mensile ---
        if job_listing_id:
            # Percorso preferito: fetch dal job listing in DynamoDB
            try:
                monthly_gross, superminimo = get_gross_from_listing(job_listing_id)
            except ValueError as e:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({'code': 4054, 'error': 'Bad Request', 'message': str(e)})
                }
        else:
            # Fallback: valori espliciti dal client (retrocompatibilità)
            monthly_gross_raw = body.get('monthlyGrossSalary')
            if not monthly_gross_raw or float(monthly_gross_raw) <= 0:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({'code': 4053, 'error': 'Bad Request', 'message': 'Provide jobListingId or a valid monthlyGrossSalary'})
                }
            monthly_gross = float(monthly_gross_raw)
            superminimo = float(body.get('superminimo') or 0)

        total_monthly_gross = monthly_gross + superminimo

        if total_monthly_gross <= 0:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'code': 4053, 'error': 'Bad Request', 'message': 'Invalid salary: total monthly gross must be > 0'})
            }

        if (not days_worked or days_worked <= 0) and start_date and end_date:
            try:
                start_dt = parse_iso_date(start_date)
                end_dt = parse_iso_date(end_date)
            except ValueError as e:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({
                        'code': 4051,
                        'error': 'Bad Request',
                        'message': f'Invalid date format: {str(e)}'
                    })
                }

            if end_dt < start_dt:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                    'body': json.dumps({
                        'code': 4052,
                        'error': 'Bad Request',
                        'message': 'endDate must be after startDate'
                    })
                }

            days_worked = (end_dt.date() - start_dt.date()).days + 1
            derived_from_dates = True

        if not days_worked or days_worked <= 0:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'code': 4050,
                    'error': 'Bad Request',
                    'message': 'Invalid daysWorked: must be > 0'
                })
            }
        
        # Carica dati fiscali
        tax_data = load_tax_data()
        
        # Recupera la provincia e città dell'utente
        province, city = get_user_location(user_id)
        
        if not province:
            print(f"[WARNING] Province not found for user {user_id}, calculations without regional/municipal tax")
        
        # Calcola lo stipendio netto (paga base + indennità + superminimo)
        result = calculate_net_salary(
            monthly_gross=total_monthly_gross,
            days_worked=int(days_worked),
            days_in_month=int(days_in_month),
            province=province,
            city=city,
            tax_data=tax_data
        )
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(result)
        }
        
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 4050,
                'error': 'Bad Request',
                'message': 'Invalid JSON in request body'
            })
        }
    
    except Exception as e:
        print(f"[ERROR] Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'code': 5014,
                'error': 'Internal Server Error',
                'message': str(e)
            })
        }
