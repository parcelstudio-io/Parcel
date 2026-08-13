"""Pure fail-closed health join for translation-authorizing inputs.

The join uses one decision timestamp.  Pose, scan, and controller feedback
must all be present, finite, fresh, payload-valid, and in their commissioned
frames before translation is allowed.

Provenance is DECLARED and typed (:class:`EvidenceOrigin`), never inferred from
a producer's name.  Card W0-A retired the ``PHYSICAL_SOURCE_NAMES`` whitelist
that let an unattributed producer mint physical authority; there is now no
string, anywhere, that reaches :attr:`EvidenceOrigin.PHYSICAL`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum, IntEnum
from types import MappingProxyType

from parcel_robot.evidence_origin import SYNTHETIC_ORIGINS, EvidenceOrigin


class RequiredInput(str, Enum):
    POSE = "pose"
    SCAN = "scan"
    CONTROLLER_FEEDBACK = "controller_feedback"


# Card W0-A. ``EvidenceOrigin`` is DEFINED in the leaf module
# :mod:`parcel_robot.evidence_origin` and re-exported here, so the boundary
# layers (``control/``, and through them ``commissioning/``) can declare
# provenance without importing ``parcel_robot.core.__init__`` — which
# transitively pulls in ``brain`` and ``instructnav``. See that module's
# docstring for the measurement behind the split.


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
    # Card W0-A: the default was ``PHYSICAL``. Omitting the origin therefore
    # MINTED physical authority, which is the defect in its purest form. The
    # default is now the fail-closed one: a sample nobody attributed is
    # UNKNOWN, and UNKNOWN never authorizes anything.
    origin: object = EvidenceOrigin.UNKNOWN
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


def evidence_origin(producer_label: object) -> tuple[EvidenceOrigin, str | None]:
    """``(origin, fixture_label)`` for a sample carried on a ``SimObservation``.

    Board decision D-1 (``scrum/20260812/task_2/BOARD_DECISIONS.md``): authority
    comes from the CARRIER TYPE, not from a producer name. ``SimObservation`` is
    by definition the simulator observation contract, so every sample stamped
    through this helper is :attr:`EvidenceOrigin.SIMULATION` and the argument
    supplies ONLY the required non-empty ``fixture_label``. There is no string —
    not ``"physical"``, not ``""``, not ``"unknown"`` — that reaches
    :attr:`EvidenceOrigin.PHYSICAL` from here or from anywhere else.

    A physical pose/scan channel must therefore arrive as a typed source that
    *declares* ``PHYSICAL`` (see ``control.base.CommissionedStateSource``);
    migrating ``navigation/reactive_safety.py`` — the frozen consumer whose
    signature this preserves — onto that seam is a W0-F/W1 follow-up.

    An empty label is returned as-is rather than being repaired: it reads as an
    UNLABELED fixture downstream, which latches.
    """

    return EvidenceOrigin.SIMULATION, str(producer_label or "")


def requirements_allowing_sim_fixtures(
    requirements: Mapping[RequiredInput, RequiredInputSpec] = DEFAULT_REQUIRED_INPUTS,
) -> Mapping[RequiredInput, RequiredInputSpec]:
    """``requirements`` with LABELED sim fixtures permitted for every input.

    Only a deployment that is explicitly commissioned against a simulator may
    use this.  It relaxes *who may produce* a sample, never *what makes it
    healthy*: an unlabeled sim fixture still latches, and a physically
    commissioned deployment keeps :data:`DEFAULT_REQUIRED_INPUTS`, where a
    sim-labeled pose or controller-feedback sample is a ``LATCHED_STOP``.
    """

    return MappingProxyType(
        {
            required_input: replace(spec, sim_fixture_allowed=True)
            for required_input, spec in requirements.items()
        }
    )


def requirements_requiring_physical_inputs(
    requirements: Mapping[RequiredInput, RequiredInputSpec] = DEFAULT_REQUIRED_INPUTS,
) -> Mapping[RequiredInput, RequiredInputSpec]:
    """``requirements`` with EVERY fixture allowance withdrawn, including SCAN.

    Board decision D-2. :data:`DEFAULT_REQUIRED_INPUTS` is the *simulator*
    default and deliberately keeps ``SCAN.sim_fixture_allowed=True`` — that is
    the shipped behavior and it is preserved here untouched, to be migrated
    only deliberately. But the physical branch used to reuse that same table,
    so stub geometry was admitted on a physically commissioned deployment and
    only POSE/FEEDBACK dominating the join blocked translation.

    A physical deployment gets this table instead, on which no synthetic
    origin satisfies any requirement. Missing calibrated geometry then holds
    exactly (a recoverable ``HOLD``, from the missing branch) and *substituted*
    geometry latches — so no missing-scan/geometry path can emit physical
    translation on its own account rather than as a side effect.
    """

    return MappingProxyType(
        {
            required_input: replace(spec, sim_fixture_allowed=False)
            for required_input, spec in requirements.items()
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
    if not isinstance(sample.origin, EvidenceOrigin):
        return InputFault(required_input, "origin_malformed", HealthAction.LATCHED_STOP)
    if sample.origin is EvidenceOrigin.UNKNOWN:
        # Card W0-A / board D-3. An undeclared producer is not a physical one.
        # This LATCHES rather than HOLDS: an authority-bearing sample nobody
        # attributed is a boundary defect, not a transient gap, and a
        # default-constructed boundary object must never satisfy a join.
        return InputFault(required_input, "origin_unknown", HealthAction.LATCHED_STOP)
    if sample.origin in SYNTHETIC_ORIGINS:
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
    "SYNTHETIC_ORIGINS",
    "EvidenceOrigin",
    "HealthAction",
    "InputEvidence",
    "InputFault",
    "InputHealthVerdict",
    "RequiredInput",
    "RequiredInputSpec",
    "evaluate_input_health",
    "evidence_origin",
    "requirements_allowing_sim_fixtures",
    "requirements_requiring_physical_inputs",
]
