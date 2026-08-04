from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.external import barn_v9_supervisory_gap_s2 as challenger
from evals.external.barn_policy_sidecar import verify_policy_bundle


def test_exact_scratch_freeze_and_one_factor_plan_verify() -> None:
    verified = challenger.verify_supervisory_gap_s2()

    assert verified.freeze_sha256 == challenger.SCRATCH_FREEZE_SHA256
    assert verified.plan.package_sha256 == challenger.CANDIDATE_PACKAGE_SHA256
    assert verified.plan.manifest_sha256 == challenger.CANDIDATE_MANIFEST_SHA256
    assert verified.plan.source_contract.contract_sha256 == challenger.SOURCE_CONTRACT_SHA256
    assert verified.plan.delta["one_factor_tracker_subsystem_delta"] is True
    assert verified.plan.delta["all_other_file_bytes_identical_to_reference"] is True
    assert verified.plan.delta["all_ray_safety_shield_changed"] is False
    assert verified.plan.delta["adapter_or_evaluator_source_changed"] is False
    assert verified.plan.delta["deployment_enabled"] is False
    assert verified.freeze["scratch_screen"]["training_only"] is True
    assert verified.freeze["scratch_incumbent"] == {
        "analysis_sha256": challenger.S1_ANALYSIS_SHA256,
        "manifest_sha256": challenger.S1_MANIFEST_SHA256,
        "package_sha256": challenger.S1_PACKAGE_SHA256,
        "report_sha256": challenger.S1_REPORT_SHA256,
    }
    assert verified.freeze["development_execution_authorized"] is False
    assert verified.freeze["holdout_execution_authorized"] is False


def test_raw_freeze_mutation_is_rejected(tmp_path: Path) -> None:
    changed = tmp_path / "changed.json"
    changed.write_bytes(challenger.SCRATCH_FREEZE_PATH.read_bytes() + b" ")

    with pytest.raises(challenger.SupervisoryGapS2Error, match="raw identity changed"):
        challenger.verify_supervisory_gap_s2(freeze_path=changed)


def test_source_mutation_is_rejected_after_freeze() -> None:
    tracker = challenger.EXPERIMENT_ROOT / "experimental_sampled_predictive_tracker.py"
    original = tracker.read_bytes()
    try:
        tracker.write_bytes(original + b"\n")
        with pytest.raises(ValueError, match="tracker source bytes differ"):
            challenger.verify_supervisory_gap_s2()
    finally:
        tracker.write_bytes(original)

    assert challenger.verify_supervisory_gap_s2().freeze_sha256 == (
        challenger.SCRATCH_FREEZE_SHA256
    )


def test_materialized_scratch_bundle_is_read_only_and_exact(tmp_path: Path) -> None:
    prepared = challenger.prepare_supervisory_gap_s2_bundle(destination_root=tmp_path)
    verified = verify_policy_bundle(
        prepared.root,
        expected_package_sha256=challenger.CANDIDATE_PACKAGE_SHA256,
        expected_manifest_sha256=challenger.CANDIDATE_MANIFEST_SHA256,
    )

    assert verified.package_sha256 == challenger.CANDIDATE_PACKAGE_SHA256
    assert verified.manifest_sha256 == challenger.CANDIDATE_MANIFEST_SHA256
    assert prepared.delta["unchanged_file_count"] == 116
    assert all(path.stat().st_mode & 0o222 == 0 for path in prepared.root.rglob("*"))
    manifest = json.loads(verified.manifest_path.read_bytes())
    assert manifest["experiment_derivation"]["deployment_enabled"] is False
    assert manifest["experiment_derivation"]["all_ray_safety_shield_changed"] is False
