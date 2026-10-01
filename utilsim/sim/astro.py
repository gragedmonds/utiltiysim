"""Sun position (NOAA solar calculator equations) and moon phase, for the clock in state frames.

Accuracy is about ±0.5° in elevation for 1950–2050, which is plenty for scene lighting and the sun/moon widget."""

from __future__ import annotations

import math
from datetime import UTC, datetime

SYNODIC_MONTH = 29.530588853
REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=UTC)


def _julian_day(t: datetime) -> float:
    t = t.astimezone(UTC)
    return t.timestamp() / 86400.0 + 2440587.5


def sun_position(t: datetime, lat: float, lon: float) -> tuple[float, float]:
    """(elevation°, azimuth° clockwise from north) of the sun at aware datetime ``t``; includes refraction."""
    jd = _julian_day(t)
    jc = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360.0
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + math.sin(2 * mr) * (0.019993 - 0.000101 * jc)
         + math.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    mean_obliq = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obliq = mean_obliq + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(obliq)) * math.sin(math.radians(app_long))))
    y = math.tan(math.radians(obliq / 2)) ** 2
    l0r = math.radians(l0)
    eq_time = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) *
                               math.cos(2 * l0r) - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    tu = t.astimezone(UTC)
    minutes = tu.hour * 60 + tu.minute + tu.second / 60 + tu.microsecond / 6e7
    true_solar = (minutes + eq_time + 4 * lon) % 1440
    hour_angle = true_solar / 4 - 180 if true_solar >= 0 else true_solar / 4 + 180
    latr, declr, har = math.radians(lat), math.radians(decl), math.radians(hour_angle)
    cos_zen = math.sin(latr) * math.sin(declr) + math.cos(latr) * math.cos(declr) * math.cos(har)
    zen = math.degrees(math.acos(max(-1.0, min(1.0, cos_zen))))
    elev = 90 - zen
    if elev > 85:
        refr = 0.0
    elif elev > 5:
        te = math.tan(math.radians(elev))
        refr = 58.1 / te - 0.07 / te**3 + 0.000086 / te**5
    elif elev > -0.575:
        refr = 1735 + elev * (-518.2 + elev * (103.4 + elev * (-12.79 + elev * 0.711)))
    else:
        refr = -20.772 / math.tan(math.radians(elev))
    elev += refr / 3600.0
    zr = math.radians(zen)
    denom = math.cos(latr) * math.sin(zr)
    if abs(denom) < 1e-9:
        az = 0.0
    else:
        a = math.degrees(math.acos(max(-1.0, min(1.0, (math.sin(latr) * math.cos(zr) - math.sin(declr)) / denom))))
        az = (a + 180) % 360 if hour_angle > 0 else (540 - a) % 360
    return round(elev, 3), round(az, 3)


def moon_phase(t: datetime) -> float:
    """Fraction of the synodic month in [0, 1): 0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter."""
    days = (t.astimezone(UTC) - REFERENCE_NEW_MOON).total_seconds() / 86400.0
    return round((days / SYNODIC_MONTH) % 1.0, 4)
