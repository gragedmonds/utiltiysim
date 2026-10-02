"""Array-based planar graph and rooted-tree utilities.

``PlanarGraph`` stores nodes (x, y), undirected edges (u, v) with lengths, a class code per edge and the edge
polyline geometry. ``Tree`` is a rooted forest over a graph (parent / parent_edge / depth arrays) with
vectorised bottom-up aggregation and top-down propagation, which is what every utility network, flow solve and
trace query needs. Dijkstra is scipy's; ties are broken deterministically by callers via tiny cost perturbations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra


@dataclass
class PlanarGraph:
    xy: np.ndarray  # (N, 2) float64
    uv: np.ndarray  # (E, 2) int32, u < v not required but edges are undirected
    length: np.ndarray  # (E,) float64
    edge_class: np.ndarray  # (E,) int8 (meaning defined by the producer)
    geometry: list[np.ndarray] = field(default_factory=list)  # per edge, (k, 2) polyline from u to v
    node_attr: dict[str, np.ndarray] = field(default_factory=dict)
    edge_attr: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def n_nodes(self) -> int:
        return int(self.xy.shape[0])

    @property
    def n_edges(self) -> int:
        return int(self.uv.shape[0])

    def adjacency(self, weights: np.ndarray | None = None) -> csr_matrix:
        w = self.length if weights is None else np.asarray(weights, dtype=np.float64)
        n = self.n_nodes
        rows = np.concatenate([self.uv[:, 0], self.uv[:, 1]])
        cols = np.concatenate([self.uv[:, 1], self.uv[:, 0]])
        data = np.concatenate([w, w])
        return coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr()

    def degree(self) -> np.ndarray:
        return np.bincount(self.uv.ravel(), minlength=self.n_nodes)

    def components(self) -> tuple[int, np.ndarray]:
        n, labels = connected_components(self.adjacency(), directed=False)
        return int(n), labels

    def incident_edges(self) -> list[np.ndarray]:
        """Edge indices incident to each node (lists sorted ascending for determinism)."""
        order = np.argsort(self.uv.ravel(), kind="stable")
        ends = np.repeat(np.arange(self.n_edges), 2)[order]
        counts = np.bincount(self.uv.ravel(), minlength=self.n_nodes)
        splits = np.cumsum(counts)[:-1]
        return [np.sort(a) for a in np.split(ends, splits)]

    def edge_lookup(self) -> dict[tuple[int, int], int]:
        return {(int(min(u, v)), int(max(u, v))): i for i, (u, v) in enumerate(self.uv)}

    def shortest_path_forest(self, sources: np.ndarray, weights: np.ndarray | None = None) -> Tree:
        """Multi-source Dijkstra → rooted forest; each node is attached to its nearest source."""
        sources = np.asarray(sources, dtype=np.int64)
        adj = self.adjacency(weights)
        dist, pred, src = dijkstra(adj, directed=False, indices=sources, return_predecessors=True, min_only=True)
        parent = np.where(pred < 0, -1, pred).astype(np.int64)
        parent[sources] = -1
        lookup = self.edge_lookup()
        parent_edge = np.full(self.n_nodes, -1, dtype=np.int64)
        for i in np.flatnonzero(parent >= 0):
            parent_edge[i] = lookup[(int(min(i, parent[i])), int(max(i, parent[i])))]
        return Tree.from_parents(parent, parent_edge, dist, src.astype(np.int64))


@dataclass
class Tree:
    """Rooted forest: parent[i] == -1 for roots and unreachable nodes (reachable flag distinguishes them)."""

    parent: np.ndarray
    parent_edge: np.ndarray
    depth: np.ndarray
    order: np.ndarray  # nodes sorted by depth (BFS-like), deterministic
    levels: list[np.ndarray]  # order split by depth
    dist: np.ndarray
    source: np.ndarray  # root index for each node (-1 if unreachable)

    @staticmethod
    def from_parents(parent: np.ndarray, parent_edge: np.ndarray, dist: np.ndarray | None = None,
                     source: np.ndarray | None = None) -> Tree:
        n = parent.shape[0]
        reachable = np.isfinite(dist) if dist is not None else np.ones(n, dtype=bool)
        depth = np.full(n, -1, dtype=np.int64)
        roots = np.flatnonzero((parent < 0) & reachable)
        depth[roots] = 0
        children = [[] for _ in range(n)]
        for i in np.flatnonzero(parent >= 0):
            children[parent[i]].append(int(i))
        frontier = list(map(int, roots))
        levels = []
        while frontier:
            levels.append(np.asarray(sorted(frontier), dtype=np.int64))
            nxt = []
            for p in frontier:
                for c in children[p]:
                    depth[c] = depth[p] + 1
                    nxt.append(c)
            frontier = nxt
        order = np.concatenate(levels) if levels else np.zeros(0, dtype=np.int64)
        if dist is None:
            dist = np.where(depth >= 0, 0.0, np.inf)
        if source is None:
            source = np.full(n, -1, dtype=np.int64)
            for lvl in levels:
                for i in lvl:
                    source[i] = i if parent[i] < 0 else source[parent[i]]
        return Tree(parent, parent_edge, depth, order, levels, dist, source)

    @property
    def n_nodes(self) -> int:
        return int(self.parent.shape[0])

    @property
    def roots(self) -> np.ndarray:
        return np.flatnonzero((self.parent < 0) & (self.depth == 0))

    def aggregate_up(self, values: np.ndarray) -> np.ndarray:
        """Subtree sums: out[i] = values[i] + Σ out[children]. Vectorised per depth level."""
        acc = np.array(values, dtype=np.float64, copy=True)
        for lvl in reversed(self.levels[1:]):
            np.add.at(acc, self.parent[lvl], acc[lvl])
        return acc

    def aggregate_up_max(self, values: np.ndarray) -> np.ndarray:
        acc = np.array(values, dtype=np.float64, copy=True)
        for lvl in reversed(self.levels[1:]):
            np.maximum.at(acc, self.parent[lvl], acc[lvl])
        return acc

    def propagate_down(self, root_values: np.ndarray, edge_delta: np.ndarray) -> np.ndarray:
        """out[root] = root_values[root]; out[child] = out[parent] - edge_delta[child] (per-node delta)."""
        out = np.array(root_values, dtype=np.float64, copy=True)
        for lvl in self.levels[1:]:
            out[lvl] = out[self.parent[lvl]] - edge_delta[lvl]
        return out

    def subtree_mask(self, node: int) -> np.ndarray:
        mask = np.zeros(self.n_nodes, dtype=bool)
        mask[node] = True
        for lvl in self.levels[1:]:
            mask[lvl] |= mask[self.parent[lvl]]
        return mask

    def path_to_root(self, node: int) -> list[int]:
        path = [int(node)]
        while self.parent[path[-1]] >= 0:
            path.append(int(self.parent[path[-1]]))
            if len(path) > self.n_nodes:
                raise RuntimeError("cycle in tree")
        return path

    def keep_mask_for(self, served: np.ndarray) -> np.ndarray:
        """Nodes on any root→served path (used to prune utility trees to what actually serves customers)."""
        keep = np.zeros(self.n_nodes, dtype=bool)
        keep[np.asarray(served, dtype=np.int64)] = True
        for lvl in reversed(self.levels[1:]):
            np.logical_or.at(keep, self.parent[lvl], keep[lvl])
        return keep
