"""Town validation: the invariants every generated town must satisfy (also exported in the snapshot)."""

from __future__ import annotations

import numpy as np

CHECKS = [
    "Unique identifiers", "Valid edge endpoints", "Construction forest (one parent edge per non-source node)",
    "Loop edges join existing nodes and are never parent edges", "Every node reachable from a source",
    "Every active service reachable through enabled edges", "Meters resolve by premiseId or servicePointId",
    "Sizes non-increasing away from source", "Capacity covers design load", "Electric voltage stages",
    "Electric radial: no cycles through energized edges; feeder ties explicit and normally open",
    "No gas service without gas mains in the district", "Referential integrity",
]
# Electric equipment stages along the construction forest: supply* → trunk/distribution+ → transformer → service.
_STAGE = {"supply": ((0,), 0), "trunk": ((0, 1), 1), "distribution": ((0, 1), 1), "transformer": ((1,), 2),
          "service": ((2,), 3)}


def _reach(n: int, adj: dict[int, list[int]], sources: list[int]) -> np.ndarray:
    seen = np.zeros(n, dtype=bool)
    stack = list(sources)
    seen[stack] = True
    while stack:
        v = stack.pop()
        for w in adj.get(v, ()):
            if not seen[w]:
                seen[w] = True
                stack.append(w)
    return seen


def _electric_topology(net, sources: list[int]) -> list[str]:
    """Radial operation (enabled edges form a forest; every loop is a normally-open, disabled tie) and valid
    equipment stages from the source to every meter."""
    errors = []
    n = len(net.nodes)
    root = list(range(n))

    def find(x: int) -> int:
        while root[x] != x:
            root[x] = root[root[x]]
            x = root[x]
        return x

    for e in net.edges:
        if e.loop and (e.enabled or not e.normally_open):
            errors.append(f"electric: loop {e.id} is not a normally-open tie")
        if not e.enabled:
            continue
        ra, rb = find(e.a), find(e.b)
        if ra == rb:
            errors.append(f"electric: energized cycle through {e.id}")
        else:
            root[ra] = rb
    stage = np.full(n, -1, dtype=np.int64)
    stage[sources] = 0
    tree = net.tree()
    for lvl in tree.levels[1:]:
        for v in lvl:
            e = net.edges[int(tree.parent_edge[v])]
            ok, nxt = _STAGE.get(e.kind, ((), -1))
            stage[v] = nxt if stage[e.a] in ok else -2
            if stage[e.a] >= 0 and stage[v] == -2:
                errors.append(f"electric: {e.id} ({e.kind}) out of equipment order")
    for k, nd in enumerate(net.nodes):
        if nd.kind == "meter" and stage[k] != 3:
            errors.append(f"electric: meter {nd.id} not fed through supply → primary → transformer → service")
    return errors


def validate_town(town) -> dict:
    errors: list[str] = []
    total_edges = 0
    prem = town.prem
    for u, net in town.networks.items():
        n = len(net.nodes)
        ids = [nd.id for nd in net.nodes]
        if len(set(ids)) != n:
            errors.append(f"Duplicate node id in {u}")
        sources = [k for k, nd in enumerate(net.nodes) if nd.kind == "external_supply"]
        if net.index(net.source_id) not in sources:
            errors.append(f"{u}: sourceId {net.source_id} is not an external_supply node")
        parents = np.zeros(n, dtype=np.int64)
        down: dict[int, list[int]] = {}
        undirected: dict[int, list[int]] = {}
        for e in net.edges:
            total_edges += 1
            if not (0 <= e.a < n and 0 <= e.b < n):
                errors.append(f"Dangling edge {e.id}")
                continue
            if not np.isfinite(e.length) or e.length < 0 or len(e.points) < 2:
                errors.append(f"Invalid geometry {e.id}")
            if e.loop:
                if e.a == e.b:
                    errors.append(f"Self-loop {e.id}")
                if net.nodes[e.b].parent_edge >= 0 and net.edges[net.nodes[e.b].parent_edge] is e:
                    errors.append(f"Loop edge {e.id} used as a parent edge")
            else:
                parents[e.b] += 1
                down.setdefault(e.a, []).append(e.b)
            if e.enabled:
                undirected.setdefault(e.a, []).append(e.b)
                undirected.setdefault(e.b, []).append(e.a)
        non_source = np.ones(n, dtype=bool)
        non_source[sources] = False
        if np.any(parents[non_source] != 1) or np.any(parents[sources] != 0):
            errors.append(f"{u}: construction forest broken (a non-source node without exactly one parent edge)")
        tree_reach = _reach(n, down, sources)
        if not tree_reach.all():
            errors.append(f"{u}: {int((~tree_reach).sum())} nodes unreachable from a source")
        live = _reach(n, undirected, sources)
        meters: dict[str, int] = {}
        for k, nd in enumerate(net.nodes):
            if nd.kind == "meter":
                for key in ("premiseId", "servicePointId"):
                    if nd.attrs.get(key):
                        meters[nd.attrs[key]] = k
        served = prem.attrs["has_gas"] if u == "gas" else np.ones(len(prem), dtype=bool)
        from utilsim.core.ids import service_point_id

        for i in np.flatnonzero(served):
            pid = prem.ids[i]
            k = meters.get(pid, meters.get(service_point_id(pid, u)))
            if k is None:
                errors.append(f"No {u} meter node for {pid}")
            elif not live[k]:
                errors.append(f"Disconnected service {pid} ({u})")
        for e in net.edges:
            if e.kind not in ("distribution", "trunk") or e.loop:
                continue
            pe = net.nodes[e.a].parent_edge
            if pe >= 0:
                par = net.edges[pe]
                same_tier = par.attrs.get("pressureTier") == e.attrs.get("pressureTier")
                if u != "electric" and par.kind in ("distribution", "trunk") and same_tier and \
                        par.size_mm and e.size_mm and par.size_mm < e.size_mm:
                    errors.append(f"{u}: {par.id} ({par.size_mm} mm) feeds larger {e.id} ({e.size_mm} mm)")
                if u == "electric" and par.kind == "distribution" and \
                        par.attrs.get("capacityKVA", 1e9) < e.attrs.get("capacityKVA", 0) - 1e-6:
                    errors.append(f"electric: {par.id} capacity below child {e.id}")
            if u == "electric" and e.attrs.get("capacityKVA", 1e9) < e.attrs.get("designKVA", 0) - 1e-6:
                errors.append(f"electric: {e.id} design {e.attrs['designKVA']} kVA exceeds capacity")
        if u == "electric":
            for nd in net.nodes:
                if nd.kind == "transformer" and nd.attrs["phases"] == 1 and \
                        nd.attrs["ratingKVA"] * town.cfg.electric.transformer_max_loading < nd.attrs["designKVA"] - 1e-6:
                    errors.append(f"electric: {nd.id} overloaded at design")
            errors.extend(_electric_topology(net, sources))
    ae = ~prem.attrs["gas_available"] & prem.attrs["has_gas"]
    if ae.any():
        errors.append(f"{int(ae.sum())} premises have gas in all-electric districts")
    c = town.customers
    if c is not None:
        all_ids = []
        for coll in (c.business_partners, c.accounts, c.service_points, c.meters, c.registers, c.installations,
                     c.contracts):
            all_ids.extend(r["id"] for r in coll)
        all_ids.extend(prem.ids)
        dup = len(all_ids) - len(set(all_ids))
        if dup:
            errors.append(f"{dup} duplicate record ids")
        meters_ = {m["id"] for m in c.meters}
        insts = {r["id"] for r in c.installations}
        accounts = {r["id"] for r in c.accounts}
        pids = set(prem.ids)
        for sp in c.service_points:
            if sp["premiseId"] not in pids or sp["meterId"] not in meters_ or sp["installationId"] not in insts:
                errors.append(f"Broken service point {sp['id']}")
        for r in c.registers:
            if r["meterId"] not in meters_:
                errors.append(f"Register {r['id']} has no meter")
        for k in c.contracts:
            if k["installationId"] not in insts or k["accountId"] not in accounts:
                errors.append(f"Broken contract {k['id']}")
    return {"valid": not errors, "errors": errors[:200], "errorCount": len(errors),
            "connectedServices": len(c.service_points) if c is not None else None, "networkEdges": total_edges,
            "checks": CHECKS}
