"""Instantaneous flows on the radial networks (the prototype's semantics, vectorised).

Each meter node carries its premise's demand; every parent-forest edge carries the signed sum of everything
downstream of it (positive = from → to). Loop edges are not solved by this radial aggregation: an enabled loop edge
reports NaN (exported as ``null`` = unavailable) and a disabled one reports 0. The looped hydraulic and power-flow
solves arrive in M2 behind the same interface."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from utilsim.sim.demand import hourly, july_daily


@dataclass
class FlowResult:
    source: dict[str, float]
    edge_flows: dict[str, np.ndarray]  # per commodity, aligned with network.edges
    homes: dict[str, np.ndarray]
    unit: dict[str, str]


class FlowModel:
    def __init__(self, town):
        self.town = town
        self.daily = july_daily(town.prem, town.cfg)
        self.index = {pid: i for i, pid in enumerate(town.prem.ids)}
        self._topo = {}
        for u, net in town.networks.items():
            n = len(net.nodes)
            parent = np.full(n, -1, dtype=np.int64)
            pe = np.full(n, -1, dtype=np.int64)
            for k, e in enumerate(net.edges):
                if e.loop:
                    continue
                parent[e.b] = e.a
                pe[e.b] = k
            depth = np.zeros(n, dtype=np.int64)
            # BFS order from the source.
            children: dict[int, list[int]] = {}
            for v in range(n):
                if parent[v] >= 0:
                    children.setdefault(int(parent[v]), []).append(v)
            src = net.index(net.source_id)
            bfs, frontier = [], [src]
            while frontier:
                bfs.extend(frontier)
                nxt = []
                for v in frontier:
                    for c in children.get(v, []):
                        depth[c] = depth[v] + 1
                        nxt.append(c)
                frontier = nxt
            order = np.array(bfs, dtype=np.int64)
            levels = [order[depth[order] == d] for d in range(int(depth[order].max()) + 1)] if len(order) else []
            meter = np.array([self.index.get(nd.attrs.get("premiseId"), -1) if nd.kind == "meter" else -1
                              for nd in net.nodes])
            loop_val = np.array([np.nan if e.enabled else 0.0 for e in net.edges if e.loop])
            loop_idx = np.array([k for k, e in enumerate(net.edges) if e.loop], dtype=np.int64)
            self._topo[u] = (parent, pe, levels, meter, src, loop_idx, loop_val)

    def flows(self, hour: float, scenario: str = "normal", target: str | None = None) -> FlowResult:
        prem = self.town.prem
        ti = self.index.get(target) if target else None
        d = hourly(self.daily, prem.attrs["occupied"], prem.attrs["has_gas"], hour, scenario, ti,
                   self.town.cfg.scenario.leak_m3h)
        source, edge_flows, unit = {}, {}, {}
        for u, net in self.town.networks.items():
            parent, pe, levels, meter, src, loop_idx, loop_val = self._topo[u]
            tot = np.zeros(len(net.nodes))
            m = meter >= 0
            tot[m] = d[u][meter[m]]
            for lvl in reversed(levels[1:]):
                np.add.at(tot, parent[lvl], tot[lvl])
            ef = np.zeros(len(net.edges))
            ef[pe[pe >= 0]] = tot[np.flatnonzero(pe >= 0)]
            if len(loop_idx):
                ef[loop_idx] = loop_val
            source[u] = float(tot[src])
            edge_flows[u] = ef
            unit[u] = net.unit
        return FlowResult(source, edge_flows, d, unit)
