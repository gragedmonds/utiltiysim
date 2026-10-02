"""Deterministic randomness.

Two primitives, both pure functions of the master seed:

* ``stage_rng(master, *path)`` – a numpy ``Generator`` (PCG64) for a pipeline stage or sub-stage. Streams are
  derived from the path, so changing one stage's parameters never reshuffles another stage.
* ``hash_u01(seed, purpose, *keys)`` – counter-based, vectorised uniform draws keyed by entity ids. Use this for
  anything per-entity (house attributes, daily consumption noise, anomaly draws) so the value never depends on
  evaluation order or on how many other entities exist.

Rules: never use the ``random`` module, never iterate Python sets, never hash floats, never let a stream RNG
leak into per-entity computations.
"""

from __future__ import annotations

import hashlib
from enum import IntEnum
from functools import lru_cache

import numpy as np

_GOLDEN = np.uint64(0x9E3779B97F4A7C15)
_M1 = np.uint64(0xBF58476D1CE4E5B9)
_M2 = np.uint64(0x94D049BB133111EB)
_2POW53 = float(1 << 53)


class Purpose(IntEnum):
    """Purpose ids for counter-based hashing. Append only; never renumber (it would change every town)."""

    EDGE_TIEBREAK = 1
    LOT_JITTER = 2
    HOUSE_ATTR = 3
    HOUSEHOLD = 4
    FOOTPRINT = 5
    ROOF_TONE = 6
    ERA_NOISE = 7
    STREET_NAME = 8
    PHASE = 9
    METER_SERIAL = 10
    REGISTER_BASE = 11
    DAILY_NOISE = 12
    WEATHER = 13
    ANOMALY = 14
    READ_JITTER = 15
    OCCUPANCY = 16
    DEMAND_PROFILE = 17
    AMI_ROLLOUT = 18
    PLACEMENT = 19
    INCIDENT = 20
    NAMES = 21
    PAYMENT = 22
    MOVE = 23
    SOLAR = 24
    DISTRICT_STYLE = 25
    TERRAIN = 26
    ROADS = 27
    LOT_SELECT = 28
    FACILITY = 29
    FEEDER = 30
    ROUTE = 31
    CUSTOMER = 32
    LAND_USE = 33
    M2C_READ = 34
    M2C_ANOMALY = 35
    M2C_WORK = 36
    M2C_BILL = 37
    OPS_INCIDENT = 38


def normalize_seed(seed: int | str) -> int:
    """Turn a user-facing seed (int or any string such as 'WHITBY-042') into a 64-bit unsigned integer."""
    if isinstance(seed, str):
        return _normalize_str(seed)
    if isinstance(seed, bool):
        raise TypeError("seed must be int or str")
    if isinstance(seed, int):
        return seed & 0xFFFFFFFFFFFFFFFF
    s = str(seed).strip()
    if not s:
        raise ValueError("seed must not be empty")
    if s.lstrip("-").isdigit() and len(s) < 19:
        return int(s) & 0xFFFFFFFFFFFFFFFF
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "little")


@lru_cache(maxsize=4096)
def _normalize_str(seed: str) -> int:
    s = seed.strip()
    if not s:
        raise ValueError("seed must not be empty")
    if s.lstrip("-").isdigit() and len(s) < 19:
        return int(s) & 0xFFFFFFFFFFFFFFFF
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "little")


def derive_seed(master: int | str, *path: str | int) -> int:
    """Stable 64-bit sub-seed for a named stage path, e.g. derive_seed(seed, 'roads', 'locals', block_idx)."""
    base = normalize_seed(master)
    key = (str(base) + "/" + "/".join(str(p) for p in path)).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "little")


def stage_rng(master: int | str, *path: str | int) -> np.random.Generator:
    """numpy Generator (PCG64) for a stage. Use one per stage/sub-stage, never share across stages."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(derive_seed(master, *path))))


def _mix64(x: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        x = (x ^ (x >> np.uint64(30))) * _M1
        x = (x ^ (x >> np.uint64(27))) * _M2
        return x ^ (x >> np.uint64(31))


def hash_u64(seed: int | str, purpose: int, *keys) -> np.ndarray:
    """Vectorised 64-bit hash of (seed, purpose, key_1, key_2, ...). Keys broadcast like numpy arrays.

    Integer keys only (ids, day numbers, indices). Strings must be mapped to ints first (see ``ids``)."""
    arrs = [np.asarray(k) for k in keys]
    shape = np.broadcast_shapes(*(a.shape for a in arrs)) if arrs else ()
    h = np.full(shape, normalize_seed(seed), dtype=np.uint64)
    with np.errstate(over="ignore"):
        h = _mix64(h ^ (np.uint64(int(purpose)) + _GOLDEN))
        for a in arrs:
            if a.dtype.kind == "f":
                raise TypeError("hash keys must be integers, not floats")
            k = a.astype(np.int64).astype(np.uint64)
            h = _mix64(h ^ (k + _GOLDEN))
    return h


def hash_u01(seed: int | str, purpose: int, *keys) -> np.ndarray:
    """Uniform floats in [0, 1) with 53-bit resolution, keyed by (seed, purpose, keys)."""
    return (hash_u64(seed, purpose, *keys) >> np.uint64(11)).astype(np.float64) / _2POW53


def hash_normal(seed: int | str, purpose: int, *keys) -> np.ndarray:
    """Standard normal draws keyed by (seed, purpose, keys) via Box–Muller on two independent hashes."""
    u1 = hash_u01(seed, purpose, *keys, 0x51)
    u2 = hash_u01(seed, purpose, *keys, 0x52)
    u1 = np.maximum(u1, 1e-300)
    return np.sqrt(-2.0 * np.log(u1)) * np.cos(2.0 * np.pi * u2)


def hash_choice(seed: int | str, purpose: int, keys, weights) -> np.ndarray:
    """Weighted categorical draw per key. ``weights`` is a 1-D sequence; returns category indices."""
    w = np.asarray(weights, dtype=np.float64)
    if w.ndim != 1 or w.size == 0 or np.any(w < 0) or w.sum() <= 0:
        raise ValueError("weights must be a non-empty 1-D non-negative sequence with positive sum")
    cdf = np.cumsum(w / w.sum())
    u = hash_u01(seed, purpose, keys)
    return np.minimum(np.searchsorted(cdf, u, side="right"), w.size - 1)
