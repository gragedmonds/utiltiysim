"""The scenario library: situations an analyst can inflict on the utility from a day of the year. Each scenario is
one or more episode templates (dated setting overrides on the run's base settings, relative to the day it is
inflicted) with what to watch afterwards. The engine only lists them; the Year page turns a template into the run's
``episodes`` and the run replays the year with the day's settings (``M2CRun.cfg_at``). Values are absolute or
operators on the base (``"*0.5"``, ``"+2"``, ``"-1"``), so a scenario fits any town.
"""

from __future__ import annotations

SCENARIOS_VERSION = "m2c-scenarios/1.0"
GROUPS = (("starters", "Starter setups"), ("staffing", "Staffing"), ("reading", "Meter reading"), ("vee", "VEE"), ("billing", "Billing"),
          ("collections", "Collections"), ("anomalies", "Meters & anomalies"), ("contact", "Contact centre"),
          ("field", "Field work"), ("operations", "Operations"))


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
    {"id": "collections_rule", "title": "Collections rule approves disconnections", "group": "collections",
     "description": "From this day a collections rule approves every disconnection notice as it is issued, instead of "
                    "waiting for a person in the Collections worklist.",
     "watch": "Notices turn into disconnections at the earliest day; most customers pay and are reconnected the next "
              "business day. Disconnected contacts follow, and the meter technicians get disconnects and reconnects "
              "(AMI electric meters with a switch are done remotely). The winter moratorium still holds notices.",
     "tags": ["disconnections", "field work", "contacts"],
     "episodes": [_ep("Rule approves disconnections", {"billing": {"disconnect_rule_share": 1.0}})]},
    {"id": "meter_tech_shortage", "title": "Meter technicians short", "group": "field",
     "description": "Half the meter technicians are off for two months (injuries, a retirement, a vacancy not filled).",
     "watch": "VEE field visits still take their time first and customer work goes ahead of planned work, so planned "
              "meter work (seal samples, batteries, water meter replacement) backs up and goes overdue. It bites "
              "hardest from March to May, when the seal samples are due; in high summer the meter work is light.",
     "tags": ["field work", "backlog", "overtime"],
     "episodes": [_ep("Half the meter technicians", {"field": {"crew_meter": {"per_1000_premises": "*0.5"}}}, days=60)]},
    {"id": "ami_conversion", "title": "AMI conversion programme", "group": "field",
     "description": "The utility converts AMR and manually read meters to AMI, route by route, with contract "
                    "installers joining the meter technicians.",
     "watch": "AMI conversion orders fill the meter maintenance programme through the season; capital materials "
              "climb. The converted meters keep their old reading method in this run (the conversion does not yet "
              "reach the reads).",
     "tags": ["field work", "capital", "AMI"],
     "episodes": [_ep("Convert 40% of AMR and manual meters", {"field": {"ami_conversion": {"rate": 0.4},
                                                                      "crew_meter": {"per_1000_premises": "*2"}}})]},
    {"id": "seal_lot_failures", "title": "Seal lots fail sampling", "group": "field",
     "description": "From this day every lot whose sample finishes testing fails compliance sampling (a meter "
                    "model drifting out of tolerance).",
     "watch": "Each failed lot has every other meter exchanged through the rest of the year, due 31 December: seal "
              "exchanges, the meter technicians' hours and materials jump. Add Meter technicians short to see the "
              "exchanges compete with the rest of the meter work.",
     "tags": ["field work", "compliance", "meters"],
     "episodes": [_ep("Lots fail", {"field": {"seal_lot_pass_rate": 0.0}})]},
    {"id": "contractor_stoppage", "title": "Construction crews off the job", "group": "field",
     "description": "The construction contractor stops work for six weeks (a dispute, or crews moved to another "
                    "utility's storm recovery).",
     "watch": "New services and main renewal wait: capital construction backlog grows and on-time falls; meter sets "
              "follow late. Work not built by the end of the season carries into next year.",
     "tags": ["field work", "capital", "backlog"],
     "episodes": [_ep("No construction crews", {"field": {"crew_construction": {"per_1000_premises": 0}}}, days=42)]},
    {"id": "storm_season", "title": "Storm season", "group": "operations",
     "description": "Three months with three times the storm days: more overhead line faults, longer outages, and the "
                    "outage reports that come with them.",
     "watch": "Outage contacts and the emergency line climb on storm days; with one agent the queue spills into "
              "hang-ups and call backs (Year: contact charts; Data: Outages & leaks, Contacts). The line crews' "
              "outage repairs and overtime climb too (Field work). The year's reads do not see these outages yet.",
     "tags": ["outages", "contact centre", "field work"],
     "episodes": [_ep("Storms ×3", {"outages": {"storm_factor": "*3"}}, days=92)]},
    {"id": "phones_mornings_only", "title": "Lines open mornings only", "group": "contact",
     "description": "For a month the agents cover the phones only until 1 pm; the rest of the day goes to the "
                    "billing backlog.",
     "watch": "Contacts squeeze into four hours: longer waits, more hang-ups and call backs, more callers who find "
              "the lines closed and try again.",
     "tags": ["contact centre", "abandonment"],
     "episodes": [_ep("Phones until 1 pm", {"contact": {"close_hour": 13.0}}, days=30)]},
    {"id": "ivr_down", "title": "IVR and website down", "group": "contact",
     "description": "Self-service is out for ten days: every balance check, password reset and outage report needs "
                    "an agent.",
     "watch": "Contacts to agents roughly double; the service level drops and hang-ups rise until self-service is back.",
     "tags": ["contact centre", "self-service"],
     "episodes": [_ep("No self-service", {"contact": {"self_serve_factor": 0}}, days=10)]},
    {"id": "second_agent", "title": "Hire a second agent", "group": "contact",
     "description": "A second agent joins the phones from this day.",
     "watch": "Waits, hang-ups and call backs fall; staffing cost and idle time rise. Compare with the busiest months.",
     "tags": ["contact centre", "staffing"],
     "episodes": [_ep("Second agent", {"contact": {"agents": "+1"}})]},
)
# Starter setups deliberately combine existing supported effects. They are ordinary episodes,
# so the wizard and Year view use the same authoritative settings and editable periods.
SCENARIOS += (
    {"id": "starter_busy", "title": "A little busy", "group": "starters",
     "description": "A quarter of extra missed reads and payment hiccups. The team is still at full strength.",
     "watch": "Missing reads, estimates and returned debits, compared with normal operations.",
     "tags": ["starter", "light pressure"],
     "episodes": [_ep("A busier quarter", {"reading": {"ami_missed_read": "*1.5"},
                                             "billing": {"pad_reject_rate": "*1.5"}}, days=90)]},
    {"id": "starter_pressure", "title": "Under pressure", "group": "starters",
     "description": "A quarter with half the queue hours, more missed reads and billing master-data mistakes.",
     "watch": "A growing backlog, blocked bills, estimates and labour cost.",
     "tags": ["starter", "backlog", "billing"],
     "episodes": [_ep("A stretched team", {"process": {"analyst_hours_per_day": "*0.5"},
                                            "reading": {"ami_missed_read": "*2"},
                                            "billing": {"data_error_rate": "*2"}}, days=90)]},
    {"id": "starter_chaos", "title": "Organised chaos", "group": "starters",
     "description": "Half the billing team, patchy AMI, and more returned debits for a quarter. Automation also "
                    "disappears for the first month, then returns.",
     "watch": "Queue recovery when automation returns, delayed bills, returned debits and overdue balances.",
     "tags": ["starter", "recovery", "cash flow"],
     "episodes": [_ep("A rough quarter", {"process": {"analysts": "*0.5", "analyst_hours_per_day": "*0.5"},
                                            "reading": {"ami_missed_read": 0.08},
                                            "billing": {"pad_reject_rate": 0.08}}, days=90),
                  _ep("Automation takes a holiday", {"process": {"rpa_coverage": 0}}, days=30)]},
    {"id": "catchup_team", "title": "The catch-up team", "group": "staffing",
     "description": "A six-week recovery effort doubles queue hours and adds two analysts to clear old cases.",
     "watch": "Backlog and case age falling, alongside higher staffing costs.",
     "tags": ["recovery", "cost"],
     "episodes": [_ep("Extra hands on the queues", {"process": {"analysts": "+2", "analyst_hours_per_day": "*2"}},
                      days=42)]},
    {"id": "migration_hangover", "title": "The migration hangover", "group": "billing",
     "description": "A billing migration leaves wrong rate classes for a month. Automation is off for two weeks; "
                    "then a four-week catch-up shift tackles the backlog.",
     "watch": "Blocked bills and rebills during the migration, then the shape and cost of recovery.",
     "tags": ["migration", "recovery", "rebills"],
     "episodes": [_ep("Migration errors", {"billing": {"data_error_rate": "*5"}}, days=30),
                  _ep("Manual checks only", {"process": {"rpa_coverage": 0}}, days=14),
                  _ep("Catch-up shift", {"process": {"analyst_hours_per_day": "*1.5"}}, start=30, days=28)]},
)
COMING: tuple[dict, ...] = (
    {"id": "water_loss", "title": "Undetected water loss", "group": "operations",
     "description": "Non-revenue water rising towards 30% of supply with no alarm until the water balance is checked. "
                    "Needs the unbilled-loss physics and the water balance report (next step)."},
)
BY_ID = {s["id"]: s for s in SCENARIOS}


def catalog() -> dict:
    """``m2c-scenarios/1.0``: the groups, the scenarios with their episode templates, and the ones still coming."""
    return {"schemaVersion": SCENARIOS_VERSION, "groups": [{"id": g, "title": t} for g, t in GROUPS],
            "scenarios": list(SCENARIOS), "coming": list(COMING)}
