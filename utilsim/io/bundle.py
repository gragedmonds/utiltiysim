"""Write everything a frontend or analyst needs for one town into a folder."""

from __future__ import annotations

import gzip
from pathlib import Path

import orjson

from utilsim.io.geojson import LAYERS, layer
from utilsim.io.render_png import render
from utilsim.io.snapshot import build_snapshot
from utilsim.io.tables import write_tables
from utilsim.process.fixtures import fixture


def write_bundle(town, out: str | Path, *, geojson: bool = True, tables: bool = True, png: bool = True,
                 gzip_snapshot: bool = True) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    snap = build_snapshot(town)
    raw = orjson.dumps(snap)
    files = {}
    if gzip_snapshot:
        p = out / "snapshot.json.gz"
        p.write_bytes(gzip.compress(raw, 6, mtime=0))
    else:
        p = out / "snapshot.json"
        p.write_bytes(raw)
    files["snapshot"] = p.name
    summary = {k: snap[k] for k in ("schemaVersion", "generatorVersion", "id", "seed", "count", "premiseCount",
                                    "bounds", "source", "stats", "validation", "configHash")}
    (out / "town.json").write_bytes(orjson.dumps(summary, option=orjson.OPT_INDENT_2))
    (out / "config.json").write_bytes(orjson.dumps(snap["config"], option=orjson.OPT_INDENT_2))
    (out / "vee-fixture.json").write_bytes(orjson.dumps(fixture(snap["sampleReads"]), option=orjson.OPT_INDENT_2))
    if geojson:
        gdir = out / "geojson"
        gdir.mkdir(exist_ok=True)
        for name in LAYERS:
            (gdir / f"{name}.geojson").write_bytes(orjson.dumps(layer(town, name)))
        files["geojson"] = "geojson/"
    if tables:
        write_tables(snap, out / "tables")
        files["tables"] = "tables/"
    if png:
        render(town, out / "render.png", title=f"{town.cfg.name} · seed {town.cfg.seeds.master} · "
                                              f"{snap['count']} homes")
        files["png"] = "render.png"
    return {"out": str(out), "files": files, "bytes": len(raw)}
