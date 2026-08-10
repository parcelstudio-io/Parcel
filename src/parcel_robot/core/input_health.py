"""Pure fail-closed health join for translation-authorizing inputs.

The join uses one decision timestamp.  Pose, scan, and controller feedback
must all be present, finite, fresh, payload-valid, and in their commissioned
frames before translation is allowed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, IntEnum
from types import MappingProxyType


class RequiredInput(str, Enum):
    POSE = "pose"
    SCAN = "scan"
    CONTROLLER_FEEDBACK = "controller_feedback"


class InputOrigin(str, Enum):
    PHYSICAL = "physical"
    SIM_FIXTURE = "sim_fixture"


class HealthAction(IntEnum):
    ALLOW = 0
    HOLD = 1
    LATCHED_STOP = 2


@dataclass(frozen=True)
class RequiredInputSpec:
    frame_id: str
    max_age_s: float
    sim_fixture_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.frame_id:
            raise ValueError("required input frame must be non-empty")
        if not math.isfinite(self.max_age_s) or self.max_age_s <= 0.0:
            raise ValueError("required input max age must be positive and finite")


@dataclass(frozen=True)
class InputEvidence:
    """One authority-bearing sample.

    Fields intentionally remain inspectable rather than raising in
    ``__post_init__``: malformed boundary objects must produce a fail-closed
    verdict, not escape the health join as an exception.
    """

    captured_at: object
    frame_id: object
    payload_valid: object = True
    origin: object = InputOrigin.PHYSICAL
    fixture_label: object = None


@dataclass(frozen=True)
class InputFault:
    required_input: RequiredInput
    reason: str
    action: HealthAction


@dataclass(frozen=True)
class InputHealthVerdict:
    action: HealthAction
    faults: tuple[InputFault, ...]

    @property
    def translation_allowed(self) -> bool:
        return self.action is HealthAction.ALLOW

    @property
    def stop_latched(self) -> bool:
        return self.action is HealthAction.LATCHED_STOP


DEFAULT_REQUIRED_INPUTS: Mapping[RequiredInput, RequiredInputSpec] = MappingProxyType(
    {
        RequiredInput.POSE: RequiredInputSpec(frame_id="odom", max_age_s=0.25),
        RequiredInput.SCAN: RequiredInputSpec(
            frame_id="base_link",
            max_age_s=0.25,
            sim_fixture_allowed=True,
        ),
        RequiredInput.CONTROLLER_FEEDBACK: RequiredInputSpec(
            frame_id="base_link",
            max_age_s=0.25,
        ),
    }
)


def evaluate_input_health(
    evidence: Mapping[RequiredInput, InputEvidence | None] | object,
    *,
    now: float,
    requirements: Mapping[RequiredInput, RequiredInputSpec] = DEFAULT_REQUIRED_INPUTS,
    future_tolerance_s: float = 0.05,
) -> InputHealthVerdict:
    """Join required inputs into one translation-authority verdict.

    Missing and stale evidence produce a recoverable ``HOLD``.  Malformed,
    future-dated, frame-inconsistent, or silently stubbed evidence produces a
    ``LATCHED_STOP``.  The most severe fault wins, and all faults are retained.
    """

    if (
        isinstance(now, bool)
        or not isinstance(now, (int, float))
        or not math.isfinite(float(now))
        or not math.isfinite(future_tolerance_s)
        or future_tolerance_s < 0.0
    ):
        return _global_latched_fault("decision_time_malformed")
    if not isinstance(evidence, Mapping):
        return _global_latched_fault("evidence_table_malformed")

    faults: list[InputFault] = []
    for required_input, spec in requirements.items():
        sample = evidence.get(required_input)
        fault = _fault_for(
            required_input,
            spec,
            sample,
            now=float(now),
            future_tolerance_s=future_tolerance_s,
        )
        if fault is not None:
            faults.append(fault)
    action = max((fault.action for fault in faults), default=HealthAction.ALLOW)
    return InputHealthVerdict(action=action, faults=tuple(faults))


def _fault_for(
    required_input: RequiredInput,
    spec: RequiredInputSpec,
    sample: object,
    *,
    now: float,
    future_tolerance_s: float,
) -> InputFault | None:
    if sample is None:
        return InputFault(required_input, "missing", HealthAction.HOLD)
    if not isinstance(sample, InputEvidence):
        return InputFault(required_input, "malformed", HealthAction.LATCHED_STOP)
    if (
        isinstance(sample.captured_at, bool)
        or not isinstance(sample.captured_at, (int, float))
        or not math.isfinite(float(sample.captured_at))
    ):
        return InputFault(required_input, "timestamp_malformed", HealthAction.LATCHED_STOP)
    age = now - float(sample.captured_at)
    if age < -future_tolerance_s:
        return InputFault(required_input, "timestamp_in_future", HealthAction.LATCHED_STOP)
    if age > spec.max_age_s:
        return InputFault(required_input, "stale", HealthAction.HOLD)
    if sample.payload_valid is not True:
        return InputFault(required_input, "payload_malformed", HealthAction.LATCHED_STOP)
    if not isinstance(sample.frame_id, str) or sample.frame_id != spec.frame_id:
        return InputFault(required_input, "frame_inconsistent", HealthAction.LATCHED_STOP)
    if not isinstance(sample.origin, InputOrigin):
        return InputFault(required_input, "origin_malformed", HealthAction.LATCHED_STOP)
    if sample.origin is InputOrigin.SIM_FIXTURE:
        if not spec.sim_fixture_allowed:
            return InputFault(required_input, "sim_fixture_forbidden", HealthAction.LATCHED_STOP)
        if not isinstance(sample.fixture_label, str) or not sample.fixture_label.strip():
            return InputFault(required_input, "sim_fixture_unlabeled", HealthAction.LATCHED_STOP)
    elif sample.fixture_label is not None:
        return InputFault(required_input, "physical_input_has_fixture_label", HealthAction.LATCHED_STOP)
    return None


def _global_latched_fault(reason: str) -> InputHealthVerdict:
    return InputHealthVerdict(
        action=HealthAction.LATCHED_STOP,
        faults=tuple(
            InputFault(required_input, reason, HealthAction.LATCHED_STOP)
            for required_input in RequiredInput
        ),
    )


__all__ = [
    "DEFAULT_REQUIRED_INPUTS",
    "HealthAction",
    "InputEvidence",
    "InputFault",
    "InputHealthVerdict",
    "InputOrigin",
    "RequiredInput",
    "RequiredInputSpec",
    "evaluate_input_health",
]
