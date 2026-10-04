# Roadmap

## M1: town, networks, customers (done)

Seeded towns, configurable, built from generic synthetic skeletons (OpenStreetMap extracts until October 2026):
- parcels, buildings, households and addresses;
- engineered electric, gas and water networks with equipment;
- IS-U-shaped customers, routes, schedules, AMI and baseline reads.

Outputs and tooling:
- the `utility-town/2.0` snapshot, GeoJSON, parquet, API and CLI;
- complete state frames and replays with sun and moon;
- JSON Schemas and OpenAPI;
- real-place presets from frozen OSM extracts (removed in October 2026: every town is now generic);
- the viewer's receiver conformance in CI.

## M2: time and physics (partly done)

Done:
- **Weather:** a seeded daily weather year (`sim/weather.py`). It drives monthly consumption through degree-days,
  live seasonal demand, frames (`clock.tempC`) and meter-reading conditions.
- **Run-scoped settings** (`x-applies: run`): process, anomalies, reading, VEE, billing and scenario.
- **Field movement:** walker and drive-by reading rounds on the operations day, with trajectories.
- **Radial power flow:** voltage, loading, losses and solar reverse flow in every frame. Back-feed only closes a tie
  the receiving feeder can carry.
- **Radial hydraulics:** water service pressure (Hazen-Williams from the tank grade) and two-tier gas pressure
  (Weymouth and Spitzglass) in every frame. Elevated tanks feed when the supply path is cut, and main breaks leak at
  orifice flow.
- **Looped hydraulics:** water and gas loop flows (Newton on the loop equations, `sim/loops.py`) in every frame, so
  loop edges carry numbers and service pressures come from the looped grades.

Next:
- tank levels over a day (a tank is a fixed grade today);
- tank and pump control;
- nightly AMI collection visualised;
- frames over WebSocket.

## M3: operations and meter-to-cash (done, iterating)

**Operations** (`utilsim/ops`):
- break a pole or a water/gas main, with protection, isolation and repair;
- a gas relight sweep with mutual-aid crews;
- field visits, with crews driving real roads;
- stateless, append-only command runs on the hosted engine.

**Meter-to-cash** (`utilsim/m2c`, see [M2C.md](M2C.md)):
- a year of reads with seeded anomalies and ground truth;
- VEE in the v5 shape;
- exception work queues: RPA, analysts, supervisors, field crews;
- Activity Sequence events, costs and carry;
- billing documents, blocks, invoices, payments, dunning and ledgers;
- analyst actions from the viewer;
- a VEE scorecard against simulation truth (recall per anomaly, precision per exception).

**Linked:**
- the operations day schedules that day's reading rounds and meter-to-cash field orders as crew jobs;
- a field visit on the map settles the premise's open read cases;
- the map and the worklists share one run day;
- outages on the map reach meter-to-cash: lost use, AMI last gasps and missed reads, outage-aware VEE, SAIDI.

Next:
- a two-way connector with the real m2c.vee engine (import dispositions);
- budget billing and payment arrangements.

## M4: product (in progress)

Viewer (Astra's package):
- Worklists page;
- Activity sequences explorer;
- meter-to-cash settings tab rendered from the engine's schema;
- billing tab from the engine;
- daytime outage rings;
- main roads leaning commercial;
- meter-to-cash on the map: reading-round outcomes, the day's cycle, outages feeding meter-to-cash, a VEE scorecard.

Next:
- **Start from your numbers** (the digital twin, [TWIN.md](TWIN.md)): the engine fits its levers to observed
  KPIs and known inputs (`utilsim twin`, `POST /api/twin/fit`) and proposes the setup; done. Still open: the Studio
  entry card and browser-driven fit, town levers for payment figures, candidate explanations side by side, the
  shared-workforce batch mode for a pool of billers over districts;
- road hierarchy and utility corridors ([CORRIDOR_ROUTING_REQUIREMENTS.md](CORRIDOR_ROUTING_REQUIREMENTS.md)):
  electric is done in generator 0.6.0 (corridors, turn-aware trunks, feeder territories, express sections,
  normally-open ties, corridor exports and routing metrics); still open: water/gas backbone-first routing, road
  `hierarchy` overrides and classification provenance, construction-transition rationale beyond `riser` assets;
- a visual Activity Sequence builder;
- real-place import from the UI;
- hosted 10,000-home towns (chunked snapshots, precomputed base runs).
