"""A utility above its towns: the upstream networks over the districts and their events (utilsim/utility/network.py),
and one workforce allocated day by day across the districts (utilsim/utility/coordinator.py)."""

from __future__ import annotations

import numpy as np
import pytest

from utilsim.m2c import staffing as staff_mod
from utilsim.m2c import upstream as up
from utilsim.m2c.calendar import calendar
from utilsim.utility import coordinator as co
from utilsim.utility import network as nw

CAL = calendar(2026)
D = CAL.days
WORK = [CAL.add_bdays(d, 0) == d for d in range(D)]


def _daily(analysts: int, arrivals_min, crew: float = 0.5) -> dict:
    """A district's measured year with analyst work arriving ``arrivals_min`` minutes each working day (worked by
    its own team at 360 minutes a person-day), steady crews and contact load."""
    arr = np.zeros(D)
    for d in range(D):
        if WORK[d]:
            arr[d] = arrivals_min(d)
    offered, done, left = np.zeros(D), np.zeros(D), 0.0
    for d in range(D):
        if WORK[d]:
            offered[d] = left + arr[d]
            done[d] = min(offered[d], analysts * 360.0)
            left = offered[d] - done[d]
    zeros = [0.0] * D
    crews = {c: {"crews": [crew] * D, "availableMin": [crew * 480.0 if WORK[d] else 0.0 for d in range(D)],
                 "busyMin": zeros, "overtimeMin": zeros, "waitingMin": zeros, "oldestDays": zeros}
             for c in (*co.CREWS, "emergency")}
    people = {"people": [analysts] * D, "workday": WORK, "offeredMin": offered.tolist(), "doneMin": done.tolist()}
    return {"year": 2026, "staff": {"analysts": people,
                                    "supervisors": {**people, "people": [1] * D, "offeredMin": zeros,
                                                    "doneMin": zeros}},
            "crews": crews, "contact": {"agents": [1] * D, "availableS": [8 * 3600.0] * D, "busyS": [3600.0] * D}}


def _three(spike_day: int | None = None):
    """Three districts with two analysts each; the second gets a week of heavy work from ``spike_day``."""
    def quiet(d: int) -> float:
        return 300.0

    def spiky(d: int) -> float:
        return 3000.0 if spike_day is not None and spike_day <= d < spike_day + 7 else 300.0

    return [{"id": "d1", "premises": 1000, "daily": _daily(2, quiet)},
            {"id": "d2", "premises": 1000, "daily": _daily(2, spiky)},
            {"id": "d3", "premises": 1000, "daily": _daily(2, quiet)}]


def test_no_float_team_is_every_district_on_its_own():
    p = co.plan(_three(60), float_share=0.0)
    for d in ("d1", "d2", "d3"):
        assert p["schedules"][d]["pools"]["analysts"] == [["2026-01-01", 2]]
    assert p["pools"]["analysts"]["float"] == 0


def test_the_float_team_goes_where_the_work_waits():
    districts = _three(60)
    shared = co.plan(districts, float_share=0.5)
    alone = co.plan(districts, float_share=0.0)
    s = np.array(shared["staff"]["analysts"])
    assert set(s.sum(0).tolist()) == {6.0}  # the pool every day, no more, no less
    assert (s >= 1).all()  # every district keeps a home team
    spike = [d for d in range(60, 67) if WORK[d]]
    assert all(s[1, d] > s[0, d] for d in spike)  # the busy district gets the float team
    w_shared, w_alone = np.array(shared["predictedWaiting"]["analysts"]), np.array(alone["predictedWaiting"]["analysts"])
    assert w_shared.max() < w_alone.max()  # the utility's worst backlog is smaller
    assert w_shared.sum() < w_alone.sum()


def test_the_schedules_are_valid_run_inputs_and_deterministic():
    districts = _three(100)
    p = co.plan(districts, float_share=0.4)
    assert p == co.plan(districts, float_share=0.4)
    for d in ("d1", "d2", "d3"):
        parsed = staff_mod.parse(p["schedules"][d], CAL)
        assert set(parsed) == set(co.POOLS)
        assert np.allclose(parsed["analysts"], np.array(p["staff"]["analysts"])[["d1", "d2", "d3"].index(d)])
    crews = np.array(p["staff"]["crew_meter"])
    assert np.allclose(crews.sum(0), 1.5, atol=1e-3) and (crews >= 0).all()  # the crews every day


def test_a_small_crew_pool_keeps_its_crews():
    tiny = [{"id": f"d{i}", "premises": 30, "daily": _daily(1, lambda d: 100.0, crew=0.026)} for i in range(3)]
    crews = np.array(co.plan(tiny, float_share=0.5)["staff"]["crew_meter"])
    assert np.allclose(crews.sum(0), 0.078, atol=1e-3) and (crews.sum(1) > 0).all()


def test_a_bad_plan_is_refused():
    with pytest.raises(ValueError, match="float_share"):
        co.plan(_three(), float_share=1.5)
    with pytest.raises(ValueError, match="at least one district"):
        co.plan([])


def test_the_upstream_layout_feeds_neighbours():
    names = [f"district-{i:04d}" for i in range(1, 11)]
    lay = nw.layout(names, per_circuit=4, per_main=3, per_gate=6)
    by = {a["id"]: a for a in lay["assets"]}
    assert by["T1"]["districts"] == names[:4] and by["T3"]["districts"] == names[8:]
    assert by["P1"]["districts"] == names and by["M4"]["districts"] == names[9:]
    assert by["G2"]["districts"] == names[6:]
    for name in names:  # every district on one circuit, one main, one gate and the plant
        fed = [a["kind"] for a in lay["assets"] if name in a["districts"]]
        assert sorted(fed) == ["circuit", "gate", "main", "plant"]


def test_upstream_events_reach_the_districts_they_feed():
    names = [f"district-{i:04d}" for i in range(1, 9)]
    lay = nw.layout(names)
    ev = nw.events(lay, "UTILITY", CAL, rate_factor=10.0)
    assert ev == nw.events(lay, "UTILITY", CAL, rate_factor=10.0)  # deterministic
    assert ev != nw.events(lay, "OTHER", CAL, rate_factor=10.0)
    by = {a["id"]: set(a["districts"]) for a in lay["assets"]}
    seen = {}
    for name, evs in ev.items():
        for e in evs:
            asset = e["id"].split("-")[1]
            assert name in by[asset]
            seen.setdefault(e["id"], set()).add(name)
    assert seen and all(names == by[e.split("-")[1]] for e, names in seen.items())  # every district it feeds
    inputs = nw.upstream_inputs(lay, "UTILITY", CAL, rate_factor=10.0)
    for name in names:
        parsed = up.parse(inputs[name], CAL)  # valid upstream inputs
        assert parsed["stormSeed"] == "UTILITY:storms" and len(parsed["events"]) == len(ev[name])


def test_event_counts_follow_the_rates():
    names = [f"district-{i:04d}" for i in range(1, 5)]
    lay = nw.layout(names, per_circuit=1)  # four circuits
    n = sum(1 for seed in range(40) for e in nw.events(lay, f"S{seed}", CAL)["district-0001"] if "-T1-" in e["id"])
    rate = nw.ASSETS["circuit"][1]
    assert abs(n / 40 - rate) < 3 * np.sqrt(rate / 40) + 0.05  # one circuit's events a year
