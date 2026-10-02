# Meter-to-cash (M2C)

Reads, VEE and exception work queues for every premise, replayed by the engine for calendar 2026. Billing documents,
invoices, payments and dunning are next (PR B) and reuse the same run, settings and actions.

## Run model

A run is stateless and deterministic: `(town, settings, actions)` gives the same year every time.
- `settings` overrides the run-scoped config groups `process`, `anomalies`, `reading` and `vee`. They never change
  the town id. `GET /api/m2c/settings` returns their JSON Schema, with units, bounds, effects and advanced flags.
- `actions` are analyst decisions from the viewer: `{id, day, type, caseId, value?}`.
  - `type` is one of `accept`, `override` (with a register value), `estimate`, `field_order` or `escalate`.
  - Actions are append-only by `day`. An action never changes anything before its day, so a reply for an earlier
    date stays valid.
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
7. **RPA** resolves exception types covered by `rpa_coverage`, taken in the order of `catalog.EXCEPTIONS`. Half are
   resolved the same evening; the rest at 07:00 the next business day.

## Reads

Every register is read once a month on its portion's business day. Missed reads by technology:
- AMI: `ami_missed_read`;
- AMR: `amr_missed_read`;
- walked (MANUAL): `manual_no_access`, then `no_access_repeat` while it stays missed.

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
4. **Process corroboration**: implausible-value cases on the register in the last 180 days.
5. **Context**: a vacant premise that consumes; walked reads.

Confidence is `1 − 2·Σ risk`. The disposition is decided in this order:
- a regression is rejected;
- confidence at or above `accept_confidence`: accept;
- below `reject_confidence`: reject;
- bill impact at or above `escalate_impact`: escalate;
- otherwise: review.

The real SAP `MRIndependantValidation` codes plug into `catalog.CODES`. `/api/vee/export` writes
`vee-input-fixture/1.1` (truth stripped) for an external VEE engine such as m2c.vee.

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/m2c/settings` | Schema, defaults, queues, exception vocabulary |
| `POST /api/m2c/summary` | `m2c-summary/1.0`: KPIs, cost (labour, system, CX, reads), carry, VEE precision/recall against truth, queues with aging and daily opened/closed/backlog, exception mix, RPA rules, one status per premise |
| `POST /api/process/queue` | Paged worklist: `queue`, `status`, `sort` (`age`, `impact`, `confidence`, `created`), `page`, `pageSize` ≤ 200, `type`, `commodity`, `search` |
| `POST /api/m2c/case` | `work-case/1.0`: the case, its VEE decision, the read, 12-month history, events (`event/1.0`) with causal edges, allowed actions (`truth: true` adds ground truth) |
| `POST /api/m2c/premise` | Registers, every read to date and cases (`billingDocuments` and `invoices` arrive with PR B) |
| `POST /api/vee/decision` | `vee-decision/1.0` for one `readId` |
| `POST /api/vee/export` | VEE input fixture for a `month` and optional `portion` |
| `POST /api/process/graph` | Activity Sequence nodes and edges for a month |
| `POST /api/process/costs` | Cost, carry and days to release by exception type |

Every response stays under the hosted 4.5 MB limit; `tests/test_m2c.py` checks this.
