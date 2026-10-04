"""Day-by-day staffing (utilsim/m2c/staffing.py) and the run day by day (utilsim/m2c/daily.py): a schedule of
headcounts overrides the settings' team sizes from its dates, every part of the replay sees it, and the work logs
show the work waiting and done."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api._m2c import _ops_town, load_snapshot
from api.app import app
from utilsim.m2c import contact, daily, staffing
from utilsim.m2c import fieldwork as fwk
from utilsim.m2c.base import M2CTown
from utilsim.m2c.calendar import calendar
from utilsim.m2c.run import M2CRun

TOWN = "small_town"


@pytest.fixture(scope="module")
def town():
    return M2CTown.from_snapshot(load_snapshot(TOWN))


@pytest.fixture(scope="module")
def base(town):
    return M2CRun(town, ops_factory=lambda: _ops_town(TOWN))


def _run(town, schedule):
    return M2CRun(town, ops_factory=lambda: _ops_town(TOWN), staffing=schedule)


def test_a_schedule_of_the_settings_is_the_same_run(town, base):
    crews = fwk.fieldwork(base).crews
    same = {"pools": {"analysts": [["2026-01-01", base.cfg.process.analysts]],
                      "agents": [["2026-01-01", base.cfg.contact.agents]],
                      "crew_meter": [["2026-01-01", float(crews["meter"]["crews"][0])]]}}
    run = _run(town, same)
    assert run.simulation_id != base.simulation_id  # the schedule is part of the run
    assert [(i["id"], i["total"], i["out"]) for i in run.books.invoices] == \
        [(i["id"], i["total"], i["out"]) for i in base.books.invoices]
    assert [(c.id, c.resolved) for c in run.cases] == [(c.id, c.resolved) for c in base.cases]
    for q in base.series:
        assert np.array_equal(run.series[q], base.series[q])
    assert np.array_equal(fwk.fieldwork(run).crews["meter"]["busyMin"], crews["meter"]["busyMin"])


def test_fewer_analysts_leave_work_waiting(town, base):
    n = base.cfg.process.analysts
    run = _run(town, {"pools": {"analysts": [["2026-03-02", 0], ["2026-03-30", n]]}})
    cal = run.cal
    a, b = cal.day_of(calendar(2026).date_of(60)), cal.day_of(calendar(2026).date_of(88))
    assert [run.cfg_at(d).process.analysts for d in (a - 1, a, b - 1, b)] == [n, 0, 0, n]
    log, log0 = run.work_log["analysts"], base.work_log["analysts"]
    assert log[a:b, 2].sum() == 0 and log[a:b, 1].sum() == 0  # nobody worked a case
    assert log[a:b, 3].max() > log0[a:b, 3].max()  # cases waited for the analysts
    assert log[a:b, 4].max() > log0[a:b, 4].max()  # and grew older
    backlog = sum(run.series[q][a:b, 2].sum() for q in ("VEE_REVIEW", "ESTIMATION", "BILLING"))
    backlog0 = sum(base.series[q][a:b, 2].sum() for q in ("VEE_REVIEW", "ESTIMATION", "BILLING"))
    assert backlog > backlog0
    assert log[b:b + 30, 2].sum() > log0[b:b + 30, 2].sum()  # they catch up when they are back
    assert np.allclose(log[:a], log0[:a])  # nothing changes before the schedule's date


def test_crews_and_agents_follow_the_schedule(town, base):
    run = _run(town, {"pools": {"crew_meter": [["2026-06-01", 0.5], ["2026-07-02", 2]],
                                "agents": [["2026-02-02", 3]]}})
    cal = run.cal
    meter = fwk.fieldwork(run).crews["meter"]["crews"]
    assert meter[cal.day_of(calendar(2026).date_of(151))] == 0.5 and meter[cal.days - 1] == 2.0
    assert meter[0] == fwk.fieldwork(base).crews["meter"]["crews"][0]
    agents = contact.contacts(run).daily["agents"]
    assert agents[32] == 3 and agents[31] == base.cfg.contact.agents


@pytest.mark.parametrize(("schedule", "message"), [
    ({"pools": {"plumbers": [["2026-01-01", 1]]}}, "unknown pool"),
    ({"pools": {"analysts": [["2026-03-01", 2], ["2026-02-01", 3]]}}, "increase"),
    ({"pools": {"analysts": [["2027-01-04", 2]]}}, "not a date in 2026"),
    ({"pools": {"analysts": [["2026-01-01", -1]]}}, "at least 0"),
    ({"pools": {"analysts": [["2026-01-01", 1.5]]}}, "whole number"),
    ({"pools": {"analysts": [["2026-01-01", 500]]}}, "staffing settings on 2026-01-01"),
    ({"pools": {"crew_meter": [["2026-01-01", 1000]]}}, "staffing settings on 2026-01-01"),
    ({"pools": {}}, "at least one pool"),
])
def test_a_bad_schedule_is_refused(town, schedule, message):
    with pytest.raises(ValueError, match=message):
        _run(town, schedule)


def test_a_schedule_round_trips():
    cal = calendar(2026)
    s = {"pools": {"analysts": [["2026-01-05", 3], ["2026-02-02", 1]], "crew_gas": [["2026-03-02", 0.25]]}}
    assert staffing.as_json(staffing.parse(s, cal), cal) == {"schemaVersion": staffing.SCHEDULE_VERSION, **s}


def test_the_day_by_day_view_adds_up(base):
    d = daily.daily(base)
    assert d["schemaVersion"] == "run-daily/1.0" and d["days"] == 365 and d["start"] == "2026-01-01"
    for q, s in d["queues"].items():
        assert s["opened"] == base.series[q][:, 0].tolist()
    cx = contact.contacts(base)
    assert sum(d["contact"]["contacts"]) == len(cx.t)
    assert sum(d["staff"]["analysts"]["done"]) == sum(1 for c in base.cases for e in c.events
                                                       if e[1] == "ANALYST_REVIEW")
    assert len(d["crews"]["meter"]["waitingMin"]) == 365
    assert sum(d["outages"].get("electric", {}).get("customers", [0])) >= 0


def test_staffing_over_the_api(base):
    client = TestClient(app)
    plain = client.post("/api/m2c/summary", json={"town": TOWN}).json()
    assert plain["simulationId"] == base.simulation_id  # no schedule: the run as ever
    sched = {"pools": {"analysts": [["2026-03-02", 0], ["2026-03-30", base.cfg.process.analysts]]}}
    s = client.post("/api/m2c/summary", json={"town": TOWN, "staffing": sched}).json()
    assert s["simulationId"] != plain["simulationId"]
    d = client.post("/api/m2c/daily", json={"town": TOWN, "staffing": sched}).json()
    assert d["staff"]["analysts"]["people"][60] == 0 and d["staff"]["analysts"]["people"][59] > 0
    bad = client.post("/api/m2c/summary", json={"town": TOWN, "staffing": {"pools": {"analysts": [["x", 1]]}}})
    assert bad.status_code == 422 and "staffing" in bad.text
