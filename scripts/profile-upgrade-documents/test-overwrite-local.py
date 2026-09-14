"""
TEST LOCALE - Document Overwrite Feature
=========================================
Testa la funzionalità di overwrite dei documenti nel profile upgrade
SENZA modificare il database AWS reale.

Usa moto per mockare DynamoDB e S3 localmente.

Requirements:
    pip install moto boto3

Usage:
    python test-overwrite-local.py
"""

import json
import os
import sys
import time
from unittest.mock import patch, MagicMock

# Setup mocking BEFORE importing boto3
os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
os.environ['AWS_SECURITY_TOKEN'] = 'testing'
os.environ['AWS_SESSION_TOKEN'] = 'testing'
os.environ['AWS_DEFAULT_REGION'] = 'eu-south-1'

from moto import mock_aws
import boto3

# Setup environment variables for the lambda
os.environ['REGION'] = 'eu-south-1'
os.environ['BUCKET'] = 'test-bucket'
os.environ['KMS_KEY_ID'] = 'test-kms-key'
os.environ['TABLE_NAME'] = 'test-UserDocuments'
os.environ['CLEANUP_FUNCTION_NAME'] = 'test-cleanup-function'
os.environ['USER_PROFILES_TABLE'] = 'test-UserProfiles'

# Import the lambda module (it will use mocked boto3)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src/lambdas/services/profile-upgrade-documents/presign-url'))
import app as lambda_app


def print_section(title):
    """Print a section header"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def print_success(message):
    """Print success message in green"""
    print(f"✅ {message}")


def print_error(message):
    """Print error message in red"""
    print(f"❌ {message}")


def print_info(message):
    """Print info message"""
    print(f"ℹ️  {message}")


@mock_aws
def setup_mock_resources():
    """Setup mock DynamoDB and S3"""
    print_section("Setup Mock AWS Resources")
    
    # Create DynamoDB table
    dynamodb = boto3.client('dynamodb', region_name='eu-south-1')
    dynamodb.create_table(
        TableName='test-UserDocuments',
        KeySchema=[
            {'AttributeName': 'pk', 'KeyType': 'HASH'},
            {'AttributeName': 'sk', 'KeyType': 'RANGE'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'pk', 'AttributeType': 'S'},
            {'AttributeName': 'sk', 'AttributeType': 'S'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    print_success("Created mock DynamoDB table: test-UserDocuments")
    
    # Create UserProfiles table
    dynamodb.create_table(
        TableName='test-UserProfiles',
        KeySchema=[
            {'AttributeName': 'user_id', 'KeyType': 'HASH'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'user_id', 'AttributeType': 'S'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    print_success("Created mock DynamoDB table: test-UserProfiles")
    
    # Create S3 bucket
    s3 = boto3.client('s3', region_name='eu-south-1')
    s3.create_bucket(
        Bucket='test-bucket',
        CreateBucketConfiguration={'LocationConstraint': 'eu-south-1'}
    )
    print_success("Created mock S3 bucket: test-bucket")
    
    return dynamodb, s3


@mock_aws
def insert_existing_documents(dynamodb, s3, user_sub, doc_type, count=3):
    """Insert existing documents to simulate previous uploads"""
    print_info(f"Inserting {count} existing '{doc_type}' documents for user {user_sub}")
    
    table = boto3.resource('dynamodb', region_name='eu-south-1').Table('test-UserDocuments')
    
    for i in range(count):
        ts_ms = int(time.time() * 1000) - (i * 10000)  # Different timestamps
        pk = f"USER#{user_sub}"
        sk = f"DOC#{doc_type}#{ts_ms}"
        s3_key = f"docs/{user_sub}/{ts_ms}_{doc_type}.jpg"
        
        # Insert into DynamoDB
        table.put_item(Item={
            'pk': pk,
            'sk': sk,
            's3Key': s3_key,
            'docType': doc_type,
            'mime': 'image/jpeg',
            'size': 1024,
            'status': 'AWAITING_REVIEW',
            'uploadedAt': time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            'ttl': int(time.time()) + 86400 * 30
        })
        
        # Put object in S3
        s3.put_object(
            Bucket='test-bucket',
            Key=s3_key,
            Body=b'fake image data'
        )
        
        print(f"   Document {i+1}: {sk}")
    
    print_success(f"Inserted {count} existing documents")


@mock_aws
def count_documents(user_sub, doc_type):
    """Count documents of a specific type for a user"""
    table = boto3.resource('dynamodb', region_name='eu-south-1').Table('test-UserDocuments')
    
    pk = f"USER#{user_sub}"
    sk_prefix = f"DOC#{doc_type}#"
    
    response = table.query(
        KeyConditionExpression='pk = :pk AND begins_with(sk, :sk_prefix)',
        ExpressionAttributeValues={
            ':pk': pk,
            ':sk_prefix': sk_prefix
        }
    )
    
    return len(response.get('Items', []))


@mock_aws
def count_s3_objects(user_sub):
    """Count S3 objects for a user"""
    s3 = boto3.client('s3', region_name='eu-south-1')
    
    response = s3.list_objects_v2(
        Bucket='test-bucket',
        Prefix=f'docs/{user_sub}/'
    )
    
    return len(response.get('Contents', []))


@mock_aws
def test_delete_existing_documents():
    """Test the delete function directly"""
    print_section("Test 1: Delete Existing Documents Function")
    
    # Setup
    dynamodb, s3 = setup_mock_resources()
    user_sub = "test-user-123"
    doc_type = "id_card_front"
    
    # Insert 3 existing documents
    insert_existing_documents(dynamodb, s3, user_sub, doc_type, count=3)
    
    # Verify they exist
    count_before = count_documents(user_sub, doc_type)
    s3_count_before = count_s3_objects(user_sub)
    print_info(f"Documents in DB before delete: {count_before}")
    print_info(f"Files in S3 before delete: {s3_count_before}")
    
    if count_before != 3:
        print_error(f"Expected 3 documents, found {count_before}")
        return False
    
    # Call the delete function
    print_info(f"Calling _delete_existing_documents_of_type...")
    deleted_count = lambda_app._delete_existing_documents_of_type(user_sub, doc_type)
    
    # Verify deletion
    count_after = count_documents(user_sub, doc_type)
    s3_count_after = count_s3_objects(user_sub)
    print_info(f"Documents in DB after delete: {count_after}")
    print_info(f"Files in S3 after delete: {s3_count_after}")
    print_info(f"Deleted count returned: {deleted_count}")
    
    if count_after == 0 and s3_count_after == 0 and deleted_count == 3:
        print_success("All documents deleted successfully!")
        return True
    else:
        print_error(f"Delete failed! Expected 0 documents, found {count_after} in DB and {s3_count_after} in S3")
        return False


@mock_aws
def test_overwrite_on_upload():
    """Test the complete overwrite flow when uploading a document"""
    print_section("Test 2: Overwrite Flow on Document Upload")
    
    # Setup
    dynamodb, s3 = setup_mock_resources()
    user_sub = "test-user-456"
    doc_type = "visura"
    
    # Add user profile
    profiles_table = boto3.resource('dynamodb', region_name='eu-south-1').Table('test-UserProfiles')
    profiles_table.put_item(Item={
        'user_id': user_sub,
        'user_type': 'company'
    })
    
    # Insert 2 existing documents
    insert_existing_documents(dynamodb, s3, user_sub, doc_type, count=2)
    
    count_before = count_documents(user_sub, doc_type)
    print_info(f"Documents before upload: {count_before}")
    
    if count_before != 2:
        print_error(f"Setup failed: Expected 2 documents, found {count_before}")
        return False
    
    # Create a mock event (simulating API Gateway request)
    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": user_sub
                }
            }
        },
        "body": json.dumps({
            "docType": doc_type,
            "mime": "application/pdf",
            "size": 2048
        })
    }
    
    # Mock only EventBridge scheduling (not critical for overwrite test)
    # We patch the _schedule_cleanup function to avoid EventBridge complexity
    with patch.object(lambda_app, '_schedule_cleanup', return_value=None):
        # Call the lambda handler
        print_info("Calling lambda_handler to upload new document...")
        response = lambda_app.lambda_handler(event, None)
    
    # Check response
    print_info(f"Lambda response status: {response['statusCode']}")
    
    if response['statusCode'] != 200:
        print_error(f"Lambda returned error: {response.get('body')}")
        return False
    
    # Verify old documents were deleted and only new one remains
    count_after = count_documents(user_sub, doc_type)
    print_info(f"Documents after upload: {count_after}")
    
    if count_after == 1:
        print_success("Overwrite successful! Old documents deleted, new one created")
        
        # Show the remaining document
        table = boto3.resource('dynamodb', region_name='eu-south-1').Table('test-UserDocuments')
        response = table.query(
            KeyConditionExpression='pk = :pk AND begins_with(sk, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': f"USER#{user_sub}",
                ':sk_prefix': f"DOC#{doc_type}#"
            }
        )
        
        if response['Items']:
            remaining_doc = response['Items'][0]
            print_info(f"Remaining document: {remaining_doc['sk']} - Status: {remaining_doc['status']}")
        
        return True
    else:
        print_error(f"Overwrite failed! Expected 1 document, found {count_after}")
        return False


@mock_aws
def test_multiple_document_types():
    """Test that deleting one type doesn't affect other types"""
    print_section("Test 3: Multiple Document Types Isolation")
    
    # Setup
    dynamodb, s3 = setup_mock_resources()
    user_sub = "test-user-789"
    
    # Insert documents of different types
    insert_existing_documents(dynamodb, s3, user_sub, "id_card_front", count=2)
    insert_existing_documents(dynamodb, s3, user_sub, "id_card_back", count=2)
    insert_existing_documents(dynamodb, s3, user_sub, "selfie", count=1)
    
    total_before = count_documents(user_sub, "id_card_front") + \
                   count_documents(user_sub, "id_card_back") + \
                   count_documents(user_sub, "selfie")
    
    print_info(f"Total documents before: {total_before}")
    print_info(f"  - id_card_front: {count_documents(user_sub, 'id_card_front')}")
    print_info(f"  - id_card_back: {count_documents(user_sub, 'id_card_back')}")
    print_info(f"  - selfie: {count_documents(user_sub, 'selfie')}")
    
    # Delete only id_card_front
    print_info("Deleting only 'id_card_front' documents...")
    lambda_app._delete_existing_documents_of_type(user_sub, "id_card_front")
    
    # Check counts
    front_after = count_documents(user_sub, "id_card_front")
    back_after = count_documents(user_sub, "id_card_back")
    selfie_after = count_documents(user_sub, "selfie")
    
    print_info(f"Documents after deletion:")
    print_info(f"  - id_card_front: {front_after}")
    print_info(f"  - id_card_back: {back_after}")
    print_info(f"  - selfie: {selfie_after}")
    
    if front_after == 0 and back_after == 2 and selfie_after == 1:
        print_success("Document type isolation working correctly!")
        return True
    else:
        print_error(f"Isolation failed! Expected (0, 2, 1), got ({front_after}, {back_after}, {selfie_after})")
        return False


def main():
    """Run all tests"""
    print_section("🧪 LOCAL TEST - Document Overwrite Feature")
    print_info("Testing WITHOUT touching AWS databases!")
    print_info("Using moto to mock DynamoDB and S3")
    
    tests = [
        ("Delete Existing Documents", test_delete_existing_documents),
        ("Complete Overwrite Flow", test_overwrite_on_upload),
        ("Document Type Isolation", test_multiple_document_types),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print_error(f"Test '{test_name}' crashed: {str(e)}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Print summary
    print_section("📊 Test Summary")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status} - {test_name}")
    
    print(f"\n{'='*70}")
    print(f"  Results: {passed}/{total} tests passed")
    print(f"{'='*70}\n")
    
    if passed == total:
        print_success("All tests passed! 🎉")
        return 0
    else:
        print_error(f"{total - passed} test(s) failed!")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
