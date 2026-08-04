"""Label-independent liveness diagnostics for the BARN V9 experiment.

V8 classified shield stalls by parsing free-form policy notes.  An incomplete
scan label consequently hid a final all-ray hard stop.  This module treats the
published action and measured odometry as the evidence boundary.  Free-form
notes may be retained for debugging, but they never decide whether the robot
was translating or whether a safety layer vetoed a command.

The helpers are additive and evaluator-facing.  They do not alter Parcel's
controller, the frozen V8 evidence, or the BARN episode outcome definition.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Any


@dataclass(frozen=True, slots=True)
class LivenessConfig:
    """Frozen thresholds expressed in final-action and odometry units."""

    control_period_s: float = 0.1
    stationary_speed_epsilon_mps: float = 0.005
    stationary_odometry_epsilon_m: float = 0.025
    long_stall_steps: int = 50
    safe_escape_progress_m: float = 0.5
    safe_escape_minimum_clearance_m: float = 0.475

    def __post_init__(self) -> None:
        positive = (
            self.control_period_s,
            self.stationary_speed_epsilon_mps,
            self.stationary_odometry_epsilon_m,
            self.safe_escape_progress_m,
            self.safe_escape_minimum_clearance_m,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("liveness thresholds must be finite and positive")
        if (
            isinstance(self.long_stall_steps, bool)
            or not isinstance(self.long_stall_steps, int)
            or self.long_stall_steps < 2
        ):
            raise ValueError("long_stall_steps must be an integer of at least two")


@dataclass(frozen=True, slots=True)
class PublishedActionSample:
    """One evaluator-observed command with optional structured causal fields.

    ``requested_translation_mps`` and ``all_ray_scale_limit`` must come from a
    structured controller/shield decision.  A policy note is intentionally not
    represented because text cannot establish causal attribution.
    """

    step_index: int
    position_xy: tuple[float, float]
    published_vx_mps: float
    published_vy_mps: float
    published_yaw_rate_rps: float
    issued_by_policy: bool = True
    published_stop: bool = False
    collided: bool = False
    inside_success_region: bool = False
    certificate_satisfied: bool | None = None
    signed_clearance_m: float | None = None
    requested_translation_mps: float | None = None
    all_ray_scale_limit: float | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.step_index, bool)
            or not isinstance(self.step_index, int)
            or self.step_index < 0
        ):
            raise ValueError("step_index must be a non-negative integer")
        if not isinstance(self.position_xy, tuple) or len(self.position_xy) != 2:
            raise TypeError("position_xy must be a two-item tuple")
        numeric = (
            *self.position_xy,
            self.published_vx_mps,
            self.published_vy_mps,
            self.published_yaw_rate_rps,
        )
        if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in numeric):
            raise ValueError("published action and position values must be finite numbers")
        for name in (
            "issued_by_policy",
            "published_stop",
            "collided",
            "inside_success_region",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be boolean")
        if self.certificate_satisfied is not None and not isinstance(
            self.certificate_satisfied, bool
        ):
            raise TypeError("certificate_satisfied must be boolean or None")
        for name in (
            "signed_clearance_m",
            "requested_translation_mps",
            "all_ray_scale_limit",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(float(value))
            ):
                raise ValueError(f"{name} must be finite when present")
        if self.requested_translation_mps is not None and self.requested_translation_mps < 0.0:
            raise ValueError("requested_translation_mps must be non-negative")
        if self.all_ray_scale_limit is not None and not 0.0 <= self.all_ray_scale_limit <= 1.0:
            raise ValueError("all_ray_scale_limit must be in [0, 1]")

    @property
    def published_translation_mps(self) -> float:
        return math.hypot(self.published_vx_mps, self.published_vy_mps)


@dataclass(frozen=True, slots=True)
class StationaryRun:
    """A maximal run of nonterminal, near-zero final translation commands."""

    start_step: int
    end_step: int
    step_count: int
    duration_s: float
    displacement_m: float
    maximum_odometry_excursion_m: float
    maximum_translation_mps: float
    structured_shield_veto_steps: int
    yaw_only_steps: int
    is_long: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EpisodeLivenessReport:
    """Task-independent liveness summary for one episode."""

    issued_action_count: int
    stationary_action_count: int
    maximum_consecutive_stationary_steps: int
    long_stationary_run_count: int
    stationary_tail_steps: int
    structured_shield_veto_steps: int
    startup_failed: bool
    navigation_no_progress_latched: bool
    runs: tuple[StationaryRun, ...]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["runs"] = [run.as_dict() for run in self.runs]
        return result


@dataclass(frozen=True, slots=True)
class SafeEscapeWitness:
    """A candidate's independently safe progress after a reference stall."""

    reference_stall_start_step: int
    reference_stall_steps: int
    candidate_escape_step: int
    candidate_progress_m: float
    minimum_candidate_clearance_m: float
    all_candidate_certificates_satisfied: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_samples(samples: Sequence[PublishedActionSample]) -> tuple[PublishedActionSample, ...]:
    if isinstance(samples, (str, bytes)):
        raise TypeError("samples must be a sequence of PublishedActionSample values")
    result = tuple(samples)
    if any(not isinstance(sample, PublishedActionSample) for sample in result):
        raise TypeError("every sample must be a PublishedActionSample")
    steps = [sample.step_index for sample in result]
    if steps != sorted(steps) or len(set(steps)) != len(steps):
        raise ValueError("sample step indices must be strictly increasing")
    if any(current != previous + 1 for previous, current in pairwise(steps)):
        raise ValueError(
            "sample step indices must be consecutive; missing actions cannot count "
            "toward a stationary duration"
        )
    return result


def _is_stationary(sample: PublishedActionSample, config: LivenessConfig) -> bool:
    return (
        sample.issued_by_policy
        and sample.published_translation_mps < config.stationary_speed_epsilon_mps
        and not sample.published_stop
        and not sample.collided
        and not sample.inside_success_region
    )


def _is_structured_shield_veto(
    sample: PublishedActionSample,
    config: LivenessConfig,
) -> bool:
    """Return true only when structured pre/post-shield data proves a veto."""

    return (
        _is_stationary(sample, config)
        and sample.requested_translation_mps is not None
        and sample.requested_translation_mps >= config.stationary_speed_epsilon_mps
        and sample.all_ray_scale_limit is not None
        and sample.all_ray_scale_limit
        < config.stationary_speed_epsilon_mps / sample.requested_translation_mps
    )


def _stationary_run(
    samples: tuple[PublishedActionSample, ...],
    config: LivenessConfig,
) -> StationaryRun:
    first, last = samples[0], samples[-1]
    displacement = math.dist(first.position_xy, last.position_xy)
    maximum_excursion = max(
        math.dist(first.position_xy, sample.position_xy) for sample in samples
    )
    # Final-action zero alone establishes a command stall.  Odometry is a
    # strengthening check: meaningful displacement prevents a run from being
    # called long even if quantized commands were reported as near zero.
    is_long = (
        len(samples) >= config.long_stall_steps
        and maximum_excursion < config.stationary_odometry_epsilon_m
    )
    return StationaryRun(
        start_step=first.step_index,
        end_step=last.step_index,
        step_count=len(samples),
        duration_s=len(samples) * config.control_period_s,
        displacement_m=displacement,
        maximum_odometry_excursion_m=maximum_excursion,
        maximum_translation_mps=max(sample.published_translation_mps for sample in samples),
        structured_shield_veto_steps=sum(
            _is_structured_shield_veto(sample, config) for sample in samples
        ),
        yaw_only_steps=sum(
            abs(sample.published_yaw_rate_rps) > 1e-12 for sample in samples
        ),
        is_long=is_long,
    )


def analyze_episode_liveness(
    samples: Sequence[PublishedActionSample],
    *,
    trial_started: bool,
    navigation_no_progress_latched: bool,
    config: LivenessConfig | None = None,
) -> EpisodeLivenessReport:
    """Measure liveness without parsing controller or safety-note strings."""

    if not isinstance(trial_started, bool) or not isinstance(
        navigation_no_progress_latched, bool
    ):
        raise TypeError("episode state flags must be boolean")
    profile = config or LivenessConfig()
    actions = _validate_samples(samples)
    raw_runs: list[tuple[PublishedActionSample, ...]] = []
    current: list[PublishedActionSample] = []
    for sample in actions:
        if _is_stationary(sample, profile):
            current.append(sample)
        elif current:
            raw_runs.append(tuple(current))
            current = []
    if current:
        raw_runs.append(tuple(current))
    runs = tuple(_stationary_run(run, profile) for run in raw_runs)
    issued = tuple(sample for sample in actions if sample.issued_by_policy)
    stationary_count = sum(run.step_count for run in runs)
    last_issued_step = issued[-1].step_index if issued else None
    tail = next(
        (
            run.step_count
            for run in reversed(runs)
            if last_issued_step is not None and run.end_step == last_issued_step
        ),
        0,
    )
    return EpisodeLivenessReport(
        issued_action_count=len(issued),
        stationary_action_count=stationary_count,
        maximum_consecutive_stationary_steps=max(
            (run.step_count for run in runs), default=0
        ),
        long_stationary_run_count=sum(run.is_long for run in runs),
        stationary_tail_steps=tail,
        structured_shield_veto_steps=sum(
            _is_structured_shield_veto(sample, profile) for sample in issued
        ),
        startup_failed=not trial_started,
        navigation_no_progress_latched=navigation_no_progress_latched,
        runs=runs,
    )


def find_safe_escape_witness(
    reference_samples: Sequence[PublishedActionSample],
    candidate_samples: Sequence[PublishedActionSample],
    *,
    config: LivenessConfig | None = None,
) -> SafeEscapeWitness | None:
    """Find candidate progress after the first independently measured reference stall.

    Causal paired-observation equality belongs to the V9 promotion gate.  This
    helper establishes only the liveness/safety part of an escape witness.
    """

    profile = config or LivenessConfig()
    reference = _validate_samples(reference_samples)
    candidate = _validate_samples(candidate_samples)
    reference_report = analyze_episode_liveness(
        reference,
        trial_started=True,
        navigation_no_progress_latched=False,
        config=profile,
    )
    stall = next((run for run in reference_report.runs if run.is_long), None)
    if stall is None:
        return None
    candidate_by_step = {sample.step_index: sample for sample in candidate}
    start = candidate_by_step.get(stall.start_step)
    if start is None:
        return None
    safety_window: list[PublishedActionSample] = []
    for sample in candidate:
        if sample.step_index < stall.start_step:
            continue
        safety_window.append(sample)
        if sample.collided or sample.certificate_satisfied is not True:
            return None
        if (
            sample.signed_clearance_m is None
            or sample.signed_clearance_m + 1e-12
            < profile.safe_escape_minimum_clearance_m
        ):
            return None
        progress = math.dist(start.position_xy, sample.position_xy)
        if progress + 1e-12 >= profile.safe_escape_progress_m:
            return SafeEscapeWitness(
                reference_stall_start_step=stall.start_step,
                reference_stall_steps=stall.step_count,
                candidate_escape_step=sample.step_index,
                candidate_progress_m=progress,
                minimum_candidate_clearance_m=min(
                    float(item.signed_clearance_m) for item in safety_window
                ),
                all_candidate_certificates_satisfied=True,
            )
    return None


__all__ = [
    "EpisodeLivenessReport",
    "LivenessConfig",
    "PublishedActionSample",
    "SafeEscapeWitness",
    "StationaryRun",
    "analyze_episode_liveness",
    "find_safe_escape_witness",
]
