# Configuration reference

Every assumption in the simulator is a field of `SimConfig` (see `utilsim/config/model.py`). The settings page is
generated from `GET /api/config/schema`, which carries these UI hints on every field:

| Hint | Meaning |
|---|---|
| `x-unit` | Unit shown next to the input (stored values are SI) |
| `x-advanced` | Hide behind an "Advanced" toggle |
| `x-effects` | What changes downstream when this value changes (show as a tooltip / "affects" chips) |
| `x-group`, `x-order` | Group cards and their order on the page |

Presets (`GET /api/config/presets`) are YAML overrides deep-merged on the defaults. The town id is a hash of the
generation-relevant config plus the generator version, so every combination is reproducible.

## Knock-on chains worth demonstrating

| Change | What you should see |
|---|---|
| `housing.solar_rate` ↑ | More export registers and net-metering contracts; reverse flow on services, transformers and eventually the whole town at noon |
| `housing.ev_rate` ↑ | Higher individual peaks → larger transformers, more transformer groups, heavier feeders, more feeders |
| `housing.electric_heat_rate` ↑ or `gas.all_electric_district_share` ↑ | Fewer gas services and smaller gas mains; higher electric design load |
| `electric.overhead_before_year` ↑ | More overhead districts → poles, pole-mount transformers, lightning exposure (M3 outages) |
| `gas.scheme` = `mp` | No low-pressure core, no district regulators, ¾" services with regulators everywhere |
| `water.fire_flow_residential_lps` ↑ | Larger distribution mains everywhere (fire flow governs sizing) |
| `town.terrain_relief_m` ↑ | Second pressure zone, second elevated tank, PRV/booster equipment at zone boundaries |
| `ami.ami_route_share` ↓ | More AMR van and manual walker routes; more estimated reads (M3) |
| `customers_billing.mru_target_meters` ↓ | More, smaller meter reading routes |
| `town.houses` ↑ beyond the OSM extract | Synthetic districts grown around the Whitby core; second substation; more feeders |


## Seeds

Master seed and optional per-subsystem re-rolls.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `master` | `WHITBY-042` |  |  | Master seed. Any text or integer; same seed + config + generator version reproduces the same town byte for byte. *Affects: everything.* |
| `town` | `None` |  |  | (advanced) Override seed for geography only (roads growth, parcels, buildings). |
| `households` | `None` |  |  | (advanced) Override seed for household attributes (occupants, solar, EV, heating). |
| `weather` | `None` |  |  | (advanced) Override seed for weather series (re-roll storms, keep the town). |
| `incidents` | `None` |  |  | (advanced) Override seed for incident hazards. |
| `anomalies` | `None` |  |  | (advanced) Override seed for meter/read anomalies. |

## Town & geography

Size, road skeleton source, terrain and land use.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `houses` | `480` | 20–10000 |  | Number of residential premises to place. *Affects: town extent, growth districts, substations, feeders, pipe sizes, MRUs.* |
| `skeleton` | `osm` |  |  | Road skeleton source: a frozen OpenStreetMap extract, or a fully synthetic warped section grid. |
| `osm_source` | `data/osm/whitby-roads.json` |  |  | Path to an OSM API 0.6 / Overpass JSON extract. |
| `osm_sha256` | `4c4bb0d8c88e4b53e89f5cfae2dc1778f1c446ba93b9b587ee423a91005706d8` |  |  | (advanced) Expected SHA-256 of the OSM extract; generation fails if it differs. |
| `expansion` | `grow` |  |  | When the OSM extract cannot hold the requested houses: grow synthetic districts outward, repeat the extract as tiles (prototype behaviour), or fail. |
| `units` | `ontario` |  |  | Display unit profile (stored values are always SI). |
| `anchor_lat` | `43.3` | -80–80 | deg | (advanced) Latitude of the local origin for synthetic towns. |
| `anchor_lon` | `-80.6` | -180–180 | deg | (advanced) Longitude of the local origin for synthetic towns. |
| `timezone` | `America/Toronto` |  |  | IANA timezone of the town (read schedules, billing calendar, day/night). |
| `terrain_relief_m` | `15.0` | 0–120 | m | Peak-to-trough terrain relief. *Affects: water pressure zones, PRVs, tank siting.* |
| `terrain_wavelength_m` | `900.0` | 100–5000 | m | (advanced) Dominant wavelength of terrain undulation. |
| `arterial_spacing_m` | `1400.0` | 600–2400 | m | (advanced) Mean spacing of arterial roads (concession-grid style). |
| `arterial_warp_m` | `130.0` | 0–400 | m | (advanced) Amplitude of the smooth warp applied to arterials. |
| `collector_block_m` | `650.0` | 250–1500 | m | (advanced) Superblocks larger than this get a collector road. |
| `era_core_year` | `1925` | 1850–2020 |  | Construction year at the town centre. *Affects: street pattern, lot sizes, overhead vs underground electric, legacy gas district, cast-iron water mains, solar/EV uptake.* |
| `era_span_years` | `85` | 0–150 |  | Years added from centre to edge (era = core + span·(d/R)^1.2 + noise). |
| `era_noise_years` | `8.0` | 0–30 | yr | (advanced) Std-dev of era noise per district. |
| `park_share` | `0.04` | 0–0.2 |  | (advanced) Share of blocks kept as parks. |
| `commercial_strip_m` | `700.0` | 0–3000 | m | Length of the commercial strip along the main arterial. |
| `industrial_lots` | `2` | 0–10 |  | Number of large industrial customers. |
| `houses_per_school` | `2500` | 500–20000 |  | (advanced) One school per this many houses. |
| `margin_m` | `120.0` | 0–1000 | m | (advanced) Empty margin around the developed area. |

## Housing & households

Lots, buildings and the people and appliances inside them.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `lot_frontage_m` | `pre_1945=15.0, postwar=18.5, modern=16.5` |  | m | Mean lot frontage by era. *Affects: houses per km of street.* |
| `lot_depth_m` | `pre_1945=36.0, postwar=35.0, modern=33.0` |  | m | Mean lot depth by era. |
| `setback_m` | `pre_1945=6.0, postwar=7.5, modern=6.5` |  | m | (advanced) Front setback by era. |
| `two_storey_share` | `pre_1945=0.7, postwar=0.25, modern=0.75` |  |  | Share of two-storey houses by era. |
| `semi_share` | `pre_1945=0.25, postwar=0.08, modern=0.18` |  |  | (advanced) Share of lots built as semi-detached/townhouse pairs. |
| `occupancy_rate` | `0.955` | 0.5–1.0 |  | Share of premises occupied at simulation start. *Affects: vacant consumption, VEE vacancy signals, move-ins.* |
| `rental_share` | `0.28` | 0–1 |  | Share of premises that are rentals (more contract turnover). *Affects: move-in/out frequency, contract history.* |
| `household_size_weights` | `[0.28, 0.34, 0.15, 0.15, 0.06, 0.02]` |  |  | (advanced) Relative frequency of households with 1..6 occupants. |
| `solar_rate` | `pre_1945=0.06, postwar=0.1, modern=0.18` |  |  | Share of houses with rooftop PV by era. *Affects: export registers, midday reverse flow, net-metering credits.* |
| `pv_kw_min` | `4.0` | 0.5–20 | kW | Smallest rooftop PV system. |
| `pv_kw_max` | `9.5` | 1–30 | kW | Largest rooftop PV system. |
| `ev_rate` | `pre_1945=0.05, postwar=0.07, modern=0.12` |  |  | Share of houses with an EV charger. *Affects: transformer loading, evening peak.* |
| `electric_heat_rate` | `pre_1945=0.1, postwar=0.14, modern=0.18` |  |  | Share of houses heated electrically (baseboard or heat pump) where gas is available. All houses in all-electric districts are electric. *Affects: gas service count, winter electric peak.* |
| `heat_pump_share_of_electric` | `0.55` | 0–1 |  | (advanced) Share of electric heating that is a heat pump (vs baseboard). |
| `ac_rate` | `0.85` | 0–1 |  | Share of houses with central air conditioning. *Affects: summer peak, transformer sizing.* |
| `pool_rate` | `0.06` | 0–0.5 |  | (advanced) Share of houses (on lots > 600 m²) with a pool. |
| `irrigation_rate` | `0.3` | 0–1 |  | Share of houses that irrigate lawns in summer. *Affects: summer water peak.* |

## Electric distribution

Bulk supply, substations, feeders, transformers, services.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `transmission_kv` | `115.0` | 34.5–500 | kV | Off-map transmission voltage into the substation. |
| `primary_kv` | `13.8` | 4.16–34.5 | kV | Primary distribution line-to-line voltage (Ontario urban 13.8 kV; US 12.47 kV). *Affects: feeder capacity, conductor sizing.* |
| `secondary_v` | `240.0` | 120–480 | V | (advanced) Split-phase secondary voltage (120/240 V). |
| `kva_per_100m2` | `1.0` | 0.2–5 | kVA | Individual peak demand per 100 m² of floor area (lighting, plug, appliances). *Affects: transformer sizing.* |
| `kva_ac` | `3.5` | 0–10 | kVA | Added peak for central air conditioning. |
| `kva_electric_heat` | `6.0` | 0–20 | kVA | Added peak for electric resistance heat. |
| `kva_heat_pump` | `4.0` | 0–15 | kVA | Added peak for a heat pump. |
| `kva_ev` | `7.2` | 0–20 | kVA | Added peak for a Level-2 EV charger. |
| `kva_pool` | `1.5` | 0–10 | kVA | (advanced) Added peak for a pool pump/heater. |
| `coincidence_floor` | `0.33` | 0.1–1.0 |  | (advanced) Coincidence factor CF(n) = a + (1-a)/√n; a is the floor as n → ∞. *Affects: every electric size.* |
| `transformer_kva_steps` | `[25, 50, 75, 100, 167]` |  | kVA | (advanced) Single-phase transformer sizes. |
| `transformer_max_loading` | `1.3` | 0.8–2.0 |  | (advanced) Allowed peak loading relative to nameplate. |
| `max_houses_per_transformer_overhead` | `6` | 1–20 |  | Max houses on a pole-mount transformer. |
| `max_houses_per_transformer_underground` | `10` | 1–25 |  | Max houses on a pad-mount transformer. |
| `feeder_design_mva` | `6.0` | 1–20 | MVA | Design peak per feeder. *Affects: feeder count, tie switches.* |
| `substation_mva` | `25.0` | 5–100 | MVA | Firm capacity per substation. *Affects: substation count.* |
| `overhead_before_year` | `1978` | 1850–2030 |  | Districts built before this year are overhead (poles); later underground. *Affects: poles, lightning exposure, storm outages.* |
| `pole_spacing_m` | `42.0` | 20–90 | m | (advanced) Pole span on overhead lines. |
| `voltage_min_pu` | `0.95` | 0.85–1.0 |  | (advanced) Lower service voltage limit (CSA CAN3-C235 / ANSI Range A). |
| `voltage_max_pu` | `1.05` | 1.0–1.15 |  | (advanced) Upper service voltage limit. |

## Natural gas

City gate, mains, regulators and services.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `all_electric_district_share` | `0.15` | 0–1 |  | Share of districts with no gas mains (all-electric). *Affects: gas services, electric heat share, winter electric peak.* |
| `scheme` | `mp_with_lp_core` |  |  | Medium-pressure PE everywhere with a regulator at every meter, optionally with a legacy low-pressure core fed by district regulators. |
| `transmission_kpa` | `3800.0` | 700–10000 | kPa | (advanced) Off-map transmission pressure at the city gate inlet. |
| `mp_kpa` | `414.0` | 35–700 | kPa | Medium-pressure distribution set point (60 psig). |
| `lp_kpa` | `1.74` | 0.5–7 | kPa | (advanced) Low-pressure legacy main set point (7 in w.c.). |
| `lp_core_before_year` | `1945` | 1850–2000 |  | (advanced) Districts built before this year are on the low-pressure system. |
| `design_m3h_base` | `1.15` | 0–10 | m3/h | Design-hour demand per house, base component (≈ 40 CFH). |
| `design_m3h_per_m2` | `0.017` | 0–0.2 | m3/h | Design-hour demand per m² of floor area (≈ 0.6 CFH/m²). |
| `coincidence_floor` | `0.5` | 0.1–1 |  | (advanced) Gas coincidence factor floor a in CF(n) = a + (1-a)/√n. |
| `min_main_mm` | `50` | 25–150 | mm | Smallest distribution main (2-inch PE). |
| `valve_spacing_m` | `800.0` | 100–3000 | m | (advanced) Maximum spacing of main valves on feeders. |
| `calorific_mj_per_m3` | `37.5` | 30–45 | MJ/m3 | Higher heating value used for energy conversion (therm/kWh display and billing). *Affects: gas bill energy, therm/kWh conversion.* |
| `base_pressure_kpa` | `101.325` | 90–110 | kPa | (advanced) Base pressure for standard volume. |
| `base_temperature_c` | `15.0` | 0–25 | C | (advanced) Base temperature for standard volume. |

## Water distribution

Supply, pumping, storage, mains, hydrants and services.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `lpcd` | `220.0` | 50–600 | L | Indoor residential use per person per day. *Affects: water bills, peak flow.* |
| `irrigation_m3_per_day` | `0.6` | 0–5 | m3 | Summer irrigation per irrigating house. |
| `max_day_factor` | `2.0` | 1–4 |  | (advanced) Max-day / average-day ratio. |
| `peak_hour_factor` | `3.0` | 1–6 |  | (advanced) Peak-hour / average-day ratio. |
| `fire_flow_residential_lps` | `63.0` | 0–200 | L/s | Required residential fire flow (1,000 USgpm). *Affects: minimum main size, hydrants.* |
| `fire_flow_commercial_lps` | `95.0` | 0–300 | L/s | (advanced) Required commercial/institutional fire flow. |
| `fire_flow_industrial_lps` | `190.0` | 0–500 | L/s | (advanced) Required industrial fire flow. |
| `min_main_mm` | `150` | 100–300 | mm | Smallest main where hydrants are attached. |
| `collector_main_mm` | `300` | 150–600 | mm | (advanced) Minimum main on collector roads. |
| `arterial_main_mm` | `400` | 200–900 | mm | (advanced) Minimum transmission main on arterials leaving the pump station. |
| `hw_c_new` | `130.0` | 60–150 |  | (advanced) Hazen-Williams C for PVC/ductile iron. |
| `hw_c_old` | `100.0` | 40–140 |  | (advanced) Hazen-Williams C for unlined cast iron. |
| `cast_iron_before_year` | `1960` | 1850–2000 |  | Districts built before this year have cast-iron mains. *Affects: main break rate, head loss.* |
| `tank_overflow_above_ground_m` | `42.0` | 20–80 | m | Elevated tank overflow height above the highest service in its zone. *Affects: service pressure.* |
| `zone_band_m` | `28.0` | 10–60 | m | (advanced) Elevation band per pressure zone. |
| `hydrant_spacing_m` | `150.0` | 50–300 | m | Hydrant spacing on residential mains. |
| `hydrant_spacing_commercial_m` | `90.0` | 40–200 | m | (advanced) Hydrant spacing in commercial areas. |
| `valve_spacing_m` | `240.0` | 60–600 | m | (advanced) Maximum spacing between line valves. |
| `pump_units` | `3` | 1–8 |  | (advanced) Pumps at the booster station (one is standby). |

## Metering & AMI

Meter technology mix, AMI collectors and nightly collection.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `ami_route_share` | `0.6` | 0–1 |  | Share of meter reading routes converted to AMI. *Affects: meter vans, manual reads, estimates, VEE comm-fail flags.* |
| `amr_route_share` | `0.25` | 0–1 |  | Share of routes read by drive-by AMR vans (rest are walked manually). *Affects: van routes, walker routes.* |
| `collector_radius_m` | `900.0` | 200–3000 | m | AMI collector coverage radius. *Affects: collector count, comm-fail clusters.* |
| `poll_start_hour` | `1.0` | 0–24 | h | Nightly head-end poll window start (local time). |
| `poll_end_hour` | `4.0` | 0–24 | h | Nightly head-end poll window end. |
| `meter_digits_electric` | `6` | 4–9 |  | (advanced) Register digits on electric meters (rollover at 10^digits). |
| `meter_digits_water` | `6` | 4–9 |  | (advanced) Register digits on water meters. |
| `meter_digits_gas` | `5` | 4–9 |  | (advanced) Register digits on gas meters. |
| `battery_life_years` | `15.0` | 3–30 | yr | (advanced) AMR/AMI endpoint battery life. |
| `comm_fail_rate` | `0.004` | 0–0.2 |  | Nightly probability an AMI meter fails to report. *Affects: estimated reads, consecutive estimates.* |

## Weather

Seeded daily weather. Drives magnitudes and volumes, never process structure.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `winter` | `mean_c=-4.5, sd_c=6.5, min_c=-28.0, max_c=12.0` |  |  | Winter (Dec 21–Mar 20). |
| `spring` | `mean_c=9.0, sd_c=6.0, min_c=-8.0, max_c=30.0` |  |  | Spring (Mar 21–Jun 20). |
| `summer` | `mean_c=21.5, sd_c=4.0, min_c=10.0, max_c=37.0` |  |  | Summer (Jun 21–Sep 20). |
| `fall` | `mean_c=9.5, sd_c=6.5, min_c=-10.0, max_c=28.0` |  |  | Fall (Sep 21–Dec 20). |
| `persistence` | `0.7` | 0–0.98 |  | (advanced) Day-to-day AR(1) persistence of temperature anomalies. |
| `storm_days_per_year` | `28.0` | 0–120 |  | Thunderstorm days per year (mostly May–Sep). *Affects: lightning outages, estimated reads.* |
| `heating_base_c` | `15.0` | 5–22 | C | (advanced) Heating starts below this temperature. |
| `cooling_base_c` | `22.0` | 15–30 | C | (advanced) Cooling starts above this temperature. |

## Incidents & hazards

What goes wrong, how often. Rates are per year.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `gas_service_leaks_per_1000` | `1.2` | 0–50 |  | Leaks per 1,000 gas services per year. |
| `gas_main_leaks_per_100km` | `8.0` | 0–200 |  | Leaks per 100 km of gas main per year. |
| `water_main_breaks_per_100km` | `14.0` | 0–200 |  | Main breaks per 100 km per year (×2 for cast iron). *Affects: water outages, crew workload.* |
| `overhead_faults_per_km_storm_day` | `0.015` | 0–1 |  | Overhead primary faults per km per storm day. *Affects: outages, SAIDI/SAIFI, zero-usage reads.* |
| `transformer_failures_per_1000` | `3.0` | 0–100 |  | Transformer failures per 1,000 units per year (×3 when overloaded). |
| `collector_outages_per_year` | `2.0` | 0–50 |  | AMI collector outages per year (town-wide). |
| `manual_only` | `False` |  |  | Disable random hazards; only manually injected incidents occur. |

## Field operations

Fleet, shifts, response targets and vehicle movement.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `gas_crews` | `2` | 0–20 |  | Gas emergency crews. *Affects: leak response time.* |
| `electric_crews` | `3` | 0–30 |  | Electric trouble crews. *Affects: outage duration, SAIDI.* |
| `water_crews` | `2` | 0–20 |  | Water distribution crews. |
| `meter_techs` | `2` | 0–20 |  | Meter technicians (exchanges, investigations). |
| `meter_vans` | `2` | 0–20 |  | Drive-by AMR reading vans. *Affects: AMR read completion.* |
| `meter_walkers` | `3` | 0–40 |  | Manual meter readers. *Affects: manual read completion, no-access.* |
| `shift_start_hour` | `7.0` | 0–23 | h | Day shift start. |
| `shift_end_hour` | `15.5` | 1–24 | h | Day shift end. |
| `gas_response_target_min` | `60.0` | 10–240 | min | Target response to a gas odour call. |
| `speed_kmh_arterial` | `50.0` | 10–100 | km/h | (advanced) Driving speed on arterials. |
| `speed_kmh_collector` | `40.0` | 10–80 | km/h | (advanced) Driving speed on collectors. |
| `speed_kmh_local` | `30.0` | 5–60 | km/h | (advanced) Driving speed on local streets. |
| `drive_by_radius_m` | `120.0` | 20–500 | m | (advanced) AMR van reads meters within this distance. |
| `walker_meters_per_hour` | `45.0` | 5–150 |  | (advanced) Manual reads per walker-hour. |

## Customers & billing

Accounts, reading routes, calendars and tariffs.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `mru_target_meters` | `450` | 50–3000 |  | Target premises per meter reading unit (route). *Affects: route count, read workload per day.* |
| `bill_cycles` | `21` | 1–31 |  | Billing portions per month (one per working day). |
| `currency` | `CAD` |  |  | Billing currency. |
| `tax_rate` | `0.13` | 0–0.3 |  | Sales tax on utility bills (Ontario HST). |
| `electric_fixed_monthly` | `36.5` | 0–500 | $ | Electric fixed delivery charge per month. |
| `electric_blocks` | `[{'up_to': 600.0, 'price': 0.098}, {'up_to': None, 'price': 0.116}]` |  | $/kWh | Electric energy price blocks per kWh (summer threshold). |
| `electric_variable_delivery` | `0.042` | 0–1 | $/kWh | Electric variable delivery per kWh. |
| `net_metering_credit` | `0.098` | 0–1 | $/kWh | Credit per exported kWh. *Affects: solar customer bills.* |
| `gas_fixed_monthly` | `26.5` | 0–500 | $ | Gas customer charge per month. |
| `gas_price_m3` | `0.36` | 0–5 | $/m3 | Gas delivery + supply per m³. |
| `water_fixed_monthly` | `18.0` | 0–500 | $ | Water fixed charge per month. |
| `water_price_m3` | `2.15` | 0–20 | $/m3 | Water volumetric charge. |
| `wastewater_ratio` | `1.05` | 0–3 |  | Wastewater charge as a multiple of the water volumetric charge. |
| `on_time_payer_share` | `0.82` | 0–1 |  | Share of accounts that pay on time. *Affects: dunning, collections, carrying cost.* |
| `late_payer_share` | `0.14` | 0–1 |  | Share that pay late. |
| `pre_authorized_share` | `0.45` | 0–1 |  | (advanced) Share on pre-authorized debit. |
| `due_days` | `20` | 5–60 |  | Days from invoice to due date. |

## Meter-to-cash process

Work queues, automation, costs and carrying cost.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `sequences` | `builtin` |  |  | Activity sequence library: 'builtin' or a path to a YAML file. |
| `rpa_coverage` | `0.35` | 0–1 |  | Share of exception types with an RPA/auto-resolve rule. *Affects: analyst workload, days to invoice, carrying cost.* |
| `analyst_queue_days_min` | `1` | 1–10 |  | Minimum queue wait before an analyst picks up an exception. |
| `analyst_queue_days_max` | `3` | 1–20 |  | Maximum queue wait. |
| `carry_rate_per_day` | `1.25` | 0–20 | $ | Carrying cost per account per day before invoicing. |
| `receivable_carry_ratio` | `0.4` | 0–1 |  | (advanced) Receivable carry as a share of the billing carry rate. |

## Meter & read anomalies

Injected faults with ground truth. Rates per 1,000 meters per year.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `enabled` | `True` |  |  | Inject anomalies into observed reads (truth is always kept separately). |
| `leak` | `8.0` | 0–200 |  | Continuous post-meter water leaks. |
| `stuck_meter` | `5.0` | 0–200 |  | Registers that stop advancing. |
| `slow_meter` | `4.0` | 0–200 |  | Meters under-registering 10–40%. |
| `transposed_digits` | `6.0` | 0–200 |  | Reads with two digits swapped. |
| `misread` | `6.0` | 0–200 |  | Reads off by one in a high digit. |
| `consecutive_estimates` | `15.0` | 0–200 |  | Runs of 2–4 estimated periods (higher on manual routes). |
| `missing_read` | `5.0` | 0–200 |  | Periods with no read document. |
| `exchange_registration_failure` | `2.0` | 0–100 |  | Meter exchanges whose new serial fails registration. |
| `vacant_consuming` | `3.0` | 0–100 |  | Vacant premises that still consume. |
| `tamper` | `1.0` | 0–50 |  | Bypass/tamper (50–90% under-registration). |

## Scenario

Demonstration scenario on the live clock.

| Field | Default | Range | Unit | Description |
|---|---|---|---|---|
| `name` | `normal` |  |  | Live demonstration scenario. |
| `date` | `2026-07-15` |  |  | Demonstration date (local). |
| `hour` | `8.0` | 0– | h | Demonstration hour (local, decimal). |
| `target_premise` | `None` |  |  | Premise targeted by the leak scenario (default: first premise). |
| `leak_m3h` | `0.65` | 0–50 | m3/h | Leak rate added to the target premise's water demand. |
| `tick_minutes` | `5` | 1–60 | min | Live clock step. |
