"""
Get Reference Data Handler

This Lambda function retrieves all reference data needed for job listings:
- Job Roles
- Contracts (Contract Types)
- Job Categories
- Employment Types

Public endpoint - no authentication required.
This data is typically cached on the frontend.
"""

import json
import os
import boto3
from decimal import Decimal
from typing import Dict, List, Any

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')

# Reference tables
JOB_ROLES_TABLE = dynamodb.Table(os.environ.get('JOB_ROLES_TABLE_NAME', 'dev-JobRoles'))
CONTRACTS_TABLE = dynamodb.Table(os.environ.get('CONTRACTS_TABLE_NAME', 'dev-Contracts'))
JOB_CATEGORIES_TABLE = dynamodb.Table(os.environ.get('JOB_CATEGORIES_TABLE_NAME', 'dev-JobCategories'))
EMPLOYMENT_TYPES_TABLE = dynamodb.Table(os.environ.get('EMPLOYMENT_TYPES_TABLE_NAME', 'dev-EmploymentTypes'))


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def get_all_items_from_table(table, table_name: str) -> List[Dict[str, Any]]:
    """
    Scan a DynamoDB table and return all items
    
    Args:
        table: DynamoDB table resource
        table_name: Name of the table (for logging)
        
    Returns:
        List of all items in the table
    """
    try:
        items = []
        response = table.scan()
        items.extend(response.get('Items', []))
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            items.extend(response.get('Items', []))
        
        print(f"Retrieved {len(items)} items from {table_name}")
        return items
        
    except Exception as e:
        print(f"Error scanning {table_name}: {str(e)}")
        return []


def format_job_role(role: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format job role for API response
    
    Expected structure in DB:
    - roleId (PK): unique identifier
    - name: role name (e.g., "Chef", "Waiter")
    - category: category it belongs to
    - description: optional description
    - isActive: boolean flag
    """
    return {
        'id': role.get('roleId', ''),
        'name': role.get('name', ''),
        'category': role.get('category', ''),
        'description': role.get('description', ''),
        'isActive': bool(role.get('isActive', True))
    }


def format_contract(contract: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format contract type for API response
    
    Expected structure in DB:
    - contractId (PK): unique identifier
    - name: contract name (e.g., "Full-time", "Part-time", "Freelance")
    - description: optional description
    - isActive: boolean flag
    """
    return {
        'id': contract.get('contractId', ''),
        'name': contract.get('name', ''),
        'description': contract.get('description', ''),
        'isActive': bool(contract.get('isActive', True))
    }


def format_category(category: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format job category for API response
    
    Expected structure in DB:
    - categoryId (PK): unique identifier
    - name: category name (e.g., "Hospitality", "Healthcare")
    - icon: optional icon identifier
    - description: optional description
    - isActive: boolean flag
    """
    return {
        'id': category.get('categoryId', ''),
        'name': category.get('name', ''),
        'icon': category.get('icon', ''),
        'description': category.get('description', ''),
        'isActive': bool(category.get('isActive', True))
    }


def format_employment_type(employment: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format employment type for API response
    
    Expected structure in DB:
    - employmentTypeId (PK): unique identifier
    - name: employment type (e.g., "Permanent", "Temporary", "Seasonal")
    - description: optional description
    - isActive: boolean flag
    """
    return {
        'id': employment.get('employmentTypeId', ''),
        'name': employment.get('name', ''),
        'description': employment.get('description', ''),
        'isActive': bool(employment.get('isActive', True))
    }


def lambda_handler(event, context):
    """
    Lambda handler to get all reference data
    
    Query Parameters:
    - type: Optional filter to get specific type only (jobRoles, contracts, categories, employmentTypes)
    - activeOnly: Optional boolean to filter only active items (default: true)
    
    Returns:
        200: Object containing all reference data
        400: Invalid query parameters
        500: Internal server error
    """
    try:
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        data_type = params.get('type')  # Optional: filter by specific type
        active_only = params.get('activeOnly', 'true').lower() == 'true'
        
        print(f"Get reference data - type: {data_type}, activeOnly: {active_only}")
        
        # Determine which data to fetch
        fetch_all = data_type is None
        
        response_data = {}
        
        # Fetch Job Roles
        if fetch_all or data_type == 'jobRoles':
            job_roles = get_all_items_from_table(JOB_ROLES_TABLE, 'JobRoles')
            formatted_roles = [format_job_role(role) for role in job_roles]
            
            # Filter active only if requested
            if active_only:
                formatted_roles = [role for role in formatted_roles if role['isActive']]
            
            response_data['jobRoles'] = formatted_roles
        
        # Fetch Contracts
        if fetch_all or data_type == 'contracts':
            contracts = get_all_items_from_table(CONTRACTS_TABLE, 'Contracts')
            formatted_contracts = [format_contract(contract) for contract in contracts]
            
            if active_only:
                formatted_contracts = [c for c in formatted_contracts if c['isActive']]
            
            response_data['contracts'] = formatted_contracts
        
        # Fetch Job Categories
        if fetch_all or data_type == 'categories':
            categories = get_all_items_from_table(JOB_CATEGORIES_TABLE, 'JobCategories')
            formatted_categories = [format_category(category) for category in categories]
            
            if active_only:
                formatted_categories = [c for c in formatted_categories if c['isActive']]
            
            response_data['categories'] = formatted_categories
        
        # Fetch Employment Types
        if fetch_all or data_type == 'employmentTypes':
            employment_types = get_all_items_from_table(EMPLOYMENT_TYPES_TABLE, 'EmploymentTypes')
            formatted_employment = [format_employment_type(emp) for emp in employment_types]
            
            if active_only:
                formatted_employment = [e for e in formatted_employment if e['isActive']]
            
            response_data['employmentTypes'] = formatted_employment
        
        # Build response
        response_body = {
            'success': True,
            'data': response_data,
            'meta': {
                'type': data_type or 'all',
                'activeOnly': active_only
            }
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=3600'  # Cache for 1 hour (reference data changes rarely)
            },
            'body': json.dumps(response_body, cls=DecimalEncoder)
        }
        
    except ValueError as e:
        print(f"Invalid parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'message': f'Invalid parameter: {str(e)}'
            })
        }
    except Exception as e:
        print(f"Unexpected error getting reference data: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': 'An unexpected error occurred'
            })
        }