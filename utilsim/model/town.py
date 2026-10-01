"""The generated town: everything downstream of (config, generator version)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from utilsim.config.model import SimConfig
from utilsim.gen.landuse import LandUse
from utilsim.gen.roads.build import Geography
from utilsim.model.network import Network
from utilsim.model.premises import Premises


@dataclass
class Town:
    cfg: SimConfig
    geo: Geography
    lu: LandUse
    prem: Premises
    networks: dict[str, Network]
    customers: object | None = None
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.cfg.town_id()

    @property
    def bounds(self):
        return self.lu.bounds

    @property
    def roads(self):
        return self.lu.roads

    @property
    def lot_polys(self):
        return [np.asarray(p.exterior.coords) for p in self.prem.lot]

    @property
    def footprints(self):
        return [np.asarray(p.exterior.coords) for p in self.prem.footprint if p.geom_type == "Polygon"]
