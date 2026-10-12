"""
Matchups API - Get Votes
Ritorna i totali voto correnti e lo storico a bucket temporali (per il
grafico "highlights") di un matchup. Endpoint pubblico.
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])
votes_table = dynamodb.Table(os.environ['MATCHUP_VOTES_TABLE'])


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
        matchup_id = event['pathParameters']['matchupId']

        matchup = matchups_table.get_item(Key={'matchup_id': matchup_id}).get('Item')
        if not matchup:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Matchup not found'})

        response = votes_table.query(
            KeyConditionExpression=Key('matchup_id').eq(matchup_id) & Key('sk').begins_with('BUCKET#')
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
            'votes_a': int(matchup.get('votes_a', 0)),
            'votes_b': int(matchup.get('votes_b', 0)),
            'timeseries': timeseries,
        })

    except Exception as e:
        print(f"[get-votes] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
