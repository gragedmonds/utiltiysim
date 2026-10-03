"""How every setting changes the results: where it reaches and by what mechanism.

The settings page shows this in each field's (i) popover (``x-reach`` and ``x-impact`` in the JSON Schema), and
``docs/CONFIG.md`` prints it. Reaches, from the meter-to-cash year outward:

``year``
    A run setting. It changes the meter-to-cash year directly (reads, VEE, queues, bills, collections) on the same
    town, with no regeneration.
``town``
    A town setting that changes the customers, their usage, routes or prices, so the year replays a different
    population. Changing it builds a new town.
``shape``
    Town geometry. It moves streets, lots and buildings. Because every home's household is drawn from its place in
    the town, a change re-draws households and the year's totals move by about as much as a different seed would
    move them; it is not a lever on the year.
``operations``
    The operations day on the map: networks, pressures, voltages, incidents, crews and vans. The year sees it only
    through interruptions you carry from a day into a run.
``display``
    Labels, units, clocks and default dates. No result changes.

``scripts/config_impact.py`` measures each town setting on two towns (nudge it, regenerate, replay the year) and
writes ``docs/CONFIG_IMPACT.md``; tests keep this table complete.
"""

from __future__ import annotations

REACHES = {
    "year": "Changes the meter-to-cash year directly, on the same town.",
    "town": "Changes the customers, usage, routes or prices the year replays. Builds a new town.",
    "shape": "Map shape. Rearranges the town; the year moves only because homes are drawn again (seed-sized noise).",
    "operations": "The operations day on the map. Reaches the year only through interruptions you carry into a run.",
    "display": "Display only: labels, units, clocks or default dates. No result changes.",
}

# Settings removed because nothing used them (not modelled, deprecated) or they only labelled the map. Old configs
# and snapshots that still carry them load: SimConfig drops these keys before validation.
REMOVED: dict[str, tuple[str, ...]] = {
    "housing": ("semi_share",),
    "electric": ("transmission_kv", "severe_turn_deg"),
    "ami": ("battery_life_years", "comm_fail_rate"),
    "operations": ("drive_by_radius_m", "walker_meters_per_hour"),
    "process": ("sequences",),
    "scenario": ("tick_minutes",),
    # Towns are generic: streets come from the settings and the seed, never from a real place's street extract.
    "town": ("skeleton", "osm_source", "osm_sha256", "expansion"),
}

IMPACT: dict[str, tuple[str, str]] = {
    # ---- seeds ------------------------------------------------------------------------------------------------------
    "seeds.master": ("town", "Re-rolls everything: the streets, households, weather, incidents and the "
                             "year's draws. Use it to see how much results vary by chance alone."),
    "seeds.town": ("town", "Re-rolls the geography (growth, lots, buildings). Households sit on lots, so they are drawn "
                           "again too and usage totals shift by a few percent."),
    "seeds.households": ("town", "Re-rolls who lives where: occupants, solar, EVs, heating fuel, pools, payer profiles "
                                 "and tenancies. Streets stay put. Small towns move several percent on solar export."),
    "seeds.weather": ("town", "Re-rolls the daily temperatures: heating and cooling usage follow, and so do the cold "
                              "days that make AMI, AMR and walked reads miss more often."),
    "seeds.incidents": ("town", "Re-rolls the random leaks, breaks, faults and collector outages, on "
                                      "the operations day and across the year, so the outage and gas odour "
                                      "contacts move too."),
    "seeds.anomalies": ("town", "Re-rolls the year's draws (missed reads, anomalies, analyst work, bill checks) on the "
                                "same households. A run's own seed overrides it without building a new town."),
    # ---- town & geography ---------------------------------------------------------------------------------------------
    "town.houses": ("town", "The number of homes. Accounts, reads, exceptions, bills and staffing load scale with it; "
                            "a bigger town also spreads further, so its edge reaches newer eras."),
    "town.units": ("display", "How values are labelled (Ontario, US or UK units). Stored values stay SI; no result "
                              "changes."),
    "town.anchor_lat": ("display", "Where the town sits on the globe: its latitude and the sun path "
                                   "in the map's day and night. Measured: no usage, network or year change."),
    "town.anchor_lon": ("display", "Where the town sits on the globe (its longitude). Measured: no "
                                   "usage, network or year change."),
    "town.timezone": ("display", "The local clock for timestamps, read schedules and business days. Measured: the "
                                 "year's figures do not change, only the times printed on records."),
    "town.terrain_relief_m": ("operations", "Hillier towns get a second water pressure zone, another elevated tank and "
                                            "PRVs or boosters at zone boundaries: pressures on the operations day."),
    "town.terrain_wavelength_m": ("operations", "How quickly the ground rises and falls: elevations, water pressures "
                                                "and zone boundaries on the operations day."),
    "town.arterial_spacing_m": ("shape", "Synthetic towns and grown districts only: how far apart the main roads run, "
                                         "so block sizes and drive times. On a real-street town it does nothing."),
    "town.arterial_warp_m": ("shape", "Synthetic towns and grown districts only: how much the main roads bend."),
    "town.collector_block_m": ("shape", "Synthetic towns and grown districts only: superblocks larger than this get a "
                                        "collector road."),
    "town.era_core_year": ("town", "When the centre was built; ages every home. Older homes leak more heat (more gas or "
                                   "electric heating), rent more, have less solar and EV, and sit on overhead lines and "
                                   "cast-iron mains."),
    "town.era_span_years": ("town", "How much newer the edge is than the centre. A wider span puts more homes in the "
                                    "modern era: better insulation, more solar, EVs, pools and irrigation."),
    "town.era_noise_years": ("town", "Scatter of construction years between districts: a few districts change era, "
                                     "which shifts their insulation, appliances and tenure."),
    "town.park_share": ("shape", "Blocks kept as parks. Homes move to other blocks; the count stays the same."),
    "town.commercial_strip_m": ("town", "Length of the all-commercial main street downtown: more storefront accounts "
                                        "with commercial usage, tariffs and gas heat."),
    "town.commercial_share_arterial": ("town", "Share of arterial frontage that becomes shops: more commercial accounts "
                                               "(large, steady electric and gas loads) while homes stay at the count."),
    "town.commercial_share_collector": ("town", "Share of collector frontage that becomes shops: more commercial "
                                                "accounts."),
    "town.commercial_share_local": ("town", "Corner stores on local streets: a few more commercial accounts."),
    "town.commercial_cluster_m": ("shape", "How tightly shops cluster around main-road junctions and downtown. Which "
                                           "lots hold shops changes, not how many."),
    "town.industrial_lots": ("town", "Large industrial customers. Each is a very large electric, gas and water account; "
                                     "two of them are about a tenth of a small town's usage."),
    "town.houses_per_school": ("town", "One school per this many homes, rounded (towns under about 1,250 "
                                       "homes have none). A school is an institutional account with a large "
                                       "floor area, heavy water use and gas heat."),
    "town.margin_m": ("shape", "Empty land around the developed area, where utility sites sit. It moves things on the "
                               "map only."),
    "town.corridor_max_deflection_deg": ("operations", "How sharp a bend still counts as one road corridor: feeder "
                                                       "routes follow corridors, so it can change which customers share "
                                                       "a feeder (and an outage) on the operations day."),
    "town.corridor_name_bonus_deg": ("operations", "Extra bend allowed when both roads share a name, for feeder "
                                                   "corridors on the operations day."),
    # ---- housing ------------------------------------------------------------------------------------------------------
    "housing.lot_frontage_m": ("town", "Wider lots build wider houses (55 to 70 percent of the frontage, up to 15 m): "
                                       "more floor area, so more heating and base load. Fewer lots fit each street, so "
                                       "homes spread to other streets and eras. Pools need lots over 600 m²."),
    "housing.lot_depth_m": ("town", "Deeper lots are larger (pools need over 600 m²) and leave room for "
                                    "deeper houses on shallow streets. On synthetic towns it also reshapes "
                                    "blocks, which re-draws households, so totals move by about seed-sized "
                                    "noise."),
    "housing.setback_m": ("shape", "How far houses sit back from the street. On shallow lots a deep setback makes the "
                                   "house shallower, a fraction of a percent of usage."),
    "housing.two_storey_share": ("town", "Two storeys double the floor area on the same footprint: more heating in "
                                         "winter, more cooling and base load, and higher bills."),
    "housing.occupancy_rate": ("town", "Vacant homes use almost nothing (12 percent of base load, 3 percent of water). "
                                       "Fewer occupied homes: lower usage, more zero-use reads for VEE, vacant-consuming "
                                       "cases and first bills at move-in."),
    "housing.rental_share": ("town", "Rentals turn over: more move-ins and move-outs, so more first bills, final bills, "
                                     "short tenancies and contract changes for billing and collections."),
    "housing.household_size_weights": ("town", "Bigger households use more water (people times litres per day) and "
                                               "more base electricity: higher water bills above all."),
    "housing.solar_rate": ("town", "Homes with rooftop PV by era: export registers, net-metering credits on bills, and "
                                   "low or negative summer net use that VEE and billing must handle."),
    "housing.pv_kw_min": ("town", "Smallest PV system: more export and larger net-metering credits per solar home."),
    "housing.pv_kw_max": ("town", "Largest PV system: more export and larger summer credits per solar home."),
    "housing.ev_rate": ("town", "EV chargers add about 6.5 kWh a day per home, all year: higher electric usage and "
                                "bills, and bigger transformers on the map."),
    "housing.electric_heat_rate": ("town", "Electric instead of gas heat: winter electric usage and bills rise, gas "
                                           "accounts and gas usage fall."),
    "housing.heat_pump_share_of_electric": ("town", "Heat pumps use far less than baseboard heat for the same warmth: "
                                                    "lower winter electric usage and bills."),
    "housing.ac_rate": ("town", "Central air adds cooling load on hot days: higher July and August electric usage and "
                                "bills, and summer high-bill checks."),
    "housing.pool_rate": ("town", "Pools (only on lots over 600 m², more in modern districts) run a pump and heater on "
                                  "electricity, about 7.5 kWh a day from May to September, and top up 0.15 m³ of water "
                                  "a day. Pools are not heated with gas in this engine."),
    "housing.irrigation_rate": ("town", "Lawn watering adds summer water use (May to September, peaking in July): "
                                        "higher summer water bills and seasonal swings VEE must accept."),
    # ---- electric -----------------------------------------------------------------------------------------------------
    "electric.primary_kv": ("operations", "Feeder voltage: voltage drop and loading in the operations day's power "
                                          "flow."),
    "electric.secondary_v": ("operations", "Service voltage for the power flow and the voltage readings on the map."),
    "electric.kva_per_100m2": ("operations", "Design load per floor area: transformer and conductor sizes, so loading "
                                             "and overload failures on the operations day. Usage is not affected."),
    "electric.kva_ac": ("operations", "Design load added for air conditioning: equipment sizing on the map."),
    "electric.kva_electric_heat": ("operations", "Design load added for electric heat: equipment sizing on the map."),
    "electric.kva_heat_pump": ("operations", "Design load added for a heat pump: equipment sizing on the map."),
    "electric.kva_ev": ("operations", "Design load added for an EV charger: equipment sizing on the map."),
    "electric.kva_pool": ("operations", "Design load added for a pool: equipment sizing on the map."),
    "electric.coincidence_floor": ("operations", "How much peaks overlap: larger floors size bigger transformers and "
                                                 "feeders."),
    "electric.transformer_kva_steps": ("operations", "The transformer sizes available: groupings, loading and "
                                                     "overloads on the map."),
    "electric.transformer_max_loading": ("operations", "Allowed loading before a bigger transformer is chosen: "
                                                       "overloaded units fail three times as often on the operations "
                                                       "day."),
    "electric.conductor_planning_margin": ("operations", "Head-room in primary conductor sizing: thicker "
                                                         "conductors, less loading on the map."),
    "electric.max_houses_per_transformer_overhead": ("operations", "Houses per pole transformer: how many customers "
                                                                   "lose power when one fails."),
    "electric.max_houses_per_transformer_underground": ("operations", "Houses per pad transformer: how many customers "
                                                                      "lose power when one fails."),
    "electric.feeder_design_mva": ("operations", "Design peak per feeder: how many feeders, and so how many customers "
                                                 "one feeder fault interrupts."),
    "electric.feeder_max_customers": ("operations", "Most customers on one feeder: the largest outage one breaker trip "
                                                    "can cause."),
    "electric.min_feeders_per_substation": ("operations", "Feeders per substation, so ties can back-feed during an "
                                                          "outage."),
    "electric.substation_mva": ("operations", "Firm capacity per substation: big towns get a second substation."),
    "electric.route_weight_arterial": ("operations", "Feeder routing cost along arterials: where trunks run and which "
                                                     "customers share them."),
    "electric.route_weight_collector": ("operations", "Feeder routing cost along collector roads: where "
                                                      "trunks run on the map."),
    "electric.route_weight_local": ("operations", "Feeder routing cost along local streets: where trunks run "
                                                  "on the map."),
    "electric.route_turn_penalty_m": ("operations", "How much feeders avoid turns: straighter, longer trunks."),
    "electric.route_corridor_change_penalty_m": ("operations", "How much feeders avoid switching corridors: "
                                                               "straighter feeders on the map."),
    "electric.route_hierarchy_penalty_m": ("operations", "How much feeders avoid stepping between road classes."),
    "electric.trunk_min_load_share": ("operations", "How far a three-phase trunk extends before laterals take over."),
    "electric.route_shared_trunk_factor": ("operations", "How much feeders avoid running through each other's "
                                                         "territory."),
    "electric.ties_per_feeder_pair": ("operations", "Normally-open ties: with ties, crews restore part of a faulted "
                                                    "feeder from a neighbour, so outages are shorter on the operations "
                                                    "day."),
    "electric.tie_max_length_m": ("operations", "Longest line built for a tie: more ties, more restoration options."),
    "electric.section_max_share": ("operations", "Sectionalising switches: smaller sections mean a fault takes out "
                                                 "fewer customers."),
    "electric.section_min_customers": ("operations", "Smallest section a feeder is cut into: how few "
                                                     "customers one fault can take out."),
    "electric.overhead_before_year": ("operations", "Districts built before this year are on poles: storm faults and "
                                                    "pole transformers on the operations day."),
    "electric.pole_spacing_m": ("operations", "Pole span on overhead lines: pole count, and where AMI collectors can "
                                              "mount."),
    "electric.voltage_min_pu": ("operations", "Low-voltage limit for the voltage readings on the map."),
    "electric.voltage_max_pu": ("operations", "High-voltage limit for the voltage readings on the map."),
    # ---- gas ----------------------------------------------------------------------------------------------------------
    "gas.all_electric_district_share": ("town", "Share of districts without gas mains, counted in whole "
                                                "districts and never the core: those homes heat with "
                                                "electricity, mostly heat pumps. Gas accounts and usage "
                                                "fall, winter electric usage rises. One-district towns "
                                                "(village, small_town) have none whatever the share."),
    "gas.scheme": ("operations", "Medium pressure everywhere or a legacy low-pressure core: regulators and pressures "
                                 "on the map."),
    "gas.transmission_kpa": ("operations", "Pressure into the city gate: gas pressures on the operations day."),
    "gas.mp_kpa": ("operations", "Medium-pressure set point: gas pressures on the operations day."),
    "gas.lp_kpa": ("operations", "Low-pressure core set point: gas pressures on the operations day."),
    "gas.lp_core_before_year": ("operations", "Districts older than this sit on the low-pressure core."),
    "gas.design_m3h_base": ("operations", "Design-hour demand per house: gas main sizes. Usage is not affected."),
    "gas.design_m3h_per_m2": ("operations", "Design-hour demand per floor area: gas main sizes."),
    "gas.coincidence_floor": ("operations", "How much gas peaks overlap: larger floors size bigger gas mains."),
    "gas.min_main_mm": ("operations", "Smallest gas main: pipe sizes and pressures on the map. Usage is not "
                                      "affected."),
    "gas.valve_spacing_m": ("operations", "Valve spacing: how much main a leak repair isolates."),
    "gas.calorific_mj_per_m3": ("display", "Energy per cubic metre for showing gas in GJ or therms. Bills charge per m³, "
                                           "so no amount changes."),
    "gas.base_pressure_kpa": ("operations", "Standard-volume base pressure in the gas flow equations."),
    "gas.base_temperature_c": ("operations", "Standard-volume base temperature in the gas flow equations."),
    # ---- water --------------------------------------------------------------------------------------------------------
    "water.lpcd": ("town", "Indoor water per person per day: every home's water usage and bill scales with it, and "
                           "wastewater charges follow."),
    "water.irrigation_m3_per_day": ("town", "Summer watering per irrigating home: higher summer water usage and bills."),
    "water.max_day_factor": ("operations", "Max-day demand used to size mains and storage on the map."),
    "water.peak_hour_factor": ("operations", "Peak-hour demand used to size mains: pipe sizes and pressures "
                                             "on the map."),
    "water.fire_flow_residential_lps": ("operations", "Fire flow that sizes residential mains: bigger mains, lower "
                                                      "velocities."),
    "water.fire_flow_commercial_lps": ("operations", "Fire flow that sizes commercial mains: pipe sizes and "
                                                     "pressures on the map."),
    "water.fire_flow_industrial_lps": ("operations", "Fire flow that sizes the industrial and supply mains."),
    "water.min_main_mm": ("operations", "Smallest main that carries hydrants: pipe sizes and pressures on the "
                                        "map."),
    "water.collector_main_mm": ("operations", "Smallest main on collector roads: pipe sizes and pressures on "
                                              "the map."),
    "water.arterial_main_mm": ("operations", "Smallest transmission main from the pump station."),
    "water.hw_c_new": ("operations", "Pipe roughness of new mains: pressures on the operations day."),
    "water.hw_c_old": ("operations", "Pipe roughness of old cast iron: more head loss, lower pressures."),
    "water.cast_iron_before_year": ("operations", "Mains older than this are cast iron: rougher and break twice as "
                                                  "often on the operations day."),
    "water.tank_overflow_above_ground_m": ("operations", "Elevated tank height: static pressure in its zone."),
    "water.zone_band_m": ("operations", "Elevation band per pressure zone: how many zones a hilly town needs."),
    "water.hydrant_spacing_m": ("operations", "Hydrant spacing on residential mains: hydrant count on the "
                                              "map."),
    "water.hydrant_spacing_commercial_m": ("operations", "Hydrant spacing in commercial areas: hydrant count "
                                                         "on the map."),
    "water.valve_spacing_m": ("operations", "Valve spacing: how many customers a main break isolates."),
    "water.pump_units": ("operations", "Pumps at the station, one on standby: pumping capacity on the "
                                       "operations day."),
    # ---- metering & AMI -----------------------------------------------------------------------------------------------
    "ami.ami_route_share": ("town", "Routes read by AMI. AMI reads are cheapest and miss least (1.2 percent); moving "
                                    "routes to AMR or walkers raises read cost, missed reads, estimates and the work "
                                    "they create."),
    "ami.amr_route_share": ("town", "Routes read by drive-by AMR vans: costlier than AMI and missed more often "
                                    "(3 percent), with their own anomaly factor. The rest are walked."),
    "ami.collector_radius_m": ("operations", "AMI collector reach: how many collectors, and how many meters go dark "
                                             "when one fails on the operations day."),
    "ami.poll_start_hour": ("display", "When the nightly AMI poll starts: the time stamped on AMI reads. Results do not "
                                       "change."),
    "ami.poll_end_hour": ("display", "When the nightly AMI poll ends: the latest time stamped on AMI reads. "
                                     "Results do not change."),
    "ami.meter_digits_electric": ("town", "Register digits on electric meters: where registers roll over, and how far a "
                                          "transposed or misread digit throws a read."),
    "ami.meter_digits_water": ("town", "Register digits on water meters: rollover and digit-error size."),
    "ami.meter_digits_gas": ("town", "Register digits on gas meters: rollover and digit-error size."),
    # ---- weather ------------------------------------------------------------------------------------------------------
    "weather.winter": ("town", "Winter temperatures: colder winters raise heating usage (gas, or electricity for "
                               "electric homes), winter bills, and the deep-cold days below -10 °C when reads miss "
                               "more."),
    "weather.spring": ("town", "Spring temperatures: a cold spring keeps heating usage and bills up into "
                               "April and May."),
    "weather.summer": ("town", "Summer temperatures: hotter summers raise cooling usage and bills on homes with air "
                               "conditioning."),
    "weather.fall": ("town", "Fall temperatures: an early cold snap raises October and November heating usage "
                             "and bills."),
    "weather.persistence": ("town", "How long warm or cold spells last: longer spells make monthly usage swing more "
                                    "from normal, which VEE's tolerances see."),
    "weather.storm_days_per_year": ("town", "Thunderstorm days: overhead faults and outages on the "
                                                  "operations day and across the year, with the outage "
                                                  "reports they bring to the contact centre."),
    "weather.heating_base_c": ("town", "Heating starts below this temperature: a higher base means more heating "
                                       "usage in spring and fall."),
    "weather.cooling_base_c": ("town", "Cooling starts above this temperature: a lower base means more cooling usage."),
    # ---- incidents ----------------------------------------------------------------------------------------------------
    "incidents.gas_service_leaks_per_1000": ("town", "Random service leaks on the operations day and "
                                                           "across the year: gas odour calls and a household "
                                                           "without gas until the repair."),
    "incidents.gas_main_leaks_per_100km": ("town", "Random gas main leaks on the operations day and "
                                                         "across the year: crew calls, isolations and gas "
                                                         "odour calls from the neighbours."),
    "incidents.water_main_breaks_per_100km": ("town", "Random main breaks on the operations day and "
                                                            "across the year: customers without water and "
                                                            "the outage reports they make."),
    "incidents.overhead_faults_per_km_storm_day": ("town", "Storm faults on overhead lines: feeder "
                                                                 "outages on storm days, on the operations "
                                                                 "day and across the year, and the outage "
                                                                 "reports."),
    "incidents.transformer_failures_per_1000": ("town", "Transformer failures (three times as many "
                                                              "where units are overloaded): small outages on "
                                                              "the operations day and across the year."),
    "incidents.collector_outages_per_year": ("operations", "AMI collector outages: the meters behind it "
                                                           "miss their nightly read that day. Customers do "
                                                           "not notice them."),
    "incidents.manual_only": ("operations", "Turns random incidents off on the operations day; only the "
                                            "ones you inject happen. The year draws them unless Outages & "
                                            "leaks is off."),
    # ---- field operations ---------------------------------------------------------------------------------------------
    "operations.gas_crews": ("operations", "Gas crews: how fast leaks are made safe on the operations day."),
    "operations.electric_crews": ("operations", "Electric crews: how long outages last on the operations day."),
    "operations.water_crews": ("operations", "Water crews: how long main breaks keep customers off."),
    "operations.meter_techs": ("operations", "Meter technicians for exchanges and investigations on the operations "
                                             "day. The year's field capacity is Field orders per day."),
    "operations.meter_vans": ("operations", "AMR vans driving routes on the operations day; routes are shared among "
                                            "them."),
    "operations.meter_walkers": ("operations", "Walkers reading manual routes on the operations day."),
    "operations.shift_start_hour": ("operations", "When the day shift starts: non-emergency repairs wait for it."),
    "operations.shift_end_hour": ("operations", "When the day shift ends: non-emergency repairs left after it "
                                                "wait for the next morning."),
    "operations.gas_response_target_min": ("operations", "The response target gas crews are measured against "
                                                         "on the operations day."),
    "operations.speed_kmh_arterial": ("operations", "Driving speed on arterials: crew and van travel times."),
    "operations.speed_kmh_collector": ("operations", "Driving speed on collector roads: crew and van travel "
                                                     "times on the operations day."),
    "operations.speed_kmh_local": ("operations", "Driving speed on local streets: crew and van travel times "
                                                 "on the operations day."),
    # ---- customers & billing ------------------------------------------------------------------------------------------
    "customers_billing.mru_target_meters": ("town", "Premises per reading route. Every town gets at least "
                                                    "one route per billing portion (21), so it only bites "
                                                    "above about 9,500 premises; then smaller routes mean "
                                                    "more of them and a different split of AMI, AMR and "
                                                    "walked routes."),
    "customers_billing.bill_cycles": ("town", "Billing portions per month: how reads and bills spread across working "
                                              "days, so daily queue load and when bills go out."),
    "customers_billing.currency": ("display", "The currency label on bills. Amounts do not change."),
    "customers_billing.tax_rate": ("town", "Sales tax on every bill: invoice totals, receivables and late fees scale "
                                           "with it."),
    "customers_billing.electric_fixed_monthly": ("town", "Fixed electric charge: every electric bill moves by this, "
                                                         "whatever the usage."),
    "customers_billing.electric_blocks": ("town", "Energy price blocks: bill amounts, high-bill checks and the cost of "
                                                  "each billing error."),
    "customers_billing.electric_variable_delivery": ("town", "Delivery charge per kWh: electric bills scale with "
                                                             "usage."),
    "customers_billing.net_metering_credit": ("town", "Credit per exported kWh: solar homes' summer bills and the "
                                                      "large-credit checks."),
    "customers_billing.gas_fixed_monthly": ("town", "Fixed gas charge: every gas bill moves by this, whatever "
                                                    "the usage."),
    "customers_billing.gas_price_m3": ("town", "Gas price per m³: winter gas bills scale with it."),
    "customers_billing.water_fixed_monthly": ("town", "Fixed water charge: every water bill moves by this, "
                                                      "whatever the usage."),
    "customers_billing.water_price_m3": ("town", "Water price per m³: water bills scale with it, and "
                                                 "wastewater follows it."),
    "customers_billing.wastewater_ratio": ("town", "Wastewater as a multiple of the water price: water bills scale "
                                                   "with it."),
    "customers_billing.on_time_payer_share": ("town", "Accounts that pay on time. Fewer means more overdue balances, "
                                                      "reminders, notices, late fees and collections work."),
    "customers_billing.late_payer_share": ("town", "Accounts that pay late; the rest are at-risk payers who may not pay "
                                                   "at all. More late and at-risk payers drive dunning and "
                                                   "disconnections."),
    "customers_billing.pre_authorized_share": ("town", "Accounts on pre-authorized debit: they pay on the due date, but "
                                                       "a share bounce, which opens payment-rejected cases and NSF "
                                                       "fees."),
    "customers_billing.due_days": ("town", "Days from invoice to due date: when accounts go overdue, so receivable "
                                           "carry and the dunning calendar."),
    # ---- meter-to-cash process (run) ----------------------------------------------------------------------------------
    "process.rpa_coverage": ("year", "Share of exception types automation resolves. More coverage: fewer cases for "
                                     "analysts, cheaper and faster resolution, less carry; uncovered types still queue "
                                     "for people."),
    "process.analyst_queue_days_min": ("year", "Shortest wait before an analyst first looks at a case: every human case "
                                               "takes at least this long, so carry and days to release rise."),
    "process.analyst_queue_days_max": ("year", "Longest first-look wait: the tail of slow cases, open-case counts and "
                                               "carry."),
    "process.carry_rate_per_day": ("year", "Cost of a day a bill is held back. Prices the carry; it does not change "
                                           "which cases happen."),
    "process.receivable_carry_ratio": ("year", "Carry on unpaid invoices as a share of the billing carry rate. Prices "
                                               "receivable carry only."),
    "process.analysts": ("year", "People working the queues. Fewer: backlog grows, cases age, estimates and blocked "
                                 "bills wait longer and carry builds; more: queues clear faster."),
    "process.analyst_hours_per_day": ("year", "Queue hours per analyst per day: capacity, like the number of analysts."),
    "process.review_minutes_min": ("year", "Shortest review: longer reviews cut how many cases a day each analyst "
                                           "clears."),
    "process.review_minutes_max": ("year", "Longest review: capacity and labor cost per case."),
    "process.supervisors": ("year", "Supervisors approving escalations. Zero: escalated cases wait, high-impact bills "
                                    "stay held."),
    "process.supervisor_hours_per_day": ("year", "Supervisor time for escalations: how fast the Escalations queue "
                                                 "clears."),
    "process.supervisor_minutes": ("year", "Supervisor time per escalation: capacity and labor cost."),
    "process.supervisor_queue_days_min": ("year", "Shortest wait for a supervisor: escalated cases take at least this "
                                                  "long."),
    "process.supervisor_queue_days_max": ("year", "Longest wait before a supervisor picks up an escalation: "
                                                  "the tail of held high-impact bills."),
    "process.field_orders_per_day": ("year", "Field orders worked per day (re-reads, checks, exchanges). Fewer: field "
                                             "backlog, longer estimate streaks, stuck and slow meters fixed later."),
    "process.field_days_min": ("year", "Earliest a field order is worked after it is raised."),
    "process.analyst_accuracy": ("year", "Reviews where the analyst finds the true cause. Lower: wrong dispositions, "
                                         "billing errors that surface later as rebills and complaints."),
    # ---- anomalies (run) ----------------------------------------------------------------------------------------------
    "anomalies.enabled": ("year", "Off: reads are clean apart from missed reads, so VEE flags only what usage swings "
                                  "and outages explain. Truth is always kept for scoring."),
    "anomalies.leak": ("year", "Water leaks after the meter: high water reads, high-bill blocks and complaints."),
    "anomalies.stuck_meter": ("year", "Registers that stop: zero-use reads at occupied homes, field orders and "
                                      "exchanges, under-billing until fixed."),
    "anomalies.slow_meter": ("year", "Meters under-registering 10 to 40 percent: lost revenue VEE catches only through "
                                     "the trend test."),
    "anomalies.transposed_digits": ("year", "Two digits swapped in a read: wild spikes or drops VEE should reject."),
    "anomalies.misread": ("year", "A high digit off by one: large spikes or negative use."),
    "anomalies.consecutive_estimates": ("year", "Runs of estimated periods (more on walked routes): estimate streaks "
                                                "that trigger field reads and true-ups."),
    "anomalies.missing_read": ("year", "Periods with no read document: estimates and missing-read cases."),
    "anomalies.exchange_registration_failure": ("year", "Meter exchanges whose new meter fails registration: zero use, "
                                                        "blocked bills and analyst or field work."),
    "anomalies.vacant_consuming": ("year", "Vacant homes that still use energy: unbilled consumption cases."),
    "anomalies.tamper": ("year", "Bypasses that under-register 50 to 90 percent: lost revenue and investigations."),
    "anomalies.amr_factor": ("year", "Multiplies every anomaly rate on AMR meters: an ageing drive-by fleet misreads "
                                     "and under-registers more."),
    "anomalies.manual_factor": ("year", "Multiplies every anomaly rate on walked meters: more misreads and "
                                        "faults on manual routes."),
    # ---- scenario (run) -----------------------------------------------------------------------------------------------
    "scenario.name": ("operations", "The map's demonstration (normal, solar noon, leak, substation outage) on the "
                                    "live day. The year is unchanged."),
    "scenario.date": ("display", "The day the map shows and the Studio opens on. The year's results are the same; "
                                 "only the default view date moves."),
    "scenario.hour": ("display", "The hour the map's live clock starts at. The year is unchanged."),
    "scenario.target_premise": ("operations", "The premise the map's leak demonstration targets."),
    "scenario.leak_m3h": ("operations", "Leak size in the map's leak demonstration: flows and pressures that day."),
    # ---- meter reading (run) ------------------------------------------------------------------------------------------
    "reading.ami_missed_read": ("year", "AMI reads still missing after retries: estimates, missing-read cases and "
                                        "estimate streaks."),
    "reading.amr_missed_read": ("year", "Drive-by reads missed: estimates and missing-read cases on AMR routes."),
    "reading.manual_no_access": ("year", "Walked reads with no access: estimates, streaks and field reads."),
    "reading.no_access_repeat": ("year", "Chance a no-access meter is missed again next month: longer estimate streaks "
                                         "and more field reads."),
    "reading.read_cost_ami": ("year", "Cost of one AMI read. Prices reading; no read changes."),
    "reading.read_cost_amr": ("year", "Cost of one drive-by read. Prices reading in the cost totals; no read "
                                      "changes."),
    "reading.read_cost_manual": ("year", "Cost of one walked read. Prices reading in the cost totals; no read "
                                         "changes."),
    # ---- VEE rules (run) ----------------------------------------------------------------------------------------------
    "vee.high_ratio": ("year", "Flag use above this multiple of expected. Lower: more high reads flagged (more cases, "
                               "more real spikes caught, more false alarms)."),
    "vee.low_ratio": ("year", "Flag use below this share of expected. Higher: more low reads flagged, catching slow and "
                              "stuck meters sooner at the cost of more cases."),
    "vee.zero_at_occupied": ("year", "Flag zero use at an occupied home: catches stuck meters and failed exchanges."),
    "vee.max_consecutive_estimates": ("year", "Estimates in a row before a field read is ordered: lower means more "
                                              "field orders, shorter streaks."),
    "vee.min_period_days": ("year", "Shortest plausible read period: shorter periods fail the timing test."),
    "vee.max_period_days": ("year", "Longest plausible read period: longer periods fail the timing test and "
                                    "go to review."),
    "vee.accept_confidence": ("year", "Auto-accept at or above this confidence. Higher: fewer reads auto-accepted, more "
                                      "for review."),
    "vee.reject_confidence": ("year", "Reject below this confidence (the read is replaced by an estimate)."),
    "vee.escalate_impact": ("year", "Doubtful reads whose bill impact exceeds this go to a supervisor: lower means more "
                                    "escalations and supervisor load."),
    "vee.trend_ratio": ("year", "Persistent low use below this share of expected is flagged: how slow meters and tamper "
                                "are caught."),
    "vee.trend_periods": ("year", "Periods of low use before the trend flag: fewer means earlier detection, more "
                                  "cases."),
    "vee.oms_events": ("year", "Use outage events: hours without service lower the expected use, so "
                               "outage-explained low reads are accepted instead of flagged. Only matters "
                               "when a run carries interruptions from an operations day."),
    "vee.estimation": ("year", "How missing or rejected reads are estimated: prior year or average daily use. Changes "
                               "estimated amounts and later true-ups."),
    "vee.history_noise": ("year", "How far last year's history strays from this year's normal use: more noise, more "
                                  "reads look odd against history."),
    # ---- billing & collections (run) ----------------------------------------------------------------------------------
    "billing.rate_change_date": ("year", "When the new tariff version starts: bills after it prorate across the change."),
    "billing.rate_change_pct": ("year", "Price change in the new tariff version: bill amounts after the date."),
    "billing.high_bill_ratio": ("year", "Block bills above this multiple of expected: lower means more billing outsorts "
                                        "for analysts or RPA."),
    "billing.high_bill_min": ("year", "And at least this much above expected: filters small bills out of high-bill "
                                      "checks."),
    "billing.first_bill_limit": ("year", "Block first bills above this total when there is no expected use "
                                         "to compare with (vacant or new premises). Rare in small towns."),
    "billing.credit_review": ("year", "Block credit bills larger than this for review: lower means more "
                                      "credit outsorts."),
    "billing.outsort_auto_release_max": ("year", "RPA may release outsorts up to this amount; larger ones wait for an "
                                                 "analyst."),
    "billing.billing_queue_worked_by": ("year", "Who works the Billing queue: analysts and RPA, or only you (cases wait "
                                                "for your decisions)."),
    "billing.trueup_max_ratio": ("year", "Block estimate true-ups (a negative period after an "
                                         "over-estimate) larger than this multiple of expected use. Rare "
                                         "unless estimates run high."),
    "billing.data_error_rate": ("year", "Wrong rate classes in billing master data: mis-billed accounts, rate-class "
                                        "blocks and rebills."),
    "billing.print_lag_days": ("year", "Days from invoice to issue: due dates and receivable carry move with it."),
    "billing.pad_reject_rate": ("year", "Pre-authorized debits that bounce: payment-rejected cases, NSF fees and "
                                        "overdue balances."),
    "billing.nsf_fee": ("year", "Fee added to an account when a payment bounces: higher balances and more "
                                "overdue amounts."),
    "billing.late_fee_pct": ("year", "Late charge on overdue amounts at each notice: higher balances and "
                                     "receivables."),
    "billing.reminder_days": ("year", "Days after the due date for a reminder letter: when collections work "
                                      "starts."),
    "billing.notice_days": ("year", "Days after the due date for an overdue notice and late fee: when fees "
                                    "start to build."),
    "billing.disconnect_days": ("year", "Days after the due date for a disconnection notice: later notices, "
                                        "fewer disconnections in the year."),
    "billing.winter_moratorium": ("year", "No electric or water disconnection notices in winter; held notices go out "
                                          "after the end date. Shifts collections from winter to spring."),
    "billing.moratorium_start": ("year", "First day of the winter moratorium: an earlier start holds more "
                                         "autumn notices."),
    "billing.moratorium_end": ("year", "Last day of the winter moratorium; held notices go out the next day."),
    "billing.disconnect_notice_days": ("year", "Days from a disconnection notice to the earliest "
                                               "disconnection. Acts only on disconnections you approve: the "
                                               "engine never disconnects on its own."),
    "billing.disconnect_payment_rate": ("year", "Disconnected customers who pay within a week and are "
                                                "reconnected the next business day. Acts only on "
                                                "disconnections you approve in the Collections worklist."),
    "billing.arrangement_break_rate": ("year", "At-risk payers who break a payment arrangement after a few "
                                               "instalments; dunning resumes. Acts only on arrangements you "
                                               "set up in the Collections worklist."),
    "billing.low_income_referral_rate": ("year", "Notices and holds after which the customer is referred to a "
                                                 "low-income programme; dunning waits."),
    "billing.low_income_review_days": ("year", "Business days the agency takes to decide a referral; dunning "
                                               "waits meanwhile."),
    "billing.low_income_approval_rate": ("year", "Referrals approved with a grant against arrears: less owed, "
                                                 "fewer disconnections."),
    "billing.low_income_grant_max": ("year", "Largest low-income grant credited to an account's arrears: less "
                                             "owed, fewer notices."),
    "billing.budget_billing_offer_rate": ("year", "Overdue notices after which the customer moves to budget billing: "
                                                  "levelled later invoices."),

    # ---- contact centre (run) ----------------------------------------------------------------------------------------
    "contact.agents": ("year", "Agents answering during opening hours. Fewer: longer waits, more hang-ups, call backs "
                               "and repeat calls; more: shorter waits but more idle time and staffing cost."),
    "contact.open_hour": ("year", "When the lines open on business days. Later opening squeezes the same contacts "
                                  "into fewer hours: longer waits at peaks."),
    "contact.close_hour": ("year", "When the lines close. Earlier closing squeezes contacts into fewer hours; callers "
                                   "who find the lines closed try again the next day."),
    "contact.patience_s": ("year", "How long callers hold before hanging up. Less patience: more hang-ups and retries "
                                   "at the same waits."),
    "contact.retry_share": ("year", "Callers who hung up or found the lines closed and try again: retries add load "
                                    "at busy times; the rest give up unanswered."),
    "contact.repeat_share": ("year", "Customers whose problem was not resolved who contact again: repeat contacts, "
                                     "and complaints after a second failure."),
    "contact.callback": ("year", "Offer a call back instead of holding when the wait is long: fewer hang-ups, the "
                                 "same agent time spread later in the day."),
    "contact.callback_after_s": ("year", "Expected wait at which the call back is offered: lower offers it more often, "
                                         "turning hang-ups into later calls."),
    "contact.callback_take_share": ("year", "Callers who accept the call back offer."),
    "contact.service_target_s": ("year", "The answer target the service level counts against. It changes the reported "
                                         "service level, not who waits."),
    "contact.volume_factor": ("year", "Multiplies every reason's rates: a quick way to test a busier or quieter year."),
    "contact.handle_factor": ("year", "Multiplies every handling time: slower handling fills the agents' day, so waits "
                                      "and hang-ups rise."),
    "contact.self_serve_factor": ("year", "Multiplies the share the IVR and website handle; zero sends every contact to "
                                          "an agent."),
    "contact.agent_cost_per_hour": ("year", "Prices the agents' open hours in the contact cost. No contact changes."),
    "contact.self_serve_cost": ("year", "Prices each self-served contact. No contact changes."),
    "contact.abandon_cx_cost": ("year", "Prices the customer-experience cost of each hang-up. No contact changes."),
    "contact.emergency_answer_s": ("year", "Answer time on the emergency line (gas odours, after-hours outages)."),
    "contact.high_bill": ("year", "High-bill contacts: invoices at 1.5 times the expected amount. More estimates, "
                                  "leaks, cold months and rate changes raise them."),
    "contact.bill_question": ("year", "Questions about bills: more with estimated bills, first bills after a move-in "
                                      "and bills just after a rate change."),
    "contact.bill_wrong": ("year", "Disputes over bills that overcharge against the truth: VEE misses, rate-class "
                                   "errors and misreads drive them."),
    "contact.back_bill": ("year", "Contacts about catch-up bills: rebills, and the first actual bill after a run of "
                                  "estimates (no-access and missed reads drive them)."),
    "contact.balance": ("year", "Balance enquiries around due dates; the IVR answers most."),
    "contact.password": ("year", "Online account help when bills arrive; most reset online."),
    "contact.payment_arrangement": ("year", "Can't-pay contacts after reminders, overdue notices and disconnection "
                                            "notices: collections settings and payer mix drive them."),
    "contact.payment_problem": ("year", "Contacts after a returned pre-authorized debit (the PAD reject rate drives "
                                        "them)."),
    "contact.move_in": ("year", "Start-service contacts before each move-in: rentals and turnover drive them."),
    "contact.move_out": ("year", "Stop-service contacts before each move-out."),
    "contact.new_connection": ("year", "New-connection requests (background only)."),
    "contact.outage": ("year", "Outage reports from customers who lose power or water in the year's incidents; the "
                               "IVR's outage message answers most, after hours the emergency line."),
    "contact.gas_odour": ("year", "Gas odour calls from neighbours of the year's gas leaks, on the emergency line."),
    "contact.meter_access": ("year", "Contacts after no-access read cards and to book field visits: walked routes and "
                                     "no-access rates drive them."),
    "contact.disconnection": ("year", "Reconnection requests after disconnections you approve."),
    "contact.complaint": ("year", "Complaints after a second unresolved contact or giving up on hold twice: long waits "
                                  "and low first-contact resolution drive them."),
    # ---- outages & leaks over the year (run) ------------------------------------------------------------------------
    "outages.enabled": ("year", "Draw the operations day's incidents for every day of the year. Off: outage and gas "
                                "odour contacts are background only."),
    "outages.storm_factor": ("year", "Multiplies the chance of a storm day: more overhead line faults, outages and "
                                     "outage reports, mostly May to September."),
    "outages.incident_factor": ("year", "Multiplies every incident rate: more outages, main breaks and gas leaks, and "
                                        "the contacts they bring."),
    "outages.restore_factor": ("year", "Multiplies the time to restore service: longer outages bring twice the outage "
                                       "reports past two hours."),
}


def impact_of(group: str, key: str) -> tuple[str, str] | None:
    return IMPACT.get(f"{group}.{key}")
