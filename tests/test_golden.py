"""Golden digests per snapshot section. A failure names the first section that changed; if the change is
intentional, bump GENERATOR_VERSION and run `uv run python scripts/update_goldens.py`."""

import importlib.util
import json
from pathlib import Path

import pytest

from utilsim.version import GENERATOR_VERSION

ROOT = Path(__file__).resolve().parents[1]
GOLD = json.loads((ROOT / "tests" / "golden" / "digests.json").read_text())
spec = importlib.util.spec_from_file_location("update_goldens", ROOT / "scripts" / "update_goldens.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_golden_version_matches():
    assert GOLD["generatorVersion"] == GENERATOR_VERSION, "bump goldens together with GENERATOR_VERSION"


@pytest.mark.parametrize("case", sorted(mod.CASES))
def test_golden_digests(case):
    got = mod.digests(*mod.CASES[case])
    want = GOLD["cases"][case]
    changed = [k for k in mod.SECTIONS + ["townId"] if got[k] != want[k]]
    assert not changed, f"{case}: sections changed {changed} (bump GENERATOR_VERSION and update goldens if intended)"
