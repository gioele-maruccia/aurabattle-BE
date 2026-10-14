"""
Battles API - Update Battle
Aggiorna una battle. Solo l'host può modificarla.
"""
import json
import os
import boto3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

dynamodb = boto3.resource('dynamodb')
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])

scheduler_client = boto3.client('scheduler')
SCHEDULER_ROLE_ARN = os.environ['SCHEDULER_ROLE_ARN']
lambda_client = boto3.client('lambda')
SET_BATTLE_LIVE_FUNCTION_ARN = os.environ['SET_BATTLE_LIVE_FUNCTION_ARN']
SET_BATTLE_CLOSED_FUNCTION_ARN = os.environ['SET_BATTLE_CLOSED_FUNCTION_ARN']

UPDATABLE_FIELDS = ['title', 'description', 'location', 'latitude', 'longitude', 'event_datetime', 'end_datetime', 'status', 'cover', 'stream_url']
ALLOWED_STATUSES = ['published', 'live', 'closed']
STATUS_ORDER = {'published': 0, 'live': 1, 'closed': 2}

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
            'Access-Control-Allow-Methods': 'PUT,OPTIONS',
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


def _delete_schedule(name, battle_id):
    try:
        scheduler_client.delete_schedule(Name=f'{name}-{battle_id}')
    except scheduler_client.exceptions.ResourceNotFoundException:
        pass
    except Exception as e:
        print(f"[update-battle] Warning: could not delete {name} schedule for {battle_id}: {e}")


def _create_schedule(name, function_arn, battle_id, when_iso):
    try:
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
    except Exception as e:
        print(f"[update-battle] Warning: could not create {name} schedule for {battle_id}: {e}")


def _invoke_async(function_arn, battle_id):
    """Fa girare subito set-battle-live / set-battle-closed per una battle
    portata a mano a 'live' / 'closed': sono loro ad aprire / chiudere i
    matchup, cosi' battle e matchup restano coerenti qualunque sia l'origine
    della transizione. Asincrona e best-effort: la risposta dell'host non deve
    aspettare i matchup.
    """
    try:
        lambda_client.invoke(
            FunctionName=function_arn,
            InvocationType='Event',
            Payload=json.dumps({'battle_id': battle_id}).encode('utf-8'),
        )
    except Exception as e:
        print(f"[update-battle] Warning: could not invoke {function_arn} for {battle_id}: {e}")


def handler(event, context):
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        battle_id = event['pathParameters']['battleId']
        body = json.loads(event.get('body') or '{}', parse_float=Decimal)

        existing = battles_table.get_item(Key={'battle_id': battle_id}).get('Item')
        if not existing:
            return _cors_response(404, {'error': 'Not Found', 'message': 'Battle not found'})

        if existing['host_id'] != user_id:
            return _cors_response(403, {'error': 'Forbidden', 'message': 'Only the host can update this battle'})

        if existing.get('moderation_state') == 'removed':
            return _cors_response(403, {
                'error': 'Forbidden',
                'code': 'CONTENT_REMOVED',
                'message': 'This battle was removed for violating the community guidelines',
            })

        if 'status' in body and body['status'] not in ALLOWED_STATUSES:
            return _cors_response(400, {
                'error': 'Bad Request',
                'message': f'status must be one of: {", ".join(ALLOWED_STATUSES)}'
            })

        # Lo stato va solo avanti: tornare indietro lascerebbe i matchup
        # (gia' aperti o chiusi, con stats applicate) incoerenti con la battle.
        current_status = existing.get('status', 'published')
        if 'status' in body and STATUS_ORDER[body['status']] < STATUS_ORDER[current_status]:
            return _cors_response(409, {
                'error': 'Conflict',
                'message': f'status can only move forward (published -> live -> closed), it is {current_status}'
            })

        # Una battle chiusa e' definitiva: si possono ancora correggere testi e
        # copertina, non gli orari, che rimetterebbero in moto gli schedule.
        if current_status == 'closed' and ('event_datetime' in body or 'end_datetime' in body):
            return _cors_response(409, {
                'error': 'Conflict',
                'message': 'The dates of a closed battle cannot be changed'
            })

        if 'event_datetime' in body and _parse_iso_datetime(body['event_datetime']) is None:
            return _cors_response(400, {'error': 'Bad Request', 'message': 'event_datetime must be a valid ISO 8601 date-time'})

        if 'latitude' in body:
            latitude = _parse_coordinate(body['latitude'], -90, 90)
            if latitude is None:
                return _cors_response(400, {'error': 'Bad Request', 'message': 'latitude must be a number between -90 and 90'})
            body['latitude'] = latitude

        if 'longitude' in body:
            longitude = _parse_coordinate(body['longitude'], -180, 180)
            if longitude is None:
                return _cors_response(400, {'error': 'Bad Request', 'message': 'longitude must be a number between -180 and 180'})
            body['longitude'] = longitude

        # cover: null (o stringa vuota) e' gestito piu' sotto come REMOVE.
        # Qui valido solo un valore non vuoto contro la whitelist.
        if 'cover' in body and body['cover'] not in (None, ''):
            if not isinstance(body['cover'], str) or body['cover'] not in ALLOWED_COVERS:
                return _cors_response(400, {
                    'error': 'Bad Request',
                    'message': f'cover must be one of: {", ".join(sorted(ALLOWED_COVERS))}'
                })

        # stream_url: null (o stringa vuota) e' gestito piu' sotto come REMOVE.
        if 'stream_url' in body and body['stream_url'] not in (None, ''):
            if not isinstance(body['stream_url'], str) or not body['stream_url'].startswith(('http://', 'https://')):
                return _cors_response(400, {'error': 'Bad Request', 'message': 'stream_url must be a valid http(s) URL'})

        # end_datetime: null (o stringa vuota) e' gestito piu' sotto come REMOVE.
        # Si valida solo quando cambia: modificare il titolo di una battle con
        # una fine ormai passata non deve fallire per questo.
        if 'end_datetime' in body and body['end_datetime'] not in (None, ''):
            end = _parse_iso_datetime(body['end_datetime'])
            if end is None:
                return _cors_response(400, {'error': 'Bad Request', 'message': 'end_datetime must be a valid ISO 8601 date-time'})
            if end <= datetime.now(timezone.utc):
                return _cors_response(400, {'error': 'Bad Request', 'message': 'end_datetime must be in the future'})

        # La fine deve restare dopo l'inizio, sia che cambi l'una o l'altro.
        if 'end_datetime' in body or 'event_datetime' in body:
            effective_start = _parse_iso_datetime(body.get('event_datetime', existing.get('event_datetime')))
            effective_end_raw = body['end_datetime'] if 'end_datetime' in body else existing.get('end_datetime')
            if effective_end_raw not in (None, '') and effective_start is not None:
                effective_end = _parse_iso_datetime(effective_end_raw)
                if effective_end is not None and effective_end <= effective_start:
                    return _cors_response(400, {'error': 'Bad Request', 'message': 'end_datetime must be after event_datetime'})

        update_parts = []
        remove_parts = []
        expr_values = {':now': datetime.utcnow().isoformat() + 'Z'}
        expr_names = {}

        for field in UPDATABLE_FIELDS:
            if field not in body:
                continue

            # `cover: null` (o stringa vuota) significa "togli la copertina".
            if field == 'cover' and (body[field] is None or body[field] == ''):
                expr_names['#cover'] = 'cover'
                remove_parts.append('#cover')
                continue

            # `stream_url: null` (o stringa vuota) significa "togli lo stream".
            if field == 'stream_url' and (body[field] is None or body[field] == ''):
                expr_names['#stream_url'] = 'stream_url'
                remove_parts.append('#stream_url')
                continue

            # `end_datetime: null` (o stringa vuota) significa "nessuna fine".
            if field == 'end_datetime' and (body[field] is None or body[field] == ''):
                expr_names['#end_datetime'] = 'end_datetime'
                remove_parts.append('#end_datetime')
                continue

            expr_names[f'#{field}'] = field
            update_parts.append(f'#{field} = :{field}')
            expr_values[f':{field}'] = body[field]

            # cover (di repertorio) e cover_url (upload custom) sono mutuamente esclusivi:
            # impostare l'una azzera l'altra.
            if field == 'cover':
                expr_names['#cover_url'] = 'cover_url'
                remove_parts.append('#cover_url')

        if not update_parts and not remove_parts:
            return _cors_response(400, {'error': 'Bad Request', 'message': 'No fields to update'})

        expr_names['#updated_at'] = 'updated_at'
        update_parts.append('#updated_at = :now')

        update_expression = 'SET ' + ', '.join(update_parts)
        if remove_parts:
            update_expression += ' REMOVE ' + ', '.join(remove_parts)

        result = battles_table.update_item(
            Key={'battle_id': battle_id},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names,
            ReturnValues='ALL_NEW',
        )

        updated = result['Attributes']

        # Mantiene in sincrono gli schedule EventBridge:
        # - 'live': se la battle non e' (piu') 'published' non serve, lo
        #   cancella; se resta 'published' ma l'orario e' cambiato, lo ricrea.
        #   Un inizio spostato a un orario gia' passato non si schedula (uno
        #   schedule at() nel passato non e' garantito che scatti): la battle
        #   parte subito.
        # - 'close': non serve piu' se la battle e' chiusa o ha perso la fine;
        #   se la fine e' cambiata lo ricrea (la battle puo' essere gia' live).
        starts_now = False
        if updated.get('status') != 'published':
            _delete_schedule('battle-live', battle_id)
        elif 'event_datetime' in body:
            _delete_schedule('battle-live', battle_id)
            if _parse_iso_datetime(updated['event_datetime']) <= datetime.now(timezone.utc):
                starts_now = True
            else:
                _create_schedule('battle-live', SET_BATTLE_LIVE_FUNCTION_ARN, battle_id, updated['event_datetime'])

        end_datetime = updated.get('end_datetime')
        if updated.get('status') == 'closed' or not end_datetime:
            _delete_schedule('battle-close', battle_id)
        elif 'end_datetime' in body:
            _delete_schedule('battle-close', battle_id)
            _create_schedule('battle-close', SET_BATTLE_CLOSED_FUNCTION_ARN, battle_id, end_datetime)

        # Transizione manuale (o inizio gia' passato): i matchup seguono la
        # battle.
        if updated.get('status') == 'closed' and existing.get('status') != 'closed':
            _invoke_async(SET_BATTLE_CLOSED_FUNCTION_ARN, battle_id)
        elif starts_now or (updated.get('status') == 'live' and existing.get('status') != 'live'):
            _invoke_async(SET_BATTLE_LIVE_FUNCTION_ARN, battle_id)

        return _cors_response(200, updated)

    except Exception as e:
        print(f"[update-battle] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
