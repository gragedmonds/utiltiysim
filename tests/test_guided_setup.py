import json
import uuid

import pytest
from fastapi.testclient import TestClient

from api._setup import configuration
from utilsim.config.model import SimConfig
from utilsim.config.presets import deep_merge
from utilsim.config.wizard import catalogue
from utilsim.worker import guided_setup, world_creation
from utilsim.worker.jobs import LocalJobs
from utilsim.worker.server import create_app
from utilsim.worker.worlds import WorldLibrary
from utilsim.world.map_view import WorldMap
from utilsim.world.store import DEFAULTS


def request():
    return {'commandId': str(uuid.uuid4()), 'preset': 'small_town', 'environment': 'Wizard acceptance',
            'start': '2026-02-01', 'townOverrides': {'town': {'houses': 20, 'era_core_year': 2016},
                                                   'customers_billing': {'services': ['water']},
                                                   'ami': {'ami_route_share': 0, 'amr_route_share': 0}},
            'worldSettings': {'annual_meter_failure': .04, 'winter_mean_c': -5}}


def test_catalogue_profiles_are_real_engine_settings():
    data = configuration('small_town')
    assert data['wizard'] == catalogue()
    assert set(data['schemas']['world']['properties']) == {'weather', 'meters'}
    assert {key for values in data['defaults']['world'].values() for key in values} == set(DEFAULTS)
    for page in catalogue()['pages']:
        for profile in page.get('presets', []):
            overrides = {}
            for key, value in profile['values'].items():
                scope, path = key.split(':')
                if scope != 'town':
                    continue
                group, field, *nested = path.split('.')
                assert field in getattr(SimConfig(), group).__class__.model_fields, key
                target = overrides.setdefault(group, {})
                for part in [field, *nested][:-1]:
                    target = target.setdefault(part, {})
                target[nested[-1] if nested else field] = value
            SimConfig.model_validate(deep_merge(data['defaults']['town'], overrides))


def test_create_reviewed_world_without_running_a_studio_year(tmp_path):
    value = request()
    reviewed = guided_setup.review(value)
    assert reviewed['homes'] == 20 and reviewed['services'] == ['water']
    library = WorldLibrary(tmp_path)
    created = guided_setup.create(library, value)
    world = library.world(created['id'])
    snapshot = WorldMap(world).snapshot()
    assert {s['commodity'] for s in snapshot['servicePoints']} == {'water'}
    assert world.status()['days'] == 0
    with world.db() as db:
        meta = world.metadata(db)
        assert meta['settings']['winter_mean_c'] == -5
        assert meta['settings']['annual_meter_failure'] == .04
    assert guided_setup.create(library, value) == created
    assert library.list()['total'] == 1
    with pytest.raises(ValueError, match='different inputs'):
        guided_setup.create(library, {**value, 'start': '2027-01-01'})


def test_pinned_creation_recovers_without_regenerating(tmp_path, monkeypatch):
    from test_world_creation import source

    from utilsim.gen import pipeline
    from utilsim.io import snapshot as snapshots
    _, snap = source(tmp_path)
    monkeypatch.setattr(pipeline, 'generate', lambda cfg: object())
    monkeypatch.setattr(snapshots, 'build_snapshot', lambda *args, **kwargs: snap)
    original = world_creation.resume
    monkeypatch.setattr(world_creation, 'resume', lambda *args: (_ for _ in ()).throw(OSError('interrupted')))
    library, value = WorldLibrary(tmp_path), request()
    with pytest.raises(OSError):
        guided_setup.create(library, value)
    assert len(world_creation.pending(library)) == 1
    monkeypatch.setattr(world_creation, 'resume', original)
    monkeypatch.setattr(pipeline, 'generate', lambda cfg: pytest.fail('Recovery must use the pinned geography'))
    assert guided_setup.create(library, value)['state'] == 'complete'
    assert not world_creation.pending(library)


@pytest.mark.parametrize('patch', [
    {'worldSettings': {'annual_meter_failure': 1.1}}, {'worldSettings': {'annual_meter_drift': True}},
    {'worldSettings': {'daily_weather_spread_c': -1}}, {'worldSettings': {'unknown': 1}},
    {'townOverrides': {'town': {'houses': 10001}}}, {'townOverrides': {'town': {'osm_source': 'C:/secret'}}},
    {'townOverrides': {'billing': {'tax': .2}}}, {'townOverrides': {'town': {'timezone': 'Invalid/Place'}}},
    {'environment': ' '}, {'start': 'not-a-date'}, {'commandId': 'not-a-command'},
])
def test_invalid_setup_is_rejected_before_generation(patch):
    with pytest.raises((ValueError, KeyError)):
        guided_setup.review({**request(), **patch})


def test_guided_routes_use_local_auth_and_validate_without_creating(tmp_path):
    jobs = LocalJobs(tmp_path)
    with TestClient(create_app(jobs, 'guided-test-token'), base_url='http://127.0.0.1') as client:
        assert client.post('/local/worlds/setup/validate', json=request()).status_code == 401
        headers = {'Authorization': 'Bearer guided-test-token'}
        response = client.post('/local/worlds/setup/validate', json=request(), headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()['homes'] == 20
        assert client.get('/local/worlds', headers=headers).json()['total'] == 0
        assert client.post('/local/worlds/setup/validate', json={**request(), 'worldSettings': {'unknown': 3}}, headers=headers).status_code == 422
        assert json.loads(client.get('/api/setup/configuration?preset=small_town').text)['wizard']['version'] == 1
