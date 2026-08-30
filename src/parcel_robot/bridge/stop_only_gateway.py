"""A product-side gateway client which can observe and latch STOP only.

The public object deliberately has no acquire, command, arbitrary request,
raw-send, clear-latch, or vendor handle. Kernel ``SO_PEERCRED`` policy at the
gateway assigns this client's operating-system UID to the stop-only role; the
caller-supplied ``writer_id`` is audit text, never lease authority.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from parcel_robot.bridge.protocol import (
    MAX_GATEWAY_PACKET_BYTES,
    GatewayHashesV1,
    GatewayHelloV1,
    GatewayStateQueryV1,
    GatewayStateV1,
    GatewayStopReportV1,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only on Python 3.10
    from typing import Self


class StopOnlyGatewayError(RuntimeError):
    """The stop-only seam could not complete a bounded operation."""


@dataclass(frozen=True)
class StopOnlyGatewayIdentityV1:
    boot_epoch: str
    phase: str


@dataclass(frozen=True)
class StopOnlyGatewayStateV1:
    boot_epoch: str
    phase: str
    state_sequence: int
    state_age_ms: float
    lease_active: bool
    writer_id: str
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    stationary: bool
    last_stop_sequence: int
    last_stop_reason: str


@dataclass(frozen=True)
class LatchedStopResultV1:
    boot_epoch: str
    stop_sequence: int
    reason: str
    stop_rpc_completed: bool
    stationary_confirmed: bool
    state_sequence: int

    @property
    def confirmed_stationary(self) -> bool:
        return self.stop_rpc_completed and self.stationary_confirmed


class StopOnlyGatewayClientV1:
    """Bounded read/latched-STOP client with structurally no motion API."""

    __slots__ = (
        "_closed",
        "_connection",
        "_expected_hashes",
        "_hello",
        "_sequence",
        "_socket_path",
        "_timeout_s",
        "_writer_id",
    )

    def __init__(
        self,
        socket_path: str | Path,
        *,
        writer_id: str = "parcel-safety",
        timeout_s: float = 0.25,
        expected_hashes: GatewayHashesV1 | None = None,
    ) -> None:
        if not isinstance(writer_id, str) or not writer_id or len(writer_id) > 128:
            raise ValueError("writer_id must be non-empty bounded text")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise TypeError("timeout_s must be numeric")
        if not 0.01 <= float(timeout_s) <= 5.0:
            raise ValueError("timeout_s must be between 0.01 and 5 seconds")
        if expected_hashes is not None and not isinstance(expected_hashes, GatewayHashesV1):
            raise TypeError("expected_hashes must be GatewayHashesV1 or None")
        self._socket_path = Path(socket_path)
        self._writer_id = writer_id
        self._timeout_s = float(timeout_s)
        self._expected_hashes = expected_hashes
        self._connection: socket.socket | None = None
        self._hello: GatewayHelloV1 | None = None
        self._sequence = 0
        self._closed = False

    @classmethod
    def connect(
        cls,
        socket_path: str | Path,
        *,
        writer_id: str = "parcel-safety",
        timeout_s: float = 0.25,
        expected_hashes: GatewayHashesV1 | None = None,
    ) -> StopOnlyGatewayClientV1:
        client = cls(
            socket_path,
            writer_id=writer_id,
            timeout_s=timeout_s,
            expected_hashes=expected_hashes,
        )
        client._open()
        return client

    @property
    def authorizes_actuation(self) -> bool:
        return False

    @property
    def identity(self) -> StopOnlyGatewayIdentityV1:
        hello = self._hello
        if hello is None:
            raise StopOnlyGatewayError("the stop-only client is not connected")
        return StopOnlyGatewayIdentityV1(hello.boot_epoch, hello.phase.value)

    @property
    def boot_epoch(self) -> str:
        return self.identity.boot_epoch

    def close(self) -> None:
        self._closed = True
        self._drop_connection()

    def reconnect(self) -> StopOnlyGatewayIdentityV1:
        """Reconnect for observation/STOP only; reconnect can never arm."""

        self._drop_connection()
        self._closed = False
        self._open()
        return self.identity

    def state(self) -> StopOnlyGatewayStateV1:
        """Read gateway state without carrying or changing positive authority."""

        self._sequence += 1
        response = self._exchange(GatewayStateQueryV1(sequence=self._sequence))
        if not isinstance(response, GatewayStateV1):
            raise StopOnlyGatewayError(
                f"state query answered with {type(response).__name__}"
            )
        return StopOnlyGatewayStateV1(
            boot_epoch=response.boot_epoch,
            phase=response.phase.value,
            state_sequence=response.state_sequence,
            state_age_ms=response.state_age_ms,
            lease_active=response.lease_active,
            writer_id=response.writer_id,
            vx_mps=response.vx_mps,
            vy_mps=response.vy_mps,
            vyaw_rad_s=response.vyaw_rad_s,
            stationary=response.stationary,
            last_stop_sequence=response.last_stop_sequence,
            last_stop_reason=response.last_stop_reason,
        )

    def stop(self, *, reason: str = "independent_safety_stop") -> LatchedStopResultV1:
        """Request unconditional emergency STOP; the emergency bit is not optional."""

        if not isinstance(reason, str) or not reason or len(reason) > 160:
            raise ValueError("reason must be non-empty bounded text")
        hello = self._require_hello()
        self._sequence += 1
        response = self._exchange(
            GatewayStopV1(
                writer_id=self._writer_id,
                boot_epoch=hello.boot_epoch,
                sequence=self._sequence,
                reason=reason,
                emergency=True,
            )
        )
        if not isinstance(response, GatewayStopReportV1):
            raise StopOnlyGatewayError(f"stop answered with {type(response).__name__}")
        return LatchedStopResultV1(
            boot_epoch=response.boot_epoch,
            stop_sequence=response.stop_sequence,
            reason=response.reason,
            stop_rpc_completed=response.stop_rpc_completed,
            stationary_confirmed=response.stationary_confirmed,
            state_sequence=response.state_sequence,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _open(self) -> None:
        if self._closed:
            raise StopOnlyGatewayError("this stop-only client has been closed")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        connection.settimeout(self._timeout_s)
        try:
            connection.connect(str(self._socket_path))
            self._connection = connection
            hello = self._receive()
        except (OSError, ValueError, TypeError) as exc:
            connection.close()
            self._connection = None
            raise StopOnlyGatewayError(
                f"cannot reach the motion gateway at {self._socket_path}: {exc}"
            ) from exc
        if not isinstance(hello, GatewayHelloV1):
            self._drop_connection()
            raise StopOnlyGatewayError("the gateway did not open with GatewayHelloV1")
        if self._expected_hashes is not None and hello.required_hashes != self._expected_hashes:
            self._drop_connection()
            raise StopOnlyGatewayError("gateway compatibility hashes do not match")
        self._hello = hello

    def _require_hello(self) -> GatewayHelloV1:
        hello = self._hello
        if hello is None or self._connection is None:
            raise StopOnlyGatewayError("the stop-only client is not connected")
        return hello

    def _exchange(self, message: GatewayStateQueryV1 | GatewayStopV1) -> object:
        connection = self._connection
        if connection is None:
            raise StopOnlyGatewayError("the stop-only client is not connected")
        try:
            connection.sendall(encode_gateway_message(message))
            return self._receive()
        except (OSError, ValueError, TypeError) as exc:
            self._drop_connection()
            raise StopOnlyGatewayError(f"gateway exchange failed: {exc}") from exc

    def _receive(self) -> object:
        connection = self._connection
        if connection is None:
            raise StopOnlyGatewayError("the stop-only client is not connected")
        packet = connection.recv(MAX_GATEWAY_PACKET_BYTES + 1)
        if not packet:
            raise StopOnlyGatewayError("the gateway closed the connection")
        if len(packet) > MAX_GATEWAY_PACKET_BYTES:
            raise StopOnlyGatewayError("the gateway response exceeded the packet bound")
        return decode_gateway_message(packet)

    def _drop_connection(self) -> None:
        connection = self._connection
        self._connection = None
        self._hello = None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


__all__ = [
    "LatchedStopResultV1",
    "StopOnlyGatewayClientV1",
    "StopOnlyGatewayError",
    "StopOnlyGatewayIdentityV1",
    "StopOnlyGatewayStateV1",
]
