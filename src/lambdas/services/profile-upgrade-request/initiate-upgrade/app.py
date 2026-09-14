"""
Lambda Function: Initiate User Upgrade
Triggherata dall'app Flutter quando l'utente carica documenti per upgrade.

AZIONI:
1. Valida input (username, upgrade_type)
2. Aggiorna Cognito attributes:
   - custom:profile_type = "worker" | "company"
   - custom:verification_status = "in_review"
   - custom:upgrade_requested_at = timestamp ISO
3. Gestisce gruppi Cognito:
   - Rimuove da: basic_users, workers, companies
   - Aggiunge a: pending_review

STATI verification_status:
- in_review: Documenti caricati, in revisione (impostato qui)
- approved: Documenti approvati (impostato da Lambda backoffice)
- rejected: Documenti rifiutati (impostato da Lambda backoffice)
"""

import json
import boto3
import os
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Inizializza client Cognito e DynamoDB
cognito = boto3.client('cognito-idp')
dynamodb = boto3.resource('dynamodb')

# Environment variables
USER_POOL_ID = os.environ.get('USER_POOL_ID')
USER_PROFILES_TABLE = os.environ.get('USER_PROFILES_TABLE')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')

# Inizializza tabella DynamoDB
table = dynamodb.Table(USER_PROFILES_TABLE)

# Costanti
VALID_UPGRADE_TYPES = ['worker', 'company']
GROUPS_TO_REMOVE = ['basic_users', 'workers', 'companies']
TARGET_GROUP = 'pending_review'


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principale Lambda.
    
    INPUT (body JSON):
    {
      "username": "user-sub-uuid",
      "upgrade_type": "worker" | "company"
    }
    
    OUTPUT SUCCESS (200):
    {
      "success": true,
      "message": "Upgrade process initiated",
      "username": "user-sub-uuid",
      "profile_type": "worker",
      "verification_status": "in_review",
      "group": "pending_review",
      "timestamp": "2025-10-01T10:30:00.123456"
    }
    
    OUTPUT ERROR (400/404/500):
    {
      "error": "Error description"
    }
    """
    
    logger.info(f"Event received: {json.dumps(event, default=str)}")
    
    try:
        # Handle CORS preflight
        if event.get('httpMethod') == 'OPTIONS':
            return build_response(200, {"message": "OK"})
        
        # Parse request body
        body = parse_body(event)
        
        # Extract and validate parameters
        username = body.get('username')
        upgrade_type = body.get('upgrade_type')
        
        validation_error = validate_parameters(username, upgrade_type)
        if validation_error:
            return validation_error
        
        # Check user exists in Cognito
        if not user_exists(username):
            return build_response(404, {
                "error": f"User not found: {username}"
            })
        
        # Get current timestamp
        timestamp = datetime.utcnow().isoformat()
        
        # Step 1: Update Cognito user attributes
        update_cognito_attributes(
            username=username,
            profile_type=upgrade_type,
            timestamp=timestamp
        )
        
        # Step 2: Update Cognito user groups
        update_cognito_groups(username)
        
        # Step 3: Update DynamoDB UserProfiles
        user_sub = get_user_sub(username)
        update_dynamodb_profile_type(
            user_sub=user_sub,
            profile_type=upgrade_type,
            timestamp=timestamp
        )
        
        # Build success response
        response_data = {
            'success': True,
            'message': 'Upgrade process initiated',
            'username': username,
            'profile_type': upgrade_type,
            'verification_status': 'in_review',
            'group': TARGET_GROUP,
            'timestamp': timestamp
        }
        
        logger.info(f"SUCCESS: Upgrade initiated for {username} as {upgrade_type}")
        
        return build_response(200, response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return build_response(500, {
            "error": "Internal server error",
            "message": str(e)
        })


def parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse request body from API Gateway or direct invocation."""
    try:
        if 'body' in event:
            if isinstance(event['body'], str):
                return json.loads(event['body'])
            return event['body']
        return event
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {str(e)}")
        raise ValueError("Invalid JSON in request body")


def validate_parameters(username: Optional[str], upgrade_type: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Validate input parameters.
    Returns None if valid, error response otherwise.
    """
    if not username:
        return build_response(400, {"error": "username is required"})
    
    if not upgrade_type:
        return build_response(400, {"error": "upgrade_type is required"})
    
    if upgrade_type not in VALID_UPGRADE_TYPES:
        return build_response(400, {
            "error": f"upgrade_type must be one of: {', '.join(VALID_UPGRADE_TYPES)}"
        })
    
    return None


def user_exists(username: str) -> bool:
    """Check if user exists in Cognito User Pool."""
    try:
        cognito.admin_get_user(
            UserPoolId=USER_POOL_ID,
            Username=username
        )
        logger.info(f"User found: {username}")
        return True
    except cognito.exceptions.UserNotFoundException:
        logger.warning(f"User not found: {username}")
        return False
    except Exception as e:
        logger.error(f"Error checking user: {str(e)}")
        raise


def get_user_sub(username: str) -> str:
    """Get user's sub (UUID) from Cognito."""
    try:
        response = cognito.admin_get_user(
            UserPoolId=USER_POOL_ID,
            Username=username
        )
        
        # Extract sub from UserAttributes
        for attr in response.get('UserAttributes', []):
            if attr['Name'] == 'sub':
                return attr['Value']
        
        raise ValueError(f"Sub not found for user: {username}")
        
    except Exception as e:
        logger.error(f"Error getting user sub: {str(e)}\")")
        raise


def update_cognito_attributes(username: str, profile_type: str, timestamp: str) -> None:
    """
    Update user custom attributes in Cognito:
    - custom:profile_type
    - custom:verification_status
    - custom:upgrade_requested_at
    """
    try:
        attributes = [
            {
                'Name': 'custom:profile_type',
                'Value': profile_type
            },
            {
                'Name': 'custom:verification_status',
                'Value': 'in_review'
            },
            {
                'Name': 'custom:upgrade_requested_at',
                'Value': timestamp
            }
        ]
        
        cognito.admin_update_user_attributes(
            UserPoolId=USER_POOL_ID,
            Username=username,
            UserAttributes=attributes
        )
        
        logger.info(
            f"Updated attributes: username={username}, "
            f"profile_type={profile_type}, status=in_review"
        )
        
    except Exception as e:
        logger.error(f"Error updating attributes: {str(e)}")
        raise


def update_dynamodb_profile_type(user_sub: str, profile_type: str, timestamp: str) -> None:
    """
    Update profile_type in DynamoDB UserProfiles table.
    This ensures the profile_type is synced between Cognito and DynamoDB.
    """
    try:
        table.update_item(
            Key={'user_id': user_sub},
            UpdateExpression='SET profile_type = :pt, updated_at = :ts, profile_type_changed_at = :ts',
            ExpressionAttributeValues={
                ':pt': profile_type,
                ':ts': timestamp
            }
        )
        
        logger.info(
            f"Updated DynamoDB: user_id={user_sub}, profile_type={profile_type}"
        )
        
    except Exception as e:
        logger.error(f"Error updating DynamoDB: {str(e)}")
        raise


def update_cognito_groups(username: str) -> None:
    """
    Update user Cognito groups:
    - Remove from: basic_users, workers, companies
    - Add to: pending_review
    """
    try:
        # Get current groups
        current_groups = get_user_groups(username)
        logger.info(f"Current groups: {current_groups}")
        
        # Remove from previous groups
        for group in GROUPS_TO_REMOVE:
            if group in current_groups:
                remove_from_group(username, group)
        
        # Add to target group
        if TARGET_GROUP not in current_groups:
            add_to_group(username, TARGET_GROUP)
        else:
            logger.info(f"User already in {TARGET_GROUP}")
            
    except Exception as e:
        logger.error(f"Error updating groups: {str(e)}")
        raise


def get_user_groups(username: str) -> List[str]:
    """Get list of groups user belongs to."""
    try:
        response = cognito.admin_list_groups_for_user(
            UserPoolId=USER_POOL_ID,
            Username=username
        )
        return [group['GroupName'] for group in response.get('Groups', [])]
    except Exception as e:
        logger.error(f"Error getting groups: {str(e)}")
        return []


def add_to_group(username: str, group_name: str) -> None:
    """Add user to Cognito group."""
    try:
        cognito.admin_add_user_to_group(
            UserPoolId=USER_POOL_ID,
            Username=username,
            GroupName=group_name
        )
        logger.info(f"Added {username} to group {group_name}")
    except Exception as e:
        logger.error(f"Error adding to group {group_name}: {str(e)}")
        raise


def remove_from_group(username: str, group_name: str) -> None:
    """Remove user from Cognito group."""
    try:
        cognito.admin_remove_user_from_group(
            UserPoolId=USER_POOL_ID,
            Username=username,
            GroupName=group_name
        )
        logger.info(f"Removed {username} from group {group_name}")
    except Exception as e:
        # Don't raise - user might not be in group
        logger.warning(f"Error removing from group {group_name}: {str(e)}")


def build_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Build HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'POST,OPTIONS'
        },
        'body': json.dumps(body, default=str)
    }