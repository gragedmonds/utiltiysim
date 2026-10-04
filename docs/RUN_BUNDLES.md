# Saved runs and the offline Studio

The first implementation of [PORTAL_ARCHITECTURE.md](PORTAL_ARCHITECTURE.md): replay on a local machine, keep a
content-addressed archive, and inspect saved results without an engine. The **Runs** link in the live Studio opens
`runs.html`, a separate entry point that boots without loading a map, town pack, or engine API.

## Export

From a checkout with the Python dependencies installed (`uv sync --all-extras`):

```bash
uv run utilsim export-run --town small_town --as-of 2026-12-31 --store out/store
```

The command prints the run key, bundle directory, date, file count and compressed size. The directory is
`out/store/runs/<runKey>/`. Repeating an export verifies and reuses that directory without replaying. A corrupt
existing archive causes an error; move it aside before exporting again. Failed exports leave no completed bundle.

To carry a run from the Studio, use its Worklists **Export run** button (the `viewer-m2c-run/1.0` inputs), then:

```bash
uv run utilsim export-run --input your-run.json --store out/store
```

This preserves the run seed, settings, episodes, actions, interruptions and view date. `--as-of` overrides the
saved view date. For a generated or modified town, supply its matching snapshot:

```bash
uv run utilsim export-run --input your-run.json --snapshot snapshot.json.gz --store out/store
```

The town identity is checked: a run from a different town or a stale pack requires its original snapshot. Prebuilt
packs and saved snapshots need no network access, and nothing in the engine fetches outside data.

## Read

With Three.js already vendored (`npm ci --prefix packages/town-viewer` during setup), start the local Studio:

```bash
node web/serve.mjs
```

Open `http://localhost:5175/runs.html` and **Open run folder**. Select the individual `<runKey>` folder containing
`manifest.json`, not the whole store. The browser reads the selected files locally; it does not upload them or call
the engine. After the page loads, this path also works with browser networking disabled. A local HTTP server serves
the Studio's JavaScript and CSS; opening the HTML directly with `file://` is not supported.

Alternatively, serve the archive directory beside the Studio:

```bash
UTILSIM_RUN_STORE=out/store node web/serve.mjs
```

Open `http://localhost:5175/runs.html?run=/runs/<runKey>/`, or paste a bundle folder URL into **Open stored run**.
Any static HTTPS host can serve the same folder; a different origin must allow CORS. Files are fetched lazily and
checked against their SHA-256 and byte length before they are decoded. Missing and damaged details produce a visible
error. **Verify all files** checks the entire archive, including the saved snapshot.

The views are:

- **Runs**: identity, seed and inputs download, summary KPIs, export date and integrity check.
- **Year**: the existing nine trend charts and calendar with the saved episodes; scenario editing is disabled.
- **Data**: all 26 complete tables at the export date, filters, search, sort, columns, paging and filtered CSV.
- **Workspace**: all open cases at each month end through the export date, plus the export date if it is mid-month;
  queue and text filters, paging and the saved case row. No actions or live record drill-downs.
- **VEE scorecard**: the engine's saved scorecard against simulation truth.

Tables have one saved date. The month-end worklist selector does not change their date or fabricate intermediate
results. More dates require another export. The browser may print an integer-valued numeric CSV cell as `0` rather
than Python's `0.0`; its value, selection and order are the same.

## Archive contract

`run-manifest/1.0` includes `runKey`, `engineVersion`, `engineBuild`, canonical `inputs`, `simulationId`, `asOf`,
`towns`, `files: [{name, bytes, sha256, uploaded}]`, `tableDates`, `worklistDates`, `aggregates` and `readOnly`.
`engineBuild` hashes the packaged engine and run-validation sources plus the numpy, pydantic and orjson versions.
The run key is BLAKE2b-256 of the build identifier, a NUL separator and sorted-key JSON of the inputs. Inputs include
the snapshot's SHA-256, effective settings and seed, ordered episodes/actions/interruptions and export date. Aliases
and omitted settings defaults therefore do not create different keys for the same inputs. A different build or
snapshot cannot silently reuse an old result. There are no timestamps or output-directory paths in the identity.
Generation timing measurements are omitted from the saved snapshot so rebuilding the same town on another machine
does not change its identity.

```
store/runs/<runKey>/
  manifest.json                 # written last, directory published atomically
  inputs.json
  aggregates.json               # run-aggregates/1.0; small summary, trend, scorecard, episodes
  trend.json
  scorecard.json
  snapshot.json.gz              # matching town for reproducibility and later live use
  tables/catalog.json
  tables/<table>.json.gz        # run-table/1.0; columns, search indexes, facets, all saved rows
  summaries/<date>.json         # compact engine summary at each snapshot date
  worklists/<date>.json.gz      # run-worklist/1.0; all open case rows at that date
```

Daily and per-premise arrays are excluded from the online aggregate payload. Details remain separate compressed
files. The initial browser reader limits each compressed or expanded file to 256 MiB and holds a small detail cache;
it still loads a whole requested table. Large utility shards will need paged detail files or Parquet-backed local
queries. The exporter currently handles one town and the engine's 2026 calendar.

## Following milestones

The planned runner will expose a **Storage folder** selector and remember paths such as `P:\UtilitySim\` for models,
archives, downloads and runtime caches. The current CLI already supports an explicit location, for example
`utilsim export-run --town ayr --as-of 2026-12-31 --store "P:\UtilitySim"` on Windows. The runner's folder picker,
library migration and unavailable-drive handling are still to be built. Archive identities are independent of paths.

The product uses downloadable archive copies and local libraries, with no NAS integration required. Opening an old
archive reads its saved results; switching scenarios uses the existing device connection and creates a new run.
Pairing screens will use eight individual boxes with a central dash, such as `K7M2-Q9RX`; the dash is display-only.

This implements architecture step 1. The next milestone is **log in to Sim → download and open the small launcher →
configure online → pair with an eight-character alphanumeric code → see the local engine Ready**. See
[the connection flow](PORTAL_ARCHITECTURE.md#the-user-flow-login-launch-pair). The launcher downloads and caches the
larger runtime on first use; pairing and online sync need internet access, while cached computation stays local.

Login, pairing and launcher distribution are planned, not implemented by `export-run`. The control-plane queue,
worker polling/leases/uploads, run comparisons, utility/region roll-ups, data-first synthesis and multi-year campaigns
follow that connection milestone.
The existing hosted and local live engine routes continue to work alongside the saved reader.

Validation includes Python engine-to-archive comparisons for every table and saved worklist date, archive reuse
without replay, corruption and interrupted-write checks, a Node reader comparison against Python filtering/sorting
and CSV, browser folder import with networking disabled, and desktop/phone navigation.


## Sequential district batches

The local CLI can run up to 50,000 residential homes as independent districts, one process at a time.
Each completed district becomes a full verified run bundle. Memory is released before the next district.
This mode explicitly requires independent teams and networks: analysts/agents are **per district**, and
per-1,000 crew settings scale within each district. It is not a shared utility-wide queue or connected city.
Districts inherit the same environment and temperature seed; their geography, customers and incident seeds differ.

```sh
uv run utilsim batch-run --homes 50000 --chunk-size 2000 --staffing independent-districts --store "P:/UtilitySim"
```

Use `--homes 50000` for 25 districts at 2,000 homes each. Optional `--config` supplies generation overrides;
`--input` accepts a JSON object containing `settings`, `episodes`, `seed` and `asOf`. Town-specific actions
and interruptions cannot be copied between districts. The engine still models calendar year 2026 only.
Use smaller chunks to reduce peak memory. Their size affects network boundaries and per-district staffing,
so comparisons must keep the same chunk size; chunking is part of the model, not only a performance setting.

Progress reports completed/total districts, homes, elapsed time and remaining ETA. ETA stays unknown until
one batch finishes, then uses measured time per home including generation, replay and archive writing.
It is an estimate, not a percentage of internal engine work. A slow batch reports an overrun.
Each update also names the active stage and its elapsed time. Completed phase times cover roads, land use,
buildings, each network, customers, snapshot preparation, annual reads/VEE/billing replay, annual analysis,
each exported table (including compression/writing), month-end views and integrity verification.

Batch exports omit visual map data by default: building/parcel/park/district polygons, display terrain and
initial power/pressure frame. Roads and network assets remain because outages, meter coverage and field
maintenance depend on them. This does not skip those simulations. `--map-data` restores a map-capable
snapshot; changing this option creates a different job. Analysis-only snapshots open in the saved-run
reader, and the map importer explains why they cannot be displayed as maps.

A same-seed 2,000-home comparison measured 20.0 s with map data and 19.0 s without (single local sample,
including child startup and one-second polling). Map-free worker phases: generation 4.59 s, snapshot
0.91 s, annual replay 3.06 s, analysis 1.71 s, and archive preparation/writing/verification 7.69 s.
The full snapshot phase took 1.28 s. Archive size fell from 12.47 to 12.09 MB; all 60 analysis output files
matched after excluding the archive identity. Map removal is a modest saving; table exports dominate.
These timings vary with hardware, configuration and background load.

`--max-batches 2` pauses after two new districts. Run the same command again (without that limit) to resume.
Identical configuration, engine build and chunk size reuse verified completed archives. A changed build or
configuration creates a different job. An interrupted in-flight district is retried; completed ones are kept.
An OS lock prevents two processes writing the same job simultaneously and releases on process exit.

Outputs under the chosen store:

- `batches/<jobKey>/job.json`: exact inputs, district identities, archive references, timings and status.
- `batches/<jobKey>/timings.json`: per-stage totals, completed district wall time and finalization time.
  Phase timings are disjoint; process startup, parent polling and resumed-archive validation are additional.
- `batches/<jobKey>/district-NNNN.progress.json`: current worker phase and completed phase timings,
  replaced atomically while running. Timings stay outside deterministic analysis archives.
- `batches/<jobKey>/rollup.json`: completed districts' additive monthly billing and case totals, clearly
  marked partial until all districts finish. It never averages percentages or invents shared staffing results.
- `runs/<runKey>/`: each district's existing full archive, openable in Studio's saved-run folder reader.

Record IDs are local to a district. Cross-district references must use `(districtId, recordId)`.
The first release is a local CLI path; the hosted wizard still enforces its single-town generation limit.
Verification included a 5,000-home, five-district pause/resume run and a full 50,000-home run in 25 districts
of 2,000 homes. The latter took 505 seconds and wrote 313 MB of archives (61,104 accounts, 164,985 registers);
monthly totals were checked against all district files. Reported peak child-process RSS was 744 MiB. These
are measurements from one development environment, not guaranteed estimates for other hardware or settings.
Batch runs are capped at 50,000 homes.

### Shared utility-wide resources

A fully shared utility requires a daily coordinator: district workers produce reads and candidate work;
the coordinator allocates analyst, contact and field capacity once across all eligible work; districts then
apply the assigned outcomes before advancing the day. Independent annual replay cannot reproduce this by
summing results. Resume checkpoints must include queues, balances, device state and deterministic ordering.
Connected electric/water/gas simulations additionally need boundary conditions between network partitions.
Full map detail should load only for a selected district, while the utility view pages archived records.
