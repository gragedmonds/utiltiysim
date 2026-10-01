"""Generation pipeline: config → town. Pure and deterministic; stage timings are recorded for benchmarks."""

from __future__ import annotations

import time

from utilsim.config.model import SimConfig
from utilsim.gen.addresses import assign_addresses
from utilsim.gen.buildings import assign_households, build_premises
from utilsim.gen.landuse import plan_land_use
from utilsim.gen.roads.build import build_geography
from utilsim.model.town import Town
from utilsim.net.context import NetContext
from utilsim.net.electric import build_electric
from utilsim.net.gas import build_gas
from utilsim.net.water import build_water


def generate(cfg: SimConfig, *, with_customers: bool = True) -> Town:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    def mark(name: str):
        nonlocal t0
        t1 = time.perf_counter()
        timings[name] = round(t1 - t0, 3)
        t0 = t1

    geo = build_geography(cfg)
    mark("roads")
    lu = plan_land_use(geo, cfg)
    geo.roads = lu.roads
    mark("land_use")
    prem = build_premises(lu, cfg, geo.terrain, geo.era)
    assign_households(prem, cfg, geo.era)
    assign_addresses(prem, lu.roads, geo.center)
    mark("buildings")
    ctx = NetContext(cfg, lu, prem, geo.terrain, geo.era, cfg.seeds.for_("town"))
    networks = {"electric": build_electric(ctx)}
    mark("electric")
    networks["water"] = build_water(ctx)
    mark("water")
    networks["gas"] = build_gas(ctx)
    mark("gas")
    for net in networks.values():
        for nd in net.nodes:
            nd.attrs.setdefault("elevationM", round(float(geo.terrain.elevation(nd.xy[0], nd.xy[1])), 3))
    town = Town(cfg, geo, lu, prem, networks, timings=timings)
    if with_customers:
        from utilsim.customers.generate import build_customers

        town.customers = build_customers(town)
        mark("customers")
    timings["total"] = round(sum(v for k, v in timings.items()), 3)
    return town
