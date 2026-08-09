"""SLIM-2: compound placement+posture and owner-anchored arrival predicates.

These are the pure halves of the NAV_E2E slim plan. They exist so the
product-path e2e cases in ``tests/test_voice_nav_e2e.py`` score "sit next to
the bench" and "go to the owner" against the same K0 arrival authority the
NAV_INSTRUCT loop uses, instead of inventing a second set of radii.

Two properties matter most and are tested explicitly:

* every gate is reported separately, so a failure is attributable (a run that
  reaches the band but never sits must not look like a navigation failure);
* facing is measured but does **not** gate success in v1, and an unknown
  facing is ``None``, never a silent ``False``.
"""

from __future__ import annotations

import math

import pytest

from parcel_robot.instructnav.scoring import (
    FACING_TOLERANCE_RAD,
    NEXT_TO_BAND_M,
    OWNER_ARRIVAL_RADIUS_M,
    evaluate_owner_arrival,
    evaluate_sit_next_to,
    is_sit_posture,
    next_to_band_from_centre,
    object_next_to_goal_region,
    orbit_revolutions,
    owner_anchored_band_goal_region,
    owner_anchored_goal_region,
    swept_angle_rad,
)

BENCH_XY = (-2.5, 3.0)
BENCH_FOOTPRINT_M = 0.7
OWNER_XY = (2.0, -0.5)


def _beside_bench() -> tuple[float, float]:
    """A point inside the bench next-to band (south side, on the sidewalk).

    The band is measured to the anchor's SURFACE (card S-1, 2026-08-09), so it
    is materialised through the one definition rather than read off
    ``NEXT_TO_BAND_M`` directly — a test that recomputed the band by hand would
    be the second authority this module exists to prevent.
    """

    lo, hi = next_to_band_from_centre(BENCH_FOOTPRINT_M)
    radius = lo + 0.15
    assert radius <= hi
    return (BENCH_XY[0], BENCH_XY[1] - radius)


# --------------------------------------------------------------------------
# posture normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["sit", "Sit", "SIT", "sit_down", " sitting "])
def test_sit_posture_aliases_normalise(value: str) -> None:
    assert is_sit_posture(value)


@pytest.mark.parametrize("value", [None, "", "stand", "lie_down", "bow", "unknown"])
def test_non_sit_postures_are_rejected(value: str | None) -> None:
    assert not is_sit_posture(value)


# --------------------------------------------------------------------------
# SitNextTo
# --------------------------------------------------------------------------


def test_sit_next_to_succeeds_on_band_plus_posture_plus_settle() -> None:
    outcome = evaluate_sit_next_to(
        robot_xy=_beside_bench(),
        anchor_xy=BENCH_XY,
        anchor_footprint_m=BENCH_FOOTPRINT_M,
        posture="sit",
        settled=True,
    )
    assert outcome.success
    assert outcome.in_next_to_band
    assert outcome.sit_posture
    assert outcome.settled
    assert outcome.distance_to_band_m == pytest.approx(0.0)
    assert outcome.detail == "success"
    # Owner not supplied → facing is unknown, never a silent False.
    assert outcome.facing_owner is None
    assert outcome.facing_gates_success is False


def test_sit_next_to_uses_the_shared_k0_next_to_band() -> None:
    """The predicate must not carry its own radii (single arrival authority)."""

    goal = object_next_to_goal_region(BENCH_XY, BENCH_FOOTPRINT_M)
    for point in [(BENCH_XY[0], BENCH_XY[1] - d) for d in (0.5, 0.9, 1.4, 1.6, 2.5)]:
        outcome = evaluate_sit_next_to(
            robot_xy=point,
            anchor_xy=BENCH_XY,
            anchor_footprint_m=BENCH_FOOTPRINT_M,
            posture="sit",
            settled=True,
        )
        assert outcome.in_next_to_band == goal.contains(point[0], point[1])
        assert outcome.distance_to_band_m == pytest.approx(
            goal.distance_to(point[0], point[1])
        )


def test_sit_next_to_inside_the_anchor_footprint_is_not_next_to() -> None:
    outcome = evaluate_sit_next_to(
        robot_xy=(BENCH_XY[0], BENCH_XY[1] - 0.2),
        anchor_xy=BENCH_XY,
        anchor_footprint_m=BENCH_FOOTPRINT_M,
        posture="sit",
        settled=True,
    )
    assert not outcome.success
    assert not outcome.in_next_to_band
    assert outcome.detail == "outside_next_to_band"


def test_sit_next_to_attributes_a_posture_miss_separately_from_placement() -> None:
    """Arrived and stopped but standing: a posture gap, not a nav gap."""

    outcome = evaluate_sit_next_to(
        robot_xy=_beside_bench(),
        anchor_xy=BENCH_XY,
        anchor_footprint_m=BENCH_FOOTPRINT_M,
        posture="stand",
        settled=True,
    )
    assert not outcome.success
    assert outcome.in_next_to_band  # navigation did its job
    assert not outcome.sit_posture
    assert outcome.detail == "sit_posture_not_active"


def test_sit_next_to_attributes_a_settle_miss_separately() -> None:
    outcome = evaluate_sit_next_to(
        robot_xy=_beside_bench(),
        anchor_xy=BENCH_XY,
        anchor_footprint_m=BENCH_FOOTPRINT_M,
        posture="sit",
        settled=False,
    )
    assert not outcome.success
    assert outcome.in_next_to_band
    assert outcome.sit_posture
    assert outcome.detail == "never_settled"


def test_sit_next_to_facing_is_measured_against_the_owner_bearing() -> None:
    spot = _beside_bench()
    bearing = math.atan2(OWNER_XY[1] - spot[1], OWNER_XY[0] - spot[0])

    aligned = evaluate_sit_next_to(
        robot_xy=spot,
        anchor_xy=BENCH_XY,
        anchor_footprint_m=BENCH_FOOTPRINT_M,
        posture="sit",
        settled=True,
        robot_heading_rad=bearing + math.radians(45.0),
        owner_xy=OWNER_XY,
        owner_visible=True,
    )
    assert aligned.facing_owner is True
    assert aligned.heading_error_rad == pytest.approx(math.radians(45.0))

    turned_away = evaluate_sit_next_to(
        robot_xy=spot,
        anchor_xy=BENCH_XY,
        anchor_footprint_m=BENCH_FOOTPRINT_M,
        posture="sit",
        settled=True,
        robot_heading_rad=bearing + math.pi,
        owner_xy=OWNER_XY,
        owner_visible=True,
    )
    assert turned_away.facing_owner is False
    assert turned_away.heading_error_rad == pytest.approx(math.pi)


def test_sit_next_to_facing_is_report_only_by_default_and_gates_on_request() -> None:
    spot = _beside_bench()
    bearing = math.atan2(OWNER_XY[1] - spot[1], OWNER_XY[0] - spot[0])
    kwargs = {
        "robot_xy": spot,
        "anchor_xy": BENCH_XY,
        "anchor_footprint_m": BENCH_FOOTPRINT_M,
        "posture": "sit",
        "settled": True,
        "robot_heading_rad": bearing + math.pi,
        "owner_xy": OWNER_XY,
        "owner_visible": True,
    }
    report_only = evaluate_sit_next_to(**kwargs)  # type: ignore[arg-type]
    assert report_only.success  # v1 default: a facing miss cannot fail arrival
    assert report_only.facing_owner is False
    assert report_only.facing_gates_success is False
    assert report_only.detail == "success"

    gated = evaluate_sit_next_to(require_facing=True, **kwargs)  # type: ignore[arg-type]
    assert not gated.success
    assert gated.facing_gates_success is True
    assert gated.detail == "not_facing_owner"


def test_sit_next_to_facing_is_unknown_when_the_owner_is_not_visible() -> None:
    outcome = evaluate_sit_next_to(
        robot_xy=_beside_bench(),
        anchor_xy=BENCH_XY,
        anchor_footprint_m=BENCH_FOOTPRINT_M,
        posture="sit",
        settled=True,
        robot_heading_rad=0.0,
        owner_xy=OWNER_XY,
        owner_visible=False,
    )
    assert outcome.facing_owner is None
    assert outcome.heading_error_rad is None
    assert outcome.success


def test_sit_next_to_facing_tolerance_boundary_is_generous() -> None:
    spot = _beside_bench()
    bearing = math.atan2(OWNER_XY[1] - spot[1], OWNER_XY[0] - spot[0])
    just_inside = evaluate_sit_next_to(
        robot_xy=spot,
        anchor_xy=BENCH_XY,
        anchor_footprint_m=BENCH_FOOTPRINT_M,
        posture="sit",
        settled=True,
        robot_heading_rad=bearing + FACING_TOLERANCE_RAD - 1e-6,
        owner_xy=OWNER_XY,
        owner_visible=True,
    )
    just_outside = evaluate_sit_next_to(
        robot_xy=spot,
        anchor_xy=BENCH_XY,
        anchor_footprint_m=BENCH_FOOTPRINT_M,
        posture="sit",
        settled=True,
        robot_heading_rad=bearing + FACING_TOLERANCE_RAD + 1e-3,
        owner_xy=OWNER_XY,
        owner_visible=True,
    )
    assert FACING_TOLERANCE_RAD == pytest.approx(math.radians(60.0))
    assert just_inside.facing_owner is True
    assert just_outside.facing_owner is False


def test_sit_next_to_is_pure() -> None:
    kwargs = {
        "robot_xy": _beside_bench(),
        "anchor_xy": BENCH_XY,
        "anchor_footprint_m": BENCH_FOOTPRINT_M,
        "posture": "sit",
        "settled": True,
    }
    first = evaluate_sit_next_to(**kwargs)  # type: ignore[arg-type]
    second = evaluate_sit_next_to(**kwargs)  # type: ignore[arg-type]
    assert first == second
    assert first.as_dict() == second.as_dict()


# --------------------------------------------------------------------------
# owner-anchored arrival
# --------------------------------------------------------------------------


def test_owner_anchored_disc_tracks_the_supplied_anchor() -> None:
    """The whole point: the region moves with the observed owner."""

    here = owner_anchored_goal_region((0.0, 0.0))
    there = owner_anchored_goal_region((6.0, 6.0))
    assert here.center == (0.0, 0.0)
    assert there.center == (6.0, 6.0)
    assert here.radius_m == pytest.approx(OWNER_ARRIVAL_RADIUS_M)
    assert here.anchor_entity == "owner"
    probe = (6.0, 5.0)
    assert not here.contains(*probe)
    assert there.contains(*probe)


def test_owner_anchored_band_excludes_the_owner_footprint() -> None:
    band = owner_anchored_band_goal_region(OWNER_XY, owner_footprint_m=0.22)
    assert not band.contains(OWNER_XY[0] + 0.1, OWNER_XY[1])  # standing on them
    assert band.contains(OWNER_XY[0] + 1.0, OWNER_XY[1])
    assert not band.contains(OWNER_XY[0] + 3.0, OWNER_XY[1])


@pytest.mark.parametrize("radius", [0.0, -1.0, float("nan"), float("inf")])
def test_owner_anchored_disc_rejects_bad_radii(radius: float) -> None:
    with pytest.raises(ValueError):
        owner_anchored_goal_region(OWNER_XY, radius_m=radius)


def test_owner_arrival_succeeds_inside_the_moved_anchor_disc() -> None:
    moved_owner = (5.0, 1.0)
    outcome = evaluate_owner_arrival(
        robot_xy=(4.2, 1.0),
        owner_xy=moved_owner,
        settled=True,
        robot_heading_rad=0.0,
    )
    assert outcome.success
    assert outcome.in_region
    assert outcome.settled
    assert outcome.facing_owner is True
    assert outcome.distance_to_goal_m == pytest.approx(0.0)
    assert outcome.detail == "success"

    # Same robot pose, owner never moved: the static anchor would have failed.
    stale = evaluate_owner_arrival(
        robot_xy=(4.2, 1.0),
        owner_xy=OWNER_XY,
        settled=True,
        robot_heading_rad=0.0,
    )
    assert not stale.success
    assert stale.detail == "outside_owner_region"
    assert stale.distance_to_goal_m > 0.0


def test_owner_arrival_reports_a_settle_miss_separately() -> None:
    outcome = evaluate_owner_arrival(
        robot_xy=(OWNER_XY[0] + 1.0, OWNER_XY[1]),
        owner_xy=OWNER_XY,
        settled=False,
    )
    assert not outcome.success
    assert outcome.in_region
    assert outcome.detail == "never_settled"


def test_owner_arrival_facing_is_report_only_by_default() -> None:
    kwargs = {
        "robot_xy": (OWNER_XY[0] + 1.0, OWNER_XY[1]),
        "owner_xy": OWNER_XY,
        "settled": True,
        # pointing +x, i.e. directly away from the owner
        "robot_heading_rad": 0.0,
    }
    report_only = evaluate_owner_arrival(**kwargs)  # type: ignore[arg-type]
    assert report_only.facing_owner is False
    assert report_only.success

    gated = evaluate_owner_arrival(require_facing=True, **kwargs)  # type: ignore[arg-type]
    assert not gated.success
    assert gated.detail == "not_facing_owner"


def test_owner_arrival_band_form_rejects_standing_on_the_owner() -> None:
    outcome = evaluate_owner_arrival(
        robot_xy=(OWNER_XY[0] + 0.1, OWNER_XY[1]),
        owner_xy=OWNER_XY,
        settled=True,
        band_m=NEXT_TO_BAND_M,
    )
    assert not outcome.success
    assert outcome.detail == "outside_owner_region"


def test_owner_arrival_facing_unknown_without_a_heading() -> None:
    outcome = evaluate_owner_arrival(
        robot_xy=(OWNER_XY[0] + 1.0, OWNER_XY[1]),
        owner_xy=OWNER_XY,
        settled=True,
    )
    assert outcome.facing_owner is None
    assert outcome.heading_error_rad is None
    assert outcome.success


# --------------------------------------------------------------------------
# orbit trajectory scoring (used by the "walk around the owner" e2e case)
# --------------------------------------------------------------------------


def _arc(
    anchor: tuple[float, float],
    radius: float,
    turns: float,
    *,
    samples: int = 72,
) -> list[tuple[float, float]]:
    return [
        (
            anchor[0] + radius * math.cos(turns * 2.0 * math.pi * i / samples),
            anchor[1] + radius * math.sin(turns * 2.0 * math.pi * i / samples),
        )
        for i in range(samples + 1)
    ]


def test_swept_angle_counts_a_full_lap_and_signs_the_direction() -> None:
    ccw = swept_angle_rad(_arc(OWNER_XY, 1.6, 1.0), OWNER_XY)
    cw = swept_angle_rad(_arc(OWNER_XY, 1.6, -1.0), OWNER_XY)
    assert ccw == pytest.approx(2.0 * math.pi, abs=1e-6)
    assert cw == pytest.approx(-2.0 * math.pi, abs=1e-6)


def test_swept_angle_cancels_back_and_forth_motion() -> None:
    there = _arc(OWNER_XY, 1.6, 0.5)
    back = list(reversed(there))
    assert swept_angle_rad(there + back, OWNER_XY) == pytest.approx(0.0, abs=1e-6)


def test_swept_angle_ignores_samples_at_the_anchor() -> None:
    points = [OWNER_XY, OWNER_XY, *_arc(OWNER_XY, 1.6, 1.0)]
    assert swept_angle_rad(points, OWNER_XY) == pytest.approx(2.0 * math.pi, abs=1e-6)


def test_orbit_revolutions_separates_sweep_from_corridor() -> None:
    revs, in_band = orbit_revolutions(_arc(OWNER_XY, 1.6, 1.0), OWNER_XY)
    assert revs == pytest.approx(1.0, abs=1e-6)
    assert in_band == pytest.approx(1.0)

    # A full sweep at 8 m is a sweep, not an orbit — reported separately.
    wide_revs, wide_in_band = orbit_revolutions(_arc(OWNER_XY, 8.0, 1.0), OWNER_XY)
    assert wide_revs == pytest.approx(1.0, abs=1e-6)
    assert wide_in_band == pytest.approx(0.0)


def test_orbit_revolutions_handles_empty_and_partial_traces() -> None:
    assert orbit_revolutions([], OWNER_XY) == (0.0, 0.0)
    half, _ = orbit_revolutions(_arc(OWNER_XY, 1.6, 0.5), OWNER_XY)
    assert half == pytest.approx(0.5, abs=1e-6)


def test_orbit_revolutions_rejects_an_invalid_band() -> None:
    with pytest.raises(ValueError):
        orbit_revolutions(_arc(OWNER_XY, 1.6, 1.0), OWNER_XY, radius_band_m=(3.0, 1.0))
