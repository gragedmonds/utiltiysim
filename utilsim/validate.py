"""Town validation: the invariants every generated town must satisfy (also exported in the snapshot)."""

from __future__ import annotations

import numpy as np

from utilsim.core.ids import meter_node_id

CHECKS = [
    "Unique identifiers", "Valid edge endpoints", "Radial topology (edges = nodes - 1)", "Source reachability",
    "All active services connected", "Sizes non-increasing away from source", "Capacity covers design load",
    "Electric voltage stages", "No gas service without gas mains in the district", "Referential integrity",
]


def validate_town(town) -> dict:
    errors: list[str] = []
    seen: set[str] = set()
    total_edges = 0
    prem = town.prem
    for u, net in town.networks.items():
        ids = {nd.id for nd in net.nodes}
        if len(ids) != len(net.nodes):
            errors.append(f"Duplicate node id in {u}")
        children: dict[str, list[str]] = {}
        parents_seen: dict[str, int] = {}
        for e in net.edges:
            total_edges += 1
            a, b = net.nodes[e.a].id, net.nodes[e.b].id
            if a not in ids or b not in ids:
                errors.append(f"Dangling edge {e.id}")
            children.setdefault(a, []).append(b)
            parents_seen[b] = parents_seen.get(b, 0) + 1
            if not np.isfinite(e.length) or e.length < 0:
                errors.append(f"Invalid length {e.id}")
        if len(net.edges) != len(net.nodes) - 1:
            errors.append(f"Not a tree: {u}")
        if any(c > 1 for c in parents_seen.values()):
            errors.append(f"Multiple parents in {u}")
        reached = {net.source_id}
        stack = [net.source_id]
        while stack:
            v = stack.pop()
            for c in children.get(v, []):
                if c not in reached:
                    reached.add(c)
                    stack.append(c)
        missing = [nd.id for nd in net.nodes if nd.id not in reached]
        if missing:
            errors.append(f"{u}: {len(missing)} nodes unreachable from source (e.g. {missing[0]})")
        served = prem.attrs["has_gas"] if u == "gas" else np.ones(len(prem), dtype=bool)
        for i in np.flatnonzero(served):
            if meter_node_id(u, prem.ids[i]) not in reached:
                errors.append(f"Disconnected service {prem.ids[i]} ({u})")
        for e in net.edges:
            if e.kind in ("distribution", "trunk") and not e.attrs.get("loop"):
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
                if nd.kind == "transformer" and nd.attrs["ratingKVA"] * town.cfg.electric.transformer_max_loading \
                        < nd.attrs["designKVA"] - 1e-6 and nd.attrs["phases"] == 1:
                    errors.append(f"electric: {nd.id} overloaded at design")
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
        seen.update(all_ids)
        meters = {m["id"] for m in c.meters}
        insts = {r["id"] for r in c.installations}
        accounts = {r["id"] for r in c.accounts}
        pids = set(prem.ids)
        for sp in c.service_points:
            if sp["premiseId"] not in pids or sp["meterId"] not in meters or sp["installationId"] not in insts:
                errors.append(f"Broken service point {sp['id']}")
        for r in c.registers:
            if r["meterId"] not in meters:
                errors.append(f"Register {r['id']} has no meter")
        for k in c.contracts:
            if k["installationId"] not in insts or k["accountId"] not in accounts:
                errors.append(f"Broken contract {k['id']}")
    return {"valid": not errors, "errors": errors[:200], "errorCount": len(errors),
            "connectedServices": len(c.service_points) if c is not None else None, "networkEdges": total_edges,
            "checks": CHECKS}
