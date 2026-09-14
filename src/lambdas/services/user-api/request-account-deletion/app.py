"""
Request Account Deletion Handler

Marks a user's account for deletion after a 15-day grace period.
During the grace period, the user can restore their account by logging in.

Flow:
1. Validate no blocking bookings exist (blocks deletion if any exist)
2. For company users: pause all published job listings (suspendedByDeletion=true)
3. For all users: cancel ONLY pending bookings (suspendedByDeletion=true, previousStatus saved)
4. Mark user profile with account_status='to_be_deleted' and deletion_requested_at

Booking Status Rules:
- pending → auto-cancelled (suspendedByDeletion=true). Worker applied, company hasn't committed yet.
- accepted, confirmed → BLOCKING (company has committed). User must resolve first.
- contracted → BLOCKING (active contract exists). User must resolve first.
- completed, cancelled, rejected, blocked, no_show → terminal, untouched.

NOTE: 'accepted' is a legacy status never set by current lambdas but treated the same as
'confirmed' for safety, since both represent a company commitment to a worker.

Listing Status Rules (company only):
- published → paused (suspendedByDeletion=true, previousStatus='published')
- paused, draft, closed, expired, deleted, archived → untouched

Version: 1.1.0
"""

import json
import os
import boto3
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
USER_PROFILES_TABLE = os.environ['USER_PROFILES_TABLE']
BOOKINGS_TABLE = os.environ['BOOKINGS_TABLE']
JOB_LISTINGS_TABLE = os.environ['JOB_LISTINGS_TABLE']
COMPANIES_TABLE = os.environ['COMPANIES_TABLE']
USER_POOL_ID = os.environ['USER_POOL_ID']

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
cognito = boto3.client('cognito-idp')

profiles_table = dynamodb.Table(USER_PROFILES_TABLE)
bookings_table = dynamodb.Table(BOOKINGS_TABLE)
job_listings_table = dynamodb.Table(JOB_LISTINGS_TABLE)
companies_table = dynamodb.Table(COMPANIES_TABLE)

# Grace period in days
DELETION_GRACE_PERIOD_DAYS = 15

# Booking statuses that are auto-cancelled on deletion request (no company commitment yet)
AUTO_CANCEL_BOOKING_STATUSES = ['pending']

# Booking statuses that BLOCK deletion (company has committed, or active contract)
# 'accepted' = legacy status (never set by current lambdas, kept for safety)
# 'confirmed' = current status set by update-booking-status when company accepts
BLOCKING_BOOKING_STATUSES = ['contracted', 'accepted', 'confirmed']

# Terminal booking statuses (leave untouched)
TERMINAL_BOOKING_STATUSES = ['completed', 'cancelled', 'rejected', 'blocked', 'no_show']


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


def get_user_groups(user_id):
    """Get Cognito groups for the user"""
    try:
        response = cognito.admin_list_groups_for_user(
            UserPoolId=USER_POOL_ID,
            Username=user_id
        )
        return [g['GroupName'] for g in response.get('Groups', [])]
    except ClientError as e:
        logger.error(f"Error getting user groups: {e}")
        return []


def get_company_id(user_id):
    """Get the companyId for a company user from their profile"""
    try:
        response = profiles_table.get_item(Key={'user_id': user_id})
        return response.get('Item', {}).get('companyId')
    except Exception as e:
        logger.error(f"Error getting companyId for user {user_id}: {e}")
        return None


def check_worker_bookings(user_id):
    """
    Check worker's bookings for blocking and auto-cancellable statuses.
    
    Blocking: contracted, accepted, confirmed (company has committed)
    Auto-cancel: pending (no commitment yet)
    
    Returns: (has_blocking, blocking_bookings, pending_bookings)
    """
    try:
        response = bookings_table.query(
            IndexName='workerId-startDate-index',
            KeyConditionExpression=Key('workerId').eq(user_id)
        )
        
        blocking = []
        pending = []
        
        for booking in response.get('Items', []):
            status = booking.get('status')
            booking_info = {
                'bookingId': booking.get('bookingId'),
                'listingId': booking.get('listingId'),
                'jobTitle': booking.get('jobTitle'),
                'companyName': booking.get('companyName'),
                'startDate': booking.get('startDate'),
                'endDate': booking.get('endDate'),
                'status': status
            }
            
            if status in BLOCKING_BOOKING_STATUSES:
                blocking.append(booking_info)
            elif status in AUTO_CANCEL_BOOKING_STATUSES:
                pending.append(booking_info)
        
        return len(blocking) > 0, blocking, pending
        
    except Exception as e:
        logger.error(f"Error checking worker bookings: {e}")
        raise


def check_company_bookings(company_id):
    """
    Check company's bookings for blocking and auto-cancellable statuses.
    Uses companyId-status-index GSI for efficient querying.
    
    Blocking: contracted, accepted, confirmed (company has committed)
    Auto-cancel: pending only
    
    Returns: (has_blocking, blocking_bookings, pending_bookings)
    """
    try:
        blocking = []
        pending = []
        
        # Check each relevant status via GSI (companyId + status)
        for status in BLOCKING_BOOKING_STATUSES + AUTO_CANCEL_BOOKING_STATUSES:
            response = bookings_table.query(
                IndexName='companyId-status-index',
                KeyConditionExpression=Key('companyId').eq(company_id) & Key('status').eq(status)
            )
            
            for booking in response.get('Items', []):
                booking_info = {
                    'bookingId': booking.get('bookingId'),
                    'listingId': booking.get('listingId'),
                    'jobTitle': booking.get('jobTitle'),
                    'workerName': booking.get('workerName'),
                    'startDate': booking.get('startDate'),
                    'endDate': booking.get('endDate'),
                    'status': status
                }
                
                if status in BLOCKING_BOOKING_STATUSES:
                    blocking.append(booking_info)
                else:
                    pending.append(booking_info)
        
        return len(blocking) > 0, blocking, pending
        
    except Exception as e:
        logger.error(f"Error checking company bookings: {e}")
        raise


def cancel_bookings_for_deletion(bookings_to_cancel, cancelled_by_role):
    """
    Cancel ONLY pending bookings due to account deletion request.
    Marks each with suspendedByDeletion=true and saves previousStatus.
    Pending bookings do NOT affect positionsFilled (only confirmed/accepted do).
    
    Returns: (success_count, error_count, decrement_listing_ids)
    """
    now = datetime.now(timezone.utc).isoformat()
    success_count = 0
    error_count = 0
    listings_to_decrement = []
    
    for booking in bookings_to_cancel:
        booking_id = booking['bookingId']
        previous_status = booking['status']
        
        try:
            bookings_table.update_item(
                Key={'bookingId': booking_id},
                UpdateExpression=(
                    'SET #status = :cancelled, '
                    'updatedAt = :now, '
                    'cancelledAt = :now, '
                    'cancelledByRole = :role, '
                    'cancellationReason = :reason, '
                    'suspendedByDeletion = :suspended, '
                    'previousStatus = :prev_status'
                ),
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':cancelled': 'cancelled',
                    ':now': now,
                    ':role': 'system',
                    ':reason': f'Account deletion requested by {cancelled_by_role}. The user has requested to delete their account from the platform.',
                    ':suspended': True,
                    ':prev_status': previous_status
                }
            )
            success_count += 1
            logger.info(f"Cancelled booking {booking_id} (was {previous_status}) for account deletion")
            
            # NOTE: pending bookings do NOT affect positionsFilled
            # (only confirmed/accepted bookings do, but those are now blocking)
            
        except Exception as e:
            error_count += 1
            logger.error(f"Error cancelling booking {booking_id}: {e}")
    
    return success_count, error_count, []


def pause_company_listings(company_id):
    """
    Pause all published job listings for a company due to account deletion.
    Only published listings are paused (they are the only "visible" ones).
    Marks each with suspendedByDeletion=true and saves previousStatus.
    
    Returns: (success_count, error_count, paused_listing_ids)
    """
    try:
        response = job_listings_table.query(
            IndexName='companyId-createdAt-index',
            KeyConditionExpression=Key('companyId').eq(company_id)
        )
        
        now = datetime.now(timezone.utc).isoformat()
        success_count = 0
        error_count = 0
        paused_ids = []
        
        for listing in response.get('Items', []):
            listing_id = listing.get('listingId')
            listing_status = listing.get('status')
            
            # Only pause published listings
            if listing_status != 'published':
                continue
            
            try:
                job_listings_table.update_item(
                    Key={'listingId': listing_id},
                    UpdateExpression=(
                        'SET #status = :paused, '
                        'updatedAt = :now, '
                        'suspendedByDeletion = :suspended, '
                        'previousStatus = :prev_status'
                    ),
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':paused': 'paused',
                        ':now': now,
                        ':published': 'published',
                        ':suspended': True,
                        ':prev_status': listing_status
                    },
                    ConditionExpression='#status = :published'
                )
                success_count += 1
                paused_ids.append(listing_id)
                logger.info(f"Paused listing {listing_id} for account deletion")
                
            except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
                logger.warning(f"Listing {listing_id} status changed, skipping")
            except Exception as e:
                error_count += 1
                logger.error(f"Error pausing listing {listing_id}: {e}")
        
        return success_count, error_count, paused_ids
        
    except Exception as e:
        logger.error(f"Error querying company listings: {e}")
        raise


def handler(event, context):
    """
    POST /profile/delete-request
    
    Marks the authenticated user's account for deletion after a 15-day grace period.
    
    Authorization: Cognito JWT (user's own token)
    
    Response on success:
    {
        "message": "Account marked for deletion",
        "deletion_scheduled_at": "2026-03-12T...",
        "grace_period_days": 15,
        "summary": {
            "bookings_cancelled": N,
            "listings_paused": N
        },
        "restore_info": "Log in within 15 days to automatically restore your account."
    }
    """
    try:
        # Get user_id from Cognito token
        user_id = event['requestContext']['authorizer']['claims']['sub']
        logger.info(f"Account deletion request from user: {user_id}")
        
        # Step 0: Check if profile exists and is not already marked for deletion
        profile_response = profiles_table.get_item(Key={'user_id': user_id})
        
        if 'Item' not in profile_response:
            return _cors_response(404, {
                'error': 'Not Found',
                'message': 'User profile does not exist.'
            })
        
        profile = profile_response['Item']
        
        if profile.get('account_status') == 'to_be_deleted':
            deletion_date = profile.get('deletion_requested_at', 'unknown')
            return _cors_response(409, {
                'code': 4090,
                'error': 'Conflict',
                'message': 'Your account is already marked for deletion.',
                'deletion_requested_at': deletion_date,
                'deletion_scheduled_at': str(
                    datetime.fromisoformat(deletion_date.replace('Z', '+00:00'))
                    + timedelta(days=DELETION_GRACE_PERIOD_DAYS)
                ) if deletion_date != 'unknown' else 'unknown'
            })
        
        profile_type = profile.get('profile_type', 'basic')
        user_groups = get_user_groups(user_id)
        
        logger.info(f"User profile_type: {profile_type}, groups: {user_groups}")
        
        summary = {
            'bookings_cancelled': 0,
            'bookings_errors': 0,
            'listings_paused': 0,
            'listings_errors': 0
        }
        
        # ============================================
        # COMPANY FLOW
        # ============================================
        if 'companies' in user_groups or profile_type in ['company', 'company_representative']:
            company_id = profile.get('companyId')
            
            if not company_id:
                # Try to get from Companies table
                try:
                    company_response = companies_table.get_item(Key={'userId': user_id})
                    company_id = company_response.get('Item', {}).get('companyId')
                except Exception:
                    pass
            
            if not company_id:
                return _cors_response(400, {
                    'error': 'Bad Request',
                    'message': 'Your company profile could not be found. Please contact support.'
                })
            
            # Check for contracted bookings (blocking)
            has_blocking, blocking_bookings, pending_bookings = check_company_bookings(company_id)
            
            if has_blocking:
                return _cors_response(409, {
                    'code': 4091,
                    'error': 'Conflict',
                    'message': (
                        f'You have {len(blocking_bookings)} confirmed or contracted booking(s). '
                        'Please cancel or complete all confirmed (accepted) bookings and resolve all '
                        'contracts before requesting account deletion.'
                    ),
                    'blocking_bookings': blocking_bookings
                })
            
            # Pause all published listings
            paused_count, pause_errors, paused_ids = pause_company_listings(company_id)
            summary['listings_paused'] = paused_count
            summary['listings_errors'] = pause_errors
            
            logger.info(f"Paused {paused_count} listings for company {company_id}")
            
            # Auto-cancel only pending bookings
            if pending_bookings:
                cancelled_count, cancel_errors, _ = cancel_bookings_for_deletion(
                    pending_bookings, 'company'
                )
                summary['bookings_cancelled'] = cancelled_count
                summary['bookings_errors'] = cancel_errors
                
                logger.info(f"Cancelled {cancelled_count} pending bookings for company {company_id}")
        
        # ============================================
        # WORKER FLOW
        # ============================================
        elif 'workers' in user_groups or profile_type == 'worker':
            # Check for blocking bookings (confirmed, accepted, contracted)
            has_blocking, blocking_bookings, pending_bookings = check_worker_bookings(user_id)
            
            if has_blocking:
                return _cors_response(409, {
                    'code': 4091,
                    'error': 'Conflict',
                    'message': (
                        f'You have {len(blocking_bookings)} confirmed or contracted booking(s). '
                        'Please cancel or complete all confirmed bookings and resolve all '
                        'contracts before requesting account deletion.'
                    ),
                    'blocking_bookings': blocking_bookings
                })
            
            # Auto-cancel only pending bookings
            if pending_bookings:
                cancelled_count, cancel_errors, _ = cancel_bookings_for_deletion(
                    pending_bookings, 'worker'
                )
                summary['bookings_cancelled'] = cancelled_count
                summary['bookings_errors'] = cancel_errors
                
                logger.info(f"Cancelled {cancelled_count} pending bookings for worker {user_id}")
        
        # ============================================
        # BASIC USER FLOW
        # ============================================
        else:
            # Basic users shouldn't have bookings, but check anyway
            has_blocking, blocking_bookings, pending_bookings = check_worker_bookings(user_id)
            
            if has_blocking:
                return _cors_response(409, {
                    'code': 4091,
                    'error': 'Conflict',
                    'message': 'You have confirmed or contracted bookings. Please resolve them before requesting account deletion.',
                    'blocking_bookings': blocking_bookings
                })
            
            if pending_bookings:
                cancelled_count, cancel_errors, _ = cancel_bookings_for_deletion(
                    pending_bookings, 'user'
                )
                summary['bookings_cancelled'] = cancelled_count
                summary['bookings_errors'] = cancel_errors
        
        # ============================================
        # MARK PROFILE FOR DELETION
        # ============================================
        now = datetime.now(timezone.utc).isoformat()
        deletion_scheduled = (datetime.now(timezone.utc) + timedelta(days=DELETION_GRACE_PERIOD_DAYS)).isoformat()
        
        profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression=(
                'SET account_status = :status, '
                'deletion_requested_at = :requested_at, '
                'deletion_scheduled_at = :scheduled_at, '
                'updatedAt = :now'
            ),
            ExpressionAttributeValues={
                ':status': 'to_be_deleted',
                ':requested_at': now,
                ':scheduled_at': deletion_scheduled,
                ':now': now
            }
        )
        
        logger.info(f"Account marked for deletion: user={user_id}, scheduled_at={deletion_scheduled}")
        
        return _cors_response(200, {
            'message': 'Account marked for deletion',
            'deletion_requested_at': now,
            'deletion_scheduled_at': deletion_scheduled,
            'grace_period_days': DELETION_GRACE_PERIOD_DAYS,
            'summary': summary,
            'restore_info': 'Log in within 15 days to automatically restore your account.'
        })
        
    except KeyError as e:
        logger.error(f"KeyError: {e}")
        return _cors_response(401, {'error': 'Unauthorized'})
    except Exception as e:
        logger.error(f"Unexpected error in request-account-deletion: {e}", exc_info=True)
        return _cors_response(500, {
            'error': 'Internal Server Error',
            'message': str(e)
        })
