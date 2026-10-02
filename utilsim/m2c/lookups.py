"""Lookups for the Utility Studio query screens, as of a date: an installation's billing record, a meter-reading
document, and possible entries (F4) for installation, read, account and premise ids.

Every payload is bounded: an installation carries one year of its own documents, invoices and reads, a read document
is one read, and possible entries are paged (at most ``PAGE_MAX`` per page).
"""

from __future__ import annotations

import numpy as np

from utilsim.m2c.base import date_of
from utilsim.m2c.run import M2CRun
from utilsim.m2c.views import (
    _row,
    as_of_t,
    decision,
    doc_json,
    hold_json,
    invoice_json,
    missing_cause,
    order_brief,
    read_record,
    read_type,
    vee_status,
)

ENTRY_KINDS = ("installation", "read", "account", "premise")
PAGE_MAX = 50


def _head(run: M2CRun, day: int, version: str) -> dict:
    return {"schemaVersion": version, "simulationId": run.simulation_id, "asOf": date_of(day).isoformat()}


def _account(run: M2CRun, acct: str, T: float) -> dict:
    """An account with its business partner, balance, ledger to date and any invoice hold."""
    tw, bk = run.town, run.books
    meta = tw.accounts.get(acct, {})
    bp = meta.get("businessPartnerId")
    hold = run.hold_on(acct, T)
    return {"accountId": acct, **meta, "businessPartner": {"businessPartnerId": bp, **tw.partners.get(bp, {})}
            if bp else None, "balance": bk.balance(acct, T),
            "ledger": [{"at": run.iso(t), "type": k, "amount": amt, "ref": ref}
                       for t, k, amt, ref in bk.ledger.get(acct, []) if t <= T],
            "invoiceHold": hold_json(run, hold, T) if hold is not None else None}


def installation(run: M2CRun, installation_id: str, *, as_of: str | None = None, truth: bool = False) -> dict:
    """``m2c-installation/1.0``: the installation (premise, commodity, rate category, meters and registers), its
    contracts with account and business partner, billing documents (with lines), invoices, the accounts' ledgers,
    its read results and its cases, as of ``as_of``. KeyError for an unknown id."""
    tw, bk = run.town, run.books
    k = tw.inst_index.get(installation_id)
    if k is None:
        raise KeyError(installation_id)
    day, T = as_of_t(run, as_of)
    asof = date_of(day).isoformat()
    rows = [int(r) for r in tw.inst_rows[k]]
    r0 = int(bk.main[k]) if bk.main[k] >= 0 else rows[0]
    p = int(tw.prem[r0])
    meta = tw.inst_meta[k]
    meters: dict[int, dict] = {}
    for r in rows:
        mi = int(tw.meter_of[r])
        meters.setdefault(mi, {"meterId": tw.meter_ids[mi], "technology": str(tw.tech[r]), "registers": []})[
            "registers"].append({"registerId": tw.reg_ids[r], "direction": str(tw.direction[r]),
                                 "unit": str(tw.unit[r]), "digits": int(tw.digits[r]),
                                 "multiplier": int(tw.multiplier[r])})
    contracts = []
    for c in tw.inst_contracts[k]:
        if (c.get("validFrom") or "")[:10] > asof:
            continue  # a move-in later in the year
        contracts.append({"contractId": c["id"], "accountId": c["accountId"], "validFrom": c.get("validFrom"),
                          "validTo": c.get("validTo"), "status": c.get("status"),
                          "current": not c.get("validTo") or c["validTo"][:10] > asof})
    docs = [d for d in bk.docs if d["inst"] == k and d["created"] <= T]
    mine = {d["k"] for d in docs}
    invoices = [inv for inv in bk.invoices if inv["created"] <= T and mine.intersection(inv["docs"])]
    return {**_head(run, day, "m2c-installation/1.0"), "installationId": installation_id,
            "premiseId": tw.premise_ids[p], "address": tw.address[p], "commodity": str(tw.commodity[r0]),
            "servicePointId": tw.service_point[r0], "division": meta.get("division"),
            "rateCategory": bk.rate_at(k, T), "masterRateCategory": tw.inst_rate[k],
            "billingClass": meta.get("billingClass"), "mruId": tw.mru[r0], "portion": int(tw.portion[r0]),
            "status": meta.get("status"), "meters": list(meters.values()), "contracts": contracts,
            "accounts": [_account(run, a, T) for a in dict.fromkeys(c["accountId"] for c in contracts)],
            "billingDocuments": [doc_json(run, d, T, truth) for d in docs],
            "invoices": [invoice_json(run, inv, T) for inv in invoices],
            "reads": [read_record(run, r, m, T, truth) for r in rows for m in range(1, 13) if run.read_t[r, m] <= T],
            "cases": [_row(run, c, T) for c in run.cases if c.created <= T and int(tw.inst_of[c.r]) == k
                      and c.work != "hold"]}


def read_document(run: M2CRun, read_id: str, *, as_of: str | None = None, truth: bool = False) -> dict:
    """``m2c-read-document/1.0``: one meter-reading result (``meter-read/1.1``), its VEE decision, the installation,
    contract, account and business partner it bills to, its case and field service order, and the register's other
    reads to date. KeyError for an unknown read, or one not taken yet as of ``as_of``."""
    tw = run.town
    r, m = tw.find_read(read_id)
    day, T = as_of_t(run, as_of)
    if run.read_t[r, m] > T:
        raise KeyError(read_id)
    rec = read_record(run, r, m, T, truth)
    p = int(tw.prem[r])
    c = int(run.case_of[r, m])
    case = run.cases[c] if c >= 0 and run.cases[c].created <= T else None
    mine = set(case.orders) if case is not None else set()
    order = next((o for o in run.orders.values() if o.case is not None and o.created <= T
                  and (o.id in mine or (o.r, o.m) == (r, m))), None)
    acct = rec["accountId"]
    return {**_head(run, day, "m2c-read-document/1.0"), "readId": read_id, "read": rec,
            "decision": decision(run, r, m), "installationId": rec["installationId"],
            "contractId": rec["contractId"], "accountId": acct,
            "businessPartnerId": tw.accounts.get(acct, {}).get("businessPartnerId"), "premiseId": tw.premise_ids[p],
            "address": tw.address[p], "meterId": rec["meterId"], "registerId": rec["registerId"],
            "case": _row(run, case, T) if case is not None else None,
            "order": order_brief(run, order, T) if order is not None else None,
            "history": [{"readId": run.read_id(r, j), "readDate": date_of(int(tw.read_day[r, j])).isoformat(),
                         "readType": read_type(run, r, j, T), "registerValue": _value(run, r, j, T),
                         "veeStatus": vee_status(run, r, j, T), "cause": missing_cause(run, r, j)}
                        for j in range(12, 0, -1) if run.read_t[r, j] <= T]}


def _value(run: M2CRun, r: int, m: int, T: float) -> float | None:
    """The register value billing uses as of ``T``: the released value once released, else the observation."""
    v = run.released[r, m] if run.release_t[r, m] <= T else run.obs[r, m]
    return None if not np.isfinite(v) else round(float(v), 3)


def possible_entries(run: M2CRun, kind: str, query: str = "", *, as_of: str | None = None, page: int = 1,
                     page_size: int = 20) -> dict:
    """``m2c-possible-entries/1.0``: F4 matches for an id field (``kind``), by id or short text (case-insensitive
    substring), paged. Reads are those taken by ``as_of``, newest first."""
    if kind not in ENTRY_KINDS:
        raise ValueError(f"kind must be one of {', '.join(ENTRY_KINDS)}")
    page_size = min(max(1, page_size), PAGE_MAX)
    page = max(1, page)
    tw = run.town
    day, T = as_of_t(run, as_of)
    q = (query or "").strip().lower()
    entries: list[tuple[str, str]] = []
    if kind == "premise":
        entries = [(pid, tw.address[i]) for i, pid in enumerate(tw.premise_ids)]
    elif kind == "installation":
        for k, iid in enumerate(tw.inst_ids):
            r = int(tw.inst_rows[k][0])
            entries.append((iid, f"{tw.address[tw.prem[r]]} · {tw.commodity[r]} · {tw.inst_rate[k]}"))
    elif kind == "account":
        for acct, meta in tw.accounts.items():
            bp = tw.partners.get(meta.get("businessPartnerId") or "", {})
            p = tw.premise_index.get(meta.get("premiseId") or "")
            entries.append((acct, " · ".join(str(x) for x in (bp.get("name"), tw.address[p] if p is not None else None,
                                                               meta.get("sapContractAccount")) if x)))
    if kind != "read":
        hits = [e for e in entries if not q or q in e[0].lower() or q in e[1].lower()]
        total, rows = len(hits), hits[(page - 1) * page_size: page * page_size]
        out = [{"id": i, "text": t} for i, t in rows]
    else:
        total, out = _read_entries(run, q, T, page, page_size)
    return {**_head(run, day, "m2c-possible-entries/1.0"), "kind": kind, "query": query or "", "total": total,
            "page": page, "pageSize": page_size, "entries": out}


def _read_entries(run: M2CRun, q: str, T: float, page: int, page_size: int) -> tuple[int, list[dict]]:
    """Reads taken by ``T``, newest month first, matching ``q`` on the read id or the register's meter, premise,
    installation or address."""
    tw = run.town
    taken = run.read_t[:, 1:] <= T  # (R, 12)
    if q:
        reg_hit = np.array([q in f"{tw.reg_ids[r]} {tw.meter_ids[tw.meter_of[r]]} {tw.premise_ids[tw.prem[r]]} "
                                 f"{tw.installation[r]} {tw.address[tw.prem[r]]}".lower()
                            for r in range(tw.n_registers)], dtype=bool)
        hit = taken & reg_hit[:, None]
        if "read-" in q or any(ch.isdigit() for ch in q):  # a read id or a date: match the read ids themselves
            for r, j in zip(*np.nonzero(taken & ~hit), strict=True):
                if q in run.read_id(int(r), int(j) + 1).lower():
                    hit[r, j] = True
    else:
        hit = taken
    total = int(hit.sum())
    out, skip = [], (page - 1) * page_size
    for j in range(11, -1, -1):  # newest month first, then register order
        rows = np.flatnonzero(hit[:, j])
        if skip >= len(rows):
            skip -= len(rows)
            continue
        for r in rows[skip: skip + page_size - len(out)].tolist():
            m = j + 1
            out.append({"id": run.read_id(r, m),
                        "text": f"{date_of(int(tw.read_day[r, m])).isoformat()} · {tw.meter_ids[tw.meter_of[r]]} · "
                                f"{tw.address[tw.prem[r]]} · {tw.commodity[r]}"})
        skip = 0
        if len(out) >= page_size:
            break
    return total, out
