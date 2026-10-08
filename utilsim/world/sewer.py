"""Sanitary lateral truth: water-derived inflow, blockages, storage and overflow.

This opt-in model has no sewer meters and never changes observation-derived bills.
"""
import json
import math
from datetime import date
from decimal import Decimal, InvalidOperation

from .migrations import rollback_backup
from .store import canonical, draw, stable

VERSION = "world-sewer/1"
DEFAULT_POLICY = {"annualProbability": 0.0, "returnFactor": "0.9", "storageM3": "0.25",
                  "blockedCapacityM3PerDay": "0", "revision": 0, "cause": None}
PRECISION = Decimal("0.0001")


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='sewerModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported sewer model version.")
    return row is not None


def _decimal(value, maximum):
    try:
        if not isinstance(value, str):
            raise ValueError("Physical quantities must be decimal strings.")
        number = Decimal(value)
        if (not number.is_finite() or not 0 <= number <= maximum
                or number.normalize().as_tuple().exponent < -4):
            raise ValueError(f"Physical quantity must be between 0 and {maximum}, with up to four decimals.")
    except InvalidOperation as exc:
        raise ValueError("Invalid physical quantity.") from exc
    return format(number.normalize(), "f")


def _service(db, water_asset, environment):
    asset = db.execute("SELECT * FROM assets WHERE id=? AND commodity='water'", (water_asset,)).fetchone()
    if not asset:
        raise ValueError("Choose an existing water service for its derived sewer lateral.")
    # Exactly the existing observation/2 service identity; replacement devices do not change it.
    point = "SEWER-SP-" + stable(environment, asset["installation"])
    return {"id": point, "lateral": "LATERAL-" + stable(environment, point), "water_asset": water_asset,
            "premise": asset["premise"], "installed": asset["installed"]}


def _enable(world, db):
    if enabled(db):
        return
    backup = rollback_backup(world, "sewer")
    for sql in (
        "CREATE TABLE sewer_services(id TEXT PRIMARY KEY,lateral TEXT UNIQUE NOT NULL,water_asset TEXT UNIQUE NOT NULL,"
        "premise TEXT NOT NULL,installed TEXT NOT NULL)",
        "CREATE TABLE sewer_storage(service TEXT PRIMARY KEY,retained TEXT NOT NULL,day TEXT)",
        "CREATE TABLE sewer_slots(service TEXT PRIMARY KEY,revision INTEGER NOT NULL)",
        "CREATE TABLE sewer_faults(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,service TEXT NOT NULL,"
        "opened_date TEXT NOT NULL,cleared_date TEXT,capacity TEXT NOT NULL,source TEXT NOT NULL,cause TEXT NOT NULL,"
        "open_event TEXT NOT NULL,clear_event TEXT,work_order TEXT)",
        "CREATE UNIQUE INDEX sewer_fault_active ON sewer_faults(service) WHERE cleared_date IS NULL",
        "CREATE INDEX sewer_fault_history ON sewer_faults(service,sequence)",
        "CREATE TABLE sewer_flows(service TEXT,day TEXT,water_asset TEXT NOT NULL,water_quantity TEXT NOT NULL,"
        "excluded_leak TEXT NOT NULL,return_factor TEXT NOT NULL,inflow TEXT NOT NULL,previous_retained TEXT NOT NULL,"
        "transported TEXT NOT NULL,retained TEXT NOT NULL,overflow TEXT NOT NULL,fault_id TEXT,policy_event TEXT,"
        "previous_day TEXT,PRIMARY KEY(service,day))",
    ):
        db.execute(sql)
    meta = world.metadata(db)
    for row in db.execute("SELECT id FROM assets WHERE commodity='water' ORDER BY id").fetchall():
        s = _service(db, row[0], meta["environment"])
        db.execute("INSERT INTO sewer_services VALUES(:id,:lateral,:water_asset,:premise,:installed)", s)
        db.execute("INSERT INTO sewer_storage VALUES(?,'0.0000',NULL)", (s["id"],))
    world.put(db, "sewerModelVersion", VERSION)
    world.put(db, "sewerRollbackBackup", backup)
    world.put(db, "sewerPolicy", DEFAULT_POLICY)


def state(db, service):
    if not enabled(db):
        return {"revision": 0, "active": None, "retained": "0.0000", "lastDay": None}
    slot = db.execute("SELECT revision FROM sewer_slots WHERE service=?", (service,)).fetchone()
    active = db.execute("SELECT * FROM sewer_faults WHERE service=? AND cleared_date IS NULL", (service,)).fetchone()
    storage = db.execute("SELECT * FROM sewer_storage WHERE service=?", (service,)).fetchone()
    return {"revision": slot[0] if slot else 0, "active": dict(active) if active else None,
            "retained": storage["retained"] if storage else "0.0000", "lastDay": storage["day"] if storage else None}


def _revision(db, service):
    db.execute("INSERT INTO sewer_slots VALUES(?,1) ON CONFLICT(service) DO UPDATE SET revision=revision+1", (service,))
    return state(db, service)["revision"]


def _start(world, db, meta, service, capacity, source, cause, actor, reason):
    if state(db, service)["active"]:
        raise ValueError("This lateral already has an active blockage.")
    identity = "BLOCK-" + stable(meta["environment"], meta["through"], service, cause)
    revision = _revision(db, service)
    event = world.event(db, meta["environment"], meta["through"], "PhysicalSewerBlocked", service,
                        {"faultId": identity, "capacityM3PerDay": capacity, "source": source, "actorId": actor,
                         "reason": reason, "revision": revision, "modelVersion": VERSION}, cause)
    db.execute("INSERT INTO sewer_faults(id,service,opened_date,capacity,source,cause,open_event) VALUES(?,?,?,?,?,?,?)",
               (identity, service, meta["through"], capacity, source, cause, event))
    return {"faultId": identity, "eventId": event, "revision": revision}


def command(world, payload):
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "expectedRevision",
              "effectiveDate", "action", "reason", "causalReference"}
    if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
        raise ValueError("Sewer command must identify an action.")
    action = payload["action"]
    extra = {"configure": {"annualProbability", "returnFactor", "storageM3", "blockedCapacityM3PerDay"},
             "start": {"waterAssetId", "servicePointId", "capacityM3PerDay"},
             "clear": {"waterAssetId", "servicePointId", "faultId", "workOrderId"}}.get(action)
    if extra is None or set(payload) != common | extra or payload.get("schemaVersion") != VERSION:
        raise ValueError("Invalid sewer command contract.")
    if payload["actorId"] != "world-admin":
        raise ValueError("Local world administrator required.")
    for key in (common | extra) - {"annualProbability", "expectedRevision"}:
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 512:
            raise ValueError("Command text must be nonempty and at most 512 characters.")
    if type(payload["expectedRevision"]) is not int or payload["expectedRevision"] < 0:
        raise ValueError("Expected revision must be a nonnegative integer.")
    if action == "configure":
        probability = payload["annualProbability"]
        if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("Annual probability must be between zero and one.")
        policy = {key: _decimal(payload[key], 1 if key == "returnFactor" else 10000)
                  for key in ("returnFactor", "storageM3", "blockedCapacityM3PerDay")}
    elif action == "start":
        capacity = _decimal(payload["capacityM3PerDay"], 10000)
    encoded = canonical(payload)
    with world.db() as db:
        meta = world.metadata(db)
        if payload["environmentId"] != meta.get("environment") or payload["worldFingerprint"] != meta.get("fingerprint"):
            raise ValueError("World identity mismatch.")
        old = db.execute("SELECT * FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
        if old:
            if old["payload"] != encoded:
                raise ValueError("Conflicting command retry.")
            return json.loads(old["result"])
        if payload["effectiveDate"] != meta["through"]:
            raise ValueError("World date changed. Reload before making changes.")
        if action == "configure":
            expected = meta.get("sewerPolicy", DEFAULT_POLICY)["revision"]
        else:
            service = _service(db, payload["waterAssetId"], meta["environment"])
            if service["id"] != payload["servicePointId"]:
                raise ValueError("Sewer service identity mismatch.")
            if service["installed"] > meta["through"]:
                raise ValueError("Cannot affect a service before commissioning.")
            current = state(db, service["id"])
            expected = current["revision"]
            if action == "start" and current["active"]:
                raise ValueError("This lateral already has an active blockage.")
            if action == "clear" and (not current["active"] or current["active"]["id"] != payload["faultId"]):
                raise ValueError("Clearance must reference this lateral's active fault.")
        if payload["expectedRevision"] != expected:
            raise ValueError("Sewer revision changed. Reload before making changes.")
        _enable(world, db)
        if action == "configure":
            event = world.event(db, meta["environment"], meta["through"], "SewerPolicyChanged", meta["town"],
                                {**payload, "revision": expected+1}, payload["commandId"])
            world.put(db, "sewerPolicy", {**policy, "annualProbability": probability, "revision": expected+1, "cause": event})
            result = {"eventId": event, "revision": expected+1}
        elif action == "start":
            result = _start(world, db, meta, service["id"], capacity, "manual", payload["commandId"],
                            payload["actorId"], payload["reason"])
        else:
            revision = _revision(db, service["id"])
            event = world.event(db, meta["environment"], meta["through"], "PhysicalSewerCleared", service["id"],
                                {**payload, "revision": revision}, payload["commandId"])
            db.execute("UPDATE sewer_faults SET cleared_date=?,clear_event=?,work_order=? WHERE id=?",
                       (meta["through"], event, payload["workOrderId"], payload["faultId"]))
            result = {"eventId": event, "revision": revision, "faultId": payload["faultId"]}
        result.update(commandId=payload["commandId"], status="completed", effectiveDate=meta["through"], modelVersion=VERSION)
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def flow(world, db, asset, day, quantity, meta):
    if asset["commodity"] != "water" or not enabled(db):
        return
    service = db.execute("SELECT * FROM sewer_services WHERE water_asset=?", (asset["id"],)).fetchone()
    if service is None:
        raise ValueError("Sewer mapping missing for water service; extend it through a service lifecycle command.")
    identity = service["id"]
    current, policy = state(db, identity), meta["sewerPolicy"]
    if not current["active"] and policy["annualProbability"] > 0:
        cleared_today = db.execute("SELECT 1 FROM sewer_faults WHERE service=? AND cleared_date=? LIMIT 1", (identity, day)).fetchone()
        hazard = 1 - (1-policy["annualProbability"]) ** (1/365.2425)
        if not cleared_today and draw(meta["seed"], day, identity, VERSION, "start") < hazard:
            _start(world, db, meta, identity, policy["blockedCapacityM3PerDay"], "seeded", policy["cause"],
                   "world-system", "Seeded daily blockage hazard")
            current = state(db, identity)
    water = Decimal(f"{quantity:.4f}")
    excluded = Decimal(0)
    # Existing downstream leak model is treated as ground loss, not sanitary return.
    if "waterFaultModelVersion" in meta:
        leak = db.execute("SELECT leak_quantity FROM water_fault_effects WHERE asset=? AND day=?", (asset["id"], day)).fetchone()
        excluded = Decimal(leak[0]) if leak else Decimal(0)
    inflow = ((water-excluded) * Decimal(policy["returnFactor"])).quantize(PRECISION)
    previous = Decimal(current["retained"])
    total = previous + inflow
    active = current["active"]
    transported = min(total, Decimal(active["capacity"])) if active else total
    retained = min(total-transported, Decimal(policy["storageM3"]))
    overflow = total-transported-retained
    db.execute("INSERT INTO sewer_flows VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (identity, day, asset["id"], str(water), str(excluded), policy["returnFactor"], str(inflow),
                str(previous), str(transported), str(retained), str(overflow), active["id"] if active else None,
                policy["cause"], current["lastDay"]))
    db.execute("UPDATE sewer_storage SET retained=?,day=? WHERE service=?", (str(retained), day, identity))


def inspect(world, water_asset, before=None, before_day=None, limit=25):
    if (not isinstance(water_asset, str) or not water_asset or len(water_asset) > 512
            or type(limit) is not int or not 1 <= limit <= 50
            or (before is not None and (type(before) is not int or not 1 <= before <= 9223372036854775807))
            or (before_day is not None and (not isinstance(before_day, str) or len(before_day) != 10))):
        raise ValueError("Invalid sewer service or history page.")
    if before_day is not None and date.fromisoformat(before_day).isoformat() != before_day:
        raise ValueError("Use a canonical history date.")
    with world.db() as db:
        meta = world.metadata(db)
        service = _service(db, water_asset, meta["environment"])
        history, flows = [], []
        if enabled(db):
            history = [dict(r) for r in db.execute("SELECT * FROM sewer_faults WHERE service=? AND sequence<? "
                       "ORDER BY sequence DESC LIMIT ?", (service["id"], before or 9223372036854775807, limit+1))]
            flows = [dict(r) for r in db.execute("SELECT * FROM sewer_flows WHERE service=? AND day<? ORDER BY day DESC LIMIT ?",
                                                 (service["id"], before_day or "9999-12-31", limit+1))]
        return {"view": "administrator-truth", "modelVersion": VERSION, "enabled": enabled(db), "service": service,
                "through": meta["through"], "environmentId": meta["environment"], "worldFingerprint": meta["fingerprint"],
                "current": state(db, service["id"]), "policy": meta.get("sewerPolicy", DEFAULT_POLICY),
                "history": history[:limit], "nextBefore": history[limit-1]["sequence"] if len(history) > limit else None,
                "flows": flows[:limit], "nextDay": flows[limit-1]["day"] if len(flows) > limit else None}


def map_state(db, water_asset, environment):
    if not enabled(db):
        return None
    service = _service(db, water_asset, environment)
    latest = db.execute("SELECT * FROM sewer_flows WHERE service=? ORDER BY day DESC LIMIT 1", (service["id"],)).fetchone()
    return {"service": service, "current": state(db, service["id"]), "latest": dict(latest) if latest else None}
