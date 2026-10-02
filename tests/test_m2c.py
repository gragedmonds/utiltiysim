"""Meter-to-cash: periodic reads, VEE, work queues and analyst actions, built from snapshots (hosted runtime)."""

from __future__ import annotations

import gzip
from collections import Counter
from pathlib import Path

import numpy as np
import orjson
import pytest

from utilsim.io import schemas
from utilsim.io.snapshot import build_snapshot
from utilsim.m2c import catalog as cat
from utilsim.m2c import views
from utilsim.m2c.base import M2CTown, date_of
from utilsim.m2c.run import FAULTS, M2CRun, add_bdays, resolve_settings
from utilsim.sim.demand import monthly_energy as town_energy
from utilsim.sim.usage import UsageInputs, monthly_energy

ROOT = Path(__file__).resolve().parents[1]
QUIET = {"anomalies": {"enabled": False},
         "reading": {"ami_missed_read": 0, "amr_missed_read": 0, "manual_no_access": 0}}


@pytest.fixture(scope="module")
def ayr_town() -> M2CTown:
    index = orjson.loads((ROOT / "packs" / "index.json").read_bytes())
    entry = next(t for t in index["towns"] if t["preset"] == "ayr")
    snap = orjson.loads(gzip.decompress((ROOT / "packs" / entry["files"]["snapshot"]["path"]).read_bytes()))
    return M2CTown.from_snapshot(snap)


@pytest.fixture(scope="module")
def ayr(ayr_town) -> M2CRun:
    return M2CRun(ayr_town)


def test_snapshot_usage_and_june_reads_match_the_generator(town120):
    snap = orjson.loads(orjson.dumps(build_snapshot(town120), option=orjson.OPT_SERIALIZE_NUMPY))
    a, b = monthly_energy(UsageInputs.from_snapshot(snap), town120.cfg), town_energy(town120.prem, town120.cfg)
    assert all(np.array_equal(a[k], b[k]) for k in a)
    run = M2CRun(M2CTown.from_snapshot(snap), QUIET)
    tw = run.town
    assert {"AMI", "AMR", "MANUAL"} <= set(tw.tech.tolist())  # per-route technology (MANUAL meters exist)
    for r in snap["sampleReads"]:
        k = tw.reg_index[r["registerId"]]
        assert (run.obs[k, 5], run.obs[k, 6]) == (r["previousRegisterValue"], r["registerValue"]), r["id"]
        assert run.read_id(k, 6) == r["id"]


def test_reads_misses_and_estimates(ayr):
    tw, c = ayr.town, ayr.cfg
    got = ~np.isnan(ayr.obs[:, 1:])
    assert got.all(axis=1).sum() > 0.6 * tw.n_registers and got.mean() > 0.95
    ami = np.flatnonzero(tw.tech == "AMI")
    n = len(ami) * 12
    miss = int((~got[ami]).sum())
    p = c.reading.ami_missed_read
    # AMI misses: comm fails plus episodes and missing documents (anomaly rates are small).
    assert p * n - 4 * np.sqrt(n * p) < miss < p * n + 4 * np.sqrt(n * p) + 0.004 * n
    released = ayr.status[:, 1:]
    assert ((released >= 1) & (released <= 3)).mean() > 0.995  # nearly everything reaches billing in the year
    est = ayr.status[:, 1:] == 2
    assert np.all(np.isnan(ayr.obs[:, 1:]) | ~est | (ayr.truth_cls[:, 1:] == 2) | (ayr.disp[:, 1:] > 0))


def test_vee_catches_injected_faults(ayr):
    tw = ayr.town
    hits: Counter = Counter()
    seen: Counter = Counter()
    for r in range(tw.n_registers):
        if tw.direction[r] != "import":
            continue
        meter = tw.meter_of[r]
        for m in range(1, 13):
            if np.isnan(ayr.obs[r, m]) or ayr.truth_cls[r, m] == 0:
                continue
            kind = cat.TRUTH[ayr.truth_cls[r, m]]
            if kind == "meter_fault":
                kind = FAULTS[ayr.fault_type[meter]]
                if kind == "stuck_meter" and not (ayr.cons[r, m] == 0 and tw.occupied[tw.prem[r]]
                                                  and ayr.expected[r, m] >= {"kWh": 30, "m3": 1}[tw.unit[r]]):
                    continue  # only full-period zero reads at occupied premises are detectable by tolerance
            seen[kind] += 1
            hits[kind] += int(ayr.disp[r, m] > 0)
    assert seen["exchange_registration_failure"] and hits["exchange_registration_failure"] == \
        seen["exchange_registration_failure"]
    assert hits["read_error"] >= 0.8 * seen["read_error"] > 0
    assert hits["stuck_meter"] >= 0.9 * seen["stuck_meter"] > 0
    clean = ~np.isnan(ayr.obs[:, 1:]) & (ayr.truth_cls[:, 1:] == 0)
    assert (ayr.disp[:, 1:][clean] == 0).mean() > 0.99


def test_queues_follow_the_workforce(ayr_town):
    none = M2CRun(ayr_town, {"process": {"analysts": 0, "rpa_coverage": 0}})
    backlog = none.series["ESTIMATION"][:, 2] + none.series["VEE_REVIEW"][:, 2]
    assert backlog[-1] > 500 and np.all(np.diff(backlog) >= 0)
    auto = M2CRun(ayr_town, {"process": {"rpa_coverage": 1}})
    missing = [c for c in auto.cases if c.type in ("COMM_FAIL", "NO_ACCESS", "NO_READ") and c.created < 360]
    assert missing and all(any(e[1] == "AUTO_RESOLVED" for e in c.events) for c in missing)
    s = views.summary(none, "2026-12-31")
    assert s["kpis"]["carry"] > views.summary(auto, "2026-12-31")["kpis"]["carry"]


def test_actions_are_append_only_and_take_effect(ayr_town):
    base = M2CRun(ayr_town, {"process": {"analysts": 0, "rpa_coverage": 0}})
    case = next(c for c in base.cases if c.type not in cat.MISSING_TYPES and c.created < 150)
    day = add_bdays(int(case.created), 3)
    when = date_of(day).isoformat()
    act = [{"id": "A1", "day": when, "type": "override", "caseId": case.id, "value": 1234.5}]
    run = M2CRun(ayr_town, {"process": {"analysts": 0, "rpa_coverage": 0}}, act)
    mine = run.case_index[case.id]
    assert mine.outcome == "override" and int(mine.resolved) == day
    assert run.released[case.r, case.month] == 1234.5 and run.status[case.r, case.month] == 3
    before = [(c.id, [e for e in c.events if e[0] < day]) for c in base.cases if c.created < day]
    assert before == [(c.id, [e for e in c.events if e[0] < day]) for c in run.cases if c.created < day]
    with pytest.raises(ValueError, match="append-only"):
        M2CRun(ayr_town, None, [act[0], {**act[0], "id": "A0", "day": "2026-01-05"}])
    with pytest.raises(ValueError):
        resolve_settings(ayr_town.cfg, {"vee": {"high_ratio": 0.5}})
    stale = M2CRun(ayr_town, None, [{**act[0], "caseId": "CASE-nope"}])
    assert stale.warnings


def test_views_are_valid_bounded_and_deterministic(ayr, ayr_town):
    s = views.summary(ayr, "2026-12-31")
    assert s == views.summary(M2CRun(ayr_town), "2026-12-31")
    assert len(s["premises"]["status"]) == len(ayr_town.premise_ids)
    assert sum(q["open"] for q in s["queues"]) == s["kpis"]["casesOpen"]
    for q in s["queues"]:
        assert len(q["series"]["backlog"]) == 365 and q["series"]["backlog"][-1] == q["open"]
    w = views.worklist(ayr, None, as_of="2026-12-31", status="all", sort="impact", page_size=500)
    assert w["total"] == s["kpis"]["casesOpened"] and len(w["rows"]) == 200
    c = views.case_view(ayr, w["rows"][0]["caseId"], as_of="2026-12-31", truth=True)
    assert c["events"][0]["eventType"] == c["type"] and len(c["decision"]["tests"]) == 5
    assert {e["type"] for e in c["edges"]} <= set(cat.EDGE_TYPES)
    p = views.premise(ayr, c["premiseId"], as_of="2026-12-31")
    for rd in p["reads"]:
        assert not schemas.errors("meter-read-1.1", rd), rd["id"]
    fx = views.vee_export(ayr, 6, 3)
    assert fx["reads"] and not schemas.errors("vee-input-fixture-1.1", fx)
    for doc in (s, w, c, p, fx, views.graph(ayr, 6), views.costs(ayr)):
        assert len(orjson.dumps(doc)) < 4_500_000
    assert views.summary(ayr, "2026-03-31")["kpis"]["reads"] < s["kpis"]["reads"]


def test_hosted_m2c_api():
    from fastapi.testclient import TestClient

    from api.index import app

    client = TestClient(app)
    st = client.get("/api/m2c/settings").json()
    assert set(st["schema"]["properties"]) == {"process", "anomalies", "reading", "vee"}
    assert st["defaults"]["vee"]["accept_confidence"] == 0.75
    body = {"town": "ayr", "asOf": "2026-08-31", "settings": {"process": {"analysts": 1}}}
    s = client.post("/api/m2c/summary", json=body)
    assert s.status_code == 200 and s.json()["schemaVersion"] == "m2c-summary/1.0"
    q = client.post("/api/process/queue", json={**body, "status": "all", "pageSize": 5}).json()
    assert q["total"] > 0 and len(q["rows"]) == 5
    row = q["rows"][0]
    case = client.post("/api/m2c/case", json={**body, "caseId": row["caseId"]}).json()
    assert case["caseId"] == row["caseId"] and case["decision"]["readId"] == row["readId"]
    assert client.post("/api/m2c/premise", json={**body, "premiseId": row["premiseId"]}).json()["reads"]
    dec = client.post("/api/vee/decision", json={**body, "readId": row["readId"]}).json()
    assert dec["readId"] == row["readId"] and len(dec["tests"]) == 5
    assert client.post("/api/vee/export", json={**body, "month": 3, "portion": 2}).status_code == 200
    assert client.post("/api/process/graph", json={**body, "month": 3}).json()["nodes"]
    assert client.post("/api/process/costs", json=body).json()["types"]
    assert client.post("/api/m2c/case", json={**body, "caseId": "CASE-nope"}).status_code == 404
    assert client.post("/api/m2c/summary", json={**body, "settings": {"vee": {"high_ratio": 0.1}}}).status_code == 422
    assert client.post("/api/m2c/summary", json={**body, "settings": {"billing": {}}}).status_code == 422
    late = {**body, "actions": [{"day": "2026-03-02", "type": "accept", "caseId": row["caseId"]},
                                {"day": "2026-03-01", "type": "accept", "caseId": row["caseId"]}]}
    assert client.post("/api/m2c/summary", json=late).status_code == 422
