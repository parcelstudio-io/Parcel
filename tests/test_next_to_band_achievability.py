"""Why ``next_to`` had no pose around ``bench_1``, and what fixed it.

Card F-1 proved the bench's admissible set empty with an exhaustive sweep and
left the conclusion in an xfail reason string. Card B-1 (2026-08-08) turned that
measurement into executable geometry and found the real cause: **the reason was
not the bench, it was the band.** ``NEXT_TO_BAND_M`` was measured to the
anchor's *centre* while every stand-off authority is measured to its *surface*,
so the band's usable width shrank by the anchor's radius and vanished entirely
above R = 0.38 m.

Card S-1 (2026-08-09) re-anchored the band to the surface. This file keeps both
halves: the measurements that diagnosed the defect (now evaluated against the
superseded band, which is named as such) and the measurements that show the fix
opens the bench, at full shipping clearances, in the live scene.

Every number is derived or read from the MJCF at test time. Nothing about the
scene is transcribed — the bench, the pedestrians and the buildings are
projected the same way ``mujoco_lidar.planar_geom_surface_hit`` projects them
(logical-obstacle geoms whose bottom sits below
``RobotProfile.obstacle_clearance_height_m``, as oriented boxes or circles).
"""

from __future__ import annotations

import dataclasses
import functools
import json
import math
from pathlib import Path

import mujoco
import pytest

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE, DEFAULT_STAND_OFF_ENVELOPE
from parcel_robot.instructnav.relations import (
    PLACEMENT_BEARINGS,
    PLACEMENT_RADII,
    next_to_placement,
)
from parcel_robot.instructnav.scoring import (
    NEXT_TO_BAND_M,
    next_to_band_from_centre,
    next_to_band_surface_slack_m,
    next_to_is_achievable,
    object_next_to_goal_region,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.approach import _next_to_planning_band
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy, apply_reactive_safety
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE
from parcel_robot.sim import is_logical_obstacle_name

REPO = Path(__file__).resolve().parents[1]
SCENE = REPO / "src/parcel_robot/scenes/city_block.xml"

BENCH_GEOMS = frozenset({"bench_seat", "bench_back", "bench_leg_l", "bench_leg_r"})
PERSON_PREFIXES = ("pedestrian_", "owner_")

#: ``safe_approach_pose``'s ``next_to`` occupancy threshold, centre-to-surface:
#: ``footprint + target_surface_clearance + arrival``. The branch floors the
#: arrival tolerance at 0.08 m.
NEXT_TO_ARRIVAL_FLOOR_M = 0.08
SOLVER_CLEARANCE_M = (
    DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m
    + DEFAULT_STAND_OFF_ENVELOPE.target_surface_clearance_m
    + NEXT_TO_ARRIVAL_FLOOR_M
)
#: The runtime reactive gate's own envelope around any obstacle, centre-to-
#: surface. ``configs/robot.yaml safety.obstacle_stop_m`` is footprint-to-
#: surface, so the body radius is added. Nothing exempts the approach target.
RUNTIME_GATE_CLEARANCE_M = (
    DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m + ReactiveSafetyPolicy().obstacle_stop_m
)


def _superseded_centre_band(radius_m: float) -> tuple[float, float]:
    """The band as it was measured before 2026-08-09: to the anchor's CENTRE.

    Written here, in the test that documents the defect, rather than left in
    the source as a second live definition.
    """

    return (max(NEXT_TO_BAND_M[0], radius_m), NEXT_TO_BAND_M[1])


class _Solid:
    """One logical obstacle, projected to 2-D exactly as the range channel does."""

    __slots__ = ("circle", "name", "rot", "sx", "sy", "x", "y")

    def __init__(self, name, circle, x, y, sx, sy, rot):
        self.name, self.circle = name, circle
        self.x, self.y, self.sx, self.sy, self.rot = x, y, sx, sy, rot

    def distance(self, px: float, py: float) -> float:
        dx, dy = px - self.x, py - self.y
        if self.circle:
            return max(0.0, math.hypot(dx, dy) - self.sx)
        r00, r01, r10, r11 = self.rot
        lx, ly = r00 * dx + r10 * dy, r01 * dx + r11 * dy
        return math.hypot(max(abs(lx) - self.sx, 0.0), max(abs(ly) - self.sy, 0.0))


@functools.lru_cache(maxsize=1)
def _solids() -> tuple[tuple[_Solid, ...], tuple[_Solid, ...], tuple[_Solid, ...]]:
    """``(bench, people, everything else)`` — read from the MJCF, never typed."""

    model = mujoco.MjModel.from_xml_path(str(SCENE))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    out: list[_Solid] = []
    for gid in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, gid) or ""
        if not is_logical_obstacle_name(name):
            continue
        gtype = int(model.geom_type[gid])
        gx, gy, gz = (float(v) for v in data.geom_xpos[gid, :3])
        size = [float(v) for v in model.geom_size[gid, :3]]
        if gtype == mujoco.mjtGeom.mjGEOM_BOX:
            half_z = size[2]
        elif gtype == mujoco.mjtGeom.mjGEOM_SPHERE:
            half_z = size[0]
        elif gtype == mujoco.mjtGeom.mjGEOM_CYLINDER:
            half_z = size[1]
        elif gtype == mujoco.mjtGeom.mjGEOM_CAPSULE:
            half_z = size[1] + size[0]
        else:
            continue
        if gz - half_z > DEFAULT_ROBOT_PROFILE.obstacle_clearance_height_m:
            continue  # the scan passes under it
        matrix = data.geom_xmat[gid]
        rot = (float(matrix[0]), float(matrix[1]), float(matrix[3]), float(matrix[4]))
        out.append(
            _Solid(name, gtype != mujoco.mjtGeom.mjGEOM_BOX, gx, gy, size[0], size[1], rot)
        )
    bench = tuple(s for s in out if s.name in BENCH_GEOMS)
    people = tuple(s for s in out if s.name.startswith(PERSON_PREFIXES))
    other = tuple(s for s in out if s not in bench and s not in people)
    assert bench and people and other
    return bench, people, other


@functools.lru_cache(maxsize=1)
def _bench_anchor() -> tuple[tuple[float, float], float]:
    truth = json.loads((REPO / "evals/nav_instruct/scene_truth.json").read_text())["derived"]
    entry = truth["bench_1"]
    return (float(entry["position"][0]), float(entry["position"][1])), float(entry["radius_m"])


def _sweep(band: tuple[float, float], *, bearings: int = 721, radii: int = 61):
    """Yield ``(x, y, d_bench, d_people, d_other)`` over the whole annulus."""

    bench, people, other = _solids()
    (ax, ay), _ = _bench_anchor()
    lo, hi = band
    for i in range(bearings):
        theta = 2.0 * math.pi * i / (bearings - 1)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        for j in range(radii):
            r = lo + (hi - lo) * j / (radii - 1)
            px, py = ax + r * cos_t, ay + r * sin_t
            yield (
                px,
                py,
                min(s.distance(px, py) for s in bench),
                min(s.distance(px, py) for s in people),
                min(s.distance(px, py) for s in other),
            )


# ---------------------------------------------------------------------------
# 1. the inequality — the defect, and what removed it
# ---------------------------------------------------------------------------


def test_the_defect_was_an_anchor_sized_band_and_the_fix_is_a_fixed_width_one() -> None:
    """One statement of the whole change, in the two authorities' own terms."""

    envelope = DEFAULT_STAND_OFF_ENVELOPE
    _, radius = _bench_anchor()
    assert radius == pytest.approx(0.733757)

    # BEFORE: outer edge fixed at 1.5 m from the CENTRE, so the usable width was
    # 1.5 - minimum_vicinity(R) and went negative at R = 0.38 m.
    superseded_hi = _superseded_centre_band(radius)[1]
    assert superseded_hi - envelope.minimum_vicinity(radius) == pytest.approx(
        -0.353757, abs=1e-6
    )

    # AFTER: outer edge 1.5 m from the SURFACE, so the usable width is a
    # constant that R cancels out of entirely.
    band = next_to_band_from_centre(radius)
    assert band == pytest.approx((radius + 0.4, radius + 1.5))
    assert band[1] - envelope.minimum_vicinity(radius) == pytest.approx(
        next_to_band_surface_slack_m()
    )
    assert next_to_band_surface_slack_m() == pytest.approx(0.38)
    assert next_to_is_achievable(radius)


@pytest.mark.parametrize("radius_m", [0.0, 0.06, 0.38, 0.45, 0.58, 0.733757, 2.408, 50.0])
def test_no_anchor_size_can_empty_the_band_any_more(radius_m: float) -> None:
    """Including a synthetic anchor 68x the bench's radius."""

    assert next_to_is_achievable(radius_m)
    band = next_to_band_from_centre(radius_m)
    assert band[1] - band[0] == pytest.approx(NEXT_TO_BAND_M[1] - NEXT_TO_BAND_M[0])
    assert band[1] >= DEFAULT_STAND_OFF_ENVELOPE.minimum_vicinity(radius_m)
    # ...and under the superseded centre-anchored band, anything above 0.38 m
    # was refused — which is the measurement this test used to make.
    superseded_ok = _superseded_centre_band(radius_m)[
        1
    ] >= DEFAULT_STAND_OFF_ENVELOPE.minimum_vicinity(radius_m)
    assert superseded_ok is (radius_m <= 0.38 + 1e-9)


def test_a_genuinely_unreachable_affordance_is_still_refused() -> None:
    """The predicate is still load-bearing; what it refuses is now the BODY.

    Surface anchoring removed the anchor-size failure mode by construction, so
    the honest remaining question is whether *this embodiment* can stand in the
    band at all. A body whose footprint plus comfort clearance exceeds the
    band's outer edge cannot stand beside anything — a pole, a bench, or a city
    block — and the predicate says so for every one of them.
    """

    envelope = DEFAULT_STAND_OFF_ENVELOPE
    big_body = dataclasses.replace(
        envelope,
        envelope=dataclasses.replace(envelope.envelope, footprint_radius_m=0.9),
    )
    assert next_to_band_surface_slack_m(envelope=big_body) == pytest.approx(-0.2)
    for radius in (0.0, 0.06, 0.733757, 2.408, 50.0):
        assert not next_to_is_achievable(radius, envelope=big_body)

    # A band narrower than the body's own comfort envelope is refused too, at
    # every anchor size — the same inequality read from the other side.
    for radius in (0.0, 0.733757, 50.0):
        assert not next_to_is_achievable(radius, band_m=(0.4, 1.0))
        assert next_to_is_achievable(radius, band_m=(0.4, 1.12))


def test_the_band_is_not_empty_as_a_point_set_which_is_why_the_old_check_passed()  -> None:
    """The superseded sidecar check asked the wrong question, and still would.

    ``max(band_lo, footprint) <= band_hi`` is a statement about a point set. It
    passed for the bench under the centre-anchored band, when no *body* could
    stand anywhere in that band. It is kept alongside the real check so the two
    questions stay visibly distinct.
    """

    centre, radius = _bench_anchor()
    region = object_next_to_goal_region(centre, radius, entity_id="bench_1")
    assert region.band_m is not None
    assert max(region.band_m[0], region.anchor_footprint_m) <= region.band_m[1]
    # The point set was never empty, even under the superseded band...
    superseded = _superseded_centre_band(radius)
    assert max(superseded[0], radius) <= superseded[1]
    # ...and a point 1.0 m from the centre was in it: 0.27 m from the bench's
    # own surface, well inside the runtime gate's 0.97 m centre-to-surface stop.
    # Under the surface band that point is outside the region, because the
    # region now begins where a body can be.
    assert max(superseded[0], radius) <= 1.0 <= superseded[1]
    assert not region.contains(centre[0], centre[1] - 1.0)
    assert region.contains(centre[0], centre[1] - 2.0)


# ---------------------------------------------------------------------------
# 2. the scene under the superseded band: (a) TODAY-as-of-B-1, (c) the perimeter
# ---------------------------------------------------------------------------


def test_no_pose_in_the_superseded_bench_band_cleared_the_shipping_envelopes() -> None:
    """(a) Re-derived from the MJCF, all four sides, at the centre-anchored band."""

    _centre, radius = _bench_anchor()
    band = _superseded_centre_band(radius)
    person_zone = DEFAULT_SAFETY_ENVELOPE.person_social_zone_m
    admissible = [
        (x, y)
        for x, y, db, dp, do in _sweep(band)
        if db >= SOLVER_CLEARANCE_M and dp >= person_zone and do >= SOLVER_CLEARANCE_M
    ]
    assert admissible == [], admissible[:5]


def _best_slack_per_bearing(
    band: tuple[float, float],
    *,
    bearings: int = 360,
    radii: int = 61,
) -> dict[int, float]:
    """Per bearing, the best achievable *slack* over every requirement at once.

    Slack is ``min(d_bench, d_people - person_zone + solver, d_other) - solver``
    expressed as the worst of the three margins, maximised over the radii the
    band admits. Non-negative on some bearing means a pose exists there.
    """

    bench, people, other = _solids()
    (ax, ay), _ = _bench_anchor()
    person_zone = DEFAULT_SAFETY_ENVELOPE.person_social_zone_m
    lo, hi = band
    out: dict[int, float] = {}
    for i in range(bearings):
        theta = 2.0 * math.pi * i / bearings
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        best = -math.inf
        for j in range(radii):
            r = lo + (hi - lo) * j / (radii - 1)
            px, py = ax + r * cos_t, ay + r * sin_t
            best = max(
                best,
                min(
                    min(s.distance(px, py) for s in bench) - SOLVER_CLEARANCE_M,
                    min(s.distance(px, py) for s in people) - person_zone,
                    min(s.distance(px, py) for s in other) - SOLVER_CLEARANCE_M,
                ),
            )
        out[round(math.degrees(theta)) % 360] = best
    return out


def test_the_perimeter_was_genuinely_searched_and_still_empty_on_every_side() -> None:
    """(c) The polar sampler has no world-frame bias; the *band* is what failed.

    Unlike ``nearest_point_in_region``'s inset sampler (which anchored a
    rectangular lattice at ``(min_x, min_y)`` and so under-reported distance
    from a region's ``max`` side — card F-3(b)), this lattice is uniform in
    bearing and has no preferred axis. So "only the long faces were searched"
    is not the explanation: **every bearing was searched and every bearing was
    short.** The best slack anywhere on the perimeter is -0.382 m, at bearing
    29 degrees (the north-east quadrant, between the bench's east short end and
    ``bldg_2``); due east is -0.400 m and due south -0.437 m.
    """

    _, radius = _bench_anchor()
    band = _superseded_centre_band(radius)
    slack = _best_slack_per_bearing(band)
    assert len(slack) == 360
    assert max(slack.values()) < 0.0, max(slack.items(), key=lambda kv: kv[1])
    assert max(slack.values()) == pytest.approx(-0.382, abs=0.02)
    # No side is privileged: the distance-to-bench profile is symmetric about
    # the bench's own axes, which is what an unbiased polar lattice looks like.
    bench_only = {}
    for x, y, db, _dp, _do in _sweep(band, bearings=361, radii=61):
        (ax, ay), _ = _bench_anchor()
        deg = round(math.degrees(math.atan2(y - ay, x - ax))) % 360
        bench_only[deg] = max(bench_only.get(deg, -1.0), db)
    for deg in (15, 45, 75):
        # East/west is the axis a (min_x, min_y) lattice bias would break, and
        # it is exact.
        assert bench_only[deg] == pytest.approx(bench_only[(180 - deg) % 360], abs=2e-2)
    # North/south is NOT symmetric, and the asymmetry is a property of the
    # anchor rather than of the sampler: the semantic centre is y=3.045 while
    # the union of the bench solids is centred at y=3.005, so every northern
    # bearing gains what the matching southern one loses.
    centre_offset = 3.045 - 3.005  # semantic centre minus solid-union centre
    for deg in (15, 45, 75):
        gap = bench_only[deg] - bench_only[(360 - deg) % 360]
        assert 0.0 < gap <= 2.0 * centre_offset + 1e-6, (deg, gap)
    # The short-axis normals are the best bearings against the bench alone —
    # north is 1.315 m, south 1.235 m, both clearing the 1.20 m requirement.
    # They are nonetheless inadmissible: bldg_1's face is 0.77 m north of the
    # bench back, and pedestrian_5 stands 1.342 m from the bench centre.
    assert bench_only[90] == pytest.approx(1.315, abs=1e-2)
    assert bench_only[270] == pytest.approx(1.235, abs=1e-2)
    assert slack[90] < 0.0 and slack[270] < 0.0


def test_the_best_pose_that_cleared_the_rest_of_the_scene_was_inside_the_gate() -> None:
    """No solver margin could rescue it: the gate itself forbade the whole band.

    Restricted to poses that already clear every *other* solid and every
    person, the greatest achievable distance to the bench's own surface was
    0.78 m over the whole superseded band (0.68 m over its planning inset) —
    inside the unconditional reactive gate's centre-to-surface stop envelope
    (0.97 m). The robot could not stand there even if the approach solver asked
    it to, so no loosening of the solver's own margin could open this case.
    Only moving the band could, which is what card S-1 did.
    """

    _, radius = _bench_anchor()
    band = _superseded_centre_band(radius)
    person_zone = DEFAULT_SAFETY_ENVELOPE.person_social_zone_m
    best = max(
        (
            db
            for _x, _y, db, dp, do in _sweep(band)
            if dp >= person_zone and do >= SOLVER_CLEARANCE_M
        ),
        default=-1.0,
    )
    assert best == pytest.approx(0.78, abs=0.02)
    assert best < RUNTIME_GATE_CLEARANCE_M
    assert RUNTIME_GATE_CLEARANCE_M == pytest.approx(0.97)


# ---------------------------------------------------------------------------
# 3. (b) relaxing the terminal person clearance could not have helped
# ---------------------------------------------------------------------------


def test_the_planning_band_was_empty_even_if_the_dog_may_touch_the_pedestrian() -> None:
    """(b), first refutation: the *bench* forbade it, so the person was moot.

    Over the whole superseded planning band the greatest distance to the bench
    surface was 1.195 m against a 1.20 m requirement — and that maximum is due
    north, 0.20 m from ``bldg_1``'s face.
    """

    _, radius = _bench_anchor()
    inset = NEXT_TO_ARRIVAL_FLOOR_M + DEFAULT_STAND_OFF_ENVELOPE.stand_off_margin_m
    superseded = _superseded_centre_band(radius)
    band = (max(superseded[0] + inset, radius), superseded[1] - inset)
    rows = list(_sweep(band))
    assert [
        (x, y) for x, y, db, _dp, do in rows if db >= SOLVER_CLEARANCE_M and do >= SOLVER_CLEARANCE_M
    ] == []
    # ...and with NO person clearance whatsoever, still empty.
    assert [(x, y) for x, y, db, _dp, _do in rows if db >= SOLVER_CLEARANCE_M] == []
    assert max(db for _x, _y, db, _dp, _do in rows) == pytest.approx(1.195, abs=5e-3)


def test_the_terminal_clearance_that_would_open_the_band_is_inside_the_gate() -> None:
    """(b), second refutation: the relaxation was unreachable, not just unwise.

    Ignoring the planning inset entirely and searching the raw superseded band,
    poses appear only once the terminal person clearance drops to 0.651 m
    centre-to-person-surface — 0.331 m footprint-to-surface. That is inside the
    unconditional reactive gate's 0.65 m obstacle stop, so the body is hard-
    stopped before it can reach such a pose. The gate below is the shipping
    one, unmodified, and this test exists to keep it that way.
    """

    _, radius = _bench_anchor()
    band = _superseded_centre_band(radius)
    rows = list(_sweep(band))

    def opens(person_clearance: float) -> bool:
        return any(
            db >= SOLVER_CLEARANCE_M and dp >= person_clearance and do >= SOLVER_CLEARANCE_M
            for _x, _y, db, dp, do in rows
        )

    lo, hi = 0.0, DEFAULT_SAFETY_ENVELOPE.person_social_zone_m
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if opens(mid) else (lo, mid)
    footprint_to_surface = lo - DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m
    # 0.651 m at the reporting resolution (3601 x 551); this lattice is coarser,
    # so it can only ever under-report the opening threshold.
    assert lo == pytest.approx(0.65, abs=0.02)
    assert footprint_to_surface == pytest.approx(0.33, abs=0.02)

    policy = ReactiveSafetyPolicy()
    assert footprint_to_surface < policy.obstacle_stop_m
    assert footprint_to_surface < policy.person_stop_m


def test_the_unconditional_gate_still_zeroes_translation_at_that_clearance() -> None:
    """The gate is consumed, never retuned: a person that close stops the body.

    Asserted for both channels the static and dynamic cities use — a stationary
    pedestrian arrives as an *obstacle* return in the static city (it is not a
    social track when ``dynamic_city`` is disabled) and as ``nearest_person_m``
    in the dynamic one. Either way, translation is zero. **Nothing in the S-1
    band change touches this**: re-anchoring an arrival band cannot move a stop
    distance, and this test is what says so.
    """

    from parcel_robot.backends.base import (
        LidarObstacle,
        OwnerTrack,
        RobotPose,
        SimObservation,
    )

    policy = ReactiveSafetyPolicy()
    gap = 0.331  # footprint-to-surface, the clearance (b) would have needed
    command = VelocityCommand(vx=0.35, vy=0.0, vyaw=0.0)

    as_obstacle = SimObservation(
        timestamp=1000.0,
        robot=RobotPose(x=0.0, y=0.0, z=0.0, yaw=0.0),
        owner=OwnerTrack(x=50.0, y=50.0, visible=False),
        nearest_obstacle_m=gap,
        nearest_obstacle_bearing_rad=0.0,
        lidar_obstacles=(
            LidarObstacle(obstacle_id="pedestrian_5_body", distance_m=gap, bearing_rad=0.0),
        ),
    )
    gated, note = apply_reactive_safety(
        command, as_obstacle, policy=policy, now=1000.0, require_fresh_telemetry=False
    )
    assert (gated.vx, gated.vy) == (0.0, 0.0), note
    assert note == "stopped"

    as_person = SimObservation(
        timestamp=1000.0,
        robot=RobotPose(x=0.0, y=0.0, z=0.0, yaw=0.0),
        owner=OwnerTrack(x=50.0, y=50.0, visible=False),
        nearest_person_m=gap,
        nearest_person_bearing_rad=0.0,
    )
    gated, note = apply_reactive_safety(
        command, as_person, policy=policy, now=1000.0, require_fresh_telemetry=False
    )
    assert (gated.vx, gated.vy) == (0.0, 0.0), note
    assert note == "stopped"


# ---------------------------------------------------------------------------
# 4. the fix, measured in the live scene
# ---------------------------------------------------------------------------


def test_the_surface_anchored_band_opens_the_bench_at_full_clearances() -> None:
    """The K0 change, measured against the true MJCF geometry.

    The *same* 1.1 m-wide band offset to the anchor's surface opens ``bench_1``
    at full shipping clearances — the 1.20 m solver clearance to every solid
    and the 1.20 m person social zone to every pedestrian — on a narrow arc off
    the bench's east end. It is a sliver, not a comfortable set, and the arc's
    width is exactly why the lattice density had to move with the band.
    """

    _, radius = _bench_anchor()
    plan = _next_to_planning_band(NEXT_TO_ARRIVAL_FLOOR_M, radius)
    person_zone = DEFAULT_SAFETY_ENVELOPE.person_social_zone_m
    admissible = [
        (x, y)
        for x, y, db, dp, do in _sweep(plan)
        if db >= SOLVER_CLEARANCE_M and dp >= person_zone and do >= SOLVER_CLEARANCE_M
    ]
    assert admissible, "the surface-anchored band must open a pose"
    (ax, ay), _ = _bench_anchor()
    bearings = [
        math.degrees(math.atan2(y - ay, x - ax)) % 360.0 for x, y in admissible
    ]
    assert min(bearings) == pytest.approx(332.5, abs=1.0)
    assert max(bearings) == pytest.approx(336.2, abs=1.0)


def test_the_lattice_density_travelled_with_the_band_and_now_resolves_that_arc() -> None:
    """24 bearings missed a 3.7-degree arc entirely; 72 find it.

    This is the pair the density raise exists for, and it is asserted as a pair:
    the shipped lattice must now find the pose the band opens, and the
    superseded 24-bearing lattice must be shown unable to. Raising the density
    *before* the band change would have found nothing (no anchor had a non-empty
    set) while perturbing the one live ``next_to`` case that passed, which is
    why it travelled with it.
    """

    bench, people, other = _solids()
    centre, radius = _bench_anchor()
    person_zone = DEFAULT_SAFETY_ENVELOPE.person_social_zone_m
    plan = _next_to_planning_band(NEXT_TO_ARRIVAL_FLOOR_M, radius)

    def occupied(px: float, py: float) -> bool:
        return (
            min(s.distance(px, py) for s in bench) < SOLVER_CLEARANCE_M
            or min(s.distance(px, py) for s in people) < person_zone
            or min(s.distance(px, py) for s in other) < SOLVER_CLEARANCE_M
        )

    assert (PLACEMENT_BEARINGS, PLACEMENT_RADII) == (72, 5)
    assert 360.0 / PLACEMENT_BEARINGS == pytest.approx(5.0)

    placement = next_to_placement(
        centre, radius, (0.0, 0.0), band_m=plan, occupied=occupied
    )
    assert placement is not None, "the shipped lattice must resolve the opened arc"
    x, y, _heading = placement
    assert not occupied(x, y)
    # And the pose it returns is one the arrival authority will certify.
    assert object_next_to_goal_region(centre, radius, entity_id="bench_1").contains(x, y)

    # The superseded density, on the same band and the same scene: nothing.
    def _placement_at(bearings: int):
        lo, hi = plan
        best = None
        for index in range(bearings):
            theta = index * 2.0 * math.pi / bearings
            for j in range(PLACEMENT_RADII):
                r = lo + (hi - lo) * j / (PLACEMENT_RADII - 1)
                px, py = centre[0] + r * math.cos(theta), centre[1] + r * math.sin(theta)
                if not occupied(px, py):
                    best = (px, py)
        return best

    assert _placement_at(24) is None
    assert _placement_at(48) is None
    assert _placement_at(64) is None
    assert _placement_at(72) is not None


def test_next_to_placement_refuses_to_invent_a_band() -> None:
    """One band. The retired ``(0.4, 0.9)`` default was a second one."""

    with pytest.raises(TypeError):
        next_to_placement((0.0, 0.0), 0.3, (3.0, 0.0))  # type: ignore[call-arg]
