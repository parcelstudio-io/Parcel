"""Serialized commissioned motion-gateway session boundary."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path

from parcel_robot.bridge.gateway_client import (
    ArmResultV1,
    CommandResultV1,
    ConnectResultV1,
    MotionGatewayClientV1,
    MotionStateV1,
    MotionStateV2,
    StopResultV1,
)
from parcel_robot.bridge.protocol import GatewayBodyKindV1, GatewayHashesV1

from .motion_gateway_common import (
    ClientFactory,
    CommissionedGatewayError,
    StateObserver,
)


class _CommissionedGatewaySessionV1:
    """Serialized, explicitly armed access to one production gateway client.

    Every authority-changing result is followed by an authoritative state
    query.  Epoch, writer, phase, and the client-local arm bit must agree at
    each boundary; disagreement drops the socket so the gateway's peer-loss
    stop is the final action. Controller acquire/refresh/stop calls remain
    bounded synchronous I/O on this session; the background cache removes
    socket work from ``latest()``, not from those authority transactions.
    """

    def __init__(
        self,
        socket_path: str | Path,
        *,
        writer_id: str,
        timeout_s: float,
        state_timeout_s: float,
        session_epoch: str,
        commissioning_record_id: str,
        expected_hashes: GatewayHashesV1,
        client_factory: ClientFactory,
    ) -> None:
        self._socket_path = Path(socket_path)
        self._writer_id = writer_id
        self._timeout_s = timeout_s
        self._state_timeout_s = state_timeout_s
        self._session_epoch = session_epoch
        self._commissioning_record_id = commissioning_record_id
        self._expected_hashes = expected_hashes
        self._client_factory = client_factory
        self._client: MotionGatewayClientV1 | None = None
        self._expected_boot_epoch: str | None = None
        self._lock = threading.RLock()
        # State publication is deliberately independent of the serialized wire
        # lock. The commissioned source registers one in-process observer so
        # every verified read -- including reads that fence arm, command, and
        # stop transactions -- can advance its cache. The observer never does
        # I/O.
        self._state_observer_lock = threading.Lock()
        self._state_observer: StateObserver | None = None
        # Background observation may share this socket only while there is no
        # local motion authority. The flag remains false after local TTL expiry
        # until a verified stop/reconnect boundary; the gateway can outlive the
        # client's pessimistic deadline by transport latency.
        self._background_state_poll_allowed = True
        self._closed = False

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._client is not None

    @property
    def session_epoch(self) -> str:
        return self._session_epoch

    @property
    def commissioning_record_id(self) -> str:
        return self._commissioning_record_id

    @property
    def writer_id(self) -> str:
        return self._writer_id

    @property
    def boot_epoch(self) -> str:
        with self._lock:
            if self._expected_boot_epoch is None:
                raise CommissionedGatewayError("the commissioned gateway is not connected")
            return self._expected_boot_epoch

    @property
    def armed(self) -> bool:
        with self._lock:
            client = self._client
            return client is not None and client.armed

    def register_state_observer(self, observer: StateObserver) -> None:
        """Register the pair's sole non-I/O state observer before connect."""

        if not callable(observer):
            raise TypeError("gateway state observer must be callable")
        with self._state_observer_lock:
            if self._closed:
                raise CommissionedGatewayError("the commissioned gateway session is closed")
            if self._state_observer is not None and self._state_observer is not observer:
                raise CommissionedGatewayError("a gateway state observer is already registered")
            self._state_observer = observer

    def unregister_state_observer(self, observer: StateObserver) -> None:
        """Remove ``observer`` without disturbing a replacement observer."""

        with self._state_observer_lock:
            if self._state_observer is observer:
                self._state_observer = None

    def connect(self) -> None:
        """Open and attest a passive, ownerless DISARMED connection."""

        with self._lock:
            if self._closed:
                raise CommissionedGatewayError("the commissioned gateway session is closed")
            if self._client is not None:
                return
            client = self._client_factory(
                self._socket_path,
                writer_id=self._writer_id,
                timeout_s=self._timeout_s,
                expected_hashes=self._expected_hashes,
            )
            try:
                identity = client.identity
                self._require_client_identity(client)
                if identity.phase != "disarmed" or client.armed:
                    raise CommissionedGatewayError(
                        "commissioned gateway activation requires a passive DISARMED hello"
                    )
                self._expected_boot_epoch = identity.boot_epoch
                state = self._read_state(client)
                if state.phase != "disarmed":
                    raise CommissionedGatewayError(
                        "commissioned gateway activation requires DISARMED state"
                    )
                self._background_state_poll_allowed = True
            except Exception:
                client.close()
                self._expected_boot_epoch = None
                raise
            self._client = client

    def reconnect(self, *, settle_timeout_s: float = 2.0) -> ConnectResultV1:
        """Reconnect and attest that no authority was carried across it."""

        with self._lock:
            client = self._require_client()
            previous_boot_epoch = self.boot_epoch
            try:
                result = client.reconnect(settle_timeout_s=settle_timeout_s)
                if not isinstance(result, ConnectResultV1):
                    raise CommissionedGatewayError(
                        "gateway reconnect returned an unexpected result type"
                    )
                self._require_client_identity(client)
                identity = client.identity
                restarted = previous_boot_epoch != identity.boot_epoch
                if (
                    result.identity != identity
                    or result.armed
                    or client.armed
                    or result.previous_boot_epoch != previous_boot_epoch
                    or result.gateway_restarted is not restarted
                    or identity.phase not in {"disarmed", "latched"}
                ):
                    raise CommissionedGatewayError(
                        "gateway reconnect violated identity or disarmed authority"
                    )
                if restarted:
                    raise CommissionedGatewayError(
                        "gateway boot epoch changed; rebuild the commissioned control manager"
                    )
                self._expected_boot_epoch = identity.boot_epoch
                state = self._read_state(client)
                if state.phase not in {"disarmed", "latched"}:
                    raise CommissionedGatewayError("gateway reconnect retained motion authority")
                self._background_state_poll_allowed = True
            except Exception:
                self._drop_client(client)
                raise
            return result

    def state(self) -> MotionStateV2:
        with self._lock:
            client = self._require_client()
            try:
                state = self._read_state(client)
            except Exception:
                self._drop_client(client)
                raise
            return state

    def state_if_disarmed(self) -> MotionStateV2 | None:
        """Poll only when no command/stop can need the serialized socket.

        Check and read are one transaction under ``_lock``. Once acquire has
        succeeded, this path cannot enter the socket until a verified stop or
        reconnect reopens it, so an active motion STOP never queues behind a
        background state request.
        """

        with self._lock:
            client = self._require_client()
            if not self._background_state_poll_allowed or client.armed:
                return None
            try:
                state = self._read_state(client)
                if state.phase == "armed":
                    self._background_state_poll_allowed = False
                    raise CommissionedGatewayError(
                        "background state poll observed unexpected motion authority"
                    )
            except Exception:
                self._drop_client(client)
                raise
            return state

    def arm(self, *, local_ttl_ms: int) -> ArmResultV1:
        """Perform the sole explicit arm transaction and verify its new lease."""

        with self._lock:
            client = self._require_client()
            try:
                before = self._read_state(client)
                if before.phase != "disarmed":
                    raise CommissionedGatewayError(
                        "motion authority can only be acquired from DISARMED"
                    )
                result = client.acquire(local_ttl_ms=local_ttl_ms)
                if not isinstance(result, ArmResultV1):
                    raise CommissionedGatewayError(
                        "gateway acquire returned an unexpected result type"
                    )
                self._require_authority_result(
                    client,
                    boot_epoch=result.boot_epoch,
                    authority_deadline=result.authority_deadline_monotonic_s,
                    authoritative=result.armed,
                )
                if result.armed:
                    # This assignment is under the same lock used by
                    # state_if_disarmed(), closing the check-then-arm race.
                    self._background_state_poll_allowed = False
                if result.local_ttl_ms != local_ttl_ms:
                    raise CommissionedGatewayError(
                        "gateway acquire result changed the requested local TTL"
                    )
                # The gateway phase can change before Unitree publishes the
                # first post-arm physical sample. Do not expose that
                # transitional metadata under the old physical sequence.
                after = self._read_state(client, publish=False)
                while (
                    result.armed
                    and after.phase == "armed"
                    and after.state_sequence <= before.state_sequence
                ):
                    remaining_s = result.authority_deadline_monotonic_s - time.monotonic()
                    if remaining_s <= 0.0:
                        break
                    time.sleep(min(0.005, remaining_s))
                    after = self._read_state(client, publish=False)
                if result.armed and (
                    after.phase != "armed" or after.state_sequence <= before.state_sequence
                ):
                    raise CommissionedGatewayError(
                        "accepted acquire did not produce a fresh verified writer sample"
                    )
                if not result.armed and after.phase == "armed":
                    raise CommissionedGatewayError(
                        "refused acquire nevertheless produced motion authority"
                    )
                if not result.armed:
                    self._background_state_poll_allowed = True
                # Publish through a fresh conservative timestamp only after
                # the post-arm sequence/phase fence has passed.
                published = self._read_state(client)
                if result.armed and (
                    published.phase != "armed" or published.state_sequence <= before.state_sequence
                ):
                    raise CommissionedGatewayError(
                        "motion authority changed before post-arm state publication"
                    )
            except Exception:
                self._drop_client(client)
                raise
            return result

    def refresh(
        self,
        *,
        vx_mps: float,
        vy_mps: float,
        vyaw_rad_s: float,
        local_ttl_ms: int,
        task_id: str,
        trace_id: str,
    ) -> CommandResultV1:
        """Send one bounded refresh, then verify epoch, writer, and phase."""

        with self._lock:
            client = self._require_client()
            try:
                result = client.command(
                    vx_mps=vx_mps,
                    vy_mps=vy_mps,
                    vyaw_rad_s=vyaw_rad_s,
                    local_ttl_ms=local_ttl_ms,
                    task_id=task_id,
                    trace_id=trace_id,
                )
                if not isinstance(result, CommandResultV1):
                    raise CommissionedGatewayError(
                        "gateway command returned an unexpected result type"
                    )
                self._require_authority_result(
                    client,
                    boot_epoch=result.boot_epoch,
                    authority_deadline=result.authority_deadline_monotonic_s,
                    authoritative=result.admitted,
                )
                after = self._read_state(client)
                if result.admitted and after.phase != "armed":
                    raise CommissionedGatewayError(
                        "admitted command lost the verified writer lease"
                    )
                if not result.admitted and after.phase == "armed":
                    raise CommissionedGatewayError(
                        "refused command retained unexpected motion authority"
                    )
                if not result.admitted:
                    self._background_state_poll_allowed = True
            except Exception:
                self._drop_client(client)
                raise
            return result

    def ensure_stopped(
        self,
        *,
        reason: str,
        emergency: bool,
        max_state_age_s: float,
    ) -> StopResultV1 | None:
        """Cross the socket for real stops, with one passive-start exception.

        ``ControlManager.start`` always establishes a stationary boundary.  A
        stop sent by a client that has never owned the lease intentionally
        latches the gateway, so the already-fresh, ownerless DISARMED state is
        the only ordinary-stop witness that may elide the packet.  Once armed,
        ordinary stop and emergency stop both cross the socket.
        """

        with self._lock:
            client = self._require_client()
            before: MotionStateV1 | None = None
            if not emergency:
                try:
                    before = self._read_state(client)
                except Exception:
                    self._drop_client(client)
                    raise
                already_stopped = (
                    before.phase == "disarmed"
                    and before.stationary
                    and not before.lease_active
                    and not before.writer_id
                    and 0.0 <= float(before.state_age_ms) / 1000.0 <= max_state_age_s
                )
                if already_stopped:
                    self._background_state_poll_allowed = True
                    return None
            try:
                report = client.stop(reason=reason, emergency=emergency)
                if not isinstance(report, StopResultV1):
                    raise CommissionedGatewayError(
                        "gateway stop returned an unexpected result type"
                    )
                expected_reason = f"client_stop:{reason}"
                if (
                    report.boot_epoch != self.boot_epoch
                    or report.stop_sequence < 1
                    or report.state_sequence < 1
                    or (before is not None and report.state_sequence <= before.state_sequence)
                    or report.reason != expected_reason
                    or not report.confirmed_stationary
                    or client.armed
                ):
                    raise CommissionedGatewayError(
                        "gateway stop report violates epoch, reason, or stationary contract"
                    )
                after = self._read_state(client)
                if (
                    after.last_stop_sequence != report.stop_sequence
                    or after.last_stop_reason != report.reason
                    or (emergency and after.phase != "latched")
                    or (
                        not emergency
                        and before is not None
                        and before.phase == "armed"
                        and after.phase != "disarmed"
                    )
                ):
                    raise CommissionedGatewayError(
                        "gateway state does not attest the returned stop result"
                    )
                self._background_state_poll_allowed = True
            except Exception:
                self._drop_client(client)
                raise
            return report

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._background_state_poll_allowed = False
            client = self._client
            self._client = None
            if client is not None:
                client.close()

    def _require_client(self) -> MotionGatewayClientV1:
        client = self._client
        if client is None:
            raise CommissionedGatewayError("the commissioned motion gateway is not connected")
        return client

    def _drop_client(self, client: MotionGatewayClientV1) -> None:
        client.close()
        self._background_state_poll_allowed = False
        if self._client is client:
            self._client = None

    def _require_client_identity(self, client: MotionGatewayClientV1) -> None:
        identity = client.identity
        if (
            client.writer_id != self._writer_id
            or not identity.boot_epoch
            or len(identity.boot_epoch) > 80
        ):
            raise CommissionedGatewayError(
                "gateway client writer or boot identity violates commissioning"
            )

    def _read_state(
        self,
        client: MotionGatewayClientV1,
        *,
        publish: bool = True,
    ) -> MotionStateV2:
        query_started_at = time.monotonic()
        state = client.state_v2()
        self._require_state(client, state, query_started_at=query_started_at)
        if publish:
            with self._state_observer_lock:
                observer = self._state_observer
            if observer is not None:
                # Do not hold the observer lock across callback code. A
                # sequencing exception must propagate so the transaction drops
                # the connection.
                observer(state, query_started_at)
        return state

    def _require_state(
        self,
        client: MotionGatewayClientV1,
        state: object,
        *,
        query_started_at: float,
    ) -> None:
        self._require_client_identity(client)
        expected_boot = self._expected_boot_epoch
        if expected_boot is None:
            raise CommissionedGatewayError("gateway state arrived before identity fencing")
        if not isinstance(state, MotionStateV2):
            raise CommissionedGatewayError(
                "commissioned gateway requires telemetry-bearing V2 state"
            )
        if state.body_kind is not GatewayBodyKindV1.UNITREE_SDK2:
            raise CommissionedGatewayError(
                "commissioned gateway requires UNITREE_SDK2 V2 body attestation"
            )
        if (
            not isinstance(state.feedback_integrity_ok, bool)
            or not state.feedback_integrity_reason
            or len(state.feedback_integrity_reason) > 160
            or state.feedback_integrity_reason == "feedback_integrity_unavailable"
            or state.feedback_integrity_ok is not (state.feedback_integrity_reason == "ok")
            or state.commissioned_soc_ok is None
            or not isinstance(state.commissioned_soc_ok, bool)
            or not state.commissioned_soc_reason
            or len(state.commissioned_soc_reason) > 160
            or state.commissioned_soc_ok
            is not (state.commissioned_soc_reason == "soc_above_commissioned_minimum")
        ):
            raise CommissionedGatewayError(
                "gateway feedback integrity or commissioned SOC verdict is inconsistent"
            )
        values = (
            state.state_age_ms,
            state.vx_mps,
            state.vy_mps,
            state.vyaw_rad_s,
            *state.vendor_position_m,
            *state.vendor_rpy_rad,
        )
        conservative_age_s = float(state.state_age_ms) / 1000.0 + max(
            0.0, time.monotonic() - query_started_at
        )
        if (
            state.boot_epoch != expected_boot
            or state.boot_epoch != client.identity.boot_epoch
            or state.phase not in {"disarmed", "armed", "latched"}
            or state.state_sequence < 1
            or state.last_stop_sequence < 0
            or isinstance(state.error_code, bool)
            or not isinstance(state.error_code, int)
            or not 0 <= state.error_code < 2**32
            or any(not math.isfinite(float(value)) for value in values)
            or state.state_age_ms < 0.0
            or not math.isfinite(conservative_age_s)
            or conservative_age_s >= self._state_timeout_s
            or not state.telemetry_valid
            or not state.low_state_valid
            or state.low_state_sequence < 1
            or state.low_state_age_ms is None
            or state.low_state_age_ms < 0.0
            or (
                float(state.low_state_age_ms) / 1000.0
                + max(0.0, time.monotonic() - query_started_at)
                >= self._state_timeout_s
            )
            or state.low_state_tick is None
            or state.battery_soc_percent is None
            or state.power_v is None
            or state.power_a is None
            or state.max_motor_temperature_raw is None
            or state.motor_lost_max_raw is None
            or state.foot_force_est_raw is None
            or state.imu_temperature_raw is None
            or state.temperature_ntc_raw is None
            or state.bms_status is None
        ):
            raise CommissionedGatewayError(
                "gateway state violates identity, freshness, or required telemetry contract"
            )
        if state.phase == "armed":
            if not client.armed or not state.lease_active or state.writer_id != self._writer_id:
                raise CommissionedGatewayError(
                    "ARMED gateway state does not carry the commissioned writer lease"
                )
            return
        if client.armed or state.lease_active or bool(state.writer_id):
            raise CommissionedGatewayError(
                "contained gateway state retains a writer or local authority"
            )
        if state.phase == "disarmed" and not state.stationary:
            raise CommissionedGatewayError("DISARMED gateway state is not stationary")

    def _require_authority_result(
        self,
        client: MotionGatewayClientV1,
        *,
        boot_epoch: str,
        authority_deadline: float,
        authoritative: bool,
    ) -> None:
        if (
            boot_epoch != self.boot_epoch
            or boot_epoch != client.identity.boot_epoch
            or not math.isfinite(float(authority_deadline))
            or bool(client.armed) is not bool(authoritative)
            or (authoritative and authority_deadline <= time.monotonic())
        ):
            raise CommissionedGatewayError(
                "gateway authority result violates epoch, deadline, or arm state"
            )
