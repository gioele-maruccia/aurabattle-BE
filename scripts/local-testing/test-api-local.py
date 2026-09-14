"""
TEST API IN LOCALE
==================
Template universale per testare QUALSIASI Lambda/API in locale con moto.
ZERO rischio di modificare il DB dev!

Usage:
    python test-api-local.py --lambda <path> --event <json_file>
    python test-api-local.py --lambda <path> --event <json_file> --load-data
    
Examples:
    # Test con DB vuoto
    python test-api-local.py \\
        --lambda ../../src/lambdas/services/user-api/update-profile \\
        --event events/update-profile.json
    
    # Test con dati dal dev
    python test-api-local.py \\
        --lambda ../../src/lambdas/services/user-api/update-profile \\
        --event events/update-profile.json \\
        --load-data
    
    # Test interattivo
    python test-api-local.py --interactive
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from moto import mock_aws
import boto3
from decimal import Decimal


# Paths
SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
DATA_DIR = SCRIPT_DIR / "exported-data"
EVENTS_DIR = SCRIPT_DIR / "events"

# Load config
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)


class Colors:
    """ANSI colors per output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    print(f"\n{Colors.BOLD}{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}{Colors.ENDC}\n")


def print_success(text: str):
    print(f"{Colors.GREEN}✅ {text}{Colors.ENDC}")


def print_info(text: str):
    print(f"{Colors.CYAN}ℹ️  {text}{Colors.ENDC}")


def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.ENDC}")


def print_error(text: str):
    print(f"{Colors.RED}❌ {text}{Colors.ENDC}")


class DecimalEncoder(json.JSONEncoder):
    """Handle Decimal types from DynamoDB"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj) if obj % 1 else int(obj)
        return super(DecimalEncoder, self).default(obj)


class LocalTestEnvironment:
    """Ambiente di test locale con moto"""
    
    def __init__(self, load_data: bool = False, tables: list = None):
        self.mock = None
        self.load_data = load_data
        self.tables_to_create = tables or CONFIG['local_mock']['tables']
        self.dynamodb_resource = None
        self.dynamodb_client = None
        self.s3_client = None
        self.tables = {}
        
    def __enter__(self):
        """Setup ambiente mock"""
        print_info("🔧 Setup ambiente locale con moto...")
        
        # Environment variables
        os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
        os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
        os.environ['AWS_SECURITY_TOKEN'] = 'testing'
        os.environ['AWS_SESSION_TOKEN'] = 'testing'
        os.environ['AWS_DEFAULT_REGION'] = CONFIG['aws_region']
        os.environ['REGION'] = CONFIG['aws_region']
        
        # Start mock
        self.mock = mock_aws()
        self.mock.start()
        
        # Create clients
        self.dynamodb_resource = boto3.resource('dynamodb', region_name=CONFIG['aws_region'])
        self.dynamodb_client = boto3.client('dynamodb', region_name=CONFIG['aws_region'])
        self.s3_client = boto3.client('s3', region_name=CONFIG['aws_region'])
        
        # Setup resources
        self._create_tables()
        self._create_buckets()
        
        if self.load_data:
            self._load_data()
        
        print_success("Ambiente locale pronto!")
        return self
    
    def __exit__(self, *args):
        """Cleanup"""
        if self.mock:
            self.mock.stop()
        print_info("Ambiente locale chiuso")
    
    def _create_tables(self):
        """Crea tabelle DynamoDB"""
        print_info("Creazione tabelle DynamoDB...")
        
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
        
        for table_name in self.tables_to_create:
            try:
                table = self.dynamodb_resource.create_table(
                    TableName=table_name,
                    **base_schema
                )
                self.tables[table_name] = table
                print(f"  ✓ {table_name}")
            except Exception as e:
                print_error(f"Errore creazione {table_name}: {str(e)}")
    
    def _create_buckets(self):
        """Crea bucket S3"""
        print_info("Creazione bucket S3...")
        
        for bucket_name in CONFIG['local_mock']['buckets']:
            try:
                self.s3_client.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': CONFIG['aws_region']}
                )
                print(f"  ✓ {bucket_name}")
            except Exception as e:
                print_error(f"Errore creazione {bucket_name}: {str(e)}")
    
    def _load_data(self):
        """Carica dati esportati"""
        print_info("Caricamento dati esportati...")
        
        if not DATA_DIR.exists():
            print_warning(f"Directory dati non trovata: {DATA_DIR}")
            return
        
        total_loaded = 0
        for table_name in self.tables_to_create:
            latest_file = DATA_DIR / f"{table_name}_latest.json"
            
            if not latest_file.exists():
                continue
            
            try:
                with open(latest_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                items = data.get('items', [])
                table = self.tables[table_name]
                
                with table.batch_writer() as batch:
                    for item in items:
                        batch.put_item(Item=item)
                
                print(f"  ✓ {table_name}: {len(items)} items")
                total_loaded += len(items)
                
            except Exception as e:
                print_error(f"Errore caricamento {table_name}: {str(e)}")
        
        if total_loaded > 0:
            print_success(f"Caricati {total_loaded} items totali")
    
    def set_env_vars(self, env_vars: Dict[str, str]):
        """Imposta variabili d'ambiente per la Lambda"""
        for key, value in env_vars.items():
            os.environ[key] = value
    
    def invoke_lambda(self, lambda_path: Path, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Invoca una Lambda in locale.
        
        Args:
            lambda_path: Path alla directory della Lambda
            event: Event JSON da passare alla Lambda
        
        Returns:
            Response della Lambda
        """
        print_info(f"Invocazione Lambda: {lambda_path.name}")
        
        # Add lambda to path
        sys.path.insert(0, str(lambda_path))
        
        try:
            # Import lambda handler
            import app
            
            # Reload per assicurarsi di avere la versione fresh
            import importlib
            importlib.reload(app)
            
            # Invoke handler
            response = app.lambda_handler(event, None)
            
            return response
            
        except Exception as e:
            print_error(f"Errore nell'invocazione: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                "statusCode": 500,
                "body": json.dumps({"error": str(e)})
            }
        finally:
            # Remove from path
            sys.path.pop(0)


def load_event(event_path: Path) -> Dict[str, Any]:
    """Carica un evento da file JSON"""
    try:
        with open(event_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print_error(f"Errore caricamento evento: {str(e)}")
        return {}


def print_response(response: Dict[str, Any]):
    """Stampa la response formattata"""
    print_header("RESPONSE")
    
    status_code = response.get('statusCode', 'N/A')
    
    # Color code status
    if isinstance(status_code, int):
        if 200 <= status_code < 300:
            status_color = Colors.GREEN
        elif 400 <= status_code < 500:
            status_color = Colors.YELLOW
        else:
            status_color = Colors.RED
    else:
        status_color = Colors.ENDC
    
    print(f"{Colors.BOLD}Status Code:{Colors.ENDC} {status_color}{status_code}{Colors.ENDC}")
    
    # Headers
    if 'headers' in response:
        print(f"\n{Colors.BOLD}Headers:{Colors.ENDC}")
        for key, value in response['headers'].items():
            print(f"  {key}: {value}")
    
    # Body
    if 'body' in response:
        print(f"\n{Colors.BOLD}Body:{Colors.ENDC}")
        try:
            body = json.loads(response['body']) if isinstance(response['body'], str) else response['body']
            print(json.dumps(body, indent=2, cls=DecimalEncoder, ensure_ascii=False))
        except:
            print(response['body'])
    
    # Full response
    print(f"\n{Colors.BOLD}Full Response:{Colors.ENDC}")
    print(json.dumps(response, indent=2, cls=DecimalEncoder, ensure_ascii=False))


def interactive_mode():
    """Modalità interattiva per test rapidi"""
    print_header("MODALITÀ INTERATTIVA")
    print_info("Test rapido delle API in locale")
    print()
    
    # Lista Lambda disponibili
    lambdas_dir = Path(__file__).parent.parent.parent / "src" / "lambdas" / "services"
    
    print("Lambda disponibili:")
    lambda_dirs = []
    for service_dir in lambdas_dir.iterdir():
        if service_dir.is_dir():
            for lambda_dir in service_dir.iterdir():
                if lambda_dir.is_dir() and (lambda_dir / "app.py").exists():
                    lambda_dirs.append(lambda_dir)
                    print(f"  {len(lambda_dirs)}. {service_dir.name}/{lambda_dir.name}")
    
    print()
    choice = input("Scegli Lambda (numero): ")
    
    try:
        lambda_path = lambda_dirs[int(choice) - 1]
    except:
        print_error("Scelta non valida")
        return
    
    # Carica evento
    print()
    event_file = input("File evento JSON (o ENTER per evento vuoto): ")
    
    if event_file:
        event_path = Path(event_file)
        if not event_path.exists():
            event_path = EVENTS_DIR / event_file
        event = load_event(event_path)
    else:
        event = {}
    
    # Load data?
    print()
    load_data = input("Caricare dati dal dev? (y/N): ").lower() == 'y'
    
    # Environment variables
    print()
    print("Variabili d'ambiente (formato: KEY=VALUE, ENTER per finire):")
    env_vars = {}
    while True:
        env_line = input("  ")
        if not env_line:
            break
        try:
            key, value = env_line.split('=', 1)
            env_vars[key.strip()] = value.strip()
        except:
            print_warning("Formato non valido, usa KEY=VALUE")
    
    # Run test
    print()
    with LocalTestEnvironment(load_data=load_data) as env:
        env.set_env_vars(env_vars)
        response = env.invoke_lambda(lambda_path, event)
        print_response(response)


def main():
    parser = argparse.ArgumentParser(
        description="Test API in locale con moto (ZERO rischio per DB dev)"
    )
    parser.add_argument(
        '--lambda',
        help='Path alla directory della Lambda (es: ../../src/lambdas/services/user-api/update-profile)'
    )
    parser.add_argument(
        '--event',
        help='Path al file JSON con l\'evento'
    )
    parser.add_argument(
        '--load-data',
        action='store_true',
        help='Carica dati esportati dal dev (read-only)'
    )
    parser.add_argument(
        '--env',
        action='append',
        help='Variabile d\'ambiente (formato: KEY=VALUE), ripeti per più variabili'
    )
    parser.add_argument(
        '--interactive',
        action='store_true',
        help='Modalità interattiva'
    )
    
    args = parser.parse_args()
    
    print_header("TEST API IN LOCALE")
    print_warning("🔒 MODALITÀ SICURA: Il DB dev NON verrà MAI modificato!")
    print_info("🔧 Test completamente in locale con moto")
    print()
    
    # Interactive mode
    if args.interactive:
        interactive_mode()
        return 0
    
    # Validate args
    if not args.lambda or not args.event:
        print_error("Specificare --lambda e --event (o usa --interactive)")
        parser.print_help()
        return 1
    
    # Resolve paths
    lambda_path = Path(args.lambda)
    if not lambda_path.is_absolute():
        lambda_path = SCRIPT_DIR / lambda_path
    
    event_path = Path(args.event)
    if not event_path.is_absolute():
        if not event_path.exists():
            event_path = EVENTS_DIR / event_path
    
    # Validate
    if not lambda_path.exists():
        print_error(f"Lambda non trovata: {lambda_path}")
        return 1
    
    if not (lambda_path / "app.py").exists():
        print_error(f"app.py non trovato in: {lambda_path}")
        return 1
    
    if not event_path.exists():
        print_error(f"Evento non trovato: {event_path}")
        return 1
    
    # Parse env vars
    env_vars = {}
    if args.env:
        for env_str in args.env:
            try:
                key, value = env_str.split('=', 1)
                env_vars[key.strip()] = value.strip()
            except:
                print_warning(f"Variabile d'ambiente ignorata (formato non valido): {env_str}")
    
    # Load event
    event = load_event(event_path)
    
    # Run test
    print_info(f"Lambda: {lambda_path.name}")
    print_info(f"Evento: {event_path.name}")
    print_info(f"Dati: {'Caricati dal dev' if args.load_data else 'DB vuoto'}")
    print()
    
    with LocalTestEnvironment(load_data=args.load_data) as env:
        env.set_env_vars(env_vars)
        response = env.invoke_lambda(lambda_path, event)
        print_response(response)
    
    print()
    print_success("Test completato!")
    print_info("Il DB dev non è stato toccato 👍")
    
    return 0


if __name__ == '__main__':
    exit(main())
