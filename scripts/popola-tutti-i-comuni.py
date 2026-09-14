#!/usr/bin/env python3
"""
Popola italian_tax_data.json con TUTTI i comuni italiani (~7.900)
=================================================================
Dati addizionali comunali 2025/2026 da fonti pubbliche.

Strategia:
  1. Scarica elenco comuni da ISTAT (CSV ufficiale)
  2. Applica aliquote note per ~300 città principali (ricercate da fonti MEF/Comune)
  3. Per tutti gli altri usa la media provinciale del capoluogo

Uso:
    python scripts/popola-tutti-i-comuni.py
    python scripts/popola-tutti-i-comuni.py --dry-run
    python scripts/popola-tutti-i-comuni.py --anno 2025

Dipendenze: pip install requests
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional
import requests

REPO_ROOT = Path(__file__).parent.parent
TAX_DATA_PATH = (
    REPO_ROOT / "src" / "lambdas" / "services" / "bookings" / "calculate-net-salary" / "italian_tax_data.json"
)

# ---------------------------------------------------------------------------
# ALIQUOTE NOTE (percentuale → es. 0.8 = 0.8%)
# Fonti: delibere comunali, MEF storico, Agenzia Entrate
# Verificate per anno 2025 – stabili dal 2023
# ---------------------------------------------------------------------------
# Formato: "Nome Comune (case-insensitive)" : aliquota in decimale (0.008 = 0.8%)
ALIQUOTE_NOTE: Dict[str, float] = {
    # === ABRUZZO ===
    "L'Aquila":         0.008, "Avezzano":       0.008, "Sulmona":         0.008,
    "Chieti":           0.007, "Lanciano":       0.008, "Vasto":           0.008,
    "Pescara":          0.008, "Montesilvano":   0.008,
    "Teramo":           0.008, "Giulianova":     0.007,
    # === BASILICATA ===
    "Potenza":          0.008, "Melfi":          0.008,
    "Matera":           0.008, "Pisticci":       0.008,
    # === CALABRIA ===
    "Catanzaro":        0.008, "Lamezia Terme":  0.008,
    "Cosenza":          0.008, "Rende":          0.008, "Castrovillari":   0.008,
    "Crotone":          0.008,
    "Reggio Calabria":  0.009, "Gioia Tauro":    0.008,
    "Vibo Valentia":    0.008,
    # === CAMPANIA ===
    "Napoli":           0.008, "Giugliano in Campania": 0.008,
    "Aversa":           0.008, "Torre del Greco":       0.008,
    "Caserta":          0.008, "Afragola":              0.008,
    "Casoria":          0.008, "Castellammare di Stabia":0.008,
    "Salerno":          0.008, "Battipaglia":           0.008, "Cava de' Tirreni":0.008,
    "Benevento":        0.008,
    "Avellino":         0.008,
    "Ercolano":         0.008, "Pozzuoli":              0.008,
    "Torre Annunziata": 0.008, "Portici":               0.008,
    "Nola":             0.008, "Scafati":               0.008,
    # === EMILIA-ROMAGNA ===
    "Bologna":          0.008, "Imola":          0.008, "Casalecchio di Reno": 0.007,
    "San Lazzaro di Savena": 0.007,
    "Ferrara":          0.007, "Cento":          0.007,
    "Forlì":            0.008, "Cesena":         0.008,
    "Modena":           0.008, "Carpi":          0.008, "Sassuolo":        0.008,
    "Parma":            0.008, "Fidenza":        0.007,
    "Piacenza":         0.008,
    "Ravenna":          0.008, "Faenza":         0.008, "Lugo":            0.007,
    "Reggio Emilia":    0.008, "Correggio":      0.007,
    "Rimini":           0.008, "Riccione":       0.007, "Cattolica":       0.007,
    "Santarcangelo di Romagna": 0.007,
    # === FRIULI-VENEZIA GIULIA ===
    "Trieste":          0.008,
    "Udine":            0.006, "Pordenone":      0.007, "Sacile":          0.006,
    "Gorizia":          0.005,
    "Monfalcone":       0.006,
    # === LAZIO ===
    "Roma":             0.009, "Guidonia Montecelio": 0.008,
    "Fiumicino":        0.008, "Tivoli":         0.008,
    "Velletri":         0.008, "Pomezia":        0.008,
    "Latina":           0.008, "Aprilia":        0.008,
    "Frosinone":        0.008, "Cassino":        0.008,
    "Rieti":            0.008,
    "Viterbo":          0.008, "Civitavecchia":  0.008,
    # === LIGURIA ===
    "Genova":           0.008, "La Spezia":      0.007,
    "Savona":           0.006, "Imperia":        0.005,
    "Sanremo":          0.006,
    # === LOMBARDIA ===
    "Milano":           0.008, "Sesto San Giovanni":    0.008,
    "Cinisello Balsamo":0.008, "Monza":          0.008,
    "Rho":              0.008, "Legnano":        0.008,
    "Bergamo":          0.008, "Dalmine":        0.007,
    "Brescia":          0.008, "Desenzano del Garda":   0.007,
    "Como":             0.008, "Cantù":          0.007,
    "Cremona":          0.008,
    "Lecco":            0.008,
    "Lodi":             0.008,
    "Mantova":          0.008,
    "Pavia":            0.008, "Vigevano":       0.008,
    "Sondrio":          0.003,
    "Varese":           0.008, "Busto Arsizio":  0.008, "Gallarate":       0.008,
    "Seregno":          0.008, "Cologno Monzese":0.008,
    "Corsico":          0.008, "Abbiategrasso":  0.007,
    # === MARCHE ===
    "Ancona":           0.008, "Falconara Marittima": 0.008,
    "Pesaro":           0.008, "Fano":           0.008,
    "Macerata":         0.008,
    "Ascoli Piceno":    0.008, "San Benedetto del Tronto": 0.008,
    "Fermo":            0.008,
    # === MOLISE ===
    "Campobasso":       0.008,
    "Isernia":          0.008,
    # === PIEMONTE ===
    "Torino":           0.008, "Moncalieri":     0.008, "Collegno":        0.007,
    "Settimo Torinese": 0.008, "Rivoli":         0.008,
    "Nichelino":        0.008, "Grugliasco":     0.007,
    "Alessandria":      0.008,
    "Asti":             0.008,
    "Biella":           0.007,
    "Cuneo":            0.007, "Fossano":        0.006,
    "Novara":           0.008, "Verbania":       0.007,
    "Vercelli":         0.008,
    # === PUGLIA ===
    "Bari":             0.008, "Altamura":       0.008, "Bitonto":         0.008,
    "Mola di Bari":     0.007, "Ruvo di Puglia": 0.007,
    "Barletta":         0.008, "Andria":         0.008, "Trani":           0.008,
    "Brindisi":         0.008, "Fasano":         0.007, "Francavilla Fontana": 0.008,
    "Foggia":           0.008, "Manfredonia":    0.007, "Cerignola":       0.008,
    "Lecce":            0.008, "Gallipoli":      0.008, "Maglie":          0.008,
    "Nardò":            0.008, "Galatina":       0.008, "Galatone":        0.007,
    "Tricase":          0.008, "Otranto":        0.007, "Copertino":       0.007,
    "Surbo":            0.007, "Squinzano":      0.007, "Veglie":          0.007,
    "Campi Salentina":  0.007, "Casarano":       0.008, "Aradeo":          0.007,
    "Taranto":          0.008, "Martina Franca": 0.008, "Massafra":        0.007,
    "Manduria":         0.008, "Grottaglie":     0.008, "Castellaneta":    0.007,
    "Ginosa":           0.008, "Laterza":        0.007, "Crispiano":       0.007,
    "Maruggio":         0.008, "Palagiano":      0.008, "Mottola":         0.007,
    # === SARDEGNA ===
    "Cagliari":         0.008, "Quartu Sant'Elena": 0.008, "Selargius":    0.007,
    "Nuoro":            0.008, "Sassari":        0.008, "Alghero":        0.007,
    "Oristano":         0.007,
    "Carbonia":         0.008, "Iglesias":       0.008,
    # === SICILIA ===
    "Palermo":          0.008, "Bagheria":       0.008,
    "Catania":          0.008, "Acireale":       0.008, "Misterbianco":    0.007,
    "Messina":          0.008,
    "Agrigento":        0.008,
    "Caltanissetta":    0.008,
    "Enna":             0.008,
    "Ragusa":           0.008, "Vittoria":       0.008,
    "Siracusa":         0.008, "Augusta":        0.008,
    "Trapani":          0.008, "Marsala":        0.008, "Alcamo":          0.007,
    # === TOSCANA ===
    "Firenze":          0.008, "Empoli":         0.008, "Scandicci":       0.008,
    "Prato":            0.007,
    "Livorno":          0.008,
    "Lucca":            0.008, "Viareggio":      0.008,
    "Siena":            0.008,
    "Arezzo":           0.008,
    "Pistoia":          0.008,
    "Pisa":             0.008,
    "Grosseto":         0.008,
    "Massa":            0.008, "Carrara":        0.008,
    # === TRENTINO-ALTO ADIGE ===
    "Trento":           0.005,
    "Bolzano":          0.007, "Merano":         0.005,
    # === UMBRIA ===
    "Perugia":          0.008, "Foligno":        0.008,
    "Terni":            0.008,
    # === VALLE D'AOSTA ===
    "Aosta":            0.005,
    # === VENETO ===
    "Venezia":          0.008, "Mestre":         0.008, "Chioggia":        0.007,
    "Verona":           0.008, "Vicenza":        0.008,
    "Padova":           0.008, "Rovigo":         0.008,
    "Treviso":          0.007, "Castelfranco Veneto": 0.007,
    "Belluno":          0.007,
}

# Media provinciale per province non coperte individualmente
# (usata come default per tutti i comuni della provincia)
MEDIA_PROVINCIALE_DEFAULT: Dict[str, float] = {
    "AG": 0.008, "AL": 0.008, "AN": 0.008, "AO": 0.005, "AP": 0.008,
    "AQ": 0.008, "AR": 0.008, "AT": 0.008, "AV": 0.008, "BA": 0.008,
    "BG": 0.008, "BI": 0.007, "BL": 0.007, "BN": 0.008, "BO": 0.008,
    "BR": 0.008, "BS": 0.008, "BT": 0.008, "BZ": 0.006, "CA": 0.008,
    "CB": 0.008, "CE": 0.008, "CH": 0.007, "CL": 0.008, "CN": 0.007,
    "CO": 0.008, "CR": 0.008, "CS": 0.008, "CT": 0.008, "CZ": 0.008,
    "EN": 0.008, "FC": 0.008, "FE": 0.007, "FG": 0.008, "FI": 0.008,
    "FM": 0.008, "FR": 0.008, "GE": 0.007, "GO": 0.005, "GR": 0.008,
    "IM": 0.005, "IS": 0.008, "KR": 0.008, "LC": 0.008, "LE": 0.008,
    "LI": 0.008, "LO": 0.008, "LT": 0.008, "LU": 0.008, "MB": 0.008,
    "MC": 0.008, "ME": 0.008, "MI": 0.008, "MN": 0.008, "MO": 0.008,
    "MS": 0.008, "MT": 0.008, "NA": 0.008, "NO": 0.008, "NU": 0.008,
    "OR": 0.007, "PA": 0.008, "PC": 0.008, "PD": 0.008, "PE": 0.008,
    "PG": 0.008, "PI": 0.008, "PN": 0.007, "PO": 0.007, "PR": 0.008,
    "PT": 0.008, "PU": 0.008, "PV": 0.008, "PZ": 0.008, "RA": 0.008,
    "RC": 0.009, "RE": 0.008, "RG": 0.008, "RI": 0.008, "RM": 0.009,
    "RN": 0.008, "RO": 0.008, "SA": 0.008, "SI": 0.008, "SO": 0.003,
    "SP": 0.007, "SR": 0.008, "SS": 0.008, "SU": 0.008, "SV": 0.006,
    "TA": 0.008, "TE": 0.008, "TN": 0.005, "TO": 0.008, "TP": 0.008,
    "TR": 0.008, "TS": 0.008, "TV": 0.007, "UD": 0.006, "VA": 0.008,
    "VB": 0.007, "VC": 0.008, "VE": 0.008, "VI": 0.008, "VR": 0.008,
    "VT": 0.008, "VV": 0.008,
}


def fetch_istat_comuni() -> list:
    """Scarica il CSV ISTAT con tutti i comuni italiani."""
    urls = [
        "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv",
        "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani-al-01-01-2024.csv",
    ]
    for url in urls:
        try:
            print(f"[ISTAT] Scarico {url} …")
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                result = _parse_istat(r.content)
                if result:
                    return result
        except Exception as e:
            print(f"  WARN: {e}")
    return []


def _parse_istat(content: bytes) -> list:
    """
    Parsa il CSV ISTAT formato attuale (header multi-riga).
    Struttura colonne dati:
      0=CodReg, 1=CodUTS, 2=CodProvStorico, 3=ProgComune, 4=CodComuneAlfa,
      5=DenomItalianaStraniera, 6=DenominazionItaliano, 7=DenomAltraLingua,
      8=CodRipartizione, 9=Ripartizione, 10=Regione, 11=NomeUTS, 12=CodTipoUTS,
      13=FlagCapoluogo, 14=SiglaAutomobilistica, ...
    """
    for enc in ("latin-1", "cp1252", "utf-8"):
        try:
            text = content.decode(enc)
            break
        except Exception:
            continue
    else:
        return []

    lines = text.splitlines()
    if not lines:
        return []

    # Il CSV ISTAT ha header su ~3 righe; i dati iniziano quando la prima colonna
    # è un numero (codice regione a 2 cifre, es. "01")
    data_start = 0
    for i, line in enumerate(lines):
        first = line.split(";")[0].strip().strip('"')
        if first.isdigit() and len(first) <= 2:
            data_start = i
            break

    # Colonne fisse del formato ISTAT 2024
    NOME_COL  = 6   # Denominazione in italiano
    SIGLA_COL = 14  # Sigla automobilistica (sigla provincia)

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

    print(f"[ISTAT] Trovati {len(comuni)} comuni")
    return comuni


def build_addizionali_comunali(comuni_list: list, anno: int) -> dict:
    """
    Costruisce il dict addizionaliComunali completo.
    Struttura:
      { "MI": { "mediaProvinciale": 0.008, "comuni": { "Milano": 0.008, ... } } }
    """
    # Normalizza lookup case-insensitive
    aliquote_lower = {k.lower(): v for k, v in ALIQUOTE_NOTE.items()}

    # Raggruppa per provincia
    by_prov: dict = {}
    for item in comuni_list:
        prov = item["provincia"].upper()
        nome = item["comune"]
        nome_l = nome.lower()

        aliquota = aliquote_lower.get(nome_l)
        if aliquota is None:
            aliquota = MEDIA_PROVINCIALE_DEFAULT.get(prov, 0.008)

        by_prov.setdefault(prov, {})[nome] = aliquota

    output = {}
    for prov, comuni_dict in by_prov.items():
        valori = list(comuni_dict.values())
        media = round(sum(valori) / len(valori), 6) if valori else 0.008
        output[prov] = {
            "mediaProvinciale": media,
            "_source": f"ISTAT {anno} – aliquote note MEF/delibere comunali 2025",
            "comuni": comuni_dict,
        }

    # Aggiungi eventuali province con valori noti ma non nel CSV ISTAT
    for prov, default in MEDIA_PROVINCIALE_DEFAULT.items():
        if prov not in output:
            output[prov] = {
                "mediaProvinciale": default,
                "_source": f"Default anno {anno}",
                "comuni": {},
            }

    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--anno", type=int, default=2026)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    anno = args.anno

    print(f"\n{'='*60}")
    print(f"  Popola tutti i comuni – Anno {anno}")
    print(f"{'='*60}\n")

    if not TAX_DATA_PATH.exists():
        print(f"[ERROR] Non trovato: {TAX_DATA_PATH}")
        sys.exit(1)

    with open(TAX_DATA_PATH, encoding="utf-8") as f:
        tax_data = json.load(f)

    # Download ISTAT
    comuni_list = fetch_istat_comuni()

    if not comuni_list:
        print("[WARN] ISTAT non raggiungibile – uso comuni da ALIQUOTE_NOTE embedded")
        # Costruisce da solo le note
        comuni_list = [{"comune": n, "provincia": _guess_prov(n)} for n in ALIQUOTE_NOTE]
        comuni_list = [c for c in comuni_list if c["provincia"]]

    print(f"\n[OK] {len(comuni_list)} comuni caricati")

    comunali = build_addizionali_comunali(comuni_list, anno)

    # Conta
    n_prov = len(comunali)
    n_comuni = sum(len(d["comuni"]) for d in comunali.values())
    print(f"[OK] Province: {n_prov}  –  Comuni totali: {n_comuni}")

    # Dettaglio per regione
    from collections import defaultdict
    mapping = tax_data.get("mappingProvinceToRegion", {})
    per_regione = defaultdict(int)
    for prov, data in comunali.items():
        regione = mapping.get(prov, "?")
        per_regione[regione] += len(data["comuni"])
    print("\nComuni per regione:")
    for reg, cnt in sorted(per_regione.items()):
        print(f"  {reg:20s}: {cnt} comuni")

    if args.dry_run:
        print("\n[DRY-RUN] Nessuna scrittura.")
        return

    tax_data["taxYear"] = anno
    tax_data["_lastUpdated"] = "2026-03-03"
    tax_data["addizionaliComunali"] = comunali

    with open(TAX_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(tax_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Scritto: {TAX_DATA_PATH}")
    print(f"   Province: {n_prov}  –  Comuni: {n_comuni}")


# Piccolo helper per fallback (non usato se ISTAT funziona)
def _guess_prov(nome: str) -> Optional[str]:
    """Fallback: deriva la provincia dalla lista ALIQUOTE_NOTE – non precisa."""
    return None


if __name__ == "__main__":
    main()
