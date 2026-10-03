"""The scenario library: situations an analyst can inflict on the utility from a day of the year. Each scenario is
one or more episode templates (dated setting overrides on the run's base settings, relative to the day it is
inflicted) with what to watch afterwards. The engine only lists them; the Year page turns a template into the run's
``episodes`` and the run replays the year with the day's settings (``M2CRun.cfg_at``). Values are absolute or
operators on the base (``"*0.5"``, ``"+2"``, ``"-1"``), so a scenario fits any town.
"""

from __future__ import annotations

SCENARIOS_VERSION = "m2c-scenarios/1.0"
GROUPS = (("staffing", "Staffing"), ("reading", "Meter reading"), ("vee", "VEE"), ("billing", "Billing"),
          ("collections", "Collections"), ("anomalies", "Meters & anomalies"), ("operations", "Operations"))


def _ep(title: str, settings: dict, *, start: int = 0, days: int | None = None, ramp: int = 0) -> dict:
    return {"title": title, "startOffset": start, "durationDays": days, "ramp": ramp, "settings": settings}


SCENARIOS: tuple[dict, ...] = (
    {"id": "half_staff_billing", "title": "Billing at half staff", "group": "staffing",
     "description": "Half the billing analysts leave the exception queues from this day; the ones who stay also cover "
                    "the phones, so queue hours halve and a new exception waits a week longer for a first look.",
     "watch": "Open cases and days to resolve roughly double within weeks; VEE review backlog, carry and billing blocks "
              "wait longer. Small towns absorb a lot: add No-access summer to see it bite.",
     "tags": ["backlog", "carry", "estimates"],
     "episodes": [_ep("Half the analysts", {"process": {"analysts": "*0.5", "analyst_hours_per_day": "*0.5",
                                                       "analyst_queue_days_min": "+4", "analyst_queue_days_max": "+8"}})]},
    {"id": "no_analysts", "title": "Nobody on the queues", "group": "staffing",
     "description": "The analysts are pulled onto a project for six weeks; RPA keeps resolving its share, everything "
                    "else waits.",
     "watch": "Open cases pile up by exception type; estimates and blocked bills stay unreleased; carry runs daily.",
     "tags": ["backlog", "carry"],
     "episodes": [_ep("No analysts", {"process": {"analysts": 0}}, days=42)]},
    {"id": "supervisor_away", "title": "Supervisor away", "group": "staffing",
     "description": "No supervisor approves escalations for six weeks.",
     "watch": "The Escalations queue grows and high-impact cases age; releases resume when the supervisor is back.",
     "tags": ["escalations"],
     "episodes": [_ep("No supervisor", {"process": {"supervisors": 0}}, days=42)]},
    {"id": "rpa_outage", "title": "Automation switched off", "group": "staffing",
     "description": "The RPA rules are disabled for a month after a system change; every exception goes to a person.",
     "watch": "Cases opened stay level but resolutions shift to analysts; the backlog and labour cost rise.",
     "tags": ["backlog", "cost"],
     "episodes": [_ep("RPA off", {"process": {"rpa_coverage": 0}}, days=30)]},
    {"id": "no_access_season", "title": "No-access summer", "group": "reading",
     "description": "Walked routes find gates locked and meters inside for three months; a missed premise is usually "
                    "missed again the next month.",
     "watch": "Missed and estimated reads on manual routes, consecutive-estimate cases, field orders and true-ups.",
     "tags": ["missed reads", "estimates", "field"],
     "episodes": [_ep("Locked gates", {"reading": {"manual_no_access": 0.3, "no_access_repeat": 0.7}}, days=92)]},
    {"id": "ami_heat_dropouts", "title": "AMI dropouts in the heat", "group": "reading",
     "description": "Two months of heat: AMI endpoints drop out and billing reads stay missing after the retry window.",
     "watch": "COMM_FAIL cases in the Missing reads queue, estimated bills and the collector groups list.",
     "tags": ["missed reads", "AMI"],
     "episodes": [_ep("AMI dropouts", {"reading": {"ami_missed_read": 0.08}}, days=61)]},
    {"id": "amr_drift", "title": "ERT/AMR fleet drift", "group": "anomalies",
     "description": "An ageing drive-by fleet: over four months, every meter fault and read error on AMR meters "
                    "becomes five times as likely. Nothing announces it; only VEE's tolerances and the trend tests "
                    "can catch it.",
     "watch": "Slow-meter and misread onsets on AMR meters, low-use flags, billed use drifting below truth, and what "
              "VEE misses (the scorecard).",
     "tags": ["undetected", "revenue", "AMR"],
     "episodes": [_ep("Fleet drift", {"anomalies": {"amr_factor": 5.0}}, ramp=120)]},
    {"id": "anomaly_wave", "title": "Anomaly wave", "group": "anomalies",
     "description": "Everything that can go wrong at the meter goes wrong three times as often for four months, "
                    "building up over the first two.",
     "watch": "Exceptions by type, VEE precision, field orders, estimated and adjusted reads.",
     "tags": ["anomalies", "field"],
     "episodes": [_ep("Anomaly wave", {"anomalies": {k: "*3" for k in ("leak", "stuck_meter", "slow_meter",
                                                                      "transposed_digits", "misread",
                                                                      "vacant_consuming", "tamper")}},
                      days=122, ramp=60)]},
    {"id": "vee_loosened", "title": "VEE loosened", "group": "vee",
     "description": "Wider tolerances and no zero-use check from this day: misreads and faults pass as plausible and "
                    "get billed.",
     "watch": "Fewer cases but more billing error against truth, high-bill outsorts and later corrections.",
     "tags": ["undetected", "billing error"],
     "episodes": [_ep("Wide tolerances", {"vee": {"high_ratio": 3.5, "low_ratio": 0.15, "trend_ratio": 0.5,
                                                   "zero_at_occupied": False}})]},
    {"id": "vee_tightened", "title": "VEE tightened", "group": "vee",
     "description": "Narrow tolerances and a high auto-accept bar from this day: many ordinary reads are flagged.",
     "watch": "The VEE review queue, false positives (precision on the scorecard), analyst hours and carry.",
     "tags": ["backlog", "false positives"],
     "episodes": [_ep("Narrow tolerances", {"vee": {"high_ratio": 1.25, "low_ratio": 0.7, "accept_confidence": 0.95,
                                                   "escalate_impact": 60.0}})]},
    {"id": "data_quality_slip", "title": "Master data slips", "group": "billing",
     "description": "A migration leaves wrong rate classes in billing master data: installations are billed on the "
                    "wrong tariff five times as often for four months.",
     "watch": "RATE_CLASS billing blocks, rebills and the rate billed now on the Installations table.",
     "tags": ["billing blocks", "rebills"],
     "episodes": [_ep("Wrong rate classes", {"billing": {"data_error_rate": "*5"}}, days=122)]},
    {"id": "blocks_wait_for_you", "title": "Billing blocks wait for you", "group": "billing",
     "description": "The analysts stop working the billing queue; every blocked bill waits for your decision in the "
                    "Studio.",
     "watch": "The Billing blocks queue and the invoices it holds back; carry while they wait.",
     "tags": ["billing blocks", "carry"],
     "episodes": [_ep("Billing queue is yours", {"billing": {"billing_queue_worked_by": "you"}})]},
    {"id": "pad_failures", "title": "Bank debit failures", "group": "collections",
     "description": "A payment processor fault returns pre-authorized debits for six weeks.",
     "watch": "Rejected payments, NSF fees, the Returned debits list and overdue amounts.",
     "tags": ["payments", "fees"],
     "episodes": [_ep("Returned debits", {"billing": {"pad_reject_rate": 0.08}}, days=45)]},
    {"id": "collections_lenient", "title": "Lenient collections", "group": "collections",
     "description": "Reminders, notices and disconnection notices go out later from this day.",
     "watch": "Overdue amounts and receivables grow; fewer disconnection notices; collections phases shift.",
     "tags": ["receivables", "dunning"],
     "episodes": [_ep("Slower dunning", {"billing": {"reminder_days": 14, "notice_days": 35, "disconnect_days": 75}})]},
    {"id": "collections_aggressive", "title": "Aggressive collections", "group": "collections",
     "description": "Dunning steps come fast with a doubled late fee from this day.",
     "watch": "Notices and disconnection notices per month, late fees, complaints by way of call-centre referrals.",
     "tags": ["dunning", "fees"],
     "episodes": [_ep("Fast dunning", {"billing": {"reminder_days": 5, "notice_days": 14, "disconnect_days": 30,
                                                     "late_fee_pct": 3.0}})]},
    {"id": "long_moratorium", "title": "Longer winter moratorium", "group": "collections",
     "description": "The winter disconnection moratorium runs from mid-October to the end of May this year.",
     "watch": "Winter holds, arrears carried through spring, and the release wave when it ends.",
     "tags": ["moratorium", "arrears"],
     "episodes": [_ep("Long moratorium", {"billing": {"moratorium_start": "10-15", "moratorium_end": "05-31"}})]},
)
COMING: tuple[dict, ...] = (
    {"id": "storm_season", "title": "Storm season", "group": "operations",
     "description": "Months of storms: more line faults, outages and AMI last gasps feeding missed reads and estimates. "
                    "Needs the engine to generate the year's operations itself (next step)."},
    {"id": "water_loss", "title": "Undetected water loss", "group": "operations",
     "description": "Non-revenue water rising towards 30% of supply with no alarm until the water balance is checked. "
                    "Needs the unbilled-loss physics and the water balance report (next step)."},
)
BY_ID = {s["id"]: s for s in SCENARIOS}


def catalog() -> dict:
    """``m2c-scenarios/1.0``: the groups, the scenarios with their episode templates, and the ones still coming."""
    return {"schemaVersion": SCENARIOS_VERSION, "groups": [{"id": g, "title": t} for g, t in GROUPS],
            "scenarios": list(SCENARIOS), "coming": list(COMING)}
