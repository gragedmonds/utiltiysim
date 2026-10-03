"""Regenerate docs/CONFIG.md from the SimConfig JSON Schema (run: uv run python scripts/gen_config_doc.py)."""

from pathlib import Path

from utilsim.config import config_schema

HEADER = """# Configuration reference

Every assumption in the simulator is a field of `SimConfig` (see `utilsim/config/model.py`). The settings page is
generated from `GET /api/config/schema`, which carries these UI hints on every field:

| Hint | Meaning |
|---|---|
| `x-unit` | Unit shown next to the input (stored values are SI) |
| `x-advanced` | Hide behind an "Advanced" toggle |
| `x-effects` | What changes downstream when this value changes (show as a tooltip / "affects" chips) |
| `x-group`, `x-order` | Group cards and their order on the page |
| `x-applies` (on a group) | `town`: part of the town id, so changing it generates a new town (new `townId`, revisions and ids); `run`: applies to a simulation run of the same town (no regeneration) |
| `x-run-setting` | This town value is the default of an operations run setting with that key (`GET /api/sim/settings/schema?town=`): change it per run there without generating a new town |
| `x-reach` | Where the setting's effect reaches: `year` (the meter-to-cash year, same town), `town` (the customers, usage, routes or prices the year replays; a new town), `shape` (map geometry; the year moves only because homes are drawn again), `operations` (the operations day on the map), `display` (labels, units, clocks, default dates) |
| `x-impact` | How the setting changes the results, in a sentence or two (the first line of its (i) popover) |
| `x-status`, `x-status-reason` | `not-modelled`: the engine does not use the field yet (show it disabled with the reason); `deprecated`: another setting replaces it, named in `x-deprecated` |

Presets (`GET /api/config/presets`) are YAML overrides deep-merged on the defaults. The town id is a hash of the
generation-relevant config plus the generator version, so every combination is reproducible. The run-scoped groups
(`x-applies: run`: scenario, process, anomalies, reading, VEE, billing) are the meter-to-cash run's settings
(`GET /api/m2c/settings`). Crews, the day shift, the gas response target, incident rates and storm days stay in the
town groups but are only defaults: the operations run settings (`x-run-setting`) override them per run.

Each table below has a **Reaches** column and the setting's **How it changes the results** text
(`utilsim/config/impact.py`). Measurements behind them: [CONFIG_IMPACT.md](CONFIG_IMPACT.md). Settings removed in
generator 0.9.1 because nothing used them or they only labelled the map: `housing.semi_share`,
`electric.transmission_kv`, `electric.severe_turn_deg`, `ami.battery_life_years`, `ami.comm_fail_rate`,
`operations.drive_by_radius_m`, `operations.walker_meters_per_hour`, `process.sequences`, `scenario.tick_minutes`.
Configs that still carry them load; the keys are ignored.

## Knock-on chains worth demonstrating

| Change | What you should see |
|---|---|
| `housing.solar_rate` ↑ | More export registers and net-metering contracts; reverse flow on services, transformers and eventually the whole town at noon |
| `housing.ev_rate` ↑ | Higher individual peaks → larger transformers, more transformer groups, heavier feeders, more feeders |
| `housing.electric_heat_rate` ↑ or `gas.all_electric_district_share` ↑ | Fewer gas services and smaller gas mains; higher electric design load |
| `electric.overhead_before_year` ↑ | More overhead districts → poles, pole-mount transformers, lightning exposure (M3 outages) |
| `gas.scheme` = `mp` | No low-pressure core, no district regulators, ¾" services with regulators everywhere |
| `water.fire_flow_residential_lps` ↑ | Larger distribution mains everywhere (fire flow governs sizing) |
| `water.cast_iron_before_year` ↑ | More unlined cast-iron mains along the older streets: more head loss (`hw_c_old`) and twice the background main-break rate |
| `incidents.*` / `weather.storm_days_per_year` ↑ (or the run's random-incident settings) | More background incidents on operations days: crews busier, more interruptions, more outage-explained estimates in meter-to-cash |
| `town.terrain_relief_m` ↑ | Second pressure zone, second elevated tank, PRV/booster equipment at zone boundaries |
| `ami.ami_route_share` ↓ | More AMR van and manual walker routes; more estimated reads (M3) |
| `customers_billing.mru_target_meters` ↓ | More, smaller meter reading routes |
| `town.houses` ↑ | A wider town whose edge reaches newer eras; a second substation; more feeders, routes and accounts |
| `town.commercial_share_arterial` / `_collector` / `_local` ↑ | More storefronts on that class of street, clustered at main-road intersections and towards downtown; homes pushed outward (still exactly `houses`); more 3φ pads, commercial accounts and closer hydrant spacing |
| A preset (`village`, `small_town`, `town`, `large_town`, `city`, `us_town`) | A generic town of that size; every street comes from the settings and the seed, never from a real place |

"""


def main() -> None:
    s = config_schema()
    defs = s["$defs"]
    groups = sorted(((k, v) for k, v in defs.items() if v.get("x-group")), key=lambda kv: kv[1].get("x-order", 99))
    lines = [HEADER]
    for name, d in groups:
        lines.append(f"## {d.get('title', name)}\n\n{d.get('description', '')}\n")
        lines.append("| Field | Reaches | Default | Range | Unit | Description | How it changes the results |")
        lines.append("|---|---|---|---|---|---|---|")
        for f, p in d["properties"].items():
            default = p.get("default")
            if isinstance(default, dict):
                default = ", ".join(f"{k}={v}" for k, v in default.items() if not isinstance(v, (dict, list)))
            rng = ""
            if "minimum" in p or "maximum" in p:
                rng = f"{p.get('minimum', '')}–{p.get('maximum', '')}"
            desc = p.get("description", "").replace("|", "/")
            if p.get("x-effects"):
                desc += f" *Affects: {', '.join(p['x-effects'])}.*"
            if p.get("x-run-setting"):
                desc += f" *Default of the operations run setting `{p['x-run-setting']}`.*"
            if p.get("x-status") == "not-modelled":
                desc += f" **Not modelled yet:** {p['x-status-reason']}"
            elif p.get("x-status") == "deprecated":
                desc += f" **Deprecated** (use `{p['x-deprecated']}`): {p['x-status-reason']}"
            if p.get("x-advanced"):
                desc = "(advanced) " + desc
            impact = p.get("x-impact", "").replace("|", "/")
            lines.append(f"| `{f}` | {p.get('x-reach', '')} | `{default}` | {rng} | {p.get('x-unit', '')} | {desc} | {impact} |")
        lines.append("")
    Path("docs/CONFIG.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
