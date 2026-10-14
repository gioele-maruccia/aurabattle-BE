"""
Backoffice - Admin API (super admin)

Una sola Lambda con un router interno: tutte le rotte condividono il
controllo di accesso (gruppo Cognito `superadmins`) e le stesse letture, e
cosi' non serve un layer solo per questo.

Niente di automatico: ogni rimozione, sospensione o eliminazione parte da
una richiesta esplicita del super admin, e ogni decisione finisce in
ModerationLog.

Rotte (tutte sotto /v1/admin):
  GET  /reports?status=open|actioned|dismissed
  GET  /reports/{targetType}/{targetId}
  POST /reports/{targetType}/{targetId}/resolve
  POST /content/{targetType}/{targetId}/restore
  GET  /users?q=
  GET  /users/{userId}
  POST /users/{userId}/suspend
  POST /users/{userId}/reinstate
  GET  /deletion-requests
  POST /deletion-requests/{userId}/complete
  GET  /stats
"""
import json
import os
import uuid
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

REGION = os.environ['REGION']
COGNITO_USER_POOL_ID = os.environ['COGNITO_USER_POOL_ID']
ADMIN_GROUP = 'superadmins'

dynamodb = boto3.resource('dynamodb', region_name=REGION)
cognito = boto3.client('cognito-idp', region_name=REGION)

reports_table = dynamodb.Table(os.environ['REPORTS_TABLE'])
blocks_table = dynamodb.Table(os.environ['USER_BLOCKS_TABLE'])
log_table = dynamodb.Table(os.environ['MODERATION_LOG_TABLE'])
battles_table = dynamodb.Table(os.environ['BATTLES_TABLE'])
matchups_table = dynamodb.Table(os.environ['MATCHUPS_TABLE'])
profiles_table = dynamodb.Table(os.environ['USER_PROFILES_TABLE'])
usernames_table = dynamodb.Table(os.environ['USERNAMES_TABLE'])

TARGET_TYPES = {'battle', 'matchup', 'user'}
RESOLVE_ACTIONS = {'remove_content', 'suspend_user', 'remove_and_suspend', 'dismiss'}
REPORT_STATUSES = {'open', 'actioned', 'dismissed'}
DELETION_DAYS = 15
REMOVED_GUEST_NAME = 'Partecipante rimosso'

# Quante segnalazioni leggere al massimo per costruire la coda. Ai volumi
# attuali la coda sta tutta in una lettura; oltre, si vedono le piu' vecchie.
MAX_QUEUE_REPORTS = 1000


class HttpError(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return str(value)


def _response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
        },
        'body': json.dumps(body, default=_json_default),
    }


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _claims(event):
    return ((event.get('requestContext') or {}).get('authorizer') or {}).get('claims') or {}


def _groups(claims):
    """API Gateway (REST) passa cognito:groups come stringa ("a" oppure
    "[a b]" / "a,b" a seconda della versione): la normalizziamo."""
    raw = claims.get('cognito:groups') or ''
    if isinstance(raw, list):
        return {str(g) for g in raw}
    cleaned = raw.strip('[]')
    return {g.strip() for g in cleaned.replace(',', ' ').split() if g.strip()}


def _require_admin(event):
    claims = _claims(event)
    if ADMIN_GROUP not in _groups(claims):
        raise HttpError(403, 'Super admin only', 'FORBIDDEN')
    return claims['sub']


def _body(event):
    try:
        body = json.loads(event.get('body') or '{}')
    except json.JSONDecodeError:
        raise HttpError(400, 'Body must be valid JSON')
    if not isinstance(body, dict):
        raise HttpError(400, 'Body must be a JSON object')
    return body


def _query_all(table, **kwargs):
    items = []
    while True:
        response = table.query(**kwargs)
        items.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            return items
        kwargs['ExclusiveStartKey'] = last_key


def _count(table, **kwargs):
    total = 0
    kwargs['Select'] = 'COUNT'
    while True:
        response = table.query(**kwargs)
        total += response.get('Count', 0)
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            return total
        kwargs['ExclusiveStartKey'] = last_key


def _target_type(value):
    if value not in TARGET_TYPES:
        raise HttpError(400, f'targetType must be one of: {", ".join(sorted(TARGET_TYPES))}')
    return value


# ------------------------------------------------------------------
# Profili
# ------------------------------------------------------------------

def _public_profile(user_id, cache=None):
    if not user_id:
        return None
    if cache is not None and user_id in cache:
        return cache[user_id]
    profile = profiles_table.get_item(
        Key={'user_id': user_id},
        ProjectionExpression='user_id, username, display_name, avatar_url, account_status',
    ).get('Item')
    if cache is not None:
        cache[user_id] = profile
    return profile


def _admin_profile(profile):
    """Dati di un utente come li vede il super admin (email inclusa)."""
    if not profile:
        return None
    names = profile.get('profile') or {}
    return {
        'user_id': profile['user_id'],
        'username': profile.get('username'),
        'display_name': profile.get('display_name', ''),
        'given_name': names.get('given_name', ''),
        'family_name': names.get('family_name', ''),
        'email': profile.get('email'),
        'avatar_url': profile.get('avatar_url'),
        'account_status': profile.get('account_status', 'active'),
        'created_at': profile.get('created_at'),
        'suspended_at': profile.get('suspended_at'),
        'suspended_reason': profile.get('suspended_reason'),
        'deletion_requested_at': profile.get('deletion_requested_at'),
        'hosted_battles_count': profile.get('hosted_battles_count', 0),
    }


def _owner_stats(user_id):
    return {
        'reports_received': _count(
            reports_table,
            IndexName='target_owner_id-created_at-index',
            KeyConditionExpression=Key('target_owner_id').eq(user_id),
        ),
        'blocked_by': _count(
            blocks_table,
            IndexName='blocked_id-index',
            KeyConditionExpression=Key('blocked_id').eq(user_id),
        ),
        'removed_battles': _count(
            battles_table,
            IndexName='host_id-index',
            KeyConditionExpression=Key('host_id').eq(user_id),
            FilterExpression=Attr('moderation_state').eq('removed'),
        ),
    }


def _cognito_username(user_id):
    """Il pool usa l'email come username: le Admin* API vogliono lo username
    Cognito, che recuperiamo dal sub."""
    response = cognito.list_users(
        UserPoolId=COGNITO_USER_POOL_ID,
        Filter=f'sub = "{user_id}"',
        Limit=1,
    )
    users = response.get('Users', [])
    return users[0]['Username'] if users else None


# ------------------------------------------------------------------
# Contenuti
# ------------------------------------------------------------------

def _load_target(target_type, target_id):
    if target_type == 'battle':
        return battles_table.get_item(Key={'battle_id': target_id}).get('Item')
    if target_type == 'matchup':
        return matchups_table.get_item(Key={'matchup_id': target_id}).get('Item')
    return profiles_table.get_item(Key={'user_id': target_id}).get('Item')


def _target_owner(target_type, target):
    if target_type == 'battle':
        return target['host_id']
    if target_type == 'matchup':
        battle = battles_table.get_item(Key={'battle_id': target['battle_id']}).get('Item')
        return battle['host_id'] if battle else None
    return target['user_id']


def _enrich_matchup(matchup):
    for side in ('participant_a', 'participant_b'):
        participant = matchup.get(side) or {}
        if participant.get('user_id'):
            profile = _public_profile(participant['user_id']) or {}
            matchup[side] = {
                **participant,
                'username': profile.get('username'),
                'display_name': profile.get('display_name', ''),
                'avatar_url': profile.get('avatar_url'),
            }
    return matchup


def _set_removed(table, key, admin_id, reason):
    try:
        table.update_item(
            Key=key,
            UpdateExpression=(
                'SET moderation_state = :removed, moderated_at = :now, '
                'moderated_by = :admin, moderation_reason = :reason'
            ),
            ConditionExpression='attribute_exists(' + next(iter(key)) + ')',
            ExpressionAttributeValues={
                ':removed': 'removed',
                ':now': _now_iso(),
                ':admin': admin_id,
                ':reason': reason,
            },
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            raise HttpError(404, 'Content not found')
        raise


def _clear_removed(table, key):
    table.update_item(
        Key=key,
        UpdateExpression='REMOVE moderation_state, moderated_at, moderated_by, moderation_reason',
    )


def _new_username(user_id):
    """Username generato e riservato (stessa forma del ripiego di
    post-confirmation)."""
    for _ in range(10):
        candidate = f'user_{uuid.uuid4().hex[:12]}'
        try:
            usernames_table.put_item(
                Item={'username': candidate, 'user_id': user_id, 'status': 'active', 'created_at': _now_iso()},
                ConditionExpression=Attr('username').not_exists(),
            )
            return candidate
        except ClientError as e:
            if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                raise
    raise HttpError(500, 'Could not generate a new username')


def _remove_user_content(user_id, rename_username):
    """Toglie dal profilo cio' che e' visibile agli altri: nome pubblico e
    avatar, e su richiesta lo username."""
    profile = profiles_table.get_item(Key={'user_id': user_id}).get('Item')
    if not profile:
        raise HttpError(404, 'User not found')

    username = profile.get('username') or ''
    updates = {
        'avatar_url': None,
        'updated_at': _now_iso(),
    }
    if rename_username:
        new_username = _new_username(user_id)
        if username:
            usernames_table.delete_item(Key={'username': username})
        updates['username'] = new_username
        username = new_username
    updates['display_name'] = username
    updates['display_name_lower'] = username.lower()

    names = {f'#{k}': k for k in updates}
    values = {f':{k}': v for k, v in updates.items()}
    profiles_table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='SET ' + ', '.join(f'#{k} = :{k}' for k in updates),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    return {'username': username}


def _remove_guest(matchup, side):
    participant = matchup.get(f'participant_{side}') or {}
    if 'guest_name' not in participant:
        raise HttpError(400, f'participant_{side} is not a guest')
    matchups_table.update_item(
        Key={'matchup_id': matchup['matchup_id']},
        UpdateExpression='SET #p = :p, updated_at = :now',
        ExpressionAttributeNames={'#p': f'participant_{side}'},
        ExpressionAttributeValues={
            ':p': {'guest_name': REMOVED_GUEST_NAME, 'guest_removed': True},
            ':now': _now_iso(),
        },
    )


def _write_log(target_key, admin_id, action, note=None, report_ids=None, details=None):
    item = {
        'target_key': target_key,
        'ts': _now_iso() + '#' + uuid.uuid4().hex[:6],
        'action': action,
        'admin_id': admin_id,
    }
    if note:
        item['note'] = note
    if report_ids:
        item['report_ids'] = report_ids
    if details:
        item['details'] = details
    log_table.put_item(Item=item)


# ------------------------------------------------------------------
# Sospensione
# ------------------------------------------------------------------

def _suspend(user_id, admin_id, reason):
    profile = profiles_table.get_item(Key={'user_id': user_id}).get('Item')
    if not profile:
        raise HttpError(404, 'User not found')

    cognito_username = _cognito_username(user_id)
    if cognito_username:
        cognito.admin_disable_user(UserPoolId=COGNITO_USER_POOL_ID, Username=cognito_username)
        cognito.admin_user_global_sign_out(UserPoolId=COGNITO_USER_POOL_ID, Username=cognito_username)

    profiles_table.update_item(
        Key={'user_id': user_id},
        UpdateExpression=(
            'SET account_status = :s, suspended_at = :now, suspended_by = :admin, '
            'suspended_reason = :reason, updated_at = :now'
        ),
        ExpressionAttributeValues={
            ':s': 'suspended', ':now': _now_iso(), ':admin': admin_id, ':reason': reason,
        },
    )

    # Le sue battle spariscono con lui. Il motivo 'user_suspended' permette
    # alla riattivazione di rimettere solo queste, non quelle rimosse prima
    # per conto loro.
    hidden = 0
    battles = _query_all(battles_table, IndexName='host_id-index', KeyConditionExpression=Key('host_id').eq(user_id))
    for battle in battles:
        if battle.get('moderation_state') == 'removed':
            continue
        _set_removed(battles_table, {'battle_id': battle['battle_id']}, admin_id, 'user_suspended')
        hidden += 1
    return {'battles_hidden': hidden, 'cognito_disabled': bool(cognito_username)}


def _reinstate(user_id):
    profile = profiles_table.get_item(Key={'user_id': user_id}).get('Item')
    if not profile:
        raise HttpError(404, 'User not found')

    cognito_username = _cognito_username(user_id)
    if cognito_username:
        cognito.admin_enable_user(UserPoolId=COGNITO_USER_POOL_ID, Username=cognito_username)

    profiles_table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='SET account_status = :s, updated_at = :now REMOVE suspended_at, suspended_by, suspended_reason',
        ExpressionAttributeValues={':s': 'active', ':now': _now_iso()},
    )

    restored = 0
    battles = _query_all(battles_table, IndexName='host_id-index', KeyConditionExpression=Key('host_id').eq(user_id))
    for battle in battles:
        if battle.get('moderation_reason') == 'user_suspended':
            _clear_removed(battles_table, {'battle_id': battle['battle_id']})
            restored += 1
    return {'battles_restored': restored}


# ------------------------------------------------------------------
# Segnalazioni
# ------------------------------------------------------------------

def _reporter_view(report, cache):
    if report.get('reporter_id'):
        profile = _public_profile(report['reporter_id'], cache) or {}
        return {'type': 'user', 'user_id': report['reporter_id'], 'username': profile.get('username')}
    return {'type': 'visitor'}


def _report_view(report, cache):
    return {
        'report_id': report['report_id'],
        'reason': report.get('reason'),
        'note': report.get('note'),
        'participant_side': report.get('participant_side'),
        'status': report.get('status'),
        'created_at': report.get('created_at'),
        'resolved_at': report.get('resolved_at'),
        'resolution': report.get('resolution'),
        'reporter': _reporter_view(report, cache),
        'snapshot': report.get('snapshot'),
    }


def list_reports(event):
    _require_admin(event)
    params = event.get('queryStringParameters') or {}
    status = params.get('status') or 'open'
    if status not in REPORT_STATUSES:
        raise HttpError(400, f'status must be one of: {", ".join(sorted(REPORT_STATUSES))}')

    # Aperte: le piu' vecchie prima (conta la scadenza). Gestite: le piu' recenti.
    oldest_first = status == 'open'
    reports = []
    kwargs = {
        'IndexName': 'status-created_at-index',
        'KeyConditionExpression': Key('status').eq(status),
        'ScanIndexForward': oldest_first,
    }
    while len(reports) < MAX_QUEUE_REPORTS:
        response = reports_table.query(**kwargs)
        reports.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            break
        kwargs['ExclusiveStartKey'] = last_key

    groups = {}
    for report in reports:
        key = report['target_key']
        group = groups.get(key)
        if not group:
            group = groups[key] = {
                'target_type': report['target_type'],
                'target_id': report['target_id'],
                'target_owner_id': report.get('target_owner_id'),
                'count': 0,
                'reasons': {},
                'first_reported_at': report['created_at'],
                'last_reported_at': report['created_at'],
                'snapshot': report.get('snapshot'),
                'participant_sides': [],
            }
        group['count'] += 1
        reason = report.get('reason', 'other')
        group['reasons'][reason] = group['reasons'].get(reason, 0) + 1
        if report['created_at'] < group['first_reported_at']:
            group['first_reported_at'] = report['created_at']
        if report['created_at'] >= group['last_reported_at']:
            group['last_reported_at'] = report['created_at']
            group['snapshot'] = report.get('snapshot')
        side = report.get('participant_side')
        if side and side not in group['participant_sides']:
            group['participant_sides'].append(side)

    cache = {}
    items = list(groups.values())
    for group in items:
        owner = _public_profile(group['target_owner_id'], cache) or {}
        group['owner'] = {
            'user_id': group['target_owner_id'],
            'username': owner.get('username'),
            'account_status': owner.get('account_status', 'active') if owner else None,
        }

    if oldest_first:
        items.sort(key=lambda g: g['first_reported_at'])
    else:
        items.sort(key=lambda g: g['last_reported_at'], reverse=True)

    return _response(200, {'items': items, 'count': len(items), 'truncated': len(reports) >= MAX_QUEUE_REPORTS})


def get_report_group(event, target_type, target_id):
    _require_admin(event)
    _target_type(target_type)
    target_key = f'{target_type}#{target_id}'

    reports = _query_all(
        reports_table,
        IndexName='target_key-created_at-index',
        KeyConditionExpression=Key('target_key').eq(target_key),
        ScanIndexForward=False,
    )
    target = _load_target(target_type, target_id)
    if not reports and not target:
        raise HttpError(404, 'Nothing found for this content')

    owner_id = None
    if target:
        owner_id = _target_owner(target_type, target)
    elif reports:
        owner_id = reports[0].get('target_owner_id')

    current = None
    if target and target_type == 'user':
        current = _admin_profile(target)
    elif target and target_type == 'matchup':
        current = _enrich_matchup(target)
        battle = battles_table.get_item(Key={'battle_id': target['battle_id']}).get('Item') or {}
        current['battle_title'] = battle.get('title')
    elif target:
        current = target

    owner_profile = profiles_table.get_item(Key={'user_id': owner_id}).get('Item') if owner_id else None

    log = _query_all(log_table, KeyConditionExpression=Key('target_key').eq(target_key), ScanIndexForward=False)

    cache = {}
    return _response(200, {
        'target_type': target_type,
        'target_id': target_id,
        'target_key': target_key,
        'exists': target is not None,
        'current': current,
        'reports': [_report_view(r, cache) for r in reports],
        'open_count': sum(1 for r in reports if r.get('status') == 'open'),
        'owner': _admin_profile(owner_profile) if owner_profile else ({'user_id': owner_id} if owner_id else None),
        'owner_stats': _owner_stats(owner_id) if owner_id else None,
        'log': log,
    })


def resolve_reports(event, target_type, target_id):
    admin_id = _require_admin(event)
    _target_type(target_type)
    body = _body(event)

    action = body.get('action')
    if action not in RESOLVE_ACTIONS:
        raise HttpError(400, f'action must be one of: {", ".join(sorted(RESOLVE_ACTIONS))}')
    note = (body.get('note') or '').strip() if isinstance(body.get('note'), str) else ''
    suspends = action in ('suspend_user', 'remove_and_suspend')
    removes = action in ('remove_content', 'remove_and_suspend')
    if suspends and not note:
        raise HttpError(400, 'A note is required to suspend a user')

    target_key = f'{target_type}#{target_id}'
    open_reports = _query_all(
        reports_table,
        IndexName='target_key-created_at-index',
        KeyConditionExpression=Key('target_key').eq(target_key),
        FilterExpression=Attr('status').eq('open'),
    )

    target = _load_target(target_type, target_id)
    if (removes or suspends) and not target:
        raise HttpError(404, 'Content not found')

    details = {}
    if removes:
        if target_type == 'battle':
            _set_removed(battles_table, {'battle_id': target_id}, admin_id, note or 'reported')
            details['removed'] = 'battle'
        elif target_type == 'matchup':
            side = body.get('participant_side')
            if side is None:
                sides = {r.get('participant_side') for r in open_reports if r.get('participant_side')}
                side = sides.pop() if len(sides) == 1 else None
            if side in ('a', 'b') and 'guest_name' in (target.get(f'participant_{side}') or {}):
                _remove_guest(target, side)
                details['removed'] = f'guest_{side}'
            else:
                _set_removed(matchups_table, {'matchup_id': target_id}, admin_id, note or 'reported')
                details['removed'] = 'matchup'
        else:
            details.update(_remove_user_content(target_id, bool(body.get('rename_username'))))
            details['removed'] = 'profile'

    if suspends:
        owner_id = _target_owner(target_type, target)
        if not owner_id:
            raise HttpError(404, 'Owner not found')
        details['suspended_user_id'] = owner_id
        details.update(_suspend(owner_id, admin_id, note))
        _write_log(f'user#{owner_id}', admin_id, 'suspend', note, details={'from': target_key})

    resolution = 'dismissed' if action == 'dismiss' else 'actioned'
    now = _now_iso()
    for report in open_reports:
        reports_table.update_item(
            Key={'report_id': report['report_id']},
            UpdateExpression='SET #status = :s, resolved_at = :now, resolved_by = :admin, resolution = :action',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':s': resolution, ':now': now, ':admin': admin_id, ':action': action},
        )

    report_ids = [r['report_id'] for r in open_reports]
    _write_log(target_key, admin_id, action, note, report_ids, details)

    return _response(200, {'action': action, 'resolved_reports': len(report_ids), 'details': details})


def restore_content(event, target_type, target_id):
    admin_id = _require_admin(event)
    _target_type(target_type)
    if target_type == 'user':
        raise HttpError(400, 'A profile cleanup cannot be undone; reinstate the user instead')

    table = battles_table if target_type == 'battle' else matchups_table
    key = {'battle_id': target_id} if target_type == 'battle' else {'matchup_id': target_id}
    target = table.get_item(Key=key).get('Item')
    if not target:
        raise HttpError(404, 'Content not found')
    if target.get('moderation_state') != 'removed':
        raise HttpError(409, 'Content is not removed')

    _clear_removed(table, key)
    note = (_body(event).get('note') or '').strip() or None
    _write_log(f'{target_type}#{target_id}', admin_id, 'restore', note)
    return _response(200, {'restored': True})


# ------------------------------------------------------------------
# Utenti
# ------------------------------------------------------------------

def search_users(event):
    _require_admin(event)
    params = event.get('queryStringParameters') or {}
    query = (params.get('q') or '').strip()
    if len(query) < 2:
        raise HttpError(400, 'q must be at least 2 characters')

    found = {}

    def add(items):
        for item in items:
            found.setdefault(item['user_id'], item)

    if '@' in query:
        add(profiles_table.query(
            IndexName='email-index',
            KeyConditionExpression=Key('email').eq(query.lower()),
        ).get('Items', []))
        if not found:
            add(profiles_table.query(
                IndexName='email-index',
                KeyConditionExpression=Key('email').eq(query),
            ).get('Items', []))
    else:
        query_lower = query.lower()
        owner = usernames_table.get_item(Key={'username': query_lower}).get('Item')
        if owner:
            profile = profiles_table.get_item(Key={'user_id': owner['user_id']}).get('Item')
            if profile:
                add([profile])
        for index, sort_key in (
            ('search_bucket-username-index', 'username'),
            ('search_bucket-display_name_lower-index', 'display_name_lower'),
            ('search_bucket-family_name_lower-index', 'family_name_lower'),
        ):
            add(profiles_table.query(
                IndexName=index,
                KeyConditionExpression=Key('search_bucket').eq('ALL') & Key(sort_key).begins_with(query_lower),
                Limit=20,
            ).get('Items', []))

    items = [_admin_profile(p) for p in list(found.values())[:50]]
    return _response(200, {'items': items, 'count': len(items)})


def get_user(event, user_id):
    _require_admin(event)
    profile = profiles_table.get_item(Key={'user_id': user_id}).get('Item')
    if not profile:
        raise HttpError(404, 'User not found')

    battles = _query_all(battles_table, IndexName='host_id-index', KeyConditionExpression=Key('host_id').eq(user_id))
    battles.sort(key=lambda b: b.get('created_at', ''), reverse=True)

    reports_received = reports_table.query(
        IndexName='target_owner_id-created_at-index',
        KeyConditionExpression=Key('target_owner_id').eq(user_id),
        ScanIndexForward=False,
        Limit=100,
    ).get('Items', [])

    cache = {}
    log = _query_all(log_table, KeyConditionExpression=Key('target_key').eq(f'user#{user_id}'), ScanIndexForward=False)

    return _response(200, {
        'user': _admin_profile(profile),
        'stats': {
            **_owner_stats(user_id),
            'blocking': _count(blocks_table, KeyConditionExpression=Key('blocker_id').eq(user_id)),
        },
        'battles': [
            {
                'battle_id': b['battle_id'],
                'title': b.get('title'),
                'status': b.get('status'),
                'event_datetime': b.get('event_datetime'),
                'moderation_state': b.get('moderation_state', 'visible'),
                'moderation_reason': b.get('moderation_reason'),
                'created_at': b.get('created_at'),
            }
            for b in battles
        ],
        'reports_received': [
            {**_report_view(r, cache), 'target_type': r['target_type'], 'target_id': r['target_id']}
            for r in reports_received
        ],
        'log': log,
    })


def suspend_user(event, user_id):
    admin_id = _require_admin(event)
    note = (_body(event).get('note') or '').strip()
    if not note:
        raise HttpError(400, 'A note is required to suspend a user')
    details = _suspend(user_id, admin_id, note)
    _write_log(f'user#{user_id}', admin_id, 'suspend', note, details=details)
    return _response(200, {'suspended': True, **details})


def reinstate_user(event, user_id):
    admin_id = _require_admin(event)
    note = (_body(event).get('note') or '').strip() or None
    details = _reinstate(user_id)
    _write_log(f'user#{user_id}', admin_id, 'reinstate', note, details=details)
    return _response(200, {'reinstated': True, **details})


# ------------------------------------------------------------------
# Eliminazione account (eseguita a mano dal super admin)
# ------------------------------------------------------------------

def _days_since(iso):
    try:
        then = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).days


def _pending_deletions():
    items = []
    kwargs = {'FilterExpression': Attr('account_status').eq('deletion_requested')}
    while True:
        response = profiles_table.scan(**kwargs)
        items.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            return items
        kwargs['ExclusiveStartKey'] = last_key


def list_deletion_requests(event):
    _require_admin(event)
    # Scan: UserProfiles non ha un indice su account_status. Ai volumi
    # attuali va bene; se crescono, aggiungere un GSI sparso.
    items = []
    for profile in _pending_deletions():
        view = _admin_profile(profile)
        elapsed = _days_since(profile.get('deletion_requested_at'))
        view['days_left'] = None if elapsed is None else DELETION_DAYS - elapsed
        items.append(view)
    items.sort(key=lambda p: p.get('deletion_requested_at') or '')
    return _response(200, {'items': items, 'count': len(items), 'deletion_days': DELETION_DAYS})


def complete_deletion(event, user_id):
    admin_id = _require_admin(event)
    now = _now_iso()
    # Il super admin puo' aver gia' cancellato il profilo a mano: in quel caso
    # resta solo il registro, che e' cio' che serve come traccia.
    try:
        profiles_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='SET account_status = :s, deletion_completed_at = :now, deletion_completed_by = :admin',
            ConditionExpression='attribute_exists(user_id)',
            ExpressionAttributeValues={':s': 'deleted', ':now': now, ':admin': admin_id},
        )
        profile_found = True
    except ClientError as e:
        if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
            raise
        profile_found = False

    _write_log(f'user#{user_id}', admin_id, 'deletion_completed', details={'profile_found': profile_found})
    return _response(200, {'completed': True, 'profile_found': profile_found})


# ------------------------------------------------------------------
# Statistiche
# ------------------------------------------------------------------

def get_stats(event):
    _require_admin(event)
    oldest = reports_table.query(
        IndexName='status-created_at-index',
        KeyConditionExpression=Key('status').eq('open'),
        ScanIndexForward=True,
        Limit=1,
    ).get('Items', [])
    return _response(200, {
        'open_reports': _count(
            reports_table,
            IndexName='status-created_at-index',
            KeyConditionExpression=Key('status').eq('open'),
        ),
        'oldest_open_report_at': oldest[0]['created_at'] if oldest else None,
        'pending_deletions': len(_pending_deletions()),
    })


# ------------------------------------------------------------------
# Router
# ------------------------------------------------------------------

ROUTES = {
    ('GET', '/v1/admin/reports'): lambda e, p: list_reports(e),
    ('GET', '/v1/admin/reports/{targetType}/{targetId}'): lambda e, p: get_report_group(e, p['targetType'], p['targetId']),
    ('POST', '/v1/admin/reports/{targetType}/{targetId}/resolve'): lambda e, p: resolve_reports(e, p['targetType'], p['targetId']),
    ('POST', '/v1/admin/content/{targetType}/{targetId}/restore'): lambda e, p: restore_content(e, p['targetType'], p['targetId']),
    ('GET', '/v1/admin/users'): lambda e, p: search_users(e),
    ('GET', '/v1/admin/users/{userId}'): lambda e, p: get_user(e, p['userId']),
    ('POST', '/v1/admin/users/{userId}/suspend'): lambda e, p: suspend_user(e, p['userId']),
    ('POST', '/v1/admin/users/{userId}/reinstate'): lambda e, p: reinstate_user(e, p['userId']),
    ('GET', '/v1/admin/deletion-requests'): lambda e, p: list_deletion_requests(e),
    ('POST', '/v1/admin/deletion-requests/{userId}/complete'): lambda e, p: complete_deletion(e, p['userId']),
    ('GET', '/v1/admin/stats'): lambda e, p: get_stats(e),
}


def lambda_handler(event, context):
    route = ROUTES.get((event.get('httpMethod'), event.get('resource')))
    if not route:
        return _response(404, {'error': 'Not Found', 'message': 'Unknown admin route'})
    try:
        return route(event, event.get('pathParameters') or {})
    except HttpError as e:
        body = {'error': e.message, 'message': e.message}
        if e.code:
            body['code'] = e.code
        return _response(e.status, body)
    except Exception as e:
        print(f"[backoffice-admin] Error on {event.get('httpMethod')} {event.get('resource')}: {e}")
        return _response(500, {'error': 'Internal Server Error', 'message': str(e)})
