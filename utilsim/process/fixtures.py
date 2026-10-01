"""VEE input fixtures (``vee-input-fixture/1.1``).

Variants match the prototype inspector: ``actual`` (baseline), ``stuck`` (register stopped), ``missing``
(telemetry failure: null register/consumption/readAt, never zero; the expected date stays in scheduledReadAt) and
``spike`` (8× reported consumption). ``truth`` always keeps the physical baseline; it is removed by default so a VEE
engine cannot see the answer, and is included only for scoring (``include_truth``). 1.1 differs from the
prototype's 1.0 in that ``truth`` is optional and reads are ``meter-read/1.1``."""

from __future__ import annotations

import copy

from utilsim.version import VEE_FIXTURE_VERSION

VARIANTS = ("actual", "stuck", "missing", "spike")


def variant(read: dict, kind: str) -> dict:
    if kind not in VARIANTS:
        raise KeyError(f"unknown variant {kind!r}; choose from {VARIANTS}")
    r = copy.deepcopy(read)
    mod = 10 ** int(r.get("registerDigits", 9))
    if kind == "stuck":
        r.update(registerValue=r["previousRegisterValue"], consumption=0.0, reasonCode="SIM_STUCK_REGISTER")
    elif kind == "missing":
        r.update(registerValue=None, consumption=None, readAt=None, readType="missing", readStatus="missing",
                 reasonCode="SIM_TELEMETRY_FAILURE")
    elif kind == "spike":
        c = round(r["consumption"] * 8.0, 3)
        r.update(consumption=c, registerValue=round((r["previousRegisterValue"] + c) % mod, 3),
                 reasonCode="SIM_SPIKE")
    if kind != "actual":
        r["id"] = f"{r['id']}-{kind}"
        r["idempotencyKey"] = f"{r['idempotencyKey']}:{kind}"
    r["fixtureVariant"] = kind
    return r


def strip_truth(read: dict) -> dict:
    return {k: v for k, v in read.items() if k != "truth"}


def fixture(reads: list[dict], include_truth: bool = False) -> dict:
    return {"schemaVersion": VEE_FIXTURE_VERSION, "truthIncluded": bool(include_truth),
            "reads": [r if include_truth else strip_truth(r) for r in reads]}
