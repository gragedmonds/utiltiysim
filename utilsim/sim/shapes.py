"""Hourly demand shapes (the prototype's morning/evening Gaussians and solar arc), normalised per day.

Pure numpy: the runtime (state frames, the operations timeline, the Vercel function) imports this without the
generation stack (scipy, shapely)."""

from __future__ import annotations

import math

import numpy as np


def _shapes(hour: float):
    morning = math.exp(-(((hour - 7.5) / 2.0) ** 2))
    evening = math.exp(-(((hour - 19.0) / 3.0) ** 2))
    sun = max(0.0, math.sin((hour - 6.0) / 12.0 * math.pi))
    return morning, evening, sun


def _shape_means() -> tuple[float, float, float]:
    """Mean of each consumption shape over a day (288 five-minute midpoints), so ``daily/24 · shape/mean``
    integrates exactly to the daily total."""
    t = (np.arange(288) + 0.5) / 12.0
    m = np.exp(-(((t - 7.5) / 2.0) ** 2))
    e = np.exp(-(((t - 19.0) / 3.0) ** 2))
    return (float(np.mean(0.42 + 1.15 * m + 1.65 * e)), float(np.mean(0.22 + 2.0 * m + 1.8 * e)),
            float(np.mean(0.35 + 1.3 * m + 0.8 * e)))


LOAD_MEAN, WATER_MEAN, GAS_MEAN = _shape_means()


def hourly(daily: dict[str, np.ndarray], occupied: np.ndarray, has_gas: np.ndarray, hour: float,
           scenario: str = "normal", target: int | None = None, leak_m3h: float = 0.65) -> dict[str, np.ndarray]:
    """Instantaneous demand per premise (kW, m³/h, m³/h) with the prototype's shapes, normalised so that a full day
    integrates exactly to ``dailyKWh``, ``dailyWaterM3`` and ``dailyGasM3`` (occupied premises)."""
    morning, evening, sun = _shapes(hour)
    occ = np.where(occupied, 1.0, 0.09)
    load = daily["dailyKWh"] / 24.0 * (0.42 + 1.15 * morning + 1.65 * evening) / LOAD_MEAN * occ
    water = daily["dailyWaterM3"] / 24.0 * (0.22 + 2.0 * morning + 1.8 * evening) / WATER_MEAN * occ
    gas = daily["dailyGasM3"] / 24.0 * (0.35 + 1.3 * morning + 0.8 * evening) / GAS_MEAN * occ
    gen = sun * daily["solarPeakKW"]
    if scenario == "leak" and target is not None:
        water = water.copy()
        water[target] += leak_m3h
    if scenario == "substation_outage":
        load = np.zeros_like(load)
        gen = np.zeros_like(gen)
    gas = np.where(has_gas, gas, 0.0)
    net = load - gen
    return {"electric": net, "water": water, "gas": gas, "loadKW": load, "generationKW": gen,
            "importKW": np.maximum(0.0, net), "exportKW": np.maximum(0.0, -net)}
