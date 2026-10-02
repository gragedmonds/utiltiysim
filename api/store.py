"""In-process town store: builds are deterministic, so a town is fully identified by its config; generated towns
are kept in an LRU and their snapshots cached on disk under ``.utilsim_cache/{townId}/``."""

from __future__ import annotations

import gzip
import os
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import orjson

from utilsim.config.model import SimConfig

SERVERLESS = bool(os.environ.get("VERCEL"))  # a function invocation cannot leave a build running after it returns
CACHE_DIR = Path(os.environ.get("UTILSIM_CACHE", "/tmp/utilsim-cache" if SERVERLESS else ".utilsim_cache"))
SYNC_LIMIT = int(os.environ.get("UTILSIM_SYNC_HOUSES", str(10**9) if SERVERLESS else "2000"))
MAX_TOWNS = int(os.environ.get("UTILSIM_MAX_TOWNS", "4"))


class TownStore:
    def __init__(self):
        self._towns: OrderedDict[str, object] = OrderedDict()
        self._snap_gz: dict[str, bytes] = {}
        self._jobs: dict[str, Future] = {}
        self._errors: dict[str, str] = {}
        self._configs: dict[str, SimConfig] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1)

    def submit(self, cfg: SimConfig) -> tuple[str, str]:
        tid = cfg.town_id()
        with self._lock:
            self._configs[tid] = cfg
            if tid in self._towns:
                return tid, "ready"
            if tid in self._jobs and not self._jobs[tid].done():
                return tid, "building"
        if cfg.town.houses <= SYNC_LIMIT:
            self._build(tid, cfg)
            return tid, "ready" if tid in self._towns else "failed"
        with self._lock:
            self._jobs[tid] = self._pool.submit(self._build, tid, cfg)
        return tid, "building"

    def build(self, cfg: SimConfig) -> str:
        """Build ``cfg`` now (in this request) unless it is ready; returns its status."""
        tid = cfg.town_id()
        with self._lock:
            self._configs[tid] = cfg
        if tid not in self._towns:
            self._build(tid, cfg)
        return self.status(tid)

    def config(self, tid: str) -> SimConfig | None:
        return self._configs.get(tid)

    def _build(self, tid: str, cfg: SimConfig) -> None:
        try:
            from utilsim.gen.pipeline import generate  # the generation stack, loaded on first use

            town = generate(cfg)
            with self._lock:
                self._towns[tid] = town
                self._towns.move_to_end(tid)
                while len(self._towns) > MAX_TOWNS:
                    old, _ = self._towns.popitem(last=False)
                    for k in [k for k in self._snap_gz if k.startswith(old + ":")]:
                        self._snap_gz.pop(k, None)
            self._errors.pop(tid, None)
        except Exception as exc:  # surfaced through status
            self._errors[tid] = f"{type(exc).__name__}: {exc}"

    def status(self, tid: str) -> str:
        if tid in self._towns:
            return "ready"
        if tid in self._errors:
            return "failed"
        if tid in self._jobs and not self._jobs[tid].done():
            return "building"
        if tid in self._configs:
            return "evicted"
        return "unknown"

    def ready(self) -> list[dict]:
        """Generated towns in memory, oldest first: ``{townId, name, seed, houses}``."""
        with self._lock:
            towns = list(self._towns.items())
        return [{"townId": tid, "name": t.cfg.name, "seed": t.cfg.seeds.master, "houses": t.cfg.town.houses}
                for tid, t in towns]

    def error(self, tid: str) -> str | None:
        return self._errors.get(tid)

    def get(self, tid: str):
        town = self._towns.get(tid)
        if town is None and tid in self._configs and self.status(tid) == "evicted":
            self._build(tid, self._configs[tid])
            town = self._towns.get(tid)
        return town

    def snapshot_gz(self, tid: str, profile: str = "full") -> bytes:
        key = f"{tid}:{profile}"
        if key in self._snap_gz:
            return self._snap_gz[key]
        path = CACHE_DIR / tid / f"snapshot-{profile}.json.gz"
        if path.exists():
            data = path.read_bytes()
        else:
            town = self.get(tid)
            from utilsim.io.snapshot import build_snapshot

            data = gzip.compress(orjson.dumps(build_snapshot(town, detail=profile)), 6, mtime=0)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except OSError:
                pass
        self._snap_gz[key] = data
        return data

    def snapshot(self, tid: str) -> dict:
        return orjson.loads(gzip.decompress(self.snapshot_gz(tid)))


store = TownStore()
