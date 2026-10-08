"""Recoverable creation of new library worlds from pinned saved town snapshots."""
import gzip
import hashlib
import json
import uuid
from datetime import date
from pathlib import Path

from utilsim.world.store import DEFAULTS, MODEL_VERSION, World, canonical

MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024


def schema(library):
    with library.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS world_creations '
                   '(command TEXT PRIMARY KEY,request TEXT NOT NULL,snapshot TEXT NOT NULL,'
                   'digest TEXT NOT NULL,world_id TEXT NOT NULL,state TEXT NOT NULL)')


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('schemaVersion') != 'utility-town/2.0':
        raise ValueError('Choose a complete utility-town/2.0 snapshot, not a town manifest.')
    for field in ('id', 'seed', 'bounds', 'roads', 'networks', 'premises', 'meters', 'servicePoints'):
        if field not in snapshot:
            raise ValueError('The snapshot is missing map or service data: ' + field)
    for field in ('premises', 'meters', 'servicePoints'):
        if not isinstance(snapshot[field], list):
            raise ValueError('Invalid snapshot collection: ' + field)
    home_ids = [p['id'] for p in snapshot['premises']]
    meter_ids = [m['id'] for m in snapshot['meters']]
    homes, meters = set(home_ids), set(meter_ids)
    if not homes or len(homes) != len(home_ids) or len(meters) != len(meter_ids):
        raise ValueError('Premise and meter identities must be present and unique.')
    linked = set()
    for service in snapshot['servicePoints']:
        if service['commodity'] not in ('electric', 'gas', 'water'):
            raise ValueError('Unsupported physical service. Sewer use derives from water; do not supply a sewer meter.')
        if service['premiseId'] not in homes or service['meterId'] not in meters or service['meterId'] in linked:
            raise ValueError('Each physical service needs a known premise and a unique known meter.')
        linked.add(service['meterId'])
        if not service.get('installationId'):
            raise ValueError('A service installation identity is required.')


def create(library, command, path, environment, start):
    try:
        command = str(uuid.UUID(command))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('A creation command UUID is required.') from exc
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError('Provide the full path to a saved snapshot.')
    if not isinstance(environment, str) or not environment.strip() or len(environment) > 200:
        raise ValueError('Provide a new environment name of at most 200 characters.')
    if not isinstance(start, str) or date.fromisoformat(start).isoformat() != start:
        raise ValueError('Use a canonical YYYY-MM-DD start date.')
    request = canonical({'path': str(Path(path).resolve()), 'environment': environment, 'start': start,
                         'modelVersion': MODEL_VERSION, 'settings': DEFAULTS})
    with library.db() as db:
        row = db.execute('SELECT * FROM world_creations WHERE command=?', (command,)).fetchone()
    if row:
        if row['request'] != request:
            raise ValueError('That creation command belongs to different inputs.')
    else:
        source = Path(path).resolve(strict=True)
        opener = gzip.open if source.suffix.lower() == '.gz' else open
        try:
            with opener(source, 'rb') as stream:
                raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
        except EOFError as exc:
            raise ValueError('The compressed snapshot is incomplete.') from exc
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise ValueError('Snapshot exceeds the 64 MiB uncompressed limit.')
        snapshot = json.loads(raw)
        validate_snapshot(snapshot)
        pinned = canonical(snapshot)
        with library.db() as db:
            # Pin source contents before creating any world; retries never reread a changed source.
            db.execute('INSERT OR IGNORE INTO world_creations VALUES(?,?,?,?,?,?)',
                       (command, request, pinned, hashlib.sha256(pinned.encode()).hexdigest(),
                        uuid.uuid4().hex, 'pending'))
            row = db.execute('SELECT * FROM world_creations WHERE command=?', (command,)).fetchone()
            if row['request'] != request:
                raise ValueError('That creation command belongs to different inputs.')
    return resume(library, row)


def resume(library, row):
    request = json.loads(row['request'])
    if request['modelVersion'] != MODEL_VERSION:
        raise ValueError('Resume this pending request with its recorded world-model version.')
    snapshot = json.loads(row['snapshot'])
    if hashlib.sha256(row['snapshot'].encode()).hexdigest() != row['digest']:
        raise ValueError('Pinned creation snapshot checksum failed.')
    directory = library.path.parent / 'worlds' / row['world_id']
    # Catalog serializes concurrent completions; the source world commit may precede catalog commit.
    with library.db() as db:
        state = db.execute('SELECT state FROM world_creations WHERE command=?', (row['command'],)).fetchone()[0]
        if state == 'complete':
            return {'id': row['world_id'], 'state': 'complete', 'snapshotSha256': row['digest']}
        target = directory / 'world.sqlite'
        if not target.resolve().is_relative_to(library.path.parent.resolve() / 'worlds'):
            raise ValueError('Managed world path leaves its library.')
        directory.mkdir(parents=True, exist_ok=True)
        world = World(target)
        world.initialize(snapshot, request['environment'], request['start'], request['settings'])
        with world.db() as source:
            fingerprint = world.metadata(source)['fingerprint']
        import os
        db.execute('INSERT INTO worlds VALUES(?,?,?)',
                   (row['world_id'], os.path.normcase(str(target.resolve())), fingerprint))
        db.execute("UPDATE world_creations SET state='complete' WHERE command=?", (row['command'],))
    return {'id': row['world_id'], 'state': 'complete', 'snapshotSha256': row['digest']}


def pending(library):
    with library.db() as db:
        rows = db.execute("SELECT command,request FROM world_creations WHERE state='pending' ORDER BY command LIMIT 25").fetchall()
    return [{'commandId': r['command'], **json.loads(r['request'])} for r in rows]


def retry(library, command):
    with library.db() as db:
        row = db.execute('SELECT * FROM world_creations WHERE command=?', (command,)).fetchone()
    if row is None:
        raise ValueError('Unknown creation request.')
    return resume(library, row)
