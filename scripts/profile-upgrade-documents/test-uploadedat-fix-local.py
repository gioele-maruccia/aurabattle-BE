"""
TEST LOCALE - uploadedAt Fix Verification
==========================================
Verifica che uploadedAt NON sia impostato quando viene creato il record PENDING
e che venga impostato solo quando il file è effettivamente caricato.

Usa moto per mockare DynamoDB e S3 localmente SENZA toccare AWS.

Requirements:
    pip install moto boto3

Usage:
    python test-uploadedat-fix-local.py
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

# Import the lambda modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src/lambdas/services/profile-upgrade-documents/presign-url'))
import app as presign_app

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src/lambdas/services/profile-upgrade-documents/doc-received'))
import app as doc_received_app


def print_section(title):
    """Print a section header"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def print_success(message):
    """Print success message"""
    print(f"✅ {message}")


def print_error(message):
    """Print error message"""
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
def test_pending_record_no_uploadedat():
    """
    TEST 1: Verifica che uploadedAt NON sia presente nel record PENDING
    """
    print_section("TEST 1: Record PENDING NON deve avere uploadedAt")
    
    # Setup
    dynamodb, s3 = setup_mock_resources()
    user_sub = "test-user-pending"
    
    # Mock EventBridge per evitare errori di cleanup scheduling
    with patch('boto3.client') as mock_client:
        # Setup mock responses
        mock_events = MagicMock()
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {'Account': '123456789012'}
        mock_events.put_rule.return_value = {'RuleArn': 'arn:aws:events:eu-south-1:123456789012:rule/test-rule'}
        mock_events.put_targets.return_value = {'FailedEntryCount': 0}
        
        # Return appropriate mock based on service name
        def get_mock_client(service_name, **kwargs):
            if service_name == 'events':
                return mock_events
            elif service_name == 'sts':
                return mock_sts
            else:
                return boto3.client(service_name, **kwargs)
        
        mock_client.side_effect = get_mock_client
        
        # Create mock event (presigned URL request)
        event = {
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "sub": user_sub
                    }
                }
            },
            "body": json.dumps({
                "docType": "id_card_front",
                "mime": "image/jpeg",
                "size": 2048576
            })
        }
        
        # Call the lambda
        print_info("Calling presign-url lambda...")
        response = presign_app.lambda_handler(event, {})
        
        # Verify response is successful
        if response['statusCode'] != 200:
            print_error(f"Lambda failed with status {response['statusCode']}")
            print_error(f"Response: {response['body']}")
            return False
        
        print_success(f"Lambda returned status 200")
        
        # Get the created record from DynamoDB
        table = boto3.resource('dynamodb', region_name='eu-south-1').Table('test-UserDocuments')
        pk = f"USER#{user_sub}"
        
        response = table.query(
            KeyConditionExpression='pk = :pk AND begins_with(sk, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': pk,
                ':sk_prefix': 'DOC#id_card_front#'
            }
        )
        
        items = response.get('Items', [])
        
        if len(items) != 1:
            print_error(f"Expected 1 record, found {len(items)}")
            return False
        
        item = items[0]
        print_info(f"Found record: {item['sk']}")
        print_info(f"Status: {item.get('status')}")
        
        # VERIFICA: status deve essere PENDING
        if item.get('status') != 'PENDING':
            print_error(f"Expected status PENDING, found {item.get('status')}")
            return False
        
        print_success("Status is PENDING ✓")
        
        # VERIFICA: uploadedAt NON deve esistere
        if 'uploadedAt' in item:
            print_error(f"❌ BUG TROVATO! uploadedAt è presente nel record PENDING: {item['uploadedAt']}")
            print_error("I documenti risulteranno già scaduti appena caricati!")
            return False
        
        print_success("uploadedAt NON è presente nel record PENDING ✓")
        print_success("TEST PASSED! Il bug è stato fixato correttamente!")
        
        return True


@mock_aws  
def test_uploaded_record_has_uploadedat():
    """
    TEST 2: Verifica che uploadedAt SIA presente nel record UPLOADED
    """
    print_section("TEST 2: Record UPLOADED deve avere uploadedAt")
    
    # Setup
    dynamodb, s3 = setup_mock_resources()
    user_sub = "test-user-uploaded"
    doc_type = "id_card_front"
    ts_ms = int(time.time() * 1000)
    
    # Create PENDING record manually (simulating presign-url)
    table = boto3.resource('dynamodb', region_name='eu-south-1').Table('test-UserDocuments')
    pk = f"USER#{user_sub}"
    sk = f"DOC#{doc_type}#{ts_ms}"
    s3_key = f"docs/{user_sub}/{ts_ms}_{doc_type}.jpg"
    
    table.put_item(Item={
        'pk': pk,
        'sk': sk,
        's3Key': s3_key,
        'docType': doc_type,
        'mime': 'image/jpeg',
        'size': 1024,
        'status': 'PENDING',
        'ttl': int(time.time()) + 86400 * 30
    })
    
    print_info(f"Created PENDING record: {sk}")
    
    # Verify no uploadedAt
    item_before = table.get_item(Key={'pk': pk, 'sk': sk})['Item']
    if 'uploadedAt' in item_before:
        print_error("Test setup failed: uploadedAt already present in PENDING record")
        return False
    
    print_success("PENDING record has no uploadedAt ✓")
    
    # Upload file to S3 (simulating user upload)
    s3.put_object(
        Bucket='test-bucket',
        Key=s3_key,
        Body=b'fake image data'
    )
    print_info(f"Uploaded file to S3: {s3_key}")
    
    # Call doc-received (simulating S3 event)
    event = {
        "Records": [{
            "s3": {
                "bucket": {"name": "test-bucket"},
                "object": {"key": s3_key, "size": 1024}
            }
        }]
    }
    
    print_info("Calling doc-received lambda...")
    
    # Mock the lambda invocation for doc-scan
    with patch('boto3.client') as mock_boto_client:
        # Create mock lambda client
        mock_lambda = MagicMock()
        mock_lambda.invoke.return_value = {}
        
        # Return appropriate mock based on service name
        def get_mock_client(service_name, **kwargs):
            if service_name == 'lambda':
                return mock_lambda
            else:
                return boto3.client(service_name, **kwargs)
        
        mock_boto_client.side_effect = get_mock_client
        
        response = doc_received_app.lambda_handler(event, {})
    
    if not response.get('ok'):
        print_error(f"doc-received failed: {response}")
        return False
    
    print_success("doc-received completed successfully")
    
    # Verify uploadedAt is now present
    item_after = table.get_item(Key={'pk': pk, 'sk': sk})['Item']
    
    print_info(f"Status after upload: {item_after.get('status')}")
    
    if item_after.get('status') != 'UPLOADED':
        print_error(f"Expected status UPLOADED, found {item_after.get('status')}")
        return False
    
    print_success("Status is UPLOADED ✓")
    
    if 'uploadedAt' not in item_after:
        print_error("uploadedAt is missing from UPLOADED record!")
        return False
    
    print_success(f"uploadedAt is present: {item_after['uploadedAt']} ✓")
    print_success("TEST PASSED! uploadedAt viene impostato correttamente al momento dell'upload!")
    
    return True


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("  TEST LOCALE - Verifica Fix uploadedAt")
    print("  NESSUNA CONNESSIONE AD AWS - Solo mock locali con moto")
    print("="*70)
    
    results = []
    
    # Test 1: PENDING record should NOT have uploadedAt
    try:
        result1 = test_pending_record_no_uploadedat()
        results.append(("PENDING senza uploadedAt", result1))
    except Exception as e:
        print_error(f"Test 1 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("PENDING senza uploadedAt", False))
    
    # Test 2: UPLOADED record SHOULD have uploadedAt
    try:
        result2 = test_uploaded_record_has_uploadedat()
        results.append(("UPLOADED con uploadedAt", result2))
    except Exception as e:
        print_error(f"Test 2 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("UPLOADED con uploadedAt", False))
    
    # Summary
    print_section("Test Summary")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status} - {test_name}")
    
    print(f"\n{'='*70}")
    print(f"  Results: {passed}/{total} tests passed")
    print(f"{'='*70}\n")
    
    if passed == total:
        print_success("🎉 TUTTI I TEST PASSATI! Il fix è corretto!")
        return 0
    else:
        print_error("⚠️  Alcuni test sono falliti!")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
