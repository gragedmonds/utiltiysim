# Saved-road field travel estimates

The administrator's **Field assignments → Estimate travel** page estimates a
pending downstream-water visit from an explicitly selected saved depot, through
the assigned service's premise access, and back. Preparation, on-site work and
speeds for each road class are explicit, editable assumptions. This is planning
information: it neither reserves workforce time nor changes field execution.

The page works on ordinary and smaller desktop windows. Changing an assumption
hides the old estimate; a late response cannot replace newer edits. Invalid or
unknown assignments cannot leave an old result visible. Suggestions contain the
first 100 assignments; any saved assignment ID can be entered.

## Contract

`field_travel.quote(field_owner, request)` and local administrator
`POST /api/field-travel/quote` accept exactly:

```json
{
  "schemaVersion": "field-travel-quote/1",
  "environmentId": "the saved environment",
  "worldFingerprint": "the saved world fingerprint",
  "assignmentId": "an accepted assignment",
  "depotId": "a saved depot",
  "mobilisationSeconds": 300,
  "workSeconds": 1800,
  "speedsKmh": {"arterial": 60, "collector": 40, "local": 30}
}
```

A ready result includes the field owner, crew, immutable assignment checksum,
world fingerprint, road checksum, selected access points, outbound and return
polylines/times, durations and a deterministic quote identity. Durations are
whole seconds: preparation + outbound + work + return. The existing router's
interpolation margin is retained and each leg rounded up. Speeds must be finite
and within 1–160 km/h. Preparation allows zero; work must be positive. Each may
be at most 86,400 seconds. These limits validate input; they do not promise shift
availability or a feasible booking.

Routing reuses `ops.routing.Router` and the small `OpsTown._roads` construction
helper without constructing the legacy operations simulation. Road identifiers,
classes, junction continuity, positive lengths, coordinates and fractional access
are checked. Missing, ambiguous, malformed or disconnected saved roads return
`status: unavailable` with a reason and no duration/quote ID. There is no
straight-line fallback, invented depot, or snapping of invalid access fractions.
Unknown assignments and invalid request identities raise validation errors.

Only pending `repair-water-leak` assignments are supported initially. The estimate
does not inspect whether a leak exists or disclose fault/consumption truth. A
previously committed physical visit awaiting field recovery returns unavailable;
quoting cannot create a duplicate visit or itself perform recovery. No database
schema, assignment, message or physical event changes during quotation.

## Shared workforce follow-up

An estimate is not a booking or an execution authorization. The next managed
adapter must retain the complete quote, bind the existing runtime job/resource,
reserve the full interval with `synth_runtime`, and validate the matching active
reservation at execution. Skills, weekday availability, daily capacity, complete
shift fit and UTC/DST calendar handling remain independent constraints. It must
prevent races with local cruise and define next-boundary physical effects rather
than retroactively rewriting a completed day. No second queue or scheduler is
introduced here. Enterprise cancellation/rework and water-main phase identities
still require the existing owner agreement.

## Validation

`tests/test_world_field_travel.py` verifies real saved-town routing, both-direction
times, speed changes, restart stability, both owner stores unchanged, invalid and
disconnected geometry, request rejection, HTTP boundaries and physical-commit
recovery. `scripts/check_world_field_travel.py` drives the actual desktop page in
a fresh 570-property world at 1440px and 960px, changes work assumptions, reloads,
rejects an unknown assignment, and verifies exact before/after database hashes.
It also delays a quote response while editing its assumptions and verifies that
the stale response cannot restore the hidden result.
It writes screenshots and `result.json` in a newly created output directory:

```powershell
python scripts/check_world_field_travel.py --engine-python .venv/Scripts/python.exe --out out/field-travel-acceptance
```

Run it with a Python containing Playwright; `--engine-python` selects the engine
environment. The temporary server is terminated after verification. Source town
packs and existing worlds remain untouched.

## Continuation acceptance, 9 October 2026

The `greg/utilitysim-continuation` branch combines this increment with guided
setup on the current world engine. All 24 travel checks and the generated-town
setup/repair/report/restart scenario pass. The 570-premise browser check reports
no browser errors at 1440px and 960px, suppresses the deliberately stale response,
and preserves exact hashes of both owner databases. Evidence is written to
`out/continuation-travel-final/result.json`; it is local acceptance evidence,
not proof of enterprise delivery or scheduled workforce execution.
The combined release also passes all 1,060 non-slow Python tests, 301 viewer
tests, 11 viewer conformance checks and Ruff. No paid CI or cloud build was used.
