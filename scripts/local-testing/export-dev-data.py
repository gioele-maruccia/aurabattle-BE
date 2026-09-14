"""
EXPORT DATI DA DB DEV (READ-ONLY)
===================================
Esporta dati dal database DynamoDB dev SENZA modificarlo.
I dati vengono salvati in file JSON locali per essere usati nei test.

Usage:
    python export-dev-data.py [table_name] [--limit N] [--scan-all]
    
Examples:
    python export-dev-data.py UserProfiles
    python export-dev-data.py UserProfiles --limit 50
    python export-dev-data.py --scan-all
"""

import argparse
import boto3
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from decimal import Decimal

# Load config
SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
DATA_DIR = SCRIPT_DIR / "exported-data"

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)


class DecimalEncoder(json.JSONEncoder):
    """Handle Decimal types from DynamoDB"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj) if obj % 1 else int(obj)
        return super(DecimalEncoder, self).default(obj)


def print_header(text: str):
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def print_success(text: str):
    print(f"✅ {text}")


def print_info(text: str):
    print(f"ℹ️  {text}")


def print_error(text: str):
    print(f"❌ {text}")


def export_table(table_name: str, dev_table_name: str, limit: int = None) -> Dict[str, Any]:
    """
    Esporta dati da una tabella DynamoDB dev (READ-ONLY).
    
    Args:
        table_name: Nome logico della tabella (es. 'UserProfiles')
        dev_table_name: Nome effettivo della tabella in dev (es. 'dev-UserProfiles')
        limit: Numero massimo di items da esportare (None = tutti)
    
    Returns:
        Dict con metadata e items esportati
    """
    print_info(f"Esportazione {table_name} da '{dev_table_name}'...")
    
    try:
        # Connessione READ-ONLY al DB dev
        dynamodb = boto3.resource(
            'dynamodb',
            region_name=CONFIG['aws_region']
        )
        table = dynamodb.Table(dev_table_name)
        
        # Scan della tabella (READ-ONLY operation)
        items = []
        scan_kwargs = {}
        
        if limit:
            scan_kwargs['Limit'] = limit
        
        while True:
            response = table.scan(**scan_kwargs)
            items.extend(response.get('Items', []))
            
            # Check se ci sono altri items
            if 'LastEvaluatedKey' not in response:
                break
            if limit and len(items) >= limit:
                break
                
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        # Limita se necessario
        if limit and len(items) > limit:
            items = items[:limit]
        
        print_success(f"Esportati {len(items)} items da {table_name}")
        
        return {
            "table_name": table_name,
            "dev_table_name": dev_table_name,
            "exported_at": datetime.utcnow().isoformat(),
            "item_count": len(items),
            "items": items
        }
        
    except Exception as e:
        print_error(f"Errore nell'esportazione di {table_name}: {str(e)}")
        return None


def save_export(data: Dict[str, Any], table_name: str):
    """Salva i dati esportati in un file JSON"""
    DATA_DIR.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{table_name}_{timestamp}.json"
    filepath = DATA_DIR / filename
    
    # Salva anche una versione "latest" senza timestamp
    latest_filepath = DATA_DIR / f"{table_name}_latest.json"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, cls=DecimalEncoder, ensure_ascii=False)
    
    with open(latest_filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, cls=DecimalEncoder, ensure_ascii=False)
    
    print_success(f"Dati salvati in: {filepath.name}")
    print_info(f"Link rapido: {latest_filepath.name}")


def main():
    parser = argparse.ArgumentParser(
        description="Esporta dati dal DB dev (READ-ONLY) per test locali"
    )
    parser.add_argument(
        'table',
        nargs='?',
        help='Nome della tabella da esportare (es. UserProfiles)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=CONFIG['dev_environment']['export_limit'],
        help=f"Numero massimo di items (default: {CONFIG['dev_environment']['export_limit']})"
    )
    parser.add_argument(
        '--scan-all',
        action='store_true',
        help='Esporta tutte le tabelle configurate'
    )
    
    args = parser.parse_args()
    
    print_header("EXPORT DATI DA DB DEV (READ-ONLY)")
    
    print_info("⚠️  MODALITÀ READ-ONLY: Il database dev NON verrà mai modificato")
    print_info(f"Region: {CONFIG['aws_region']}")
    print_info(f"Limite items: {args.limit if args.limit else 'Nessun limite'}")
    print()
    
    # Determina quali tabelle esportare
    tables_to_export = {}
    
    if args.scan_all:
        tables_to_export = CONFIG['dev_environment']['tables_to_export']
    elif args.table:
        if args.table in CONFIG['dev_environment']['tables_to_export']:
            tables_to_export[args.table] = CONFIG['dev_environment']['tables_to_export'][args.table]
        else:
            print_error(f"Tabella '{args.table}' non trovata in config.json")
            print_info("Tabelle disponibili:")
            for name in CONFIG['dev_environment']['tables_to_export'].keys():
                print(f"  - {name}")
            return 1
    else:
        print_error("Specifica una tabella o usa --scan-all")
        parser.print_help()
        return 1
    
    # Esporta le tabelle
    exported_count = 0
    for table_name, dev_table_name in tables_to_export.items():
        data = export_table(table_name, dev_table_name, args.limit)
        if data:
            save_export(data, table_name)
            exported_count += 1
        print()
    
    # Summary
    print_header("RIEPILOGO")
    print_success(f"Tabelle esportate: {exported_count}/{len(tables_to_export)}")
    print_info(f"Dati salvati in: {DATA_DIR}")
    print()
    print("📝 I dati esportati possono essere usati con:")
    print("   python setup-local-env.py --load-data")
    print()
    
    return 0


if __name__ == '__main__':
    exit(main())
