"""
User API - Add Job Listing Bookmark
Aggiunge un job listing ai bookmark dell'utente
"""
import json
import os
import boto3
from datetime import datetime
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
job_listings_table = dynamodb.Table(os.environ['JOB_LISTINGS_TABLE'])

def handler(event, context):
    """
    POST /bookmarks/job-listings/{job_listing_id}
    Aggiunge un job listing ai bookmark dell'utente
    """
    try:
        # Estrai user_id dal token Cognito
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Estrai job_listing_id dai path parameters
        job_listing_id = event['pathParameters']['job_listing_id']
        
        print(f"[AddBookmark] User {user_id} adding job listing {job_listing_id}")
        
        # Verifica che il job listing esista
        job_response = job_listings_table.get_item(Key={'listingId': job_listing_id})
        
        if 'Item' not in job_response:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Job listing not found', 'code': 4109})
            }
        
        job_listing = job_response['Item']
        
        # Verifica che il job listing sia pubblicato
        # Stati possibili: draft, published, paused, closed, archived
        if job_listing.get('status') != 'published':
            status = job_listing.get('status', 'unknown')
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': f'Cannot bookmark job listing with status: {status}. Only published job listings can be bookmarked',
                    'code': 4108
                })
            }
        
        # Verifica che il profilo utente esista
        profile_response = user_profiles_table.get_item(Key={'user_id': user_id})
        
        if 'Item' not in profile_response:
            print(f"[AddBookmark] ❌ User profile not found for user {user_id}")
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'User profile not found', 'code': 4110})
            }
        
        profile = profile_response['Item']
        bookmarked_listings = profile.get('bookmarked_job_listings', [])
        
        # Verifica se il bookmark esiste già
        if job_listing_id in bookmarked_listings:
            print(f"[AddBookmark] ⚠️ Bookmark already exists for user {user_id} and job {job_listing_id}")
            return {
                'statusCode': 409,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({
                    'error': 'Conflict',
                    'message': 'This job listing is already in your bookmarks',
                    'code': 4111
                })
            }
        
        # Aggiorna il profilo utente aggiungendo il bookmark
        response = user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='SET bookmarked_job_listings = list_append(if_not_exists(bookmarked_job_listings, :empty_list), :job_id), updated_at = :timestamp',
            ExpressionAttributeValues={
                ':job_id': [job_listing_id],
                ':empty_list': [],
                ':timestamp': datetime.utcnow().isoformat() + 'Z'
            },
            ReturnValues='ALL_NEW'
        )
        
        print(f"[AddBookmark] ✅ Bookmark added successfully")
        
        return {
            'statusCode': 201,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'message': 'Bookmark added successfully',
                'bookmarked_job_listings': response['Attributes'].get('bookmarked_job_listings', []),
                'code': 3020
            })
        }
        
    except KeyError as e:
        print(f"[AddBookmark] ❌ Missing parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': f'Missing parameter: {str(e)}', 'code': 4288})
        }
        
    except Exception as e:
        print(f"[AddBookmark] ❌ Error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': str(e), 'code': 5022})
        }
