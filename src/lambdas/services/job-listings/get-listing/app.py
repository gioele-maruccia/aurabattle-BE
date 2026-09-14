"""
Updated Get Job Listing Lambda
Aligned with CCNL Turismo contract schema and new job listing structure
"""

import json
import os
from decimal import Decimal
import boto3
from botocore.config import Config

# Initialize DynamoDB and Cognito
dynamodb = boto3.resource('dynamodb')
cognito_client = boto3.client('cognito-idp')

job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])

# Extract Cognito User Pool ID from ARN
COGNITO_USER_POOL_ARN = os.environ.get('COGNITO_USER_POOL_ARN', '')
USER_POOL_ID = COGNITO_USER_POOL_ARN.split('/')[-1] if COGNITO_USER_POOL_ARN else None

# S3 configuration for company assets
COMPANIES_BUCKET = os.environ.get('COMPANIES_BUCKET_NAME', '')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-south-1')

s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    endpoint_url=f"https://s3.{AWS_REGION}.amazonaws.com",
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"}
    ),
)


# Tax constants for net salary estimation (mirrored from calculate-base-pay)
_IRPEF_RATE = 0.23
_IRPEF_DETRAZIONE_LAVORO = 1880.0  # detrazione per redditi da lavoro dipendente
_INPS_RATE = 0.0919


def decimal_default(obj):
    """Helper function to convert Decimal to float for JSON response"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def calculate_estimated_net(gross_base_pay):
    """
    Stima il netto mensile partendo dal lordo totale (include già superminimo).
    Formula identica a quella usata in calculate-base-pay lambda.
    """
    total_gross = gross_base_pay
    if total_gross <= 0:
        return 0.0
    annual_gross = total_gross * 12
    irpef_annual = max(0.0, annual_gross * _IRPEF_RATE - _IRPEF_DETRAZIONE_LAVORO)
    irpef_monthly = irpef_annual / 12
    inps_monthly = total_gross * _INPS_RATE
    net = total_gross - irpef_monthly - inps_monthly
    return round(net, 2)


def get_user_profile(user_id):
    """
    Get user profile information from Cognito
    Returns: dict with userId, firstName, lastName, profileImage
    """
    try:
        response = cognito_client.admin_get_user(
            UserPoolId=USER_POOL_ID,
            Username=user_id
        )
        
        # Extract user attributes
        attributes = {attr['Name']: attr['Value'] for attr in response.get('UserAttributes', [])}
        
        return {
            'userId': user_id,
            'firstName': attributes.get('given_name', ''),
            'lastName': attributes.get('family_name', ''),
            'profileImage': attributes.get('picture', attributes.get('custom:profileImage', None))
        }
    except Exception as e:
        print(f"Error fetching user profile for {user_id}: {str(e)}")
        return {
            'userId': user_id,
            'firstName': None,
            'lastName': None,
            'profileImage': None
        }


def build_company_logo_url(company_id):
    """
    Build public S3 URL for company logo
    Structure: s3://{bucket}/companies/{companyId}/profile.jpg
    Returns: Public HTTPS URL to the logo
    
    Note: Since the bucket has public read access, we use direct URLs
    instead of presigned URLs for better performance and caching.
    """
    if not COMPANIES_BUCKET or not company_id:
        return None
    
    try:
        object_key = f"companies/{company_id}/profile.jpg"
        
        # Generate public URL (bucket is public, no need for presigned URL)
        public_url = f"https://{COMPANIES_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{object_key}"
        
        print(f"Generated logo URL for company {company_id}: {object_key}")
        return public_url
        
    except Exception as e:
        print(f"Error generating URL for company {company_id}: {str(e)}")
        return None


def calculate_compensation(listing):
    """
    Calculate compensation details from contract.
    Returns a flat object: base, contingency, superminimo, grossPay, estimatedNet.
    """
    contract = listing.get('contract')

    if not contract:
        # Manual listing: use simple salary field
        salary = float(listing.get('salary', 0))
        return {
            'base': salary,
            'contingency': 0.0,
            'superminimo': None,
            'grossPay': salary,
            'estimatedNet': calculate_estimated_net(salary),
            'currency': 'EUR',
            'displayText': f"€{salary:,.2f}/month" if salary > 0 else 'Contact for details'
        }

    # CCNL listing
    calculation = contract.get('calculation') or {}
    superminimo_obj = contract.get('superminimo') or {}

    base = float(calculation.get('basePay', 0))
    contingency = float(calculation.get('contingencyAllowance', 0))
    superminimo = float(superminimo_obj.get('amount', 0)) if superminimo_obj else 0.0
    gross_pay = base + contingency + superminimo

    return {
        'base': base,
        'contingency': contingency,
        'superminimo': superminimo if superminimo > 0 else None,
        'grossPay': gross_pay,
        'estimatedNet': calculate_estimated_net(gross_pay),
        'currency': superminimo_obj.get('currency', 'EUR') if superminimo_obj else 'EUR',
        'displayText': f"€{gross_pay:,.2f}/month"
    }


def format_schedule_display(schedule):
    """
    Format schedule for display
    Returns: human-readable schedule string
    """
    if not schedule:
        return "Schedule not specified"
    hours_per_week = schedule.get('hoursPerWeek', 0)
    work_time_slots = schedule.get('workTimeSlots', [])
    
    # Determine shift type from workTimeSlots
    shift_type = "Variable"
    if work_time_slots:
        first_slot = work_time_slots[0]
        slot_type = first_slot.get('type', 'single')
        
        if slot_type == 'single':
            shift_type = "Single shift"
        elif slot_type == 'split':
            shift_type = "Split shift"
        elif slot_type == 'flexible':
            shift_type = "Flexible"
    
    return f"{hours_per_week} hrs/week • {shift_type}"


def enrich_listing_response(listing):
    """
    Enrich listing with calculated fields and formatted data
    Handles both CCNL and manual listings with None values
    """
    # Calculate compensation and replace with single clean object
    listing['compensation'] = calculate_compensation(listing)

    # Strip raw calculation details from contract — they are now in compensation
    contract = listing.get('contract')
    if contract:
        contract.pop('calculation', None)
        contract.pop('superminimo', None)

    # Format schedule display (safe for None)
    schedule = listing.get('schedule')
    if schedule:
        listing['schedule']['displayText'] = format_schedule_display(schedule)

    # Add contract display text (safe for None)
    if contract:
        listing['contract']['displayText'] = f"CCNL {contract.get('ccnlType', 'Turismo').title()} - {contract.get('levelName', '')}"
    
    # Add employment display text (safe for None)
    employment = listing.get('employment')
    if employment:
        listing['employment']['displayText'] = employment.get('typeName', employment.get('typeId', ''))
    
    # Add location display text (safe for None)
    location = listing.get('location')
    if location:
        city = location.get('city', '')
        country = location.get('country', '')
        listing['location']['displayText'] = f"{city}, {country}" if city and country else city or country or ''
    
    return listing


def lambda_handler(event, context):
    """
    Get job listing details by ID
    
    GET /listings/{listingId}
    
    Public endpoint - no authentication required
    Returns complete job listing with:
    - Full contract details (CCNL calculation, superminimo)
    - Job role information
    - Detailed schedule with workTimeSlots
    - Company information with logo and recruiter details
    - Calculated compensation
    """
    
    try:
        # Get listingId from path parameters
        listing_id = event['pathParameters']['listingId']
        
        # Get job listing from DynamoDB
        try:
            response = job_listings_table.get_item(Key={'listingId': listing_id})
            
            if 'Item' not in response:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Not Found',
                        'message': 'Job listing not found'
                    })
                }
            
            listing = response['Item']
            
        except Exception as e:
            print(f"Error fetching listing: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error fetching job listing'
                })
            }
        
        # Enrich listing with calculated fields
        listing = enrich_listing_response(listing)
        
        # Get company information
        company = None
        
        try:
            company_response = companies_table.query(
                IndexName='companyId-index',
                KeyConditionExpression='companyId = :companyId',
                ExpressionAttributeValues={':companyId': listing['companyId']}
            )
            
            if company_response['Items']:
                company_full = company_response['Items'][0]
                
                # Get recruiter info from Cognito
                recruiter_info = None
                user_id = company_full.get('userId')
                if user_id:
                    recruiter_info = get_user_profile(user_id)
                
                # Build logo URL from S3
                company_id = company_full.get('companyId')
                logo_url = build_company_logo_url(company_id)
                
                # Return public company information
                company = {
                    'companyId': company_full['companyId'],
                    'businessName': company_full.get('businessName'),
                    'description': company_full.get('description'),
                    'logoUrl': logo_url,
                    'location': company_full.get('location'),
                    'averageRating': company_full.get('averageRating'),
                    'totalReviews': company_full.get('totalReviews'),
                    'recruiterInfo': recruiter_info
                }
            
        except Exception as e:
            print(f"Error fetching company: {str(e)}")
            company = None
        
        # Convert Decimal to float for JSON response
        listing_json = json.loads(json.dumps(listing, default=decimal_default))
        company_json = json.loads(json.dumps(company, default=decimal_default)) if company else None
        
        # Log successful retrieval
        print(f"Retrieved listing {listing_id}")
        print(f"  - Title: {listing.get('title')}")
        print(f"  - Status: {listing.get('status')}")
        # Safe access for manual listings with None values
        contract = listing.get('contract') or {}
        compensation = listing.get('compensation') or {}
        print(f"  - Contract: {contract.get('levelName')} (Paragraph {contract.get('paragraph')})")
        print(f"  - Compensation: {compensation.get('displayText')}")
        # Log alloggio fields for debugging
        print(f"  - vitto: {listing.get('vitto')}")
        print(f"  - alloggio: {listing.get('alloggio')}")
        print(f"  - alloggioDescription: {listing.get('alloggioDescription')}")
        print(f"  - alloggioPricePerDay: {listing.get('alloggioPricePerDay')}")
        
        # Prepare response
        response_data = {
            'success': True,
            'data': {
                'listing': listing_json,
                'company': company_json
            }
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=300'  # Cache for 5 minutes
            },
            'body': json.dumps(response_data)
        }
        
    except KeyError as e:
        print(f"KeyError: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'message': 'Missing listingId in path parameters'
            })
        }
    
    except Exception as e:
        print(f"Error in get listing: {str(e)}")
        import traceback
        print("Full traceback:")
        traceback.print_exc()
        error_details = traceback.format_exc()
        print(f"Error details: {error_details}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': 'An error occurred while fetching the job listing',
                'details': error_details  # Include detailed error for debugging
            })
        }