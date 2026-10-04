"""Flat tables (parquet/CSV) for analysts and downstream engines."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import orjson

TABLES = ["premises", "buildings", "accounts", "businessPartners", "servicePoints", "meters", "registers",
          "installations", "contracts", "tariffAssignments", "tariffs", "mrus", "readSchedules", "sampleReads",
          "electric_nodes", "electric_edges", "gas_nodes", "gas_edges", "water_nodes", "water_edges", "equipment"]


def _flat(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if k in ("points", "polygon", "path", "sequence", "premiseIds"):
            continue
        if isinstance(v, dict):
            for kk, vv in v.items():
                out[f"{k}.{kk}"] = vv if not isinstance(vv, (dict, list)) else orjson.dumps(vv).decode()
        elif isinstance(v, list):
            out[k] = orjson.dumps(v).decode()
        else:
            out[k] = v
    return out


def table_rows(snap: dict, name: str) -> list[dict]:
    if name not in TABLES:
        raise KeyError(f"unknown table {name!r}; available: {TABLES}")
    if "_" in name and name.split("_")[0] in ("electric", "gas", "water"):
        u, part = name.split("_")
        return [_flat(r) for r in snap["networks"][u][part]]
    if name == "equipment":
        return [_flat({"commodity": u, **q}) for u, n in snap["networks"].items() for q in n["equipment"]]
    if name == "buildings":
        return [_flat({**b, "footprint": {k: v for k, v in b["footprint"].items() if k != "polygon"}})
                for b in snap["buildings"]]
    return [_flat(r) for r in snap[name]]


def _normalise(rows: list[dict]) -> list[dict]:
    keys: list[str] = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    return [{k: r.get(k) for k in keys} for r in rows]


def to_parquet_bytes(rows: list[dict]) -> bytes:
    # pyarrow is imported here, not at module import: the packaged app leaves it out (scripts/build_runner.py) and
    # serves the engine API without parquet tables.
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = _normalise(rows)
    buf = io.BytesIO()
    if not rows:
        pq.write_table(pa.table({}), buf)
        return buf.getvalue()
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    for k, v in cols.items():
        types = {type(x) for x in v if x is not None}
        if len(types) > 1:
            cols[k] = [None if x is None else str(x) for x in v]
    pq.write_table(pa.table(cols), buf, compression="zstd")
    return buf.getvalue()


def to_csv_text(rows: list[dict]) -> str:
    rows = _normalise(rows)
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


def write_tables(snap: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in TABLES:
        p = out_dir / f"{name}.parquet"
        p.write_bytes(to_parquet_bytes(table_rows(snap, name)))
        paths.append(p)
    return paths
