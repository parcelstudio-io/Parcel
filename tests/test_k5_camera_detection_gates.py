"""K5 Sol: CameraChannel, DetectionMsg noise adapter, low-viewpoint gates."""

from __future__ import annotations

import math
import random
from dataclasses import FrozenInstanceError

import pytest

from parcel_robot.camera_channel import (
    CALIBRATION_ID_NOMINAL,
    MOUNT_HEIGHT_M,
    CameraChannel,
    CameraChannelSpec,
    CameraFrameEnvelope,
    ColorFrameMeta,
    assert_nominal_d455_contract,
    color_meta_from_mapping,
    d455_color_intrinsics,
    go2_d455_mount,
)
from parcel_robot.contracts import DetectionMsg, EvidenceEnvelopeV1, SCHEMA_VERSION
from parcel_robot.detection_adapter import (
    DetectionNoiseAdapter,
    DetectionNoiseConfig,
    GroundTruthDetection,
    default_person_confusion,
)
from parcel_robot.low_viewpoint import (
    DOES_NOT_PROVE,
    GATE_CURB_HEIGHT_MAP_NO_D455,
    GATE_LEGS_FIRST_REID,
    GATE_OCR_UPWARD_ANGLE,
    GATE_VPR_AT_35CM,
    LOW_VIEWPOINT_GATE_IDS,
    LowViewpointSample,
    LowViewpointThresholds,
    all_passed,
    evaluate_all_gates,
    gate_curb_height_map_without_d455,
    gate_legs_first_reid,
    gate_ocr_upward_angle,
    gate_vpr_at_35cm,
)


# ---------------------------------------------------------------------------
# CameraChannel
# ---------------------------------------------------------------------------


def test_d455_nominal_intrinsics_and_mount_match_bag_contract() -> None:
    intr = d455_color_intrinsics()
    mount = go2_d455_mount()
    assert intr.width_px == 1280
    assert intr.height_px == 720
    assert intr.fx == 644.0
    assert intr.fy == 644.0
    assert intr.cx == 640.0
    assert intr.cy == 360.0
    assert intr.calibration_id == CALIBRATION_ID_NOMINAL
    assert mount.height_m == MOUNT_HEIGHT_M == 0.35
    assert mount.is_dog_height()
    assert_nominal_d455_contract(CameraChannelSpec.d455_go2_nominal())
    assert intr.horizontal_fov_rad() > math.radians(80.0)


def test_camera_channel_stub_envelope_and_bag_meta_round_trip() -> None:
    channel = CameraChannel()
    assert not channel.has_backend
    envelope = channel.wrap_stub_envelope(
        source_timestamp_ns=1_000,
        sequence=3,
        class_ids=("person", "sidewalk", "curb"),
        color_blob_ref="mem://color-3",
    )
    assert isinstance(envelope, CameraFrameEnvelope)
    assert envelope.kinds() == ("rgb", "depth", "segmentation")
    assert envelope.color.mount_height_m == 0.35
    assert envelope.color.calibration_id == CALIBRATION_ID_NOMINAL
    assert envelope.segmentation is not None
    assert envelope.segmentation.class_ids == ("person", "sidewalk", "curb")
    channel.validate_envelope(envelope)

    bag_payload = {
        "width_px": 1280,
        "height_px": 720,
        "fx": 644.0,
        "fy": 644.0,
        "cx": 640.0,
        "cy": 360.0,
        "mount_height_m": 0.35,
        "encoding": "rgb8",
        "blob_ref": None,
    }
    meta = color_meta_from_mapping(bag_payload)
    assert meta == ColorFrameMeta.from_intrinsics(
        d455_color_intrinsics(), mount_height_m=0.35
    )


def test_camera_channel_capture_requires_backend() -> None:
    channel = CameraChannel()
    with pytest.raises(RuntimeError, match="no backend"):
        channel.capture(source_timestamp_ns=0, sequence=0)

    class StubBackend:
        def capture(
            self,
            *,
            source_timestamp_ns: int,
            sequence: int,
            scene_revision: int = 0,
        ) -> CameraFrameEnvelope:
            return CameraChannel().wrap_stub_envelope(
                source_timestamp_ns=source_timestamp_ns,
                sequence=sequence,
                scene_revision=scene_revision,
            )

    channel.attach_backend(StubBackend())
    got = channel.capture(source_timestamp_ns=42, sequence=7, scene_revision=1)
    assert got.sequence == 7
    assert got.source_timestamp_ns == 42


def test_elevation_angle_positive_for_tall_sign() -> None:
    channel = CameraChannel()
    # Tall storefront lettering close-in from 0.35 m mount (extreme upward look).
    elev = channel.elevation_angle_to_point_rad(
        horizontal_range_m=3.0, target_height_m=3.0
    )
    assert elev > math.radians(25.0)


def test_camera_spec_frozen() -> None:
    spec = CameraChannelSpec.d455_go2_nominal()
    with pytest.raises(FrozenInstanceError):
        spec.rgb_fps = 15  # type: ignore[misc]
    assert "does_not_prove" in spec.as_dict()


# ---------------------------------------------------------------------------
# DetectionNoiseAdapter
# ---------------------------------------------------------------------------


def _gt(
    *,
    class_id: str = "person",
    range_m: float = 2.0,
    bearing: float = 0.1,
) -> GroundTruthDetection:
    return GroundTruthDetection(
        class_id=class_id,
        embedding=(0.1, 0.2, 0.3, 0.4),
        bearing_rad=bearing,
        range_m=range_m,
        track_id="trk-1",
    )


def test_p_detect_range_cutoff_and_interpolation() -> None:
    cfg = DetectionNoiseConfig(confusion=default_person_confusion())
    assert cfg.p_detect(0.5) == cfg.p_detect_near
    assert cfg.p_detect(cfg.range_cutoff_m + 0.1) == 0.0
    mid = 0.5 * (cfg.p_detect_near_range_m + cfg.p_detect_far_range_m)
    mid_p = cfg.p_detect(mid)
    assert cfg.p_detect_far < mid_p < cfg.p_detect_near


def test_adapter_drops_beyond_cutoff_and_emits_detection_msg() -> None:
    adapter = DetectionNoiseAdapter(
        DetectionNoiseConfig(
            range_cutoff_m=5.0,
            p_detect_near=1.0,
            p_detect_far=1.0,
            p_detect_near_range_m=1.0,
            p_detect_far_range_m=5.0,
            bearing_jitter_std_rad=0.0,
            range_jitter_std_m=0.0,
            score_jitter_std=0.0,
            embedding_jitter_std=0.0,
            confusion={},
        )
    )
    rng = random.Random(0)
    far = adapter.adapt_ground_truth(
        [_gt(range_m=6.0)],
        rng=rng,
        received_monotonic_ns=1_000_000_000,
    )
    assert far == []

    near = adapter.adapt_ground_truth(
        [_gt(range_m=2.0, class_id="lamppost")],
        rng=rng,
        received_monotonic_ns=1_000_000_000,
    )
    assert len(near) == 1
    msg = near[0]
    assert isinstance(msg, DetectionMsg)
    assert msg.class_id == "lamppost"
    assert msg.range_m == pytest.approx(2.0)
    assert msg.envelope.source == "sim.detection_adapter"
    assert msg.envelope.calibration_id == CALIBRATION_ID_NOMINAL
    assert DetectionMsg.from_mapping(msg.as_dict()) == msg


def test_adapter_applies_confusion_and_jitter_deterministically() -> None:
    cfg = DetectionNoiseConfig(
        range_cutoff_m=10.0,
        p_detect_near=1.0,
        p_detect_far=1.0,
        p_detect_near_range_m=1.0,
        p_detect_far_range_m=10.0,
        bearing_jitter_std_rad=0.1,
        range_jitter_std_m=0.2,
        score_jitter_std=0.0,
        embedding_jitter_std=0.0,
        confusion={"person": {"person": 0.0, "owner": 1.0}},
    )
    a = DetectionNoiseAdapter(cfg).adapt_ground_truth(
        [_gt()], rng=random.Random(7), received_monotonic_ns=10
    )
    b = DetectionNoiseAdapter(cfg).adapt_ground_truth(
        [_gt()], rng=random.Random(7), received_monotonic_ns=10
    )
    assert a[0].class_id == "owner"
    assert a[0].as_dict() == b[0].as_dict()
    # Same seed ⇒ same jitter; seed 7 moves bearing off the GT value.
    assert a[0].bearing_rad != pytest.approx(0.1)


def test_adapter_consumes_detection_msg() -> None:
    adapter = DetectionNoiseAdapter(
        DetectionNoiseConfig(
            range_cutoff_m=10.0,
            p_detect_near=1.0,
            p_detect_far=1.0,
            p_detect_near_range_m=1.0,
            p_detect_far_range_m=10.0,
            bearing_jitter_std_rad=0.0,
            range_jitter_std_m=0.0,
            score_jitter_std=0.0,
            embedding_jitter_std=0.0,
            confusion={},
        )
    )
    seed = adapter.adapt_ground_truth(
        [_gt()], rng=random.Random(1), received_monotonic_ns=100
    )
    again = adapter.adapt_detections(seed, rng=random.Random(2))
    assert len(again) == 1
    assert again[0].class_id == "person"
    assert "detection_noise_adapter_v1" in again[0].envelope.provenance


def test_p_detect_miss_is_probabilistic() -> None:
    adapter = DetectionNoiseAdapter(
        DetectionNoiseConfig(
            range_cutoff_m=10.0,
            p_detect_near=0.0,
            p_detect_far=0.0,
            p_detect_near_range_m=1.0,
            p_detect_far_range_m=10.0,
            confusion={},
        )
    )
    assert (
        adapter.adapt_ground_truth(
            [_gt()], rng=random.Random(99), received_monotonic_ns=1
        )
        == []
    )


# ---------------------------------------------------------------------------
# Low-viewpoint gates
# ---------------------------------------------------------------------------


def _good_sample(**overrides: object) -> LowViewpointSample:
    payload: dict[str, object] = {
        "mount_height_m": 0.35,
        "sign_elevation_angle_rad": math.radians(30.0),
        "ocr_char_recall": 0.85,
        "legs_visible_fraction": 0.75,
        "torso_visible_fraction": 0.35,
        "reid_top1_correct": True,
        "vpr_recall_at_1": 0.72,
        "curb_detected_from_height_map": True,
        "d455_depth_available": False,
    }
    payload.update(overrides)
    return LowViewpointSample(**payload)  # type: ignore[arg-type]


def test_low_viewpoint_gates_pass_on_nominal_sample() -> None:
    sample = _good_sample()
    results = evaluate_all_gates(sample)
    assert {r.gate_id for r in results} == LOW_VIEWPOINT_GATE_IDS
    assert all_passed(results)
    assert all(r.passed and r.reason for r in results)
    assert DOES_NOT_PROVE


def test_ocr_gate_fails_on_low_recall_or_shallow_angle() -> None:
    fail_recall = gate_ocr_upward_angle(_good_sample(ocr_char_recall=0.2))
    assert fail_recall.gate_id == GATE_OCR_UPWARD_ANGLE
    assert not fail_recall.passed
    assert "ocr_char_recall" in fail_recall.reason

    fail_angle = gate_ocr_upward_angle(
        _good_sample(sign_elevation_angle_rad=math.radians(5.0))
    )
    assert not fail_angle.passed
    assert "elevation" in fail_angle.reason


def test_legs_first_reid_and_vpr_and_curb_gates() -> None:
    assert gate_legs_first_reid(_good_sample()).passed
    fail_reid = gate_legs_first_reid(_good_sample(reid_top1_correct=False))
    assert fail_reid.gate_id == GATE_LEGS_FIRST_REID
    assert not fail_reid.passed

    fail_vpr = gate_vpr_at_35cm(_good_sample(vpr_recall_at_1=0.1))
    assert fail_vpr.gate_id == GATE_VPR_AT_35CM
    assert not fail_vpr.passed

    fail_curb = gate_curb_height_map_without_d455(
        _good_sample(d455_depth_available=True)
    )
    assert fail_curb.gate_id == GATE_CURB_HEIGHT_MAP_NO_D455
    assert not fail_curb.passed
    assert "D455" in fail_curb.reason

    assert not gate_curb_height_map_without_d455(
        _good_sample(curb_detected_from_height_map=False)
    ).passed


def test_mount_height_mismatch_fails_viewpoint_gates() -> None:
    sample = _good_sample(mount_height_m=1.5)
    assert not gate_ocr_upward_angle(sample).passed
    assert not gate_vpr_at_35cm(sample).passed
    thr = LowViewpointThresholds(mount_height_tolerance_m=0.0)
    assert not gate_legs_first_reid(sample, thr).passed


def test_evidence_envelope_still_valid_from_adapter() -> None:
    """Sanity: adapter envelopes remain contract-valid."""
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
    msg = adapter.adapt_ground_truth(
        [_gt()], rng=random.Random(0), received_monotonic_ns=5_000
    )[0]
    env = EvidenceEnvelopeV1.from_mapping(msg.envelope.as_dict())
    assert env.schema_version == SCHEMA_VERSION
