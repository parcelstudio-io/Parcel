#!/usr/bin/env python
"""Derive an acoustic-mode config from configs/robot.yaml.

WHY THIS EXISTS INSTEAD OF AN EDIT
    configs/robot.yaml is hash-locked by evals/companion/embodied_plan_v1's
    manifest (`locked_inputs.robot_config`), and run_embodied_plan_v1.py
    refuses to run when the sha changes. Editing it to turn on semantic
    endpointing would break that frozen suite for everyone.

    Parcel has no config-overlay mechanism — ConfigStore loads exactly one
    YAML file and never merges (src/parcel_robot/config.py). What it does have
    is a `--config PATH` flag on the CLI, the panel and scripts/launch_sim.sh.
    So the overlay is a DERIVED sibling file, regenerated from robot.yaml
    rather than forked from it: a hand-maintained copy is precisely the
    "divergent config with stale keys" trap the packaged
    src/parcel_robot/config/robot.yaml already fell into.

    Regenerate after ANY change to configs/robot.yaml. The generated file
    records the source sha256 it was derived from, and --check tells you when
    it has gone stale.

USAGE
    .parcel/bin/python scripts/make_acoustic_config.py          # write it
    .parcel/bin/python scripts/make_acoustic_config.py --check  # stale?
    scripts/launch_sim.sh --config configs/robot.acoustic.yaml --llm

WHAT IT CHANGES (speech: only — nothing else is touched)
    endpointing: energy -> semantic     turn segmentation by Smart Turn v3
    vad_model:   models/endpointing/silero_vad_v6.onnx
    turn_model:  models/endpointing/smart_turn_v3.onnx

    echo_guard_scale is deliberately LEFT at 2.5. The plan lowers it only
    after an ERLE gate passes, and no ERLE has been measured on this machine
    because no acoustic echo path exists yet.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "configs" / "robot.yaml"
TARGET = REPO_ROOT / "configs" / "robot.acoustic.yaml"

SPEECH_OVERRIDES = {
    "endpointing": "semantic",
    "vad_model": "models/endpointing/silero_vad_v6.onnx",
    "turn_model": "models/endpointing/smart_turn_v3.onnx",
}

HEADER = """\
# GENERATED FILE - DO NOT EDIT BY HAND.
#
# Derived from configs/robot.yaml by scripts/make_acoustic_config.py.
# Regenerate after any change to configs/robot.yaml:
#     .parcel/bin/python scripts/make_acoustic_config.py
#
# configs/robot.yaml is hash-locked by evals/companion/embodied_plan_v1's
# manifest, so acoustic-mode settings live here instead of being edited in.
# Use it with:  scripts/launch_sim.sh --config configs/robot.acoustic.yaml
#
# Difference from configs/robot.yaml (speech: block only):
#   endpointing: energy -> semantic
#   vad_model:   models/endpointing/silero_vad_v6.onnx   (added)
#   turn_model:  models/endpointing/smart_turn_v3.onnx   (added)
#
# echo_guard_scale stays at 2.5: it is lowered only after an ERLE gate
# passes, and no acoustic echo path exists on this machine yet.
#
# derived_from: configs/robot.yaml
# source_sha256: {sha}
"""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recorded_source_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# source_sha256:"):
            return line.split(":", 1)[1].strip()
    return None


def build() -> tuple[str, str]:
    data = yaml.safe_load(SOURCE.read_text(encoding="utf-8")) or {}
    speech = data.get("speech")
    if not isinstance(speech, dict):
        raise SystemExit("configs/robot.yaml has no speech: mapping")
    speech.update(SPEECH_OVERRIDES)
    data["speech"] = speech
    source_sha = sha256_of(SOURCE)
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False, width=100)
    return HEADER.format(sha=source_sha) + body, source_sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if the derived file is missing or stale",
    )
    args = parser.parse_args()

    if not SOURCE.is_file():
        print(f"missing {SOURCE}", file=sys.stderr)
        return 1

    content, source_sha = build()

    if args.check:
        recorded = recorded_source_sha(TARGET)
        if recorded is None:
            print(f"{TARGET.name} does not exist; run without --check", file=sys.stderr)
            return 1
        if recorded != source_sha:
            print(
                f"{TARGET.name} is STALE: derived from {recorded[:16]}..., "
                f"configs/robot.yaml is now {source_sha[:16]}...",
                file=sys.stderr,
            )
            return 1
        print(f"{TARGET.name} is current (source {source_sha[:16]}...)")
        return 0

    TARGET.write_text(content, encoding="utf-8")
    print(f"wrote {TARGET}")
    print(f"  derived from configs/robot.yaml sha256 {source_sha}")
    for key, value in SPEECH_OVERRIDES.items():
        print(f"  speech.{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
