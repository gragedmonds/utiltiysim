# Operations and process design (M2–M3)

## Clock

5-minute ticks (configurable) in the town's timezone; hourly flow solves with event-driven re-solves when topology
changes (a valve closes, a switch opens). The clock endpoint returns local time, `isDay`, sun elevation/azimuth
and moon phase for the sun/moon widget and scene lighting.

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

Hazard rates are per asset per year and modulated by weather (storm days, freeze-thaw, heat); `manual_only`
disables random hazards for scripted demos; `POST /api/sim/{id}/incidents` injects one.

## Meter-to-cash process

The prior Activity Sequence Simulator becomes this layer, anchored to the map: every event references a premise,
device or asset and has a position. Exceptions always go through a work queue (no same-day human resolution;
RPA same/next day), costs are labour/system/CX plus carrying cost per day to invoice. Weather changes volumes and
magnitudes, never sequence structure. Physical state forces sequence selection (an outage produces ZERO_USAGE for
every premise downstream; a cold snap raises COMM_FAIL on old AMR batteries). The event envelope:

`eventId, simulationId, sequence, occurredAt, effectiveAt, eventType, schemaVersion, correlationId, causationId,
entityType, entityId, payload` (`causationId` is the causal parent; rationale, cost and edge type ride in
`payload`).
