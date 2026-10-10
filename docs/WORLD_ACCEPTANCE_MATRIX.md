# Integrated acceptance and scale work

This is the acceptance ledger for the twelve platform scenarios, not a claim
that twelve passing financial unit tests establish platform completion. Updated
9 October 2026 against public PRs #73 and #74, and the subsequent
notice/staffing/managed-field candidate. The private requirements baseline
is the source of the SCN identifiers and their end-to-end outcomes.

**No complete cross-system scenario or five-year integrated benchmark is marked
passed here.** Existing component evidence is useful, but missing receivers,
shared execution, or customer behavior cannot be replaced by assertions against
invented enterprise state. A fixture callback is labeled as such.

## Scenario ledger

| Scenario | Implemented and tested components | Remaining end-to-end acceptance |
| --- | --- | --- |
| SCN-001 Hidden leak | Persistent physical water leak; consumption changes; observation-only export; local investigation-bound assignment, physical repair, and separately delayed report | Detect through actual enterprise observations, create authorized work, reserve shared workforce/travel, deliver and accept the report, and show that each owner learns only through its interface |
| SCN-002 Broken meter / repeated zero | Meter failure/observation gaps; physical replacement; enterprise reading validation and billing dependencies | Zero-read escalation over repeated cycles, analyst history review, authorized reread/exchange with shared field capacity, and subsequent billing release. The world's default failed-meter output is missing, not automatically a zero-read scenario |
| SCN-003 New 500-home subdivision | Saved vacant properties can progress through construction, commissioning and occupancy; filtered service notices can be delayed | Actual new subdivision geometry/services and 500-home operational onboarding; account/meter work, billing, contact and field demand after each dependency. Reusing a few existing vacant premises is not this scenario |
| SCN-004 Major weather event | Dated temperature/risk stress; correlated four-domain faults; causal symptom contacts; finite local crews and recovery | Weather-dependent travel and staff availability, authorized enterprise work creation, shared reservations, and a measured end-to-end backlog/recovery curve |
| SCN-005 Billing batch failure | Shared runtime jobs, dependencies, pause/retry; enterprise bill/invoice transactions and failure recovery | Schedule the real overnight batch, demonstrate stranded daytime work and growing unbilled population, recover it, and measure resulting delivered invoices, customer responses and operational load |
| SCN-006 Payment processor failure | Delivered invoice knowledge; cash reservations; explicit terminal provider failure, settlement and full return; notice-reaction candidate | Durable actual document delivery, authenticated provider adapter, independently retried world/ledger consequences, wrong/pending enterprise balances, collections/calls and reconciliation. Lost transport acknowledgment is not provider failure |
| SCN-007 Rate increase and call demand | Versioned enterprise pricing; world reacts to delivered notices and inability to fund a known due invoice in the current candidate | Effective-date rate change through actual bills/delivery, segment-specific high-bill inquiries/disputes/arrangement requests, and real call-center work. Payment-help notices alone do not model rate-increase reactions |
| SCN-008 Disconnect with continued usage | Existing enterprise disconnect/service-order controls; separate physical consumption and observations | Explicit permitted physical disconnect outcome, continued-use detection from observations, investigation/rework and eventual reconciliation. An enterprise status must not silently force physical truth |
| SCN-009 Physical work without recorded completion | Manual reporting; completed physical repair can remain unreported; false reports do not repair assets; field/world crash recovery | Actual recipient handling and enterprise process held open despite repaired physical state, followed by authorized reconciliation and operation-specific acceptance. A test inbox receipt is not enterprise closure |
| SCN-010 Seven staff versus five | Local fixed-workload comparisons show different completion days under finite daily capacity | Same incoming workload and shared conditions, full hourly/shift/travel reservations, backlog age and downstream bill/contact/collection consequences; compare the complete integrated run |
| SCN-011 Veteran versus new hire | Existing Studio workforce/productivity assumptions; field operation time assumptions and explicit manual misreporting | Bind per-worker skill/speed/error profiles to the durable shared execution path; compare equivalent work and measured rework, without equating a planner's staffing suggestion with execution capacity |
| SCN-012 Move-in / move-out | Dated physical occupancy and cohort isolation; enterprise first/final-reading lifecycle components | Actual customer contact through account/service actions, four-domain first/final reads and bills, and persistent stuck states when required actions are missing |

## Evidence already available

These checks establish their stated component boundary only:

- [World operations acceptance](WORLD_PARALLEL_ACCEPTANCE.md): separate world and
  field stores, trusted test invoice delivery, local repair, customer cash and
  development. Month-long uninterrupted/reopened comparisons preserve nineteen
  domain-table digests.
- [Manual physical visits and reports](WORLD_FIELD_REPORTING.md),
  [water-main phases](WORLD_FIELD_WATER_MAINS.md), and
  [cancellation](WORLD_FIELD_CANCELLATION.md): physical work, submitted claims and
  report delivery remain separate, including crash recovery and replacement work.
- [Travel](WORLD_FIELD_TRAVEL.md): saved-road quotes and selected network work
  sites are read-only. They do not prove an accepted booking or consume time.
- [Managed field](WORLD_FIELD_MANAGED.md): the opt-in downstream-water repair
  adapter has passed isolated acceptance against actual runtime authentication,
  jobs, reservations, cancellation and calendars. One repair and one cancelled
  visit, lost-acknowledgement retry, delayed reporting and DST checks passed on
  570 premises against runtime revision `0b52c868`. This does not connect the
  private recipient or establish every field operation's shared execution.
- [Storms](WORLD_STORMS.md): dated physical stress and recoverable causal events;
  a 5,864-premise seven-day diagnostic is larger-town component evidence.
- [Customer cash](WORLD_CUSTOMER_FINANCE.md),
  [recurring cashflow](WORLD_CUSTOMER_CASHFLOW.md), and
  [notice reactions](WORLD_CUSTOMER_NOTICES.md): bounded customer knowledge,
  exact cents and reservations, explicit provider outcomes, and independently
  delayed contact intentions. Their fixture delivery is not a live enterprise
  document or call-center adapter.

The public continuation passed 1,150 Python tests and its four desktop packages
were published through PR #73. Cashflow passed an expanded 1,194 Python tests,
301 viewer tests, eleven conformance checks, desktop acceptance and a 300-cohort,
60-day comparison. Later candidate test results must be recorded separately;
these historical counts are not the count of an untested later revision.

The physical scale preflight used two distinct towns containing 15,892 source
accounts and 14,288 premises. Its ten-minute budget stopped after 38 days per
world (607.68 seconds including final checks), with 1,459,080 truth rows and the
same number of observations. Both SQLite integrity checks, source hashes and
completed-boundary replay checks passed. Database sizes were 525,066,240 and
184,205,312 bytes; indexed latest-day 25-row queries took about 0.30/0.34 ms.
This was a development preflight, not a frozen integrated release benchmark.
The 1,826-day target was **not reached**. Evidence is retained locally under
`out/scale-15892-accounts/`; no throughput extrapolation is counted as a pass.
The [compact evidence record](WORLD_SCALE_PREFLIGHT_2026_10_09.json) preserves
source identities/hashes, budgets and actual results without committing large
synthetic snapshots or owner databases. It explicitly records that no exact
frozen implementation fingerprint was captured for this development invocation.

## How to close a scenario

Each scenario needs a fresh output directory and a manifest recording exact
public/private revisions, source snapshot hashes, configuration, seed, roles,
clock/calendar, recipient bindings and enabled adapters. Preserve original
checkpoints and credentials; credentials do not belong in public artifacts.

Record observable assertions at each ownership boundary: physical occurrence,
available observation, recipient acceptance, authorized enterprise transaction,
accepted runtime job/reservation, physical execution, submitted report and
enterprise disposition. Link original message/job/receipt IDs. Never substitute
an administrator's view of physical truth for a worker's allowed observation.

Exercise interruption after a sender commit and after a recipient commit with a
lost reply, reopening both owners and retrying the original identity. Verify
exactly one business effect, preserved pending work, no changed message payload,
and a balanced financial journal where money is involved. Delay tests must show
that future knowledge is unavailable before its timestamp.

For comparative staffing/worker scenarios, use the same external demand, fault
seed and assignments. Change only the stated workforce policy and preserve all
other inputs. Measure completed work, backlog and age, travel/work time, missed
reports/rework, billing delay and relevant customer contacts. State which
outcomes are unsupported rather than assigning zero to an unimplemented metric.

## Reproducible physical scale preflight

`scripts/benchmark_world_scale.py` is a first layer of the scale work. It accepts
one or more **distinct saved full snapshots**, counts actual source account
records, creates separate world namespaces and advances their existing daily
transactions. It does not slice/remap saved geography or fabricate account rows
to hit a target.

Example with two distinct source snapshots:

```powershell
python scripts/benchmark_world_scale.py --snapshot first.json.gz --snapshot second.json.gz --out out/scale-fresh --days 1826 --minimum-accounts 15000 --max-seconds 600 --max-gib 20
```

The output directory must be new. To continue a stopped measurement, repeat the
same sources, start date, account target and duration with `--resume`. The saved
plan verifies source paths and hashes before opening the worlds. Budgets can be
adjusted explicitly on a subsequent invocation. A running lock prevents overlap;
after an interrupted process, inspect the recorded PID before removing that
specific stale lock. The script never removes a source or resets a database.

The time/storage/free-space budgets are checked between complete daily
transactions. They can be exceeded by one transaction and by final integrity
checks; they are not a hard kill timer. Each completed district-day appends a
timing/storage measurement. The final result records completed days, stop reason,
source hashes, SQLite integrity, expected observation/truth row counts,
completed-boundary replay, and an indexed 25-row observation query.

`targetReached=false` is an unfinished run. Even `targetReached=true` means only
that this **physical-layer** target was reached. The result deliberately retains
`integratedAcceptance=false`: these source accounts are not onboarded enterprise
customers, the districts have independent worlds rather than one shared utility
clock, and bills, payments, calls, field jobs, workforce and AI are not exercised.
Completed-boundary replay also does not establish arbitrary interrupted
cross-system recovery. Five years means the actual requested daily transactions
completed, never a short-run throughput extrapolation.

## Integrated scale gate still to run

After the receiver and shared execution seams are connected, the integrated
benchmark must retain at least the intended approximately 15,000 active customer
accounts, their service/contract cardinalities and all twelve scenario workloads
for the full five-year horizon. Source account count and occupied premise count
are different metrics; neither can replace proof of actual enterprise onboarding.

Report setup time separately from advancement, database/storage growth by owner,
latencies for bounded application queries, read/bill/contact/order volumes,
staff backlog, checkpoint size/time, recovery time, and any provider/model cost.
Verify limited-knowledge worker access and budget exhaustion where AI is enabled.
Keep monthly/yearly checkpoints, source/configuration hashes and scenario event
lineage so the observed totals can be reproduced and compared. A physical-only
load result is a prerequisite measurement, not a waiver of these gates.
