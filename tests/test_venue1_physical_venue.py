"""Card VENUE-1 — the runtime opens the PHYSICAL eye.

P1-A built three physical ``CameraBackend``s, a GPU detector daemon behind an
AF_UNIX socket and a ``--camera`` launcher switch, and then declared a HALT:
``RobotRuntime._attach_configured_camera_ingress`` built the MuJoCo/EGL ingress
UNCONDITIONALLY, so every piece of the physical path existed and nothing
selected it. A plugged-in camera fed nothing.

This file pins the composition root that changes that, and each property below
is a way the wiring could look present while being useless or — worse —
dishonest:

* **The venue is selectable, and a physical venue never touches MuJoCo.** The
  attach returns before the ``MUJOCO_GL`` preamble and before ``import
  mujoco``; a webcam has no GL binding to get wrong. Pinned with a
  ``sys.meta_path`` finder that makes any import of ``mujoco`` an error.
* **The frame says where it came from, and the declaration comes from the
  backend that made the pixels.** ``CameraIngress.origin`` defaults to
  ``"unknown"`` and the ingress never reads ``PhysicalCaptureBuffers.origin``,
  so an ingress built without ``origin=`` publishes honest buffers and
  dishonest records — the defect Fable caught in P1-A's own handoff snippet.
* **The map's world is the frame's world.** The runtime used to stamp the map's
  writer ``simulation`` whenever the camera stream was enabled, and the
  in-process mixing refusal compared the writer's origin against an observation
  carrying that same writer — a vacuous comparison. Here the writer is derived
  from the pixels and a real mismatch is refused before one frame flows.
* **The daemon's failures are typed states, not silence and not a crash.**
  Absence, restart, the backoff window, an undecodable row and a slow detect
  are each measured through the attached ingress, with the control-loop read
  timed in every one of them.
* **RGB-only is said out loud.** ``CameraIngress`` needs metric depth to place
  a box, so a webcam publishes NOTHING. That is the correct failure — assumed
  depth would produce world coordinates that look like measurements and are not
  — but it belongs on the operator's surface, not in an empty stream that reads
  like an empty room.

**No robot hardware is on hand** (owner, 2026-08-22): every cell here runs on
P1-A's committed clip, on doubles that subclass P1-A's
``PhysicalCameraBackendBase``, or on a real ``PerceptionDaemon`` over a real
AF_UNIX socket with an injected stub detector. The live ``uvc`` / ``realsense``
arms are owner-gated and listed in ``scrum/20260822/task_16/VENUE1_STATUS.md``.
"""

from __future__ import annotations

import importlib.abc
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.camera_channel.backends.physical import (
    PhysicalCameraBackendBase,
    spec_from_config,
)
from parcel_robot.detection_adapter.pixel_detections import PixelDetection
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
CLIP = REPO / "tests" / "data" / "p1a_desk_clip.npz"

def _attached_realsense() -> list[str]:
    """Serials on the bus, through P1-A's probe. Empty on this host."""

    from parcel_robot.camera_channel.backends.realsense import connected_devices

    return connected_devices()


#: Sockets live on a SHORT path of this card's own, never under ``tmp_path``:
#: AF_UNIX addresses are capped at 108 bytes and a long ``TMPDIR`` silently
#: blows that (the failure mode P1-A's daemon tests hit).
SOCKET_ROOT = Path.home() / ".cache" / "parcel-venue1" / "sock"


# ---------------------------------------------------------------------------
# runtime fixtures (the same shape tests/test_c1_camera_stream.py uses)
# ---------------------------------------------------------------------------


def _audio() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


class _Backend:
    name = "fake"

    def __init__(self, observation: SimObservation) -> None:
        self._observation = observation

    def observe(self) -> SimObservation:
        return self._observation

    def move(self, command: object) -> None:
        pass

    def stop(self) -> None:
        pass

    def pose(self, pose: object) -> None:
        pass

    def trajectory(self, skill: object) -> None:
        pass

    def move_owner(self, dx: float, dy: float) -> None:
        pass


def _observation() -> SimObservation:
    return SimObservation(
        timestamp=time.monotonic(),
        robot=RobotPose(x=1.0, y=-2.0, yaw=0.0),
        owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0),
        backend="fake",
    )


ON_BLOCK = """  spatial_sensors: [camera, lidar]
  camera_ingress: true
  camera_ingress_rate_hz: 10.0
  camera_ingress_queue_capacity: 256
  camera_ingress_max_detections_per_frame: 4
  camera_ingress_queries: [person, chair]
"""


def _config(
    tmp_path: Path,
    *,
    perception: str = ON_BLOCK,
    navigation_config: Path | None = None,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "robot.yaml"
    nav = "  enabled: false\n"
    if navigation_config is not None:
        nav += f"  config: {navigation_config}\n"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
{nav}motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
perception:
{perception}""",
        encoding="utf-8",
    )
    return path


def _learned_map_nav_config(tmp_path: Path) -> Path:
    """A navigation config whose semantic source READS the learned map.

    Off-oracle is the only mode in which P1-B's map exists at all, so it is the
    only mode in which the venue/map origin questions have a subject.
    """

    path = tmp_path / "navigation.yaml"
    path.write_text(
        "perception:\n"
        "  semantic_source: learned_map\n"
        "  online_map:\n"
        "    persist_on_close: true\n"
        "    reload_on_start: true\n"
        "    visit_id_prefix: venue1\n",
        encoding="utf-8",
    )
    return path


def _runtime(config: Path) -> RobotRuntime:
    return RobotRuntime(config, _Backend(_observation()), audio_status=_audio())


# ---------------------------------------------------------------------------
# camera doubles — P1-A's contract, no hardware
# ---------------------------------------------------------------------------


class _DepthDouble(PhysicalCameraBackendBase):
    """A D455-shaped venue: RGB + colour-aligned depth, declared PHYSICAL."""

    origin = EvidenceOrigin.PHYSICAL
    kind = "realsense"

    def __init__(self, *, width: int = 64, height: int = 48) -> None:
        super().__init__(
            spec=spec_from_config({}, width_px=width, height_px=height, has_depth=True),
            origin_label="double:d455-contract",
        )
        self._width = width
        self._height = height
        self.reads = 0

    @property
    def has_depth(self) -> bool:
        return True

    def _read_frame(self) -> tuple[np.ndarray, np.ndarray]:
        self.reads += 1
        rgb = np.full((self._height, self._width, 3), 90, dtype=np.uint8)
        rgb[12:42, 20:40] = 200
        depth = np.full((self._height, self._width), 2.0, dtype=np.float32)
        return rgb, depth


class _RgbOnlyDouble(PhysicalCameraBackendBase):
    """A webcam-shaped venue: pixels, no metric depth, declared PHYSICAL."""

    origin = EvidenceOrigin.PHYSICAL
    kind = "uvc"

    def __init__(self, *, width: int = 64, height: int = 48) -> None:
        super().__init__(
            spec=spec_from_config({}, width_px=width, height_px=height, has_depth=False),
            origin_label="double:uvc-uncalibrated",
        )
        self._width = width
        self._height = height

    @property
    def has_depth(self) -> bool:
        return False

    def _read_frame(self) -> tuple[np.ndarray, None]:
        rgb = np.full((self._height, self._width, 3), 90, dtype=np.uint8)
        rgb[12:42, 20:40] = 200
        return rgb, None


def _use_double(monkeypatch: pytest.MonkeyPatch, backend: PhysicalCameraBackendBase) -> None:
    """Make ``open_physical_backend`` hand back a double for its kind.

    The runtime resolves the opener from the module at call time, so this
    replaces exactly the one seam a real camera would sit behind and leaves the
    rest of the composition root — including ``camera_ingress_kwargs`` and the
    origin declaration it derives — running for real.
    """

    from parcel_robot.camera_channel.backends import physical as physical_module

    def _open(kind: str | None = None, **_: Any) -> tuple[Any, str]:
        return backend, backend.kind

    monkeypatch.setattr(physical_module, "open_physical_backend", _open)


# ---------------------------------------------------------------------------
# detector doubles + a REAL daemon over a REAL socket
# ---------------------------------------------------------------------------


class _StubDetector:
    """One box per call, in the shape the daemon serializes."""

    name = "stub"

    def __init__(self, *, delay_s: float = 0.0) -> None:
        self.delay_s = float(delay_s)
        self.calls = 0

    def detect(
        self,
        *,
        rgb: Any,
        depth: Any = None,
        seg: Any = None,
        query: Any = None,
    ) -> list[PixelDetection]:
        del depth, seg
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        if rgb is None:
            return []
        phrases = list(query or ["chair"])
        label = "chair" if "chair" in phrases else phrases[0]
        return [PixelDetection(label=label, score=0.8, box=(20, 12, 40, 42))]


@pytest.fixture()
def socket_path() -> Iterator[Path]:
    SOCKET_ROOT.mkdir(parents=True, exist_ok=True)
    path = SOCKET_ROOT / f"v{os.getpid()}-{threading.get_ident() % 9973}.sock"
    if path.exists():
        path.unlink()
    yield path
    if path.exists():
        path.unlink()


def _daemon(path: Path, detector: Any) -> Any:
    from parcel_robot.perception_daemon.server import PerceptionDaemon

    daemon = PerceptionDaemon(path, detector_factory=lambda: detector)
    daemon.start()
    return daemon


# ---------------------------------------------------------------------------
# driving the attached ingress
# ---------------------------------------------------------------------------


def _drive(runtime: RobotRuntime, polls: int) -> int:
    """Poll the ATTACHED ingress N times through the runtime's own pose mailbox.

    The worker thread is stopped first so the count is exact; every frame still
    travels the product seam — ``CameraIngress.poll_once`` → ``on_frame`` →
    ``RobotRuntime._publish_camera_frame`` — because that is the callback the
    composition root wired. What this does NOT exercise is the worker's own
    cadence; ``test_the_worker_thread_publishes_on_its_own_cadence`` does that.
    """

    ingress = runtime._camera_ingress
    assert ingress is not None
    ingress.stop()
    done = 0
    for _ in range(polls):
        runtime._offer_camera_pose(_observation())
        if not ingress._refresh_pose_from_source():
            continue
        ingress.poll_once()
        done += 1
    return done


class _NoMujoco(importlib.abc.MetaPathFinder):
    """Any import of ``mujoco`` while this is installed is a test failure."""

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        # Returning nothing hands the import on to the next finder; only the
        # one name this card cares about is fatal.
        if fullname == "mujoco" or fullname.startswith("mujoco."):
            raise AssertionError(
                f"the physical venue imported {fullname!r}: a camera that renders "
                "nothing must not bind an offscreen GL backend"
            )


#: Modules that must be FORGOTTEN before the MuJoCo fixture can answer
#: anything. ``parcel_robot.sim``'s first statements are ``import mujoco`` /
#: ``import mujoco.viewer``; if an earlier cell in the session already imported
#: it, a later ``from parcel_robot.sim import resolve_scene`` is a dict lookup
#: that re-imports nothing — and a fixture that only dropped ``mujoco`` would
#: pass vacuously in a full-file run while failing in isolation. Measured: this
#: cell was exactly that, in both directions, before the prefix was widened.
_MUJOCO_ROOTS = ("mujoco", "parcel_robot.sim")


def _forget_mujoco() -> dict[str, Any]:
    saved = {
        name: module
        for name, module in list(sys.modules.items())
        if name in _MUJOCO_ROOTS or name.startswith(tuple(f"{r}." for r in _MUJOCO_ROOTS))
    }
    for name in saved:
        del sys.modules[name]
    return saved


@pytest.fixture()
def mujoco_is_fatal() -> Iterator[None]:
    saved = _forget_mujoco()
    finder = _NoMujoco()
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        sys.modules.update(saved)


# Card GREEN-1 retired the companion ``mujoco_unloaded`` fixture. Its one user,
# ``test_the_map_installer_still_imports_mujoco_and_that_is_a_handoff``, now runs
# in a clean subprocess: forgetting modules in THIS process could answer "was it
# imported?" but never "was a GL backend bound?" — ``MUJOCO_GL`` is an
# environment variable a neighbouring cell can set process-wide, and no
# ``sys.modules`` surgery un-initializes a MuJoCo that has already run.


@pytest.fixture()
def recorded_venue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``PARCEL_CAMERA_BACKEND=recorded`` pointed at P1-A's committed clip."""

    camera_config = tmp_path / "camera.json"
    camera_config.write_text(json.dumps({"clip": str(CLIP)}), encoding="utf-8")
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "recorded")
    monkeypatch.setenv("PARCEL_CAMERA_CONFIG", str(camera_config))
    return camera_config


@pytest.fixture(autouse=True)
def _clean_venue_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No venue, no socket and no encoder leak between cells or from the host."""

    for name in (
        "PARCEL_CAMERA_BACKEND",
        "PARCEL_CAMERA_CONFIG",
        "PARCEL_PERCEPTION_SOCKET",
        "PARCEL_ONLINE_MAP_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    # The encoder is a separate decision from the venue and loading 200 MB of
    # SigLIP-2 in a unit test would measure the host, not the wiring.
    from parcel_robot.camera_channel import ingress as ingress_module

    monkeypatch.setattr(ingress_module, "load_siglip2_embed_fn", lambda *a, **k: None)
    yield


# ===========================================================================
# R1 — the venue is selectable and reaches the attach site
# ===========================================================================


def test_the_recorded_venue_reaches_the_attach_site_and_replaces_the_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    from parcel_robot.camera_channel.backends.recorded import RecordedCameraBackend

    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        ingress = runtime._camera_ingress
        assert ingress is not None
        assert isinstance(ingress.backend, RecordedCameraBackend)
        # C-1's MuJoCo path sets `_camera_scene_path` to a scene file. There is
        # no scene behind a clip and the surface must not name one.
        assert runtime._camera_scene_path == "venue:recorded"
        assert runtime.venue_snapshot() is not None
    finally:
        runtime.close()


def test_a_venue_name_nobody_implements_refuses_by_name(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK + "  camera_backend: relasense\n"))
    try:
        with pytest.raises(ValueError, match="unknown camera backend 'relasense'"):
            runtime._attach_configured_camera_ingress()
        assert runtime._camera_ingress is None
    finally:
        runtime.close()


def test_the_launcher_flag_outranks_the_profile_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    """``--camera`` is a decision about THIS run and beats the profile's default."""

    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK + "  camera_backend: realsense\n"))
    try:
        assert runtime._venue1_resolve_venue() == "recorded"
        monkeypatch.delenv("PARCEL_CAMERA_BACKEND")
        assert runtime._venue1_resolve_venue() == "realsense"
    finally:
        runtime.close()


def test_the_profile_key_is_loadable_by_the_overlay(tmp_path: Path) -> None:
    """A key the runtime reads that the overlay refuses is a dead switch.

    Both spellings this card added must survive ``check_overlay_keys`` against
    the SHA-locked base, which is the mechanism that made P0-A's camera keys and
    ROAM-1's ``roam:`` block real.
    """

    import yaml

    from parcel_robot.config import check_overlay_keys

    base = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    check_overlay_keys(
        base, {"perception": {"camera_backend": "realsense", "detector": "daemon"}}
    )


# ===========================================================================
# R2 — a physical venue never imports or initializes MuJoCo/EGL
# ===========================================================================


def test_a_physical_venue_never_imports_mujoco(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recorded_venue: Path,
    mujoco_is_fatal: None,
) -> None:
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    monkeypatch.delenv("MUJOCO_GL", raising=False)
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        published = _drive(runtime, 3)
        assert published == 3
        assert runtime.camera_detection_frame_slice(8)
        # Neither imported nor bound: MUJOCO_GL is written by the preamble this
        # path returns before, and a webcam has no GL backend to choose.
        assert "mujoco" not in sys.modules
        assert "MUJOCO_GL" not in os.environ
    finally:
        runtime.close()


def test_a_physical_double_never_imports_mujoco(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mujoco_is_fatal: None
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        assert _drive(runtime, 3) == 3
        assert "mujoco" not in sys.modules
    finally:
        runtime.close()


# ===========================================================================
# R3 — the published frame's origin comes from the backend that made the pixels
# ===========================================================================


def test_a_physical_venue_publishes_frames_that_say_physical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        assert _drive(runtime, 5) == 5
        frames = runtime.camera_detection_frame_slice(16)
        assert frames
        origins = {frame.origin for frame in frames}
        assert origins == {EvidenceOrigin.PHYSICAL.value}, (
            f"physical pixels published as {sorted(origins)!r} — the buffers are "
            "honest and every derived record is not"
        )
    finally:
        runtime.close()


def test_a_recorded_clip_publishes_replay_and_can_never_mint_physical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        _drive(runtime, 4)
        frames = runtime.camera_detection_frame_slice(16)
        assert frames
        assert {frame.origin for frame in frames} == {EvidenceOrigin.REPLAY.value}
    finally:
        runtime.close()


def test_a_hundred_physical_frames_publish_without_a_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        assert _drive(runtime, 100) == 100
        assert runtime._camera_frames_published == 100
        assert runtime._camera_frames_dropped == 0
        assert runtime._camera_stream_errors == 0
        frames = runtime.camera_detection_frame_slice(128)
        assert len(frames) == 100
        assert all(frame.origin == EvidenceOrigin.PHYSICAL.value for frame in frames)
    finally:
        runtime.close()


def test_the_worker_thread_publishes_on_its_own_cadence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The attach STARTS a worker; nothing here is hand-driven."""

    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        ingress = runtime._camera_ingress
        assert ingress is not None and ingress._thread is not None
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and runtime._camera_frames_published < 3:
            runtime._offer_camera_pose(_observation())
            time.sleep(0.02)
        assert runtime._camera_frames_published >= 3
        frames = runtime.camera_detection_frame_slice(8)
        assert {frame.origin for frame in frames} == {EvidenceOrigin.PHYSICAL.value}
    finally:
        runtime.close()


# ===========================================================================
# R4 — capture -> publish through the runtime, with the daemon on a real socket
# ===========================================================================


def test_capture_to_publish_p50_through_the_runtime_with_the_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path, socket_path: Path
) -> None:
    """100 frames, real AF_UNIX socket, real client, real framing.

    The daemon's detector is a stub, so this measures the pipeline and the
    process boundary — not OWLv2. P1-A measured the GPU round trip at 100.6 /
    113.7 ms p50 on this host and the process boundary itself at 0.6 / 1.8 ms;
    that cost is additive to what is measured here.
    """

    detector = _StubDetector()
    daemon = _daemon(socket_path, detector)
    monkeypatch.setenv("PARCEL_PERCEPTION_SOCKET", str(socket_path))
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        assert runtime._camera_ingress is not None
        assert type(runtime._camera_ingress.detector).__name__ == "DaemonDetector"
        assert _drive(runtime, 100) == 100
        frames = runtime.camera_detection_frame_slice(128)
        assert len(frames) == 100
        latencies = sorted(frame.publish_latency_ns / 1e6 for frame in frames)
        p50 = statistics.median(latencies)
        p95 = latencies[int(0.95 * (len(latencies) - 1))]
        print(f"\nVENUE-1 R4 capture->publish p50={p50:.2f} ms p95={p95:.2f} ms")
        assert p50 < 300.0
        assert p50 + 113.7 < 300.0
        assert detector.calls >= 100
    finally:
        runtime.close()
        daemon.stop()


def test_capture_to_publish_p50_at_the_d455_raster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, socket_path: Path
) -> None:
    """The same row at 640x480 — the raster a D455 actually streams.

    P1-A's committed clip is 128x96, so the row above understates the copy and
    the socket write a real camera pays. This one carries 921,600 bytes of RGB
    plus 1,228,800 of depth per frame, over the same real socket.
    """

    detector = _StubDetector()
    daemon = _daemon(socket_path, detector)
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setenv("PARCEL_PERCEPTION_SOCKET", str(socket_path))
    _use_double(monkeypatch, _DepthDouble(width=640, height=480))
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        assert _drive(runtime, 100) == 100
        frames = runtime.camera_detection_frame_slice(128)
        latencies = sorted(frame.publish_latency_ns / 1e6 for frame in frames)
        p50 = statistics.median(latencies)
        p95 = latencies[int(0.95 * (len(latencies) - 1))]
        print(f"\nVENUE-1 R4b 640x480 capture->publish p50={p50:.2f} ms p95={p95:.2f} ms")
        assert p50 < 300.0
        assert p50 + 113.7 < 300.0
        assert runtime._camera_frames_dropped == 0
        assert {frame.origin for frame in frames} == {EvidenceOrigin.PHYSICAL.value}
    finally:
        runtime.close()
        daemon.stop()


def test_capture_to_publish_with_a_hundred_millisecond_detect_in_the_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, socket_path: Path
) -> None:
    """Is the "pipeline + GPU" model additive? Measured, not assumed.

    R4 and R4b measure the pipeline with a detector that returns instantly, and
    the status doc composes them with P1-A's measured GPU round trip. A
    composition is a MODEL, and this cell is the arithmetic check on it: the
    daemon's stub sleeps 100 ms inside `detect`, so the end-to-end number here
    should be the pipeline number plus ~100 ms if the model holds, and more if
    something in the path serializes worse than the model says.

    The measured overshoot goes in the status doc rather than being rounded
    away — it is why the composed figure is quoted as a floor.
    """

    daemon = _daemon(socket_path, _StubDetector(delay_s=0.100))
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setenv("PARCEL_PERCEPTION_SOCKET", str(socket_path))
    _use_double(monkeypatch, _DepthDouble(width=640, height=480))
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        assert _drive(runtime, 20) == 20
        frames = runtime.camera_detection_frame_slice(32)
        latencies = sorted(frame.publish_latency_ns / 1e6 for frame in frames)
        p50 = statistics.median(latencies)
        print(
            f"\nVENUE-1 R4c 640x480 + 100 ms detect: capture->publish "
            f"p50={p50:.2f} ms (model floor 100 + pipeline)"
        )
        assert p50 < 300.0
        assert p50 >= 100.0, "the detect did not actually run in the path"
    finally:
        runtime.close()
        daemon.stop()


# ===========================================================================
# R5/R6 — the map's world is the frame's world, and a mismatch is refused
# ===========================================================================


def _map_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    store: Path,
    name: str = "run",
) -> RobotRuntime:
    monkeypatch.setenv("PARCEL_ONLINE_MAP_PATH", str(store))
    nav = _learned_map_nav_config(tmp_path)
    config = _config(tmp_path / name, navigation_config=nav)
    return _runtime(config)


def test_the_map_writer_origin_comes_from_the_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not from ``_camera_stream_enabled``, which is what it used to be.

    The runtime installs the map immediately BEFORE the attach (the query batch
    is built from the reloaded map), so the ingress did not exist when the
    writer was stamped and the guess — ``simulation`` whenever the stream is on
    — always won. On a physical venue that is simply false.
    """

    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _map_runtime(tmp_path, monkeypatch, store=tmp_path / "physical.sqlite3")
    try:
        runtime._p1b_install_learned_map()
        assert runtime._p1b_learned_map is not None
        assert runtime._p1b_learned_map.provenance.origin == EvidenceOrigin.SIMULATION.value
        runtime._attach_configured_camera_ingress()
        assert (
            runtime._p1b_learned_map.provenance.origin == EvidenceOrigin.PHYSICAL.value
        )
        note = runtime.venue_snapshot()["map"]
        assert note["rederived_from_frame"] is True
        assert note["frame_origin"] == EvidenceOrigin.PHYSICAL.value
        # And the same re-derivation fixes the WORLD'S NAME. `_p1b_scene_id`
        # prefers `_camera_scene_path` and otherwise resolves the simulator's
        # scene, so before this card a desk's places persisted stamped
        # `city_block` — the name of a street the robot has never been on.
        assert runtime._p1b_learned_map.provenance.scene_id == "venue:realsense"
    finally:
        runtime.close()


def test_the_map_installer_still_imports_mujoco_and_that_is_a_handoff(tmp_path: Path) -> None:
    """TODAY'S BEHAVIOUR, asserted so it cannot rot. This is a declared miss.

    The attach site is clean — ``test_a_physical_venue_never_imports_mujoco``
    proves it. But ``start()`` installs P1-B's map one line BEFORE the attach,
    and ``_p1b_scene_id()`` does ``from parcel_robot.sim import resolve_scene``,
    a module whose FIRST LINE is ``import mujoco``. So a physical venue running
    off-oracle still drags MuJoCo into the process — imported, never
    initialized: no ``MjModel``, no ``MjData``, no EGL context, no
    ``MUJOCO_GL``.

    ``_p1b_scene_id`` is inside card P1-B's region and outside this card's
    OWNS, so this is a HALT and a handoff, not a fix. The one-line remedy is
    in ``VENUE1_STATUS.md``: resolve the venue's name before reaching for the
    simulator's. When it lands, THIS test goes red and both are revisited
    together — which is the point of writing it down.

    Card GREEN-1: run in a CLEAN SUBPROCESS, because every one of the four
    facts above is a property of a PROCESS, not of a call. In-process this cell
    used ``mujoco_unloaded`` to forget ``mujoco`` and ``parcel_robot.sim`` from
    ``sys.modules``, which handled the import half — but ``MUJOCO_GL`` is an
    environment variable, and ``src/parcel_robot/runtime.py`` sets it
    process-wide when the SIMULATED camera ingress attaches. Any earlier cell in
    the sweep that takes that path (measured: ``tests/test_runtime_activation.py``
    and ``tests/test_scene_assets.py``, either alone) leaves ``MUJOCO_GL=egl``
    behind, and ``assert "MUJOCO_GL" not in os.environ`` went red on a fact
    about a NEIGHBOUR. Forgetting a module also cannot un-initialize MuJoCo: in
    a process where an earlier cell already built an ``MjModel`` and bound EGL,
    "imported, never initialized" is unmeasurable however clean ``sys.modules``
    looks.

    ``test_a_physical_venue_never_imports_mujoco`` above defends its own copy of
    the ``MUJOCO_GL`` assertion with ``monkeypatch.delenv``, and that is the
    right tool THERE: it asserts a path returns BEFORE the preamble, so the
    process it runs in is not part of the claim. It is not enough here. This
    cell's subject is a FIRST import — the tripwire only fires if
    ``parcel_robot.sim`` is genuinely loaded from source by the installer — and
    no ``delenv`` or ``sys.modules`` surgery gives a warm process back its
    pristine MuJoCo.

    A fresh interpreter with ``MUJOCO_GL`` scrubbed from its environment answers
    all four honestly and makes the tripwire real — ``parcel_robot.sim`` is
    imported for the first time, from source, by the installer itself. The
    instrument is the house pattern (``test_a_full_preflight_run_never_imports_a_vendor_sdk``
    in ``tests/test_capture_preflight.py``). The child reuses THIS module's own
    ``_config`` / ``_runtime`` helpers, so the runtime under measurement is
    built exactly the way every other cell in this file builds one.
    """

    script = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        f"sys.path.insert(0, {str(REPO / 'tests')!r})\n"
        "from pathlib import Path\n"
        "import test_venue1_physical_venue as venue1\n"
        f"tmp = Path({str(tmp_path)!r})\n"
        "nav = venue1._learned_map_nav_config(tmp)\n"
        "runtime = venue1._runtime(venue1._config(tmp / 'probe', navigation_config=nav))\n"
        "try:\n"
        "    print('BEFORE', 'mujoco' in sys.modules)\n"
        "    runtime._p1b_install_learned_map()\n"
        "    print('AFTER', 'mujoco' in sys.modules)\n"
        "    print('GL', os.environ.get('MUJOCO_GL', '<unset>'))\n"
        "    learned = runtime._p1b_learned_map\n"
        "    print('MAP', learned is not None)\n"
        "    print('SCENE', None if learned is None else learned.provenance.scene_id)\n"
        "finally:\n"
        "    runtime.close()\n"
    )
    env = dict(os.environ)
    # The two leaks this cell has to be immune to, scrubbed rather than trusted:
    # a neighbour's `MUJOCO_GL`, and any venue the host exported.
    env.pop("MUJOCO_GL", None)
    for name in ("PARCEL_CAMERA_BACKEND", "PARCEL_CAMERA_CONFIG", "PARCEL_PERCEPTION_SOCKET"):
        env.pop(name, None)
    env["PARCEL_ONLINE_MAP_PATH"] = ":memory:"

    proc = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    # Nothing on the way in imported it — importing this module for its helpers
    # must not be what puts MuJoCo in the process, or the next line is vacuous.
    assert "BEFORE False" in proc.stdout, proc.stdout
    assert "AFTER True" in proc.stdout, f"the handoff was taken; delete this cell\n{proc.stdout}"
    # Imported is not initialized. Nothing here builds a model, forwards a
    # step or binds a GL backend, which is why this is a handoff and not a
    # blocker for the venue.
    assert "GL <unset>" in proc.stdout, proc.stdout
    # And the name it went looking for is the SIMULATOR'S scene, on what
    # would be a desk. The re-derivation at the attach site replaces it
    # with `venue:<kind>`; nothing replaces it for a run that never
    # attaches a physical venue at all.
    assert "MAP True" in proc.stdout, proc.stdout
    assert "SCENE city_block" in proc.stdout, proc.stdout


def test_a_recorded_venue_stamps_its_map_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _map_runtime(tmp_path, monkeypatch, store=tmp_path / "replay.sqlite3")
    try:
        runtime._p1b_install_learned_map()
        runtime._attach_configured_camera_ingress()
        assert runtime._p1b_learned_map is not None
        assert runtime._p1b_learned_map.provenance.origin == EvidenceOrigin.REPLAY.value
    finally:
        runtime.close()


def _seed_store(path: Path, origin: str, *, entries: int = 2) -> None:
    """A store of places from ONE world, written through the public API."""

    from parcel_robot.online_map.entries import MapObservation, WriterProvenance
    from parcel_robot.online_map.online_map import OnlineSemanticMap
    from parcel_robot.online_map.store import OnlineMapStore

    os.environ["PARCEL_ONLINE_MAP_PATH"] = str(path)
    store = OnlineMapStore()
    learned = OnlineSemanticMap(
        store,
        provenance=WriterProvenance(
            session_id="seed",
            seat="test",
            detector_name="stub",
            scene_id="seed-scene",
            origin=origin,
        ),
        reload=False,
    )
    for index in range(entries):
        learned.observe(
            MapObservation(
                label="chair",
                score=0.9,
                surface_x=2.0 + index,
                surface_y=0.5,
                surface_z=0.4,
                range_m=2.0,
                bearing_rad=0.0,
                depth_m=2.0,
                extent_w_m=0.6,
                extent_h_m=0.9,
                inlier_pixels=400,
                frame_id=f"seed-{index}",
                visit_id="seed-visit",
                observed_wall_s=time.time(),
                robot_x=0.0,
                robot_y=0.0,
                provenance=learned.provenance,
            )
        )
    learned.persist()
    learned.close()


def test_a_physical_venue_refuses_a_simulation_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline refusal, on the exact runtime path, before one frame flows."""

    store = tmp_path / "sim_places.sqlite3"
    _seed_store(store, EvidenceOrigin.SIMULATION.value)
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _map_runtime(tmp_path, monkeypatch, store=store)
    try:
        runtime._p1b_install_learned_map()
        with pytest.raises(RuntimeError) as excinfo:
            runtime._attach_configured_camera_ingress()
        message = str(excinfo.value)
        assert EvidenceOrigin.PHYSICAL.value in message
        assert EvidenceOrigin.SIMULATION.value in message
        assert str(store) in message
        # And the refusal LEAVES NOTHING that teardown could persist into the
        # store it just protected.
        assert runtime._camera_ingress is None
        assert runtime._p1b_learned_map is None
    finally:
        runtime.close()


def test_a_replay_venue_refuses_a_store_of_physical_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    """The inverse direction: a clip must not be fused into a room's map."""

    store = tmp_path / "real_places.sqlite3"
    _seed_store(store, EvidenceOrigin.PHYSICAL.value)
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _map_runtime(tmp_path, monkeypatch, store=store)
    try:
        runtime._p1b_install_learned_map()
        with pytest.raises(RuntimeError, match="one world"):
            runtime._attach_configured_camera_ingress()
    finally:
        runtime.close()


def test_a_physical_venue_refuses_a_simulation_store_that_holds_no_rows_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the row census cannot see, and the likeliest one in practice.

    A store that declared a world and has not written a place yet is exactly
    what a second run against the wrong file looks like on day one.
    """

    store = tmp_path / "empty_sim.sqlite3"
    _seed_store(store, EvidenceOrigin.SIMULATION.value, entries=0)
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _map_runtime(tmp_path, monkeypatch, store=store)
    try:
        runtime._p1b_install_learned_map()
        assert len(runtime._p1b_learned_map) == 0
        with pytest.raises(RuntimeError) as excinfo:
            runtime._attach_configured_camera_ingress()
        assert "0 place(s) reloaded" in str(excinfo.value)
        assert EvidenceOrigin.SIMULATION.value in str(excinfo.value)
    finally:
        runtime.close()


def test_a_replay_venue_over_simulation_rows_is_admitted_and_rewrites_the_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    """A declared consequence, pinned so the declaration is falsifiable.

    `origins_conflict` fires only when PHYSICAL meets a synthetic origin, so
    `simulation` rows under a `replay` venue do NOT conflict and the run is
    admitted — deliberately: both are synthetic, and refusing here would make
    a clip recorded from the simulator unusable against the map it came from.

    The consequence is that `persist()` rewrites the store's `origin` META to
    `replay` while the pre-existing ROWS still say `simulation`, leaving a file
    whose meta describes only its newest writer. The row census is the
    authority — `load_all` and this card's reconcile both read the ROWS — but
    an operator reading `origin` out of `map_meta` would be misled, so it is
    stated in VENUE1_STATUS.md §4 and measured here.
    """

    store = tmp_path / "sim_rows_replay_run.sqlite3"
    _seed_store(store, EvidenceOrigin.SIMULATION.value)
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _map_runtime(tmp_path, monkeypatch, store=store)
    try:
        runtime._p1b_install_learned_map()
        runtime._attach_configured_camera_ingress()
        assert runtime._p1b_learned_map.provenance.origin == EvidenceOrigin.REPLAY.value
        runtime._p1b_persist_learned_map()
    finally:
        runtime.close()

    from parcel_robot.online_map.store import OnlineMapStore

    reopened = OnlineMapStore(store)
    try:
        assert reopened.get_meta("origin") == EvidenceOrigin.REPLAY.value
        origins = {
            entry.provenance.origin for entry in reopened.load_all()
        }
        assert EvidenceOrigin.SIMULATION.value in origins, (
            "the meta now says replay while the rows still say simulation"
        )
    finally:
        reopened.close()


def test_a_replay_venue_may_open_an_unknown_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    """``unknown`` is silent, not synthetic: a pre-P1-B store still loads.

    Refusing every store written before the origin field existed would make
    this guard the first thing a future executor deletes.
    """

    store = tmp_path / "legacy.sqlite3"
    _seed_store(store, EvidenceOrigin.UNKNOWN.value)
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _map_runtime(tmp_path, monkeypatch, store=store)
    try:
        runtime._p1b_install_learned_map()
        runtime._attach_configured_camera_ingress()
        assert runtime._camera_ingress is not None
        assert runtime._p1b_learned_map is not None
        assert runtime._p1b_learned_map.provenance.origin == EvidenceOrigin.REPLAY.value
    finally:
        runtime.close()


def test_a_replay_venue_may_reopen_its_own_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    store = tmp_path / "same_world.sqlite3"
    _seed_store(store, EvidenceOrigin.REPLAY.value)
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _map_runtime(tmp_path, monkeypatch, store=store)
    try:
        runtime._p1b_install_learned_map()
        runtime._attach_configured_camera_ingress()
        note = runtime.venue_snapshot()["map"]
        assert note["reloaded_entries"] == 2
        assert note["writer_origin"] == EvidenceOrigin.REPLAY.value
    finally:
        runtime.close()


def test_the_whole_runtime_starts_on_a_recorded_venue_and_learns_a_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    """`RobotRuntime.start()` — not the attach method — end to end, twice.

    Everything else in this file drives ``_attach_configured_camera_ingress``
    directly, which is the method ``start()`` calls but not the ordering it
    imposes. This cell takes the whole thing: the map is installed one line
    before the eye, the venue re-derives the writer, the worker thread runs on
    its own clock, frames reach the map through ``_publish_camera_frame``, and
    ``close()`` persists. Then a SECOND runtime reloads what the first one saw
    — which is the only way to tell a map from a log.
    """

    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    store = tmp_path / "desk.sqlite3"
    first = _map_runtime(tmp_path, monkeypatch, store=store, name="run1")
    try:
        first.start()
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and first._camera_frames_published < 4:
            time.sleep(0.05)
        assert first._camera_frames_published >= 4
        assert first._camera_frames_dropped == 0
        frames = first.camera_detection_frame_slice(16)
        assert {frame.origin for frame in frames} == {EvidenceOrigin.REPLAY.value}
        assert first._p1b_learned_map.provenance.origin == EvidenceOrigin.REPLAY.value
        assert first._p1b_learned_map.provenance.scene_id == "venue:recorded"
        learned = first.learned_map_snapshot()
        assert learned["frames_ingested"] >= 4
        assert learned["errors"] == 0
        assert learned["entries"] >= 1
    finally:
        first.close()

    assert store.is_file()
    second = _map_runtime(tmp_path, monkeypatch, store=store, name="run2")
    try:
        second._p1b_install_learned_map()
        second._attach_configured_camera_ingress()
        # Same world, so the store opens; and what it reloaded is what run 1
        # actually saw through a replayed desk clip.
        assert second._p1b_map_reloaded >= 1
        assert second._p1b_learned_map.provenance.origin == EvidenceOrigin.REPLAY.value
    finally:
        second.close()


# ===========================================================================
# R7 — the daemon's degraded states are typed, and none of them blocks motion
# ===========================================================================


def _control_loop_read_ms(runtime: RobotRuntime, samples: int = 40) -> list[float]:
    """Time the 10 Hz loop's semantic read, which is the deadline that matters."""

    observation = _observation()
    timings: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        runtime._semantic_candidates(observation)
        timings.append((time.perf_counter() - started) * 1000.0)
    timings.sort()
    return timings


def _p95(values: list[float]) -> float:
    return values[int(0.95 * (len(values) - 1))]


def test_an_absent_daemon_is_a_typed_degraded_state_not_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path, socket_path: Path
) -> None:
    monkeypatch.setenv("PARCEL_PERCEPTION_SOCKET", str(socket_path))
    runtime = _runtime(_config(tmp_path))
    try:
        # No daemon was ever started. The attach SUCCEEDS: a camera with an
        # unreachable detector is a degraded eye, not a dead runtime.
        runtime._attach_configured_camera_ingress()
        detector = runtime._camera_ingress.detector
        assert detector.stale is True
        assert _drive(runtime, 3) == 3
        frames = runtime.camera_detection_frame_slice(8)
        assert frames and all(frame.detections == () for frame in frames)
        # Empty, and still honest about where the empty came from.
        assert {frame.origin for frame in frames} == {EvidenceOrigin.REPLAY.value}
        snapshot = detector.snapshot()
        assert snapshot["stale"] is True
        assert snapshot["consecutive_failures"] >= 1
        assert snapshot["last_error"]
        assert _p95(_control_loop_read_ms(runtime)) <= 5.0
        assert runtime.venue_snapshot()["detector"]["reachable_at_attach"] is False
    finally:
        runtime.close()


def test_a_daemon_restart_is_survived_and_the_detector_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path, socket_path: Path
) -> None:
    detector_impl = _StubDetector()
    daemon = _daemon(socket_path, detector_impl)
    monkeypatch.setenv("PARCEL_PERCEPTION_SOCKET", str(socket_path))
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        detector = runtime._camera_ingress.detector
        _drive(runtime, 2)
        assert detector.stale is False
        daemon.stop()
        detector.retry_interval_s = 0.0
        _drive(runtime, 2)
        assert detector.stale is True
        daemon = _daemon(socket_path, detector_impl)
        _drive(runtime, 2)
        assert detector.stale is False
        assert _p95(_control_loop_read_ms(runtime)) <= 5.0
    finally:
        runtime.close()
        daemon.stop()


def test_the_backoff_window_is_a_counted_state_not_a_silent_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path, socket_path: Path
) -> None:
    """A stale detector must not hammer a dead socket every poll — and the
    polls it skips must be COUNTED, or "the daemon is away" renders exactly
    like "the room is empty"."""

    monkeypatch.setenv("PARCEL_PERCEPTION_SOCKET", str(socket_path))
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        detector = runtime._camera_ingress.detector
        detector.retry_interval_s = 60.0
        _drive(runtime, 6)
        snapshot = detector.snapshot()
        assert snapshot["stale"] is True
        assert snapshot["degraded_requests"] >= 5
        # The backoff is real: only the first attempt reached the socket.
        assert snapshot["consecutive_failures"] == 1
    finally:
        runtime.close()


def test_an_undecodable_daemon_row_is_a_typed_failure_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path, socket_path: Path
) -> None:
    class _BadSchema:
        name = "bad-schema"

        def detect(self, **_: Any) -> list[Any]:
            class _Row:
                label = "chair"
                score = 0.5
                box = ("x", 1, 2, 3)
                seg_id = None
                instance_key = None

            return [_Row()]

    daemon = _daemon(socket_path, _BadSchema())
    monkeypatch.setenv("PARCEL_PERCEPTION_SOCKET", str(socket_path))
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        detector = runtime._camera_ingress.detector
        assert _drive(runtime, 2) == 2
        snapshot = detector.snapshot()
        assert snapshot["last_error"]
        assert runtime._camera_stream_errors == 0
        assert _p95(_control_loop_read_ms(runtime)) <= 5.0
    finally:
        runtime.close()
        daemon.stop()


def test_a_slow_detect_never_lands_on_the_control_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path, socket_path: Path
) -> None:
    """Backpressure: a 250 ms detect is in flight on the camera worker while the
    control loop takes its semantic read. The read is a lock-free look at the
    last published candidates; it must not queue behind inference."""

    daemon = _daemon(socket_path, _StubDetector(delay_s=0.25))
    monkeypatch.setenv("PARCEL_PERCEPTION_SOCKET", str(socket_path))
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        ingress = runtime._camera_ingress
        ingress.stop()
        runtime._offer_camera_pose(_observation())
        ingress._refresh_pose_from_source()
        worker = threading.Thread(target=ingress.poll_once, daemon=True)
        worker.start()
        time.sleep(0.05)
        timings = _control_loop_read_ms(runtime, samples=60)
        worker.join(timeout=10.0)
        assert not worker.is_alive()
        assert _p95(timings) <= 5.0
        health = ingress.detector.health()
        assert health is not None
    finally:
        runtime.close()
        daemon.stop()


# ===========================================================================
# correction pass — the live wire, the raise window, the row census, detach,
# and the two handoffs the verifier routed here
# ===========================================================================


def test_the_operator_wire_carries_the_daemons_LIVE_state_not_the_attach_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path, socket_path: Path
) -> None:
    """`/api/state` must move when the daemon does.

    Fable, correction item 1: `venue_snapshot()` — the only method that merges
    the detector's live `snapshot()` — had ZERO product callers. Seam 2 called
    `_venue1_composition()`, which is frozen at attach time, so an operator
    watching the panel would have kept reading `reachable_at_attach: true`
    while the socket was long dead. The whole reason the detector is out of
    process is that its failures are survivable AND VISIBLE.
    """

    daemon = _daemon(socket_path, _StubDetector())
    monkeypatch.setenv("PARCEL_PERCEPTION_SOCKET", str(socket_path))
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        _drive(runtime, 2)
        live = runtime.camera_stream_snapshot()["composition"]["detector"]
        assert live["reachable_at_attach"] is True
        assert live["stale"] is False, "the live snapshot never reached the wire"
        assert live["requests"] >= 2

        daemon.stop()
        runtime._camera_ingress.detector.retry_interval_s = 0.0
        _drive(runtime, 2)
        after = runtime.camera_stream_snapshot()["composition"]["detector"]
        # The attach-time fact is unchanged and still reported; the LIVE fact
        # moved. Both, because they answer different questions.
        assert after["reachable_at_attach"] is True
        assert after["stale"] is True
        assert after["consecutive_failures"] >= 1
        assert after["last_error"]
    finally:
        runtime.close()
        daemon.stop()


def test_a_failed_re_install_never_leaves_a_closed_map_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    """Fable, correction item 2: the reconcile's untested raise window.

    The re-derivation closes the guessed map and builds a new one. If the
    second install raises — a store that has become unwritable between the two,
    a config read that fails — the runtime would carry a map whose store is
    SHUT while `_p1b_store_closed` still read False, and teardown would try to
    persist through it and report a store it had not written.
    """

    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _map_runtime(tmp_path, monkeypatch, store=tmp_path / "boom.sqlite3")
    try:
        runtime._p1b_install_learned_map()
        assert runtime._p1b_learned_map is not None
        assert runtime._p1b_store_closed is False

        def _explode() -> None:
            raise RuntimeError("the store went away between the two installs")

        monkeypatch.setattr(runtime, "_p1b_install_learned_map", _explode)
        with pytest.raises(RuntimeError, match="went away"):
            runtime._attach_configured_camera_ingress()

        assert runtime._p1b_learned_map is None, "a closed map is still installed"
        assert runtime._p1b_store_closed is True, "the flag lies about the store"
        assert runtime._camera_ingress is None
        # And teardown is quiet: persist finds nothing to write rather than
        # reaching through a closed connection.
        assert runtime._p1b_persist_learned_map() == 0
    finally:
        runtime.close()


def _save_rows_directly(path: Path, origin: str, *, entries: int = 2) -> None:
    """Rows of one world through `store.save()`, WITHOUT touching `origin` meta.

    `persist()` rewrites the meta, so a store seeded through it can never
    exercise the row census — which is exactly how that half of the guard came
    to be pinned by nothing (Fable, correction item 5). A v1 store migrated
    forward is the real shape of this: rows that know their world, meta that
    does not.
    """

    from parcel_robot.online_map.entries import MapEntry, WriterProvenance
    from parcel_robot.online_map.store import OnlineMapStore

    store = OnlineMapStore(path)
    try:
        for index in range(entries):
            store.save(
                MapEntry(
                    entry_id=f"e{index}",
                    label="chair",
                    surface_x=2.0 + index,
                    surface_y=0.5,
                    surface_z=0.4,
                    provenance=WriterProvenance(
                        session_id="raw",
                        seat="test",
                        detector_name="stub",
                        scene_id="raw-scene",
                        origin=origin,
                    ),
                    first_seen_wall_s=1.0,
                    last_seen_wall_s=2.0,
                )
            )
        assert store.get_meta("origin") is None
    finally:
        store.close()


def test_the_row_census_refuses_a_store_whose_META_says_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the mixing guard, with the meta half taken away.

    A store whose rows are `simulation` and whose `origin` meta is absent is a
    v1 file, or one written by a run that never persisted its meta. The meta
    check cannot see it. The ROWS can.
    """

    store = tmp_path / "rows_only.sqlite3"
    _save_rows_directly(store, EvidenceOrigin.SIMULATION.value)
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _map_runtime(tmp_path, monkeypatch, store=store)
    try:
        runtime._p1b_install_learned_map()
        assert len(runtime._p1b_learned_map) == 2
        with pytest.raises(RuntimeError) as excinfo:
            runtime._attach_configured_camera_ingress()
        message = str(excinfo.value)
        assert EvidenceOrigin.SIMULATION.value in message
        assert "2 place(s) reloaded" in message
        assert runtime._p1b_learned_map is None
    finally:
        runtime.close()


def test_a_compatible_foreign_origin_is_reported_and_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    """`unknown` rows under a `replay` venue: admitted, and SAID.

    `foreign_but_compatible` is the note that makes the difference between "no
    foreign origins" and "foreign origins that do not conflict" legible. It was
    written and read by nothing until this cell (Fable, correction item 5).
    """

    store = tmp_path / "legacy_rows.sqlite3"
    _save_rows_directly(store, EvidenceOrigin.UNKNOWN.value)
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _map_runtime(tmp_path, monkeypatch, store=store)
    try:
        runtime._p1b_install_learned_map()
        runtime._attach_configured_camera_ingress()
        note = runtime.venue_snapshot()["map"]
        assert note["store_origin"] is None
        assert note["foreign_but_compatible"] == [EvidenceOrigin.UNKNOWN.value]
        assert note["reloaded_entries"] == 2
    finally:
        runtime.close()


def test_the_surface_stops_claiming_a_camera_once_the_eye_is_detached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fable, correction item 6. `_venue1_state` outlives the ingress."""

    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        composition = runtime.camera_stream_snapshot()["composition"]
        assert composition["attached"] is True
        assert composition["real_camera"] is True

        runtime.detach_camera_ingress()
        after = runtime.camera_stream_snapshot()["composition"]
        # The VENUE is still the venue this run selected — that is a fact about
        # the run. What is no longer true is that a camera is behind it.
        assert after["venue"] == "realsense"
        assert after["attached"] is False
        assert after["real_camera"] is False
    finally:
        runtime.close()


def test_the_semantic_source_binding_now_follows_the_config_in_both_directions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CAP-1's finding, taken here on the verifier's routing.

    `_p1b_install_learned_map` binds the process-global source only when the
    policy READS the learned map; under `oracle` it returns first, so a process
    that already bound `learned_map` handed the next runtime a source its own
    YAML does not describe. The composition root is where the file becomes the
    process, so the binding is asserted there — for the camera-off runtime too,
    which is why seam 1a sits above C-1's early return.
    """

    from parcel_robot.perception_source.selection import (
        SemanticSourcePolicy,
        active_semantic_source,
        use_semantic_source,
    )

    use_semantic_source(SemanticSourcePolicy(source="learned_map"))
    assert active_semantic_source().source == "learned_map"
    try:
        off = "  spatial_sensors: [camera, lidar]\n  camera_ingress: false\n"
        runtime = _runtime(_config(tmp_path, perception=off))
        try:
            # A runtime whose navigation config names the shipping oracle, and
            # whose camera is OFF — the case the early return would have
            # skipped.
            runtime._attach_configured_camera_ingress()
            assert active_semantic_source().source == "oracle"
        finally:
            runtime.close()
    finally:
        use_semantic_source(SemanticSourcePolicy())


def test_a_physical_venue_hands_the_owner_tracker_its_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OT-2 §9.1, taken here on the verifier's routing.

    OT-2's `_ot2_latest_rgb` duck-types `latest_rgb()` on the attached ingress
    and degrades to `no_pixels` without it — so on a live camera, the one venue
    where identity from real pixels is the point, the owner tracker kept
    position tracks and asserted nothing. `CameraIngress` is P1-B's file, but a
    PHYSICAL backend already holds the buffers it just produced, so the
    composition root can supply the accessor.

    The pairing is a timing property, not a type, and it is asserted as such:
    the pixels handed over are the ones behind the frame that was just
    published.
    """

    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    double = _DepthDouble()
    _use_double(monkeypatch, double)
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        assert runtime._ot2_latest_rgb() is None, "no capture has happened yet"
        assert _drive(runtime, 2) == 2
        rgb = runtime._ot2_latest_rgb()
        assert rgb is not None, "the venue did not hand the tracker its pixels"
        assert rgb.shape == (48, 64, 3)
        assert np.array_equal(rgb, double.last_buffers.color_rgb8)
    finally:
        runtime.close()


# ===========================================================================
# R8 — flag-off is byte-identical
# ===========================================================================


def test_no_venue_means_the_simulator_and_this_card_is_absent(
    tmp_path: Path,
) -> None:
    """No env, no key ⇒ `_venue1_resolve_venue()` is None and the snapshot's
    `composition` block is C-1's literal, unchanged."""

    runtime = _runtime(_config(tmp_path))
    try:
        assert runtime._venue1_resolve_venue() is None
        assert runtime._venue1_composition() is None
        assert runtime.venue_snapshot() is None
        snapshot = runtime.camera_stream_snapshot()
        assert snapshot is not None
        assert snapshot["composition"] == {
            "mode": "static_scene_copy_pose_synced",
            "scene": None,
            "camera_pose_synced": True,
            "dynamic_actors_synced": False,
            "robot_joint_state_synced": False,
            "real_camera": False,
            # The ONE key this card adds to C-1's literal, and it is here to
            # make a silent ignore visible rather than to change anything: the
            # simulator venue does not honour `perception.detector`. Nothing
            # else in the block moved.
            "detector": {
                "kind": "in_process",
                "configured": None,
                "honoured": True,
            },
        }
    finally:
        runtime.close()


def test_the_simulator_venue_says_it_does_not_honour_the_detector_key(
    tmp_path: Path,
) -> None:
    """`perception.detector: daemon` is read by nothing on C-1's path.

    Before the correction pass it was also refused by nothing: the key was
    validated inside the PHYSICAL attach, so a simulator run took a typo, a
    deliberate `daemon`, or anything else in silence. That is the exact class
    of defect CAP-1 exists for — a knob the operator set and the product never
    read.
    """

    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK + "  detector: daemon\n"))
    try:
        assert runtime._venue1_detector_choice() == "daemon"
        composition = runtime.camera_stream_snapshot()["composition"]
        assert composition["detector"] == {
            "kind": "in_process",
            "configured": "daemon",
            "honoured": False,
        }
    finally:
        runtime.close()


def test_a_detector_typo_refuses_on_the_simulator_venue_too(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK + "  detector: deamon\n"))
    try:
        with pytest.raises(ValueError, match="perception.detector"):
            runtime._attach_configured_camera_ingress()
    finally:
        runtime.close()


def test_an_explicit_mujoco_venue_is_the_same_as_no_venue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "mujoco")
    runtime = _runtime(_config(tmp_path))
    try:
        assert runtime._venue1_resolve_venue() is None
    finally:
        runtime.close()


def test_the_camera_off_path_never_resolves_a_venue(tmp_path: Path) -> None:
    off = "  spatial_sensors: [camera, lidar]\n  camera_ingress: false\n"
    runtime = _runtime(_config(tmp_path, perception=off))
    try:
        runtime._attach_configured_camera_ingress()
        assert runtime._camera_ingress is None
        assert runtime.camera_stream_snapshot() is None
        assert runtime.venue_snapshot() is None
    finally:
        runtime.close()


# ===========================================================================
# R9 — an RGB-only venue says so; it never silently passes a depth gate
# ===========================================================================


def test_an_rgb_only_venue_says_depth_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "uvc")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _RgbOnlyDouble())
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        composition = runtime.venue_snapshot()
        assert composition is not None
        assert composition["depth_available"] is False
        assert "depth_unavailable" in composition["depth_note"]
        _drive(runtime, 10)
        # P1-A measured this at the seam: no metric depth ⇒ no localization ⇒
        # nothing published, counted as an error rather than an empty room.
        assert runtime._camera_frames_published == 0
        ingress = runtime._camera_ingress
        assert ingress.stats.errors == 10
        assert runtime._p1b_learned_map is None
    finally:
        runtime.close()


def test_the_operator_surface_stops_saying_static_scene_on_a_real_camera(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`real_camera: False` while a D455 streams is the same class of lie as a
    frame stamped `unknown`."""

    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    _use_double(monkeypatch, _DepthDouble())
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        composition = runtime.camera_stream_snapshot()["composition"]
        assert composition["mode"] == "physical_camera"
        assert composition["real_camera"] is True
        assert composition["evidence_origin"] == EvidenceOrigin.PHYSICAL.value
        assert composition["scene"] is None
        assert composition["dynamic_actors_synced"] is True
        assert composition["depth_available"] is True
    finally:
        runtime.close()


def test_a_recorded_venue_is_not_a_real_camera_on_the_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    monkeypatch.setattr(
        "parcel_robot.detection_adapter.owlv2_onnx.load_owlv2_detector",
        lambda **_: _StubDetector(),
    )
    runtime = _runtime(_config(tmp_path))
    try:
        runtime._attach_configured_camera_ingress()
        composition = runtime.camera_stream_snapshot()["composition"]
        assert composition["venue"] == "recorded"
        assert composition["real_camera"] is False
        assert composition["evidence_origin"] == EvidenceOrigin.REPLAY.value
    finally:
        runtime.close()


# ===========================================================================
# the refusals that protect the declaration itself
# ===========================================================================


def test_an_ingress_whose_backend_declares_nothing_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one line this card turns on, guarded rather than trusted.

    ``camera_ingress_kwargs`` derives ``origin`` from the backend. If that ever
    stops happening, the attach must fail loudly here rather than publish a
    stream of frames stamped ``unknown`` while the buffers say ``physical``.
    """

    from parcel_robot.camera_channel.backends import physical as physical_module

    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    double = _DepthDouble()
    _use_double(monkeypatch, double)
    real_kwargs = physical_module.camera_ingress_kwargs

    def _stripped(backend: Any) -> dict[str, Any]:
        kwargs = dict(real_kwargs(backend))
        kwargs.pop("origin", None)
        return kwargs

    monkeypatch.setattr(physical_module, "camera_ingress_kwargs", _stripped)
    runtime = _runtime(_config(tmp_path))
    try:
        with pytest.raises(RuntimeError, match="no declared EvidenceOrigin"):
            runtime._attach_configured_camera_ingress()
        assert runtime._camera_ingress is None
    finally:
        runtime.close()


@pytest.mark.skipif(
    bool(_attached_realsense()),
    reason=(
        "a RealSense IS attached, so the real open path succeeds and this row "
        "no longer has a subject; the attached arm is OWNER-GATED as OG-1 in "
        "scrum/20260822/task_16/VENUE1_STATUS.md §6"
    ),
)
def test_a_venue_that_cannot_open_names_the_presence_check_not_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No camera is attached to this host, and the refusal says so with the
    remedy for THAT kind — through the two probes that already exist.

    HOST-CONDITIONAL, and marked as such rather than left to look universal:
    this is the only cell in the file that drives the REAL
    ``open_physical_backend`` with no double, so it passes here because
    ``connected_devices()`` is empty. The verifier reproduced its failure
    against a D455-shaped double (``DID NOT RAISE``). What it pins is the
    refusal MESSAGE on a host with no camera; the attached case is OG-1.
    """

    monkeypatch.setenv("PARCEL_CAMERA_BACKEND", "realsense")
    runtime = _runtime(_config(tmp_path))
    try:
        with pytest.raises(RuntimeError) as excinfo:
            runtime._attach_configured_camera_ingress()
        message = str(excinfo.value)
        assert "realsense" in message
        assert "RealSense devices on the bus" in message
        assert runtime._camera_ingress is None
    finally:
        runtime.close()


def test_an_unknown_detector_choice_refuses_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_venue: Path
) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK + "  detector: deamon\n"))
    try:
        with pytest.raises(ValueError, match="perception.detector"):
            runtime._attach_configured_camera_ingress()
    finally:
        runtime.close()
