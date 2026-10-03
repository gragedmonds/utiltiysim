"""Geometry helpers shared by every stage.

Engine axes: x east, y north, metres, in a local plane anchored at ``origin`` (lat, lon). The viewer/snapshot
uses Astra's convention x east, **z south**; ``to_viewer`` flips y → -z. Projection is the same equirectangular
formula the Studio's model.js uses, so coordinates match the viewer exactly.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import LineString

M_PER_DEG_LAT = 111_320.0
QUANTUM = 0.01  # 1 cm grid at stage boundaries


def project(lat, lon, origin_lat: float, origin_lon: float):
    """Lat/lon → local metres (x east, y north). Vectorised."""
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    k = M_PER_DEG_LAT * math.cos(math.radians(origin_lat))
    return (lon - origin_lon) * k, (lat - origin_lat) * M_PER_DEG_LAT


def unproject(x, y, origin_lat: float, origin_lon: float):
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    k = M_PER_DEG_LAT * math.cos(math.radians(origin_lat))
    return y / M_PER_DEG_LAT + origin_lat, x / k + origin_lon


def quantize(a, q: float = QUANTUM):
    return np.round(np.asarray(a, dtype=np.float64) / q) * q


def to_viewer_xz(x, y):
    """Engine (x east, y north) → viewer (x east, z south)."""
    return np.asarray(x, dtype=np.float64), -np.asarray(y, dtype=np.float64)


def polyline_length(pts: np.ndarray) -> float:
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 2:
        return 0.0
    return float(np.sum(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))))


def point_along(pts: np.ndarray, s: float) -> tuple[float, float, float]:
    """Point at arc length ``s`` along a polyline; returns (x, y, heading_rad)."""
    pts = np.asarray(pts, dtype=np.float64)
    seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    s = min(max(s, 0.0), total)
    i = int(np.searchsorted(cum, s, side="right") - 1)
    i = min(max(i, 0), len(seg) - 1)
    t = 0.0 if seg[i] == 0 else (s - cum[i]) / seg[i]
    p = pts[i] + (pts[i + 1] - pts[i]) * t
    heading = math.atan2(pts[i + 1, 1] - pts[i, 1], pts[i + 1, 0] - pts[i, 0])
    return float(p[0]), float(p[1]), heading


def offset_polyline(pts: np.ndarray, distance: float) -> np.ndarray:
    """Parallel offset of a polyline (positive = left of travel direction). Falls back to a per-vertex normal
    offset when GEOS returns something unusable (very short lines)."""
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 2 or distance == 0:
        return pts.copy()
    try:
        off = shapely.offset_curve(LineString(pts), distance, join_style="mitre", mitre_limit=2.0)
        if off.geom_type == "LineString" and len(off.coords) >= 2:
            out = np.asarray(off.coords, dtype=np.float64)
            # GEOS may reverse direction for negative offsets; keep the input orientation.
            if np.hypot(*(out[0] - pts[0])) > np.hypot(*(out[-1] - pts[0])):
                out = out[::-1]
            return out
    except Exception:  # pragma: no cover - defensive
        pass
    d = np.diff(pts, axis=0)
    n = np.column_stack([-d[:, 1], d[:, 0]])
    n /= np.maximum(np.hypot(n[:, 0], n[:, 1]), 1e-9)[:, None]
    vn = np.vstack([n[:1], (n[1:] + n[:-1]) / 2.0, n[-1:]])
    vn /= np.maximum(np.hypot(vn[:, 0], vn[:, 1]), 1e-9)[:, None]
    return pts + vn * distance


def bbox(pts: np.ndarray) -> tuple[float, float, float, float]:
    pts = np.asarray(pts, dtype=np.float64)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def canonical_order(bounds: np.ndarray, lengths: np.ndarray | None = None) -> np.ndarray:
    """Stable ordering of geometries by (minx, miny, maxx, maxy[, length]) — never trust GEOS output order."""
    cols = [quantize(bounds[:, i]) for i in range(4)]
    if lengths is not None:
        cols.append(quantize(lengths))
    return np.lexsort(tuple(reversed(cols)))
