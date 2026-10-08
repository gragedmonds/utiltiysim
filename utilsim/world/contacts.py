"""Customer experience, awareness and contact intent, separate from agent handling.

Only experienced supply loss / visible overflow can trigger this first version.
An internal fault, missing meter transmission or unreceived bill is not awareness.
"""
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from .migrations import rollback_backup
from .store import canonical, draw, stable

VERSION = "world-contacts/1"
INTENT_VERSION = "customer-contact-intent/1"
DEFAULT_POLICY = {"active": False, "noticeProbabilityPerDay": 0.5, "deliveryDelaySeconds": 86400,
                  "repeatAfterDays": 3, "maxContacts": 3, "revision": 0, "cause": None}


def _meta(db):
    # Inspection and relays do not need saved physical-network catalogs.
    return {r['key']: json.loads(r['value']) for r in db.execute(
        "SELECT key,value FROM meta WHERE key IN ('environment','fingerprint','through','town','contactPolicy')")}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='contactModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported customer-contact model version.")
    return row is not None


def _enable(world, db):
    if enabled(db):
        return
    backup = rollback_backup(world, "contacts")
    for sql in [
        "CREATE TABLE contact_episodes(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,"
        "asset TEXT,premise TEXT,commodity TEXT,condition TEXT,occupancy_stamp TEXT,started_day TEXT,"
        "last_day TEXT,ended_day TEXT,noticed_at TEXT,contacts INTEGER NOT NULL DEFAULT 0,last_contact_day TEXT,last_contact_id TEXT)",
        "CREATE UNIQUE INDEX contact_episode_open ON contact_episodes(asset,commodity,condition) WHERE ended_day IS NULL",
        "CREATE INDEX contact_episode_history ON contact_episodes(premise,sequence)",
        "CREATE TABLE contact_outbox(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,episode TEXT,premise TEXT,"
        "available_at TEXT,envelope TEXT,fingerprint TEXT,state TEXT NOT NULL DEFAULT 'pending',"
        "attempts INTEGER NOT NULL DEFAULT 0,receipt TEXT,last_error TEXT)",
        "CREATE INDEX contact_due ON contact_outbox(state,available_at,sequence)",
        "CREATE INDEX contact_availability ON contact_outbox(available_at,sequence)",
        "CREATE INDEX contact_history ON contact_outbox(premise,sequence)",
    ]:
        db.execute(sql)
    world.put(db, "contactModelVersion", VERSION)
    world.put(db, "contactPolicy", DEFAULT_POLICY)
    world.put(db, "contactRollbackBackup", backup)


def command(world, payload):
    fields = {"active", "noticeProbabilityPerDay", "deliveryDelaySeconds", "repeatAfterDays", "maxContacts"}
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "expectedRevision",
              "effectiveDate", "action", "reason", "causalReference"}
    if not isinstance(payload, dict) or set(payload) != fields | common or payload.get("schemaVersion") != VERSION or payload.get("action") != "configure":
        raise ValueError("Invalid customer-contact policy command.")
    for key in common-{"expectedRevision"}:
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 512:
            raise ValueError("Command text must be nonempty and at most 512 characters.")
    if payload["actorId"] != "world-admin":
        raise ValueError("Local world administrator required.")
    if type(payload["active"]) is not bool:
        raise ValueError("Active must be a boolean.")
    probability = payload["noticeProbabilityPerDay"]
    if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("Notice probability must be between zero and one.")
    for key, lo, hi in [("expectedRevision", 0, 2147483647), ("deliveryDelaySeconds", 0, 366*86400),
                        ("repeatAfterDays", 1, 365), ("maxContacts", 1, 10)]:
        if type(payload[key]) is not int or not lo <= payload[key] <= hi:
            raise ValueError("Invalid revision, delay or contact limit.")
    encoded = canonical(payload)
    with world.db() as db:
        meta = _meta(db)
        if payload["environmentId"] != meta.get("environment") or payload["worldFingerprint"] != meta.get("fingerprint"):
            raise ValueError("World identity mismatch.")
        old = db.execute("SELECT * FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
        if old:
            if old["payload"] != encoded:
                raise ValueError("Conflicting command retry.")
            return json.loads(old["result"])
        policy = meta.get("contactPolicy", DEFAULT_POLICY)
        if payload["expectedRevision"] != policy["revision"] or payload["effectiveDate"] != meta["through"]:
            raise ValueError("World date or contact-policy revision changed. Reload before editing.")
        _enable(world, db)
        revision = policy["revision"]+1
        event = world.event(db, meta["environment"], meta["through"], "CustomerContactPolicyChanged", meta["town"],
                            {**payload, "revision": revision}, payload["commandId"])
        world.put(db, "contactPolicy", {**{k: payload[k] for k in fields}, "revision": revision, "cause": event})
        result = {"commandId": payload["commandId"], "status": "completed", "revision": revision,
                  "eventId": event, "effectiveDate": meta["through"], "modelVersion": VERSION}
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def _symptoms(db, day, meta):
    """Translate experienced effects, never raw fault existence or missing reads."""
    symptoms = {}
    for prefix, table, field in [("networkFault", "network_fault_effects", "unserved_quantity"),
                                 ("waterMain", "water_main_effects", "unserved_m3")]:
        if prefix+"ModelVersion" not in meta:
            continue
        db.execute(f"CREATE INDEX IF NOT EXISTS contact_{table}_day ON {table}(day,asset)")
        for row in db.execute(f"SELECT asset,{field} FROM {table} WHERE day=?", (day,)):
            if Decimal(row[field]) > 0:
                symptoms[(row['asset'], 'no_supply')] = {"sourceTable": table, "day": day}
    if "sewerModelVersion" in meta:
        db.execute("CREATE INDEX IF NOT EXISTS contact_sewer_day ON sewer_flows(day,service)")
        for row in db.execute("SELECT s.water_asset,f.overflow,f.service FROM sewer_flows f "
                              "JOIN sewer_services s ON s.id=f.service WHERE f.day=?", (day,)):
            if Decimal(row['overflow']) > 0:
                symptoms[(row['water_asset'], 'visible_overflow')] = {"sourceTable": "sewer_flows", "day": day}
    return symptoms


def daily(world, db, meta):
    if not enabled(db):
        return
    day, policy = meta["through"], meta["contactPolicy"]
    finish = (date.fromisoformat(day)+timedelta(days=1)).isoformat()+"T00:00:00Z"
    changed = {}
    if "occupancyModelVersion" in meta:
        changed = {r['premise']: r['applied_command'] for r in db.execute('SELECT premise,applied_command FROM occupancy_premises')}
    current = set()
    for (asset_id, condition), evidence in sorted(_symptoms(db, day, meta).items()):
        asset = dict(db.execute('SELECT * FROM assets WHERE id=?', (asset_id,)).fetchone())
        profile = json.loads(asset['profile'])
        if not profile.get('occupied', True) or asset['installed'] > day:
            continue
        commodity = 'sewer' if condition == 'visible_overflow' else asset['commodity']
        key = (asset_id, commodity, condition)
        current.add(key)
        stamp = changed.get(asset['premise']) or 'baseline'
        row = db.execute('SELECT * FROM contact_episodes WHERE asset=? AND commodity=? AND condition=? AND ended_day IS NULL', key).fetchone()
        if row and row['occupancy_stamp'] != stamp:
            db.execute('UPDATE contact_episodes SET ended_day=? WHERE id=?', (day, row['id']))
            row = None
        if row is None:
            identity = 'EXP-'+stable(meta['environment'], asset_id, commodity, condition, stamp, day)
            db.execute('INSERT INTO contact_episodes(id,asset,premise,commodity,condition,occupancy_stamp,started_day,last_day) '
                       'VALUES(?,?,?,?,?,?,?,?)', (identity, asset_id, asset['premise'], commodity, condition, stamp, day, day))
            row = db.execute('SELECT * FROM contact_episodes WHERE id=?', (identity,)).fetchone()
        else:
            db.execute('UPDATE contact_episodes SET last_day=? WHERE id=?', (day, row['id']))
        if not policy['active'] or row['contacts'] >= policy['maxContacts']:
            continue
        if row['noticed_at'] is None and draw(meta['seed'], row['id'], day, VERSION, 'notice') >= policy['noticeProbabilityPerDay']:
            continue
        if row['last_contact_day'] and (date.fromisoformat(day)-date.fromisoformat(row['last_contact_day'])).days < policy['repeatAfterDays']:
            continue
        attempt = row['contacts']+1
        identity = 'CONTACT-'+stable(meta['environment'], row['id'], attempt)
        available = (datetime.fromisoformat(finish.replace('Z', '+00:00'))+
                     timedelta(seconds=policy['deliveryDelaySeconds'])).isoformat().replace('+00:00', 'Z')
        point = 'SP-'+stable(meta['environment'], asset['installation'])
        # Whitelist the customer's experience. Source tables, hidden causes,
        # precise physical quantities and policy parameters stay in owner events.
        intent = {'schemaVersion': INTENT_VERSION, 'id': identity, 'environmentId': meta['environment'],
                  'premiseId': asset['premise'], 'servicePointId': ('SEWER-' if commodity == 'sewer' else '')+point,
                  'commodity': commodity, 'callerKind': 'premise_occupants', 'condition': condition,
                  'experienceId': row['id'], 'observedAt': finish, 'noticedAt': row['noticed_at'] or finish,
                  'createdAt': finish, 'availableAt': available, 'attempt': attempt,
                  'previousContactId': row['last_contact_id'],
                  'reason': 'repeat_service_problem' if attempt > 1 else 'service_problem'}
        world.event(db, meta['environment'], day, 'CustomerContactIntentCreated', asset['premise'],
                    {'intentId': identity, 'experienceId': row['id'], 'evidence': evidence,
                     'policy': policy, 'occupancyStamp': stamp, 'assetId': asset_id}, policy['cause'])
        db.execute('INSERT INTO contact_outbox(id,episode,premise,available_at,envelope,fingerprint) VALUES(?,?,?,?,?,?)',
                   (identity, row['id'], asset['premise'], available, canonical(intent), stable(intent)))
        db.execute('UPDATE contact_episodes SET noticed_at=COALESCE(noticed_at,?),contacts=?,last_contact_day=?,last_contact_id=? WHERE id=?',
                   (finish, attempt, day, identity, row['id']))
    for row in db.execute('SELECT * FROM contact_episodes WHERE ended_day IS NULL').fetchall():
        if (row['asset'], row['commodity'], row['condition']) not in current:
            db.execute('UPDATE contact_episodes SET ended_day=? WHERE id=?', (day, row['id']))


def _page(after, limit):
    if type(after) is not int or not 0 <= after <= 9223372036854775807 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid contact page cursor or limit.')


def ready(world, after=None, limit=25):
    """Committed, available intents only. Never accepts a caller-supplied future clock."""
    _page(0, limit)
    since, sequence = '', 0
    if after is not None:
        if not isinstance(after, str) or len(after) > 100 or after.count('|') != 1:
            raise ValueError('Invalid availability cursor.')
        since, sequence = after.split('|')
        parsed = datetime.fromisoformat(since.replace('Z', '+00:00'))
        if not since.endswith('Z') or parsed.isoformat().replace('+00:00', 'Z') != since:
            raise ValueError('Use a canonical UTC availability cursor.')
        sequence = int(sequence)
        _page(sequence, limit)
    with world.db() as db:
        meta = _meta(db)
        if not meta:
            raise ValueError('Initialize a world first.')
        rows = [] if not enabled(db) else list(db.execute(
            "SELECT * FROM contact_outbox WHERE (available_at,sequence)>(?,?) "
            "AND available_at<=? ORDER BY available_at,sequence LIMIT ?",
            (since, sequence, meta['through']+'T00:00:00Z', limit+1)))
        items = []
        for row in rows[:limit]:
            intent = json.loads(row['envelope'])
            if stable(intent) != row['fingerprint']:
                raise ValueError('Stored contact checksum mismatch.')
            items.append({'cursor': row['available_at']+'|'+str(row['sequence']), 'intent': intent})
        return {'schemaVersion': INTENT_VERSION, 'environmentId': meta['environment'], 'items': items,
                'nextAfter': items[-1]['cursor'] if len(rows) > limit else None}


def relay(world, send, limit=25):
    """Dedicated adapter callback only; no live network sender or agent resolution.

    The recipient must deduplicate by environment/id and compare the fingerprint.
    Concurrent sends and lost receipts can repeat delivery, never change payload.
    """
    _page(0, limit)
    accepted = 0
    for _ in range(limit):
        with world.db() as db:
            meta = _meta(db)
            if not enabled(db):
                break
            row = db.execute("SELECT * FROM contact_outbox WHERE state='pending' AND available_at<=? "
                             "ORDER BY available_at,sequence LIMIT 1", (meta['through']+'T00:00:00Z',)).fetchone()
            if row is None:
                break
            intent = json.loads(row['envelope'])
            if stable(intent) != row['fingerprint']:
                raise ValueError('Stored contact checksum mismatch.')
            db.execute('UPDATE contact_outbox SET attempts=attempts+1 WHERE id=?', (row['id'],))
        try:
            receipt = send(intent)
            if (not isinstance(receipt, dict) or set(receipt) != {'id', 'environmentId', 'fingerprint', 'status', 'receiptId'}
                    or receipt['id'] != intent['id'] or receipt['environmentId'] != intent['environmentId']
                    or receipt['fingerprint'] != row['fingerprint'] or receipt['status'] != 'accepted'
                    or not isinstance(receipt['receiptId'], str) or not 0 < len(receipt['receiptId']) <= 512):
                raise ValueError('Recipient did not acknowledge this contact intent.')
            encoded = canonical(receipt)
        except Exception as exc:
            error = type(exc).__name__
            with world.db() as db:
                db.execute("UPDATE contact_outbox SET last_error=? WHERE id=? AND state='pending'", (error, row['id']))
            return {'accepted': accepted, 'blocked': row['id'], 'error': error}
        with world.db() as db:
            accepted += db.execute("UPDATE contact_outbox SET state='accepted',receipt=?,last_error=NULL "
                                   "WHERE id=? AND state='pending'", (encoded, row['id'])).rowcount
    return {'accepted': accepted, 'blocked': None, 'error': None}


def inspect(world, after=0, limit=25):
    _page(after, limit)
    with world.db() as db:
        meta = _meta(db)
        if not meta:
            raise ValueError('Initialize a world first.')
        present = enabled(db)
        rows = [] if not present else [dict(r) for r in db.execute(
            'SELECT * FROM contact_outbox WHERE sequence>? ORDER BY sequence LIMIT ?', (after, limit+1))]
        for row in rows:
            row['intent'] = json.loads(row.pop('envelope'))
            row['receipt'] = json.loads(row['receipt']) if row['receipt'] else None
            row['available'] = row['available_at'] <= meta['through']+'T00:00:00Z'
        counts = {} if not present else {r[0]: r[1] for r in db.execute('SELECT state,COUNT(*) FROM contact_outbox GROUP BY state')}
        return {'view': 'administrator-truth', 'modelVersion': VERSION, 'environmentId': meta['environment'],
                'worldFingerprint': meta['fingerprint'], 'through': meta['through'], 'enabled': present,
                'policy': meta.get('contactPolicy', DEFAULT_POLICY), 'items': rows[:limit], 'counts': counts,
                'nextAfter': rows[limit-1]['sequence'] if len(rows) > limit else None}
