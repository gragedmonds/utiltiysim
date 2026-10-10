"""Civic Atlas prototype: a local UI over a dedicated, real durable world."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ConfigDict  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from utilsim.config import load_preset  # noqa: E402
from utilsim.gen.pipeline import generate  # noqa: E402
from utilsim.io.snapshot import build_snapshot  # noqa: E402
from utilsim.world import cruise  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402
from utilsim.world.store import World  # noqa: E402


class AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    townId: str
    expectedThrough: date


def prepare_world(store: Path, houses: int, seed: str, *, showcase: bool = False,
                  reference: bool = False) -> World:
    store.mkdir(parents=True, exist_ok=True)
    world = World(store / "world.sqlite")
    if not world.status().get("environmentId"):
        if reference:
            from reference_world import build_reference_snapshot

            snapshot = build_reference_snapshot(seed=seed)
            world.initialize(snapshot, "Brookfield", start="2026-01-01")
            world.advance("2026-01-08")
            return world
        town_config = {"street_pattern": "neighborhoods", "arterial_spacing_m": 900,
                       "collector_block_m": 350, "terrain_relief_m": 6}
        if showcase:
            town_config.update({"collector_block_m": 250, "terrain_relief_m": 12,
                                "park_share": .18, "commercial_strip_m": 180,
                                "commercial_share_arterial": .08, "commercial_share_collector": .06,
                                "commercial_share_local": .01, "commercial_cluster_m": 70,
                                "industrial_lots": 1, "houses_per_school": 500})
        cfg = load_preset("village", seed=seed, houses=houses, overrides={"town": town_config})
        snapshot = build_snapshot(generate(cfg), embed_state=False)
        world.initialize(snapshot, "Brookfield", start="2026-01-01")
        world.advance("2026-01-08")
    return world


def create_app(world: World) -> FastAPI:
    app = FastAPI(title="Civic Atlas prototype", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    view = WorldMap(world)
    gate = threading.Lock()
    snapshot = view.snapshot()

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Use the local Civic Atlas application."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site changes are refused."}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "Expected application/json."}, status_code=415)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def state():
        with world.db() as db:
            status = world._status(db)
            meta = world.metadata(db)
            days = [dict(row) for row in db.execute(
                "SELECT d.day,d.temperature,COUNT(o.id) observations FROM days d "
                "LEFT JOIN observations o ON o.day=d.day GROUP BY d.day ORDER BY d.day DESC LIMIT 30")]
            events = [dict(row) for row in db.execute(
                "SELECT sequence,day,type,subject FROM events ORDER BY sequence DESC LIMIT 40")]
            conditions = {row["condition"]: row["n"] for row in db.execute(
                "SELECT condition,COUNT(*) n FROM assets GROUP BY condition")}
            managed = db.execute("SELECT 1 FROM observation_delivery_configuration").fetchone() is not None
        controller = cruise.inspect(world)
        owner = "shared-runtime" if managed else "local-cruise" if cruise.owns_clock(controller) else "manual"
        return {**status, "daysHistory": days, "events": events, "conditions": conditions,
                "managedDelivery": managed, "settings": meta["settings"],
                "lastCompletedDay": days[0]["day"] if days else None,
                "clockOwner": owner, "manualAdvanceAllowed": owner == "manual",
                "clockReason": controller["unavailableReason"] or (
                    "Local cruise owns the clock. Cancel it in its control screen before advancing here."
                    if owner == "local-cruise" else None)}

    @app.get("/atlas/api/bootstrap")
    def bootstrap():
        return {"snapshot": snapshot, "state": state()}

    @app.get("/atlas/api/state")
    def get_state():
        return state()

    @app.get("/atlas/api/premises/{identity}")
    def premise(identity: str):
        try:
            return view.premise(identity)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/atlas/api/advance")
    def advance(body: AdvanceRequest):
        with gate:
            try:
                with cruise.manual_control(world):
                    current = view.status()
                    if current["townId"] != body.townId:
                        raise HTTPException(409, "The selected world changed. Refresh before continuing.")
                    if current["managedDelivery"]:
                        raise HTTPException(409, "A shared runtime owns this world's clock.")
                    expected = body.expectedThrough.isoformat()
                    target = (body.expectedThrough + timedelta(days=1)).isoformat()
                    if current["through"] == expected:
                        world.advance(target)
                    elif current["through"] != target:
                        raise HTTPException(409, "This view is out of date. Refresh before advancing.")
            except (ValueError, OverflowError, cruise.BusyError) as exc:
                raise HTTPException(409, str(exc)) from exc
            # Repeating a request after a lost reply never advances a second day.
            return state()

    app.mount("/viewer", StaticFiles(directory=ROOT / "packages/town-viewer/dist"), name="viewer")
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="atlas")
    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8040)
    parser.add_argument("--store", type=Path, default=ROOT / "out/civic-atlas")
    parser.add_argument("--houses", type=int, choices=(80, 180, 320, 480))
    parser.add_argument("--seed")
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("--showcase", action="store_true",
                          help="Use more park land, a school at 320+ homes, and a shorter commercial core.")
    profiles.add_argument("--reference", action="store_true",
                          help="Use the curated Civic Atlas reference town with real simulation records.")
    args = parser.parse_args()
    if args.reference and args.houses is not None:
        parser.error("The curated reference town has a fixed layout; --houses applies to generated profiles.")
    default_seed = "CIVIC-ATLAS-REFERENCE-01" if args.reference else (
        "CIVIC-ATLAS-PARK-01" if args.showcase else "CIVIC-ATLAS-01")
    world = prepare_world(args.store, args.houses or (320 if args.showcase else 180),
                          args.seed or default_seed, showcase=args.showcase, reference=args.reference)
    print(json.dumps({"world": world.status(), "note": "Existing stores are resumed, never regenerated."}), flush=True)
    uvicorn.run(create_app(world), host="127.0.0.1", port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
