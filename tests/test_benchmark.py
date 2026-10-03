import time

import pytest

from utilsim.config import load_preset
from utilsim.gen.pipeline import generate
from utilsim.validate import validate_town


@pytest.mark.slow
def test_ten_thousand_homes_within_budget():
    t = time.perf_counter()
    town = generate(load_preset("city"))
    elapsed = time.perf_counter() - t
    assert int(town.prem.residential.sum()) == 10_000
    res = validate_town(town)
    assert res["valid"], res["errors"][:5]
    assert elapsed < 60, f"10k generation took {elapsed:.1f}s"
    assert town.networks["electric"].meta["substations"] >= 2
