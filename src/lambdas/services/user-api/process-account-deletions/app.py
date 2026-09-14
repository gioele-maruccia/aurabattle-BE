"""
Process Account Deletions - Scheduled Cron Job

Runs daily at 3:00 AM UTC to permanently delete accounts that have been
marked as 'to_be_deleted' for more than 15 days.

Flow for each account past the grace period:
1. For company users:
   - Set all paused listings (suspendedByDeletion) to 'closed'
   - Set any remaining published/paused/draft listings to 'closed'
   - Delete company record from Companies table
2. Delete all user documents from DynamoDB and S3
3. Delete user profile from UserProfiles table
4. Delete user from Cognito

Bookings and listings are NOT deleted - they remain in the DB
but lose the reference to the deleted user.

Version: 1.0.0
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
USER_DOCUMENTS_TABLE = os.environ['USER_DOCUMENTS_TABLE']
DOCUMENTS_BUCKET = os.environ['DOCUMENTS_BUCKET']
BOOKINGS_TABLE = os.environ['BOOKINGS_TABLE']
JOB_LISTINGS_TABLE = os.environ['JOB_LISTINGS_TABLE']
COMPANIES_TABLE = os.environ['COMPANIES_TABLE']
USER_POOL_ID = os.environ['USER_POOL_ID']

# Grace period
DELETION_GRACE_PERIOD_DAYS = 15

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
cognito = boto3.client('cognito-idp')
s3 = boto3.client('s3')

profiles_table = dynamodb.Table(USER_PROFILES_TABLE)
documents_table = dynamodb.Table(USER_DOCUMENTS_TABLE)
bookings_table = dynamodb.Table(BOOKINGS_TABLE)
job_listings_table = dynamodb.Table(JOB_LISTINGS_TABLE)
companies_table = dynamodb.Table(COMPANIES_TABLE)


def find_accounts_to_delete():
    """
    Scan UserProfiles for accounts marked as 'to_be_deleted'
    where deletion_requested_at is older than DELETION_GRACE_PERIOD_DAYS.
    
    Returns list of user profiles to delete.
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=DELETION_GRACE_PERIOD_DAYS)).isoformat()
    
    logger.info(f"Looking for accounts to delete with deletion_requested_at < {cutoff_date}")
    
    accounts = []
    scan_kwargs = {
        'FilterExpression': (
            Attr('account_status').eq('to_be_deleted') &
            Attr('deletion_requested_at').lt(cutoff_date)
        )
    }
    
    while True:
        response = profiles_table.scan(**scan_kwargs)
        accounts.extend(response.get('Items', []))
        
        if 'LastEvaluatedKey' not in response:
            break
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    
    logger.info(f"Found {len(accounts)} accounts to delete")
    return accounts


def close_company_listings(company_id):
    """
    Set all active/paused/draft listings of a company to 'closed'.
    These listings remain in the DB for historical reference.
    
    Returns count of closed listings.
    """
    try:
        response = job_listings_table.query(
            IndexName='companyId-createdAt-index',
            KeyConditionExpression=Key('companyId').eq(company_id)
        )
        
        now = datetime.now(timezone.utc).isoformat()
        closed_count = 0
        closable_statuses = ['published', 'paused', 'draft']
        
        for listing in response.get('Items', []):
            listing_id = listing.get('listingId')
            listing_status = listing.get('status')
            
            if listing_status not in closable_statuses:
                continue
            
            try:
                job_listings_table.update_item(
                    Key={'listingId': listing_id},
                    UpdateExpression=(
                        'SET #status = :closed, '
                        'updatedAt = :now, '
                        'closedByDeletion = :deleted, '
                        'closedAt = :now'
                    ),
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':closed': 'closed',
                        ':now': now,
                        ':deleted': True
                    }
                )
                closed_count += 1
                logger.info(f"Closed listing {listing_id} (was {listing_status}) for account deletion")
                
            except Exception as e:
                logger.error(f"Error closing listing {listing_id}: {e}")
        
        return closed_count
        
    except Exception as e:
        logger.error(f"Error querying company listings for closure: {e}")
        return 0


def delete_s3_files(s3_keys):
    """Delete files from S3"""
    if not s3_keys:
        return 0
    
    deleted_count = 0
    for s3_key in s3_keys:
        try:
            s3.delete_object(Bucket=DOCUMENTS_BUCKET, Key=s3_key)
            deleted_count += 1
            logger.info(f"Deleted S3 file: {s3_key}")
        except ClientError as e:
            logger.error(f"Error deleting S3 file {s3_key}: {e}")
    
    return deleted_count


def delete_user_documents(user_id):
    """
    Delete all documents for a user from DynamoDB and S3.
    Returns: (documents_deleted, s3_files_deleted)
    """
    try:
        pk = f"USER#{user_id}"
        response = documents_table.query(
            KeyConditionExpression=Key('pk').eq(pk)
        )
        
        documents = response.get('Items', [])
        s3_keys = [doc['s3Key'] for doc in documents if 's3Key' in doc]
        
        # Delete S3 files
        s3_deleted = delete_s3_files(s3_keys)
        
        # Delete document records
        doc_deleted = 0
        for doc in documents:
            try:
                documents_table.delete_item(
                    Key={'pk': doc['pk'], 'sk': doc['sk']}
                )
                doc_deleted += 1
            except ClientError as e:
                logger.error(f"Error deleting document record {doc.get('sk')}: {e}")
        
        return doc_deleted, s3_deleted
        
    except Exception as e:
        logger.error(f"Error deleting user documents: {e}")
        return 0, 0


def delete_company_record(user_id):
    """Delete company record from Companies table"""
    try:
        companies_table.delete_item(Key={'userId': user_id})
        logger.info(f"Deleted company record for user: {user_id}")
        return True
    except ClientError as e:
        logger.error(f"Error deleting company record for user {user_id}: {e}")
        return False


def delete_cognito_user(user_id):
    """Delete user from Cognito"""
    try:
        cognito.admin_delete_user(
            UserPoolId=USER_POOL_ID,
            Username=user_id
        )
        logger.info(f"Deleted Cognito user: {user_id}")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'UserNotFoundException':
            logger.warning(f"Cognito user already deleted: {user_id}")
            return True
        logger.error(f"Error deleting Cognito user {user_id}: {e}")
        return False


def delete_user_profile(user_id):
    """Delete user profile from DynamoDB"""
    try:
        profiles_table.delete_item(Key={'user_id': user_id})
        logger.info(f"Deleted user profile: {user_id}")
        return True
    except ClientError as e:
        logger.error(f"Error deleting user profile {user_id}: {e}")
        return False


def process_single_deletion(profile):
    """
    Process the permanent deletion of a single user account.
    
    Returns: result dict with counts
    """
    user_id = profile['user_id']
    profile_type = profile.get('profile_type', 'basic')
    
    logger.info(f"Processing permanent deletion for user: {user_id} (type: {profile_type})")
    
    result = {
        'user_id': user_id,
        'profile_type': profile_type,
        'success': True,
        'listings_closed': 0,
        'documents_deleted': 0,
        's3_files_deleted': 0,
        'company_deleted': False,
        'cognito_deleted': False,
        'profile_deleted': False
    }
    
    try:
        # Step 1: Handle company-specific data
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
                # Close all remaining active listings
                result['listings_closed'] = close_company_listings(company_id)
                
                # Delete company record
                result['company_deleted'] = delete_company_record(user_id)
            else:
                logger.warning(f"No companyId found for company user {user_id}")
        
        # Step 2: Delete user documents from DynamoDB + S3
        doc_count, s3_count = delete_user_documents(user_id)
        result['documents_deleted'] = doc_count
        result['s3_files_deleted'] = s3_count
        
        # Step 3: Delete user profile from DynamoDB
        result['profile_deleted'] = delete_user_profile(user_id)
        
        # Step 4: Delete user from Cognito (last step - point of no return)
        result['cognito_deleted'] = delete_cognito_user(user_id)
        
        logger.info(f"Permanent deletion completed for user {user_id}: {json.dumps(result, default=str)}")
        
    except Exception as e:
        result['success'] = False
        result['error'] = str(e)
        logger.error(f"Error during permanent deletion of user {user_id}: {e}", exc_info=True)
    
    return result


def handler(event, context):
    """
    Lambda handler - triggered by EventBridge schedule (cron).
    
    Scans for accounts marked as 'to_be_deleted' past the grace period
    and permanently deletes them.
    """
    try:
        logger.info("=== Starting process-account-deletions cron job ===")
        logger.info(f"Environment: {ENVIRONMENT}")
        logger.info(f"Grace period: {DELETION_GRACE_PERIOD_DAYS} days")
        
        # Find accounts to delete
        accounts = find_accounts_to_delete()
        
        if not accounts:
            logger.info("No accounts to delete. Job complete.")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No accounts to delete',
                    'processed': 0
                })
            }
        
        # Process each account
        results = []
        success_count = 0
        error_count = 0
        
        for profile in accounts:
            result = process_single_deletion(profile)
            results.append(result)
            
            if result['success']:
                success_count += 1
            else:
                error_count += 1
        
        summary = {
            'total_processed': len(accounts),
            'success': success_count,
            'errors': error_count,
            'results': results
        }
        
        logger.info(f"=== Process-account-deletions completed: {json.dumps(summary, default=str)} ===")
        
        return {
            'statusCode': 200,
            'body': json.dumps(summary, default=str)
        }
        
    except Exception as e:
        logger.error(f"Fatal error in process-account-deletions: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': str(e)
            })
        }
