import json
import os
import boto3
from botocore.exceptions import ClientError

cognito = boto3.client('cognito-idp')
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

USER_POOL_ID = os.environ['USER_POOL_ID']
USER_PROFILES_TABLE = os.environ['USER_PROFILES_TABLE']
USER_DOCUMENTS_TABLE = os.environ['USER_DOCUMENTS_TABLE']
DOCUMENTS_BUCKET = os.environ['DOCUMENTS_BUCKET']
COMPANIES_TABLE = os.environ['COMPANIES_TABLE']
JOB_LISTINGS_TABLE = os.environ['JOB_LISTINGS_TABLE']
BOOKINGS_TABLE = os.environ['BOOKINGS_TABLE']

profiles_table = dynamodb.Table(USER_PROFILES_TABLE)
documents_table = dynamodb.Table(USER_DOCUMENTS_TABLE)
companies_table = dynamodb.Table(COMPANIES_TABLE)
job_listings_table = dynamodb.Table(JOB_LISTINGS_TABLE)
bookings_table = dynamodb.Table(BOOKINGS_TABLE)

def delete_s3_files(s3_keys):
    """Elimina file da S3"""
    if not s3_keys:
        print("No S3 files to delete")
        return
    
    print(f"Attempting to delete {len(s3_keys)} S3 files from bucket: {DOCUMENTS_BUCKET}")
    deleted_count = 0
    for s3_key in s3_keys:
        try:
            print(f"Deleting S3 file: {s3_key}")
            s3.delete_object(
                Bucket=DOCUMENTS_BUCKET,
                Key=s3_key
            )
            deleted_count += 1
            print(f"Successfully deleted S3 file: {s3_key}")
        except ClientError as e:
            print(f"ERROR deleting S3 file {s3_key}: {e}")
            print(f"Error details: {e.response}")
    
    print(f"Deleted {deleted_count}/{len(s3_keys)} S3 files")

def is_user_in_companies_group(user_id):
    """Verifica se l'utente appartiene al gruppo 'companies'"""
    try:
        print(f"Checking groups for user {user_id}")
        response = cognito.admin_list_groups_for_user(
            UserPoolId=USER_POOL_ID,
            Username=user_id
        )
        
        groups = [group['GroupName'] for group in response.get('Groups', [])]
        print(f"User groups: {groups}")
        is_company = 'companies' in groups
        print(f"User is in companies group: {is_company}")
        return is_company
    except ClientError as e:
        print(f"ERROR checking user groups: {e}")
        print(f"Error details: {e.response}")
        return False

def get_user_groups(user_id):
    """Ottiene tutti i gruppi a cui appartiene l'utente"""
    try:
        print(f"Getting groups for user {user_id}")
        response = cognito.admin_list_groups_for_user(
            UserPoolId=USER_POOL_ID,
            Username=user_id
        )
        
        groups = [group['GroupName'] for group in response.get('Groups', [])]
        print(f"User groups: {groups}")
        return groups
    except ClientError as e:
        print(f"ERROR getting user groups: {e}")
        print(f"Error details: {e.response}")
        return []

def has_published_job_listings(company_id):
    """Verifica se la company ha job listings con status = published"""
    try:
        print(f"Checking for published job listings for company {company_id}")
        
        # Query usando il GSI companyId-publishedAt-index
        response = job_listings_table.query(
            IndexName='companyId-publishedAt-index',
            KeyConditionExpression='companyId = :company_id',
            FilterExpression='#status = :status',
            ExpressionAttributeNames={
                '#status': 'status'
            },
            ExpressionAttributeValues={
                ':company_id': company_id,
                ':status': 'published'
            },
            Limit=1  # Ci basta trovarne uno per bloccare l'eliminazione
        )
        
        items = response.get('Items', [])
        print(f"Query result: {json.dumps(items, default=str)}")
        published_count = len(items)
        print(f"Found {published_count} published job listings for company {company_id}")
        
        return published_count > 0
        
    except ClientError as e:
        print(f"ERROR checking job listings: {e}")
        print(f"Error details: {e.response}")
        # In caso di errore, per sicurezza blocchiamo l'eliminazione
        return True

def check_worker_active_bookings(user_id):
    """Verifica se il worker ha bookings attivi (status = pending o accepted)"""
    try:
        print(f"Checking for active bookings for worker {user_id}")
        
        response = bookings_table.query(
            IndexName='workerId-startDate-index',
            KeyConditionExpression='workerId = :worker_id',
            ExpressionAttributeValues={
                ':worker_id': user_id
            }
        )
        
        active_statuses = ['pending', 'accepted']
        active_bookings = []
        
        for booking in response.get('Items', []):
            if booking.get('status') in active_statuses:
                active_bookings.append({
                    'bookingId': booking.get('bookingId'),
                    'listingId': booking.get('listingId'),
                    'jobTitle': booking.get('jobTitle'),
                    'startDate': booking.get('startDate'),
                    'endDate': booking.get('endDate'),
                    'companyName': booking.get('companyName'),
                    'status': booking.get('status')
                })
        
        print(f"Found {len(active_bookings)} active bookings for worker {user_id}")
        return len(active_bookings) > 0, active_bookings
        
    except ClientError as e:
        print(f"ERROR checking worker bookings: {e}")
        print(f"Error details: {e.response}")
        # In caso di errore, per sicurezza blocchiamo l'eliminazione
        return True, []

def delete_worker_inactive_bookings(user_id):
    """Elimina tutti i bookings INATTIVI del worker (rejected, cancelled, completed, blocked)"""
    try:
        print(f"Deleting inactive bookings for worker {user_id}")
        
        response = bookings_table.query(
            IndexName='workerId-startDate-index',
            KeyConditionExpression='workerId = :worker_id',
            ExpressionAttributeValues={
                ':worker_id': user_id
            }
        )
        
        inactive_statuses = ['rejected', 'cancelled', 'completed', 'blocked']
        deleted_count = 0
        
        for booking in response.get('Items', []):
            if booking.get('status') in inactive_statuses:
                try:
                    bookings_table.delete_item(
                        Key={'bookingId': booking['bookingId']}
                    )
                    deleted_count += 1
                    print(f"Deleted inactive booking: {booking['bookingId']} (status: {booking.get('status')})")
                except ClientError as e:
                    print(f"ERROR deleting booking {booking['bookingId']}: {e}")
        
        print(f"Deleted {deleted_count} inactive bookings for worker {user_id}")
        return deleted_count
        
    except ClientError as e:
        print(f"ERROR deleting worker bookings: {e}")
        print(f"Error details: {e.response}")
        return 0

def check_company_active_bookings(company_id):
    """Verifica se la company ha bookings attivi (status = pending o accepted)"""
    try:
        print(f"Checking for active bookings for company {company_id}")
        
        active_statuses = ['pending', 'accepted']
        active_bookings = []
        
        # Controlla bookings per ogni status attivo usando l'indice companyId-status-index
        for status in active_statuses:
            response = bookings_table.query(
                IndexName='companyId-status-index',
                KeyConditionExpression='companyId = :company_id AND #status = :status',
                ExpressionAttributeNames={
                    '#status': 'status'
                },
                ExpressionAttributeValues={
                    ':company_id': company_id,
                    ':status': status
                }
            )
            
            for booking in response.get('Items', []):
                active_bookings.append({
                    'bookingId': booking.get('bookingId'),
                    'listingId': booking.get('listingId'),
                    'jobTitle': booking.get('jobTitle'),
                    'workerName': booking.get('workerName'),
                    'startDate': booking.get('startDate'),
                    'endDate': booking.get('endDate'),
                    'status': booking.get('status')
                })
        
        print(f"Found {len(active_bookings)} active bookings for company {company_id}")
        return len(active_bookings) > 0, active_bookings
        
    except ClientError as e:
        print(f"ERROR checking company bookings: {e}")
        print(f"Error details: {e.response}")
        # In caso di errore, per sicurezza blocchiamo l'eliminazione
        return True, []

def delete_company_inactive_bookings(company_id):
    """Elimina tutti i bookings INATTIVI della company"""
    try:
        print(f"Deleting inactive bookings for company {company_id}")
        
        # Prima ottieni tutti i job listings della company
        listings_response = job_listings_table.query(
            IndexName='companyId-createdAt-index',
            KeyConditionExpression='companyId = :company_id',
            ExpressionAttributeValues={
                ':company_id': company_id
            }
        )
        
        deleted_count = 0
        inactive_statuses = ['rejected', 'cancelled', 'completed', 'blocked']
        
        # Elimina bookings per ogni listing
        for listing in listings_response.get('Items', []):
            listing_id = listing.get('listingId')
            
            bookings_response = bookings_table.query(
                IndexName='listingId-startDate-index',
                KeyConditionExpression='listingId = :listing_id',
                ExpressionAttributeValues={
                    ':listing_id': listing_id
                }
            )
            
            for booking in bookings_response.get('Items', []):
                if booking.get('status') in inactive_statuses:
                    try:
                        bookings_table.delete_item(
                            Key={'bookingId': booking['bookingId']}
                        )
                        deleted_count += 1
                        print(f"Deleted inactive booking: {booking['bookingId']} (status: {booking.get('status')})")
                    except ClientError as e:
                        print(f"ERROR deleting booking {booking['bookingId']}: {e}")
        
        print(f"Deleted {deleted_count} inactive bookings for company {company_id}")
        return deleted_count
        
    except ClientError as e:
        print(f"ERROR deleting company bookings: {e}")
        print(f"Error details: {e.response}")
        return 0

def handler(event, context):
    """
    DELETE /profile - Elimina utente da Cognito, UserProfiles, UserDocuments, Companies, Bookings e S3
    """
    try:
        # Estrai user_id dal token Cognito
        user_id = event['requestContext']['authorizer']['claims']['sub']
        pk = f"USER#{user_id}"
        
        print(f"=== Starting deletion process for user: {user_id} ===")
        print(f"Environment variables:")
        print(f"  USER_POOL_ID: {USER_POOL_ID}")
        print(f"  USER_PROFILES_TABLE: {USER_PROFILES_TABLE}")
        print(f"  USER_DOCUMENTS_TABLE: {USER_DOCUMENTS_TABLE}")
        print(f"  DOCUMENTS_BUCKET: {DOCUMENTS_BUCKET}")
        print(f"  COMPANIES_TABLE: {COMPANIES_TABLE}")
        print(f"  JOB_LISTINGS_TABLE: {JOB_LISTINGS_TABLE}")
        print(f"  BOOKINGS_TABLE: {BOOKINGS_TABLE}")
        
        company_deleted = False
        deleted_bookings = 0
        
        # 0. Determina il tipo di utente dai gruppi Cognito
        print("\n--- Step 0: Determining user type ---")
        user_groups = get_user_groups(user_id)
        
        # Gestione per COMPANY
        if 'companies' in user_groups:
            print("User is a COMPANY")
            
            # Recupera il record company dalla tabella Companies usando userId come chiave
            try:
                print(f"Querying Companies table with userId: {user_id}")
                response = companies_table.get_item(
                    Key={'userId': user_id}
                )
                
                print(f"Companies query response: {json.dumps(response, default=str)}")
                
                if 'Item' in response:
                    company_record = response['Item']
                    company_id = company_record.get('companyId')
                    print(f"Found company record with companyId: {company_id}")
                    
                    # Verifica se ci sono job listings pubblicati
                    if has_published_job_listings(company_id):
                        print(f"Company {company_id} has published job listings - deletion not allowed")
                        return {
                            'statusCode': 400,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'error': 'Bad Request',
                                'message': 'You have published job listings. Please unpublish or delete them before deleting your account.',
                                'code': 4291
                            })
                        }
                    
                    # Verifica se ci sono bookings attivi
                    has_active, active_bookings = check_company_active_bookings(company_id)
                    if has_active:
                        print(f"Company {company_id} has {len(active_bookings)} active bookings - deletion not allowed")
                        return {
                            'statusCode': 400,
                            'headers': {
                                'Content-Type': 'application/json',
                                'Access-Control-Allow-Origin': '*'
                            },
                            'body': json.dumps({
                                'error': 'Bad Request',
                                'message': f'You have {len(active_bookings)} active bookings (pending or accepted). Please cancel or complete them before deleting your account.',
                                'activeBookings': active_bookings,
                                'code': 4112
                            })
                        }
                    
                    # Elimina i bookings inattivi della company
                    deleted_bookings = delete_company_inactive_bookings(company_id)
                    print(f"Deleted {deleted_bookings} inactive bookings for company")
                    
                    # Se non ci sono job listings pubblicati né bookings attivi, procedi con l'eliminazione della company
                    try:
                        print(f"Deleting company with userId: {user_id}")
                        companies_table.delete_item(
                            Key={'userId': user_id}
                        )
                        company_deleted = True
                        print(f"Successfully deleted company for user {user_id}")
                    except ClientError as e:
                        print(f"ERROR deleting company: {e}")
                        print(f"Error details: {e.response}")
                else:
                    print(f"WARNING: User is in companies group but no company record found in Companies table")
                        
            except ClientError as e:
                print(f"ERROR retrieving company record: {e}")
                print(f"Error details: {e.response}")
        
        # Gestione per WORKER
        elif 'workers' in user_groups:
            print("User is a WORKER")
            
            # Verifica se ci sono bookings attivi
            has_active, active_bookings = check_worker_active_bookings(user_id)
            if has_active:
                print(f"Worker {user_id} has {len(active_bookings)} active bookings - deletion not allowed")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': f'You have {len(active_bookings)} active bookings (pending or accepted). Please cancel or complete them before deleting your account.',
                        'activeBookings': active_bookings,
                        'code': 4112
                    })
                }
            
            # Elimina i bookings inattivi del worker
            deleted_bookings = delete_worker_inactive_bookings(user_id)
            print(f"Deleted {deleted_bookings} inactive bookings for worker")
        
        # Gestione per BASIC o altri tipi
        else:
            print(f"User is BASIC or other type (groups: {user_groups})")
            # Per gli utenti basic non dovrebbero esserci bookings, ma per sicurezza controlliamo
            has_active, active_bookings = check_worker_active_bookings(user_id)
            if has_active:
                print(f"Basic user {user_id} has {len(active_bookings)} active bookings - deletion not allowed")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': f'You have {len(active_bookings)} active bookings. Please cancel or complete them before deleting your account.',
                        'activeBookings': active_bookings,
                        'code': 4112
                    })
                }
            
            # Elimina eventuali bookings inattivi
            deleted_bookings = delete_worker_inactive_bookings(user_id)
            if deleted_bookings > 0:
                print(f"Deleted {deleted_bookings} inactive bookings for basic user")
        
        # 1. Recupera tutti i documenti dell'utente e raccogli gli s3_key
        print("\n--- Step 1: Retrieving user documents ---")
        s3_keys = []
        documents_to_delete = []
        
        try:
            print(f"Querying documents with pk: {pk}")
            response = documents_table.query(
                KeyConditionExpression='pk = :pk',
                ExpressionAttributeValues={
                    ':pk': pk
                }
            )
            
            print(f"Query response: {json.dumps(response, default=str)}")
            
            if 'Items' in response:
                print(f"Found {len(response['Items'])} documents")
                for item in response['Items']:
                    print(f"Processing document: pk={item.get('pk')}, sk={item.get('sk')}")
                    # Raccogli s3Key se presente
                    if 's3Key' in item:
                        s3_keys.append(item['s3Key'])
                        print(f"  Found s3Key: {item['s3Key']}")
                    else:
                        print(f"  No s3Key found in document")
                    
                    # Salva la chiave per eliminazione
                    documents_to_delete.append({
                        'pk': item['pk'],
                        'sk': item['sk']
                    })
                
                print(f"Total: {len(documents_to_delete)} documents and {len(s3_keys)} S3 files")
            else:
                print("No documents found in response")
        except ClientError as e:
            print(f"ERROR retrieving documents: {e}")
            print(f"Error details: {e.response}")
        
        # 2. Elimina file da S3
        print("\n--- Step 2: Deleting S3 files ---")
        if s3_keys:
            delete_s3_files(s3_keys)
        else:
            print("No S3 files to delete")
        
        # 3. Elimina tutti i documenti dalla tabella UserDocuments
        print("\n--- Step 3: Deleting document records from DynamoDB ---")
        deleted_docs = 0
        for doc in documents_to_delete:
            try:
                print(f"Deleting document: pk={doc['pk']}, sk={doc['sk']}")
                documents_table.delete_item(
                    Key={
                        'pk': doc['pk'],
                        'sk': doc['sk']
                    }
                )
                deleted_docs += 1
                print(f"Successfully deleted document: {doc['sk']}")
            except ClientError as e:
                print(f"ERROR deleting document {doc['sk']}: {e}")
                print(f"Error details: {e.response}")
        
        print(f"Deleted {deleted_docs}/{len(documents_to_delete)} document records")
        
        # 4. Elimina profilo dalla tabella UserProfiles
        print("\n--- Step 4: Deleting user profile ---")
        try:
            print(f"Deleting profile for user_id: {user_id}")
            profiles_table.delete_item(
                Key={'user_id': user_id}
            )
            print(f"Successfully deleted profile for user {user_id}")
        except ClientError as e:
            print(f"ERROR deleting profile: {e}")
            print(f"Error details: {e.response}")
        
        # 5. Elimina utente da Cognito
        print("\n--- Step 5: Deleting user from Cognito ---")
        try:
            print(f"Deleting Cognito user: {user_id}")
            cognito.admin_delete_user(
                UserPoolId=USER_POOL_ID,
                Username=user_id
            )
            print(f"Successfully deleted Cognito user {user_id}")
        except ClientError as e:
            print(f"ERROR deleting Cognito user: {e}")
            print(f"Error details: {e.response}")
            raise
        
        response_body = {
            'message': 'User deleted successfully',
            'user_id': user_id,
            'deleted_files': len(s3_keys),
            'deleted_documents': deleted_docs,
            'deleted_bookings': deleted_bookings,
            'code': 3021
        }
        
        if company_deleted:
            response_body['company_deleted'] = True
        
        print(f"\n=== Deletion process completed ===")
        print(f"Response: {json.dumps(response_body)}")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_body)
        }
    except KeyError as e:
        print(f"KeyError: {e}")
        return {
            'statusCode': 401,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': 'Unauthorized', 'message': 'Missing authorization token', 'code': 4113})
        }
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': 'Internal Server Error', 'message': str(e), 'code': 5023})
        }