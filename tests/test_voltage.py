"""Radial power flow: conductor parsing, service design, voltages and loading on a real town, frames, and the
back-feed check that keeps a tie from overloading the feeder that picks up the load."""

from __future__ import annotations

import gzip
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import orjson
import pytest
from viewer_contract import validate_frame

from utilsim.net.tables import SECONDARY
from utilsim.ops.opstown import OpsTown
from utilsim.ops.timeline import Run
from utilsim.sim.voltage import BASE_V, RANGE_A, SOURCE_PU, conductor_of

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ayr_snapshot() -> dict:
    index = orjson.loads((ROOT / "packs" / "index.json").read_bytes())
    entry = next(t for t in index["towns"] if t["preset"] == "ayr")
    return orjson.loads(gzip.decompress((ROOT / "packs" / entry["files"]["snapshot"]["path"]).read_bytes()))


@pytest.fixture(scope="module")
def ayr(ayr_snapshot) -> OpsTown:
    return OpsTown(ayr_snapshot)


def test_conductor_labels_parse():
    c, n = conductor_of("2 × 350 kcmil AL URD")
    assert c.code == "URD_350" and n == 2
    assert conductor_of("795 kcmil ACSR (115 kV)")[0].code == "ACSR_795"
    assert conductor_of("1000 kcmil AL 15 kV XLPE (substation exit)")[0].code == "AL_1000"
    assert conductor_of("#2 ACSR") == (conductor_of("#2 ACSR")[0], 1) and conductor_of(None) == (None, 1)


def test_services_carry_their_design_current(ayr_snapshot):
    """Large three-phase customers take 347/600 V, and every service has enough parallel sets for its design load."""
    amp = {c.label: c.ampacity_a for c in SECONDARY}
    for e in ayr_snapshot["networks"]["electric"]["edges"]:
        if e["kind"] != "service":
            continue
        c, n = conductor_of(e["conductor"])
        kv = e["voltageKV"]
        current = e["designKVA"] / (math.sqrt(3) * kv if e["phases"] == 3 else kv)
        assert current <= n * amp[c.label] + 1e-6, e["id"]
        if e["phases"] == 3 and e["designKVA"] > 150:
            assert kv == 0.6, e["id"]


def test_summer_peak_voltages_loading_and_losses(ayr):
    res = ayr.flow_model.flows(17.0, month=7)
    v = res.voltage
    pv = v.premise_v[~np.isnan(v.premise_v)]
    assert len(pv) == len(ayr.premise_ids)
    assert RANGE_A[0] * BASE_V <= pv.min() and pv.max() <= SOURCE_PU * BASE_V + 1e-9  # no solar lift at 17:00
    net = ayr.nets["electric"]
    primary = np.array([k not in ("service", "transformer", "supply") for k in net.kind])
    assert np.nanmax(v.loading[primary]) <= 1.0
    assert 0.01 < v.losses_kw / res.source["electric"] < 0.06
    # Voltage falls along every energized edge that carries load away from the source.
    f = ayr.flow_model.forest("electric")
    kids = np.flatnonzero((f.pedge >= 0) & (f.parent >= 0))
    flow = res.edge_flows["electric"][f.pedge[kids]] * f.sign[kids]
    down = kids[flow > 1.0]
    assert (v.node_pu[down] <= v.node_pu[f.parent[down]] + 1e-12).all()


def test_rooftop_solar_lifts_voltage_at_noon(ayr):
    noon = ayr.flow_model.flows(13.0, month=7).voltage
    evening = ayr.flow_model.flows(19.0, month=7).voltage
    assert np.nanmax(noon.premise_v) > SOURCE_PU * BASE_V  # reverse flow raises the voltage past the bus
    assert np.nanmedian(noon.premise_v) > np.nanmedian(evening.premise_v)


def test_frames_carry_loading_losses_and_service_voltage(ayr, ayr_snapshot):
    when = datetime(2026, 1, 15, 18, 30, tzinfo=ZoneInfo(ayr.timezone))
    frame = ayr.frames.frame(when)
    validate_frame(ayr_snapshot, frame)
    el = frame["networks"]["electric"]
    assert len(el["loading"]) == len(el["edgeIds"]) and el["lossesKW"] > 0
    volts = [x for x in frame["premises"]["voltage"] if x is not None]
    assert len(volts) == len(ayr.premise_ids) and 100 < min(volts) < max(volts) <= 126
    # The town's service limits travel with the frame (electric.voltage_min_pu / max_pu on a 120 V base).
    lim = frame["premises"]["voltageLimits"]
    e = ayr.sim_config.electric
    assert (lim["min"], lim["max"]) == (e.voltage_min_pu * BASE_V, e.voltage_max_pu * BASE_V) == (114.0, 126.0)
    assert lim["low"] == sum(v < lim["min"] for v in volts) and lim["high"] == sum(v > lim["max"] for v in volts)


def test_backfeed_is_declined_when_the_receiving_feeder_would_overload(ayr):
    from test_ops import break_pole

    net = ayr.nets["electric"]
    edges = ayr.flow_inputs.nets["electric"]
    tl = None
    for q in net.equipment:  # a trunk pole whose isolated fault leaves customers for a tie to pick up
        if q["kind"] != "pole" or q.get("edgeId") not in net.edge_index:
            continue
        k = net.edge_index[q["edgeId"]]
        if edges.loop[k]:
            continue
        tl = Run(ayr, [break_pole(q, 8 * 3600)], settings={"randomIncidents": False}).timeline()
        if tl["incidents"] and tl["incidents"][0].get("tie"):
            break
    inc = tl["incidents"][0]
    assert inc["tie"]["maxLoading"] <= 1.3 and inc["tie"]["minVoltage"] >= 110
    strict = Run(ayr, [break_pole(q, 8 * 3600)], settings={"tieMaxLoading": 0.01, "randomIncidents": False}).timeline()
    inc2 = strict["incidents"][0]
    assert "tie" not in inc2 and inc2["tiesDeclined"][0]["maxLoading"] > 0.01
    assert any(e["eventType"] == "backfeed.declined" for e in strict["events"])
    assert "afterBackfeed" not in inc2["unsupplied"]
