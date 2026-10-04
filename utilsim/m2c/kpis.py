"""The KPI catalogue: every figure Utility Studio can watch, what it means, how it is counted, which settings and
scenarios move it, and where it shows.

The eleven figures of the digital twin (utilsim/twin/kpis.py, each pinned to one measure of a run over a window) are
the core; the catalogue adds the figures the Studio's pages already show (VEE against truth, blocked bills, the
contact centre, field work, reliability, cost) and the threshold figures whose windows are settings
(``SimConfig.kpi``: a bill on time within N days of its scheduled read, a held read released within N days, an
invoice paid within N days of due, a case resolved within N business days). ``measure`` computes every figure of a
run year to date, as the Studio's summary does; the thresholds come from the run's own settings, so an exported
simulation carries its definitions.

Settings paths are ``group.key`` as the settings schema names them (``reading.ami_missed_read``); ``direction`` is
+1 when raising the setting raises the figure and -1 when it lowers it. A scenario of the library influences a
figure when one of its episodes changes one of these settings (``scenarios_for``).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from utilsim.m2c import catalog as cat
from utilsim.m2c.run import OFF, M2CRun

KPIS_VERSION = "m2c-kpis/1.0"
SHARE, DAYS, PER_1000_YEAR, PER_1000, MINUTES, SECONDS, MONEY_PER_ACCOUNT, COUNT = (
    "share", "days", "per_1000_accounts_year", "per_1000_accounts", "minutes", "seconds", "currency_per_account",
    "count")

FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("reading", "Meter reading", "Whether the scheduled billing reads arrive, and what happens to the ones that do not."),
    ("vee", "Validation and estimation", "How the VEE rules and the review team sort real anomalies from noise."),
    ("work", "Exceptions and backlog", "The clarification cases, who works them, how long they wait."),
    ("billing", "Billing", "Bills released on time, held, wrong; invoices out the door."),
    ("cash", "Cash and collections", "Money in: paid on time, days to pay, what is overdue, who is cut off."),
    ("contact", "Contact centre", "Calls answered in time, hung up, resolved first time."),
    ("field", "Field work", "Orders done on time, the backlog, how fast the emergency crews arrive."),
    ("reliability", "Reliability", "Interruptions and the minutes customers were without service."),
    ("cost", "Cost", "What the year's process cost, per account."),
)
FAMILY_IDS = {f[0] for f in FAMILIES}
# Where a figure shows in the Studio.
COMMAND_CENTER, STATISTICS, WORKLISTS, SCORECARD = (
    "Command Center · trends", "Workspace · Run statistics", "Worklists · tiles", "Workspace · VEE scorecard")


@dataclass(frozen=True)
class Kpi:
    id: str
    title: str
    family: str
    unit: str
    better: str  # "lower" or "higher"
    goals: tuple[str, ...]
    definition: str
    formula: str
    thresholds: tuple[str, ...] = ()  # settings whose values the definition counts with
    settings: tuple[tuple[str, int], ...] = ()  # (path, direction): what moves it
    related: tuple[str, ...] = ()
    where: tuple[str, ...] = ()
    twin: bool = False  # one of the digital twin's figures (fitted from observed values)


MISSED = (("reading.ami_missed_read", 1), ("reading.amr_missed_read", 1), ("reading.manual_no_access", 1))
ANOMALIES = (("anomalies.leak", 1), ("anomalies.stuck_meter", 1), ("anomalies.slow_meter", 1),
             ("anomalies.transposed_digits", 1), ("anomalies.misread", 1), ("anomalies.consecutive_estimates", 1),
             ("anomalies.vacant_consuming", 1), ("anomalies.tamper", 1))
VEE_STRICT = (("vee.high_ratio", -1), ("vee.low_ratio", 1), ("vee.accept_confidence", 1))
TEAM = (("process.analysts", -1), ("process.analyst_hours_per_day", -1), ("process.rpa_coverage", -1),
        ("process.analyst_queue_days_min", 1), ("process.analyst_queue_days_max", 1))
FIELD_CAP = (("process.field_orders_per_day", -1),)

KPIS: tuple[Kpi, ...] = (
    # ---- reading --------------------------------------------------------------------------------------------------
    Kpi("missed_read_share", "Missed reads", "reading", SHARE, "lower", ("reading",),
        "Share of scheduled billing reads with no read taken: AMI dropouts, drive-by misses, no access.",
        "missed reads ÷ scheduled reads, year to date", settings=MISSED + (("outages.storm_factor", 1),),
        related=("estimated_read_share", "exceptions_all"), where=(COMMAND_CENTER, STATISTICS, WORKLISTS), twin=True),
    Kpi("estimated_read_share", "Estimated reads", "reading", SHARE, "lower", ("reading", "billing"),
        "Share of scheduled billing reads released to billing as an estimate rather than an actual read.",
        "estimated releases ÷ scheduled reads, year to date", settings=MISSED + ANOMALIES + FIELD_CAP,
        related=("missed_read_share", "bills_on_time"), where=(COMMAND_CENTER, STATISTICS, WORKLISTS), twin=True),
    Kpi("reads_released_promptly", "Reads released promptly", "reading", SHARE, "higher", ("reading", "vee"),
        "Share of held reads (a case raised on them) that were released to billing within the window, counted from "
        "the scheduled read day.", "held reads released within kpi.read_release_days ÷ held reads released",
        thresholds=("kpi.read_release_days",), settings=TEAM + FIELD_CAP + VEE_STRICT,
        related=("days_to_release", "case_backlog"), where=(STATISTICS,)),
    # ---- vee ------------------------------------------------------------------------------------------------------
    Kpi("auto_accept_share", "Auto-accepted reads", "vee", SHARE, "higher", ("vee",),
        "Share of actual reads VEE accepted without a person looking.", "auto-accepted ÷ actual reads",
        settings=VEE_STRICT + ANOMALIES, related=("exceptions_vee", "vee_precision"), where=(WORKLISTS, STATISTICS)),
    Kpi("exceptions_vee", "VEE exceptions", "vee", PER_1000_YEAR, "lower", ("vee",),
        "Cases VEE's own tests raised (high, low, zero and erratic use, register regression, odd periods, persistent "
        "low use, vacant but consuming), per 1,000 accounts a year.", "VEE cases ÷ accounts × 1,000, annualised",
        settings=VEE_STRICT + ANOMALIES, related=("vee_precision", "exceptions_all"), where=(STATISTICS,), twin=True),
    Kpi("vee_precision", "VEE precision", "vee", SHARE, "higher", ("vee",),
        "Of the reads VEE flagged, the share that were real anomalies in the simulation's truth.",
        "flagged and anomalous ÷ flagged", settings=VEE_STRICT, related=("vee_recall", "exceptions_vee"),
        where=(SCORECARD, STATISTICS, WORKLISTS)),
    Kpi("vee_recall", "VEE recall", "vee", SHARE, "higher", ("vee",),
        "Of the real anomalies among actual reads, the share VEE flagged.", "flagged and anomalous ÷ anomalous",
        settings=VEE_STRICT, related=("vee_precision", "billing_error_share"), where=(SCORECARD, STATISTICS)),
    # ---- work -----------------------------------------------------------------------------------------------------
    Kpi("exceptions_all", "Exceptions, every case", "work", PER_1000_YEAR, "lower", ("vee", "billing", "reading"),
        "Every clarification case opened, per 1,000 accounts a year: missed reads, VEE exceptions, billing blocks, "
        "disputes and complaints, whoever resolved them.", "cases opened ÷ accounts × 1,000, annualised",
        settings=MISSED + ANOMALIES + VEE_STRICT, related=("exceptions_worked", "case_backlog"),
        where=(COMMAND_CENTER, STATISTICS), twin=True),
    Kpi("exceptions_worked", "Exceptions a person worked", "work", PER_1000_YEAR, "lower", ("vee", "billing"),
        "Cases an analyst, a supervisor or you touched, per 1,000 accounts a year: what a billing team counts as its "
        "exceptions, automation's own resolutions left out.", "cases a person touched ÷ accounts × 1,000, annualised",
        settings=(("process.rpa_coverage", -1),) + VEE_STRICT + ANOMALIES + MISSED,
        related=("exceptions_all", "cost_per_account"), where=(STATISTICS,), twin=True),
    Kpi("case_backlog", "Open cases", "work", PER_1000, "lower", ("vee", "billing", "reading"),
        "Cases open at the view date, per 1,000 accounts.", "open cases ÷ accounts × 1,000",
        settings=TEAM + VEE_STRICT + MISSED, related=("days_to_release", "cases_resolved_in_time"),
        where=(COMMAND_CENTER, STATISTICS, WORKLISTS), twin=True),
    Kpi("days_to_release", "Days to release a held read", "work", DAYS, "lower", ("vee", "billing", "reading"),
        "Average calendar days from the scheduled read to the day its case released it to billing, for cases "
        "resolved year to date.", "mean(release day − scheduled read day)", settings=TEAM + FIELD_CAP,
        related=("reads_released_promptly", "case_backlog"), where=(STATISTICS, WORKLISTS), twin=True),
    Kpi("cases_resolved_in_time", "Cases resolved in time", "work", SHARE, "higher", ("vee", "billing"),
        "Share of cases raised year to date that closed within the window, in business days from being raised; a "
        "case still open counts as not in time.", "cases closed within kpi.case_resolution_days ÷ cases raised",
        thresholds=("kpi.case_resolution_days",), settings=TEAM, related=("case_backlog", "days_to_release"),
        where=(STATISTICS,)),
    Kpi("truck_rolls_per_1000", "Truck rolls", "work", PER_1000_YEAR, "lower", ("fieldwork", "reading"),
        "Field visits made for cases (check reads, no-access visits, meter faults), per 1,000 accounts a year.",
        "truck rolls ÷ accounts × 1,000, annualised", settings=MISSED + ANOMALIES + FIELD_CAP,
        related=("estimated_read_share", "cost_per_account"), where=(STATISTICS,)),
    # ---- billing --------------------------------------------------------------------------------------------------
    Kpi("bills_on_time", "Bills on time", "billing", SHARE, "higher", ("billing",),
        "Share of bills created year to date that were released to invoicing within the window, counted from the "
        "scheduled read day they bill; a bill still blocked counts as late.",
        "bills released within kpi.on_time_bill_days of the scheduled read ÷ bills created",
        thresholds=("kpi.on_time_bill_days",), settings=TEAM + MISSED + VEE_STRICT + FIELD_CAP,
        related=("invoice_timeliness", "blocked_bill_share"), where=(STATISTICS,)),
    Kpi("invoice_timeliness", "Invoice timeliness", "billing", SHARE, "higher", ("billing",),
        "Share of invoices created within the window of the last scheduled read they bill. The engine bills on an "
        "estimate rather than holding a bill, so this stays high under stress; a utility that counts an estimated "
        "bill as late wants Estimated reads too.", "invoices created within kpi.timely_invoice_days ÷ invoices",
        thresholds=("kpi.timely_invoice_days",), settings=TEAM + MISSED + VEE_STRICT + FIELD_CAP,
        related=("bills_on_time", "estimated_read_share"), where=(STATISTICS,), twin=True),
    Kpi("blocked_bill_share", "Bills blocked", "billing", SHARE, "lower", ("billing",),
        "Share of bills created year to date that a billing check held for a person (true-up, rate class, high "
        "bill, bill credit), whether or not they were released later.", "bills with a billing case ÷ bills created",
        settings=(("billing.high_bill_ratio", -1), ("billing.trueup_max_ratio", -1)) + ANOMALIES,
        related=("bills_on_time", "billing_error_share"), where=(COMMAND_CENTER, STATISTICS, WORKLISTS)),
    Kpi("billing_error_share", "Billing error", "billing", SHARE, "lower", ("billing", "vee"),
        "Absolute difference between released bills and the simulation's true bills, as a share of the amount "
        "billed.", "Σ|billed − true| ÷ Σ billed", settings=VEE_STRICT + ANOMALIES,
        related=("vee_recall", "blocked_bill_share"), where=(STATISTICS, WORKLISTS), twin=True),
    Kpi("days_to_invoice", "Days to invoice", "billing", DAYS, "lower", ("billing",),
        "Average calendar days from the last scheduled read an invoice bills to the invoice.",
        "mean(invoice created − last scheduled read day)", settings=TEAM + (("billing.print_lag_days", 1),),
        related=("invoice_timeliness", "days_to_pay"), where=(WORKLISTS, STATISTICS)),
    # ---- cash -----------------------------------------------------------------------------------------------------
    Kpi("days_to_pay", "Days to pay", "cash", DAYS, "lower", ("collections",),
        "Average days from an invoice's issue to its payment in full, for invoices paid year to date. Payer "
        "behaviour is a town setting (on-time and late payer shares), not a run lever.",
        "mean(paid − issued)", settings=(("customers_billing.due_days", 1),), related=("paid_on_time", "collected_share"),
        where=(WORKLISTS, STATISTICS), twin=True),
    Kpi("paid_on_time", "Invoices paid on time", "cash", SHARE, "higher", ("collections",),
        "Share of invoices whose due date (plus the grace window) has passed that were settled in full by then.",
        "invoices paid by due + kpi.payment_grace_days ÷ invoices past that date",
        thresholds=("kpi.payment_grace_days",), settings=(("customers_billing.due_days", 1),),
        related=("days_to_pay", "overdue_share"), where=(STATISTICS,)),
    Kpi("collected_share", "Cash collected", "cash", SHARE, "higher", ("collections",),
        "Payments received year to date as a share of the amount invoiced.", "collected ÷ invoiced",
        settings=(("customers_billing.due_days", -1),), related=("overdue_share", "days_to_pay"),
        where=(COMMAND_CENTER, STATISTICS, WORKLISTS), twin=True),
    Kpi("overdue_share", "Overdue receivable", "cash", SHARE, "lower", ("collections",),
        "Of the money owed at the view date, the share past its due date.", "overdue ÷ receivable",
        settings=(("customers_billing.due_days", -1), ("billing.notice_days", 1)),
        related=("collected_share", "disconnections_per_1000"), where=(COMMAND_CENTER, STATISTICS)),
    Kpi("disconnections_per_1000", "Disconnections", "cash", PER_1000_YEAR, "lower", ("collections",),
        "Services disconnected for non-payment, per 1,000 accounts a year.", "disconnected ÷ accounts × 1,000, annualised",
        settings=(("billing.disconnect_days", -1),), related=("overdue_share",), where=(COMMAND_CENTER, STATISTICS)),
    # ---- contact --------------------------------------------------------------------------------------------------
    Kpi("contact_service_level", "Calls answered in target", "contact", SHARE, "higher", ("contact",),
        "Share of answered contacts whose wait was within the day's service target.",
        "answered within contact.service_target_s ÷ answered", thresholds=("contact.service_target_s",),
        settings=(("contact.agents", 1), ("contact.handle_factor", -1)), related=("abandoned_share", "contacts_per_1000"),
        where=(COMMAND_CENTER, STATISTICS)),
    Kpi("abandoned_share", "Calls hung up", "contact", SHARE, "lower", ("contact",),
        "Share of contacts that reached the queue and hung up before an agent answered.", "abandoned ÷ (abandoned + answered)",
        settings=(("contact.agents", -1), ("contact.handle_factor", 1)), related=("contact_service_level",),
        where=(COMMAND_CENTER, STATISTICS)),
    Kpi("contacts_per_1000", "Contacts", "contact", PER_1000_YEAR, "lower", ("contact",),
        "Contacts of every kind (self-served, answered, callbacks, abandoned), per 1,000 accounts a year.",
        "contacts ÷ accounts × 1,000, annualised", settings=(("billing.high_bill_ratio", -1),) + MISSED + (("outages.storm_factor", 1),),
        related=("first_contact_resolution", "abandoned_share"), where=(COMMAND_CENTER, STATISTICS)),
    Kpi("first_contact_resolution", "Resolved first time", "contact", SHARE, "higher", ("contact",),
        "Share of contacts resolved on the first attempt, self-served or answered, not a repeat.", "resolved first ÷ contacts",
        settings=(("contact.agents", 1),), related=("contacts_per_1000",), where=(STATISTICS,)),
    # ---- field ----------------------------------------------------------------------------------------------------
    Kpi("field_on_time", "Field work on time", "field", SHARE, "higher", ("fieldwork",),
        "Share of completed field orders that met their target: arrival for emergencies, completion for the rest.",
        "orders that met their due time ÷ orders completed",
        settings=(("field.crew_meter.per_1000_premises", 1), ("field.crew_emergency.per_1000_premises", 1)),
        related=("field_backlog_per_1000", "emergency_response_min"), where=(COMMAND_CENTER, STATISTICS)),
    Kpi("field_backlog_per_1000", "Field orders open", "field", PER_1000, "lower", ("fieldwork",),
        "Released field orders not yet done at the view date, per 1,000 accounts.", "open orders ÷ accounts × 1,000",
        settings=(("field.crew_meter.per_1000_premises", -1),), related=("field_on_time",),
        where=(COMMAND_CENTER, STATISTICS)),
    Kpi("emergency_response_min", "Emergency response", "field", MINUTES, "lower", ("fieldwork", "operations"),
        "Average minutes from an emergency order (gas odour, no supply) to the crew's arrival.",
        "mean(arrive − created) for emergency orders", settings=(("field.crew_emergency.per_1000_premises", -1),),
        related=("field_on_time",), where=(STATISTICS,)),
    # ---- reliability ----------------------------------------------------------------------------------------------
    Kpi("customer_minutes_lost", "Customer minutes without service", "reliability", MINUTES, "lower", ("operations", "fieldwork"),
        "Minutes of interrupted service per customer over the year's outages and leaks, all utilities together.",
        "Σ customer-minutes interrupted ÷ customers", settings=(("outages.storm_factor", 1), ("outages.incident_factor", 1), ("outages.restore_factor", 1), ("incidents.water_main_breaks_per_100km", 1), ("incidents.gas_service_leaks_per_1000", 1)),
        related=("contacts_per_1000",), where=(STATISTICS, WORKLISTS)),
    # ---- cost -----------------------------------------------------------------------------------------------------
    Kpi("cost_per_account", "Process cost per account", "cost", MONEY_PER_ACCOUNT, "lower", ("billing", "vee", "reading"),
        "The year's meter-to-cash process cost (people, systems, customer effects, reads) per account.",
        "cost total ÷ accounts", settings=(("process.analysts", 1), ("process.rpa_coverage", -1)) + MISSED,
        related=("exceptions_worked", "carry_per_account"), where=(COMMAND_CENTER, STATISTICS, WORKLISTS)),
    Kpi("carry_per_account", "Carrying cost per account", "cost", MONEY_PER_ACCOUNT, "lower", ("billing", "collections"),
        "Money held up in unreleased reads, unbilled periods and unpaid invoices, priced at the carry rate, per account.",
        "(case carry + billing carry + receivable carry) ÷ accounts",
        settings=(("process.carry_rate_per_day", 1),) + TEAM, related=("cost_per_account", "days_to_pay"),
        where=(COMMAND_CENTER, STATISTICS, WORKLISTS)),
)
KPI_BY_ID: dict[str, Kpi] = {k.id: k for k in KPIS}
KPI_IDS = frozenset(KPI_BY_ID)


def kpi_json(kpi: Kpi) -> dict:
    d = asdict(kpi)
    d["settings"] = [{"path": p, "direction": s} for p, s in kpi.settings]
    d["scenarios"] = scenarios_for(kpi.id)
    return d


def setting_paths(settings: dict | None) -> set[str]:
    return {f"{g}.{k}" for g, vals in (settings or {}).items() if isinstance(vals, dict) for k in vals}


def scenarios_for(kpi_id: str) -> list[str]:
    """The library scenarios whose episodes change a setting that moves this figure."""
    from utilsim.m2c.scenarios import SCENARIOS

    moved = {p for p, _ in KPI_BY_ID[kpi_id].settings}
    out = []
    for s in SCENARIOS:
        paths = set().union(*(setting_paths(e.get("settings")) for e in s.get("episodes", [])))
        if paths & moved:
            out.append(s["id"])
    return out


def for_goals(goals) -> list[Kpi]:
    """The figures that belong to any of these goals (every figure for "everything")."""
    wanted = set(goals or [])
    if not wanted or "everything" in wanted:
        return list(KPIS)
    return [k for k in KPIS if wanted & set(k.goals)]


def thresholds(cfg) -> dict:
    """The threshold settings as a config holds them, by path, with their schema titles and units."""
    from utilsim.m2c.run import settings_schema

    schema = settings_schema()["properties"]
    out = {}
    for path in sorted({p for k in KPIS for p in k.thresholds}):
        g, key = path.split(".")
        field = schema[g]["properties"][key]
        out[path] = {"title": field.get("title", key), "unit": field.get("x-unit", ""), "value": getattr(getattr(cfg, g), key),
                     "description": field.get("description", ""), "group": schema[g].get("title", g)}
    return out


def catalogue(cfg=None) -> dict:
    from utilsim.config.model import SimConfig

    cfg = cfg or SimConfig()
    return {"schemaVersion": KPIS_VERSION, "families": [{"id": i, "title": t, "text": x} for i, t, x in FAMILIES],
            "kpis": [kpi_json(k) for k in KPIS], "thresholds": thresholds(cfg), "settingsGroup": "kpi"}


# ---- measuring ------------------------------------------------------------------------------------------------------
def _share(count, total, digits=4):
    return round(float(count) / float(total), digits) if total else None


def _mean(values):
    return round(float(np.mean(values)), 2) if len(values) else None


def measure(run: M2CRun, as_of: str | None = None, ids=None) -> dict:
    """Every figure of ``run`` year to date at ``as_of`` (``None`` where there is nothing to count yet), with the
    thresholds in force. ``ids`` restricts the figures."""
    from utilsim.m2c import contact, fieldwork, views
    from utilsim.m2c.views import as_of_t
    from utilsim.twin.kpis import measure as twin_measure
    from utilsim.twin.kpis import window

    wanted = set(ids) if ids else KPI_IDS
    day, T = as_of_t(run, as_of)
    k_cfg = run.cfg.kpi
    tw, bk, cal = run.town, run.books, run.cal
    n_acc = max(1, len(tw.account_method))
    per_year = cal.days / (day + 1)
    out: dict = {}
    w = window(run, None, cal.date_of(day).isoformat())
    twin = twin_measure(run, w, k_cfg.timely_invoice_days)
    out.update({k: v for k, v in twin.items() if k in KPI_BY_ID})
    # The summary blocks the Studio already shows.
    s = views.summary(run, as_of)
    kp, bill, rel = s["kpis"], s["billing"], s.get("reliability") or {}
    out["auto_accept_share"] = _share(kp["autoAccepted"], kp["actual"])
    out["vee_precision"] = kp["vee"].get("precision")
    out["vee_recall"] = kp["vee"].get("recall")
    out["truck_rolls_per_1000"] = round(kp["truckRolls"] / n_acc * 1000.0 * per_year, 2)
    out["blocked_bill_share"] = None
    out["days_to_invoice"] = bill.get("avgDaysToInvoice")
    out["overdue_share"] = _share(bill.get("overdue", 0.0), bill.get("receivable", 0.0))
    disconnected = (bill.get("collections") or {}).get("disconnections", {}).get("disconnected", 0)
    out["disconnections_per_1000"] = round(disconnected / n_acc * 1000.0 * per_year, 2)
    out["cost_per_account"] = round(kp["costs"]["total"] / n_acc, 2)
    out["carry_per_account"] = round((kp.get("carry", 0.0) + bill.get("billingCarry", 0.0) + bill.get("receivableCarry", 0.0)) / n_acc, 2)
    minutes = sum(float(u.get("customerMinutes", 0.0)) for u in rel.values() if isinstance(u, dict))
    out["customer_minutes_lost"] = round(minutes / n_acc, 2)
    # Documents: on time against the scheduled read, blocked.
    docs = [d for d in bk.docs if 0 <= d["created"] <= T]
    if docs:
        on_time = sum(1 for d in docs if d["released"] is not None and d["released"] <= T
                      and int(np.floor(d["released"])) - int(tw.read_day[bk.main[d["inst"]], d["month"]]) <= k_cfg.on_time_bill_days)
        out["bills_on_time"] = _share(on_time, len(docs))
        out["blocked_bill_share"] = _share(sum(1 for d in docs if d["case"] >= 0), len(docs))
    else:
        out["bills_on_time"] = None
    # Held reads released promptly.
    months = slice(1, 13)
    read_day, read_t = tw.read_day[:, months], run.read_t[:, months]
    status, release, case_of = run.status[:, months], run.release_t[:, months], run.case_of[:, months]
    held = (read_t <= T) & (status != OFF) & (case_of >= 0) & (release <= T) & (status >= 1) & (status <= 3)
    if held.any():
        prompt = held & ((np.floor(release) - read_day) <= k_cfg.read_release_days)  # whole days late
        out["reads_released_promptly"] = _share(int(prompt.sum()), int(held.sum()))
    else:
        out["reads_released_promptly"] = None
    # Cases resolved in time, in business days.
    opened = [c for c in run.cases if 0 <= c.created <= T]
    if opened:
        in_time = sum(1 for c in opened if c.resolved is not None and c.resolved <= T
                      and cal.bdays_between(c.created, c.resolved) <= k_cfg.case_resolution_days)
        out["cases_resolved_in_time"] = _share(in_time, len(opened))
    else:
        out["cases_resolved_in_time"] = None
    # Invoices paid on time: due plus grace has passed.
    due_passed = [inv for inv in bk.invoices if 0 <= inv["created"] <= T and inv["due"] + k_cfg.payment_grace_days + 1 <= T]
    if due_passed:
        paid = sum(1 for inv in due_passed if inv.get("paid") is not None and inv["paid"] <= inv["due"] + k_cfg.payment_grace_days + 1)
        out["paid_on_time"] = _share(paid, len(due_passed))
    else:
        out["paid_on_time"] = None
    # Contact centre and field work, as their summaries count.
    if wanted & {"contact_service_level", "abandoned_share", "contacts_per_1000", "first_contact_resolution"}:
        ck = contact.summary(run, as_of)["kpis"]
        out["contact_service_level"] = ck.get("serviceLevelPct")  # shares already, despite the names
        out["abandoned_share"] = ck.get("abandonedPct")
        out["contacts_per_1000"] = round(ck.get("contacts", 0) / n_acc * 1000.0 * per_year, 2)
        out["first_contact_resolution"] = _share(ck.get("resolvedFirst", 0), ck.get("contacts", 0))
    if wanted & {"field_on_time", "field_backlog_per_1000", "emergency_response_min"}:
        fk = fieldwork.summary(run, as_of)["kpis"]
        out["field_on_time"] = fk.get("onTimePct")  # a share, despite the name
        out["field_backlog_per_1000"] = round(fk.get("open", 0) / n_acc * 1000.0, 2)
        out["emergency_response_min"] = fk.get("responseMin")
    values = {k: out.get(k) for k in KPI_BY_ID if k in wanted}
    return {"schemaVersion": KPIS_VERSION, "asOf": cal.date_of(day).isoformat(), "accounts": n_acc, "values": values,
            "thresholds": {p: t["value"] for p, t in thresholds(run.cfg).items()}}


_ = cat  # the catalogue's event names are documented through the Studio; kept for callers that extend it
