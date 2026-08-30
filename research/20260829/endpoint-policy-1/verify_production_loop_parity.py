"""Replay the declared default cells through the actual production voice loop."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np

from parcel_robot.audio.endpointing import SileroVad, TurnEndpointer
from parcel_robot.audio.voice_loop import MicrophoneVoiceLoop

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location("endpoint_policy_run", HERE / "run.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load endpoint policy runner")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _NoTranscriptRecognizer:
    def transcribe(self, _wav_audio: bytes) -> str:
        return ""


class _CommitRecordingLoop(MicrophoneVoiceLoop):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.commit_sample_clocks_s: list[float] = []

    def _commit_turn(self) -> None:
        self.commit_sample_clocks_s.append(self._elapsed_s)
        super()._commit_turn()


def actual_commits(frames: list[np.ndarray]) -> list[float]:
    vad = SileroVad(str(runner.SILERO))
    endpointer = TurnEndpointer(str(runner.SMART_TURN))
    if not vad.available or endpointer.detail != "smart-turn-v3":
        raise RuntimeError("required production endpoint models are unavailable")
    loop = _CommitRecordingLoop(
        recognizer=_NoTranscriptRecognizer(),
        submit_text=lambda *_args, **_kwargs: None,
        barge_in=lambda: None,
        playback_active=lambda: False,
        neural_vad=vad,
        endpointer=endpointer,
    )
    for frame in frames:
        loop.run_once(frame)
    return loop.commit_sample_clocks_s


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    selected, _manifest = runner.verify_and_load_inputs()
    variants = runner.prepare_variants(selected)
    probability = runner.SmartTurnProbability()
    cells: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for variant in variants:
        replay = runner.replay_policy(
            frames=variant["frames"],
            flags=variant["flags"],
            probability=probability,
            confidence_threshold=0.5,
            complete_silence_s=0.2,
        )
        expected = [float(value) for value in replay["commit_sample_clocks_s"]]
        actual = actual_commits(variant["frames"])
        same_count = len(expected) == len(actual)
        deltas = (
            [abs(left - right) for left, right in zip(expected, actual, strict=True)]
            if same_count
            else []
        )
        expected_frames = [round(value / runner.FRAME_S) for value in expected]
        actual_frames = [round(value / runner.FRAME_S) for value in actual]
        same_sample_clock = (
            same_count
            and expected_frames == actual_frames
            and all(delta <= 1e-9 for delta in deltas)
        )
        cell = {
            "name": variant["name"],
            "kind": variant["kind"],
            "phase_offset_samples": variant["phase_offset_samples"],
            "duplicate_state_machine_commit_clocks_s": expected,
            "production_loop_commit_clocks_s": actual,
            "commit_clock_abs_deltas_s": deltas,
            "duplicate_state_machine_commit_frame_indices": expected_frames,
            "production_loop_commit_frame_indices": actual_frames,
            "same_sample_clock": same_sample_clock,
        }
        cells.append(cell)
        if not same_sample_clock:
            mismatches.append(cell)

    report = {
        "schema": "parcel-endpoint-production-loop-parity-1",
        "scope": "direct_frames_real_models_actual_microphone_voice_loop_no_pipewire_no_device",
        "policy": {"confidence_threshold": 0.5, "complete_silence_s": 0.2},
        "cell_count": len(cells),
        "sample_clock_match_count": sum(int(cell["same_sample_clock"]) for cell in cells),
        "mismatch_count": len(mismatches),
        "pass": len(cells) == 52 and not mismatches,
        "source_hashes": {
            "parity_script": sha256(Path(__file__)),
            "sensitivity_runner": sha256(HERE / "run.py"),
            "voice_loop": sha256(ROOT / "src/parcel_robot/audio/voice_loop.py"),
            "endpointing": sha256(ROOT / "src/parcel_robot/audio/endpointing.py"),
            "silero": sha256(runner.SILERO),
            "smart_turn": sha256(runner.SMART_TURN),
        },
        "mismatches": mismatches,
        "cells": cells,
        "does_not_prove": [
            "PipeWire, capture-device, room, noise, AEC, or human-speech parity",
            "corrected acoustic-v2 baseline parity",
            "endpoint policy quality or mount readiness",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "cell_count": report["cell_count"],
                "sample_clock_match_count": report["sample_clock_match_count"],
                "mismatch_count": report["mismatch_count"],
                "pass": report["pass"],
            },
            indent=2,
        )
    )
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
