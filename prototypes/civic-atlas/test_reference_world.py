"""Curated geography must remain a coherent physical-world input."""
import sys
from pathlib import Path

import pytest
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_world import build_reference_snapshot  # noqa: E402

from utilsim.world.map_view import WorldMap  # noqa: E402
from utilsim.world.store import World  # noqa: E402


def polygon(points):
    return Polygon([(p["x"], p["z"]) for p in points])


@pytest.fixture(scope="module")
def reference():
    return build_reference_snapshot()


def test_reference_land_use_and_crossing_are_consistent(reference):
    design = reference["atlasDesign"]
    river = polygon(design["river"]["polygon"])
    parks = [polygon(p["polygon"]) for p in reference["parks"]]
    assert river.is_valid and len(parks) >= 2 and all(p.is_valid for p in parks)
    exclusion = unary_union([river, *parks])
    assert reference["homes"] >= 100
    assert any(p["buildingType"] == "school" for p in reference["premises"])
    assert len(set(design["buildingFamilies"].values())) >= 4
    for building in reference["buildings"]:
        shape = polygon(building["footprint"]["polygon"])
        assert shape.is_valid
        assert shape.intersection(exclusion).area < .1, building["id"]
    bridges = {b["roadId"] for b in design["bridges"]}
    assert bridges
    for road in reference["roads"]:
        geometry = LineString([(p["x"], p["z"]) for p in road["points"]])
        if geometry.intersects(river):
            assert road["id"] in bridges
            assert road["bridge"] is True
    premise_ids = {p["id"] for p in reference["premises"]}
    assert set(design["buildingFamilies"]) == premise_ids
    for utility, network in reference["networks"].items():
        metered = {n.get("premiseId") for n in network["nodes"] if n["kind"] == "meter"}
        assert all(p["id"] in metered for p in reference["premises"] if p["services"].get(utility))


def test_reference_runs_real_days_and_reopens(tmp_path, reference):
    path = tmp_path / "reference.sqlite"
    world = World(path)
    world.initialize(reference, "REFERENCE", start="2026-01-01")
    world.advance("2026-01-03")
    assert world.status()["days"] == 2
    assert world.status()["observations"] > 0
    reopened = World(path)
    assert WorldMap(reopened).snapshot() == reference
    school = next(p for p in reference["premises"] if p["buildingType"] == "school")
    record = WorldMap(reopened).premise(school["id"])
    assert record["lastCompletedDay"] == "2026-01-02"
    assert any(asset["observed_quantity"] is not None for asset in record["assets"])
