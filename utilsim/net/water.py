"""Water distribution: off-map treated supply → pumping station → transmission/trunk mains → distribution mains
→ services → meters, with elevated tanks, pressure zones (PRVs/boosters at boundaries), loops, hydrants and
valves. Mains are sized for peak hour at 1.5 m/s and for max-day + fire flow at 3 m/s; fire flow governs."""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from utilsim.core.ids import meter_node_id, service_point_id
from utilsim.gen.roads.model import ARTERIAL, COLLECTOR
from utilsim.model.network import Network
from utilsim.net.common import (
    OFFSETS,
    Forest,
    SplitGraph,
    add_closed_tie,
    facility_path,
    grow,
    loop_pieces,
    piece_points,
    subtree_max,
    subtree_sums,
)
from utilsim.net.context import NetContext
from utilsim.net.tables import V_FIRE, V_NORMAL, WATER_MAINS, WATER_SERVICE, water_capacity_lps
from utilsim.sim.demand import water_avg_lps

FIRE_CLASS = {0: "fire_flow_residential_lps", 1: "fire_flow_commercial_lps", 2: "fire_flow_commercial_lps",
              3: "fire_flow_industrial_lps", 4: "fire_flow_commercial_lps"}


def _pick_main(ph_lps: float, fire_lps: float, min_mm: int) -> int:
    for p in WATER_MAINS:
        if p.nominal_mm < min_mm:
            continue
        if water_capacity_lps(p, V_NORMAL) >= ph_lps and water_capacity_lps(p, V_FIRE) >= fire_lps:
            return p.nominal_mm
    return WATER_MAINS[-1].nominal_mm


MAIN_BY_MM = {p.nominal_mm: p for p in WATER_MAINS}


def build_water(ctx: NetContext) -> Network:
    cfg, prem, w = ctx.cfg, ctx.prem, ctx.cfg.water
    roads = ctx.roads
    g = roads.graph
    pumps = ctx.facilities("pump_station")
    tanks = ctx.facilities("elevated_tank")
    if not pumps:
        raise RuntimeError("water network needs a pumping station")
    n_prem = len(prem)
    tap_edge = np.concatenate([prem.edge, [f.edge for f in pumps + tanks]]).astype(np.int64)
    tap_s = np.concatenate([prem.s, [f.s for f in pumps + tanks]])
    sg = SplitGraph.build(roads, tap_edge, tap_s)
    prem_tap = sg.n_road + np.arange(n_prem)
    pump_tap = [sg.n_road + n_prem + i for i in range(len(pumps))]
    tank_tap = [sg.n_road + n_prem + len(pumps) + i for i in range(len(tanks))]
    forest = grow(sg, pump_tap, np.concatenate([prem_tap, tank_tap]), "water", ctx.seed)

    # Zones by elevation band (one per tank).
    z = ctx.terrain.elevation(sg.xy[:, 0], sg.xy[:, 1])
    n_z = max(1, len(tanks))
    zmin = float(z[forest.keep].min())
    zone = np.clip(((z - zmin) / w.zone_band_m).astype(int), 0, n_z - 1)

    # Loads per split node.
    avg = water_avg_lps(prem, cfg)
    own_avg = np.zeros(sg.n_nodes)
    own_avg[prem_tap] = avg
    fire_own = np.zeros(sg.n_nodes)
    fire_own[prem_tap] = [getattr(w, FIRE_CLASS[int(t)]) for t in prem.ptype]
    loops = loop_pieces(sg, forest)
    loop_end = np.zeros(sg.n_nodes)
    loop_end[sg.piece_a[loops]] = 1
    loop_end[sg.piece_b[loops]] = 1
    sub_avg = subtree_sums(forest, own_avg)
    sub_fire = subtree_max(forest, fire_own)
    sub_loop = subtree_max(forest, loop_end)
    sub_n = subtree_sums(forest, np.isin(np.arange(sg.n_nodes), prem_tap).astype(float))
    ph = sub_avg * w.peak_hour_factor
    md = sub_avg * w.max_day_factor
    fire_need = md + sub_fire * np.where(sub_loop > 0, 0.55, 1.0)

    # Size every kept child node's parent piece; then enforce non-increasing sizes away from the source.
    size = np.zeros(sg.n_nodes, dtype=int)
    for v in forest.order:
        if forest.parent[v] < 0:
            continue
        cls = int(g.edge_class[sg.piece_edge[forest.parent_piece[v]]])
        min_mm = w.min_main_mm
        if cls == COLLECTOR:
            min_mm = max(min_mm, w.collector_main_mm if sub_n[v] >= 60 else w.min_main_mm)
        if cls == ARTERIAL:
            min_mm = max(min_mm, w.arterial_main_mm if sub_n[v] >= 200 else w.collector_main_mm)
        size[v] = _pick_main(ph[v], fire_need[v], min_mm)
    for v in forest.order[::-1]:
        p = forest.parent[v]
        if p >= 0 and forest.parent[p] >= 0 and size[p] < size[v]:
            size[p] = size[v]

    net = Network("water", "m3/h")
    off = OFFSETS["water"]
    pump = pumps[0]
    entry = ctx.exit_for(pump.xy)
    total_md = float(md[pump_tap].sum())
    supply_mm = max(400, _pick_main(total_md * 1.2, total_md + w.fire_flow_industrial_lps, 400))
    src = net.add_node("water-supply", "external_supply", entry, label="Treated water supply (off-map)")
    st = net.add_node("water-station", "pump_station", pump.xy, label=pump.label, facilityId=pump.id,
                      pumps=w.pump_units)
    _sized_edge(net, "supply", src, st, facility_path(roads, entry, pump), supply_mm, "transmission", zone=0)
    net.source_id, net.station_id = "water-supply", "water-station"
    node_of: dict[int, int] = {}
    root_tap = pump_tap[0]
    node_of[root_tap] = net.add_node(f"water-J-T{root_tap}", "junction",
                                     sg.point_at(int(sg.tap_edge[root_tap - sg.n_road]), float(sg.tap_s[root_tap - sg.n_road]), off))
    trunk_mm = int(max(size[forest.order].max() if len(forest.order) else 0, w.arterial_main_mm))
    _sized_edge(net, "trunk", st, node_of[root_tap], None, trunk_mm, "trunk", zone=0)
    _emit_tree(net, sg, forest, node_of, size, zone, off, prem_tap, tank_tap, sub_n, ph, fire_need)
    # Zone boundary equipment.
    for v in forest.order:
        p = forest.parent[v]
        if p < 0 or zone[p] == zone[v]:
            continue
        e = net.nodes[node_of[v]].parent_edge
        kind = "booster_station" if zone[v] > zone[p] else "prv"
        net.edges[e].attrs["equipment"] = kind
        net.equipment.append({"id": f"{kind.upper()}-{len(net.equipment)}", "kind": kind,
                              "xy": net.edges[e].points[len(net.edges[e].points) // 2], "edgeId": net.edges[e].id,
                              "fromZone": int(zone[p]), "toZone": int(zone[v])})
    # Tanks.
    for i, (f, t) in enumerate(zip(tanks, tank_tap)):
        tank = net.add_node(f"water-tank-{i + 1}", "elevated_tank", f.xy, label=f.label, facilityId=f.id,
                            zone=int(zone[t]), overflowElevationM=round(float(z[forest.keep & (zone == zone[t])].max()
                                                                                + w.tank_overflow_above_ground_m), 2),
                            capacityM3=3785.0)
        _sized_edge(net, "tank_riser", node_of[t], tank, None, 400, "trunk", zone=int(zone[t]))
    # Services and meters.
    meter_w = prem.meter_point("water")
    for i in range(n_prem):
        t = prem_tap[i]
        meter_xy = meter_w[i]
        mid = net.add_node(meter_node_id("water", prem.ids[i]), "meter", meter_xy, premiseId=prem.ids[i],
                           servicePointId=service_point_id(prem.ids[i], "water"))
        peak_lps = avg[i] * 8.0
        mm, label = 19, '3/4" copper'
        if prem.ptype[i] != 0 or prem.attrs["irrigation"][i] or prem.lot_area[i] > 1500:
            for smm, slabel, cap in WATER_SERVICE:
                if cap >= peak_lps and smm >= (25 if prem.ptype[i] == 0 else 38):
                    mm, label = smm, slabel
                    break
        pts = np.array([net.nodes[node_of[t]].xy, prem.row_xy[i] + prem.normal[i] * 0.5, meter_xy])
        net.add_edge("service", node_of[t], mid, pts, placement="underground", tier="service", size_mm=mm,
                     diameterIn=round(mm / 25.4, 2), nominalLabel=label, depthM=1.7, zone=int(zone[t]))
    # Loops (closed ties): connected within a zone, closed valve across zones.
    for k in loops:
        a, b = int(sg.piece_a[k]), int(sg.piece_b[k])
        if a not in node_of or b not in node_of:
            continue
        mm = int(min(size[a] if forest.parent[a] >= 0 else size[b], size[b] if forest.parent[b] >= 0 else size[a]))
        mm = max(mm, w.min_main_mm)
        state = "connected" if zone[a] == zone[b] else "closed_valve"
        pts = piece_points(sg, int(k), off, a)
        add_closed_tie(net, node_of[a], node_of[b], pts, state, placement="underground", tier="distribution",
                       size_mm=mm, diameterIn=round(mm / 25.4, 1), nominalLabel=MAIN_BY_MM[mm].label,
                       material=MAIN_BY_MM[mm].material, depthM=1.8, zone=int(zone[a]))
    _hydrants_and_valves(net, ctx, prem)
    net.meta.update({"zones": int(n_z), "zoneBandM": w.zone_band_m, "elevationMinM": round(zmin, 2),
                     "designPeakHourLps": round(float(ph[pump_tap].sum()), 2),
                     "designMaxDayLps": round(total_md, 2), "loops": int(len(loops))})
    return net


def _sized_edge(net: Network, kind: str, a: int, b: int, pts, mm: int, tier: str, zone: int) -> int:
    pipe = MAIN_BY_MM.get(mm) or WATER_MAINS[-1]
    return net.add_edge(kind, a, b, pts, placement="underground", tier=tier, size_mm=pipe.nominal_mm,
                        diameterIn=round(pipe.nominal_mm / 25.4, 1), nominalLabel=pipe.label, material=pipe.material,
                        depthM=1.8, zone=zone)


def _emit_tree(net, sg: SplitGraph, forest: Forest, node_of, size, zone, off, prem_tap, tank_tap, sub_n, ph,
               fire_need):
    g = sg.roads.graph
    for v in forest.order:
        p = int(forest.parent[v])
        if p < 0:
            continue
        piece = int(forest.parent_piece[v])
        pts = piece_points(sg, piece, off, p)
        nid = f"water-J-{v}" if v < sg.n_road else f"water-T-{v}"
        node_of[v] = net.add_node(nid, "junction", pts[-1], zone=int(zone[v]))
        mm = int(size[v])
        pipe = MAIN_BY_MM[mm]
        cls = int(g.edge_class[sg.piece_edge[piece]])
        tier = "trunk" if mm >= 300 or cls == ARTERIAL and mm >= 250 else "distribution"
        net.add_edge("distribution", node_of[p], node_of[v], pts, placement="underground", tier=tier, size_mm=mm,
                     diameterIn=round(mm / 25.4, 1), nominalLabel=pipe.label, material=pipe.material, depthM=1.8,
                     zone=int(zone[v]), roadEdge=int(sg.piece_edge[piece]), customers=int(sub_n[v]),
                     designPeakHourLps=round(float(ph[v]), 3), designFireLps=round(float(fire_need[v]), 2))


def _hydrants_and_valves(net: Network, ctx: NetContext, prem) -> None:
    w = ctx.cfg.water
    com = prem.xy[prem.ptype == 1]
    placed: list[np.ndarray] = []
    from scipy.spatial import cKDTree

    com_tree = cKDTree(com) if len(com) else None
    mains = [e for e in net.edges if e.kind in ("distribution", "trunk") and e.size_mm >= 150]
    grid: dict[tuple[int, int], list[np.ndarray]] = {}
    cell = w.hydrant_spacing_m
    for e in mains:
        pts = e.points
        seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        L = float(seg.sum())
        if L < 5:
            continue
        cum = np.concatenate([[0], np.cumsum(seg)])
        for s in np.arange(5.0, L, 10.0):
            i = min(int(np.searchsorted(cum, s, side="right") - 1), len(seg) - 1)
            t = 0 if seg[i] == 0 else (s - cum[i]) / seg[i]
            p = pts[i] + (pts[i + 1] - pts[i]) * t
            spacing = w.hydrant_spacing_m
            if com_tree is not None and com_tree.query(p)[0] < 80:
                spacing = w.hydrant_spacing_commercial_m
            gx, gy = int(p[0] // cell), int(p[1] // cell)
            near = [q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in grid.get((gx + dx, gy + dy), [])]
            if any(np.hypot(*(q - p)) < spacing * 0.92 for q in near):
                continue
            grid.setdefault((gx, gy), []).append(p)
            placed.append(p)
            net.equipment.append({"id": f"HYD-{len(placed):05d}", "kind": "hydrant", "xy": p, "edgeId": e.id,
                                  "chainageM": round(float(s), 1)})
    # Valves: N-1 at junctions with 3+ mains; line valves so no run exceeds the spacing.
    inc: dict[int, list[int]] = {}
    for k, e in enumerate(net.edges):
        if e.kind in ("distribution", "trunk"):
            inc.setdefault(e.a, []).append(k)
            inc.setdefault(e.b, []).append(k)
    nv = 0
    for node, es in sorted(inc.items()):
        if len(es) < 3:
            continue
        for k in sorted(es)[: len(es) - 1]:
            e = net.edges[k]
            end = e.points[0] if e.a == node else e.points[-1]
            nxt = e.points[1] if e.a == node else e.points[-2]
            d = nxt - end
            p = end + d / max(np.hypot(*d), 1e-9) * min(3.0, float(np.hypot(*d)) / 2)
            nv += 1
            net.equipment.append({"id": f"WV-{nv:05d}", "kind": "valve", "xy": p, "edgeId": e.id, "normally": "open"})
    for e in net.edges:
        if e.kind not in ("distribution", "trunk"):
            continue
        L = e.length
        line = LineString(e.points)
        for s in np.arange(w.valve_spacing_m, L - 20, w.valve_spacing_m):
            q = line.interpolate(float(s))
            p = np.array([q.x, q.y])
            nv += 1
            net.equipment.append({"id": f"WV-{nv:05d}", "kind": "valve", "xy": p, "edgeId": e.id, "normally": "open"})
