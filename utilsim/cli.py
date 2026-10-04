"""utilsim command line: gen | render | schema | validate | pack | export-run | serve."""

from __future__ import annotations

import json
from pathlib import Path

import orjson
import typer

from utilsim.config import config_schema, list_presets, load_preset
from utilsim.io.pack import DEFAULT_PRESETS

app = typer.Typer(add_completion=False, help="Seeded utility-town engine.")


def _cfg(preset: str, seed: str | None, houses: int | None, config: Path | None, scenario: str | None):
    overrides = json.loads(config.read_text()) if config else None
    return load_preset(preset, overrides=overrides, seed=seed, houses=houses, scenario=scenario)


@app.command()
def gen(preset: str = typer.Option("village", help="Preset name (see `utilsim presets`)."),
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
def render(bundle_or_preset: str = typer.Argument("village"), out: Path = typer.Option(None),
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
def validate(preset: str = "village", seed: str = typer.Option(None), houses: int = typer.Option(None)):
    """Generate and run the town validator; exits non-zero on failure."""
    from utilsim.gen.pipeline import generate
    from utilsim.validate import validate_town

    town = generate(_cfg(preset, seed, houses, None, None))
    res = validate_town(town)
    typer.echo(json.dumps({k: v for k, v in res.items() if k != "errors"} | {"errors": res["errors"][:20]}, indent=2))
    raise typer.Exit(0 if res["valid"] else 1)


@app.command()
def pack(presets: str = typer.Option(",".join(DEFAULT_PRESETS),
                                     help="Comma-separated presets to pack."),
         out: Path = typer.Option(Path("packs"), help="Output folder (served at /packs/).")):
    """Prebuild town packs (snapshot + day replay, gzipped, named by town id) and packs/index.json."""
    from utilsim.io.pack import write_packs

    index = write_packs([p.strip() for p in presets.split(",") if p.strip()], out)
    for t in index["towns"]:
        typer.echo(f"{t['preset']:<14} {t['townId']}  {t['homes']:>6} homes  "
                   f"snapshot {t['files']['snapshot']['bytes'] / 1e6:.1f} MB  replay {t['files']['replay']['bytes'] / 1e6:.1f} MB")


@app.command("export-run")
def export_run_command(
    town: str = typer.Option("small_town", help="Prebuilt pack preset or generated town reference."),
    input_: Path = typer.Option(None, "--input", help="Studio Export run JSON (settings, episodes, actions, outages)."),
    snapshot: Path = typer.Option(None, help="A snapshot.json or snapshot.json.gz instead of a pack town."),
    as_of: str = typer.Option(None, help="Save results through this 2026 date (YYYY-MM-DD)."),
    store: Path = typer.Option(Path("out/store"), help="Archive root; bundles go in runs/<runKey>/."),
):
    """Replay once and archive tables, month-end worklists, trends and scorecard for the offline Studio."""
    import gzip

    from fastapi import HTTPException

    from utilsim.io.run_bundle import export_run

    try:
        request = orjson.loads(input_.read_bytes()) if input_ else {}
        if not isinstance(request, dict):
            raise ValueError("run input must be a JSON object")
        ref = request.get("town") or request.get("townId") or town
        if snapshot:
            raw = snapshot.read_bytes()
            snap = orjson.loads(gzip.decompress(raw) if snapshot.suffix == ".gz" else raw)
            if request.get("townId") and request["townId"] != snap["id"]:
                raise ValueError("the supplied snapshot belongs to a different town than the Studio run")
        else:
            from api import _towns  # noqa: F401 -- registers generated town references
            from api._ops import load_snapshot

            snap = load_snapshot(ref)
            if request.get("townId") and request["townId"] != snap["id"]:
                raise ValueError("the saved Studio run belongs to a different version of this town; supply --snapshot")
        if as_of is not None:
            request["asOf"] = as_of
        directory, manifest, reused = export_run(snap, request, store)
    except HTTPException as exc:
        raise typer.BadParameter(str(exc.detail)) from exc
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps({"runKey": manifest["runKey"], "directory": str(directory),
                          "asOf": manifest["asOf"], "reused": reused,
                          "files": len(manifest["files"]), "bytes": sum(f["bytes"] for f in manifest["files"]),
                          "open": "Open runs.html in the Studio and choose this bundle folder."}, indent=2))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8010, reload: bool = False):
    """Run the API (FastAPI + uvicorn)."""
    import uvicorn

    uvicorn.run("api.app:app", host=host, port=port, reload=reload)


@app.command("batch-run")
def batch_run_command(
    homes: int = typer.Option(..., help="Total residential homes, up to 500,000 (local computer only)."),
    staffing: str = typer.Option(..., help="Must be independent-districts; settings apply to EACH district's team."),
    chunk_size: int = typer.Option(2000, help="Maximum homes per sequential district, 20–5,000."),
    preset: str = typer.Option("small_town"),
    config: Path = typer.Option(None, help="Generation configuration overrides JSON."),
    input_: Path = typer.Option(None, "--input", help="JSON with settings, episodes, seed and asOf."),
    store: Path = typer.Option(Path("out/store"), help="Output drive/folder; completed districts persist here."),
    map_data: bool = typer.Option(False, "--map-data/--no-map-data", help="Include visual map data and initial state; batch analysis omits these by default."),
    max_batches: int = typer.Option(None, help="Pause after this many newly completed districts; rerun to resume."),
):
    """Run independent districts sequentially, archive full results, and resume with a measured ETA."""
    from utilsim.batch import run_batch

    last = [None]

    def report(status):
        # Emit once per district or every ten elapsed seconds; unknown ETA stays unknown.
        marker = (status["completed"], status["status"], status["activeSeconds"] // 10, status.get("stage"))
        if marker != last[0]:
            typer.echo(json.dumps(status))
            last[0] = marker

    try:
        cfg = _cfg(preset, None, None, config, None)
        request = orjson.loads(input_.read_bytes()) if input_ else {}
        directory, job = run_batch(cfg, homes, store, request, chunk_size=chunk_size,
                                   staffing=staffing, map_data=map_data, max_batches=max_batches, on_progress=report)
    except (ValueError, OSError, RuntimeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps({"directory": str(directory), "status": job["status"],
                           "rollup": str(directory / "rollup.json"),
                           "timings": str(directory / "timings.json"),
                           "open": "Open each completed district's runs/<runKey> folder in Studio's saved-run reader."}))


@app.command("runner")
def runner_command(store: Path = typer.Option(..., help="Existing storage folder, e.g. P:/UtilitySim."),
                   port: int = typer.Option(8010)):
    """Open the local runner: pair once, queue jobs in Studio, keep all large files here."""
    from utilsim.worker.server import serve
    serve(store, port)


@app.command("run-job")
def run_job_command(job: Path, store: Path = typer.Option(...)):
    """Process a downloaded job offline and write a small result file for Studio."""
    from utilsim.worker.execute import execute
    result = execute(orjson.loads(job.read_bytes()), store, lambda p: typer.echo(json.dumps(p)))
    typer.echo(str(store / "results" / (result["jobId"] + ".result.json")))


if __name__ == "__main__":
    app()
