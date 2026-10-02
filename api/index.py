"""Hosted engine: the Vercel Python function behind /api/* (see vercel.json).

Serves operations on the prebuilt town packs (packs/): break assets, dispatch crews, field visits, frames; and
meter-to-cash: a year of reads, VEE decisions, exception work queues and analyst actions. It imports
only the light runtime (numpy, FastAPI); tables and renders stay in the full local API (api/app.py, `uv run utilsim
serve`). It also mounts the generated-town endpoints (api/_towns.py), which load the generation stack only on use:
without scipy and shapely, health says ``capabilities.generate: false`` and ``POST /api/towns`` answers 501.
Dependencies for this function: api/requirements.txt.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api._m2c import router as m2c_router
from api._ops import J, router
from api._towns import health as health_body
from api._towns import router as towns_router
from utilsim.version import GENERATOR_VERSION

app = FastAPI(title="utilsim hosted engine", version=GENERATOR_VERSION,
              description="Operations and meter-to-cash on prebuilt towns: incidents, crews, field visits, state "
                          "frames, reads, VEE and work queues.")
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["*"])
app.include_router(router)
app.include_router(m2c_router)
app.include_router(towns_router)  # POST /api/towns: answers 501 until the function ships the generation stack


@app.get("/api/health")
def health():
    """Status, versions, towns and ``capabilities.generate``: true only when this function can import the generation
    stack (scipy, shapely), tried on request, never at import."""
    body = health_body("hosted")
    return J({**body, "schema": body["schemaVersion"]})
