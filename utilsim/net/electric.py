"""Electric distribution: off-map transmission → substation(s) (in-and-out 115 kV backbone) → 3φ feeder trunks along
road corridors → laterals → distribution transformers (pole-mount in overhead districts, pad-mount underground) →
120/240 V services → meters.

Backbone first (docs/CORRIDOR_ROUTING_REQUIREMENTS.md):

1. Arterial/collector corridors are extracted from the road graph (``net/corridors.py``).
2. A turn-aware preference tree from each substation assigns transformer groups to substations; each substation's
   demand is carved into feeder *territories* of about equal connected load (at least ``min_feeders_per_substation``,
   more for capacity or customer count), cutting preferably where a branch leaves a corridor.
3. Each feeder's trunk is routed from the substation exit with the edge-state router (length × class weight + turn
   + corridor-change + hierarchy penalties) to the corridor points where its territory's demand leaves the
   corridors, farthest first, each further branch starting from the trunk built so far. Where a trunk runs through
   another feeder's territory it is an *express* section (no taps, its own conductor on a shared pole line or duct
   bank), so every feeder is a separate circuit from the substation bus.
4. Laterals attach every transformer group to the nearest trunk (one multi-source run of the same router), which
   fixes the final territories. Branch nodes are trunk nodes: laterals leave at junctions or continue past a trunk end.
5. Normally-open tie switches join neighbouring feeders on a street piece between them (preferring three-phase ends);
   a feeder that touches no other gets a short new tie line. Ties are disabled as built, so operation stays radial.
Reclosers at feeder heads, fuses at single-phase lateral taps, poles along overhead lines."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

from utilsim.core.ids import meter_node_id, service_point_id
from utilsim.gen.roads.model import ARTERIAL, COLLECTOR, LOCAL, ROW_WIDTH
from utilsim.model.network import Network
from utilsim.net.common import (
    OFFSETS,
    SplitGraph,
    add_loop_edge,
    densify_polyline,
    facility_path,
    piece_points,
)
from utilsim.net.context import NetContext
from utilsim.net.corridors import Corridors, RouteCosts, TurnRouter
from utilsim.net.tables import SECONDARY, THREE_PHASE_KVA, coincidence, conductor_kva, pick_conductor
from utilsim.sim.demand import design_kva

EXPRESS_LANE_M = 1.5  # an express circuit runs this much further out than the line it parallels, per lane
MAX_TRUNK_PATHS = 48  # trunk branches routed per feeder (the rest of its demand is reached by laterals)


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


# ------------------------------------------------------------------------------------------------ feeder layout
@dataclass
class Layout:
    """Feeder forest over split-graph nodes plus express copies. Virtual node ids: the split node id for a node a
    feeder owns (trunk, lateral or head), ``n_split + k`` for an express copy of a split node."""

    n_split: int
    real: list[int]
    parent: list[int]
    piece: list[int]
    arrive: list[int]  # router state the node is reached on (-1 at heads)
    role: list[str]  # head | trunk | express | lateral | "" (not in the network)
    feeder: list[int]
    lane: list[int]
    heads: list[int] = field(default_factory=list)
    feeder_sub: list[int] = field(default_factory=list)
    feeder_name: list[str] = field(default_factory=list)
    order: list[int] = field(default_factory=list)

    @classmethod
    def empty(cls, n: int) -> Layout:
        return cls(n, list(range(n)), [-1] * n, [-1] * n, [-1] * n, [""] * n, [-1] * n, [0] * n)

    def copy_of(self, u: int, feeder: int, lane: int) -> int:
        for lst, v in ((self.real, u), (self.parent, -1), (self.piece, -1), (self.arrive, -1),
                       (self.role, "express"), (self.feeder, feeder), (self.lane, lane)):
            lst.append(v)
        return len(self.real) - 1


def _carve(nodes: list[int], par: np.ndarray, w: np.ndarray, K: int, corr_node: np.ndarray
           ) -> tuple[list[tuple[int, float]], float]:
    """Up to K-1 subtree heads splitting one substation's tree (``nodes`` in parent-before-child order, root first)
    into territories of about equal connected load. A head is preferably where a branch leaves an arterial or
    collector, and no cut leaves the territory it splits with less than half a share."""
    root = nodes[0]
    target = float(w[nodes].sum()) / K
    cut: list[int] = []
    cutset: set[int] = set()

    def remainders() -> tuple[dict[int, float], dict[int, int]]:
        rem = {v: float(w[v]) for v in nodes}
        for v in reversed(nodes):
            p = int(par[v])
            if p >= 0 and v not in cutset:
                rem[p] += rem[v]
        terr = {}
        for v in nodes:
            terr[v] = v if (v == root or v in cutset) else terr[int(par[v])]
        return rem, terr

    for _ in range(K - 1):
        rem, terr = remainders()
        best, best_key = None, None
        for v in nodes[1:]:
            if v in cutset or rem[v] <= 0 or rem[terr[v]] - rem[v] < 0.5 * target:
                continue
            key = (round(abs(rem[v] - target) / target + (0.0 if corr_node[int(par[v])] else 0.25), 9), v)
            if best_key is None or key < best_key:
                best, best_key = v, key
        if best is None:
            break
        cut.append(best)
        cutset.add(best)
    rem, _ = remainders()
    return [(v, rem[v]) for v in cut], rem[root]


def _starts(router: TurnRouter, L: Layout, nodes: dict[int, int], tkids: dict[int, set[int]],
            scale: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    """Start states for routing from existing trunk nodes. A trunk end continues with the full turn penalty; an
    interior trunk node branches (the hierarchy step is still priced); the head leaves the substation freely."""
    base = router.base if scale is None else router.base * scale
    st, cost = [], []
    for u in sorted(nodes):
        v = nodes[u]
        used = set(tkids.get(v, ()))
        if L.piece[v] >= 0:
            used.add(L.piece[v])
        outs = np.array([o for o in router.outgoing(u) if int(o) >> 1 not in used], dtype=np.int64)
        if not len(outs):
            continue
        a = L.arrive[v]
        c = base[outs]
        if a >= 0:
            aa = np.full(len(outs), a)
            c = c + (router.transition(aa, outs) if not tkids.get(v) else
                     router.transition(aa, outs, turn=False, corridor=False))
        st.append(outs)
        cost.append(c)
    if not st:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    return np.concatenate(st), np.concatenate(cost)


def _drop_loops(path: list[int], states: list[int]) -> tuple[list[int], list[int]]:
    """Remove any detour that returns to a node already on the path (path[i] is the tail of states[i])."""
    out_p, out_s = [path[0]], []
    pos = {path[0]: 0}
    for i in range(1, len(path)):
        u = path[i]
        if u in pos:
            k = pos[u]
            for x in out_p[k + 1:]:
                del pos[x]
            out_p, out_s = out_p[:k + 1], out_s[:k]
        else:
            out_s.append(states[i - 1])
            out_p.append(u)
            pos[u] = len(out_p) - 1
    return out_p, out_s


def plan_feeders(sg: SplitGraph, router: TurnRouter, grp_tap: np.ndarray, own_n: np.ndarray, own_p: np.ndarray,
                 sub_tap: list[int], ec) -> Layout:
    g = sg.roads.graph
    n = sg.n_nodes
    tail, head = router.tail, router.head
    corr_piece = np.asarray(g.edge_class)[sg.piece_edge] <= COLLECTOR
    corr_node = np.zeros(n, dtype=bool)
    corr_node[sg.piece_a[corr_piece]] = True
    corr_node[sg.piece_b[corr_piece]] = True
    grp_tap = np.asarray(grp_tap, dtype=np.int64)

    # 1. Turn-aware preference tree from every substation exit.
    starts = np.concatenate([router.outgoing(t) for t in sub_tap])
    dist, _ = router.run(starts, router.base[starts])
    nd, ns = router.best_arrivals(dist)
    par = np.where(ns >= 0, tail[np.maximum(ns, 0)], -1)
    par[sub_tap] = -1
    miss = grp_tap[~np.isfinite(nd[grp_tap])]
    if len(miss):
        raise RuntimeError(f"electric: {len(miss)} transformer groups are not reachable from any substation")
    keep = np.zeros(n, dtype=bool)
    keep[sub_tap] = True
    for x in grp_tap:
        x = int(x)
        while x >= 0 and not keep[x]:
            keep[x] = True
            x = int(par[x])
    kids: dict[int, list[int]] = {}
    for v in np.flatnonzero(keep & (par >= 0)):
        kids.setdefault(int(par[v]), []).append(int(v))
    per_sub: list[list[int]] = []
    for t in sub_tap:
        order, stack = [], [t]
        while stack:
            nxt = []
            for v in stack:
                order.append(v)
                nxt.extend(sorted(kids.get(v, [])))
            stack = nxt
        per_sub.append(order)

    # 2. Feeder territories per substation (the substation's own territory first).
    L = Layout.empty(n)
    terr = np.full(n, -1, dtype=np.int64)
    head_split: list[int] = []
    limit = ec.feeder_design_mva * 1000.0
    for s, nodes in enumerate(per_sub):
        cust = float(own_n[nodes].sum())
        load = float(coincidence(cust, ec.coincidence_floor) * own_p[nodes].sum())
        K = max(ec.min_feeders_per_substation, math.ceil(load / limit - 1e-9),
                math.ceil(cust / ec.feeder_max_customers - 1e-9))
        K = max(1, min(K, int(np.count_nonzero(own_n[nodes] > 0))))
        cuts, _ = _carve(nodes, par, own_p, K, corr_node)
        heads = [nodes[0]] + [v for v, _ in sorted(cuts, key=lambda c: (-round(c[1], 6), c[0]))]
        fid = {}
        for k, h in enumerate(heads):
            fid[h] = len(L.feeder_name)
            L.feeder_name.append(f"F{s + 1}-{k + 1:02d}")
            L.feeder_sub.append(s)
            head_split.append(h)
        for v in nodes:
            terr[v] = fid[v] if v in fid else terr[int(par[v])]
    F = len(L.feeder_name)

    # Trunk terminals: where each group's supply leaves the corridors (walking up the preference tree), within
    # its territory; the territory head when no corridor is reached first. A terminal is a trunk target while at
    # least ``trunk_min_load_share`` of its feeder's connected load lies at or beyond it (smaller tails are laterals).
    memo: dict[int, int] = {}
    access = np.zeros(n)
    cand: list[set[int]] = [set() for _ in head_split]
    for x0 in grp_tap:
        f = int(terr[int(x0)])
        x, path = int(x0), []
        while x not in memo and not corr_node[x] and x != head_split[f]:
            path.append(x)
            x = int(par[x])
        t = memo.get(x, x)
        for y in path:
            memo[y] = t
        memo[x] = t
        cand[f].add(t)
        access[t] += own_p[int(x0)]
    beyond = access.copy()
    terr_load = np.zeros(F)
    for nodes in per_sub:
        for v in reversed(nodes):
            p = int(par[v])
            terr_load[terr[v]] += own_p[v]
            if p >= 0 and terr[p] == terr[v]:
                beyond[p] += beyond[v]
    terminals = [{h} | {t for t in cand[f] if beyond[t] >= ec.trunk_min_load_share * terr_load[f]}
                 for f, h in enumerate(head_split)]

    # 3. Trunks, feeder by feeder, farthest terminal first.
    owner = np.full(n, -1, dtype=np.int64)
    copies = np.zeros(n, dtype=np.int64)
    tkids: dict[int, set[int]] = {}

    def place(u: int, f: int) -> int:
        if owner[u] < 0 and terr[u] in (f, -1):
            owner[u] = f
            L.role[u], L.feeder[u] = "trunk", f
            return u
        copies[u] += 1
        return L.copy_of(u, f, int(copies[u]))

    for f in range(F):
        t = sub_tap[L.feeder_sub[f]]
        hv = place(t, f)
        L.role[hv] = "head"
        L.heads.append(hv)
        nodes_f = {t: hv}
        ok = ((terr == f) | (terr < 0)) & ((owner < 0) | (owner == f))
        scale = np.where(ok[head], 1.0, ec.route_shared_trunk_factor)
        todo = set(terminals[f]) - set(nodes_f)
        for _ in range(MAX_TRUNK_PATHS):
            if not todo:
                break
            st, c = _starts(router, L, nodes_f, tkids, scale)
            if not len(st):
                break
            dist, pred = router.run(st, c, scale)
            ndf, nsf = router.best_arrivals(dist)
            reach = [x for x in todo if np.isfinite(ndf[x])]
            if not reach:
                break
            x = max(reach, key=lambda x: (round(float(ndf[x]), 9), -x))
            states = router.path(pred, int(nsf[x]))
            path = [int(tail[states[0]])] + [int(head[q]) for q in states]
            j = max(i for i, u in enumerate(path) if u in nodes_f)
            path, states = _drop_loops(path[j:], states[j:])
            prev = nodes_f[path[0]]
            for u, q in zip(path[1:], states):
                v = place(u, f)
                L.parent[v], L.piece[v], L.arrive[v] = prev, q >> 1, q
                tkids.setdefault(prev, set()).add(q >> 1)
                nodes_f[u] = v
                prev = v
            todo -= set(nodes_f)

    # 4. Laterals: every transformer group to the nearest owned trunk node (any feeder).
    own_trunk = {u: u for u in range(n) if owner[u] >= 0}
    st, c = _starts(router, L, own_trunk, tkids, None)
    dist, _ = router.run(st, c)
    _, nsl = router.best_arrivals(dist)
    for x0 in grp_tap:
        x = int(x0)
        while owner[x] < 0 and L.role[x] == "":
            q = int(nsl[x])
            if q < 0:
                raise RuntimeError("electric: a transformer group cannot reach any feeder trunk")
            L.role[x], L.parent[x], L.piece[x], L.arrive[x] = "lateral", int(tail[q]), q >> 1, q
            x = int(tail[q])

    # 5. Parent-before-child order, feeder by feeder; laterals inherit the feeder of the trunk they hang from.
    ch: dict[int, list[int]] = {}
    for v in range(len(L.real)):
        if L.role[v] in ("trunk", "express", "lateral"):
            ch.setdefault(L.parent[v], []).append(v)
    for hv in L.heads:
        stack = [hv]
        while stack:
            nxt = []
            for v in stack:
                if L.role[v] == "lateral":
                    L.feeder[v] = L.feeder[L.parent[v]]
                L.order.append(v)
                nxt.extend(sorted(ch.get(v, [])))
            stack = nxt
    return L


def _edge_placement(ctx: NetContext, g) -> list[str]:
    """Overhead or underground per road edge, so construction changes only at junctions: districts built before
    ``overhead_before_year`` are overhead, arterials before 2000. A street is as old as the older side it serves
    (main roads often bound districts of different eras; the line along them predates the newer side)."""
    ec = ctx.cfg.electric
    mids, normals = [], []
    for pts in g.geometry:
        pts = np.asarray(pts, dtype=np.float64)
        seg = np.hypot(*np.diff(pts, axis=0).T)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        s = 0.5 * cum[-1]
        m = np.array([np.interp(s, cum, pts[:, 0]), np.interp(s, cum, pts[:, 1])])
        a = np.array([np.interp(max(0.0, s - 2), cum, pts[:, 0]), np.interp(max(0.0, s - 2), cum, pts[:, 1])])
        b = np.array([np.interp(min(cum[-1], s + 2), cum, pts[:, 0]), np.interp(min(cum[-1], s + 2), cum, pts[:, 1])])
        d = b - a
        nrm = np.array([-d[1], d[0]]) / max(float(np.hypot(*d)), 1e-9)
        mids.append(m)
        normals.append(nrm)
    mids, normals = np.array(mids).reshape(-1, 2), np.array(normals).reshape(-1, 2)
    reach = (ROW_WIDTH[np.asarray(g.edge_class)] / 2 + 15.0)[:, None]
    yr = np.min([ctx.year_at(mids), ctx.year_at(mids + normals * reach), ctx.year_at(mids - normals * reach)], axis=0)
    cls = np.asarray(g.edge_class)
    oh = (yr < ec.overhead_before_year) | ((cls == ARTERIAL) & (yr < 2000))
    return ["overhead" if x else "underground" for x in oh]


def _sums(order: list[int], parent: list[int], values: np.ndarray) -> np.ndarray:
    acc = np.array(values, dtype=np.float64, copy=True)
    for v in reversed(order):
        p = parent[v]
        if p >= 0:
            acc[p] += acc[v]
    return acc


# ------------------------------------------------------------------------------------------------------- build
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
    corridors = ctx.corridors
    sg = SplitGraph.build(roads, tap_edge, tap_s, corridors.side)
    grp_tap = sg.n_road + np.arange(len(groups))
    sub_tap = [sg.n_road + len(groups) + k for k in range(len(subs))]
    router = TurnRouter(sg, corridors, RouteCosts.from_config(ec))

    own_n = np.zeros(sg.n_nodes)
    own_p = np.zeros(sg.n_nodes)
    own_nr = np.zeros(sg.n_nodes)
    for k, gr in enumerate(groups):
        own_n[grp_tap[k]] = len(gr["members"])
        own_p[grp_tap[k]] = gr["kva_sum"]
        own_nr[grp_tap[k]] = 1.0 if gr.get("three_phase") else 0.0
    L = plan_feeders(sg, router, grp_tap, own_n, own_p, sub_tap, ec)
    N = len(L.real)
    pad = np.zeros(N - sg.n_nodes)
    own_n, own_p, own_nr = (np.concatenate([a, pad]) for a in (own_n, own_p, own_nr))
    order, parent = L.order, L.parent
    sub_n = _sums(order, parent, own_n)
    sub_p = _sums(order, parent, own_p)
    sub_nr = _sums(order, parent, own_nr)
    design = coincidence(sub_n, ec.coincidence_floor) * sub_p
    fname_of = L.feeder_name
    head_of = L.heads

    # Placement, phases and conductors per kept piece (indexed by child node).
    placement: dict[int, str] = {}
    phases: dict[int, int] = {}
    cond: dict[int, object] = {}
    circuits: dict[int, int] = {}

    def sized(v: int, need: float) -> tuple[object, int]:
        """Conductor and parallel circuits for a piece that must carry ``need`` kVA: one cable when one is enough,
        else the largest cable in parallel."""
        c = pick_conductor(need, ec.primary_kv, phases[v], placement[v])
        return c, max(1, math.ceil(need / conductor_kva(c, ec.primary_kv, phases[v]) - 1e-9))

    edge_place = _edge_placement(ctx, g)
    for v in order:
        if parent[v] < 0:
            continue
        piece = L.piece[v]
        e = int(sg.piece_edge[piece])
        cls = int(g.edge_class[e])
        placement[v] = edge_place[e]
        if L.role[v] in ("trunk", "express"):
            phases[v] = 3  # the backbone is three-phase and sized for its whole feeder (back-feed through ties)
            need = max(float(design[v]), float(design[head_of[L.feeder[v]]]))
        else:
            three = sub_n[v] > 150 or sub_nr[v] > 0 or cls != LOCAL or \
                design[v] > 0.8 * conductor_kva(pick_conductor(1e9, ec.primary_kv, 1, placement[v]), ec.primary_kv, 1)
            phases[v] = 3 if three else 1
            need = float(design[v])
        cond[v], circuits[v] = sized(v, need)
    for v in order[::-1]:
        p = parent[v]
        if p >= 0 and parent[p] >= 0:
            if phases[v] == 3 and phases[p] == 1:
                phases[p] = 3
            cap_c = conductor_kva(cond[v], ec.primary_kv, phases[v]) * circuits[v]
            if conductor_kva(cond[p], ec.primary_kv, phases[p]) * circuits[p] < cap_c:
                cond[p], circuits[p] = sized(p, cap_c)
    # Phase letters for laterals, balanced per feeder.
    phase_letter: dict[int, str] = {}
    feeder_phase_load: dict[int, np.ndarray] = {}
    for v in order:
        p = parent[v]
        if p < 0:
            continue
        if phases[v] == 3:
            phase_letter[v] = "ABC"
        elif parent[p] < 0 or phases.get(p, 3) == 3:
            fl = feeder_phase_load.setdefault(L.feeder[v], np.zeros(3))
            k = int(np.argmin(fl))
            fl[k] += design[v]
            phase_letter[v] = "ABC"[k]
        else:
            phase_letter[v] = phase_letter[p]

    net = Network("electric", "kW")
    spacing = ec.pole_spacing_m
    sub0 = subs[0]
    entry = ctx.exit_for(sub0.xy)
    src = net.add_node("electric-supply", "external_supply", entry,
                       label=f"Regional grid · {ec.transmission_kv:g} kV (off-map)")
    net.source_id, net.station_id = "electric-supply", "electric-station"
    station_nodes = []
    sub_designs = []
    prev = src
    for k, f in enumerate(subs):
        sid = "electric-station" if k == 0 else f"electric-station-{k + 1}"
        mine = [h for fi, h in enumerate(head_of) if L.feeder_sub[fi] == k]
        sub_design = float(coincidence(sum(sub_n[h] for h in mine), ec.coincidence_floor) * sum(sub_p[h] for h in mine))
        sub_designs.append(sub_design)
        mva = max(10.0, math.ceil(sub_design / 1000.0 / 5.0) * 5.0 + 5.0)
        st = net.add_node(sid, "substation", f.xy, label=f.label, facilityId=f.id, ratingMVA=mva,
                          primaryKV=ec.transmission_kv, secondaryKV=ec.primary_kv, feeders=len(mine),
                          designKVA=round(sub_design, 1))
        start = net.nodes[prev].xy
        path = facility_path(roads, start, f) if k else facility_path(roads, entry, f)
        net.add_edge("supply", prev, st, densify_polyline(path, 250.0), placement="overhead", tier="transmission",
                     voltageKV=ec.transmission_kv, conductor="795 kcmil ACSR (115 kV)", designRole="supply")
        station_nodes.append(st)
        prev = st

    off_oh, off_ug = OFFSETS["electric_oh"], OFFSETS["electric_ug"]
    first_child: dict[int, int] = {}
    for v in order:
        if parent[v] >= 0 and parent[v] not in first_child:
            first_child[parent[v]] = v

    def offset(v: int, place: str) -> float:
        base = off_oh if place == "overhead" else off_ug
        return base + math.copysign(EXPRESS_LANE_M * L.lane[v], base)

    def corridor_attr(e: int) -> dict:
        cid = corridors.id_of(e)
        return {"corridorId": cid} if cid else {}

    node_of: dict[int, int] = {}
    edge_of: dict[int, int] = {}  # virtual node -> its parent edge index
    pole_pts: dict[int, np.ndarray] = {}  # edge index -> where its poles stand (express lines share structures)
    for fi, hv in enumerate(head_of):
        k = L.feeder_sub[fi]
        f, t, fname = subs[k], sub_tap[k], fname_of[fi]
        ttop = placement.get(first_child.get(hv, -1), "underground")
        nid = f"electric-J-T{t}" if hv == t else f"electric-J-T{t}-{fname}"
        xy = sg.street_point(int(f.edge), float(f.s), offset(hv, ttop))
        node_of[hv] = net.add_node(nid, "junction", xy,
                                   feeder=fname)
        # The exit is the feeder's getaway cable: parallel cables when one cannot carry its load.
        cable_kva = conductor_kva(pick_conductor(1e9, ec.primary_kv, 3, "underground"), ec.primary_kv, 3)
        n_cab = max(1, math.ceil(float(design[hv]) / cable_kva - 1e-9))
        getaway = {"conductor": "1000 kcmil AL 15 kV XLPE (substation exit)"} if n_cab == 1 else \
            {"conductor": f"{n_cab} × 1000 kcmil AL 15 kV XLPE (substation getaway duct bank)",
             "parallelCables": n_cab}
        net.add_edge("trunk", station_nodes[k], node_of[hv], None, placement=ttop, tier="primary_main",
                     voltageKV=ec.primary_kv, phases=3, phase="ABC", feeder=fname, feederId=fname,
                     designRole="getaway", **getaway, capacityKVA=round(cable_kva * n_cab, 1),
                     designKVA=round(float(design[hv]), 1), customers=int(sub_n[hv]))
        net.equipment.append({"id": f"RCL-{fname}", "kind": "recloser", "xy": net.nodes[node_of[hv]].xy,
                              "nodeId": net.nodes[node_of[hv]].id, "feeder": fname})
        placement[hv] = ttop
    n_riser = 0
    for v in order:
        p = parent[v]
        if p < 0:
            continue
        piece = L.piece[v]
        e = int(sg.piece_edge[piece])
        oh = placement[v] == "overhead"
        pts = piece_points(sg, piece, offset(v, placement[v]), L.real[p], densify=spacing if oh else None)
        fname = fname_of[L.feeder[v]]
        u = L.real[v]
        if L.role[v] == "express":
            nid = f"electric-X-{fname}-{u}"
        else:
            nid = f"electric-J-{u}" if u < sg.n_road else f"electric-T-{u}"
        node_of[v] = net.add_node(nid, "junction", pts[-1], feeder=fname)
        c, n_c = cond[v], circuits[v]
        tier = "primary_main" if phases[v] == 3 else "primary_lateral"
        cable = {"conductor": c.label} if n_c == 1 else \
            {"conductor": f"{n_c} × {c.label} ({'multi-circuit pole line' if oh else 'shared feeder duct bank'})",
             "parallelCables": n_c}
        net.add_edge("distribution", node_of[p], node_of[v], pts, placement=placement[v], tier=tier,
                     voltageKV=ec.primary_kv, phases=phases[v], phase=phase_letter[v], feeder=fname, feederId=fname,
                     designRole=L.role[v], **corridor_attr(e), **cable,
                     capacityKVA=round(conductor_kva(c, ec.primary_kv, phases[v]) * n_c, 1),
                     designKVA=round(float(design[v]), 1), customers=int(sub_n[v]), roadEdge=e,
                     rOhmKm=c.r_ohm_km if n_c == 1 else round(c.r_ohm_km / n_c, 4),
                     xOhmKm=c.x_ohm_km if n_c == 1 else round(c.x_ohm_km / n_c, 4))
        edge_of[v] = len(net.edges) - 1
        if oh and L.lane[v]:
            pole_pts[edge_of[v]] = piece_points(sg, piece, off_oh, L.real[p], densify=spacing)
        if phases[v] == 1 and (phases.get(p, 3) == 3):
            net.equipment.append({"id": f"FUSE-{len(net.equipment):05d}", "kind": "fuse",
                                  "xy": pts[min(1, len(pts) - 1)], "edgeId": net.edges[-1].id, "feeder": fname})
        if placement[p] != placement[v]:  # overhead ↔ underground at a riser pole (cable terminations)
            n_riser += 1
            net.equipment.append({"id": f"RISER-{n_riser:05d}", "kind": "riser", "xy": net.nodes[node_of[p]].xy,
                                  "nodeId": net.nodes[node_of[p]].id, "edgeId": net.edges[-1].id, "feeder": fname,
                                  "from": placement[p], "to": placement[v]})
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
            txy = sg.street_point(e, gr["s"], off_oh)
            kind_lbl, place = "Pole-mount transformer", "overhead"
        else:
            txy = sg.point_at(e, gr["s"], side * (ROW_WIDTH[cls] / 2 - 1.0))
            kind_lbl, place = "Pad-mount transformer", "underground"
        n_tx += 1
        fname = fname_of[L.feeder[t]]
        ph = phase_letter.get(t, "A") if not three else "ABC"
        sec_kv = 0.208 if three else ec.secondary_v / 1000.0
        tx = net.add_node(f"electric-TX-{n_tx:05d}", "transformer", txy, label=kind_lbl, ratingKVA=rating,
                          primaryKV=ec.primary_kv, secondaryKV=sec_kv, phases=3 if three else 1, phase=ph,
                          feeder=fname, mount="pole" if gr["overhead"] else "pad", customers=len(m),
                          designKVA=round(gr["design"], 2),
                          loadingPct=round(100.0 * gr["design"] / rating, 1))
        net.add_edge("transformer", node_of[t], tx, None, placement=place, tier="transformer",
                     voltageKV=ec.primary_kv, secondaryVoltageKV=sec_kv, ratingKVA=rating, phases=3 if three else 1,
                     phase=ph, feeder=fname, feederId=fname, designRole="transformer")
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
                         phases=3 if three else 1, conductor=sec.label, feeder=fname, feederId=fname,
                         designRole="service", designKVA=round(float(kva[i]), 2))
    ties = _ties(sg, L, corridors, phases, phase_letter, placement, ec)
    tie_ids: dict[int, list[str]] = {}
    for fa, fb, nodes, pcs, ph in ties:
        a, b = nodes[0], nodes[-1]
        oh = "overhead" in (placement.get(a), placement.get(b))
        off = off_oh if oh else off_ug
        pts = [piece_points(sg, k, off, x, densify=spacing if oh else None) for k, x in zip(pcs, nodes[:-1])]
        pts = np.vstack([pts[0]] + [q[1:] for q in pts[1:]])
        key = (fname_of[fa], fname_of[fb])
        n_same = sum(1 for x in tie_ids.get(fa, []) if x.startswith(f"TIE-{key[0]}-{key[1]}"))
        tid = f"TIE-{key[0]}-{key[1]}" + (f"-{n_same + 1}" if n_same else "")
        cids = {corridors.id_of(int(sg.piece_edge[k])) for k in pcs}
        extra = {"corridorId": cids.pop()} if len(cids) == 1 and None not in cids else {}
        if len(pcs) > 1:
            extra["newLine"] = True  # built only to tie this feeder: no other feeder touches it
        ei = add_loop_edge(net, node_of[a], node_of[b], pts, enabled=False, normally_open=True,
                           placement="overhead" if oh else "underground",
                           tier="primary_main" if len(ph) == 3 else "primary_lateral", voltageKV=ec.primary_kv,
                           phases=len(ph), phase=ph, switch="tie", switchId=tid, feeders=list(key),
                           designRole="tie", **extra)
        net.equipment.append({"id": tid, "kind": "tie_switch", "xy": pts[len(pts) // 2],
                              "edgeId": net.edges[ei].id, "normally": "open", "feeders": list(key)})
        tie_ids.setdefault(fa, []).append(tid)
        tie_ids.setdefault(fb, []).append(tid)
    # Poles along overhead primary (deduplicated; an express circuit hangs on the structures of the line it runs with).
    seen: set[tuple[int, int]] = set()
    n_pole = 0
    for k, e in enumerate(net.edges):
        if e.placement != "overhead" or e.kind in ("service", "transformer", "supply"):
            continue
        for p in pole_pts.get(k, e.points):
            key = (int(round(p[0] * 2)), int(round(p[1] * 2)))
            if key in seen:
                continue
            seen.add(key)
            n_pole += 1
            net.equipment.append({"id": f"POLE-{n_pole:05d}", "kind": "pole", "xy": p, "edgeId": e.id,
                                  "heightM": 12.2})
    # Feeder summaries, corridor usage and routing exceptions (trunk sections off the corridors, with the reason).
    trunk_km = np.zeros(len(head_of))
    express_km = np.zeros(len(head_of))
    corr_use: dict[int, dict] = {}
    for v, ei in edge_of.items():
        e = net.edges[ei]
        f = L.feeder[v]
        if L.role[v] in ("trunk", "express"):
            (trunk_km if L.role[v] == "trunk" else express_km)[f] += e.length / 1000.0
            ck = int(corridors.edge_corridor[int(e.attrs["roadEdge"])])
            if ck >= 0:
                u = corr_use.setdefault(ck, {"feeders": set(), "m": 0.0})
                u["feeders"].add(fname_of[f])
                u["m"] += e.length
    exceptions = _exceptions(L, sg, g, net, edge_of, fname_of)
    feeders = []
    for fi, hv in enumerate(head_of):
        fname = fname_of[fi]
        feeders.append({"id": fname, "substationId": subs[L.feeder_sub[fi]].id,
                        "headNodeId": net.nodes[node_of[hv]].id, "customers": int(sub_n[hv]),
                        "designKVA": round(float(design[hv]), 1), "trunkKm": round(float(trunk_km[fi]), 3),
                        "expressKm": round(float(express_km[fi]), 3),
                        "corridorIds": sorted(corridors.ids[k] for k, u in corr_use.items() if fname in u["feeders"]),
                        "tieIds": sorted(tie_ids.get(fi, []))})
    net.corridors = []
    for k, rec in enumerate(corridors.export()):
        u = corr_use.get(k)
        net.corridors.append({**rec, "feederIds": sorted(u["feeders"]) if u else [],
                              "trunkLengthM": round(u["m"], 2) if u else 0.0})
    c = RouteCosts.from_config(ec)
    net.meta.update({"feeders": feeders, "substations": len(subs), "transformers": n_tx, "poles": n_pole,
                     "primaryKV": ec.primary_kv, "transmissionKV": ec.transmission_kv,
                     "townDesignKVA": round(float(sum(sub_designs)), 1),
                     "ties": len(ties), "corridors": len(corridors.chains), "risers": n_riser,
                     "routing": {"algorithm": "edge-state Dijkstra (incoming piece), backbone first",
                                 "classWeights": dict(zip(("arterial", "collector", "local"), c.weights)),
                                 "turnPenaltyM": c.turn_m, "corridorChangePenaltyM": c.corridor_change_m,
                                 "hierarchyPenaltyM": c.hierarchy_m,
                                 "sharedTrunkFactor": ec.route_shared_trunk_factor},
                     "routingExceptions": exceptions})
    return net


def _ties(sg: SplitGraph, L: Layout, corridors: Corridors, phases: dict, phase_letter: dict, placement: dict, ec
          ) -> list[tuple[int, int, list[int], list[int], str]]:
    """Normally-open ties as (feeder a, feeder b, split nodes a…b, pieces, phase letters). Candidates are street
    pieces whose ends belong to different feeders, best first: both ends three-phase, then farthest along both
    feeders from their substation (a tie near the feeder ends can back-feed the most after a fault upstream), then
    shortest. A feeder that touches no other feeder gets the shortest new line (through streets no feeder serves)
    to the nearest one."""
    n = L.n_split
    fe = np.full(n, -1, dtype=np.int64)
    for v in L.order:
        if v < n:
            fe[v] = L.feeder[v]
    if len(L.heads) < 2 or ec.ties_per_feeder_pair <= 0:
        return []

    def letters(v: int) -> str:
        return "ABC" if L.parent[v] < 0 else phase_letter[v]

    def common(a: int, b: int) -> str:
        return "".join(x for x in "ABC" if x in letters(a) and x in letters(b))

    length = sg.piece_length()
    depth = np.zeros(len(L.real))
    for v in L.order:
        if L.parent[v] >= 0:
            depth[v] = depth[L.parent[v]] + length[L.piece[v]]
    cands: dict[tuple[int, int], list[tuple]] = {}
    for k in range(len(sg.piece_a)):
        a, b = int(sg.piece_a[k]), int(sg.piece_b[k])
        fa, fb = int(fe[a]), int(fe[b])
        if a == b or fa < 0 or fb < 0 or fa == fb:
            continue
        ph = common(a, b)
        if not ph:
            continue
        if fa > fb:
            a, b, fa, fb = b, a, fb, fa
        reach = -round(float(min(depth[a], depth[b])), -1)
        cands.setdefault((fa, fb), []).append((0 if len(ph) == 3 else 1, reach, round(float(length[k]), 3), k, a, b,
                                               ph))
    out = []
    for (fa, fb) in sorted(cands):
        for *_, k, a, b, ph in sorted(cands[(fa, fb)])[:ec.ties_per_feeder_pair]:
            out.append((fa, fb, [a, b], [k], ph))
    tied = {x for t in out for x in t[:2]}
    for f in range(len(L.heads)):
        if f in tied:
            continue
        hit = _tie_line(sg, fe, f, ec.tie_max_length_m, common)
        if hit is not None:
            nodes, pcs, ph = hit
            fa, fb = sorted((f, int(fe[nodes[-1]])))
            if fa != f:
                nodes, pcs = nodes[::-1], pcs[::-1]
            out.append((fa, fb, nodes, pcs, ph))
            tied.update((fa, fb))
    return out


def _tie_line(sg: SplitGraph, fe: np.ndarray, f: int, max_m: float, common):
    """Shortest new line from feeder f through unserved street pieces to another feeder's node."""
    n = len(fe)
    a, b = sg.piece_a.astype(np.int64), sg.piece_b.astype(np.int64)
    w = sg.piece_length()
    rows, cols, ws, pc = [], [], [], []
    for x, y in ((a, b), (b, a)):
        ok = ((fe[x] == f) | (fe[x] < 0)) & (fe[y] != f) & (x != y)
        rows.append(x[ok])
        cols.append(y[ok])
        ws.append(w[ok])
        pc.append(np.flatnonzero(ok))
    rows, cols, ws, pc = (np.concatenate(z) for z in (rows, cols, ws, pc))
    srcs = np.flatnonzero(fe == f)
    if not len(srcs) or not len(rows):
        return None
    o = np.lexsort((pc, ws, cols, rows))  # cheapest piece per (row, col)
    rows, cols, ws, pc = rows[o], cols[o], ws[o], pc[o]
    first = np.ones(len(rows), dtype=bool)
    first[1:] = (rows[1:] != rows[:-1]) | (cols[1:] != cols[:-1])
    rows, cols, ws, pc = rows[first], cols[first], ws[first], pc[first]
    piece_of = {(int(r), int(c)): int(k) for r, c, k in zip(rows, cols, pc)}
    m = coo_matrix((ws, (rows, cols)), shape=(n, n)).tocsr()
    dist, pred, _ = dijkstra(m, directed=True, indices=srcs, return_predecessors=True, min_only=True, limit=max_m)
    targets = [int(v) for v in np.flatnonzero(np.isfinite(dist) & (fe >= 0) & (fe != f))]
    targets.sort(key=lambda v: (round(float(dist[v]), 6), v))
    for t in targets:
        nodes = [t]
        while pred[nodes[-1]] >= 0:
            nodes.append(int(pred[nodes[-1]]))
        nodes.reverse()
        ph = common(nodes[0], nodes[-1])
        if ph:
            return nodes, [piece_of[(x, y)] for x, y in zip(nodes[:-1], nodes[1:])], ph
    return None


def _exceptions(L: Layout, sg: SplitGraph, g, net: Network, edge_of: dict[int, int], fname_of: list[str]
                ) -> list[dict]:
    """Trunk sections on local streets, per feeder and road, with why the backbone left the corridors."""
    corridor_below: dict[int, bool] = {}
    for v in reversed(L.order):
        if L.role[v] not in ("trunk", "express"):
            continue
        e = int(sg.piece_edge[L.piece[v]])
        here = int(g.edge_class[e]) <= COLLECTOR
        corridor_below[v] = corridor_below.get(v, False) or False
        p = L.parent[v]
        corridor_below[p] = corridor_below.get(p, False) or here or corridor_below[v]
    agg: dict[tuple[str, int], dict] = {}
    for v in L.order:
        if L.role[v] not in ("trunk", "express") or v not in edge_of:
            continue
        e = int(sg.piece_edge[L.piece[v]])
        if int(g.edge_class[e]) != LOCAL:
            continue
        key = (fname_of[L.feeder[v]], e)
        r = agg.setdefault(key, {"feederId": key[0], "roadId": f"R-{e}", "lengthM": 0.0, "edgeIds": [],
                                 "reason": "bridges corridors (no arterial/collector link)" if corridor_below[v]
                                 else "territory has no arterial/collector access"})
        r["lengthM"] += net.edges[edge_of[v]].length
        r["edgeIds"].append(net.edges[edge_of[v]].id)
    out = sorted(agg.values(), key=lambda r: (r["feederId"], r["roadId"]))
    for r in out:
        r["lengthM"] = round(r["lengthM"], 1)
    return out
