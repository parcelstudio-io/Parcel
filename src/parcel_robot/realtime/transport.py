"""Transport seam for the Realtime lane (card R1, task_7).

WHY A SEAM AT ALL
-----------------
``.parcel`` has no ``websockets``, no ``aiohttp``, no ``openai``, and no
``OPENAI_API_KEY``. R1 is therefore built entirely against an in-process pair
of queues joined to :class:`~parcel_robot.realtime.fake_server.FakeRealtimeServer`.
The live WebSocket transport is R1.5 and is a *new implementation of this
Protocol*, not an edit to the lane: everything the lane knows about the network
is ``send`` / ``receive`` / ``close``.

WHY IT CARRIES MAPPINGS, NOT DATACLASSES
----------------------------------------
The wire carries JSON objects. Making the transport speak mappings means the
fake server can inject a genuinely malformed frame (one the typed codec must
refuse) — which is impossible if the transport only accepts already-valid
dataclasses. ``send`` accepts either: a :class:`ClientEvent` is serialized
through its own ``to_payload``.

WHY THERE ARE NO THREADS
------------------------
Every R1 test must be deterministic and offline. ``receive`` never blocks: it
returns the next frame or ``None``. Time enters only through an injected
``clock``, so a stall is expressed by advancing a number rather than sleeping.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable

from .protocol import ClientEvent


class TransportClosed(RuntimeError):
    """The peer hung up. Raised on ``receive`` once the backlog is drained."""


@runtime_checkable
class Transport(Protocol):
    """The only thing the lane knows about a network."""

    def send(self, event: ClientEvent | Mapping[str, Any]) -> None:
        """Hand one frame to the peer. Raises ``TransportClosed`` when down."""

    def receive(self) -> Mapping[str, Any] | None:
        """Next inbound frame, or ``None`` when nothing is pending."""

    def close(self) -> None:
        """Hang up. Idempotent."""

    @property
    def closed(self) -> bool: ...


def payload_of(event: ClientEvent | Mapping[str, Any]) -> Mapping[str, Any]:
    """Normalize either half of the ``send`` contract to a wire mapping."""

    if isinstance(event, ClientEvent):
        return event.to_payload()
    if isinstance(event, Mapping):
        return event
    raise TypeError(f"realtime transport cannot send {type(event).__name__}")


class InProcessTransport:
    """One end of a queue pair. Sending appends to the *peer's* inbox.

    ``sent`` keeps every outbound frame for assertions; it is the record a test
    reads to prove that a truncate carried played-milliseconds, or that the
    memory tail went up before any audio did.
    """

    def __init__(self, *, name: str, clock: Callable[[], float] = time.monotonic):
        self.name = name
        self._clock = clock
        self._inbox: deque[Mapping[str, Any]] = deque()
        self._peer: InProcessTransport | None = None
        self._closed = False
        self.sent: list[Mapping[str, Any]] = []
        self.last_send_at: float | None = None
        self.last_receive_at: float | None = None

    # -- wiring ----------------------------------------------------------
    def attach(self, peer: InProcessTransport) -> None:
        self._peer = peer

    # -- Transport -------------------------------------------------------
    @property
    def closed(self) -> bool:
        """True once either end hung up — a socket has no one-sided liveness."""

        peer = self._peer
        return self._closed or (peer is not None and peer._closed)

    def send(self, event: ClientEvent | Mapping[str, Any]) -> None:
        if self.closed:
            raise TransportClosed(f"{self.name} transport is closed")
        payload = payload_of(event)
        self.sent.append(payload)
        self.last_send_at = self._clock()
        peer = self._peer
        if peer is not None:
            peer._inbox.append(payload)

    def receive(self) -> Mapping[str, Any] | None:
        """Drain first, then report the hang-up.

        Order matters: a server that emits three frames and then disconnects
        mid-turn must deliver those three frames before the lane sees
        ``TransportClosed``, or the disconnect test would be indistinguishable
        from a server that said nothing at all.
        """

        if self._inbox:
            self.last_receive_at = self._clock()
            return self._inbox.popleft()
        if self.closed:
            raise TransportClosed(f"{self.name} transport is closed")
        return None

    def drain(self) -> list[Mapping[str, Any]]:
        """Every pending inbound frame, oldest first. Never raises."""

        frames = list(self._inbox)
        self._inbox.clear()
        if frames:
            self.last_receive_at = self._clock()
        return frames

    def close(self) -> None:
        self._closed = True

    # -- test affordance --------------------------------------------------
    @property
    def pending(self) -> int:
        return len(self._inbox)


def transport_pair(
    *, clock: Callable[[], float] = time.monotonic
) -> tuple[InProcessTransport, InProcessTransport]:
    """``(lane_end, server_end)`` sharing one injected clock."""

    lane = InProcessTransport(name="lane", clock=clock)
    server = InProcessTransport(name="server", clock=clock)
    lane.attach(server)
    server.attach(lane)
    return lane, server


__all__ = [
    "InProcessTransport",
    "Transport",
    "TransportClosed",
    "payload_of",
    "transport_pair",
]
