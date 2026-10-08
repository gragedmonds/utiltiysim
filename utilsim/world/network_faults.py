"""Opt-in physical supply interruptions on the saved electricity and gas graphs.

Connectivity is an illustrative supply model, not a power-flow or gas-pressure solver.
Only administrator views expose fault truth. Meter exports remain observations.
"""
import json
import math
from collections import defaultdict

from . import hazards
from .migrations import rollback_backup
from .store import canonical, draw, stable

VERSION = "world-network-faults/1"
DEFAULT_POLICY = {"annualProbability": 0.0, "revision": 0, "cause": None}
UTILITIES = ("electric", "gas")


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='networkFaultModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported network-fault model version.")
    return row is not None


def _reachable(edges, sources, removed=()):
    graph = defaultdict(set)
    for e in edges:
        if e["enabled"] and e["id"] not in removed:
            graph[e["a"]].add(e["b"])
            graph[e["b"]].add(e["a"])
    seen, stack = set(sources), list(sources)
    while stack:
        for node in graph[stack.pop()] - seen:
            seen.add(node)
            stack.append(node)
    return seen, graph


def _catalog(db):
    if enabled(db):
        return ([dict(r) for r in db.execute("SELECT * FROM network_edges ORDER BY commodity,id")],
                [dict(r) for r in db.execute("SELECT * FROM network_services ORDER BY asset")],
                [dict(r) for r in db.execute("SELECT * FROM network_sources ORDER BY commodity,node")])
    row = db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()
    if not row:
        raise ValueError("Initialize a world first.")
    snapshot = json.loads(row[0])
    edges, services, sources = [], [], []
    for commodity in UTILITIES:
        expected = {r[0] for r in db.execute("SELECT id FROM assets WHERE commodity=?", (commodity,))}
        if not expected:
            continue
        network = snapshot.get("networks", {}).get(commodity, {})
        nodes = {n["id"] for n in network.get("nodes", [])}
        roots = network.get("sourceIds") or [network.get("sourceId")]
        if not nodes or not roots or any(r not in nodes for r in roots):
            raise ValueError(f"Saved {commodity} topology needs valid supply sources.")
        sources.extend({"commodity": commodity, "node": n} for n in sorted(set(roots)))
        ids = set()
        for e in network.get("edges", []):
            if (not isinstance(e.get("id"), str) or not e["id"] or e["id"] in ids
                    or e.get("from") not in nodes or e.get("to") not in nodes
                    or type(e.get("enabled", True)) is not bool):
                raise ValueError(f"Invalid saved {commodity} network edge.")
            ids.add(e["id"])
            edges.append({"commodity": commodity, "id": e["id"], "a": e["from"], "b": e["to"],
                          "kind": e.get("kind", "network"), "enabled": int(e.get("enabled", True))})
        found = set()
        reachable, _ = _reachable([e for e in edges if e["commodity"] == commodity], roots)
        for sp in snapshot["servicePoints"]:
            if sp["commodity"] != commodity:
                continue
            meter, node = sp["meterId"], sp.get("networkNodeId")
            if meter not in expected or meter in found or node not in reachable:
                raise ValueError(f"Saved {commodity} service must have one connected network node.")
            found.add(meter)
            services.append({"asset": meter, "commodity": commodity, "node": node, "premise": sp["premiseId"]})
        if found != expected:
            raise ValueError(f"Incomplete saved {commodity} service mapping.")
    return edges, services, sources


def _enable(world, db, catalog):
    if enabled(db):
        return
    backup = rollback_backup(world, "network-faults")
    statements = [
        "CREATE TABLE network_edges(commodity TEXT,id TEXT,a TEXT,b TEXT,kind TEXT,enabled INTEGER,PRIMARY KEY(commodity,id))",
        "CREATE TABLE network_services(asset TEXT PRIMARY KEY,commodity TEXT,node TEXT,premise TEXT)",
        "CREATE TABLE network_sources(commodity TEXT,node TEXT,PRIMARY KEY(commodity,node))",
        "CREATE TABLE network_fault_slots(commodity TEXT,edge TEXT,revision INTEGER NOT NULL,PRIMARY KEY(commodity,edge))",
        "CREATE TABLE network_faults(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,"
        "commodity TEXT NOT NULL,edge TEXT NOT NULL,opened_date TEXT NOT NULL,restored_date TEXT,"
        "source TEXT NOT NULL,cause TEXT NOT NULL,open_event TEXT NOT NULL,restore_event TEXT,work_order TEXT)",
        "CREATE UNIQUE INDEX network_fault_active ON network_faults(commodity,edge) WHERE restored_date IS NULL",
        "CREATE INDEX network_fault_history ON network_faults(commodity,edge,sequence)",
        "CREATE TABLE network_fault_effects(asset TEXT,day TEXT,demand_quantity TEXT NOT NULL,"
        "unserved_quantity TEXT NOT NULL,fault_ids TEXT NOT NULL,PRIMARY KEY(asset,day))",
    ]
    for sql in statements:
        db.execute(sql)
    edges, services, sources = catalog
    db.executemany("INSERT INTO network_edges VALUES(:commodity,:id,:a,:b,:kind,:enabled)", edges)
    db.executemany("INSERT INTO network_services VALUES(:asset,:commodity,:node,:premise)", services)
    db.executemany("INSERT INTO network_sources VALUES(:commodity,:node)", sources)
    world.put(db, "networkFaultModelVersion", VERSION)
    world.put(db, "networkFaultRollbackBackup", backup)
    world.put(db, "networkFaultPolicy", DEFAULT_POLICY)


def state(db, commodity, edge):
    if not enabled(db):
        return {"revision": 0, "active": None}
    slot = db.execute("SELECT revision FROM network_fault_slots WHERE commodity=? AND edge=?", (commodity, edge)).fetchone()
    active = db.execute("SELECT * FROM network_faults WHERE commodity=? AND edge=? AND restored_date IS NULL",
                        (commodity, edge)).fetchone()
    return {"revision": slot[0] if slot else 0, "active": dict(active) if active else None}


def _revision(db, commodity, edge):
    db.execute("INSERT INTO network_fault_slots VALUES(?,?,1) ON CONFLICT(commodity,edge) "
               "DO UPDATE SET revision=revision+1", (commodity, edge))
    return state(db, commodity, edge)["revision"]


def _start(world, db, meta, commodity, edge, source, cause, actor, reason):
    if state(db, commodity, edge)["active"]:
        raise ValueError("This network edge already has an active fault.")
    identity = "NET-" + stable(meta["environment"], meta["through"], commodity, edge, cause)
    revision = _revision(db, commodity, edge)
    event = world.event(db, meta["environment"], meta["through"], "PhysicalNetworkFaultStarted", edge,
                        {"faultId": identity, "commodity": commodity, "source": source, "actorId": actor,
                         "reason": reason, "revision": revision, "modelVersion": VERSION}, cause)
    db.execute("INSERT INTO network_faults(id,commodity,edge,opened_date,source,cause,open_event) VALUES(?,?,?,?,?,?,?)",
               (identity, commodity, edge, meta["through"], source, cause, event))
    return {"faultId": identity, "eventId": event, "revision": revision}


def _restore(world, db, meta, payload):
    """Physical transition; callers own authorization, identity and transaction."""
    commodity, edge = payload["commodity"], payload["edgeId"]
    current = state(db, commodity, edge)
    if (not current["active"] or current["active"]["id"] != payload["faultId"]
            or current["revision"] != payload["expectedRevision"]):
        raise ValueError("Restoration must reference this edge's current active fault and revision.")
    revision = _revision(db, commodity, edge)
    event = world.event(db, meta["environment"], meta["through"], "PhysicalNetworkRestored", edge,
                        {**payload, "revision": revision}, payload["commandId"])
    db.execute("UPDATE network_faults SET restored_date=?,restore_event=?,work_order=? WHERE id=?",
               (meta["through"], event, payload["workOrderId"], payload["faultId"]))
    return {"eventId": event, "revision": revision, "faultId": payload["faultId"]}


def command(world, payload):
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "expectedRevision",
              "effectiveDate", "action", "reason", "causalReference"}
    if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
        raise ValueError("Network-fault command must identify an action.")
    action = payload["action"]
    extra = {"configure": {"annualProbability"}, "start": {"commodity", "edgeId"},
             "restore": {"commodity", "edgeId", "faultId", "workOrderId"}}.get(action)
    if extra is None or set(payload) != common | extra or payload.get("schemaVersion") != VERSION:
        raise ValueError("Invalid network-fault command contract.")
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
        catalog = _catalog(db)
        policy = meta.get("networkFaultPolicy", DEFAULT_POLICY)
        if action == "configure":
            expected = policy["revision"]
        else:
            commodity, edge = payload["commodity"], payload["edgeId"]
            selected = next((e for e in catalog[0] if e["commodity"] == commodity and e["id"] == edge), None)
            if not selected or not selected["enabled"]:
                raise ValueError("Choose a normally enabled electricity or gas edge.")
            current = state(db, commodity, edge)
            expected = current["revision"]
            if action == "start" and current["active"]:
                raise ValueError("This network edge already has an active fault.")
            if action == "restore" and (not current["active"] or current["active"]["id"] != payload["faultId"]):
                raise ValueError("Restoration must reference this edge's active fault.")
        if payload["expectedRevision"] != expected:
            raise ValueError("Network-fault revision changed. Reload before making changes.")
        _enable(world, db, catalog)
        if action == "configure":
            event = world.event(db, meta["environment"], meta["through"], "NetworkFaultPolicyChanged", meta["town"],
                                {**payload, "revision": expected+1}, payload["commandId"])
            world.put(db, "networkFaultPolicy", {"annualProbability": probability, "revision": expected+1, "cause": event})
            result = {"eventId": event, "revision": expected+1}
        elif action == "start":
            result = _start(world, db, meta, commodity, edge, "manual", payload["commandId"],
                            payload["actorId"], payload["reason"])
        else:
            result = _restore(world, db, meta, payload)
        result.update(commandId=payload["commandId"], status="completed", effectiveDate=meta["through"], modelVersion=VERSION)
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def _outages(catalog, faults):
    """Connected components respect loops and normally open ties. Boundary faults
    explain each isolated component; they are not asserted to be a minimal cut set.
    """
    edges, services, sources = catalog
    result = {}
    for commodity in UTILITIES:
        selected = [e for e in edges if e["commodity"] == commodity]
        active = {f["edge"]: f["id"] for f in faults if f["commodity"] == commodity}
        if not active:
            continue
        reached, graph = _reachable(selected, [s["node"] for s in sources if s["commodity"] == commodity], active)
        components, boundaries = {}, defaultdict(set)
        isolated = [s for s in services if s["commodity"] == commodity and s["node"] not in reached]
        for service in isolated:
            node = service["node"]
            if node not in components:
                component, stack = {node}, [node]
                while stack:
                    for neighbor in graph[stack.pop()] - component:
                        component.add(neighbor)
                        stack.append(neighbor)
                for member in component:
                    components[member] = node
        for e in selected:
            if e["id"] in active:
                a, b = components.get(e["a"]), components.get(e["b"])
                if a != b:
                    if a is not None:
                        boundaries[a].add(active[e["id"]])
                    if b is not None:
                        boundaries[b].add(active[e["id"]])
        for service in isolated:
            result[service["asset"]] = sorted(boundaries[components[service["node"]]])
    return result


def _active(db):
    return [dict(r) for r in db.execute("SELECT * FROM network_faults WHERE restored_date IS NULL ORDER BY commodity,edge")]


def daily(world, db, meta):
    if not enabled(db):
        return {}
    catalog = _catalog(db)
    policy = meta["networkFaultPolicy"]
    if policy["annualProbability"] > 0:
        active = {(f["commodity"], f["edge"]) for f in _active(db)}
        restored = {(r[0], r[1]) for r in db.execute("SELECT commodity,edge FROM network_faults WHERE restored_date=?",
                                                    (meta["through"],))}
        for e in catalog[0]:
            hazard, cause = hazards.risk(meta, e["commodity"], policy["annualProbability"], policy["cause"])
            key = (e["commodity"], e["id"])
            if (e["enabled"] and key not in active | restored
                    and draw(meta["seed"], meta["through"], *key, VERSION, "start") < hazard):
                _start(world, db, meta, *key, "seeded", cause, "world-system", "Seeded daily network hazard")
    return _outages(catalog, _active(db))


def consumption(db, asset, day, quantity, outages):
    if asset["id"] not in outages:
        return quantity
    demand = f"{quantity:.4f}"
    db.execute("INSERT INTO network_fault_effects VALUES(?,?,?,?,?)",
               (asset["id"], day, demand, demand, canonical(outages[asset["id"]])))
    return 0.0


def service_state(db, identity):
    if not enabled(db):
        return None
    # Last completed physical day; do not mix it with a newly submitted restoration.
    row = db.execute("SELECT * FROM network_fault_effects WHERE asset=? ORDER BY day DESC LIMIT 1", (identity,)).fetchone()
    return {**dict(row), "fault_ids": json.loads(row["fault_ids"])} if row else None


def inspect(world, commodity="electric", edge=None, after="", before=None, limit=25, service_after=""):
    if (commodity not in UTILITIES or not isinstance(after, str) or len(after) > 512
            or (edge is not None and (not isinstance(edge, str) or not edge or len(edge) > 512))
            or not isinstance(service_after, str) or len(service_after) > 512
            or type(limit) is not int or not 1 <= limit <= 50
            or (before is not None and (type(before) is not int or not 1 <= before <= 9223372036854775807))):
        raise ValueError("Invalid network catalog or history page.")
    with world.db() as db:
        meta = world.metadata(db)
        catalog = _catalog(db)
        commissioned = {r[0] for r in db.execute("SELECT id FROM assets WHERE installed<=?", (meta["through"],))}
        catalog = (catalog[0], [s for s in catalog[1] if s["asset"] in commissioned], catalog[2])
        faults = _active(db) if enabled(db) else []
        rows = sorted((e for e in catalog[0] if e["commodity"] == commodity and e["id"] > after), key=lambda e: e["id"])
        outages = _outages(catalog, faults)
        result = {"view": "administrator-truth", "modelVersion": VERSION, "environmentId": meta["environment"],
                  "worldFingerprint": meta["fingerprint"], "through": meta["through"],
                  "policy": meta.get("networkFaultPolicy", DEFAULT_POLICY),
                  "edges": [{**e, **state(db, commodity, e["id"])} for e in rows[:limit]],
                  "nextAfter": rows[limit-1]["id"] if len(rows) > limit else None,
                  "interruptedServices": len(outages)}
        if edge is not None:
            selected = next((e for e in catalog[0] if e["commodity"] == commodity and e["id"] == edge), None)
            if selected is None:
                raise ValueError("Unknown network edge.")
            history = []
            if enabled(db):
                history = [dict(r) for r in db.execute("SELECT * FROM network_faults WHERE commodity=? AND edge=? "
                           "AND sequence<? ORDER BY sequence DESC LIMIT ?", (commodity, edge, before or 9223372036854775807, limit+1))]
            preview = faults if state(db, commodity, edge)["active"] else [*faults, {"commodity": commodity, "edge": edge, "id": "preview"}]
            impact = _outages(catalog, preview)
            affected = sorted((s for s in catalog[1] if s["commodity"] == commodity and s["asset"] in impact),
                              key=lambda s: s["asset"])
            page = [s for s in affected if s["asset"] > service_after]
            result.update(selected={**selected, **state(db, commodity, edge)}, history=history[:limit],
                          nextBefore=history[limit-1]["sequence"] if len(history) > limit else None,
                          additionalInterruptedServices=len(set(impact) - set(outages)),
                          affectedServiceCount=len(affected), affectedSample=page[:limit],
                          nextServiceAfter=page[limit-1]["asset"] if len(page) > limit else None)
        return result
