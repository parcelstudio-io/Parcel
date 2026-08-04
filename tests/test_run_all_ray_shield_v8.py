from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import evals.external.run_all_ray_shield_v8 as runner
from evals.external.barn_v8_transaction import (
    V8EvaluationIdentity,
    V8TransactionConsumedError,
    V8TransactionState,
    inspect_v8_transaction,
    preflight_v8_transaction,
)
from evals.external.generate_all_ray_shield_v8_corpus import (
    CORPUS_ID,
    DEVELOPMENT_WORLD_IDS,
    MANIFEST_ID,
    OPERATIONAL_HOLDOUT_WORLD_IDS,
    PAIR_EXECUTION_SCHEDULE,
    PAIR_EXECUTION_SCHEDULE_SHA256,
    PAIRED_ARM_ORDER_SCHEDULE,
    PAIRED_ARM_ORDER_SCHEDULE_SHA256,
    PROMOTION_GATE,
    SCHEMA_VERSION,
    SUITE_SEED,
)


def _manifest_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": MANIFEST_ID,
        "corpus_id": CORPUS_ID,
        "benchmark_scope": {
            "official_gazebo_score": False,
            "leaderboard_claim": False,
            "policy_executed_during_corpus_targeting": False,
        },
        "promotion_gate_frozen_before_development": copy.deepcopy(PROMOTION_GATE),
        "status_at_freeze": {
            "deployment_enabled": False,
            "development_assets_generated_and_hashed": True,
            "development_policy_execution_started": False,
            "holdout_generated": False,
            "holdout_opened": False,
            "holdout_run_id": None,
        },
        "paired_protocol_frozen_before_execution": {
            "arms_never_concurrent_within_pair": True,
            "episode_workers": 4,
            "execution_schedule": list(PAIR_EXECUTION_SCHEDULE),
            "execution_schedule_sha256": PAIR_EXECUTION_SCHEDULE_SHA256,
            "one_trial_per_world": True,
            "order_schedule": list(PAIRED_ARM_ORDER_SCHEDULE),
            "order_schedule_sha256": PAIRED_ARM_ORDER_SCHEDULE_SHA256,
            "same_world_config_trial_and_seed_within_pair": True,
            "suite_seed": SUITE_SEED,
            "trials_per_world": 1,
        },
        "operational_holdout_recipe": {
            "assets_root": str(runner.DEFAULT_HOLDOUT_ASSETS_ROOT),
            "assets_root_absent_at_freeze": True,
            "cryptographically_sealed": False,
            "evaluated": False,
            "generated": False,
            "opened": False,
            "root_authorization_required": True,
            "recipe": {"world_ids": list(OPERATIONAL_HOLDOUT_WORLD_IDS)},
        },
        "development_corpus": {
            "assets_root": str(runner.DEFAULT_ASSETS_ROOT),
            "world_count": 30,
            "episodes": [{"world_id": world_id} for world_id in DEVELOPMENT_WORLD_IDS],
        },
    }


def _identity(manifest: Path, *, run_id: str) -> V8EvaluationIdentity:
    return V8EvaluationIdentity(
        run_id=run_id,
        corpus_id=CORPUS_ID,
        corpus_sha256="a" * 64,
        manifest_id=MANIFEST_ID,
        manifest_path=manifest,
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )


def _transaction_contract(tmp_path: Path, *, run_id: str):
    manifest = tmp_path / "frozen" / "split.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"corpus_id": CORPUS_ID}) + "\n", encoding="utf-8")
    manifest.chmod(0o444)
    paths, _evidence = runner._canonical_paths(results_root=tmp_path / "results")
    return _identity(manifest, run_id=run_id), paths


def _complete_every_declared_artifact(transaction: Any, paths: Any) -> None:
    transaction.write_json_artifact("report", {"complete": True})
    transaction.write_json_artifact("evidence_index", {"artifacts": 60})
    transaction.write_json_artifact("ledger_record", {"decision": "failed"})
    for name, path in paths.binary_artifact_paths.items():
        path.write_bytes(f"opaque-{name}\n".encode())
        path.chmod(0o444)
        transaction.verify_binary_artifact(name)


def _prepared_stub(
    tmp_path: Path,
    *,
    paths: Any,
    evidence_paths: dict[tuple[int, int, str], Path],
) -> runner.PreparedV8DevelopmentRun:
    return runner.PreparedV8DevelopmentRun(
        run_id="prepared-stub",
        manifest_path=tmp_path / "split.json",
        manifest={},
        manifest_verification={},
        assets_root=tmp_path / "assets",
        policy_pair=SimpleNamespace(),
        config=SimpleNamespace(),
        gate_contract=SimpleNamespace(),
        transaction_paths=paths,
        transaction=SimpleNamespace(),
        evidence_paths=evidence_paths,
    )


@pytest.mark.parametrize(
    ("failure_stage", "materialized_artifacts"),
    [
        ("pre_execution_revalidation", "none"),
        ("paired_development_execution", "one_binary"),
        ("canonical_artifact_write", "one_json"),
        ("final_input_and_binary_verification", "all"),
    ],
)
def test_callback_failures_at_runner_stages_are_aborted_and_consumed(
    tmp_path: Path,
    failure_stage: str,
    materialized_artifacts: str,
) -> None:
    identity, paths = _transaction_contract(tmp_path, run_id=f"failure-{failure_stage}")

    def fail(transaction: Any) -> None:
        transaction.set_stage(failure_stage)
        if materialized_artifacts == "one_binary":
            name, path = next(iter(paths.binary_artifact_paths.items()))
            path.write_bytes(b"partial opaque action evidence\n")
            path.chmod(0o444)
            transaction.verify_binary_artifact(name)
        elif materialized_artifacts == "one_json":
            transaction.write_json_artifact("evidence_index", {"partial": True})
        elif materialized_artifacts == "all":
            _complete_every_declared_artifact(transaction, paths)
        raise RuntimeError(f"synthetic failure at {failure_stage}")

    with pytest.raises(RuntimeError, match=f"synthetic failure at {failure_stage}"):
        preflight_v8_transaction(identity=identity, paths=paths).run(fail)

    inspection = inspect_v8_transaction(identity=identity, paths=paths)
    assert inspection.state is V8TransactionState.ABORTED
    assert inspection.consumed is True
    outcome = json.loads(paths.outcome_path.read_bytes())
    assert outcome["status"] == "aborted"
    assert outcome["stage"] == failure_stage

    retry_identity = _identity(identity.manifest_path, run_id=f"retry-{failure_stage}")
    with pytest.raises(V8TransactionConsumedError, match="transaction directory"):
        preflight_v8_transaction(identity=retry_identity, paths=paths)


def test_completed_runner_transaction_has_exact_membership_and_detects_binary_tamper(
    tmp_path: Path,
) -> None:
    identity, paths = _transaction_contract(tmp_path, run_id="complete-membership")
    expected_json_names = {"report", "evidence_index", "ledger_record"}
    expected_binary_names = {
        runner.v8_evidence_artifact_name(arm, world_id, 0)
        for world_id in DEVELOPMENT_WORLD_IDS
        for arm in ("reference", "candidate")
    }
    expected_names = expected_json_names | expected_binary_names
    assert set(paths.artifact_paths) == expected_json_names
    assert set(paths.binary_artifact_paths) == expected_binary_names
    assert len(expected_names) == 63

    preflight_v8_transaction(identity=identity, paths=paths).run(
        lambda transaction: _complete_every_declared_artifact(transaction, paths)
    )

    claim = json.loads(paths.claim_path.read_bytes())
    outcome = json.loads(paths.outcome_path.read_bytes())
    assert set(claim["paths"]["artifacts"]) == expected_names
    assert set(claim["paths"]["artifact_formats"]) == expected_names
    assert set(outcome["artifacts"]) == expected_names
    assert all(evidence is not None for evidence in outcome["artifacts"].values())
    inspection = inspect_v8_transaction(identity=identity, paths=paths)
    assert inspection.state is V8TransactionState.COMPLETED
    assert inspection.consumed is True

    tampered_path = paths.binary_artifact_paths[min(expected_binary_names)]
    tampered_path.chmod(0o644)
    tampered_path.write_bytes(b"tampered opaque action evidence\n")
    tampered_path.chmod(0o444)
    inspection = inspect_v8_transaction(identity=identity, paths=paths)
    assert inspection.state is V8TransactionState.INVALID
    assert inspection.consumed is True
    assert "artifact digests do not match disk" in inspection.reason


@pytest.mark.parametrize("terminal_state", ["completed", "aborted", "empty_hard_abort"])
def test_corpus_global_claim_prevents_retry_under_a_different_run_id(
    tmp_path: Path,
    terminal_state: str,
) -> None:
    identity, paths = _transaction_contract(tmp_path, run_id="first-run")
    prepared = preflight_v8_transaction(identity=identity, paths=paths)
    if terminal_state == "completed":
        prepared.run(lambda transaction: _complete_every_declared_artifact(transaction, paths))
        assert inspect_v8_transaction(identity=identity, paths=paths).state is (
            V8TransactionState.COMPLETED
        )
    elif terminal_state == "aborted":

        def abort(_transaction: Any) -> None:
            raise RuntimeError("synthetic evaluator failure")

        with pytest.raises(RuntimeError, match="synthetic evaluator failure"):
            prepared.run(abort)
        assert inspect_v8_transaction(identity=identity, paths=paths).state is (
            V8TransactionState.ABORTED
        )
    else:
        os.mkdir(paths.transaction_dir, 0o700)
        assert inspect_v8_transaction(identity=identity, paths=paths).state is (
            V8TransactionState.INDETERMINATE_HARD_ABORT
        )

    second_identity = _identity(identity.manifest_path, run_id="second-run")
    second_paths, _evidence = runner._canonical_paths(results_root=tmp_path / "results")
    assert second_paths.transaction_dir == paths.transaction_dir
    assert second_paths.binary_artifact_paths == paths.binary_artifact_paths
    with pytest.raises(V8TransactionConsumedError, match="transaction directory"):
        preflight_v8_transaction(identity=second_identity, paths=second_paths)


def test_run_id_never_changes_canonical_claim_or_evidence_paths(tmp_path: Path) -> None:
    first, first_evidence = runner._canonical_paths(results_root=tmp_path / "results")
    second, second_evidence = runner._canonical_paths(results_root=tmp_path / "results")

    assert first.transaction_dir == second.transaction_dir
    assert first.transaction_dir.name == runner.CANONICAL_TRANSACTION_DIRNAME
    assert first_evidence == second_evidence
    assert len(first.binary_artifact_paths) == 60
    assert set(first.binary_artifact_paths) == {
        runner.v8_evidence_artifact_name(arm, world_id, 0)
        for world_id in DEVELOPMENT_WORLD_IDS
        for arm in ("reference", "candidate")
    }


def test_prepared_evidence_paths_are_copied_and_immutable(tmp_path: Path) -> None:
    paths, evidence_paths = runner._canonical_paths(results_root=tmp_path / "results")
    source = dict(evidence_paths)
    prepared = _prepared_stub(tmp_path, paths=paths, evidence_paths=source)
    key = next(iter(evidence_paths))
    original = evidence_paths[key]

    source[key] = tmp_path / "redirected.v8ae"
    assert prepared.evidence_paths[key] == original
    with pytest.raises(TypeError):
        prepared.evidence_paths[key] = tmp_path / "mutation.v8ae"  # type: ignore[index]


def test_claimed_path_rederivation_rejects_undeclared_harness_output_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, evidence_paths = runner._canonical_paths(results_root=tmp_path / "results")
    rogue_path = tmp_path / "undeclared" / "rogue.v8ae"
    redirected = dict(evidence_paths)
    redirected[(9999, 0, "candidate")] = rogue_path
    prepared = _prepared_stub(tmp_path, paths=paths, evidence_paths=redirected)
    entered_harness: list[bool] = []
    monkeypatch.setattr(
        runner,
        "run_sensor_faithful_paired_comparison",
        lambda **_kwargs: entered_harness.append(True),
    )
    transaction = SimpleNamespace(paths=paths, set_stage=lambda _stage: None)

    with pytest.raises(
        runner.V8DevelopmentRunnerError,
        match="claimed binary action-evidence paths",
    ):
        runner._execute_claimed(prepared, transaction)

    assert entered_harness == []
    assert rogue_path.exists() is False


def test_runner_exposes_no_manifest_results_or_holdout_redirection(tmp_path: Path) -> None:
    assert set(inspect.signature(runner.run_development).parameters) == {
        "authorize_single_use",
        "run_id",
    }
    assert set(inspect.signature(runner.preflight_development).parameters) == {"run_id"}
    redirected = tmp_path / "bypass"
    with pytest.raises(SystemExit):
        runner.main(
            [
                "--authorize-single-use-development-run",
                "--results-root",
                str(redirected),
            ]
        )
    assert not redirected.exists()
    with pytest.raises(SystemExit):
        runner.main(["--holdout"])


def test_private_preparation_helper_rejects_alternate_claim_namespaces(
    tmp_path: Path,
) -> None:
    with pytest.raises(runner.V8DevelopmentRunnerError, match="canonical frozen manifest"):
        runner._prepare_development_at_paths(
            manifest_path=tmp_path / "alternate-split.json",
            results_root=runner.DEFAULT_RESULTS_ROOT,
            run_id="alternate-manifest",
        )
    with pytest.raises(runner.V8DevelopmentRunnerError, match="corpus-global results"):
        runner._prepare_development_at_paths(
            manifest_path=runner.DEFAULT_MANIFEST,
            results_root=tmp_path / "alternate-results",
            run_id="alternate-results",
        )


def test_explicit_authorization_is_checked_before_preflight_or_policy_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def forbidden_preflight(*, run_id: str | None = None) -> None:
        del run_id
        events.append("preflight")

    monkeypatch.setattr(runner, "preflight_development", forbidden_preflight)
    with pytest.raises(PermissionError, match="single-use"):
        runner.run_development(authorize_single_use=False)
    assert events == []


def test_policy_execution_callback_is_entered_only_after_transaction_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _ClaimingTransaction:
        def run(self, callback: Any) -> dict[str, bool]:
            events.append("claimed")
            return callback("claimed-transaction")

    prepared = SimpleNamespace(transaction=_ClaimingTransaction())
    monkeypatch.setattr(runner, "preflight_development", lambda **_kwargs: prepared)

    def execute(_prepared: Any, transaction: Any) -> dict[str, bool]:
        assert transaction == "claimed-transaction"
        events.append("policy_execution")
        return {"completed": True}

    monkeypatch.setattr(runner, "_execute_claimed", execute)
    assert runner.run_development(authorize_single_use=True) == {"completed": True}
    assert events == ["claimed", "policy_execution"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("promotion", "promotion gate"),
        ("status", "pre-execution state"),
        ("schedule", "execution protocol"),
        ("official", "development-only"),
        ("holdout", "holdout state"),
        ("development_root", "development corpus assets root"),
        ("holdout_root", "operational holdout assets root"),
        ("world_count", "exactly 30"),
    ],
)
def test_manifest_protocol_preflight_fails_closed_on_every_contract_change(
    mutation: str,
    message: str,
) -> None:
    payload = _manifest_payload()
    if mutation == "promotion":
        payload["promotion_gate_frozen_before_development"]["minimum_paired_success_gains"] = 2
    elif mutation == "status":
        payload["status_at_freeze"]["development_policy_execution_started"] = True
    elif mutation == "schedule":
        payload["paired_protocol_frozen_before_execution"]["episode_workers"] = 3
    elif mutation == "official":
        payload["benchmark_scope"]["leaderboard_claim"] = True
    elif mutation == "holdout":
        payload["operational_holdout_recipe"]["generated"] = True
    elif mutation == "development_root":
        payload["development_corpus"]["assets_root"] = "/tmp/redirected-development"
    elif mutation == "holdout_root":
        payload["operational_holdout_recipe"]["assets_root"] = "/tmp/redirected-holdout"
    else:
        payload["development_corpus"]["world_count"] = 29

    with pytest.raises(runner.V8DevelopmentRunnerError, match=message):
        runner._validate_manifest_protocol(payload)


def test_manifest_protocol_accepts_only_the_exact_frozen_declaration() -> None:
    runner._validate_manifest_protocol(_manifest_payload())
