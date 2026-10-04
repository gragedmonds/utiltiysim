# Paired local simulations

Studio supports **500 / 5,000 / 25,000 / 50,000 / 500,000 residential homes**. Sizes above the connected live
engine's limit open the local-run workspace. Commercial sites add accounts. A 500k option does not promise a
500k shared workforce: this release explicitly requires independent districts with independent teams/networks.
Each district has at most 2,000 homes by default. Existing 50k measurements do not establish a measured 500k runtime;
the monitor estimates from completed districts and shows actual phase times.

## One-time setup

1. Open a simulation from the guided setup. Large sizes say **Local computer required**.
2. Download the UtilityStudio launcher from the repository's latest release. Select the matching operating system.
3. Choose a writable storage folder, such as `P:\UtilitySim`. The engine, baselines, archives, temporary downloads,
   jobs and receipts stay under it. The bootstrap preference stores only the selected path in the OS config folder.
4. Start the engine, choose **Connect a computer** in Studio, and enter the eight boxes (`ABCD–2345`) in the runner.
   Codes expire after ten minutes and can be redeemed once. The computer keeps a separate credential for reconnection.
5. Review the independent-district staffing explanation and queue a run. Pairing itself never starts a simulation.

Windows credentials use DPAPI; macOS uses Keychain; Linux uses an owner-readable credential file under the chosen
storage root. Credentials are not part of exported archives. The local API binds to 127.0.0.1, validates the Host
header and requires a per-launch bearer token; hosted Studio communicates through outbound HTTPS polling.

The compiled launcher is small; its versioned engine is a separate first-use download. A Linux development build
measured a **3.1 MB compressed launcher and 135 MB runtime**. Release manifests record each platform's exact sizes.
The launcher checks the pinned digest and Ed25519 signature before extraction, rejects traversal and symlinks,
resumes interrupted downloads, and commits an installed version only after verification. Each launcher pins its
release verification key; the ephemeral release signing key is never stored or published. This is runtime integrity,
not OS publisher signing: Apple notarization and Windows Authenticode certificates are not configured.

Download a newer launcher to update its pinned runtime. Older runtime versions and libraries remain on disk.
To open another library, select its folder before starting. Automated library relocation is not implemented: stop
processing, copy the complete library, then select the destination. Missing drives pause work instead of redirecting
writes to another volume. Start only one runner per library (an OS lock prevents competing processes).

## Jobs, edits and results

- Every submitted job captures an immutable recipe and numbered revision. Concurrent edits get a conflict rather
  than reusing the same revision. Previous results remain readable while the next job processes.
- A paired worker claims a job with a 120-second renewable lease, reports progress every five seconds, and saves a
  local receipt before upload. A stale lease cannot overwrite another worker's result. If two workers eventually
  compute the same recipe, content-addressed district archives can be reused; completion is fenced by the lease.
- Baselines are cached by generation configuration, district seed, map mode and engine build. Staffing/Year scenario
  edits reuse those snapshots; environment changes create different baselines. No database download is needed for a
  newly generated model. A revised year may still replay in full; there is no incremental mid-year checkpoint.
- The worker checkpoints completed districts and retries an interrupted district. Pause waits until the current
  district completes. Restart reopens the active inbox, verifies saved results and resumes. Offline completion saves
  a receipt; reconnect uploads it idempotently. Revocation stops sync and keeps local files.
- Studio receives additive monthly totals, phase timings and references/checksums for district manifests. It does
  not upload all tables. A selected page of an archived table can be requested from the computer holding the result;
  it must be online. Requested pages expire after five minutes. Imported receipts have no attached detail provider.
- The local saved-run reader opens full district folders without an engine or internet connection.

A workspace link contains a high-entropy capability in its URL fragment. Anyone with that link can read its small
results, edit configurations, queue jobs and connect computers. WorkOS/login remain absent. Devices are scoped to
one workspace and cannot read another workspace. Browser-local drafts remain available independently.

## Manual fallback

Without shared storage, **Prepare/Run locally** creates a portable job, marked as awaiting manual processing.
Download it, import it into the local runner, then download the result summary and import it back into Studio.
Both inputs and receipts carry job/revision identities; mismatched or partial results are rejected. The server's
validation endpoints do not need Redis. Full files remain in the runner's `runs/<runKey>` folders.

Advanced CLI equivalents:

```sh
utilsim runner --store "P:/UtilitySim"
utilsim run-job my-job.job.json --store "P:/UtilitySim"
```

The directory must exist. Manual jobs process without internet; importing them into hosted Studio and using Claude
requires a connection. `baselines/`, `batches/`, `runs/`, `results/` and `runner.json` live under the selected root.

## Deployment and release

For automatic pairing/queueing on Vercel, connect **Upstash Redis** and expose:

- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`

The older Vercel integration aliases `KV_REST_API_URL` / `KV_REST_API_TOKEN` are also accepted. Redis uses an atomic
compare-and-swap Lua script for workspace updates; pairing redemption and lease transitions happen in those atomic
updates. Hosted deployment never falls back to an ephemeral filesystem or in-memory queue. If credentials are absent,
`GET /api/portal/status` reports unavailable and Studio offers manual files.

A standalone/local portal uses SQLite transactions at `UTILSIM_PORTAL_DB` (default `out/portal.sqlite3` when not on
Vercel). Keep that database on a persistent volume. This backend supports integration tests and self-hosting; it is
not an ephemeral fallback for Vercel.

The **Local runner packages** workflow builds and smoke-tests Windows x64, Linux x64, macOS arm64 and macOS x64.
PRs produce artifacts only. A successful main CI run triggers release builds; publication requires every platform's
packaged smoke test. The latest GitHub release supplies the download page. The release workflow uses the repository's
normal Actions token with contents write; no runtime signing secret is uploaded or embedded.

Current operational bounds: 100 revisions per workspace; five concurrent five-minute detail requests; metadata
requests up to 2 MB and detail pages up to 500 KB; full data stays local. Rate limits protect workspace creation and
pair-code attempts. This paired-batch workflow uses calendar year 2026 and independent districts. The engine also has shared-workforce,
connected-network and chained-year modes through the existing CLI and live Studio paths; those are not selected by
this first paired-job contract.
