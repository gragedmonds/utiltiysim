"""Refresh the bundled map for saved-result readers that have no running engine."""
from pathlib import Path

import orjson

from utilsim.config.dependencies import dependency_graph

if __name__ == '__main__':
    path = Path(__file__).resolve().parents[1] / 'packages/town-viewer/dist/dependency-graph.json'
    path.write_bytes(orjson.dumps(dependency_graph(), option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE))
    print(path)
