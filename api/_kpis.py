"""The KPI catalogue over HTTP: what Utility Studio can watch (GET) and a run's figures (POST)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import Field

from api._m2c import J, RunRequest, run_for
from api._ops import load_snapshot
from utilsim.m2c.kpis import KPI_IDS, catalogue, measure

router = APIRouter()


@router.get('/api/dependencies')
def get_dependencies():
    """The offline variable dependency map. No town generation or simulation is required."""
    from utilsim.config.dependencies import dependency_graph

    return J(dependency_graph())


class KpiRequest(RunRequest):
    kpis: list[str] | None = Field(None, max_length=100, description="Figures to compute (default: every figure).")


@router.get("/api/m2c/kpis")
def get_kpis(town: str | None = None):
    """``m2c-kpis/2.0``: every figure with its family, unit, definition, the settings and scenarios that move it,
    where it shows, and the threshold settings it counts with (their values from ``town``'s config, else the
    defaults)."""
    cfg = None
    if town:
        try:
            from api._m2c import _town

            cfg = _town(town).cfg
        except HTTPException:
            raise
        except Exception as exc:  # a town the engine cannot build
            raise HTTPException(422, str(exc)[:500]) from exc
    return J(catalogue(cfg))


@router.post("/api/m2c/kpis")
def post_kpis(req: KpiRequest):
    """A run's figures year to date at ``asOf`` (``null`` where nothing can be counted yet), with the thresholds in
    force: a request like any meter-to-cash view, plus ``kpis`` to restrict the figures."""
    unknown = sorted(set(req.kpis or []) - KPI_IDS)
    if unknown:
        raise HTTPException(422, f"unknown KPI {unknown[0]!r}; GET /api/m2c/kpis lists them")
    run = run_for(RunRequest.model_validate(req.model_dump(exclude={"kpis"})))
    return J(measure(run, req.asOf, req.kpis))


_: Any = load_snapshot  # the engine API's town sources are registered by api._ops at import
