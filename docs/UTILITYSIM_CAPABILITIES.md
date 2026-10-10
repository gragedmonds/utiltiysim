# UtilitySim capability inventory and design handoff

Prepared **9 October 2026** for a design agent assessing product coverage. This is a capability map of the public UtilitySim repository, with explicit distinctions between the downloadable release, tested candidate work, and the wider integrated platform still being built. It is not a certification that the full utility operating platform is complete.

Repository: [gragedmonds/utiltiysim](https://github.com/gragedmonds/utiltiysim). Paths below are relative to this document in `docs/`. They point to implementation, contracts, and reproducible checks, rather than treating a screenshot or a menu item as proof of a completed workflow.

## 1. Release status and how to read this document

| Label | Meaning in this handoff |
| --- | --- |
| **Released** | Present in the named public release. The continuation shipped as `runner-38cd7617d2ba` through [PR #73](https://github.com/gragedmonds/utiltiysim/pull/73); cashflow followed as [`runner-d12f41d60e05`](https://github.com/gragedmonds/utiltiysim/releases/tag/runner-d12f41d60e05) through [PR #74](https://github.com/gragedmonds/utiltiysim/pull/74), for Windows x64, Linux x64, macOS arm64 and macOS x64. This does not mean every installed copy has updated. |
| **Merged; package pending** | Merged into public main after CI, but a downloadable runtime containing it has not yet been verified as published. |
| **Candidate** | Implemented and locally verified in subsequent work, but not part of that named downloadable release. Merge, CI, and runtime publication are separate milestones. |
| **In progress** | Implementation or acceptance is underway in separate work. Do not represent it as a released capability. |
| **Partial** | A usable bounded component exists; the larger workflow described by the row still has missing links or fidelity limits. |
| **External owner** | Belongs to the separate enterprise/runtime integration, not to the public world's administrator UI. An interface or test receiver does not establish that integration. |
| **Unsupported / unverified** | Not implemented at the stated boundary, or no acceptance evidence establishes the claimed outcome or scale. |

The released baseline includes guided Quick/Full setup, durable local worlds, four-domain fault components, local field visits and reporting, main-phase cancellation/replacement, storms, expanded saved-road travel planning, and terminal provider-failure evidence. The recurring household-cashflow increment, tested at `e5a72fd`, merged through [PR #74](https://github.com/gragedmonds/utiltiysim/pull/74) as `d12f41d60e0537c516595cf5cd46ff07c487a077` after CI passed, at 00:30:04 UTC on 10 October (9 October in the working timezone). Its four-platform desktop runtime was published at 00:37:13 UTC. Financial-notice reactions, district-size guided staffing and the shared-runtime field adapter are subsequent **candidates**, now combined for regression on `greg/world-notice-reactions`; their focused/local acceptance is described below. They remain outside the named published releases at this review point.

The [delivery status](WORLD_DELIVERY_STATUS.md) and [integrated acceptance ledger](WORLD_ACCEPTANCE_MATRIX.md) are companion records. Older documents deliberately preserve historical test counts and earlier limitations. For example, early world/map documents describe sewer faults, main phases, or travel as future work; the newer dedicated domain documents and current implementation supersede those particular gaps. Conversely, a later local test does not retroactively place its feature in an earlier published runtime.

## 2. What the product is

UtilitySim generates reproducible synthetic utility towns and supports two substantial but distinct uses:

1. **Utility Studio analysis:** configure a utility, simulate meter-to-cash operations, change dated assumptions, inspect work queues and customer/billing records, compare outcomes, and export reusable data. It includes a legacy operations-day map and a desktop utility-wide Command Center.
2. **Living world:** preserve a generated town in a durable SQLite world and advance its physical and customer circumstances day by day. Physical faults, consumption, device condition, occupancy, customer knowledge, cash, visits and messages persist across restarts. Enterprise systems must learn through allowed observations and communications.

The intended wider loop is physical world → available evidence → enterprise processing → authorized human/agent work → physical and business consequences. The public repository implements much of the world and Studio analysis, plus interfaces and local demonstrations. It does **not** by itself supply a completed authenticated enterprise workforce, financial subledger, provider network, and all twelve integrated acceptance scenarios.

Towns, addresses, properties, people, networks, and assumptions are synthetic. Normal generation does not fetch geography or personal data from external services. A setting called a region is an editable modeling profile, not a calibration to an actual utility. Source: [README](../README.md), [generation pipeline](../utilsim/gen/pipeline.py), [world store](../utilsim/world/store.py).

### The two execution paths must remain visible in the design

| Dimension | Studio year / utility batch | Durable Living world |
| --- | --- | --- |
| Primary question | What does this scenario do to annual reads, queues, bills, collections, staffing and KPIs? | What actually happened in this saved place, and when could each other owner learn or act? |
| Execution model | Deterministic replay from town, settings, seed, dated actions, episodes and interruptions. Desktop jobs archive results/checkpoints. | Daily transactions append physical history and advance a durable next-day cursor. Cannot rewind the same database. |
| Persistence | Browser simulation metadata and edits; local job queue; generated baselines; verified run archives and revisions. | World SQLite database; a distinct optional field SQLite database; journals, inbox/outbox records, causal events and checkpoints. |
| Geography | Per-town template up to 10,000 homes; desktop utilities aggregate district checkpoints up to a configured 500,000-home cap. | One retained full snapshot per world. Multiple namespaces are separate worlds, not automatically a connected large territory. |
| Time | Annual replay, dated scenario episodes, scheduled process steps; individual-town year chaining exists. Combined desktop utility jobs cover model year 2026. | UTC daily physical boundaries, with separate occurrence/availability times and optional managed runtime scheduling. |
| Processes | Integrated illustrative VEE, billing, contact, collections and field models in the replay. | Physical and customer owner; business systems and shared workforce remain separate integrations. |
| Map | Operations-day engine frames, demonstration controls, flow/day-night animation where that path is exposed. | Current physical inspection over saved geography; no second browser simulation and no invented animated crew activity. |
| Workforce | Studio analyst/contact/field productivity assumptions; CLI district pool coordination. | Local crew skills, weekdays and finite visits/day; travel quotes are planning. Shared hourly reservations are separate work. |
| Safe interpretation | Scenario analysis, not an independently authenticated enterprise system of record. | Durable administrator truth and bounded message contracts, not an omniscient worker interface. |

Do not connect a Studio staffing slider, legacy truck animation, or old map storm preset to a Living-world action merely because the vocabulary matches. Their settings and clocks are different. Switching setup modes retains values, but Review identifies dormant settings. Sources: [guided setup](GUIDED_SETUP.md), [M2C run model](M2C.md), [local runner](LOCAL_RUNNER.md), [world runtime](WORLD_V2.md).

## 3. Download, launch, storage, and offline operation

**Released.** Utility Studio is a downloadable desktop application whose interface opens in a desktop browser. A small Go launcher manages the storage folder and packaged Python runtime. Once installed, the ordinary engine, Studio UI, bundled artwork, town packs and local jobs run offline. Optional online actions include runtime download/update checks and conversational setup.

The launcher provides a storage-folder choice, Open Utility Studio, status/error/log information, and app settings/update/restart/quit controls. Subsequent starts reuse the chosen library and engine; opening an already running launcher reopens its Studio instead of starting a second engine for that library. Separate storage folders are separate libraries. A missing drive produces an explicit failure/pause rather than silently relocating saved work.

The runtime serves UI assets, engine APIs, local jobs and saved results on loopback. Runtime archives are checked for size, SHA-256 and Ed25519 signature, installed in versioned folders, and staged for restart. Runtime integrity signing is distinct from OS publisher signing: the documented release process does not configure Windows Authenticode or Apple notarization. Updating the runtime updates its bundled screens; replacing the launcher itself is a separate download.

Useful storage concepts for design:

- A **simulation definition** is the settings, seed, purpose, chosen dates and scenario edits. Its small `.utilitysim.json` export can recreate the setup elsewhere; it is not a world-history database or a complete run archive.
- A **saved result/revision** is an archived analysis and its inputs. Old revisions remain inspectable after a new replay.
- A **saved world** is a durable physical history with a pinned town and identity. Removing its library shortcut does not delete the source database.
- A **world creation request** is itself durable and retryable; it can be pending even if a response was lost.
- A **field store** is a separate owner, explicitly supplied when launching local field execution. It must not be confused with the world database or an enterprise order system.

The supported interaction target is desktop keyboard and mouse, including resized windows, browser zoom and display scaling. Dedicated phone/tablet support is deprecated by [CLAUDE.md](../CLAUDE.md). Avoid proposing a mobile-first redesign as implied existing scope.

Implementation: [launcher](../launcher/), [worker server](../utilsim/worker/server.py), [worker entry](../utilsim/worker/entry.py), [world library](../utilsim/worker/worlds.py), [local runtime contract](LOCAL_RUNNER.md).

## 4. Screen and navigation inventory

The application has related surfaces rather than one completely consolidated navigation system. The design agent should preserve the scope and authority of each surface while improving continuity.

### 4.1 Setup and libraries

| Surface | User can do | Important interpretation |
| --- | --- | --- |
| Simulations/home | Create a simulation, reopen browser-saved definitions, import/export definitions, open saved results, reach app settings and Saved world maps in a launcher session. | Browser metadata is local to its origin/computer; it is not a shared cloud account. |
| Guided builder | Choose Living world or Studio year; choose Quick or Full; edit settings, search, navigate sections, pin values, review and validate. | New desktop setups default to Living world. Existing drafts retain their selected mode and values. |
| Match existing metrics | Enter baseline/current/target KPI observations and generate a proposed Studio configuration. | Inverse fitting of model assumptions; not a uniquely identified explanation of a real utility. |
| Talk it through | Type or, when browser support permits, speak to a setup guide; answer follow-ups and review a validated proposal. | Requires internet and an Anthropic API key. It is a setup assistant, not an enterprise worker agent. Manual setup remains available. |
| Saved world maps | Create from guided settings, choose a complete town from saved results, use a full snapshot file, register an existing initialized database, reopen a map, retry interrupted creation, remove a shortcut. | Registering inspects the existing file; it does not reset its physical history. An analysis-only archive cannot supply missing map geometry. |
| Saved results / run reader | Open archived run folders or supported run URLs and inspect saved Year/Data/Workspace/scorecard views. | Reading existing exports can work without a live engine. Interactive recomputation needs its engine path. |

Sources: [setup entry](../packages/town-viewer/dist/setup.js), [guided UI](../packages/town-viewer/dist/guided-setup.js), [simulation library](../packages/town-viewer/dist/simulation-library.js), [world library UI](../utilsim/worker/worlds.html), [saved-run contract](RUN_BUNDLES.md).

### 4.2 Studio analysis surfaces

| Screen | Existing behavior |
| --- | --- |
| **Command Center** | Utility trends and chosen KPIs; calendar of dated scenario changes; submit Run utility; inspect progress and completed checkpoints; edit/replay scenarios after completion; save a new revision. The job monitor shows active/queued work, stages and measured ETA. |
| **Config** | Searchable schema-backed configuration, groups, Advanced controls, unit/effect information, default/reset behavior, town versus run settings, run identity and engine guide. Locked baseline settings remain attached to the simulation; later episodes are dated changes. |
| **Workspace** | Recognizable utility enterprise patterns for clarification queues, meter-reading validation, billing displays, collections and field-service orders. Query and F4-style possible-entry selection lead to records. Actions are constrained by current run date and engine eligibility. |
| **Clarification case list/detail** | Open/completed/all cases, category and text filters, pagination, age/status/assignee, related cases, read history, expected/observed/released quantities, notes, holds, assignment/escalation, estimates/overrides and field-order links as permitted. A category label alone is not proof of a distinct end-to-end process. |
| **Display Billing** | Installation, contract periods, billing orders, billing documents and line items, print/invoice records, account/ledger/payment/dunning context, device and register history, linked readings. |
| **Display Meter Reading Results** | Reading and schedule dates, actual/missing/estimated state, cumulative register and interval usage, validation tests/rationale, history, anomaly/missed-read cause where modeled, related case/order. Register regression is distinguished from a genuine rollover. |
| **Field service order** | Save, release and dispatch an order in the Studio replay; simulated en-route/on-site/completed stages and structured outcomes; related-case coverage. Read taken/confirmed, device exchange, no access and defect findings are modeled here. This is separate from the durable world's field store. |
| **Collections** | Overdue accounts, rejected payments, moratorium holds, disconnection notices, account detail; allowed arrangement, due-date, dunning hold, referral, budget-plan, fee waiver and disconnect approval/cancellation actions. These are modeled policies, not universal regulatory rules. |
| **Data** | Browse/filter/project tabular data and download CSV; inspect monthly billing audit and other run data. Local connection links pin a revision, input set and query for CSV/JSON access while the local server is reachable. |
| **Activity sequences** | Filter causal event history by month/domain/event/account; inspect a linked sequence trace. |
| **Run statistics / VEE scorecard** | Period/year results, queue age, billing/collection and operational measures; VEE comparison against simulation truth. The scorecard is explicitly an evaluation/admin view, not knowledge granted to a worker. |
| **Glossary / dependency explanations** | Explain KPI definitions, time windows, settings' reach and causal relationships. Dependency explanations are model guidance, not empirical calibration. |

Sources: [desktop Command Center](../packages/town-viewer/dist/local-runs.js), [workspace implementation](../packages/town-viewer/dist/workspace.js), [collections implementation](../packages/town-viewer/dist/workspace-collections.js), [data page](../packages/town-viewer/dist/data-page.js), [Studio billing contract](STUDIO_BILLING.md), [KPIs and report inventory](KPIS.md).

**Map navigation differs by context.** The legacy Studio HTML includes a Map tab with layers, customer search, source files, camera controls, operations panel and quick scenarios. Current desktop analysis routes emphasize one Command Center and hide the old Map link; engine-only development still exposes the operations-day map. Living-world maps are reached through their own library/control paths. Do not assume every tab visible in `studio.html` appears in every desktop mode. See [desktop navigation contract](LOCAL_RUNNER.md) and [Studio shell](../packages/town-viewer/dist/studio.html).

### 4.3 Living-world administrator surfaces

The standalone world's base URL serves **World controls**. Its routes are implemented in [world server](../utilsim/world/server.py); the launcher library uses its protected `/local/` map/library boundary instead. These are local administrator tools, not authenticated worker portals.

| Screen / standalone route | Working controls and inspection | Status |
| --- | --- | --- |
| World controls `/` | Next day, completed days, physical meter condition, weather/history, manual advancement where allowed, observation download, explicit physical meter replacement. | Released |
| Living town `/map` | Search/select property, utility layers, pan/zoom, four-sided isometric rotation, plan view and optional 3D; inspect retained geometry and current physical records, true versus observed quantities, faults and domain links. | Released |
| Cruise control `/cruise` | Persist a target date; start/pause/resume/cancel a local run; execute due field visits before each world day; show progress/failure and recover interrupted work. | Released |
| Infrastructure risk `/hazards` | Configure utility cohort ages, age-risk coefficients, cold thresholds/multipliers; inspect calculated daily causes and model activation. | Released |
| Storm scenarios `/storms` | Schedule finite temperature/risk stress, inspect schedule and daily effects, cancel an unstarted event, page history and retry uncertain commands. | Released |
| Supply faults `/network-faults` | Choose electric/gas network assets; configure fault assumptions, start/inspect faults and explicitly restore physical supply. | Released |
| Water faults `/water-faults` | Configure/inspect downstream leaks; inject a leak and explicitly repair it; see future consumption effects. | Released |
| Water mains `/water-mains` | Inspect main fault/loss/isolation history and saved section boundaries; break, isolate, repair, restore. | Released |
| Sewer laterals `/sewer` | Inspect water-derived service's separate lateral; configure transport/storage/return assumptions, block and clear it, inspect retained/transported/overflow volume. | Released |
| Occupancy changes `/occupancy` | Schedule/cancel future physical vacancy/population changes and inspect applied history. | Released |
| Development `/development` | Plan, pause, hold for failure and resume staged work on an existing vacant serviced premise. | Released, bounded development scope |
| Customer awareness `/contacts` | Configure noticing/repeat/delay policy; inspect symptom contact history and available intentions. | Released |
| Customer cash `/customer-finance` | Configure household/business finance profiles, credit cash explicitly, inspect cash/reservations/known debt/payment intentions and provider results. | Released |
| Income and living costs `/customer-cashflow` | Set one recurring income and one essential-expense stream for an existing finance cohort; inspect paid/unfunded/skipped amounts and paged history. | Released through PR #74 |
| Payment-help contacts `/customer-notices` | Configure notice-based first noticing, repeat interval/count and availability delay; inspect contact episodes and transport. | Candidate |
| Field execution `/field-execution` | Configure crews/skills/weekday visit capacity; accept authorized local assignments; accept dependency-bound main phases; run due visits; inspect physical and message states; cancel/replace eligible pending main phases. | Released, local owner |
| Crew reports `/field-reporting` | Configure automatic/manual reporting and perform/inspect-only work; inspect actual versus claimed outcome; explicitly submit a simulated assigned-crew claim. | Released, administrator simulation |
| Visit travel `/field-travel` | Quote depot → saved premise access → depot, or explicitly selected network work-site access; show preparation/outbound/work/return duration and unavailability reasons. | Released, planning only |

The map is not a current hydraulic/power-flow solution for the daily world: its network lines show saved topology and its neutral daylight is a presentation choice. Historical observations keep their original device IDs after replacement. Missing source geometry produces a clear error; the viewer does not invent coordinates. Sources: [world map](WORLD_MAP.md), [isometric map](ISOMETRIC_MAP.md), [map projection](../utilsim/world/map_view.py).

## 5. Setup and configuration coverage

### Quick and Full are two paths through the same settings

**Released.** Quick setup has six screens: identity, services, town size, region, meter mix, and review. Full setup exposes refinement pages grouped by the subjects below. Switching paths preserves values and pins. Review and engine validation include active settings hidden by Quick setup; hidden does not mean reset to default.

The backend catalogue generates the pages from current schemas. The inspected base catalogue yields 43 Living-world pages and 117 Studio pages including Review, but these are optional refinement pages, not a requirement that a user answer 117 questions. Ordinary pages limit themselves to four top-level controls; nested lists/structures can require additional input. Search also finds settings from the other mode and explains their dormant status. Invalid values block navigation/creation; backend validation remains authoritative.

Presets change actual settings. Exact entry and sliders can pin an individual value; later presets preserve those pins. Imported overrides become pins. Reset and Use preset are distinct choices. Probability/share sliders show percentages without changing stored units. Friendly slider ranges do not narrow the engine's real validation bounds. Schema metadata distinguishes generation, run, operations and display effects and can disable unsupported/deprecated settings with a reason.

The AMI/AMR/manual control allocates **reading routes**. AMI and AMR are stored fields; manual is their remainder. The three-way bar totals 100%, with keyboard-operable handles and exact entry. It does not guarantee an exact percentage of individual meters for every generated town.

Sources: [wizard catalogue](../utilsim/config/wizard.json), [schema catalogue builder](../utilsim/config/wizard.py), [guided model](../packages/town-viewer/dist/guided-model.js), [configuration schema](../utilsim/config/model.py), [guided setup contract](GUIDED_SETUP.md).

### Configuration dimensions

| Group | Inputs the product can express | Scope / caveat |
| --- | --- | --- |
| Identity and reproducibility | Name/purpose, mode, master seed, optional subsystem seeds, start date, generation identity. | Town seed/config/version identifies generation. World commands additionally bind world/environment/run identity. |
| Utility selection | Electricity, water and gas supply selection. | Sewer observations are derived from water; this is not a fourth independent metered-network generator toggle. |
| Town size and geography | Residential home count; synthetic street pattern, hierarchy/spacing/warp; neighborhood loops/shorter blocks; terrain relief/wavelength; latitude/longitude/timezone and display units. | A single generator accepts 20–10,000 homes. Whole-utility Studio totals can be larger through checkpoints. Daily world remains UTC despite regional display settings. |
| Land use | Parks, commercial presence by road class, industry, schools and their placement/demand. | Homes, total premises, accounts, meters and registers are different counts. |
| Housing and households | Development eras, lot geometry, building/floor-area patterns, household size, occupancy/vacancy, rental share, heating/cooling, heat pumps, electric heating, EVs, solar, pools and irrigation. | Generation assumptions; changing them can regenerate households and IDs. Solar in the legacy generation/frame/year path does not imply daily-world net-export support. |
| Climate | Regional starters, Studio seasonal weather and demand thresholds; separate daily-world winter/summer means and daily variability. | Illustrative seasonal/daily models, not weather forecasts. |
| Electric engineering | Supply, diversified demand, transformers, conductor/feeder sizing, overhead/underground cutoffs, corridor routing, switches/ties and design limits. | Shapes saved assets and legacy engineering frames. Daily supply faults primarily use connectivity. |
| Gas engineering | Coverage/all-electric areas, pressure scheme, design load, main/service sizing and regulator/era settings. | Daily fault effects are not a pressure solver. |
| Water engineering | Household demand, fire-flow/design inputs, main materials/sizing, storage, pressure zones and service assumptions. | Daily main losses use explicit scenario rates, not pressure-dependent leak physics. |
| Metering and routes | AMI/AMR/manual mix, collector coverage/windows, route grouping, register digits, meter/read assumptions. | Daily-world initial settings separately expose annual failure and drift probabilities. |
| Studio operations day | Incidents, starting scenario/event, crews, shifts, response and per-day overrides. | These do not automatically activate corresponding optional durable-world policies. |
| Studio customer/billing | Account/payer mix, billing cycles, rates and charges, terms, print lag, invoice checks, collections and disconnection assumptions. | Model settings, not measured customer finances or authoritative jurisdictional policy. |
| Studio reading/VEE/anomalies | Miss rates, meter anomalies, thresholds, estimation/release behavior, validation strictness and confidence. | Produces replay reads/cases; worker eligibility comes from current case state. |
| Studio workforce | Analysts, supervisors, automation share/accuracy/pickup lag, contact agents, field skill/productivity/cost assumptions and dated staffing changes. | District or replay staffing; distinct from the durable field owner and shared runtime reservations. |
| Contact center | Arrival reasons, channel/self-service assumptions, service time, working hours, staffing, patience and related behavioral parameters. | Studio's contact simulation is separate from the world's delayed contact-intent feed. |
| KPI definitions | Selected focus figures and timing windows for on-time invoices/payments, case resolution, read release and other measures. | A changed threshold can change a KPI without changing the underlying physical/business events. |
| Optional world policies after creation | Domain fault rates, infrastructure cohorts, storms, occupancy plans, development, symptom contacts, customer cash/cashflow, field execution/report policies; candidate notice policy. | These are separate domain screens/commands, not all part of the initial guided five daily-world parameters. |

The [configuration reference](CONFIG.md) gives exact field names, defaults, units, ranges and effects. [Measured configuration impact](CONFIG_IMPACT.md) distinguishes causal levers from geometry/reseeding effects. Small synthetic populations can produce no additional rare event after a modest probability increase; this is not necessarily a broken control.

**District-size staffing candidate:** changing home count suggests analysts/contact agents using the district template, not the entire utility total. With standard defaults the documented examples are 5,000 homes → 5 analysts/3 agents and 25,000 total homes with a 10,000-home district → 11/5. Manually edited/imported/pinned staffing stays unchanged; Use size suggestion opts back in. Reloading, changing setup path or switching mode does not silently recalculate it. These are illustrative starting assumptions and remain dormant in Living-world field execution. This candidate passed focused and desktop persistence checks, but is not in the named release.

### Metrics fitting and conversational setup

The twin fitter takes observed KPI windows, customer/staff counts and constraints, moves supported model levers, and returns an engine-replayed proposal and fit information. Different levers can explain similar outcomes; payment/collections figures can be reported without being fitted, and small calibration samples make rare events noisy. Do not market the proposal as a unique diagnosis or validated forecast. See [twin contract and limits](TWIN.md), [fitter](../utilsim/twin/fit.py).

Conversational setup uses optional Anthropic access; desktop key storage uses the OS vault. Browser voice transcription support is conditional. A successfully generated proposal still passes engine validation. Neither typing to this guide nor choosing the twin creates an authenticated agent capable of operating the separate enterprise system. See [setup agent](SETUP_AGENT.md), [vault](../utilsim/worker/vault.py).

## 6. Synthetic geography, equipment, and model fidelity

The generator builds terrain, roads, land use, parcels, buildings, households and addresses, followed by networks and customer/device/read-route data. Town identity includes generation-relevant settings and generator version. Stage-specific seeded random streams and stable ordering support repeatability; content identity avoids treating browser rendering as authority.

Electricity, gas and water networks are fitted to street corridors and service taps. Equipment includes substations, feeders, transformers, overhead poles/underground routes, switches/ties, gas sources/regulators, water sources/storage/pressure-zone equipment, hydrants/valves and premise connections as appropriate. Size/placement rules aggregate demand and apply configurable engineering tables. Commercial, industrial and school premises are represented alongside homes.

The original engineering/frame path includes linearized electric voltage/power-flow behavior and water/gas hydraulic calculations with loop handling. The operations-day model uses its own incidents, dispatch and road routing. These useful components must not be described as a full engineering digital twin, nor presumed to execute in the newer daily world. The daily world deliberately uses bounded demand, connectivity, loss and balance models.

Saved worlds preserve the original full snapshot. Occupancy overlays, replacements and faults change current records and future outcomes without regenerating the map or rewriting historical reads. A new neighborhood street choice changes newly generated towns; it does not remodel existing saved geography.

Sources: [network rules](NETWORK_RULES.md), [data model](DATA_MODEL.md), [snapshot contract](CONTRACT.md), [street design](WORLD_STREET_DESIGN.md), [electric solver](../utilsim/sim/voltage.py), [hydraulics](../utilsim/sim/hydraulics.py), [world map projection](../utilsim/world/map_view.py).

## 7. Studio meter-to-cash and analysis behavior

Studio replays scheduled reads, anomalies, VEE, case queues, analysts/automation, billing, invoicing, payments, collections, contacts, field work and reliability/cost outputs from a common run definition. Dated episodes can change supported assumptions from a chosen point; prior periods remain governed by their earlier settings. A run seed can vary chance without regenerating town geography.

The reading model distinguishes AMI, AMR and manual route behavior, missing/implausible reads, actual versus estimated/released values, meter/register/device identity, and reasons for unavailable observations. VEE exposes tests, contributions, confidence and rationale. Cases can wait, age, be assigned/escalated, acquire notes/orders/holds, or be resolved through permitted actions. A late-day case is not actionable at an earlier same-day action time. The UI should use server-provided allowed actions and `actionableFrom`, rather than infer eligibility from its visual status.

Billing creates service/contract documents and account invoices, supports blocks/holds, modeled rates and fixed/variable charges, estimation corrections/rebilling, due dates, payments and dunning. Collections can model arrangements, referrals, budget billing, fees and approved disconnections. These are meaningful replay actions, but are not equivalent to the separately persisted private enterprise subledger and recipient integration.

The CLI batch path supports independent districts and an optional shared workforce/connected upstream-network model. Shared staffing coordinates district/day allocations; connected upstream assets can affect several districts and common weather. It does not model one giant shared physical network, and it is not the durable shared-workforce booking authority. Chunk size affects district boundaries and staffing, so it is part of the scenario, not simply an invisible performance knob.

KPIs cover reading, validation/estimation, exceptions/backlog, billing, cash/collections, contact center, field work, reliability and cost. The expanded report catalogue adds active-service/reference-integrity checks, invoice timing/estimation/correction/period audits, meterless/orphan associations, open reads and monthly billing audit. Definitions specify denominators and time windows. Some reports are explicitly partial or require additional data: actual print completion, e-bill adoption, full first/final settlement, administrative reading blocks and external SAP BPEM telemetry are not supplied merely by using similar labels.

Sources: [M2C](M2C.md), [Studio billing/action contract](STUDIO_BILLING.md), [KPI/report definitions](KPIS.md), [batch implementation](../utilsim/batch.py), [utility coordination](../utilsim/utility/coordinator.py), [upstream network model](../utilsim/utility/network.py).

## 8. Durable world: time, truth, observations, and knowledge

### Daily progression

The world's cursor is the **next unprocessed day**. Advancing through January 5 completes January 4; date ranges are start-inclusive/end-exclusive. Each day commits atomically. A failed day rolls back its effects; prior completed days remain durable. The same seed, configuration and actions must reproduce the same history when advanced in chunks or reopened after interruption.

The current daily order includes due development/occupancy changes, weather and storm effects, infrastructure risk/faults, commissioned-meter demand and condition, water/network/sewer consequences, readings/register reconstruction, symptom contacts, customer finance behavior and the completion checkpoint/outbox. In the finance candidate path, recurring income/essentials precede notice-reaction evaluation and new payment reservations. Source: [World.advance](../utilsim/world/store.py), [finance daily hook](../utilsim/world/customer_finance.py).

The local cruise server owns execution independently of the browser tab. It runs due field work before each physical day and persists target/status. Closing a page does not stop the job. Pause, cancel and failure are distinct states. When a managed shared runtime owns world advancement, local direct advancement/cruise cannot silently become a second clock owner. See [cruise control](WORLD_CRUISE_CONTROL.md), [cruise implementation](../utilsim/world/cruise.py).

### Four distinct layers of information

| Layer | Examples | Who may see it |
| --- | --- | --- |
| Physical/customer truth | Actual consumption, hidden leak, meter drift, unmet demand, occupied cohort, household cash, fault lifecycle. | World administrator and its permitted internal owners. |
| Available observation/message | A meter interval, source-linked derived sewer quantity, customer contact, submitted crew report, payment intention after availability. | A permitted consumer through its bounded contract. |
| Enterprise record | Accepted reading, documented estimate, work order, invoice, journal entry, case disposition. | External enterprise owner under its own permissions and processing rules. |
| Actor knowledge | What a particular worker has received or may query at the shared clock. | Authenticated actor-specific interface; not established by the administrator screens here. |

A repaired pipe can coexist with an open enterprise order. A report can claim completion while no repair occurred. An invoice can exist in enterprise records before the customer learns of it. Transport can acknowledge a message before a business process accepts it. These are intended states to preserve and show clearly.

### Observation contracts

`utility-observations/1.0` exports daily consumption quantities, not physical cumulative register readings. Electricity uses kWh; gas/water use m³. Missing readings remain null. Service slots and physical devices have separate IDs; commissioning dates prevent early readings. Hidden faults, true demand and finances are excluded.

Version 2 adds service-point/register identities, availability and provenance links, and observation-derived cumulative reconstruction. Sewer is observed water multiplied by a declared return factor; missing water yields missing sewer and sewer has no invented meter/device/register. A missing interval makes that device's reconstructed cumulative value unknown; replacement has a distinct register identity. This is not a measured physical opening/final register model. Reconstruction is cached transactionally so a late-period export need not scan all earlier history.

Stable source/batch identifiers support conflict detection and replay. A checksum is an integrity/replay identifier, **not authentication**. Consumers still enforce environment, service mapping, units, periods, availability, coverage and source conflicts. See [observation contract](WORLD_V2.md), [v2 exchange](../utilsim/world/exchange.py), [register reconstruction](../utilsim/world/registers.py), [schemas](../schemas/).

## 9. Physical domains, faults, weather, occupancy, and growth

| Domain/component | Implemented consequence | Boundary to preserve |
| --- | --- | --- |
| Electricity | Daily weather/occupancy-sensitive consumption, meter failure/drift, opt-in saved-edge supply faults, connectivity-based interrupted services and unmet demand; explicit restoration. | Daily fault model is not electrical load-flow, protection coordination or safety procedure simulation. Another fault can keep supply interrupted after one edge is restored. |
| Gas | Daily demand sensitive to generated characteristics/weather, metering condition, opt-in connectivity supply faults and restoration. | No daily gas-pressure/leak dispersion/emergency safety model is implied. |
| Water service | Persistent downstream leak increases real metered demand until repair, subject to supply and independent meter condition. | A failed/drifting meter may hide/distort the extra demand. Repair does not produce an enterprise report automatically. |
| Water main | Breaks produce unbilled loss; saved valve-bounded isolation can interrupt several premises; repair and restore are distinct stages; overlapping isolation remains effective. | Configured loss, not pressure-dependent rupture physics. Restoring a phase does not prove water quality, flushing measurements or system-wide service. |
| Sewer | Separate local lateral per water-derived sewer service, partial/full blockage, retained volume, transport capacity and overflow, explicit clearance and next-day drainage. | No sewer meter; no complete gravity network, treatment plant, infiltration/stormwater/septic system. Billing quantity and physical wastewater balance are separate. |
| Meter condition | Seeded age-sensitive failure, drift and explicit device replacement with durable work reference and prior-device history. | Default failure produces missing readings, not automatically repeated zeros. Work-reference text is not external work-order authorization. |
| Infrastructure age/cold | Optional utility cohort-age multipliers and cold thresholds on the shared daily temperature, with causal daily risk records. | Illustrative cohorts, not verified installation/condition histories for each pipe/edge. Repair does not reset age. A zero baseline remains zero. |
| Storm | Dated bounded temperature offset and four-domain risk multipliers, using existing fault handlers and shared daily transaction. | No wind/rain/flood track, weather-dependent travel or staffing disruption. Ending the storm does not repair its faults. |
| Occupancy | Dated vacancy/population changes alter future demand and customer cohort eligibility; pending changes can be cancelled. | Does not automatically create/terminate commercial contracts, issue final bills, or tell enterprise actors. |
| Development | Planned → constructing → utility-ready → occupied on an existing vacant, serviced premise; work days accrue, commissioning constrains readiness, pause/failure hold and resume preserve progress. | Does not create a new 500-home subdivision, new roads, network branches, meters, accounts or businesses. No project cancellation/release workflow in this version. |

Storm schedules last 1–90 UTC day intervals, use exclusive end dates, and cannot overlap active scheduled intervals. They can be cancelled before an affected day is processed; started events finish on their saved date. Utility multipliers require separately enabled fault models. UI and command revisions prevent an old form silently overwriting newer scenario state. Source: [storms](WORLD_STORMS.md).

Development's planned dates are lower bounds, not guaranteed completion dates. Only one phase transition occurs per day; held days do not count as free construction. Occupancy happens after readiness through the occupancy owner's transaction. Existing serviced premises may have vacant background demand before development is complete. Source: [development](WORLD_DEVELOPMENT.md).

Domain sources: [network faults](WORLD_NETWORK_FAULTS.md), [water faults](WORLD_WATER_FAULTS.md), [water mains](WORLD_WATER_MAINS.md), [sewer](WORLD_SEWER.md), [hazards](WORLD_HAZARDS.md), [occupancy](WORLD_OCCUPANCY.md). Each has corresponding `utilsim/world/` implementation, focused tests and a local acceptance script.

## 10. Customers, contacts, cash and financial evidence

### Physical service awareness — released

Occupied customers can notice experienced loss of electricity/gas/water or visible sewer overflow and create delayed, durable contact intentions with bounded repeat memory. An underground leak, missing meter transmission or undelivered bill is not automatically customer knowledge. Contact occurrence, availability, transport and physical resolution are separate. The feed excludes hidden causes/future messages; the administrator history can inspect more than a consumer may receive. Recipient acceptance does not repair the fault or necessarily stop the experienced problem. See [contacts](WORLD_CONTACTS.md), [contact owner](../utilsim/world/contacts.py).

### Cash and payment intentions — released

Profiles explicitly configure household/business recipient cohort, integer USD cash, essential reserve, maximum installment and payment probability. An administrator can credit cash with a reason and durable command. Reconfiguration does not refill the balance or transfer it to a replacement household.

The customer must learn a matching invoice through a trusted **actually delivered document** callback before the world knows any debt. Merely issuing/posting an enterprise invoice or acknowledging its transport is insufficient. A notice must refer to an already delivered invoice. There is deliberately no local button or public ingestion endpoint that manufactures delivery evidence or settlement.

Due known invoices can create payment intentions bounded by unpaid amount, available cash, other reservations, essential reserve and maximum installment. Pending provider money is reserved. Transport acceptance does not spend it. Confirmed full settlement spends once; confirmed full return restores according to the supported contract. Version-2 terminal provider-failure evidence releases only the unspent reservation, once, without refunding cash, reducing debt or inventing settlement. A timeout or lost acknowledgment is not terminal failure. A later day may create a new intention; the failed intention is never silently revived.

The payment feed contains the permitted intent and references, not the household's hidden cash, probabilities or enterprise ledger. The public model does not send real money or implement a live provider. Partial provider settlements/returns, enterprise reconciliation, customer credit/unapplied-cash and richer invoice-adjustment contracts remain separate scope. Sources: [customer finance](WORLD_CUSTOMER_FINANCE.md), [finance owner](../utilsim/world/customer_finance.py), [failure tests](../tests/test_world_customer_finance_failures.py).

### Recurring income and essentials — released through PR #74

One optional income stream and one essential-expense stream are configured per existing finance cohort. Both use explicit amount, first date and interval in whole UTC days; these are not inferred wages or calendar-month payroll. Income posts before essentials, then payment decisions use the resulting cash. Available-cash versus all-or-nothing spending determines shortfall behavior. Essentials cannot consume money reserved for a pending utility provider, but may use the reserve floor protected from utility payment decisions.

Unfunded essentials are recorded without creating debt. Income overflow is explicitly skipped with evidence. Pausing skips occurrences without later catch-up. Cashflow activity and payment-intention activity are independent. Vacancy/cohort changes suppress inappropriate effects; old provider outcomes remain reconcilable without enabling the new household's old policy. Daily amounts/history, configuration revisions and causal records are paged administrator truth. Sources: [cashflow](WORLD_CUSTOMER_CASHFLOW.md), [cashflow owner](../utilsim/world/customer_cashflow.py).

### Financial-notice reactions — candidate

An actually delivered notice for an already known, due, unpaid invoice can prompt payment-help contact when the customer cannot fund the remaining obligation after valid reservations/reserves. Recurring income/essentials apply first. An entirely reserved invoice is awaiting provider processing, not automatically a new shortfall. A random choice not to pay does not prove inability to pay.

Policy specifies first-noticing probability, availability delay, repeat interval and maximum contacts per cohort/invoice episode. **The probability governs first noticing; setting it to zero does not stop repeats in an already noticed, still eligible episode.** Pause the policy to stop new contacts. Settlement or sufficient funds stops new eligible contacts; a later shortfall can resume within the same remaining attempt budget. Additional notices do not reset the episode counter. Cohort replacement ends new reactions for the old household.

The separate `financial-contact-intent/1` feed carries payment-help/repeat-help intent and delivered-document references, with no hidden balances, private receivables or guessed commodity. Availability ordering and recipient deduplication support delayed/lost replies. This creates neither an enterprise case nor a payment arrangement. Real document delivery, caller verification, contact-center handling, dispositions and enterprise acceptance remain external integration. Sources: [notice reactions](WORLD_CUSTOMER_NOTICES.md), [notice owner](../utilsim/world/customer_notices.py), [financial contact schema](../schemas/financial-contact-intent-1.schema.json).

## 11. Field execution, reporting, cancellation and travel

### Local finite-capacity execution — released

The optional separate field owner accepts an assignment binding a crew, target, supported operation, scheduled date, order reference/revision and report delay. Crews have skills, weekday availability and a shared daily visit budget. Multi-skilled crews consume the same budget across operations. Acceptance and execution validate service commissioning and target identity; the active fault is discovered at authorized execution, rather than supplied as hidden knowledge by a worker.

Supported operations are downstream water-leak repair, electric supply-edge restoration, gas supply-edge restoration, sewer-lateral clearance, and the three water-main phases. A truthful no-fault visit consumes capacity. A blocked physical phase remains pending without pretending it was completed. Network commissioning eligibility is derived from a commissioned service in the saved component; it is not an invented installation date for the edge.

Water-main isolation → repair → restoration uses immutable predecessor assignment/checksum bindings to the same physical lifecycle. Only a real completed physical predecessor unlocks its successor. A missing report does not invalidate completed work; a false completion report cannot unlock repair. Wider supply may remain interrupted by another fault. See [field execution](WORLD_FIELD_EXECUTION.md), [four-domain operations](WORLD_FIELD_OPERATIONS.md), [main phases](WORLD_FIELD_WATER_MAINS.md).

### Work and reports are independently durable — released

Default visits perform work and produce automatic reports. An assignment can instead use manual reporting; an inspect-only visit records `not_attempted`, consumes capacity and leaves the fault active. A later manual claim can say completed/not-found regardless of physical outcome, deliberately enabling omission and misreport scenarios. Claims are immutable and once-only, with operation-specific bounded wording rather than arbitrary hidden-truth attachments.

A manual report's availability derives from its actual submission date plus delay. Dispatch acknowledgment precedes report relay. A committed report, successful transport receipt and enterprise acceptance are three different milestones. The administrator page may simulate the assigned crew principal; a payload actor ID is not an authenticated crew login. Sources: [reporting](WORLD_FIELD_REPORTING.md), [reporting owner](../utilsim/world/field_reporting.py).

### Cancellation/replacement — released, limited scope

Pending **water-main phase** assignments can be explicitly cancelled. All pending descendants must be explicitly selected; there is no silent cascade. Independently committed physical work is recovered before a cancellation decision, so an interrupted field transaction cannot make completed work cancellable. Cancellation does not reopen valves, erase reports or refund completed capacity.

A cancelled phase can be replaced atomically with new identities/local work reference, the same operation/edge and explicitly chosen valid predecessor. Original bindings and claims remain historical. This local lifecycle does not cover all water/electric/gas/sewer assignment types and does not send an enterprise cancellation/rework receipt. Source: [cancellation](WORLD_FIELD_CANCELLATION.md).

### Travel — released planning; shared booking candidate

The travel screen uses saved roads, explicit depot, class-specific speed assumptions, preparation and on-site work duration. Water and sewer visits resolve their existing premise access. Network-edge and main-phase planning requires an administrator-selected saved road/fraction and explicitly labels it a planning assumption; it is not proof of the actual physical work location.

Quotes return outbound/return route and time, work/preparation duration, identities and checksums. Missing/disconnected/malformed road access returns unavailable; there is no invented straight-line fallback. Changing assumptions invalidates the displayed quote. Quoting does not inspect hidden faults, mutate either owner, reserve a person, consume time or authorize a visit.

The shared-runtime adapter candidate binds **accepted downstream-water `repair-water-leak` assignments only** to existing runtime jobs/resources/reservations. It checks saved-road preparation/outbound/work/return against a complete same-day local shift, crew skills/weekdays and capacity, pins the crew's resource mapping, and uses actual runtime calendar conversion for DST. Physical effects begin at the first UTC boundary at or after the full visit ends, preserving original visit-day capacity and already sampled history. Overnight shifts and other operations are not supported in this initial slice. There is no browser endpoint that accepts a purported runtime receipt.

Its real-runtime acceptance covers one repair and one cancelled visit on a 570-premise fixture, original-job retry after a lost acknowledgment, delayed reporting, DST handling and source/history preservation; 127 focused field tests passed. This is unmerged opt-in adapter evidence, not released general dispatch or private recipient wiring. The released planner remains read-only. Sources: [managed-field contract](WORLD_FIELD_MANAGED.md), [adapter](../utilsim/world/field_managed.py), [travel](WORLD_FIELD_TRAVEL.md), [travel implementation](../utilsim/world/field_travel.py).

### Recovery across field and world owners

The world commits the physical result and its idempotency journal together. The field store separately commits visit/capacity/report state. If the second commit is lost, reopening recovers the original physical result and charges the original day's capacity without doing the repair twice. Manual reporting stays manual during recovery. A report failure does not roll back an independently committed repair. A downgrade/restore after field work requires coordinated world and field checkpoints; a field-only pre-migration backup is not a complete run rollback.

## 12. Integration and authentication boundaries

The desktop worker uses loopback, Host restrictions, no cross-origin access and a per-launch bearer credential for `/local/` library/job/world queries. The standalone world administrator server binds loopback and checks Host/Origin/content type and asset containment. These controls do not constitute a multi-user enterprise authorization system. Do not expose these administrator routes as remote worker or AI tools.

Managed daily delivery atomically stores immutable outgoing observations with the completed physical day. The relay sends to an explicitly permitted loopback runtime endpoint using a separately provisioned credential; credentials are not stored in world messages/status. The authenticated runtime supplies actor identity, enforces operation grants and controls availability/processing. Distinct roles for advancing world days and ingesting observations avoid using an all-powerful administrator principal for both.

An accepted inbox receipt does not prove successful processing. Unknown acknowledgments retain the same pending identity/payload; a failed recipient job needs explicit recovery. Predecessor-linked days cannot overtake an unaccepted handoff. Shared runtime retries must not independently regenerate a day, bypass its clock or create competing local progression.

The existing public acceptance driver targets an earlier runtime/utility foundation and has proved limited delayed-delivery/lost-reply behavior with test fixtures. It is not evidence that all current enterprise adapters are connected. Separate private work, verified read-only at revision `0bc113d0` in an **unmerged draft**, now routes explicitly bound water-field acknowledgements and reports through authenticated runtime jobs into actual Billing transactions. Its isolated acceptance demonstrates real repair and false-completion cases, delayed availability and lost-reply recovery. Both reports remain pending for clerk review; receiving a claim does not close the order. The private merge/deployment hold remains, and connecting that recipient to the new public shared-visit adapter is still separate work.

Actual invoice-delivery/payment recipient work has been claimed in a separate private branch, but has no completed adapter acceptance at this document's review point. Provider, document, contact and report owners must validate recipient/account/service/operation identities and operation-specific evidence before business acceptance. Neither an implementation claim nor an unfinished branch is a delivered capability.

Design-critical external seams:

- Bind delivered documents to the correct simulated recipient/cohort, premise and run. An account invoice spanning premises must not become duplicated household debt.
- Confirm actual document delivery before customer knowledge; distinguish issued, posted, queued, delivered and learned states.
- Let the provider persist its result and independently retry world cash evidence and enterprise posting. One side can succeed while the other remains pending.
- Validate field dispatch/order revision, physical operation and permitted target. Receiving a submitted claim must not automatically close a business order or trigger repair.
- Preserve queues/blocked work when required evidence or acceptance is absent. Do not auto-reconcile truth and records in the UI.
- Use the existing shared scheduler/reservation owner for workforce timing; do not add a second “helpful” scheduler in a redesigned screen.

Sources: [world delivery/runtime contract](WORLD_V2.md), [delivery transport](../utilsim/world/delivery.py), [scheduled handler](../utilsim/world/runtime.py), [integration acceptance driver](../scripts/world_runtime_acceptance.py), [worker server](../utilsim/worker/server.py).

## 13. Outputs, exportability, recovery and audit

| Output | What it is useful for | What it is not |
| --- | --- | --- |
| `utility-town/2.0` full snapshot | Stable geography, assets, service/customer model, renderer and new-world initialization. | Current durable history or enterprise truth. A `town.json` manifest alone is not its replacement. |
| Viewer snapshot, state frames and replay | Engine-driven visualization, operation-day inspection, receiver integration. | A replacement simulation implemented in the browser. |
| GeoJSON, Parquet/tables, PNG and VEE fixtures | GIS/data analysis, BI/mock datasets, demonstrations and contract testing. | Real utility/person data or validated forecasting outputs. |
| `.utilitysim.json` | Portable simulation setup, seed and scenarios. | Entire archived result or world/field database backup. |
| Run bundles/revisions | Inputs, archived tables, monthly views, scorecard, year/state exports, integrity verification and offline review. | Permission to mutate an old result in place. |
| CSV/JSON local connection links | Query data with chosen fields/filters across district checkpoints. | A hosted always-available external API; local server/address is required. |
| World SQLite and field SQLite | Durable owner state, events, receipts and checkpoint/recovery evidence. | Safe worker-visible data sources; they contain administrator truth. |
| Observation v1/v2 and intent/report feeds | Bounded cross-owner evidence with stable identities/provenance/availability. | Business acceptance, customer delivery, payment settlement or authorization by themselves. |
| Acceptance `result.json`, logs and screenshots | Reproduce exactly what a checker exercised and compare source/history hashes. | Automatic proof of all integrated scenarios or broad performance. |

Creation validates and pins the exact full source snapshot, identity, settings and model version before initialization. A saved creation UUID allows retry after a lost reply/source-file disappearance without rebuilding or resetting the now-advanced world. Reusing an ID for different content is rejected. Library registration rejects replaced/foreign files and unsupported versions, preserves missing-drive entries and uses read-only consistent projections.

Across optional domains, the common pattern is strict versioned commands, current identity/date/revision checks, exact retry results, append-only causal evidence, additive migrations and a pre-feature backup where documented. Read-only inspection does not silently opt a world into a new model. New history remains intact when a policy is paused; disabling new faults does not repair existing ones. These are important states for UI copy, not incidental implementation details.

Sources: [world creation](../utilsim/worker/world_creation.py), [world library](../utilsim/worker/worlds.py), [run bundles](RUN_BUNDLES.md), [export contract](CONTRACT.md), [world migrations](../utilsim/world/migrations.py).

## 14. Verification and performance: what the evidence actually establishes

The following are **dated results**, not a claim that this document reran every test or that their counts equal a later combined branch's suite. Acceptance scripts generally operate on new/copy-only stores and verify that source snapshots and previous observations remain unchanged.

| Evidence | Recorded result | Practical limit |
| --- | --- | --- |
| Released continuation, 9 October 2026 | 1,150 non-slow Python tests; 301 viewer tests; 11 viewer-conformance checks; Ruff; four packaged desktop runtimes published after PR #73. | Component/regression and packaging evidence, not all cross-system scenarios. |
| Household cashflow, 9 October 2026 | 1,194 non-slow Python tests, 301 viewer, 11 conformance; focused finance/HTTP and desktop acceptance, followed by successful CI and four-platform publication. | Applies to that tested revision, not proof of later uncommitted combinations. |
| Combined notice/staffing/managed-field candidate, 9 October 2026 | 1,268 non-slow Python tests in 1,496.01 seconds; Ruff, 304 viewer tests and 11 conformance checks; independent cross-feature review. | Local regression with three existing deprecation warnings; CI, merge and publication remain separate milestones. |
| Cashflow cohort diagnostic | 300 configured cohorts × 60 days, 18,000 cashflow records per world; uninterrupted/reopened runs match twelve domain digests and conserve cash; 98,280 physical-truth rows. | Synthetic local scenario with no invoices, provider intentions or enterprise transactions. Configuration alone took roughly 100–118 seconds per compared world. |
| Cashflow diagnostic timing | Physical advancement 35.277/42.231 seconds; total diagnostic 307.589 seconds. | Hardware/workload-specific component timings; not an integrated throughput guarantee. |
| Notice candidate | 50 focused tests and a 570-premise desktop fixture; 32 contacts, 25/7 history pages, delayed availability and retry/pause/restart checks at 1440/960 widths. | Eight explicit fixture households and synthetic trusted delivery, not a real enterprise recipient. |
| Guided staffing candidate | 19 focused checks plus real 117-page desktop traversal/persistence checks at 1440/960 widths. | Validates setup suggestions and retained configuration, not staffing sufficiency or runtime capacity. |
| Storm diagnostic | Seven-day 5,864-premise check, preserved source/map hashes and restart identity; separate finite-crew recovery comparison. | Short physical component run, not multi-year financial/workforce integration. |
| Local field/world acceptance | Copied-town multi-domain visits, main phases, missing/false reports, cancellation, capacity and independent-owner recovery; paired month-long replay comparisons documented. | Test inbox receipt does not close an enterprise order. |
| Historical Studio district batch | 50,000 homes in 25 × 2,000-home districts: 505 seconds, 313 MB archives, 61,104 accounts, 164,985 registers, reported peak child RSS 744 MiB. | One development environment and older specific scenario; not one large durable world. Full configured 500,000-home cap was not benchmarked by that result. |
| Historical long horizon | Small fixtures advance/reopen across years; one-premise five-year cruise and small multi-year world checks exist. | Proves temporal/restart behavior, not realistic utility-scale capacity. |
| Physical scale preflight, 9 October 2026 | A bounded two-world run with 15,892 actual source accounts reached 38 days per world in 607.68 seconds, with approximately 1.459 million physical-truth rows and the same observation count; integrity, replay and source-hash checks passed. The harness has four safety tests. | Partial progress toward a 1,826-day target, not a completed five-year run. Two independent districts; physical-only, without integrated bills/calls/field/workforce acceptance. |

Consult [acceptance ledger](WORLD_ACCEPTANCE_MATRIX.md), [delivery status](WORLD_DELIVERY_STATUS.md), [cashflow evidence](WORLD_CUSTOMER_CASHFLOW.md), [parallel acceptance](WORLD_PARALLEL_ACCEPTANCE.md), [batch measurements](RUN_BUNDLES.md), and [scale harness](../scripts/benchmark_world_scale.py) for exact scope and later results.

The target of approximately 15,000 accounts over five years with connected observations, bills, contacts, orders and workforce remains an **integrated acceptance target**. Counts of homes, premises, accounts, meters and registers cannot be substituted for one another. A configured limit, a test count or a short physical-only benchmark is not that acceptance.

## 15. Coverage matrix for design decisions

This matrix summarizes product coverage. “Partial” does not mean decorative: many rows have real state changes, but their full cross-owner outcome is still incomplete.

| Capability family | Public coverage | Design implication / remaining gap |
| --- | --- | --- |
| Downloadable local app | Released | Preserve clear library/runtime/version state and offline operation. |
| Guided setup and portable definitions | Released; staffing refinement candidate | Keep Quick concise, Full discoverable, pins visible, mode-specific settings explicit. |
| Synthetic geography and three supply networks | Released | Preserve stable town identity and source geometry; distinguish homes from all premises. |
| Four utility domains | Released, bounded | Sewer is water-derived observation plus a local lateral model, not an independent metered sewer network. |
| Studio year/scenario analysis | Released | Rich analysis/workspace flow; do not equate replay state with durable enterprise records. |
| Large Studio utility batches | Released, cap beyond measured scale | Show checkpoints, per-district staffing and measured ETA; preserve compound IDs. |
| Current durable map | Released | Clearly badge administrator truth and unknown quantities. |
| Daily physical history and restart | Released | Show next unprocessed day, history preservation and clock owner. |
| Delayed observations and durable relay | Released component; external integration partial | Separate availability, transport acceptance, processing and rejected/blocked work. |
| Persistent four-domain faults | Released | Show continuing physical consequences and explicit repair, not automatic resolution. |
| Storms/age/cold | Released parameterized models | Label scenario assumptions; no implied weather track, calibration or travel disruption. |
| Physical occupancy/moves | Released component | Commercial account/contact/first-final billing integration remains separate. |
| Development | Released on saved vacant serviced premises | Do not depict working greenfield/subdivision/network-construction capability. |
| Customer symptom awareness | Released intentions | Real contact handling and service disposition are external. |
| Customer cash/provider evidence | Released component | Clearly distinguish reservation, accepted intent, confirmed settlement/return/failure and enterprise posting. |
| Recurring income/essentials | Released through PR #74 | Explicit cadence/cents/funding assumptions, shortfalls without invented debt. |
| Financial-notice contacts | Candidate | Delivered evidence and genuine shortfall required; no automatic enterprise arrangement. |
| Field visits and skills/capacity | Released local owner | Assignment validity and physical progress are independent of business-order status. |
| Missing/late/false field reports | Released local owner | Show actual outcome and claim separately only to authorized administrator views. |
| Main phase cancellation/replacement | Released bounded lifecycle | Preserve immutable history and explicit descendants/new work references. |
| Saved-road travel estimates | Released planning | Do not imply booking, validated network site or elapsed execution time. |
| Shared-runtime field reservations | Unmerged candidate with bounded integration acceptance | Verify the final operation scope and release before general UI exposure; private enterprise recipients remain separate. |
| Authenticated enterprise workforce/AI | External owner / incomplete here | Administrator pages and actor text are insufficient; bounded knowledge, roles, budgets and evidence access needed. |
| Provider/document/contact/field recipient adapters | External owner / partial; private water ack/report draft locally verified | Keep clerk review distinct from receipt. Invoice/payment adapter work is in progress; do not fill missing transitions with fabricated receipts or automatic closure. |
| BI/export/audit | Released with report-specific limits | State denominators, provenance, snapshot/revision and unsupported source fields. |
| Fifteen-thousand-account five-year integrated scale | Unverified | Instrument and measure the full loop; current physical preflight is only one layer. |

### Twelve scenario checks: current public contribution and what still needs proving

The detailed [acceptance ledger](WORLD_ACCEPTANCE_MATRIX.md) owns closure evidence. No row below claims complete integrated acceptance.

| Scenario | Existing contribution | Missing complete-loop demonstration |
| --- | --- | --- |
| SCN-001 Hidden leak | Hidden persistent leak, altered observations, local repair and independent report. | Actual enterprise detection → authorized shared-time work → accepted evidence/closure, with no truth leakage. |
| SCN-002 Broken meter / repeated zeros | Failure/missing observations, condition history and physical replacement; Studio anomaly/VEE history. | Deliberate repeated-zero semantics, escalation, actual reread/exchange and controlled billing release across owners. |
| SCN-003 New 500-home subdivision | Staged existing-premise development and occupancy. | New geography/services, delayed operational knowledge, account/meter onboarding and downstream workloads at that size. |
| SCN-004 Major weather event | Shared temperature/risk effects, faults, symptom contacts and local finite crews. | Weather effects on travel/availability and full enterprise backlog/recovery curve. |
| SCN-005 Billing batch failure | Runtime/job and Studio billing components with failure/retry concepts. | Real scheduled overnight batch strands work, grows unbilled population and produces measured catch-up downstream load. |
| SCN-006 Payment processor failure | Customer-known invoices, reserved intentions, terminal failure and confirmed cash outcomes. | Actual delivery/provider/ledger adapters, wrong/pending enterprise balance consequences and reconciliation. |
| SCN-007 Rate increase → call demand | Studio rate/contact assumptions; candidate delivered-notice payment-help behavior. | Actual effective-date bills/delivery and segment-specific inquiry/dispute/help handling. Notice shortfall alone is not this scenario. |
| SCN-008 Disconnect with continued use | Separate physical truth and enterprise concepts. | Authorized physical disconnect outcome, persistent consumption, observation-based detection and corrective work. |
| SCN-009 Work complete, report missing | Working manual/misreport model and physical/field recovery. | Actual enterprise state stays open until authorized evidence handling/reconciliation. |
| SCN-010 Seven staff versus five | Studio staffing levers and local fixed-workload capacity comparisons. | Shared travel/shift-reserved comparison with unchanged demand and downstream bills/contact/collections effects. |
| SCN-011 Veteran versus new hire | Studio productivity/error assumptions and local controlled misreporting. | Per-worker profiles bound to durable shared execution with measured equivalent workload and rework. |
| SCN-012 Move-in / move-out | Physical occupancy/cohort isolation and separate commercial model components. | Actual customer contact, service/account actions, four-domain first/final reads/bills and stuck-state consequences. |

## 16. Explicit nonclaims and design priorities

Do not represent the present public application as:

- A complete SAP IS-U/Oracle Utilities clone, certified tariff/regulatory engine, or production financial system.
- A multi-user authenticated operational portal simply because it has enterprise-style screens or actor IDs.
- A calibrated utility forecast, real geographic digital twin, or comprehensive electric/gas/water/sewer engineering solver.
- A connected 500,000-home durable physical world; that number belongs to the Studio batch limit.
- A completed 15,000-account, five-year integrated workforce/financial benchmark.
- A greenfield subdivision/network construction tool or full commercial move-in/out and first/final settlement system.
- A working live bank/payment, document-delivery, contact-center or enterprise report adapter because a fixture callback accepted a message.
- A complete hourly workforce/parts/materials/contractor model or automatic travel-constrained durable execution because routes and local visit counts exist.
- A mobile product, cloud SaaS account service, omniscient AI worker, or live remote utility integration.

Recommended design priorities follow from the working boundaries:

1. **Make context legible.** Keep mode, environment/world, run/revision, date semantics, runtime version and clock owner visible. A user should immediately know whether they are reviewing a Studio replay, inspecting administrator truth, or working an authorized enterprise record.
2. **Use a consistent evidence timeline.** Show occurred, observed/learned, available, submitted, received, processed and accepted only where each exists. Do not collapse them into one “complete” badge.
3. **Separate physical and administrative outcomes.** Repair, claim, transport and business closure can disagree. Display the mismatch without silently repairing it.
4. **Keep settings understandable.** Distinguish illustrative assumption, generated asset property, runtime policy, dormant setting and measured outcome. Preserve pins, dependencies, validation and explicit reset semantics.
5. **Consolidate discovery without changing authority.** A coherent world navigation can link the currently separate domain pages; it must not give worker contexts access to cash, hidden faults or future plans.
6. **Expose recoverable states.** Pending creation, missing drive, stale revision, blocked phase, unknown receipt, failed recipient job and interrupted owner commit need a clear reason and the correct exact-retry action.
7. **Design scale honestly.** Use paged lists, stable identities, clear counts, scoped filters, progress stages and partial-result labels. Avoid loading every physical/customer record just to draw a dashboard.
8. **Treat the twelve scenarios as acceptance stories.** Design each cross-owner handoff and failure state, then require observable evidence at every boundary before labeling the larger workflow complete.

The repository already supplies substantial reusable behavior. The principal remaining product challenge is to connect those behaviors through explicit ownership, delayed knowledge, authenticated action and measured capacity without letting a polished interface imply integrations or fidelity that do not yet exist.
