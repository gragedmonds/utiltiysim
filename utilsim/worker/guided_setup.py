"""Validate a reviewed setup and pin its generated geography before creating a world."""
import hashlib
import math
import uuid
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from api._agent_config import preset_config, supported_fields
from api._towns import MAX_HOUSES
from utilsim.config.model import RUN_GROUPS, SimConfig, config_schema
from utilsim.config.presets import deep_merge
from utilsim.world.store import DEFAULTS, MODEL_VERSION, canonical


def validate_setup(value):
    allowed = {'commandId', 'preset', 'townOverrides', 'environment', 'start', 'worldSettings'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('Unknown guided setup input.')
    try:
        command = str(uuid.UUID(value.get('commandId')))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('A creation command UUID is required.') from exc
    environment, start = value.get('environment'), value.get('start')
    if not isinstance(environment, str) or not environment.strip() or len(environment) > 200:
        raise ValueError('Give the environment a name of at most 200 characters.')
    if not isinstance(start, str) or date.fromisoformat(start).isoformat() != start:
        raise ValueError('Use a canonical YYYY-MM-DD start date.')
    overrides = value.get('townOverrides', {})
    if not isinstance(overrides, dict) or any(not isinstance(v, dict) for v in overrides.values()):
        raise ValueError('Each town override group must be an object.')
    if any(k in RUN_GROUPS or k not in SimConfig.model_fields or k in ('name', 'description') for k in overrides):
        raise ValueError('A physical world accepts only town-generation settings.')
    if set(overrides.get('town', {})) & {'osm_source', 'osm_sha256'}:
        raise ValueError('Street sources must come from a prepared town.')
    supported_fields(overrides, config_schema())
    cfg = SimConfig.model_validate(deep_merge(preset_config(value.get('preset')).model_dump(mode='json'), overrides))
    if cfg.town.houses > MAX_HOUSES:
        raise ValueError(f'A saved physical world supports at most {MAX_HOUSES:,} homes.')
    try:
        ZoneInfo(cfg.town.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError('Choose a valid IANA timezone.') from exc
    supplied = value.get('worldSettings', {})
    if not isinstance(supplied, dict):
        raise ValueError('World settings must be an object.')
    settings = {**DEFAULTS, **supplied}
    if set(settings) != set(DEFAULTS) or any(type(v) not in (int, float) or not math.isfinite(v) for v in settings.values()):
        raise ValueError('Unknown or invalid world setting.')
    if any(not 0 <= settings[k] <= 1 for k in ('annual_meter_failure', 'annual_meter_drift')):
        raise ValueError('Annual probabilities must be between zero and one.')
    if settings['daily_weather_spread_c'] < 0:
        raise ValueError('Daily weather variation must be nonnegative.')
    request = {'source': 'guided-setup', 'configuration': cfg.generation_dict(),
               'environment': environment, 'start': start, 'settings': settings, 'modelVersion': MODEL_VERSION}
    return command, cfg, request


def review(value):
    _, cfg, request = validate_setup(value)
    return {'homes': cfg.town.houses, 'services': list(cfg.customers_billing.services),
            'configurationSha256': hashlib.sha256(canonical(request).encode()).hexdigest(),
            'worldSettings': request['settings']}


def create(library, value):
    from utilsim.gen.pipeline import generate
    from utilsim.io.snapshot import build_snapshot

    from .world_creation import resume, validate_snapshot

    command, cfg, request = validate_setup(value)
    request = canonical(request)
    with library.db() as db:
        row = db.execute('SELECT * FROM world_creations WHERE command=?', (command,)).fetchone()
    if row:
        if row['request'] != request:
            raise ValueError('That creation command belongs to different inputs.')
        return resume(library, row)
    snapshot = build_snapshot(generate(cfg), include_reads=False, detail='full')
    validate_snapshot(snapshot)
    pinned = canonical(snapshot)
    with library.db() as db:
        db.execute('INSERT OR IGNORE INTO world_creations VALUES(?,?,?,?,?,?)',
                   (command, request, pinned, hashlib.sha256(pinned.encode()).hexdigest(), uuid.uuid4().hex, 'pending'))
        row = db.execute('SELECT * FROM world_creations WHERE command=?', (command,)).fetchone()
        if row['request'] != request:
            raise ValueError('That creation command belongs to different inputs.')
    return resume(library, row)
