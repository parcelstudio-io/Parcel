#!/usr/bin/env python3
"""Freeze the complete LHO-1 implementation/evaluator source inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = (
    "DESIGN.md",
    "AMENDMENT_1_COVERING_ARRAY.md",
    "AMENDMENT_2_PRE_EVIDENCE_AUDIT.md",
    "AMENDMENT_3_FREEZE_READINESS.md",
    "freeze_manifest.py",
    "freeze_sources.py",
    "run.py",
    "verify_results.py",
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "study": "LHO-1",
        "files": {relative: _sha((ROOT / relative).read_bytes()) for relative in SOURCE_FILES},
    }
    value["manifest_sha256"] = _sha(_canonical(value))
    return value


def verify(value: dict[str, object]) -> None:
    expected = value.get("manifest_sha256")
    payload = dict(value)
    payload.pop("manifest_sha256", None)
    if expected != _sha(_canonical(payload)):
        raise ValueError("source manifest digest mismatch")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != set(SOURCE_FILES):
        raise ValueError("source manifest inventory mismatch")
    for relative, digest in files.items():
        if digest != _sha((ROOT / relative).read_bytes()):
            raise ValueError(f"source changed after freeze: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "source-manifest.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        value = json.loads(args.output.read_text(encoding="utf-8"))
    else:
        value = build()
        args.output.write_bytes(_canonical(value) + b"\n")
    verify(value)
    print(
        json.dumps({"path": str(args.output), "sha256": value["manifest_sha256"]}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
