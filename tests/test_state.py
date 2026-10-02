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
