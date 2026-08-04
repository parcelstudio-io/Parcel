"""Fail-closed, read-only gates for rerunnable V9 training screens.

This module never runs a policy and never creates evidence.  It consumes an
explicitly hash-pinned immutable training report plus the immutable
label-independent analysis produced for that report.  Gate metrics are
rederived from episode/evidence rows; policy notes and policy-owned diagnostic
labels are deliberately outside the input paths used here.

The declarative gate uses the flat ``scratch_screen`` vocabulary stored in V9
scratch freezes.  Unknown keys are rejected so a typo cannot silently remove a
condition.  Structural/evidence disagreements raise ``V9ScratchGateError``;
valid evidence that misses a threshold returns a structured failed decision.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from statistics import fmean
from typing import Any, NoReturn

from .analyze_barn_v9_training_run import (
    ANALYSIS_ID,
    TRAINING_EVALUATION_KIND,
    TRAINING_WORLD_IDS,
    V8_REFERENCE_PACKAGE_SHA256,
    V9RunAnalysisError,
    validate_training_report_policy_bindings,
)
from .barn_native import OFFICIAL_START_XY
from .barn_v9_step_trace import V9PostIntegrationTrace, V9StepTraceError

SCHEMA_VERSION = 1
GATE_RESULT_ID = "parcel-barn-v9-training-scratch-gate-result-v1"

_SHA256_LENGTH = 64
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_FLOAT_ABS_TOLERANCE = 1e-12
_FLOAT_REL_TOLERANCE = 1e-12
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

_DECLARATION_KEYS = frozenset(
    {
        "accepted_for_next_training_stage_only_if_all_conditions_pass",
        "candidate_package_sha256",
        "gate_id",
        "screen_world_ids",
        "screening_can_never_authorize_development_holdout_or_deployment",
        "training_only",
    }
)
_GLOBAL_GATE_KEYS = frozenset(
    {
        "maximum_candidate_collisions",
        "maximum_candidate_observed_return_certificate_violations",
        "maximum_candidate_policy_stop_latch_count",
        "maximum_candidate_reverse_action_count",
        "maximum_candidate_startup_failure_count",
        "maximum_controller_p99_latency_ms",
        "maximum_controller_p99_latency_ratio",
        "maximum_candidate_mean_final_distance_to_goal_m_exclusive",
        "maximum_mean_final_distance_to_goal_m",
        "maximum_mean_final_distance_to_goal_m_exclusive",
        "maximum_mean_traveled_distance_m",
        "maximum_yaw_only_action_count",
        "minimum_candidate_signed_body_clearance_m",
        "minimum_candidate_mean_goal_progress_efficiency",
        "minimum_label_independent_liveness_failure_count_reduction",
        "minimum_mean_goal_progress_efficiency",
        "minimum_mean_goal_progress_efficiency_exclusive",
        "minimum_mean_maximum_goal_progress_m",
        "minimum_mean_maximum_goal_progress_m_exclusive",
        "minimum_success_count",
    }
)
_PER_WORLD_GATE_SPECS: dict[str, tuple[str, str, str]] = {
    "required_per_world_maximum_stationary_steps": (
        "maximum_consecutive_stationary_steps",
        "le",
        "integer",
    ),
    "required_per_world_maximum_consecutive_stationary_steps": (
        "maximum_consecutive_stationary_steps",
        "le",
        "integer",
    ),
    "required_per_world_maximum_consecutive_stationary_steps_exclusive": (
        "maximum_consecutive_stationary_steps",
        "lt",
        "integer",
    ),
    # This historical V9 scratch-freeze name means that the measured maximum
    # progress must strictly exceed the frozen value.
    "required_per_world_maximum_goal_progress_m_exclusive": (
        "maximum_goal_progress_m",
        "gt",
        "number",
    ),
    "required_per_world_minimum_maximum_goal_progress_m": (
        "maximum_goal_progress_m",
        "ge",
        "number",
    ),
    "required_per_world_maximum_final_distance_to_goal_m": (
        "final_distance_to_goal_m",
        "le",
        "number",
    ),
    "required_per_world_maximum_final_distance_to_goal_m_exclusive": (
        "final_distance_to_goal_m",
        "lt",
        "number",
    ),
    "required_per_world_minimum_goal_progress_efficiency": (
        "goal_progress_efficiency",
        "ge",
        "number",
    ),
    "required_per_world_minimum_goal_progress_efficiency_exclusive": (
        "goal_progress_efficiency",
        "gt",
        "number",
    ),
    "required_per_world_maximum_traveled_distance_m": (
        "traveled_distance_m",
        "le",
        "number",
    ),
    "required_per_world_maximum_traveled_distance_m_exclusive": (
        "traveled_distance_m",
        "lt",
        "number",
    ),
}
_SUPPORTED_GATE_KEYS = _DECLARATION_KEYS | _GLOBAL_GATE_KEYS | frozenset(
    _PER_WORLD_GATE_SPECS
)


class V9ScratchGateError(RuntimeError):
    """Raised when scratch evidence or a declarative gate fails validation."""


@dataclass(frozen=True)
class _Artifact:
    path: Path
    raw: bytes
    sha256: str
    document: dict[str, Any]


@dataclass(frozen=True)
class _EpisodeMetrics:
    world_id: int
    trial_id: int
    seed: int
    success: bool
    collided: bool
    timed_out: bool
    trial_started: bool
    startup_failed: bool
    policy_stop_latched: bool
    controller_latency_samples_ms: tuple[float, ...]
    minimum_signed_clearance_m: float
    maximum_goal_progress_m: float
    final_distance_to_goal_m: float
    goal_progress_efficiency: float
    traveled_distance_m: float
    post_integration_trace_traveled_distance_m: float
    maximum_consecutive_stationary_steps: int
    yaw_only_action_count: int
    reverse_action_count: int
    certificate_violation_count: int
    failure_kind: str

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.world_id, self.trial_id, self.seed)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise V9ScratchGateError("declarative gate must be finite JSON data") from error


def _valid_sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise V9ScratchGateError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _strict_json_object(raw: bytes, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise V9ScratchGateError(f"{label} contains duplicate field: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> NoReturn:
        raise V9ScratchGateError(f"{label} contains non-finite value: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise V9ScratchGateError(f"{label} is not strict JSON") from error
    if not isinstance(value, dict):
        raise V9ScratchGateError(f"{label} must contain an object")
    return value


def _read_immutable_json(
    path: str | Path,
    *,
    label: str,
    expected_sha256: str,
) -> _Artifact:
    expected = _valid_sha256(expected_sha256, f"expected_{label}_sha256")
    requested = _lexical_absolute(path)
    for component in (requested, *requested.parents):
        if os.path.lexists(component) and stat.S_ISLNK(os.lstat(component).st_mode):
            raise V9ScratchGateError(f"{label} path contains a symbolic link: {component}")
    try:
        metadata = os.lstat(requested)
    except FileNotFoundError:
        raise V9ScratchGateError(f"{label} is missing: {requested}") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_mode & _WRITE_BITS
    ):
        raise V9ScratchGateError(f"{label} must be an unaliased read-only regular file")
    raw = requested.read_bytes()
    actual = _sha256_bytes(raw)
    if actual != expected:
        raise V9ScratchGateError(f"{label} SHA-256 differs from expectation")
    return _Artifact(
        path=requested,
        raw=raw,
        sha256=actual,
        document=_strict_json_object(raw, label),
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V9ScratchGateError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise V9ScratchGateError(f"{name} must be an array")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise V9ScratchGateError(f"{name} must be boolean")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise V9ScratchGateError(f"{name} must be a non-negative integer")
    return value


def _signed_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise V9ScratchGateError(f"{name} must be an integer")
    return value


def _finite(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V9ScratchGateError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        suffix = f" at least {minimum}" if minimum is not None else ""
        raise V9ScratchGateError(f"{name} must be a finite number{suffix}")
    return result


def _equal_float(first: float, second: float) -> bool:
    return math.isclose(
        first,
        second,
        rel_tol=_FLOAT_REL_TOLERANCE,
        abs_tol=_FLOAT_ABS_TOLERANCE,
    )


def _require_float_equal(actual: object, expected: float, name: str) -> None:
    reported = _finite(actual, name)
    if not _equal_float(reported, expected):
        raise V9ScratchGateError(f"{name} disagrees with episode-level evidence")


def _nearest_rank_p99(values: Sequence[float]) -> float:
    if not values:
        raise V9ScratchGateError("controller p99 requires at least one latency sample")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1))
    return ordered[index]


def _episode_key(episode: Mapping[str, Any], *, prefix: str) -> tuple[int, int, int]:
    world_id = _integer(episode.get("world_index"), f"{prefix}.world_index")
    if world_id not in TRAINING_WORLD_IDS:
        raise V9ScratchGateError("scratch gate accepts only V9 training worlds 5000--5099")
    return (
        world_id,
        _integer(episode.get("trial"), f"{prefix}.trial"),
        _integer(episode.get("episode_seed"), f"{prefix}.episode_seed"),
    )


def _index_report_episodes(
    report: Mapping[str, Any],
) -> dict[str, dict[tuple[int, int, int], Mapping[str, Any]]]:
    paired = _mapping(report.get("paired_report"), "report.paired_report")
    arms = {
        "reference": _mapping(paired.get("baseline"), "paired_report.baseline"),
        "candidate": _mapping(paired.get("candidate"), "paired_report.candidate"),
    }
    indexed: dict[str, dict[tuple[int, int, int], Mapping[str, Any]]] = {}
    for arm, document in arms.items():
        items: dict[tuple[int, int, int], Mapping[str, Any]] = {}
        for position, raw_episode in enumerate(
            _sequence(document.get("episodes"), f"paired_report.{arm}.episodes")
        ):
            episode = _mapping(raw_episode, f"paired_report.{arm}.episodes[{position}]")
            key = _episode_key(episode, prefix=f"{arm}.episode[{position}]")
            if key in items:
                raise V9ScratchGateError(f"{arm} report contains duplicate episode identity")
            items[key] = episode
        if not items:
            raise V9ScratchGateError(f"{arm} report contains no episodes")
        indexed[arm] = items
    if set(indexed["reference"]) != set(indexed["candidate"]):
        raise V9ScratchGateError("reference and candidate report episode identities differ")
    return indexed


def _index_analysis_records(
    analysis: Mapping[str, Any],
    name: str,
) -> dict[tuple[int, int, int], Mapping[str, Any]]:
    items: dict[tuple[int, int, int], Mapping[str, Any]] = {}
    for position, raw in enumerate(_sequence(analysis.get(name), f"analysis.{name}")):
        item = _mapping(raw, f"analysis.{name}[{position}]")
        key = (
            _integer(item.get("world_id"), f"analysis.{name}[{position}].world_id"),
            _integer(item.get("trial_id"), f"analysis.{name}[{position}].trial_id"),
            _integer(item.get("seed"), f"analysis.{name}[{position}].seed"),
        )
        if key[0] not in TRAINING_WORLD_IDS:
            raise V9ScratchGateError("analysis contains a non-training world")
        if key in items:
            raise V9ScratchGateError(f"analysis.{name} contains duplicate episode identity")
        items[key] = item
    return items


def _validate_top_level_contract(
    report_artifact: _Artifact,
    analysis_artifact: _Artifact,
) -> tuple[str, Mapping[str, Any], Mapping[str, Any], dict[str, Any], bool]:
    report = report_artifact.document
    analysis = analysis_artifact.document
    if report.get("schema_version") != 1:
        raise V9ScratchGateError("training report schema_version is invalid")
    if report.get("evaluation_kind") != TRAINING_EVALUATION_KIND:
        raise V9ScratchGateError("report is not a V9 training-only evaluation")
    for name in (
        "official_score",
        "leaderboard",
        "promotion_evidence",
        "official_gazebo_score",
        "leaderboard_claim",
        "promotion_evidence_eligible",
    ):
        if report.get(name) is not False:
            raise V9ScratchGateError(f"training report must keep {name}=false")
    run_id = report.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise V9ScratchGateError("training report run_id is invalid")

    report_pair = _mapping(report.get("policy_pair"), "report.policy_pair")
    if report_pair.get("reference_package_sha256") != V8_REFERENCE_PACKAGE_SHA256:
        raise V9ScratchGateError("training report reference is not the exact V8 control")
    if report_pair.get("deployment_enabled") is not False:
        raise V9ScratchGateError("training report policy pair must be deployment-disabled")
    candidate_sha = _valid_sha256(
        report_pair.get("candidate_package_sha256"),
        "report.policy_pair.candidate_package_sha256",
    )

    if analysis.get("schema_version") != 1 or analysis.get("analysis_id") != ANALYSIS_ID:
        raise V9ScratchGateError("label-independent analysis identity is invalid")
    source = _mapping(analysis.get("source_report"), "analysis.source_report")
    if (
        source.get("path") != str(report_artifact.path)
        or source.get("sha256") != report_artifact.sha256
        or source.get("size_bytes") != len(report_artifact.raw)
        or source.get("run_id") != run_id
        or source.get("evaluation_kind") != TRAINING_EVALUATION_KIND
    ):
        raise V9ScratchGateError("analysis source-report identity differs from the report")
    claims = _mapping(analysis.get("claims"), "analysis.claims")
    expected_claims = {
        "official_score": False,
        "leaderboard": False,
        "promotion_evidence": False,
        "deployment_enabled": False,
        "training_worlds_are_rerunnable": True,
    }
    if dict(claims) != expected_claims:
        raise V9ScratchGateError("analysis claims are not exact training-only claims")
    evidence = _mapping(analysis.get("evidence_contract"), "analysis.evidence_contract")
    required_true = (
        "all_action_artifacts_fully_read_chain_checked_and_recertified",
        "all_post_integration_trace_hashes_recomputed",
        "one_to_one_action_trace_step_relation_verified",
        "null_fields_not_counted_as_structured_shield_vetoes",
    )
    if any(evidence.get(name) is not True for name in required_true):
        raise V9ScratchGateError("analysis does not attest complete evidence verification")
    if evidence.get("policy_notes_used_for_failure_classification") is not False:
        raise V9ScratchGateError("analysis must not use policy notes for classification")

    expected_liveness_config = {
        "control_period_s": 0.1,
        "stationary_speed_epsilon_mps": 0.005,
        "stationary_odometry_epsilon_m": 0.025,
        "long_stall_steps": 50,
        "safe_escape_progress_m": 0.5,
        "safe_escape_minimum_clearance_m": 0.475,
    }
    liveness_config = _mapping(analysis.get("liveness_config"), "analysis.liveness_config")
    if dict(liveness_config) != expected_liveness_config:
        raise V9ScratchGateError("analysis liveness_config is not the exact frozen default")

    analysis_pair = _mapping(analysis.get("policy_pair"), "analysis.policy_pair")
    if (
        analysis_pair.get("reference_package_sha256") != V8_REFERENCE_PACKAGE_SHA256
        or analysis_pair.get("candidate_package_sha256") != candidate_sha
    ):
        raise V9ScratchGateError("report and analysis policy identities differ")
    try:
        policy_bindings = validate_training_report_policy_bindings(report)
    except V9RunAnalysisError as error:
        raise V9ScratchGateError(f"training report policy binding is invalid: {error}") from error
    analysis_binding_matches = False
    if "policy_bindings" in analysis:
        analysis_bindings = _mapping(analysis["policy_bindings"], "analysis.policy_bindings")
        if dict(analysis_bindings) != policy_bindings:
            raise V9ScratchGateError("report and analysis policy bindings differ")
        analysis_binding_matches = True
    return run_id, report_pair, analysis_pair, policy_bindings, analysis_binding_matches


def _report_episode_values(
    episode: Mapping[str, Any],
    *,
    prefix: str,
) -> dict[str, Any]:
    success = _boolean(episode.get("success"), f"{prefix}.success")
    collided = _boolean(episode.get("collided"), f"{prefix}.collided")
    timed_out = _boolean(episode.get("timed_out"), f"{prefix}.timed_out")
    trial_started = _boolean(episode.get("trial_started"), f"{prefix}.trial_started")
    startup_timed_out = _boolean(
        episode.get("startup_timed_out"), f"{prefix}.startup_timed_out"
    )
    stopped = _boolean(episode.get("stopped"), f"{prefix}.stopped")
    evaluator = _mapping(episode.get("evaluator_diagnostics"), f"{prefix}.evaluator_diagnostics")
    if evaluator.get("evaluator_private_state") is not True:
        raise V9ScratchGateError(f"{prefix} lacks evaluator-owned diagnostics")

    initial = _finite(
        evaluator.get("initial_goal_distance_m"),
        f"{prefix}.evaluator_diagnostics.initial_goal_distance_m",
        minimum=0.0,
    )
    closest = _finite(
        evaluator.get("closest_goal_distance_m"),
        f"{prefix}.evaluator_diagnostics.closest_goal_distance_m",
        minimum=0.0,
    )
    maximum_progress = initial - closest
    reported_progress = _finite(
        evaluator.get("maximum_goal_progress_m"),
        f"{prefix}.evaluator_diagnostics.maximum_goal_progress_m",
    )
    if not _equal_float(maximum_progress, reported_progress):
        raise V9ScratchGateError(f"{prefix} maximum progress is not evaluator-derived")

    final_distance = _finite(
        episode.get("final_distance_to_goal_m"),
        f"{prefix}.final_distance_to_goal_m",
        minimum=0.0,
    )
    _require_float_equal(
        evaluator.get("final_goal_distance_m"),
        final_distance,
        f"{prefix}.evaluator_diagnostics.final_goal_distance_m",
    )
    traveled = _finite(
        episode.get("traveled_distance_m"),
        f"{prefix}.traveled_distance_m",
        minimum=0.0,
    )
    try:
        trace = V9PostIntegrationTrace.from_mapping(
            _mapping(episode.get("v9_step_trace"), f"{prefix}.v9_step_trace")
        )
    except (TypeError, V9StepTraceError) as error:
        raise V9ScratchGateError(f"{prefix} post-integration trace is invalid") from error
    if trace.world_id != _integer(episode.get("world_index"), f"{prefix}.world_index"):
        raise V9ScratchGateError(f"{prefix} trace world identity differs")
    if not trace.records:
        raise V9ScratchGateError(f"{prefix} trace contains no integrated actions")
    if len(trace.records) != _integer(episode.get("steps"), f"{prefix}.steps"):
        raise V9ScratchGateError(f"{prefix} trace and episode step counts differ")
    trace_sha = _valid_sha256(
        episode.get("v9_step_trace_sha256"), f"{prefix}.v9_step_trace_sha256"
    )
    if trace.sha256 != trace_sha:
        raise V9ScratchGateError(f"{prefix} trace SHA-256 commitment differs")
    post_positions = tuple(record.post_step_position_xy for record in trace.records)
    full_trace_traveled = sum(
        math.dist(first, second)
        for first, second in pairwise((OFFICIAL_START_XY, *post_positions))
    )
    if not _equal_float(traveled, full_trace_traveled):
        raise V9ScratchGateError(f"{prefix} traveled distance is not trace-derived")
    post_integration_trace_traveled = sum(
        math.dist(first, second) for first, second in pairwise(post_positions)
    )
    efficiency = maximum_progress / traveled if traveled > 0.0 else 0.0
    _require_float_equal(
        evaluator.get("goal_progress_efficiency"),
        efficiency,
        f"{prefix}.evaluator_diagnostics.goal_progress_efficiency",
    )
    clearance = _finite(
        evaluator.get("minimum_signed_obstacle_clearance_m"),
        f"{prefix}.evaluator_diagnostics.minimum_signed_obstacle_clearance_m",
    )
    samples = tuple(
        _finite(item, f"{prefix}.controller_latency[{position}]", minimum=0.0)
        for position, item in enumerate(
            _sequence(
                episode.get("evaluator_controller_step_latency_samples_ms"),
                f"{prefix}.evaluator_controller_step_latency_samples_ms",
            )
        )
    )
    if not samples:
        raise V9ScratchGateError(f"{prefix} has no controller latency evidence")
    shield = _mapping(
        episode.get("shield_stall_diagnostics"), f"{prefix}.shield_stall_diagnostics"
    )
    reverse_action_count = _integer(
        shield.get("reverse_command_steps"),
        f"{prefix}.shield_stall_diagnostics.reverse_command_steps",
    )
    return {
        "success": success,
        "collided": collided,
        "timed_out": timed_out,
        "trial_started": trial_started,
        "startup_failed": startup_timed_out or not trial_started,
        "policy_stop_latched": stopped,
        "controller_latency_samples_ms": samples,
        "minimum_signed_clearance_m": clearance,
        "maximum_goal_progress_m": maximum_progress,
        "final_distance_to_goal_m": final_distance,
        "goal_progress_efficiency": efficiency,
        "traveled_distance_m": traveled,
        "post_integration_trace_traveled_distance_m": post_integration_trace_traveled,
        "reverse_action_count": reverse_action_count,
    }


def _validate_report_aggregate(
    arm: str,
    arm_document: Mapping[str, Any],
    values: Sequence[Mapping[str, Any]],
) -> None:
    aggregate = _mapping(arm_document.get("aggregate"), f"report.{arm}.aggregate")
    count = len(values)
    samples = tuple(
        sample for item in values for sample in item["controller_latency_samples_ms"]
    )
    clearances = tuple(float(item["minimum_signed_clearance_m"]) for item in values)
    expected = {
        "episodes": float(count),
        "success_rate": sum(bool(item["success"]) for item in values) / count,
        "collision_rate": sum(bool(item["collided"]) for item in values) / count,
        "startup_failure_rate": sum(bool(item["startup_failed"]) for item in values) / count,
        "policy_stop_latch_rate": sum(bool(item["policy_stop_latched"]) for item in values)
        / count,
        "controller_step_count": float(len(samples)),
        "controller_step_p99_ms": _nearest_rank_p99(samples),
        "mean_final_distance_to_goal_m": fmean(
            float(item["final_distance_to_goal_m"]) for item in values
        ),
        "mean_traveled_distance_m": fmean(float(item["traveled_distance_m"]) for item in values),
    }
    for name, value in expected.items():
        _require_float_equal(aggregate.get(name), value, f"report.{arm}.aggregate.{name}")
    evaluator = _mapping(
        aggregate.get("evaluator_diagnostics"),
        f"report.{arm}.aggregate.evaluator_diagnostics",
    )
    evaluator_expected = {
        "mean_maximum_goal_progress_m": fmean(
            float(item["maximum_goal_progress_m"]) for item in values
        ),
        "mean_goal_progress_efficiency": fmean(
            float(item["goal_progress_efficiency"]) for item in values
        ),
        "minimum_signed_obstacle_clearance_m": min(clearances),
    }
    for name, value in evaluator_expected.items():
        _require_float_equal(
            evaluator.get(name),
            value,
            f"report.{arm}.aggregate.evaluator_diagnostics.{name}",
        )
    sensor = _mapping(
        aggregate.get("sensor_diagnostics"),
        f"report.{arm}.aggregate.sensor_diagnostics",
    )
    if _integer(
        sensor.get("reverse_command_steps"),
        f"report.{arm}.aggregate.sensor_diagnostics.reverse_command_steps",
    ) != sum(int(item["reverse_action_count"]) for item in values):
        raise V9ScratchGateError(
            f"report.{arm}.aggregate reverse action count disagrees with episode evidence"
        )


def _join_metrics(
    report: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> tuple[dict[str, tuple[_EpisodeMetrics, ...]], Mapping[str, Any]]:
    report_episodes = _index_report_episodes(report)
    paired_records = _index_analysis_records(analysis, "paired_episodes")
    dynamics_root = _mapping(analysis.get("episode_dynamics"), "analysis.episode_dynamics")
    dynamics = {
        arm: _index_analysis_records(dynamics_root, arm) for arm in ("reference", "candidate")
    }
    expected_keys = set(report_episodes["reference"])
    if set(paired_records) != expected_keys or any(
        set(dynamics[arm]) != expected_keys for arm in dynamics
    ):
        raise V9ScratchGateError("report and analysis episode identities differ")

    joined: dict[str, list[_EpisodeMetrics]] = {"reference": [], "candidate": []}
    report_values: dict[str, list[Mapping[str, Any]]] = {"reference": [], "candidate": []}
    for key in sorted(expected_keys):
        pair = paired_records[key]
        for arm in ("reference", "candidate"):
            prefix = f"{arm}.world-{key[0]}-trial-{key[1]}"
            episode = report_episodes[arm][key]
            values = _report_episode_values(episode, prefix=prefix)
            report_values[arm].append(values)
            diagnosis = _mapping(pair.get(arm), f"analysis.paired_episode.{arm}")
            if (
                _integer(diagnosis.get("world_id"), f"{prefix}.analysis.world_id") != key[0]
                or _integer(diagnosis.get("trial_id"), f"{prefix}.analysis.trial_id") != key[1]
                or _integer(diagnosis.get("seed"), f"{prefix}.analysis.seed") != key[2]
            ):
                raise V9ScratchGateError(f"{prefix} analysis identity differs")
            for report_name, analysis_name in (
                ("success", "succeeded"),
                ("collided", "collided"),
                ("timed_out", "timed_out"),
                ("trial_started", "trial_started"),
                ("policy_stop_latched", "policy_stop_latched"),
            ):
                if values[report_name] is not _boolean(
                    diagnosis.get(analysis_name), f"{prefix}.analysis.{analysis_name}"
                ):
                    raise V9ScratchGateError(f"{prefix} report and analysis outcomes differ")
            liveness = _mapping(diagnosis.get("liveness"), f"{prefix}.analysis.liveness")
            startup_failed = _boolean(
                liveness.get("startup_failed"), f"{prefix}.analysis.liveness.startup_failed"
            )
            if startup_failed is not values["startup_failed"]:
                raise V9ScratchGateError(f"{prefix} startup evidence differs")
            maximum_stationary = _integer(
                liveness.get("maximum_consecutive_stationary_steps"),
                f"{prefix}.analysis.liveness.maximum_consecutive_stationary_steps",
            )
            dynamic = dynamics[arm][key]
            dynamic_stationary = _integer(
                dynamic.get("maximum_consecutive_stationary_steps"),
                f"{prefix}.analysis.dynamic.maximum_consecutive_stationary_steps",
            )
            if dynamic_stationary != maximum_stationary:
                raise V9ScratchGateError(f"{prefix} stationary evidence differs")
            dynamic_traveled = _finite(
                dynamic.get("post_integration_traveled_distance_m"),
                f"{prefix}.analysis.dynamic.post_integration_traveled_distance_m",
                minimum=0.0,
            )
            if not _equal_float(
                dynamic_traveled,
                float(values["post_integration_trace_traveled_distance_m"]),
            ):
                raise V9ScratchGateError(f"{prefix} traveled-distance evidence differs")
            dynamic_clearance = _finite(
                dynamic.get("minimum_signed_clearance_m"),
                f"{prefix}.analysis.dynamic.minimum_signed_clearance_m",
            )
            if not _equal_float(dynamic_clearance, float(values["minimum_signed_clearance_m"])):
                raise V9ScratchGateError(f"{prefix} clearance evidence differs")
            failure_kind = diagnosis.get("failure_kind")
            if not isinstance(failure_kind, str) or not failure_kind:
                raise V9ScratchGateError(f"{prefix} failure_kind is invalid")
            if dynamic.get("failure_kind") != failure_kind:
                raise V9ScratchGateError(f"{prefix} dynamic failure kind differs")
            joined[arm].append(
                _EpisodeMetrics(
                    world_id=key[0],
                    trial_id=key[1],
                    seed=key[2],
                    success=bool(values["success"]),
                    collided=bool(values["collided"]),
                    timed_out=bool(values["timed_out"]),
                    trial_started=bool(values["trial_started"]),
                    startup_failed=startup_failed,
                    policy_stop_latched=bool(values["policy_stop_latched"]),
                    controller_latency_samples_ms=values["controller_latency_samples_ms"],
                    minimum_signed_clearance_m=dynamic_clearance,
                    maximum_goal_progress_m=float(values["maximum_goal_progress_m"]),
                    final_distance_to_goal_m=float(values["final_distance_to_goal_m"]),
                    goal_progress_efficiency=float(values["goal_progress_efficiency"]),
                    traveled_distance_m=float(values["traveled_distance_m"]),
                    post_integration_trace_traveled_distance_m=dynamic_traveled,
                    maximum_consecutive_stationary_steps=maximum_stationary,
                    yaw_only_action_count=_integer(
                        dynamic.get("yaw_only_action_count"),
                        f"{prefix}.analysis.dynamic.yaw_only_action_count",
                    ),
                    reverse_action_count=int(values["reverse_action_count"]),
                    certificate_violation_count=_integer(
                        dynamic.get("certificate_violation_count"),
                        f"{prefix}.analysis.dynamic.certificate_violation_count",
                    ),
                    failure_kind=failure_kind,
                )
            )

    paired_report = _mapping(report.get("paired_report"), "report.paired_report")
    _validate_report_aggregate(
        "reference",
        _mapping(paired_report.get("baseline"), "paired_report.baseline"),
        report_values["reference"],
    )
    _validate_report_aggregate(
        "candidate",
        _mapping(paired_report.get("candidate"), "paired_report.candidate"),
        report_values["candidate"],
    )
    frozen_joined = {arm: tuple(items) for arm, items in joined.items()}
    _validate_analysis_aggregates(analysis, frozen_joined)
    return frozen_joined, _mapping(analysis.get("summary"), "analysis.summary")


def _failure_count(items: Sequence[_EpisodeMetrics]) -> int:
    return sum(item.failure_kind in _LIVENESS_FAILURE_KINDS for item in items)


def _validate_analysis_aggregates(
    analysis: Mapping[str, Any],
    joined: Mapping[str, Sequence[_EpisodeMetrics]],
) -> None:
    summary = _mapping(analysis.get("summary"), "analysis.summary")
    reference_failures = _failure_count(joined["reference"])
    candidate_failures = _failure_count(joined["candidate"])
    expected_summary = {
        "pair_count": len(joined["candidate"]),
        "reference_liveness_failure_count": reference_failures,
        "candidate_liveness_failure_count": candidate_failures,
        "candidate_minus_reference_liveness_failure_count": (
            candidate_failures - reference_failures
        ),
        "label_independent_liveness_failure_count_reduction": (
            reference_failures - candidate_failures
        ),
        "reference_yaw_only_action_count": sum(
            item.yaw_only_action_count for item in joined["reference"]
        ),
        "candidate_yaw_only_action_count": sum(
            item.yaw_only_action_count for item in joined["candidate"]
        ),
    }
    for name, expected in expected_summary.items():
        parser = (
            _signed_integer
            if name
            in {
                "candidate_minus_reference_liveness_failure_count",
                "label_independent_liveness_failure_count_reduction",
            }
            else _integer
        )
        if parser(summary.get(name), f"analysis.summary.{name}") != expected:
            raise V9ScratchGateError(f"analysis.summary.{name} disagrees with episode evidence")

    taxonomy = _mapping(analysis.get("failure_taxonomy"), "analysis.failure_taxonomy")
    expected_taxonomy = {
        "pair_count": len(joined["candidate"]),
        "reference_startup_failure_count": sum(
            item.startup_failed for item in joined["reference"]
        ),
        "candidate_startup_failure_count": sum(
            item.startup_failed for item in joined["candidate"]
        ),
        "reference_policy_stop_latch_count": sum(
            item.policy_stop_latched for item in joined["reference"]
        ),
        "candidate_policy_stop_latch_count": sum(
            item.policy_stop_latched for item in joined["candidate"]
        ),
        "reference_maximum_consecutive_stationary_steps": max(
            item.maximum_consecutive_stationary_steps for item in joined["reference"]
        ),
        "candidate_maximum_consecutive_stationary_steps": max(
            item.maximum_consecutive_stationary_steps for item in joined["candidate"]
        ),
    }
    for name, expected in expected_taxonomy.items():
        if _integer(taxonomy.get(name), f"analysis.failure_taxonomy.{name}") != expected:
            raise V9ScratchGateError(
                f"analysis.failure_taxonomy.{name} disagrees with episode evidence"
            )


def _validate_gate(
    gate: Mapping[str, Any],
    *,
    available_world_ids: tuple[int, ...],
) -> tuple[dict[str, Any], tuple[int, ...]]:
    declared = dict(gate)
    unknown = sorted(set(declared) - _SUPPORTED_GATE_KEYS)
    if unknown:
        raise V9ScratchGateError(f"declarative gate contains unsupported keys: {unknown}")
    for name in (
        "accepted_for_next_training_stage_only_if_all_conditions_pass",
        "screening_can_never_authorize_development_holdout_or_deployment",
        "training_only",
    ):
        if declared.get(name) is not True:
            raise V9ScratchGateError(f"declarative gate must set {name}=true")
    raw_worlds = _sequence(declared.get("screen_world_ids"), "gate.screen_world_ids")
    screen_world_ids = tuple(
        _integer(value, f"gate.screen_world_ids[{position}]")
        for position, value in enumerate(raw_worlds)
    )
    if (
        not screen_world_ids
        or len(set(screen_world_ids)) != len(screen_world_ids)
        or tuple(sorted(screen_world_ids)) != screen_world_ids
        or any(world_id not in TRAINING_WORLD_IDS for world_id in screen_world_ids)
    ):
        raise V9ScratchGateError("gate.screen_world_ids must be unique sorted V9 training IDs")
    if screen_world_ids != available_world_ids:
        raise V9ScratchGateError("gate screen worlds differ from immutable evidence worlds")
    gate_id = declared.get("gate_id", "caller-declared-v9-training-scratch-gate")
    if not isinstance(gate_id, str) or not gate_id:
        raise V9ScratchGateError("gate.gate_id must be a nonempty string when provided")
    if "candidate_package_sha256" in declared:
        _valid_sha256(declared["candidate_package_sha256"], "gate.candidate_package_sha256")
    threshold_keys = (set(declared) & _GLOBAL_GATE_KEYS) | (
        set(declared) & set(_PER_WORLD_GATE_SPECS)
    )
    if not threshold_keys:
        raise V9ScratchGateError("declarative gate contains no metric thresholds")
    # This also rejects nested non-JSON values and all NaN/Infinity thresholds.
    _canonical_json_bytes(declared)
    return declared, screen_world_ids


def _check(
    checks: list[dict[str, Any]],
    *,
    check_id: str,
    actual: float,
    operator: str,
    threshold: float,
    source: str,
    world_id: int | None = None,
) -> None:
    operations = {
        "le": ("<=", actual <= threshold),
        "lt": ("<", actual < threshold),
        "ge": (">=", actual >= threshold),
        "gt": (">", actual > threshold),
    }
    symbol, passed = operations[operator]
    item: dict[str, Any] = {
        "check_id": check_id,
        "source": source,
        "operator": symbol,
        "actual": actual,
        "threshold": threshold,
        "passed": passed,
    }
    if world_id is not None:
        item["world_id"] = world_id
    checks.append(item)


def _threshold_number(gate: Mapping[str, Any], name: str) -> float:
    return _finite(gate.get(name), f"gate.{name}", minimum=0.0)


def _threshold_integer(gate: Mapping[str, Any], name: str) -> int:
    return _integer(gate.get(name), f"gate.{name}")


def _derive_metrics(
    episodes: Mapping[str, Sequence[_EpisodeMetrics]],
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    reference = episodes["reference"]
    candidate = episodes["candidate"]
    reference_samples = tuple(
        sample for episode in reference for sample in episode.controller_latency_samples_ms
    )
    candidate_samples = tuple(
        sample for episode in candidate for sample in episode.controller_latency_samples_ms
    )
    reference_p99 = _nearest_rank_p99(reference_samples)
    candidate_p99 = _nearest_rank_p99(candidate_samples)
    if reference_p99 == 0.0:
        if candidate_p99 != 0.0:
            raise V9ScratchGateError("candidate/reference controller p99 ratio is not finite")
        latency_ratio = 1.0
    else:
        latency_ratio = candidate_p99 / reference_p99
    global_metrics = {
        "pair_count": len(candidate),
        "candidate_success_count": sum(item.success for item in candidate),
        "candidate_collision_count": sum(item.collided for item in candidate),
        "candidate_startup_failure_count": sum(item.startup_failed for item in candidate),
        "candidate_policy_stop_latch_count": sum(
            item.policy_stop_latched for item in candidate
        ),
        "reference_controller_p99_ms": reference_p99,
        "candidate_controller_p99_ms": candidate_p99,
        "candidate_to_reference_controller_p99_ratio": latency_ratio,
        "candidate_minimum_signed_clearance_m": min(
            item.minimum_signed_clearance_m for item in candidate
        ),
        "candidate_observed_return_certificate_violation_count": sum(
            item.certificate_violation_count for item in candidate
        ),
        "candidate_mean_maximum_goal_progress_m": fmean(
            item.maximum_goal_progress_m for item in candidate
        ),
        "candidate_mean_final_distance_to_goal_m": fmean(
            item.final_distance_to_goal_m for item in candidate
        ),
        "candidate_mean_goal_progress_efficiency": fmean(
            item.goal_progress_efficiency for item in candidate
        ),
        "candidate_mean_traveled_distance_m": fmean(
            item.traveled_distance_m for item in candidate
        ),
        "candidate_yaw_only_action_count": sum(
            item.yaw_only_action_count for item in candidate
        ),
        "candidate_reverse_action_count": sum(item.reverse_action_count for item in candidate),
        "label_independent_liveness_failure_count_reduction": (
            _failure_count(reference) - _failure_count(candidate)
        ),
    }
    per_world: dict[int, dict[str, Any]] = {}
    for item in candidate:
        if item.world_id in per_world:
            raise V9ScratchGateError("per-world gates require one candidate trial per world")
        per_world[item.world_id] = {
            "trial_id": item.trial_id,
            "seed": item.seed,
            "maximum_consecutive_stationary_steps": (
                item.maximum_consecutive_stationary_steps
            ),
            "maximum_goal_progress_m": item.maximum_goal_progress_m,
            "final_distance_to_goal_m": item.final_distance_to_goal_m,
            "goal_progress_efficiency": item.goal_progress_efficiency,
            "traveled_distance_m": item.traveled_distance_m,
        }
    return global_metrics, per_world


def _apply_global_gates(
    gate: Mapping[str, Any],
    metrics: Mapping[str, Any],
    checks: list[dict[str, Any]],
) -> None:
    specs: dict[str, tuple[str, str, str, str]] = {
        "minimum_success_count": (
            "candidate_success_count",
            "ge",
            "integer",
            "report episode terminal fields",
        ),
        "maximum_candidate_collisions": (
            "candidate_collision_count",
            "le",
            "integer",
            "report episode terminal fields",
        ),
        "maximum_candidate_startup_failure_count": (
            "candidate_startup_failure_count",
            "le",
            "integer",
            "report/analysis startup fields",
        ),
        "maximum_candidate_policy_stop_latch_count": (
            "candidate_policy_stop_latch_count",
            "le",
            "integer",
            "label-independent published-action analysis",
        ),
        "maximum_candidate_reverse_action_count": (
            "candidate_reverse_action_count",
            "le",
            "integer",
            "report evaluator shield/action diagnostics",
        ),
        "maximum_controller_p99_latency_ms": (
            "candidate_controller_p99_ms",
            "le",
            "number",
            "report evaluator controller latency samples",
        ),
        "maximum_controller_p99_latency_ratio": (
            "candidate_to_reference_controller_p99_ratio",
            "le",
            "number",
            "report evaluator controller latency samples",
        ),
        "minimum_candidate_signed_body_clearance_m": (
            "candidate_minimum_signed_clearance_m",
            "ge",
            "number",
            "report evaluator plus post-integration analysis",
        ),
        "maximum_candidate_observed_return_certificate_violations": (
            "candidate_observed_return_certificate_violation_count",
            "le",
            "integer",
            "label-independent recertified action analysis",
        ),
        "minimum_label_independent_liveness_failure_count_reduction": (
            "label_independent_liveness_failure_count_reduction",
            "ge",
            "integer",
            "label-independent paired episode classifications",
        ),
        "minimum_mean_maximum_goal_progress_m": (
            "candidate_mean_maximum_goal_progress_m",
            "ge",
            "number",
            "report evaluator episode diagnostics",
        ),
        "minimum_mean_maximum_goal_progress_m_exclusive": (
            "candidate_mean_maximum_goal_progress_m",
            "gt",
            "number",
            "report evaluator episode diagnostics",
        ),
        "maximum_mean_final_distance_to_goal_m": (
            "candidate_mean_final_distance_to_goal_m",
            "le",
            "number",
            "report evaluator episode diagnostics",
        ),
        "maximum_mean_final_distance_to_goal_m_exclusive": (
            "candidate_mean_final_distance_to_goal_m",
            "lt",
            "number",
            "report evaluator episode diagnostics",
        ),
        "maximum_candidate_mean_final_distance_to_goal_m_exclusive": (
            "candidate_mean_final_distance_to_goal_m",
            "lt",
            "number",
            "report evaluator episode diagnostics",
        ),
        "minimum_mean_goal_progress_efficiency": (
            "candidate_mean_goal_progress_efficiency",
            "ge",
            "number",
            "derived evaluator progress / post-integration travel",
        ),
        "minimum_candidate_mean_goal_progress_efficiency": (
            "candidate_mean_goal_progress_efficiency",
            "ge",
            "number",
            "derived evaluator progress / post-integration travel",
        ),
        "minimum_mean_goal_progress_efficiency_exclusive": (
            "candidate_mean_goal_progress_efficiency",
            "gt",
            "number",
            "derived evaluator progress / post-integration travel",
        ),
        "maximum_mean_traveled_distance_m": (
            "candidate_mean_traveled_distance_m",
            "le",
            "number",
            "post-integration analysis",
        ),
        "maximum_yaw_only_action_count": (
            "candidate_yaw_only_action_count",
            "le",
            "integer",
            "label-independent published-action analysis",
        ),
    }
    for gate_name in sorted(set(gate) & _GLOBAL_GATE_KEYS):
        metric_name, operator, kind, source = specs[gate_name]
        threshold = (
            _threshold_integer(gate, gate_name)
            if kind == "integer"
            else _threshold_number(gate, gate_name)
        )
        _check(
            checks,
            check_id=gate_name,
            actual=metrics[metric_name],
            operator=operator,
            threshold=threshold,
            source=source,
        )


def _apply_per_world_gates(
    gate: Mapping[str, Any],
    per_world: Mapping[int, Mapping[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    for gate_name in sorted(set(gate) & set(_PER_WORLD_GATE_SPECS)):
        metric_name, operator, kind = _PER_WORLD_GATE_SPECS[gate_name]
        thresholds = _mapping(gate.get(gate_name), f"gate.{gate_name}")
        if not thresholds:
            raise V9ScratchGateError(f"gate.{gate_name} must not be empty")
        parsed: list[tuple[int, int | float]] = []
        for raw_world_id, raw_threshold in thresholds.items():
            if not isinstance(raw_world_id, str) or not raw_world_id.isdecimal():
                raise V9ScratchGateError(f"gate.{gate_name} world keys must be decimal strings")
            world_id = int(raw_world_id)
            if str(world_id) != raw_world_id or world_id not in per_world:
                raise V9ScratchGateError(f"gate.{gate_name} refers to an unavailable world")
            threshold: int | float = (
                _integer(raw_threshold, f"gate.{gate_name}.{raw_world_id}")
                if kind == "integer"
                else _finite(
                    raw_threshold,
                    f"gate.{gate_name}.{raw_world_id}",
                    minimum=0.0,
                )
            )
            parsed.append((world_id, threshold))
        for world_id, threshold in sorted(parsed):
            _check(
                checks,
                check_id=f"{gate_name}.world-{world_id}",
                actual=per_world[world_id][metric_name],
                operator=operator,
                threshold=threshold,
                source=(
                    "label-independent post-integration analysis"
                    if metric_name
                    in {"maximum_consecutive_stationary_steps", "traveled_distance_m"}
                    else "report evaluator episode diagnostics"
                ),
                world_id=world_id,
            )


def evaluate_training_scratch_gate(
    report_path: str | Path,
    analysis_path: str | Path,
    *,
    expected_report_sha256: str,
    expected_analysis_sha256: str,
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate immutable evidence and return a training-only gate decision.

    A false metric threshold is an ordinary result and is represented in
    ``checks``.  Malformed, mutable, aliased, mismatched, or internally
    inconsistent evidence raises ``V9ScratchGateError`` and yields no decision.
    """

    if not isinstance(gate, Mapping):
        raise V9ScratchGateError("declarative gate must be an object")
    report_artifact = _read_immutable_json(
        report_path,
        label="training report",
        expected_sha256=expected_report_sha256,
    )
    analysis_artifact = _read_immutable_json(
        analysis_path,
        label="label-independent analysis",
        expected_sha256=expected_analysis_sha256,
    )
    (
        run_id,
        report_pair,
        _analysis_pair,
        policy_bindings,
        analysis_policy_bindings_match_report,
    ) = _validate_top_level_contract(
        report_artifact,
        analysis_artifact,
    )
    episodes, _summary = _join_metrics(report_artifact.document, analysis_artifact.document)
    available_world_ids = tuple(item.world_id for item in episodes["candidate"])
    if tuple(sorted(available_world_ids)) != available_world_ids:
        raise V9ScratchGateError("candidate evidence worlds are not sorted")
    declared_gate, screen_world_ids = _validate_gate(
        gate,
        available_world_ids=available_world_ids,
    )
    declared_candidate_sha = declared_gate.get("candidate_package_sha256")
    if (
        declared_candidate_sha is not None
        and declared_candidate_sha != report_pair["candidate_package_sha256"]
    ):
        raise V9ScratchGateError("gate candidate package identity differs from evidence")
    metrics, per_world = _derive_metrics(episodes)
    checks: list[dict[str, Any]] = []
    _apply_global_gates(declared_gate, metrics, checks)
    _apply_per_world_gates(declared_gate, per_world, checks)
    gate_passed = all(item["passed"] for item in checks)
    gate_id = declared_gate.get("gate_id", "caller-declared-v9-training-scratch-gate")
    return {
        "schema_version": SCHEMA_VERSION,
        "result_id": GATE_RESULT_ID,
        "gate_id": gate_id,
        "gate_sha256": _sha256_bytes(_canonical_json_bytes(declared_gate)),
        "run_id": run_id,
        "evaluation_kind": TRAINING_EVALUATION_KIND,
        "source_report": {
            "path": str(report_artifact.path),
            "sha256": report_artifact.sha256,
            "size_bytes": len(report_artifact.raw),
        },
        "source_analysis": {
            "path": str(analysis_artifact.path),
            "sha256": analysis_artifact.sha256,
            "size_bytes": len(analysis_artifact.raw),
        },
        "policy_pair": {
            "reference_package_sha256": V8_REFERENCE_PACKAGE_SHA256,
            "candidate_package_sha256": report_pair["candidate_package_sha256"],
        },
        "screen_world_ids": list(screen_world_ids),
        "claims": {
            "official_score": False,
            "leaderboard": False,
            "promotion_evidence": False,
            "development_authorized": False,
            "holdout_authorized": False,
            "deployment_enabled": False,
            "accepted_for_next_training_stage": gate_passed,
        },
        "evidence_contract": {
            "immutable_hash_pinned_report_and_analysis": True,
            "report_aggregates_recomputed_from_episode_fields": True,
            "analysis_aggregates_recomputed_from_episode_evidence_fields": True,
            "report_analysis_episode_identity_join_exact": True,
            "policy_notes_read_or_used": False,
            "candidate_package_identity_pinned_by_gate": declared_candidate_sha is not None,
            "all_available_policy_bindings_verified": policy_bindings[
                "all_available_bindings_verified"
            ],
            "analysis_policy_bindings_match_report": analysis_policy_bindings_match_report,
            "lateral_action_channel_absent_from_v8_evidence_schema": True,
        },
        "policy_bindings": policy_bindings,
        "metrics": metrics,
        "per_world_metrics": {str(key): value for key, value in sorted(per_world.items())},
        "checks": checks,
        "check_count": len(checks),
        "failed_check_ids": [item["check_id"] for item in checks if not item["passed"]],
        "gate_passed": gate_passed,
    }


__all__ = [
    "GATE_RESULT_ID",
    "SCHEMA_VERSION",
    "V9ScratchGateError",
    "evaluate_training_scratch_gate",
]
