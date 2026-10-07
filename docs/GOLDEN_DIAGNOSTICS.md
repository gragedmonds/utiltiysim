# Golden geometry diagnosis

The two Windows golden failures remain open. No expected digest, generator version,
generation algorithm or assertion has been changed to make them pass. The diagnostic
tool produces evidence for a correction; it is not that correction.

## Evidence collected on 7 October 2026

At source revision `ec33a4383f549cdc7e21131552d661eca90aa52c`, Windows x86-64,
Python 3.11.17, NumPy 2.4.6, SciPy 1.17.1, Shapely 2.1.2 and GEOS 3.13.1:

| Case / section | Expected digest | Windows digest |
| --- | --- | --- |
| village-120-T120 / parcels | bb75ed274afbb8ee | 81a196fa73eb9c20 |
| village-600-42 / premises | ec0894c6cbc2296c | d982994a5688c95e |
| village-600-42 / parcels | c4f070b79a120bd2 | 69befb56ec9d87ed |

Every other checked section and both town IDs match. Two fresh generations of each
case on this Windows runtime match each other exactly. This is repeatable drift
against the reference, not observed run-to-run randomness.
The same two failures also reproduce in an untouched archive of `7287d93`, the
commit that originally recorded these version-0.10.0 golden hashes, using this
Windows runtime. Later world-runtime changes are therefore not necessary to
produce the mismatch.

The existing [Linux CI run](https://github.com/gragedmonds/utiltiysim/actions/runs/37669502497)
at `e8c5f3707e19bface153149f21921515f61be9f0` passed 525 tests. Its log lists the
same Python, NumPy, SciPy and Shapely versions. This is evidence of a platform
difference, but the log alone does not establish the underlying numeric cause or
the Linux GEOS build. No new cloud job was requested for this diagnosis.

The committed 480-home snapshot provides record-level reference data absent from
the golden hash file. Regenerating from its embedded configuration on Windows:

- Roads, buildings and facilities are identical.
- Eight premises differ only in `lotAreaM2`, each by 0.1 square metres.
- 58 parcels differ: 39 polygon rings have identical vertices in a different
  cyclic order; 19 have different vertices. Maximum measured Hausdorff distance
  for those 19 is about 0.010305 metres; maximum symmetric-difference area is
  about 0.0878 square metres.
- For example, `LOT-P-00021` acquires an intermediate vertex and its reported
  area changes from 483.9 to 484.0 square metres.

The comparison also reports configuration metadata differences: validating that
older embedded configuration adds today's defaults for field work, contact rules,
KPIs and the enabled-service list. Original supplied values are retained. This is
reported separately, not silently removed from the comparison. The untouched
golden-commit reproduction above provides the independent historical check.

These measurements do **not** turn differences into passes. Ring normalization
alone cannot account for all the mismatches. Nor is a platform-specific expected
hash sufficient evidence that the generator is portable.

## Read-only capture and comparison

Run from the repository root in the locked environment. Choose new output files;
both commands refuse to overwrite an existing file, including a reference.

```sh
python -m scripts.diagnose_goldens capture --case village-120-T120 --output out-120.json
python -m scripts.diagnose_goldens capture --case village-600-42 --output out-600.json
python -m scripts.diagnose_goldens capture --case example-480 --output out-example.json
python -m scripts.diagnose_goldens compare examples/village-480-seed42/snapshot.json.gz out-example.json --output comparison-example.json
python -m scripts.diagnose_goldens compare linux-120.json out-120.json --output comparison-platforms.json
```

`linux-120.json` is a separately captured file from the same case and source on
Linux; it is not supplied by this change. Captures include exact golden sections,
configuration, generator version, installed library/GEOS versions, source revision,
tracked-change flag and lockfile SHA-256. They exclude machine names and paths.
Capture exits 1 if its existing golden digests differ, while still saving evidence.
The example case has no golden hash entry; compare it to the committed snapshot.

Comparison accepts captures or ordinary full JSON/gzip snapshots. It reports
metadata changes, section digests, missing/new identities, record order, changed
fields and geometry measurements. Detail is limited to 25 changed records per
section by default (`--detail-limit 0..1000`); aggregate counts remain complete.
Duplicate identities are errors. Signed zero and numeric representation changes
remain exact differences. A comparison exits 1 for **any** exact difference,
including ring order alone; exit 0 means all inspected metadata and sections match.
This checks the same sections as the golden suite, not every snapshot field.

## Next corrective step

Capture the two golden cases on another platform at the same source/lockfile and
compare their individual parcel records with Windows. Then isolate the first
divergent intermediate operation in lot clipping/de-overlap and precision snapping
(`utilsim/gen/parcels.py`) before choosing a correction. An intentional geometry
change requires a justified generator-version change and reviewed fixtures across
platforms. Preserve original reference files and demonstrate whether physical and
customer identities are affected. Do not add tolerances or rewrite goldens merely
to obtain green tests.

The diagnostic regressions cover exact versus ring-only changes, true boundary
movement, complete aggregate counts with bounded details, record membership/order,
duplicate IDs and protection against overwritten evidence. The world progression
and enterprise integration can continue independently of this open baseline issue.

Local validation for this diagnostic increment: six diagnostic regressions passed;
the full non-slow engine suite finished with 529 passed and the same two golden
failures (719.41 seconds, four workers). All 291 viewer tests, 11 export-conformance
checks and repository lint passed. CLI checks confirmed identical captures exit 0,
changed captures exit nonzero with evidence retained, and existing output files are
rejected. This does not constitute a green complete engine acceptance run.
