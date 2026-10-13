"""
Matchups API - WebSocket $disconnect
Rimuove la connessione da MatchupConnections quando il client si disconnette.
"""
import os
import boto3

dynamodb = boto3.resource('dynamodb')
connections_table = dynamodb.Table(os.environ['MATCHUP_CONNECTIONS_TABLE'])


def handler(event, context):
    connection_id = event['requestContext']['connectionId']
    try:
        connections_table.delete_item(Key={'connectionId': connection_id})
    except Exception as e:
        print(f"[on-disconnect] Warning: could not delete connection {connection_id}: {e}")

    return {'statusCode': 200, 'body': 'Disconnected'}
