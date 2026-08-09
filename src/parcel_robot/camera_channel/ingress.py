"""Camera-ingress wiring: put the DETECTOR on the mission path (Card B4).

This is the seam that makes the dog **search with its camera** instead of reading
the ground-truth frustum oracle. It renders RGB(+depth) through the proven
:class:`~parcel_robot.camera_channel.backends.mujoco_egl.MujocoEglCameraBackend`,
runs an open-vocab :class:`~parcel_robot.detection_adapter.pixel_detections.Detector`
(the B3 :class:`OwlV2Detector`) for the *active semantic goal*, localizes each box to
a metric world point via ``localize_frame`` (B2), and turns those
:class:`LocalizedDetection` rows into the SAME ``semantic_candidates`` dict payload
the navigator's grounding already consumes — only now sourced from **pixels**, not
the ``SimObservation`` oracle.

Placement — off the reactive 10 Hz path
---------------------------------------
OWLv2 costs ~559 ms/query on CPU (B3), so it must never run inline on the reactive
control tick. :class:`CameraIngress` runs the render→detect→localize pipeline on a
**background worker** at a bounded cadence and publishes the latest candidate list to
a lock-guarded buffer. The runtime's 10 Hz path only ever calls
:meth:`latest_candidates` (a non-blocking snapshot read) and :meth:`set_pose` /
:meth:`set_query` (cheap setters). The reactive gate + A* consume whatever the
detector last PROPOSED; they never wait on a detection.

Thread-safety / MuJoCo
----------------------
The worker renders from its **own** ``MjData`` (a static, once-forwarded copy of the
scene) so it never races the control loop's live ``MjData``. The free camera is
placed from the robot pose passed to ``capture(...)`` — objects are static, the
camera moves — so a separate data buffer renders the correct scene from the current
mount pose without touching the simulation's physics state.

EGL-before-import constraint
----------------------------
``MUJOCO_GL`` binds the offscreen GL backend at the **first** ``import mujoco`` in a
process and cannot change afterwards. :class:`CameraIngress` imports MuJoCo (via the
backend) only when constructed, so the *entry point* that builds the ingress must set
``MUJOCO_GL=egl`` before it — the runtime never imports MuJoCo itself, keeping the
constraint at the sim/gate boundary where the model/data already live.

HONESTY (P0)
------------
Rendered MuJoCo textures are NOT photoreal, so OWLv2 recall here tests the
pixels→localize→ground→lock-on pipeline + a FLOOR of recognition, not real-world D455
recognition (a hardware re-earn). No field recall/precision is claimed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Default worker cadence floor. OWLv2 detect itself is ~559 ms, so the effective
#: rate is detector-bound; this only caps the *minimum* gap between polls so the
#: worker never busy-spins and stays comfortably off the 10 Hz reactive path.
DEFAULT_MIN_POLL_INTERVAL_S = 0.25

#: Candidate source tag so downstream logging / the arbiter can tell a pixel
#: proposal apart from the GT-frustum oracle.
PIXEL_SOURCE = "pixel_detector"


@dataclass
class IngressStats:
    """Cheap health/telemetry for /api/ or a gate report (never blocks a read)."""

    polls: int = 0
    detections_last: int = 0
    candidates_last: int = 0
    last_latency_ms: float = 0.0
    last_detect_ms: float = 0.0
    errors: int = 0
    last_error: str | None = None
    last_query: tuple[str, ...] = ()
    reactive_reads: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "polls": self.polls,
            "detections_last": self.detections_last,
            "candidates_last": self.candidates_last,
            "last_latency_ms": round(self.last_latency_ms, 2),
            "last_detect_ms": round(self.last_detect_ms, 2),
            "errors": self.errors,
            "last_error": self.last_error,
            "last_query": list(self.last_query),
            "reactive_reads": self.reactive_reads,
        }


@dataclass(frozen=True, slots=True)
class _Pose:
    x: float
    y: float
    yaw: float


@dataclass
class CameraIngress:
    """Async pixel→``semantic_candidates`` producer for the mission path.

    Construct with :meth:`from_model_data` (the normal path — it defers the EGL
    backend to the worker thread and loads the detector), or inject a ``backend`` +
    ``detector`` directly for a deterministic offline test. All setters are cheap and
    thread-safe; the detector only runs inside :meth:`poll_once`, never on a read.

    EGL is thread-affine: a MuJoCo GL context can only be made current on the thread
    that created it. So the backend is created **lazily on the first poll** — when
    the worker runs, the context is born on the worker thread and every render stays
    there. ``backend_factory`` (set by :meth:`from_model_data`) builds it once; an
    injected ``backend`` skips the factory entirely (offline tests, single-threaded).
    """

    backend: Any = None
    detector: Any = None
    intrinsics: Any = None
    mount: Any = None
    depth_min_m: float = 0.4
    depth_max_m: float = 6.0
    embed_fn: Callable[[Any], Sequence[float]] | None = None
    min_poll_interval_s: float = DEFAULT_MIN_POLL_INTERVAL_S
    backend_factory: Callable[[], Any] | None = None
    # runtime state ---------------------------------------------------------
    _query: tuple[str, ...] = field(default=(), init=False)
    _pose: _Pose | None = field(default=None, init=False)
    _latest: list[dict[str, Any]] | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _seq: int = field(default=0, init=False)
    stats: IngressStats = field(default_factory=IngressStats, init=False)

    # -- construction -------------------------------------------------------
    @classmethod
    def from_model_data(
        cls,
        model: Any,
        data: Any,
        *,
        spec: Any | None = None,
        detector: Any | None = None,
        robot_body_name: str | None = None,
        class_ids: tuple[str, ...] = ("background", "object"),
        threshold: float | None = None,
        embed_fn: Callable[[Any], Sequence[float]] | None = None,
        min_poll_interval_s: float = DEFAULT_MIN_POLL_INTERVAL_S,
    ) -> CameraIngress:
        """Build the EGL backend + OWLv2 detector for an in-process MuJoCo scene.

        ``data`` should be a MuJoCo ``MjData`` the ingress may render from freely
        (a static/once-forwarded copy is ideal — the worker calls ``mj_forward``
        on it). The EGL backend is created lazily on the first poll so its GL
        context is born on whichever thread renders (the worker), never on this
        constructing thread. When ``detector`` is None it loads :class:`OwlV2Detector`
        via the opt-in ``PARCEL_OWLV2_ONNX`` env gate — and raises if it is
        unavailable, so a caller that asked for camera ingress hears about a missing
        detector loudly (that check is eager; only the GL backend is deferred).
        """

        from parcel_robot.camera_channel.channel import CameraChannelSpec

        spec = spec if spec is not None else CameraChannelSpec.d455_go2_nominal()

        def _factory() -> Any:
            from parcel_robot.camera_channel.backends.factory import open_camera_backend

            backend, kind = open_camera_backend(
                spec,
                prefer="mujoco_egl",
                model=model,
                data=data,
                class_ids=class_ids,
                robot_body_name=robot_body_name,
            )
            if kind != "mujoco_egl":  # pragma: no cover - factory raises first
                raise RuntimeError(f"camera ingress requires the mujoco_egl backend, got {kind}")
            return backend

        if detector is None:
            from parcel_robot.detection_adapter.owlv2_onnx import load_owlv2_detector

            detector = load_owlv2_detector(threshold=threshold)
            if detector is None:
                raise RuntimeError(
                    "camera ingress requested but the OWLv2 detector is unavailable "
                    "(set PARCEL_OWLV2_ONNX=1 and run scripts/fetch_owlv2.sh)"
                )

        return cls(
            backend=None,
            detector=detector,
            intrinsics=spec.intrinsics,
            mount=spec.mount,
            depth_min_m=float(spec.depth_min_m),
            # Drop the backend's depth-clip sentinel: MuJoCo clips background to
            # exactly ``depth_max_m``, so a ``<= depth_max_m`` inlier filter would
            # count that far wall as a surface and drag a thin object's box-interior
            # median depth outward. Trimming a hair below the clip excludes it.
            depth_max_m=float(spec.depth_max_m) - 1e-2,
            embed_fn=embed_fn,
            min_poll_interval_s=float(min_poll_interval_s),
            backend_factory=_factory,
        )

    def _ensure_backend(self) -> Any:
        """Build the deferred backend on the calling (worker) thread, once."""

        backend = self.backend
        if backend is not None:
            return backend
        factory = self.backend_factory
        if factory is None:
            raise RuntimeError("camera ingress has no backend and no backend_factory")
        backend = factory()
        self.backend = backend
        return backend

    # -- cheap thread-safe setters (called from the 10 Hz path) -------------
    def set_query(self, query: str | Sequence[str] | None) -> None:
        """Set the active open-vocab query (the semantic goal noun/phrase)."""

        if query is None:
            phrases: tuple[str, ...] = ()
        elif isinstance(query, str):
            phrases = tuple(p for p in (query.strip(),) if p)
        else:
            phrases = tuple(str(q).strip() for q in query if str(q).strip())
        with self._lock:
            self._query = phrases
            self.stats.last_query = phrases

    def clear_query(self) -> None:
        self.set_query(None)

    def set_pose(self, x: float, y: float, yaw: float) -> None:
        """Set the mount pose the next render captures from (robot base pose)."""

        with self._lock:
            self._pose = _Pose(float(x), float(y), float(yaw))

    @property
    def has_query(self) -> bool:
        with self._lock:
            return bool(self._query)

    def latest_candidates(self) -> list[dict[str, Any]] | None:
        """Non-blocking snapshot of the most recent pixel candidates.

        Returns ``None`` when the detector has not yet produced a frame (the
        caller then keeps whatever fallback it uses). A copy is returned so the
        reactive path never mutates the published buffer.
        """

        with self._lock:
            self.stats.reactive_reads += 1
            if self._latest is None:
                return None
            return [dict(item) for item in self._latest]

    # -- the detector pipeline (worker thread only) -------------------------
    def poll_once(self) -> list[dict[str, Any]] | None:
        """Render → detect → localize → publish once. Returns the new candidates.

        Never raises: any failure is counted in :attr:`stats` and leaves the last
        good buffer in place (a transient render/detect error must not blank the
        map mid-mission). Returns ``None`` when there is no query/pose yet.
        """

        with self._lock:
            query = self._query
            pose = self._pose
        if not query or pose is None:
            return None
        try:
            candidates = self._detect_and_localize(query, pose)
        except Exception as exc:  # noqa: BLE001 - a detect error must not crash the mission
            with self._lock:
                self.stats.errors += 1
                self.stats.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("camera ingress poll failed: %s", exc)
            return None
        with self._lock:
            self._latest = candidates
            self.stats.polls += 1
            self.stats.candidates_last = len(candidates)
        return candidates

    def _detect_and_localize(
        self, query: tuple[str, ...], pose: _Pose
    ) -> list[dict[str, Any]]:
        import numpy as np

        from parcel_robot.detection_adapter.pixel_detections import (
            CameraExtrinsics,
            localize_frame,
        )

        t0 = time.perf_counter()
        self._seq += 1
        seq = self._seq
        source_ts = time.time_ns()
        recv_ns = time.monotonic_ns()

        backend = self._ensure_backend()
        # Render RGB+depth from the current mount pose (worker's own MjData).
        backend.capture(
            source_timestamp_ns=source_ts % (1 << 62),
            sequence=seq,
            robot_x=pose.x,
            robot_y=pose.y,
            robot_yaw_rad=pose.yaw,
        )
        buffers = backend.last_buffers
        if buffers is None or buffers.color_rgb8 is None or buffers.depth_m_f32 is None:
            raise RuntimeError("camera backend produced no RGB/depth buffers")
        rgb = np.asarray(buffers.color_rgb8)
        depth = np.asarray(buffers.depth_m_f32, dtype=np.float64)

        extrinsics = CameraExtrinsics.from_mount_pose(
            robot_x=pose.x,
            robot_y=pose.y,
            robot_yaw_rad=pose.yaw,
            mount=self.mount,
        )

        t_detect = time.perf_counter()
        localized = localize_frame(
            self.detector,
            rgb=rgb,
            depth=depth,
            seg=None,  # a real open-vocab detector is box-only (seg_id=None)
            query=list(query),
            intrinsics=self.intrinsics,
            extrinsics=extrinsics,
            source_timestamp_ns=source_ts % (1 << 62),
            received_monotonic_ns=recv_ns,
            sequence=seq,
            embed_fn=self.embed_fn,
            depth_min_m=self.depth_min_m,
            depth_max_m=self.depth_max_m,
        )
        detect_ms = (time.perf_counter() - t_detect) * 1000.0

        candidates = [
            self._candidate_from_localized(loc, seq, offset)
            for offset, loc in enumerate(localized)
        ]
        latency_ms = (time.perf_counter() - t0) * 1000.0
        with self._lock:
            self.stats.detections_last = len(localized)
            self.stats.last_latency_ms = latency_ms
            self.stats.last_detect_ms = detect_ms
        return candidates

    @staticmethod
    def _candidate_from_localized(loc: Any, seq: int, offset: int) -> dict[str, Any]:
        """One :class:`LocalizedDetection` → the navigator's candidate dict shape.

        Matches ``navigation.semantic_map._candidate``: an ``object`` candidate with
        a world ``position``, the detector ``score`` as confidence (clamped to the
        [0, 1] the schema requires), and ``source=pixel_detector`` so grounding /
        the arbiter can see it came from pixels, not the oracle.
        """

        confidence = float(loc.score)
        confidence = 0.0 if confidence < 0.0 else min(confidence, 1.0)
        return {
            "id": f"pxdet-{seq}-{offset}",
            "label": str(loc.label),
            "position": [float(loc.world_x), float(loc.world_y), float(loc.world_z)],
            "confidence": confidence,
            "kind": "object",
            "source": PIXEL_SOURCE,
            "reachable": True,
            "metadata": {
                "detector": getattr(loc, "instance_key", None) or PIXEL_SOURCE,
                "range_m": round(float(loc.message.range_m), 4),
                "bearing_rad": round(float(loc.message.bearing_rad), 4),
                "sigma_range_m": round(float(loc.sigma_range_m), 4),
                "inlier_pixels": int(loc.inlier_pixels),
                "depth_m": round(float(loc.depth_m), 4),
            },
        }

    # -- background worker --------------------------------------------------
    def start(self) -> None:
        """Start the background detect worker (idempotent)."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="camera-ingress", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.perf_counter()
            if self.has_query and self._pose is not None:
                self.poll_once()
            # Sleep at least the floor between polls so the worker never busy-spins
            # while idle (no query) and stays off the reactive path when active.
            elapsed = time.perf_counter() - started
            wait = max(0.0, self.min_poll_interval_s - elapsed)
            if self._stop.wait(timeout=max(wait, 0.02)):
                break

    def stop(self) -> None:
        """Stop the worker and release the renderer (idempotent, best-effort)."""

        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        close = getattr(self.backend, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001, S110 - teardown best-effort
                pass


__all__ = ["DEFAULT_MIN_POLL_INTERVAL_S", "PIXEL_SOURCE", "CameraIngress", "IngressStats"]
