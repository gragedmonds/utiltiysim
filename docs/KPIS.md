# KPIs: the figures a simulation watches

Every simulation watches a handful of figures: the person picks them when setting up ("What to test"), the setup
guide offers them as names while talking, the Command Center and Run statistics show them with their values, and
the Glossary explains what moves each one. The engine owns the list (`utilsim/m2c/kpis.py`), measures every figure
from a run, and defines each one with a window the simulation can set: an on-time bill is a bill released within
`kpi.on_time_bill_days` of its scheduled day (3 by default), a timely invoice within `kpi.timely_invoice_days` (5),
a case resolved in time within `kpi.case_resolution_days` business days (5).

## The catalogue

`GET /api/m2c/kpis?town=` returns `m2c-kpis/1.0`: `families` (id, title, what the family is about), `kpis` (one
entry per figure, below), `thresholds` (the current value, unit, title and bounds of every setting a definition
counts with, for that town's configuration) and `settingsGroup` (`kpi`). Each figure carries:

| Field | Meaning |
|---|---|
| `id`, `title`, `family`, `unit` | `share` (0 to 1), `days`, `minutes`, `seconds`, `per_1000_accounts_year`, `per_1000_accounts`, `currency_per_account`, `count` |
| `better` | `lower`, `higher`, or `context` (no universal good/bad direction) |
| `goals` | the wizard goals the figure belongs to (`reading`, `vee`, `billing`, `collections`, `contact`, `fieldwork`, `cost`, …); "everything" takes them all |
| `definition`, `formula` | what is counted, in words and as the engine computes it |
| `thresholds` | the `kpi.*` and other settings the definition counts with (`kpi.on_time_bill_days`, `contact.service_target_s`) |
| `settings` | `[path, direction]`: the run and town settings that move the figure; `+1` raises it, `-1` lowers it |
| `related` | figures that move with it |
| `where` | the Studio pages that show it |
| `twin` | one of the eleven figures the [digital twin](TWIN.md) fits from observed values |

The settings paths are the Config page's (`group.key`, with one level of nesting such as
`field.crew_meter.per_1000_premises`); `tests/test_kpis.py` keeps every path in the run or town schema and every
threshold a run setting with a default and bounds.

### The `kpi` settings group

Run settings (they apply to a run, never regenerate the town), proposed and edited like any other, locked with the
simulation and carried in its file:

| Setting | Default | Range | Counts |
|---|---|---|---|
| `kpi.on_time_bill_days` | 3 | 0–60 days | a bill is on time when released within this many days of its scheduled day, either side |
| `kpi.timely_invoice_days` | 5 | 1–60 days | an invoice is timely when created within this many days of the last scheduled read |
| `kpi.read_release_days` | 3 | 0–90 days | a held read is released promptly within this many days of the scheduled read day |
| `kpi.payment_grace_days` | 3 | 0–60 days | a payment is on time within this many days after the due date |
| `kpi.case_resolution_days` | 5 | 0–60 business days | a clarification case is resolved in time within this many business days |

Lateness counts whole days (`floor`), so a window of 0 days means "on the day". A tighter window lowers every
on-time share and raises nothing else; `test_a_runs_figures_and_how_the_windows_move_them` checks the direction on
`small_town`.

## Measuring a run

`POST /api/m2c/kpis` takes the same body as every meter-to-cash request (`town`, `asOf`, `settings`, `episodes`,
`seed`, `year`, `previous`, `staffing`, `actions`) plus `kpis` (ids; all when omitted) and returns
`{schemaVersion, asOf, accounts, values, thresholds}`: `values` by id, year to date as of `asOf`, and `thresholds`
as the run counted them. An unknown id is a 422. The Studio calls it for the simulation's chosen figures on the
Command Center (`year-page.js`) and on Run statistics (`workspace.js`), both through `kpis.js`. The Command Center requests the complete catalogue regardless of the wizard selections.

## The Studio

- **Setting up.** The "What to test" step lists the figures that belong to the chosen goals as chips
  (`setup-config.js` `kpiMarkup`); up to twelve can be chosen, and changing the goals filters the choice. The review
  step and the proposal summary say "Watching: …".
- **Talking it through.** Claude receives the catalogue (`kpiCatalogue` in its context) and sets the proposal's `kpis`
  when the person names an outcome; while typing or dictating, the catalogue's matches for the last few words show
  above the box, and a click writes the exact title in (`setup-agent.js` `paintAutofill`, `kpis.js` `matchKpis`).
- **Watching.** After a run the Command Center lists every KPI in nine business groups, alongside each group's monthly charts (`kpi-dashboard.js`). Each group can be collapsed or reached from the group navigation. Chosen
  figures have a Watched badge; all other figures remain visible even when the wizard selected none. Definitions,
  formulas and counting windows expand beside each value. Changing the date, episodes or an existing decision
  reloads the complete set and discards superseded responses. Run statistics retains the chosen-KPI strip.
- **The Glossary** (`glossary.html`, the Glossary tab, opened with the simulation and its town) lists every figure by
  family with its definition and formula, the window as this simulation set it (its locked `kpi` settings over the
  catalogue's defaults), the settings that raise or lower it with the Config page's titles, the library scenarios
  whose episodes touch those settings, the related figures and where it shows; the simulation's own figures are
  marked. A filter box narrows the page; `#<id>` links scroll to a figure.

## Sharing

A simulation file (`utility-studio-simulation/1.0`) carries `kpis` with the rest of the proposal, so the figures a
person chose travel with the simulation, and the `kpi` settings travel as run settings.

## The figures

Direction arrows in "Moved by" say what raising that setting does to the figure (↑ raises it, ↓ lowers it); the
Glossary shows the full list with the settings' titles.

### Meter reading

Whether the scheduled billing reads arrive, and what happens to the ones that do not.

| KPI | Unit | Better | Definition | Window | Moved by |
|---|---|---|---|---|---|
| `missed_read_share` Missed reads (twin) | share | lower | Share of scheduled billing reads with no read taken: AMI dropouts, drive-by misses, no access. | — | Ami Missed Read ↑; Amr Missed Read ↑; Manual No Access ↑; Storm Factor ↑ |
| `estimated_read_share` Estimated reads (twin) | share | lower | Share of scheduled billing reads released to billing as an estimate rather than an actual read. | — | Ami Missed Read ↑; Amr Missed Read ↑; Manual No Access ↑; Leak ↑; Stuck Meter ↑ … |
| `reads_released_promptly` Reads released promptly | share | higher | Share of held reads (a case raised on them) that were released to billing within the window, counted from the scheduled read day. | `kpi.read_release_days` (3 days) | Analysts ↓; Analyst Hours Per Day ↓; Rpa Coverage ↓; Analyst Queue Days Min ↑; Analyst Queue Days Max ↑ … |

### Validation and estimation

How the VEE rules and the review team sort real anomalies from noise.

| KPI | Unit | Better | Definition | Window | Moved by |
|---|---|---|---|---|---|
| `auto_accept_share` Auto-accepted reads | share | higher | Share of actual reads VEE accepted without a person looking. | — | High Ratio ↓; Low Ratio ↑; Accept Confidence ↑; Leak ↑; Stuck Meter ↑ … |
| `exceptions_vee` VEE exceptions (twin) | per_1000_accounts_year | lower | Cases VEE's own tests raised (high, low, zero and erratic use, register regression, odd periods, persistent low use, vacant but consuming), per 1,000 accounts a year. | — | High Ratio ↓; Low Ratio ↑; Accept Confidence ↑; Leak ↑; Stuck Meter ↑ … |
| `vee_precision` VEE precision | share | higher | Of the reads VEE flagged, the share that were real anomalies in the simulation's truth. | — | High Ratio ↓; Low Ratio ↑; Accept Confidence ↑ |
| `vee_recall` VEE recall | share | higher | Of the real anomalies among actual reads, the share VEE flagged. | — | High Ratio ↓; Low Ratio ↑; Accept Confidence ↑ |

### Exceptions and backlog

The clarification cases, who works them, how long they wait.

| KPI | Unit | Better | Definition | Window | Moved by |
|---|---|---|---|---|---|
| `exceptions_all` Exceptions, every case (twin) | per_1000_accounts_year | lower | Every clarification case opened, per 1,000 accounts a year: missed reads, VEE exceptions, billing blocks, disputes and complaints, whoever resolved them. | — | Ami Missed Read ↑; Amr Missed Read ↑; Manual No Access ↑; Leak ↑; Stuck Meter ↑ … |
| `exceptions_worked` Exceptions a person worked (twin) | per_1000_accounts_year | lower | Cases an analyst, a supervisor or you touched, per 1,000 accounts a year: what a billing team counts as its exceptions, automation's own resolutions left out. | — | Rpa Coverage ↓; High Ratio ↓; Low Ratio ↑; Accept Confidence ↑; Leak ↑ … |
| `case_backlog` Open cases (twin) | per_1000_accounts | lower | Cases open at the view date, per 1,000 accounts. | — | Analysts ↓; Analyst Hours Per Day ↓; Rpa Coverage ↓; Analyst Queue Days Min ↑; Analyst Queue Days Max ↑ … |
| `days_to_release` Days to release a held read (twin) | days | lower | Average calendar days from the scheduled read to the day its case released it to billing, for cases resolved year to date. | — | Analysts ↓; Analyst Hours Per Day ↓; Rpa Coverage ↓; Analyst Queue Days Min ↑; Analyst Queue Days Max ↑ … |
| `cases_resolved_in_time` Cases resolved in time | share | higher | Share of cases raised year to date that closed within the window, in business days from being raised; a case still open counts as not in time. | `kpi.case_resolution_days` (5 business days) | Analysts ↓; Analyst Hours Per Day ↓; Rpa Coverage ↓; Analyst Queue Days Min ↑; Analyst Queue Days Max ↑ |
| `truck_rolls_per_1000` Truck rolls | per_1000_accounts_year | lower | Field visits made for cases (check reads, no-access visits, meter faults), per 1,000 accounts a year. | — | Ami Missed Read ↑; Amr Missed Read ↑; Manual No Access ↑; Leak ↑; Stuck Meter ↑ … |

### Billing

Bills released on time, held, wrong; invoices out the door.

| KPI | Unit | Better | Definition | Window | Moved by |
|---|---|---|---|---|---|
| `bills_on_time` Bills on time | share | higher | Share of bills created year to date that were released to invoicing within the window, counted from the scheduled read day they bill; a bill still blocked counts as late. | `kpi.on_time_bill_days` (3 days) | Analysts ↓; Analyst Hours Per Day ↓; Rpa Coverage ↓; Analyst Queue Days Min ↑; Analyst Queue Days Max ↑ … |
| `invoice_timeliness` Invoice timeliness (twin) | share | higher | Share of invoices created within the window of the last scheduled read they bill. The engine bills on an estimate rather than holding a bill, so this stays high under stress; a utility that counts an estimated bill as late wants Estimated reads too. | `kpi.timely_invoice_days` (5 days) | Analysts ↓; Analyst Hours Per Day ↓; Rpa Coverage ↓; Analyst Queue Days Min ↑; Analyst Queue Days Max ↑ … |
| `blocked_bill_share` Bills blocked | share | lower | Share of bills created year to date that a billing check held for a person (true-up, rate class, high bill, bill credit), whether or not they were released later. | — | High Bill Ratio ↓; Trueup Max Ratio ↓; Leak ↑; Stuck Meter ↑; Slow Meter ↑ … |
| `billing_error_share` Billing error (twin) | share | lower | Absolute difference between released bills and the simulation's true bills, as a share of the amount billed. | — | High Ratio ↓; Low Ratio ↑; Accept Confidence ↑; Leak ↑; Stuck Meter ↑ … |
| `days_to_invoice` Days to invoice | days | lower | Average calendar days from the last scheduled read an invoice bills to the invoice. | — | Analysts ↓; Analyst Hours Per Day ↓; Rpa Coverage ↓; Analyst Queue Days Min ↑; Analyst Queue Days Max ↑ … |

### Cash and collections

Money in: paid on time, days to pay, what is overdue, who is cut off.

| KPI | Unit | Better | Definition | Window | Moved by |
|---|---|---|---|---|---|
| `days_to_pay` Days to pay (twin) | days | lower | Average days from an invoice's issue to its payment in full, for invoices paid year to date. Payer behaviour is a town setting (on-time and late payer shares), not a run lever. | — | Due Days ↑ |
| `paid_on_time` Invoices paid on time | share | higher | Share of invoices whose due date (plus the grace window) has passed that were settled in full by then. | `kpi.payment_grace_days` (3 days) | Due Days ↑ |
| `collected_share` Cash collected (twin) | share | higher | Payments received year to date as a share of the amount invoiced. | — | Due Days ↓ |
| `overdue_share` Overdue receivable | share | lower | Of the money owed at the view date, the share past its due date. | — | Due Days ↓; Notice Days ↑ |
| `disconnections_per_1000` Disconnections | per_1000_accounts_year | lower | Services disconnected for non-payment, per 1,000 accounts a year. | — | Disconnect Days ↓ |

### Contact centre

Calls answered in time, hung up, resolved first time.

| KPI | Unit | Better | Definition | Window | Moved by |
|---|---|---|---|---|---|
| `contact_service_level` Calls answered in target | share | higher | Share of answered contacts whose wait was within the day's service target. | `contact.service_target_s` (30.0 s) | Agents ↑; Handle Factor ↓ |
| `abandoned_share` Calls hung up | share | lower | Share of contacts that reached the queue and hung up before an agent answered. | — | Agents ↓; Handle Factor ↑ |
| `contacts_per_1000` Contacts | per_1000_accounts_year | lower | Contacts of every kind (self-served, answered, callbacks, abandoned), per 1,000 accounts a year. | — | High Bill Ratio ↓; Ami Missed Read ↑; Amr Missed Read ↑; Manual No Access ↑; Storm Factor ↑ |
| `first_contact_resolution` Resolved first time | share | higher | Share of contacts resolved on the first attempt, self-served or answered, not a repeat. | — | Agents ↑ |

### Field work

Orders done on time, the backlog, how fast the emergency crews arrive.

| KPI | Unit | Better | Definition | Window | Moved by |
|---|---|---|---|---|---|
| `field_on_time` Field work on time | share | higher | Share of completed field orders that met their target: arrival for emergencies, completion for the rest. | — | Meter technicians · Per 1000 Premises ↑; On-call responders · Per 1000 Premises ↑ |
| `field_backlog_per_1000` Field orders open | per_1000_accounts | lower | Released field orders not yet done at the view date, per 1,000 accounts. | — | Meter technicians · Per 1000 Premises ↓ |
| `emergency_response_min` Emergency response | minutes | lower | Average minutes from an emergency order (gas odour, no supply) to the crew's arrival. | — | On-call responders · Per 1000 Premises ↓ |

### Reliability

Interruptions and the minutes customers were without service.

| KPI | Unit | Better | Definition | Window | Moved by |
|---|---|---|---|---|---|
| `customer_minutes_lost` Customer minutes without service | minutes | lower | Minutes of interrupted service per customer over the year's outages and leaks, all utilities together. | — | Storm Factor ↑; Incident Factor ↑; Restore Factor ↑; Water Main Breaks Per 100Km ↑; Gas Service Leaks Per 1000 ↑ |

### Cost

What the year's process cost, per account.

| KPI | Unit | Better | Definition | Window | Moved by |
|---|---|---|---|---|---|
| `cost_per_account` Process cost per account | currency_per_account | lower | The year's meter-to-cash process cost (people, systems, customer effects, reads) per account. | — | Analysts ↑; Rpa Coverage ↓; Ami Missed Read ↑; Amr Missed Read ↑; Manual No Access ↑ |
| `carry_per_account` Carrying cost per account | currency_per_account | lower | Money held up in unreleased reads, unbilled periods and unpaid invoices, priced at the carry rate, per account. | — | Carry Rate Per Day ↑; Analysts ↓; Analyst Hours Per Day ↓; Rpa Coverage ↓; Analyst Queue Days Min ↑ … |

## Billing assurance and report coverage

The October 2026 billing inventory adds 28 measures, taking the catalogue to 61. The setup wizard,
Command Center, Run statistics and Variable dependencies use the same catalogue. The Glossary includes a
searchable crosswalk for all 31 supplied report titles, including report-code search. The Word specifications
were not supplied: these are explicit engine definitions, not a claim to reproduce external report logic.

Counts add across offline processing checkpoints; shares pool numerators and denominators. Empty populations
are null, not a fabricated zero. Historical views exclude future documents, reversals and observations.
Current-document figures exclude versions already reversed; cancel/rebill and the monthly audit retain version history.
Early reads use the actual final-read timestamp when service ends before the scheduled read.

### Added measures

| Measure | Unit | Definition |
|---|---|---|
| `active_services` — Active services | count | Supply contracts active on the view date. A multi-service account contributes one contract per service. |
| `service_setup_defects` — Active service setup defects | count | Active contracts with a missing account or installation, a premise mismatch, or overlapping active contracts for one installation. |
| `move_ins` — Move-ins | count | Premises with a recorded move-in date this year through the view date. |
| `move_outs` — Move-outs | count | Premises with a recorded move-out date this year through the view date. |
| `net_terms_mismatch_share` — Invoice net-term mismatches | share | Created invoices whose original due date minus issue date differs from the configured payment term. Later payment arrangements do not count as defects. |
| `delayed_bill_share` — Delayed bills | share | Current billing documents released after the bill window, or still unreleased after that window expires. Newly created bills still within the window are not late. |
| `estimated_bill_share` — Estimated bills | share | Current billing documents built on at least one estimated register. Reversed versions are excluded at the view date. |
| `move_boundary_estimate_share` — Move-boundary bills estimated | share | Estimated current bills whose read period spans a recorded move-in or move-out. This is a boundary check, not a separate first/final invoice workflow. |
| `consecutive_estimated_bill_share` — Consecutive estimated bills | share | Current estimated bills whose immediately preceding monthly bill for the same installation and account was also estimated. Missing months break the sequence; the first month has no in-year predecessor. |
| `consecutive_zero_bill_share` — Consecutive zero-use bills | share | Current bills with zero import and export consumption whose preceding monthly bill for the same installation and account also had zero consumption. Fixed charges may still apply. |
| `bill_period_defect_share` — Bill period defects | share | Current bills with non-finite, non-positive or overlapping periods for the same installation and account. Legitimate longer periods after a service interruption are allowed. |
| `due_date_defect_share` — Invoice due-date defects | share | Created invoices with missing/non-finite issue or due dates, or an original due date before issue. |
| `rebill_share` — Cancel and rebill | share | Documents created this year that explicitly replace another billing document. All versions created this year form the denominator. |
| `multiple_invoice_cycle_share` — Cycles with multiple invoices | share | Account/cycle-month combinations represented on more than one invoice. Staggered services and corrective invoices can legitimately produce this; it is an audit indicator. |
| `zero_customer_charge_share` — Invoices without a customer charge | share | Created invoices with no non-zero fixed charge across their bill lines, as reconstructed by the engine tariff calculation. Zero-fixed-charge tariffs are included; this does not detect an external print omission. |
| `move_prorated_charge_count` — Move-boundary prorated charges | count | Move-boundary bills carrying a fixed charge prorated by the actual read-period duration. The engine prorates by read days, not by a separate move-in/out settlement period. |
| `invoices_pending_issue` — Invoices awaiting issue | count | Invoices already created whose planned issue day is after the view date. This is print-lag workload; the engine does not record actual print completion. |
| `billing_exceptions` — Billing exceptions raised | count | Billing-check and billing-dispute cases raised this year through the view date, including subsequently resolved cases. This is the model equivalent of a billing exception workload, not SAP BPEM telemetry. |
| `active_billing_blocks` — Active billing blocks | count | Current documents with a billing case that remain unreleased at the view date. Account-level invoice holds are counted separately. |
| `active_invoice_holds` — Active invoice holds | count | Account-level invoice holds in force at the view date. |
| `meterless_billed_accounts` — Billed accounts without a linked meter | count | Active accounts invoiced this year that have no meter linked through an active supply contract on the view date. This is a reference-integrity check, not a zero-consumption check. |
| `active_reading_blocks` — Active read-release blocks | count | Scheduled active register periods whose read was attempted, has a case, and remains unreleased. These are VEE/review holds; administrative meter-reading blocks are not separately modelled. |
| `outstanding_reads` — Open scheduled reads | count | Scheduled active register periods due by the view date without a released value, including missing and held reads. Future and service-off periods are excluded. |
| `early_read_share` — Reads taken early | share | Actual observations taken on a calendar day before the scheduled read day. Estimates and missing observations are excluded. |
| `late_read_share` — Reads taken late | share | Actual observations taken on a calendar day after the scheduled read day. Same-day time-of-day differences do not count as late. |
| `active_implausibles` — Open implausible-read cases | count | Unresolved VEE anomaly cases at the view date. Missing-read, billing, field-order and invoice-hold cases are excluded. |
| `active_meterless_accounts` — Active accounts without a linked meter | count | Active accounts without a meter linked through an active contract, installation and service point. An unmetered tariff may be intentional; review the account. |
| `orphaned_meters` — Meters without an active account | count | Installed active meter records with no active supply contract linked to a known active account. Vacancies can be legitimate; retired meters are excluded. |

### Report inventory

| Report | Coverage | Measures / table | Limits |
|---|---|---|---|
| BR-ACC-01 — Active Services | available | active_services, contracts | — |
| BR-ACC-03 — Active MultiService Setup Improperly | partial | service_setup_defects, contracts | Checks references, premise consistency and duplicate active contracts; organisation-specific multi-service rules are not supplied. |
| BR-ACC-04 — Move In Reporting | available | move_ins, accounts | — |
| BR-ACC-05 — Move Out Reporting | available | move_outs, accounts | — |
| BR-ACC-06 — Net Term Mismatch | available | net_terms_mismatch_share, invoices | — |
| BR-ACC-07 — eBill Adoption | needs data |  | Requires an account delivery preference or e-bill enrolment event. Payment method does not establish e-bill adoption. |
| BR-BIL-01 — Schedule v Actual Invoicing | available | invoice_timeliness, days_to_invoice, bills_on_time, invoices | — |
| BR-BIL-02 — Delayed Bills | available | delayed_bill_share, billingDocuments | — |
| BR-BIL-03 — Cycle Schedule | available | early_read_share, late_read_share, readSchedules | — |
| BR-BIL-04 — Monthly Audit File | available | billingAudit | Monthly document, invoice, estimate, reversal and amount totals; downloadable through Data. |
| BR-BIL-05 — Estimated Bills | available | estimated_bill_share, billingDocuments | — |
| BR-BIL-06 — First & Final Estimates | partial | move_boundary_estimate_share, billingDocuments | Uses bills spanning recorded move boundaries. A separate first/final customer settlement process is not modelled. |
| BR-BIL-07 — Consecutively Estimated Bills | available | consecutive_estimated_bill_share, billingDocuments | — |
| BR-BIL-08 — Consecutively Zero Consumption Bills | available | consecutive_zero_bill_share, billingDocuments | — |
| BR-BIL-09 — Bill Period Defects | available | bill_period_defect_share, billingDocuments | — |
| BR-BIL-10 — Due Date Defects | available | due_date_defect_share, invoices | — |
| BR-BIL-11 — Cancel Rebill | available | rebill_share, billingDocuments | — |
| BR-BIL-12 — Multi Invoice Issuance | available | multiple_invoice_cycle_share, invoices | Multiple invoices can be legitimate; this indicator identifies account/cycle combinations to review. |
| BR-BIL-13 — Invoices Issued without Customer Charge | partial | zero_customer_charge_share, invoices | Audits the engine-computed fixed charge; external line-item or print omissions require the actual issued document. |
| BR-BIL-14 — Prorated Customer Charge (on MIMO) | partial | move_prorated_charge_count, billingDocuments | Fixed charges use actual read-period days; move-specific settlement proration is not separately modelled. |
| BR-BIL-15 — Invoices Issued without Print Date | needs data | invoices_pending_issue, invoices | Planned issue dates and print-lag workload are available. Actual print-completion timestamps are not recorded. |
| BR-BIL-16 — Outsorts | available | blocked_bill_share, active_billing_blocks, billingDocuments | — |
| BR-BIL-17 — Exceptions (BPEMs) | partial | billing_exceptions, cases | Uses the simulation billing-check/dispute cases, not external SAP BPEM records. |
| BR-BIL-18 — Active Billing Blocks | available | active_billing_blocks, active_invoice_holds, billingDocuments | — |
| BR-BIL-19 — Accounts Billed without Usage (Meterless) | available | meterless_billed_accounts, consecutive_zero_bill_share, accounts | Meterless account associations and zero recorded consumption are separate checks. |
| BR-BIL-20 — Active Meter Reading Blocks | partial | active_reading_blocks, reads | Counts VEE/review holds on read release. Administrative meter-reading block flags need additional source data. |
| BR-MTR-01 — Open & Outstanding Reads | available | outstanding_reads, reads | — |
| BR-MTR-02 — Early & Late Reads | available | early_read_share, late_read_share, reads | — |
| BR-MTR-03 — Active Implausibles | available | active_implausibles, cases | — |
| BR-MTR-04 — Active Meterless Accounts | available | active_meterless_accounts, accounts | — |
| BR-MTR-05 — Orphaned Meters without Accounts | available | orphaned_meters, meters | — |

### Monthly billing audit

Data → Monthly billing audit (`billingAudit`) has one row per elapsed month: documents, estimates, replacements,
reversals, gross document amount, reversed amount, invoices and net invoice amount. Events belong to their creation
or reversal month, including reversals of carried documents. Gross document amounts include all created versions;
net invoice amounts include correction credits. They are deliberately separate totals, not double-counted revenue.
Offline views add the monthly rows across the whole utility before filtering, sorting, projecting columns or
paging. CSV and Connect exports use those same totals. Old archives without the new table or KPI values replay
their preserved inputs; users do not need to recreate their simulation.
