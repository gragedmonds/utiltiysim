"""Acceptance checks for the authored 500-home layout and real daily world."""
import sys
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import prepare_world  # noqa: E402
from town500_world import build_town500_snapshot  # noqa: E402

from utilsim.world.map_view import WorldMap  # noqa: E402
from utilsim.world.store import World  # noqa: E402


def polygon(points):
    return Polygon([(p["x"], p["z"]) for p in points])


@pytest.fixture(scope="module")
def town():
    return build_town500_snapshot()


def test_exact_home_count_and_connected_accessible_streets(town):
    homes = [p for p in town["premises"] if p["premiseType"] == "residential"]
    assert town["homes"] == len(homes) == 500
    assert len(town["premises"]) > 500
    assert 1000 < sum(p["occupants"] for p in homes if p["occupied"]) < 1600
    for collection in ("premises", "meters", "buildings", "parcels"):
        assert len({p["id"] for p in town[collection]}) == len(town[collection])
    roads = {r["id"]: r for r in town["roads"]}
    adjacent = {}
    for road in roads.values():
        adjacent.setdefault(road["a"], set()).add(road["b"])
        adjacent.setdefault(road["b"], set()).add(road["a"])
    reached, pending = set(), [next(iter(adjacent))]
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(adjacent[node] - reached)
    assert reached == set(adjacent)
    assert sum(len(neighbors) == 1 for neighbors in adjacent.values()) >= 4
    for home in town["premises"]:
        road = roads[home["roadId"]]
        assert LineString([(p["x"], p["z"]) for p in road["points"]]).distance(Point(home["front"]["x"], home["front"]["z"])) < .02


def test_sites_are_disjoint_and_industry_has_edge_access(town):
    parcels = [polygon(p["polygon"]) for p in town["parcels"]]
    tree = STRtree(parcels)
    for i, parcel in enumerate(parcels):
        assert parcel.is_valid
        for j in tree.query(parcel, predicate="intersects"):
            if j > i:
                assert parcel.intersection(parcels[j]).area < .02
    by_premise = {p["premiseId"]: polygon(p["polygon"]) for p in town["parcels"]}
    for b in town["buildings"]:
        shape = polygon(b["footprint"]["polygon"])
        assert shape.is_valid
        for identity in b["premiseIds"]:
            assert by_premise[identity].buffer(.02).covers(shape)
    pavement = unary_union([LineString([(p["x"], p["z"]) for p in r["points"]]).buffer(r["pavementWidthM"]/2, cap_style=2)
                            for r in town["roads"]])
    assert all(p.intersection(pavement).area < .02 for p in parcels)
    home_shapes = [by_premise[p["id"]] for p in town["premises"] if p["premiseType"] == "residential"]
    roads = {r["id"]: r for r in town["roads"]}
    industry = [p for p in town["premises"] if p["buildingType"] in ("industrial", "depot")]
    assert len(industry) == 2
    for p in industry:
        assert roads[p["roadId"]]["name"] == "East Service Road"
        assert roads[p["roadId"]]["roadClass"] == "arterial"
        assert min(by_premise[p["id"]].distance(h) for h in home_shapes) > 20
    shops = [p for p in town["premises"] if p["buildingType"] == "storefront"]
    assert len(shops) == 20
    assert all(roads[p["roadId"]]["name"] == "Main Street" for p in shops)
    assert {p["buildingType"] for p in town["premises"]} >= {"school", "church"}
    for p in town["premises"]:
        if p["buildingType"] in ("school", "church"):
            assert min(by_premise[p["id"]].distance(h) for h in home_shapes) < 100


def test_repeat_templates_preserve_physical_and_demand_attributes(town):
    design = town["atlasDesign"]
    by_id = {p["id"]: p for p in town["premises"]}
    blocks = [b for b in design["blocks"] if b["kind"] == "residential"]
    assert len(blocks) == 50
    assert len({identity for b in blocks for identity in b["premiseIds"]}) == 500
    appearances = {}
    for block in blocks:
        assert len(block["premiseIds"]) == 10
        source = design["blockTemplates"][block["templateId"]]
        result = []
        for slot, identity in enumerate(block["premiseIds"]):
            p = by_id[identity]
            contract = source["slots"][slot]
            fields = ("width", "depth", "height", "stories", "roof", "solar", "solarKW", "hasPool", "roofTone", "angle", "side")
            assert all(p[k] == contract[k] for k in fields)
            result.append(tuple(p[k] for k in (*fields, "solarPeakKW")) +
                          (round(p["x"]-block["center"]["x"], 4), round(p["z"]-block["center"]["z"], 4)))
            assert p["elevationM"] == 90
            assert (p["solarKW"] > 0) == p["solar"]
            assert (p["solarPeakKW"] > 0) == p["solar"]
            if p["hasPool"]:
                pool = polygon([{ "x": q["x"]+block["center"]["x"], "z": q["z"]+block["center"]["z"]} for q in contract["poolPolygon"]])
                lot = next(q for q in town["parcels"] if q["premiseId"] == identity)
                building = next(q for q in town["buildings"] if identity in q["premiseIds"])
                assert polygon(lot["polygon"]).covers(pool.buffer(1))
                assert not polygon(building["footprint"]["polygon"]).intersects(pool)
        key = block["templateId"]
        if key in appearances:
            assert result == appearances[key]
        appearances[key] = result
    assert len(appearances) == 4
    # Whole-block templates may not erase a unique park or utility site.
    for key in {b["templateId"] for b in design["blocks"]}:
        repeated = [b for b in design["blocks"] if b["templateId"] == key]
        assert len({(bool(b.get("parkIds")), bool(b.get("facilityIds"))) for b in repeated}) == 1


def test_fields_parks_and_commons_are_real_space_not_extra_customers(town):
    design = town["atlasDesign"]
    lots = unary_union([polygon(p["polygon"]) for p in town["parcels"]])
    assert len(design["fields"]) == 7 and len(design["commons"]) == 50 and len(town["parks"]) == 4
    for field in design["fields"]:
        assert field["descriptiveOnly"] is True
        shape = polygon(field["polygon"])
        assert shape.is_valid and shape.area > 10000
        assert not shape.intersects(lots)
    for common in design["commons"]:
        assert common["descriptiveOnly"] is True
        assert polygon(common["polygon"]).intersection(lots).area < .02
    for park in town["parks"]:
        assert polygon(park["polygon"]).intersection(lots).area < .02


def test_fresh_world_runs_real_days_and_resumes_existing_store(tmp_path, town):
    path = tmp_path / "fairhaven" / "world.sqlite"
    path.parent.mkdir()
    world = World(path)
    world.initialize(town, "Fairhaven", start="2026-01-01")
    world.advance("2026-01-03")
    assert world.status()["days"] == 2 and world.status()["observations"] > 1000
    reopened = World(path)
    assert WorldMap(reopened).snapshot() == town
    for kind in ("detached", "storefront", "school", "church", "industrial", "depot"):
        home = next(p for p in town["premises"] if p["buildingType"] == kind)
        record = WorldMap(reopened).premise(home["id"])
        assert record["lastCompletedDay"] == "2026-01-02"
        assert any(asset["observed_quantity"] is not None for asset in record["assets"])
    same = prepare_world(path.parent, 500, "different-seed-does-not-regenerate", town500=True)
    assert same.status() == reopened.status()
    assert WorldMap(same).snapshot() == town


def test_profile_refuses_to_replace_a_different_existing_world(tmp_path, town):
    import copy

    other = copy.deepcopy(town)
    other["atlasDesign"]["version"] = "another-curated-profile"
    path = tmp_path / "world.sqlite"
    existing = World(path)
    existing.initialize(other, "Existing world", start="2026-01-01")
    before = existing.status()
    with pytest.raises(ValueError, match="needs its own store"):
        prepare_world(tmp_path, 500, "unrelated-seed", town500=True)
    assert World(path).status() == before
    assert WorldMap(World(path)).snapshot() == other
