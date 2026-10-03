"""The engine guide: what this engine can do, the impact it can show, how far it scales and what is still missing,
as structured text the Studio renders on its Configuration page (``GET /api/m2c/guide``). The live part (engine kind,
versions, towns, capabilities, request limits) comes from the engine itself; the measured figures were taken on the
development container in October 2026 and are labelled as such.
"""

from __future__ import annotations

from utilsim.m2c import scenarios, tables
from utilsim.m2c.run import EPISODE_MAX, YEAR_DAYS

GUIDE_VERSION = "engine-guide/1.0"
MEASURED_ON = "October 2026, one 4-core development container"

SUMMARY = ("utilsim is a seeded utility-town engine. It generates a town (streets, parcels, buildings, electric, gas "
           "and water networks, customers, meters and reading routes), runs its operations day (incidents, crews, "
           "outages, hydraulics, power flow) and replays a full meter-to-cash year (reads, VEE, work queues, bills, "
           "invoices, payments, collections) deterministically: the same seed and settings always give the same town "
           "and the same year, so every change you make is a controlled experiment.")

CAPABILITIES = (
    {"id": "town", "title": "Town generation",
     "text": "Generic towns built only from their settings and seed (no real places): synthetic streets, parcels, "
             "buildings by era, households, commercial frontage on main roads; 20 to 10,000 homes, from the village "
             "to the city preset. A town's reference names its preset and changes, so any engine rebuilds it byte "
             "for byte.",
     "where": ["Configuration › Town & meters"]},
    {"id": "networks", "title": "Networks",
     "text": "Electric feeders with transformers, sectionalising switches and normally-open ties; gas mains and "
             "district regulators; water mains, pressure zones, elevated tanks and hydrants; AMI collectors.",
     "where": ["Map › Layers"]},
    {"id": "operations", "title": "Operations day",
     "text": "Break a pole, main or house, dispatch crews, send field visits; background incidents at the town's "
             "rates; radial power flow with voltage, loading and back-feed within ratings; water hydraulics with "
             "tanks and leaks; reading rounds by walkers, drive-by vans and AMI polls; play a day, a week or a month.",
     "where": ["Map", "Configuration › Scenario"]},
    {"id": "reading", "title": "Meter reading",
     "text": "AMI, AMR and manual technologies per route; missed reads by technology, cold and no-access repeats; "
             "outages and collector failures make AMI meters miss; every read keeps its register, period, revisions "
             "and billing status.",
     "where": ["Data › Meter reads", "Workspace › Display Meter Reading Results"]},
    {"id": "vee", "title": "VEE",
     "text": "A five-test battery (SAP-style validation codes, temporal validity, consistency, process corroboration, "
             "context) with confidence and dispositions (accept, review, escalate, reject), two estimation methods, "
             "revisions that keep the original, and a scorecard against the simulation's truth.",
     "where": ["Workspace › Resolve Implausible Meter Readings", "VEE scorecard"]},
    {"id": "work", "title": "Exception work",
     "text": "Queues for VEE review, missing reads, escalations, field orders, billing blocks and collections; analysts "
             "and supervisors with hours, review times and pickup lag; RPA coverage; Activity Sequence events with "
             "labour, system and CX cost and carry; your own actions are append-only and dated.",
     "where": ["Workspace › Clarification Case List", "Workspace › Activity sequences"]},
    {"id": "billing", "title": "Billing",
     "text": "Tariffs with energy blocks, delivery, net metering, demand charges, wastewater and HST; proration across "
             "the November rate change; bill checks for high bills, credits, first bills, true-ups and wrong rate "
             "classes; outsorts, rebills and reversals.",
     "where": ["Workspace › Display Billing", "Data › Billing documents", "Data › Tariffs & prices"]},
    {"id": "collections", "title": "Invoices, payments and collections",
     "text": "Invoices per account, payer profiles, pre-authorized debits and returns, reminders, notices with late "
             "fees, disconnection notices and approvals, the winter moratorium, payment arrangements, budget billing, "
             "low-income referrals and dunning holds.",
     "where": ["Workspace › Collections", "Data › Collections"]},
    {"id": "field", "title": "Field service orders and devices",
     "text": "Orders with stages, crews and structured outcomes; meter exchanges with initial and removal reads; the "
             "device history of every meter slot; one access visit per premise.",
     "where": ["Workspace › Field Work", "Data › Device changes"]},
    {"id": "scenarios", "title": "Scenarios and episodes",
     "text": f"A library of {len(scenarios.SCENARIOS)} situations you inflict from any day of the calendar; each is "
             "dated setting changes, optionally ramped, absolute or relative to the base; the engine replays the year "
             "with each day's settings and every page shows the result.",
     "where": ["Year"]},
    {"id": "data", "title": "Data tables",
     "text": f"{len(tables.SPECS)} tables of the town and the run as of the run date, with facets, search, sorting, "
             "paging and CSV download; linked values open their record.",
     "where": ["Data"]},
    {"id": "reporting", "title": "Reporting",
     "text": "The year month by month with episodes shaded; summary KPIs and period windows; the VEE scorecard; "
             "outage follow-up and AMI collector groups.",
     "where": ["Year", "Workspace › Statistics", "Workspace › Outage Follow-up"]},
    {"id": "contact", "title": "Contact centre",
     "text": "Sixteen reasons customers get in touch (high bill, bill question, bill wrong, back bill, balance, online "
             "account, can't pay, payment problem, disconnected, start and stop service, new connection, meter access, "
             "outage report, gas odour, complaint), each triggered by what happens in the year: invoices, billing "
             "errors, rebills and catch-up bills, dunning, returned debits, move-ins and move-outs, no-access reads, "
             "field visits and the year's outages and leaks. Self-service, an emergency line, and agents in opening "
             "hours with patience, retries, call backs, repeat contacts and complaints. Every rate, handling time and "
             "staffing level is a run setting, and episodes can change them from a day.",
     "where": ["Configuration › Contact centre", "Year", "Data › Contact centre"]},
    {"id": "incidents", "title": "Outages and leaks over the year",
     "text": "The operations day's background incidents drawn for every date of the year (the same storm or leak the "
             "map shows on that date): who loses power or water, for how long, and who smells gas. Storm, incident "
             "and restoration factors are run settings, so Storm season can be inflicted from a day.",
     "where": ["Configuration › Outages & leaks over the year", "Data › Outages & leaks"]},
    {"id": "weather", "title": "Weather year",
     "text": "Daily temperatures drive usage, flows, state frames and reading conditions through the year.",
     "where": ["Map", "Data › Usage by month"]},
    {"id": "hosting", "title": "Hosting",
     "text": "The same engine runs as a serverless function for the prebuilt towns and small generated towns, and "
             "locally with the full API (exports, renders, GeoJSON, large towns).",
     "where": ["Configuration › Engine & data"]},
)

IMPACTS = (
    {"title": "Backlog and days to resolve", "text": "Open cases by queue at any date, pickup and resolution times, "
     "escalations.", "where": "Year, Workspace › Statistics, Worklists"},
    {"title": "Estimated and missed reads", "text": "Share of reads missed and estimated by month and technology, "
     "consecutive estimates, true-ups.", "where": "Year, Data › Meter reads, Data › Usage by month"},
    {"title": "Cost and carry", "text": "Labour, system and CX cost per event and per month; billing and receivable "
     "carry.", "where": "Year, Workspace › Activity sequences"},
    {"title": "Billing quality", "text": "Blocked bills, rebills and reversals, billing error against the simulation's "
     "truth.", "where": "Year, Workspace › Statistics, Data › Billing documents"},
    {"title": "Cash", "text": "Invoiced, collected, receivable and overdue by month; days to invoice and to pay.",
     "where": "Year, Data › Invoices, Data › Account ledger"},
    {"title": "Collections", "text": "Reminders, notices, disconnection notices and disconnections; every account's "
     "collections phase; arrangements, holds, referrals.", "where": "Year, Data › Accounts in collections"},
    {"title": "VEE effectiveness", "text": "Precision and recall against injected anomalies, days to flag, what passes "
     "undetected.", "where": "VEE scorecard, Data › Meter reads"},
    {"title": "Reliability", "text": "Interruptions, SAIDI, lost use, AMI last gasps and the reads an outage cost.",
     "where": "Map, Workspace › Outage Follow-up"},
    {"title": "Field work", "text": "Truck rolls, orders by stage, exchanges, visits per premise.",
     "where": "Workspace › Field Work, Data › Field service orders"},
)

MEASURED = (
    {"town": "Village", "homes": 480, "accounts": 635, "registers": 1698, "generateS": 3, "replayS": 2},
    {"town": "Small town", "homes": 1900, "accounts": 2368, "registers": 6350, "generateS": 9, "replayS": 6},
    {"town": "Town", "homes": 3300, "accounts": 3969, "registers": 10071, "generateS": 14, "replayS": 11},
    {"town": "Large town", "homes": 5500, "accounts": 6598, "registers": 16416, "generateS": 23, "replayS": 15,
     "memoryMB": 260, "documents": 187767, "invoices": 73106},
)

LIMITS = (
    {"title": "Hosted engine (serverless function)",
     "text": "One request has 60 seconds and about 1 GB. Generation finishes in time up to roughly 2,000 homes; a "
             "year replays comfortably up to about 7,000 accounts (15 s cold) and approaches the limit between "
             "15,000 and 20,000 accounts. Each new instance replays the year once before its first answer. Every "
             "response stays under 4.5 MB, which is why every list is paged."},
    {"title": "Local engine or an always-on container",
     "text": "One town up to roughly 20,000 to 25,000 accounts per run (a few minutes, 1 to 2 GB). The replay is "
             "linear in registers: the reads and VEE side is vectorised, the bills, invoices and collections side is "
             "per-invoice Python. The generator is built for towns up to 10,000 homes."},
    {"title": "Beyond one town",
     "text": "A utility of 100,000 accounts is forty towns of 2,500 or ten of 10,000 run side by side with a roll-up, "
             "which is not built yet (see Gaps)."},
    {"title": "Calendar",
     "text": f"One calendar year (2026, {YEAR_DAYS} days), twelve billing cycles, twenty-one portions. Multi-year "
             "needs chaining (see Gaps)."},
)

GAPS = (
    {"title": "Outages in the year's reads", "text": "The year's outages and leaks reach the contact centre, but not "
     "yet the reads, VEE or bills: only interruptions you carry from a day on the map do.", "plan": "Feed the year's "
     "incidents into the replay as interruptions (AMI misses, lost use, VEE outage events)."},
    {"title": "Contact centre feedback", "text": "Contacts do not create back-office work yet: a bill dispute or a "
     "complaint is answered and counted, but opens no case for the analysts.", "plan": "Disputes and complaints open "
     "Billing cases; long queues and failed resolutions raise churn and collections risk."},
    {"title": "Undetected water loss", "text": "No mains leakage fraction and no supplied-versus-billed water "
     "balance.", "plan": "Per-zone unbilled loss that shows in flows but never in bills, and a monthly water-balance "
     "report."},
    {"title": "Multiple years", "text": "One calendar year; nothing carries into a second.", "plan": "Chain years: "
     "year two starts from year one's balances, arrears, open cases, device ages and backlog."},
    {"title": "A utility above the town", "text": "Every run, setting, episode and view keys on one town; no "
     "cross-town staffing, no roll-ups, no per-state rules.", "plan": "A utility index of towns with per-town "
     "presets, sharded runs and merged views."},
    {"title": "Technology mix and rollouts", "text": "The AMI, AMR and manual mix is set per town at generation and "
     "applied per route; no street or district rules, no mid-year AMR-to-AMI rollout.", "plan": "Generator rules "
     "by street class, district and premise type; a rollout episode on the device-exchange machinery."},
    {"title": "Rate change as an episode", "text": "The tariff version change is a year-level setting, not something "
     "inflicted from a day.", "plan": "Make the change date and size per-day settings."},
    {"title": "Payer behaviour as a run setting", "text": "On-time, late and at-risk shares are fixed when the town "
     "is generated.", "plan": "A run-scoped payment-stress episode."},
    {"title": "Saved runs across devices", "text": "Your actions and episodes live in this browser.", "plan": "A "
     "small store for named runs."},
    {"title": "Always-on hosting", "text": "The serverless engine replays on cold start, rebuilds generated towns per "
     "instance and cannot hold large towns.", "plan": "The full API in one container with a volume, the function as "
     "fallback."},
    {"title": "Map art", "text": "Wall meters, valves, fuses, reclosers, switches, collectors and damaged states have "
     "no sprites yet; evening-peak back-feed limits differ by town.", "plan": "The next sprite batch and the "
     "back-feed sizing pass."},
    {"title": "Analyst exports", "text": "Parquet and CSV dumps of the snapshot and PNG renders are local-only.",
     "plan": "They come with the container."},
    {"title": "Clarification categories without engine meaning", "text": "AMP, Bill Correction, Bill Print Errors, "
     "Billing - see IT Supp and Invoice Errors list no cases.", "plan": "Model the processes behind them or drop them."},
)


def guide(health: dict | None = None) -> dict:
    """``engine-guide/1.0``: the guide with the engine's live status folded in."""
    h = health or {}
    return {"schemaVersion": GUIDE_VERSION, "title": "Engine guide", "summary": SUMMARY,
            "capabilities": list(CAPABILITIES), "impacts": list(IMPACTS),
            "scale": {"measuredOn": MEASURED_ON, "measured": list(MEASURED), "limits": list(LIMITS)},
            "gaps": list(GAPS),
            "status": {"engine": h.get("engine"), "generatorVersion": h.get("generatorVersion"),
                       "schemaVersion": h.get("schemaVersion"), "towns": h.get("towns", []),
                       "capabilities": h.get("capabilities", {}),
                       "limits": {"episodes": EPISODE_MAX, "actions": 2000, "interruptions": 500,
                                  "pageRows": tables.PAGE_MAX, "csvRows": tables.CSV_MAX, "yearDays": YEAR_DAYS,
                                  "scenarios": len(scenarios.SCENARIOS), "tables": len(tables.SPECS)}}}
