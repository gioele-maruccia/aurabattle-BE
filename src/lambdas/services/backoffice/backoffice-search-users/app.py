import json
import os
import boto3
import logging
from typing import Dict, List, Any, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ["REGION"]
COGNITO_USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]

cognito = boto3.client('cognito-idp', region_name=REGION)

def _cors_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Standardized CORS response format"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,OPTIONS"
        },
        "body": json.dumps(body)
    }

def _get_query_params(event: Dict[str, Any]) -> Dict[str, str]:
    """Extract query parameters from event"""
    return event.get('queryStringParameters') or {}

def _get_user_groups(username: str) -> List[str]:
    """Get Cognito groups for a user"""
    try:
        response = cognito.admin_list_groups_for_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=username
        )
        return [group['GroupName'] for group in response.get('Groups', [])]
    except Exception as e:
        logger.warning(f"Could not fetch groups for user {username}: {str(e)}")
        return []

def _format_user_profile(user: Dict[str, Any]) -> Dict[str, Any]:
    """Format Cognito user data for API response using updated attributes"""
    attributes = {attr['Name']: attr['Value'] for attr in user.get('Attributes', [])}
    
    # Extract standard attributes
    sub = user.get('Username', '')  # This is the user's sub/ID
    given_name = attributes.get('given_name', '')
    family_name = attributes.get('family_name', '')
    name = attributes.get('name', '')
    
    # Fallback parsing if given_name/family_name not available
    if not given_name and not family_name and name:
        name_parts = name.split(' ', 1)
        given_name = name_parts[0] if len(name_parts) > 0 else ''
        family_name = name_parts[1] if len(name_parts) > 1 else ''
    
    # Build full name
    full_name = f"{given_name} {family_name}".strip()
    if not full_name and name:
        full_name = name
    
    # Get user groups from Cognito
    groups = _get_user_groups(sub)
    
    # Determine profileType from groups (prioritized)
    # admins > workers/companies > basic_users
    profile_type = attributes.get('custom:profile_type', 'basic')
    if 'admins' in groups:
        profile_type = 'admin'
    elif 'beezey_admin' in groups:
        profile_type = 'admin'
    elif 'beezey_staff' in groups:
        profile_type = 'staff'
    elif 'workers' in groups:
        profile_type = 'worker'
    elif 'companies' in groups:
        profile_type = 'company'
    elif 'pending_review' in groups:
        profile_type = 'pending_review'
    elif 'basic_users' in groups:
        profile_type = 'basic'
    
    return {
        "sub": sub,
        "userSub": sub,  # Same as sub for consistency
        "firstName": given_name,
        "lastName": family_name,
        "fullName": full_name,
        "email": attributes.get('email', ''),
        "profileType": profile_type,
        "groups": groups,  # Add groups to response
        "userStatus": user.get('UserStatus', ''),
        "enabled": user.get('Enabled', False),
        "registeredAt": user.get('UserCreateDate', '').isoformat() if user.get('UserCreateDate') else '',
        "lastModified": user.get('UserLastModifiedDate', '').isoformat() if user.get('UserLastModifiedDate') else ''
    }

def search_users_by_email(email_query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search users by email in Cognito"""
    try:
        response = cognito.list_users(
            UserPoolId=COGNITO_USER_POOL_ID,
            Filter=f'email ^= "{email_query}"',
            Limit=limit
        )
        
        users = []
        for user in response.get('Users', []):
            users.append(_format_user_profile(user))
        
        return users
        
    except Exception as e:
        logger.error(f"Error searching users by email {email_query}: {str(e)}")
        raise

def search_users_by_name(name_query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search users by name in Cognito"""
    try:
        # Search by given_name first
        try:
            response = cognito.list_users(
                UserPoolId=COGNITO_USER_POOL_ID,
                Filter=f'given_name ^= "{name_query}"',
                Limit=limit
            )
            
            users_by_first_name = []
            for user in response.get('Users', []):
                users_by_first_name.append(_format_user_profile(user))
        except:
            users_by_first_name = []
        
        # Search by family_name if we haven't reached the limit
        users_by_last_name = []
        if len(users_by_first_name) < limit:
            try:
                response = cognito.list_users(
                    UserPoolId=COGNITO_USER_POOL_ID,
                    Filter=f'family_name ^= "{name_query}"',
                    Limit=limit - len(users_by_first_name)
                )
                
                for user in response.get('Users', []):
                    user_profile = _format_user_profile(user)
                    # Avoid duplicates
                    if not any(u['sub'] == user_profile['sub'] for u in users_by_first_name):
                        users_by_last_name.append(user_profile)
            except:
                pass
        
        # If still not enough results, fallback to client-side filtering
        all_users = users_by_first_name + users_by_last_name
        if len(all_users) < limit:
            try:
                response = cognito.list_users(
                    UserPoolId=COGNITO_USER_POOL_ID,
                    Limit=60  # Get more to filter
                )
                
                name_query_lower = name_query.lower()
                existing_subs = {u['sub'] for u in all_users}
                
                for user in response.get('Users', []):
                    if len(all_users) >= limit:
                        break
                        
                    formatted_user = _format_user_profile(user)
                    
                    # Skip if already included
                    if formatted_user['sub'] in existing_subs:
                        continue
                    
                    full_name = formatted_user['fullName'].lower()
                    first_name = formatted_user['firstName'].lower()
                    last_name = formatted_user['lastName'].lower()
                    
                    if (name_query_lower in full_name or 
                        name_query_lower in first_name or 
                        name_query_lower in last_name):
                        all_users.append(formatted_user)
                        existing_subs.add(formatted_user['sub'])
            except:
                pass
        
        return all_users[:limit]
        
    except Exception as e:
        logger.error(f"Error searching users by name {name_query}: {str(e)}")
        raise

def search_users_by_status(status: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search users by status in Cognito"""
    try:
        response = cognito.list_users(
            UserPoolId=COGNITO_USER_POOL_ID,
            Filter=f'status = "{status}"',
            Limit=limit
        )
        
        users = []
        for user in response.get('Users', []):
            users.append(_format_user_profile(user))
        
        return users
        
    except Exception as e:
        logger.error(f"Error searching users by status {status}: {str(e)}")
        raise

def search_users_by_user_type(user_type: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search users by user type (custom attribute) in Cognito"""
    try:
        response = cognito.list_users(
            UserPoolId=COGNITO_USER_POOL_ID,
            Filter=f'custom:profile_type = "{user_type}"',
            Limit=limit
        )
        
        users = []
        for user in response.get('Users', []):
            users.append(_format_user_profile(user))
        
        return users
        
    except Exception as e:
        logger.error(f"Error searching users by user type {user_type}: {str(e)}")
        raise

def list_recent_users(limit: int = 20) -> List[Dict[str, Any]]:
    """List most recently registered users"""
    try:
        response = cognito.list_users(
            UserPoolId=COGNITO_USER_POOL_ID,
            Limit=limit
        )
        
        users = []
        for user in response.get('Users', []):
            users.append(_format_user_profile(user))
        
        # Sort by creation date descending
        users.sort(key=lambda x: x['registeredAt'], reverse=True)
        
        return users
        
    except Exception as e:
        logger.error(f"Error listing recent users: {str(e)}")
        raise

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
                "message": error_msg
            })
        
        logger.info(f"Event: {json.dumps(event)}")
        logger.info(f"Admin {admin_info.get('email')} searching users")
        
        # Extract query parameters
        query_params = _get_query_params(event)
        search_type = query_params.get('type', 'email')  # Default to email search
        query = query_params.get('q', '').strip()
        limit = min(int(query_params.get('limit', 20)), 60)  # Max 60 for Cognito
        
        users = []
        
        if not query and search_type not in ['recent', 'status', 'user_type']:
            return _cors_response(400, {
                "error": "Missing search query",
                "message": "Query parameter 'q' is required unless type is 'recent'"
            })
        
        if search_type == 'email':
            if len(query) < 3:
                return _cors_response(400, {
                    "error": "Query too short",
                    "message": "Email search requires at least 3 characters"
                })
            users = search_users_by_email(query, limit)
            
        elif search_type == 'name':
            if len(query) < 2:
                return _cors_response(400, {
                    "error": "Query too short", 
                    "message": "Name search requires at least 2 characters"
                })
            users = search_users_by_name(query, limit)
            
        elif search_type == 'status':
            if not query:
                return _cors_response(400, {
                    "error": "Missing status",
                    "message": "Status query is required (e.g., CONFIRMED, UNCONFIRMED, ARCHIVED)"
                })
            users = search_users_by_status(query, limit)
            
        elif search_type == 'user_type':
            if not query:
                return _cors_response(400, {
                    "error": "Missing user type",
                    "message": "User type query is required (e.g., guest, premium, admin)"
                })
            users = search_users_by_user_type(query, limit)
            
        elif search_type == 'recent':
            users = list_recent_users(limit)
            
        else:
            return _cors_response(400, {
                "error": "Invalid search type",
                "message": "Type must be one of: email, name, status, user_type, recent"
            })
        
        return _cors_response(200, {
            "users": users,
            "count": len(users),
            "searchType": search_type,
            "query": query if query else None
        })
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"Cognito error: {error_code} - {str(e)}")
        return _cors_response(500, {
            "error": "Search service error",
            "message": f"Unable to search users: {error_code}"
        })
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return _cors_response(400, {"error": "Invalid request", "message": str(e)})
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return _cors_response(500, {"error": "Internal server error", "message": str(e)})