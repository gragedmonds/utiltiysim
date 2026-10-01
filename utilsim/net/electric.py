"""Electric distribution: off-map transmission → substation(s) (in-and-out 115 kV backbone) → 3φ primary feeders
→ 1φ laterals → distribution transformers (pole-mount in overhead districts, pad-mount underground) → 120/240 V
services → meters. Feeders are carved from each substation's tree by design capacity; adjacent feeders get
normally-open tie switches; reclosers at feeder heads, fuses at lateral taps, poles along overhead lines."""

from __future__ import annotations

import math

import numpy as np

from utilsim.core.ids import meter_node_id, service_point_id
from utilsim.gen.roads.model import ARTERIAL, LOCAL, ROW_WIDTH
from utilsim.model.network import Network
from utilsim.net.common import (
    OFFSETS,
    SplitGraph,
    add_loop_edge,
    densify_polyline,
    facility_path,
    grow,
    loop_pieces,
    piece_points,
    subtree_sums,
)
from utilsim.net.context import NetContext
from utilsim.net.tables import SECONDARY, THREE_PHASE_KVA, coincidence, conductor_kva, pick_conductor
from utilsim.sim.demand import design_kva


def _groups(ctx: NetContext, kva: np.ndarray, overhead: np.ndarray) -> list[dict]:
    """Consecutive premises along each street side-agnostic, limited by count, span and transformer size."""
    prem, e = ctx.prem, ctx.cfg.electric
    max_kva = e.transformer_kva_steps[-1] * e.transformer_max_loading
    out: list[dict] = []
    order = np.lexsort((prem.s, prem.edge))
    cur: list[int] = []

    def flush():
        if cur:
            out.append({"members": list(cur)})
            cur.clear()

    for i in order:
        i = int(i)
        if prem.ptype[i] != 0:
            continue
        if cur:
            j0 = cur[0]
            same_edge = prem.edge[i] == prem.edge[j0]
            limit = e.max_houses_per_transformer_overhead if overhead[j0] else \
                e.max_houses_per_transformer_underground
            members = cur + [i]
            load = float(coincidence(len(members), e.coincidence_floor) * kva[members].sum())
            if (not same_edge or overhead[i] != overhead[j0] or len(cur) >= limit or
                    prem.s[i] - prem.s[j0] > 90.0 or load > max_kva):
                flush()
        cur.append(i)
    flush()
    # Non-residential: storefronts share a pad (≤ 3 within 60 m), larger customers get their own.
    com = [int(i) for i in order if prem.ptype[i] == 1]
    for i in com:
        if cur and (prem.edge[i] != prem.edge[cur[0]] or len(cur) >= 3 or prem.s[i] - prem.s[cur[0]] > 60):
            out.append({"members": list(cur), "three_phase": True})
            cur.clear()
        cur.append(i)
    if cur:
        out.append({"members": list(cur), "three_phase": True})
        cur.clear()
    for i in order:
        if prem.ptype[i] >= 2:
            out.append({"members": [int(i)], "three_phase": True})
    for g in out:
        m = g["members"]
        g["s"] = float(np.median(prem.s[m]))
        g["edge"] = int(prem.edge[m[0]])
        g["overhead"] = bool(np.mean(overhead[m]) >= 0.5) and not g.get("three_phase", False)
        g["kva_sum"] = float(kva[m].sum())
        g["design"] = float(coincidence(len(m), e.coincidence_floor) * kva[m].sum())
    return out


def _rating(design_kva: float, three_phase: bool, steps, loading: float) -> float:
    table = THREE_PHASE_KVA if three_phase else steps
    for r in table:
        if r * (1.0 if three_phase else loading) >= design_kva:
            return float(r)
    return float(table[-1])


def build_electric(ctx: NetContext) -> Network:
    cfg, prem, ec = ctx.cfg, ctx.prem, ctx.cfg.electric
    roads = ctx.roads
    g = roads.graph
    subs = ctx.facilities("substation")
    if not subs:
        raise RuntimeError("electric network needs a substation")
    kva = design_kva(prem, cfg)
    overhead = (prem.year < ec.overhead_before_year) & (prem.ptype == 0)
    groups = _groups(ctx, kva, overhead)
    tap_edge = np.array([gr["edge"] for gr in groups] + [f.edge for f in subs], dtype=np.int64)
    tap_s = np.array([gr["s"] for gr in groups] + [f.s for f in subs])
    sg = SplitGraph.build(roads, tap_edge, tap_s)
    grp_tap = sg.n_road + np.arange(len(groups))
    sub_tap = [sg.n_road + len(groups) + k for k in range(len(subs))]
    forest = grow(sg, sub_tap, grp_tap, "electric", ctx.seed)

    own_n = np.zeros(sg.n_nodes)
    own_p = np.zeros(sg.n_nodes)
    own_nr = np.zeros(sg.n_nodes)
    for k, gr in enumerate(groups):
        own_n[grp_tap[k]] = len(gr["members"])
        own_p[grp_tap[k]] = gr["kva_sum"]
        own_nr[grp_tap[k]] = 1.0 if gr.get("three_phase") else 0.0
    sub_n = subtree_sums(forest, own_n)
    sub_p = subtree_sums(forest, own_p)
    sub_nr = subtree_sums(forest, own_nr)
    design = coincidence(sub_n, ec.coincidence_floor) * sub_p

    # Feeder partition by design capacity.
    limit = ec.feeder_design_mva * 1000.0
    children: dict[int, list[int]] = {}
    for v in forest.order:
        p = forest.parent[v]
        if p >= 0:
            children.setdefault(int(p), []).append(int(v))
    rem_n, rem_p = own_n.copy(), own_p.copy()
    heads = set(int(s) for s in sub_tap)
    for v in forest.order[::-1]:
        v = int(v)
        kids = [c for c in children.get(v, []) if c not in heads]
        rem_n[v] = own_n[v] + sum(rem_n[c] for c in kids)
        rem_p[v] = own_p[v] + sum(rem_p[c] for c in kids)
        while coincidence(rem_n[v], ec.coincidence_floor) * rem_p[v] > limit and kids:
            c = max(kids, key=lambda c: (coincidence(rem_n[c], ec.coincidence_floor) * rem_p[c], -c))
            heads.add(c)
            kids.remove(c)
            rem_n[v] -= rem_n[c]
            rem_p[v] -= rem_p[c]
    feeder_head = np.full(sg.n_nodes, -1, dtype=np.int64)
    for v in forest.order:
        feeder_head[v] = v if v in heads else feeder_head[forest.parent[v]]
    sub_of = {int(t): k for k, t in enumerate(sub_tap)}
    root_of = forest.root
    feeder_name: dict[int, str] = {}
    counter: dict[int, int] = {}
    for v in forest.order:
        if v in heads and v not in feeder_name:
            k = sub_of[int(root_of[v])]
            counter[k] = counter.get(k, 0) + 1
            feeder_name[int(v)] = f"F{k + 1}-{counter[k]:02d}"

    # Placement, phases and conductors per kept piece (indexed by child node).
    placement: dict[int, str] = {}
    phases: dict[int, int] = {}
    cond: dict[int, object] = {}
    for v in forest.order:
        if forest.parent[v] < 0:
            continue
        piece = int(forest.parent_piece[v])
        e = int(sg.piece_edge[piece])
        cls = int(g.edge_class[e])
        cl = sg.centreline(piece)
        yr = int(ctx.year_at(cl[len(cl) // 2])[0])
        oh = yr < ec.overhead_before_year or (cls == ARTERIAL and yr < 2000)
        placement[v] = "overhead" if oh else "underground"
        three = sub_n[v] > 150 or sub_nr[v] > 0 or cls != LOCAL or \
            design[v] > 0.8 * conductor_kva(pick_conductor(1e9, ec.primary_kv, 1, placement[v]), ec.primary_kv, 1)
        phases[v] = 3 if three else 1
        cond[v] = pick_conductor(design[v], ec.primary_kv, phases[v], placement[v])
    for v in forest.order[::-1]:
        p = forest.parent[v]
        if p >= 0 and forest.parent[p] >= 0:
            if phases[v] == 3 and phases[p] == 1:
                phases[p] = 3
            cap_c = conductor_kva(cond[v], ec.primary_kv, phases[v])
            if conductor_kva(cond[p], ec.primary_kv, phases[p]) < cap_c:
                cond[p] = pick_conductor(cap_c, ec.primary_kv, phases[p], placement[p])
    # Phase letters for laterals, balanced per feeder.
    phase_letter: dict[int, str] = {}
    feeder_phase_load: dict[int, np.ndarray] = {}
    for v in forest.order:
        p = forest.parent[v]
        if p < 0:
            continue
        if phases[v] == 3:
            phase_letter[v] = "ABC"
        elif forest.parent[p] < 0 or phases.get(int(p), 3) == 3:
            fl = feeder_phase_load.setdefault(int(feeder_head[v]), np.zeros(3))
            k = int(np.argmin(fl))
            fl[k] += design[v]
            phase_letter[v] = "ABC"[k]
        else:
            phase_letter[v] = phase_letter[int(p)]

    net = Network("electric", "kW")
    spacing = ec.pole_spacing_m
    sub0 = subs[0]
    entry = ctx.exit_for(sub0.xy)
    src = net.add_node("electric-supply", "external_supply", entry,
                       label=f"Regional grid · {ec.transmission_kv:g} kV (off-map)")
    net.source_id, net.station_id = "electric-supply", "electric-station"
    station_nodes = []
    prev = src
    for k, f in enumerate(subs):
        sid = "electric-station" if k == 0 else f"electric-station-{k + 1}"
        mva = max(10.0, math.ceil(design[sub_tap[k]] / 1000.0 / 5.0) * 5.0 + 5.0)
        st = net.add_node(sid, "substation", f.xy, label=f.label, facilityId=f.id, ratingMVA=mva,
                          primaryKV=ec.transmission_kv, secondaryKV=ec.primary_kv)
        start = net.nodes[prev].xy
        path = facility_path(roads, start, f) if k else facility_path(roads, entry, f)
        net.add_edge("supply", prev, st, densify_polyline(path, 250.0), placement="overhead", tier="transmission",
                     voltageKV=ec.transmission_kv, conductor="795 kcmil ACSR (115 kV)")
        station_nodes.append(st)
        prev = st
    node_of: dict[int, int] = {}
    off_oh, off_ug = OFFSETS["electric_oh"], OFFSETS["electric_ug"]
    for k, t in enumerate(sub_tap):
        f = subs[k]
        ttop = None
        kids = children.get(int(t), [])
        if kids:
            ttop = placement[kids[0]]
        off = off_oh if ttop == "overhead" else off_ug
        node_of[t] = net.add_node(f"electric-J-T{t}", "junction", sg.point_at(int(f.edge), float(f.s), off),
                                  feeder=feeder_name[int(t)])
        net.add_edge("trunk", station_nodes[k], node_of[t], None, placement=ttop or "underground",
                     tier="primary_main", voltageKV=ec.primary_kv, phases=3, phase="ABC",
                     feeder=feeder_name[int(t)], conductor="1000 kcmil AL 15 kV XLPE (substation exit)",
                     capacityKVA=round(conductor_kva(pick_conductor(1e9, ec.primary_kv, 3, "underground"),
                                                     ec.primary_kv, 3), 1),
                     designKVA=round(float(design[t]), 1), customers=int(sub_n[t]))
        net.equipment.append({"id": f"RCL-{feeder_name[int(t)]}", "kind": "recloser", "xy": net.nodes[node_of[t]].xy,
                              "nodeId": net.nodes[node_of[t]].id, "feeder": feeder_name[int(t)]})
    for v in forest.order:
        p = int(forest.parent[v])
        if p < 0:
            continue
        piece = int(forest.parent_piece[v])
        oh = placement[v] == "overhead"
        pts = piece_points(sg, piece, off_oh if oh else off_ug, p, densify=spacing if oh else None)
        nid = f"electric-J-{v}" if v < sg.n_road else f"electric-T-{v}"
        fname = feeder_name[int(feeder_head[v])]
        node_of[v] = net.add_node(nid, "junction", pts[-1], feeder=fname)
        c = cond[v]
        tier = "primary_main" if phases[v] == 3 else "primary_lateral"
        net.add_edge("distribution", node_of[p], node_of[v], pts, placement=placement[v], tier=tier,
                     voltageKV=ec.primary_kv, phases=phases[v], phase=phase_letter[v], feeder=fname,
                     conductor=c.label, capacityKVA=round(conductor_kva(c, ec.primary_kv, phases[v]), 1),
                     designKVA=round(float(design[v]), 1), customers=int(sub_n[v]),
                     roadEdge=int(sg.piece_edge[piece]),
                     rOhmKm=c.r_ohm_km, xOhmKm=c.x_ohm_km)
        if v in heads and v not in sub_tap:
            net.equipment.append({"id": f"RCL-{fname}", "kind": "recloser", "xy": net.nodes[node_of[v]].xy,
                                  "nodeId": net.nodes[node_of[v]].id, "feeder": fname})
        if phases[v] == 1 and (phases.get(p, 3) == 3):
            net.equipment.append({"id": f"FUSE-{len(net.equipment):05d}", "kind": "fuse",
                                  "xy": pts[min(1, len(pts) - 1)], "edgeId": net.edges[-1].id, "feeder": fname})
    # Transformers and services.
    meter_e = prem.meter_point("electric")
    n_tx = 0
    for k, gr in enumerate(groups):
        t = int(grp_tap[k])
        m = gr["members"]
        three = bool(gr.get("three_phase"))
        rating = _rating(gr["design"], three, ec.transformer_kva_steps, ec.transformer_max_loading)
        e = gr["edge"]
        side = int(np.sign(prem.side[m].sum()) or 1)
        cls = int(g.edge_class[e])
        if gr["overhead"]:
            txy = sg.point_at(e, gr["s"], off_oh)
            kind_lbl, place = "Pole-mount transformer", "overhead"
        else:
            txy = sg.point_at(e, gr["s"], side * (ROW_WIDTH[cls] / 2 - 1.0))
            kind_lbl, place = "Pad-mount transformer", "underground"
        n_tx += 1
        fname = feeder_name[int(feeder_head[t])]
        ph = phase_letter.get(t, "A") if not three else "ABC"
        sec_kv = 0.208 if three else ec.secondary_v / 1000.0
        tx = net.add_node(f"electric-TX-{n_tx:05d}", "transformer", txy, label=kind_lbl, ratingKVA=rating,
                          primaryKV=ec.primary_kv, secondaryKV=sec_kv, phases=3 if three else 1, phase=ph,
                          feeder=fname, mount="pole" if gr["overhead"] else "pad", customers=len(m),
                          designKVA=round(gr["design"], 2),
                          loadingPct=round(100.0 * gr["design"] / rating, 1))
        net.add_edge("transformer", node_of[t], tx, None, placement=place, tier="transformer",
                     voltageKV=ec.primary_kv, secondaryVoltageKV=sec_kv, ratingKVA=rating, phases=3 if three else 1,
                     phase=ph, feeder=fname)
        for i in m:
            mid = net.add_node(meter_node_id("electric", prem.ids[i]), "meter", meter_e[i], premiseId=prem.ids[i],
                               servicePointId=service_point_id(prem.ids[i], "electric"), feeder=fname,
                               transformerId=net.nodes[tx].id, phase=ph)
            if gr["overhead"]:
                pts = np.array([txy, meter_e[i]])
            else:
                pts = np.array([txy, prem.row_xy[i], meter_e[i]])
            sec = SECONDARY[0 if kva[i] <= 40 else 1] if gr["overhead"] else SECONDARY[2 if kva[i] <= 50 else 3]
            net.add_edge("service", tx, mid, pts, placement=place, tier="service", voltageKV=sec_kv, phase=ph,
                         phases=3 if three else 1, conductor=sec.label, feeder=fname,
                         designKVA=round(float(kva[i]), 2))
    # Normally-open ties between adjacent feeders (one per feeder pair, shortest piece).
    best_tie: dict[tuple[str, str], int] = {}
    for k in loop_pieces(sg, forest):
        a, b = int(sg.piece_a[k]), int(sg.piece_b[k])
        if a not in node_of or b not in node_of:
            continue
        fa, fb = feeder_name[int(feeder_head[a])], feeder_name[int(feeder_head[b])]
        if fa == fb:
            continue
        key = (min(fa, fb), max(fa, fb))
        L = float(sg.piece_s1[k] - sg.piece_s0[k])
        if key not in best_tie or L < float(sg.piece_s1[best_tie[key]] - sg.piece_s0[best_tie[key]]):
            best_tie[key] = int(k)
    for key, k in sorted(best_tie.items()):
        a, b = int(sg.piece_a[k]), int(sg.piece_b[k])
        oh = placement.get(a, placement.get(b, "underground")) == "overhead"
        pts = piece_points(sg, k, off_oh if oh else off_ug, a, densify=spacing if oh else None)
        ei = add_loop_edge(net, node_of[a], node_of[b], pts, enabled=False, normally_open=True,
                           placement="overhead" if oh else
                            "underground", tier="primary_main", voltageKV=ec.primary_kv, phases=3, phase="ABC",
                            switch="tie", feeders=list(key))
        net.equipment.append({"id": f"TIE-{key[0]}-{key[1]}", "kind": "tie_switch", "xy": pts[len(pts) // 2],
                              "edgeId": net.edges[ei].id, "normally": "open", "feeders": list(key)})
    # Poles along overhead primary (deduplicated).
    seen: set[tuple[int, int]] = set()
    n_pole = 0
    for e in net.edges:
        if e.placement != "overhead" or e.kind in ("service", "transformer", "supply"):
            continue
        for p in e.points:
            key = (int(round(p[0] * 2)), int(round(p[1] * 2)))
            if key in seen:
                continue
            seen.add(key)
            n_pole += 1
            net.equipment.append({"id": f"POLE-{n_pole:05d}", "kind": "pole", "xy": p, "edgeId": e.id,
                                  "heightM": 12.2})
    feeders = []
    for v in sorted(heads, key=lambda h: feeder_name[int(h)]):
        fname = feeder_name[int(v)]
        feeders.append({"id": fname, "substationId": subs[sub_of[int(root_of[v])]].id,
                        "headNodeId": net.nodes[node_of[int(v)]].id,
                        "customers": int(sum(own_n[u] for u in forest.order if feeder_head[u] == v)),
                        "designKVA": round(float(coincidence(rem_n[v], ec.coincidence_floor) * rem_p[v]), 1)})
    net.meta.update({"feeders": feeders, "substations": len(subs), "transformers": n_tx, "poles": n_pole,
                     "primaryKV": ec.primary_kv, "transmissionKV": ec.transmission_kv,
                     "townDesignKVA": round(float(sum(design[t] for t in sub_tap)), 1),
                     "ties": len(best_tie)})
    return net
