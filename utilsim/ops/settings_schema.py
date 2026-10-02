"""JSON Schema for the operations run settings (``ops.timeline.DEFAULTS``), in the shape the viewer's schema form
renders: groups with titled, bounded, unit-carrying fields.

Groups marked ``x-flat`` hold top-level settings (``{"fieldCrews": 3}``); the others are the nested per-utility or
per-incident settings (``{"detectSeconds": {"water": 600}}``). A request's ``settings`` overrides only what it names.
"""

from __future__ import annotations

from utilsim.ops.timeline import DEFAULTS

# key: (title, description, unit, minimum, maximum, effects)
_FLAT = {
    "crews": ("Crews and mutual aid", "Who is available to send.", {
        "fieldCrews": ("Field crews", "Crews for meter-to-cash field orders.", "", 1, 20, ["field orders per day"]),
        "relightCrews": ("Relight crews", "Gas technicians available for a relight sweep.", "", 1, 60, ["relight time"]),
        "relightPerCrew": ("Premises per relight crew", "Mutual aid: one more crew per this many shut premises.", "",
                           5, 500, ["relight time"]),
    }),
    "dispatch": ("Dispatch and repair", "How the day's incidents are worked.", {
        "autoDispatch": ("Dispatch automatically", "Send a crew as soon as an incident is detected.", "", None, None,
                         ["time to restore"]),
        "mobiliseMinutes": ("Mobilise", "From dispatch to the van leaving the depot.", "min", 0, 120, ["time to restore"]),
        "flushMinutes": ("Flush after a water repair", "", "min", 0, 240, []),
        "visitMinutes": ("Field visit", "Time on site for a customer visit.", "min", 1, 240, []),
        "relightMinutes": ("Relight one premise", "", "min", 1, 60, ["relight time"]),
    }),
    "backfeed": ("Back-feed through ties", "Restoring customers from the next feeder during a repair.", {
        "tieBackfeed": ("Use normally-open ties", "Close a tie to pick up customers cut off by an isolated fault.", "",
                        None, None, ["customer minutes"]),
        "tieSwitchMinutes": ("Switching time", "From isolation to the tie closing.", "min", 0, 120, []),
        "tieMaxLoading": ("Emergency loading limit", "Do not close a tie that would load the receiving feeder above this "
                          "share of its rating.", "×", 0.5, 2.0, ["back-feeds declined"]),
        "tieMinVoltage": ("Voltage floor", "Do not close a tie that would leave a customer below this (120 V base).",
                          "V", 90, 120, ["back-feeds declined"]),
    }),
    "reading": ("Reading rounds", "The day's walked and drive-by routes.", {
        "meterReading": ("Run reading rounds", "Schedule the day's walked and drive-by routes as crew jobs.", "", None,
                         None, []),
        "walkKmh": ("Walking speed", "", "km/h", 1, 8, ["round length"]),
        "driveByKmh": ("Drive-by speed", "", "km/h", 5, 60, ["round length"]),
        "meterDwellSeconds": ("Time at each meter", "", "s", 0, 600, ["round length"]),
    }),
}
# nested key: (title, description, unit, minimum, maximum)
_NESTED = {
    "detectSeconds": ("Detection time", "From the fault to the utility knowing (AMI last gasp, pressure alarm, odour "
                      "calls).", "s", 0, 7200),
    "isolateMinutes": ("Isolation time on site", "Opening devices or closing valves once the crew arrives.", "min", 0,
                       240),
    "repairMinutes": ("Repair time", "On-site repair by incident type.", "min", 5, 1440),
    "leakM3h": ("Fixed leak rate", "Used when the leak opening is 0.", "m³/h", 0, 5000),
    "leakOpening": ("Leak opening", "Share of the pipe bore a break opens (orifice flow at the local pressure).", "", 0,
                    1),
    "readerStartHour": ("Rounds start", "Local hour the readers leave the depot.", "h", 0, 23),
}


def _field(title: str, description: str, unit: str, lo, hi, effects, default) -> dict:
    t = "boolean" if isinstance(default, bool) else "integer" if isinstance(default, int) else "number"
    out = {"title": title, "description": description, "type": t, "default": default}
    if unit:
        out["x-unit"] = unit
    if lo is not None and t != "boolean":
        out["minimum"] = lo
    if hi is not None and t != "boolean":
        out["maximum"] = hi
    if effects:
        out["x-effects"] = effects
    return out


def settings_schema() -> dict:
    props: dict = {}
    for group, (title, description, fields) in _FLAT.items():
        props[group] = {"type": "object", "title": title, "description": description, "x-flat": True,
                        "properties": {k: _field(*spec, DEFAULTS[k]) for k, spec in fields.items() if k in DEFAULTS}}
    for key, (title, description, unit, lo, hi) in _NESTED.items():
        if key not in DEFAULTS:
            continue
        props[key] = {"type": "object", "title": title, "description": description,
                      "properties": {k: _field(k.replace("_", " ").capitalize(), "", unit, lo, hi, [], v)
                                     for k, v in DEFAULTS[key].items()}}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Operations run settings",
            "type": "object", "x-applies": "run", "properties": props}


def to_settings(overrides: dict) -> dict:
    """Schema-form overrides (``{group: {key: value}}``) → a timeline request's ``settings``."""
    out: dict = {}
    for group, values in (overrides or {}).items():
        if group in _FLAT:
            out.update(values)
        else:
            out.setdefault(group, {}).update(values)
    return out
