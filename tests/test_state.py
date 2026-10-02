from datetime import UTC, datetime

import numpy as np
import pytest
from viewer_contract import ContractError, accept_replay, validate_frame

from utilsim.io.snapshot import build_snapshot
from utilsim.sim.astro import moon_phase, sun_position
from utilsim.sim.state import FrameBuilder, local_time


def test_sun_and_moon():
    elev, az = sun_position(datetime(2026, 6, 21, 17, 20, tzinfo=UTC), 43.65, -79.38)
    assert elev == pytest.approx(69.7, abs=0.5) and az == pytest.approx(180, abs=3)
    assert sun_position(datetime(2026, 12, 21, 4, 0, tzinfo=UTC), 43.65, -79.38)[0] < -30
    assert 0 <= moon_phase(datetime(2026, 7, 15, tzinfo=UTC)) < 0.1  # new moon on 14 July 2026


def test_frames_and_replay_pass_receiver_rules(town480):
    snap = build_snapshot(town480)
    validate_frame(snap, snap["stateFrame"])
    fb = FrameBuilder(town480)
    rp = fb.replay("2026-07-15", step_minutes=60)
    assert len(rp["frames"]) == 24
    accept_replay(snap, rp)
    noon = rp["frames"][12]
    assert noon["clock"]["isDay"] and not rp["frames"][2]["clock"]["isDay"]
    assert any(v is not None and v < 0 for v in noon["networks"]["electric"]["flows"])  # solar export somewhere
    water = noon["networks"]["water"]
    loops = {e["id"] for e in snap["networks"]["water"]["edges"] if e.get("loop") and e["enabled"]}
    assert all(v is None for i, v in zip(water["edgeIds"], water["flows"]) if i in loops)


def test_outage_disables_supply_and_zeroes_electric(town480):
    snap = build_snapshot(town480)
    f = FrameBuilder(town480).frame(local_time(town480, "2026-07-15", 19), scenario="substation_outage")
    validate_frame(snap, f)
    e = f["networks"]["electric"]
    supply = {x["id"] for x in snap["networks"]["electric"]["edges"] if x["kind"] == "supply"}
    assert all(not en for i, en in zip(e["edgeIds"], e["enabled"]) if i in supply)
    assert e["sourceFlow"] == 0 and all(v in (0, None) for v in e["flows"])


def test_leak_frame_and_gas_nulls(town480):
    snap = build_snapshot(town480)
    fb = FrameBuilder(town480)
    pid = town480.prem.ids[5]
    base = fb.frame(local_time(town480, "2026-07-15", 8))
    leak = fb.frame(local_time(town480, "2026-07-15", 8), scenario="leak", target=pid)
    validate_frame(snap, leak)
    assert leak["networks"]["water"]["sourceFlow"] - base["networks"]["water"]["sourceFlow"] == pytest.approx(0.65,
                                                                                                         abs=1e-3)
    no_gas = np.flatnonzero(~town480.prem.attrs["has_gas"])
    if len(no_gas):
        assert leak["premises"]["gas"][int(no_gas[0])] is None


def test_receiver_rejects_tampered_frames(town120):
    snap = build_snapshot(town120)
    f = snap["stateFrame"]
    for bad in ({**f, "topologyRevision": "topo-x"}, {**f, "townId": "town-x"}, {**f, "complete": False},
                {**f, "clock": {**f["clock"], "simTime": "2026-07-15T12:00:00+00:00"}}):
        with pytest.raises(ContractError):
            validate_frame(snap, bad)
    nets = dict(f["networks"])
    nets["water"] = {**nets["water"], "edgeIds": nets["water"]["edgeIds"][:-1], "flows": nets["water"]["flows"][:-1],
                     "enabled": nets["water"]["enabled"][:-1]}
    with pytest.raises(ContractError):
        validate_frame(snap, {**f, "networks": nets})


def test_sequence_is_minutes_since_local_midnight(town120):
    fb = FrameBuilder(town120)
    rep = fb.replay("2026-07-15", start_hour=6, hours=3, step_minutes=30, include_premises=False)
    assert [f["sequence"] for f in rep["frames"]] == [360, 390, 420, 450, 480, 510]
    one = fb.frame(local_time(town120, "2026-07-15", 7.5), include_premises=False)
    assert one["sequence"] == 450 and one["simulationId"] == rep["simulationId"]
    assert one == rep["frames"][3]
    # A replay past midnight keeps counting from the run day, so sequences stay increasing.
    late = fb.replay("2026-07-15", start_hour=23, hours=2, step_minutes=60, include_premises=False)
    assert [f["sequence"] for f in late["frames"]] == [1380, 1440]


def test_weather_year_drives_seasonal_demand(town120):
    from utilsim.sim.weather import daily_temps

    temps = daily_temps(town120.cfg)
    assert len(temps) == 396 and np.array_equal(temps, daily_temps(town120.cfg))
    fb = FrameBuilder(town120)
    jan = fb.frame(local_time(town120, "2026-01-15", 7.0))
    jul = fb.frame(local_time(town120, "2026-07-15", 7.0))
    assert jan["networks"]["gas"]["sourceFlow"] > 3 * jul["networks"]["gas"]["sourceFlow"]
    assert jan["clock"]["tempC"] < jul["clock"]["tempC"]


def test_closing_a_normally_open_tie_backfeeds_downstream_premises():
    from utilsim.sim.flows import FlowInputs, FlowModel, NetInputs

    # source 0 -> 1 -> 2 -> 3, and an open tie 0 - 3; meters at 2 (premise 0) and 3 (premise 1).
    net = NetInputs(n_nodes=4, a=np.array([0, 1, 2, 0]), b=np.array([1, 2, 3, 3]), loop=np.array([False] * 3 + [True]),
                    enabled=np.array([True, True, True, False]), meter=np.array([-1, -1, 0, 1]), sources=np.array([0]),
                    unit="kW")
    daily = {"dailyKWh": np.array([24.0, 24.0]), "dailyWaterM3": np.zeros(2), "dailyGasM3": np.zeros(2),
             "solarPeakKW": np.zeros(2)}
    fm = FlowModel(FlowInputs({"electric": net}, daily, np.array([True, True]), np.array([False, False]),
                              ["P-1", "P-2"], 0.0))
    fault = {"electric": np.array([False, True, False, False])}
    out = fm.flows(12.0, disabled=fault)
    assert out.unsupplied["electric"].tolist() == [True, True]
    tie = {"electric": np.array([False, False, False, True])}
    back = fm.flows(12.0, disabled=fault, closed=tie)
    assert back.unsupplied["electric"].tolist() == [False, False]
    flows = back.edge_flows["electric"]
    assert flows[1] == 0 and flows[3] != 0 and back.source["electric"] == out.source["electric"] + sum(back.homes["electric"])
    assert fm.flows(12.0).edge_flows["electric"][3] == 0  # the tie stays open as built
