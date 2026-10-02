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

from utilsim.version import GENERATOR_VERSION


def F(default: Any, description: str, *, unit: str | None = None, ge: float | None = None,
      le: float | None = None, advanced: bool = False, effects: list[str] | None = None, **kw: Any):
    extra: dict[str, Any] = {}
    if unit:
        extra["x-unit"] = unit
    if advanced:
        extra["x-advanced"] = True
    if effects:
        extra["x-effects"] = effects
    return Field(default, description=description, ge=ge, le=le, json_schema_extra=extra or None, **kw)


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
    master: str = F("WHITBY-042", "Master seed. Any text or integer; same seed + config + generator version "
                    "reproduces the same town byte for byte.", effects=["everything"])
    town: str | None = F(None, "Override seed for geography only (roads growth, parcels, buildings).", advanced=True)
    households: str | None = F(None, "Override seed for household attributes (occupants, solar, EV, heating).",
                               advanced=True)
    weather: str | None = F(None, "Override seed for weather series (re-roll storms, keep the town).", advanced=True)
    incidents: str | None = F(None, "Override seed for incident hazards.", advanced=True)
    anomalies: str | None = F(None, "Override seed for meter/read anomalies.", advanced=True)

    def for_(self, subsystem: str) -> str:
        v = getattr(self, subsystem, None)
        return v if v else f"{self.master}"


class TownConfig(BaseModel):
    model_config = group("Town & geography", 1, "Size, road skeleton source, terrain and land use.")
    houses: int = F(480, "Number of residential premises to place.", ge=20, le=10_000,
                    effects=["town extent", "growth districts", "substations", "feeders", "pipe sizes", "MRUs"])
    skeleton: Literal["osm", "synthetic"] = F("osm", "Road skeleton source: a frozen OpenStreetMap extract, or a "
                                              "fully synthetic warped section grid.")
    osm_source: str = F("data/osm/whitby-roads.json", "Path to an OSM API 0.6 / Overpass JSON extract.")
    osm_sha256: str | None = F("4c4bb0d8c88e4b53e89f5cfae2dc1778f1c446ba93b9b587ee423a91005706d8",
                               "Expected SHA-256 of the OSM extract; generation fails if it differs.", advanced=True)
    expansion: Literal["grow", "repeat", "none"] = F("grow", "When the OSM extract cannot hold the requested houses: "
                                                     "grow synthetic districts outward, repeat the extract as tiles "
                                                     "(prototype behaviour), or fail.")
    units: Literal["ontario", "us", "uk"] = F("ontario", "Display unit profile (stored values are always SI).")
    anchor_lat: float = F(43.30, "Latitude of the local origin for synthetic towns.", unit="deg", ge=-80, le=80,
                          advanced=True)
    anchor_lon: float = F(-80.60, "Longitude of the local origin for synthetic towns.", unit="deg", ge=-180, le=180,
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
    commercial_strip_m: float = F(700.0, "Length of the commercial strip along the main arterial.", unit="m", ge=0,
                                  le=3000)
    industrial_lots: int = F(2, "Number of large industrial customers.", ge=0, le=10)
    houses_per_school: int = F(2500, "One school per this many houses.", ge=500, le=20_000, advanced=True)
    margin_m: float = F(120.0, "Empty margin around the developed area.", unit="m", ge=0, le=1000, advanced=True)


class HousingConfig(BaseModel):
    model_config = group("Housing & households", 2, "Lots, buildings and the people and appliances inside them.")
    lot_frontage_m: EraValues = F(EraValues(pre_1945=15, postwar=18.5, modern=16.5),
                                  "Mean lot frontage by era.", unit="m", effects=["houses per km of street"])
    lot_depth_m: EraValues = F(EraValues(pre_1945=36, postwar=35, modern=33), "Mean lot depth by era.", unit="m")
    setback_m: EraValues = F(EraValues(pre_1945=6, postwar=7.5, modern=6.5), "Front setback by era.", unit="m",
                             advanced=True)
    two_storey_share: EraValues = F(EraValues(pre_1945=0.7, postwar=0.25, modern=0.75),
                                    "Share of two-storey houses by era.")
    semi_share: EraValues = F(EraValues(pre_1945=0.25, postwar=0.08, modern=0.18),
                              "Share of lots built as semi-detached/townhouse pairs.", advanced=True)
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
    transmission_kv: float = F(115.0, "Off-map transmission voltage into the substation.", unit="kV", ge=34.5,
                               le=500)
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
    max_houses_per_transformer_overhead: int = F(6, "Max houses on a pole-mount transformer.", ge=1, le=20)
    max_houses_per_transformer_underground: int = F(10, "Max houses on a pad-mount transformer.", ge=1, le=25)
    feeder_design_mva: float = F(6.0, "Design peak per feeder.", unit="MVA", ge=1, le=20,
                                 effects=["feeder count", "tie switches"])
    substation_mva: float = F(25.0, "Firm capacity per substation.", unit="MVA", ge=5, le=100,
                              effects=["substation count"])
    overhead_before_year: int = F(1978, "Districts built before this year are overhead (poles); later underground.",
                                  ge=1850, le=2030, effects=["poles", "lightning exposure", "storm outages"])
    pole_spacing_m: float = F(42.0, "Pole span on overhead lines.", unit="m", ge=20, le=90, advanced=True)
    voltage_min_pu: float = F(0.95, "Lower service voltage limit (CSA CAN3-C235 / ANSI Range A).", ge=0.85, le=1.0,
                              advanced=True)
    voltage_max_pu: float = F(1.05, "Upper service voltage limit.", ge=1.0, le=1.15, advanced=True)


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
    base_pressure_kpa: float = F(101.325, "Base pressure for standard volume.", unit="kPa", ge=90, le=110,
                                 advanced=True)
    base_temperature_c: float = F(15.0, "Base temperature for standard volume.", unit="C", ge=0, le=25, advanced=True)


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
    hw_c_new: float = F(130.0, "Hazen-Williams C for PVC/ductile iron.", ge=60, le=150, advanced=True)
    hw_c_old: float = F(100.0, "Hazen-Williams C for unlined cast iron.", ge=40, le=140, advanced=True)
    cast_iron_before_year: int = F(1960, "Districts built before this year have cast-iron mains.", ge=1850, le=2000,
                                   effects=["main break rate", "head loss"])
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
    battery_life_years: float = F(15.0, "AMR/AMI endpoint battery life.", unit="yr", ge=3, le=30, advanced=True)
    comm_fail_rate: float = F(0.004, "Nightly probability an AMI meter fails to report.", ge=0, le=0.2,
                              effects=["estimated reads", "consecutive estimates"])


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
    model_config = group("Incidents & hazards", 8, "What goes wrong, how often. Rates are per year.")
    gas_service_leaks_per_1000: float = F(1.2, "Leaks per 1,000 gas services per year.", ge=0, le=50)
    gas_main_leaks_per_100km: float = F(8.0, "Leaks per 100 km of gas main per year.", ge=0, le=200)
    water_main_breaks_per_100km: float = F(14.0, "Main breaks per 100 km per year (×2 for cast iron).", ge=0, le=200,
                                           effects=["water outages", "crew workload"])
    overhead_faults_per_km_storm_day: float = F(0.015, "Overhead primary faults per km per storm day.", ge=0, le=1,
                                                effects=["outages", "SAIDI/SAIFI", "zero-usage reads"])
    transformer_failures_per_1000: float = F(3.0, "Transformer failures per 1,000 units per year (×3 when "
                                             "overloaded).", ge=0, le=100)
    collector_outages_per_year: float = F(2.0, "AMI collector outages per year (town-wide).", ge=0, le=50)
    manual_only: bool = F(False, "Disable random hazards; only manually injected incidents occur.")


class OperationsConfig(BaseModel):
    model_config = group("Field operations", 9, "Fleet, shifts, response targets and vehicle movement.")
    gas_crews: int = F(2, "Gas emergency crews.", ge=0, le=20, effects=["leak response time"])
    electric_crews: int = F(3, "Electric trouble crews.", ge=0, le=30, effects=["outage duration", "SAIDI"])
    water_crews: int = F(2, "Water distribution crews.", ge=0, le=20)
    meter_techs: int = F(2, "Meter technicians (exchanges, investigations).", ge=0, le=20)
    meter_vans: int = F(2, "Drive-by AMR reading vans.", ge=0, le=20, effects=["AMR read completion"])
    meter_walkers: int = F(3, "Manual meter readers.", ge=0, le=40, effects=["manual read completion", "no-access"])
    shift_start_hour: float = F(7.0, "Day shift start.", unit="h", ge=0, le=23)
    shift_end_hour: float = F(15.5, "Day shift end.", unit="h", ge=1, le=24)
    gas_response_target_min: float = F(60.0, "Target response to a gas odour call.", unit="min", ge=10, le=240)
    speed_kmh_arterial: float = F(50.0, "Driving speed on arterials.", unit="km/h", ge=10, le=100, advanced=True)
    speed_kmh_collector: float = F(40.0, "Driving speed on collectors.", unit="km/h", ge=10, le=80, advanced=True)
    speed_kmh_local: float = F(30.0, "Driving speed on local streets.", unit="km/h", ge=5, le=60, advanced=True)
    drive_by_radius_m: float = F(120.0, "AMR van reads meters within this distance.", unit="m", ge=20, le=500,
                                 advanced=True)
    walker_meters_per_hour: float = F(45.0, "Manual reads per walker-hour.", ge=5, le=150, advanced=True)


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
    sequences: str = F("builtin", "Activity sequence library: 'builtin' or a path to a YAML file.")
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
                                "(Ontario).")


class ScenarioConfig(BaseModel):
    model_config = group("Scenario", 13, "Demonstration scenario on the live clock.", applies="run")
    name: Literal["normal", "solar_noon", "leak", "substation_outage"] = F(
        "normal", "Live demonstration scenario.")
    date: str = F("2026-07-15", "Demonstration date (local).")
    hour: float = F(8.0, "Demonstration hour (local, decimal).", unit="h", ge=0, lt=24)
    target_premise: str | None = F(None, "Premise targeted by the leak scenario (default: first premise).")
    leak_m3h: float = F(0.65, "Leak rate added to the target premise's water demand.", unit="m3/h", ge=0, le=50)
    tick_minutes: int = F(5, "Live clock step.", unit="min", ge=1, le=60)


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


def config_schema() -> dict[str, Any]:
    """JSON Schema with UI hints for the settings page."""
    schema = SimConfig.model_json_schema()
    schema["x-generator-version"] = GENERATOR_VERSION
    return schema
