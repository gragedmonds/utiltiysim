"""Static matplotlib render of a town (for judging the generator; the product look is the 3D viewer)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection, PolyCollection  # noqa: E402

from utilsim.gen.roads.model import PAVEMENT_WIDTH  # noqa: E402

COLORS = {"electric": "#e5a735", "water": "#149faf", "gas": "#a783d8"}
BG, GROUND, ROAD, PARCEL, HOUSE = "#dfe1dc", "#bfc4b5", "#9eaaa6", "#cfd3c6", "#efeee6"


def render(town_or_geo, path: str | Path, *, networks: tuple[str, ...] = ("electric", "water", "gas"),
           services: bool = False, dpi: int = 160, size_in: float = 12.0, title: str | None = None) -> Path:
    geo = getattr(town_or_geo, "geo", town_or_geo)
    town = town_or_geo if hasattr(town_or_geo, "geo") else None
    g = geo.roads.graph
    minx, miny, maxx, maxy = (town.bounds if town is not None else geo.extent)
    aspect = (maxy - miny) / max(maxx - minx, 1)
    fig, ax = plt.subplots(figsize=(size_in, size_in * aspect))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(GROUND)
    span = max(maxx - minx, maxy - miny)
    m_per_pt = span / (size_in * 72)
    if town is not None:
        lots = getattr(town, "lot_polys", None)
        if lots:
            ax.add_collection(PolyCollection(lots, facecolors=PARCEL, edgecolors="#b7bcae", linewidths=0.2))
        feet = getattr(town, "footprints", None)
        if feet:
            ax.add_collection(PolyCollection(feet, facecolors=HOUSE, edgecolors="#8d9187", linewidths=0.25,
                                             zorder=3))
    widths = [PAVEMENT_WIDTH[c] / m_per_pt for c in g.edge_class]
    ax.add_collection(LineCollection(g.geometry, colors=ROAD, linewidths=widths, capstyle="round", zorder=2))
    if town is not None:
        for u in networks:
            net = town.networks.get(u) if hasattr(town, "networks") else None
            if net is None:
                continue
            segs, lw = [], []
            for e in net.edges:
                if e.kind == "service" and not services:
                    continue
                segs.append(e.points)
                lw.append({"supply": 2.2, "trunk": 1.6, "service": 0.25}.get(e.kind, 0.6 + 0.004 * e.size_mm))
            ax.add_collection(LineCollection(segs, colors=COLORS[u], linewidths=lw, alpha=0.9, zorder=4))
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    if title:
        ax.set_title(title, fontsize=10, color="#263c36", family="serif")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return path
