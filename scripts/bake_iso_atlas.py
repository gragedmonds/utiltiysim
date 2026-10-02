"""Bake Astra's isometric sprite sheets (assets/town/isometric) into the viewer's sprite atlas.

Each sheet cell is cropped to its artwork, the faint generation haze around it is cleared (alpha below
``HAZE``), the sprite is trimmed to what is left and scaled down to a size that still holds detail at close zoom,
then every sprite is shelf-packed into one WebP atlas with a JSON index:

    packages/town-viewer/dist/iso/atlas.webp
    packages/town-viewer/dist/iso/atlas.json   {"version", "image", "size": [w, h], "sprites": {name: [x, y, w, h]}}

Sprite names are ``<family>.<view>``. Views are the prototype's banks for houses (``ne``, ``nw``, ``se``, ``sw``,
``top``), ``iso``/``top`` for roadside equipment, and the five study positions for the batch-2 families
(``front-right``, ``front-left``, ``rear-left``, ``rear-right``, ``overhead``).

Run ``uv run python scripts/bake_iso_atlas.py`` after the artwork changes; the output is committed.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "assets/town/isometric"
OUT = ROOT / "packages/town-viewer/dist/iso"
HAZE = 28  # alpha at or below this is generation haze, not artwork
ATLAS_WIDTH = 2048
GAP = 8
VERSION = "iso-atlas/1.0"

# The original banks: name, columns, rows and the family name of each cell.
HOUSES = ["brick2", "bungalow_hip", "solar2", "victorian2", "bungalow_gable", "commercial"]
DIAGONAL = ["cottage", "brick_hip2", "ranch_hip"]
EQUIPMENT = ["tree", "pole", "pad", "hydrant", "bucket_truck_small", "electric_meter", "gas_meter", "water_meter"]
BATCH_VIEWS = ["front-right", "front-left", "rear-left", "rear-right", "overhead"]
BATCH = {
    "01-industrial-plant": "industrial",
    "02-utility-depot": "depot",
    "03-electric-substation": "substation",
    "04-water-pump-station": "pump_station",
    "05-elevated-water-tower": "water_tower",
    "06-gas-city-gate": "city_gate",
    "07-bucket-line-truck": "bucket_truck",
    "08-water-crew-truck-excavator": "water_truck",
    "09-gas-service-truck": "gas_truck",
    "10-meter-technician-van": "meter_van",
    "11-residential-electric-ami-meter": "ami_meter_module",
    "12-residential-diaphragm-gas-meter": "gas_meter_module",
}
# Longest side of each baked sprite, in atlas pixels.
MAX_SIDE = {"house": 224, "facility": 256, "vehicle": 128, "equipment": 128, "tree": 112, "module": 72}


def kind_of(family: str) -> str:
    if family in ("industrial", "depot", "substation", "pump_station", "water_tower", "city_gate"):
        return "facility"
    if family.endswith(("_truck", "_van")) or family == "bucket_truck_small":
        return "vehicle"
    if family.endswith("_module") or family.endswith("_meter"):
        return "module"
    if family == "tree":
        return "tree"
    if family in ("pole", "pad", "hydrant"):
        return "equipment"
    return "house"


def clean(cell: Image.Image) -> Image.Image | None:
    """Clear the haze, trim to the artwork and return it (None when the cell is empty)."""
    a = np.asarray(cell.convert("RGBA")).copy()
    alpha = a[..., 3]
    alpha[alpha <= HAZE] = 0
    # Soften the cut so edges stay anti-aliased rather than stepping from 28 to 0.
    edge = (alpha > 0) & (alpha < 96)
    alpha[edge] = ((alpha[edge].astype(np.int32) - HAZE) * 96 // (96 - HAZE)).clip(0, 255).astype(np.uint8)
    ys, xs = np.nonzero(alpha > 0)
    if len(xs) < 50:
        return None
    a[..., 3] = alpha
    return Image.fromarray(a[ys.min():ys.max() + 1, xs.min():xs.max() + 1], "RGBA")


def scaled(img: Image.Image, family: str) -> Image.Image:
    side = MAX_SIDE[kind_of(family)]
    k = min(1.0, side / max(img.size))
    if k >= 1:
        return img
    return img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)


def grid_cells(sheet: Image.Image, cols: int, rows: int, bounds: list | None):
    cw, ch = sheet.width / cols, sheet.height / rows
    for i in range(cols * rows):
        if bounds and i < len(bounds):
            x0, y0, x1, y1 = bounds[i]
            # The prototype's bounds are inclusive; pad a few pixels so trimming finds the true edge.
            box = (max(0, x0 - 4), max(0, y0 - 4), min(sheet.width, x1 + 5), min(sheet.height, y1 + 5))
        else:
            box = (round(i % cols * cw), round(i // cols * ch), round((i % cols + 1) * cw), round((i // cols + 1) * ch))
        yield i, sheet.crop(box)


def collect() -> dict[str, Image.Image]:
    bounds = json.loads((ART / "bounds.json").read_text())
    sprites: dict[str, Image.Image] = {}

    def add(name: str, family: str, cell: Image.Image):
        img = clean(cell)
        if img is not None:
            sprites[name] = scaled(img, family)

    for view in ("ne", "nw", "se", "sw", "top"):
        sheet = Image.open(ART / f"{view}.png")
        for i, cell in grid_cells(sheet, 3, 2, bounds.get(view)):
            add(f"{HOUSES[i]}.{view}", HOUSES[i], cell)
    # diagonal.png: front row, rear row, overhead row; diagonal-sides.png: one side row, the other side row.
    sheet = Image.open(ART / "diagonal.png")
    for i, cell in grid_cells(sheet, 3, 3, bounds.get("diagonal")):
        add(f"{DIAGONAL[i % 3]}.{('front', 'rear', 'top')[i // 3]}", DIAGONAL[i % 3], cell)
    sheet = Image.open(ART / "diagonal-sides.png")
    for i, cell in grid_cells(sheet, 3, 2, bounds.get("diagonal-sides")):
        add(f"{DIAGONAL[i % 3]}.{('side-a', 'side-b')[i // 3]}", DIAGONAL[i % 3], cell)
    for sheet_name, view in (("equipment", "iso"), ("equipment-top", "top")):
        sheet = Image.open(ART / f"{sheet_name}.png")
        for i, cell in grid_cells(sheet, 4, 2, bounds.get(sheet_name)):
            add(f"{EQUIPMENT[i]}.{view}", EQUIPMENT[i], cell)
    manifest = json.loads((ART / "batch-v2/manifest.json").read_text())
    for fam in manifest["families"]:
        family = BATCH[fam["id"]]
        sheet = Image.open(ART / "batch-v2" / fam["file"])
        for cell in fam["image"]["cells"]:
            if cell["index"] >= len(BATCH_VIEWS):
                continue
            x0, y0, x1, y1 = cell["cell_rect"]
            add(f"{family}.{BATCH_VIEWS[cell['index']]}", family, sheet.crop((x0, y0, x1, y1)))
    return sprites


def pack(sprites: dict[str, Image.Image]) -> tuple[Image.Image, dict[str, list[int]]]:
    # Sprites start on multiples of GAP with at least GAP pixels between them, so the viewer's quarter-size copy
    # (used at far zoom) keeps them apart too.
    order = sorted(sprites, key=lambda n: (-sprites[n].height, n))
    up = lambda v: -(-v // GAP) * GAP  # noqa: E731
    x = y = GAP
    shelf = 0
    places: dict[str, list[int]] = {}
    for name in order:
        w, h = sprites[name].size
        if x + w + GAP > ATLAS_WIDTH:
            x, y, shelf = GAP, up(y + shelf + GAP), 0
        places[name] = [x, y, w, h]
        x = up(x + w + GAP)
        shelf = max(shelf, h)
    atlas = Image.new("RGBA", (ATLAS_WIDTH, up(y + shelf + GAP)), (0, 0, 0, 0))
    for name, (px, py, _, _) in places.items():
        atlas.paste(sprites[name], (px, py))
    return atlas, dict(sorted(places.items()))


def main() -> None:
    sprites = collect()
    atlas, places = pack(sprites)
    OUT.mkdir(parents=True, exist_ok=True)
    atlas.save(OUT / "atlas.webp", "WEBP", quality=90, method=6, alpha_quality=100)
    index = {"version": VERSION, "image": "atlas.webp", "size": list(atlas.size), "haze": HAZE,
             "source": "assets/town/isometric (Pixel Town art, batch 1 and batch 2)", "sprites": places}
    (OUT / "atlas.json").write_text(json.dumps(index, separators=(",", ":")) + "\n")
    kb = (OUT / "atlas.webp").stat().st_size / 1024
    print(f"{len(places)} sprites -> {atlas.size[0]}x{atlas.size[1]} atlas.webp ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
