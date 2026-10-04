"""Events upstream of a town (utilsim/m2c/upstream.py): the supply lost in the utility's wider networks reaches the
town as an outage shaped by its own networks (tanks, line pack, relighting), without a repair order of its own; a
shared storm seed gives towns of one utility the same storm days."""

from __future__ import annotations

import numpy as np
import pytest

from api._m2c import _ops_town, load_snapshot
from utilsim.m2c import contact, daily
from utilsim.m2c import fieldwork as fwk
from utilsim.m2c import upstream as up
from utilsim.m2c.base import M2CTown
from utilsim.m2c.calendar import calendar
from utilsim.m2c.run import M2CRun

TOWN = "small_town"
H = 3600
EVENTS = {"events": [{"id": "UP-E", "utility": "electric", "day": "2026-03-10", "start": 10 * H, "end": 12 * H},
                     {"id": "UP-W1", "utility": "water", "day": "2026-04-14", "start": 1 * H, "end": 7 * H},
                     {"id": "UP-W2", "utility": "water", "day": "2026-05-12", "start": 1 * H, "end": 21 * H},
                     {"id": "UP-G", "utility": "gas", "day": "2026-06-09", "start": 8 * H, "end": 13 * H}]}


@pytest.fixture(scope="module")
def town():
    return M2CTown.from_snapshot(load_snapshot(TOWN))


def _run(town, **kw):
    return M2CRun(town, ops_factory=lambda: _ops_town(TOWN), **kw)


@pytest.fixture(scope="module")
def runs(town):
    return _run(town), _run(town, upstream=EVENTS)


def _ups(run):
    return {x["id"]: x for x in run.field.incidents if x.get("upstream")}


def test_the_supply_lost_upstream_is_an_outage_here(runs):
    base, run = runs
    ups = _ups(run)
    tw = run.town
    e = ups["UP-E"]
    on_electric = {int(tw.prem[r]) for r in range(tw.n_registers) if tw.commodity[r] == "electric"}
    assert set(e["premises"].tolist()) == on_electric  # one supply point: the whole town
    assert e["t"] == pytest.approx(68 + 10 / 24) and np.allclose(e["restoredAt"], 68 + 12 / 24)
    d = daily.daily(run)
    assert d["outages"]["electric"]["customers"][68] == len(on_electric)
    assert d["outages"]["electric"]["customerHours"][68] == pytest.approx(2.0 * len(on_electric), rel=1e-6)
    # The town's own background incidents still happen; the upstream repair is not the town's.
    own = [x["id"] for x in run.field.incidents if not x.get("upstream")]
    assert own == [x["id"] for x in base.field.incidents]
    assert not any(o.cause in ups for o in fwk.fieldwork(run).orders)
    cx, cx0 = contact.contacts(run), contact.contacts(base)
    outage = contact.KEYS.index("outage")
    calls = [t for t, why, trig, n in zip(cx.t.tolist(), cx.reason.tolist(), cx.trigger, cx.attempt.tolist())
             if why == outage and trig == "UP-E" and n == 1]
    assert calls and min(calls) >= 68 + 10 / 24  # customers call once the power is off,
    assert np.median(calls) <= 68 + 12 / 24  # most of them while it is
    assert (cx.reason == outage).sum() > (cx0.reason == outage).sum()


def test_the_towns_networks_shape_it(runs):
    _, run = runs
    ups = _ups(run)
    assert not len(ups["UP-W1"]["premises"])  # the tank carried the town through six hours
    w = ups["UP-W2"]
    tanks = run.field.ops.nets["water"].node_kind.count("elevated_tank")
    assert tanks == 1 and w["t"] == pytest.approx(131 + (1 + up.TANK_HOURS) / 24)  # dry once the tank is empty
    assert np.allclose(w["restoredAt"], 131 + 21 / 24)
    g = ups["UP-G"]
    assert g["t"] == pytest.approx(159 + (8 + up.LINE_PACK_HOURS) / 24)
    back = np.sort(g["restoredAt"])
    assert back[0] == pytest.approx(159 + 13 / 24 + 1 / up.RELIGHT_PER_HOUR / 24)  # relit one by one after
    assert back[-1] == pytest.approx(159 + 13 / 24 + len(back) / up.RELIGHT_PER_HOUR / 24)


def test_one_storm_seed_shares_the_weather(town):
    a = _run(town, seed="A", upstream={"stormSeed": "UTILITY"})
    b = _run(town, seed="B", upstream={"stormSeed": "UTILITY"})
    c = _run(town, seed="A")
    assert np.array_equal(a.field.storm, b.field.storm) and a.field.storm.any()
    assert not np.array_equal(a.field.storm, c.field.storm)
    faults = [[x["id"] for x in r.field.incidents if x["kind"] == "line_fault"] for r in (a, b)]
    assert faults[0] != faults[1]  # the same storms, each town its own faults
    assert a.simulation_id != c.simulation_id


def test_no_upstream_is_the_run_as_ever(town, runs):
    base, _ = runs
    assert _run(town, upstream=None).simulation_id == base.simulation_id


@pytest.mark.parametrize(("upstream", "message"), [
    ({"events": [{"utility": "steam", "day": "2026-01-05", "start": 0, "end": 60}]}, "utility one of"),
    ({"events": [{"utility": "gas", "day": "2027-01-05", "start": 0, "end": 60}]}, "not a date in 2026"),
    ({"events": [{"utility": "gas", "day": "2026-01-05", "start": 100, "end": 50}]}, "end after it"),
    ({"events": [{"id": "X", "utility": "gas", "day": "2026-01-05", "start": 0, "end": 60},
                 {"id": "X", "utility": "gas", "day": "2026-01-06", "start": 0, "end": 60}]}, "repeated"),
    ({"stormSeed": ""}, "stormSeed"),
    ({"events": [], "where": 1}, "upstream"),
])
def test_a_bad_input_is_refused(upstream, message):
    with pytest.raises(ValueError, match=message):
        up.parse(upstream, calendar(2026))


def test_events_need_the_towns_networks(town):
    with pytest.raises(ValueError, match="networks"):
        M2CRun(town, upstream=EVENTS)


def test_upstream_over_the_api(runs):
    from fastapi.testclient import TestClient

    from api.index import app

    base, run = runs
    client = TestClient(app)
    d = client.post("/api/m2c/daily", json={"town": TOWN, "upstream": EVENTS}).json()
    assert d["simulationId"] == run.simulation_id != base.simulation_id
    assert d["outages"]["electric"]["customers"][68] > 0
    bad = client.post("/api/m2c/summary", json={"town": TOWN, "upstream": {"events": [{"utility": "steam"}]}})
    assert bad.status_code == 422 and "upstream" in bad.text
