import pytest

from utilsim.config import load_preset
from utilsim.gen.pipeline import generate


@pytest.fixture(scope="session")
def town480():
    return generate(load_preset("whitby_small", seed="WHITBY-042", houses=480))


@pytest.fixture(scope="session")
def town120():
    return generate(load_preset("whitby_small", seed="T120", houses=120))


@pytest.fixture(scope="session")
def synth():
    return generate(load_preset("ontario_small", houses=600))
