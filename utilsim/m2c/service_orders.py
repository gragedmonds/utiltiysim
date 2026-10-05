"""Common physical jobs, their reasons, and coverage of the supplied order inventory.

The MAT codes are reference labels transcribed from a photo, not engine order IDs or
universal industry codes. A related work type does not establish an exact match.
No arrival rates, durations or extra jobs are inferred from the report's volumes or
medians. In particular, an exchange is counted once regardless of its accounting label.
"""

from copy import deepcopy

# These are job families, not arrival streams. Legacy MAT codes remain reasons or
# accounting labels under one family; grouping must never schedule duplicate work.
WORK_TYPES = (
    {"id": "service_on", "title": "Turn service on", "codes": ("300", "301", "302", "309"),
     "description": "Activate or restore an existing service. The reason determines prerequisites, approval and priority; the physical job is the same.",
     "reasons": {"300": "Start service", "301": "Payment received", "302": "Temporary disconnection ended", "309": "Customer request"},
     "connections": [
         {"status": "available", "trigger": "Payment after a collections disconnection", "job": "Turn service on", "result": "Service and readings resume when reconnection completes"},
         {"status": "planned", "trigger": "Customer calls to start or resume service", "job": "Turn service on", "result": "Verify the account and connection, then restore service on completion"}]},
    {"id": "service_off", "title": "Turn service off", "codes": ("350", "354"),
     "description": "Disconnect an existing service. Move-out, temporary shutdown and debt collection are reasons for this job, with different authorisation rules.",
     "reasons": {"350": "Customer request / move-out", "354": "Non-payment"},
     "connections": [
         {"status": "available", "trigger": "Approved collections disconnection", "job": "Turn service off", "result": "Final read, then no usage or readings while disconnected"},
         {"status": "planned", "trigger": "Move-out reaches its last service day", "job": "Turn service off, due that day", "result": "Check for a continuing account, take the final read and close or transfer service"}]},
    {"id": "meter_visit", "title": "Meter visit", "codes": ("216", "245", "217", "222", "238", "236"),
     "description": "One visit to read, check or investigate a meter. Re-reads, usage questions and suspected faults are purposes for the visit, not separate job families.",
     "reasons": {"216": "Read / re-read", "245": "Transfer / move read", "217": "Investigation", "222": "Suspected tampering", "238": "High bill", "236": "Zero usage"},
     "connections": [
         {"status": "available", "trigger": "Read exception or a manually issued read/case order", "job": "Meter visit", "result": "Return a read, confirm it, report no access or a defect; an investigation can lead to exchange"},
         {"status": "available", "trigger": "Billing reviewer requests field evidence for a high-bill or zero/low-usage case", "job": "Meter visit, when justified", "result": "Return findings to the source case; the reviewer still decides how to resolve it"}]},
    {"id": "meter_maintenance", "title": "Maintain metering equipment", "codes": ("204", "218"),
     "description": "Maintain the meter or its radio module. The component and task determine duration, materials and the result; replacing the whole meter is a separate job.",
     "reasons": {"204": "Radio / ERT module maintenance", "218": "Meter maintenance"},
     "connections": [
         {"status": "available", "trigger": "Gas/water module battery reaches its age limit", "job": "Replace battery", "result": "Prevent or end missed reads caused by a dead battery"},
         {"status": "planned", "trigger": "Inspection finds a repairable meter or module defect", "job": "Maintain the affected component", "result": "Record the repair and restore its reading capability"}]},
    {"id": "meter_exchange", "title": "Exchange meter", "codes": ("212", "206", "213", "207", "201"),
     "description": "Remove the old meter and register its replacement once. CAPEX/OPEX describes how that work is accounted for, not another physical visit.",
     "reasons": {"212": "Replacement", "206": "Replacement", "213": "Replacement", "207": "Replacement", "201": "Periodic replacement"},
     "accounting": {"212": "CAPEX · miscellaneous", "206": "OPEX", "213": "CAPEX", "207": "OPEX · miscellaneous"},
     "connections": [
         {"status": "available", "trigger": "Fault investigation, seal expiry or age programme", "job": "Exchange meter", "result": "Register the new device and initial read; subsequent usage follows that register"},
         {"status": "planned", "trigger": "Exchange is costed", "job": "Apply accounting classification", "result": "Allocate CAPEX/OPEX without creating another exchange"}]},
    {"id": "network_response", "title": "Respond to a network problem", "codes": ("108", "109"),
     "description": "Respond to modelled leaks or loss of supply. Keep the utility, asset, crew, urgency and repair outcome explicit within this common job family.",
     "reasons": {"108": "Main leak", "109": "Loss of supply"},
     "connections": [
         {"status": "available", "trigger": "Modelled outage/leak or eligible no-supply report", "job": "Dispatch the relevant response crew", "result": "Record the response and the modelled incident's repair/restoration"}]},
)

MANUAL_WORK_TYPES = (
    {"id": "meter_visit", "title": "Meter visit", "purposes": [
        {"activity": "Meter investigation", "label": "Investigate meter / usage"},
        {"activity": "Special meter read", "label": "Read / re-read"},
        {"activity": "Access investigation", "label": "Resolve access issue"}]},
    {"id": "meter_exchange", "title": "Exchange meter", "purposes": [
        {"activity": "Meter exchange", "label": "Replace meter"}]},
)


def manual_work_types():
    return deepcopy(list(MANUAL_WORK_TYPES))


def work_profile(activity):
    """Classify legacy order fields without changing their replay or recorded purpose."""
    for work in MANUAL_WORK_TYPES:
        for purpose in work["purposes"]:
            if purpose["activity"] == activity:
                return {"id": work["id"], "title": work["title"], "purpose": purpose["label"]}
    return None


def _item(code, title, group, status, types=(), activities=(), *, behaviour, gap=""):
    return {"code": code, "title": title, "group": group, "status": status,
            "engineTypes": list(types), "manualActivities": list(activities),
            "behaviour": behaviour, "gap": gap}


ORDERS = (
    _item("216", "Meter Reread", "Meter reads", "covered", ("meter_investigation",),
          ("Special meter read",),
          behaviour="Create a field service order from a read or eligible case. The crew can take or confirm a read; the returned check read can then be used to resolve the case."),
    _item("245", "Transfer Read", "Meter reads", "partial", ("move_in", "move_out"),
          ("Special meter read",),
          behaviour="Account opening and closing dates generate visits for non-AMI meters. A move-out and adjacent move-in share a visit.",
          gap="No distinct transfer-read reason or customer-transfer settlement. A manual special read does not transfer the account."),
    _item("204", "ERT Maintenance", "Meter maintenance", "partial", ("ami_battery",),
          behaviour="Gas and water AMI/AMR module batteries are replaced at their age limit; overdue batteries miss reads until replaced.",
          gap="Only battery ageing is modelled. ERT electronics repair, reprogramming and module-only exchanges are separate gaps."),
    _item("218", "Meter Maintenance", "Meter maintenance", "partial", ("meter_investigation", "corrective_exchange"),
          ("Meter investigation",),
          behaviour="VEE investigations inspect meters and can lead to a corrective exchange.",
          gap="Cleaning, minor repairs and other maintenance outcomes have no separate lifecycle."),
    _item("300", "Turn On", "Turn on", "partial", ("move_in", "meter_set"),
          behaviour="Move-in visits and meter sets following new-service construction contribute field workload.",
          gap="These are not a general activation order. Turning an existing disconnected service on currently follows the collections reconnect flow."),
    _item("301", "Reconnect Non Pay", "Turn on", "covered", ("reconnect",),
          behaviour="Payment after a collections disconnection requests reconnection. Crew completion restores service, reads and usage; eligible electric AMI switches operate remotely."),
    _item("302", "Reconnect After TempDisconnect", "Turn on", "not_modelled",
          behaviour="No temporary-disconnection lifecycle is modelled.",
          gap="Needs a temporary service-off request, its reason and a linked restoration order independent of debt collection."),
    _item("309", "Reconnect-Customer Request", "Turn on", "not_modelled",
          behaviour="The existing reconnect job is tied to a collections invoice.",
          gap="Needs a customer-requested restoration flow with service eligibility and a linked prior disconnection."),
    _item("108", "Leak at Street/Sidewalk", "Emergency", "partial", ("outage_repair",),
          behaviour="Water-main breaks raise utility repair work and interrupt supply until the incident's restoration time.",
          gap="Street versus sidewalk location and leak-report reason are not separate service-order categories."),
    _item("109", "No Water-Customer", "Emergency", "covered", ("no_supply",),
          behaviour="A share of background single-premise outage reports dispatches an on-call no-supply responder. This is a generic response workload; utility-specific network outages are handled separately."),
    *(_item(code, title, "Meter replacements / exchanges", "partial",
            ("corrective_exchange", "seal_exchange", "water_meter_replacement"), ("Meter exchange",),
            behaviour="Fault, seal and age programmes generate exchanges. Manual orders can record a new device, initial read and removal read; subsequent readings use the new register.",
            gap=f"{accounting} is a reporting distinction here. Costs are tracked, but these MAT codes and capitalisation rules are not assigned to engine orders; do not count the same exchange twice.")
      for code, title, accounting in (
          ("212", "Meter Exchange Misc-CAPEX", "Miscellaneous CAPEX"),
          ("206", "Meter Exchange-OPEX", "OPEX"),
          ("213", "Meter Exchange-CAPEX", "CAPEX"),
          ("207", "Meter Exchange Misc-OPEX", "Miscellaneous OPEX"))),
    _item("201", "Meter First Periodic Replacement", "Meter replacements / exchanges", "partial",
          ("water_meter_replacement", "seal_exchange"), ("Meter exchange",),
          behaviour="Water-meter service life and electric/gas seal expiry generate planned replacements.",
          gap="The first periodic replacement is not separately classified from later replacements."),
    _item("350", "Turn Off", "Turn off", "partial", ("move_out", "removal"),
          behaviour="Move-out dates generate final-read visits. Abandoned-premise meter removal stops service, readings and billing.",
          gap="A move-out visit alone does not switch service off. Temporary or customer-requested turn-off needs its own service-state lifecycle."),
    _item("354", "Disconnect Non Payment", "Turn off", "covered", ("disconnect",),
          behaviour="An approved collections disconnection raises work. Completion stops service, use and reads; eligible electric AMI switches avoid a truck. Payment or a hold can cancel unstarted work."),
    _item("217", "Investigation", "Investigations", "covered", ("meter_investigation",),
          ("Meter investigation", "Access investigation"),
          behaviour="VEE field visits and manual read/case orders investigate meters or access. Outcomes include read taken, read confirmed, defect found, no access and meter exchanged."),
    _item("222", "Tampering or Theft", "Investigations", "partial", ("meter_investigation", "corrective_exchange"),
          ("Meter investigation",),
          behaviour="The electric-meter fault model includes tampering. Investigation can discover the fault and exchange the meter.",
          gap="No distinct theft order, water-tampering model, evidence workflow or revenue-recovery calculation."),
    _item("238", "High Bill Complaint", "Billing-related investigations", "partial", ("meter_investigation",),
          ("Meter investigation",),
          behaviour="High invoices can generate customer contacts and billing disputes. A related meter/read investigation can supply field evidence.",
          gap="Field evidence is optional: the reviewer can issue a visit from the open billing case. Completing the visit returns findings without settling the billing dispute."),
    _item("236", "Zero Usage", "Billing-related investigations", "partial", ("meter_investigation",),
          ("Meter investigation", "Special meter read"),
          behaviour="Stuck meters and low/implausible readings can enter VEE review and field investigation; billing KPIs expose repeated zero consumption.",
          gap="The reviewer can issue a visit from a zero/low-usage case. There is no unconditional zero-usage dispatch: genuine zero usage is not automatically a meter fault."),
)


def catalogue() -> dict:
    """A small static reference: no replay needed, and no run totals allocated to aliases."""
    from utilsim.m2c.fieldwork import TYPES

    by_code = {code: work for work in WORK_TYPES for code in work["codes"]}
    items = []
    for original in ORDERS:
        o = deepcopy(original)
        work = by_code[o["code"]]
        o.update(referenceGroup=o["group"], group=work["title"], workType=work["id"],
                 reason=work["reasons"][o["code"]], accounting=work.get("accounting", {}).get(o["code"]))
        items.append(o)
    return {
        "schemaVersion": "service-order-coverage/1.1",
        "source": "Selected common work from the supplied report. Original codes are retained as lookup labels; uncommon or unsupported standalone activities have been removed.",
        "statuses": {"covered": "Core work covered", "partial": "Partial match", "not_modelled": "Not modelled"},
        "groups": [w["title"] for w in WORK_TYPES],
        "workTypes": [{**deepcopy(w), "codes": list(w["codes"])} for w in WORK_TYPES],
        "engineTypes": {key: label for key, label, *_ in TYPES},
        "timingNote": "The photo compares standard time with median travel and wrench time. The model's field.<type>.minutes is on-site crew time; road travel and stop time (or fallback travel_minutes) are added separately. Timed incident repairs and VEE visits have their own scheduling rules. Sample volumes and medians have not been imported as rates or duration defaults.",
        "manualNote": "Manual orders start from a read or eligible case in Workspace. Choose Meter visit or Exchange meter, then the visit's purpose. Existing orders retain their recorded purpose and outcomes. The other common work types describe the annual engine and planned links; grouping a reason here does not make a missing lifecycle executable.",
        "orders": items,
    }
