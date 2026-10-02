"""utilsim command line: gen | render | schema | validate | serve | osm (fetch | add | list)."""

from __future__ import annotations

import json
from pathlib import Path

import orjson
import typer

from utilsim.config import config_schema, list_presets, load_preset

app = typer.Typer(add_completion=False, help="Seeded utility-town engine.")


def _cfg(preset: str, seed: str | None, houses: int | None, config: Path | None, scenario: str | None):
    overrides = json.loads(config.read_text()) if config else None
    return load_preset(preset, overrides=overrides, seed=seed, houses=houses, scenario=scenario)


@app.command()
def gen(preset: str = typer.Option("whitby_small", help="Preset name (see `utilsim presets`)."),
        seed: str = typer.Option(None, help="Master seed override."),
        houses: int = typer.Option(None, help="House count override (20–10,000)."),
        config: Path = typer.Option(None, help="JSON file with config overrides (deep-merged)."),
        scenario: str = typer.Option(None, help="Scenario preset."),
        out: Path = typer.Option(Path("out/town"), help="Output folder."),
        geojson: bool = True, tables: bool = True, png: bool = True):
    """Generate a town and write the export bundle (snapshot, GeoJSON layers, tables, PNG)."""
    from utilsim.gen.pipeline import generate
    from utilsim.io.bundle import write_bundle

    cfg = _cfg(preset, seed, houses, config, scenario)
    town = generate(cfg)
    res = write_bundle(town, out, geojson=geojson, tables=tables, png=png)
    typer.echo(json.dumps({"townId": town.id, **res, "timings": town.timings}, indent=2))


@app.command()
def render(bundle_or_preset: str = typer.Argument("whitby_small"), out: Path = typer.Option(None),
           seed: str = typer.Option(None), houses: int = typer.Option(None), services: bool = False):
    """Render a PNG for a preset (regenerates deterministically)."""
    from utilsim.gen.pipeline import generate
    from utilsim.io.render_png import render as _render

    cfg = _cfg(bundle_or_preset, seed, houses, None, None)
    town = generate(cfg, with_customers=False)
    path = _render(town, out or Path(f"out/{bundle_or_preset}.png"), services=services, title=cfg.name)
    typer.echo(str(path))


@app.command()
def presets():
    """List presets."""
    for p in list_presets():
        typer.echo(f"{p['name']:<16} {p['description']}")


@app.command()
def schema(out: Path = typer.Option(None, help="Write the SimConfig JSON Schema here."),
           all_: bool = typer.Option(False, "--all", help="Regenerate schemas/config.schema.json and openapi.json.")):
    """Print or write the configuration JSON Schema (drives the settings page); --all refreshes generated schemas."""
    if all_:
        from utilsim.io.schemas import write_generated

        for p in write_generated():
            typer.echo(str(p))
        return
    data = orjson.dumps(config_schema(), option=orjson.OPT_INDENT_2)
    if out:
        out.write_bytes(data)
    else:
        typer.echo(data.decode())


@app.command()
def validate(preset: str = "whitby_small", seed: str = typer.Option(None), houses: int = typer.Option(None)):
    """Generate and run the town validator; exits non-zero on failure."""
    from utilsim.gen.pipeline import generate
    from utilsim.validate import validate_town

    town = generate(_cfg(preset, seed, houses, None, None))
    res = validate_town(town)
    typer.echo(json.dumps({k: v for k, v in res.items() if k != "errors"} | {"errors": res["errors"][:20]}, indent=2))
    raise typer.Exit(0 if res["valid"] else 1)


osm_app = typer.Typer(add_completion=False, help="Freeze real places' streets from OpenStreetMap and make presets.")
app.add_typer(osm_app, name="osm")


@osm_app.command("fetch")
def osm_fetch(place: str = typer.Option(..., help='Place to geocode, e.g. "Ayr, Ontario".'),
              radius_m: float = typer.Option(2000.0, help="Half-width of the square fetched around the place."),
              out: Path = typer.Option(None, help="Output file (default data/osm/<place-slug>.json)."),
              name: str = typer.Option(None, help="Preset name (default from the file name)."),
              register: bool = typer.Option(True, help="Register a preset sized to the streets' natural capacity."),
              timezone: str = typer.Option(None, help="IANA timezone for the preset (default America/Toronto)."),
              units: str = typer.Option(None, help="Unit profile for the preset: ontario | us | uk."),
              overwrite: bool = typer.Option(False, help="Replace an existing file/preset."),
              from_file: Path = typer.Option(None, help="Use a saved Overpass answer (see --print-url) instead "
                                                        "of querying Overpass."),
              print_url: bool = typer.Option(False, help="Only print the Overpass download link for this place.")):
    """Geocode (Nominatim), fetch streets (Overpass), write a frozen extract, register a preset."""
    from utilsim.gen.roads.fetch import (
        bbox_around,
        fetch_extract,
        geocode,
        overpass_query,
        overpass_url,
        slugify,
        write_extract,
    )
    from utilsim.gen.sources import DATA_DIR, register_preset

    if print_url:
        p = geocode(place)
        typer.echo(overpass_url(overpass_query(bbox_around(p.lat, p.lon, radius_m))))
        return
    out = out or DATA_DIR / f"{slugify(place)}.json"
    if out.exists() and not overwrite:
        raise typer.BadParameter(f"{out} exists; pass --overwrite to replace it.")
    doc = fetch_extract(place, radius_m, overpass_file=from_file)
    sha = write_extract(doc, out)
    res = {"file": str(out), "sha256": sha, "snapshotDate": doc["snapshot_date"], "place": doc["place"],
           "ways": sum(1 for e in doc["elements"] if e["type"] == "way")}
    if register:
        res["preset"] = register_preset(out, name=name, timezone=timezone, units=units, overwrite=overwrite)
    typer.echo(json.dumps(res, indent=2, ensure_ascii=False))


@osm_app.command("add")
def osm_add(extract: Path = typer.Argument(..., help="OSM API 0.6 / Overpass JSON extract."),
            name: str = typer.Option(None, help="Preset name (default from the file name)."),
            houses: int = typer.Option(None, help="Fixed size instead of the natural capacity."),
            description: str = typer.Option(None),
            timezone: str = typer.Option(None), units: str = typer.Option(None),
            overwrite: bool = typer.Option(False)):
    """Register a preset for an extract already on disk."""
    from utilsim.gen.sources import register_preset

    res = register_preset(extract, name=name, houses=houses, description=description, timezone=timezone,
                          units=units, overwrite=overwrite)
    typer.echo(json.dumps(res, indent=2))


@osm_app.command("list")
def osm_list():
    """Frozen extracts and the presets that use them."""
    from utilsim.gen.sources import list_sources

    for s in list_sources():
        presets = ", ".join(f"{p['preset']} ({p['houses']:,})" for p in s["presets"]) or "-"
        typer.echo(f"{s['file']:<34} {s['snapshotDate'] or '':<11} {s['ways']:>6} ways  {presets}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8010, reload: bool = False):
    """Run the API (FastAPI + uvicorn)."""
    import uvicorn

    uvicorn.run("api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
