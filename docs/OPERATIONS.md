# Operations and process design (M2–M3)

## Clock

5-minute ticks (configurable) in the town's timezone; hourly flow solves with event-driven re-solves when topology
changes (a valve closes, a switch opens). Every state frame already carries `clock` (local time, `isDay`, sun
elevation/azimuth from the NOAA solar position at the town's origin, moon phase) for the sun/moon widget and scene
lighting. Labels such as "nightly AMI collection" come from `ami.poll_start_hour`–`poll_end_hour` (local), not the
word "night": the window can fall in daylight.

## Field fleet (config group `operations`)

All vehicles start at the depot and drive shortest paths on the road graph at class speeds. The engine emits
**trajectories** (timestamped polylines); the viewer interpolates positions.

| Agent | Behaviour |
|---|---|
| AMR van | drives its route's streets on the scheduled day; reads meters within `drive_by_radius_m` as it passes |
| Walker | visits premises in route `sequenceNo` order at `walker_meters_per_hour`; may log no-access |
| Gas crew | responds to odour calls within the target; makes safe, closes the upstream valve, repairs, relights |
| Electric trouble crew | patrols from the predicted device, isolates, restores via ties, repairs |
| Water crew | isolates a break with N−1 valves, repairs, flushes, restores |
| Meter technician | planned exchanges and investigations |

## Incidents (config group `incidents`)

Each incident is the **initiating event** of a causal chain; its downstream events carry rationale and cost.

| Incident | Physical effect | Process effect |
|---|---|---|
| Gas service/main leak | odour call → crew → valve closed → downstream services at zero flow → repair → relight | post-meter leaks raise consumption → VEE spike |
| Lightning on overhead primary | recloser/fuse trips → subtree outage → AMI last-gasp → trouble calls → OMS predicts device → patrol, isolate, partial restore by tie, repair | zero usage, estimated reads if meters are offline at read time |
| Water main break | pressure drop → crew → valve isolation → repair → flush | outage window, high-bill complaints |
| Transformer failure | 4–10 homes out → replacement (upsized if overloaded) | zero-usage reads |
| AMI collector outage | cluster of comm failures | estimates, consecutive-estimate flags |

Hazard rates are per asset per year; overhead faults happen on storm days (`weather.storm_days_per_year`) and a
transformer loaded above its rating fails three times as often. `manual_only` disables random hazards for scripted
demos. As built (`utilsim/ops/hazards.py`), every operations day draws its background incidents at these rates,
seeded by (town, run seed, date), and works them exactly like a hammer blow; the rates and the on/off switch are
operations run settings whose defaults are the town's values (see CONTRACT.md "Background incidents"). Freeze-thaw
and heat modulation are not modelled yet.

## Meter-to-cash process

The prior Activity Sequence Simulator becomes this layer, anchored to the map: every event references a premise,
device or asset and has a position. Exceptions always go through a work queue (no same-day human resolution;
RPA same/next day), costs are labour/system/CX plus carrying cost per day to invoice. Weather changes volumes and
magnitudes and modulates incident hazards, so it can change a run's event graph (reproducibly for a seed); it never
changes geography or customer identities. Physical state forces sequence selection (an outage produces zero usage
for every premise downstream, a physical state rather than an anomaly; a cold snap raises COMM_FAIL on old AMR
batteries). The event envelope:

`eventId, simulationId, sequence, occurredAt, effectiveAt, eventType, schemaVersion, correlationId, causationId,
entityType, entityId, payload`. `causationId` is the primary causal parent; further causes are listed in
`payload.relatedEventIds`, so the record is a graph. Rationale, cost and edge type ride in `payload`. Events that
share a timestamp are ordered by `sequence`.
