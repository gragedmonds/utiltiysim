"""Runs Astra's real viewer receiver (packages/town-viewer) on engine exports via scripts/viewer_conformance.mjs."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from utilsim.io.bundle import write_bundle

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
ADAPTER = ROOT / "packages" / "town-viewer" / "dist" / "adapter.js"
pytestmark = pytest.mark.skipif(not NODE or not ADAPTER.exists(), reason="node or the viewer package is unavailable")


def _run(export_dir: Path) -> dict:
    proc = subprocess.run([NODE, str(ROOT / "scripts" / "viewer_conformance.mjs"), str(export_dir)], cwd=ROOT,
                          capture_output=True, text=True, timeout=300)
    report = json.loads(proc.stdout)
    failed = [r for r in report["results"] if not r["ok"]]
    assert proc.returncode == 0 and not failed, failed or proc.stderr
    return report


def test_committed_example_conforms():
    report = _run(ROOT / "examples" / "whitby-480-seed42")
    assert report["passed"] >= 9


def test_fresh_export_conforms(town120, tmp_path):
    write_bundle(town120, tmp_path, geojson=False, tables=False, png=False)
    _run(tmp_path)
