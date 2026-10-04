"""Simulation codes: one simulation's complete inputs as a short uppercase code to paste into another copy of Utility
Studio.

A code carries everything that shapes a simulation: the prepared town (preset) and the town settings that differ from
it, the number of homes, the run seed, the run and map-day settings, the goals, the results date, the name, and every
episode on the year (the starting scenario's and the ones inflicted later, each with its dates, ramp, settings and
sporadic pattern with its seed). Nothing is looked up anywhere: the same engine build rebuilds the same simulation
from the code alone, offline.

Layout: ``UTS`` + version digit + Crockford base32 of (raw deflate of the compact JSON payload, then two check bytes).
Deflate uses a frozen preset dictionary (``share_dictionary_v1.txt``: the engine's default settings, the regional
starters and the scenario library), which makes a typical code three to four times shorter than plain compression.
The dictionary is part of the format: a new one is a new version digit, never an edit of this file.
"""
from __future__ import annotations

import zlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import orjson

VERSION = 1
PREFIX = "UTS"
SCHEMA = "simulation-code/1.0"
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: no I, L, O or U, so a read-back code is unambiguous
_DECODE = {c: i for i, c in enumerate(ALPHABET)} | {"O": 0, "I": 1, "L": 1}
GROUP = 5  # display: UTS1-ABCDE-FGHJK-…
MAX_CODE_CHARS = 12_000
MAX_PAYLOAD = 256_000
YEAR = 2026
DEFAULT_AS_OF = "2026-03-31"
SUMMARY = "Imported from a simulation code."


class CodeError(ValueError):
    """The code cannot be read; the message is for the person who pasted it."""


# ---- base32 -----------------------------------------------------------------------------------------------------
def b32encode(data: bytes) -> str:
    bits = int.from_bytes(data, "big")
    length = -(-len(data) * 8 // 5)
    bits <<= length * 5 - len(data) * 8
    return "".join(ALPHABET[(bits >> (5 * (length - 1 - i))) & 31] for i in range(length))


def b32decode(text: str) -> bytes:
    bits = 0
    for c in text:
        if c not in _DECODE:
            raise CodeError(f"The character {c!r} cannot appear in a simulation code.")
        bits = (bits << 5) | _DECODE[c]
    size = len(text) * 5 // 8
    extra = len(text) * 5 - size * 8
    if bits & ((1 << extra) - 1):
        raise CodeError("This code is damaged: a character is missing or wrong.")
    return (bits >> extra).to_bytes(size, "big")


def clean(code: str) -> str:
    """The code as typed or pasted: any case, spaces, dashes or line breaks, and the look-alikes O, I and L."""
    return "".join(c for c in str(code or "").upper() if c.isalnum())


def grouped(code: str) -> str:
    body = code[len(PREFIX) + 1:]
    return "-".join([code[:len(PREFIX) + 1], *(body[i:i + GROUP] for i in range(0, len(body), GROUP))])


# ---- dictionary --------------------------------------------------------------------------------------------------
def dictionary_path(version: int = VERSION) -> Path:
    return Path(__file__).with_name(f"share_dictionary_v{version}.txt")


def dictionary(version: int = VERSION) -> bytes:
    return dictionary_path(version).read_bytes()


def build_dictionary() -> bytes:
    """What a new dictionary version is made of (the committed file is never regenerated in place): the default
    settings, the regional starters, the scenario library's episodes in the compact form and the map-day defaults.
    zlib matches against the last 32 KiB, so the most useful text comes last."""
    from api._agent_config import grouped_ops_defaults, preset_config
    from api._setup import REGIONS
    from utilsim.config.model import SimConfig
    from utilsim.m2c.scenarios import SCENARIOS

    dump = lambda v: orjson.dumps(v, option=orjson.OPT_SORT_KEYS)  # noqa: E731
    parts = [dump(SimConfig().model_dump(mode="json")), dump(grouped_ops_defaults(preset_config("small_town")))]
    parts += [dump(r["overrides"]) for r in REGIONS]
    for s in SCENARIOS:
        parts.append(dump([_pack_episode(e) for e in dated_episodes(s, f"{YEAR}-01-01")]))
    return b"".join(parts)[-32768:]


# ---- payload -----------------------------------------------------------------------------------------------------
def day_number(value: str) -> int:
    d = date.fromisoformat(value)
    if d.year != YEAR:
        raise CodeError(f"Dates must be in {YEAR}.")
    return d.timetuple().tm_yday


def day_text(number: int) -> str:
    if not 1 <= int(number) <= 365:
        raise CodeError("This code holds a date outside the model year.")
    return (date(YEAR, 1, 1) + timedelta(days=int(number) - 1)).isoformat()


def dated_episodes(scenario: dict, day: str) -> list[dict]:
    """A library scenario's episode templates as dated episodes from ``day`` (as the Studio's episodeDates)."""
    start, end = date.fromisoformat(day), date(YEAR, 12, 31)
    out = []
    for t in scenario.get("episodes", []):
        frm = min(start + timedelta(days=int(t.get("startOffset") or 0)), end)
        to = None if t.get("durationDays") is None else min(frm + timedelta(days=max(1, int(t["durationDays"])) - 1), end)
        ep = {"title": t.get("title") or scenario["title"], "from": frm.isoformat(), "to": to.isoformat() if to else None,
              "ramp": int(t.get("ramp") or 0), "settings": t.get("settings") or {}}
        if t.get("pattern"):
            ep["pattern"] = t["pattern"]
        out.append(ep)
    return out


def _pack_episode(ep: dict) -> dict:
    out = {"t": str(ep.get("title") or ""), "f": day_number(ep["from"]), "s": ep.get("settings") or {}}
    if ep.get("to"):
        out["u"] = day_number(ep["to"])
    if int(ep.get("ramp") or 0):
        out["m"] = int(ep["ramp"])
    if ep.get("pattern"):
        out["p"] = ep["pattern"]
    return out


def _unpack_episode(e: dict) -> dict:
    if not isinstance(e, dict) or "f" not in e:
        raise CodeError("This code holds an episode without a start day.")
    return {"title": e.get("t") or "Episode", "from": day_text(e["f"]), "to": day_text(e["u"]) if e.get("u") else None,
            "ramp": int(e.get("m") or 0), "settings": e.get("s") or {}, "pattern": e.get("p") or None}


def _diff(base: Any, value: Any) -> Any:
    """The parts of ``value`` that differ from ``base`` (dicts recursively); None when nothing does."""
    if isinstance(value, dict) and isinstance(base, dict):
        out = {k: d for k, v in value.items() if (d := _diff(base.get(k), v)) is not None}
        return out or None
    return None if value == base else value


def _overrides(base: dict, values: dict) -> dict:
    """``values`` without the leaves that already hold the base value (an override that changes nothing)."""
    out = {}
    for k, v in (values or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            inner = _overrides(base[k], v)
            if inner:
                out[k] = inner
        elif k not in base or v != base[k]:
            out[k] = v
    return out


def pack(proposal: dict) -> dict:
    """The compact payload of a proposal (the wizard's inputs, api/_agent_config.py Proposal by alias)."""
    from api._agent_config import grouped_ops_defaults, preset_config
    from utilsim.config.model import RUN_GROUPS, SimConfig
    from utilsim.config.presets import deep_merge

    preset = str(proposal.get("preset") or "")
    base = preset_config(preset).model_dump(mode="json")
    town = _overrides(base, proposal.get("townOverrides") or {})
    cfg = SimConfig.model_validate(deep_merge(base, town))
    merged = cfg.model_dump(mode="json")
    out: dict[str, Any] = {"p": preset}
    if proposal.get("execution") == "local" and proposal.get("totalHomes"):
        out["x"] = int(proposal["totalHomes"])
    for key, short in (("name", "n"), ("seed", "s"), ("purpose", "q"), ("region", "l")):
        if proposal.get(key):
            out[short] = str(proposal[key])
    goals = proposal.get("goals")
    if goals and goals != ["everything"]:
        out["g"] = list(goals)
    if proposal.get("asOf") and proposal["asOf"] != DEFAULT_AS_OF:
        out["a"] = day_number(proposal["asOf"])
    if town:
        out["t"] = town
    run = _overrides({k: merged[k] for k in RUN_GROUPS}, proposal.get("settings") or {})
    if run:
        out["r"] = run
    ops = _overrides(grouped_ops_defaults(cfg), proposal.get("operations") or {})
    if ops:
        out["o"] = ops
    episodes = [_pack_episode(e) for e in proposal.get("episodes") or []]
    if episodes:
        out["e"] = episodes
    return out


def unpack(payload: dict) -> dict:
    """A proposal (by alias) from a payload; validate it with api/_agent_config.py validate_proposal afterwards."""
    if not isinstance(payload, dict) or not isinstance(payload.get("p"), str):
        raise CodeError("This code does not describe a simulation.")
    goals = payload.get("g")
    out = {"execution": "local" if payload.get("x") else "hosted", "totalHomes": int(payload["x"]) if payload.get("x") else None,
           "name": str(payload.get("n") or "Imported simulation")[:100], "goals": list(goals) if goals else ["everything"],
           "purpose": str(payload.get("q") or "")[:500], "region": str(payload.get("l") or "")[:200],
           "preset": payload["p"], "seed": str(payload.get("s") or "")[:64],
           "asOf": day_text(payload["a"]) if payload.get("a") else DEFAULT_AS_OF,
           "townOverrides": payload.get("t") or {}, "settings": payload.get("r") or {}, "operations": payload.get("o") or {},
           "episodes": [_unpack_episode(e) for e in payload.get("e") or []], "summary": SUMMARY}
    for key in ("townOverrides", "settings", "operations"):
        if not isinstance(out[key], dict):
            raise CodeError("This code does not describe a simulation.")
    return out


# ---- codes -------------------------------------------------------------------------------------------------------
def encode(proposal: dict) -> str:
    text = orjson.dumps(pack(proposal), option=orjson.OPT_SORT_KEYS)
    z = zlib.compressobj(9, zlib.DEFLATED, -15, 9, zlib.Z_DEFAULT_STRATEGY, zdict=dictionary())
    data = z.compress(text) + z.flush() + (zlib.crc32(text) & 0xFFFF).to_bytes(2, "big")
    return f"{PREFIX}{VERSION}{b32encode(data)}"


def decode(code: str) -> dict:
    """The proposal a code holds (CodeError when it is not one, is damaged, or needs another version)."""
    text = clean(code)
    if len(text) > MAX_CODE_CHARS:
        raise CodeError("This is too long to be a simulation code.")
    if not text.startswith(PREFIX) or len(text) <= len(PREFIX) or text[len(PREFIX)] not in _DECODE:
        raise CodeError(f"A simulation code starts with {PREFIX}{VERSION}.")
    version = _DECODE[text[len(PREFIX)]]
    if len(text) < len(PREFIX) + 6:
        raise CodeError("This code is too short.")
    if version != VERSION:
        raise CodeError("This code was made with a newer version of Utility Studio. Update the app to open it.")
    data = b32decode(text[len(PREFIX) + 1:])
    if len(data) < 3:
        raise CodeError("This code is too short.")
    body, check = data[:-2], int.from_bytes(data[-2:], "big")
    try:
        z = zlib.decompressobj(-15, zdict=dictionary(version))
        plain = z.decompress(body, MAX_PAYLOAD)
        if z.unconsumed_tail or not z.eof:
            raise CodeError("This code is damaged: a character is missing or wrong.")
        payload = orjson.loads(plain)
    except (zlib.error, orjson.JSONDecodeError) as exc:
        raise CodeError("This code is damaged: a character is missing or wrong.") from exc
    if zlib.crc32(plain) & 0xFFFF != check:
        raise CodeError("This code is damaged: a character is missing or wrong.")
    return unpack(payload)
