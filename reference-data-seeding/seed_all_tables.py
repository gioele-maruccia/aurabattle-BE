#!/usr/bin/env python3
"""
Unified Seed Script - Configuration-Driven Approach
Aggiunto supporto per FIPE Job Roles Catalog
"""

import json
import argparse
import boto3
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import sys

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')

# Paths
CONFIG_DIR = Path(__file__).parent / 'config'
COMMON_MODULE_DIR = Path(__file__).parent.parent / 'modules' / 'common-beebusy'


class DecimalEncoder(json.JSONEncoder):
    """Helper to encode Decimal for JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def convert_to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB"""
    if isinstance(obj, list):
        return [convert_to_decimal(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: convert_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, float):
        return Decimal(str(obj))
    else:
        return obj


def load_json_config(filename: str, use_common_module: bool = False) -> Dict:
    """
    Load and parse JSON configuration file
    
    Args:
        filename: Name of the JSON file to load
        use_common_module: If True, load from common-beebusy module instead of config dir
    """
    if use_common_module:
        config_path = COMMON_MODULE_DIR / filename
    else:
        config_path = CONFIG_DIR / filename
    
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def add_timestamps(item: Dict) -> Dict:
    """Add createdAt and updatedAt timestamps"""
    now = datetime.utcnow().isoformat() + 'Z'
    item['createdAt'] = now
    item['updatedAt'] = now
    return item


def seed_fipe_job_roles(environment: str, dry_run: bool = False) -> tuple:
    """
    Seed FipeJobRoles table from fipe_job_roles_catalog.json
    
    Returns:
        (success_count, error_count, errors_list)
    """
    print("\n" + "="*70)
    print("👔 SEEDING FIPE JOB ROLES CATALOG")
    print("="*70)
    
    table_name = f'{environment}-JobRoles'
    config = load_json_config('fipe_job_roles_catalog.json')
    
    roles = config.get('jobRoles', [])
    
    print(f"Configuration version: {config.get('version')}")
    print(f"Source: {config.get('source')}")
    print(f"Total FIPE roles: {len(roles)}")
    print(f"Level distribution: {config.get('metadata', {}).get('levelDistribution', {})}")
    
    if dry_run:
        print("\n🔍 DRY RUN - No data will be inserted")
        # Group by level for preview
        by_level = {}
        for role in roles:
            level = role['fipeLevel']
            by_level.setdefault(level, []).append(role)
        
        for level in sorted(by_level.keys(), key=lambda x: (x if isinstance(x, str) and x.startswith('Q') else int(x) if x.isdigit() else x)):
            print(f"\n  Level {level} ({len(by_level[level])} roles):")
            for role in by_level[level][:3]:  # Show first 3
                print(f"    - {role['roleId']}: {role['roleName']}")
            if len(by_level[level]) > 3:
                print(f"    ... and {len(by_level[level]) - 3} more")
        
        return len(roles), 0, []
    
    table = dynamodb.Table(table_name)
    success_count = 0
    error_count = 0
    errors = []
    
    for role in roles:
        try:
            # Use roleId as partition key
            item = role.copy()
            
            # Convert floats to Decimal (minSubordinates se presente)
            item = convert_to_decimal(item)
            
            # Insert into DynamoDB
            table.put_item(Item=item)
            
            print(f"  ✅ {role['roleId']} - {role['roleName']} (Level {role['fipeLevel']})")
            success_count += 1
            
        except Exception as e:
            error_msg = f"{role['roleId']}: {str(e)}"
            print(f"  ❌ {error_msg}")
            errors.append(error_msg)
            error_count += 1
    
    return success_count, error_count, errors


def seed_ateco_categories(environment: str, dry_run: bool = False) -> tuple:
    """
    Seed AtecoCategories table from ateco_categories.json
    Struttura: atecoMappings con applicableRoles per ogni ATECO
    
    Returns:
        (success_count, error_count, errors_list)
    """
    print("\n" + "="*70)
    print("🏢 SEEDING ATECO CATEGORIES (with FIPE roles mapping)")
    print("="*70)
    
    table_name = f'{environment}-AtecoCategories'
    config = load_json_config('ateco_categories.json', use_common_module=True)
    
    # Nuova struttura: atecoMappings invece di atecoCategories
    mappings = config.get('atecoMappings', [])
    
    print(f"Configuration version: {config.get('version')}")
    print(f"Last updated: {config.get('lastUpdated')}")
    print(f"ATECO codes to insert: {len(mappings)}")
    
    if dry_run:
        print("\n🔍 DRY RUN - No data will be inserted")
        for mapping in mappings:
            roles_count = len(mapping.get('applicableRoles', []))
            typical_count = len(mapping.get('typicalRoles', []))
            print(f"  - {mapping['atecoCode']}: {mapping['atecoDescription'][:50]}...")
            print(f"    → Sector: {mapping['sector']} | Category: {mapping['fipeCategory']}")
            print(f"    → {roles_count} applicable roles ({typical_count} typical)")
        return len(mappings), 0, []
    
    table = dynamodb.Table(table_name)
    success_count = 0
    error_count = 0
    errors = []
    
    for mapping in mappings:
        try:
            # Usa atecoCode come partition key
            item = mapping.copy()
            
            # Aggiungi timestamps
            item = add_timestamps(item)
            
            # Convert floats to Decimal (if any)
            item = convert_to_decimal(item)
            
            # Insert into DynamoDB
            table.put_item(Item=item)
            
            roles_count = len(mapping.get('applicableRoles', []))
            print(f"  ✅ {mapping['atecoCode']} - {mapping['atecoDescription'][:40]}... ({roles_count} roles)")
            success_count += 1
            
        except Exception as e:
            error_msg = f"{mapping['atecoCode']}: {str(e)}"
            print(f"  ❌ {error_msg}")
            errors.append(error_msg)
            error_count += 1
    
    return success_count, error_count, errors


def seed_contracts(environment: str, dry_run: bool = False) -> tuple:
    """
    Seed Contracts table from contracts_ccnl_turismo.json
    
    Returns:
        (success_count, error_count, errors_list)
    """
    print("\n" + "="*70)
    print("📋 SEEDING CONTRACTS (CCNL)")
    print("="*70)
    
    table_name = f'{environment}-Contracts'
    config = load_json_config('contracts_ccnl_turismo.json')
    
    contracts = config.get('contracts', [])
    
    print(f"Configuration version: {config.get('version')}")
    print(f"Last updated: {config.get('lastUpdated')}")
    print(f"CCNL Type: {config.get('ccnlType')}")
    print(f"Contracts to insert: {len(contracts)}")
    
    if dry_run:
        print("\n🔍 DRY RUN - No data will be inserted")
        for contract in contracts:
            print(f"  - {contract['contractId']} (Level: {contract['level']})")
        return len(contracts), 0, []
    
    table = dynamodb.Table(table_name)
    success_count = 0
    error_count = 0
    errors = []
    
    for contract in contracts:
        try:
            # Add timestamps
            item = add_timestamps(contract.copy())
            
            # Convert floats to Decimal
            item = convert_to_decimal(item)
            
            # Insert into DynamoDB
            table.put_item(Item=item)
            
            print(f"  ✅ {contract['contractId']} - {contract['level']}")
            success_count += 1
            
        except Exception as e:
            error_msg = f"{contract['contractId']}: {str(e)}"
            print(f"  ❌ {error_msg}")
            errors.append(error_msg)
            error_count += 1
    
    return success_count, error_count, errors


def seed_employment_types(environment: str, dry_run: bool = False) -> tuple:
    """
    Seed EmploymentTypes table from employment_types.json
    
    Returns:
        (success_count, error_count, errors_list)
    """
    print("\n" + "="*70)
    print("💼 SEEDING EMPLOYMENT TYPES")
    print("="*70)
    
    table_name = f'{environment}-EmploymentTypes'
    config = load_json_config('employment_types.json')
    
    types = config.get('employmentTypes', [])
    
    print(f"Configuration version: {config.get('version')}")
    print(f"Last updated: {config.get('lastUpdated')}")
    print(f"Employment types to insert: {len(types)}")
    
    if dry_run:
        print("\n🔍 DRY RUN - No data will be inserted")
        for emp_type in types:
            print(f"  - {emp_type['typeId']}: {emp_type['typeName']}")
        return len(types), 0, []
    
    table = dynamodb.Table(table_name)
    success_count = 0
    error_count = 0
    errors = []
    
    for emp_type in types:
        try:
            item = add_timestamps(emp_type.copy())
            item = convert_to_decimal(item)
            
            table.put_item(Item=item)
            
            print(f"  ✅ {emp_type['typeId']} - {emp_type['typeName']}")
            success_count += 1
            
        except Exception as e:
            error_msg = f"{emp_type['typeId']}: {str(e)}"
            print(f"  ❌ {error_msg}")
            errors.append(error_msg)
            error_count += 1
    
    return success_count, error_count, errors


def print_summary(results: Dict[str, tuple]):
    """Print final summary of all seeding operations"""
    print("\n" + "="*70)
    print("📊 SEEDING SUMMARY")
    print("="*70)
    
    total_success = 0
    total_errors = 0
    
    for table, (success, errors, error_list) in results.items():
        total_success += success
        total_errors += errors
        
        status = "✅" if errors == 0 else "⚠️"
        print(f"{status} {table}:")
        print(f"   Success: {success}")
        print(f"   Errors:  {errors}")
        
        if error_list:
            print("   Failed items:")
            for error in error_list[:3]:  # Show first 3 errors
                print(f"     - {error}")
            if len(error_list) > 3:
                print(f"     ... and {len(error_list) - 3} more")
    
    print("\n" + "="*70)
    print(f"TOTAL SUCCESS: {total_success}")
    print(f"TOTAL ERRORS:  {total_errors}")
    print("="*70)


def main():
    parser = argparse.ArgumentParser(
        description='Seed DynamoDB tables from JSON configuration files'
    )
    parser.add_argument(
        '--environment',
        required=True,
        choices=['dev', 'dev-be', 'prod'],
        help='Environment (dev, dev-be or prod)'
    )
    parser.add_argument(
        '--table',
        choices=['contracts', 'categories', 'employment', 'ateco', 'fipe', 'all'],
        default='all',
        help='Which table to seed (default: all)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be inserted without actually inserting'
    )
    parser.add_argument(
        '--region',
        default='eu-south-1',
        help='AWS region (default: eu-south-1)'
    )
    
    args = parser.parse_args()
    
    # Set AWS region
    boto3.setup_default_session(region_name=args.region)
    
    print("╔" + "="*68 + "╗")
    print("║" + " "*15 + "BEEZEY REFERENCE DATA SEEDING" + " "*24 + "║")
    print("╚" + "="*68 + "╝")
    print(f"\nEnvironment: {args.environment}")
    print(f"Region: {args.region}")
    print(f"Tables: {args.table}")
    if args.dry_run:
        print("Mode: DRY RUN (no actual changes)")
    print("")
    
    results = {}
    
    try:
        # Seed based on --table argument
        if args.table in ['contracts', 'all']:
            results['Contracts'] = seed_contracts(args.environment, args.dry_run)
        
        if args.table in ['employment', 'all']:
            results['EmploymentTypes'] = seed_employment_types(args.environment, args.dry_run)
        
        if args.table in ['ateco', 'all']:
            results['AtecoCategories'] = seed_ateco_categories(args.environment, args.dry_run)
        
        if args.table in ['fipe', 'all']:
            results['FipeJobRoles'] = seed_fipe_job_roles(args.environment, args.dry_run)
        
        # Print summary
        print_summary(results)
        
        # Exit with error code if any errors occurred
        total_errors = sum(r[1] for r in results.values())
        if total_errors > 0:
            sys.exit(1)
        
        print("\n✅ Seeding completed successfully!")
        
    except FileNotFoundError as e:
        print(f"\n❌ ERROR: {e}")
        print("\nMake sure the config/ directory exists with the following files:")
        print("  - contracts_ccnl_turismo.json")
        print("  - job_categories.json")
        print("  - employment_types.json")
        print("  - fipe_job_roles_catalog.json")
        print("\nAnd the modules/common-beebusy/ directory with:")
        print("  - ateco_categories.json (shared with frontend)")
        sys.exit(1)
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()