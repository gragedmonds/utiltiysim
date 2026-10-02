"""Instantaneous flows on the networks (the prototype's semantics, vectorised).

Each meter node carries its premise's demand; every forest edge carries the signed sum of everything downstream of it
(positive = from → to). Loop edges are not solved by this radial aggregation: an enabled loop edge reports NaN
(exported as ``null`` = unavailable) and a disabled one reports 0. The looped hydraulic and power-flow solves arrive
in M2 behind the same interface.

Switching and faults (``disabled`` edges, leak ``injections``) use a *repaired* forest: a 0-1 BFS from the sources
over enabled edges where each node's original parent edge costs 0 and any other enabled edge (loop, tie) costs 1,
ties broken by edge index. Unaffected parts keep their parents and signs; a loop or tie promoted into the forest
carries a number; enabled non-forest edges stay NaN; disabled edges and de-energised islands carry 0, and meters
that no source reaches draw nothing (``unsupplied``). With nothing extra disabled this is exactly the construction
forest. Pure numpy (no scipy/shapely), so it runs in the hosted engine."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from utilsim.sim.shapes import hourly

UTILITIES = ("electric", "water", "gas")


@dataclass
class NetInputs:
    n_nodes: int
    a: np.ndarray  # edge from-node index (supply side in the construction forest)
    b: np.ndarray  # edge to-node index
    loop: np.ndarray  # bool per edge
    enabled: np.ndarray  # bool per edge, as built (ties open, zone boundaries closed)
    meter: np.ndarray  # per node: premise index of a meter node, else -1
    sources: np.ndarray  # external supply node indices
    unit: str


@dataclass
class FlowInputs:
    nets: dict[str, NetInputs]
    daily: dict[str, np.ndarray]  # dailyKWh, dailyWaterM3, dailyGasM3, solarPeakKW per premise
    occupied: np.ndarray
    has_gas: np.ndarray
    premise_ids: list[str]
    leak_m3h: float

    @classmethod
    def from_town(cls, town) -> FlowInputs:
        from utilsim.sim.demand import july_daily

        index = {pid: i for i, pid in enumerate(town.prem.ids)}
        nets = {}
        for u, net in town.networks.items():
            nets[u] = NetInputs(
                n_nodes=len(net.nodes),
                a=np.array([e.a for e in net.edges], dtype=np.int64),
                b=np.array([e.b for e in net.edges], dtype=np.int64),
                loop=np.array([bool(e.loop) for e in net.edges]),
                enabled=np.array([bool(e.enabled) for e in net.edges]),
                meter=np.array([index.get(nd.attrs.get("premiseId"), -1) if nd.kind == "meter" else -1
                                for nd in net.nodes], dtype=np.int64),
                sources=np.array([i for i, nd in enumerate(net.nodes) if nd.kind == "external_supply"],
                                 dtype=np.int64),
                unit=net.unit)
        return cls(nets, july_daily(town.prem, town.cfg), np.asarray(town.prem.attrs["occupied"], dtype=bool),
                   np.asarray(town.prem.attrs["has_gas"], dtype=bool), list(town.prem.ids), town.cfg.scenario.leak_m3h)


@dataclass
class FlowResult:
    source: dict[str, float]
    edge_flows: dict[str, np.ndarray]  # per commodity, aligned with network.edges
    homes: dict[str, np.ndarray]
    unit: dict[str, str]
    unsupplied: dict[str, np.ndarray] | None = None  # per commodity, bool per premise (no source reaches its meter)


@dataclass
class _Forest:
    parent: np.ndarray  # parent node per node (-1 for sources / unreached)
    pedge: np.ndarray  # parent edge per node (-1)
    sign: np.ndarray  # +1 if the parent edge runs parent → child (a → b), -1 if reversed
    levels: list[np.ndarray]  # nodes by depth, sources first
    reached: np.ndarray  # bool per node
    in_forest: np.ndarray  # bool per edge


class FlowModel:
    def __init__(self, town_or_inputs):
        inp = town_or_inputs if isinstance(town_or_inputs, FlowInputs) else FlowInputs.from_town(town_or_inputs)
        self.inputs = inp
        self.daily = inp.daily
        self.index = {pid: i for i, pid in enumerate(inp.premise_ids)}
        self._adj: dict[str, list[list[tuple[int, int]]]] = {}
        self._orig_pe: dict[str, np.ndarray] = {}
        self._cache: dict[tuple[str, bytes], _Forest] = {}
        for u, net in inp.nets.items():
            adj: list[list[tuple[int, int]]] = [[] for _ in range(net.n_nodes)]
            for k in range(len(net.a)):
                a, b = int(net.a[k]), int(net.b[k])
                adj[a].append((k, b))
                adj[b].append((k, a))
            self._adj[u] = adj
            pe = np.full(net.n_nodes, -1, dtype=np.int64)
            tree = ~net.loop
            pe[net.b[tree]] = np.flatnonzero(tree)
            self._orig_pe[u] = pe

    # ---- topology --------------------------------------------------------------------------------------------
    def forest(self, u: str, disabled: np.ndarray | None = None) -> _Forest:
        """Repaired forest for a disabled-edge mask (``None`` = as built). Cached per mask."""
        net = self.inputs.nets[u]
        off = ~net.enabled if disabled is None else (~net.enabled | disabled)
        key = (u, np.packbits(off).tobytes())
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        n, orig = net.n_nodes, self._orig_pe[u]
        dist = np.full(n, np.iinfo(np.int64).max, dtype=np.int64)
        parent = np.full(n, -1, dtype=np.int64)
        pedge = np.full(n, -1, dtype=np.int64)
        dq = deque()
        for s in sorted(int(x) for x in net.sources):
            dist[s] = 0
            dq.append(s)
        adj = self._adj[u]
        while dq:
            v = dq.popleft()
            dv = dist[v]
            for k, w in adj[v]:
                if off[k]:
                    continue
                cost = 0 if orig[w] == k and int(net.a[k]) == v else 1
                nd = dv + cost
                if nd < dist[w]:
                    dist[w], parent[w], pedge[w] = nd, v, k
                    if cost == 0:
                        dq.appendleft(w)
                    else:
                        dq.append(w)
        reached = dist < np.iinfo(np.int64).max
        # Depth levels for vectorised aggregation (BFS over the chosen parent pointers).
        children: dict[int, list[int]] = {}
        for v in np.flatnonzero(parent >= 0):
            children.setdefault(int(parent[v]), []).append(int(v))
        levels, frontier = [], sorted(int(x) for x in net.sources)
        while frontier:
            levels.append(np.array(frontier, dtype=np.int64))
            frontier = [c for v in frontier for c in children.get(v, [])]
        sign = np.ones(n)
        has = pedge >= 0
        sign[has] = np.where(net.a[pedge[has]] == parent[has], 1.0, -1.0)
        in_forest = np.zeros(len(net.a), dtype=bool)
        in_forest[pedge[has]] = True
        f = _Forest(parent, pedge, sign, levels, reached, in_forest)
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[key] = f
        return f

    # ---- flows -----------------------------------------------------------------------------------------------
    def flows(self, hour: float, scenario: str = "normal", target: str | None = None, *,
              disabled: dict[str, np.ndarray] | None = None,
              injections: dict[str, dict[int, float]] | None = None,
              premises_off: dict[str, np.ndarray] | None = None) -> FlowResult:
        """``premises_off`` (bool per premise) takes premises off a commodity although the network reaches them
        (e.g. gas meters shut until relit)."""
        inp = self.inputs
        ti = self.index.get(target) if target else None
        d = hourly(self.daily, inp.occupied, inp.has_gas, hour, scenario, ti, inp.leak_m3h)
        source, edge_flows, unit, unsupplied = {}, {}, {}, {}
        homes = dict(d)
        for u, net in inp.nets.items():
            f = self.forest(u, None if disabled is None else disabled.get(u))
            off = ~net.enabled if disabled is None or u not in disabled else (~net.enabled | disabled[u])
            dead_meter = (net.meter >= 0) & ~f.reached
            lost = np.zeros(len(inp.premise_ids), dtype=bool)
            lost[net.meter[dead_meter]] = True
            if premises_off is not None and u in premises_off:
                lost |= premises_off[u]
            if lost.any():
                homes[u] = np.where(lost, 0.0, homes[u])
            unsupplied[u] = lost
            tot = np.zeros(net.n_nodes)
            m = net.meter >= 0
            tot[m] = homes[u][net.meter[m]]
            for node, q in (injections or {}).get(u, {}).items():
                if f.reached[node]:
                    tot[node] += q
            for lvl in reversed(f.levels[1:]):
                np.add.at(tot, f.parent[lvl], tot[lvl])
            ef = np.full(len(net.a), np.nan)
            ef[off] = 0.0
            kids = np.flatnonzero(f.pedge >= 0)
            ef[f.pedge[kids]] = tot[kids] * f.sign[kids]
            # Edges with both ends unreached carry nothing (a dead island), even if their switch is closed.
            dead = ~f.reached[net.a] & ~f.reached[net.b]
            ef[dead] = 0.0
            source[u] = float(sum(tot[int(s)] for s in net.sources))
            edge_flows[u] = ef
            unit[u] = net.unit
        return FlowResult(source, edge_flows, homes, unit, unsupplied)
