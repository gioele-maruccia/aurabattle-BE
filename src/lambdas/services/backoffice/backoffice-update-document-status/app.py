import json
import os
import sys
import boto3
import logging
from datetime import datetime, timezone
from botocore.exceptions import ClientError
from typing import Dict, Any, List, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ["BUCKET_NAME"]
REGION = os.environ["REGION"]
USER_POOL_ID = os.environ["USER_POOL_ID"]
COMPANIES_TABLE_NAME = os.environ.get("COMPANIES_TABLE_NAME", "dev-Companies")
USER_PROFILES_TABLE = os.environ.get("USER_PROFILES_TABLE", "dev-UserProfiles")

dynamodb = boto3.resource('dynamodb', region_name=REGION)
s3_client = boto3.client('s3', region_name=REGION)
cognito_client = boto3.client('cognito-idp', region_name=REGION)
scheduler_client = boto3.client('scheduler', region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
companies_table = dynamodb.Table(COMPANIES_TABLE_NAME)
user_profiles_table = dynamodb.Table(USER_PROFILES_TABLE)

# Firebase notifications (optional, best-effort)
try:
    # Lambda layers are mounted under /opt/python for Python runtimes.
    sys.path.append('/opt/python')
    # Keep backward compatibility if older layers were mounted differently.
    sys.path.append('/opt/firebase')
    from firebase_notifications import send_profile_upgrade_notification
    FIREBASE_AVAILABLE = True
except ImportError:
    logger.info("Firebase layer not available - push notifications disabled")
    FIREBASE_AVAILABLE = False

# Document status constants
VALID_STATUSES = {
    'APPROVED': 'Document approved by reviewer',
    'REJECTED': 'Document rejected by reviewer'
}
REQUIRED_CURRENT_STATUS = 'AWAITING_REVIEW'

# User profile types and required documents
PROFILE_REQUIREMENTS = {
    'worker': {
        # TODO: re-aggiungere 'selfie' quando verrà richiesto di nuovo
        # 'selfie' temporaneamente rimosso dal flusso di approvazione worker
        'required_docs': ['id_card_front', 'id_card_back'],
        'cognito_group': 'workers',
        'verification_status': 'approved'
    },
    'company': {
        # TODO: re-aggiungere 'visura' e 'selfie' quando verranno richiesti di nuovo
        # 'visura' e 'selfie' temporaneamente rimossi dal flusso di approvazione company
        # 'required_docs': ['id_card_front', 'id_card_back', 'visura', 'selfie'],
        'required_docs': ['id_card_front', 'id_card_back'],
        'cognito_group': 'companies',
        'verification_status': 'approved'
    }
}

# Cognito groups
COGNITO_GROUPS = {
    'basic': 'basic_users',
    'pending': 'pending_review',
    'worker': 'workers',
    'company': 'companies'
}

def _cors_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Standardized CORS response format"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "PUT,OPTIONS"
        },
        "body": json.dumps(body)
    }

def _get_current_timestamp() -> str:
    """Get current UTC timestamp in ISO format"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _parse_doc_id(doc_id: str) -> tuple[str, str]:
    """Parse document ID into timestamp and doc_type"""
    try:
        timestamp, doc_type = doc_id.split('_', 1)
        return timestamp, doc_type
    except ValueError:
        raise ValueError(f"Invalid document ID format: {doc_id}")

def _extract_reviewer_info(event: Dict[str, Any]) -> Dict[str, str]:
    """Extract reviewer information from Cognito claims"""
    try:
        authorizer = event.get('requestContext', {}).get('authorizer', {})
        claims = authorizer.get('jwt', {}).get('claims', {})
        
        return {
            'reviewerId': claims.get('sub', 'unknown'),
            'reviewerEmail': claims.get('email', 'unknown'),
            'reviewerName': claims.get('name', claims.get('cognito:username', 'unknown'))
        }
    except Exception as e:
        logger.warning(f"Could not extract reviewer info: {str(e)}")
        return {
            'reviewerId': 'unknown',
            'reviewerEmail': 'unknown', 
            'reviewerName': 'unknown'
        }

def get_current_document_status(user_sub: str, doc_id: str) -> Dict[str, Any]:
    """Get current document from DynamoDB to verify status"""
    try:
        timestamp, doc_type = _parse_doc_id(doc_id)
        
        pk = f"USER#{user_sub}"
        sk = f"DOC#{doc_type}#{timestamp}"
        
        response = table.get_item(Key={'pk': pk, 'sk': sk})
        
        if 'Item' not in response:
            raise ValueError(f"Document not found: {doc_id} for user {user_sub}")
        
        return response['Item']
        
    except Exception as e:
        logger.error(f"Error getting current document status: {str(e)}")
        raise

def get_all_user_documents(user_sub: str) -> List[Dict[str, Any]]:
    """Get all documents for a user from DynamoDB"""
    try:
        pk = f"USER#{user_sub}"
        
        response = table.query(
            KeyConditionExpression='pk = :pk AND begins_with(sk, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': pk,
                ':sk_prefix': 'DOC#'
            }
        )
        
        return response.get('Items', [])
        
    except Exception as e:
        logger.error(f"Error getting user documents: {str(e)}")
        raise

def update_document_status(
    user_sub: str, 
    doc_id: str, 
    new_status: str, 
    reviewer_info: Dict[str, str],
    rejection_reason: str = None
) -> Dict[str, Any]:
    """Update document status in DynamoDB with validation"""
    try:
        timestamp, doc_type = _parse_doc_id(doc_id)
        
        pk = f"USER#{user_sub}"
        sk = f"DOC#{doc_type}#{timestamp}"
        
        update_expr = "SET #status = :status, #reviewedAt = :reviewedAt, #reviewedBy = :reviewedBy"
        expr_names = {
            '#status': 'status',
            '#reviewedAt': 'reviewedAt', 
            '#reviewedBy': 'reviewedBy'
        }
        expr_values = {
            ':status': new_status,
            ':reviewedAt': _get_current_timestamp(),
            ':reviewedBy': reviewer_info['reviewerEmail']
        }
        
        if new_status == 'REJECTED' and rejection_reason:
            update_expr += ", #rejectionReason = :rejectionReason"
            expr_names['#rejectionReason'] = 'rejectionReason'
            expr_values[':rejectionReason'] = rejection_reason
        
        condition_expr = "attribute_exists(pk) AND #status = :current_status"
        expr_values[':current_status'] = REQUIRED_CURRENT_STATUS
        
        response = table.update_item(
            Key={'pk': pk, 'sk': sk},
            UpdateExpression=update_expr,
            ConditionExpression=condition_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW"
        )
        
        return response['Attributes']
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ConditionalCheckFailedException':
            try:
                current_doc = get_current_document_status(user_sub, doc_id)
                current_status = current_doc.get('status', 'UNKNOWN')
                if current_status != REQUIRED_CURRENT_STATUS:
                    raise ValueError(f"Document status is '{current_status}', but must be '{REQUIRED_CURRENT_STATUS}' to be updated")
                else:
                    raise ValueError(f"Document not found: {doc_id} for user {user_sub}")
            except:
                raise ValueError(f"Document not found or not in correct status for update: {doc_id}")
        else:
            logger.error(f"DynamoDB error: {str(e)}")
            raise

def update_s3_tags(s3_key: str, status: str, reviewer_email: str) -> None:
    """Update S3 object tags to reflect new status"""
    try:
        try:
            response = s3_client.get_object_tagging(Bucket=BUCKET_NAME, Key=s3_key)
            existing_tags = response.get('TagSet', [])
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning(f"S3 object not found: {s3_key}")
                return
            existing_tags = []
        
        tag_dict = {tag['Key']: tag['Value'] for tag in existing_tags}
        tag_dict.update({
            'DocumentStatus': status,
            'ReviewedBy': reviewer_email,
            'ReviewedAt': _get_current_timestamp()
        })
        
        new_tags = [{'Key': k, 'Value': v} for k, v in tag_dict.items()]
        
        s3_client.put_object_tagging(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Tagging={'TagSet': new_tags}
        )
        
        logger.info(f"Updated S3 tags for {s3_key}")
        
    except Exception as e:
        logger.error(f"Error updating S3 tags: {str(e)}")

def get_user_cognito_attributes(user_sub: str) -> Dict[str, str]:
    """Get user attributes from Cognito"""
    try:
        response = cognito_client.admin_get_user(
            UserPoolId=USER_POOL_ID,
            Username=user_sub
        )
        
        attributes = {}
        for attr in response.get('UserAttributes', []):
            attr_name = attr['Name']
            # Remove 'custom:' prefix for custom attributes
            if attr_name.startswith('custom:'):
                attr_name = attr_name.replace('custom:', '')
            attributes[attr_name] = attr['Value']
        
        return attributes
        
    except Exception as e:
        logger.error(f"Error getting user Cognito attributes: {str(e)}")
        raise

def update_user_cognito_attributes(user_sub: str, attributes: Dict[str, str]) -> None:
    """Update user custom attributes in Cognito"""
    try:
        # Format attributes for Cognito
        user_attributes = []
        for key, value in attributes.items():
            # Add 'custom:' prefix if not a standard attribute
            if key in ['profile_type', 'verification_status', 'upgrade_requested_at']:
                attr_name = f'custom:{key}'
            else:
                attr_name = key
            
            user_attributes.append({
                'Name': attr_name,
                'Value': str(value)
            })
        
        cognito_client.admin_update_user_attributes(
            UserPoolId=USER_POOL_ID,
            Username=user_sub,
            UserAttributes=user_attributes
        )
        
        logger.info(f"Updated Cognito attributes for user {user_sub}: {attributes}")
        
    except Exception as e:
        logger.error(f"Error updating Cognito attributes: {str(e)}")
        raise

def get_user_cognito_groups(user_sub: str) -> List[str]:
    """Get user's current Cognito groups"""
    try:
        response = cognito_client.admin_list_groups_for_user(
            UserPoolId=USER_POOL_ID,
            Username=user_sub
        )
        
        return [group['GroupName'] for group in response.get('Groups', [])]
        
    except Exception as e:
        logger.error(f"Error getting user groups: {str(e)}")
        return []

def remove_user_from_group(user_sub: str, group_name: str) -> None:
    """Remove user from a Cognito group"""
    try:
        cognito_client.admin_remove_user_from_group(
            UserPoolId=USER_POOL_ID,
            Username=user_sub,
            GroupName=group_name
        )
        logger.info(f"Removed user {user_sub} from group {group_name}")
    except Exception as e:
        logger.error(f"Error removing user from group {group_name}: {str(e)}")
        raise

def add_user_to_group(user_sub: str, group_name: str) -> None:
    """Add user to a Cognito group"""
    try:
        cognito_client.admin_add_user_to_group(
            UserPoolId=USER_POOL_ID,
            Username=user_sub,
            GroupName=group_name
        )
        logger.info(f"Added user {user_sub} to group {group_name}")
    except Exception as e:
        logger.error(f"Error adding user to group {group_name}: {str(e)}")
        raise


def kill_retention_push(user_id: str, retention: dict) -> None:
    """Cancel all pending EventBridge Scheduler jobs for the 3-Touch retention system."""
    for step in ['T1', 'T2', 'T3']:
        job_id = retention.get(f'{step.lower()}_job_id')
        if not job_id:
            continue
        try:
            scheduler_client.delete_schedule(Name=job_id)
            logger.info(f"Retention KILL SWITCH: cancelled {step} job {job_id} for user {user_id}")
        except scheduler_client.exceptions.ResourceNotFoundException:
            logger.info(f"Retention job {job_id} not found (already fired) for user {user_id}")
        except Exception as e:
            logger.warning(f"Could not cancel retention job {job_id} for {user_id}: {e}")

    try:
        user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression=(
                'SET retention_state.completed = :t, '
                'retention_state.current_step = :done, '
                'retention_state.last_event = :evt, '
                'retention_state.last_event_at = :now'
            ),
            ExpressionAttributeValues={
                ':t': True,
                ':done': 'done',
                ':evt': 'upgrade_flow_completed',
                ':now': datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        logger.error(f"Failed to update retention_state for {user_id} after kill switch: {e}")


def create_company_record(user_sub: str) -> Optional[str]:
    """
    Create a basic company record in Companies table when user is promoted to company
    This ensures consistency between Cognito groups and DynamoDB data
    
    Args:
        user_sub: User ID (Cognito sub)
        
    Returns:
        companyId if created, None if already exists or error
    """
    try:
        import uuid
        from decimal import Decimal
        
        # Check if company record already exists
        response = companies_table.get_item(Key={'userId': user_sub})
        if 'Item' in response:
            logger.info(f"Company record already exists for user {user_sub}")
            return response['Item'].get('companyId')
        
        # Get user info from Cognito
        user_attrs = get_user_cognito_attributes(user_sub)
        given_name = user_attrs.get('given_name', '')
        family_name = user_attrs.get('family_name', '')
        email = user_attrs.get('email', '')
        
        # Generate IDs and timestamps
        company_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # Create basic company record
        # This is a minimal record - user will need to complete their profile later
        company_item = {
            'userId': user_sub,
            'companyId': company_id,
            
            # Placeholder data - to be updated by user
            'businessName': f"{given_name} {family_name}".strip() or email,
            'vatNumber': '',  # To be filled by user
            'pec': email if email else '',
            
            # Empty address - to be filled by user
            'address': {
                'street': '',
                'city': '',
                'province': '',
                'postalCode': '',
                'country': 'IT'
            },
            
            # Empty ATECO - to be filled by user
            'atecoCodes': [],
            'primaryAtecoCode': '',
            'atecoName': '',
            'applicableRoles': [],
            'atecoDetails': {},
            
            # Default FIPE classification
            'fipeCategory': 'pubblici_esercizi',
            'fipeArticle': 'Art. 1, I',
            'tableName': 'Tabella Standard',
            
            # Business info
            'isSmallBusiness': False,
            'numberOfEmployees': None,
            'annualRevenue': None,
            'businessTypeDetails': {
                'businessType': None,
                'sector': None
            },
            
            # Additional fields
            'description': '',
            'location': {
                'city': '',
                'country': 'IT'
            },
            
            # Media
            'media': {
                'profileImageUrl': '',
                'logoUrl': '',
                'galleryImages': []
            },
            
            # Stats
            'stats': {
                'averageRating': Decimal('0'),
                'totalReviews': 0,
                'activeListingsCount': 0
            },
            
            # Profile completion status
            'profileCompleted': False,
            'profileCompletionPercentage': 10,  # Just created
            
            # Timestamps
            'createdAt': now,
            'updatedAt': now
        }
        
        # Save to DynamoDB
        companies_table.put_item(Item=company_item)
        
        logger.info(f"Created company record for user {user_sub} with companyId {company_id}")
        return company_id
        
    except Exception as e:
        logger.error(f"Error creating company record for user {user_sub}: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def check_and_update_user_verification(user_sub: str, updated_doc_type: str) -> Dict[str, Any]:
    """
    Check if user has completed verification and update Cognito accordingly
    Returns dict with promotion info if user was promoted
    """
    try:
        # Get user's current profile type and verification status
        user_attrs = get_user_cognito_attributes(user_sub)
        profile_type = user_attrs.get('profile_type', 'basic')
        current_verification = user_attrs.get('verification_status', 'pending')
        
        logger.info(f"Checking verification for user {user_sub}: profile_type={profile_type}, current_status={current_verification}")
        
        # If user is still basic, no verification to check
        if profile_type == 'basic':
            logger.info(f"User {user_sub} is basic profile, no verification needed")
            return {'action': 'none', 'reason': 'basic_profile'}
        
        # Check if profile type has requirements
        if profile_type not in PROFILE_REQUIREMENTS:
            logger.warning(f"Unknown profile type: {profile_type}")
            return {'action': 'none', 'reason': 'unknown_profile_type'}
        
        requirements = PROFILE_REQUIREMENTS[profile_type]
        required_docs = requirements['required_docs']
        target_group = requirements['cognito_group']
        
        # Get all user documents
        all_docs = get_all_user_documents(user_sub)
        
        # Group documents by type (keep only the latest for each type)
        docs_by_type = {}
        for doc in all_docs:
            doc_type = doc.get('docType')
            timestamp = doc.get('uploadedAt', '')
            
            if doc_type not in docs_by_type or timestamp > docs_by_type[doc_type].get('uploadedAt', ''):
                docs_by_type[doc_type] = doc
        
        logger.info(f"Found documents for user {user_sub}: {list(docs_by_type.keys())}")
        
        # Check if all required documents exist and their status
        approved_count = 0
        rejected_count = 0
        pending_count = 0
        
        for required_doc in required_docs:
            if required_doc not in docs_by_type:
                logger.info(f"Required document {required_doc} not found")
                pending_count += 1
                continue
            
            doc_status = docs_by_type[required_doc].get('status', 'PENDING')
            if doc_status == 'APPROVED':
                approved_count += 1
            elif doc_status == 'REJECTED':
                rejected_count += 1
            else:
                pending_count += 1
        
        logger.info(f"Document status for user {user_sub}: approved={approved_count}, rejected={rejected_count}, pending={pending_count}, required={len(required_docs)}")
        
        # Determine action based on document statuses
        
        # Case 1: At least one document rejected -> move to pending_review group
        if rejected_count > 0:
            logger.info(f"User {user_sub} has rejected documents, moving to pending_review")
            
            # Update Cognito attributes
            update_user_cognito_attributes(user_sub, {
                'verification_status': 'rejected'
            })
            
            # Update groups - remove from all groups and add to pending_review
            current_groups = get_user_cognito_groups(user_sub)
            for group in current_groups:
                if group != COGNITO_GROUPS['pending']:
                    remove_user_from_group(user_sub, group)
            
            if COGNITO_GROUPS['pending'] not in current_groups:
                add_user_to_group(user_sub, COGNITO_GROUPS['pending'])
            
            # =====================================================================
            # PUSH NOTIFICATION - Profile rejected
            # =====================================================================
            if FIREBASE_AVAILABLE:
                try:
                    user_profile = user_profiles_table.get_item(
                        Key={'user_id': user_sub}
                    ).get('Item')
                    
                    if user_profile and user_profile.get('fcm_token'):
                        fcm_token = user_profile['fcm_token']
                        notification_sent = send_profile_upgrade_notification(
                            fcm_token=fcm_token,
                            profile_type=profile_type,
                            verification_status='rejected'
                        )
                        if notification_sent:
                            logger.info(f"Profile rejection notification sent to user {user_sub}")
                        else:
                            logger.warning(f"Failed to send notification to user {user_sub}")
                    else:
                        logger.info(f"User {user_sub} has no FCM token registered")
                except Exception as notif_error:
                    logger.error(f"Push notification error (non-critical): {notif_error}")
            
            return {
                'action': 'rejected',
                'profile_type': profile_type,
                'verification_status': 'rejected',
                'group': COGNITO_GROUPS['pending'],
                'reason': f'{rejected_count} document(s) rejected'
            }
        
        # Case 2: All required documents approved -> promote to target group
        elif approved_count == len(required_docs):
            logger.info(f"User {user_sub} has all documents approved, promoting to {target_group}")
            
            # Update Cognito attributes
            update_user_cognito_attributes(user_sub, {
                'verification_status': 'approved'
            })
            
            # Update groups - remove from all groups and add to target group
            current_groups = get_user_cognito_groups(user_sub)
            for group in current_groups:
                if group != target_group:
                    remove_user_from_group(user_sub, group)
            
            if target_group not in current_groups:
                add_user_to_group(user_sub, target_group)
            
            # CRITICAL: Create company record in Companies table if promoting to company
            company_id = None
            if profile_type == 'company':
                logger.info(f"Creating company record for newly approved company user {user_sub}")
                company_id = create_company_record(user_sub)
                if company_id:
                    logger.info(f"Successfully created company record with ID {company_id}")
                else:
                    logger.error(f"Failed to create company record for user {user_sub}")
            
            # =====================================================================
            # PUSH NOTIFICATION - Profile approved
            # =====================================================================
            if FIREBASE_AVAILABLE:
                try:
                    user_profile = user_profiles_table.get_item(
                        Key={'user_id': user_sub}
                    ).get('Item')
                    
                    if user_profile and user_profile.get('fcm_token'):
                        fcm_token = user_profile['fcm_token']
                        notification_sent = send_profile_upgrade_notification(
                            fcm_token=fcm_token,
                            profile_type=profile_type,
                            verification_status='approved'
                        )
                        if notification_sent:
                            logger.info(f"Profile upgrade notification sent to user {user_sub}")
                        else:
                            logger.warning(f"Failed to send notification to user {user_sub}")
                    else:
                        logger.info(f"User {user_sub} has no FCM token registered")

                    # =====================================================================
                    # RETENTION KILL SWITCH — user completed upgrade via backoffice approval
                    # Cancel any pending T1/T2/T3 scheduler jobs (idempotent, best-effort)
                    # =====================================================================
                    if profile_type == 'company':
                        retention_state = (user_profile or {}).get('retention_state', {})
                        kill_retention_push(user_sub, retention_state)

                except Exception as notif_error:
                    logger.error(f"Push notification error (non-critical): {notif_error}")
            
            result = {
                'action': 'promoted',
                'profile_type': profile_type,
                'verification_status': 'approved',
                'group': target_group,
                'reason': 'All required documents approved'
            }
            
            # Add companyId to result if created
            if company_id:
                result['companyId'] = company_id
            
            return result
        
        # Case 3: Still pending documents
        else:
            logger.info(f"User {user_sub} still has pending documents, no action taken")
            
            # Make sure user is in pending_review group
            current_groups = get_user_cognito_groups(user_sub)
            if COGNITO_GROUPS['pending'] not in current_groups:
                # Remove from other groups
                for group in current_groups:
                    if group != COGNITO_GROUPS['pending']:
                        remove_user_from_group(user_sub, group)
                add_user_to_group(user_sub, COGNITO_GROUPS['pending'])
            
            return {
                'action': 'pending',
                'profile_type': profile_type,
                'verification_status': 'in_review',
                'group': COGNITO_GROUPS['pending'],
                'reason': f'{pending_count} document(s) still pending review'
            }
        
    except Exception as e:
        logger.error(f"Error checking user verification: {str(e)}")
        return {'action': 'error', 'reason': str(e)}

def verify_admin_access(event: Dict[str, Any]) -> tuple[bool, str, Dict[str, str]]:
    """Verifica che l'utente autenticato sia nel gruppo admins"""
    try:
        authorizer = event.get('requestContext', {}).get('authorizer', {})
        claims = authorizer.get('jwt', {}).get('claims', {}) or authorizer.get('claims', {})
        
        user_sub = claims.get('sub', 'unknown')
        user_email = claims.get('email', 'unknown')
        user_name = claims.get('name', claims.get('cognito:username', 'unknown'))
        
        groups = claims.get('cognito:groups', [])
        if isinstance(groups, str):
            groups = [groups]
        
        logger.info(f"User {user_email} (sub: {user_sub}) attempting access with groups: {groups}")
        
        if 'admins' not in groups:
            logger.warning(f"Access denied for user {user_email} - not in admins group")
            return False, "Access denied: admin privileges required", {}
        
        user_info = {
            'sub': user_sub,
            'email': user_email,
            'name': user_name,
            'groups': groups
        }
        
        logger.info(f"Admin access granted for user {user_email}")
        return True, "", user_info
        
    except Exception as e:
        logger.error(f"Error verifying admin access: {str(e)}")
        return False, f"Authorization error: {str(e)}", {}

def lambda_handler(event, context):
    try:
        # Handle CORS preflight
        if event.get('httpMethod') == 'OPTIONS':
            return _cors_response(200, {"message": "OK"})
        
        # ========================================
        # VERIFICA ACCESSO ADMIN
        # ========================================
        is_admin, error_msg, admin_info = verify_admin_access(event)
        if not is_admin:
            return _cors_response(403, {
                "error": "Forbidden",
                "message": error_msg,
                "code": 4332
            })
        
        logger.info(f"Document status update request: {json.dumps(event, default=str)}")
        logger.info(f"Admin {admin_info.get('email')} updating document status")
        
        # Extract path parameters
        path_params = event.get('pathParameters') or {}
        user_sub = path_params.get('user_sub')
        doc_id = path_params.get('doc_id')
        
        if not user_sub or not doc_id:
            return _cors_response(400, {
                'error': 'Bad Request',
                "message": "user_sub and doc_id are required",
                "code": 4333
            })
        
        # Parse request body
        if not event.get('body'):
            return _cors_response(400, {
                'error': 'Bad Request',
                "message": "Status update data must be provided",
                "code": 4334
            })
        
        try:
            body = json.loads(event['body'])
        except json.JSONDecodeError:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': "Invalid JSON in request body",
                'code': 4335
            })
        
        new_status = body.get('status')
        rejection_reason = body.get('rejectionReason', '').strip()
        
        if not new_status:
            return _cors_response(400, {
                'error': 'Bad Request',
                "message": "status field is required",
                "code": 4336
            })
        
        # Validate status
        if new_status not in VALID_STATUSES:
            return _cors_response(400, {
                'error': 'Bad Request',
                "message": f"Status must be one of: {list(VALID_STATUSES.keys())}",
                "code": 4337
            })
        
        # Validate rejection reason if status is REJECTED
        if new_status == 'REJECTED':
            if not rejection_reason:
                return _cors_response(400, {
                    'error': 'Bad Request',
                    "message": "rejectionReason is required when status is REJECTED",
                    "code": 4338
                })
            if len(rejection_reason) < 10:
                return _cors_response(400, {
                    'error': 'Bad Request',
                    "message": "rejectionReason must be at least 10 characters long",
                    "code": 4339
                })
        
        # Extract reviewer information
        reviewer_info = _extract_reviewer_info(event)
        
        # Get current document to verify it exists and is in correct status
        try:
            current_doc = get_current_document_status(user_sub, doc_id)
            current_status = current_doc.get('status')
            
            if current_status != REQUIRED_CURRENT_STATUS:
                return _cors_response(409, {
                    'error': 'Conflict',
                    "message": f"Document status is '{current_status}', but must be '{REQUIRED_CURRENT_STATUS}' to be updated",
                    "currentStatus": current_status,
                    "requiredStatus": REQUIRED_CURRENT_STATUS,
                    "code": 4340
                })
        except ValueError as e:
            return _cors_response(404, {
                'error': 'Not Found',
                "message": str(e),
                "code": 4341
            })
        
        # Update document status
        try:
            updated_doc = update_document_status(
                user_sub, doc_id, new_status, reviewer_info, rejection_reason
            )
        except ValueError as e:
            return _cors_response(409, {
                'error': 'Conflict',
                "message": str(e),
                "code": 4342
            })
        
        # Update S3 tags (best effort)
        s3_key = updated_doc.get('s3Key')
        if s3_key:
            update_s3_tags(s3_key, new_status, reviewer_info['reviewerEmail'])
        
        # Check if user verification is complete and update Cognito
        timestamp, doc_type = _parse_doc_id(doc_id)
        verification_result = check_and_update_user_verification(user_sub, doc_type)
        
        # Log audit trail
        logger.info(f"Document {doc_id} for user {user_sub} updated from {current_status} to {new_status} by {reviewer_info['reviewerEmail']}")
        logger.info(f"User verification check result: {verification_result}")
        
        # Build response
        response_data = {
            "success": True,
            "documentId": doc_id,
            "userSub": user_sub,
            "previousStatus": current_status,
            "newStatus": new_status,
            "reviewedBy": reviewer_info['reviewerEmail'],
            "reviewedAt": updated_doc.get('reviewedAt'),
            "message": f"Document status updated from {current_status} to {new_status}",
            "userVerification": verification_result,
            "code": 3090
        }
        
        # Add rejection reason to response if applicable
        if new_status == 'REJECTED' and rejection_reason:
            response_data["rejectionReason"] = rejection_reason
        
        return _cors_response(200, response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in status update handler: {str(e)}")
        return _cors_response(500, {
            'error': 'Internal Server Error',
            "message": str(e),
            "code": 5096
        })