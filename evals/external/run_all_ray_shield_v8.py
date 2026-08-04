"""Run the single-use V8 paired development evaluation transaction.

This runner has no holdout mode and no output-redirection CLI.  The canonical
development corpus is consumed by one fixed, corpus-global transaction
directory: changing ``run_id`` cannot create another opportunity to execute
the same policies.  A failed gate is a completed development result, while a
runtime/provenance/evidence error is an immutable aborted result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .barn_policy_sidecar import HISTORICAL_CONFIG, verify_policy_bundle
from .barn_policy_specs import (
    BarnPolicySpec,
    parcel_isolated_bundle_candidate_spec,
    parcel_isolated_bundle_reference_spec,
    validate_isolated_policy_pair,
)
from .barn_sensor_faithful import (
    CalibratedBarnConfig,
    calibrated_policy_spec,
    run_sensor_faithful_paired_comparison,
)
from .barn_v8_policy_bundle import verify_v8_candidate_delta
from .barn_v8_promotion_gate import (
    V8DevelopmentGateContract,
    build_v8_evidence_index_from_report,
    canonical_json_bytes,
    canonical_json_sha256,
    evaluate_v8_promotion_gate,
    expected_v8_evidence_paths,
    v8_evidence_artifact_name,
)
from .barn_v8_transaction import (
    PreparedV8Transaction,
    V8EvaluationIdentity,
    V8TransactionPaths,
    preflight_v8_transaction,
)
from .generate_all_ray_shield_v8_corpus import (
    CORPUS_ID,
    DEFAULT_ASSETS_ROOT,
    DEFAULT_HOLDOUT_ASSETS_ROOT,
    DEFAULT_MANIFEST,
    DEVELOPMENT_WORLD_IDS,
    EPISODE_WORKERS,
    FROZEN_CALIBRATED_CONFIG,
    MANIFEST_ID,
    OPERATIONAL_HOLDOUT_WORLD_IDS,
    PAIR_EXECUTION_SCHEDULE,
    PAIR_EXECUTION_SCHEDULE_SHA256,
    PAIRED_ARM_ORDER_SCHEDULE,
    PAIRED_ARM_ORDER_SCHEDULE_SHA256,
    PROMOTION_GATE,
    SCHEMA_VERSION,
    SUITE_SEED,
    TRIALS_PER_WORLD,
    verify_frozen_corpus,
)

EVALUATION_KIND = "barn-v8-all-ray-paired-generated-development-non-official"
DEFAULT_RESULTS_ROOT = DEFAULT_MANIFEST.parent / "results"
CANONICAL_TRANSACTION_DIRNAME = "single-use-development-transaction"
CANONICAL_EVIDENCE_DIRNAME = "single-use-development-action-evidence"
CANONICAL_LEDGER_FILENAME = "single-use-development-ledger-record.json"
CHANGE_DESCRIPTION = (
    "Historical Parcel 75f7ff4d policy bundle versus the exact reviewed V8 all-ray "
    "yaw-swept projected-speed-shield source delta; evaluator, adapter, model, runtime, "
    "calibration, corpus, seeds, and paired schedule are held fixed."
)

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


class V8DevelopmentRunnerError(RuntimeError):
    """Raised before/inside the irreversible V8 development transaction."""


@dataclass(frozen=True, slots=True)
class V8PolicyPairPreflight:
    reference_spec: BarnPolicySpec
    candidate_spec: BarnPolicySpec
    exact_delta: Mapping[str, Any]
    isolated_pair: Mapping[str, Any]
    reference_policy_metadata_sha256: str
    candidate_policy_metadata_sha256: str
    exact_delta_sha256: str
    isolated_pair_sha256: str


@dataclass(frozen=True, slots=True)
class PreparedV8DevelopmentRun:
    """Everything authenticated before the corpus-global point of no return."""

    run_id: str
    manifest_path: Path
    manifest: Mapping[str, Any]
    manifest_verification: Mapping[str, Any]
    assets_root: Path
    policy_pair: V8PolicyPairPreflight
    config: CalibratedBarnConfig
    gate_contract: V8DevelopmentGateContract
    transaction_paths: V8TransactionPaths
    transaction: PreparedV8Transaction
    evidence_paths: Mapping[tuple[int, int, str], Path]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_paths",
            MappingProxyType(dict(self.evidence_paths)),
        )


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V8DevelopmentRunnerError(f"{name} must be a JSON object")
    return value


def _read_manifest(path: Path) -> tuple[dict[str, Any], str]:
    requested = _lexical_absolute(path)
    for component in (requested, *requested.parents):
        if os.path.lexists(component) and component.is_symlink():
            raise V8DevelopmentRunnerError(
                f"frozen manifest path contains a symbolic link: {component}"
            )
    if not requested.is_file():
        raise FileNotFoundError(f"frozen V8 manifest is missing: {requested}")
    metadata = os.lstat(requested)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & _WRITE_BITS:
        raise V8DevelopmentRunnerError("frozen V8 manifest must be an immutable regular file")
    raw = requested.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V8DevelopmentRunnerError("frozen V8 manifest is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise V8DevelopmentRunnerError("frozen V8 manifest must contain an object")
    return payload, hashlib.sha256(raw).hexdigest()


def _validate_manifest_protocol(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("manifest_id") != MANIFEST_ID
        or payload.get("corpus_id") != CORPUS_ID
    ):
        raise V8DevelopmentRunnerError("unexpected V8 manifest identity")
    benchmark = _mapping(payload.get("benchmark_scope"), "benchmark_scope")
    if (
        benchmark.get("official_gazebo_score") is not False
        or benchmark.get("leaderboard_claim") is not False
        or benchmark.get("policy_executed_during_corpus_targeting") is not False
    ):
        raise V8DevelopmentRunnerError("manifest benchmark scope is not development-only")
    if payload.get("promotion_gate_frozen_before_development") != PROMOTION_GATE:
        raise V8DevelopmentRunnerError("predeclared V8 promotion gate changed")
    status = _mapping(payload.get("status_at_freeze"), "status_at_freeze")
    expected_status = {
        "deployment_enabled": False,
        "development_assets_generated_and_hashed": True,
        "development_policy_execution_started": False,
        "holdout_generated": False,
        "holdout_opened": False,
        "holdout_run_id": None,
    }
    if dict(status) != expected_status:
        raise V8DevelopmentRunnerError("manifest is not in the frozen pre-execution state")
    protocol = _mapping(payload.get("paired_protocol_frozen_before_execution"), "paired protocol")
    expected_protocol = {
        "arms_never_concurrent_within_pair": True,
        "episode_workers": EPISODE_WORKERS,
        "execution_schedule": list(PAIR_EXECUTION_SCHEDULE),
        "execution_schedule_sha256": PAIR_EXECUTION_SCHEDULE_SHA256,
        "one_trial_per_world": True,
        "order_schedule": list(PAIRED_ARM_ORDER_SCHEDULE),
        "order_schedule_sha256": PAIRED_ARM_ORDER_SCHEDULE_SHA256,
        "same_world_config_trial_and_seed_within_pair": True,
        "suite_seed": SUITE_SEED,
        "trials_per_world": TRIALS_PER_WORLD,
    }
    if dict(protocol) != expected_protocol:
        raise V8DevelopmentRunnerError("frozen paired execution protocol changed")
    holdout = _mapping(payload.get("operational_holdout_recipe"), "operational holdout")
    if holdout.get("assets_root") != str(_lexical_absolute(DEFAULT_HOLDOUT_ASSETS_ROOT)):
        raise V8DevelopmentRunnerError("operational holdout assets root is not canonical")
    if (
        holdout.get("assets_root_absent_at_freeze") is not True
        or holdout.get("cryptographically_sealed") is not False
        or holdout.get("evaluated") is not False
        or holdout.get("generated") is not False
        or holdout.get("opened") is not False
        or holdout.get("root_authorization_required") is not True
        or _mapping(holdout.get("recipe"), "holdout recipe").get("world_ids")
        != list(OPERATIONAL_HOLDOUT_WORLD_IDS)
    ):
        raise V8DevelopmentRunnerError("operational holdout state/authorization changed")
    development = _mapping(payload.get("development_corpus"), "development_corpus")
    if development.get("assets_root") != str(_lexical_absolute(DEFAULT_ASSETS_ROOT)):
        raise V8DevelopmentRunnerError("development corpus assets root is not canonical")
    if development.get("world_count") != len(DEVELOPMENT_WORLD_IDS) or len(
        development.get("episodes", ())
    ) != len(DEVELOPMENT_WORLD_IDS):
        raise V8DevelopmentRunnerError("development corpus must contain exactly 30 worlds")


def _policy_pair_preflight(manifest: Mapping[str, Any]) -> V8PolicyPairPreflight:
    identity = _mapping(manifest.get("policy_pair_identity"), "policy_pair_identity")
    reference = _mapping(identity.get("reference"), "reference policy identity")
    candidate = _mapping(identity.get("candidate"), "candidate policy identity")
    reference_descriptor = _mapping(reference.get("descriptor"), "reference descriptor")
    candidate_descriptor = _mapping(candidate.get("descriptor"), "candidate descriptor")
    reference_bundle = verify_policy_bundle(
        str(reference.get("bundle_root")),
        expected_package_sha256=str(reference_descriptor.get("package_sha256")),
        expected_manifest_sha256=str(reference_descriptor.get("manifest_sha256")),
    )
    candidate_bundle = verify_policy_bundle(
        str(candidate.get("bundle_root")),
        expected_package_sha256=str(candidate_descriptor.get("package_sha256")),
        expected_manifest_sha256=str(candidate_descriptor.get("manifest_sha256")),
    )
    if (
        _lexical_absolute(str(reference.get("manifest_path"))) != reference_bundle.manifest_path
        or _lexical_absolute(str(candidate.get("manifest_path"))) != candidate_bundle.manifest_path
    ):
        raise V8DevelopmentRunnerError("policy bundle manifest path identity changed")
    reference_spec = parcel_isolated_bundle_reference_spec(
        reference_bundle.root,
        package_sha256=reference_bundle.package_sha256,
        manifest_sha256=reference_bundle.manifest_sha256,
        navigation_config_relative=HISTORICAL_CONFIG,
        reference_id="barn-v8-historical-reference",
        description="Byte-exact historical Parcel reference for the V8 paired experiment",
    )
    candidate_spec = parcel_isolated_bundle_candidate_spec(
        candidate_bundle.root,
        package_sha256=candidate_bundle.package_sha256,
        reference_package_sha256=reference_bundle.package_sha256,
        manifest_sha256=candidate_bundle.manifest_sha256,
        navigation_config_relative=HISTORICAL_CONFIG,
        experiment_id="barn-v8-all-ray-candidate",
        description="Deployment-disabled V8 all-ray yaw-swept candidate",
    )
    isolated_pair = validate_isolated_policy_pair(reference_spec, candidate_spec)
    if (
        identity.get("validated_isolated_pair") is not True
        or identity.get("pair_contract") != isolated_pair
    ):
        raise V8DevelopmentRunnerError("isolated policy runtime contract changed")
    exact_delta = _mapping(identity.get("exact_allowlisted_delta"), "exact delta")
    reviewed_sources = _mapping(exact_delta.get("reviewed_sources"), "reviewed sources")
    actual_delta = verify_v8_candidate_delta(
        candidate_bundle,
        reference_bundle,
        repo_root=None,
        expected_reviewed_sources=reviewed_sources,
    )
    if dict(exact_delta) != actual_delta:
        raise V8DevelopmentRunnerError("candidate is not the frozen exact one-factor delta")
    if reference_descriptor != reference_spec.process_descriptor.report_metadata():
        raise V8DevelopmentRunnerError("reference sidecar descriptor changed")
    if candidate_descriptor != candidate_spec.process_descriptor.report_metadata():
        raise V8DevelopmentRunnerError("candidate sidecar descriptor changed")
    reference_metadata = calibrated_policy_spec(reference_spec).report_metadata()
    candidate_metadata = calibrated_policy_spec(candidate_spec).report_metadata()
    return V8PolicyPairPreflight(
        reference_spec=reference_spec,
        candidate_spec=candidate_spec,
        exact_delta=actual_delta,
        isolated_pair=isolated_pair,
        reference_policy_metadata_sha256=canonical_json_sha256(reference_metadata),
        candidate_policy_metadata_sha256=canonical_json_sha256(candidate_metadata),
        exact_delta_sha256=canonical_json_sha256(actual_delta),
        isolated_pair_sha256=canonical_json_sha256(isolated_pair),
    )


def _canonical_paths(
    *,
    results_root: Path,
) -> tuple[V8TransactionPaths, dict[tuple[int, int, str], Path]]:
    transaction_dir = results_root / CANONICAL_TRANSACTION_DIRNAME
    evidence_root = results_root / CANONICAL_EVIDENCE_DIRNAME
    binary_by_name = expected_v8_evidence_paths(
        evidence_root,
        world_ids=DEVELOPMENT_WORLD_IDS,
    )
    evidence_paths = {
        (world_id, 0, arm): binary_by_name[v8_evidence_artifact_name(arm, world_id, 0)]
        for world_id in DEVELOPMENT_WORLD_IDS
        for arm in ("reference", "candidate")
    }
    paths = V8TransactionPaths(
        results_root=results_root,
        transaction_dir=transaction_dir,
        claim_path=transaction_dir / "claim.json",
        outcome_path=transaction_dir / "outcome.json",
        artifact_paths={
            "report": transaction_dir / "report.json",
            "evidence_index": transaction_dir / "evidence-index.json",
            "ledger_record": results_root / "ledger" / CANONICAL_LEDGER_FILENAME,
        },
        binary_artifact_paths=binary_by_name,
    )
    return paths, evidence_paths


def _assert_pristine_evidence_namespace(paths: Mapping[tuple[int, int, str], Path]) -> None:
    roots = {path.parent for path in paths.values()}
    if len(roots) != 1:
        raise V8DevelopmentRunnerError("binary action evidence must use one fixed directory")
    root = next(iter(roots))
    if root.is_symlink():
        raise V8DevelopmentRunnerError("binary action-evidence directory is a symbolic link")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise V8DevelopmentRunnerError(
            "binary action-evidence namespace is non-empty and therefore consumed"
        )


def _verify_manifest_inputs(path: Path) -> tuple[dict[str, Any], str, dict[str, Any]]:
    verification = verify_frozen_corpus(path)
    manifest, manifest_sha256 = _read_manifest(path)
    _validate_manifest_protocol(manifest)
    if verification.get("manifest_sha256") != manifest_sha256:
        raise V8DevelopmentRunnerError("manifest verifier and byte digest disagree")
    if (
        verification.get("corpus_id") != CORPUS_ID
        or verification.get("world_count") != len(DEVELOPMENT_WORLD_IDS)
        or verification.get("holdout_absent") is not True
        or verification.get("policy_pair_verified") is not True
    ):
        raise V8DevelopmentRunnerError("frozen corpus verifier returned an incomplete identity")
    return manifest, manifest_sha256, dict(verification)


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"barn-v8-development-{stamp}-{uuid.uuid4().hex[:8]}"


def _prepare_development_at_paths(
    *,
    manifest_path: Path,
    results_root: Path,
    run_id: str,
) -> PreparedV8DevelopmentRun:
    manifest_path = _lexical_absolute(manifest_path)
    results_root = _lexical_absolute(results_root)
    if manifest_path != _lexical_absolute(DEFAULT_MANIFEST):
        raise V8DevelopmentRunnerError(
            "the V8 development runner accepts only the canonical frozen manifest"
        )
    if results_root != _lexical_absolute(DEFAULT_RESULTS_ROOT):
        raise V8DevelopmentRunnerError(
            "the V8 development runner accepts only the corpus-global results namespace"
        )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise V8DevelopmentRunnerError("run_id is not path-safe")
    manifest, manifest_sha256, verification = _verify_manifest_inputs(manifest_path)
    policy_pair = _policy_pair_preflight(manifest)
    development = _mapping(manifest.get("development_corpus"), "development_corpus")
    assets_root = _lexical_absolute(str(development.get("assets_root")))
    corpus_sha256 = str(development.get("corpus_sha256"))
    if verification.get("corpus_sha256") != corpus_sha256:
        raise V8DevelopmentRunnerError("corpus verifier and manifest identity disagree")
    config = CalibratedBarnConfig(**FROZEN_CALIBRATED_CONFIG)
    config_sha256 = canonical_json_sha256(asdict(config))
    gate_contract = V8DevelopmentGateContract(
        run_id=run_id,
        corpus_id=CORPUS_ID,
        corpus_sha256=corpus_sha256,
        manifest_sha256=manifest_sha256,
        native_config_sha256=config_sha256,
        reference_policy_metadata_sha256=policy_pair.reference_policy_metadata_sha256,
        candidate_policy_metadata_sha256=policy_pair.candidate_policy_metadata_sha256,
        one_factor_delta_sha256=policy_pair.exact_delta_sha256,
        isolated_runtime_pair_sha256=policy_pair.isolated_pair_sha256,
        arm_order_schedule_sha256=PAIRED_ARM_ORDER_SCHEDULE_SHA256,
    )
    transaction_paths, evidence_paths = _canonical_paths(results_root=results_root)
    _assert_pristine_evidence_namespace(evidence_paths)
    transaction = preflight_v8_transaction(
        identity=V8EvaluationIdentity(
            run_id=run_id,
            corpus_id=CORPUS_ID,
            corpus_sha256=corpus_sha256,
            manifest_id=MANIFEST_ID,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
        ),
        paths=transaction_paths,
    )
    return PreparedV8DevelopmentRun(
        run_id=run_id,
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_verification=verification,
        assets_root=assets_root,
        policy_pair=policy_pair,
        config=config,
        gate_contract=gate_contract,
        transaction_paths=transaction_paths,
        transaction=transaction,
        evidence_paths=evidence_paths,
    )


def preflight_development(*, run_id: str | None = None) -> PreparedV8DevelopmentRun:
    """Authenticate the sole canonical run without claiming or executing it."""

    manifest = _lexical_absolute(DEFAULT_MANIFEST)
    results = _lexical_absolute(DEFAULT_RESULTS_ROOT)
    return _prepare_development_at_paths(
        manifest_path=manifest,
        results_root=results,
        run_id=run_id or _new_run_id(),
    )


def _reverify_prepared(prepared: PreparedV8DevelopmentRun) -> None:
    manifest, digest, verification = _verify_manifest_inputs(prepared.manifest_path)
    if (
        manifest != prepared.manifest
        or digest != prepared.gate_contract.manifest_sha256
        or verification != prepared.manifest_verification
    ):
        raise V8DevelopmentRunnerError("frozen manifest/corpus changed after preflight")
    policy_pair = _policy_pair_preflight(manifest)
    expected = prepared.policy_pair
    if (
        policy_pair.reference_policy_metadata_sha256 != expected.reference_policy_metadata_sha256
        or policy_pair.candidate_policy_metadata_sha256 != expected.candidate_policy_metadata_sha256
        or policy_pair.exact_delta_sha256 != expected.exact_delta_sha256
        or policy_pair.isolated_pair_sha256 != expected.isolated_pair_sha256
    ):
        raise V8DevelopmentRunnerError("policy bundle/runtime identity changed after preflight")


def _rederive_claimed_evidence_paths(
    prepared: PreparedV8DevelopmentRun,
    transaction: Any,
) -> Mapping[tuple[int, int, str], Path]:
    """Rebind harness outputs to the binary paths frozen in the installed claim."""

    if transaction.paths != prepared.transaction_paths:
        raise V8DevelopmentRunnerError("claimed transaction paths changed after preflight")
    declared = transaction.paths.binary_artifact_paths
    expected_names = {
        v8_evidence_artifact_name(arm, world_id, 0)
        for world_id in DEVELOPMENT_WORLD_IDS
        for arm in ("reference", "candidate")
    }
    if set(declared) != expected_names:
        raise V8DevelopmentRunnerError(
            "claimed transaction does not declare the exact binary action-evidence set"
        )
    rederived = {
        (world_id, 0, arm): declared[v8_evidence_artifact_name(arm, world_id, 0)]
        for world_id in DEVELOPMENT_WORLD_IDS
        for arm in ("reference", "candidate")
    }
    if dict(prepared.evidence_paths) != rederived:
        raise V8DevelopmentRunnerError(
            "prepared harness paths differ from the claimed binary action-evidence paths"
        )
    return MappingProxyType(rederived)


def _report_preflight(prepared: PreparedV8DevelopmentRun) -> dict[str, Any]:
    return {
        "corpus_sha256": prepared.gate_contract.corpus_sha256,
        "exact_one_factor_policy_delta": True,
        "isolated_runtime_parity": True,
        "isolated_runtime_pair_sha256": prepared.gate_contract.isolated_runtime_pair_sha256,
        "manifest_sha256": prepared.gate_contract.manifest_sha256,
        "one_factor_delta_sha256": prepared.gate_contract.one_factor_delta_sha256,
    }


def _ledger_record(
    *,
    prepared: PreparedV8DevelopmentRun,
    report: Mapping[str, Any],
    evidence_index_sha256: str,
    gates: Mapping[str, bool],
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    reference = _mapping(
        _mapping(report.get("baseline"), "baseline").get("aggregate"), "reference aggregate"
    )
    candidate = _mapping(
        _mapping(report.get("candidate"), "candidate").get("aggregate"),
        "candidate aggregate",
    )
    passed = bool(diagnostics.get("all_conditions_passed"))
    return {
        "schema_version": 1,
        "evaluation_kind": EVALUATION_KIND,
        "run_id": prepared.run_id,
        "run_date_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_id": CORPUS_ID,
        "corpus_sha256": prepared.gate_contract.corpus_sha256,
        "manifest_id": MANIFEST_ID,
        "manifest_sha256": prepared.gate_contract.manifest_sha256,
        "change_description": CHANGE_DESCRIPTION,
        "reference_metrics": {
            "success_rate": reference["success_rate"],
            "navigation_metric": reference["navigation_metric"],
            "collision_rate": reference["collision_rate"],
            "timeout_rate": reference["timeout_rate"],
            "controller_step_p99_ms": reference["controller_step_p99_ms"],
        },
        "candidate_metrics": {
            "success_rate": candidate["success_rate"],
            "navigation_metric": candidate["navigation_metric"],
            "collision_rate": candidate["collision_rate"],
            "timeout_rate": candidate["timeout_rate"],
            "controller_step_p99_ms": candidate["controller_step_p99_ms"],
            "minimum_signed_body_clearance_m": diagnostics[
                "candidate_minimum_signed_body_clearance_m"
            ],
        },
        "evidence_index_sha256": evidence_index_sha256,
        "gates": dict(gates),
        "gate_diagnostics": dict(diagnostics),
        "decision": "development_gate_passed" if passed else "development_gate_failed",
        "holdout_authorized": False,
        "holdout_evaluated": False,
        "official_score": False,
        "leaderboard_claim": False,
    }


def _execute_claimed(prepared: PreparedV8DevelopmentRun, transaction: Any) -> dict[str, Any]:
    transaction.set_stage("claimed_evidence_path_revalidation")
    evidence_paths = _rederive_claimed_evidence_paths(prepared, transaction)
    transaction.set_stage("pre_execution_revalidation")
    _reverify_prepared(prepared)
    transaction.set_stage("paired_development_execution")
    paired_report = run_sensor_faithful_paired_comparison(
        assets_root=prepared.assets_root,
        world_indices=DEVELOPMENT_WORLD_IDS,
        reference_spec=prepared.policy_pair.reference_spec,
        candidate_spec=prepared.policy_pair.candidate_spec,
        trials=TRIALS_PER_WORLD,
        suite_seed=SUITE_SEED,
        workers=EPISODE_WORKERS,
        allow_experimental=True,
        config=prepared.config,
        generated_corpus=True,
        asset_manifest_sha256=prepared.gate_contract.manifest_sha256,
        arm_order_schedule=PAIRED_ARM_ORDER_SCHEDULE,
        action_evidence_paths=evidence_paths,
    )
    paired_report["v8_preflight"] = _report_preflight(prepared)

    transaction.set_stage("post_execution_revalidation")
    _reverify_prepared(prepared)
    evidence_root = next(iter(evidence_paths.values())).parent
    evidence_index = build_v8_evidence_index_from_report(
        paired_report,
        contract=prepared.gate_contract,
        evidence_root=evidence_root,
    )
    transaction.set_stage("independent_evidence_gate")
    gates, diagnostics = evaluate_v8_promotion_gate(
        paired_report,
        evidence_index=evidence_index,
        evidence_root=evidence_root,
        contract=prepared.gate_contract,
    )
    indexed_by_key = {
        (
            str(_mapping(entry["identity"], "evidence identity")["arm"]),
            int(_mapping(entry["identity"], "evidence identity")["world_id"]),
            int(_mapping(entry["identity"], "evidence identity")["trial_id"]),
        ): _mapping(entry["identity"], "evidence identity")
        for entry in evidence_index["entries"]
    }
    for (world_id, trial_id, arm), _path in sorted(evidence_paths.items()):
        identity = indexed_by_key[(arm, world_id, trial_id)]
        transaction.verify_binary_artifact(
            v8_evidence_artifact_name(arm, world_id, trial_id),
            expected_sha256=str(identity["artifact_sha256"]),
        )

    evidence_index_sha256 = canonical_json_sha256(evidence_index)
    paired_report["v8_development"] = {
        "evaluation_kind": EVALUATION_KIND,
        "run_id": prepared.run_id,
        "change_description": CHANGE_DESCRIPTION,
        "promotion_gate": dict(PROMOTION_GATE),
        "gates": gates,
        "gate_diagnostics": diagnostics,
        "gate_passed": bool(diagnostics["all_conditions_passed"]),
        "evidence_index_sha256": evidence_index_sha256,
        "official_score": False,
        "leaderboard_claim": False,
        "holdout_authorized": False,
        "holdout_evaluated": False,
    }
    paired_report["target_status"] = {
        "development_gate_pass": bool(diagnostics["all_conditions_passed"]),
        "official_gate_pass": False,
        "leaderboard_claim": False,
        "holdout_authorized": False,
        "note": "This calibrated native development proxy is not an official Gazebo score.",
    }
    ledger = _ledger_record(
        prepared=prepared,
        report=paired_report,
        evidence_index_sha256=evidence_index_sha256,
        gates=gates,
        diagnostics=diagnostics,
    )

    transaction.set_stage("canonical_artifact_write")
    index_artifact = transaction.write_json_artifact("evidence_index", evidence_index)
    if index_artifact.sha256 != evidence_index_sha256:
        raise V8DevelopmentRunnerError("written evidence-index digest changed")
    report_artifact = transaction.write_json_artifact("report", paired_report)
    ledger_artifact = transaction.write_json_artifact("ledger_record", ledger)
    transaction.set_stage("final_input_and_binary_verification")
    _reverify_prepared(prepared)
    for (world_id, trial_id, arm), _path in sorted(evidence_paths.items()):
        identity = indexed_by_key[(arm, world_id, trial_id)]
        transaction.verify_binary_artifact(
            v8_evidence_artifact_name(arm, world_id, trial_id),
            expected_sha256=str(identity["artifact_sha256"]),
        )
    return {
        "run_id": prepared.run_id,
        "decision": ledger["decision"],
        "development_gate_passed": bool(diagnostics["all_conditions_passed"]),
        "report_path": str(prepared.transaction_paths.artifact_paths["report"]),
        "report_sha256": report_artifact.sha256,
        "evidence_index_path": str(prepared.transaction_paths.artifact_paths["evidence_index"]),
        "evidence_index_sha256": index_artifact.sha256,
        "ledger_record_path": str(prepared.transaction_paths.artifact_paths["ledger_record"]),
        "ledger_record_sha256": ledger_artifact.sha256,
        "transaction_dir": str(prepared.transaction_paths.transaction_dir),
        "official_score": False,
        "leaderboard_claim": False,
        "holdout_authorized": False,
        "holdout_evaluated": False,
    }


def run_development(
    *,
    authorize_single_use: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Consume the sole canonical development transaction when explicitly authorized."""

    if authorize_single_use is not True:
        raise PermissionError(
            "V8 development is single-use; pass authorize_single_use=True explicitly"
        )
    prepared = preflight_development(run_id=run_id)
    return prepared.transaction.run(lambda transaction: _execute_claimed(prepared, transaction))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--authorize-single-use-development-run",
        action="store_true",
        help="irreversibly consume the sole V8 development transaction",
    )
    parser.add_argument("--run-id", help="diagnostic run ID; it never changes the claim path")
    args = parser.parse_args(argv)
    if not args.authorize_single_use_development_run:
        parser.error("--authorize-single-use-development-run is required")
    result = run_development(
        authorize_single_use=True,
        run_id=args.run_id,
    )
    print(canonical_json_bytes(result).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CANONICAL_EVIDENCE_DIRNAME",
    "CANONICAL_TRANSACTION_DIRNAME",
    "DEFAULT_RESULTS_ROOT",
    "EVALUATION_KIND",
    "PreparedV8DevelopmentRun",
    "V8DevelopmentRunnerError",
    "preflight_development",
    "run_development",
]
