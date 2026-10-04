"""Customer model: IS-U-shaped entities with Astra's ids, routes and schedules, AMI collectors, baseline reads.

Physical equipment (meters, registers), commercial ownership (business partners, contract accounts, contracts)
and observations (reads) are separate. A move-out changes contract validity; a meter exchange changes device
validity; neither creates a premise. Register values are cumulative and never negative; solar export has its own
register. Ground truth stays in ``truth`` and is stripped by the VEE adapter."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from scipy.spatial import cKDTree

from utilsim.core import ids
from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, hash_choice, hash_u01
from utilsim.customers.calendar import scheduled_read_date, to_utc_iso
from utilsim.customers.names import BUSINESS, GIVEN, SURNAME
from utilsim.m2c import registers
from utilsim.m2c.calendar import calendar
from utilsim.sim.demand import monthly_energy
from utilsim.version import READ_SCHEMA_VERSION

SPARTE = {"electric": "01", "gas": "02", "water": "03"}
UNIT = {"electric": "kWh", "gas": "m3", "water": "m3"}
OBIS = {("electric", "import"): "1-0:1.8.0", ("electric", "export"): "1-0:2.8.0", ("gas", "import"): "7-0:3.0.0",
        ("water", "import"): "8-0:1.0.0"}
TECH_MODEL = {
    ("electric", "AMI"): "E-AMI-FORM2S-RF", ("electric", "AMR"): "E-AMR-FORM2S", ("electric", "MANUAL"): "E-EM-FORM2S",
    ("gas", "AMI"): "G-DIAPH-250-AMI", ("gas", "AMR"): "G-DIAPH-250-ERT", ("gas", "MANUAL"): "G-DIAPH-250",
    ("water", "AMI"): "W-PD-58-AMI", ("water", "AMR"): "W-PD-58-ERT", ("water", "MANUAL"): "W-PD-58",
}
READ_YEAR, READ_MONTH = 2026, 6  # baseline fixture: the June read (May read → June read)
READ_CAL = calendar(READ_YEAR)
SIM_START = date(2026, 1, 1)


@dataclass
class Customers:
    business_partners: list[dict] = field(default_factory=list)
    accounts: list[dict] = field(default_factory=list)
    service_points: list[dict] = field(default_factory=list)
    installations: list[dict] = field(default_factory=list)
    meters: list[dict] = field(default_factory=list)
    registers: list[dict] = field(default_factory=list)
    contracts: list[dict] = field(default_factory=list)
    tariff_assignments: list[dict] = field(default_factory=list)
    tariffs: list[dict] = field(default_factory=list)
    mrus: list[dict] = field(default_factory=list)
    portions: list[dict] = field(default_factory=list)
    read_schedules: list[dict] = field(default_factory=list)
    ami: dict = field(default_factory=dict)
    sample_reads: list[dict] = field(default_factory=list)
    premise_extra: dict[str, dict] = field(default_factory=dict)


def _hilbert(x: np.ndarray, y: np.ndarray, order: int = 12) -> np.ndarray:
    n = 1 << order
    xi = np.clip((x * (n - 1)).astype(np.int64), 0, n - 1)
    yi = np.clip((y * (n - 1)).astype(np.int64), 0, n - 1)
    d = np.zeros_like(xi)
    s = n // 2
    while s > 0:
        rx = (xi & s) > 0
        ry = (yi & s) > 0
        d += s * s * ((3 * rx) ^ ry)
        flip = ~ry
        swap_x = np.where(flip & rx, s - 1 - xi, xi)
        swap_y = np.where(flip & rx, s - 1 - yi, yi)
        xi, yi = np.where(flip, swap_y, xi), np.where(flip, swap_x, yi)
        s //= 2
    return d


def _date_iso(d: date) -> str:
    return f"{d.isoformat()}T00:00:00Z"


def build_customers(town) -> Customers:
    cfg, prem, nets = town.cfg, town.prem, town.networks
    cb = cfg.customers_billing
    seed = cfg.seeds.for_("households")
    tz = cfg.town.timezone
    n = len(prem)
    keys = np.array([str_key(u) for u in prem.uid], dtype=np.int64)
    U = hash_u01(seed, Purpose.CUSTOMER, keys[:, None], np.arange(16)[None, :])
    cust = Customers()
    a = prem.attrs

    # ---------------- routes (MRUs), portions, technology
    minx, miny, maxx, maxy = town.bounds
    hx = (prem.xy[:, 0] - minx) / max(maxx - minx, 1)
    hy = (prem.xy[:, 1] - miny) / max(maxy - miny, 1)
    order = np.argsort(_hilbert(hx, hy), kind="stable")
    n_routes = max(math.ceil(n / cb.mru_target_meters), min(cb.bill_cycles, math.ceil(n / 25)))
    chunks = np.array_split(order, n_routes)
    r_u = hash_u01(seed, Purpose.ROUTE, np.arange(n_routes))
    rank = np.argsort(r_u, kind="stable")
    n_ami = int(round(cfg.ami.ami_route_share * n_routes))
    n_amr = int(round(cfg.ami.amr_route_share * n_routes))
    tech = np.empty(n_routes, dtype=object)
    tech[rank[:n_ami]] = "AMI"
    tech[rank[n_ami:n_ami + n_amr]] = "AMR"
    tech[rank[n_ami + n_amr:]] = "MANUAL"
    mru_of = np.empty(n, dtype=np.int64)
    seq_of = np.empty(n, dtype=np.int64)
    for r, ch in enumerate(chunks):
        mru_of[ch] = r
        seq_of[ch] = np.arange(1, len(ch) + 1)
    portion_of_route = np.arange(n_routes) % cb.bill_cycles + 1
    walkers = [f"WALKER-{k + 1:02d}" for k in range(max(1, cfg.operations.meter_walkers))]
    vans = [f"VAN-{k + 1:02d}" for k in range(max(1, cfg.operations.meter_vans))]
    for p in range(1, cb.bill_cycles + 1):
        cust.portions.append({"id": f"PORT-{p:02d}", "portion": p, "billingBusinessDay": p,
                              "mruIds": [f"MRU-{r + 1:03d}" for r in range(n_routes) if portion_of_route[r] == p]})
    for r, ch in enumerate(chunks):
        t = str(tech[r])
        reader = None if t == "AMI" else (vans[r % len(vans)] if t == "AMR" else walkers[r % len(walkers)])
        cust.mrus.append({
            "id": f"MRU-{r + 1:03d}", "portionId": f"PORT-{portion_of_route[r]:02d}", "technology": t,
            "readerId": reader, "meterCount": int(len(ch)), "premiseIds": [prem.ids[i] for i in ch],
            "name": f"Route {r + 1:02d} · {prem.street[int(ch[0])] or 'Town'}",
            "sequence": [{"premiseId": prem.ids[i], "sequenceNo": int(k + 1)} for k, i in enumerate(ch)],
            "path": [[float(prem.front_xy[i, 0]), float(prem.front_xy[i, 1])] for i in ch],
        })
        for mo in range(1, 13):
            d = scheduled_read_date(READ_YEAR, mo, int(portion_of_route[r]))
            cust.read_schedules.append({"mruId": f"MRU-{r + 1:03d}", "period": f"{READ_YEAR}-{mo:02d}",
                                        "scheduledReadDate": d.isoformat(), "billingDate": d.isoformat()})
    route_tech = tech[mru_of]
    ami_year_of_route = 2014 + (hash_u01(seed, Purpose.AMI_ROLLOUT, np.arange(n_routes)) * 6).astype(int)

    # ---------------- AMI collectors (greedy k-centre over AMI meters, snapped to poles/tank/substation sites)
    ami_idx = np.flatnonzero(route_tech == "AMI")
    collectors = []
    if len(ami_idx):
        pts = prem.xy[ami_idx]
        radius = cfg.ami.collector_radius_m
        # Mounting points: poles (overhead areas), pad-mount transformers (underground areas), tanks, substations.
        mounts = [(q["xy"], "pole", q["id"]) for q in nets["electric"].equipment if q["kind"] == "pole"]
        mounts += [(nd.xy, "transformer_pad", nd.id) for nd in nets["electric"].nodes
                   if nd.kind == "transformer" and nd.attrs.get("mount") == "pad"]
        mounts += [(f.xy, f.kind, f.id) for f in town.lu.facilities if f.kind in ("elevated_tank", "substation")]
        mxy = np.array([m[0] for m in mounts]) if mounts else np.zeros((0, 2))
        mtree = cKDTree(mxy) if len(mxy) else None
        sites: list[tuple[np.ndarray, str, str]] = []

        def site_for(p: np.ndarray, i_prem: int):
            if mtree is not None:
                d, mi = mtree.query(p)
                if d < 150.0:
                    return mxy[mi], mounts[mi][1], mounts[mi][2]
            return prem.front_xy[i_prem], "streetlight", f"SL-{prem.ids[i_prem]}"

        cen = pts.mean(0)
        first = int(np.argmin(np.hypot(*(pts - cen).T)))
        sites.append(site_for(pts[first], int(ami_idx[first])))
        while len(sites) < 500:
            d = cKDTree(np.array([s[0] for s in sites])).query(pts)[0]
            uncovered = d > radius * 0.9
            if not uncovered.any():
                break
            far = int(np.argmax(np.where(uncovered, d, -1)))
            sites.append(site_for(pts[far], int(ami_idx[far])))
        for k, (xy, kind, mid_) in enumerate(sites):
            collectors.append({"id": f"COL-{k + 1:02d}", "x": float(xy[0]), "y": float(xy[1]), "mountedOn": kind,
                               "mountId": mid_, "coverageRadiusM": radius})
    col_tree = cKDTree(np.array([[c["x"], c["y"]] for c in collectors])) if collectors else None
    depot = next((f for f in town.lu.facilities if f.kind == "depot"), None)
    cust.ami = {"headend": {"id": "HEADEND-01", "facilityId": depot.id if depot else None,
                            "x": float(depot.xy[0]) if depot else 0.0, "y": float(depot.xy[1]) if depot else 0.0},
                "collectors": collectors, "pollWindowLocal": [cfg.ami.poll_start_hour, cfg.ami.poll_end_hour]}

    # ---------------- tariffs
    cust.tariffs = [
        {"id": "RES-E", "commodity": "electric", "fixedMonthly": cb.electric_fixed_monthly,
         "energyBlocks": [b.model_dump() for b in cb.electric_blocks], "variableDelivery": cb.electric_variable_delivery,
         "netMeteringCredit": cb.net_metering_credit, "taxRate": cb.tax_rate, "currency": cb.currency},
        {"id": "RES-G", "commodity": "gas", "fixedMonthly": cb.gas_fixed_monthly, "pricePerM3": cb.gas_price_m3,
         "calorificMJm3": cfg.gas.calorific_mj_per_m3, "taxRate": cb.tax_rate, "currency": cb.currency},
        {"id": "RES-W", "commodity": "water", "fixedMonthly": cb.water_fixed_monthly, "pricePerM3": cb.water_price_m3,
         "wastewaterRatio": cb.wastewater_ratio, "taxRate": cb.tax_rate, "currency": cb.currency},
        {"id": "COM-E", "commodity": "electric", "basedOn": "RES-E", "demandChargePerKW": 9.5},
        {"id": "COM-G", "commodity": "gas", "basedOn": "RES-G"},
        {"id": "COM-W", "commodity": "water", "basedOn": "RES-W"},
    ]

    # ---------------- monthly energy for reads
    energy = monthly_energy(prem, cfg)
    cum = {k: registers.cumulative(v) for k, v in energy.items()}
    december = {k: v[11] for k, v in energy.items()}
    digits = {"electric": cfg.ami.meter_digits_electric, "water": cfg.ami.meter_digits_water,
              "gas": cfg.ami.meter_digits_gas}

    # ---------------- per-premise entities
    payment = hash_choice(seed, Purpose.PAYMENT, keys, [cb.on_time_payer_share, cb.late_payer_share,
                                                        max(0.0, 1 - cb.on_time_payer_share - cb.late_payer_share)])
    pay_names = np.array(["on_time", "late", "at_risk"])
    for i in range(n):
        pid = prem.ids[i]
        ptype = int(prem.ptype[i])
        u = U[i]
        occupied = bool(a["occupied"][i])
        rental = bool(a["rental"][i])
        # Contract history: current (or most recent) tenancy plus previous tenancies for rentals.
        tenure_years = (-math.log(max(u[0], 1e-6))) * (2.5 if rental else 11.0)
        built = date(int(min(a["year_built"][i], 2024)), 1 + int(u[1] * 12) % 12, 1)
        move_in = max(built, date(2026, 6, 1) - timedelta(days=int(tenure_years * 365.25)))
        move_out = None
        if not occupied:
            move_out = date(2026, 3, 1) + timedelta(days=int(u[2] * 110))
            move_in = min(move_in, move_out - timedelta(days=200))
        tenancies = [(move_in, move_out, "")]
        if rental:
            prev_end = move_in - timedelta(days=int(u[3] * 45))
            for h in range(1, 3):
                prev_start = prev_end - timedelta(days=int(200 + u[3 + h] * 900))
                if prev_start < date(2023, 1, 1):
                    break
                tenancies.append((prev_start, prev_end, f"-H{h}"))
                prev_end = prev_start - timedelta(days=int(u[6 + h] * 30))
        ca_current = None
        for t_in, t_out, suffix in tenancies:
            bp = ids.business_partner_id(pid) + suffix
            ca = ids.account_id(pid) + suffix
            if ptype == 0:
                k = str_key(bp)
                name = f"{GIVEN[k % len(GIVEN)]} {SURNAME[(k // 7) % len(SURNAME)]}"
                kind = "person"
            else:
                name = prem.building_type[i].replace("_", " ").title() if ptype != 1 else \
                    BUSINESS[str_key(bp) % len(BUSINESS)]
                kind = "organization"
            cust.business_partners.append({"id": bp, "kind": kind, "name": name, "since": t_in.isoformat(),
                                           "paymentProfile": str(pay_names[payment[i]]),
                                           "sapPartner": f"{(str_key(bp) % 9_000_000_000) + 1_000_000_000:010d}"})
            cust.accounts.append({"id": ca, "businessPartnerId": bp, "currency": cb.currency, "premiseId": pid,
                                  "paymentMethod": "pre_authorized_debit" if u[10] < cb.pre_authorized_share
                                  else ("online" if u[10] < 0.9 else "cheque"),
                                  "budgetBilling": bool(u[11] < 0.18), "validFrom": _date_iso(t_in),
                                  "validTo": _date_iso(t_out) if t_out else None,
                                  "sapContractAccount": f"{(str_key(ca) % 900_000_000_000) + 100_000_000_000:012d}"})
            if not suffix:
                ca_current = ca
        mru = int(mru_of[i])
        t_route = str(tech[mru])
        extra = {"mruId": f"MRU-{mru + 1:03d}", "sequenceNo": int(seq_of[i]),
                 "billingCycle": int(portion_of_route[mru]), "meterTechnology": t_route,
                 "moveInAt": _date_iso(move_in), "moveOutAt": _date_iso(move_out) if move_out else None,
                 "accountId": ca_current}
        cust.premise_extra[pid] = extra
        # Services.
        commodities = ["electric", "water"] + (["gas"] if a["has_gas"][i] else [])
        for c in ("electric", "water", "gas"):
            if c not in commodities:
                continue
            sp = ids.service_point_id(pid, c)
            mid = ids.meter_id(pid, c)
            inst = ids.installation_id(pid, c)
            node_id = ids.meter_node_id(c, pid)
            tech_c = t_route
            ami_year = int(ami_year_of_route[mru])
            installed = date(max(int(a["year_built"][i]), ami_year if tech_c == "AMI" else 2009 + int(u[12] * 8)),
                             1 + int(u[13] * 11), 1 + int(u[14] * 27))
            dirs = ["import", "export"] if (c == "electric" and a["solar"][i]) else ["import"]
            cust.service_points.append({"id": sp, "premiseId": pid, "commodity": c, "meterId": mid,
                                        "installationId": inst, "status": "active", "validFrom": _date_iso(built),
                                        "validTo": None, "networkNodeId": node_id})
            cust.installations.append({"id": inst, "servicePointId": sp, "premiseId": pid, "division": c,
                                       "sparte": SPARTE[c], "timezone": tz, "readCycle": int(portion_of_route[mru]),
                                       "mruId": f"MRU-{mru + 1:03d}",
                                       "rateCategory": ("RES-" if ptype == 0 else "COM-") + c[0].upper(),
                                       "billingClass": "residential" if ptype == 0 else "commercial",
                                       "status": "active"})
            col = None
            if tech_c == "AMI" and col_tree is not None:
                dcol, kcol = col_tree.query(prem.xy[i])
                col = {"collectorId": collectors[int(kcol)]["id"], "distanceM": round(float(dcol), 1)}
            serial = f"{c[0].upper()}{(str_key(mid) % 90_000_000) + 10_000_000:08d}"
            cust.meters.append({"id": mid, "servicePointId": sp, "technology": tech_c, "manufacturer": "Synthetic",
                                "model": TECH_MODEL[(c, tech_c)], "serialNumber": serial,
                                "registerIds": [ids.register_id(mid, d) for d in dirs], "multiplier": 1,
                                "registerDigits": digits[c], "installedAt": _date_iso(installed), "removedAt": None,
                                "commStatus": "online" if tech_c == "AMI" else None,
                                "batteryInstallYear": installed.year if tech_c != "MANUAL" else None,
                                "bidirectional": len(dirs) == 2, **({"ami": col} if col else {})})
            for d in dirs:
                cust.registers.append({"id": ids.register_id(mid, d), "meterId": mid, "direction": d,
                                       "unit": UNIT[c], "precision": 3, "digits": digits[c], "obis": OBIS[(c, d)]})
            for t_in, t_out, suffix in tenancies:
                ctr = ids.contract_id(pid, c) + suffix
                cust.contracts.append({"id": ctr, "installationId": inst, "accountId": ids.account_id(pid) + suffix,
                                       "validFrom": _date_iso(t_in), "validTo": _date_iso(t_out) if t_out else None,
                                       "status": "active" if t_out is None else "ended"})
                rate = ("RES-" if ptype == 0 else "COM-") + c[0].upper()
                cust.tariff_assignments.append({"contractId": ctr, "tariffId": rate,
                                                "netMetering": bool(c == "electric" and len(dirs) == 2),
                                                "validFrom": _date_iso(t_in),
                                                "validTo": _date_iso(t_out) if t_out else None,
                                                "status": "configured"})
            # Baseline read for the read month (previous scheduled read → this one).
            portion = int(portion_of_route[mru])
            prev_d = scheduled_read_date(READ_YEAR, READ_MONTH - 1, portion)
            this_d = scheduled_read_date(READ_YEAR, READ_MONTH, portion)
            read_hour = {"AMI": 2.0, "AMR": 9.5 + 5 * u[15], "MANUAL": 9.0 + 6 * u[15]}[tech_c]
            for d in dirs:
                reg = ids.register_id(mid, d)
                key = "electric_" + d if c == "electric" else c
                base = registers.register_base(reg, cfg.seeds.master)
                mod = 10.0 ** digits[c]
                true = base + registers.advance(cum[key], december[key], np.array([i, i]),
                                                np.array([READ_CAL.day_of(prev_d), READ_CAL.day_of(this_d)]),
                                                np.array([read_hour, read_hour]), READ_CAL.month_start)
                prev_val, val = (float(x) for x in registers.observe(true, digits[c]))
                consumption = round((val - prev_val) % mod, 3)
                active_ctr = next((ids.contract_id(pid, c) + sfx for t_in, t_out, sfx in tenancies
                                   if t_in <= prev_d and (t_out is None or t_out > prev_d)),
                                  ids.contract_id(pid, c))
                active_ca = active_ctr.replace(f"C-{pid}-{c}", f"CA-{pid}")
                read_at = to_utc_iso(this_d, read_hour, tz)
                rid = f"READ-{town.id}-{reg}-{this_d.isoformat()}"
                cust.sample_reads.append({
                    "id": rid, "schemaVersion": READ_SCHEMA_VERSION,
                    "simulationId": town.id, "premiseId": pid, "servicePointId": sp, "installationId": inst,
                    "meterId": mid, "registerId": reg, "contractId": active_ctr, "accountId": active_ca,
                    "commodity": c, "direction": d, "unit": UNIT[c],
                    "periodStart": to_utc_iso(prev_d, read_hour, tz), "periodEnd": read_at,
                    "scheduledReadAt": to_utc_iso(this_d, read_hour, tz), "readAt": read_at,
                    "previousReadAt": to_utc_iso(prev_d, read_hour, tz), "previousRegisterValue": prev_val,
                    "registerValue": val, "consumption": consumption, "multiplier": 1, "registerDigits": digits[c],
                    "rolloverFlag": bool(val < prev_val), "readType": "actual", "readStatus": "received",
                    "readReason": "periodic", "source": {"AMI": "synthetic-AMI", "AMR": "synthetic-AMR-drive-by",
                                                         "MANUAL": "synthetic-manual-route"}[tech_c],
                    "mruId": f"MRU-{mru + 1:03d}", "reasonCode": None, "consecutiveEstimates": 0,
                    "occupied": occupied, "moveInAt": extra["moveInAt"], "moveOutAt": extra["moveOutAt"],
                    "sapValidationCode": None, "veeStatus": "not_processed", "billingDocumentId": None,
                    "invoiceId": None, "truth": {"registerValue": val, "consumption": consumption},
                    "idempotencyKey": f"{town.id}:{reg}:{read_at}"})
    return cust
