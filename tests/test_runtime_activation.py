"""RUNTIME-ACTIVATION wave: camera pixel-ingress (B4) + the memory write-path.

Two cards, one runtime:

* **B4 — camera on the mission path.** ``RobotRuntime._semantic_candidates`` reads
  pixel detections from an attached :class:`CameraIngress` when the flag is ON, and
  the GT-frustum oracle otherwise. These tests pin the flag gating (default OFF is
  byte-identical to the oracle), the ``pixel_detector`` source tag, and the
  ``CameraIngress`` render→detect→localize→candidate-dict wiring on a deterministic
  fake backend+detector. A guarded cell runs the real OWLv2+EGL path when present.
* **memory write-path.** Live ``_chat_item`` turns flow into ``TieredMemory``; an
  aged-out fact survives into a Tier-2 summary and ``retrieve()`` surfaces it into
  the prompt sections. Default-off leaves the composed prompt byte-identical.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import (
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SimObservation,
)
from parcel_robot.camera_channel.ingress import (
    PIXEL_SOURCE,
    CameraIngress,
    radius_m_from_box_depth,
)
from parcel_robot.detection_adapter.pixel_detections import PixelDetection
from parcel_robot.navigation.semantic_map import semantic_candidates_from_observation
from parcel_robot.runtime import RobotRuntime, _camera_query_from_directive

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# fixtures / fakes
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
    """Minimal in-process SimulatorBackend for a cold runtime construction."""

    name = "fake"

    def __init__(self, observation: SimObservation) -> None:
        self._observation = observation
        self.moves: list[object] = []

    def observe(self) -> SimObservation:
        return self._observation

    def move(self, command: object) -> None:
        self.moves.append(command)

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
        robot=RobotPose(x=1.0, y=-2.0, yaw=0.5),
        owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0),
        semantic_objects=(
            SemanticObjectTrack(
                object_id="lamp-oracle",
                label="lamppost",
                position=(4.0, 0.0, 0.5),
                confidence=0.9,
                source="oracle",
            ),
        ),
        backend="fake",
    )


def _base_config(tmp_path: Path, *, extra: str = "") -> Path:
    path = tmp_path / "robot.yaml"
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
{extra}
""",
        encoding="utf-8",
    )
    return path


def _make_runtime(config: Path) -> RobotRuntime:
    return RobotRuntime(config, _Backend(_observation()), audio_status=_audio())


class _FakeIngress:
    """Stand-in for CameraIngress: records set_pose, returns a fixed candidate."""

    def __init__(self, candidates: list[dict] | None) -> None:
        self._candidates = candidates
        self.poses: list[tuple[float, float, float]] = []
        self.queries: list[object] = []
        self.started = False
        self.stopped = False

    def set_pose(self, x: float, y: float, yaw: float) -> None:
        self.poses.append((x, y, yaw))

    def set_query(self, query: object) -> None:
        self.queries.append(query)

    def latest_candidates(self) -> list[dict] | None:
        if self._candidates is None:
            return None
        return [dict(item) for item in self._candidates]

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def _pixel_candidate() -> dict:
    return {
        "id": "pxdet-1-0",
        "label": "lamppost",
        "position": [4.1, 0.05, 0.5],
        "confidence": 0.66,
        "kind": "object",
        "source": PIXEL_SOURCE,
        "reachable": True,
        "metadata": {"detector": PIXEL_SOURCE},
    }


# ---------------------------------------------------------------------------
# B4 — directive → query extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directive,expected",
    [
        ("go to the lamppost", "lamppost"),
        ("Walk to the red bench.", "red bench"),
        ("navigate to the fire hydrant", "fire hydrant"),
        ("find the trash can", "trash can"),
        ("lamppost", "lamppost"),
    ],
)
def test_camera_query_from_directive(directive: str, expected: str) -> None:
    assert _camera_query_from_directive(directive) == expected


# ---------------------------------------------------------------------------
# B4 — runtime flag gating on the mission path
# ---------------------------------------------------------------------------


def test_semantic_candidates_default_is_oracle_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PARCEL_CAMERA_INGRESS", raising=False)
    runtime = _make_runtime(_base_config(tmp_path))
    try:
        observation = _observation()
        # No ingress attached: must be exactly the oracle read.
        assert runtime._camera_ingress is None
        assert runtime._semantic_candidates(observation) == (
            semantic_candidates_from_observation(observation)
        )
    finally:
        runtime.close()


def test_ingress_ignored_when_flag_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_INGRESS", "0")
    runtime = _make_runtime(_base_config(tmp_path))
    try:
        ingress = _FakeIngress([_pixel_candidate()])
        runtime.attach_camera_ingress(ingress, start=False)
        observation = _observation()
        result = runtime._semantic_candidates(observation)
        # Flag off ⇒ oracle, and the ingress is never consulted for a pose.
        assert result == semantic_candidates_from_observation(observation)
        assert result[0]["source"] == "oracle"
        assert ingress.poses == []
    finally:
        runtime.close()


def test_ingress_pixels_used_when_flag_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_INGRESS", "1")
    runtime = _make_runtime(_base_config(tmp_path))
    try:
        ingress = _FakeIngress([_pixel_candidate()])
        runtime.attach_camera_ingress(ingress)  # default start=True starts the worker
        observation = _observation()
        result = runtime._semantic_candidates(observation)
        assert len(result) == 1
        assert result[0]["source"] == PIXEL_SOURCE
        assert result[0]["label"] == "lamppost"
        # The 10 Hz path pushed the live robot pose to the detector.
        assert ingress.poses[-1] == (1.0, -2.0, 0.5)
        assert ingress.started is True
    finally:
        runtime.close()


def test_ingress_falls_back_to_oracle_before_first_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_INGRESS", "1")
    runtime = _make_runtime(_base_config(tmp_path))
    try:
        ingress = _FakeIngress(None)  # detector has produced nothing yet
        runtime.attach_camera_ingress(ingress, start=False)
        observation = _observation()
        result = runtime._semantic_candidates(observation)
        assert result == semantic_candidates_from_observation(observation)
    finally:
        runtime.close()


def test_config_enable_flag_without_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARCEL_CAMERA_INGRESS", raising=False)
    config = _base_config(tmp_path, extra="camera_ingress:\n  enabled: true\n")
    runtime = _make_runtime(config)
    try:
        assert runtime._camera_ingress_enabled() is True
        ingress = _FakeIngress([_pixel_candidate()])
        runtime.attach_camera_ingress(ingress, start=False)
        result = runtime._semantic_candidates(_observation())
        assert result[0]["source"] == PIXEL_SOURCE
    finally:
        runtime.close()


def test_start_navigation_sets_camera_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_INGRESS", "1")
    runtime = _make_runtime(_base_config(tmp_path))
    try:
        ingress = _FakeIngress([_pixel_candidate()])
        runtime.attach_camera_ingress(ingress, start=False)
        runtime._set_camera_query_from_directive("go to the lamppost")
        # Card P0-D: the directive lane hands the ingress a BATCH — the
        # configured ``camera_ingress_queries`` (none here, so empty) plus the
        # goal noun — instead of the bare noun that used to REPLACE the batch
        # and take the ``person`` safety lease with it. The real
        # ``CameraIngress.set_query`` pins ``person`` on top of whatever arrives;
        # this stand-in records the batch verbatim.
        assert ingress.queries == [("lamppost",)]
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# B4 — CameraIngress render→detect→localize→candidate wiring (fake backend)
# ---------------------------------------------------------------------------


class _FakeCaptureBackend:
    """A CameraBackend stand-in that hands back fixed RGB+depth buffers."""

    def __init__(self, rgb: np.ndarray, depth: np.ndarray) -> None:
        self._buffers = SimpleNamespace(color_rgb8=rgb, depth_m_f32=depth, seg_u16=None)
        self.captures: list[dict] = []
        self.closed = False

    def capture(self, *, source_timestamp_ns, sequence, robot_x, robot_y, robot_yaw_rad):
        self.captures.append({"x": robot_x, "y": robot_y, "yaw": robot_yaw_rad, "seq": sequence})

    @property
    def last_buffers(self):
        return self._buffers

    def close(self) -> None:
        self.closed = True


class _FakeDetector:
    """Returns one box for any query — the recognition step, faked deterministically."""

    name = "fake_owlv2"

    def __init__(self, box: tuple[int, int, int, int], label: str = "lamppost") -> None:
        self._box = box
        self._label = label

    def detect(self, *, rgb, depth, seg, query):
        del rgb, depth, seg, query
        return [PixelDetection(label=self._label, score=0.71, box=self._box, seg_id=None)]


def _fake_ingress_frame() -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    from parcel_robot.camera_channel.channel import CameraChannelSpec

    spec = CameraChannelSpec.d455_go2_nominal()
    h, w = spec.intrinsics.height_px, spec.intrinsics.width_px
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    depth = np.full((h, w), np.inf, dtype=np.float32)
    # A box straddling the principal point at a clean 3.0 m depth.
    u0, v0, u1, v1 = (600, 320, 680, 400)
    depth[v0:v1, u0:u1] = 3.0
    rgb[v0:v1, u0:u1] = (200, 40, 40)
    return rgb, depth, (u0, v0, u1, v1)


def test_radius_m_from_box_depth_is_half_angular_width_times_depth() -> None:
    # 80 px wide box at D=3 m, fx=644 → r = 40 * 3 / 644.
    assert radius_m_from_box_depth((600, 320, 680, 400), 3.0, 644.0) == pytest.approx(
        40.0 * 3.0 / 644.0
    )
    # Tall thin box: footprint uses the larger side.
    assert radius_m_from_box_depth((600, 200, 620, 400), 2.0, 500.0) == pytest.approx(
        100.0 * 2.0 / 500.0
    )


def test_camera_ingress_poll_produces_pixel_candidate() -> None:
    from parcel_robot.camera_channel.channel import CameraChannelSpec
    from parcel_robot.instructnav.scoring import object_near_envelope_m

    spec = CameraChannelSpec.d455_go2_nominal()
    rgb, depth, box = _fake_ingress_frame()
    backend = _FakeCaptureBackend(rgb, depth)
    ingress = CameraIngress(
        backend=backend,
        detector=_FakeDetector(box),
        intrinsics=spec.intrinsics,
        mount=spec.mount,
        depth_min_m=spec.depth_min_m,
        depth_max_m=spec.depth_max_m,
    )

    # No query/pose yet ⇒ no work, non-blocking read returns None.
    assert ingress.poll_once() is None
    assert ingress.latest_candidates() is None

    ingress.set_query("lamppost")
    ingress.set_pose(0.0, 0.0, 0.0)
    candidates = ingress.poll_once()
    assert candidates is not None and len(candidates) == 1
    cand = candidates[0]
    assert cand["kind"] == "object"
    assert cand["label"] == "lamppost"
    assert cand["source"] == PIXEL_SOURCE
    assert 0.0 <= cand["confidence"] <= 1.0
    # The box sits ahead of a camera looking down +x, so the world point is ~3 m
    # in front of the mount (depth 3.0 + forward offset), finite, and reasonable.
    x, y, z = cand["position"]
    assert all(math.isfinite(v) for v in (x, y, z))
    assert 2.5 < x < 4.0
    assert abs(y) < 1.0
    # Honest box+depth footprint + full near-envelope (city_semantics field set).
    expected_r = radius_m_from_box_depth(box, 3.0, spec.intrinsics.fx)
    meta = cand["metadata"]
    assert meta["radius_m"] == pytest.approx(expected_r, abs=1e-3)
    stand_off, minimum, vicinity = object_near_envelope_m(
        expected_r, label="lamppost"
    )
    assert meta["stand_off_m"] == pytest.approx(stand_off)
    assert meta["minimum_vicinity_radius_m"] == pytest.approx(minimum)
    assert meta["vicinity_radius_m"] == pytest.approx(vicinity)
    assert meta["arrival_radius_m"] == pytest.approx(0.06)
    assert meta["target_min_surface_clearance_m"] == pytest.approx(0.8)
    # Front-surface + radius recovers a CENTRE ahead of the depth plane.
    assert x > 3.0  # 3 m front depth + radius push along +x
    # The render was placed at the pose we set.
    assert backend.captures[-1]["x"] == 0.0
    assert ingress.latest_candidates()[0]["id"] == cand["id"]
    assert ingress.stats.polls == 1


def test_camera_ingress_poll_survives_detector_error() -> None:
    from parcel_robot.camera_channel.channel import CameraChannelSpec

    spec = CameraChannelSpec.d455_go2_nominal()

    class _Boom:
        name = "boom"

        def detect(self, *, rgb, depth, seg, query):
            raise RuntimeError("detector exploded")

    rgb, depth, _ = _fake_ingress_frame()
    ingress = CameraIngress(
        backend=_FakeCaptureBackend(rgb, depth),
        detector=_Boom(),
        intrinsics=spec.intrinsics,
        mount=spec.mount,
    )
    ingress.set_query("lamppost")
    ingress.set_pose(0.0, 0.0, 0.0)
    # A detector error must not crash: poll returns None and the buffer stays empty.
    assert ingress.poll_once() is None
    assert ingress.stats.errors == 1
    assert ingress.latest_candidates() is None


# ---------------------------------------------------------------------------
# B4 — guarded live cell: real OWLv2 + EGL render
# ---------------------------------------------------------------------------


def _live_ingress_available() -> tuple[bool, str]:
    os.environ.setdefault("MUJOCO_GL", "egl")
    from parcel_robot.camera_channel.backends.factory import probe_mujoco_offscreen
    from parcel_robot.detection_adapter.owlv2_onnx import owlv2_weights_present

    if not owlv2_weights_present():
        return False, "OWLv2 weights absent"
    if not probe_mujoco_offscreen().available:
        return False, "no offscreen GL (MUJOCO_GL=egl)"
    return True, ""


@pytest.mark.slow
def test_camera_ingress_live_owlv2_localizes_object() -> None:
    """B4 guarded live cell — real OWLv2 weights, real EGL render.

    Card R26, found by the first recorded nightly. This cell used to CRASH
    rather than run or skip, and had done so in every ad-hoc slow sweep on
    record (R20 §6.1 attributed the same red as environmental):
    ``_live_ingress_available`` gates on ``owlv2_weights_present()``, but
    ``CameraIngress.from_model_data`` loads the detector through
    ``load_owlv2_detector(require_env=True)`` — the opt-in ``PARCEL_OWLV2_ONNX``
    switch. On a machine where the weights ARE fetched and the switch is simply
    off (the normal state of this repo: the switch is default-off by Design A,
    and the commit tier's model-off gate exists to keep it that way), the guard
    said "available", the loader said ``None``, and the constructor raised
    ``RuntimeError: camera ingress requested but the OWLv2 detector is
    unavailable`` — so the ONE test that exercises the real detector could never
    pass and was permanently misfiled as "environmental".

    The fix is the seam the loader documents: a test that has already decided to
    run the real model builds it with ``require_env=False`` and hands it in.
    Nothing about the default-off env gate changes — this is the caller opting
    in, not the switch flipping.
    """

    ok, why = _live_ingress_available()
    if not ok:
        pytest.skip(why)
    import mujoco

    from parcel_robot.camera_channel.channel import CameraChannelSpec
    from parcel_robot.detection_adapter.owlv2_onnx import load_owlv2_detector

    detector = load_owlv2_detector(threshold=0.05, require_env=False)
    if detector is None:
        pytest.skip("OWLv2 weights present but the detector would not load (runtime deps absent)")

    spec = CameraChannelSpec.d455_go2_nominal()
    # A red ball 3 m ahead of the robot at the origin.
    xml = (
        '<mujoco><worldbody><light pos="0 0 5"/>'
        '<geom name="ground" type="plane" size="40 40 0.1" rgba="0.7 0.7 0.72 1"/>'
        '<body name="target" pos="3.0 0.0 0.5">'
        '<geom name="ball" type="sphere" size="0.35" rgba="1 0 0 1"/></body>'
        "</worldbody></mujoco>"
    )
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    ingress = CameraIngress.from_model_data(
        model, data, spec=spec, detector=detector, threshold=0.05, class_ids=("bg", "obj")
    )
    try:
        ingress.set_query("red ball")
        ingress.set_pose(0.0, 0.0, 0.0)
        candidates = ingress.poll_once()
        assert candidates, "OWLv2 found no red ball on the render (recognition floor)"
        best = max(candidates, key=lambda c: c["confidence"])
        x, y, _z = best["position"]
        # Localizes within the arrival band of the true 3 m target.
        assert math.dist((x, y), (3.0, 0.0)) < 0.6
        assert best["source"] == PIXEL_SOURCE
    finally:
        ingress.stop()


# ---------------------------------------------------------------------------
# memory write-path
# ---------------------------------------------------------------------------

_MEMORY_EXTRA = (
    "prompting:\n"
    "  enabled: true\n"
    "  user_profile:\n"
    "    home: Manhattan\n"
    "  memory:\n"
    "    enabled: true\n"
    "    tier1_max_turns: 2\n"
    "    tier2_max_summaries: 6\n"
)


def test_memory_disabled_by_default_is_none(tmp_path: Path) -> None:
    runtime = _make_runtime(_base_config(tmp_path))
    try:
        assert runtime.prompting.memory is None
    finally:
        runtime.close()


def test_write_feed_is_noop_when_memory_disabled_prompt_byte_identical(
    tmp_path: Path,
) -> None:
    # prompting enabled but memory NOT enabled: the write feed must be inert and
    # the composed prompt byte-identical before and after feeding live turns.
    config = _base_config(tmp_path, extra="prompting:\n  enabled: true\n")
    runtime = _make_runtime(config)
    try:
        assert runtime.prompting.memory is None
        composer = runtime.prompting.composer
        assert composer is not None
        before = composer.compose("anything").text
        for i in range(6):
            runtime._chat_item("user", f"remember fact number {i}")
            runtime._chat_item("assistant", f"noted {i}")
        after = composer.compose("anything").text
        assert before == after
        assert not any("memory_tier" in s for s in composer.sources())
    finally:
        runtime.close()


def test_live_turns_flow_and_aged_fact_surfaces_into_prompt(tmp_path: Path) -> None:
    runtime = _make_runtime(_base_config(tmp_path, extra=_MEMORY_EXTRA))
    try:
        memory = runtime.prompting.memory
        assert memory is not None
        # A durable fact early, then enough turns to age it out of Tier 1 (max 2).
        runtime._chat_item("user", "my dog's name is Pickle and he loves pineapple")
        runtime._chat_item("assistant", "Pickle is a lovely name")
        for i in range(6):
            runtime._chat_item("user", f"small talk turn {i}")
            runtime._chat_item("assistant", f"reply {i}")

        # Live turns actually flowed into the store.
        assert memory.turn_count() == 14

        retrieval = memory.retrieve("what is my dog's name")
        tier1_text = " ".join(t.content for t in retrieval.tier1_recent)
        assert "Pickle" not in tier1_text  # aged out of verbatim Tier 1
        tier2_text = " ".join(s.text for s in retrieval.tier2_summaries)
        assert "Pickle" in tier2_text  # survived into the Tier-2 rolling summary

        # And it surfaces into the composed prompt's memory section.
        composed = runtime.prompting.composer.compose("what is my dog's name")
        assert "Pickle" in composed.text
        assert any("memory_tier" in s for s in runtime.prompting.composer.sources())
    finally:
        runtime.close()


def test_handle_text_feeds_memory_turns(tmp_path: Path) -> None:
    runtime = _make_runtime(_base_config(tmp_path, extra=_MEMORY_EXTRA))
    try:
        memory = runtime.prompting.memory
        assert memory is not None
        before = memory.turn_count()
        runtime.handle_text("sit")
        # handle_text commits a user turn and an assistant reply through _chat_item.
        assert memory.turn_count() >= before + 2
    finally:
        runtime.close()
