"""
Lambda Function: Verify Face
Verifica che il selfie contenga un volto reale e che corrisponda
al volto presente nel documento d'identità (id_card_front).

FLUSSO:
1. Frontend carica id_card_front (documento identità fronte)
2. Frontend acquisisce selfie e lo invia a questa API (base64 o S3 key)
3. Questa Lambda:
   a) DetectFaces sul selfie → verifica che ci sia un volto umano
   b) CompareFaces tra selfie e id_card_front → verifica match >= soglia
4. Se OK → Frontend procede con upload definitivo del selfie
5. Se FAIL → Frontend mostra errore e richiede nuovo selfie

ENDPOINT: POST /documents/verify-face
"""

import json
import os
import logging
import base64
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal
from PIL import Image
import io

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
REGION = os.environ.get("REGION", "eu-south-1")
# NOTA: Rekognition NON è disponibile in eu-south-1 (Milano)
# Usiamo eu-west-1 (Irlanda) per Rekognition, il più vicino con supporto
REKOGNITION_REGION = os.environ.get("REKOGNITION_REGION", "eu-west-1")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "beezey-dev-user-documents")
TABLE_NAME = os.environ.get("TABLE_NAME", "dev-UserDocuments")
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "80.0"))

# Error codes mapping (from ERROR_CODES.json - verify-face service)
ERROR_CODES_MAP = {
    "FACE_VERIFIED": 1001,
    "FACE_VERIFICATION_FAILED": 2001,
    "IMAGE_TOO_LARGE": 2002,
    "INVALID_IMAGE_FORMAT": 2003,
    "FACE_NOT_DETECTED": 2004,
    "MULTIPLE_FACES_DETECTED": 2005,
    "FACE_SIMILARITY_LOW": 2006,
    "REKOGNITION_ERROR": 5001,
    "INTERNAL_ERROR": 5002
}

# AWS Clients
# Rekognition usa eu-west-1 (non disponibile in eu-south-1)
rekognition = boto3.client("rekognition", region_name=REKOGNITION_REGION)
# S3 e DynamoDB usano la region principale (eu-south-1)
s3 = boto3.client("s3", region_name=REGION)
dynamodb = boto3.client("dynamodb", region_name=REGION)


def _resize_image_if_needed(image_bytes: bytes, max_size: int = 4 * 1024 * 1024) -> bytes:
    """
    Ridimensiona l'immagine se supera la dimensione massima consentita.
    Rekognition accetta max 5MB per immagini passate come bytes, usiamo 4MB per sicurezza.
    
    Args:
        image_bytes: bytes dell'immagine originale
        max_size: dimensione massima in bytes (default 4MB)
    
    Returns:
        bytes: immagine ridimensionata se necessario, altrimenti originale
    """
    try:
        current_size = len(image_bytes)
        
        if current_size <= max_size:
            logger.info(f"Image size OK: {current_size} bytes")
            return image_bytes
        
        logger.warning(f"Image too large ({current_size} bytes), resizing...")
        
        # Apri l'immagine
        img = Image.open(io.BytesIO(image_bytes))
        
        # Converti a RGB se necessario (alcune immagini possono essere in RGBA, CMYK, etc.)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        # Calcola il fattore di ridimensionamento per raggiungere circa max_size
        # Riduciamo al 60% della dimensione target per avere margine
        target_size = max_size * 0.6
        scale_factor = (target_size / current_size) ** 0.5
        
        new_width = int(img.width * scale_factor)
        new_height = int(img.height * scale_factor)
        
        logger.info(f"Resizing from {img.width}x{img.height} to {new_width}x{new_height}")
        
        # Ridimensiona con antialiasing di alta qualità
        img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Salva in un buffer con qualità ottimizzata
        buffer = io.BytesIO()
        img_resized.save(buffer, format='JPEG', quality=85, optimize=True)
        resized_bytes = buffer.getvalue()
        
        logger.info(f"Image resized successfully: {len(resized_bytes)} bytes")
        
        return resized_bytes
        
    except Exception as e:
        logger.error(f"Error resizing image: {e}")
        # Se il ridimensionamento fallisce, ritorna l'originale
        return image_bytes


def _resp(status: int, body: dict) -> dict:
    """Build API Gateway response."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
        },
        "body": json.dumps(body, default=str),
    }


def _build_error_response(error_code_key: str, message: str, details: dict = None) -> dict:
    """Build error response with unique error code."""
    code = ERROR_CODES_MAP.get(error_code_key, 5002)  # Default to INTERNAL_ERROR
    body = {
        "success": False,
        "code": code,
        "error_code": error_code_key,
        "message": message
    }
    if details:
        body["details"] = details
    return body


def _build_success_response(success_data: dict) -> dict:
    """Build success response with unique code."""
    body = {
        "success": True,
        "code": 1001,  # FACE_VERIFIED
        **success_data
    }
    return body


def _get_user_document_s3_key(user_sub: str, doc_type: str) -> str | None:
    """
    Recupera l'S3 key del documento più recente di un certo tipo per l'utente.
    Cerca in DynamoDB i record con pk=USER#{user_sub} e sk che inizia con DOC#{doc_type}
    """
    try:
        response = dynamodb.query(
            TableName=TABLE_NAME,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": {"S": f"USER#{user_sub}"},
                ":sk_prefix": {"S": f"DOC#{doc_type}#"},
            },
            ScanIndexForward=False,  # Ordine decrescente (più recente prima)
            Limit=1,
        )
        
        items = response.get("Items", [])
        if not items:
            logger.warning(f"No {doc_type} document found for user {user_sub}")
            return None
        
        item = items[0]
        s3_key = item.get("s3Key", {}).get("S")
        status = item.get("status", {}).get("S")
        
        # Verifica che il documento sia in uno stato valido (non REJECTED, non EXPIRED)
        if status in ["REJECTED", "EXPIRED"]:
            logger.warning(f"Document {doc_type} has invalid status: {status}")
            return None
            
        return s3_key
        
    except ClientError as e:
        logger.error(f"DynamoDB error: {e}")
        return None


def _detect_faces_in_image(image_bytes: bytes) -> dict:
    """
    Rileva volti in un'immagine usando Rekognition DetectFaces.
    
    Returns:
        dict con:
        - has_face: bool
        - face_count: int
        - confidence: float (confidenza del volto principale)
        - details: dict con attributi del volto
    """
    try:
        response = rekognition.detect_faces(
            Image={"Bytes": image_bytes},
            Attributes=["ALL"]  # Ottieni tutti gli attributi per validazione
        )
        
        face_details = response.get("FaceDetails", [])
        
        if not face_details:
            return {
                "has_face": False,
                "face_count": 0,
                "confidence": 0.0,
                "details": None,
                "error": None
            }
        
        # Prendi il volto con maggiore confidenza
        primary_face = max(face_details, key=lambda f: f.get("Confidence", 0))
        
        return {
            "has_face": True,
            "face_count": len(face_details),
            "confidence": primary_face.get("Confidence", 0),
            "details": {
                "age_range": primary_face.get("AgeRange"),
                "smile": primary_face.get("Smile"),
                "eyeglasses": primary_face.get("Eyeglasses"),
                "sunglasses": primary_face.get("Sunglasses"),
                "eyes_open": primary_face.get("EyesOpen"),
                "mouth_open": primary_face.get("MouthOpen"),
                "quality": primary_face.get("Quality"),
                "pose": primary_face.get("Pose"),
            },
            "error": None
        }
        
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        logger.error(f"Rekognition DetectFaces error: {error_code}")
        return {
            "has_face": False,
            "face_count": 0,
            "confidence": 0.0,
            "details": None,
            "error": error_code
        }


def _compare_faces(source_bytes: bytes, target_s3_key: str) -> dict:
    """
    Confronta il selfie (source) con il documento d'identità (target) in S3.
    
    NOTA: Dato che Rekognition è in eu-west-1 e S3 è in eu-south-1,
    dobbiamo leggere l'immagine da S3 e passare i bytes a Rekognition.
    
    Returns:
        dict con:
        - match: bool
        - similarity: float (0-100)
        - error: str | None
    """
    try:
        # Leggi l'immagine target da S3 (necessario perché Rekognition è in regione diversa)
        logger.info(f"Reading target image from S3: {BUCKET_NAME}/{target_s3_key}")
        try:
            s3_response = s3.get_object(Bucket=BUCKET_NAME, Key=target_s3_key)
            target_bytes = s3_response["Body"].read()
            logger.info(f"Target image loaded, size: {len(target_bytes)} bytes")
        except ClientError as s3_error:
            error_code = s3_error.response["Error"]["Code"]
            logger.error(f"S3 GetObject error: {error_code} for key {target_s3_key}")
            return {
                "match": False,
                "similarity": 0.0,
                "error": f"S3_{error_code}",
                "reason": f"Cannot read target image: {error_code}"
            }
        
        # Ridimensiona le immagini se necessario per Rekognition
        logger.info("Resizing images if needed for Rekognition...")
        source_bytes_resized = _resize_image_if_needed(source_bytes)
        target_bytes_resized = _resize_image_if_needed(target_bytes)
        
        response = rekognition.compare_faces(
            SourceImage={"Bytes": source_bytes_resized},
            TargetImage={"Bytes": target_bytes_resized},
            SimilarityThreshold=SIMILARITY_THRESHOLD,
            QualityFilter="AUTO"  # Filtra automaticamente immagini di bassa qualità
        )
        
        face_matches = response.get("FaceMatches", [])
        unmatched_faces = response.get("UnmatchedFaces", [])
        
        if not face_matches:
            # Nessun match trovato sopra la soglia
            return {
                "match": False,
                "similarity": 0.0,
                "unmatched_count": len(unmatched_faces),
                "error": None,
                "reason": "no_match_above_threshold"
            }
        
        # Prendi il match con la similarità più alta
        best_match = max(face_matches, key=lambda m: m.get("Similarity", 0))
        similarity = best_match.get("Similarity", 0)
        
        return {
            "match": similarity >= SIMILARITY_THRESHOLD,
            "similarity": round(similarity, 2),
            "unmatched_count": len(unmatched_faces),
            "error": None,
            "reason": None
        }
        
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"Rekognition CompareFaces error: {error_code} - {error_msg}")
        
        # Gestisci errori specifici
        if error_code == "InvalidParameterException":
            if "no faces" in error_msg.lower():
                return {
                    "match": False,
                    "similarity": 0.0,
                    "error": "no_face_in_document",
                    "reason": "Il documento non contiene un volto riconoscibile"
                }
        
        return {
            "match": False,
            "similarity": 0.0,
            "error": error_code,
            "reason": error_msg
        }


def _validate_image_quality(face_details: dict) -> tuple[bool, str | None]:
    """
    Valida la qualità dell'immagine del selfie.
    
    Returns:
        tuple (is_valid, error_message)
    """
    if not face_details:
        return False, "Nessun dettaglio volto disponibile"
    
    quality = face_details.get("quality", {})
    pose = face_details.get("pose", {})
    eyes_open = face_details.get("eyes_open", {})
    
    # Verifica qualità minima
    if quality:
        brightness = quality.get("Brightness", 100)
        sharpness = quality.get("Sharpness", 100)
        
        if brightness < 20:
            return False, "Immagine troppo scura. Riprova con più luce."
        if brightness > 95:
            return False, "Immagine troppo luminosa. Riduci l'esposizione."
        if sharpness < 20:
            return False, "Immagine sfocata. Mantieni il telefono fermo."
    
    # Verifica posa (volto troppo inclinato)
    if pose:
        yaw = abs(pose.get("Yaw", 0))
        pitch = abs(pose.get("Pitch", 0))
        
        if yaw > 30:
            return False, "Volto troppo ruotato. Guarda dritto verso la fotocamera."
        if pitch > 25:
            return False, "Volto troppo inclinato. Mantieni la testa dritta."
    
    # Verifica occhi aperti
    if eyes_open:
        if not eyes_open.get("Value", True) and eyes_open.get("Confidence", 0) > 80:
            return False, "Occhi chiusi rilevati. Mantieni gli occhi aperti."
    
    return True, None


def lambda_handler(event, context):
    """
    Handler principale.
    
    INPUT (body JSON):
    {
        "selfie_base64": "base64_encoded_image_data",  // Selfie come base64
        // OPPURE
        "selfie_s3_key": "docs/user123/timestamp_selfie.jpg"  // S3 key se già caricato
    }
    
    OUTPUT SUCCESS (200):
    {
        "success": true,
        "verification": {
            "face_detected": true,
            "face_confidence": 99.5,
            "face_match": true,
            "similarity": 95.2,
            "quality_check": "passed"
        },
        "message": "Verifica completata con successo"
    }
    
    OUTPUT ERROR (4xx):
    {
        "success": false,
        "error_code": "FACE_NOT_DETECTED" | "FACE_MISMATCH" | "QUALITY_CHECK_FAILED" | ...,
        "message": "Descrizione errore per l'utente",
        "details": { ... }
    }
    """
    logger.info(f"Event: {json.dumps(event, default=str)}")

    # ==========================================================================
    # TODO: verify-face temporaneamente DISABILITATO
    # Il selfie è stato rimosso dal flusso di profile-upgrade (worker e company).
    # Restituisce successo bypass per non bloccare chiamate residue dal frontend.
    # Re-abilitare rimuovendo questo blocco quando il selfie sarà di nuovo richiesto.
    # ==========================================================================
    if event.get("httpMethod") != "OPTIONS":
        return _resp(200, _build_success_response({
            "verification": {
                "face_detected": True,
                "face_confidence": 99.0,
                "face_match": True,
                "similarity": 99.0,
                "quality_check": "bypassed",
                "threshold_used": 0
            },
            "message": "Verifica selfie temporaneamente disabilitata."
        }))

    try:
        # Handle CORS preflight
        if event.get("httpMethod") == "OPTIONS":
            return _resp(200, {"message": "OK"})
        
        # Extract user from JWT claims
        claims = (event.get("requestContext", {})
                  .get("authorizer", {})
                  .get("claims", {}))
        
        user_sub = claims.get("sub")
        
        if not user_sub:
            logger.warning("Missing user sub in JWT claims")
            return _resp(401, {
                "code": 2001,
                "success": False,
                "error_code": "UNAUTHORIZED",
                "message": "Autenticazione richiesta"
            })
        
        # Parse body
        body_raw = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            body_raw = base64.b64decode(body_raw).decode("utf-8")
        
        try:
            body = json.loads(body_raw)
        except json.JSONDecodeError as e:
            return _resp(400, {
                "code": 2003,
                "success": False,
                "error_code": "INVALID_JSON",
                "message": "Corpo della richiesta non valido"
            })
        
        # Get selfie image bytes
        selfie_bytes = None
        
        if "selfie_base64" in body:
            try:
                selfie_bytes = base64.b64decode(body["selfie_base64"])
            except Exception as e:
                return _resp(400, {
                    "code": 2003,
                    "success": False,
                    "error_code": "INVALID_BASE64",
                    "message": "Immagine selfie non valida"
                })
        elif "selfie_s3_key" in body:
            try:
                response = s3.get_object(Bucket=BUCKET_NAME, Key=body["selfie_s3_key"])
                selfie_bytes = response["Body"].read()
            except ClientError as e:
                return _resp(400, {                    "code": 2001,                    "success": False,
                    "error_code": "SELFIE_NOT_FOUND",
                    "message": "Selfie non trovato in S3"
                })
        else:
            return _resp(400, {
                "code": 2001,
                "success": False,
                "error_code": "MISSING_SELFIE",
                "message": "Selfie richiesto (selfie_base64 o selfie_s3_key)"
            })
        
        # Validate image size (max 5MB for Rekognition when using bytes)
        if len(selfie_bytes) > 5 * 1024 * 1024:
            return _resp(400, {
                "code": 2002,
                "success": False,
                "error_code": "IMAGE_TOO_LARGE",
                "message": "Immagine troppo grande. Massimo 5MB."
            })
        
        # ============================================
        # STEP 1: Detect faces in selfie
        # ============================================
        logger.info(f"Step 1: Detecting faces in selfie for user {user_sub}")
        
        face_result = _detect_faces_in_image(selfie_bytes)
        
        if face_result.get("error"):
            return _resp(500, {
                "code": 5001,
                "success": False,
                "error_code": "REKOGNITION_ERROR",
                "message": "Errore durante l'analisi del volto",
                "details": {"error": face_result["error"]}
            })
        
        if not face_result["has_face"]:
            return _resp(400, {
                "code": 2004,
                "success": False,
                "error_code": "FACE_NOT_DETECTED",
                "message": "Nessun volto rilevato nel selfie. Assicurati che il tuo viso sia ben visibile."
            })
        
        if face_result["face_count"] > 1:
            return _resp(400, {
                "code": 2005,
                "success": False,
                "error_code": "MULTIPLE_FACES",
                "message": "Rilevati più volti. Assicurati di essere solo tu nell'inquadratura."
            })
        
        # ============================================
        # STEP 2: Validate image quality
        # ============================================
        logger.info(f"Step 2: Validating image quality for user {user_sub}")
        
        is_quality_ok, quality_error = _validate_image_quality(face_result["details"])
        
        if not is_quality_ok:
            return _resp(400, {
                "code": 2001,
                "success": False,
                "error_code": "QUALITY_CHECK_FAILED",
                "message": quality_error,
                "details": {
                    "quality": face_result["details"].get("quality"),
                    "pose": face_result["details"].get("pose")
                }
            })
        
        # ============================================
        # STEP 3: Get ID card front from S3
        # ============================================
        logger.info(f"Step 3: Getting id_card_front for user {user_sub}")
        
        id_card_s3_key = _get_user_document_s3_key(user_sub, "id_card_front")
        
        if not id_card_s3_key:
            return _resp(400, {
                "code": 2001,
                "success": False,
                "error_code": "ID_CARD_NOT_FOUND",
                "message": "Documento d'identità (fronte) non trovato. Carica prima il documento."
            })
        
        # ============================================
        # STEP 4: Compare faces
        # ============================================
        logger.info(f"Step 4: Comparing selfie with id_card_front for user {user_sub}")
        
        compare_result = _compare_faces(selfie_bytes, id_card_s3_key)
        
        if compare_result.get("error"):
            if compare_result["error"] == "no_face_in_document":
                return _resp(400, {
                    "code": 2004,
                    "success": False,
                    "error_code": "NO_FACE_IN_DOCUMENT",
                    "message": "Nessun volto riconoscibile nel documento d'identità. Carica un'immagine più chiara."
                })
            
            return _resp(500, {
                "code": 5001,
                "success": False,
                "error_code": "COMPARISON_ERROR",
                "message": "Errore durante il confronto dei volti",
                "details": {"error": compare_result["error"]}
            })
        
        if not compare_result["match"]:
            return _resp(400, {
                "code": 2006,
                "success": False,
                "error_code": "FACE_MISMATCH",
                "message": f"Il volto nel selfie non corrisponde al documento. Similarità: {compare_result['similarity']}%",
                "details": {
                    "similarity": compare_result["similarity"],
                    "threshold": SIMILARITY_THRESHOLD
                }
            })
        
        # ============================================
        # SUCCESS - All checks passed!
        # ============================================
        logger.info(f"Verification successful for user {user_sub}. Similarity: {compare_result['similarity']}%")
        
        return _resp(200, _build_success_response({
            "verification": {
                "face_detected": True,
                "face_confidence": round(face_result["confidence"], 2),
                "face_match": True,
                "similarity": compare_result["similarity"],
                "quality_check": "passed",
                "threshold_used": SIMILARITY_THRESHOLD
            },
            "message": "Verifica completata con successo. Puoi procedere con il caricamento."
        }))
        
    except Exception as e:
        logger.exception("Unhandled error in verify-face Lambda")
        return _resp(500, _build_error_response(
            "INTERNAL_ERROR",
            "Errore interno del server"
        ))
