"""Execute portable recipes without internet; only result receipts need syncing."""
from __future__ import annotations

import hashlib
from pathlib import Path

import orjson

from utilsim.worker.contracts import ResultFile, check_job


def execute(job, store: Path, on_progress=lambda _: None, should_pause=lambda: False):
    from utilsim.batch import run_batch, write_json
    from utilsim.config.model import SimConfig
    from utilsim.io.run_bundle import read_manifest

    job = check_job(job)
    recipe = job['recipe']
    store = Path(store).resolve()
    # Never silently fall back to a different volume if removable storage disappears.
    if not store.is_dir():
        raise OSError('Storage drive unavailable. Reconnect the selected drive to continue.')
    directory, batch = run_batch(SimConfig.model_validate(recipe['config']), recipe['homes'], store,
                                 recipe['request'], chunk_size=recipe['chunkSize'], staffing=recipe['staffing'],
                                 on_progress=on_progress, should_pause=should_pause)
    if batch['status'] != 'complete':
        return None
    districts = []
    for d in batch['districts']:
        folder = store / 'runs' / d['result']['runKey']
        read_manifest(folder)
        districts.append({'id': d['id'], 'runKey': d['result']['runKey'], 'homes': d['homes'],
                          'manifestSha256': hashlib.sha256((folder / 'manifest.json').read_bytes()).hexdigest()})
    result = ResultFile(jobId=job['jobId'], recipeKey=job['recipeKey'], revision=job['revision'],
                        engineBuild=batch['inputs']['engineBuild'], districts=districts,
                        rollup={k: v for k, v in orjson.loads((directory / 'rollup.json').read_bytes()).items() if k != 'daily'},
                        timings=orjson.loads((directory / 'timings.json').read_bytes())).model_dump()
    outbox = store / 'results'
    outbox.mkdir(exist_ok=True)
    write_json(outbox / (job['jobId'] + '.result.json'), result)
    return result
