"""Card P1-A — the out-of-process perception daemon's contract.

The daemon owns the GPU; the runtime owns a socket. These cells prove the three
properties that make that trade safe, on a stub detector so the suite costs
milliseconds instead of a 200 MB ONNX session:

1. **The contract is typed and closed.** A wrong protocol version, a payload
   whose declared size does not match its shape, an unknown operation and an
   over-long query batch are all REFUSALS with the reason in them.
2. **Unavailability degrades, it does not crash.** With no daemon,
   ``DaemonDetector.detect`` returns ``[]`` and sets ``stale`` — and
   ``CameraIngress.poll_once``, which is what the robot actually calls,
   completes.
3. **A daemon restart costs no client restart.** The same ``DaemonDetector``
   answers again after the daemon is stopped and started on the same socket.

The GPU numbers themselves are P0-C's (98 ms p50 idle, 132–139 ms under this
wave's load) and are re-measured on the desk camera; what is measured HERE is
the round-trip OVERHEAD the process boundary adds.
"""

from __future__ import annotations

import os
import socket
import stat
import statistics
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from parcel_robot.camera_channel.backends.physical import camera_ingress_kwargs
from parcel_robot.camera_channel.backends.recorded import RecordedCameraBackend
from parcel_robot.detection_adapter.pixel_detections import Detector, PixelDetection
from parcel_robot.perception_daemon import (
    MAX_QUERY_PHRASES,
    PROTOCOL_VERSION,
    DaemonClient,
    DaemonDetector,
    DaemonEmbedder,
    DaemonRequestFailed,
    DaemonUnavailable,
    PerceptionDaemon,
    ProtocolError,
)
from parcel_robot.perception_daemon import protocol as proto

CLIP = Path(__file__).parent / "data" / "p1a_desk_clip.npz"


class StubDetector:
    """One box per query phrase, so a response is attributable to its request."""

    name = "stub-owlv2"

    class resolution:
        selected = "cuda_fp16"
        execution_providers = ("CUDAExecutionProvider", "CPUExecutionProvider")

    def __init__(self, *, delay_s: float = 0.0, boom: bool = False, count: int = 1) -> None:
        self.delay_s = delay_s
        self.boom = boom
        self.count = count
        self.calls = 0
        self.last_query: list[str] = []

    def detect(self, *, rgb, depth, seg, query):
        self.calls += 1
        self.last_query = list(query)
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.boom:
            raise RuntimeError("the model fell over")
        return [
            PixelDetection(label=str(phrase), score=0.75, box=(1, 2, 20, 30))
            for phrase in list(query)[: self.count]
        ]


class StubEmbedder:
    def __init__(self, dims: int = 8) -> None:
        self.dims = dims

    def embed_image(self, image):
        arr = np.asarray(image, dtype=np.float64)
        base = float(arr.mean()) if arr.size else 0.0
        return tuple(base + i for i in range(self.dims))

    def embed_text(self, text):
        return tuple(float(len(text) + i) for i in range(self.dims))


@pytest.fixture
def socket_path(tmp_path) -> str:
    # Unique per test: this tree has other executors and the owner's live stack.
    return str(tmp_path / "p1a_perception.sock")


@pytest.fixture
def detector() -> StubDetector:
    return StubDetector()


@pytest.fixture
def daemon(socket_path, detector):
    server = PerceptionDaemon(
        socket_path, detector_factory=lambda: detector, embedder_factory=StubEmbedder
    )
    server.start()
    try:
        yield server
    finally:
        server.stop()


def rgb(width=64, height=48, fill=7) -> np.ndarray:
    return np.full((height, width, 3), fill, dtype=np.uint8)


# ------------------------------------------------------------- protocol -----
def test_a_message_round_trips_its_header_and_its_arrays():
    left, right = socket.socketpair()
    try:
        array = np.arange(24, dtype=np.uint8).reshape(2, 4, 3)
        left.sendall(proto.encode(proto.request_header("detect", 5, query=["person"]),
                                  {"rgb": array}))
        header, arrays = proto.decode(right)
        assert header["op"] == "detect"
        assert header["id"] == 5
        assert header["query"] == ["person"]
        assert np.array_equal(arrays["rgb"], array)
        assert "parts" not in header
    finally:
        left.close()
        right.close()


def test_a_peer_from_another_protocol_version_is_refused():
    left, right = socket.socketpair()
    try:
        left.sendall(proto.encode({"v": PROTOCOL_VERSION + 1, "op": "health", "id": 1}))
        with pytest.raises(ProtocolError, match="protocol version"):
            proto.decode(right)
    finally:
        left.close()
        right.close()


def test_a_part_whose_declared_size_disagrees_with_its_shape_is_refused():
    with pytest.raises(ProtocolError, match="declares 999 bytes"):
        proto.Part(name="rgb", dtype="uint8", shape=(2, 2, 3), nbytes=999)


def test_an_exotic_dtype_never_reaches_numpy():
    with pytest.raises(ProtocolError, match="not allowed"):
        proto.Part(name="rgb", dtype="object", shape=(2,), nbytes=16)


def test_a_truncated_payload_is_a_transport_failure_not_a_short_read():
    left, right = socket.socketpair()
    try:
        blob = proto.encode(proto.request_header("detect", 1, query=["person"]),
                            {"rgb": rgb(8, 8)})
        left.sendall(blob[: len(blob) - 32])
        left.close()
        with pytest.raises(DaemonUnavailable, match="closed the connection mid-message"):
            proto.decode(right)
    finally:
        right.close()


def test_the_query_ceiling_is_the_frame_ceiling():
    """Fable's wave row D-R2: crossing it downstream is SILENT blindness."""

    from parcel_robot.camera_channel.ingress import CameraDetectionFrame  # noqa: F401

    assert MAX_QUERY_PHRASES == 16
    ok = [f"thing {i}" for i in range(MAX_QUERY_PHRASES)]
    assert proto.normalize_query(ok) == tuple(ok)
    with pytest.raises(ProtocolError, match="17 phrases; the ceiling is 16"):
        proto.normalize_query([*ok, "one too many"])


def test_duplicates_and_whitespace_do_not_spend_the_query_budget():
    assert proto.normalize_query(["  person ", "person", "person\t"]) == ("person",)
    assert proto.normalize_query("a  chair") == ("a chair",)
    assert proto.normalize_query(None) == ()


def test_an_absurdly_long_phrase_is_refused():
    with pytest.raises(ProtocolError, match="exceeds 64 characters"):
        proto.normalize_query(["x" * 65])


def test_the_default_socket_is_not_the_simulators_socket():
    assert proto.default_socket_path() != "/tmp/parcel_sim.sock"
    assert proto.default_socket_path().endswith("parcel_perception.sock")


# --------------------------------------------------------------- serving ----
def test_a_detect_round_trip_returns_typed_detections(daemon, socket_path, detector):
    client = DaemonClient(socket_path)
    try:
        response = client.detect(rgb(), ["person", "chair"])
    finally:
        client.close()
    assert response["status"] == "ok"
    assert [row["label"] for row in response["detections"]] == ["person"]
    assert response["provider_profile"] == "cuda_fp16"
    assert response["execution_providers"][0] == "CUDAExecutionProvider"
    assert detector.last_query == ["person", "chair"]


def test_health_answers_before_any_model_is_loaded(daemon, socket_path):
    client = DaemonClient(socket_path)
    try:
        report = client.health()
    finally:
        client.close()
    assert report["protocol_version"] == PROTOCOL_VERSION
    assert report["detector_loaded"] is False
    assert report["socket"] == socket_path
    assert report["pid"] == os.getpid()


def test_the_socket_is_owner_only(daemon, socket_path):
    mode = os.stat(socket_path).st_mode
    assert stat.S_ISSOCK(mode)
    assert stat.S_IMODE(mode) == 0o600


def test_the_daemon_refuses_to_replace_a_path_that_is_not_a_socket(tmp_path):
    victim = tmp_path / "important.txt"
    victim.write_text("not a socket", encoding="utf-8")
    server = PerceptionDaemon(victim, detector_factory=lambda: StubDetector())
    with pytest.raises(FileExistsError, match="refusing to replace non-socket"):
        server.start()
    assert victim.read_text(encoding="utf-8") == "not a socket"


def test_the_socket_file_is_removed_on_stop(socket_path):
    server = PerceptionDaemon(socket_path, detector_factory=lambda: StubDetector())
    server.start()
    assert Path(socket_path).exists()
    server.stop()
    assert not Path(socket_path).exists()


def test_embeddings_cross_the_boundary_as_float32(daemon, socket_path):
    embedder = DaemonEmbedder(socket_path)
    try:
        image = embedder.embed_image(rgb(fill=10))
        text = embedder.embed_text("a red chair")
    finally:
        embedder.close()
    assert image[0] == pytest.approx(10.0)
    assert len(image) == 8
    assert text[0] == pytest.approx(11.0)


def test_an_unknown_operation_is_refused_without_killing_the_daemon(daemon, socket_path):
    client = DaemonClient(socket_path)
    try:
        with pytest.raises(ProtocolError, match="unknown operation"):
            client.request("teleport")
        # The daemon is still there.
        assert client.health()["protocol_version"] == PROTOCOL_VERSION
    finally:
        client.close()


def test_a_detector_that_raises_becomes_an_error_response_not_a_dead_daemon(socket_path):
    boom = StubDetector(boom=True)
    server = PerceptionDaemon(socket_path, detector_factory=lambda: boom)
    server.start()
    client = DaemonClient(socket_path)
    try:
        with pytest.raises(DaemonRequestFailed) as caught:
            client.detect(rgb(), ["person"])
        assert "the model fell over" in str(caught.value)
        assert caught.value.kind == "internal"
        report = client.health()
        assert report["errors"] == 1
        assert "fell over" in report["last_error"]
    finally:
        client.close()
        server.stop()


def test_an_empty_query_is_refused_at_the_daemon_too(daemon, socket_path):
    client = DaemonClient(socket_path)
    try:
        with pytest.raises(DaemonRequestFailed, match="non-empty query"):
            client.request("detect", arrays={"rgb": rgb()}, query=[])
    finally:
        client.close()


def test_a_detect_without_pixels_is_refused(daemon, socket_path):
    client = DaemonClient(socket_path)
    try:
        with pytest.raises(DaemonRequestFailed, match="requires an 'rgb' array part"):
            client.request("detect", query=["person"])
    finally:
        client.close()


def test_a_health_probe_does_not_queue_behind_a_slow_detect(socket_path):
    slow = StubDetector(delay_s=0.4)
    server = PerceptionDaemon(socket_path, detector_factory=lambda: slow)
    server.start()
    detect_client = DaemonClient(socket_path)
    probe_client = DaemonClient(socket_path)
    try:
        done = threading.Event()

        def run_detect():
            try:
                detect_client.detect(rgb(), ["person"])
            finally:
                done.set()

        worker = threading.Thread(target=run_detect)
        worker.start()
        time.sleep(0.05)
        started = time.perf_counter()
        probe_client.health()
        probe_ms = (time.perf_counter() - started) * 1000.0
        worker.join(timeout=5.0)
        assert done.is_set()
        assert probe_ms < 200.0, f"health probe waited {probe_ms:.1f} ms behind a detect"
    finally:
        detect_client.close()
        probe_client.close()
        server.stop()


# ------------------------------------------------------------ degradation ---
def test_an_unreachable_daemon_returns_nothing_and_says_it_is_stale(tmp_path):
    detector = DaemonDetector(str(tmp_path / "absent.sock"))
    try:
        assert detector.detect(rgb=rgb(), depth=None, seg=None, query=["person"]) == []
        assert detector.stale is True
        assert detector.consecutive_failures == 1
        assert "cannot reach" in detector.snapshot()["last_error"]
    finally:
        detector.close()


def test_the_ingress_survives_an_unreachable_daemon(tmp_path):
    """The property the whole process boundary is for.

    ``CameraIngress.poll_once`` is what the robot calls. With no daemon it must
    complete — publishing an honest empty frame — rather than leaving the last
    good candidate buffer in place while only an error counter moves.
    """

    from parcel_robot.camera_channel.ingress import CameraIngress

    backend = RecordedCameraBackend(CLIP)
    detector = DaemonDetector(str(tmp_path / "absent.sock"))
    published: list[object] = []
    ingress = CameraIngress(
        **camera_ingress_kwargs(backend),
        detector=detector,
        on_frame=published.append,
    )
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.set_query(["person"])
    try:
        candidates = ingress.poll_once()
    finally:
        detector.close()
    assert candidates == []
    assert ingress.stats.errors == 0, "an unreachable daemon must not look like a crash"
    assert len(published) == 1
    assert published[0].localized_detections == 0
    assert detector.stale is True
    # An honest empty frame still has to say WHERE it came from: the published
    # record, not just the buffers behind it, carries the declared origin.
    assert published[0].origin == "replay"
    assert published[0].origin == backend.origin.value


def test_a_malformed_query_raises_instead_of_going_quietly_blind(tmp_path):
    detector = DaemonDetector(str(tmp_path / "absent.sock"))
    try:
        with pytest.raises(ProtocolError, match="the ceiling is 16"):
            detector.detect(
                rgb=rgb(), depth=None, seg=None, query=[f"q{i}" for i in range(17)]
            )
        # A caller bug is not a daemon failure: nothing was marked stale by it.
        assert detector.consecutive_failures == 0
    finally:
        detector.close()


def test_a_dead_daemon_is_not_reconnected_to_on_every_single_frame(tmp_path):
    ticks = [0.0]
    detector = DaemonDetector(
        str(tmp_path / "absent.sock"), retry_interval_s=5.0, clock=lambda: ticks[0]
    )
    try:
        detector.detect(rgb=rgb(), depth=None, seg=None, query=["person"])
        assert detector.consecutive_failures == 1
        for _ in range(20):
            assert detector.detect(rgb=rgb(), depth=None, seg=None, query=["person"]) == []
        assert detector.consecutive_failures == 1, "backoff must suppress the retries"
        ticks[0] = 10.0
        detector.detect(rgb=rgb(), depth=None, seg=None, query=["person"])
        assert detector.consecutive_failures == 2, "and must expire"
    finally:
        detector.close()


def test_the_same_client_survives_a_daemon_restart(socket_path):
    server = PerceptionDaemon(socket_path, detector_factory=lambda: StubDetector())
    server.start()
    detector = DaemonDetector(socket_path, retry_interval_s=0.0)
    try:
        assert detector.detect(rgb=rgb(), depth=None, seg=None, query=["person"])
        assert detector.stale is False

        server.stop()
        assert detector.detect(rgb=rgb(), depth=None, seg=None, query=["person"]) == []
        assert detector.stale is True

        server = PerceptionDaemon(socket_path, detector_factory=lambda: StubDetector())
        server.start()
        found = detector.detect(rgb=rgb(), depth=None, seg=None, query=["person"])
        assert [d.label for d in found] == ["person"]
        assert detector.stale is False
        assert detector.consecutive_failures == 0
    finally:
        detector.close()
        server.stop()


def test_the_daemon_detector_is_a_drop_in_for_the_detector_protocol(socket_path):
    detector = DaemonDetector(socket_path)
    try:
        assert isinstance(detector, Detector)
    finally:
        detector.close()


def test_the_provider_that_answered_survives_the_process_boundary(daemon, socket_path):
    detector = DaemonDetector(socket_path)
    try:
        detector.detect(rgb=rgb(), depth=None, seg=None, query=["person"])
        assert detector.resolution.selected == "cuda_fp16"
        assert detector.resolution.execution_providers[0] == "CUDAExecutionProvider"
        assert detector.name == "stub-owlv2-daemon"
    finally:
        detector.close()


def test_a_refusal_from_the_daemon_is_not_a_stale_detector(socket_path):
    boom = StubDetector(boom=True)
    server = PerceptionDaemon(socket_path, detector_factory=lambda: boom)
    server.start()
    detector = DaemonDetector(socket_path)
    try:
        assert detector.detect(rgb=rgb(), depth=None, seg=None, query=["person"]) == []
        assert detector.stale is False, "the daemon answered; it just refused"
        assert "fell over" in detector.snapshot()["last_error"]
    finally:
        detector.close()
        server.stop()


# ------------------------------------------------------------- end to end ---
def test_a_recorded_clip_reaches_the_daemon_and_comes_back_localized(daemon, socket_path):
    """The two halves of this card, composed — without touching ingress.py."""

    from parcel_robot.camera_channel.ingress import CameraIngress

    backend = RecordedCameraBackend(CLIP)
    detector = DaemonDetector(socket_path)
    published: list[object] = []
    ingress = CameraIngress(
        **camera_ingress_kwargs(backend),
        detector=detector,
        on_frame=published.append,
    )
    ingress.set_pose(1.0, 2.0, 0.0)
    ingress.set_query(["person"])
    try:
        candidates = ingress.poll_once()
    finally:
        detector.close()
    assert candidates, "a detection from the daemon must reach the candidate list"
    assert candidates[0]["label"] == "person"
    frame = published[0]
    assert frame.detector_name == "stub-owlv2-daemon"
    assert frame.provider_profile == "cuda_fp16"
    assert frame.localized_detections == 1
    assert frame.queries == ("person",)
    assert backend.last_buffers.origin.value == "replay"
    # The PUBLISHED frame — the thing every downstream reader sees — carries the
    # origin too, not only the buffers the ingress consumed.
    assert frame.origin == "replay"


class _FakeUvcCap:
    """Minimal ``cv2.VideoCapture`` double so a PHYSICAL venue is reachable here."""

    def __init__(self, width: int = 128, height: int = 96) -> None:
        self.width, self.height, self.reads = width, height, 0

    def isOpened(self):
        return True

    def set(self, prop, value):
        return True

    def get(self, prop):
        return {3: self.width, 4: self.height, 5: 30}.get(prop, 0)

    def read(self):
        self.reads += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[..., 2] = 200
        return True, frame

    def release(self):
        return None


class _FakeRealSenseSession:
    """RGB + color-aligned metric depth, so the ingress can actually localize."""

    def __init__(self, *, width_px=128, height_px=96, **_):
        self.width, self.height = width_px, height_px

    def start(self):
        from parcel_robot.camera_channel.backends.realsense import RealSenseProfile

        return RealSenseProfile(
            width_px=self.width,
            height_px=self.height,
            fx=110.85,
            fy=110.85,
            cx=self.width / 2.0,
            cy=self.height / 2.0,
            depth_scale_m=0.001,
            serial="P1AFIX01",
        )

    def read(self):
        colour = np.full((self.height, self.width, 3), 90, dtype=np.uint8)
        colour[30:70, 50:70] = 210
        return colour, np.full((self.height, self.width), 1.85, dtype=np.float32)

    def stop(self):
        return None


def _physical_backend():
    """A PHYSICAL venue that carries depth — the one the ingress can consume.

    Not the UVC double: a webcam has no depth, and ``CameraIngress`` refuses a
    capture without a depth raster ("camera backend produced no RGB/depth
    buffers"). That is the real, stated limitation of the RGB-only venue and it
    is pinned by its own cell below rather than worked around here.
    """

    from parcel_robot.camera_channel.backends.realsense import RealSenseCameraBackend

    return RealSenseCameraBackend(
        width_px=128,
        height_px=96,
        session_factory=lambda **kw: _FakeRealSenseSession(**kw),
    )


def _uvc_backend():
    from parcel_robot.camera_channel.backends.uvc import UvcCameraBackend

    return UvcCameraBackend(
        0, width_px=128, height_px=96, capture_factory=lambda _d: _FakeUvcCap()
    )


def test_an_rgb_only_venue_cannot_feed_the_ingress_and_says_so(daemon, socket_path):
    """The UVC limitation, at the seam where it actually bites.

    A webcam reaches the DETECTOR fine — boxes come back — but
    ``CameraIngress`` needs metric depth to place a box in the world, so a
    depth-less capture is a counted poll error and NO frame is published. This
    is the intended failure: a constant "assumed depth plane" would produce
    world coordinates that look like measurements and are not. The venue that
    maps is the D455.
    """

    from parcel_robot.camera_channel.ingress import CameraIngress

    backend = _uvc_backend()
    detector = DaemonDetector(socket_path)
    published: list = []
    ingress = CameraIngress(
        **camera_ingress_kwargs(backend),
        detector=detector,
        on_frame=published.append,
    )
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.set_query(["person"])
    try:
        assert ingress.poll_once() is None
    finally:
        detector.close()
        backend.close()
    assert backend.last_buffers.origin.value == "physical"
    assert backend.last_buffers.depth_m_f32 is None
    assert published == [], "no depth means no localization, so nothing is published"
    assert ingress.stats.errors == 1
    assert "no RGB/depth buffers" in ingress.stats.last_error


def test_a_physical_backend_publishes_frames_that_say_physical(daemon, socket_path):
    """The one property this whole card exists to deliver, at the PUBLISHED record.

    ``CameraIngress`` stamps ``CameraDetectionFrame.origin`` from its OWN
    ``origin`` field — it never reads ``PhysicalCaptureBuffers.origin``. So
    honest buffers are not enough: the composition root has to declare, and
    ``camera_ingress_kwargs`` is what makes that impossible to forget.
    """

    from parcel_robot.camera_channel.ingress import CameraIngress

    backend = _physical_backend()
    detector = DaemonDetector(socket_path)
    published: list = []
    ingress = CameraIngress(
        **camera_ingress_kwargs(backend),
        detector=detector,
        on_frame=published.append,
    )
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.set_query(["person"])
    try:
        ingress.poll_once()
    finally:
        detector.close()
        backend.close()
    assert backend.last_buffers.origin.value == "physical"
    assert published, "a completed cycle must publish a frame"
    for frame in published:
        assert frame.origin == "physical", (
            "a desk frame that publishes as anything else is confusable with a "
            "sim frame everywhere downstream"
        )


def test_camera_ingress_kwargs_carries_the_declaration_the_ingress_cannot_infer():
    backend = _physical_backend()
    try:
        kwargs = camera_ingress_kwargs(backend)
    finally:
        backend.close()
    assert kwargs["origin"] == "physical"
    assert kwargs["intrinsics"] is backend.spec.intrinsics
    assert kwargs["mount"] is backend.spec.mount
    # No 1 cm trim: that trim is a MuJoCo depth-clip workaround, not a sensor fact.
    assert kwargs["depth_max_m"] == pytest.approx(backend.spec.depth_max_m)


def test_camera_ingress_kwargs_refuses_a_backend_it_cannot_vouch_for():
    with pytest.raises(TypeError, match="expects a physical CameraBackend"):
        camera_ingress_kwargs(object())


@pytest.mark.xfail(
    reason=(
        "HAZARD PIN, card P1-A / Fable's P1-A verification. CameraIngress.origin "
        "defaults to 'unknown' and the published CameraDetectionFrame is stamped "
        "from it, so an ingress built over a REAL camera without origin= publishes "
        "every frame as 'unknown' while its buffers correctly say 'physical'. The "
        "ingress cannot refuse this today — ingress.py is P1-B's file and the "
        "'unknown' default is deliberate there (a renderer that could mint "
        "'physical' by default is the W0-A defect). This cell asserts the CORRECT "
        "behaviour so it is RED until a composition root or the ingress itself "
        "closes the gap: VENUE-1 inherits a red it must turn green. "
        "camera_ingress_kwargs() is the mitigation in the meantime."
    ),
    strict=True,
)
def test_an_ingress_built_without_a_declared_origin_must_not_publish_unknown(
    daemon, socket_path
):
    from parcel_robot.camera_channel.ingress import CameraIngress

    backend = _physical_backend()
    detector = DaemonDetector(socket_path)
    published: list = []
    ingress = CameraIngress(
        backend=backend,
        detector=detector,
        intrinsics=backend.spec.intrinsics,
        mount=backend.spec.mount,
        depth_min_m=backend.spec.depth_min_m,
        depth_max_m=backend.spec.depth_max_m,
        on_frame=published.append,
        # origin= deliberately omitted — this is the hazard.
    )
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.set_query(["person"])
    try:
        ingress.poll_once()
    finally:
        detector.close()
        backend.close()
    assert backend.last_buffers.origin.value == "physical"
    assert published[0].origin != "unknown", (
        "physical pixels published as 'unknown' — the buffers are honest and every "
        "derived record is not"
    )


def test_the_hazard_is_real_today_and_this_is_what_it_looks_like(daemon, socket_path):
    """The same construction, asserted as it BEHAVES, so the pin cannot rot.

    Paired with the xfail above: that one says what must become true, this one
    records what is true now. If P1-B ever changes the default, this cell goes
    red and both are revisited together.
    """

    from parcel_robot.camera_channel.ingress import CameraIngress

    backend = _physical_backend()
    detector = DaemonDetector(socket_path)
    published: list = []
    ingress = CameraIngress(
        backend=backend,
        detector=detector,
        intrinsics=backend.spec.intrinsics,
        mount=backend.spec.mount,
        depth_min_m=backend.spec.depth_min_m,
        depth_max_m=backend.spec.depth_max_m,
        on_frame=published.append,
    )
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.set_query(["person"])
    try:
        ingress.poll_once()
    finally:
        detector.close()
        backend.close()
    assert backend.last_buffers.origin.value == "physical"
    assert published[0].origin == "unknown"


def test_the_round_trip_overhead_is_measured_and_reported(daemon, socket_path, capsys):
    """Pre-registered row C5: p50 ≤ 15 ms, p95 ≤ 40 ms for a 640×480 frame.

    This is the cost the PROCESS BOUNDARY adds, on a stub detector — not the
    detector's own latency, which is P0-C's measurement and is load-conditional
    (98 ms p50 idle, 132–139 ms under wave load; Fable row C-1).
    """

    frame = rgb(640, 480)
    client = DaemonClient(socket_path)
    samples: list[float] = []
    try:
        client.detect(frame, ["person"])  # warm the connection
        for _ in range(100):
            started = time.perf_counter()
            client.detect(frame, ["person"])
            samples.append((time.perf_counter() - started) * 1000.0)
    finally:
        client.close()
    p50 = statistics.median(samples)
    p95 = sorted(samples)[94]
    with capsys.disabled():
        print(f"\n[P1-A C5] round-trip overhead 640x480x3: p50={p50:.2f} ms p95={p95:.2f} ms")
    assert p50 <= 15.0, f"p50 {p50:.2f} ms exceeds the pre-registered 15 ms"
    assert p95 <= 40.0, f"p95 {p95:.2f} ms exceeds the pre-registered 40 ms"
