"""Controller and composition factory for a commissioned motion gateway."""

from __future__ import annotations

import math
from pathlib import Path

from parcel_robot.bridge.gateway_client import (
    ArmResultV1,
    CommandResultV1,
    ConnectResultV1,
    MotionGatewayClientV1,
    StopResultV1,
)
from parcel_robot.bridge.protocol import MAX_LOCAL_TTL_MS, GatewayHashesV1
from parcel_robot.evidence_origin import EvidenceOrigin

from .models import ControllerCapabilities, RobotMotionState, TimedVelocitySetpoint
from .motion_gateway_common import (
    ClientFactory,
    CommissionedGatewayError,
    bounded_identifier,
    bounded_reason,
    local_ttl,
)
from .motion_gateway_session import _CommissionedGatewaySessionV1
from .motion_gateway_state import CommissionedGatewayStateSourceV1

_COMMISSIONED_DISARMED_CAPABILITIES = ControllerCapabilities(
    body_velocity=False,
    lateral_velocity=False,
    high_level_balance=True,
    low_level_joint_control=False,
    requires_stop_confirmation=True,
)

_COMMISSIONED_ARMED_CAPABILITIES = ControllerCapabilities(
    body_velocity=True,
    lateral_velocity=True,
    high_level_balance=True,
    low_level_joint_control=False,
    requires_stop_confirmation=True,
)


class CommissionedGatewayControllerV1:
    """Motion-capable controller whose authority is always operator-explicit."""

    name = "motion_gateway_commissioned"

    def __init__(
        self,
        session: _CommissionedGatewaySessionV1,
        *,
        state_timeout_s: float,
        local_ttl_ms: int,
    ) -> None:
        self._session = session
        self._state_timeout_s = state_timeout_s
        self._local_ttl_ms = local_ttl_ms
        self._active = False
        self._closed = False
        self._emergency_stopped = False
        self._authority_owner_token: object | None = None
        self._last_arm: ArmResultV1 | None = None
        self._last_command: CommandResultV1 | None = None
        self._last_stop: StopResultV1 | None = None

    @property
    def armed(self) -> bool:
        return self._active and not self._closed and self._session.armed

    @property
    def capabilities(self) -> ControllerCapabilities:
        """Expose velocity capability only while explicit authority is live."""

        if self.armed and not self._emergency_stopped:
            return _COMMISSIONED_ARMED_CAPABILITIES
        return _COMMISSIONED_DISARMED_CAPABILITIES

    @property
    def last_arm_result(self) -> ArmResultV1 | None:
        return self._last_arm

    @property
    def last_command_result(self) -> CommandResultV1 | None:
        return self._last_command

    @property
    def last_stop_result(self) -> StopResultV1 | None:
        return self._last_stop

    def activate(self) -> None:
        """Connect passively.  Activation never acquires motion authority."""

        if self._closed:
            raise CommissionedGatewayError("the commissioned gateway controller is closed")
        self._session.connect()
        self._active = True

    def bind_authority_owner(self, owner_token: object) -> None:
        """Bind production arming to exactly one ControlManager instance."""

        if owner_token is None:
            raise TypeError("motion authority owner token cannot be None")
        if self._active or self._closed:
            raise CommissionedGatewayError(
                "motion authority owner must be bound before controller activation"
            )
        if (
            self._authority_owner_token is not None
            and self._authority_owner_token is not owner_token
        ):
            raise CommissionedGatewayError("motion authority already has a different owner")
        self._authority_owner_token = owner_token

    def arm(self, *, local_ttl_ms: int | None = None) -> ArmResultV1:
        """Low-level explicit arm used by commissioning and adapter tests.

        Production threaded control must use
        :meth:`~parcel_robot.control.manager.ControlManager.arm_and_set_target`;
        separating this call from target installation creates an empty-target
        stop race by design.
        """

        if self._authority_owner_token is not None:
            raise CommissionedGatewayError("a manager-owned controller must use arm_and_set_target")

        return self._arm(local_ttl_ms=local_ttl_ms)

    def _arm(self, *, local_ttl_ms: int | None = None) -> ArmResultV1:
        """Execute the adapter-local authority transaction after ownership checks."""

        if not self._active or self._closed:
            raise CommissionedGatewayError("activate the commissioned gateway before arming")
        if self._emergency_stopped:
            raise CommissionedGatewayError(
                "the gateway E-stop is latched; restart and rebuild before arming"
            )
        ttl_ms = self._local_ttl_ms if local_ttl_ms is None else local_ttl(local_ttl_ms)
        if ttl_ms > self._local_ttl_ms:
            raise ValueError("operator arm TTL cannot exceed the commissioned local_ttl_ms")
        self._last_arm = self._session.arm(local_ttl_ms=ttl_ms)
        return self._last_arm

    def acquire_motion_authority(self, owner_token: object) -> None:
        """Manager-owned arm hook; return only with verified live authority."""

        if self._authority_owner_token is None or owner_token is not self._authority_owner_token:
            raise CommissionedGatewayError("motion authority owner token does not match")
        result = self._arm()
        if not result.armed:
            raise CommissionedGatewayError(
                f"gateway refused motion authority: {result.reason or 'unspecified'}"
            )

    def reconnect_disarmed(self, *, settle_timeout_s: float = 2.0) -> ConnectResultV1:
        """Explicit recovery hook.  Its result is always locally disarmed."""

        if not self._active or self._closed:
            raise CommissionedGatewayError("activate the commissioned gateway before reconnecting")
        result = self._session.reconnect(settle_timeout_s=settle_timeout_s)
        self._last_arm = None
        self._last_command = None
        return result

    def update(
        self,
        target: TimedVelocitySetpoint,
        state: RobotMotionState,
        *,
        now: float,
    ) -> None:
        if not self._active or self._closed:
            raise CommissionedGatewayError("the commissioned gateway is not active")
        if self._emergency_stopped:
            raise CommissionedGatewayError("the commissioned gateway is emergency-stopped")
        if state.origin is not EvidenceOrigin.PHYSICAL:
            raise CommissionedGatewayError("motion requires commissioned PHYSICAL feedback")
        if state.session_epoch != self._session.session_epoch:
            raise CommissionedGatewayError("motion feedback session epoch does not match")
        feedback = dict(state.vendor_extra)
        if (
            feedback.get("gateway_boot_epoch") != self._session.boot_epoch
            or feedback.get("gateway_phase") != "armed"
            or feedback.get("gateway_writer_id") != self._session.writer_id
        ):
            raise CommissionedGatewayError(
                "motion feedback does not attest the commissioned epoch, writer, and phase"
            )
        remaining_s = target.valid_until - float(now)
        if not math.isfinite(remaining_s) or remaining_s <= 0.0:
            raise CommissionedGatewayError("refusing an expired gateway setpoint")
        remaining_ms = math.floor(remaining_s * 1000.0)
        ttl_ms = min(self._local_ttl_ms, remaining_ms, MAX_LOCAL_TTL_MS)
        if ttl_ms < 1:
            raise CommissionedGatewayError(
                "setpoint has less than one millisecond of authority remaining"
            )
        command = target.command
        self._last_command = self._session.refresh(
            vx_mps=command.vx,
            vy_mps=command.vy,
            vyaw_rad_s=command.vyaw,
            local_ttl_ms=ttl_ms,
            task_id=bounded_identifier(target.source, fallback="parcel-runtime"),
            trace_id=bounded_identifier(
                f"{self._session.session_epoch}:{target.sequence}",
                fallback="parcel-runtime",
            ),
        )
        if not self._last_command.admitted:
            raise CommissionedGatewayError(
                f"gateway refused motion command: {self._last_command.reason}"
            )

    def stop(self, reason: str) -> None:
        if not self._active or self._closed:
            return
        self._last_stop = self._session.ensure_stopped(
            reason=bounded_reason(reason),
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
            raise CommissionedGatewayError("the commissioned gateway controller is closed")
        if self._emergency_stopped:
            raise CommissionedGatewayError(
                "the gateway E-stop is latched; restart the gateway and rebuild the "
                "commissioned control manager"
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._active = False
        self._session.close()


def build_commissioned_gateway_pair(
    socket_path: str | Path,
    *,
    writer_id: str,
    session_epoch: str,
    expected_hashes: GatewayHashesV1,
    commissioning_record_id: str = "",
    timeout_s: float = 2.0,
    state_timeout_s: float = 0.25,
    local_ttl_ms: int = MAX_LOCAL_TTL_MS,
    client_factory: ClientFactory = MotionGatewayClientV1.connect,
) -> tuple[CommissionedGatewayControllerV1, CommissionedGatewayStateSourceV1]:
    """Build a shared-client motion pair; factory commissioning is separate."""

    clean_writer = writer_id.strip()
    if not clean_writer or len(clean_writer) > 80:
        raise ValueError("motion gateway writer_id must be 1..80 non-whitespace characters")
    clean_epoch = session_epoch.strip()
    if not clean_epoch or len(clean_epoch) > 80:
        raise ValueError("motion gateway session_epoch must be 1..80 characters")
    clean_record_id = commissioning_record_id.strip()
    if len(clean_record_id) > 80:
        raise ValueError("motion gateway commissioning_record_id cannot exceed 80 characters")
    clean_path = Path(socket_path)
    if not clean_path.is_absolute():
        raise ValueError("motion gateway socket_path must be absolute")
    seconds = float(timeout_s)
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise ValueError("motion gateway timeout_s must be positive and finite")
    state_seconds = float(state_timeout_s)
    if not math.isfinite(state_seconds) or state_seconds <= 0.0:
        raise ValueError("motion gateway state_timeout_s must be positive and finite")
    ttl_ms = local_ttl(local_ttl_ms)
    if not isinstance(expected_hashes, GatewayHashesV1):
        raise TypeError("motion gateway expected_hashes must be GatewayHashesV1")
    session = _CommissionedGatewaySessionV1(
        clean_path,
        writer_id=clean_writer,
        timeout_s=seconds,
        state_timeout_s=state_seconds,
        session_epoch=clean_epoch,
        commissioning_record_id=clean_record_id,
        expected_hashes=expected_hashes,
        client_factory=client_factory,
    )
    # Poll at 50 Hz for the normal 250 ms state window and up to 200 Hz for
    # tighter commissioned windows. This is observation cadence only; command
    # cadence remains owned by ControlManager.
    poll_interval_s = min(0.02, max(0.005, state_seconds / 4.0))
    return (
        CommissionedGatewayControllerV1(
            session,
            state_timeout_s=state_seconds,
            local_ttl_ms=ttl_ms,
        ),
        CommissionedGatewayStateSourceV1(
            session,
            poll_interval_s=poll_interval_s,
            shutdown_timeout_s=seconds + 0.25,
        ),
    )
