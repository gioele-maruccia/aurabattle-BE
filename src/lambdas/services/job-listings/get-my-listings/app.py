"""
Updated Get My Listings Lambda
Aligned with CCNL Turismo contract schema and new job listing structure
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
    """
    Format schedule for display
    Returns: human-readable schedule string
    """
    if not schedule:
        return "Not specified"
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


def enrich_listing_summary(listing):
    """
    Enrich listing with summary fields for list view
    Returns listing with added display fields
    """
    # Calculate compensation and replace with single clean object
    listing['compensation'] = calculate_compensation(listing)

    # Strip raw calculation details from contract — they are now in compensation
    contract = listing.get('contract')
    if contract:
        contract.pop('calculation', None)
        contract.pop('superminimo', None)

    # Format schedule display
    schedule = listing.get('schedule')
    if schedule:
        listing['scheduleDisplay'] = format_schedule_display(schedule)

    # Add contract display text
    if contract:
        listing['contractDisplay'] = f"CCNL {contract.get('ccnlType', 'Turismo').title()} - {contract.get('levelName', '')} (Par. {contract.get('paragraph', '')})"

    # Add employment display text
    employment = listing.get('employment')
    if employment:
        listing['employmentDisplay'] = employment.get('typeName', employment.get('typeId', ''))

    # Add job role display
    job_role = listing.get('jobRole')
    if job_role:
        listing['jobRoleDisplay'] = job_role.get('roleName', '')
    
    return listing


def calculate_stats(listings):
    """
    Calculate aggregate statistics from listings
    Updated to work with new schema
    """
    stats = {
        'total': len(listings),
        'byStatus': {
            'draft': 0,
            'published': 0,
            'paused': 0,
            'closed': 0,
            'archived': 0
        },
        'byLevel': {},  # NEW: Stats by CCNL level
        'byParagraph': {  # NEW: Stats by paragraph
            'I': 0,
            'II': 0
        },
        'totalViews': 0,
        'totalApplications': 0,
        'averageViewsPerListing': 0,
        'totalPositions': 0,
        'averageCompensation': 0  # NEW: Average monthly compensation
    }
    
    total_compensation = 0
    compensation_count = 0
    
    for listing in listings:
        # Status stats
        status = listing.get('status', 'draft')
        stats['byStatus'][status] = stats['byStatus'].get(status, 0) + 1
        
        # Level stats
        contract = listing.get('contract') or {}
        level = contract.get('level')
        if level:
            stats['byLevel'][level] = stats['byLevel'].get(level, 0) + 1
        
        # Paragraph stats
        paragraph = contract.get('paragraph')
        if paragraph in ['I', 'II']:
            stats['byParagraph'][paragraph] += 1
        
        # Views and applications
        stats['totalViews'] += listing.get('viewsCount', 0)
        stats['totalApplications'] += listing.get('applicationsCount', 0)
        
        # Positions
        stats['totalPositions'] += listing.get('positions', 0)
        
        # Compensation stats - handle both CCNL and manual listings
        total_monthly = 0
        
        if contract:
            # CCNL listing
            calculation = contract.get('calculation') or {}
            superminimo_obj = contract.get('superminimo') or {}
            if calculation:
                base = float(calculation.get('basePay', 0))
                contingency = float(calculation.get('contingencyAllowance', 0))
                superminimo_amount = float(superminimo_obj.get('amount', 0)) if superminimo_obj else 0
                total_monthly = base + contingency + superminimo_amount
        else:
            # Manual listing - use salary field
            salary = listing.get('salary')
            if salary:
                total_monthly = float(salary)
        
        if total_monthly > 0:
            total_compensation += total_monthly
            compensation_count += 1
    
    # Calculate averages
    if stats['total'] > 0:
        stats['averageViewsPerListing'] = round(stats['totalViews'] / stats['total'], 2)
    
    if compensation_count > 0:
        stats['averageCompensation'] = round(total_compensation / compensation_count, 2)
    
    return stats


def filter_listings(listings, query_params):
    """
    Apply filters to listings
    Updated with new CCNL filters
    """
    filtered = listings
    
    # Filter by status
    status_filter = query_params.get('status', 'all')
    if status_filter != 'all':
        filtered = [l for l in filtered if l.get('status') == status_filter]
    
    # Filter by CCNL level
    level_filter = query_params.get('level')
    if level_filter:
        filtered = [l for l in filtered if (l.get('contract') or {}).get('level') == level_filter]
    
    # Filter by paragraph
    paragraph_filter = query_params.get('paragraph')
    if paragraph_filter:
        filtered = [l for l in filtered if (l.get('contract') or {}).get('paragraph') == paragraph_filter]
    
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
    
    # Filter by job role
    role_filter = query_params.get('roleId')
    if role_filter:
        filtered = [l for l in filtered if (l.get('jobRole') or {}).get('roleId') == role_filter]
    
    # Filter by hours per week range
    min_hours = query_params.get('minHoursPerWeek')
    if min_hours:
        try:
            min_hours = int(min_hours)
            filtered = [l for l in filtered if (l.get('schedule') or {}).get('hoursPerWeek', 0) >= min_hours]
        except ValueError:
            pass
    
    max_hours = query_params.get('maxHoursPerWeek')
    if max_hours:
        try:
            max_hours = int(max_hours)
            filtered = [l for l in filtered if (l.get('schedule') or {}).get('hoursPerWeek', 999) <= max_hours]
        except ValueError:
            pass
    
    # Search in title and description
    search_term = query_params.get('search', '').lower()
    if search_term:
        filtered = [
            l for l in filtered 
            if search_term in l.get('title', '').lower() 
            or search_term in l.get('description', '').lower()
            or search_term in (l.get('jobRole') or {}).get('roleName', '').lower()
        ]
    
    return filtered


def sort_listings(listings, sort_by='createdAt', sort_order='desc'):
    """
    Sort listings by specified field
    Updated to support new fields
    """
    reverse = (sort_order == 'desc')
    
    # Special handling for nested fields
    if sort_by == 'level':
        # Sort by contract level
        def get_level_sort_key(listing):
            level = (listing.get('contract') or {}).get('level', '')
            # Convert level to sortable format (Qa, Qb, 1-7, 6S)
            level_order = {'Qa': 0, 'Qb': 1, '1': 2, '2': 3, '3': 4, '4': 5, '5': 6, '6S': 7, '6': 8, '7': 9}
            return level_order.get(level, 99)
        
        return sorted(listings, key=get_level_sort_key, reverse=reverse)
    
    elif sort_by == 'compensation':
        # Sort by total monthly compensation
        def get_compensation_sort_key(listing):
            contract = listing.get('contract') or {}
            calculation = contract.get('calculation') or {}
            superminimo_obj = contract.get('superminimo') or {}

            base = float(calculation.get('basePay', 0))
            contingency = float(calculation.get('contingencyAllowance', 0))
            superminimo_amount = float(superminimo_obj.get('amount', 0)) if superminimo_obj else 0
            return base + contingency + superminimo_amount
        
        return sorted(listings, key=get_compensation_sort_key, reverse=reverse)
    
    elif sort_by == 'hoursPerWeek':
        # Sort by hours per week
        return sorted(
            listings,
            key=lambda x: (x.get('schedule') or {}).get('hoursPerWeek', 0),
            reverse=reverse
        )
    
    else:
        # Standard field sorting
        try:
            return sorted(
                listings,
                key=lambda x: x.get(sort_by, ''),
                reverse=reverse
            )
        except:
            # Fallback to createdAt
            return sorted(
                listings,
                key=lambda x: x.get('createdAt', ''),
                reverse=reverse
            )


def lambda_handler(event, context):
    """
    Get all job listings for the authenticated company
    
    GET /listings/my
    
    Authorization: Cognito JWT (company user only)
    
    Shows all statuses: draft, published, paused, closed, archived
    Returns enriched listings with:
    - Calculated compensation from contract
    - Formatted display strings
    - Complete contract details
    - Job role information
    - Schedule summaries
    
    New query parameters:
    - level: Filter by CCNL level (Qa, Qb, 1-7, 6S)
    - paragraph: Filter by paragraph (I, II)
    - minHoursPerWeek: Filter by minimum hours
    - maxHoursPerWeek: Filter by maximum hours
    - roleId: Filter by job role ID
    """
    
    try:
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        # Check if user is in 'companies' group
        if 'companies' not in user_groups:
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Forbidden',
                    'message': 'Only company users can access this endpoint'
                })
            }
        
        # Get company info
        try:
            company_response = companies_table.get_item(Key={'userId': user_id})
            if 'Item' not in company_response:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Not Found',
                        'message': 'Company profile not found'
                    })
                }
            
            company = company_response['Item']
            company_id = company['companyId']
            
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
        limit = int(query_params.get('limit', 50))
        limit = min(max(limit, 1), 100)  # Clamp between 1 and 100
        
        sort_by = query_params.get('sortBy', 'createdAt')
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
        
        # Calculate stats on ALL listings (before filtering)
        stats = calculate_stats(all_listings)
        
        # Apply filters
        filtered_listings = filter_listings(all_listings, query_params)
        
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
        stats_json = json.loads(json.dumps(stats, default=decimal_default))
        
        # Log retrieval
        print(f"Retrieved {len(paginated_listings)} listings for company {company_id}")
        print(f"  - Total in DB: {len(all_listings)}")
        print(f"  - After filters: {total_filtered}")
        print(f"  - Stats: {stats['byStatus']}")
        
        # Build response
        response_data = {
            'success': True,
            'data': {
                'listings': listings_json,
                'count': len(paginated_listings),
                'total': total_filtered
            },
            'stats': stats_json,
            'pagination': {
                'limit': limit,
                'hasMore': last_key is not None,
                'lastKey': last_key
            },
            'filters': {
                'status': query_params.get('status', 'all'),
                'level': query_params.get('level'),
                'paragraph': query_params.get('paragraph'),
                'startDateFrom': query_params.get('startDateFrom'),
                'startDateTo': query_params.get('startDateTo'),
                'search': query_params.get('search'),
                'category': query_params.get('category'),
                'roleId': query_params.get('roleId'),
                'minHoursPerWeek': query_params.get('minHoursPerWeek'),
                'maxHoursPerWeek': query_params.get('maxHoursPerWeek')
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
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_data)
        }
        
    except Exception as e:
        print(f"Error in get my listings: {str(e)}")
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
                'message': 'An error occurred while fetching your job listings'
            })
        }