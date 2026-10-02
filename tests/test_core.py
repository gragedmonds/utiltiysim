import numpy as np
import pytest

from utilsim.core import geom, ids
from utilsim.core.graph import PlanarGraph
from utilsim.core.rng import (
    Purpose,
    derive_seed,
    hash_choice,
    hash_normal,
    hash_u01,
    normalize_seed,
    stage_rng,
)
from utilsim.core.units import get_profile


def test_seed_normalisation_and_derivation_are_stable():
    assert normalize_seed(42) == 42
    assert normalize_seed("42") == 42
    assert normalize_seed("WHITBY-042") == normalize_seed(" WHITBY-042 ")
    assert normalize_seed("WHITBY-042") != normalize_seed("WHITBY-043")
    assert derive_seed(42, "roads", "arterials") == derive_seed("42", "roads", "arterials")
    assert derive_seed(42, "roads", "arterials") != derive_seed(42, "roads", "locals")
    with pytest.raises(ValueError):
        normalize_seed("   ")


def test_stage_rng_streams_independent_and_repeatable():
    a = stage_rng(7, "x").random(5)
    b = stage_rng(7, "x").random(5)
    c = stage_rng(7, "y").random(5)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_hash_u01_is_order_independent_and_well_distributed():
    keys = np.arange(100_000)
    u = hash_u01(42, Purpose.HOUSE_ATTR, keys)
    assert u.shape == keys.shape and u.min() >= 0 and u.max() < 1
    assert abs(u.mean() - 0.5) < 0.005
    # Evaluating a subset gives identical values (counter based, not stream based).
    sub = hash_u01(42, Purpose.HOUSE_ATTR, keys[500:510])
    assert np.array_equal(sub, u[500:510])
    # Different purposes decorrelate; different seeds decorrelate.
    assert abs(np.corrcoef(u, hash_u01(42, Purpose.HOUSEHOLD, keys))[0, 1]) < 0.01
    assert abs(np.corrcoef(u, hash_u01(43, Purpose.HOUSE_ATTR, keys))[0, 1]) < 0.01
    # Multi-key broadcasting.
    m = hash_u01(1, Purpose.DAILY_NOISE, np.arange(4)[:, None], np.arange(3)[None, :])
    assert m.shape == (4, 3)
    with pytest.raises(TypeError):
        hash_u01(1, Purpose.DAILY_NOISE, np.array([0.5]))


def test_hash_normal_and_choice():
    z = hash_normal(3, Purpose.ERA_NOISE, np.arange(200_000))
    assert abs(z.mean()) < 0.01 and abs(z.std() - 1) < 0.01
    c = hash_choice(3, Purpose.DISTRICT_STYLE, np.arange(100_000), [0.2, 0.5, 0.3])
    frac = np.bincount(c, minlength=3) / c.size
    assert np.allclose(frac, [0.2, 0.5, 0.3], atol=0.01)


def test_ids_grammar_matches_prototype():
    p = ids.premise_id(0)
    assert p == "P-00001"
    assert ids.service_point_id(p, "electric") == "SP-P-00001-electric"
    assert ids.register_id(ids.meter_id(p, "electric"), "export") == "M-P-00001-electric-export"
    assert ids.meter_node_id("water", p) == "water-N-P-00001"
    assert ids.edge_id("gas", 7) == "gas-E7"
    assert len(ids.uid("a", 1)) == 16 and ids.uid("a", 1) == ids.uid("a", 1) != ids.uid("a", 2)


def test_units_profiles():
    on = get_profile("ontario")
    assert on.pipe_label(150) == '6"' and on.pipe_label(19) == '3/4"'
    v, u = on.gas_value(2.831685)
    assert u == "CCF" and abs(v - 1.0) < 1e-6
    assert get_profile("uk").pipe_label(150) == "150 mm"
    assert abs(on.pressure_value(413.685)[0] - 60.0) < 0.01


def test_geometry_helpers():
    x, y = geom.project([43.872, 43.873], [-78.937, -78.936], 43.872, -78.937)
    assert abs(x[0]) < 1e-9 and abs(y[0]) < 1e-9 and y[1] > 0 and x[1] > 0
    lat, lon = geom.unproject(x, y, 43.872, -78.937)
    assert np.allclose(lat, [43.872, 43.873]) and np.allclose(lon, [-78.937, -78.936])
    pts = np.array([[0, 0], [10, 0], [10, 10]], dtype=float)
    assert geom.polyline_length(pts) == 20
    px, py, h = geom.point_along(pts, 15)
    assert (px, py) == (10, 5) and abs(h - np.pi / 2) < 1e-9
    off = geom.offset_polyline(pts, 2.0)
    assert len(off) >= 2 and abs(off[0, 1] - 2.0) < 1e-6  # left of eastward travel = north
    vx, vz = geom.to_viewer_xz(1.0, 2.0)
    assert vz == -2.0


def _grid_graph(n=4, spacing=10.0):
    xs, ys = np.meshgrid(np.arange(n) * spacing, np.arange(n) * spacing)
    xy = np.column_stack([xs.ravel(), ys.ravel()]).astype(float)
    uv = []
    for r in range(n):
        for c in range(n):
            i = r * n + c
            if c + 1 < n:
                uv.append((i, i + 1))
            if r + 1 < n:
                uv.append((i, i + n))
    uv = np.asarray(uv, dtype=np.int32)
    length = np.hypot(*(xy[uv[:, 0]] - xy[uv[:, 1]]).T)
    return PlanarGraph(xy, uv, length, np.zeros(len(uv), dtype=np.int8), [xy[list(e)] for e in uv])


def test_graph_forest_and_tree_ops():
    g = _grid_graph()
    assert g.components()[0] == 1
    tree = g.shortest_path_forest(np.array([0]))
    assert tree.roots.tolist() == [0]
    assert tree.depth.max() == 6 and (tree.parent >= 0).sum() == g.n_nodes - 1
    ones = np.ones(g.n_nodes)
    agg = tree.aggregate_up(ones)
    assert agg[0] == g.n_nodes  # root sees everything
    assert np.all(agg >= 1)
    # Leaves aggregate to exactly 1.
    is_parent = np.zeros(g.n_nodes, dtype=bool)
    is_parent[tree.parent[tree.parent >= 0]] = True
    assert np.all(agg[~is_parent] == 1)
    path = tree.path_to_root(15)
    assert path[0] == 15 and path[-1] == 0 and len(path) == 7
    keep = tree.keep_mask_for(np.array([15]))
    assert keep.sum() == 7 and keep[0] and keep[15]
    mask = tree.subtree_mask(0)
    assert mask.all()
    # Two sources partition the grid.
    t2 = g.shortest_path_forest(np.array([0, 15]))
    assert set(t2.roots.tolist()) == {0, 15}
    assert set(np.unique(t2.source).tolist()) == {0, 15}
    down = t2.propagate_down(np.where(t2.parent < 0, 100.0, 0.0), np.ones(g.n_nodes))
    assert down[0] == 100 and down[15] == 100 and down.min() == 100 - t2.depth.max()
