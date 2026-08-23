from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from _external_roots import skip_unless

from evals.external import barn_v10_planner_profile as frozen
from evals.external import barn_v10_planner_profile_candidate as declaration


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@skip_unless("barn-policy-bundles")
def test_exact_freeze_authenticates_recomputed_one_file_plan_and_training_scope() -> None:
    verified = frozen.verify_v10_planner_profile()

    assert verified.freeze_sha256 == frozen.CANDIDATE_FREEZE_SHA256
    assert verified.plan.profile_sha256 == frozen.PROFILE_SHA256
    assert verified.plan.package_sha256 == frozen.CANDIDATE_PACKAGE_SHA256
    assert verified.plan.manifest_sha256 == frozen.CANDIDATE_MANIFEST_SHA256
    assert verified.plan.reference.package_sha256 == frozen.REFERENCE_PACKAGE_SHA256
    assert verified.plan.reference.manifest_sha256 == frozen.REFERENCE_MANIFEST_SHA256
    assert verified.plan.delta["replacements"] == [declaration.PROFILE_DESTINATION]
    assert verified.plan.delta["additions"] == []
    assert verified.plan.delta["one_factor_planner_profile_delta"] is True
    assert verified.freeze["frozen_before_materialization"] is True
    assert verified.freeze["training_execution_authorization"] == {
        "all_other_worlds_authorized": False,
        "rerunnable": True,
        "world_ids": list(range(5000, 5010)),
    }
    assert verified.freeze["development_execution_authorized"] is False
    assert verified.freeze["holdout_execution_authorized"] is False
    assert verified.freeze["deployment_enabled"] is False


def test_raw_freeze_mutation_is_rejected(tmp_path: Path) -> None:
    changed = tmp_path / "changed-freeze.json"
    changed.write_bytes(frozen.CANDIDATE_FREEZE_PATH.read_bytes() + b" ")

    with pytest.raises(frozen.V10PlannerProfileError, match="raw identity changed"):
        frozen.verify_v10_planner_profile(freeze_path=changed)


def test_gate_threshold_mutation_is_rejected_even_with_matching_raw_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = json.loads(frozen.CANDIDATE_FREEZE_PATH.read_bytes())
    document["scratch_screen"]["minimum_success_count"] = 1
    changed_raw = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    changed = tmp_path / "changed-gate-freeze.json"
    changed.write_bytes(changed_raw)
    monkeypatch.setattr(frozen, "CANDIDATE_FREEZE_SHA256", _sha256(changed_raw))

    with pytest.raises(frozen.V10PlannerProfileError, match="exact S4 gate"):
        frozen.verify_v10_planner_profile(freeze_path=changed)


@skip_unless("barn-policy-bundles")
def test_profile_source_mutation_is_rejected_after_freeze(tmp_path: Path) -> None:
    changed = tmp_path / "changed-grid.yaml"
    changed.write_bytes(declaration.PROFILE_SOURCE.read_bytes() + b"\n")

    with pytest.raises(frozen.V10PlannerProfileError, match="derivation differs"):
        frozen.verify_v10_planner_profile(profile_source_path=changed)


@skip_unless("barn-policy-bundles")
def test_s4_numeric_screen_is_exact_except_declared_identity_substitutions() -> None:
    candidate = frozen.verify_v10_planner_profile().freeze["scratch_screen"]
    s4 = json.loads(frozen.S4_FREEZE_PATH.read_bytes())["scratch_screen"]
    expected = copy.deepcopy(s4)
    expected["candidate_package_sha256"] = frozen.CANDIDATE_PACKAGE_SHA256
    expected["gate_id"] = frozen.V10_GATE_ID

    assert candidate == expected


@skip_unless("barn-policy-bundles")
def test_authenticated_wrapper_is_only_candidate_specific_materialization_entry_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not hasattr(declaration, "prepare_v10_planner_profile_candidate")
    verified = frozen.verify_v10_planner_profile()
    calls: list[dict[str, object]] = []
    stand_in = SimpleNamespace(delta=verified.plan.delta)

    def fake_prepare(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return stand_in

    monkeypatch.setattr(frozen, "prepare_planner_profile_candidate", fake_prepare)
    destination = tmp_path / "not-materialized-by-stand-in"

    result = frozen.prepare_v10_planner_profile_bundle(destination_root=destination)

    assert result is stand_in
    assert not destination.exists()
    assert len(calls) == 1
    assert calls[0]["expected_candidate_package_sha256"] == (
        frozen.CANDIDATE_PACKAGE_SHA256
    )
    assert calls[0]["expected_candidate_manifest_sha256"] == (
        frozen.CANDIDATE_MANIFEST_SHA256
    )
    assert calls[0]["expected_reference_package_sha256"] == (
        frozen.REFERENCE_PACKAGE_SHA256
    )
    assert calls[0]["expected_reference_manifest_sha256"] == (
        frozen.REFERENCE_MANIFEST_SHA256
    )
    assert calls[0]["destination_root"] == destination
