"""Render a north-up planning overview and evidence for road/density review."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/civic-atlas-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/civic-atlas-cache")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.patches import Polygon as PlotPolygon
from shapely.geometry import LineString, Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from utilsim.world.map_view import WorldMap  # noqa: E402
from utilsim.world.store import World  # noqa: E402


def shape(points):
    return Polygon([(p["x"], -p["z"]) for p in points])


def review(snapshot, output):
    output.mkdir(parents=True, exist_ok=True)
    homes = [p for p in snapshot["premises"] if p["premiseType"] == "residential"]
    population = sum(p.get("occupants", 0) for p in homes if p.get("occupied"))
    premises = {p["id"]: p for p in snapshot["premises"]}
    parcels = [shape(p["polygon"]) for p in snapshot["parcels"]]
    parks = [shape(p["polygon"]) for p in snapshot["parks"]]
    envelope = unary_union([*parcels, *parks]).convex_hull
    graph = nx.Graph()
    road_length = 0
    internal_length = 0
    frontage = Counter(p["roadId"] for p in snapshot["premises"])
    for road in snapshot["roads"]:
        graph.add_edge(road["a"], road["b"])
        line = LineString([(p["x"], -p["z"]) for p in road["points"]])
        road_length += line.length
        internal_length += line.intersection(envelope).length
    metrics = {
        "townId": snapshot["id"], "homes": len(homes), "residents": population,
        "premises": len(premises), "parks": len(parks),
        "developedEnvelopeKm2": round(envelope.area / 1e6, 4),
        "residentsPerEnvelopeKm2": round(population / (envelope.area / 1e6)),
        "homesPerEnvelopeHectare": round(len(homes) / (envelope.area / 1e4), 2),
        "allRoadKm": round(road_length / 1000, 3),
        "roadKmInsideEnvelope": round(internal_length / 1000, 3),
        "roadMetresPerHomeInsideEnvelope": round(internal_length / len(homes), 1),
        "roadComponents": nx.number_connected_components(graph),
        "junctionsDegree3Plus": sum(d >= 3 for _, d in graph.degree()),
        "roadEndsIncludingTownExits": sum(d == 1 for _, d in graph.degree()),
        "roadSegmentsWithoutAddressedPremises": [r["id"] for r in snapshot["roads"] if not frontage[r["id"]]],
        "densityDefinition": "Residents in occupied residential premises / convex hull of saved parcels and parks. Not total map bounds or a municipal density claim.",
    }
    (output / "town-review.json").write_text(json.dumps(metrics, indent=2) + "\n")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(18, 10), facecolor="#f7f7f0")
    fig.subplots_adjust(left=.025, right=.975, top=.83, bottom=.16, wspace=.04)
    fig.text(.03, .955, "BROOKFIELD  /  FULL-TOWN REVIEW", fontsize=25, color="#14384a", weight="bold")
    fig.text(.03, .918, "North-up aerial plan from saved geometry · authored fictional town · not satellite imagery", fontsize=12, color="#58706b")
    fig.text(.03, .87, f"{len(homes)} homes   ·   {population} residents   ·   {len(parks)} parks   ·   {internal_length / 1000:.2f} km of roads inside the developed envelope", fontsize=14, color="#14384a")
    bounds = snapshot["bounds"]
    ground = LinearSegmentedColormap.from_list("ground", ["#a7b68e", "#d2dcc0"])
    density = plt.get_cmap("YlOrRd")
    norm = Normalize(0, max(p.get("occupants", 0) for p in homes))
    kinds = {"residential": "#f2ecda", "commercial": "#b97b62", "community": "#567887", "utility": "#637079", "industrial": "#637079"}
    for index, ax in enumerate(axes):
        terrain = snapshot["terrain"]
        values = np.array(terrain["values"]).reshape(terrain["rows"], terrain["cols"])
        extent = [terrain["originX"], terrain["originX"] + (terrain["cols"] - 1) * terrain["cellSizeM"],
                  -(terrain["originZ"] + (terrain["rows"] - 1) * terrain["cellSizeM"]), -terrain["originZ"]]
        ax.imshow(values, extent=extent, origin="upper", cmap=ground, alpha=.7)
        for water in snapshot.get("waterBodies", []):
            ax.add_patch(PlotPolygon(list(shape(water["polygon"]).exterior.coords), facecolor="#55919d", edgecolor="#e2d6b4", linewidth=2))
        for park in parks:
            ax.add_patch(PlotPolygon(list(park.exterior.coords), facecolor="#719463", edgecolor="#5a7b51", linewidth=.8))
        for record, parcel in zip(snapshot["parcels"], parcels):
            p = premises[record["premiseId"]]
            color = density(norm(p.get("occupants", 0) if p.get("occupied") else 0)) if index and p["premiseType"] == "residential" else "#cfdbb7"
            ax.add_patch(PlotPolygon(list(parcel.exterior.coords), facecolor=color, edgecolor="#8da17b", linewidth=.25, alpha=.9))
        for road in snapshot["roads"]:
            line = LineString([(p["x"], -p["z"]) for p in road["points"]])
            pavement = road.get("pavementWidthM", 8)
            right_of_way = road.get("rowWidthM", pavement + 4)
            for width, color, level in [(right_of_way, "#f1eee2", 4), (pavement, "#8e9898", 5)]:
                ribbon = line.buffer(width / 2, cap_style="flat", join_style="round")
                ax.add_patch(PlotPolygon(list(ribbon.exterior.coords), facecolor=color, edgecolor="none", zorder=level))
        for building in snapshot["buildings"]:
            p = premises[building["premiseIds"][0]]
            polygon = shape(building["footprint"]["polygon"])
            category = "community" if p["buildingType"] == "school" else p["premiseType"]
            ax.add_patch(PlotPolygon(list(polygon.exterior.coords), facecolor=kinds.get(category, "#637079"), edgecolor="#536259", linewidth=.35, zorder=6, alpha=.75 if index else 1))
        for facility in snapshot.get("facilities", []):
            if facility.get("premiseId"):
                continue
            pad = shape(facility["polygon"])
            ax.add_patch(PlotPolygon(list(pad.exterior.coords), facecolor="#acb3aa", edgecolor="#506b70", linewidth=.7, zorder=6))
            if facility["kind"] == "elevated_tank":
                ax.scatter([facility["x"]], [-facility["z"]], s=42, facecolor="#fbfaf2", edgecolor="#426674", zorder=8)
                if not index:
                    ax.text(facility["x"], -facility["z"] + 15, "Water tower", fontsize=7, ha="center", color="#14384a", zorder=9)
        ax.plot(*envelope.exterior.xy, color="#204b52", linewidth=1.3, linestyle=(0, (5, 4)), zorder=7)
        if not index:
            seen = set()
            for road in sorted(snapshot["roads"], key=lambda r: -r["lengthM"]):
                if road["name"] in seen:
                    continue
                seen.add(road["name"])
                line = LineString([(p["x"], -p["z"]) for p in road["points"]])
                mid = line.interpolate(.5, normalized=True)
                ax.text(mid.x, mid.y + 7, road["name"], fontsize=6.5, color="#203d40", ha="center", zorder=8,
                        bbox={"facecolor": "#f7f7f0", "alpha": .78, "edgecolor": "none", "pad": 1})
            for park in snapshot.get("atlasDesign", {}).get("parks", []):
                center = shape(park["polygon"]).centroid
                ax.text(center.x, center.y, park["name"], color="#f9fff0", fontsize=8, ha="center", weight="bold", zorder=9)
        ax.set(xlim=(bounds["minX"] - 15, bounds["maxX"] + 15), ylim=(-bounds["maxZ"] - 15, -bounds["minZ"] + 15), aspect="equal")
        ax.axis("off")
        ax.set_title("Streets, building footprints & land use" if not index else "Resident count per residential parcel", loc="left", color="#14384a", fontsize=13, pad=12)
        ax.annotate("N", xy=(.95, .95), xytext=(.95, .86), xycoords="axes fraction", ha="center", color="#14384a", arrowprops={"arrowstyle": "-|>", "color": "#14384a"})
    fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=density), ax=axes[1], orientation="horizontal", fraction=.03, pad=.01, shrink=.45, label="Residents in each occupied household (0 includes vacant)")
    axes[0].legend(handles=[Patch(color=v, label=k.title()) for k, v in kinds.items() if k != "industrial"], loc="lower left", framealpha=.92, fontsize=8)
    fig.text(.03, .10, f"Developed envelope: {metrics['developedEnvelopeKm2']:.3f} km²  |  {metrics['residentsPerEnvelopeKm2']:,} residents/km²  |  {metrics['homesPerEnvelopeHectare']:.2f} homes/ha  |  {metrics['roadMetresPerHomeInsideEnvelope']:.1f} road metres/home", fontsize=12, color="#14384a")
    fig.text(.03, .064, "Dashed line = convex hull of saved parcels and parks. Through-road extensions are shown but excluded from internal road density.\nReview aid, not a realism score: vacant block interiors, frontage continuity, junctions, crossings, and scale still require visual judgment.", fontsize=10, color="#58706b", linespacing=1.5)
    fig.savefig(output / "town-overview.png", dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("out/civic-atlas/review"))
    args = parser.parse_args()
    review(WorldMap(World(args.store / "world.sqlite")).snapshot(), args.output)
