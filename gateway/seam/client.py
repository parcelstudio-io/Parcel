"""``MotionGatewayClientV1`` — the production side of the motion seam.

HLD Gate 1 asks for "the fake-body gateway **and production Unix client**".
Until this module there was only ``gateway/bench_client.py``, which exists to
attack the gateway: it can put arbitrary bytes on the wire
(``send_raw``), send any message object at all, and forge fields.  That is the
right tool for proving the decoder fails closed and the wrong shape entirely
for a runtime caller, so the two are separate modules and this one has none of
those doors.

**The whole public surface**, and nothing else:

``connect`` / ``close`` / context manager
    one ``AF_UNIX`` ``SOCK_SEQPACKET`` connection, every socket operation on a
    timeout, the gateway's ``GatewayHelloV1`` read before anything is sent.
``acquire``
    the **explicit arm transaction**.  It is the only thing that can make this
    client armed, it is never called from anywhere else in this module, and
    there is no flag or option on any other method that reaches it.
``command``
    the time-bounded refresh.  Refuses locally — before a byte is sent — if
    this client is not armed or if its own conservative copy of the authority
    deadline has passed.
``stop``
    the explicit stop, returning the gateway's own stop report.
``state`` / ``last_stop_report``
    typed observation.
``reconnect``
    drop the connection and open a new one.  **Always lands DISARMED**, and
    reports whether the gateway restarted underneath (a new boot epoch).

There is no ``send``, no ``request``, no ``receive``, no ``send_raw`` and no
way to hand this class a message object: :func:`typed results only
<MotionStateV1>` in, typed results out.  It imports the frozen wire contract
and stdlib and nothing else — no ``gateway.core``, no ``gateway.ports``, no
``gateway.writer``, no vendor SDK, no fake — so a runtime caller physically
cannot reach the vendor except by going through the Unix socket to the gateway
process.  ``tests/test_motion_seam.py`` pins that import surface and the public
method set.

**Disarmed is the resting state.**  Anything that could mean "authority may
have changed hands" sets ``armed`` back to false and requires a fresh
``acquire``: a refused ack, an explicit stop, a transport error, a close, a
reconnect, a gateway restart, and the client's own deadline lapsing.  Nothing
in this module re-acquires on its own — not on connect, not on hello, not on a
healthy state, not on reconnect.  That is HLD Gate 1's "restart/reconnect stay
disarmed" and the card's stop condition "auto-arms or auto-reacquires on
startup, readiness, reconnect or restart".

**The sequence fence is never rewound.**  The gateway's monotonic client
sequence is per *boot*, not per connection, so this client keeps counting
across a reconnect to the same boot epoch; rewinding it would make its own
next acquire look like a replay and stop the robot.

**What this client is not.**  It is not a controller: it holds no vendor
object, no lease of its own, no shaping, no retry-until-it-works loop.  A
refusal is returned to the caller as a typed result, because the answer to
"the gateway refused my command" is a decision the caller has to make, not one
a transport wrapper may make by trying again.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from parcel_robot.bridge.protocol import (
    MAX_GATEWAY_PACKET_BYTES,
    MAX_LOCAL_TTL_MS,
    GatewayAckDispositionV1,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayCommandV1,
    GatewayHelloV1,
    GatewayStateQueryV1,
    GatewayStateV1,
    GatewayStopReportV1,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)

# ``typing.Self`` is 3.11+ and the dog's Orin NX runs JetPack's CPython 3.10
# (card HW-1).  ``from __future__ import annotations`` above makes the one use
# of the name a string at runtime, so no ``typing.Self`` object is ever built.
if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime
    from typing import Self

#: The body frame every V1 command is expressed in.  The gateway refuses any
#: other value at the DTO; naming it here keeps callers from inventing one.
BODY_FRAME_V1 = "base_link"

#: How much of its own TTL the client spends before it calls its authority
#: gone.  The gateway derives the real deadline from *its* clock at receipt, so
#: this local copy is deliberately the pessimistic one: it can only ever refuse
#: earlier than the gateway would, never later.
LOCAL_DEADLINE_MARGIN_S = 0.0


class MotionGatewayError(RuntimeError):
    """Base class for every failure this client reports."""


class GatewayUnavailableError(MotionGatewayError):
    """The gateway could not be reached, or the connection died."""


class GatewayAuthorityError(MotionGatewayError):
    """A motion command was attempted without a live explicit arm transaction."""


class GatewayProtocolError(MotionGatewayError):
    """The gateway answered with something this contract does not allow."""


@dataclass(frozen=True)
class GatewayIdentityV1:
    """Who answered, and in what state, at the moment the connection opened."""

    boot_epoch: str
    phase: str


@dataclass(frozen=True)
class ConnectResultV1:
    """The result of opening (or reopening) a connection. Always disarmed."""

    identity: GatewayIdentityV1
    armed: bool
    gateway_restarted: bool
    previous_boot_epoch: str


@dataclass(frozen=True)
class ArmResultV1:
    """The outcome of the one explicit arm transaction."""

    armed: bool
    reason: str
    boot_epoch: str
    local_ttl_ms: int
    authority_deadline_monotonic_s: float


@dataclass(frozen=True)
class CommandResultV1:
    """The outcome of one time-bounded refresh.

    ``admitted`` is *admission*, never motion truth: the gateway acks before
    the vendor write lands, by design (GWI-010).  ``clamped`` says the governor
    reduced the setpoint.
    """

    admitted: bool
    clamped: bool
    reason: str
    boot_epoch: str
    authority_deadline_monotonic_s: float


@dataclass(frozen=True)
class StopResultV1:
    """The gateway's own stop report, as a typed value."""

    boot_epoch: str
    stop_sequence: int
    reason: str
    stop_rpc_completed: bool
    stationary_confirmed: bool
    state_sequence: int

    @property
    def confirmed_stationary(self) -> bool:
        return self.stop_rpc_completed and self.stationary_confirmed


@dataclass(frozen=True)
class MotionStateV1:
    """One observation of the gateway and the body it writes to."""

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

    @property
    def armed(self) -> bool:
        return self.phase == "armed"

    @property
    def latched(self) -> bool:
        return self.phase == "latched"


class MotionGatewayClientV1:
    """The one production path from a runtime caller to the body."""

    def __init__(
        self,
        socket_path: str | Path,
        *,
        writer_id: str,
        timeout_s: float = 2.0,
    ) -> None:
        self._socket_path = Path(socket_path)
        self._writer_id = writer_id
        self._timeout_s = float(timeout_s)
        self._connection: socket.socket | None = None
        self._hello: GatewayHelloV1 | None = None
        self._sequence = 0
        self._armed = False
        self._deadline: float | None = None
        self._last_stop: StopResultV1 | None = None
        self._closed = False

    # -- lifecycle --------------------------------------------------------

    @classmethod
    def connect(
        cls,
        socket_path: str | Path,
        *,
        writer_id: str,
        timeout_s: float = 2.0,
    ) -> MotionGatewayClientV1:
        """Open the connection and read the gateway's hello. Arms nothing."""

        client = cls(socket_path, writer_id=writer_id, timeout_s=timeout_s)
        client._open()
        return client

    def close(self) -> None:
        """Drop the connection. The gateway stops the body when it notices."""

        self._closed = True
        self._disarm_locally()
        self._drop_connection()

    def reconnect(self, *, settle_timeout_s: float = 2.0) -> ConnectResultV1:
        """Reopen the connection. **Never re-acquires** — the caller must arm again.

        ``settle_timeout_s`` waits for the gateway to finish releasing the
        lease the dropped connection held, so the caller's own next
        ``acquire`` is not refused with ``writer_conflict``.  Waiting is a
        read: it polls :meth:`state` and stops as soon as no writer holds the
        lease.  It never sends an acquire.
        """

        previous = "" if self._hello is None else self._hello.boot_epoch
        self._disarm_locally()
        self._drop_connection()
        self._closed = False
        self._open()
        self._settle(settle_timeout_s)
        identity = self.identity
        return ConnectResultV1(
            identity=identity,
            # Structural, not a computed value: this constructor is the only
            # place a reconnect can report armed, and it is a literal.
            armed=False,
            gateway_restarted=bool(previous) and previous != identity.boot_epoch,
            previous_boot_epoch=previous,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    # -- observation ------------------------------------------------------

    @property
    def identity(self) -> GatewayIdentityV1:
        hello = self._hello
        if hello is None:
            raise GatewayUnavailableError("the client is not connected")
        return GatewayIdentityV1(boot_epoch=hello.boot_epoch, phase=str(hello.phase.value))

    @property
    def boot_epoch(self) -> str:
        return self.identity.boot_epoch

    @property
    def writer_id(self) -> str:
        return self._writer_id

    @property
    def armed(self) -> bool:
        """True only between a successful :meth:`acquire` and losing authority."""

        return self._armed and self._authority_remaining_s() > 0.0

    @property
    def authority_deadline_monotonic_s(self) -> float | None:
        return self._deadline

    def state(self) -> MotionStateV1:
        """Ask the gateway what it and the body are doing. Sends no authority."""

        self._sequence += 1
        response = self._exchange(GatewayStateQueryV1(sequence=self._sequence))
        if not isinstance(response, GatewayStateV1):
            raise GatewayProtocolError(
                f"state query answered with {type(response).__name__}"
            )
        return MotionStateV1(
            boot_epoch=response.boot_epoch,
            phase=str(response.phase.value),
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

    def last_stop_report(self) -> StopResultV1 | None:
        """The last stop report this client has seen, if any."""

        return self._last_stop

    # -- authority --------------------------------------------------------

    def acquire(self, *, local_ttl_ms: int = MAX_LOCAL_TTL_MS) -> ArmResultV1:
        """The explicit arm transaction. The only way this client becomes armed."""

        hello = self._require_hello()
        self._sequence += 1
        request = GatewayAcquireV1(
            writer_id=self._writer_id,
            boot_epoch=hello.boot_epoch,
            sequence=self._sequence,
            local_ttl_ms=int(local_ttl_ms),
            hashes=hello.required_hashes,
        )
        sent_at = time.monotonic()
        ack = self._acknowledge(request)
        if ack.disposition is not GatewayAckDispositionV1.ACCEPTED:
            self._disarm_locally()
            return ArmResultV1(
                armed=False,
                reason=ack.reason,
                boot_epoch=ack.boot_epoch,
                local_ttl_ms=int(local_ttl_ms),
                authority_deadline_monotonic_s=sent_at,
            )
        self._armed = True
        self._deadline = sent_at + int(local_ttl_ms) / 1000.0 - LOCAL_DEADLINE_MARGIN_S
        return ArmResultV1(
            armed=True,
            reason=ack.reason,
            boot_epoch=ack.boot_epoch,
            local_ttl_ms=int(local_ttl_ms),
            authority_deadline_monotonic_s=self._deadline,
        )

    def command(
        self,
        *,
        vx_mps: float = 0.0,
        vy_mps: float = 0.0,
        vyaw_rad_s: float = 0.0,
        local_ttl_ms: int = MAX_LOCAL_TTL_MS,
        task_id: str = "parcel-runtime",
        trace_id: str = "parcel-runtime",
    ) -> CommandResultV1:
        """One time-bounded refresh of the setpoint.

        Raises :class:`GatewayAuthorityError` — before anything is sent —
        when this client is not armed or its own authority deadline has
        passed.  It does not arm itself and does not retry.
        """

        hello = self._require_hello()
        if not self._armed:
            raise GatewayAuthorityError(
                "no motion authority: acquire() is the only way to arm, and it "
                "has not succeeded (or was lost) since this client last armed"
            )
        if self._authority_remaining_s() <= 0.0:
            self._disarm_locally()
            raise GatewayAuthorityError(
                "motion authority lapsed: the local TTL deadline passed, so a "
                "fresh explicit acquire() is required before commanding again"
            )
        self._sequence += 1
        request = GatewayCommandV1(
            writer_id=self._writer_id,
            boot_epoch=hello.boot_epoch,
            sequence=self._sequence,
            local_ttl_ms=int(local_ttl_ms),
            frame_id=BODY_FRAME_V1,
            vx_mps=float(vx_mps),
            vy_mps=float(vy_mps),
            vyaw_rad_s=float(vyaw_rad_s),
            task_id=task_id,
            trace_id=trace_id,
            hashes=hello.required_hashes,
        )
        sent_at = time.monotonic()
        ack = self._acknowledge(request)
        if ack.disposition is not GatewayAckDispositionV1.ACCEPTED:
            self._disarm_locally()
            return CommandResultV1(
                admitted=False,
                clamped=False,
                reason=ack.reason,
                boot_epoch=ack.boot_epoch,
                authority_deadline_monotonic_s=sent_at,
            )
        self._deadline = sent_at + int(local_ttl_ms) / 1000.0 - LOCAL_DEADLINE_MARGIN_S
        return CommandResultV1(
            admitted=True,
            clamped=ack.reason == "clamped",
            reason=ack.reason,
            boot_epoch=ack.boot_epoch,
            authority_deadline_monotonic_s=self._deadline,
        )

    def stop(self, *, reason: str = "client_stop", emergency: bool = False) -> StopResultV1:
        """Ask for an exact-zero stop. The gateway never refuses one."""

        hello = self._require_hello()
        self._sequence += 1
        request = GatewayStopV1(
            writer_id=self._writer_id,
            boot_epoch=hello.boot_epoch,
            sequence=self._sequence,
            reason=reason,
            emergency=bool(emergency),
        )
        response = self._exchange(request)
        if not isinstance(response, GatewayStopReportV1):
            raise GatewayProtocolError(
                f"stop answered with {type(response).__name__}"
            )
        # A stop always ends authority, whatever it reports.
        self._disarm_locally()
        result = StopResultV1(
            boot_epoch=response.boot_epoch,
            stop_sequence=response.stop_sequence,
            reason=response.reason,
            stop_rpc_completed=response.stop_rpc_completed,
            stationary_confirmed=response.stationary_confirmed,
            state_sequence=response.state_sequence,
        )
        self._last_stop = result
        return result

    # -- internals --------------------------------------------------------

    def _open(self) -> None:
        if self._closed:
            raise GatewayUnavailableError("this client has been closed")
        try:
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            connection.settimeout(self._timeout_s)
            connection.connect(str(self._socket_path))
        except OSError as exc:
            raise GatewayUnavailableError(
                f"cannot reach the motion gateway at {self._socket_path}: {exc}"
            ) from exc
        self._connection = connection
        hello = self._receive()
        if not isinstance(hello, GatewayHelloV1):
            self._drop_connection()
            raise GatewayProtocolError("the gateway did not open with GatewayHelloV1")
        if self._hello is not None and hello.boot_epoch != self._hello.boot_epoch:
            # A new boot epoch is a restart.  The per-boot sequence fence is
            # new too, but continuing to count is always safe: the fence only
            # ever refuses a sequence that does not increase.
            self._last_stop = None
        self._hello = hello
        # Belt and braces.  Nothing above can arm; this makes it structural.
        self._armed = False
        self._deadline = None

    def _settle(self, timeout_s: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            if not self.state().writer_id:
                return
            time.sleep(0.005)

    def _drop_connection(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    def _disarm_locally(self) -> None:
        self._armed = False
        self._deadline = None

    def _authority_remaining_s(self) -> float:
        deadline = self._deadline
        if deadline is None:
            return 0.0
        return deadline - time.monotonic()

    def _require_hello(self) -> GatewayHelloV1:
        hello = self._hello
        if hello is None or self._connection is None:
            raise GatewayUnavailableError("the client is not connected")
        return hello

    def _acknowledge(
        self,
        request: GatewayAcquireV1 | GatewayCommandV1,
    ) -> GatewayAckV1:
        response = self._exchange(request)
        if not isinstance(response, GatewayAckV1):
            raise GatewayProtocolError(
                f"{request.kind} answered with {type(response).__name__}"
            )
        if response.acknowledged_sequence != request.sequence:
            raise GatewayProtocolError(
                "the gateway acknowledged a different sequence than was sent"
            )
        return response

    def _exchange(
        self,
        request: GatewayAcquireV1 | GatewayCommandV1 | GatewayStopV1 | GatewayStateQueryV1,
    ) -> object:
        """The single private send/receive. Nothing public reaches the wire."""

        connection = self._connection
        if connection is None:
            raise GatewayUnavailableError("the client is not connected")
        try:
            connection.sendall(encode_gateway_message(request))
        except OSError as exc:
            self._disarm_locally()
            self._drop_connection()
            raise GatewayUnavailableError(f"the gateway connection died: {exc}") from exc
        return self._receive()

    def _receive(self) -> object:
        connection = self._connection
        if connection is None:
            raise GatewayUnavailableError("the client is not connected")
        try:
            packet = connection.recv(MAX_GATEWAY_PACKET_BYTES + 1)
        except OSError as exc:
            self._disarm_locally()
            self._drop_connection()
            raise GatewayUnavailableError(f"the gateway connection died: {exc}") from exc
        if not packet:
            self._disarm_locally()
            self._drop_connection()
            raise GatewayUnavailableError("the gateway closed the connection")
        try:
            return decode_gateway_message(packet)
        except (TypeError, ValueError) as exc:
            self._disarm_locally()
            self._drop_connection()
            raise GatewayProtocolError(f"the gateway sent an unreadable message: {exc}") from exc
