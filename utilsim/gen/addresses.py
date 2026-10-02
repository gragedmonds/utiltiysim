"""Civic addresses: numbers increase away from the town centre along each named street, odd on one side and even
on the other, with gaps proportional to frontage (as Ontario municipalities number by distance)."""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

from utilsim.model.premises import Premises


def assign_addresses(prem: Premises, roads, center) -> None:
    g = roads.graph
    names = roads.names
    by_name: dict[str, list[int]] = {}
    for i in range(len(prem)):
        by_name.setdefault(names[int(prem.edge[i])] or "Unnamed Road", []).append(i)
    street = [""] * len(prem)
    number = np.zeros(len(prem), dtype=np.int64)
    c = Point(center)
    for name in sorted(by_name):
        idx = by_name[name]
        edges = sorted({int(e) for e, nm in enumerate(names) if (nm or "Unnamed Road") == name})
        merged = linemerge(MultiLineString([LineString(g.geometry[e]) for e in edges]))
        parts = list(getattr(merged, "geoms", [merged]))
        # Orient every part to start at its end nearest the centre; parts laid end to end by that distance.
        oriented = []
        for p in parts:
            a, b = Point(p.coords[0]), Point(p.coords[-1])
            if b.distance(c) < a.distance(c):
                p = LineString(list(p.coords)[::-1])
            oriented.append(p)
        oriented.sort(key=lambda p: (round(Point(p.coords[0]).distance(c), 2), round(p.length, 2)))
        base = np.cumsum([0.0] + [p.length + 50.0 for p in oriented])
        recs = []
        for i in idx:
            fp = Point(prem.front_xy[i])
            k = int(np.argmin([p.distance(fp) for p in oriented]))
            line = oriented[k]
            s = line.project(fp)
            a = line.interpolate(max(0.0, s - 1.0))
            b = line.interpolate(min(line.length, s + 1.0))
            t = np.array([b.x - a.x, b.y - a.y])
            v = prem.row_xy[i] - prem.front_xy[i]
            left = (t[0] * v[1] - t[1] * v[0]) > 0
            recs.append((base[k] + s, left, i))
        for parity in (True, False):
            run = sorted((r for r in recs if r[1] == parity), key=lambda r: (round(r[0], 2), r[2]))
            last = -1
            for s, left, i in run:
                n = 2 * int(s // 9.0) + (1 if left else 2)
                if n <= last:
                    n = last + 2
                number[i] = n
                street[i] = name
                last = n
    prem.street = street
    prem.number = number
