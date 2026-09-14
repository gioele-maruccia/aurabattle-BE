"""
List/Search Job Listings Handler - Updated for CCNL Schema

This Lambda function lists and searches job listings with the new contract structure.
Includes company data (logo, name, rating) for UI display.
Public endpoint - no authentication required.

Key Changes:
- Replaced salary with contract.calculation (base pay details)
- Added contract.superminimo (optional additional pay)
- Removed deprecated fields: tags, features, schedule.flexibility, schedule.shiftType
- Updated to use contract.paragraph and contract.level
- Updated schedule to use workTimeSlots structure
"""

import json
import os
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr
from botocore.config import Config
from typing import Dict, List, Any, Optional

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])

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
        # S3 object key
        object_key = f"companies/{company_id}/profile.jpg"
        
        # Generate public URL (bucket is public, no need for presigned URL)
        public_url = f"https://{COMPANIES_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{object_key}"
        
        print(f"Generated logo URL for company {company_id}: {object_key}")
        return public_url
        
    except Exception as e:
        print(f"Error generating URL for company {company_id}: {str(e)}")
        return None


def get_companies_data(company_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Batch get company data for multiple companies
    
    Args:
        company_ids: List of company IDs to fetch
        
    Returns:
        Dictionary mapping companyId to company data
    """
    if not company_ids:
        return {}
    
    try:
        # Remove duplicates
        unique_company_ids = list(set(company_ids))
        print(f"[get_companies_data] Fetching data for {len(unique_company_ids)} unique companies")
        
        # DynamoDB BatchGetItem can handle max 100 items
        companies_data = {}
        
        # Batch get items (max 100 per request)
        for i in range(0, len(unique_company_ids), 100):
            batch_ids = unique_company_ids[i:i+100]
            print(f"[get_companies_data] Processing batch {i//100 + 1} with {len(batch_ids)} companies")
            
            for company_id in batch_ids:
                try:
                    print(f"[get_companies_data] Querying for company_id={company_id}")
                    response = companies_table.query(
                        IndexName='companyId-index',
                        KeyConditionExpression=Key('companyId').eq(company_id),
                        Limit=1
                    )
                    print(f"[get_companies_data] Query response items: {len(response.get('Items', []))}")
                    
                    if response.get('Items'):
                        company = response['Items'][0]
                        print(f"[get_companies_data] Found company record: {company.get('companyId')}")
                        
                        # Build logo URL from S3
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
                    else:
                        print(f"[get_companies_data] No company found for company_id={company_id}")
                except Exception as e:
                    print(f"[get_companies_data] Error fetching company {company_id}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    # Add placeholder data
                    companies_data[company_id] = {
                        'companyId': company_id,
                        'businessName': 'Company',
                        'logoUrl': '',
                        'averageRating': 0,
                        'totalReviews': 0,
                        'city': '',
                        'country': ''
                    }
        
        print(f"[get_companies_data] Returning data for {len(companies_data)} companies")
        return companies_data
        
    except Exception as e:
        print(f"[get_companies_data] Error in batch get companies: {str(e)}")
        import traceback
        traceback.print_exc()
        return {}


def calculate_total_compensation(contract: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate compensation from contract. Returns base, contingency, superminimo, grossPay.
    """
    try:
        if not contract:
            return {
                'base': 0.0,
                'contingency': 0.0,
                'superminimo': None,
                'grossPay': 0.0,
                'currency': 'EUR',
                'displayText': 'Contact for details',
                'includesSuperminimo': False
            }

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
            'currency': superminimo_obj.get('currency', 'EUR') if superminimo_obj else 'EUR',
            'displayText': f"€{gross_pay:,.2f}/month",
            'includesSuperminimo': superminimo > 0
        }

    except Exception as e:
        print(f"Error calculating compensation: {str(e)}")
        return {
            'base': 0.0,
            'contingency': 0.0,
            'superminimo': None,
            'grossPay': 0.0,
            'currency': 'EUR',
            'displayText': 'Contact for details',
            'includesSuperminimo': False
        }


def format_work_schedule(schedule: Dict[str, Any]) -> str:
    """
    Format work schedule for display
    
    Args:
        schedule: Schedule object with hoursPerWeek and workTimeSlots
        
    Returns:
        Formatted schedule string
    """
    if not schedule:
        return 'Schedule TBD'
    
    hours_per_week = schedule.get('hoursPerWeek')
    work_time_slots = schedule.get('workTimeSlots', [])
    
    if not hours_per_week:
        return 'Schedule TBD'
    
    # Basic hours display
    schedule_text = f"{hours_per_week} hrs/week"
    
    # Add shift type info if available
    if work_time_slots:
        # Count shift types
        shift_types = [slot.get('type') for slot in work_time_slots if slot.get('type')]
        if shift_types:
            primary_type = shift_types[0]
            if primary_type == 'split':
                schedule_text += " • Split shift"
            elif primary_type == 'flexible':
                schedule_text += " • Flexible hours"
    
    return schedule_text


def format_listing_for_ui(listing: Dict[str, Any], company_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Format a listing with company data for UI consumption
    Supports both CCNL and manual (non-FIPE) listings
    
    Args:
        listing: Raw listing from DynamoDB
        company_data: Company data fetched separately
        
    Returns:
        Formatted listing ready for UI
    """
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
            'base': salary,
            'contingency': 0.0,
            'superminimo': None,
            'grossPay': salary,
            'currency': 'EUR',
            'displayText': f"€{salary:,.2f}/month" if salary > 0 else 'Contact for details',
            'includesSuperminimo': False
        }
    else:
        # CCNL listing: use contract calculation
        compensation = calculate_total_compensation(contract or {})
    
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


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /listings?limit=20&cursor=eyJsa...&status=published&category=hospitality
    
    Query Parameters:
    - limit: Items per page (default: 20, max: 50)
    - cursor: Pagination cursor (base64 encoded LastEvaluatedKey)
    - status: Filter by status (default: published)
    - category: Filter by category
    - city: Filter by city
    - province: Filter by province
    - country: Filter by country
    - companyId: Filter by company
    - level: Filter by CCNL level (Qa, Qb, 1-7, 6S)
    - paragraph: Filter by paragraph (I or II)
    - minHoursPerWeek: Minimum hours per week
    - maxHoursPerWeek: Maximum hours per week
    - startDateFrom: Inizio range di date (overlap): mostra listing il cui periodo si sovrappone al range cercato
    - startDateTo: Fine range di date (overlap): mostra listing il cui periodo si sovrappone al range cercato
    - alloggio: Se 'true', filtra solo listing con alloggio disponibile
    - sortBy: Sort field (publishedAt, startDate) - default: publishedAt
    - sortOrder: Sort order (asc, desc) - default: desc
    
    Returns:
        200: List of job listings with company data
        400: Invalid query parameters
        500: Internal server error
    """
    try:
        print(f"[lambda_handler] Starting list-listings request")
        print(f"[lambda_handler] Event: {json.dumps(event, default=str)[:200]}...")
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        print(f"[lambda_handler] Query parameters: {params}")
        
        # Pagination
        limit = min(int(params.get('limit', 20)), 50)  # Max 50 items per request
        cursor = params.get('cursor')
        
        # Filters
        status = params.get('status', 'published')
        category = params.get('category')
        city = params.get('city')
        location_query = params.get('location')
        province = params.get('province')
        country = params.get('country')
        company_id = params.get('companyId')
        
        # NEW: Contract filters
        level = params.get('level')  # Qa, Qb, 1-7, 6S
        paragraph = params.get('paragraph')  # I or II
        
        # NEW: Schedule filters
        min_hours = params.get('minHoursPerWeek')
        max_hours = params.get('maxHoursPerWeek')
        
        # Date filters
        start_date_from = params.get('startDateFrom')
        start_date_to = params.get('startDateTo')
        
        # Alloggio filter
        alloggio_filter = params.get('alloggio')
        
        # Sorting
        sort_by = params.get('sortBy', 'publishedAt')  # publishedAt or startDate
        sort_order = params.get('sortOrder', 'desc')
        scan_index_forward = (sort_order == 'asc')
        
        print(f"List listings - status: {status}, category: {category}, level: {level}, location: {location_query}, limit: {limit}")
        
        # Determine which GSI to use based on filters
        # Priority: category > status
        index_name = None
        key_condition = None
        
        if category:
            # Use category-publishedAt-index
            index_name = 'category-publishedAt-index'
            key_condition = Key('category').eq(category)
        elif status:
            # Use status-publishedAt-index or status-startDate-index
            if sort_by == 'startDate':
                index_name = 'status-startDate-index'
                key_condition = Key('status').eq(status)
            else:
                index_name = 'status-publishedAt-index'
                key_condition = Key('status').eq(status)
        
        # Build query parameters
        query_params = {
            'Limit': limit,
            'ScanIndexForward': scan_index_forward
        }
        
        # Add pagination cursor
        if cursor:
            try:
                import base64
                decoded_cursor = base64.b64decode(cursor).decode('utf-8')
                query_params['ExclusiveStartKey'] = json.loads(decoded_cursor)
            except Exception as e:
                print(f"Invalid cursor: {str(e)}")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'Invalid pagination cursor'
                    })
                }
        
        # Build filter expressions for additional filters
        filter_expressions = []
        expression_values = {}
        expression_names = {}
        
        # Location filters
        if city:
            filter_expressions.append('#loc.#city = :city')
            expression_names['#loc'] = 'location'
            expression_names['#city'] = 'city'
            expression_values[':city'] = city

        if location_query:
            filter_expressions.append('(#loc.#city = :location OR #loc.#province = :location OR #loc.#region = :location)')
            expression_names['#loc'] = 'location'
            expression_names['#city'] = 'city'
            expression_names['#province'] = 'province'
            expression_names['#region'] = 'region'
            expression_values[':location'] = location_query
        
        if province:
            filter_expressions.append('#loc.province = :province')
            expression_names['#loc'] = 'location'
            expression_values[':province'] = province
        
        if country:
            filter_expressions.append('#loc.#country = :country')
            expression_names['#loc'] = 'location'
            expression_names['#country'] = 'country'
            expression_values[':country'] = country
        
        # Company filter
        if company_id:
            filter_expressions.append('companyId = :companyId')
            expression_values[':companyId'] = company_id
        
        # NEW: Contract level filter
        if level:
            filter_expressions.append('#contract.#level = :level')
            expression_names['#contract'] = 'contract'
            expression_names['#level'] = 'level'
            expression_values[':level'] = level
        
        # NEW: Paragraph filter
        if paragraph:
            filter_expressions.append('#contract.paragraph = :paragraph')
            expression_names['#contract'] = 'contract'
            expression_values[':paragraph'] = paragraph
        
        # NEW: Schedule hours filters
        if min_hours:
            filter_expressions.append('#schedule.hoursPerWeek >= :minHours')
            expression_names['#schedule'] = 'schedule'
            expression_values[':minHours'] = int(min_hours)
        
        if max_hours:
            filter_expressions.append('#schedule.hoursPerWeek <= :maxHours')
            expression_names['#schedule'] = 'schedule'
            expression_values[':maxHours'] = int(max_hours)
        
        # Date range overlap filter:
        # Un listing è incluso se il suo periodo si SOVRAPPONE al range cercato:
        #   listing.startDate <= ricerca_fine AND listing.endDate >= ricerca_inizio
        if start_date_from and start_date_to:
            filter_expressions.append('startDate <= :dateSearchTo AND endDate >= :dateSearchFrom')
            expression_values[':dateSearchFrom'] = start_date_from
            expression_values[':dateSearchTo'] = start_date_to
        elif start_date_from:
            # Solo data inizio: listing che terminano dopo la data cercata
            filter_expressions.append('endDate >= :dateSearchFrom')
            expression_values[':dateSearchFrom'] = start_date_from
        elif start_date_to:
            # Solo data fine: listing che iniziano prima della data cercata
            filter_expressions.append('startDate <= :dateSearchTo')
            expression_values[':dateSearchTo'] = start_date_to
        
        # Alloggio filter
        if alloggio_filter and alloggio_filter.lower() == 'true':
            filter_expressions.append('alloggio = :alloggio')
            expression_values[':alloggio'] = True
        
        # Add filter expressions
        if filter_expressions:
            query_params['FilterExpression'] = ' AND '.join(filter_expressions)
            query_params['ExpressionAttributeValues'] = expression_values
            if expression_names:
                query_params['ExpressionAttributeNames'] = expression_names
        
        # Perform query on GSI or scan
        if index_name and key_condition:
            print(f"[lambda_handler] Using index {index_name} for query")
            query_params['IndexName'] = index_name
            query_params['KeyConditionExpression'] = key_condition
            print(f"[lambda_handler] Query params keys: {list(query_params.keys())}")
            response = job_listings_table.query(**query_params)
            print(f"[lambda_handler] Query completed, items found: {len(response.get('Items', []))}")
        else:
            # Fallback to scan (less efficient)
            print("[lambda_handler] Warning: Using scan operation (consider using GSI)")
            response = job_listings_table.scan(**query_params)
            print(f"[lambda_handler] Scan completed, items found: {len(response.get('Items', []))}")
        
        listings = response.get('Items', [])
        print(f"[lambda_handler] Retrieved {len(listings)} listings from DynamoDB")
        
        # Extract unique company IDs
        company_ids = [listing['companyId'] for listing in listings if 'companyId' in listing]
        print(f"[lambda_handler] Extracted company IDs: {len(company_ids)} total (before dedup)")
        
        # Fetch company data in batch
        print(f"[lambda_handler] Calling get_companies_data...")
        companies_data = get_companies_data(company_ids)
        print(f"[lambda_handler] get_companies_data returned {len(companies_data)} companies")
        
        # Format listings for UI
        print(f"[lambda_handler] Formatting {len(listings)} listings for UI...")
        formatted_listings = [
            format_listing_for_ui(listing, companies_data.get(listing.get('companyId')))
            for listing in listings
        ]
        print(f"[lambda_handler] Formatted {len(formatted_listings)} listings")
        
        # Build pagination cursor
        next_cursor = None
        if response.get('LastEvaluatedKey'):
            import base64
            cursor_json = json.dumps(response['LastEvaluatedKey'], cls=DecimalEncoder)
            next_cursor = base64.b64encode(cursor_json.encode('utf-8')).decode('utf-8')
        
        # Build response
        response_body = {
            'success': True,
            'data': {
                'listings': formatted_listings,
                'count': len(formatted_listings),
                'hasMore': next_cursor is not None,
                'nextCursor': next_cursor
            },
            'meta': {
                'limit': limit,
                'filters': {
                    'status': status,
                    'category': category,
                    'city': city,
                    'location': location_query,
                    'province': province,
                    'country': country,
                    'companyId': company_id,
                    'level': level,
                    'paragraph': paragraph,
                    'minHoursPerWeek': min_hours,
                    'maxHoursPerWeek': max_hours
                }
            }
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=300'  # Cache for 5 minutes
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
        print(f"Unexpected error listing jobs: {str(e)}")
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
                'message': 'An unexpected error occurred',
                'details': error_details  # Include detailed error for debugging
            })
        }