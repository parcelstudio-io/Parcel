from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.external import ledger as ledger_module
from evals.external import run_sampled_predictive_tracker_v9_training as runner
from evals.external.barn_policy_specs import IsolatedPlannerProfileAuthorization
from evals.external.barn_sensor_faithful import (
    CANDIDATE_THEN_REFERENCE,
    REFERENCE_THEN_CANDIDATE,
)
from evals.external.ledger import GitState, iter_ledger


def _policy_spec() -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="DirectiveNavigator",
        adapter_id="parcel-barn-adapter",
        implementation_sha256="a" * 64,
        config_id="bundle/config.yaml",
        config_sha256="b" * 64,
        model_id="grid_v1",
        model_artifact_sha256="c" * 64,
    )


def _preflight() -> runner.V9TrainingPreflight:
    return runner.V9TrainingPreflight(
        corpus_verification={
            "corpus_id": runner.CORPUS_ID,
            "corpus_sha256": runner.EXPECTED_TRAINING_CORPUS_SHA256,
            "manifest_sha256": runner.EXPECTED_TRAINING_MANIFEST_SHA256,
            "promotion_evidence_eligible": False,
            "world_count": 100,
        },
        reference_spec=_policy_spec(),  # type: ignore[arg-type]
        candidate_spec=_policy_spec(),  # type: ignore[arg-type]
        one_factor_delta={"one_factor_tracker_subsystem_delta": True},
        isolated_pair={"same_execution_environment": True},
    )


def _profile_authorization(
    *,
    candidate_package_sha256: str | None = None,
) -> IsolatedPlannerProfileAuthorization:
    identity = runner.INITIAL_CANDIDATE_IDENTITY
    return IsolatedPlannerProfileAuthorization(
        reference_package_sha256="1" * 64,
        reference_manifest_sha256="2" * 64,
        candidate_package_sha256=(
            identity.package_sha256
            if candidate_package_sha256 is None
            else candidate_package_sha256
        ),
        candidate_manifest_sha256=identity.manifest_sha256,
        reference_model_artifact_sha256="3" * 64,
        candidate_model_artifact_sha256="4" * 64,
        navigation_config_sha256="5" * 64,
        model_id="grid_v1",
        reference_policy_id="synthetic-reference",
        candidate_policy_id=identity.experiment_id,
    )


def _paired_report(
    reference_success: float = 0.4, candidate_success: float = 0.5
) -> dict[str, Any]:
    reference = {
        "success_rate": reference_success,
        "navigation_metric": 0.3,
        "collision_rate": 0.1,
        "timeout_rate": 0.5,
    }
    candidate = {
        "success_rate": candidate_success,
        "navigation_metric": 0.35,
        "collision_rate": 0.1,
        "timeout_rate": 0.4,
    }
    return {
        "official_gazebo_score": False,
        "baseline": {"aggregate": reference},
        "candidate": {"aggregate": candidate},
        "comparison": {
            "candidate_minus_baseline": {
                "success_rate": candidate_success - reference_success,
                "navigation_metric": 0.05,
            },
            "paired_outcomes": {
                "success_gains": 1,
                "success_regressions": 0,
            },
        },
    }


def test_training_prefix_and_candidate_first_schedule_are_exact() -> None:
    assert runner.training_world_ids(10) == tuple(range(5000, 5010))
    assert runner.training_world_ids(100) == tuple(range(5000, 5100))
    assert runner.candidate_first_alternating_schedule(4) == (
        CANDIDATE_THEN_REFERENCE,
        REFERENCE_THEN_CANDIDATE,
        CANDIDATE_THEN_REFERENCE,
        REFERENCE_THEN_CANDIDATE,
    )
    assert runner.SUITE_SEED == 20260803
    assert runner.TRIALS_PER_WORLD == 1
    assert runner.DEFAULT_WORKERS == 4


@pytest.mark.parametrize("forbidden_id", [4999, 5100, 5129, 5130, 5149])
def test_development_holdout_and_nontraining_ids_are_rejected(forbidden_id: int) -> None:
    with pytest.raises(runner.V9TrainingRunnerError, match="5000--5099"):
        runner.validate_training_world_ids((5000, forbidden_id))


def test_invalid_world_count_fails_before_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner,
        "_preflight_training_inputs",
        lambda: pytest.fail("preflight must not run for an invalid world count"),
    )
    with pytest.raises(runner.V9TrainingRunnerError, match="10 or 100"):
        runner.run_training_screen(world_count=30)


def test_profile_authorization_identity_mismatch_fails_before_evaluator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _profile_authorization(candidate_package_sha256="9" * 64)
    monkeypatch.setattr(
        runner,
        "run_sensor_faithful_paired_comparison_with_v9_traces",
        lambda **_kwargs: pytest.fail("identity mismatch must fail before evaluator"),
    )

    with pytest.raises(ValueError, match="reported candidate identity"):
        runner.run_training_screen_for_candidate(
            candidate_identity=runner.INITIAL_CANDIDATE_IDENTITY,
            preflight_factory=_preflight,
            world_count=10,
            workers=1,
            run_id="authorization-mismatch",
            results_root=tmp_path,
            isolated_planner_profile_authorization=authorization,
        )


def test_shared_runner_revalidates_and_propagates_profile_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _profile_authorization()
    preflight = _preflight()
    observed: dict[str, object] = {}

    def validate_identity(
        self: IsolatedPlannerProfileAuthorization,
        **kwargs: object,
    ) -> None:
        observed["identity"] = kwargs

    def validate_pair(
        self: IsolatedPlannerProfileAuthorization,
        reference: object,
        candidate: object,
    ) -> dict[str, object]:
        observed["pair"] = (reference, candidate)
        return dict(preflight.isolated_pair)

    def traced(**kwargs: object) -> dict[str, object]:
        observed["propagated"] = kwargs["isolated_planner_profile_authorization"]
        raise RuntimeError("stop before synthetic episode output")

    monkeypatch.setattr(
        IsolatedPlannerProfileAuthorization,
        "validate_candidate_report_identity",
        validate_identity,
    )
    monkeypatch.setattr(
        IsolatedPlannerProfileAuthorization,
        "validate_pair",
        validate_pair,
    )
    monkeypatch.setattr(
        runner,
        "run_sensor_faithful_paired_comparison_with_v9_traces",
        traced,
    )

    with pytest.raises(RuntimeError, match="stop before synthetic episode output"):
        runner.run_training_screen_for_candidate(
            candidate_identity=runner.INITIAL_CANDIDATE_IDENTITY,
            preflight_factory=lambda: preflight,
            world_count=10,
            workers=1,
            run_id="authorization-propagation",
            results_root=tmp_path,
            isolated_planner_profile_authorization=authorization,
        )

    assert observed["identity"] == {
        "package_sha256": runner.INITIAL_CANDIDATE_IDENTITY.package_sha256,
        "manifest_sha256": runner.INITIAL_CANDIDATE_IDENTITY.manifest_sha256,
        "experiment_id": runner.INITIAL_CANDIDATE_IDENTITY.experiment_id,
    }
    assert observed["pair"] == (preflight.reference_spec, preflight.candidate_spec)
    assert observed["propagated"] is authorization


def test_shared_runner_rejects_preflight_pair_metadata_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _profile_authorization()
    preflight = _preflight()
    monkeypatch.setattr(
        IsolatedPlannerProfileAuthorization,
        "validate_candidate_report_identity",
        lambda _self, **_kwargs: None,
    )
    monkeypatch.setattr(
        IsolatedPlannerProfileAuthorization,
        "validate_pair",
        lambda _self, _reference, _candidate: {"different": True},
    )
    monkeypatch.setattr(
        runner,
        "run_sensor_faithful_paired_comparison_with_v9_traces",
        lambda **_kwargs: pytest.fail("pair mismatch must fail before evaluator"),
    )

    with pytest.raises(runner.V9TrainingRunnerError, match="preflight isolated pair differs"):
        runner.run_training_screen_for_candidate(
            candidate_identity=runner.INITIAL_CANDIDATE_IDENTITY,
            preflight_factory=lambda: preflight,
            world_count=10,
            workers=1,
            run_id="authorization-pair-mismatch",
            results_root=tmp_path,
            isolated_planner_profile_authorization=authorization,
        )


def test_preflight_rejects_nonexact_training_identity_before_policy_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "verify_training_corpus",
        lambda _path: {
            "corpus_id": runner.CORPUS_ID,
            "corpus_sha256": "0" * 64,
            "manifest_sha256": runner.EXPECTED_TRAINING_MANIFEST_SHA256,
            "promotion_evidence_eligible": False,
            "world_count": 100,
        },
    )
    monkeypatch.setattr(
        runner,
        "plan_v9_candidate_bundle",
        lambda: pytest.fail("bundle work must not begin after a corpus mismatch"),
    )
    with pytest.raises(runner.V9TrainingRunnerError, match="manifest/corpus identity"):
        runner._preflight_training_inputs()


def test_preflight_rejects_any_candidate_identity_other_than_c68bb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verification = {
        "corpus_id": runner.CORPUS_ID,
        "corpus_sha256": runner.EXPECTED_TRAINING_CORPUS_SHA256,
        "manifest_sha256": runner.EXPECTED_TRAINING_MANIFEST_SHA256,
        "promotion_evidence_eligible": False,
        "world_count": 100,
    }
    bad_plan = SimpleNamespace(
        reference=SimpleNamespace(
            root=runner.DEFAULT_REFERENCE_ROOT.resolve(),
            package_sha256=runner.V8_REFERENCE_PACKAGE_SHA256,
            manifest_sha256=runner.V8_REFERENCE_MANIFEST_SHA256,
        ),
        package_sha256="0" * 64,
        manifest_sha256=runner.V9_CANDIDATE_MANIFEST_SHA256,
    )
    monkeypatch.setattr(runner, "verify_training_corpus", lambda _path: verification)
    monkeypatch.setattr(runner, "plan_v9_candidate_bundle", lambda: bad_plan)
    monkeypatch.setattr(
        runner,
        "verify_policy_bundle",
        lambda *_args, **_kwargs: pytest.fail("candidate verification must not accept wrong plan"),
    )
    with pytest.raises(runner.V9TrainingRunnerError, match="frozen policy pair"):
        runner._preflight_training_inputs()


def test_ten_world_screen_uses_fixed_traced_protocol_and_writes_immutable_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results_root = tmp_path / "training-results"
    monkeypatch.setattr(runner, "DEFAULT_RESULTS_ROOT", results_root)
    monkeypatch.setattr(runner, "_preflight_training_inputs", _preflight)
    monkeypatch.setattr(
        ledger_module,
        "detect_git_state",
        lambda _repository=ledger_module.REPOSITORY_ROOT: GitState(
            commit="parcel-test-commit",
            dirty=True,
        ),
    )
    captured: dict[str, Any] = {}

    def fake_traced_paired(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        for path in kwargs["action_evidence_paths"].values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic immutable v8 evidence\n")
            path.chmod(0o444)
        return _paired_report()

    monkeypatch.setattr(
        runner,
        "run_sensor_faithful_paired_comparison_with_v9_traces",
        fake_traced_paired,
    )

    summary = runner.run_training_screen(
        world_count=10,
        workers=4,
        run_id="scratch-screen-001",
        description="First deterministic V9 scratch screen.",
    )

    assert captured["world_indices"] == tuple(range(5000, 5010))
    assert captured["suite_seed"] == 20260803
    assert captured["trials"] == 1
    assert captured["workers"] == 4
    assert captured["allow_experimental"] is True
    assert captured["generated_corpus"] is True
    assert captured["asset_manifest_sha256"] == runner.EXPECTED_TRAINING_MANIFEST_SHA256
    assert captured["arm_order_schedule"][0] == CANDIDATE_THEN_REFERENCE
    assert captured["arm_order_schedule"] == runner.candidate_first_alternating_schedule(10)
    assert set(captured["action_evidence_paths"]) == {
        (world_id, 0, arm) for world_id in range(5000, 5010) for arm in ("reference", "candidate")
    }

    report_path = Path(summary["report_path"])
    report = json.loads(report_path.read_bytes())
    assert not report_path.stat().st_mode & stat.S_IWUSR
    assert report["official_score"] is False
    assert report["leaderboard"] is False
    assert report["promotion_evidence"] is False
    assert report["corpus"]["world_ids"] == list(range(5000, 5010))
    assert report["policy_pair"]["reference_package_sha256"].startswith("189ac31f")
    assert report["policy_pair"]["reference_experimental"] is False
    assert report["policy_pair"]["candidate_package_sha256"].startswith("c68bb69c")
    assert len(list((report_path.parent / "action-evidence").glob("*.v8ae"))) == 20
    assert all(
        not path.stat().st_mode & stat.S_IWUSR
        for path in (report_path.parent / "action-evidence").glob("*.v8ae")
    )

    entries = list(iter_ledger(results_root / "ledger"))
    assert len(entries) == 1
    entry = entries[0]
    assert entry["run_id"] == "scratch-screen-001"
    assert entry["timestamp_utc"] == report["run_date_utc"]
    assert entry["change_description"] == "First deterministic V9 scratch screen."
    assert entry["aggregate_metrics"]["official_score"] is False
    assert entry["aggregate_metrics"]["leaderboard"] is False
    assert entry["aggregate_metrics"]["promotion_evidence"] is False
    assert entry["aggregate_metrics"]["candidate"]["success_rate"] == pytest.approx(0.5)
    assert not Path(summary["ledger_record_path"]).stat().st_mode & stat.S_IWUSR


def test_existing_run_namespace_is_never_overwritten_or_evaluated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "DEFAULT_RESULTS_ROOT", tmp_path / "results")
    run_root = runner.DEFAULT_RESULTS_ROOT / "runs" / "duplicate-run"
    run_root.mkdir(parents=True)
    marker = run_root / "user-data.txt"
    marker.write_text("preserve me", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_preflight_training_inputs",
        lambda: pytest.fail("preflight must not run for a consumed namespace"),
    )
    with pytest.raises(FileExistsError, match="refusing to replace"):
        runner.run_training_screen(run_id="duplicate-run")
    assert marker.read_text(encoding="utf-8") == "preserve me"


def test_immutable_evidence_check_rejects_a_writable_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "writable.v8ae"
    artifact.write_bytes(b"not immutable")
    with pytest.raises(runner.V9TrainingRunnerError, match="not immutable"):
        runner._verify_immutable_action_evidence({(5000, 0, "reference"): artifact})


def test_cli_exposes_no_world_id_manifest_asset_or_results_override() -> None:
    with pytest.raises(SystemExit):
        runner.main(["--world-count", "30"])
    with pytest.raises(SystemExit):
        runner.main(["--world-id", "5100"])
    with pytest.raises(SystemExit):
        runner.main(["--manifest", "/tmp/development.json"])
