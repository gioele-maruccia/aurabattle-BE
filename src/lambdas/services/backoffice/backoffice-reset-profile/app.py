"""
Backoffice Lambda: Reset User Profile to Basic

This Lambda handles profile reset requests from backoffice.
It resets a user's profile to "basic" and removes all associated data.

Version: 2.2.1

Actions performed:
1. Check for active bookings/job listings (if worker/company)
2. Delete all INACTIVE bookings/job listings
3. Delete company record (if company/company_representative)
4. Delete all user documents
5. Reset Cognito attributes to basic profile
6. Remove user from groups and add to basic_users

State Validation (based on delete-user pattern):
- Worker: Cannot reset if has bookings with status = "pending" or "accepted" (ACTIVE)
          Can delete: rejected, cancelled, completed, blocked
- Company: Cannot reset if has:
           - Job listings with status = "published" or "paused" (ACTIVE)
           - OR bookings with status = "pending" or "accepted" (ACTIVE) - includes:
             * Bookings in company's job listings (via listingId)
             * All bookings where companyId matches (direct bookings)
           Can delete: draft, deleted, closed, cancelled job listings
                      and their associated bookings

This approach mirrors the delete-user logic in user-api/delete-user
where active entities (published job listings, accepted bookings) block
deletion to prevent data inconsistencies.
"""

import json
import os
import boto3
import logging
from typing import Dict, List, Any, Optional
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
REGION = os.environ["REGION"]
COGNITO_USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]
BOOKINGS_TABLE = os.environ.get("BOOKINGS_TABLE", f"{os.environ.get('ENVIRONMENT', 'dev')}-Bookings")
JOB_LISTINGS_TABLE = os.environ.get("JOB_LISTINGS_TABLE", f"{os.environ.get('ENVIRONMENT', 'dev')}-JobListings")
COMPANIES_TABLE = os.environ.get("COMPANIES_TABLE", f"{os.environ.get('ENVIRONMENT', 'dev')}-Companies")
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", f"{os.environ.get('ENVIRONMENT', 'dev')}-UserDocuments")
USER_PROFILES_TABLE = os.environ.get("USER_PROFILES_TABLE", f"{os.environ.get('ENVIRONMENT', 'dev')}-UserProfiles")

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name=REGION)
cognito = boto3.client('cognito-idp', region_name=REGION)

# DynamoDB tables
bookings_table = dynamodb.Table(BOOKINGS_TABLE)
job_listings_table = dynamodb.Table(JOB_LISTINGS_TABLE)
companies_table = dynamodb.Table(COMPANIES_TABLE)
documents_table = dynamodb.Table(DOCUMENTS_TABLE)
user_profiles_table = dynamodb.Table(USER_PROFILES_TABLE)


def _cors_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Standardized CORS response format"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
        },
        "body": json.dumps(body, default=str)
    }


def get_user_cognito_attributes(user_sub: str) -> Dict[str, str]:
    """Get user attributes from Cognito"""
    try:
        response = cognito.admin_get_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=user_sub
        )
        
        attributes = {}
        for attr in response.get('UserAttributes', []):
            attr_name = attr['Name']
            # Remove 'custom:' prefix for custom attributes
            if attr_name.startswith('custom:'):
                attr_name = attr_name.replace('custom:', '')
            attributes[attr_name] = attr['Value']
        
        # Get user groups
        groups_response = cognito.admin_list_groups_for_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=user_sub
        )
        attributes['groups'] = [g['GroupName'] for g in groups_response.get('Groups', [])]
        
        return attributes
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'UserNotFoundException':
            logger.error(f"User not found: {user_sub}")
            raise ValueError(f"User not found: {user_sub}")
        logger.error(f"Error getting user Cognito attributes: {str(e)}")
        raise


def check_worker_active_bookings(user_sub: str) -> tuple[bool, List[Dict]]:
    """
    Check if worker has any active bookings (status = 'pending' or 'accepted')
    Inactive bookings: rejected, cancelled, completed, blocked
    
    Returns: (has_active, list_of_active_bookings)
    """
    try:
        response = bookings_table.query(
            IndexName='workerId-startDate-index',
            KeyConditionExpression=Key('workerId').eq(user_sub)
        )
        
        # Active statuses: pending, accepted
        # Inactive statuses: rejected, cancelled, completed, blocked, cancelled
        active_statuses = ['pending', 'accepted']
        active_bookings = []
        
        for booking in response.get('Items', []):
            if booking.get('status') in active_statuses:
                active_bookings.append({
                    'bookingId': booking.get('bookingId'),
                    'listingId': booking.get('listingId'),
                    'jobTitle': booking.get('jobTitle'),
                    'startDate': booking.get('startDate'),
                    'endDate': booking.get('endDate'),
                    'companyName': booking.get('companyName'),
                    'status': booking.get('status')
                })
        
        return len(active_bookings) > 0, active_bookings
        
    except Exception as e:
        logger.error(f"Error checking worker bookings: {str(e)}")
        raise


def check_company_active_job_listings_and_bookings(user_sub: str) -> tuple[bool, List[Dict], List[Dict]]:
    """
    Check if company has any active job listings or active bookings.
    Active job listing statuses: 'published', 'paused' (drafts and deleted are inactive)
    Active booking statuses: 'pending', 'accepted'
    
    Checks:
    1. Active job listings
    2. Active bookings in those listings
    3. Active bookings where company is employer (using companyId field)
    
    Returns: (has_active, active_listings, active_bookings)
    """
    try:
        # Get companyId from UserProfiles
        profile_response = user_profiles_table.get_item(
            Key={'user_id': user_sub}
        )
        company_id = profile_response.get('Item', {}).get('companyId')
        
        if not company_id:
            logger.warning(f"No companyId found for user: {user_sub}")
            return False, [], []
        
        # Get all job listings for this company
        response = job_listings_table.query(
            IndexName='companyId-createdAt-index',
            KeyConditionExpression=Key('companyId').eq(company_id)
        )
        
        job_listings = response.get('Items', [])
        active_statuses_listings = ['published', 'paused']
        active_statuses_bookings = ['pending', 'accepted']
        
        active_listings = []
        active_bookings = []
        
        for listing in job_listings:
            listing_status = listing.get('status')
            listing_id = listing.get('listingId')
            
            # Skip inactive job listings (draft, deleted, closed, cancelled)
            if listing_status not in active_statuses_listings:
                continue
            
            active_listings.append({
                'listingId': listing_id,
                'jobTitle': listing.get('jobTitle'),
                'status': listing_status
            })
            
            # Check for active bookings in this listing
            bookings_response = bookings_table.query(
                IndexName='listingId-startDate-index',
                KeyConditionExpression=Key('listingId').eq(listing_id)
            )
            
            for booking in bookings_response.get('Items', []):
                if booking.get('status') in active_statuses_bookings:
                    active_bookings.append({
                        'bookingId': booking.get('bookingId'),
                        'listingId': listing_id,
                        'jobTitle': listing.get('jobTitle'),
                        'workerName': booking.get('workerName'),
                        'status': booking.get('status'),
                        'startDate': booking.get('startDate'),
                        'endDate': booking.get('endDate')
                    })
        
        # ALSO check for active bookings where company is employer (using companyId)
        # Query for each active status since status is the sort key
        for status in active_statuses_bookings:
            company_bookings_response = bookings_table.query(
                IndexName='companyId-status-index',
                KeyConditionExpression=Key('companyId').eq(company_id) & Key('status').eq(status)
            )
            
            for booking in company_bookings_response.get('Items', []):
                # Avoid duplicates (bookings already found via listings)
                booking_id = booking.get('bookingId')
                if not any(b['bookingId'] == booking_id for b in active_bookings):
                    active_bookings.append({
                        'bookingId': booking_id,
                        'listingId': booking.get('listingId', 'N/A'),
                        'jobTitle': booking.get('jobTitle'),
                        'workerName': booking.get('workerName'),
                        'status': booking.get('status'),
                        'startDate': booking.get('startDate'),
                        'endDate': booking.get('endDate')
                    })
        
        # Cannot reset if there are active listings or active bookings
        has_active = len(active_listings) > 0 or len(active_bookings) > 0
        
        return has_active, active_listings, active_bookings
        
    except Exception as e:
        logger.error(f"Error checking company job listings and bookings: {str(e)}")
        raise


def delete_worker_inactive_bookings(user_sub: str) -> int:
    """Delete all INACTIVE bookings for a worker. Returns count of deleted items.
    
    Inactive: rejected, cancelled, completed, blocked
    Active: pending, accepted (will not delete these)
    """
    try:
        response = bookings_table.query(
            IndexName='workerId-startDate-index',
            KeyConditionExpression=Key('workerId').eq(user_sub)
        )
        
        bookings = response.get('Items', [])
        deleted_count = 0
        inactive_statuses = ['rejected', 'cancelled', 'completed', 'blocked']
        
        for booking in bookings:
            # Only delete inactive bookings (active ones were already checked and should have blocked the reset)
            if booking.get('status') in inactive_statuses:
                bookings_table.delete_item(
                    Key={'bookingId': booking['bookingId']}
                )
                deleted_count += 1
                logger.info(f"Deleted inactive booking: {booking['bookingId']} (status: {booking.get('status')})")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error deleting worker bookings: {str(e)}")
        raise


def delete_company_inactive_job_listings_and_bookings(user_sub: str) -> Dict[str, int]:
    """Delete all INACTIVE job listings and associated bookings for a company.
    
    Inactive job listing statuses: draft, deleted, closed, cancelled
    Active job listing statuses: published, paused (will not delete these)
    
    Returns dict with counts of deleted items.
    """
    try:
        # Get companyId from UserProfiles
        profile_response = user_profiles_table.get_item(
            Key={'user_id': user_sub}
        )
        company_id = profile_response.get('Item', {}).get('companyId')
        
        if not company_id:
            logger.warning(f"No companyId found for user: {user_sub}")
            return {'listings': 0, 'bookings': 0}
        
        # Get all job listings
        response = job_listings_table.query(
            IndexName='companyId-createdAt-index',
            KeyConditionExpression=Key('companyId').eq(company_id)
        )
        
        job_listings = response.get('Items', [])
        deleted_listings = 0
        deleted_bookings = 0
        inactive_statuses = ['draft', 'deleted', 'closed', 'cancelled']
        
        for listing in job_listings:
            listing_id = listing.get('listingId')
            listing_status = listing.get('status')
            
            # Skip active listings - they should have blocked the reset
            if listing_status not in inactive_statuses:
                logger.warning(f"Skipping active listing {listing_id} with status {listing_status}")
                continue
            
            # Delete all bookings for this inactive listing
            bookings_response = bookings_table.query(
                IndexName='listingId-startDate-index',
                KeyConditionExpression=Key('listingId').eq(listing_id)
            )
            
            for booking in bookings_response.get('Items', []):
                bookings_table.delete_item(
                    Key={'bookingId': booking['bookingId']}
                )
                deleted_bookings += 1
                logger.info(f"Deleted booking: {booking['bookingId']} from inactive listing")
            
            # Delete the inactive job listing
            job_listings_table.delete_item(
                Key={'listingId': listing_id}
            )
            deleted_listings += 1
            logger.info(f"Deleted inactive job listing: {listing_id} (status: {listing_status})")
        
        return {
            'listings': deleted_listings,
            'bookings': deleted_bookings
        }
        
    except Exception as e:
        logger.error(f"Error deleting company job listings: {str(e)}")
        raise


def delete_company_record(user_sub: str) -> bool:
    """Delete company record from Companies table"""
    try:
        companies_table.delete_item(
            Key={'userId': user_sub}
        )
        logger.info(f"Deleted company record for user: {user_sub}")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            logger.warning(f"Company record not found for user: {user_sub}")
            return False
        logger.error(f"Error deleting company record: {str(e)}")
        raise


def delete_user_documents(user_sub: str) -> int:
    """Delete all documents for a user. Returns count of deleted items."""
    try:
        pk = f"USER#{user_sub}"
        response = documents_table.query(
            KeyConditionExpression=Key('pk').eq(pk)
        )
        
        documents = response.get('Items', [])
        deleted_count = 0
        
        for doc in documents:
            documents_table.delete_item(
                Key={
                    'pk': doc['pk'],
                    'sk': doc['sk']
                }
            )
            deleted_count += 1
            # Legacy items might miss documentId; fall back to sk to avoid KeyError
            logger.info(f"Deleted document: {doc.get('documentId', doc.get('sk', 'unknown'))}")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error deleting user documents: {str(e)}")
        raise


def reset_cognito_to_basic(user_sub: str) -> None:
    """Reset user's Cognito attributes to basic profile"""
    try:
        # Update custom attributes
        attributes = [
            {'Name': 'custom:profile_type', 'Value': 'basic'},
            {'Name': 'custom:verification_status', 'Value': 'none'}
        ]
        
        cognito.admin_update_user_attributes(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=user_sub,
            UserAttributes=attributes
        )
        logger.info(f"Updated Cognito attributes for user {user_sub} to basic")
        
        # Remove from all groups
        groups_response = cognito.admin_list_groups_for_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=user_sub
        )
        
        for group in groups_response.get('Groups', []):
            group_name = group['GroupName']
            cognito.admin_remove_user_from_group(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=user_sub,
                GroupName=group_name
            )
            logger.info(f"Removed user {user_sub} from group: {group_name}")
        
        # Add to basic_users group
        try:
            cognito.admin_add_user_to_group(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=user_sub,
                GroupName='basic_users'
            )
            logger.info(f"Added user {user_sub} to basic_users group")
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceNotFoundException':
                raise
            logger.warning(f"basic_users group not found, skipping group assignment")
        
    except Exception as e:
        logger.error(f"Error resetting Cognito profile: {str(e)}")
        raise


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for profile reset
    
    Expected input (POST /backoffice/reset-profile):
    {
        "userSub": "cognito-user-sub-uuid"
    }
    """
    try:
        logger.info(f"Event: {json.dumps(event)}")
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        user_sub = body.get('userSub')
        
        if not user_sub:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': 'Missing required parameter: userSub',
                'code': 4348
            })
        
        logger.info(f"Processing profile reset for user: {user_sub}")
        
        # Step 1: Get user's current profile type
        try:
            user_attrs = get_user_cognito_attributes(user_sub)
        except ValueError as e:
            return _cors_response(404, {
                'error': str(e),
                'code': 4221
            })
        
        profile_type = user_attrs.get('profile_type', 'basic')
        logger.info(f"User profile type: {profile_type}")
        
        # If already basic, nothing to do
        if profile_type == 'basic':
            return _cors_response(200, {
                'message': 'User is already on basic profile',
                'userSub': user_sub,
                'profileType': 'basic',
                'code': 3093
            })
        
        # Step 2: Check for confirmed bookings based on profile type
        reset_summary = {
            'userSub': user_sub,
            'previousProfileType': profile_type,
            'resetTimestamp': datetime.utcnow().isoformat(),
            'deletedItems': {}
        }
        
        if profile_type == 'worker':
            # Check for active bookings (pending or accepted)
            has_active, active_bookings = check_worker_active_bookings(user_sub)
            
            if has_active:
                return _cors_response(409, {
                    'error': 'Conflict',
                    'activeBookings': active_bookings,
                    'message': 'Please cancel or complete all active bookings before resetting the profile. Active bookings: pending and accepted.',
                    'code': 4217
                })
            
            # Delete all inactive worker bookings
            deleted_bookings = delete_worker_inactive_bookings(user_sub)
            reset_summary['deletedItems']['bookings'] = deleted_bookings
            logger.info(f"Deleted {deleted_bookings} inactive bookings for worker")
            
            # Delete worker documents
            deleted_docs = delete_user_documents(user_sub)
            reset_summary['deletedItems']['documents'] = deleted_docs
            logger.info(f"Deleted {deleted_docs} documents for worker")
        
        elif profile_type in ['company', 'company_representative']:
            # Check for active job listings or active bookings in those listings
            has_active, active_listings, active_bookings = check_company_active_job_listings_and_bookings(user_sub)
            
            if has_active:
                error_detail = {
                    'error': 'Cannot reset profile: company has active job listings or active bookings',
                    'message': 'Please close or delete all active job listings (published/paused) and cancel all active bookings (pending/accepted) before resetting the profile.',
                    'code': 4218
                }
                
                if active_listings:
                    error_detail['activeListings'] = active_listings
                if active_bookings:
                    error_detail['activeBookings'] = active_bookings
                
                return _cors_response(409, error_detail)
            
            # Delete all inactive job listings and their bookings
            deleted_counts = delete_company_inactive_job_listings_and_bookings(user_sub)
            reset_summary['deletedItems']['jobListings'] = deleted_counts['listings']
            reset_summary['deletedItems']['bookings'] = deleted_counts['bookings']
            logger.info(f"Deleted {deleted_counts['listings']} inactive job listings and {deleted_counts['bookings']} bookings")
            
            # Delete company record
            company_deleted = delete_company_record(user_sub)
            reset_summary['deletedItems']['companyRecord'] = company_deleted
            
            # Delete company documents
            deleted_docs = delete_user_documents(user_sub)
            reset_summary['deletedItems']['documents'] = deleted_docs
            logger.info(f"Deleted {deleted_docs} documents for company")
        
        # Step 3: Reset Cognito profile to basic
        reset_cognito_to_basic(user_sub)

        # Step 4: Update profile_type in UserProfiles DynamoDB table
        try:
            user_profiles_table.update_item(
                Key={'user_id': user_sub},
                UpdateExpression='SET profile_type = :pt, verification_status = :vs, updatedAt = :now',
                ExpressionAttributeValues={
                    ':pt': 'basic',
                    ':vs': 'none',
                    ':now': datetime.utcnow().isoformat()
                }
            )
            logger.info(f"Updated UserProfiles profile_type to basic for user {user_sub}")
        except Exception as e:
            logger.warning(f"Could not update UserProfiles for user {user_sub}: {str(e)}")

        logger.info(f"Profile reset completed successfully for user: {user_sub}")
        
        return _cors_response(200, {
            'message': 'Profile reset to basic successfully',
            'summary': reset_summary,
            'code': 3070
        })
        
    except Exception as e:
        logger.error(f"Error in profile reset: {str(e)}", exc_info=True)
        return _cors_response(500, {
            'error': 'Internal Server Error',
            'message': 'Internal server error',
            'details': str(e),
            'code': 5064
        })
