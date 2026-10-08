"""Bounded discovery and verified snapshot reads from completed local run archives."""
import gzip
import hashlib
import heapq
import io
import json
import os
import re
from pathlib import Path

KEY = re.compile(r'[a-f0-9]{64}')
MAX_METADATA_BYTES = 2 * 1024 * 1024


def location(store, key):
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError('Choose a saved run from this library.')
    root = (Path(store) / 'runs').resolve()
    directory = root / key
    if directory.resolve() != directory:
        raise ValueError('A saved run must remain inside its library.')
    return directory


def bounded_file(directory, name, maximum):
    path = directory / name
    if path.resolve() != path:
        raise ValueError('Archive files must remain inside their saved run.')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('Saved archive file exceeds its size limit.')
    return raw


def manifest(directory, key):
    value = json.loads(bounded_file(directory, 'manifest.json', MAX_METADATA_BYTES))
    if value['schemaVersion'] != 'run-manifest/1.0' or value['runKey'] != key:
        raise ValueError('Saved run identity does not match its manifest.')
    entries = [f for f in value['files'] if f['name'] == 'snapshot.json.gz']
    if len(entries) != 1 or not KEY.fullmatch(entries[0]['sha256']):
        raise ValueError('Saved run needs one checksummed town snapshot.')
    if type(entries[0]['bytes']) is not int or entries[0]['bytes'] < 1:
        raise ValueError('Invalid saved snapshot size.')
    return value, entries[0]


def listing(store, after='', limit=10):
    if not isinstance(after, str) or (after and not KEY.fullmatch(after)) or not 1 <= limit <= 25:
        raise ValueError('Use a saved-run cursor and a page size from 1 to 25.')
    root = Path(store) / 'runs'
    # Only a page of names and metadata is retained; never load town geometry to populate the picker.
    names = []
    if root.exists():
        with os.scandir(root) as entries:
            names = heapq.nsmallest(limit + 1, (p.name for p in entries
                                    if KEY.fullmatch(p.name) and p.name > after))
    rows = []
    for key in names[:limit]:
        row = {'runKey': key}
        try:
            directory = location(store, key)
            saved, _ = manifest(directory, key)
            town = saved['towns'][0]
            row.update(available=True, townId=str(town['id']), name=str(town['name']),
                       asOf=str(saved['asOf']), accounts=town['accounts'], registers=town['registers'])
            if not (directory / 'snapshot.json.gz').is_file():
                raise ValueError('Snapshot missing.')
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            row = {'runKey': key, 'available': False,
                   'error': 'Saved town unavailable. Restore its archive or choose another source.'}
        rows.append(row)
    return {'towns': rows, 'next': names[limit - 1] if len(names) > limit else None}


def read_snapshot(store, key, maximum):
    from utilsim.io.run_bundle import run_key

    directory = location(store, key)
    saved, entry = manifest(directory, key)
    inputs = json.loads(bounded_file(directory, 'inputs.json', MAX_METADATA_BYTES))
    if inputs != saved['inputs'] or run_key(saved['engineBuild'], inputs) != key:
        raise ValueError('Saved run inputs no longer match its identity.')
    raw = bounded_file(directory, 'snapshot.json.gz', maximum)
    if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('Saved snapshot checksum failed. Restore the original archive.')
    # Decompress the same verified bytes, so a replaced file cannot enter between verification and pinning.
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(maximum + 1)
    if len(expanded) > maximum:
        raise ValueError('Snapshot exceeds its uncompressed size limit.')
    if hashlib.sha256(expanded).hexdigest() != inputs['snapshotSha256']:
        raise ValueError('Saved snapshot does not belong to these run inputs.')
    snapshot = json.loads(expanded)
    if snapshot['id'] != inputs['town'] or snapshot['id'] != saved['towns'][0]['id']:
        raise ValueError('Saved town identity does not match its source records.')
    return snapshot
