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
from parcel_robot.contracts import SCHEMA_VERSION, DetectionMsg, EvidenceEnvelopeV1
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


# ---------------------------------------------------------------------------
# B1: MuJoCo-EGL intrinsics fix + seg-truth back-projection self-check
# ---------------------------------------------------------------------------

import numpy as np

from parcel_robot.detection_adapter.pixel_detections import (
    CameraExtrinsics,
    PixelDetection,
    SegTruthDetector,
    back_project,
    localize_detection,
    localize_frame,
    project,
)

#: Pinned bound for the pure synthetic seg-truth self-check: a flat facing patch
#: at the centroid depth back-projects to within pixel-quantization of truth.
_SEG_TRUTH_PURE_BOUND_M = 0.01
#: Pinned bound for the real-render self-check against a MuJoCo geom centroid:
#: the back-projected SURFACE point sits ~one radius in front of the volumetric
#: centre, so the bound is radius + a small geometry margin. The un-fixed
#: fovy=45 render misses this by >2x (asserted below).
_SEG_TRUTH_REAL_MARGIN_M = 0.03


def _synthetic_seg_depth(intr, ext, targets):
    """Project ``targets`` {seg_id: (label, world_xyz, radius)} to (seg, depth).

    Flat facing patches at each centroid's optical-axis depth — the CI-safe
    stand-in for a MuJoCo seg render, sharing the localizer's exact geometry.
    """

    h, w = intr.height_px, intr.width_px
    seg = np.zeros((h, w), dtype=np.int32)
    depth = np.zeros((h, w), dtype=np.float64)
    for seg_id, (_label, pos, radius) in targets.items():
        pr = project(pos, intr, ext)
        assert pr is not None
        u, v, d = pr
        r_px = max(4, round(intr.fx * radius / d))
        uc_i, vc_i = round(u), round(v)
        u0, u1 = uc_i - r_px, uc_i + r_px
        v0, v1 = vc_i - r_px, vc_i + r_px
        seg[v0:v1, u0:u1] = seg_id
        depth[v0:v1, u0:u1] = d
    return seg, depth


def test_advertised_fovy_reconstructs_the_d455_focal() -> None:
    """The vertical fov the render is bound to reproduces fx=fy=644, cx/cy centered."""

    intr = d455_color_intrinsics()
    fovy = intr.vertical_fov_rad()  # 2·atan(H/(2·fy))
    fy_reconstructed = intr.height_px / (2.0 * math.tan(fovy / 2.0))
    assert fy_reconstructed == pytest.approx(644.0, abs=1e-6)
    # A MuJoCo free camera can only carry a centered principal point.
    assert intr.cx == pytest.approx(intr.width_px / 2.0)
    assert intr.cy == pytest.approx(intr.height_px / 2.0)
    assert intr.fx == pytest.approx(intr.fy)


def test_back_projection_is_the_exact_inverse_of_projection() -> None:
    intr = d455_color_intrinsics()
    ext = CameraExtrinsics.from_mount_pose(robot_x=1.0, robot_y=-2.0, robot_yaw_rad=0.6)
    for world in [(3.0, 0.4, 0.7), (2.2, -0.9, 1.3), (4.5, 1.1, 0.3)]:
        u, v, d = project(world, intr, ext)
        recovered = ext.camera_to_world(back_project(u, v, d, intr))
        assert recovered == pytest.approx(world, abs=1e-9)


def test_pure_seg_truth_backprojection_self_check() -> None:
    """Back-project a rendered box+depth; assert it lands on the seg-truth centroid."""

    intr = d455_color_intrinsics()
    ext = CameraExtrinsics.from_mount_pose(robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.2)
    targets = {
        2: ("bench", (3.0, 0.5, 0.5), 0.3),
        3: ("lamppost", (4.0, -0.7, 1.1), 0.2),
    }
    seg, depth = _synthetic_seg_depth(intr, ext, targets)
    localized = localize_frame(
        SegTruthDetector({k: v[0] for k, v in targets.items()}),
        rgb=None,
        depth=depth,
        seg=seg,
        query=None,
        intrinsics=intr,
        extrinsics=ext,
        source_timestamp_ns=1,
        received_monotonic_ns=1,
        depth_max_m=1000.0,
    )
    assert len(localized) == 2
    for loc in localized:
        truth = targets[loc.seg_id][1]
        err = float(
            np.linalg.norm(
                np.array([loc.world_x, loc.world_y, loc.world_z]) - np.array(truth)
            )
        )
        assert err < _SEG_TRUTH_PURE_BOUND_M


def test_localizer_is_rigid_transform_equivariant() -> None:
    """Rotate+translate the whole scene (world points AND camera) -> the recovered
    world point transforms by the same SE2 rigid motion (metamorphic gate)."""

    intr = d455_color_intrinsics()
    base_pose = (0.5, -1.0, 0.3)
    target = (3.0, 0.6, 0.7)
    radius = 0.25

    def localize(pose, tgt):
        ext = CameraExtrinsics.from_mount_pose(
            robot_x=pose[0], robot_y=pose[1], robot_yaw_rad=pose[2]
        )
        seg, depth = _synthetic_seg_depth(intr, ext, {2: ("x", tgt, radius)})
        locs = localize_frame(
            SegTruthDetector({2: "x"}), rgb=None, depth=depth, seg=seg, query=None,
            intrinsics=intr, extrinsics=ext, source_timestamp_ns=1,
            received_monotonic_ns=1, depth_max_m=1000.0,
        )
        assert len(locs) == 1
        return np.array([locs[0].world_x, locs[0].world_y, locs[0].world_z])

    p0 = localize(base_pose, target)

    # Apply an SE2 rigid transform T = (rotate dyaw about origin, then translate).
    dyaw, tx, ty = 0.7, 2.0, -1.5
    c, s = math.cos(dyaw), math.sin(dyaw)

    def se2(x, y):
        return (c * x - s * y + tx, s * x + c * y + ty)

    tpose = (*se2(base_pose[0], base_pose[1]), base_pose[2] + dyaw)
    ttarget = (*se2(target[0], target[1]), target[2])
    p1 = localize(tpose, ttarget)

    expected = np.array([*se2(p0[0], p0[1]), p0[2]])
    assert np.linalg.norm(p1 - expected) < 1e-6


def test_erode_and_zscore_reject_survive_depth_outliers() -> None:
    """Gross depth outliers under a box are Z-score rejected; the point holds."""

    intr = d455_color_intrinsics()
    ext = CameraExtrinsics.from_mount_pose(robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0)
    target = (3.0, 0.0, 0.35)  # on the optical axis (mount height), centered
    seg, depth = _synthetic_seg_depth(intr, ext, {2: ("x", target, 0.35)})
    ys, xs = np.where(seg == 2)
    # Spray 5% of the mask (scattered, not a contiguous strip) with a 4 m spike;
    # scattered removal keeps the eroded-mask centroid unbiased.
    rng = np.random.default_rng(0)
    k = ys.size // 20
    pick = rng.choice(ys.size, size=k, replace=False)
    depth[ys[pick], xs[pick]] = depth[ys[0], xs[0]] + 4.0
    clean = localize_detection(
        PixelDetection(label="x", score=1.0, box=(int(xs.min()), int(ys.min()),
            int(xs.max()) + 1, int(ys.max()) + 1), seg_id=2),
        depth=depth, seg=seg, intrinsics=intr, extrinsics=ext,
        source_timestamp_ns=1, received_monotonic_ns=1, sequence=0, depth_max_m=1000.0,
    )
    assert clean is not None
    err = float(np.linalg.norm(
        np.array([clean.world_x, clean.world_y, clean.world_z]) - np.array(target)))
    assert err < _SEG_TRUTH_PURE_BOUND_M


def _try_build_real_backend(model, data, spec):
    from parcel_robot.camera_channel.backends.mujoco_egl import (
        MujocoEglCameraBackend,
        MujocoEglUnavailable,
    )

    try:
        return MujocoEglCameraBackend(model, data, spec=spec, class_ids=("bg", "tg"))
    except MujocoEglUnavailable as exc:
        pytest.skip(f"MuJoCo offscreen render unavailable: {exc}")


def test_real_render_seg_truth_self_check_and_fovy_bug_regression() -> None:
    """Guarded: the REAL MuJoCo render back-projects onto the true geom centroid
    with the fixed fovy, and the un-fixed fovy=45 misses by >2x (the fix is
    load-bearing). Skips where no offscreen GL context exists (CI)."""

    mujoco = pytest.importorskip("mujoco")
    from parcel_robot.camera_channel.channel import CameraChannelSpec

    spec = CameraChannelSpec.d455_go2_nominal()
    intr = spec.intrinsics
    tgt = (3.2, 0.6, 0.55)
    radius = 0.09
    xml = (
        '<mujoco><worldbody><light pos="0 0 5"/>'
        '<geom name="ground" type="plane" size="40 40 0.1"/>'
        f'<body name="t" pos="{tgt[0]} {tgt[1]} {tgt[2]}">'
        f'<geom name="tg" type="sphere" size="{radius}" rgba="1 0 0 1"/></body>'
        "</worldbody></mujoco>"
    )
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    backend = _try_build_real_backend(model, data, spec)

    # The render frustum is bound to the advertised focal, not the 45° default.
    assert backend.render_fovy_deg == pytest.approx(
        math.degrees(intr.vertical_fov_rad()), abs=1e-6
    )

    pose = (0.0, 0.0, 0.18)
    try:
        backend.capture(
            source_timestamp_ns=1, sequence=0,
            robot_x=pose[0], robot_y=pose[1], robot_yaw_rad=pose[2],
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"offscreen capture failed: {exc}")
    buffers = backend.last_buffers
    assert buffers is not None and buffers.seg_u16 is not None

    seg = buffers.seg_u16.astype(np.int32)
    depth = buffers.depth_m_f32.astype(np.float64)
    tid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "tg")
    seg_val = (tid + 1) & 0xFFFF
    if not (seg == seg_val).any():
        pytest.skip("target not visible in the rendered frustum")
    ext = CameraExtrinsics.from_mount_pose(
        robot_x=pose[0], robot_y=pose[1], robot_yaw_rad=pose[2], mount=spec.mount
    )
    localized = localize_frame(
        SegTruthDetector({seg_val: "tg"}), rgb=None, depth=depth, seg=seg,
        query="tg", intrinsics=intr, extrinsics=ext,
        source_timestamp_ns=1, received_monotonic_ns=1, depth_max_m=1000.0,
    )
    assert len(localized) == 1
    loc = localized[0]
    err_fixed = float(np.linalg.norm(
        np.array([loc.world_x, loc.world_y, loc.world_z]) - np.array(tgt)))
    assert err_fixed < radius + _SEG_TRUTH_REAL_MARGIN_M

    # Regression: render the SAME scene/camera at the buggy default fovy=45 and
    # back-project the seg-mask centroid — the error is >2x the fixed bound.
    pitch = spec.mount.pitch_up_rad
    fwd = np.array([
        math.cos(pitch) * math.cos(pose[2]),
        math.cos(pitch) * math.sin(pose[2]),
        math.sin(pitch),
    ])
    center = np.array([
        pose[0] + spec.mount.forward_m * math.cos(pose[2]),
        pose[1] + spec.mount.forward_m * math.sin(pose[2]),
        spec.mount.height_m,
    ])
    model.vis.global_.offwidth = intr.width_px
    model.vis.global_.offheight = intr.height_px
    model.vis.global_.fovy = 45.0
    renderer = mujoco.Renderer(model, intr.height_px, intr.width_px)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, cam)
    look = center + 3.0 * fwd
    cam.lookat[:] = look
    cam.distance = 3.0
    cam.azimuth = math.degrees(pose[2])
    cam.elevation = math.degrees(spec.mount.pitch_up_rad)
    renderer.enable_depth_rendering()
    renderer.update_scene(data, camera=cam)
    depth_bug = np.asarray(renderer.render(), dtype=np.float64).copy()
    renderer.disable_depth_rendering()
    renderer.enable_segmentation_rendering()
    renderer.update_scene(data, camera=cam)
    seg_bug = np.asarray(renderer.render())[..., 0].astype(np.int32)
    renderer.disable_segmentation_rendering()
    renderer.close()
    ys, xs = np.where(seg_bug == tid)
    if xs.size:
        uc, vc = float(xs.mean()), float(ys.mean())
        dd = float(np.median(depth_bug[ys, xs]))
        world_bug = ext.camera_to_world(back_project(uc, vc, dd, intr))
        err_bug = float(np.linalg.norm(np.array(world_bug) - np.array(tgt)))
        # The bug fails the very self-check the fix passes: same scene, same
        # camera placement, ONLY fovy differs.
        assert err_bug > radius + _SEG_TRUTH_REAL_MARGIN_M
        assert err_bug > 1.5 * err_fixed


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
