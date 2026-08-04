from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from evals.external.analyze_barn_v9_training_run import (
    TRAINING_EVALUATION_KIND,
    V8_REFERENCE_PACKAGE_SHA256,
    V9RunAnalysisError,
    analyze_training_run,
    write_analysis_exclusive,
)
from evals.external.barn_native import BarnAction, BarnObservation, BarnWorld
from evals.external.barn_sensor_faithful import (
    CalibratedBarnConfig,
    SensorFaithfulBarnRunner,
    V8EpisodeEvidenceCaptureSpec,
)
from evals.external.barn_v9_step_trace import run_sensor_faithful_with_v9_step_trace


@dataclass
class _ConstantPolicy:
    action: BarnAction

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        del start_xy, heading_rad, goal_xy

    def act(self, observation: BarnObservation) -> BarnAction:
        del observation
        return self.action

    def close(self) -> None:
        return None


def _world() -> BarnWorld:
    return BarnWorld(
        world_index=5000,
        cylinders=(),
        reference_path_grid=((15.0, 0.0), (15.0, 29.0)),
        reference_path_world=((-2.25, 5.075), (-2.25, 9.425)),
        optimal_path_length_m=10.0,
    )


def _write_run(tmp_path: Path, *, last_action_note: str = "ignored") -> Path:
    run_root = tmp_path / "run"
    evidence_root = run_root / "action-evidence"
    evidence_root.mkdir(parents=True)
    config = CalibratedBarnConfig(timeout_s=0.2, startup_timeout_s=0.4)
    episodes: dict[str, dict[str, object]] = {}
    for order, (arm, action) in enumerate(
        (
            ("reference", BarnAction(0.0, 0.3, note="arbitrary-reference-label")),
            ("candidate", BarnAction(0.5, 0.0, note="arbitrary-candidate-label")),
        )
    ):
        capture = V8EpisodeEvidenceCaptureSpec(
            arm=arm,
            execution_order=order,
            world_id=5000,
            trial_id=0,
            seed=20260803,
        )
        traced = run_sensor_faithful_with_v9_step_trace(
            SensorFaithfulBarnRunner(_world(), config),
            _ConstantPolicy(action),
            evidence_capture=capture,
        )
        assert traced.action_evidence is not None
        evidence_path = evidence_root / f"world-5000-trial-0-{arm}.v8ae"
        written = traced.action_evidence.write_exclusive(evidence_path)
        result = traced.result
        episodes[arm] = {
            "world_index": 5000,
            "trial": 0,
            "episode_seed": 20260803,
            "steps": result.steps,
            "final_position_xy": list(result.final_position_xy),
            "success": result.success,
            "collided": result.collided,
            "timed_out": result.timed_out,
            "trial_started": result.trial_started,
            "last_action_note": last_action_note,
            "action_evidence": {"identity": written.identity.as_dict()},
            "v9_step_trace": traced.step_trace.as_dict(),
            "v9_step_trace_sha256": traced.step_trace.sha256,
        }

    report = {
        "schema_version": 1,
        "run_id": "synthetic-v9-training-run",
        "evaluation_kind": TRAINING_EVALUATION_KIND,
        "official_score": False,
        "leaderboard": False,
        "promotion_evidence": False,
        "official_gazebo_score": False,
        "leaderboard_claim": False,
        "promotion_evidence_eligible": False,
        "policy_pair": {
            "reference_package_sha256": V8_REFERENCE_PACKAGE_SHA256,
            "candidate_package_sha256": "1" * 64,
            "deployment_enabled": False,
        },
        "paired_report": {
            "baseline": {"episodes": [episodes["reference"]]},
            "candidate": {"episodes": [episodes["candidate"]]},
        },
    }
    report_path = run_root / "report.json"
    report_path.write_text(
        json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.chmod(0o444)
    return report_path


def test_analyzer_reverifies_joined_evidence_and_ignores_policy_note_labels(
    tmp_path: Path,
) -> None:
    report_path = _write_run(tmp_path, last_action_note="navigation_no_progress")
    analysis = analyze_training_run(report_path)

    assert analysis["summary"]["pair_count"] == 1
    assert analysis["claims"] == {
        "official_score": False,
        "leaderboard": False,
        "promotion_evidence": False,
        "deployment_enabled": False,
        "training_worlds_are_rerunnable": True,
    }
    evidence = analysis["evidence_contract"]
    assert evidence["all_action_artifacts_fully_read_chain_checked_and_recertified"] is True
    assert evidence["all_post_integration_trace_hashes_recomputed"] is True
    assert evidence["policy_notes_used_for_failure_classification"] is False
    assert evidence["navigation_no_progress_latch_available"] is False
    assert analysis["failure_taxonomy"]["reference_navigation_no_progress_latch_count"] == 0
    assert analysis["failure_taxonomy"]["candidate_navigation_no_progress_latch_count"] == 0
    assert analysis["episode_dynamics"]["candidate"][0]["moving_translation_action_count"] > 0


def test_analyzer_rejects_trace_digest_mutation_before_using_actions(tmp_path: Path) -> None:
    original = _write_run(tmp_path)
    document = json.loads(original.read_text(encoding="utf-8"))
    document["paired_report"]["candidate"]["episodes"][0]["v9_step_trace_sha256"] = "0" * 64
    mutated = original.parent / "mutated.json"
    mutated.write_text(json.dumps(document), encoding="utf-8")
    mutated.chmod(0o444)

    with pytest.raises(V9RunAnalysisError, match="trace SHA-256"):
        analyze_training_run(mutated)


def test_analysis_write_is_immutable_and_never_replaces(tmp_path: Path) -> None:
    target = tmp_path / "analysis.json"
    written = write_analysis_exclusive(target, {"schema_version": 1, "value": 2})

    assert written == target.resolve()
    assert written.stat().st_mode & 0o222 == 0
    assert json.loads(written.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "value": 2,
    }
    with pytest.raises(FileExistsError, match="refusing to replace"):
        write_analysis_exclusive(target, {"schema_version": 1, "value": 3})
