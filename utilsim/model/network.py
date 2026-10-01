"""Utility network container: a rooted tree of nodes and edges (from = parent side, to = child side), plus loop
closures represented as edges to ``closed_tie`` nodes (coincident with another node) so the tree contract that the
prototype viewer relies on (``edges = nodes - 1``, one parent edge per node) holds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from utilsim.core.graph import Tree


@dataclass
class Node:
    id: str
    kind: str
    xy: np.ndarray
    attrs: dict[str, Any] = field(default_factory=dict)
    parent_edge: int = -1


@dataclass
class Edge:
    id: str
    kind: str
    a: int  # parent node index
    b: int  # child node index
    points: np.ndarray
    placement: str = "underground"
    tier: str = "distribution"
    size_mm: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> float:
        p = self.points
        return float(np.sum(np.hypot(np.diff(p[:, 0]), np.diff(p[:, 1])))) if len(p) > 1 else 0.0


@dataclass
class Network:
    commodity: str
    unit: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    source_id: str = ""
    station_id: str = ""
    equipment: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    _index: dict[str, int] = field(default_factory=dict)

    def add_node(self, id: str, kind: str, xy, **attrs) -> int:
        if id in self._index:
            raise ValueError(f"duplicate node id {id}")
        self.nodes.append(Node(id, kind, np.asarray(xy, dtype=np.float64), attrs))
        self._index[id] = len(self.nodes) - 1
        return len(self.nodes) - 1

    def add_edge(self, kind: str, a: int, b: int, points=None, **kw) -> int:
        if self.nodes[b].parent_edge >= 0:
            raise ValueError(f"node {self.nodes[b].id} already has a parent edge")
        pts = np.asarray(points if points is not None else [self.nodes[a].xy, self.nodes[b].xy], dtype=np.float64)
        pts[0], pts[-1] = self.nodes[a].xy, self.nodes[b].xy
        attrs = kw.pop("attrs", {})
        known = {k: kw.pop(k) for k in ("placement", "tier", "size_mm") if k in kw}
        attrs.update(kw)
        e = Edge(f"{self.commodity}-E{len(self.edges)}", kind, a, b, pts, attrs=attrs, **known)
        self.edges.append(e)
        self.nodes[b].parent_edge = len(self.edges) - 1
        return len(self.edges) - 1

    def index(self, id: str) -> int:
        return self._index[id]

    def tree(self) -> Tree:
        n = len(self.nodes)
        parent = np.full(n, -1, dtype=np.int64)
        pe = np.full(n, -1, dtype=np.int64)
        for i, e in enumerate(self.edges):
            parent[e.b] = e.a
            pe[e.b] = i
        return Tree.from_parents(parent, pe)

    def kinds(self) -> np.ndarray:
        return np.array([nd.kind for nd in self.nodes])
