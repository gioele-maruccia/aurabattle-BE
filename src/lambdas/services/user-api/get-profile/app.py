"""
Get User Profile Handler

Returns the authenticated user's profile.
If the profile is marked as 'to_be_deleted', it automatically restores it:
1. Removes deletion flags from profile
2. Restores job listings that were paused by deletion (company only)
3. Restores PENDING bookings that were auto-cancelled by deletion
   (confirmed/accepted bookings were blocking, so they were never cancelled)
4. Returns profile with '_restore_info' containing restore details

Version: 2.1.0
"""

import json
import os
import boto3
import logging
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
bookings_table = dynamodb.Table(os.environ.get('BOOKINGS_TABLE', f"{os.environ.get('ENVIRONMENT', 'dev')}-Bookings"))
job_listings_table = dynamodb.Table(os.environ.get('JOB_LISTINGS_TABLE', f"{os.environ.get('ENVIRONMENT', 'dev')}-JobListings"))
companies_table = dynamodb.Table(os.environ.get('COMPANIES_TABLE', f"{os.environ.get('ENVIRONMENT', 'dev')}-Companies"))
cognito = boto3.client('cognito-idp')

USER_POOL_ID = os.environ.get('USER_POOL_ID', '')


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _cors_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
        },
        "body": json.dumps(body, cls=DecimalEncoder, default=str)
    }


def restore_company_listings(company_id):
    """
    Restore job listings that were paused by the deletion process.
    Only restores listings with suspendedByDeletion=true, setting them
    back to their previousStatus (typically 'published').
    
    Returns: (restored_count, listing_details)
    """
    try:
        response = job_listings_table.query(
            IndexName='companyId-createdAt-index',
            KeyConditionExpression=Key('companyId').eq(company_id)
        )
        
        now = datetime.now(timezone.utc).isoformat()
        restored_count = 0
        details = []
        
        for listing in response.get('Items', []):
            if not listing.get('suspendedByDeletion'):
                continue
            
            listing_id = listing.get('listingId')
            previous_status = listing.get('previousStatus', 'published')
            
            try:
                job_listings_table.update_item(
                    Key={'listingId': listing_id},
                    UpdateExpression=(
                        'SET #status = :prev_status, updatedAt = :now '
                        'REMOVE suspendedByDeletion, previousStatus'
                    ),
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':prev_status': previous_status,
                        ':now': now
                    }
                )
                restored_count += 1
                details.append({
                    'listingId': listing_id,
                    'restoredTo': previous_status
                })
                logger.info(f"Restored listing {listing_id} to {previous_status}")
                
            except Exception as e:
                logger.error(f"Error restoring listing {listing_id}: {e}")
                details.append({
                    'listingId': listing_id,
                    'error': str(e)
                })
        
        return restored_count, details
        
    except Exception as e:
        logger.error(f"Error querying company listings for restore: {e}")
        return 0, []


def restore_worker_bookings(user_id):
    """
    Restore PENDING bookings that were auto-cancelled by the deletion process.
    Only restores bookings with suspendedByDeletion=true.
    
    Note: confirmed/accepted bookings were BLOCKING (never cancelled), so only
    pending bookings can appear here. Pending bookings do not affect positionsFilled.
    
    Returns: (restored_count, not_restored_count, details)
    """
    try:
        response = bookings_table.query(
            IndexName='workerId-startDate-index',
            KeyConditionExpression=Key('workerId').eq(user_id)
        )
        
        return _restore_bookings(response.get('Items', []))
        
    except Exception as e:
        logger.error(f"Error querying worker bookings for restore: {e}")
        return 0, 0, []


def restore_company_bookings(company_id):
    """
    Restore PENDING bookings that were auto-cancelled by the deletion process for a company.
    Uses companyId-status-index to find cancelled bookings filtered by suspendedByDeletion.
    
    Note: confirmed/accepted bookings were BLOCKING (never cancelled), so only
    pending bookings can appear here. Pending bookings do not affect positionsFilled.
    
    Returns: (restored_count, not_restored_count, details)
    """
    try:
        # Query cancelled bookings for this company
        response = bookings_table.query(
            IndexName='companyId-status-index',
            KeyConditionExpression=Key('companyId').eq(company_id) & Key('status').eq('cancelled')
        )
        
        return _restore_bookings(response.get('Items', []))
        
    except Exception as e:
        logger.error(f"Error querying company bookings for restore: {e}")
        return 0, 0, []


def _restore_bookings(bookings):
    """
    Core logic to restore bookings that have suspendedByDeletion=true.
    
    In practice only pending bookings are ever suspended (confirmed/accepted bookings
    are blocking and never auto-cancelled). So positionsFilled adjustments are not
    needed, but the capacity check is kept as a safety net.
    
    Returns: (restored_count, not_restored_count, details)
    """
    now = datetime.now(timezone.utc).isoformat()
    restored_count = 0
    not_restored_count = 0
    details = []
    
    # Cache for listing positions check
    listing_cache = {}
    
    for booking in bookings:
        if not booking.get('suspendedByDeletion'):
            continue
        
        booking_id = booking.get('bookingId')
        previous_status = booking.get('previousStatus', 'pending')
        listing_id = booking.get('listingId')
        
        # For accepted/confirmed bookings, check position availability.
                    # (Safety net: in practice these are never suspended since they are blocking,
                    # but guard against edge cases or manual data manipulation.)
        if previous_status in ['accepted', 'confirmed']:
            can_restore = _check_listing_capacity(listing_id, listing_cache)
            
            if not can_restore:
                # Cannot restore - position was filled by someone else
                not_restored_count += 1
                # Clean up the suspension flags but leave as cancelled
                try:
                    bookings_table.update_item(
                        Key={'bookingId': booking_id},
                        UpdateExpression=(
                            'SET updatedAt = :now, '
                            'cancellationReason = :reason '
                            'REMOVE suspendedByDeletion, previousStatus'
                        ),
                        ExpressionAttributeValues={
                            ':now': now,
                            ':reason': 'Account restored but position no longer available. The booking could not be restored because all positions are now filled.'
                        }
                    )
                except Exception as e:
                    logger.error(f"Error cleaning up booking {booking_id}: {e}")
                
                details.append({
                    'bookingId': booking_id,
                    'status': 'not_restored',
                    'reason': 'Position no longer available',
                    'previousStatus': previous_status
                })
                logger.warning(f"Cannot restore booking {booking_id} - no capacity in listing {listing_id}")
                continue
        
        # Restore the booking
        try:
            update_expr = (
                'SET #status = :prev_status, updatedAt = :now '
                'REMOVE suspendedByDeletion, previousStatus, cancelledAt, '
                'cancelledBy, cancelledByRole, cancellationReason, cancellationMetadata'
            )
            expr_values = {
                ':prev_status': previous_status,
                ':now': now
            }
            
            bookings_table.update_item(
                Key={'bookingId': booking_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues=expr_values
            )
            
            # If restoring to accepted/confirmed, increment positionsFilled
            if previous_status in ['accepted', 'confirmed'] and listing_id:
                try:
                    job_listings_table.update_item(
                        Key={'listingId': listing_id},
                        UpdateExpression='ADD positionsFilled :inc',
                        ExpressionAttributeValues={':inc': 1}
                    )
                    # Update cache
                    if listing_id in listing_cache:
                        listing_cache[listing_id]['positionsFilled'] += 1
                except Exception as e:
                    logger.error(f"Error incrementing positionsFilled for listing {listing_id}: {e}")
            
            restored_count += 1
            details.append({
                'bookingId': booking_id,
                'status': 'restored',
                'restoredTo': previous_status
            })
            logger.info(f"Restored booking {booking_id} to {previous_status}")
            
        except Exception as e:
            logger.error(f"Error restoring booking {booking_id}: {e}")
            details.append({
                'bookingId': booking_id,
                'status': 'error',
                'error': str(e)
            })
    
    return restored_count, not_restored_count, details


def _check_listing_capacity(listing_id, cache):
    """
    Check if a listing has available positions.
    Uses a cache to avoid repeated DynamoDB reads for the same listing.
    
    Returns True if there is capacity, False otherwise.
    """
    if listing_id in cache:
        listing = cache[listing_id]
    else:
        try:
            response = job_listings_table.get_item(Key={'listingId': listing_id})
            listing = response.get('Item', {})
            cache[listing_id] = {
                'positions': int(listing.get('positions', 1)),
                'positionsFilled': int(listing.get('positionsFilled', 0))
            }
            listing = cache[listing_id]
        except Exception as e:
            logger.error(f"Error checking listing capacity for {listing_id}: {e}")
            return False
    
    return listing['positionsFilled'] < listing['positions']


def restore_account(user_id, profile):
    """
    Restore a user account that was marked for deletion.
    
    Steps:
    1. Remove deletion flags from profile
    2. Restore paused listings (company only)
    3. Restore cancelled bookings
    
    Returns: restore_summary dict
    """
    profile_type = profile.get('profile_type', 'basic')
    
    logger.info(f"Restoring account for user {user_id} (type: {profile_type})")
    
    summary = {
        'account_restored': True,
        'message': 'Il tuo account è stato ripristinato con successo.',
        'listings_restored': 0,
        'bookings_restored': 0,
        'bookings_not_restored': 0,
        'warnings': []
    }
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Step 1: Remove deletion flags from profile
    try:
        table.update_item(
            Key={'user_id': user_id},
            UpdateExpression=(
                'SET updatedAt = :now '
                'REMOVE account_status, deletion_requested_at, deletion_scheduled_at'
            ),
            ExpressionAttributeValues={':now': now}
        )
        logger.info(f"Removed deletion flags for user {user_id}")
    except Exception as e:
        logger.error(f"Error removing deletion flags for user {user_id}: {e}")
        summary['warnings'].append('Error removing deletion flags')
    
    # Step 2: Restore company listings (if company user)
    if profile_type in ['company', 'company_representative']:
        company_id = profile.get('companyId')
        if not company_id:
            # Fallback: companyId may not be stored in UserProfiles — fetch from Companies table
            try:
                company_record = companies_table.get_item(Key={'userId': user_id})
                company_id = company_record.get('Item', {}).get('companyId')
            except Exception as e:
                logger.warning(f"Could not fetch companyId from Companies table for user {user_id}: {e}")
        if company_id:
            restored, listing_details = restore_company_listings(company_id)
            summary['listings_restored'] = restored
            if listing_details:
                summary['listing_details'] = listing_details
            
            # Restore company bookings
            b_restored, b_not_restored, b_details = restore_company_bookings(company_id)
            summary['bookings_restored'] = b_restored
            summary['bookings_not_restored'] = b_not_restored
            
            if b_not_restored > 0:
                summary['warnings'].append(
                    f'{b_not_restored} booking(s) could not be restored because positions are no longer available.'
                )
            if b_details:
                summary['booking_details'] = b_details
    else:
        # Worker or basic user - restore worker bookings
        b_restored, b_not_restored, b_details = restore_worker_bookings(user_id)
        summary['bookings_restored'] = b_restored
        summary['bookings_not_restored'] = b_not_restored
        
        if b_not_restored > 0:
            summary['warnings'].append(
                f'{b_not_restored} booking(s) could not be restored because positions are no longer available.'
            )
        if b_details:
            summary['booking_details'] = b_details
    
    logger.info(f"Account restore completed for {user_id}: {json.dumps(summary, default=str)}")
    return summary


def _enrich_profile_from_cognito(profile, user_id):
    """
    If given_name or family_name are absent from the DynamoDB profile sub-object,
    fetch them from Cognito (authoritative source) and inject them.
    This is a safety net for profiles that lost name data due to partial updates.
    """
    try:
        if not USER_POOL_ID:
            return profile
        profile_sub = profile.get('profile')
        if not isinstance(profile_sub, dict):
            profile_sub = {}
        if profile_sub.get('given_name') and profile_sub.get('family_name'):
            return profile  # already present, nothing to do
        response = cognito.admin_get_user(UserPoolId=USER_POOL_ID, Username=user_id)
        cognito_attrs = {attr['Name']: attr['Value'] for attr in response.get('UserAttributes', [])}
        changed = False
        if cognito_attrs.get('given_name') and not profile_sub.get('given_name'):
            profile_sub['given_name'] = cognito_attrs['given_name']
            changed = True
        if cognito_attrs.get('family_name') and not profile_sub.get('family_name'):
            profile_sub['family_name'] = cognito_attrs['family_name']
            changed = True
        if changed:
            profile['profile'] = profile_sub
    except Exception as e:
        logger.warning(f"Could not enrich profile with Cognito data for {user_id}: {e}")
    return profile


def handler(event, context):
    """
    GET /profile
    
    Returns the authenticated user's profile.
    If the profile is marked for deletion (account_status='to_be_deleted'),
    it automatically restores the account and adds restore info to the response.
    """
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        response = table.get_item(Key={'user_id': user_id})
        
        if 'Item' not in response:
            return _cors_response(404, {'error': 'Profile not found'})
        
        profile = response['Item']
        
        # Check if account is marked for deletion → auto-restore
        restore_info = None
        if profile.get('account_status') == 'to_be_deleted':
            logger.info(f"Auto-restoring account for user {user_id} (deletion was pending)")
            restore_info = restore_account(user_id, profile)
            
            # Re-fetch the cleaned profile after restore
            response = table.get_item(Key={'user_id': user_id})
            if 'Item' in response:
                profile = response['Item']
        
        # Enrich with Cognito names if they were lost from DynamoDB (safety net)
        profile = _enrich_profile_from_cognito(profile, user_id)

        # Build response
        response_body = profile
        
        if restore_info:
            response_body['_restore_info'] = restore_info
        
        return _cors_response(200, response_body)
        
    except Exception as e:
        logger.error(f"Error in get-profile: {e}", exc_info=True)
        return _cors_response(500, {'error': str(e)})