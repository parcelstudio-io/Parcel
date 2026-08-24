"""K5 Opus: CameraBackend wiring, sim→DetectionMsg path, low-viewpoint smoke."""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from parcel_robot.backends.base import OwnerTrack, RobotPose, SemanticObjectTrack, SimObservation
from parcel_robot.camera_channel.backends.factory import (
    attach_preferred_backend,
    open_camera_backend,
    probe_mujoco_offscreen,
)
from parcel_robot.camera_channel.backends.synthetic import SyntheticCameraBackend
from parcel_robot.camera_channel.channel import CameraChannel, CameraChannelSpec
from parcel_robot.contracts.v1 import DetectionMsg
from parcel_robot.detection_adapter.adapter import DetectionNoiseAdapter
from parcel_robot.detection_adapter.noise import DetectionNoiseConfig
from parcel_robot.detection_adapter.sim_bridge import (
    SimTrackObservation,
    detections_for_agent,
    detections_from_observation,
    label_embedding,
    privileged_gt_from_tracks,
)
from parcel_robot.low_viewpoint.samples import (
    assert_pack_expectations,
    load_sample_pack,
    smoke_default_pack,
)

# ---------------------------------------------------------------------------
# Camera backends
# ---------------------------------------------------------------------------


def test_synthetic_backend_fills_envelope_and_is_deterministic() -> None:
    backend_a = SyntheticCameraBackend(seed=11)
    backend_b = SyntheticCameraBackend(seed=11)
    env_a = backend_a.capture(source_timestamp_ns=100, sequence=3, scene_revision=1)
    env_b = backend_b.capture(source_timestamp_ns=100, sequence=3, scene_revision=1)
    assert env_a.color.blob_ref is not None
    assert env_a.depth.blob_ref is not None
    assert env_a.segmentation is not None
    assert env_a.color.width_px == 1280
    assert env_a.color.mount_height_m == 0.35
    color_a = backend_a.get_buffer(env_a.color.blob_ref)
    color_b = backend_b.get_buffer(env_b.color.blob_ref)
    assert color_a.shape == (720, 1280, 3)
    assert color_a.dtype == np.uint8
    assert np.array_equal(color_a, color_b)
    depth = backend_a.get_buffer(env_a.depth.blob_ref)
    assert depth.dtype == np.float32
    assert float(depth.min()) >= 0.4
    assert float(depth.max()) <= 6.0


def test_camera_channel_attaches_synthetic_backend() -> None:
    channel = CameraChannel()
    kind = attach_preferred_backend(channel, prefer="synthetic", seed=0)
    assert kind == "synthetic"
    assert channel.has_backend
    got = channel.capture(source_timestamp_ns=1, sequence=0)
    assert got.sequence == 0
    channel.validate_envelope(got)


def test_open_camera_backend_auto_falls_back_without_model() -> None:
    backend, kind = open_camera_backend(prefer="auto")
    assert kind == "synthetic"
    assert isinstance(backend, SyntheticCameraBackend)


def test_probe_mujoco_offscreen_reports_honest_dict() -> None:
    result = probe_mujoco_offscreen()
    payload = result.as_dict()
    assert "available" in payload
    assert "does_not_prove" in payload
    assert payload["does_not_prove"]
    # Presence only — CI may or may not have EGL in-process.
    assert isinstance(result.available, bool)


def test_mujoco_egl_backend_optional() -> None:
    """Exercise EGL path when the process can render; otherwise skip cleanly."""

    probe = probe_mujoco_offscreen()
    if not probe.available:
        pytest.skip(f"MuJoCo offscreen unavailable: {probe.detail}")

    import mujoco

    xml = (
        '<mujoco><worldbody><light pos="0 0 3"/>'
        '<geom type="plane" size="2 2 0.1"/>'
        '<body pos="1 0 0.3"><geom type="box" size="0.2 0.2 0.2" rgba="0 1 0 1"/>'
        "</body></worldbody></mujoco>"
    )
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    backend, kind = open_camera_backend(
        prefer="mujoco_egl",
        model=model,
        data=data,
    )
    assert kind == "mujoco_egl"
    channel = CameraChannel(CameraChannelSpec.d455_go2_nominal())
    channel.attach_backend(backend)
    envelope = channel.capture(source_timestamp_ns=5, sequence=1)
    assert envelope.color.blob_ref is not None
    rgb = backend.get_buffer(envelope.color.blob_ref)  # type: ignore[attr-defined]
    assert rgb.shape[0] == 720 and rgb.shape[1] == 1280
    backend.close()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# DetectionMsg sim bridge
# ---------------------------------------------------------------------------


def test_privileged_gt_helper_and_agent_path_use_noise() -> None:
    tracks = [
        SimTrackObservation(track_id="lamp_post_1", class_id="lamppost", x=3.0, y=0.5),
        SimTrackObservation(track_id="bench_1", class_id="bench", x=2.0, y=-1.0),
    ]
    gt = privileged_gt_from_tracks(
        tracks, robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0
    )
    assert len(gt) == 2
    assert gt[0].range_m == pytest.approx(math.hypot(3.0, 0.5))
    assert gt[0].class_id == "lamppost"

    adapter = DetectionNoiseAdapter(
        DetectionNoiseConfig(
            range_cutoff_m=10.0,
            p_detect_near=1.0,
            p_detect_far=1.0,
            p_detect_near_range_m=1.0,
            p_detect_far_range_m=10.0,
            bearing_jitter_std_rad=0.05,
            range_jitter_std_m=0.1,
            score_jitter_std=0.0,
            embedding_jitter_std=0.0,
            confusion={},
        )
    )
    agent = detections_for_agent(
        tracks,
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        rng=random.Random(3),
        received_monotonic_ns=1_000_000,
        adapter=adapter,
    )
    assert len(agent) == 2
    assert all(isinstance(m, DetectionMsg) for m in agent)
    # Noise moves range off exact GT for seed 3.
    assert agent[0].range_m != pytest.approx(gt[0].range_m)
    assert "detection_noise_adapter_v1" in agent[0].envelope.provenance


def test_detections_from_observation_agent_path() -> None:
    observation = SimObservation(
        timestamp=1.5,
        robot=RobotPose(x=0.0, y=0.0, yaw=0.0),
        owner=OwnerTrack(owner_id="owner-1", x=1.0, y=0.0, visible=True, confidence=0.9),
        semantic_objects=(
            SemanticObjectTrack(
                object_id="lamp_post_1",
                label="lamppost",
                position=(4.0, 0.0, 0.0),
                confidence=1.0,
            ),
        ),
        backend="test",
    )
    adapter = DetectionNoiseAdapter(
        DetectionNoiseConfig(
            p_detect_near=1.0,
            p_detect_far=1.0,
            confusion={},
            bearing_jitter_std_rad=0.0,
            range_jitter_std_m=0.0,
            score_jitter_std=0.0,
            embedding_jitter_std=0.0,
        )
    )
    msgs = detections_from_observation(
        observation,
        rng=random.Random(0),
        received_monotonic_ns=2_000,
        adapter=adapter,
    )
    classes = {m.class_id for m in msgs}
    assert "lamppost" in classes
    assert "owner" in classes
    assert all(m.envelope.source == "sim.detection_adapter" for m in msgs)


def test_label_embedding_stable() -> None:
    assert label_embedding("person") == label_embedding("person")
    assert label_embedding("person") != label_embedding("bench")


def test_agent_path_does_not_expose_raw_gt_as_detection_without_adapter_fields() -> None:
    """Regression: agent detections always carry adapter provenance."""

    msgs = detections_for_agent(
        [SimTrackObservation(track_id="p1", class_id="person", x=1.5, y=0.0)],
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        rng=random.Random(1),
        received_monotonic_ns=10,
        adapter=DetectionNoiseAdapter(
            DetectionNoiseConfig(
                p_detect_near=1.0,
                p_detect_far=1.0,
                confusion={},
                bearing_jitter_std_rad=0.0,
                range_jitter_std_m=0.0,
                score_jitter_std=0.0,
                embedding_jitter_std=0.0,
            )
        ),
    )
    assert msgs[0].envelope.provenance == ("detection_noise_adapter_v1",)


# ---------------------------------------------------------------------------
# Low-viewpoint sample pack smoke
# ---------------------------------------------------------------------------


def test_low_viewpoint_sample_pack_smoke() -> None:
    pack = load_sample_pack()
    assert pack.version == 1
    assert len(pack.samples) >= 4
    results = pack.smoke()
    assert_pack_expectations(results)
    # Also exercise the convenience entrypoint.
    assert_pack_expectations(smoke_default_pack())


def test_low_viewpoint_pack_documents_hr4() -> None:
    pack = load_sample_pack()
    joined = " ".join(pack.does_not_prove).lower()
    assert "hr-4" in joined or "d455" in joined
