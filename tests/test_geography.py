import numpy as np
import shapely
from scipy.spatial import cKDTree

from utilsim.config import load_preset
from utilsim.gen.landuse import plan_land_use
from utilsim.gen.roads.build import build_geography
from utilsim.gen.roads.model import ARTERIAL, COLLECTOR, LOCAL


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


def _shop_share(cls: np.ndarray, shop: np.ndarray, classes) -> float:
    return float(shop[np.isin(cls, classes)].mean())


def test_main_roads_lean_commercial_local_streets_stay_homes(town480):
    p = town480.prem
    on_lot = p.ptype <= 1  # homes and shops; schools, industry and utility sites sit on their own pads
    cls = town480.roads.graph.edge_class[p.edge][on_lot]
    shop = p.ptype[on_lot] == 1
    main, local = _shop_share(cls, shop, (ARTERIAL, COLLECTOR)), _shop_share(cls, shop, (LOCAL,))
    assert p.residential.sum() == 480
    assert local <= 0.05 and main >= 0.4 and main > 10 * local, (main, local)
    assert local < _shop_share(cls, shop, (COLLECTOR,)) < _shop_share(cls, shop, (ARTERIAL,))
    # Shops come in runs (corners, strips, downtown), not one lot here and another there.
    xy = p.row_xy[p.ptype == 1]
    d, _ = cKDTree(xy).query(xy, k=2)
    assert (d[:, 1] < 30.0).mean() > 0.75


def _land_use(**town):
    cfg = load_preset("whitby_small", seed="WHITBY-042", houses=480, overrides={"town": town})
    geo = build_geography(cfg)
    return cfg, geo, plan_land_use(geo, cfg)


def test_frontage_shares_are_settings_and_homes_stay_exact():
    cfg, geo, lu = _land_use(commercial_share_arterial=0.0, commercial_share_collector=0.0,
                             commercial_share_local=0.0)
    assert len(lu.houses) == 480
    # With every share at zero only the downtown main street is commercial.
    assert (lu.roads.graph.edge_class[lu.commercial.edge] == ARTERIAL).all()
    fdist = np.hypot(*(lu.commercial.front_xy - np.asarray(geo.center)).T)
    assert (fdist < cfg.town.commercial_strip_m / 2).all()
    _, _, lu = _land_use(commercial_share_local=0.25)
    assert len(lu.houses) == 480
    g = lu.roads.graph
    shops, homes = (g.edge_class[lu.commercial.edge] == LOCAL).sum(), (g.edge_class[lu.houses.edge] == LOCAL).sum()
    assert abs(shops / (shops + homes) - 0.25) < 0.03
