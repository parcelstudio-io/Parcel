#!/usr/bin/env python3
"""Freeze DSP-2 authored sources and episode fixtures before test rollout."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


FILES = (
    "DESIGN.md",
    "DEVELOPMENT_DECISIONS.md",
    "fixtures.json",
    "episode_manifest.json",
    "experiment.py",
    "verify_results.py",
    "freeze_manifest.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=directory / "FROZEN_MANIFEST.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.force:
        raise SystemExit(f"refusing to replace existing freeze: {args.output}")
    missing = [name for name in FILES if not (directory / name).is_file()]
    if missing:
        raise SystemExit(f"missing frozen inputs: {missing}")
    fixture = json.loads((directory / "fixtures.json").read_text())
    manifest = json.loads((directory / "episode_manifest.json").read_text())
    canonical_fixture = json.dumps(fixture, sort_keys=True, separators=(",", ":")).encode()
    fixture_lineage = hashlib.sha256(canonical_fixture).hexdigest()
    if manifest["generated_from_fixture_sha256"] != fixture_lineage:
        raise SystemExit("episode manifest does not match fixtures")
    split_seeds = {split: set(block["base_sensor_seeds"]) for split, block in fixture["splits"].items()}
    for left in split_seeds:
        for right in split_seeds:
            if left < right and split_seeds[left] & split_seeds[right]:
                raise SystemExit(f"sensor seed overlap: {left}/{right}")
    test_count = sum(entry["split"] == "test" for entry in manifest["episodes"])
    if test_count != fixture["expected_test_inventory"]["total_episodes"]:
        raise SystemExit(f"test inventory mismatch: {test_count}")
    payload = {
        "schema_version": 1,
        "study": "DSP-2",
        "frozen_before_first_test_rollout": True,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": {name: digest(directory / name) for name in FILES},
        "fixture_canonical_sha256": fixture_lineage,
        "inventory": manifest["split_inventory"],
        "test_episodes": test_count,
        "claim_boundary": fixture["evidence_tier"],
    }
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "sha256": digest(args.output), "test_episodes": test_count}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
