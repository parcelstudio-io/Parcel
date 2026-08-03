from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import evals.external.barn_v8_transaction as v8_transaction
from evals.external.barn_v8_transaction import (
    V8ArtifactExistsError,
    V8EvaluationIdentity,
    V8TransactionConsumedError,
    V8TransactionError,
    V8TransactionPaths,
    V8TransactionState,
    V8UnsafePathError,
    canonical_json_bytes,
    inspect_v8_transaction,
    preflight_v8_transaction,
)


def _contract(tmp_path: Path, *, run_id: str = "barn-v8-dev-4000") -> tuple[Any, Any]:
    manifest = tmp_path / "inputs" / "split.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(canonical_json_bytes({"corpus_id": "barn-v8-dev30", "worlds": [4000]}))
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    identity = V8EvaluationIdentity(
        run_id=run_id,
        corpus_id="barn-v8-dev30",
        corpus_sha256="c" * 64,
        manifest_id="barn-v8-split-v1",
        manifest_path=manifest,
        manifest_sha256=manifest_sha256,
    )
    results_root = tmp_path / "results"
    transaction_dir = results_root / "transactions" / run_id
    paths = V8TransactionPaths(
        results_root=results_root,
        transaction_dir=transaction_dir,
        claim_path=transaction_dir / "claim.json",
        outcome_path=transaction_dir / "outcome.json",
        artifact_paths={
            "report": transaction_dir / "report.json",
            "ledger_record": results_root / "ledger" / f"{run_id}.json",
        },
    )
    return identity, paths


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_v8_transaction_completes_with_canonical_content_addressed_evidence(
    tmp_path: Path,
) -> None:
    identity, paths = _contract(tmp_path)
    assert inspect_v8_transaction(identity=identity, paths=paths).state is (
        V8TransactionState.AVAILABLE
    )

    prepared = preflight_v8_transaction(identity=identity, paths=paths)
    assert paths.transaction_dir.exists() is False
    assert paths.transaction_dir.parent.is_dir()
    assert paths.artifact_paths["ledger_record"].parent.is_dir()

    def execute(transaction: Any) -> dict[str, bool]:
        transaction.set_stage("paired_world_execution")
        report_evidence = transaction.write_json_artifact(
            "report", {"metric": 0.25, "run_id": identity.run_id}
        )
        assert (
            report_evidence.sha256
            == hashlib.sha256(paths.artifact_paths["report"].read_bytes()).hexdigest()
        )
        transaction.set_stage("ledger_write")
        transaction.write_json_artifact("ledger_record", {"report_sha256": report_evidence.sha256})
        return {"ran": True}

    assert prepared.run(execute) == {"ran": True}
    assert paths.transaction_dir.is_dir()
    for path in (
        paths.claim_path,
        paths.outcome_path,
        *paths.artifact_paths.values(),
    ):
        assert path.stat().st_mode & 0o222 == 0
        assert path.read_bytes() == canonical_json_bytes(json.loads(path.read_bytes()))

    claim = _json(paths.claim_path)
    assert claim["identity"] == {
        "corpus": {"id": identity.corpus_id, "sha256": identity.corpus_sha256},
        "manifest": {
            "id": identity.manifest_id,
            "path": str(identity.manifest_path.absolute()),
            "sha256": identity.manifest_sha256,
        },
        "run_id": identity.run_id,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", claim["ownership_nonce"])
    assert claim["paths"]["transaction_dir"] == str(paths.transaction_dir.absolute())

    outcome = _json(paths.outcome_path)
    assert outcome["status"] == "completed"
    assert outcome["stage"] == "all_required_artifacts_written"
    assert outcome["exception"] is None
    assert outcome["ownership_nonce"] == claim["ownership_nonce"]
    assert outcome["claim"]["sha256"] == hashlib.sha256(paths.claim_path.read_bytes()).hexdigest()
    for name, artifact_path in paths.artifact_paths.items():
        assert (
            outcome["artifacts"][name]["sha256"]
            == hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        )

    inspection = inspect_v8_transaction(identity=identity, paths=paths)
    assert inspection.state is V8TransactionState.COMPLETED
    assert inspection.consumed is True
    assert inspection.claim_sha256 == outcome["claim"]["sha256"]
    assert inspection.outcome_sha256 == hashlib.sha256(paths.outcome_path.read_bytes()).hexdigest()

    with pytest.raises(V8TransactionConsumedError, match="transaction directory"):
        preflight_v8_transaction(identity=identity, paths=paths)
    with pytest.raises(V8TransactionConsumedError, match="already attempted"):
        prepared.claim()


def test_v8_transaction_authenticates_predeclared_immutable_binary_evidence(
    tmp_path: Path,
) -> None:
    identity, base_paths = _contract(tmp_path)
    binary_path = base_paths.transaction_dir / "candidate_4000_0.v8ae"
    paths = replace(
        base_paths,
        binary_artifact_paths={"candidate_4000_0": binary_path},
    )
    payload = b"\x00\xffparcel-v8-action-evidence\n"

    def execute(transaction: Any) -> None:
        binary_path.write_bytes(payload)
        binary_path.chmod(0o444)
        evidence = transaction.verify_binary_artifact(
            "candidate_4000_0",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
        assert evidence.canonical_json is False
        assert evidence.size_bytes == len(payload)
        transaction.write_json_artifact("report", {"binary_sha256": evidence.sha256})
        transaction.write_json_artifact("ledger_record", {"complete": True})

    preflight_v8_transaction(identity=identity, paths=paths).run(execute)

    claim = _json(paths.claim_path)
    assert claim["paths"]["artifact_formats"]["candidate_4000_0"] == "opaque_binary"
    outcome = _json(paths.outcome_path)
    assert outcome["artifacts"]["candidate_4000_0"] == {
        "canonical_json": False,
        "path": str(binary_path.absolute()),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }
    assert inspect_v8_transaction(identity=identity, paths=paths).state is (
        V8TransactionState.COMPLETED
    )

    binary_path.chmod(0o644)
    binary_path.write_bytes(payload + b"tampered")
    binary_path.chmod(0o444)
    inspection = inspect_v8_transaction(identity=identity, paths=paths)
    assert inspection.state is V8TransactionState.INVALID
    assert "artifact digests do not match disk" in inspection.reason


def test_v8_transaction_rejects_json_writer_for_binary_artifact(tmp_path: Path) -> None:
    identity, base_paths = _contract(tmp_path)
    paths = replace(
        base_paths,
        binary_artifact_paths={"candidate_evidence": base_paths.transaction_dir / "candidate.v8ae"},
    )

    with (
        pytest.raises(V8TransactionError, match="opaque_binary"),
        preflight_v8_transaction(identity=identity, paths=paths).claim() as transaction,
    ):
        transaction.write_json_artifact("candidate_evidence", {"wrong": True})

    assert inspect_v8_transaction(identity=identity, paths=paths).state is (
        V8TransactionState.ABORTED
    )


def test_v8_transaction_records_abort_and_preserves_partial_evidence(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    prepared = preflight_v8_transaction(identity=identity, paths=paths)

    def fail_after_report(transaction: Any) -> None:
        transaction.set_stage("candidate_world_4000")
        transaction.write_json_artifact("report", {"partial": True})
        raise RuntimeError("simulated evaluator failure")

    with pytest.raises(RuntimeError, match="simulated evaluator failure"):
        prepared.run(fail_after_report)

    assert paths.claim_path.is_file()
    assert paths.claim_path.stat().st_mode & 0o222 == 0
    outcome = _json(paths.outcome_path)
    assert outcome["status"] == "aborted"
    assert outcome["stage"] == "candidate_world_4000"
    assert outcome["exception"] == {
        "class": "builtins.RuntimeError",
        "message": "simulated evaluator failure",
    }
    assert outcome["artifacts"]["report"] is not None
    assert outcome["artifacts"]["ledger_record"] is None
    assert inspect_v8_transaction(identity=identity, paths=paths).state is (
        V8TransactionState.ABORTED
    )


def test_v8_context_manager_turns_incomplete_completion_into_abort(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    prepared = preflight_v8_transaction(identity=identity, paths=paths)

    with (
        pytest.raises(V8TransactionError, match="requires result artifact ledger_record"),
        prepared.claim() as transaction,
    ):
        transaction.write_json_artifact("report", {"partial": True})

    outcome = _json(paths.outcome_path)
    assert outcome["status"] == "aborted"
    assert outcome["exception"]["class"].endswith("V8TransactionError")
    assert inspect_v8_transaction(identity=identity, paths=paths).state is (
        V8TransactionState.ABORTED
    )


def test_v8_empty_transaction_directory_is_a_permanent_hard_abort(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    preflight_v8_transaction(identity=identity, paths=paths)

    # This is the exact SIGKILL gap: atomic mkdir won, claim.json did not land.
    os.mkdir(paths.transaction_dir, 0o700)

    inspection = inspect_v8_transaction(identity=identity, paths=paths)
    assert inspection.state is V8TransactionState.INDETERMINATE_HARD_ABORT
    assert inspection.consumed is True
    assert "cannot be retried" in inspection.reason
    assert paths.claim_path.exists() is False
    assert paths.outcome_path.exists() is False
    with pytest.raises(V8TransactionConsumedError, match="transaction directory"):
        preflight_v8_transaction(identity=identity, paths=paths)


def test_v8_claim_without_outcome_is_a_permanent_hard_abort(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    claimed = preflight_v8_transaction(identity=identity, paths=paths).claim()

    inspection = inspect_v8_transaction(identity=identity, paths=paths)
    assert inspection.state is V8TransactionState.INDETERMINATE_HARD_ABORT
    assert inspection.consumed is True
    assert inspection.claim_sha256 == claimed.claim_sha256
    assert paths.claim_path.is_file()
    assert paths.outcome_path.exists() is False
    with pytest.raises(V8TransactionConsumedError, match="transaction directory"):
        preflight_v8_transaction(identity=identity, paths=paths)


def test_v8_nonfinite_json_aborts_without_creating_the_bad_artifact(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    prepared = preflight_v8_transaction(identity=identity, paths=paths)

    def write_nan(transaction: Any) -> None:
        transaction.write_json_artifact("report", {"unsafe": math.nan})

    with pytest.raises(ValueError, match="Out of range float values"):
        prepared.run(write_nan)

    assert paths.artifact_paths["report"].exists() is False
    outcome = _json(paths.outcome_path)
    assert outcome["status"] == "aborted"
    assert outcome["artifacts"] == {"ledger_record": None, "report": None}
    assert inspect_v8_transaction(identity=identity, paths=paths).state is (
        V8TransactionState.ABORTED
    )


def test_v8_artifact_writer_never_clobbers_an_installed_result(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    prepared = preflight_v8_transaction(identity=identity, paths=paths)

    def execute(transaction: Any) -> None:
        transaction.write_json_artifact("report", {"winner": "first"})
        with pytest.raises(V8ArtifactExistsError, match="refusing to replace"):
            transaction.write_json_artifact("report", {"winner": "second"})
        transaction.write_json_artifact("ledger_record", {"installed": True})

    prepared.run(execute)
    assert _json(paths.artifact_paths["report"]) == {"winner": "first"}
    assert inspect_v8_transaction(identity=identity, paths=paths).state is (
        V8TransactionState.COMPLETED
    )


@pytest.mark.parametrize("existing_name", ["claim", "outcome", "report"])
def test_v8_preflight_fails_closed_on_every_existing_canonical_artifact(
    tmp_path: Path,
    existing_name: str,
) -> None:
    identity, paths = _contract(tmp_path)
    if existing_name == "report":
        target = paths.artifact_paths["ledger_record"]
        target.parent.mkdir(parents=True)
    else:
        paths.transaction_dir.mkdir(parents=True)
        target = paths.claim_path if existing_name == "claim" else paths.outcome_path
    target.write_bytes(canonical_json_bytes({"preexisting": existing_name}))

    with pytest.raises(V8TransactionConsumedError):
        preflight_v8_transaction(identity=identity, paths=paths)
    if existing_name == "outcome":
        assert paths.outcome_path.read_bytes() == canonical_json_bytes(
            {"preexisting": existing_name}
        )


def test_v8_artifact_appearing_after_preflight_prevents_directory_consumption(
    tmp_path: Path,
) -> None:
    identity, paths = _contract(tmp_path)
    prepared = preflight_v8_transaction(identity=identity, paths=paths)
    prior = canonical_json_bytes({"foreign": True})
    paths.artifact_paths["ledger_record"].write_bytes(prior)

    with pytest.raises(V8TransactionConsumedError, match="result artifact ledger_record"):
        prepared.claim()

    assert paths.transaction_dir.exists() is False
    assert paths.artifact_paths["ledger_record"].read_bytes() == prior


def test_v8_preflight_never_unlinks_a_foreign_temporary_name_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, paths = _contract(tmp_path)
    paths.results_root.mkdir(parents=True)
    fixed_hex = "d" * 32
    collision = paths.results_root / f".parcel-v8-preflight-{os.getpid()}-{fixed_hex}.tmp"
    foreign_bytes = b"foreign preflight file\n"
    collision.write_bytes(foreign_bytes)
    monkeypatch.setattr(v8_transaction.uuid, "uuid4", lambda: type("U", (), {"hex": fixed_hex})())

    with pytest.raises(FileExistsError):
        preflight_v8_transaction(identity=identity, paths=paths)

    assert collision.read_bytes() == foreign_bytes
    assert paths.transaction_dir.exists() is False


def test_v8_artifact_writer_never_unlinks_a_foreign_temporary_name_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, paths = _contract(tmp_path)
    claimed = preflight_v8_transaction(identity=identity, paths=paths).claim()
    real_uuid4 = v8_transaction.uuid.uuid4
    fixed_hex = "e" * 32
    collision = paths.transaction_dir / f".report.json.{os.getpid()}.{fixed_hex}.tmp"
    foreign_bytes = b"foreign artifact temporary file\n"
    collision.write_bytes(foreign_bytes)
    monkeypatch.setattr(v8_transaction.uuid, "uuid4", lambda: type("U", (), {"hex": fixed_hex})())

    with pytest.raises(FileExistsError):
        claimed.write_json_artifact("report", {"must_not_land": True})

    assert collision.read_bytes() == foreign_bytes
    assert paths.artifact_paths["report"].exists() is False
    monkeypatch.setattr(v8_transaction.uuid, "uuid4", real_uuid4)
    claimed.abort(RuntimeError("temporary collision"))
    assert inspect_v8_transaction(identity=identity, paths=paths).state is (
        V8TransactionState.ABORTED
    )


def test_v8_manifest_change_after_preflight_prevents_directory_consumption(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    prepared = preflight_v8_transaction(identity=identity, paths=paths)
    identity.manifest_path.write_bytes(canonical_json_bytes({"changed": True}))

    with pytest.raises(V8TransactionError, match="manifest identity changed"):
        prepared.claim()
    assert paths.transaction_dir.exists() is False


def test_v8_preflight_rejects_manifest_symlink(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    real_manifest = identity.manifest_path
    linked_manifest = tmp_path / "linked-manifest.json"
    linked_manifest.symlink_to(real_manifest)
    linked_identity = replace(identity, manifest_path=linked_manifest)

    with pytest.raises(V8UnsafePathError, match="symlink"):
        preflight_v8_transaction(identity=linked_identity, paths=paths)
    assert paths.transaction_dir.exists() is False


def test_v8_preflight_rejects_transaction_directory_symlink(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    paths.transaction_dir.parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    paths.transaction_dir.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(V8UnsafePathError, match="symlink"):
        preflight_v8_transaction(identity=identity, paths=paths)


def test_v8_preflight_rejects_symlinked_artifact_parent(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    paths.results_root.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    ledger_parent = paths.artifact_paths["ledger_record"].parent
    ledger_parent.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(V8UnsafePathError, match="symlink"):
        preflight_v8_transaction(identity=identity, paths=paths)
    assert paths.transaction_dir.exists() is False


def test_v8_paths_must_stay_in_root_and_claim_directly_in_transaction_dir(
    tmp_path: Path,
) -> None:
    identity, paths = _contract(tmp_path)
    escaped = replace(paths, artifact_paths={"report": tmp_path / "outside.json"})
    with pytest.raises(V8UnsafePathError, match="escapes results_root"):
        preflight_v8_transaction(identity=identity, paths=escaped)

    misplaced_claim = replace(paths, claim_path=paths.results_root / "claim.json")
    with pytest.raises(V8UnsafePathError, match="direct children"):
        preflight_v8_transaction(identity=identity, paths=misplaced_claim)

    directory_alias = replace(paths, artifact_paths={"report": paths.transaction_dir})
    with pytest.raises(V8UnsafePathError, match="transaction_dir"):
        preflight_v8_transaction(identity=identity, paths=directory_alias)


def test_v8_inspection_fails_closed_if_completed_evidence_is_modified(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)

    def execute(transaction: Any) -> None:
        transaction.write_json_artifact("report", {"metric": 0.1})
        transaction.write_json_artifact("ledger_record", {"record": True})

    preflight_v8_transaction(identity=identity, paths=paths).run(execute)
    report_path = paths.artifact_paths["report"]
    report_path.chmod(0o644)
    report_path.write_bytes(canonical_json_bytes({"metric": 0.9}))

    inspection = inspect_v8_transaction(identity=identity, paths=paths)
    assert inspection.state is V8TransactionState.INVALID
    assert inspection.consumed is True
    assert "terminal evidence is invalid" in inspection.reason
    with pytest.raises(V8TransactionConsumedError):
        preflight_v8_transaction(identity=identity, paths=paths)


def test_v8_outcome_without_transaction_directory_is_invalid_and_consumed(tmp_path: Path) -> None:
    identity, paths = _contract(tmp_path)
    foreign_outcome = paths.results_root / "foreign-outcome.json"
    invalid_paths = replace(paths, outcome_path=foreign_outcome)
    # The path contract itself is invalid because the outcome is not a direct
    # child, so use an external declared report to exercise orphan evidence.
    orphan = paths.artifact_paths["ledger_record"]
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(canonical_json_bytes({"orphan": True}))

    inspection = inspect_v8_transaction(identity=identity, paths=paths)
    assert inspection.state is V8TransactionState.INVALID
    assert inspection.consumed is True
    assert "without its single-use claim" in inspection.reason
    with pytest.raises(V8UnsafePathError, match="direct children"):
        preflight_v8_transaction(identity=identity, paths=invalid_paths)
