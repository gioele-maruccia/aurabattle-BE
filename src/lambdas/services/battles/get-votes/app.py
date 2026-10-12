"""
Battles API - Get Votes
Ritorna i totali voto correnti e lo storico a bucket temporali (per il
grafico "highlights"). Endpoint pubblico.
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
votes_table = dynamodb.Table(os.environ['BATTLE_VOTES_TABLE'])


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }


def handler(event, context):
    try:
        battle_id = event['pathParameters']['battleId']

        battle = battles_table.get_item(Key={'battle_id': battle_id}).get('Item')
        if not battle:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Battle not found'})

        response = votes_table.query(
            KeyConditionExpression=Key('battle_id').eq(battle_id) & Key('sk').begins_with('BUCKET#')
        )

        timeseries = [
            {
                'bucket_ts': int(item['bucket_ts']),
                'votes_a': int(item.get('votes_a', 0)),
                'votes_b': int(item.get('votes_b', 0)),
            }
            for item in response.get('Items', [])
        ]
        timeseries.sort(key=lambda b: b['bucket_ts'])

        return _cors_response(200, {
            'votes_a': int(battle.get('votes_a', 0)),
            'votes_b': int(battle.get('votes_b', 0)),
            'timeseries': timeseries,
        })

    except Exception as e:
        print(f"[get-votes] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
