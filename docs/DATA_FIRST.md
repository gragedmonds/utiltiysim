# Data first: a utility of towns, generated from a specification

*Plan, October 2026. Replaces "scale by bigger OSM extracts" with "specify the utility, synthesise the structure, fit
the geography to it".*

## Why

The engine scales linearly and is fast per account (Cobourg: 6,993 accounts, 26 s to generate, 15 s to replay the
year). What stops it at 100,000 accounts is shape, not speed: one town per run, one process, one year, geometry first.
Today a town starts from a street extract, lots and premises emerge from the roads, districts are Voronoi cells, the
AMI/AMR/manual mix is a town-wide route share, and there is no object above the town. A multi-region utility with a
different blend per town and per street cannot be expressed.

## What stays

- The whole meter-to-cash engine (reads, VEE, queues, billing, invoices, collections, episodes, tables, trend) reads
  only the customer tables and the config. It does not care where a premise is.
- The road machinery already makes sense of synthetic geography: `skeleton: synthetic` builds a warped concession
  grid, `planarize` guarantees a planar road graph (roads meet only at nodes), `road_path` gives distances along
  roads, the land-use stage places lots along frontage, the network builders follow the roads. The pivot reuses all of
  it; it changes what drives it.
- The map stays as a view of one town. It is no longer on the critical path: a utility-level Studio (Year, Data,
  Workspace, Configuration) works with no geometry at all, and a town generated data-first still gets roads and
  premises the isometric map can draw.

## The shape

```
Utility  (name, regions, defaults)
 └─ Region  (state or province: moratorium window, tax, due days, holidays, tariff set)
     └─ Town  (homes, climate, seed, technology defaults)
         └─ District  (core | suburb | rural | commercial | industrial; era; homes; technology blend)
             └─ Street  (name, class, homes, side pattern; technology override)
                 └─ Premise  (house number, lot, household, meters, account, route position)
```

A **utility spec** (`utility-spec/1.0`, YAML or JSON) names all of this, down to the street where the author wants
to, with defaults filling the rest (a town with "homes: 8,000, districts: 9" gets nine districts of plausible kinds and
named streets). Everything below the spec is deterministic from the seed.

### 1. Structure synthesis (no geometry yet)

From the spec: districts → streets with target homes and lengths (homes × frontage, two sides) → premises with house
numbers → households and buildings (the existing `assign_households`) → customers, meters, registers, installations,
contracts, tariffs (the existing `build_customers`) → reading routes as contiguous street runs inside a district, each
about 450 meters, with the technology the spec gives that district or street → portions and read schedules.
This stage alone produces every table the meter-to-cash engine needs, so a utility can be replayed before any map
exists.

### 2. Layout from structure (geometry that fits)

Each district is laid out as a block grid sized from its streets: streets become grid edges with the lengths the
structure asked for, blocks get the lot depth, dead-ends and curvature come from the existing warp. Districts tile a
concession plane around a core; arterials and collectors connect them; `planarize` runs as a check and a tidy, so
roads never intersect except at junctions. Premises take coordinates along their street's frontage. Networks, terrain,
the operations day and the map then run unchanged. Distances exist at three levels: along roads inside a town, between
districts, and between towns (a coarse regional plane with road kilometres, for crews and readers later).

The OSM path remains for demos of real places; it stops being the base.

### 3. The utility layer and sharding

- `GET /api/utility/{id}`: the spec, its regions and towns, each town's status.
- Every town is its own run, cached as today; a container runs them in a process pool (ten towns of 10,000 accounts
  replay side by side in about half a minute; forty towns of 2,500 in less).
- Roll-ups: the trend summed across towns; tables concatenated with a `town` column and the same filters, sorts and
  CSV; the summary KPIs added; worklists merged with a town column (top-N from each shard).
- Episodes gain a scope: utility, region, town, district or street. Region scope carries the state rules (moratorium,
  fees); district and street scopes drive technology and reading factors through per-premise indexes the engine
  already keeps for technology.
- Staffing pools stay per town first; a shared pool across towns is a later engine change.

### 4. Technology blends and rollouts

The blend comes from the spec (district and street), not from a town-wide route share. A rollout episode (AMR to AMI
across a district over months) rides the existing device-exchange machinery with a technology that changes per
register at the exchange date.

### 5. Years

Year two starts from year one's closing state (balances, arrears, open cases, device ages, backlog). Chaining keeps
every array one year wide and every id as it is.

## Guidelines, as tests

- **The world makes sense:** every premise on a street, every street in a district, every district in a town, counts
  equal to the spec; eras and lot sizes coherent within a district; commercial on arterials.
- **Roads never intersect:** the road graph is planar (checked by `planarize` and a test that no two edges cross).
- **Everything has a distance:** road distance between any two premises in a town, straight-line distance everywhere,
  road kilometres between towns.
- **It runs on the engine:** a data-first town is a normal snapshot; the meter-to-cash run, the operations day and the
  map accept it without special cases.

## Order of work

| Step | What | Size |
|---|---|---|
| A | `utility-spec/1.0`, structure synthesis, layout from structure, a first spec (one region, three towns, mixed blends), the Studio loading a spec-built town | about 2 weeks |
| B | Utility object, sharded runs in a process pool, roll-up trend, tables, summary and worklists, a utility picker in the Studio, episode scopes | about 1.5 weeks |
| C | Blends per district and street from the spec, rollout episodes | 3 to 5 days |
| D | The always-on container (needed for B at scale), the no-map boot mode | 2 to 3 days |
| E | Year chaining | about 1 week |

Step A is where the pivot pays or fails: a 10,000-home town specified in a dozen lines, generated in under a minute,
with a planar road graph and the exact counts asked for, replaying its year in the existing engine.
