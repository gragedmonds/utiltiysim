"""The digital twin over HTTP: the KPI and lever dictionary a form or a conversation needs, and the fit itself.

``POST /api/twin/fit`` replays the calibration town up to ``budget`` times (about 2 seconds each on the village,
8 on the small town, longer under stress), so on the hosted engine (60 seconds a request) use the village and a
budget of about 10; the local app and the command line (``utilsim twin``) have no such limit. The returned
``proposal`` has passed the setup validation that the wizard and the conversational guide use, so the Studio can
open it as it stands; ``validated`` carries its town reference.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api._agent_config import Proposal, validate_proposal
from api._ops import pack_index
from api._towns import MAX_HOUSES
from utilsim.twin import TwinSpec, dictionary, fit

router = APIRouter()


@router.get("/api/twin/dictionary")
def get_twin_dictionary():
    """The twin's vocabulary (``twin-fit/1.0``): KPIs with their engine definitions and the levers that move them,
    the levers with the settings each sets, the known inputs, the calibration towns and the defaults."""
    out = dictionary()
    out["calibrations"] = [{"preset": t["preset"], "homes": t["homes"], "premises": t.get("premises")}
                           for t in pack_index()["towns"]]
    out["defaults"]["homeLimit"] = MAX_HOUSES
    return out


@router.post("/api/twin/fit")
def post_twin_fit(spec: TwinSpec):
    """Fit a twin to the spec: sizing, the levers, target against achieved per KPI, every KPI the twin shows, and a
    setup proposal the Studio opens (validated here; ``validated`` holds its ``townRef``)."""
    try:
        result = fit(spec, home_limit=MAX_HOUSES)
        validated = validate_proposal(Proposal.model_validate(result["proposal"]))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result["validated"] = {k: validated[k] for k in ("townRef", "townId", "townName", "homes")}
    return result
