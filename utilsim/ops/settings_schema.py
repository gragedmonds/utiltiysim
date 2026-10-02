"""JSON Schema for the operations run settings (``ops.timeline.run_defaults``), in the shape the viewer's schema form
renders: groups with titled, bounded, unit-carrying fields.

Groups marked ``x-flat`` hold top-level settings (``{"fieldCrews": 3}``); the others are the nested per-utility or
per-incident settings (``{"detectSeconds": {"water": 600}}``). A request's ``settings`` overrides only what it names.
A field whose default comes from the town's config names that field in ``x-town`` (e.g. ``operations.gas_crews``):
``GET /api/sim/settings/schema?town=`` fills those defaults from the town, so they can be tweaked per run without
generating a new town.
"""

from __future__ import annotations

from utilsim.ops.timeline import DEFAULTS, TOWN_SETTINGS

# key: (title, description, unit, minimum, maximum, effects)
_FLAT = {
    "crews": ("Crews and mutual aid", "Who is available to send. Defaults come from the town's field operations.", {
        "electricCrews": ("Electric crews", "Line crews for electric faults.", "", 1, 30,
                          ["outage duration", "SAIDI"]),
        "waterCrews": ("Water crews", "Distribution crews for main breaks.", "", 1, 20, ["time to restore"]),
        "gasCrews": ("Gas crews", "Emergency crews for leaks.", "", 1, 20, ["leak response time"]),
        "meterTechs": ("Meter technicians", "Field visits and AMI collector repairs.", "", 1, 20,
                       ["visit wait", "collector outage length"]),
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
        "gasResponseTargetMinutes": ("Gas response target", "An odour call should have a crew on site within this; "
                                     "each gas incident reports whether it was met.", "min", 10, 240,
                                     ["targets met"]),
        "shiftStartHour": ("Day shift starts", "Non-emergency work (AMI collector repairs) waits for the day shift; "
                           "emergencies are worked around the clock.", "h", 0, 23, ["collector outage length"]),
        "shiftEndHour": ("Day shift ends", "", "h", 1, 24, ["collector outage length"]),
    }),
    "incidents": ("Random incidents", "What goes wrong on its own each day, at yearly rates scaled to the town's "
                  "assets. Defaults come from the town's incidents and weather.", {
        "randomIncidents": ("Random incidents", "Off: only the incidents you cause happen (the town's manual-only "
                            "setting).", "", None, None, ["background incidents"]),
        "waterMainBreaksPer100km": ("Water main breaks", "Per 100 km of main per year; cast-iron mains count twice.",
                                    "/100 km/yr", 0, 200, ["water outages", "crew workload"]),
        "gasMainLeaksPer100km": ("Gas main leaks", "Per 100 km of main per year.", "/100 km/yr", 0, 200,
                                 ["gas outages", "relights"]),
        "gasServiceLeaksPer1000": ("Gas service leaks", "Per 1,000 services per year.", "/1000/yr", 0, 50,
                                   ["gas crew workload"]),
        "transformerFailuresPer1000": ("Transformer failures", "Per 1,000 transformers per year; three times as "
                                       "likely when the evening peak loads one above its rating.", "/1000/yr", 0, 100,
                                       ["electric outages"]),
        "overheadFaultsPerKmStormDay": ("Storm line faults", "Per km of overhead primary on a storm day.",
                                        "/km/storm day", 0, 1, ["outages", "SAIDI/SAIFI"]),
        "stormDaysPerYear": ("Storm days", "Thunderstorm days per year, mostly May to September.", "days/yr", 0, 120,
                             ["storm line faults"]),
        "collectorOutagesPerYear": ("AMI collector outages", "Per year, town-wide; the collector's meters miss their "
                                    "reads until it is repaired.", "/yr", 0, 50, ["comm-fail exceptions"]),
    }),
    "backfeed": ("Back-feed through ties", "Restoring customers from the next feeder during a repair.", {
        "tieBackfeed": ("Use normally-open ties", "Close a tie to pick up customers cut off by an isolated fault.", "",
                        None, None, ["customer minutes"]),
        "tieSwitchMinutes": ("Switching time", "From isolation to the tie closing.", "min", 0, 120, []),
        "tieMaxLoading": ("Emergency loading limit", "Do not close a tie that would load the receiving feeder above this "
                          "share of its rating.", "×", 0.5, 2.0, ["back-feeds declined"]),
        "tieMinVoltage": ("Voltage floor", "Do not close a tie that would leave a customer below this (120 V base). "
                          "Default: the town's lower service limit less 4 V (ANSI C84.1 Range B).",
                          "V", 90, 120, ["back-feeds declined"]),
    }),
    "reading": ("Reading rounds", "The day's walked and drive-by routes.", {
        "meterReading": ("Run reading rounds", "Schedule the day's walked and drive-by routes as crew jobs.", "", None,
                         None, []),
        "meterWalkers": ("Meter readers", "Walkers share the walked routes in turn; one reader's rounds on the same "
                         "day run one after another.", "", 1, 40, ["round start"]),
        "meterVans": ("Drive-by vans", "Vans share the drive-by routes in turn.", "", 1, 20, ["round start"]),
        "walkKmh": ("Walking speed", "", "km/h", 1, 8, ["round length"]),
        "driveByKmh": ("Drive-by speed", "", "km/h", 5, 60, ["round length"]),
        "meterDwellSeconds": ("Time at each meter", "", "s", 0, 600, ["round length"]),
    }),
}
# nested key: (title, description, unit, minimum, maximum)
_NESTED = {
    "detectSeconds": ("Detection time", "From the fault to the utility knowing (AMI last gasp, pressure alarm, odour "
                      "calls, the head end's alarm for a silent collector).", "s", 0, 7200),
    "isolateMinutes": ("Isolation time on site", "Opening devices or closing valves once the crew arrives.", "min", 0,
                       240),
    "repairMinutes": ("Repair time", "On-site repair by incident type.", "min", 5, 1440),
    "leakM3h": ("Fixed leak rate", "Used when the leak opening is 0 (always for a gas service).", "m³/h", 0, 5000),
    "leakOpening": ("Leak opening", "Share of the pipe bore a break opens (orifice flow at the local pressure).", "", 0,
                    1),
    "readerStartHour": ("Rounds start", "Local hour the readers leave the depot.", "h", 0, 23),
}
_TITLES = {"ami": "AMI collector", "MANUAL": "Walked", "AMR": "Drive-by", "gas_service": "Gas service"}


def _field(title: str, description: str, unit: str, lo, hi, effects, default, town: str | None = None) -> dict:
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
    if town:
        out["x-town"] = town
    return out


def settings_schema(defaults: dict | None = None) -> dict:
    """The schema with ``defaults`` (a town's ``run_defaults``; default: the config defaults)."""
    d = defaults or DEFAULTS
    props: dict = {}
    for group, (title, description, fields) in _FLAT.items():
        props[group] = {"type": "object", "title": title, "description": description, "x-flat": True,
                        "properties": {k: _field(*spec, d[k], TOWN_SETTINGS.get(k, (None,))[0])
                                       for k, spec in fields.items() if k in d}}
    for key, (title, description, unit, lo, hi) in _NESTED.items():
        if key not in d:
            continue
        props[key] = {"type": "object", "title": title, "description": description,
                      "properties": {k: _field(_TITLES.get(k) or k.replace("_", " ").capitalize(), "", unit, lo, hi, [],
                                               v) for k, v in d[key].items()}}
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
