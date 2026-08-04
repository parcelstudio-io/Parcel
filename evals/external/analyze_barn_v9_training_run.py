"""Reverify and diagnose an immutable V9 training run without policy notes.

The scratch runner records full evaluator-owned post-integration traces and
V8's independently certified published-action artifacts.  This module joins
those two evidence streams after the run and derives liveness from measured
motion.  It deliberately does not parse controller notes, reconstruct a
pre-shield request, or turn a training result into promotion evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, NoReturn

from .barn_sensor_faithful import V8EpisodeEvidenceCaptureSpec
from .barn_v8_action_evidence import read_v8_action_evidence
from .barn_v9_liveness import LivenessConfig
from .barn_v9_liveness_adapter import (
    EpisodeLivenessDiagnostics,
    PairedEpisodeLivenessDiagnostics,
    aggregate_paired_failure_taxonomy,
    diagnose_paired_episode,
)
from .barn_v9_step_trace import V9PostIntegrationTrace

SCHEMA_VERSION = 1
ANALYSIS_ID = "parcel-barn-v9-label-independent-training-analysis-v1"
TRAINING_EVALUATION_KIND = "barn-v9-sampled-predictive-tracker-training-paired-non-official"
V8_REFERENCE_PACKAGE_SHA256 = "189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9"
TRAINING_WORLD_IDS = frozenset(range(5000, 5100))

_SHA256_LENGTH = 64
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_LIVENESS_FAILURE_KINDS = frozenset(
    {
        "startup_timeout",
        "structured_shield_stall",
        "navigation_no_progress",
        "other_long_stationary_stall",
        "stopped_outside_goal",
        "timeout_without_long_stall",
    }
)


class V9RunAnalysisError(RuntimeError):
    """Raised when a run or its joined evidence fails closed."""


def _canonical_json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
        )
        + ("\n" if pretty else "")
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise V9RunAnalysisError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _read_immutable_regular(path: str | Path, label: str) -> tuple[Path, bytes]:
    requested = _lexical_absolute(path)
    for component in (requested, *requested.parents):
        if os.path.lexists(component) and stat.S_ISLNK(os.lstat(component).st_mode):
            raise V9RunAnalysisError(f"{label} path contains a symbolic link: {component}")
    try:
        metadata = os.lstat(requested)
    except FileNotFoundError:
        raise V9RunAnalysisError(f"{label} is missing: {requested}") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_mode & _WRITE_BITS
    ):
        raise V9RunAnalysisError(f"{label} must be an unaliased read-only regular file")
    return requested, requested.read_bytes()


def _strict_json_object(raw: bytes, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise V9RunAnalysisError(f"{label} contains duplicate field: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> NoReturn:
        raise V9RunAnalysisError(f"{label} contains non-finite value: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise V9RunAnalysisError(f"{label} is not strict JSON") from error
    if not isinstance(value, dict):
        raise V9RunAnalysisError(f"{label} must contain an object")
    return value


def _required_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V9RunAnalysisError(f"{name} must be an object")
    return value


def _required_sequence(value: object, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise V9RunAnalysisError(f"{name} must be an array")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise V9RunAnalysisError(f"{name} must be a non-negative integer")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise V9RunAnalysisError(f"{name} must be boolean")
    return value


def _optional_mapping(
    parent: Mapping[str, Any],
    key: str,
    name: str,
) -> Mapping[str, Any] | None:
    if key not in parent:
        return None
    return _required_mapping(parent[key], name)


def _bound_bundle_component(
    policy: Mapping[str, Any],
    *,
    component: str,
    package_sha256: str,
    arm: str,
) -> tuple[str, str]:
    provenance = _required_mapping(policy.get("provenance"), f"{arm}.policy.provenance")
    record = _required_mapping(
        provenance.get(component),
        f"{arm}.policy.provenance.{component}",
    )
    digest = _valid_sha256(
        record.get("sha256"),
        f"{arm}.policy.provenance.{component}.sha256",
    )
    identity = record.get("id")
    prefix = f"bundle:{package_sha256}/"
    if not isinstance(identity, str) or not identity.startswith(prefix) or len(identity) == len(prefix):
        raise V9RunAnalysisError(
            f"{arm} executed {component} identity is not bound to its advertised package"
        )
    return digest, identity[len(prefix) :]


def validate_training_report_policy_bindings(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate every package/execution binding exposed by a training report.

    Early synthetic and historical reports did not expose bundle manifests or
    evaluator policy provenance.  Their absence remains accepted for backward
    compatibility, but a partially present or inconsistent binding fails
    closed.  Planner-profile reports additionally bind the one permitted model
    YAML digest change to the executed policy metadata.
    """

    policy_pair = _required_mapping(report.get("policy_pair"), "report.policy_pair")
    reference_package = _valid_sha256(
        policy_pair.get("reference_package_sha256"),
        "policy_pair.reference_package_sha256",
    )
    candidate_package = _valid_sha256(
        policy_pair.get("candidate_package_sha256"),
        "policy_pair.candidate_package_sha256",
    )
    if reference_package != V8_REFERENCE_PACKAGE_SHA256:
        raise V9RunAnalysisError("training report reference is not the exact V8 control")

    manifest_fields = (
        "reference_manifest_sha256" in policy_pair,
        "candidate_manifest_sha256" in policy_pair,
    )
    if manifest_fields[0] is not manifest_fields[1]:
        raise V9RunAnalysisError("policy-pair manifest bindings must be present for both arms")
    reference_manifest: str | None = None
    candidate_manifest: str | None = None
    if all(manifest_fields):
        reference_manifest = _valid_sha256(
            policy_pair.get("reference_manifest_sha256"),
            "policy_pair.reference_manifest_sha256",
        )
        candidate_manifest = _valid_sha256(
            policy_pair.get("candidate_manifest_sha256"),
            "policy_pair.candidate_manifest_sha256",
        )

    candidate_freeze = _optional_mapping(
        policy_pair,
        "candidate_freeze",
        "policy_pair.candidate_freeze",
    )
    candidate_freeze_path: str | None = None
    candidate_freeze_sha256: str | None = None
    if candidate_freeze is not None:
        raw_freeze_path = candidate_freeze.get("path")
        if (
            not isinstance(raw_freeze_path, str)
            or not raw_freeze_path
            or not Path(raw_freeze_path).is_absolute()
        ):
            raise V9RunAnalysisError("candidate freeze path must be a nonempty absolute path")
        candidate_freeze_path = raw_freeze_path
        candidate_freeze_sha256 = _valid_sha256(
            candidate_freeze.get("sha256"),
            "policy_pair.candidate_freeze.sha256",
        )
        expected_freeze_claims = {
            "training_only": True,
            "promotion_evidence": False,
            "development_execution_authorized": False,
            "holdout_execution_authorized": False,
            "deployment_enabled": False,
        }
        if any(candidate_freeze.get(key) is not value for key, value in expected_freeze_claims.items()):
            raise V9RunAnalysisError("candidate freeze claims are not exact training-only claims")

    isolated_pair = _optional_mapping(policy_pair, "isolated_pair", "policy_pair.isolated_pair")
    if isolated_pair is not None:
        if reference_manifest is None or candidate_manifest is None:
            raise V9RunAnalysisError("isolated policy pair requires advertised manifest bindings")
        for arm, package, manifest in (
            ("reference", reference_package, reference_manifest),
            ("candidate", candidate_package, candidate_manifest),
        ):
            descriptor = _required_mapping(
                isolated_pair.get(arm),
                f"policy_pair.isolated_pair.{arm}",
            )
            if (
                descriptor.get("package_sha256") != package
                or descriptor.get("manifest_sha256") != manifest
            ):
                raise V9RunAnalysisError(
                    f"{arm} isolated descriptor differs from advertised package identity"
                )

    paired = _required_mapping(report.get("paired_report"), "report.paired_report")
    arm_documents = {
        "reference": _required_mapping(paired.get("baseline"), "paired_report.baseline"),
        "candidate": _required_mapping(paired.get("candidate"), "paired_report.candidate"),
    }
    policy_presence = tuple("policy" in arm_documents[arm] for arm in ("reference", "candidate"))
    if policy_presence[0] is not policy_presence[1]:
        raise V9RunAnalysisError("executed policy provenance must be present for both arms")

    executed_policies: dict[str, Mapping[str, Any]] = {}
    model_digests: dict[str, str] = {}
    config_digests: dict[str, str] = {}
    model_relatives: dict[str, str] = {}
    if all(policy_presence):
        if reference_manifest is None or candidate_manifest is None:
            raise V9RunAnalysisError("executed policy provenance requires manifest bindings")
        for arm, package, manifest in (
            ("reference", reference_package, reference_manifest),
            ("candidate", candidate_package, candidate_manifest),
        ):
            policy = _required_mapping(
                arm_documents[arm].get("policy"),
                f"paired_report.{arm}.policy",
            )
            execution = _required_mapping(
                policy.get("execution_isolation"),
                f"paired_report.{arm}.policy.execution_isolation",
            )
            if (
                execution.get("package_sha256") != package
                or execution.get("manifest_sha256") != manifest
            ):
                raise V9RunAnalysisError(
                    f"{arm} executed policy differs from advertised package identity"
                )
            executed_policies[arm] = policy
            for component in ("implementation", "config", "model_artifact", "policy_source_tree"):
                digest, relative = _bound_bundle_component(
                    policy,
                    component=component,
                    package_sha256=package,
                    arm=arm,
                )
                if component == "model_artifact":
                    model_digests[arm] = digest
                    model_relatives[arm] = relative
                elif component == "config":
                    config_digests[arm] = digest
        candidate_experiment_id = policy_pair.get("candidate_experiment_id")
        if candidate_experiment_id is not None and (
            not isinstance(candidate_experiment_id, str)
            or executed_policies["candidate"].get("policy_id") != candidate_experiment_id
        ):
            raise V9RunAnalysisError(
                "executed candidate policy ID differs from its advertised experiment identity"
            )
        if model_relatives["reference"] != model_relatives["candidate"]:
            raise V9RunAnalysisError("paired arms resolve different active model artifact paths")

    factor = (
        _optional_mapping(
            isolated_pair,
            "allowed_planner_profile_factor",
            "policy_pair.isolated_pair.allowed_planner_profile_factor",
        )
        if isolated_pair is not None
        else None
    )
    authorization = (
        _optional_mapping(
            isolated_pair,
            "planner_profile_authorization",
            "policy_pair.isolated_pair.planner_profile_authorization",
        )
        if isolated_pair is not None
        else None
    )
    if (factor is None) is not (authorization is None):
        raise V9RunAnalysisError(
            "planner-profile factor and authorization must be present together"
        )
    if factor is not None:
        if authorization is None:  # pragma: no cover - guarded by the paired presence check.
            raise V9RunAnalysisError("planner-profile authorization is missing")
        if not executed_policies:
            raise V9RunAnalysisError("planner-profile factor requires executed policy provenance")
        expected_factor_keys = {
            "all_other_runtime_and_policy_boundary_fields_equal",
            "candidate_model_artifact_sha256",
            "config_sha256",
            "kind",
            "model_id",
            "reference_model_artifact_sha256",
        }
        if set(factor) != expected_factor_keys:
            raise V9RunAnalysisError("planner-profile factor membership is not exact")
        reference_model = _valid_sha256(
            factor.get("reference_model_artifact_sha256"),
            "planner_profile_factor.reference_model_artifact_sha256",
        )
        candidate_model = _valid_sha256(
            factor.get("candidate_model_artifact_sha256"),
            "planner_profile_factor.candidate_model_artifact_sha256",
        )
        config_sha = _valid_sha256(
            factor.get("config_sha256"),
            "planner_profile_factor.config_sha256",
        )
        model_id = factor.get("model_id")
        if (
            factor.get("kind") != "active_navigation_model_artifact_sha256"
            or factor.get("all_other_runtime_and_policy_boundary_fields_equal") is not True
            or not isinstance(model_id, str)
            or not model_id
            or reference_model == candidate_model
            or model_digests
            != {"reference": reference_model, "candidate": candidate_model}
            or config_digests != {"reference": config_sha, "candidate": config_sha}
            or any(policy.get("model_id") != model_id for policy in executed_policies.values())
        ):
            raise V9RunAnalysisError(
                "executed policy provenance differs from the planner-profile factor"
            )
        expected_authorization = {
            "kind": "isolated_planner_profile_artifact_delta_v1",
            "reference_package_sha256": reference_package,
            "reference_manifest_sha256": reference_manifest,
            "candidate_package_sha256": candidate_package,
            "candidate_manifest_sha256": candidate_manifest,
            "reference_model_artifact_sha256": reference_model,
            "candidate_model_artifact_sha256": candidate_model,
            "navigation_config_sha256": config_sha,
            "model_id": model_id,
            "reference_policy_id": executed_policies["reference"].get("policy_id"),
            "candidate_policy_id": executed_policies["candidate"].get("policy_id"),
            "strict_default_validation_preserved": True,
            "exact_profile_validator_required": True,
        }
        if dict(authorization) != expected_authorization:
            raise V9RunAnalysisError(
                "planner-profile authorization differs from the executed policy pair"
            )
    elif executed_policies and model_digests["reference"] != model_digests["candidate"]:
        raise V9RunAnalysisError(
            "executed model artifacts differ without an explicit planner-profile factor"
        )

    return {
        "reference_package_sha256": reference_package,
        "candidate_package_sha256": candidate_package,
        "reference_manifest_sha256": reference_manifest,
        "candidate_manifest_sha256": candidate_manifest,
        "candidate_experiment_id": policy_pair.get("candidate_experiment_id"),
        "candidate_freeze_path": candidate_freeze_path,
        "candidate_freeze_sha256": candidate_freeze_sha256,
        "manifest_bindings_available": reference_manifest is not None,
        "isolated_pair_binding_available": isolated_pair is not None,
        "executed_policy_provenance_available": bool(executed_policies),
        "planner_profile_factor_available": factor is not None,
        "planner_profile_authorization_available": authorization is not None,
        "reference_model_artifact_sha256": model_digests.get("reference"),
        "candidate_model_artifact_sha256": model_digests.get("candidate"),
        "active_model_relative_path": model_relatives.get("reference"),
        "all_available_bindings_verified": True,
    }


def _episode_key(episode: Mapping[str, Any]) -> tuple[int, int, int]:
    return (
        _integer(episode.get("world_index"), "episode.world_index"),
        _integer(episode.get("trial"), "episode.trial"),
        _integer(episode.get("episode_seed"), "episode.episode_seed"),
    )


def _validate_trace_terminal(
    episode: Mapping[str, Any],
    trace: V9PostIntegrationTrace,
) -> None:
    world_id, _trial_id, _seed = _episode_key(episode)
    if trace.world_id != world_id:
        raise V9RunAnalysisError("episode and V9 trace world IDs differ")
    if len(trace.records) != _integer(episode.get("steps"), "episode.steps"):
        raise V9RunAnalysisError("episode and V9 trace step counts differ")
    if not trace.records:
        raise V9RunAnalysisError("V9 analysis requires a nonempty integrated trace")
    last = trace.records[-1]
    expected_position = episode.get("final_position_xy")
    if isinstance(expected_position, Sequence) and not isinstance(expected_position, (str, bytes)):
        expected_position = tuple(expected_position)
    if last.post_step_position_xy != expected_position:
        raise V9RunAnalysisError("episode and V9 trace final positions differ")
    for episode_name, trace_value in (
        ("success", last.inside_success_region),
        ("collided", last.collided),
        ("timed_out", last.timed_out),
        ("trial_started", last.trial_started),
    ):
        if _boolean(episode.get(episode_name), f"episode.{episode_name}") != trace_value:
            raise V9RunAnalysisError(f"episode and V9 trace {episode_name} values differ")


def _load_episode_evidence(
    *,
    episode: Mapping[str, Any],
    arm: str,
    report_root: Path,
) -> tuple[Any, V9PostIntegrationTrace, tuple[dict[str, object], ...]]:
    world_id, trial_id, seed = _episode_key(episode)
    if world_id not in TRAINING_WORLD_IDS:
        raise V9RunAnalysisError("analysis accepts only V9 training worlds 5000--5099")
    trace_value = _required_mapping(episode.get("v9_step_trace"), "episode.v9_step_trace")
    trace = V9PostIntegrationTrace.from_mapping(trace_value)
    expected_trace_sha = _valid_sha256(
        episode.get("v9_step_trace_sha256"),
        "episode.v9_step_trace_sha256",
    )
    if trace.sha256 != expected_trace_sha:
        raise V9RunAnalysisError("V9 trace SHA-256 does not match its episode commitment")
    _validate_trace_terminal(episode, trace)

    action = _required_mapping(episode.get("action_evidence"), "episode.action_evidence")
    identity = _required_mapping(action.get("identity"), "episode.action_evidence.identity")
    expected_artifact_sha = _valid_sha256(
        identity.get("artifact_sha256"),
        "action_evidence.identity.artifact_sha256",
    )
    expected_path = (
        report_root / "action-evidence" / f"world-{world_id}-trial-{trial_id}-{arm}.v8ae"
    )
    reported_path = _lexical_absolute(identity.get("path"))  # type: ignore[arg-type]
    if reported_path != expected_path:
        raise V9RunAnalysisError("action evidence path escapes the immutable run directory")
    verified = read_v8_action_evidence(
        reported_path,
        expected_artifact_sha256=expected_artifact_sha,
    )
    verified_identity = verified.identity
    if (
        verified_identity.arm != arm
        or verified_identity.world_id != world_id
        or verified_identity.trial_id != trial_id
        or verified_identity.seed != seed
        or verified_identity.record_count != len(trace.records)
    ):
        raise V9RunAnalysisError("verified action evidence identity differs from the episode")
    for name in (
        "artifact_sha256",
        "record_count",
        "root_record_sha256",
        "profile_id",
        "profile_sha256",
        "arm",
        "execution_order",
        "world_id",
        "trial_id",
        "seed",
    ):
        if identity.get(name) != getattr(verified_identity, name):
            raise V9RunAnalysisError(
                f"reported and independently verified action identities differ: {name}"
            )

    capture = V8EpisodeEvidenceCaptureSpec(
        arm=arm,
        execution_order=verified_identity.execution_order,
        world_id=world_id,
        trial_id=trial_id,
        seed=seed,
    )
    # The integration boundary does not expose the executive's no-progress
    # latch. Explicit None prevents a policy-note label from entering the
    # liveness taxonomy.
    rows = trace.adapter_step_rows(capture, navigation_no_progress_latch_step=None)
    return verified, trace, rows


def _episode_dynamics(
    diagnosis: EpisodeLivenessDiagnostics,
    trace: V9PostIntegrationTrace,
    config: LivenessConfig,
) -> dict[str, Any]:
    samples = diagnosis.samples
    moving = tuple(
        sample
        for sample in samples
        if sample.published_translation_mps >= config.stationary_speed_epsilon_mps
    )
    yaw_only = tuple(
        sample
        for sample in samples
        if sample.published_translation_mps < config.stationary_speed_epsilon_mps
        and abs(sample.published_yaw_rate_rps) > 1e-12
        and not sample.published_stop
    )
    combined = tuple(sample for sample in moving if abs(sample.published_yaw_rate_rps) > 1e-12)
    positions = tuple(record.post_step_position_xy for record in trace.records)
    traveled = sum(math.dist(first, second) for first, second in pairwise(positions))
    integrated_abs_yaw = sum(
        abs(sample.published_yaw_rate_rps) * trace.control_period_s for sample in samples
    )
    clearances = tuple(
        float(sample.signed_clearance_m)
        for sample in samples
        if sample.signed_clearance_m is not None
    )
    return {
        "world_id": diagnosis.world_id,
        "trial_id": diagnosis.trial_id,
        "seed": diagnosis.seed,
        "failure_kind": diagnosis.failure_kind,
        "issued_action_count": diagnosis.liveness.issued_action_count,
        "moving_translation_action_count": len(moving),
        "translation_duty_cycle": (len(moving) / len(samples) if samples else 0.0),
        "yaw_only_action_count": len(yaw_only),
        "moving_with_yaw_action_count": len(combined),
        "published_stop_action_count": sum(sample.published_stop for sample in samples),
        "maximum_consecutive_stationary_steps": (
            diagnosis.liveness.maximum_consecutive_stationary_steps
        ),
        "long_stationary_run_count": diagnosis.liveness.long_stationary_run_count,
        "stationary_tail_steps": diagnosis.liveness.stationary_tail_steps,
        "first_moving_step": moving[0].step_index if moving else None,
        "last_moving_step": moving[-1].step_index if moving else None,
        "post_integration_traveled_distance_m": traveled,
        "integrated_absolute_yaw_command_rad": integrated_abs_yaw,
        "minimum_signed_clearance_m": min(clearances) if clearances else None,
        "certificate_violation_count": sum(
            sample.certificate_satisfied is not True for sample in samples
        ),
        "structured_request_field_available_count": sum(
            sample.requested_translation_mps is not None for sample in samples
        ),
        "structured_shield_scale_field_available_count": sum(
            sample.all_ray_scale_limit is not None for sample in samples
        ),
    }


def _liveness_failure_count(counts: Mapping[str, int]) -> int:
    return sum(int(counts.get(kind, 0)) for kind in _LIVENESS_FAILURE_KINDS)


def analyze_training_run(
    report_path: str | Path,
    *,
    expected_report_sha256: str | None = None,
    config: LivenessConfig | None = None,
) -> dict[str, Any]:
    """Return a deterministic, fully reverified label-independent analysis."""

    profile = config or LivenessConfig()
    source_path, raw = _read_immutable_regular(report_path, "V9 training report")
    report_sha = _sha256_bytes(raw)
    if expected_report_sha256 is not None and report_sha != _valid_sha256(
        expected_report_sha256,
        "expected_report_sha256",
    ):
        raise V9RunAnalysisError("training report SHA-256 differs from expectation")
    report = _strict_json_object(raw, "V9 training report")
    if report.get("schema_version") != 1:
        raise V9RunAnalysisError("training report schema_version is invalid")
    if report.get("evaluation_kind") != TRAINING_EVALUATION_KIND:
        raise V9RunAnalysisError("report is not a V9 training-only evaluation")
    for name in (
        "official_score",
        "leaderboard",
        "promotion_evidence",
        "official_gazebo_score",
        "leaderboard_claim",
        "promotion_evidence_eligible",
    ):
        if report.get(name) is not False:
            raise V9RunAnalysisError(f"training report must keep {name}=false")
    run_id = report.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise V9RunAnalysisError("training report run_id is invalid")
    policy_pair = _required_mapping(report.get("policy_pair"), "report.policy_pair")
    if policy_pair.get("reference_package_sha256") != V8_REFERENCE_PACKAGE_SHA256:
        raise V9RunAnalysisError("training report reference is not the exact V8 control")
    if policy_pair.get("deployment_enabled") is not False:
        raise V9RunAnalysisError("training policy pair must remain deployment-disabled")
    policy_bindings = validate_training_report_policy_bindings(report)

    paired_report = _required_mapping(report.get("paired_report"), "report.paired_report")
    arm_documents = {
        "reference": _required_mapping(paired_report.get("baseline"), "paired_report.baseline"),
        "candidate": _required_mapping(paired_report.get("candidate"), "paired_report.candidate"),
    }
    episodes_by_arm: dict[str, dict[tuple[int, int, int], Mapping[str, Any]]] = {}
    evidence_by_arm: dict[
        str, dict[tuple[int, int, int], tuple[Any, V9PostIntegrationTrace, Any]]
    ] = {}
    for arm, arm_document in arm_documents.items():
        episodes = _required_sequence(arm_document.get("episodes"), f"{arm}.episodes")
        indexed: dict[tuple[int, int, int], Mapping[str, Any]] = {}
        loaded: dict[tuple[int, int, int], tuple[Any, V9PostIntegrationTrace, Any]] = {}
        for raw_episode in episodes:
            episode = _required_mapping(raw_episode, f"{arm}.episode")
            key = _episode_key(episode)
            if key in indexed:
                raise V9RunAnalysisError(f"{arm} contains a duplicate episode identity")
            indexed[key] = episode
            loaded[key] = _load_episode_evidence(
                episode=episode,
                arm=arm,
                report_root=source_path.parent,
            )
        episodes_by_arm[arm] = indexed
        evidence_by_arm[arm] = loaded
    if set(episodes_by_arm["reference"]) != set(episodes_by_arm["candidate"]):
        raise V9RunAnalysisError("reference and candidate episode identities differ")
    if not episodes_by_arm["reference"]:
        raise V9RunAnalysisError("training report contains no paired episodes")

    pairs: list[PairedEpisodeLivenessDiagnostics] = []
    dynamics: dict[str, list[dict[str, Any]]] = {"reference": [], "candidate": []}
    for key in sorted(episodes_by_arm["reference"]):
        reference_evidence, reference_trace, reference_rows = evidence_by_arm["reference"][key]
        candidate_evidence, candidate_trace, candidate_rows = evidence_by_arm["candidate"][key]
        pair = diagnose_paired_episode(
            reference_evidence,
            reference_rows,
            candidate_evidence,
            candidate_rows,
            config=profile,
        )
        pairs.append(pair)
        dynamics["reference"].append(_episode_dynamics(pair.reference, reference_trace, profile))
        dynamics["candidate"].append(_episode_dynamics(pair.candidate, candidate_trace, profile))

    taxonomy = aggregate_paired_failure_taxonomy(pairs)
    taxonomy_dict = taxonomy.as_dict()
    reference_failure_count = _liveness_failure_count(taxonomy.reference_counts)
    candidate_failure_count = _liveness_failure_count(taxonomy.candidate_counts)
    candidate_package_sha = _valid_sha256(
        policy_pair.get("candidate_package_sha256"),
        "policy_pair.candidate_package_sha256",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "source_report": {
            "path": str(source_path),
            "sha256": report_sha,
            "size_bytes": len(raw),
            "run_id": run_id,
            "evaluation_kind": TRAINING_EVALUATION_KIND,
        },
        "claims": {
            "official_score": False,
            "leaderboard": False,
            "promotion_evidence": False,
            "deployment_enabled": False,
            "training_worlds_are_rerunnable": True,
        },
        "policy_pair": {
            "reference_package_sha256": V8_REFERENCE_PACKAGE_SHA256,
            "candidate_package_sha256": candidate_package_sha,
        },
        "policy_bindings": policy_bindings,
        "evidence_contract": {
            "all_action_artifacts_fully_read_chain_checked_and_recertified": True,
            "all_post_integration_trace_hashes_recomputed": True,
            "one_to_one_action_trace_step_relation_verified": True,
            "policy_notes_used_for_failure_classification": False,
            "navigation_no_progress_latch_available": False,
            "pre_shield_request_fields_available": False,
            "shield_scale_fields_available": False,
            "null_fields_not_counted_as_structured_shield_vetoes": True,
            "safe_escape_witnesses_are_physical_only_not_causal_divergence_proof": True,
        },
        "liveness_config": {
            "control_period_s": profile.control_period_s,
            "stationary_speed_epsilon_mps": profile.stationary_speed_epsilon_mps,
            "stationary_odometry_epsilon_m": profile.stationary_odometry_epsilon_m,
            "long_stall_steps": profile.long_stall_steps,
            "safe_escape_progress_m": profile.safe_escape_progress_m,
            "safe_escape_minimum_clearance_m": profile.safe_escape_minimum_clearance_m,
        },
        "summary": {
            "pair_count": taxonomy.pair_count,
            "reference_liveness_failure_count": reference_failure_count,
            "candidate_liveness_failure_count": candidate_failure_count,
            "candidate_minus_reference_liveness_failure_count": (
                candidate_failure_count - reference_failure_count
            ),
            "label_independent_liveness_failure_count_reduction": (
                reference_failure_count - candidate_failure_count
            ),
            "reference_moving_translation_action_count": sum(
                item["moving_translation_action_count"] for item in dynamics["reference"]
            ),
            "candidate_moving_translation_action_count": sum(
                item["moving_translation_action_count"] for item in dynamics["candidate"]
            ),
            "reference_yaw_only_action_count": sum(
                item["yaw_only_action_count"] for item in dynamics["reference"]
            ),
            "candidate_yaw_only_action_count": sum(
                item["yaw_only_action_count"] for item in dynamics["candidate"]
            ),
        },
        "failure_taxonomy": taxonomy_dict,
        "paired_episodes": [pair.as_dict() for pair in pairs],
        "episode_dynamics": dynamics,
    }


def write_analysis_exclusive(path: str | Path, analysis: Mapping[str, Any]) -> Path:
    """Write one deterministic immutable analysis without replacement."""

    target = _lexical_absolute(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_json_bytes(dict(analysis), pretty=True)
    try:
        with target.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
    except FileExistsError:
        raise FileExistsError(f"refusing to replace V9 run analysis: {target}") from None
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-report-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    analysis = analyze_training_run(
        args.report,
        expected_report_sha256=args.expected_report_sha256,
    )
    output = args.output or args.report.parent / "analysis" / "label-independent-liveness-v1.json"
    written = write_analysis_exclusive(output, analysis)
    print(
        json.dumps(
            {
                "analysis_path": str(written),
                "analysis_sha256": _sha256_bytes(written.read_bytes()),
                "summary": analysis["summary"],
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ANALYSIS_ID",
    "SCHEMA_VERSION",
    "TRAINING_EVALUATION_KIND",
    "V9RunAnalysisError",
    "analyze_training_run",
    "main",
    "validate_training_report_policy_bindings",
    "write_analysis_exclusive",
]
