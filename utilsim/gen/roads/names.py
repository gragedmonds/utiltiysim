"""Seeded, Ontario-flavoured street names for synthetic roads (never real addresses)."""

from __future__ import annotations

import numpy as np

from utilsim.core.rng import Purpose, hash_u01

WORDS = [
    "Maple", "Oak", "Birch", "Cedar", "Elm", "Willow", "Pine", "Spruce", "Aspen", "Ash", "Hickory", "Walnut",
    "Chestnut", "Sumac", "Tamarack", "Juniper", "Linden", "Beech", "Poplar", "Alder", "Hawthorn", "Basswood",
    "Meadow", "Orchard", "Ridge", "Valley", "Creek", "Brook", "Glen", "Heron", "Fox", "Hawk", "Harvest",
    "Trillium", "Bluebell", "Clover", "Fairway", "Highland", "Lakeview", "Millpond", "Stonegate", "Fieldstone",
    "Wheatfield", "Barley", "Copper", "Silverthorn", "Ironwood", "Kingfisher", "Loon", "Osprey", "Cardinal",
    "Bramble", "Thistle", "Heather", "Primrose", "Larkspur", "Foxglove", "Wildrose", "Sandhill", "Bayview",
    "Elgin", "Colborne", "Talbot", "Bayfield", "Simcoe", "Huron", "Lennox", "Wentworth", "Haldimand", "Brant",
    "Carleton", "Dufferin", "Frontenac", "Grenville", "Hastings", "Leeds", "Lambton", "Norfolk", "Peel", "Russell",
    "Selkirk", "Tecumseh", "Moodie", "Galbraith", "MacKay", "Fraser", "Gillespie", "Ferguson", "Laidlaw", "Munro",
]
SUFFIX = {
    0: ["Road", "Line", "Sideroad", "Concession Road"],
    1: ["Avenue", "Boulevard", "Drive", "Parkway"],
    2: ["Street", "Crescent", "Drive", "Way", "Avenue", "Trail", "Gate", "Lane"],
    3: ["Court", "Place", "Close", "Circle"],
}


class NamePool:
    """Deterministic name dealer: each call returns a fresh name for the class until combinations run out."""

    def __init__(self, seed: str, reserved: set[str] | None = None):
        self.seed = seed
        self.used = set(reserved or ())
        self.counter = 0

    def next(self, kind: int) -> str:
        suffixes = SUFFIX[kind]
        for _ in range(4000):
            self.counter += 1
            u = hash_u01(self.seed, Purpose.STREET_NAME, self.counter, kind)
            w = WORDS[int(u * len(WORDS))]
            s = suffixes[int(hash_u01(self.seed, Purpose.STREET_NAME, self.counter, kind + 10) * len(suffixes))]
            name = f"{w} {s}"
            if name not in self.used:
                self.used.add(name)
                return name
        name = f"{WORDS[self.counter % len(WORDS)]} {suffixes[0]} {self.counter}"
        self.used.add(name)
        return name


def concession_names(n: int) -> list[str]:
    return [f"Concession Road {i + 3}" for i in range(n)]


def as_array(names: list[str]) -> np.ndarray:
    return np.asarray(names, dtype=object)
