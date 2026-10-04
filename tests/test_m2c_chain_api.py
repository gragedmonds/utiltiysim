"""Chained years over the API: ``year`` and ``previous`` on every run request, earlier years replayed once and their
closes cached, errors naming the year."""

from __future__ import annotations

import orjson
import pytest
from fastapi.testclient import TestClient

from api import _m2c
from api._m2c import RunRequest, _ops_town, load_snapshot, run_for
from api.app import app
from utilsim.m2c import yearclose

TOWN = "village"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_a_later_year_over_the_api(client):
    first = client.post("/api/m2c/summary", json={"town": TOWN}).json()
    assert first["year"] == 2026 and first["opening"] is None
    s = client.post("/api/m2c/summary", json={"town": TOWN, "year": 2027}).json()
    assert s["year"] == 2027 and s["period"] == {"start": "2027-01-01", "end": "2027-12-31"}
    assert s["asOf"].startswith("2027-") and s["simulationId"].startswith(f"m2c-{first['townId']}-2027-")
    assert s["opening"]["unpaidInvoices"] > 0 and s["kpis"]["casesOpen"] >= 0
    # The same chain with its first year given explicitly (no settings, work or outages) is the same run.
    same = client.post("/api/m2c/summary", json={"town": TOWN, "year": 2027, "previous": [{}]}).json()
    assert same == s
    # The first year's own id is unchanged by chains.
    assert first["simulationId"] == run_for(RunRequest(town=TOWN)).simulation_id


def test_the_api_chain_is_the_engines(client):
    run = run_for(RunRequest(town=TOWN, year=2028, previous=[{}, {}]))
    snap = load_snapshot(TOWN)
    direct = yearclose.replay(snap, [{}, {}, {}], ops_factory=lambda: _ops_town(TOWN))
    assert run.simulation_id == direct.simulation_id and run.cal.days == 366
    assert [(i["id"], i["total"]) for i in run.books.invoices] == [(i["id"], i["total"]) for i in direct.books.invoices]


def test_earlier_years_replay_once(client, monkeypatch):
    run_for(RunRequest(town=TOWN, year=2027))
    calls = []
    real = yearclose.close
    monkeypatch.setattr(yearclose, "close", lambda r: calls.append(r.cal.year) or real(r))
    settings = {"vee": {"accept_confidence": 0.8}}
    run_for(RunRequest(town=TOWN, year=2027))  # cached
    run_for(RunRequest(town=TOWN, year=2027, settings=settings, previous=[{}]))  # a new 2027 on the cached 2026
    assert calls == []
    run_for(RunRequest(town=TOWN, year=2028, settings=settings, previous=[{}, {"settings": settings}]))
    assert calls == [2027]


def test_chain_errors_name_the_year(client):
    r = client.post("/api/m2c/summary", json={"town": TOWN, "year": 2028, "previous": [{}]})
    assert r.status_code == 422 and "2026-2027" in r.text
    bad = {"episodes": [{"from": "2027-03-01", "settings": {"vee": {"accept_confidence": 0.9}}}]}
    r = client.post("/api/m2c/summary", json={"town": TOWN, "year": 2027, "previous": [bad]})
    assert r.status_code == 422 and "2026" in r.json()["detail"]
    r = client.post("/api/m2c/summary", json={"town": TOWN, "year": 2027,
                                              "actions": [{"day": "2026-05-01", "type": "accept", "caseId": "X"}]})
    assert r.status_code == 422 and "2027" in r.text
    assert client.post("/api/m2c/summary", json={"town": TOWN, "year": 2031}).status_code == 422
    r = client.post("/api/m2c/summary", json={"town": TOWN, "year": 2027, "asOf": "2026-06-30"})
    assert r.status_code == 422 and "2027" in r.text


def test_close_cache_is_bounded():
    assert len(_m2c._CLOSES) <= _m2c.CLOSE_CACHE


def test_a_later_year_exports_as_a_bundle(tmp_path):
    from utilsim.io import run_bundle as B

    snap = load_snapshot(TOWN)
    directory, manifest, reused = B.export_run(snap, {"year": 2027, "asOf": "2027-03-31"}, tmp_path)
    assert not reused and manifest["inputs"]["year"] == 2027 and len(manifest["inputs"]["previous"]) == 1
    assert manifest["asOf"] == "2027-03-31" and manifest["worklistDates"][0] == "2027-01-31"
    summary = orjson.loads((directory / "summaries" / "2027-03-31.json").read_bytes())
    assert summary["year"] == 2027 and summary["opening"]["year"] == 2026
    assert summary["simulationId"] == run_for(RunRequest(town=TOWN, year=2027, asOf="2027-03-31")).simulation_id
    first = B.export_run(snap, {"asOf": "2026-03-31"}, tmp_path)[1]
    assert "year" not in first["inputs"] and "previous" not in first["inputs"]  # the first year's key as ever
    with pytest.raises(ValueError, match="2027"):
        B.export_run(snap, {"year": 2027, "asOf": "2026-03-31"}, tmp_path)
