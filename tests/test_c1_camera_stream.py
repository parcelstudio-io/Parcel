"""Card C-1 — attach the eye: the camera OBSERVATION stream inside the runtime.

B4 (``tests/test_runtime_activation.py``) pins the other camera switch: the one
that re-points navigation grounding at pixels. This file pins C-1's, which is a
different thing on purpose — an observation stream that proposes nothing, is
bounded, counts what it loses, says how old its pixels are, and is absent from
the wire entirely until an operator asks for it.

The properties worth stating, because each is a way the feature could look
installed while being useless or dishonest:

* **Absent means absent.** Flag off ⇒ no ``camera_ingress`` key, no producer
  constructed, no import of numpy/mujoco/onnxruntime, and a snapshot
  byte-identical between "block missing" and "explicitly false".
* **Loss is counted.** A full queue evicts the OLDEST and counts both the frame
  and the detections that went with it. A frame that exceeds the per-frame
  retention cap truncates and counts that separately. "The queue was full" and
  "the camera saw nothing" must never render the same.
* **Freshness is measured from the pixels.** Age runs from capture START, not
  from when the answer arrived — the one arithmetic choice that decides whether
  a half-second-old detection reports itself as current.
* **An empty observation is an observation.** Looking and finding nothing
  advances liveness without inventing a detection age.
* **Safety never queues behind a frame.** The control loop writes a pose slot
  under one leaf lock and calls no producer method; the worker pulls.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.camera_channel.ingress import (
    DEFAULT_DETECTION_TTL_NS,
    CameraDetectionFrame,
    CameraDetectionRecord,
    CameraIngress,
)
from parcel_robot.perception.contention import (
    PerceptionContentionGuard,
)
from parcel_robot.runtime import (
    EVIDENCE_KIND_CAMERA_FRAME,
    CameraStreamConfig,
    RobotRuntime,
)

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# fixtures
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


def _observation(*, timestamp: float | None = None) -> SimObservation:
    return SimObservation(
        timestamp=time.monotonic() if timestamp is None else timestamp,
        robot=RobotPose(x=1.0, y=-2.0, yaw=0.5),
        owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0),
        backend="fake",
    )


def _config(tmp_path: Path, *, perception: str = "") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "robot.yaml"
    block = perception or "  spatial_sensors: [camera, lidar]\n"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
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
{block}""",
        encoding="utf-8",
    )
    return path


ON_BLOCK = """  spatial_sensors: [camera, lidar]
  camera_ingress: true
  camera_ingress_rate_hz: 2.0
  camera_ingress_queue_capacity: 4
  camera_ingress_max_detections_per_frame: 2
  camera_ingress_queries: [person, lamppost]
"""

OFF_EXPLICIT_BLOCK = """  spatial_sensors: [camera, lidar]
  camera_ingress: false
"""


def _runtime(config: Path) -> RobotRuntime:
    return RobotRuntime(config, _Backend(_observation()), audio_status=_audio())


def _record(label: str = "lamppost", score: float = 0.5) -> CameraDetectionRecord:
    return CameraDetectionRecord(
        label=label,
        score=score,
        box=(10.0, 20.0, 60.0, 90.0),
        world_x=4.0,
        world_y=0.5,
        world_z=0.4,
        range_m=3.2,
        bearing_rad=0.05,
        depth_m=3.1,
        sigma_range_m=0.04,
        inlier_pixels=340,
    )


def _frame(
    *,
    sequence: int = 1,
    detections: tuple[CameraDetectionRecord, ...] = (),
    started_ns: int | None = None,
    publish_delay_ns: int = 1_000_000,
    render_ns: int = 1,
    truncated: int = 0,
    rejected: int = 0,
) -> CameraDetectionFrame:
    start = time.monotonic_ns() if started_ns is None else started_ns
    localized = len(detections) + truncated
    return CameraDetectionFrame(
        frame_id=f"cam-{sequence}",
        sequence=sequence,
        source_timestamp_ns=1234 + sequence,
        capture_started_monotonic_ns=start,
        capture_completed_monotonic_ns=start + render_ns,
        published_monotonic_ns=start + publish_delay_ns,
        published_wall_s=time.time(),
        detection_ttl_ns=DEFAULT_DETECTION_TTL_NS,
        width_px=1280,
        height_px=720,
        robot_x=1.0,
        robot_y=-2.0,
        robot_yaw_rad=0.5,
        queries=("person", "lamppost"),
        detections=detections,
        raw_detections=localized + rejected,
        localized_detections=localized,
        rejected_detections=rejected,
        truncated_detections=truncated,
        render_ms=26.0,
        detect_ms=515.0,
        total_ms=541.0,
        detector_name="owlv2-b16",
        provider_profile="cpu_int8",
        active_providers=("CPUExecutionProvider",),
    )


# ---------------------------------------------------------------------------
# 1. config contract — fail closed
# ---------------------------------------------------------------------------


def test_absent_block_and_explicit_false_are_both_off_and_identical() -> None:
    assert CameraStreamConfig.from_section({}) is None
    assert CameraStreamConfig.from_section({"spatial_sensors": ["camera"]}) is None
    explicit = CameraStreamConfig.from_section({"camera_ingress": False})
    assert explicit is not None and explicit.enabled is False


@pytest.mark.parametrize(
    "section",
    [
        {"camera_ingress": 1},  # bool-as-number
        {"camera_ingress": "true"},
        {"camera_ingress": True, "camera_ingress_rate_hz": 0.0},
        {"camera_ingress": True, "camera_ingress_rate_hz": -1.0},
        {"camera_ingress": True, "camera_ingress_rate_hz": 10.5},
        {"camera_ingress": True, "camera_ingress_rate_hz": float("nan")},
        {"camera_ingress": True, "camera_ingress_rate_hz": float("inf")},
        {"camera_ingress": True, "camera_ingress_queue_capacity": 0},
        {"camera_ingress": True, "camera_ingress_queue_capacity": 4097},
        {"camera_ingress": True, "camera_ingress_queue_capacity": True},
        {"camera_ingress": True, "camera_ingress_max_detections_per_frame": 0},
        {"camera_ingress": True, "camera_ingress_max_detections_per_frame": 999},
        {"camera_ingress": True, "camera_ingress_queries": []},
        {"camera_ingress": True, "camera_ingress_queries": "person"},
        {"camera_ingress": True, "camera_ingress_queries": [1]},
        {"camera_ingress": True, "camera_ingress_queries": ["x" * 65, "person"]},
        {"camera_ingress_unknown_key": True},
        {"camera_ingress": True, "camera_ingress_rate": 2.0},  # plausible typo
    ],
)
def test_the_config_refuses_rather_than_defaults(section: dict) -> None:
    """A typo that silently kept a default is an operator lied to by their config."""

    with pytest.raises((TypeError, ValueError)):
        CameraStreamConfig.from_section(section)


def test_queries_must_name_person_so_the_pg1_lease_is_real() -> None:
    with pytest.raises(ValueError, match="person"):
        CameraStreamConfig.from_section(
            {"camera_ingress": True, "camera_ingress_queries": ["lamppost", "bench"]}
        )
    # substring is not the whole word: "personnel carrier" must not qualify
    with pytest.raises(ValueError, match="person"):
        CameraStreamConfig.from_section(
            {"camera_ingress": True, "camera_ingress_queries": ["personnel carrier"]}
        )
    ok = CameraStreamConfig.from_section(
        {"camera_ingress": True, "camera_ingress_queries": ["a person", "lamppost"]}
    )
    assert ok is not None and ok.queries == ("a person", "lamppost")


def test_queries_are_normalized_and_deduplicated() -> None:
    config = CameraStreamConfig.from_section(
        {
            "camera_ingress": True,
            "camera_ingress_queries": ["  PERSON  ", "person", "Lamp   Post"],
        }
    )
    assert config is not None
    assert config.queries == ("person", "lamp post")


# ---------------------------------------------------------------------------
# 2. flag-off is byte-identical (the R1 discipline)
# ---------------------------------------------------------------------------


def test_flag_off_snapshot_has_no_camera_key_and_is_byte_identical(
    tmp_path: Path,
) -> None:
    """The R1 discipline, stated as bytes.

    Both arms use the SAME config PATH — written, read, then rewritten — so the
    only difference between them is the presence of ``camera_ingress: false``.
    Comparing two different tmp files would have compared their filenames,
    which appear in the snapshot, and would have proved nothing.
    """

    path = _config(tmp_path / "same", perception="")
    absent = _runtime(path)
    try:
        first = absent.snapshot()
    finally:
        absent.close()

    _config(tmp_path / "same", perception=OFF_EXPLICIT_BLOCK)
    explicit = _runtime(path)
    try:
        second = explicit.snapshot()
        assert explicit.camera_stream_snapshot() is None
    finally:
        explicit.close()

    assert "camera_ingress" not in first
    assert "camera_ingress" not in second
    # Same keys, same order — a new key would show up here even if its value
    # happened to serialize identically.
    assert list(first) == list(second)
    # No camera field leaks in ANYWHERE, at any depth, with the flag off.
    assert not _keys_matching(first, "camera_ingress")
    assert not _keys_matching(second, "camera_ingress")
    # And the whole serialized wire matches once per-instance ids and clocks —
    # volatile BY DEFINITION, and volatile between any two constructions
    # regardless of C-1 — are normalized. Everything else must be equal.
    assert json.dumps(_normalize(first), sort_keys=True) == json.dumps(
        _normalize(second), sort_keys=True
    )


def _normalize(value: object) -> object:
    """Replace per-instance ids and clocks; keep every other value verbatim."""

    volatile_suffixes = ("_id", "_at", "_at_s", "_ts", "timestamp", "_seconds", "_uptime_s")
    volatile_names = {"started_at", "closed_at", "session", "uptime_s", "elapsed_s"}
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            if key.endswith(volatile_suffixes) or key in volatile_names:
                out[key] = "<volatile>"
            else:
                out[key] = _normalize(item)
        return out
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, str):
        # Per-instance hex session ids, wherever they are embedded (they show
        # up inside log PATHS as well as in id fields).
        return re.sub(r"\b[0-9a-f]{12,}\b", "<volatile>", value)
    return value


def _keys_matching(value: object, needle: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if needle in key:
                found.append(key)
            found.extend(_keys_matching(item, needle))
    elif isinstance(value, list):
        for item in value:
            found.extend(_keys_matching(item, needle))
    return found


def test_flag_off_never_constructs_a_producer_or_a_guard(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=OFF_EXPLICIT_BLOCK))
    try:
        # The composition root is a no-op; nothing renders, nothing loads.
        runtime._attach_configured_camera_ingress()
        assert runtime._camera_ingress is None
        assert runtime.perception_contention is None
        assert runtime._camera_stream_enabled is False
    finally:
        runtime.close()


def test_flag_off_pose_mailbox_is_inert(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=OFF_EXPLICIT_BLOCK))
    try:
        runtime._offer_camera_pose(_observation())
        assert runtime._camera_pose_slot is None
        assert runtime._camera_poses_offered == 0
    finally:
        runtime.close()


def test_c1_and_the_legacy_b4_flag_are_one_switch_now(tmp_path: Path) -> None:
    """Card P0-A retired this refusal; the two spellings now resolve together.

    Until 2026-08-22 this construction raised: `perception.camera_ingress` (the
    C-1 observation stream) and `camera_ingress.enabled` / PARCEL_CAMERA_INGRESS
    (the B4 grounding authority) refused each other, on the reasoning that an
    operator should not have to answer "which camera switch is authoritative"
    from a snapshot. The prototype answer is that it is one question: the camera
    is on. `_camera_ingress_enabled` resolves all three spellings in precedence
    order, and C-1's own guarantees are unchanged — the stream still runs only
    when THIS block is present and true, because it reads its rate, queue and
    query batch from nowhere else.
    """

    path = tmp_path / "robot.yaml"
    base = _config(tmp_path, perception=ON_BLOCK).read_text(encoding="utf-8")
    path.write_text(base + "\ncamera_ingress:\n  enabled: true\n", encoding="utf-8")
    runtime = _runtime(path)
    try:
        assert runtime._camera_stream_enabled is True
        assert runtime._camera_ingress_enabled() is True
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# 3. the frame contract
# ---------------------------------------------------------------------------


def test_frame_serialization_is_a_stable_fixed_point() -> None:
    """The property EV-1 replay actually needs.

    ``as_dict`` rounds for a compact JSONL row, so encode→decode is NOT the
    identity on raw floats and claiming it would be false. What must hold — and
    what a replay tool depends on — is that the ROW is a fixed point: decoding
    it and re-encoding yields byte-equal JSON, so a stored row round-trips
    forever without drifting.
    """

    frame = _frame(detections=(_record(),))
    first = frame.as_dict()
    again = CameraDetectionFrame.from_mapping(first).as_dict()
    assert json.dumps(again, sort_keys=True) == json.dumps(first, sort_keys=True)
    # And the fields an auditor reasons about survive exactly.
    decoded = CameraDetectionFrame.from_mapping(first)
    assert decoded.sequence == frame.sequence
    assert decoded.queries == frame.queries
    assert decoded.detections[0].label == frame.detections[0].label
    assert decoded.expired_at_publish == frame.expired_at_publish


def test_frame_freshness_is_measured_from_capture_start() -> None:
    """The one arithmetic choice that decides whether the indicator can lie.

    This test previously used a fixture whose capture COMPLETED 1 ns after it
    STARTED, which made the two candidate clocks numerically indistinguishable
    — so it asserted the property without being able to detect its violation,
    and the seeded-defect harness caught it staying green under seed #3. The
    frame below has a render window wide enough that the choice of clock
    changes the verdict, which is the only way this test means anything.
    """

    fresh = _frame(publish_delay_ns=10_000_000)  # 10 ms
    assert fresh.expired_at_publish is False

    # Render took 250 ms; the answer landed 400 ms after the shutter.
    #   from capture START      → 400 ms > 300 ms TTL ⇒ EXPIRED (correct)
    #   from capture COMPLETION → 150 ms < 300 ms TTL ⇒ "fresh" (the lie)
    slow_render = _frame(render_ns=250_000_000, publish_delay_ns=400_000_000)
    assert slow_render.publish_latency_ns == 400_000_000
    assert slow_render.expired_at_publish is True, (
        "freshness is being measured from when the ANSWER appeared, not from "
        "when the pixels were true"
    )
    # And the mis-measurement it must not be equal to:
    from_completion = (
        slow_render.published_monotonic_ns
        - slow_render.capture_completed_monotonic_ns
    )
    assert from_completion < slow_render.detection_ttl_ns
    assert slow_render.publish_latency_ns != from_completion


@pytest.mark.parametrize(
    "kwargs",
    [
        {"score": 1.5},
        {"score": -0.1},
        {"score": float("nan")},
        {"range_m": -1.0},
        {"inlier_pixels": -1},
        {"label": ""},
        {"label": "x" * 65},
        {"world_x": float("inf")},
    ],
)
def test_detection_records_refuse_impossible_values(kwargs: dict) -> None:
    base = {
        "label": "lamppost",
        "score": 0.5,
        "box": (1.0, 2.0, 3.0, 4.0),
        "world_x": 1.0,
        "world_y": 1.0,
        "world_z": 1.0,
        "range_m": 1.0,
        "bearing_rad": 0.0,
        "depth_m": 1.0,
        "sigma_range_m": 0.1,
        "inlier_pixels": 5,
    }
    base.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        CameraDetectionRecord(**base)


def test_a_frame_that_loses_rows_without_counting_them_is_refused() -> None:
    """retained + truncated == localized, or it is not evidence."""

    with pytest.raises(ValueError, match="truncated"):
        CameraDetectionFrame(
            frame_id="cam-1",
            sequence=1,
            source_timestamp_ns=1,
            capture_started_monotonic_ns=10,
            capture_completed_monotonic_ns=11,
            published_monotonic_ns=12,
            published_wall_s=1.0,
            detection_ttl_ns=DEFAULT_DETECTION_TTL_NS,
            width_px=64,
            height_px=64,
            robot_x=0.0,
            robot_y=0.0,
            robot_yaw_rad=0.0,
            queries=("person",),
            detections=(),
            raw_detections=5,
            localized_detections=5,
            rejected_detections=0,
            truncated_detections=0,  # lies: 5 localized, 0 retained, 0 truncated
            render_ms=1.0,
            detect_ms=1.0,
            total_ms=2.0,
            detector_name="d",
            provider_profile="cpu_int8",
            active_providers=(),
        )


def test_a_frame_cannot_publish_before_it_was_captured() -> None:
    with pytest.raises(ValueError, match="publish before"):
        _frame(publish_delay_ns=-5)


def test_from_mapping_is_exact_key(tmp_path: Path) -> None:
    payload = _frame().as_dict()
    payload["surprise"] = 1
    with pytest.raises(ValueError, match="unknown frame keys"):
        CameraDetectionFrame.from_mapping(payload)
    del payload["surprise"]
    del payload["queries"]
    with pytest.raises(ValueError, match="missing frame keys"):
        CameraDetectionFrame.from_mapping(payload)


# ---------------------------------------------------------------------------
# 4. the bounded stream
# ---------------------------------------------------------------------------


def test_queue_keeps_newest_and_counts_every_lost_frame_and_detection(
    tmp_path: Path,
) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        assert runtime._camera_frames.maxlen == 4
        for i in range(1, 8):  # 7 frames into a queue of 4
            runtime._publish_camera_frame(_frame(sequence=i, detections=(_record(),)))
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["queue_depth"] == 4
        assert snap["frames_published"] == 7
        assert snap["frames_dropped"] == 3
        # each evicted frame carried exactly one detection
        assert snap["detections_dropped_with_frames"] == 3
        # keep-NEWEST: the survivors are the last four
        kept = [f.sequence for f in runtime.camera_detection_frame_slice(16)]
        assert kept == [4, 5, 6, 7]
    finally:
        runtime.close()


def test_empty_observations_are_real_observations(tmp_path: Path) -> None:
    """Looking and seeing nothing must advance liveness, not invent a detection."""

    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        runtime._publish_camera_frame(_frame(sequence=1, detections=()))
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["frames_published"] == 1
        assert snap["latest_class_counts"] == {}
        assert snap["frame_age_s"] is not None
        # No detection has ever arrived, so there is no detection age to report.
        assert snap["last_detection_age_s"] is None
    finally:
        runtime.close()


def test_detection_age_tracks_the_last_frame_that_actually_saw_something(
    tmp_path: Path,
) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        runtime._publish_camera_frame(_frame(sequence=1, detections=(_record(),)))
        runtime._publish_camera_frame(_frame(sequence=2, detections=()))
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["latest_class_counts"] == {}  # newest frame found nothing
        assert snap["last_detection_age_s"] is not None  # but one did, earlier
    finally:
        runtime.close()


def test_snapshot_reports_stale_when_the_newest_frame_is_past_ttl(
    tmp_path: Path,
) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        old = time.monotonic_ns() - 900_000_000  # captured 0.9 s ago
        runtime._publish_camera_frame(
            _frame(sequence=1, detections=(_record(),), started_ns=old)
        )
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["state"] == "stale"
        assert snap["fresh"] is False
        # Two DIFFERENT facts, and the snapshot keeps them apart: this frame
        # was fresh when it landed (1 ms after capture) and has merely aged
        # since. A frame that was already expired on arrival is the other
        # failure and gets its own flag.
        assert snap["newest_expired_at_publish"] is False
        assert snap["frame_age_s"] > 0.8

        runtime._publish_camera_frame(
            _frame(sequence=2, detections=(_record(),), publish_delay_ns=520_000_000)
        )
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["newest_expired_at_publish"] is True
    finally:
        runtime.close()


def test_snapshot_reports_fresh_for_a_just_captured_frame(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        runtime._publish_camera_frame(_frame(sequence=1, detections=(_record(),)))
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["state"] == "fresh"
        assert snap["fresh"] is True
    finally:
        runtime.close()


def test_starting_state_before_any_frame(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["state"] == "starting"
        assert snap["frame_age_s"] is None
    finally:
        runtime.close()


def test_a_non_frame_payload_is_refused_and_faults_the_stream(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        runtime._publish_camera_frame({"label": "not a frame"})  # type: ignore[arg-type]
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["state"] == "fault"
        assert snap["frames_published"] == 0
        assert snap["stream_errors"] == 1
    finally:
        runtime.close()


def test_drain_is_destructive_and_slice_is_not(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        for i in range(1, 4):
            runtime._publish_camera_frame(_frame(sequence=i))
        assert [f.sequence for f in runtime.camera_detection_frame_slice(16)] == [1, 2, 3]
        assert [f.sequence for f in runtime.camera_detection_frame_slice(16)] == [1, 2, 3]
        drained = runtime.drain_camera_detection_frames(2)
        assert [f.sequence for f in drained] == [1, 2]  # oldest first
        assert [f.sequence for f in runtime.camera_detection_frame_slice(16)] == [3]
        assert runtime.drain_camera_detection_frames(0) == ()
    finally:
        runtime.close()


def test_achieved_rate_is_reported_not_assumed(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["config"]["rate_hz"] == 2.0  # what was ASKED for
        assert snap["achieved_rate_hz"] is None  # nothing measured yet
        runtime._publish_camera_frame(_frame(sequence=1))
        time.sleep(0.05)
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert isinstance(snap["achieved_rate_hz"], float)
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# 5. the pose mailbox — safety never queues behind a frame
# ---------------------------------------------------------------------------


def test_one_fresh_pose_permits_exactly_one_capture(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        runtime._offer_camera_pose(_observation())
        assert runtime._take_camera_pose() == (1.0, -2.0, 0.5)
        # The slot is consumed: a second pull must NOT re-render a pose the
        # robot may already have left.
        assert runtime._take_camera_pose() is None
    finally:
        runtime.close()


def test_a_stale_pose_is_refused_rather_than_rendered(tmp_path: Path) -> None:
    """A stalled simulator must stop the camera, not feed it confident fiction."""

    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        ancient = _observation(timestamp=time.monotonic() - 30.0)
        runtime._offer_camera_pose(ancient)
        assert runtime._take_camera_pose() is None
        assert runtime._camera_poses_consumed == 0
    finally:
        runtime.close()


def test_a_non_finite_pose_never_reaches_the_mailbox(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        broken = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(x=float("nan"), y=0.0, yaw=0.0),
            owner=OwnerTrack(owner_id="o", x=0.0, y=0.0, visible=False, confidence=0.0),
            backend="fake",
        )
        runtime._offer_camera_pose(broken)
        assert runtime._camera_pose_slot is None
    finally:
        runtime.close()


def test_the_control_loop_calls_no_producer_method_for_the_camera() -> None:
    """The structural half of "safety never waits behind inference".

    ``_offer_camera_pose`` is the ONLY camera call the 10 Hz loop makes. If it
    ever reaches the producer, a slow producer is in front of the safety path.
    """

    import ast
    import inspect

    source = inspect.getsource(RobotRuntime._offer_camera_pose)
    tree = ast.parse(source.strip())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    forbidden = {"set_pose", "set_query", "poll_once", "start", "stop", "capture", "detect"}
    assert not (called & forbidden), f"control loop reaches the producer: {called & forbidden}"


def test_the_worker_pulls_and_does_not_reuse_a_missing_pose() -> None:
    ingress = CameraIngress(backend=object(), detector=object())
    poses: list[tuple[float, float, float] | None] = [(1.0, 2.0, 0.0), None]
    ingress.pose_source = lambda: poses.pop(0) if poses else None
    assert ingress._refresh_pose_from_source() is True
    assert ingress._pose is not None
    # No new pose ⇒ the previous one is CLEARED, not re-rendered.
    assert ingress._refresh_pose_from_source() is False
    assert ingress._pose is None


def test_a_raising_pose_source_is_counted_not_fatal() -> None:
    ingress = CameraIngress(backend=object(), detector=object())

    def boom() -> tuple[float, float, float] | None:
        raise RuntimeError("telemetry gone")

    ingress.pose_source = boom
    assert ingress._refresh_pose_from_source() is False
    assert ingress.stats.errors == 1
    assert "telemetry gone" in (ingress.stats.last_error or "")


# ---------------------------------------------------------------------------
# 6. PG-1 contention registration
# ---------------------------------------------------------------------------


class _FakeDetector:
    """Records whether a mission lease was held at the moment inference ran."""

    name = "fake-detector"

    def __init__(self, guard: PerceptionContentionGuard) -> None:
        self._guard = guard
        self.leases_seen: list[int] = []
        self.admissions: list[bool] = []

    def detect(self, *, rgb, depth, seg, query):
        self.leases_seen.append(len(self._guard.active_leases()))
        # The consumer half: would a generation be allowed right now?
        self.admissions.append(bool(self._guard.try_admit_generation(estimated_ms=500.0)))
        return []


def _fake_backend_pair():
    import numpy as np

    class _Buffers:
        color_rgb8 = np.zeros((8, 8, 3), dtype=np.uint8)
        depth_m_f32 = np.full((8, 8), 2.0, dtype=np.float32)

    class _Backend2:
        last_buffers = _Buffers()

        def capture(self, **kwargs):
            return None

    return _Backend2()


def _ingress_with(guard: PerceptionContentionGuard, detector) -> CameraIngress:
    from parcel_robot.camera_channel.channel import CameraChannelSpec

    spec = CameraChannelSpec.d455_go2_nominal()
    ingress = CameraIngress(
        backend=_fake_backend_pair(),
        detector=detector,
        intrinsics=spec.intrinsics,
        mount=spec.mount,
    )
    ingress.contention_guard = guard
    return ingress


def test_inference_runs_under_a_pg1_mission_lease() -> None:
    """Registration must be observable, or it is decorative."""

    guard = PerceptionContentionGuard()
    detector = _FakeDetector(guard)
    ingress = _ingress_with(guard, detector)
    ingress.set_query(["person"])
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.poll_once()
    assert detector.leases_seen == [1], "no lease was held while the detector ran"
    # ...and while it was held, a 500 ms generation was REFUSED.
    assert detector.admissions == [False]
    # The lease is released afterwards; speech is not starved.
    assert guard.active_leases() == ()
    assert ingress.stats.leased_inferences == 1


def test_without_a_guard_the_detector_still_runs() -> None:
    """Offline determinism: absent guard is the incumbent path, not a silent skip."""

    guard = PerceptionContentionGuard()
    detector = _FakeDetector(guard)
    ingress = _ingress_with(guard, detector)
    ingress.contention_guard = None
    ingress.set_query(["person"])
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.poll_once()
    assert detector.leases_seen == [0]
    assert ingress.stats.leased_inferences == 0


# ---------------------------------------------------------------------------
# 7. the publish seam
# ---------------------------------------------------------------------------


def test_a_frame_is_published_even_when_nothing_was_detected() -> None:
    guard = PerceptionContentionGuard()
    ingress = _ingress_with(guard, _FakeDetector(guard))
    frames: list[CameraDetectionFrame] = []
    ingress.on_frame = frames.append
    ingress.set_query(["person"])
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.poll_once()
    assert len(frames) == 1
    assert frames[0].detections == ()
    assert frames[0].queries == ("person",)
    assert ingress.stats.frames_published == 1


def test_a_raising_consumer_is_counted_and_does_not_kill_the_worker() -> None:
    guard = PerceptionContentionGuard()
    ingress = _ingress_with(guard, _FakeDetector(guard))

    def boom(frame: CameraDetectionFrame) -> None:
        raise RuntimeError("consumer exploded")

    ingress.on_frame = boom
    ingress.set_query(["person"])
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.poll_once()
    assert ingress.stats.frame_callback_errors == 1
    assert ingress.stats.frames_published == 0
    # the producer survives and keeps polling
    ingress.poll_once()
    assert ingress.stats.frame_callback_errors == 2


def test_the_publish_callback_is_invoked_outside_the_ingress_lock() -> None:
    """A consumer taking the runtime lock must not be inside the producer's."""

    guard = PerceptionContentionGuard()
    ingress = _ingress_with(guard, _FakeDetector(guard))
    observed: list[bool] = []

    def probe(frame: CameraDetectionFrame) -> None:
        # If the worker still held _lock, this acquire would block/fail.
        acquired = ingress._lock.acquire(blocking=False)
        observed.append(acquired)
        if acquired:
            ingress._lock.release()

    ingress.on_frame = probe
    ingress.set_query(["person"])
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.poll_once()
    assert observed == [True], "on_frame ran while the ingress lock was held"


# ---------------------------------------------------------------------------
# 8. EV-1 evidence integration
# ---------------------------------------------------------------------------


def test_frames_persist_into_ev1_as_typed_rows(tmp_path: Path) -> None:
    from parcel_robot.realtime.evidence_log import (
        STREAM_EVENT,
        SessionEventLog,
        read_event_log,
        verify_event_log,
    )

    runtime = _runtime(_config(tmp_path / "cfg", perception=ON_BLOCK))
    log = SessionEventLog(root=tmp_path / "sessions", session_id="sess-c1")
    log.start()
    runtime._session_evidence = log
    try:
        runtime._publish_camera_frame(_frame(sequence=1, detections=(_record(),)))
        runtime._publish_camera_frame(_frame(sequence=2, detections=()))
        time.sleep(0.3)
    finally:
        log.close("test done")
        runtime.close()

    rows = read_event_log(log.path)
    assert verify_event_log(rows) == [], "the evidence log is not a complete record"
    camera_rows = [r for r in rows if r.get("kind") == EVIDENCE_KIND_CAMERA_FRAME]
    assert len(camera_rows) == 2
    assert all(r["stream"] == STREAM_EVENT for r in camera_rows)
    # Strictly replay-decodable: the row IS the frame, not a lossy summary.
    for row in camera_rows:
        payload = {k: v for k, v in row.items() if k not in {"kind", "stream", "seq", "at", "wall"}}
        decoded = CameraDetectionFrame.from_mapping(payload)
        assert decoded.sequence in {1, 2}
    assert rows[-1]["kind"] == "log_closed"


def test_evidence_rows_are_counted_in_the_snapshot(tmp_path: Path) -> None:
    from parcel_robot.realtime.evidence_log import SessionEventLog

    runtime = _runtime(_config(tmp_path / "cfg", perception=ON_BLOCK))
    log = SessionEventLog(root=tmp_path / "sessions", session_id="sess-c1b")
    log.start()
    runtime._session_evidence = log
    try:
        runtime._publish_camera_frame(_frame(sequence=1))
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["evidence_rows_offered"] == 1
        assert snap["evidence_rows_refused"] == 0
    finally:
        log.close("done")
        runtime.close()


def test_no_evidence_log_is_not_an_error(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        assert runtime._session_evidence is None
        runtime._publish_camera_frame(_frame(sequence=1))
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["evidence_rows_offered"] == 0
        assert snap["frames_published"] == 1
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# 9. composition honesty + teardown ordering
# ---------------------------------------------------------------------------


def test_the_snapshot_states_what_this_camera_actually_is(tmp_path: Path) -> None:
    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        composition = snap["composition"]
        assert composition["mode"] == "static_scene_copy_pose_synced"
        assert composition["dynamic_actors_synced"] is False
        assert composition["real_camera"] is False
    finally:
        runtime.close()


def test_camera_stops_before_the_evidence_log_closes() -> None:
    """Ordering: the last in-flight frame must still reach the record."""

    import ast
    import inspect

    source = inspect.getsource(RobotRuntime.close)
    tree = ast.parse(source.strip())
    order: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            target = node.func
            if target.attr == "stop" and getattr(target.value, "attr", "") == "_camera_ingress":
                order.append("camera")
            if target.attr == "close" and getattr(target.value, "attr", "") == "_session_evidence":
                order.append("evidence")
    assert order.index("camera") < order.index("evidence"), (
        "the evidence log closes before the camera stops: the final frame is lost"
    )


def test_egl_binding_is_refused_when_mujoco_is_already_bound_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silently software-rendered camera is not a perception stream."""

    import sys
    import types

    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        monkeypatch.setitem(sys.modules, "mujoco", types.ModuleType("mujoco"))
        monkeypatch.setenv("MUJOCO_GL", "glfw")
        with pytest.raises(RuntimeError, match="MUJOCO_GL"):
            runtime._attach_configured_camera_ingress()
        assert runtime._camera_ingress is None
    finally:
        runtime.close()


def test_the_stream_never_touches_navigation_grounding(tmp_path: Path) -> None:
    """C-1 publishes observations; grounding needs an ATTACHED ingress.

    Card P0-A collapsed the camera flags, so `_camera_ingress_enabled()` now
    reads True here where it read False — the operator turned the camera on and
    there is only one switch to turn on. That is a statement about CONSENT, not
    about authority: `_semantic_candidates` grounds on pixels only through an
    ingress that was actually attached, and nothing attached one here. So the
    oracle read is untouched no matter how many frames the stream carries,
    which is the property this test was always about.
    """

    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        runtime._publish_camera_frame(_frame(sequence=1, detections=(_record(),)))
        assert runtime._camera_ingress_enabled() is True
        assert runtime._camera_ingress is None
        candidates = runtime._semantic_candidates(_observation())
        assert all(c.get("source") != "pixel_detector" for c in candidates)
    finally:
        runtime.close()


def test_concurrent_publishers_do_not_lose_the_count(tmp_path: Path) -> None:
    """The counters are the evidence; a race in them is a race in the record."""

    runtime = _runtime(_config(tmp_path, perception=ON_BLOCK))
    try:
        def publish(start: int) -> None:
            for i in range(50):
                runtime._publish_camera_frame(_frame(sequence=start + i))

        threads = [threading.Thread(target=publish, args=(n * 100,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = runtime.camera_stream_snapshot()
        assert snap is not None
        assert snap["frames_published"] == 200
        # capacity 4 ⇒ exactly 196 evicted, every one of them counted
        assert snap["frames_dropped"] == 196
        assert snap["queue_depth"] == 4
    finally:
        runtime.close()
