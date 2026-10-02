# Roadmap

## M1: town, networks, customers (done)

Seeded towns, configurable, built from OSM or synthetic skeletons with growth:
- parcels, buildings, households and addresses;
- engineered electric, gas and water networks with equipment;
- IS-U-shaped customers, routes, schedules, AMI and baseline reads.

Outputs and tooling:
- the `utility-town/2.0` snapshot, GeoJSON, parquet, API and CLI;
- complete state frames and replays with sun and moon;
- JSON Schemas and OpenAPI;
- real-place presets from frozen OSM extracts;
- the viewer's receiver conformance in CI.

## M2: time and physics (partly done)

Done:
- **Weather:** a seeded daily weather year (`sim/weather.py`). It drives monthly consumption through degree-days,
  live seasonal demand, frames (`clock.tempC`) and meter-reading conditions.
- **Run-scoped settings** (`x-applies: run`): process, anomalies, reading, VEE, billing and scenario.
- **Field movement:** walker and drive-by reading rounds on the operations day, with trajectories.

Next:
- radial power flow: voltage, loading, losses, reverse flow;
- looped hydraulics: water (HGL, pressure) and gas (P²), to fill today's `null` loop flows;
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
- analyst actions from the viewer.

**Linked:**
- the operations day schedules that day's reading rounds and meter-to-cash field orders as crew jobs;
- a field visit on the map settles the premise's open read cases;
- the map and the worklists share one run day.

Next:
- a two-way connector with the real m2c.vee engine (import dispositions);
- outage-driven exceptions (AMI last gasps, zero use);
- budget billing and payment arrangements.

## M4: product (in progress)

Viewer (Astra's package):
- Worklists page;
- Activity sequences explorer;
- meter-to-cash settings tab rendered from the engine's schema;
- billing tab from the engine;
- daytime outage rings.

Next:
- road hierarchy and utility corridors ([CORRIDOR_ROUTING_REQUIREMENTS.md](CORRIDOR_ROUTING_REQUIREMENTS.md)):
  continuous electric corridors, feeder territories, normally-open ties (which enable back-feed during repairs),
  and corridor exports;
- main roads leaning commercial;
- a visual Activity Sequence builder;
- real-place import from the UI;
- hosted 10,000-home towns (chunked snapshots, precomputed base runs).
