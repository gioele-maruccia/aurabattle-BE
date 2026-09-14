"""
Get Company Profile Handler

This Lambda function retrieves a company profile by userId with presigned URLs.
"""

import json
import os
import boto3
from decimal import Decimal
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = os.environ.get("REGION", "eu-south-1")

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"}
    ),
)
cognito_client = boto3.client('cognito-idp', region_name=REGION)
table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])
bucket_name = os.environ.get('COMPANIES_BUCKET_NAME', 'seasonal-jobs-companies-assets')
profile_photos_bucket = os.environ.get('PROFILE_PHOTOS_BUCKET', 'prod-beezey-profiles')
user_pool_id = os.environ.get('USER_POOL_ID', '')


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def generate_presigned_download_url(key):
    """
    Generate presigned URL for downloading an image
    
    Args:
        key (str): S3 object key
        
    Returns:
        str: Presigned URL for download (valid for 1 hour)
    """
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket_name,
                'Key': key
            },
            ExpiresIn=3600  # URL valid for 1 hour
        )
        return url
    except Exception as e:
        print(f"Error generating presigned URL for {key}: {str(e)}")
        return None


def add_presigned_urls_to_company(company):
    """
    Add presigned download URLs to company media
    
    Args:
        company (dict): Company data from DynamoDB
        
    Returns:
        dict: Company with presigned URLs
    """
    if 'media' not in company:
        return company
    
    media = company['media']
    
    # Generate presigned URL for profile image
    if 'profileImageUrl' in media and media['profileImageUrl']:
        # Extract key from URL
        profile_key = f"companies/{company['companyId']}/profile.jpg"
        presigned_url = generate_presigned_download_url(profile_key)
        if presigned_url:
            media['profileImageUrl'] = presigned_url
    
    # Generate presigned URLs for gallery images
    if 'galleryImages' in media and media['galleryImages']:
        presigned_gallery = []
        for img_url in media['galleryImages']:
            # Solo se l'URL esiste, genera il presigned URL
            if img_url:
                # Estrai la chiave dall'URL esistente invece di ricostruirla
                # L'URL salvato è già il path corretto in S3
                try:
                    # Estrai il path dopo il bucket name dall'URL
                    # Es: https://bucket.s3.region.amazonaws.com/companies/uuid/gallery/1.jpg
                    # -> companies/uuid/gallery/1.jpg
                    key = img_url.split('.amazonaws.com/')[-1].split('?')[0]
                    presigned_url = generate_presigned_download_url(key)
                    if presigned_url:
                        presigned_gallery.append(presigned_url)
                except Exception as e:
                    print(f"Error extracting key from URL {img_url}: {str(e)}")
                    # Se fallisce l'estrazione, mantieni l'URL originale
                    presigned_gallery.append(img_url)
        
        media['galleryImages'] = presigned_gallery
    
    return company


def get_user_profile_from_cognito(user_id):
    """
    Get user profile information from Cognito
    
    Args:
        user_id (str): Cognito user ID (sub)
        
    Returns:
        dict: User profile information or None if not found
    """
    if not user_pool_id:
        print("Warning: USER_POOL_ID not set, skipping user profile fetch")
        return None
        
    try:
        response = cognito_client.admin_get_user(
            UserPoolId=user_pool_id,
            Username=user_id
        )
        
        # Extract attributes
        attributes = {attr['Name']: attr['Value'] for attr in response.get('UserAttributes', [])}
        
        # Generate presigned URL for representative profile photo
        photo_url = None
        try:
            photo_key = f"profiles/{user_id}/avatar.jpg"
            photo_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': profile_photos_bucket, 'Key': photo_key},
                ExpiresIn=3600
            )
        except Exception as photo_err:
            print(f"Could not generate photo URL for {user_id}: {str(photo_err)}")

        return {
            "sub": attributes.get('sub', user_id),
            "firstName": attributes.get('given_name', ''),
            "lastName": attributes.get('family_name', ''),
            "email": attributes.get('email', ''),
            "birthdate": attributes.get('birthdate', ''),
            "userStatus": response.get('UserStatus', ''),
            "enabled": response.get('Enabled', False),
            "photoUrl": photo_url
        }
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'UserNotFoundException':
            print(f"User not found in Cognito: {user_id}")
        else:
            print(f"Error getting user from Cognito {user_id}: {str(e)}")
        
        return None
    except Exception as e:
        print(f"Unexpected error getting user profile: {str(e)}")
        return None


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    GET /companies/{userId}
    Retrieve company profile by userId
    
    Returns:
        200: Company found
        404: Company not found
        500: Internal server error
    """
    try:
        # Get userId from path parameters
        user_id = event['pathParameters']['userId']
        
        print(f"Getting company for user: {user_id}")
        
        # Get company from DynamoDB
        response = table.get_item(Key={'userId': user_id})
        
        if 'Item' not in response:
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Not Found',
                    'message': 'Company profile not found'
                })
            }
        
        company = response['Item']
        
        # Add presigned URLs for image downloads
        company = add_presigned_urls_to_company(company)
        
        # Fetch representative (user) information from Cognito
        representative = get_user_profile_from_cognito(user_id)
        if representative:
            company['representative'] = representative
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(company, cls=DecimalEncoder)
        }
        
    except Exception as e:
        print(f"Error getting company: {str(e)}")
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
                'message': 'An unexpected error occurred'
            })
        }