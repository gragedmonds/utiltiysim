# Recurring household cashflow

`world-customer-cashflow/1` is an optional, administrator-configured extension of
the existing customer finance owner. It models explicit recurring income and
essential spending in integer cents. It does not infer wages, benefits, household
needs, borrowing, bank accounts, enterprise balances, or unpaid-expense debt.
Amounts and cadence are scenario assumptions supplied by the administrator.

Existing `world-customer-finance/1` commands, payment intentions, delivery evidence,
and provider receipts retain their existing contracts. Without cashflow
configuration the new model has no tables, records, or cash effects. Inspecting
cashflow does not enable it.

## Configuration

Configure a customer finance profile first. Submit the following exact command
to `customer_cashflow.command(world, payload)` or the administrator endpoint
`POST /api/customer-cashflow`:

```json
{
  "schemaVersion": "world-customer-cashflow/1",
  "commandId": "household-budget-1",
  "environmentId": "EXAMPLE",
  "runId": "EXAMPLE",
  "worldFingerprint": "use-the-current-world-fingerprint",
  "actorId": "world-admin",
  "expectedRevision": 0,
  "effectiveDate": "2026-01-01",
  "action": "configure",
  "premiseId": "P1",
  "recipientRef": "SIM-HOUSEHOLD-P1",
  "active": true,
  "income": {"amountCents": 100000, "firstDate": "2026-01-01", "intervalDays": 14},
  "essentialExpense": {"amountCents": 5000, "firstDate": "2026-01-01", "intervalDays": 1},
  "insufficientCashPolicy": "available-cash",
  "incomeOverflowPolicy": "skip-with-record",
  "reason": "Explicit illustrative household budget",
  "causalReference": "scenario-budget-1"
}
```

`expectedRevision` is the cashflow configuration revision, independent of the
customer finance cash/reservation revision. `effectiveDate` must equal the
world's next unprocessed day (`through`). Configuration never resets cash.
Recipient and occupied cohort must match the existing finance profile. A
replacement household cannot inherit or reconfigure the old household's policy.

All money fields are integers from zero through 1,000,000,000,000 cents; boolean
and fractional values are rejected. Zero disables the corresponding stream.
Cadence is 1 through 366 whole UTC calendar days, inclusive of `firstDate`.
It is not a calendar-month, payroll, holiday, or business-day convention.

A new anchor must be on or after `through`. An existing historical anchor may
remain unchanged when editing amounts, interval, funding policy, or activity.
Changing an interval with the original anchor changes future occurrences only:
elapsed days from that anchor must divide evenly by the new interval. Historical
days are immutable. An alternative new future anchor explicitly restarts cadence.

The cashflow `active` switch is independent of customer finance's `active`
payment-intention switch. Pausing utility payment decisions does not pause income
or essentials. Pausing cashflow skips its occurrences without accumulating later
catch-up payments, income, or debt.

## Daily ordering and conservation

Each physical day, before new utility payment decisions:

1. Check the original recipient/cohort, occupancy, and cashflow activity.
2. Credit due income. If the entire deposit would exceed the cash limit, skip the
   entire deposit and record `cash_limit`; the day continues. This check happens
   before spending, even if that spending would have created room for income.
3. Fund due essentials from cash minus already reserved utility-provider money.
   `available-cash` pays as much as available; `all-or-nothing` pays only when the
   full expense is available. Record the unfunded remainder without creating debt.
4. Existing finance logic may create utility payment intentions using the updated
   cash, actual delivered invoices, and the existing essential-reserve floor.

Essentials may spend the `essentialReserveCents` payment floor: that floor
protects money for essentials from utility intentions. Essentials cannot spend
money already reserved by a pending provider intention. Cash remains nonnegative,
at least reserved cash, and within the existing upper bound. Income or expense
movement advances the finance revision even if their net cash change is zero.

Settled, returned, and terminal-failed provider receipts retain their finance
semantics. A failure releases the unspent reservation; it does not reimburse
essentials or duplicate income. Old receipts remain reconcilable after a cohort
change, without enabling cashflow for the replacement occupant.

## Replay, recovery, and inspection

First activation saves a consistent pre-migration SQLite backup and records its
path as `customerCashflowRollbackBackup`. Configuration, event, and receipt writes
are atomic. The cashflow effects, daily record, payment decisions, and physical
day commit share the existing daily transaction. An interrupted day rolls back
all these effects; restarting applies the day once. Exact command retry returns
the original receipt even after time/cohort changes. Reusing its ID with changed
content is rejected. World/run identity is always checked.

`customer_cashflow.inspect(world, premise, before=None, limit=25)` and
`GET /api/customer-cashflow?premise=P1` expose administrator truth. They must not
be surfaced as worker/customer observation or exported as enterprise evidence.
The result includes `financeConfigured`, `configured`, `cohortBlocked`, current
cash/reserved cash, policy, configuration revision, and descending daily history.
Initial cashflow configuration is allowed when finance is configured and the
cohort matches; `configured=false` alone does not forbid it.

History contains every processed configured day, including `paused`, `vacant`,
`cohort_changed`, and `no_occurrence` days. Each record includes due/credited/skipped
income, due/paid/unfunded expense, opening/closing/reserved cash, policy revision,
per-stream statuses, and a causal event ID. The underlying event retains that
day's policy, so subsequent edits do not rewrite the explanation.

History is indexed by premise/day and bounded to 25 records by default, at most
100 for direct callers. Pass `nextBefore` back as the exclusive `before` date
cursor to read older records. The storage retains history; the bounded limit is
an inspection limit rather than deletion or automatic retention policy.

Focused tests cover cadence and ordering, both funding policies, protected
reservations, independent switches, overflow, cohort changes, exact retries,
atomic interruptions, absent-feature compatibility, and paged restart equivalence.
This is a local household-cash model, not enterprise billing or payroll acceptance.

## Verified desktop and cohort scenarios

The 9 October 2026 focused run passed 72 combined cashflow/finance tests and 12
HTTP tests. The desktop checker `scripts/check_world_customer_cashflow.py`
uses a separate copy of a 570-premise town. At 1440- and 960-pixel widths it
verified exact cent inputs, rejection of excess precision, a lost-response retry,
pause, process restart and 25/9-record history pages. Across 34 days it preserved
the original $40 payment reservation and recorded unfunded expenses without
creating debt. Source data and prior observations were unchanged; there were no
JavaScript errors or external requests. Local evidence and screenshots are in
`out/customer-cashflow-browser-verified/`.

A separate 300-cohort, 60-day diagnostic produced 18,000 cashflow records per
world. An uninterrupted run and a run reopened after 30 days matched across
twelve domain-table digests, including 98,280 physical truth records and matching
observations. Credited income of 2,516,700 cents minus paid expenses of 1,258,440
cents exactly matched the aggregate cash increase. Three overflow days skipped
3,300 cents of income; fifteen shortfall days recorded 1,560 unfunded cents.
Source-pack and static-map hashes were preserved.

Configuration took 118.196 and 100.378 seconds respectively; physical advancement
took 35.277 and 42.231 seconds. Total diagnostic elapsed time was 307.589 seconds.
These are local component timings: repeated individual profile configuration is
still a material cost for larger scenarios. The fixture created no invoices,
payment intentions or enterprise transactions. Evidence is saved in
`out/cashflow-cohort-acceptance/result.json`; this is not the 15,000-account,
five-year integrated acceptance run.
