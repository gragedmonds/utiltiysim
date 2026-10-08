# World operations: combined acceptance

This increment joins three independently developed world components to the
existing daily runtime. All three are opt-in and use real commands behind their
screens. Existing town geometry, earlier observations and other demos are kept.

| Component | Working behavior | Boundary still outstanding |
|---|---|---|
| Customer cash | Delivered invoice knowledge, cash constraints, seeded payment intentions, reservations, simulated settlements and full returns | Actual enterprise invoice delivery and payment-provider adapters; partial receipts and broader household income models |
| Development | Saved vacant property progresses through construction, commissioned services and dated occupancy; pause/failure retains unfinished work; delayed service notices | New parcels/network construction and enterprise service/account creation |
| Field execution | Explicit separate store, plumbing crews, weekday availability, finite daily visits, assigned repair, durable reports and crash recovery | Hourly travel/reservations, remaining utility operations and enterprise dispatch/acceptance integration |

The local screens are administrator scenario controls, not worker authentication
or SAP replicas. Invoice and order references in the acceptance scenario are
explicit test fixtures. Receiving a transport acknowledgment never closes an
enterprise order or posts a financial journal.

## Launch on an existing initialized world

```powershell
python -m utilsim.world.server --db out/demo/world.sqlite --field-db out/demo/field.sqlite --port 8042 --viewer-dir packages/town-viewer/dist
```

Use a fresh directory and a SQLite backup of a world for experiments. Do not
point a field store at the world database or another application's database.
Initialization rejects unrelated existing stores without changing their contents.
Reopening the same field store requires its original world identity.

Open `/customer-finance`, `/development` and `/field-execution` from the world
controls. The original server command remains valid without `--field-db`; field
actions then return a configuration error. The cash screen has no pretend
invoice-delivery or payment-settlement buttons: those inputs require the trusted
adapter functions documented in WORLD_CUSTOMER_FINANCE.md.

Before advancing a physical day, run that day's due field visits. Development
and customer behavior then advance with the world. Multi-day world advance does
not secretly schedule field visits on intermediate days. A coordinator that
alternates these owners remains necessary for unattended integrated field runs.

## Repeat the combined desktop check

Install the repository dependencies and Playwright/Chromium in the verification
environment, then run:

```powershell
python scripts/check_world_parallel_ui.py --db SOURCE.sqlite --viewer-dir packages/town-viewer/dist --out out/parallel/new-browser-run
```

The script requires a town with an occupied water service and a saved vacant
water-served property. It refuses an existing output directory, backs up the
source, starts an ephemeral local server, and saves screenshots and
`acceptance.json`. It never connects a real invoice provider or enterprise
recipient.

The 8 October 2026 run on a 608-property neighborhood established:

- Customer configuration alone produced no payment. Delivered test invoice
  evidence allowed a $40 intention; settlement spent cash; a full return restored
  the $105 balance and the $90 known debt. Later due behavior could reserve again.
- One crew with one visit per day completed one repair while the second
  assignment remained waiting. Repair affected the physical leak before its
  delayed report became available. A later visit correctly found no remaining
  leak rather than inventing a second repair.
- A development command survived a lost HTTP reply and retry. A paused project
  did no construction work while time advanced. Resume progressed through
  readiness and occupancy, with separately delayed notices.
- All three screens operated at 1440 and 1024 pixels without horizontal page
  overflow, browser errors, unexpected external requests or replacement-character
  text corruption. Screenshots were visually inspected.
- Source database bytes, existing observation exports and saved map geometry
  remained unchanged.

## Recovery and invariants

Release checks passed: 813 tests in the full non-slow Python run; 53 final
field/HTTP tests after the late acknowledgment-ordering correction; 291 viewer
tests; 11 viewer conformance checks; three field-form JavaScript regressions;
repository Ruff, JavaScript syntax and whitespace checks. The full run reported
only the existing Starlette/httpx deprecation warning. The final 53-test selection
includes the new HTTP coverage and three added ordering cases; it is reported
separately rather than pretending the initial full run included later additions.

Focused tests cover financial reservation/settlement/return conservation,
occupancy-cohort changes, replayed commands and receipts, day rollback,
development reservation bypass attempts, service-notice checksums and availability
cursors, derived sewer provenance, physical-commit/field-store interruption,
capacity recovery and protection of unrelated databases. The shared occupancy
transaction helper lets development update occupancy atomically without allowing
a caller to forge internal development context.

SQLite owns these world/field components. No PostgreSQL code or private
enterprise schema changed in this increment. PostgreSQL acceptance belongs to
the future enterprise adapters; SQLite success does not establish it.

No entire plan milestone is marked complete by these slices. Four-domain field
work, the twelve integrated acceptance scenarios, authenticated AI operations,
SAP fidelity and the five-year 15,000-account benchmark remain open.

## Month-long combined replay

```powershell
python scripts/check_world_parallel_replay.py --db SOURCE.sqlite --out out/parallel/new-replay --profiles 300 --days 31
```

This checker initializes fresh daily/uninterrupted worlds from the source's
saved snapshot and start date; it does not copy historical customer state. It
uses explicit test invoice delivery, refuses existing output, and records
table hashes, query plans, counts and timing separately from setup. A portable
three-profile/five-day smoke also passed after packaging this command.

An additional 31-day run used an existing 608-premise / 1,758-asset snapshot,
300 configured customer profiles and delivered test invoices, and 18 saved
vacant-property developments. Observation delivery included derived sewer.
A daily run reopened after day 15 matched an uninterrupted copy across 19
table digests, including registers, observations, events, commands and outboxes.

The run recorded 53,458 observations, 9,300 customer decisions, 300 reserved
payment intentions and 32 service notices. Sixteen sites became occupied; one
explicitly failed site remained pending and another correctly waited for its
saved October commissioning date. All requested five-row pages stayed bounded;
the service feed used its availability index without a temporary sort.

On the Windows development host while the full suite ran concurrently, daily
processing totaled 38.86 seconds (mean 1.25, median 0.96, maximum 5.07 seconds).
The uninterrupted comparison took 39.17 seconds. The 600 public configuration/
document calls took 62.45 seconds separately. These are diagnostic timings under
contention, not calibrated performance guarantees. No provider settlements,
fault workload or live enterprise recipient participated in this replay.
