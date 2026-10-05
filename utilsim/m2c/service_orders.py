"""Coverage of the supplied water-utility service-order inventory.

The MAT codes are reference labels transcribed from a photo, not engine order IDs or
universal industry codes. A related work type does not establish an exact match.
No arrival rates, durations or extra jobs are inferred from the report's volumes or
medians. In particular, an exchange is counted once regardless of its accounting label.
"""


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
    _item("106", "Leak at Property", "Emergency", "not_modelled",
          behaviour="Water-main breaks are modelled, but a water leak at a property is not a distinct incident.",
          gap="Needs a water service-line or private-side leak, ownership boundary and repair outcome. A gas service leak is not an equivalent water event."),
    _item("109", "No Water-Customer", "Emergency", "covered", ("no_supply",),
          behaviour="A share of background single-premise outage reports dispatches an on-call no-supply responder. This is a generic response workload; utility-specific network outages are handled separately."),
    _item("105", "Emergency-Other", "Emergency", "partial", ("no_supply", "outage_repair"),
          behaviour="Known no-supply reports and modelled network incidents already create emergency work.",
          gap="There is no catch-all emergency demand stream or free-form emergency outcome."),
    _item("111", "Sewer Odor Complaint", "Emergency", "not_modelled",
          behaviour="The simulator serves electricity, water and gas; it has no wastewater network.",
          gap="Needs sewer assets, complaint causes and wastewater response work. Do not substitute gas odour."),
    _item("107", "No Water-Hydrant", "Emergency", "partial", ("hydrant_flush", "hydrant_repair"),
          behaviour="Hydrant flushing and inspection can find a defect and raise a hydrant repair.",
          gap="No emergency hydrant no-water report or hydrant-flow outcome is modelled."),
    _item("227", "Third Party Damage", "Emergency", "partial", ("outage_repair",),
          behaviour="The incident model can represent the resulting outage and repair workload.",
          gap="Third-party damage is not an incident cause; liability, recovery and damage-specific arrivals are not modelled."),
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
          gap="High-bill contacts do not automatically create a dedicated field visit. A read investigation does not itself settle the billing dispute."),
    _item("236", "Zero Usage", "Billing-related investigations", "partial", ("meter_investigation",),
          ("Meter investigation", "Special meter read"),
          behaviour="Stuck meters and low/implausible readings can enter VEE review and field investigation; billing KPIs expose repeated zero consumption.",
          gap="No dedicated zero-usage order trigger. Genuine zero usage must not automatically be treated as a meter fault."),
    _item("315", "Meter Reset and Turn-on", "Meter sets", "partial", ("meter_set", "reconnect"),
          behaviour="A finished new-service job can raise a meter set. Collections reconnection separately restores a disconnected service.",
          gap="Resetting a removed meter and restoring that same service is not a combined order or lifecycle."),
    _item("219", "ERT Install", "Meter sets", "partial", ("ami_conversion",),
          behaviour="Route-based AMI conversion changes meter reading technology and registers a new device.",
          gap="A standalone ERT/AMR module installation that retains the physical meter and register is not modelled."),
)


def catalogue() -> dict:
    """A small static reference: no replay needed, and no run totals allocated to aliases."""
    from utilsim.m2c.fieldwork import TYPES

    return {
        "schemaVersion": "service-order-coverage/1.0",
        "source": "Service-order comparison photo supplied by the user; codes are reference labels, not engine order IDs.",
        "statuses": {"covered": "Core work covered", "partial": "Partial match", "not_modelled": "Not modelled"},
        "groups": list(dict.fromkeys(o["group"] for o in ORDERS)),
        "engineTypes": {key: label for key, label, *_ in TYPES},
        "timingNote": "The photo compares standard time with median travel and wrench time. The model's field.<type>.minutes is on-site crew time; road travel and stop time (or fallback travel_minutes) are added separately. Timed incident repairs and VEE visits have their own scheduling rules. Sample volumes and medians have not been imported as rates or duration defaults.",
        "manualNote": "Manual orders start from a read or eligible case in Workspace. The four activity choices are broader than these reference codes. Choose the activity, dispatch the order and record its outcome; a related automatic work type does not make every reference code manually issuable.",
        "orders": [{**o, "engineTypes": list(o["engineTypes"]), "manualActivities": list(o["manualActivities"])}
                   for o in ORDERS],
    }
