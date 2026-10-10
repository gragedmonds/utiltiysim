"""Editable guided-setup catalogue; numerical bounds remain owned by engine schemas."""
import json
from pathlib import Path

from utilsim.world.store import DEFAULTS


def catalogue():
    return json.loads(Path(__file__).with_name('wizard.json').read_text(encoding='utf-8'))


def world_configuration():
    groups = {
        'weather': ('Daily weather', {
            'winter_mean_c': ('Winter average', '°C'),
            'summer_mean_c': ('Summer average', '°C'),
            'daily_weather_spread_c': ('Daily variation', '°C'),
        }),
        'meters': ('Meter condition', {
            'annual_meter_failure': ('Annual base failure probability', ''),
            'annual_meter_drift': ('Annual drift probability', ''),
        }),
    }
    properties, defaults = {}, {}
    for group, (title, fields) in groups.items():
        props = {}
        for key, (label, unit) in fields.items():
            props[key] = {'type': 'number', 'title': label, 'default': DEFAULTS[key], 'x-unit': unit,
                          **({'minimum': 0, 'maximum': 1} if group == 'meters' else
                             {'minimum': 0} if key == 'daily_weather_spread_c' else {})}
        properties[group] = {'type': 'object', 'title': title, 'properties': props}
        defaults[group] = {key: DEFAULTS[key] for key in fields}
    return {'type': 'object', 'properties': properties}, defaults
