"""Write the Studio's browser demo streets (packages/town-viewer/dist/demo-streets.json) from the small_town preset.

The browser demo (``?town=demo``, and the placeholder town the Studio draws while a pack loads) lays its own
utilities along a street graph read by ``parseStreets`` in ``model.js``. Its streets are the engine's generic small
town streets (room for the demo's 480 homes plus schools, shops and restaurants), written in the same nodes-and-ways
JSON, so nothing in the Studio comes from a real place.

    uv run python scripts/build_demo_streets.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import orjson

from utilsim.config import load_preset
from utilsim.core.geom import unproject
from utilsim.gen.roads.build import build_geography
from utilsim.gen.roads.model import ROAD_TAG_FOR_CLASS
from utilsim.version import GENERATOR_VERSION

OUT = Path(__file__).resolve().parents[1] / "packages" / "town-viewer" / "dist" / "demo-streets.json"


def build(preset: str = "small_town") -> dict:
    cfg = load_preset(preset)
    geo = build_geography(cfg)
    g, names = geo.roads.graph, geo.roads.names
    lat0, lon0 = geo.origin_lat, geo.origin_lon
    nodes: list[dict] = []
    node_id: dict[tuple[float, float], int] = {}

    def nid(x: float, y: float) -> int:
        key = (round(float(x), 2), round(float(y), 2))
        if key not in node_id:
            node_id[key] = len(node_id) + 1
            lat, lon = unproject(key[0], key[1], lat0, lon0)
            nodes.append({"type": "node", "id": node_id[key], "lat": round(float(lat), 7), "lon": round(float(lon), 7)})
        return node_id[key]

    ways = []
    for e in range(g.n_edges):
        pts = np.asarray(g.geometry[e])
        ids = [nid(x, y) for x, y in pts]
        ids = [i for k, i in enumerate(ids) if k == 0 or i != ids[k - 1]]
        if len(ids) < 2:
            continue
        ways.append({"type": "way", "id": e + 1, "nodes": ids,
                     "tags": {"highway": ROAD_TAG_FOR_CLASS[int(g.edge_class[e])], "name": names[e] or ""}})
    return {"version": 1, "source": "utilsim synthetic streets", "label": f"Generic {preset.replace('_', ' ')} streets",
            "preset": preset, "seed": cfg.seeds.master, "generatorVersion": GENERATOR_VERSION,
            "elements": nodes + ways}


def main() -> None:
    doc = build()
    OUT.write_bytes(orjson.dumps(doc) + b"\n")
    print(OUT, sum(e["type"] == "way" for e in doc["elements"]), "ways")


if __name__ == "__main__":
    main()
