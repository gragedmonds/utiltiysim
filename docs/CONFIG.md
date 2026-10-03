# Configuration reference

Every assumption in the simulator is a field of `SimConfig` (see `utilsim/config/model.py`). The settings page is
generated from `GET /api/config/schema`, which carries these UI hints on every field:

| Hint | Meaning |
|---|---|
| `x-unit` | Unit shown next to the input (stored values are SI) |
| `x-advanced` | Hide behind an "Advanced" toggle |
| `x-effects` | What changes downstream when this value changes (show as a tooltip / "affects" chips) |
| `x-group`, `x-order` | Group cards and their order on the page |
| `x-applies` (on a group) | `town`: part of the town id, so changing it generates a new town (new `townId`, revisions and ids); `run`: applies to a simulation run of the same town (no regeneration) |
| `x-run-setting` | This town value is the default of an operations run setting with that key (`GET /api/sim/settings/schema?town=`): change it per run there without generating a new town |
| `x-reach` | Where the setting's effect reaches: `year` (the meter-to-cash year, same town), `town` (the customers, usage, routes or prices the year replays; a new town), `shape` (map geometry; the year moves only because homes are drawn again), `operations` (the operations day on the map), `display` (labels, units, clocks, default dates) |
| `x-impact` | How the setting changes the results, in a sentence or two (the first line of its (i) popover) |
| `x-status`, `x-status-reason` | `not-modelled`: the engine does not use the field yet (show it disabled with the reason); `deprecated`: another setting replaces it, named in `x-deprecated` |

Presets (`GET /api/config/presets`) are YAML overrides deep-merged on the defaults. The town id is a hash of the
generation-relevant config plus the generator version, so every combination is reproducible. The run-scoped groups
(`x-applies: run`: scenario, process, anomalies, reading, VEE, billing) are the meter-to-cash run's settings
(`GET /api/m2c/settings`). Crews, the day shift, the gas response target, incident rates and storm days stay in the
town groups but are only defaults: the operations run settings (`x-run-setting`) override them per run.

Each table below has a **Reaches** column and the setting's **How it changes the results** text
(`utilsim/config/impact.py`). Measurements behind them: [CONFIG_IMPACT.md](CONFIG_IMPACT.md). Settings removed in
generator 0.9.1 because nothing used them or they only labelled the map: `housing.semi_share`,
`electric.transmission_kv`, `electric.severe_turn_deg`, `ami.battery_life_years`, `ami.comm_fail_rate`,
`operations.drive_by_radius_m`, `operations.walker_meters_per_hour`, `process.sequences`, `scenario.tick_minutes`.
Configs that still carry them load; the keys are ignored.

## Knock-on chains worth demonstrating

| Change | What you should see |
|---|---|
| `housing.solar_rate` ↑ | More export registers and net-metering contracts; reverse flow on services, transformers and eventually the whole town at noon |
| `housing.ev_rate` ↑ | Higher individual peaks → larger transformers, more transformer groups, heavier feeders, more feeders |
| `housing.electric_heat_rate` ↑ or `gas.all_electric_district_share` ↑ | Fewer gas services and smaller gas mains; higher electric design load |
| `electric.overhead_before_year` ↑ | More overhead districts → poles, pole-mount transformers, lightning exposure (M3 outages) |
| `gas.scheme` = `mp` | No low-pressure core, no district regulators, ¾" services with regulators everywhere |
| `water.fire_flow_residential_lps` ↑ | Larger distribution mains everywhere (fire flow governs sizing) |
| `water.cast_iron_before_year` ↑ | More unlined cast-iron mains along the older streets: more head loss (`hw_c_old`) and twice the background main-break rate |
| `incidents.*` / `weather.storm_days_per_year` ↑ (or the run's random-incident settings) | More background incidents on operations days: crews busier, more interruptions, more outage-explained estimates in meter-to-cash |
| `town.terrain_relief_m` ↑ | Second pressure zone, second elevated tank, PRV/booster equipment at zone boundaries |
| `ami.ami_route_share` ↓ | More AMR van and manual walker routes; more estimated reads (M3) |
| `customers_billing.mru_target_meters` ↓ | More, smaller meter reading routes |
| `town.houses` ↑ | A wider town whose edge reaches newer eras; a second substation; more feeders, routes and accounts |
| `town.commercial_share_arterial` / `_collector` / `_local` ↑ | More storefronts on that class of street, clustered at main-road intersections and towards downtown; homes pushed outward (still exactly `houses`); more 3φ pads, commercial accounts and closer hydrant spacing |
| A preset (`village`, `small_town`, `town`, `large_town`, `city`, `us_town`) | A generic town of that size; every street comes from the settings and the seed, never from a real place |


## Seeds

Master seed and optional per-subsystem re-rolls.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `master` | town | `TOWN-042` |  |  | Master seed. Any text or integer; same seed + config + generator version reproduces the same town byte for byte. *Affects: everything.* | Re-rolls everything: the streets, households, weather, incidents and the year's draws. Use it to see how much results vary by chance alone. |
| `town` | town | `None` |  |  | (advanced) Override seed for geography only (roads growth, parcels, buildings). | Re-rolls the geography (growth, lots, buildings). Households sit on lots, so they are drawn again too and usage totals shift by a few percent. |
| `households` | town | `None` |  |  | (advanced) Override seed for household attributes (occupants, solar, EV, heating). | Re-rolls who lives where: occupants, solar, EVs, heating fuel, pools, payer profiles and tenancies. Streets stay put. Small towns move several percent on solar export. |
| `weather` | town | `None` |  |  | (advanced) Override seed for weather series (re-roll storms, keep the town). | Re-rolls the daily temperatures: heating and cooling usage follow, and so do the cold days that make AMI, AMR and walked reads miss more often. |
| `incidents` | town | `None` |  |  | (advanced) Override seed for incident hazards. | Re-rolls the random leaks, breaks, faults and collector outages, on the operations day and across the year, so the outage and gas odour contacts move too. |
| `anomalies` | town | `None` |  |  | (advanced) Override seed for the meter-to-cash run (missed reads, anomalies, analyst work, bill checks); a request's run seed overrides it per run. | Re-rolls the year's draws (missed reads, anomalies, analyst work, bill checks) on the same households. A run's own seed overrides it without building a new town. |

## Town & geography

Size, street grid, terrain and land use. Towns are generic: every street comes from these settings and the seed.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `houses` | town | `480` | 20–10000 |  | Number of residential premises to place. *Affects: town extent, era mix, substations, feeders, pipe sizes, MRUs.* | The number of homes. Accounts, reads, exceptions, bills and staffing load scale with it; a bigger town also spreads further, so its edge reaches newer eras. |
| `units` | display | `ontario` |  |  | Display unit profile (stored values are always SI). | How values are labelled (Ontario, US or UK units). Stored values stay SI; no result changes. |
| `anchor_lat` | display | `43.3` | -80–80 | deg | (advanced) Latitude of the town (sun path, day length). | Where the town sits on the globe: its latitude and the sun path in the map's day and night. Measured: no usage, network or year change. |
| `anchor_lon` | display | `-80.6` | -180–180 | deg | (advanced) Longitude of the town. | Where the town sits on the globe (its longitude). Measured: no usage, network or year change. |
| `timezone` | display | `America/Toronto` |  |  | IANA timezone of the town (read schedules, billing calendar, day/night). | The local clock for timestamps, read schedules and business days. Measured: the year's figures do not change, only the times printed on records. |
| `terrain_relief_m` | operations | `15.0` | 0–120 | m | Peak-to-trough terrain relief. *Affects: water pressure zones, PRVs, tank siting.* | Hillier towns get a second water pressure zone, another elevated tank and PRVs or boosters at zone boundaries: pressures on the operations day. |
| `terrain_wavelength_m` | operations | `900.0` | 100–5000 | m | (advanced) Dominant wavelength of terrain undulation. | How quickly the ground rises and falls: elevations, water pressures and zone boundaries on the operations day. |
| `arterial_spacing_m` | shape | `1400.0` | 600–2400 | m | (advanced) Mean spacing of arterial roads (concession-grid style). | Synthetic towns and grown districts only: how far apart the main roads run, so block sizes and drive times. On a real-street town it does nothing. |
| `arterial_warp_m` | shape | `130.0` | 0–400 | m | (advanced) Amplitude of the smooth warp applied to arterials. | Synthetic towns and grown districts only: how much the main roads bend. |
| `collector_block_m` | shape | `650.0` | 250–1500 | m | (advanced) Superblocks larger than this get a collector road. | Synthetic towns and grown districts only: superblocks larger than this get a collector road. |
| `era_core_year` | town | `1925` | 1850–2020 |  | Construction year at the town centre. *Affects: street pattern, lot sizes, overhead vs underground electric, legacy gas district, cast-iron water mains, solar/EV uptake.* | When the centre was built; ages every home. Older homes leak more heat (more gas or electric heating), rent more, have less solar and EV, and sit on overhead lines and cast-iron mains. |
| `era_span_years` | town | `85` | 0–150 |  | Years added from centre to edge (era = core + span·(d/R)^1.2 + noise). | How much newer the edge is than the centre. A wider span puts more homes in the modern era: better insulation, more solar, EVs, pools and irrigation. |
| `era_noise_years` | town | `8.0` | 0–30 | yr | (advanced) Std-dev of era noise per district. | Scatter of construction years between districts: a few districts change era, which shifts their insulation, appliances and tenure. |
| `park_share` | shape | `0.04` | 0–0.2 |  | (advanced) Share of blocks kept as parks. | Blocks kept as parks. Homes move to other blocks; the count stays the same. |
| `commercial_strip_m` | town | `700.0` | 0–3000 | m | Length of the downtown main street: arterial frontage within half this distance of the centre is all commercial (up to 80 lots). The frontage shares below apply beyond it. *Affects: downtown storefronts, homes pushed outward.* | Length of the all-commercial main street downtown: more storefront accounts with commercial usage, tariffs and gas heat. |
| `commercial_share_arterial` | town | `0.45` | 0–1 |  | Share of developed lots fronting an arterial (beyond the downtown main street) that become commercial or mixed-use premises. The rest are homes, or rear yards where modern subdivisions back onto the arterial. *Affects: commercial premises, plazas at major intersections, commercial hydrant spacing, transformer pads, commercial accounts.* | Share of arterial frontage that becomes shops: more commercial accounts (large, steady electric and gas loads) while homes stay at the count. |
| `commercial_share_collector` | town | `0.15` | 0–1 |  | Share of developed lots fronting a collector that become commercial or mixed-use premises. *Affects: commercial premises, corner shops on collectors, commercial accounts.* | Share of collector frontage that becomes shops: more commercial accounts. |
| `commercial_share_local` | town | `0.02` | 0–1 |  | Share of developed lots on local streets that become commercial (corner stores near downtown and where local streets meet main roads). *Affects: commercial premises, homes pushed outward.* | Corner stores on local streets: a few more commercial accounts. |
| `commercial_cluster_m` | shape | `120.0` | 20–1000 | m | (advanced) Distance over which commercial frontage clusters around main-road intersections and downtown. Smaller gives tight corner clusters, larger gives long strips. *Affects: where storefronts sit along main roads.* | How tightly shops cluster around main-road junctions and downtown. Which lots hold shops changes, not how many. |
| `industrial_lots` | town | `2` | 0–10 |  | Number of large industrial customers. | Large industrial customers. Each is a very large electric, gas and water account; two of them are about a tenth of a small town's usage. |
| `houses_per_school` | town | `2500` | 500–20000 |  | (advanced) One school per this many houses. | One school per this many homes, rounded (towns under about 1,250 homes have none). A school is an institutional account with a large floor area, heavy water use and gas heat. |
| `margin_m` | shape | `120.0` | 0–1000 | m | (advanced) Empty margin around the developed area. | Empty land around the developed area, where utility sites sit. It moves things on the map only. |
| `corridor_max_deflection_deg` | operations | `35.0` | 5–90 | deg | (advanced) Arterial/collector road edges continue one corridor through a junction when the heading changes by at most this much. *Affects: corridors, trunk routes, corridor changes.* | How sharp a bend still counts as one road corridor: feeder routes follow corridors, so it can change which customers share a feeder (and an outage) on the operations day. |
| `corridor_name_bonus_deg` | operations | `20.0` | 0–60 | deg | (advanced) Extra deflection allowed when both edges carry the same street name (a name is weak evidence of continuity). *Affects: corridors.* | Extra bend allowed when both roads share a name, for feeder corridors on the operations day. |

## Housing & households

Lots, buildings and the people and appliances inside them.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `lot_frontage_m` | town | `pre_1945=15.0, postwar=18.5, modern=16.5` |  | m | Mean lot frontage by era. *Affects: houses per km of street.* | Wider lots build wider houses (55 to 70 percent of the frontage, up to 15 m): more floor area, so more heating and base load. Fewer lots fit each street, so homes spread to other streets and eras. Pools need lots over 600 m². |
| `lot_depth_m` | town | `pre_1945=36.0, postwar=35.0, modern=33.0` |  | m | Mean lot depth by era. | Deeper lots are larger (pools need over 600 m²) and leave room for deeper houses on shallow streets. On synthetic towns it also reshapes blocks, which re-draws households, so totals move by about seed-sized noise. |
| `setback_m` | shape | `pre_1945=6.0, postwar=7.5, modern=6.5` |  | m | (advanced) Front setback by era. | How far houses sit back from the street. On shallow lots a deep setback makes the house shallower, a fraction of a percent of usage. |
| `two_storey_share` | town | `pre_1945=0.7, postwar=0.25, modern=0.75` |  |  | Share of two-storey houses by era. | Two storeys double the floor area on the same footprint: more heating in winter, more cooling and base load, and higher bills. |
| `occupancy_rate` | town | `0.955` | 0.5–1.0 |  | Share of premises occupied at simulation start. *Affects: vacant consumption, VEE vacancy signals, move-ins.* | Vacant homes use almost nothing (12 percent of base load, 3 percent of water). Fewer occupied homes: lower usage, more zero-use reads for VEE, vacant-consuming cases and first bills at move-in. |
| `rental_share` | town | `0.28` | 0–1 |  | Share of premises that are rentals (more contract turnover). *Affects: move-in/out frequency, contract history.* | Rentals turn over: more move-ins and move-outs, so more first bills, final bills, short tenancies and contract changes for billing and collections. |
| `household_size_weights` | town | `[0.28, 0.34, 0.15, 0.15, 0.06, 0.02]` |  |  | (advanced) Relative frequency of households with 1..6 occupants. | Bigger households use more water (people times litres per day) and more base electricity: higher water bills above all. |
| `solar_rate` | town | `pre_1945=0.06, postwar=0.1, modern=0.18` |  |  | Share of houses with rooftop PV by era. *Affects: export registers, midday reverse flow, net-metering credits.* | Homes with rooftop PV by era: export registers, net-metering credits on bills, and low or negative summer net use that VEE and billing must handle. |
| `pv_kw_min` | town | `4.0` | 0.5–20 | kW | Smallest rooftop PV system. | Smallest PV system: more export and larger net-metering credits per solar home. |
| `pv_kw_max` | town | `9.5` | 1–30 | kW | Largest rooftop PV system. | Largest PV system: more export and larger summer credits per solar home. |
| `ev_rate` | town | `pre_1945=0.05, postwar=0.07, modern=0.12` |  |  | Share of houses with an EV charger. *Affects: transformer loading, evening peak.* | EV chargers add about 6.5 kWh a day per home, all year: higher electric usage and bills, and bigger transformers on the map. |
| `electric_heat_rate` | town | `pre_1945=0.1, postwar=0.14, modern=0.18` |  |  | Share of houses heated electrically (baseboard or heat pump) where gas is available. All houses in all-electric districts are electric. *Affects: gas service count, winter electric peak.* | Electric instead of gas heat: winter electric usage and bills rise, gas accounts and gas usage fall. |
| `heat_pump_share_of_electric` | town | `0.55` | 0–1 |  | (advanced) Share of electric heating that is a heat pump (vs baseboard). | Heat pumps use far less than baseboard heat for the same warmth: lower winter electric usage and bills. |
| `ac_rate` | town | `0.85` | 0–1 |  | Share of houses with central air conditioning. *Affects: summer peak, transformer sizing.* | Central air adds cooling load on hot days: higher July and August electric usage and bills, and summer high-bill checks. |
| `pool_rate` | town | `0.06` | 0–0.5 |  | (advanced) Share of houses (on lots > 600 m²) with a pool. | Pools (only on lots over 600 m², more in modern districts) run a pump and heater on electricity, about 7.5 kWh a day from May to September, and top up 0.15 m³ of water a day. Pools are not heated with gas in this engine. |
| `irrigation_rate` | town | `0.3` | 0–1 |  | Share of houses that irrigate lawns in summer. *Affects: summer water peak.* | Lawn watering adds summer water use (May to September, peaking in July): higher summer water bills and seasonal swings VEE must accept. |

## Electric distribution

Bulk supply, substations, feeders, transformers, services.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `primary_kv` | operations | `13.8` | 4.16–34.5 | kV | Primary distribution line-to-line voltage (Ontario urban 13.8 kV; US 12.47 kV). *Affects: feeder capacity, conductor sizing.* | Feeder voltage: voltage drop and loading in the operations day's power flow. |
| `secondary_v` | operations | `240.0` | 120–480 | V | (advanced) Split-phase secondary voltage (120/240 V). | Service voltage for the power flow and the voltage readings on the map. |
| `kva_per_100m2` | operations | `1.0` | 0.2–5 | kVA | Individual peak demand per 100 m² of floor area (lighting, plug, appliances). *Affects: transformer sizing.* | Design load per floor area: transformer and conductor sizes, so loading and overload failures on the operations day. Usage is not affected. |
| `kva_ac` | operations | `3.5` | 0–10 | kVA | Added peak for central air conditioning. | Design load added for air conditioning: equipment sizing on the map. |
| `kva_electric_heat` | operations | `6.0` | 0–20 | kVA | Added peak for electric resistance heat. | Design load added for electric heat: equipment sizing on the map. |
| `kva_heat_pump` | operations | `4.0` | 0–15 | kVA | Added peak for a heat pump. | Design load added for a heat pump: equipment sizing on the map. |
| `kva_ev` | operations | `7.2` | 0–20 | kVA | Added peak for a Level-2 EV charger. | Design load added for an EV charger: equipment sizing on the map. |
| `kva_pool` | operations | `1.5` | 0–10 | kVA | (advanced) Added peak for a pool pump/heater. | Design load added for a pool: equipment sizing on the map. |
| `coincidence_floor` | operations | `0.33` | 0.1–1.0 |  | (advanced) Coincidence factor CF(n) = a + (1-a)/√n; a is the floor as n → ∞. *Affects: every electric size.* | How much peaks overlap: larger floors size bigger transformers and feeders. |
| `transformer_kva_steps` | operations | `[25, 50, 75, 100, 167]` |  | kVA | (advanced) Single-phase transformer sizes. | The transformer sizes available: groupings, loading and overloads on the map. |
| `transformer_max_loading` | operations | `1.3` | 0.8–2.0 |  | (advanced) Allowed peak loading relative to nameplate. | Allowed loading before a bigger transformer is chosen: overloaded units fail three times as often on the operations day. |
| `conductor_planning_margin` | operations | `1.25` | 1.0–2.0 |  | (advanced) Primary conductors are sized for design load × this margin (winter peaks, load growth). *Affects: primary conductor sizes, loading in power flow.* | Head-room in primary conductor sizing: thicker conductors, less loading on the map. |
| `max_houses_per_transformer_overhead` | operations | `6` | 1–20 |  | Max houses on a pole-mount transformer. | Houses per pole transformer: how many customers lose power when one fails. |
| `max_houses_per_transformer_underground` | operations | `10` | 1–25 |  | Max houses on a pad-mount transformer. | Houses per pad transformer: how many customers lose power when one fails. |
| `feeder_design_mva` | operations | `6.0` | 1–20 | MVA | Design peak per feeder. *Affects: feeder count, tie switches.* | Design peak per feeder: how many feeders, and so how many customers one feeder fault interrupts. |
| `feeder_max_customers` | operations | `1200` | 100–10000 |  | Most customers planned on one feeder (limits how many lose supply when a feeder breaker trips). *Affects: feeder count, feeder territories, tie switches.* | Most customers on one feeder: the largest outage one breaker trip can cause. |
| `min_feeders_per_substation` | operations | `2` | 1–12 |  | Feeders leaving each substation at least (fewer only when it serves fewer transformer groups), so normally-open ties can back-feed. *Affects: feeder count, tie switches, outage size.* | Feeders per substation, so ties can back-feed during an outage. |
| `substation_mva` | operations | `25.0` | 5–100 | MVA | Firm capacity per substation. *Affects: substation count.* | Firm capacity per substation: big towns get a second substation. |
| `route_weight_arterial` | operations | `1.0` | 0.1–10 |  | (advanced) Feeder routing cost per metre along an arterial (trunks follow the cheapest corridors). *Affects: trunk routes, feeder territories.* | Feeder routing cost along arterials: where trunks run and which customers share them. |
| `route_weight_collector` | operations | `1.4` | 0.1–10 |  | (advanced) Feeder routing cost per metre along a collector. *Affects: trunk routes.* | Feeder routing cost along collector roads: where trunks run on the map. |
| `route_weight_local` | operations | `2.0` | 0.1–10 |  | (advanced) Feeder routing cost per metre along a local street. *Affects: trunk routes, lateral routes.* | Feeder routing cost along local streets: where trunks run on the map. |
| `route_turn_penalty_m` | operations | `60.0` | 0–2000 | m | (advanced) Routing cost of a 90° turn, in weighted metres; it grows with the square of the angle (a U-turn costs 4×). Bends under 10° are free. *Affects: trunk continuity, severe turns.* | How much feeders avoid turns: straighter, longer trunks. |
| `route_corridor_change_penalty_m` | operations | `80.0` | 0–2000 | m | (advanced) Routing cost of switching from one arterial/collector corridor to another. *Affects: trunk continuity, corridor changes.* | How much feeders avoid switching corridors: straighter feeders on the map. |
| `route_hierarchy_penalty_m` | operations | `60.0` | 0–2000 | m | (advanced) Routing cost per step up or down the road hierarchy (arterial ↔ collector ↔ local). *Affects: trunks staying on main roads.* | How much feeders avoid stepping between road classes. |
| `trunk_min_load_share` | operations | `0.04` | 0–0.5 |  | (advanced) A feeder trunk extends along a corridor while at least this share of the feeder's connected load lies at or beyond that point; smaller tails are served by laterals. *Affects: trunk length, three-phase backbone.* | How far a three-phase trunk extends before laterals take over. |
| `route_shared_trunk_factor` | operations | `1.2` | 1.0–5.0 |  | (advanced) Cost multiplier for running a feeder express through another feeder's territory or alongside its trunk. *Affects: express sections, feeder separation.* | How much feeders avoid running through each other's territory. |
| `ties_per_feeder_pair` | operations | `1` | 0–4 |  | Normally-open tie switches between each pair of neighbouring feeders (0: no ties at all, section ties included). *Affects: tie switches, back-feed options.* | Normally-open ties: with ties, crews restore part of a faulted feeder from a neighbour, so outages are shorter on the operations day. |
| `tie_max_length_m` | operations | `1200.0` | 0–5000 | m | (advanced) Longest new line built for a tie: to a feeder that touches no other feeder, or from a switched section to another feeder's three-phase line (or round to its own feeder's). Along a street a line already uses, a metre counts 1.25 (single-phase) or 2 (three-phase). *Affects: tie switches, back-feed options.* | Longest line built for a tie: more ties, more restoration options. |
| `section_max_share` | operations | `0.15` | 0.05–1.0 |  | Sectionalising switches cut each feeder's three-phase backbone into sections of at most this share of the feeder's customers (at least section_min_customers), so a crew isolates a fault within a bounded section and ties back-feed the healthy sections beyond it. *Affects: sectionalising switches, tie switches, outage size after isolation.* | Sectionalising switches: smaller sections mean a fault takes out fewer customers. |
| `section_min_customers` | operations | `100` | 10–5000 |  | (advanced) Smallest section limit: a feeder is not cut into sections smaller than this many customers. *Affects: sectionalising switches, outage size after isolation.* | Smallest section a feeder is cut into: how few customers one fault can take out. |
| `overhead_before_year` | operations | `1978` | 1850–2030 |  | Districts built before this year are overhead (poles); later underground. *Affects: poles, lightning exposure, storm outages.* | Districts built before this year are on poles: storm faults and pole transformers on the operations day. |
| `pole_spacing_m` | operations | `42.0` | 20–90 | m | (advanced) Pole span on overhead lines. | Pole span on overhead lines: pole count, and where AMI collectors can mount. |
| `voltage_min_pu` | operations | `0.95` | 0.85–1.0 |  | (advanced) Lower service voltage limit (CSA CAN3-C235 / ANSI Range A). Frames report it on a 120 V base (premises.voltageLimits) with the premises below it; less 4 V it is the default floor for back-feeding through a tie. *Affects: low-voltage premises, voltage lens, back-feed voltage floor.* *Default of the operations run setting `tieMinVoltage`.* | Low-voltage limit for the voltage readings on the map. |
| `voltage_max_pu` | operations | `1.05` | 1.0–1.15 |  | (advanced) Upper service voltage limit (premises.voltageLimits in frames). *Affects: high-voltage premises, voltage lens.* | High-voltage limit for the voltage readings on the map. |

## Natural gas

City gate, mains, regulators and services.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `all_electric_district_share` | town | `0.15` | 0–1 |  | Share of districts with no gas mains (all-electric). *Affects: gas services, electric heat share, winter electric peak.* | Share of districts without gas mains, counted in whole districts and never the core: those homes heat with electricity, mostly heat pumps. Gas accounts and usage fall, winter electric usage rises. One-district towns (village, small_town) have none whatever the share. |
| `scheme` | operations | `mp_with_lp_core` |  |  | Medium-pressure PE everywhere with a regulator at every meter, optionally with a legacy low-pressure core fed by district regulators. | Medium pressure everywhere or a legacy low-pressure core: regulators and pressures on the map. |
| `transmission_kpa` | operations | `3800.0` | 700–10000 | kPa | (advanced) Off-map transmission pressure at the city gate inlet. | Pressure into the city gate: gas pressures on the operations day. |
| `mp_kpa` | operations | `414.0` | 35–700 | kPa | Medium-pressure distribution set point (60 psig). | Medium-pressure set point: gas pressures on the operations day. |
| `lp_kpa` | operations | `1.74` | 0.5–7 | kPa | (advanced) Low-pressure legacy main set point (7 in w.c.). | Low-pressure core set point: gas pressures on the operations day. |
| `lp_core_before_year` | operations | `1945` | 1850–2000 |  | (advanced) Districts built before this year are on the low-pressure system. | Districts older than this sit on the low-pressure core. |
| `design_m3h_base` | operations | `1.15` | 0–10 | m3/h | Design-hour demand per house, base component (≈ 40 CFH). | Design-hour demand per house: gas main sizes. Usage is not affected. |
| `design_m3h_per_m2` | operations | `0.017` | 0–0.2 | m3/h | Design-hour demand per m² of floor area (≈ 0.6 CFH/m²). | Design-hour demand per floor area: gas main sizes. |
| `coincidence_floor` | operations | `0.5` | 0.1–1 |  | (advanced) Gas coincidence factor floor a in CF(n) = a + (1-a)/√n. | How much gas peaks overlap: larger floors size bigger gas mains. |
| `min_main_mm` | operations | `50` | 25–150 | mm | Smallest distribution main (2-inch PE). | Smallest gas main: pipe sizes and pressures on the map. Usage is not affected. |
| `valve_spacing_m` | operations | `800.0` | 100–3000 | m | (advanced) Maximum spacing of main valves on feeders. | Valve spacing: how much main a leak repair isolates. |
| `calorific_mj_per_m3` | display | `37.5` | 30–45 | MJ/m3 | Higher heating value used for energy conversion (therm/kWh display and billing). *Affects: gas bill energy, therm/kWh conversion.* | Energy per cubic metre for showing gas in GJ or therms. Bills charge per m³, so no amount changes. |
| `base_pressure_kpa` | operations | `101.559771` | 90–110 | kPa | (advanced) Base pressure for standard volume: the Weymouth base pressure in gas main sizing and pressures (default 14.73 psia). *Affects: gas main sizes, gas pressures.* | Standard-volume base pressure in the gas flow equations. |
| `base_temperature_c` | operations | `15.738889` | 0–25 | C | (advanced) Base temperature for standard volume: the Weymouth base temperature (default 520 °R, about 60 °F). *Affects: gas main sizes, gas pressures.* | Standard-volume base temperature in the gas flow equations. |

## Water distribution

Supply, pumping, storage, mains, hydrants and services.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `lpcd` | town | `220.0` | 50–600 | L | Indoor residential use per person per day. *Affects: water bills, peak flow.* | Indoor water per person per day: every home's water usage and bill scales with it, and wastewater charges follow. |
| `irrigation_m3_per_day` | town | `0.6` | 0–5 | m3 | Summer irrigation per irrigating house. | Summer watering per irrigating home: higher summer water usage and bills. |
| `max_day_factor` | operations | `2.0` | 1–4 |  | (advanced) Max-day / average-day ratio. | Max-day demand used to size mains and storage on the map. |
| `peak_hour_factor` | operations | `3.0` | 1–6 |  | (advanced) Peak-hour / average-day ratio. | Peak-hour demand used to size mains: pipe sizes and pressures on the map. |
| `fire_flow_residential_lps` | operations | `63.0` | 0–200 | L/s | Required residential fire flow (1,000 USgpm). *Affects: minimum main size, hydrants.* | Fire flow that sizes residential mains: bigger mains, lower velocities. |
| `fire_flow_commercial_lps` | operations | `95.0` | 0–300 | L/s | (advanced) Required commercial/institutional fire flow. | Fire flow that sizes commercial mains: pipe sizes and pressures on the map. |
| `fire_flow_industrial_lps` | operations | `190.0` | 0–500 | L/s | (advanced) Required industrial fire flow. | Fire flow that sizes the industrial and supply mains. |
| `min_main_mm` | operations | `150` | 100–300 | mm | Smallest main where hydrants are attached. | Smallest main that carries hydrants: pipe sizes and pressures on the map. |
| `collector_main_mm` | operations | `300` | 150–600 | mm | (advanced) Minimum main on collector roads. | Smallest main on collector roads: pipe sizes and pressures on the map. |
| `arterial_main_mm` | operations | `400` | 200–900 | mm | (advanced) Minimum transmission main on arterials leaving the pump station. | Smallest transmission main from the pump station. |
| `hw_c_new` | operations | `130.0` | 60–150 |  | (advanced) Hazen-Williams C for PVC/ductile iron mains. *Affects: head loss, service pressure.* | Pipe roughness of new mains: pressures on the operations day. |
| `hw_c_old` | operations | `100.0` | 40–140 |  | (advanced) Hazen-Williams C for unlined cast iron mains. *Affects: head loss, service pressure.* | Pipe roughness of old cast iron: more head loss, lower pressures. |
| `cast_iron_before_year` | operations | `1960` | 1850–2000 |  | Mains along streets built before this year are unlined cast iron (the concrete trunk excepted). *Affects: cast-iron mains, main break rate (×2), head loss.* | Mains older than this are cast iron: rougher and break twice as often on the operations day. |
| `tank_overflow_above_ground_m` | operations | `42.0` | 20–80 | m | Elevated tank overflow height above the highest service in its zone. *Affects: service pressure.* | Elevated tank height: static pressure in its zone. |
| `zone_band_m` | operations | `28.0` | 10–60 | m | (advanced) Elevation band per pressure zone. | Elevation band per pressure zone: how many zones a hilly town needs. |
| `hydrant_spacing_m` | operations | `150.0` | 50–300 | m | Hydrant spacing on residential mains. | Hydrant spacing on residential mains: hydrant count on the map. |
| `hydrant_spacing_commercial_m` | operations | `90.0` | 40–200 | m | (advanced) Hydrant spacing in commercial areas. | Hydrant spacing in commercial areas: hydrant count on the map. |
| `valve_spacing_m` | operations | `240.0` | 60–600 | m | (advanced) Maximum spacing between line valves. | Valve spacing: how many customers a main break isolates. |
| `pump_units` | operations | `3` | 1–8 |  | (advanced) Pumps at the booster station (one is standby). | Pumps at the station, one on standby: pumping capacity on the operations day. |

## Metering & AMI

Meter technology mix, AMI collectors and nightly collection.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `ami_route_share` | town | `0.6` | 0–1 |  | Share of meter reading routes converted to AMI. *Affects: meter vans, manual reads, estimates, VEE comm-fail flags.* | Routes read by AMI. AMI reads are cheapest and miss least (1.2 percent); moving routes to AMR or walkers raises read cost, missed reads, estimates and the work they create. |
| `amr_route_share` | town | `0.25` | 0–1 |  | Share of routes read by drive-by AMR vans (rest are walked manually). *Affects: van routes, walker routes.* | Routes read by drive-by AMR vans: costlier than AMI and missed more often (3 percent), with their own anomaly factor. The rest are walked. |
| `collector_radius_m` | operations | `900.0` | 200–3000 | m | AMI collector coverage radius. *Affects: collector count, comm-fail clusters.* | AMI collector reach: how many collectors, and how many meters go dark when one fails on the operations day. |
| `poll_start_hour` | display | `1.0` | 0–24 | h | Nightly head-end poll window start (local time). | When the nightly AMI poll starts: the time stamped on AMI reads. Results do not change. |
| `poll_end_hour` | display | `4.0` | 0–24 | h | Nightly head-end poll window end. | When the nightly AMI poll ends: the latest time stamped on AMI reads. Results do not change. |
| `meter_digits_electric` | town | `6` | 4–9 |  | (advanced) Register digits on electric meters (rollover at 10^digits). | Register digits on electric meters: where registers roll over, and how far a transposed or misread digit throws a read. |
| `meter_digits_water` | town | `6` | 4–9 |  | (advanced) Register digits on water meters. | Register digits on water meters: rollover and digit-error size. |
| `meter_digits_gas` | town | `5` | 4–9 |  | (advanced) Register digits on gas meters. | Register digits on gas meters: rollover and digit-error size. |

## Weather

Seeded daily weather. Drives magnitudes and volumes, never process structure.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `winter` | town | `mean_c=-4.5, sd_c=6.5, min_c=-28.0, max_c=12.0` |  |  | Winter (Dec 21–Mar 20). | Winter temperatures: colder winters raise heating usage (gas, or electricity for electric homes), winter bills, and the deep-cold days below -10 °C when reads miss more. |
| `spring` | town | `mean_c=9.0, sd_c=6.0, min_c=-8.0, max_c=30.0` |  |  | Spring (Mar 21–Jun 20). | Spring temperatures: a cold spring keeps heating usage and bills up into April and May. |
| `summer` | town | `mean_c=21.5, sd_c=4.0, min_c=10.0, max_c=37.0` |  |  | Summer (Jun 21–Sep 20). | Summer temperatures: hotter summers raise cooling usage and bills on homes with air conditioning. |
| `fall` | town | `mean_c=9.5, sd_c=6.5, min_c=-10.0, max_c=28.0` |  |  | Fall (Sep 21–Dec 20). | Fall temperatures: an early cold snap raises October and November heating usage and bills. |
| `persistence` | town | `0.7` | 0–0.98 |  | (advanced) Day-to-day AR(1) persistence of temperature anomalies. | How long warm or cold spells last: longer spells make monthly usage swing more from normal, which VEE's tolerances see. |
| `storm_days_per_year` | town | `28.0` | 0–120 |  | Thunderstorm days per year (mostly May–Sep). *Affects: lightning outages, estimated reads.* *Default of the operations run setting `stormDaysPerYear`.* | Thunderstorm days: overhead faults and outages on the operations day and across the year, with the outage reports they bring to the contact centre. |
| `heating_base_c` | town | `15.0` | 5–22 | C | (advanced) Heating starts below this temperature. | Heating starts below this temperature: a higher base means more heating usage in spring and fall. |
| `cooling_base_c` | town | `22.0` | 15–30 | C | (advanced) Cooling starts above this temperature. | Cooling starts above this temperature: a lower base means more cooling usage. |

## Incidents & hazards

What goes wrong, how often. Rates are per year. Each operations day draws its background incidents at these rates; they are the defaults of the operations run's random-incident settings (x-run-setting), so a run can change them without a new town.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `gas_service_leaks_per_1000` | town | `1.2` | 0–50 |  | Leaks per 1,000 gas services per year. *Default of the operations run setting `gasServiceLeaksPer1000`.* | Random service leaks on the operations day and across the year: gas odour calls and a household without gas until the repair. |
| `gas_main_leaks_per_100km` | town | `8.0` | 0–200 |  | Leaks per 100 km of gas main per year. *Default of the operations run setting `gasMainLeaksPer100km`.* | Random gas main leaks on the operations day and across the year: crew calls, isolations and gas odour calls from the neighbours. |
| `water_main_breaks_per_100km` | town | `14.0` | 0–200 |  | Main breaks per 100 km per year (×2 for cast iron). *Affects: water outages, crew workload.* *Default of the operations run setting `waterMainBreaksPer100km`.* | Random main breaks on the operations day and across the year: customers without water and the outage reports they make. |
| `overhead_faults_per_km_storm_day` | town | `0.015` | 0–1 |  | Overhead primary faults per km per storm day. *Affects: outages, SAIDI/SAIFI, zero-usage reads.* *Default of the operations run setting `overheadFaultsPerKmStormDay`.* | Storm faults on overhead lines: feeder outages on storm days, on the operations day and across the year, and the outage reports. |
| `transformer_failures_per_1000` | town | `3.0` | 0–100 |  | Transformer failures per 1,000 units per year (×3 when overloaded). *Default of the operations run setting `transformerFailuresPer1000`.* | Transformer failures (three times as many where units are overloaded): small outages on the operations day and across the year. |
| `collector_outages_per_year` | operations | `2.0` | 0–50 |  | AMI collector outages per year (town-wide). *Default of the operations run setting `collectorOutagesPerYear`.* | AMI collector outages: the meters behind it miss their nightly read that day. Customers do not notice them. |
| `manual_only` | operations | `False` |  |  | Disable random hazards; only manually injected incidents occur (the run's "Random incidents" switch defaults to the opposite). *Affects: background incidents.* *Default of the operations run setting `randomIncidents`.* | Turns random incidents off on the operations day; only the ones you inject happen. The year draws them unless Outages & leaks is off. |

## Field operations

Fleet, shifts, response targets and vehicle movement. Crews, readers, the shift and the gas target are the defaults of the operations run settings (x-run-setting), so a run can change them without a new town.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `gas_crews` | operations | `2` | 0–20 |  | Gas emergency crews. *Affects: leak response time.* *Default of the operations run setting `gasCrews`.* | Gas crews: how fast leaks are made safe on the operations day. |
| `electric_crews` | operations | `3` | 0–30 |  | Electric trouble crews. *Affects: outage duration, SAIDI.* *Default of the operations run setting `electricCrews`.* | Electric crews: how long outages last on the operations day. |
| `water_crews` | operations | `2` | 0–20 |  | Water distribution crews. *Default of the operations run setting `waterCrews`.* | Water crews: how long main breaks keep customers off. |
| `meter_techs` | operations | `2` | 0–20 |  | Meter technicians (exchanges, investigations). *Default of the operations run setting `meterTechs`.* | Meter technicians for exchanges and investigations on the operations day. The year's field capacity is Field orders per day. |
| `meter_vans` | operations | `2` | 0–20 |  | Drive-by AMR reading vans. *Affects: AMR read completion.* *Default of the operations run setting `meterVans`.* | AMR vans driving routes on the operations day; routes are shared among them. |
| `meter_walkers` | operations | `3` | 0–40 |  | Manual meter readers. *Affects: manual read completion, no-access.* *Default of the operations run setting `meterWalkers`.* | Walkers reading manual routes on the operations day. |
| `shift_start_hour` | operations | `7.0` | 0–23 | h | Day shift start. Non-emergency work (AMI collector repairs) waits for the day shift; emergencies are worked around the clock. *Affects: collector outage length.* *Default of the operations run setting `shiftStartHour`.* | When the day shift starts: non-emergency repairs wait for it. |
| `shift_end_hour` | operations | `15.5` | 1–24 | h | Day shift end. *Affects: collector outage length.* *Default of the operations run setting `shiftEndHour`.* | When the day shift ends: non-emergency repairs left after it wait for the next morning. |
| `gas_response_target_min` | operations | `60.0` | 10–240 | min | Target response to a gas odour call. *Default of the operations run setting `gasResponseTargetMinutes`.* | The response target gas crews are measured against on the operations day. |
| `speed_kmh_arterial` | operations | `50.0` | 10–100 | km/h | (advanced) Driving speed on arterials. | Driving speed on arterials: crew and van travel times. |
| `speed_kmh_collector` | operations | `40.0` | 10–80 | km/h | (advanced) Driving speed on collectors. | Driving speed on collector roads: crew and van travel times on the operations day. |
| `speed_kmh_local` | operations | `30.0` | 5–60 | km/h | (advanced) Driving speed on local streets. | Driving speed on local streets: crew and van travel times on the operations day. |

## Customers & billing

Accounts, reading routes, calendars and tariffs.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `mru_target_meters` | town | `450` | 50–3000 |  | Target premises per meter reading unit (route). *Affects: route count, read workload per day.* | Premises per reading route. Every town gets at least one route per billing portion (21), so it only bites above about 9,500 premises; then smaller routes mean more of them and a different split of AMI, AMR and walked routes. |
| `bill_cycles` | town | `21` | 1–31 |  | Billing portions per month (one per working day). | Billing portions per month: how reads and bills spread across working days, so daily queue load and when bills go out. |
| `currency` | display | `CAD` |  |  | Billing currency. | The currency label on bills. Amounts do not change. |
| `tax_rate` | town | `0.13` | 0–0.3 |  | Sales tax on utility bills (Ontario HST). | Sales tax on every bill: invoice totals, receivables and late fees scale with it. |
| `electric_fixed_monthly` | town | `36.5` | 0–500 | $ | Electric fixed delivery charge per month. | Fixed electric charge: every electric bill moves by this, whatever the usage. |
| `electric_blocks` | town | `[{'up_to': 600.0, 'price': 0.098}, {'up_to': None, 'price': 0.116}]` |  | $/kWh | Electric energy price blocks per kWh (summer threshold). | Energy price blocks: bill amounts, high-bill checks and the cost of each billing error. |
| `electric_variable_delivery` | town | `0.042` | 0–1 | $/kWh | Electric variable delivery per kWh. | Delivery charge per kWh: electric bills scale with usage. |
| `net_metering_credit` | town | `0.098` | 0–1 | $/kWh | Credit per exported kWh. *Affects: solar customer bills.* | Credit per exported kWh: solar homes' summer bills and the large-credit checks. |
| `gas_fixed_monthly` | town | `26.5` | 0–500 | $ | Gas customer charge per month. | Fixed gas charge: every gas bill moves by this, whatever the usage. |
| `gas_price_m3` | town | `0.36` | 0–5 | $/m3 | Gas delivery + supply per m³. | Gas price per m³: winter gas bills scale with it. |
| `water_fixed_monthly` | town | `18.0` | 0–500 | $ | Water fixed charge per month. | Fixed water charge: every water bill moves by this, whatever the usage. |
| `water_price_m3` | town | `2.15` | 0–20 | $/m3 | Water volumetric charge. | Water price per m³: water bills scale with it, and wastewater follows it. |
| `wastewater_ratio` | town | `1.05` | 0–3 |  | Wastewater charge as a multiple of the water volumetric charge. | Wastewater as a multiple of the water price: water bills scale with it. |
| `on_time_payer_share` | town | `0.82` | 0–1 |  | Share of accounts that pay on time. *Affects: dunning, collections, carrying cost.* | Accounts that pay on time. Fewer means more overdue balances, reminders, notices, late fees and collections work. |
| `late_payer_share` | town | `0.14` | 0–1 |  | Share that pay late. | Accounts that pay late; the rest are at-risk payers who may not pay at all. More late and at-risk payers drive dunning and disconnections. |
| `pre_authorized_share` | town | `0.45` | 0–1 |  | (advanced) Share on pre-authorized debit. | Accounts on pre-authorized debit: they pay on the due date, but a share bounce, which opens payment-rejected cases and NSF fees. |
| `due_days` | town | `20` | 5–60 |  | Days from invoice to due date. | Days from invoice to due date: when accounts go overdue, so receivable carry and the dunning calendar. |

## Meter-to-cash process

Work queues, automation, workforce, costs and carrying cost.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `rpa_coverage` | year | `0.35` | 0–1 |  | Share of exception types with an RPA/auto-resolve rule. *Affects: analyst workload, days to invoice, carrying cost.* | Share of exception types automation resolves. More coverage: fewer cases for analysts, cheaper and faster resolution, less carry; uncovered types still queue for people. |
| `analyst_queue_days_min` | year | `1` | 1–10 |  | Minimum queue wait before an analyst picks up an exception. | Shortest wait before an analyst first looks at a case: every human case takes at least this long, so carry and days to release rise. |
| `analyst_queue_days_max` | year | `3` | 1–20 |  | Maximum queue wait. | Longest first-look wait: the tail of slow cases, open-case counts and carry. |
| `carry_rate_per_day` | year | `1.25` | 0–20 | $ | Carrying cost per account per day before invoicing. | Cost of a day a bill is held back. Prices the carry; it does not change which cases happen. |
| `receivable_carry_ratio` | year | `0.4` | 0–1 |  | (advanced) Receivable carry as a share of the billing carry rate. | Carry on unpaid invoices as a share of the billing carry rate. Prices receivable carry only. |
| `analysts` | year | `2` | 0–200 |  | Billing analysts working the exception queues. *Affects: queue backlog, days to bill, carrying cost.* | People working the queues. Fewer: backlog grows, cases age, estimates and blocked bills wait longer and carry builds; more: queues clear faster. |
| `analyst_hours_per_day` | year | `6.0` | 0.5–10 | h | Productive queue hours per analyst per business day. | Queue hours per analyst per day: capacity, like the number of analysts. |
| `review_minutes_min` | year | `15.0` | 1–240 | min | (advanced) Shortest analyst review. | Shortest review: longer reviews cut how many cases a day each analyst clears. |
| `review_minutes_max` | year | `30.0` | 1–480 | min | (advanced) Longest analyst review. | Longest review: capacity and labor cost per case. |
| `supervisors` | year | `1` | 0–50 |  | Supervisors approving escalations. *Affects: escalation backlog.* | Supervisors approving escalations. Zero: escalated cases wait, high-impact bills stay held. |
| `supervisor_hours_per_day` | year | `2.0` | 0.25–10 | h | (advanced) Supervisor hours on escalations per business day. | Supervisor time for escalations: how fast the Escalations queue clears. |
| `supervisor_minutes` | year | `40.0` | 5–240 | min | (advanced) Supervisor review time per escalation. | Supervisor time per escalation: capacity and labor cost. |
| `supervisor_queue_days_min` | year | `1` | 1–20 | d | Minimum wait before a supervisor picks up an escalation (VEE's own escalations wait this long). *Affects: escalation backlog, days to bill.* | Shortest wait for a supervisor: escalated cases take at least this long. |
| `supervisor_queue_days_max` | year | `3` | 1–30 | d | Maximum wait before a supervisor picks up an escalation from an analyst or you. An escalation you take yourself (assign) waits for you. *Affects: escalation backlog, days to bill.* | Longest wait before a supervisor picks up an escalation: the tail of held high-impact bills. |
| `field_orders_per_day` | year | `6` | 0–500 |  | Meter investigations, re-reads and exchanges completed per business day. *Affects: field order backlog, estimates.* | Field orders worked per day (re-reads, checks, exchanges). Fewer: field backlog, longer estimate streaks, stuck and slow meters fixed later. |
| `field_days_min` | year | `1` | 0–20 | d | (advanced) Earliest a field order is worked after it is raised. | Earliest a field order is worked after it is raised. |
| `analyst_accuracy` | year | `0.95` | 0.5–1 |  | (advanced) Share of reviews where the analyst finds the true cause. *Affects: billing errors, wasted truck rolls.* | Reviews where the analyst finds the true cause. Lower: wrong dispositions, billing errors that surface later as rebills and complaints. |

## Meter & read anomalies

Injected faults with ground truth. Rates per 1,000 meters per year.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `enabled` | year | `True` |  |  | Inject anomalies into observed reads (truth is always kept separately). | Off: reads are clean apart from missed reads, so VEE flags only what usage swings and outages explain. Truth is always kept for scoring. |
| `leak` | year | `8.0` | 0–200 |  | Continuous post-meter water leaks. | Water leaks after the meter: high water reads, high-bill blocks and complaints. |
| `stuck_meter` | year | `5.0` | 0–200 |  | Registers that stop advancing. | Registers that stop: zero-use reads at occupied homes, field orders and exchanges, under-billing until fixed. |
| `slow_meter` | year | `4.0` | 0–200 |  | Meters under-registering 10–40%. | Meters under-registering 10 to 40 percent: lost revenue VEE catches only through the trend test. |
| `transposed_digits` | year | `6.0` | 0–200 |  | Reads with two digits swapped. | Two digits swapped in a read: wild spikes or drops VEE should reject. |
| `misread` | year | `6.0` | 0–200 |  | Reads off by one in a high digit. | A high digit off by one: large spikes or negative use. |
| `consecutive_estimates` | year | `15.0` | 0–200 |  | Runs of 2–4 estimated periods (higher on manual routes). | Runs of estimated periods (more on walked routes): estimate streaks that trigger field reads and true-ups. |
| `missing_read` | year | `5.0` | 0–200 |  | Periods with no read document. | Periods with no read document: estimates and missing-read cases. |
| `exchange_registration_failure` | year | `2.0` | 0–100 |  | Meter exchanges whose new serial fails registration. | Meter exchanges whose new meter fails registration: zero use, blocked bills and analyst or field work. |
| `vacant_consuming` | year | `3.0` | 0–100 |  | Vacant premises that still consume. | Vacant homes that still use energy: unbilled consumption cases. |
| `tamper` | year | `1.0` | 0–50 |  | Bypass/tamper (50–90% under-registration). | Bypasses that under-register 50 to 90 percent: lost revenue and investigations. |
| `amr_factor` | year | `1.0` | 0–20 |  | (advanced) Multiplier on every anomaly rate for AMR (drive-by) meters: an ageing ERT fleet misreads and under-registers more. | Multiplies every anomaly rate on AMR meters: an ageing drive-by fleet misreads and under-registers more. |
| `manual_factor` | year | `1.0` | 0–20 |  | (advanced) Multiplier on every anomaly rate for manually read meters. | Multiplies every anomaly rate on walked meters: more misreads and faults on manual routes. |

## Scenario

Demonstration scenario on the live clock.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `name` | operations | `normal` |  |  | Live demonstration scenario. | The map's demonstration (normal, solar noon, leak, substation outage) on the live day. The year is unchanged. |
| `date` | display | `2026-07-15` |  |  | Demonstration date (local). | The day the map shows and the Studio opens on. The year's results are the same; only the default view date moves. |
| `hour` | display | `8.0` | 0– | h | Demonstration hour (local, decimal). | The hour the map's live clock starts at. The year is unchanged. |
| `target_premise` | operations | `None` |  |  | Premise targeted by the leak scenario (default: first premise). | The premise the map's leak demonstration targets. |
| `leak_m3h` | operations | `0.65` | 0–50 | m3/h | Leak rate added to the target premise's water demand. | Leak size in the map's leak demonstration: flows and pressures that day. |

## Meter reading

How periodic billing reads succeed or fail, by meter technology.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `ami_missed_read` | year | `0.012` | 0–0.5 |  | AMI billing reads still missing after the head-end retry window. *Affects: comm-fail exceptions, estimates.* | AMI reads still missing after retries: estimates, missing-read cases and estimate streaks. |
| `amr_missed_read` | year | `0.03` | 0–0.5 |  | Drive-by reads missed (no signal, street skipped). | Drive-by reads missed: estimates and missing-read cases on AMR routes. |
| `manual_no_access` | year | `0.06` | 0–0.8 |  | Manual reads with no access (locked gate, dog, meter inside). *Affects: no-access exceptions, consecutive estimates.* | Walked reads with no access: estimates, streaks and field reads. |
| `no_access_repeat` | year | `0.4` | 0–1 |  | (advanced) Chance a missed manual read is missed again the next month. | Chance a no-access meter is missed again next month: longer estimate streaks and more field reads. |
| `read_cost_ami` | year | `0.1` | 0–20 | $ | (advanced) Cost of one AMI read. | Cost of one AMI read. Prices reading; no read changes. |
| `read_cost_amr` | year | `0.35` | 0–20 | $ | (advanced) Cost of one drive-by read. | Cost of one drive-by read. Prices reading in the cost totals; no read changes. |
| `read_cost_manual` | year | `1.2` | 0–50 | $ | (advanced) Cost of one walked read. | Cost of one walked read. Prices reading in the cost totals; no read changes. |

## VEE rules

Validation, estimation and editing: the five-test battery, confidence and disposition (VEE v5 shape).

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `high_ratio` | year | `2.0` | 1.1–10 |  | Flag consumption above this multiple of expected (tolerance high). *Affects: flagged reads, analyst workload.* | Flag use above this multiple of expected. Lower: more high reads flagged (more cases, more real spikes caught, more false alarms). |
| `low_ratio` | year | `0.35` | 0–0.95 |  | Flag consumption below this share of expected (tolerance low). | Flag use below this share of expected. Higher: more low reads flagged, catching slow and stuck meters sooner at the cost of more cases. |
| `zero_at_occupied` | year | `True` |  |  | Flag zero consumption at an occupied premise. | Flag zero use at an occupied home: catches stuck meters and failed exchanges. |
| `max_consecutive_estimates` | year | `2` | 1–12 |  | Estimates in a row before a field read is ordered. *Affects: field orders.* | Estimates in a row before a field read is ordered: lower means more field orders, shorter streaks. |
| `min_period_days` | year | `25` | 1–40 | d | (advanced) Shortest plausible read period. | Shortest plausible read period: shorter periods fail the timing test. |
| `max_period_days` | year | `38` | 20–120 | d | (advanced) Longest plausible read period. | Longest plausible read period: longer periods fail the timing test and go to review. |
| `accept_confidence` | year | `0.75` | 0–1 |  | Auto-accept at or above this confidence. *Affects: auto-accept rate, billing errors.* | Auto-accept at or above this confidence. Higher: fewer reads auto-accepted, more for review. |
| `reject_confidence` | year | `0.35` | 0–1 |  | Reject below this confidence. | Reject below this confidence (the read is replaced by an estimate). |
| `escalate_impact` | year | `150.0` | 0–10000 | $ | Escalate a doubtful read when its bill impact exceeds this. *Affects: supervisor workload.* | Doubtful reads whose bill impact exceeds this go to a supervisor: lower means more escalations and supervisor load. |
| `trend_ratio` | year | `0.8` | 0.3–1.0 |  | Persistent low use: flag reads below this share of expected … *Affects: slow and tampered meters found.* | Persistent low use below this share of expected is flagged: how slow meters and tamper are caught. |
| `trend_periods` | year | `3` | 2–12 |  | … for this many periods in a row. | Periods of low use before the trend flag: fewer means earlier detection, more cases. |
| `oms_events` | year | `True` |  |  | Use outage events (OMS, AMI last gasps) from operations: hours without service lower the expected use. *Affects: low-usage flags after outages.* | Use outage events: hours without service lower the expected use, so outage-explained low reads are accepted instead of flagged. Only matters when a run carries interruptions from an operations day. |
| `estimation` | year | `prior_year` |  |  | Estimation method for missing or rejected reads. | How missing or rejected reads are estimated: prior year or average daily use. Changes estimated amounts and later true-ups. |
| `history_noise` | year | `0.1` | 0–0.5 |  | (advanced) Spread of prior-year history around this year's normal usage. | How far last year's history strays from this year's normal use: more noise, more reads look odd against history. |

## Billing & collections

Bill checks, tariff versions, invoicing, payments and dunning.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `rate_change_date` | year | `2026-11-01` |  |  | Date a new tariff version takes effect (volumetric prices). | When the new tariff version starts: bills after it prorate across the change. |
| `rate_change_pct` | year | `3.5` | -50–100 | % | Volumetric price change in the new tariff version. *Affects: bills after the change, proration.* | Price change in the new tariff version: bill amounts after the date. |
| `high_bill_ratio` | year | `2.5` | 1.1–20 |  | Block a bill above this multiple of its expected amount (prior-year use at current prices). *Affects: billing blocks, analyst workload.* | Block bills above this multiple of expected: lower means more billing outsorts for analysts or RPA. |
| `high_bill_min` | year | `150.0` | 0–5000 | $ | …and at least this much above the expected amount. | And at least this much above expected: filters small bills out of high-bill checks. |
| `first_bill_limit` | year | `600.0` | 0–10000 | $ | (advanced) Block a bill with no expected use (vacant, new) above this total. | Block first bills above this total when there is no expected use to compare with (vacant or new premises). Rare in small towns. |
| `credit_review` | year | `75.0` | 0–5000 | $ | (advanced) Block a bill that is a credit larger than this. | Block credit bills larger than this for review: lower means more credit outsorts. |
| `outsort_auto_release_max` | year | `500.0` | 0–100000 | $ | RPA may release a high-bill or large-credit outsort only up to this bill amount (either sign); a larger one waits for an analyst. *Affects: analyst workload, billing errors.* | RPA may release outsorts up to this amount; larger ones wait for an analyst. |
| `billing_queue_worked_by` | year | `analysts` |  |  | Who works the BILLING queue (high bills, large credits, true-ups, rate-class errors): the simulated analysts and RPA, or only you. With 'you', no analyst or RPA touches a billing block, so every outsort waits in the Studio for your release, rebill or escalation. *Affects: billing blocks, days to invoice, billing carry.* | Who works the Billing queue: analysts and RPA, or only you (cases wait for your decisions). |
| `trueup_max_ratio` | year | `3.0` | 1–50 | × | (advanced) Block a bill whose estimate true-up (a negative period quantity) is larger than this multiple of the period's expected use; an analyst decides it. *Affects: billing blocks, billing errors.* | Block estimate true-ups (a negative period after an over-estimate) larger than this multiple of expected use. Rare unless estimates run high. |
| `data_error_rate` | year | `3.0` | 0–200 |  | Installations with a wrong rate class in billing master data (per 1,000 per year). *Affects: rate-class billing blocks.* | Wrong rate classes in billing master data: mis-billed accounts, rate-class blocks and rebills. |
| `print_lag_days` | year | `1` | 0–10 | d | (advanced) Days from invoice creation to issue. | Days from invoice to issue: due dates and receivable carry move with it. |
| `pad_reject_rate` | year | `0.015` | 0–0.5 |  | Pre-authorized debits returned for insufficient funds. *Affects: payment rejections, collections.* | Pre-authorized debits that bounce: payment-rejected cases, NSF fees and overdue balances. |
| `nsf_fee` | year | `20.0` | 0–100 | $ | (advanced) Fee for a returned payment. | Fee added to an account when a payment bounces: higher balances and more overdue amounts. |
| `late_fee_pct` | year | `1.5` | 0–5 | % | Late payment charge on overdue amounts (per notice). | Late charge on overdue amounts at each notice: higher balances and receivables. |
| `reminder_days` | year | `7` | 1–60 | d | Days after the due date for a reminder. | Days after the due date for a reminder letter: when collections work starts. |
| `notice_days` | year | `21` | 1–90 | d | Days after the due date for an overdue notice and late fee. | Days after the due date for an overdue notice and late fee: when fees start to build. |
| `disconnect_days` | year | `45` | 5–180 | d | Days after the due date for a disconnection notice. *Affects: disconnection notices.* | Days after the due date for a disconnection notice: later notices, fewer disconnections in the year. |
| `winter_moratorium` | year | `True` |  |  | No disconnection notices for electricity and water from Nov 15 to Apr 30 (Ontario); a notice held for the winter is issued on May 1 if the bill is still unpaid. | No electric or water disconnection notices in winter; held notices go out after the end date. Shifts collections from winter to spring. |
| `moratorium_start` | year | `11-15` |  |  | (advanced) First day of the winter moratorium (MM-DD). | First day of the winter moratorium: an earlier start holds more autumn notices. |
| `moratorium_end` | year | `04-30` |  |  | (advanced) Last day of the winter moratorium (MM-DD); held notices go out the day after. | Last day of the winter moratorium; held notices go out the next day. |
| `disconnect_notice_days` | year | `10` | 1–60 | d | Days from a disconnection notice to the earliest disconnection. A disconnection also needs a person's approval (the Collections worklist). *Affects: disconnections.* | Days from a disconnection notice to the earliest disconnection. Acts only on disconnections you approve: the engine never disconnects on its own. |
| `disconnect_rule_share` | year | `0.0` | 0–1 |  | Share of disconnection notices a collections rule approves when they are issued (the disconnection follows at the earliest day); the rest wait for a person's approval. 0: every disconnection needs you. *Affects: disconnections, field disconnects and reconnects.* | Disconnection notices a collections rule approves as they are issued: the crews' disconnects and reconnects follow, disconnected meters are not read or billed until reconnected, and disconnected contacts come in. 0 (the default): every disconnection waits for you. |
| `disconnect_payment_rate` | year | `0.6` | 0–1 |  | (advanced) Disconnected customers who pay within a week of the disconnection (and are reconnected the next business day); the rest stay off until they pay. *Affects: collections, reconnections.* | Disconnected customers who pay within a week and are reconnected the next business day. Acts only on disconnections you approve in the Collections worklist. |
| `arrangement_break_rate` | year | `0.3` | 0–1 |  | (advanced) At-risk payers who break a payment arrangement after a few instalments (dunning resumes); other payers pay every instalment. *Affects: collections.* | At-risk payers who break a payment arrangement after a few instalments; dunning resumes. Acts only on arrangements you set up in the Collections worklist. |
| `low_income_referral_rate` | year | `0.15` | 0–1 |  | Disconnection notices and winter moratorium holds after which the call centre refers the customer to a low-income programme (once a year per account). *Affects: Low Income Process cases, disconnections.* | Notices and holds after which the customer is referred to a low-income programme; dunning waits. |
| `low_income_review_days` | year | `10` | 1–60 | d | (advanced) Business days the low-income agency takes to decide a referral; dunning waits meanwhile. | Business days the agency takes to decide a referral; dunning waits meanwhile. |
| `low_income_approval_rate` | year | `0.7` | 0–1 |  | Referrals the agency approves with a grant. *Affects: collections, receivable.* | Referrals approved with a grant against arrears: less owed, fewer disconnections. |
| `low_income_grant_max` | year | `500.0` | 0–5000 | $ | (advanced) Largest low-income grant credited to an account's arrears. | Largest low-income grant credited to an account's arrears: less owed, fewer notices. |
| `budget_billing_offer_rate` | year | `0.08` | 0–1 |  | Overdue notices after which the call centre enrols the customer in budget billing (once a year per account); the plan levels later invoices. *Affects: Budget Bill Cases, collections.* | Overdue notices after which the customer moves to budget billing: levelled later invoices. |

## Contact centre

Why customers phone, write or use the IVR, and the agents, hours and self-service that answer them. Contacts follow the year: bills, errors, rebills, dunning, payments, move-ins and move-outs, missed reads and the year's outages and gas leaks.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `agents` | year | `1` | 0–500 |  | Agents on the phones on a business day (a small utility often has one, shared with billing). *Affects: wait, abandonment.* | Agents answering during opening hours. Fewer: longer waits, more hang-ups, call backs and repeat calls; more: shorter waits but more idle time and staffing cost. |
| `open_hour` | year | `8.0` | 0–23 | h | Lines open (local time, business days). | When the lines open on business days. Later opening squeezes the same contacts into fewer hours: longer waits at peaks. |
| `close_hour` | year | `17.0` | 1–24 | h | Lines close (local time). | When the lines close. Earlier closing squeezes contacts into fewer hours; callers who find the lines closed try again the next day. |
| `patience_s` | year | `240.0` | 10–3600 | s | Average time a caller waits before hanging up. | How long callers hold before hanging up. Less patience: more hang-ups and retries at the same waits. |
| `retry_share` | year | `0.6` | 0–1 |  | Callers who hung up or found the lines closed and try again. | Callers who hung up or found the lines closed and try again: retries add load at busy times; the rest give up unanswered. |
| `repeat_share` | year | `0.5` | 0–1 |  | Callers whose problem was not resolved who contact again within days. | Customers whose problem was not resolved who contact again: repeat contacts, and complaints after a second failure. |
| `callback` | year | `True` |  |  | Offer a call back instead of holding when the wait is long. | Offer a call back instead of holding when the wait is long: fewer hang-ups, the same agent time spread later in the day. |
| `callback_after_s` | year | `300.0` | 0–3600 | s | (advanced) Offer the call back when the expected wait exceeds this. | Expected wait at which the call back is offered: lower offers it more often, turning hang-ups into later calls. |
| `callback_take_share` | year | `0.5` | 0–1 |  | (advanced) Callers offered a call back who take it. | Callers who accept the call back offer. |
| `service_target_s` | year | `30.0` | 5–600 | s | Answer target for the service level (answered within it). | The answer target the service level counts against. It changes the reported service level, not who waits. |
| `volume_factor` | year | `1.0` | 0–20 |  | Multiplies every reason's contact rates. | Multiplies every reason's rates: a quick way to test a busier or quieter year. |
| `handle_factor` | year | `1.0` | 0.1–10 |  | Multiplies every reason's handling time. | Multiplies every handling time: slower handling fills the agents' day, so waits and hang-ups rise. |
| `self_serve_factor` | year | `1.0` | 0–3 |  | Multiplies every reason's self-service share (0: IVR and web down). | Multiplies the share the IVR and website handle; zero sends every contact to an agent. |
| `agent_cost_per_hour` | year | `38.0` | 0–500 | $ | (advanced) Loaded cost of an agent hour on the phones. | Prices the agents' open hours in the contact cost. No contact changes. |
| `self_serve_cost` | year | `0.4` | 0–50 | $ | (advanced) Cost of a contact the IVR or website handles. | Prices each self-served contact. No contact changes. |
| `abandon_cx_cost` | year | `6.0` | 0–200 | $ | (advanced) Customer-experience cost of a caller who hangs up. | Prices the customer-experience cost of each hang-up. No contact changes. |
| `emergency_answer_s` | year | `15.0` | 1–600 | s | (advanced) Answer time on the emergency line (gas odour, outages after hours). | Answer time on the emergency line (gas odours, after-hours outages). |
| `high_bill` | year | `per_event=0.25, per_1000=2.0, self_serve=0.1, handle_min=7.5, resolved=0.85` |  |  | High bill: an invoice at least 1.5 times what the account usually pays (and $40 more). | High-bill contacts: invoices at 1.5 times the expected amount. More estimates, leaks, cold months and rate changes raise them. |
| `bill_question` | year | `per_event=0.008, per_1000=1.5, self_serve=0.2, handle_min=6.0, resolved=0.9` |  |  | Questions about a bill: any invoice, more for estimated bills, first bills and bills after a rate change. | Questions about bills: more with estimated bills, first bills after a move-in and bills just after a rate change. |
| `bill_wrong` | year | `per_event=0.35, per_1000=0.3, self_serve=0.0, handle_min=11.0, resolved=0.6` |  |  | Bill wrong: a bill that overcharges the customer (customers rarely call about undercharges). | Disputes over bills that overcharge against the truth: VEE misses, rate-class errors and misreads drive them. |
| `back_bill` | year | `per_event=0.45, per_1000=0.0, self_serve=0.0, handle_min=12.0, resolved=0.7` |  |  | Back bill: a rebill, or the first actual bill after estimates, that catches up on under-billed use. | Contacts about catch-up bills: rebills, and the first actual bill after a run of estimates (no-access and missed reads drive them). |
| `balance` | year | `per_event=0.03, per_1000=4.0, self_serve=0.75, handle_min=3.0, resolved=0.98` |  |  | What's my balance: around due dates; mostly the IVR. | Balance enquiries around due dates; the IVR answers most. |
| `payment_arrangement` | year | `per_event=0.12, per_1000=0.5, self_serve=0.1, handle_min=9.0, resolved=0.8` |  |  | Can't pay: after overdue notices, more after disconnection notices. | Can't-pay contacts after reminders, overdue notices and disconnection notices: collections settings and payer mix drive them. |
| `payment_problem` | year | `per_event=0.4, per_1000=0.4, self_serve=0.3, handle_min=6.0, resolved=0.85` |  |  | Payment problem: a pre-authorized debit returned. | Contacts after a returned pre-authorized debit (the PAD reject rate drives them). |
| `password` | year | `per_event=0.01, per_1000=3.0, self_serve=0.6, handle_min=4.0, resolved=0.95` |  |  | Forgot password or online account help: when bills arrive; most reset online. | Online account help when bills arrive; most reset online. |
| `move_in` | year | `per_event=0.85, per_1000=0.0, self_serve=0.3, handle_min=10.0, resolved=0.95` |  |  | Start service: a new account at a premise, days before the move-in. | Start-service contacts before each move-in: rentals and turnover drive them. |
| `move_out` | year | `per_event=0.85, per_1000=0.0, self_serve=0.3, handle_min=8.0, resolved=0.95` |  |  | Stop service: days before an account closes. | Stop-service contacts before each move-out. |
| `new_connection` | year | `per_event=0.0, per_1000=0.4, self_serve=0.1, handle_min=14.0, resolved=0.7` |  |  | New connection: builders and owners asking for a new service. | New-connection requests (background only). |
| `outage` | year | `per_event=0.18, per_1000=0.2, self_serve=0.65, handle_min=3.5, resolved=0.9` |  |  | Outage report: customers who lose power or water (twice as many when it lasts over two hours); the IVR's outage message answers most. | Outage reports from customers who lose power or water in the year's incidents; the IVR's outage message answers most, after hours the emergency line. |
| `gas_odour` | year | `per_event=0.06, per_1000=0.15, self_serve=0.0, handle_min=4.0, resolved=1.0` |  |  | I smell gas: neighbours of a gas leak (the household with a service leak calls 9 times in 10); emergency line. | Gas odour calls from neighbours of the year's gas leaks, on the emergency line. |
| `meter_access` | year | `per_event=0.08, per_1000=0.3, self_serve=0.2, handle_min=6.0, resolved=0.85` |  |  | Meter access: after a no-access read card, and to book field visits. | Contacts after no-access read cards and to book field visits: walked routes and no-access rates drive them. |
| `disconnection` | year | `per_event=0.8, per_1000=0.0, self_serve=0.0, handle_min=9.0, resolved=0.85` |  |  | Disconnected: customers asking to be reconnected after a disconnection you approved. | Reconnection requests after disconnections you approve. |
| `complaint` | year | `per_event=0.5, per_1000=0.2, self_serve=0.0, handle_min=14.0, resolved=0.6` |  |  | Complaint: after a second unresolved contact about the same thing, or after giving up on hold twice. | Complaints after a second unresolved contact or giving up on hold twice: long waits and low first-contact resolution drive them. |

## Outages & leaks over the year

The operations day's background incidents drawn for every day of the year (same storms and leaks the map shows on a date): who loses power or water, for how long, and where gas is smelled. The contact centre hears about them.

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `enabled` | year | `True` |  |  | Draw outages and leaks across the year. | Draw the operations day's incidents for every day of the year. Off: outage and gas odour contacts are background only. |
| `storm_factor` | year | `1.0` | 0–30 |  | Multiplies the chance that a day is a storm day. | Multiplies the chance of a storm day: more overhead line faults, outages and outage reports, mostly May to September. |
| `incident_factor` | year | `1.0` | 0–30 |  | Multiplies every incident rate (leaks, breaks, failures, faults). | Multiplies every incident rate: more outages, main breaks and gas leaks, and the contacts they bring. |
| `restore_factor` | year | `1.0` | 0.1–20 |  | Multiplies the time to restore service. | Multiplies the time to restore service: longer outages bring twice the outage reports past two hours. |

## Field work

The work the field crews do over the year and the crews that do it: customer emergencies, service orders (disconnects, reconnects, move-ins and move-outs), meter maintenance (seal exchanges, batteries, removals), preventative maintenance on the networks and capital construction (new sets, upgrades, main renewal). Work follows the year: collections, moves, VEE field visits, the contact centre's calls, the year's outages and leaks, the meters' install years and the town's assets. What the crews do changes the year: a disconnected or removed meter is not read or billed, an exchange registers a new meter, and maintenance left overdue fails (dead batteries, drifting meters, outages, gas leaks).

| Field | Reaches | Default | Range | Unit | Description | How it changes the results |
|---|---|---|---|---|---|---|
| `shift_start_hour` | year | `7.0` | 0–20 | h | Crews start their day (local time, business days). | When the business-day crews start. It moves when work is done in the day and which emergencies fall after hours (call-out and overtime). |
| `shift_hours` | year | `8.0` | 1–16 | h | Hours in a crew's working day. | Hours in a crew's day: every business-day crew's capacity. Shorter days build backlog, overdue work and overtime. |
| `travel_minutes` | year | `20.0` | 0–240 | min | Driving to the job and back, added to every visit. | Driving to each job and back: more travel fills the crews' day with fewer jobs, and slows emergency response. |
| `callout_minutes` | year | `30.0` | 0–240 | min | After hours, the time an on-call responder takes to get on the road. | Time for an on-call responder to get on the road after hours: emergency response times at night and on weekends. |
| `overtime_max_hours` | year | `3.0` | 0–12 | h | Most hours a crew works past its shift to finish same-day and overdue customer work (priority 1 and 2). | Overtime per crew for customer work due today or overdue: more keeps disconnects, reconnects and move reads on time, at overtime cost. |
| `remote_switch_share` | year | `0.85` | 0–1 |  | Share of AMI electric meters with a remote connect switch: their disconnects, reconnects and move reads need no truck. | AMI electric meters with a remote switch: their disconnects and reconnects need no truck. |
| `seal_years_electric` | year | `10` | 1–30 | yr | Electric meter seal period: a lot whose seal expires this year is sampled. | Electric seal period: picks which install year's lots are sampled this year (the meters' install cohorts set the volume). |
| `seal_years_gas` | year | `10` | 1–30 | yr | Gas meter seal period. | Gas seal period: picks which install year's lots are sampled this year. |
| `seal_sample_size` | year | `32` | 1–500 |  | Meters pulled and tested from each lot whose seal expires. | Meters pulled from each expiring lot: more sample exchanges. |
| `seal_lot_pass_rate` | year | `0.8` | 0–1 |  | Share of lots that pass compliance sampling and are resealed; a failed lot is exchanged meter by meter before its seal expires. | Lots that pass sampling. A failed lot has every meter exchanged by 31 December: the biggest swing in meter work. |
| `battery_years` | year | `15` | 1–40 | yr | Radio module battery life on gas and water meters, AMI and AMR (they have no mains power). | Module battery life: picks which install year's gas and water modules get new batteries this year. |
| `water_meter_life_years` | year | `15` | 1–60 | yr | Water meters this old or older are due for replacement. | Water meters this old or older are due for replacement: a shorter life puts more cohorts in the backlog. |
| `dead_battery_miss` | year | `0.9` | 0–1 |  | Share of reads a radio module misses once its battery has died (past its life and not replaced): estimates follow. | Reads a module misses once its battery died (not replaced by its anniversary): estimates, estimation cases and contacts follow. |
| `failed_lot_drift` | year | `0.04` | 0–0.5 |  | Under-registration of a failed seal lot's meters, from the failed test until each is exchanged. | How much a failed seal lot's meters under-register until exchanged: less billed against the truth while the exchanges wait. |
| `old_water_meter_drift` | year | `0.03` | 0–0.5 |  | Under-registration of water meters at or past their service life, until replaced (read at the start of the year). | How much water meters past their life under-register until replaced: the revenue a replacement programme recovers. |
| `deferred_pole_failures` | year | `2.0` | 0–100 |  | Chance a year that a pole found needing replacement fails once its replacement is overdue (ten times as likely on a storm day): an outage. | How likely an overdue pole replacement fails: outages, outage reports and repairs on the line crews. |
| `deferred_tree_faults` | year | `0.02` | 0–1 |  | Chance on a storm day that an overhead span overdue for trimming faults: an outage. | How likely a span overdue for trimming faults on a storm day: outages and outage reports. |
| `deferred_leak_escalation` | year | `1.0` | 0–100 |  | Chance a year that a leak found by survey becomes a public gas leak (odour calls, an emergency) once its repair is overdue. | How likely a surveyed leak overdue for repair becomes a public gas leak: odour calls and emergency response. |
| `construction_start_month` | year | `4` | 1–12 |  | First month of the construction season (digging is frost-free). | First month of the construction season: new services, upgrades, AMI conversion and main renewal wait for it. |
| `construction_end_month` | year | `11` | 1–12 |  | Last month of the construction season. | Last month of the construction season: work not built by then waits for next year. |
| `crew_emergency` | year | `per_1000_premises=0.4, cost_per_hour=110.0, overtime_factor=1.5` |  |  | Gas odour and no-supply calls, any hour of any day. | On-call responders: fewer stretch emergency response when emergencies overlap; the cost prices their time. |
| `crew_meter` | year | `per_1000_premises=0.3, cost_per_hour=75.0, overtime_factor=1.5` |  |  | Disconnects, reconnects, move visits, exchanges, batteries, removals, investigations, meter sets. | Meter technicians: service orders, VEE visits, exchanges, batteries and meter sets share them. Fewer: backlog, late disconnects and move reads, overtime. |
| `crew_electric` | year | `per_1000_premises=0.15, cost_per_hour=165.0, overtime_factor=1.5` |  |  | Pole work, tree trimming, outage repairs, service upgrades. | Electric line crews: outage repairs take their time first, then pole and tree programmes and service upgrades. |
| `crew_water` | year | `per_1000_premises=0.15, cost_per_hour=140.0, overtime_factor=1.5` |  |  | Valves, hydrants, main break repairs. | Water crews: main break repairs, valve and hydrant programmes and their repairs. |
| `crew_gas` | year | `per_1000_premises=0.08, cost_per_hour=150.0, overtime_factor=1.5` |  |  | Leak surveys, regulator stations, leak repairs. | Gas crews: leak repairs, leak surveys and regulator inspections. |
| `crew_construction` | year | `per_1000_premises=0.08, cost_per_hour=230.0, overtime_factor=1.5` |  |  | Contractors: new services, main renewal. | Construction crews: new services and main renewal through the season. |
| `gas_odour` | year | `rate=1.0, minutes=45.0, target_days=0.041666666666666664, materials=0.0` |  |  | Gas odour investigation: share of gas odour reports (a leak's first report, every background report) a responder attends. | Gas odour reports a responder attends; follows the year's gas leaks and the contact centre's gas odour calls. |
| `no_supply` | year | `rate=0.6, minutes=60.0, target_days=0.16666666666666666, materials=40.0` |  |  | No supply at one premise (a service fault, a blown fuse, a curb stop): share of single-premise outage reports that need a truck. | Single-premise no-supply reports that need a truck; follows the contact centre's outage reports. |
| `outage_repair` | year | `rate=1.0, minutes=120.0, target_days=1.0, materials=900.0` |  |  | Repair of the year's outages and leaks (the incident model times it): share recorded against the utility's crew. | Outage and leak repairs on the utilities' crews, timed by the incident model; follows the outages settings. |
| `disconnect` | year | `rate=1.0, minutes=30.0, target_days=0.0, materials=0.0` |  |  | Disconnect for non-payment: share of collections disconnections worked (AMI electric with a switch is done remotely). | Disconnections the crews carry out (approved in Collections). A disconnected meter is not read and not billed until it is reconnected. |
| `reconnect` | year | `rate=1.0, minutes=30.0, target_days=1.0, materials=0.0` |  |  | Reconnect after payment: share of reconnections worked, due the next business day. | Reconnections the crews do after payment; the rest come back without a visit. |
| `move_out` | year | `rate=1.0, minutes=20.0, target_days=1.0, materials=0.0` |  |  | Move-out final read or lock-off: share of account closings at a premise with a meter that cannot be read remotely. | Move-out visits: account closings at premises without AMI. |
| `move_in` | year | `rate=0.5, minutes=25.0, target_days=1.0, materials=0.0` |  |  | Move-in turn-on or first read: share of account openings at a premise with a meter that cannot be read remotely. | Move-in visits: account openings at premises without AMI (not the day after a move-out there). |
| `meter_investigation` | year | `rate=1.0, minutes=40.0, target_days=10.0, materials=0.0` |  |  | VEE field visit (the run decides when): share recorded against the meter technicians. | VEE field visits on the meter technicians' time: follows the process settings (field orders a day, field days) and the anomalies. |
| `corrective_exchange` | year | `rate=1.0, minutes=60.0, target_days=10.0, materials=140.0` |  |  | Faulty meter exchanged on a field visit (the run decides when): share recorded. | Faulty meters exchanged on field visits: follows the anomalies (stuck, slow, tamper) and the field visits that find them. |
| `seal_exchange` | year | `rate=1.0, minutes=45.0, target_days=20.0, materials=140.0` |  |  | Seal-expiry exchange: share of the meters due (the sample of every expiring lot, every meter of a failed lot) exchanged. A failed lot's meters are due by 31 December. | Seal-expiry exchanges: the samples and failed lots due this year, each a new meter on the installation (reads and bills on the new register). |
| `ami_battery` | year | `rate=1.0, minutes=20.0, target_days=20.0, materials=35.0` |  |  | Module battery replacement on gas and water meters: share of batteries reaching their life this year. | Module battery replacements due this year. |
| `water_meter_replacement` | year | `rate=0.5, minutes=45.0, target_days=20.0, materials=160.0` |  |  | Water meter replacement by age: share of over-age water meters replaced this year. | Over-age water meters replaced this year (new meters, no more drift); the rest keep under-registering. |
| `removal` | year | `rate=2.0, minutes=30.0, target_days=10.0, materials=0.0` |  |  | Meter removal (vacant premise, service abandoned): removals per 1,000 premises a year. | Meter removals at vacant premises: the removed meters are not read or billed again. |
| `ami_conversion` | year | `rate=0.0, minutes=35.0, target_days=20.0, materials=180.0` |  |  | AMI conversion: share of AMR and manually read meters converted to AMI this year (capital, priority 4). | AMR and manually read meters converted to AMI, route by route in the season: fewer missed reads and no-access visits after. Off by default. |
| `pole_inspection` | year | `rate=0.1, minutes=15.0, target_days=20.0, materials=0.0` |  |  | Pole inspection: share of poles inspected a year (0.1 is a ten-year cycle). | Poles inspected a year; inspections find poles to replace. |
| `pole_replacement` | year | `rate=0.03, minutes=480.0, target_days=40.0, materials=2500.0` |  |  | Pole replacement: share of inspected poles found needing replacement. | Inspected poles found needing replacement: long, costly line crew jobs. |
| `tree_trimming` | year | `rate=0.25, minutes=25.0, target_days=20.0, materials=0.0` |  |  | Tree trimming: share of overhead spans trimmed a year (minutes per span). | Overhead spans trimmed a year. |
| `valve_exercise` | year | `rate=0.25, minutes=30.0, target_days=20.0, materials=0.0` |  |  | Valve exercising: share of water and gas valves a year. | Water and gas valves exercised a year; exercising finds valves to repair. |
| `valve_repair` | year | `rate=0.05, minutes=300.0, target_days=20.0, materials=1800.0` |  |  | Valve repair: share of exercised valves found broken or stuck. | Exercised valves found broken: repairs on the utility's crew. |
| `hydrant_flush` | year | `rate=1.0, minutes=40.0, target_days=15.0, materials=0.0` |  |  | Hydrant flushing and inspection: share of hydrants a year (May to October). | Hydrants flushed May to October; flushing finds hydrants to repair. |
| `hydrant_repair` | year | `rate=0.04, minutes=240.0, target_days=10.0, materials=900.0` |  |  | Hydrant repair: share of flushed hydrants found defective. | Flushed hydrants found defective. |
| `leak_survey` | year | `rate=0.33, minutes=90.0, target_days=20.0, materials=0.0` |  |  | Gas leak survey: share of gas main length walked a year (minutes per km). | Gas main walked a year; surveys find leaks to repair. |
| `gas_leak_repair` | year | `rate=0.15, minutes=360.0, target_days=15.0, materials=800.0` |  |  | Gas leak repair (grade 2): leaks found per surveyed km. | Leaks found per surveyed kilometre: grade 2 repairs on the gas crews. |
| `regulator_inspection` | year | `rate=1.0, minutes=180.0, target_days=10.0, materials=0.0` |  |  | Regulator station inspection: share of stations (city gate, district regulators) a year. | Regulator stations inspected a year. |
| `new_set` | year | `rate=0.8, minutes=480.0, target_days=30.0, materials=1500.0` |  |  | New service: share of new-connection requests (the contact centre's new connection contacts) that go ahead; built in the construction season. | New-connection requests that go ahead: new services built in the season, then meter sets. Follows the contact centre's new connection contacts. |
| `meter_set` | year | `rate=1.0, minutes=45.0, target_days=5.0, materials=250.0` |  |  | Meter set on a finished new service: share set by a meter technician (the rest come with the contractor). | Meter sets on finished new services by the meter technicians. |
| `service_upgrade` | year | `rate=0.04, minutes=240.0, target_days=20.0, materials=900.0` |  |  | Electric service upgrade: share of homes with an EV or electric heat upgrading a year. | Homes with an EV or electric heat upgrading their service a year. |
| `main_replacement` | year | `rate=0.02, minutes=1440.0, target_days=40.0, materials=45000.0` |  |  | Main renewal: share of cast-iron water and gas main length replaced a year (minutes and materials per 100 m). | Cast-iron main renewed a year: the biggest capital cost. |
