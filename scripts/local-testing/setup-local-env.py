"""
SETUP AMBIENTE MOTO LOCALE
===========================
Crea un ambiente AWS mockato in locale con moto per testare le API
SENZA toccare il DB dev.

Usage:
    python setup-local-env.py [--load-data] [--tables TABLE1,TABLE2]
    
Examples:
    # Setup ambiente vuoto
    python setup-local-env.py
    
    # Setup e carica dati esportati
    python setup-local-env.py --load-data
    
    # Setup solo alcune tabelle
    python setup-local-env.py --tables UserProfiles,JobListings --load-data
"""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Any
from decimal import Decimal
from moto import mock_aws
import boto3

# Load config
SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
DATA_DIR = SCRIPT_DIR / "exported-data"

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)


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


def print_warning(text: str):
    print(f"⚠️  {text}")


class LocalAWSEnvironment:
    """Gestisce l'ambiente AWS mockato con moto"""
    
    def __init__(self):
        self.mock = None
        self.dynamodb_resource = None
        self.dynamodb_client = None
        self.s3_client = None
        self.tables = {}
        
    def __enter__(self):
        """Avvia l'ambiente mock"""
        print_info("Avvio ambiente AWS mockato con moto...")
        
        # Setup environment variables per moto
        os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
        os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
        os.environ['AWS_SECURITY_TOKEN'] = 'testing'
        os.environ['AWS_SESSION_TOKEN'] = 'testing'
        os.environ['AWS_DEFAULT_REGION'] = CONFIG['aws_region']
        
        # Avvia mock
        self.mock = mock_aws()
        self.mock.start()
        
        # Crea client
        self.dynamodb_resource = boto3.resource('dynamodb', region_name=CONFIG['aws_region'])
        self.dynamodb_client = boto3.client('dynamodb', region_name=CONFIG['aws_region'])
        self.s3_client = boto3.client('s3', region_name=CONFIG['aws_region'])
        
        print_success("Ambiente mock avviato")
        return self
    
    def __exit__(self, *args):
        """Ferma l'ambiente mock"""
        if self.mock:
            self.mock.stop()
        print_info("Ambiente mock fermato")
    
    def create_table(self, table_name: str, schema: Dict[str, Any] = None):
        """
        Crea una tabella DynamoDB nel mock.
        
        Args:
            table_name: Nome della tabella
            schema: Schema opzionale, altrimenti usa schema generico
        """
        if not schema:
            # Schema generico con PK e SK
            schema = {
                'TableName': table_name,
                'KeySchema': [
                    {'AttributeName': 'PK', 'KeyType': 'HASH'},
                    {'AttributeName': 'SK', 'KeyType': 'RANGE'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'PK', 'AttributeType': 'S'},
                    {'AttributeName': 'SK', 'AttributeType': 'S'}
                ],
                'BillingMode': 'PAY_PER_REQUEST'
            }
        
        try:
            table = self.dynamodb_resource.create_table(**schema)
            self.tables[table_name] = table
            print_success(f"Tabella creata: {table_name}")
            return table
        except Exception as e:
            print_error(f"Errore creazione tabella {table_name}: {str(e)}")
            return None
    
    def create_bucket(self, bucket_name: str):
        """Crea un bucket S3 nel mock"""
        try:
            self.s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': CONFIG['aws_region']}
            )
            print_success(f"Bucket creato: {bucket_name}")
        except Exception as e:
            print_error(f"Errore creazione bucket {bucket_name}: {str(e)}")
    
    def load_data_from_file(self, table_name: str, filepath: Path):
        """
        Carica dati da un file JSON esportato in una tabella.
        
        Args:
            table_name: Nome della tabella
            filepath: Path al file JSON con i dati
        """
        if table_name not in self.tables:
            print_error(f"Tabella {table_name} non trovata nel mock")
            return 0
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            items = data.get('items', [])
            table = self.tables[table_name]
            
            # Batch write degli items
            loaded_count = 0
            with table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)
                    loaded_count += 1
            
            print_success(f"Caricati {loaded_count} items in {table_name}")
            return loaded_count
            
        except FileNotFoundError:
            print_warning(f"File non trovato: {filepath.name}")
            return 0
        except Exception as e:
            print_error(f"Errore caricamento dati in {table_name}: {str(e)}")
            return 0


def get_table_schemas() -> Dict[str, Dict]:
    """
    Restituisce gli schemi delle tabelle.
    In futuro può essere espanso con schemi specifici per ogni tabella.
    """
    # Schema base per tutte le tabelle
    base_schema = {
        'KeySchema': [
            {'AttributeName': 'PK', 'KeyType': 'HASH'},
            {'AttributeName': 'SK', 'KeyType': 'RANGE'}
        ],
        'AttributeDefinitions': [
            {'AttributeName': 'PK', 'AttributeType': 'S'},
            {'AttributeName': 'SK', 'AttributeType': 'S'}
        ],
        'BillingMode': 'PAY_PER_REQUEST'
    }
    
    schemas = {}
    for table_name in CONFIG['local_mock']['tables']:
        schemas[table_name] = {
            'TableName': table_name,
            **base_schema
        }
    
    return schemas


def main():
    parser = argparse.ArgumentParser(
        description="Setup ambiente moto locale per test API"
    )
    parser.add_argument(
        '--load-data',
        action='store_true',
        help='Carica dati esportati nelle tabelle'
    )
    parser.add_argument(
        '--tables',
        help='Lista di tabelle da creare (separate da virgola). Default: tutte'
    )
    
    args = parser.parse_args()
    
    print_header("SETUP AMBIENTE MOTO LOCALE")
    print_info("🔧 Ambiente 100% locale - NESSUNA connessione ad AWS")
    print()
    
    # Determina quali tabelle creare
    if args.tables:
        tables_to_create = [t.strip() for t in args.tables.split(',')]
    else:
        tables_to_create = CONFIG['local_mock']['tables']
    
    # Setup ambiente
    with LocalAWSEnvironment() as env:
        # Crea tabelle
        print_header("CREAZIONE TABELLE")
        schemas = get_table_schemas()
        
        for table_name in tables_to_create:
            if table_name in schemas:
                env.create_table(table_name, schemas[table_name])
            else:
                print_warning(f"Schema non definito per {table_name}, uso schema generico")
                env.create_table(table_name)
        
        # Crea bucket S3
        print_header("CREAZIONE BUCKET S3")
        for bucket_name in CONFIG['local_mock']['buckets']:
            env.create_bucket(bucket_name)
        
        # Carica dati se richiesto
        if args.load_data:
            print_header("CARICAMENTO DATI")
            
            if not DATA_DIR.exists():
                print_warning(f"Directory dati non trovata: {DATA_DIR}")
                print_info("Esegui prima: python export-dev-data.py --scan-all")
            else:
                total_loaded = 0
                for table_name in tables_to_create:
                    # Cerca file _latest.json
                    latest_file = DATA_DIR / f"{table_name}_latest.json"
                    if latest_file.exists():
                        count = env.load_data_from_file(table_name, latest_file)
                        total_loaded += count
                    else:
                        print_info(f"Nessun dato esportato per {table_name}")
                
                print()
                print_success(f"Totale items caricati: {total_loaded}")
        
        # Summary
        print_header("AMBIENTE PRONTO")
        print_success("L'ambiente moto locale è configurato!")
        print()
        print("📋 Tabelle create:")
        for table_name in env.tables.keys():
            print(f"   - {table_name}")
        print()
        print("📦 Bucket S3:")
        for bucket in CONFIG['local_mock']['buckets']:
            print(f"   - {bucket}")
        print()
        print("🚀 Prossimo passo:")
        print("   python test-api-local.py --lambda <nome_lambda> --event <evento.json>")
        print()
        
        # Salva info ambiente per altri script
        env_info = {
            "region": CONFIG['aws_region'],
            "tables": list(env.tables.keys()),
            "buckets": CONFIG['local_mock']['buckets'],
            "mock_active": True
        }
        
        env_file = SCRIPT_DIR / ".local-env-info.json"
        with open(env_file, 'w') as f:
            json.dump(env_info, f, indent=2)
        
        print_info(f"Info ambiente salvate in: {env_file.name}")


if __name__ == '__main__':
    main()
