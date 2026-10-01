"""Identifier conventions.

Public ids follow Astra's ``utility-town/1.0`` grammar so the existing viewer keeps working:
``P-00001`` premise, ``B-P-00001`` building, ``CA-P-00001`` contract account, ``SP-P-00001-electric`` service
point, ``M-P-00001-electric`` meter, ``M-P-00001-electric-import`` register, ``IN-P-00001-electric`` installation,
``C-P-00001-electric`` contract, ``electric-N-P-00001`` meter node, ``electric-E42`` edge.

Every entity additionally carries a content-derived ``uid`` (blake2b of its structural ancestry) that survives
unrelated upstream changes. All ids are scoped by the town/simulation id; they are not globally unique.
"""

from __future__ import annotations

import hashlib

COMMODITIES = ("electric", "water", "gas")


def premise_id(i: int) -> str:
    return f"P-{i + 1:05d}"


def building_id(premise: str) -> str:
    return f"B-{premise}"


def account_id(premise: str) -> str:
    return f"CA-{premise}"


def business_partner_id(premise: str) -> str:
    return f"BP-{premise}"


def service_point_id(premise: str, commodity: str) -> str:
    return f"SP-{premise}-{commodity}"


def meter_id(premise: str, commodity: str) -> str:
    return f"M-{premise}-{commodity}"


def register_id(meter: str, direction: str) -> str:
    return f"{meter}-{direction}"


def installation_id(premise: str, commodity: str) -> str:
    return f"IN-{premise}-{commodity}"


def contract_id(premise: str, commodity: str) -> str:
    return f"C-{premise}-{commodity}"


def meter_node_id(commodity: str, premise: str) -> str:
    return f"{commodity}-N-{premise}"


def edge_id(commodity: str, n: int) -> str:
    return f"{commodity}-E{n}"


def seq_id(prefix: str, n: int, width: int = 5) -> str:
    return f"{prefix}-{n:0{width}d}"


def uid(*parts) -> str:
    """16-hex-char content uid from structural ancestry, e.g. uid('parcel', block_uid, face, lot)."""
    key = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return hashlib.blake2b(key, digest_size=8).hexdigest()


def str_key(s: str) -> int:
    """Stable 63-bit integer for a string, for use as a hash_u01 key."""
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "little") >> 1
