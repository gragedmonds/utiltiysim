from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def _town():
    r = client.post("/api/towns", json={"preset": "village", "seed": "API", "houses": 120})
    assert r.status_code in (200, 201), r.text
    return r.json()["townId"]


def test_health_schema_presets():
    assert client.get("/api/health").json()["status"] == "ok"
    s = client.get("/api/config/schema").json()
    assert "TownConfig" in s["$defs"]
    p = client.get("/api/config/presets").json()
    assert "village" in {x["name"] for x in p["towns"]} and "leak" in p["scenarios"]


def test_town_lifecycle_and_endpoints():
    tid = _town()
    info = client.get(f"/api/towns/{tid}").json()
    assert info["status"] == "ready" and info["houses"] == 120
    snap = client.get(f"/api/towns/{tid}/snapshot.json")
    body = snap.json()  # the client transparently decodes Content-Encoding: gzip
    assert body["schemaVersion"] == "utility-town/2.0" and body["validation"]["valid"]
    gj = client.get(f"/api/towns/{tid}/layers/buildings.geojson").json()
    assert gj["type"] == "FeatureCollection" and len(gj["features"]) >= 120
    lon, lat = gj["features"][0]["geometry"]["coordinates"][0][0]
    assert abs(lat - 43.30) < 0.05 and abs(lon + 80.60) < 0.05  # around the town's configured anchor
    net = client.get(f"/api/towns/{tid}/network/electric").json()
    # One source: a construction forest of nodes - 1 parent edges; every other edge is a normally-open feeder tie.
    parents = [p for p in net["nodes"]["parentEdge"] if p >= 0]
    assert len(set(parents)) == len(parents) == len(net["nodes"]["id"]) - 1
    assert len(net["edges"]["id"]) - len(parents) == net["meta"]["ties"]
    pid = body["premises"][0]["id"]
    tr = client.get(f"/api/towns/{tid}/network/electric/trace/electric-N-{pid}").json()
    assert tr["upstreamEdgeIds"][0] == "electric-E0"
    stack = client.get(f"/api/towns/{tid}/premises/{pid}").json()
    assert stack["premise"]["id"] == pid and stack["meters"] and stack["contracts"] and stack["reads"]
    fl = client.get(f"/api/towns/{tid}/flows", params={"hour": 8, "scenario": "leak", "target": pid}).json()
    assert len(fl["edgeFlows"]["water"]) == len(fl["edgeIds"]["water"])
    tab = client.get(f"/api/towns/{tid}/tables/meters.csv")
    assert tab.status_code == 200 and tab.text.startswith("id,")
    pq = client.get(f"/api/towns/{tid}/tables/sampleReads.parquet")
    assert pq.status_code == 200 and pq.content[:4] == b"PAR1"
    fx = client.get(f"/api/towns/{tid}/fixtures/vee/{pid}/electric.json", params={"variant": "missing"}).json()
    assert fx["schemaVersion"] == "vee-input-fixture/1.1" and fx["truthIncluded"] is False
    assert fx["reads"][0]["registerValue"] is None and "truth" not in fx["reads"][0]
    assert client.get(f"/api/towns/{tid}/render.png").content[:4] == b"\x89PNG"


def test_a_generated_town_runs_operations_and_meter_to_cash():
    """The Studio's Configuration flow: send a full edited config (the small town with another seed and an override), then use
    the new town id everywhere a pack preset works."""
    import time

    import orjson

    from utilsim.config import load_preset

    cfg = load_preset("small_town").model_dump(mode="json")
    cfg["seeds"]["master"] = "SMALL-STUDIO-7"
    cfg["operations"]["electric_crews"] = 5
    t0 = time.perf_counter()
    r = client.post("/api/towns", json={"config": cfg})
    built = time.perf_counter() - t0
    assert r.status_code == 201, r.text
    tid = r.json()["townId"]
    again = client.post("/api/towns", json={"config": cfg}).json()
    assert again == {"townId": tid, "ref": r.json()["ref"], "status": "ready"}  # same id and the same name
    assert again["ref"].startswith("small_town~")
    health = client.get("/api/health").json()
    assert health["capabilities"]["generate"] is True and tid in health["towns"] and "small_town" in health["towns"]
    assert next(t for t in health["generated"] if t["townId"] == tid)["seed"] == "SMALL-STUDIO-7"
    view = client.get(f"/api/towns/{tid}/snapshot.json", params={"detail": "viewer"}).json()
    assert view["id"] == tid and view["detail"] == "viewer" and view["sampleReads"] == []
    assert view["config"]["seeds"]["master"] == "SMALL-STUDIO-7"
    settings = client.get("/api/sim/settings", params={"town": tid}).json()
    assert settings["electricCrews"] == 5  # the town's config is the run's default
    tl = client.post("/api/sim/timeline", json={"town": tid, "m2c": {}})
    assert tl.status_code == 200, tl.text
    tl = tl.json()
    assert tl["townId"] == tid and tl["topologyRevision"] == view["topologyRevision"] and "meterToCash" in tl
    pole = next(q for q in view["networks"]["electric"]["equipment"] if q["kind"] == "pole")
    body = {"town": tid, "commands": [{"id": "C", "at": 8 * 3600, "type": "break_asset",
                                       "payload": {"id": pole["id"], "kind": "pole", "utility": "electric",
                                                   "edgeId": pole["edgeId"]}}], "settings": {"randomIncidents": False}}
    frame = client.post("/api/sim/frame", json={**body, "at": 8 * 3600 + 120}).json()
    assert frame["townId"] == tid and frame["premises"]["unsupplied"]["electric"]
    summary = client.post("/api/m2c/summary", json={"town": tid, "asOf": "2026-06-30"})
    assert summary.status_code == 200 and summary.json()["townId"] == tid and summary.json()["kpis"]["reads"] > 0
    print(f"generated {tid} in {built:.1f} s; snapshot {len(orjson.dumps(view)) / 1e6:.1f} MB")


def test_errors():
    assert client.get("/api/towns/town-nope").status_code == 404
    assert client.post("/api/towns", json={"preset": "nope"}).status_code == 422
    assert client.post("/api/towns", json={"houses": 5}).status_code == 422


def test_state_and_replay_endpoints():
    tid = _town()
    snap = client.get(f"/api/towns/{tid}/snapshot.json").json()
    f = client.get(f"/api/towns/{tid}/state", params={"hour": 12, "scenario": "solar_noon"}).json()
    assert f["schemaVersion"] == "utility-state/1.0" and f["topologyRevision"] == snap["topologyRevision"]
    assert f["clock"]["simTime"] == f["simTime"]
    rp = client.get(f"/api/towns/{tid}/replay", params={"stepMinutes": 30, "hours": 6, "startHour": 6}).json()
    assert rp["schemaVersion"] == "utility-replay/1.0" and len(rp["frames"]) == 12
    assert [x["sequence"] for x in rp["frames"]] == [360 + 30 * k for k in range(12)]  # minutes since midnight
    assert f["sequence"] == 720
    assert client.get(f"/api/towns/{tid}/replay", params={"stepMinutes": 1, "hours": 168}).status_code == 422
