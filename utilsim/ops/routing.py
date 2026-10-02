"""Crew routing on the road graph.

Shortest *travel time* between two street access points ``(road edge, distance along it)``, with speeds per road
class from ``operations.speed_kmh_*``. Parallel roads between the same two junctions stay separate edges. The route
is returned as a polyline in the right-hand lane (``LANE_M`` from the centreline) with a timestamp at every vertex,
seconds from departure, strictly increasing, so the viewer can interpolate a van without inventing anything.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

LANE_M = 1.8
MAX_STEP_M = 20.0


@dataclass
class Route:
    points: np.ndarray  # (k, 2) x, z
    times: np.ndarray  # seconds from departure, strictly increasing
    length_m: float

    @property
    def seconds(self) -> float:
        return float(self.times[-1])

    def reversed(self) -> Route:
        """The way back: same path in reverse, in the other lane, same timing per segment."""
        pts = _offset(self._centre[::-1], LANE_M) if hasattr(self, "_centre") else self.points[::-1]
        dt = np.diff(self.times)[::-1]
        r = Route(pts, np.concatenate([[0.0], np.cumsum(dt)]), self.length_m)
        if hasattr(self, "_centre"):
            r._centre = self._centre[::-1]
        return r


def _sub(points: np.ndarray, s0: float, s1: float) -> np.ndarray:
    """Part of a polyline between arc lengths s0 and s1 (s1 < s0 walks it backwards)."""
    seg = np.hypot(*np.diff(points, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    lo, hi = sorted((s0, s1))
    lo, hi = max(0.0, lo), min(float(cum[-1]), hi)

    def at(s):
        i = int(np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(seg) - 1))
        t = 0.0 if seg[i] == 0 else (s - cum[i]) / seg[i]
        return points[i] + (points[i + 1] - points[i]) * t

    inner = points[(cum > lo) & (cum < hi)]
    out = np.vstack([at(lo), inner, at(hi)]) if len(inner) else np.vstack([at(lo), at(hi)])
    return out if s1 >= s0 else out[::-1]


def _offset(points: np.ndarray, d: float) -> np.ndarray:
    """Shift a polyline ``d`` metres to the right of travel (x east, z south: right of (dx, dz) is (-dz, dx))."""
    if len(points) < 2:
        return points.copy()
    seg = np.diff(points, axis=0)
    ln = np.hypot(seg[:, 0], seg[:, 1])
    ln[ln == 0] = 1.0
    n = np.stack([-seg[:, 1] / ln, seg[:, 0] / ln], axis=1)
    vn = np.zeros_like(points)
    vn[:-1] += n
    vn[1:] += n
    vl = np.hypot(vn[:, 0], vn[:, 1])
    vl[vl == 0] = 1.0
    return points + vn / vl[:, None] * d


def _densify(points: np.ndarray, speeds: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split long segments (≤ MAX_STEP_M) carrying their speed; drop zero-length steps."""
    out, sp = [points[0]], []
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        d = float(np.hypot(*(b - a)))
        if d < 1e-6:
            continue
        k = max(1, int(np.ceil(d / MAX_STEP_M)))
        for j in range(1, k + 1):
            out.append(a + (b - a) * j / k)
            sp.append(speeds[i - 1])
    return np.array(out), np.array(sp)


class Router:
    def __init__(self, roads, speeds_kmh: tuple[float, float, float]):
        self.g = roads
        self.mps = np.array(speeds_kmh, dtype=float) / 3.6
        self.edge_mps = self.mps[np.clip(roads.cls, 0, 2)]
        self.edge_sec = roads.length / self.edge_mps

    def _dijkstra(self, start: tuple[int, float], stop: tuple[int, ...] = ()) -> tuple[np.ndarray, np.ndarray]:
        """Travel times from an access point; stops once every node in ``stop`` is settled (when given)."""
        g = self.g
        waiting = set(stop)
        e0, s0 = start
        n = len(g.node_xy)
        dist = np.full(n, np.inf)
        prev = np.full(n, -1, dtype=np.int64)  # edge used to reach the node (-1 = from the start edge)
        heap = []
        for node, d in ((int(g.a[e0]), s0), (int(g.b[e0]), g.length[e0] - s0)):
            t = d / self.edge_mps[e0]
            if t < dist[node]:
                dist[node] = t
                heapq.heappush(heap, (t, node))
        while heap:
            t, v = heapq.heappop(heap)
            if t > dist[v]:
                continue
            if waiting:
                waiting.discard(v)
                if not waiting:
                    break
            for k, w in g.adj[v]:
                nt = t + self.edge_sec[k]
                if nt < dist[w] - 1e-9:
                    dist[w], prev[w] = nt, k
                    heapq.heappush(heap, (nt, w))
        return dist, prev

    def route(self, origin: tuple[int, float], target: tuple[int, float]) -> Route:
        """Fastest route between two access points ``(edge, metres from the edge's a-end)``."""
        g = self.g
        e0, s0 = origin[0], float(np.clip(origin[1], 0, g.length[origin[0]]))
        e1, s1 = target[0], float(np.clip(target[1], 0, g.length[target[0]]))
        dist, prev = self._dijkstra((e0, s0), (int(g.a[e1]), int(g.b[e1])))
        options = []
        if e0 == e1:
            options.append((abs(s1 - s0) / self.edge_mps[e0], "direct", None))
        for end, along in ((int(g.a[e1]), s1), (int(g.b[e1]), g.length[e1] - s1)):
            if np.isfinite(dist[end]):
                options.append((dist[end] + along / self.edge_mps[e1], "via", end))
        if not options:
            raise ValueError("no road route between these points (separate road islands)")
        _, how, end = min(options, key=lambda o: (o[0], o[1]))
        pieces: list[tuple[np.ndarray, float]] = []  # (centreline points, speed m/s)
        if how == "direct":
            pieces.append((_sub(g.points[e0], s0, s1), self.edge_mps[e0]))
        else:
            chain, v = [], end
            while prev[v] >= 0:  # walk back to the start edge
                k = int(prev[v])
                chain.append((k, v))
                v = int(g.a[k]) if int(g.b[k]) == v else int(g.b[k])
            first = v  # the start edge's end we left from
            leave = 0.0 if first == int(g.a[e0]) else float(g.length[e0])
            pieces.append((_sub(g.points[e0], s0, leave), self.edge_mps[e0]))
            for k, w in reversed(chain):
                p = g.points[k] if int(g.b[k]) == w else g.points[k][::-1]
                pieces.append((p, self.edge_mps[k]))
            enter = 0.0 if end == int(g.a[e1]) else float(g.length[e1])
            pieces.append((_sub(g.points[e1], enter, s1), self.edge_mps[e1]))
        pts, sp = [pieces[0][0][:1]], []
        for p, v in pieces:
            pts.append(p[1:] if len(pts) else p)
            sp.extend([v] * (len(p) - 1))
        centre = np.vstack(pts)
        centre, sp = _densify(centre, np.array(sp)) if len(centre) > 1 else (centre, np.array([]))
        if len(centre) < 2:  # already there
            centre = np.vstack([centre[0], centre[0] + 1e-3])
            sp = np.array([1.0])
        seg = np.hypot(*np.diff(centre, axis=0).T)
        times = np.concatenate([[0.0], np.cumsum(seg / sp)])
        times = np.maximum.accumulate(times + np.arange(len(times)) * 1e-3)  # strictly increasing (≥ 1 ms apart)
        r = Route(_offset(centre, LANE_M), times, float(seg.sum()))
        r._centre = centre
        return r


def access_point(roads, edge: int, t: float) -> tuple[int, float]:
    """(edge, metres from a) from a snapshot ``roadId``/``t`` pair."""
    return int(edge), float(t) * float(roads.length[int(edge)])
