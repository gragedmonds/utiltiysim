"""Read-only saved-road quotes; no reservation, scheduling or physical effects."""
import json
import math

from utilsim.ops.opstown import OpsTown
from utilsim.ops.routing import Router, access_point

from . import field_execution as field

VERSION = "field-travel-quote/1"
CLASSES = ("arterial", "collector", "local")


def _validate(request):
    keys = {"schemaVersion", "environmentId", "worldFingerprint", "assignmentId", "depotId",
            "mobilisationSeconds", "workSeconds", "speedsKmh"}
    if not isinstance(request, dict) or set(request) != keys or request["schemaVersion"] != VERSION:
        raise ValueError("Provide a field-travel-quote/1 request with explicit duration and speed assumptions.")
    for key in ("environmentId", "worldFingerprint", "assignmentId", "depotId"):
        field._text(request[key])
    field._integer(request["mobilisationSeconds"], 0, 86400)
    field._integer(request["workSeconds"], 1, 86400)
    speeds = request["speedsKmh"]
    if not isinstance(speeds, dict) or set(speeds) != set(CLASSES):
        raise ValueError("Provide arterial, collector and local speeds in km/h.")
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 1 <= v <= 160 for v in speeds.values()):
        raise ValueError("Each road speed must be finite and between 1 and 160 km/h.")


def _roads(records):
    """Reject ambiguous/broken geometry rather than inventing access or distance."""
    if not isinstance(records, list) or not records:
        raise ValueError("Saved roads are unavailable.")
    identities, junctions = set(), {}
    for road in records:
        if not isinstance(road, dict) or not isinstance(road.get("points"), list) or len(road["points"]) < 2:
            raise ValueError("Saved road geometry is invalid.")
        for key in ("id", "a", "b"):
            field._text(road.get(key))
        if road["id"] in identities:
            raise ValueError("Saved road identity is ambiguous.")
        identities.add(road["id"])
        if road.get("roadClass") not in CLASSES:
            raise ValueError("Saved road class has no explicit speed assumption.")
        points = road["points"]
        for point in points:
            if not isinstance(point, dict) or any(type(point.get(k)) not in (int, float)
                    or not math.isfinite(point[k]) for k in ("x", "z")):
                raise ValueError("Saved road coordinates are invalid.")
        if not any(a["x"] != b["x"] or a["z"] != b["z"] for a, b in zip(points, points[1:])):
            raise ValueError("Saved road has no length.")
        for node, point in ((road["a"], points[0]), (road["b"], points[-1])):
            position = (point["x"], point["z"])
            if node in junctions and math.dist(junctions[node], position) > 0.001:
                raise ValueError("Saved road junctions do not meet.")
            junctions[node] = position
    return OpsTown._roads(records)


def _access(graph, record):
    road_id, fraction = record.get("roadId"), record.get("t")
    if (not isinstance(road_id, str) or road_id not in graph.index
            or type(fraction) not in (int, float) or not math.isfinite(fraction) or not 0 <= fraction <= 1):
        raise ValueError("Saved road access is unavailable or invalid.")
    return {"roadId": road_id, "t": fraction}, access_point(graph, graph.index[road_id], fraction)


def _leg(route):
    return {"seconds": math.ceil(route.seconds), "lengthMeters": route.length_m,
            "points": [{"x": float(p[0]), "z": float(p[1]), "seconds": float(t)}
                       for p, t in zip(route.points, route.times)]}


def quote(owner, request):
    """Administrator adapter API. Quotes never authorize execution or claim a booking.

    The caller must retain the complete quote, and a future runtime adapter must
    revalidate assignment state and its matching active reservation at execution.
    """
    _validate(request)
    with owner.db() as db:
        if not field.enabled(db):
            raise ValueError("No accepted field assignments are available.")
        meta = owner.metadata(db)
        if request["environmentId"] != meta["environment"] or request["worldFingerprint"] != meta["fingerprint"]:
            raise ValueError("Field travel world identity mismatch.")
        row = field._assignment(db, request["assignmentId"])
        payload = json.loads(row["payload"])
        result = {"schemaVersion": VERSION, "status": "unavailable", "environmentId": meta["environment"],
                  "worldFingerprint": meta["fingerprint"], "fieldOwnerId": owner.owner_id,
                  "assignmentId": row["id"], "assignmentChecksum": row["checksum"], "crewId": row["crew"],
                  "assetId": row["asset"], "operation": payload["operation"], "scheduledDate": row["scheduled_day"],
                  "assumptions": {k: request[k] for k in ("mobilisationSeconds", "workSeconds", "speedsKmh")}}
        if row["state"] != "accepted":
            return {**result, "reason": "Assignment is no longer pending."}
        if payload["operation"] != field.OPERATION:
            return {**result, "reason": "This travel quote supports downstream-water visits only."}
        if field._physical_result(owner, row) is not None:
            return {**result, "reason": "Physical work already committed; reconcile its existing visit."}
        with owner.world.db() as physical:
            saved = physical.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()
            asset = physical.execute("SELECT premise FROM assets WHERE id=? AND commodity='water'", (row["asset"],)).fetchone()
            snapshot = json.loads(saved[0]) if saved else {}
        if not asset:
            return {**result, "reason": "Assigned water service is unavailable."}
        premises = [p for p in snapshot.get("premises", []) if p.get("id") == asset["premise"]]
        depots = [d for d in snapshot.get("facilities", []) if d.get("id") == request["depotId"] and d.get("kind") == "depot"]
        if len(premises) != 1 or len(depots) != 1:
            return {**result, "reason": "Saved premise or selected depot is unavailable or ambiguous."}
        try:
            graph = _roads(snapshot.get("roads"))
            origin, start = _access(graph, depots[0])
            destination, stop = _access(graph, premises[0])
            router = Router(graph, tuple(request["speedsKmh"][k] for k in CLASSES))
            outbound, returning = _leg(router.route(start, stop)), _leg(router.route(stop, start))
        except ValueError as exc:
            return {**result, "reason": str(exc)}
        durations = {"mobilisation": request["mobilisationSeconds"], "outbound": outbound["seconds"],
                     "work": request["workSeconds"], "return": returning["seconds"]}
        ready = {**result, "status": "ready", "premiseId": asset["premise"], "depotId": request["depotId"],
                 "roadChecksum": field.checksum(snapshot["roads"]), "origin": origin, "destination": destination,
                 "outbound": outbound, "return": returning, "durationSeconds": durations,
                 "totalSeconds": sum(durations.values())}
        return {**ready, "quoteId": "field-travel-" + field.checksum(ready)}
