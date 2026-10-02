import numpy as np
import shapely

from utilsim.gen.roads.model import ARTERIAL


def _check_planar_synthetic(roads):
    g = roads.graph
    lines = [shapely.LineString(p) for p in g.geometry]
    tree = shapely.STRtree(lines)
    synth = [e for e in range(g.n_edges) if roads.origin[e] != "osm"]
    for e in synth:
        for o in tree.query(lines[e], predicate="crosses"):
            assert roads.origin[o] == "osm", f"synthetic edge {e} crosses {o}"


def test_road_networks_connected(town480, synth):
    for t in (town480, synth):
        assert t.roads.graph.components()[0] == 1
        assert (t.roads.graph.edge_class == ARTERIAL).any()


def test_synthetic_roads_planar(synth):
    _check_planar_synthetic(synth.roads)


def test_lots_do_not_overlap_and_buildings_inside(town480, synth):
    for t in (town480, synth):
        lots = t.prem.lot
        tree = shapely.STRtree(lots)
        pairs = tree.query(lots, predicate="intersects")
        for i, j in zip(*pairs):
            if i < j:
                assert lots[i].intersection(lots[j]).area < 0.5
        res = np.flatnonzero(t.prem.residential)
        inside = sum(lots[i].buffer(0.5).contains(t.prem.footprint[i]) for i in res)
        assert inside / len(res) > 0.97


def test_addresses_unique_per_street(town480):
    seen = set()
    for s, n in zip(town480.prem.street, town480.prem.number):
        assert (s, int(n)) not in seen
        seen.add((s, int(n)))


def test_water_and_electric_engineering_rules(town480, synth):
    for t in (town480, synth):
        w = t.networks["water"]
        mains = [e for e in w.edges if e.kind == "distribution"]
        assert all(e.size_mm >= t.cfg.water.min_main_mm for e in mains)
        assert sum(q["kind"] == "hydrant" for q in w.equipment) > 0
        el = t.networks["electric"]
        for nd in el.nodes:
            if nd.kind == "transformer" and nd.attrs["phases"] == 1:
                assert nd.attrs["designKVA"] <= nd.attrs["ratingKVA"] * t.cfg.electric.transformer_max_loading
        assert el.meta["substations"] >= 1 and el.meta["transformers"] > 0
