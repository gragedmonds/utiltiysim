"""Units. Everything internal is SI: metres, m², m³, m³/h, kWh, kW/kVA, kPa, °C. A ``UnitProfile`` decides how
values are *displayed* (and labelled) per locale; it never changes stored values.
"""

from __future__ import annotations

from dataclasses import dataclass

KPA_PER_PSI = 6.894757
M3_PER_CCF = 2.831685  # 100 cubic feet
M3_PER_GAL = 0.003785412
MJ_PER_THERM = 105.4804
MJ_PER_KWH = 3.6
CFH_PER_M3H = 35.3147  # cubic feet per hour per m³/h
GPM_PER_LPS = 15.850323  # US gallons per minute per litre/second
FT_PER_M = 3.280840

# Nominal pipe sizes: internal key is nominal millimetres; labels differ by profile.
NOMINAL_INCH_LABEL = {
    19: '3/4"', 25: '1"', 32: '1-1/4"', 38: '1-1/2"', 50: '2"', 75: '3"', 100: '4"', 150: '6"', 200: '8"',
    250: '10"', 300: '12"', 400: '16"', 450: '18"', 500: '20"', 600: '24"', 750: '30"', 900: '36"',
}


@dataclass(frozen=True)
class UnitProfile:
    name: str
    pipe_size: str  # "in" | "mm"
    pressure: str  # "psi" | "kPa" | "bar"
    gas_volume: str  # "ccf" | "m3" | "therm" | "kwh"
    water_volume: str  # "m3" | "gal"
    temperature: str  # "C" | "F"
    gas_calorific_mj_per_m3: float = 37.5  # Ontario typical heating value

    def pipe_label(self, nominal_mm: int) -> str:
        if self.pipe_size == "in":
            return NOMINAL_INCH_LABEL.get(int(nominal_mm), f"{nominal_mm / 25.4:.2f}\"")
        return f"{int(nominal_mm)} mm"

    def pressure_value(self, kpa: float) -> tuple[float, str]:
        if self.pressure == "psi":
            return kpa / KPA_PER_PSI, "psi"
        if self.pressure == "bar":
            return kpa / 100.0, "bar"
        return kpa, "kPa"

    def gas_value(self, m3: float) -> tuple[float, str]:
        if self.gas_volume == "ccf":
            return m3 / M3_PER_CCF, "CCF"
        if self.gas_volume == "therm":
            return m3 * self.gas_calorific_mj_per_m3 / MJ_PER_THERM, "therm"
        if self.gas_volume == "kwh":
            return m3 * self.gas_calorific_mj_per_m3 / MJ_PER_KWH, "kWh"
        return m3, "m³"

    def water_value(self, m3: float) -> tuple[float, str]:
        if self.water_volume == "gal":
            return m3 / M3_PER_GAL, "gal"
        return m3, "m³"

    def temperature_value(self, c: float) -> tuple[float, str]:
        if self.temperature == "F":
            return c * 9.0 / 5.0 + 32.0, "°F"
        return c, "°C"


PROFILES: dict[str, UnitProfile] = {
    "ontario": UnitProfile("ontario", "in", "psi", "ccf", "m3", "C"),
    "us": UnitProfile("us", "in", "psi", "ccf", "gal", "F", gas_calorific_mj_per_m3=38.3),
    "uk": UnitProfile("uk", "mm", "bar", "kwh", "m3", "C", gas_calorific_mj_per_m3=39.5),
}


def get_profile(name: str) -> UnitProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise KeyError(f"unknown unit profile {name!r}; choose from {sorted(PROFILES)}") from exc
