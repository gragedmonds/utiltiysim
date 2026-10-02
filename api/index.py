"""Hosted engine: the Vercel Python function behind /api/* (see vercel.json).

Serves operations on the prebuilt town packs (packs/): break assets, dispatch crews, field visits, frames; and
meter-to-cash: a year of reads, VEE decisions, exception work queues and analyst actions. It imports
only the light runtime (numpy, FastAPI); town generation, tables and renders stay in the full local API
(api/app.py, `uv run utilsim serve`). Dependencies for this function: api/requirements.txt.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api._m2c import router as m2c_router
from api._ops import J, pack_index, router
from utilsim.version import GENERATOR_VERSION, SCHEMA_VERSION

app = FastAPI(title="utilsim hosted engine", version=GENERATOR_VERSION,
              description="Operations and meter-to-cash on prebuilt towns: incidents, crews, field visits, state "
                          "frames, reads, VEE and work queues.")
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["*"])
app.include_router(router)
app.include_router(m2c_router)


@app.get("/api/health")
def health():
    return J({"status": "ok", "engine": "hosted", "generatorVersion": GENERATOR_VERSION, "schema": SCHEMA_VERSION,
              "towns": [t["preset"] for t in pack_index()["towns"]]})
