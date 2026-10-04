"""Flat tables of a town and its meter-to-cash run, as of a date: the Studio's Data pages and their CSV exports.

A table is columns (key, label, kind, facet, link) and rows. Master data (premises, business partners, accounts,
contracts, service points, meters, registers, installations, tariffs, MRUs, read schedules) comes from the town
snapshot; run data (reads, usage, billing documents, invoices, payments, the ledger, dunning, collections, cases,
field orders, device changes, interruptions) from the finished run *as of* a date, so a table never shows an event
the run has not reached. A request filters a table (facet values, a text search, a date prefix, a number range),
sorts it by one column and returns one page: at most PAGE_MAX rows as JSON and CSV_MAX rows as CSV, so a whole
table downloads in pages. Nothing here decides anything: every value is the run's own.
"""

from __future__ import annotations

import csv
import io
from collections import Counter, OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np

from utilsim.m2c import catalog as cat
from utilsim.m2c import collections as colls
from utilsim.m2c import views
from utilsim.m2c.base import date_of
from utilsim.m2c.run import INF, METHODS, OFF, M2CRun

TABLE_VERSION = "m2c-table/1.0"
CATALOG_VERSION = "m2c-tables/1.0"
PAGE_MAX = 500
CSV_MAX = 5000
FACET_MAX = 40
CACHE = 8  # built tables kept per run (one per table and view date)
KINDS = ("text", "id", "int", "num", "money", "pct", "date", "datetime", "time", "bool")
LINKS = ("premise", "installation", "read", "account", "invoice", "case", "order")
MASTER_KEYS = ("premises", "businessPartners", "accounts", "servicePoints", "meters", "registers", "installations",
               "contracts", "tariffAssignments", "tariffs", "mrus", "portions", "readSchedules")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
MONTH_LABELS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# Collections phases, from the least to the most advanced; an account is in the furthest one that applies.
PHASES = ("current", "overdue", "reminder", "overdue notice", "winter moratorium", "dunning hold",
          "payment arrangement", "disconnection notice", "disconnected")


@dataclass(frozen=True)
class Col:
    key: str
    label: str
    kind: str = "text"
    facet: bool = False
    link: str | None = None  # the record a value opens (LINKS)
    unit: str | None = None
    search: bool = False  # part of the row's search text
    hint: str | None = None

    def json(self) -> dict:
        out = {"key": self.key, "label": self.label, "kind": self.kind}
        if self.facet:
            out["facet"] = True
        if self.link:
            out["link"] = self.link
        if self.unit:
            out["unit"] = self.unit
        if self.hint:
            out["hint"] = self.hint
        return out


@dataclass
class Table:
    cols: list[Col]
    data: list[list]  # column-major: data[j] holds column j, one Python value per row
    facets: dict[str, list[dict]] = field(default_factory=dict)
    blob: list[str] = field(default_factory=list)  # lower-case search text per row
    orders: dict[tuple[str, bool], list[int]] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.data[0]) if self.data else 0


@dataclass(frozen=True)
class Spec:
    name: str
    title: str
    group: str
    source: str  # town | run | both
    description: str
    cols: tuple[Col, ...]
    build: Callable[[SimpleNamespace], list[list]]

    def json(self) -> dict:
        return {"name": self.name, "title": self.title, "group": self.group, "source": self.source,
                "description": self.description, "columns": [c.json() for c in self.cols]}


GROUPS = (("customers", "Customers"), ("metering", "Meters & reading"), ("billing", "Billing & pricing"),
          ("collections", "Collections"), ("contact", "Contact centre"), ("field", "Field work"), ("work", "Work"))


# ---- value helpers ----------------------------------------------------------------------------------------------
_DATES: dict[int, str] = {}


def _d(day) -> str | None:
    """ISO date of a run day (a float time's local day); None for missing or never."""
    if day is None:
        return None
    x = float(day)
    if x != x or x == INF or x == -INF:
        return None
    k = int(np.floor(x))
    s = _DATES.get(k)
    if s is None:
        s = _DATES[k] = date_of(k).isoformat()
    return s


def _hm(t) -> str | None:
    if t is None or t != t:
        return None
    h = (float(t) - np.floor(float(t))) * 24.0
    return f"{int(h):02d}:{int(round((h - int(h)) * 60)) % 60:02d}"


def _days(arr) -> list:
    return [_d(x) for x in np.asarray(arr, dtype=float).tolist()]


def _nums(arr, nd: int | None = 3) -> list:
    out = np.asarray(arr, dtype=float)
    vals = (np.round(out, nd) if nd is not None else out).tolist()
    return [None if x != x or x in (INF, -INF) else x for x in vals]


def _ints(arr) -> list:
    return [int(x) for x in np.asarray(arr).tolist()]


def _strs(arr) -> list:
    return [str(x) for x in np.asarray(arr).tolist()]


def _pick(seq, idx) -> list:
    return np.asarray(list(seq), dtype=object)[np.asarray(idx, dtype=np.int64)].tolist()


def _date10(s) -> str | None:
    return str(s)[:10] if s else None


def _money(x) -> float | None:
    return None if x is None else round(float(x), 2)


def _text(v) -> str:
    if v is None:
        return ""
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v)


# ---- master data (the snapshot's customer and meter tables) ------------------------------------------------------
def master_data(snap: dict) -> dict:
    """The snapshot lists the tables read, plus the indexes that join them (kept small: no geometry)."""
    m = {k: list(snap.get(k) or []) for k in MASTER_KEYS}
    m["id"] = snap["id"]
    m["premise_by_id"] = {p["id"]: p for p in m["premises"]}
    m["account_by_id"] = {a["id"]: a for a in m["accounts"]}
    m["partner_by_id"] = {b["id"]: b for b in m["businessPartners"]}
    acc_of_bp: dict[str, list[dict]] = {}
    for a in m["accounts"]:
        acc_of_bp.setdefault(a.get("businessPartnerId"), []).append(a)
    m["accounts_of_partner"] = acc_of_bp
    m["sp_by_id"] = {s["id"]: s for s in m["servicePoints"]}
    m["meter_by_id"] = {x["id"]: x for x in m["meters"]}
    m["inst_by_id"] = {x["id"]: x for x in m["installations"]}
    assign: dict[str, dict] = {}
    for a in m["tariffAssignments"]:
        assign[a["contractId"]] = a  # the last assignment listed wins (one per contract today)
    m["assign_by_contract"] = assign
    ctr_of_inst: dict[str, list[dict]] = {}
    for c in m["contracts"]:
        ctr_of_inst.setdefault(c["installationId"], []).append(c)
    m["contracts_of_inst"] = ctr_of_inst
    m["mru_by_id"] = {x["id"]: x for x in m["mrus"]}
    m["portion_of_mru"] = {mid: p for p in m["portions"] for mid in p.get("mruIds", [])}
    return m


def _address(c, premise_id) -> str | None:
    p = c.master["premise_by_id"].get(premise_id)
    return p.get("address") if p else None


def _partner_name(c, account_id) -> str | None:
    a = c.master["account_by_id"].get(account_id)
    bp = c.master["partner_by_id"].get(a.get("businessPartnerId")) if a else None
    return bp.get("name") if bp else None


def _cols(*rows: list) -> list[list]:
    """Row-major → column-major."""
    return [list(col) for col in zip(*rows)] if rows else []


def _empty(spec_cols: tuple[Col, ...]) -> list[list]:
    return [[] for _ in spec_cols]


def _rows_to_cols(cols: tuple[Col, ...], rows: list[list]) -> list[list]:
    return _cols(*rows) if rows else _empty(cols)


# ---- customers -------------------------------------------------------------------------------------------------
PREMISES = (Col("premiseId", "Premise", "id", link="premise", search=True), Col("address", "Address", search=True),
            Col("street", "Street", facet=True), Col("premiseType", "Type", facet=True),
            Col("buildingType", "Building", facet=True), Col("occupied", "Occupied", "bool", facet=True),
            Col("occupants", "Occupants", "int"), Col("yearBuilt", "Built", "int"), Col("era", "Era", facet=True),
            Col("stories", "Stories", "int"), Col("floorAreaM2", "Floor area", "num", unit="m²"),
            Col("lotAreaM2", "Lot", "num", unit="m²"), Col("heatingFuel", "Heating", facet=True),
            Col("electricHeat", "Electric heat", "bool"), Col("hasAC", "A/C", "bool"), Col("hasEV", "EV", "bool"),
            Col("hasPool", "Pool", "bool"), Col("solar", "Solar", "bool", facet=True),
            Col("solarKW", "Solar", "num", unit="kW"), Col("tenure", "Tenure", facet=True),
            Col("meterTechnology", "Meter tech", facet=True), Col("mruId", "MRU", facet=True),
            Col("districtId", "District", facet=True), Col("accountId", "Account", "id", link="account", search=True),
            Col("businessPartner", "Customer", search=True), Col("dailyKWh", "Daily electric", "num", unit="kWh"),
            Col("dailyWaterM3", "Daily water", "num", unit="m³"), Col("dailyGasM3", "Daily gas", "num", unit="m³"),
            Col("moveInAt", "Move in", "date"), Col("moveOutAt", "Move out", "date"))


def b_premises(c) -> list[list]:
    rows = []
    for p in c.master["premises"]:
        rows.append([p["id"], p.get("address"), p.get("street"), p.get("premiseType"), p.get("buildingType"),
                     bool(p.get("occupied")), p.get("occupants"), p.get("yearBuilt"), p.get("era"), p.get("stories"),
                     p.get("floorAreaM2"), p.get("lotAreaM2"), p.get("heatingFuel"), p.get("electricHeat"),
                     p.get("hasAC"), p.get("hasEV"), p.get("hasPool"), bool(p.get("solar")), p.get("solarKW"),
                     p.get("tenure"), p.get("meterTechnology"), p.get("mruId"), p.get("districtId"),
                     p.get("accountId"), _partner_name(c, p.get("accountId")), p.get("dailyKWh"),
                     p.get("dailyWaterM3"), p.get("dailyGasM3"), _date10(p.get("moveInAt")),
                     _date10(p.get("moveOutAt"))])
    return _rows_to_cols(PREMISES, rows)


PARTNERS = (Col("businessPartnerId", "Business partner", "id", search=True), Col("name", "Name", search=True),
            Col("kind", "Kind", facet=True), Col("since", "Customer since", "date"),
            Col("paymentProfile", "Payer profile", facet=True), Col("sapPartner", "SAP partner", "id", search=True),
            Col("accountId", "Account", "id", link="account", search=True),
            Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
            Col("paymentMethod", "Payment method", facet=True))


def b_partners(c) -> list[list]:
    rows = []
    for b in c.master["businessPartners"]:
        accts = c.master["accounts_of_partner"].get(b["id"], [])
        a = accts[0] if accts else {}
        rows.append([b["id"], b.get("name"), b.get("kind"), b.get("since"), b.get("paymentProfile"),
                     b.get("sapPartner"), a.get("id"), a.get("premiseId"), _address(c, a.get("premiseId")),
                     a.get("paymentMethod")])
    return _rows_to_cols(PARTNERS, rows)


ACCOUNTS = (Col("accountId", "Account", "id", link="account", search=True), Col("name", "Customer", search=True),
            Col("businessPartnerId", "Business partner", "id"), Col("premiseId", "Premise", "id", link="premise"),
            Col("address", "Address", search=True), Col("paymentMethod", "Payment method", facet=True),
            Col("paymentProfile", "Payer profile", facet=True), Col("sapContractAccount", "SAP contract account",
                                                                      "id", search=True),
            Col("validFrom", "Valid from", "date"), Col("validTo", "Valid to", "date"),
            Col("contracts", "Contracts", "int"), Col("invoices", "Invoices", "int"),
            Col("openInvoices", "Open invoices", "int"), Col("balance", "Balance", "money"),
            Col("overdue", "Overdue", "money"), Col("phase", "Collections phase", facet=True),
            Col("lastDunning", "Last dunning", facet=True), Col("lastDunningAt", "Last dunning on", "date"),
            Col("budgetBilling", "Budget billing", facet=True), Col("lowIncome", "Low income", facet=True))


def _phase(col: colls.Collections, A: colls.Account, T: float) -> str:
    unpaid = [inv for inv in A.invs if inv["issued"] <= T and not colls.is_paid(inv, T)]
    states = [colls.disconnect_state(inv, T) for inv in unpaid]
    if "disconnected" in states:
        return "disconnected"
    if any(s in ("pending", "approved") for s in states):
        return "disconnection notice"
    if col.active_arrangement(A, T):
        return "payment arrangement"
    if col.hold_on(A, T):
        return "dunning hold"
    if any(inv.get("moratorium") is not None and inv["moratorium"] <= T for inv in unpaid):
        return "winter moratorium"
    steps = {k for inv in unpaid for t, k in inv["dunning"] if t <= T and k in colls.STEPS}
    if "DISCONNECT_NOTICE" in steps:
        return "disconnection notice"
    if "DUNNING_NOTICE" in steps:
        return "overdue notice"
    if "DUNNING_REMINDER" in steps:
        return "reminder"
    if any(colls.is_overdue(inv, T) for inv in unpaid):
        return "overdue"
    return "current"


def _account_at(c, A: colls.Account | None, T: float) -> dict:
    """Collections figures of an account as of T (zeros for an account without invoices yet)."""
    if A is None:
        return {"invoices": 0, "open": 0, "overdue": 0.0, "phase": "current", "last": None, "lastAt": None,
                "budget": None, "lowIncome": None}
    invs = [inv for inv in A.invs if inv["issued"] <= T]
    last = max(((t, k) for inv in invs for t, k in inv["dunning"] if t <= T and k in (*colls.STEPS,
                                                                                  "MORATORIUM_HOLD")), default=None)
    f = colls.flags(c.col, A, T)
    return {"invoices": len(invs), "open": sum(1 for inv in invs if not colls.is_paid(inv, T)),
            "overdue": round(sum(colls.owed(inv, T) for inv in invs if colls.is_overdue(inv, T)), 2),
            "phase": _phase(c.col, A, T), "last": cat.EVENTS[last[1]][0] if last else None,
            "lastAt": _d(last[0]) if last else None, "budget": f["budgetBilling"], "lowIncome": f["lowIncome"]}


def b_accounts(c) -> list[list]:
    tw, bk, T = c.tw, c.bk, c.T
    n_ctr: Counter = Counter(x["accountId"] for x in c.master["contracts"])
    rows = []
    for a in c.master["accounts"]:
        aid = a["id"]
        bp = c.master["partner_by_id"].get(a.get("businessPartnerId"), {})
        at = _account_at(c, c.col.accounts.get(aid), T)
        rows.append([aid, bp.get("name"), a.get("businessPartnerId"), a.get("premiseId"),
                     _address(c, a.get("premiseId")), a.get("paymentMethod"),
                     tw.account_profile.get(aid, bp.get("paymentProfile")), a.get("sapContractAccount"),
                     _date10(a.get("validFrom")), _date10(a.get("validTo")), n_ctr.get(aid, 0), at["invoices"],
                     at["open"], bk.balance(aid, T), at["overdue"], at["phase"], at["last"], at["lastAt"],
                     at["budget"] or ("enrolled" if a.get("budgetBilling") else None), at["lowIncome"]])
    return _rows_to_cols(ACCOUNTS, rows)


CONTRACTS = (Col("contractId", "Contract", "id", search=True),
             Col("installationId", "Installation", "id", link="installation", search=True),
             Col("accountId", "Account", "id", link="account", search=True),
             Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
             Col("commodity", "Commodity", facet=True), Col("tariffId", "Tariff", facet=True),
             Col("netMetering", "Net metering", "bool", facet=True), Col("validFrom", "Valid from", "date"),
             Col("validTo", "Valid to", "date"), Col("status", "Status", facet=True))


def b_contracts(c) -> list[list]:
    rows = []
    for x in c.master["contracts"]:
        inst = c.master["inst_by_id"].get(x["installationId"], {})
        asg = c.master["assign_by_contract"].get(x["id"], {})
        rows.append([x["id"], x["installationId"], x.get("accountId"), inst.get("premiseId"),
                     _address(c, inst.get("premiseId")), inst.get("division"), asg.get("tariffId"),
                     bool(asg.get("netMetering")), _date10(x.get("validFrom")), _date10(x.get("validTo")),
                     x.get("status")])
    return _rows_to_cols(CONTRACTS, rows)


# ---- meters & reading --------------------------------------------------------------------------------------------
SERVICE_POINTS = (Col("servicePointId", "Service point", "id", search=True),
                  Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
                  Col("commodity", "Commodity", facet=True), Col("meterId", "Meter", "id", search=True),
                  Col("installationId", "Installation", "id", link="installation"), Col("status", "Status", facet=True),
                  Col("validFrom", "Valid from", "date"), Col("validTo", "Valid to", "date"),
                  Col("networkNodeId", "Network node", "id"))


def b_service_points(c) -> list[list]:
    rows = [[s["id"], s.get("premiseId"), _address(c, s.get("premiseId")), s.get("commodity"), s.get("meterId"),
             s.get("installationId"), s.get("status"), _date10(s.get("validFrom")), _date10(s.get("validTo")),
             s.get("networkNodeId")] for s in c.master["servicePoints"]]
    return _rows_to_cols(SERVICE_POINTS, rows)


METERS = (Col("meterId", "Meter", "id", search=True), Col("premiseId", "Premise", "id", link="premise"),
          Col("address", "Address", search=True), Col("commodity", "Commodity", facet=True),
          Col("technology", "Technology", facet=True), Col("manufacturer", "Manufacturer", facet=True),
          Col("model", "Model", facet=True), Col("serialNumber", "Serial", "id", search=True),
          Col("registers", "Registers", "int"), Col("multiplier", "Multiplier", "int"),
          Col("registerDigits", "Digits", "int"), Col("installedAt", "Installed", "date"),
          Col("commStatus", "Comms", facet=True), Col("collectorId", "AMI collector", facet=True),
          Col("collectorDistanceM", "To collector", "num", unit="m"), Col("bidirectional", "Bidirectional", "bool"),
          Col("deviceId", "Device now", "id", hint="The device on this meter slot as registered by the view date."),
          Col("replacements", "Replacements", "int"))


def b_meters(c) -> list[list]:
    run, tw, T = c.run, c.tw, c.T
    slot = {mid: k for k, mid in enumerate(tw.meter_ids)}
    swaps: Counter = Counter(x.meter for x in run.installs if x.t_reg <= T)
    rows = []
    for m in c.master["meters"]:
        sp = c.master["sp_by_id"].get(m.get("servicePointId"), {})
        k = slot.get(m["id"])
        ami = m.get("ami") or {}
        rows.append([m["id"], sp.get("premiseId"), _address(c, sp.get("premiseId")), sp.get("commodity"),
                     m.get("technology"), m.get("manufacturer"), m.get("model"), m.get("serialNumber"),
                     len(m.get("registerIds") or []), m.get("multiplier"), m.get("registerDigits"),
                     _date10(m.get("installedAt")), m.get("commStatus"), ami.get("collectorId"),
                     ami.get("distanceM"), bool(m.get("bidirectional")),
                     run.device_at(k, T, T) if k is not None else m["id"], swaps.get(k, 0) if k is not None else 0])
    return _rows_to_cols(METERS, rows)


REGISTERS = (Col("registerId", "Register", "id", search=True), Col("meterId", "Meter", "id", search=True),
             Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
             Col("commodity", "Commodity", facet=True), Col("direction", "Direction", facet=True),
             Col("unit", "Unit", facet=True), Col("digits", "Digits", "int"), Col("obis", "OBIS", facet=True),
             Col("technology", "Technology", facet=True), Col("mruId", "MRU", facet=True),
             Col("portion", "Portion", "int"), Col("readsToDate", "Reads to date", "int"),
             Col("lastReadAt", "Last read", "date"))


def b_registers(c) -> list[list]:
    run, tw, T = c.run, c.tw, c.T
    rows = []
    for g in c.master["registers"]:
        r = tw.reg_index.get(g["id"])
        reads = last = None
        if r is not None:
            done = run.read_t[r, 1:] <= T
            reads = int(done.sum())
            last = _d(tw.read_day[r, int(np.flatnonzero(done)[-1]) + 1]) if reads else None
        p = int(tw.prem[r]) if r is not None else None
        rows.append([g["id"], g.get("meterId"), tw.premise_ids[p] if p is not None else None,
                     tw.address[p] if p is not None else None, str(tw.commodity[r]) if r is not None else None,
                     g.get("direction"), g.get("unit"), g.get("digits"), g.get("obis"),
                     str(tw.tech[r]) if r is not None else None, tw.mru[r] if r is not None else None,
                     int(tw.portion[r]) if r is not None else None, reads, last])
    return _rows_to_cols(REGISTERS, rows)


INSTALLATIONS = (Col("installationId", "Installation", "id", link="installation", search=True),
                 Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
                 Col("division", "Division", facet=True), Col("rateCategory", "Rate category", facet=True),
                 Col("billedRate", "Rate billed now", facet=True,
                     hint="The rate category billing uses on the view date (a seeded data error bills a wrong one "
                          "until it is fixed)."),
                 Col("billingClass", "Billing class", facet=True), Col("mruId", "MRU", facet=True),
                 Col("portion", "Portion", "int"), Col("readCycle", "Read cycle", "int"),
                 Col("status", "Status", facet=True), Col("accountId", "Account", "id", link="account", search=True),
                 Col("contracts", "Contracts", "int"), Col("documents", "Bills", "int"),
                 Col("billedToDate", "Billed to date", "money"))


def b_installations(c) -> list[list]:
    run, tw, bk, T = c.run, c.tw, c.bk, c.T
    da = _doc_arrays(run)
    n = len(tw.inst_ids)
    seen = da["created"] <= T
    counts = np.bincount(da["inst"][seen], minlength=n) if seen.any() else np.zeros(n, dtype=np.int64)
    good = seen & (da["released"] <= T) & ~(da["reversed"] <= T)
    billed = np.bincount(da["inst"][good], weights=da["total"][good], minlength=n) if good.any() else np.zeros(n)
    asof = _d(c.day)
    rows = []
    for x in c.master["installations"]:
        k = tw.inst_index.get(x["id"])
        ctrs = c.master["contracts_of_inst"].get(x["id"], [])
        current = next((y for y in ctrs if (y.get("validFrom") or "")[:10] <= asof
                        and (not y.get("validTo") or y["validTo"][:10] > asof)), ctrs[-1] if ctrs else {})
        rows.append([x["id"], x.get("premiseId"), _address(c, x.get("premiseId")), x.get("division"),
                     x.get("rateCategory"), bk.rate_at(k, T) if k is not None else x.get("rateCategory"),
                     x.get("billingClass"), x.get("mruId"), c.master["portion_of_mru"].get(x.get("mruId"),
                                                                                        {}).get("portion"),
                     x.get("readCycle"), x.get("status"), current.get("accountId"), len(ctrs),
                     int(counts[k]) if k is not None else 0, round(float(billed[k]), 2) if k is not None else 0.0])
    return _rows_to_cols(INSTALLATIONS, rows)


MRUS = (Col("mruId", "MRU", "id", search=True), Col("portionId", "Portion", facet=True),
        Col("portion", "Portion no.", "int"), Col("billingBusinessDay", "Billing day", "int"),
        Col("technology", "Technology", facet=True), Col("readerId", "Reader", facet=True),
        Col("meterCount", "Meters", "int"), Col("premises", "Premises", "int"))


def b_mrus(c) -> list[list]:
    rows = []
    for m in c.master["mrus"]:
        p = c.master["portion_of_mru"].get(m["id"], {})
        rows.append([m["id"], m.get("portionId"), p.get("portion"), p.get("billingBusinessDay"), m.get("technology"),
                     m.get("readerId"), m.get("meterCount"), len(m.get("premiseIds") or [])])
    return _rows_to_cols(MRUS, rows)


SCHEDULES = (Col("mruId", "MRU", facet=True, search=True), Col("period", "Period", facet=True),
             Col("scheduledReadDate", "Scheduled read", "date"), Col("billingDate", "Billing date", "date"),
             Col("technology", "Technology", facet=True), Col("meterCount", "Meters", "int"))


def b_schedules(c) -> list[list]:
    rows = []
    for s in c.master["readSchedules"]:
        m = c.master["mru_by_id"].get(s.get("mruId"), {})
        rows.append([s.get("mruId"), s.get("period"), s.get("scheduledReadDate"), s.get("billingDate"),
                     m.get("technology"), m.get("meterCount")])
    return _rows_to_cols(SCHEDULES, rows)


READS = (Col("readId", "Read", "id", link="read", search=True), Col("readDate", "Read date", "date"),
         Col("premiseId", "Premise", "id", link="premise", search=True), Col("address", "Address", search=True),
         Col("accountId", "Account", "id", link="account", search=True), Col("meterId", "Meter", "id", search=True),
         Col("registerId", "Register", "id"), Col("commodity", "Commodity", facet=True),
         Col("direction", "Direction", facet=True), Col("technology", "Technology", facet=True),
         Col("mruId", "MRU", facet=True), Col("portion", "Portion", "int"), Col("periodStart", "Period start", "date"),
         Col("periodEnd", "Period end", "date"), Col("days", "Days", "num"),
         Col("previousValue", "Previous register", "num"), Col("registerValue", "Register", "num"),
         Col("consumption", "Consumption", "num"), Col("unit", "Unit", facet=True),
         Col("readType", "Read", facet=True), Col("reasonCode", "Missed reason", facet=True),
         Col("veeStatus", "VEE status", facet=True), Col("veeConfidence", "Confidence", "pct"),
         Col("sapValidationCode", "Validation code", facet=True), Col("disposition", "Disposition", facet=True),
         Col("caseId", "Case", "id", link="case"), Col("released", "Released", "bool", facet=True),
         Col("method", "Released as", facet=True), Col("releasedValue", "Released register", "num"),
         Col("billedUse", "Billed use", "num"), Col("consecutiveEstimates", "Estimates in a row", "int"),
         Col("billStatus", "Bill status", facet=True), Col("billingDocumentId", "Billing document", "id"),
         Col("invoiceId", "Invoice", "id", link="invoice"))


def _doc_arrays(run: M2CRun) -> dict:
    """The billing documents and invoices as arrays (built once per run; the view date filters them)."""
    hit = run.__dict__.get("_doc_arrays")
    if hit is not None:
        return hit
    bk = run.books
    docs = bk.docs

    def t(key):
        return np.array([INF if d[key] is None else d[key] for d in docs], dtype=float) if docs else np.zeros(0)

    out = {"created": t("created"), "released": t("released"), "reversed": t("reversed"),
           "inst": np.array([d["inst"] for d in docs], dtype=np.int64),
           "invoice": np.array([d["invoice"] for d in docs], dtype=np.int64),
           "case": np.array([d["case"] for d in docs], dtype=np.int64),
           "total": np.array([d["total"] for d in docs], dtype=float), "ids": [bk.doc_id(d) for d in docs],
           "inv_created": np.array([inv["created"] for inv in bk.invoices], dtype=float),
           "inv_ids": [inv["id"] for inv in bk.invoices]}
    run.__dict__["_doc_arrays"] = out
    return out


def _doc_status(da: dict, k: np.ndarray, T: float) -> np.ndarray:
    return np.where(da["reversed"][k] <= T, "reversed", np.where(da["released"][k] <= T, "released",
                                                                 np.where(da["case"][k] >= 0, "blocked", "created")))


def _billed_use(run: M2CRun, T: float) -> np.ndarray:
    """Billed consumption per register and month ((R, 12), NaN until the read is released), as billing takes it."""
    rel = run.released
    mod = 10.0 ** run.town.digits.astype(float)[:, None]
    d = rel[:, 1:] - rel[:, :-1]
    use = np.where(d < -0.5 * mod, d + mod, d)
    for r, m in zip(*np.nonzero(run.dev_change[:, 1:] != None)):  # noqa: E711  (object array of Installs)
        x = run.dev_change[r, m + 1]
        if x is not None and x.t_reg <= T:
            use[r, m] = views.billed_use(run, int(r), int(m) + 1)
    for r, m in zip(*np.nonzero((run.status[:, :-1] == OFF) & ~np.isnan(rel[:, 1:]))):  # after the service was off
        use[r, m] = views.billed_use(run, int(r), int(m) + 1)
    done = (run.read_t[:, 1:] <= T) & (run.release_t[:, 1:] <= T)
    return np.where(done, use, np.nan)


def b_reads(c) -> list[list]:
    run, tw, T = c.run, c.tw, c.T
    rr, mm = np.nonzero(run.read_t[:, 1:] <= T)
    mm = mm + 1
    if not len(rr):
        return _empty(READS)
    order = np.lexsort((rr, -tw.read_day[rr, mm]))  # newest read day first, then register order
    rr, mm = rr[order], mm[order]
    day = tw.read_day[rr, mm]
    prem = tw.prem[rr]
    obs = run.obs[rr, mm]
    missing = np.isnan(obs)
    released = run.release_t[rr, mm] <= T
    case = run.case_of[rr, mm]
    has_case = case >= 0
    case_month = np.array([x.month for x in run.cases], dtype=np.int64) if run.cases else np.zeros(0, np.int64)
    case_ids = np.array([x.id for x in run.cases], dtype=object) if run.cases else np.zeros(0, dtype=object)
    disp = run.disp[rr, mm]
    status = run.status[rr, mm]
    held = has_case & (case_month[np.maximum(case, 0)] != mm)
    open_disp = np.array(("review", "review", "escalated", "rejected"), dtype=object)[np.clip(disp, 0, 3)]
    after = np.select([status == 1, status == 2, status == 3],
                      ["accepted_after_review", "estimated", "adjusted"], "accepted")
    vee = np.where(~has_case, np.where(released, "accepted", "not_processed"),
                   np.where(~released, np.where(missing, "missing", np.where(held, "held", open_disp)), after))
    vee = np.where(status == OFF, "service_off", vee)
    reg_ids = np.array(tw.reg_ids, dtype=object)
    read_ids = [f"READ-{tw.id}-{g}-{_d(d)}" for g, d in zip(reg_ids[rr].tolist(), day.tolist())]
    da = _doc_arrays(run)
    k = run.books.doc_of[tw.inst_of[rr], mm]
    has_doc = (k >= 0) & (da["created"][np.maximum(k, 0)] <= T)
    kk = np.maximum(k, 0)
    doc_state = np.where(has_doc, _doc_status(da, kk, T), "")
    bill_status = np.where(has_doc, np.select([doc_state == "released", doc_state == "blocked",
                                               doc_state == "reversed"],
                                              ["billed", "billing_blocked", "rebilled"], "billing"),
                           np.where(released, "released_for_billing", np.where(has_case, "blocked", "pending")))
    bill_status = np.where(status == OFF, "not_billed", bill_status)
    doc_ids = np.array(da["ids"] + [None], dtype=object)[np.where(has_doc, kk, len(da["ids"]))]
    inv = np.where(has_doc, da["invoice"][kk], -1)
    has_inv = (inv >= 0) & (da["inv_created"][np.maximum(inv, 0)] <= T)
    inv_ids = np.array(da["inv_ids"] + [None], dtype=object)[np.where(has_inv, np.maximum(inv, 0),
                                                                        len(da["inv_ids"]))]
    use = _billed_use(run, T)[rr, mm - 1]
    code = run.code[rr, mm]
    codes = np.array(cat.CODE_LIST + (None,), dtype=object)[np.where(code >= 0, code, len(cat.CODE_LIST))]
    disps = np.array(cat.DISPOSITIONS + (None,), dtype=object)[np.where(has_case & (disp >= 0), np.clip(disp, 0, 3),
                                                                      len(cat.DISPOSITIONS))]
    methods = np.array(METHODS, dtype=object)[np.where(released, np.clip(run.method[rr, mm], 0, 4), 0)]
    rel_val = np.where(released & np.isin(status, (2, 3)), run.released[rr, mm], np.nan)
    accounts = [tw.contract_at(int(r), int(d))[1] for r, d in zip(rr.tolist(), day.tolist())]
    return [read_ids, _days(day), _pick(tw.premise_ids, prem), _pick(tw.address, prem), accounts,
            _pick(tw.meter_ids, tw.meter_of[rr]), reg_ids[rr].tolist(), _strs(tw.commodity[rr]),
            _strs(tw.direction[rr]), _strs(tw.tech[rr]), _pick(tw.mru, rr), _ints(tw.portion[rr]),
            _days(np.floor(run.prev_t_at_read[rr, mm])), _days(day),
            _nums(run.read_t[rr, mm] - run.prev_t_at_read[rr, mm], 1), _nums(run.prev_at_read[rr, mm]), _nums(obs),
            _nums(run.cons[rr, mm]), _strs(tw.unit[rr]), np.where(missing, "missing", "actual").tolist(),
            [x or None if miss else None for x, miss in zip(run.reason[rr, mm].tolist(), missing.tolist())],
            vee.tolist(), _nums(run.conf[rr, mm], 3), codes.tolist(), disps.tolist(),
            np.where(has_case, case_ids[np.maximum(case, 0)] if len(case_ids) else None, None).tolist(),
            released.tolist(), methods.tolist(), _nums(rel_val), _nums(use), _ints(run.consec_at[rr, mm]),
            bill_status.tolist(), doc_ids.tolist(), inv_ids.tolist()]


USAGE = (Col("registerId", "Register", "id", search=True), Col("premiseId", "Premise", "id", link="premise",
                                                                search=True),
         Col("address", "Address", search=True), Col("accountId", "Account", "id", link="account", search=True),
         Col("commodity", "Commodity", facet=True), Col("direction", "Direction", facet=True),
         Col("unit", "Unit", facet=True), Col("technology", "Technology", facet=True), Col("mruId", "MRU", facet=True),
         Col("rateCategory", "Rate category", facet=True),
         *[Col(k, lbl, "num") for k, lbl in zip(MONTHS, MONTH_LABELS)],
         Col("yearToDate", "Year to date", "num"), Col("perDay", "Per day", "num"),
         Col("readsToDate", "Reads", "int"), Col("estimatedMonths", "Estimated", "int"),
         Col("missedReads", "Missed", "int"))


def b_usage(c) -> list[list]:
    run, tw, T = c.run, c.tw, c.T
    R = len(tw.reg_ids)
    use = _billed_use(run, T)
    seen = run.read_t[:, 1:] <= T
    ytd = np.where(np.isnan(use).all(1), np.nan, np.nansum(use, axis=1))
    first = np.where(seen.any(1), run.prev_t_at_read[:, 1], np.nan)
    last_m = np.where(seen.any(1), seen.shape[1] - np.argmax(seen[:, ::-1], axis=1), 0)
    last = run.read_t[np.arange(R), last_m]
    per_day = ytd / np.maximum(last - first, 1e-9)
    est = ((run.status[:, 1:] == 2) & (run.release_t[:, 1:] <= T)).sum(1)
    missed = (np.isnan(run.obs[:, 1:]) & seen & (run.status[:, 1:] != OFF)).sum(1)
    accounts = [tw.contract_at(r, c.day)[1] for r in range(R)]
    rate = [tw.inst_rate[i] for i in tw.inst_of.tolist()]
    return [list(tw.reg_ids), _pick(tw.premise_ids, tw.prem), _pick(tw.address, tw.prem), accounts,
            _strs(tw.commodity), _strs(tw.direction), _strs(tw.unit), _strs(tw.tech), list(tw.mru), rate,
            *[_nums(use[:, m]) for m in range(12)], _nums(ytd), _nums(np.where(seen.any(1), per_day, np.nan), 3),
            _ints(seen.sum(1)), _ints(est), _ints(missed)][: len(USAGE)] if R else _empty(USAGE)


DEVICE_CHANGES = (Col("meterId", "Meter", "id", search=True), Col("premiseId", "Premise", "id", link="premise"),
                  Col("address", "Address", search=True), Col("commodity", "Commodity", facet=True),
                  Col("previousDevice", "Removed device", "id", search=True),
                  Col("deviceId", "New device", "id", search=True), Col("installedAt", "Installed", "date"),
                  Col("registeredAt", "Registered", "date"), Col("physical", "Swapped now", "bool", facet=True),
                  Col("by", "By", facet=True), Col("orderId", "Order", "id", link="order"),
                  Col("caseId", "Case", "id", link="case"), Col("initialReads", "Initial reads"),
                  Col("removalReads", "Removal reads"), Col("note", "Note"))


def b_device_changes(c) -> list[list]:
    run, tw, T = c.run, c.tw, c.T
    rows = []
    for x in sorted((x for x in run.installs if x.t_reg <= T), key=lambda x: -x.t_reg):
        p = int(tw.meter_prem[x.meter])
        rows.append([tw.meter_ids[x.meter], tw.premise_ids[p], tw.address[p], str(tw.meter_commodity[x.meter]),
                     x.previous, x.device, _d(x.t), _d(x.t_reg), bool(x.physical), x.by, x.order, x.case,
                     " · ".join(f"{tw.reg_ids[r]}: {v:g}" for r, v in x.initial.items()),
                     " · ".join(f"{tw.reg_ids[r]}: {v:g}" for r, v in x.removal.items()) or None, x.note])
    return _rows_to_cols(DEVICE_CHANGES, rows)


# ---- billing & pricing -------------------------------------------------------------------------------------------
TARIFFS = (Col("tariffId", "Tariff", "id", facet=True, search=True), Col("commodity", "Commodity", facet=True),
           Col("basedOn", "Based on"), Col("version", "Version", "int"), Col("effectiveFrom", "Effective from", "date"),
           Col("effectiveTo", "Effective to", "date"), Col("fixedMonthly", "Fixed charge", "money", unit="/month"),
           Col("tier1UpTo", "Tier 1 up to", "num", unit="kWh/month"), Col("tier1Price", "Tier 1", "num", unit="$/kWh"),
           Col("tier2Price", "Tier 2", "num", unit="$/kWh"), Col("variableDelivery", "Delivery", "num", unit="$/kWh"),
           Col("netMeteringCredit", "Net-metering credit", "num", unit="$/kWh"),
           Col("demandChargePerKW", "Demand charge", "money", unit="$/kW·month"),
           Col("pricePerM3", "Volume price", "num", unit="$/m³"), Col("wastewaterRatio", "Wastewater ratio", "num"),
           Col("calorificMJm3", "Calorific value", "num", unit="MJ/m³"), Col("taxRate", "Tax", "pct"),
           Col("currency", "Currency"), Col("contracts", "Contracts", "int"))


def _scaler(k: float):
    return lambda v: None if v is None else round(float(v) * k, 5)


def b_tariffs(c) -> list[list]:
    tw, b = c.tw, c.run.cfg.billing
    n_ctr: Counter = Counter(a.get("tariffId") for a in c.master["tariffAssignments"])
    change = str(b.rate_change_date)[:10] if b.rate_change_date else None
    f = 1.0 + float(b.rate_change_pct) / 100.0
    before = (date_of(views.parse_day(change, 0) - 1).isoformat() if change else None)
    rows = []
    for t in c.master["tariffs"]:
        tf = tw.tariffs.get(t["id"], t)
        blocks = tf.get("energyBlocks") or []
        for ver, (frm, to, k) in enumerate([("2026-01-01", before, 1.0), (change, None, f)] if change else
                                           [("2026-01-01", None, 1.0)], start=1):
            sc = _scaler(k)
            rows.append([t["id"], tf.get("commodity"), t.get("basedOn"), ver, frm, to, tf.get("fixedMonthly"),
                         blocks[0].get("up_to") if blocks else None, sc(blocks[0].get("price")) if blocks else None,
                         sc(blocks[1].get("price")) if len(blocks) > 1 else None, sc(tf.get("variableDelivery")),
                         sc(tf.get("netMeteringCredit")), tf.get("demandChargePerKW"), sc(tf.get("pricePerM3")),
                         tf.get("wastewaterRatio"), tf.get("calorificMJm3"), tf.get("taxRate"), tf.get("currency"),
                         n_ctr.get(t["id"], 0)])
    return _rows_to_cols(TARIFFS, rows)


ASSIGNMENTS = (Col("contractId", "Contract", "id", search=True), Col("tariffId", "Tariff", facet=True),
               Col("netMetering", "Net metering", "bool", facet=True), Col("validFrom", "Valid from", "date"),
               Col("validTo", "Valid to", "date"), Col("status", "Status", facet=True),
               Col("installationId", "Installation", "id", link="installation", search=True),
               Col("accountId", "Account", "id", link="account", search=True),
               Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
               Col("commodity", "Commodity", facet=True))


def b_assignments(c) -> list[list]:
    ctr_by_id = {x["id"]: x for x in c.master["contracts"]}
    rows = []
    for a in c.master["tariffAssignments"]:
        ctr = ctr_by_id.get(a["contractId"], {})
        inst = c.master["inst_by_id"].get(ctr.get("installationId"), {})
        rows.append([a["contractId"], a.get("tariffId"), bool(a.get("netMetering")), _date10(a.get("validFrom")),
                     _date10(a.get("validTo")), a.get("status"), ctr.get("installationId"), ctr.get("accountId"),
                     inst.get("premiseId"), _address(c, inst.get("premiseId")), inst.get("division")])
    return _rows_to_cols(ASSIGNMENTS, rows)


DOCUMENTS = (Col("billingDocumentId", "Billing document", "id", search=True),
             Col("installationId", "Installation", "id", link="installation", search=True),
             Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
             Col("accountId", "Account", "id", link="account", search=True), Col("commodity", "Commodity", facet=True),
             Col("rateCategory", "Rate", facet=True), Col("month", "Cycle month", "int"),
             Col("periodStart", "Period start", "date"), Col("periodEnd", "Period end", "date"),
             Col("days", "Days", "num"), Col("quantityImport", "Quantity", "num"),
             Col("quantityExport", "Exported", "num"), Col("unit", "Unit", facet=True),
             Col("subtotal", "Subtotal", "money"), Col("tax", "Tax", "money"), Col("total", "Total", "money"),
             Col("status", "Status", facet=True), Col("version", "Version", "int"),
             Col("replaces", "Replaces", "id"), Col("estimated", "On an estimate", "bool", facet=True),
             Col("createdAt", "Created", "date"), Col("releasedAt", "Released", "date"),
             Col("reversedAt", "Reversed", "date"), Col("caseId", "Case", "id", link="case"),
             Col("invoiceId", "Invoice", "id", link="invoice"))


def b_documents(c) -> list[list]:
    run, tw, bk, T = c.run, c.tw, c.bk, c.T
    da = _doc_arrays(run)
    ks = np.flatnonzero(da["created"] <= T)
    if not len(ks):
        return _empty(DOCUMENTS)
    ks = ks[np.argsort(-da["created"][ks], kind="stable")]
    docs = [bk.docs[k] for k in ks.tolist()]
    inst = da["inst"][ks]
    main = bk.main[inst]
    months = np.array([d["month"] for d in docs], dtype=np.int64)
    start = run.read_t[main, months - 1]
    end = run.read_t[main, months]
    status = _doc_status(da, ks, T)
    inv = da["invoice"][ks]
    has_inv = (inv >= 0) & (da["inv_created"][np.maximum(inv, 0)] <= T)
    inv_ids = np.array(da["inv_ids"] + [None], dtype=object)[np.where(has_inv, np.maximum(inv, 0),
                                                                        len(da["inv_ids"]))]
    prem = tw.prem[main]
    accounts = [tw.contract_at(int(r), int(np.floor(s)))[1] for r, s in zip(main.tolist(), start.tolist())]
    return [[da["ids"][k] for k in ks.tolist()], _pick(tw.inst_ids, inst), _pick(tw.premise_ids, prem),
            _pick(tw.address, prem), accounts, _strs(tw.commodity[main]), [d["rate"] for d in docs],
            months.tolist(), _days(np.floor(start)), _days(np.floor(end)), _nums(end - start, 1),
            _nums([d["qImp"] for d in docs]), _nums([d["qExp"] for d in docs]), _strs(tw.unit[main]),
            _nums([d["subtotal"] for d in docs], 2), _nums([d["tax"] for d in docs], 2),
            _nums([d["total"] for d in docs], 2), status.tolist(), [d["version"] for d in docs],
            [da["ids"][d["replaces"]] if d["replaces"] >= 0 else None for d in docs],
            [bool(d.get("estimated")) for d in docs], _days(da["created"][ks]),
            [_d(d["released"]) if d["released"] is not None and d["released"] <= T else None for d in docs],
            [_d(d["reversed"]) if s == "reversed" else None for d, s in zip(docs, status.tolist())],
            [run.cases[d["case"]].id if d["case"] >= 0 else None for d in docs], inv_ids.tolist()]


INVOICES = (Col("invoiceId", "Invoice", "id", link="invoice", search=True),
            Col("accountId", "Account", "id", link="account", search=True), Col("name", "Customer", search=True),
            Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
            Col("paymentMethod", "Payment method", facet=True), Col("issuedAt", "Issued", "date"),
            Col("dueAt", "Due", "date"), Col("totalAmount", "Total", "money"), Col("amountDue", "Amount due", "money"),
            Col("outstanding", "Outstanding", "money"), Col("status", "Status", facet=True),
            Col("paidAt", "Paid", "date"), Col("daysOverdue", "Days overdue", "int"),
            Col("documents", "Bills", "int"), Col("commodities", "Commodities", facet=True),
            Col("estimated", "On an estimate", "bool", facet=True),
            Col("budgetBilling", "Budget billing", "bool", facet=True), Col("dunning", "Dunning", facet=True),
            Col("lastDunningAt", "Last dunning", "date"), Col("disconnection", "Disconnection", facet=True),
            Col("lateFees", "Late fees", "money"), Col("nsfFees", "NSF fees", "money"),
            Col("payments", "Payments", "int"))


def _who(c, acct: str) -> tuple[str | None, str | None, str | None, str | None]:
    tw = c.tw
    meta = tw.accounts.get(acct, {})
    p = tw.premise_index.get(meta.get("premiseId") or "")
    return (tw.partners.get(meta.get("businessPartnerId") or "", {}).get("name"), meta.get("premiseId"),
            tw.address[p] if p is not None else None, meta.get("paymentMethod"))


def b_invoices(c) -> list[list]:
    tw, bk, T = c.tw, c.bk, c.T
    rows = []
    for inv in sorted((inv for inv in bk.invoices if inv["created"] <= T), key=lambda i: -i["created"]):
        name, pid, addr, method = _who(c, inv["account"])
        due = colls.due_at(inv, T)
        last = max(((t, k) for t, k in inv["dunning"] if t <= T), default=None)
        est = any(bk.docs[k].get("estimated") for k in inv["docs"])
        rows.append([inv["id"], inv["account"], name, pid, addr, method, _d(inv["issued"]), _d(due),
                     _money(inv["total"]), _money(colls.amount_due(inv)), _money(colls.owed(inv, T)),
                     views.invoice_status(inv, T), _d(inv["paid"]) if colls.is_paid(inv, T) else None,
                     max(0, int(np.floor(T - due))) if due < T and not colls.is_paid(inv, T) else 0,
                     len(inv["docs"]), " + ".join(sorted({str(tw.commodity[bk.main[bk.docs[k]["inst"]]])
                                                          for k in inv["docs"]})), est, bool(inv.get("budget")),
                     cat.EVENTS[last[1]][0] if last else None, _d(last[0]) if last else None,
                     colls.disconnect_state(inv, T),
                     _money(sum(x for t, f, x in inv.get("fees", []) if f == "late_fee" and t <= T)),
                     _money(sum(x for t, f, x in inv.get("fees", []) if f == "nsf_fee" and t <= T)),
                     sum(1 for p in inv["payments"] if p["at"] <= T)])
    return _rows_to_cols(INVOICES, rows)


PAYMENTS = (Col("paidAt", "Date", "date"), Col("invoiceId", "Invoice", "id", link="invoice", search=True),
            Col("accountId", "Account", "id", link="account", search=True), Col("name", "Customer", search=True),
            Col("address", "Address", search=True), Col("amount", "Amount", "money"),
            Col("status", "Status", facet=True), Col("method", "Method", facet=True),
            Col("ref", "Reference", "id"), Col("invoiceStatus", "Invoice now", facet=True))


def b_payments(c) -> list[list]:
    bk, T = c.bk, c.T
    rows = []
    for inv in bk.invoices:
        if inv["created"] > T:
            continue
        name, _, addr, method = _who(c, inv["account"])
        for p in inv["payments"]:
            if p["at"] <= T:
                rows.append([_d(p["at"]), inv["id"], inv["account"], name, addr, _money(p["amount"]), p["status"],
                             method, p.get("ref"), views.invoice_status(inv, T), p["at"]])
    rows.sort(key=lambda r: -r[-1])
    return _rows_to_cols(PAYMENTS, [r[:-1] for r in rows])


LEDGER = (Col("postedAt", "Date", "date"), Col("accountId", "Account", "id", link="account", search=True),
          Col("name", "Customer", search=True), Col("type", "Entry", facet=True), Col("amount", "Amount", "money"),
          Col("ref", "Reference", "id", search=True), Col("balanceAfter", "Balance after", "money"))


def b_ledger(c) -> list[list]:
    bk, T = c.bk, c.T
    rows = []
    for acct, entries in bk.ledger.items():
        name = _who(c, acct)[0]
        bal = 0.0
        for t, k, amt, ref in sorted(entries, key=lambda e: e[0]):
            if t > T:
                break
            bal = round(bal + amt, 2)
            rows.append([_d(t), acct, name, k, _money(amt), ref, bal, t])
    rows.sort(key=lambda r: -r[-1])
    return _rows_to_cols(LEDGER, [r[:-1] for r in rows])


# ---- collections --------------------------------------------------------------------------------------------------
DUNNING = (Col("at", "Date", "date"), Col("step", "Step", facet=True), Col("type", "Event", facet=True),
           Col("invoiceId", "Invoice", "id", link="invoice", search=True),
           Col("accountId", "Account", "id", link="account", search=True), Col("name", "Customer", search=True),
           Col("address", "Address", search=True), Col("invoiceTotal", "Invoice total", "money"),
           Col("daysOverdue", "Days overdue then", "int"), Col("outstandingNow", "Outstanding now", "money"),
           Col("invoiceStatus", "Invoice now", facet=True), Col("disconnection", "Disconnection", facet=True))


def b_dunning(c) -> list[list]:
    bk, T = c.bk, c.T
    rows = []
    for inv in bk.invoices:
        if inv["created"] > T:
            continue
        name, _, addr, _ = _who(c, inv["account"])
        for t, k in inv["dunning"]:
            if t <= T:
                rows.append([_d(t), cat.EVENTS[k][0], k, inv["id"], inv["account"], name, addr, _money(inv["total"]),
                             max(0, int(np.floor(t - inv["due"]))), _money(colls.owed(inv, T)),
                             views.invoice_status(inv, T), colls.disconnect_state(inv, T), t])
    rows.sort(key=lambda r: -r[-1])
    return _rows_to_cols(DUNNING, [r[:-1] for r in rows])


COLLECTIONS_ACCOUNTS = (Col("accountId", "Account", "id", link="account", search=True),
                        Col("name", "Customer", search=True), Col("premiseId", "Premise", "id", link="premise"),
                        Col("address", "Address", search=True), Col("paymentMethod", "Payment method", facet=True),
                        Col("paymentProfile", "Payer profile", facet=True), Col("phase", "Phase", facet=True),
                        Col("balance", "Balance", "money"), Col("outstanding", "Outstanding", "money"),
                        Col("overdue", "Overdue", "money"), Col("overdueInvoices", "Overdue invoices", "int"),
                        Col("oldestDueAt", "Oldest due", "date"), Col("lastDunning", "Last dunning", facet=True),
                        Col("lastDunningAt", "Last dunning on", "date"), Col("arrangement", "Arrangement", facet=True),
                        Col("dunningHoldUntil", "Dunning held until", "date"), Col("lowIncome", "Low income", facet=True),
                        Col("budgetBilling", "Budget billing", facet=True),
                        Col("disconnection", "Disconnection", facet=True), Col("openCases", "Open cases", "int"))


def b_collections_accounts(c) -> list[list]:
    run, bk, col, T = c.run, c.bk, c.col, c.T
    open_cases: Counter = Counter(x.ref for x in run.cases if x.work in cat.ACCOUNT_WORK and x.created <= T
                                  and (x.resolved is None or x.resolved > T))
    rows = []
    for aid, A in col.accounts.items():
        invs = [inv for inv in A.invs if inv["issued"] <= T]
        if not invs:
            continue
        name, pid, addr, method = _who(c, aid)
        due = [inv for inv in invs if colls.is_overdue(inv, T)]
        at = _account_at(c, A, T)
        arr = col.active_arrangement(A, T)
        hold = col.hold_on(A, T)
        states = [colls.disconnect_state(inv, T) for inv in invs]
        disc = next((s for s in ("disconnected", "approved", "pending", "reconnected", "cancelled") if s in states),
                    None)
        rows.append([aid, name, pid, addr, method, A.profile, at["phase"], bk.balance(aid, T),
                     _money(sum(colls.owed(inv, T) for inv in invs)), at["overdue"], len(due),
                     _d(min(colls.due_at(inv, T) for inv in due)) if due else None, at["last"], at["lastAt"],
                     (arr["state"] if arr else None), _d(hold["end"]) if hold else None, at["lowIncome"],
                     at["budget"], disc, open_cases.get(aid, 0)])
    rows.sort(key=lambda r: (-PHASES.index(r[6]) if r[6] in PHASES else 0, -(r[9] or 0)))
    return _rows_to_cols(COLLECTIONS_ACCOUNTS, rows)


DISCONNECTIONS = (Col("invoiceId", "Invoice", "id", link="invoice", search=True),
                  Col("accountId", "Account", "id", link="account", search=True), Col("name", "Customer", search=True),
                  Col("address", "Address", search=True), Col("noticeAt", "Notice", "date"),
                  Col("state", "State", facet=True), Col("earliestDisconnectAt", "Earliest disconnect", "date"),
                  Col("approvedAt", "Approved", "date"), Col("scheduledAt", "Scheduled", "date"),
                  Col("disconnectedAt", "Disconnected", "date"), Col("reconnectedAt", "Reconnected", "date"),
                  Col("cancelledAt", "Cancelled", "date"), Col("heldBy", "Held by", facet=True),
                  Col("outstanding", "Outstanding", "money"), Col("open", "Open", "bool", facet=True))


def b_disconnections(c) -> list[list]:
    rows = []
    for row, age, _, _, _, _ in colls._items(c.run, c.col, "disconnect", c.T):
        rows.append([row["invoiceId"], row["accountId"], row["name"], row["address"], _date10(row["noticeAt"]),
                     row["state"], row["earliestDisconnectAt"], _date10(row["approvedAt"]),
                     _date10(row["scheduledAt"]), _date10(row["disconnectedAt"]), _date10(row["reconnectedAt"]),
                     _date10(row["cancelledAt"]), row["heldBy"], _money(row["outstanding"]), bool(row["open"]), age])
    rows.sort(key=lambda r: r[-1], reverse=True)
    return _rows_to_cols(DISCONNECTIONS, [r[:-1] for r in rows])


COLLECTIONS_WORK = (Col("kind", "Kind", facet=True), Col("accountId", "Account", "id", link="account", search=True),
                    Col("name", "Customer", search=True), Col("address", "Address", search=True),
                    Col("startedAt", "From", "date"), Col("endsAt", "Until", "date"), Col("state", "State", facet=True),
                    Col("amount", "Amount", "money"), Col("detail", "Detail"), Col("source", "Opened by", facet=True),
                    Col("caseId", "Case", "id", link="case"))


def b_collections_work(c) -> list[list]:
    col, T = c.col, c.T
    rows = []
    for aid, A in col.accounts.items():
        name, _, addr, _ = _who(c, aid)
        for x in A.arrangements:
            if x["start"] <= T:
                ended = x["end"] is not None and x["end"] <= T
                rows.append(["payment arrangement", aid, name, addr, _d(x["start"]), _d(x["end"]) if ended else None,
                             x["state"] if ended else "active", _money(x["amount"]),
                             f"{x.get('instalments')} instalments · {len(x.get('invoices', []))} invoices",
                             "you", None, x["start"]])
        for p in A.plans:
            t0 = p["requested"] if p["requested"] is not None and p["requested"] >= 0 else p["start"]
            if t0 is not None and t0 <= T:
                rows.append(["budget billing", aid, name, addr, _d(t0), None,
                             "active" if p["start"] is not None and p["start"] <= T else "pending",
                             _money(p["instalment"]) if p.get("instalment") is not None else None,
                             "monthly instalment", p.get("source"), p.get("caseId"), t0])
        for h in A.holds:
            if h["start"] <= T:
                rows.append(["dunning hold", aid, name, addr, _d(h["start"]), _d(h["end"]),
                             "active" if h["start"] <= T < h["end"] else "ended", None, h.get("note"), "you", None,
                             h["start"]])
        for r in A.referrals:
            if r["start"] <= T:
                decided = r.get("decided") is not None and r["decided"] <= T
                rows.append(["low-income referral", aid, name, addr, _d(r["start"]), _d(r["decide"]),
                             ("approved" if r["approved"] else "declined") if decided else "referred",
                             _money(r["grant"]) if decided and r.get("grant") else None,
                             f"decision due {_d(r['decide'])}", r.get("source"), r.get("caseId"), r["start"]])
    rows.sort(key=lambda r: -r[-1])
    return _rows_to_cols(COLLECTIONS_WORK, [r[:-1] for r in rows])


# ---- work ---------------------------------------------------------------------------------------------------------
CASES = (Col("caseId", "Case", "id", link="case", search=True), Col("exception", "Exception", facet=True),
         Col("category", "Category", facet=True), Col("queue", "Queue", facet=True), Col("status", "Status", facet=True),
         Col("createdAt", "Created", "date"), Col("resolvedAt", "Resolved", "date"), Col("ageDays", "Age", "int",
                                                                                          unit="business days"),
         Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
         Col("accountId", "Account", "id", link="account", search=True), Col("commodity", "Commodity", facet=True),
         Col("technology", "Technology", facet=True), Col("readId", "Read", "id", link="read"),
         Col("readDate", "Read date", "date"), Col("sapValidationCode", "Validation code", facet=True),
         Col("disposition", "Disposition", facet=True), Col("confidence", "Confidence", "pct"),
         Col("impact", "Bill impact", "money"), Col("assignee", "Assignee", facet=True),
         Col("createdBy", "Raised by", facet=True), Col("outcome", "Outcome", facet=True),
         Col("releasedMethod", "Released as", facet=True), Col("collectorId", "AMI collector", facet=True),
         Col("orderId", "Order", "id", link="order"))


def b_cases(c) -> list[list]:
    run, T = c.run, c.T
    rows = []
    for case in run.cases:
        if case.created > T:
            continue
        r = views._row(run, case, T)
        rows.append([r["caseId"], r["label"], r["category"], r["queue"], r["status"], _date10(r["createdAt"]),
                     _date10(r["resolvedAt"]), r["ageDays"], r["premiseId"], r["address"], r["accountId"],
                     r["commodity"], r["technology"], r["readId"], r["readDate"], r["sapValidationCode"],
                     r["disposition"], r["confidence"], _money(r["impact"]), r["assignee"], r["createdByLabel"],
                     r["outcome"], r["releasedMethod"], r.get("collectorId"), r.get("orderId"), case.created])
    rows.sort(key=lambda r: -r[-1])
    return _rows_to_cols(CASES, [r[:-1] for r in rows])


ORDERS = (Col("orderId", "Order", "id", link="order", search=True), Col("stage", "Stage", facet=True),
          Col("systemStatus", "System status", facet=True), Col("orderType", "Order type", facet=True),
          Col("shortText", "Description", search=True), Col("priority", "Priority", facet=True),
          Col("premiseId", "Premise", "id", link="premise"), Col("address", "Address", search=True),
          Col("caseId", "Case", "id", link="case"), Col("sourceCaseId", "Raised from", "id", link="case"),
          Col("createdAt", "Created", "date"), Col("startDate", "Basic start", "date"), Col("crew", "Crew", facet=True),
          Col("completedAt", "Completed", "date"), Col("outcome", "Outcome"), Col("coveredCases", "Covers", "int"))


def b_orders(c) -> list[list]:
    run, tw, T = c.run, c.tw, c.T
    rows = []
    for o in run.orders.values():
        if o.created > T:
            continue
        b = views.order_brief(run, o, T)
        f = (o.version_at(T) or (0, "", {}, []))[2]
        p = int(tw.prem[o.r]) if o.r >= 0 else None
        rows.append([o.id, b["stage"], b["systemStatus"], f.get("orderType"), b["shortText"], f.get("priority"),
                     tw.premise_ids[p] if p is not None else None, tw.address[p] if p is not None else None,
                     b["caseId"], o.source_case, _d(o.created), b["startDate"], o.crew,
                     _date10(b["completedAt"]), (b["outcome"] or {}).get("text"), len(b["coveredCaseIds"]),
                     o.created])
    rows.sort(key=lambda r: -r[-1])
    return _rows_to_cols(ORDERS, [r[:-1] for r in rows])


INTERRUPTIONS = (Col("outageId", "Interruption", "id", search=True), Col("day", "Day", "date"),
                 Col("utility", "Utility", facet=True), Col("start", "From", "time"), Col("end", "To", "time"),
                 Col("hours", "Hours", "num"), Col("premises", "Premises", "int"))


def b_interruptions(c) -> list[list]:
    rows = []
    for o in c.run.outages:
        day = views.parse_day(o["day"], 0)
        if day > c.day:
            continue
        rows.append([o.get("id"), o["day"], o["utility"], _hm(o["start"] / 86400.0), _hm(o["end"] / 86400.0),
                     round((o["end"] - o["start"]) / 3600.0, 2), len(o.get("premiseIds") or [])])
    rows.sort(key=lambda r: (r[1] or "", r[3] or ""), reverse=True)
    return _rows_to_cols(INTERRUPTIONS, rows)


CHANNEL_LABEL = {"self_serve": "Self-service", "agent": "Agent", "callback": "Call back", "emergency": "Emergency line",
                 "none": "Lines closed"}
OUTCOME_LABEL = {"resolved": "Resolved", "unresolved": "Unresolved", "abandoned": "Hung up", "gave_up": "Gave up",
                 "dispatched": "Dispatched"}
CONTACTS = (Col("contactId", "Contact", "id", search=True), Col("date", "Date", "date"), Col("time", "Time", "time"),
            Col("reason", "Reason", facet=True, search=True), Col("group", "Group", facet=True),
            Col("channel", "Channel", facet=True), Col("outcome", "Outcome", facet=True),
            Col("waitS", "Wait", "num", unit="s"), Col("handleMin", "Handle", "num", unit="min"),
            Col("attempt", "Attempt", "int"), Col("repeat", "Repeat", "bool"),
            Col("accountId", "Account", "id", link="account", search=True),
            Col("premiseId", "Premise", "id", link="premise", search=True), Col("address", "Address", search=True),
            Col("trigger", "Because of", search=True), Col("caseId", "Case opened", "id", link="case", search=True))


def b_contacts(c) -> list[list]:
    from utilsim.m2c import contact

    cx = contact.contacts(c.run)
    tw = c.run.town
    keep = np.flatnonzero(cx.t <= c.T)
    labels = [r[1] for r in contact.REASONS]
    groups = [contact.GROUPS[r[2]] for r in contact.REASONS]
    rows = []
    for i in keep.tolist():
        t = float(cx.t[i])
        a, p = int(cx.acct[i]), int(cx.prem[i])
        pid = tw.premise_ids[p] if p >= 0 else None
        w = float(cx.wait[i])
        rows.append([f"CT-{i + 1:06d}", _d(int(t)), _hm(t), labels[cx.reason[i]], groups[cx.reason[i]],
                     CHANNEL_LABEL[contact.CHANNELS[cx.channel[i]]], OUTCOME_LABEL[contact.OUTCOMES[cx.outcome[i]]],
                     None if w != w else round(w, 1), round(float(cx.handle[i]) / 60.0, 2) or None,
                     int(cx.attempt[i]), bool(cx.repeat[i]), cx.accounts[a] if a >= 0 else None, pid,
                     _address(c, pid) if pid else None, cx.trigger[i], cx.case[i] if cx.case else None])
    rows.reverse()  # newest first
    return _rows_to_cols(CONTACTS, rows)


CONTACT_DAILY = (Col("date", "Date", "date"), Col("weekday", "Day", facet=True), Col("agents", "Agents", "int"),
                 Col("contacts", "Contacts", "int"), Col("selfServed", "Self-served", "int"),
                 Col("toAgents", "To agents", "int"), Col("answered", "Answered live", "int"),
                 Col("callbacks", "Call backs", "int"), Col("abandoned", "Hung up", "int"),
                 Col("abandonedPct", "Hung up", "pct"), Col("asaS", "Average wait", "num", unit="s"),
                 Col("serviceLevelPct", "In target", "pct"), Col("occupancyPct", "Occupancy", "pct"),
                 Col("emergency", "Emergency line", "int"), Col("cost", "Cost", "money"))


def b_contact_daily(c) -> list[list]:
    from utilsim.m2c import contact

    cx = contact.contacts(c.run)
    cfgs = [c.run.cfg_at(d).contact for d in range(len(cx.daily["agents"]))]
    rows = []
    for d in range(min(c.day, len(cfgs) - 1), -1, -1):
        k = (cx.t >= d) & (cx.t < d + 1) & (cx.t <= c.T)
        s = contact._stats(cx, k, cfgs, d, d)
        rows.append([_d(d), date_of(d).strftime("%a"), int(cx.daily["agents"][d]), s["contacts"], s["selfServed"],
                     s["toAgents"], s["answered"], s["callbacks"], s["abandoned"],
                     s["abandonedPct"] if s["toAgents"] else None, s["asaS"], s["serviceLevelPct"], s["occupancyPct"],
                     s["emergency"], s["cost"]["total"]])
    return _rows_to_cols(CONTACT_DAILY, rows)


YEAR_INCIDENTS = (Col("incidentId", "Incident", "id", search=True), Col("date", "Date", "date"),
                  Col("time", "Time", "time"), Col("kind", "What", facet=True, search=True),
                  Col("utility", "Utility", facet=True), Col("storm", "Storm day", "bool"),
                  Col("customersOut", "Premises out", "int"), Col("hoursOut", "Average hours out", "num"),
                  Col("smelled", "Premises that could smell it", "int"), Col("contacts", "Contacts", "int"))


def b_year_incidents(c) -> list[list]:
    from utilsim.m2c import contact

    cx = contact.contacts(c.run)
    by_trigger = Counter(cx.trigger[i] for i in np.flatnonzero(cx.t <= c.T).tolist())
    rows = []
    for x in cx.incidents:
        if x["t"] > c.T:
            continue
        out = len(x["premises"]) if x["utility"] in ("electric", "water", "gas") else 0
        hours = float((x["restoredAt"] - x["t"]).mean() * 24.0) if out else None
        rows.append([x["id"], _d(int(x["t"])), _hm(x["t"]), x["label"], x["utility"], x["storm"], out,
                     None if hours is None else round(hours, 2), len(x["odour"]) + (1 if x["odourOwner"] >= 0 else 0),
                     by_trigger.get(x["id"], 0)])
    rows.reverse()
    return _rows_to_cols(YEAR_INCIDENTS, rows)


STATUS_LABEL = {"planned": "Planned", "open": "Open", "in_progress": "In progress", "completed": "Completed"}
WORK_ORDERS = (Col("orderId", "Work order", "id", search=True), Col("type", "Work", facet=True, search=True),
               Col("program", "Programme", facet=True), Col("crew", "Crew", facet=True),
               Col("crewId", "Crew id", search=True), Col("priority", "Priority", "int", facet=True),
               Col("status", "Status", facet=True), Col("created", "Created", "date"),
               Col("released", "Released", "date"), Col("due", "Due", "date"), Col("started", "Started", "date"),
               Col("completed", "Completed", "date"), Col("onTime", "On time", "bool", facet=True),
               Col("responseMin", "Response", "num", unit="min",
                   hint="Emergencies: from the report to the responder on site."),
               Col("hours", "Crew hours", "num", unit="h"), Col("overtimeHours", "Overtime", "num", unit="h"),
               Col("labour", "Labour", "money"), Col("materials", "Materials", "money"),
               Col("premiseId", "Premise", "id", link="premise", search=True), Col("address", "Address", search=True),
               Col("asset", "Asset", search=True), Col("cause", "Because of", search=True),
               Col("outcome", "Outcome", search=True, hint="When it was not simply done: called off, not needed on "
                   "arrival, skipped, or the asset failed first."))


def b_work_orders(c) -> list[list]:
    from utilsim.m2c import fieldwork as fwk

    fw = fwk.fieldwork(c.run)
    tw = c.run.town
    rows = []
    for o in fw.orders:
        st = fwk.status_at(o, c.T)
        if st is None:
            continue
        key, label, prog, _, _ = fwk.TYPES[o.type]
        done = st == "completed"
        met = o.arrive if key in fwk.EMERGENCY else o.end
        pid = tw.premise_ids[o.prem] if o.prem >= 0 else None
        rows.append([o.id, label, fwk.PROGRAMS[prog], "Remote (AMI)" if o.remote else fwk.CREWS[o.crew],
                     o.crew_id or None, o.prio, STATUS_LABEL[st], _d(o.created), _d(o.release) if o.release <= c.T
                     else _d(o.release), _d(o.due - 1e-6), _d(o.start) if o.start <= c.T else None,
                     _d(o.end) if done else None, (met <= o.due + 1e-9) if done else None,
                     round((o.arrive - o.created) * 1440.0, 1) if key in fwk.EMERGENCY and o.arrive <= c.T else None,
                     round((o.regular + o.overtime) / 60.0, 2) if done else None,
                     round(o.overtime / 60.0, 2) if done and o.overtime else None,
                     round(o.labour, 2) if done else None, round(o.materials, 2) if done else None, pid,
                     _address(c, pid) if pid else None, o.asset or None, o.cause or None,
                     (o.outcome or None) if st in ("completed", "cancelled") else None])
    rows.reverse()  # newest first
    return _rows_to_cols(WORK_ORDERS, rows)


CREW_DAYS = (Col("date", "Date", "date"), Col("weekday", "Day", facet=True), Col("crew", "Crew", facet=True),
             Col("crews", "Crews", "num", hint="Part of a crew: its share of the day on this work."),
             Col("availableHours", "Available", "num", unit="h"), Col("busyHours", "Busy", "num", unit="h"),
             Col("overtimeHours", "Overtime", "num", unit="h"), Col("utilisationPct", "Utilisation", "pct"),
             Col("completed", "Orders completed", "int"), Col("open", "Open at day end", "int"),
             Col("overdue", "Overdue at day end", "int"))


def b_crew_days(c) -> list[list]:
    from utilsim.m2c import fieldwork as fwk

    fw = fwk.fieldwork(c.run)
    cols = fw.cols
    rows = []
    for d in range(min(c.day, len(fw.crews["meter"]["crews"]) - 1), -1, -1):
        Td = min(d + 1 - 1e-6, c.T)
        for crew, label in fwk.CREWS.items():
            cr = fw.crews[crew]
            k = cols["crew"] == crew
            avail, busy = float(cr["availableMin"][d]), float(cr["busyMin"][d])
            live = k & (cols["release"] <= Td) & (cols["end"] > Td)
            rows.append([_d(d), date_of(d).strftime("%a"), label, round(float(cr["crews"][d]), 3),
                         round(avail / 60.0, 1), round(busy / 60.0, 1), round(float(cr["overtimeMin"][d]) / 60.0, 1),
                         round(busy / avail, 4) if avail else None,
                         int((k & (cols["end"] >= d) & (cols["end"] <= Td)).sum()), int(live.sum()),
                         int((live & (cols["due"] < Td)).sum())])
    return _rows_to_cols(CREW_DAYS, rows)


PLAN = (Col("work", "Work", facet=True, search=True), Col("program", "Programme", facet=True),
        Col("crew", "Crew", facet=True), Col("dueThisYear", "Due this year", "int",
                                             hint="Items the year's plan requires (assets, meters)."),
        Col("notOrdered", "Not ordered", "int", hint="Due items the work's rate left out."),
        Col("orders", "Orders", "int"), Col("completed", "Completed", "int"),
        Col("dueByNow", "Due by the view date", "int"), Col("onTime", "Done on time", "int"),
        Col("compliancePct", "Compliance", "pct", hint="Orders due by the view date that were done by their due date."),
        Col("overdue", "Overdue", "int"), Col("hours", "Crew hours", "num", unit="h"), Col("cost", "Cost", "money"))


def b_plan(c) -> list[list]:
    from utilsim.m2c import fieldwork as fwk

    s = fwk.summary(c.run, _d(c.day))
    types = {t["id"]: t for t in s["types"]}
    rows = []
    for p in s["plan"]:
        t = types[p["id"]]
        rows.append([p["label"], fwk.PROGRAMS[p["program"]], fwk.CREWS.get(t["crew"], "By utility"), p["due"],
                     p["skipped"], p["orders"], p["completed"], p["dueByNow"], p["onTime"], p["compliancePct"],
                     t["overdue"], t["hours"], t["cost"]["total"]])
    return _rows_to_cols(PLAN, rows)


# ---- catalog ------------------------------------------------------------------------------------------------------
SPECS: tuple[Spec, ...] = (
    Spec("premises", "Premises", "customers", "town", "Every premise of the town with its building, household and "
         "baseline daily use, and the account billed for it.", PREMISES, b_premises),
    Spec("businessPartners", "Business partners", "customers", "town", "The customers (people and organisations) "
         "with their payer profile and the account and premise they hold.", PARTNERS, b_partners),
    Spec("accounts", "Accounts", "customers", "both", "Contract accounts with their balance, open and overdue "
         "invoices and collections phase as of the view date.", ACCOUNTS, b_accounts),
    Spec("contracts", "Contracts", "customers", "town", "Supply contracts: one per installation and tenancy, with "
         "the tariff assigned.", CONTRACTS, b_contracts),
    Spec("servicePoints", "Service points", "metering", "town", "Where each commodity is delivered: the premise, "
         "meter, installation and network node.", SERVICE_POINTS, b_service_points),
    Spec("meters", "Meters", "metering", "both", "Meter master data (technology, make, collector) and the device on "
         "the slot as of the view date.", METERS, b_meters),
    Spec("registers", "Registers", "metering", "both", "Register master data with the reads taken to the view date.",
         REGISTERS, b_registers),
    Spec("installations", "Installations", "metering", "both", "Billing installations: rate category, billing class, "
         "reading unit and portion, with bills to date.", INSTALLATIONS, b_installations),
    Spec("mrus", "Meter reading units", "metering", "town", "Reading routes with their portion and billing business "
         "day.", MRUS, b_mrus),
    Spec("readSchedules", "Read schedules", "metering", "town", "The scheduled read and billing date of every MRU for "
         "each month of 2026.", SCHEDULES, b_schedules),
    Spec("reads", "Meter reads", "metering", "run", "Every periodic read taken by the view date: registers, "
         "consumption, VEE outcome, release and billing status.", READS, b_reads),
    Spec("usage", "Usage by month", "metering", "run", "Billed consumption per register for each month released by "
         "the view date, with the year to date and the reads estimated or missed.", USAGE, b_usage),
    Spec("deviceChanges", "Device changes", "metering", "run", "Meter exchanges registered by the view date, with "
         "initial and removal reads and who made them.", DEVICE_CHANGES, b_device_changes),
    Spec("tariffs", "Tariffs & prices", "billing", "both", "Price schedules per rate category, one row per version "
         "(the run's rate change starts a second version).", TARIFFS, b_tariffs),
    Spec("tariffAssignments", "Tariff assignments", "billing", "town", "Which tariff each contract is billed on, "
         "and whether it nets exports.", ASSIGNMENTS, b_assignments),
    Spec("billingDocuments", "Billing documents", "billing", "run", "Every bill computed by the view date: period, "
         "quantities, amounts, status (created, blocked, released, reversed) and the invoice it went on.",
         DOCUMENTS, b_documents),
    Spec("invoices", "Invoices", "billing", "run", "Invoices issued by the view date with what is owed, payment, "
         "dunning and disconnection state.", INVOICES, b_invoices),
    Spec("payments", "Payments", "billing", "run", "Payments received, returned debits, instalments and grants by "
         "the view date.", PAYMENTS, b_payments),
    Spec("ledger", "Account ledger", "billing", "run", "Every posting on every account: invoices, payments, fees, "
         "waivers, deferrals and grants, with the running balance.", LEDGER, b_ledger),
    Spec("dunning", "Dunning events", "collections", "run", "Reminders, overdue notices, disconnection notices, "
         "winter holds and returned payments, invoice by invoice.", DUNNING, b_dunning),
    Spec("collectionsAccounts", "Accounts in collections", "collections", "run", "Every account with an invoice, "
         "placed in its collections phase as of the view date (current, overdue, reminder, notice, hold, arrangement, "
         "disconnection).", COLLECTIONS_ACCOUNTS, b_collections_accounts),
    Spec("disconnections", "Disconnections", "collections", "run", "Disconnection notices and what became of them: "
         "approved, scheduled, disconnected, reconnected, cancelled or held.", DISCONNECTIONS, b_disconnections),
    Spec("collectionsWork", "Arrangements, plans & holds", "collections", "run", "Payment arrangements, budget "
         "billing plans, dunning holds and low-income referrals, by account.", COLLECTIONS_WORK, b_collections_work),
    Spec("contacts", "Contacts", "contact", "run", "Every contact by the view date: why the customer got in touch, "
         "how (self-service, agent, call back, emergency line), the wait, the handling time, what it resolved, "
         "what caused it and the case it opened (a bill dispute, a complaint).", CONTACTS, b_contacts),
    Spec("contactDaily", "Contact centre by day", "contact", "run", "Each day's contacts, self-service, answered, "
         "call backs and hang-ups, average wait, service level, agent occupancy and cost.", CONTACT_DAILY,
         b_contact_daily),
    Spec("yearIncidents", "Outages & leaks", "contact", "run", "The year's background incidents (the operations "
         "day's draws for every date): premises out and for how long, who could smell gas, and the contacts each "
         "caused.", YEAR_INCIDENTS, b_year_incidents),
    Spec("workOrders", "Work orders", "field", "run", "Every field work order created by the view date: customer "
         "emergencies, service orders, meter maintenance, preventative maintenance and construction, with its crew, "
         "status, due date, crew hours, cost and what raised it.", WORK_ORDERS, b_work_orders),
    Spec("crewDays", "Crews by day", "field", "run", "Each crew type's day: crews, hours available and worked, "
         "overtime, utilisation, orders completed and the open and overdue work at the end of the day.", CREW_DAYS,
         b_crew_days),
    Spec("maintenancePlan", "Maintenance plan", "field", "run", "The year's planned programmes (seal exchanges, "
         "batteries, water meter replacement, AMI conversion, inspections, flushing, surveys, upgrades and main "
         "renewal): due, ordered, completed and on time as of the view date.", PLAN, b_plan),
    Spec("cases", "Cases", "work", "run", "Every clarification case raised by the view date, across the queues, "
         "with its disposition, assignee and outcome.", CASES, b_cases),
    Spec("fieldOrders", "Field service orders", "work", "run", "Field service orders raised in the Studio, with stage, "
         "crew and outcome.", ORDERS, b_orders),
    Spec("interruptions", "Interruptions", "work", "run", "Service interruptions the map's operations days fed into "
         "this run.", INTERRUPTIONS, b_interruptions),
)
BY_NAME = {s.name: s for s in SPECS}


def catalog() -> dict:
    """``m2c-tables/1.0``: the groups and tables, with their columns."""
    return {"schemaVersion": CATALOG_VERSION, "pageMax": PAGE_MAX, "csvMax": CSV_MAX,
            "groups": [{"id": gid, "title": title, "tables": [s.json() for s in SPECS if s.group == gid]}
                       for gid, title in GROUPS]}


# ---- building and caching ------------------------------------------------------------------------------------------
def _facets(cols: tuple[Col, ...], data: list[list]) -> dict[str, list[dict]]:
    out = {}
    for j, col in enumerate(cols):
        if not col.facet:
            continue
        counts = Counter(data[j])
        top = sorted(counts.items(), key=lambda kv: (-kv[1], _text(kv[0])))[:FACET_MAX]
        out[col.key] = [{"value": v, "count": n} for v, n in top]
    return out


def build(run: M2CRun, master: dict, name: str, as_of: str | None = None) -> tuple[Spec, Table, int]:
    """The table ``name`` as of ``as_of`` (cached per run and view day); KeyError for an unknown table."""
    spec = BY_NAME.get(name)
    if spec is None:
        raise KeyError(name)
    day, T = views.as_of_t(run, as_of)
    cache: OrderedDict = run.__dict__.setdefault("_data_tables", OrderedDict())
    key = (name, day, master["id"])
    hit = cache.get(key)
    if hit is not None:
        cache.move_to_end(key)
        return spec, hit, day
    c = SimpleNamespace(run=run, tw=run.town, bk=run.books, col=run.books.collections, master=master, T=T, day=day)
    data = spec.build(c)
    if len(data) != len(spec.cols):
        raise RuntimeError(f"table {name}: {len(data)} columns built, {len(spec.cols)} declared")
    n = len(data[0]) if data else 0
    if any(len(col) != n for col in data):
        raise RuntimeError(f"table {name}: ragged columns")
    blob_cols = [data[j] for j, col in enumerate(spec.cols) if col.search]
    blob = [" ".join(_text(v) for v in row).lower() for row in zip(*blob_cols)] if blob_cols else [""] * n
    table = Table(list(spec.cols), data, _facets(spec.cols, data), blob)
    cache[key] = table
    while len(cache) > CACHE:
        cache.popitem(last=False)
    return spec, table, day


# ---- selecting: filter, search, sort, page -------------------------------------------------------------------------
def _sort_key(kind: str):
    if kind in ("int", "num", "money", "pct"):
        return lambda v: (v is None or v != v, v if v is not None and v == v else 0.0)
    if kind == "bool":
        return lambda v: (v is None, bool(v))
    return lambda v: (v is None, _text(v).lower())


def _order(table: Table, sort: str | None, desc: bool) -> list[int]:
    if not sort:
        return list(range(table.n))
    key = (sort, desc)
    hit = table.orders.get(key)
    if hit is None:
        j = next((i for i, c in enumerate(table.cols) if c.key == sort), None)
        if j is None:
            raise ValueError(f"unknown sort column {sort!r}")
        kf = _sort_key(table.cols[j].kind)
        col = table.data[j]
        if desc:  # None last in both directions
            none = [i for i in range(table.n) if col[i] is None]
            vals = [i for i in range(table.n) if col[i] is not None]
            hit = sorted(vals, key=lambda i: kf(col[i]), reverse=True) + none
        else:
            hit = sorted(range(table.n), key=lambda i: kf(col[i]))
        table.orders[key] = hit
    return hit


def _matcher(col: Col, want: str):
    """A predicate on one value for a filter string: a facet value, a date prefix, a number range (a..b) or text."""
    want = want.strip()
    if col.kind in ("int", "num", "money", "pct") and ".." in want:
        lo, hi = want.split("..", 1)
        lo_v = float(lo) if lo.strip() else -INF
        hi_v = float(hi) if hi.strip() else INF
        return lambda v: v is not None and v == v and lo_v <= float(v) <= hi_v
    if col.kind in ("date", "datetime"):
        return lambda v: (_text(v)[: len(want)] == want) if want else v is None
    if col.facet or col.kind in ("bool", "int", "num", "money", "pct", "id"):
        if want in ("", "null", "—"):
            return lambda v: v is None or v == ""
        return lambda v: _text(v) == want
    low = want.lower()
    return lambda v: low in _text(v).lower()


def select(table: Table, *, search: str | None = None, filters: dict[str, str] | None = None,
           sort: str | None = None, desc: bool = False) -> list[int]:
    """Row indexes matching the filters and the search, in sort order."""
    idx = _order(table, sort, desc)
    tests = []
    for key, want in (filters or {}).items():
        j = next((i for i, c in enumerate(table.cols) if c.key == key), None)
        if j is None:
            raise ValueError(f"unknown filter column {key!r}")
        tests.append((table.data[j], _matcher(table.cols[j], str(want))))
    needle = (search or "").strip().lower()
    if needle:
        blob = table.blob
        idx = [i for i in idx if needle in blob[i]]
    for col, ok in tests:
        idx = [i for i in idx if ok(col[i])]
    return idx


def _columns(table: Table, columns: list[str] | None) -> list[int]:
    if not columns:
        return list(range(len(table.cols)))
    by_key = {c.key: i for i, c in enumerate(table.cols)}
    unknown = [k for k in columns if k not in by_key]
    if unknown:
        raise ValueError(f"unknown column(s): {', '.join(unknown)}")
    return [by_key[k] for k in columns]


def page(run: M2CRun, master: dict, name: str, *, as_of: str | None = None, page: int = 1, page_size: int = 100,
         sort: str | None = None, desc: bool = False, search: str | None = None,
         filters: dict[str, str] | None = None, columns: list[str] | None = None) -> dict:
    """``m2c-table/1.0``: one page of a table as of a date, filtered and sorted. Rows are arrays in ``columns``
    order; ``facets`` counts the facet columns' values over the whole table (before filters), ``total`` the rows
    that match."""
    spec, table, day = build(run, master, name, as_of)
    idx = select(table, search=search, filters=filters, sort=sort, desc=desc)
    js = _columns(table, columns)
    page = max(1, page)
    size = min(max(1, page_size), PAGE_MAX)
    start = (page - 1) * size
    rows = [[table.data[j][i] for j in js] for i in idx[start:start + size]]
    return {"schemaVersion": TABLE_VERSION, "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "table": spec.name, "title": spec.title, "group": spec.group, "source": spec.source,
            "description": spec.description, "columns": [table.cols[j].json() for j in js], "rows": rows,
            "total": len(idx), "rowsInTable": table.n, "page": page, "pageSize": size, "sort": sort,
            "desc": bool(desc), "search": search or "", "filters": dict(filters or {}), "facets": table.facets}


def csv_page(run: M2CRun, master: dict, name: str, *, as_of: str | None = None, page: int = 1,
             page_size: int = CSV_MAX, sort: str | None = None, desc: bool = False, search: str | None = None,
             filters: dict[str, str] | None = None, columns: list[str] | None = None) -> str:
    """One CSV page of a table (header on every page, so a page stands alone; a client stitches pages by dropping
    the header after the first). Values as the JSON view shows them; booleans as true/false, missing as empty."""
    _, table, _ = build(run, master, name, as_of)
    idx = select(table, search=search, filters=filters, sort=sort, desc=desc)
    js = _columns(table, columns)
    size = min(max(1, page_size), CSV_MAX)
    start = (max(1, page) - 1) * size
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([table.cols[j].key for j in js])
    for i in idx[start:start + size]:
        w.writerow([_text(table.data[j][i]) for j in js])
    return buf.getvalue()
