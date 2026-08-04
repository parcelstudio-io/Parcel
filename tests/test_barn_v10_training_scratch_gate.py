from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.external import barn_v10_training_scratch_gate as gate
from evals.external.barn_v10_planner_profile import (
    CANDIDATE_FREEZE_PATH,
    CANDIDATE_FREEZE_SHA256,
    CANDIDATE_MANIFEST_SHA256,
    CANDIDATE_PACKAGE_SHA256,
    PROFILE_SHA256,
    REFERENCE_MANIFEST_SHA256,
    REFERENCE_PACKAGE_SHA256,
    REFERENCE_PROFILE_SHA256,
    TRAINING_WORLD_IDS,
    V10_GATE_ID,
)
from evals.external.barn_v10_planner_profile_candidate import PROFILE_DESTINATION


def _generic_result(*, passed: bool = True) -> dict[str, Any]:
    return {
        "gate_id": V10_GATE_ID,
        "gate_sha256": gate.V10_GATE_DECLARATION_SHA256,
        "screen_world_ids": list(TRAINING_WORLD_IDS),
        "check_count": gate.EXPECTED_CHECK_COUNT,
        "gate_passed": passed,
        "failed_check_ids": [] if passed else ["minimum_success_count"],
        "policy_pair": {
            "reference_package_sha256": REFERENCE_PACKAGE_SHA256,
            "candidate_package_sha256": CANDIDATE_PACKAGE_SHA256,
        },
        "policy_bindings": {
            "reference_package_sha256": REFERENCE_PACKAGE_SHA256,
            "candidate_package_sha256": CANDIDATE_PACKAGE_SHA256,
            "reference_manifest_sha256": REFERENCE_MANIFEST_SHA256,
            "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
            "candidate_experiment_id": gate.EXPECTED_EXPERIMENT_ID,
            "candidate_freeze_path": str(CANDIDATE_FREEZE_PATH.resolve()),
            "candidate_freeze_sha256": CANDIDATE_FREEZE_SHA256,
            "manifest_bindings_available": True,
            "isolated_pair_binding_available": True,
            "executed_policy_provenance_available": True,
            "planner_profile_factor_available": True,
            "planner_profile_authorization_available": True,
            "reference_model_artifact_sha256": REFERENCE_PROFILE_SHA256,
            "candidate_model_artifact_sha256": PROFILE_SHA256,
            "active_model_relative_path": PROFILE_DESTINATION,
            "all_available_bindings_verified": True,
        },
        "evidence_contract": {"analysis_policy_bindings_match_report": True},
    }


def _patch_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    verified = SimpleNamespace(
        freeze={"scratch_screen": {"gate_id": V10_GATE_ID}},
        freeze_path=CANDIDATE_FREEZE_PATH.resolve(),
        freeze_sha256=CANDIDATE_FREEZE_SHA256,
    )
    monkeypatch.setattr(gate, "verify_v10_planner_profile", lambda: verified)

    def fake_gate(*args: object, **kwargs: object) -> dict[str, Any]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _generic_result() if result is None else result

    monkeypatch.setattr(gate, "evaluate_training_scratch_gate", fake_gate)
    return captured


def test_v10_wrapper_binds_freeze_profile_and_full_decision_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_evaluation(monkeypatch)

    decision = gate.evaluate_v10_training_scratch_gate(
        Path("/immutable/report.json"),
        Path("/immutable/analysis.json"),
        expected_report_sha256="1" * 64,
        expected_analysis_sha256="2" * 64,
    )

    unhashed = dict(decision)
    decision_sha = unhashed.pop("decision_sha256")
    canonical = json.dumps(
        unhashed,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    assert decision_sha == hashlib.sha256(canonical).hexdigest()
    assert decision["claims"]["accepted_for_next_training_stage"] is True
    assert decision["protocol_note"].startswith("V10 candidate evaluated under unchanged V9")
    assert captured["kwargs"]["gate"] == {"gate_id": V10_GATE_ID}
    assert captured["kwargs"]["expected_report_sha256"] == "1" * 64


def test_v10_wrapper_rejects_missing_executed_or_analysis_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _generic_result()
    result["policy_bindings"]["executed_policy_provenance_available"] = False
    _patch_evaluation(monkeypatch, result=result)

    with pytest.raises(gate.V10TrainingGateError, match="exact executed V8/V10"):
        gate.evaluate_v10_training_scratch_gate(
            "/report.json",
            "/analysis.json",
            expected_report_sha256="1" * 64,
            expected_analysis_sha256="2" * 64,
        )


def test_decision_writer_is_immutable_unaliased_and_no_clobber(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_evaluation(monkeypatch)
    decision = gate.evaluate_v10_training_scratch_gate(
        "/report.json",
        "/analysis.json",
        expected_report_sha256="1" * 64,
        expected_analysis_sha256="2" * 64,
    )
    output = tmp_path / "analysis" / gate.DEFAULT_DECISION_NAME

    written = gate.write_v10_gate_decision_exclusive(output, decision)

    metadata = os.lstat(output)
    assert written.path == output.resolve()
    assert written.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert written.size_bytes == output.stat().st_size
    assert stat.S_ISREG(metadata.st_mode)
    assert metadata.st_nlink == 1
    assert metadata.st_mode & 0o222 == 0
    with pytest.raises(FileExistsError, match="refusing to replace"):
        gate.write_v10_gate_decision_exclusive(output, decision)


def test_cli_persists_failed_decision_before_returning_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _generic_result(passed=False)
    _patch_evaluation(monkeypatch, result=result)
    output = tmp_path / "failed-decision.json"

    status = gate.main(
        [
            "/report.json",
            "/analysis.json",
            "--expected-report-sha256",
            "1" * 64,
            "--expected-analysis-sha256",
            "2" * 64,
            "--output",
            str(output),
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert status == 2
    assert output.is_file()
    assert output.stat().st_mode & 0o222 == 0
    assert summary["gate_passed"] is False
    assert summary["failed_check_ids"] == ["minimum_success_count"]
