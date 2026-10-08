"""Local administrator library of existing worlds. Never migrate or write source worlds."""
from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from utilsim.world.map_view import WorldMap
from utilsim.world.store import MODEL_VERSION, World


class ReadOnlyWorld(World):
    def __init__(self, path, fingerprint=None):
        self.path = Path(path)
        self.fingerprint = fingerprint

    @contextmanager
    def db(self):
        # mode=ro preserves live WAL visibility and refuses to create a missing file.
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            meta = self.metadata(db)
            if meta.get('modelVersion') != MODEL_VERSION or not meta.get('fingerprint'):
                raise ValueError('This file is not a supported initialized world.')
            if self.fingerprint and meta['fingerprint'] != self.fingerprint:
                raise ValueError('World identity changed at this path. Register the replacement explicitly.')
            yield db
        finally:
            db.close()


class WorldLibrary:
    def __init__(self, store):
        self.path = Path(store) / 'world-library.sqlite'
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS worlds '
                       '(id TEXT PRIMARY KEY,path TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL)')
        from .world_creation import schema
        schema(self)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    def register(self, path):
        if not isinstance(path, str) or not path.strip() or len(path) > 4096 or not Path(path).is_absolute():
            raise ValueError('Enter the full path to an existing world SQLite file.')
        source = Path(path).resolve(strict=True)
        if not source.is_file():
            raise ValueError('Choose a world SQLite file.')
        world = ReadOnlyWorld(source)
        with world.db() as db:
            meta = world.metadata(db)
            world._status(db)  # Validate required physical tables before registration.
            db.execute('SELECT 1 FROM observation_delivery_configuration LIMIT 1')
            if not db.execute("SELECT 1 FROM meta WHERE key='snapshot'").fetchone():
                raise ValueError('World has no saved snapshot.')
        canonical = os.path.normcase(str(source))
        with self.db() as db:
            row = db.execute('SELECT * FROM worlds WHERE path=?', (canonical,)).fetchone()
            if row and row['fingerprint'] == meta['fingerprint']:
                return row['id']
            identity = uuid.uuid4().hex
            # Explicit re-registration of a different world retires the old map URL.
            db.execute('DELETE FROM worlds WHERE path=?', (canonical,))
            db.execute('INSERT INTO worlds VALUES(?,?,?)', (identity, canonical, meta['fingerprint']))
            return identity

    def world(self, identity):
        with self.db() as db:
            row = db.execute('SELECT * FROM worlds WHERE id=?', (identity,)).fetchone()
        if not row:
            raise KeyError(identity)
        return ReadOnlyWorld(row['path'], row['fingerprint'])

    def list(self, offset=0, limit=25):
        with self.db() as db:
            total = db.execute('SELECT COUNT(*) FROM worlds').fetchone()[0]
            rows = db.execute('SELECT * FROM worlds ORDER BY id LIMIT ? OFFSET ?', (limit, offset)).fetchall()
        entries = []
        for row in rows:
            entry = {'id': row['id'], 'path': row['path']}
            try:
                entry.update(WorldMap(ReadOnlyWorld(row['path'], row['fingerprint'])).status(), available=True)
            except (OSError, sqlite3.Error, ValueError, KeyError):
                entry.update(available=False, error='World unavailable or changed. Reconnect its drive or register it again.')
            entries.append(entry)
        return {'worlds': entries, 'total': total, 'offset': offset, 'limit': limit}

    def remove(self, identity):
        with self.db() as db:
            return db.execute('DELETE FROM worlds WHERE id=?', (identity,)).rowcount > 0


def mount_world_library(app, store, viewer):
    """The worker's /local/ bearer guard protects every world-data route."""
    library = WorldLibrary(store)
    here = Path(__file__).parent
    world_ui = here.parent / 'world'

    @app.get('/worlds')
    def page():
        return FileResponse(here / 'worlds.html')

    @app.get('/worlds.js')
    def script():
        return FileResponse(here / 'worlds.js', media_type='text/javascript')

    @app.get('/world-map')
    def map_page():
        if not (viewer / 'vendor/three.module.js').is_file():
            raise HTTPException(503, 'Offline map assets are missing from this runtime.')
        return FileResponse(world_ui / 'map.html')

    @app.get('/map.js')
    def map_script():
        return FileResponse(world_ui / 'map.js', media_type='text/javascript')

    @app.get('/local/worlds')
    def listing(offset: int = 0, limit: int = 25):
        if offset < 0 or not 1 <= limit <= 50:
            raise HTTPException(422, 'Use a nonnegative offset and a limit from 1 to 50.')
        return library.list(offset, limit)

    @app.post('/local/worlds')
    async def register(request: Request):
        from utilsim.worker.prepare import body
        value = await body(request)
        try:
            return {'id': library.register(value.get('path'))}
        except (OSError, sqlite3.Error, ValueError, KeyError) as exc:
            raise HTTPException(422, 'Could not open a supported existing world. Check its path and initialization.') from exc

    @app.get('/local/worlds/creations')
    def pending_creations():
        from .world_creation import pending
        return {'pending': pending(library)}

    @app.get('/local/worlds/sources')
    def sources(after: str = '', limit: int = 10):
        from .snapshot_catalog import listing
        try:
            return listing(store, after, limit)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, 'Could not list saved towns. Check the library and page cursor.') from exc

    @app.post('/local/worlds/create')
    async def create_world(request: Request):
        from fastapi.concurrency import run_in_threadpool

        from .prepare import body
        from .world_creation import create
        value = await body(request)
        try:
            return await run_in_threadpool(create, library, value.get('commandId'), value.get('path'),
                                           value.get('environment'), value.get('start'), run_key=value.get('runKey'))
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, 'Could not create this world. Check the full snapshot, name and date; retry a pending request after recovery.') from exc

    @app.post('/local/worlds/creations/{command}/retry')
    def retry_creation(command: str):
        from .world_creation import retry
        try:
            return retry(library, command)
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(409, 'Creation remains pending. Check source integrity and storage availability.') from exc

    @app.delete('/local/worlds/{identity}')
    def remove(identity: str):
        if not library.remove(identity):
            raise HTTPException(404, 'World entry not found.')
        return {'removed': True, 'sourceDeleted': False}

    @app.get('/local/worlds/{identity}/map/{operation}')
    def query(identity: str, operation: str, request: Request):
        try:
            view = WorldMap(library.world(identity))
            params = list(request.query_params.multi_items())
            if operation == 'snapshot' and not params:
                return view.snapshot()
            if operation == 'status' and not params:
                return view.status()
            if operation == 'premise' and len(params) == 1 and params[0][0] == 'id':
                return view.premise(params[0][1])
            raise HTTPException(422, 'Use snapshot, status or one premise ID.')
        except KeyError as exc:
            raise HTTPException(404, 'World entry not found.') from exc
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise HTTPException(409, 'World unavailable or changed. Reconnect its drive or register it again.') from exc

    app.mount('/viewer', StaticFiles(directory=viewer), name='world-viewer')
