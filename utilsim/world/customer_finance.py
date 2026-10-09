"""Simulated customer cash and intentions; never enterprise billing or posting.

Inbound delivery/receipt functions are trusted adapter boundaries, not public
administrator commands. Adapters must authenticate their producer and recipient.
"""
import json
import math
from datetime import date, datetime, timedelta

from . import occupancy
from .migrations import rollback_backup
from .store import canonical, draw, stable

VERSION = 'world-customer-finance/1'
DELIVERY_VERSION = 'customer-finance-delivery/1'
INTENT_VERSION = 'payment-intent/1'
RECEIPT_VERSION = 'customer-finance-provider-receipt/1'
RECEIPT_VERSION_2 = 'customer-finance-provider-receipt/2'
MAX_CENTS = 10**12
COMMON = {'schemaVersion', 'commandId', 'environmentId', 'worldFingerprint', 'runId',
          'actorId', 'expectedRevision', 'effectiveDate', 'action', 'premiseId', 'reason', 'causalReference'}
POLICY = {'active', 'customerKind', 'recipientRef', 'cashCents', 'essentialReserveCents',
          'maxPaymentCents', 'paymentProbability'}


def _meta(db):
    return {row['key']: json.loads(row['value']) for row in db.execute(
        "SELECT key,value FROM meta WHERE key IN ('environment','fingerprint','through','seed')")}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='customerFinanceModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError('Unsupported customer finance model version.')
    return row is not None


def _enable(world, db):
    if enabled(db):
        return
    backup = rollback_backup(world, 'customer-finance')
    statements = [
        'CREATE TABLE customer_finance_profiles(premise TEXT PRIMARY KEY,recipient TEXT UNIQUE NOT NULL,'
        'stamp TEXT NOT NULL,policy TEXT NOT NULL,cash INTEGER NOT NULL CHECK(cash>=0),'
        'reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0 AND reserved<=cash),'
        'settled INTEGER NOT NULL DEFAULT 0 CHECK(settled>=0),revision INTEGER NOT NULL,cause TEXT NOT NULL)',
        'CREATE TABLE customer_finance_invoices(id TEXT PRIMARY KEY,premise TEXT NOT NULL,recipient TEXT NOT NULL,'
        'amount INTEGER NOT NULL,settled INTEGER NOT NULL DEFAULT 0,created_delivery TEXT NOT NULL,'
        'due TEXT NOT NULL,known_at TEXT NOT NULL)',
        'CREATE TABLE customer_finance_inbox(id TEXT PRIMARY KEY,payload TEXT NOT NULL,result TEXT NOT NULL)',
        'CREATE TABLE customer_finance_decisions(premise TEXT NOT NULL,day TEXT NOT NULL,PRIMARY KEY(premise,day))',
        'CREATE TABLE customer_finance_intents(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,'
        'premise TEXT NOT NULL,invoice TEXT NOT NULL,amount INTEGER NOT NULL,available_at TEXT NOT NULL,'
        "envelope TEXT NOT NULL,fingerprint TEXT NOT NULL,payment_state TEXT NOT NULL DEFAULT 'reserved',"
        "delivery_state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,receipt TEXT,last_error TEXT)",
        'CREATE INDEX customer_finance_pending ON customer_finance_intents(delivery_state,available_at,sequence)',
        'CREATE INDEX customer_finance_invoice ON customer_finance_intents(invoice,payment_state)',
        'CREATE INDEX customer_finance_invoice_due ON customer_finance_invoices(premise,due,id)',
    ]
    for sql in statements:
        db.execute(sql)
    world.put(db, 'customerFinanceModelVersion', VERSION)
    world.put(db, 'customerFinanceRollbackBackup', backup)


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError('Text must be nonempty and at most 512 characters.')


def _cents(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_CENTS:
        raise ValueError('Use bounded integer cents.')


def _date(value):
    _text(value)
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('Use canonical YYYY-MM-DD dates.')


def _time(value):
    _text(value)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not value.endswith('Z') or parsed.isoformat().replace('+00:00', 'Z') != value:
        raise ValueError('Use canonical UTC timestamps.')


def _identity(meta, payload):
    if (payload['environmentId'] != meta.get('environment') or payload['runId'] != meta.get('environment')
            or payload['worldFingerprint'] != meta.get('fingerprint')):
        raise ValueError('World or run identity mismatch.')


def _stamp(db, premise):
    state = occupancy.current(db, premise)  # Also validates the physical premise.
    return state['appliedCommandId'] or 'baseline', state['occupied']


def _retry(db, table, identity, encoded):
    old = db.execute(f'SELECT payload,result FROM {table} WHERE id=?', (identity,)).fetchone()
    if old:
        if old['payload'] != encoded:
            raise ValueError('Conflicting customer finance retry.')
        return json.loads(old['result'])
    return None


def command(world, payload):
    """Administrator configure/credit only. cashCents cannot reset existing cash."""
    action = payload.get('action') if isinstance(payload, dict) else None
    extra = POLICY if action == 'configure' else {'amountCents'}
    if (not isinstance(payload, dict) or set(payload) != COMMON | extra or
            payload.get('schemaVersion') != VERSION or action not in ('configure', 'credit')):
        raise ValueError('Invalid customer finance command.')
    for key in COMMON - {'expectedRevision'}:
        _text(payload[key])
    _cents(payload['expectedRevision'])
    _date(payload['effectiveDate'])
    if payload['actorId'] != 'world-admin':
        raise ValueError('Local world administrator required.')
    if action == 'configure':
        for key in ('recipientRef', 'customerKind'):
            _text(payload[key])
        if type(payload['active']) is not bool or payload['customerKind'] not in ('household', 'business'):
            raise ValueError('Use an explicit simulated household or business profile.')
        for key in ('cashCents', 'essentialReserveCents', 'maxPaymentCents'):
            _cents(payload[key], 1 if key == 'maxPaymentCents' else 0)
        probability = payload['paymentProbability']
        if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError('Payment probability must be between zero and one.')
    else:
        _cents(payload['amountCents'], 1)
    encoded = canonical(payload)
    with world.db() as db:
        meta = _meta(db)
        _identity(meta, payload)
        prior = _retry(db, 'commands', payload['commandId'], encoded)
        if prior:
            return prior
        stamp, occupied = _stamp(db, payload['premiseId'])
        present = enabled(db)
        profile = db.execute('SELECT * FROM customer_finance_profiles WHERE premise=?',
                             (payload['premiseId'],)).fetchone() if present else None
        revision = profile['revision'] if profile else 0
        if payload['effectiveDate'] != meta['through'] or payload['expectedRevision'] != revision:
            raise ValueError('Customer finance revision or world date changed. Reload before editing.')
        if not occupied or (profile and profile['stamp'] != stamp):
            raise ValueError('Occupancy changed or is vacant; customer cohort migration is unsupported.')
        if action == 'credit' and profile is None:
            raise ValueError('Configure a customer cash profile first.')
        if action == 'configure' and profile and (profile['recipient'] != payload['recipientRef'] or
                                                   profile['cash'] != payload['cashCents']):
            raise ValueError('Cannot replace a recipient or reset cash; use an explicit credit command.')
        if action == 'configure' and present and not profile and db.execute(
                'SELECT 1 FROM customer_finance_profiles WHERE recipient=?', (payload['recipientRef'],)).fetchone():
            raise ValueError('A simulated recipient is already bound to another premise.')
        if action == 'credit':
            _cents(profile['cash'] + payload['amountCents'])
        _enable(world, db)
        event = world.event(db, meta['environment'], meta['through'], 'CustomerFinanceConfigured' if action == 'configure'
                            else 'CustomerCashCredited', payload['premiseId'], payload, payload['causalReference'])
        if action == 'configure':
            policy = canonical({key: payload[key] for key in POLICY - {'cashCents', 'recipientRef'}})
            if profile:
                db.execute('UPDATE customer_finance_profiles SET policy=?,revision=?,cause=? WHERE premise=?',
                           (policy, revision+1, event, payload['premiseId']))
            else:
                db.execute('INSERT INTO customer_finance_profiles(premise,recipient,stamp,policy,cash,revision,cause) '
                           'VALUES(?,?,?,?,?,?,?)', (payload['premiseId'], payload['recipientRef'], stamp, policy,
                                                     payload['cashCents'], 1, event))
        else:
            db.execute('UPDATE customer_finance_profiles SET cash=cash+?,revision=revision+1,cause=? WHERE premise=?',
                       (payload['amountCents'], event, payload['premiseId']))
        result = {'commandId': payload['commandId'], 'status': 'completed', 'revision': revision+1, 'eventId': event}
        db.execute('INSERT INTO commands VALUES(?,?,?)', (payload['commandId'], encoded, canonical(result)))
        return result


def receive_delivery(world, message):
    """Trusted delivery adapter only: transport acceptance is NOT delivered evidence.

    Invoice amounts are immutable original amounts. A notice corroborates an
    already-known invoice; it cannot create or replace a receivable balance.
    """
    fields = {'schemaVersion', 'deliveryId', 'environmentId', 'worldFingerprint', 'runId', 'premiseId',
              'recipientRef', 'invoiceId', 'currency', 'amountCents', 'dueDate', 'deliveredAt', 'kind', 'status'}
    if not isinstance(message, dict) or set(message) != fields or message['schemaVersion'] != DELIVERY_VERSION:
        raise ValueError('Invalid delivered customer document.')
    for key in fields - {'amountCents'}:
        _text(message[key])
    _cents(message['amountCents'], 1)
    _date(message['dueDate'])
    _time(message['deliveredAt'])
    if message['status'] != 'delivered' or message['kind'] not in ('invoice', 'notice') or message['currency'] != 'USD':
        raise ValueError('Only actually delivered simulated USD invoices and notices are supported.')
    encoded = canonical(message)
    with world.db() as db:
        meta = _meta(db)
        _identity(meta, message)
        if not enabled(db):
            raise ValueError('Configure customer finance first.')
        identity = 'delivery:' + message['deliveryId']
        prior = _retry(db, 'customer_finance_inbox', identity, encoded)
        if prior:
            return prior
        if message['deliveredAt'] > meta['through']+'T00:00:00Z':
            raise ValueError('Document has not yet been delivered at the world clock.')
        profile = db.execute('SELECT * FROM customer_finance_profiles WHERE premise=?', (message['premiseId'],)).fetchone()
        stamp, occupied = _stamp(db, message['premiseId'])
        if not profile or profile['recipient'] != message['recipientRef'] or profile['stamp'] != stamp or not occupied:
            raise ValueError('Delivered recipient does not match the configured occupied cohort.')
        invoice = db.execute('SELECT * FROM customer_finance_invoices WHERE id=?', (message['invoiceId'],)).fetchone()
        if invoice:
            if (invoice['premise'], invoice['recipient'], invoice['amount'], invoice['due']) != (
                    message['premiseId'], message['recipientRef'], message['amountCents'], message['dueDate']):
                raise ValueError('Conflicting invoice evidence; balance revisions are unsupported.')
        elif message['kind'] == 'notice':
            raise ValueError('A notice requires an already delivered invoice.')
        else:
            db.execute('INSERT INTO customer_finance_invoices(id,premise,recipient,amount,created_delivery,due,known_at) '
                       'VALUES(?,?,?,?,?,?,?)', (message['invoiceId'], message['premiseId'], message['recipientRef'],
                                                message['amountCents'], message['deliveryId'], message['dueDate'],
                                                meta['through']+'T00:00:00Z'))
        event = world.event(db, meta['environment'], meta['through'], 'CustomerDocumentLearned', message['premiseId'],
                            message, message['deliveryId'])
        db.execute('UPDATE customer_finance_profiles SET revision=revision+1 WHERE premise=?', (message['premiseId'],))
        result = {'deliveryId': message['deliveryId'], 'status': 'recorded', 'eventId': event}
        db.execute('INSERT INTO customer_finance_inbox VALUES(?,?,?)', (identity, encoded, canonical(result)))
        return result


def daily(world, db, meta):
    """Run inside the physical day transaction before advancing meta.through."""
    from . import customer_cashflow

    if not enabled(db):
        return
    cashflow_active = customer_cashflow.enabled(db)
    day = meta['through']
    finish = (date.fromisoformat(day)+timedelta(days=1)).isoformat()+'T00:00:00Z'
    # Decode the town once, not once per baseline household. Profiles without a
    # current occupied physical premise are frozen, never implicitly reassigned.
    snapshot = json.loads(db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()[0])
    cohorts = {p['id']: ('baseline', bool(p.get('occupied', True))) for p in snapshot['premises']}
    if occupancy.enabled(db):
        cohorts.update({r['premise']: (r['applied_command'] or 'baseline', bool(r['occupied']))
                        for r in db.execute('SELECT premise,applied_command,occupied FROM occupancy_premises')})
    for profile in db.execute('SELECT * FROM customer_finance_profiles ORDER BY premise').fetchall():
        if db.execute('SELECT 1 FROM customer_finance_decisions WHERE premise=? AND day=?', (profile['premise'], day)).fetchone():
            continue
        db.execute('INSERT INTO customer_finance_decisions VALUES(?,?)', (profile['premise'], day))
        policy = json.loads(profile['policy'])
        stamp, occupied = cohorts.get(profile['premise'], (None, False))
        if cashflow_active:
            profile = customer_cashflow.apply_day(world, db, meta, profile, stamp, occupied)
        if not policy['active'] or not occupied or stamp != profile['stamp']:
            continue
        available = max(0, profile['cash']-profile['reserved']-policy['essentialReserveCents'])
        for invoice in db.execute('SELECT * FROM customer_finance_invoices WHERE premise=? AND due<=? '
                                  'ORDER BY due,id', (profile['premise'], day)).fetchall():
            # Hold one in-flight intent per invoice. Settlement confirmation, not
            # transport acknowledgment, allows another installment on a later day.
            if db.execute("SELECT 1 FROM customer_finance_intents WHERE invoice=? AND payment_state='reserved'",
                          (invoice['id'],)).fetchone():
                continue
            amount = min(available, invoice['amount']-invoice['settled'], policy['maxPaymentCents'])
            if amount <= 0 or draw(meta['seed'], VERSION, profile['recipient'], invoice['id'], day, 'pay') >= policy['paymentProbability']:
                continue
            identity = 'PAY-'+stable(meta['environment'], VERSION, profile['recipient'], invoice['id'], day)
            intent = {'schemaVersion': INTENT_VERSION, 'id': identity, 'environmentId': meta['environment'],
                      'runId': meta['environment'], 'premiseId': profile['premise'], 'recipientRef': profile['recipient'],
                      'customerKind': policy['customerKind'], 'invoiceId': invoice['id'],
                      'deliveredDocumentId': invoice['created_delivery'], 'currency': 'USD', 'amountCents': amount,
                      'createdAt': finish, 'availableAt': finish, 'purpose': 'simulated_invoice_payment'}
            world.event(db, meta['environment'], day, 'CustomerPaymentIntended', profile['premise'],
                        {'intent': intent, 'policyCause': profile['cause'], 'occupancyStamp': stamp}, invoice['created_delivery'])
            db.execute('INSERT INTO customer_finance_intents(id,premise,invoice,amount,available_at,envelope,fingerprint) '
                       'VALUES(?,?,?,?,?,?,?)', (identity, profile['premise'], invoice['id'], amount, finish,
                                                canonical(intent), stable(intent)))
            db.execute('UPDATE customer_finance_profiles SET reserved=reserved+?,revision=revision+1 WHERE premise=?',
                       (amount, profile['premise']))
            available -= amount


def provider_receipt(world, receipt):
    """Trusted provider confirmation; version 2 also supports terminal failure.

    Each intent permits exactly one settlement and one full return. Distinct
    receipt IDs cannot repeat a transition. Failure confirms no settlement ever
    occurred or will occur for this intent; transport errors are not evidence.
    """
    fields = {'schemaVersion', 'receiptId', 'environmentId', 'worldFingerprint', 'runId', 'intentId',
              'intentFingerprint', 'status', 'amountCents', 'currency', 'occurredAt', 'settlementReceiptId'}
    if (not isinstance(receipt, dict) or set(receipt) != fields
            or receipt['schemaVersion'] not in (RECEIPT_VERSION, RECEIPT_VERSION_2)):
        raise ValueError('Invalid simulated provider receipt.')
    for key in fields - {'amountCents', 'settlementReceiptId'}:
        _text(receipt[key])
    _cents(receipt['amountCents'], 1)
    _time(receipt['occurredAt'])
    statuses = ('settled', 'returned', 'failed') if receipt['schemaVersion'] == RECEIPT_VERSION_2 else ('settled', 'returned')
    if receipt['currency'] != 'USD' or receipt['status'] not in statuses:
        raise ValueError('Only full simulated USD settlements and returns are supported.')
    if receipt['status'] in ('settled', 'failed') and receipt['settlementReceiptId'] is not None:
        raise ValueError('Settlement or terminal failure cannot reference an earlier settlement.')
    if receipt['status'] == 'returned':
        _text(receipt['settlementReceiptId'])
    encoded = canonical(receipt)
    with world.db() as db:
        meta = _meta(db)
        _identity(meta, receipt)
        if not enabled(db):
            raise ValueError('Customer finance is not configured.')
        identity = 'provider:' + receipt['receiptId']
        prior = _retry(db, 'customer_finance_inbox', identity, encoded)
        if prior:
            return prior
        row = db.execute('SELECT * FROM customer_finance_intents WHERE id=?', (receipt['intentId'],)).fetchone()
        if not row or row['fingerprint'] != receipt['intentFingerprint'] or receipt['amountCents'] != row['amount']:
            raise ValueError('Unknown intent, fingerprint mismatch, or unsupported partial receipt.')
        if not row['available_at'] <= receipt['occurredAt'] <= meta['through']+'T00:00:00Z':
            raise ValueError('Receipt time must follow intent availability and not exceed the world clock.')
        status = receipt['status']
        # A late acknowledgment is not required: a provider can settle and lose
        # the transport reply. The confirmed receipt is stronger evidence.
        if status == 'settled' and row['payment_state'] != 'reserved':
            raise ValueError('Intent already settled, returned or failed; replay the original receipt ID.')
        if status == 'failed' and row['payment_state'] != 'reserved':
            raise ValueError('Terminal failure requires an unspent reserved intent; replay the original receipt ID.')
        if status == 'returned':
            settlement = db.execute('SELECT payload FROM customer_finance_inbox WHERE id=?',
                                    ('provider:'+receipt['settlementReceiptId'],)).fetchone()
            original = json.loads(settlement[0]) if settlement else {}
            if (row['payment_state'] != 'settled' or original.get('status') != 'settled' or
                    original.get('intentId') != receipt['intentId'] or original['occurredAt'] > receipt['occurredAt']):
                raise ValueError('Full return must reference this intent\'s confirmed settlement.')
        amount = row['amount']
        if status == 'settled':
            db.execute('UPDATE customer_finance_profiles SET cash=cash-?,reserved=reserved-?,settled=settled+?,revision=revision+1 '
                       'WHERE premise=?', (amount, amount, amount, row['premise']))
            db.execute('UPDATE customer_finance_invoices SET settled=settled+? WHERE id=?', (amount, row['invoice']))
        elif status == 'returned':
            current_cash = db.execute('SELECT cash FROM customer_finance_profiles WHERE premise=?', (row['premise'],)).fetchone()[0]
            _cents(current_cash + amount)
            db.execute('UPDATE customer_finance_profiles SET cash=cash+?,settled=settled-?,revision=revision+1 WHERE premise=?',
                       (amount, amount, row['premise']))
            db.execute('UPDATE customer_finance_invoices SET settled=settled-? WHERE id=?', (amount, row['invoice']))
        else:
            db.execute('UPDATE customer_finance_profiles SET reserved=reserved-?,revision=revision+1 WHERE premise=?',
                       (amount, row['premise']))
        db.execute('UPDATE customer_finance_intents SET payment_state=? WHERE id=?', (status, row['id']))
        event_type = {'settled': 'CustomerPaymentSettled', 'returned': 'CustomerPaymentReturned',
                      'failed': 'CustomerPaymentFailed'}[status]
        event = world.event(db, meta['environment'], meta['through'], event_type, row['premise'], receipt, row['id'])
        result = {'receiptId': receipt['receiptId'], 'status': 'recorded', 'eventId': event}
        db.execute('INSERT INTO customer_finance_inbox VALUES(?,?,?)', (identity, encoded, canonical(result)))
        return result


def _page(after, limit):
    if type(after) is not int or not 0 <= after <= 9223372036854775807 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid payment intent page.')


def ready(world, after=0, limit=25):
    """Filtered committed intention feed, never cash/policy truth or paid status."""
    _page(after, limit)
    with world.db() as db:
        meta = _meta(db)
        rows = [] if not enabled(db) else db.execute('SELECT * FROM customer_finance_intents WHERE sequence>? AND available_at<=? '
                                                    'ORDER BY sequence LIMIT ?', (after, meta['through']+'T00:00:00Z', limit+1)).fetchall()
        items = []
        for row in rows[:limit]:
            intent = json.loads(row['envelope'])
            if stable(intent) != row['fingerprint']:
                raise ValueError('Stored payment intent checksum mismatch.')
            items.append({'cursor': row['sequence'], 'intent': intent})
        return {'schemaVersion': INTENT_VERSION, 'environmentId': meta.get('environment'), 'items': items,
                'nextAfter': items[-1]['cursor'] if len(rows) > limit else None}


def relay(world, send, limit=25):
    """At-least-once delivery; recipient must deduplicate runId/id/fingerprint."""
    _page(0, limit)
    accepted = 0
    for _ in range(limit):
        with world.db() as db:
            if not enabled(db):
                break
            meta = _meta(db)
            row = db.execute("SELECT * FROM customer_finance_intents WHERE delivery_state='pending' AND available_at<=? "
                             'ORDER BY sequence LIMIT 1', (meta['through']+'T00:00:00Z',)).fetchone()
            if row is None:
                break
            intent = json.loads(row['envelope'])
            if stable(intent) != row['fingerprint']:
                raise ValueError('Stored payment intent checksum mismatch.')
            db.execute('UPDATE customer_finance_intents SET attempts=attempts+1 WHERE id=?', (row['id'],))
        try:
            receipt = send(intent)
            if (not isinstance(receipt, dict) or set(receipt) != {'id', 'runId', 'fingerprint', 'status', 'receiptId'} or
                    receipt['id'] != row['id'] or receipt['runId'] != intent['runId'] or
                    receipt['fingerprint'] != row['fingerprint'] or receipt['status'] != 'accepted'):
                raise ValueError('Recipient did not acknowledge this payment intent.')
            _text(receipt['receiptId'])
        except Exception as exc:
            error = type(exc).__name__
            with world.db() as db:
                db.execute("UPDATE customer_finance_intents SET last_error=? WHERE id=? AND delivery_state='pending'", (error, row['id']))
            return {'accepted': accepted, 'blocked': row['id'], 'error': error}
        with world.db() as db:
            accepted += db.execute("UPDATE customer_finance_intents SET delivery_state='accepted',receipt=?,last_error=NULL "
                                   "WHERE id=? AND delivery_state='pending'", (canonical(receipt), row['id'])).rowcount
    return {'accepted': accepted, 'blocked': None, 'error': None}


def inspect(world, premise):
    """Administrator-only cash truth, bounded to one configured premise."""
    _text(premise)
    with world.db() as db:
        meta = _meta(db)
        base = {'view': 'administrator-truth', 'modelVersion': VERSION, 'premiseId': premise,
                'environmentId': meta.get('environment'), 'runId': meta.get('environment'),
                'worldFingerprint': meta.get('fingerprint'), 'through': meta.get('through')}
        stamp, occupied = _stamp(db, premise)
        row = db.execute('SELECT * FROM customer_finance_profiles WHERE premise=?', (premise,)).fetchone() if enabled(db) else None
        if row is None:
            return {**base, 'configured': False, 'revision': 0, 'cohortBlocked': not occupied}
        policy = json.loads(row['policy'])
        totals = db.execute('SELECT COALESCE(SUM(amount-settled),0) FROM customer_finance_invoices WHERE premise=?', (premise,)).fetchone()[0]
        return {**base, 'configured': True,
                'recipientRef': row['recipient'], 'policy': policy, 'revision': row['revision'],
                'cashCents': row['cash'], 'reservedCashCents': row['reserved'], 'netSettledCashCents': row['settled'],
                'spendableCashCents': max(0, row['cash']-row['reserved']-policy['essentialReserveCents']),
                'knownOutstandingCents': totals, 'unreservedKnownOutstandingCents': totals-row['reserved'],
                'cohortBlocked': not occupied or row['stamp'] != stamp}
