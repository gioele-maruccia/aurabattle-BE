"""
Battles API - Create Battle
Crea una nuova battle. L'utente autenticato ne diventa l'host.
"""
import json
import os
import uuid
import boto3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

scheduler_client = boto3.client('scheduler')
SCHEDULER_ROLE_ARN = os.environ['SCHEDULER_ROLE_ARN']
SET_BATTLE_LIVE_FUNCTION_ARN = os.environ['SET_BATTLE_LIVE_FUNCTION_ARN']
SET_BATTLE_CLOSED_FUNCTION_ARN = os.environ['SET_BATTLE_CLOSED_FUNCTION_ARN']

REQUIRED_FIELDS = ['title', 'event_datetime', 'location', 'latitude', 'longitude']

ALLOWED_COVERS = {
    'arena', 'crowd', 'soundwave', 'turntable', 'mic',
    'versus', 'city', 'street', 'spark', 'aura',
}


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


def _parse_coordinate(value, min_value, max_value):
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None
    if decimal_value < min_value or decimal_value > max_value:
        return None
    return decimal_value


def _parse_stream_url(value):
    """Valida l'URL dello stream (YouTube/Twitch/altro). Nessuna verifica di
    dominio stretta: basta che sia un link http(s) valido, per non accoppiare
    il backend a un elenco di piattaforme supportate.

    Ritorna (stream_url, errore). `(None, None)` significa "nessuno stream".
    """
    if value is None or value == '':
        return None, None
    if not isinstance(value, str) or not value.startswith(('http://', 'https://')):
        return None, 'stream_url must be a valid http(s) URL'
    return value, None


def _parse_cover(value):
    """Valida la chiave della cover di repertorio.

    Ritorna (cover, errore). `(None, None)` significa "nessuna copertina":
    l'attributo non va scritto affatto.
    """
    if value is None or value == '':
        return None, None
    if not isinstance(value, str) or value not in ALLOWED_COVERS:
        return None, f'cover must be one of: {", ".join(sorted(ALLOWED_COVERS))}'
    return value, None


def _parse_iso_datetime(value):
    """Parsa un datetime ISO 8601 e lo normalizza in UTC. Un valore senza
    fuso e' considerato UTC. Ritorna None se non e' parsabile.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_end_datetime(value, event_datetime):
    """Valida l'orario di fine (opzionale): ISO 8601, dopo l'inizio e nel
    futuro. Ritorna (end_datetime, errore); `(None, None)` significa "nessuna
    fine": l'attributo non va scritto affatto e la battle non si chiude da sola.
    """
    if value is None or value == '':
        return None, None

    end = _parse_iso_datetime(value)
    if end is None:
        return None, 'end_datetime must be a valid ISO 8601 date-time'

    start = _parse_iso_datetime(event_datetime)
    if start is not None and end <= start:
        return None, 'end_datetime must be after event_datetime'
    if end <= datetime.now(timezone.utc):
        return None, 'end_datetime must be in the future'
    return value, None


def _create_schedule(name, function_arn, battle_id, when_iso):
    scheduled_at = _parse_iso_datetime(when_iso).strftime('%Y-%m-%dT%H:%M:%S')
    scheduler_client.create_schedule(
        Name=f'{name}-{battle_id}',
        ScheduleExpression=f'at({scheduled_at})',
        ScheduleExpressionTimezone='UTC',
        FlexibleTimeWindow={'Mode': 'OFF'},
        Target={
            'Arn': function_arn,
            'RoleArn': SCHEDULER_ROLE_ARN,
            'Input': json.dumps({'battle_id': battle_id}),
        },
        ActionAfterCompletion='DELETE',
    )


def _schedule_live_transition(battle_id, event_datetime):
    """Registra uno schedule one-time EventBridge che a event_datetime
    invoca set-battle-live per passare la battle a 'live' (e aprirne i
    matchup). Best-effort: se event_datetime e' nel passato (o altro errore),
    la creazione della battle non deve fallire per questo.
    """
    try:
        _create_schedule('battle-live', SET_BATTLE_LIVE_FUNCTION_ARN, battle_id, event_datetime)
    except Exception as e:
        print(f"[create-battle] Warning: could not schedule live-transition for {battle_id}: {e}")


def _schedule_close_transition(battle_id, end_datetime):
    """Come sopra, ma a end_datetime: set-battle-closed chiude la battle e i
    suoi matchup. Best-effort per lo stesso motivo.
    """
    try:
        _create_schedule('battle-close', SET_BATTLE_CLOSED_FUNCTION_ARN, battle_id, end_datetime)
    except Exception as e:
        print(f"[create-battle] Warning: could not schedule close-transition for {battle_id}: {e}")


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        body = json.loads(event.get('body') or '{}', parse_float=Decimal)

        missing = [f for f in REQUIRED_FIELDS if body.get(f) is None or body.get(f) == '']
        if missing:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': f'Missing required fields: {", ".join(missing)}'
            })

        latitude = _parse_coordinate(body['latitude'], -90, 90)
        if latitude is None:
            return _cors_response(400, {'error': 'Bad Request', 'message': 'latitude must be a number between -90 and 90'})

        longitude = _parse_coordinate(body['longitude'], -180, 180)
        if longitude is None:
            return _cors_response(400, {'error': 'Bad Request', 'message': 'longitude must be a number between -180 and 180'})

        cover, cover_error = _parse_cover(body.get('cover'))
        if cover_error:
            return _cors_response(400, {'error': 'Bad Request', 'message': cover_error})

        stream_url, stream_url_error = _parse_stream_url(body.get('stream_url'))
        if stream_url_error:
            return _cors_response(400, {'error': 'Bad Request', 'message': stream_url_error})

        end_datetime, end_datetime_error = _parse_end_datetime(
            body.get('end_datetime'), body['event_datetime']
        )
        if end_datetime_error:
            return _cors_response(400, {'error': 'Bad Request', 'message': end_datetime_error})

        now = datetime.utcnow().isoformat() + 'Z'
        battle_id = str(uuid.uuid4())

        battle = {
            'battle_id': battle_id,
            'host_id': user_id,
            'title': body['title'],
            'description': body.get('description', ''),
            'location': body['location'],
            'latitude': latitude,
            'longitude': longitude,
            'event_datetime': body['event_datetime'],
            'status': 'published',
            'created_at': now,
            'updated_at': now,
        }

        if cover:
            battle['cover'] = cover

        if stream_url:
            battle['stream_url'] = stream_url

        if end_datetime:
            battle['end_datetime'] = end_datetime

        battles_table.put_item(Item=battle)

        # Aggiorna il contatore denormalizzato sul profilo utente (best-effort)
        try:
            user_profiles_table.update_item(
                Key={'user_id': user_id},
                UpdateExpression='ADD hosted_battles_count :inc',
                ExpressionAttributeValues={':inc': 1}
            )
        except Exception as e:
            print(f"[create-battle] Warning: could not update hosted_battles_count: {e}")

        _schedule_live_transition(battle_id, battle['event_datetime'])
        if end_datetime:
            _schedule_close_transition(battle_id, end_datetime)

        return _cors_response(201, battle)

    except Exception as e:
        print(f"[create-battle] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
