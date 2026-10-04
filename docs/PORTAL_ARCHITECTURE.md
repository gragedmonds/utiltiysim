> **Superseded (October 2026).** Utility Studio is now a downloaded app that runs everything on the person's own computer:
> pages, engine and job queue in one process, no pairing, no portal, no hosted sync. Simulations travel between computers
> as codes. See [LOCAL_RUNNER.md](LOCAL_RUNNER.md). This document is kept as the design history of the web-paired portal.

# The portal as command centre, processing and storage offline

*Architecture, October 2026. Companion to [DATA_FIRST.md](DATA_FIRST.md) (what gets generated) and [M2C.md](M2C.md)
(what gets replayed).*

**Implemented:** saved archives, goal-first setup, local-only 25k/50k/500k mode, revisioned jobs,
workspace links, expiring pairing, leased worker execution, baseline reuse, receipt sync, manual files,
small on-demand table pages and cross-platform launcher/release builds. See [LOCAL_RUNNER.md](LOCAL_RUNNER.md)
for the shipped workflow and its exact limits. Automatic hosted sync requires Upstash Redis configuration.
The sections below retain the broader target architecture: automatic library moves, platform publisher signing and comparisons are not implemented here. Newer engine
shared-workforce, connected-network and chained-year paths remain available separately.

## The user flow: open the link, choose or configure, launch, pair

1. **Open the Studio link.** First visit opens the setup wizard; returning visits offer saved simulations. The
   current list is stored in this browser. Shared workspace metadata is a later addition, with no login gate.
   WorkOS and account authentication are explicitly deferred.
2. **Download and open a small launcher.** Choose a storage folder, such as `P:\UtilitySim\`, before the runtime
   download. It starts a local server and opens a minimal pairing/status screen.
   No Python installation, terminal command, copied server URL or hand-managed token is part of the user flow.
3. **Configure online.** Town or utility specifications, seed, settings and scenarios are composed and saved in Sim.
   A configuration can be saved before a computer is connected; it has an immutable revision when submitted for a run.
4. **Connect with an eight-character alphanumeric code.** Sim displays eight separate character boxes, grouped as
   `K7M2-Q9RX` with a dash between the fourth and fifth. The launcher uses the same arrangement, accepts a full-code
   paste and sends the eight characters without the display dash. Pairing links the computer to the workspace; the
   initially selected configuration can be changed afterward without pairing again.
5. **See the connection established.** Sim shows the computer's name, engine readiness and last contact. The local
   screen shows the linked workspace and configuration revision. Initial download or setup appears as **Preparing**;
   **Ready** means the engine is running and the configuration is available locally.
6. **Work from Sim.** Subsequent configuration changes and run requests reach the paired server through the control
   plane. The local engine computes and stores results; Sim receives progress and small result summaries.

The first acceptance milestone stops at **Ready**, with the saved online configuration received by the local server.
Pairing itself does not start a simulation. Job execution, details requests and the campaign flow follow it.

Here, "offline server" means the engine runs on the user's computer. Pairing, new online configuration and result
sync need internet access. Once the runtime and a run's inputs are cached, computation and local saved-result browsing
can continue without it; progress and results sync on reconnection.

### Small launcher, cached engine

The initial executable is a bootstrapper and supervisor: start the local service, accept the pairing code, show its
status, and stop or restart it. The Python runtime, numerical libraries, engine and local Studio assets are a separate,
versioned download cached on first use. Their size is shown during setup. The initial executable can therefore remain
small; a complete first installation still includes the larger engine download. Exact sizes need measurement on the
target platforms.

Later launches use the installed runtime and keep the device link. Updates download and verify a new signed runtime
before switching to it; the previous version and saved bundles remain available if setup fails.

### What the pairing code establishes

The eight characters are a short-lived, single-use pairing code, generated randomly from an alphabet that avoids
ambiguous characters. They are exchanged for a device credential scoped to the issuing workspace and computer; the code
is not reused as the connection password. Pairing attempts are rate-limited and expire after ten minutes.

The server initiates outbound HTTPS requests for pairing, heartbeat, configuration and jobs. The portal needs no
inbound connection to the computer, open router port or public local-server address. The local API binds to loopback;
the hosted portal uses the control plane to communicate with it. Existing direct `?engine=` integration remains a
development option rather than a prerequisite for this flow.

The device credential is kept in the platform credential store. Restarting the launcher reconnects automatically;
Sim can disconnect a computer and revoke its credential. Expired codes can be regenerated. Unpairing stops account
sync without deleting locally stored bundles. Changes to configuration are revisioned, and each run records the exact
revision it uses so a later edit cannot change an in-progress run.

### Storage folder and returning to a model

The runner remembers a user-selected storage root across restarts. Models, downloaded copies, generated data, run
archives, runtime caches and temporary downloads live beneath it. A small bootstrap preference records the path;
credentials remain in the platform credential store. The setup screen shows the path and available space.
On Windows, an existing writable drive such as `P:\UtilitySim\` is supported. If that drive is unavailable, show
**Storage drive unavailable** and pause work that needs it; do not redirect large writes to another disk.

Changing the folder offers **Move existing library** or **Open another library**. Moves run with jobs stopped,
verify copied manifests and checksums before switching the saved root, and retain the source if interrupted. The
selected storage path never becomes part of a model's or run's content identity.

First setup selects storage, installs the runtime and pairs the computer. Returning users start the runner, reconnect
with its stored credential, and select a model from the library. Opening a model loads its configuration and saved
results without replaying it. Switching scenarios creates a new run on the same connected computer when the user
chooses Run; previous runs remain available. Resuming mid-simulation requires future checkpoint support.

People can export or download complete archive copies and import them into their selected local library. A full
download is offered only when all manifest files are available; otherwise offer export from the computer holding
them. Imports verify the complete bundle before publishing it in the library. A fresh computer pairs once for online
work and obtains a copy of the model or regenerates it using the matching engine and inputs. NAS integration and
archive-sharing codes are outside the current product scope; eight-character codes are for device pairing.

## Principles

1. **The portal never computes a run.** It composes inputs, tracks jobs, keeps small results and renders them.
2. **Big data stays where it was made.** Bundles live on the worker's disk; the portal holds aggregates by default and
   details only when asked for.
3. **Everything is content-addressed.** A run is a pure function of the engine version and its inputs (spec or town,
   settings, episodes, actions, seed), so a run key names it anywhere, identical jobs are served from the store, and
   any result can be regenerated.
4. **Pull, not push.** Workers poll the portal and upload over plain HTTPS; nothing reaches into a laptop.
5. **Degrade gracefully.** No worker online means jobs wait and everything already stored still renders; small packs
   can still use the hosted engine live.

## The loop

```
      Studio (browser)                        control plane (Vercel, no engine)              worker (offline)
 ┌──────────────────────┐   compose a job    ┌──────────────────────────────┐   claim/poll   ┌──────────────────────┐
 │ Year · Configuration │ ─────────────────▶ │ jobs · runs · specs (KV)     │ ◀───────────── │ utilsim worker       │
 │ Runs · Utility board │ ◀───────────────── │ aggregates · details (Blob)  │ ─────────────▶ │  generate · replay   │
 │ Data · Workspace     │   status, results  │ signed upload/download URLs  │   progress,    │  bundle · aggregate  │
 └──────────────────────┘                    └──────────────────────────────┘   upload       │  store on disk       │
          │  "open in local engine"                                                          │  serve (local API)   │
          └──────────────────────────────────────────────────────────────────────────────────▶└──────────────────────┘
```

A tweak online is a new job (or the same run key, answered from the store). A job is claimed by a worker, which
generates the towns it does not have, replays the year per town in a process pool, writes the bundle to its store,
computes the aggregates and uploads them (kilobytes), then marks the job complete. The Studio fills in as results land.
Details (a table, a town, a worklist month) are uploaded on request, from the stored bundle, without recomputing.

## Components

### Portal (the static Studio, exists)

Map, Workspace, Data, Year and Configuration as today, plus:

- **Workspace and computers**: link access, launcher download, pairing-code display, connection/readiness status and disconnect.
- **Configuration**: save online before pairing; show which revision a connected computer has received.
- **Runs**: compose a job (utility spec or town, settings, episodes carried over from the Year calendar, seed, the
  outputs wanted), the queue with status and progress, the library of completed runs, fork a run with edits, compare
  two runs.
- **Utility board**: the aggregate level, regions and towns side by side, from the uploaded aggregates alone.

The Studio picks its engine per context: the hosted function for small packs, a local engine when `?engine=` names one,
and *portal mode* (jobs and stored results) for utilities and large towns. In portal mode the Year calendar's Inflict
becomes "Queue a run", the Data tab reads uploaded details or offers "Request details", the Workspace shows worklist
snapshots read-only with "Open in local engine", and the map shows a town only when its pack is uploaded.

### Control plane (a few serverless functions, no engine)

| Call | Does |
|---|---|
| `POST /api/pairings` | logged-in user creates a ten-minute, single-use code for the selected configuration |
| `POST /api/pairings/redeem` | launcher exchanges the code and device identity for a scoped device credential |
| `GET /api/devices` · `DELETE /api/devices/{id}` | account's paired computers and their status; revoke a computer's link |
| `POST /api/devices/heartbeat` | authenticated device reports engine version, capabilities, readiness and received configuration revision |
| `GET /api/device/config` | authenticated device fetches its assigned, revisioned configuration |
| `POST /api/jobs` | create a job from inputs; computes the run key; returns the stored run if one exists |
| `GET /api/jobs` · `GET /api/jobs/{id}` | queue and status for the Studio |
| `POST /api/jobs/claim` | a worker takes the next queued job it is able to run (by size, by capability); a lease with a TTL |
| `POST /api/jobs/{id}/progress` · `/complete` · `/fail` | the worker reports; complete carries the manifest and the aggregates |
| `GET /api/runs` · `GET /api/runs/{key}` | the library; a run's manifest and aggregates |
| `POST /api/runs/{key}/upload` · `GET /api/runs/{key}/files/{name}` | signed URLs for optional detail files |
| `GET/POST /api/specs` | utility specs, versioned |

Planned shared state lives in a key-value store (workspace configurations, pairings, devices, jobs, runs index, specs),
with files in a blob store (aggregates, optional details, specs). Opening the Studio link is enough; account login and
WorkOS are deferred. Device credentials are issued through pairing; no manually copied worker token is needed.
Future shared configuration, job and result access must use the link workspace’s scope. The code's consumption and device registration are atomic, so concurrent redemption
cannot connect two devices with one code. The hosted engine (`api/index.py`) keeps serving the small packs beside this;
nothing in the control plane imports the engine. The shared storage service remains an implementation
choice; these endpoints are proposed contracts, not existing routes.

### Worker (the local engine behind the launcher)

The launcher owns startup and pairing; the worker uses the stored device credential and configuration revisions.
An advanced/development entry point can expose `utilsim worker --portal https://… --store ~/utilsim [--cores 8]
[--max-accounts 200000]`, with credentials resolved from the device store.

- Starts its local API, registers readiness and reports heartbeat/configuration receipt to Sim after pairing.
- Polls, claims, runs. Towns are cached in the store by town id; a utility spec's towns are generated once.
- Replays towns in a process pool; reports progress per town; writes `store/runs/<key>/` (below).
- Computes and uploads the aggregates and the manifest; uploads detail files only for `detail` jobs or when a job asked
  for them up front.
- Leases: a crashed worker's job returns to the queue when its lease expires; the run key makes a retry safe.
- The launcher starts the full local API and serves the local Studio, so the same computer can open any stored run
  live (actions, map and scenarios). The local engine rebuilds that run's inputs from its saved bundle.
- Distributed as a small launcher per platform plus a cached runtime, as described above. Double-click starts the
  local service and pairing/status screen. After first setup it reconnects without another pairing code.

### Storage

Offline (the worker's store):

```
store/towns/<townId>/snapshot.json.gz, replay-day.json.gz, meta.json
store/runs/<runKey>/manifest.json, inputs.json, aggregates.json, trend.json, scorecard.json,
                    tables/<name>.parquet (or .json.gz pages), worklists/<queue>-<month>.json.gz, premises.json, log.txt
```

Online: `run:<key>` and `job:<id>` records, `runs/<key>/aggregates.json` (tens of kilobytes; a few per town more),
`runs/<key>/details/<file>` on request (capped per run; aggregates are never evicted, details may be), `specs/<id>/<v>`.

Measured archive reference: Whitby's 654 accounts and 1,832 registers through December 31, 2026 produce 3.61 MB
of saved files (30.29 MB expanded JSON), including the town snapshot, 26 tables and 12 worklist snapshots. Linear
scaling gives about 55 MB per 10,000-account year, or 110–275 MB compressed for two to five separately archived
years (0.93–2.32 GB expanded). These are projections, not multi-year benchmarks; multi-year execution is still
planned. Additional scenario archives multiply storage, and high-backlog scenarios can differ substantially.
Detailed interval-meter histories and the runtime installation are not included in these archive estimates.
This supersedes the earlier 150–300 MB estimate for a 100,000-account archive.

## Campaigns: month batches with a check-in

A **campaign** is a job that runs the simulation in batches of at least one month and stops at each boundary for the
portal to ask: *this month is done, change anything before the next?* It is how a run spans several years without
either a 36-click chore or a blind three-year replay.

- **Composer.** A campaign names its spec or town, a start month, a horizon (months or years), the batch length (one
  month minimum, which matches the billing cycle and the read portions; a quarter or a year are the other sensible
  sizes), and a pause policy: pause at every batch, pause only when a watch condition trips (open cases above N,
  overdue above $X, estimated reads above Y%, a disconnection), or never pause. A timeout policy says what happens when
  nobody answers (continue after 24 hours, or wait).
- **The check-in.** When a batch ends the worker uploads that month's aggregates plus a check-in card: the month's
  headline figures against the previous month and the baseline, the episodes in force, the watch conditions that
  tripped, and the levers that move those figures (staffing, RPA coverage, VEE tolerances, dunning timings, the
  moratorium). The Runs page shows the card and opens the Year calendar on the next month. A decision is any of: add,
  edit or end episodes from the next batch's first day; change settings; take aggregate-level staffing decisions;
  continue for one batch, for N batches, or to the end of the year; or change the pause policy. Every decision is
  appended to the campaign's **decision log**, dated to the batch it applies from, in the same form as episodes today,
  so the whole campaign stays a pure function of its inputs plus its log and can be replayed anywhere.
- **Continuation.** The worker holds the state at the boundary. In the first version it continues by replaying from
  the start with the extended log (deterministic, and seconds to a few minutes); checkpoints (the run serialised at
  each month end, resumed instead of replayed) are an optimisation for large utilities and need the payments and
  collections pass, which runs after the year today, to run inline day by day.
- **Years.** At a December boundary the worker chains: the closing state (register values, ledgers and arrears, open
  cases, device ages, consecutive-estimate streaks, arrangements and holds, the moratorium in force) becomes the next
  year's opening state, the real prior year replaces the synthetic one in VEE's prior-year tests, the new tariff
  version takes effect, and the weather year rolls. This is DATA_FIRST step E brought forward: the engine's calendar
  generalises from 2026 to any year and the run gains an opening state.
- **The Studio across years.** The Year tab becomes a strip of years, each its twelve months; episodes, decisions and
  check-ins are marked on it; the trend charts run across the strip; the decision log is a page of its own, with who
  changed what and from when.
- **Notification.** A waiting check-in is a notification (email or push) with a link to the card; a campaign on
  "never pause" just reports when it finishes.

Contract: `campaign/1.0` = `{id, inputs (as a job), start, horizonMonths, batchMonths, pause: {policy, watch:
[{metric, op, value}], timeoutHours}, log: [{at: YYYY-MM, decisions: [episode | setting | policy change]}],
batches: [{month, status, aggregatesRef, checkIn}]}`.

## Contracts

- `utility-spec/1.0`: [DATA_FIRST.md](DATA_FIRST.md); `campaign/1.0`: above.
- `job/1.0`: `{id, kind: run | detail | generate, inputs: {spec | town, settings, episodes, actions, seed, asOf, outputs},
  runKey, status: queued | claimed | running | complete | failed, claimedBy, lease, progress: {towns done, of, message},
  result: {manifest, aggregates}, error}`.
- `run-manifest/1.0`: `{runKey, engineVersion, inputs, towns: [{id, name, accounts, registers, replayS}], files:
  [{name, bytes, sha256, uploaded}], aggregates}`.
- `run-aggregates/1.0`: per utility, region and town: the trend (`m2c-trend/1.0` months), the summary KPIs, collections
  phases, the VEE scorecard, cost and carry, reliability; the run's episodes with their scope.
- `detail` requests name a run key, a town and a file; the response is the uploaded file's URL.

The run key is `blake2b(engineVersion | canonical JSON of inputs)`; the engine's existing `simulation_id` is the
per-town form of the same idea.

## Behaviour under failure

- Pairing code expired or already used: show that outcome and allow the logged-in user to issue a new code.
- Runtime download fails: stay in Preparing and offer a retry; a working cached runtime remains usable.
- Device loses internet: show Disconnected/last contact online; local computation and saved results remain usable,
  and workspace sync resumes with the stored credential when connectivity returns.
- Device credential revoked: stop workspace sync; require pairing again to reconnect, retaining local bundles.
- Configuration revision not received or engine incompatible: show the specific readiness state; do not claim a run
  until its exact inputs and required runtime are available.
- No worker online: jobs stay queued, the Runs page shows "waiting for a worker, last seen …", everything stored still
  renders.
- Worker crash mid-run: the lease expires, the job requeues, the retry reuses cached towns.
- Engine versions differ between runs: aggregates carry the version; comparisons across versions are shown with a
  warning, never silently.
- Blob quota: details are evicted oldest first and can be re-requested; aggregates are kept.

## What this changes in the plan

Nothing in the engine or its contracts. The always-on container becomes optional (only for live interactivity on a
big utility from a browser with nothing installed). Sharding (DATA_FIRST step B) becomes the worker's process pool
and the roll-up in the aggregates rather than a server.

The connection experience comes before job queueing and campaigns. Packaging is part of that experience from the
start, with runtime size measured separately from launcher size.

| Step | What | Status |
|---|---|---|
| 1 | Run bundle and aggregates (`utilsim export-run`); the Studio reads a bundle read-only (Year, Data, Workspace snapshots, scorecard) | Implemented |
| 2 | Guided setup, saved simulation metadata, online configuration revisions, eight-character pairing codes and device registry | Browser entry complete; shared metadata and pairing next |
| 3 | Small launcher, selectable storage, cached runtime, local server, reconnect and configuration receipt; Sim shows Ready | Browser entry complete; shared metadata and pairing next |
| 4 | Control-plane jobs/runs/specs and signed detail URLs; worker claim, replay, progress, upload and leases | After connection |
| 5 | "Run on connected computer" in Year and Configuration, Runs queue, Utility board and comparisons | After worker execution |
| 6 | DATA_FIRST step A on the worker; roll-ups per region and utility in the aggregates | as planned |
| 7 | Campaigns: the multi-year calendar and opening state in the engine (DATA_FIRST step E), batches, check-in cards, the decision log, pause and timeout policies, the Year strip across years | After the paired run flow |

Step 1 is the foundation: the bundle is both the upload format and the local archive, and a Studio that reads it is
the portal mode.
