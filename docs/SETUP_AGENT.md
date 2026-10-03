# Conversational simulation setup

Choose **Talk it through** at the start of the wizard or while choosing a scenario. Claude asks short follow-up
questions across location, service area, utility type/scale, metering, normal staffing/workflow, billing and
starting pressures before shaping the experiment. It inspects the engine's current configuration definitions, and proposes a complete setup. The proposal
shows its summary, dated episodes, assumptions, model limits and exact setting changes. **Use this setup** validates
it again and fills in the draft; **Open simulation** opens Year with those settings. Manual starters remain available.

## Voice tweaks in Year

Choose **Talk through a tweak** in the Year header, or choose a calendar day and **Describe a tweak by voice or text**.
Describe changes such as reduced staffing, missed reads, changed automation or a recovery period. The guide asks
about severity, start/end, ramps and recovery, using the live baseline and existing episodes rather than repeating
setup questions. It can propose up to ten new periods per turn, within the engine's forty-episode total.

The review shows the new periods, exact settings, assumptions and analysis date. **Inflict & run to period end**
revalidates the combined timeline, appends the periods and runs through their last end date (December 31 for an
open end). A later current analysis date stays later. Existing town, base settings, seed, analyst actions and
recorded outages are preserved. Failed analysis restores the previous periods/date; retry cannot duplicate them.
A proposal becomes stale if the current base or periods change before applying it; ask for a fresh proposal.
Map incidents and operations-day settings still use their existing controls; voice tweaks here change Year settings.
The conversation remains in memory while the Year guide is open; switching pages cancels its client request.

## Vercel environment

| Variable | Required | Value |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes, for conversation | An Anthropic API key; server-side only |
| `ANTHROPIC_MODEL` | No | Defaults to `claude-sonnet-4-6`; override with an Anthropic Messages API model ID |

Set the key in the Vercel project's **Settings → Environment Variables** for **Preview** and **Production** as
appropriate, then redeploy those environments. This integration calls Anthropic's Messages API directly; it expects
an Anthropic key, not a Vercel management token or an AI Gateway key. Do not prefix the variable with `PUBLIC_` or
`NEXT_PUBLIC_`, or put it in browser code. The key is read at request time by `api/_agent.py`.

Locally, expose the same variable to the process running `utilsim serve`. The static viewer uses the existing
`?engine=http://127.0.0.1:8010` connection. When no key is configured, the conversation panel explains that the guide
is not connected and keeps manual setup available. It never returns the key to the browser.

## Voice and conversation

- Browser speech recognition transcribes into an editable text box. The user starts/stops the microphone and
  reviews the transcript before sending. Typing is always available; speech support depends on browser/device.
- An optional **Read replies aloud** checkbox uses browser speech synthesis. It is off by default.
- Recognition may use the browser vendor's speech service. Only submitted text and relevant configuration go to
  Anthropic; the application does not record or upload audio to its server.
- Draft conversations, proposals and typed text stay in the browser's existing simulation library. Navigating away
  cancels the client request; an interrupted conversation offers a retry on return. Canceling the browser request
  cannot guarantee cancellation of a provider request already accepted by Anthropic.

## Engine boundary

The provider receives a group index, prepared-town catalogue, scenario catalogue and the current draft. Its
`inspect_configuration` tool reads `SimConfig`, M2C and operations schemas, including descriptions, defaults,
bounds, units and not-modelled/deprecated flags. It can inspect every group, up to six per call. Its only other
tool is `respond`, which asks a question or proposes a setup. There are no shell, filesystem or general URL tools.

Before returning a proposal, the server validates:

- A known pack preset; generation-only town overrides, home limits, IANA timezone and all SimConfig dependencies.
  Arbitrary street-source file paths and checksum overrides are refused.
- M2C settings and each day of overlapping/ramped episodes using the engine's shared configuration resolver.
- Operations fields/types/bounds and shift ordering. Grouped overrides are converted to the engine's actual format.
- No unknown, deprecated or not-modelled variables; all dates are in 2026. Homes are not presented as account counts.

Generation changes become a portable town reference, rebuilt by the existing town API when the user opens the
simulation. Validation itself does not generate a town or run an analysis. Base settings, episodes, seed, date and
operations settings pass into the existing per-simulation clients; saved user changes take precedence on reopening.

Geographic context does not automatically recalibrate weather, tariffs, regulations or economics. Prepared towns
and baseline assumptions are Ontario-based. The proposal carries that limitation. Map-day operations settings
also do not imply a full year of automatically simulated storms/outages.

## Request limits and errors

Each chat request accepts at most 48 messages of 4,000 characters, 48,000 characters total, and a bounded draft.
There are at most four provider turns and 4,096 output tokens per turn, within a 50-second overall deadline.
Per warm server instance, the endpoint limits chat to two simultaneous requests and 12 requests per minute per
reported client IP. These are best-effort request controls, **not** a distributed rate limit or project spending cap.
Use the Anthropic account's budget controls for spending limits on this link-access application.

Invalid proposals return validation feedback to Claude for correction. A failed or truncated provider response,
invalid credentials, rate limiting, timeout or exhausted repair loop produces an actionable error and leaves the
saved simulation unchanged. The manual wizard is independent of the provider.

## Verification

Automated API tests use a deterministic provider double and a mocked HTTP transport: schema inspection, probing
questions, invalid-proposal repair, bounds/dependencies, dates, paths, timeout, unknown tools, call limits,
credential isolation and missing-key behavior. Viewer tests cover draft application, handoff to both engine
clients, reopening after edits, and voice detection/fallback.

Browser verification uses deterministic provider replies with the real validation and simulation APIs. A proposed
staff reduction and recovery opened Year at May 12 with two episodes, a 5% AMI missed-read setting and three field
crews. Desktop/phone layouts and the missing-key state were checked. Live Claude response quality and physical
microphone/speech-service behavior require a configured provider key and a supported device; test doubles do not
establish those results.

Additional verification covers the longer baseline interview, separate Year proposal schema, combined/overlapping
period validation, custom-town context, preserved existing state and rollback on both validation/network failures.
Browser checks use a provider double to exercise a multi-exchange baseline interview and a spoken/edited Year tweak;
The same browser run preserved a pre-existing episode and baseline settings, rejected a stale proposal after a
date change, verified the phone panel fits, and canceled the guide on navigation. Live provider question quality
and physical microphone behavior still require the key and a supported device.
