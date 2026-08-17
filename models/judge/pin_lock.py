#!/usr/bin/env python3
"""Pin the judge model's provenance after download, then verify it.

Mirrors ``models/reasoner/models.lock.json``: the lock records the exact
revision the artifact came from and the digest of the bytes actually on disk,
and it admits Apache-2.0 only.

    python models/judge/pin_lock.py --pin      # compute digest, write the lock
    python models/judge/pin_lock.py --verify   # re-check disk against the lock
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "models.lock.json"

REPOSITORY = "Qwen/Qwen3-32B-GGUF"
SOURCE_COMMIT = "938a7432affaec9157f883a87164e2646ae17555"
FILENAME = "Qwen3-32B-Q4_K_M.gguf"
EXPECTED_SIZE = 19_762_149_024


def sha256_file(path: Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def build_entry(path: Path) -> dict[str, object]:
    size = path.stat().st_size
    if size != EXPECTED_SIZE:
        raise SystemExit(
            f"size mismatch: {size} != {EXPECTED_SIZE} announced by the hub. "
            "Refusing to pin a partial or substituted download."
        )
    return {
        "filename": FILENAME,
        "url": (
            f"https://huggingface.co/{REPOSITORY}/resolve/{SOURCE_COMMIT}/{FILENAME}?download=true"
        ),
        "size_bytes": size,
        "sha256": sha256_file(path),
        "source": f"https://huggingface.co/{REPOSITORY}",
        "source_commit": SOURCE_COMMIT,
        "upstream_filename": FILENAME,
        "license": "Apache-2.0",
        "role": "offline_autorater_judge_only",
        "activation": "evaluation_only_never_a_runtime_or_motion_authority",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pin", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    path = ROOT / FILENAME
    if not path.is_file():
        print(f"error: {path} is not present; download it first", file=sys.stderr)
        return 2

    if args.pin:
        payload = {
            "schema_version": 1,
            "models": {"qwen3_32b_q4_k_m_judge": build_entry(path)},
        }
        LOCK.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"pinned {FILENAME}: sha256={payload['models']['qwen3_32b_q4_k_m_judge']['sha256']}")
        return 0

    if not LOCK.is_file():
        print("error: no lock to verify against; run --pin first", file=sys.stderr)
        return 2
    spec = json.loads(LOCK.read_text(encoding="utf-8"))["models"]["qwen3_32b_q4_k_m_judge"]
    if spec["license"] != "Apache-2.0":
        print(f"error: {spec['license']} is not admitted by this Apache-only lock", file=sys.stderr)
        return 1
    actual_size, actual_digest = path.stat().st_size, sha256_file(path)
    problems = []
    if actual_size != spec["size_bytes"]:
        problems.append(f"size {actual_size} != {spec['size_bytes']}")
    if actual_digest != spec["sha256"]:
        problems.append(f"sha256 {actual_digest[:12]} != {spec['sha256'][:12]}")
    if problems:
        print("judge model FAILED verification: " + "; ".join(problems), file=sys.stderr)
        return 1
    print(f"judge model verified: {FILENAME} sha256={actual_digest[:12]}… @ {SOURCE_COMMIT[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
