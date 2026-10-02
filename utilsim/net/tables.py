"""Engineering step tables. Capacities are derived from the same equations the flow solvers use, so sizing and
simulation never disagree. Values are representative of North American distribution practice."""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------- electric
@dataclass(frozen=True)
class Conductor:
    code: str
    label: str
    ampacity_a: float
    r_ohm_km: float
    x_ohm_km: float
    construction: str  # overhead | underground


OH_CONDUCTORS = [
    Conductor("ACSR_2", "#2 ACSR", 180, 1.050, 0.435, "overhead"),
    Conductor("ACSR_1/0", "1/0 ACSR", 230, 0.696, 0.410, "overhead"),
    Conductor("ACSR_4/0", "4/0 ACSR", 340, 0.367, 0.373, "overhead"),
    Conductor("ACSR_336", "336.4 kcmil ACSR", 530, 0.193, 0.286, "overhead"),
    Conductor("ACSR_477", "477 kcmil ACSR", 670, 0.137, 0.273, "overhead"),
    Conductor("ACSR_795", "795 kcmil ACSR", 900, 0.082, 0.255, "overhead"),
]
UG_CONDUCTORS = [
    Conductor("AL_1/0", "1/0 AL 15 kV XLPE", 175, 0.641, 0.140, "underground"),
    Conductor("AL_4/0", "4/0 AL 15 kV XLPE", 255, 0.320, 0.130, "underground"),
    Conductor("AL_500", "500 kcmil AL 15 kV XLPE", 385, 0.135, 0.118, "underground"),
    Conductor("AL_750", "750 kcmil AL 15 kV XLPE", 475, 0.090, 0.112, "underground"),
    Conductor("AL_1000", "1000 kcmil AL 15 kV XLPE", 540, 0.068, 0.108, "underground"),
]
SECONDARY = [
    Conductor("TPX_1/0", "1/0 AL triplex", 200, 0.641, 0.090, "overhead"),
    Conductor("TPX_4/0", "4/0 AL triplex", 300, 0.320, 0.085, "overhead"),
    Conductor("URD_4/0", "4/0 AL URD triplex", 255, 0.320, 0.080, "underground"),
    Conductor("URD_350", "350 kcmil AL URD", 330, 0.193, 0.078, "underground"),
]
THREE_PHASE_KVA = [75, 150, 300, 500, 750, 1000, 1500, 2500]


def conductor_kva(c: Conductor, kv_ll: float, phases: int) -> float:
    if phases == 3:
        return math.sqrt(3) * kv_ll * c.ampacity_a
    return kv_ll / math.sqrt(3) * c.ampacity_a


def pick_conductor(kva: float, kv_ll: float, phases: int, construction: str) -> Conductor:
    table = OH_CONDUCTORS if construction == "overhead" else UG_CONDUCTORS
    for c in table:
        if conductor_kva(c, kv_ll, phases) >= kva:
            return c
    return table[-1]


def coincidence(n, floor: float):
    import numpy as np

    n = np.maximum(np.asarray(n, dtype=np.float64), 1.0)
    return floor + (1.0 - floor) / np.sqrt(n)


# ---------------------------------------------------------------- gas
@dataclass(frozen=True)
class GasPipe:
    nominal_mm: int
    label: str
    id_in: float
    material: str
    tier: str  # mp | lp | service


PSI_PER_KPA = 1 / 6.894757
WEYMOUTH_BASE = (520.0, 14.73)  # customary Weymouth base: 520 °R (≈ 60 °F) and 14.73 psia


def weymouth_base(base_pressure_kpa: float, base_temperature_c: float) -> tuple[float, float]:
    """Weymouth base conditions (°R, psia) from the config's standard-volume base (``gas.base_*``), to 6 decimals
    (the defaults, 15.738889 °C and 101.559771 kPa, give exactly 520 °R and 14.73 psia)."""
    return round(base_temperature_c * 1.8 + 491.67, 6), round(base_pressure_kpa * PSI_PER_KPA, 6)


def weymouth_m3h(id_in: float, p1_psig: float, p2_psig: float, length_mi: float, sg: float = 0.6,
                 base: tuple[float, float] = WEYMOUTH_BASE) -> float:
    """Weymouth equation, US units (scfd at the ``base`` conditions), returned as standard m³/h."""
    (tb, pb), t = base, 520.0
    p1, p2 = p1_psig + 14.7, p2_psig + 14.7
    q_scfd = 433.5 * (tb / pb) * math.sqrt((p1 * p1 - p2 * p2) / (sg * t * length_mi)) * id_in ** (8.0 / 3.0)
    return q_scfd / 24.0 / 35.3147


def spitzglass_lp_m3h(id_in: float, dh_inwc: float, length_ft: float, sg: float = 0.6) -> float:
    """Spitzglass low-pressure equation (CFH), returned as m³/h."""
    q_cfh = 3550.0 * math.sqrt(dh_inwc * id_in**5 / (sg * length_ft * (1 + 3.6 / id_in + 0.03 * id_in)))
    return q_cfh / 35.3147


GAS_MP = [
    GasPipe(50, '2" PE', 1.94, "PE SDR11", "mp"),
    GasPipe(100, '4" PE', 3.63, "PE SDR11", "mp"),
    GasPipe(150, '6" PE', 5.35, "PE SDR11", "mp"),
    GasPipe(200, '8" PE', 7.00, "PE SDR11", "mp"),
    GasPipe(250, '10" steel', 10.02, "steel", "mp"),
    GasPipe(300, '12" steel', 12.00, "steel", "mp"),
    GasPipe(400, '16" steel', 15.25, "steel", "mp"),
]
GAS_LP = [
    GasPipe(100, '4" cast iron (lined)', 4.0, "cast iron", "lp"),
    GasPipe(150, '6" cast iron (lined)', 6.0, "cast iron", "lp"),
    GasPipe(200, '8" cast iron (lined)', 8.0, "cast iron", "lp"),
    GasPipe(300, '12" cast iron (lined)', 12.0, "cast iron", "lp"),
    GasPipe(400, '16" steel', 15.25, "steel", "lp"),
]
GAS_SERVICE = [  # (nominal mm, label, capacity m³/h)
    (19, '3/4" PE', 7.0), (25, '1" PE', 12.7), (32, '1-1/4" PE', 34.0), (50, '2" PE', 99.0), (100, '4" steel', 560.0),
]
GAS_TRANSMISSION = GasPipe(300, '12" steel transmission', 12.0, "steel", "hp")


def gas_capacity_m3h(p: GasPipe, mp_psig: float = 60.0, base: tuple[float, float] = WEYMOUTH_BASE) -> float:
    if p.tier == "lp":
        return spitzglass_lp_m3h(p.id_in, 1.5, 2000.0)
    return weymouth_m3h(p.id_in, mp_psig, mp_psig * 2.0 / 3.0, 2.0, base=base)


# ---------------------------------------------------------------- water
@dataclass(frozen=True)
class WaterPipe:
    nominal_mm: int
    label: str
    id_mm: float
    material: str


WATER_MAINS = [
    WaterPipe(150, '6" PVC', 155.0, "PVC C900"),
    WaterPipe(200, '8" PVC', 204.0, "PVC C900"),
    WaterPipe(250, '10" PVC', 250.0, "PVC C900"),
    WaterPipe(300, '12" PVC', 297.0, "PVC C900"),
    WaterPipe(400, '16" ductile iron', 412.0, "ductile iron"),
    WaterPipe(500, '20" ductile iron', 512.0, "ductile iron"),
    WaterPipe(600, '24" ductile iron', 612.0, "ductile iron"),
    WaterPipe(750, '30" concrete', 762.0, "PCCP"),
]
CAST_IRON = "cast iron"  # unlined, in districts built before ``water.cast_iron_before_year``
WATER_SERVICE = [(19, '3/4" copper', 1.0), (25, '1" copper', 1.6), (38, '1-1/2" copper', 4.0), (50, '2" copper', 6.5),
                 (100, '4" ductile iron', 26.0), (150, '6" ductile iron', 55.0)]
V_NORMAL = 1.5  # m/s at peak hour
V_FIRE = 3.0  # m/s at max day + fire flow


def water_capacity_lps(p: WaterPipe, velocity: float) -> float:
    a = math.pi * (p.id_mm / 1000.0) ** 2 / 4.0
    return a * velocity * 1000.0


def hazen_williams_headloss_m(q_lps: float, id_mm: float, length_m: float, c: float) -> float:
    q = abs(q_lps) / 1000.0
    d = id_mm / 1000.0
    return 10.67 * length_m * q**1.852 / (c**1.852 * d**4.8704)
