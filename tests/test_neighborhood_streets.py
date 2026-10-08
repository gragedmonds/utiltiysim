"""New street patterns must support real properties, networks and crew travel."""
import numpy as np
import pytest
import shapely
from pydantic import ValidationError

from utilsim.config import SimConfig, config_schema, load_preset
from utilsim.gen.pipeline import generate
from utilsim.gen.roads.build import build_geography
from utilsim.io.snapshot import build_snapshot
from utilsim.ops.opstown import OpsTown
from utilsim.ops.routing import Router, access_point
from utilsim.validate import validate_town
from utilsim.world import World
from utilsim.world.map_view import WorldMap


def config(houses=480, seed="TOWN-042", **town):
    return load_preset("village", houses=houses, seed=seed,
                       overrides={"town": {"street_pattern": "neighborhoods", **town}})


def test_default_keeps_existing_identity_and_roads():
    legacy = load_preset("village", houses=480, seed="TOWN-042")
    assert legacy.town_id() == "town-ab2b8b3609f83517"
    old_document = legacy.model_dump()
    old_document["town"].pop("street_pattern")
    restored = SimConfig.model_validate(old_document)
    assert restored.town_id() == legacy.town_id()
    left, right = build_geography(legacy), build_geography(restored)
    assert left.source == right.source == {"type": "synthetic", "label": "Synthetic town", "expansion": "none"}
    for a, b in zip(left.roads.graph.geometry, right.roads.graph.geometry, strict=True):
        np.testing.assert_array_equal(a, b)
    assert config().town_id() != legacy.town_id()


def test_street_option_is_validated_and_explained_in_settings():
    field = config_schema()["$defs"]["TownConfig"]["properties"]["street_pattern"]
    assert field["enum"] == ["legacy", "neighborhoods"]
    assert field["default"] == "legacy" and field["x-reach"] == "shape"
    assert "New towns only" in field["description"]
    with pytest.raises(ValidationError):
        config(street_pattern="unrecognised")


@pytest.mark.parametrize("houses,seed,warp", [(20, "TOWN-042", 0), (120, "STREETS-2", 130),
                                             (480, "TOWN-042", 130), (2000, "STREETS-2", 400)])
def test_neighborhoods_support_properties_networks_and_travel(houses, seed, warp):
    town = generate(config(houses, seed, arterial_warp_m=warp))
    graph = town.roads.graph
    assert graph.components()[0] == 1
    lines = [shapely.LineString(p) for p in graph.geometry]
    tree = shapely.STRtree(lines)
    assert not any(len(tree.query(line, predicate="crosses")) for line in lines)
    # Separately placed junctions must not create tiny local street fragments.
    assert min(graph.length[graph.edge_class == 2]) > 20
    assert town.prem.residential.sum() == houses
    lots = town.prem.lot
    pairs = shapely.STRtree(lots).query(lots, predicate="intersects")
    assert all(lots[i].intersection(lots[j]).area < .5 for i, j in zip(*pairs) if i < j)
    residential = np.flatnonzero(town.prem.residential)
    assert sum(lots[i].buffer(.5).contains(town.prem.footprint[i]) for i in residential)/houses > .97
    assert len(set(zip(town.prem.street, town.prem.number))) == len(town.prem)
    assert not validate_town(town)["errors"]
    snapshot = build_snapshot(town, include_reads=False)
    assert snapshot["source"]["streetModel"] == "neighborhood-streets/1"
    assert snapshot["config"]["town"]["street_pattern"] == "neighborhoods"
    assert snapshot["stats"]["gasServices"] > 0 and snapshot["stats"]["hydrants"] > 0
    ops = OpsTown(snapshot)
    router = Router(ops.roads, (50, 40, 30))
    depot = access_point(ops.roads, *ops.depot["access"])
    for i in range(len(ops.premises)):
        route = router.route(depot, access_point(ops.roads, *ops.premise_access[i]))
        assert np.isfinite(route.seconds) and np.all(np.diff(route.times) > 0)
        front = ops.premises[i]["front"]
        assert np.hypot(*(route.points[-1] - (front["x"], front["z"]))) < 2.5


def test_repeatable_geometry_and_shorter_blocks():
    a, b = build_geography(config()), build_geography(config())
    for left, right in zip(a.roads.graph.geometry, b.roads.graph.geometry, strict=True):
        np.testing.assert_array_equal(left, right)
    old = build_geography(config(street_pattern="legacy")).roads.graph
    new = a.roads.graph
    assert np.median(new.length[new.edge_class == 2]) < np.median(old.length[old.edge_class == 2])


def test_world_pins_streets_and_replays_all_four_utility_observations(tmp_path):
    town = generate(config(20))
    snapshot = build_snapshot(town, include_reads=False)
    world = World(tmp_path/"world.sqlite")
    world.initialize(snapshot, "NEIGHBORHOODS")
    world.advance("2026-01-03")
    first = world.export_v2("2026-01-01", "2026-01-03")
    reopened = World(tmp_path/"world.sqlite")
    reopened.advance("2026-01-03")
    assert reopened.export_v2("2026-01-01", "2026-01-03") == first
    assert WorldMap(reopened).snapshot()["roads"] == snapshot["roads"]
    assert {o["commodity"] for o in first["observations"]} == {"electric", "gas", "water", "sewer"}
