"""Premises table (struct of arrays). One premise per building in M1, matching the prototype."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon

PREMISE_TYPES = ("residential", "commercial", "institutional", "industrial", "utility")


@dataclass
class Premises:
    ids: list[str]
    uid: list[str]
    ptype: np.ndarray  # index into PREMISE_TYPES
    building_type: list[str]
    xy: np.ndarray  # building centre (engine coords)
    footprint: list[Polygon]
    width: np.ndarray  # along the street
    depth: np.ndarray  # perpendicular to the street
    height: np.ndarray
    stories: np.ndarray
    roof: list[str]
    heading: np.ndarray  # street direction (radians, engine frame) used to orient the building
    normal: np.ndarray  # unit vector street -> building
    edge: np.ndarray  # frontage road edge
    s: np.ndarray  # arc length of the frontage point along the edge centreline
    side: np.ndarray  # +1 left / -1 right of edge direction
    front_xy: np.ndarray  # frontage point on the street centreline
    row_xy: np.ndarray  # property-line point (service point)
    lot: list[Polygon]
    lot_area: np.ndarray
    year: np.ndarray
    era: np.ndarray
    district: np.ndarray
    facility_id: list[str | None]
    street: list[str]
    number: np.ndarray
    attrs: dict[str, np.ndarray] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.ids)

    @property
    def residential(self) -> np.ndarray:
        return self.ptype == 0

    def meter_point(self, commodity: str) -> np.ndarray:
        """Electric/gas meters on the front wall corner on the driveway side; water meter box at the property line."""
        t = np.column_stack([np.cos(self.heading), np.sin(self.heading)])
        if commodity == "water":
            return self.row_xy + self.normal * 1.5 + t * 2.0
        sgn = 1.0 if commodity == "electric" else -1.0
        front = self.xy - self.normal * (self.depth / 2)[:, None]
        return front + t * (sgn * (self.width / 2 - 1.0))[:, None] - self.normal * 0.4
