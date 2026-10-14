"""
User API - Create Report
POST /v1/reports          (Cognito: il segnalante e' l'utente loggato)
POST /v1/public/reports   (pubblico: il segnalante e' il device_id, lo stesso
                           voter_id usato per votare)

Segnala una battle, un matchup (o un suo partecipante ospite) o un utente.
Il server ricava da se' il proprietario del contenuto e ne salva una copia
(snapshot): il contenuto puo' cambiare o sparire prima che il super admin lo
guardi. Una sola segnalazione per persona e contenuto: ripetere la richiesta
non crea duplicati e risponde comunque 200, cosi' il client mostra sempre la
stessa conferma.
"""
import hashlib
import json
import os
import time
import boto3
from datetime import datetime, timezone
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
reports_table = dynamodb.Table(os.environ['REPORTS_TABLE'])
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])
user_profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])

TARGET_TYPES = {'battle', 'matchup', 'user'}
REASONS = {'spam', 'hate', 'violence', 'sexual', 'false_info', 'impersonation', 'other'}
PARTICIPANT_SIDES = {'a', 'b'}
MAX_NOTE_LENGTH = 500

# Segnalazioni anonime: massimo per dispositivo al giorno (UTC).
PUBLIC_DAILY_LIMIT = 10


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


def _bad_request(message):
    return _cors_response(400, {'error': 'Bad Request', 'message': message})


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _caller_id(event):
    claims = ((event.get('requestContext') or {}).get('authorizer') or {}).get('claims') or {}
    return claims.get('sub')


def _public_profile(user_id):
    if not user_id:
        return None
    return user_profiles_table.get_item(
        Key={'user_id': user_id},
        ProjectionExpression='user_id, username, display_name, avatar_url',
    ).get('Item')


def _participant_snapshot(participant):
    if not participant:
        return None
    if 'guest_name' in participant:
        return {'guest_name': participant['guest_name']}
    profile = _public_profile(participant.get('user_id')) or {}
    return {
        'user_id': participant.get('user_id'),
        'username': profile.get('username'),
        'display_name': profile.get('display_name'),
    }


def _resolve_target(target_type, target_id, participant_side):
    """Ritorna (owner_id, snapshot, errore). Un contenuto gia' rimosso non si
    segnala: per chi lo vede ancora (cache) basta che sparisca al refresh."""
    if target_type == 'battle':
        battle = battles_table.get_item(Key={'battle_id': target_id}).get('Item')
        if not battle or battle.get('moderation_state') == 'removed':
            return None, None, 'not_found'
        snapshot = {
            'title': battle.get('title'),
            'description': battle.get('description'),
            'location': battle.get('location'),
            'cover': battle.get('cover'),
            'cover_url': battle.get('cover_url'),
            'stream_url': battle.get('stream_url'),
            'event_datetime': battle.get('event_datetime'),
        }
        return battle['host_id'], snapshot, None

    if target_type == 'matchup':
        matchup = matchups_table.get_item(Key={'matchup_id': target_id}).get('Item')
        if not matchup or matchup.get('moderation_state') == 'removed':
            return None, None, 'not_found'
        battle = battles_table.get_item(Key={'battle_id': matchup['battle_id']}).get('Item')
        if not battle or battle.get('moderation_state') == 'removed':
            return None, None, 'not_found'
        if participant_side:
            participant = matchup.get(f'participant_{participant_side}') or {}
            # Il partecipante registrato si segnala come utente, non come
            # nome dentro il matchup: e' il suo profilo che va moderato.
            if 'guest_name' not in participant:
                return None, None, 'participant_side is only for guest participants: report the user instead'
        snapshot = {
            'battle_id': matchup['battle_id'],
            'battle_title': battle.get('title'),
            'participant_a': _participant_snapshot(matchup.get('participant_a')),
            'participant_b': _participant_snapshot(matchup.get('participant_b')),
        }
        return battle['host_id'], snapshot, None

    profile = user_profiles_table.get_item(Key={'user_id': target_id}).get('Item')
    if not profile or profile.get('account_status') == 'deleted':
        return None, None, 'not_found'
    snapshot = {
        'username': profile.get('username'),
        'display_name': profile.get('display_name'),
        'avatar_url': profile.get('avatar_url'),
    }
    return target_id, snapshot, None


def _consume_public_quota(device_id):
    """Conta le segnalazioni anonime del giorno. False se il limite e' superato."""
    day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        reports_table.update_item(
            Key={'report_id': f'RATE#{device_id}#{day}'},
            UpdateExpression='ADD #count :one SET #ttl = :ttl',
            ConditionExpression='attribute_not_exists(#count) OR #count < :limit',
            ExpressionAttributeNames={'#count': 'count', '#ttl': 'ttl'},
            ExpressionAttributeValues={
                ':one': 1,
                ':limit': PUBLIC_DAILY_LIMIT,
                ':ttl': int(time.time()) + 2 * 24 * 3600,
            },
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return False
        raise


def handler(event, context):
    try:
        body = json.loads(event.get('body') or '{}')
        caller_id = _caller_id(event)

        target_type = body.get('target_type')
        target_id = (body.get('target_id') or '').strip() if isinstance(body.get('target_id'), str) else ''
        reason = body.get('reason')
        note = body.get('note') or ''
        participant_side = body.get('participant_side')

        if target_type not in TARGET_TYPES:
            return _bad_request(f'target_type must be one of: {", ".join(sorted(TARGET_TYPES))}')
        if not target_id:
            return _bad_request('target_id is required')
        if reason not in REASONS:
            return _bad_request(f'reason must be one of: {", ".join(sorted(REASONS))}')
        if not isinstance(note, str) or len(note) > MAX_NOTE_LENGTH:
            return _bad_request(f'note must be a string of at most {MAX_NOTE_LENGTH} characters')
        if participant_side is not None and (target_type != 'matchup' or participant_side not in PARTICIPANT_SIDES):
            return _bad_request("participant_side must be 'a' or 'b' and only applies to matchups")

        if caller_id:
            reporter_key = f'user#{caller_id}'
        else:
            device_id = (body.get('device_id') or '').strip() if isinstance(body.get('device_id'), str) else ''
            if not device_id:
                return _bad_request('device_id is required for anonymous reports')
            reporter_key = f'device#{device_id}'

        owner_id, snapshot, error = _resolve_target(target_type, target_id, participant_side)
        if error == 'not_found':
            return _cors_response(404, {'error': 'Not Found', 'message': f'{target_type} not found'})
        if error:
            return _bad_request(error)

        if caller_id and owner_id == caller_id:
            return _bad_request('You cannot report your own content')

        # Il limite si consuma solo per segnalazioni valide, dopo i controlli.
        if not caller_id and not _consume_public_quota(device_id):
            return _cors_response(429, {'error': 'Too Many Requests', 'message': 'Daily report limit reached'})

        target_key = f'{target_type}#{target_id}'
        identity = f'{target_key}|{participant_side or ""}|{reporter_key}'
        report_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]

        report = {
            'report_id': report_id,
            'target_type': target_type,
            'target_id': target_id,
            'target_key': target_key,
            'target_owner_id': owner_id,
            'reason': reason,
            'status': 'open',
            'snapshot': snapshot,
            'created_at': _now_iso(),
        }
        if participant_side:
            report['participant_side'] = participant_side
        if note.strip():
            report['note'] = note.strip()
        if caller_id:
            report['reporter_id'] = caller_id
        else:
            report['reporter_device_id'] = device_id

        # Se la stessa persona aveva gia' una segnalazione aperta su questo
        # contenuto non si duplica; se era gia' stata gestita, la nuova la
        # riapre (il contenuto puo' essere cambiato dopo la decisione).
        try:
            reports_table.put_item(
                Item=report,
                ConditionExpression='attribute_not_exists(report_id) OR #status <> :open',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':open': 'open'},
            )
            created = True
        except ClientError as e:
            if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                raise
            created = False

        return _cors_response(201 if created else 200, {
            'report_id': report_id,
            'already_reported': not created,
        })

    except json.JSONDecodeError:
        return _bad_request('Body must be valid JSON')
    except Exception as e:
        print(f"[create-report] Error: {e}")
        return _cors_response(500, {'error': 'Internal Server Error', 'message': str(e)})
