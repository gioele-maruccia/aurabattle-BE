import json
import os
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "eu-south-1")
BUCKET = os.environ["BUCKET"]
TABLE_NAME = os.environ["TABLE_NAME"]

s3 = boto3.client("s3", region_name=REGION)
ddb = boto3.client("dynamodb", region_name=REGION)
events = boto3.client("events", region_name=REGION)

def _delete_rule(rule_name):
    """Self-delete the EventBridge rule and its target after execution."""
    if not rule_name:
        return
    try:
        events.remove_targets(Rule=rule_name, Ids=["1"])
    except Exception as e:
        logger.warning(f"Could not remove targets from rule {rule_name}: {e}")
    try:
        events.delete_rule(Name=rule_name)
        logger.info(f"Deleted EventBridge rule: {rule_name}")
    except Exception as e:
        logger.warning(f"Could not delete rule {rule_name}: {e}")

def lambda_handler(event, context):
    """
    Controlla se un file è stato caricato su S3.
    Se non è stato caricato, marca il record DynamoDB come EXPIRED.
    """
    try:
        # Estrai i dati dall'evento EventBridge
        detail = event.get("detail", {})
        pk = detail.get("pk")  # USER#user123
        sk = detail.get("sk")  # DOC#id_card_front#1234567890
        s3_key = detail.get("s3Key")  # docs/user123/1234567890_id_card_front.jpg
        rule_name = detail.get("ruleName")  # cleanup-<timestamp>
       
        if not all([pk, sk, s3_key]):
            logger.error("Missing required fields in event: %s", event)
            return {"statusCode": 400, "body": "Missing required fields"}
       
        logger.info(f"Checking if file exists: {s3_key}")
       
        # Controlla se il file esiste su S3
        try:
            s3.head_object(Bucket=BUCKET, Key=s3_key)
            logger.info(f"File exists: {s3_key} - No action needed")
            _delete_rule(rule_name)
            return {"statusCode": 200, "body": "File uploaded successfully"}
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            # Gestisci sia 404 che 403 come "file non trovato"
            # 403 può essere restituito per oggetti non esistenti in bucket con policy restrittive
            if error_code in ['404', '403']:
                logger.info(f"File not found (error {error_code}): {s3_key} - Marking as EXPIRED")
               
                # Update DynamoDB record status
                try:
                    ddb.update_item(
                        TableName=TABLE_NAME,
                        Key={"pk": {"S": pk}, "sk": {"S": sk}},
                        UpdateExpression="SET #status = :expired_status, expiredAt = :expired_at",
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":expired_status": {"S": "EXPIRED"},
                            ":expired_at": {"S": str(context.aws_request_id)},  # Timestamp di quando è scaduto
                            ":pending_status": {"S": "PENDING"}  # Solo se è ancora PENDING
                        },
                        ConditionExpression="#status = :pending_status"
                    )
                    logger.info(f"Marked as EXPIRED: {pk}#{sk}")
                    _delete_rule(rule_name)
                    return {"statusCode": 200, "body": "Marked as EXPIRED"}
                   
                except ClientError as ddb_error:
                    if ddb_error.response['Error']['Code'] == 'ConditionalCheckFailedException':
                        # Record non è più PENDING (forse è già UPLOADED o EXPIRED)
                        logger.info(f"Record is no longer PENDING: {pk}#{sk}")
                        _delete_rule(rule_name)
                        return {"statusCode": 200, "body": "Record already processed"}
                    else:
                        logger.error(f"DynamoDB error: {ddb_error}")
                        raise ddb_error
            else:
                # Errore S3 diverso da 404/403
                logger.error(f"S3 head_object error {error_code}: {e}")
                raise e
               
    except Exception as e:
        logger.exception("Error processing cleanup")
        return {"statusCode": 500, "body": f"Error: {str(e)}"}