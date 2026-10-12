"""
Matchups API - Get Matchup
Recupera un singolo matchup. Endpoint pubblico.
"""
import json
import os
import boto3

dynamodb = boto3.resource('dynamodb')
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])


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

        return _cors_response(200, matchup)

    except Exception as e:
        print(f"[get-matchup] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
