"""C-1 re-dispatch seeded-defect harness.

Each seed is a REAL source edit that breaks one property this card claims, and
each is paired with the named test that must go RED for it. A seed that stays
green is a property nobody is actually checking.

Per the register's protocol: ``__pycache__`` is purged per restore, every
restore is verified by SHA against the pre-seed bytes, a fresh interpreter runs
each cell, and the file list is swept for strays at the end.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PY = REPO / ".parcel" / "bin" / "python"
RUNTIME = REPO / "src" / "parcel_robot" / "runtime.py"
INGRESS = REPO / "src" / "parcel_robot" / "camera_channel" / "ingress.py"
PYCACHE_PREFIX = "/tmp/parcel-c1-rerun-mutations"

#: Per-cell ceiling. A seeded defect that hangs is RED by timeout.
TEST_TIMEOUT_S = 240


@dataclass(frozen=True)
class Seed:
    name: str
    path: Path
    old: str
    new: str
    test: str
    breaks: str


SEEDS: tuple[Seed, ...] = (
    Seed(
        "explicit_false_silently_enables",
        RUNTIME,
        "self._camera_stream_enabled = bool(\n"
        "            self._camera_stream_config is not None"
        " and self._camera_stream_config.enabled\n        )",
        "self._camera_stream_enabled = bool(self._camera_stream_config is not None)",
        "tests/test_c1_camera_stream.py::test_flag_off_snapshot_has_no_camera_key_and_is_byte_identical",
        "flag-off is no longer byte-identical: an explicit false turns the eye on",
    ),
    Seed(
        "queue_eviction_uncounted",
        RUNTIME,
        "self._camera_frames_dropped += 1\n"
        "                self._camera_detections_dropped += len(evicted.detections)",
        "pass",
        "tests/test_c1_camera_stream.py::test_queue_keeps_newest_and_counts_every_lost_frame_and_detection",
        "the queue forgets silently; a full queue and a blind camera render alike",
    ),
    Seed(
        "freshness_measured_from_the_answer",
        INGRESS,
        "return self.published_monotonic_ns - self.capture_started_monotonic_ns",
        "return self.published_monotonic_ns - self.capture_completed_monotonic_ns",
        "tests/test_c1_camera_stream.py::test_frame_freshness_is_measured_from_capture_start",
        "a half-second-old detection reports itself as current",
    ),
    Seed(
        "truncated_rows_not_reconciled",
        INGRESS,
        "if len(detections) + self.truncated_detections != self.localized_detections:",
        "if False:",
        "tests/test_c1_camera_stream.py::test_a_frame_that_loses_rows_without_counting_them_is_refused",
        "a frame may drop detections without counting them",
    ),
    Seed(
        "stale_pose_is_rendered",
        RUNTIME,
        "if not -0.05 <= now - stamped <= self.telemetry_stale_s:\n"
        "                return None",
        "if False:\n                return None",
        "tests/test_c1_camera_stream.py::test_a_stale_pose_is_refused_rather_than_rendered",
        "a stalled simulator keeps producing confident frames of a world it cannot see",
    ),
    Seed(
        "worker_reuses_a_missing_pose",
        INGRESS,
        "            with self._lock:\n"
        "                self._pose = None\n"
        "            return False",
        "            return False",
        "tests/test_c1_camera_stream.py::test_the_worker_pulls_and_does_not_reuse_a_missing_pose",
        "the last good pose is re-rendered forever after telemetry stops",
    ),
    Seed(
        "inference_takes_no_pg1_lease",
        INGRESS,
        'lease_ctx = getattr(guard, "mission_lease", None) if guard is not None else None',
        "lease_ctx = None",
        "tests/test_c1_camera_stream.py::test_inference_runs_under_a_pg1_mission_lease",
        "camera inference no longer registers with PG-1's admission mechanism",
    ),
    Seed(
        "publish_runs_inside_the_producer_lock",
        INGRESS,
        "        if frame is not None:\n            self._publish_frame(frame)\n        return candidates",
        "        if frame is not None:\n"
        "            with self._lock:\n"
        "                self._publish_frame(frame)\n"
        "        return candidates",
        "tests/test_c1_camera_stream.py::test_the_publish_callback_is_invoked_outside_the_ingress_lock",
        "a lock-order edge from the producer's lock into the runtime's",
    ),
    Seed(
        "two_camera_authorities_coexist",
        RUNTIME,
        "            raise ValueError(\n"
        '                "perception.camera_ingress (C-1 observation stream) and the legacy "',
        "            pass\n        if False:\n"
        '            raise ValueError(\n                "unreachable "',
        "tests/test_c1_camera_stream.py::test_c1_and_the_legacy_b4_authority_flag_cannot_both_be_on",
        "the observation stream and the navigation-authority flag silently coexist",
    ),
    Seed(
        "evidence_rows_silently_skipped",
        RUNTIME,
        "        if self._session_evidence is None:\n            return\n        try:\n"
        "            row = frame.as_dict()",
        "        if self._session_evidence is None:\n            return\n        if True:\n"
        "            return\n        try:\n            row = frame.as_dict()",
        "tests/test_c1_camera_stream.py::test_frames_persist_into_ev1_as_typed_rows",
        "perception never reaches the evidence log; the stream is unauditable",
    ),
    Seed(
        "non_frame_payload_accepted",
        RUNTIME,
        "if not isinstance(frame, CameraDetectionFrame):",
        "if False:",
        "tests/test_c1_camera_stream.py::test_a_non_frame_payload_is_refused_and_faults_the_stream",
        "untyped junk enters the stream and the evidence log",
    ),
    Seed(
        "empty_frames_invent_a_detection_age",
        RUNTIME,
        "        newest_with_detections = None\n"
        "        for candidate in reversed(frames):\n"
        "            if candidate.detections:\n"
        "                newest_with_detections = candidate\n"
        "                break",
        "        newest_with_detections = newest",
        "tests/test_c1_camera_stream.py::test_empty_observations_are_real_observations",
        "an empty observation fabricates a last-detection age it does not have",
    ),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge_pycache() -> None:
    for target in REPO.joinpath("src").rglob("__pycache__"):
        shutil.rmtree(target, ignore_errors=True)
    for target in REPO.joinpath("tests").rglob("__pycache__"):
        shutil.rmtree(target, ignore_errors=True)
    shutil.rmtree(PYCACHE_PREFIX, ignore_errors=True)


def run_test(test_id: str, tag: str) -> tuple[bool, str]:
    """Fresh interpreter, no cache, dedicated pycache prefix."""

    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": f"{PYCACHE_PREFIX}-{tag}",
    }
    try:
        proc = subprocess.run(
            [str(PY), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *test_id.split()],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            env=env,
            timeout=TEST_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # A HANG is a failure, not an inconclusive result. Seed 8 (publishing
        # inside the producer's lock) self-deadlocks a non-reentrant Lock, so
        # the cell never returns — which is a louder RED than a failing assert,
        # and must be recorded as RED rather than crashing the harness and
        # leaving the mutant in the tree. (It did exactly that on the first
        # run; the restore now lives in a finally block.)
        return False, f"TIMEOUT after {TEST_TIMEOUT_S}s (deadlock)"
    tail = (proc.stdout or "").strip().splitlines()
    return proc.returncode == 0, tail[-1] if tail else ""


def main() -> None:
    results = []
    purge_pycache()

    # Canary: a fresh interpreter on the clean tree must be GREEN before any
    # seed runs, or a RED below proves nothing.
    canary_ok, canary_line = run_test(
        "tests/test_c1_camera_stream.py", "canary-pre"
    )
    if not canary_ok:
        raise SystemExit(f"pre-seed canary is not green: {canary_line}")

    for index, seed in enumerate(SEEDS, start=1):
        original = seed.path.read_text(encoding="utf-8")
        clean_sha = sha(seed.path)
        if seed.old not in original:
            raise SystemExit(f"seed {seed.name}: anchor text not found in {seed.path}")
        if original.count(seed.old) != 1:
            raise SystemExit(f"seed {seed.name}: anchor is not unique in {seed.path}")

        purge_pycache()
        # The restore lives in `finally`: on the first run a deadlocking seed
        # raised out of the RED cell and left its mutation in the tree. A
        # harness that can leave uncertified bytes behind on an exception is
        # the exact failure this register keeps relearning.
        try:
            seed.path.write_text(
                original.replace(seed.old, seed.new, 1), encoding="utf-8"
            )
            mutant_sha = sha(seed.path)
            red_ok, red_line = run_test(seed.test, f"seed{index}-red")
        finally:
            seed.path.write_text(original, encoding="utf-8")
        purge_pycache()
        restored_sha = sha(seed.path)
        green_ok, green_line = run_test(seed.test, f"seed{index}-green")

        results.append(
            {
                "seed": seed.name,
                "file": str(seed.path.relative_to(REPO)),
                "breaks": seed.breaks,
                "test": seed.test,
                "clean_sha256": clean_sha,
                "mutant_sha256": mutant_sha,
                "restored_sha256": restored_sha,
                "byte_restored": restored_sha == clean_sha,
                "went_red": not red_ok,
                "red_by": "timeout_deadlock" if "TIMEOUT" in red_line else "assertion",
                "red_line": red_line,
                "green_after_restore": green_ok,
                "green_line": green_line,
            }
        )
        status = "RED" if not red_ok else "!!! STAYED GREEN !!!"
        print(f"[{index:2d}/{len(SEEDS)}] {seed.name}: {status} | restored={restored_sha == clean_sha}")

    # Final sweep, run AFTER the last source write so it cannot be a stale pass.
    purge_pycache()
    sweep_ok, sweep_line = run_test(
        "tests/test_c1_camera_stream.py tests/test_runtime_activation.py "
        "tests/test_r24_lock_discipline.py tests/test_web_panel.py",
        "final-sweep",
    )
    strays = sorted(
        p.name
        for p in REPO.iterdir()
        if p.is_file() and p.suffix in {".orig", ".rej", ".bak", ".patch"}
    )
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "seeds_total": len(SEEDS),
        "seeds_red": sum(1 for r in results if r["went_red"]),
        "seeds_byte_restored": sum(1 for r in results if r["byte_restored"]),
        "seeds_green_after_restore": sum(1 for r in results if r["green_after_restore"]),
        "pre_seed_canary": canary_line,
        "final_sweep_green": sweep_ok,
        "final_sweep_line": sweep_line,
        "repo_root_strays": strays,
        "results": results,
    }
    out = Path(__file__).parent / "c1_rerun_mutation_results.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"\n{payload['seeds_red']}/{len(SEEDS)} RED · "
        f"{payload['seeds_byte_restored']}/{len(SEEDS)} byte-restored · "
        f"{payload['seeds_green_after_restore']}/{len(SEEDS)} green after restore"
    )
    print(f"final sweep: {sweep_line}")
    print(f"repo-root strays: {strays or 'none'}")
    print(f"wrote {out}")
    if payload["seeds_red"] != len(SEEDS) or payload["seeds_byte_restored"] != len(SEEDS):
        sys.exit(1)


if __name__ == "__main__":
    main()
