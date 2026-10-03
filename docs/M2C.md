# Meter-to-cash (M2C)

Reads, VEE, exception work queues, billing, invoicing, payments and collections for every premise, replayed by the
engine for calendar 2026.

## Run model

A run is stateless and deterministic: `(town, settings, actions, outages, seed)` gives the same year every time.
- `settings` overrides the run-scoped config groups `process`, `anomalies`, `reading`, `vee` and `billing`. They never change
  the town id. `GET /api/m2c/settings` returns their JSON Schema, with units, bounds, effects and advanced flags
  (`?town=` takes the defaults from that town).
- `seed` (optional, top level, at most 64 characters) re-rolls the run on the same town: every random draw of the run
  (missed reads, anomalies and their onsets, analyst pickup and review, bill checks, payments) comes from
  `"{seed}:m2c"` instead of the town's `"{seeds.anomalies or seeds.master}:m2c"`. Blank, `null` or the town's own seed is the town's
  run, exactly as before the field existed (same `simulationId`). The routes, read days, meters and customers never
  change. `GET /api/m2c/settings` returns `seed: {type, maxLength: 64, default: <town seed>, title, description}`,
  so a form can show "blank = town seed"; summaries echo `seed` (`null` for the town's run). Operations requests
  pass it inside `m2c` (`m2c: {settings, actions, outages, seed}`), and every run cache key includes it.
- `actions` are analyst decisions from the viewer: `{id, day, type, caseId, value?, note?}`.
  - `type` is one of `accept`, `override` (with a register value), `estimate`, `field_order` (optionally with
    `coverCaseIds`), `escalate` or `check_read` (release the read with a completed field order's check read).
  - The Utility Studio adds field service orders (`order_save`, `order_release`, `order_dispatch`,
    `order_complete`), case work (`note`, `assign`, `invoice_hold`, `invoice_unhold`) and device replacement
    (`device_replace`); see "Studio work" and "Devices" below.
  - Collections work on an account or an invoice: `payment_arrangement`, `extend_due`, `dunning_hold`,
    `low_income_referral`, `budget_billing`, `waive_fee`, `disconnect_approve`, `disconnect_cancel`; see
    "Collections" below.
  - Actions are append-only by `day`. An action never changes anything before its day, so a reply for an earlier
    date stays valid.
  - A refused action is HTTP 422 with a clear `detail` (for an order form, an object with `fieldErrors`), so the
    viewer can roll it back. Only the newest action is refused this way; an earlier one that no longer applies
    (settings or outages changed the run under it) is skipped with a warning, so a stored list always replays.
  - An action works a case only if the case is open when the action lands (09:00). Otherwise it is refused, and the
    message says why and when:
    - a case raised later that day (VEE at 18:00, billing at 19:30) or on a later day: `CASE-… was raised at 18:00
      on 2026-07-06; work it from 2026-07-07` (rows and case views carry this date as `actionableFrom`);
    - a case already resolved: `CASE-… was already completed by RPA at 19:00 on 2026-07-06` (or by analyst AN-01,
      supervisor SUP-01, field crew FIELD-1, you);
    - a case id the run does not have: `case CASE-… does not exist in this run`.
  - Decisions a case does not take are refused too: `accept` on a register that went backwards (see "Backwards
    registers"), `override` or `field_order` on a billing block, a release while the account is on hold, any
    decision on a Field Work or hold case.
- `field_read` (`{day, premiseId, at}`, no `caseId`) is a field visit made on the map. The tech reads the
  premise's meters, and each of its open read cases settles on the spot: a faulty meter is exchanged, otherwise a
  special read gives the real register value.
- `outages` are service interruptions from the operations simulator: `{day, utility, start, end, premiseIds}`
  (`utility` `electric`, `water`, `gas`, or `ami` for an AMI collector outage), with
  start and end in seconds since local midnight of `day` (end may pass midnight, up to a week). An operations
  timeline reports them as `interruptions`. See "Outages from the map" below.
- Views read the finished year *as of* a date (`asOf`, default: the town's scenario date).

The engine (`utilsim/m2c/`, numpy only) runs locally (`utilsim serve`) and on the hosted Vercel function. A
5,500-home town (16k registers) replays its year, every bill and collection included, in about 15 s on one core,
and warm instances keep the last four runs.

## Episodes: a scenario inflicted from a day

The run's settings are the year's base. An **episode** overrides some of them from a day (``from``) to a day
(``to``, inclusive; null runs to the year's end), optionally sliding numeric values from the base to the target over
``ramp`` days, so a situation can get progressively worse. A value is absolute (a number, a boolean, a text choice)
or an operator on the value in force before the episode (``"*0.5"``, ``"+2"``, ``"-1"``), so the same episode fits
any town. Episodes travel with the run like actions (``episodes`` on every run request) and enter the simulation id;
a run without episodes is byte-identical to the base.

The engine resolves the configuration in force on every day (``M2CRun.cfg_at(day)``; distinct configurations are
validated once) and the day's values reach: the reading batch (missed-read rates, VEE thresholds, the trend tests,
the estimation method), case creation (queue waits, RPA coverage), the analysts, supervisors and field pool
(headcount, hours, review minutes, field days), bill checks and the release rule, invoicing lag, and dunning (reminder,
notice and disconnection timings, fees, the moratorium window ``billing.moratorium_start``/``moratorium_end``, PAD
rejections, arrangements, low-income decisions) at the time each event happens. Anomaly onsets and master-data
errors are drawn per month from the month's average rate (``month_rate``), scaled per technology by
``anomalies.amr_factor`` and ``manual_factor``; the random draws themselves never change, so raising a rate from March
adds onsets from March and keeps every earlier one. Settings read once for the whole year stay at the base: the rate
change (``billing.rate_change_date``/``pct``), prior-year history noise, the price used for bill impact, and the
carry rates and read costs in the summary's cost figures.

**The scenario library** (``GET /api/m2c/scenarios``, ``utilsim/m2c/scenarios.py``) lists situations as episode
templates relative to the day they are inflicted (start offset, duration, ramp, settings) with what to watch:
staffing (half staff, nobody on the queues, supervisor away, automation off), reading (no-access summer, AMI heat
dropouts), meters (ERT/AMR fleet drift, anomaly wave), VEE (loosened, tightened), billing (master data slips, blocks
wait for you), collections (bank debit failures, lenient and aggressive dunning, a longer moratorium), the contact
centre (lines open mornings only, IVR and website down, a second agent) and operations (storm season, which triples
the storm days the year draws). Undetected water loss is listed as coming: it needs the unbilled-loss physics.
``tests/test_m2c_episodes.py`` checks that every template parses and that the ones that must show on a small town do.

**The trend** (``POST /api/m2c/trend``, ``m2c-trend/1.0``) reports the year month by month as of the view date:
reads scheduled, taken, missed, estimated and adjusted; cases opened and resolved, the backlog by queue at month end,
escalations and field orders; labour, system and CX cost and carry; documents, blocked bills, billed, invoices,
invoiced, collected, overdue and receivable; dunning events and every account's collections phase at month end;
and the contact centre (`contact`: contacts by group and reason, answered, hung up, service level, cost). It
echoes the run's episodes so the Year page shades them behind the lines. Months after the view date are null; the
month holding it is partial.

## A day in the run

Each business day goes in this order:

1. **Your orders' crews** roll (07:00–09:00, any day) for the orders dispatched for that start date.
2. **Your actions** at 09:00. Then the crews on your orders record their outcomes, stamped when each visit ends,
   unless you completed the order that day (yours replaces the crew's); see "Your orders and the simulated field
   workforce".
3. **RPA carry-over** (07:00): cases deferred from the previous evening.
4. **Analysts** work `VEE_REVIEW` and `ESTIMATION` cases, oldest first.
   - A case becomes eligible after `analyst_queue_days_min`–`max` business days.
   - Each review takes `review_minutes_min`–`max`, within `analysts × analyst_hours_per_day`.
   - The analyst reaches the true cause with probability `analyst_accuracy`. Correct actions by cause:
     - clean read: accept;
     - read error: correct the value;
     - meter fault: field order;
     - real usage (leak, vacant consumption): accept, then a customer callback.
   - An escalate disposition, or a bill impact at or above `vee.escalate_impact`, goes to `SUPERVISOR`.
   - One visit per premise: an analyst (or a supervisor, or RPA) who sends a case to the field sends the premise's
     other open read cases nobody owns (and no RPA run is due on) along with it (`FIELD_ORDER` with `with`).
5. **Supervisors** approve escalations every business day, up to `supervisors × supervisor_hours_per_day ÷
   supervisor_minutes` (3 a day by default), oldest first. An escalation from an analyst or you becomes eligible
   `supervisor_queue_days_min`–`max` business days after it is raised (default 1–3), a case VEE escalated itself
   after `supervisor_queue_days_min`. An escalation stays with the supervisors: a note, an order or a hold on it does
   not make you its owner. Only `assign` takes it from them (a case you own waits for you).
6. **Field crews** visit up to `field_orders_per_day` premises, oldest work first. One truck roll per premise settles
   every open read case there that nobody owns (the lead case has `TRUCK_ROLL` with `caseIds`, the others
   `VISIT_SHARED`). A meter fault gets a meter exchange: a new device and register, initial read 0, registered at
   the visit (an exchange whose registration failed is registered as found, at its dial); otherwise the crew takes a
   special read.
7. **Evening batch** for the portions read today: reads, then VEE at 18:00, then exceptions.
   - 19:30: billing documents for every installation period whose reads are all released.
   - 20:00: invoices that consolidate each account's released documents.
8. **RPA** resolves exception types covered by `rpa_coverage`, taken in the order of `catalog.EXCEPTIONS`. Half are
   resolved the same evening; the rest at 07:00 the next business day. RPA never resolves a `TRUE_UP` block, nor a
   `HIGH_BILL` or `BILL_CREDIT` outsort above `billing.outsort_auto_release_max`: those wait for a person.

## Cases

**Ids.** An engine case is `CASE-{yymmdd}-{code}`: the date it was raised and six characters (Crockford base 32) of a
hash of what it is about (exception type, register, read period, creation minute). A case keeps its id when
anything else in the run changes (an outage on an earlier day, another anomaly rate), so stored actions keep naming
the same case. A collision takes the next salt of the hash (deterministic). The cases you open keep their action-keyed
ids: Field Work `CASE-{yymmdd}-F{nnnn}` and invoice holds `CASE-{yymmdd}-H{nnnn}`.

**Who raised it.** Every row and case view carries `createdBy` and `createdByLabel`:

| `createdBy` | Cases |
|---|---|
| `ami_head_end` | AMI reads that did not arrive (comm fail, power outage, collector outage) |
| `meter_reading_route` | Walked (no access) and drive-by reads that were missed |
| `vee_batch` | Value exceptions, consecutive estimates, periods with no read document |
| `billing_run` | Billing blocks (`HIGH_BILL`, `BILL_CREDIT`, `RATE_CLASS`, `TRUE_UP`) |
| `collections` | The call centre's low-income referrals (`LOW_INCOME`) and budget billing enrolments (`BUDGET_BILL`) |
| `studio` | Your Field Work, invoice hold, low-income referral and budget billing cases |

**Missing reads explain themselves.** A missing-read case (its read record and its VEE decision too) carries
`cause`: `{code, label, reasonCode, reason}`, plus `outageStart` and `outageEnd` for an outage. `code` is
`power_outage` (with `lastGaspAt`), `collector_outage` (with `outageSince`), `comm_fail` (AMI head-end or drive-by),
`no_access` or `no_read_document`; `reason` is one line that names it ("No read: the meter lost power at 00:00 on
2026-03-03 (AMI last gasp) and was still without power at the 02:00 read (back at 04:00 on 2026-03-03)."). The five
VEE tests stay `not_applicable`, each saying what it would have checked. A case with no read value offers `estimate`,
`field_order` and `escalate` only, and `check_read` once a field order took a read.

**What a decision needs.** Case views (`work-case/1.0`) carry:
- `expected`: `{registerValue, consumption}`, the expected register (previous register + expected use) and use;
- `registerDelta` (observed − previous register), `registerWentBackwards` (below the last actual read and not a
  rollover) and `previousEstimated` (the previous register was an estimate, so a negative delta alone is a true-up);
- `released` once resolved: `{registerValue, consumption, method, by, at}`, what billing used. `method` is `as_read`,
  `corrected`, `estimated` or `field_read`; `by` is `RPA`, `AN-nn`, `SUP-nn`, `FIELD-n` or `you`. A billing case adds
  `billingDocumentId` and `totalAmount`;
- `readHistory`: the register's periods to date (up to 13, oldest first), each `{readId, date, register,
  consumption, type, estimated, method, veeStatus, caseId}`;
- `actionableFrom`, `cause`, `createdBy`;
- `relatedCases`: the other open cases at the premise (`{caseId, type, label, commodity, queue, registerId,
  coverable}`; `coverable`: a field order from this case can also cover it, one visit per premise);
- `fieldOutcome`: the newest outcome a completed field order wrote back to the case (`{orderId, kind, label, text,
  by, at, registerId, ...}`), and `checkRead` (`{value, orderId}`) when that outcome gives this read a check read;
- `actions` and `studioActions`: only what the engine accepts from an action dated the view's day (empty while the
  case is not open at 09:00 that day).

Worklist rows carry `actionableFrom`, `createdBy`, `createdByLabel`, `cause`, `registerDelta`,
`registerWentBackwards`, `previousEstimated`, `releasedMethod` and `relatedCaseIds` as well.

**Check reads.** A completed field order writes its outcome back to every case it serves: a "Field order completed"
step (`ORDER_COMPLETED`, in the processing history and the case notes). A read taken on the case's register (brought
back to the read date by the normal use since), or a read confirmed on a read that came in, is the case's check read:
the `check_read` decision releases the read with it, method `field_read`. A crew's outcome counts from the day after
the visit (that day you may still replace it); yours counts at once. A check read below the last actual read is
refused like an `accept` (register the device replacement first).

**The AMI collector behind a missed read.** Each AMI meter reports through one collector (the snapshot's
`meters[].ami.collectorId`; `amiNetwork.collectors` mounts them on poles, streetlights and transformer pads), so a
collector outage or a street of comm fails is one problem, not many cases:
- rows carry `collectorId` (null for AMR and walked meters) and `collectorCases`: the AMI missed reads (comm fail,
  power outage, collector outage) on that collector raised the same day, this one included (0 for other cases);
- a case view adds `network`: `{collectorId, mountedOn, mountId, day, cases, relatedCases[]}` (up to 50 related
  cases, each with `caseId`, `address`, `status`, `outcome`, `reasonCode`); null for a meter without a collector;
- `POST /api/m2c/collector-groups` lists the groups (collector and day, at least `minCases`, newest first) with
  their case ids, open count, shared `cause`, premises, streets and the collector's mount, plus the town's
  collectors (`meters` each); `POST /api/process/queue` with `collector` and `createdOn` lists one group's cases.

**Backwards registers.** A register below its last actual read (as read, corrected or field read; not an estimate),
and not a plausible rollover, is never released as read:
- simulated analysts, supervisors, RPA and field visits estimate it or send a field order;
- your `accept` is refused ("estimate it, correct the value (override) or send a field order");
- a read below the previous *estimate* only is a true-up of that estimate and can be accepted.

Your `override` value is yours to give; billing still checks the true-up it causes. After a device replacement (see
"Devices"), the floor is the new register's initial read: a read on the new device is not backwards against the
old register's reads.

## Devices

Each meter slot (`meterId` in the snapshot) holds one device at a time; the snapshot's device is in place before 2026.
A **device replacement** installs a new device (`deviceId`, the serial) with its registers' initial reads from an
install date:
- your `device_replace` `{day, meterId, deviceId, installDate, initialRead, removalRead?, note?, caseId?}` (from the
  installation record): `installDate` is on or before the action day, and after the last read already released on the
  old device (else 422: "the read of … was already released on device …"); `initialRead` is the case register's
  (the slot's first register when no `caseId` names one), other registers start at 0 (at their dial when it registers
  a swap already made); a `caseId` records `DEVICE_REPLACED` on that case. A device id already in use is refused.
- a field order completed with `meter exchanged` (yours, or the crew's on a meter exchange or meter investigation
  order that finds a faulty meter);
- the simulated crews' meter exchanges (`METER_EXCHANGE` with `deviceId`, `previousDeviceId`, `initialRead`).

What it changes:
- **Reads** after the install date are diffed against the new register. The read period with the change bills the
  new register from its initial read, plus the old register's last stretch: its `removalRead` less the previous
  read, or, when no removal read is known, the normal use up to the install date. Read records carry `deviceId` (the
  device at the read) and, for that period, `deviceChange` `{deviceId, previousDeviceId, installedAt, registeredAt,
  initialRead, removalRead, oldRegisterUse, by}`, with `previousRegisterValue` the initial read. A change registered
  after the read was taken re-bases that read too, so a held backwards read can then be accepted.
- **The meter.** A meter that shows an exchange whose registration failed (`exchange_registration_failure`: a new
  meter the system did not know) is registered as found: nothing is swapped. Any other replacement swaps the meter
  when it is registered: the new dial reads the initial read plus what flowed since the install date, and a fault on
  the old meter ends.
- **A backwards register stops recurring.** A register that dropped (35,623 → 61.7 after an unregistered exchange) used
  to raise `REGISTER_REGRESSION` every cycle; once the device is registered, later reads count from it.

The installation lookup lists, per meter, `deviceId` (current as of `asOf`) and `devices[]`: `{deviceId,
installedAt, registeredAt, removedAt, initialReads, removalReads, by, orderId, caseId, note, physical, current}`,
oldest first.

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
`veeStatus`, `veeDecisionId`, `veeConfidence`, `caseId`, `billStatus`, `registerRegression`, `registerDelta`, `cause`
and `revisions[]`. Estimated and adjusted values are revisions; the original observation is kept.
- A lower register near the top of its dial (previous above 80 % of it, new below 20 %) is a rollover:
  `rolloverFlag: true` and the consumption wraps.
- Any other lower register went backwards: `registerRegression: true`, `consumption: null` and the negative
  `registerDelta` (observed − previous register). No consumption is ever priced as a wrap that is not a rollover.
- A missed read carries `reasonCode` and `cause` (see "Cases"); an outage adds `outageStart` and `outageEnd`, so a
  reading screen can show "missed: power outage 01:00–03:20".

## VEE (v5 shape)

There are five tests per read, each with a risk contribution of 0–0.25 and a rationale:

1. **SAP diagnosis** (simulated codes):
   - `SIM-T01` / `SIM-T02`: tolerance high / low;
   - `SIM-Z01`: zero consumption;
   - `SIM-C01`: cascade (the register went backwards);
   - `SIM-L01`: lifecycle (a move inside the period);
   - `SIM-T03`, `SIM-E01`, `SIM-D01`: the diagnosis of a persistent-low, erratic or period-length exception (their
     risk is carried by the consistency or temporal test), so every value exception has a code.
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

**Billing blocks** go to the `BILLING` queue, checked in this order:
- `TRUE_UP`: an estimate true-up (a negative period quantity) larger than `trueup_max_ratio` (default 3) × the
  period's expected use (at least 30 kWh or 1 m³): more credit than any over-estimate could explain;
- `RATE_CLASS`: a wrong rate class in billing master data, seeded at `data_error_rate`;
- `HIGH_BILL`: above `high_bill_ratio` × the expected bill (prior-year use at current prices) and at least
  `high_bill_min` above it;
- `BILL_CREDIT`: a credit larger than `credit_review`.

What analysts do with a block:
- release it, with a customer callback when the use is real;
- rebill it on an estimate when the read was wrong (a version 2 document replaces the reversed one);
- fix the rate class and rebill.

RPA covers `BILL_CREDIT` at the default coverage, but releases a `HIGH_BILL` or `BILL_CREDIT` outsort only up to
`outsort_auto_release_max` (default $500, either sign); a larger one waits for an analyst (or you). No RPA rule
covers `TRUE_UP`. All three are in the "Billing Outsorts" category.

`billing_queue_worked_by` (default `analysts`) decides who works the `BILLING` queue. Set it to `you` to practise
outsort release: no analyst and no RPA touches a billing block, so every `HIGH_BILL`, `BILL_CREDIT`, `TRUE_UP` and
`RATE_CLASS` case waits for your `accept`, `estimate` (rebill) or `escalate`. Bills behind them wait too, so days to
invoice and billing carry grow.

**Estimated bills.** A billing document built on an estimated read says so: `estimated: true` and
`estimatedReadIds` (a rebill on an estimate is estimated too). An invoice carries `estimated` and
`estimatedBillingDocumentIds`, so premise and installation views show which bills and invoices rest on estimates.

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

Disconnection notices for electricity and water are held from Nov 15 to Apr 30 (`winter_moratorium`): the invoice
gets a `MORATORIUM_HOLD`, and the notice is issued on May 1 if the bill is still unpaid. An account's ledger
(invoices, payments, fees, grants, waivers, budget deferrals) gives its balance.

The summary's `billing` block reports:
- documents and blocked documents;
- billed, invoiced and collected amounts (collected counts instalments and low-income grants too);
- receivable and overdue amounts (overdue is what is still owed on overdue invoices);
- days to invoice and days to pay;
- billing and receivable carry;
- billing error;
- dunning counts (every step and collections event on an invoice, by type);
- `collections`: arrangements (made, active, completed, broken, amount), dunning holds, low-income referrals (open,
  approved, declined, grants), budget plans (master data, enrolled in the run, active), disconnections (notices,
  pending, approved, disconnected, reconnected, cancelled) and fees waived.

The premise view carries `billingDocuments` (with lines), `invoices` (with payments and dunning) and `accounts` (with
balance and recent ledger). Invoices also carry `amountDue` (a budget plan's instalment, else the total),
`outstanding`, `budgetBilling`, `disconnection` (its state) and `originalDueAt` when the due date was extended. Reads
show `billStatus` (`billed`, `billing_blocked`, `rebilled`), `billingDocumentId`, `invoiceId` and `invoiceStatus`.

## Collections

Payments, dunning and collections run after the year's billing (`collections.py`), one account at a time in time
order, so your collections actions change the books from their day on and never before. Each lands at 09:00 on its
`day` like every Studio action, and is refused (422, or a warning for an older action) when it does not apply, with
the reason ("account CA-… has nothing overdue on 2026-01-02", "the disconnection for invoice INV-… was cancelled on
…").

| Action | Body | Effect |
|---|---|---|
| `payment_arrangement` | `{day, accountId, instalments (2–12, default 3), note?}` | What is overdue at 09:00 becomes equal monthly instalments, the first due 7 days later. The customer's own payments on those bills stop; instalments pay them oldest first. Dunning on them waits while the arrangement runs. On-time payers and debits pay on each due date, late payers 1–10 days late; an at-risk payer breaks it after a few instalments (`arrangement_break_rate`), and dunning resumes. One at a time per account |
| `extend_due` | `{day, invoiceId, days (1–60, default 14), note?}` | The due date moves; the next dunning step is counted from the new date (a late fee may never come). Not after a disconnection notice |
| `dunning_hold` | `{day, accountId, days (1–90, default 30), note}` | No reminder, notice or disconnection on the account until the hold ends; a step that fell in it comes at the end |
| `low_income_referral` | `{day, accountId, note?}` | Opens a Low Income Process case `CASE-{yymmdd}-L{nnnn}`. Dunning waits until the agency decides, `low_income_review_days` business days later at 14:00; it approves with `low_income_approval_rate` and credits a grant (up to `low_income_grant_max`) to the oldest unpaid bills |
| `budget_billing` | `{day, accountId, note?}` | Opens a Budget Bill Cases case `CASE-{yymmdd}-B{nnnn}`. A collections agent sets the plan up after the analyst pickup lag (10:00); invoices issued after that owe the plan's instalment (the account's average monthly expected bill: prior-year use at current prices, whole dollars, at least $10) and the difference goes to `budget_deferral` on the ledger. Refused for an account already on a plan (master data `budgetBilling`, or enrolled) |
| `waive_fee` | `{day, invoiceId, fee: late_fee \| nsf_fee, note?}` | Credits the invoice's posted late fee (or NSF fee) back (`fee_waived` on the ledger) |
| `disconnect_approve` | `{day, invoiceId, note?}` | After a disconnection notice: a crew disconnects at 10:00 on the earliest disconnection day (notice + `disconnect_notice_days`), or the next morning, if the bill is still unpaid. A dunning hold or an open referral moves it to their end; under a payment arrangement the approval lapses. A customer who would not have paid within a week pays the overdue bills 2–7 days later with `disconnect_payment_rate` and is reconnected the next business day at 10:00 |
| `disconnect_cancel` | `{day, invoiceId, note}` | No disconnection for that notice |

The engine never disconnects without your approval. **The call centre** (simulated, `createdBy: collections`)
refers a customer to a low-income programme after a disconnection notice or a moratorium hold
(`low_income_referral_rate`, once a year per account), and enrols one in budget billing after an overdue notice
(`budget_billing_offer_rate`, once a year per account); the agency and a collections agent (`CC-01`) then work them as
above. Accounts with `budgetBilling` in master data are on a plan all year.

Collections cases are account work (`Case.work` `low_income` or `budget_bill`, `ref` the account) in the
`COLLECTIONS` queue: their case view has `collections` (the account's overdue and outstanding, the referral's
outcome and grant, or the plan) and no read, decision or read history; `studioActions` are `note` and `assign`
(your notes on a call-centre case wait in the day loop and land in time order).

**Worklists** (`POST /api/m2c/collections`, `m2c-collections/1.0`): `{list, status (open, closed, all), sort (age
oldest first, amount largest first, created newest first), page, pageSize ≤ 200, search, commodity}`.

| `list` | One row per | Open while | Row fields beyond the invoice's (`invoiceId`, `accountId`, `name`, `premiseId`, `address`, `commodities`, `dueAt`, `amountDue`, `outstanding`, `daysOverdue`) |
|---|---|---|---|
| `disconnect` | disconnection notice | `pending`, `approved` or `disconnected` | `noticeAt`, `earliestDisconnectAt`, `state` (`pending`, `approved`, `disconnected`, `reconnected`, `cancelled`, `paid`, `arranged`), `approvedAt`, `scheduledAt`, `disconnectedAt`, `reconnectedAt`, `cancelledAt`, `heldBy` |
| `moratorium` | winter moratorium hold | `held` | `heldAt`, `heldUntil` (May 1), `state` (`held`, `notice issued`, `paid`), `noticeAt`, `heldBy` |
| `rejected` | returned pre-authorized debit | unpaid | `rejectedAt`, `amount`, `nsfFee`, `nsfWaived`, `repaidAt`, `state` |
| `overdue` | account with overdue bills | always | `overdue`, `invoices`, `invoiceIds`, `oldestDueAt`, `ageDays`, `balance`, `lastDunning` |

Each row carries `flags` (`arrangementId`, `dunningHoldUntil`, `lowIncome`, `budgetBilling`, `disconnected`),
`actions` (the collections actions the engine takes from an action dated the view's day; `waive_fee:late_fee` and
`waive_fee:nsf_fee` name the fee) and, for invoice rows, `fees` (what is left to waive). `counts` gives each list's
open items and `amount` the matching total. `POST /api/m2c/collections/account {accountId}`
(`m2c-collections-account/1.0`) gives one account: balance, overdue, outstanding, `flags`, `budgetPlan`
(instalment, source, start, `budgetBalance`), `arrangements` (with their schedule), `holds`, `referrals`, the account
log, its invoices (with payments, dunning, disconnection, `heldBy` and `actions`), its collections cases, the last 40
ledger postings and the account-level `actions`.

## Follow-up worklists

**Outage follow-up** (`POST /api/m2c/outage-followup`, `m2c-outage-followup/1.0`): one row per premise per
interruption in the run's `outages`, newest first: `outageId`, `utility` (or `collectorOutage`), `start`, `end`,
`day`, `startSeconds`, `ongoing`, `minutes`; the premise; `lastGasp` and `lastGaspAt` (an electric AMI meter lost
power); `lostUse` and `unit` (the import use that never flowed while the service was off); `collectorId`;
`missedReads` (each read scheduled during the interruption that its outage cost: `readId`, `meterId`,
`scheduledReadAt`, `reasonCode`, `caseId`, `caseStatus`, `outcome`); and `followUp` (`open missed-read case`, `missed
read worked`, `no read missed`). Filters: `utility`, `kind` (`last_gasp`, `lost_use`, `missed_read`), `status`
(`open`: an open missed-read case), `outageId`, `search`, paged. `outages` sums up each interruption (premises, last
gasps, use lost, missed reads, open cases).

## Outages and leaks over the year

The year now draws the operations day's background incidents (`utilsim/ops/hazards.py`) for every date of 2026
(`utilsim/m2c/incidents.py`), with the same seed as the map's day (the town's incident seed, plus the run seed when the
run names one), so a date's storm, leak or failure is the same incident on the map and in the year. The run group
**Outages & leaks over the year** (`outages`) scales them per day, and episodes can change it:

| Setting | Effect |
|---|---|
| `enabled` | Off: the year draws no incidents (no outage or gas odour contacts beyond the background rate) |
| `storm_factor` | Multiplies the chance of a storm day (the town's `weather.storm_days_per_year`); storms bring overhead line faults |
| `incident_factor` | Multiplies every incident rate (the town's `incidents.*` settings: main breaks, leaks, transformer and line faults, collector outages) |
| `restore_factor` | Multiplies the time to restore (detection, mobilising and driving, isolating, repair) |

Who is affected, and for how long:
- **Transformer failure:** every premise the transformer feeds, until it is replaced.
- **Overhead line fault:** every premise downstream of the span. With tie back-feed on, premises more than 250 m from
  the fault get power back once the section is isolated; the rest wait for the repair.
- **Water main break:** premises with water within 150 m lose it until the repair.
- **Gas main leak:** no outage; premises with gas within 80 m can smell it.
- **Gas service leak:** the household with the leaking service loses gas until the repair; neighbours within 40 m can
  smell it.
- **AMI collector outage:** recorded; nobody loses service.

This is a consequence model, not the operations day's crew dispatch: travel is a flat 20 minutes and crews are never
busy elsewhere. The year's reads do not see these outages yet (the operations day's interruptions you carry into a run
do). A run without a network (a town with no `ops` data) draws none and says so in the contact summary's `notes`.

## Contact centre

Customers get in touch for sixteen reasons, and most of them follow what happens to their account in the replayed
year (`utilsim/m2c/contact.py`). Every reason is a run setting in the group **Contact centre** (`contact`) with five
parts: `per_event` (the share of triggers that lead to a contact), `per_1000` (a background rate per 1,000 accounts a
month), `self_serve` (the share the IVR, website or outage message settles), `handle_min` (an agent's minutes) and
`resolved` (the share an agent settles first time).

| Reason | Group | Triggered by |
|---|---|---|
| High bill | billing | an invoice at least 1.5 times the account's expected amount and $40 more |
| Bill question | billing | any invoice; ×3 with an estimate, ×4 for a first invoice, ×2 in the 45 days after the rate change |
| Bill wrong | billing | a bill that overcharges against the truth by $15 and 15 percent (undercharges at a sixth of the share) |
| Back bill | billing | a rebill, or the first actual bill after estimates, that catches up $25 and half the expected amount |
| Balance | billing | each invoice, in the days before it is due |
| Online account | billing | each invoice, as customers log in to see it (forgotten passwords and lockouts) |
| Can't pay | payments | reminders (a quarter of the share), overdue notices, disconnection notices (2.5 times) |
| Payment problem | payments | a returned pre-authorized debit |
| Disconnected | payments | a disconnection you approved |
| Start service, Stop service | service | an account opening or closing in the year, 3 to 14 days before |
| New connection | service | background only |
| Meter access | service | a no-access read, and a field visit (twice the share) |
| Outage | emergency | each premise that loses power or water in the year's incidents; twice the share past two hours |
| Gas odour | emergency | premises near a gas leak; the household with a leaking service calls 9 times in 10 |
| Complaint | complaints | a second unresolved contact about the same thing, or giving up on hold twice |

How the lines answer them:
1. **Self-service first.** A fresh contact is settled by self-service at the reason's `self_serve` share times
   `self_serve_factor`. Gas odours always go to the emergency line (answered within `emergency_answer_s`, a crew
   dispatched). Outage reports go there too when the lines are closed.
2. **The queue.** The rest queue for `agents` between `open_hour` and `close_hour` on business days, first come first
   served, each call taking the reason's `handle_min` times `handle_factor` (drawn around it).
3. **Patience and call backs.** A caller hangs up after a patience drawn around `patience_s`. One who would wait longer
   than `callback_after_s` takes a call back at `callback_take_share` when `callback` is on, served in turn without
   hanging up.
4. **Retries, repeats and complaints.** Callers who hung up, or called while the lines were closed, try again
   (`retry_share`, at most three attempts); after the third they give up. An unresolved contact comes back within days
   (`repeat_share`), and a second unresolved one can become a complaint.

`volume_factor` scales every reason's shares. Costs are agents' paid hours (`agent_cost_per_hour`, whether busy or not),
`self_serve_cost` per self-served contact, `abandon_cx_cost` per hang-up and the emergency line's handling time. Every
draw is a counter-based hash of the run seed and the contact's identity, so one reason never moves another's draws,
and episodes on `contact` or `outages` settings apply from their day. The contact settings never change the rest of
the year: reads, cases, bills and collections are byte-identical (`tests/test_m2c_contact.py`).

**Summary** (`POST /api/m2c/contact`, `m2c-contact/1.0`): as of `asOf`, the settings in force, `kpis` (contacts,
self-served, to agents, answered, call backs, abandoned, closed, gave up, emergency, repeats, resolved first time,
`abandonedPct`, `serviceLevelPct` (answered within `service_target_s`), `asaS` (average speed of answer),
`avgHandleMin`, `occupancyPct`, `cost` {staff, selfServe, abandoned, dispatch, total}, `byGroup`, `byReason`),
`reasons` (each with its figures and settings), `groups`, `daily` (the last 60 days), `incidents` (count, by kind,
storm days, customers out) and `notes`. The trend's months carry the same figures under `contact`.

Measured on the default settings, year to 31 December:

| Town | Accounts | Contacts | To agents | Hung up | In target | ASA | Occupancy | Cost |
|---|---|---|---|---|---|---|---|---|
| `village` | 635 | 798 | 458 | 1.5% | 99% | 2.7 s | 2.3% | $86k |
| `small_town` | 2,368 | 2,634 | 1,476 | 4.5% | 97% | 3.9 s | 6.9% | $87k |
| `town` | 3,969 | 4,706 | 2,542 | 7.4% | 95% | 8.5 s | 12% | $88k |
| `large_town` | 6,598 | 8,227 | 4,258 | 12% | 91% | 14 s | 19% | $91k |

The year draws 10 incidents on the village, 21 on the small town, 32 on the town and 57 on the large town. One
agent is the default: a town of a few thousand accounts keeps
one person busy for a tenth of the day, and storm days or a week of disconnection notices still spill into hang-ups.
The scenario library's **Contact centre** group tries the levers (lines open mornings only, IVR and website down, hire
a second agent), and **Storm season** (operations) triples the storm days for three months.

Not yet modelled: contacts do not open back-office cases (a bill-wrong call does not raise a billing exception), and
the year's outages do not reach the reads.

## Run statistics for a period

`POST /api/m2c/summary` with `since` (a date) adds `window`: the summary's measures counted between that day (00:00)
and `asOf` (24:00): `kpis` (reads, actual, missing, auto-accepted, flagged, released, estimated, adjusted, cases
opened and resolved, field orders, truck rolls, days to release, costs, carry, plus `casesOpenAtStart` and
`casesOpen`), `billing` (documents, blocked, released, billed, invoices, invoiced, paid, collected, dunning, and
overdue and receivable at the start and the end), `collections` (arrangements, dunning holds, low-income referrals
and grants, budget enrolments, disconnections, fees waived) and `reliability` (interruptions that began in it). From
January 1 the window equals the year to date; two adjacent windows add up to the longer one.

## Studio work

The Utility Studio Workspace acts on the run with the same append-only actions. Each lands at 09:00 on its `day`
(after the latest event of the case it touches).

| Action | Body | Effect |
|---|---|---|
| `order_save` | `{day, orderId?, sourceCaseId? \| readId?, coverCaseIds?, fields{…}, components[{description, quantity, unit}]}` | Without `orderId`: a new **Draft** from one source (an open case, or a read taken by then), id `WO-{yymmdd}-{nnnn}`, plus a linked **Field Work** case `CASE-{yymmdd}-F{nnnn}` (`FIELD` queue). `coverCaseIds` (new orders only): other open read cases at the same premise the one visit also serves; each links the order (a case already with an order, another premise's, a billing block or someone else's is refused). With `orderId` (or the same source again): updates that Draft; `fields` merge, `components` replace. Incomplete forms are allowed; unknown fields or wrong types are refused (`fieldErrors`). |
| `order_release` | `{day, orderId}` | Validates the whole form against the action's day → **Ready for dispatch**, or 422 with `fieldErrors` (field → message). |
| `order_dispatch` | `{day, orderId}` | Only after release → **Dispatched**. The crew rolls at 07:00–09:00 on the basic start date (or 30 min after dispatch when that is on or after the start), never before it: **En route**, **On site** 20 min later, and **Completed** when the order's duration is up, with the crew's outcome. |
| `order_complete` | `{day, orderId, outcome, note?}` | Your structured outcome (below), on the day the crew works the order: it replaces the crew's. Before the start, or after the crew completed it on an earlier day, it is refused ("already completed by field crew FIELD-1 at …"). An older action list's `{note}` alone still replays as a remark. |
| `check_read` | `{day, caseId, orderId?}` | A decision: releases the case's read with its check read (see "Cases"), method `field_read`. |
| `device_replace` | `{day, meterId, deviceId, installDate, initialRead, removalRead?, note?, caseId?}` | A new device and register on an installation's meter; see "Devices". |
| `note` | `{day, caseId, text}` | A case note (required text, ≤ 600 characters), listed in the case view's `notes`. |
| `assign` | `{day, caseId, assignee}` | The case's owner and assignee. |
| `invoice_hold` | `{day, caseId \| accountId, note}` | Holds the account's invoices: released documents wait (`INVOICE_DEFERRED`) instead of being invoiced. Opens an **Invoice Outsorts** case `CASE-{yymmdd}-H{nnnn}` (`BILLING` queue). One hold per account at a time. |
| `invoice_unhold` | `{day, caseId \| accountId, note}` | Removes the hold (the hold case resolves); held documents go to the next 20:00 invoice run. |

Release rules (the Studio's `validateFieldOrder`, enforced by the engine; `GET /api/m2c/vocabulary` serves them as
data):
- required: order type, order description, planning plant, planner group, main work center, activity type, basic
  start and finish, priority, notification long text, operation, estimated duration, access / dispatch instructions
  (person responsible, contact name and telephone, downtime and components are optional);
- choices: order type, planning plant (the town's, e.g. `SM01 · Small Town`), planner group, work center, activity type and
  priority must be one of the vocabulary's values;
- dates are `YYYY-MM-DD`: start on or after the action's day and in 2026, finish on or after start;
- duration is a positive number of minutes (at most 1,440);
- each component needs a description, a positive quantity and a unit (`EA` or `M`).

Lifecycle rules: dispatch only a released order; complete only a dispatched one, on the day its crew works it (on or
after its start); only a Draft can be saved. Reopening is the viewer's: `POST /api/m2c/order` with the source
(`sourceCaseId` or `readId`) returns the existing order, or `order: null` with a suggested form (`proposal`). There
is never a second order for a source: saving again from the same source edits the same draft, and an order raised on
the same read from another path (its case, or the read) is refused.

**Field outcomes.** `order_complete` takes `outcome` `{kind, ...}` (`GET /api/m2c/vocabulary` serves them as
`order.outcomes`) and an optional comment `note`:

| `kind` | Fields | Write-back |
|---|---|---|
| `read_taken` | `value` (register, ≥ 0), `date` (from the basic start to the action day) | A check read for the order's register |
| `read_confirmed` | none | The reported read is the check read (a read that came in) |
| `meter_exchanged` | `deviceId`, `installDate`, `initialRead`, `removalRead?` | A device replacement (see "Devices") |
| `no_access` | none | Recorded on the cases |
| `defect_found` | `text` (≤ 600 characters) | Recorded on the cases |

The order's `outcome` (`field-order/1.0`) is `{kind, label, text, by, at, ...fields}`: `by` is `you` or the crew
(`FIELD-n`), `text` one line ("Read taken: 4,182.000 on 2026-07-14"). The crew's simulated outcome follows the meter
it finds: no access (a walked meter, at the town's `reading.manual_no_access`, unless the order is an access
investigation); a faulty meter exchanged (meter exchange and meter investigation orders) or reported as a defect;
a read taken when the read was missing or wrong; else the read confirmed. Each case the order covers on another
register gets the crew's read of that register. `completable` on the order (and `order_complete` in the Field Work
case's `studioActions`) says whether your outcome applies today.

**Source cases stay open.** Creating an order does not release the source reading or resolve the source case: the
case keeps its queue and category and links the order (`linkedOrderIds` on rows, `orders` in the case view). Your
first Studio action on a case (an order, a note, a hold) makes you its owner; `assign` gives it to someone else.
**An owned case waits for its owner**: RPA, analysts, supervisors and the simulated field crews leave it alone until
you decide it (`accept`, `override`, `estimate`, `check_read`). `escalate` and `field_order` are explicit hand-offs:
they clear the owner, and supervisors or the simulated crews then work the case as usual. An escalated case is not
taken from the supervisors by a note, an order or a hold; `assign` takes it. Field Work and hold cases are yours:
decisions do not apply to them (use `order_complete`, `invoice_unhold`). Completing a case while its order is open is
allowed: the order goes on, and the run's `warnings` carry a notice `ACT-n (notice): CASE-… was completed while field
service order WO-… is still Dispatched; the order goes on` (not a refusal).

**One visit per premise.** Several open cases on one premise (three consecutive-estimate cases, one per utility)
should cost one truck roll. Rows list them (`relatedCaseIds`), case views describe them (`relatedCases`, with
`coverable`), and an order (`order_save` `coverCaseIds`) or a `field_order` decision (`coverCaseIds`) covers them: the
covered cases link the order and get its outcome. The simulated workforce does the same (see "A day in the run").

**Your orders and the simulated field workforce.** The run already has field crews: a `field_order` decision (or an
analyst's) moves a case to the `FIELD` queue, and the crew pool visits up to `process.field_orders_per_day` premises
a business day (08:00–15:00); that visit settles the premise's open cases (a meter exchange or a special read).
Your field service orders do not use that pool or its capacity: they are owned, they roll when you dispatch them
(07:00–09:00 on the basic start date, any day), and the crew (or you) completes them that day without settling the
source case. Both kinds are `FIELD` work: they count in the `FIELD` queue, show as "field order" on the map, and
become `field_order` crew jobs in the operations timeline (yours carry `orderId`, and `coveredCaseIds` when the
visit covers other cases). On the map, a `field_read` visit still settles every open, non-Studio read case at the
premise.

**Invoice holds** mirror the Studio's `updateCase`: while a hold is on, releasing that account's billing outsort
(`accept` or `estimate` on a `BILLING` case) is refused. Releasing an outsort is `accept` with a reason in `note`.

### Clarification categories

Every worklist row and case view carries a `category`, derived from the engine's own type and queue (a resolved case
keeps the queue it was resolved from). `POST /api/process/queue` filters by `category`, and by `assignee`;
`My Assigned Cases` is the cases you own.

| Category | Engine meaning |
|---|---|
| MR Implausibles | Value exceptions (`HIGH_USAGE`, `LOW_USAGE`, `ZERO_USAGE`, `ERRATIC`, …) in `VEE_REVIEW` |
| Meter Read Follow-Up | Missing reads: `COMM_FAIL`, `NO_ACCESS`, `NO_READ`, `CONSECUTIVE_ESTIMATES` in `ESTIMATION` |
| Billing Outsorts | Billing blocks `HIGH_BILL`, `BILL_CREDIT`, `TRUE_UP` |
| Billing Errors | Billing blocks `RATE_CLASS` (wrong rate class in master data) |
| Invoice Outsorts | Your invoice holds (`INVOICE_HOLD` cases) |
| Field Work | Any case in the `FIELD` queue, and your field service orders (`FIELD_SERVICE` cases) |
| Low Income Process | Low-income referrals (`LOW_INCOME`, `COLLECTIONS` queue) by the call centre or you, open until the agency decides |
| Budget Bill Cases | Budget billing enrolments (`BUDGET_BILL`, `COLLECTIONS` queue) by the call centre or you, open until the plan is set up |
| Escalations | Any case in the `SUPERVISOR` queue (escalated by VEE, an analyst or you), whatever its type |

Field Work comes first: a case in the `FIELD` queue is Field Work whatever its type; then Escalations. A category is
a view of the engine's queues, so a case moves category only when it moves queue. The Studio's other categories (AMP,
Bill Correction, Bill Print Errors, Billing- see IT Supp, Invoice Errors) have no engine meaning yet: they are accepted
and return empty lists.

Rows also carry the read the case is about (`meterId`, `mruId`, `portion`, `unit`, `readType`, `observed`,
`previous`, `consumption`, `expected`, `scheduledReadAt`, `validationText`), so a reading list renders without
opening each case.

### Lookups for the query screens

- `POST /api/m2c/installation` `{installationId}` (Display Billing): the installation, its meters and registers
  (each meter with its current `deviceId` and its `devices` history), contracts with account and business partner,
  billing documents with lines, invoices, the accounts' ledgers and holds, its read results and its cases, as of
  `asOf`. 404 for an unknown id.
- `POST /api/m2c/read-document` `{readId}` (Display Meter Reading Results): the read (`meter-read/1.1`), its VEE
  decision, the installation, contract, account and partner, its case and order, and the register's reads to date.
  404 for an unknown read or one not taken yet.
- `POST /api/m2c/possible-entries` `{kind, query, page, pageSize ≤ 50}` (F4): `installation`, `read`, `account` or
  `premise` ids whose id or short text contains `query` (any case), paged; reads are those taken by `asOf`, newest
  first. Selecting an entry never executes the query.

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/m2c/settings?town=` | Schema, defaults (the town's with `?town=`), the run `seed` (default: the town seed), queues, exception vocabulary, action types, clarification categories |
| `GET /api/m2c/vocabulary?town=` | `m2c-vocabulary/1.0`: the field service order form as data (fields with label, tab, required, kind, bounds and choices; the town's planning plant; component units; stages and system status; the structured field `outcomes`), action types (`decisions`, `orders`, `caseWork`, `collections`, `devices`) and the `collections` block, queues and categories |
| *every run request* | takes `episodes` (see "Episodes"): dated setting overrides that make the run replay the year with each day's settings |
| `POST /api/m2c/summary` | `m2c-summary/1.0`: KPIs, cost (labour, system, CX, reads), carry, VEE precision/recall against truth, `billing` (with `collections`), `reliability`, `weather`, queues with aging and daily opened/closed/backlog, exception mix, RPA rules, one status per premise. `since` adds `window`, the figures for a period (see "Run statistics for a period") |
| `POST /api/process/queue` | Paged worklist: `queue` (incl. `BILLING`, `COLLECTIONS`), `category`, `assignee`, `status`, `sort` (`age` oldest first, `impact`, `confidence`, `created` newest first; ties by case id, so pages never overlap), `page`, `pageSize` ≤ 200, `type`, `commodity`, `search` (case, address, premise, account, meter or order id), `collector` and `createdOn` (an AMI collector's cases raised that day). `total` counts every matching row |
| `POST /api/m2c/collections` | `m2c-collections/1.0`: a Collections worklist (`disconnect`, `moratorium`, `rejected`, `overdue`), filtered, sorted and paged, rows with `actions` and `flags`, `counts` per list (see "Collections") |
| `POST /api/m2c/collections/account` | `m2c-collections-account/1.0` for one `accountId`; 404 for an unknown account |
| `POST /api/m2c/outage-followup` | `m2c-outage-followup/1.0`: last gasps, lost use and missed reads per premise per interruption (see "Follow-up worklists") |
| `POST /api/m2c/collector-groups` | `m2c-collector-groups/1.0`: AMI missed reads grouped by collector and day, and the town's collectors |
| `POST /api/m2c/case` | `work-case/1.0`: the case, its VEE decision, the read, 12-month history and `readHistory`, `expected`, `released`, the register check, `cause`, `createdBy`, `actionableFrom`, events (`event/1.0`) with causal edges, allowed decisions (`actions`) and Studio actions (`studioActions`), `notes`, linked `orders` (each with its `outcome` and `coveredCaseIds`), `fieldOutcome` and `checkRead`, `relatedCases`, the account's `invoiceHold`, and for a Field Work case its `order` (`truth: true` adds ground truth); see "Cases" |
| `POST /api/m2c/order` | `m2c-order/1.0`: a field service order (`field-order/1.0`: form, stage, SAP system status, history with who moved it, source, `coveredCaseIds`, reference installation/meter/contract, crew visit with `onSiteAt` and `doneAt`, structured `outcome`, `completable`) by `orderId`, or the order of a `sourceCaseId` / `readId` (`order: null` and a `proposal` when there is none) |
| `POST /api/m2c/installation` | `m2c-installation/1.0` for one `installationId` (see "Lookups") |
| `POST /api/m2c/read-document` | `m2c-read-document/1.0` for one `readId` |
| `POST /api/m2c/possible-entries` | `m2c-possible-entries/1.0`: F4 matches `{id, text}` for a `kind` and `query`, paged |
| `POST /api/m2c/premise` | Registers, every read to date, cases, `outages`, `billingDocuments`, `invoices` and `accounts` (balance and ledger) |
| `POST /api/vee/decision` | `vee-decision/1.0` for one `readId` |
| `POST /api/vee/export` | VEE input fixture for a `month` and optional `portion` |
| `POST /api/vee/scorecard` | `vee-scorecard/1.0`: VEE against simulation truth. Per anomaly type: recall and median days from onset to the first flag. Per exception type: precision |
| `POST /api/vee/dispositions` | Import decisions from an external VEE engine (m2c.vee v5) by `readId`. Each becomes the equivalent append-only action on the case holding the read: accept → accept; reject or estimate → estimate; an edit → override; escalate and field order map directly; review keeps the case open. Unmatched decisions are returned with a reason. |
| `POST /api/process/graph` | Activity Sequence nodes and edges for a month |
| `POST /api/process/costs` | Cost, carry and days to release by exception type |
| `GET /api/m2c/guide` | `engine-guide/1.0`: what the engine can do, the impact it can show, measured scale and limits, the gaps remaining, with the engine's live status (Configuration › Engine guide) |
| `GET /api/m2c/scenarios` | `m2c-scenarios/1.0`: the scenario library (groups, episode templates, what to watch, coming) |
| `POST /api/m2c/trend` | `m2c-trend/1.0`: the year month by month as of `asOf` (reads, cases and backlog, cost, billing, dunning, collections phases) with the run's `episodes` |
| `POST /api/m2c/contact` | `m2c-contact/1.0`: the contact centre as of `asOf` (KPIs, reasons, groups, the last 60 days, the year's incidents, notes); see "Contact centre" |
| `GET /api/m2c/tables` | `m2c-tables/1.0`: the Data pages' catalog: table groups, each table's source, description and columns (key, label, kind, facet, link), and the page limits (see "Data tables") |
| `POST /api/m2c/table` | `m2c-table/1.0`: one page (≤ 500 rows) of a table as of `asOf`, filtered (`search`, `filters`), sorted (`sort`, `desc`) and paged; rows as arrays in `columns` order, `facets` over the whole table, `total` matching rows |
| `POST /api/m2c/table.csv` | one CSV page (≤ 5,000 rows, header on every page) of the same selection; a client stitches the pages |

Every response stays under the hosted 4.5 MB limit; `tests/test_m2c.py` checks this.

## Data tables

The Studio's **Data** tab (`#/data/<table>`) lists the town and the run as flat tables, built by `utilsim/m2c/tables.py`
and served by the three endpoints above (local and hosted). Master data comes from the town snapshot; run data from the
run *as of* the view date, so nothing from after that date appears. Every table has typed columns (`text`, `id`, `int`,
`num`, `money`, `pct`, `date`, `time`, `bool`), facet columns (distinct values with counts over the whole table) and
link columns (the record a value opens: `premise`, `installation`, `read`, `account`, `invoice`, `case`, `order`).
A request filters by facet value (`{"commodity": "water"}`, `""` for blank), by date prefix (`{"readDate": "2026-06"}`),
by number range (`{"consumption": "1000.."}`) or by text in a column, searches the row's ids, names and address, sorts by
one column (missing values last either way) and takes one page. Built tables are cached per run and view day.

| Group | Table | Source | Rows (small town, 5 Aug) |
|---|---|---|---|
| Customers | `premises`, `businessPartners`, `contracts` | town | 2,103 · 2,368 · 6,851 |
| Customers | `accounts` | both: master data plus balance, open and overdue invoices and the collections phase as of the date | 2,368 |
| Meters & reading | `servicePoints`, `mrus`, `readSchedules` | town | 6,085 · 21 · 252 |
| Meters & reading | `meters` (device on the slot, replacements), `registers` (reads to date), `installations` (rate billed now, bills to date) | both | 6,085 · 6,350 · 6,085 |
| Meters & reading | `reads` (every periodic read: register, consumption, VEE status, release, bill status), `usage` (billed use per register and month, year to date), `deviceChanges` | run | 45,054 · 6,350 · 25 |
| Billing & pricing | `tariffs` (one row per rate version: the run's rate change starts version 2), `tariffAssignments` | town/both | 12 · 6,851 |
| Billing & pricing | `billingDocuments`, `invoices`, `payments`, `ledger` (every posting with the running balance) | run | 43,184 · 15,491 · 14,199 · 33,369 |
| Collections | `dunning` (reminders, notices, disconnection notices, winter holds, returned payments), `collectionsAccounts` (every account with an invoice in its phase: current, overdue, reminder, overdue notice, winter moratorium, dunning hold, payment arrangement, disconnection notice, disconnected), `disconnections`, `collectionsWork` (arrangements, budget plans, dunning holds, low-income referrals) | run | 2,392 · 2,175 · 145 · 468 |
| Work | `cases`, `fieldOrders`, `interruptions` | run | 1,398 · your orders · the map's outages |
| Contact centre | `contacts` (every contact: reason, channel, outcome, wait, handle time, attempt, what caused it), `contactDaily` (each day's contacts, answered, hung up, service level, agents, cost), `yearIncidents` (the year's outages and leaks: premises out, hours, who could smell gas, contacts) | run | 1,630 · 217 · 17 |

`tests/test_m2c_tables.py` builds every table for the small town, bounds the pages (JSON and CSV under the hosted 4.5 MB), and
checks the counts against the run (reads taken, documents and invoices created by the date, usage against
`billed_use`, collections phases covering every account).

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
- **The run's day:** with the run linked, the timeline also carries `meterToCash`, which is what meter-to-cash does
  that day. Each step has an `at` (seconds since local midnight):
  - `ami`: the 02:00 collection, with `read` and `missed` premise ids;
  - `vee`: the 18:00 batch, with `flagged` premises (new value exceptions);
  - `bills`: the 19:30 billing documents;
  - `invoices`: the 20:00 invoices.

  The map shows a ring over each house at each step, and the operations panel lists the day.
- **Field orders:** when the request carries the meter-to-cash run (`m2c: {settings, actions}`), that run's truck
  rolls on the day become `field_order` jobs (`FIELD-n` crews, 45 min for an exchange, 20 for a special read, 10 more
  per extra case when one visit settles several: the job then carries `caseIds`).
  A field service order you dispatched becomes a job on its basic start date (never before it; the day you dispatch
  it when that is on or after the start) with its own activity (from the activity type: `special_read`,
  `meter_investigation`, `meter_exchange`, `access_investigation`), duration, label (the order description) and
  `orderId`; its `caseId` is the Field Work case, and `coveredCaseIds` the cases the same visit covers. The timeline
  replays the stored action list leniently: an action that no longer applies is skipped, never a 422. The viewer
  refreshes the map's operations day after each Workspace action, so an order dispatched for today shows in the Field
  operations panel at once.

The viewer keeps one run day for the map and the worklists. "Watch the truck roll" on a field-order case moves the
map to that day and follows the van, and a field visit on the map is reported back as `field_read`.

### Outages from the map

Break a pole or a main on the map, or let a background incident happen, and the outage reaches meter-to-cash. The timeline's `interruptions` list who lost
which service and when; the viewer keeps them per operations day and sends them as the run's `outages`. In the run:
- **Use stops:** each register loses its normal consumption for the hours without service (an electric outage also
  stops PV export), so the following reads, bills and true-ups are lower.
- **AMI needs power:** an electric AMI meter without power at its 02:00 read misses it (`readReason`
  `SIM_POWER_OUTAGE`). The `COMM_FAIL` case is caused by an `AMI_LAST_GASP` event in its Activity Sequence and is
  estimated like any missing read. Water and gas endpoints run on batteries.
- **VEE knows:** with `vee.oms_events` (default on), the hours without service lower the expected use, and the
  context test's rationale names them. Turn it off to see what an outage does to low-usage flags when VEE is not
  told.
- **Silent collectors:** an outage with `utility: "ami"` is an AMI collector outage from operations (a background
  incident; see CONTRACT.md "Background incidents"). Service goes on and nothing stops flowing, but every AMI meter
  (any commodity) at its premises misses a read that falls inside it (`reasonCode` `SIM_COLLECTOR_OUTAGE`); the
  `COMM_FAIL` case is caused by an `AMI_COLLECTOR_OUTAGE` event. A collector that fails in the evening is repaired in
  the next day shift, so the night's 02:00 reads are the ones it costs. It is not in `reliability`; a premise view
  lists it among its `outages` with `utility: "ami"`, `collectorOutage: true` and no use lost.
- **Reliability:** the summary's `reliability` reports interruptions, customers interrupted, customer-minutes, SAIDI
  minutes per customer served, use lost and AMI last gasps, per utility. A premise view lists its `outages`.
- **Follow-up:** `POST /api/m2c/outage-followup` lists, per premise per interruption, the last gasp, the use lost and
  the reads it cost with their missing-read cases; `POST /api/m2c/collector-groups` shows a collector outage as one
  group of cases (see "Follow-up worklists" and "The AMI collector behind a missed read").

The morning's field orders for a day never depend on that day's own outages, so linking the two runs cannot loop.
The day's read outcomes and its `meterToCash` cycle do include them: a pole broken at 01:40 shows on the card as
missed AMI reads, and its comm-fail cases and held bills match the Workspace.
A day's outages stay after you move the map to another day or reload; "Reset engine run" clears them.

**Days pass on the map.** The map, the operations day and the Workspace's run date (`#ws-asof`) are one date. Playing
past midnight starts the next day without a pause: once the clock passes about 22:00 (earlier at the fastest speeds)
the viewer asks for tomorrow's timeline in the background (the same request as the day's, with no commands and the
run's current context) and applies it at midnight at once, recording the new day's background interruptions as above;
when that request has not landed yet, the day loads while the clock runs on from 00:00. The time bar's "+1 week" and
"+1 month" (a calendar month, clamped to the month's length) make the skipped days happen too: one
`POST /api/sim/days` (CONTRACT.md) replays them with no commands, each day's `interruptions` are recorded as that day's
background outages (a day you worked keeps its own), the run date moves to the last day and its timeline loads as
usual. The year ends on 31 December 2026.
