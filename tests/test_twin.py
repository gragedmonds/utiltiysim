"""The digital twin: observed KPIs in, a setup that replays them out (utilsim/twin)."""

from __future__ import annotations

import orjson
import pytest
from fastapi.testclient import TestClient

from api._agent_config import Proposal, validate_proposal
from api.app import app
from utilsim.config.model import SimConfig
from utilsim.io.snapshot import build_snapshot
from utilsim.m2c.base import M2CTown
from utilsim.m2c.run import M2CRun, resolve_settings
from utilsim.twin import (
    DISTRICT_HOMES,
    KPI_BY_ID,
    KPIS,
    LEVERS,
    TwinSpec,
    dictionary,
    fit,
    measure,
    patches,
    sizing,
    staffing,
    window,
)

QUIET = {"anomalies": {"enabled": False},
         "reading": {"ami_missed_read": 0, "amr_missed_read": 0, "manual_no_access": 0},
         "field": {"old_water_meter_drift": 0, "dead_battery_miss": 0, "seal_exchange": {"rate": 0},
                   "water_meter_replacement": {"rate": 0}, "removal": {"rate": 0}}}


@pytest.fixture(scope="module")
def town(town120) -> M2CTown:
    snap = orjson.loads(orjson.dumps(build_snapshot(town120), option=orjson.OPT_SERIALIZE_NUMPY))
    return M2CTown.from_snapshot(snap)


@pytest.fixture(scope="module")
def defaults(town) -> dict:
    run = M2CRun(town)
    return measure(run, window(run))


# ---- the dictionary and the levers ---------------------------------------------------------------------------------
def test_the_dictionary_is_consistent():
    d = dictionary()
    assert d["schemaVersion"] == "twin-fit/1.0"
    assert {k["id"] for k in d["kpis"]} == set(KPI_BY_ID) and len(KPIS) >= 10
    assert {lever["id"] for lever in d["levers"]} == set(LEVERS)
    for kpi in KPIS:  # every lever a KPI names exists, with a direction
        assert all(lever in LEVERS and direction in (-1, 1) for lever, direction in kpi.levers), kpi.id
        assert kpi.unit in ("share", "days", "per_1000_accounts_year") and kpi.better in ("higher", "lower")
    assert all(lever["settings"] for lever in d["levers"])  # each lever sets something
    assert d["defaults"]["districtHomes"] == DISTRICT_HOMES


def test_levers_at_their_defaults_change_nothing_and_stay_in_bounds():
    base = SimConfig()
    same = resolve_settings(base, patches({lever: LEVERS[lever].default for lever in LEVERS}))
    assert same.model_dump() == base.model_dump()
    for lever in LEVERS.values():
        for v in (lever.lo, lever.hi, (lever.lo + lever.hi) / 2, lever.default + lever.step, lever.default - lever.step):
            resolve_settings(base, lever.patch(v))  # every value the fit can reach is a valid configuration
    assert patches({"missed_reads": 2.0})["reading"]["ami_missed_read"] == pytest.approx(2 * base.reading.ami_missed_read)
    assert patches({"vee_strictness": 1.0})["vee"]["high_ratio"] == 1.25
    assert patches({"vee_strictness": 0.0})["vee"]["low_ratio"] == 0.15
    assert patches({"pickup_lag": 7})["process"] == {"analyst_queue_days_min": 7, "analyst_queue_days_max": 9}


# ---- the measures ---------------------------------------------------------------------------------------------------
def test_a_quiet_year_measures_as_one(town):
    run = M2CRun(town, QUIET)
    m = measure(run, window(run))
    assert m["missed_read_share"] == 0 and m["estimated_read_share"] < 0.001  # a few estimates from field work
    assert m["invoice_timeliness"] == 1.0
    assert 0 <= m["exceptions_vee"] < 50 and m["exceptions_all"] < 200  # move-ins, disputes: a few cases remain
    assert 0 < m["collected_share"] <= 1 and m["days_to_pay"] > 0
    # A window: the second half annualised, and a one-day window that holds no read.
    half = measure(run, window(run, "2026-07-01"))
    assert half["exceptions_all"] >= 0 and half["invoice_timeliness"] == 1.0
    assert window(run, "2026-07-01", "2026-07-01").days == 1


def test_the_defaults_measure_like_the_summary(town, defaults):
    assert 0.9 < defaults["invoice_timeliness"] <= 1 and 0 < defaults["missed_read_share"] < 0.1
    assert defaults["exceptions_all"] > defaults["exceptions_worked"] > defaults["exceptions_vee"] >= 0
    assert defaults["days_to_release"] > 0 and defaults["billing_error_share"] >= 0


# ---- sizing -----------------------------------------------------------------------------------------------------------
def test_sizing_and_staffing_scale_with_the_utility():
    small = sizing(1_000, cal_homes=1900, cal_accounts=2375, home_limit=10_000)
    assert small["execution"] == "hosted" and small["homes"] == 800 and small["templateHomes"] == 800
    big = sizing(50_000, cal_homes=1900, cal_accounts=2375, home_limit=10_000)
    assert big["execution"] == "local" and big["homes"] == 40_000 and big["districts"] == 4
    assert big["templateHomes"] == DISTRICT_HOMES
    spec = TwinSpec(customers=50_000, billers=8, supervisors=2, agents=20, kpis=[{"id": "missed_read_share", "value": .05}])
    whole = staffing(spec, 1.0)
    assert whole["process"]["analysts"] == 8 and whole["process"]["analyst_hours_per_day"] == 6.0
    assert whole["process"]["supervisors"] == 2 and whole["contact"]["agents"] == 20
    district = staffing(spec, DISTRICT_HOMES / big["homes"])  # 8 billers over four processing areas: two each
    assert district["process"]["analysts"] == 2 and district["process"]["analyst_hours_per_day"] == pytest.approx(6)
    assert district["contact"]["agents"] == 5
    assert staffing(TwinSpec(customers=500, billers=0, kpis=[{"id": "missed_read_share", "value": .05}]), 1.0) == {
        "process": {"analysts": 0, "analyst_hours_per_day": 6.0}}
    assert staffing(TwinSpec(customers=500, kpis=[{"id": "missed_read_share", "value": .05}]), 1.0) == {}


def test_the_spec_refuses_what_the_engine_cannot_fit():
    kpi = {"id": "missed_read_share", "value": .05}
    for bad in ({"customers": 500, "kpis": [{"id": "nothing", "value": 1}]},
                {"customers": 500, "kpis": [{"id": "missed_read_share"}]},
                {"customers": 500, "kpis": [{"id": "missed_read_share", "value": .05, "after": .06}]},
                {"customers": 500, "kpis": [{"id": "missed_read_share", "value": 1.5}]},
                {"customers": 500, "kpis": [{"id": "invoice_timeliness", "value": .9, "absolute": True}]},
                {"customers": 500, "kpis": [{"id": "missed_read_share", "before": .03, "after": .06}]},  # no changedOn
                {"customers": 500, "changedOn": "2026-04-01", "kpis": [kpi]},  # nothing after
                {"customers": 500, "changedOn": "2027-04-01", "kpis": [{"id": "missed_read_share", "before": .03, "after": .06}]},
                {"customers": 500, "kpis": [kpi, kpi]},
                {"customers": 500, "kpis": [kpi], "fixed": {"plumbers": 1}},
                {"customers": 500, "kpis": [kpi], "fixed": {"automation": 2}},
                {"customers": 500, "kpis": [kpi], "townOverrides": {"process": {"analysts": 3}}},
                {"customers": 500, "kpis": [kpi], "services": ["gas", "gas"]}):
        with pytest.raises(ValueError):
            TwinSpec.model_validate(bad)


# ---- the fit ----------------------------------------------------------------------------------------------------------
def test_the_fit_reaches_a_steady_target_and_proposes_a_setup(town, defaults):
    target = round(defaults["missed_read_share"] * 2, 4)
    spec = TwinSpec(name="Twice the misses", customers=len(town.account_method), billers=2, calibration="village",
                    kpis=[{"id": "missed_read_share", "value": target}], budget=6)
    seen = []
    result = fit(spec, town=town, progress=seen.append)
    assert result["schemaVersion"] == "twin-fit/1.0" and 1 <= result["calibration"]["replays"] <= 6
    assert len(seen) == result["calibration"]["replays"] and seen[0]["label"] == "defaults"
    (row,) = result["kpis"]
    assert row["period"] == "year" and row["status"] == "fitted" and row["levers"] == ["missed_reads"]
    assert abs(row["achieved"] - target) <= row["tolerance"] and row["start"] == defaults["missed_read_share"]
    lever = next(x for x in result["levers"] if x["id"] == "missed_reads")
    assert 1.5 < lever["value"] < 3 and lever["settings"]["reading"]["ami_missed_read"] > 0.012
    assert next(x for x in result["levers"] if x["id"] == "analyst_hours")["state"] == "known"
    assert result["utility"]["execution"] == "hosted" and result["utility"]["homes"] == 120
    # The twin shows every KPI, fitted or not.
    assert set(result["twin"]["year"]) == set(KPI_BY_ID)
    p = result["proposal"]
    assert p["execution"] == "hosted" and p["totalHomes"] is None and p["episodes"] == []
    assert p["settings"]["process"]["analysts"] == 2 and p["townOverrides"]["town"]["houses"] == 120
    assert p["settings"]["reading"]["ami_missed_read"] == lever["settings"]["reading"]["ami_missed_read"]
    validated = validate_proposal(Proposal.model_validate(p))  # what the Studio's review and lock-in accept
    assert validated["homes"] == 120 and validated["townRef"].startswith("village")
    assert any(c["path"] == "reading.ami_missed_read" for c in validated["changes"])


def test_before_and_after_make_a_dated_episode(town, defaults):
    before, after = round(defaults["missed_read_share"], 4), round(defaults["missed_read_share"] * 2.5, 4)
    spec = TwinSpec(customers=50_000, billers=8, changedOn="2026-07-01", ramp=14, calibration="village",
                    kpis=[{"id": "missed_read_share", "before": before, "after": after}], budget=8)
    result = fit(spec, town=town)
    rows = {r["period"]: r for r in result["kpis"]}
    assert rows["before"]["status"] == "fitted" and rows["before"]["levers"] == []  # the defaults already fit
    assert rows["after"]["status"] in ("fitted", "close") and rows["after"]["levers"] == ["missed_reads"]
    assert rows["after"]["achieved"] > rows["before"]["achieved"]
    assert set(result["twin"]) == {"year", "before", "after"}
    assert result["twin"]["after"]["missed_read_share"] == rows["after"]["achieved"]
    assert result["twin"]["before"]["missed_read_share"] < result["twin"]["after"]["missed_read_share"]
    # Sizing: 50,000 accounts at the 120-home town's ratio is a utility of districts; billers share out by homes.
    u = result["utility"]
    assert u["execution"] == "local" and u["districts"] > 1 and u["templateHomes"] <= DISTRICT_HOMES
    assert u['templateHomes'] == (u['homes'] + u['districts'] - 1) // u['districts']
    assert u["calibrationStaffing"]["process"]["analysts"] == 1
    assert result["notes"] and "smallest capacity" in result["notes"][0]
    p = result["proposal"]
    assert p["execution"] == "local" and p["totalHomes"] == u["homes"] and p["townOverrides"]["town"]["houses"] == u['templateHomes']
    assert all(p['settings']['process'][key] == value
               for key, value in staffing(spec, u['templateHomes'] / u['homes'])['process'].items())
    (episode,) = p["episodes"]
    assert episode["from"] == "2026-07-01" and episode["ramp"] == 14 and set(episode["settings"]) == {"reading"}
    assert p["settings"]["reading"]["ami_missed_read"] == 0.012  # the base keeps the 'before' fit
    assert episode["settings"]["reading"]["ami_missed_read"] > 0.012
    validated = validate_proposal(Proposal.model_validate(p))
    assert validated["execution"] == "local" and validated["episodes"][0]["id"] == "EP-1"
    assert any(c["scope"] == "episode" and c["path"] == "reading.ami_missed_read" for c in validated["changes"])


def test_an_absolute_count_is_a_rate_per_thousand_accounts(town, defaults):
    accounts = len(town.account_method)
    customers = 20_000
    per_year = defaults["exceptions_worked"]  # per 1,000 accounts
    spec = TwinSpec(customers=customers, kpis=[{"id": "exceptions_worked", "value": per_year * customers / 1000,
                                                "absolute": True}], budget=2)
    (row,) = fit(spec, town=town)["kpis"]
    assert row["absolute"] and row["given"] == pytest.approx(per_year * customers / 1000)
    assert row["target"] == pytest.approx(per_year) and row["status"] == "fitted" and row["levers"] == []
    assert accounts == len(town.account_method)


def test_a_kpi_without_a_lever_is_reported_not_forced(town, defaults):
    spec = TwinSpec(customers=300, kpis=[{"id": "days_to_pay", "value": defaults["days_to_pay"] + 10}], budget=3)
    result = fit(spec, town=town)
    (row,) = result["kpis"]
    assert row["status"] == "unfitted" and "No run lever" in row["note"] and row["levers"] == []
    assert result["calibration"]["replays"] == 1  # nothing to try
    assert any("not fitted" in x for x in result["proposal"]["limitations"])


def test_fixed_and_excluded_levers_are_honoured(town, defaults):
    target = round(defaults["missed_read_share"] * 2, 4)
    spec = TwinSpec(customers=300, exclude=["missed_reads"], kpis=[{"id": "missed_read_share", "value": target}], budget=3)
    result = fit(spec, town=town)
    assert result["kpis"][0]["status"] == "unfitted" and result["kpis"][0]["levers"] == []
    assert next(x for x in result["levers"] if x["id"] == "missed_reads")["state"] == "excluded"
    spec = TwinSpec(customers=300, fixed={"automation": 0.0}, kpis=[{"id": "missed_read_share", "value": target}], budget=4)
    result = fit(spec, town=town)
    fixed = next(x for x in result["levers"] if x["id"] == "automation")
    assert fixed["state"] == "fixed" and fixed["value"] == 0.0 and result["proposal"]["settings"]["process"]["rpa_coverage"] == 0.0


def test_the_fit_is_deterministic(town, defaults):
    spec = TwinSpec(customers=400, billers=1, kpis=[{"id": "estimated_read_share", "value": round(defaults["estimated_read_share"] * 1.8, 4)}],
                    budget=4)
    a, b = fit(spec, town=town), fit(spec, town=town)
    strip = lambda r: {k: v for k, v in r.items() if k != "calibration"}  # noqa: E731 -- seconds differ
    assert strip(a) == strip(b) and a["calibration"]["replays"] == b["calibration"]["replays"]


# ---- over HTTP --------------------------------------------------------------------------------------------------------
def test_the_twin_over_the_api():
    with TestClient(app) as client:
        d = client.get("/api/twin/dictionary").json()
        assert {k["id"] for k in d["kpis"]} == set(KPI_BY_ID) and d["defaults"]["homeLimit"] > 0
        assert "village" in {c["preset"] for c in d["calibrations"]}
        r = client.post("/api/twin/fit", json={"customers": 300, "billers": 1, "calibration": "village", "budget": 1,
                                               "kpis": [{"id": "invoice_timeliness", "value": 0.99}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["calibration"]["replays"] == 1 and body["validated"]["townRef"].startswith("village")
        assert body["kpis"][0]["id"] == "invoice_timeliness" and body["proposal"]["preset"] == "village"
        bad = client.post("/api/twin/fit", json={"customers": 300, "kpis": [{"id": "nothing", "value": 1}]})
        assert bad.status_code == 422
        unknown = client.post("/api/twin/fit", json={"customers": 300, "calibration": "atlantis", "budget": 1,
                                                     "kpis": [{"id": "invoice_timeliness", "value": 0.99}]})
        assert unknown.status_code == 422
