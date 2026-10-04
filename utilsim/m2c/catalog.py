"""Meter-to-cash vocabulary: event types (Activity Sequence nodes) with costs, exception types, queues and VEE codes."""

from __future__ import annotations

# key: (label, icon, domain, labor $, system $, cx $). Costs follow the Activity Sequence spec's work-management table.
EVENTS: dict[str, tuple[str, str, str, float, float, float]] = {
    # Initiating events (exceptions).
    "COMM_FAIL": ("Comm fail", "📡", "ami", 0, 0.25, 0),
    "NO_ACCESS": ("No access", "🚪", "read", 0, 0.25, 0),
    "NO_READ": ("No read document", "📭", "read", 0, 0.25, 0),
    "HIGH_USAGE": ("High usage", "📈", "vee", 0, 0.25, 0),
    "LOW_USAGE": ("Low usage", "📉", "vee", 0, 0.25, 0),
    "ZERO_USAGE": ("Zero/Low usage", "0️⃣", "read", 0, 0.25, 8),
    "REGISTER_REGRESSION": ("Register went backwards", "↩️", "vee", 0, 0.25, 0),
    "VACANT_CONSUMING": ("Vacant but consuming", "🏚️", "vee", 0, 0.25, 0),
    "PERIOD_LENGTH": ("Odd read period", "📅", "vee", 0, 0.25, 0),
    "ERRATIC": ("Erratic pattern", "〰️", "vee", 0, 0.25, 0),
    "PERSISTENT_LOW": ("Persistent low use", "🐢", "vee", 0, 0.25, 0),
    "CONSECUTIVE_ESTIMATES": ("Consecutive estimates", "🔁", "vee", 0, 0.25, 0),
    # Upstream signals from operations (they explain an exception rather than raise one).
    "AMI_LAST_GASP": ("AMI last gasp (power lost)", "🪫", "ami", 0, 0.02, 0),
    "AMI_COLLECTOR_OUTAGE": ("AMI collector outage", "📡", "ami", 0, 0.02, 0),
    # Work management (must appear on every exception path).
    "EXCEPTION_QUEUED": ("Exception queued", "📥", "wm", 0, 0.10, 0),
    "ANALYST_ASSIGNED": ("Analyst assigned", "👤", "wm", 2, 0, 0),
    "ANALYST_REVIEW": ("Analyst review", "🔎", "wm", 22, 0, 0),
    "ANALYST_OVERRIDE": ("Analyst override", "✏️", "wm", 8, 0, 0),
    "ANALYST_CANCEL": ("Analyst cancel", "🚫", "wm", 8, 0, 5),
    "ANALYST_ESCALATE": ("Escalated", "⬆️", "wm", 12, 0, 5),
    "SUPERVISOR_REVIEW": ("Supervisor review", "👔", "wm", 35, 0, 0),
    "SUPERVISOR_APPROVE": ("Supervisor approve", "✅", "wm", 10, 0, 0),
    "AUTO_RESOLVED": ("Auto-resolved (RPA)", "🤖", "wm", 0, 2, 0),
    "AUTO_OVERRIDE": ("Auto-override (RPA)", "⚙️", "wm", 0, 1.5, 0),
    "CX_CALLBACK": ("Customer callback", "📲", "cx", 18, 0, 12),
    "USER_ACTION": ("Your action", "🧑‍💻", "wm", 8, 0, 0),
    # Field.
    "FIELD_ORDER": ("Field order raised", "🧰", "field", 0, 0.5, 0),
    "TRUCK_ROLL": ("Truck roll", "🚚", "field", 85, 0, 0),
    "ON_SITE": ("Crew on site", "📍", "field", 0, 0, 0),
    "VISIT_SHARED": ("Covered by the same visit", "🏘️", "field", 0, 0, 0),
    "METER_EXCHANGE": ("Meter exchanged", "🔧", "field", 40, 0, 0),
    "DEVICE_REPLACED": ("Device replaced (new register)", "🔁", "field", 4, 0.1, 0),
    "SPECIAL_READ": ("Special read", "🔍", "field", 0, 0, 0),
    # Read outcomes.
    "ESTIMATE_CREATED": ("Estimate created", "🧮", "vee", 0, 0.25, 0),
    "READ_ADJUSTED": ("Read adjusted", "📝", "vee", 0, 0.05, 0),
    "READ_HELD": ("Read held by open case", "⏸️", "vee", 0, 0, 0),
    # Billing, invoicing, payments and collections.
    "HIGH_BILL": ("High bill", "💸", "billing", 0, 0.25, 0),
    "BILL_CREDIT": ("Large credit", "🧾", "billing", 0, 0.25, 0),
    "RATE_CLASS": ("Billing block: rate class", "🏷️", "billing", 0, 0.25, 0),
    "TRUE_UP": ("Implausible true-up", "⚖️", "billing", 0, 0.25, 0),
    "BILL_CREATED": ("Billing document", "🧾", "billing", 0, 0.05, 0),
    "BILL_RELEASED": ("Bill released", "✅", "billing", 0, 0.05, 0),
    "BILL_REVERSED": ("Bill reversed", "↩️", "billing", 0, 0.5, 0),
    "REBILL": ("Rebilled", "🔁", "billing", 0, 0.5, 0),
    "RATE_FIXED": ("Rate class corrected", "🏷️", "billing", 4, 0, 0),
    "INVOICE_CREATED": ("Invoice created", "📨", "invoice", 0, 0.35, 0),
    "PAYMENT_RECEIVED": ("Payment received", "💳", "payment", 0, 0.1, 0),
    "PAYMENT_REJECTED": ("Payment rejected", "⛔", "payment", 0, 0.5, 20),
    "DUNNING_REMINDER": ("Reminder", "✉️", "collections", 0, 0.5, 0),
    "DUNNING_NOTICE": ("Overdue notice and late fee", "⚠️", "collections", 0, 1.0, 5),
    "DISCONNECT_NOTICE": ("Disconnection notice", "🔌", "collections", 0, 2.0, 15),
    "MORATORIUM_HOLD": ("Winter moratorium hold", "❄️", "collections", 0, 0, 0),
    # Collections work (utilsim/m2c/collections.py): your actions, the call centre's referrals and their outcomes.
    "DISCONNECT_APPROVED": ("Disconnection approved", "✅", "collections", 4, 0, 0),
    "DISCONNECT_CANCELLED": ("Disconnection cancelled", "🚫", "collections", 4, 0, 0),
    "DISCONNECTED": ("Disconnected for non-payment", "⛔", "collections", 85, 0.5, 25),
    "RECONNECTED": ("Reconnected", "🔌", "collections", 85, 0.5, 0),
    "DUE_DATE_EXTENDED": ("Due date extended", "📅", "collections", 4, 0, 0),
    "FEE_WAIVED": ("Fee waived", "🎟️", "collections", 4, 0, 0),
    "PAYMENT_ARRANGEMENT": ("Payment arrangement", "🤝", "collections", 12, 0.5, 0),
    "ARRANGEMENT_COMPLETED": ("Payment arrangement completed", "🏁", "collections", 0, 0.1, 0),
    "ARRANGEMENT_BROKEN": ("Payment arrangement broken", "💔", "collections", 0, 0.5, 5),
    "DUNNING_HOLD": ("Dunning hold", "⏸️", "collections", 4, 0, 0),
    "LOW_INCOME": ("Low-income referral", "🤲", "collections", 6, 0.25, 0),
    "LOW_INCOME_GRANT": ("Low-income grant approved", "💚", "collections", 0, 0.5, 0),
    "LOW_INCOME_DECLINED": ("Low-income application declined", "✖️", "collections", 0, 0.5, 0),
    "BUDGET_BILL": ("Budget billing enrolment", "📆", "collections", 6, 0.25, 0),
    "BUDGET_PLAN_CREATED": ("Budget billing plan set up", "🗓️", "collections", 8, 0.5, 0),
    "READ_RELEASED": ("Released to billing", "📤", "billing", 0, 0.05, 0),
    # Studio work: your field service orders, invoice holds, notes and ownership.
    "FIELD_SERVICE": ("Field service order", "🛠️", "field", 6, 0.5, 0),
    "ORDER_SAVED": ("Order draft saved", "💾", "field", 0, 0, 0),
    "ORDER_LINKED": ("Field service order linked", "🔗", "field", 0, 0, 0),
    "ORDER_RELEASED": ("Order released", "📋", "field", 2, 0.1, 0),
    "ORDER_DISPATCHED": ("Order dispatched", "📟", "field", 1, 0.1, 0),
    "ORDER_COMPLETED": ("Field order completed", "🏁", "field", 0, 0.1, 0),
    "INVOICE_HOLD": ("Invoice hold", "🧊", "invoice", 4, 0, 0),
    "INVOICE_DEFERRED": ("Invoice held back", "⏸️", "invoice", 0, 0.1, 0),
    "INVOICE_UNHOLD": ("Invoice hold removed", "▶️", "invoice", 2, 0, 0),
    "CASE_NOTE": ("Case note", "🗒️", "wm", 1, 0, 0),
    # Contact centre work (utilsim/m2c/contact.py): a disputed bill or a complaint becomes a case for the analysts.
    "BILL_DISPUTE": ("Bill dispute", "🗣️", "billing", 0, 0.25, 10),
    "DISPUTE_EXPLAINED": ("Bill explained to the customer", "💬", "billing", 6, 0, 0),
    "CHECK_READ": ("Check read", "🔍", "billing", 0, 0.25, 0),
    "COMPLAINT": ("Customer complaint", "😠", "cx", 0, 0.25, 20),
    "COMPLAINT_ANSWERED": ("Complaint answered", "✉️", "cx", 10, 0, 0),
    "PAYMENT_RISK_RAISED": ("Pays later after bad service", "⏳", "collections", 0, 0, 10),
    "AUTOPAY_CANCELLED": ("Cancelled automatic payments", "🚪", "collections", 0, 0, 15),
    "CASE_ASSIGNED": ("Case assigned", "👤", "wm", 0, 0, 0),
}
EDGE_TYPES = ("caused_by", "triggered", "resulted_in", "blocked_by", "resolved_by", "escalated_to", "required_for",
              "compensated_by")

# Exception types in the order an RPA programme automates them (process.rpa_coverage picks the first share).
EXCEPTIONS = ("COMM_FAIL", "NO_ACCESS", "NO_READ", "ZERO_USAGE", "BILL_CREDIT", "LOW_USAGE", "PERIOD_LENGTH",
              "ERRATIC", "HIGH_USAGE", "VACANT_CONSUMING", "REGISTER_REGRESSION", "PERSISTENT_LOW",
              "CONSECUTIVE_ESTIMATES", "RATE_CLASS", "HIGH_BILL")
CONTACT_TYPES = ("BILL_DISPUTE", "COMPLAINT")  # cases the contact centre opens (a disputed bill, a complaint)
HUMAN_ONLY = ("TRUE_UP", *CONTACT_TYPES)  # exception types no RPA rule covers, whatever process.rpa_coverage says
EXCEPTION_TYPES = (*EXCEPTIONS, *HUMAN_ONLY)
BILL_TYPES = ("HIGH_BILL", "BILL_CREDIT", "RATE_CLASS", "TRUE_UP")
OUTSORTS = ("HIGH_BILL", "BILL_CREDIT")  # billing outsorts RPA may release, up to billing.outsort_auto_release_max
MISSING_TYPES = ("COMM_FAIL", "NO_ACCESS", "NO_READ", "CONSECUTIVE_ESTIMATES")
WORK_TYPES = ("FIELD_SERVICE", "INVOICE_HOLD")  # cases you open in the Studio (an order, an invoice hold)
COLLECTION_TYPES = ("LOW_INCOME", "BUDGET_BILL")  # collections cases on an account (you or the call centre open them)
# Case work kinds that belong to a contract account rather than a read: an invoice hold, a low-income referral and a
# budget billing enrolment (``Case.work``; ``Case.ref`` is the account).
ACCOUNT_WORK = ("hold", "low_income", "budget_bill", "complaint")
# Who raised a case (``createdBy`` on rows and case views).
CREATED_BY = {"ami_head_end": "AMI head-end", "meter_reading_route": "Meter-reading route", "vee_batch": "VEE batch",
              "billing_run": "Billing run", "studio": "You (Utility Studio)", "collections": "Collections (call centre)",
              "contact_centre": "Contact centre"}

QUEUES = {
    "VEE_REVIEW": "VEE review",
    "ESTIMATION": "Missing reads",
    "SUPERVISOR": "Escalations",
    "FIELD": "Field orders",
    "BILLING": "Billing blocks",
    "COLLECTIONS": "Collections",
}

# Clarification categories (Utility Studio). Each case gets one from its type and queue (``category()``); the rest of
# the Studio's list has no engine meaning yet, so filtering by it returns an empty list.
CATEGORIES = {
    "MR Implausibles": "Value exceptions from VEE (VEE_REVIEW)",
    "Meter Read Follow-Up": "Missing reads: comm fail, no access, no read document, consecutive estimates "
                            "(ESTIMATION)",
    "Billing Outsorts": "Billing blocks for a high bill, a large credit or an implausible true-up (HIGH_BILL, "
                        "BILL_CREDIT, TRUE_UP)",
    "Billing Errors": "Billing blocks for a wrong rate class in master data (RATE_CLASS)",
    "Invoice Outsorts": "Invoice holds you placed on an account (INVOICE_HOLD)",
    "Field Work": "Cases in the FIELD queue and your field service orders (FIELD_SERVICE)",
    "Low Income Process": "Low-income programme referrals (LOW_INCOME) by you or the call centre, open until the "
                          "agency decides",
    "Budget Bill Cases": "Budget billing enrolments (BUDGET_BILL) by you or the call centre, open until billing sets "
                         "up the plan",
    "Escalations": "Cases in the SUPERVISOR queue (escalated by VEE, an analyst or you), whatever their type",
    "Bill Correction": "Bills a customer disputed with the contact centre (BILL_DISPUTE): an analyst checks the read "
                       "and rebills or explains",
    "Customer Complaints": "Complaints the contact centre took (COMPLAINT): an analyst answers them",
}
NO_ENGINE_CATEGORIES = ("AMP", "Bill Print Errors", "Billing- see IT Supp", "Invoice Errors")
MY_CASES = "My Assigned Cases"  # not a category: the cases assigned to you


def category(kind: str, queue: str | None, work: str | None = None) -> str:
    """The clarification category of a case of type ``kind`` in ``queue`` (its last queue once resolved)."""
    if work == "order" or queue == "FIELD":
        return "Field Work"
    if queue == "SUPERVISOR":
        return "Escalations"
    if work == "hold":
        return "Invoice Outsorts"
    if kind == "LOW_INCOME":
        return "Low Income Process"
    if kind == "BUDGET_BILL":
        return "Budget Bill Cases"
    if kind == "BILL_DISPUTE":
        return "Bill Correction"
    if kind == "COMPLAINT":
        return "Customer Complaints"
    if kind == "RATE_CLASS":
        return "Billing Errors"
    if kind in BILL_TYPES:
        return "Billing Outsorts"
    if kind in MISSING_TYPES:
        return "Meter Read Follow-Up"
    return "MR Implausibles"


# Simulated SAP MR validation codes → VEE v5 severity categories. Real MRIndependantValidation semantics plug in here.
CODES = {
    "SIM-C01": ("cascade", "Register lower than the previous released read, not a plausible rollover"),
    "SIM-T01": ("tolerance", "Consumption above the high tolerance"),
    "SIM-T02": ("tolerance", "Consumption below the low tolerance"),
    "SIM-Z01": ("zero consumption", "Zero consumption at an occupied premise"),
    "SIM-P01": ("process", "Too many consecutive estimates"),
    "SIM-L01": ("lifecycle", "Move-in or move-out inside the read period"),
    # Diagnoses for the exceptions the consistency and temporal tests raise (no tolerance code of their own).
    "SIM-T03": ("tolerance", "Consumption persistently below the trend share of expected"),
    "SIM-E01": ("consistency", "Consumption erratic against the register's history"),
    "SIM-D01": ("temporal", "Read period shorter or longer than plausible"),
}
CODE_LIST = tuple(CODES)
TESTS = ("SAP VEE diagnosis", "Temporal validity", "Consistency checks", "Process corroboration", "Context signals")
DISPOSITIONS = ("accept", "review", "escalate", "reject")
TRUTH = ("clean", "read_error", "meter_fault", "physics")
ANOMALY_CLASS = {"transposed_digits": "read_error", "misread": "read_error", "stuck_meter": "meter_fault",
                 "slow_meter": "meter_fault", "tamper": "meter_fault", "exchange_registration_failure": "meter_fault",
                 "leak": "physics", "vacant_consuming": "physics", "missing_read": "clean",
                 "consecutive_estimates": "clean"}
REASON = {"AMI": "SIM_TELEMETRY_FAILURE", "AMR": "SIM_DRIVE_BY_MISSED", "MANUAL": "SIM_NO_ACCESS"}
SOURCE = {"AMI": "synthetic-AMI", "AMR": "synthetic-AMR-drive-by", "MANUAL": "synthetic-manual-route"}


def cost(event: str) -> dict[str, float]:
    _, _, _, labor, system, cx = EVENTS[event]
    return {"labor": labor, "system": system, "cx": cx}
