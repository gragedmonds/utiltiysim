"""Buildings and households for every premise (residential, commercial strip, school, industry, utility sites)."""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import Polygon

from utilsim.config.model import SimConfig
from utilsim.core.ids import premise_id, str_key, uid
from utilsim.core.rng import Purpose, hash_choice, hash_u01
from utilsim.gen.landuse import LandUse
from utilsim.gen.zoning import ERA_MODERN, ERA_POSTWAR, ERA_PRE1945, era_bucket
from utilsim.model.premises import Premises

STOREY_HEIGHT = {1: 3.7, 2: 6.3, 3: 9.0}


def _rect(c, t, n, w, d) -> Polygon:
    return Polygon([c + t * w / 2 + n * d / 2, c - t * w / 2 + n * d / 2, c - t * w / 2 - n * d / 2,
                    c + t * w / 2 - n * d / 2])


def _place_house(lot: Polygon, row_xy, t, n, frontage, depth, setback, w, d, lateral) -> tuple[Polygon, np.ndarray, float, float]:
    inner = lot.buffer(-0.4)
    for k in range(6):
        sb = setback * (1 - 0.15 * k)
        c = row_xy + n * (sb + d / 2) + t * lateral
        poly = _rect(c, t, n, w, d)
        if inner.contains(poly):
            return poly, c, w, d
        w, d, lateral = w * 0.9, d * 0.9, lateral * 0.5
    c = np.asarray(lot.representative_point().coords[0])
    w, d = 6.0, 7.0
    return _rect(c, t, n, w, d), c, w, d


def build_premises(lu: LandUse, cfg: SimConfig, terrain, era_field) -> Premises:
    seed = cfg.seeds.for_("households")
    h = cfg.housing
    recs = []  # (kind, lot index into a Lots, Lots, facility)
    for i in range(len(lu.houses)):
        recs.append(("residential", i, lu.houses, None))
    for i in range(len(lu.commercial)):
        recs.append(("commercial", i, lu.commercial, None))
    # Order premises along streets so ids read naturally: by edge, side, arc length.
    def key(r):
        kind, i, L, _ = r
        return (0 if kind == "residential" else 1, int(L.edge[i]), -int(L.side[i]), round(float(L.s_center[i]), 2))

    recs.sort(key=key)
    n_lot = len(recs)
    fac = [f for f in lu.facilities if f.kind in ("school", "industrial", "depot", "pump_station")]
    n = n_lot + len(fac)
    out = {k: [] for k in ("ids", "uid", "ptype", "building_type", "xy", "footprint", "width", "depth", "height",
                           "stories", "roof", "heading", "normal", "edge", "s", "side", "front_xy", "row_xy", "lot",
                           "lot_area", "year", "facility_id")}
    two_storey = np.array(h.two_storey_share.as_array())
    setback_era = np.array(h.setback_m.as_array())
    for q, (kind, i, L, _) in enumerate(recs):
        u_uid = L.uid[i]
        ku = str_key(u_uid)
        u = hash_u01(seed, Purpose.FOOTPRINT, ku, np.arange(8))
        e = int(L.era[i])
        t = L.tangent[i]
        nrm = L.normal[i]
        fr, dp = float(L.frontage[i]), float(L.depth[i])
        if kind == "residential":
            w = float(np.clip(fr * (0.55 + 0.15 * u[0]), 7.0, min(15.0, fr - 2.4)))
            dmin, dmax = {ERA_PRE1945: (9.0, 12.0), ERA_POSTWAR: (8.5, 11.0), ERA_MODERN: (10.0, 13.5)}[e]
            d = float(np.clip(dmin + (dmax - dmin) * u[1], 6.0, max(6.0, dp - setback_era[e] - 7.0)))
            sb = setback_era[e] + (u[2] - 0.5) * 2.0
            lat = (fr - w) / 2 * (u[3] - 0.5) * 1.2
            stories = 2 if u[4] < two_storey[e] else 1
            roof = "gable" if e == ERA_PRE1945 or u[5] < 0.55 else "hip"
            btype = "detached"
        else:
            w = float(np.clip(fr * 0.88, 8.0, fr - 0.6))
            d = float(np.clip(dp - 10.0, 10.0, 24.0))
            sb = 1.5 + u[2]
            lat = 0.0
            stories = 2 if e <= ERA_POSTWAR and u[4] < 0.6 else 1
            roof = "flat"
            btype = "storefront"
        poly, c, w, d = _place_house(L.poly[i], L.row_xy[i], t, nrm, fr, dp, sb, w, d, lat)
        out["ids"].append(premise_id(q))
        out["uid"].append(uid("premise", u_uid))
        out["ptype"].append(0 if kind == "residential" else 1)
        out["building_type"].append(btype)
        out["xy"].append(c)
        out["footprint"].append(shapely.set_precision(poly, 0.01))
        out["width"].append(w)
        out["depth"].append(d)
        out["stories"].append(stories)
        out["height"].append(STOREY_HEIGHT[stories] + (0.6 if kind != "residential" else 0.0))
        out["roof"].append(roof)
        out["heading"].append(math.atan2(t[1], t[0]))
        out["normal"].append(nrm)
        out["edge"].append(int(L.edge[i]))
        out["s"].append(float(L.s_center[i]))
        out["side"].append(int(L.side[i]))
        out["front_xy"].append(L.front_xy[i])
        out["row_xy"].append(L.row_xy[i])
        out["lot"].append(L.poly[i])
        out["lot_area"].append(L.poly[i].area)
        out["year"].append(int(L.year[i]))
        out["facility_id"].append(None)
    g = lu.roads.graph
    for k, f in enumerate(fac):
        q = n_lot + k
        ls = shapely.LineString(g.geometry[f.edge])
        p = ls.interpolate(f.s)
        a = ls.interpolate(max(0.0, f.s - 2))
        b = ls.interpolate(min(ls.length, f.s + 2))
        heading = math.atan2(b.y - a.y, b.x - a.x)
        t = np.array([math.cos(heading), math.sin(heading)])
        nrm = np.array([-t[1], t[0]]) * f.side
        c = np.asarray(f.poly.centroid.coords[0])
        if f.kind == "school":
            w, d, stories, ptype, btype = 70.0, 40.0, 2, 2, "school"
            nrm = c - np.array([p.x, p.y])
            nrm = nrm / max(np.hypot(*nrm), 1e-9)
            t = np.array([nrm[1], -nrm[0]])
            heading = math.atan2(t[1], t[0])
        elif f.kind == "industrial":
            w, d, stories, ptype, btype = 90.0, 55.0, 1, 3, "industrial"
        elif f.kind == "depot":
            w, d, stories, ptype, btype = 45.0, 25.0, 1, 4, "depot"
        else:
            w, d, stories, ptype, btype = 18.0, 12.0, 1, 4, "pump_house"
        poly = _rect(c, t, nrm, w, d)
        if not f.poly.buffer(0.5).contains(poly):
            poly = poly.intersection(f.poly)
        row = np.array([p.x, p.y]) + nrm * 12.0
        out["ids"].append(premise_id(q))
        out["uid"].append(uid("premise", f.id))
        out["ptype"].append(ptype)
        out["building_type"].append(btype)
        out["xy"].append(c)
        out["footprint"].append(shapely.set_precision(poly, 0.01))
        out["width"].append(w)
        out["depth"].append(d)
        out["stories"].append(stories)
        out["height"].append(STOREY_HEIGHT[stories] + 1.5)
        out["roof"].append("flat")
        out["heading"].append(heading)
        out["normal"].append(nrm)
        out["edge"].append(int(f.edge))
        out["s"].append(float(f.s))
        out["side"].append(int(f.side))
        out["front_xy"].append(np.array([p.x, p.y]))
        out["row_xy"].append(row)
        out["lot"].append(f.poly)
        out["lot_area"].append(f.poly.area)
        cen = c[None, :]
        out["year"].append(int(era_field.year_at(cen)[0]))
        out["facility_id"].append(f.id)
        f.attrs["premise_id"] = premise_id(q)
    xy = np.array(out["xy"])
    year = np.array(out["year"], dtype=np.int64)
    prem = Premises(
        ids=out["ids"], uid=out["uid"], ptype=np.array(out["ptype"], dtype=np.int8),
        building_type=out["building_type"], xy=xy, footprint=out["footprint"],
        width=np.array(out["width"]), depth=np.array(out["depth"]), height=np.array(out["height"]),
        stories=np.array(out["stories"], dtype=np.int8), roof=out["roof"], heading=np.array(out["heading"]),
        normal=np.array(out["normal"]), edge=np.array(out["edge"], dtype=np.int64), s=np.array(out["s"]),
        side=np.array(out["side"], dtype=np.int8), front_xy=np.array(out["front_xy"]),
        row_xy=np.array(out["row_xy"]), lot=out["lot"], lot_area=np.array(out["lot_area"]), year=year,
        era=era_bucket(year), district=np.zeros(n, dtype=np.int64), facility_id=out["facility_id"],
        street=[""] * n, number=np.zeros(n, dtype=np.int64))
    prem.attrs["elevation"] = terrain.elevation(xy[:, 0], xy[:, 1])
    return prem


def assign_households(prem: Premises, cfg: SimConfig, era_field) -> None:
    """Household and appliance attributes, all counter-based on the premise uid (order independent)."""
    seed = cfg.seeds.for_("households")
    h = cfg.housing
    keys = np.array([str_key(u) for u in prem.uid], dtype=np.int64)
    prem.district = era_field.district_of(prem.xy)
    U = hash_u01(seed, Purpose.HOUSE_ATTR, keys[:, None], np.arange(20)[None, :])
    e = prem.era
    res = prem.residential
    all_elec = era_field.district_all_electric[prem.district]
    gas_available = ~all_elec
    occupants = hash_choice(seed, Purpose.HOUSEHOLD, keys, h.household_size_weights) + 1
    occupants = np.where(res, occupants, 0)
    occupied = np.where(res, U[:, 0] < h.occupancy_rate, True)
    rental = res & (U[:, 1] < h.rental_share * np.where(e == ERA_PRE1945, 1.4, np.where(e == ERA_MODERN, 0.7, 1.0)))
    elec_rate = np.array(h.electric_heat_rate.as_array())[e]
    electric_heat = ~gas_available | (U[:, 2] < elec_rate)
    heat_pump = electric_heat & (U[:, 3] < np.where(all_elec, max(h.heat_pump_share_of_electric, 0.6),
                                                    h.heat_pump_share_of_electric))
    heating_fuel = np.where(~electric_heat, "gas", np.where(heat_pump, "heat_pump", "electric_resistance"))
    gas_dhw = electric_heat & gas_available & (U[:, 4] < 0.22)
    has_gas = gas_available & (~electric_heat | gas_dhw)
    # Commercial and institutional premises in gas districts use gas heat.
    has_gas = np.where(res, has_gas, gas_available & (prem.ptype != 4))
    # Non-residential heating follows gas availability (rooftop gas units where mains exist, else heat pumps).
    electric_heat = np.where(res, electric_heat, ~has_gas)
    heat_pump = np.where(res, heat_pump, ~has_gas)
    heating_fuel = np.where(res, heating_fuel, np.where(has_gas, "gas", "heat_pump"))
    ac = np.where(res, U[:, 5] < h.ac_rate * np.where(e == ERA_PRE1945, 0.8, 1.0), True)
    solar = res & (U[:, 6] < np.array(h.solar_rate.as_array())[e])
    pv_kw = np.where(solar, np.round(h.pv_kw_min + (h.pv_kw_max - h.pv_kw_min) * U[:, 7], 1), 0.0)
    ev = res & (U[:, 8] < np.array(h.ev_rate.as_array())[e])
    pool = res & (prem.lot_area > 600) & (U[:, 9] < h.pool_rate * np.where(e == ERA_MODERN, 1.5, 1.0))
    irrigation = res & (U[:, 10] < h.irrigation_rate * np.where(e == ERA_MODERN, 1.4, 0.8))
    floor = np.round(np.array([p.area for p in prem.footprint]) * prem.stories * 0.92, 1)
    year_built = prem.year + np.round((U[:, 11] - 0.5) * 6).astype(np.int64)
    prem.attrs.update({
        "occupants": occupants.astype(np.int64), "occupied": occupied, "rental": rental,
        "heating_fuel": heating_fuel, "electric_heat": electric_heat, "heat_pump": heat_pump,
        "has_gas": has_gas, "gas_available": gas_available, "ac": ac, "solar": solar, "pv_kw": pv_kw, "ev": ev,
        "pool": pool, "irrigation": irrigation, "floor_m2": floor, "year_built": year_built,
        "roof_tone": np.round(U[:, 12], 4), "garage": res & (e != ERA_PRE1945) & (U[:, 13] < 0.7),
    })
