from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _external_roots import skip_unless

from evals.external import run_barn_v9_supervisory_gap_s4_training as runner
from evals.external import run_sampled_predictive_tracker_v9_training as shared
from evals.external.barn_v9_supervisory_gap_s4 import (
    CANDIDATE_MANIFEST_SHA256,
    CANDIDATE_PACKAGE_SHA256,
    SCRATCH_FREEZE_SHA256,
)


@skip_unless("barn-generator-checkout")
def test_real_preflight_authenticates_s4_bundle_corpus_and_isolated_pair() -> None:
    preflight = runner._preflight_training_inputs()

    assert preflight.corpus_verification["world_count"] == 100
    assert preflight.corpus_verification["promotion_evidence_eligible"] is False
    assert preflight.isolated_pair["candidate"]["package_sha256"] == (
        CANDIDATE_PACKAGE_SHA256
    )
    assert preflight.isolated_pair["candidate"]["manifest_sha256"] == (
        CANDIDATE_MANIFEST_SHA256
    )
    assert preflight.isolated_pair["reference"]["package_sha256"] == (
        shared.V8_REFERENCE_PACKAGE_SHA256
    )
    assert preflight.one_factor_delta["one_factor_tracker_subsystem_delta"] is True
    assert preflight.one_factor_delta["all_ray_safety_shield_changed"] is False
    assert preflight.one_factor_delta["deployment_enabled"] is False


def test_wrapper_passes_frozen_identity_to_shared_training_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_shared(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"run_id": kwargs["run_id"]}

    monkeypatch.setattr(shared, "run_training_screen_for_candidate", fake_shared)
    result = runner.run_training_screen(
        run_id="s4-test",
        workers=4,
        results_root=tmp_path,
    )

    assert result == {"run_id": "s4-test"}
    identity = captured["candidate_identity"]
    assert identity.package_sha256 == CANDIDATE_PACKAGE_SHA256
    assert identity.manifest_sha256 == CANDIDATE_MANIFEST_SHA256
    assert identity.freeze_sha256 == SCRATCH_FREEZE_SHA256
    assert captured["world_count"] == 10
    assert captured["workers"] == 4
    assert captured["results_root"] == tmp_path
    assert captured["preflight_factory"] is runner._preflight_training_inputs


def test_s4_has_no_100_world_development_holdout_or_path_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        shared,
        "run_training_screen_for_candidate",
        lambda **_kwargs: pytest.fail("invalid scope must fail before shared runner"),
    )
    with pytest.raises(shared.V9TrainingRunnerError, match="exactly 10"):
        runner.run_training_screen(world_count=100)
    with pytest.raises(SystemExit):
        runner.main(["--world-count", "100"])
    with pytest.raises(SystemExit):
        runner.main(["--world-id", "5100"])
    with pytest.raises(SystemExit):
        runner.main(["--candidate-root", "/tmp/other"])


def test_candidate_identity_metadata_is_explicitly_nonpromotional() -> None:
    metadata = runner.CANDIDATE_IDENTITY.report_metadata()

    assert metadata["candidate_package_sha256"] == CANDIDATE_PACKAGE_SHA256
    assert metadata["candidate_experimental"] is True
    assert metadata["deployment_enabled"] is False
    assert metadata["candidate_freeze"] == {
        "path": str(runner.CANDIDATE_IDENTITY.freeze_path),
        "sha256": SCRATCH_FREEZE_SHA256,
        "training_only": True,
        "promotion_evidence": False,
        "development_execution_authorized": False,
        "holdout_execution_authorized": False,
        "deployment_enabled": False,
    }


