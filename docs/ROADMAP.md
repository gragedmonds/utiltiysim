# Roadmap

## M1 — town, networks, customers (done)
Configurable seeded towns from OSM or synthetic skeletons with growth; parcels, buildings, households, addresses;
engineered electric/gas/water networks with equipment; IS-U-shaped customers, routes, schedules, AMI, baseline
reads; `utility-town/2.0` snapshot, GeoJSON, parquet, API, CLI; complete state frames and replays (static solver
output) with sun/moon; JSON Schemas and OpenAPI; real-place presets from frozen OSM extracts; prototype acceptance
gates and the viewer receiver's conformance in CI; `web/` handed to Astra (`7dd7cc8`).

## M2 — time and physics
Ticking clock; seeded weather (and run-scoped weather/incident/operations settings, `x-applies: run`);
consumption from weather, including a summer air-conditioning peak; radial power flow (voltage, loading, losses,
reverse flow) and looped hydraulics for water (HGL, pressure) and gas (P²), filling today's `null` loop flows;
tank and pump control; nightly AMI collection; van and walker trajectories; frames over WebSocket
(`?afterSequence=`); the scenario command endpoint.

## M3 — operations and meter-to-cash
Incidents, OMS, crews; causal event graph with activity sequences and work queues; monthly read cycle with
estimates and exceptions; VEE hand-off to m2c.vee and an internal rule set; billing documents, invoices,
payments, dunning; anomaly injector with ground truth and scoring.

## M4 — product
Production viewer (Astra) with the settings page generated from the config schema, OMS and process panels;
real-place import from the UI (`/api/sources` plus a fetch endpoint); tensor-field road option; chunked snapshots
if towns grow past 10,000 homes.
