"""
User API - List Job Listing Bookmarks
Recupera tutti i job listing salvati nei bookmark dell'utente

Riutilizza la logica di formattazione e presentazione da job-listings/list-listings
per mantenere consistenza nell'API response.
"""
import json
import os
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from typing import Dict, List, Any, Optional

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE'])

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


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def build_company_logo_url(company_id):
    """Build presigned S3 URL for company logo"""
    if not COMPANIES_BUCKET or not company_id:
        return None
    
    try:
        object_key = f"companies/{company_id}/profile.jpg"
        
        try:
            s3_client.head_object(Bucket=COMPANIES_BUCKET, Key=object_key)
        except s3_client.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                return None
            return None
        
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': COMPANIES_BUCKET, 'Key': object_key},
            ExpiresIn=3600
        )
        
        return presigned_url
        
    except Exception as e:
        print(f"Error generating presigned URL for company {company_id}: {str(e)}")
        return None


def get_companies_data(company_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batch get company data for multiple companies"""
    if not company_ids:
        return {}
    
    try:
        unique_company_ids = list(set(company_ids))
        companies_data = {}
        
        for company_id in unique_company_ids:
            try:
                response = companies_table.query(
                    IndexName='companyId-index',
                    KeyConditionExpression=Key('companyId').eq(company_id),
                    Limit=1
                )
                
                if response.get('Items'):
                    company = response['Items'][0]
                    logo_url = build_company_logo_url(company_id)
                    
                    # Safe access for company location (might be None)
                    company_location = company.get('location') or {}
                    
                    companies_data[company_id] = {
                        'companyId': company.get('companyId'),
                        'businessName': company.get('businessName', ''),
                        'logoUrl': logo_url,
                        'averageRating': float(company.get('averageRating', 0)),
                        'totalReviews': int(company.get('totalReviews', 0)),
                        'city': company_location.get('city', ''),
                        'country': company_location.get('country', '')
                    }
            except Exception as e:
                print(f"Error fetching company {company_id}: {str(e)}")
                companies_data[company_id] = {
                    'companyId': company_id,
                    'businessName': 'Company',
                    'logoUrl': '',
                    'averageRating': 0,
                    'totalReviews': 0,
                    'city': '',
                    'country': ''
                }
        
        return companies_data
        
    except Exception as e:
        print(f"Error in batch get companies: {str(e)}")
        return {}


def calculate_total_compensation(contract: Dict[str, Any], listing: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate total compensation from contract details - handles CCNL and manual listings"""
    try:
        # Handle None contract for manual listings
        if not contract:
            return {
                'minMonthly': 0,
                'maxMonthly': 0,
                'currency': 'EUR',
                'displayText': 'Contact for details',
                'basePay': 0,
                'includesSuperminimo': False
            }
        
        calculation = contract.get('calculation') or {}
        gross_base_pay = float(calculation.get('grossBasePay', 0))
        
        min_monthly = gross_base_pay
        max_monthly = gross_base_pay
        
        superminimo = contract.get('superminimo') or {}
        if superminimo.get('amount'):
            superminimo_amount = float(superminimo['amount'])
            min_monthly += superminimo_amount
            max_monthly += superminimo_amount
        
        currency = superminimo.get('currency', 'EUR')
        if min_monthly == max_monthly:
            display_text = f"€{min_monthly:,.2f}/month"
        else:
            display_text = f"€{min_monthly:,.2f}-€{max_monthly:,.2f}/month"
        
        return {
            'minMonthly': min_monthly,
            'maxMonthly': max_monthly,
            'currency': currency,
            'displayText': display_text,
            'basePay': gross_base_pay,
            'includesSuperminimo': bool(superminimo.get('amount'))
        }
        
    except Exception as e:
        print(f"Error calculating compensation: {str(e)}")
        return {
            'minMonthly': 0,
            'maxMonthly': 0,
            'currency': 'EUR',
            'displayText': 'Contact for details',
            'basePay': 0,
            'includesSuperminimo': False
        }


def format_work_schedule(schedule: Dict[str, Any]) -> str:
    """Format work schedule for display"""
    if not schedule:
        return 'Schedule TBD'
    
    hours_per_week = schedule.get('hoursPerWeek')
    work_time_slots = schedule.get('workTimeSlots', [])
    
    if not hours_per_week:
        return 'Schedule TBD'
    
    schedule_text = f"{hours_per_week} hrs/week"
    
    if work_time_slots:
        shift_types = [slot.get('type') for slot in work_time_slots if slot.get('type')]
        if shift_types:
            primary_type = shift_types[0]
            if primary_type == 'split':
                schedule_text += " • Split shift"
            elif primary_type == 'flexible':
                schedule_text += " • Flexible hours"
    
    return schedule_text


def format_listing_for_ui(listing: Dict[str, Any], company_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Format a listing with company data for UI consumption - supports CCNL and manual listings"""
    # Get contract info - handle None values from DynamoDB
    contract = listing.get('contract')
    
    # Check if this is a manual listing: contract is None
    is_manual = contract is None
    
    # Get other fields safely
    schedule = listing.get('schedule') or {}
    employment = listing.get('employment') or {}
    location = listing.get('location') or {}
    job_role = listing.get('jobRole') or {}
    
    # Calculate compensation based on type
    if is_manual:
        # Manual listing: use simple salary field
        salary = float(listing.get('salary', 0))
        compensation = {
            'minMonthly': salary,
            'maxMonthly': salary,
            'currency': 'EUR',
            'displayText': f"€{salary:,.2f}/month" if salary > 0 else 'Contact for details',
            'basePay': salary,
            'includesSuperminimo': False
        }
    else:
        # CCNL listing: use contract calculation
        compensation = calculate_total_compensation(contract, listing)
    
    # Format location
    location_parts = [
        location.get('city', ''),
        location.get('province', ''),
        location.get('region', ''),
        location.get('country', '')
    ]
    location_str = ", ".join([part for part in location_parts if part])
    
    # Format schedule - both manual and CCNL use schedule object
    schedule_str = format_work_schedule(schedule)
    
    # Build employment type badge
    if is_manual:
        # Manual listing: employmentType is a string
        employment_type = listing.get('employmentType', 'Full-time')
    else:
        # CCNL listing: employment is an object
        employment_type = employment.get('typeName', '') if employment else ''
        if not employment_type and employment and employment.get('typeId'):
            # Try to infer from typeId
            type_id = employment['typeId'].lower()
            if 'full' in type_id:
                employment_type = 'Full-time'
            elif 'part' in type_id:
                employment_type = 'Part-time'
            elif 'seasonal' in type_id:
                employment_type = 'Seasonal'
        if not employment_type:
            employment_type = 'To be defined'
    
    # Company info
    company_info = company_data or {}
    
    # Base response structure
    response = {
        'listingId': listing['listingId'],
        'title': listing.get('title', ''),
        'description': listing.get('description', '')[:200] + '...' if len(listing.get('description', '')) > 200 else listing.get('description', ''),
        
        # Company data
        'company': {
            'companyId': company_info.get('companyId', listing.get('companyId')),
            'name': company_info.get('businessName', 'Company'),
            'logoUrl': company_info.get('logoUrl', ''),
            'rating': company_info.get('averageRating', 0),
            'reviewsCount': company_info.get('totalReviews', 0)
        },
        
        # Job details
        'location': {
            'city': location.get('city', ''),
            'province': location.get('province', ''),
            'region': location.get('region', ''),
            'country': location.get('country', ''),
            'displayText': location_str
        },
        
        # Compensation (works for both manual and CCNL)
        'compensation': compensation,
        
        # Metadata
        'startDate': listing.get('startDate'),
        'endDate': listing.get('endDate'),
        'category': listing.get('category', 'other'),
        'positions': listing.get('positions', 1),
        'publishedAt': listing.get('publishedAt'),
        'status': listing.get('status', 'published'),
        
        # Type indicator
        'ccnlType': listing.get('ccnlType', 'turismo'),
        'isManual': is_manual,
        
        # Benefits
        'isHousingIncluded': listing.get('isHousingIncluded', False),
        
        # Booking/Accommodation info
        'vitto': listing.get('vitto', False),
        'alloggio': listing.get('alloggio', False),
        'alloggioPricePerDay': listing.get('alloggioPricePerDay'),
        'alloggioDescription': listing.get('alloggioDescription', ''),
        'minConsecutiveDays': listing.get('minConsecutiveDays'),
        'minNoticeDays': listing.get('minNoticeDays'),
        
        # Stats
        'viewsCount': listing.get('viewsCount', 0),
        'applicationsCount': listing.get('applicationsCount', 0)
    }
    
    # Add CCNL-specific fields (only if not manual)
    if not is_manual:
        response['contract'] = {
            'level': contract.get('level', ''),
            'levelName': contract.get('levelName', ''),
            'ccnlType': contract.get('ccnlType', ''),
            'paragraph': contract.get('paragraph', ''),
            'displayText': f"CCNL {contract.get('ccnlType', '').title()} - {contract.get('levelName', '')}"
        }
        
        response['employment'] = {
            'typeId': employment.get('typeId', ''),
            'typeName': employment_type,
            'displayText': employment_type
        }
        
        response['jobRole'] = {
            'roleId': job_role.get('roleId', ''),
            'roleName': job_role.get('roleName', ''),
            'category': job_role.get('category', '')
        }
    else:
        # Manual listing fields (simplified)
        response['contractId'] = listing.get('contractId', '')
        response['employmentType'] = employment_type
    
    # Schedule is present for both manual and CCNL listings
    response['schedule'] = {
        'hoursPerWeek': schedule.get('hoursPerWeek') if schedule else None,
        'workDays': schedule.get('workDays', []) if schedule else [],
        'displayText': schedule_str
    }
    
    return response


def handler(event, context):
    """
    GET /bookmarks/job-listings
    Recupera tutti i job listing bookmarked dall'utente
    
    Query parameters:
    - include_inactive: true/false (default: false) - Include job listing non più attivi
    
    Returns formatted listings usando lo stesso formato di list-listings
    """
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        query_params = event.get('queryStringParameters') or {}
        include_inactive = query_params.get('include_inactive', 'false').lower() == 'true'
        
        print(f"[ListBookmarks] User {user_id} requesting bookmarks (inactive={include_inactive})")
        
        # Get user profile with bookmarks
        profile_response = user_profiles_table.get_item(Key={'user_id': user_id})
        
        if 'Item' not in profile_response:
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Not Found',
                    'message': 'User profile not found'
                })
            }
        
        profile = profile_response['Item']
        bookmarked_listing_ids = profile.get('bookmarked_job_listings', [])
        
        # Empty bookmarks case
        if not bookmarked_listing_ids:
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'private, max-age=60'
                },
                'body': json.dumps({
                    'success': True,
                    'data': {
                        'listings': [],
                        'count': 0
                    },
                    'meta': {
                        'totalBookmarked': 0,
                        'includeInactive': include_inactive
                    }
                })
            }
        
        # Fetch all bookmarked job listings
        listings = []
        not_found_count = 0
        filtered_count = 0
        
        for listing_id in bookmarked_listing_ids:
            try:
                response = job_listings_table.get_item(Key={'listingId': listing_id})
                
                if 'Item' in response:
                    listing = response['Item']
                    listing_status = listing.get('status', 'unknown')
                    
                    # Filter non-published listings if requested
                    # Stati: draft, published, paused, closed, archived
                    if not include_inactive and listing_status != 'published':
                        print(f"[ListBookmarks] Skipping {listing_status} listing {listing_id}")
                        filtered_count += 1
                        continue
                    
                    listings.append(listing)
                else:
                    print(f"[ListBookmarks] Listing {listing_id} not found (deleted)")
                    not_found_count += 1
                    
            except Exception as e:
                print(f"[ListBookmarks] Error fetching listing {listing_id}: {str(e)}")
                not_found_count += 1
        
        # Get unique company IDs
        company_ids = [listing['companyId'] for listing in listings if 'companyId' in listing]
        
        # Fetch company data
        companies_data = get_companies_data(company_ids)
        
        # Format listings using the same formatter as list-listings
        formatted_listings = [
            format_listing_for_ui(listing, companies_data.get(listing.get('companyId')))
            for listing in listings
        ]
        
        print(f"[ListBookmarks] Returning {len(formatted_listings)} bookmarks (filtered: {filtered_count}, not found: {not_found_count})")
        
        # Use same response format as list-listings
        response_body = {
            'success': True,
            'data': {
                'listings': formatted_listings,
                'count': len(formatted_listings)
            },
            'meta': {
                'totalBookmarked': len(bookmarked_listing_ids),
                'includeInactive': include_inactive,
                'filtered': filtered_count,  # Quanti sono stati filtrati (paused, closed, etc.)
                'notFound': not_found_count  # Quanti sono stati eliminati
            }
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'private, max-age=60'  # Cache for 1 minute (private per user)
            },
            'body': json.dumps(response_body, cls=DecimalEncoder)
        }
        
    except Exception as e:
        print(f"[ListBookmarks] Error: {str(e)}")
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
