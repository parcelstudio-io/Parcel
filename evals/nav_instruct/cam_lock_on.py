"""Additive T-cam V-E cells: D3 lock-on + D4 chance-constrained K0.

Standalone report — does not modify frozen packs or cam_foundation /
cam_detector / cam_arrival / cam_multiview_metric.

Usage::

    .parcel/bin/python -m evals.nav_instruct.cam_lock_on
"""

from __future__ import annotations

import json
import math
from typing import Any

from parcel_robot.instructnav.scoring import (
    INSIDE_PROBABILITY_THRESHOLD,
    AuthorityCategory,
    differential_arrival_verdict,
    object_near_goal_region,
    p_inside_goal_region,
)
from parcel_robot.navigation.detection_lock_on import (
    T_CAM_ORACLE_SR_MARGIN,
    DetectionLockOnSession,
)
from parcel_robot.navigation.semantic_map import SemanticCandidate

TIER_ID = "T-cam-ve-lock-on"
DOES_NOT_PROVE = (
    (
        "Paired-seed lock-on vs oracle SR margin proves detection-triggered "
        "commit machinery, not field open-vocab recognition."
    ),
    (
        "Chance-constrained boundary fuzz is synthetic D2 covariance, not "
        "real D455 depth noise."
    ),
)


def _cand(
    cid: str,
    label: str,
    x: float,
    y: float,
    *,
    score: float,
    sigma_range: float = 0.05,
) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=cid,
        label=label,
        x=x,
        y=y,
        confidence=score,
        kind="object",
        source="pixel_detector",
        metadata={
            "range_m": math.hypot(x, y),
            "bearing_rad": math.atan2(y, x),
            "sigma_range_m": sigma_range,
            "radius_m": 0.06,
        },
    )


def evaluate_cells() -> dict[str, Any]:
    """Deterministic JSON-serializable V-E evidence."""

    n = 16
    oracle_ok = 0
    lock_ok = 0
    for seed in range(n):
        oracle_ok += 1
        session = DetectionLockOnSession()
        decision = None
        for view in range(3):
            decision = session.observe_candidate(
                query="lamppost",
                candidate=_cand(
                    f"lamp-{seed}",
                    "lamppost",
                    2.5 + 0.02 * seed,
                    0.05 * (seed % 4),
                    score=0.28 + 0.07 * view,
                ),
                robot_xy=(0.0, 0.0),
                now_ns=10_000 * (seed + 1) + view,
            )
        if decision is not None:
            lock_ok += 1
    sr_oracle = oracle_ok / n
    sr_lock = lock_ok / n
    sr_gap = abs(sr_lock - sr_oracle)

    # D4: T0 byte-equal (zero cov) + boundary fuzz under wide cov.
    region = object_near_goal_region((0.0, 0.0), 0.06, label="lamppost")
    lo, hi = region.band_m
    assert lo is not None and hi is not None
    mid = 0.5 * (lo + hi)
    zero_cov_inside = region.contains(mid, 0.0, anchor_covariance=((0.0, 0.0), (0.0, 0.0)))
    bool_inside = region.contains(mid, 0.0)
    t0_byte_equal = zero_cov_inside is bool_inside is True

    edge_xy = (float(hi), 0.0)
    wide = ((0.25, 0.0), (0.0, 0.25))
    edge_prob = p_inside_goal_region(*edge_xy, region, anchor_covariance=wide)
    edge_refused = not region.contains(
        *edge_xy,
        anchor_covariance=wide,
        probability_threshold=INSIDE_PROBABILITY_THRESHOLD,
    )

    # Differential authority: absent-target (robot at origin) must not false_arrive.
    fp_false_arrivals = 0
    for episode in range(8):
        session = DetectionLockOnSession()
        d = session.observe_candidate(
            query="bench",
            candidate=_cand(f"fp-{episode}", "tree", 6.0, 0.0, score=0.99),
            robot_xy=(0.0, 0.0),
            now_ns=episode + 1,
        )
        if d is not None:
            fp_false_arrivals += 1
        verdict = differential_arrival_verdict(
            object_near_goal_region((6.0, 0.0), 0.5, label="tree"),
            (0.0, 0.0),
            system_arrival=False,
        )
        if verdict.category == AuthorityCategory.FALSE_ARRIVAL:
            fp_false_arrivals += 1

    return {
        "tier_id": TIER_ID,
        "does_not_prove": list(DOES_NOT_PROVE),
        "scenes": n,
        "sr_oracle": sr_oracle,
        "sr_lock_on": sr_lock,
        "sr_gap": sr_gap,
        "t_cam_oracle_sr_margin": T_CAM_ORACLE_SR_MARGIN,
        "sr_within_margin": sr_gap <= T_CAM_ORACLE_SR_MARGIN,
        "t0_byte_equal_zero_covariance": t0_byte_equal,
        "boundary_fuzz_edge_probability": edge_prob,
        "boundary_fuzz_edge_refused": edge_refused,
        "false_positive_lock_commits": fp_false_arrivals,
        "inside_probability_threshold": INSIDE_PROBABILITY_THRESHOLD,
    }


def main() -> None:
    report = evaluate_cells()
    print(json.dumps(report, indent=2, sort_keys=True))
    assert report["sr_within_margin"], report
    assert report["t0_byte_equal_zero_covariance"], report
    assert report["boundary_fuzz_edge_refused"], report
    assert report["false_positive_lock_commits"] == 0, report


if __name__ == "__main__":
    main()
