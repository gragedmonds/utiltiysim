"""Complete state frames (``utility-state/1.0``) and replays (``utility-replay/1.0``).

M1 frames are static solver output: radial aggregation of the deterministic demand model at the frame time.
Rules (match the viewer receiver): every edge of every network is listed with an explicit id; ``flows[i] > 0`` runs
from → to, ``< 0`` to → from, ``0`` is a calculated zero, ``null`` is unavailable (enabled loop edges until the M2
looped solve); a disabled edge has 0 or null; premises list every premise with ``null`` where a commodity is not
served; the clock carries the same ``simTime`` string as the frame."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from utilsim.io.revisions import index_revision, topology_revision
from utilsim.sim.astro import moon_phase, sun_position
from utilsim.sim.flows import FlowModel
from utilsim.version import REPLAY_SCHEMA_VERSION, STATE_SCHEMA_VERSION

MAX_REPLAY_FRAMES = 2000
UNITS = {"electric": "kW", "water": "m3/h", "gas": "m3/h"}


def iso_utc(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timezone(town) -> str:
    return town.timezone if hasattr(town, "timezone") else town.cfg.town.timezone


def local_time(town, day: str | date, hour: float) -> datetime:
    d = date.fromisoformat(day) if isinstance(day, str) else day
    tz = ZoneInfo(_timezone(town))
    return datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(minutes=round(hour * 60))


def simulation_id(town, scenario: str, day: str, target: str | None) -> str:
    h = hashlib.blake2b(f"{town.id}|{scenario}|{day}|{target}".encode(), digest_size=5).hexdigest()
    return f"run-{scenario}-{day}-{h}"


def run_sequence(when: datetime, day: date, tz: ZoneInfo) -> int:
    """Whole local wall-clock minutes from midnight of ``day`` to ``when``: the same instant gets the same
    sequence in /state and in a replay, and a reconnecting client resumes from startHour = sequence / 60."""
    local = when.astimezone(tz).replace(tzinfo=None)
    return int((local - datetime(day.year, day.month, day.day)).total_seconds() // 60)


def _clean(a: np.ndarray, digits: int = 4) -> list:
    return [None if not np.isfinite(v) else round(float(v), digits) for v in a]


@dataclass
class FrameContext:
    """What frames need from a town, independent of how it was obtained (a generated ``Town`` or a snapshot)."""

    id: str
    topology: str
    index: str
    timezone: str
    origin_lat: float
    origin_lon: float
    premise_ids: list[str]
    edge_ids: dict[str, list[str]]
    enabled: dict[str, np.ndarray]
    supply: np.ndarray  # electric supply edges (substation_outage disables them)
    served: dict[str, np.ndarray]  # premise has the service

    @classmethod
    def from_town(cls, town) -> FrameContext:
        
        a = town.prem.attrs
        n = len(town.prem)
        return cls(id=town.id, topology=topology_revision(town), index=index_revision(town),
                   timezone=town.cfg.town.timezone, origin_lat=town.geo.origin_lat, origin_lon=town.geo.origin_lon,
                   premise_ids=list(town.prem.ids),
                   edge_ids={u: [e.id for e in nt.edges] for u, nt in town.networks.items()},
                   enabled={u: np.array([e.enabled for e in nt.edges]) for u, nt in town.networks.items()},
                   supply=np.array([e.kind == "supply" for e in town.networks["electric"].edges]),
                   served={"electric": np.ones(n, dtype=bool), "water": np.ones(n, dtype=bool),
                           "gas": np.asarray(a["has_gas"], dtype=bool)})


class FrameBuilder:
    """Reuses one flow model and the town's revisions for many frames. Accepts a ``Town`` or a ``FrameContext``
    (with its ``FlowModel``), so the hosted runtime builds frames from a snapshot without the generation stack."""

    def __init__(self, town, flow_model: FlowModel | None = None):
        if isinstance(town, FrameContext):
            if flow_model is None:
                raise ValueError("a FrameContext needs its FlowModel")
            self.ctx, self.fm = town, flow_model
        else:
            self.ctx, self.fm = FrameContext.from_town(town), flow_model or FlowModel(town)
        self.town = town  # the Town (or the context) it was built from
        self.topology, self.index = self.ctx.topology, self.ctx.index

    def frame(self, when: datetime, *, scenario: str = "normal", target: str | None = None,
              sequence: int | None = None, sim_id: str | None = None, include_premises: bool = True,
              disabled: dict[str, np.ndarray] | None = None,
              injections: dict[str, dict[int, float]] | None = None,
              premises_off: dict[str, np.ndarray] | None = None) -> dict:
        """One complete frame. ``disabled`` (bool mask per utility) opens switches / closes valves on top of the
        built state; ``injections`` adds flow at nodes (a leak). Unsupplied premises are listed per utility."""
        ctx = self.ctx
        tz = ZoneInfo(ctx.timezone)
        local = when.astimezone(tz)
        hour = local.hour + local.minute / 60.0 + local.second / 3600.0
        if scenario == "leak" and target is None:
            target = ctx.premise_ids[0]
        if sequence is None:
            sequence = run_sequence(when, local.date(), tz)
        res = self.fm.flows(hour, scenario, target, disabled=disabled, injections=injections, premises_off=premises_off)
        sim_time = iso_utc(when)
        networks = {}
        for u in ("electric", "water", "gas"):
            enabled = ctx.enabled[u].copy()
            if disabled is not None and u in disabled:
                enabled &= ~disabled[u]
            flows = res.edge_flows[u].copy()
            if u == "electric" and scenario == "substation_outage":
                enabled[ctx.supply] = False
            flows[~enabled & np.isfinite(flows)] = 0.0
            src = res.source[u]
            networks[u] = {"unit": UNITS[u], "edgeIds": ctx.edge_ids[u], "flows": _clean(flows),
                           "sourceFlow": round(float(src), 4) if np.isfinite(src) else None,
                           "enabled": [bool(x) for x in enabled]}
        frame = {"schemaVersion": STATE_SCHEMA_VERSION, "townId": ctx.id,
                 "simulationId": sim_id or simulation_id(ctx, scenario, local.date().isoformat(), target),
                 "topologyRevision": ctx.topology, "indexRevision": ctx.index, "sequence": int(sequence),
                 "simTime": sim_time, "complete": True, "scenario": scenario, "networks": networks}
        if scenario == "leak":
            frame["scenarioTarget"] = target
        if include_premises:
            prem = {"ids": ctx.premise_ids}
            for u in ("electric", "water", "gas"):
                v = np.where(ctx.served[u], res.homes[u], np.nan)
                prem[u] = _clean(v, 5)
            lost = {u: [ctx.premise_ids[i] for i in np.flatnonzero(m & ctx.served[u])]
                    for u, m in (res.unsupplied or {}).items() if (m & ctx.served[u]).any()}
            if lost:
                prem["unsupplied"] = lost
            frame["premises"] = prem
        elev, az = sun_position(when, ctx.origin_lat, ctx.origin_lon)
        frame["clock"] = {"simTime": sim_time, "timezone": ctx.timezone, "localTime": local.isoformat(),
                          "sunElevationDeg": elev, "sunAzimuthDeg": az, "moonPhase": moon_phase(when),
                          "isDay": bool(elev > -0.833)}
        return frame

    def replay(self, day: str, *, scenario: str = "normal", target: str | None = None, start_hour: float = 0.0,
               hours: float = 24.0, step_minutes: int = 60, include_premises: bool = True) -> dict:
        if step_minutes <= 0:
            raise ValueError("step_minutes must be positive")
        n = int(round(hours * 60 / step_minutes))
        if not 1 <= n <= MAX_REPLAY_FRAMES:
            raise ValueError(f"a replay holds 1–{MAX_REPLAY_FRAMES} frames; {n} requested")
        start = local_time(self.ctx, day, start_hour)
        sim_id = simulation_id(self.ctx, scenario, day, target)
        d, tz = date.fromisoformat(day), ZoneInfo(self.ctx.timezone)
        times = [start + timedelta(minutes=k * step_minutes) for k in range(n)]
        frames = [self.frame(t, scenario=scenario, target=target, sequence=run_sequence(t, d, tz), sim_id=sim_id,
                             include_premises=include_premises) for t in times]
        return {"schemaVersion": REPLAY_SCHEMA_VERSION, "townId": self.ctx.id, "simulationId": sim_id,
                "topologyRevision": self.topology, "indexRevision": self.index, "scenario": scenario,
                "stepMinutes": step_minutes, "frames": frames}


def initial_frame(town) -> dict:
    sc = town.cfg.scenario
    return FrameBuilder(town).frame(local_time(town, sc.date, sc.hour), scenario=sc.name,
                                    target=sc.target_premise)
