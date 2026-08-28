"""Disarmed product adapter for the Unix motion gateway.

This module closes the first, deliberately narrow, product-composition rung:
``RobotRuntime`` can receive a :class:`ControlManager` whose controller and
feedback source use
:class:`parcel_robot.bridge.gateway_client.MotionGatewayClientV1` over the real
``AF_UNIX``/``SOCK_SEQPACKET`` boundary.

It does **not** close the motion-enabled rung.  The adapter has no call site for
``MotionGatewayClientV1.acquire`` or ``MotionGatewayClientV1.command`` and
declares ``body_velocity=False``.  A non-zero setpoint is therefore refused by
``ControlManager`` before this controller is called, even if a future caller
tries to bypass that declaration and invokes :meth:`update` directly.  The
only authority-affecting packet this adapter can emit is a stop.

The gateway does not attest which ``SportPort`` is behind its V1 hello, so this
module makes no fake-versus-physical claim and declares feedback provenance
``UNKNOWN``.  That is intentional: the adapter is safe against either because
it never arms.  Desktop integration tests launch the existing fake Sport
gateway separately; vendor mode remains the gateway CLI's fail-closed concern.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from pathlib import Path

from parcel_robot.bridge.gateway_client import (
    ConnectResultV1,
    MotionGatewayClientV1,
    MotionStateV1,
    StopResultV1,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.models import VelocityCommand

from .models import (
    ControllerCapabilities,
    FaultReason,
    RobotMotionState,
    TimedVelocitySetpoint,
)

ClientFactory = Callable[..., MotionGatewayClientV1]


class DisarmedGatewayError(RuntimeError):
    """The non-authoritative gateway composition refused or lost its boundary."""


class _DisarmedGatewaySessionV1:
    """One serialized client shared by the controller and state source.

    ``MotionGatewayClientV1`` is a request/response transport, so interleaving a
    state response with a stop response would violate its typed protocol.  This
    lock is therefore also the product-side sole-writer boundary.  No method in
    this class can arm or command the gateway.
    """

    def __init__(
        self,
        socket_path: str | Path,
        *,
        writer_id: str,
        timeout_s: float,
        client_factory: ClientFactory,
    ) -> None:
        self._socket_path = Path(socket_path)
        self._writer_id = writer_id
        self._timeout_s = timeout_s
        self._client_factory = client_factory
        self._client: MotionGatewayClientV1 | None = None
        self._lock = threading.RLock()
        self._closed = False

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._client is not None

    def connect(self) -> None:
        """Connect and verify the gateway itself is currently disarmed."""

        with self._lock:
            if self._closed:
                raise DisarmedGatewayError("the disarmed gateway session is closed")
            if self._client is not None:
                return
            client = self._client_factory(
                self._socket_path,
                writer_id=self._writer_id,
                timeout_s=self._timeout_s,
            )
            try:
                self._require_disarmed_gateway(client)
            except Exception:
                client.close()
                raise
            self._client = client

    def reconnect(self, *, settle_timeout_s: float = 2.0) -> ConnectResultV1:
        """Explicitly reconnect, retaining the client's always-disarmed contract."""

        with self._lock:
            client = self._require_client()
            result = client.reconnect(settle_timeout_s=settle_timeout_s)
            try:
                if result.identity != client.identity:
                    raise DisarmedGatewayError(
                        "gateway reconnect identity disagrees with the live client"
                    )
                self._require_disarmed_gateway(client)
            except Exception:
                client.close()
                self._client = None
                raise
            return result

    def state(self) -> MotionStateV1:
        with self._lock:
            client = self._require_client()
            state = client.state()
            try:
                self._require_contained_state(client, state)
            except Exception:
                self._drop_client(client)
                raise
            return state

    def ensure_stopped(
        self,
        *,
        reason: str,
        emergency: bool,
        max_state_age_s: float,
    ) -> StopResultV1 | None:
        """Stop unless an ordinary stop is already witnessed at rest.

        A stop from a client that does not own a gateway lease intentionally
        latches the gateway.  Startup calls ``controller.stop('manager_start')``
        even though this adapter can never have moved it, so an ordinary stop
        may use a fresh DISARMED-and-stationary gateway state as its witness.
        Emergency stop is never elided: it always crosses the Unix boundary and
        latches the gateway, including while already disarmed.
        """

        with self._lock:
            client = self._require_client()
            if emergency:
                report = client.stop(reason=reason, emergency=True)
                if (
                    report.boot_epoch != client.identity.boot_epoch
                    or not report.confirmed_stationary
                ):
                    self._drop_client(client)
                    raise DisarmedGatewayError(
                        "gateway stop report violates epoch or stationary contract"
                    )
                return report
            before = self.state()
            already_stopped = (
                before.phase == "disarmed"
                and before.stationary
                and not before.lease_active
                and not before.writer_id
                and 0.0 <= float(before.state_age_ms) / 1000.0 <= max_state_age_s
            )
            if already_stopped:
                return None
            report = client.stop(reason=reason, emergency=False)
            if (
                report.boot_epoch != client.identity.boot_epoch
                or not report.confirmed_stationary
            ):
                self._drop_client(client)
                raise DisarmedGatewayError(
                    "gateway stop report violates epoch or stationary contract"
                )
            return report

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            client = self._client
            self._client = None
            if client is not None:
                client.close()

    def _require_client(self) -> MotionGatewayClientV1:
        client = self._client
        if client is None:
            raise DisarmedGatewayError("the disarmed motion gateway is not connected")
        return client

    def _drop_client(self, client: MotionGatewayClientV1) -> None:
        client.close()
        if self._client is client:
            self._client = None

    @staticmethod
    def _require_disarmed_gateway(client: MotionGatewayClientV1) -> None:
        """Fence on authoritative hello and state, not the client-local arm bit."""

        state = client.state()
        _DisarmedGatewaySessionV1._require_disarmed_state(client, state)

    @staticmethod
    def _require_disarmed_state(
        client: MotionGatewayClientV1,
        state: MotionStateV1,
    ) -> None:
        identity = client.identity
        if (
            client.armed
            or identity.phase != "disarmed"
            or state.phase != "disarmed"
            or state.boot_epoch != identity.boot_epoch
            or state.lease_active
            or bool(state.writer_id)
        ):
            raise DisarmedGatewayError(
                "gateway phase, epoch, or lease violates the disarmed contract"
            )

    @staticmethod
    def _require_contained_state(
        client: MotionGatewayClientV1,
        state: MotionStateV1,
    ) -> None:
        """Continuously fence identity/authority while accepting a safe latch."""

        identity = client.identity
        if (
            client.armed
            or identity.phase != "disarmed"
            or state.phase not in {"disarmed", "latched"}
            or state.boot_epoch != identity.boot_epoch
            or state.lease_active
            or bool(state.writer_id)
        ):
            raise DisarmedGatewayError(
                "gateway phase, epoch, or lease violates the disarmed contract"
            )


class DisarmedGatewayStateSourceV1:
    """Read-only gateway feedback with conservative host-clock freshness."""

    name = "motion_gateway_disarmed_state"
    origin = EvidenceOrigin.UNKNOWN

    def __init__(self, session: _DisarmedGatewaySessionV1) -> None:
        self._session = session
        self._closed = False

    def start(self) -> None:
        if self._closed:
            raise DisarmedGatewayError("the disarmed gateway state source is closed")
        self._session.connect()

    def latest(self) -> RobotMotionState | None:
        if self._closed or not self._session.connected:
            return None
        state = self._session.state()
        return self._adapt(state)

    def reconnect_disarmed(self, *, settle_timeout_s: float = 2.0) -> ConnectResultV1:
        """Operator/test recovery hook; reconnect never acquires authority."""

        if self._closed:
            raise DisarmedGatewayError("the disarmed gateway state source is closed")
        return self._session.reconnect(settle_timeout_s=settle_timeout_s)

    def close(self) -> None:
        self._closed = True
        self._session.close()

    @classmethod
    def _adapt(cls, state: MotionStateV1) -> RobotMotionState:
        received_now = time.monotonic()
        age_s = max(0.0, float(state.state_age_ms) / 1000.0)
        received_at = received_now - age_s
        if not math.isfinite(received_at):
            raise DisarmedGatewayError("gateway feedback age produced a non-finite timestamp")
        phase_fault = state.phase != "disarmed"
        return RobotMotionState(
            received_at=received_at,
            sequence=state.state_sequence,
            velocity=VelocityCommand(
                vx=state.vx_mps,
                vy=state.vy_mps,
                vyaw=state.vyaw_rad_s,
            ),
            source=cls.name,
            fault_reason=FaultReason.COMMS if phase_fault else FaultReason.NONE,
            vendor_extra=(
                ("gateway_boot_epoch", state.boot_epoch),
                ("gateway_phase", state.phase),
                ("gateway_writer_id", state.writer_id),
                ("gateway_last_stop_reason", state.last_stop_reason),
            ),
            origin=cls.origin,
            session_epoch=state.boot_epoch,
        )


class DisarmedGatewayControllerV1:
    """Stop-capable, permanently non-motion controller for product composition."""

    name = "motion_gateway_disarmed"
    capabilities = ControllerCapabilities(
        body_velocity=False,
        lateral_velocity=False,
        high_level_balance=False,
        low_level_joint_control=False,
        requires_stop_confirmation=True,
    )

    def __init__(
        self,
        session: _DisarmedGatewaySessionV1,
        *,
        state_timeout_s: float,
    ) -> None:
        self._session = session
        self._state_timeout_s = state_timeout_s
        self._active = False
        self._closed = False
        self._emergency_stopped = False
        self._last_stop: StopResultV1 | None = None

    @property
    def last_stop_result(self) -> StopResultV1 | None:
        return self._last_stop

    def activate(self) -> None:
        if self._closed:
            raise DisarmedGatewayError("the disarmed gateway controller is closed")
        self._session.connect()
        self._active = True

    def update(
        self,
        target: TimedVelocitySetpoint,
        state: RobotMotionState,
        *,
        now: float,
    ) -> None:
        """Defense in depth: no setpoint, including zero, crosses as a command."""

        del target, state, now
        raise DisarmedGatewayError(
            "motion_gateway_disarmed cannot send velocity; it has no acquire or command path"
        )

    def stop(self, reason: str) -> None:
        if not self._active or self._closed:
            return
        self._last_stop = self._session.ensure_stopped(
            reason=_bounded_reason(reason),
            emergency=False,
            max_state_age_s=self._state_timeout_s,
        )

    def emergency_stop(self) -> None:
        if not self._active or self._closed:
            return
        self._emergency_stopped = True
        self._last_stop = self._session.ensure_stopped(
            reason="emergency_stop",
            emergency=True,
            max_state_age_s=self._state_timeout_s,
        )

    def clear_emergency_stop(self) -> None:
        if self._closed:
            raise DisarmedGatewayError("the disarmed gateway controller is closed")
        if self._emergency_stopped:
            raise DisarmedGatewayError(
                "the gateway E-stop is latched; restart the gateway and rebuild the "
                "disarmed control manager instead of clearing authority in place"
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._active = False
        self._session.close()


def build_disarmed_gateway_pair(
    socket_path: str | Path,
    *,
    writer_id: str = "parcel-runtime",
    timeout_s: float = 2.0,
    state_timeout_s: float = 0.25,
    client_factory: ClientFactory = MotionGatewayClientV1.connect,
) -> tuple[DisarmedGatewayControllerV1, DisarmedGatewayStateSourceV1]:
    """Build the one shared-client controller/source pair used by the factory."""

    clean_writer = writer_id.strip()
    if not clean_writer or len(clean_writer) > 80:
        raise ValueError("motion gateway writer_id must be 1..80 non-whitespace characters")
    clean_path = Path(socket_path)
    if not clean_path.is_absolute():
        raise ValueError("motion gateway socket_path must be absolute")
    seconds = float(timeout_s)
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise ValueError("motion gateway timeout_s must be positive and finite")
    state_seconds = float(state_timeout_s)
    if not math.isfinite(state_seconds) or state_seconds <= 0.0:
        raise ValueError("motion gateway state_timeout_s must be positive and finite")
    session = _DisarmedGatewaySessionV1(
        clean_path,
        writer_id=clean_writer,
        timeout_s=seconds,
        client_factory=client_factory,
    )
    return (
        DisarmedGatewayControllerV1(session, state_timeout_s=state_seconds),
        DisarmedGatewayStateSourceV1(session),
    )


def _bounded_reason(reason: str) -> str:
    clean = " ".join(str(reason).split()) or "runtime_stop"
    return clean[:160]


__all__ = [
    "DisarmedGatewayControllerV1",
    "DisarmedGatewayError",
    "DisarmedGatewayStateSourceV1",
    "build_disarmed_gateway_pair",
]
