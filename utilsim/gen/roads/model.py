"""Road model shared by all skeleton sources."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from utilsim.core.graph import PlanarGraph

ARTERIAL, COLLECTOR, LOCAL = 0, 1, 2
CLASS_NAMES = ("arterial", "collector", "local")
# Right-of-way and pavement widths by class (m).
ROW_WIDTH = np.array([30.0, 22.0, 18.0])
PAVEMENT_WIDTH = np.array([14.0, 10.0, 8.0])
# Astra/OSM highway tags the viewer understands, per class (for the 1.0-compatible ``class`` field).
OSM_TAG_FOR_CLASS = ("primary", "tertiary", "residential")


@dataclass
class RoadLine:
    """A polyline with attributes before planarization (engine coords: x east, y north)."""

    points: np.ndarray
    cls: int
    name: str = ""
    origin: str = "synthetic"  # "osm" | "synthetic" | "connector"
    source_id: str = ""
    bulb_at_end: bool = False  # cul-de-sac bulb at the last point
    bulb_at_start: bool = False


@dataclass
class RoadNetwork:
    graph: PlanarGraph
    names: list[str]
    origin: list[str]
    source_id: list[str]
    bulb_radius: np.ndarray  # per node, 0 if none
    osm_tag: list[str] = field(default_factory=list)
    dropped_edges: int = 0

    @property
    def edge_class(self) -> np.ndarray:
        return self.graph.edge_class

    def summary(self) -> dict:
        g = self.graph
        return {
            "nodes": g.n_nodes,
            "edges": g.n_edges,
            "length_km": round(float(g.length.sum()) / 1000.0, 3),
            "by_class_km": {CLASS_NAMES[c]: round(float(g.length[g.edge_class == c].sum()) / 1000, 3)
                            for c in range(3)},
            "components": g.components()[0],
            "dead_ends": int((g.degree() == 1).sum()),
            "dropped_edges": self.dropped_edges,
        }
