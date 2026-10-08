import gzip
import hashlib
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_world_v2 import snapshot

from utilsim.worker import world_creation
from utilsim.worker.jobs import LocalJobs
from utilsim.worker.server import create_app
from utilsim.worker.worlds import WorldLibrary
from utilsim.world.map_view import WorldMap
from utilsim.world.store import World


def source(tmp_path):
    value = {**snapshot(), 'bounds': [0, 0, 100, 100], 'roads': [], 'networks': {}}
    file = tmp_path / 'snapshot.json.gz'
    with gzip.open(file, 'wt') as stream:
        json.dump(value, stream)
    return file, value


def test_create_once_with_pinned_geography_and_new_physical_history(tmp_path):
    file, value = source(tmp_path)
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    library = WorldLibrary(tmp_path)
    command = str(uuid.uuid4())
    def create(_):
        return world_creation.create(library, command, str(file), 'NEW', '2027-01-01')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(4)))
    assert all(r == results[0] for r in results)
    assert library.list()['total'] == 1
    world = library.world(results[0]['id'])
    assert WorldMap(world).snapshot() == value
    assert world.status()['through'] == '2027-01-01'
    assert world.status()['days'] == world.status()['observations'] == 0
    with world.db() as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
    assert hashlib.sha256(file.read_bytes()).hexdigest() == digest
    # Recorded completion survives restart and disappearance of the source file.
    file.unlink()
    assert create(None) == results[0]
    with pytest.raises(ValueError, match='different inputs'):
        world_creation.create(library, command, str(file), 'DIFFERENT', '2027-01-01')
    assert WorldLibrary(tmp_path).list()['total'] == 1


def test_recover_after_world_commit_before_catalog_commit(tmp_path, monkeypatch):
    file, value = source(tmp_path)
    library = WorldLibrary(tmp_path)
    command = str(uuid.uuid4())
    initialize = World.initialize
    def interrupted(self, *args):
        initialize(self, *args)
        raise OSError('simulated interrupted catalog completion')
    monkeypatch.setattr(World, 'initialize', interrupted)
    with pytest.raises(OSError):
        world_creation.create(library, command, str(file), 'RECOVER', '2026-04-01')
    assert library.list()['total'] == 0
    assert world_creation.pending(library)[0]['commandId'] == command
    file.write_text('source has changed; recovery must use the pinned original')
    monkeypatch.setattr(World, 'initialize', initialize)
    # A separately registered shortcut must not be silently overwritten during recovery.
    manual = library.register(str(next((tmp_path / 'worlds').glob('*/world.sqlite'))))
    with pytest.raises(sqlite3.IntegrityError):
        world_creation.retry(library, command)
    assert world_creation.pending(library) and library.list()['worlds'][0]['id'] == manual
    library.remove(manual)
    result = world_creation.retry(WorldLibrary(tmp_path), command)
    assert library.list()['total'] == 1 and world_creation.pending(library) == []
    world = library.world(result['id'])
    assert WorldMap(world).snapshot() == value
    with world.db() as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1


def test_reject_bad_sources_and_bound_decompression_before_writing_worlds(tmp_path, monkeypatch):
    file, value = source(tmp_path)
    library = WorldLibrary(tmp_path)
    def create():
        return world_creation.create(library, str(uuid.uuid4()), str(file), 'BAD', '2026-01-01')
    monkeypatch.setattr(world_creation, 'MAX_SNAPSHOT_BYTES', 100)
    with pytest.raises(ValueError, match='limit'):
        create()
    monkeypatch.setattr(world_creation, 'MAX_SNAPSHOT_BYTES', 10000)
    for invalid in ({'schemaVersion': 'town-manifest/1'}, {**value, 'meters': []}):
        with gzip.open(file, 'wt') as stream:
            json.dump(invalid, stream)
        with pytest.raises(ValueError):
            create()
    file.write_bytes(gzip.compress(json.dumps(value).encode())[:-8])
    with pytest.raises(ValueError, match='incomplete'):
        create()
    assert library.list()['total'] == 0
    assert not (tmp_path / 'worlds').exists()
    assert world_creation.pending(library) == []


def test_creation_api_requires_launcher_access_and_preserves_sources(tmp_path):
    file, value = source(tmp_path)
    data = {'path': str(file), 'environment': 'HTTP', 'start': '2026-03-01', 'commandId': str(uuid.uuid4())}
    headers = {'Authorization': 'Bearer creation-test'}
    with TestClient(create_app(LocalJobs(tmp_path), 'creation-test'), base_url='http://127.0.0.1') as client:
        assert client.post('/local/worlds/create', json=data).status_code == 401
        assert client.get('/local/worlds/creations').status_code == 401
        assert client.post('/local/worlds/creations/x/retry', json={}).status_code == 401
        assert client.post('/local/worlds/create', json=data, headers={**headers, 'Host': 'example.com'}).status_code == 403
        result = client.post('/local/worlds/create', json=data, headers=headers)
        assert result.status_code == 200, result.text
        assert client.post('/local/worlds/create', json=data, headers=headers).json() == result.json()
        assert client.get('/local/worlds', headers=headers).json()['total'] == 1
        assert client.get('/local/worlds/creations', headers=headers).json()['pending'] == []
        assert client.get('/local/worlds/' + result.json()['id'] + '/map/snapshot', headers=headers).json() == value
        assert client.post('/local/worlds/create', json={**data, 'environment': 'WRONG'}, headers=headers).status_code == 422
