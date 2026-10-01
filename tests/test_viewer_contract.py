import pytest
from viewer_contract import ContractError, inspect_snapshot

from utilsim.io.snapshot import build_snapshot


@pytest.mark.parametrize("detail", ["full", "viewer"])
def test_snapshots_pass_the_viewer_receiver_rules(town480, synth, detail):
    for t in (town480, synth):
        snap = build_snapshot(t, detail=detail)
        inspect_snapshot(snap)
        assert snap["count"] == len(snap["premises"]) and snap["homes"] == int(t.prem.residential.sum())


def test_revisions_identical_across_profiles_and_regeneration(town120):
    from utilsim.config import load_preset
    from utilsim.gen.pipeline import generate

    a = build_snapshot(town120)
    b = build_snapshot(town120, detail="viewer")
    c = build_snapshot(generate(load_preset("whitby_small", seed="T120", houses=120)))
    assert a["topologyRevision"] == b["topologyRevision"] == c["topologyRevision"]
    assert a["indexRevision"] == b["indexRevision"] == c["indexRevision"]
    d = build_snapshot(generate(load_preset("whitby_small", seed="T121", houses=120)))
    assert d["topologyRevision"] != a["topologyRevision"]


def test_heightmap_orientation_matches_terrain(town120):
    snap = build_snapshot(town120)
    t = snap["terrain"]
    for row, col in ((0, 0), (1, 3), (t["rows"] - 1, t["cols"] - 1)):
        x = t["originX"] + col * t["cellSizeM"]
        z = t["originZ"] + row * t["cellSizeM"]
        expect = float(town120.geo.terrain.elevation(x, -z))
        assert t["values"][row * t["cols"] + col] == pytest.approx(expect, abs=0.01)


def test_contract_checker_rejects_known_bad_shapes(town120):
    snap = build_snapshot(town120)
    bad = dict(snap, count=snap["count"] - 1)
    with pytest.raises(ContractError):
        inspect_snapshot(bad)
    bad = dict(snap, terrain={**snap["terrain"], "values": snap["terrain"]["values"][:-1]})
    with pytest.raises(ContractError):
        inspect_snapshot(bad)
    bad = {k: v for k, v in snap.items() if k != "topologyRevision"}
    with pytest.raises(ContractError):
        inspect_snapshot(bad)
