"""Meter-reading rounds on the operations day.

Walked routes: the reader parks at the route's first premise and walks every meter in sequence order, pausing at
each one, then walks back to the van. Drive-by (AMR) routes: the van drives the route past every few premises,
reading radio endpoints within range. Paths come from the road graph; the times are seconds from the round's start.
"""

from __future__ import annotations

import numpy as np

from utilsim.ops.routing import Route, Router, access_point

DRIVE_BY_STRIDE = 4  # a drive-by van passes every 4th premise; endpoints in range are read on the way


def stops(ops, mru_id: str) -> list[int]:
    rows = [i for i, p in enumerate(ops.premises) if p.get("mruId") == mru_id]
    return sorted(rows, key=lambda i: (ops.premises[i].get("sequenceNo") or 0, ops.premises[i]["id"]))


def reading_path(ops, mru_id: str, mode: str, *, kmh: float, dwell: float) -> Route | None:
    """The round's path (walk or drive-by), cached on the town; None when the route has no premises."""
    key = (mru_id, mode, round(kmh, 2), round(dwell, 1))
    if key in ops.reading_paths:
        return ops.reading_paths[key]
    rows = stops(ops, mru_id)
    if mode == "drive" and len(rows) > 2:
        rows = rows[::DRIVE_BY_STRIDE] + [rows[-1]]
    if mode == "walk" and rows:
        rows = rows + [rows[0]]  # back to the van
    router = Router(ops.roads, (kmh, kmh, kmh))
    pts, times, length, clock = [], [], 0.0, 0.0
    for a, b in zip(rows, rows[1:], strict=False):
        try:
            leg = router.route(access_point(ops.roads, *ops.premise_access[a]),
                               access_point(ops.roads, *ops.premise_access[b]))
        except ValueError:
            continue
        if pts:
            clock += dwell if mode == "walk" else 0.0
            pts.append(leg.points)
            times.append(clock + leg.times)
        else:
            pts.append(leg.points)
            times.append(leg.times)
        clock = float(times[-1][-1])
        length += leg.length_m
    if not pts:
        ops.reading_paths[key] = None
        return None
    points = np.vstack(pts)
    t = np.concatenate(times)
    t = np.maximum.accumulate(t + np.arange(len(t)) * 1e-3)  # strictly increasing
    route = Route(points, t, length)
    ops.reading_paths[key] = route
    return route
