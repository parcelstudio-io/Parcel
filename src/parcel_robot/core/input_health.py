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
import threading  # ---- CARD HW-2 (task_40): CommissionedScanSource's latch lock ----
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum, IntEnum
from types import MappingProxyType
from typing import Protocol  # ---- CARD HW-2 (task_40): ScanEvidenceSource ----

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


# ---- CARD HW-2 go2-backend (scrum/20260822/task_40) ------------------------
#
# THE HOLE THIS FILLS. ``evidence_origin`` above stamps SIMULATION on every
# sample that rides a ``SimObservation`` — deliberately, because the carrier
# type is the authority (board D-1), and no string reaches PHYSICAL. That is
# right for pose and it is right for a simulated scan, but it left the tree
# with **no way for a real LiDAR to be believed at all**: HW-3's verifier
# measured a real Mid-360 band on a ``SimObservation`` latching
# ``SCAN: sim_fixture_forbidden`` under
# :func:`requirements_requiring_physical_inputs`, and
# ``control/base.py:CommissionedStateSource`` — the one typed-origin seam that
# existed — carries ``RobotMotionState`` (pose/feedback), not scans. This is
# the missing twin, and it is the W0-F/W1 follow-up ``evidence_origin``'s
# docstring names.
#
# WHAT IT DOES NOT DO. It does not let a *configuration* mint authority. The
# origin is a constructor argument that the PRODUCER declares by construction
# (``backends/go2.py``: the recorded-fixture source is REPLAY because it reads
# a file, the live source is PHYSICAL because it opens a socket), not a YAML
# key anyone can flip. A REPLAY scan therefore still latches under a physical
# requirements table — which is what the desktop measures, and the right
# answer.
#
# THE LATCH IS THE POINT, and it is copied from ``CommissionedStateSource``
# rather than reinvented: an ordering violation (a duplicate or regressed
# sequence, a receipt moving backwards, a session-epoch change) means the
# stream is no longer the stream that was commissioned, so every LATER read —
# including clean ones — reports ``payload_valid=False``, which the join above
# reads as ``payload_malformed`` -> ``LATCHED_STOP``. A latch that a single
# good tick can clear is not a latch (verdict RC-1c).


@dataclass(frozen=True)
class ScanDatum:
    """One scan sample, with the two clocks and the ordering key kept apart.

    ``captured_at`` is the HOST monotonic receipt — the clock the freshness
    check above is expressed in — and never the sensor's own device clock,
    which lives in ``source_time_ns`` unconverted for a later ``ClockMapper``
    to fuse. ``populated_bins``/``points_seen`` are HW-3's coverage evidence,
    carried for the log and read by nothing here.
    """

    captured_at: float
    sequence: int
    frame_id: str = "base_link"
    payload_valid: bool = True
    populated_bins: int = 0
    points_seen: int = 0
    source_time_ns: int | None = None
    #: The producer's boot/session identity. ``sequence`` is only comparable
    #: within one epoch, so a change of epoch is an ordering fault.
    session_epoch: str = ""


class ScanEvidenceSource(Protocol):
    """A source of scan evidence that DECLARES where its scans come from.

    ``origin`` is read with :func:`parcel_robot.control.base.declared_origin`
    at the read site, so a ``str`` attribute spelled ``"physical"`` is not a
    declaration and reads back as UNKNOWN.

    ``evidence`` takes the DATUM KEY it is being asked about -- in the runtime
    this is the ``SimObservation`` being graded -- so a join can never be handed
    the evidence of a different sweep. ``None`` means "I have nothing for that
    one", which leaves the caller's own stamp in place.
    """

    origin: EvidenceOrigin

    def evidence(self, key: object) -> InputEvidence | None: ...


class CommissionedScanSource:
    """Read-only, origin-declaring, order-checked view over a scan producer.

    The scan twin of ``control/base.py:CommissionedStateSource``. ``inner`` is
    anything with a callable ``latest_scan() -> ScanDatum | None``;
    ``Go2Backend`` is the first one.

    ``latest_scan()`` returning ``None`` means **no scan** — the sensor drained
    nothing, or the sweep measured too little to be a scan (HW-3's ``ranges_m
    == ()``). It becomes ``evidence() is None``, which the join reads as
    ``missing`` -> recoverable ``HOLD``. It is never a stubbed sample.
    """

    def __init__(
        self,
        inner: object,
        *,
        origin: EvidenceOrigin,
        session_epoch: str = "",
        fixture_label: str = "",
        name: str = "",
    ) -> None:
        if not isinstance(origin, EvidenceOrigin):
            raise TypeError("commissioned scan origin must be an EvidenceOrigin")
        if origin is EvidenceOrigin.UNKNOWN:
            raise ValueError("commissioning must declare a real origin; UNKNOWN is not one")
        if not callable(getattr(inner, "scan_datum_for", None)):
            raise TypeError("commissioned scan source must expose a callable scan_datum_for()")
        if not isinstance(session_epoch, str) or len(session_epoch) > 80:
            raise ValueError("session_epoch must be a short string")
        label = str(fixture_label or "")
        if origin in SYNTHETIC_ORIGINS and not label.strip():
            # The join latches an unlabeled fixture (``sim_fixture_unlabeled``).
            # Refusing here instead makes it a construction error with a name,
            # not a stop three layers away with none.
            raise ValueError(
                f"a {origin.value} scan source must name its fixture; an unlabeled "
                "fixture is refused by the health join anyway"
            )
        if origin is EvidenceOrigin.PHYSICAL and label.strip():
            # ``physical_input_has_fixture_label`` is a LATCHED_STOP above.
            raise ValueError("a physical scan source must not carry a fixture label")
        self._inner = inner
        self.origin = origin
        self.session_epoch = session_epoch
        self.fixture_label: str | None = label or None
        # Verifier finding F5: the NAME must be the producing source's
        # (``go2_live`` / ``go2_stage0_replay``), not the backend's bare
        # ``go2``, because it is what the latch record publishes and a reader
        # has to be able to tell a recording from a robot.
        self.name = str(name or getattr(inner, "name", "") or "commissioned_scan")
        self._lock = threading.Lock()
        self._last_sequence: int | None = None
        self._last_captured_at: float | None = None
        self._last_datum: ScanDatum | None = None
        self._latched_reason: str | None = None

    @property
    def latched_reason(self) -> str | None:
        """The ordering fault that latched this view, or ``None``."""

        return self._latched_reason

    def evidence(self, key: object) -> InputEvidence | None:
        """``InputEvidence`` for the sweep behind ``key``, or ``None``.

        ``key`` is the datum's own key -- in the runtime, the
        ``SimObservation`` being graded.
        """

        datum = self._inner.scan_datum_for(key)
        if datum is None:
            return None
        if not isinstance(datum, ScanDatum):
            # A producer that returns something else is a boundary defect, not
            # a transient gap: hand the join a sample it will latch on rather
            # than dropping the evidence (which would only HOLD).
            return InputEvidence(
                captured_at=float("nan"),
                frame_id="",
                payload_valid=False,
                origin=self.origin,
                fixture_label=self.fixture_label,
            )
        with self._lock:
            reason = self._latched_reason
            if reason is None:
                reason = self._ordering_fault(datum)
                if reason is None:
                    self._last_sequence = datum.sequence
                    self._last_captured_at = datum.captured_at
                    self._last_datum = datum
                else:
                    self._latched_reason = reason
        return InputEvidence(
            captured_at=datum.captured_at,
            frame_id=datum.frame_id,
            payload_valid=bool(datum.payload_valid) and reason is None,
            origin=self.origin,
            fixture_label=self.fixture_label,
        )

    def _ordering_fault(self, datum: ScanDatum) -> str | None:
        if datum.session_epoch and datum.session_epoch != self.session_epoch:
            return "session_epoch_mismatch"
        if self._last_sequence is not None:
            if datum.sequence == self._last_sequence:
                # RE-READING THE SAME DATUM IS NOT A FAULT, and an earlier
                # draft of this class got that wrong on the premise "the join
                # reads this once per tick". It does not, and the verifier
                # reproduced both ways it does not (finding H1):
                #
                #   * automatically -- when ``observe()`` raises (ONE corrupt
                #     Livox datagram is enough) the runtime keeps the previous
                #     ``SimObservation`` and joins on it again
                #     (``runtime.py:10347`` clears a local, not the attribute);
                #   * deliberately -- ``clear_input_health_latch``
                #     (``runtime.py:4786``, the operator's e-stop clear)
                #     re-joins on that same observation, so a duplicate fault
                #     here latched the very thing the operator was clearing,
                #     un-clearably, short of a process restart.
                #
                # So the exemption is exactly ``CommissionedStateSource``'s
                # (``control/base.py:175-191``) and for the same measured
                # reason: identity first, then full field equality for a source
                # that rebuilds equal values. A DIFFERENT datum carrying a
                # repeated sequence is still a producer defect and still
                # latches -- matching ``(sequence, captured_at)`` is not on its
                # own evidence of sameness.
                if datum is self._last_datum or datum == self._last_datum:
                    return None
                return "sequence_duplicate"
            if datum.sequence < self._last_sequence:
                return "sequence_reordered"
        if self._last_captured_at is not None and datum.captured_at < self._last_captured_at:
            return "receipt_regression"
        return None


# ---- END CARD HW-2 go2-backend ---------------------------------------------


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
    # ---- CARD HW-2 (task_40) ----
    "CommissionedScanSource",
    # ---- END CARD HW-2 ----
    "EvidenceOrigin",
    "HealthAction",
    "InputEvidence",
    "InputFault",
    "InputHealthVerdict",
    "RequiredInput",
    "RequiredInputSpec",
    # ---- CARD HW-2 (task_40) ----
    "ScanDatum",
    "ScanEvidenceSource",
    # ---- END CARD HW-2 ----
    "evaluate_input_health",
    "evidence_origin",
    "requirements_allowing_sim_fixtures",
    "requirements_requiring_physical_inputs",
]
