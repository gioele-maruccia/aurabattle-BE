"""
Get User Profile Handler

Returns the authenticated user's profile from UserProfiles.
"""

import json
import os
import boto3
import logging
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
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
    """
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']

        response = table.get_item(Key={'user_id': user_id})

        if 'Item' not in response:
            return _cors_response(404, {'error': 'Profile not found'})

        profile = response['Item']
        profile = _enrich_profile_from_cognito(profile, user_id)

        return _cors_response(200, profile)

    except Exception as e:
        logger.error(f"Error in get-profile: {e}", exc_info=True)
        return _cors_response(500, {'error': str(e)})
