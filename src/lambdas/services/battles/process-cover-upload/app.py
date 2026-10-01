"""
Battles - Process Cover Upload
Triggerata da S3 su ogni oggetto caricato sotto uploads/{battleId}/...
Ridimensiona/comprime a risoluzione standard web (1200x675, cover-fit),
pubblica il risultato su covers/{battleId}.jpg (pubblico) e aggiorna
cover_url sulla battle. Rimuove sempre l'originale caricato.
"""
import io
import os
import time
import urllib.parse
import boto3
from PIL import Image, ImageOps

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])

TARGET_SIZE = (1200, 675)  # stesso standard delle cover di repertorio, 16:9
JPEG_QUALITY = 82
MAX_SOURCE_BYTES = 10 * 1024 * 1024  # scarta file palesemente anomali prima di processarli


def _battle_id_from_key(key):
    # uploads/{battle_id}/{uuid}.{ext}
    parts = key.split('/')
    if len(parts) < 2:
        return None
    return parts[1]


def handler(event, context):
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = urllib.parse.unquote_plus(record['s3']['object']['key'])
        size = record['s3']['object'].get('size', 0)

        print(f"[process-cover-upload] Processing s3://{bucket}/{key} ({size} bytes)")

        battle_id = _battle_id_from_key(key)
        if not battle_id:
            print(f"[process-cover-upload] Could not parse battle_id from key '{key}', skipping")
            continue

        try:
            if size > MAX_SOURCE_BYTES:
                print(f"[process-cover-upload] File too large ({size} bytes), rejecting")
                s3_client.delete_object(Bucket=bucket, Key=key)
                continue

            obj = s3_client.get_object(Bucket=bucket, Key=key)
            source_bytes = obj['Body'].read()

            image = Image.open(io.BytesIO(source_bytes))
            image = ImageOps.exif_transpose(image)  # rispetta l'orientamento EXIF (foto da smartphone)
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Cover-fit: riempie 1200x675 ritagliando l'eccesso, centrato (come CSS object-fit: cover)
            resized = ImageOps.fit(image, TARGET_SIZE, method=Image.LANCZOS, centering=(0.5, 0.5))

            buffer = io.BytesIO()
            resized.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
            buffer.seek(0)

            output_key = f'covers/{battle_id}.jpg'
            s3_client.put_object(
                Bucket=bucket,
                Key=output_key,
                Body=buffer,
                ContentType='image/jpeg',
                CacheControl='public, max-age=31536000, immutable',
            )

            cover_url = f'https://{bucket}.s3.{s3_client.meta.region_name}.amazonaws.com/{output_key}?v={int(time.time())}'

            battles_table.update_item(
                Key={'battle_id': battle_id},
                UpdateExpression='SET cover_url = :url, updated_at = :now REMOVE cover',
                ExpressionAttributeValues={
                    ':url': cover_url,
                    ':now': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                }
            )

            print(f"[process-cover-upload] Done: battle {battle_id} -> {cover_url}")

        except Exception as e:
            print(f"[process-cover-upload] Error processing {key}: {e}")

        finally:
            # L'originale caricato non serve più in nessun caso (successo, scarto o errore)
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except Exception as cleanup_error:
                print(f"[process-cover-upload] Warning: could not delete {key}: {cleanup_error}")
