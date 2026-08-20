from __future__ import annotations

import math
from collections.abc import MutableMapping, Sequence
from typing import Any

from parcel_robot.authority import DEFAULT_STAND_OFF_ENVELOPE
from parcel_robot.instructnav.relations import (
    nearest_point_in_region,
    next_to_placement,
    towards_waypoint,
)
from parcel_robot.instructnav.scoring import NEXT_TO_BAND_M, next_to_band_from_centre

from .base import GoalPose, NavObservation
from .goals import SemanticGoal
from .semantic_map import SemanticCandidate
from .traffic_aware import RankedCandidate, rank_approach_candidates


def safe_approach_pose(
    goal: SemanticGoal,
    candidate: SemanticCandidate,
    observation: NavObservation,
    *,
    footprint_clearance_m: float | None = None,
    obstacle_stop_m: float | None = None,
    tracks: Sequence[object] = (),
    cost_out: MutableMapping[str, Any] | None = None,
    traffic_weight: float = 1.0,
) -> GoalPose | None:
    # Embodiment/envelope scale resolves in-body from the stand-off authority,
    # never as a Python default argument (F-robot-radius / F-proximity).
    stand_off_envelope = DEFAULT_STAND_OFF_ENVELOPE
    if footprint_clearance_m is None:
        footprint_clearance_m = stand_off_envelope.footprint_radius_m
    if obstacle_stop_m is None:
        obstacle_stop_m = stand_off_envelope.target_surface_clearance_m
    if (
        not candidate.reachable
        or not math.isfinite(obstacle_stop_m)
        or obstacle_stop_m <= 0.0
    ):
        return None
    blocked_points = _observed_obstacle_points(observation)
    # Dynamic agents are scored by traffic cost. Instantaneous LiDAR hits on
    # those same bodies must not prune the quieter interior samples the
    # ranking needs — otherwise only stream gaps remain as "valid".
    if tracks:
        blocked_points = _blocked_points_without_tracks(blocked_points, tracks)
    arrival_radius = _bounded_metadata_float(
        candidate.metadata,
        "arrival_radius_m",
        default=0.12,
        minimum=0.05,
        maximum=0.35,
    )
    robot_xy = (observation.position[0], observation.position[1])
    # When tracks are active, prefer quieter entries even when they cost a few
    # metres of detour (Sol module default weight=1; call-site 2.0 is the
    # geometric flip for the e2e crosswalk stream).
    active_traffic_weight = float(traffic_weight)
    if tracks and active_traffic_weight == 1.0:
        active_traffic_weight = 2.0
    if (
        not math.isfinite(active_traffic_weight)
        or active_traffic_weight < 0.0
    ):
        active_traffic_weight = 1.0
    if goal.terminal_relation == "inside" and candidate.polygon:
        terminal_clearance = _bounded_metadata_float(
            candidate.metadata,
            "terminal_clearance_m",
            default=stand_off_envelope.footprint_radius_m,
            minimum=0.10,
            maximum=1.0,
        )
        approach_clearance = max(footprint_clearance_m, terminal_clearance + arrival_radius)
        configured_obstacle_clearance = _bounded_metadata_float(
            candidate.metadata,
            "target_obstacle_clearance_m",
            default=footprint_clearance_m + obstacle_stop_m + arrival_radius + 0.05,
            minimum=footprint_clearance_m,
            maximum=3.0,
        )
        # This is center-to-obstacle-surface clearance at the planned pose.
        # Include the controller's arrival tolerance so every accepted terminal
        # pose still retains the hard-stop envelope around the robot footprint.
        obstacle_clearance = max(
            configured_obstacle_clearance,
            footprint_clearance_m + obstacle_stop_m + arrival_radius + 0.05,
        )
        ranked = _safe_polygon_point(
            candidate.polygon,
            robot_xy,
            approach_clearance,
            blocked_points=blocked_points,
            obstacle_clearance=obstacle_clearance,
            tracks=tracks,
            traffic_weight=active_traffic_weight,
            veto_out=cost_out,
        )
        if ranked is None:
            # N-S3 fallback: nearest inset point without LiDAR pruning.
            try:
                point = nearest_point_in_region(
                    candidate.polygon, robot_xy, inset_m=approach_clearance
                )
            except ValueError:
                point = None
            if point is not None:
                ranked = _rank_approach_point(
                    (point,),
                    robot_xy,
                    tracks,
                    traffic_weight=active_traffic_weight,
                    veto_out=cost_out,
                )
        if ranked is None:
            # Card R10 tier 3 — the in-region resample. Root cause of the live
            # ``semantic_target_unreachable``: tiers 1 and 2 above BOTH require
            # the straight ROBOT->POINT segment to be clear
            # (``_segment_clear_of_observed_obstacles``), so one pedestrian
            # standing between the robot and the sidewalk disqualifies every
            # interior sample at once and the whole region reports "unreachable"
            # — while ``_fallback_near_arrival_pose`` in the pipeline is gated to
            # near/next_to and never runs for a region goal. The resampler keeps
            # every POINT clearance at full strength (containment, edge
            # clearance, footprint-to-surface clearance from every observed
            # surface, and person keepout discs the old path never consulted)
            # and drops only the straight-line precondition, which is a route
            # heuristic the grid planner and the reactive gate already own.
            attempts: list[dict[str, Any]] = []
            resampled = resample_inside_region(
                candidate.polygon,
                robot_xy,
                approach_clearance=approach_clearance,
                obstacle_clearance=obstacle_clearance,
                blocked_points=blocked_points,
                keepouts=_person_keepout_discs(tracks),
                footprint_clearance_m=footprint_clearance_m,
                attempts_out=attempts,
            )
            if cost_out is not None:
                cost_out["inside_resample_attempts"] = attempts
                cost_out["inside_resample_candidates"] = len(resampled)
            if resampled:
                ranked = _rank_approach_point(
                    tuple(resampled),
                    robot_xy,
                    tracks,
                    traffic_weight=active_traffic_weight,
                    veto_out=cost_out,
                )
        if ranked is None:
            # Every admissible pose sits in the pedestrian stream. Saying so is
            # the point of a fail-closed veto.
            return None
        _record_approach_costs(ranked, cost_out)
        x, y = ranked.x, ranked.y
    elif goal.terminal_relation == "towards":
        x, y = towards_waypoint(
            (candidate.x, candidate.y),
            robot_xy,
            stop_short_m=stand_off_envelope.towards_stop_short_m,
        )
        arrival_radius = max(arrival_radius, 0.2)
    elif goal.terminal_relation == "next_to":
        footprint = _bounded_metadata_float(
            candidate.metadata, "radius_m", default=0.3, minimum=0.05, maximum=2.0
        )
        arrival_radius = max(arrival_radius, 0.08)
        # A placed sample is a robot *centre*; a blocked point is an observed
        # *surface*. The threshold is a footprint-to-surface clearance, so the
        # body radius has to be in the comparison — it was not, which let this
        # branch place the robot with its footprint inside the stop envelope of
        # the very object it was asked to sit beside. ``obstacle_stop_m``
        # resolves in-body to ``StandOffEnvelope.target_surface_clearance_m``
        # (0.8 m), which dominates the runtime reactive gate (0.65 m), so a
        # placement that clears this also clears every gate that does NOT
        # exempt the approach target — and the runtime's gate never does.
        surface_clearance = footprint_clearance_m + obstacle_stop_m + arrival_radius

        def _occupied(px: float, py: float) -> bool:
            # Every observed surface, id or not. The old id filter silently
            # ignored anonymous returns; a camera and a LiDAR share no id space
            # (stratum 2), so an unlabelled return is still a solid.
            return any(
                math.hypot(px - ox, py - oy) < surface_clearance
                for _oid, ox, oy in blocked_points
            )

        try:
            placement = next_to_placement(
                (candidate.x, candidate.y),
                footprint,
                robot_xy,
                band_m=_next_to_planning_band(
                    arrival_radius, footprint, stand_off_envelope
                ),
                occupied=_occupied,
            )
        except ValueError:
            # An empty planning band is "no such pose exists", not a crash.
            return None
        if placement is None:
            return None
        x, y, _heading = placement
    elif goal.terminal_relation == "near":
        stand_off = _bounded_metadata_float(
            candidate.metadata,
            "stand_off_m",
            default=stand_off_envelope.near_stand_off_floor_m,
            minimum=0.5,
            maximum=3.0,
        )
        candidate_radius = _bounded_metadata_float(
            candidate.metadata,
            "radius_m",
            default=0.0,
            minimum=0.0,
            maximum=2.0,
        )
        target_surface_clearance = max(
            obstacle_stop_m,
            _bounded_metadata_float(
                candidate.metadata,
                "target_min_surface_clearance_m",
                default=obstacle_stop_m,
                minimum=0.1,
                maximum=2.0,
            ),
        )
        # The near band's INNER edge in anchor-centre coordinates: the same
        # ``minimum_vicinity`` = r + footprint + target_surface_clearance the
        # pipeline terminal check and the scorer read. Kept explicit so the
        # planning band below insets from the identical edge the authority
        # verifies against — one band, not two that agree by convention.
        minimum_vicinity = (
            candidate_radius + footprint_clearance_m + target_surface_clearance
        )
        stand_off = max(
            stand_off,
            minimum_vicinity + arrival_radius + stand_off_envelope.stand_off_margin_m,
        )
        maximum_vicinity = _bounded_metadata_float(
            candidate.metadata,
            "vicinity_radius_m",
            default=stand_off + arrival_radius + 0.05,
            minimum=0.5,
            maximum=4.0,
        )
        # F-1 for near (card near-band-inset, 2026-08-09). Inset BOTH edges of
        # the K0 near band by (arrival tolerance + stand_off_margin) and clamp
        # the planned stand-off inside, so the controller's stop — up to
        # arrival_radius past the pose in any direction, plus settle overshoot —
        # lands INSIDE the band the mission verifies. Without the outer inset
        # the lamppost pose sat on the outer edge (stand_off_m metadata = 1.32 =
        # vicinity − arrival_radius) and every run stopped ~1 cm outside the
        # 1.38 m verify max. Narrowing only; the K0 arrival authority is
        # unchanged.
        try:
            plan_lo, plan_hi = _near_planning_band(
                minimum_vicinity, maximum_vicinity, arrival_radius, stand_off_envelope
            )
        except ValueError:
            # The inset empties the band — no admissible near pose exists here.
            return None
        stand_off = max(plan_lo, min(stand_off, plan_hi))
        non_target_clearance = _bounded_metadata_float(
            candidate.metadata,
            "non_target_obstacle_clearance_m",
            default=footprint_clearance_m + obstacle_stop_m + arrival_radius + 0.05,
            minimum=footprint_clearance_m,
            maximum=3.0,
        )
        support_polygon = _metadata_polygon(candidate.metadata.get("support_polygon"))
        ranked = _safe_near_object_point(
            candidate,
            (observation.position[0], observation.position[1]),
            stand_off,
            support_polygon,
            blocked_points,
            footprint_clearance_m + arrival_radius,
            max(
                non_target_clearance,
                footprint_clearance_m + obstacle_stop_m + arrival_radius + 0.05,
            ),
            tracks=tracks,
            traffic_weight=active_traffic_weight,
            veto_out=cost_out,
        )
        if ranked is None:
            return None
        _record_approach_costs(ranked, cost_out)
        x, y = ranked.x, ranked.y
    else:
        x, y = candidate.x, candidate.y
    heading = math.degrees(
        math.atan2(candidate.y - y, candidate.x - x)
    )
    return GoalPose(
        x=x,
        y=y,
        z=candidate.z,
        heading_deg=heading,
        poi_id=candidate.candidate_id,
        label=candidate.label,
        arrival_radius_m=arrival_radius,
    )


def _next_to_planning_band(
    arrival_radius_m: float,
    anchor_footprint_m: float,
    envelope: Any = DEFAULT_STAND_OFF_ENVELOPE,
    band_m: tuple[float, float] = NEXT_TO_BAND_M,
) -> tuple[float, float]:
    """The ``next_to`` band a *pose* may be planned in, inset from the K0 band.

    K0's :data:`~parcel_robot.instructnav.scoring.NEXT_TO_BAND_M` is the band
    the arrival authority *verifies* against. It is not the band a pose may be
    planned in, because the controller does not stop on the pose — it stops
    anywhere within ``arrival_radius_m`` of it (``GridNavigator.act``:
    ``goal_distance <= arrival_radius``), in **any** direction, including
    radially away from the anchor. A pose on the outer edge therefore admits a
    final pose outside the very band the mission then verifies, and the mission
    fails ``semantic_arrival_verification_failed`` having done everything it
    was asked. Measured 2026-08-06: pose planned at 1.500 m from
    ``lamp_post_1``, stopped at 1.572 m, 0.072 m outside — exactly one arrival
    tolerance (0.08 m).

    So the planning band is inset on both edges by the tolerance the controller
    is allowed to spend, plus ``stand_off_margin_m`` — the authority's own name
    for "and a little more than exactly enough". This is a *narrowing*: every
    pose it admits was already admissible before, and no widening of any band,
    tolerance, or gate is involved.

    ``anchor_footprint_m`` is **required** and is not a knob: the K0 band is
    measured to the anchor's SURFACE, so the centre-coordinate band the sampler
    needs is :func:`~parcel_robot.instructnav.scoring.next_to_band_from_centre`
    of it — the same call
    :func:`~parcel_robot.instructnav.scoring.object_next_to_goal_region` makes.
    Planning and verification therefore read one definition rather than two
    that agree by convention. Passing it explicitly (rather than defaulting to
    0.0) is deliberate: a caller that forgot it would plan against a band the
    arrival authority never verifies, which is exactly the defect this function
    exists to prevent.

    Raises ``ValueError`` when the inset would empty the band; callers treat
    that as "no such pose exists", which is the honest answer.
    """

    centre_band = next_to_band_from_centre(anchor_footprint_m, band_m)
    inset = float(arrival_radius_m) + float(envelope.stand_off_margin_m)
    lo = centre_band[0] + inset
    hi = centre_band[1] - inset
    if not (math.isfinite(lo) and math.isfinite(hi)) or lo >= hi:
        raise ValueError("next_to planning band is empty after the arrival inset")
    return (lo, hi)


#: A ``near`` band whose inset edges cross by no more than this is treated as a
#: single admissible ring at the midpoint, not an empty band. The lamppost's
#: near band is razor-thin by construction — its width (vicinity −
#: minimum_vicinity = 0.20 m) is exactly twice the inset (arrival 0.06 +
#: stand_off_margin 0.04), so the two inset edges land on the SAME midpoint
#: (1.28 m) and float rounding makes ``lo`` exceed ``hi`` by ~4e-16. Collapsing
#: that to the midpoint is the honest reading; only a genuine crossing (the
#: inset is wider than half the band) is "no such pose exists".
_NEAR_BAND_COLLAPSE_EPS_M = 1e-6


def _near_planning_band(
    minimum_vicinity_m: float,
    maximum_vicinity_m: float,
    arrival_radius_m: float,
    envelope: Any = DEFAULT_STAND_OFF_ENVELOPE,
) -> tuple[float, float]:
    """The stand-off distances a ``near`` pose may be planned at, inset from K0.

    The K0 ``near`` band the arrival authority verifies against is
    ``[minimum_vicinity, vicinity]`` in anchor-CENTRE coordinates — the same
    ``minimum_vicinity_radius_m .. vicinity_radius_m`` the pipeline terminal
    check reads (``pipeline.py`` near branch) and
    :func:`~parcel_robot.instructnav.scoring.object_near_goal_region` stamps.
    It is not the band a pose may be planned in, for exactly the reason spelled
    out in :func:`_next_to_planning_band`: the controller does not stop on the
    pose — it stops anywhere within ``arrival_radius_m`` of it, in **any**
    direction, including radially away from the anchor, plus a small settle
    overshoot. A pose on the outer edge (which is where the lamppost's
    ``stand_off_m`` metadata put it: 1.32 m = vicinity − arrival_radius)
    therefore admits a final pose OUTSIDE the very band the mission then
    verifies, and the mission fails ``semantic_arrival_verification_failed``
    having walked to the right object. The F-1 inset fix landed for ``next_to``
    on 2026-08-07; this is the same shape for ``near`` (card near-band-inset).

    Both edges are inset by ``arrival_radius_m + stand_off_margin_m`` — the
    tolerance the controller may spend plus the authority's own "and a little
    more than exactly enough". This is a *narrowing*: every pose it admits was
    already admissible, and no band, tolerance, or gate is widened.

    Raises ``ValueError`` when the inset genuinely empties the band (the inset
    exceeds half the band width); callers treat that as "no such pose exists".
    """

    inset = float(arrival_radius_m) + float(envelope.stand_off_margin_m)
    lo = float(minimum_vicinity_m) + inset
    hi = float(maximum_vicinity_m) - inset
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ValueError("near planning band is not finite")
    if lo > hi:
        if lo - hi <= _NEAR_BAND_COLLAPSE_EPS_M:
            mid = 0.5 * (lo + hi)
            return (mid, mid)
        raise ValueError("near planning band is empty after the arrival inset")
    return (lo, hi)


def _safe_polygon_point(
    polygon: tuple[tuple[float, float], ...],
    robot: tuple[float, float],
    clearance: float,
    *,
    blocked_points: tuple[tuple[str | None, float, float], ...] = (),
    obstacle_clearance: float = 0.0,
    tracks: Sequence[object] = (),
    traffic_weight: float = 1.0,
    veto_out: MutableMapping[str, Any] | None = None,
) -> RankedCandidate | None:
    if len(polygon) < 3:
        return None
    # Sample the interior rather than trusting its centroid: a sidewalk's
    # centroid can itself contain a lamp, bench, or tree. This is a bounded
    # local free-space approximation over camera semantics + LiDAR surfaces.
    cx = sum(point[0] for point in polygon) / len(polygon)
    cy = sum(point[1] for point in polygon) / len(polygon)
    samples = [(cx, cy)]
    min_x = min(point[0] for point in polygon)
    max_x = max(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_y = max(point[1] for point in polygon)
    spacing = max(0.25, max(max_x - min_x, max_y - min_y) / 40.0)
    x = min_x + clearance
    while x <= max_x - clearance + 1e-9:
        y = min_y + clearance
        while y <= max_y - clearance + 1e-9:
            samples.append((x, y))
            y += spacing
        x += spacing
    valid = [
        point
        for point in samples
        if _inside(point, polygon) and _has_clearance(point, polygon, clearance)
        and _clear_of_observed_obstacles(point, blocked_points, obstacle_clearance)
        and _segment_clear_of_observed_obstacles(
            robot,
            point,
            blocked_points,
            obstacle_clearance,
        )
    ]
    if not valid:
        return None
    return _rank_approach_point(
        valid, robot, tracks, traffic_weight=traffic_weight, veto_out=veto_out
    )


#: Inset ladder for the in-region resample, as MULTIPLES of the requested
#: approach clearance. The last rung is pinned to the footprint radius by
#: :func:`resample_inside_region` and never goes below it: at the footprint
#: radius the body is exactly contained by the region, which is the whole
#: meaning of an ``inside`` terminal. Relaxing the INSET is legitimate (it is a
#: comfort margin off the region edge); relaxing the obstacle clearance is not,
#: and this ladder never touches it.
INSIDE_RESAMPLE_INSET_STEPS: tuple[float, ...] = (1.0, 0.75, 0.5)

#: Grid spacing cap for the resample, in metres. Finer than
#: ``_safe_polygon_point``'s 0.25 m floor, because this tier only runs when the
#: coarse pass already failed and a 2 m-wide sidewalk deserves a closer look.
INSIDE_RESAMPLE_SPACING_M = 0.12

#: Hard cap on samples evaluated per inset rung. Bounded work in a 10 Hz tick.
INSIDE_RESAMPLE_MAX_SAMPLES = 900


def resample_inside_region(
    polygon: tuple[tuple[float, float], ...],
    robot: tuple[float, float],
    *,
    approach_clearance: float,
    obstacle_clearance: float,
    blocked_points: tuple[tuple[str | None, float, float], ...] = (),
    keepouts: tuple[tuple[str, float, float, float], ...] = (),
    footprint_clearance_m: float | None = None,
    attempts_out: list[dict[str, Any]] | None = None,
) -> tuple[tuple[float, float], ...]:
    """Keepout-aware in-region goal resampling — card R10 work item 1.

    Returns admissible interior points, nearest-to-robot first, for the ranker to
    veto or accept. Empty means the region genuinely has no admissible pose, and
    ``attempts_out`` then NAMES what was tried: one row per inset rung with the
    sample count and the count each filter rejected, which is what turns "give
    up" into "give up, and here is what I tried" (card: *the give-up names the
    candidates tried*).

    What it never relaxes, in one place so an auditor can check it:

    * ``obstacle_clearance`` — the full centre-to-surface distance the reactive
      gate enforces — is applied at EVERY accepted point, unchanged, at every
      rung;
    * ``keepouts`` (person discs) veto absolutely, at any clearance;
    * containment is exact ``_inside`` plus an edge clearance that never drops
      below the robot footprint radius, so an accepted point always has the
      whole body inside the region.

    What it does relax, and why: the straight ROBOT->POINT segment test. The
    robot does not drive straight lines — ``grid_planner`` routes and
    ``apply_reactive_safety`` disposes — so using an occlusion test as an
    arrival-POSE admissibility test conflates "can I get there" with "is this
    pose safe", and only the second belongs to this function.
    """

    if len(polygon) < 3:
        if attempts_out is not None:
            attempts_out.append({"rung": "n/a", "rejected": "polygon_degenerate"})
        return ()
    floor = (
        DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m
        if footprint_clearance_m is None
        else float(footprint_clearance_m)
    )
    base = float(approach_clearance)
    if not math.isfinite(base) or base <= 0.0:
        base = floor
    obstacle = float(obstacle_clearance)
    if not math.isfinite(obstacle) or obstacle < 0.0:
        obstacle = 0.0

    min_x = min(point[0] for point in polygon)
    max_x = max(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_y = max(point[1] for point in polygon)
    span = max(max_x - min_x, max_y - min_y)
    spacing = max(INSIDE_RESAMPLE_SPACING_M, span / 60.0)

    insets: list[float] = []
    for step in INSIDE_RESAMPLE_INSET_STEPS:
        value = max(floor, base * float(step))
        if not any(abs(value - existing) < 1e-9 for existing in insets):
            insets.append(value)
    if not any(abs(floor - existing) < 1e-9 for existing in insets):
        insets.append(floor)

    for inset in insets:
        considered = 0
        outside = 0
        too_close_to_edge = 0
        blocked_by_surface = 0
        blocked_by_person = 0
        admitted: list[tuple[float, float]] = []
        x = min_x
        while x <= max_x + 1e-9 and considered < INSIDE_RESAMPLE_MAX_SAMPLES:
            y = min_y
            while y <= max_y + 1e-9 and considered < INSIDE_RESAMPLE_MAX_SAMPLES:
                point = (x, y)
                considered += 1
                y += spacing
                if not _inside(point, polygon):
                    outside += 1
                    continue
                if not _has_clearance(point, polygon, inset):
                    too_close_to_edge += 1
                    continue
                if not _clear_of_observed_obstacles(point, blocked_points, obstacle):
                    blocked_by_surface += 1
                    continue
                if _inside_any_keepout(point, keepouts):
                    blocked_by_person += 1
                    continue
                admitted.append(point)
            x += spacing
        if attempts_out is not None:
            attempts_out.append(
                {
                    "inset_m": round(inset, 3),
                    "obstacle_clearance_m": round(obstacle, 3),
                    "spacing_m": round(spacing, 3),
                    "considered": considered,
                    "outside_region": outside,
                    "too_close_to_region_edge": too_close_to_edge,
                    "blocked_by_observed_surface": blocked_by_surface,
                    "blocked_by_person_keepout": blocked_by_person,
                    "admitted": len(admitted),
                }
            )
        if admitted:
            admitted.sort(key=lambda item: (math.dist(robot, item), item[0], item[1]))
            return tuple(admitted)
    return ()


def _inside_any_keepout(
    point: tuple[float, float],
    keepouts: tuple[tuple[str, float, float, float], ...],
) -> bool:
    return any(
        math.hypot(point[0] - x, point[1] - y) < radius for _label, x, y, radius in keepouts
    )


def _person_keepout_discs(
    tracks: Sequence[object],
) -> tuple[tuple[str, float, float, float], ...]:
    """Dynamic tracks as keepout discs, from the tracks already in hand.

    Fail-safe on kind: a track that declares a NON-person kind (a car) is left
    to the LiDAR surfaces that already describe it, but a track with no declared
    kind — which is what ``coerce_tracks`` produces for the ``TrackState`` form,
    since it carries no ``kind`` field — is treated as a PERSON. Guessing
    "probably not a person" about a moving body would be the wrong direction to
    be wrong in, and this is the case the proxemics literature (and the live
    sidewalk mission) says a goal pose must never be planted on top of.
    """

    from .traffic_aware import coerce_tracks

    try:
        validated = coerce_tracks(tracks)
    except ValueError:
        return ()
    discs: list[tuple[str, float, float, float]] = []
    for track in validated:
        kind = str(getattr(track, "kind", "") or "").lower()
        if kind and kind not in {"person", "pedestrian", "human", "owner"}:
            continue
        radius = float(getattr(track, "radius_m", 0.0) or 0.0)
        if radius <= 0.0:
            continue
        discs.append((kind or "someone", float(track.x), float(track.y), radius))
    return tuple(discs)


def point_in_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    return _inside(point, polygon)


def point_in_polygon_with_clearance(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
    clearance_m: float,
) -> bool:
    return _inside(point, polygon) and _has_clearance(point, polygon, clearance_m)


def _safe_near_object_point(
    candidate: SemanticCandidate,
    robot: tuple[float, float],
    stand_off: float,
    support_polygon: tuple[tuple[float, float], ...],
    blocked_points: tuple[tuple[str | None, float, float], ...],
    footprint_clearance: float,
    obstacle_clearance: float,
    *,
    tracks: Sequence[object] = (),
    traffic_weight: float = 1.0,
    veto_out: MutableMapping[str, Any] | None = None,
) -> RankedCandidate | None:
    base_angle = math.atan2(robot[1] - candidate.y, robot[0] - candidate.x)
    samples = [
        (
            candidate.x + stand_off * math.cos(base_angle + index * math.pi / 16.0),
            candidate.y + stand_off * math.sin(base_angle + index * math.pi / 16.0),
        )
        for index in range(32)
    ]
    other_obstacles = _obstacles_excluding_target(candidate, blocked_points, robot)
    usable = []
    for point in samples:
        if support_polygon and not point_in_polygon_with_clearance(
            point, support_polygon, footprint_clearance
        ):
            continue
        if not _clear_of_observed_obstacles(point, other_obstacles, obstacle_clearance):
            continue
        if not _segment_clear_of_observed_obstacles(
            robot,
            point,
            other_obstacles,
            obstacle_clearance,
        ):
            continue
        usable.append(point)
    if not usable:
        return None
    return _rank_approach_point(
        usable, robot, tracks, traffic_weight=traffic_weight, veto_out=veto_out
    )


#: How many ranked candidates the proxemic veto is allowed to walk before it
#: gives up and reports an honest no-pose. Bounded because each evaluation runs
#: a TTC rollout per track.
PROXEMIC_VETO_DEPTH = 16


def _rank_approach_point(
    points: Sequence[tuple[float, float]],
    robot: tuple[float, float],
    tracks: Sequence[object] = (),
    *,
    traffic_weight: float = 1.0,
    veto_out: MutableMapping[str, Any] | None = None,
) -> RankedCandidate | None:
    """Best-first pick, then the proxemic veto. Empty tracks keep static order.

    **N11 residual, and the shape matters.** ``proxemic_approach`` is wired as
    a *veto on the winner*, never as a competing selector. The ordering is
    entirely ``traffic_aware``'s; the veto may only strike candidates off that
    ordering, in that order, and if it strikes them all the answer is ``None``
    — an honest "I have no safe approach pose", not the least-bad landing in
    the pedestrian stream. Two proxemic authorities that could disagree about
    which pose is *best* is the D5 defect class; one authority that ranks and
    one that refuses cannot disagree, because refusing is not ranking.
    """

    ranked = rank_approach_candidates(
        points,
        tracks,
        static_cost_fn=lambda point: math.hypot(point[0] - robot[0], point[1] - robot[1]),
        traffic_weight=traffic_weight,
        # Bound the traffic rollout to the statically best subset: the polygon
        # grid can reach ~1681 candidates x several tracks (19-34 ms measured
        # unbounded). Preselection is static-order, so the ladder guarantee
        # (empty tracks == static ordering) is unaffected.
        top_k=64,
    )
    if not ranked:
        return None
    if not tracks:
        # Ladder rule: with no dynamic agents the veto has nothing to say and
        # must not be consulted at all, so static ordering stays byte-identical.
        return ranked[0]
    return _proxemic_veto(ranked, tracks, robot, veto_out=veto_out)


def _proxemic_veto(
    ranked: Sequence[RankedCandidate],
    tracks: Sequence[object],
    robot: tuple[float, float],
    *,
    veto_out: MutableMapping[str, Any] | None = None,
) -> RankedCandidate | None:
    """Return the first ranked candidate the proxemic cost does not reject."""

    try:
        from .proxemic_approach import ProxemicApproachConfig, proxemic_costs
    except ImportError:  # pragma: no cover — bundle without numpy siblings
        return ranked[0]

    head = list(ranked[:PROXEMIC_VETO_DEPTH])
    try:
        costs = proxemic_costs(
            [(item.x, item.y) for item in head],
            _proxemic_tracks(tracks),
            robot_xy=robot,
        )
    except (ImportError, TypeError, ValueError):
        # A veto that cannot be evaluated must not silently pass everything,
        # but it also must not veto everything on a malformed input: the
        # ranking authority still holds, so defer to it and say so.
        if veto_out is not None:
            veto_out["proxemic_veto"] = "unavailable"
        return ranked[0]

    threshold = ProxemicApproachConfig().reject_cost
    vetoed = 0
    for item, cost in zip(head, costs, strict=False):
        if float(cost) < threshold:
            if veto_out is not None:
                veto_out["proxemic_veto"] = "passed" if vetoed == 0 else "demoted"
                veto_out["proxemic_vetoed_count"] = vetoed
                veto_out["proxemic_cost"] = float(cost)
            return item
        vetoed += 1
    if veto_out is not None:
        veto_out["proxemic_veto"] = "all_vetoed"
        veto_out["proxemic_vetoed_count"] = vetoed
        veto_out["proxemic_cost"] = float(min(costs)) if len(costs) else None
    return None


def _proxemic_tracks(tracks: Sequence[object]) -> list[Any]:
    """Coerce the pipeline's track payload into ``dynamic_costs.AgentTrack``."""

    from .dynamic_costs import AgentTrack
    from .traffic_aware import coerce_tracks

    return [
        AgentTrack(x=t.x, y=t.y, vx=t.vx, vy=t.vy, radius_m=t.radius_m)
        for t in coerce_tracks(tracks)
    ]


def _record_approach_costs(
    ranked: RankedCandidate,
    cost_out: MutableMapping[str, Any] | None,
) -> None:
    if cost_out is None:
        return
    cost_out["approach_static_cost"] = ranked.static_cost
    cost_out["approach_traffic_cost"] = ranked.traffic_cost
    cost_out["approach_total_cost"] = ranked.total_cost


def _blocked_points_without_tracks(
    blocked_points: tuple[tuple[str | None, float, float], ...],
    tracks: Sequence[object],
    *,
    match_m: float = 0.9,
) -> tuple[tuple[str | None, float, float], ...]:
    """Drop LiDAR hits that coincide with dynamic tracks (traffic owns those)."""

    from .traffic_aware import coerce_tracks

    try:
        validated = coerce_tracks(tracks)
    except ValueError:
        return blocked_points
    if not validated:
        return blocked_points
    kept: list[tuple[str | None, float, float]] = []
    for item in blocked_points:
        _oid, x, y = item
        if any(
            math.hypot(x - track.x, y - track.y) <= track.radius_m + match_m
            for track in validated
        ):
            continue
        kept.append(item)
    return tuple(kept)


def _observed_obstacle_points(
    observation: NavObservation,
) -> tuple[tuple[str | None, float, float], ...]:
    raw = observation.extras.get("lidar_obstacles") or ()
    if not isinstance(raw, (list, tuple)):
        return ()
    heading = math.radians(observation.heading_deg)
    robot_x, robot_y = observation.position[:2]
    points: list[tuple[str | None, float, float]] = []
    for item in raw[:64]:
        if not isinstance(item, dict):
            continue
        try:
            distance = float(item["distance_m"])
            bearing = float(item["bearing_rad"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(distance) or not math.isfinite(bearing) or distance < 0.0:
            continue
        # Simulator/robot range contracts report footprint-to-surface
        # clearance. Add the nominal body radius to estimate a world surface
        # point without exposing simulator coordinates to the planner.
        ray = distance + DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m
        angle = heading + bearing
        points.append(
            (
                str(item["id"]) if item.get("id") else None,
                robot_x + ray * math.cos(angle),
                robot_y + ray * math.sin(angle),
            )
        )
    return tuple(points)


def _clear_of_observed_obstacles(
    point: tuple[float, float],
    blocked_points: tuple[tuple[str | None, float, float], ...],
    clearance: float,
) -> bool:
    return all(math.hypot(point[0] - x, point[1] - y) >= clearance for _, x, y in blocked_points)


def _segment_clear_of_observed_obstacles(
    start: tuple[float, float],
    end: tuple[float, float],
    blocked_points: tuple[tuple[str | None, float, float], ...],
    clearance: float,
) -> bool:
    """Conservatively validate the swept centerline against observed surfaces.

    A robot already inside a slowdown envelope may move away from that surface;
    otherwise the full segment must retain the requested center clearance.
    """

    groups: dict[str, list[tuple[float, float]]] = {}
    for index, (obstacle_id, x, y) in enumerate(blocked_points):
        key = obstacle_id or f"anonymous-{index}"
        groups.setdefault(key, []).append((x, y))
    for surfaces in groups.values():
        start_distance = min(math.dist(start, point) for point in surfaces)
        end_distance = min(math.dist(end, point) for point in surfaces)
        if (
            start_distance < clearance
            and end_distance > start_distance + 0.05
            and _group_clearance_is_nondecreasing(start, end, surfaces)
        ):
            # Moving out of an already-entered slowdown envelope is safer than
            # freezing in it. Group all returns from a long face so individual
            # perimeter samples do not falsely reject motion away from the
            # underlying solid obstacle.
            continue
        if any(
            _segment_distance(surface, start, end) < clearance
            for surface in surfaces
        ):
            return False
    return True


def _group_clearance_is_nondecreasing(
    start: tuple[float, float],
    end: tuple[float, float],
    surfaces: list[tuple[float, float]],
) -> bool:
    previous = min(math.dist(start, point) for point in surfaces)
    for index in range(1, 17):
        fraction = index / 16.0
        position = (
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        )
        current = min(math.dist(position, point) for point in surfaces)
        if current + 1e-6 < previous:
            return False
        previous = current
    return True


#: Slack around the target's own radius when deciding which observed surfaces
#: belong to the target itself. Mirrors
#: ``pipeline.DirectiveNavigator.TARGET_ASSOCIATION_SLACK_M`` — one number,
#: stated twice rather than imported, because ``approach`` sits below
#: ``pipeline`` in the import graph and must stay there.
TARGET_ASSOCIATION_SLACK_M = 0.45


def _obstacles_excluding_target(
    candidate: SemanticCandidate,
    blocked_points: tuple[tuple[str | None, float, float], ...],
    robot: tuple[float, float],
) -> tuple[tuple[str | None, float, float], ...]:
    """Drop observed surfaces that belong to the approach target itself.

    Stratum 2: this used to be ``obstacle_id not in {candidate_id,
    *associated_lidar_ids}`` — a join between the semantic channel's ids and
    the range channel's ids, which only closes because one simulator emits
    both. A camera and a LiDAR share no id space.

    The geometric replacement is a **line-of-sight** test, not a
    distance-to-centre test, for the reason spelled out in
    ``pipeline._ray_hits_target``: a range return lands on a body's near
    *surface*, so on a body whose radius the semantic channel does not carry it
    sits a whole radius short of the centre. A surface belongs to the target
    when the robot→surface ray points at the target (perpendicular offset
    within radius + slack) and the surface is not beyond it.
    """

    radius = _bounded_metadata_float(
        candidate.metadata, "radius_m", default=0.0, minimum=0.0, maximum=5.0
    )
    gate = radius + TARGET_ASSOCIATION_SLACK_M
    dx = candidate.x - robot[0]
    dy = candidate.y - robot[1]
    kept: list[tuple[str | None, float, float]] = []
    for item in blocked_points:
        vx = item[1] - robot[0]
        vy = item[2] - robot[1]
        length = math.hypot(vx, vy)
        if length <= 1e-9:
            kept.append(item)
            continue
        ux, uy = vx / length, vy / length
        along = dx * ux + dy * uy
        perpendicular = abs(dx * uy - dy * ux)
        if along > 0.0 and perpendicular <= gate and length <= along + gate:
            continue  # this surface is the target
        kept.append(item)
    return tuple(kept)


def _metadata_polygon(value: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)) or not 3 <= len(value) <= 256:
        return ()
    try:
        polygon = tuple((float(point[0]), float(point[1])) for point in value)
    except (IndexError, TypeError, ValueError):
        return ()
    if any(not math.isfinite(axis) for point in polygon for axis in point):
        return ()
    return polygon


def _bounded_metadata_float(
    metadata: dict[str, object],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(metadata.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and minimum <= value <= maximum else default


def _inside(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def _edge_distance(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> float:
    return min(
        _segment_distance(point, polygon[index - 1], polygon[index])
        for index in range(len(polygon))
    )


def _has_clearance(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
    clearance: float,
) -> bool:
    return _edge_distance(point, polygon) + 1e-9 >= clearance


def _segment_distance(point, start, end) -> float:
    return _segment_distance_and_progress(point, start, end)[0]


def _segment_distance_and_progress(point, start, end) -> tuple[float, float]:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(point[0] - start[0], point[1] - start[1]), 0.0
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    progress = max(0.0, min(1.0, projection))
    return (
        math.hypot(
            point[0] - (start[0] + progress * dx),
            point[1] - (start[1] + progress * dy),
        ),
        progress,
    )
