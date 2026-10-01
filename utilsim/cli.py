"""utilsim command line: gen | render | schema | validate | serve."""

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
def schema(out: Path = typer.Option(None, help="Write the SimConfig JSON Schema here.")):
    """Print or write the configuration JSON Schema (drives the settings page)."""
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


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8010, reload: bool = False):
    """Run the API (FastAPI + uvicorn)."""
    import uvicorn

    uvicorn.run("api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
