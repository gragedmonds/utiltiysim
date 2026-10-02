# Studio billing pages: what drives them

This is for Astra's reworked Utility Studio UI. It lists, for each billing and meter-reading page, the engine call
behind it, the fields it shows and how the page changes as the run date moves. The production viewer's
`packages/town-viewer/dist/workspace.js` is a working reference; layout and styling are yours to change.

## 1. One run date

Everything on a billing page is the engine's state **as of the run date** (`asOf`, `YYYY-MM-DD`, within 2026). The
map, the operations day and meter-to-cash share that one date:

| Who moves it | How |
|---|---|
| Map time bar | Playing past midnight rolls the run to the next day. **+1 day** jumps a day at the same time of day. Speeds go up to 14,400× (a day in about 6 s). |
| Map operations panel | The **Run day** field. |
| Workspace status bar | The **Run date** field and **+1 day**. |

After a date change every open page reloads for the new day: the case list, a case, the VEE list, Run statistics, a
billing or reading record, and an open order. A record that did not exist yet on the new date (a reading taken
later) sends you back to its query with a message.

### What a day does

Each step happens at a fixed local time; fast-forwarding a day replays all of them:

| Local time | Step |
|---|---|
| About 02:00 | AMI meters in the day's portion report overnight. Collector or comm failures become missing reads. |
| From 08:00 (MANUAL) and 09:00 (AMR) | Walked MANUAL routes and AMR drive-by routes read their meters. A no-access stop becomes a missing read. The start hours are run settings. |
| 18:00 | VEE batch: suspect reads become clarification cases and are held back from billing. |
| 19:30 | Billing: one billing document per contract for every read released that day. A blocked bill becomes a BILLING case: high bill, large credit or wrong rate class. |
| 20:00 | Invoicing: one invoice per account, issued after the print lag and due `due_days` later. The account must not be on hold. |
| Later days | Payments arrive by payer profile. Overdue invoices get a reminder, then a notice with a late fee, then a disconnect notice. |

On a portion's read day you see new reads, documents and invoices for its installations. On other days the billing
pages change only through payments, dunning and the cases you work.

### Your actions

Your Studio actions (`accept`, `override`, `estimate`, notes, holds, orders…) are dated with the run date and land at
**09:00** that day. Actions are append-only: you cannot act on a date earlier than your last action. A case the
engine raised later in the day (VEE at 18:00, billing at 19:30) can be worked from the next day; **+1 day** is the
quick way there. Every case row and case carries that date as `actionableFrom`, and until then the case lists no
`actions` or `studioActions`. An action on a case that is not open at 09:00 is refused (HTTP 422) with the reason,
e.g. `CASE-260706-K3M9QX was raised at 18:00 on 2026-07-06; work it from 2026-07-07` or `… was already completed by
RPA at 19:00 on 2026-07-06`. Case ids are stable: the same case keeps its id when outages or settings change the run
around it.

## 2. Requests

Every page call is a `POST` with the run's identity in the body. `EngineM2C` (`packages/town-viewer/dist/m2c.js`)
builds it:

```json
{"town": "ayr", "asOf": "2026-07-16", "actions": [ ... ], "settings": { ... }, "outages": [ ... ]}
```

`actions` is the analyst's append-only list, `settings` the run overrides (Config → Process & costs), and `outages`
the interruptions the map's operations days produced. The engine replays the year deterministically. The same body
always gives the same answer, so pages can be cached by body.

A refused action returns **HTTP 422**. Its `detail` is a string, or for order release
`{message, fieldErrors: {field: message}}`. The client removes the refused action again.

## 3. Pages and their data

### Display Billing (query → record)

- **Query:** a blank Installation field, F4 and an explicit Execute.
  - F4 calls `POST /api/m2c/possible-entries {kind: "installation", query, page, pageSize ≤ 50}` and returns
    `{total, entries: [{id, text}]}`.
  - Execute calls `POST /api/m2c/installation {installationId}`, which gives HTTP 404 for an unknown id.
- **Record (`m2c-installation/1.0`):**
  - Header fields: `installationId`, `premiseId`, `address`, `commodity`, `rateCategory`, `billingClass`, `mruId`,
    `portion`, `status`, `servicePointId`.
  - Lists: `meters[]` (each with `registers[]`, the current `deviceId` and its `devices[]` history), `contracts[]`,
    `accounts[]` (each with `businessPartner`, `balance`,
    `ledger[]` and `invoiceHold`), `billingDocuments[]`, `invoices[]` (each with `payments[]` and `dunning[]`),
    `reads[]`, `cases[]`.

| Screen | Fields |
|---|---|
| **Bil. Order** | One row per entry in `reads[]` (newest first): `scheduledReadAt`, `billStatus`, `contractId`, `readReason`. Under the table, the block or hold: an open `cases[]` entry with `queue: "BILLING"`, or `accounts[0].invoiceHold`. |
| **Bil.Time** | `contracts[]`: `contractId`, `status`, `validFrom`, `validTo` (none means open-ended), `accountId`. |
| **Documents** | `billingDocuments[]`: `id`, `periodStart`, `periodEnd`, `contractId`, `invoiceId`, `totalAmount`, `billStatus`, `estimated` (built on an estimated read; `estimatedReadIds` names them), `reversedAt`, `version`, `replaces`. Below it, `invoices[]`: `id`, `issuedAt`, `dueAt`, `totalAmount`, `invoiceStatus`, `paidAt`, `estimated` (`estimatedBillingDocumentIds`). |
| **Billing document** | One `billingDocuments[]` entry. `lines[]` has `type`, `description`, `quantity`, `unit`, `rate` and `amount`, plus `subtotal`, `tax` and `totalAmount`. A rebill has `replaces`; a reversed document has `reversedAt`. |
| **Print document** | One `invoices[]` entry: `billingDocumentIds[]`, `payments[]` (`at`, `amount`, `status`), `dunning[]` (`at`, `type`, `label`). |
| **Contract** | The current entry in `contracts[]`, plus from `accounts[0]`: `paymentMethod`, `budgetBilling`, `balance`, `ledger[]` (`at`, `type`, `amount`, `ref`) and `invoiceHold`. |
| **Installation / Device** | `meters[]` (`meterId`: the meter slot, `deviceId`: the device in it as of the run date, `technology`) and `registers[]` (`registerId`, `direction`, `unit`, `digits`, `multiplier`). **Device history** is `devices[]`, oldest first: `deviceId`, `installedAt` (null for the snapshot's device), `removedAt`, `initialReads` and `removalReads` (by register id), `by` (`you` or a field crew `FIELD-n`), `orderId`, `caseId`, `current`. **Replace device** is `device_replace {meterId, deviceId, installDate, initialRead, removalRead?, note?}`: the new register counts from its initial read and later reads are diffed against it; an install date before a read already released on the old device is refused (422 with the date). |
| **MR results** | `reads[]`: `scheduledReadAt`, `registerValue`, `consumption`, `unit`, `readType`, `veeStatus`, `billStatus`, `deviceId`. A missed read has `cause` (`label`, `outageStart`, `outageEnd`, `reason`): the Note column says e.g. "Missed: power outage 00:00–04:00 (AMI last gasp)". Opening one calls Display Meter Reading Results with the read's `id`. |

### Display Meter Reading Results (query → record)

- **Query:** F4 is `possible-entries` with `kind: "read"`. Execute calls `POST /api/m2c/read-document {readId}`,
  which gives HTTP 404 for an unknown read, or one not taken yet on the run date.
- **Record (`m2c-read-document/1.0`):**
  - The reading itself is `read` (`meter-read`: `registerValue`, `previousRegisterValue`, `consumption`,
    `readType`, `readStatus`, `readReason`, `veeStatus`, `sapValidationCode`, `billStatus`, …).
  - A missed read has `reasonCode` and `cause {code, label, reason, outageStart?, outageEnd?, …}`: show e.g.
    "missed: power outage 01:00–03:20" from `cause.label`, `outageStart` and `outageEnd`, or `cause.reason`.
  - A register that went backwards (not a rollover) has `consumption: null`, `registerRegression: true` and the
    negative `registerDelta`; `rolloverFlag` is true only for a real rollover.
  - `deviceId` is the device the read was taken on. A read period with a device replacement has `deviceChange`
    (`deviceId`, `previousDeviceId`, `installedAt`, `initialRead`, `removalRead`, `oldRegisterUse`): its
    `previousRegisterValue` is the new register's initial read, and its consumption adds the old register's last
    stretch (`oldRegisterUse`).
  - Its VEE decision is `decision`: `tests[]` (`test`, `outcome`, `contribution`, `rationale`), `confidence`,
    `disposition`, `expectedConsumption`.
  - Linked records: `installationId`, `contractId`, `accountId`, `businessPartnerId`, `premiseId`, `address`,
    `meterId`, `registerId`, `case`, `order`.
  - The register's other readings are `history[]` (`readId`, `readDate`, `registerValue`, `readType`, `veeStatus`,
    `cause` for a missed one, so the history can say "missed: power outage" too).

Astra's navigation rules hold. A reading opened from Billing Details may go back to it. Installation, contract and
billing pages reached from a standalone reading go through the installation query.

### Clarification cases (the billing ones)

- **Lists** come from `POST /api/process/queue`.
  - Body: `{status: open|resolved|all, queue?, category?, assignee?, sort, page, pageSize ≤ 200}`. `sort: "created"`
    is newest first; `total` counts every matching row, so `ceil(total / pageSize)` pages hold them all.
  - Billing categories: **Billing Outsorts** (HIGH_BILL, BILL_CREDIT, TRUE_UP), **Billing Errors** (RATE_CLASS) and
    **Invoice Outsorts** (invoice holds). **Escalations** lists every case in the SUPERVISOR queue (escalated by VEE,
    an analyst or you), whatever its type: a supervisor works it after the pickup lag (run settings
    `process.supervisor_queue_days_min`–`max`), unless you take it (`assign`) and decide it yourself. A note, an order
    or a hold on an escalation does not take it from the supervisors.
  - Rows also carry `actionableFrom`, `createdBy` / `createdByLabel` (AMI head-end, meter-reading route, VEE batch,
    billing run, you), `cause` (missing reads), `registerDelta`, `registerWentBackwards`, `previousEstimated`,
    `releasedMethod` and `relatedCaseIds` (the other open cases at the same premise: show "2 related cases" with links).
- **Case** comes from `POST /api/m2c/case {caseId}`.
  - Billing-related fields: `queue`, `type`, `category`, `impact`, `invoiceHold`, `notes[]`, `orders[]`,
    `billingDocument`.
  - Decision data (docs/M2C.md "Cases"): `expected {registerValue, consumption}`; once resolved, `released
    {registerValue, consumption, method, by, at}` (`method`: `as_read`, `corrected`, `estimated`, `field_read`; a
    billing case adds `billingDocumentId`, `totalAmount`); `registerDelta`, `registerWentBackwards`,
    `previousEstimated`; `readHistory[]` (`readId`, `date`, `register`, `consumption`, `type`, `estimated`, `method`,
    `veeStatus`, `caseId`; up to 13 periods); `cause {code, label, reasonCode, reason, lastGaspAt?, outageSince?}` for
    a missing read.
  - Field work: `relatedCases[]` (`caseId`, `label`, `commodity`, `queue`, `coverable`: a field order from this case
    can cover it); `fieldOutcome` (the newest field order outcome written back: `orderId`, `kind`, `label`, `text`,
    `by`, `at`, and the kind's fields); `checkRead {value, orderId}` when that outcome gives the read a check read.
    `check_read` in `actions` releases the read with it (method `field_read`).
  - `actions` lists the decisions allowed today; `studioActions` lists the case work allowed today. Both list only
    what the engine accepts from an action dated the run date, so both are empty before `actionableFrom`.
  - Show a button only when its action is in one of these lists. For example, while an account is on hold, `accept`
    (the outsort release) disappears; on a register that went backwards `accept` is not offered (estimate, override
    with the right value, or a field order); a missing read offers only estimate, field order, escalate and, after a
    field order took a read, `check_read`.
  - Completing a case while its order is still open is allowed; the summary's `warnings` then carry `ACT-n (notice):
    … the order goes on`. Warn about it, never block it.
  - Show a backwards register as `registerDelta` (negative), not as the read's `consumption`, which a meter data
    system records as a rollover.
- **Releasing a billing outsort** is `accept` with a `note`, the reason. Holds are
  `invoice_hold {caseId | accountId, note}` and `invoice_unhold {caseId | accountId, note}`.
- **Who releases what.** RPA releases a high bill or a large credit only up to the run setting
  `billing.outsort_auto_release_max` ($500 by default, Config → Billing & collections); larger outsorts, and every
  `TRUE_UP` block (an estimate true-up beyond `billing.trueup_max_ratio` × the period's expected use), wait in the
  queue for an analyst or you.
- **Practising outsort release.** Set the run setting `billing.billing_queue_worked_by` to `you` (Config → Billing &
  collections). No analyst or RPA then works the BILLING queue, so every high bill, credit, true-up and rate-class
  block waits for you. The default, `analysts`, keeps the calibrated run.

### Field service orders

- **The form's vocabulary** comes from `GET /api/m2c/vocabulary?town=`: fields (label, tab, required, kind,
  choices, bounds), component units, stages and system statuses, and `order.outcomes` (the structured field outcomes
  and their fields).
- **Opening an order:** `POST /api/m2c/order {orderId | sourceCaseId | readId}` returns the order, or `order: null`
  and a prefill `proposal` when that source has none yet.
- **One visit per premise:** when the case has `coverable` related cases, offer to cover them; send their ids as
  `coverCaseIds` with the first `order_save`. The order lists them (`coveredCaseIds`) and its outcome is written back
  to each.
- **Steps:** `order_save`, `order_release`, `order_dispatch`, then the order moves on its own: on its start date
  (never before) the crew rolls at 07:00–09:00 (En route, `REL DISP ENRT`), is On site (`REL DISP ONST`) and
  completes it (`TECO`) with a simulated outcome when the visit ends. `order_complete {orderId, outcome, note?}`
  records your outcome instead, on the day the crew works the order (`completable` on the order says when); a later
  completion is refused. The outcome kinds: `read_taken {value, date}`, `read_confirmed`, `meter_exchanged
  {deviceId, installDate, initialRead, removalRead?}`, `no_access`, `defect_found {text}`. The order's `outcome` is
  `{kind, label, text, by, at, ...}` (`by`: `you` or the crew), and `history[]` says who moved each stage (`by`).
- **On the map:** a dispatched order becomes a field van on its start date. The viewer refreshes the map's
  operations day after every Workspace action, so an order dispatched for today appears in the Field operations panel
  at once. "Watch the truck roll" opens that day on the map.

## 4. Statistics

`POST /api/m2c/summary` gives the KPIs as of the run date: reads, queues with aging, costs, billing (`documents`,
`blocked`, `billed`, `billingError`, `invoices`, `collected`, `receivable`, `overdue`, `dunning`) and service
interruptions. `POST /api/vee/scorecard` scores VEE against the simulation's truth.
