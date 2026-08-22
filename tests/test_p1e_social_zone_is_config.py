"""Card P1-E — the person social zone is a config, with a named hard floor.

What this file pins, and what it deliberately does not.

The card moves the **SOURCE** of one distance and nothing else.
``SafetyEnvelope.person_social_zone_m`` used to be a hardcoded 1.2 m that
``ReactiveSafetyPolicy.__post_init__`` floored every configured
``safety.person_stop_m`` against — so the shipped commissioning value was its
own floor, an indoor 0.7 m profile was impossible, and writing it into an
overlay did not relax the robot, it stopped the robot from BOOTING (P0-A's
blocker; ``scrum/20260822/WAVE_P0_VERIFICATION_FABLE.md`` row A-1). Now config
commissions the zone and the floor underneath is
:data:`~parcel_robot.authority.PERSON_SOCIAL_ZONE_FLOOR_M`.

The gate's LOGIC is untouched, and that is checked elsewhere by a stronger
instrument than anything here: ``tests/test_dynamic_layer.py``'s AST ratchet,
which holds ``apply_reactive_safety`` at ``f52db9c5…`` across this card.

Three properties are seeded RED in ``scrum/20260822/task_12/P1E_STATUS.md``:
the floor removed, the planner inflation decoupled from the envelope, and a
below-floor overlay booting.
"""

from __future__ import annotations

import inspect
import math
import time
from pathlib import Path

import pytest
import yaml

from parcel_robot.authority import (
    DEFAULT_SAFETY_ENVELOPE,
    DEFAULT_SPEED_REGIME,
    GATE_TOWARD_HALF_ANGLE_RAD,
    PERSON_SOCIAL_ZONE_FLOOR_M,
    PERSON_SOCIAL_ZONE_M,
    SafetyEnvelope,
    gate_lateral_clearance_m,
)
from parcel_robot.navigation import reactive_safety as reactive_safety_module
from parcel_robot.navigation.grid_planner import (
    GridPlannerConfig,
    LidarScan,
    Pose2D,
    RollingGridPlanner,
)
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy

REPO = Path(__file__).resolve().parents[1]
ROBOT_YAML = REPO / "configs" / "robot.yaml"
PROTOTYPE_YAML = REPO / "configs" / "robot.prototype.yaml"


# ---------------------------------------------------------------------------
# 1. the floor: what it is, why that number, and that it refuses
# ---------------------------------------------------------------------------


def test_the_floor_is_the_bodys_stopping_distance_at_cruise() -> None:
    """The literal and its derivation must not part company.

    ``PERSON_SOCIAL_ZONE_FLOOR_M`` is written as a literal on purpose — a floor
    that moves when someone retunes ``linear_decel`` is not a floor — so this
    test is the thing that notices if the body it was derived from changes.
    """

    cruise = DEFAULT_SPEED_REGIME.cruise.vx_mps
    derived = DEFAULT_SAFETY_ENVELOPE.stop_distance(cruise)

    assert cruise == 0.85
    assert derived == pytest.approx(0.680036, abs=1e-6)
    assert PERSON_SOCIAL_ZONE_FLOOR_M == 0.68
    # The literal is the derivation, rounded to the centimetre it is quoted at.
    assert PERSON_SOCIAL_ZONE_FLOOR_M == pytest.approx(derived, abs=5e-4)


def test_the_floor_dominates_both_obstacle_floors() -> None:
    """A person may never be commissioned less clearance than a wall."""

    assert PERSON_SOCIAL_ZONE_FLOOR_M > DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m
    assert PERSON_SOCIAL_ZONE_FLOOR_M > reactive_safety_module._REACTIVE_OBSTACLE_STOP_FLOOR_M
    assert ReactiveSafetyPolicy().obstacle_stop_m < PERSON_SOCIAL_ZONE_FLOOR_M


def test_the_floor_plus_the_gates_predictive_term_still_covers_the_iso_sum() -> None:
    """At ``motion.max_vx`` the gate's own ring must not sit inside the physics.

    The reactive gate's person branch stops at ``person_stop_m + v * tau``. At
    the floor and at the fastest speed ``configs/robot.yaml`` permits, that ring
    must still be at least the ISO/TS-15066 stopping distance, or the floor
    would be a number the body cannot honour.
    """

    max_vx = yaml.safe_load(ROBOT_YAML.read_text(encoding="utf-8"))["motion"]["max_vx"]
    policy = ReactiveSafetyPolicy(person_stop_m=PERSON_SOCIAL_ZONE_FLOOR_M)

    predictive_ring = policy.person_stop_m + max_vx * policy.reaction_time_s
    iso_sum = DEFAULT_SAFETY_ENVELOPE.stop_distance(max_vx)

    assert max_vx == 1.0
    assert predictive_ring == pytest.approx(0.80)
    assert iso_sum == pytest.approx(0.797142, abs=1e-6)
    assert predictive_ring >= iso_sum


@pytest.mark.parametrize("value", [0.0, 0.3, 0.6, 0.679])
def test_below_the_floor_the_envelope_refuses_and_names_the_floor(value: float) -> None:
    """Refusal, not a clamp, and the operator is told the number to clear."""

    with pytest.raises(ValueError, match="PERSON_SOCIAL_ZONE_FLOOR_M"):
        SafetyEnvelope(person_social_zone_m=value)
    with pytest.raises(ValueError, match="0.68"):
        DEFAULT_SAFETY_ENVELOPE.with_person_social_zone(value)


def test_every_construction_path_lands_on_the_floor() -> None:
    """``from_mapping`` / ``from_profile`` / ``replace`` cannot route around it."""

    import dataclasses

    from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE

    with pytest.raises(ValueError, match="PERSON_SOCIAL_ZONE_FLOOR_M"):
        SafetyEnvelope.from_mapping({"person_social_zone_m": 0.5})
    with pytest.raises(ValueError, match="PERSON_SOCIAL_ZONE_FLOOR_M"):
        SafetyEnvelope.from_profile(DEFAULT_ROBOT_PROFILE, person_social_zone_m=0.5)
    with pytest.raises(ValueError, match="PERSON_SOCIAL_ZONE_FLOOR_M"):
        dataclasses.replace(DEFAULT_SAFETY_ENVELOPE, person_social_zone_m=0.5)


def test_the_floor_is_a_floor_and_not_an_equality() -> None:
    """At and above the floor the envelope is built and the zone is honoured."""

    for value in (PERSON_SOCIAL_ZONE_FLOOR_M, 0.7, 1.2, 2.0):
        envelope = DEFAULT_SAFETY_ENVELOPE.with_person_social_zone(value)
        assert envelope.person_social_zone_m == value
        assert envelope.person_stop(0.0) == pytest.approx(value)
        assert envelope.social_zone_is_binding is True


# ---------------------------------------------------------------------------
# 2. the shipped configuration did not move
# ---------------------------------------------------------------------------


def test_the_shipped_authority_is_unchanged() -> None:
    """No profile, no change — this card moved a SOURCE, not a value."""

    assert DEFAULT_SAFETY_ENVELOPE.person_social_zone_m == 1.2
    assert PERSON_SOCIAL_ZONE_M == 1.2
    assert DEFAULT_SAFETY_ENVELOPE.person_stop(0.0) == 1.2
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


def test_the_shipped_gate_defaults_are_unchanged() -> None:
    policy = ReactiveSafetyPolicy()

    assert policy.obstacle_stop_m == 0.65
    assert policy.obstacle_slow_m == 1.2
    assert policy.person_stop_m == 1.2
    assert policy.person_slow_m == 2.5
    assert policy.owner_slow_m == pytest.approx(1.30)
    assert policy.reaction_time_s == 0.12
    assert policy.envelope is DEFAULT_SAFETY_ENVELOPE


def test_the_shipped_robot_yaml_still_carries_the_production_clearance() -> None:
    shipped = yaml.safe_load(ROBOT_YAML.read_text(encoding="utf-8"))

    assert shipped["safety"]["person_stop_m"] == 1.2
    assert shipped["safety"]["person_slow_m"] == 2.5
    assert shipped["owner_follow"]["owner_keepout_m"] == 1.75


# ---------------------------------------------------------------------------
# 3. config commissions the zone
# ---------------------------------------------------------------------------


def test_the_gate_takes_its_person_clearance_from_config() -> None:
    """0.7 m indoors: the number the card exists to make possible."""

    policy = ReactiveSafetyPolicy(person_stop_m=0.7)

    assert policy.person_stop_m == 0.7
    assert policy.commissioned_envelope.person_social_zone_m == 0.7
    assert policy.commissioned_envelope.person_stop(0.0) == pytest.approx(0.7)
    # The owner comfort band is DERIVED from it and follows, unchanged in form.
    assert policy.owner_slow_m == pytest.approx(0.80)
    # ...and the authority object itself is untouched.
    assert DEFAULT_SAFETY_ENVELOPE.person_social_zone_m == 1.2


def test_the_gate_refuses_below_the_floor_naming_both_the_key_and_the_floor() -> None:
    with pytest.raises(ValueError) as excinfo:
        ReactiveSafetyPolicy(person_stop_m=0.6)

    message = str(excinfo.value)
    assert "person_stop_m must not undercut" in message
    assert "PERSON_SOCIAL_ZONE_FLOOR_M" in message
    assert "0.68" in message


def test_a_stricter_commissioning_is_still_allowed() -> None:
    """The floor is one-sided: tighter than shipped is always legal."""

    assert ReactiveSafetyPolicy(person_stop_m=1.4).person_stop_m == 1.4


def test_the_prototype_overlay_lands_the_indoor_stand_off() -> None:
    """The real file on disk, and the runtime numbers it implies."""

    overlay = yaml.safe_load(PROTOTYPE_YAML.read_text(encoding="utf-8"))

    assert overlay["safety"]["person_stop_m"] == 0.7
    # The paired follow keepout: a LITERAL in the base, so it cannot re-derive.
    assert overlay["owner_follow"]["owner_keepout_m"] == 1.25
    assert overlay["owner_follow"]["owner_keepout_m"] == pytest.approx(
        overlay["safety"]["person_stop_m"] + 0.55
    )
    assert overlay["safety"]["person_stop_m"] > PERSON_SOCIAL_ZONE_FLOOR_M


# ---------------------------------------------------------------------------
# 3b. the whole runtime: boots at 0.7, refuses below the floor
# ---------------------------------------------------------------------------


class _Backend:
    name = "sim"

    def observe(self):
        from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation

        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            nearest_obstacle_bearing_rad=0.0,
            backend="sim",
        )

    def move(self, command) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose) -> None:
        del pose

    def trajectory(self, skill) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


def _runtime(tmp_path: Path, *, safety_block: str):
    """A real ``RobotRuntime`` on a minimal config plus one safety block."""

    from parcel_robot.audio_io import AudioDeviceStatus
    from parcel_robot.runtime import RobotRuntime

    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "p1e.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
poses: {{}}
modules: []
{safety_block}""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="test",
        ),
    )


def test_a_runtime_boots_at_the_indoor_stand_off(tmp_path: Path) -> None:
    """The P0-A blocker, gone: 0.7 m from a config file now BOOTS."""

    runtime = _runtime(
        tmp_path / "indoor",
        safety_block=(
            "safety:\n"
            "  person_stop_m: 0.7\n"
            "  person_slow_m: 2.5\n"
            "owner_follow:\n"
            "  owner_keepout_m: 1.25\n"
        ),
    )
    try:
        assert runtime.person_stop_m == 0.7
        assert runtime.reactive_safety_policy.person_stop_m == 0.7
        assert runtime.reactive_safety_policy.owner_slow_m == pytest.approx(0.80)
        assert runtime.follow.config.owner_keepout_m == 1.25
    finally:
        runtime.close()


def test_a_below_floor_config_refuses_to_boot_and_names_the_floor(tmp_path: Path) -> None:
    """The refusal is the safety core, and it stays. No runtime is produced."""

    with pytest.raises(ValueError) as excinfo:
        _runtime(
            tmp_path / "below",
            safety_block="safety:\n  person_stop_m: 0.6\n  person_slow_m: 2.5\n",
        )

    message = str(excinfo.value)
    assert "person_stop_m must not undercut" in message
    assert "PERSON_SOCIAL_ZONE_FLOOR_M" in message
    assert "0.68" in message


# ---------------------------------------------------------------------------
# 4. one number, two consumers — the planner inflation
# ---------------------------------------------------------------------------


def test_the_gate_cone_named_in_the_authority_is_the_cone_the_gate_uses() -> None:
    """The planner derives from the gate's cone without importing the gate.

    Read off the gate function's OWN signature, so the two cannot drift: if
    someone retunes ``_toward``'s half-angle, this reddens and the planner
    derivation is re-derived rather than silently stale.
    """

    signature = inspect.signature(reactive_safety_module._toward)
    assert signature.parameters["half_angle"].default == GATE_TOWARD_HALF_ANGLE_RAD


def test_the_lateral_clearance_is_the_gates_own_geometry() -> None:
    """``h / sin(half_angle) <= ring`` is the gate's refusal, solved for ``h``."""

    ring = 0.65
    lateral = gate_lateral_clearance_m(ring)

    assert lateral == pytest.approx(0.593297, abs=1e-6)
    # A wall at exactly this lateral offset sits exactly on the stop ring when
    # it first enters the cone; a hair further out and it never does.
    assert lateral / math.sin(GATE_TOWARD_HALF_ANGLE_RAD) == pytest.approx(ring)


def test_the_planner_inflation_derives_from_the_same_envelope_quantity() -> None:
    """One number, two consumers — and the legacy default is untouched."""

    policy = ReactiveSafetyPolicy()

    assert GridPlannerConfig().gate_clearance_m is None
    assert GridPlannerConfig().inflation_radius_m == pytest.approx(0.42)

    coupled = GridPlannerConfig(gate_clearance_m=policy.obstacle_stop_m)
    assert coupled.inflation_radius_m == pytest.approx(policy.planner_inflation_m)
    assert coupled.inflation_radius_m == pytest.approx(gate_lateral_clearance_m(0.65))
    assert coupled.inflation_radius_m > GridPlannerConfig().inflation_radius_m

    # A map whose cells are PEOPLE takes the other ring, same derivation.
    person = GridPlannerConfig(gate_clearance_m=0.7)
    assert person.inflation_radius_m == pytest.approx(gate_lateral_clearance_m(0.7))


def test_the_planner_radius_reads_the_authoritys_footprint() -> None:
    assert GridPlannerConfig().robot_radius_m == DEFAULT_SAFETY_ENVELOPE.footprint_radius_m


def test_gate_clearance_must_be_finite_and_non_negative() -> None:
    for bad in (-0.1, math.inf, math.nan):
        with pytest.raises(ValueError, match="gate_clearance_m"):
            GridPlannerConfig(gate_clearance_m=bad)


def _corridor_scan(half_width_m: float, *, maximum: float = 5.0, rays: int = 1441) -> LidarScan:
    """A 360-degree scan of two walls parallel to +x at ``+/- half_width_m``."""

    angle_min = -math.pi
    increment = 2.0 * math.pi / (rays - 1)
    ranges = []
    for index in range(rays):
        angle = angle_min + index * increment
        sine = math.sin(angle)
        if abs(sine) < 1e-9:
            ranges.append(math.inf)
            continue
        distance = half_width_m / abs(sine)
        ranges.append(distance if 0.0 < distance < maximum else math.inf)
    return LidarScan(
        ranges_m=tuple(ranges),
        angle_min_rad=angle_min,
        angle_increment_rad=increment,
        range_max_m=maximum,
    )


def _admits_corridor(width_m: float, *, gate_clearance_m: float | None) -> bool:
    config = GridPlannerConfig(
        resolution_m=0.05,
        grid_size_cells=161,
        lidar_range_cap_m=5.0,
        gate_clearance_m=gate_clearance_m,
    )
    planner = RollingGridPlanner(config)
    planner.update(Pose2D(0.0, 0.0, 0.0), _corridor_scan(width_m / 2.0))
    return all(
        planner.grid.is_traversable((x, 0.0), inflated=True) for x in (0.5, 1.0, 1.5, 2.0)
    )


@pytest.mark.parametrize(
    ("width_m", "legacy", "coupled"),
    [
        # The disagreement band, measured on the REAL planner. Widths are
        # quantised by the 0.05 m grid, so the continuous thresholds (0.84 m
        # legacy, 1.187 m coupled) land at 0.90 m and 1.20 m here.
        (0.80, False, False),  # narrower than both: nobody plans it
        (1.00, True, False),  # THE FLIP: legacy planned it, the gate refuses it
        (1.10, True, False),
        (1.40, True, True),  # wider than both: unchanged
    ],
)
def test_the_planner_stops_choosing_corridors_the_gate_refuses(
    width_m: float, legacy: bool, coupled: bool
) -> None:
    assert _admits_corridor(width_m, gate_clearance_m=None) is legacy
    assert _admits_corridor(width_m, gate_clearance_m=0.65) is coupled


def test_the_dev_scenes_own_corridors_are_unaffected() -> None:
    """Measured, and a NULL result worth pinning.

    The three narrowest un-occluded lidar-visible corridors in
    ``scenes/city_block.xml`` (``bldg_4``/``tree_2`` 0.70 m, ``bldg_1``/``tree_1``
    0.75 m, ``bldg_1``/``bench_back`` 0.77 m) are all narrower than the LEGACY
    planner's own threshold, so coupling the planner to the gate changes no
    verdict in the dev scene: the two configurations already agree there. The
    disagreement is real (the test above), it is just not exercised by this
    scene's static geometry.
    """

    for width_m in (0.70, 0.75, 0.77):
        assert _admits_corridor(width_m, gate_clearance_m=None) is False
        assert _admits_corridor(width_m, gate_clearance_m=0.65) is False


def test_the_physics_floor_still_binds_for_a_wider_body() -> None:
    """The second ``__post_init__`` check is not vestigial — it is scale-dependent.

    At Go2 scale ``stop_distance(0.0)`` is the 0.32 m footprint and the 0.68 m
    proxemics floor dominates it, so that branch is unreachable. Inject a body
    whose hull is wider than the commissioned person clearance and it is the
    binding one: a robot may not commission a stop ring inside itself. This
    test exists so the branch cannot be deleted as dead code.
    """

    wide = SafetyEnvelope(footprint_radius_m=1.5)

    assert wide.stop_distance(0.0) == pytest.approx(1.5)
    assert wide.person_stop(0.0) == pytest.approx(1.5)  # hull beats the zone
    with pytest.raises(ValueError, match=r"must not undercut\s+SafetyEnvelope\.person_stop"):
        ReactiveSafetyPolicy(person_stop_m=0.7, person_slow_m=2.5, envelope=wide)
    # ...and the two floors are independent: the proxemics floor still refuses
    # an under-floor value on the same wide body, with its own message.
    with pytest.raises(ValueError, match="PERSON_SOCIAL_ZONE_FLOOR_M"):
        ReactiveSafetyPolicy(person_stop_m=0.6, person_slow_m=2.5, envelope=wide)
