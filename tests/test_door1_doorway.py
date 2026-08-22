"""Card DOOR-1 — through a doorway, and a follow stand-off that obeys config.

Design DW-4 (``scrum/20260822/WAVE2_DESIGN_FABLE.md`` §1). Four claims, and the
rows that make each of them falsifiable:

1. **The obstacle ring is a config with a named floor.** ``safety.obstacle_stop_m``
   COMMISSIONS ``SafetyEnvelope.obstacle_stop_floor_m`` through
   ``with_obstacle_stop_ring``; under it sits ``OBSTACLE_STOP_FLOOR_M`` (0.41 m),
   the body's ISO/TS-15066 stopping distance at the APPROACH regime. Below the
   floor the runtime refuses to boot and names the number.
2. **The planner and the final gate derive from ONE immutable profile.**
   ``ClearanceProfile`` states the ring once; ``planner_inflation_m`` and
   ``final_gate_ring_m`` come off it, the second recomputed independently of the
   planner, and both monotone in the ring.
3. **Both production ``GridPlannerConfig`` sites pass a float, never ``None``.**
   ``grid_navigator.py`` and ``search_owner.py``.
4. **No import-time stand-off constant decides profile-dependent behaviour.**
   ``FollowConfig.owner_keepout_m`` / ``desired_distance_m`` derive per instance.

**UNCOMMISSIONED — read this before believing any distance below.** No robot
hardware is on hand (owner, 2026-08-22: only the reSpeaker XVF3800 mic array).
0.41 m, 0.45 m and every corridor width here are arithmetic over in-tree body
constants and a synthetic lidar corridor in the dev simulator. Not one of them
is a measured physical clearance, and the 0.45 m band is SIMULATOR POLICY that
ships only inside ``configs/robot.prototype.yaml``. The shipped
``configs/robot.yaml`` still carries 0.65 m and 1.2 m.
"""

from __future__ import annotations

import ast
import math
import time
from itertools import pairwise
from pathlib import Path

import pytest

import parcel_robot
from parcel_robot.authority import (
    DEFAULT_CLEARANCE_PROFILE,
    DEFAULT_SAFETY_ENVELOPE,
    DEFAULT_SPEED_REGIME,
    GATE_TOWARD_HALF_ANGLE_RAD,
    LEGACY_GATE_CLEARANCE_M,
    OBSTACLE_STOP_FLOOR_M,
    PERSON_SOCIAL_ZONE_FLOOR_M,
    PLANNER_HARD_MARGIN_M,
    ClearanceProfile,
    SafetyEnvelope,
    gate_lateral_clearance_m,
)
from parcel_robot.backends.base import (
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SimObservation,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.base import GoalPose, Mission, NavObservation
from parcel_robot.navigation.follow import FollowConfig
from parcel_robot.navigation.grid_planner import (
    GridPlannerConfig,
    LidarScan,
    Pose2D,
    RollingGridPlanner,
)
from parcel_robot.navigation.reactive_safety import (
    OWNER_STAND_OFF_MARGIN_M,
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)
from parcel_robot.navigation.registry import ModelRegistry

REPO = Path(__file__).resolve().parents[1]
#: Resolved from the IMPORTED package rather than from the repo layout, so a
#: seeded scratch copy of ``src/`` on PYTHONPATH reddens the static site check
#: too, not only the dynamic one.
SRC = Path(parcel_robot.__file__).resolve().parent
MODELS_ROOT = REPO / "configs" / "navigation" / "models"
PROTOTYPE_YAML = REPO / "configs" / "robot.prototype.yaml"

#: The indoor ring `configs/robot.prototype.yaml` commissions. Simulator policy.
PROTOTYPE_RING_M = 0.45
#: The ring `configs/robot.yaml` ships.
SHIPPED_RING_M = 0.65


# ---------------------------------------------------------------------------
# 1. the floor: named, derived, and a refusal
# ---------------------------------------------------------------------------


def test_the_obstacle_floor_is_the_bodys_stopping_distance_at_approach() -> None:
    """0.41 m is not a taste. It is ``stop_distance(SpeedRegime.approach.vx)``.

    Written in ``authority.py`` as a literal on purpose (a floor that moves when
    someone retunes ``linear_decel`` is not a floor), so this is the test that
    reddens if the literal and its derivation ever part company.
    """

    approach_vx = DEFAULT_SPEED_REGIME.approach.vx_mps
    assert approach_vx == 0.35
    derived = DEFAULT_SAFETY_ENVELOPE.stop_distance(approach_vx)
    assert derived == pytest.approx(0.405750, abs=5e-7)
    assert OBSTACLE_STOP_FLOOR_M == round(derived, 2) == 0.41


def test_the_floor_is_above_the_hull_and_below_the_person_floor() -> None:
    """The two properties that make 0.41 m the RIGHT floor rather than a small one.

    1. Above the hull ``stop_distance(0.0)`` = footprint + Zs + Zr = 0.32 m, so
       no commissioning can put the stop ring inside the robot's own body.
    2. Below ``PERSON_SOCIAL_ZONE_FLOOR_M`` = 0.68 m, which preserves card
       P1-E's property 1: a person can never be commissioned LESS clearance
       than a wall.
    """

    assert DEFAULT_SAFETY_ENVELOPE.stop_distance(0.0) == pytest.approx(0.32)
    assert OBSTACLE_STOP_FLOOR_M > DEFAULT_SAFETY_ENVELOPE.stop_distance(0.0)
    assert OBSTACLE_STOP_FLOOR_M < PERSON_SOCIAL_ZONE_FLOOR_M


def test_an_under_floor_obstacle_ring_refuses_and_names_the_floor() -> None:
    """A refusal, not a clamp — and the message carries the key AND the number."""

    with pytest.raises(ValueError) as raised:
        ReactiveSafetyPolicy(obstacle_stop_m=0.40)
    message = str(raised.value)
    assert "obstacle_stop_m" in message
    assert "OBSTACLE_STOP_FLOOR_M" in message
    assert "0.41" in message

    # ...and the floor itself, and the prototype's ring, both construct.
    assert ReactiveSafetyPolicy(obstacle_stop_m=0.41).obstacle_stop_m == 0.41
    assert (
        ReactiveSafetyPolicy(obstacle_stop_m=PROTOTYPE_RING_M).obstacle_stop_m
        == PROTOTYPE_RING_M
    )


def test_every_envelope_construction_path_lands_on_the_obstacle_floor() -> None:
    """``from_mapping`` / ``from_profile`` / ``replace`` / ``with_obstacle_stop_ring``."""

    for build in (
        lambda: SafetyEnvelope(obstacle_stop_floor_m=0.40),
        lambda: SafetyEnvelope.from_mapping({"obstacle_stop_floor_m": 0.40}),
        lambda: SafetyEnvelope.from_profile(
            __import__(
                "parcel_robot.robot_profile", fromlist=["DEFAULT_ROBOT_PROFILE"]
            ).DEFAULT_ROBOT_PROFILE,
            obstacle_stop_floor_m=0.40,
        ),
        lambda: DEFAULT_SAFETY_ENVELOPE.with_obstacle_stop_ring(0.40),
    ):
        with pytest.raises(ValueError, match="OBSTACLE_STOP_FLOOR_M"):
            build()


def test_the_obstacle_ring_may_not_sit_inside_a_wider_bodys_hull() -> None:
    """The physics floor, which binds only for an INJECTED envelope.

    At Go2 scale the 0.41 m commissioning floor dominates the 0.32 m hull, so
    this branch is unreachable there. Give the body a 0.9 m footprint and it is
    the binding one. The test exists so the branch cannot be deleted as dead
    code — the same argument P1-E made for its person twin.
    """

    wide = SafetyEnvelope(footprint_radius_m=0.9)
    assert wide.stop_distance(0.0) == pytest.approx(0.9)
    with pytest.raises(ValueError, match=r"must not undercut\s+SafetyEnvelope\.stop_distance"):
        ReactiveSafetyPolicy(obstacle_stop_m=0.5, envelope=wide)


# ---------------------------------------------------------------------------
# 2. the shipped defaults did not move
# ---------------------------------------------------------------------------


def test_the_shipped_envelope_and_policy_are_untouched() -> None:
    """The whole card must be invisible to anything that did not opt in."""

    assert DEFAULT_SAFETY_ENVELOPE.as_dict() == {
        "footprint_radius_m": 0.32,
        "reaction_latency_s": 0.12,
        "decel_max_mps2": 1.4,
        "sensing_intrusion_m": 0.0,
        "pose_uncertainty_m": 0.0,
        "person_social_zone_m": 1.2,
        "person_latency_s": 0.168,
        "obstacle_comfort_band_m": 1.2,
        "person_comfort_band_m": 2.5,
        "obstacle_stop_floor_m": 0.6,
    }
    policy = ReactiveSafetyPolicy()
    assert policy.obstacle_stop_m == SHIPPED_RING_M
    assert policy.person_stop_m == 1.2
    assert policy.owner_slow_m == 1.3


def test_the_shipped_follow_stand_off_family_is_bit_identical() -> None:
    """1.75 / 1.85 by exact IEEE equality, not ``approx``.

    Card DOOR-1 changed WHERE these come from (import-time constant -> derived
    per instance). If it had also changed WHAT they are, every FOLLOW_BENCH row
    would move. ``==`` rather than ``approx`` so a re-tuned literal cannot hide
    inside a tolerance.
    """

    config = FollowConfig()
    assert config.owner_keepout_m == 1.2 + 0.55
    assert config.desired_distance_m == 1.2 + 0.55 + OWNER_STAND_OFF_MARGIN_M
    assert config.owner_keepout_m == 1.75
    assert config.desired_distance_m == 1.85


def test_the_legacy_planner_inflation_is_bit_identical() -> None:
    """The un-commissioned default ring reproduces 0.42 m exactly.

    ``LEGACY_GATE_CLEARANCE_M`` is defined as ``(footprint + hard_margin) /
    sin(half_angle)``, so running it back through the gate's cone must return
    the footprint term itself — the property that makes wiring the coupling at
    the un-commissioned default a no-op for every frozen navigation baseline.
    """

    legacy = DEFAULT_SAFETY_ENVELOPE.footprint_radius_m + PLANNER_HARD_MARGIN_M
    assert gate_lateral_clearance_m(LEGACY_GATE_CLEARANCE_M) == legacy
    assert DEFAULT_CLEARANCE_PROFILE.planner_inflation_m == legacy
    assert GridPlannerConfig().inflation_radius_m == legacy
    assert GridPlannerConfig(
        gate_clearance_m=DEFAULT_CLEARANCE_PROFILE.obstacle_ring_m
    ).inflation_radius_m == legacy


def test_every_grid_model_profile_keeps_its_legacy_inflation() -> None:
    """The bit-identity claim, on EVERY shipped grid profile, not just the default.

    Verifier catch (correction pass). The original claim held only at the
    default 0.10 m hard margin. ``configs/navigation/models/grid_clearance.yaml``
    runs ``map_hard_safety_margin_m: 0.03`` — a 0.35 m footprint term — and a
    coupling capped at the flat module-level ``LEGACY_GATE_CLEARANCE_M``
    (0.4601 m, whose lateral demand is 0.42 m) would have raised it 0.35 -> 0.42
    without anybody noticing. The cap is per-profile now
    (``ClearanceProfile.legacy_equivalent_ring_m``), and this walks every grid
    profile in the tree through the PRODUCT constructor to prove it.

    Exact equality, not ``approx``: a moved planner route is a moved frozen
    baseline, and a tolerance would hide one.
    """

    registry = ModelRegistry.load(MODELS_ROOT)
    checked = 0
    for model_id in sorted(registry.ids()):
        if registry.get(model_id).type != "grid":
            continue
        navigator = registry.create(model_id, arrive_radius_m=1.5)
        try:
            config = navigator._planner.config
            legacy = config.robot_radius_m + config.effective_hard_margin_m
            assert config.gate_clearance_m is not None, model_id
            assert config.inflation_radius_m == legacy, (
                f"{model_id}: coupling moved the hard inflation "
                f"{legacy} -> {config.inflation_radius_m}; that is a frozen "
                "navigation baseline moving as a side effect of wiring a seam"
            )
            checked += 1
        finally:
            navigator.close()
    assert checked >= 9, f"only {checked} grid profiles walked"


def test_the_coupling_is_tighter_only_and_says_when_it_is_deferred() -> None:
    """The scope of the coupling, stated as two booleans.

    Verifier catch (correction pass): site 2 was passing the RAW commissioned
    ring, which on the shipped ``configs/robot.yaml`` is 0.65 m — and
    ``evals/companion_nav/runner.py`` builds that controller for the
    follow-bench, so a frozen row would have moved. The coupling is capped at
    each profile's own legacy-equivalent ring. Where the cap binds, the planner
    and the gate still disagree and the card says so (HALTED item H-2) rather
    than closing it silently in either direction.
    """

    shipped = ReactiveSafetyPolicy().clearance_profile
    prototype = ReactiveSafetyPolicy(obstacle_stop_m=PROTOTYPE_RING_M).clearance_profile

    assert shipped.planner_coupling_is_deferred is True
    assert shipped.planner_coupling_ring_m == pytest.approx(LEGACY_GATE_CLEARANCE_M)
    assert shipped.planner_inflation_m == shipped.legacy_footprint_term_m
    # ...and the cost of closing H-2, stated by the profile itself.
    assert shipped.uncapped_planner_inflation_m == pytest.approx(0.593297, abs=5e-7)

    assert prototype.planner_coupling_is_deferred is False
    assert prototype.planner_coupling_ring_m == PROTOTYPE_RING_M
    assert prototype.planner_inflation_m == prototype.legacy_footprint_term_m

    # The per-profile cap: a 0.03 m hard margin gets a 0.383 m cap, not 0.460.
    tight = ClearanceProfile(obstacle_ring_m=SHIPPED_RING_M, planner_hard_margin_m=0.03)
    assert tight.legacy_footprint_term_m == pytest.approx(0.35)
    assert tight.legacy_equivalent_ring_m == pytest.approx(0.383451, abs=5e-7)
    assert tight.planner_inflation_m == tight.legacy_footprint_term_m


# ---------------------------------------------------------------------------
# 3. one immutable profile, two consumers, independent recomputation
# ---------------------------------------------------------------------------


def test_the_profile_is_immutable_and_states_the_ring_once() -> None:
    profile = ClearanceProfile(obstacle_ring_m=PROTOTYPE_RING_M)
    with pytest.raises(Exception):  # noqa: B017 — frozen dataclass, any raise is the point
        profile.obstacle_ring_m = 0.9  # type: ignore[misc]
    assert profile.with_ring(0.6).obstacle_ring_m == 0.6
    assert profile.obstacle_ring_m == PROTOTYPE_RING_M  # the original is untouched


def test_the_final_gate_ring_is_recomputed_from_the_profile_alone() -> None:
    """It matches what ``apply_reactive_safety`` enforces — computed independently.

    The gate's stop test is ``distance <= obstacle_stop_m + |v| * reaction_time_s``.
    ``ClearanceProfile.final_gate_ring_m`` restates that from the profile without
    consulting the planner, the planner's config, or any inflated radius. This
    test drives the REAL gate and bisects the distance at which it stops, then
    checks the profile predicted it.
    """

    for ring in (0.45, 0.55, SHIPPED_RING_M):
        policy = ReactiveSafetyPolicy(obstacle_stop_m=ring)
        profile = policy.clearance_profile
        for speed in (0.0, 0.25, 0.6):
            predicted = profile.final_gate_ring_m(speed)
            assert predicted == pytest.approx(ring + speed * 0.12)
            if speed == 0.0:
                continue
            # The gate stops at or inside the predicted ring, and moves outside it.
            assert _gate_stops_at(policy, distance_m=predicted - 1e-4, speed_mps=speed)
            assert not _gate_stops_at(policy, distance_m=predicted + 1e-3, speed_mps=speed)


def test_both_derived_quantities_are_monotone_in_the_ring() -> None:
    """Monotone non-decreasing: a bigger commissioned ring never buys slack.

    200 rings across the whole commissionable band, and 200 speeds. Monotonicity
    is what makes "the planner can never end up looser than the gate" a property
    rather than a hope.
    """

    rings = [OBSTACLE_STOP_FLOOR_M + index * (1.20 - OBSTACLE_STOP_FLOOR_M) / 199 for index in range(200)]
    inflations = [ClearanceProfile(obstacle_ring_m=ring).planner_inflation_m for ring in rings]
    gates = [ClearanceProfile(obstacle_ring_m=ring).final_gate_ring_m(0.5) for ring in rings]
    assert all(b >= a for a, b in pairwise(inflations))
    assert all(b >= a for a, b in pairwise(gates))

    profile = ClearanceProfile(obstacle_ring_m=PROTOTYPE_RING_M)
    speeds = [index / 199.0 for index in range(200)]
    rings_by_speed = [profile.final_gate_ring_m(speed) for speed in speeds]
    assert all(b >= a for a, b in pairwise(rings_by_speed))


def test_the_prototype_ring_makes_the_planner_and_the_gate_agree() -> None:
    """The card's actual claim, in one assertion each way.

    At the PROTOTYPE ring the planner's own footprint term (0.42 m) already
    exceeds the gate's lateral demand (0.4107 m), so the planner is the
    STRICTER of the two and never proposes a corridor the gate always refuses.
    At the SHIPPED ring it is the looser one — that is audit §6's disagreement,
    and it is why the ring had to move before the coupling could.
    """

    legacy_inflation = GridPlannerConfig().inflation_radius_m
    prototype = ClearanceProfile(obstacle_ring_m=PROTOTYPE_RING_M)
    shipped = ClearanceProfile(obstacle_ring_m=SHIPPED_RING_M)

    assert prototype.gate_lateral_clearance_m == pytest.approx(0.410744, abs=5e-7)
    assert shipped.gate_lateral_clearance_m == pytest.approx(0.593297, abs=5e-7)
    assert prototype.planner_agrees_with_gate(legacy_inflation) is True
    assert shipped.planner_agrees_with_gate(legacy_inflation) is False
    # And the coupling is a NO-OP at the prototype ring: same inflation, so no
    # planned route anywhere can move when the seam is finally closed.
    assert prototype.planner_inflation_m == legacy_inflation


# ---------------------------------------------------------------------------
# 4. both production construction sites pass a float, never None
# ---------------------------------------------------------------------------


PRODUCTION_PLANNER_SITES = (
    "navigation/grid_navigator.py",
    "navigation/search_owner.py",
)


@pytest.mark.parametrize("relative", PRODUCTION_PLANNER_SITES)
def test_every_production_planner_site_passes_gate_clearance(relative: str) -> None:
    """Static: no ``GridPlannerConfig(...)`` in the product omits the keyword.

    ``gate_clearance_m=None`` is the state audit §6 named — a planner with no
    opinion about the final gate, routing through corridors the gate refuses.
    Seeded RED by deleting the keyword at either site.
    """

    tree = ast.parse((SRC / relative).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "GridPlannerConfig"
    ]
    assert calls, f"{relative} no longer constructs a GridPlannerConfig"
    for call in calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert "gate_clearance_m" in keywords, (
            f"{relative}:{call.lineno} builds a GridPlannerConfig without "
            "gate_clearance_m — the planner would plan blind to the final gate"
        )
        value = keywords["gate_clearance_m"]
        assert not (
            isinstance(value, ast.Constant) and value.value is None
        ), (
            f"{relative}:{call.lineno} passes gate_clearance_m=None, which is "
            "the keyword without the meaning"
        )


def test_the_grid_navigator_planner_is_never_built_with_none() -> None:
    """Dynamic: the object the product actually builds carries a float."""

    registry = ModelRegistry.load(MODELS_ROOT)
    navigator = registry.create("grid_v1", arrive_radius_m=1.5)
    try:
        config = navigator._planner.config
        assert config.gate_clearance_m is not None
        assert config.gate_clearance_m == DEFAULT_CLEARANCE_PROFILE.obstacle_ring_m
        # ...and a commissioned caller gets its own ring through.
        commissioned = registry.create(
            "grid_v1", arrive_radius_m=1.5, map_gate_clearance_m=PROTOTYPE_RING_M
        )
        try:
            assert commissioned._planner.config.gate_clearance_m == PROTOTYPE_RING_M
        finally:
            commissioned.close()
    finally:
        navigator.close()


def test_the_owner_search_planner_takes_the_runtimes_own_commissioned_ring() -> None:
    """Site 2 does not need a new seam: it already holds the commissioned gate.

    ``runtime.py:1809`` injects the runtime's own ``ReactiveSafetyPolicy``, so
    the prototype's 0.45 m ring reaches this planner for real — the only
    production planner in the tree that is genuinely commissioned today.
    """

    from parcel_robot.navigation.search_owner import SearchOwnerController

    policy = ReactiveSafetyPolicy(obstacle_stop_m=PROTOTYPE_RING_M)
    controller = SearchOwnerController(safety_policy=policy)
    controller._update_map(_corridor_observation(1.20, policy=policy))
    assert controller._planner is not None
    assert controller._planner.config.gate_clearance_m == PROTOTYPE_RING_M


def test_the_owner_search_planner_keeps_its_legacy_inflation_when_shipped() -> None:
    """The frozen-evidence guard on site 2 (verifier catch, correction pass).

    ``evals/companion_nav/runner.py:213`` constructs ``SearchOwnerController``
    and the follow-bench is a hard-safety gate row. Passing the RAW commissioned
    ring moved this planner's hard inflation 0.42 -> 0.5933 m on the SHIPPED
    profile — measured at the search planner's own 0.20 m grid, the inflated
    non-traversable set around a point obstacle grew 18 -> 30 cells (+67%).
    Seeded RED (S6).
    """

    from parcel_robot.navigation.search_owner import SearchOwnerController

    for policy, expected_ring in (
        (ReactiveSafetyPolicy(), LEGACY_GATE_CLEARANCE_M),
        (ReactiveSafetyPolicy(obstacle_stop_m=PROTOTYPE_RING_M), PROTOTYPE_RING_M),
    ):
        controller = SearchOwnerController(safety_policy=policy)
        controller._update_map(_corridor_observation(1.20, policy=policy))
        config = controller._planner.config
        assert config.gate_clearance_m == pytest.approx(expected_ring)
        assert config.inflation_radius_m == (
            config.robot_radius_m + config.effective_hard_margin_m
        )


# ---------------------------------------------------------------------------
# 5. the planner may never relax the final gate
# ---------------------------------------------------------------------------


def test_a_planner_that_relaxes_the_final_gate_refuses_to_construct() -> None:
    """Seeded RED by deleting the ``max`` in ``inflation_radius_m``.

    **Stated honestly (verifier note): the construction guard is UNREACHABLE
    while ``inflation_radius_m`` keeps its ``max``.** It is a seed detector, not
    a live gate — its job is to make the deletion of that ``max`` a red test
    instead of a silent weakening, which seed S3 demonstrates. The assertions
    below are therefore about the INVARIANT holding, not about the refusal
    firing; nothing in the tree can currently make it fire.
    """

    # Green: the shipped footprint term covers the prototype ring's demand.
    GridPlannerConfig(gate_clearance_m=PROTOTYPE_RING_M)
    # Green: the coupled term covers the shipped ring's demand (via the max).
    coupled = GridPlannerConfig(gate_clearance_m=SHIPPED_RING_M)
    assert coupled.inflation_radius_m == pytest.approx(0.593297, abs=5e-7)
    assert coupled.inflation_radius_m >= coupled.gate_lateral_clearance_m

    # The invariant, on 200 rings: inflation never sits inside the gate demand.
    for index in range(200):
        ring = OBSTACLE_STOP_FLOOR_M + index * (1.20 - OBSTACLE_STOP_FLOOR_M) / 199
        config = GridPlannerConfig(gate_clearance_m=ring)
        assert config.inflation_radius_m + 1e-12 >= config.gate_lateral_clearance_m


def test_the_gate_cone_named_in_the_authority_is_still_the_cone_the_gate_uses() -> None:
    """P1-E's pin, re-asserted here because DOOR-1's arithmetic now depends on it."""

    import inspect

    from parcel_robot.navigation import reactive_safety

    signature = inspect.signature(reactive_safety._toward)
    assert signature.parameters["half_angle"].default == GATE_TOWARD_HALF_ANGLE_RAD


# ---------------------------------------------------------------------------
# 6. the corridors, on the product path
# ---------------------------------------------------------------------------

FOOTPRINT_M = 0.32
RANGE_MAX_M = 6.0


def _ray(half_width_m: float, y: float, world_angle: float) -> float:
    sine = math.sin(world_angle)
    if abs(sine) < 1e-9:
        return math.inf
    best = math.inf
    for wall in (half_width_m, -half_width_m):
        travel = (wall - y) / sine
        if travel > 0.0:
            best = min(best, travel)
    return best


def _scan(half_width_m: float, y: float, yaw: float, rays: int):
    angle_min = -math.pi
    increment = 2.0 * math.pi / (rays - 1)
    ranges = []
    for index in range(rays):
        distance = _ray(half_width_m, y, yaw + angle_min + index * increment)
        ranges.append(distance if 0.0 < distance < RANGE_MAX_M else math.inf)
    return tuple(ranges), angle_min, increment


def _corridor_observation(
    width_m: float,
    *,
    policy: ReactiveSafetyPolicy,
    y: float = 0.0,
    yaw: float = 0.0,
    rays: int = 181,
    person_ahead_m: float | None = None,
) -> SimObservation:
    ranges, angle_min, increment = _scan(width_m / 2.0, y, yaw, rays)
    obstacles = tuple(
        LidarObstacle(
            distance_m=distance,
            bearing_rad=angle_min + index * increment,
            obstacle_id=f"wall_{index}",
        )
        for index, distance in enumerate(ranges)
        if math.isfinite(distance)
    )
    return SimObservation(
        timestamp=time.monotonic(),
        robot=RobotPose(x=0.0, y=y, yaw=yaw),
        owner=OwnerTrack(visible=False),
        lidar_obstacles=obstacles,
        nearest_obstacle_m=min((item.distance_m for item in obstacles), default=None),
        nearest_obstacle_bearing_rad=(
            min(obstacles, key=lambda item: item.distance_m).bearing_rad
            if obstacles
            else None
        ),
        nearest_person_m=person_ahead_m,
        nearest_person_bearing_rad=None if person_ahead_m is None else 0.0,
        lidar_ranges=ranges,
        lidar_angle_min_rad=angle_min,
        lidar_angle_increment_rad=increment,
        lidar_range_min_m=0.05,
        lidar_range_max_m=RANGE_MAX_M,
        backend="door1-corridor",
    )


def _gate_stops_at(
    policy: ReactiveSafetyPolicy, *, distance_m: float, speed_mps: float
) -> bool:
    observation = SimObservation(
        timestamp=time.monotonic(),
        robot=RobotPose(),
        owner=OwnerTrack(visible=False),
        lidar_obstacles=(LidarObstacle(distance_m=distance_m, bearing_rad=0.0),),
        nearest_obstacle_m=distance_m,
        nearest_obstacle_bearing_rad=0.0,
        backend="door1-ring-probe",
    )
    gated, _state = apply_reactive_safety(
        VelocityCommand(vx=speed_mps), observation, policy=policy
    )
    return gated.vx <= 1e-12


def _gate_drives_corridor(width_m: float, ring_m: float, *, vx: float = 0.25) -> bool:
    """SINGLE-TICK admission: does the gate veto a 0.25 m/s forward command here?

    Deliberately not called "traverses". This asks one question of the final
    gate on the corridor's centreline; a traverse additionally needs the planner
    to route it and the controller to hold the line, which is what
    ``_drive_corridor`` measures.
    """

    policy = ReactiveSafetyPolicy(obstacle_stop_m=ring_m)
    observation = _corridor_observation(width_m, policy=policy)
    gated, _state = apply_reactive_safety(
        VelocityCommand(vx=vx), observation, policy=policy, now=observation.timestamp
    )
    return gated.vx > 1e-12


def _planner_routes_corridor(width_m: float, ring_m: float | None) -> bool:
    """The PRODUCT planner's own verdict, at the PRODUCT grid resolution (0.10 m)."""

    config = GridPlannerConfig(
        resolution_m=0.10,
        grid_size_cells=161,
        lidar_range_cap_m=12.0,
        gate_clearance_m=ring_m,
    )
    planner = RollingGridPlanner(config)
    ranges, angle_min, increment = _scan(width_m / 2.0, 0.0, 0.0, 721)
    planner.update(
        Pose2D(0.0, 0.0, 0.0),
        LidarScan(
            ranges_m=ranges,
            angle_min_rad=angle_min,
            angle_increment_rad=increment,
            range_min_m=0.05,
            range_max_m=RANGE_MAX_M,
        ),
    )
    return all(
        planner.grid.is_traversable((x, 0.0), inflated=True)
        for x in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
    )


def _drive_corridor(
    width_m: float, *, ring_m: float, ticks: int = 700, dt: float = 0.1
) -> dict[str, float | bool | int]:
    """The product planner proposing and the product final gate disposing.

    The planner is the ``RollingGridPlanner`` inside the product
    ``GridNavigator``, constructed through ``ModelRegistry.create("grid_v1")``
    from ``configs/navigation/models/grid.yaml`` — the same call
    ``DirectiveNavigator`` makes. Every command it proposes is passed through
    ``apply_reactive_safety`` (the final gate the runtime control loop applies)
    before it is integrated, so nothing moves the body that the gate did not
    admit.
    """

    policy = ReactiveSafetyPolicy(obstacle_stop_m=ring_m)
    half = width_m / 2.0
    goal_x = 6.0
    registry = ModelRegistry.load(MODELS_ROOT)
    navigator = registry.create("grid_v1", arrive_radius_m=0.30)
    mission = Mission(
        directive="through the doorway",
        goal=GoalPose(x=goal_x, y=0.0, arrival_radius_m=0.30),
        status="running",
    )

    x = y = yaw = 0.0
    min_clearance = math.inf
    contacts = 0
    routed = False
    now = time.monotonic()
    try:
        for _ in range(ticks):
            now += dt
            nav_ranges, angle_min, increment = _scan(half, y, yaw, 721)
            command = navigator.act(
                NavObservation(
                    position=(x, y, 0.0),
                    heading_deg=math.degrees(yaw),
                    lidar=nav_ranges,
                    extras={
                        "lidar_angle_min_rad": angle_min,
                        "lidar_angle_increment_rad": increment,
                        "lidar_range_min_m": 0.05,
                        "lidar_range_max_m": RANGE_MAX_M,
                    },
                ),
                mission,
            )
            if navigator.last_route_status not in (None, "no_path", "goal_blocked"):
                routed = True
            observation = _corridor_observation(width_m, policy=policy, y=y, yaw=yaw)
            observation = type(observation)(  # restamp on the harness clock
                **{
                    **{
                        field: getattr(observation, field)
                        for field in observation.__dataclass_fields__
                    },
                    "timestamp": now,
                    "robot": RobotPose(x=x, y=y, yaw=yaw),
                }
            )
            proposed = VelocityCommand(
                vx=0.0 if command.stop else command.vx,
                vy=0.0 if command.stop else command.vy,
                vyaw=0.0 if command.stop else command.vyaw,
            )
            gated, _state = apply_reactive_safety(
                proposed, observation, policy=policy, now=now
            )
            x += (gated.vx * math.cos(yaw) - gated.vy * math.sin(yaw)) * dt
            y += (gated.vx * math.sin(yaw) + gated.vy * math.cos(yaw)) * dt
            yaw += gated.vyaw * dt
            min_clearance = min(min_clearance, half - abs(y) - FOOTPRINT_M)
            if min_clearance < 0.0:
                contacts += 1
            if x >= goal_x - 0.30:
                break
    finally:
        navigator.close()

    return {
        "routed": routed,
        "travelled_m": x,
        "min_clearance_m": min_clearance,
        "contacts": contacts,
    }


def test_the_shipped_ring_plans_a_corridor_it_then_refuses_to_drive() -> None:
    """Audit §6's disagreement, measured on the product path.

    The planner routes a 1.20 m corridor (its inflation is 0.42 m) and the final
    gate then refuses every translation in it, because at the shipped 0.65 m
    ring the nearest in-cone wall (0.657 m) is inside the stop ring. The robot
    plans a route and stands still. THAT is what "the planner and the gate
    disagree on the envelope" costs, in metres of travel.
    """

    # 1400 ticks = 140 s, the SAME horizon as the traversal arm below, so the
    # control and treatment arms are comparable (verifier catch: the first
    # version pinned a 20 s horizon against a 140 s headline).
    result = _drive_corridor(1.20, ring_m=SHIPPED_RING_M, ticks=1400)
    assert result["routed"] is True
    assert result["travelled_m"] < 0.05
    assert result["contacts"] == 0


def test_the_commissioned_indoor_ring_drives_the_same_corridor() -> None:
    """The DOOR-1 deliverable: the same corridor, traversed, with zero contact."""

    result = _drive_corridor(1.20, ring_m=PROTOTYPE_RING_M, ticks=700)
    assert result["routed"] is True
    assert result["travelled_m"] >= 5.70
    assert result["contacts"] == 0
    assert result["min_clearance_m"] >= 0.20


def test_a_one_point_one_metre_corridor_is_traversed_at_the_indoor_ring() -> None:
    """The narrower of the two widths the PRODUCT planner will route at all."""

    result = _drive_corridor(1.10, ring_m=PROTOTYPE_RING_M, ticks=1400)
    assert result["routed"] is True
    assert result["travelled_m"] >= 5.70
    assert result["contacts"] == 0
    assert result["min_clearance_m"] >= 0.17


@pytest.mark.parametrize(
    ("width_m", "gate_drives", "planner_routes"),
    [
        # The measured boundaries, and the ONE conclusion that matters: below
        # 1.0000 m it is the PLANNER that refuses, not the safety envelope.
        # ``gate_drives`` is a SINGLE-TICK centreline admission (the gate does
        # not veto a 0.25 m/s forward command on the corridor's centreline), not
        # a traverse — a traverse also needs the planner, which is the point.
        (0.80, False, False),
        (0.90, True, False),   # the gate admits it; the planner will not route it
        (1.00, True, False),   # EXACTLY on the knife edge: 1.0000 does not route
        (1.0001, True, True),  # ...and one tenth of a millimetre wider does
        (1.20, True, True),
    ],
)
def test_the_measured_corridor_boundaries_at_the_indoor_ring(
    width_m: float, gate_drives: bool, planner_routes: bool
) -> None:
    assert _gate_drives_corridor(width_m, PROTOTYPE_RING_M) is gate_drives
    assert _planner_routes_corridor(width_m, PROTOTYPE_RING_M) is planner_routes


def test_the_planner_is_the_stricter_of_the_two_at_the_indoor_ring() -> None:
    """"The planner never proposes what the gate always refuses", as a measurement.

    Both boundaries found by bisection on the real objects. The planner's is
    coarser because the product grid is 0.10 m: the continuous 0.84 m threshold
    quantises up to exactly 1.0000 m. The direction is what the card asks for —
    the planner refuses FIRST, so no proposed corridor is one the gate will
    stand in and refuse.

    The gate boundary is a SINGLE-TICK centreline admission bisected at
    vx 0.25 m/s, which is why it is 0.8628 m and not the static-ring arithmetic
    0.8215 m: the gate's stop test carries a predictive ``+ v*tau`` term, and
    the 2-degree ray grid rounds the in-cone minimum. Both numbers are real;
    they answer different questions.

    Tolerances are tight on purpose (verifier catch: the first version asserted
    ``1.00 < b <= 1.05``, a window wide enough to admit both the true value and
    the wrong one this doc used to publish).
    """

    gate_boundary = _bisect(lambda w: _gate_drives_corridor(w, PROTOTYPE_RING_M))
    planner_boundary = _bisect(
        lambda w: _planner_routes_corridor(w, PROTOTYPE_RING_M), steps=28
    )
    assert gate_boundary == pytest.approx(0.862842, abs=1e-4)
    assert planner_boundary == pytest.approx(1.0000, abs=1e-3)
    assert planner_boundary > gate_boundary
    assert planner_boundary - gate_boundary == pytest.approx(0.137, abs=2e-3)


def _bisect(admits, low: float = 0.30, high: float = 2.00, steps: int = 40) -> float:
    for _ in range(steps):
        middle = (low + high) / 2.0
        if admits(middle):
            high = middle
        else:
            low = middle
    return high


def test_a_person_standing_in_the_doorway_stops_the_dog() -> None:
    """The obstacle ring moved; the PERSON ring did not, and it still binds.

    Card DOOR-1 relaxes clearance to WALLS. A person in the same doorway is
    still held at ``person_stop_m`` (0.7 m under the prototype profile, plus the
    gate's predictive term), which is a wider ring than the 0.45 m wall ring by
    construction — ``PERSON_SOCIAL_ZONE_FLOOR_M`` (0.68) dominates
    ``OBSTACLE_STOP_FLOOR_M`` (0.41).
    """

    policy = ReactiveSafetyPolicy(
        obstacle_stop_m=PROTOTYPE_RING_M, person_stop_m=0.7, person_slow_m=2.5
    )
    assert policy.person_stop_m > policy.obstacle_stop_m

    blocked = _corridor_observation(1.20, policy=policy, person_ahead_m=0.70)
    gated, _state = apply_reactive_safety(
        VelocityCommand(vx=0.25), blocked, policy=policy, now=blocked.timestamp
    )
    assert gated.vx == 0.0

    # ...and with the person out of the ring the same corridor still drives.
    clear = _corridor_observation(1.20, policy=policy, person_ahead_m=2.6)
    moving, _state = apply_reactive_safety(
        VelocityCommand(vx=0.25), clear, policy=policy, now=clear.timestamp
    )
    assert moving.vx > 0.0


# ---------------------------------------------------------------------------
# 7. the follow stand-off obeys config
# ---------------------------------------------------------------------------


def test_the_follow_stand_off_derives_from_the_instance_not_the_import() -> None:
    """P1-E's handoff, closed. No yaml at all: the numbers follow the fields."""

    prototype = FollowConfig(person_stop_m=0.7, person_slow_m=2.5)
    assert prototype.owner_keepout_m == pytest.approx(1.25)
    assert prototype.desired_distance_m == pytest.approx(1.35)
    assert prototype.desired_distance_m == pytest.approx(
        prototype.owner_keepout_m + OWNER_STAND_OFF_MARGIN_M
    )
    # An explicit value still wins: this changed the DEFAULT, not the precedence.
    explicit = FollowConfig(person_stop_m=0.7, person_slow_m=2.5, owner_keepout_m=1.5)
    assert explicit.owner_keepout_m == 1.5
    assert explicit.desired_distance_m == pytest.approx(1.6)


def test_no_module_level_stand_off_constant_survives_in_follow() -> None:
    """The seeded-RED anchor for "silently constant again"."""

    from parcel_robot.navigation import follow

    assert not hasattr(follow, "_FOLLOW_DESIRED_DISTANCE_M")
    assert not hasattr(follow, "_OWNER_KEEPOUT_M")
    fields = FollowConfig.__dataclass_fields__
    assert fields["desired_distance_m"].default is None
    assert fields["owner_keepout_m"].default is None


def test_the_arrival_stand_off_is_still_an_import_time_constant() -> None:
    """A KNOWN GAP, pinned rather than claimed closed (verifier catch).

    DW-4 says "no import-time follow/arrival stand-off constants in
    profile-dependent behaviour". DOOR-1 closed the FOLLOW half.
    ``navigation/arrival_semantics.SOCIAL_STANDOFF_M`` is the ARRIVAL half: it
    is still ``PERSON_SOCIAL_ZONE_M`` frozen at import (1.2 m), so "go next to
    the person" still targets 1.2 m under a profile whose gate is commissioned
    to 0.7 m. ``arrival_semantics.py`` is outside DOOR-1's OWNS — P1-E handed it
    off and so does this card.

    This test asserts the gap EXISTS, so the day someone fixes it the assertion
    reddens and the handoff gets closed on purpose rather than by drift.
    """

    from parcel_robot.authority import PERSON_SOCIAL_ZONE_M
    from parcel_robot.navigation import arrival_semantics

    assert arrival_semantics.SOCIAL_STANDOFF_M == PERSON_SOCIAL_ZONE_M == 1.2


def test_the_stand_off_still_clears_its_own_keepout_at_every_commissioning() -> None:
    """The E2/E5 defect the derivation must not reintroduce.

    A stand-off inside its own keepout makes the controller brake against the
    gate it shares (measured then: FOLLOW_BENCH_V1 9/9 -> 6/9). Swept across the
    whole commissionable person band.
    """

    for index in range(50):
        person_stop = PERSON_SOCIAL_ZONE_FLOOR_M + index * (2.0 - PERSON_SOCIAL_ZONE_FLOOR_M) / 49
        keepout = person_stop + 0.55
        config = FollowConfig(
            person_stop_m=person_stop,
            person_slow_m=person_stop + 1.8,
            # The behind formation has its own floor (outside the keepout);
            # moved with the sweep so this test measures the STAND-OFF
            # derivation and not the shipped 1.9 m behind distance.
            behind_distance_m=keepout + 0.15,
            max_behind_distance_m=keepout + 1.5,
            staging_radius_m=keepout + 0.9,
        )
        assert config.desired_distance_m >= config.owner_keepout_m + OWNER_STAND_OFF_MARGIN_M - 1e-9


# ---------------------------------------------------------------------------
# 8. the prototype band stays non-default and says so
# ---------------------------------------------------------------------------


def test_the_relaxed_bands_are_not_defaults_anywhere() -> None:
    """Nothing un-commissioned sees 0.70 m or 0.45 m."""

    assert DEFAULT_SAFETY_ENVELOPE.person_social_zone_m == 1.2
    assert DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m == 0.6
    policy = ReactiveSafetyPolicy()
    assert policy.person_stop_m == 1.2
    assert policy.obstacle_stop_m == SHIPPED_RING_M
    shipped = (REPO / "configs" / "robot.yaml").read_text(encoding="utf-8")
    assert "person_stop_m: 1.2" in shipped
    assert "obstacle_stop_m: 0.65" in shipped


def test_the_prototype_overlay_says_the_bands_are_uncommissioned_simulator_policy() -> None:
    """One wording check, on the real file.

    A relaxed clearance band with no hardware behind it must not read as a
    commissioning record. The overlay has to say so IN THE FILE, because the
    file is what an operator reads before starting the stack.
    """

    text = PROTOTYPE_YAML.read_text(encoding="utf-8")
    assert "obstacle_stop_m: 0.45" in text
    assert "person_stop_m: 0.7" in text
    # Comment reflow must not break the check, so the file is normalised to a
    # single whitespace-separated stream of words before the phrases are read.
    lowered = " ".join(text.replace("#", " ").lower().split())
    assert "not commissioned" in lowered
    assert "simulator policy" in lowered
    assert "no robot hardware is on hand" in lowered
    # ...and the floor is named where the value is set.
    assert "OBSTACLE_STOP_FLOOR_M" in text
