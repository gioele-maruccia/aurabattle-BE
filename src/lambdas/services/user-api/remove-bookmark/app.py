"""
User API - Remove Job Listing Bookmark
Rimuove un job listing dai bookmark dell'utente
"""
import json
import os
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

def handler(event, context):
    """
    DELETE /bookmarks/job-listings/{job_listing_id}
    Rimuove un job listing dai bookmark dell'utente
    """
    try:
        # Estrai user_id dal token Cognito
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Estrai job_listing_id dai path parameters
        job_listing_id = event['pathParameters']['job_listing_id']
        
        print(f"[RemoveBookmark] User {user_id} removing job listing {job_listing_id}")
        
        # Recupera il profilo utente per trovare l'indice del bookmark
        profile_response = user_profiles_table.get_item(Key={'user_id': user_id})
        
        if 'Item' not in profile_response:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'User profile not found', 'code': 4289})
            }
        
        profile = profile_response['Item']
        bookmarked_listings = profile.get('bookmarked_job_listings', [])
        
        # Trova l'indice del job listing da rimuovere
        if job_listing_id not in bookmarked_listings:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not Found', 'message': 'Bookmark not found', 'code': 4124})
            }
        
        index = bookmarked_listings.index(job_listing_id)
        
        # Rimuovi il bookmark usando l'indice
        response = user_profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression=f'REMOVE bookmarked_job_listings[{index}] SET updated_at = :timestamp',
            ExpressionAttributeValues={
                ':timestamp': datetime.utcnow().isoformat() + 'Z'
            },
            ReturnValues='ALL_NEW'
        )
        
        print(f"[RemoveBookmark] ✅ Bookmark removed successfully")
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'message': 'Bookmark removed successfully',
                'bookmarked_job_listings': response['Attributes'].get('bookmarked_job_listings', []),
                'code': 3028
            })
        }
        
    except KeyError as e:
        print(f"[RemoveBookmark] ❌ Missing parameter: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Bad Request', 'message': f'Missing parameter: {str(e)}', 'code': 4290})
        }
        
    except Exception as e:
        print(f"[RemoveBookmark] ❌ Error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Internal Server Error', 'message': str(e), 'code': 5082})
        }
