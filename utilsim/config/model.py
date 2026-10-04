"""SimConfig: every assumption in the simulator is a parameter here.

Each field carries a description, default, bounds and UI hints (``x-unit``, ``x-advanced``, ``x-effects``) in its
JSON Schema so the frontend can generate a detailed settings page (``GET /api/config/schema``). Defaults are
calibrated to a Southern Ontario suburb; presets override subsets. Changing any value that affects generation
changes the town id, so every run is reproducible from (config, generator_version).
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

import orjson
from pydantic import BaseModel, ConfigDict, Field, model_validator

from utilsim.config.impact import IMPACT, REACHES, REMOVED
from utilsim.version import GENERATOR_VERSION


def F(default: Any, description: str, *, unit: str | None = None, ge: float | None = None,
      le: float | None = None, advanced: bool = False, effects: list[str] | None = None,
      not_modelled: str | None = None, deprecated: tuple[str, str] | None = None, **kw: Any):
    """A config field with its UI hints. ``not_modelled``: why the engine does not use it yet (``x-status:
    not-modelled`` + ``x-status-reason``). ``deprecated``: (replacement, reason) for a field another setting replaces
    (``x-status: deprecated``, ``x-deprecated``, ``x-status-reason``). A viewer shows both disabled with the reason."""
    extra: dict[str, Any] = {}
    if unit:
        extra["x-unit"] = unit
    if advanced:
        extra["x-advanced"] = True
    if effects:
        extra["x-effects"] = effects
    if not_modelled:
        extra.update({"x-status": "not-modelled", "x-status-reason": not_modelled})
    if deprecated:
        extra.update({"x-status": "deprecated", "x-deprecated": deprecated[0], "x-status-reason": deprecated[1]})
    return Field(default, description=description, ge=ge, le=le, json_schema_extra=extra or None, **kw)


def _drop_removed(name: str):
    """A before-validator for group ``name``: drop settings that were removed (``impact.REMOVED``), so configs, town
    references and snapshots written before the removal still load."""
    gone = REMOVED.get(name, ())

    def drop(cls, data: Any) -> Any:
        if gone and isinstance(data, dict) and any(k in data for k in gone):
            return {k: v for k, v in data.items() if k not in gone}
        return data

    return model_validator(mode="before")(classmethod(drop))


def group(title: str, order: int, description: str, applies: str = "town") -> ConfigDict:
    """``applies``: "town" = part of the town id (changing it generates a new town); "run" = applies to a
    simulation run of the same town."""
    return ConfigDict(extra="forbid", title=title,
                      json_schema_extra={"x-group": True, "x-order": order, "x-applies": applies,
                                         "description": description})


class EraValues(BaseModel):
    """A value per construction era: pre-1945 core, 1945–1978 post-war, post-1978 modern subdivisions."""

    model_config = ConfigDict(extra="forbid")
    pre_1945: float
    postwar: float
    modern: float

    def as_array(self) -> list[float]:
        return [self.pre_1945, self.postwar, self.modern]


class SeedsConfig(BaseModel):
    model_config = group("Seeds", 0, "Master seed and optional per-subsystem re-rolls.")
    master: str = F("TOWN-042", "Master seed. Any text or integer; same seed + config + generator version "
                    "reproduces the same town byte for byte.", effects=["everything"])
    town: str | None = F(None, "Override seed for geography only (roads growth, parcels, buildings).", advanced=True)
    households: str | None = F(None, "Override seed for household attributes (occupants, solar, EV, heating).",
                               advanced=True)
    weather: str | None = F(None, "Override seed for weather series (re-roll storms, keep the town).", advanced=True)
    incidents: str | None = F(None, "Override seed for incident hazards.", advanced=True)
    anomalies: str | None = F(None, "Override seed for the meter-to-cash run (missed reads, anomalies, analyst work, "
                              "bill checks); a request's run seed overrides it per run.", advanced=True)

    def for_(self, subsystem: str) -> str:
        v = getattr(self, subsystem, None)
        return v if v else f"{self.master}"


class TownConfig(BaseModel):
    model_config = group("Town & geography", 1, "Size, street grid, terrain and land use. Towns are generic: "
                         "every street comes from these settings and the seed.")
    drop_removed_settings = _drop_removed("town")
    houses: int = F(480, "Number of residential premises to place.", ge=20, le=10_000,
                    effects=["town extent", "era mix", "substations", "feeders", "pipe sizes", "MRUs"])
    units: Literal["ontario", "us", "uk"] = F("ontario", "Display unit profile (stored values are always SI).")
    anchor_lat: float = F(43.30, "Latitude of the town (sun path, day length).", unit="deg", ge=-80, le=80,
                          advanced=True)
    anchor_lon: float = F(-80.60, "Longitude of the town.", unit="deg", ge=-180, le=180,
                          advanced=True)
    timezone: str = F("America/Toronto", "IANA timezone of the town (read schedules, billing calendar, day/night).")
    terrain_relief_m: float = F(15.0, "Peak-to-trough terrain relief.", unit="m", ge=0, le=120,
                                effects=["water pressure zones", "PRVs", "tank siting"])
    terrain_wavelength_m: float = F(900.0, "Dominant wavelength of terrain undulation.", unit="m", ge=100, le=5000,
                                    advanced=True)
    arterial_spacing_m: float = F(1400.0, "Mean spacing of arterial roads (concession-grid style).", unit="m",
                                  ge=600, le=2400, advanced=True)
    arterial_warp_m: float = F(130.0, "Amplitude of the smooth warp applied to arterials.", unit="m", ge=0, le=400,
                               advanced=True)
    collector_block_m: float = F(650.0, "Superblocks larger than this get a collector road.", unit="m", ge=250,
                                 le=1500, advanced=True)
    era_core_year: int = F(1925, "Construction year at the town centre.", ge=1850, le=2020,
                           effects=["street pattern", "lot sizes", "overhead vs underground electric",
                                    "legacy gas district", "cast-iron water mains", "solar/EV uptake"])
    era_span_years: int = F(85, "Years added from centre to edge (era = core + span·(d/R)^1.2 + noise).", ge=0,
                            le=150)
    era_noise_years: float = F(8.0, "Std-dev of era noise per district.", unit="yr", ge=0, le=30, advanced=True)
    park_share: float = F(0.04, "Share of blocks kept as parks.", ge=0, le=0.2, advanced=True)
    commercial_strip_m: float = F(700.0, "Length of the downtown main street: arterial frontage within half this "
                                  "distance of the centre is all commercial (up to 80 lots). The frontage shares "
                                  "below apply beyond it.", unit="m", ge=0, le=3000,
                                  effects=["downtown storefronts", "homes pushed outward"])
    commercial_share_arterial: float = F(0.45, "Share of developed lots fronting an arterial (beyond the downtown "
                                         "main street) that become commercial or mixed-use premises. The rest are "
                                         "homes, or rear yards where modern subdivisions back onto the arterial.",
                                         ge=0, le=1,
                                         effects=["commercial premises", "plazas at major intersections",
                                                  "commercial hydrant spacing", "transformer pads",
                                                  "commercial accounts"])
    commercial_share_collector: float = F(0.15, "Share of developed lots fronting a collector that become "
                                          "commercial or mixed-use premises.", ge=0, le=1,
                                          effects=["commercial premises", "corner shops on collectors",
                                                   "commercial accounts"])
    commercial_share_local: float = F(0.02, "Share of developed lots on local streets that become commercial "
                                      "(corner stores near downtown and where local streets meet main roads).",
                                      ge=0, le=1, effects=["commercial premises", "homes pushed outward"])
    commercial_cluster_m: float = F(120.0, "Distance over which commercial frontage clusters around main-road "
                                    "intersections and downtown. Smaller gives tight corner clusters, larger gives "
                                    "long strips.", unit="m", ge=20, le=1000, advanced=True,
                                    effects=["where storefronts sit along main roads"])
    industrial_lots: int = F(2, "Number of large industrial customers.", ge=0, le=10)
    houses_per_school: int = F(2500, "One school per this many houses.", ge=500, le=20_000, advanced=True)
    margin_m: float = F(120.0, "Empty margin around the developed area.", unit="m", ge=0, le=1000, advanced=True)
    corridor_max_deflection_deg: float = F(35.0, "Arterial/collector road edges continue one corridor through a "
                                           "junction when the heading changes by at most this much.", unit="deg",
                                           ge=5, le=90, advanced=True,
                                           effects=["corridors", "trunk routes", "corridor changes"])
    corridor_name_bonus_deg: float = F(20.0, "Extra deflection allowed when both edges carry the same street name "
                                       "(a name is weak evidence of continuity).", unit="deg", ge=0, le=60,
                                       advanced=True, effects=["corridors"])


class HousingConfig(BaseModel):
    model_config = group("Housing & households", 2, "Lots, buildings and the people and appliances inside them.")
    drop_removed_settings = _drop_removed("housing")
    lot_frontage_m: EraValues = F(EraValues(pre_1945=15, postwar=18.5, modern=16.5),
                                  "Mean lot frontage by era.", unit="m", effects=["houses per km of street"])
    lot_depth_m: EraValues = F(EraValues(pre_1945=36, postwar=35, modern=33), "Mean lot depth by era.", unit="m")
    setback_m: EraValues = F(EraValues(pre_1945=6, postwar=7.5, modern=6.5), "Front setback by era.", unit="m",
                             advanced=True)
    two_storey_share: EraValues = F(EraValues(pre_1945=0.7, postwar=0.25, modern=0.75),
                                    "Share of two-storey houses by era.")
    occupancy_rate: float = F(0.955, "Share of premises occupied at simulation start.", ge=0.5, le=1.0,
                              effects=["vacant consumption", "VEE vacancy signals", "move-ins"])
    rental_share: float = F(0.28, "Share of premises that are rentals (more contract turnover).", ge=0, le=1,
                            effects=["move-in/out frequency", "contract history"])
    household_size_weights: list[float] = F([0.28, 0.34, 0.15, 0.15, 0.06, 0.02],
                                            "Relative frequency of households with 1..6 occupants.", advanced=True)
    solar_rate: EraValues = F(EraValues(pre_1945=0.06, postwar=0.10, modern=0.18),
                              "Share of houses with rooftop PV by era.",
                              effects=["export registers", "midday reverse flow", "net-metering credits"])
    pv_kw_min: float = F(4.0, "Smallest rooftop PV system.", unit="kW", ge=0.5, le=20)
    pv_kw_max: float = F(9.5, "Largest rooftop PV system.", unit="kW", ge=1, le=30)
    ev_rate: EraValues = F(EraValues(pre_1945=0.05, postwar=0.07, modern=0.12), "Share of houses with an EV charger.",
                           effects=["transformer loading", "evening peak"])
    electric_heat_rate: EraValues = F(EraValues(pre_1945=0.10, postwar=0.14, modern=0.18),
                                      "Share of houses heated electrically (baseboard or heat pump) where gas is "
                                      "available. All houses in all-electric districts are electric.",
                                      effects=["gas service count", "winter electric peak"])
    heat_pump_share_of_electric: float = F(0.55, "Share of electric heating that is a heat pump (vs baseboard).",
                                           ge=0, le=1, advanced=True)
    ac_rate: float = F(0.85, "Share of houses with central air conditioning.", ge=0, le=1,
                       effects=["summer peak", "transformer sizing"])
    pool_rate: float = F(0.06, "Share of houses (on lots > 600 m²) with a pool.", ge=0, le=0.5, advanced=True)
    irrigation_rate: float = F(0.30, "Share of houses that irrigate lawns in summer.", ge=0, le=1,
                               effects=["summer water peak"])


class ElectricConfig(BaseModel):
    model_config = group("Electric distribution", 3, "Bulk supply, substations, feeders, transformers, services.")
    drop_removed_settings = _drop_removed("electric")
    primary_kv: float = F(13.8, "Primary distribution line-to-line voltage (Ontario urban 13.8 kV; US 12.47 kV).",
                          unit="kV", ge=4.16, le=34.5, effects=["feeder capacity", "conductor sizing"])
    secondary_v: float = F(240.0, "Split-phase secondary voltage (120/240 V).", unit="V", ge=120, le=480,
                           advanced=True)
    kva_per_100m2: float = F(1.0, "Individual peak demand per 100 m² of floor area (lighting, plug, appliances).",
                             unit="kVA", ge=0.2, le=5, effects=["transformer sizing"])
    kva_ac: float = F(3.5, "Added peak for central air conditioning.", unit="kVA", ge=0, le=10)
    kva_electric_heat: float = F(6.0, "Added peak for electric resistance heat.", unit="kVA", ge=0, le=20)
    kva_heat_pump: float = F(4.0, "Added peak for a heat pump.", unit="kVA", ge=0, le=15)
    kva_ev: float = F(7.2, "Added peak for a Level-2 EV charger.", unit="kVA", ge=0, le=20)
    kva_pool: float = F(1.5, "Added peak for a pool pump/heater.", unit="kVA", ge=0, le=10, advanced=True)
    coincidence_floor: float = F(0.33, "Coincidence factor CF(n) = a + (1-a)/√n; a is the floor as n → ∞.", ge=0.1,
                                 le=1.0, effects=["every electric size"], advanced=True)
    transformer_kva_steps: list[float] = F([25, 50, 75, 100, 167], "Single-phase transformer sizes.", unit="kVA",
                                           advanced=True)
    transformer_max_loading: float = F(1.3, "Allowed peak loading relative to nameplate.", ge=0.8, le=2.0,
                                       advanced=True)
    conductor_planning_margin: float = F(1.25, "Primary conductors are sized for design load × this margin (winter "
                                         "peaks, load growth).", ge=1.0, le=2.0,
                                         effects=["primary conductor sizes", "loading in power flow"], advanced=True)
    max_houses_per_transformer_overhead: int = F(6, "Max houses on a pole-mount transformer.", ge=1, le=20)
    max_houses_per_transformer_underground: int = F(10, "Max houses on a pad-mount transformer.", ge=1, le=25)
    feeder_design_mva: float = F(6.0, "Design peak per feeder.", unit="MVA", ge=1, le=20,
                                 effects=["feeder count", "tie switches"])
    feeder_max_customers: int = F(1200, "Most customers planned on one feeder (limits how many lose supply when a "
                                  "feeder breaker trips).", ge=100, le=10_000,
                                  effects=["feeder count", "feeder territories", "tie switches"])
    min_feeders_per_substation: int = F(2, "Feeders leaving each substation at least (fewer only when it serves "
                                        "fewer transformer groups), so normally-open ties can back-feed.", ge=1,
                                        le=12, effects=["feeder count", "tie switches", "outage size"])
    substation_mva: float = F(25.0, "Firm capacity per substation.", unit="MVA", ge=5, le=100,
                              effects=["substation count"])
    route_weight_arterial: float = F(1.0, "Feeder routing cost per metre along an arterial (trunks follow the "
                                     "cheapest corridors).", ge=0.1, le=10, advanced=True,
                                     effects=["trunk routes", "feeder territories"])
    route_weight_collector: float = F(1.4, "Feeder routing cost per metre along a collector.", ge=0.1, le=10,
                                      advanced=True, effects=["trunk routes"])
    route_weight_local: float = F(2.0, "Feeder routing cost per metre along a local street.", ge=0.1, le=10,
                                  advanced=True, effects=["trunk routes", "lateral routes"])
    route_turn_penalty_m: float = F(60.0, "Routing cost of a 90° turn, in weighted metres; it grows with the "
                                    "square of the angle (a U-turn costs 4×). Bends under 10° are free.", unit="m",
                                    ge=0, le=2000, advanced=True, effects=["trunk continuity", "severe turns"])
    route_corridor_change_penalty_m: float = F(80.0, "Routing cost of switching from one arterial/collector "
                                               "corridor to another.", unit="m", ge=0, le=2000, advanced=True,
                                               effects=["trunk continuity", "corridor changes"])
    route_hierarchy_penalty_m: float = F(60.0, "Routing cost per step up or down the road hierarchy "
                                         "(arterial ↔ collector ↔ local).", unit="m", ge=0, le=2000, advanced=True,
                                         effects=["trunks staying on main roads"])
    trunk_min_load_share: float = F(0.04, "A feeder trunk extends along a corridor while at least this share of "
                                    "the feeder's connected load lies at or beyond that point; smaller tails are "
                                    "served by laterals.", ge=0, le=0.5, advanced=True,
                                    effects=["trunk length", "three-phase backbone"])
    route_shared_trunk_factor: float = F(1.2, "Cost multiplier for running a feeder express through another "
                                         "feeder's territory or alongside its trunk.", ge=1.0, le=5.0,
                                         advanced=True, effects=["express sections", "feeder separation"])
    ties_per_feeder_pair: int = F(1, "Normally-open tie switches between each pair of neighbouring feeders (0: no "
                                  "ties at all, section ties included).", ge=0, le=4,
                                  effects=["tie switches", "back-feed options"])
    tie_max_length_m: float = F(1200.0, "Longest new line built for a tie: to a feeder that touches no other "
                                "feeder, or from a switched section to another feeder's three-phase line (or round "
                                "to its own feeder's). Along a street a line already uses, a metre counts 1.25 "
                                "(single-phase) or 2 (three-phase).", unit="m", ge=0, le=5000, advanced=True,
                                effects=["tie switches", "back-feed options"])
    section_max_share: float = F(0.15, "Sectionalising switches cut each feeder's three-phase backbone into "
                                 "sections of at most this share of the feeder's customers (at least "
                                 "section_min_customers), so a crew isolates a fault within a bounded section and "
                                 "ties back-feed the healthy sections beyond it.", ge=0.05, le=1.0,
                                 effects=["sectionalising switches", "tie switches", "outage size after isolation"])
    section_min_customers: int = F(100, "Smallest section limit: a feeder is not cut into sections smaller than "
                                   "this many customers.", ge=10, le=5000, advanced=True,
                                   effects=["sectionalising switches", "outage size after isolation"])
    overhead_before_year: int = F(1978, "Districts built before this year are overhead (poles); later underground.",
                                  ge=1850, le=2030, effects=["poles", "lightning exposure", "storm outages"])
    pole_spacing_m: float = F(42.0, "Pole span on overhead lines.", unit="m", ge=20, le=90, advanced=True)
    voltage_min_pu: float = F(0.95, "Lower service voltage limit (CSA CAN3-C235 / ANSI Range A). Frames report it "
                              "on a 120 V base (premises.voltageLimits) with the premises below it; less 4 V it is "
                              "the default floor for back-feeding through a tie.", ge=0.85, le=1.0, advanced=True,
                              effects=["low-voltage premises", "voltage lens", "back-feed voltage floor"])
    voltage_max_pu: float = F(1.05, "Upper service voltage limit (premises.voltageLimits in frames).", ge=1.0,
                              le=1.15, advanced=True, effects=["high-voltage premises", "voltage lens"])


class GasConfig(BaseModel):
    model_config = group("Natural gas", 4, "City gate, mains, regulators and services.")
    all_electric_district_share: float = F(0.15, "Share of districts with no gas mains (all-electric).", ge=0, le=1,
                                           effects=["gas services", "electric heat share", "winter electric peak"])
    scheme: Literal["mp", "mp_with_lp_core"] = F("mp_with_lp_core", "Medium-pressure PE everywhere with a regulator "
                                                 "at every meter, optionally with a legacy low-pressure core fed by "
                                                 "district regulators.")
    transmission_kpa: float = F(3800.0, "Off-map transmission pressure at the city gate inlet.", unit="kPa", ge=700,
                                le=10_000, advanced=True)
    mp_kpa: float = F(414.0, "Medium-pressure distribution set point (60 psig).", unit="kPa", ge=35, le=700)
    lp_kpa: float = F(1.74, "Low-pressure legacy main set point (7 in w.c.).", unit="kPa", ge=0.5, le=7,
                      advanced=True)
    lp_core_before_year: int = F(1945, "Districts built before this year are on the low-pressure system.", ge=1850,
                                 le=2000, advanced=True)
    design_m3h_base: float = F(1.15, "Design-hour demand per house, base component (≈ 40 CFH).", unit="m3/h", ge=0,
                               le=10)
    design_m3h_per_m2: float = F(0.017, "Design-hour demand per m² of floor area (≈ 0.6 CFH/m²).", unit="m3/h",
                                 ge=0, le=0.2)
    coincidence_floor: float = F(0.5, "Gas coincidence factor floor a in CF(n) = a + (1-a)/√n.", ge=0.1, le=1,
                                 advanced=True)
    min_main_mm: int = F(50, "Smallest distribution main (2-inch PE).", unit="mm", ge=25, le=150)
    valve_spacing_m: float = F(800.0, "Maximum spacing of main valves on feeders.", unit="m", ge=100, le=3000,
                               advanced=True)
    calorific_mj_per_m3: float = F(37.5, "Higher heating value used for energy conversion (therm/kWh display and "
                                   "billing).", unit="MJ/m3", ge=30, le=45,
                                   effects=["gas bill energy", "therm/kWh conversion"])
    base_pressure_kpa: float = F(101.559771, "Base pressure for standard volume: the Weymouth base pressure in gas "
                                 "main sizing and pressures (default 14.73 psia).", unit="kPa", ge=90, le=110,
                                 advanced=True, effects=["gas main sizes", "gas pressures"])
    base_temperature_c: float = F(15.738889, "Base temperature for standard volume: the Weymouth base temperature "
                                  "(default 520 °R, about 60 °F).", unit="C", ge=0, le=25, advanced=True,
                                  effects=["gas main sizes", "gas pressures"])


class WaterConfig(BaseModel):
    model_config = group("Water distribution", 5, "Supply, pumping, storage, mains, hydrants and services.")
    lpcd: float = F(220.0, "Indoor residential use per person per day.", unit="L", ge=50, le=600,
                    effects=["water bills", "peak flow"])
    irrigation_m3_per_day: float = F(0.6, "Summer irrigation per irrigating house.", unit="m3", ge=0, le=5)
    max_day_factor: float = F(2.0, "Max-day / average-day ratio.", ge=1, le=4, advanced=True)
    peak_hour_factor: float = F(3.0, "Peak-hour / average-day ratio.", ge=1, le=6, advanced=True)
    fire_flow_residential_lps: float = F(63.0, "Required residential fire flow (1,000 USgpm).", unit="L/s", ge=0,
                                         le=200, effects=["minimum main size", "hydrants"])
    fire_flow_commercial_lps: float = F(95.0, "Required commercial/institutional fire flow.", unit="L/s", ge=0,
                                        le=300, advanced=True)
    fire_flow_industrial_lps: float = F(190.0, "Required industrial fire flow.", unit="L/s", ge=0, le=500,
                                        advanced=True)
    min_main_mm: int = F(150, "Smallest main where hydrants are attached.", unit="mm", ge=100, le=300)
    collector_main_mm: int = F(300, "Minimum main on collector roads.", unit="mm", ge=150, le=600, advanced=True)
    arterial_main_mm: int = F(400, "Minimum transmission main on arterials leaving the pump station.", unit="mm",
                              ge=200, le=900, advanced=True)
    hw_c_new: float = F(130.0, "Hazen-Williams C for PVC/ductile iron mains.", ge=60, le=150, advanced=True,
                        effects=["head loss", "service pressure"])
    hw_c_old: float = F(100.0, "Hazen-Williams C for unlined cast iron mains.", ge=40, le=140, advanced=True,
                        effects=["head loss", "service pressure"])
    cast_iron_before_year: int = F(1960, "Mains along streets built before this year are unlined cast iron (the "
                                   "concrete trunk excepted).", ge=1850, le=2000,
                                   effects=["cast-iron mains", "main break rate (×2)", "head loss"])
    tank_overflow_above_ground_m: float = F(42.0, "Elevated tank overflow height above the highest service in its "
                                            "zone.", unit="m", ge=20, le=80, effects=["service pressure"])
    zone_band_m: float = F(28.0, "Elevation band per pressure zone.", unit="m", ge=10, le=60, advanced=True)
    hydrant_spacing_m: float = F(150.0, "Hydrant spacing on residential mains.", unit="m", ge=50, le=300)
    hydrant_spacing_commercial_m: float = F(90.0, "Hydrant spacing in commercial areas.", unit="m", ge=40, le=200,
                                            advanced=True)
    valve_spacing_m: float = F(240.0, "Maximum spacing between line valves.", unit="m", ge=60, le=600,
                               advanced=True)
    pump_units: int = F(3, "Pumps at the booster station (one is standby).", ge=1, le=8, advanced=True)


class AmiConfig(BaseModel):
    model_config = group("Metering & AMI", 6, "Meter technology mix, AMI collectors and nightly collection.")
    drop_removed_settings = _drop_removed("ami")
    ami_route_share: float = F(0.60, "Share of meter reading routes converted to AMI.", ge=0, le=1,
                               effects=["meter vans", "manual reads", "estimates", "VEE comm-fail flags"])
    amr_route_share: float = F(0.25, "Share of routes read by drive-by AMR vans (rest are walked manually).", ge=0,
                               le=1, effects=["van routes", "walker routes"])
    collector_radius_m: float = F(900.0, "AMI collector coverage radius.", unit="m", ge=200, le=3000,
                                  effects=["collector count", "comm-fail clusters"])
    poll_start_hour: float = F(1.0, "Nightly head-end poll window start (local time).", unit="h", ge=0, le=24)
    poll_end_hour: float = F(4.0, "Nightly head-end poll window end.", unit="h", ge=0, le=24)
    meter_digits_electric: int = F(6, "Register digits on electric meters (rollover at 10^digits).", ge=4, le=9,
                                   advanced=True)
    meter_digits_water: int = F(6, "Register digits on water meters.", ge=4, le=9, advanced=True)
    meter_digits_gas: int = F(5, "Register digits on gas meters.", ge=4, le=9, advanced=True)


class SeasonTemp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mean_c: float
    sd_c: float
    min_c: float
    max_c: float


class WeatherConfig(BaseModel):
    model_config = group("Weather", 7, "Seeded daily weather. Drives magnitudes and volumes, never process "
                         "structure.")
    winter: SeasonTemp = F(SeasonTemp(mean_c=-4.5, sd_c=6.5, min_c=-28, max_c=12), "Winter (Dec 21–Mar 20).")
    spring: SeasonTemp = F(SeasonTemp(mean_c=9.0, sd_c=6.0, min_c=-8, max_c=30), "Spring (Mar 21–Jun 20).")
    summer: SeasonTemp = F(SeasonTemp(mean_c=21.5, sd_c=4.0, min_c=10, max_c=37), "Summer (Jun 21–Sep 20).")
    fall: SeasonTemp = F(SeasonTemp(mean_c=9.5, sd_c=6.5, min_c=-10, max_c=28), "Fall (Sep 21–Dec 20).")
    persistence: float = F(0.7, "Day-to-day AR(1) persistence of temperature anomalies.", ge=0, le=0.98,
                           advanced=True)
    storm_days_per_year: float = F(28.0, "Thunderstorm days per year (mostly May–Sep).", ge=0, le=120,
                                   effects=["lightning outages", "estimated reads"])
    heating_base_c: float = F(15.0, "Heating starts below this temperature.", unit="C", ge=5, le=22, advanced=True)
    cooling_base_c: float = F(22.0, "Cooling starts above this temperature.", unit="C", ge=15, le=30, advanced=True)


class IncidentConfig(BaseModel):
    model_config = group("Incidents & hazards", 8, "What goes wrong, how often. Rates are per year. Each operations "
                         "day draws its background incidents at these rates; they are the defaults of the operations "
                         "run's random-incident settings (x-run-setting), so a run can change them without a new "
                         "town.")
    gas_service_leaks_per_1000: float = F(1.2, "Leaks per 1,000 gas services per year.", ge=0, le=50)
    gas_main_leaks_per_100km: float = F(8.0, "Leaks per 100 km of gas main per year.", ge=0, le=200)
    water_main_breaks_per_100km: float = F(14.0, "Main breaks per 100 km per year (×2 for cast iron).", ge=0, le=200,
                                           effects=["water outages", "crew workload"])
    overhead_faults_per_km_storm_day: float = F(0.015, "Overhead primary faults per km per storm day.", ge=0, le=1,
                                                effects=["outages", "SAIDI/SAIFI", "zero-usage reads"])
    transformer_failures_per_1000: float = F(3.0, "Transformer failures per 1,000 units per year (×3 when "
                                             "overloaded).", ge=0, le=100)
    collector_outages_per_year: float = F(2.0, "AMI collector outages per year (town-wide).", ge=0, le=50)
    manual_only: bool = F(False, "Disable random hazards; only manually injected incidents occur (the run's "
                          "\"Random incidents\" switch defaults to the opposite).", effects=["background incidents"])


class OperationsConfig(BaseModel):
    model_config = group("Field operations", 9, "Fleet, shifts, response targets and vehicle movement. Crews, readers, "
                         "the shift and the gas target are the defaults of the operations run settings "
                         "(x-run-setting), so a run can change them without a new town.")
    drop_removed_settings = _drop_removed("operations")
    gas_crews: int = F(2, "Gas emergency crews.", ge=0, le=20, effects=["leak response time"])
    electric_crews: int = F(3, "Electric trouble crews.", ge=0, le=30, effects=["outage duration", "SAIDI"])
    water_crews: int = F(2, "Water distribution crews.", ge=0, le=20)
    meter_techs: int = F(2, "Meter technicians (exchanges, investigations).", ge=0, le=20)
    meter_vans: int = F(2, "Drive-by AMR reading vans.", ge=0, le=20, effects=["AMR read completion"])
    meter_walkers: int = F(3, "Manual meter readers.", ge=0, le=40, effects=["manual read completion", "no-access"])
    shift_start_hour: float = F(7.0, "Day shift start. Non-emergency work (AMI collector repairs) waits for the day "
                                "shift; emergencies are worked around the clock.", unit="h", ge=0, le=23,
                                effects=["collector outage length"])
    shift_end_hour: float = F(15.5, "Day shift end.", unit="h", ge=1, le=24, effects=["collector outage length"])
    gas_response_target_min: float = F(60.0, "Target response to a gas odour call.", unit="min", ge=10, le=240)
    speed_kmh_arterial: float = F(50.0, "Driving speed on arterials.", unit="km/h", ge=10, le=100, advanced=True)
    speed_kmh_collector: float = F(40.0, "Driving speed on collectors.", unit="km/h", ge=10, le=80, advanced=True)
    speed_kmh_local: float = F(30.0, "Driving speed on local streets.", unit="km/h", ge=5, le=60, advanced=True)


class RateBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    up_to: float | None
    price: float


class CustomersBillingConfig(BaseModel):
    model_config = group("Customers & billing", 10, "Accounts, reading routes, calendars and tariffs.")
    mru_target_meters: int = F(450, "Target premises per meter reading unit (route).", ge=50, le=3000,
                               effects=["route count", "read workload per day"])
    bill_cycles: int = F(21, "Billing portions per month (one per working day).", ge=1, le=31)
    currency: str = F("CAD", "Billing currency.")
    tax_rate: float = F(0.13, "Sales tax on utility bills (Ontario HST).", ge=0, le=0.3)
    electric_fixed_monthly: float = F(36.50, "Electric fixed delivery charge per month.", unit="$", ge=0, le=500)
    electric_blocks: list[RateBlock] = F([RateBlock(up_to=600, price=0.098), RateBlock(up_to=None, price=0.116)],
                                         "Electric energy price blocks per kWh (summer threshold).", unit="$/kWh")
    electric_variable_delivery: float = F(0.042, "Electric variable delivery per kWh.", unit="$/kWh", ge=0, le=1)
    net_metering_credit: float = F(0.098, "Credit per exported kWh.", unit="$/kWh", ge=0, le=1,
                                   effects=["solar customer bills"])
    gas_fixed_monthly: float = F(26.50, "Gas customer charge per month.", unit="$", ge=0, le=500)
    gas_price_m3: float = F(0.36, "Gas delivery + supply per m³.", unit="$/m3", ge=0, le=5)
    water_fixed_monthly: float = F(18.00, "Water fixed charge per month.", unit="$", ge=0, le=500)
    water_price_m3: float = F(2.15, "Water volumetric charge.", unit="$/m3", ge=0, le=20)
    wastewater_ratio: float = F(1.05, "Wastewater charge as a multiple of the water volumetric charge.", ge=0, le=3)
    on_time_payer_share: float = F(0.82, "Share of accounts that pay on time.", ge=0, le=1,
                                   effects=["dunning", "collections", "carrying cost"])
    late_payer_share: float = F(0.14, "Share that pay late.", ge=0, le=1)
    pre_authorized_share: float = F(0.45, "Share on pre-authorized debit.", ge=0, le=1, advanced=True)
    due_days: int = F(20, "Days from invoice to due date.", ge=5, le=60)


class ProcessConfig(BaseModel):
    model_config = group("Meter-to-cash process", 11, "Work queues, automation, workforce, costs and carrying cost.",
                         applies="run")
    drop_removed_settings = _drop_removed("process")
    rpa_coverage: float = F(0.35, "Share of exception types with an RPA/auto-resolve rule.", ge=0, le=1,
                            effects=["analyst workload", "days to invoice", "carrying cost"])
    analyst_queue_days_min: int = F(1, "Minimum queue wait before an analyst picks up an exception.", ge=1, le=10)
    analyst_queue_days_max: int = F(3, "Maximum queue wait.", ge=1, le=20)
    carry_rate_per_day: float = F(1.25, "Carrying cost per account per day before invoicing.", unit="$", ge=0,
                                  le=20)
    receivable_carry_ratio: float = F(0.4, "Receivable carry as a share of the billing carry rate.", ge=0, le=1,
                                      advanced=True)
    analysts: int = F(2, "Billing analysts working the exception queues.", ge=0, le=200,
                      effects=["queue backlog", "days to bill", "carrying cost"])
    analyst_hours_per_day: float = F(6.0, "Productive queue hours per analyst per business day.", unit="h", ge=0.5,
                                     le=10)
    review_minutes_min: float = F(15.0, "Shortest analyst review.", unit="min", ge=1, le=240, advanced=True)
    review_minutes_max: float = F(30.0, "Longest analyst review.", unit="min", ge=1, le=480, advanced=True)
    supervisors: int = F(1, "Supervisors approving escalations.", ge=0, le=50, effects=["escalation backlog"])
    supervisor_hours_per_day: float = F(2.0, "Supervisor hours on escalations per business day.", unit="h", ge=0.25,
                                        le=10, advanced=True)
    supervisor_minutes: float = F(40.0, "Supervisor review time per escalation.", unit="min", ge=5, le=240,
                                  advanced=True)
    supervisor_queue_days_min: int = F(1, "Minimum wait before a supervisor picks up an escalation (VEE's own "
                                       "escalations wait this long).", unit="d", ge=1, le=20,
                                       effects=["escalation backlog", "days to bill"])
    supervisor_queue_days_max: int = F(3, "Maximum wait before a supervisor picks up an escalation from an analyst "
                                       "or you. An escalation you take yourself (assign) waits for you.", unit="d",
                                       ge=1, le=30, effects=["escalation backlog", "days to bill"])
    field_orders_per_day: int = F(6, "Meter investigations, re-reads and exchanges completed per business day.",
                                  ge=0, le=500, effects=["field order backlog", "estimates"])
    field_days_min: int = F(1, "Earliest a field order is worked after it is raised.", unit="d", ge=0, le=20,
                            advanced=True)
    analyst_accuracy: float = F(0.95, "Share of reviews where the analyst finds the true cause.", ge=0.5, le=1,
                                advanced=True, effects=["billing errors", "wasted truck rolls"])


class AnomaliesConfig(BaseModel):
    model_config = group("Meter & read anomalies", 12, "Injected faults with ground truth. Rates per 1,000 meters "
                         "per year.", applies="run")
    enabled: bool = F(True, "Inject anomalies into observed reads (truth is always kept separately).")
    leak: float = F(8.0, "Continuous post-meter water leaks.", ge=0, le=200)
    stuck_meter: float = F(5.0, "Registers that stop advancing.", ge=0, le=200)
    slow_meter: float = F(4.0, "Meters under-registering 10–40%.", ge=0, le=200)
    transposed_digits: float = F(6.0, "Reads with two digits swapped.", ge=0, le=200)
    misread: float = F(6.0, "Reads off by one in a high digit.", ge=0, le=200)
    consecutive_estimates: float = F(15.0, "Runs of 2–4 estimated periods (higher on manual routes).", ge=0,
                                     le=200)
    missing_read: float = F(5.0, "Periods with no read document.", ge=0, le=200)
    exchange_registration_failure: float = F(2.0, "Meter exchanges whose new serial fails registration.", ge=0,
                                             le=100)
    vacant_consuming: float = F(3.0, "Vacant premises that still consume.", ge=0, le=100)
    tamper: float = F(1.0, "Bypass/tamper (50–90% under-registration).", ge=0, le=50)
    amr_factor: float = F(1.0, "Multiplier on every anomaly rate for AMR (drive-by) meters: an ageing ERT fleet "
                          "misreads and under-registers more.", ge=0, le=20, advanced=True)
    manual_factor: float = F(1.0, "Multiplier on every anomaly rate for manually read meters.", ge=0, le=20,
                             advanced=True)


class ReadingConfig(BaseModel):
    model_config = group("Meter reading", 14, "How periodic billing reads succeed or fail, by meter technology.",
                         applies="run")
    ami_missed_read: float = F(0.012, "AMI billing reads still missing after the head-end retry window.", ge=0, le=0.5,
                               effects=["comm-fail exceptions", "estimates"])
    amr_missed_read: float = F(0.03, "Drive-by reads missed (no signal, street skipped).", ge=0, le=0.5)
    manual_no_access: float = F(0.06, "Manual reads with no access (locked gate, dog, meter inside).", ge=0, le=0.8,
                                effects=["no-access exceptions", "consecutive estimates"])
    no_access_repeat: float = F(0.4, "Chance a missed manual read is missed again the next month.", ge=0, le=1,
                                advanced=True)
    read_cost_ami: float = F(0.10, "Cost of one AMI read.", unit="$", ge=0, le=20, advanced=True)
    read_cost_amr: float = F(0.35, "Cost of one drive-by read.", unit="$", ge=0, le=20, advanced=True)
    read_cost_manual: float = F(1.20, "Cost of one walked read.", unit="$", ge=0, le=50, advanced=True)


class VeeConfig(BaseModel):
    model_config = group("VEE rules", 15, "Validation, estimation and editing: the five-test battery, confidence "
                         "and disposition (VEE v5 shape).", applies="run")
    high_ratio: float = F(2.0, "Flag consumption above this multiple of expected (tolerance high).", ge=1.1, le=10,
                          effects=["flagged reads", "analyst workload"])
    low_ratio: float = F(0.35, "Flag consumption below this share of expected (tolerance low).", ge=0, le=0.95)
    zero_at_occupied: bool = F(True, "Flag zero consumption at an occupied premise.")
    max_consecutive_estimates: int = F(2, "Estimates in a row before a field read is ordered.", ge=1, le=12,
                                       effects=["field orders"])
    min_period_days: int = F(25, "Shortest plausible read period.", unit="d", ge=1, le=40, advanced=True)
    max_period_days: int = F(38, "Longest plausible read period.", unit="d", ge=20, le=120, advanced=True)
    accept_confidence: float = F(0.75, "Auto-accept at or above this confidence.", ge=0, le=1,
                                 effects=["auto-accept rate", "billing errors"])
    reject_confidence: float = F(0.35, "Reject below this confidence.", ge=0, le=1)
    escalate_impact: float = F(150.0, "Escalate a doubtful read when its bill impact exceeds this.", unit="$", ge=0,
                               le=10000, effects=["supervisor workload"])
    trend_ratio: float = F(0.8, "Persistent low use: flag reads below this share of expected …", ge=0.3, le=1.0,
                           effects=["slow and tampered meters found"])
    trend_periods: int = F(3, "… for this many periods in a row.", ge=2, le=12)
    oms_events: bool = F(True, "Use outage events (OMS, AMI last gasps) from operations: hours without service "
                         "lower the expected use.", effects=["low-usage flags after outages"])
    estimation: Literal["prior_year", "recent_average"] = F("prior_year", "Estimation method for missing or "
                                                            "rejected reads.")
    history_noise: float = F(0.10, "Spread of prior-year history around this year's normal usage.", ge=0, le=0.5,
                             advanced=True)


class BillingConfig(BaseModel):
    model_config = group("Billing & collections", 16, "Bill checks, tariff versions, invoicing, payments and dunning.",
                         applies="run")
    rate_change_date: str = F("2026-11-01", "Date a new tariff version takes effect (volumetric prices).")
    rate_change_pct: float = F(3.5, "Volumetric price change in the new tariff version.", unit="%", ge=-50, le=100,
                               effects=["bills after the change", "proration"])
    high_bill_ratio: float = F(2.5, "Block a bill above this multiple of its expected amount (prior-year use at "
                               "current prices).", ge=1.1, le=20, effects=["billing blocks", "analyst workload"])
    high_bill_min: float = F(150.0, "…and at least this much above the expected amount.", unit="$", ge=0, le=5000)
    first_bill_limit: float = F(600.0, "Block a bill with no expected use (vacant, new) above this total.", unit="$",
                                ge=0, le=10000, advanced=True)
    credit_review: float = F(75.0, "Block a bill that is a credit larger than this.", unit="$", ge=0, le=5000,
                             advanced=True)
    outsort_auto_release_max: float = F(500.0, "RPA may release a high-bill or large-credit outsort only up to this "
                                        "bill amount (either sign); a larger one waits for an analyst.", unit="$",
                                        ge=0, le=100000, effects=["analyst workload", "billing errors"])
    billing_queue_worked_by: Literal["analysts", "you"] = F(
        "analysts", "Who works the BILLING queue (high bills, large credits, true-ups, rate-class errors): the "
        "simulated analysts and RPA, or only you. With 'you', no analyst or RPA touches a billing block, so every "
        "outsort waits in the Studio for your release, rebill or escalation.",
        effects=["billing blocks", "days to invoice", "billing carry"])
    trueup_max_ratio: float = F(3.0, "Block a bill whose estimate true-up (a negative period quantity) is larger than "
                                "this multiple of the period's expected use; an analyst decides it.", unit="×", ge=1,
                                le=50, advanced=True, effects=["billing blocks", "billing errors"])
    data_error_rate: float = F(3.0, "Installations with a wrong rate class in billing master data (per 1,000 per "
                               "year).", ge=0, le=200, effects=["rate-class billing blocks"])
    print_lag_days: int = F(1, "Days from invoice creation to issue.", unit="d", ge=0, le=10, advanced=True)
    pad_reject_rate: float = F(0.015, "Pre-authorized debits returned for insufficient funds.", ge=0, le=0.5,
                               effects=["payment rejections", "collections"])
    nsf_fee: float = F(20.0, "Fee for a returned payment.", unit="$", ge=0, le=100, advanced=True)
    late_fee_pct: float = F(1.5, "Late payment charge on overdue amounts (per notice).", unit="%", ge=0, le=5)
    reminder_days: int = F(7, "Days after the due date for a reminder.", unit="d", ge=1, le=60)
    notice_days: int = F(21, "Days after the due date for an overdue notice and late fee.", unit="d", ge=1, le=90)
    disconnect_days: int = F(45, "Days after the due date for a disconnection notice.", unit="d", ge=5, le=180,
                             effects=["disconnection notices"])
    winter_moratorium: bool = F(True, "No disconnection notices for electricity and water from Nov 15 to Apr 30 "
                                "(Ontario); a notice held for the winter is issued on May 1 if the bill is still "
                                "unpaid.")
    moratorium_start: str = F("11-15", "First day of the winter moratorium (MM-DD).", advanced=True)
    moratorium_end: str = F("04-30", "Last day of the winter moratorium (MM-DD); held notices go out the day after.",
                            advanced=True)
    disconnect_notice_days: int = F(10, "Days from a disconnection notice to the earliest disconnection. A "
                                    "disconnection also needs a person's approval (the Collections worklist).",
                                    unit="d", ge=1, le=60, effects=["disconnections"])
    disconnect_rule_share: float = F(0.0, "Share of disconnection notices a collections rule approves when they are "
                                     "issued (the disconnection follows at the earliest day); the rest wait for a "
                                     "person's approval. 0: every disconnection needs you.", ge=0, le=1,
                                     effects=["disconnections", "field disconnects and reconnects"])
    disconnect_payment_rate: float = F(0.6, "Disconnected customers who pay within a week of the disconnection (and "
                                       "are reconnected the next business day); the rest stay off until they pay.",
                                       ge=0, le=1, advanced=True, effects=["collections", "reconnections"])
    arrangement_break_rate: float = F(0.3, "At-risk payers who break a payment arrangement after a few instalments "
                                      "(dunning resumes); other payers pay every instalment.", ge=0, le=1,
                                      advanced=True, effects=["collections"])
    low_income_referral_rate: float = F(0.15, "Disconnection notices and winter moratorium holds after which the call "
                                        "centre refers the customer to a low-income programme (once a year per "
                                        "account).", ge=0, le=1,
                                        effects=["Low Income Process cases", "disconnections"])
    low_income_review_days: int = F(10, "Business days the low-income agency takes to decide a referral; dunning "
                                    "waits meanwhile.", unit="d", ge=1, le=60, advanced=True)
    low_income_approval_rate: float = F(0.7, "Referrals the agency approves with a grant.", ge=0, le=1,
                                        effects=["collections", "receivable"])
    low_income_grant_max: float = F(500.0, "Largest low-income grant credited to an account's arrears.", unit="$",
                                    ge=0, le=5000, advanced=True)
    budget_billing_offer_rate: float = F(0.08, "Overdue notices after which the call centre enrols the customer in "
                                         "budget billing (once a year per account); the plan levels later "
                                         "invoices.", ge=0, le=1, effects=["Budget Bill Cases", "collections"])


class ScenarioConfig(BaseModel):
    model_config = group("Scenario", 13, "Demonstration scenario on the live clock.", applies="run")
    drop_removed_settings = _drop_removed("scenario")
    name: Literal["normal", "solar_noon", "leak", "substation_outage"] = F(
        "normal", "Live demonstration scenario.")
    date: str = F("2026-07-15", "Demonstration date (local).")
    hour: float = F(8.0, "Demonstration hour (local, decimal).", unit="h", ge=0, lt=24)
    target_premise: str | None = F(None, "Premise targeted by the leak scenario (default: first premise).")
    leak_m3h: float = F(0.65, "Leak rate added to the target premise's water demand.", unit="m3/h", ge=0, le=50)


class ContactReason(BaseModel):
    """One reason customers contact the utility: how often it happens and what handling it takes."""

    model_config = ConfigDict(extra="forbid")
    per_event: float = Field(0.0, ge=0, le=1, description="Share of triggering events that lead to a contact.")
    per_1000: float = Field(0.0, ge=0, le=500, description="Background contacts per 1,000 accounts per month.")
    self_serve: float = Field(0.0, ge=0, le=1, description="Share handled by the IVR or online, with no agent.")
    handle_min: float = Field(6.0, ge=0.5, le=120, description="Agent minutes per contact (talk and wrap-up).")
    resolved: float = Field(0.9, ge=0, le=1, description="Share resolved on the first contact.")


def _reason(per_event: float, per_1000: float, self_serve: float, handle_min: float, resolved: float, text: str):
    return F(ContactReason(per_event=per_event, per_1000=per_1000, self_serve=self_serve, handle_min=handle_min,
                           resolved=resolved), text)


class ContactConfig(BaseModel):
    model_config = group("Contact centre", 17, "Why customers phone, write or use the IVR, and the agents, hours and "
                         "self-service that answer them. Contacts follow the year: bills, errors, rebills, dunning, "
                         "payments, move-ins and move-outs, missed reads and the year's outages and gas leaks.",
                         applies="run")
    agents: int = F(1, "Agents on the phones on a business day (a small utility often has one, shared with billing).",
                    ge=0, le=500, effects=["wait", "abandonment"])
    open_hour: float = F(8.0, "Lines open (local time, business days).", unit="h", ge=0, le=23)
    close_hour: float = F(17.0, "Lines close (local time).", unit="h", ge=1, le=24)
    patience_s: float = F(240.0, "Average time a caller waits before hanging up.", unit="s", title="Patience", ge=10,
                          le=3600)
    retry_share: float = F(0.6, "Callers who hung up or found the lines closed and try again.", ge=0, le=1)
    repeat_share: float = F(0.5, "Callers whose problem was not resolved who contact again within days.", ge=0, le=1)
    callback: bool = F(True, "Offer a call back instead of holding when the wait is long.")
    callback_after_s: float = F(300.0, "Offer the call back when the expected wait exceeds this.", unit="s",
                                title="Call back after", ge=0, le=3600, advanced=True)
    callback_take_share: float = F(0.5, "Callers offered a call back who take it.", ge=0, le=1, advanced=True)
    service_target_s: float = F(30.0, "Answer target for the service level (answered within it).", unit="s",
                                title="Service target", ge=5, le=600)
    volume_factor: float = F(1.0, "Multiplies every reason's contact rates.", ge=0, le=20)
    handle_factor: float = F(1.0, "Multiplies every reason's handling time.", ge=0.1, le=10)
    self_serve_factor: float = F(1.0, "Multiplies every reason's self-service share (0: IVR and web down).", ge=0,
                                 le=3)
    agent_cost_per_hour: float = F(38.0, "Loaded cost of an agent hour on the phones.", unit="$", ge=0, le=500,
                                   advanced=True)
    self_serve_cost: float = F(0.40, "Cost of a contact the IVR or website handles.", unit="$", ge=0, le=50,
                               advanced=True)
    abandon_cx_cost: float = F(6.0, "Customer-experience cost of a caller who hangs up.", unit="$", ge=0, le=200,
                               advanced=True)
    emergency_answer_s: float = F(15.0, "Answer time on the emergency line (gas odour, outages after hours).",
                                  unit="s", title="Emergency answer", ge=1, le=600, advanced=True)
    high_bill: ContactReason = _reason(0.25, 2.0, 0.1, 7.5, 0.85, "High bill: an invoice at least 1.5 times what "
                                       "the account usually pays (and $40 more).")
    bill_question: ContactReason = _reason(0.008, 1.5, 0.2, 6.0, 0.9, "Questions about a bill: any invoice, more for "
                                           "estimated bills, first bills and bills after a rate change.")
    bill_wrong: ContactReason = _reason(0.35, 0.3, 0.0, 11.0, 0.6, "Bill wrong: a bill that overcharges the "
                                        "customer (customers rarely call about undercharges).")
    back_bill: ContactReason = _reason(0.45, 0.0, 0.0, 12.0, 0.7, "Back bill: a rebill, or the first actual bill "
                                       "after estimates, that catches up on under-billed use.")
    balance: ContactReason = _reason(0.03, 4.0, 0.75, 3.0, 0.98, "What's my balance: around due dates; mostly the "
                                     "IVR.")
    payment_arrangement: ContactReason = _reason(0.12, 0.5, 0.1, 9.0, 0.8, "Can't pay: after overdue notices, more "
                                                 "after disconnection notices.")
    payment_problem: ContactReason = _reason(0.4, 0.4, 0.3, 6.0, 0.85, "Payment problem: a pre-authorized debit "
                                             "returned.")
    password: ContactReason = _reason(0.01, 3.0, 0.6, 4.0, 0.95, "Forgot password or online account help: when "
                                      "bills arrive; most reset online.")
    move_in: ContactReason = _reason(0.85, 0.0, 0.3, 10.0, 0.95, "Start service: a new account at a premise, days "
                                     "before the move-in.")
    move_out: ContactReason = _reason(0.85, 0.0, 0.3, 8.0, 0.95, "Stop service: days before an account closes.")
    new_connection: ContactReason = _reason(0.0, 0.4, 0.1, 14.0, 0.7, "New connection: builders and owners asking "
                                            "for a new service.")
    outage: ContactReason = _reason(0.18, 0.2, 0.65, 3.5, 0.9, "Outage report: customers who lose power or water "
                                    "(twice as many when it lasts over two hours); the IVR's outage message answers "
                                    "most.")
    gas_odour: ContactReason = _reason(0.06, 0.15, 0.0, 4.0, 1.0, "I smell gas: neighbours of a gas leak (the "
                                       "household with a service leak calls 9 times in 10); emergency line.")
    meter_access: ContactReason = _reason(0.08, 0.3, 0.2, 6.0, 0.85, "Meter access: after a no-access read card, "
                                          "and to book field visits.")
    disconnection: ContactReason = _reason(0.8, 0.0, 0.0, 9.0, 0.85, "Disconnected: customers asking to be "
                                           "reconnected after a disconnection you approved.")
    complaint: ContactReason = _reason(0.5, 0.2, 0.0, 14.0, 0.6, "Complaint: after a second unresolved contact "
                                       "about the same thing, or after giving up on hold twice.")
    # What the contacts change (the contact centre inside the replay).
    dispute_cases: float = F(1.0, "Share of answered bill-wrong contacts (and unresolved high-bill and back-bill ones) "
                             "that open a Bill Correction case: an analyst checks the read and rebills, or explains "
                             "the bill. 0: disputes are only counted.", ge=0, le=1,
                             effects=["bill disputes", "rebills", "dunning holds"])
    dispute_hold_days: float = F(30.0, "Collections pauses dunning on a disputed account until the dispute is "
                                 "decided, at most this long.", unit="d", ge=0, le=120, advanced=True)
    complaint_cases: bool = F(True, "A complaint the lines take opens a Customer Complaints case for the analysts to "
                              "answer (one open complaint per account).")
    frustration_threshold: int = F(3, "Bad experiences (a hang-up after a long wait, an unresolved contact, a wait "
                                   "past long_wait_s, a complaint) before a customer pays later from then on. 0: "
                                   "never.", ge=0, le=20, effects=["late payment", "autopay cancellations"])
    long_wait_s: float = F(600.0, "A wait this long counts as a bad experience even when the call is answered.",
                           unit="s", ge=30, le=7200, advanced=True)
    autopay_cancel_share: float = F(0.3, "Share of frustrated customers on pre-authorized debit who cancel it and pay "
                                    "by hand from then on (later, and sometimes not at all).", ge=0, le=1)

    @model_validator(mode="after")
    def _hours(self) -> ContactConfig:
        if self.close_hour <= self.open_hour:
            raise ValueError("contact.close_hour must be after open_hour")
        return self


class OutagesConfig(BaseModel):
    model_config = group("Outages & leaks over the year", 18, "The operations day's background incidents drawn for "
                         "every day of the year (same storms and leaks the map shows on a date): who loses power or "
                         "water, for how long, and where gas is smelled. The contact centre hears about them.",
                         applies="run")
    enabled: bool = F(True, "Draw outages and leaks across the year.")
    storm_factor: float = F(1.0, "Multiplies the chance that a day is a storm day.", ge=0, le=30)
    incident_factor: float = F(1.0, "Multiplies every incident rate (leaks, breaks, failures, faults).", ge=0, le=30)
    restore_factor: float = F(1.0, "Multiplies the time to restore service.", ge=0.1, le=20)


class FieldCrew(BaseModel):
    """One kind of field crew: how many there are for the town's size, and what an hour costs."""

    model_config = ConfigDict(extra="forbid")
    per_1000_premises: float = Field(0.5, ge=0, le=20, description="Crews per 1,000 premises. A fraction is part "
                                     "of a crew's time (the rest goes to work this model does not draw); on-call "
                                     "responders are at least one when above zero.")
    cost_per_hour: float = Field(120.0, ge=0, le=1000, description="Loaded cost of a crew hour, truck included.")
    overtime_factor: float = Field(1.5, ge=1, le=3, description="Multiplies the hourly cost after hours.")


def _crew(per_1000_premises: float, cost_per_hour: float, title: str, text: str, overtime_factor: float = 1.5):
    return F(FieldCrew(per_1000_premises=per_1000_premises, cost_per_hour=cost_per_hour,
                       overtime_factor=overtime_factor), text, title=title)


class FieldWorkType(BaseModel):
    """One kind of field work order: how much of it there is, what it takes and how soon it is due."""

    model_config = ConfigDict(extra="forbid")
    rate: float = Field(1.0, ge=0, le=500, description="How much of this work there is (its meaning is in the "
                        "setting's own description).")
    minutes: float = Field(30.0, ge=1, le=10_000, description="Crew minutes on site per order (travel is added for "
                           "premise visits).")
    target_days: float = Field(5.0, ge=0, le=365, description="Business days from the order's release to its due "
                               "date (0: the same day; planned work is released on its scheduled day). Emergencies "
                               "count calendar time: fractions of a day.")
    materials: float = Field(0.0, ge=0, le=500_000, description="Materials cost per order.", json_schema_extra={
        "x-unit": "$"})


def _work(rate: float, minutes: float, target_days: float, materials: float, text: str, title: str | None = None):
    kw = {"title": title} if title else {}
    return F(FieldWorkType(rate=rate, minutes=minutes, target_days=target_days, materials=materials), text, **kw)


class FieldConfig(BaseModel):
    model_config = group("Field work", 19, "The work the field crews do over the year and the crews that do it: "
                         "customer emergencies, service orders (disconnects, reconnects, move-ins and move-outs), "
                         "meter maintenance (seal exchanges, batteries, removals), preventative maintenance on the "
                         "networks and capital construction (new sets, upgrades, main renewal). Work follows the "
                         "year: collections, moves, VEE field visits, the contact centre's calls, the year's outages "
                         "and leaks, the meters' install years and the town's assets. What the crews do changes the "
                         "year: a disconnected or removed meter is not read or billed, an exchange registers a new "
                         "meter, and maintenance left overdue fails (dead batteries, drifting meters, outages, gas "
                         "leaks).", applies="run")
    shift_start_hour: float = F(7.0, "Crews start their day (local time, business days).", unit="h", ge=0, le=20)
    shift_hours: float = F(8.0, "Hours in a crew's working day.", unit="h", ge=1, le=16)
    routing: bool = F(True, "Crews drive the town's streets: from the depot in the morning, job to job by the "
                      "fastest route (the operations driving speeds), and back at the end of the day. Of the jobs "
                      "equally urgent and due, a crew takes the nearest next. On-call responders drive from the depot "
                      "and back. Off, or in a town without streets: every visit adds travel_minutes.")
    stop_minutes: float = F(5.0, "With routing: parking, walking to the asset and setting up at each stop, added to "
                            "the drive.", unit="min", ge=0, le=120)
    travel_minutes: float = F(20.0, "Driving to the job and back, added to every visit without routing (and to the "
                              "VEE field visits the run times).", unit="min", ge=0, le=240)
    callout_minutes: float = F(30.0, "After hours, the time an on-call responder takes to get on the road.",
                               unit="min", ge=0, le=240)
    overtime_max_hours: float = F(3.0, "Most hours a crew works past its shift to finish same-day and overdue "
                                  "customer work (priority 1 and 2).", unit="h", ge=0, le=12)
    remote_switch_share: float = F(0.85, "Share of AMI electric meters with a remote connect switch: their "
                                   "disconnects, reconnects and move reads need no truck.", ge=0, le=1)
    seal_years_electric: int = F(10, "Electric meter seal period: a lot whose seal expires this year is sampled.",
                                 unit="yr", ge=1, le=30)
    seal_years_gas: int = F(10, "Gas meter seal period.", unit="yr", ge=1, le=30)
    seal_sample_size: int = F(32, "Meters pulled and tested from each lot whose seal expires.", ge=1, le=500)
    seal_lot_pass_rate: float = F(0.8, "Share of lots that pass compliance sampling and are resealed; a failed lot "
                                  "is exchanged meter by meter before its seal expires.", ge=0, le=1)
    battery_years: int = F(15, "Radio module battery life on gas and water meters, AMI and AMR (they have no mains "
                           "power).", unit="yr", ge=1, le=40)
    water_meter_life_years: int = F(15, "Water meters this old or older are due for replacement.", unit="yr", ge=1,
                                    le=60)
    dead_battery_miss: float = F(0.9, "Share of reads a radio module misses once its battery has died (past its life "
                                 "and not replaced): estimates follow.", ge=0, le=1)
    failed_lot_drift: float = F(0.04, "Under-registration of a failed seal lot's meters, from the failed test until "
                                "each is exchanged.", ge=0, le=0.5)
    old_water_meter_drift: float = F(0.03, "Under-registration of water meters at or past their service life, until "
                                     "replaced (read at the start of the year).", ge=0, le=0.5)
    deferred_pole_failures: float = F(2.0, "Chance a year that a pole found needing replacement fails once its "
                                      "replacement is overdue (ten times as likely on a storm day): an outage.",
                                      ge=0, le=100)
    deferred_tree_faults: float = F(0.02, "Chance on a storm day that an overhead span overdue for trimming faults: "
                                    "an outage.", ge=0, le=1)
    deferred_leak_escalation: float = F(1.0, "Chance a year that a leak found by survey becomes a public gas leak "
                                        "(odour calls, an emergency) once its repair is overdue.", ge=0, le=100)
    renewed_main_break_factor: float = F(0.3, "A renewed main's breaks and leaks, as a share of the cast-iron "
                                         "main's it replaced: from the day the construction crew finishes a "
                                         "segment.", ge=0, le=1)
    construction_start_month: int = F(4, "First month of the construction season (digging is frost-free).", ge=1,
                                      le=12)
    construction_end_month: int = F(11, "Last month of the construction season.", ge=1, le=12)
    # ---- crews -----------------------------------------------------------------------------------------------------
    crew_emergency: FieldCrew = _crew(0.4, 110.0, "On-call responders", "Gas odour and no-supply calls, any hour "
                                      "of any day.")
    crew_meter: FieldCrew = _crew(0.3, 75.0, "Meter technicians", "Disconnects, reconnects, move visits, exchanges, "
                                  "batteries, removals, investigations, meter sets.")
    crew_electric: FieldCrew = _crew(0.15, 165.0, "Electric line crews", "Pole work, tree trimming, outage repairs, "
                                     "service upgrades.")
    crew_water: FieldCrew = _crew(0.15, 140.0, "Water crews", "Valves, hydrants, main break repairs.")
    crew_gas: FieldCrew = _crew(0.08, 150.0, "Gas crews", "Leak surveys, regulator stations, leak repairs.")
    crew_construction: FieldCrew = _crew(0.08, 230.0, "Construction crews", "Contractors: new services, main "
                                         "renewal.")
    # ---- customer emergencies (priority 1, on-call crew) -----------------------------------------------------------
    gas_odour: FieldWorkType = _work(1.0, 45.0, 1 / 24, 0.0, "Gas odour investigation: share of gas odour reports "
                                     "(a leak's first report, every background report) a responder attends.",
                                     title="Gas odour")
    no_supply: FieldWorkType = _work(0.6, 60.0, 4 / 24, 40.0, "No supply at one premise (a service fault, a blown "
                                     "fuse, a curb stop): share of single-premise outage reports that need a truck.")
    outage_repair: FieldWorkType = _work(1.0, 120.0, 1.0, 900.0, "Repair of the year's outages and leaks (the "
                                         "incident model times it): share recorded against the utility's crew.",
                                         title="Outage and leak repair")
    # ---- customer service orders (priority 2, meter technicians) ---------------------------------------------------
    disconnect: FieldWorkType = _work(1.0, 30.0, 0.0, 0.0, "Disconnect for non-payment: share of collections "
                                      "disconnections worked (AMI electric with a switch is done remotely).")
    reconnect: FieldWorkType = _work(1.0, 30.0, 1.0, 0.0, "Reconnect after payment: share of reconnections worked, "
                                     "due the next business day.")
    move_out: FieldWorkType = _work(1.0, 20.0, 1.0, 0.0, "Move-out final read or lock-off: share of account closings "
                                    "at a premise with a meter that cannot be read remotely.",
                                    title="Move-out read")
    move_in: FieldWorkType = _work(0.5, 25.0, 1.0, 0.0, "Move-in turn-on or first read: share of account openings at "
                                   "a premise with a meter that cannot be read remotely.",
                                   title="Move-in read")
    meter_investigation: FieldWorkType = _work(1.0, 40.0, 10.0, 0.0, "VEE field visit (the run decides when): share "
                                               "recorded against the meter technicians.")
    corrective_exchange: FieldWorkType = _work(1.0, 60.0, 10.0, 140.0, "Faulty meter exchanged on a field visit (the "
                                               "run decides when): share recorded.")
    # ---- meter maintenance (priority 3, meter technicians) ---------------------------------------------------------
    seal_exchange: FieldWorkType = _work(1.0, 45.0, 20.0, 140.0, "Seal-expiry exchange: share of the meters due (the "
                                         "sample of every expiring lot, every meter of a failed lot) exchanged. A "
                                         "failed lot's meters are due by 31 December.")
    ami_battery: FieldWorkType = _work(1.0, 20.0, 20.0, 35.0, "Module battery replacement on gas and water meters: "
                                       "share of batteries reaching their life this year.",
                                       title="Module battery")
    water_meter_replacement: FieldWorkType = _work(0.5, 45.0, 20.0, 160.0, "Water meter replacement by age: share "
                                                   "of over-age water meters replaced this year.")
    removal: FieldWorkType = _work(2.0, 30.0, 10.0, 0.0, "Meter removal (vacant premise, service abandoned): "
                                   "removals per 1,000 premises a year.", title="Meter removal")
    ami_conversion: FieldWorkType = _work(0.0, 35.0, 20.0, 180.0, "AMI conversion: share of AMR and manually read "
                                          "meters converted to AMI this year (capital, priority 4).",
                                          title="AMI conversion")
    # ---- preventative maintenance (priority 3, utility crews) ------------------------------------------------------
    pole_inspection: FieldWorkType = _work(0.1, 15.0, 20.0, 0.0, "Pole inspection: share of poles inspected a year "
                                           "(0.1 is a ten-year cycle).")
    pole_replacement: FieldWorkType = _work(0.03, 480.0, 40.0, 2500.0, "Pole replacement: share of inspected poles "
                                            "found needing replacement.")
    tree_trimming: FieldWorkType = _work(0.25, 25.0, 20.0, 0.0, "Tree trimming: share of overhead spans trimmed a "
                                         "year (minutes per span).")
    valve_exercise: FieldWorkType = _work(0.25, 30.0, 20.0, 0.0, "Valve exercising: share of water and gas valves a "
                                        "year.")
    valve_repair: FieldWorkType = _work(0.05, 300.0, 20.0, 1800.0, "Valve repair: share of exercised valves found "
                                        "broken or stuck.")
    hydrant_flush: FieldWorkType = _work(1.0, 40.0, 15.0, 0.0, "Hydrant flushing and inspection: share of hydrants "
                                         "a year (May to October).", title="Hydrant flushing")
    hydrant_repair: FieldWorkType = _work(0.04, 240.0, 10.0, 900.0, "Hydrant repair: share of flushed hydrants found "
                                          "defective.")
    leak_survey: FieldWorkType = _work(0.33, 90.0, 20.0, 0.0, "Gas leak survey: share of gas main length walked a "
                                       "year (minutes per km).")
    gas_leak_repair: FieldWorkType = _work(0.15, 360.0, 15.0, 800.0, "Gas leak repair (grade 2): leaks found per "
                                           "surveyed km.")
    regulator_inspection: FieldWorkType = _work(1.0, 180.0, 10.0, 0.0, "Regulator station inspection: share of "
                                                "stations (city gate, district regulators) a year.")
    # ---- capital construction (priority 4, construction crews) -----------------------------------------------------
    new_set: FieldWorkType = _work(0.8, 480.0, 30.0, 1500.0, "New service: share of new-connection requests (the "
                                   "contact centre's new connection contacts) that go ahead; built in the "
                                   "construction season.", title="New set (new service)")
    meter_set: FieldWorkType = _work(1.0, 45.0, 5.0, 250.0, "Meter set on a finished new service: share set by a "
                                     "meter technician (the rest come with the contractor).")
    service_upgrade: FieldWorkType = _work(0.04, 240.0, 20.0, 900.0, "Electric service upgrade: share of homes with an "
                                           "EV or electric heat upgrading a year.")
    main_replacement: FieldWorkType = _work(0.02, 1440.0, 40.0, 45000.0, "Main renewal: share of cast-iron water and "
                                            "gas main length replaced a year (minutes and materials per 100 m).",
                                            title="Main renewal")


class SimConfig(BaseModel):
    """Complete simulator configuration. ``town_id`` is a pure function of this object and the generator version."""

    model_config = ConfigDict(extra="forbid", title="SimConfig")
    name: str = F("custom", "Preset or scenario name (informational; not part of the town id).")
    description: str = F("", "Free-text description (informational).")
    seeds: SeedsConfig = Field(default_factory=SeedsConfig)
    town: TownConfig = Field(default_factory=TownConfig)
    housing: HousingConfig = Field(default_factory=HousingConfig)
    electric: ElectricConfig = Field(default_factory=ElectricConfig)
    gas: GasConfig = Field(default_factory=GasConfig)
    water: WaterConfig = Field(default_factory=WaterConfig)
    ami: AmiConfig = Field(default_factory=AmiConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    incidents: IncidentConfig = Field(default_factory=IncidentConfig)
    operations: OperationsConfig = Field(default_factory=OperationsConfig)
    customers_billing: CustomersBillingConfig = Field(default_factory=CustomersBillingConfig)
    process: ProcessConfig = Field(default_factory=ProcessConfig)
    anomalies: AnomaliesConfig = Field(default_factory=AnomaliesConfig)
    scenario: ScenarioConfig = Field(default_factory=ScenarioConfig)
    reading: ReadingConfig = Field(default_factory=ReadingConfig)
    vee: VeeConfig = Field(default_factory=VeeConfig)
    billing: BillingConfig = Field(default_factory=BillingConfig)
    contact: ContactConfig = Field(default_factory=ContactConfig)
    outages: OutagesConfig = Field(default_factory=OutagesConfig)
    field: FieldConfig = Field(default_factory=FieldConfig)

    @model_validator(mode="after")
    def _check(self) -> SimConfig:
        h = self.housing
        if h.pv_kw_max < h.pv_kw_min:
            raise ValueError("housing.pv_kw_max must be >= housing.pv_kw_min")
        if len(h.household_size_weights) != 6 or sum(h.household_size_weights) <= 0:
            raise ValueError("housing.household_size_weights needs 6 non-negative weights with a positive sum")
        if self.ami.ami_route_share + self.ami.amr_route_share > 1.0 + 1e-9:
            raise ValueError("ami.ami_route_share + ami.amr_route_share must not exceed 1")
        if self.customers_billing.on_time_payer_share + self.customers_billing.late_payer_share > 1.0 + 1e-9:
            raise ValueError("on-time + late payer shares must not exceed 1")
        if self.process.analyst_queue_days_max < self.process.analyst_queue_days_min:
            raise ValueError("process.analyst_queue_days_max must be >= min")
        if self.process.review_minutes_max < self.process.review_minutes_min:
            raise ValueError("process.review_minutes_max must be >= min")
        if self.process.supervisor_queue_days_max < self.process.supervisor_queue_days_min:
            raise ValueError("process.supervisor_queue_days_max must be >= min")
        if self.vee.reject_confidence > self.vee.accept_confidence:
            raise ValueError("vee.reject_confidence must not exceed vee.accept_confidence")
        if self.vee.max_period_days < self.vee.min_period_days:
            raise ValueError("vee.max_period_days must be >= min_period_days")
        if sorted(self.electric.transformer_kva_steps) != list(self.electric.transformer_kva_steps):
            raise ValueError("electric.transformer_kva_steps must be ascending")
        return self

    # ---- identity ---------------------------------------------------------------------------------------------
    def generation_dict(self) -> dict[str, Any]:
        """The part of the config that determines the generated town and its fixtures."""
        d = self.model_dump(mode="json")
        for k in ("name", "description", *RUN_GROUPS):
            d.pop(k, None)
        return d

    def canonical_json(self) -> bytes:
        return orjson.dumps(self.generation_dict(), option=orjson.OPT_SORT_KEYS)

    def town_id(self) -> str:
        h = hashlib.blake2b(self.canonical_json() + b"|" + GENERATOR_VERSION.encode(), digest_size=8).hexdigest()
        return f"town-{h}"

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json() + b"|" + GENERATOR_VERSION.encode()).hexdigest()


RUN_GROUPS = tuple(k for k, f in SimConfig.model_fields.items()
                   if (getattr(f.annotation, "model_config", None) or {}).get("json_schema_extra", {}).get("x-applies")
                   == "run")


def annotate_group(name: str, group_schema: dict[str, Any]) -> dict[str, Any]:
    """Add ``x-reach`` (where the setting's effect reaches) and ``x-impact`` (how it changes the results) to a group's
    JSON Schema properties, from ``utilsim/config/impact.py``."""
    for key, prop in group_schema.get("properties", {}).items():
        hit = IMPACT.get(f"{name}.{key}")
        if hit:
            prop["x-reach"], prop["x-impact"] = hit
    return group_schema


def config_schema() -> dict[str, Any]:
    """JSON Schema with UI hints for the settings page. A town field that is the default of an operations run setting
    names it in ``x-run-setting`` (a key of ``GET /api/sim/settings/schema``): change it per run there, or here for a
    new town."""
    from utilsim.ops.timeline import TOWN_SETTINGS

    schema = SimConfig.model_json_schema()
    schema["x-generator-version"] = GENERATOR_VERSION
    schema["x-reaches"] = REACHES
    defs = schema["$defs"]
    for g, f in SimConfig.model_fields.items():
        if not hasattr(f.annotation, "model_fields"):
            continue
        annotate_group(g, defs[f.annotation.__name__])
    for key, (path, _) in TOWN_SETTINGS.items():
        group, field = path.split(".")
        defs[SimConfig.model_fields[group].annotation.__name__]["properties"][field]["x-run-setting"] = key
    return schema
