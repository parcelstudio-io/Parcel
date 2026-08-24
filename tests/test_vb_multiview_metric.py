"""Card V-B: D1 multi-view evidence and D2 metric-fusion gates."""

from __future__ import annotations

import math

import pytest

from evals.nav_instruct.cam_multiview_metric import evaluate_cells
from parcel_robot.contracts.freshness import expires_from_ttl
from parcel_robot.contracts.v1 import SCHEMA_VERSION, DetectionMsg, EvidenceEnvelopeV1
from parcel_robot.detection_adapter.metric_localizer import (
    MetricLocalizer,
    MetricMeasurement,
)
from parcel_robot.detection_adapter.multi_view_confirm import MultiViewConfirm


def _detection(
    view: int,
    *,
    score: float,
    track_id: str = "lamp-1",
    class_id: str = "lamppost",
    bearing: float = 0.1,
    range_m: float = 4.0,
) -> DetectionMsg:
    timestamp = 1_000_000 + view
    envelope = EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=f"det-{view}-{track_id}",
        source="test.pixel",
        source_timestamp_ns=timestamp,
        received_monotonic_ns=timestamp,
        sequence=view,
        frame_id="base_link",
        scene_revision=0,
        expires_monotonic_ns=expires_from_ttl(
            received_monotonic_ns=timestamp, ttl_ns=1_000_000
        ),
        calibration_id="test-cal",
        provenance=("test",),
    )
    return DetectionMsg(
        envelope=envelope,
        class_id=class_id,
        embedding=(0.1, 0.2),
        bearing_rad=bearing,
        range_m=range_m,
        score=score,
        track_id=track_id,
    )


def test_lamppost_operating_scores_accumulate_without_per_class_gate() -> None:
    confirmer = MultiViewConfirm()
    outputs = [
        confirmer.update(_detection(view, score=score))
        for view, score in enumerate((0.28, 0.35, 0.42), start=1)
    ]
    assert [confirmed for confirmed, _, _ in outputs] == [False, False, True]
    # Noisy-OR finite-view credibility: 1 - (1-.28)(1-.35)(1-.42).
    assert outputs[-1][1] == pytest.approx(0.72856)
    assert outputs[-1][2] == ()


def test_single_frame_never_commits_even_at_score_one() -> None:
    confirmer = MultiViewConfirm()
    confirmed, credibility, _ = confirmer.update(_detection(1, score=1.0))
    assert not confirmed
    assert credibility == 1.0
    for _ in range(4):
        confirmed, _, _ = confirmer.update(None)
        assert not confirmed


def test_three_of_five_tolerates_two_missed_views() -> None:
    confirmer = MultiViewConfirm()
    assert not confirmer.update(_detection(1, score=0.5))[0]
    assert not confirmer.update(None)[0]
    assert not confirmer.update(_detection(3, score=0.5))[0]
    assert not confirmer.update(None)[0]
    confirmed, credibility, _ = confirmer.update(_detection(5, score=0.5))
    assert confirmed
    assert credibility == pytest.approx(0.875)


def test_duplicate_boxes_in_one_view_are_one_witness() -> None:
    confirmer = MultiViewConfirm()
    first = _detection(1, score=0.9)
    assert not confirmer.update(first)[0]
    assert not confirmer.update(first)[0]
    assert not confirmer.update(_detection(2, score=0.9))[0]
    assert confirmer.update(_detection(3, score=0.9))[0]


def test_rejected_false_positive_is_suppressed_on_next_scan() -> None:
    confirmer = MultiViewConfirm()
    assert not confirmer.update(
        _detection(1, score=0.99, track_id="phantom-7", class_id="hydrant")
    )[0]
    # Complete a 1-of-5 history, then open the next view to finalize rejection.
    for _ in range(5):
        _, _, rejected = confirmer.update(None)
    assert rejected == ("phantom-7",)

    confirmed, credibility, rejected = confirmer.update(
        _detection(20, score=1.0, track_id="phantom-7", class_id="hydrant")
    )
    assert not confirmed
    assert credibility == 0.0
    assert rejected == ("phantom-7",)


def _measurement(
    x: float,
    y: float,
    *,
    variance: float = 0.04,
    low_viewpoint: bool = False,
) -> MetricMeasurement:
    return MetricMeasurement(
        x=x,
        y=y,
        covariance=((variance, 0.0), (0.0, variance)),
        low_viewpoint=low_viewpoint,
    )


def test_static_kalman_fuse_reduces_covariance_and_error() -> None:
    localizer = MetricLocalizer()
    first = localizer.update(_measurement(4.2, 1.8))
    assert first is not None
    fused = localizer.update(_measurement(3.8, 2.2))
    assert fused is not None
    assert fused.position == pytest.approx((4.0, 2.0), abs=1e-6)
    assert fused.covariance[0][0] < first.covariance[0][0]
    assert fused.covariance[1][1] < first.covariance[1][1]
    assert fused.measurement_count == 2
    assert fused.mode == "depth"


def test_fusion_is_equivariant_under_planar_rigid_transform() -> None:
    base = [_measurement(2.8, 1.1, variance=0.03), _measurement(3.2, 0.9, variance=0.05)]
    original = MetricLocalizer()
    for measurement in base:
        estimate = original.update(measurement)
    assert estimate is not None

    angle, tx, ty = 0.7, -1.2, 2.4
    c, s = math.cos(angle), math.sin(angle)

    def point(x: float, y: float) -> tuple[float, float]:
        return (c * x - s * y + tx, s * x + c * y + ty)

    def covariance(value):
        r = ((c, -s), (s, c))
        rp = (
            (
                r[0][0] * value[0][0] + r[0][1] * value[1][0],
                r[0][0] * value[0][1] + r[0][1] * value[1][1],
            ),
            (
                r[1][0] * value[0][0] + r[1][1] * value[1][0],
                r[1][0] * value[0][1] + r[1][1] * value[1][1],
            ),
        )
        return (
            (
                rp[0][0] * r[0][0] + rp[0][1] * r[0][1],
                rp[0][0] * r[1][0] + rp[0][1] * r[1][1],
            ),
            (
                rp[1][0] * r[0][0] + rp[1][1] * r[0][1],
                rp[1][0] * r[1][0] + rp[1][1] * r[1][1],
            ),
        )

    transformed = MetricLocalizer()
    for measurement in base:
        px, py = point(measurement.x, measurement.y)  # type: ignore[arg-type]
        transformed_estimate = transformed.update(
            MetricMeasurement(
                x=px,
                y=py,
                covariance=covariance(measurement.covariance),
            )
        )
    assert transformed_estimate is not None
    assert transformed_estimate.position == pytest.approx(point(*estimate.position), abs=1e-7)
    expected_covariance = covariance(estimate.covariance)
    for actual_row, expected_row in zip(
        transformed_estimate.covariance, expected_covariance, strict=True
    ):
        assert actual_row == pytest.approx(expected_row, abs=1e-8)


def test_motion_parallax_runs_only_for_unreliable_depth() -> None:
    target = (4.0, 2.0)
    localizer = MetricLocalizer()
    first = MetricMeasurement(
        x=None,
        y=None,
        covariance=None,
        depth_reliable=False,
        camera_x=0.0,
        camera_y=0.0,
        world_bearing_rad=math.atan2(target[1], target[0]),
    )
    second = MetricMeasurement(
        x=None,
        y=None,
        covariance=None,
        depth_reliable=False,
        camera_x=1.0,
        camera_y=0.0,
        world_bearing_rad=math.atan2(target[1], target[0] - 1.0),
    )
    assert localizer.update(first) is None
    estimate = localizer.update(second)
    assert estimate is not None
    assert estimate.position == pytest.approx(target, abs=1e-9)
    assert estimate.mode == "parallax"

    depth = MetricLocalizer().update(
        MetricMeasurement(
            x=4.1,
            y=2.0,
            covariance=((0.01, 0.0), (0.0, 0.01)),
            depth_reliable=True,
            camera_x=0.0,
            camera_y=0.0,
            world_bearing_rad=math.atan2(2.0, 4.1),
        )
    )
    assert depth is not None and depth.mode == "depth"


def test_low_viewpoint_is_visible_and_inflates_covariance() -> None:
    normal = MetricLocalizer().update(_measurement(3.0, 1.0))
    low = MetricLocalizer().update(_measurement(3.0, 1.0, low_viewpoint=True))
    assert normal is not None and low is not None
    assert low.low_viewpoint_seen
    assert low.covariance[0][0] > normal.covariance[0][0] * 3.9


def test_additive_tcam_cells_prove_vb_properties() -> None:
    report = evaluate_cells()
    assert report["confirmed_scenes"] == report["scene_count"]
    assert report["single_frame_commits"] == 0
    assert report["false_positive_commits"] == 0
    assert report["remembered_rejections"] == 12
    assert report["suppressed_recommits"] == 12
    assert report["low_viewpoint_scenes"] > 0
    assert report["localization_error_m"]["p95_m"] < 0.02
    assert report["does_not_prove"]
