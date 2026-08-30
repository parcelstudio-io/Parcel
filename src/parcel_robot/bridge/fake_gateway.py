"""Test-only gateway core and bounded Unix ``SOCK_SEQPACKET`` service.

This process is deliberately isolated from Parcel's runtime and physical
controller factory.  It proves N24 contract/fault behavior against
``FakeSportServiceV1``; native implementation, peer credentials, launch
profiles, real DDS ownership, and product authority remain N28.
"""

from __future__ import annotations

import selectors
import socket
import stat
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from parcel_robot.control.models import ControlTiming

from .fake_sport import EventSink, FakeSportServiceV1, nonblocking_event_sink
from .protocol import (
    MAX_GATEWAY_PACKET_BYTES,
    GatewayAckDispositionV1,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayBodyKindV1,
    GatewayCommandV1,
    GatewayHashesV1,
    GatewayHelloV1,
    GatewayMessage,
    GatewayPhaseV1,
    GatewayStateQueryV1,
    GatewayStateQueryV2,
    GatewayStateV1,
    GatewayStateV2,
    GatewayStopReportV1,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)


class FakeGatewayCoreV1:
    """State owner for the fake gateway's epoch, writer, TTL, and stop epoch."""

    def __init__(
        self,
        sport: FakeSportServiceV1,
        *,
        required_hashes: GatewayHashesV1,
        boot_epoch: str | None = None,
        timing: ControlTiming | None = None,
        clock: Callable[[], float] = time.monotonic,
        event_sink: EventSink | None = None,
    ) -> None:
        self.sport = sport
        self.required_hashes = required_hashes
        # Test doubles can never self-promote into physical provenance.
        self.body_kind = GatewayBodyKindV1.FAKE
        self.boot_epoch = boot_epoch or uuid.uuid4().hex
        self.timing = timing or ControlTiming()
        self._clock = clock
        self._event_sink = nonblocking_event_sink(event_sink)
        self._lock = threading.RLock()
        self.phase = GatewayPhaseV1.DISARMED
        self._active_connection: int | None = None
        self._writer_id: str | None = None
        self._last_client_sequence = 0
        self._local_deadline: float | None = None
        self._gateway_sequence = 0
        self._stop_sequence = 0
        self._stop_epoch = 0
        self._last_state_sequence: int | None = None
        self._last_stop_reason = "gateway_boot"
        self._last_stop_confirmed = True
        self._move_threads: list[threading.Thread] = []

    @property
    def active_writer(self) -> str | None:
        with self._lock:
            return self._writer_id

    def hello(self) -> GatewayHelloV1:
        with self._lock:
            return GatewayHelloV1(
                boot_epoch=self.boot_epoch,
                gateway_sequence=self._next_gateway_sequence_locked(),
                phase=self.phase,
                required_hashes=self.required_hashes,
            )

    def acquire(self, connection_id: int, request: GatewayAcquireV1) -> GatewayAckV1:
        with self._lock:
            reason = self._acquire_refusal_locked(connection_id, request)
            if reason:
                if reason == "writer_conflict":
                    self._stop_locked(reason, latch=True)
                return self._ack_locked(request, accepted=False, reason=reason)
            if not self.sport.acquire_writer(request.writer_id):
                self._stop_locked("sport_writer_conflict", latch=True)
                return self._ack_locked(
                    request,
                    accepted=False,
                    reason="sport_writer_conflict",
                )
            now = self._clock()
            self.phase = GatewayPhaseV1.ARMED
            self._active_connection = connection_id
            self._writer_id = request.writer_id
            self._last_client_sequence = request.sequence
            # Receiver-local derivation: only the duration crosses the wire.
            self._local_deadline = now + request.local_ttl_ms / 1000.0
            state = self.sport.state()
            self._last_state_sequence = state.sequence
            self._record_locked(
                "gateway_armed",
                writer_id=request.writer_id,
                local_ttl_ms=request.local_ttl_ms,
            )
            return self._ack_locked(request, accepted=True)

    def command(self, connection_id: int, request: GatewayCommandV1) -> GatewayAckV1:
        with self._lock:
            reason = self._authority_refusal_locked(connection_id, request)
            if reason:
                self._stop_locked(reason, latch=True)
                return self._ack_locked(request, accepted=False, reason=reason)
            if self._deadline_expired_locked():
                self._stop_locked("local_ttl_expired", latch=False)
                return self._ack_locked(
                    request,
                    accepted=False,
                    reason="local_ttl_expired",
                )
            state_reason = self._state_refusal_locked()
            if state_reason:
                self._stop_locked(state_reason, latch=state_reason == "state_out_of_order")
                return self._ack_locked(request, accepted=False, reason=state_reason)
            self._last_client_sequence = request.sequence
            # Again, derive expiry on the receiver clock at receipt.  There is
            # no client-issued monotonic stamp in GatewayCommandV1.
            self._local_deadline = self._clock() + request.local_ttl_ms / 1000.0
            delivery_stop_epoch = self._stop_epoch
            thread = threading.Thread(
                target=self._deliver_move,
                args=(request, delivery_stop_epoch),
                name=f"fake-sport-move-{request.sequence}",
                daemon=True,
            )
            self._move_threads.append(thread)
            thread.start()
            self._record_locked(
                "gateway_command_admitted",
                writer_id=request.writer_id,
                client_sequence=request.sequence,
                local_ttl_ms=request.local_ttl_ms,
                ack_scope="gateway_admission",
            )
            # This ACK deliberately precedes/does not wait for Move completion.
            return self._ack_locked(request, accepted=True)

    def explicit_stop(
        self,
        connection_id: int,
        request: GatewayStopV1,
    ) -> GatewayStopReportV1 | GatewayAckV1:
        with self._lock:
            reason = self._authority_refusal_locked(connection_id, request, require_hashes=False)
            if reason:
                self._stop_locked(reason, latch=True)
                return self._ack_locked(request, accepted=False, reason=reason)
            self._last_client_sequence = request.sequence
            return self._stop_locked(
                f"client_stop:{request.reason}",
                latch=request.emergency,
            )

    def state(self) -> GatewayStateV1:
        with self._lock:
            if self.phase is GatewayPhaseV1.ARMED and self._deadline_expired_locked():
                self._stop_locked("local_ttl_expired", latch=False)
            state = self.sport.state()
            age_ms = max(0.0, (self._clock() - state.received_at_monotonic_s) * 1000.0)
            return GatewayStateV1(
                boot_epoch=self.boot_epoch,
                gateway_sequence=self._next_gateway_sequence_locked(),
                phase=self.phase,
                state_sequence=state.sequence,
                state_age_ms=age_ms,
                lease_active=state.lease_active,
                writer_id=self._writer_id or "",
                vx_mps=state.vx_mps,
                vy_mps=state.vy_mps,
                vyaw_rad_s=state.vyaw_rad_s,
                stationary=state.stationary,
                last_stop_sequence=self._stop_sequence,
                last_stop_reason=self._last_stop_reason,
            )

    def state_query(self, request: GatewayStateQueryV1) -> GatewayStateV1:
        del request
        return self.state()

    def state_v2(self) -> GatewayStateV2:
        """Expose fake provenance and explicitly unavailable native telemetry."""

        state = self.state()
        return GatewayStateV2(
            boot_epoch=state.boot_epoch,
            gateway_sequence=state.gateway_sequence,
            phase=state.phase,
            state_sequence=state.state_sequence,
            state_age_ms=state.state_age_ms,
            lease_active=state.lease_active,
            writer_id=state.writer_id,
            vx_mps=state.vx_mps,
            vy_mps=state.vy_mps,
            vyaw_rad_s=state.vyaw_rad_s,
            stationary=state.stationary,
            last_stop_sequence=state.last_stop_sequence,
            last_stop_reason=state.last_stop_reason,
            body_kind=self.body_kind,
            telemetry_valid=False,
            vendor_position_m=(0.0, 0.0, 0.0),
            vendor_rpy_rad=(0.0, 0.0, 0.0),
            mode=0,
            error_code=0,
            source_time_s=None,
            sport_foot_force_raw=(0, 0, 0, 0),
            feedback_integrity_ok=None,
            feedback_integrity_reason="feedback_integrity_unavailable",
            commissioned_soc_ok=None,
            commissioned_soc_reason="commissioned_soc_unavailable",
            low_state_valid=False,
            low_state_sequence=0,
            low_state_age_ms=None,
            low_state_tick=None,
            battery_soc_percent=None,
            power_v=None,
            power_a=None,
            max_motor_temperature_raw=None,
            motor_lost_max_raw=None,
            foot_force_est_raw=None,
            imu_temperature_raw=None,
            temperature_ntc_raw=None,
            bms_status=None,
        )

    def state_query_v2(self, request: GatewayStateQueryV2) -> GatewayStateV2:
        del request
        return self.state_v2()

    def client_lost(self, connection_id: int) -> GatewayStopReportV1 | None:
        with self._lock:
            if connection_id != self._active_connection:
                return None
            return self._stop_locked("client_disconnected", latch=False)

    def protocol_fault(self, connection_id: int, reason: str) -> None:
        with self._lock:
            if connection_id == self._active_connection:
                self._stop_locked(f"protocol_fault:{reason}", latch=True)

    def tick(self) -> GatewayStopReportV1 | None:
        with self._lock:
            if self.phase is not GatewayPhaseV1.ARMED:
                return None
            if self._deadline_expired_locked():
                return self._stop_locked("local_ttl_expired", latch=False)
            reason = self._state_refusal_locked()
            if reason:
                return self._stop_locked(reason, latch=reason == "state_out_of_order")
            return None

    def close(self) -> None:
        with self._lock:
            if self.phase is GatewayPhaseV1.ARMED:
                self._stop_locked("gateway_shutdown", latch=False)
        self.sport.close()

    def _acquire_refusal_locked(
        self,
        connection_id: int,
        request: GatewayAcquireV1,
    ) -> str:
        if self.phase is GatewayPhaseV1.LATCHED:
            return "gateway_latched"
        if request.boot_epoch != self.boot_epoch:
            return "boot_epoch_mismatch"
        if request.hashes != self.required_hashes:
            return "contract_hash_mismatch"
        if request.sequence <= self._last_client_sequence:
            return "client_sequence_not_increasing"
        if self._active_connection is not None or self._writer_id is not None:
            del connection_id
            return "writer_conflict"
        return ""

    def _authority_refusal_locked(
        self,
        connection_id: int,
        request: GatewayCommandV1 | GatewayStopV1,
        *,
        require_hashes: bool = True,
    ) -> str:
        if self.phase is not GatewayPhaseV1.ARMED:
            return "gateway_disarmed"
        if connection_id != self._active_connection:
            return "writer_connection_mismatch"
        if request.writer_id != self._writer_id:
            return "writer_id_mismatch"
        if request.boot_epoch != self.boot_epoch:
            return "boot_epoch_mismatch"
        if request.sequence <= self._last_client_sequence:
            return "client_sequence_not_increasing"
        if (
            require_hashes
            and isinstance(request, GatewayCommandV1)
            and request.hashes != self.required_hashes
        ):
            return "contract_hash_mismatch"
        return ""

    def _state_refusal_locked(self) -> str:
        state = self.sport.state()
        now = self._clock()
        if not state.lease_active:
            return "sport_lease_lost"
        age = now - state.received_at_monotonic_s
        if age < 0.0:
            return "state_from_future"
        if age >= self.timing.state_timeout_s:
            return "state_stale"
        if self._last_state_sequence is not None and state.sequence <= self._last_state_sequence:
            return "state_out_of_order"
        self._last_state_sequence = state.sequence
        return ""

    def _deadline_expired_locked(self) -> bool:
        now = self._clock()
        return self._local_deadline is None or now >= self._local_deadline

    def _deliver_move(self, request: GatewayCommandV1, delivery_stop_epoch: int) -> None:
        error: Exception | None = None
        try:
            self.sport.move(
                writer_id=request.writer_id,
                vx_mps=request.vx_mps,
                vy_mps=request.vy_mps,
                vyaw_rad_s=request.vyaw_rad_s,
            )
        except Exception as caught:  # noqa: BLE001 - fake vendor is a fault boundary
            error = caught
        with self._lock:
            if delivery_stop_epoch != self._stop_epoch or self.phase is not GatewayPhaseV1.ARMED:
                # Move completed after a stop boundary.  It must never be the
                # final vendor action, even if the prior StopMove succeeded.
                self._stop_locked("late_move_completion_compensation", latch=False)
            elif error is not None:
                self._stop_locked(f"move_failed:{error}", latch=True)

    def _stop_locked(self, reason: str, *, latch: bool) -> GatewayStopReportV1:
        # A later compensation/retry may strengthen a stop, never clear a
        # previously latched authority fault.
        latch = latch or self.phase is GatewayPhaseV1.LATCHED
        self._stop_epoch += 1
        self._stop_sequence += 1
        previous_state_sequence = self._last_state_sequence or 0
        writer = self._writer_id
        rpc_completed = self.sport.stop_move(reason=reason)
        state = self.sport.state()
        state_age = self._clock() - state.received_at_monotonic_s
        stationary_confirmed = (
            rpc_completed
            and state.sequence > previous_state_sequence
            and 0.0 <= state_age < self.timing.state_timeout_s
            and state.stationary
        )
        if not rpc_completed or not stationary_confirmed:
            latch = True
        self.phase = GatewayPhaseV1.LATCHED if latch else GatewayPhaseV1.DISARMED
        self._active_connection = None
        self._writer_id = None
        # Sequence is a per-boot replay fence, not merely a per-connection
        # counter.  Disarm/client loss must not make a captured acquire+command
        # pair reusable in the same boot epoch.
        self._local_deadline = None
        self._last_state_sequence = state.sequence
        self._last_stop_reason = reason
        self._last_stop_confirmed = stationary_confirmed
        self.sport.release_writer(writer)
        report = GatewayStopReportV1(
            boot_epoch=self.boot_epoch,
            gateway_sequence=self._next_gateway_sequence_locked(),
            stop_sequence=self._stop_sequence,
            reason=reason,
            stop_rpc_completed=rpc_completed,
            stationary_confirmed=stationary_confirmed,
            state_sequence=state.sequence if stationary_confirmed else 0,
        )
        self._record_locked("gateway_stop_report", **report.as_dict())
        return report

    def _ack_locked(
        self,
        request: GatewayAcquireV1 | GatewayCommandV1 | GatewayStopV1,
        *,
        accepted: bool,
        reason: str = "",
    ) -> GatewayAckV1:
        return GatewayAckV1(
            boot_epoch=self.boot_epoch,
            gateway_sequence=self._next_gateway_sequence_locked(),
            acknowledged_kind=request.kind,
            acknowledged_sequence=request.sequence,
            disposition=(
                GatewayAckDispositionV1.ACCEPTED if accepted else GatewayAckDispositionV1.REJECTED
            ),
            reason=reason,
        )

    def _next_gateway_sequence_locked(self) -> int:
        self._gateway_sequence += 1
        return self._gateway_sequence

    def _record_locked(self, event: str, **details: object) -> None:
        self._event_sink(
            {
                "event": event,
                "at_monotonic_s": self._clock(),
                "boot_epoch": self.boot_epoch,
                "phase": self.phase.value,
                **details,
            }
        )


class FakeGatewayServerV1:
    """Bounded local seqpacket server around :class:`FakeGatewayCoreV1`."""

    def __init__(self, socket_path: str | Path, core: FakeGatewayCoreV1) -> None:
        self.socket_path = Path(socket_path)
        self.core = core
        self._selector = selectors.DefaultSelector()
        self._listener: socket.socket | None = None
        self._clients: dict[socket.socket, int] = {}
        self._next_connection_id = 1
        self._bound_inode: int | None = None

    def serve(self, stop_event: threading.Event) -> None:
        self._open()
        try:
            while not stop_event.is_set():
                for key, _mask in self._selector.select(timeout=self.core.timing.period_s):
                    if key.fileobj is self._listener:
                        self._accept()
                    else:
                        self._read(key.fileobj)
                self.core.tick()
        finally:
            self.close()

    def close(self) -> None:
        for client in list(self._clients):
            self._close_client(client)
        if self._listener is not None:
            self._selector.unregister(self._listener)
            self._listener.close()
            self._listener = None
        self.core.close()
        self._selector.close()
        try:
            metadata = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if self._bound_inode is not None and metadata.st_ino == self._bound_inode:
            self.socket_path.unlink()

    def _open(self) -> None:
        try:
            existing = self.socket_path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISSOCK(existing.st_mode):
                raise FileExistsError(f"refusing to replace non-socket path {self.socket_path}")
            self.socket_path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        listener.setblocking(False)
        listener.bind(str(self.socket_path))
        listener.listen(8)
        self._bound_inode = self.socket_path.lstat().st_ino
        self._listener = listener
        self._selector.register(listener, selectors.EVENT_READ)

    def _accept(self) -> None:
        assert self._listener is not None
        client, _address = self._listener.accept()
        client.setblocking(False)
        connection_id = self._next_connection_id
        self._next_connection_id += 1
        self._clients[client] = connection_id
        self._selector.register(client, selectors.EVENT_READ)
        self._send(client, self.core.hello())

    def _read(self, fileobj: object) -> None:
        if not isinstance(fileobj, socket.socket):
            return
        client = fileobj
        connection_id = self._clients[client]
        try:
            packet = client.recv(MAX_GATEWAY_PACKET_BYTES + 1)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._close_client(client)
            return
        if not packet:
            self._close_client(client)
            return
        try:
            message = decode_gateway_message(packet)
            response = self._dispatch(connection_id, message)
        except (TypeError, ValueError) as exc:
            self.core.protocol_fault(connection_id, str(exc))
            self._close_client(client)
            return
        if response is not None:
            self._send(client, response)

    def _dispatch(self, connection_id: int, message: GatewayMessage) -> GatewayMessage | None:
        if isinstance(message, GatewayAcquireV1):
            return self.core.acquire(connection_id, message)
        if isinstance(message, GatewayCommandV1):
            return self.core.command(connection_id, message)
        if isinstance(message, GatewayStopV1):
            return self.core.explicit_stop(connection_id, message)
        if isinstance(message, GatewayStateQueryV1):
            return self.core.state_query(message)
        if isinstance(message, GatewayStateQueryV2):
            return self.core.state_query_v2(message)
        raise ValueError(f"client cannot send gateway response kind {message.kind!r}")

    def _send(self, client: socket.socket, message: GatewayMessage) -> None:
        try:
            client.sendall(encode_gateway_message(message))
        except (BlockingIOError, BrokenPipeError, OSError):
            self._close_client(client)

    def _close_client(self, client: socket.socket) -> None:
        connection_id = self._clients.pop(client, None)
        if connection_id is None:
            return
        try:
            self._selector.unregister(client)
        except (KeyError, ValueError):
            pass
        client.close()
        self.core.client_lost(connection_id)
