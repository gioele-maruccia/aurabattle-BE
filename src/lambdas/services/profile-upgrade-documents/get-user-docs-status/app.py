import json
import os
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from urllib.parse import urlparse, parse_qs

# === Config ===
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
REGION = os.environ.get('REGION', os.environ.get('AWS_REGION', 'eu-south-1'))
BUCKET_REGION = os.environ.get('BUCKET_REGION', REGION)
TABLE_NAME = os.environ['TABLE_NAME']
BUCKET_NAME = os.environ.get('BUCKET_NAME')

dynamodb = boto3.resource('dynamodb', region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

# Client S3 per HEAD (non influisce sul presign)
s3_head = boto3.client(
    's3',
    region_name=BUCKET_REGION,
    config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
)

# Tipi supportati
# TODO: re-aggiungere 'visura' e 'selfie' quando verranno richiesti di nuovo
# SUPPORTED_DOC_TYPES = ['id_card_front', 'id_card_back', 'passport', 'drivers_license', 'visura', 'selfie']
SUPPORTED_DOC_TYPES = ['id_card_front', 'id_card_back', 'passport', 'drivers_license']

# Solo i parametri validi per get_object che NON introducono header firmati indesiderati
GET_OBJECT_PARAMS_ALLOWLIST = {'Bucket', 'Key'}  # niente Response* per escludere possibili variazioni

def decimal_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError

def presign_get_clean(bucket: str, key: str, region: str, expires: int = 900) -> dict:
    """
    Ritorna dict con:
      - url: presigned GET
      - signed_headers: string (per debug)
    Firmiamo SOLO 'host'. Nessun header extra.
    """
    # HEAD per verificare esistenza (alcuni oggetti SSE-KMS richiedono policy adeguate)
    s3_head.head_object(Bucket=bucket, Key=key)

    presigner = boto3.session.Session().client(
        's3',
        region_name=region,
        config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
    )

    # Costruisci Params solo con allowlist
    params = {'Bucket': bucket, 'Key': key}

    url = presigner.generate_presigned_url(
        ClientMethod='get_object',
        Params=params,
        ExpiresIn=expires,
        HttpMethod='GET'
    )

    # Estrai i SignedHeaders dalla URL per conferma
    q = parse_qs(urlparse(url).query)
    signed_headers = q.get('X-Amz-SignedHeaders', [''])[0]

    # Log diagnostico
    print(f"[PRESIGN] key={key} expires={expires} signed_headers={signed_headers}")

    return {'url': url, 'signed_headers': signed_headers, 'expires': expires}

def _unauth(status, msg):
    return {
        'statusCode': status,
        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
        'body': json.dumps({'error': msg})
    }

def lambda_handler(event, context):
    print("=== LAMBDA START ===")
    print(f"env={ENVIRONMENT} region={REGION}/{BUCKET_REGION} table={TABLE_NAME} bucket={BUCKET_NAME}")
    # Log versione lambda (utile a capire se sei sulla versione aggiornata)
    fn_ver = getattr(context, 'function_version', '$LATEST')
    print(f"function_name={getattr(context, 'function_name', '')} version={fn_ver}")

    # Auth
    claims = (event.get('requestContext', {})
                   .get('authorizer', {})
                   .get('claims') or {})
    sub = claims.get('sub')
    if not sub:
        return _unauth(401, 'Unauthorized')

    path_user = event.get('pathParameters', {}).get('userId')
    if not path_user:
        return _unauth(400, 'Missing userId parameter')

    if path_user != sub:
        return _unauth(403, 'Forbidden: You can only access your own documents')

    # Query Dynamo
    pk = f"USER#{path_user}"
    resp = table.query(KeyConditionExpression=Key('pk').eq(pk) & Key('sk').begins_with('DOC#'))
    items = resp.get('Items', [])

    docs = {}
    for it in items:
        sk = it.get('sk', '')
        parts = sk.split('#')  # DOC#type#ts
        if len(parts) != 3:
            continue
        doc_type = parts[1]
        if doc_type not in SUPPORTED_DOC_TYPES:
            continue
        try:
            ts = int(parts[2])
        except:
            continue
        cur = docs.get(doc_type)
        if (cur is None) or (ts > cur['timestamp']):
            docs[doc_type] = {
                'timestamp': ts,
                'status': it.get('status', 'UNKNOWN'),
                'uploadedAt': it.get('uploadedAt'),
                'fileName': it.get('fileName'),
                's3Key': it.get('s3Key'),
                'lastUpdated': it.get('lastUpdated')
            }

    result = {'userId': path_user, 'documents': {}}

    for doc_type in SUPPORTED_DOC_TYPES:
        if doc_type in docs:
            d = docs[doc_type]
            payload = {
                'status': d['status'],
                'timestamp': d['timestamp'],
                'uploadedAt': d.get('uploadedAt'),
                'lastUpdated': d.get('lastUpdated'),
                'fileName': d.get('fileName'),
                's3Key': d.get('s3Key'),
                'imageUrl': None
            }

            if d['status'] == 'APPROVED' and BUCKET_NAME and d.get('s3Key'):
                try:
                    # usa 900s per coerenza con i log che mostrano 300 (evitiamo incongruenze)
                    pres = presign_get_clean(BUCKET_NAME, d['s3Key'], BUCKET_REGION, expires=900)
                    payload['imageUrl'] = pres['url']
                    payload['urlExpiresIn'] = pres['expires']
                    if ENVIRONMENT != 'prod':
                        payload['debugSignedHeaders'] = pres['signed_headers']
                except Exception as e:
                    print(f"Presign failed for {d['s3Key']}: {e}")
                    payload['error'] = 'Unable to generate download URL'

            result['documents'][doc_type] = payload
        else:
            result['documents'][doc_type] = {
                'status': 'NOT_UPLOADED',
                'timestamp': None,
                'uploadedAt': None,
                'lastUpdated': None,
                'fileName': None,
                's3Key': None,
                'imageUrl': None
            }

    # Summary
    statuses = [x['status'] for x in result['documents'].values() if x['status'] != 'NOT_UPLOADED']
    if not statuses:
        overall = 'NO_DOCUMENTS'
    elif all(s == 'APPROVED' for s in statuses):
        overall = 'ALL_APPROVED'
    elif any(s == 'REJECTED' for s in statuses):
        overall = 'SOME_REJECTED'
    elif any(s in ('AWAITING_REVIEW', 'UNDER_REVIEW') for s in statuses):
        overall = 'UNDER_REVIEW'
    else:
        overall = 'MIXED'

    result['overallStatus'] = overall
    result['totalDocuments'] = len([d for d in result['documents'].values() if d['status'] != 'NOT_UPLOADED'])

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
        'body': json.dumps(result, default=decimal_default)
    }

# Local test
if __name__ == "__main__":
    evt = {
        'pathParameters': {'userId': 'test-user-id'},
        'requestContext': {'authorizer': {'claims': {'sub': 'test-user-id'}}}
    }
    class Ctx:
        function_version = '$LOCAL'
        function_name = 'get-user-docs-status'
    print(lambda_handler(evt, Ctx()))
