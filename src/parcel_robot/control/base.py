from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any, Protocol

from parcel_robot.contracts.navigation_snapshot_v2 import NavigationSnapshotV2
from parcel_robot.contracts.observation_carrier import ObservationCarrierV1
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.observation.carrier_view import carrier_view

from .models import ControllerCapabilities, FaultReason, RobotMotionState, TimedVelocitySetpoint


class RobotStateSource(Protocol):
    """READ-ONLY source of locally timestamped robot feedback.

    ``latest`` must be nonblocking and state sequence numbers must increase for
    every received sample; post-stop confirmation depends on that ordering.

    Card W0-A splits this from :class:`ObservationSink`. The runtime used to
    retain a state source only via ``isinstance(BufferedRobotStateSource)``,
    which discarded a ``UnitreeSportStateSource`` (a plain class) and left the
    input-health join with no physical feedback at all — while simultaneously
    using that one predicate to decide whether it could *write* simulator
    observations into the source. Reading feedback and writing simulated
    observations are now different capabilities behind different protocols.

    ``origin`` is the DECLARED provenance of everything this source produces.
    It is never inferred from ``name``; a source that declares nothing reads
    back as :attr:`EvidenceOrigin.UNKNOWN`, which is never physical authority.
    """

    name: str
    origin: EvidenceOrigin

    def start(self) -> None: ...

    def latest(self) -> RobotMotionState | None: ...

    def close(self) -> None: ...


class ObservationSink(Protocol):
    """SIMULATOR-ONLY write seam: synthesize feedback from an observation carrier.

    Only a source that is *fed by the simulator* implements this. A physical
    vendor source must not — its feedback comes from the robot, and writing a
    simulated observation into it would manufacture exactly the fake physical
    feedback the health join exists to reject. :func:`as_observation_sink`
    refuses to hand back a sink that declares a physical origin, so the rule
    holds even against a source that implements the method by mistake.
    """

    def update_observation(self, observation: ObservationCarrierV1) -> RobotMotionState: ...


def declared_origin(candidate: object) -> EvidenceOrigin:
    """The origin ``candidate`` DECLARES, or ``UNKNOWN``.

    Typed lookup only. A ``str`` attribute (even ``"physical"``) is not a
    declaration and reads back as ``UNKNOWN`` — there is no spelling of a
    string that reaches physical authority.
    """

    origin = getattr(candidate, "origin", None)
    return origin if isinstance(origin, EvidenceOrigin) else EvidenceOrigin.UNKNOWN


def is_robot_state_source(candidate: object) -> bool:
    """True when ``candidate`` can be READ for feedback, whatever its class."""

    return candidate is not None and callable(getattr(candidate, "latest", None))


def as_observation_sink(candidate: object) -> ObservationSink | None:
    """``candidate`` as a simulator observation sink, or ``None``.

    Structural, and refused outright for a source declaring a physical origin.
    """

    if not callable(getattr(candidate, "update_observation", None)):
        return None
    if declared_origin(candidate) is EvidenceOrigin.PHYSICAL:
        return None
    return candidate  # type: ignore[return-value]


class CommissionedStateSource:
    """Read-only, origin-declaring, order-checked view over a vendor source.

    This is the seam through which a physical vendor stream — e.g.
    ``UnitreeSportStateSource``, which declares nothing on its own — becomes
    boundary data a commissioned input-health join can accept. It does exactly
    three things, and deliberately not a fourth:

    1. stamps the commissioned :class:`EvidenceOrigin` and session epoch onto
       every datum, so provenance travels ON the data instead of being guessed
       from a producer name;
    2. preserves the vendor/source clock, the host receipt clock, and the
       sequence exactly as the vendor source produced them;
    3. LATCHES on an ordering violation — duplicate or regressed sequence, host
       receipt moving backward, session-epoch change, or a datum whose own
       declared origin contradicts the commissioning — by reporting the stream
       as :attr:`FaultReason.COMMS` from that point on. The health join reads
       that as ``payload_malformed`` -> ``LATCHED_STOP`` on EVERY later tick,
       including clean ones, which is what makes the latch a latch rather than
       an enum label (verdict RC-1c).

    It exposes no ``update_observation``: a commissioned source can never be
    written by simulator observations.
    """

    def __init__(
        self,
        inner: Any,
        *,
        origin: EvidenceOrigin,
        session_epoch: str = "",
    ) -> None:
        if not isinstance(origin, EvidenceOrigin):
            raise TypeError("commissioned origin must be an EvidenceOrigin")
        if origin is EvidenceOrigin.UNKNOWN:
            raise ValueError("commissioning must declare a real origin; UNKNOWN is not one")
        if not isinstance(session_epoch, str) or len(session_epoch) > 80:
            raise ValueError("session_epoch must be a short string")
        if not is_robot_state_source(inner):
            raise TypeError("commissioned source must expose a callable latest()")
        self._inner = inner
        self.origin = origin
        self.session_epoch = session_epoch
        self.name = str(getattr(inner, "name", "") or "commissioned")
        self._lock = threading.Lock()
        self._last_sequence: int | None = None
        self._last_received_at: float | None = None
        self._last_state: RobotMotionState | None = None
        self._latched_reason: str | None = None

    @property
    def latched_reason(self) -> str | None:
        """The ordering fault that latched this view, or ``None``."""

        return self._latched_reason

    def start(self) -> None:
        start = getattr(self._inner, "start", None)
        if callable(start):
            start()

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()

    def latest(self) -> RobotMotionState | None:
        state = self._inner.latest()
        if state is None or not isinstance(state, RobotMotionState):
            return None
        with self._lock:
            reason = self._latched_reason
            if reason is None:
                reason = self._ordering_fault(state)
                if reason is None:
                    self._last_sequence = state.sequence
                    self._last_received_at = state.received_at
                    self._last_state = state
                else:
                    self._latched_reason = reason
        return self._stamp(state, fault=reason)

    def _ordering_fault(self, state: RobotMotionState) -> str | None:
        if state.origin is not EvidenceOrigin.UNKNOWN and state.origin is not self.origin:
            return "origin_conflict"
        if state.session_epoch and state.session_epoch != self.session_epoch:
            return "session_epoch_mismatch"
        if self._last_sequence is not None:
            if state.sequence == self._last_sequence:
                # ``latest()`` is a POLL, not a queue pop: the runtime reads it
                # more than once per tick (the dispatch idle check and the
                # health join both call it), and re-reading the very same
                # buffered sample is normal — that, and ONLY that, is exempt.
                #
                # Fable audit item 1: matching ``(sequence, received_at)`` is
                # not on its own evidence of sameness. A probe swapped a
                # different payload under colliding keys and drew a clean
                # physical ALLOW. The shipped Unitree adapter stamps
                # ``received_at`` from a host monotonic clock and increments
                # ``sequence`` per message, so it cannot collide — but this
                # seam is public and W0-C's adapters are not written yet, so
                # the exemption now requires the datum to actually BE the one
                # already accepted (identity first, then full field equality
                # for a source that rebuilds equal values).
                if state is self._last_state or state == self._last_state:
                    return None
                return "sequence_duplicate"
            if state.sequence < self._last_sequence:
                return "sequence_reordered"
        if self._last_received_at is not None and state.received_at < self._last_received_at:
            return "receipt_regression"
        return None

    def _stamp(self, state: RobotMotionState, *, fault: str | None) -> RobotMotionState:
        if fault is None:
            return replace(state, origin=self.origin, session_epoch=self.session_epoch)
        return replace(
            state,
            origin=self.origin,
            session_epoch=self.session_epoch,
            fault_reason=FaultReason.COMMS,
            vendor_extra=(*state.vendor_extra, ("provenance_fault", fault)),
        )


class LocomotionController(Protocol):
    """Exclusive body-velocity controller owned by ``ControlManager``.

    Unitree Sport closes its fast gait/balance loop onboard. A future custom
    implementation can close a faster IMU/joint loop internally while keeping
    the same leased body-velocity input contract. Implementations must make
    ``stop`` and ``emergency_stop`` safe when an ``update`` is in flight; the
    manager invalidates that update and follows it with a compensating stop.

    ``activate`` must be passive (it must never initiate locomotion), bounded,
    and safe to follow immediately with ``stop`` or ``emergency_stop``. Every
    controller I/O method must be bounded and internally serialize access to
    its vendor transport. Those invariants let the manager latch an E-stop
    while slow activation is still returning and safely quiesce replacement
    controllers during shutdown.
    """

    name: str
    capabilities: ControllerCapabilities

    def activate(self) -> None: ...

    def update(
        self,
        target: TimedVelocitySetpoint,
        state: RobotMotionState,
        *,
        now: float,
    ) -> None: ...

    def stop(self, reason: str) -> None: ...

    def emergency_stop(self) -> None: ...

    def clear_emergency_stop(self) -> None: ...

    def close(self) -> None: ...


def update_sink_from_snapshot(
    sink: ObservationSink, snapshot: NavigationSnapshotV2
) -> RobotMotionState:
    """Card A4's V2 entry point for the simulator-only feedback sink.

    The sink's rule is unchanged, and it is why this is a helper rather than a
    widened annotation: only a simulator-fed source may be written to, so a
    snapshot whose base evidence declares a physical origin is refused here
    instead of manufacturing fake physical feedback further down.
    """

    if snapshot.base.header.origin is EvidenceOrigin.PHYSICAL:
        raise ValueError(
            "a physically-sourced snapshot must not be written into the simulator sink"
        )
    return sink.update_observation(carrier_view(snapshot))
