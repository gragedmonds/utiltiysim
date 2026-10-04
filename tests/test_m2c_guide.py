"""The engine guide (GET /api/m2c/guide): structured, complete and consistent with the engine's own limits."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.index import app
from utilsim.m2c import guide, scenarios, tables
from utilsim.m2c.run import EPISODE_MAX


def test_guide_sections_are_complete_and_consistent():
    g = guide.guide({"engine": "local", "generatorVersion": "x", "schemaVersion": "y", "towns": ["small_town"],
                     "capabilities": {"generate": True}})
    assert g["schemaVersion"] == guide.GUIDE_VERSION and g["summary"]
    assert len(g["capabilities"]) >= 12 and all(c["title"] and c["text"] and c["where"] for c in g["capabilities"])
    assert len({c["id"] for c in g["capabilities"]}) == len(g["capabilities"])
    assert len(g["impacts"]) >= 8 and all(i["title"] and i["text"] and i["where"] for i in g["impacts"])
    assert len(g["gaps"]) >= 10 and all(x["title"] and x["text"] and x["plan"] for x in g["gaps"])
    assert {m["town"] for m in g["scale"]["measured"]} >= {"Small town", "Large town"} and g["scale"]["measuredOn"]
    assert all(m["accounts"] > 0 and m["replayS"] > 0 for m in g["scale"]["measured"])
    assert any("50,000" in lim["text"] for lim in g["scale"]["limits"])
    lim = g["status"]["limits"]
    assert lim["episodes"] == EPISODE_MAX and lim["pageRows"] == tables.PAGE_MAX and lim["csvRows"] == tables.CSV_MAX
    assert lim["scenarios"] == len(scenarios.SCENARIOS) and lim["tables"] == len(tables.SPECS)
    assert g["status"]["towns"] == ["small_town"] and g["status"]["engine"] == "local"
    # The library and table counts quoted in the text match the engine.
    text = " ".join(c["text"] for c in g["capabilities"])
    assert f"{len(scenarios.SCENARIOS)} situations" in text and f"{len(tables.SPECS)} tables" in text


def test_guide_endpoint_on_the_hosted_app():
    r = TestClient(app).get("/api/m2c/guide")
    assert r.status_code == 200
    body = r.json()
    assert body["schemaVersion"] == guide.GUIDE_VERSION and "small_town" in body["status"]["towns"]
    assert body["status"]["generatorVersion"] and body["status"]["capabilities"]
