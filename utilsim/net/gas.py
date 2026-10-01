"""Natural gas: off-map transmission → city gate (pressure reduction to MP) → medium-pressure PE mains → service
(¾" with a service regulator at every MP meter) → meter. Optionally a legacy low-pressure core (pre-war streets)
fed through district regulator stations, with larger low-pressure mains and no service regulators."""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from utilsim.core.ids import meter_node_id, service_point_id
from utilsim.model.network import Network
from utilsim.net.common import (
    OFFSETS,
    SplitGraph,
    add_closed_tie,
    facility_path,
    grow,
    loop_pieces,
    piece_points,
    subtree_sums,
)
from utilsim.net.context import NetContext
from utilsim.net.tables import GAS_LP, GAS_MP, GAS_SERVICE, GAS_TRANSMISSION, coincidence, gas_capacity_m3h
from utilsim.sim.demand import design_gas_m3h

KPA_PER_PSI = 6.894757


def _pick(table, m3h: float, mp_psig: float, min_mm: int = 0):
    for p in table:
        if p.nominal_mm >= min_mm and gas_capacity_m3h(p, mp_psig) >= m3h:
            return p
    return table[-1]


def build_gas(ctx: NetContext) -> Network:
    cfg, prem, gcfg = ctx.cfg, ctx.prem, ctx.cfg.gas
    roads = ctx.roads
    gates = ctx.facilities("city_gate")
    served = np.flatnonzero(prem.attrs["has_gas"])
    net = Network("gas", "m3/h")
    if not gates:
        raise RuntimeError("gas network needs a city gate")
    gate = gates[0]
    mp_psig = gcfg.mp_kpa / KPA_PER_PSI
    tap_edge = np.concatenate([prem.edge[served], [gate.edge]]).astype(np.int64)
    tap_s = np.concatenate([prem.s[served], [gate.s]])
    sg = SplitGraph.build(roads, tap_edge, tap_s)
    prem_tap = sg.n_road + np.arange(len(served))
    gate_tap = sg.n_road + len(served)
    entry = ctx.exit_for(gate.xy)
    src = net.add_node("gas-supply", "external_supply", entry, label="Regional gas transmission (off-map)")
    st = net.add_node("gas-station", "city_gate_regulator", gate.xy, label=gate.label, facilityId=gate.id,
                      inletKPa=gcfg.transmission_kpa, outletKPa=gcfg.mp_kpa)
    net.source_id, net.station_id = "gas-supply", "gas-station"
    net.add_edge("supply", src, st, facility_path(roads, entry, gate), placement="underground", tier="transmission",
                 size_mm=GAS_TRANSMISSION.nominal_mm, diameterIn=12.0, nominalLabel=GAS_TRANSMISSION.label,
                 material="steel", depthM=1.2, pressureKPa=gcfg.transmission_kpa, pressureTier="hp")
    if not len(served):
        net.meta["served"] = 0
        return net
    forest = grow(sg, [gate_tap], prem_tap, "gas", ctx.seed)
    # Pressure tier: LP inside the legacy core once entered (never back to MP downstream).
    lp_zone = np.zeros(sg.n_nodes, dtype=bool)
    if gcfg.scheme == "mp_with_lp_core":
        lp_zone = ctx.year_at(sg.xy) < gcfg.lp_core_before_year
    tier_lp = np.zeros(sg.n_nodes, dtype=bool)
    for v in forest.order:
        p = forest.parent[v]
        tier_lp[v] = lp_zone[v] if p < 0 else (tier_lp[p] or lp_zone[v])
    tier_lp[gate_tap] = False
    loads = design_gas_m3h(prem, cfg)
    own = np.zeros(sg.n_nodes)
    own[prem_tap] = loads[served]
    cnt = np.zeros(sg.n_nodes)
    cnt[prem_tap] = 1
    sub_load = subtree_sums(forest, own)
    sub_n = subtree_sums(forest, cnt)
    design = coincidence(sub_n, gcfg.coincidence_floor) * sub_load
    pipe_of: dict[int, object] = {}
    for v in forest.order:
        if forest.parent[v] < 0:
            continue
        table = GAS_LP if tier_lp[v] else GAS_MP
        pipe_of[v] = _pick(table, design[v], mp_psig, gcfg.min_main_mm if not tier_lp[v] else 100)
    # Monotone within a tier: a parent main is at least as large as any same-tier child.
    for v in forest.order[::-1]:
        p = forest.parent[v]
        if p >= 0 and forest.parent[p] >= 0 and tier_lp[p] == tier_lp[v]:
            if pipe_of[p].nominal_mm < pipe_of[v].nominal_mm:
                pipe_of[p] = pipe_of[v]
    off = OFFSETS["gas"]
    node_of: dict[int, int] = {}
    root_xy = sg.point_at(int(gate.edge), float(gate.s), off)
    node_of[gate_tap] = net.add_node(f"gas-J-T{gate_tap}", "junction", root_xy, pressureTier="mp")
    head = max((pipe_of[v] for v in pipe_of if forest.parent[v] == gate_tap), key=lambda p: p.nominal_mm,
               default=GAS_MP[1])
    net.add_edge("trunk", st, node_of[gate_tap], None, placement="underground", tier="trunk",
                 size_mm=head.nominal_mm, diameterIn=round(head.nominal_mm / 25.4, 1), nominalLabel=head.label,
                 material=head.material, depthM=1.0, pressureKPa=gcfg.mp_kpa, pressureTier="mp")
    n_reg = 0
    for v in forest.order:
        p = int(forest.parent[v])
        if p < 0:
            continue
        piece = int(forest.parent_piece[v])
        pts = piece_points(sg, piece, off, p)
        pipe = pipe_of[v]
        nid = f"gas-J-{v}" if v < sg.n_road else f"gas-T-{v}"
        a = node_of[p]
        if tier_lp[v] and not tier_lp[p]:
            # District regulator station at the piece midpoint.
            line = LineString(pts)
            mid = line.interpolate(0.5, normalized=True)
            n_reg += 1
            reg = net.add_node(f"gas-DREG-{n_reg:02d}", "district_regulator", (mid.x, mid.y),
                               label=f"District regulator {n_reg}", inletKPa=gcfg.mp_kpa, outletKPa=gcfg.lp_kpa)
            first = np.vstack([pts[:1], _cut(line, 0, line.length / 2)])
            mp_pipe = _pick(GAS_MP, design[v], mp_psig, gcfg.min_main_mm)
            net.add_edge("distribution", a, reg, first, placement="underground", tier="distribution",
                         size_mm=mp_pipe.nominal_mm, diameterIn=round(mp_pipe.nominal_mm / 25.4, 1),
                         nominalLabel=mp_pipe.label, material=mp_pipe.material, depthM=1.0,
                         pressureKPa=gcfg.mp_kpa, pressureTier="mp", customers=int(sub_n[v]),
                         designM3h=round(float(design[v]), 3))
            net.equipment.append({"id": f"GREG-{n_reg:02d}", "kind": "district_regulator",
                                  "xy": np.array([mid.x, mid.y]), "nodeId": net.nodes[reg].id})
            a = reg
            pts = _cut(line, line.length / 2, line.length)
        node_of[v] = net.add_node(nid, "junction", pts[-1], pressureTier="lp" if tier_lp[v] else "mp")
        net.add_edge("distribution", a, node_of[v], pts, placement="underground",
                     tier="trunk" if pipe.nominal_mm >= 150 and not tier_lp[v] else "distribution",
                     size_mm=pipe.nominal_mm, diameterIn=round(pipe.nominal_mm / 25.4, 1), nominalLabel=pipe.label,
                     material=pipe.material, depthM=1.0,
                     pressureKPa=gcfg.lp_kpa if tier_lp[v] else gcfg.mp_kpa,
                     pressureTier="lp" if tier_lp[v] else "mp", customers=int(sub_n[v]),
                     designM3h=round(float(design[v]), 3), roadEdge=int(sg.piece_edge[piece]))
    # Services and meter sets.
    for k, i in enumerate(served):
        t = int(prem_tap[k])
        meter_xy = prem.meter_point("gas")[i]
        mid = net.add_node(meter_node_id("gas", prem.ids[i]), "meter", meter_xy, premiseId=prem.ids[i],
                           servicePointId=service_point_id(prem.ids[i], "gas"),
                           meterClass="250 CFH diaphragm" if loads[i] < 7 else "1000 CFH rotary")
        lp = bool(tier_lp[t])
        mm, label = 19, '3/4" PE'
        for smm, slabel, cap in GAS_SERVICE:
            if cap >= loads[i] * (1.6 if lp else 1.0) and (smm >= 25 or not lp):
                mm, label = smm, slabel
                break
        pts = np.array([net.nodes[node_of[t]].xy, prem.row_xy[i], meter_xy])
        attrs = {"regulator": "service pressure regulator"} if not lp else {}
        net.add_edge("service", node_of[t], mid, pts, placement="underground", tier="service", size_mm=mm,
                     diameterIn=round(mm / 25.4, 2), nominalLabel=label, depthM=0.8,
                     pressureTier="lp" if lp else "mp", excessFlowValve=not lp, **attrs)
    # Loops within the same pressure tier.
    for k in loop_pieces(sg, forest):
        a, b = int(sg.piece_a[k]), int(sg.piece_b[k])
        if a not in node_of or b not in node_of or tier_lp[a] != tier_lp[b]:
            continue
        pa = pipe_of.get(a) or pipe_of.get(b)
        pb = pipe_of.get(b) or pa
        pipe = pa if pa.nominal_mm <= pb.nominal_mm else pb
        add_closed_tie(net, node_of[a], node_of[b], piece_points(sg, int(k), off, a), "connected",
                       placement="underground", tier="distribution", size_mm=pipe.nominal_mm,
                       diameterIn=round(pipe.nominal_mm / 25.4, 1), nominalLabel=pipe.label, material=pipe.material,
                       depthM=1.0, pressureTier="lp" if tier_lp[a] else "mp")
    _valves(net, gcfg.valve_spacing_m)
    net.meta.update({"served": int(len(served)), "scheme": gcfg.scheme, "districtRegulators": n_reg,
                     "designHourM3h": round(float(design[gate_tap]), 2), "mpKPa": gcfg.mp_kpa, "lpKPa": gcfg.lp_kpa,
                     "lpCustomers": int(tier_lp[prem_tap].sum())})
    return net


def _cut(line: LineString, a: float, b: float) -> np.ndarray:
    from shapely.ops import substring

    return np.asarray(substring(line, a, b).coords)


def _valves(net: Network, spacing: float) -> None:
    inc: dict[int, list[int]] = {}
    for k, e in enumerate(net.edges):
        if e.kind in ("distribution", "trunk") and e.attrs.get("pressureTier") == "mp":
            inc.setdefault(e.a, []).append(k)
            inc.setdefault(e.b, []).append(k)
    n = 0
    for node, es in sorted(inc.items()):
        if len(es) >= 3:
            for k in sorted(es)[: len(es) - 1]:
                e = net.edges[k]
                end, nxt = (e.points[0], e.points[1]) if e.a == node else (e.points[-1], e.points[-2])
                d = nxt - end
                n += 1
                net.equipment.append({"id": f"GV-{n:05d}", "kind": "valve",
                                      "xy": end + d / max(np.hypot(*d), 1e-9) * min(2.5, float(np.hypot(*d)) / 2),
                                      "edgeId": e.id, "normally": "open"})
    for e in net.edges:
        if e.kind in ("distribution", "trunk") and e.size_mm >= 100 and e.attrs.get("pressureTier") == "mp":
            line = LineString(e.points)
            for s in np.arange(spacing, line.length - 30, spacing):
                q = line.interpolate(float(s))
                n += 1
                net.equipment.append({"id": f"GV-{n:05d}", "kind": "valve", "xy": np.array([q.x, q.y]),
                                      "edgeId": e.id, "normally": "open"})
