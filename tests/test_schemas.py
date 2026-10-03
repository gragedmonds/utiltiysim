"""Published schemas validate real engine output and the generated schemas are current."""

import gzip
from pathlib import Path

import orjson
import pytest

from utilsim.io import schemas
from utilsim.io.snapshot import build_snapshot
from utilsim.process.fixtures import fixture, variant
from utilsim.sim.state import FrameBuilder

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "village-480-seed42"


def _ok(name, doc):
    errs = schemas.errors(name, doc)
    assert not errs, errs


@pytest.mark.parametrize("detail", ["full", "viewer"])
def test_snapshot_validates(town120, synth, detail):
    for t in (town120, synth):
        _ok("utility-town-2.0", build_snapshot(t, detail=detail))


def test_frames_replay_reads_and_fixtures_validate(town120):
    snap = build_snapshot(town120)
    fb = FrameBuilder(town120)
    _ok("utility-replay-1.0", fb.replay("2026-07-15", step_minutes=120))
    for r in snap["sampleReads"][:50]:
        _ok("meter-read-1.1", r)
    reads = [variant(r, v) for r in snap["sampleReads"][:8] for v in ("actual", "stuck", "missing", "spike")]
    _ok("vee-input-fixture-1.1", fixture(reads))
    _ok("vee-input-fixture-1.1", fixture(reads, include_truth=True))
    bad = fixture(reads)
    bad["reads"][0]["truth"] = {"registerValue": 1, "consumption": 1}
    assert schemas.errors("vee-input-fixture-1.1", bad)


def test_committed_example_validates():
    snap = orjson.loads(gzip.decompress((EXAMPLE / "snapshot.json.gz").read_bytes()))
    _ok("utility-town-2.0", snap)
    _ok("utility-replay-1.0", orjson.loads((EXAMPLE / "replay-day.json").read_bytes()))
    for p in EXAMPLE.glob("state-*.json"):
        _ok("utility-state-1.0", orjson.loads(p.read_bytes()))


def test_generated_schemas_are_current():
    for name, doc in schemas.generated().items():
        committed = schemas.load(name)
        assert orjson.dumps(committed, option=orjson.OPT_SORT_KEYS) == orjson.dumps(doc, option=orjson.OPT_SORT_KEYS), \
            f"schemas/{schemas.NAMES[name]} is stale: run `uv run utilsim schema --all`"
