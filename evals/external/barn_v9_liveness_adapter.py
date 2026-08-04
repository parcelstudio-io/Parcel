"""Strict evidence adapter and paired liveness taxonomy for BARN V9.

The immutable V8 action artifact proves the final published action and its
independent certificate, but intentionally does not contain evaluator
odometry or the controller's pre-shield request.  This adapter joins a
*verified* artifact read result to explicit evaluator-owned step fields.  It
never substitutes the published action for the missing request and never
derives state from policy notes.

V9 currently reuses the verified V8 action-evidence format.  A future evidence
format must be admitted here through its verifier result explicitly; accepting
arbitrary record-like objects would silently discard the verification
boundary.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from .barn_v8_action_evidence import (
    V8_ACTION_EVIDENCE_FORMAT_ID,
    V8ActionEvidenceReadResult,
    V8ActionEvidenceRecord,
)
from .barn_v9_liveness import (
    EpisodeLivenessReport,
    LivenessConfig,
    PublishedActionSample,
    SafeEscapeWitness,
    analyze_episode_liveness,
    find_safe_escape_witness,
)


class LivenessEvidenceSchemaError(ValueError):
    """Raised when verified actions and evaluator-owned fields cannot be joined."""


FailureKind: TypeAlias = Literal[
    "success",
    "collision",
    "startup_timeout",
    "structured_shield_stall",
    "navigation_no_progress",
    "other_long_stationary_stall",
    "stopped_outside_goal",
    "timeout_without_long_stall",
    "incomplete_or_nonfailure",
]

_FAILURE_KINDS: tuple[FailureKind, ...] = (
    "success",
    "collision",
    "startup_timeout",
    "structured_shield_stall",
    "navigation_no_progress",
    "other_long_stationary_stall",
    "stopped_outside_goal",
    "timeout_without_long_stall",
    "incomplete_or_nonfailure",
)
_LIVENESS_FAILURE_KINDS: frozenset[FailureKind] = frozenset(
    {
        "startup_timeout",
        "structured_shield_stall",
        "navigation_no_progress",
        "other_long_stationary_stall",
        "stopped_outside_goal",
        "timeout_without_long_stall",
    }
)
_STEP_FIELD_NAMES = frozenset(
    {
        "step_index",
        "world_id",
        "trial_id",
        "seed",
        "arm",
        "position_xy",
        "inside_success_region",
        "collided",
        "trial_started",
        "navigation_no_progress_latched",
        "timed_out",
        "signed_clearance_m",
        "requested_vx_mps",
        "requested_vy_mps",
        "all_ray_scale_limit",
    }
)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LivenessEvidenceSchemaError(f"{name} must be a non-negative integer")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise LivenessEvidenceSchemaError(f"{name} must be boolean")
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LivenessEvidenceSchemaError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise LivenessEvidenceSchemaError(f"{name} must be finite")
    return result


def _optional_finite(value: object, name: str) -> float | None:
    return None if value is None else _finite(value, name)


@dataclass(frozen=True, slots=True)
class EvaluatorStepFields:
    """Evaluator-owned fields joined to one verified final-action record.

    Optional values must still be present explicitly in mapping input.  In
    particular, paired null request velocities and ``all_ray_scale_limit=None``
    mean that no structured pre-shield decision is available; omission means
    that the schema is incomplete.  Physical liveness remains measurable from
    verified final actions and evaluator odometry, but causal shield
    attribution then stays unavailable rather than being inferred.
    """

    step_index: int
    world_id: int
    trial_id: int
    seed: int
    arm: str
    position_xy: tuple[float, float]
    inside_success_region: bool
    collided: bool
    trial_started: bool
    navigation_no_progress_latched: bool
    timed_out: bool
    signed_clearance_m: float | None
    requested_vx_mps: float | None
    requested_vy_mps: float | None
    all_ray_scale_limit: float | None

    def __post_init__(self) -> None:
        for name in ("step_index", "world_id", "trial_id", "seed"):
            _integer(getattr(self, name), name)
        if self.arm not in {"reference", "candidate"}:
            raise LivenessEvidenceSchemaError("arm must be 'reference' or 'candidate'")
        if not isinstance(self.position_xy, tuple) or len(self.position_xy) != 2:
            raise LivenessEvidenceSchemaError("position_xy must be a two-item tuple")
        for index, value in enumerate(self.position_xy):
            _finite(value, f"position_xy[{index}]")
        for name in (
            "inside_success_region",
            "collided",
            "trial_started",
            "navigation_no_progress_latched",
            "timed_out",
        ):
            _boolean(getattr(self, name), name)
        _optional_finite(self.signed_clearance_m, "signed_clearance_m")
        requested_vx = _optional_finite(self.requested_vx_mps, "requested_vx_mps")
        requested_vy = _optional_finite(self.requested_vy_mps, "requested_vy_mps")
        if (requested_vx is None) != (requested_vy is None):
            raise LivenessEvidenceSchemaError(
                "requested_vx_mps and requested_vy_mps must both be present or both be null"
            )
        scale = _optional_finite(self.all_ray_scale_limit, "all_ray_scale_limit")
        if scale is not None and not 0.0 <= scale <= 1.0:
            raise LivenessEvidenceSchemaError("all_ray_scale_limit must be in [0, 1]")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EvaluatorStepFields:
        if not isinstance(value, Mapping):
            raise TypeError("evaluator step fields must be mappings or EvaluatorStepFields")
        missing = sorted(_STEP_FIELD_NAMES.difference(value))
        if missing:
            important = {"position_xy", "requested_vx_mps", "requested_vy_mps"}
            qualifier = " position/request" if important.intersection(missing) else ""
            raise LivenessEvidenceSchemaError(
                f"evaluator step schema is missing required{qualifier} fields: "
                f"{', '.join(missing)}; fields are never inferred from notes or final actions"
            )
        position = value["position_xy"]
        if isinstance(position, Sequence) and not isinstance(position, (str, bytes)):
            position = tuple(position)
        try:
            return cls(
                step_index=value["step_index"],  # type: ignore[arg-type]
                world_id=value["world_id"],  # type: ignore[arg-type]
                trial_id=value["trial_id"],  # type: ignore[arg-type]
                seed=value["seed"],  # type: ignore[arg-type]
                arm=value["arm"],  # type: ignore[arg-type]
                position_xy=position,  # type: ignore[arg-type]
                inside_success_region=value["inside_success_region"],  # type: ignore[arg-type]
                collided=value["collided"],  # type: ignore[arg-type]
                trial_started=value["trial_started"],  # type: ignore[arg-type]
                navigation_no_progress_latched=value["navigation_no_progress_latched"],  # type: ignore[arg-type]
                timed_out=value["timed_out"],  # type: ignore[arg-type]
                signed_clearance_m=value["signed_clearance_m"],  # type: ignore[arg-type]
                requested_vx_mps=value["requested_vx_mps"],  # type: ignore[arg-type]
                requested_vy_mps=value["requested_vy_mps"],  # type: ignore[arg-type]
                all_ray_scale_limit=value["all_ray_scale_limit"],  # type: ignore[arg-type]
            )
        except LivenessEvidenceSchemaError:
            raise
        except (TypeError, ValueError) as exc:
            raise LivenessEvidenceSchemaError(
                f"invalid evaluator fields for step {value.get('step_index')!r}: {exc}"
            ) from exc


StepFieldsInput: TypeAlias = EvaluatorStepFields | Mapping[str, object]


@dataclass(frozen=True, slots=True)
class EpisodeLivenessDiagnostics:
    """One complete structured episode diagnosis."""

    world_id: int
    trial_id: int
    seed: int
    arm: str
    failure_kind: FailureKind
    trial_started: bool
    succeeded: bool
    collided: bool
    timed_out: bool
    policy_stop_latched: bool
    navigation_no_progress_latched: bool
    structured_shield_long_run_count: int
    liveness: EpisodeLivenessReport
    samples: tuple[PublishedActionSample, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "trial_id": self.trial_id,
            "seed": self.seed,
            "arm": self.arm,
            "failure_kind": self.failure_kind,
            "trial_started": self.trial_started,
            "succeeded": self.succeeded,
            "collided": self.collided,
            "timed_out": self.timed_out,
            "policy_stop_latched": self.policy_stop_latched,
            "navigation_no_progress_latched": self.navigation_no_progress_latched,
            "structured_shield_long_run_count": self.structured_shield_long_run_count,
            "liveness": self.liveness.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class PairedEpisodeLivenessDiagnostics:
    """Reference/candidate liveness diagnosis for one matched evaluator world."""

    reference: EpisodeLivenessDiagnostics
    candidate: EpisodeLivenessDiagnostics
    transition: str
    safe_escape_witness: SafeEscapeWitness | None

    @property
    def pair_key(self) -> tuple[int, int, int]:
        return (self.reference.world_id, self.reference.trial_id, self.reference.seed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.reference.world_id,
            "trial_id": self.reference.trial_id,
            "seed": self.reference.seed,
            "transition": self.transition,
            "safe_escape_witness": (
                None if self.safe_escape_witness is None else self.safe_escape_witness.as_dict()
            ),
            "reference": self.reference.as_dict(),
            "candidate": self.candidate.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class PairedFailureTaxonomyReport:
    """Aggregate paired taxonomy derived only from final actions and structured state."""

    pair_count: int
    reference_counts: Mapping[str, int]
    candidate_counts: Mapping[str, int]
    transition_counts: Mapping[str, int]
    reference_long_stall_episode_count: int
    candidate_long_stall_episode_count: int
    reference_structured_shield_stall_episode_count: int
    candidate_structured_shield_stall_episode_count: int
    reference_startup_failure_count: int
    candidate_startup_failure_count: int
    reference_navigation_no_progress_latch_count: int
    candidate_navigation_no_progress_latch_count: int
    reference_policy_stop_latch_count: int
    candidate_policy_stop_latch_count: int
    reference_maximum_consecutive_stationary_steps: int
    candidate_maximum_consecutive_stationary_steps: int
    safe_escape_witness_count: int
    candidate_liveness_gain_count: int
    candidate_liveness_regression_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "pair_count": self.pair_count,
            "reference_counts": dict(self.reference_counts),
            "candidate_counts": dict(self.candidate_counts),
            "transition_counts": dict(self.transition_counts),
            "reference_long_stall_episode_count": self.reference_long_stall_episode_count,
            "candidate_long_stall_episode_count": self.candidate_long_stall_episode_count,
            "reference_structured_shield_stall_episode_count": (
                self.reference_structured_shield_stall_episode_count
            ),
            "candidate_structured_shield_stall_episode_count": (
                self.candidate_structured_shield_stall_episode_count
            ),
            "reference_startup_failure_count": self.reference_startup_failure_count,
            "candidate_startup_failure_count": self.candidate_startup_failure_count,
            "reference_navigation_no_progress_latch_count": (
                self.reference_navigation_no_progress_latch_count
            ),
            "candidate_navigation_no_progress_latch_count": (
                self.candidate_navigation_no_progress_latch_count
            ),
            "reference_policy_stop_latch_count": self.reference_policy_stop_latch_count,
            "candidate_policy_stop_latch_count": self.candidate_policy_stop_latch_count,
            "reference_maximum_consecutive_stationary_steps": (
                self.reference_maximum_consecutive_stationary_steps
            ),
            "candidate_maximum_consecutive_stationary_steps": (
                self.candidate_maximum_consecutive_stationary_steps
            ),
            "safe_escape_witness_count": self.safe_escape_witness_count,
            "candidate_liveness_gain_count": self.candidate_liveness_gain_count,
            "candidate_liveness_regression_count": self.candidate_liveness_regression_count,
        }


def _verified_records(
    evidence: V8ActionEvidenceReadResult,
) -> tuple[V8ActionEvidenceRecord, ...]:
    if not isinstance(evidence, V8ActionEvidenceReadResult):
        raise TypeError(
            "evidence must be a V8ActionEvidenceReadResult returned by the verified reader; "
            "bare or record-like action sequences are not accepted"
        )
    identity = evidence.identity
    records = evidence.records
    if identity.format_id != V8_ACTION_EVIDENCE_FORMAT_ID:
        raise LivenessEvidenceSchemaError("verified action evidence format is not admitted")
    if not records or identity.record_count != len(records):
        raise LivenessEvidenceSchemaError("verified evidence record count is inconsistent")
    if identity.root_record_sha256 != records[-1].record_sha256:
        raise LivenessEvidenceSchemaError("verified evidence root record is inconsistent")
    for record in records:
        if not isinstance(record, V8ActionEvidenceRecord):
            raise LivenessEvidenceSchemaError("verified evidence contains an unknown record type")
        expected = {
            "arm": identity.arm,
            "execution_order": identity.execution_order,
            "world_id": identity.world_id,
            "trial_id": identity.trial_id,
            "seed": identity.seed,
        }
        if any(getattr(record, name) != value for name, value in expected.items()):
            raise LivenessEvidenceSchemaError("verified evidence episode identity is inconsistent")
    return records


def _coerce_step_fields(values: Sequence[StepFieldsInput]) -> tuple[EvaluatorStepFields, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("evaluator_steps must be a sequence")
    result = tuple(
        value if isinstance(value, EvaluatorStepFields) else EvaluatorStepFields.from_mapping(value)
        for value in values
    )
    steps = [value.step_index for value in result]
    if len(set(steps)) != len(steps):
        raise LivenessEvidenceSchemaError("evaluator step indices must be unique")
    return result


def _require_monotonic_flag(fields: Sequence[EvaluatorStepFields], name: str) -> None:
    seen_true = False
    for field in fields:
        current = bool(getattr(field, name))
        if seen_true and not current:
            raise LivenessEvidenceSchemaError(f"{name} cannot return to false within an episode")
        seen_true = seen_true or current


def published_action_samples_from_verified_evidence(
    evidence: V8ActionEvidenceReadResult,
    evaluator_steps: Sequence[StepFieldsInput],
) -> tuple[PublishedActionSample, ...]:
    """Join one verified action artifact to an exact evaluator step relation.

    A bare V8 record is insufficient because its schema has neither measured
    position nor pre-shield request fields.  Missing, duplicate, extra, or
    identity-mismatched evaluator rows therefore fail closed.
    """

    records = _verified_records(evidence)
    fields = _coerce_step_fields(evaluator_steps)
    by_step = {field.step_index: field for field in fields}
    record_steps = {record.step_index for record in records}
    missing = sorted(record_steps.difference(by_step))
    extra = sorted(set(by_step).difference(record_steps))
    if missing or extra:
        raise LivenessEvidenceSchemaError(
            f"evaluator/action step relation must be one-to-one; missing={missing}, extra={extra}"
        )

    ordered_fields: list[EvaluatorStepFields] = []
    result: list[PublishedActionSample] = []
    for record in records:
        field = by_step[record.step_index]
        ordered_fields.append(field)
        for name in ("arm", "world_id", "trial_id", "seed"):
            if getattr(field, name) != getattr(record, name):
                raise LivenessEvidenceSchemaError(
                    f"evaluator/action identity mismatch at step {record.step_index}: {name}"
                )
        certificate_satisfied = record.certificate.observed_return_boundary_satisfied
        if not isinstance(certificate_satisfied, bool):
            raise LivenessEvidenceSchemaError("action certificate lacks a boolean verdict")
        result.append(
            PublishedActionSample(
                step_index=record.step_index,
                position_xy=field.position_xy,
                published_vx_mps=record.published_vx_mps,
                published_vy_mps=record.published_vy_mps,
                published_yaw_rate_rps=record.published_yaw_rate_rps,
                issued_by_policy=record.issued_by_policy,
                published_stop=record.published_stop,
                collided=field.collided,
                inside_success_region=field.inside_success_region,
                certificate_satisfied=certificate_satisfied,
                signed_clearance_m=field.signed_clearance_m,
                requested_translation_mps=(
                    None
                    if field.requested_vx_mps is None
                    else math.hypot(
                        field.requested_vx_mps,
                        field.requested_vy_mps or 0.0,
                    )
                ),
                all_ray_scale_limit=field.all_ray_scale_limit,
            )
        )

    for flag in (
        "trial_started",
        "navigation_no_progress_latched",
        "inside_success_region",
        "collided",
        "timed_out",
    ):
        _require_monotonic_flag(ordered_fields, flag)
    outcomes = (
        any(field.inside_success_region for field in ordered_fields),
        any(field.collided for field in ordered_fields),
        any(field.timed_out for field in ordered_fields),
    )
    if sum(outcomes) > 1:
        raise LivenessEvidenceSchemaError(
            "success, collision, and timeout terminal states are mutually exclusive"
        )
    return tuple(result)


def _classify_failure(
    *,
    succeeded: bool,
    collided: bool,
    timed_out: bool,
    policy_stop_latched: bool,
    report: EpisodeLivenessReport,
    structured_shield_long_run_count: int,
) -> FailureKind:
    if succeeded:
        return "success"
    if collided:
        return "collision"
    if report.startup_failed:
        return "startup_timeout"
    if structured_shield_long_run_count:
        return "structured_shield_stall"
    if report.navigation_no_progress_latched:
        return "navigation_no_progress"
    if report.long_stationary_run_count:
        return "other_long_stationary_stall"
    if policy_stop_latched:
        return "stopped_outside_goal"
    if timed_out:
        return "timeout_without_long_stall"
    return "incomplete_or_nonfailure"


def diagnose_verified_episode(
    evidence: V8ActionEvidenceReadResult,
    evaluator_steps: Sequence[StepFieldsInput],
    *,
    config: LivenessConfig | None = None,
) -> EpisodeLivenessDiagnostics:
    """Convert and classify one episode without inspecting policy-note text."""

    profile = config or LivenessConfig()
    samples = published_action_samples_from_verified_evidence(evidence, evaluator_steps)
    fields = _coerce_step_fields(evaluator_steps)
    fields_by_step = {field.step_index: field for field in fields}
    ordered = tuple(fields_by_step[sample.step_index] for sample in samples)
    trial_started = any(field.trial_started for field in ordered)
    no_progress = any(field.navigation_no_progress_latched for field in ordered)
    succeeded = any(field.inside_success_region for field in ordered)
    collided = any(field.collided for field in ordered)
    timed_out = any(field.timed_out for field in ordered)
    policy_stop_latched = any(sample.published_stop for sample in samples)
    report = analyze_episode_liveness(
        samples,
        trial_started=trial_started,
        navigation_no_progress_latched=no_progress,
        config=profile,
    )
    structured_long_runs = sum(
        run.is_long and run.structured_shield_veto_steps >= profile.long_stall_steps
        for run in report.runs
    )
    identity = evidence.identity
    return EpisodeLivenessDiagnostics(
        world_id=identity.world_id,
        trial_id=identity.trial_id,
        seed=identity.seed,
        arm=identity.arm,
        failure_kind=_classify_failure(
            succeeded=succeeded,
            collided=collided,
            timed_out=timed_out,
            policy_stop_latched=policy_stop_latched,
            report=report,
            structured_shield_long_run_count=structured_long_runs,
        ),
        trial_started=trial_started,
        succeeded=succeeded,
        collided=collided,
        timed_out=timed_out,
        policy_stop_latched=policy_stop_latched,
        navigation_no_progress_latched=no_progress,
        structured_shield_long_run_count=structured_long_runs,
        liveness=report,
        samples=samples,
    )


def diagnose_paired_episode(
    reference_evidence: V8ActionEvidenceReadResult,
    reference_steps: Sequence[StepFieldsInput],
    candidate_evidence: V8ActionEvidenceReadResult,
    candidate_steps: Sequence[StepFieldsInput],
    *,
    config: LivenessConfig | None = None,
) -> PairedEpisodeLivenessDiagnostics:
    """Diagnose a same-world reference/candidate pair and seek a safe escape."""

    profile = config or LivenessConfig()
    reference = diagnose_verified_episode(reference_evidence, reference_steps, config=profile)
    candidate = diagnose_verified_episode(candidate_evidence, candidate_steps, config=profile)
    if reference.arm != "reference" or candidate.arm != "candidate":
        raise LivenessEvidenceSchemaError(
            "paired diagnosis requires reference and candidate evidence arms"
        )
    reference_key = (reference.world_id, reference.trial_id, reference.seed)
    candidate_key = (candidate.world_id, candidate.trial_id, candidate.seed)
    if reference_key != candidate_key:
        raise LivenessEvidenceSchemaError("paired evidence world/trial/seed identities differ")
    witness = find_safe_escape_witness(
        reference.samples,
        candidate.samples,
        config=profile,
    )
    return PairedEpisodeLivenessDiagnostics(
        reference=reference,
        candidate=candidate,
        transition=f"{reference.failure_kind}->{candidate.failure_kind}",
        safe_escape_witness=witness,
    )


def _complete_counts(values: Sequence[FailureKind]) -> dict[str, int]:
    counts = Counter(values)
    return {kind: counts.get(kind, 0) for kind in _FAILURE_KINDS}


def aggregate_paired_failure_taxonomy(
    pairs: Sequence[PairedEpisodeLivenessDiagnostics],
) -> PairedFailureTaxonomyReport:
    """Aggregate paired liveness categories and label-independent diagnostics."""

    if isinstance(pairs, (str, bytes)) or not isinstance(pairs, Sequence):
        raise TypeError("pairs must be a sequence of PairedEpisodeLivenessDiagnostics")
    episodes = tuple(pairs)
    if any(not isinstance(pair, PairedEpisodeLivenessDiagnostics) for pair in episodes):
        raise TypeError("every pair must be a PairedEpisodeLivenessDiagnostics")
    keys = [pair.pair_key for pair in episodes]
    if len(set(keys)) != len(keys):
        raise LivenessEvidenceSchemaError("paired aggregate contains duplicate episode identities")

    reference = tuple(pair.reference for pair in episodes)
    candidate = tuple(pair.candidate for pair in episodes)
    transitions = Counter(pair.transition for pair in episodes)
    return PairedFailureTaxonomyReport(
        pair_count=len(episodes),
        reference_counts=_complete_counts([item.failure_kind for item in reference]),
        candidate_counts=_complete_counts([item.failure_kind for item in candidate]),
        transition_counts=dict(sorted(transitions.items())),
        reference_long_stall_episode_count=sum(
            item.liveness.long_stationary_run_count > 0 for item in reference
        ),
        candidate_long_stall_episode_count=sum(
            item.liveness.long_stationary_run_count > 0 for item in candidate
        ),
        reference_structured_shield_stall_episode_count=sum(
            item.structured_shield_long_run_count > 0 for item in reference
        ),
        candidate_structured_shield_stall_episode_count=sum(
            item.structured_shield_long_run_count > 0 for item in candidate
        ),
        reference_startup_failure_count=sum(item.liveness.startup_failed for item in reference),
        candidate_startup_failure_count=sum(item.liveness.startup_failed for item in candidate),
        reference_navigation_no_progress_latch_count=sum(
            item.navigation_no_progress_latched for item in reference
        ),
        candidate_navigation_no_progress_latch_count=sum(
            item.navigation_no_progress_latched for item in candidate
        ),
        reference_policy_stop_latch_count=sum(item.policy_stop_latched for item in reference),
        candidate_policy_stop_latch_count=sum(item.policy_stop_latched for item in candidate),
        reference_maximum_consecutive_stationary_steps=max(
            (item.liveness.maximum_consecutive_stationary_steps for item in reference),
            default=0,
        ),
        candidate_maximum_consecutive_stationary_steps=max(
            (item.liveness.maximum_consecutive_stationary_steps for item in candidate),
            default=0,
        ),
        safe_escape_witness_count=sum(pair.safe_escape_witness is not None for pair in episodes),
        candidate_liveness_gain_count=sum(
            pair.reference.failure_kind in _LIVENESS_FAILURE_KINDS
            and pair.candidate.failure_kind not in _LIVENESS_FAILURE_KINDS
            for pair in episodes
        ),
        candidate_liveness_regression_count=sum(
            pair.reference.failure_kind not in _LIVENESS_FAILURE_KINDS
            and pair.candidate.failure_kind in _LIVENESS_FAILURE_KINDS
            for pair in episodes
        ),
    )


__all__ = [
    "EpisodeLivenessDiagnostics",
    "EvaluatorStepFields",
    "FailureKind",
    "LivenessEvidenceSchemaError",
    "PairedEpisodeLivenessDiagnostics",
    "PairedFailureTaxonomyReport",
    "aggregate_paired_failure_taxonomy",
    "diagnose_paired_episode",
    "diagnose_verified_episode",
    "published_action_samples_from_verified_evidence",
]
