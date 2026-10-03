"""Episodes: scenarios inflicted from a day of the year. A run without episodes is byte-identical to the base run; an
episode changes nothing before its first day; the day's settings reach reading, VEE, staffing, anomalies, billing and
dunning; the library's scenarios all parse against the engine; the trend reports the year month by month."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import orjson
import pytest
from fastapi.testclient import TestClient

from api._m2c import RunRequest, _master, run_for
from api.index import app
from utilsim.m2c import scenarios as sc
from utilsim.m2c import tables, trend
from utilsim.m2c.run import M2CRun, parse_day, parse_episodes

DAY = "2026-03-01"
D0 = parse_day(DAY, 0)


@pytest.fixture(scope="module")
def base() -> M2CRun:
    return run_for(RunRequest(town="small_town"))


def ep(settings, frm=DAY, to=None, ramp=0, eid="EP-1"):
    return {"id": eid, "title": eid, "from": frm, "to": to, "ramp": ramp, "settings": settings}


def inflicted(scenario: str, day: str = DAY) -> list[dict]:
    """A library scenario's episodes, as the Year page builds them for an inflict day."""
    d0 = date.fromisoformat(day)
    out = []
    for i, e in enumerate(sc.BY_ID[scenario]["episodes"]):
        f = d0 + timedelta(days=e["startOffset"])
        t = None if e["durationDays"] is None else min(f + timedelta(days=e["durationDays"] - 1), date(2026, 12, 31))
        out.append({"id": f"EP-{i + 1}", "title": e["title"], "scenario": scenario, "from": f.isoformat(),
                    "to": t.isoformat() if t else None, "ramp": e["ramp"], "settings": e["settings"]})
    return out


def test_no_episodes_is_the_base_run(base):
    same = M2CRun(base.town, episodes=[])
    assert same.simulation_id == base.simulation_id and same.cfg_at(100) is same.cfg
    assert np.array_equal(same.obs, base.obs, equal_nan=True)
    assert np.array_equal(same.released, base.released, equal_nan=True)
    assert [c.id for c in same.cases] == [c.id for c in base.cases]
    assert np.array_equal(same.month_rate("anomalies", "slow_meter"), np.full(12, base.cfg.anomalies.slow_meter))


def test_an_episode_changes_nothing_before_its_day_and_the_settings_after(base):
    run = M2CRun(base.town, episodes=[ep({"process": {"analysts": 0}})])
    assert run.simulation_id != base.simulation_id
    assert run.cfg_at(D0 - 1).process.analysts == base.cfg.process.analysts and run.cfg_at(D0).process.analysts == 0
    assert [c.id for c in run.cases if c.created < D0] == [c.id for c in base.cases if c.created < D0]
    assert np.array_equal(run.obs[:, :3], base.obs[:, :3], equal_nan=True)  # Dec, Jan, Feb reads untouched
    # Nobody on the queues: the analyst queues pile up after March.
    peak = {q: int(run.series[q][D0:, 2].max()) for q in ("VEE_REVIEW", "ESTIMATION", "BILLING")}
    peak_base = {q: int(base.series[q][D0:, 2].max()) for q in ("VEE_REVIEW", "ESTIMATION", "BILLING")}
    assert all(peak[q] > 3 * peak_base[q] for q in peak), (peak, peak_base)
    assert sum(1 for c in run.cases if c.resolved is None) > sum(1 for c in base.cases if c.resolved is None)


def test_operators_ramps_and_windows(base):
    run = M2CRun(base.town, episodes=[ep({"anomalies": {"slow_meter": "*4"}, "process": {"analysts": "+1"}},
                                         frm="2026-02-01", to="2026-05-31", ramp=60)])
    s = [run.cfg_at(d).anomalies.slow_meter for d in range(0, 160)]
    d1 = parse_day("2026-02-01", 0)
    assert s[d1 - 1] == base.cfg.anomalies.slow_meter and s[d1] > s[d1 - 1]
    assert all(b >= a for a, b in zip(s[d1:d1 + 60], s[d1 + 1:d1 + 61]))  # the ramp never goes back
    assert s[d1 + 59] == pytest.approx(4 * base.cfg.anomalies.slow_meter)
    assert run.cfg_at(parse_day("2026-05-31", 0)).anomalies.slow_meter == pytest.approx(4 * base.cfg.anomalies.slow_meter)
    assert run.cfg_at(parse_day("2026-06-01", 0)).anomalies.slow_meter == base.cfg.anomalies.slow_meter  # window closed
    assert run.cfg_at(d1 + 59).process.analysts == base.cfg.process.analysts + 1  # an integer setting steps
    rates = run.month_rate("anomalies", "slow_meter")
    assert rates[0] == base.cfg.anomalies.slow_meter and rates[1] < rates[2] <= rates[4] and rates[6] == rates[0]
    # Later episodes see earlier ones; absolute values and booleans too.
    two = [ep({"process": {"analysts": "*2"}}, eid="A"),
           ep({"process": {"analysts": "+1"}, "vee": {"zero_at_occupied": False}}, eid="B")]
    assert [e["id"] for e in parse_episodes(base.cfg, two)] == ["A", "B"]
    run2 = M2CRun(base.town, episodes=two)
    assert run2.cfg_at(D0).process.analysts == base.cfg.process.analysts * 2 + 1
    assert run2.cfg_at(D0).vee.zero_at_occupied is False and run2.cfg_at(D0 - 1).vee.zero_at_occupied is True


def test_bad_episodes_are_refused(base):
    cfg = base.cfg
    for bad, msg in [([ep({"nope": {"x": 1}})], "unknown settings group"),
                     ([ep({"process": {"nope": 1}})], "unknown setting"),
                     ([ep({"process": {"analysts": "x2"}})], "not a number or an operator"),
                     ([ep({"vee": {"zero_at_occupied": "*2"}})], "not a number"),
                     ([ep({"process": {"analysts": 1}}, frm="2027-01-01")], "day of 2026"),
                     ([ep({"process": {"analysts": 1}}, frm="2026-05-01", to="2026-04-01")], "before"),
                     ([ep({})], "at least one"),
                     ([ep({"process": {"analysts": 1}}, eid=f"E{i}") for i in range(41)], "at most")]:
        with pytest.raises(ValueError, match=msg):
            parse_episodes(cfg, bad)
    with pytest.raises(ValueError, match="episode settings on"):  # out of the field's bounds: pydantic refuses
        M2CRun(base.town, episodes=[ep({"process": {"analysts": "*500"}})])


def test_the_days_settings_reach_reading_anomalies_and_dunning(base):
    tw = base.town
    # Locked gates for June: manual reads missed in June, May untouched.
    run = M2CRun(tw, episodes=[ep({"reading": {"manual_no_access": 0.8}}, frm="2026-06-01", to="2026-06-30")])
    manual = tw.tech == "MANUAL"
    june, may = 6, 5
    assert int(np.isnan(run.obs[manual, june]).sum()) > 3 * int(np.isnan(base.obs[manual, june]).sum())
    assert np.array_equal(run.obs[:, may], base.obs[:, may], equal_nan=True)
    # AMR fleet drift: more faults on AMR meters, none added on AMI.
    drift = M2CRun(tw, episodes=inflicted("amr_drift", "2026-02-01"))
    amr, ami = tw.meter_tech == "AMR", tw.meter_tech == "AMI"
    assert int(((drift.fault_type >= 0) & amr).sum()) > 2 * int(((base.fault_type >= 0) & amr).sum())
    assert int(((drift.fault_type >= 0) & ami).sum()) == int(((base.fault_type >= 0) & ami).sum())
    # A longer moratorium holds more notices.
    hold = M2CRun(tw, episodes=inflicted("long_moratorium", "2026-01-01"))
    holds = lambda r: sum(1 for i in r.books.invoices for _, k in i["dunning"] if k == "MORATORIUM_HOLD")  # noqa: E731
    assert holds(hold) > holds(base)
    # Returned debits: more rejected payments inside the window.
    pad = M2CRun(tw, episodes=inflicted("pad_failures", "2026-05-01"))
    rejected = lambda r: sum(1 for i in r.books.invoices for p in i["payments"] if p["status"] == "rejected")  # noqa: E731
    assert rejected(pad) > rejected(base)


def test_every_library_scenario_parses_and_moves_something(base):
    cat = sc.catalog()
    ids = [s["id"] for s in cat["scenarios"]]
    assert len(set(ids)) == len(ids) and {s["group"] for s in cat["scenarios"]} <= {g["id"] for g in cat["groups"]}
    for s in cat["scenarios"]:
        assert s["title"] and s["description"] and s["watch"] and s["episodes"], s["id"]
        parse_episodes(base.cfg, inflicted(s["id"]))  # every template is a valid episode on the base
    assert {c["id"] for c in cat["coming"]} == {"water_loss"}  # storm season is live (the year draws incidents)
    # The ones that must show on a small town do.
    for sid in ("no_analysts", "vee_tightened", "no_access_season", "data_quality_slip", "collections_lenient"):
        run = M2CRun(base.town, episodes=inflicted(sid))
        assert run.simulation_id != base.simulation_id
        assert (len(run.cases), [c.id for c in run.cases]) != (len(base.cases), [c.id for c in base.cases]) or \
            sum(len(i["dunning"]) for i in run.books.invoices) != sum(len(i["dunning"]) for i in base.books.invoices), sid


def test_trend_reports_the_year_month_by_month(base):
    t = trend.trend(base, "2026-07-15")
    assert t["schemaVersion"] == trend.TREND_VERSION and len(t["months"]) == 12 and t["episodes"] == []
    done = [m for m in t["months"] if m["reads"] is not None]
    assert [m["month"] for m in done] == list(range(1, 8)) and done[-1]["complete"] is False and done[-1]["end"] == \
        "2026-07-15" and all(m["complete"] for m in done[:-1])
    assert all(m["reads"] is None and m["cases"] is None and m["billing"] is None for m in t["months"][7:])
    day, T = tables.views.as_of_t(base, "2026-07-15")
    assert sum(m["cases"]["opened"] for m in done) == sum(1 for c in base.cases if c.created <= T)
    assert sum(m["reads"]["scheduled"] for m in done) == int((base.read_t[:, 1:] <= T).sum())
    june = done[5]
    assert june["reads"]["taken"] + june["reads"]["missed"] == june["reads"]["scheduled"]
    assert sum(june["cases"]["byQueue"].values()) == june["cases"]["backlog"]
    assert sum(june["collections"]["phases"].values()) == tables.page(base, _master("small_town"), "collectionsAccounts",
                                                                       as_of="2026-06-30", page_size=1)["total"]
    assert june["billing"]["invoices"] > 0 and june["billing"]["collected"] > 0 and june["cost"]["total"] > 0
    assert len(orjson.dumps(t)) < 200_000
    # With an episode the trend echoes it and the months after it differ.
    run = M2CRun(base.town, episodes=inflicted("no_analysts"))
    t2 = trend.trend(run, "2026-07-15")
    assert t2["episodes"][0]["scenario"] == "no_analysts" and t2["episodes"][0]["from"] == DAY
    assert t2["months"][1]["cases"] == t["months"][1]["cases"]  # February untouched
    assert t2["months"][3]["cases"]["backlog"] > t["months"][3]["cases"]["backlog"]  # April piles up


def test_endpoints_take_episodes():
    client = TestClient(app)
    cat = client.get("/api/m2c/scenarios")
    assert cat.status_code == 200 and cat.json()["schemaVersion"] == sc.SCENARIOS_VERSION
    body = {"town": "small_town", "asOf": "2026-07-15", "episodes": inflicted("no_analysts")}
    t = client.post("/api/m2c/trend", json=body)
    assert t.status_code == 200 and t.json()["episodes"][0]["id"] == "EP-1"
    s = client.post("/api/m2c/summary", json=body)
    assert s.status_code == 200
    tbl = client.post("/api/m2c/table", json={**body, "table": "cases", "pageSize": 1})
    assert tbl.status_code == 200 and tbl.json()["total"] > 0
    bad = client.post("/api/m2c/trend", json={"town": "small_town", "episodes": [ep({"process": {"nope": 1}})]})
    assert bad.status_code == 422 and "unknown setting" in str(bad.json()["detail"])
    # The operations day takes the run's episodes through its m2c context.
    tl = client.post("/api/sim/timeline", json={"town": "small_town", "date": "2026-07-15",
                                                "m2c": {"actions": [], "episodes": inflicted("no_analysts")}})
    assert tl.status_code == 200
