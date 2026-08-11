"""Additive V-B cells for D1 confirmation and D2 metric fusion.

This standalone report consumes the existing frozen camera-foundation pack but
does not modify it or wire either pure module into the mission runtime.

Two cells live here and they prove different things. Read the ``tier_id``:

``evaluate_cells()`` — ``T-cam-proxy-vb-pure``
    A **pure-module unit result on a synthetic score sequence**. The detector is
    :class:`SegTruthDetector` (recognition perfect by construction) and the
    scores fed to the confirmer are a hardcoded literal, not a recording. It
    proves the confirmer's arithmetic; it proves nothing about any detector
    operating point.

``evaluate_live_cells()`` — ``T-cam-proxy-vb-live`` (opt-in: EGL + OWLv2 weights)
    The **real OWLv2 detector at a real operating point** on live MuJoCo-EGL
    renders from several distinct camera poses. Scores here are recorded, not
    written down in advance, and ``PARCEL_OWLV2_THRESHOLD`` is genuinely
    exercised: the cell runs the detector at each requested threshold.

Naming: ``T-cam-proxy-*`` is a **card-local report label, not a registered
perception tier**. ``PerceptionChain.from_tier`` knows only ``T0`` and ``T1``
(see :data:`~parcel_robot.detection_adapter.perception_chain.REGISTERED_TIERS`),
so nothing in these cells runs through the tier seam the nav_instruct harness
installs. Fable's independent audit of task_15 returned every "T-cam" row for
exactly this reason; the ``-proxy-`` infix is the correction.

Usage::

    .parcel/bin/python -m evals.nav_instruct.cam_multiview_metric
    MUJOCO_GL=egl PARCEL_OWLV2_ONNX=1 \\
      .parcel/bin/python -m evals.nav_instruct.cam_multiview_metric --live
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import replace
from typing import Any

from evals.nav_instruct.cam_foundation import load_scenes, render_scene
from parcel_robot.camera_channel.d455 import d455_color_intrinsics
from parcel_robot.detection_adapter.metric_localizer import MetricLocalizer
from parcel_robot.detection_adapter.multi_view_confirm import (
    MultiViewConfig,
    MultiViewConfirm,
)
from parcel_robot.detection_adapter.pixel_detections import (
    SegTruthDetector,
    localize_frame,
)

TIER_ID = "T-cam-proxy-vb-pure"
LIVE_TIER_ID = "T-cam-proxy-vb-live"
DOES_NOT_PROVE = (
    (
        "These additive cells prove pure M-of-N/FP-memory and seg-truth metric "
        "fusion properties; they do not prove runtime false-positive arrival."
    ),
    (
        "Seg-truth recognition is perfect by construction and does not prove "
        "open-vocabulary recognition on real D455 imagery."
    ),
    (
        "Runtime camera wiring, K0 arrival, and full absent-target episodes are "
        "owned by Wave-2 V-E and remain deferred."
    ),
    (
        "'T-cam-proxy-*' is a report label, not a registered perception tier: "
        "PerceptionChain.from_tier knows only T0/T1, so no cell here runs "
        "through the tier seam the nav_instruct harness installs."
    ),
    (
        "operating_scores in the pure cell is a HARDCODED synthetic sequence, "
        "not a recording. It exercises the confirmer's arithmetic and says "
        "nothing about any detector threshold; evaluate_live_cells() is the "
        "cell that actually runs the detector at an operating point."
    ),
    (
        "false_positive_commits in the pure cell is ARITHMETICALLY GUARANTEED "
        "to be 0: each phantom gets one update() against a fresh 3-of-5 "
        "confirmer, and one view can never satisfy 3-of-5. It is a "
        "single-frame-rejection assertion, not a false-positive measurement. "
        "The measured one is live_absent_class_commits / "
        "live_repeated_phantom_commits in evaluate_live_cells()."
    ),
)


def evaluate_cells() -> dict[str, Any]:
    """Pure-module unit result on a SYNTHETIC score sequence (no detector).

    Deliberately unchanged in value from the row V-B published, so the two are
    comparable; what changed is that the report now states what it is.
    """

    scores = (0.28, 0.35, 0.42)
    intrinsics = d455_color_intrinsics()
    localization_errors: list[float] = []
    confirmations = 0
    single_frame_commits = 0
    low_viewpoint_scenes = 0

    for scene_index, scene in enumerate(load_scenes()):
        seg, depth = render_scene(scene, intrinsics)
        localized = localize_frame(
            SegTruthDetector(scene.id_to_label()),
            rgb=None,
            depth=depth,
            seg=seg,
            query=scene.query,
            intrinsics=intrinsics,
            extrinsics=scene.extrinsics(),
            source_timestamp_ns=1,
            received_monotonic_ns=1,
            sequence=scene_index,
            depth_max_m=1000.0,
        )
        target = next(target for target in scene.targets if target.is_query)
        observation = next(item for item in localized if item.seg_id == target.seg_id)

        confirmer = MultiViewConfirm()
        localizer = MetricLocalizer()
        for offset, score in enumerate(scores):
            timestamp = 10_000 * (scene_index + 1) + offset
            envelope = replace(
                observation.message.envelope,
                evidence_id=f"vb-{scene_index}-{offset}",
                source_timestamp_ns=timestamp,
                received_monotonic_ns=timestamp,
                sequence=offset,
                expires_monotonic_ns=timestamp + 1_000_000,
            )
            message = replace(observation.message, envelope=envelope, score=score)
            confirmed, _, _ = confirmer.update(message)
            if offset == 0:
                single_frame_commits += int(confirmed)
            estimate = localizer.update_localized(
                observation,
                camera_x=scene.extrinsics().translation[0],
                camera_y=scene.extrinsics().translation[1],
            )
        confirmations += int(confirmed)
        assert estimate is not None
        low_viewpoint_scenes += int(estimate.low_viewpoint_seen)
        localization_errors.append(
            math.hypot(
                estimate.position[0] - target.position[0],
                estimate.position[1] - target.position[1],
            )
        )

    # Absent-target/FP cell: each phantom appears in only one view and is then
    # finalized into memory. Re-observation on the next scan stays suppressed.
    template_scene = load_scenes()[0]
    seg, depth = render_scene(template_scene, intrinsics)
    template = localize_frame(
        SegTruthDetector(template_scene.id_to_label()),
        rgb=None,
        depth=depth,
        seg=seg,
        query=template_scene.query,
        intrinsics=intrinsics,
        extrinsics=template_scene.extrinsics(),
        source_timestamp_ns=1,
        received_monotonic_ns=1,
        depth_max_m=1000.0,
    )[0].message
    false_positive_commits = 0
    remembered_rejections = 0
    suppressed_recommits = 0
    for index in range(12):
        confirmer = MultiViewConfirm()
        phantom = replace(
            template,
            envelope=replace(
                template.envelope,
                evidence_id=f"phantom-{index}",
                source_timestamp_ns=100_000 + index,
                received_monotonic_ns=100_000 + index,
                sequence=index,
                expires_monotonic_ns=2_000_000,
            ),
            class_id="absent_target",
            score=0.99,
            track_id=f"phantom-{index}",
        )
        false_positive_commits += int(confirmer.update(phantom)[0])
        for _ in range(5):
            _, _, rejected = confirmer.update(None)
        remembered_rejections += int(phantom.track_id in rejected)
        recommit = confirmer.update(
            replace(
                phantom,
                envelope=replace(
                    phantom.envelope,
                    evidence_id=f"phantom-rescan-{index}",
                    source_timestamp_ns=200_000 + index,
                    received_monotonic_ns=200_000 + index,
                ),
            )
        )
        suppressed_recommits += int(not recommit[0] and recommit[1] == 0.0)

    ordered = sorted(localization_errors)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "tier_id": TIER_ID,
        "cell_kind": "pure_module_synthetic_sequence",
        "detector": "SegTruthDetector (recognition perfect by construction)",
        "operating_scores_are_synthetic": True,
        "false_positive_commits_is_arithmetic": True,
        "scene_count": len(localization_errors),
        "operating_scores": list(scores),
        "confirmed_scenes": confirmations,
        "low_viewpoint_scenes": low_viewpoint_scenes,
        "single_frame_commits": single_frame_commits,
        "false_positive_commits": false_positive_commits,
        "remembered_rejections": remembered_rejections,
        "suppressed_recommits": suppressed_recommits,
        "localization_error_m": {
            "max_m": max(ordered),
            "mean_m": sum(ordered) / len(ordered),
            "p95_m": ordered[p95_index],
        },
        "does_not_prove": list(DOES_NOT_PROVE),
    }


# ---------------------------------------------------------------------------
# LIVE cell — the real detector at a real operating point (opt-in)
# ---------------------------------------------------------------------------

#: The lamppost prop from the B4 gate rig (scrum/20260809/task_12/b4_gate.py).
#: Reused verbatim because it is the object V-B's headline was written about:
#: OWLv2 scores it BELOW the unmodified 0.55 grounder floor on most views, which
#: is precisely the case a multi-view confirmer is supposed to rescue.
_LAMPPOST_GEOMS = (
    '<geom name="lamp_pole" type="cylinder" size="0.16 1.3" pos="0 0 1.3" '
    'rgba="0.12 0.12 0.14 1"/>'
    '<geom name="lamp_head" type="box" size="0.28 0.16 0.14" pos="0 0 2.72" '
    'rgba="0.98 0.94 0.55 1"/>'
)
_LAMPPOST_XY = (3.2, 1.0)
#: Camera poses: an ORBIT at fixed stand-off, each pose facing the lamppost.
#: Distinct azimuths are what makes these distinct views; holding stand-off and
#: heading constant keeps camera-frame bearing/range inside the confirmer's
#: association gate, which is a frame-relative gate by design.
_ORBIT_RADIUS_M = 3.0
_ORBIT_AZIMUTHS_DEG = (-40.0, -20.0, 0.0, 20.0, 40.0)
#: Query for a class that is NOT in the scene. Every box it returns is, by
#: construction, a false positive — no annotation or judgement required.
_ABSENT_CLASS_QUERY = "fire hydrant"
#: Operating points actually run. 0.2 is the lowered point V-B's headline was
#: about; 0.55 is the UNMODIFIED grounder ``minimum_confidence`` this rig's
#: single-frame path uses, i.e. the control.
LIVE_THRESHOLDS: tuple[float, ...] = (0.2, 0.55)

LIVE_DOES_NOT_PROVE = (
    (
        "Rendered MuJoCo pixels are NOT photoreal. These scores are a FLOOR of "
        "recognition on a synthetic prop, not D455 field recall/precision."
    ),
    (
        "One object, one orbit, five views. This is an operating-point probe, "
        "not a precision/recall curve over a labelled set."
    ),
    (
        "The absent-class cell measures whether THIS detector hallucinates THIS "
        "class on THIS prop. Zero commits there is a detector-precision "
        "observation on one scene, not a false-positive rate."
    ),
    (
        "The repeated-phantom cell is an INJECTED view-consistent hypothesis. "
        "It is the honest counter-example to any 'M-of-N makes FP=0' reading: "
        "finite-window M-of-N cannot reject a phantom that keeps being "
        "re-observed. IPDA/existence-probability remains unimplemented."
    ),
    (
        "'T-cam-proxy-vb-live' is a report label, not a registered perception "
        "tier, and none of this is wired into the mission runtime."
    ),
)


def _lamppost_xml() -> str:
    x, y = _LAMPPOST_XY
    return (
        '<mujoco><worldbody><light pos="0 0 6"/>'
        '<geom name="ground" type="plane" size="40 40 0.1" rgba="0.72 0.72 0.75 1"/>'
        f'<body name="target" pos="{x} {y} 0">{_LAMPPOST_GEOMS}</body>'
        "</worldbody></mujoco>"
    )


def _orbit_poses() -> list[tuple[float, float, float]]:
    """(x, y, yaw) for each view: on a circle of radius R, facing the lamppost."""

    x, y = _LAMPPOST_XY
    poses = []
    for degrees in _ORBIT_AZIMUTHS_DEG:
        azimuth = math.radians(degrees)
        poses.append(
            (
                x - _ORBIT_RADIUS_M * math.cos(azimuth),
                y - _ORBIT_RADIUS_M * math.sin(azimuth),
                azimuth,
            )
        )
    return poses


def _live_blocker() -> str | None:
    """The precise reason the live cell cannot run, or ``None`` when it can."""

    from parcel_robot.detection_adapter.owlv2_onnx import (
        onnx_enabled,
        owlv2_weights_present,
    )

    if not owlv2_weights_present():
        return "OWLv2 weights absent — run scripts/fetch_owlv2.sh"
    if not onnx_enabled():
        return "PARCEL_OWLV2_ONNX not set — opt-in detector gate is off"
    if os.environ.get("MUJOCO_GL", "").strip().lower() not in {"egl", "osmesa"}:
        return "MUJOCO_GL is not an offscreen backend (set MUJOCO_GL=egl)"
    return None


def _observe_view(
    confirmer: MultiViewConfirm,
    *,
    detector: Any,
    query: str,
    frame: dict[str, Any],
) -> dict[str, Any]:
    """One query against one rendered view, fed to ``confirmer``."""

    localized = localize_frame(
        detector,
        rgb=frame["rgb"],
        depth=frame["depth"],
        seg=None,
        query=query,
        intrinsics=frame["intrinsics"],
        extrinsics=frame["extrinsics"],
        source_timestamp_ns=frame["timestamp"],
        received_monotonic_ns=frame["timestamp"],
        sequence=frame["index"],
        depth_max_m=1000.0,
    )
    if not localized:
        # An explicit empty view — the contract's own requirement for a miss to
        # count toward rejection.
        confirmer.update(None)
        return {"boxes": 0, "scores": [], "confirmed": False, "credibility": 0.0}
    confirmed = False
    credibility = 0.0
    for item in localized:
        hit, cred, _ = confirmer.update(item.message)
        confirmed = confirmed or bool(hit)
        credibility = max(credibility, float(cred))
    return {
        "boxes": len(localized),
        "scores": [round(float(i.message.score), 4) for i in localized],
        "bearing_rad": [round(float(i.message.bearing_rad), 4) for i in localized],
        "range_m": [round(float(i.message.range_m), 3) for i in localized],
        "confirmed": confirmed,
        "credibility": round(credibility, 5),
        "first_message": localized[0].message,
    }


def _run_threshold(threshold: float, *, spec: Any, model: Any, data: Any) -> dict[str, Any]:
    import numpy as np

    from parcel_robot.camera_channel.backends.mujoco_egl import MujocoEglCameraBackend
    from parcel_robot.detection_adapter.owlv2_onnx import load_owlv2_detector
    from parcel_robot.detection_adapter.pixel_detections import CameraExtrinsics

    detector = load_owlv2_detector(threshold=threshold)
    if detector is None:
        return {"threshold": threshold, "status": "skipped",
                "blocker": "OWLv2 detector failed to load (see log)"}

    present = MultiViewConfirm()
    absent = MultiViewConfirm()
    phantom_confirmer = MultiViewConfirm()
    config = MultiViewConfig()

    backend = MujocoEglCameraBackend(model, data, spec=spec, class_ids=("bg", "obj"))
    views: list[dict[str, Any]] = []
    present_scores: list[float] = []
    absent_boxes = 0
    present_confirm_view: int | None = None
    absent_confirm_view: int | None = None
    phantom_confirm_view: int | None = None
    try:
        for index, (x, y, yaw) in enumerate(_orbit_poses()):
            timestamp = 1_000_000 + index
            backend.capture(
                source_timestamp_ns=timestamp, sequence=index,
                robot_x=x, robot_y=y, robot_yaw_rad=yaw,
            )
            buffers = backend.last_buffers
            if buffers is None or buffers.color_rgb8 is None:
                raise RuntimeError("EGL backend produced no colour buffer")
            rgb = np.asarray(buffers.color_rgb8)
            depth = np.asarray(buffers.depth_m_f32, dtype=np.float64)
            extrinsics = CameraExtrinsics.from_mount_pose(
                robot_x=x, robot_y=y, robot_yaw_rad=yaw, mount=spec.mount
            )

            frame = {
                "rgb": rgb,
                "depth": depth,
                "intrinsics": spec.intrinsics,
                "extrinsics": extrinsics,
                "timestamp": timestamp,
                "index": index,
            }
            lamppost = _observe_view(
                present, detector=detector, query="lamppost", frame=frame
            )
            hydrant = _observe_view(
                absent, detector=detector, query=_ABSENT_CLASS_QUERY, frame=frame
            )

            # Injected phantom: a hypothesis with NO object behind it, held at a
            # constant bearing/range so it is re-observed across every view. The
            # point is to show what finite-window M-of-N does with a persistent
            # hallucination, which the single-update pure cell cannot show.
            phantom_hit = False
            phantom_cred = 0.0
            sample = lamppost.pop("first_message", None)
            hydrant.pop("first_message", None)
            if sample is not None:
                phantom = replace(
                    sample,
                    class_id="absent_target",
                    track_id="",
                    score=0.42,
                    bearing_rad=0.0,
                    range_m=4.0,
                )
                phantom_hit, phantom_cred, _ = phantom_confirmer.update(phantom)
            else:
                phantom_confirmer.update(None)

            present_scores.extend(lamppost["scores"])
            absent_boxes += int(hydrant["boxes"])
            if lamppost["confirmed"] and present_confirm_view is None:
                present_confirm_view = index
            if hydrant["confirmed"] and absent_confirm_view is None:
                absent_confirm_view = index
            if phantom_hit and phantom_confirm_view is None:
                phantom_confirm_view = index
            views.append({
                "view": index,
                "pose_xy_yaw": [round(x, 4), round(y, 4), round(yaw, 4)],
                "lamppost": lamppost,
                "absent_class": hydrant,
                "injected_phantom": {
                    "confirmed": bool(phantom_hit),
                    "credibility": round(float(phantom_cred), 5),
                },
            })
    finally:
        backend.close()

    survive = [score for score in present_scores if score >= threshold]
    return {
        "threshold": threshold,
        "status": "measured",
        "views": views,
        "distinct_views": len(views),
        # RECORDED, not written down in advance. This is the artifact the pure
        # cell's `operating_scores` literal was standing in for.
        "recorded_lamppost_scores": present_scores,
        "lamppost_views_with_a_box": sum(1 for v in views if v["lamppost"]["boxes"]),
        "lamppost_scores_at_or_above_threshold": len(survive),
        "lamppost_confirmed": present_confirm_view is not None,
        "lamppost_confirm_view_index": present_confirm_view,
        "confirm_policy": f"{config.confirm_hits}-of-{config.confirm_window}",
        # MEASURED false positives: the class is absent from the scene, so every
        # box is a false positive and every commit is a false-positive commit.
        "absent_class_query": _ABSENT_CLASS_QUERY,
        "absent_class_boxes_total": absent_boxes,
        "live_absent_class_commits": int(absent_confirm_view is not None),
        # MEASURED counter-example: a view-consistent phantom DOES commit.
        "live_repeated_phantom_commits": int(phantom_confirm_view is not None),
        "repeated_phantom_confirm_view_index": phantom_confirm_view,
    }


def evaluate_live_cells(
    thresholds: tuple[float, ...] = LIVE_THRESHOLDS,
) -> dict[str, Any]:
    """Run the REAL OWLv2 detector at each operating point on live EGL renders.

    Returns ``{"status": "skipped", "blocker": ...}`` when EGL or the weights are
    unavailable, so this never reddens a machine without them.
    """

    blocker = _live_blocker()
    if blocker is not None:
        return {"tier_id": LIVE_TIER_ID, "status": "skipped", "blocker": blocker}

    import mujoco

    from parcel_robot.camera_channel.channel import CameraChannelSpec

    spec = CameraChannelSpec.d455_go2_nominal()
    model = mujoco.MjModel.from_xml_string(_lamppost_xml())
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    per_threshold = [
        _run_threshold(float(t), spec=spec, model=model, data=data) for t in thresholds
    ]
    return {
        "tier_id": LIVE_TIER_ID,
        "status": "measured",
        "cell_kind": "live_owlv2_multi_view_orbit",
        "scene": "b4_gate lamppost prop, MuJoCo-EGL render",
        "orbit_radius_m": _ORBIT_RADIUS_M,
        "orbit_azimuths_deg": list(_ORBIT_AZIMUTHS_DEG),
        "grounder_minimum_confidence": 0.55,
        "thresholds": [float(t) for t in thresholds],
        "per_threshold": per_threshold,
        "does_not_prove": list(LIVE_DOES_NOT_PROVE),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="also run the live OWLv2 operating-point cell (needs EGL + weights)",
    )
    args = parser.parse_args()
    payload: dict[str, Any] = {"pure": evaluate_cells()}
    if args.live:
        payload["live"] = evaluate_live_cells()
    print(json.dumps(payload if args.live else payload["pure"], indent=2, sort_keys=True))
