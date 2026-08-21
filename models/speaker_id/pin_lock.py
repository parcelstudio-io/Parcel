#!/usr/bin/env python3
"""Pin the speaker-embedding model's provenance after download, then verify it.

Card F1-SI. Mirrors ``models/judge/pin_lock.py`` and ``models/reasoner/
models.lock.json``: the lock records the exact release the artifact came from
and the digest of the bytes actually on disk, and it admits Apache-2.0 only.

    python models/speaker_id/pin_lock.py --pin      # compute digest, write the lock
    python models/speaker_id/pin_lock.py --verify   # re-check disk against the lock

WHY THIS MODEL GETS A LOCK AT ALL
---------------------------------
It is the only model in this repository whose output is a **security decision**.
The judge scores transcripts after the fact and the reasoner writes sentences; a
substituted file there costs a wrong opinion. A substituted file here decides
whether a stranger's voice can move a robot dog, and it would do it silently,
because a different network still returns a plausible 192-float vector and a
cosine against it still prints as a number between zero and one.

The digest is checked against the bytes on disk; the enrolled owner profile
records the same digest at enrollment time (``model_sha256``), so a model swapped
*after* enrollment is visible from the profile alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "models.lock.json"

REPOSITORY = "k2-fsa/sherpa-onnx"
#: The GitHub release tag the sherpa-onnx project publishes its speaker models
#: under. The upstream tag really is spelled this way; it is quoted verbatim
#: rather than corrected, because a "fixed" tag is a 404.
RELEASE_TAG = "speaker-recongition-models"
FILENAME = "nemo_en_titanet_small.onnx"
EXPECTED_SIZE = 40_257_283
URL = f"https://github.com/{REPOSITORY}/releases/download/{RELEASE_TAG}/{FILENAME}"

KEY = "nemo_en_titanet_small"


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
            f"size mismatch: {size} != {EXPECTED_SIZE} announced by the release. "
            "Refusing to pin a partial or substituted download."
        )
    return {
        "filename": FILENAME,
        "url": URL,
        "size_bytes": size,
        "sha256": sha256_file(path),
        "source": f"https://github.com/{REPOSITORY}",
        "source_release": RELEASE_TAG,
        "upstream_filename": FILENAME,
        "upstream_origin": (
            "NVIDIA NeMo titanet_small, exported to ONNX and republished by the "
            "sherpa-onnx project"
        ),
        "license": "Apache-2.0",
        "role": "speaker_embedding_for_command_arming_only",
        "activation": (
            "identity_gate_for_command_arming_never_the_emergency_latch"
        ),
        "measured_on_this_host": {
            "bench": "scrum/20260820/research/bench_doa.md Bench B",
            "pairs": 378,
            "same_speaker_cos_mean": 0.802,
            "cross_speaker_cos_mean": 0.033,
            "zero_overlap_margin": 0.209,
            "latency_ms_median": 27.1,
            "latency_ms_p95": 126.1,
            "load_ms": 115,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pin", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    path = ROOT / FILENAME
    if not path.is_file():
        print(f"error: {path} is not present; download it first:", file=sys.stderr)
        print(f"  {URL}", file=sys.stderr)
        return 2

    if args.pin:
        payload = {"schema_version": 1, "models": {KEY: build_entry(path)}}
        LOCK.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"pinned {FILENAME}: sha256={payload['models'][KEY]['sha256']}")
        return 0

    if not LOCK.is_file():
        print(f"error: {LOCK} is missing; run --pin first", file=sys.stderr)
        return 2
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    entry = lock.get("models", {}).get(KEY)
    if not isinstance(entry, dict):
        print(f"error: {LOCK} has no {KEY!r} entry", file=sys.stderr)
        return 2
    size = path.stat().st_size
    digest = sha256_file(path)
    problems: list[str] = []
    if size != entry.get("size_bytes"):
        problems.append(f"size {size} != locked {entry.get('size_bytes')}")
    if digest != entry.get("sha256"):
        problems.append(f"sha256 {digest} != locked {entry.get('sha256')}")
    if entry.get("license") != "Apache-2.0":
        problems.append(f"license {entry.get('license')!r} is not Apache-2.0")
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print(f"verified {FILENAME}: sha256={digest} ({size} bytes, {entry.get('license')})")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
