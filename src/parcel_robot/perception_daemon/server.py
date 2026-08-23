"""The out-of-process perception daemon: one GPU, one socket (card P1-A).

Owns the OWLv2 detector (``cuda_fp16`` after P0-C) and the SigLIP-2 encoders,
and answers :mod:`parcel_robot.perception_daemon.protocol` messages on an
AF_UNIX socket. The robot's runtime holds no model at all — it holds a
:class:`~parcel_robot.perception_daemon.client.DaemonDetector`, which is a
drop-in for the existing ``detection_adapter.Detector`` protocol.

Design commitments, and the reason for each
-------------------------------------------
* **The models are loaded LAZILY and exactly once**, behind
  :attr:`PerceptionDaemon._model_lock`. A 202 MB ORT session and a CUDA context
  are not free; two threads racing to build them is how a daemon ends up with
  two copies of a model on one GPU.
* **Inference is serialized.** One GPU, one detector session: concurrent
  ``Run`` calls would contend for the same device anyway, and serializing here
  makes the latency the client measures the latency the client will get.
  Connections are still concurrent — a health probe never queues behind a
  detect.
* **A handler never kills the daemon.** Every request is answered: a protocol
  violation becomes a typed error response, an unexpected exception becomes an
  ``internal`` error response with the type name, and the accept loop keeps
  running. A daemon that dies on one bad frame is worse than no daemon, because
  the runtime would then have to be restarted to get its eyes back.
* **The socket is user-private (mode 0600)** and refuses to replace a path that
  is not already a socket — the same rule
  :class:`parcel_robot.sim_ipc.PoseSocketServer` applies, for the same reason.

HONESTY
-------
The daemon does not make the detector faster or more accurate. It moves the
detector's variance off the robot's 10 Hz loop and makes a model crash
survivable. Measured detector latency remains what P0-C measured (98 ms p50
idle; 132–139 ms under this wave's load) plus the round-trip overhead this
module's own health counters report.
"""

from __future__ import annotations

import logging
import os
import socket
import stat
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from parcel_robot.perception_daemon.protocol import (
    MAX_DETECTIONS,
    OP_DETECT,
    OP_EMBED_IMAGE,
    OP_EMBED_TEXT,
    OP_HEALTH,
    OP_SHUTDOWN,
    PROTOCOL_VERSION,
    DaemonUnavailable,
    ProtocolError,
    decode,
    default_socket_path,
    detection_to_wire,
    encode,
    error_header,
    normalize_query,
    ok_header,
)

# ---- CARD HW-1 py310-clean (scrum/20260822/task_35) ----
# ``typing.Self`` is 3.11+ and the dog's Orin NX runs JetPack's CPython 3.10
# (WAVE3_HW_DESIGN_FABLE.md §5.1, seam S22). This module opens with ``from
# __future__ import annotations``, so its one use of the name — the return
# annotation of ``PerceptionDaemon.__enter__`` — is a *string* at runtime and
# no ``typing.Self`` object is ever built. The ``TYPE_CHECKING`` form (already
# used by ``commissioning/session.py:77`` before this card) therefore leaves
# ``__annotations__`` byte-for-byte what it was.
if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime
    from typing import Self
# ---- END CARD HW-1 py310-clean ----

logger = logging.getLogger(__name__)

#: Concurrent connections. The runtime uses one; the extras are for a health
#: probe, the launcher's readiness check and an operator's `--probe` call.
DEFAULT_MAX_CLIENTS = 8

#: Per-connection socket timeout. Long enough for a cold model load on the
#: first detect, short enough that a wedged peer frees its slot.
DEFAULT_CLIENT_TIMEOUT_S = 120.0

#: Latency samples retained for the p50/p95 the health probe reports.
LATENCY_WINDOW = 256


def _percentile(samples: list[float], fraction: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


class PerceptionDaemon:
    """Serve detect/embed/health over an AF_UNIX socket.

    ``detector_factory`` and ``embedder_factory`` default to the real GPU
    loaders and are injectable so the contract can be tested with a stub in
    milliseconds instead of loading 200 MB of ONNX.
    """

    def __init__(
        self,
        socket_path: str | os.PathLike[str] | None = None,
        *,
        detector_factory: Callable[[], Any] | None = None,
        embedder_factory: Callable[[], Any] | None = None,
        max_clients: int = DEFAULT_MAX_CLIENTS,
        client_timeout_s: float = DEFAULT_CLIENT_TIMEOUT_S,
        preload: bool = False,
    ) -> None:
        self.socket_path = Path(socket_path or default_socket_path())
        self._detector_factory = detector_factory or _load_gpu_detector
        self._embedder_factory = embedder_factory or _load_gpu_embedder
        self._max_clients = max(1, int(max_clients))
        self._client_timeout_s = float(client_timeout_s)
        self._server: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._model_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._clients = threading.BoundedSemaphore(self._max_clients)
        # Live client connections. ``stop()`` shuts these down explicitly:
        # closing only the LISTENING socket leaves established peers being
        # served forever, so an operator who ran `--stop` would still have a
        # GPU answering detects. Stopped has to mean stopped.
        self._connections: set[socket.socket] = set()
        self._connections_lock = threading.Lock()
        self._detector: Any = None
        self._embedder: Any = None
        self._detector_error: str | None = None
        self._embedder_error: str | None = None
        self._started_monotonic_ns = 0
        self._requests = 0
        self._errors = 0
        self._detections_served = 0
        self._last_error: str | None = None
        self._detect_ms: list[float] = []
        self._preload = bool(preload)

    # -- lifecycle ----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._server is not None and not self._stop.is_set()

    def start(self) -> None:
        """Bind, listen, and serve on a background accept thread."""

        if self._server is not None:
            raise RuntimeError("daemon is already started")
        self._unlink_existing_socket()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.socket_path))
        except OSError as exc:
            server.close()
            raise RuntimeError(f"cannot bind {self.socket_path}: {exc}") from exc
        # Owner-only: the socket is a live GPU and a camera stream. 0600 before
        # the first listen, so there is no window where it is world-writable.
        os.chmod(self.socket_path, 0o600)
        server.listen(self._max_clients)
        server.settimeout(0.2)
        self._server = server
        self._stop.clear()
        self._started_monotonic_ns = time.monotonic_ns()
        if self._preload:
            # Preloading is an OPTIMISATION — it buys the first frame a warm
            # session — and the two models are independent capabilities. A host
            # with OWLv2 weights but no SigLIP-2 must still serve detections, so
            # a preload failure is recorded in `health()` (`detector_error` /
            # `embedder_error`) and logged, not raised. The LAZY path still
            # raises to the client that actually asked for the missing model, so
            # the failure reaches whoever needs it instead of taking the eye
            # down for everybody.
            for label, load in (("detector", self._ensure_detector),
                                ("embedder", self._ensure_embedder)):
                try:
                    load()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "perception daemon: %s did not preload (%s: %s); serving without "
                        "it — requests for it will be refused by name",
                        label,
                        type(exc).__name__,
                        exc,
                    )
            # NARROWER THAN IT LOOKS, measured 2026-08-22: `_ensure_embedder`
            # builds the SigLIP-2 TEXT session only. `_OnnxSigLIP2Embedder`
            # resolves vision independently and builds it lazily inside
            # `_ensure_vision` on the first `embed_image`, which therefore still
            # pays a cold session (418 ms on this host; 188 ms in Fable's run)
            # against a 3.3 ms warm p50. `health()["embedder_loaded"]` is true
            # about the embedder OBJECT, not about the vision session behind it.
        thread = threading.Thread(
            target=self._accept_loop, name="perception-daemon", daemon=True
        )
        self._accept_thread = thread
        thread.start()

    def stop(self, *, timeout_s: float = 5.0) -> None:
        """Stop accepting, drop live peers, join the loop, remove the socket.

        Established connections are shut down deliberately. Closing only the
        listening socket would leave every already-connected client being served
        indefinitely — a "stopped" daemon still running inference on the GPU,
        which is the opposite of what `--stop` promises. A peer sees the
        connection close, which is precisely the condition
        :class:`~.client.DaemonDetector` degrades on.
        """

        self._stop.set()
        thread, self._accept_thread = self._accept_thread, None
        server, self._server = self._server, None
        if server is not None:
            try:
                server.close()
            except OSError:  # pragma: no cover - defensive
                pass
        with self._connections_lock:
            live = list(self._connections)
            self._connections.clear()
        for conn in live:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:  # the peer may already be gone
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_s)
        self._unlink_existing_socket(missing_ok=True)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _unlink_existing_socket(self, *, missing_ok: bool = False) -> None:
        try:
            mode = os.lstat(self.socket_path).st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(mode):
            raise FileExistsError(f"refusing to replace non-socket path: {self.socket_path}")
        try:
            self.socket_path.unlink()
        except FileNotFoundError:  # pragma: no cover - race with another unlink
            if not missing_ok:
                raise

    # -- serving ------------------------------------------------------------
    def _accept_loop(self) -> None:
        server = self._server
        while not self._stop.is_set() and server is not None:
            try:
                conn, _ = server.accept()
            except (TimeoutError, socket.timeout):  # noqa: UP041
                continue
            except OSError:
                break
            if not self._clients.acquire(blocking=False):
                # Over the connection ceiling: say so and close, rather than
                # queueing a client that will time out with no explanation.
                try:
                    conn.sendall(
                        encode(error_header("connect", 0, "daemon is at its client ceiling"))
                    )
                finally:
                    conn.close()
                continue
            worker = threading.Thread(
                target=self._serve_client,
                args=(conn,),
                name="perception-daemon-client",
                daemon=True,
            )
            worker.start()

    def _serve_client(self, conn: socket.socket) -> None:
        with self._connections_lock:
            self._connections.add(conn)
        try:
            conn.settimeout(self._client_timeout_s)
            while not self._stop.is_set():
                try:
                    header, arrays = decode(conn)
                except DaemonUnavailable:
                    return  # the peer went away; that is normal, not an error
                except ProtocolError as exc:
                    self._count_error(str(exc))
                    self._send(conn, error_header("unknown", 0, str(exc), kind="protocol"))
                    return
                response, payload = self._dispatch(header, arrays)
                if not self._send(conn, response, payload):
                    return
                if header.get("op") == OP_SHUTDOWN and response.get("status") == "ok":
                    threading.Thread(target=self.stop, daemon=True).start()
                    return
        finally:
            with self._connections_lock:
                self._connections.discard(conn)
            try:
                conn.close()
            except OSError:  # pragma: no cover - defensive
                pass
            self._clients.release()

    def _send(
        self,
        conn: socket.socket,
        header: Mapping[str, Any],
        arrays: Mapping[str, np.ndarray] | None = None,
    ) -> bool:
        try:
            conn.sendall(encode(header, arrays))
        except OSError:
            return False
        return True

    def _dispatch(
        self, header: Mapping[str, Any], arrays: Mapping[str, np.ndarray]
    ) -> tuple[dict[str, Any], dict[str, np.ndarray] | None]:
        op = str(header.get("op", ""))
        request_id = int(header.get("id", 0) or 0)
        with self._stats_lock:
            self._requests += 1
        try:
            if op == OP_HEALTH:
                return ok_header(op, request_id, **self.health()), None
            if op == OP_SHUTDOWN:
                return ok_header(op, request_id, stopping=True), None
            if op == OP_DETECT:
                return self._handle_detect(request_id, header, arrays), None
            if op == OP_EMBED_IMAGE:
                return self._handle_embed_image(request_id, arrays)
            if op == OP_EMBED_TEXT:
                return self._handle_embed_text(request_id, header)
            raise ProtocolError(f"unknown operation {op!r}")
        except ProtocolError as exc:
            self._count_error(str(exc))
            return error_header(op, request_id, str(exc), kind="protocol"), None
        except Exception as exc:  # noqa: BLE001 - one bad request must not end the daemon
            detail = f"{type(exc).__name__}: {exc}"
            self._count_error(detail)
            logger.warning("perception daemon %s failed: %s", op, detail)
            return error_header(op, request_id, detail, kind="internal"), None

    # -- operations ---------------------------------------------------------
    def _handle_detect(
        self, request_id: int, header: Mapping[str, Any], arrays: Mapping[str, np.ndarray]
    ) -> dict[str, Any]:
        query = normalize_query(header.get("query"))
        if not query:
            raise ProtocolError("detect requires a non-empty query batch")
        rgb = arrays.get("rgb")
        if rgb is None:
            raise ProtocolError("detect requires an 'rgb' array part")
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ProtocolError("detect 'rgb' must be HxWx3")
        depth = arrays.get("depth")
        detector = self._ensure_detector()
        started = time.perf_counter()
        with self._infer_lock:
            detections = detector.detect(rgb=rgb, depth=depth, seg=None, query=list(query))
        detect_ms = (time.perf_counter() - started) * 1000.0
        rows = [detection_to_wire(det) for det in detections[:MAX_DETECTIONS]]
        truncated = max(0, len(detections) - len(rows))
        with self._stats_lock:
            self._detections_served += len(rows)
            self._detect_ms.append(detect_ms)
            if len(self._detect_ms) > LATENCY_WINDOW:
                del self._detect_ms[:-LATENCY_WINDOW]
        return ok_header(
            OP_DETECT,
            request_id,
            detections=rows,
            truncated=truncated,
            detect_ms=round(detect_ms, 3),
            detector=str(getattr(detector, "name", "detector")),
            provider_profile=self._provider_profile(detector),
            execution_providers=self._execution_providers(detector),
            query=list(query),
        )

    def _handle_embed_image(
        self, request_id: int, arrays: Mapping[str, np.ndarray]
    ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        image = arrays.get("rgb")
        if image is None:
            raise ProtocolError("embed_image requires an 'rgb' array part")
        embedder = self._ensure_embedder()
        with self._infer_lock:
            vector = embedder.embed_image(image)
        arr = np.asarray(vector, dtype=np.float32)
        return (
            ok_header(OP_EMBED_IMAGE, request_id, dims=int(arr.size)),
            {"embedding": arr},
        )

    def _handle_embed_text(
        self, request_id: int, header: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        text = header.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ProtocolError("embed_text requires a non-empty 'text'")
        if len(text) > 512:
            raise ProtocolError("embed_text 'text' exceeds 512 characters")
        embedder = self._ensure_embedder()
        with self._infer_lock:
            vector = embedder.embed_text(text)
        arr = np.asarray(vector, dtype=np.float32)
        return (
            ok_header(OP_EMBED_TEXT, request_id, dims=int(arr.size)),
            {"embedding": arr},
        )

    # -- models -------------------------------------------------------------
    def _ensure_detector(self) -> Any:
        with self._model_lock:
            if self._detector is not None:
                return self._detector
            try:
                detector = self._detector_factory()
            except Exception as exc:
                self._detector_error = f"{type(exc).__name__}: {exc}"
                raise
            if detector is None:
                self._detector_error = "detector factory returned None"
                raise RuntimeError(
                    "the perception daemon has no detector: OWLv2 weights, "
                    "onnxruntime or tokenizers are missing (scripts/fetch_owlv2.sh)"
                )
            self._detector = detector
            self._detector_error = None
            return detector

    def _ensure_embedder(self) -> Any:
        with self._model_lock:
            if self._embedder is not None:
                return self._embedder
            try:
                embedder = self._embedder_factory()
            except Exception as exc:
                self._embedder_error = f"{type(exc).__name__}: {exc}"
                raise
            if embedder is None:
                self._embedder_error = "embedder factory returned None"
                raise RuntimeError(
                    "the perception daemon has no SigLIP-2 embedder "
                    "(scripts/fetch_siglip2.sh)"
                )
            self._embedder = embedder
            self._embedder_error = None
            return embedder

    @staticmethod
    def _provider_profile(model: Any) -> str:
        return str(getattr(getattr(model, "resolution", None), "selected", None) or "unknown")

    @staticmethod
    def _execution_providers(model: Any) -> list[str]:
        providers = (
            getattr(getattr(model, "resolution", None), "execution_providers", ()) or ()
        )
        return [str(p) for p in providers][:8]

    def _count_error(self, detail: str) -> None:
        with self._stats_lock:
            self._errors += 1
            self._last_error = detail[:256]

    # -- health -------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        """Everything an operator needs to know without opening a second tool."""

        with self._stats_lock:
            requests = self._requests
            errors = self._errors
            served = self._detections_served
            last_error = self._last_error
            samples = list(self._detect_ms)
        uptime_ns = (
            0 if not self._started_monotonic_ns else time.monotonic_ns() - self._started_monotonic_ns
        )
        detector = self._detector
        embedder = self._embedder
        return {
            "protocol_version": PROTOCOL_VERSION,
            "socket": str(self.socket_path),
            "pid": os.getpid(),
            "uptime_s": round(uptime_ns / 1e9, 3),
            "requests": requests,
            "errors": errors,
            "last_error": last_error,
            "detections_served": served,
            "detector_loaded": detector is not None,
            "detector": None if detector is None else str(getattr(detector, "name", "detector")),
            "detector_error": self._detector_error,
            "provider_profile": self._provider_profile(detector),
            "execution_providers": self._execution_providers(detector),
            "embedder_loaded": embedder is not None,
            "embedder_error": self._embedder_error,
            "detect_ms_p50": round(_percentile(samples, 0.5), 3),
            "detect_ms_p95": round(_percentile(samples, 0.95), 3),
            "detect_samples": len(samples),
        }


def _load_gpu_detector() -> Any:  # pragma: no cover - needs weights + GPU
    """OWLv2 on the resolved provider (``cuda_fp16`` after P0-C).

    ``require_env=False`` matches the runtime's own composition root: an
    operator who started the daemon has already said yes to the heavy model,
    explicitly, on a command line.
    """

    from parcel_robot.detection_adapter.owlv2_onnx import load_owlv2_detector

    return load_owlv2_detector(require_env=False)


def _load_gpu_embedder() -> Any:  # pragma: no cover - needs weights + GPU
    """SigLIP-2 text+vision encoders on the resolved provider.

    ``load_onnx_embedder`` has no ``require_env`` parameter (the detector's
    loader does), and it returns ``None`` when ``PARCEL_SIGLIP2_ONNX`` is unset.
    That switch exists so that merely having weights on disk never flips a
    mission onto a heavy model by accident — a decision an operator who typed
    ``launch_detector_daemon.sh`` has already made, explicitly, on a command
    line. This process therefore opts itself in, and ONLY this process: the
    daemon is a dedicated process, so the env write cannot leak into the
    runtime, the panel or a test. An operator who wants the switch off can still
    export ``PARCEL_SIGLIP2_ONNX=0``, which is respected because an already-set
    value is not overwritten.

    ``instructnav.siglip.DEFAULT_WEIGHTS`` is the one weights location the tree
    already agrees on (``route_memory.place_graph`` and ``instructnav.siglip``
    both resolve through it); the daemon reuses it rather than inventing a
    second spelling of the same directory.
    """

    from parcel_robot.instructnav.siglip import DEFAULT_WEIGHTS
    from parcel_robot.instructnav.siglip2_onnx import ONNX_ENABLE_ENV, load_onnx_embedder

    os.environ.setdefault(ONNX_ENABLE_ENV, "1")
    return load_onnx_embedder(DEFAULT_WEIGHTS)


__all__ = [
    "DEFAULT_CLIENT_TIMEOUT_S",
    "DEFAULT_MAX_CLIENTS",
    "LATENCY_WINDOW",
    "PerceptionDaemon",
]
