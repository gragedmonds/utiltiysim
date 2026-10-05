# The digital twin: start from the outcomes

The Studio's first path builds a utility from the ground up: a town, services, staffing, a scenario, and the year's
KPIs come out of the replay. The twin is the second path, run in reverse. A utility knows its outcomes (invoice
timeliness was 99 percent and fell to 94, exceptions rose to 10,000 a year, there are 8 billers and 50,000
customers) and asks the engine to fill in everything else so that the replayed year reproduces those figures. The
result is an ordinary setup proposal, opened, locked in and explored like any other, plus a report of what the twin
shows for every KPI, which levers it moved and how far each observed figure was reproduced.

Engine module `utilsim/twin/`, command `utilsim twin`, API `GET /api/twin/dictionary` and `POST /api/twin/fit`
(`twin-fit/1.0`). The fitting and comparison figures are part of the Studio's KPI catalogue under the same ids
(`utilsim/m2c/kpis.py`, [KPIS.md](KPIS.md)), marked `twin`. The Studio exposes this through **Match existing metrics**; see "Studio" below.

## What goes in

**Known inputs** are set directly, never fitted:

| Input | Becomes |
|---|---|
| `customers` (contract accounts in the year) | Homes, through the calibration town's accounts-per-home ratio (about 1.2 to 1.8 depending on the town). Above the live engine's limit (10,000 homes locally, 6,000 hosted) the utility runs as internal checkpoints of up to 10,000 homes from the local run page, as the wizard's large sizes do. |
| `billers`, `supervisors`, `agents` | `process.analysts`, `process.supervisors`, `contact.agents`. A town that holds part of the utility (the calibration town during the fit, a district in the proposal) gets its share of their hours: 8 billers over four areas is two analysts at six hours a day in each. The engine's smallest capacity is one analyst at half an hour a day; when the share falls below it the report says so and suggests a larger calibration town. |
| `services` | `customers_billing.services` (what the utility provides). |
| `townOverrides` | Generation settings the utility knows (AMI route share, payer mix, housing); the calibration town is generated with them (a few seconds) instead of read from the packs. |
| `changedOn`, `ramp` | The day the "after" figures begin and how many days the change took to build up. |

**Observed KPIs** come from the dictionary (`GET /api/twin/dictionary`, `utilsim twin --dictionary`). Each is pinned
to one measure of a run, because a utility's "timeliness" can mean several things and the twin must say which one it
reproduced:

| KPI | Engine measure | Levers that move it |
|---|---|---|
| `invoice_timeliness` | Share of scheduled account-month cycles fully issued within `timelyDays` (5) of each service scheduled read, including print lag and upstream holds | invoice issue lag, automation, VEE strictness, pickup lag, analyst hours, missed reads, field capacity |
| `missed_read_share` | Scheduled billing reads with no read taken | missed reads |
| `estimated_read_share` | Scheduled reads released to billing as an estimate | missed reads, field capacity, anomalies |
| `exceptions_all` | Every case opened, per 1,000 accounts a year | missed reads, anomalies, VEE strictness |
| `exceptions_worked` | Cases an analyst, a supervisor or you touched, per 1,000 accounts a year (what a billing team counts) | automation, VEE strictness, anomalies, missed reads |
| `exceptions_vee` | Cases VEE's own tests raised, per 1,000 accounts a year | VEE strictness, anomalies |
| `case_backlog` | Cases open at the end of the window, per 1,000 accounts | analyst hours, automation, pickup lag, VEE strictness, missed reads |
| `days_to_release` | Calendar days from the read to its case releasing it | pickup lag, automation, analyst hours, field capacity |
| `days_to_pay` | Days from an invoice's issue to payment in full | none yet (payer behaviour is a town setting) |
| `collected_share` | Payments in the window over the amount invoiced | none yet |
| `billing_error_share` | Net issued invoices against simulated truth, over absolute net amounts issued | VEE strictness, anomalies |

The picker also includes all 28 billing-assurance and reading-audit KPIs from
`utilsim/m2c/billing_quality.py`, grouped by family. The same IDs, labels, definitions and calculations
serve the Command Center and the fitting wizard. Estimated, consecutive estimated, consecutive zero-use
and delayed **invoices** are measured at customer issue, not upstream document creation.

The dictionary labels each KPI `adjustable` or `comparison`. Comparison-only observations are retained
and reported as `matched`, `comparison` or `unmeasured`; the fitter does not claim to change structural
reference defects, move counts or other inputs without a supported lever. Each row explains this before
submission. Raw count inputs refer to the entire utility: calibration counts are scaled by customer
accounts (and disclosed as estimates), while shares are unchanged. Count tolerances default to five
percent of the target, at least one. Event measures use the selected window; active and outstanding
counts are snapshots at its end. Sequence checks retain earlier invoice history across window boundaries.

A KPI is a steady `value`, or a `before` and an `after` around `changedOn`. Rates are per 1,000 accounts a year;
`absolute: true` gives the utility's own yearly total instead (10,000 exceptions over 50,000 customers is 200 per
1,000). Each KPI has a tolerance (half a percentage point for a share, half a day, 5 percent of a rate and at least
10 per 1,000) that the spec can override.

**Levers** are the handful of named, one-dimensional causes the fit may move. Fitting eight explained levers rather
than a hundred settings keeps the answer identifiable: "missed reads at 2.4 times the default" says what happened.
Every lever's default reproduces the engine's defaults exactly, so a lever the fit never moved changes nothing.

| Lever | Sets | Range |
|---|---|---|
| `print_lag` | `billing.print_lag_days`, creation to customer issue | 0 to 10 days |
| `missed_reads` | the AMI, drive-by and manual missed-read chances, together | 0 to 12 × default |
| `anomalies` | every injected anomaly rate | 0 to 8 × default |
| `vee_strictness` | high and low tolerances and the auto-accept bar, from the scenario library's loosened (0) through the defaults (0.5) to its tightened battery (1) | 0 to 1 |
| `automation` | `process.rpa_coverage` | 0 to 1 |
| `pickup_lag` | the analyst queue wait (shortest; the longest is two days more) | 1 to 10 days |
| `analyst_hours` | `process.analyst_hours_per_day`; known, not fitted, when the spec gives the billers | 0.5 to 10 |
| `field_capacity` | `process.field_orders_per_day` | 0 to 100 |

All levers are run settings: the fit replays the same town and never regenerates it. `fixed` holds a lever at a
value; `exclude` keeps the fit off it.

## How the fit works

1. **Size.** Customers become homes at the calibration town's accounts-per-home ratio; homes above the live limit
   become districts. The known people are scaled to the calibration town for the fit and to a district (or the one
   live town) for the proposal.
2. **Search the free levers on the calibration town.** Every replay measures every KPI in every window the spec needs
   (the year; before and after `changedOn`). Each round takes the targets most off-target first and, for each, the
   first free lever that moves it in the needed direction and is not at its bound: a probe step (the lever's `step`),
   a secant step to the target damped to twice the probe (a KPI that moves in steps on a small town would otherwise
   fling a lever to a bound), and the candidate with the smallest total residual over every target is kept. A lever
   that fails to move a KPI is not tried again for it. The search stops when every target is within tolerance, a round
   moves nothing, or the replay budget (`budget`, default 20) is spent.
3. **Fit what changed as an episode.** With `before` and `after` figures, the base levers are fitted to the whole year
   at the `before` values, then held while the `after` values are fitted on the window from `changedOn` to 31 December
   with one episode starting there (ramped over `ramp` days) whose settings are the levers that moved.
   A year replays from a cold start (no history yet: consecutive-estimate, trend and collections cases take months to
   build), so a rate over the first months runs below the whole year's. The `before` figure is therefore fitted as a
   whole year at the base levers, the `after` figure over its own window with the episode in force, and the report's
   `windows` say so; `twin.before` shows the fitted year's first months for information.
4. **Report.** For each observed figure: given, target (in fit units), start (the defaults), achieved, residual,
   tolerance, status (`fitted` within tolerance, `close` within three, `unfitted`, `unmeasured`), the levers that
   moved and a note when it could not be fitted (no lever moves it, every lever at a bound, the budget ran out). `twin`
   holds every KPI's value over the year, before and after. `levers` lists each lever's state (free, fixed, excluded,
   known), value and settings. `proposal` is the setup.

The fit is deterministic: the same spec gives the same twin. One replay takes about 2 seconds on the village, 8 on
the 1,900-home small town (the default calibration) and longer under stress; a 20-replay fit on the small town takes
three to five minutes. The hosted engine allows 60 seconds a request, so `POST /api/twin/fit` there wants the village
and a budget near 10; the local app and `utilsim twin` have no such limit.

```bash
uv run utilsim twin --customers 50000 --billers 8 --changed-on 2026-04-01 --ramp 30 \
    --kpi invoice_timeliness=0.99:0.94 --kpi exceptions_worked=8000:10000,abs --out out/twin.json
uv run utilsim twin spec.json --calibration village --budget 10      # a spec file, flags added to it
uv run utilsim twin --dictionary
```

The proposal is `api/_agent_config.py`'s `Proposal`, the object the wizard and the conversational guide produce, and
it has passed the same validation (`POST /api/setup-agent/validate`) when the API returns it. Base settings are the
fitted levers plus the known people scaled to the town they run in; `townOverrides` carry the homes (a district
template of 10,000 for a local utility) and any town settings the utility gave; what changed is one episode.

## What the first probe showed

Historical fit benchmarks used invoice creation and omitted cycles that had not reached invoicing. They are
not comparable with the version 2 invoice-issue measure. Refit observed targets with the new population: scheduled
account-month cycles, each service's own deadline, upstream holds and print lag. An estimated invoice can still be
on time; estimate quality is a separate measure. Print lag remains outside the twin's fitted levers.

## Limits

- Payment and collections figures are reported but not fitted: the payer mix is a town setting. A later slice adds
  town levers (regenerate once per candidate) or a run-scoped payment-stress setting.
- Rates per account carry from the calibration town to the utility; counts scale with accounts. Rare events on a
  small calibration town are noisy: fit a 50,000-customer utility on the small town or larger, not the village.
- A district's whole-number analysts cannot express a small share of a pool below one person at half an hour a day;
  the batch's shared-workforce mode (one pool, a float team) is the eventual answer and is not yet exposed to the
  Studio's local jobs.
- The cold start above means an "after" window compares with a base year that includes its own quiet first months.
  A later slice can calibrate on a chained second year (the engine opens it on the first year's close) to remove the
  cold start at twice the replay cost.
- The fit moves one lever at a time towards each target. Several levers can explain the same figure (fewer exceptions
  worked can be more automation or looser VEE); the dictionary's order decides which is tried first, and `fixed` or
  `exclude` steer it. A later slice offers two or three candidate explanations side by side.

## Studio

The five-step wizard starts with **Build from the ground up** and **Match existing metrics**.
The metrics path asks for accounts, known billing staff, the change date, and before/current/target
values from the engine dictionary. Percent fields convert to engine shares. Historical calibration
and target calibration run separately, with the latter added as a future episode. The review displays
requested and achieved values with fit status and model limits. Settings, episodes and calibration
observations are kept with the simulation. Fitting runs entirely in the local Python engine; no cloud
assistant or API key is required. It uses a small calibration town, so the full run is still needed to
evaluate the result at utility scale.
