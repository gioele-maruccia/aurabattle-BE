"""
Matchups API - WebSocket $connect
Il client si connette a wss://.../{env}?matchupId={id} per ricevere il
conteggio voti in tempo reale mentre guarda un matchup live. Nessuna
autenticazione: il voto e' pubblico (anche ospiti non loggati possono
guardare), la connessione serve solo a "osservare" i numeri aggiornarsi.
"""
import os
import time
import boto3

dynamodb = boto3.resource('dynamodb')
connections_table = dynamodb.Table(os.environ['MATCHUP_CONNECTIONS_TABLE'])


def handler(event, context):
    connection_id = event['requestContext']['connectionId']
    query_params = event.get('queryStringParameters') or {}
    matchup_id = (query_params.get('matchupId') or '').strip()

    if not matchup_id:
        return {'statusCode': 400, 'body': 'matchupId query parameter is required'}

    ttl = int(time.time()) + 86400  # pulizia automatica dopo 24h se il client non disconnette correttamente

    connections_table.put_item(Item={
        'connectionId': connection_id,
        'matchupId': matchup_id,
        'connectedAt': int(time.time()),
        'ttl': ttl,
    })

    return {'statusCode': 200, 'body': 'Connected'}
