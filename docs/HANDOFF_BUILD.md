# Build handoff: the portal as command centre, the offline worker, utilities and campaigns

*For Astra. October 3, 2026. Companion to [PORTAL_ARCHITECTURE.md](PORTAL_ARCHITECTURE.md) (the architecture),
[DATA_FIRST.md](DATA_FIRST.md) (what gets generated), [RUN_BUNDLES.md](RUN_BUNDLES.md) (step 1, implemented) and
[M2C.md](M2C.md) (the engine being replayed). This document is the instructions: what to build, in what order, what
"done" means for each step, and the rules every step follows.*

Read in this order: this page end to end, then PORTAL_ARCHITECTURE.md, then RUN_BUNDLES.md and the step 1 code
(`utilsim/io/run_bundle.py`, `packages/town-viewer/dist/run-bundle.js`, `runs.js`), then DATA_FIRST.md when you reach
milestone 6.

## 0. How to use this document

Each milestone below has the same parts:

- **Goal and done-when.** The acceptance test in plain words. A milestone is finished when every done-when line holds
  on `main`, in CI, and on the Vercel deployment where it applies.
- **Build.** The modules, pages and files to add or change, by path. Names are proposals; keep them unless a better
  name is obvious, and record renames in the PR.
- **Contracts.** Every payload that crosses a boundary (browser ↔ control plane, control plane ↔ worker, worker ↔ disk)
  has a `schemaVersion`, a JSON Schema in `schemas/` and a row in [CONTRACT.md](CONTRACT.md).
- **Tests.** What CI must prove. Python tests in `tests/`, viewer tests in `packages/town-viewer/tests/*.test.mjs`.
- **Out of scope.** What the milestone deliberately does not do, so it can land.

Work one milestone per branch and pull request (several PRs per milestone are fine; one PR for several milestones is
not). The rules in §4 apply to every PR.

## 1. Where things stand (October 3, 2026)

**Engine** (`utilsim/`, Python 3.11, numpy, pydantic, FastAPI; generator `0.9.1`, snapshot `utility-town/2.0`):

- Generic town generation from settings and a seed (synthetic streets, no real places): parcels, buildings,
  households, electric, gas and water networks, customers, meters, registers, installations, tariffs, reading routes.
- The operations day (incidents, crews, outages, hydraulics, power flow) and a full meter-to-cash year: reads, VEE,
  work queues, billing documents, invoices, payments, dunning and collections, deterministic from seed and settings.
- The contact centre: sixteen reasons customers phone in, triggered by the year's bills, notices, moves, field
  visits, outages and gas leaks, answered by self-service, agents, call backs and an emergency line, every reason and
  lever a run setting (M2C.md "Contact centre").
- Episodes (dated setting overrides, a scenario library of 20), 29 flat data tables with facets, search, sort, paging
  and CSV, the 12-month trend, the VEE scorecard, costs by exception type, the engine guide.
- Step 1 of the portal architecture: `utilsim export-run` writes a content-addressed archive
  (`store/runs/<runKey>/`, `run-manifest/1.0`), reusing a verified archive instead of replaying.

**Studio** (`packages/town-viewer/dist/`, vanilla ES modules, no framework): Map (isometric), Workspace, Data, Year,
Configuration (with the engine guide), and **Runs** (`runs.html`), which opens an archive from a folder or a URL and
shows Year, Data, month-end Workspace snapshots and the scorecard without an engine.

**Hosting:** Vercel serves the static Studio plus one Python function (`api/index.py`) that answers for the four
prebuilt packs and generates towns up to 6,000 houses. Limits that shape everything below: 60 s per request, about
1 GB of memory, 4.5 MB per response.

**Measured** (one 4-core container):

| Town | Homes | Accounts | Registers | Generate | Replay the year |
|---|---|---|---|---|---|
| `village` | 480 | 635 | 1,698 | 3 s | 2 s |
| `small_town` | 1,900 | 2,368 | 6,350 | 9 s | 6 s |
| `town` | 3,300 | 3,969 | 10,071 | 14 s | 11 s |
| `large_town` | 5,500 | 6,598 | 16,416 | 23 s | 15 s, about 260 MB, 187,767 documents |

A 100,000-account utility is therefore 10 to 40 towns, replayed side by side in a process pool in minutes, with
150 to 300 MB of archives on disk and about 100 KB of aggregates online per run. Nothing in the engine needs to get
faster for this plan; it needs an object above the town, a place to run, and a portal that commands it.

**Not built yet:** account login, the launcher, pairing, the control plane (jobs, runs, specs, devices), the worker
loop, the Runs queue and Utility board in the Studio, the utility spec and structure synthesis, roll-ups, campaigns,
year chaining.

## 2. The target in one page

Five principles, from the architecture, that decide every design question below:

1. **The portal never computes a run.** It composes inputs, tracks jobs, keeps small results and renders them.
2. **Big data stays where it was made.** Archives live on the worker's disk; the portal holds aggregates, and details
   only on request.
3. **Everything is content-addressed.** A run is a pure function of the engine build and its inputs, named by its run
   key; identical jobs are served from the store; any result can be regenerated.
4. **Pull, not push.** The worker makes outbound HTTPS calls (pair, heartbeat, claim, upload). Nothing reaches into a
   laptop; the local API binds to loopback.
5. **Degrade gracefully.** No worker online means jobs wait and everything stored still renders; small packs keep
   using the hosted engine live.

The user flow the milestones build, in order: **log in to Sim → download and open a small launcher → configure
online → pair with an eight-character code → see the computer Ready with the configuration received → queue a run
from the Year calendar or Configuration → watch aggregates land on the Runs page → open details on request → run a
campaign in month batches and decide at each check-in.**

Where data lives:

```
browser        Studio state (episodes, actions, view date), nothing durable
control plane  KV: accounts' configurations (revisioned), pairings, devices, jobs, runs index, campaigns, specs
               Blob: runs/<key>/aggregates.json (always), runs/<key>/details/<file> (on request, evictable), specs
worker disk    store/towns/<townId>/…, store/runs/<runKey>/… (RUN_BUNDLES.md), store/device.json (credential)
```

## 3. Milestones

The numbering matches the status table at the end of PORTAL_ARCHITECTURE.md. Update that table's Status column as
each milestone lands.

### Milestone 1: run archives and the read-only Studio (done, PR #18)

What exists and what the following milestones build on:

- `utilsim/io/run_bundle.py`: `export_run(snapshot, request, store)` writes `store/runs/<runKey>/` atomically
  (manifest last), reuses a verified archive, refuses a corrupt one. The run key is BLAKE2b-256 of the engine build
  identifier, a NUL and the sorted-key JSON of the canonical inputs (snapshot digest, effective settings, seed,
  ordered episodes, actions and interruptions, export date). `request` is the Studio's `viewer-m2c-run/1.0` export or
  the API's `RunRequest` fields.
- The archive: `manifest.json`, `inputs.json`, `aggregates.json` (`run-aggregates/1.0`), `trend.json`,
  `scorecard.json`, `snapshot.json.gz`, `tables/catalog.json`, `tables/<table>.json.gz` (`run-table/1.0`),
  `summaries/<date>.json`, `worklists/<date>.json.gz` (`run-worklist/1.0`) at each month end through the export date.
- The Studio's `runs.html` (`runs.js`, `run-bundle.js`, `runs.css`): opens a folder or `?run=<url>`, checks every
  file against its size and SHA-256, reuses the Year and Data pages read-only, shows Workspace snapshots and the
  scorecard. `node web/serve.mjs` serves a store at `/runs/` when `UTILSIM_RUN_STORE` names it.
- Tests: `tests/test_run_bundle.py` (archive equals the engine's own pages, reuse without replay, corruption and
  interrupted writes) and `packages/town-viewer/tests/run-bundle.test.mjs` (the reader's selection, sorting and CSV
  agree with Python).

Two things to keep from step 1 in every later step: the archive is both the upload format and the local store, and
the Studio pages take a client object (`getClient`) and a `readOnly` flag rather than talking to an engine directly.
Portal mode is a third client beside `EngineM2C` (live) and `SavedM2C` (archive).

### Milestone 2: account, configurations, pairing codes, device registry

**Goal.** A logged-in user saves a configuration, issues a pairing code, a device redeems it and reports a heartbeat,
and Sim shows that computer with the configuration revision it received. No engine is involved.

**Done when**

- A user logs in to the hosted Studio and sees an Account page with their configurations and computers; another
  account sees none of them (a test proves scoping on every route).
- "Connect a computer" shows a code such as `K7M2Q9RX` with a ten-minute countdown; the code is single-use, expires,
  and two concurrent redemptions cannot both succeed (a test runs them concurrently).
- A test device (a Python client in the test suite) redeems the code, receives a device credential, fetches its
  assigned configuration revision and heartbeats; the Account page shows it as **Preparing** then **Ready** with the
  revision number, and "last contact" updates.
- Revoking a computer invalidates its credential at once; its next heartbeat is refused.
- `api/index.py` still imports without scipy and shapely, and the new router imports nothing from `utilsim.gen`,
  `utilsim.sim` or `utilsim.m2c` (add a test that walks the module graph).
- Everything works locally with no cloud account: `uv run utilsim serve` plus `node web/serve.mjs`, storage in a
  folder, a development account from an environment variable.

**Build**

- `api/_portal.py`: a new FastAPI router mounted in `api/app.py` and `api/index.py`. Routes from the architecture's
  table, this milestone's share: `POST /api/pairings`, `POST /api/pairings/redeem`, `GET /api/devices`,
  `DELETE /api/devices/{id}`, `POST /api/devices/heartbeat`, `GET /api/device/config`, and configurations
  (`GET/POST /api/configurations`, `GET /api/configurations/{id}`, `POST /api/configurations/{id}/revisions`).
- `api/_kv.py`: a key-value interface (`get`, `set`, `delete`, `list(prefix)`, `claim(key, owner, ttl)` as an atomic
  compare-and-set) with two implementations: a local JSON folder (`UTILSIM_PORTAL_STORE`, default `.utilsim_portal/`)
  for development and tests, and the hosted provider (recommendation: Vercel KV or Upstash Redis; the choice is yours,
  the interface is not). `api/_blob.py` likewise: `put`, `get`, `signed_upload_url`, `signed_download_url`, `delete`,
  local folder and Vercel Blob.
- `api/_auth.py`: `current_account(request)` as a FastAPI dependency. Hosted: a session cookie from an identity
  provider (recommendation: email magic links through a hosted provider; keep the provider behind this one function).
  Local: `UTILSIM_DEV_ACCOUNT=<email>` names the account. Device routes authenticate with `Authorization: Bearer
  <device credential>`; credentials are random 32-byte tokens stored hashed (SHA-256) with the device record.
- Pairing codes: 8 characters from an alphabet without `0 O 1 I L`, random, stored hashed, `expiresAt` ten minutes
  out, `redeemedAt` set atomically by the `claim` primitive so a second redemption fails. Rate limit: 10 failed
  redemptions per code per minute per IP, then refuse until the code expires.
- Studio: `account-page.js` (route `#/account`, a cog-menu entry and a header avatar), `portal.js` (the browser
  client: configurations, pairings, devices, later jobs and runs). Reuse the Configuration page's schema form for a
  configuration's inputs; a configuration is the Studio's `viewer-m2c-run/1.0` export plus a name, or (milestone 6)
  a utility spec reference.

**Contracts** (add schemas and CONTRACT.md rows)

- `configuration/1.0`: `{id, accountId, name, revision, inputs: viewer-m2c-run/1.0 | {spec: <id@version>},
  createdAt, updatedAt}`; a revision is immutable once a job or device references it.
- `pairing/1.0`: `{id, accountId, configurationId, codeHash, expiresAt, redeemedAt, deviceId}`.
- `device/1.0`: `{id, accountId, name, platform, engineVersion, capabilities: {cores, memoryGB, maxAccounts},
  readiness: preparing | ready | disconnected, configurationRevision, lastSeenAt, revokedAt}`.
- `heartbeat/1.0` (request body): `{engineVersion, engineBuild, capabilities, readiness, configurationRevision,
  message}`; the response carries the assigned configuration id and revision and, from milestone 4, whether jobs wait.

**Tests.** `tests/test_portal_pairing.py` (single use, expiry, concurrency, rate limit, scoping, revoke),
`tests/test_portal_imports.py` (no engine imports in the control plane), `tests/test_hosted_deploy.py` extended for
the new router; viewer `account-page.test.mjs` (markup for code display and device states).

**Out of scope.** The launcher binary, the runtime download, any job. The device in this milestone is a test client.

### Milestone 3: the launcher, the cached runtime, the local server, Ready

**Goal.** Double-click a small launcher, enter the code from Sim, see **Ready**; Sim shows the computer Ready with the
configuration revision received. Pairing does not start a simulation.

**Done when**

- On macOS (arm64 and x64), Windows x64 and Linux x64 the launcher starts, shows a pairing screen in the default
  browser (`http://127.0.0.1:8010/launcher`), accepts the code, downloads and verifies the runtime once (progress and
  size shown as **Preparing**), starts the local engine and reports **Ready**.
- Quitting and reopening reconnects without a new code; revoking from Sim puts the launcher back on the pairing
  screen with the stored archives intact.
- A tampered runtime download is refused (signature and SHA-256 both checked) and the previous runtime keeps working.
- The launcher is under 20 MB per platform; the runtime size per platform is measured and written into RUN_BUNDLES.md.
- The whole pairing flow runs in the Python test suite against the control plane in-process, with a fake runtime
  (no real download), so CI covers it without a desktop.

**Build**

- `utilsim/worker/` (engine side, Python): `device.py` (the credential store: platform keychain through `keyring`
  when available, else `store/device.json` with 0600 permissions), `agent.py` (pair, heartbeat every 30 s with
  engine version and build, cores, memory and a `maxAccounts` estimate, readiness, the configuration revision held;
  fetches `GET /api/device/config` and caches it under `store/config/<revision>.json`), and the CLI entry
  `utilsim worker --portal <url> --store <dir> [--serve] [--cores N]`. `--serve` starts the local API (today's
  `api.app`) with two extra routes: `GET /launcher` (the status and pairing page, plain HTML served by FastAPI) and
  `POST /api/local/pair` (the code, forwarded to the control plane). The local API binds to `127.0.0.1` only.
- `launcher/` (a new top-level folder, its own CI job): the small bootstrapper. Recommendation: Go, one static binary
  per platform, no runtime dependencies. It reads a runtime manifest (`runtime/<version>/manifest.json`: files,
  sizes, SHA-256, Ed25519 signature) from the portal's static hosting, downloads to `~/.utilsim/runtime/<version>/`,
  verifies, extracts, starts `utilsim worker --serve` from that runtime as a child process, opens the launcher page,
  and supervises (restart on crash, stop on quit). The runtime itself is Python (python-build-standalone) plus the
  `utilsim` wheel and its dependencies plus the Studio assets, built by a script `scripts/build_runtime.py` and
  published with the deployment.
- Signing: one Ed25519 key pair; the public key is compiled into the launcher; the private key lives only in the
  release workflow's secrets. Code signing and notarisation of the launcher itself (Apple, Windows) are part of this
  milestone's release checklist, not of CI.

**Contracts.** `runtime-manifest/1.0`: `{version, platform, files: [{name, bytes, sha256}], engineVersion,
engineBuild, signature}`. `local-status/1.0` (what `/launcher` polls): `{paired, account, device, readiness,
configurationRevision, engineVersion, lastContactAt, message}`.

**Tests.** `tests/test_worker_pairing.py` (agent against the in-process control plane: pair, heartbeat, config
receipt, revoke, reconnect with stored credential), `tests/test_runtime_manifest.py` (verification refuses a wrong
hash or signature; a resumed download completes). Launcher: Go unit tests for manifest verification and the
supervisor state machine; a smoke run in CI on Linux with the fake runtime.

**Out of scope.** Jobs. Auto-update beyond "download a newer runtime when the manifest says so".

### Milestone 4: jobs, runs and specs; the worker claims, replays, uploads; leases

**Goal.** A job created online is claimed by the paired worker, replayed into an archive, and its aggregates and
manifest appear in the portal; details are uploaded on request; a crashed worker's job returns to the queue.

**Done when**

- `POST /api/jobs` with inputs whose run key already exists returns the stored run without a job.
- A worker claims the oldest queued job it can run (`maxAccounts`), holds a lease (10 minutes, renewed by every
  progress report), reports progress per town, and completes with the manifest and aggregates; the portal stores
  `runs/<key>/aggregates.json` and indexes the run.
- Killing the worker mid-run leaves the job to expire and requeue; the retry reuses cached towns and produces the same
  run key and byte-identical archive files.
- `POST /api/runs/{key}/details` with a file name makes the worker upload that one file from its archive through a
  signed URL; the portal serves it through a signed download URL; nothing is recomputed.
- Aggregates for a 5,500-home town are under 200 KB; a detail upload of the largest table stays under the blob
  provider's single-object limit (chunk if it does not).
- The Studio's Runs page (milestone 5 widens it) lists jobs with status and progress and opens a completed run's
  aggregates in the existing Year page.

**Build**

- `api/_portal.py`: `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/claim`,
  `POST /api/jobs/{id}/progress|complete|fail`, `GET /api/runs`, `GET /api/runs/{key}`,
  `POST /api/runs/{key}/details`, `GET /api/runs/{key}/files/{name}`, `GET/POST /api/specs`. The claim uses the KV
  `claim` primitive; `complete` validates the manifest (`run-manifest/1.0`) and that its `runKey` equals the job's.
- `utilsim/worker/loop.py`: poll (every 15 s, or at once when a heartbeat response says jobs wait), claim, run
  `export_run` per town (a `concurrent.futures.ProcessPoolExecutor` sized by `--cores`), upload, complete; failures
  report `fail` with the traceback's last line; `detail` jobs upload one file. Town generation for a spec (milestone 6)
  plugs in here; until then jobs name a pack town or a self-describing town reference.
- The run key: keep `utilsim.io.run_bundle.run_key`; the control plane computes the same key in Python from the
  same canonical inputs, so a job created online matches the archive the worker writes. Put the canonicalisation in
  one shared module (`utilsim/io/run_key.py`) imported by both sides; it must not import numpy or the engine.

**Contracts.** `job/1.0` as in the architecture (`kind: run | detail | generate`, `status: queued | claimed |
running | complete | failed`, `lease`, `progress`, `result`, `error`). `run-manifest/1.0` and
`run-aggregates/1.0` exist (RUN_BUNDLES.md); add `uploaded: bool` per file if it is not already there. `detail`
request: `{runKey, file}`; response `{url, expiresAt}`.

**Tests.** `tests/test_portal_jobs.py` (claim exclusivity, lease expiry and requeue, run-key dedupe, progress,
complete validation, scoping), `tests/test_worker_loop.py` (the loop against the in-process control plane and a local
blob folder: a whole job for village, a kill between towns, detail upload), size assertions on aggregates.

**Out of scope.** Comparisons, the Utility board, campaigns.

### Milestone 5: portal mode in the Studio: queue a run, the Runs page, the Utility board, comparisons

**Goal.** From the Year calendar or Configuration, "Run on connected computer" queues a job; the Runs page shows the
queue, the library, progress and results; two runs can be compared; details are requested from the Data tab.

**Done when**

- With a paired computer, the Year page's Inflict panel offers **Run on connected computer** beside **Inflict**
  (the live hosted engine) for pack towns, and only the former for towns above the hosted limit; it creates a job
  from the current episodes, settings, seed and view date and navigates to the Runs page.
- The Runs page (`#/runs`, replacing `runs.html` as the entry, which keeps working as a redirect) shows: queued and
  running jobs with progress ("3 of 10 towns"), the library of completed runs with town, inputs summary, engine
  version and date, **Fork** (opens the Year page with that run's episodes to edit and queue again), **Compare**
  (two runs: the nine trend charts overlaid, KPI deltas, episodes of both marked on the calendar), and **Open in
  local engine** (a deep link to the paired computer's local Studio with the run key).
- The Data tab in portal mode lists the tables from the manifest; a table not yet uploaded shows **Request details**,
  which creates a `detail` job and loads the table when it lands.
- The Workspace in portal mode shows the month-end worklist snapshots read-only.
- The Utility board (`#/utility`) renders from aggregates alone: towns (and, after milestone 6, regions) side by
  side with the summary KPIs, open cases, cost and carry, VEE precision and recall, collections phases; clicking a
  town opens its run. Until milestone 6 the board shows one town per run.
- Phone layout works for the Runs page and the board (the Studio's existing breakpoints).

**Build.** `runs-page.js` (queue, library, fork, compare), `compare.js` (pure functions: align two trends month by
month, deltas, the overlaid chart models, tested in node), `utility-board.js`, `portal.js` gains jobs and runs;
`PortalM2C` in `m2c.js` or a new `portal-m2c.js`: the third client, read-only like `SavedM2C` but reading uploaded
aggregates and requesting details; `focus-ui.js`, `app.js`, `index.html` for the routes and nav.

**Tests.** `compare.test.mjs`, `runs-page.test.mjs`, `utility-board.test.mjs`; a Playwright flow against a fake
control plane (a small Node server in `packages/town-viewer/tests/fixtures/`) covering queue → progress → open →
compare → request details.

**Out of scope.** Multi-town roll-ups (milestone 6), campaigns (7).

### Milestone 6: data first: the utility spec, structure synthesis, layout, roll-ups

**Goal.** A utility of towns is specified in a few dozen lines, generated deterministically on the worker, replayed
as one run with roll-ups per region and utility, and shown on the Utility board; one of its
towns opens in the Studio with a planar road map.

**Done when** (these are DATA_FIRST.md's guidelines as tests)

- `specs/ontario-three-towns.yaml` (one region, three towns of 2,500 AMI, 6,000 AMR and 10,000 mixed homes) validates
  against `utility-spec/1.0`; `uv run utilsim gen-utility specs/ontario-three-towns.yaml --out out/utility` generates
  all three towns in under 3 minutes on 4 cores, the 10,000-home town alone in under 60 s.
- Counts equal the spec at every level (premises per street, streets per district, districts per town); eras and lot
  sizes are coherent within a district; commercial sits on arterials.
- The road graph is planar: no two edges cross except at a node (a test over every generated town).
- Road distance exists between any two premises of a town; straight-line distance everywhere; road kilometres between
  towns from the regional plane.
- A spec-built town is an ordinary snapshot: the meter-to-cash run, the operations day, the tables and the map accept
  it with no special case (reuse the existing test suites parameterised over a spec-built town).
- The worker replays the utility's towns in its process pool and the aggregates carry three levels: utility, region,
  town; the Utility board shows them; the Year page's trend for the utility is the sum across towns.
- Episodes carry a `scope` (`utility | region | town | district | street`); a region-scoped episode applies the
  region's rules (moratorium window, fees); technology blends come from the spec per district and street.
- Towns are already generic (done October 3, 2026, before this milestone): the OpenStreetMap fetcher, the committed
  street extracts and the real-place presets are gone, and every town comes from its settings and seed on the
  synthetic skeleton. Specs build on the generic presets (`village`, `small_town`, `town`, `large_town`, `city`,
  `us_town`); keep it that way (no module may fetch or read a real place's data).
- Town packs (`packs/`, about 24 MB committed and copied into the site by `scripts/build_site.mjs`) are rebuilt from
  the specs, and retired once the hosted Studio no longer needs them: either the worker (milestone 4) serves
  generated towns and archives, or the site build generates the packs from the specs instead of committing them.
  Until one of those exists the packs stay: they are the cache that lets the hosted engine open a 10,000-home town
  inside a serverless request.

**Build.** `utilsim/config/utility.py` (pydantic `UtilitySpec`, `Region`, `TownSpec`, `DistrictSpec`, `StreetSpec`;
`schemas/utility-spec-1.0.schema.json` generated by `uv run utilsim schema --all`), `utilsim/gen/structure.py`
(districts → streets → premises → households → customers → routes and portions, no geometry),
`utilsim/gen/layout.py` (block grids per district sized from the streets, a concession plane tiling districts around
the core, arterials and collectors between them, `planarize` as the check; premises placed along frontage; networks,
terrain and the operations day unchanged), `utilsim/utility.py` (the Utility object: towns, their status, per-town
runs, roll-ups), `utilsim/m2c/rollup.py` (trend summed, KPIs added, tables concatenated with a `town` column,
worklists merged with top-N per town), episode scopes in `utilsim/m2c/run.py` (through the per-premise indexes the
engine already keeps for technology), the `gen-utility` CLI, `GET /api/utility/{id}` on the local API, and the
worker's `generate` job kind. The synthetic skeleton is already the only base; `layout.py` extends it from the spec.

**Contracts.** `utility-spec/1.0` (DATA_FIRST.md "The shape"); `run-aggregates/1.0` gains `levels: {utility,
regions: [...], towns: [...]}`; `episode` gains `scope`.

**Tests.** `tests/test_utility_spec.py` (validation and defaults), `tests/test_structure.py` (counts, coherence,
routes about 450 meters), `tests/test_layout.py` (planarity, distances, frontage placement), the existing engine
suites over a spec-built town, `tests/test_rollup.py` (sums equal the per-town figures), a size test on the
three-level aggregates.

**Out of scope.** Year chaining (7). Shared staffing pools across towns (later engine change).

### Milestone 7: campaigns: month batches, check-ins, the decision log, years

**Goal.** A campaign runs the simulation in batches of at least one month, stops at each boundary with a check-in card,
accepts decisions (episodes, settings, policy) that apply from the next batch, chains Decembers into the next year,
and stays a pure function of its inputs plus its decision log.

**Done when**

- The engine's calendar is a parameter: `year` replaces the 2026 constants (`YEAR`, `YEAR_DAYS`, the business-day
  table, the weather year) and a run has an **opening state** (register values, ledgers and arrears, open cases,
  device ages, consecutive-estimate streaks, arrangements and holds, the moratorium in force). Year two of a chained
  run starts from year one's closing state; a test checks every opening field equals the closing field.
- A campaign on "pause at every batch" produces, per month, the month's aggregates and a check-in card; "pause when a
  watch condition trips" pauses only then; "never pause" runs to the horizon; a 24-hour timeout policy continues
  without an answer.
- A decision made at a check-in appears in the decision log dated to the batch it applies from; replaying the campaign
  from scratch with the same log gives byte-identical archives (determinism test).
- The Year page becomes a strip of years with episodes, decisions and check-ins marked; the trend charts run across
  the strip; the decision log is a page.
- A waiting check-in sends an email with a link to the card (provider behind `api/_notify.py`).

**Build.** Engine: `utilsim/m2c/calendar.py` generalised to any year, `utilsim/m2c/state.py` (closing → opening
state, `opening-state/1.0` serialisable to `store/runs/<key>/state/<year>.json.gz`), chaining in `M2CRun`
(the prior real year replaces the synthetic one in VEE's prior-year tests; the next tariff version takes effect;
the weather year rolls). Worker: `utilsim/worker/campaign.py` (batch loop: replay from the start with the extended
log in the first version; checkpoints later). Control plane: `POST /api/campaigns`, `GET /api/campaigns/{id}`,
`POST /api/campaigns/{id}/decide`, `POST /api/campaigns/{id}/continue`, the card stored with each batch. Studio:
`campaign-composer.js` (spec or town, start, horizon, batch length, pause and timeout policy), `checkin-card.js`,
`decision-log.js`, the Year strip in `year-page.js`.

**Contracts.** `campaign/1.0` as in the architecture; `checkin/1.0`: `{month, headline: {metric: {value, prevMonth,
baseline}}, episodesInForce, tripped: [watch], levers: [{setting, group, current}]}`; `opening-state/1.0`.

**Tests.** `tests/test_year_chaining.py`, `tests/test_campaign.py` (pause policies, watch conditions, timeout, log
determinism), viewer `year-strip.test.mjs`, `checkin-card.test.mjs`.

**Out of scope.** Checkpoint resume (an optimisation; needs the payments and collections pass to run inline day by
day) unless a utility above 50,000 accounts makes replay-from-start too slow at a check-in.

## 4. Rules for every pull request

**Branches and PRs.** One branch per milestone (or per coherent part of one), a PR against `main`, CI green (the
`engine` and `viewer` jobs in `.github/workflows/ci.yml`: `uv run ruff check .`, `uv run pytest -m "not slow"`,
`npm test` in `packages/town-viewer`, `node scripts/viewer_conformance.mjs examples/village-480-seed42`), a Vercel
preview opened on a desktop and a phone, then a merge commit. The PR body says what changed, how it was verified, and
what is out of scope. Do not modify `prototypes/town-lab` (the original prototype, kept as a reference).

**Code.** Python: 3.11, `from __future__ import annotations`, ruff with line length 110 (`pyproject.toml`), pydantic
models for every contract, numpy only inside the engine, no engine imports in `api/_portal.py` or `utilsim/worker/`
beyond `utilsim.io.run_bundle` and the shared run-key module. Viewer: vanilla ES modules in
`packages/town-viewer/dist/`, the existing dense one-statement-per-line style, pure functions exported for tests,
`node:test` tests, no framework, CSS in `studio.css` or a page's own file (`runs.css`). Keep the hosted function
importable without scipy and shapely (`tests/test_hosted_deploy.py`).

**Contracts and versions.** Every payload carries `schemaVersion`. New shapes get a JSON Schema in `schemas/`
(regenerate with `uv run utilsim schema --all`) and a row in `docs/CONTRACT.md`. Bump `GENERATOR_VERSION` in
`utilsim/version.py` whenever any deterministic output can change, then regenerate goldens
(`uv run python scripts/update_goldens.py`) and packs (`uv run utilsim pack`); a test fails while packs are stale.
Settings documentation is generated: `uv run python scripts/gen_config_doc.py` after a config change.

**Security.** Device credentials and pairing codes are stored hashed; codes are single-use and expire in ten
minutes; every control-plane query is scoped to the authenticated account; signed URLs expire; the local API binds
to loopback; no secret in the repository (the release workflow holds the signing key). Treat run inputs from the
browser as untrusted: validate with the pydantic models, cap sizes (`EPISODE_MAX`, action counts, spec sizes).

**Docs to update with each milestone.** The Status column of PORTAL_ARCHITECTURE.md's table; RUN_BUNDLES.md for
anything about archives or the reader; `docs/HANDOFF_ASTRA.md` with a new numbered section when a Studio surface
changes; the docs table in `README.md`; `docs/M2C.md` for engine changes (episode scopes, years).

**Verification you can run locally**

```bash
uv sync --all-extras && npm ci --prefix packages/town-viewer
uv run ruff check . && uv run pytest -m "not slow"          # engine and API
npm test --prefix packages/town-viewer                      # Studio
uv run utilsim serve --port 8010                            # local engine and API
node web/serve.mjs                                          # Studio at http://localhost:5175 (?engine=http://127.0.0.1:8010)
uv run utilsim export-run --town small_town --as-of 2026-12-31 --store out/store   # a saved run for runs.html
```

## 5. Decisions to make in the first week (with recommendations)

| Decision | Recommendation | Why |
|---|---|---|
| Identity provider | Email magic links through a hosted provider, behind `api/_auth.py` | No passwords to store; one function to swap |
| Key-value and blob storage | Vercel KV (or Upstash Redis) and Vercel Blob, behind `api/_kv.py` and `api/_blob.py` | Same platform as the deployment; the interfaces keep it replaceable; local folders for tests |
| Launcher language | Go, one static binary per platform | Small, no runtime, cross-compiles from one CI job |
| Runtime packaging | python-build-standalone plus wheels, zstd tarball per platform, signed manifest | Cached once, verified, versioned beside the engine |
| Signing | Ed25519 (minisign-compatible) for the runtime; platform code signing for the launcher | Simple, offline verification |
| Platforms | macOS arm64 and x64, Windows x64, Linux x64 | Covers the people who will run this |
| Notifications | Email through a hosted provider behind `api/_notify.py` | Needed only from milestone 7 |

Write each decision into PORTAL_ARCHITECTURE.md when made (a short "Decisions" list at the end), so the architecture
stays the single reference.

## 6. Risks and how to see them early

- **Storage limits.** Count KV operations and blob bytes in a test with a 40-town utility before milestone 6; details
  are evictable, aggregates are not.
- **Runtime size and first-run time.** Measure the runtime tarball per platform in milestone 3 and write it into
  RUN_BUNDLES.md; if it passes 300 MB, drop matplotlib and pyarrow from the worker's dependency set.
- **Launcher trust prompts.** Unsigned binaries trigger Gatekeeper and SmartScreen; budget for signing accounts in
  milestone 3's release checklist.
- **Memory on big utilities.** A 5,500-home town's year is about 260 MB (600 MB for the process with its town); forty such towns in a pool of 4 is fine, a pool of 40
  is not. Size the pool by memory, not only cores (`capabilities.memoryGB`).
- **Year chaining touches the engine's arrays.** Milestone 7 generalises constants used everywhere in `utilsim/m2c/`;
  land the calendar parameter first, with the full suite green at `year=2026`, before adding the opening state.
- **Two engines, one key.** The control plane and the worker must compute identical run keys; keep the
  canonicalisation in one module and test it from both sides.

## 7. Checklist for each PR

- [ ] Done-when lines of the milestone that this PR advances are quoted in the PR body with their status.
- [ ] New payloads have `schemaVersion`, a schema in `schemas/`, a row in `docs/CONTRACT.md`.
- [ ] `uv run ruff check .`, `uv run pytest -m "not slow"`, `npm test` pass locally; CI green.
- [ ] `api/index.py` imports without the generation stack; the control plane imports no engine module.
- [ ] Vercel preview checked on desktop and phone for any Studio change.
- [ ] PORTAL_ARCHITECTURE.md status table, RUN_BUNDLES.md, HANDOFF_ASTRA.md and README updated where they apply.
- [ ] No change under `prototypes/town-lab`.
