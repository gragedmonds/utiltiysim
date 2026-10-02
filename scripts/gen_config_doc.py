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

Presets (`GET /api/config/presets`) are YAML overrides deep-merged on the defaults. The town id is a hash of the
generation-relevant config plus the generator version, so every combination is reproducible. Only `scenario` is
run-scoped today; weather, incidents, operations, process and anomalies become run-scoped when the M2/M3 clock
uses them (their groups will then say `x-applies: run`).

## Knock-on chains worth demonstrating

| Change | What you should see |
|---|---|
| `housing.solar_rate` ↑ | More export registers and net-metering contracts; reverse flow on services, transformers and eventually the whole town at noon |
| `housing.ev_rate` ↑ | Higher individual peaks → larger transformers, more transformer groups, heavier feeders, more feeders |
| `housing.electric_heat_rate` ↑ or `gas.all_electric_district_share` ↑ | Fewer gas services and smaller gas mains; higher electric design load |
| `electric.overhead_before_year` ↑ | More overhead districts → poles, pole-mount transformers, lightning exposure (M3 outages) |
| `gas.scheme` = `mp` | No low-pressure core, no district regulators, ¾" services with regulators everywhere |
| `water.fire_flow_residential_lps` ↑ | Larger distribution mains everywhere (fire flow governs sizing) |
| `town.terrain_relief_m` ↑ | Second pressure zone, second elevated tank, PRV/booster equipment at zone boundaries |
| `ami.ami_route_share` ↓ | More AMR van and manual walker routes; more estimated reads (M3) |
| `customers_billing.mru_target_meters` ↓ | More, smaller meter reading routes |
| `town.houses` ↑ beyond the OSM extract | Synthetic districts grown around the Whitby core; second substation; more feeders |
| `town.commercial_share_arterial` / `_collector` / `_local` ↑ | More storefronts on that class of street, clustered at main-road intersections and towards downtown; homes pushed outward (still exactly `houses`); more 3φ pads, commercial accounts and closer hydrant spacing |
| A real-place preset (`ayr`, `elora`, `cobourg`, `whitby_wide`) | The place's own streets at their natural size; set `expansion: grow` and more `houses` to add synthetic districts around it |

"""


def main() -> None:
    s = config_schema()
    defs = s["$defs"]
    groups = sorted(((k, v) for k, v in defs.items() if v.get("x-group")), key=lambda kv: kv[1].get("x-order", 99))
    lines = [HEADER]
    for name, d in groups:
        lines.append(f"## {d.get('title', name)}\n\n{d.get('description', '')}\n")
        lines.append("| Field | Default | Range | Unit | Description |")
        lines.append("|---|---|---|---|---|")
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
            if p.get("x-advanced"):
                desc = "(advanced) " + desc
            lines.append(f"| `{f}` | `{default}` | {rng} | {p.get('x-unit', '')} | {desc} |")
        lines.append("")
    Path("docs/CONFIG.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
