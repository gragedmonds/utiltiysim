"""Seeded terrain: multi-octave value noise on an integer lattice anchored at the world origin.

The lattice is keyed by (seed, octave, ix, iy) through ``hash_u01`` so elevation at a world point never depends on
the town extent, house count or evaluation order. Elevations are synthetic (not surveyed)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from utilsim.core.rng import Purpose, hash_u01


@dataclass(frozen=True)
class Terrain:
    seed: str
    relief_m: float = 15.0
    wavelength_m: float = 900.0
    base_m: float = 90.0
    octaves: int = 3

    def elevation(self, x, y) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        total = np.zeros(np.broadcast_shapes(x.shape, y.shape))
        amp_sum = 0.0
        for k in range(self.octaves):
            lam = self.wavelength_m / (2.0**k)
            amp = 0.5**k
            gx, gy = x / lam, y / lam
            ix, iy = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
            fx, fy = gx - ix, gy - iy
            sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
            v00 = hash_u01(self.seed, Purpose.TERRAIN, k, ix, iy)
            v10 = hash_u01(self.seed, Purpose.TERRAIN, k, ix + 1, iy)
            v01 = hash_u01(self.seed, Purpose.TERRAIN, k, ix, iy + 1)
            v11 = hash_u01(self.seed, Purpose.TERRAIN, k, ix + 1, iy + 1)
            v = (v00 * (1 - sx) + v10 * sx) * (1 - sy) + (v01 * (1 - sx) + v11 * sx) * sy
            total = total + amp * v
            amp_sum += amp
        v = total / amp_sum
        return np.round(self.base_m + self.relief_m * (v - 0.5) * 1.8, 3)

    def heightmap(self, minx: float, miny: float, maxx: float, maxy: float, max_cells: int = 256) -> dict:
        """Regular grid for the viewer. Rows run north→south so row 0 is the viewer's minimum z."""
        span = max(maxx - minx, maxy - miny)
        cell = max(5.0, float(np.ceil(span / max_cells / 5.0) * 5.0))
        cols = int(np.ceil((maxx - minx) / cell)) + 1
        rows = int(np.ceil((maxy - miny) / cell)) + 1
        xs = minx + np.arange(cols) * cell
        ys = maxy - np.arange(rows) * cell  # north to south
        gx, gy = np.meshgrid(xs, ys)
        z = self.elevation(gx, gy)
        return {"cols": cols, "rows": rows, "cellSizeM": cell, "originX": round(float(minx), 3),
                "originY": round(float(maxy), 3), "values": np.round(z, 2)}
