"""Capture/compare deterministic sections without changing fixtures or accepting drift.

Use ``python -m scripts.diagnose_goldens --help`` from the repository root.
Outputs must be new files. A comparison exits 1 on any exact difference, including
polygon ring rotations; geometric measurements explain differences, not waive them.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path

import orjson
import shapely
from shapely.geometry import Polygon

from scripts.update_goldens import CASES, SECTIONS
from utilsim.config import load_preset
from utilsim.config.model import SimConfig
from utilsim.gen.pipeline import generate
from utilsim.io.snapshot import build_snapshot

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "golden-diagnostic/1"


def read_json(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def write_new(path, value):
    # Exclusive creation also protects callers who accidentally name a golden file.
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def digest(value):
    return hashlib.sha256(orjson.dumps(value, option=orjson.OPT_SORT_KEYS)).hexdigest()[:16]


def environment():
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT, check=False).returncode
    return {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine(),
            "libraries": {name: version(name) for name in ("numpy", "scipy", "shapely", "orjson")},
            "geos": shapely.geos_version_string, "gitRevision": revision.stdout.strip(),
            "trackedChanges": bool(dirty), "lockSha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()}


def capture(case):
    if case == "example-480":
        reference = read_json(ROOT / "examples/village-480-seed42/snapshot.json.gz")
        config = SimConfig.model_validate(reference["config"])
    else:
        preset, seed, houses = CASES[case]
        config = load_preset(preset, seed=seed, houses=houses)
    snapshot = build_snapshot(generate(config))
    selected = {key: snapshot[key] for key in ["id", "generatorVersion", "config", *SECTIONS]}
    expected = read_json(ROOT / "tests/golden/digests.json")["cases"].get(case)
    actual = {key: digest(snapshot[key]) for key in SECTIONS} | {"townId": snapshot["id"]}
    return {"schemaVersion": SCHEMA, "case": case, "environment": environment(), "snapshot": selected,
            "expectedDigests": expected, "actualDigests": actual,
            "changedGoldenSections": [key for key in actual if expected and actual[key] != expected[key]]}


def ring_key(points):
    ring = [(p["x"], p["z"]) for p in points]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if not ring:
        return ()
    return min(tuple(r[i:] + r[:i]) for r in (ring, ring[::-1]) for i in range(len(r)))


def polygon_difference(before, after):
    same_ring = ring_key(before) == ring_key(after)
    result = {"classification": "ring-order-only" if same_ring else "different-vertices",
              "beforeVertices": len(before), "afterVertices": len(after)}
    a = Polygon([(p["x"], p["z"]) for p in before])
    b = Polygon([(p["x"], p["z"]) for p in after])
    result["valid"] = a.is_valid and b.is_valid
    if result["valid"]:
        result.update(hausdorffM=a.hausdorff_distance(b), symmetricDifferenceM2=a.symmetric_difference(b).area)
    return result


def records_by_id(records):
    if isinstance(records, dict):
        return records
    by_id = {row["id"]: row for row in records}
    if len(by_id) != len(records):
        raise ValueError("Duplicate record identities in compared section")
    return by_id


def compare(reference, candidate, detail_limit=25):
    if type(detail_limit) is not int or not 0 <= detail_limit <= 1000:
        raise ValueError("detail_limit must be an integer between 0 and 1000")
    a = reference["snapshot"] if reference.get("schemaVersion") == SCHEMA else reference
    b = candidate["snapshot"] if candidate.get("schemaVersion") == SCHEMA else candidate
    report = {"schemaVersion": "golden-comparison/1", "exactMatch": True,
              "referenceEnvironment": reference.get("environment"),
              "candidateEnvironment": candidate.get("environment"), "metadataDifferences": {}, "sections": {}}
    for key in ("id", "generatorVersion", "config"):
        if a[key] != b[key]:
            report["metadataDifferences"][key] = {"reference": a[key], "candidate": b[key]}
            report["exactMatch"] = False
    for section in SECTIONS:
        # JSON encoding catches signed zero and int/float differences that Python == hides.
        ah, bh = digest(a[section]), digest(b[section])
        aa, bb = records_by_id(a[section]), records_by_id(b[section])
        summary = {"exactMatch": ah == bh, "referenceDigest": ah, "candidateDigest": bh,
                   "referenceCount": len(aa), "candidateCount": len(bb),
                   "added": sorted(bb.keys() - aa.keys()), "removed": sorted(aa.keys() - bb.keys()),
                   "recordOrderChanged": isinstance(a[section], list) and list(aa) != list(bb), "changedRecords": 0,
                   "ringOrderOnly": 0, "differentVertices": 0, "details": []}
        for key in sorted(aa.keys() & bb.keys()):
            old, new = aa[key], bb[key]
            if digest(old) == digest(new):
                continue
            summary["changedRecords"] += 1
            fields = [field for field in sorted(old.keys() | new.keys())
                      if field not in old or field not in new or digest(old[field]) != digest(new[field])]
            detail = {"id": key, "fields": fields}
            if section == "parcels" and "polygon" in fields and "polygon" in old and "polygon" in new:
                detail["geometry"] = polygon_difference(old["polygon"], new["polygon"])
                classification = detail["geometry"]["classification"]
                summary["ringOrderOnly" if classification == "ring-order-only" else "differentVertices"] += 1
            if len(summary["details"]) < detail_limit:
                detail["values"] = {field: {"referencePresent": field in old, "candidatePresent": field in new,
                                            "reference": old.get(field), "candidate": new.get(field)} for field in fields}
                summary["details"].append(detail)
        summary["detailsOmitted"] = summary["changedRecords"] - len(summary["details"])
        report["sections"][section] = summary
        report["exactMatch"] &= summary["exactMatch"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    take = commands.add_parser("capture", help="Generate one case and save exact sections plus runtime metadata")
    take.add_argument("--case", choices=[*CASES, "example-480"], required=True)
    take.add_argument("--output", type=Path, required=True)
    diff = commands.add_parser("compare", help="Compare captures or full JSON/gzip snapshots; changes exit 1")
    diff.add_argument("reference", type=Path)
    diff.add_argument("candidate", type=Path)
    diff.add_argument("--output", type=Path, required=True)
    diff.add_argument("--detail-limit", type=int, default=25)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new file (references are never overwritten).")
    if args.command == "capture":
        result = capture(args.case)
        write_new(args.output, result)
        print(json.dumps({"case": args.case, "changedGoldenSections": result["changedGoldenSections"]}))
        return int(bool(result["changedGoldenSections"]))
    result = compare(read_json(args.reference), read_json(args.candidate), args.detail_limit)
    write_new(args.output, result)
    print(json.dumps({"exactMatch": result["exactMatch"], "changedSections":
                      [key for key, value in result["sections"].items() if not value["exactMatch"]]}))
    return int(not result["exactMatch"])


if __name__ == "__main__":
    raise SystemExit(main())
