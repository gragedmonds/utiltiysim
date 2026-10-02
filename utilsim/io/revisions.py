"""Content revisions shared by snapshots and state frames.

* ``topologyRevision``: structural nodes and edges and how they connect (ids, kinds, from/to, loop flag) for all
  three networks. Enabling or disabling a link is state and does not change it; adding, removing or reconnecting an
  edge does.
* ``indexRevision``: the public entity-id mapping (premises, buildings, network nodes and edges, service points,
  meters, registers, accounts, contracts) in snapshot order. Identical for the ``full`` and ``viewer`` profiles."""

from __future__ import annotations

import hashlib

import orjson


def _h(prefix: str, obj) -> str:
    return f"{prefix}-{hashlib.sha256(orjson.dumps(obj)).hexdigest()[:20]}"


def topology_revision(town) -> str:
    data = {}
    for u in ("electric", "water", "gas"):
        net = town.networks[u]
        data[u] = {"nodes": [[nd.id, nd.kind] for nd in net.nodes],
                   "edges": [[e.id, net.nodes[e.a].id, net.nodes[e.b].id, e.kind, bool(e.loop)] for e in net.edges],
                   "source": net.source_id}
    return _h("topo", data)


def index_revision(town) -> str:
    c = town.customers
    data = {
        "premises": list(town.prem.ids),
        "networks": {u: [[nd.id for nd in n.nodes], [e.id for e in n.edges]] for u, n in town.networks.items()},
        "servicePoints": [r["id"] for r in c.service_points] if c else [],
        "meters": [r["id"] for r in c.meters] if c else [],
        "registers": [r["id"] for r in c.registers] if c else [],
        "accounts": [r["id"] for r in c.accounts] if c else [],
        "contracts": [r["id"] for r in c.contracts] if c else [],
    }
    return _h("idx", data)
