"""Read-only saved-road quotes; no reservation, scheduling or physical effects."""
import json
import math

from utilsim.ops.opstown import OpsTown
from utilsim.ops.routing import Router, access_point

from . import field_execution as field

VERSION = "field-travel-quote/1"
WORK_SITE_VERSION = "field-travel-quote/2"
CLASSES = ("arterial", "collector", "local")
PREMISE_OPERATIONS = (field.OPERATION, "clear-sewer-blockage")


def _validate(request):
    keys = {"schemaVersion", "environmentId", "worldFingerprint", "assignmentId", "depotId",
            "mobilisationSeconds", "workSeconds", "speedsKmh"}
    if not isinstance(request, dict):
        raise ValueError("Provide a field travel request with explicit duration and speed assumptions.")
    version = request.get("schemaVersion")
    if version == WORK_SITE_VERSION:
        keys.add("workSite")
    if set(request) != keys or version not in (VERSION, WORK_SITE_VERSION):
        raise ValueError("Provide a field-travel-quote/1 request, or /2 with an explicit workSite.")
    if version == WORK_SITE_VERSION:
        site = request["workSite"]
        if not isinstance(site, dict) or set(site) != {"roadId", "t"}:
            raise ValueError("Work site requires exactly a saved roadId and fractional position t.")
        field._text(site["roadId"])
        if type(site["t"]) not in (int, float) or not math.isfinite(site["t"]) or not 0 <= site["t"] <= 1:
            raise ValueError("Work-site fraction must be finite and between 0 and 1.")
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
        result = {"schemaVersion": request["schemaVersion"], "status": "unavailable", "environmentId": meta["environment"],
                  "worldFingerprint": meta["fingerprint"], "fieldOwnerId": owner.owner_id,
                  "assignmentId": row["id"], "assignmentChecksum": row["checksum"], "crewId": row["crew"],
                  "assetId": row["asset"], "operation": payload["operation"], "scheduledDate": row["scheduled_day"],
                  "assumptions": {k: request[k] for k in ("mobilisationSeconds", "workSeconds", "speedsKmh")}}
        if row["state"] != "accepted":
            return {**result, "reason": "Assignment is no longer pending."}
        if field._physical_result(owner, row) is not None:
            return {**result, "reason": "Physical work already committed; reconcile its existing visit."}
        selected_site = request["schemaVersion"] == WORK_SITE_VERSION
        if selected_site and payload["operation"] in PREMISE_OPERATIONS:
            raise ValueError("Water-service and sewer visits use saved premise access; use field-travel-quote/1.")
        if not selected_site and payload["operation"] not in PREMISE_OPERATIONS:
            return {**result, "reason": "This network-edge visit has no defined saved road-access binding. "
                    "A connected customer's premise is not the assigned work location."}
        with owner.world.db() as physical:
            saved = physical.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()
            snapshot = json.loads(saved[0]) if saved else {}
            try:
                target = field._target(physical, meta, payload["operation"], row["asset"], row["scheduled_day"])
            except ValueError as exc:
                return {**result, "reason": str(exc)}
            water_asset = target.get("waterAssetId", row["asset"])
            asset = None if selected_site else physical.execute(
                "SELECT premise FROM assets WHERE id=? AND commodity='water'", (water_asset,)).fetchone()
        if not selected_site and not asset:
            return {**result, "reason": "Assigned water service is unavailable."}
        premises = [] if selected_site else [p for p in snapshot.get("premises", []) if p.get("id") == asset["premise"]]
        depots = [d for d in snapshot.get("facilities", []) if d.get("id") == request["depotId"] and d.get("kind") == "depot"]
        if (not selected_site and len(premises) != 1) or len(depots) != 1:
            return {**result, "reason": "Saved premise or selected depot is unavailable or ambiguous."}
        try:
            graph = _roads(snapshot.get("roads"))
            origin, start = _access(graph, depots[0])
            destination, stop = _access(graph, request["workSite"] if selected_site else premises[0])
            router = Router(graph, tuple(request["speedsKmh"][k] for k in CLASSES))
            outbound, returning = _leg(router.route(start, stop)), _leg(router.route(stop, start))
        except ValueError as exc:
            return {**result, "reason": str(exc)}
        durations = {"mobilisation": request["mobilisationSeconds"], "outbound": outbound["seconds"],
                     "work": request["workSeconds"], "return": returning["seconds"]}
        ready = {**result, "status": "ready", "depotId": request["depotId"],
                 "roadChecksum": field.checksum(snapshot["roads"]), "origin": origin, "destination": destination,
                 "outbound": outbound, "return": returning, "durationSeconds": durations,
                 "totalSeconds": sum(durations.values())}
        if selected_site:
            ready.update(orderId=row["order_id"], orderRevision=row["order_revision"],
                         accessBinding={"kind": "administrator-selected", "assetId": row["asset"],
                                        "operation": payload["operation"], **destination},
                         locationNotice="Administrator-selected planning assumption; not a verified physical work site or execution authorization.")
        else:
            ready["premiseId"] = asset["premise"]
        if payload["operation"] == "clear-sewer-blockage":
            ready["accessBinding"] = {"kind": "saved-premise", "premiseId": asset["premise"], "waterAssetId": water_asset}
        return {**ready, "quoteId": "field-travel-" + field.checksum(ready)}
