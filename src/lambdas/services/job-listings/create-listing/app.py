"""
Updated Create Job Listing Lambda
Aligned with calculate_base_pay structure and CCNL Turismo contract schema
"""

import json
import os
import boto3
from decimal import Decimal
from datetime import datetime
import uuid
from typing import Dict, Any, Tuple

dynamodb = boto3.resource('dynamodb')
cognito = boto3.client('cognito-idp')

ENVIRONMENT = os.environ['ENVIRONMENT']
JOB_LISTINGS_TABLE = os.environ['JOB_LISTINGS_TABLE_NAME']
COMPANIES_TABLE = os.environ['COMPANIES_TABLE_NAME']

job_listings_table = dynamodb.Table(JOB_LISTINGS_TABLE)
companies_table = dynamodb.Table(COMPANIES_TABLE)

# Valid CCNL Turismo levels
VALID_LEVELS = ['Qa', 'Qb', '1', '2', '3', '4', '5', '6S', '6', '7']

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
        
        # Reference table names based on actual DynamoDB tables
        self.job_categories_table = self.dynamodb.Table(f'{environment}-JobCategories')
        self.job_roles_table = self.dynamodb.Table(f'{environment}-JobRoles')
        self.contracts_table = self.dynamodb.Table(f'{environment}-Contracts')
        self.employment_types_table = self.dynamodb.Table(f'{environment}-EmploymentTypes')
        
    def validate_listing(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate job listing data
        
        Args:
            data: Job listing data to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Auto-detect mode based on jobRole and contract fields
        # If jobRole or contract are null/missing, use simplified validation (non-FIPE companies)
        job_role = data.get('jobRole')
        contract = data.get('contract')
        
        if job_role is None or contract is None:
            # Simplified validation for non-FIPE companies (ATECO != 55.xx or 56.xx)
            print("[AUTO-DETECT] Using simplified validation: jobRole or contract is null")
            return self._validate_simplified_listing(data)
        
        # Full CCNL Turismo validation for FIPE companies
        print("[AUTO-DETECT] Using full CCNL validation: jobRole and contract are present")
        
        # Validate required fields
        validation_result = self._validate_required_fields(data)
        if not validation_result[0]:
            return validation_result
        
        # Validate field formats
        validation_result = self._validate_field_formats(data)
        if not validation_result[0]:
            return validation_result
        
        # Validate reference data (category, jobRole, contract, employment)
        validation_result = self._validate_references(data)
        if not validation_result[0]:
            return validation_result
        
        # Validate business logic
        validation_result = self._validate_business_logic(data)
        if not validation_result[0]:
            return validation_result
        
        return True, None
    
    def _validate_simplified_listing(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Simplified validation for non-FIPE companies (ATECO != 55.xx or 56.xx)
        When jobRole or contract are null
        
        Required fields:
        - title, description
        - startDate, endDate
        - positions
        - location (with city and country)
        
        Optional fields:
        - jobRole, contract, employment, schedule (can be null or present)
        - category, requirements, responsibilities, benefits
        - vitto, alloggio, etc.
        """
        print(f"[DEBUG] Validating simplified listing (non-FIPE company)")
        
        # Required basic fields
        required_fields = {
            'title': 'Job title',
            'description': 'Job description',
            'startDate': 'Start date',
            'endDate': 'End date',
            'positions': 'Number of positions',
            'location': 'Location'
        }
        
        for field, label in required_fields.items():
            if field not in data or data[field] is None:
                error_msg = f"Missing required field: {label} ({field})"
                print(f"[ERROR] {error_msg}")
                return False, error_msg
        
        # Validate title length
        title = data.get('title', '')
        if not isinstance(title, str) or len(title.strip()) < 3:
            return False, "Title must be at least 3 characters long"
        if len(title) > 200:
            return False, "Title must be at most 200 characters long"
        
        # Validate description length
        description = data.get('description', '')
        if not isinstance(description, str) or len(description.strip()) < 10:
            return False, "Description must be at least 10 characters long"
        if len(description) > 5000:
            return False, "Description must be at most 5000 characters long"
        
        # Validate dates
        try:
            start_date = datetime.fromisoformat(data['startDate'].replace('Z', '+00:00'))
            end_date = datetime.fromisoformat(data['endDate'].replace('Z', '+00:00'))
            
            if end_date <= start_date:
                return False, "End date must be after start date"
        except (ValueError, AttributeError) as e:
            return False, f"Invalid date format: {str(e)}. Use ISO 8601 format (YYYY-MM-DD)"
        
        # Validate positions
        try:
            positions = int(data['positions'])
            if positions < 1:
                return False, "Positions must be at least 1"
            if positions > 1000:
                return False, "Positions must be at most 1000"
        except (ValueError, TypeError):
            return False, "Invalid positions value. Must be an integer"
        
        # Validate location
        location = data.get('location', {})
        if not isinstance(location, dict):
            return False, "Location must be an object"
        if not location.get('city'):
            return False, "Location must include 'city'"
        if not location.get('country'):
            return False, "Location must include 'country'"
        
        # Validate salary (required for simplified mode)
        salary = data.get('salary')
        if salary is None:
            return False, "Missing required field: salary (monthly gross salary in EUR)"
        try:
            salary_val = float(salary)
            if salary_val <= 0:
                return False, "Salary must be greater than 0"
            if salary_val > 999999:
                return False, "Salary must be at most 999999"
        except (ValueError, TypeError):
            return False, "Invalid salary value. Must be a number"
        
        print("[DEBUG] Simplified listing validation passed")
        return True, None
    
    def _validate_required_fields(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate that all required fields are present"""
        
        required_fields = [
            'title',
            'description',
            'startDate',
            'endDate',
            'positions',
            'category',
            'jobRole',
            'contract',
            'location',
            'schedule',
            'employment'
        ]
        
        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"
        
        # Validate nested required fields
        
        # jobRole must have roleId
        job_role = data.get('jobRole', {})
        if 'roleId' not in job_role:
            return False, "Missing required field: jobRole.roleId"
        if 'roleName' not in job_role:
            return False, "Missing required field: jobRole.roleName"
        if 'category' not in job_role:
            return False, "Missing required field: jobRole.category"
        
        # contract must have all required fields based on new schema
        contract = data.get('contract', {})
        required_contract_fields = [
            'contractId',
            'ccnlType',
            'level',
            'levelName',
            'description',
            'paragraph'
        ]
        for field in required_contract_fields:
            if field not in contract:
                return False, f"Missing required field: contract.{field}"
        
        # contract must have calculation object with base pay details
        if 'calculation' not in contract:
            return False, "Missing required field: contract.calculation"
        
        calculation = contract.get('calculation', {})
        required_calculation_fields = [
            'basePay',
            'contingencyAllowance',
            'grossBasePay',
            'calculationDate'
        ]
        for field in required_calculation_fields:
            if field not in calculation:
                return False, f"Missing required field: contract.calculation.{field}"
        
        # location must have city and country
        location = data.get('location', {})
        if 'city' not in location:
            return False, "Missing required field: location.city"
        if 'country' not in location:
            return False, "Missing required field: location.country"
        
        # schedule must have hoursPerWeek and workTimeSlots
        schedule = data.get('schedule', {})
        if 'hoursPerWeek' not in schedule:
            return False, "Missing required field: schedule.hoursPerWeek"
        if 'workTimeSlots' not in schedule:
            return False, "Missing required field: schedule.workTimeSlots"
        
        # employment must have typeId
        if 'typeId' not in data.get('employment', {}):
            return False, "Missing required field: employment.typeId"
        
        return True, None
    
    def _validate_field_formats(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate field formats and types"""
        
        # Validate title length
        title = data.get('title', '')
        if not isinstance(title, str) or len(title.strip()) < 3:
            return False, "Title must be at least 3 characters long"
        if len(title) > 200:
            return False, "Title must be at most 200 characters long"
        
        # Validate description length
        description = data.get('description', '')
        if not isinstance(description, str) or len(description.strip()) < 10:
            return False, "Description must be at least 10 characters long"
        if len(description) > 5000:
            return False, "Description must be at most 5000 characters long"
        
        # Validate dates
        try:
            start_date = datetime.fromisoformat(data['startDate'].replace('Z', '+00:00'))
            end_date = datetime.fromisoformat(data['endDate'].replace('Z', '+00:00'))
            
            if end_date <= start_date:
                return False, "End date must be after start date"
        except (ValueError, AttributeError):
            return False, "Invalid date format. Use ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)"
        
        # Validate positions
        try:
            positions = int(data['positions'])
            if positions < 1:
                return False, "Positions must be at least 1"
            if positions > 1000:
                return False, "Positions must be at most 1000"
        except (ValueError, TypeError):
            return False, "Positions must be a valid integer"
        
        # Validate contract level - MODIFICATO: solo per ccnlType=turismo
        contract = data.get('contract', {})
        level = contract.get('level')
        ccnl_type = contract.get('ccnlType', 'turismo')
        
        # Per CCNL Turismo, il livello deve essere valido
        if ccnl_type == 'turismo' and level not in VALID_LEVELS:
            return False, f"Invalid contract level: {level}. Must be one of: {', '.join(VALID_LEVELS)}"
        
        # Validate paragraph - MODIFICATO: solo per ccnlType=turismo
        paragraph = contract.get('paragraph')
        if ccnl_type == 'turismo':
            if paragraph not in VALID_PARAGRAPHS:
                return False, f"Invalid paragraph: {paragraph}. Must be 'I' or 'II'"
        # Per ccnlType=manuale, paragraph può essere null o qualsiasi valore
        
        # Validate ccnlType - MODIFICATO: ora permette anche inserimento manuale per aziende non settore turismo
        ccnl_type = contract.get('ccnlType')
        # Se ccnlType è presente, deve essere valido
        if ccnl_type and ccnl_type not in ['turismo', 'manuale']:
            return False, f"Invalid ccnlType: {ccnl_type}. Must be 'turismo' or 'manuale' (for non-hospitality companies)"
        
        # Validate contractId format - MODIFICATO: solo per ccnlType=turismo
        contract_id = contract.get('contractId', '')
        if ccnl_type == 'turismo':
            expected_contract_id = f"CCNL#{ccnl_type}#{level}"
            if not contract_id.startswith(expected_contract_id):
                return False, f"Invalid contractId format. Expected to start with: {expected_contract_id}"
        # Per ccnlType=manuale, contractId può essere qualsiasi stringa
        
        # Validate contract calculation values
        calculation = contract.get('calculation', {})
        try:
            base_pay = float(calculation.get('basePay', 0))
            contingency = float(calculation.get('contingencyAllowance', 0))
            gross_base = float(calculation.get('grossBasePay', 0))
            
            if base_pay < 0 or contingency < 0 or gross_base < 0:
                return False, "Base pay values must be positive"
            
            # Validate calculation accuracy
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
                
                if 'currency' not in superminimo:
                    return False, "Superminimo must include currency"
                
                if superminimo.get('currency') not in ['EUR', 'USD', 'GBP']:
                    return False, "Superminimo currency must be EUR, USD, or GBP"
                    
            except (ValueError, TypeError):
                return False, "Invalid superminimo values"
        
        # Validate schedule hoursPerWeek
        schedule = data.get('schedule', {})
        try:
            hours_per_week = int(schedule.get('hoursPerWeek', 0))
            if hours_per_week < 1 or hours_per_week > 168:
                return False, "Hours per week must be between 1 and 168"
        except (ValueError, TypeError):
            return False, "Invalid hours per week"
        
        # Validate workTimeSlots structure
        work_time_slots = schedule.get('workTimeSlots', [])
        if not isinstance(work_time_slots, list):
            return False, "Work time slots must be an array"
        
        if len(work_time_slots) == 0:
            return False, "At least one work time slot is required"
        
        # Validate each workTimeSlot entry
        for slot_entry in work_time_slots:
            if not isinstance(slot_entry, dict):
                return False, "Each work time slot entry must be an object"
            
            if 'type' not in slot_entry:
                return False, "Work time slot entry must have a 'type' field"
            
            if slot_entry['type'] not in ['single', 'split', 'flexible']:
                return False, f"Work time slot type must be one of: single, split, flexible"
            
            if 'slots' in slot_entry and not isinstance(slot_entry['slots'], list):
                return False, "Work time slot 'slots' must be an array"
            
            if 'days' in slot_entry:
                if not isinstance(slot_entry['days'], list):
                    return False, "Work time slot 'days' must be an array"
                
                # Validate each day
                valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                for day in slot_entry['days']:
                    if day.lower() not in valid_days:
                        return False, f"Invalid day in workTimeSlot: {day}"
        
        # Validate workDays if present (overall working days)
        if 'workDays' in schedule:
            work_days = schedule['workDays']
            if not isinstance(work_days, list):
                return False, "Work days must be an array"
            
            valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            for day in work_days:
                if day.lower() not in valid_days:
                    return False, f"Invalid work day: {day}"
        
        # Validate location coordinates if present
        location = data.get('location', {})
        if 'coordinates' in location:
            coords = location['coordinates']
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
    
    def _validate_references(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate that referenced IDs exist in reference tables"""
        
        try:
            # Validate category exists in JobCategories
            category_id = data.get('category')
            if category_id:
                response = self.job_categories_table.get_item(Key={'categoryId': category_id})
                if 'Item' not in response:
                    return False, f"Invalid category: '{category_id}' does not exist in JobCategories"
                
                # Check if category is active
                if not response['Item'].get('isActive', True):
                    return False, f"Category '{category_id}' is not active"
            
            # Validate jobRole exists in JobRoles - MODIFICATO: opzionale per ccnlType=manuale
            role_id = data.get('jobRole', {}).get('roleId')
            ccnl_type = data.get('contract', {}).get('ccnlType', 'turismo')
            
            # Per ccnlType=turismo, validare che il ruolo esista in JobRoles (FIPE)
            # Per ccnlType=manuale, permettere qualsiasi roleId (inserimento manuale)
            if role_id and ccnl_type == 'turismo':
                response = self.job_roles_table.get_item(Key={'roleId': role_id})
                if 'Item' not in response:
                    return False, f"Invalid jobRole: '{role_id}' does not exist in JobRoles"
                
                # Check if role is active
                if not response['Item'].get('isActive', True):
                    return False, f"Job role '{role_id}' is not active"
            
            # Validate contract exists in Contracts - MODIFICATO: solo per ccnlType=turismo
            contract_id = data.get('contract', {}).get('contractId')
            if contract_id and ccnl_type == 'turismo':
                response = self.contracts_table.get_item(Key={'contractId': contract_id})
                if 'Item' not in response:
                    return False, f"Invalid contract: '{contract_id}' does not exist in Contracts"
                
                # Check if contract is active
                if response['Item'].get('status') != 'active':
                    return False, f"Contract '{contract_id}' is not active"
            
            # Validate employment type exists in EmploymentTypes
            employment_type_id = data.get('employment', {}).get('typeId')
            if employment_type_id:
                response = self.employment_types_table.get_item(Key={'typeId': employment_type_id})
                if 'Item' not in response:
                    return False, f"Invalid employment type: '{employment_type_id}' does not exist in EmploymentTypes"
                
                # Check if employment type is active
                if not response['Item'].get('isActive', True):
                    return False, f"Employment type '{employment_type_id}' is not active"
            
        except Exception as e:
            # Log the error but don't fail validation if reference tables are temporarily unavailable
            print(f"Warning: Could not validate references: {str(e)}")
            # Uncomment the next line if you want to fail on reference validation errors
            # return False, f"Error validating references: {str(e)}"
        
        return True, None
    
    def _validate_business_logic(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate business logic rules"""
        
        # Check that start date is not too far in the past
        try:
            start_date = datetime.fromisoformat(data['startDate'].replace('Z', '+00:00'))
            now = datetime.utcnow()
            
            # Allow start date up to 30 days in the past
            days_diff = (now - start_date).days
            if days_diff > 30:
                return False, "Start date cannot be more than 30 days in the past"
        except:
            pass  # Date format already validated
        
        # Check that end date is not too far in the future
        try:
            end_date = datetime.fromisoformat(data['endDate'].replace('Z', '+00:00'))
            now = datetime.utcnow()
            
            # Allow end date up to 2 years in the future
            days_diff = (end_date - now).days
            if days_diff > 730:  # ~2 years
                return False, "End date cannot be more than 2 years in the future"
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
        # Keep integers as integers (DynamoDB supports them)
        return obj
    else:
        return obj


def lambda_handler(event, context):
    """
    Create new job listing with updated schema aligned with calculate_base_pay
    
    POST /listings
    
    Required in body:
    - title, description
    - startDate, endDate, positions
    - category (must exist in JobCategories)
    - jobRole (roleId, roleName, category, optional roleDescription)
    - contract:
        - contractId (format: CCNL#turismo#level, e.g., CCNL#turismo#4)
        - ccnlType (must be 'turismo')
        - level (Qa, Qb, 1-7, 6S)
        - levelName (e.g., "Livello 4")
        - description
        - paragraph ('I' or 'II')
        - calculation:
            - basePay: Base monthly pay
            - contingencyAllowance: Contingency allowance
            - grossBasePay: Total gross base pay
            - calculationDate: Date of calculation (ISO 8601)
            - article162Reduction: (optional) Reduction for small businesses
            - formula: (optional) Formula used
            - explanation: (optional) Detailed explanation
        - coefficient: (optional) CCNL coefficient
        - superminimo: (optional)
            - amount: Additional pay above CCNL
            - currency: EUR/USD/GBP
            - description: Reason for superminimo
    - location (city, country, optional: address, province, region, postalCode, coordinates)
    - schedule:
        - hoursPerWeek (20-48 based on level)
        - workTimeSlots: Array of time slots with type, slots, days
        - workDays: (optional) Overall working days summary
        - notes: (optional) Additional schedule notes
    - employment (typeId, optional: typeName, contractDuration, benefits)
    - responsibilities, requirements, benefits: (optional) text descriptions
    - status: (optional) draft/published/closed/archived
    """
    try:
        # Get authenticated user
        claims = event['requestContext']['authorizer']['claims']
        user_id = claims['sub']
        user_groups = claims.get('cognito:groups', '')
        
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
                    'message': 'Only company users can create job listings'
                })
            }
        
        # Get company info from Companies table using userId
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
                        'message': 'Company profile not found. Please create a company profile first.'
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
        
        # Parse request body
        body = json.loads(event['body'])
        
        print(f"[DEBUG] Request body ricevuto - status: '{body.get('status', 'NOT PROVIDED')}', title: '{body.get('title', 'N/A')}'")
        
        # Validate listing data against new schema
        is_valid, error_message = validator.validate_listing(body)
        if not is_valid:
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
        
        # Generate IDs and timestamps
        listing_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + 'Z'
        
        # Determine status and publishedAt
        status = body.get('status', 'draft')
        print(f"[INFO] Status ricevuto dal frontend: '{status}' (body.get('status') = {body.get('status')})")
        published_at = None
        if status == 'published':
            published_at = now
        
        # Check if this is simplified mode (non-FIPE company)
        # Detected by jobRole or contract being null
        job_role = body.get('jobRole')
        contract = body.get('contract')
        is_simplified = (job_role is None or contract is None)
        
        if is_simplified:
            # Build simplified item for non-FIPE companies
            print(f"[SIMPLIFIED] ===== CREATING SIMPLIFIED JOB LISTING =====")
            print(f"[SIMPLIFIED] Company ID: {company_id}")
            print(f"[SIMPLIFIED] Listing ID: {listing_id}")
            print(f"[SIMPLIFIED] Status: {status}")
            print(f"[SIMPLIFIED] Title: {body['title']}")
            print(f"[SIMPLIFIED] Positions: {body['positions']}")
            print(f"[SIMPLIFIED] Location: {body['location']}")
            
            item = {
                'listingId': listing_id,
                'companyId': company_id,  # From JWT
                'status': status,
                
                # Basic info
                'title': body['title'],
                'description': body['description'],
                'startDate': body['startDate'],
                'endDate': body['endDate'],
                'positions': int(body['positions']),
                
                # Location
                'location': body['location'],
                
                # Category: MUST NOT be null (required for GSI category-publishedAt-index)
                'category': body.get('category') or 'other',  # Default to 'other' if null/empty
                
                # Salary (manual entry - required for simplified mode)
                'salary': float(body.get('salary', 0)) if body.get('salary') else None,
                
                # Optional fields (can be null or present)
                'jobRole': body.get('jobRole'),  # Can be null
                'contract': body.get('contract'),  # Can be null
                'schedule': body.get('schedule'),  # Can be null
                'employment': body.get('employment'),  # Can be null
                
                # Text fields
                'responsibilities': body.get('responsibilities', ''),
                'requirements': body.get('requirements', ''),
                'benefits': body.get('benefits', ''),
                
                # Housing/accommodation
                'vitto': body.get('vitto', False),
                'alloggio': body.get('alloggio', False),
                'alloggioPricePerDay': body.get('alloggioPricePerDay'),
                'alloggioDescription': body.get('alloggioDescription', ''),
                'minConsecutiveDays': body.get('minConsecutiveDays'),
                'minNoticeDays': body.get('minNoticeDays'),
                
                # Counters
                'viewsCount': 0,
                'applicationsCount': 0,
                
                # Timestamps
                'createdAt': now,
                'updatedAt': now
            }
            
            if published_at:
                item['publishedAt'] = published_at
                print(f"[SIMPLIFIED] Published at: {published_at}")
            
            print(f"[SIMPLIFIED] Item structure created successfully")
            print(f"[SIMPLIFIED] Item keys: {list(item.keys())}")
            
        else:
            # Build item with standard CCNL Turismo schema
            item = {
                'listingId': listing_id,
                'companyId': company_id,
                'status': status,
                
                # Basic info
                'title': body['title'],
                'description': body['description'],
                'startDate': body['startDate'],
                'endDate': body['endDate'],
                'positions': int(body['positions']),
                
                # Category (validated)
                'category': body['category'],
                
                # Job Role (simplified structure)
                'jobRole': {
                    'roleId': body['jobRole']['roleId'],
                    'roleName': body['jobRole']['roleName'],
                    'category': body['jobRole']['category'],
                    'roleDescription': body['jobRole'].get('roleDescription', '')
                },
                
                # Contract with complete calculation details aligned to CCNL schema
                'contract': {
                    'contractId': body['contract']['contractId'],
                    'ccnlType': body['contract']['ccnlType'],
                    'level': body['contract']['level'],
                    'levelName': body['contract']['levelName'],
                    'description': body['contract']['description'],
                    'paragraph': body['contract']['paragraph'],
                    
                    # Base pay calculation details
                    'calculation': {
                        'basePay': float(body['contract']['calculation']['basePay']),
                        'contingencyAllowance': float(body['contract']['calculation']['contingencyAllowance']),
                        'grossBasePay': float(body['contract']['calculation']['grossBasePay']),
                        'calculationDate': body['contract']['calculation']['calculationDate']
                    }
                },
                
                # Location
                'location': body['location'],
                
                # Schedule with workDays (summary) and workTimeSlots (detailed)
                'schedule': {
                    'hoursPerWeek': int(body['schedule']['hoursPerWeek']),
                    'workTimeSlots': body['schedule'].get('workTimeSlots', []),
                    'workDays': body['schedule'].get('workDays', []),
                    'notes': body['schedule'].get('notes', '')
                },
                
                # Employment (validated)
                'employment': body['employment'],
                
                # Job details
                'responsibilities': body.get('responsibilities', ''),
                'requirements': body.get('requirements', ''),
                'benefits': body.get('benefits', ''),
                'isHousingIncluded': body.get('isHousingIncluded', False),  # Housing benefit flag
                
                # NEW: Booking requirements
                'vitto': body.get('vitto', False),  # Meals provided
                'alloggio': body.get('alloggio', False),  # Accommodation provided
                'alloggioPricePerDay': body.get('alloggioPricePerDay'),  # Optional: price per day if alloggio=true
                'alloggioDescription': body.get('alloggioDescription', ''),  # Optional: accommodation description
                'minConsecutiveDays': body.get('minConsecutiveDays'),  # Minimum consecutive booking days
                'minNoticeDays': body.get('minNoticeDays'),  # Minimum advance notice days
                
                # Counters
                'viewsCount': 0,
                'applicationsCount': 0,
                
                # Timestamps
                'createdAt': now,
                'updatedAt': now
            }
            
            # Add publishedAt if status is published
            if published_at:
                item['publishedAt'] = published_at
        
            # Add optional coefficient if present
            if 'coefficient' in body['contract']:
                item['contract']['coefficient'] = float(body['contract']['coefficient'])
            
            # Add optional article162Reduction if present
            if 'article162Reduction' in body['contract']['calculation']:
                item['contract']['calculation']['article162Reduction'] = float(
                    body['contract']['calculation']['article162Reduction']
                )
            
            # Add optional formula if present
            if 'formula' in body['contract']['calculation']:
                item['contract']['calculation']['formula'] = body['contract']['calculation']['formula']
            
            # Add optional explanation if present
            if 'explanation' in body['contract']['calculation']:
                item['contract']['calculation']['explanation'] = body['contract']['calculation']['explanation']
            
            # Add optional superminimo if present
            if 'superminimo' in body['contract']:
                item['contract']['superminimo'] = {
                    'amount': float(body['contract']['superminimo']['amount']),
                    'currency': body['contract']['superminimo'].get('currency', 'EUR'),
                    'description': body['contract']['superminimo'].get('description', '')
                }
        
        # Convert floats to Decimal for DynamoDB
        item = convert_floats_to_decimal(item)
        
        # Create job listing in DynamoDB
        print(f"[INFO] ===== SAVING TO DYNAMODB =====")
        print(f"[INFO] Table: {JOB_LISTINGS_TABLE}")
        print(f"[INFO] Listing ID: {listing_id}")
        print(f"[INFO] Mode: {'Simplified (non-FIPE)' if is_simplified else 'Full CCNL (FIPE)'}")
        if is_simplified:
            print(f"[SIMPLIFIED] About to save simplified listing")
        
        try:
            job_listings_table.put_item(Item=item)
            print(f"[SUCCESS] ✓ Job listing {listing_id} saved to DynamoDB")
            if is_simplified:
                print(f"[SIMPLIFIED] ✓ Simplified listing saved successfully")
        except Exception as save_error:
            print(f"[ERROR] ✗ Failed to save to DynamoDB: {str(save_error)}")
            print(f"[ERROR] Error type: {type(save_error).__name__}")
            raise
        
        print(f"[INFO] Job listing {listing_id} created successfully")
        
        # Return created listing
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Job listing created successfully',
                'listingId': listing_id,
                'companyId': item['companyId'],
                'title': item['title'],
                'status': status,
                'createdAt': now
            }, default=str)
        }
        
    except json.JSONDecodeError:
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
        
    except Exception as e:
        print(f"[ERROR] Unexpected error: {str(e)}")
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
                'message': str(e)
            })
        }
        print(f"  - Role: {item['jobRole']['roleName']}")
        print(f"  - Contract: {item['contract']['level']} ({item['contract']['ccnlType']}) - Paragrafo {item['contract']['paragraph']}")
        print(f"  - Base Pay: {item['contract']['calculation']['grossBasePay']} EUR")
        
        # Return created listing
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Job listing created successfully',
                'listingId': listing_id,
                'status': status,
                'listing': convert_decimals_to_float(item),
                'summary': {
                    'title': item['title'],
                    'role': item['jobRole']['roleName'],
                    'level': item['contract']['levelName'],
                    'paragraph': item['contract']['paragraph'],
                    'grossBasePay': convert_decimals_to_float(item['contract']['calculation']['grossBasePay']),
                    'positions': item['positions'],
                    'period': f"{item['startDate']} to {item['endDate']}",
                    'hoursPerWeek': item['schedule']['hoursPerWeek']
                }
            }, default=str)
        }
        
    except json.JSONDecodeError:
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
        print(f"Missing key in request: {str(e)}")
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
                'message': f'Missing required field: {str(e)}'
            })
        }
    except Exception as e:
        print(f"Error creating job listing: {str(e)}")
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
                'message': 'Failed to create job listing'
            })
        }


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