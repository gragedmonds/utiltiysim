# Meter-to-cash (M2C)

Reads, VEE, exception work queues, billing, invoicing, payments and collections for every premise, replayed by the
engine for calendar 2026.

## Run model

A run is stateless and deterministic: `(town, settings, actions, outages)` gives the same year every time.
- `settings` overrides the run-scoped config groups `process`, `anomalies`, `reading`, `vee` and `billing`. They never change
  the town id. `GET /api/m2c/settings` returns their JSON Schema, with units, bounds, effects and advanced flags.
- `actions` are analyst decisions from the viewer: `{id, day, type, caseId, value?}`.
  - `type` is one of `accept`, `override` (with a register value), `estimate`, `field_order` or `escalate`.
  - Actions are append-only by `day`. An action never changes anything before its day, so a reply for an earlier
    date stays valid.
- `field_read` (`{day, premiseId, at}`, no `caseId`) is a field visit made on the map. The tech reads the
  premise's meters, and each of its open read cases settles on the spot: a faulty meter is exchanged, otherwise a
  special read gives the real register value.
- `outages` are service interruptions from the operations simulator: `{day, utility, start, end, premiseIds}`, with
  start and end in seconds since local midnight of `day` (end may pass midnight, up to a week). An operations
  timeline reports them as `interruptions`. See "Outages from the map" below.
- Views read the finished year *as of* a date (`asOf`, default: the town's scenario date).

The engine (`utilsim/m2c/`, numpy only) runs locally (`utilsim serve`) and on the hosted Vercel function. A
Cobourg-sized town (16k registers) replays its year in about 2 s, and warm instances keep the last four runs.

## A day in the run

Each business day goes in this order:

1. **Your actions** at 09:00.
2. **RPA carry-over** (07:00): cases deferred from the previous evening.
3. **Analysts** work `VEE_REVIEW` and `ESTIMATION` cases, oldest first.
   - A case becomes eligible after `analyst_queue_days_min`–`max` business days.
   - Each review takes `review_minutes_min`–`max`, within `analysts × analyst_hours_per_day`.
   - The analyst reaches the true cause with probability `analyst_accuracy`. Correct actions by cause:
     - clean read: accept;
     - read error: correct the value;
     - meter fault: field order;
     - real usage (leak, vacant consumption): accept, then a customer callback.
   - An escalate disposition, or a bill impact at or above `vee.escalate_impact`, goes to `SUPERVISOR`.
4. **Supervisors** approve escalations, within capacity.
5. **Field crews** complete up to `field_orders_per_day` orders. A meter fault gets a meter exchange (and the meter is
   fixed); otherwise the crew takes a special read.
6. **Evening batch** for the portions read today: reads, then VEE at 18:00, then exceptions.
   - 19:30: billing documents for every installation period whose reads are all released.
   - 20:00: invoices that consolidate each account's released documents.
7. **RPA** resolves exception types covered by `rpa_coverage`, taken in the order of `catalog.EXCEPTIONS`. Half are
   resolved the same evening; the rest at 07:00 the next business day.

## Weather

`sim/weather.py` gives the town a seeded daily temperature for 2025-12-01 to 2026-12-31: climate normals, each
season's configured mean and spread, an AR(1) anomaly (`weather.persistence`), and clipping to the season's range.
It drives:
- monthly consumption, through each month's mean heating and cooling degree-days;
- live demand: each frame uses its month's typical day and carries `clock.tempC`;
- reading conditions: below −10 °C, missed reads grow by up to 2.5×.

The summary carries the series to date (`weather.series`) and the count of days at or below −15 °C.

## Reads

Every register is read once a month on its portion's business day. Missed reads by technology:
- AMI: `ami_missed_read`;
- AMR: `amr_missed_read`;
- walked (MANUAL): `manual_no_access`, then `no_access_repeat` while it stays missed. No access is per premise:
  a walker who cannot get in misses every meter there.

Anomalies follow `anomalies.*` (per 1,000 meters per year). Each keeps its ground truth:

| Kind | Anomalies | Effect |
|---|---|---|
| Meter faults | stuck, slow, tamper, exchange registration failure | The meter shows less than flowed (or restarts) until a field exchange |
| Read errors | transposed digits, misreads | One bad value; walked reads only |
| Real use | leaks, vacant consumption | Truth rises; a customer callback ends it |
| Process | missing documents, consecutive-estimate episodes | Reads not obtained |

The June reads equal the snapshot's `sampleReads` exactly. Reads are `meter-read/1.1`, with these additive fields:
`veeStatus`, `veeDecisionId`, `veeConfidence`, `caseId`, `billStatus`, `registerRegression` and `revisions[]`.
Estimated and adjusted values are revisions; the original observation is kept.

## VEE (v5 shape)

There are five tests per read, each with a risk contribution of 0–0.25 and a rationale:

1. **SAP diagnosis** (simulated codes):
   - `SIM-T01` / `SIM-T02`: tolerance high / low;
   - `SIM-Z01`: zero consumption;
   - `SIM-C01`: cascade (the register went backwards);
   - `SIM-L01`: lifecycle (a move inside the period).
2. **Temporal validity**: period length.
3. **Consistency**: an erratic ratio against prior-year history; true-ups after estimates.
4. **Process corroboration**: implausible-value cases on the register in the last 180 days. They strengthen
   another signal in the read (0.06 each, up to 0.25); alone they weigh at most 0.05, so a run of cases never keeps
   flagging normal reads.
5. **Context**: a vacant premise that consumes; walked reads.

Confidence is `1 − 2·Σ risk`. The disposition is decided in this order:
- a regression is rejected;
- confidence at or above `accept_confidence`: accept;
- below `reject_confidence`: reject;
- bill impact at or above `escalate_impact`: escalate;
- otherwise: review.

The real SAP `MRIndependantValidation` codes plug into `catalog.CODES`. `/api/vee/export` writes
`vee-input-fixture/1.1` (truth stripped) for an external VEE engine such as m2c.vee.

## Billing, invoices, payments and collections

The calculator is `billing.py`, vectorised per tariff; the state lives in `books.py`.

**Charges** follow the snapshot's tariffs (`RES-E/G/W`, and `COM-*` with an electric demand charge):
- fixed charges and electric blocks are prorated by days over an average month;
- volumetric prices change by `billing.rate_change_pct` from `billing.rate_change_date`, and a period that straddles
  the change is split by days;
- net-metered exports are credited;
- a negative quantity after an over-estimate is credited as a true-up;
- HST is added;
- every line is rounded to the cent.

Each document also carries its total at true consumption (`truthTotal`); summed, these give the billing error.

**Billing blocks** go to the `BILLING` queue:
- `HIGH_BILL`: above `high_bill_ratio` × the expected bill (prior-year use at current prices) and at least
  `high_bill_min` above it;
- `BILL_CREDIT`: a credit larger than `credit_review`;
- `RATE_CLASS`: a wrong rate class in billing master data, seeded at `data_error_rate`.

What analysts do with a block:
- release it, with a customer callback when the use is real;
- rebill it on an estimate when the read was wrong (a version 2 document replaces the reversed one);
- fix the rate class and rebill.

RPA covers `BILL_CREDIT`.

**Invoices:** `INV-{account}-{date}` sums the account's documents released that day. It is issued
`print_lag_days` later and due `customers_billing.due_days` after issue.

**Payments** follow the account's method and its partner's payer profile:
- pre-authorized debit: paid on the due date, or returned (`pad_reject_rate`, plus an NSF fee) and repaid later;
- on-time payers: before the due date;
- late payers: 3–40 days after it;
- at-risk payers: half pay very late, half not in the year.

**Dunning** applies to unpaid invoices:
- a reminder at due + `reminder_days`;
- an overdue notice with a `late_fee_pct` fee at due + `notice_days`;
- a disconnection notice at due + `disconnect_days`.

Disconnection notices for electricity and water are held from Nov 15 to Apr 30 (`winter_moratorium`). An account's
ledger (invoices, payments, fees) gives its balance.

The summary's `billing` block reports:
- documents and blocked documents;
- billed, invoiced and collected amounts;
- receivable and overdue amounts;
- days to invoice and days to pay;
- billing and receivable carry;
- billing error;
- dunning counts.

The premise view carries `billingDocuments` (with lines), `invoices` (with payments and dunning) and `accounts` (with
balance and recent ledger). Reads show `billStatus` (`billed`, `billing_blocked`, `rebilled`), `billingDocumentId`,
`invoiceId` and `invoiceStatus`.

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/m2c/settings` | Schema, defaults, queues, exception vocabulary |
| `POST /api/m2c/summary` | `m2c-summary/1.0`: KPIs, cost (labour, system, CX, reads), carry, VEE precision/recall against truth, `billing`, `reliability`, `weather`, queues with aging and daily opened/closed/backlog, exception mix, RPA rules, one status per premise |
| `POST /api/process/queue` | Paged worklist: `queue`, `status`, `sort` (`age`, `impact`, `confidence`, `created`), `page`, `pageSize` ≤ 200, `type`, `commodity`, `search` |
| `POST /api/m2c/case` | `work-case/1.0`: the case, its VEE decision, the read, 12-month history, events (`event/1.0`) with causal edges, allowed actions (`truth: true` adds ground truth) |
| `POST /api/m2c/premise` | Registers, every read to date, cases, `outages`, `billingDocuments`, `invoices` and `accounts` (balance and ledger) |
| `POST /api/vee/decision` | `vee-decision/1.0` for one `readId` |
| `POST /api/vee/export` | VEE input fixture for a `month` and optional `portion` |
| `POST /api/vee/scorecard` | `vee-scorecard/1.0`: VEE against simulation truth. Per anomaly type: recall and median days from onset to the first flag. Per exception type: precision |
| `POST /api/vee/dispositions` | Import decisions from an external VEE engine (m2c.vee v5) by `readId`. Each becomes the equivalent append-only action on the case holding the read: accept → accept; reject or estimate → estimate; an edit → override; escalate and field order map directly; review keeps the case open. Unmatched decisions are returned with a reason. |
| `POST /api/process/graph` | Activity Sequence nodes and edges for a month |
| `POST /api/process/costs` | Cost, carry and days to release by exception type |

Every response stays under the hosted 4.5 MB limit; `tests/test_m2c.py` checks this.

## In the simulator (operations day)

The operations run for a day (`POST /api/sim/timeline`) schedules meter-to-cash work as crew jobs, before your
commands and on their own crews:
- **Reading rounds:** the day's walked (MANUAL) and drive-by (AMR) routes, those whose portion's business day it
  is, become `meter_reading` jobs.
  - A walker parks at the first premise, walks every meter in sequence order and walks back to the van.
  - A drive-by van drives the round.
  - Each job carries `walkRoute` and `walkTimes`, and `stops`: when each premise's meters are read
    (`{premiseId, at}`, in sequence order; a drive-by van reads the premises between its waypoints on the way).
  - With the meter-to-cash run linked, each stop also carries that read's outcome: `read`, `flagged` (with the
    VEE `exception` and `caseId`) or `missed` (with the `reason`, e.g. `SIM_NO_ACCESS`). The map paints a disc at
    each house as the reader passes it, and the round's card counts them. The read's own `readAt` in meter-to-cash
    keeps its scheduled hour, not the walker's arrival.
- **Field orders:** when the request carries the meter-to-cash run (`m2c: {settings, actions}`), that run's truck
  rolls on the day become `field_order` jobs (`FIELD-n` crews, 45 min for an exchange, 20 for a special read).

The viewer keeps one run day for the map and the worklists. "Watch the truck roll" on a field-order case moves the
map to that day and follows the van, and a field visit on the map is reported back as `field_read`.

### Outages from the map

Break a pole or a main on the map and the outage reaches meter-to-cash. The timeline's `interruptions` list who lost
which service and when; the viewer keeps them per operations day and sends them as the run's `outages`. In the run:
- **Use stops:** each register loses its normal consumption for the hours without service (an electric outage also
  stops PV export), so the following reads, bills and true-ups are lower.
- **AMI needs power:** an electric AMI meter without power at its 02:00 read misses it (`readReason`
  `SIM_POWER_OUTAGE`). The `COMM_FAIL` case is caused by an `AMI_LAST_GASP` event in its Activity Sequence and is
  estimated like any missing read. Water and gas endpoints run on batteries.
- **VEE knows:** with `vee.oms_events` (default on), the hours without service lower the expected use, and the
  context test's rationale names them. Turn it off to see what an outage does to low-usage flags when VEE is not
  told.
- **Reliability:** the summary's `reliability` reports interruptions, customers interrupted, customer-minutes, SAIDI
  minutes per customer served, use lost and AMI last gasps, per utility. A premise view lists its `outages`.

The morning's field orders for a day never depend on that day's own outages, so linking the two runs cannot loop.
A day's outages stay after you move the map to another day or reload; "Reset engine run" clears them.
