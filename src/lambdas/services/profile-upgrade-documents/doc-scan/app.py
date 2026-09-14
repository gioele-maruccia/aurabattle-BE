import os
import json
import boto3
import urllib.parse
import os.path as path
from typing import Tuple

dynamo = boto3.client('dynamodb')

TABLE_NAME = os.environ['TABLE_NAME']

# Parametri "policy" minimi per MVP
ALLOWED_EXTS = {'.jpg', '.jpeg', '.png', '.pdf'}
MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
FORBIDDEN_SUBSTRINGS = ['..', '%00']


def update_status(pk: str, sk: str, status: str, reason: str | None = None):
    expr = "SET #st = :s"
    names = {"#st": "status"}
    vals = {":s": {"S": status}}
    if reason:
        expr += ", #rs = :r"
        names["#rs"] = "reason"
        vals[":r"] = {"S": reason}

    dynamo.update_item(
        TableName=TABLE_NAME,
        Key={
            'pk': {'S': pk},
            'sk': {'S': sk}
        },
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=vals,
    )

def _parse_pk_sk_from_key(s3_key: str):
    """
    Example S3 key:
      docs/USER123/1757399658891_id_card_front.png

    Returns:
      pk = USER#USER123
      sk = DOC#id_card_front#1757399658891
    """
    parts = s3_key.split("/")
    if len(parts) < 3 or parts[0] != "docs":
        raise ValueError(f"Unexpected key format: {s3_key}")

    user_sub = parts[1]
    filename_no_ext = parts[-1].rsplit(".", 1)[0]  # "1757399658891_id_card_front"

    # Split into timestamp and doc name
    try:
        ts, doc_name = filename_no_ext.split("_", 1)
    except ValueError:
        raise ValueError(f"Filename does not match <ts>_<doc>: {filename_no_ext}")

    pk = f"USER#{user_sub}"
    sk = f"DOC#{doc_name}#{ts}"
    return pk, sk

def _has_double_extension(filename: str) -> bool:
    # Es: "id.pdf.exe" => True
    parts = filename.lower().split('.')
    return len(parts) > 2

def scan(key: str, size: int | None) -> Tuple[bool, str | None]:
    """
    Ritorna (is_clean, reason_if_blocked)
    """
    # 1) whitelist estensioni
    ext = path.splitext(key)[1].lower()
    if ext not in ALLOWED_EXTS:
        return False, f"extension_not_allowed:{ext}"

    # 2) doppia estensione
    filename = path.basename(key)
    if _has_double_extension(filename):
        # Consenti casi leciti come ".tar.gz"? Non in MVP: blocchiamo.
        return False, "double_extension_detected"

    # 3) blacklist substrings nel path
    lowered = key.lower()
    if any(bad in lowered for bad in FORBIDDEN_SUBSTRINGS):
        return False, "suspicious_name"

    # 4) dimensione massima (se disponibile nell'evento)
    if size is not None and size > MAX_SIZE_BYTES:
        return False, "file_too_large"

    # 5) no spazi/pattern strani inizio/fine filename
    if filename != filename.strip() or '  ' in filename:
        return False, "suspicious_whitespace"

    return True, None

def lambda_handler(event, context):
    detail = event.get('detail') or {}
    obj = detail.get('object') or {}
    size = detail.get('size')
    obj_key = obj.get('key')
    if not obj_key:
        return {"ok": True, "skipped": True}
    
    key = urllib.parse.unquote_plus(obj_key)
    
    pk, sk = _parse_pk_sk_from_key(key)
    
    # Stato intermedio (utile per audit nel DDB)
    update_status(pk, sk, "SCANNING")

    is_clean, reason  = scan(key, size)

    if is_clean:
        update_status(pk, sk, "AWAITING_REVIEW")
        return {"ok": True, "result": "clean"}
    else:
        update_status(pk, sk, "REJECTED", reason=reason or "policy_violation")
        return {"ok": True, "result": "infected", "reason": reason}
