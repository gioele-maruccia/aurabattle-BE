"""
Battles API - Set Battle Live
Triggerata da EventBridge Scheduler all'orario di event_datetime della battle.
Passa lo status da 'published' a 'live'. La ConditionExpression garantisce
che non tocchi mai una battle già 'live' o 'closed' (es. host che l'ha
chiusa manualmente in anticipo, o schedule rimasto orfano).
"""
import os
import boto3
from datetime import datetime
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])


def handler(event, context):
    battle_id = event.get('battle_id')
    if not battle_id:
        print(f"[set-battle-live] Missing battle_id in event: {event}")
        return

    try:
        battles_table.update_item(
            Key={'battle_id': battle_id},
            UpdateExpression='SET #status = :live, updated_at = :now',
            ConditionExpression='#status = :published',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':live': 'live',
                ':published': 'published',
                ':now': datetime.utcnow().isoformat() + 'Z',
            },
        )
        print(f"[set-battle-live] Battle {battle_id} is now live")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"[set-battle-live] Battle {battle_id} not in 'published' status anymore — skipping")
        else:
            print(f"[set-battle-live] Error updating battle {battle_id}: {e}")
            raise
