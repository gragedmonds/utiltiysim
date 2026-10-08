import hashlib
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_world_v2 import world

from utilsim.worker.jobs import LocalJobs
from utilsim.worker.server import create_app
from utilsim.worker.worlds import ReadOnlyWorld, WorldLibrary


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_library_is_durable_read_only_and_observes_current_world(tmp_path):
    w = world(tmp_path, annual_meter_failure=1)
    store = tmp_path / 'library'
    store.mkdir()
    library = WorldLibrary(store)
    original = digest(w.path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = set(pool.map(library.register, [w.path] * 8))
    assert len(identities) == 1
    identity = identities.pop()
    assert library.register(w.path) == identity
    assert WorldLibrary(store).list()['worlds'][0]['environmentId'] == 'TEST'
    assert digest(w.path) == original
    with pytest.raises(sqlite3.OperationalError, match='readonly'):
        with library.world(identity).db() as db:
            db.execute('DELETE FROM days')
    assert digest(w.path) == original
    w.advance('2026-01-03')
    assert WorldLibrary(store).list()['worlds'][0]['days'] == 2
    current = digest(w.path)
    assert library.remove(identity)
    assert not library.remove(identity)
    assert library.list()['total'] == 0
    assert digest(w.path) == current


def test_missing_changed_and_invalid_files_do_not_create_or_migrate_worlds(tmp_path):
    store = tmp_path / 'library'
    store.mkdir()
    library = WorldLibrary(store)
    missing = tmp_path / 'missing.sqlite'
    with pytest.raises(OSError):
        library.register(str(missing))
    assert not missing.exists()
    with pytest.raises(ValueError, match='full path'):
        library.register('relative.sqlite')
    invalid = tmp_path / 'other.sqlite'
    invalid.write_text('not a world')
    before = digest(invalid)
    with pytest.raises(sqlite3.Error):
        library.register(str(invalid))
    assert digest(invalid) == before
    w = world(tmp_path / 'first')
    identity = library.register(w.path)
    Path(w.path).rename(missing)
    assert not library.list()['worlds'][0]['available']
    assert not Path(w.path).exists()
    other = world(tmp_path / 'second', annual_meter_failure=1)
    shutil.copyfile(other.path, w.path)
    assert not library.list()['worlds'][0]['available']
    with pytest.raises(ValueError, match='identity changed'):
        with library.world(identity).db():
            pass
    replacement = library.register(w.path)
    assert replacement != identity
    with pytest.raises(KeyError):
        library.world(identity)
    assert library.list()['worlds'][0]['available']


def test_worker_library_authorization_and_map_boundaries(tmp_path):
    w = world(tmp_path / 'source', annual_meter_failure=1)
    w.advance('2026-01-03')
    before = digest(w.path)
    store = tmp_path / 'library'
    store.mkdir()
    auth = {'Authorization': 'Bearer library-test'}
    with TestClient(create_app(LocalJobs(store), 'library-test'), base_url='http://127.0.0.1') as client:
        assert client.get('/worlds').status_code == 200
        assert client.get('/worlds.js').status_code == 200
        assert client.get('/local/worlds').status_code == 401
        assert client.post('/local/worlds', json={'path': w.path}).status_code == 401
        assert client.get('/local/worlds', headers={**auth, 'Host': 'example.com'}).status_code == 403
        response = client.post('/local/worlds', headers=auth, json={'path': w.path})
        assert response.status_code == 200, response.text
        identity = response.json()['id']
        base = '/local/worlds/' + identity
        for operation in ('snapshot', 'status', 'premise?id=P1'):
            assert client.get(base + '/map/' + operation).status_code == 401
            assert client.get(base + '/map/' + operation, headers=auth).status_code == 200
        p = client.get(base + '/map/premise?id=P1', headers=auth).json()
        assert p['view'] == 'administrator-truth'
        assert all(a['true_quantity'] and a['observed_quantity'] is None for a in p['assets'])
        assert client.get(base + '/map/premise?id=P1&id=P2', headers=auth).status_code == 422
        assert client.get(base + '/map/snapshot?extra=1', headers=auth).status_code == 422
        assert client.get('/local/worlds?limit=51', headers=auth).status_code == 422
        assert client.get('/local/worlds?offset=-1', headers=auth).status_code == 422
        assert client.post(base + '/advance', headers=auth, json={'through': '2027-01-01'}).status_code == 405
        assert client.delete(base).status_code == 401
        assert client.delete(base, headers=auth).json()['sourceDeleted'] is False
        assert client.get(base + '/map/status', headers=auth).status_code == 404
    assert digest(w.path) == before


def test_read_only_connection_pins_one_snapshot_and_library_pages(tmp_path):
    w = world(tmp_path / 'source')
    # WAL permits a concurrent writer while a map query keeps its original snapshot.
    with sqlite3.connect(w.path) as db:
        db.execute('PRAGMA journal_mode=WAL')
    ro = ReadOnlyWorld(Path(w.path))
    with ro.db() as db:
        assert ro.metadata(db)['through'] == '2026-01-01'
        w.advance('2026-01-02')
        assert ro.metadata(db)['through'] == '2026-01-01'
    assert ro.status()['through'] == '2026-01-02'
    store = tmp_path / 'library'
    store.mkdir()
    lib = WorldLibrary(store)
    identities = set()
    for i in range(3):
        target = tmp_path / f'world-{i}.sqlite'
        with sqlite3.connect(w.path) as src, sqlite3.connect(target) as dest:
            src.backup(dest)
        identities.add(lib.register(str(target)))
    one, two = lib.list(limit=2), lib.list(offset=2, limit=2)
    assert one['total'] == two['total'] == 3
    assert len(one['worlds']) == 2 and len(two['worlds']) == 1
    assert {w['id'] for w in one['worlds'] + two['worlds']} == identities
