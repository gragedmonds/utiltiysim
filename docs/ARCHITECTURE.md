# Architecture

```
L0 Config & seeds   SimConfig (Pydantic) · stage RNG streams · counter-based hash_u01 per entity
L1 Physical         terrain → roads (synthetic skeleton) → land use → parcels → buildings → households → addresses
L2 Networks         split street graph at taps → class-weighted forest from sources → prune → aggregate → size → equipment
L3 Customers        business partners, accounts, contracts (history), installations, meters, registers, routes, AMI
L4 Time & flow      (M2) clock, astronomy, weather, consumption, power flow / hydraulics, nightly AMI collection
L5 Operations       (M3) incidents, OMS, dispatch, crews and vans on roads, isolation and restoration
L6 Process          (M3) reads → VEE → queues → billing → invoices → payments, causal event graph, anomalies
API / export        FastAPI, utility-town/2.0 snapshot, GeoJSON, parquet, PNG
```

Code map: `utilsim/config` (L0), `utilsim/gen` (L1), `utilsim/net` (L2), `utilsim/customers` (L3), `utilsim/sim`
(flows now, L4 next), `utilsim/process` (fixtures now, L6 next), `utilsim/io` (exports), `api/` (service),
`utilsim/gen/pipeline.py` (orchestration and stage timings), `utilsim/validate.py` (invariants).

## Determinism rules

* Stage streams: `stage_rng(seed, "roads", "arterials")` (SeedSequence → PCG64). One stream per stage or sub-stage.
* Per-entity draws are counter-based: `hash_u01(seed, Purpose.X, key…)` keyed by content-derived uids, so a
  household's attributes do not change when unrelated houses are added.
* Never iterate Python sets of strings, never rely on GEOS output order (geometries are sorted before ids are
  assigned), quantise coordinates to 1 cm at stage boundaries, break shortest-path ties with a hashed epsilon.
* OSM topology is authoritative: OSM endpoints are never snapped together unless identical; grade separation
  follows shared nodes.
* `town_id = blake2b(canonical generation config + generator version)`. Bump `GENERATOR_VERSION` whenever outputs
  may change (including a numpy/shapely/GEOS upgrade).

## Performance (reference container)

| Preset | Homes | Generate | Snapshot (gz, full / viewer) |
|---|---|---|---|
| `village` | 480 | ~3 s | 0.7 MB |
| `small_town` | 1,900 | ~9 s | 2.3 MB |
| `city` | 10,000 | see the engine guide | |

Hot paths are vectorised (lot clipping, ray-cast depth limits, elevations, tree aggregation). The remaining cost is
per-lot de-overlap and per-piece offset geometry; both parallelise by district if needed.

## Why one engine

The prototype recommends "a single generation service and a versioned immutable snapshot consumed by the viewer
and simulation workers". Porting the JavaScript generator bit-for-bit across languages buys nothing; instead the
engine is authoritative and the viewer consumes its snapshot. The viewer's demand shapes are reproduced exactly so
flows agree at every instant.
