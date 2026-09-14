"""
Updated Update Job Listing Lambda
Aligned with CCNL Turismo contract schema and new structure
"""

import json
import os
import boto3
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple

dynamodb = boto3.resource('dynamodb')
cognito = boto3.client('cognito-idp')
lambda_client = boto3.client('lambda')

ENVIRONMENT = os.environ['ENVIRONMENT']
JOB_LISTINGS_TABLE = os.environ['JOB_LISTINGS_TABLE_NAME']
COMPANIES_TABLE = os.environ['COMPANIES_TABLE_NAME']
BOOKINGS_TABLE = os.environ.get('BOOKINGS_TABLE_NAME', f'{ENVIRONMENT}-Bookings')
CHATS_TABLE = os.environ.get('CHATS_TABLE_NAME', f'{ENVIRONMENT}-Chats')

job_listings_table = dynamodb.Table(JOB_LISTINGS_TABLE)
companies_table = dynamodb.Table(COMPANIES_TABLE)
bookings_table = dynamodb.Table(BOOKINGS_TABLE)
chats_table = dynamodb.Table(CHATS_TABLE)

# Valid CCNL Turismo levels
VALID_LEVELS = ['Qa', 'Qb', '1', '2', '3', '4', '5', '6S', '6', '7']


def decimal_default(obj):
    """Helper function to convert Decimal to float for JSON response"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

# Valid paragraphs
VALID_PARAGRAPHS = ['I', 'II']


class JobListingValidator:
    """Validates job listing data against schema and reference tables"""
    
    def __init__(self, environment: str):
        """
        Initialize validator with DynamoDB connection
        
        Args:
            environment: Environment name (dev, staging, prod)
        """
        self.environment = environment
        self.dynamodb = boto3.resource('dynamodb')
        
        # Reference table names
        self.job_categories_table = self.dynamodb.Table(f'{environment}-JobCategories')
        self.job_roles_table = self.dynamodb.Table(f'{environment}-JobRoles')
        self.contracts_table = self.dynamodb.Table(f'{environment}-Contracts')
        self.employment_types_table = self.dynamodb.Table(f'{environment}-EmploymentTypes')
        
    def validate_listing_update(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate job listing update data (partial validation - only validates provided fields)
        
        Args:
            data: Job listing data to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Validate field formats (only for fields that are present)
        validation_result = self._validate_field_formats_partial(data)
        if not validation_result[0]:
            return validation_result
        
        # Validate reference data if provided
        validation_result = self._validate_references_partial(data)
        if not validation_result[0]:
            return validation_result
        
        # Validate business logic
        validation_result = self._validate_business_logic_partial(data)
        if not validation_result[0]:
            return validation_result
        
        return True, None
    
    def _validate_field_formats_partial(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate field formats and types (only for fields present in update)"""
        
        # Validate title length if present
        if 'title' in data:
            title = data.get('title', '')
            if not isinstance(title, str) or len(title.strip()) < 3:
                return False, "Title must be at least 3 characters long"
            if len(title) > 200:
                return False, "Title must be at most 200 characters long"
        
        # Validate description length if present
        if 'description' in data:
            description = data.get('description', '')
            if not isinstance(description, str) or len(description.strip()) < 10:
                return False, "Description must be at least 10 characters long"
            if len(description) > 5000:
                return False, "Description must be at most 5000 characters long"
        
        # Validate responsibilities length if present
        if 'responsibilities' in data:
            responsibilities = data.get('responsibilities', '')
            if responsibilities and len(responsibilities) > 5000:
                return False, "Responsibilities must be at most 5000 characters long"
        
        # Validate requirements length if present
        if 'requirements' in data:
            requirements = data.get('requirements', '')
            if requirements and len(requirements) > 5000:
                return False, "Requirements must be at most 5000 characters long"
        
        # Validate benefits length if present
        if 'benefits' in data:
            benefits = data.get('benefits', '')
            if benefits and len(benefits) > 5000:
                return False, "Benefits must be at most 5000 characters long"
        
        # Validate dates if both are provided
        if 'startDate' in data and 'endDate' in data:
            try:
                start_date = datetime.fromisoformat(data['startDate'].replace('Z', '+00:00'))
                end_date = datetime.fromisoformat(data['endDate'].replace('Z', '+00:00'))
                
                if end_date <= start_date:
                    return False, "End date must be after start date"
            except (ValueError, AttributeError):
                return False, "Invalid date format. Use ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)"
        
        # Validate positions if present
        if 'positions' in data:
            try:
                positions = int(data['positions'])
                if positions < 1:
                    return False, "Positions must be at least 1"
                if positions > 1000:
                    return False, "Positions must be at most 1000"
            except (ValueError, TypeError):
                return False, "Positions must be a valid integer"
        
        # Validate contract if present
        if 'contract' in data:
            contract = data.get('contract')
            
            # Only validate if contract is not None
            if contract is not None:
                if not isinstance(contract, dict):
                    return False, "Contract must be an object or null"
                
                # Validate level if present - MODIFICATO: solo per ccnlType=turismo
                if 'level' in contract:
                    level = contract.get('level')
                    ccnl_type = contract.get('ccnlType', 'turismo')
                    if ccnl_type == 'turismo' and level not in VALID_LEVELS:
                        return False, f"Invalid contract level: {level}. Must be one of: {', '.join(VALID_LEVELS)}"
                
                # Validate paragraph if present - MODIFICATO: solo per ccnlType=turismo
                if 'paragraph' in contract:
                    paragraph = contract.get('paragraph')
                    ccnl_type = contract.get('ccnlType', 'turismo')
                    if ccnl_type == 'turismo' and paragraph not in VALID_PARAGRAPHS:
                        return False, f"Invalid paragraph: {paragraph}. Must be 'I' or 'II'"
                
                # Validate ccnlType if present - MODIFICATO: permette anche 'manuale'
                if 'ccnlType' in contract:
                    ccnl_type = contract.get('ccnlType')
                    if ccnl_type not in ['turismo', 'manuale']:
                        return False, f"Invalid ccnlType: {ccnl_type}. Must be 'turismo' or 'manuale'"
                
                # Validate contractId format if present - MODIFICATO: solo per ccnlType=turismo
                if 'contractId' in contract:
                    contract_id = contract.get('contractId', '')
                    level = contract.get('level', '')
                    ccnl_type = contract.get('ccnlType', 'turismo')
                    
                    if level and ccnl_type == 'turismo':
                        expected_contract_id = f"CCNL#{ccnl_type}#{level}"
                        if not contract_id.startswith(expected_contract_id):
                            return False, f"Invalid contractId format. Expected to start with: {expected_contract_id}"
                
                # Validate calculation if present
                if 'calculation' in contract:
                    calculation = contract.get('calculation', {})
                    try:
                        if 'basePay' in calculation:
                            base_pay = float(calculation.get('basePay', 0))
                            if base_pay < 0:
                                return False, "Base pay must be positive"
                        
                        if 'contingencyAllowance' in calculation:
                            contingency = float(calculation.get('contingencyAllowance', 0))
                            if contingency < 0:
                                return False, "Contingency allowance must be positive"
                        
                        if 'grossBasePay' in calculation:
                            gross_base = float(calculation.get('grossBasePay', 0))
                            if gross_base < 0:
                                return False, "Gross base pay must be positive"
                        
                        # Validate calculation accuracy if all components are present
                        if all(k in calculation for k in ['basePay', 'contingencyAllowance', 'grossBasePay']):
                            base_pay = float(calculation['basePay'])
                            contingency = float(calculation['contingencyAllowance'])
                            gross_base = float(calculation['grossBasePay'])
                            
                            calculated_gross = base_pay + contingency
                            if 'article162Reduction' in calculation:
                                calculated_gross -= float(calculation['article162Reduction'])
                            
                            # Account for superminimo: calculate-base-pay includes it in grossBasePay
                            superminimo_obj = contract.get('superminimo') or {}
                            superminimo_amount = float(superminimo_obj.get('amount', 0)) if superminimo_obj else 0.0
                            calculated_gross = round(calculated_gross + superminimo_amount, 2)
                            
                            # Allow small floating point differences
                            if abs(calculated_gross - gross_base) > 0.01:
                                return False, f"Gross base pay calculation mismatch: expected {calculated_gross:.2f}, got {gross_base:.2f}"
                                
                    except (ValueError, TypeError) as e:
                        return False, f"Invalid calculation values: {str(e)}"
                
                # Validate coefficient if present
                if 'coefficient' in contract:
                    try:
                        coeff = float(contract['coefficient'])
                        if coeff < 0:
                            return False, "Coefficient must be positive"
                    except (ValueError, TypeError):
                        return False, "Invalid coefficient value"
                
                # Validate superminimo if present
                if 'superminimo' in contract:
                    superminimo = contract['superminimo']
                    try:
                        amount = float(superminimo.get('amount', 0))
                        if amount < 0:
                            return False, "Superminimo amount must be positive"
                        
                        if 'currency' in superminimo:
                            if superminimo.get('currency') not in ['EUR', 'USD', 'GBP']:
                                return False, "Superminimo currency must be EUR, USD, or GBP"
                            
                    except (ValueError, TypeError):
                        return False, "Invalid superminimo values"
        
        # Validate schedule if present
        if 'schedule' in data:
            schedule = data.get('schedule')
            
            # Only validate if schedule is not None
            if schedule is not None:
                if not isinstance(schedule, dict):
                    return False, "Schedule must be an object or null"
                
                if 'hoursPerWeek' in schedule:
                    try:
                        hours_per_week = int(schedule.get('hoursPerWeek', 0))
                        if hours_per_week < 1 or hours_per_week > 168:
                            return False, "Hours per week must be between 1 and 168"
                    except (ValueError, TypeError):
                        return False, "Invalid hours per week"
                
                # Validate workTimeSlots structure if present
                if 'workTimeSlots' in schedule:
                    work_time_slots = schedule.get('workTimeSlots', [])
                    if not isinstance(work_time_slots, list):
                        return False, "Work time slots must be an array"
                    
                    for slot_entry in work_time_slots:
                        if not isinstance(slot_entry, dict):
                            return False, "Each work time slot entry must be an object"
                        
                        if 'type' in slot_entry:
                            if slot_entry['type'] not in ['single', 'split', 'flexible']:
                                return False, f"Work time slot type must be one of: single, split, flexible"
                        
                        if 'days' in slot_entry:
                            if not isinstance(slot_entry['days'], list):
                                return False, "Work time slot 'days' must be an array"
                            
                            valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                            for day in slot_entry['days']:
                                if day.lower() not in valid_days:
                                    return False, f"Invalid day in workTimeSlot: {day}"
                
                # Validate workDays if present
                if 'workDays' in schedule:
                    work_days = schedule['workDays']
                    if not isinstance(work_days, list):
                        return False, "Work days must be an array"
                    
                    valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                    for day in work_days:
                        if day.lower() not in valid_days:
                            return False, f"Invalid work day: {day}"
        
        # Validate location coordinates if present
        if 'location' in data:
            location = data.get('location')
            
            # Only validate if location is not None
            if location is not None:
                if not isinstance(location, dict):
                    return False, "Location must be an object or null"
                
                if 'coordinates' in location:
                    coords = location['coordinates']
                    
                    # Only validate if coordinates is not None
                    if coords is not None:
                        if not isinstance(coords, dict):
                            return False, "Coordinates must be an object or null"
                        
                        if 'lat' in coords:
                            try:
                                lat = float(coords['lat'])
                                if lat < -90 or lat > 90:
                                    return False, "Latitude must be between -90 and 90"
                            except (ValueError, TypeError):
                                return False, "Invalid latitude value"
                        
                        if 'lon' in coords:
                            try:
                                lon = float(coords['lon'])
                                if lon < -180 or lon > 180:
                                    return False, "Longitude must be between -180 and 180"
                            except (ValueError, TypeError):
                                return False, "Invalid longitude value"
        
        # Validate status if present
        if 'status' in data:
            valid_statuses = ['draft', 'published', 'closed', 'archived']
            if data['status'] not in valid_statuses:
                return False, f"Status must be one of: {', '.join(valid_statuses)}"
        
        return True, None
    
    def _validate_references_partial(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate that referenced IDs exist in reference tables (only if provided in update)"""
        
        try:
            # Validate category if provided
            if 'category' in data:
                category_id = data.get('category')
                if category_id is not None and category_id != '':
                    response = self.job_categories_table.get_item(Key={'categoryId': category_id})
                    if 'Item' not in response:
                        return False, f"Invalid category: '{category_id}' does not exist in JobCategories"
                    
                    if not response['Item'].get('isActive', True):
                        return False, f"Category '{category_id}' is not active"
            
            # Validate jobRole if provided
            if 'jobRole' in data:
                job_role = data.get('jobRole')
                if job_role is not None:
                    if not isinstance(job_role, dict):
                        return False, "jobRole must be an object or null"
                    
                    role_id = job_role.get('roleId')
                    if role_id is not None and role_id != '':
                        response = self.job_roles_table.get_item(Key={'roleId': role_id})
                        if 'Item' not in response:
                            return False, f"Invalid jobRole: '{role_id}' does not exist in JobRoles"
                        
                        if not response['Item'].get('isActive', True):
                            return False, f"Job role '{role_id}' is not active"
            
            # Validate contract if provided
            if 'contract' in data:
                contract_data = data.get('contract')
                if contract_data is not None:
                    if not isinstance(contract_data, dict):
                        return False, "contract must be an object or null"
                    
                    contract_id = contract_data.get('contractId')
                    if contract_id is not None and contract_id != '':
                        response = self.contracts_table.get_item(Key={'contractId': contract_id})
                        if 'Item' not in response:
                            return False, f"Invalid contract: '{contract_id}' does not exist in Contracts"
                        
                        if response['Item'].get('status') != 'active':
                            return False, f"Contract '{contract_id}' is not active"
            
            # Validate employment type if provided
            if 'employment' in data:
                employment_data = data.get('employment')
                if employment_data is not None:
                    if not isinstance(employment_data, dict):
                        return False, "employment must be an object or null"
                    
                    employment_type_id = employment_data.get('typeId')
                    if employment_type_id is not None and employment_type_id != '':
                        response = self.employment_types_table.get_item(Key={'typeId': employment_type_id})
                        if 'Item' not in response:
                            return False, f"Invalid employment type: '{employment_type_id}' does not exist in EmploymentTypes"
                        
                        if not response['Item'].get('isActive', True):
                            return False, f"Employment type '{employment_type_id}' is not active"
            
        except Exception as e:
            print(f"Warning: Could not validate references: {str(e)}")
            # Uncomment to fail on reference validation errors
            # return False, f"Error validating references: {str(e)}"
        
        return True, None
    
    def _validate_business_logic_partial(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate business logic rules (only for fields present in update)"""
        
        # Check that start date is not too far in the past if provided
        if 'startDate' in data:
            try:
                start_date = datetime.fromisoformat(data['startDate'].replace('Z', '+00:00'))
                now = datetime.utcnow()
                
                days_diff = (now - start_date).days
                if days_diff > 30:
                    return False, "Start date cannot be more than 30 days in the past"
            except:
                pass  # Date format already validated
        
        # Check that end date is not too far in the future if provided
        if 'endDate' in data:
            try:
                end_date = datetime.fromisoformat(data['endDate'].replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                max_end_date = now + timedelta(days=730)  # 2 years from now
                
                if end_date > max_end_date:
                    max_date_str = max_end_date.strftime('%Y-%m-%d')
                    return False, f"La data di fine non può essere oltre 2 anni nel futuro. Data massima consentita: {max_date_str}"
            except:
                pass  # Date format already validated
        
        return True, None


# Initialize validator
validator = JobListingValidator(ENVIRONMENT)


def convert_floats_to_decimal(obj):
    """
    Recursively convert all float values to Decimal for DynamoDB compatibility
    """
    if isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: convert_floats_to_decimal(value) for key, value in obj.items()}
    elif isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, int) and not isinstance(obj, bool):
        return obj
    else:
        return obj


def convert_decimals_to_float(obj):
    """Convert Decimal objects to float for JSON serialization"""
    if isinstance(obj, list):
        return [convert_decimals_to_float(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    else:
        return obj


def get_bookings_for_listing(listing_id):
    """Get all active bookings for a job listing"""
    try:
        from boto3.dynamodb.conditions import Key, Attr
        
        response = bookings_table.query(
            IndexName='listingId-startDate-index',
            KeyConditionExpression=Key('listingId').eq(listing_id),
            FilterExpression=Attr('status').is_in(['pending', 'confirmed']) & Attr('bookingType').eq('booking')
        )
        return response.get('Items', [])
    except Exception as e:
        print(f"Error fetching bookings: {str(e)}")
        return []


def cancel_booking_with_notification(booking_id, reason, cancelled_by='system_listing_update'):
    """Cancel a booking and send notification to chat"""
    try:
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # Update booking status to cancelled
        bookings_table.update_item(
            Key={'bookingId': booking_id},
            UpdateExpression='SET #status = :cancelled, updatedAt = :now, cancelledAt = :now, cancelledBy = :by, cancelledByRole = :role, cancellationReason = :reason',
            ExpressionAttributeNames={
                '#status': 'status'
            },
            ExpressionAttributeValues={
                ':cancelled': 'cancelled',
                ':now': now,
                ':by': cancelled_by,
                ':role': 'system',
                ':reason': reason
            }
        )
        
        print(f"Cancelled booking {booking_id}: {reason}")
        
        # Try to send notification message to chat (non-blocking)
        try:
            # Get booking to find chat
            booking_response = bookings_table.get_item(Key={'bookingId': booking_id})
            if 'Item' in booking_response:
                booking = booking_response['Item']
                chat_id = booking.get('chatId')
                
                if chat_id:
                    # Send system message to chat
                    import uuid
                    message_id = str(uuid.uuid4())
                    
                    chats_table.update_item(
                        Key={'chatId': chat_id},
                        UpdateExpression='SET booking_state = :cancelled, updatedAt = :now',
                        ExpressionAttributeValues={
                            ':cancelled': 'cancelled',
                            ':now': now
                        }
                    )
                    
                    print(f"Updated chat {chat_id} booking_state to cancelled")
        except Exception as e:
            print(f"Warning: Could not send cancellation notification: {str(e)}")
        
        return True
    except Exception as e:
        print(f"Error cancelling booking {booking_id}: {str(e)}")
        return False


def check_and_cancel_out_of_range_bookings(listing_id, new_start_date, new_end_date, existing_listing):
    """
    Check if date changes would put existing bookings out of range.
    BLOCKS operation if any CONFIRMED bookings would fall outside the new date range.
    Confirmed bookings that are fully contained within the new date range are NOT affected.
    Auto-cancels only PENDING bookings that fall outside the new date range.

    Corner cases handled:
    - Booking fully within new range → not affected, update proceeds normally.
    - Booking partially outside new range (starts before new start OR ends after new end) → blocked if confirmed.
    - No active bookings → update is always allowed.

    Returns:
        tuple: (success, cancelled_count, error_message, error_code)
            error_code is 'BOOKING_CONFLICT' for business-rule blocks,
            'INTERNAL_ERROR' for unexpected exceptions, or None on success.
    """
    try:
        # Parse new dates (strip time zone suffix for consistent comparison)
        new_start = datetime.fromisoformat(new_start_date.replace('Z', '+00:00'))
        new_end = datetime.fromisoformat(new_end_date.replace('Z', '+00:00'))
        
        # Get all active bookings for this listing
        bookings = get_bookings_for_listing(listing_id)
        
        if not bookings:
            print(f"No active bookings found for listing {listing_id}")
            return True, 0, None, None
        
        print(f"Found {len(bookings)} active bookings for listing {listing_id}")
        
        # First pass: check for CONFIRMED bookings that would be out of range.
        # A booking is out of range only if it starts before the new start OR ends after the new end.
        # Bookings fully contained within [new_start, new_end] are NOT blocked.
        confirmed_out_of_range = []
        pending_out_of_range = []
        
        for booking in bookings:
            booking_start = datetime.fromisoformat(booking['startDate'].replace('Z', '+00:00'))
            booking_end = datetime.fromisoformat(booking['endDate'].replace('Z', '+00:00'))
            
            # Check if booking falls outside the new listing date range
            if booking_start < new_start or booking_end > new_end:
                booking_id = booking['bookingId']
                booking_status = booking['status']
                
                # workerName is stored inside metadata, not at top level
                worker_display = (
                    booking.get('metadata', {}).get('workerName')
                    or booking.get('workerId', 'Unknown')
                )
                
                if booking_status == 'confirmed':
                    confirmed_out_of_range.append({
                        'bookingId': booking_id,
                        'startDate': booking['startDate'],
                        'endDate': booking['endDate'],
                        'workerDisplay': worker_display
                    })
                elif booking_status == 'pending':
                    pending_out_of_range.append(booking)
        
        # BLOCK operation if there are confirmed bookings that fall outside the new range
        if confirmed_out_of_range:
            print(f"BLOCKING: {len(confirmed_out_of_range)} confirmed bookings would be out of range")
            
            # Build detailed error message (show up to 3 examples)
            booking_details = []
            for b in confirmed_out_of_range[:3]:
                booking_details.append(
                    f"- Worker: {b['workerDisplay']}, Dates: {b['startDate']} to {b['endDate']}"
                )
            
            error_msg = (
                f"Cannot modify dates: {len(confirmed_out_of_range)} confirmed booking(s) would fall "
                f"outside the new date range ({new_start_date} – {new_end_date}). "
                f"Please coordinate with the worker(s) or cancel their bookings first.\n"
            )
            error_msg += "\n".join(booking_details)
            if len(confirmed_out_of_range) > 3:
                error_msg += f"\n... and {len(confirmed_out_of_range) - 3} more"
            
            return False, 0, error_msg, 'BOOKING_CONFLICT'
        
        # No confirmed bookings affected – proceed to auto-cancel pending bookings outside the range
        cancelled_count = 0
        if pending_out_of_range:
            print(f"Auto-cancelling {len(pending_out_of_range)} pending bookings out of range")
            
            for booking in pending_out_of_range:
                booking_id = booking['bookingId']
                reason = (
                    f"Job listing dates changed from {existing_listing.get('startDate')} – "
                    f"{existing_listing.get('endDate')} to {new_start_date} – {new_end_date}. "
                    f"Your booking ({booking['startDate']} to {booking['endDate']}) is no longer "
                    f"within the job period."
                )
                print(f"Cancelling pending booking {booking_id}")
                cancel_booking_with_notification(booking_id, reason)
                cancelled_count += 1
            
            print(f"Cancelled {cancelled_count} pending bookings due to date range change")
        
        return True, cancelled_count, None, None
        
    except Exception as e:
        print(f"Error checking bookings: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, 0, f"Error checking existing bookings: {str(e)}", 'INTERNAL_ERROR'


def lambda_handler(event, context):
    """
    Update an existing job listing with new CCNL contract structure
    
    PUT /listings/{listingId}
    
    Authorization: Cognito JWT (company owner only)
    
    Updates all fields provided in the request body.
    Cannot change companyId or listingId.
    
    **Updated Structure:**
    - contract now includes calculation, paragraph, coefficient, superminimo
    - jobRole simplified (removed ATECO fields)
    - salary field removed (use contract.calculation + contract.superminimo)
    - schedule includes workTimeSlots with detailed time definitions
    
    **Partial Updates:**
    Only the fields provided in the request body will be updated.
    All validations apply only to the fields being updated.
    """
    
    try:
        print(f"[UPDATE-LISTING] START - Event received")
        print(f"[UPDATE-LISTING] Path: {event.get('pathParameters', {})}")
        
        # Get user info from Cognito authorizer
        user_id = event['requestContext']['authorizer']['claims']['sub']
        user_groups = event['requestContext']['authorizer']['claims'].get('cognito:groups', '')
        
        print(f"[UPDATE-LISTING] User: {user_id}, Groups: {user_groups}")
        
        # Check if user is in 'companies' group
        if 'companies' not in user_groups:
            print(f"[UPDATE-LISTING] ERROR: User not in companies group")
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Forbidden',
                    'message': 'Only company users can update job listings'
                })
            }
        
        # Get listingId from path parameters
        listing_id = event['pathParameters']['listingId']
        print(f"[UPDATE-LISTING] Listing ID: {listing_id}")
        
        # Parse request body
        body = json.loads(event['body'])
        print(f"[UPDATE-LISTING] Body parsed, {len(body)} fields")
        
        # Get company info to verify ownership
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
            print(f"[UPDATE-LISTING] ERROR fetching company: {str(e)}")
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
                    'message': 'Error fetching company information'
                })
            }
        
        # Get the existing listing to verify ownership
        try:
            listing_response = job_listings_table.get_item(Key={'listingId': listing_id})
            
            if 'Item' not in listing_response:
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
            
            existing_listing = listing_response['Item']
            
            # Check if listing belongs to this company
            if existing_listing.get('companyId') != company_id:
                return {
                    'statusCode': 403,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Forbidden',
                        'message': 'You can only update your own job listings'
                    })
                }
            
            # Cannot update deleted listings
            if existing_listing.get('status') == 'deleted':
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'Cannot update a deleted job listing'
                    })
                }
            
        except Exception as e:
            print(f"[UPDATE-LISTING] ERROR fetching listing: {str(e)}")
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
                    'message': 'Error fetching job listing'
                })
            }
        
        # Check if dates are being changed and handle affected bookings
        cancelled_bookings_count = 0
        if ('startDate' in body or 'endDate' in body):
            print(f"[UPDATE-LISTING] Date change detected - checking existing bookings...")
            
            # Use new dates if provided, otherwise use existing
            new_start = body.get('startDate', existing_listing.get('startDate'))
            new_end = body.get('endDate', existing_listing.get('endDate'))
            
            success, cancelled_count, error_msg, error_code = check_and_cancel_out_of_range_bookings(
                listing_id, new_start, new_end, existing_listing
            )
            
            if not success:
                print(f"[UPDATE-LISTING] Booking check failed [{error_code}]: {error_msg}")
                if error_code == 'BOOKING_CONFLICT':
                    # Business-rule violation: confirmed bookings fall outside the new dates
                    return {
                        'statusCode': 409,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'error': 'Conflict',
                            'code': 4066,
                            'message': error_msg
                        })
                    }
                else:
                    # Unexpected server-side error
                    return {
                        'statusCode': 500,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'error': 'Internal Server Error',
                            'code': error_code or 5021,
                            'message': error_msg
                        })
                    }
            
            cancelled_bookings_count = cancelled_count
            if cancelled_count > 0:
                print(f"[UPDATE-LISTING] Cancelled {cancelled_count} bookings due to date change")
        
        # Validate update data against schema
        print(f"[UPDATE-LISTING] Starting validation...")
        is_valid, error_message = validator.validate_listing_update(body)
        print(f"[UPDATE-LISTING] Validation result: {is_valid}")
        if not is_valid:
            print(f"[UPDATE-LISTING] Validation failed: {error_message}")
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': error_message
                })
            }
        
        # Build update expression
        update_parts = []
        remove_parts = []
        expression_values = {}
        expression_names = {}
        
        # Fields that can be updated
        updatable_fields = {
            'title': 'title',
            'description': 'description',
            'startDate': 'startDate',
            'endDate': 'endDate',
            'positions': 'positions',
            'category': 'category',
            'jobRole': 'jobRole',
            'contract': 'contract',
            'location': 'location',
            'schedule': 'schedule',
            'employment': 'employment',
            'responsibilities': 'responsibilities',
            'benefits': 'benefits',
            'requirements': 'requirements',
            'isHousingIncluded': 'isHousingIncluded',  # Housing benefit flag
            'vitto': 'vitto',  # NEW: Meals provided
            'alloggio': 'alloggio',  # NEW: Accommodation provided
            'alloggioPricePerDay': 'alloggioPricePerDay',  # NEW: Optional accommodation price per day
            'alloggioDescription': 'alloggioDescription',  # NEW: Optional accommodation description
            'minConsecutiveDays': 'minConsecutiveDays',  # NEW: Min consecutive booking days
            'minNoticeDays': 'minNoticeDays',  # NEW: Min advance notice days
            'salary': 'salary',  # Manual salary entry (non-CCNL listings)
            'status': 'status',
            'expiresAt': 'expiresAt'
        }
        
        for field, attr_name in updatable_fields.items():
            if field in body:
                value = body[field]
                
                # Handle None/null values - DynamoDB requires REMOVE instead of SET
                if value is None:
                    remove_parts.append(f'#{attr_name}')
                    expression_names[f'#{attr_name}'] = attr_name
                    continue
                
                # Convert to appropriate types
                if field == 'positions':
                    value = int(value)
                
                if field == 'schedule' and isinstance(value, dict):
                    if 'hoursPerWeek' in value:
                        value['hoursPerWeek'] = int(value['hoursPerWeek'])
                
                # Convert floats to Decimal for DynamoDB
                value = convert_floats_to_decimal(value)
                
                update_parts.append(f'#{attr_name} = :{attr_name}')
                expression_names[f'#{attr_name}'] = attr_name
                expression_values[f':{attr_name}'] = value
        
        # Always update updatedAt
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        update_parts.append('#updatedAt = :updatedAt')
        expression_names['#updatedAt'] = 'updatedAt'
        expression_values[':updatedAt'] = now
        
        # If status is being changed to 'published', set publishedAt if not already set
        if 'status' in body and body['status'] == 'published':
            if 'publishedAt' not in existing_listing or not existing_listing.get('publishedAt'):
                update_parts.append('#publishedAt = :publishedAt')
                expression_names['#publishedAt'] = 'publishedAt'
                expression_values[':publishedAt'] = now
        
        if len(update_parts) == 1 and len(remove_parts) == 0:  # Only updatedAt and nothing to remove
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'No valid fields to update'
                })
            }
        
        # Build UpdateExpression with both SET and REMOVE parts
        update_expression_parts = []
        if update_parts:
            update_expression_parts.append('SET ' + ', '.join(update_parts))
        if remove_parts:
            update_expression_parts.append('REMOVE ' + ', '.join(remove_parts))
        
        update_expression = ' '.join(update_expression_parts)
        
        # Perform update
        try:
            update_params = {
                'Key': {'listingId': listing_id},
                'UpdateExpression': update_expression,
                'ExpressionAttributeNames': expression_names,
                'ReturnValues': 'ALL_NEW'
            }
            
            # Only add ExpressionAttributeValues if there are any (REMOVE operations don't need values)
            if expression_values:
                update_params['ExpressionAttributeValues'] = expression_values
            
            response = job_listings_table.update_item(**update_params)
            
            updated_listing = response['Attributes']
            
            print(f"Updated listing: {listing_id}")
            print(f"  - Fields updated: {list(body.keys())}")
            if 'contract' in body and body['contract'] is not None:
                print(f"  - Contract level: {body['contract'].get('level', 'N/A')}")
                print(f"  - Contract paragraph: {body['contract'].get('paragraph', 'N/A')}")
            elif 'contract' in body and body['contract'] is None:
                print(f"  - Contract removed (set to null)")
            
        except Exception as e:
            print(f"[UPDATE-LISTING] ERROR updating listing in DynamoDB: {str(e)}")
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
                    'message': 'Error updating job listing'
                })
            }
        
        # Convert Decimal to float for JSON response
        updated_listing_json = convert_decimals_to_float(updated_listing)
        
        print(f"[UPDATE-LISTING] SUCCESS - Returning 200")
        print(f"[UPDATE-LISTING] Updated fields: {len(body.keys())} fields")
        
        response_body = {
            'message': 'Job listing updated successfully',
            'listing': updated_listing_json,
            'updatedFields': list(body.keys())
        }
        
        # Add info about cancelled bookings if any
        if cancelled_bookings_count > 0:
            response_body['cancelledBookingsCount'] = cancelled_bookings_count
            response_body['cancelledBookingsReason'] = 'Bookings were outside the new date range'
        
        # Log response structure (without full listing to avoid huge logs)
        print(f"[UPDATE-LISTING] Response structure: message={response_body['message']}, listing_fields={len(updated_listing_json)}, updatedFields={len(response_body['updatedFields'])}, cancelledBookings={cancelled_bookings_count}")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_body, default=decimal_default)
        }
        
    except json.JSONDecodeError as e:
        print(f"[UPDATE-LISTING] JSON decode error: {str(e)}")
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
        print(f"[UPDATE-LISTING] KeyError: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'message': f'Missing required parameter: {str(e)}'
            })
        }
    
    except Exception as e:
        print(f"[UPDATE-LISTING] UNEXPECTED ERROR: {str(e)}")
        print(f"[UPDATE-LISTING] Error type: {type(e).__name__}")
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
                'message': 'An error occurred while updating the job listing'
            })
        }