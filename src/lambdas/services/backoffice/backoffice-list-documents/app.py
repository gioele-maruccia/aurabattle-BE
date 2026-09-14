import json
import os
import boto3
import logging
from typing import Dict, List, Any, Optional
from boto3.dynamodb.conditions import Key, Attr
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ["BUCKET_NAME"]
REGION = os.environ["REGION"]
COGNITO_USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]

dynamodb = boto3.resource('dynamodb', region_name=REGION)
cognito = boto3.client('cognito-idp', region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

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

def get_user_profile_from_cognito(user_sub: str) -> Dict[str, Any]:
    """Get user profile information from Cognito User Pool"""
    try:
        response = cognito.admin_get_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=user_sub
        )
        
        # Extract user attributes
        attributes = {attr['Name']: attr['Value'] for attr in response.get('UserAttributes', [])}
        
        # Extract specific attributes as per your requirements
        given_name = attributes.get('given_name', '')
        family_name = attributes.get('family_name', '')
        email = attributes.get('email', '')
        birthdate = attributes.get('birthdate', '')
        user_type = attributes.get('custom:profile_type', 'basic')
        sub = attributes.get('sub', user_sub)  # Fallback to username if sub not available
        
        return {
            "sub": sub,
            "firstName": given_name,
            "lastName": family_name,
            "email": email,
            "birthdate": birthdate,
            "profileType": user_type,
            "userStatus": response.get('UserStatus', ''),
            "enabled": response.get('Enabled', False),
            "userCreateDate": response.get('UserCreateDate', '').isoformat() if response.get('UserCreateDate') else '',
            "userLastModifiedDate": response.get('UserLastModifiedDate', '').isoformat() if response.get('UserLastModifiedDate') else ''
        }
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'UserNotFoundException':
            logger.warning(f"User not found in Cognito: {user_sub}")
        else:
            logger.error(f"Error getting user from Cognito {user_sub}: {str(e)}")
        
        return {
            "sub": user_sub,
            "firstName": "Unknown",
            "lastName": "User",
            "email": "unknown@unknown.com",
            "birthdate": "",
            "profileType": "basic",
            "userStatus": "UNKNOWN",
            "enabled": False,
            "userCreateDate": "",
            "userLastModifiedDate": ""
        }
    except Exception as e:
        logger.error(f"Unexpected error getting user profile for {user_sub}: {str(e)}")
        return {
            "sub": user_sub,
            "firstName": "Error",
            "lastName": "Loading",
            "email": "error@error.com",
            "birthdate": "",
            "userType": "",
            "userStatus": "ERROR",
            "enabled": False,
            "userCreateDate": "",
            "userLastModifiedDate": ""
        }

def get_multiple_user_profiles_from_cognito(user_subs: List[str]) -> Dict[str, Dict[str, Any]]:
    """Get multiple user profiles from Cognito efficiently using ThreadPoolExecutor"""
    profiles = {}
    
    # Limit concurrent requests to avoid throttling
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_user_sub = {
            executor.submit(get_user_profile_from_cognito, user_sub): user_sub 
            for user_sub in user_subs
        }
        
        for future in as_completed(future_to_user_sub):
            user_sub = future_to_user_sub[future]
            try:
                profiles[user_sub] = future.result()
            except Exception as e:
                logger.error(f"Error getting profile for {user_sub}: {str(e)}")
                # Fallback profile
                profiles[user_sub] = {
                    "sub": user_sub,
                    "firstName": "Error",
                    "lastName": "Loading",
                    "email": "error@error.com",
                    "birthdate": "",
                    "userType": "",
                    "userStatus": "ERROR",
                    "enabled": False,
                    "userCreateDate": "",
                    "userLastModifiedDate": ""
                }
    
    return profiles

def _format_document_item(item: Dict[str, Any], user_profile: Dict[str, Any] = None) -> Dict[str, Any]:
    """Convert DynamoDB item to API response format with user data"""
    # Extract user_sub and doc info from PK/SK
    pk = item.get('pk', '')
    sk = item.get('sk', '')
    
    user_sub = pk.replace('USER#', '') if pk.startswith('USER#') else ''
    
    # SK format: DOC#{doc_type}#{timestamp}
    sk_parts = sk.replace('DOC#', '').split('#')
    doc_type = sk_parts[0] if len(sk_parts) > 0 else ''
    timestamp = sk_parts[1] if len(sk_parts) > 1 else ''
    
    # Base document data
    document_data = {
        "documentId": f"{timestamp}_{doc_type}",
        "userSub": user_sub,
        "docType": doc_type,
        "timestamp": int(timestamp) if timestamp.isdigit() else 0,
        "status": item.get('status', ''),
        "mime": item.get('mime', ''),
        "size": int(item.get('size', 0)) if str(item.get('size', 0)).isdigit() else 0,
        "uploadedAt": item.get('uploadedAt', ''),
        "s3Key": item.get('s3Key', ''),
        "reason": item.get('reason', None),
        "reviewedAt": item.get('reviewedAt', None),
        "reviewedBy": item.get('reviewedBy', None)
    }
    
    # Add user profile data
    if user_profile:
        full_name = f"{user_profile.get('firstName', '')} {user_profile.get('lastName', '')}".strip()
        document_data["user"] = {
            "sub": user_profile.get('sub', user_sub),
            "userSub": user_sub,  # Keep for backward compatibility
            "firstName": user_profile.get('firstName', ''),
            "lastName": user_profile.get('lastName', ''),
            "fullName": full_name or "Unknown User",
            "email": user_profile.get('email', ''),
            "birthdate": user_profile.get('birthdate', ''),
            "userType": user_profile.get('userType', ''),
            "userStatus": user_profile.get('userStatus', ''),
            "enabled": user_profile.get('enabled', False),
            "registeredAt": user_profile.get('userCreateDate', ''),
            "lastModified": user_profile.get('userLastModifiedDate', '')
        }
    else:
        # Fallback if no profile available
        document_data["user"] = {
            "sub": user_sub,
            "userSub": user_sub,
            "firstName": "Unknown",
            "lastName": "User",
            "fullName": "Unknown User",
            "email": "unknown@unknown.com",
            "birthdate": "",
            "userType": "",
            "userStatus": "UNKNOWN",
            "enabled": False,
            "registeredAt": "",
            "lastModified": ""
        }
    
    return document_data

def _get_query_params(event: Dict[str, Any]) -> Dict[str, str]:
    """Extract query parameters from event"""
    return event.get('queryStringParameters') or {}

def list_all_documents(status_filter: Optional[str] = None, user_type_filter: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List all documents with optional status and user type filters"""
    try:
        scan_kwargs = {
            'Limit': limit
        }
        
        if status_filter:
            scan_kwargs['FilterExpression'] = Attr('status').eq(status_filter)
        
        response = table.scan(**scan_kwargs)
        
        documents = []
        user_subs = set()
                
        for item in response.get('Items', []):
            if item.get('pk', '').startswith('USER#') and item.get('sk', '').startswith('DOC#'):
                documents.append(item)
                user_sub = item.get('pk', '').replace('USER#', '')
                user_subs.add(user_sub)
        
        
        # Get all user profiles from Cognito in batch
        user_profiles = get_multiple_user_profiles_from_cognito(list(user_subs))
        
        # Format documents with user data and apply user type filter if needed
        formatted_documents = []
        for item in documents:
            user_sub = item.get('pk', '').replace('USER#', '')
            user_profile = user_profiles.get(user_sub)
            
            # Apply user type filter if specified
            if user_type_filter and user_profile:
                if user_profile.get('userType', '').lower() != user_type_filter.lower():
                    continue
            
            formatted_documents.append(_format_document_item(item, user_profile))
        
        # Sort by timestamp descending (newest first)
        formatted_documents.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return formatted_documents
        
    except Exception as e:
        logger.error(f"Error listing all documents: {str(e)}")
        raise

def list_user_documents(user_sub: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """List documents for a specific user"""
    try:
        pk = f"USER#{user_sub}"
        
        query_kwargs = {
            'KeyConditionExpression': Key('pk').eq(pk) & Key('sk').begins_with('DOC#')
        }
        
        if status_filter:
            query_kwargs['FilterExpression'] = Attr('status').eq(status_filter)
        
        response = table.query(**query_kwargs)
        
        # Get user profile from Cognito once
        user_profile = get_user_profile_from_cognito(user_sub)
        
        documents = []
        for item in response.get('Items', []):
            documents.append(_format_document_item(item, user_profile))
        
        # Sort by timestamp descending (newest first)
        documents.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return documents
        
    except Exception as e:
        logger.error(f"Error listing documents for user {user_sub}: {str(e)}")
        raise

def verify_admin_access(event: Dict[str, Any]) -> tuple[bool, str, Dict[str, str]]:
    """Verifica che l'utente autenticato sia nel gruppo admins"""
    try:
        authorizer = event.get('requestContext', {}).get('authorizer', {})
        claims = authorizer.get('jwt', {}).get('claims', {}) or authorizer.get('claims', {})
        
        user_sub = claims.get('sub', 'unknown')
        user_email = claims.get('email', 'unknown')
        user_name = claims.get('name', claims.get('cognito:username', 'unknown'))
        
        # Cognito mette i gruppi in "cognito:groups" come lista
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
        
        logger.info(f"Admin {admin_info.get('email')} accessing list-documents")
        
        logger.info(f"Event: {json.dumps(event)}")
        
        # Extract path parameters
        path_params = event.get('pathParameters') or {}
        user_sub = path_params.get('user_sub')
        
        # Extract query parameters
        query_params = _get_query_params(event)
        status_filter = query_params.get('status')
        user_type_filter = query_params.get('userType')  # New filter for user type
        limit = int(query_params.get('limit', 50))
        
        # Validate limit
        if limit > 100:
            limit = 100
        
        if user_sub:
            # List documents for specific user
            documents = list_user_documents(user_sub, status_filter)
            
            # Get user profile for response metadata
            user_profile = documents[0]['user'] if documents else get_user_profile_from_cognito(user_sub)
            
            return _cors_response(200, {
                "userSub": user_sub,
                "userInfo": {
                    "sub": user_profile.get('sub', user_sub),
                    "fullName": user_profile.get('fullName', 'Unknown User'),
                    "email": user_profile.get('email', ''),
                    "profileType": user_profile.get('profileType', 'basic'),
                    "userStatus": user_profile.get('userStatus', '')
                },
                "documents": documents,
                "count": len(documents)
            })
        else:
            # List all documents
            documents = list_all_documents(status_filter, user_type_filter, limit)
            return _cors_response(200, {
                "documents": documents,
                "count": len(documents),
                "filters": {
                    "status": status_filter,
                    "profileType": user_type_filter,
                    "limit": limit
                }
            })
            
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return _cors_response(400, {"error": "Invalid request", "message": str(e)})
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return _cors_response(500, {"error": "Internal server error", "message": str(e)})