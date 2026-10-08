import gzip
import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from test_world_creation import source

from utilsim.io.run_bundle import run_key
from utilsim.worker import snapshot_catalog, world_creation
from utilsim.worker.jobs import LocalJobs
from utilsim.worker.server import create_app
from utilsim.worker.worlds import WorldLibrary
from utilsim.world.map_view import WorldMap
from utilsim.world.store import World


def archive(tmp_path, label='Saved town'):
    _, value = source(tmp_path)
    raw = json.dumps(value, sort_keys=True).encode()
    inputs = {'snapshotSha256': hashlib.sha256(raw).hexdigest(), 'town': value['id'], 'label': label}
    key = run_key('test-engine', inputs)
    directory = tmp_path / 'runs' / key
    directory.mkdir(parents=True)
    compressed = gzip.compress(raw)
    (directory / 'snapshot.json.gz').write_bytes(compressed)
    (directory / 'inputs.json').write_text(json.dumps(inputs))
    manifest = {'schemaVersion': 'run-manifest/1.0', 'runKey': key, 'inputs': inputs,
                'engineBuild': 'test-engine', 'asOf': '2026-12-31',
                'towns': [{'id': value['id'], 'name': label, 'accounts': 1, 'registers': 3}],
                'files': [{'name': 'snapshot.json.gz', 'bytes': len(compressed),
                           'sha256': hashlib.sha256(compressed).hexdigest()}]}
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return key, directory, value


def test_source_pages_bound_reads_and_retain_unavailable_entries(tmp_path, monkeypatch):
    keys = [archive(tmp_path, str(i))[0] for i in range(4)]
    (tmp_path / 'runs' / min(keys) / 'manifest.json').write_text('{}')
    (tmp_path / 'runs' / '.unfinished').mkdir()
    def no_snapshots(*_):
        raise AssertionError('Picker must not load geometry')
    monkeypatch.setattr(snapshot_catalog, 'read_snapshot', no_snapshots)
    first = snapshot_catalog.listing(tmp_path, limit=2)
    second = snapshot_catalog.listing(tmp_path, first['next'], limit=2)
    assert [r['runKey'] for r in first['towns'] + second['towns']] == sorted(keys)
    assert first['towns'][0]['available'] is False
    assert second['next'] is None
    assert snapshot_catalog.listing(tmp_path, max(keys))['towns'] == []
    for after, limit in (('../elsewhere', 2), ('', 0), ('', 26)):
        with pytest.raises(ValueError):
            snapshot_catalog.listing(tmp_path, after, limit)


def test_verified_creation_pins_source_and_recovers_without_archive(tmp_path, monkeypatch):
    key, directory, value = archive(tmp_path)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
    library = WorldLibrary(tmp_path)
    command = str(uuid.uuid4())
    original = World.initialize
    def interrupted(self, *args):
        original(self, *args)
        raise OSError('interrupted after physical commit')
    monkeypatch.setattr(World, 'initialize', interrupted)
    with pytest.raises(OSError):
        world_creation.create(library, command, None, 'PICKED', '2026-02-01', run_key=key)
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
    assert world_creation.pending(library)[0]['runKey'] == key
    (directory / 'snapshot.json.gz').unlink()
    monkeypatch.setattr(World, 'initialize', original)
    result = world_creation.create(library, command, None, 'PICKED', '2026-02-01', run_key=key)
    assert WorldMap(library.world(result['id'])).snapshot() == value
    assert library.world(result['id']).status()['days'] == 0
    assert world_creation.retry(library, command) == result
    with pytest.raises(ValueError, match='different inputs'):
        world_creation.create(library, command, None, 'PICKED', '2026-02-01', run_key='f' * 64)


@pytest.mark.parametrize('damage', ['compressed', 'input', 'lineage', 'duplicate', 'identity', 'town', 'oversize', 'missing'])
def test_archive_rejection_does_not_create_pending_or_world(tmp_path, monkeypatch, damage):
    key, directory, _ = archive(tmp_path)
    meta = directory / 'manifest.json'
    manifest = json.loads(meta.read_text())
    if damage == 'compressed':
        with (directory / 'snapshot.json.gz').open('ab') as stream:
            stream.write(b'changed')
    elif damage == 'input':
        (directory / 'inputs.json').write_text('{}')
    elif damage == 'lineage':
        raw = gzip.decompress((directory / 'snapshot.json.gz').read_bytes()) + b' '
        compressed = gzip.compress(raw)
        (directory / 'snapshot.json.gz').write_bytes(compressed)
        manifest['files'][0].update(bytes=len(compressed), sha256=hashlib.sha256(compressed).hexdigest())
    elif damage == 'duplicate':
        manifest['files'].append(manifest['files'][0])
    elif damage == 'identity':
        manifest['runKey'] = 'f' * 64
    elif damage == 'town':
        manifest['towns'][0]['id'] = 'different-town'
    elif damage == 'oversize':
        monkeypatch.setattr(world_creation, 'MAX_SNAPSHOT_BYTES', 5)
    elif damage == 'missing':
        (directory / 'snapshot.json.gz').unlink()
    meta.write_text(json.dumps(manifest))
    library = WorldLibrary(tmp_path)
    with pytest.raises((ValueError, OSError)):
        world_creation.create(library, str(uuid.uuid4()), None, 'BAD', '2026-02-01', run_key=key)
    assert library.list()['total'] == 0 and world_creation.pending(library) == []
    assert not (tmp_path / 'worlds').exists()


def test_picker_api_access_pagination_and_source_selection(tmp_path):
    key, _, value = archive(tmp_path)
    headers = {'Authorization': 'Bearer picker-test'}
    with TestClient(create_app(LocalJobs(tmp_path), 'picker-test'), base_url='http://127.0.0.1') as client:
        url = '/local/worlds/sources'
        assert client.get(url).status_code == 401
        assert client.get(url, headers={**headers, 'Host': 'elsewhere'}).status_code == 403
        assert client.get(url + '?limit=26', headers=headers).status_code == 422
        assert client.get(url + '?after=../', headers=headers).status_code == 422
        assert client.get(url, headers=headers).json()['towns'][0]['runKey'] == key
        body = {'runKey': key, 'commandId': str(uuid.uuid4()), 'environment': 'HTTP', 'start': '2026-01-01'}
        for invalid in ({**body, 'runKey': '../escape'}, {**body, 'path': str(tmp_path / 'snapshot.json.gz')}):
            assert client.post('/local/worlds/create', json=invalid, headers=headers).status_code == 422
        result = client.post('/local/worlds/create', json=body, headers=headers)
        assert result.status_code == 200, result.text
        assert client.post('/local/worlds/create', json=body, headers=headers).json() == result.json()
        assert client.get('/local/worlds/' + result.json()['id'] + '/map/snapshot', headers=headers).json() == value


def test_manifest_size_limit_and_snapshot_replacement_during_read(tmp_path, monkeypatch):
    key, directory, value = archive(tmp_path)
    read = snapshot_catalog.bounded_file
    def swap_after_read(folder, name, maximum):
        data = read(folder, name, maximum)
        if name == 'snapshot.json.gz':
            (folder / name).write_bytes(b'replacement after checksum read')
        return data
    monkeypatch.setattr(snapshot_catalog, 'bounded_file', swap_after_read)
    assert snapshot_catalog.read_snapshot(tmp_path, key, 100000) == value
    monkeypatch.setattr(snapshot_catalog, 'MAX_METADATA_BYTES', 10)
    assert snapshot_catalog.listing(tmp_path)['towns'][0]['available'] is False


def test_bounded_archive_decompression(tmp_path):
    key, directory, _ = archive(tmp_path)
    compressed = (directory / 'snapshot.json.gz').read_bytes()
    assert len(gzip.decompress(compressed)) > len(compressed) + 1
    with pytest.raises(ValueError, match='uncompressed size limit'):
        snapshot_catalog.read_snapshot(tmp_path, key, len(compressed) + 1)
