"""
Get My Applicable Job Roles Handler

This Lambda function retrieves all job roles applicable to the authenticated user's company
by scanning the JobRoles table and filtering based on the company's applicableRoles list.

Returns detailed information for each role including:
- roleId
- roleName
- fipeLevel
- fipeLevelName
- category
- roleDescription
"""

import json
import os
import boto3
from decimal import Decimal

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])
job_roles_table = dynamodb.Table(os.environ['JOB_ROLES_TABLE_NAME'])
ateco_categories_table_name = os.environ.get('ATECO_CATEGORIES_TABLE_NAME')
ateco_categories_table = dynamodb.Table(ateco_categories_table_name) if ateco_categories_table_name else None


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def get_company_by_user(user_id):
    """
    Retrieve company profile for the authenticated user
    
    Args:
        user_id (str): Cognito user ID (sub)
        
    Returns:
        dict: Company item or None if not found
    """
    try:
        response = companies_table.get_item(Key={'userId': user_id})
        return response.get('Item')
    except Exception as e:
        print(f"Error fetching company for user {user_id}: {str(e)}")
        return None


def get_applicable_job_roles(applicable_role_ids):
    """
    Scan JobRoles table and filter by applicable role IDs
    
    Args:
        applicable_role_ids (list): List of role IDs from company profile
        
    Returns:
        list: List of job role details
    """
    try:
        # Convert list to set for efficient lookup
        role_ids_set = set(applicable_role_ids)
        
        # Scan the JobRoles table
        job_roles = []
        scan_kwargs = {}
        
        while True:
            response = job_roles_table.scan(**scan_kwargs)
            
            # Filter items that match applicable role IDs
            for item in response.get('Items', []):
                role_id = item.get('roleId')
                if role_id in role_ids_set:
                    job_roles.append({
                        'roleId': role_id,
                        'roleName': item.get('roleName', ''),
                        'fipeLevel': item.get('fipeLevel', ''),
                        'fipeLevelName': item.get('fipeLevelName', ''),
                        'category': item.get('category', ''),
                        'roleDescription': item.get('roleDescription', '')
                    })
            
            # Check if there are more items to scan
            if 'LastEvaluatedKey' not in response:
                break
            
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        # Sort by fipeLevel and roleName for better presentation
        job_roles.sort(key=lambda x: (x.get('fipeLevel', ''), x.get('roleName', '')))
        
        return job_roles
        
    except Exception as e:
        print(f"Error scanning JobRoles table: {str(e)}")
        raise


def get_ateco_info(ateco_code):
    """
    Retrieve ATECO information from AtecoCategories table

    Args:
        ateco_code (str): ATECO code (e.g., "56.11.11")

    Returns:
        dict: ATECO information or None if not found
    """
    if not ateco_categories_table:
        return None

    try:
        response = ateco_categories_table.get_item(
            Key={'atecoCode': ateco_code}
        )
        return response.get('Item')
    except Exception as e:
        print(f"Error fetching ATECO info for {ateco_code}: {str(e)}")
        return None


def is_tourism_or_food_service(ateco_codes):
    """
    Check if any ATECO code belongs to tourism (55.xx.xx) or food service (56.xx.xx) sectors
    
    Args:
        ateco_codes (list): List of ATECO codes
        
    Returns:
        bool: True if at least one code starts with 55 or 56
    """
    if not ateco_codes:
        return False
    
    for code in ateco_codes:
        code = code.strip()
        if code.startswith('55') or code.startswith('56'):
            return True
    
    return False


def aggregate_applicable_roles_from_ateco(ateco_codes):
    """
    Aggregate all applicable job roles from multiple ATECO codes
    ONLY for tourism (55.xx.xx) and food service (56.xx.xx) sectors.

    Args:
        ateco_codes (list): List of ATECO codes

    Returns:
        tuple: (set of roleIds, list of missing codes)
    """
    all_roles = set()
    missing_codes = []

    for ateco_code in ateco_codes:
        ateco_code = ateco_code.strip()
        ateco_info = get_ateco_info(ateco_code)

        if ateco_info:
            applicable_roles = ateco_info.get('applicableRoles', [])
            all_roles.update(applicable_roles)
            print(f"ATECO {ateco_code}: {len(applicable_roles)} roles")
        else:
            missing_codes.append(ateco_code)
            print(f"Warning: ATECO code {ateco_code} not found in database")

    return all_roles, missing_codes


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /companies/my-applicable-job-roles
    Retrieve all job roles applicable to the authenticated user's company.
    
    Returns:
        200: List of applicable job roles with details
        404: Company not found for user
        500: Internal server error
    """
    try:
        # Get user ID from Cognito authorizer
        claims = event['requestContext']['authorizer']['claims']
        user_id = claims['sub']
        
        print(f"Fetching applicable job roles for user: {user_id}")
        
        # Get company profile
        company = get_company_by_user(user_id)
        
        if not company:
            print(f"Company not found for user: {user_id}")
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Not Found',
                    'message': 'No company profile found for this user. Please create a company profile first.'
                })
            }
        
        # Get applicable role IDs from company
        applicable_role_ids = company.get('applicableRoles', [])
        ateco_codes = company.get('atecoCodes', [])

        # Fallback: compute roles from ATECO codes ONLY for tourism/food service sectors
        # For other sectors (non 55.xx.xx or 56.xx.xx), job roles remain free-form fields
        if not applicable_role_ids and ateco_codes:
            if is_tourism_or_food_service(ateco_codes):
                if ateco_categories_table:
                    print("No applicable roles on company record, aggregating from ATECO codes (tourism/food service)")
                    aggregated_roles, missing_codes = aggregate_applicable_roles_from_ateco(ateco_codes)
                    applicable_role_ids = list(aggregated_roles)
                    if missing_codes:
                        print(f"Missing ATECO codes: {missing_codes}")
                else:
                    print("ATECO_CATEGORIES_TABLE_NAME not configured, cannot aggregate roles")
            else:
                print(f"Company ATECO codes {ateco_codes} are not tourism/food service sector - no predefined job roles")

        
        if not applicable_role_ids:
            print(f"No applicable roles found for company: {company.get('companyId')}")
            
            # Determine appropriate message based on sector
            if is_tourism_or_food_service(ateco_codes):
                message = 'No job roles available for your company ATECO codes'
            else:
                message = 'Job roles are not predefined for your business sector - use free-form fields when creating listings'
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'companyId': company.get('companyId'),
                    'businessName': company.get('businessName'),
                    'atecoCodes': ateco_codes,
                    'applicableJobRoles': [],
                    'totalRoles': 0,
                    'message': message
                })
            }
        
        print(f"Company has {len(applicable_role_ids)} applicable role IDs")
        
        # Get detailed job role information
        job_roles = get_applicable_job_roles(applicable_role_ids)
        
        print(f"Found {len(job_roles)} job roles with details")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'companyId': company.get('companyId'),
                'businessName': company.get('businessName'),
                'atecoCodes': ateco_codes,
                'fipeCategory': company.get('fipeCategory'),
                'applicableJobRoles': job_roles,
                'totalRoles': len(job_roles),
                'message': f'Successfully retrieved {len(job_roles)} applicable job roles'
            }, cls=DecimalEncoder)
        }
        
    except Exception as e:
        print(f"Unexpected error retrieving job roles: {str(e)}")
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
                'message': 'An unexpected error occurred while retrieving job roles'
            })
        }