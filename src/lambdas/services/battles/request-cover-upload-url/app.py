"""
Battles API - Request Cover Upload URL
Genera una presigned URL per caricare una copertina custom su S3.
Solo l'host della battle può richiederla. Il resize avviene async
(process-cover-upload, triggerato da S3) dopo il caricamento.
"""
import json
import os
import uuid
import boto3
from botocore.config import Config

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])

BUCKET_NAME = os.environ['BATTLE_COVERS_BUCKET']
REGION = os.environ.get('AWS_REGION', 'eu-south-1')

s3_client = boto3.client(
    's3',
    region_name=REGION,
    config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'}),
)

ALLOWED_CONTENT_TYPES = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB - limite "di sicurezza" sull'originale, non sul risultato finale
UPLOAD_URL_EXPIRES_SECONDS = 300


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'POST,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        battle_id = event['pathParameters']['battleId']
        body = json.loads(event.get('body') or '{}')

        battle = battles_table.get_item(Key={'battle_id': battle_id}).get('Item')
        if not battle:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Battle not found'})

        if battle['host_id'] != user_id:
            return _cors_response(403, {'error': 'Forbidden', 'message': 'Only the host can upload a cover for this battle'})

        content_type = body.get('content_type')
        extension = ALLOWED_CONTENT_TYPES.get(content_type)
        if not extension:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': f'content_type must be one of: {", ".join(ALLOWED_CONTENT_TYPES.keys())}'
            })

        upload_key = f'uploads/{battle_id}/{uuid.uuid4()}.{extension}'

        upload_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': upload_key,
                'ContentType': content_type,
            },
            ExpiresIn=UPLOAD_URL_EXPIRES_SECONDS,
        )

        return _cors_response(200, {
            'upload_url': upload_url,
            'upload_key': upload_key,
            'expires_in': UPLOAD_URL_EXPIRES_SECONDS,
            'max_upload_bytes': MAX_UPLOAD_BYTES,
            'message': (
                'Carica il file con PUT su upload_url (header Content-Type uguale a quello dichiarato qui). '
                'Il resize avviene in automatico: GET /battles/{battleId} mostrerà cover_url '
                'una volta completata l\'elaborazione (in genere entro pochi secondi).'
            ),
        })

    except Exception as e:
        print(f"[request-cover-upload-url] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
