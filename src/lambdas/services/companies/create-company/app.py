"""
Create Company Profile Handler - Updated with ATECO List & Job Roles Aggregation

This Lambda function creates a complete company profile in DynamoDB including:
- Multiple ATECO codes (primary + secondary)
- Aggregated applicableRoles from all ATECO codes
- FIPE category determination based on primary ATECO code
- Automatic compensation table assignment
"""

import json
import os
import boto3
from datetime import datetime
from decimal import Decimal
import uuid
import re

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])
ateco_categories_table = dynamodb.Table(os.environ['ATECO_CATEGORIES_TABLE_NAME'])


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def validate_company_data(data):
    """
    Validate required fields for company creation
    
    Args:
        data (dict): Company data from request body
        
    Returns:
        tuple: (is_valid, error_message)
    """
    # Required fields
    required_fields = ['businessName', 'vatNumber', 'address', 'atecoCodes']
    
    for field in required_fields:
        if field not in data or not data[field]:
            return False, f"Missing required field: {field}"
    
    # Validate businessName length
    business_name = data['businessName'].strip()
    if len(business_name) < 2 or len(business_name) > 200:
        return False, "businessName must be between 2 and 200 characters"
    
    # Validate vatNumber format (IT + 11 digits)
    vat_number = data['vatNumber'].strip()
    vat_pattern = r'^IT[0-9]{11}$'
    if not re.match(vat_pattern, vat_number):
        return False, "vatNumber must follow format: IT + 11 digits (e.g., IT12345678901)"
    
    # Validate address structure
    address = data['address']
    required_address_fields = ['street', 'city', 'postalCode', 'country']
    for field in required_address_fields:
        if field not in address or not address[field]:
            return False, f"Missing required address field: {field}"
    
    # Validate atecoCodes (must be a list with at least one code)
    ateco_codes = data['atecoCodes']
    if not isinstance(ateco_codes, list) or len(ateco_codes) == 0:
        return False, "atecoCodes must be a non-empty list"
    
    # Validate each ATECO code format (XX.XX.XX)
    ateco_pattern = r'^[0-9]{2}\.[0-9]{2}\.[0-9]{2}$'
    for ateco_code in ateco_codes:
        if not re.match(ateco_pattern, ateco_code.strip()):
            return False, f"Invalid ATECO code format: {ateco_code}. Must be XX.XX.XX (e.g., 56.11.11)"
    
    # Validate PEC format if provided
    if 'pec' in data and data['pec']:
        pec = data['pec'].strip()
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, pec):
            return False, "Invalid PEC email format"
    
    # Validate businessType if provided (for ATECO codes starting with 56)
    # MODIFICATO: businessType è ora opzionale per permettere a tutte le PIVA di registrarsi
    if 'businessType' in data and data['businessType']:
        valid_business_types = ['pubblici_esercizi', 'ristorazione_collettiva']
        if data['businessType'] not in valid_business_types:
            return False, f"businessType must be one of: {', '.join(valid_business_types)}"
    
    # Validate isSmallBusiness if provided
    if 'isSmallBusiness' in data and not isinstance(data['isSmallBusiness'], bool):
        return False, "isSmallBusiness must be a boolean"
    
    return True, None


def get_ateco_info(ateco_code):
    """
    Retrieve ATECO information from AtecoCategories table
    
    Args:
        ateco_code (str): ATECO code (e.g., "56.11.11")
        
    Returns:
        dict: ATECO information or None if not found
    """
    try:
        response = ateco_categories_table.get_item(
            Key={'atecoCode': ateco_code}
        )
        return response.get('Item')
    except Exception as e:
        print(f"Error fetching ATECO info for {ateco_code}: {str(e)}")
        return None


def aggregate_applicable_roles(ateco_codes):
    """
    Aggregate all applicable job roles from multiple ATECO codes
    
    Args:
        ateco_codes (list): List of ATECO codes
        
    Returns:
        tuple: (set of roleIds, dict of ATECO info by code, list of missing codes)
    """
    all_roles = set()  # Use set to avoid duplicates
    ateco_info_map = {}
    missing_codes = []
    
    for ateco_code in ateco_codes:
        ateco_code = ateco_code.strip()
        ateco_info = get_ateco_info(ateco_code)
        
        if ateco_info:
            ateco_info_map[ateco_code] = {
                'atecoDescription': ateco_info.get('atecoDescription', ''),
                'sector': ateco_info.get('sector', ''),
                'fipeCategory': ateco_info.get('fipeCategory', '')
            }
            
            # Add all applicable roles from this ATECO
            applicable_roles = ateco_info.get('applicableRoles', [])
            all_roles.update(applicable_roles)
            
            print(f"ATECO {ateco_code}: {len(applicable_roles)} roles")
        else:
            missing_codes.append(ateco_code)
            print(f"Warning: ATECO code {ateco_code} not found in database")
    
    return all_roles, ateco_info_map, missing_codes


def determine_fipe_category(ateco_code, business_type=None, is_small_business=False):
    """
    Determine FIPE category and compensation table based on primary ATECO and business type
    
    MODIFICATO: Supporta anche aziende NON del settore turismo/ristorazione (ATECO diversi da 55.xx.xx e 56.xx.xx)
    Per queste aziende, restituisce None per i campi FIPE e permetterà inserimento manuale nei job listing
    
    Args:
        ateco_code (str): Primary ATECO code
        business_type (str): Type of business ('pubblici_esercizi' or 'ristorazione_collettiva')
        is_small_business (bool): Whether company has <15 employees (Art. 162)
        
    Returns:
        dict: FIPE classification details (None per settori non turismo/ristorazione)
    """
    # STEP 1: Check if it's accommodation sector (ATECO 55.xx.xx)
    if ateco_code.startswith('55'):
        fipe_category = 'turismo'
        fipe_article = 'Settore Turismo - Alloggio'
        increment_schedule = 'giugno'
        
        # Determine compensation table
        if is_small_business:
            compensation_table = 'aziende_minori'
            table_name = f'Tabella Aziende Minori - {fipe_category}'
            fipe_article += ' + Art. 162'
        else:
            compensation_table = 'standard'
            table_name = 'Tabella Standard'
    
    # STEP 2: Check if it's food service sector (ATECO 56.xx.xx)
    elif ateco_code.startswith('56'):
        # MODIFICATO: Se business_type non è fornito, significa che l'azienda
        # non vuole usare il CCNL Turismo, quindi restituiamo None
        if business_type is None:
            return {
                'fipeCategory': None,
                'fipeArticle': None,
                'compensationTable': None,
                'tableName': None,
                'incrementSchedule': None
            }
        
        # Check for collective catering (mense/catering continuativo)
        if business_type == 'ristorazione_collettiva':
            fipe_category = 'ristorazione_collettiva'
            fipe_article = 'Art. 1, II'
            increment_schedule = 'settembre'
        else:
            fipe_category = 'pubblici_esercizi'
            fipe_article = 'Art. 1, I'
            increment_schedule = 'giugno'
        
        # Determine compensation table
        if is_small_business:
            compensation_table = 'aziende_minori'
            table_name = f'Tabella Aziende Minori - {fipe_category}'
            fipe_article += ' + Art. 162'
        else:
            if fipe_category == 'ristorazione_collettiva':
                compensation_table = 'ristorazione_collettiva'
                table_name = 'Tabella Ristorazione Collettiva'
            else:
                compensation_table = 'standard'
                table_name = 'Tabella Standard'
    
    # STEP 3: Aziende di ALTRI SETTORI (non turismo/ristorazione)
    # Per queste aziende non si applica il CCNL Turismo, quindi restituiamo None
    else:
        return {
            'fipeCategory': None,
            'fipeArticle': None,
            'compensationTable': None,
            'tableName': None,
            'incrementSchedule': None
        }
    
    return {
        'fipeCategory': fipe_category,
        'fipeArticle': fipe_article,
        'compensationTable': compensation_table,
        'tableName': table_name,
        'incrementSchedule': increment_schedule
    }


def create_company_item(user_id, data, ateco_info_map, applicable_roles, fipe_classification):
    """
    Create complete company item structure for DynamoDB
    
    Args:
        user_id (str): Cognito user ID (sub)
        data (dict): Company data from request
        ateco_info_map (dict): Map of ATECO codes to their info
        applicable_roles (set): Set of all applicable role IDs
        fipe_classification (dict): FIPE category determination result
        
    Returns:
        dict: Company item ready for DynamoDB
    """
    now = datetime.utcnow().isoformat() + 'Z'
    company_id = str(uuid.uuid4())
    
    # Primary ATECO is the first one
    primary_ateco = data['atecoCodes'][0].strip()
    primary_ateco_info = ateco_info_map.get(primary_ateco, {})
    
    # Build complete company item
    company = {
        'userId': user_id,
        'companyId': company_id,
        
        # Basic business information
        'businessName': data['businessName'].strip(),
        'vatNumber': data['vatNumber'].strip(),
        'pec': data.get('pec', '').strip() if data.get('pec') else None,
        
        # Address information
        'address': {
            'street': data['address']['street'].strip(),
            'city': data['address']['city'].strip(),
            'province': data['address'].get('province', '').strip(),
            'postalCode': data['address']['postalCode'].strip(),
            'country': data['address']['country'].strip()
        },
        
        # ATECO codes - LIST of all codes
        'atecoCodes': [code.strip() for code in data['atecoCodes']],
        'primaryAtecoCode': primary_ateco,
        'atecoName': primary_ateco_info.get('atecoDescription', ''),
        
        # Aggregated applicable job roles - STRINGSET for DynamoDB
        'applicableRoles': list(applicable_roles),  # Convert set to list for JSON
        
        # ATECO details map
        'atecoDetails': ateco_info_map,
        
        # FIPE classification (based on primary ATECO)
        'fipeCategory': fipe_classification['fipeCategory'],
        'fipeArticle': fipe_classification['fipeArticle'],
        'tableName': fipe_classification['tableName'],
        
        # Business size information
        'isSmallBusiness': data.get('isSmallBusiness', False),
        'numberOfEmployees': data.get('numberOfEmployees'),
        'annualRevenue': data.get('annualRevenue'),
        
        # Business type details
        'businessTypeDetails': {
            'businessType': data.get('businessType'),
            'sector': primary_ateco_info.get('sector')
        },
        
        # Additional fields
        'description': data.get('description', ''),
        'location': {
            'city': data['address']['city'],
            'country': data['address']['country']
        },
        
        # Media
        'media': {
            'profileImageUrl': '',
            'galleryImages': []
        },
        
        # Stats
        'stats': {
            'averageRating': Decimal('0'),
            'totalReviews': 0,
            'activeListingsCount': 0
        },
        
        # Timestamps
        'createdAt': now,
        'updatedAt': now
    }
    
    return company


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    POST /companies
    Create a complete company profile with multiple ATECO codes and aggregated job roles.
    
    Request body:
    {
        "businessName": "Ristorante Da Mario",
        "vatNumber": "IT12345678901",
        "address": {
            "street": "Via Roma 123",
            "city": "Milano",
            "province": "MI",
            "postalCode": "20100",
            "country": "IT"
        },
        "pec": "info@pec.ristorante.it",  // optional
        "atecoCodes": ["56.10.11", "56.30.00"],  // REQUIRED: list with primary + secondary
        "businessType": "pubblici_esercizi",  // required for ATECO 56.xx.xx
        "isSmallBusiness": false,
        "numberOfEmployees": 8,
        "annualRevenue": 500000  // optional
    }
    
    Returns:
        201: Company created successfully
        400: Invalid request data
        404: Primary ATECO code not found
        409: Company already exists for this user
        500: Internal server error
    """
    try:
        # Get user ID from Cognito authorizer
        claims = event['requestContext']['authorizer']['claims']
        user_id = claims['sub']
        
        print(f"Creating company for user: {user_id}")
        
        # Parse request body
        body = json.loads(event['body'])
        
        # Validate input data
        is_valid, error_msg = validate_company_data(body)
        if not is_valid:
            print(f"Validation failed: {error_msg}")
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': error_msg
                })
            }
        
        # Check if company already exists for this user
        try:
            response = companies_table.get_item(Key={'userId': user_id})
            if 'Item' in response:
                # Ignore soft-deleted companies (check status field)
                if response['Item'].get('status') == 'deleted':
                    print(f"Found soft-deleted company for user {user_id}, allowing recreation")
                else:
                    print(f"Company already exists for user: {user_id}")
                    return {
                        'statusCode': 409,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'error': 'Conflict',
                            'message': 'A company profile already exists for this user',
                            'companyId': response['Item']['companyId']
                        })
                    }
        except Exception as e:
            print(f"Error checking existing company: {str(e)}")
            raise
        
        # Aggregate applicable roles from all ATECO codes
        ateco_codes = body['atecoCodes']
        applicable_roles, ateco_info_map, missing_codes = aggregate_applicable_roles(ateco_codes)
        
        print(f"Aggregated {len(applicable_roles)} unique job roles from {len(ateco_codes)} ATECO codes")
        
        # MODIFICATO: Non bloccare più se il codice ATECO non esiste nel database
        # Permettiamo la registrazione di qualsiasi PIVA, anche con codici ATECO non mappati
        primary_ateco = ateco_codes[0].strip()
        if primary_ateco not in ateco_info_map:
            print(f"Warning: Primary ATECO code {primary_ateco} not found in database - allowing registration anyway")
        
        # Warning for missing secondary codes (but don't fail)
        if missing_codes:
            print(f"Warning: {len(missing_codes)} ATECO codes not found in database: {missing_codes}")
        
        # Determine FIPE category and compensation table (based on primary ATECO)
        fipe_classification = determine_fipe_category(
            ateco_code=primary_ateco,
            business_type=body.get('businessType'),
            is_small_business=body.get('isSmallBusiness', False)
        )
        
        print(f"FIPE classification: {fipe_classification}")
        
        # Create complete company item
        company = create_company_item(
            user_id=user_id,
            data=body,
            ateco_info_map=ateco_info_map,
            applicable_roles=applicable_roles,
            fipe_classification=fipe_classification
        )
        
        # Save to DynamoDB
        companies_table.put_item(Item=company)
        
        print(f"Company created successfully: {company['companyId']}")
        print(f"  - ATECO codes: {len(company['atecoCodes'])}")
        print(f"  - Applicable roles: {len(company['applicableRoles'])}")
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Company profile created successfully',
                'company': company,
                'fipeClassification': {
                    'category': fipe_classification['fipeCategory'],
                    'article': fipe_classification['fipeArticle'],
                    'table': fipe_classification['tableName']
                },
                'rolesInfo': {
                    'totalApplicableRoles': len(applicable_roles),
                    'atecoCodesProcessed': len(ateco_info_map),
                    'missingAtecoCodes': missing_codes if missing_codes else []
                },
                'nextSteps': {
                    'description': 'Your company profile is complete. You can now create job listings.',
                    'availableRoles': f'{len(applicable_roles)} job roles available for your business'
                }
            }, cls=DecimalEncoder)
        }
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'message': 'Invalid JSON in request body'
            })
        }
    except KeyError as e:
        print(f"Missing required field: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'message': f'Missing required field: {str(e)}'
            })
        }
    except Exception as e:
        print(f"Unexpected error creating company: {str(e)}")
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
                'message': 'An unexpected error occurred while creating the company profile'
            })
        }