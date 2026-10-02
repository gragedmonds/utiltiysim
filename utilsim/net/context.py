"""Inputs shared by every network builder."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np

from utilsim.config.model import SimConfig
from utilsim.gen.landuse import Facility, LandUse
from utilsim.gen.terrain import Terrain
from utilsim.gen.zoning import EraField
from utilsim.model.premises import Premises


@dataclass
class NetContext:
    cfg: SimConfig
    lu: LandUse
    prem: Premises
    terrain: Terrain
    era: EraField
    seed: str

    @property
    def roads(self):
        return self.lu.roads

    @cached_property
    def corridors(self):
        """Arterial/collector corridors and street sides of the town's roads (shared by every network)."""
        from utilsim.net.corridors import extract_corridors

        t = self.cfg.town
        return extract_corridors(self.roads, t.corridor_max_deflection_deg, t.corridor_name_bonus_deg)

    def facilities(self, kind: str) -> list[Facility]:
        return [f for f in self.lu.facilities if f.kind == kind]

    def exit_for(self, xy: np.ndarray, prefer_class: int = 0) -> np.ndarray:
        """Map-edge point where an off-map supply enters, nearest the facility (arterials preferred)."""
        ex = self.lu.exits
        if ex:
            cands = [e for e in ex if e["cls"] == prefer_class] or ex
            best = min(cands, key=lambda e: float(np.hypot(*(e["xy"] - xy))))
            return best["xy"].copy()
        minx, miny, maxx, maxy = self.lu.bounds
        x, y = xy
        d = [x - minx, maxx - x, y - miny, maxy - y]
        k = int(np.argmin(d))
        return np.array([[minx, y], [maxx, y], [x, miny], [x, maxy]][k], dtype=float)

    def year_at(self, xy) -> np.ndarray:
        return self.era.year_at(np.atleast_2d(xy))
