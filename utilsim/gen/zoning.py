"""Districts and construction era.

Era is a smooth function of distance from the town centre plus per-district noise:
``era = core + span · (d / R)^1.2 + N(0, σ)``. It is defined everywhere before streets exist, because the era decides
the street template, lot sizes, overhead vs underground electric, the legacy low-pressure gas core, cast-iron water
mains and solar/EV uptake. Districts are Voronoi cells of seeded district centres (≈ 900 houses each)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from utilsim.core.rng import Purpose, hash_normal, hash_u01, stage_rng

ERA_PRE1945, ERA_POSTWAR, ERA_MODERN = 0, 1, 2
ERA_NAMES = ("pre_1945", "postwar", "modern")


def era_bucket(year) -> np.ndarray:
    y = np.asarray(year)
    return np.where(y < 1945, ERA_PRE1945, np.where(y < 1979, ERA_POSTWAR, ERA_MODERN)).astype(np.int8)


@dataclass
class EraField:
    seed: str
    center: tuple[float, float]
    radius: float
    core_year: float
    span_years: float
    noise_years: float
    district_xy: np.ndarray  # (K, 2)
    district_noise: np.ndarray  # (K,) years
    district_all_electric: np.ndarray  # (K,) bool
    _tree: cKDTree | None = None

    @property
    def tree(self) -> cKDTree:
        if self._tree is None:
            self._tree = cKDTree(self.district_xy)
        return self._tree

    def district_of(self, xy: np.ndarray) -> np.ndarray:
        xy = np.atleast_2d(np.asarray(xy, dtype=np.float64))
        return self.tree.query(xy)[1].astype(np.int64)

    def year_at(self, xy: np.ndarray) -> np.ndarray:
        xy = np.atleast_2d(np.asarray(xy, dtype=np.float64))
        d = np.hypot(xy[:, 0] - self.center[0], xy[:, 1] - self.center[1])
        base = self.core_year + self.span_years * np.clip(d / max(self.radius, 1.0), 0, 1.6) ** 1.2
        y = base + self.district_noise[self.district_of(xy)]
        return np.clip(np.round(y), 1850, 2025).astype(np.int64)

    def era_at(self, xy: np.ndarray) -> np.ndarray:
        return era_bucket(self.year_at(xy))


def district_grid(extent: tuple[float, float, float, float], houses: int) -> tuple[np.ndarray, np.ndarray, float]:
    """The grid district centres are jittered from: one per ≈ 900 houses' worth of area, at least 350 m apart.
    The seed only jitters the centres, so the district count follows from the extent and the house count alone."""
    minx, miny, maxx, maxy = extent
    area = (maxx - minx) * (maxy - miny)
    k_target = max(1, int(round(houses / 900.0)))
    spacing = max(350.0, float(np.sqrt(area / max(k_target, 1))))
    return np.arange(minx + spacing / 2, maxx, spacing), np.arange(miny + spacing / 2, maxy, spacing), spacing


def build_era_field(seed: str, center: tuple[float, float], radius: float, extent: tuple[float, float, float, float],
                    houses: int, core_year: float, span_years: float, noise_years: float,
                    all_electric_share: float, gas_scheme_lp_before: int | None = None) -> EraField:
    """District centres by jittered-grid sampling over the extent, one per ≈ 900 houses' worth of area."""
    xs, ys, spacing = district_grid(extent, houses)
    rng = stage_rng(seed, "zoning", "districts")
    gx, gy = np.meshgrid(xs, ys)
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    pts = pts + rng.uniform(-0.3, 0.3, size=pts.shape) * spacing
    if len(pts) == 0:
        pts = np.array([[center[0], center[1]]])
    k = len(pts)
    idx = np.arange(k)
    noise = hash_normal(seed, Purpose.ERA_NOISE, idx) * noise_years
    # All-electric districts by hash rank, the core district (closest to centre) last: it keeps gas unless the share is 1.
    d = np.hypot(pts[:, 0] - center[0], pts[:, 1] - center[1])
    u = hash_u01(seed, Purpose.DISTRICT_STYLE, idx)
    u[np.argmin(d)] = 2.0
    n_ae = int(round(all_electric_share * k)) if k > 1 else 0
    all_electric = np.zeros(k, dtype=bool)
    if n_ae:
        all_electric[np.argsort(u, kind="stable")[:n_ae]] = True
    return EraField(seed, center, radius, core_year, span_years, noise_years, pts, noise, all_electric)
