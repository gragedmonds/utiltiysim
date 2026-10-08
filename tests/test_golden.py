"""Golden digests for portable snapshot sections.

Exact premises/parcels geometry hashes were retired on 2026-10-08 at the product
owner's request: numeric geometry differences across platforms made them an
unreliable release check. Functional geometry and same-environment determinism
tests remain. Other intentional section changes still require versioned fixtures.
"""

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
    sections = [k for k in mod.SECTIONS if k not in ("premises", "parcels")] + ["townId"]
    changed = [k for k in sections if got[k] != want[k]]
    assert not changed, f"{case}: sections changed {changed} (bump GENERATOR_VERSION and update goldens if intended)"
