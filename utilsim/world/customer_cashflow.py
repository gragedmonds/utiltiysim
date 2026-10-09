"""Administrator-configured recurring cashflows within the existing finance owner."""
import json
from datetime import date

from . import customer_finance as finance
from .migrations import rollback_backup
from .store import canonical

VERSION = 'world-customer-cashflow/1'
POLICY = {'active', 'income', 'essentialExpense', 'insufficientCashPolicy', 'incomeOverflowPolicy'}
COMMON = {'schemaVersion', 'commandId', 'environmentId', 'runId', 'worldFingerprint', 'actorId',
          'expectedRevision', 'effectiveDate', 'action', 'premiseId', 'recipientRef', 'reason', 'causalReference'}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='customerCashflowModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError('Unsupported customer cashflow model version.')
    return row is not None


def _enable(world, db):
    if enabled(db):
        return
    backup = rollback_backup(world, 'customer-cashflow')
    db.execute('CREATE TABLE customer_cashflow_policies(premise TEXT PRIMARY KEY,recipient TEXT NOT NULL,'
               'occupancy_stamp TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,cause TEXT NOT NULL)')
    db.execute('CREATE TABLE customer_cashflow_days(premise TEXT NOT NULL,day TEXT NOT NULL,payload TEXT NOT NULL,'
               'event_id TEXT NOT NULL,PRIMARY KEY(premise,day))')
    world.put(db, 'customerCashflowModelVersion', VERSION)
    world.put(db, 'customerCashflowRollbackBackup', backup)


def _validate(payload):
    if (not isinstance(payload, dict) or set(payload) != COMMON | POLICY
            or payload['schemaVersion'] != VERSION or payload['action'] != 'configure'):
        raise ValueError('Invalid customer cashflow command.')
    for key in COMMON - {'expectedRevision'}:
        finance._text(payload[key])
    finance._cents(payload['expectedRevision'])
    finance._date(payload['effectiveDate'])
    if payload['actorId'] != 'world-admin':
        raise ValueError('Local world administrator required.')
    if type(payload['active']) is not bool:
        raise ValueError('Choose an explicit active flag.')
    if payload['insufficientCashPolicy'] not in ('available-cash', 'all-or-nothing'):
        raise ValueError('Choose available-cash or all-or-nothing expense funding.')
    if payload['incomeOverflowPolicy'] != 'skip-with-record':
        raise ValueError('Income beyond the cash limit must use skip-with-record.')
    for key in ('income', 'essentialExpense'):
        stream = payload[key]
        if not isinstance(stream, dict) or set(stream) != {'amountCents', 'firstDate', 'intervalDays'}:
            raise ValueError('Each stream requires amountCents, firstDate and intervalDays.')
        finance._cents(stream['amountCents'])
        finance._date(stream['firstDate'])
        if type(stream['intervalDays']) is not int or not 1 <= stream['intervalDays'] <= 366:
            raise ValueError('Cadence must be 1 to 366 whole UTC days.')


def command(world, payload):
    """Configure explicit assumptions; never reset cash or bind a replacement cohort."""
    _validate(payload)
    encoded = canonical(payload)
    with world.db() as db:
        meta = finance._meta(db)
        finance._identity(meta, payload)
        prior = finance._retry(db, 'commands', payload['commandId'], encoded)
        if prior:
            return prior
        profile = db.execute('SELECT * FROM customer_finance_profiles WHERE premise=?',
                             (payload['premiseId'],)).fetchone() if finance.enabled(db) else None
        if not profile:
            raise ValueError('Configure a customer cash profile first.')
        stamp, occupied = finance._stamp(db, payload['premiseId'])
        if not occupied or stamp != profile['stamp'] or payload['recipientRef'] != profile['recipient']:
            raise ValueError('Recipient or occupied customer cohort does not match.')
        old = db.execute('SELECT * FROM customer_cashflow_policies WHERE premise=?',
                         (payload['premiseId'],)).fetchone() if enabled(db) else None
        revision = old['revision'] if old else 0
        if payload['effectiveDate'] != meta['through'] or payload['expectedRevision'] != revision:
            raise ValueError('Customer cashflow revision or world date changed. Reload before editing.')
        previous = json.loads(old['payload']) if old else {}
        for key in ('income', 'essentialExpense'):
            anchor = payload[key]['firstDate']
            if anchor < meta['through'] and anchor != previous.get(key, {}).get('firstDate'):
                raise ValueError('A new stream anchor cannot precede the next unprocessed day.')
        _enable(world, db)
        policy = {key: payload[key] for key in POLICY}
        event = world.event(db, meta['environment'], meta['through'], 'CustomerCashflowConfigured',
                            payload['premiseId'], payload, payload['causalReference'])
        db.execute('INSERT INTO customer_cashflow_policies VALUES(?,?,?,?,?,?) '
                   'ON CONFLICT(premise) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,cause=excluded.cause',
                   (profile['premise'], profile['recipient'], stamp, revision+1, canonical(policy), event))
        result = {'commandId': payload['commandId'], 'status': 'completed', 'revision': revision+1,
                  'eventId': event, 'effectiveDate': meta['through'], 'modelVersion': VERSION}
        db.execute('INSERT INTO commands VALUES(?,?,?)', (payload['commandId'], encoded, canonical(result)))
        return result


def _due(stream, day):
    elapsed = (date.fromisoformat(day)-date.fromisoformat(stream['firstDate'])).days
    return stream['amountCents'] if elapsed >= 0 and elapsed % stream['intervalDays'] == 0 else 0


def apply_day(world, db, meta, profile, stamp, occupied):
    """Apply within the caller's physical-day transaction, before payment decisions.

    Caller checks enabled once per day. Cashflow activity is independent of the
    existing payment-intention policy's active flag. Return the current profile.
    """
    row = db.execute('SELECT * FROM customer_cashflow_policies WHERE premise=?', (profile['premise'],)).fetchone()
    if not row:
        return profile
    day = meta['through']
    if db.execute('SELECT 1 FROM customer_cashflow_days WHERE premise=? AND day=?', (profile['premise'], day)).fetchone():
        return db.execute('SELECT * FROM customer_finance_profiles WHERE premise=?', (profile['premise'],)).fetchone()
    policy = json.loads(row['payload'])
    income, expense = _due(policy['income'], day), _due(policy['essentialExpense'], day)
    opening, reserved = profile['cash'], profile['reserved']
    status = ('cohort_changed' if stamp != row['occupancy_stamp'] or profile['recipient'] != row['recipient']
              else 'vacant' if not occupied else 'paused' if not policy['active'] else 'applied')
    credited = paid = 0
    income_status = 'not_due' if not income else status
    expense_status = 'not_due' if not expense else status
    if status == 'applied':
        if income:
            credited = income if opening + income <= finance.MAX_CENTS else 0
            income_status = 'credited' if credited else 'cash_limit'
        available = opening + credited - reserved
        if expense:
            paid = min(expense, available) if policy['insufficientCashPolicy'] == 'available-cash' else (
                expense if expense <= available else 0)
            expense_status = 'paid' if paid == expense else 'partially_paid' if paid else 'insufficient_cash'
        if not income and not expense:
            status = 'no_occurrence'
    closing = opening + credited - paid
    record = {'day': day, 'policyRevision': row['revision'], 'incomeDueCents': income,
              'incomeCreditedCents': credited, 'incomeSkippedCents': income-credited,
              'expenseDueCents': expense, 'expensePaidCents': paid, 'expenseUnfundedCents': expense-paid,
              'openingCashCents': opening, 'closingCashCents': closing, 'reservedCashCents': reserved,
              'status': status, 'incomeStatus': income_status, 'expenseStatus': expense_status}
    # The payment floor protects necessities from utility intentions. Necessities
    # may spend that floor, but cannot consume already reserved provider money.
    if credited or paid:
        db.execute('UPDATE customer_finance_profiles SET cash=?,revision=revision+1 WHERE premise=?',
                   (closing, profile['premise']))
    event = world.event(db, meta['environment'], day, 'CustomerCashflowApplied', profile['premise'],
                        {'modelVersion': VERSION, 'recipientRef': row['recipient'], 'policy': policy, **record}, row['cause'])
    db.execute('INSERT INTO customer_cashflow_days VALUES(?,?,?,?)', (profile['premise'], day, canonical(record), event))
    return db.execute('SELECT * FROM customer_finance_profiles WHERE premise=?', (profile['premise'],)).fetchone()


def inspect(world, premise, before=None, limit=25):
    """Administrator-only bounded history; never a customer/worker observation."""
    finance._text(premise)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Choose a history limit from 1 to 100.')
    if before is not None:
        finance._date(before)
    with world.db() as db:
        meta = finance._meta(db)
        if not meta:
            raise ValueError('Initialize a world first.')
        stamp, occupied = finance._stamp(db, premise)
        profile = db.execute('SELECT * FROM customer_finance_profiles WHERE premise=?',
                             (premise,)).fetchone() if finance.enabled(db) else None
        row = db.execute('SELECT * FROM customer_cashflow_policies WHERE premise=?',
                         (premise,)).fetchone() if enabled(db) else None
        history = [] if not row else [{**json.loads(r['payload']), 'eventId': r['event_id']} for r in db.execute(
            'SELECT payload,event_id FROM customer_cashflow_days WHERE premise=? AND day<? ORDER BY day DESC LIMIT ?',
            (premise, before or '9999-12-31', limit+1))]
        return {'view': 'administrator-truth', 'modelVersion': VERSION,
                'environmentId': meta['environment'], 'runId': meta['environment'], 'worldFingerprint': meta['fingerprint'],
                'through': meta['through'], 'premiseId': premise, 'financeConfigured': bool(profile),
                'recipientRef': profile['recipient'] if profile else None,
                'cohortBlocked': not occupied or bool(profile and stamp != profile['stamp']),
                'configured': bool(row), 'revision': row['revision'] if row else 0,
                'policy': json.loads(row['payload']) if row else None,
                'cashCents': profile['cash'] if profile else None, 'reservedCashCents': profile['reserved'] if profile else None,
                'history': history[:limit], 'nextBefore': history[limit-1]['day'] if len(history) > limit else None}
