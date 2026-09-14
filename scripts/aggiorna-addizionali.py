#!/usr/bin/env python3
"""
Script di aggiornamento annuale – Addizionali IRPEF Comunali e Regionali
=========================================================================
Da eseguire ogni anno a FEBBRAIO, quando il MEF pubblica i dati aggiornati.

Il risultato viene scritto in:
  src/lambdas/services/bookings/calculate-net-salary/italian_tax_data.json

La lambda calculate-net-salary usa solo i dati JSON (nessuna chiamata HTTP
a runtime), eliminando rischi di parsing HTML e velocizzando la risposta.

Uso:
    python scripts/aggiorna-addizionali.py                  # anno corrente
    python scripts/aggiorna-addizionali.py --anno 2027      # anno specifico
    python scripts/aggiorna-addizionali.py --dry-run        # solo stampa, non scrive
    python scripts/aggiorna-addizionali.py --only-regionali # solo regioni (rapido)
    python scripts/aggiorna-addizionali.py --istat-only-fallback  # lista embedded

Dipendenze (solo per questo script, non per la lambda):
    pip install requests beautifulsoup4 lxml

NOTA MEF (aggiornamento 2026):
    Il sito MEF per le addizionali comunali (www1.finanze.gov.it e finanze.gov.it)
    è protetto da Akamai WAF che blocca le richieste da script Python con 403/404.
    
    Quando il fetch MEF fallisce, lo script preserva automaticamente i dati
    esistenti nel JSON (comuni già presenti), aggiornando solo taxYear e
    _lastUpdated. Le aliquote comunali italiane cambiano raramente.

    Fonti alternative per aggiornamento manuale:
      - MEF Federalismo Fiscale (area riservata):
        https://www.finanze.gov.it/.galleries/link_siti_esterni/FederalismoFiscale.ext
      - Open Data comunale MEF:
        https://www.finanze.gov.it/.galleries/link_Esterni_Applicazioni/OpenDatacomunale.ext
      - Agenzia delle Entrate:
        https://www.agenziaentrate.gov.it/

MEF Addizionali Comunali IRPEF (storico):
    https://www1.finanze.gov.it/finanze2/dipartimentopolitichefiscali/
    fiscalitalocale/nuova_addcomuneIrpef/  (può non essere raggiungibile)
"""

import argparse
import copy
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Percorsi
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
TAX_DATA_PATH = (
    REPO_ROOT
    / "src"
    / "lambdas"
    / "services"
    / "bookings"
    / "calculate-net-salary"
    / "italian_tax_data.json"
)

# ---------------------------------------------------------------------------
# Configurazione HTTP
# ---------------------------------------------------------------------------
MEF_COMUNI_URL = (
    "https://www1.finanze.gov.it/finanze2/dipartimentopolitichefiscali/"
    "fiscalitalocale/nuova_addcomuneIrpef/risultato.html"
)
MEF_REGIONI_URL = (
    "https://www1.finanze.gov.it/finanze2/dipartimentopolitichefiscali/"
    "fiscalitalocale/addregio/"
)
MEF_REGIONI_ELENCO_URL = (
    "https://www1.finanze.gov.it/finanze2/dipartimentopolitichefiscali/"
    "fiscalitalocale/addregio/regioni.htm"
)
# Endpoint ufficiale ISTAT per tutti i comuni italiani con codice provincia
ISTAT_COMUNI_CSV = (
    "https://www.istat.it/storage/codici-unita-amministrative/"
    "Elenco-comuni-italiani.csv"
)

REQUEST_TIMEOUT = 10       # secondi per singola richiesta
MAX_WORKERS = 8            # thread paralleli per comuni
SLEEP_BETWEEN_REQUESTS = 0.3  # secondi – rispetto del rate limit MEF

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BeeBusy-AddizioniUpdater/1.0; "
        "contact: dev@beebusy.it)"
    )
}

# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

# Mapping sigla provincia → nome regione (identico al JSON)
PROVINCE_TO_REGIONE: Dict[str, str] = {
    "AG": "Sicilia",         "CL": "Sicilia",         "CT": "Sicilia",
    "EN": "Sicilia",         "ME": "Sicilia",          "PA": "Sicilia",
    "RG": "Sicilia",         "SR": "Sicilia",          "TP": "Sicilia",
    "AQ": "Abruzzo",         "CH": "Abruzzo",          "PE": "Abruzzo",
    "TE": "Abruzzo",
    "MT": "Basilicata",      "PZ": "Basilicata",
    "CZ": "Calabria",        "CS": "Calabria",         "RC": "Calabria",
    "KR": "Calabria",        "VV": "Calabria",
    "CE": "Campania",        "BN": "Campania",         "NA": "Campania",
    "AV": "Campania",        "SA": "Campania",
    "BO": "EmiliaRomagna",   "FE": "EmiliaRomagna",    "FC": "EmiliaRomagna",
    "MO": "EmiliaRomagna",   "PC": "EmiliaRomagna",    "PR": "EmiliaRomagna",
    "RA": "EmiliaRomagna",   "RE": "EmiliaRomagna",    "RN": "EmiliaRomagna",
    "GO": "FriuliVG",        "PN": "FriuliVG",         "TS": "FriuliVG",
    "UD": "FriuliVG",
    "FR": "Lazio",           "LT": "Lazio",            "RI": "Lazio",
    "RM": "Lazio",           "VT": "Lazio",
    "GE": "Liguria",         "IM": "Liguria",          "SP": "Liguria",
    "SV": "Liguria",
    "BG": "Lombardia",       "BS": "Lombardia",        "CO": "Lombardia",
    "CR": "Lombardia",       "LC": "Lombardia",        "LO": "Lombardia",
    "MB": "Lombardia",       "MI": "Lombardia",        "MN": "Lombardia",
    "PV": "Lombardia",       "SO": "Lombardia",        "VA": "Lombardia",
    "AN": "Marche",          "AP": "Marche",           "FM": "Marche",
    "MC": "Marche",          "PU": "Marche",
    "CB": "Molise",          "IS": "Molise",
    "AL": "Piemonte",        "AT": "Piemonte",         "BI": "Piemonte",
    "CN": "Piemonte",        "NO": "Piemonte",         "TO": "Piemonte",
    "VB": "Piemonte",        "VC": "Piemonte",
    "BA": "Puglia",          "BR": "Puglia",           "BT": "Puglia",
    "FG": "Puglia",          "LE": "Puglia",           "TA": "Puglia",
    "CA": "Sardegna",        "NU": "Sardegna",         "OR": "Sardegna",
    "SS": "Sardegna",        "SU": "Sardegna",
    "AR": "Toscana",         "FI": "Toscana",          "GR": "Toscana",
    "LI": "Toscana",         "LU": "Toscana",          "MS": "Toscana",
    "PI": "Toscana",         "PO": "Toscana",          "PT": "Toscana",
    "SI": "Toscana",
    "BZ": "TrentinoAA",      "TN": "TrentinoAA",
    "PG": "Umbria",          "TR": "Umbria",
    "AO": "ValleAosta",
    "BL": "Veneto",          "PD": "Veneto",           "RO": "Veneto",
    "TV": "Veneto",          "VE": "Veneto",           "VI": "Veneto",
    "VR": "Veneto",
    # Province autonome
    "LT": "Lazio",           "PS": "Marche",
}

# Aliquote regionali di default (usate come fallback se il parsing MEF fallisce).
# Fonte: MEF / leggi regionali. Verificare ogni anno.
REGIONI_DEFAULT_RATES: Dict[str, float] = {
    "Abruzzo":       0.0173,
    "Basilicata":    0.0123,
    "Calabria":      0.0203,
    "Campania":      0.0203,
    "EmiliaRomagna": 0.0133,
    "FriuliVG":      0.0123,
    "Lazio":         0.0173,
    "Liguria":       0.0123,
    "Lombardia":     0.0123,
    "Marche":        0.0123,
    "Molise":        0.0203,
    "Piemonte":      0.0162,
    "Puglia":        0.0203,
    "Sardegna":      0.0123,
    "Sicilia":       0.0123,
    "Toscana":       0.0173,
    "TrentinoAA":    0.0123,
    "Umbria":        0.0123,
    "ValleAosta":    0.0123,
    "Veneto":        0.0123,
}

# Mapping nome MEF → chiave JSON per le regioni
MEF_REGIONE_NAME_MAP: Dict[str, str] = {
    "Abruzzo":                 "Abruzzo",
    "Basilicata":              "Basilicata",
    "Calabria":                "Calabria",
    "Campania":                "Campania",
    "Emilia-Romagna":          "EmiliaRomagna",
    "Emilia Romagna":          "EmiliaRomagna",
    "Friuli-Venezia Giulia":   "FriuliVG",
    "Friuli Venezia Giulia":   "FriuliVG",
    "Lazio":                   "Lazio",
    "Liguria":                 "Liguria",
    "Lombardia":               "Lombardia",
    "Marche":                  "Marche",
    "Molise":                  "Molise",
    "Piemonte":                "Piemonte",
    "Puglia":                  "Puglia",
    "Sardegna":                "Sardegna",
    "Sicilia":                 "Sicilia",
    "Toscana":                 "Toscana",
    "Trentino-Alto Adige":     "TrentinoAA",
    "Trentino Alto Adige":     "TrentinoAA",
    "Umbria":                  "Umbria",
    "Valle d'Aosta":           "ValleAosta",
    "Valle d Aosta":           "ValleAosta",
    "Veneto":                  "Veneto",
}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _clean_float(text: str) -> Optional[float]:
    """Converte stringa italiana '0,80' in float 0.008 (percentuale → decimale)."""
    if not text:
        return None
    # rimuove caratteri non numerici tranne virgola e punto
    text = re.sub(r"[^\d,.]", "", text.strip())
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        val = float(text)
        # se > 1.0 è espressa come percentuale (es 0.80 → 0.80%, ma 0.80 → 0.0080)
        # il MEF usa formato "0,80" = 0,80% → convertiamo
        return round(val / 100, 6) if val > 1.0 else round(val / 100, 6)
    except ValueError:
        return None


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ---------------------------------------------------------------------------
# Fetch addizionali regionali da MEF
# ---------------------------------------------------------------------------

def fetch_addizionali_regionali(anno: int) -> Dict[str, float]:
    """
    Scarica le addizionali regionali IRPEF dal sito MEF.
    Ritorna dict { "Lombardia": 0.0123, ... }
    """
    print(f"[REGIONALI] Fetching anno {anno} da MEF …")
    rates: Dict[str, float] = copy.deepcopy(REGIONI_DEFAULT_RATES)

    try:
        sess = _session()
        # La pagina del MEF lista tutte le regioni con la loro aliquota
        resp = sess.get(
            MEF_REGIONI_ELENCO_URL,
            params={"anno": anno},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # La tabella ha: | Regione | Aliquota base | Aliquota addizionale | …
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            nome_raw = cells[0].get_text(strip=True)
            # cerca la colonna "Aliquota" (può variare)
            aliquota_text = None
            for cell in cells[1:]:
                txt = cell.get_text(strip=True)
                if re.search(r"\d", txt):
                    aliquota_text = txt
                    break
            if not nome_raw or not aliquota_text:
                continue
            chiave = MEF_REGIONE_NAME_MAP.get(nome_raw)
            if not chiave:
                # prova con normalizzazione
                for k, v in MEF_REGIONE_NAME_MAP.items():
                    if nome_raw.lower().startswith(k.lower()[:6]):
                        chiave = v
                        break
            if chiave:
                rate = _clean_float(aliquota_text)
                if rate is not None:
                    rates[chiave] = rate
                    print(f"  ✓ {chiave}: {rate*100:.2f}%")

    except Exception as exc:
        print(f"[REGIONALI WARNING] Parsing MEF fallito ({exc}). "
              "Uso valori di default dal codice.")

    # Seconda fonte: prova pagina alternativa
    if all(v == REGIONI_DEFAULT_RATES.get(k) for k, v in rates.items()):
        rates = _fetch_addizionali_regionali_alt(anno, rates)

    return rates


def _fetch_addizionali_regionali_alt(anno: int, rates: Dict[str, float]) -> Dict[str, float]:
    """Tentativo con URL alternativo MEF per le regioni."""
    alt_url = (
        "https://www1.finanze.gov.it/finanze2/dipartimentopolitichefiscali/"
        "fiscalitalocale/addregio/aspx/addizionalireg.aspx"
    )
    try:
        sess = _session()
        resp = sess.get(alt_url, params={"anno": anno}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            nome_raw = cells[0].get_text(strip=True)
            chiave = MEF_REGIONE_NAME_MAP.get(nome_raw)
            if not chiave:
                continue
            for cell in cells[1:]:
                rate = _clean_float(cell.get_text(strip=True))
                if rate is not None:
                    rates[chiave] = rate
                    print(f"  ✓ {chiave}: {rate*100:.2f}% (alt)")
                    break
    except Exception as exc:
        print(f"[REGIONALI WARNING] URL alt fallito: {exc}")
    return rates


# ---------------------------------------------------------------------------
# Fetch lista comuni da ISTAT
# ---------------------------------------------------------------------------

def fetch_comuni_istat() -> List[Dict]:
    """
    Scarica il CSV ISTAT e ritorna lista di:
        { "comune": "Milano", "provincia": "MI" }
    """
    print("[ISTAT] Scarico elenco comuni …")
    try:
        resp = requests.get(ISTAT_COMUNI_CSV, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        # Il CSV ISTAT usa encoding latin-1 / windows-1252
        content = resp.content.decode("latin-1", errors="replace")
        comuni = _parse_istat_csv(content)
        print(f"[ISTAT] {len(comuni)} comuni trovati.")
        return comuni
    except Exception as exc:
        print(f"[ISTAT WARNING] Download fallito ({exc}). "
              "Uso lista embedded minima.")
        return _comuni_fallback()


def _parse_istat_csv(content: str) -> List[Dict]:
    """
    Parsing del CSV ISTAT formato attuale (header multi-riga).
    Colonne fisse del formato ISTAT 2024:
      6  = Denominazione in italiano (nome comune)
      14 = Sigla automobilistica (sigla provincia)
    """
    NOME_COL  = 6
    SIGLA_COL = 14

    lines = content.splitlines()
    if not lines:
        return []

    # I dati iniziano quando la prima colonna è un numero (codice regione, es. "01")
    data_start = 0
    for i, line in enumerate(lines[:10]):
        first = line.split(";")[0].strip().strip('"')
        if first.isdigit() and len(first) <= 2:
            data_start = i
            break

    comuni = []
    seen = set()
    for line in lines[data_start:]:
        if not line.strip():
            continue
        cols = [c.strip().strip('"') for c in line.split(";")]
        if len(cols) <= max(NOME_COL, SIGLA_COL):
            continue
        sigla = cols[SIGLA_COL].strip().upper()
        nome  = cols[NOME_COL].strip()
        key   = (nome.lower(), sigla)
        if sigla and nome and len(sigla) == 2 and sigla.isalpha() and key not in seen:
            comuni.append({"comune": nome, "provincia": sigla})
            seen.add(key)

    return comuni


def _comuni_fallback() -> List[Dict]:
    """Lista minima embedded: capoluoghi di provincia + comuni > 50k abitanti."""
    return [
        # Lombardia
        {"comune": "Milano", "provincia": "MI"},
        {"comune": "Brescia", "provincia": "BS"},
        {"comune": "Bergamo", "provincia": "BG"},
        {"comune": "Monza", "provincia": "MB"},
        {"comune": "Como", "provincia": "CO"},
        {"comune": "Varese", "provincia": "VA"},
        {"comune": "Sesto San Giovanni", "provincia": "MI"},
        {"comune": "Cinisello Balsamo", "provincia": "MI"},
        {"comune": "Busto Arsizio", "provincia": "VA"},
        {"comune": "Mantova", "provincia": "MN"},
        {"comune": "Cremona", "provincia": "CR"},
        {"comune": "Pavia", "provincia": "PV"},
        {"comune": "Lodi", "provincia": "LO"},
        {"comune": "Lecco", "provincia": "LC"},
        # Piemonte
        {"comune": "Torino", "provincia": "TO"},
        {"comune": "Novara", "provincia": "NO"},
        {"comune": "Alessandria", "provincia": "AL"},
        {"comune": "Asti", "provincia": "AT"},
        {"comune": "Cuneo", "provincia": "CN"},
        {"comune": "Moncalieri", "provincia": "TO"},
        {"comune": "Collegno", "provincia": "TO"},
        # Veneto
        {"comune": "Venezia", "provincia": "VE"},
        {"comune": "Verona", "provincia": "VR"},
        {"comune": "Padova", "provincia": "PD"},
        {"comune": "Vicenza", "provincia": "VI"},
        {"comune": "Treviso", "provincia": "TV"},
        {"comune": "Mestre", "provincia": "VE"},
        # Emilia-Romagna
        {"comune": "Bologna", "provincia": "BO"},
        {"comune": "Modena", "provincia": "MO"},
        {"comune": "Parma", "provincia": "PR"},
        {"comune": "Reggio Emilia", "provincia": "RE"},
        {"comune": "Ferrara", "provincia": "FE"},
        {"comune": "Ravenna", "provincia": "RA"},
        {"comune": "Rimini", "provincia": "RN"},
        {"comune": "Forlì", "provincia": "FC"},
        {"comune": "Cesena", "provincia": "FC"},
        {"comune": "Imola", "provincia": "BO"},
        # Toscana
        {"comune": "Firenze", "provincia": "FI"},
        {"comune": "Prato", "provincia": "PO"},
        {"comune": "Livorno", "provincia": "LI"},
        {"comune": "Siena", "provincia": "SI"},
        {"comune": "Arezzo", "provincia": "AR"},
        {"comune": "Pistoia", "provincia": "PT"},
        {"comune": "Pisa", "provincia": "PI"},
        {"comune": "Lucca", "provincia": "LU"},
        {"comune": "Grosseto", "provincia": "GR"},
        {"comune": "Massa", "provincia": "MS"},
        # Lazio
        {"comune": "Roma", "provincia": "RM"},
        {"comune": "Guidonia Montecelio", "provincia": "RM"},
        {"comune": "Fiumicino", "provincia": "RM"},
        {"comune": "Latina", "provincia": "LT"},
        {"comune": "Frosinone", "provincia": "FR"},
        {"comune": "Viterbo", "provincia": "VT"},
        {"comune": "Rieti", "provincia": "RI"},
        # Campania
        {"comune": "Napoli", "provincia": "NA"},
        {"comune": "Salerno", "provincia": "SA"},
        {"comune": "Caserta", "provincia": "CE"},
        {"comune": "Benevento", "provincia": "BN"},
        {"comune": "Avellino", "provincia": "AV"},
        {"comune": "Giugliano in Campania", "provincia": "NA"},
        {"comune": "Torre del Greco", "provincia": "NA"},
        {"comune": "Casoria", "provincia": "NA"},
        {"comune": "Afragola", "provincia": "NA"},
        # Puglia
        {"comune": "Bari", "provincia": "BA"},
        {"comune": "Taranto", "provincia": "TA"},
        {"comune": "Foggia", "provincia": "FG"},
        {"comune": "Lecce", "provincia": "LE"},
        {"comune": "Brindisi", "provincia": "BR"},
        {"comune": "Andria", "provincia": "BT"},
        {"comune": "Barletta", "provincia": "BT"},
        {"comune": "Altamura", "provincia": "BA"},
        {"comune": "Bitonto", "provincia": "BA"},
        {"comune": "Martina Franca", "provincia": "TA"},
        # Calabria
        {"comune": "Reggio Calabria", "provincia": "RC"},
        {"comune": "Catanzaro", "provincia": "CZ"},
        {"comune": "Cosenza", "provincia": "CS"},
        {"comune": "Crotone", "provincia": "KR"},
        {"comune": "Vibo Valentia", "provincia": "VV"},
        # Sicilia
        {"comune": "Palermo", "provincia": "PA"},
        {"comune": "Catania", "provincia": "CT"},
        {"comune": "Messina", "provincia": "ME"},
        {"comune": "Siracusa", "provincia": "SR"},
        {"comune": "Agrigento", "provincia": "AG"},
        {"comune": "Caltanissetta", "provincia": "CL"},
        {"comune": "Enna", "provincia": "EN"},
        {"comune": "Ragusa", "provincia": "RG"},
        {"comune": "Trapani", "provincia": "TP"},
        # Sardegna
        {"comune": "Cagliari", "provincia": "CA"},
        {"comune": "Sassari", "provincia": "SS"},
        {"comune": "Nuoro", "provincia": "NU"},
        {"comune": "Oristano", "provincia": "OR"},
        # Liguria
        {"comune": "Genova", "provincia": "GE"},
        {"comune": "La Spezia", "provincia": "SP"},
        {"comune": "Imperia", "provincia": "IM"},
        {"comune": "Savona", "provincia": "SV"},
        # Marche
        {"comune": "Ancona", "provincia": "AN"},
        {"comune": "Pesaro", "provincia": "PU"},
        {"comune": "Macerata", "provincia": "MC"},
        {"comune": "Ascoli Piceno", "provincia": "AP"},
        # Abruzzo
        {"comune": "L'Aquila", "provincia": "AQ"},
        {"comune": "Pescara", "provincia": "PE"},
        {"comune": "Chieti", "provincia": "CH"},
        {"comune": "Teramo", "provincia": "TE"},
        # Umbria
        {"comune": "Perugia", "provincia": "PG"},
        {"comune": "Terni", "provincia": "TR"},
        # Friuli VG
        {"comune": "Trieste", "provincia": "TS"},
        {"comune": "Udine", "provincia": "UD"},
        {"comune": "Gorizia", "provincia": "GO"},
        {"comune": "Pordenone", "provincia": "PN"},
        # Trentino AA
        {"comune": "Trento", "provincia": "TN"},
        {"comune": "Bolzano", "provincia": "BZ"},
        # Valle d'Aosta
        {"comune": "Aosta", "provincia": "AO"},
        # Molise
        {"comune": "Campobasso", "provincia": "CB"},
        {"comune": "Isernia", "provincia": "IS"},
        # Basilicata
        {"comune": "Potenza", "provincia": "PZ"},
        {"comune": "Matera", "provincia": "MT"},
    ]


# ---------------------------------------------------------------------------
# Fetch addizionale comunale dal MEF (per singolo comune)
# ---------------------------------------------------------------------------

def _parse_mef_aliquota(html: str, comune: str) -> Optional[float]:
    """
    Parsing dell'HTML restituito dal MEF per un singolo comune.
    Il sito restituisce una tabella con colonne: Comune | Anno | Aliquota | ...
    """
    soup = BeautifulSoup(html, "lxml")

    # Strategia 1: cerca cella con testo "Aliquota" e prende la successiva
    for td in soup.find_all("td"):
        txt = td.get_text(strip=True)
        if txt.lower() in ("aliquota", "aliquota base", "aliquota irpef"):
            sib = td.find_next_sibling("td")
            if sib:
                rate = _clean_float(sib.get_text(strip=True))
                if rate is not None:
                    return rate

    # Strategia 2: riga con nome comune e valore numerico della forma "0,XX"
    comune_upper = comune.upper()
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        testi = [c.get_text(strip=True) for c in cells]
        if any(comune_upper in t.upper() for t in testi):
            for txt in testi:
                rate = _clean_float(txt)
                if rate is not None:
                    return rate

    # Strategia 3: cerca pattern numerico "0,XX" o "X,XX" in tutto l'HTML
    # tipico dell'aliquota espressa in percentuale (0.30 – 0.90%)
    matches = re.findall(r"\b0[,.](\d{2})\b", html)
    if matches:
        # prendi il primo valore trovato
        text = f"0.{matches[0]}"
        try:
            val = float(text)
            return round(val / 100, 6)
        except ValueError:
            pass

    return None


def fetch_comunale_mef(
    session: requests.Session,
    comune: str,
    provincia: str,
    anno: int,
) -> Tuple[str, str, Optional[float]]:
    """
    Chiama il MEF per singolo comune.
    Ritorna (comune, provincia, aliquota_o_None).
    """
    try:
        params = {
            "lista": "1",
            "anno": anno,
            "comune": comune.upper(),
        }
        resp = session.get(MEF_COMUNI_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        aliquota = _parse_mef_aliquota(resp.text, comune)
        return comune, provincia, aliquota
    except requests.Timeout:
        return comune, provincia, None
    except requests.RequestException:
        return comune, provincia, None
    except Exception:
        return comune, provincia, None


# ---------------------------------------------------------------------------
# Fetch TUTTE le addizionali comunali con parsing bulk (lettera per lettera)
# ---------------------------------------------------------------------------

def fetch_addizionali_comunali_bulk(
    comuni_list: List[Dict],
    anno: int,
) -> Dict[str, Dict]:
    """
    Scarica le addizionali comunali dal MEF per tutti i comuni nella lista.

    Ritorna dict organizzato per provincia:
    {
        "MI": {
            "mediaProvinciale": 0.008,
            "_source": "MEF 2026",
            "comuni": {
                "Milano": 0.008,
                ...
            }
        },
        ...
    }
    """
    print(f"\n[COMUNALI] Fetching {len(comuni_list)} comuni per anno {anno} …")
    print(f"  Thread: {MAX_WORKERS}, sleep: {SLEEP_BETWEEN_REQUESTS}s")

    # Raggruppa per provincia
    by_prov: Dict[str, List[str]] = {}
    for item in comuni_list:
        prov = item["provincia"].upper()
        by_prov.setdefault(prov, []).append(item["comune"])

    results: Dict[str, Dict[str, Optional[float]]] = {}  # provincia → comune → aliquota

    session = _session()
    total = len(comuni_list)
    done = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for item in comuni_list:
            f = executor.submit(
                fetch_comunale_mef,
                session,
                item["comune"],
                item["provincia"].upper(),
                anno,
            )
            futures[f] = item

        for future in as_completed(futures):
            comune, provincia, aliquota = future.result()
            done += 1

            if aliquota is not None:
                results.setdefault(provincia, {})[comune] = aliquota
            else:
                failed += 1

            if done % 50 == 0 or done == total:
                pct = done / total * 100
                print(f"  [{done}/{total} {pct:.0f}%] ok={done-failed} fail={failed}")

            # Rate limiting leggero
            time.sleep(SLEEP_BETWEEN_REQUESTS / MAX_WORKERS)

    # Costruisci struttura finale con medie provinciali
    output: Dict[str, Dict] = {}
    for prov, comuni_dict in results.items():
        aliquote = [v for v in comuni_dict.values() if v is not None]
        media = round(sum(aliquote) / len(aliquote), 6) if aliquote else 0.008
        output[prov] = {
            "mediaProvinciale": media,
            "_source": f"MEF {anno}",
            "comuni": {k: v for k, v in comuni_dict.items() if v is not None},
        }

    # Province senza dati: media default
    for prov in by_prov:
        if prov not in output:
            output[prov] = {
                "mediaProvinciale": 0.008,
                "_source": f"MEF {anno} – nessun dato, default",
                "comuni": {},
            }

    print(f"\n[COMUNALI] Trovate aliquote per {sum(len(d['comuni']) for d in output.values())} comuni "
          f"su {len(output)} province.")
    return output


# ---------------------------------------------------------------------------
# Update del JSON
# ---------------------------------------------------------------------------

def load_tax_data(path: Path) -> Dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_tax_data(path: Path, data: Dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVE] Scritto: {path}")


def merge_results(
    tax_data: Dict,
    regionali: Dict[str, float],
    comunali: Dict[str, Dict],
    anno: int,
) -> Dict:
    """
    Aggiorna tax_data con le nuove aliquote mantenendo la struttura esistente.
    """
    updated = copy.deepcopy(tax_data)
    updated["taxYear"] = anno
    updated["_lastUpdated"] = datetime.now().strftime("%Y-%m-%d")
    updated["_comment"] = (
        f"Dati fiscali italiani {anno} – IRPEF, INPS, addizionali regionali e comunali. "
        f"Aggiornato il {datetime.now().strftime('%Y-%m-%d')} via scripts/aggiorna-addizionali.py"
    )

    # Aggiorna addizionali regionali
    for regione, aliquota in regionali.items():
        updated["addizionaliRegionali"][regione] = {"aliquota": aliquota}

    # Merge addizionali comunali
    # Mantieni comuni esistenti che il MEF non ha restituito, aggiorna quelli trovati
    existing_comunali: Dict = updated.get("addizionaliComunali", {})
    for prov, prov_data in comunali.items():
        got_new_data = bool(prov_data.get("comuni"))
        if prov not in existing_comunali:
            existing_comunali[prov] = prov_data
        else:
            if got_new_data:
                # Merge comuni: nuovi dati MEF sovrascrivono quelli esistenti
                existing_comunali[prov].setdefault("comuni", {}).update(prov_data["comuni"])
                # Ricalcola media con tutti i comuni
                aliquote = list(existing_comunali[prov]["comuni"].values())
                existing_comunali[prov]["mediaProvinciale"] = (
                    round(sum(aliquote) / len(aliquote), 6) if aliquote else 0.008
                )
                # Aggiorna source solo se abbiamo davvero ricevuto nuovi dati
                existing_comunali[prov]["_source"] = prov_data["_source"]
            elif "mediaProvinciale" not in existing_comunali[prov]:
                existing_comunali[prov]["mediaProvinciale"] = prov_data["mediaProvinciale"]
            # Se non abbiamo nuovi dati, manteniamo _source originale

    updated["addizionaliComunali"] = existing_comunali
    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Aggiorna addizionali IRPEF comunali e regionali dal MEF"
    )
    parser.add_argument(
        "--anno",
        type=int,
        default=datetime.now().year,
        help="Anno fiscale di riferimento (default: anno corrente)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Non scrive su disco, stampa solo il risultato",
    )
    parser.add_argument(
        "--only-regionali",
        action="store_true",
        help="Aggiorna solo le addizionali regionali (più veloce)",
    )
    parser.add_argument(
        "--only-comunali",
        action="store_true",
        help="Aggiorna solo le addizionali comunali",
    )
    parser.add_argument(
        "--istat-only-fallback",
        action="store_true",
        help="Usa solo la lista embedded (non scarica ISTAT CSV – per test offline)",
    )
    args = parser.parse_args()

    anno = args.anno
    print("=" * 60)
    print(f"  Aggiornamento addizionali IRPEF – Anno {anno}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    if not TAX_DATA_PATH.exists():
        print(f"[ERROR] File non trovato: {TAX_DATA_PATH}")
        sys.exit(1)

    tax_data = load_tax_data(TAX_DATA_PATH)

    # --- Addizionali regionali ---
    if not args.only_comunali:
        regionali = fetch_addizionali_regionali(anno)
        print(f"\n[REGIONALI] {len(regionali)} regioni aggiornate:")
        for r, a in sorted(regionali.items()):
            print(f"  {r:20s}: {a*100:.2f}%")
    else:
        regionali = {r: d["aliquota"] for r, d in tax_data.get("addizionaliRegionali", {}).items()}

    # --- Addizionali comunali ---
    if not args.only_regionali:
        if args.istat_only_fallback:
            comuni_list = _comuni_fallback()
            print(f"[DEBUG] Uso lista embedded: {len(comuni_list)} comuni")
        else:
            comuni_list = fetch_comuni_istat()
            if not comuni_list:
                comuni_list = _comuni_fallback()

        comunali = fetch_addizionali_comunali_bulk(comuni_list, anno)
    else:
        comunali = {}

    # --- Merge e salva ---
    updated = merge_results(tax_data, regionali, comunali, anno)

    if args.dry_run:
        print("\n[DRY RUN] Dati aggiornati (non scritti su disco):")
        # stampa solo addizionali regionali + prime 5 province comunali
        prov_sample = dict(list(updated["addizionaliComunali"].items())[:5])
        print(json.dumps({
            "taxYear": updated["taxYear"],
            "_lastUpdated": updated.get("_lastUpdated"),
            "addizionaliRegionali": updated["addizionaliRegionali"],
            "addizionaliComunali_sample": prov_sample,
        }, indent=2, ensure_ascii=False))
    else:
        save_tax_data(TAX_DATA_PATH, updated)
        print("\n✅ Aggiornamento completato!")
        print(f"   Regionali: {len(updated['addizionaliRegionali'])} regioni")
        prov_count = len(updated["addizionaliComunali"])
        comune_count = sum(
            len(d.get("comuni", {}))
            for d in updated["addizionaliComunali"].values()
        )
        print(f"   Comunali:  {comune_count} comuni su {prov_count} province")
        print(f"\nRicordati di fare commit + deploy della lambda!")
        print(f"  git add src/lambdas/services/bookings/calculate-net-salary/italian_tax_data.json")
        print(f"  git commit -m 'chore: aggiorna addizionali IRPEF {anno}'")


if __name__ == "__main__":
    main()
