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
    "CONSECUTIVE_ESTIMATES": ("Consecutive estimates", "🔁", "vee", 0, 0.25, 0),
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
    "METER_EXCHANGE": ("Meter exchanged", "🔧", "field", 40, 0, 0),
    "SPECIAL_READ": ("Special read", "🔍", "field", 0, 0, 0),
    # Read outcomes.
    "ESTIMATE_CREATED": ("Estimate created", "🧮", "vee", 0, 0.25, 0),
    "READ_ADJUSTED": ("Read adjusted", "📝", "vee", 0, 0.05, 0),
    "READ_HELD": ("Read held by open case", "⏸️", "vee", 0, 0, 0),
    "READ_RELEASED": ("Released to billing", "📤", "billing", 0, 0.05, 0),
}
EDGE_TYPES = ("caused_by", "triggered", "resulted_in", "blocked_by", "resolved_by", "escalated_to", "required_for",
              "compensated_by")

# Exception types in the order an RPA programme automates them (process.rpa_coverage picks the first share).
EXCEPTIONS = ("COMM_FAIL", "NO_ACCESS", "NO_READ", "ZERO_USAGE", "LOW_USAGE", "PERIOD_LENGTH", "ERRATIC",
              "HIGH_USAGE", "VACANT_CONSUMING", "REGISTER_REGRESSION", "CONSECUTIVE_ESTIMATES")
MISSING_TYPES = ("COMM_FAIL", "NO_ACCESS", "NO_READ", "CONSECUTIVE_ESTIMATES")

QUEUES = {
    "VEE_REVIEW": "VEE review",
    "ESTIMATION": "Missing reads",
    "SUPERVISOR": "Escalations",
    "FIELD": "Field orders",
}

# Simulated SAP MR validation codes → VEE v5 severity categories. Real MRIndependantValidation semantics plug in here.
CODES = {
    "SIM-C01": ("cascade", "Register lower than the previous released read, not a plausible rollover"),
    "SIM-T01": ("tolerance", "Consumption above the high tolerance"),
    "SIM-T02": ("tolerance", "Consumption below the low tolerance"),
    "SIM-Z01": ("zero consumption", "Zero consumption at an occupied premise"),
    "SIM-P01": ("process", "Too many consecutive estimates"),
    "SIM-L01": ("lifecycle", "Move-in or move-out inside the read period"),
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
