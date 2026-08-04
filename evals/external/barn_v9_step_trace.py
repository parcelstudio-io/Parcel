"""Additive post-integration evidence for the exact sensor-faithful BARN runner.

The established evaluator exposes only a bounded diagnostic trace.  V9 needs
one evaluator-owned pose and swept-clearance record for every published action
without changing that evaluator.  This module temporarily wraps its exact
integration function, calls :class:`SensorFaithfulBarnRunner` unchanged, and
restores the original function in ``finally``.

Patching a module global is process-wide, so all uses of this wrapper are
serialized by a lock.  Direct uninstrumented runner calls made concurrently by
other code cannot be protected; callers must not mix those with traced runs in
the same process.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from . import barn_sensor_faithful as _evaluator
from .barn_ros2_adapter import BarnRos2Policy
from .barn_sensor_faithful import (
    SensorFaithfulBarnRunner,
    SensorFaithfulEpisodeResult,
    V8EpisodeEvidenceCaptureSpec,
)
from .barn_v8_action_evidence import V8ActionEvidenceBuilder

V9_STEP_TRACE_SCHEMA_ID = "parcel-barn-v9-post-integration-step-trace-v1"
V9_STEP_TRACE_SCHEMA_VERSION = 1

_STEP_FIELDS = frozenset(
    {
        "step_index",
        "post_step_position_xy",
        "post_step_heading_rad",
        "collided",
        "swept_clearance_m",
        "inside_success_region",
        "trial_started",
        "timed_out",
        "requested_vx_mps",
        "requested_vy_mps",
        "all_ray_scale_limit",
    }
)
_TRACE_FIELDS = frozenset(
    {
        "schema_id",
        "schema_version",
        "world_id",
        "control_period_s",
        "records",
    }
)

_INTEGRATION_PATCH_LOCK = threading.Lock()


class V9StepTraceError(RuntimeError):
    """Raised when temporary instrumentation or trace parity fails closed."""


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V9StepTraceError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise V9StepTraceError(f"{name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class V9PostIntegrationStep:
    """Evaluator-owned state immediately after one exact integration call."""

    step_index: int
    post_step_position_xy: tuple[float, float]
    post_step_heading_rad: float
    collided: bool
    swept_clearance_m: float | None
    inside_success_region: bool
    trial_started: bool
    timed_out: bool = False
    # The integration boundary cannot observe controller-private pre-shield
    # values.  Null is evidence of unavailability, not a reconstructed value.
    requested_vx_mps: None = None
    requested_vy_mps: None = None
    all_ray_scale_limit: None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.step_index, bool)
            or not isinstance(self.step_index, int)
            or self.step_index < 0
        ):
            raise V9StepTraceError("step_index must be a non-negative integer")
        if (
            not isinstance(self.post_step_position_xy, tuple)
            or len(self.post_step_position_xy) != 2
        ):
            raise V9StepTraceError("post_step_position_xy must be a two-item tuple")
        for index, value in enumerate(self.post_step_position_xy):
            _finite(value, f"post_step_position_xy[{index}]")
        _finite(self.post_step_heading_rad, "post_step_heading_rad")
        if self.swept_clearance_m is not None:
            _finite(self.swept_clearance_m, "swept_clearance_m")
        for name in ("collided", "inside_success_region", "trial_started", "timed_out"):
            if not isinstance(getattr(self, name), bool):
                raise V9StepTraceError(f"{name} must be boolean")
        if any(
            value is not None
            for value in (
                self.requested_vx_mps,
                self.requested_vy_mps,
                self.all_ray_scale_limit,
            )
        ):
            raise V9StepTraceError(
                "the observational integration trace cannot contain inferred shield fields"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "post_step_position_xy": list(self.post_step_position_xy),
            "post_step_heading_rad": self.post_step_heading_rad,
            "collided": self.collided,
            "swept_clearance_m": self.swept_clearance_m,
            "inside_success_region": self.inside_success_region,
            "trial_started": self.trial_started,
            "timed_out": self.timed_out,
            "requested_vx_mps": None,
            "requested_vy_mps": None,
            "all_ray_scale_limit": None,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> V9PostIntegrationStep:
        """Parse one exact JSON trace row without accepting schema drift."""

        if not isinstance(value, Mapping):
            raise TypeError("V9 post-integration step must be a mapping")
        if set(value) != _STEP_FIELDS:
            missing = sorted(_STEP_FIELDS.difference(value))
            extra = sorted(set(value).difference(_STEP_FIELDS))
            raise V9StepTraceError(
                f"post-integration step fields are not exact; missing={missing}, extra={extra}"
            )
        position = value["post_step_position_xy"]
        if isinstance(position, Sequence) and not isinstance(position, (str, bytes)):
            position = tuple(position)
        try:
            return cls(
                step_index=value["step_index"],  # type: ignore[arg-type]
                post_step_position_xy=position,  # type: ignore[arg-type]
                post_step_heading_rad=value["post_step_heading_rad"],  # type: ignore[arg-type]
                collided=value["collided"],  # type: ignore[arg-type]
                swept_clearance_m=value["swept_clearance_m"],  # type: ignore[arg-type]
                inside_success_region=value["inside_success_region"],  # type: ignore[arg-type]
                trial_started=value["trial_started"],  # type: ignore[arg-type]
                timed_out=value["timed_out"],  # type: ignore[arg-type]
                requested_vx_mps=value["requested_vx_mps"],  # type: ignore[arg-type]
                requested_vy_mps=value["requested_vy_mps"],  # type: ignore[arg-type]
                all_ray_scale_limit=value["all_ray_scale_limit"],  # type: ignore[arg-type]
            )
        except V9StepTraceError:
            raise
        except (TypeError, ValueError) as error:
            raise V9StepTraceError(f"invalid post-integration step: {error}") from error


@dataclass(frozen=True, slots=True)
class V9PostIntegrationTrace:
    """Deterministic, JSON-safe records for one evaluator episode."""

    world_id: int
    control_period_s: float
    records: tuple[V9PostIntegrationStep, ...]
    schema_id: str = V9_STEP_TRACE_SCHEMA_ID
    schema_version: int = V9_STEP_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.world_id, bool) or not isinstance(self.world_id, int):
            raise V9StepTraceError("world_id must be an integer")
        if self.world_id < 0:
            raise V9StepTraceError("world_id must be non-negative")
        period = _finite(self.control_period_s, "control_period_s")
        if period <= 0.0:
            raise V9StepTraceError("control_period_s must be positive")
        if self.schema_id != V9_STEP_TRACE_SCHEMA_ID:
            raise V9StepTraceError("step trace schema_id is invalid")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != V9_STEP_TRACE_SCHEMA_VERSION
        ):
            raise V9StepTraceError("step trace schema_version is invalid")
        if any(not isinstance(record, V9PostIntegrationStep) for record in self.records):
            raise V9StepTraceError("records must contain V9PostIntegrationStep values")
        steps = tuple(record.step_index for record in self.records)
        if steps != tuple(range(len(self.records))):
            raise V9StepTraceError("post-integration records must cover every step exactly once")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "world_id": self.world_id,
            "control_period_s": self.control_period_s,
            "records": [record.as_dict() for record in self.records],
        }

    def canonical_json_bytes(self) -> bytes:
        return json.dumps(
            self.as_dict(),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json_bytes()).hexdigest()

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> V9PostIntegrationTrace:
        """Parse an exact serialized trace and re-run every invariant."""

        if not isinstance(value, Mapping):
            raise TypeError("V9 post-integration trace must be a mapping")
        if set(value) != _TRACE_FIELDS:
            missing = sorted(_TRACE_FIELDS.difference(value))
            extra = sorted(set(value).difference(_TRACE_FIELDS))
            raise V9StepTraceError(
                f"post-integration trace fields are not exact; missing={missing}, extra={extra}"
            )
        records = value["records"]
        if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
            raise V9StepTraceError("post-integration trace records must be a sequence")
        try:
            return cls(
                world_id=value["world_id"],  # type: ignore[arg-type]
                control_period_s=value["control_period_s"],  # type: ignore[arg-type]
                records=tuple(V9PostIntegrationStep.from_mapping(item) for item in records),
                schema_id=value["schema_id"],  # type: ignore[arg-type]
                schema_version=value["schema_version"],  # type: ignore[arg-type]
            )
        except V9StepTraceError:
            raise
        except (TypeError, ValueError) as error:
            raise V9StepTraceError(f"invalid post-integration trace: {error}") from error

    def adapter_step_rows(
        self,
        evidence_capture: V8EpisodeEvidenceCaptureSpec,
        *,
        navigation_no_progress_latch_step: int | None,
    ) -> tuple[dict[str, object], ...]:
        """Return the explicit evaluator relation consumed by the V9 adapter.

        Navigation failure cause is not visible at integration time, so the
        caller must supply a structured latch step or explicitly supply
        ``None``.  Controller request and shield scale remain explicit nulls.
        """

        if not isinstance(evidence_capture, V8EpisodeEvidenceCaptureSpec):
            raise TypeError("evidence_capture must be a V8EpisodeEvidenceCaptureSpec")
        if evidence_capture.world_id != self.world_id:
            raise V9StepTraceError("trace and action-evidence worlds differ")
        if navigation_no_progress_latch_step is not None:
            if (
                isinstance(navigation_no_progress_latch_step, bool)
                or not isinstance(navigation_no_progress_latch_step, int)
                or navigation_no_progress_latch_step < 0
            ):
                raise V9StepTraceError(
                    "navigation_no_progress_latch_step must be non-negative or None"
                )
            if navigation_no_progress_latch_step >= len(self.records):
                raise V9StepTraceError("navigation latch step is absent from the trace")
        return tuple(
            {
                "step_index": record.step_index,
                "world_id": evidence_capture.world_id,
                "trial_id": evidence_capture.trial_id,
                "seed": evidence_capture.seed,
                "arm": evidence_capture.arm,
                "position_xy": list(record.post_step_position_xy),
                "inside_success_region": record.inside_success_region,
                "collided": record.collided,
                "trial_started": record.trial_started,
                "navigation_no_progress_latched": (
                    navigation_no_progress_latch_step is not None
                    and record.step_index >= navigation_no_progress_latch_step
                ),
                "timed_out": record.timed_out,
                "signed_clearance_m": record.swept_clearance_m,
                "requested_vx_mps": None,
                "requested_vy_mps": None,
                "all_ray_scale_limit": None,
            }
            for record in self.records
        )


@dataclass(frozen=True, slots=True)
class SensorFaithfulEpisodeWithV9Trace:
    """Exact evaluator result plus additive V9 trace and optional V8 actions."""

    result: SensorFaithfulEpisodeResult
    step_trace: V9PostIntegrationTrace
    action_evidence: V8ActionEvidenceBuilder | None = None


def deterministic_episode_result_payload(
    result: SensorFaithfulEpisodeResult,
) -> dict[str, Any]:
    """Return all deterministic evaluator outputs, excluding wall-clock latency."""

    if not isinstance(result, SensorFaithfulEpisodeResult):
        raise TypeError("result must be a SensorFaithfulEpisodeResult")
    payload = asdict(result)
    sensor = payload.get("sensor_diagnostics")
    if not isinstance(sensor, dict):  # pragma: no cover - frozen result contract.
        raise V9StepTraceError("sensor diagnostics are malformed")
    sensor.pop("latency", None)
    return payload


def _finalize_trace(
    *,
    runner: SensorFaithfulBarnRunner,
    result: SensorFaithfulEpisodeResult,
    records: Sequence[V9PostIntegrationStep],
) -> V9PostIntegrationTrace:
    finalized = list(records)
    if finalized and result.timed_out:
        finalized[-1] = replace(finalized[-1], timed_out=True)
    if len(finalized) != result.steps:
        raise V9StepTraceError(
            f"integration trace/result step mismatch: {len(finalized)} != {result.steps}"
        )
    if finalized:
        last = finalized[-1]
        if last.post_step_position_xy != result.final_position_xy or not math.isclose(
            last.post_step_heading_rad,
            result.final_heading_rad,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise V9StepTraceError("integration trace final pose differs from evaluator result")
        if last.collided != result.collided:
            raise V9StepTraceError("integration trace collision differs from evaluator result")
        if last.inside_success_region != result.success:
            raise V9StepTraceError("integration trace success differs from evaluator result")
        if last.trial_started != result.trial_started:
            raise V9StepTraceError("integration trace trial state differs from evaluator result")
    world = getattr(runner, "_world", None)
    config = getattr(runner, "_config", None)
    if world is None or config is None:  # pragma: no cover - exact runner contract.
        raise V9StepTraceError("SensorFaithfulBarnRunner internals are unavailable")
    return V9PostIntegrationTrace(
        world_id=world.world_index,
        control_period_s=config.dt_s,
        records=tuple(finalized),
    )


def run_sensor_faithful_with_v9_step_trace(
    runner: SensorFaithfulBarnRunner,
    policy: BarnRos2Policy,
    *,
    evidence_capture: V8EpisodeEvidenceCaptureSpec | None = None,
) -> SensorFaithfulEpisodeWithV9Trace:
    """Call the exact runner while observing every integration result.

    The original module function is restored even when policy execution,
    integration, evidence capture, or trace validation raises.
    """

    if not isinstance(runner, SensorFaithfulBarnRunner):
        raise TypeError("runner must be a SensorFaithfulBarnRunner")
    if evidence_capture is not None and not isinstance(
        evidence_capture, V8EpisodeEvidenceCaptureSpec
    ):
        raise TypeError("evidence_capture must be a V8EpisodeEvidenceCaptureSpec or None")
    config = getattr(runner, "_config", None)
    if config is None:  # pragma: no cover - exact runner contract.
        raise V9StepTraceError("SensorFaithfulBarnRunner configuration is unavailable")

    records: list[V9PostIntegrationStep] = []
    trace_trial_started = False
    with _INTEGRATION_PATCH_LOCK:
        original_integrator = _evaluator._integrate_collision_terminal

        def traced_integrator(
            position: tuple[float, float],
            heading: float,
            velocity: float,
            yaw_rate: float,
            dt_s: float,
            cylinders: Sequence[_evaluator.CylinderObstacle],
            robot_radius_m: float,
        ) -> tuple[tuple[float, float], float, bool, float | None]:
            nonlocal trace_trial_started
            startup_crossing = (
                None
                if trace_trial_started
                else _evaluator._first_translation_threshold_crossing_s(
                    initial_position=_evaluator.OFFICIAL_START_XY,
                    step_position=position,
                    step_heading=heading,
                    velocity=velocity,
                    yaw_rate=yaw_rate,
                    dt_s=dt_s,
                    threshold_m=config.trial_start_translation_m,
                )
            )
            next_position, next_heading, collided, swept_clearance = original_integrator(
                position,
                heading,
                velocity,
                yaw_rate,
                dt_s,
                cylinders,
                robot_radius_m,
            )
            if not collided and startup_crossing is not None:
                trace_trial_started = True
            inside_success = (
                not collided
                and math.dist(
                    next_position,
                    _evaluator.OFFICIAL_GOAL_XY,
                )
                <= config.success_radius_m
            )
            records.append(
                V9PostIntegrationStep(
                    step_index=len(records),
                    post_step_position_xy=next_position,
                    post_step_heading_rad=next_heading,
                    collided=collided,
                    swept_clearance_m=swept_clearance,
                    inside_success_region=inside_success,
                    trial_started=trace_trial_started,
                )
            )
            return next_position, next_heading, collided, swept_clearance

        _evaluator._integrate_collision_terminal = traced_integrator
        try:
            if evidence_capture is None:
                result = runner.run(policy)
                action_evidence = None
            else:
                episode = runner.run_with_action_evidence(policy, evidence_capture)
                result = episode.result
                action_evidence = episode.action_evidence
        finally:
            _evaluator._integrate_collision_terminal = original_integrator

    trace = _finalize_trace(runner=runner, result=result, records=records)
    if action_evidence is not None and len(action_evidence.records) != len(trace.records):
        raise V9StepTraceError("action evidence and integration trace step counts differ")
    return SensorFaithfulEpisodeWithV9Trace(
        result=result,
        step_trace=trace,
        action_evidence=action_evidence,
    )


__all__ = [
    "V9_STEP_TRACE_SCHEMA_ID",
    "V9_STEP_TRACE_SCHEMA_VERSION",
    "SensorFaithfulEpisodeWithV9Trace",
    "V9PostIntegrationStep",
    "V9PostIntegrationTrace",
    "V9StepTraceError",
    "deterministic_episode_result_payload",
    "run_sensor_faithful_with_v9_step_trace",
]
