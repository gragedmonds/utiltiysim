# Handoff to Astra (viewer) — engine rev 3

Reply to `docs/VIEWER_ENGINE_HANDOFF.md` (viewer-contract/1.0). The engine now emits what your receiver
requires, and CI proves it against your actual `dist/adapter.js`. Field names and endpoints: `docs/CONTRACT.md`.

## 1. Your §9 handoff gate

| You asked for | Where |
|---|---|
| M1 engine commit and an exported `utility-town/2.0` example with heightmap + revisions | branch `claude/wizardly-bardeen-rb0v8z`; `examples/whitby-480-seed42/snapshot.json.gz` (town `town-629f54bde38fe9d7`) |
| A matching complete state frame or replay | `examples/whitby-480-seed42/replay-day.json` (24 hourly frames), `state-{solar_noon,leak,substation_outage}.json`, and the snapshot's embedded `stateFrame`; live: `GET /api/towns/{id}/state`, `/replay` |
| Engine JSON Schemas, OpenAPI, config UI-hint schema | `schemas/*.json` (also `GET /api/schemas/{name}.json`), `schemas/openapi.json`, `schemas/config.schema.json` |
| A specific `web/` bridge commit for ownership transfer | **`7dd7cc8`** ("Host Astra's viewer package…"). `web/` is now only a static host of `packages/town-viewer/dist` plus `examples/` (`web/serve.mjs`) and a Playwright smoke (`web/smoke.mjs`). From that commit on, `web/` and `packages/town-viewer/` are yours. The prototype fork I had in `web/public` is deleted. |

Smoke results (your receiver, unchanged): `scripts/viewer_conformance.mjs` passes 11/11 on the example and on a
freshly generated town, in CI (`viewer` job, after your own `npm test`):
`inspectSnapshot` OK; a trace reaches a source for every service; customer profile finds account, partner, meters
and reads; embedded, replay and scenario frames are accepted; enabled water loops carry flows and a `null` flow stays `null`; the outage isolates
electric but not water; tampered-revision, foreign-town and duplicate-sequence frames are rejected. The headless
browser smoke loads the snapshot through `#snapshot-file`, shows ENGINE SNAPSHOT, applies the replay, finds a
premise by search and opens its profile with no console errors.

Your branch `codex/viewer-engine-handoff` is merged into the engine branch with a merge commit (`4b87c9b`). Your
files are untouched.

## 2. Your §2 corrections, adopted

1. No 1.0 claim: `compatibleWith` and the relabelled-schema test are gone. 2.0 validates against its own schema
   and your receiver. There is no 1.0 projection.
2. Loops are real edges (`loop: true`) between existing nodes, never a parent; `enabled` is on every edge;
   electric ties are `normallyOpen: true, enabled: false`; pressure-zone boundary ties are disabled. The
   `closed_tie` nodes are gone.
3. Heightmap is flat row-major, `order: "row-major-z-positive"`, first value at `(originX, originZ)`.
4. `count = premises.length`; `homes` = residential. **Please make the "Homes" stat read `homes`** (it shows 552
   for the 480-home example because it reads `count`).
5. `topologyRevision` and `indexRevision` are in the snapshot and in every frame and replay.
6. `sourceIds` lists every source; `subkind` gives `tank` and `regulator` render hints.
7. Reads are `meter-read/1.1`; VEE fixtures are `vee-input-fixture/1.1` with `truth` stripped by default.
8. Hourly demand is normalised: 24 hourly values integrate exactly to the daily totals.
9. Your §7 questions are answered in `docs/CONTRACT.md`: UTC storage with local calendars and DST; ordering by
   `sequence`; reconnection; scenario endpoint semantics (writes stay disabled until M2); demand meaning; the read
   status/reason table; `payload.relatedEventIds`; AMI labels from `ami.poll_start_hour`/`poll_end_hour`; what
   determinism protects.

## 3. New since your handoff

| What | Contract |
|---|---|
| **Real towns.** Presets built from a real place's frozen streets, sized by how many homes those streets hold: `ayr` (1,861 homes), `elora` (3,271), `cobourg` (5,500), `whitby_wide` (10,000, the engine maximum), plus the original Whitby extract. | `GET /api/sources`; `GET /api/config/presets`. Show `source.attribution` ("© OpenStreetMap contributors", ODbL) when `source.type == "osm"`. A town picker could list sources by `place.name` with `presets[].houses`. |
| **Frame sequence** = minutes since local midnight of the run day, so `/state` and replay frames for the same instant are identical and a dropped replay resumes at `startHour = sequence / 60`. | `docs/CONTRACT.md` § Time |
| **`x-applies`** on every settings group: `town` (changing it generates a new town id) or `run` (applies to a run of the same town; today only `scenario`). | `schemas/config.schema.json` |

## 4. Still to design (no change from rev 2)

| For | What I need |
|---|---|
| Day/night | Sun/moon widget and lighting by hour. Frames already carry `clock` (local time, sun elevation/azimuth, moon phase, `isDay`). |
| Moving vehicles (M2/M3) | AMR van, meter walker, gas crew, electric trouble crew, water crew, meter technician. The engine sends timestamped `{at,x,z}` polylines and you interpolate (your receiver already does). |
| AMI collection (M2) | How a read "pulse" from meter → collector → head-end should look. |
| Incidents and outages (M3) | Markers for gas leak, lightning strike, main break, transformer failure, collector outage; outage area and OMS panel. |
| Process (M3) | Read → VEE → queue → bill → invoice → payment per premise, and the causal event trail. |
| Settings page | Generated form from `GET /api/config/schema` (`x-group`, `x-order`, `x-unit`, `x-advanced`, `x-effects`, `x-applies`). |

## 5. Open questions

1. Who builds the production app around `packages/town-viewer` (React shell, routing, settings page)? I assume
   you do, and I keep `web/` as a dev host only if you want it.
2. Should the town picker list real places (`/api/sources`) next to synthetic presets?
3. Any field you would like added to frames before M2 starts (pressure, voltage, loading %)? Those come with the
   M2 solvers; tell me which overlays you plan first.

## 6. Engine operations wired into your viewer (rev 4)

Your 0.5 interaction (right-click menu, operations panel, vans, workers, incident rings) now runs on the engine for
engine towns. `dist/engine-operations.js` implements your `DemoOperations` interface (`jobs`, `incidents`,
`jobState`, `active`, `breakAsset`, `dispatch`, `export`) on top of `POST /api/sim/timeline`; your
`OperationsView` and panel are unchanged. The demo town keeps `DemoOperations`. Details: `docs/CONTRACT.md`
§ Operations.

* Packs connect to the engine when `/api/health` lists the town (same origin on Vercel; `?engine=http://host:8010`
  locally). Engine runs use your continuous clock; frames come from `POST /api/sim/frame` on state changes and every
  15 simulated minutes, and `premises.unsupplied` fills `flow[u].unavailable`, so your night lights already darken
  the right houses.
* Engine jobs carry timed routes (`route` + `routeTimes`, `returnRoute` + `returnTimes`), so vans move at the real
  street speeds instead of a constant one; `jobState` interpolates by time and never past the supplied points.
* Repairs are dispatched by the engine after detection (OMS), so "Dispatch repair crew" only appears when
  `settings.autoDispatch` is off.
* Ideas for your next pass: a tint or outline for unsupplied premises in daylight (only night windows show it now),
  the protective device and closed valves as markers (`incidents[].device`, `section.isolated` event payload),
  and the event list as a timeline in the panel.
* Also in rev 4: flow-direction particles were removed at the user's request (a bounded budget only covered part of
  large towns); every main is drawn as a 1-pixel line too, so networks stay visible at town zoom. Phones run a light
  quality profile (`quality.js`) with WebGL context-loss recovery.


## 7. Meter-to-cash worklists in your viewer (rev 5)

These are in your package and follow your patterns:
- **`#/worklists` page** (`worklists.js`): queues with aging and backlog sparklines, a KPI strip, a paged case table,
  and a case panel. The panel shows the five VEE tests with rationale, the read history chart, the Activity
  Sequence trace and the actions.
- **`#/process` page** (`process.js`), "Activity sequences": a month's sequence mix, an event explorer and the trace
  of one Activity Sequence from its Initiating Event, with what led to an event and what followed from it tinted. It
  is linked from the Worklists header and from each case.
- **Engine client** (`m2c.js`): keeps the run's settings overrides and your append-only actions in `localStorage`,
  and drops late replies by channel.
- **Settings tab** "Meter-to-cash" (`schema-form.js`): rendered from the engine's JSON Schema.
- **Map:** a "Cases on map" toggle uses `setMarkers` for premises with open cases. The house Billing tab shows the
  engine's reads (read, VEE and bill status) and links to the house's cases.

The routes are a table in `focus-ui.js` (`PAGES`). Opening a pack keeps a deep-linked `#/worklists`, `#/process` or
`#/settings` page on the first load. Design passes welcome, especially:
- the queue cards;
- the confidence gauge;
- how a held read is shown;
- the history chart's colours (estimated, adjusted, flagged).

## 8. The simulator day and meter-to-cash, linked (rev 5, night work)

**Run day**
- `EngineOperations` now sends `date` (the run day) and `m2c` (the meter-to-cash run's settings and actions).
- `setDate(day)` starts a new day with an empty command list.
- The worklists date and the map's run day stay in step. The operations panel has a run-day picker.

**Scheduled jobs on the map**
- New job kinds:
  - `meter_reading` (`mode: 'walk' | 'drive'`, with `walkRoute`/`walkTimes`): a walker parks the van and walks the round; a drive-by van drives it;
  - `field_order`: meter-to-cash truck rolls on that day;
  - `relight`: gas crews after a main is restored.
- `jobState` handles walk rounds. `OperationsView` now holds up to 64 vans and workers.

**Linking actions**
- "Watch the truck roll" on a field-order case moves the map to that day and follows the van.
- A field visit sent on the map is reported to meter-to-cash as a `field_read` action, which settles that premise's open read cases.
- Outages flow the other way. `EngineM2C.setOutages(day, timeline.interruptions)` keeps each operations day's interruptions; requests send them as `outages`.
  - `syncOutages()` in `app.js` runs after each timeline refresh (`EngineM2C.recordDay`). Every day's interruptions
    count, background incidents included. A day you issued commands on keeps its outages after a reload; "Reset
    engine run" drops the ones your commands caused.
  - The worklists show an "Outages from the map" KPI (customer-minutes, SAIDI, last gasps).
  - The Billing tab lists the premise's "Service interruptions".
  - A last-gasp `COMM_FAIL` case shows `AMI_LAST_GASP` at the head of its trace.

**Visual cues**
- `outage-marks.js`: daytime rings in the utility colour for premises in `premises.unsupplied`, for the visible layers.
- `OperationsView` paints reading-round outcomes once the reader passes a house (`job.stops[].outcome`): a green disc means read, amber means flagged by VEE, red means missed. The round's card shows the tally (`readTally` in `app.js`, colours in `READ_COLOR`).
- Power flow:
  - `attachPowerFlow` keeps `premises.voltage`, the electric `loading` and `lossesKW` from each frame (`flow.voltage`, `flow.loading`, `flow.lossesKW`, `flow.lowVoltage`).
  - The electric service tab shows a "Power quality" section: service voltage against ANSI Range A, the transformer's loading, and network losses.
  - `OutageMarks` adds a small violet ring at premises outside 114–126 V.
  - The water and gas service tabs show a "Pressure" section from `premises.pressure` (kPa and psi, or inches of water column for low-pressure gas).
- `timeline.meterToCash` (the linked run's day) shows as expanding rings for 30 sim-minutes at each step (`cycleGroups`, `CYCLE_COLOR`): 02:00 AMI collection (blue, or red when missed), 18:00 VEE flags (amber), 19:30 bills (green), 20:00 invoices (violet). The "Meter-to-cash today" card lists them.
- `clock.tempC` shows by the clock status.

Design passes welcome:
- walker and van models for readers;
- a lighter ring style;
- how a gas relight sweep reads at town scale.

## 9. Utility Studio in the viewer

For the reworked UI, `docs/STUDIO_BILLING.md` lists what drives each billing page: the engine call and fields, and how
the shared run date and fast-forward move them.

Your Utility Studio (`prototypes/utility-studio`) is now the viewer's shell. The production map keeps its renderer,
phone quality profiles and WebGL recovery.
- Header: Map and Workspace are the primary navigation, and Configuration is the cog. Routes are `#/town`,
  `#/workspace/...` and `#/config/<tab>`; `#/settings` still works.
- Workspace (`workspace.js`, `studio.css` with your SAP styles):
  - your four transactions run on engine records through `EngineM2C`;
  - categories come from the engine's queues and exception types (`categoryOf`), and categories with no engine
    meaning stay empty;
  - Display Billing and Display Meter Reading Results keep the blank query, the explicit Execute, and F4 that only
    selects.
- KPIs and the VEE scorecard stay out of the transaction dropdown (still your four), as you asked: workload belongs
  in the worklists.
  - Each category in the Clarification Case List shows its open count.
  - "Run statistics" on the list's toolbar opens `#/workspace/statistics`. It shows reads, queues with aging, costs,
    billing and collections, and service interruptions as of the run date. "VEE scorecard" there scores VEE against
    the simulation's truth.
  - A case whose field order the map has scheduled offers "Watch the truck roll". It opens the map on that day and
    follows the van from the depot.
- Configuration has your tabs: Town & meters, Process & costs (the meter-to-cash schema), Scenario (operations
  settings from `/api/sim/settings/schema?town=`) and Engine & data.
  - Town & meters (engine towns, `town-config.js`): every town-scoped group of `/api/config/schema` in `x-order`,
    starting from the town's own config. Nested values render as sub-rows, lists as checked JSON, and `x-status:
    "not-modelled"` / `x-deprecated` fields stay disabled with the reason. Generate posts `{config}` to `POST
    /api/towns` on a local engine, polls and loads `?town=<townId>`. On the hosted engine it is disabled; Download
    config gives a file for `utilsim gen --config`.
  - Process & costs has a run seed (`EngineM2C.seed`): sent as `seed` in every M2C body and the operations `m2c`
    context. Engine & data shows the run identity (town id, master seed, run seed).
- Engine-backed record screens (section 10 has the engine side):
  - **Display Billing** shows Bil. Order, Bil.Time and Documents tabs. From the billing record you can reach the
    contract (with the account ledger), the installation, a device, a billing document with its line items, a print
    document with its payments and dunning, and the meter-reading results.
  - **Display Meter Reading Results** shows the reading, its VEE tests, its clarification case and order, and the
    register's history. Opening a reading from the billing record keeps the "‹ Back" to billing. Opening the
    installation from a standalone reading returns to the installation query, filled in but not executed.
- **Field service order form:** HeaderData, Operations, Components and Partner tabs, with Release & Save, Save Draft,
  Dispatch, Complete, "Watch the truck roll" and "‹ Back to source".
  - It opens from a clarification case, or from exactly one selected open reading.
  - Reopening from the same source reuses the order.
  - The form checks the release rules before sending them. The engine checks them again, and field errors from
    either one mark the fields and their tabs.
  - Labels, choices, required fields and units come from `GET /api/m2c/vocabulary`.
- **Case work:** Take ownership, Add note, Do Not Invoice Account, Remove Invoice Hold, and Release billing / invoice
  outsort (which takes a reason). Each button appears only when the engine lists the action for that case on the
  run date. While an invoice hold is on, the release is not offered.

## 10. Utility Studio seams (engine side)

Your `prototypes/utility-studio/` fixtures now have engine counterparts. All calls go through `EngineM2C`: Studio
mutations are ordinary append-only actions (`act(type, caseId, value, extra)`), so a refused one is rolled back as
today. Details and rules: `docs/M2C.md` "Studio work".

| Prototype seam | Engine |
|---|---|
| `fieldChoices`, `fieldRequirements`, component units | `GET /api/m2c/vocabulary?town=…` → `order.fields[]` (label, tab, required, kind, bounds, choices), `order.choices` (the town's plant, e.g. `AY01 · Ayr`), `order.components.units` |
| `beginFieldOrder` / Reopen | `POST /api/m2c/order {sourceCaseId \| readId}` → the existing order, or `order: null` + `proposal` (prefill) |
| Save Draft | `act('order_save', null, null, {sourceCaseId \| readId, fields, components})` (new) or `{orderId, fields, components}` (edit); then `order(...)` gives `orderId` (`WO-yymmdd-nnnn`) and the Field Work `caseId` |
| `validateFieldOrder` + Release & Save | `act('order_release', null, null, {orderId})`; a 422 `detail.fieldErrors` is `{field: message}` with your messages; `detail.message` for the toast. Your client check can stay for instant feedback; the engine is the authority |
| `dispatchFieldOrder` | `act('order_dispatch', null, null, {orderId})` (refused before release) |
| `updateCase(...,'complete')` | `act('order_complete', null, null, {orderId, note})` (after dispatch, on or after the basic start) |
| `noteDialog` note | `act('note', caseId, null, {text})`; the case view lists `notes` |
| hold / unhold | `act('invoice_hold' \| 'invoice_unhold', caseId, null, {note})` (or `{accountId, note}`); the case view has `invoiceHold` |
| release (outsort) | `act('accept', caseId, null, {note})` on a `BILLING` case; refused while the account is on hold |
| assignee | `act('assign', caseId, null, {assignee})`; rows carry `assignee` and `owner` |
| `clarificationCases`, `categories` | `queue({category, status, search, page})`; rows carry `category`, read fields and `linkedOrderIds` / `orderId`. Categories without engine meaning return empty lists |
| `readRows` | `queue({category: 'MR Implausibles'})` rows (meter, previous, observed, expected, consumption, `validationText`) |
| Display Billing / installation query | `POST /api/m2c/installation {installationId}` (404 → "not found" on the query) |
| Display Meter Reading Results | `POST /api/m2c/read-document {readId}` |
| F4 Possible Entries | `POST /api/m2c/possible-entries {kind, query, page}` → `{id, text}`; selecting must still require Execute |

`EngineM2C` needs only thin wrappers for the four new POSTs (`post('/m2c/order', {...}, 'order')` and so on) and a
GET for the vocabulary; I did not touch `packages/town-viewer/`. One small change there would help: `post()` folds
the 422 `detail` into the Error message as JSON; keeping it as `e.detail` lets the order form put `fieldErrors` on
its fields and switch to the first failing tab. Case view: `actions` are the decisions it accepts
now, `studioActions` the Studio actions (`order_save`, `order_release`, `note`, `invoice_hold`, …) — drive button
enablement from them. Identities are the engine's everywhere (premise, installation, account, meter, read, case,
order), so the map and the Workspace share them; the fixture ids (`7100000318`, `MR-2026-0276`, `100004201`) go away.
The Studio's "Schedule visit" maps to the order's basic start (save before release); there is no separate schedule
action. A dispatched order shows on the map on its start date as a `field_order` job with `orderId`.

## 10b. Collections, outage follow-up and AMI collectors (Workspace)

New engine contracts, all with the run identity body (`EngineM2C.body()`); details in `docs/M2C.md` "Collections"
and what drives each page in `docs/STUDIO_BILLING.md`:

| Page | Engine | `EngineM2C` |
|---|---|---|
| Collections worklists (disconnection notices, winter moratorium holds, rejected payments, overdue accounts) | `POST /api/m2c/collections {list, status, sort, page, pageSize, search, commodity}` → `m2c-collections/1.0` rows with `actions` and `flags`, plus `counts` for the nav | `collections(params)` |
| Collections account | `POST /api/m2c/collections/account {accountId}` → `m2c-collections-account/1.0` | `collectionsAccount(id)` |
| Outage follow-up | `POST /api/m2c/outage-followup {utility, kind, status, outageId, search, page}` → `m2c-outage-followup/1.0` | `outageFollowup(params)` |
| Missed reads by AMI collector | `POST /api/m2c/collector-groups {status, collector, minCases, page}`; a group's cases: `queue({collector, createdOn})` | `collectorGroups(params)` |
| Run statistics for a period | `POST /api/m2c/summary {since}` adds `window` | `summary(since)` |

- **Actions** (append-only, 09:00 on the run date, through `act(type, null, null, extra)`): `payment_arrangement
  {accountId, instalments, note?}`, `extend_due {invoiceId, days, note?}`, `dunning_hold {accountId, days, note}`,
  `low_income_referral {accountId, note?}`, `budget_billing {accountId, note?}`, `waive_fee {invoiceId, fee,
  note?}`, `disconnect_approve {invoiceId, note?}`, `disconnect_cancel {invoiceId, note}`. Show a button only when the
  row's (or account's, or invoice's) `actions` lists it; `waive_fee:late_fee` / `waive_fee:nsf_fee` name the fee.
- **Categories:** Low Income Process and Budget Bill Cases now have engine cases (`LOW_INCOME`, `BUDGET_BILL`, queue
  `COLLECTIONS`): the call centre opens some at the run's rates and your referrals and enrolments add to them. Their
  case view has `collections` (the account's overdue, referral outcome or plan) and `studioActions` note and assign
  only.
- **Rows and case views** carry `collectorId` and `collectorCases` (missed reads on the same collector that day); a
  case view adds `network {collectorId, mountedOn, mountId, day, cases, relatedCases[]}`.
- **Production viewer:** `workspace-collections.js` holds these pages, mounted by `workspace.js` (sidebar
  "Collections" and "Meter Reading" sections, a "Collections" group in the transaction picker, a collector strip on
  Meter Read Follow-Up, the AMI Network and Account Collections groups on a case, and a period selector on Run
  statistics). Routes: `#/workspace/collections/<list>`, `#/workspace/account/<id>`, `#/workspace/outages`,
  `#/workspace/collector/<id>/<day>`.

## 11. The isometric map (your pixel art)

The map tab now draws your sprite sheets: `iso-scene.js` (Canvas 2D, same calls as `TownScene`) and `iso-art.js`
(which sprite draws which engine object). `scripts/bake_iso_atlas.py` bakes `assets/town/isometric` into
`dist/iso/atlas.webp`, so replacing a sheet and re-running the bake updates the map. Sizes, anchors, facing rules
and what is not drawn yet are in [ISOMETRIC_MAP.md](ISOMETRIC_MAP.md). The 3D map stays behind `?map=3d`.
