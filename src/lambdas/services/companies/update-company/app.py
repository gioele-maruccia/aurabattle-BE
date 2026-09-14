"""
Update Company Profile Handler - Enhanced with Image Deletion

This Lambda function updates a company profile in DynamoDB with description,
location, and manages images (upload new + delete existing).
"""

import json
import os
import boto3
from datetime import datetime
from decimal import Decimal
from botocore.config import Config

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
table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])
bucket_name = os.environ.get('COMPANIES_BUCKET_NAME', 'seasonal-jobs-companies-assets')


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def validate_update_data(data):
    """
    Validate fields for company update
    
    Args:
        data (dict): Company data from request body
        
    Returns:
        tuple: (is_valid, error_message)
    """
    # Validate description length if provided
    if 'description' in data and data['description']:
        if len(data['description']) > 2000:
            return False, "description must not exceed 2000 characters"
    
    # Validate location structure if provided
    if 'location' in data:
        location = data['location']
        # If location is provided, both city and country are required
        if 'city' not in location or not location['city']:
            return False, "location.city is required when location is provided"
        if 'country' not in location or not location['country']:
            return False, "location.country is required when location is provided"
        
        # Validate coordinates if provided
        if 'coordinates' in location:
            coords = location['coordinates']
            if 'lat' in coords:
                lat = coords['lat']
                if not isinstance(lat, (int, float)) or lat < -90 or lat > 90:
                    return False, "latitude must be between -90 and 90"
            if 'lon' in coords:
                lon = coords['lon']
                if not isinstance(lon, (int, float)) or lon < -180 or lon > 180:
                    return False, "longitude must be between -180 and 180"
    
    # Validate image requests
    if 'requestProfileImage' in data and data['requestProfileImage'] not in [True, False]:
        return False, "requestProfileImage must be boolean"
    
    if 'requestGalleryImages' in data:
        gallery_count = data['requestGalleryImages']
        if not isinstance(gallery_count, int) or gallery_count < 0 or gallery_count > 5:
            return False, "requestGalleryImages must be an integer between 0 and 5"
    
    # Validate image removal requests
    if 'removeProfileImage' in data and data['removeProfileImage'] not in [True, False]:
        return False, "removeProfileImage must be boolean"
    
    if 'removeGalleryImages' in data:
        remove_indices = data['removeGalleryImages']
        if not isinstance(remove_indices, list):
            return False, "removeGalleryImages must be a list of indices"
        
        for idx in remove_indices:
            if not isinstance(idx, int) or idx < 1 or idx > 5:
                return False, "removeGalleryImages indices must be integers between 1 and 5"
    
    return True, None


def delete_s3_image(key):
    """
    Delete an image from S3 bucket
    
    Args:
        key (str): S3 object key to delete
        
    Returns:
        bool: True if deleted successfully, False otherwise
    """
    try:
        s3_client.delete_object(
            Bucket=bucket_name,
            Key=key
        )
        print(f"Deleted S3 object: {key}")
        return True
    except Exception as e:
        print(f"Error deleting S3 object {key}: {str(e)}")
        return False


def handle_image_deletions(company_id, current_media, remove_profile, remove_gallery_indices):
    """
    Handle deletion of images from S3 and prepare updated media object
    
    Args:
        company_id (str): Company UUID
        current_media (dict): Current media object from DynamoDB
        remove_profile (bool): Whether to remove profile image
        remove_gallery_indices (list): List of gallery image indices to remove (1-5)
        
    Returns:
        dict: Updated media object
    """
    updated_media = {
        'profileImageUrl': current_media.get('profileImageUrl', ''),
        'galleryImages': current_media.get('galleryImages', []).copy()
    }
    
    deleted_images = []
    
    # Handle profile image deletion
    if remove_profile and updated_media['profileImageUrl']:
        profile_key = f"companies/{company_id}/profile.jpg"
        if delete_s3_image(profile_key):
            updated_media['profileImageUrl'] = ''
            deleted_images.append('profile')
    
    # Handle gallery images deletion
    if remove_gallery_indices:
        gallery_images = updated_media['galleryImages']
        
        # Sort indices in descending order to avoid index shifting issues
        sorted_indices = sorted(remove_gallery_indices, reverse=True)
        
        for idx in sorted_indices:
            # Convert 1-based index to 0-based
            array_idx = idx - 1
            
            if 0 <= array_idx < len(gallery_images):
                # Delete from S3
                gallery_key = f"companies/{company_id}/gallery/{idx}.jpg"
                if delete_s3_image(gallery_key):
                    # Remove from array
                    gallery_images.pop(array_idx)
                    deleted_images.append(f'gallery-{idx}')
        
        updated_media['galleryImages'] = gallery_images
    
    return updated_media, deleted_images


def generate_presigned_urls(company_id, current_media, request_profile_image=False, request_gallery_images=0):
    """
    Generate presigned URLs for image uploads
    
    Args:
        company_id (str): Company UUID
        current_media (dict): Current media to check existing gallery images
        request_profile_image (bool): Whether to generate URL for profile image
        request_gallery_images (int): Number of gallery image URLs to generate (0-5)
        
    Returns:
        dict: Presigned URLs for upload
    """
    presigned_urls = {}
    
    # Generate presigned URL for profile image (logo)
    if request_profile_image:
        profile_key = f"companies/{company_id}/profile.jpg"
        presigned_urls['profileImage'] = {
            'uploadUrl': s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': bucket_name,
                    'Key': profile_key,
                    'ContentType': 'image/jpeg'
                },
                ExpiresIn=3600
            ),
            'key': profile_key,
            'publicUrl': f"https://{bucket_name}.s3.{REGION}.amazonaws.com/{profile_key}"
        }
    
    # Generate presigned URLs for gallery images (max 5)
    if request_gallery_images > 0:
        presigned_urls['galleryImages'] = []
        
        # Determine existing gallery image count
        existing_gallery = current_media.get('galleryImages', [])
        existing_count = len(existing_gallery)
        
        # Calculate how many new images we can add (max 5 total)
        max_new_images = min(request_gallery_images, 5 - existing_count)
        
        if max_new_images <= 0:
            # Already at max capacity
            print(f"Cannot add more images. Already at maximum (5)")
            return presigned_urls
        
        # Generate URLs starting from next available index
        for i in range(max_new_images):
            next_index = existing_count + i + 1
            gallery_key = f"companies/{company_id}/gallery/{next_index}.jpg"
            presigned_urls['galleryImages'].append({
                'uploadUrl': s3_client.generate_presigned_url(
                    'put_object',
                    Params={
                        'Bucket': bucket_name,
                        'Key': gallery_key,
                        'ContentType': 'image/jpeg'
                    },
                    ExpiresIn=3600
                ),
                'key': gallery_key,
                'publicUrl': f"https://{bucket_name}.s3.{REGION}.amazonaws.com/{gallery_key}",
                'index': next_index
            })
    
    return presigned_urls


def build_update_expression(data, updated_media=None, current_media=None):
    """
    Build DynamoDB UpdateExpression from provided data
    
    Args:
        data (dict): Update data
        updated_media (dict): Updated media object if images were deleted
        current_media (dict): Current media from database
        
    Returns:
        tuple: (update_expression, expression_attribute_names, expression_attribute_values)
    """
    update_parts = []
    expr_attr_names = {}
    expr_attr_values = {}
    
    # Always update updatedAt timestamp
    update_parts.append("#updatedAt = :updatedAt")
    expr_attr_names["#updatedAt"] = "updatedAt"
    expr_attr_values[":updatedAt"] = datetime.utcnow().isoformat() + 'Z'
    
    # Update description if provided
    if 'description' in data:
        update_parts.append("#description = :description")
        expr_attr_names["#description"] = "description"
        expr_attr_values[":description"] = data['description']
    
    # Update location if provided
    if 'location' in data:
        location = {
            'city': data['location']['city'],
            'country': data['location']['country']
        }
        if 'coordinates' in data['location']:
            coords = data['location']['coordinates']
            location['coordinates'] = {
                'lat': Decimal(str(coords.get('lat', 0))),
                'lon': Decimal(str(coords.get('lon', 0)))
            }
        
        update_parts.append("#location = :location")
        expr_attr_names["#location"] = "location"
        expr_attr_values[":location"] = location
    
    # Prepare final media object
    final_media = current_media.copy() if current_media else {'profileImageUrl': '', 'galleryImages': []}
    
    # Apply deletions if any
    if updated_media is not None:
        final_media = updated_media
    
    # Apply new URLs if provided (merge with existing)
    if 'media' in data:
        media = data['media']
        
        # Update profile image URL only if provided
        if 'profileImageUrl' in media:
            final_media['profileImageUrl'] = media['profileImageUrl']
        
        # Merge gallery images (append new ones, keep existing up to max 5)
        if 'galleryImages' in media and media['galleryImages']:
            existing_gallery = final_media.get('galleryImages', [])
            new_images = media['galleryImages']
            
            # Merge: existing + new, remove duplicates, max 5
            merged_gallery = existing_gallery.copy()
            
            for new_img in new_images:
                if new_img and new_img not in merged_gallery:
                    merged_gallery.append(new_img)
            
            # Keep max 5 images
            final_media['galleryImages'] = merged_gallery[:5]
    
    # Update media in DynamoDB only if there were changes
    if updated_media is not None or 'media' in data:
        update_parts.append("#media = :media")
        expr_attr_names["#media"] = "media"
        expr_attr_values[":media"] = final_media
    
    update_expression = "SET " + ", ".join(update_parts)
    
    return update_expression, expr_attr_names, expr_attr_values


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    PUT /companies/{userId}
    Update company profile with description, location, and manage images
    
    Request body examples:
    
    1. Add description and location:
    {
        "description": "Fast food chain",
        "location": {
            "city": "Mechelen",
            "country": "Belgium",
            "coordinates": {"lat": 51.0259, "lon": 4.4773}
        }
    }
    
    2. Request presigned URLs for new uploads:
    {
        "requestProfileImage": true,
        "requestGalleryImages": 3
    }
    
    3. Save uploaded image URLs:
    {
        "media": {
            "profileImageUrl": "https://bucket.s3.amazonaws.com/companies/uuid/profile.jpg",
            "galleryImages": ["url1", "url2"]
        }
    }
    
    4. Delete images:
    {
        "removeProfileImage": true,
        "removeGalleryImages": [1, 3]
    }
    
    5. Delete and request new uploads:
    {
        "removeGalleryImages": [2],
        "requestGalleryImages": 2
    }
    
    Returns:
        200: Company updated successfully
        400: Invalid request data
        403: User not authorized
        404: Company not found
        500: Internal server error
    """
    try:
        # Get user ID from Cognito authorizer
        claims = event['requestContext']['authorizer']['claims']
        user_id = claims['sub']
        
        # Get userId from path parameters
        path_user_id = event['pathParameters']['userId']
        
        print(f"Update company request from user: {user_id} for path user: {path_user_id}")
        
        # Authorization check: user can only update their own company
        if user_id != path_user_id:
            print(f"Authorization failed: user {user_id} cannot update company for user {path_user_id}")
            return {
                'statusCode': 403,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Forbidden',
                    'message': 'You can only update your own company profile'
                })
            }
        
        # Check if company exists
        try:
            response = table.get_item(Key={'userId': user_id})
            if 'Item' not in response:
                print(f"Company not found for user: {user_id}")
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Not Found',
                        'message': 'Company profile not found. Please create one first.'
                    })
                }
            
            company = response['Item']
            company_id = company['companyId']
            current_media = company.get('media', {'profileImageUrl': '', 'galleryImages': []})
            
        except Exception as e:
            print(f"Error fetching company: {str(e)}")
            raise
        
        # Parse request body
        body = json.loads(event['body']) if event.get('body') else {}
        
        # Validate input data
        is_valid, error_msg = validate_update_data(body)
        if not is_valid:
            print(f"Validation failed: {error_msg}")
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': error_msg
                })
            }
        
        # Handle image deletions if requested
        updated_media = None
        deleted_images = []
        
        remove_profile = body.get('removeProfileImage', False)
        remove_gallery_indices = body.get('removeGalleryImages', [])
        
        if remove_profile or remove_gallery_indices:
            updated_media, deleted_images = handle_image_deletions(
                company_id,
                current_media,
                remove_profile,
                remove_gallery_indices
            )
            print(f"Images deleted: {deleted_images}")
        
        # Build update expression
        update_expr, expr_names, expr_values = build_update_expression(
            body, 
            updated_media,
            current_media  # Pass current media for merge
        )
        
        # Update DynamoDB
        updated_response = table.update_item(
            Key={'userId': user_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues='ALL_NEW'
        )
        
        updated_company = updated_response['Attributes']
        
        print(f"Company updated successfully: {company_id}")
        
        # Generate presigned URLs if requested
        request_profile_image = body.get('requestProfileImage', False)
        request_gallery_images = body.get('requestGalleryImages', 0)
        
        response_body = {
            'message': 'Company updated successfully',
            'company': updated_company
        }
        
        # Add deletion info if images were deleted
        if deleted_images:
            response_body['deletedImages'] = deleted_images
        
        # Add presigned URLs if requested
        if request_profile_image or request_gallery_images > 0:
            presigned_urls = generate_presigned_urls(
                company_id,
                current_media,  # ← Passa current_media
                request_profile_image,
                request_gallery_images
            )
            response_body['uploadUrls'] = presigned_urls
            response_body['uploadInstructions'] = {
                'expiresIn': 3600,
                'method': 'PUT',
                'contentType': 'image/jpeg',
                'note': 'Use the uploadUrl to PUT your image. After successful upload, call PUT /companies/{userId} again with the media URLs to save them.'
            }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_body, cls=DecimalEncoder)
        }
        
    except KeyError as e:
        print(f"Missing required field: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'message': f'Missing required field: {str(e)}'
            })
        }
    except Exception as e:
        print(f"Unexpected error updating company: {str(e)}")
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