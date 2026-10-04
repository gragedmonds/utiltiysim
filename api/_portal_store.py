"""Durable control-plane documents. SQLite for a local portal, Redis REST for Vercel."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import httpx
import orjson


class StoreUnavailable(RuntimeError):
    pass


class Documents:
    def __init__(self, path=None, url=None, token=None):
        self.path, self.url, self.token = path, url, token
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with self.connection() as c:
                c.execute('CREATE TABLE IF NOT EXISTS documents (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    def connection(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.execute('PRAGMA busy_timeout=15000')
        return c

    def command(self, *args):
        try:
            r = httpx.post(self.url, headers={'Authorization': 'Bearer ' + self.token}, json=list(args), timeout=15)
            r.raise_for_status()
            body = r.json()
            if body.get('error'):
                raise StoreUnavailable('Shared storage rejected the request.')
            return body['result']
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise StoreUnavailable('Shared storage is unavailable. Your saved work has not been changed.') from exc

    def get(self, key):
        if self.path:
            with self.connection() as c:
                row = c.execute('SELECT value FROM documents WHERE key=?', (key,)).fetchone()
                raw = row[0] if row else None
        else:
            raw = self.command('GET', 'utilsim:' + key)
        return orjson.loads(raw) if raw else None

    def update(self, key, change):
        """Apply a pure transform atomically. Redis retries CAS conflicts; no expiring mutex."""
        if self.path:
            with self.connection() as c:
                c.execute('BEGIN IMMEDIATE')
                row = c.execute('SELECT value FROM documents WHERE key=?', (key,)).fetchone()
                current = orjson.loads(row[0]) if row else None
                value, result = change(current)
                c.execute('INSERT INTO documents VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                          (key, orjson.dumps(value).decode()))
                return result
        script = "if (redis.call('GET',KEYS[1]) or '') ~= ARGV[1] then return 0 end redis.call('SET',KEYS[1],ARGV[2]); return 1"
        for _ in range(12):
            old = self.command('GET', 'utilsim:' + key) or ''
            value, result = change(orjson.loads(old) if old else None)
            raw = orjson.dumps(value).decode()
            if len(raw) > 12_000_000:
                raise ValueError('Workspace metadata is full. Export completed results and start a new workspace.')
            if self.command('EVAL', script, 1, 'utilsim:' + key, old, raw):
                return result
        raise StoreUnavailable('Workspace is busy. Try again.')

    def rate(self, key, limit, seconds=600):
        if self.path:
            now = time.time()
            def increment(old):
                value = old if old and old['until'] > now else {'count': 0, 'until': now + seconds}
                value['count'] += 1
                return value, value['count'] <= limit
            return self.update('rate:' + key, increment)
        script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end return n"
        return self.command('EVAL', script, 1, 'utilsim:rate:' + key, seconds) <= limit


def configured_store():
    url = os.getenv('UPSTASH_REDIS_REST_URL') or os.getenv('KV_REST_API_URL')
    token = os.getenv('UPSTASH_REDIS_REST_TOKEN') or os.getenv('KV_REST_API_TOKEN')
    if url and token:
        return Documents(url=url, token=token)
    path = os.getenv('UTILSIM_PORTAL_DB')
    if path or not os.getenv('VERCEL'):
        return Documents(path=path or 'out/portal.sqlite3')
    raise StoreUnavailable('Connect Upstash Redis to enable pairing and job sync. Manual job files are available meanwhile.')
