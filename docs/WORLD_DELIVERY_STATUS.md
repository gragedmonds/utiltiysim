# Living-world delivery status

Owner: `greg-gpt-listener`. Updated 9 October 2026. The continuation base merged
as `38cd7617` through public [PR #73](https://github.com/gragedmonds/utiltiysim/pull/73)
after local and GitHub CI checks passed. Its original wizard draft, PR #62, is
also recorded as merged; the source branches are retained.
Household cashflow merged as `d12f41d6` through public
[PR #74](https://github.com/gragedmonds/utiltiysim/pull/74). The next combined
candidate is on `greg/world-notice-reactions` and includes notice reactions,
guided staffing refinements, the opt-in managed field adapter, a resumable scale
preflight and a [capabilities/design handoff](UTILITYSIM_CAPABILITIES.md).

This record separates implemented local behavior from outstanding integration.
An idle coordination channel is not evidence that this backlog is complete.

## Current candidate

| Area | Working behavior | Remaining boundary |
| --- | --- | --- |
| Guided setup | Quick and Full configuration, retained values/pins, validated creation and exact retry; candidate size-scaled district staffing preserves manual/imported/pinned settings | Broader operational calibration; suggestions do not configure shared field workers |
| Travel estimates | Saved-road round trips for water and sewer premise visits; explicit selected work-site access for network-edge planning | A quote does not reserve a worker, establish the physical location, authorize execution or consume shared time |
| Provider failure | Versioned terminal failure evidence releases unspent reserved customer cash exactly once; no settlement/refund/debt reduction is invented | Actual provider and enterprise recipient adapters, partial amounts, enterprise reconciliation |
| Household cashflow | Explicit recurring income and essential spending, protected payment reservations, shortfall evidence, cohort isolation and atomic daily replay | Calibrated household/business economics and actual employer/provider integration |
| Financial-notice reactions | Candidate payment-help intentions after an actually delivered notice for known due debt, using available cash and persistent repeat limits | Actual document-delivery and contact-center recipient wiring; no automatic enterprise arrangement |
| Managed field | Candidate downstream-water repair bound to authenticated existing Run jobs and full-trip reservations, shifts/skills, next-boundary effects and recovery | Private principal/resource agreement and recipient wiring; remaining operations and overnight shifts |
| Storm scenarios | Dated temperature and utility-risk effects, explicit cancellation before start, shared daily transaction and causal fault history | Geographic storm tracks, wind/rain/flood physics, weather-dependent travel and staffing |

The existing local field model retains finite daily capacity, distinct physical
results and submitted reports, staged main work, and cancellation/replacement.
Storm completion does not repair faults or close business work. Provider failure
does not acknowledge transport or erase the historical payment intention.

## Integration still required

1. Wire the tested public managed-field contract into the agreed private
   principal/resource/recipient composition, then extend beyond its initial
   downstream-water repair scope. Preserve full-trip reservations, shift fit,
   calendars, capacity, cancellation, next-boundary effects and independent
   field/world recovery. See [managed field](WORLD_FIELD_MANAGED.md).
2. Connect actually delivered enterprise invoices to explicitly bound recipients,
   then route confirmed provider outcomes to independently retried world and
   enterprise transactions. Transport acceptance is not delivery or settlement.
3. Connect authorized dispatch, acknowledgments, submitted reports and enterprise
   acceptance/rework. A completion claim must not fabricate physical repair or
   bypass operation-specific evidence checks.
4. Connect the candidate financial-notice reactions and extend moves, richer household
   economics and service creation for new development through their corresponding
   owners. Recurring income and essential spending are now local scenario inputs;
   they do not establish actual financial-document delivery or enterprise debt.
5. Finish authenticated worker/AI operations with bounded knowledge and budgets.
6. Execute the twelve integrated acceptance scenarios and the 15,000-account,
   five-year benchmark. Small fixtures and individual component timings do not
   establish this acceptance.

## Reproduce local verification

The continuation base passed all **1,150 non-slow Python tests** in 1,315.58
seconds. Ruff, **301 viewer tests** and **11 viewer-conformance checks** passed.
The Python run emitted six existing Starlette/httpx deprecation warnings. The
cashflow increment passed **1,194 non-slow Python tests** in 1,191.33 seconds,
with three existing Starlette/httpx deprecation warnings. Its focused checks
passed 72 combined finance tests and twelve HTTP tests; Ruff, 301 viewer tests,
11 conformance checks and desktop acceptance also passed.

The 9 October candidate has independent code review and fresh desktop acceptance
for storm controls and water/sewer/network travel estimates. The travel check
preserves both owner databases byte for byte. Storm recovery tests demonstrate
the effect of five versus seven crews while preserving the distinction between
physical work and submitted reports. A seven-day, 5,864-premise diagnostic also
preserves source/map hashes and the completed database across restart. These
component results do not close the integrated acceptance or scale work above.

Household cashflow also passed a 300-cohort, 60-day conservation/restart comparison:
18,000 daily records per world and matching digests across twelve domain tables.
See [the cashflow contract and timings](WORLD_CUSTOMER_CASHFLOW.md).

The subsequent notice candidate passed 50 focused tests and desktop checks for
delays, pause/restart, pagination and uncertain delivery. Guided staffing passed
19 focused tests and a 117-page desktop setup/persistence check. Managed field
passed 127 focused existing/new field cases and actual shared-runtime acceptance
on 570 premises, including repair, cancellation, lost acknowledgement/retry,
delayed report and DST. These counts overlap broader suites and must not be
summed as independent coverage. The combined regression is recorded separately
after completion.

The physical-only scale preflight reached 38 days for two independent districts
containing 15,892 source accounts, with integrity/source/replay checks passing.
It stopped at its ten-minute budget; the five-year integrated target remains
unfinished. [The acceptance ledger](WORLD_ACCEPTANCE_MATRIX.md) records all
twelve scenario gaps and the benchmark's actual boundary.

Use the normal repository regression checks in `CLAUDE.md`. Focused suites are
`tests/test_world_customer_finance_failures.py`, `tests/test_world_field_travel.py`,
`tests/test_world_storms.py`, `tests/test_world_storms_http.py` and
`tests/test_world_storm_recovery.py`.

The desktop checkers use fresh output directories and preserve source packs:

```powershell
python scripts/check_world_storms.py --engine-python .venv/Scripts/python.exe --out out/storm-browser
python scripts/check_world_field_travel.py --engine-python .venv/Scripts/python.exe --out out/travel-browser
```

Run the checkers with a Python environment containing Playwright. Each starts
and closes its own local engine, saves screenshots and writes `result.json`.
They require no paid CI or live enterprise/payment connection. See the feature
documents for exact contracts and intentionally unsupported behavior.
