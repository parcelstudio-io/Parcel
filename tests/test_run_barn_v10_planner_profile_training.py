from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.external import run_barn_v10_planner_profile_training as runner
from evals.external import run_sampled_predictive_tracker_v9_training as shared
from evals.external.barn_v10_planner_profile import (
    CANDIDATE_FREEZE_SHA256,
    CANDIDATE_MANIFEST_SHA256,
    CANDIDATE_PACKAGE_SHA256,
    PROFILE_SHA256,
    REFERENCE_MANIFEST_SHA256,
    REFERENCE_PACKAGE_SHA256,
    REFERENCE_PROFILE_SHA256,
)


def _corpus_verification() -> dict[str, object]:
    return {
        "corpus_id": runner.CORPUS_ID,
        "corpus_sha256": shared.EXPECTED_TRAINING_CORPUS_SHA256,
        "manifest_sha256": shared.EXPECTED_TRAINING_MANIFEST_SHA256,
        "promotion_evidence_eligible": False,
        "world_count": len(runner.TRAINING_WORLD_IDS),
    }


def test_preflight_verifies_freeze_bundle_delta_and_isolated_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = SimpleNamespace(root=Path("/verified/reference"))
    frozen_delta = {
        "replacements": ["configs/navigation/models/grid.yaml"],
        "additions": [],
        "one_factor_planner_profile_delta": True,
        "deployment_enabled": False,
    }
    frozen = SimpleNamespace(plan=SimpleNamespace(reference=reference, delta=frozen_delta))
    candidate = SimpleNamespace(root=Path("/verified/candidate"))
    reference_spec = SimpleNamespace(name="reference-spec")
    candidate_spec = SimpleNamespace(name="candidate-spec")
    captured: dict[str, Any] = {}

    monkeypatch.setattr(runner, "verify_training_corpus", lambda _path: _corpus_verification())
    monkeypatch.setattr(runner, "verify_v10_planner_profile", lambda: frozen)

    def fake_verify_bundle(root: Path, **kwargs: Any) -> SimpleNamespace:
        captured["bundle_root"] = root
        captured["bundle_kwargs"] = kwargs
        return candidate

    def fake_verify_delta(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["delta_args"] = args
        captured["delta_kwargs"] = kwargs
        return frozen_delta

    def fake_reference_spec(root: Path, **kwargs: Any) -> SimpleNamespace:
        captured["reference_root"] = root
        captured["reference_kwargs"] = kwargs
        return reference_spec

    def fake_candidate_spec(root: Path, **kwargs: Any) -> SimpleNamespace:
        captured["candidate_root"] = root
        captured["candidate_kwargs"] = kwargs
        return candidate_spec

    def fake_pair(first: object, second: object) -> dict[str, object]:
        assert first is reference_spec
        assert second is candidate_spec
        return {"same_execution_environment": True, "isolated": True}

    monkeypatch.setattr(runner, "verify_policy_bundle", fake_verify_bundle)
    monkeypatch.setattr(runner, "verify_planner_profile_candidate_delta", fake_verify_delta)
    monkeypatch.setattr(runner, "parcel_isolated_bundle_reference_spec", fake_reference_spec)
    monkeypatch.setattr(runner, "parcel_isolated_bundle_candidate_spec", fake_candidate_spec)
    monkeypatch.setattr(
        runner,
        "PLANNER_PROFILE_AUTHORIZATION",
        SimpleNamespace(validate_pair=fake_pair),
    )

    preflight = runner._preflight_training_inputs()

    assert preflight.corpus_verification == _corpus_verification()
    assert preflight.reference_spec is reference_spec
    assert preflight.candidate_spec is candidate_spec
    assert preflight.one_factor_delta == frozen_delta
    assert preflight.isolated_pair == {
        "same_execution_environment": True,
        "isolated": True,
    }
    assert captured["bundle_root"] == runner.DEFAULT_CANDIDATE_ROOT
    assert captured["bundle_kwargs"] == {
        "expected_package_sha256": CANDIDATE_PACKAGE_SHA256,
        "expected_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
    }
    assert captured["delta_args"] == (candidate, reference)
    assert captured["delta_kwargs"]["expected_profile_sha256"] == PROFILE_SHA256
    assert captured["reference_root"] == reference.root
    assert captured["reference_kwargs"]["package_sha256"] == REFERENCE_PACKAGE_SHA256
    assert captured["reference_kwargs"]["manifest_sha256"] == REFERENCE_MANIFEST_SHA256
    assert captured["candidate_root"] == candidate.root
    assert captured["candidate_kwargs"]["package_sha256"] == CANDIDATE_PACKAGE_SHA256
    assert captured["candidate_kwargs"]["manifest_sha256"] == CANDIDATE_MANIFEST_SHA256
    assert captured["candidate_kwargs"]["reference_package_sha256"] == (
        REFERENCE_PACKAGE_SHA256
    )
    assert runner.CANDIDATE_IDENTITY.package_sha256 == CANDIDATE_PACKAGE_SHA256


def test_preflight_rejects_corpus_mismatch_before_bundle_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = _corpus_verification()
    changed["corpus_sha256"] = "0" * 64
    monkeypatch.setattr(runner, "verify_training_corpus", lambda _path: changed)
    monkeypatch.setattr(
        runner,
        "verify_v10_planner_profile",
        lambda: pytest.fail("freeze work must not start after corpus mismatch"),
    )

    with pytest.raises(shared.V9TrainingRunnerError, match="manifest/corpus identity"):
        runner._preflight_training_inputs()


def test_preflight_rejects_bundle_delta_mismatch_before_runtime_specs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = SimpleNamespace(
        plan=SimpleNamespace(
            reference=SimpleNamespace(root=Path("/verified/reference")),
            delta={"one_factor_planner_profile_delta": True},
        )
    )
    monkeypatch.setattr(runner, "verify_training_corpus", lambda _path: _corpus_verification())
    monkeypatch.setattr(runner, "verify_v10_planner_profile", lambda: frozen)
    monkeypatch.setattr(
        runner,
        "verify_policy_bundle",
        lambda *_args, **_kwargs: SimpleNamespace(root=Path("/verified/candidate")),
    )
    monkeypatch.setattr(
        runner,
        "verify_planner_profile_candidate_delta",
        lambda *_args, **_kwargs: {"one_factor_planner_profile_delta": False},
    )
    monkeypatch.setattr(
        runner,
        "parcel_isolated_bundle_reference_spec",
        lambda *_args, **_kwargs: pytest.fail("runtime spec must not follow delta mismatch"),
    )

    with pytest.raises(shared.V9TrainingRunnerError, match="differs from its frozen plan"):
        runner._preflight_training_inputs()


def test_wrapper_passes_only_frozen_ten_world_identity_to_shared_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_shared(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"run_id": kwargs["run_id"]}

    monkeypatch.setattr(shared, "run_training_screen_for_candidate", fake_shared)
    result = runner.run_training_screen(
        run_id="v10-profile-test",
        workers=3,
        results_root=tmp_path,
    )

    assert result == {"run_id": "v10-profile-test"}
    identity = captured["candidate_identity"]
    assert identity.package_sha256 == CANDIDATE_PACKAGE_SHA256
    assert identity.manifest_sha256 == CANDIDATE_MANIFEST_SHA256
    assert identity.freeze_sha256 == CANDIDATE_FREEZE_SHA256
    assert captured["world_count"] == 10
    assert captured["workers"] == 3
    assert captured["results_root"] == tmp_path
    assert captured["preflight_factory"] is runner._preflight_training_inputs
    assert captured["isolated_planner_profile_authorization"] is (
        runner.PLANNER_PROFILE_AUTHORIZATION
    )


@pytest.mark.parametrize("invalid_count", [False, 0, 1, 9, 11, 30, 100])
def test_runner_denies_every_non_ten_world_scope_before_shared_execution(
    invalid_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        shared,
        "run_training_screen_for_candidate",
        lambda **_kwargs: pytest.fail("invalid scope must fail before shared runner"),
    )

    with pytest.raises(shared.V9TrainingRunnerError, match="exactly 10"):
        runner.run_training_screen(world_count=invalid_count)


def test_cli_has_no_world_id_candidate_path_development_holdout_or_deployment_path() -> None:
    with pytest.raises(SystemExit):
        runner.main(["--world-count", "100"])
    with pytest.raises(SystemExit):
        runner.main(["--world-id", "5100"])
    with pytest.raises(SystemExit):
        runner.main(["--candidate-root", "/tmp/other"])
    with pytest.raises(SystemExit):
        runner.main(["--development"])
    with pytest.raises(SystemExit):
        runner.main(["--holdout"])
    with pytest.raises(SystemExit):
        runner.main(["--deployment"])


def test_candidate_identity_metadata_is_explicitly_nonpromotional() -> None:
    metadata = runner.CANDIDATE_IDENTITY.report_metadata()

    assert runner.DEFAULT_CANDIDATE_ROOT.name == (
        f"parcel-profile-candidate-{CANDIDATE_PACKAGE_SHA256}"
    )
    assert metadata["candidate_package_sha256"] == CANDIDATE_PACKAGE_SHA256
    assert metadata["candidate_experimental"] is True
    assert metadata["deployment_enabled"] is False
    assert metadata["candidate_freeze"] == {
        "path": str(runner.CANDIDATE_IDENTITY.freeze_path),
        "sha256": CANDIDATE_FREEZE_SHA256,
        "training_only": True,
        "promotion_evidence": False,
        "development_execution_authorized": False,
        "holdout_execution_authorized": False,
        "deployment_enabled": False,
    }
    authorization = runner.PLANNER_PROFILE_AUTHORIZATION
    assert authorization.reference_model_artifact_sha256 == REFERENCE_PROFILE_SHA256
    assert authorization.candidate_model_artifact_sha256 == PROFILE_SHA256
    assert authorization.candidate_package_sha256 == CANDIDATE_PACKAGE_SHA256
    assert authorization.candidate_manifest_sha256 == CANDIDATE_MANIFEST_SHA256
    assert authorization.candidate_policy_id == runner.CANDIDATE_IDENTITY.experiment_id
