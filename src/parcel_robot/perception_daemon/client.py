"""Client side of the perception daemon — a ``Detector`` that cannot crash you.

Card P1-A. :class:`DaemonDetector` satisfies
:class:`parcel_robot.detection_adapter.pixel_detections.Detector` exactly, so
``CameraIngress(detector=DaemonDetector(...))`` needs **no change to the
ingress at all** — which is why this card touches ``ingress.py`` zero times
(P1-B owns it).

The degradation contract, which is the whole reason for the process boundary
-----------------------------------------------------------------------------
When the daemon is not there — never started, crashed, restarting, mid-model-load
— :meth:`DaemonDetector.detect` returns ``[]`` and sets :attr:`~DaemonDetector.stale`.
It does **not** raise.

That is deliberate and it is the opposite of what a library normally does.
``CameraIngress.poll_once`` catches detector exceptions, counts one in
``stats.errors``, and returns ``None`` — leaving the last good candidate buffer
in place. So a raising detector produces a mission that keeps navigating on
STALE candidates while nothing above it can tell that the eye stopped. Returning
an empty list with ``stale`` set publishes an honest empty frame ("I looked and
the detector was unavailable") and keeps :attr:`consecutive_failures` visible in
the health snapshot, where an operator and a supervisor can both read it.

Reconnection is lazy and rate-limited: after a failure the client waits
:attr:`retry_interval_s` before spending another connect on the reactive path,
so a dead daemon costs one failed ``connect()`` every few seconds rather than
one per frame. A daemon that comes back is picked up by the next attempt with
**no restart of this process** — the pre-registered C7/L3 row.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Self

import numpy as np

from parcel_robot.perception_daemon.protocol import (
    OP_DETECT,
    OP_EMBED_IMAGE,
    OP_EMBED_TEXT,
    OP_HEALTH,
    OP_SHUTDOWN,
    DaemonUnavailable,
    ProtocolError,
    decode,
    default_socket_path,
    detection_from_wire,
    encode,
    normalize_query,
    request_header,
)

logger = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT_S = 2.0
DEFAULT_REQUEST_TIMEOUT_S = 10.0
#: Gap between reconnect attempts after a failure. One dead-daemon connect per
#: this interval, not one per frame.
DEFAULT_RETRY_INTERVAL_S = 2.0


@dataclass
class _DaemonResolution:
    """Mirrors ``ProviderResolution``'s two fields the ingress actually reads.

    ``CameraDetectionFrame`` records ``provider_profile`` and
    ``active_providers`` off ``detector.resolution`` so a latency number can
    never be read without knowing which provider produced it. The daemon
    reports both on every ``detect`` response; this object carries them across
    the process boundary so that guarantee survives it.
    """

    selected: str | None = None
    execution_providers: tuple[str, ...] = ()


class DaemonClient:
    """One AF_UNIX connection to a :class:`~.server.PerceptionDaemon`.

    Raises :class:`DaemonUnavailable` when the daemon is unreachable. The
    degrade-instead-of-raise policy lives one layer up, in
    :class:`DaemonDetector`, so a caller that WANTS the error (a health probe, a
    launcher readiness check) can still have it.
    """

    def __init__(
        self,
        socket_path: str | None = None,
        *,
        connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
        request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    ) -> None:
        self.socket_path = str(socket_path or default_socket_path())
        self.connect_timeout_s = float(connect_timeout_s)
        self.request_timeout_s = float(request_timeout_s)
        self._sock: socket.socket | None = None
        self._request_id = 0
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        if self._sock is not None:
            return
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout_s)
        try:
            sock.connect(self.socket_path)
        except OSError as exc:
            sock.close()
            raise DaemonUnavailable(
                f"cannot reach the perception daemon at {self.socket_path}: {exc}"
            ) from exc
        sock.settimeout(self.request_timeout_s)
        self._sock = sock

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            sock.close()
        except OSError:  # pragma: no cover - defensive
            pass

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(
        self,
        op: str,
        *,
        arrays: dict[str, np.ndarray] | None = None,
        **fields: Any,
    ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        """Send one request, read one response. Errors come back as raises.

        A transport failure DROPS the connection before raising: a half-written
        request would otherwise desynchronize the stream and the next response
        would be read against the wrong request id.
        """

        with self._lock:
            self.connect()
            sock = self._sock
            assert sock is not None
            self._request_id += 1
            request_id = self._request_id
            header = request_header(op, request_id, **fields)
            try:
                sock.sendall(encode(header, arrays))
                response, payload = decode(sock)
            except (DaemonUnavailable, OSError) as exc:
                self.close()
                raise DaemonUnavailable(f"{op} failed: {exc}") from exc
            except ProtocolError:
                self.close()
                raise
        if int(response.get("id", -1)) != request_id:
            self.close()
            raise ProtocolError(
                f"response id {response.get('id')!r} does not match request {request_id}"
            )
        if response.get("status") != "ok":
            raise DaemonRequestFailed(
                str(response.get("error", "daemon refused the request")),
                kind=str(response.get("kind", "error")),
            )
        return response, payload

    # -- typed operations ---------------------------------------------------
    def health(self) -> dict[str, Any]:
        response, _ = self.request(OP_HEALTH)
        response.pop("v", None)
        response.pop("id", None)
        response.pop("op", None)
        response.pop("status", None)
        return response

    def detect(
        self,
        rgb: np.ndarray,
        query: Sequence[str] | str,
        *,
        depth: np.ndarray | None = None,
    ) -> dict[str, Any]:
        phrases = normalize_query(query)
        if not phrases:
            raise ProtocolError("detect requires a non-empty query batch")
        arrays: dict[str, np.ndarray] = {"rgb": np.ascontiguousarray(rgb, dtype=np.uint8)}
        if depth is not None:
            arrays["depth"] = np.ascontiguousarray(depth, dtype=np.float32)
        response, _ = self.request(OP_DETECT, arrays=arrays, query=list(phrases))
        return response

    def embed_image(self, rgb: np.ndarray) -> np.ndarray:
        _, payload = self.request(
            OP_EMBED_IMAGE, arrays={"rgb": np.ascontiguousarray(rgb, dtype=np.uint8)}
        )
        return payload["embedding"]

    def embed_text(self, text: str) -> np.ndarray:
        _, payload = self.request(OP_EMBED_TEXT, text=str(text))
        return payload["embedding"]

    def shutdown(self) -> None:
        self.request(OP_SHUTDOWN)
        self.close()


class DaemonRequestFailed(RuntimeError):
    """The daemon answered, and the answer was a refusal."""

    def __init__(self, message: str, *, kind: str = "error") -> None:
        super().__init__(message)
        self.kind = kind


class DaemonDetector:
    """``Detector`` backed by the daemon, degrading to empty-and-stale.

    Satisfies the ``Detector`` protocol (``name`` + ``detect(*, rgb, depth,
    seg, query)``) and additionally exposes ``resolution`` so published
    ``CameraDetectionFrame`` rows keep naming the provider that answered.
    """

    def __init__(
        self,
        socket_path: str | None = None,
        *,
        name: str = "owlv2-daemon",
        connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
        request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
        retry_interval_s: float = DEFAULT_RETRY_INTERVAL_S,
        clock: Any = time.monotonic,
    ) -> None:
        self.name = str(name)
        self.retry_interval_s = float(retry_interval_s)
        self.resolution = _DaemonResolution()
        self._client = DaemonClient(
            socket_path,
            connect_timeout_s=connect_timeout_s,
            request_timeout_s=request_timeout_s,
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._stale = True
        self._next_attempt_at = 0.0
        self._consecutive_failures = 0
        self._requests = 0
        self._degraded_requests = 0
        self._last_error: str | None = None
        self._last_detect_ms = 0.0

    # -- introspection ------------------------------------------------------
    @property
    def socket_path(self) -> str:
        return self._client.socket_path

    @property
    def stale(self) -> bool:
        """True whenever the last answer did NOT come from a live daemon."""

        return self._stale

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "socket": self._client.socket_path,
                "connected": self._client.connected,
                "stale": self._stale,
                "requests": self._requests,
                "degraded_requests": self._degraded_requests,
                "consecutive_failures": self._consecutive_failures,
                "last_error": self._last_error,
                "last_detect_ms": round(self._last_detect_ms, 3),
                "provider_profile": self.resolution.selected,
                "execution_providers": list(self.resolution.execution_providers),
            }

    def health(self) -> dict[str, Any] | None:
        """The daemon's own health, or ``None`` when it cannot be reached."""

        try:
            report = self._client.health()
        except (DaemonUnavailable, DaemonRequestFailed, ProtocolError) as exc:
            self._record_failure(str(exc))
            return None
        self._record_success()
        return report

    def wait_until_ready(self, timeout_s: float = 30.0, *, poll_s: float = 0.25) -> bool:
        """Block until the daemon answers a health probe, or give up.

        For the launcher's readiness check, not for the reactive path.
        """

        deadline = self._clock() + float(timeout_s)
        while True:
            if self.health() is not None:
                return True
            if self._clock() >= deadline:
                return False
            time.sleep(poll_s)

    def close(self) -> None:
        self._client.close()

    # -- the Detector protocol ---------------------------------------------
    def detect(
        self,
        *,
        rgb: np.ndarray | None,
        depth: np.ndarray | None = None,
        seg: np.ndarray | None = None,
        query: str | Sequence[str] | None = None,
    ) -> list[Any]:
        """Detect through the daemon. NEVER raises for a transport problem.

        ``seg`` is accepted and ignored — an open-vocab detector is box-only,
        exactly as ``OwlV2Detector`` documents.
        """

        del seg
        if rgb is None:
            return []
        try:
            phrases = normalize_query(query)
        except ProtocolError as exc:
            # A malformed query is the CALLER's bug, not a transport failure.
            # It RAISES — hiding it would be exactly the silent blindness
            # Fable's row D-R2 measured, where an over-long batch made every
            # poll fail while only an error counter moved. It must NOT mark the
            # detector stale: the daemon is fine, the request was not.
            self._record_bad_request(str(exc))
            raise
        if not phrases:
            return []
        with self._lock:
            self._requests += 1
            if self._stale and self._clock() < self._next_attempt_at:
                self._degraded_requests += 1
                return []
        started = time.perf_counter()
        try:
            response = self._client.detect(rgb, phrases, depth=depth)
        except (DaemonUnavailable, ProtocolError) as exc:
            self._record_failure(f"{type(exc).__name__}: {exc}")
            return []
        except DaemonRequestFailed as exc:
            # The daemon answered with a refusal. That is a real answer, so the
            # detector is NOT stale — but it produced nothing, and the reason is
            # recorded so a wrong query cannot look like an empty scene.
            self._record_refusal(str(exc))
            return []
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        rows = response.get("detections", [])
        if not isinstance(rows, list):
            self._record_failure("daemon returned a non-list detections field")
            return []
        try:
            detections = [detection_from_wire(row) for row in rows]
        except (ProtocolError, ValueError, TypeError) as exc:
            self._record_failure(f"undecodable detection row: {exc}")
            return []
        self._record_success(
            detect_ms=elapsed_ms,
            provider=response.get("provider_profile"),
            providers=response.get("execution_providers"),
            detector=response.get("detector"),
        )
        return detections

    # -- bookkeeping --------------------------------------------------------
    def _record_success(
        self,
        *,
        detect_ms: float | None = None,
        provider: Any = None,
        providers: Any = None,
        detector: Any = None,
    ) -> None:
        with self._lock:
            self._stale = False
            self._consecutive_failures = 0
            self._next_attempt_at = 0.0
            if detect_ms is not None:
                self._last_detect_ms = float(detect_ms)
            if provider:
                self.resolution.selected = str(provider)
            if providers:
                self.resolution.execution_providers = tuple(str(p) for p in providers)[:8]
            if detector:
                self.name = str(detector) if str(detector).endswith("-daemon") else (
                    f"{detector}-daemon"
                )

    def _record_bad_request(self, detail: str) -> None:
        """A request this client refused to send. Not a daemon failure."""

        with self._lock:
            self._last_error = detail[:256]

    def _record_refusal(self, detail: str) -> None:
        with self._lock:
            self._stale = False
            self._consecutive_failures = 0
            self._last_error = detail[:256]

    def _record_failure(self, detail: str) -> None:
        with self._lock:
            self._stale = True
            self._consecutive_failures += 1
            self._degraded_requests += 1
            self._last_error = detail[:256]
            self._next_attempt_at = self._clock() + self.retry_interval_s
            failures = self._consecutive_failures
        # Loud on the first failure and then on a decade scale: a per-frame log
        # at 10 Hz would bury the very message it is trying to deliver.
        if failures == 1 or failures % 100 == 0:
            logger.warning(
                "perception daemon unavailable (%d consecutive): %s — detections "
                "degrade to empty+stale, the loop keeps running",
                failures,
                detail,
            )


class DaemonEmbedder:
    """SigLIP-2 through the daemon, shaped like ``TextImageEmbedder``.

    Provided for P1-B's ``embed_fn`` seam: the map learner needs crop
    embeddings, and paying for a second in-process copy of SigLIP-2 next to the
    detector is exactly the contention this card moves off the robot.
    Unavailability RAISES here rather than degrading — an embedding that
    silently comes back as zeros would poison a persistent map, which is a
    worse failure than a missing one.
    """

    def __init__(self, socket_path: str | None = None, **client_kwargs: Any) -> None:
        self._client = DaemonClient(socket_path, **client_kwargs)

    @property
    def socket_path(self) -> str:
        return self._client.socket_path

    def embed_image(self, image: np.ndarray) -> tuple[float, ...]:
        return tuple(float(v) for v in self._client.embed_image(image))

    def embed_text(self, text: str) -> tuple[float, ...]:
        return tuple(float(v) for v in self._client.embed_text(text))

    def close(self) -> None:
        self._client.close()


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_S",
    "DEFAULT_REQUEST_TIMEOUT_S",
    "DEFAULT_RETRY_INTERVAL_S",
    "DaemonClient",
    "DaemonDetector",
    "DaemonEmbedder",
    "DaemonRequestFailed",
]
