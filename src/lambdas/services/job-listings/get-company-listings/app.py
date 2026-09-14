"""
Get Company Listings Lambda - Public Endpoint
Retrieve all job listings for a specific company
"""

import json
import os
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])


def decimal_default(obj):
    """Helper function to convert Decimal to float for JSON response"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def calculate_compensation(listing):
    """
    Calculate compensation details from contract.
    Returns a single flat object: base, contingency, superminimo, grossPay.
    """
    contract = listing.get('contract')

    if not contract:
        salary = float(listing.get('salary', 0))
        return {
            'base': salary,
            'contingency': 0.0,
            'superminimo': None,
            'grossPay': salary,
            'currency': 'EUR',
            'displayText': f"€{salary:,.2f}/month" if salary > 0 else 'Contact for details',
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


def format_schedule_display(schedule):
    """Format schedule for display"""
    if not schedule:
        return "Not specified"
    hours_per_week = schedule.get('hoursPerWeek', 0)
    work_time_slots = schedule.get('workTimeSlots', [])

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


def enrich_listing_summary(listing):
    """Enrich listing with summary fields for list view"""
    listing['compensation'] = calculate_compensation(listing)

    # Strip raw calculation details from contract — they are now in compensation
    contract = listing.get('contract')
    if contract:
        contract.pop('calculation', None)
        contract.pop('superminimo', None)

    schedule = listing.get('schedule')
    if schedule:
        listing['scheduleDisplay'] = format_schedule_display(schedule)

    if contract:
        listing['contractDisplay'] = f"CCNL {contract.get('ccnlType', 'Turismo').title()} - {contract.get('levelName', '')} (Par. {contract.get('paragraph', '')})"

    employment = listing.get('employment')
    if employment:
        listing['employmentDisplay'] = employment.get('typeName', employment.get('typeId', ''))

    job_role = listing.get('jobRole')
    if job_role:
        listing['jobRoleDisplay'] = job_role.get('roleName', '')

    return listing


def filter_listings(listings, query_params, is_owner=False):
    """
    Apply filters to listings
    Public users can only see 'published' listings
    Owner can see all statuses
    """
    filtered = listings
    
    # Status filter - public users can ONLY see published
    status_filter = query_params.get('status', 'published')
    if not is_owner:
        # Force published for public users
        filtered = [l for l in filtered if l.get('status') == 'published']
    elif status_filter != 'all':
        filtered = [l for l in filtered if l.get('status') == status_filter]
    
    # Filter by CCNL level
    level_filter = query_params.get('level')
    if level_filter:
        filtered = [l for l in filtered if l.get('contract', {}).get('level') == level_filter]
    
    # Filter by paragraph
    paragraph_filter = query_params.get('paragraph')
    if paragraph_filter:
        filtered = [l for l in filtered if l.get('contract', {}).get('paragraph') == paragraph_filter]
    
    # Date range overlap filter:
    # Un listing è incluso se il suo periodo si SOVRAPPONE al range cercato:
    #   listing.startDate <= ricerca_fine AND listing.endDate >= ricerca_inizio
    start_date_from = query_params.get('startDateFrom')
    start_date_to = query_params.get('startDateTo')
    if start_date_from and start_date_to:
        filtered = [l for l in filtered if l.get('startDate', '') <= start_date_to and l.get('endDate', '') >= start_date_from]
    elif start_date_from:
        filtered = [l for l in filtered if l.get('endDate', '') >= start_date_from]
    elif start_date_to:
        filtered = [l for l in filtered if l.get('startDate', '') <= start_date_to]
    
    # Alloggio filter
    alloggio_filter = query_params.get('alloggio')
    if alloggio_filter and alloggio_filter.lower() == 'true':
        filtered = [l for l in filtered if l.get('alloggio') is True]
    
    # Filter by category
    category_filter = query_params.get('category')
    if category_filter:
        filtered = [l for l in filtered if l.get('category') == category_filter]
    
    return filtered


def sort_listings(listings, sort_by='publishedAt', sort_order='desc'):
    """Sort listings by specified field"""
    reverse = (sort_order == 'desc')
    
    if sort_by == 'compensation':
        def get_compensation_sort_key(listing):
            contract = listing.get('contract', {})
            calculation = contract.get('calculation', {})
            superminimo_obj = contract.get('superminimo', {})

            base = float(calculation.get('basePay', 0))
            contingency = float(calculation.get('contingencyAllowance', 0))
            superminimo_amount = float(superminimo_obj.get('amount', 0)) if superminimo_obj else 0
            return base + contingency + superminimo_amount

        return sorted(listings, key=get_compensation_sort_key, reverse=reverse)
    
    elif sort_by == 'hoursPerWeek':
        return sorted(
            listings,
            key=lambda x: x.get('schedule', {}).get('hoursPerWeek', 0),
            reverse=reverse
        )
    else:
        try:
            return sorted(
                listings,
                key=lambda x: x.get(sort_by, ''),
                reverse=reverse
            )
        except:
            return sorted(
                listings,
                key=lambda x: x.get('publishedAt', ''),
                reverse=reverse
            )


def lambda_handler(event, context):
    """
    Get all job listings for a specific company (PUBLIC endpoint)
    
    GET /listings/company/{companyId}
    
    Public users: see only 'published' listings
    Owner (authenticated): can see all statuses with ?status=all
    
    Query Parameters:
    - status: Filter by status (default: published, owner can use 'all')
    - limit: Items per page (default: 20, max: 100)
    - lastKey: Pagination token (listingId)
    - level: Filter by CCNL level
    - paragraph: Filter by paragraph (I, II)
    - startDateFrom/To: Date range filters
    - category: Filter by category
    - sortBy: Sort field (publishedAt, startDate, compensation)
    - sortOrder: asc or desc (default: desc)
    """
    
    try:
        # Get companyId from path parameters
        company_id = event['pathParameters']['companyId']
        
        # Check if user is authenticated and is the owner
        is_owner = False
        try:
            user_id = event['requestContext']['authorizer']['claims']['sub']
            user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
            
            # Check if user owns this company
            if 'companies' in user_groups:
                company_response = companies_table.get_item(Key={'userId': user_id})
                if 'Item' in company_response:
                    user_company_id = company_response['Item'].get('companyId')
                    is_owner = (user_company_id == company_id)
        except (KeyError, TypeError):
            # Not authenticated - public access
            is_owner = False
        
        # Verify company exists
        try:
            company_response = companies_table.query(
                IndexName='companyId-index',
                KeyConditionExpression=Key('companyId').eq(company_id),
                Limit=1
            )
            
            if not company_response.get('Items'):
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Not Found',
                        'message': 'Company not found'
                    })
                }
            
            company = company_response['Items'][0]
            
        except Exception as e:
            print(f"Error fetching company: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error fetching company information'
                })
            }
        
        # Get query parameters
        query_params = event.get('queryStringParameters') or {}
        limit = int(query_params.get('limit', 20))
        limit = min(max(limit, 1), 100)  # Clamp between 1 and 100
        
        sort_by = query_params.get('sortBy', 'publishedAt')
        sort_order = query_params.get('sortOrder', 'desc')
        
        # Query all listings for this company using companyId-createdAt-index
        try:
            response = job_listings_table.query(
                IndexName='companyId-createdAt-index',
                KeyConditionExpression=Key('companyId').eq(company_id)
            )
            
            all_listings = response.get('Items', [])
            
            # Handle pagination if there are more items
            while 'LastEvaluatedKey' in response:
                response = job_listings_table.query(
                    IndexName='companyId-createdAt-index',
                    KeyConditionExpression=Key('companyId').eq(company_id),
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                all_listings.extend(response.get('Items', []))
            
        except Exception as e:
            print(f"Error querying listings: {str(e)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Internal Server Error',
                    'message': 'Error fetching job listings'
                })
            }
        
        # Apply filters (respecting public/owner access)
        filtered_listings = filter_listings(all_listings, query_params, is_owner)
        
        # Sort listings
        sorted_listings = sort_listings(filtered_listings, sort_by, sort_order)
        
        # Enrich listings with display fields
        enriched_listings = [enrich_listing_summary(listing) for listing in sorted_listings]
        
        # Apply pagination
        total_filtered = len(enriched_listings)
        paginated_listings = enriched_listings[:limit]
        
        # Determine if there are more results
        last_key = None
        if len(enriched_listings) > limit:
            last_listing = paginated_listings[-1]
            last_key = last_listing.get('listingId')
        
        # Convert Decimal to float for JSON response
        listings_json = json.loads(json.dumps(paginated_listings, default=decimal_default))
        
        # Log retrieval
        print(f"Retrieved {len(paginated_listings)} listings for company {company_id}")
        print(f"  - Is owner: {is_owner}")
        print(f"  - Total in DB: {len(all_listings)}")
        print(f"  - After filters: {total_filtered}")
        
        # Build response
        response_data = {
            'success': True,
            'data': {
                'companyId': company_id,
                'companyName': company.get('businessName'),
                'listings': listings_json,
                'count': len(paginated_listings),
                'total': total_filtered
            },
            'pagination': {
                'limit': limit,
                'hasMore': last_key is not None,
                'lastKey': last_key
            },
            'filters': {
                'status': 'published' if not is_owner else query_params.get('status', 'published'),
                'level': query_params.get('level'),
                'paragraph': query_params.get('paragraph'),
                'startDateFrom': query_params.get('startDateFrom'),
                'startDateTo': query_params.get('startDateTo'),
                'category': query_params.get('category')
            },
            'sort': {
                'sortBy': sort_by,
                'sortOrder': sort_order
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
        
    except Exception as e:
        print(f"Error in get company listings: {str(e)}")
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
                'message': 'An error occurred while fetching company listings'
            })
        }