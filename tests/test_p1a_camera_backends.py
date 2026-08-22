"""Card P1-A — the physical camera backends' contract, on recorded frames.

No camera is attached to this host (measured 2026-08-22: no ``/dev/video*``,
``rs.context().query_devices()`` → 0 devices), so the LIVE rows are owner-gated
and listed in ``scrum/20260822/task_6/P1A_STATUS.md``. What runs here is the
contract every venue must satisfy whether the pixels came from a webcam, a
D455 or a committed clip:

* provenance is DECLARED — ``PHYSICAL`` only from live hardware, ``REPLAY``
  from a clip, and a bare string that spells an origin is refused;
* capture stamps STRICTLY INCREASE, because frame age is computed from them;
* the envelope's intrinsics describe the raster that actually arrived;
* a webcam can never claim the simulator's nominal calibration id.

Three of these are seeded RED in the status doc.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pytest

from parcel_robot.camera_channel.backends.physical import (
    CAMERA_BACKEND_ENV,
    PHYSICAL_BACKEND_KINDS,
    PhysicalCameraBackendBase,
    PhysicalCameraUnavailable,
    PhysicalCaptureBuffers,
    intrinsics_from_config,
    load_camera_config,
    mount_from_config,
    open_physical_backend,
    resolve_backend_kind,
    scale_intrinsics,
    spec_from_config,
    uncalibrated_intrinsics,
)
from parcel_robot.camera_channel.backends.realsense import (
    RealSenseCameraBackend,
    RealSenseProfile,
    RealSenseUnavailable,
)
from parcel_robot.camera_channel.backends.recorded import (
    ClipExhausted,
    ClipInvalid,
    RecordedCameraBackend,
    read_clip,
    record_clip,
    write_clip,
)
from parcel_robot.camera_channel.backends.uvc import (
    MAX_CONSECUTIVE_READ_FAILURES,
    UvcCameraBackend,
    UvcCameraUnavailable,
)
from parcel_robot.camera_channel.channel import CameraBackend, assert_nominal_d455_contract
from parcel_robot.camera_channel.d455 import CALIBRATION_ID_NOMINAL
from parcel_robot.evidence_origin import EvidenceOrigin

CLIP = Path(__file__).parent / "data" / "p1a_desk_clip.npz"


# ---------------------------------------------------------------- doubles ---
class FakeCap:
    """A ``cv2.VideoCapture`` stand-in with a scriptable failure schedule."""

    def __init__(self, *, width=128, height=96, fail_after=None, negotiated=None):
        self.width = width
        self.height = height
        self.negotiated = negotiated or (width, height)
        self.fail_after = fail_after
        self.reads = 0
        self.released = False
        self.props: dict[int, float] = {}

    def isOpened(self):
        return True

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def get(self, prop):
        return {3: self.negotiated[0], 4: self.negotiated[1], 5: 30}.get(prop, 0)

    def read(self):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            return False, None
        h, w = self.negotiated[1], self.negotiated[0]
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[..., 0] = 11  # B
        frame[..., 1] = min(255, self.reads)  # G
        frame[..., 2] = 222  # R
        return True, frame

    def release(self):
        self.released = True


class FakeRealSenseSession:
    def __init__(self, *, width_px=128, height_px=96, serial="P1A0001", **_):
        self.width = width_px
        self.height = height_px
        self.serial = serial
        self.started = False
        self.stopped = False
        self.misaligned = False

    def start(self):
        self.started = True
        return RealSenseProfile(
            width_px=self.width,
            height_px=self.height,
            fx=97.5,
            fy=97.5,
            cx=self.width / 2.0,
            cy=self.height / 2.0,
            depth_scale_m=0.001,
            serial=self.serial,
        )

    def read(self):
        rgb = np.full((self.height, self.width, 3), 33, dtype=np.uint8)
        shape = (self.height // 2, self.width) if self.misaligned else (self.height, self.width)
        return rgb, np.full(shape, 2.25, dtype=np.float32)

    def stop(self):
        self.stopped = True


def uvc(**kwargs) -> UvcCameraBackend:
    cap = kwargs.pop("cap", None) or FakeCap()
    kwargs.setdefault("width_px", cap.width)
    kwargs.setdefault("height_px", cap.height)
    return UvcCameraBackend(0, capture_factory=lambda _d: cap, **kwargs)


def realsense(**kwargs) -> RealSenseCameraBackend:
    session = kwargs.pop("session", None) or FakeRealSenseSession()
    kwargs.setdefault("width_px", session.width)
    kwargs.setdefault("height_px", session.height)
    return RealSenseCameraBackend(session_factory=lambda **_: session, **kwargs)


# ------------------------------------------------- the fixture clip itself ---
def test_the_committed_clip_loads_and_agrees_with_its_own_pixels():
    manifest, color, depth = read_clip(CLIP)
    assert manifest.clip_id == "p1a-desk-synth-v1"
    assert color.shape == (manifest.frames, manifest.height_px, manifest.width_px, 3)
    assert depth is not None and depth.shape == color.shape[:3]
    assert manifest.captured_origin is EvidenceOrigin.SIMULATION
    # The fixture is honest about being synthetic; nothing here claims otherwise.
    assert "SYNTHETIC" in manifest.notes


def test_a_manifest_that_disagrees_with_its_pixels_is_refused(tmp_path):
    import json

    manifest, color, _ = read_clip(CLIP)
    bad = dict(manifest.as_dict())
    bad["frames"] = manifest.frames + 3
    target = tmp_path / "lying.npz"
    with target.open("wb") as handle:
        np.savez_compressed(handle, color=color, manifest=np.asarray(json.dumps(bad)))
    with pytest.raises(ClipInvalid, match="disagrees with its own pixels"):
        read_clip(target)


# ------------------------------------------------------------ provenance ----
@pytest.mark.parametrize("factory", [uvc, realsense], ids=["uvc", "realsense"])
def test_a_live_backend_stamps_physical_on_every_frame(factory):
    backend = factory()
    with backend:
        for _ in range(100):
            backend.capture()
            buffers = backend.last_buffers
            assert buffers is not None
            assert buffers.origin is EvidenceOrigin.PHYSICAL
            assert buffers.is_physical
    assert backend.captures == 100


def test_a_recorded_clip_stamps_replay_and_never_physical():
    backend = RecordedCameraBackend(CLIP)
    with backend:
        for _ in range(100):
            backend.capture()
            buffers = backend.last_buffers
            assert buffers is not None
            assert buffers.origin is EvidenceOrigin.REPLAY
            assert not buffers.is_physical


def test_a_clip_recorded_from_a_camera_still_replays_as_replay(tmp_path):
    """The provenance rule that makes the whole card mean something.

    ``captured_origin`` records what the pixels WERE; the replay's origin is
    what they ARE now. A file may not mint live physical authority.
    """

    live = uvc()
    clip = tmp_path / "desk.npz"
    manifest = record_clip(live, clip, frames=4, clip_id="desk-live")
    live.close()
    assert manifest.captured_origin is EvidenceOrigin.PHYSICAL

    replay = RecordedCameraBackend(clip)
    replay.capture()
    assert replay.manifest.captured_origin is EvidenceOrigin.PHYSICAL
    assert replay.last_buffers.origin is EvidenceOrigin.REPLAY


def test_a_clip_may_not_be_told_to_call_itself_physical():
    with pytest.raises(TypeError, match="may not choose its own origin"):
        RecordedCameraBackend(CLIP, origin=EvidenceOrigin.PHYSICAL)


def test_capture_buffers_refuse_a_string_that_merely_spells_an_origin():
    with pytest.raises(TypeError, match="declared, never spelled"):
        PhysicalCaptureBuffers(
            color_rgb8=np.zeros((2, 2, 3), dtype=np.uint8),
            depth_m_f32=None,
            origin="physical",  # type: ignore[arg-type]
            origin_label="liar",
            capture_monotonic_ns=1,
            capture_wall_ns=1,
            sequence=0,
        )


def test_capture_buffers_refuse_the_fail_closed_unknown_origin():
    with pytest.raises(ValueError, match="never authority"):
        PhysicalCaptureBuffers(
            color_rgb8=np.zeros((2, 2, 3), dtype=np.uint8),
            depth_m_f32=None,
            origin=EvidenceOrigin.UNKNOWN,
            origin_label="unattributed",
            capture_monotonic_ns=1,
            capture_wall_ns=1,
            sequence=0,
        )


def test_a_backend_that_declares_no_origin_cannot_be_constructed():
    """SEEDED RED #1's target: the construction-time origin guard."""

    class Forgetful(PhysicalCameraBackendBase):
        kind = "forgetful"

        def _read_frame(self):  # pragma: no cover - never reached
            return np.zeros((4, 4, 3), dtype=np.uint8), None

    spec = spec_from_config(None, width_px=4, height_px=4, has_depth=False)
    with pytest.raises(TypeError, match="must declare a real EvidenceOrigin"):
        Forgetful(spec=spec, origin_label="nowhere")


# ------------------------------------------------------------- the clock ----
@pytest.mark.parametrize(
    "factory",
    [uvc, realsense, lambda **k: RecordedCameraBackend(CLIP, **k)],
    ids=["uvc", "realsense", "recorded"],
)
def test_capture_stamps_strictly_increase_over_a_hundred_frames(factory):
    backend = factory()
    stamps = []
    walls = []
    with backend:
        for _ in range(100):
            backend.capture()
            stamps.append(backend.last_buffers.capture_monotonic_ns)
            walls.append(backend.last_buffers.capture_wall_ns)
    assert all(b > a for a, b in itertools.pairwise(stamps))
    assert all(b >= a for a, b in itertools.pairwise(walls))
    assert len(set(stamps)) == 100


def test_a_repeated_capture_stamp_is_refused_not_warned():
    """SEEDED RED #2's target. A frozen clock is the sharpest form of the bug."""

    frozen = 4_242_424_242
    backend = RecordedCameraBackend(CLIP, clock=lambda: frozen)
    backend.capture()
    with pytest.raises(ValueError, match="must strictly increase"):
        backend.capture()


def test_a_regressing_clock_is_refused():
    ticks = iter([1_000, 900])
    backend = RecordedCameraBackend(CLIP, clock=lambda: next(ticks))
    backend.capture()
    with pytest.raises(ValueError, match="must strictly increase"):
        backend.capture()


def test_a_failed_read_does_not_consume_the_stamp():
    """A dropped frame must not make the NEXT good frame look non-monotonic."""

    cap = FakeCap(fail_after=1)
    backend = uvc(cap=cap)
    backend.capture()
    first = backend.last_buffers.capture_monotonic_ns
    with pytest.raises(UvcCameraUnavailable):
        backend.capture()
    cap.fail_after = None
    backend.capture()
    assert backend.last_buffers.capture_monotonic_ns > first
    assert backend.read_failures == 1


# ------------------------------------------------------- the envelope -------
@pytest.mark.parametrize(
    "factory",
    [uvc, realsense, lambda **k: RecordedCameraBackend(CLIP, **k)],
    ids=["uvc", "realsense", "recorded"],
)
def test_every_backend_satisfies_the_camera_backend_protocol(factory):
    assert isinstance(factory(), CameraBackend)


@pytest.mark.parametrize(
    "factory",
    [uvc, realsense, lambda **k: RecordedCameraBackend(CLIP, **k)],
    ids=["uvc", "realsense", "recorded"],
)
def test_the_envelope_describes_the_raster_that_arrived(factory):
    backend = factory()
    envelope = backend.capture(source_timestamp_ns=1234, sequence=7)
    buffers = backend.last_buffers
    intr = backend.spec.intrinsics
    assert (envelope.color.width_px, envelope.color.height_px) == (
        intr.width_px,
        intr.height_px,
    )
    assert buffers.color_rgb8.shape[:2] == (envelope.color.height_px, envelope.color.width_px)
    # No physical venue produces a segmentation buffer.
    assert envelope.segmentation is None
    assert envelope.sequence == 7


def test_a_frame_whose_raster_contradicts_the_spec_is_refused():
    class WrongSize(PhysicalCameraBackendBase):
        origin = EvidenceOrigin.PHYSICAL
        kind = "wrong"

        def _read_frame(self):
            return np.zeros((7, 9, 3), dtype=np.uint8), None

    spec = spec_from_config(None, width_px=64, height_px=48, has_depth=False)
    backend = WrongSize(spec=spec, origin_label="wrong")
    with pytest.raises(ValueError, match="intrinsics and raster"):
        backend.capture()


def test_unaligned_depth_is_refused_at_the_realsense_boundary():
    session = FakeRealSenseSession()
    session.misaligned = True
    backend = realsense(session=session)
    with pytest.raises(RealSenseUnavailable, match="not aligned to color"):
        backend.capture()


# ------------------------------------------------------------ calibration ---
def test_an_uncalibrated_webcam_cannot_claim_the_nominal_d455_calibration():
    backend = uvc()
    cal = backend.spec.intrinsics.calibration_id
    assert cal != CALIBRATION_ID_NOMINAL
    assert cal.startswith("uvc-uncalibrated-hfov")
    with pytest.raises(ValueError, match="d455-intrinsics-nominal"):
        assert_nominal_d455_contract(backend.spec)


def test_a_config_may_not_stamp_the_nominal_calibration_id_either():
    with pytest.raises(ValueError, match="refusing to stamp the nominal"):
        intrinsics_from_config(
            {"fx": 500.0, "calibration_id": CALIBRATION_ID_NOMINAL},
            width_px=64,
            height_px=48,
        )


def test_the_uncalibrated_guess_reproduces_the_stated_field_of_view():
    intr = uncalibrated_intrinsics(1280, 720, hfov_deg=90.0)
    assert math.degrees(intr.horizontal_fov_rad()) == pytest.approx(90.0)
    assert intr.calibration_id == "uvc-uncalibrated-hfov90"


def test_a_negotiated_resolution_moves_the_intrinsics_and_says_so():
    cap = FakeCap(width=1280, height=720, negotiated=(640, 480))
    backend = UvcCameraBackend(
        0,
        width_px=1280,
        height_px=720,
        capture_factory=lambda _d: cap,
        intrinsics={"fx": 644.0, "fy": 644.0, "cx": 640.0, "cy": 360.0,
                    "calibration_id": "bench-cal"},
    )
    backend.open()
    intr = backend.spec.intrinsics
    assert (intr.width_px, intr.height_px) == (640, 480)
    assert intr.fx == pytest.approx(644.0 * 640 / 1280)
    assert intr.cx == pytest.approx(320.0)
    assert intr.calibration_id == "bench-cal-scaled"
    backend.capture()  # the envelope validates against the rescaled spec


def test_scaling_is_a_no_op_at_the_same_resolution():
    intr = uncalibrated_intrinsics(640, 480)
    assert scale_intrinsics(intr, width_px=640, height_px=480) is intr


def test_a_realsense_adopts_the_device_calibration_and_names_the_serial():
    backend = realsense(session=FakeRealSenseSession(serial="D455XYZ"))
    backend.open()
    assert backend.spec.intrinsics.calibration_id == "d455-device-D455XYZ"
    assert backend.spec.intrinsics.fx == pytest.approx(97.5)
    assert backend.origin_label == "realsense:D455XYZ"


def test_a_configured_calibration_beats_the_device_one():
    backend = realsense(
        session=FakeRealSenseSession(serial="D455XYZ"),
        intrinsics={"fx": 500.0, "fy": 500.0, "cx": 64.0, "cy": 48.0,
                    "calibration_id": "commissioned-2026-08"},
    )
    backend.open()
    assert backend.spec.intrinsics.calibration_id == "commissioned-2026-08"
    assert backend.spec.intrinsics.fx == pytest.approx(500.0)


# ------------------------------------------------------------- depth --------
def test_a_webcam_reports_no_depth_and_produces_none():
    backend = uvc()
    assert backend.has_depth is False
    backend.capture()
    assert backend.last_buffers.depth_m_f32 is None


def test_a_realsense_produces_metric_depth():
    backend = realsense()
    assert backend.has_depth is True
    backend.capture()
    depth = backend.last_buffers.depth_m_f32
    assert depth is not None
    assert depth.dtype == np.float32
    assert float(depth.mean()) == pytest.approx(2.25)


def test_the_recorded_clip_carries_the_depth_its_manifest_promises():
    backend = RecordedCameraBackend(CLIP)
    assert backend.has_depth is True
    backend.capture()
    depth = backend.last_buffers.depth_m_f32
    assert depth is not None
    assert 0.4 <= float(depth.min()) <= float(depth.max()) <= 6.0


# ------------------------------------------------------- replay behaviour ---
def test_the_clip_loops_by_default_and_repeats_its_pixels():
    backend = RecordedCameraBackend(CLIP)
    first = []
    for _ in range(backend.frames):
        backend.capture()
        first.append(np.array(backend.last_buffers.color_rgb8, copy=True))
    backend.capture()
    assert np.array_equal(backend.last_buffers.color_rgb8, first[0])


def test_a_non_looping_clip_says_it_is_spent_rather_than_repeating():
    backend = RecordedCameraBackend(CLIP, loop=False)
    for _ in range(backend.frames):
        backend.capture()
    with pytest.raises(ClipExhausted, match="spent"):
        backend.capture()


def test_the_clip_walks_forward_frame_by_frame():
    backend = RecordedCameraBackend(CLIP)
    seen = []
    for _ in range(backend.frames):
        backend.capture()
        seen.append(np.array(backend.last_buffers.color_rgb8, copy=True))
    for a, b in itertools.pairwise(seen):
        assert not np.array_equal(a, b), "the fixture must actually move"


# ------------------------------------------------------------ the switch ----
def test_the_switch_accepts_exactly_the_three_documented_kinds():
    assert PHYSICAL_BACKEND_KINDS == ("uvc", "realsense", "recorded")
    for kind in PHYSICAL_BACKEND_KINDS:
        assert resolve_backend_kind(kind) == kind


@pytest.mark.parametrize("value", ["", "none", "off", None])
def test_no_selection_means_no_physical_camera(value, monkeypatch):
    monkeypatch.delenv(CAMERA_BACKEND_ENV, raising=False)
    assert resolve_backend_kind(value) is None


def test_an_unknown_kind_is_refused_by_name():
    with pytest.raises(ValueError, match="unknown camera backend 'webcam'"):
        resolve_backend_kind("webcam")


def test_the_env_var_selects_when_no_argument_is_given(monkeypatch):
    monkeypatch.setenv(CAMERA_BACKEND_ENV, "RealSense")
    assert resolve_backend_kind() == "realsense"


def test_open_physical_backend_builds_the_recorded_venue(monkeypatch):
    monkeypatch.setenv(CAMERA_BACKEND_ENV, "recorded")
    backend, kind = open_physical_backend(config={"clip": str(CLIP)})
    assert kind == "recorded"
    assert isinstance(backend, RecordedCameraBackend)
    backend.capture()
    assert backend.last_buffers.origin is EvidenceOrigin.REPLAY


def test_open_physical_backend_refuses_when_nothing_is_selected(monkeypatch):
    monkeypatch.delenv(CAMERA_BACKEND_ENV, raising=False)
    with pytest.raises(ValueError, match="no camera backend selected"):
        open_physical_backend()


# ------------------------------------------------------------- config -------
def test_a_missing_config_file_is_empty_but_a_named_missing_one_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("PARCEL_CAMERA_CONFIG", raising=False)
    assert load_camera_config() == {}
    with pytest.raises(FileNotFoundError):
        load_camera_config(tmp_path / "absent.json")


def test_a_json_and_a_yaml_config_load_identically(tmp_path):
    import json

    import yaml

    payload = {"kind": "uvc", "fps": 15, "mount": {"height_m": 0.4}}
    (tmp_path / "c.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "c.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert load_camera_config(tmp_path / "c.json") == load_camera_config(tmp_path / "c.yaml")


def test_an_unknown_config_key_is_refused_rather_than_ignored():
    with pytest.raises(ValueError, match="unknown intrinsics keys"):
        intrinsics_from_config({"fx": 1.0, "focal": 2.0}, width_px=8, height_px=8)
    with pytest.raises(ValueError, match="unknown mount keys"):
        mount_from_config({"heigth_m": 0.35})
    with pytest.raises(ValueError, match="unknown depth keys"):
        spec_from_config({"depth": {"minimum_m": 0.4}}, width_px=8, height_px=8, has_depth=True)


def test_pitch_may_be_given_in_degrees_or_radians_but_not_both():
    assert mount_from_config({"pitch_up_deg": 12.0}).pitch_up_rad == pytest.approx(
        math.radians(12.0)
    )
    assert mount_from_config({"pitch_up_rad": 0.5}).pitch_up_rad == pytest.approx(0.5)
    with pytest.raises(ValueError, match="not both"):
        mount_from_config({"pitch_up_deg": 12.0, "pitch_up_rad": 0.2})


# ---------------------------------------------------- device unavailability -
def test_a_device_that_will_not_open_says_so_as_a_typed_failure():
    class Closed(FakeCap):
        def isOpened(self):
            return False

    cap = Closed()
    backend = UvcCameraBackend(0, capture_factory=lambda _d: cap)
    with pytest.raises(UvcCameraUnavailable, match="cannot open UVC device"):
        backend.open()
    assert cap.released


def test_a_device_that_keeps_dropping_frames_is_declared_gone():
    cap = FakeCap(fail_after=0)
    backend = uvc(cap=cap)
    for _ in range(MAX_CONSECUTIVE_READ_FAILURES - 1):
        with pytest.raises(UvcCameraUnavailable):
            backend.capture()
    with pytest.raises(UvcCameraUnavailable, match="treat it as gone"):
        backend.capture()


def test_every_typed_camera_failure_is_a_physical_camera_unavailable():
    assert issubclass(UvcCameraUnavailable, PhysicalCameraUnavailable)
    assert issubclass(RealSenseUnavailable, PhysicalCameraUnavailable)
    assert issubclass(ClipExhausted, PhysicalCameraUnavailable)


def test_closing_a_backend_releases_the_device():
    cap = FakeCap()
    session = FakeRealSenseSession()
    with uvc(cap=cap):
        pass
    with realsense(session=session):
        pass
    assert cap.released
    assert session.stopped


# --------------------------------------------------------------- health -----
@pytest.mark.parametrize(
    "factory",
    [uvc, realsense, lambda **k: RecordedCameraBackend(CLIP, **k)],
    ids=["uvc", "realsense", "recorded"],
)
def test_health_names_the_venue_and_says_what_it_does_not_prove(factory):
    backend = factory()
    backend.capture()
    report = backend.health()
    assert report["origin"] == backend.origin.value
    assert report["captures"] == 1
    assert report["origin_label"]
    assert any("does not prove" in line.lower() or "never" in line.lower()
               for line in report["does_not_prove"])


def test_writing_a_clip_refuses_a_bare_origin_string(tmp_path):
    with pytest.raises(TypeError, match="must be an EvidenceOrigin member"):
        write_clip(
            tmp_path / "x.npz",
            np.zeros((1, 4, 4, 3), dtype=np.uint8),
            clip_id="x",
            captured_origin="physical",  # type: ignore[arg-type]
            captured_label="x",
        )
