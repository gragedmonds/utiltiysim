# Roadmap

## M1 — town, networks, customers (done)
Configurable seeded towns from OSM or synthetic skeletons with growth; parcels, buildings, households, addresses;
engineered electric/gas/water networks with equipment; IS-U-shaped customers, routes, schedules, AMI, baseline
reads; `utility-town/2.0` snapshot, GeoJSON, parquet, API, CLI; prototype acceptance gates in CI; viewer bridge.

## M2 — time and physics
Clock with sun/moon; seeded weather; consumption from weather; radial power flow (voltage, loading, losses,
reverse flow) and looped hydraulics for water (HGL, pressure) and gas (P²); tank and pump control; nightly AMI
collection; van and walker trajectories; state frames over WebSocket.

## M3 — operations and meter-to-cash
Incidents, OMS, crews; causal event graph with activity sequences and work queues; monthly read cycle with
estimates and exceptions; VEE hand-off to m2c.vee and an internal rule set; billing documents, invoices,
payments, dunning; anomaly injector with ground truth and scoring.

## M4 — product
React viewer in the prototype's style with settings page generated from the config schema, OMS and process
panels; OSM import from the UI; tensor-field road option; chunked snapshots if towns grow past 10,000 homes.
