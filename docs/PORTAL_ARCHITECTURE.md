# The portal as command centre, processing and storage offline

*Architecture, October 2026. Companion to [DATA_FIRST.md](DATA_FIRST.md) (what gets generated) and [M2C.md](M2C.md)
(what gets replayed).*

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
| `POST /api/jobs` | create a job from inputs; computes the run key; returns the stored run if one exists |
| `GET /api/jobs` · `GET /api/jobs/{id}` | queue and status for the Studio |
| `POST /api/jobs/claim` | a worker takes the next queued job it is able to run (by size, by capability); a lease with a TTL |
| `POST /api/jobs/{id}/progress` · `/complete` · `/fail` | the worker reports; complete carries the manifest and the aggregates |
| `GET /api/runs` · `GET /api/runs/{key}` | the library; a run's manifest and aggregates |
| `POST /api/runs/{key}/upload` · `GET /api/runs/{key}/files/{name}` | signed URLs for optional detail files |
| `GET/POST /api/specs` | utility specs, versioned |

State in a key-value store (jobs, runs index, specs), files in a blob store (aggregates, optional details, specs).
Auth: a token per worker machine, a token per portal user to start with; a login later. The hosted engine
(`api/index.py`) keeps serving the small packs beside this; nothing in the control plane imports the engine.

### Worker (the offline executable)

`utilsim worker --portal https://… --token … --store ~/utilsim [--cores 8] [--max-accounts 200000]`

- Polls, claims, runs. Towns are cached in the store by town id; a utility spec's towns are generated once.
- Replays towns in a process pool; reports progress per town; writes `store/runs/<key>/` (below).
- Computes and uploads the aggregates and the manifest; uploads detail files only for `detail` jobs or when a job asked
  for them up front.
- Leases: a crashed worker's job returns to the queue when its lease expires; the run key makes a retry safe.
- `--serve` also runs the full local API, so the Studio on the same machine opens any stored run live (actions, the
  map, inflicting scenarios with the result in seconds). The portal's "open in local engine" link carries the run key;
  the local engine rebuilds the inputs from it.
- Packaged as one download per platform with Python, the engine and the Studio inside; double-click gives the local
  Studio, the `worker` flag joins the queue.

### Storage

Offline (the worker's store):

```
store/towns/<townId>/snapshot.json.gz, replay-day.json.gz, meta.json
store/runs/<runKey>/manifest.json, inputs.json, aggregates.json, trend.json, scorecard.json,
                    tables/<name>.parquet (or .json.gz pages), worklists/<queue>-<month>.json.gz, premises.json, log.txt
```

Online: `run:<key>` and `job:<id>` records, `runs/<key>/aggregates.json` (tens of kilobytes; a few per town more),
`runs/<key>/details/<file>` on request (capped per run; aggregates are never evicted, details may be), `specs/<id>/<v>`.

Sizing from today's measurements: aggregates 20 to 100 KB per run; worklist snapshots about 1 MB per month per
10,000 accounts; tables 10 to 30 MB per 10,000 accounts compressed; a 100,000-account utility bundle 150 to 300 MB on
disk and about 100 KB online by default.

## Contracts

- `utility-spec/1.0`: [DATA_FIRST.md](DATA_FIRST.md).
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

| Step | What | Size |
|---|---|---|
| 1 | Run bundle and aggregates (`utilsim export-run`); the Studio reads a bundle read-only (Year, Data, Workspace snapshots, scorecard) | about 1 week |
| 2 | Control plane: jobs, runs, specs on KV + Blob, tokens, signed URLs | 2 to 3 days |
| 3 | Worker mode: claim, run, progress, upload, lease, `--serve` | 2 to 3 days |
| 4 | Runs page, "Queue a run" in Year and Configuration, the Utility board, comparisons | 4 to 5 days |
| 5 | Packaged executable per platform | 2 to 3 days |
| 6 | DATA_FIRST step A on the worker; roll-ups per region and utility in the aggregates | as planned |

Step 1 is the foundation: the bundle is both the upload format and the local archive, and a Studio that reads it is
the portal mode.
