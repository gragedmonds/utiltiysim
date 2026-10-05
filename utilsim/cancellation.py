"""Cancellation scoped to one local job/query thread, never a global engine switch."""
from contextlib import contextmanager
from contextvars import ContextVar

_signal = ContextVar('simulation_cancel_signal', default=None)


class SimulationStopped(Exception):
    def __init__(self):
        super().__init__('Simulation stopped. Your setup and previously saved results are safe.')


def check_cancelled():
    signal = _signal.get()
    if signal is not None and signal.is_set():
        raise SimulationStopped()


@contextmanager
def cancellable(signal):
    token = _signal.set(signal)
    try:
        check_cancelled()
        yield
        check_cancelled()
    finally:
        _signal.reset(token)
