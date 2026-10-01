"""utilsim API. The contract is documented in docs/CONTRACT.md; OpenAPI at /openapi.json."""

from __future__ import annotations

import io
import os
from typing import Any, Literal

import numpy as np
import orjson
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.store import store
from utilsim.config import SCENARIOS, SimConfig, config_schema, list_presets, load_preset
from utilsim.config.presets import deep_merge
from utilsim.io.geojson import LAYERS, layer
from utilsim.io.tables import TABLES, table_rows, to_csv_text, to_parquet_bytes
from utilsim.process.fixtures import VARIANTS, fixture, variant
from utilsim.sim.flows import FlowModel
from utilsim.version import GENERATOR_VERSION, SCHEMA_VERSION

app = FastAPI(title="utilsim", version=GENERATOR_VERSION,
              description="Seeded utility-town engine: geography, networks, customers, simulation, meter-to-cash.")
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


def J(data: Any, status: int = 200) -> Response:
    return Response(orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY), status_code=status,
                    media_type="application/json")


class TownRequest(BaseModel):
    preset: str = Field("whitby_small", description="Base preset.")
    seed: str | None = Field(None, description="Master seed override.")
    houses: int | None = Field(None, ge=20, le=10_000)
    scenario: str | None = None
    overrides: dict[str, Any] | None = Field(None, description="Deep-merged SimConfig overrides.")
    config: dict[str, Any] | None = Field(None, description="A complete SimConfig (wins over preset/overrides).")


def _town(tid: str):
    st = store.status(tid)
    if st == "building":
        raise HTTPException(409, f"town {tid} is still building")
    if st == "failed":
        raise HTTPException(500, store.error(tid))
    town = store.get(tid)
    if town is None:
        raise HTTPException(404, f"unknown town {tid}; POST /api/towns first")
    return town


@app.get("/api/health")
def health():
    return {"status": "ok", "generatorVersion": GENERATOR_VERSION, "schemaVersion": SCHEMA_VERSION}


@app.get("/api/config/schema")
def get_schema():
    return J(config_schema())


@app.get("/api/config/presets")
def get_presets():
    return J({"towns": list_presets(), "scenarios": sorted(SCENARIOS)})


@app.get("/api/config/presets/{name}")
def get_preset(name: str):
    try:
        return J(load_preset(name).model_dump(mode="json"))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/towns")
def create_town(req: TownRequest):
    try:
        if req.config:
            cfg = SimConfig.model_validate(req.config)
        else:
            cfg = load_preset(req.preset, overrides=req.overrides, seed=req.seed, houses=req.houses,
                              scenario=req.scenario)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    tid, status = store.submit(cfg)
    body = {"townId": tid, "status": status}
    if status == "failed":
        body["error"] = store.error(tid)
        return J(body, 422)
    return J(body, 201 if status == "ready" else 202)


@app.get("/api/towns/{tid}")
def get_town(tid: str):
    st = store.status(tid)
    if st in ("building", "failed", "unknown"):
        return J({"townId": tid, "status": st, "error": store.error(tid)}, 404 if st == "unknown" else 200)
    town = _town(tid)
    from utilsim.io.snapshot import town_stats

    minx, miny, maxx, maxy = town.bounds
    return J({"townId": tid, "status": "ready", "generatorVersion": GENERATOR_VERSION, "schemaVersion": SCHEMA_VERSION,
              "seed": town.cfg.seeds.master, "houses": int(town.prem.residential.sum()), "premises": len(town.prem),
              "bounds": {"minX": minx, "maxX": maxx, "minZ": -maxy, "maxZ": -miny},
              "origin": {"lat": town.geo.origin_lat, "lon": town.geo.origin_lon}, "source": town.geo.source,
              "layers": LAYERS, "tables": TABLES, "stats": town_stats(town)})


@app.get("/api/towns/{tid}/snapshot.json")
def get_snapshot(tid: str, profile: Literal["full", "viewer"] = "full"):
    _town(tid)
    return Response(store.snapshot_gz(tid, profile), media_type="application/json",
                    headers={"Content-Encoding": "gzip"})


@app.get("/api/towns/{tid}/layers/{name}.geojson")
def get_layer(tid: str, name: str, crs: Literal["wgs84", "local"] = "wgs84"):
    town = _town(tid)
    if name not in LAYERS:
        raise HTTPException(404, f"unknown layer {name}; available: {LAYERS}")
    return J(layer(town, name, crs))


@app.get("/api/towns/{tid}/network/{utility}")
def get_network(tid: str, utility: Literal["electric", "gas", "water"]):
    town = _town(tid)
    net = town.networks[utility]
    return J({"commodity": utility, "sourceId": net.source_id, "stationId": net.station_id, "unit": net.unit,
              "nodes": {"id": [n.id for n in net.nodes], "kind": [n.kind for n in net.nodes],
                        "x": [round(float(n.xy[0]), 2) for n in net.nodes],
                        "z": [round(float(-n.xy[1]), 2) for n in net.nodes],
                        "parentEdge": [n.parent_edge for n in net.nodes]},
              "edges": {"id": [e.id for e in net.edges], "kind": [e.kind for e in net.edges],
                        "from": [net.nodes[e.a].id for e in net.edges], "to": [net.nodes[e.b].id for e in net.edges],
                        "tier": [e.tier for e in net.edges], "placement": [e.placement for e in net.edges],
                        "sizeMm": [int(e.size_mm) for e in net.edges],
                        "lengthM": [round(e.length, 2) for e in net.edges]},
              "meta": net.meta})


@app.get("/api/towns/{tid}/network/{utility}/trace/{node_id}")
def trace(tid: str, utility: Literal["electric", "gas", "water"], node_id: str, downstream_limit: int = 5000):
    town = _town(tid)
    net = town.networks[utility]
    try:
        v = net.index(node_id)
    except KeyError as exc:
        raise HTTPException(404, f"unknown node {node_id}") from exc
    up = []
    k = v
    while net.nodes[k].parent_edge >= 0:
        e = net.edges[net.nodes[k].parent_edge]
        up.append(e.id)
        k = e.a
    children: dict[int, list[int]] = {}
    for e in net.edges:
        children.setdefault(e.a, []).append(e.b)
    down, stack = [], [v]
    while stack and len(down) < downstream_limit:
        x = stack.pop()
        for c in children.get(x, []):
            down.append(net.nodes[c].id)
            stack.append(c)
    return J({"nodeId": node_id, "upstreamEdgeIds": up[::-1], "downstreamNodeIds": down,
              "downstreamTruncated": len(down) >= downstream_limit})


@app.get("/api/towns/{tid}/premises")
def list_premises(tid: str, mru: str | None = None, bbox: str | None = Query(None, description="minX,minZ,maxX,maxZ"),
                  limit: int = 1000, offset: int = 0):
    snap = store.snapshot(_town(tid).id)
    rows = snap["premises"]
    if mru:
        rows = [p for p in rows if p.get("mruId") == mru]
    if bbox:
        x0, z0, x1, z1 = (float(v) for v in bbox.split(","))
        rows = [p for p in rows if x0 <= p["x"] <= x1 and z0 <= p["z"] <= z1]
    keep = ("id", "address", "x", "z", "premiseType", "occupied", "solar", "services", "mruId", "accountId")
    return J({"total": len(rows), "items": [{k: p.get(k) for k in keep} for p in rows[offset:offset + limit]]})


@app.get("/api/towns/{tid}/premises/{pid}")
def premise_stack(tid: str, pid: str):
    snap = store.snapshot(_town(tid).id)
    prem = next((p for p in snap["premises"] if p["id"] == pid), None)
    if prem is None:
        raise HTTPException(404, f"unknown premise {pid}")
    sps = [s for s in snap["servicePoints"] if s["premiseId"] == pid]
    meter_ids = {s["meterId"] for s in sps}
    inst_ids = {s["installationId"] for s in sps}
    contracts = [c for c in snap["contracts"] if c["installationId"] in inst_ids]
    acc_ids = {c["accountId"] for c in contracts}
    accounts = [a for a in snap["accounts"] if a["id"] in acc_ids]
    bp_ids = {a["businessPartnerId"] for a in accounts}
    return J({"premise": prem, "building": next(b for b in snap["buildings"] if b["id"] == prem["buildingId"]),
              "parcel": next((p for p in snap["parcels"] if p["premiseId"] == pid), None),
              "servicePoints": sps, "installations": [i for i in snap["installations"] if i["id"] in inst_ids],
              "meters": [m for m in snap["meters"] if m["id"] in meter_ids],
              "registers": [r for r in snap["registers"] if r["meterId"] in meter_ids],
              "contracts": contracts, "accounts": accounts,
              "businessPartners": [b for b in snap["businessPartners"] if b["id"] in bp_ids],
              "tariffAssignments": [t for t in snap["tariffAssignments"] if t["contractId"] in
                                    {c["id"] for c in contracts}],
              "reads": [r for r in snap["sampleReads"] if r["premiseId"] == pid],
              "mru": next((m for m in snap["mrus"] if m["id"] == prem.get("mruId")), None)})


_flow_models: dict[str, FlowModel] = {}


@app.get("/api/towns/{tid}/flows")
def flows(tid: str, hour: float = Query(8.0, ge=0, lt=24), scenario: str = "normal", target: str | None = None):
    town = _town(tid)
    if scenario not in SCENARIOS:
        raise HTTPException(422, f"unknown scenario {scenario}")
    fm = _flow_models.get(tid) or _flow_models.setdefault(tid, FlowModel(town))
    res = fm.flows(hour, scenario, target or (town.prem.ids[0] if scenario == "leak" else None))
    return J({"hour": hour, "scenario": scenario, "source": res.source, "unit": res.unit,
              "edgeFlows": {u: np.round(v, 5) for u, v in res.edge_flows.items()},
              "edgeIds": {u: [e.id for e in town.networks[u].edges] for u in town.networks}})


@app.get("/api/towns/{tid}/tables/{name}.{fmt}")
def get_table(tid: str, name: str, fmt: Literal["parquet", "csv", "json"]):
    snap = store.snapshot(_town(tid).id)
    try:
        rows = table_rows(snap, name)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if fmt == "parquet":
        return Response(to_parquet_bytes(rows), media_type="application/vnd.apache.parquet")
    if fmt == "csv":
        return Response(to_csv_text(rows), media_type="text/csv")
    return J(rows)


@app.get("/api/towns/{tid}/render.png")
def get_render(tid: str, services: bool = False):
    from utilsim.io.render_png import render

    town = _town(tid)
    buf = io.BytesIO()
    path = render(town, f"{store_dir(tid)}/render{'-svc' if services else ''}.png", services=services)
    buf.write(path.read_bytes())
    return Response(buf.getvalue(), media_type="image/png")


def store_dir(tid: str) -> str:
    from api.store import CACHE_DIR

    d = CACHE_DIR / tid
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


@app.get("/api/towns/{tid}/fixtures/vee.json")
def vee_fixture(tid: str, include_truth: bool = False):
    snap = store.snapshot(_town(tid).id)
    return J(fixture(snap["sampleReads"], include_truth))


@app.get("/api/towns/{tid}/fixtures/vee/{pid}/{commodity}.json")
def vee_fixture_one(tid: str, pid: str, commodity: Literal["electric", "gas", "water"],
                    variant_name: str = Query("actual", alias="variant"), include_truth: bool = False):
    if variant_name not in VARIANTS:
        raise HTTPException(422, f"variant must be one of {VARIANTS}")
    snap = store.snapshot(_town(tid).id)
    reads = [variant(r, variant_name) for r in snap["sampleReads"]
             if r["premiseId"] == pid and r["commodity"] == commodity]
    if not reads:
        raise HTTPException(404, f"no {commodity} reads for {pid}")
    return J(fixture(reads, include_truth))


_ = deep_merge
