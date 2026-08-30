"""Deterministic state-machine checks for the endpoint sensitivity runner."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("endpoint_policy_run", HERE / "run.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load endpoint policy runner")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def replay(
    silent_frames: int,
    *,
    probability: float,
    timeout_s: float = 0.2,
) -> dict:
    frame = np.zeros(runner.INPUT_FRAME, dtype=np.int16)
    frames = [frame.copy() for _ in range(1 + silent_frames)]
    flags = [True, *([False] * silent_frames)]
    return runner.replay_policy(
        frames=frames,
        flags=flags,
        probability=lambda _tail: probability,
        confidence_threshold=0.5,
        complete_silence_s=timeout_s,
    )


def main() -> int:
    # Silence starts on the first false frame: seven frames expose 180 ms,
    # while eight expose 210 ms and cross a 200 ms timeout.
    assert replay(7, probability=0.9)["commit_sample_clocks_s"] == []
    assert replay(8, probability=0.9)["commit_sample_clocks_s"] == [0.27]

    # A low-confidence opportunity uses the 2.5 s timeout, not the short one.
    assert replay(84, probability=0.1)["commit_sample_clocks_s"] == []
    assert replay(85, probability=0.1)["commit_sample_clocks_s"] == [2.58]

    # Decisions use full precision rather than the rounded presentation value.
    assert replay(8, probability=0.499999999)["commit_sample_clocks_s"] == []
    assert replay(8, probability=0.500000001)["commit_sample_clocks_s"] == [0.27]

    # A missing eventual commit fails closed for a complete case.
    missing = runner.assess_replay(
        name="synthetic",
        kind="complete",
        phase_offset_samples=0,
        ground_truth_end_s=0.03,
        replay={
            "commit_sample_clocks_s": [],
            "opportunities": [],
            "provisional_trigger_sample_clocks_s": [],
            "provisional_pre_commit_cancellation_count": 0,
            "provisional_commit_before_resume_contradiction_count": 0,
            "provisional_survived_to_commit_count": 0,
            "observed_until_s": 3.0,
            "speech_frame_count": 1,
        },
    )
    assert not missing["endpoint_measurement_valid"]
    assert "expected_exactly_one_eventual_commit" in missing["endpoint_invalid_reasons"]

    # A provisional ack survives a pause only until speech resumes.
    frame = np.zeros(runner.INPUT_FRAME, dtype=np.int16)
    provisional = runner.replay_policy(
        frames=[frame.copy() for _ in range(10)],
        flags=[True, *([False] * 8), True],
        probability=lambda _tail: 0.9,
        confidence_threshold=0.5,
        complete_silence_s=0.85,
    )
    assert len(provisional["provisional_trigger_sample_clocks_s"]) == 1
    assert provisional["provisional_pre_commit_cancellation_count"] == 1
    assert provisional["provisional_commit_before_resume_contradiction_count"] == 0
    assert provisional["commit_sample_clocks_s"] == []

    # A short-timeout acknowledgement that commits before speech resumes is
    # not a cancellation: it is a committed-then-contradicted acknowledgement.
    contradicted = runner.replay_policy(
        frames=[frame.copy() for _ in range(10)],
        flags=[True, *([False] * 8), True],
        probability=lambda _tail: 0.9,
        confidence_threshold=0.5,
        complete_silence_s=0.2,
    )
    assert contradicted["provisional_pre_commit_cancellation_count"] == 0
    assert contradicted["provisional_commit_before_resume_contradiction_count"] == 1
    assert contradicted["commit_sample_clocks_s"] == [0.27]

    # The inherited manifest check must reject a changed pin.
    with tempfile.TemporaryDirectory(prefix="parcel-endpoint-selfcheck-") as directory:
        manifest_path = Path(directory) / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "locked_files": [
                        {
                            "path": str(runner.CORPUS.relative_to(runner.ROOT)),
                            "sha256": "0" * 64,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        try:
            runner.acoustic_eval.verify_manifest(manifest_path)
        except runner.acoustic_eval.EvalError:
            pass
        else:
            raise AssertionError("tampered manifest was accepted")

    print("endpoint-policy selfcheck: all deterministic assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
