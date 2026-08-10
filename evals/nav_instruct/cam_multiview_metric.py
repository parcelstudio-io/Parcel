"""Additive T-cam V-B cells for D1 confirmation and D2 metric fusion.

This standalone report consumes the existing frozen camera-foundation pack but
does not modify it or wire either pure module into the mission runtime.

Usage: ``.parcel/bin/python -m evals.nav_instruct.cam_multiview_metric``
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from typing import Any

from evals.nav_instruct.cam_foundation import load_scenes, render_scene
from parcel_robot.camera_channel.d455 import d455_color_intrinsics
from parcel_robot.detection_adapter.metric_localizer import MetricLocalizer
from parcel_robot.detection_adapter.multi_view_confirm import MultiViewConfirm
from parcel_robot.detection_adapter.pixel_detections import (
    SegTruthDetector,
    localize_frame,
)

TIER_ID = "T-cam-vb-pure"
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
        "Runtime T-cam wiring, K0 arrival, and full absent-target episodes are "
        "owned by Wave-2 V-E and remain deferred."
    ),
)


def evaluate_cells() -> dict[str, Any]:
    """Return deterministic, JSON-serializable V-B evidence."""

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


if __name__ == "__main__":
    print(json.dumps(evaluate_cells(), indent=2, sort_keys=True))
