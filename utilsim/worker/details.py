"""Page already-saved district tables; never replay the engine to answer a detail request."""
from __future__ import annotations

import gzip
from pathlib import Path

import orjson
from pydantic import Field

from utilsim.worker.contracts import Strict


class DetailQuery(Strict):
    jobId: str = Field(pattern=r'^[a-f0-9]{32}$')
    runKey: str = Field(pattern=r'^[a-f0-9]{64}$')
    table: str = Field(pattern=r'^[a-zA-Z]+$', max_length=50)
    page: int = Field(default=1, ge=1, le=100_000)
    search: str = Field(default='', max_length=100)


def page(store: Path, query):
    from utilsim.io.run_bundle import read_manifest
    query = DetailQuery.model_validate(query)
    folder = store / 'runs' / query.runKey
    manifest = read_manifest(folder)
    name = 'tables/' + query.table + '.json.gz'
    if name not in {f['name'] for f in manifest['files']}:
        raise ValueError('This revision has no saved table with that name.')
    table = orjson.loads(gzip.decompress((folder / name).read_bytes()))
    needle = query.search.casefold()
    indices = table.get('searchColumns', [])
    rows = [r for r in table['rows'] if not needle or needle in ' '.join(str(r[i] or '') for i in indices).casefold()]
    start = (query.page - 1) * 100
    return {'columns': table['columns'], 'rows': rows[start:start+100], 'page': query.page, 'total': len(rows),
            'table': query.table, 'asOf': table['asOf'], 'runKey': query.runKey}
