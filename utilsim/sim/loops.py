"""Loop flows on a forest plus chords: Newton on the loop (energy) equations, numpy only.

The radial forest from ``sim.flows`` already balances every node: each tree edge carries what lies beyond it. Every
other enabled edge between two reached nodes is a *chord*. A chord's flow ``q`` (positive from its ``a`` end to its
``b`` end) leaves ``a`` and enters ``b``, so it adds ``q`` to every tree edge on the path from the root down to ``a``
and takes ``q`` off every tree edge on the path down to ``b``. Above the two paths' common ancestor the two cancel,
which leaves the chord's fundamental cycle. Continuity therefore holds at every node for any chord flows, and the
unknowns are the chord flows alone.

Each chord adds one energy equation: the potential (water head, gas P² or pressure) falls from ``a`` to ``b`` by the
chord's own loss. A node's potential is that of its *fixed node*, the nearest node at or above it whose potential is
held (a source, a pump station, a regulator), less the losses on the tree path between them. When the two ends hang
from different fixed nodes the equation runs from one fixed node to the other (a pseudo-loop) and carries their
difference in potential.

The loss law is ``r · Q · |Q|^(n−1)``. Newton's Jacobian is dense (chords × chords) and comes from the forest's
structure: the loss derivative two paths share is the cumulative derivative from the root down to their deepest
common ancestor. Each iteration is a few vector passes over the chord ends' paths to the root (gather indices are
built once per forest), so its cost does not depend on the number of tree levels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Cycles:
    """The chords of one forest and the paths from their ends to the roots. Built once per forest.

    Cumulative sums along the paths live in one array ``cum0``: entry 0 is zero (a root) and entry ``start[x] + d``
    is the sum from end ``x``'s root down to depth ``d`` on its path."""

    chords: np.ndarray  # edge index per chord
    ca: np.ndarray  # per chord: slot (into ``ends``) of its ``a`` end
    cb: np.ndarray  # per chord: slot of its ``b`` end
    ends: np.ndarray  # chord end nodes, unique
    depth: np.ndarray  # per end: depth below its root (= its path length)
    start: np.ndarray  # per end: offset of its path in the flat arrays
    flat: np.ndarray  # per path entry: index into ``touched`` (paths run root side first: entry d-1 is at depth d)
    owner: np.ndarray  # per path entry: end slot
    touched: np.ndarray  # nodes on any path (each stands for its parent edge)
    fixed: np.ndarray  # per end: its fixed node (nearest held node at or above it)
    fixed_depth: np.ndarray  # per end: depth of that node
    i_end: np.ndarray  # per end: ``cum0`` index of the end itself
    i_fix: np.ndarray  # per end: ``cum0`` index of its fixed node
    i_pair: np.ndarray  # (ends × ends): ``cum0`` index, on x's path, of the deepest of x's and y's common ancestor
    #                     and x's fixed node
    jac_index: np.ndarray = field(init=False)  # (4, chords, chords) ``cum0`` indices for the Jacobian

    def __post_init__(self):
        ca, cb, p = self.ca, self.cb, self.i_pair
        self.jac_index = np.stack([p[np.ix_(ca, ca)], p[np.ix_(ca, cb)], p[np.ix_(cb, ca)], p[np.ix_(cb, cb)]])

    def subset(self, keep: np.ndarray) -> Cycles:
        """The same paths with only the chords in ``keep`` (bool per chord)."""
        return Cycles(self.chords[keep], self.ca[keep], self.cb[keep], self.ends, self.depth, self.start, self.flat,
                      self.owner, self.touched, self.fixed, self.fixed_depth, self.i_end, self.i_fix, self.i_pair)

    def cumulative(self, w: np.ndarray) -> np.ndarray:
        """``cum0`` for per-touched-node weights ``w`` (each node's parent edge)."""
        out = np.zeros(len(self.flat) + 1)
        if len(self.flat):
            wf = w[self.flat]
            c = np.cumsum(wf)
            first = np.minimum(self.start, len(c) - 1)  # an end with an empty path owns no entries
            out[1:] = c - (c[first] - wf[first])[self.owner]
        return out


def cycles(parent: np.ndarray, depth: np.ndarray, a: np.ndarray, b: np.ndarray, chords: np.ndarray,
           held: np.ndarray) -> Cycles:
    """``parent`` and ``depth`` per node (−1 / 0 at roots); ``a``, ``b`` per edge; ``held`` marks nodes whose
    potential is fixed (roots are always fixed)."""
    chords = np.asarray(chords, dtype=np.int64)
    ends, inv = np.unique(np.concatenate([a[chords], b[chords]]), return_inverse=True)
    nc, ne = len(chords), len(ends)
    ca, cb = inv[:nc], inv[nc:]
    dep = depth[ends].astype(np.int64)
    start = np.concatenate([[0], np.cumsum(dep)[:-1]]).astype(np.int64) if ne else np.zeros(0, np.int64)
    nodes = np.empty(int(dep.sum()), dtype=np.int64)
    cur, d = ends.copy(), dep.copy()
    live = np.flatnonzero(d > 0)
    while len(live):
        nodes[start[live] + d[live] - 1] = cur[live]
        cur[live] = parent[cur[live]]
        d[live] -= 1
        live = live[d[live] > 0]
    root = cur  # every walk ends at its root
    owner = np.repeat(np.arange(ne), dep)
    touched, flat = np.unique(nodes, return_inverse=True)
    # Fixed node: the deepest held node on the path, else the root.
    pos = np.arange(len(nodes)) - start[owner] + 1  # depth of each entry
    fd = np.zeros(ne, dtype=np.int64)
    if len(nodes):
        np.maximum.at(fd, owner, np.where(held[nodes], pos, 0))
    fixed = root.copy()
    deep = fd > 0
    fixed[deep] = nodes[start[deep] + fd[deep] - 1]
    # Deepest common ancestor depth for every pair of ends (binary search on the common prefix of the paths).
    same = root[:, None] == root[None, :]
    lo = np.zeros((ne, ne), dtype=np.int64)
    hi = np.where(same, np.minimum(dep[:, None], dep[None, :]), 0)
    sx, sy = np.broadcast_to(start[:, None], lo.shape), np.broadcast_to(start[None, :], lo.shape)
    while True:
        open_ = lo < hi
        if not open_.any():
            break
        mid = (lo + hi + 1) // 2
        m = np.where(open_, mid, 1)
        eq = open_ & (nodes[np.where(open_, sx + m - 1, 0)] == nodes[np.where(open_, sy + m - 1, 0)])
        lo = np.where(eq, mid, lo)
        hi = np.where(open_ & ~eq, mid - 1, hi)
    lca = np.where(same, lo, -1)
    i_end = np.where(dep > 0, start + dep, 0)
    i_fix = np.where(fd > 0, start + fd, 0)
    # Shared with y below x's fixed node: from x's fixed node down to the common ancestor (nothing if it is above).
    i_pair = np.where(lca > fd[:, None], start[:, None] + lca, i_fix[:, None])
    return Cycles(chords, ca, cb, ends, dep, start, flat, owner, touched, fixed, fd, i_end, i_fix, i_pair)


BLOCK = 96  # OpenBLAS factors a matrix of order ≥ 100 on all its threads


def dense_solve(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """``np.linalg.solve`` by block elimination on halves, so that every LU factorisation stays below ``BLOCK``.

    OpenBLAS runs an LU of order 100 or more on all its threads; on a small or busy host that costs 25–180 ms for the
    ~170 loops of a 5,000-premise town, against 0.1 ms on one thread, and the thread count cannot be set from numpy.
    Pivoting stays within the diagonal blocks, which suits the loop Jacobian: it is −(Cᵀ·G·C + D) with G and D
    positive diagonals (symmetric negative definite, apart from loops whose paths cross a held node). Falls back to
    least squares if a block is singular."""
    n = len(a)
    try:
        if n <= BLOCK:
            return np.linalg.solve(a, b)
        h = n // 2
        a12, a21 = a[:h, h:], a[h:, :h]
        rhs = np.column_stack([a12, b[:h]])
        y = dense_solve(a[:h, :h], rhs)
        y12, y1 = y[:, : n - h], y[:, n - h:]
        x2 = dense_solve(a[h:, h:] - a21 @ y12, b[h:] - a21 @ (y1 if b.ndim > 1 else y1[:, 0]))
        x1 = (y1 if b.ndim > 1 else y1[:, 0]) - y12 @ x2
        x = np.concatenate([x1, x2])
        if np.isfinite(x).all():
            return x
    except np.linalg.LinAlgError:
        pass
    return np.linalg.lstsq(a, b, rcond=None)[0]


@dataclass
class LoopSolution:
    q: np.ndarray  # per chord (positive a → b)
    flow: np.ndarray  # per touched node: flow in its parent edge (positive parent → node)
    iterations: int
    residual: float  # worst |loop equation| at the end, in each chord's potential units
    converged: bool


def solve(cyc: Cycles, base: np.ndarray, r_tree: np.ndarray, r_chord: np.ndarray, n: float, dh: np.ndarray,
          tol: np.ndarray, qmin: float = 1e-3, max_iter: int = 60) -> LoopSolution:
    """Damped Newton on the chord flows, from zero (so a frame does not depend on what was solved before it).

    ``base``: radial flow per touched node; ``r_tree``: loss coefficient of each touched node's parent edge;
    ``r_chord``: per chord; ``dh``: potential of the ``a`` end's fixed node minus the ``b`` end's, per chord; ``tol``:
    per chord, in the same units. ``qmin`` floors |Q| in the derivative, so a cycle with no flow keeps a usable
    Jacobian. Each step is halved until the scaled residual norm falls."""
    ne, nt, nc = len(cyc.ends), len(cyc.touched), len(cyc.chords)
    ca, cb, owner, flat = cyc.ca, cyc.cb, cyc.owner, cyc.flat
    diag = np.diag_indices(nc)

    def evaluate(q: np.ndarray):
        inj = np.bincount(ca, q, ne) - np.bincount(cb, q, ne)
        flow = base + np.bincount(flat, inj[owner], nt) if nt else base
        cum0 = cyc.cumulative(r_tree * flow * np.abs(flow) ** (n - 1))
        loss = cum0[cyc.i_end] - cum0[cyc.i_fix]  # fixed node → end
        return dh - loss[ca] + loss[cb] - r_chord * q * np.abs(q) ** (n - 1), flow

    def jacobian(q: np.ndarray, flow: np.ndarray) -> np.ndarray:
        g0 = cyc.cumulative(n * r_tree * np.maximum(np.abs(flow), qmin) ** (n - 1))
        s = g0[cyc.jac_index]
        jac = (s[2] - s[3]) - (s[0] - s[1])
        jac[diag] -= n * r_chord * np.maximum(np.abs(q), qmin) ** (n - 1)
        return jac

    q = np.zeros(nc)
    f, flow = evaluate(q)
    scale = 1.0 / tol
    merit = float(np.linalg.norm(f * scale))
    it = 0
    while it < max_iter and np.max(np.abs(f) * scale, initial=0.0) > 1.0:
        it += 1
        jac = jacobian(q, flow)
        step = dense_solve(jac, -f)
        alpha = 1.0
        while True:
            qn = q + alpha * step
            fn, fl = evaluate(qn)
            mn = float(np.linalg.norm(fn * scale))
            if mn < (1.0 - 1e-4 * alpha) * merit or (alpha < 1e-4 and np.isfinite(mn)):
                break
            if alpha < 1e-4:  # nothing finite along the step: give up (not converged)
                return LoopSolution(q, flow, it, float(np.max(np.abs(f), initial=0.0)), False)
            alpha *= 0.5
        q, f, flow, merit = qn, fn, fl, mn
    res = float(np.max(np.abs(f), initial=0.0))
    return LoopSolution(q, flow, it, res, bool(np.max(np.abs(f) * scale, initial=0.0) <= 1.0))
