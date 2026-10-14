"""
Matchups API - Cast Vote
Vota per il side A o B di un matchup live. Endpoint pubblico (no auth Cognito):
il chiamante indica un voter_id (lo user_id Cognito se loggato, altrimenti
un ID anonimo generato e persistito dal client). Il backend non verifica
l'identità: voter_id serve solo a far rispettare il cooldown fra un voto e
l'altro, è una misura anti-abuso debole ma sufficiente per l'MVP.

Rate limit: un voto ogni VOTE_COOLDOWN_SECONDS per voter_id+matchup_id.
Ogni voto aggiorna sia il contatore totale sul Matchup sia il bucket
temporale corrente (per lo storico/grafico "highlights").
"""
import json
import os
import time
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])
votes_table = dynamodb.Table(os.environ['MATCHUP_VOTES_TABLE'])
connections_table = dynamodb.Table(os.environ['MATCHUP_CONNECTIONS_TABLE'])
apigw_management = boto3.client('apigatewaymanagementapi', endpoint_url=os.environ['WEBSOCKET_API_ENDPOINT'])

VOTE_COOLDOWN_SECONDS = 3
BUCKET_SECONDS = 15
ALLOWED_SIDES = ('A', 'B')


def _cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'POST,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }


def _broadcast_vote_update(matchup_id, votes_a, votes_b):
    """Spinge il nuovo conteggio a tutti i client connessi al WebSocket per
    questo matchup (best-effort: un errore qui non deve far fallire il voto,
    che e' comunque gia' persistito in DynamoDB).
    """
    try:
        response = connections_table.query(
            IndexName='matchupId-index',
            KeyConditionExpression=Key('matchupId').eq(matchup_id)
        )
    except Exception as e:
        print(f"[cast-vote] Warning: could not query connections for {matchup_id}: {e}")
        return

    payload = json.dumps({
        'action': 'vote_update',
        'matchup_id': matchup_id,
        'votes_a': votes_a,
        'votes_b': votes_b,
    }).encode('utf-8')

    for item in response.get('Items', []):
        connection_id = item['connectionId']
        try:
            apigw_management.post_to_connection(ConnectionId=connection_id, Data=payload)
        except apigw_management.exceptions.GoneException:
            try:
                connections_table.delete_item(Key={'connectionId': connection_id})
            except Exception:
                pass
        except Exception as e:
            print(f"[cast-vote] Warning: could not send to connection {connection_id}: {e}")


def handler(event, context):
    try:
        matchup_id = event['pathParameters']['matchupId']
        body = json.loads(event.get('body') or '{}')

        side = body.get('side')
        if side not in ALLOWED_SIDES:
            return _cors_response(400, {'error': 'Bad Request', 'message': "side must be 'A' or 'B'"})

        voter_id = (body.get('voter_id') or '').strip()
        if not voter_id:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': 'voter_id is required (Cognito sub if logged in, otherwise a client-generated anonymous id)'
            })

        matchup = matchups_table.get_item(Key={'matchup_id': matchup_id}).get('Item')
        if not matchup:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Matchup not found'})

        if matchup.get('status') != 'live':
            return _cors_response(409, {'error': 'Conflict', 'message': 'Voting is only allowed while the matchup is live'})

        now = int(time.time())

        try:
            votes_table.update_item(
                Key={'matchup_id': matchup_id, 'sk': f'RATE#{voter_id}'},
                UpdateExpression='SET last_vote_at = :now',
                ConditionExpression='attribute_not_exists(last_vote_at) OR last_vote_at < :cutoff',
                ExpressionAttributeValues={
                    ':now': now,
                    ':cutoff': now - VOTE_COOLDOWN_SECONDS,
                }
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                return _cors_response(429, {
                    'error': 'Too Many Requests',
                    'message': f'You can vote again in a few seconds (cooldown: {VOTE_COOLDOWN_SECONDS}s)'
                })
            raise

        # Lo stato si ricontrolla nella scrittura, non solo nella lettura sopra:
        # se il matchup viene chiuso nel mezzo, il voto non deve sommarsi a
        # totali su cui il vincitore e' gia' stato calcolato.
        vote_field = 'votes_a' if side == 'A' else 'votes_b'
        try:
            result = matchups_table.update_item(
                Key={'matchup_id': matchup_id},
                UpdateExpression=f'ADD {vote_field} :inc SET updated_at = :now_iso',
                ConditionExpression='#status = :live',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':inc': 1,
                    ':live': 'live',
                    ':now_iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                },
                ReturnValues='ALL_NEW',
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                return _cors_response(409, {'error': 'Conflict', 'message': 'Voting is only allowed while the matchup is live'})
            raise

        updated = result['Attributes']
        _broadcast_vote_update(matchup_id, int(updated.get('votes_a', 0)), int(updated.get('votes_b', 0)))

        bucket = (now // BUCKET_SECONDS) * BUCKET_SECONDS
        try:
            votes_table.update_item(
                Key={'matchup_id': matchup_id, 'sk': f'BUCKET#{bucket:010d}'},
                UpdateExpression=f'ADD {vote_field} :inc SET bucket_ts = :bucket',
                ExpressionAttributeValues={':inc': 1, ':bucket': bucket}
            )
        except Exception as e:
            print(f"[cast-vote] Warning: could not update vote bucket: {e}")

        return _cors_response(200, {'success': True, 'side': side})

    except Exception as e:
        print(f"[cast-vote] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
