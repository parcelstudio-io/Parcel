"""Live WebSocket transport for the Realtime lane (card R1.5, task_1).

WHAT THIS IS
------------
R1 shipped the ``Transport`` seam and exactly one implementation of it: an
in-process queue pair. This is the second implementation — a real socket to the
hosted Realtime API — satisfying the same four-member Protocol so that
``lane.py`` needs no edit at all. Everything the lane knows about the network is
still ``send`` / ``receive`` / ``close`` / ``closed``.

WHY A READER THREAD
-------------------
The lane's design assumes ``receive()`` never blocks: ``pump()`` calls it in a
loop until it returns ``None``. A socket cannot offer that, so one daemon thread
owns ``recv`` and parks decoded frames in a deque. ``receive()`` only ever
touches the deque under a lock, and returns ``None`` the moment it is empty.

The ordering ``InProcessTransport.receive`` documents is reproduced exactly:
**drain first, then report the hang-up**. A server that emits three frames and
then disconnects mid-turn must deliver those three frames before the lane sees
``TransportClosed``, or a disconnect would be indistinguishable from a server
that said nothing at all. Here that matters more than it did in R1, because the
frame a provider sends immediately before hanging up is usually the one that
explains why.

WHY THE DEQUE IS BOUNDED
------------------------
A hosted response is a burst of 24 kHz audio deltas. If the owner of the lane
stops pumping, an unbounded buffer turns a stalled turn into a memory leak. The
buffer has a hard bound and drops the OLDEST frame on overflow, counting every
drop. Oldest-first is deliberate: the frames that describe the current state
(``response.done``, ``error``) are the newest ones. The quota / auth
classification is also taken off an ``error`` frame *before* it is enqueued, so
the diagnosis survives even when the frame itself is later dropped.

WHY THE CREDENTIAL IS A NAME, NOT A VALUE
-----------------------------------------
The constructor takes an environment variable NAME. The value is read inside
``open()``, lives in one local variable and the header mapping handed to
``connect()``, and is never stored on this object. Every message this module
composes passes through :func:`redact`, and library failures are re-raised
``from None`` so that a chained exception can never print an ``Authorization``
header into a traceback. The transport also refuses to put a credential on a
non-TLS URL unless a caller explicitly opts in (a loopback test server does).

WHY IT NEVER RETRIES
--------------------
Reconnect, watchdog and memory-tail reinjection belong to ``RealtimeLane``.
This module reports and stops. It also refuses to *mis*report: a hang-up is
``TransportClosed`` (which the lane answers with a reconnect), while an
authentication or quota refusal is a typed error that is deliberately **not** a
``TransportClosed``, so the lane's reconnect path cannot turn a billing wall
into a retry storm. A billing wall is an owner action, and the caller has to
see it as one.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedOK,
    InvalidStatus,
    WebSocketException,
)
from websockets.sync.client import ClientConnection, connect

from .protocol import ClientEvent
from .transport import TransportClosed, payload_of

LOGGER = logging.getLogger(__name__)

#: The hosted endpoint. The model rides as a query parameter and the credential
#: rides as a header, so a URL built by :func:`realtime_url` is safe to log.
DEFAULT_REALTIME_URL = "wss://api.openai.com/v1/realtime"

#: The environment variable NAME the transport reads at connect time. Never a
#: value: see the module docstring.
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"

#: Inbound backlog bound, in frames. ~512 audio deltas is roughly 15-25 s of
#: hosted speech — long enough that only a genuinely stalled caller overflows.
DEFAULT_MAX_INBOUND = 512

#: How long the reader parks in ``recv`` before re-checking the stop flag. This
#: bounds shutdown latency; it is never a correctness wait.
DEFAULT_POLL_S = 0.05

DEFAULT_OPEN_TIMEOUT_S = 30.0
DEFAULT_CLOSE_TIMEOUT_S = 5.0

#: What a redacted secret looks like in any string this module produces.
REDACTED = "<redacted>"

#: Shapes a credential can take in text that came from somewhere else. Belt and
#: braces behind "never interpolate the value in the first place".
_SECRET_SHAPES = (
    re.compile(r"(?i)\bbearer\s+[^\s\"']+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{4,}"),
)

#: ``error`` frame codes that mean "the account cannot pay for this". The state
#: this account is in as of 2026-08-17.
QUOTA_ERROR_CODES = frozenset(
    {
        "insufficient_quota",
        "billing_hard_limit_reached",
        "quota_exceeded",
        "rate_limit_exceeded",
    }
)

#: ``error`` frame codes that mean "this credential may not do that".
AUTH_ERROR_CODES = frozenset(
    {
        "authentication_error",
        "insufficient_permissions",
        "invalid_api_key",
        "invalid_authentication",
        "permission_denied",
        "unauthorized",
    }
)

#: 1013 TRY_AGAIN_LATER is what the provider closes with when the account is out
#: of credit — verified live on 2026-08-17.
CLOSE_TRY_AGAIN_LATER = 1013

QUOTA_CLOSE_CODES = frozenset({CLOSE_TRY_AGAIN_LATER})

#: 3000/3003 are the IANA-registered Unauthorized / Forbidden WebSocket close
#: codes; 4001/4003 are the common private-range spellings of the same thing.
AUTH_CLOSE_CODES = frozenset({3000, 3003, 4001, 4003})

#: Handshake statuses. A rejection here never even opens a socket.
HTTP_AUTH_STATUS = frozenset({401, 403})
HTTP_QUOTA_STATUS = frozenset({402, 429})

#: ``_Down.kind`` vocabulary.
KIND_CLOSED = "closed"
KIND_AUTH = "auth"
KIND_QUOTA = "quota"


class RealtimeTransportError(RuntimeError):
    """The live transport refused, and names which wall it hit.

    A ``RuntimeError`` like ``TransportClosed`` — but deliberately *not* a
    subclass of it. ``RealtimeLane.pump`` answers ``TransportClosed`` with a
    reconnect; a credential or billing refusal must not be answered that way.
    """


class RealtimeConnectError(RealtimeTransportError):
    """The socket never opened: DNS, refused, timed out, bad handshake."""


class RealtimeAuthError(RealtimeTransportError):
    """The credential was missing, malformed, or rejected (401/403-shaped)."""


class RealtimeQuotaError(RealtimeTransportError):
    """The account cannot pay. ``insufficient_quota`` and/or close 1013.

    This is an owner billing action, not a bug and not a transient fault, which
    is exactly why it is a distinct type that no retry loop catches by accident.
    """


def redact(text: object, *, secret: str | None = None) -> str:
    """Scrub credentials out of one string. Every message here goes through it."""

    out = str(text)
    if secret:
        out = out.replace(secret, REDACTED)
    for shape in _SECRET_SHAPES:
        out = shape.sub(REDACTED, out)
    return out


def realtime_url(model: str, *, base: str = DEFAULT_REALTIME_URL) -> str:
    """The hosted URL for one model. Carries no credential, only a model name."""

    return f"{base}?{urlencode({'model': model})}"


@dataclass(frozen=True)
class _Down:
    """Why the socket is no longer usable. Written once, first writer wins."""

    kind: str
    message: str


def _error_for(down: _Down) -> Exception:
    """The exception a given terminal state raises, fresh on every call."""

    if down.kind == KIND_QUOTA:
        return RealtimeQuotaError(down.message)
    if down.kind == KIND_AUTH:
        return RealtimeAuthError(down.message)
    return TransportClosed(down.message)


class WebSocketTransport:
    """One live Realtime socket, presented as R1's ``Transport``.

    Construct, then :meth:`open`. Or use :func:`websocket_transport_factory`,
    which is the shape ``RealtimeLane(transport_factory=...)`` wants.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        url: str | None = None,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        name: str = "live",
        max_inbound: int = DEFAULT_MAX_INBOUND,
        open_timeout_s: float = DEFAULT_OPEN_TIMEOUT_S,
        close_timeout_s: float = DEFAULT_CLOSE_TIMEOUT_S,
        poll_s: float = DEFAULT_POLL_S,
        allow_insecure: bool = False,
        extra_headers: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if url is None:
            if not model:
                raise RealtimeTransportError(
                    "WebSocketTransport needs either an explicit url or a model name"
                )
            url = realtime_url(model)
        if int(max_inbound) < 1:
            raise RealtimeTransportError(f"max_inbound must be >= 1, got {max_inbound!r}")

        self.name = name
        self._url = url
        self._api_key_env = api_key_env
        self._max_inbound = int(max_inbound)
        self._open_timeout_s = float(open_timeout_s)
        self._close_timeout_s = float(close_timeout_s)
        self._poll_s = float(poll_s)
        self._allow_insecure = bool(allow_insecure)
        self._extra_headers = dict(extra_headers or {})
        self._clock = clock

        self._lock = threading.RLock()
        self._arrival = threading.Event()
        self._stop = threading.Event()
        self._inbox: deque[Mapping[str, Any]] = deque(maxlen=self._max_inbound)
        self._conn: ClientConnection | None = None
        self._thread: threading.Thread | None = None
        self._down: _Down | None = None
        self._closed = False
        self._quota_note: str | None = None
        self._auth_note: str | None = None

        #: Counters, not payload logs. A live session's frames are base64 audio;
        #: keeping them the way ``InProcessTransport.sent`` does would be a leak.
        self.sent_frames = 0
        self.received_frames = 0
        self.dropped_frames = 0
        self.decode_errors = 0
        self.last_send_at: float | None = None
        self.last_receive_at: float | None = None
        self.connected_at: float | None = None

    # ------------------------------------------------------------------ open
    def open(self) -> WebSocketTransport:
        """Read the credential, connect, start the reader. Returns ``self``."""

        with self._lock:
            if self._conn is not None or self._closed:
                raise RealtimeTransportError(
                    f"{self.name} transport has already been opened; build a new one"
                )

        key = os.environ.get(self._api_key_env, "").strip()
        if not key:
            # Names the variable, never a value — and says where the value is
            # supposed to live, which is outside this repository.
            raise RealtimeAuthError(
                f"realtime credential unavailable: environment variable "
                f"{self._api_key_env!r} is unset or empty. The key belongs in a "
                f"file outside the repo (mode 600) and is loaded into the "
                f"environment before the process starts."
            )
        if not self._url.startswith("wss://") and not self._allow_insecure:
            raise RealtimeAuthError(
                f"refusing to send the {self._api_key_env} credential to "
                f"{redact(self._url)}: the URL is not TLS. Pass allow_insecure=True "
                f"only for a loopback test server."
            )

        headers = {"Authorization": f"Bearer {key}", **self._extra_headers}
        try:
            conn = connect(
                self._url,
                additional_headers=headers,
                open_timeout=self._open_timeout_s,
                close_timeout=self._close_timeout_s,
            )
        except InvalidStatus as error:
            # `from None`: the chained exception's own text is not ours to
            # control, and a traceback prints causes.
            raise self._handshake_error(int(error.response.status_code)) from None
        except TimeoutError as error:
            raise RealtimeConnectError(
                f"realtime connect to {redact(self._url)} timed out after "
                f"{self._open_timeout_s:.0f}s: {redact(error, secret=key)}"
            ) from None
        except (WebSocketException, OSError) as error:
            raise RealtimeConnectError(
                f"realtime connect to {redact(self._url)} failed: "
                f"{type(error).__name__}: {redact(error, secret=key)}"
            ) from None

        with self._lock:
            self._conn = conn
            self.connected_at = self._clock()
        self._stop.clear()
        thread = threading.Thread(
            target=self._read_loop,
            name=f"realtime-ws-{self.name}",
            daemon=True,
        )
        self._thread = thread
        thread.start()
        LOGGER.info(
            "realtime websocket open: url=%s credential=$%s",
            redact(self._url),
            self._api_key_env,
        )
        return self

    def _handshake_error(self, status: int) -> RealtimeTransportError:
        """Map a rejected HTTP upgrade onto the typed vocabulary."""

        if status in HTTP_AUTH_STATUS:
            return RealtimeAuthError(
                f"realtime handshake rejected with HTTP {status}: the credential in "
                f"${self._api_key_env} was not accepted (its value is never logged)"
            )
        if status in HTTP_QUOTA_STATUS:
            return RealtimeQuotaError(
                f"realtime handshake rejected with HTTP {status}: the account is out "
                f"of quota. This is an owner billing action, not a transport fault."
            )
        return RealtimeConnectError(
            f"realtime handshake rejected with HTTP {status} at {redact(self._url)}"
        )

    # ------------------------------------------------------------- Transport
    @property
    def closed(self) -> bool:
        """True once EITHER end hung up — a socket has no one-sided liveness."""

        with self._lock:
            return self._closed or self._down is not None

    def send(self, event: ClientEvent | Mapping[str, Any]) -> None:
        """Hand one frame to the provider. Raises the typed reason when down."""

        with self._lock:
            down = self._down
            conn = self._conn
        if down is not None:
            raise _error_for(down)
        if conn is None:
            raise TransportClosed(f"{self.name} transport is not open")

        text = json.dumps(dict(payload_of(event)))
        try:
            conn.send(text)
        except ConnectionClosed as error:
            raise _error_for(self._close_down(error)) from None
        except (WebSocketException, OSError) as error:
            down = self._go_down(
                KIND_CLOSED,
                f"realtime send failed: {type(error).__name__}: {error}",
            )
            raise _error_for(down) from None
        with self._lock:
            self.sent_frames += 1
            self.last_send_at = self._clock()

    def receive(self) -> Mapping[str, Any] | None:
        """Drain first, then report the hang-up. Never blocks, never sleeps.

        The ordering is copied from ``InProcessTransport.receive`` on purpose:
        buffered frames come out before ``TransportClosed`` (or its typed
        subclass-free cousins) so a mid-turn disconnect still delivers the turn.
        """

        with self._lock:
            # NO early `if self._down: raise` here. That check used to sit at
            # the top of this block and it silently discarded every buffered
            # frame the moment the reader thread recorded a hang-up — the exact
            # opposite of this method's contract, and invisible in tests because
            # `_down` is set ASYNCHRONOUSLY: whether a frame or the close won
            # the race depended on machine load. Found 2026-08-17 when a
            # concurrent build made the loser win (auditor's note, task_1).
            if self._inbox:
                frame = self._inbox.popleft()
                self.last_receive_at = self._clock()
                self._mark()
                return frame
            down = self._down
            self._mark()
        if down is not None:
            raise _error_for(down)
        return None

    def close(self) -> None:
        """Hang up. Idempotent, safe from any thread, never raises."""

        with self._lock:
            already = self._closed
            self._closed = True
            conn = self._conn
        if conn is not None and not already:
            self._stop.set()
            try:
                conn.close()
            except (WebSocketException, OSError) as error:  # pragma: no cover - defensive
                LOGGER.debug("realtime close raised: %s", redact(error))
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._close_timeout_s)
        self._go_down(KIND_CLOSED, f"{self.name} transport closed locally")
        self._arrival.set()

    # ------------------------------------------------------- reader plumbing
    def _read_loop(self) -> None:
        """Own ``recv`` on one daemon thread. The only place frames are born."""

        conn = self._conn
        if conn is None:  # pragma: no cover - open() always sets it first
            return
        while not self._stop.is_set():
            try:
                raw = conn.recv(timeout=self._poll_s)
            except TimeoutError:
                continue
            except ConnectionClosed as error:
                self._close_down(error)
                return
            except (WebSocketException, OSError) as error:
                self._go_down(
                    KIND_CLOSED,
                    f"realtime socket failed: {type(error).__name__}: {error}",
                )
                return
            self._accept(raw)

    def _accept(self, raw: str | bytes) -> None:
        """Decode one wire frame into the backlog, or count it as garbage."""

        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError) as error:
            with self._lock:
                self.decode_errors += 1
            LOGGER.warning("realtime frame is not JSON, dropped: %s", redact(error))
            return
        if not isinstance(decoded, Mapping):
            with self._lock:
                self.decode_errors += 1
            LOGGER.warning(
                "realtime frame decoded to %s, not an object; dropped",
                type(decoded).__name__,
            )
            return

        # Classify BEFORE enqueueing: an overflow that drops this frame must not
        # also drop the reason the session is about to die.
        self._note_error_frame(decoded)
        with self._lock:
            if len(self._inbox) >= self._max_inbound:
                self.dropped_frames += 1
                if self.dropped_frames == 1:
                    LOGGER.warning(
                        "realtime inbound backlog full at %d frames; dropping oldest",
                        self._max_inbound,
                    )
            self._inbox.append(decoded)
            self.received_frames += 1
            self._mark()

    def _note_error_frame(self, frame: Mapping[str, Any]) -> None:
        """Remember a provider ``error`` frame's meaning, redacted."""

        if str(frame.get("type", "")) != "error":
            return
        detail = frame.get("error")
        body: Mapping[str, Any] = detail if isinstance(detail, Mapping) else frame
        codes = {str(body.get(key, "")).strip().lower() for key in ("code", "type")}
        message = redact(str(body.get("message", "")).strip() or "no message")
        with self._lock:
            if codes & QUOTA_ERROR_CODES:
                self._quota_note = message
                LOGGER.warning("realtime provider reported a quota error: %s", message)
            elif codes & AUTH_ERROR_CODES:
                self._auth_note = message
                LOGGER.warning("realtime provider reported an auth error: %s", message)

    def _close_down(self, error: ConnectionClosed) -> _Down:
        """Turn a websockets close into one of the three typed outcomes."""

        frame = error.rcvd or error.sent
        code = None if frame is None else int(frame.code)
        reason = "" if frame is None else str(frame.reason)
        detail = f"close code {code}, reason {redact(reason)!r}"
        with self._lock:
            quota_note = self._quota_note
            auth_note = self._auth_note

        if quota_note is not None or code in QUOTA_CLOSE_CODES:
            said = quota_note or "no error frame, close code 1013 (try again later)"
            return self._go_down(
                KIND_QUOTA,
                f"realtime session refused for quota ({detail}); provider said: "
                f"{said}. This is an account billing state, not a transport fault "
                f"and not something a reconnect can fix.",
            )
        if auth_note is not None or code in AUTH_CLOSE_CODES:
            said = auth_note or "no error frame"
            return self._go_down(
                KIND_AUTH,
                f"realtime session refused authentication ({detail}); provider said: "
                f"{said}. The credential came from ${self._api_key_env}.",
            )
        if isinstance(error, ConnectionClosedOK) or code in (1000, 1001):
            return self._go_down(KIND_CLOSED, f"realtime peer hung up ({detail})")
        return self._go_down(KIND_CLOSED, f"realtime socket closed abnormally ({detail})")

    def _go_down(self, kind: str, message: str) -> _Down:
        """Record the terminal state. First writer wins; every message redacted."""

        with self._lock:
            if self._down is None:
                self._down = _Down(kind=kind, message=redact(message))
                LOGGER.info("realtime transport down (%s): %s", kind, self._down.message)
            self._mark()
            return self._down

    def _mark(self) -> None:
        """Keep :meth:`wait` honest. Callers already hold the lock."""

        if self._inbox or self._down is not None:
            self._arrival.set()
        else:
            self._arrival.clear()

    # ---------------------------------------------------------- affordances
    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._inbox)

    @property
    def down_kind(self) -> str | None:
        """``closed`` / ``auth`` / ``quota``, or ``None`` while healthy."""

        with self._lock:
            return None if self._down is None else self._down.kind

    @property
    def down_reason(self) -> str | None:
        with self._lock:
            return None if self._down is None else self._down.message

    def wait(self, timeout: float | None = None) -> bool:
        """Block until a frame is pending or the socket is down. Consumes nothing.

        A caller with its own loop can use this instead of polling
        :meth:`receive`; the tests use it so that nothing waits on a clock.
        """

        return self._arrival.wait(timeout)

    def diagnostics(self) -> dict[str, object]:
        """What an operator panel would show. Contains no credential."""

        with self._lock:
            return {
                "name": self.name,
                "url": redact(self._url),
                "credential_env": self._api_key_env,
                "open": self._conn is not None,
                "closed": self._closed or self._down is not None,
                "pending": len(self._inbox),
                "max_inbound": self._max_inbound,
                "sent_frames": self.sent_frames,
                "received_frames": self.received_frames,
                "dropped_frames": self.dropped_frames,
                "decode_errors": self.decode_errors,
                "down_kind": None if self._down is None else self._down.kind,
                "down_reason": None if self._down is None else self._down.message,
            }

    def __repr__(self) -> str:
        with self._lock:
            if self._closed or self._down is not None:
                state = "closed"
            elif self._conn is None:
                state = "unopened"
            else:
                state = "open"
            pending = len(self._inbox)
        return (
            f"<WebSocketTransport name={self.name!r} url={redact(self._url)!r} "
            f"credential_env={self._api_key_env!r} state={state} pending={pending} "
            f"dropped={self.dropped_frames}>"
        )


def websocket_transport_factory(
    *,
    model: str | None = None,
    url: str | None = None,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    **kwargs: Any,
) -> Callable[[], WebSocketTransport]:
    """A ``transport_factory`` for ``RealtimeLane``: one fresh socket per call.

    The lane builds a new transport on every connect and every reconnect, which
    is exactly right for a socket — there is nothing to reuse after a hang-up.
    """

    def _factory() -> WebSocketTransport:
        return WebSocketTransport(model=model, url=url, api_key_env=api_key_env, **kwargs).open()

    return _factory


__all__ = [
    "AUTH_CLOSE_CODES",
    "AUTH_ERROR_CODES",
    "CLOSE_TRY_AGAIN_LATER",
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_MAX_INBOUND",
    "DEFAULT_REALTIME_URL",
    "QUOTA_CLOSE_CODES",
    "QUOTA_ERROR_CODES",
    "REDACTED",
    "RealtimeAuthError",
    "RealtimeConnectError",
    "RealtimeQuotaError",
    "RealtimeTransportError",
    "WebSocketTransport",
    "realtime_url",
    "redact",
    "websocket_transport_factory",
]
