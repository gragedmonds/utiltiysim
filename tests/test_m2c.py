"""Meter-to-cash: periodic reads, VEE, work queues and analyst actions, built from snapshots (hosted runtime)."""

from __future__ import annotations

import gzip
import re
from collections import Counter
from pathlib import Path

import numpy as np
import orjson
import pytest

from utilsim.io import schemas
from utilsim.io.snapshot import build_snapshot
from utilsim.m2c import catalog as cat
from utilsim.m2c import views
from utilsim.m2c.base import M2CTown
from utilsim.m2c.calendar import calendar
from utilsim.m2c.run import FAULTS, INF, METHODS, ActionError, M2CRun, resolve_settings
from utilsim.sim.demand import monthly_energy as town_energy
from utilsim.sim.usage import UsageInputs, monthly_energy

CAL = calendar(2026)
add_bdays = CAL.add_bdays
date_of = CAL.date_of

ROOT = Path(__file__).resolve().parents[1]
QUIET = {"anomalies": {"enabled": False},
         "reading": {"ami_missed_read": 0, "amr_missed_read": 0, "manual_no_access": 0},
         # no field work that changes meters: exchanges, removals, drifting or dead-battery meters
         "field": {"old_water_meter_drift": 0, "dead_battery_miss": 0, "seal_exchange": {"rate": 0},
                   "water_meter_replacement": {"rate": 0}, "removal": {"rate": 0}}}


@pytest.fixture(scope="module")
def pack_town() -> M2CTown:
    index = orjson.loads((ROOT / "packs" / "index.json").read_bytes())
    entry = next(t for t in index["towns"] if t["preset"] == "small_town")
    snap = orjson.loads(gzip.decompress((ROOT / "packs" / entry["files"]["snapshot"]["path"]).read_bytes()))
    return M2CTown.from_snapshot(snap)


@pytest.fixture(scope="module")
def small_town(pack_town) -> M2CRun:
    return M2CRun(pack_town)


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


def test_reads_misses_and_estimates(small_town):
    tw, c = small_town.town, small_town.cfg
    got = ~np.isnan(small_town.obs[:, 1:])
    assert got.all(axis=1).sum() > 0.6 * tw.n_registers and got.mean() > 0.95
    ami = np.flatnonzero(tw.tech == "AMI")
    n = len(ami) * 12
    miss = int((~got[ami]).sum())
    p = c.reading.ami_missed_read
    # AMI misses: comm fails plus episodes and missing documents (anomaly rates are small).
    assert p * n - 4 * np.sqrt(n * p) < miss < p * n + 4 * np.sqrt(n * p) + 0.004 * n
    released = small_town.status[:, 1:]
    assert ((released >= 1) & (released <= 3)).mean() > 0.995  # nearly everything reaches billing in the year
    est = small_town.status[:, 1:] == 2
    assert np.all(np.isnan(small_town.obs[:, 1:]) | ~est | (small_town.truth_cls[:, 1:] == 2) | (small_town.disp[:, 1:] > 0))


def test_vee_catches_injected_faults(small_town):
    tw = small_town.town
    hits: Counter = Counter()
    seen: Counter = Counter()
    for r in range(tw.n_registers):
        if tw.direction[r] != "import":
            continue
        meter = tw.meter_of[r]
        for m in range(1, 13):
            if np.isnan(small_town.obs[r, m]) or small_town.truth_cls[r, m] == 0:
                continue
            kind = cat.TRUTH[small_town.truth_cls[r, m]]
            if kind == "meter_fault":
                kind = FAULTS[small_town.fault_type[meter]]
                if kind == "exchange_registration_failure" and small_town.prev_t_at_read[r, m] > small_town.fault_t[meter]:
                    continue  # the first read after the swap is the one VEE must catch
                if kind == "stuck_meter" and not (small_town.cons[r, m] == 0 and tw.occupied[tw.prem[r]]
                                                  and small_town.expected[r, m] >= {"kWh": 30, "m3": 1}[tw.unit[r]]):
                    continue  # only full-period zero reads at occupied premises are detectable by tolerance
            seen[kind] += 1
            hits[kind] += int(small_town.disp[r, m] > 0)
    assert seen["exchange_registration_failure"] and hits["exchange_registration_failure"] == \
        seen["exchange_registration_failure"]
    assert hits["read_error"] >= 0.8 * seen["read_error"] > 0
    assert hits["stuck_meter"] >= 0.9 * seen["stuck_meter"] > 0
    clean = ~np.isnan(small_town.obs[:, 1:]) & (small_town.truth_cls[:, 1:] == 0)
    assert (small_town.disp[:, 1:][clean] == 0).mean() > 0.99


def test_vee_scorecard_against_truth(small_town):
    sc = views.scorecard(small_town, as_of="2026-12-31")
    kv = views.summary(small_town, "2026-12-31")["kpis"]["vee"]
    assert {k: sc[k] for k in ("truePositives", "falsePositives", "falseNegatives", "precision", "recall")} == \
        {k: kv[k] for k in ("truePositives", "falsePositives", "falseNegatives", "precision", "recall")}
    rows = {a["anomaly"]: a for a in sc["anomalies"]}
    assert set(rows) == set(views.ANOMALIES) and all(0 <= a["flagged"] <= a["reads"] for a in rows.values())
    # Stuck-meter recall is 0.68-0.69 on the 3,300- and 5,500-home towns; this town has only 24 stuck meters (62
    # reads), so its 0.58 is sampling spread. The floor catches a real regression, not that spread.
    assert rows["stuck_meter"]["recall"] >= 0.55 and rows["stuck_meter"]["medianDaysToFlag"] > 0
    assert all(x["real"] <= x["cases"] and x["exception"] not in cat.MISSING_TYPES for x in sc["exceptions"])
    assert sc["precision"] >= 0.65  # history alone no longer flags clean reads (no feedback loop)
    # Prior cases only corroborate: a read with no other signal never carries more than a soft history weight.
    got = ~np.isnan(small_town.obs[:, 1:])
    risk = small_town.risk[:, 1:]
    alone = got & (risk[..., 0] == 0) & (risk[..., 1] == 0) & (risk[..., 2] == 0) & (risk[..., 4] == 0)
    assert (risk[..., 3][alone] <= 0.05 + 1e-6).all() and (small_town.disp[:, 1:][alone] == 0).all()


def test_queues_follow_the_workforce(pack_town):
    none = M2CRun(pack_town, {"process": {"analysts": 0, "rpa_coverage": 0}})
    backlog = none.series["ESTIMATION"][:, 2] + none.series["VEE_REVIEW"][:, 2]
    assert backlog[-1] > 500 and np.all(np.diff(backlog) >= 0)
    auto = M2CRun(pack_town, {"process": {"rpa_coverage": 1}})
    missing = [c for c in auto.cases if c.type in ("COMM_FAIL", "NO_ACCESS", "NO_READ") and c.created < 360]
    assert missing and all(any(e[1] == "AUTO_RESOLVED" for e in c.events) for c in missing)
    s = views.summary(none, "2026-12-31")
    assert s["kpis"]["carry"] > views.summary(auto, "2026-12-31")["kpis"]["carry"]


def test_actions_are_append_only_and_take_effect(pack_town):
    base = M2CRun(pack_town, {"process": {"analysts": 0, "rpa_coverage": 0}})
    case = next(c for c in base.cases if c.type not in cat.MISSING_TYPES and c.doc < 0 and c.created < 150)
    day = add_bdays(int(case.created), 3)
    when = date_of(day).isoformat()
    act = [{"id": "A1", "day": when, "type": "override", "caseId": case.id, "value": 1234.5}]
    run = M2CRun(pack_town, {"process": {"analysts": 0, "rpa_coverage": 0}}, act)
    mine = run.case_index[case.id]
    assert mine.outcome == "override" and int(mine.resolved) == day
    assert run.released[case.r, case.month] == 1234.5 and run.status[case.r, case.month] == 3
    before = [(c.id, [e for e in c.events if e[0] < day]) for c in base.cases if c.created < day]
    assert before == [(c.id, [e for e in c.events if e[0] < day]) for c in run.cases if c.created < day]
    with pytest.raises(ValueError, match="append-only"):
        M2CRun(pack_town, None, [act[0], {**act[0], "id": "A0", "day": "2026-01-05"}])
    with pytest.raises(ValueError):
        resolve_settings(pack_town.cfg, {"vee": {"high_ratio": 0.5}})
    # A case id the run does not have: the newest action is refused, an older one is skipped with a warning.
    slow = {"process": {"analysts": 0, "rpa_coverage": 0}}
    with pytest.raises(ActionError, match="CASE-nope does not exist in this run"):
        M2CRun(pack_town, slow, [{**act[0], "caseId": "CASE-nope"}])
    stale = M2CRun(pack_town, slow, [{**act[0], "caseId": "CASE-nope"}, {**act[0], "type": "note", "text": "x"}])
    assert any("CASE-nope does not exist" in w and "skipped" in w for w in stale.warnings)


def test_views_are_valid_bounded_and_deterministic(small_town, pack_town):
    s = views.summary(small_town, "2026-12-31")
    assert s == views.summary(M2CRun(pack_town), "2026-12-31")
    assert len(s["premises"]["status"]) == len(pack_town.premise_ids)
    assert sum(q["open"] for q in s["queues"]) == s["kpis"]["casesOpen"]
    for q in s["queues"]:
        assert len(q["series"]["backlog"]) == 365 and q["series"]["backlog"][-1] == q["open"]
    w = views.worklist(small_town, None, as_of="2026-12-31", status="all", sort="impact", page_size=500)
    assert w["total"] == s["kpis"]["casesOpened"] and len(w["rows"]) == 200
    c = views.case_view(small_town, w["rows"][0]["caseId"], as_of="2026-12-31", truth=True)
    assert c["events"][0]["eventType"] == c["type"] and len(c["decision"]["tests"]) == 5
    assert {e["type"] for e in c["edges"]} <= set(cat.EDGE_TYPES)
    p = views.premise(small_town, c["premiseId"], as_of="2026-12-31")
    for rd in p["reads"]:
        assert not schemas.errors("meter-read-1.1", rd), rd["id"]
    fx = views.vee_export(small_town, 6, 3)
    assert fx["reads"] and not schemas.errors("vee-input-fixture-1.1", fx)
    for doc in (s, w, c, p, fx, views.graph(small_town, 6), views.costs(small_town)):
        assert len(orjson.dumps(doc)) < 4_500_000
    assert views.summary(small_town, "2026-03-31")["kpis"]["reads"] < s["kpis"]["reads"]


def test_a_run_seed_rerolls_the_run_on_the_same_town(small_town, pack_town):
    town_seed = pack_town.cfg.seeds.for_("anomalies")
    # No seed: exactly the town-derived draws as before the seed existed; naming the town seed is the same run.
    assert small_town.run_seed is None and small_town.seed == f"{town_seed}:m2c"
    same = M2CRun(pack_town, seed=town_seed)
    assert same.run_seed is None and same.simulation_id == small_town.simulation_id
    assert views.summary(same, "2026-12-31") == views.summary(small_town, "2026-12-31")
    a, b, c = M2CRun(pack_town, seed="RUN-1"), M2CRun(pack_town, seed="RUN-1"), M2CRun(pack_town, seed="RUN-2")
    assert views.summary(a, "2026-12-31") == views.summary(b, "2026-12-31")  # same seed, same run
    assert a.simulation_id != small_town.simulation_id != c.simulation_id != a.simulation_id
    assert views.summary(a, "2026-12-31")["seed"] == "RUN-1"
    for x, y in ((a, c), (a, small_town)):  # another seed: other missed reads and other anomalies
        assert not np.array_equal(np.isnan(x.obs), np.isnan(y.obs))
        assert not np.array_equal(x.fault_type, y.fault_type) or not np.array_equal(x.fault_t, y.fault_t)
    assert np.array_equal(a.read_t, small_town.read_t)  # the town (routes, read days) is unchanged
    with pytest.raises(ValueError):
        M2CRun(pack_town, seed="x" * 65)


def test_hosted_m2c_api():
    from fastapi.testclient import TestClient

    from api.app import app

    client = TestClient(app)
    st = client.get("/api/m2c/settings").json()
    assert set(st["schema"]["properties"]) == {"process", "anomalies", "reading", "vee", "billing", "contact", "outages",
                                                  "field", "kpi"}
    assert st["defaults"]["vee"]["accept_confidence"] == 0.75
    seed = client.get("/api/m2c/settings", params={"town": "small_town"}).json()["seed"]
    assert seed["default"] and seed["maxLength"] == 64 and "string" in seed["type"]
    s1 = client.post("/api/m2c/summary", json={"town": "small_town", "seed": "RUN-1"}).json()
    assert s1["seed"] == "RUN-1" and client.post("/api/m2c/summary", json={"town": "small_town", "seed": "RUN-1"}).json() == s1
    plain = client.post("/api/m2c/summary", json={"town": "small_town"}).json()
    assert plain["seed"] is None and plain == client.post(
        "/api/m2c/summary", json={"town": "small_town", "seed": seed["default"]}).json()
    assert plain["kpis"] != s1["kpis"]
    assert client.post("/api/m2c/summary", json={"town": "small_town", "seed": "x" * 65}).status_code == 422
    body = {"town": "small_town", "asOf": "2026-08-31", "settings": {"process": {"analysts": 1}}}
    s = client.post("/api/m2c/summary", json=body)
    assert s.status_code == 200 and s.json()["schemaVersion"] == "m2c-summary/1.0"
    q = client.post("/api/process/queue", json={**body, "status": "all", "pageSize": 5}).json()
    assert q["total"] > 0 and len(q["rows"]) == 5
    # A read case (collections cases are about an account and carry no read decision).
    row = client.post("/api/process/queue", json={**body, "status": "all", "queue": "VEE_REVIEW",
                                                  "pageSize": 1}).json()["rows"][0]
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


def test_billing_invoices_payments_and_collections(small_town):
    bk, tw = small_town.books, small_town.town
    live = [d for d in bk.docs if d["reversed"] is None]
    assert len(live) > 0.95 * len(tw.inst_ids) * 11
    assert all(d["released"] is not None or d["case"] >= 0 for d in live)
    # Rate-class errors are blocked, fixed and rebilled at the right rate.
    fixed = [c for c in small_town.cases if c.type == "RATE_CLASS" and c.outcome == "fix_rate"]
    assert fixed
    for c in fixed:
        old = bk.docs[c.doc]
        new = bk.docs[bk.doc_of[old["inst"], old["month"]]]
        assert old["reversed"] is not None and new["replaces"] == old["k"] and new["rate"] == tw.inst_rate[old["inst"]]
    # Invoices consolidate an account's documents of the day; the ledger reconciles.
    assert any(len(inv["docs"]) > 1 for inv in bk.invoices)
    for inv in bk.invoices[:500]:
        assert inv["total"] == round(sum(bk.docs[k]["total"] for k in inv["docs"]), 2)
        assert inv["due"] - inv["issued"] == small_town.cfg.customers_billing.due_days
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
    s = views.summary(small_town, "2026-12-31")["billing"]
    assert s["invoices"] and 0 < s["collected"] <= s["invoiced"] and s["billingError"] >= 0
    p = views.premise(small_town, tw.premise_ids[0], as_of="2026-12-31")
    assert p["billingDocuments"] and p["invoices"] and p["accounts"]
    doc = p["billingDocuments"][0]
    assert doc["totalAmount"] == round(doc["subtotal"] + doc["tax"], 2) and doc["lines"]
    assert any(r["billStatus"] == "billed" and r["invoiceId"] for r in p["reads"])


def test_external_vee_dispositions_become_actions():
    from fastapi.testclient import TestClient

    from api.app import app

    client = TestClient(app)
    slow = {"process": {"analysts": 0, "rpa_coverage": 0}}
    body = {"town": "small_town", "settings": slow, "asOf": "2026-06-30"}
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


# ---- the July 2026 QA run on the small town -----------------------------------------------------------------------------------
SLOW = {"process": {"analysts": 0, "rpa_coverage": 0}}  # nothing works the queues but you (and supervisors, crews)


def iso(day: int) -> str:
    return date_of(day).isoformat()


@pytest.fixture(scope="module")
def slow(pack_town) -> M2CRun:
    return M2CRun(pack_town, SLOW)


@pytest.fixture(scope="module")
def outage(small_town, pack_town):
    """The default run plus, on an early-March read day, a power outage on five AMI electric premises and an AMI
    collector outage on three others, both over the 02:00 read."""
    tw = pack_town
    d, (_, rows) = next((d, b) for d, b in sorted(small_town.batches.items()) if 60 < d < 80)
    ami = sorted({tw.premise_ids[tw.prem[r]] for r in rows if tw.tech[r] == "AMI" and tw.commodity[r] == "electric"})
    outages = [{"day": iso(d), "utility": "electric", "start": 0, "end": 4 * 3600, "premiseIds": ami[:5]},
               {"day": iso(d), "utility": "ami", "start": 0, "end": 4 * 3600, "premiseIds": ami[5:8]}]
    return d, M2CRun(pack_town, outages=outages), outages


def qa_case(run: M2CRun):
    """The shape of the July 2026 QA report (a water read of 61.701 against a last actual read of 35,623.686): the
    first July water register read far below its last actual read (under 1 percent of it, an actual before it)."""
    tw = run.town
    return next(c for c in run.cases if c.type == "REGISTER_REGRESSION" and c.month == 7 and tw.unit[c.r] == "m3"
                and "water" in tw.reg_ids[c.r] and run.obs[c.r, c.month] < 0.01 * run.prev_at_read[c.r, c.month])


def qa_values(run: M2CRun, c) -> tuple[float, float, float]:
    """The case's read, the last actual read before it, and the difference (3 decimals)."""
    obs, prev = float(run.obs[c.r, c.month]), float(run.prev_at_read[c.r, c.month])
    return obs, prev, round(obs - prev, 3)


def test_an_action_on_a_case_that_is_not_open_is_refused_and_says_when(pack_town, small_town, slow):
    case = next(c for c in slow.cases if c.doc < 0 and c.type in ("HIGH_USAGE", "LOW_USAGE") and 100 < c.created < 150)
    bill = next(c for c in slow.cases if c.doc >= 0 and 100 < c.created < 200)
    for c, hhmm in ((case, "18:00"), (bill, "19:30")):  # the evening VEE batch and billing run raise them
        d = int(c.created)
        with pytest.raises(ActionError, match=rf"{c.id} was raised at {hhmm} on {iso(d)}; work it from {iso(d + 1)}"):
            M2CRun(pack_town, SLOW, [{"day": iso(d), "type": "estimate", "caseId": c.id}])
        cv = views.case_view(slow, c.id, as_of=iso(d))
        assert cv["actionableFrom"] == iso(d + 1) and cv["actions"] == [] and cv["studioActions"] == []
        row = views.worklist(slow, None, as_of=iso(d), search=c.id)["rows"][0]
        assert row["actionableFrom"] == iso(d + 1)
    d = int(case.created)
    nxt = views.case_view(slow, case.id, as_of=iso(d + 1))
    assert nxt["actions"] and nxt["studioActions"]
    done = M2CRun(pack_town, SLOW, [{"day": iso(d + 1), "type": "estimate", "caseId": case.id}])
    assert done.case_index[case.id].outcome == "estimate" and int(done.case_index[case.id].resolved) == d + 1
    # An older action that no longer applies is skipped with the same reason, so a stored list still replays.
    stored = M2CRun(pack_town, SLOW, [{"id": "A1", "day": iso(d), "type": "estimate", "caseId": case.id},
                                     {"id": "A2", "day": iso(d + 1), "type": "note", "caseId": case.id, "text": "x"}])
    assert any(w.startswith(f"A1: {case.id} was raised at 18:00") and w.endswith("(skipped)") for w in stored.warnings)
    assert stored.case_index[case.id].resolved is None
    # Already resolved by automation before your action lands.
    auto = next(c for c in small_town.cases if c.by == "RPA" and c.resolved is not None and 100 < c.created < 200)
    day = int(auto.resolved) + 1
    minutes = round((auto.resolved - int(auto.resolved)) * 1440)
    with pytest.raises(ActionError, match=rf"{auto.id} was already completed by RPA at {minutes // 60:02d}:"
                                          rf"{minutes % 60:02d} on {iso(int(auto.resolved))}"):
        M2CRun(pack_town, None, [{"day": iso(day), "type": "escalate", "caseId": auto.id}])


def test_case_ids_are_content_derived_and_survive_an_earlier_outage(small_town, outage):
    d, out, _ = outage
    key = lambda c: (c.type, c.r, c.month, round(c.created * 1440))  # noqa: E731
    # The contact centre's cases follow the lines' queue, which an earlier change can reorder: compare the rest.
    before = {key(c): c for c in small_town.cases if c.created_by != "contact_centre"}
    after = {key(c): c for c in out.cases if c.created_by != "contact_centre"}
    added = [c for k, c in after.items() if k not in before]
    assert added and all(c.type == "COMM_FAIL" and int(c.created) == d for c in added)
    later = [k for k in before if before[k].created > d + 1]
    assert later and all(k in after and after[k].id == before[k].id for k in later)
    assert any(after[k].idx != before[k].idx for k in later)  # a sequence number would have renumbered them
    pattern = re.compile(r"CASE-(\d{6})-[0-9A-HJKMNP-TV-Z]{6}")
    for c in small_town.cases:
        hit = pattern.fullmatch(c.id)
        assert hit and hit[1] == date_of(int(c.created)).strftime("%y%m%d"), c.id
    assert len({c.id for c in small_town.cases}) == len(small_town.cases)
    # A collision takes the next salt, deterministically.
    c = small_town.cases[0]
    again = small_town.case_id(int(c.created), c.type, c.r, c.month, c.created)
    assert again != c.id and again == small_town.case_id(int(c.created), c.type, c.r, c.month, c.created)


def test_a_backwards_register_is_never_released_as_read(small_town):
    c = qa_case(small_town)
    r, m = c.r, c.month
    obs, prev, delta = qa_values(small_town, c)
    assert obs < 0.01 * prev and delta < -1000
    assert c.outcome != "accept" and small_town.released[r, m] >= prev and METHODS[small_town.method[r, m]] == "estimated"
    bk = small_town.books
    doc = bk.docs[bk.doc_of[small_town.town.inst_of[r], m]]
    assert doc["qImp"] > 0 and doc["total"] > 0 and doc["estimated"]
    cv = views.case_view(small_town, c.id, as_of="2026-12-31")
    assert cv["registerWentBackwards"] and cv["registerDelta"] == delta and not cv["previousEstimated"]
    assert cv["released"]["method"] == "estimated" and cv["released"]["registerValue"] >= prev
    # The whole year: no read value released by anyone (RPA, analysts, supervisors, crews) below its last actual read.
    for rr in range(small_town.town.n_registers):
        for mm in range(1, 13):
            if small_town.method[rr, mm] in (1, 3, 4):
                assert small_town.backwards(rr, mm, float(small_town.released[rr, mm]), INF) < 0, small_town.read_id(rr, mm)
    # No large outsort released by RPA, and no true-up beyond the bound went out unreviewed.
    limit = small_town.cfg.billing.outsort_auto_release_max
    assert not [x.id for x in small_town.cases if x.by == "RPA" and x.doc >= 0 and abs(bk.docs[x.doc]["total"]) > limit]
    assert all(x.type != "TRUE_UP" or x.by not in (None, "RPA") for x in small_town.cases)


def test_your_accept_on_a_backwards_register_is_refused_and_large_credits_wait_for_a_person(pack_town):
    nobody = {"process": {"analysts": 0}}  # RPA at its default coverage (it covers BILL_CREDIT); no analysts
    run = M2CRun(pack_town, nobody)
    c = qa_case(run)
    r, m, day = c.r, c.month, iso(int(c.created) + 1)
    obs, prev, delta = qa_values(run, c)
    cv = views.case_view(run, c.id, as_of=day)
    assert cv["registerWentBackwards"] and cv["registerDelta"] == delta
    assert "accept" not in cv["actions"] and {"override", "estimate", "field_order"} <= set(cv["actions"])
    with pytest.raises(ActionError, match=rf"went backwards \({re.escape(f'{obs:,.3f}')} against the last actual read "
                                          rf"{re.escape(f'{prev:,.3f}')} on 2026-0[56]-\d\d\).*estimate it, correct "
                                          r"the value \(override\) or send a field order"):
        M2CRun(pack_town, nobody, [{"day": day, "type": "accept", "caseId": c.id}])
    inst = pack_town.inst_of[r]

    def corrected(value: float, settings=nobody):
        """Your correction to ``value``, and the first billing document and outsort for that period."""
        run = M2CRun(pack_town, settings, [{"day": day, "type": "override", "caseId": c.id, "value": value}])
        doc = next(d for d in run.books.docs if d["inst"] == inst and d["month"] == m)
        return doc, run.cases[doc["case"]] if doc["case"] >= 0 else None

    # The QA value as a correction: a true-up far beyond any over-estimate is a TRUE_UP block that waits for a person.
    doc, bc = corrected(obs)
    assert bc.type == "TRUE_UP" and doc["qImp"] < 0.99 * delta and bc.rpa_at is None and bc.resolved is None
    assert doc["released"] is None and cat.category(bc.type, bc.queue) == "Billing Outsorts"
    # A plausible true-up that is still a large credit: BILL_CREDIT, above the RPA limit, so RPA leaves it alone …
    doc, bc = corrected(prev - 150)
    assert bc.type == "BILL_CREDIT" and doc["total"] < -500 and bc.rpa_at is None and bc.resolved is None
    # … unless the limit allows it; a small credit is released by RPA as before.
    doc, bc = corrected(prev - 150, {**nobody, "billing": {"outsort_auto_release_max": 1000}})
    assert bc.type == "BILL_CREDIT" and bc.by == "RPA" and doc["released"] is not None
    doc, bc = corrected(prev - 40)
    assert bc.type == "BILL_CREDIT" and -500 < doc["total"] < -75 and bc.by == "RPA" and doc["released"] is not None


def test_bills_built_on_estimated_reads_say_so(small_town):
    bk, tw = small_town.books, small_town.town
    for d in bk.docs:
        est = any(small_town.status[r, d["month"]] == 2 for r in tw.inst_rows[d["inst"]])
        on_check = bool(d.get("checkRead"))  # a disputed bill rebilled on a check read is not an estimate
        assert d["estimated"] == (not on_check and (est or bool(d.get("rebilledOnEstimate")))), bk.doc_id(d)
    assert sum(d["estimated"] for d in bk.docs) > 100
    doc = next(d for d in bk.docs if d["estimated"] and d["version"] == 1 and d["invoice"] >= 0)
    j = views.doc_json(small_town, doc, 400.0)
    assert j["estimated"] and j["estimatedReadIds"]
    inv = views.invoice_json(small_town, bk.invoices[doc["invoice"]], 400.0)
    assert inv["estimated"] and j["id"] in inv["estimatedBillingDocumentIds"]
    p = views.premise(small_town, j["premiseId"], as_of="2026-12-31")
    assert any(x["id"] == j["id"] and x["estimated"] for x in p["billingDocuments"])
    assert any(x["id"] == inv["id"] and x["estimated"] for x in p["invoices"])
    assert any(r["id"] in j["estimatedReadIds"] and r["revisions"][0]["readType"] == "estimated" for r in p["reads"])


def test_missing_read_cases_name_their_cause_and_who_raised_them(small_town, slow, outage):
    first: dict[str, object] = {}
    for run in (small_town, outage[1]):
        for c in run.cases:
            if c.type in cat.MISSING_TYPES:
                first.setdefault(views.missing_cause(run, c.r, c.month)["code"], (run, c))
    assert set(first) == {"comm_fail", "no_access", "no_read_document", "power_outage", "collector_outage"}
    by = {"comm_fail": "ami_head_end", "no_access": "meter_reading_route", "no_read_document": "vee_batch",
          "power_outage": "ami_head_end", "collector_outage": "ami_head_end"}
    for code, (run, c) in first.items():
        cv = views.case_view(run, c.id, as_of="2026-12-31")
        assert cv["cause"]["code"] == code and cv["cause"]["reason"].startswith("No read: "), cv["cause"]
        assert cv["createdBy"] == by[code] and cv["createdByLabel"] == cat.CREATED_BY[by[code]]
        rationale = [t["rationale"] for t in cv["decision"]["tests"]]
        assert {t["outcome"] for t in cv["decision"]["tests"]} == {"not_applicable"} and len(set(rationale)) == 5
        assert cv["cause"]["reason"] in rationale[0] and cv["decision"]["cause"] == cv["cause"]
    run, c = first["power_outage"]
    gasp = views.missing_cause(run, c.r, c.month)
    assert "AMI last gasp" in gasp["reason"] and gasp["lastGaspAt"] == run.iso(outage[0])  # lost power at midnight
    run, c = first["collector_outage"]
    assert views.missing_cause(run, c.r, c.month)["outageSince"] == run.iso(outage[0])
    kinds = {c.created_by for c in small_town.cases}
    assert kinds == {"ami_head_end", "meter_reading_route", "vee_batch", "billing_run", "collections", "contact_centre"}
    assert all(c.type in cat.COLLECTION_TYPES for c in small_town.cases if c.created_by == "collections")
    assert all(c.created_by == ("contact_centre" if c.type == "BILL_DISPUTE" else "billing_run")
               for c in small_town.cases if c.doc >= 0)  # a disputed bill is the contact centre's case
    # A missing read has no value to accept or override: estimate, a field order or an escalation.
    c = next(c for c in slow.cases if c.type == "COMM_FAIL" and c.resolved is None and 100 < c.created < 200)
    assert views.case_view(slow, c.id, as_of=iso(int(c.created) + 1))["actions"] == ["estimate", "field_order",
                                                                                     "escalate"]


def test_case_views_carry_the_data_a_decision_needs(small_town):
    c = next(c for c in small_town.cases if c.outcome == "correct" and c.created < 300)
    r, m = c.r, c.month
    cv = views.case_view(small_town, c.id, as_of="2026-12-31")
    assert cv["expected"] == {"registerValue": round(float(small_town.prev_at_read[r, m] + small_town.expected[r, m]), 3),
                              "consumption": round(float(small_town.expected[r, m]), 3)}
    rel = cv["released"]
    assert rel["method"] in ("corrected", "field_read") and rel["by"] == c.by and rel["at"] == small_town.iso(c.resolved)
    assert rel["registerValue"] == round(float(small_town.released[r, m]), 3)
    assert rel["consumption"] == round(float(small_town.released[r, m] - small_town.released[r, m - 1]), 3)
    hist = cv["readHistory"]
    assert len(hist) == 13 and [h["date"] for h in hist] == sorted(h["date"] for h in hist)
    assert set(hist[0]) == {"readId", "date", "register", "consumption", "type", "estimated", "method", "veeStatus",
                            "caseId"}
    mine = next(h for h in hist if h["caseId"] == c.id)
    assert mine["register"] == rel["registerValue"] and mine["type"] == "adjusted" and not mine["estimated"]
    assert cv["registerDelta"] == round(float(small_town.obs[r, m] - small_town.prev_at_read[r, m]), 3)
    field = next(c for c in small_town.cases if any(e[1] == "SPECIAL_READ" for e in c.events) and c.type in cat.MISSING_TYPES)
    assert views.case_view(small_town, field.id, as_of="2026-12-31")["released"]["method"] == "field_read"
    row = views.worklist(small_town, None, as_of="2026-12-31", status="all", search=c.id)["rows"][0]
    assert {"registerDelta", "registerWentBackwards", "previousEstimated", "actionableFrom", "createdBy", "cause",
            "releasedMethod"} <= set(row) and row["releasedMethod"] == rel["method"]


def test_queue_sorted_by_created_is_newest_first_and_pages_add_up():
    from fastapi.testclient import TestClient

    from api.app import app

    client = TestClient(app)
    body = {"town": "small_town", "asOf": "2026-08-31", "status": "all", "sort": "created", "pageSize": 200}
    rows, page = [], 1
    while True:
        res = client.post("/api/process/queue", json={**body, "page": page}).json()
        rows += res["rows"]
        if len(res["rows"]) < 200:
            break
        page += 1
    assert len(rows) == res["total"] == len({r["caseId"] for r in rows}) > 400
    created = [r["createdAt"] for r in rows]
    assert created == sorted(created, reverse=True) and created[0] > created[-1]
    # Through the API, an action on a case raised later that day is a 422 that says when it can be worked.
    late = rows[0]
    assert late["actionableFrom"] == "2026-09-01"
    r = client.post("/api/m2c/summary", json={"town": "small_town", "asOf": "2026-08-31", "actions": [
        {"day": "2026-08-31", "type": "escalate", "caseId": late["caseId"]}]})
    assert r.status_code == 422, r.text
    assert f"{late['caseId']} was raised at" in r.json()["detail"] and "work it from 2026-09-01" in r.json()["detail"]


def test_the_days_cycle_on_the_map_includes_the_days_own_outages(small_town, outage):
    from api._m2c import m2c_day

    d, full, outages = outage
    hit = set(outages[0]["premiseIds"] + outages[1]["premiseIds"])
    orders, outcomes, cycle = m2c_day("small_town", iso(d), {"outages": outages})
    assert hit <= set(cycle["ami"]["missed"])  # the 01:40-style pole break shows on the card as missed reads
    assert cycle == views.day_cycle(full, d)  # the same day the Workspace shows (VEE, bills, invoices too)
    # The morning's field orders still never depend on the day's own outages.
    assert orders == m2c_day("small_town", iso(d), {})[0]
    base = set(views.day_cycle(small_town, d)["ami"]["missed"])  # the day without its outages
    assert hit - base and set(cycle["ami"]["missed"]) == base | hit


def test_a_backwards_read_record_has_no_rollover_consumption(small_town):
    c = qa_case(small_town)
    _, _, delta = qa_values(small_town, c)
    rec = views.read_record(small_town, c.r, c.month, 400.0)
    assert rec["consumption"] is None and rec["registerRegression"] and not rec["rolloverFlag"]
    assert rec["registerDelta"] == delta
    day = iso(int(c.created))
    cv = views.case_view(small_town, c.id, as_of=day)
    row = views.worklist(small_town, None, as_of=day, search=c.id)["rows"][0]
    assert row["consumption"] == cv["consumption"] == delta and row["impact"] == cv["impact"]
    tests = [t["rationale"] for t in cv["decision"]["tests"]]
    assert "went backwards from the last actual read" in tests[0] and "no period use" in tests[2]
    # A real rollover still wraps.
    tw = small_town.town
    mod = 10.0 ** tw.digits
    wrap = np.argwhere((small_town.obs[:, 1:] < small_town.prev_at_read[:, 1:]) & (small_town.cons[:, 1:] >= 0)
                       & (small_town.prev_at_read[:, 1:] > 0.8 * mod[:, None]))
    for r, j in wrap[:3]:
        rec = views.read_record(small_town, int(r), int(j) + 1, 400.0)
        assert rec["rolloverFlag"] and not rec["registerRegression"] and rec["consumption"] > 0


def test_every_value_exception_carries_a_validation_code(small_town):
    for c in small_town.cases:
        if c.doc < 0 and c.work is None and c.type not in cat.MISSING_TYPES:
            assert small_town.code[c.r, c.month] >= 0, (c.id, c.type)
    low = next(c for c in small_town.cases if c.type == "PERSISTENT_LOW")
    row = views.worklist(small_town, None, as_of="2026-12-31", status="all", search=low.id)["rows"][0]
    assert row["sapValidationCode"] in ("SIM-T03", "SIM-T02", "SIM-L01") and "·" in row["validationText"]


def test_a_read_missed_in_an_outage_says_so_on_the_read_record(outage):
    from utilsim.m2c import lookups

    d, run, outages = outage
    tw = run.town
    r = next(int(r) for r in np.flatnonzero(tw.prem == tw.premise_index[outages[0]["premiseIds"][0]])
             if tw.commodity[r] == "electric" and tw.direction[r] == "import")
    m = next(j for j in range(1, 13) if int(tw.read_day[r, j]) == d)
    rec = views.read_record(run, r, m, 400.0)
    assert rec["reasonCode"] == "SIM_POWER_OUTAGE" and rec["cause"]["code"] == "power_outage"
    assert rec["cause"]["outageStart"] == run.iso(d) and rec["cause"]["outageEnd"] == run.iso(d + 4 / 24)
    assert "(back at 04:00 on" in rec["cause"]["reason"]
    doc = lookups.read_document(run, run.read_id(r, m), as_of="2026-12-31")
    assert doc["read"]["cause"] == rec["cause"]
    assert next(h for h in doc["history"] if h["readId"] == run.read_id(r, m))["cause"]["code"] == "power_outage"


def test_the_billing_queue_can_be_left_to_you(pack_town):
    run = M2CRun(pack_town, {"billing": {"billing_queue_worked_by": "you"}})
    bills = [c for c in run.cases if c.doc >= 0]
    assert {c.type for c in bills} >= {"HIGH_BILL", "BILL_CREDIT", "RATE_CLASS"}
    assert all(c.resolved is None and c.rpa_at is None for c in bills)
    c = next(c for c in bills if c.type == "HIGH_BILL")
    cv = views.case_view(run, c.id, as_of=iso(int(c.created) + 1))
    assert cv["actions"] == ["accept", "estimate", "escalate"] and cv["category"] == "Billing Outsorts"
    done = M2CRun(pack_town, {"billing": {"billing_queue_worked_by": "you"}},
                  [{"day": iso(int(c.created) + 1), "type": "accept", "caseId": c.id, "note": "Pool filled"}])
    assert done.case_index[c.id].outcome == "release" and done.case_index[c.id].by == "you"
