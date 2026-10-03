import pytest

from utilsim.config import load_preset
from utilsim.gen.pipeline import generate


@pytest.fixture(scope="session")
def town480():
    return generate(load_preset("village", seed="TOWN-042", houses=480))


@pytest.fixture(scope="session")
def town120():
    return generate(load_preset("village", seed="T120", houses=120))


@pytest.fixture(scope="session")
def synth():
    return generate(load_preset("village", seed="42", houses=600))
