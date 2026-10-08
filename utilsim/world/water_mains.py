"""Durable, opt-in water-main breaks. Administrator physical truth only.

Saved valves bound isolation; configured source connectivity determines supply.
Loss is a configured scenario rate, not a hydraulic pressure calculation.
"""
import json
import math
from collections import defaultdict
from decimal import Decimal

from utilsim.ops.materials import CAST_IRON_FACTOR

from .migrations import rollback_backup
from .network_faults import _reachable
from .store import canonical, draw, stable

VERSION = "world-water-mains/1"
DEFAULT_POLICY = {"breaksPer100kmYear": 0, "lossM3PerHour": "10", "revision": 0, "cause": None}
TRANSITIONS = {"isolate": ("broken", "isolated"), "repair": ("isolated", "repaired"),
               "restore": ("repaired", "restored")}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='waterMainModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported water-main model version.")
    return row is not None


def catalog(db):
    if enabled(db):
        return json.loads(db.execute("SELECT value FROM meta WHERE key='waterMainCatalog'").fetchone()[0])
    row = db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()
    if not row:
        raise ValueError("Initialize a world first.")
    snapshot = json.loads(row[0])
    net = snapshot.get("networks", {}).get("water", {})
    nodes = {n["id"] for n in net.get("nodes", [])}
    roots = net.get("sourceIds") or [net.get("sourceId")]
    if not nodes or not roots or any(n not in nodes for n in roots):
        raise ValueError("Saved water topology needs valid supply sources.")
    edges, ids = [], set()
    for e in net.get("edges", []):
        length = e.get("lengthM", 0)
        if (not isinstance(e.get("id"), str) or not e["id"] or e["id"] in ids
                or e.get("from") not in nodes or e.get("to") not in nodes
                or type(e.get("enabled", True)) is not bool or type(length) not in (int, float)
                or not math.isfinite(length) or length < 0):
            raise ValueError("Invalid saved water network edge.")
        ids.add(e["id"])
        edges.append({"id": e["id"], "a": e["from"], "b": e["to"], "kind": e.get("kind"),
                      "enabled": e.get("enabled", True), "lengthM": length, "material": e.get("material", "unknown")})
    valves = sorted({v["edgeId"] for v in net.get("equipment", [])
                     if v.get("kind") == "valve" and v.get("normally", "open") == "open"})
    if any(v not in ids for v in valves):
        raise ValueError("Saved valve refers to an unknown water edge.")
    reached, _ = _reachable(edges, roots)
    expected = {r[0] for r in db.execute("SELECT id FROM assets WHERE commodity='water'")}
    services, found = [], set()
    for sp in snapshot["servicePoints"]:
        if sp["commodity"] != "water":
            continue
        meter, node = sp["meterId"], sp.get("networkNodeId")
        if meter not in expected or meter in found or node not in reached:
            raise ValueError("Saved water service must have one connected network node.")
        found.add(meter)
        services.append({"asset": meter, "node": node, "premise": sp["premiseId"]})
    if found != expected:
        raise ValueError("Incomplete saved water service mapping.")
    return {"edges": sorted(edges, key=lambda e: e["id"]), "sources": sorted(set(roots)),
            "valves": valves, "services": sorted(services, key=lambda s: s["asset"])}


def section(cat, identity):
    """Port the legacy valve-boundary traversal, without its auto-dispatched work.

    Fail closed if the section contains a source; never invent a shut-off valve.
    Each saved valve closes its entire edge (the snapshot's lumped resolution).
    """
    edges = {e["id"]: e for e in cat["edges"] if e["enabled"]}
    edge = edges[identity]
    adjacency = defaultdict(list)
    for e in edges.values():
        adjacency[e["a"]].append(e)
        adjacency[e["b"]].append(e)
    seen, stack, closed = {edge["a"], edge["b"]}, [edge["a"], edge["b"]], {identity}
    valves = set(cat["valves"])
    while stack:
        for e in adjacency[stack.pop()]:
            if e["id"] in closed:
                continue
            if e["id"] in valves:
                closed.add(e["id"])
                continue
            for n in (e["a"], e["b"]):
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
    if seen.intersection(cat["sources"]):
        return None
    return sorted(closed)


def _enable(world, db, cat):
    if enabled(db):
        return
    backup = rollback_backup(world, "water-mains")
    for sql in [
        "CREATE TABLE water_main_slots(edge TEXT PRIMARY KEY,revision INTEGER NOT NULL)",
        "CREATE TABLE water_main_faults(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,edge TEXT,"
        "status TEXT,opened_date TEXT,restored_date TEXT,rate TEXT,source TEXT,cause TEXT,closed_edges TEXT,work_order TEXT)",
        "CREATE UNIQUE INDEX water_main_active ON water_main_faults(edge) WHERE status!='restored'",
        "CREATE INDEX water_main_history ON water_main_faults(edge,sequence)",
        "CREATE TABLE water_main_days(day TEXT,fault_id TEXT,status TEXT,loss_m3 TEXT,cause TEXT,PRIMARY KEY(day,fault_id))",
        "CREATE TABLE water_main_effects(asset TEXT,day TEXT,demand_m3 TEXT,unserved_m3 TEXT,"
        "fault_ids TEXT,PRIMARY KEY(asset,day))",
    ]:
        db.execute(sql)
    world.put(db, "waterMainCatalog", cat)
    world.put(db, "waterMainModelVersion", VERSION)
    world.put(db, "waterMainRollbackBackup", backup)
    world.put(db, "waterMainPolicy", DEFAULT_POLICY)


def state(db, edge):
    if not enabled(db):
        return {"revision": 0, "active": None}
    slot = db.execute("SELECT revision FROM water_main_slots WHERE edge=?", (edge,)).fetchone()
    active = db.execute("SELECT * FROM water_main_faults WHERE edge=? AND status!='restored'", (edge,)).fetchone()
    return {"revision": slot[0] if slot else 0, "active": dict(active) if active else None}


def _revision(db, edge):
    db.execute("INSERT INTO water_main_slots VALUES(?,1) ON CONFLICT(edge) DO UPDATE SET revision=revision+1", (edge,))
    return state(db, edge)["revision"]


def _start(world, db, meta, edge, rate, source, cause, evidence):
    identity = "MAIN-"+stable(meta["environment"], meta["through"], edge, cause)
    revision = _revision(db, edge)
    event = world.event(db, meta["environment"], meta["through"], "PhysicalWaterMainBroken", edge,
                        {"faultId": identity, "lossM3PerHour": rate, "source": source,
                         "revision": revision, "evidence": evidence, "modelVersion": VERSION}, cause)
    db.execute("INSERT INTO water_main_faults(id,edge,status,opened_date,rate,source,cause,closed_edges) "
               "VALUES(?,?,'broken',?,?,?,?, '[]')", (identity, edge, meta["through"], rate, source, event))
    return {"faultId": identity, "eventId": event, "revision": revision}


def _number(value, maximum, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum or (positive and value == 0):
        raise ValueError("Scenario rate is outside the allowed range.")
    return value


def command(world, payload):
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "expectedRevision",
              "effectiveDate", "action", "reason", "causalReference"}
    if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
        raise ValueError("Water-main command must identify an action.")
    action = payload["action"]
    extra = {"configure": {"breaksPer100kmYear", "lossM3PerHour"}, "start": {"edgeId", "lossM3PerHour"},
             **{a: {"edgeId", "faultId", "workOrderId"} for a in TRANSITIONS}}.get(action)
    if extra is None or set(payload) != common | extra or payload["schemaVersion"] != VERSION:
        raise ValueError("Invalid water-main command contract.")
    if payload["actorId"] != "world-admin":
        raise ValueError("Local world administrator required.")
    for key in (common | extra)-{"expectedRevision", "breaksPer100kmYear", "lossM3PerHour"}:
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 512:
            raise ValueError("Command text must be nonempty and at most 512 characters.")
    if type(payload["expectedRevision"]) is not int or payload["expectedRevision"] < 0:
        raise ValueError("Expected revision must be a nonnegative integer.")
    if "lossM3PerHour" in payload:
        rate = str(Decimal(str(_number(payload["lossM3PerHour"], 10000, True))))
    if action == "configure":
        frequency = _number(payload["breaksPer100kmYear"], 100000)
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
        cat, policy = catalog(db), meta.get("waterMainPolicy", DEFAULT_POLICY)
        if action == "configure":
            expected = policy["revision"]
        else:
            edge = payload["edgeId"]
            selected = next((e for e in cat["edges"] if e["id"] == edge), None)
            if not selected or not selected["enabled"] or selected["kind"] not in ("trunk", "distribution"):
                raise ValueError("Choose a normally enabled water trunk or distribution main.")
            current = state(db, edge)
            expected, active = current["revision"], current["active"]
            if action == "start" and active:
                raise ValueError("This main already has an active fault.")
            if action in TRANSITIONS and (not active or active["id"] != payload["faultId"]
                                         or active["status"] != TRANSITIONS[action][0]):
                raise ValueError("Invalid physical lifecycle transition or fault reference.")
            if action == "isolate":
                closed = section(cat, edge)
                if closed is None:
                    raise ValueError("Saved valves do not bound this section away from supply. Isolation is unavailable.")
        if expected != payload["expectedRevision"]:
            raise ValueError("Water-main revision changed. Reload before editing.")
        _enable(world, db, cat)
        if action == "configure":
            event = world.event(db, meta["environment"], meta["through"], "WaterMainPolicyChanged", meta["town"],
                                {**payload, "revision": expected+1}, payload["commandId"])
            world.put(db, "waterMainPolicy", {"breaksPer100kmYear": frequency, "lossM3PerHour": rate,
                                               "revision": expected+1, "cause": event})
            result = {"eventId": event, "revision": expected+1}
        elif action == "start":
            result = _start(world, db, meta, edge, rate, "manual", payload["commandId"], payload)
        else:
            revision = _revision(db, edge)
            event = world.event(db, meta["environment"], meta["through"], "WaterMainPhysicalAction", edge,
                                {**payload, "revision": revision, "closedEdges": closed if action == "isolate" else
                                 json.loads(active["closed_edges"])}, payload["commandId"])
            db.execute("UPDATE water_main_faults SET status=?,closed_edges=?,work_order=?,cause=?,restored_date=? WHERE id=?",
                       (TRANSITIONS[action][1], canonical(closed) if action == "isolate" else active["closed_edges"],
                        payload["workOrderId"], event, meta["through"] if action == "restore" else None, payload["faultId"]))
            result = {"eventId": event, "revision": revision, "faultId": payload["faultId"]}
        result.update(commandId=payload["commandId"], status="completed", effectiveDate=meta["through"], modelVersion=VERSION)
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def _supply(cat, faults):
    closed = {e for f in faults if f["status"] in ("isolated", "repaired") for e in json.loads(f["closed_edges"])}
    return _reachable(cat["edges"], cat["sources"], closed)[0]


def daily(world, db, meta):
    if not enabled(db):
        return {}
    cat, policy = catalog(db), meta["waterMainPolicy"]
    context = meta.get("_hazards")
    multiplier = context["multipliers"]["water"] if context else 1
    # Legacy exposure: main length, cast-iron weighting, annual breaks /100 km.
    # Per-edge survival probability replaces aggregate Poisson draws; at most one
    # active fault per main, independent named streams, no skipped repair work.
    if policy["breaksPer100kmYear"]:
        for e in cat["edges"]:
            if not e["enabled"] or e["kind"] not in ("trunk", "distribution") or state(db, e["id"])["active"]:
                continue
            if db.execute("SELECT 1 FROM water_main_faults WHERE edge=? AND restored_date=?", (e["id"], meta["through"])).fetchone():
                continue
            weight = CAST_IRON_FACTOR if str(e["material"]).lower() == "cast iron" else 1
            exposure = e["lengthM"]/1000 * weight
            probability = -math.expm1(-policy["breaksPer100kmYear"]*exposure*multiplier/(100*365))
            if draw(meta["seed"], meta["through"], e["id"], VERSION, "start") < probability:
                _start(world, db, meta, e["id"], policy["lossM3PerHour"], "seeded", policy["cause"],
                       {"policy": policy, "weightedKm": exposure, "multiplier": multiplier,
                        "dailyProbability": probability, "hazardDay": context["eventId"] if context else None})
    faults = [dict(r) for r in db.execute("SELECT * FROM water_main_faults WHERE status!='restored' ORDER BY id")]
    reached = _supply(cat, faults)
    edges = {e["id"]: e for e in cat["edges"]}
    for f in faults:
        e = edges[f["edge"]]
        supplied = e["a"] in reached or e["b"] in reached
        loss = Decimal(f["rate"])*24 if f["status"] == "broken" and supplied else Decimal(0)
        db.execute("INSERT INTO water_main_days VALUES(?,?,?,?,?)",
                   (meta["through"], f["id"], f["status"], f"{loss:.4f}", f["cause"]))
    # References are the complete simultaneous isolation context, not a minimal cut.
    causes = sorted(f["id"] for f in faults if f["status"] in ("isolated", "repaired"))
    return {s["asset"]: causes for s in cat["services"] if s["node"] not in reached}


def consumption(db, asset, day, quantity, outages):
    if asset["id"] not in outages:
        return quantity
    db.execute("INSERT INTO water_main_effects VALUES(?,?,?,?,?)",
               (asset["id"], day, f"{quantity:.4f}", f"{quantity:.4f}", canonical(outages[asset["id"]])))
    return 0.0


def inspect(world, edge=None, after="", before=None, service_after="", before_day=None, limit=25):
    if type(limit) is not int or not 1 <= limit <= 50 or (before is not None and (type(before) is not int or before < 1)):
        raise ValueError("Invalid page size or history cursor.")
    if any(not isinstance(v, str) or len(v) > 512 for v in (after, service_after)):
        raise ValueError("Invalid page cursor.")
    if before_day is not None:
        from datetime import date
        if not isinstance(before_day, str) or date.fromisoformat(before_day).isoformat() != before_day:
            raise ValueError("Use a canonical history date.")
    with world.db() as db:
        meta, cat = world.metadata(db), catalog(db)
        present = enabled(db)
        mains = [e for e in cat["edges"] if e["kind"] in ("trunk", "distribution")]
        selected = next((e for e in mains if e["id"] == edge), None)
        if edge is not None and selected is None:
            raise ValueError("Unknown water main.")
        faults = [dict(r) for r in db.execute("SELECT * FROM water_main_faults WHERE status!='restored'")] if present else []
        reached = _supply(cat, faults)
        commissioned = {r[0] for r in db.execute("SELECT id FROM assets WHERE commodity='water' AND installed<=?", (meta["through"],))}
        interrupted = [s for s in cat["services"] if s["node"] not in reached and s["asset"] in commissioned]
        history, losses, affected = [], [], []
        if selected:
            closed = section(cat, edge) if selected["enabled"] else None
            selected = {**selected, **state(db, edge), "isolationEdges": closed}
            if closed:
                preview = _supply(cat, [*faults, {"status": "isolated", "closed_edges": canonical(closed)}])
                affected = [s for s in cat["services"] if s["node"] not in preview and s["asset"] in commissioned]
            if present:
                history = [dict(r) for r in db.execute("SELECT * FROM water_main_faults WHERE edge=? AND sequence<? "
                           "ORDER BY sequence DESC LIMIT ?", (edge, before or 9223372036854775807, limit+1))]
                losses = [dict(r) for r in db.execute("SELECT d.* FROM water_main_days d JOIN water_main_faults f ON f.id=d.fault_id "
                          "WHERE f.edge=? AND d.day<? ORDER BY d.day DESC LIMIT ?", (edge, before_day or "9999-12-31", limit+1))]
        page = [e for e in mains if e["id"] > after][:limit+1]
        service_page = [s for s in affected if s["asset"] > service_after][:limit+1]
        return {"view": "administrator-truth", "modelVersion": VERSION, "enabled": present,
                "environmentId": meta["environment"], "worldFingerprint": meta["fingerprint"], "through": meta["through"],
                "policy": meta.get("waterMainPolicy", DEFAULT_POLICY), "selected": selected,
                "edges": [{**e, **state(db, e["id"])} for e in page[:limit]],
                "nextAfter": page[limit-1]["id"] if len(page) > limit else None,
                "interruptedServices": len(interrupted), "affectedServiceCount": len(affected),
                "affectedSample": service_page[:limit],
                "nextServiceAfter": service_page[limit-1]["asset"] if len(service_page) > limit else None,
                "history": history[:limit], "nextBefore": history[limit-1]["sequence"] if len(history) > limit else None,
                "losses": losses[:limit], "nextDay": losses[limit-1]["day"] if len(losses) > limit else None}


def service_state(db, asset):
    if not enabled(db):
        return None
    row = db.execute("SELECT * FROM water_main_effects WHERE asset=? ORDER BY day DESC LIMIT 1", (asset,)).fetchone()
    return dict(row) if row else None
