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
                if kind == "exchange_registration_failure" and ayr.prev_t_at_read[r, m] > ayr.fault_t[meter]:
                    continue  # the first read after the swap is the one VEE must catch
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


def test_vee_scorecard_against_truth(ayr):
    sc = views.scorecard(ayr, as_of="2026-12-31")
    kv = views.summary(ayr, "2026-12-31")["kpis"]["vee"]
    assert {k: sc[k] for k in ("truePositives", "falsePositives", "falseNegatives", "precision", "recall")} == \
        {k: kv[k] for k in ("truePositives", "falsePositives", "falseNegatives", "precision", "recall")}
    rows = {a["anomaly"]: a for a in sc["anomalies"]}
    assert set(rows) == set(views.ANOMALIES) and all(0 <= a["flagged"] <= a["reads"] for a in rows.values())
    assert rows["stuck_meter"]["recall"] >= 0.6 and rows["stuck_meter"]["medianDaysToFlag"] > 0
    assert all(x["real"] <= x["cases"] and x["exception"] not in cat.MISSING_TYPES for x in sc["exceptions"])
    assert sc["precision"] >= 0.65  # history alone no longer flags clean reads (no feedback loop)
    # Prior cases only corroborate: a read with no other signal never carries more than a soft history weight.
    got = ~np.isnan(ayr.obs[:, 1:])
    risk = ayr.risk[:, 1:]
    alone = got & (risk[..., 0] == 0) & (risk[..., 1] == 0) & (risk[..., 2] == 0) & (risk[..., 4] == 0)
    assert (risk[..., 3][alone] <= 0.05 + 1e-6).all() and (ayr.disp[:, 1:][alone] == 0).all()


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
    case = next(c for c in base.cases if c.type not in cat.MISSING_TYPES and c.doc < 0 and c.created < 150)
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


def test_a_run_seed_rerolls_the_run_on_the_same_town(ayr, ayr_town):
    town_seed = ayr_town.cfg.seeds.for_("anomalies")
    # No seed: exactly the town-derived draws as before the seed existed; naming the town seed is the same run.
    assert ayr.run_seed is None and ayr.seed == f"{town_seed}:m2c"
    same = M2CRun(ayr_town, seed=town_seed)
    assert same.run_seed is None and same.simulation_id == ayr.simulation_id
    assert views.summary(same, "2026-12-31") == views.summary(ayr, "2026-12-31")
    a, b, c = M2CRun(ayr_town, seed="RUN-1"), M2CRun(ayr_town, seed="RUN-1"), M2CRun(ayr_town, seed="RUN-2")
    assert views.summary(a, "2026-12-31") == views.summary(b, "2026-12-31")  # same seed, same run
    assert a.simulation_id != ayr.simulation_id != c.simulation_id != a.simulation_id
    assert views.summary(a, "2026-12-31")["seed"] == "RUN-1"
    for x, y in ((a, c), (a, ayr)):  # another seed: other missed reads and other anomalies
        assert not np.array_equal(np.isnan(x.obs), np.isnan(y.obs))
        assert not np.array_equal(x.fault_type, y.fault_type) or not np.array_equal(x.fault_t, y.fault_t)
    assert np.array_equal(a.read_t, ayr.read_t)  # the town (routes, read days) is unchanged
    with pytest.raises(ValueError):
        M2CRun(ayr_town, seed="x" * 65)


def test_hosted_m2c_api():
    from fastapi.testclient import TestClient

    from api.index import app

    client = TestClient(app)
    st = client.get("/api/m2c/settings").json()
    assert set(st["schema"]["properties"]) == {"process", "anomalies", "reading", "vee", "billing"}
    assert st["defaults"]["vee"]["accept_confidence"] == 0.75
    seed = client.get("/api/m2c/settings", params={"town": "ayr"}).json()["seed"]
    assert seed["default"] and seed["maxLength"] == 64 and "string" in seed["type"]
    s1 = client.post("/api/m2c/summary", json={"town": "ayr", "seed": "RUN-1"}).json()
    assert s1["seed"] == "RUN-1" and client.post("/api/m2c/summary", json={"town": "ayr", "seed": "RUN-1"}).json() == s1
    plain = client.post("/api/m2c/summary", json={"town": "ayr"}).json()
    assert plain["seed"] is None and plain == client.post(
        "/api/m2c/summary", json={"town": "ayr", "seed": seed["default"]}).json()
    assert plain["kpis"] != s1["kpis"]
    assert client.post("/api/m2c/summary", json={"town": "ayr", "seed": "x" * 65}).status_code == 422
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
    assert client.post("/api/m2c/summary", json={**body, "settings": {"tariffs": {}}}).status_code == 422
    late = {**body, "actions": [{"day": "2026-03-02", "type": "accept", "caseId": row["caseId"]},
                                {"day": "2026-03-01", "type": "accept", "caseId": row["caseId"]}]}
    assert client.post("/api/m2c/summary", json=late).status_code == 422


def test_bill_math_by_hand():
    from utilsim.m2c.billing import charges, lines

    res = {"fixedMonthly": 36.5, "energyBlocks": [{"up_to": 600.0, "price": 0.098}, {"up_to": None, "price": 0.116}],
           "variableDelivery": 0.042, "netMeteringCredit": 0.098, "taxRate": 0.13}
    month = 365 / 12
    comps, sub, tax = charges(res, "electric", np.array([750.0, -40.0]), np.array([100.0, 0.0]), np.zeros(2),
                              np.full(2, month), 1e9, 3.5, np.array([True, False]))
    # 36.50 fixed + 600 × 0.098 + 150 × 0.116 + 750 × 0.042 − 100 × 0.098 = 134.40; HST 13 % = 17.47.
    assert sub[0] == 134.40 and tax[0] == 17.47
    assert [ln["type"] for ln in lines(comps, 0)] == ["fixed", "energy", "energy", "delivery", "credit"]
    assert sub[1] == 30.90 and tax[1] == 4.02  # 36.50 − 40 kWh × 0.14 true-up credit
    # A 30-day period with a 10 % volumetric increase after day 14: blocks and volumes split 14/16 by days.
    comps, sub, _ = charges(res, "electric", np.array([750.0]), np.zeros(1), np.array([290.0]), np.array([320.0]),
                            304.0, 10.0, np.array([False]))
    split = {ln["description"]: ln for ln in lines(comps, 0)}
    assert split["Variable delivery"]["quantity"] == 350.0 and split["Variable delivery (new rates)"]["rate"] == 0.0462
    assert sub[0] == round(sum(ln["amount"] for ln in lines(comps, 0)), 2) == 149.59
    water = {"fixedMonthly": 18.0, "pricePerM3": 2.15, "wastewaterRatio": 1.05, "taxRate": 0.13}
    _, sub, tax = charges(water, "water", np.array([10.0]), np.zeros(1), np.zeros(1), np.full(1, month), 1e9, 0,
                          np.array([False]))
    assert sub[0] == 18.0 + 21.5 + 22.58 and tax[0] == round((18.0 + 21.5 + 22.58) * 0.13, 2)


def test_billing_invoices_payments_and_collections(ayr):
    bk, tw = ayr.books, ayr.town
    live = [d for d in bk.docs if d["reversed"] is None]
    assert len(live) > 0.95 * len(tw.inst_ids) * 11
    assert all(d["released"] is not None or d["case"] >= 0 for d in live)
    # Rate-class errors are blocked, fixed and rebilled at the right rate.
    fixed = [c for c in ayr.cases if c.type == "RATE_CLASS" and c.outcome == "fix_rate"]
    assert fixed
    for c in fixed:
        old = bk.docs[c.doc]
        new = bk.docs[bk.doc_of[old["inst"], old["month"]]]
        assert old["reversed"] is not None and new["replaces"] == old["k"] and new["rate"] == tw.inst_rate[old["inst"]]
    # Invoices consolidate an account's documents of the day; the ledger reconciles.
    assert any(len(inv["docs"]) > 1 for inv in bk.invoices)
    for inv in bk.invoices[:500]:
        assert inv["total"] == round(sum(bk.docs[k]["total"] for k in inv["docs"]), 2)
        assert inv["due"] - inv["issued"] == ayr.cfg.customers_billing.due_days
    acct = bk.invoices[0]["account"]
    entries = bk.ledger[acct]
    assert bk.balance(acct, 400) == round(sum(a for _, _, a, _ in entries), 2)
    # Dunning only for unpaid invoices; no disconnection notices in the winter moratorium.
    from utilsim.m2c.books import _winter

    for inv in bk.invoices:
        for t, kind in inv["dunning"]:
            assert inv.get("paid") is None or inv["paid"] > t or kind == "PAYMENT_REJECTED"
            if kind == "DISCONNECT_NOTICE":  # the moratorium covers electricity and water, not gas
                utilities = {str(tw.commodity[bk.main[bk.docs[k]["inst"]]]) for k in inv["docs"]}
                assert not (_winter(date_of(int(t))) and utilities & {"electric", "water"})
    s = views.summary(ayr, "2026-12-31")["billing"]
    assert s["invoices"] and 0 < s["collected"] <= s["invoiced"] and s["billingError"] >= 0
    p = views.premise(ayr, tw.premise_ids[0], as_of="2026-12-31")
    assert p["billingDocuments"] and p["invoices"] and p["accounts"]
    doc = p["billingDocuments"][0]
    assert doc["totalAmount"] == round(doc["subtotal"] + doc["tax"], 2) and doc["lines"]
    assert any(r["billStatus"] == "billed" and r["invoiceId"] for r in p["reads"])


def test_external_vee_dispositions_become_actions():
    from fastapi.testclient import TestClient

    from api.index import app

    client = TestClient(app)
    slow = {"process": {"analysts": 0, "rpa_coverage": 0}}
    body = {"town": "ayr", "settings": slow, "asOf": "2026-06-30"}
    rows = client.post("/api/process/queue", json={**body, "queue": "VEE_REVIEW", "pageSize": 3}).json()["rows"]
    assert len(rows) >= 2
    decisions = [{"readId": rows[0]["readId"], "disposition": "accept", "decidedAt": "2026-06-30"},
                 {"readId": rows[1]["readId"], "disposition": "reject", "value": 1234.5, "decidedAt": "2026-06-30"},
                 {"readId": "READ-nope", "disposition": "accept"}]
    out = client.post("/api/vee/dispositions", json={**body, "decisions": decisions}).json()
    assert [(a["type"], a["caseId"]) for a in out["actions"]] == [("accept", rows[0]["caseId"]),
                                                                  ("override", rows[1]["caseId"])]
    assert out["unmatched"][0]["readId"] == "READ-nope"
    after = client.post("/api/m2c/case", json={**body, "actions": out["actions"], "caseId": rows[1]["caseId"]}).json()
    assert after["outcome"] == "override" and after["read"]["revisions"][0]["registerValue"] == 1234.5
