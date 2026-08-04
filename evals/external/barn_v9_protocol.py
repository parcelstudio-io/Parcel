"""Fail-closed declaration verifier for the unexecuted V9 development gate.

This module declares identities and thresholds only.  It cannot generate a
development world, select a final candidate, claim a transaction, run a policy,
or authorize either development or holdout execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from .generate_sampled_predictive_tracker_v9_training import verify_training_corpus

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ROOT = REPO_ROOT / "evals/external/experiments/barn_sampled_predictive_tracker_v9"
PROTOCOL_PATH = EXPERIMENT_ROOT / "PROTOCOL.json"
CANDIDATE_FREEZE_PATH = EXPERIMENT_ROOT / "CANDIDATE_FREEZE.json"
TRAINING_MANIFEST_PATH = (
    REPO_ROOT / "evals/external/training/barn_sampled_predictive_tracker_v9/split.json"
)
DEVELOPMENT_ASSETS_ROOT = (
    REPO_ROOT
    / ".cache/external-evals/generated/barn_sampled_predictive_tracker_v9/development/test_data"
)
HOLDOUT_ASSETS_ROOT = (
    REPO_ROOT
    / ".cache/external-evals/generated/barn_sampled_predictive_tracker_v9/holdout/test_data"
)

SCHEMA_VERSION = 1
PROTOCOL_ID = "parcel-barn-v9-sampled-predictive-tracker-paired-development-v1"
TRAINING_CORPUS_ID = "barn-sampled-predictive-tracker-v9-training-20260803-100"
TRAINING_MANIFEST_ID = "barn-sampled-predictive-tracker-v9-training-split-v1"
TRAINING_WORLD_IDS = tuple(range(5000, 5100))
DEVELOPMENT_WORLD_IDS = tuple(range(5100, 5130))
HOLDOUT_WORLD_IDS = tuple(range(5130, 5150))
TRAINING_WORLD_IDS_SHA256 = "61b8b2769406e8f4e030fdd0a6c221f0023f2d5a1d9fe871c5bb39dcaaf2ea3e"
DEVELOPMENT_WORLD_IDS_SHA256 = "ae25a4e10bb1527416b045a73e5e2740f5dbd8370fd57be4f11ff748e59a0b7a"
HOLDOUT_WORLD_IDS_SHA256 = "7834ee138d61e040abd91fe560642be49dfcea86f7b7a69cd13dede3250f85ae"
TRAINING_CORPUS_SHA256 = "40c260e32985123d648e4634f0c087ec3de8309494581b2a64ca1fd289d9907f"
TRAINING_MANIFEST_SHA256 = "018b2863bd699a2856e264b6f7712c91ed7561de48ba2999a4a6b020f6ef16fd"

V8_REFERENCE_PACKAGE_SHA256 = "189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9"
V8_REFERENCE_MANIFEST_SHA256 = "d3bca126041d69afb5553ac29656a0152242c00f29a7b987803e9dc536914115"
INITIAL_CHALLENGER_PACKAGE_SHA256 = (
    "c68bb69c247404d0deee28f26d8000200f73aeb336fb9bb0cafd0f0c3b510833"
)
INITIAL_CHALLENGER_MANIFEST_SHA256 = (
    "540658cee91c2bdb058f54ab19b9838d731f49c7be4df6ef7332aaea631b8b08"
)
CANDIDATE_FREEZE_SHA256 = "8c875e0b3a08c1fe08965a3ce6bf6a8c07acf2b9595a34b0c3e8f0400bfc52cf"

GENERATOR_SOURCE = "https://github.com/dperille/jackal-map-creation.git"
GENERATOR_COMMIT = "295ca5cc7b9b0ecea93013f0c49c5a1ca4352151"
EVIDENCE_SEED_NAMESPACE = "parcel-barn-sampled-predictive-tracker-v9-evidence-corpus-20260803"
SUITE_SEED = 20260803
TRIALS_PER_WORLD = 1
EPISODE_WORKERS = 4
ORDER_SCHEDULE = tuple(
    "candidate_then_reference" if index % 2 == 0 else "reference_then_candidate"
    for index in range(len(DEVELOPMENT_WORLD_IDS))
)
ORDER_SCHEDULE_SHA256 = "b50bc5c5d094b79d11a3873bba72f1e21841bc03ab001de8708915631bfeedd1"

_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def canonical_json_bytes(value: Any) -> bytes:
    """Return the exact no-newline encoding used by V9 commitments."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ids_sha256(world_ids: Sequence[int]) -> str:
    return canonical_json_sha256(list(world_ids))


def _execution_schedule() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "arm_order": arm_order,
            "episode_seed": SUITE_SEED + world_id * 1_009,
            "trial": 0,
            "world_id": world_id,
        }
        for world_id, arm_order in zip(
            DEVELOPMENT_WORLD_IDS,
            ORDER_SCHEDULE,
            strict=True,
        )
    )


EXECUTION_SCHEDULE = _execution_schedule()
EXECUTION_SCHEDULE_SHA256 = "862abf0ac155f993e4e772d272a89a73596ed349d5013a8de06c45f838fe0916"


def holdout_recipe() -> dict[str, Any]:
    """Return the exact visible operational-holdout recipe preimage."""

    return {
        "acceptance": (
            "first connected upstream BARN map; no policy execution; geometry and difficulty "
            "analyses are descriptive and never admission filters"
        ),
        "generator_commit": GENERATOR_COMMIT,
        "parameter_algorithm": (
            "offset=world_id-5100; fill=(0.15,0.20,0.25,0.30)[(offset//3)%4]; "
            "smooth=(2,3,4)[offset%3]; rows=30; columns=30"
        ),
        "seed_algorithm": (
            "uint64_be(sha256(namespace + ':' + world_id + ':' + attempt)[0:8]) "
            "bitwise-and 0x7fffffff"
        ),
        "seed_namespace": EVIDENCE_SEED_NAMESPACE,
        "world_ids": list(HOLDOUT_WORLD_IDS),
    }


HOLDOUT_RECIPE_COMMITMENT_SHA256 = (
    "fbb3ce7be6895722dce96de36288a4f572086b45afb51ea39c2b9cca33796e40"
)


def development_gate() -> dict[str, Any]:
    """Return every predeclared condition; every condition is conjunctive."""

    return {
        "gate_id": "parcel-barn-v9-sampled-predictive-tracker-development-gate-v1",
        "all_conditions_required_before_any_holdout_authorization": True,
        "all_first_divergences_must_share_identical_observation": True,
        "all_safe_escape_witness_actions_must_be_certified": True,
        "candidate_timeout_rate_must_not_exceed_reference": True,
        "development_threshold_is_hill_climb_only": True,
        "evidence_and_certification_latency_excluded_from_controller_latency": True,
        "exact_one_factor_source_delta": True,
        "maximum_candidate_collisions": 0,
        "maximum_candidate_observed_return_certificate_violations": 0,
        "maximum_controller_p99_latency_ms": 100.0,
        "maximum_controller_p99_latency_ratio": 1.2,
        "maximum_paired_liveness_regressions": 0,
        "maximum_paired_success_regressions": 0,
        "minimum_candidate_signed_body_clearance_m": 0.475,
        "minimum_label_independent_liveness_failure_count_reduction": 3,
        "minimum_mode_affected_paired_episodes": 15,
        "minimum_navigation_metric_delta": 0.01,
        "minimum_paired_success_gains": 3,
        "minimum_safe_escape_witness_count": 1,
        "minimum_success_rate_delta": 0.1,
        "liveness_failure_taxonomy_uses_evaluator_final_action_and_odometry_only": True,
        "no_perception_requires_zero_translation": True,
        "required_classified_rays_per_policy_issued_action": 720,
        "required_liveness_thresholds": {
            "control_period_s": 0.1,
            "long_stall_steps": 50,
            "safe_escape_minimum_clearance_m": 0.475,
            "safe_escape_progress_m": 0.5,
            "stationary_odometry_epsilon_m": 0.025,
            "stationary_speed_epsilon_mps": 0.005,
        },
        "same_world_trial_seed_config_runtime_and_schedule": True,
        "valid_terminal_evaluator_row_and_startup_marker_required": True,
        "zero_unclassified_or_missing_policy_actions": True,
    }


def protocol_document() -> dict[str, Any]:
    """Return the exact checked-in V9 pre-development declaration."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "benchmark_scope": {
            "evaluation_kind": (
                "barn-calibrated-sensor-faithful-native-headless-paired-development-v9-non-official"
            ),
            "official_gazebo_score": False,
            "leaderboard_claim": False,
            "top_decile_claim": False,
            "development_gate_is_official_rank_evidence": False,
            "development_gate_is_top_decile_evidence": False,
            "native_development_can_establish_official_or_top_decile_status": False,
            "native_proxy_uses_go2_oriented_planar_kinematics": True,
            "official_score_or_rank_requires_external_organizer_attestation": True,
            "official_barn_2026_jackal_50x10_protocol_executed": False,
        },
        "identity_partition": {
            "training": {
                "world_ids": list(TRAINING_WORLD_IDS),
                "world_ids_sha256": TRAINING_WORLD_IDS_SHA256,
                "rerunnable": True,
                "promotion_evidence_eligible": False,
            },
            "single_use_development": {
                "world_ids": list(DEVELOPMENT_WORLD_IDS),
                "world_ids_sha256": DEVELOPMENT_WORLD_IDS_SHA256,
                "assets_materialized": False,
                "materialization_authorized": False,
                "policy_execution_authorized": False,
            },
            "operational_holdout": {
                "world_ids": list(HOLDOUT_WORLD_IDS),
                "world_ids_sha256": HOLDOUT_WORLD_IDS_SHA256,
                "assets_materialized": False,
                "opened": False,
                "evaluated": False,
                "materialization_authorized": False,
                "policy_execution_authorized": False,
            },
            "all_v9_world_ids_retired_after_experiment": list(range(5000, 5150)),
            "pairwise_disjoint": True,
        },
        "training_corpus": {
            "corpus_id": TRAINING_CORPUS_ID,
            "corpus_sha256": TRAINING_CORPUS_SHA256,
            "manifest_id": TRAINING_MANIFEST_ID,
            "manifest_path": TRAINING_MANIFEST_PATH.relative_to(REPO_ROOT).as_posix(),
            "manifest_sha256": TRAINING_MANIFEST_SHA256,
            "world_count": 100,
            "initial_challenger_may_be_scratch_screened": True,
            "scratch_screening_may_select_or_reject_but_never_promote": True,
        },
        "policy_identity": {
            "reference": {
                "role": "rejected_v8_experimental_control_only",
                "package_sha256": V8_REFERENCE_PACKAGE_SHA256,
                "manifest_sha256": V8_REFERENCE_MANIFEST_SHA256,
                "v8_development_gate_passed": False,
                "deployment_enabled": False,
            },
            "initial_challenger": {
                "role": "scratch_screening_candidate_only",
                "package_sha256": INITIAL_CHALLENGER_PACKAGE_SHA256,
                "manifest_sha256": INITIAL_CHALLENGER_MANIFEST_SHA256,
                "candidate_freeze_sha256": CANDIDATE_FREEZE_SHA256,
                "scratch_screening_authorized": True,
                "development_candidate": False,
                "development_execution_authorized": False,
                "deployment_enabled": False,
            },
            "final_development_candidate": {
                "selected": False,
                "content_addressed": False,
                "package_sha256": None,
                "manifest_sha256": None,
                "source_closure_sha256": None,
                "selection_record_sha256": None,
                "separate_content_addressed_selection_required": True,
                "development_execution_authorized": False,
                "deployment_enabled": False,
            },
        },
        "development_corpus_recipe": {
            "assets_materialized": False,
            "materialization_authorized": False,
            "generator_source": GENERATOR_SOURCE,
            "generator_commit": GENERATOR_COMMIT,
            "acceptance": holdout_recipe()["acceptance"],
            "parameter_algorithm": holdout_recipe()["parameter_algorithm"],
            "seed_algorithm": holdout_recipe()["seed_algorithm"],
            "seed_namespace": EVIDENCE_SEED_NAMESPACE,
            "world_ids": list(DEVELOPMENT_WORLD_IDS),
            "world_ids_sha256": DEVELOPMENT_WORLD_IDS_SHA256,
            "policy_executed_during_generation": False,
            "geometry_or_difficulty_used_as_admission_filter": False,
        },
        "operational_holdout": {
            "assets_materialized": False,
            "cryptographically_sealed": False,
            "opened": False,
            "evaluated": False,
            "root_authorization_required_after_development_gate": True,
            "protocol_itself_authorizes_materialization_or_execution": False,
            "recipe": holdout_recipe(),
            "recipe_commitment_sha256": HOLDOUT_RECIPE_COMMITMENT_SHA256,
            "visible_recipe_cannot_support_hidden_or_official_claim": True,
        },
        "paired_protocol": {
            "arms_never_concurrent_within_pair": True,
            "episode_workers": EPISODE_WORKERS,
            "execution_schedule": list(EXECUTION_SCHEDULE),
            "execution_schedule_sha256": EXECUTION_SCHEDULE_SHA256,
            "one_trial_per_world": True,
            "order_schedule": list(ORDER_SCHEDULE),
            "order_schedule_sha256": ORDER_SCHEDULE_SHA256,
            "same_world_config_trial_and_seed_within_pair": True,
            "suite_seed": SUITE_SEED,
            "trials_per_world": TRIALS_PER_WORLD,
        },
        "development_gate": development_gate(),
        "holdout_gate": {
            "all_development_conditions_must_pass": True,
            "development_evidence_must_be_independently_reverified": True,
            "final_development_candidate_identity_must_remain_exact": True,
            "separate_explicit_root_authorization_required": True,
            "authorization_present": False,
            "holdout_execution_authorized": False,
            "scaled_paired_gate": {
                "all_conditions_required": True,
                "all_first_divergences_must_share_identical_observation": True,
                "all_safe_escape_witness_actions_must_be_certified": True,
                "candidate_timeout_rate_must_not_exceed_reference": True,
                "exact_one_factor_source_delta": True,
                "liveness_failure_taxonomy_uses_evaluator_final_action_and_odometry_only": True,
                "maximum_candidate_collisions": 0,
                "maximum_candidate_observed_return_certificate_violations": 0,
                "maximum_controller_p99_latency_ms": 100.0,
                "maximum_controller_p99_latency_ratio": 1.2,
                "maximum_paired_liveness_regressions": 0,
                "maximum_paired_success_regressions": 0,
                "minimum_candidate_signed_body_clearance_m": 0.475,
                "minimum_label_independent_liveness_failure_count_reduction": 2,
                "minimum_mode_affected_paired_episodes": 10,
                "minimum_navigation_metric_delta": 0.01,
                "minimum_paired_success_gains": 2,
                "minimum_safe_escape_witness_count": 1,
                "minimum_success_rate_delta": 0.1,
                "no_perception_requires_zero_translation": True,
                "required_classified_rays_per_policy_issued_action": 720,
                "same_world_trial_seed_config_runtime_and_schedule": True,
                "valid_terminal_evaluator_row_and_startup_marker_required": True,
                "zero_unclassified_or_missing_policy_actions": True,
            },
        },
        "evidence_contract": {
            "action_evidence_format_id": "parcel-barn-v8-action-evidence-v2",
            "action_certificate_profile_id": "parcel-v8-all-ray-yaw-swept-projected-cap",
            "post_integration_trace_schema_id": "parcel-barn-v9-post-integration-step-trace-v1",
            "verified_action_evidence_required_for_every_policy_issued_action": True,
            "post_integration_record_required_for_every_integrated_action": True,
            "step_and_episode_identities_must_join_exactly": True,
            "free_form_notes_may_not_establish_causal_metrics": True,
            "requested_action_or_shield_scale_may_not_be_inferred": True,
            "missing_structured_fields_remain_null_and_cannot_count_as_vetoes": True,
            "evidence_files_must_be_unique_regular_read_only_and_sha256_addressed": True,
            "complete_evidence_index_required": True,
            "independent_certificate_recomputation_required": True,
            "evidence_overhead_recorded_separately_from_controller_latency": True,
        },
        "single_use_transaction_contract": {
            "implementation": "evals.external.barn_v8_transaction",
            "preflight_required_before_claim": True,
            "transaction_directory_creation_is_point_of_no_return": True,
            "one_claim_for_all_30_pairs": True,
            "exactly_one_completed_or_aborted_outcome_when_observable": True,
            "hard_abort_without_outcome_is_indeterminate_and_consumed": True,
            "stale_claim_recovery_allowed": False,
            "retry_allowed": False,
            "delete_or_reset_api_allowed": False,
            "claim_outcome_and_results_use_strict_canonical_json": True,
            "binary_evidence_must_be_predeclared_and_exclusively_written": True,
            "all_artifacts_rehashed_during_inspection": True,
        },
        "source_closure_contract": {
            "closure_complete": False,
            "closure_record_sha256": None,
            "required_before_development_materialization_or_execution": True,
            "pre_and_post_execution_identity_must_match": True,
            "working_tree_is_not_an_authoritative_policy_identity": True,
            "required_components": [
                "protocol_declaration",
                "training_manifest",
                "final_candidate_selection_record",
                "reference_and_final_candidate_bundles_and_manifests",
                "generator_checkout_and_inputs",
                "calibrated_evaluator_profile_and_configuration",
                "adapter_evaluator_runner_and_policy_factory_sources",
                "action_evidence_certifier_and_transaction_sources",
                "v9_trace_liveness_adapter_and_gate_sources",
                "python_numpy_binary_and_thread_environment",
            ],
            "development_execution_authorized": False,
        },
        "declaration_status": {
            "training_corpus_frozen": True,
            "scratch_screening_authorized": True,
            "final_development_candidate_selected": False,
            "development_assets_materialized": False,
            "development_execution_started": False,
            "development_execution_authorized": False,
            "holdout_assets_materialized": False,
            "holdout_opened": False,
            "holdout_execution_authorized": False,
            "deployment_enabled": False,
        },
    }


class V9ProtocolError(RuntimeError):
    """Raised when a declaration or frozen dependency is unsafe or inconsistent."""


class V9ExecutionNotAuthorizedError(V9ProtocolError):
    """Raised by the declaration-only execution guards."""


@dataclass(frozen=True, slots=True)
class VerifiedV9Protocol:
    protocol_path: Path
    protocol_sha256: str
    protocol_semantic_sha256: str
    training_manifest_sha256: str
    training_corpus_sha256: str
    candidate_freeze_sha256: str
    final_development_candidate_selected: bool = field(default=False, init=False)
    development_execution_authorized: bool = field(default=False, init=False)
    holdout_execution_authorized: bool = field(default=False, init=False)
    deployment_enabled: bool = field(default=False, init=False)

    def report_metadata(self) -> dict[str, Any]:
        return {
            "protocol_path": str(self.protocol_path),
            "protocol_sha256": self.protocol_sha256,
            "protocol_semantic_sha256": self.protocol_semantic_sha256,
            "training_manifest_sha256": self.training_manifest_sha256,
            "training_corpus_sha256": self.training_corpus_sha256,
            "candidate_freeze_sha256": self.candidate_freeze_sha256,
            "final_development_candidate_selected": False,
            "development_execution_authorized": False,
            "holdout_execution_authorized": False,
            "deployment_enabled": False,
        }


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _read_unique_regular(path: str | Path, label: str) -> tuple[Path, bytes]:
    requested = _lexical_absolute(path)
    for component in (requested, *requested.parents):
        if os.path.lexists(component) and stat.S_ISLNK(os.lstat(component).st_mode):
            raise V9ProtocolError(f"{label} path contains a symbolic link: {component}")
    try:
        metadata = os.lstat(requested)
    except FileNotFoundError:
        raise V9ProtocolError(f"{label} is missing: {requested}") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise V9ProtocolError(f"{label} must be a uniquely linked regular file")
    return requested, requested.read_bytes()


def _strict_json_object(raw: bytes, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise V9ProtocolError(f"{label} contains duplicate field: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> NoReturn:
        raise V9ProtocolError(f"{label} contains non-finite value: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise V9ProtocolError(f"{label} is not strict JSON") from error
    if not isinstance(value, dict):
        raise V9ProtocolError(f"{label} must contain an object")
    return value


def _validate_commitments() -> None:
    if _ids_sha256(TRAINING_WORLD_IDS) != TRAINING_WORLD_IDS_SHA256:
        raise V9ProtocolError("V9 training identity commitment changed")
    if _ids_sha256(DEVELOPMENT_WORLD_IDS) != DEVELOPMENT_WORLD_IDS_SHA256:
        raise V9ProtocolError("V9 development identity commitment changed")
    if _ids_sha256(HOLDOUT_WORLD_IDS) != HOLDOUT_WORLD_IDS_SHA256:
        raise V9ProtocolError("V9 holdout identity commitment changed")
    if canonical_json_sha256(list(ORDER_SCHEDULE)) != ORDER_SCHEDULE_SHA256:
        raise V9ProtocolError("V9 arm-order commitment changed")
    if canonical_json_sha256(list(EXECUTION_SCHEDULE)) != EXECUTION_SCHEDULE_SHA256:
        raise V9ProtocolError("V9 execution-schedule commitment changed")
    if canonical_json_sha256(holdout_recipe()) != HOLDOUT_RECIPE_COMMITMENT_SHA256:
        raise V9ProtocolError("V9 holdout-recipe commitment changed")


def verify_v9_protocol(
    *,
    protocol_path: str | Path = PROTOCOL_PATH,
    training_manifest_path: str | Path = TRAINING_MANIFEST_PATH,
    candidate_freeze_path: str | Path = CANDIDATE_FREEZE_PATH,
    development_assets_root: str | Path = DEVELOPMENT_ASSETS_ROOT,
    holdout_assets_root: str | Path = HOLDOUT_ASSETS_ROOT,
) -> VerifiedV9Protocol:
    """Verify the declaration and prove that neither gated corpus exists."""

    _validate_commitments()
    checked_protocol_path, protocol_raw = _read_unique_regular(
        protocol_path,
        "V9 protocol declaration",
    )
    observed = _strict_json_object(protocol_raw, "V9 protocol declaration")
    expected = protocol_document()
    if observed != expected:
        raise V9ProtocolError("checked-in V9 protocol differs from exact code constants")

    _training_path, training_raw = _read_unique_regular(
        training_manifest_path,
        "V9 training manifest",
    )
    if _sha256_bytes(training_raw) != TRAINING_MANIFEST_SHA256:
        raise V9ProtocolError("V9 training manifest identity changed")
    training = _strict_json_object(training_raw, "V9 training manifest")
    training_corpus = training.get("training_corpus")
    partition = training.get("identity_partition")
    if (
        training.get("manifest_id") != TRAINING_MANIFEST_ID
        or training.get("corpus_id") != TRAINING_CORPUS_ID
        or not isinstance(training_corpus, Mapping)
        or training_corpus.get("corpus_sha256") != TRAINING_CORPUS_SHA256
        or training_corpus.get("world_count") != 100
        or not isinstance(partition, Mapping)
        or partition.get("training_world_ids") != list(TRAINING_WORLD_IDS)
        or partition.get("training_world_ids_sha256") != TRAINING_WORLD_IDS_SHA256
    ):
        raise V9ProtocolError("V9 training manifest content differs from the protocol freeze")
    verified_training = verify_training_corpus(Path(training_manifest_path))
    expected_training_verification = {
        "corpus_id": TRAINING_CORPUS_ID,
        "corpus_sha256": TRAINING_CORPUS_SHA256,
        "manifest_sha256": TRAINING_MANIFEST_SHA256,
        "promotion_evidence_eligible": False,
        "world_count": 100,
    }
    if verified_training != expected_training_verification:
        raise V9ProtocolError("V9 training corpus verification result is not exact")

    _freeze_path, freeze_raw = _read_unique_regular(
        candidate_freeze_path,
        "V9 initial-challenger freeze",
    )
    if _sha256_bytes(freeze_raw) != CANDIDATE_FREEZE_SHA256:
        raise V9ProtocolError("V9 initial-challenger freeze identity changed")

    for label, root in (
        ("development", _lexical_absolute(development_assets_root)),
        ("holdout", _lexical_absolute(holdout_assets_root)),
    ):
        if os.path.lexists(root):
            raise V9ProtocolError(f"unauthorized V9 {label} assets already exist: {root}")

    return VerifiedV9Protocol(
        protocol_path=checked_protocol_path,
        protocol_sha256=_sha256_bytes(protocol_raw),
        protocol_semantic_sha256=canonical_json_sha256(expected),
        training_manifest_sha256=TRAINING_MANIFEST_SHA256,
        training_corpus_sha256=TRAINING_CORPUS_SHA256,
        candidate_freeze_sha256=CANDIDATE_FREEZE_SHA256,
    )


def require_v9_development_execution_authorization(**paths: Any) -> NoReturn:
    """Fail closed: this pre-selection declaration can never authorize development."""

    verify_v9_protocol(**paths)
    raise V9ExecutionNotAuthorizedError(
        "V9 development is unauthorized until a separate content-addressed final-candidate "
        "selection and complete source closure are frozen"
    )


def require_v9_holdout_execution_authorization(**paths: Any) -> NoReturn:
    """Fail closed: holdout needs a passed development gate and separate root action."""

    verify_v9_protocol(**paths)
    raise V9ExecutionNotAuthorizedError(
        "V9 holdout is unauthorized until every development gate passes, evidence is "
        "independently reverified, and root supplies separate explicit authorization"
    )


__all__ = [
    "CANDIDATE_FREEZE_PATH",
    "CANDIDATE_FREEZE_SHA256",
    "DEVELOPMENT_ASSETS_ROOT",
    "DEVELOPMENT_WORLD_IDS",
    "DEVELOPMENT_WORLD_IDS_SHA256",
    "EVIDENCE_SEED_NAMESPACE",
    "EXECUTION_SCHEDULE",
    "EXECUTION_SCHEDULE_SHA256",
    "EXPERIMENT_ROOT",
    "HOLDOUT_ASSETS_ROOT",
    "HOLDOUT_RECIPE_COMMITMENT_SHA256",
    "HOLDOUT_WORLD_IDS",
    "HOLDOUT_WORLD_IDS_SHA256",
    "INITIAL_CHALLENGER_MANIFEST_SHA256",
    "INITIAL_CHALLENGER_PACKAGE_SHA256",
    "ORDER_SCHEDULE",
    "ORDER_SCHEDULE_SHA256",
    "PROTOCOL_ID",
    "PROTOCOL_PATH",
    "SCHEMA_VERSION",
    "TRAINING_CORPUS_ID",
    "TRAINING_CORPUS_SHA256",
    "TRAINING_MANIFEST_ID",
    "TRAINING_MANIFEST_PATH",
    "TRAINING_MANIFEST_SHA256",
    "TRAINING_WORLD_IDS",
    "TRAINING_WORLD_IDS_SHA256",
    "V8_REFERENCE_MANIFEST_SHA256",
    "V8_REFERENCE_PACKAGE_SHA256",
    "V9ExecutionNotAuthorizedError",
    "V9ProtocolError",
    "VerifiedV9Protocol",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "development_gate",
    "holdout_recipe",
    "protocol_document",
    "require_v9_development_execution_authorization",
    "require_v9_holdout_execution_authorization",
    "verify_v9_protocol",
]
