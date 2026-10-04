"""Frozen runtime entry point: the app's server (Studio, engine API and job queue). The launcher chooses the storage
folder before starting this process."""
from __future__ import annotations

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-worker', nargs=3)
    parser.add_argument('--store')
    parser.add_argument('--self-test')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--ready-file')
    args = parser.parse_args()
    if args.self_test:
        import uuid

        from utilsim.config.model import SimConfig
        from utilsim.worker.contracts import JobFile, Recipe, recipe_key
        from utilsim.worker.execute import execute
        recipe = Recipe(name='Packaged runtime check', modelId='smoke', homes=40, chunkSize=40,
                        staffing='independent-districts', config=SimConfig().model_dump(mode='json'),
                        request={'asOf': '2026-03-31'}).model_dump()
        job = JobFile(jobId=uuid.uuid4().hex, revision=1, recipeKey=recipe_key(recipe), recipe=recipe).model_dump()
        assert execute(job, Path(args.self_test))['rollup']['complete']
    elif args.batch_worker:
        from utilsim.batch import district_worker
        district_worker(Path(args.batch_worker[0]), int(args.batch_worker[1]), args.batch_worker[2])
    else:
        from utilsim.worker.server import serve
        serve(args.store, args.port, ready_file=args.ready_file)


if __name__ == '__main__':
    main()
