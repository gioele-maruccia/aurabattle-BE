"""
Matchups API - Delete Matchup
Elimina un matchup. Solo l'host della battle può farlo.
"""
import json
import os
import boto3

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'DELETE,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        matchup_id = event['pathParameters']['matchupId']

        existing = matchups_table.get_item(Key={'matchup_id': matchup_id}).get('Item')
        if not existing:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Matchup not found'})

        battle = battles_table.get_item(Key={'battle_id': existing['battle_id']}).get('Item')
        if not battle or battle['host_id'] != user_id:
            return _cors_response(403, {'error': 'Forbidden', 'message': 'Only the host of the battle can delete this matchup'})

        matchups_table.delete_item(Key={'matchup_id': matchup_id})

        return _cors_response(200, {'success': True, 'message': 'Matchup deleted successfully'})

    except Exception as e:
        print(f"[delete-matchup] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
