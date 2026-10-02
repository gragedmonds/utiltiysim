from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def _town():
    r = client.post("/api/towns", json={"preset": "whitby_small", "seed": "API", "houses": 120})
    assert r.status_code in (200, 201), r.text
    return r.json()["townId"]


def test_health_schema_presets():
    assert client.get("/api/health").json()["status"] == "ok"
    s = client.get("/api/config/schema").json()
    assert "TownConfig" in s["$defs"]
    p = client.get("/api/config/presets").json()
    assert "whitby_small" in {x["name"] for x in p["towns"]} and "leak" in p["scenarios"]


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
    assert 43.8 < lat < 43.95 and -79.0 < lon < -78.85
    net = client.get(f"/api/towns/{tid}/network/electric").json()
    assert len(net["nodes"]["id"]) == len(net["edges"]["id"]) + 1
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
