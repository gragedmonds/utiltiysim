# Requirements

Status: **Done** (M1, tested), **Next** (designed, M2/M3), **Later** (M4).

## Town and geography

| ID | Requirement | Status |
|---|---|---|
| G1 | Same seed + config + generator version reproduce the town byte for byte | Done (`test_byte_identical_regeneration_and_seed_sensitivity`) |
| G2 | Towns of 20–10,000 homes; 10,000 generate in < 60 s (target 30 s) | Done (~27 s on the reference container) |
| G3 | OSM-inspired streets: a frozen extract (default Whitby, SHA-verified) or fully synthetic; never claims to be real | Done |
| G4 | Towns larger than the extract grow era-appropriate synthetic districts around it | Done (`expansion: grow`) |
| G5 | Coherent eras: pre-war grid core, post-war loops, modern cul-de-sac courts, with matching lot sizes | Done |
| G6 | Houses sit on parcels; buildings carry footprint, height, storeys, roof, rotation for 3D | Done |
| G7 | Land use: commercial strip, schools, industry, parks, utility sites (substation, pump station, tank, city gate, depot) | Done |
| G8 | Addresses unique per street, numbered away from the centre, odd/even by side | Done |
| G9 | Every assumption configurable with bounds, units and declared knock-on effects | Done (`docs/CONFIG.md`) |

## Utility networks

| ID | Requirement | Status |
|---|---|---|
| N1 | Electric, gas and water each connect off-map supply → station → mains → services → every meter | Done (validator, trace tests) |
| N2 | Bigger mains feed smaller ones; capacity ≥ diversified design load everywhere | Done (step tables + monotone pass) |
| N3 | Electric: substations, feeders, 1φ laterals with balanced phases, pole/pad transformers, overhead/underground by era, poles, ties, reclosers, fuses | Done |
| N4 | Gas: city gate, MP mains with service regulators, legacy LP core behind district regulators, loops, valves; all-electric districts have no gas | Done |
| N5 | Water: pump station, elevated tanks, pressure zones with PRV/booster, loops, hydrants, valves; fire flow governs size | Done |
| N6 | Homes with solar export; reverse flow appears on services, transformers and (at high penetration) the town | Done (flow tests) |
| N7 | Pressure, voltage and head-loss solves (radial sweep, looped Newton) | Next (M2) |

## Customers, reads, billing

| ID | Requirement | Status |
|---|---|---|
| C1 | IS-U-shaped customer stack per premise in the prototype's id grammar | Done |
| C2 | Contract history (owners, rentals, previous tenants, vacancies); moves never create premises | Done |
| C3 | Separate import/export registers; never a negative consumption | Done |
| C4 | Meter reading routes (AMI/AMR/manual), portions, schedules on Ontario business days | Done |
| C5 | Baseline monthly reads that reconcile with register endpoints | Done |
| C6 | VEE fixtures (actual/stuck/missing/spike) with truth kept separate | Done |
| C7 | Monthly read → VEE → work queue → billing documents → invoices → payments → dunning | Next (M3) |
| C8 | Anomaly injector with ground truth and VEE scoring | Next (M3) |

## Simulation and operations

| ID | Requirement | Status |
|---|---|---|
| S1 | Live clock with day/night (sun/moon), 5-minute ticks, scenario presets | Partly (scenarios + flows done; clock/astro in M2) |
| S2 | Weather series drives magnitudes, never process structure | Next (M2) |
| S3 | Nightly AMI collection; AMR vans and manual walkers moving along routes | Next (M2) |
| S4 | Incidents (gas leak, lightning, main break, transformer failure, collector outage) with crews, OMS, isolation and restoration visible on the map | Next (M3) |
| S5 | Causal event graph: every event has an initiating event, rationale and cost | Next (M3) |

## Non-functional

| ID | Requirement | Status |
|---|---|---|
| X1 | Snapshot is a superset of the prototype's `utility-town/1.0` | Done (schema test) |
| X2 | Viewer snapshot ≤ ~10 MB gzipped at 10,000 homes | Done (≈ 6 MB `viewer`, ≈ 10 MB `full`) |
| X3 | Test suite runs in CI on every push | Done |
