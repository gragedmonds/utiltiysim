"""Customer-owned financial contact intentions from actually delivered notices."""
import json
import math
from datetime import date, datetime, timedelta

from . import customer_finance as finance
from .migrations import rollback_backup
from .store import canonical, draw, stable

VERSION = 'world-customer-notices/1'
INTENT_VERSION = 'financial-contact-intent/1'
DEFAULT_POLICY = {'active': False, 'noticeProbabilityPerDay': .5, 'deliveryDelaySeconds': 86400,
                  'repeatAfterDays': 3, 'maxContacts': 3}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='customerNoticesModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError('Unsupported customer notices model version.')
    return row is not None


def _enable(world, db):
    if enabled(db):
        return
    backup = rollback_backup(world, 'customer-notices')
    for sql in (
        'CREATE TABLE customer_notice_policy(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,'
        'payload TEXT NOT NULL,cause TEXT NOT NULL,inbox_cursor INTEGER NOT NULL DEFAULT 0)',
        'CREATE TABLE customer_notice_documents(invoice TEXT PRIMARY KEY,premise TEXT NOT NULL,recipient TEXT NOT NULL,'
        'delivery TEXT NOT NULL,delivered_at TEXT NOT NULL,known_at TEXT NOT NULL)',
        'CREATE INDEX customer_notice_documents_premise ON customer_notice_documents(premise,invoice)',
        'CREATE TABLE customer_notice_episodes(id TEXT PRIMARY KEY,invoice TEXT UNIQUE NOT NULL,premise TEXT NOT NULL,'
        'stamp TEXT NOT NULL,noticed_at TEXT,contacts INTEGER NOT NULL DEFAULT 0,last_day TEXT,last_contact TEXT,'
        'status TEXT NOT NULL)',
        'CREATE TABLE customer_notice_outbox(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,'
        'episode TEXT NOT NULL,premise TEXT NOT NULL,available_at TEXT NOT NULL,envelope TEXT NOT NULL,'
        "fingerprint TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,"
        'receipt TEXT,last_error TEXT)',
        'CREATE INDEX customer_notice_available ON customer_notice_outbox(available_at,sequence)',
        'CREATE INDEX customer_notice_pending ON customer_notice_outbox(state,available_at,sequence)',
    ):
        db.execute(sql)
    world.put(db, 'customerNoticesModelVersion', VERSION)
    world.put(db, 'customerNoticesRollbackBackup', backup)


def command(world, payload):
    common = {'schemaVersion', 'commandId', 'environmentId', 'runId', 'worldFingerprint', 'actorId',
              'expectedRevision', 'effectiveDate', 'action', 'reason', 'causalReference'}
    if not isinstance(payload, dict) or set(payload) != common | set(DEFAULT_POLICY):
        raise ValueError('Invalid customer notices command.')
    for key in common - {'expectedRevision'}:
        finance._text(payload[key])
    finance._cents(payload['expectedRevision'])
    finance._date(payload['effectiveDate'])
    if (payload['schemaVersion'] != VERSION or payload['action'] != 'configure'
            or payload['actorId'] != 'world-admin' or type(payload['active']) is not bool):
        raise ValueError('Explicit local administrator policy required.')
    probability = payload['noticeProbabilityPerDay']
    if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError('Noticing probability must be between zero and one.')
    for key, low, high in [('deliveryDelaySeconds', 0, 2592000), ('repeatAfterDays', 1, 365), ('maxContacts', 1, 10)]:
        if type(payload[key]) is not int or not low <= payload[key] <= high:
            raise ValueError('Invalid notice delay, repeat interval or contact limit.')
    encoded = canonical(payload)
    with world.db() as db:
        meta = finance._meta(db)
        finance._identity(meta, payload)
        prior = finance._retry(db, 'commands', payload['commandId'], encoded)
        if prior:
            return prior
        old = db.execute('SELECT * FROM customer_notice_policy WHERE id=1').fetchone() if enabled(db) else None
        revision = old['revision'] if old else 0
        if payload['expectedRevision'] != revision or payload['effectiveDate'] != meta['through']:
            raise ValueError('Customer notices revision or date changed. Reload before editing.')
        _enable(world, db)
        event = world.event(db, meta['environment'], meta['through'], 'CustomerNoticePolicyConfigured',
                            'customer-notices', payload, payload['causalReference'])
        policy = {key: payload[key] for key in DEFAULT_POLICY}
        db.execute('INSERT INTO customer_notice_policy(id,revision,payload,cause) VALUES(1,?,?,?) '
                   'ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,cause=excluded.cause',
                   (revision+1, canonical(policy), event))
        result = {'commandId': payload['commandId'], 'status': 'completed', 'revision': revision+1,
                  'effectiveDate': meta['through'], 'eventId': event, 'modelVersion': VERSION}
        db.execute('INSERT INTO commands VALUES(?,?,?)', (payload['commandId'], encoded, canonical(result)))
        return result


def prepare_day(db):
    """Index new trusted inbox evidence once/day, inside the daily transaction."""
    if not enabled(db):
        return None
    row = db.execute('SELECT * FROM customer_notice_policy WHERE id=1').fetchone()
    cursor = row['inbox_cursor']
    for evidence in db.execute('SELECT rowid,payload,result FROM customer_finance_inbox WHERE rowid>? ORDER BY rowid', (cursor,)):
        cursor = evidence['rowid']
        message = json.loads(evidence['payload'])
        if message.get('schemaVersion') != finance.DELIVERY_VERSION or message.get('kind') != 'notice':
            continue
        event_id = json.loads(evidence['result'])['eventId']
        learned = db.execute('SELECT day FROM events WHERE id=?', (event_id,)).fetchone()
        if not learned:
            raise ValueError('Delivered notice is missing its learned-event evidence.')
        db.execute('INSERT INTO customer_notice_documents VALUES(?,?,?,?,?,?) ON CONFLICT(invoice) DO NOTHING',
                   (message['invoiceId'], message['premiseId'], message['recipientRef'], message['deliveryId'],
                    message['deliveredAt'], learned['day']+'T00:00:00Z'))
    db.execute('UPDATE customer_notice_policy SET inbox_cursor=? WHERE id=1', (cursor,))
    return {'policy': json.loads(row['payload']), 'cause': row['cause']}


def apply_profile(world, db, meta, profile, stamp, occupied, config):
    """Run after cashflow, before payment reservations; never moves any cash."""
    if config is None:
        return
    day, policy = meta['through'], config['policy']
    finish = (date.fromisoformat(day)+timedelta(days=1)).isoformat()+'T00:00:00Z'
    available = max(0, profile['cash']-profile['reserved']-json.loads(profile['policy'])['essentialReserveCents'])
    for notice in db.execute('SELECT n.*,i.amount,i.settled,i.due FROM customer_notice_documents n '
                             'JOIN customer_finance_invoices i ON i.id=n.invoice WHERE n.premise=? ORDER BY n.invoice',
                             (profile['premise'],)).fetchall():
        episode = db.execute('SELECT * FROM customer_notice_episodes WHERE invoice=?', (notice['invoice'],)).fetchone()
        pending = db.execute("SELECT COALESCE(SUM(amount),0) FROM customer_finance_intents WHERE invoice=? AND payment_state='reserved'",
                             (notice['invoice'],)).fetchone()[0]
        remaining = max(0, notice['amount']-notice['settled']-pending)
        status = ('cohort_changed' if not occupied or stamp != profile['stamp'] or notice['recipient'] != profile['recipient']
                  else 'not_due' if notice['due'] > day else 'settled' if notice['amount'] <= notice['settled']
                  else 'pending_provider' if remaining == 0 else 'funded' if remaining <= available
                  else 'paused' if not policy['active'] else 'shortfall')
        if episode:
            db.execute('UPDATE customer_notice_episodes SET status=? WHERE id=?', (status, episode['id']))
        if status != 'shortfall':
            continue
        if episode is None:
            identity = 'FINEXP-'+stable(meta['environment'], VERSION, profile['recipient'], stamp, notice['invoice'])
            db.execute('INSERT INTO customer_notice_episodes(id,invoice,premise,stamp,status) VALUES(?,?,?,?,?)',
                       (identity, notice['invoice'], profile['premise'], stamp, status))
            episode = db.execute('SELECT * FROM customer_notice_episodes WHERE id=?', (identity,)).fetchone()
        if episode['contacts'] >= policy['maxContacts']:
            continue
        if episode['noticed_at'] is None and draw(meta['seed'], VERSION, episode['id'], day, 'notice') >= policy['noticeProbabilityPerDay']:
            continue
        if episode['last_day'] and (date.fromisoformat(day)-date.fromisoformat(episode['last_day'])).days < policy['repeatAfterDays']:
            continue
        attempt = episode['contacts']+1
        identity = 'FINCONTACT-'+stable(meta['environment'], VERSION, episode['id'], attempt)
        available_at = (datetime.fromisoformat(finish.replace('Z', '+00:00'))+
                        timedelta(seconds=policy['deliveryDelaySeconds'])).isoformat().replace('+00:00', 'Z')
        intent = {'schemaVersion': INTENT_VERSION, 'id': identity, 'environmentId': meta['environment'],
                  'runId': meta['environment'], 'premiseId': profile['premise'], 'recipientRef': profile['recipient'],
                  'customerKind': json.loads(profile['policy'])['customerKind'], 'invoiceId': notice['invoice'],
                  'deliveredDocumentId': notice['delivery'], 'documentDeliveredAt': notice['delivered_at'],
                  'knownAt': notice['known_at'], 'noticedAt': episode['noticed_at'] or finish,
                  'createdAt': finish, 'availableAt': available_at, 'episodeId': episode['id'], 'attempt': attempt,
                  'previousContactId': episode['last_contact'], 'reason': 'payment_help' if attempt == 1 else 'repeat_payment_help'}
        world.event(db, meta['environment'], day, 'CustomerFinancialContactIntended', profile['premise'],
                    {'intentId': identity, 'episodeId': episode['id'], 'noticeDeliveryId': notice['delivery'],
                     'remainingUnreservedCents': remaining, 'availableCashCents': available, 'policy': policy,
                     'policyCause': config['cause'], 'occupancyStamp': stamp}, notice['delivery'])
        db.execute('INSERT INTO customer_notice_outbox(id,episode,premise,available_at,envelope,fingerprint) VALUES(?,?,?,?,?,?)',
                   (identity, episode['id'], profile['premise'], available_at, canonical(intent), stable(intent)))
        db.execute('UPDATE customer_notice_episodes SET noticed_at=COALESCE(noticed_at,?),contacts=?,last_day=?,last_contact=? WHERE id=?',
                   (finish, attempt, day, identity, episode['id']))


def _cursor(after, limit):
    finance._page(0, limit)
    if after is None:
        return '', 0
    if not isinstance(after, str) or len(after) > 100 or after.count('|') != 1:
        raise ValueError('Invalid financial contact cursor.')
    since, sequence = after.split('|')
    finance._time(since)
    number = int(sequence)
    finance._page(number, limit)
    if str(number) != sequence:
        raise ValueError('Use a canonical sequence cursor.')
    return since, number


def _intent(row):
    intent = json.loads(row['envelope'])
    if stable(intent) != row['fingerprint']:
        raise ValueError('Stored financial contact checksum mismatch.')
    return intent


def ready(world, after=None, limit=25):
    since, sequence = _cursor(after, limit)
    with world.db() as db:
        meta = finance._meta(db)
        if not meta:
            raise ValueError('Initialize a world first.')
        rows = [] if not enabled(db) else list(db.execute(
            'SELECT * FROM customer_notice_outbox WHERE (available_at,sequence)>(?,?) AND available_at<=? '
            'ORDER BY available_at,sequence LIMIT ?', (since, sequence, meta['through']+'T00:00:00Z', limit+1)))
        items = [{'cursor': row['available_at']+'|'+str(row['sequence']), 'intent': _intent(row)} for row in rows[:limit]]
        return {'schemaVersion': INTENT_VERSION, 'environmentId': meta['environment'], 'items': items,
                'nextAfter': items[-1]['cursor'] if len(rows) > limit else None}


def relay(world, send, limit=25):
    """At-least-once callback; recipient deduplicates runId/id/fingerprint."""
    finance._page(0, limit)
    accepted = 0
    for _ in range(limit):
        with world.db() as db:
            if not enabled(db):
                break
            meta = finance._meta(db)
            row = db.execute("SELECT * FROM customer_notice_outbox WHERE state='pending' AND available_at<=? "
                             'ORDER BY available_at,sequence LIMIT 1', (meta['through']+'T00:00:00Z',)).fetchone()
            if row is None:
                break
            intent = _intent(row)
            db.execute('UPDATE customer_notice_outbox SET attempts=attempts+1 WHERE id=?', (row['id'],))
        try:
            receipt = send(intent)
            if (not isinstance(receipt, dict) or set(receipt) != {'id', 'runId', 'fingerprint', 'status', 'receiptId'}
                    or receipt['id'] != row['id'] or receipt['runId'] != intent['runId']
                    or receipt['fingerprint'] != row['fingerprint'] or receipt['status'] != 'accepted'):
                raise ValueError('Recipient did not acknowledge this financial contact.')
            finance._text(receipt['receiptId'])
            encoded = canonical(receipt)
        except Exception as exc:
            error = type(exc).__name__
            with world.db() as db:
                db.execute("UPDATE customer_notice_outbox SET last_error=? WHERE id=? AND state='pending'", (error, row['id']))
            return {'accepted': accepted, 'blocked': row['id'], 'error': error}
        with world.db() as db:
            old = db.execute('SELECT state,receipt FROM customer_notice_outbox WHERE id=?', (row['id'],)).fetchone()
            if old['state'] == 'accepted' and old['receipt'] != encoded:
                raise ValueError('Conflicting financial contact acceptance receipt.')
            accepted += db.execute("UPDATE customer_notice_outbox SET state='accepted',receipt=?,last_error=NULL "
                                   "WHERE id=? AND state='pending'", (encoded, row['id'])).rowcount
    return {'accepted': accepted, 'blocked': None, 'error': None}


def inspect(world, after=0, limit=25):
    finance._page(after, limit)
    with world.db() as db:
        meta = finance._meta(db)
        if not meta:
            raise ValueError('Initialize a world first.')
        present = enabled(db)
        config = db.execute('SELECT * FROM customer_notice_policy WHERE id=1').fetchone() if present else None
        rows = [] if not present else list(db.execute('SELECT * FROM customer_notice_outbox WHERE sequence>? '
                                                       'ORDER BY sequence LIMIT ?', (after, limit+1)))
        items = [{key: row[key] for key in ('sequence', 'id', 'episode', 'premise', 'available_at', 'state', 'attempts', 'last_error')} |
                 {'intent': _intent(row), 'receipt': json.loads(row['receipt']) if row['receipt'] else None,
                  'available': row['available_at'] <= meta['through']+'T00:00:00Z'} for row in rows[:limit]]
        counts = {} if not present else {r[0]: r[1] for r in db.execute('SELECT state,COUNT(*) FROM customer_notice_outbox GROUP BY state')}
        return {'view': 'administrator-truth', 'modelVersion': VERSION, 'environmentId': meta['environment'],
                'runId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'through': meta['through'],
                'enabled': present, 'revision': config['revision'] if config else 0,
                'policy': json.loads(config['payload']) if config else DEFAULT_POLICY, 'items': items, 'counts': counts,
                'nextAfter': items[-1]['sequence'] if len(rows) > limit else None}
