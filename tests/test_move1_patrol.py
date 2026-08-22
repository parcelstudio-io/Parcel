"""Card MOVE-1 — the bounded exploration patrol.

The behaviour under test is the one E2-D2 measured the absence of: a patrol
must not spend its budget commanding a heading the reactive safety gate will
refuse. ``test_c1_geometry_turns_instead_of_pushing`` is the regression that
names the original failure, using C-1's own recorded geometry.
"""

from __future__ import annotations

import math

import pytest

from parcel_robot.patrol import (
    DEFAULT_MAP_SWEEP_VOCABULARY,
    SAFETY_LEASE_QUERY,
    MapGrowthSample,
    PatrolCommand,
    PatrolLimits,
    PatrolPolicy,
    PatrolRunner,
    PatrolSense,
    forward_clearance_from_scan,
    ingress_queries,
    sense_from_snapshot,
)


def sense(**kwargs) -> PatrolSense:
    base = {
        "elapsed_s": 0.0,
        "x": 0.0,
        "y": 0.0,
        "yaw": 0.0,
        "forward_clearance_m": 5.0,
        "person_clearance_m": 5.0,
    }
    base.update(kwargs)
    return PatrolSense(**base)


# --------------------------------------------------------------------------
# The policy ladder
# --------------------------------------------------------------------------


def test_advances_when_lane_and_people_are_clear():
    command = PatrolPolicy().step(sense())
    assert command.reason == "advance"
    assert command.vx == pytest.approx(0.25)
    assert command.vyaw == 0.0
    assert command.translating


def test_turns_instead_of_pushing_into_a_person():
    """E2-D2's exact failure: person inside the standoff must yield a TURN."""

    command = PatrolPolicy().step(sense(person_clearance_m=1.2))
    assert command.reason == "turn_person"
    assert not command.translating, "a patrol must never command into a person"
    assert abs(command.vyaw) == pytest.approx(0.8)


def test_turns_when_the_lane_ahead_is_short():
    command = PatrolPolicy().step(sense(forward_clearance_m=1.0))
    assert command.reason == "turn_blocked"
    assert not command.translating


def test_person_priority_beats_geometry():
    command = PatrolPolicy().step(
        sense(forward_clearance_m=1.0, person_clearance_m=1.0)
    )
    assert command.reason == "turn_person"


def test_contact_beats_everything_below_budget():
    command = PatrolPolicy().step(sense(collision=True))
    assert command.reason == "turn_contact"
    assert not command.translating


def test_unknown_clearance_is_not_treated_as_clear_for_people():
    """``None`` means unknown. Unknown people must not block; unknown lane
    must not invent an obstacle. Both stay explicit rather than defaulting."""

    command = PatrolPolicy().step(
        sense(forward_clearance_m=None, person_clearance_m=None)
    )
    assert command.reason == "advance"


def test_hysteresis_holds_the_turn_until_the_release_margin():
    limits = PatrolLimits()
    policy = PatrolPolicy(limits)
    assert policy.step(sense(forward_clearance_m=1.0)).reason == "turn_blocked"
    # Just over the threshold but inside the release margin: keep turning.
    held = policy.step(sense(elapsed_s=0.25, forward_clearance_m=1.6))
    assert held.reason == "turn_hold"
    assert not held.translating
    released = policy.step(
        sense(
            elapsed_s=0.5,
            forward_clearance_m=limits.min_forward_clearance_m
            + limits.clearance_release_margin_m,
        )
    )
    assert released.reason == "advance"


def test_turn_direction_flips_when_a_turn_finds_no_lane():
    limits = PatrolLimits(turn_flip_after_s=1.0, turn_giveup_after_s=10.0)
    policy = PatrolPolicy(limits)
    first = policy.step(sense(forward_clearance_m=0.5))
    assert first.vyaw > 0.0
    flipped = policy.step(sense(elapsed_s=1.0, forward_clearance_m=0.5))
    assert flipped.vyaw < 0.0, "a turn that finds nothing must try the other way"


def test_boxed_in_gives_up_rather_than_spinning_out_the_budget():
    limits = PatrolLimits(turn_flip_after_s=2.0, turn_giveup_after_s=2.0)
    policy = PatrolPolicy(limits)
    policy.step(sense(forward_clearance_m=0.3))
    verdict = policy.step(sense(elapsed_s=2.0, forward_clearance_m=0.3))
    assert verdict.reason == "boxed_in"
    assert not verdict.translating and verdict.vyaw == 0.0


def test_budget_exhausted_stops_and_outranks_a_clear_lane():
    policy = PatrolPolicy(PatrolLimits(budget_s=10.0))
    command = policy.step(sense(elapsed_s=10.0))
    assert command.reason == "budget_exhausted"
    assert not command.translating and command.vyaw == 0.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_sense_rejects_non_finite_pose(bad):
    with pytest.raises(ValueError):
        PatrolSense(elapsed_s=0.0, x=bad, y=0.0, yaw=0.0)


def test_limits_reject_a_giveup_shorter_than_the_flip():
    with pytest.raises(ValueError):
        PatrolLimits(turn_flip_after_s=5.0, turn_giveup_after_s=1.0)


# --------------------------------------------------------------------------
# Sensing
# --------------------------------------------------------------------------


def test_forward_clearance_takes_the_shortest_ray_inside_the_cone_only():
    # 360 rays, 1 deg, starting at -pi. Body-forward is index 180.
    ranges = [30.0] * 360
    ranges[180] = 2.0  # dead ahead
    ranges[0] = 0.1  # directly behind — must be ignored
    clearance = forward_clearance_from_scan(
        ranges, angle_min_rad=-math.pi, angle_increment_rad=math.radians(1.0),
        range_max_m=30.0,
    )
    assert clearance == pytest.approx(2.0)


def test_forward_clearance_ignores_nan_rays_and_returns_none_when_all_invalid():
    ranges = [float("nan")] * 360
    assert (
        forward_clearance_from_scan(
            ranges, angle_min_rad=-math.pi, angle_increment_rad=math.radians(1.0)
        )
        is None
    )


def test_forward_clearance_treats_range_max_as_no_return():
    ranges = [30.0] * 360
    assert (
        forward_clearance_from_scan(
            ranges,
            angle_min_rad=-math.pi,
            angle_increment_rad=math.radians(1.0),
            range_max_m=30.0,
        )
        is None
    )


def test_sense_from_snapshot_without_a_pose_is_none_not_the_origin():
    assert sense_from_snapshot({"lidar_scan": {}}, elapsed_s=0.0) is None
    assert sense_from_snapshot({"robot": {"y": 1.0}}, elapsed_s=0.0) is None


def test_c1_geometry_turns_instead_of_pushing():
    """C-1's own recorded snapshot geometry, replayed through the patrol.

    ``on_api_state.json`` records ``owner {x: 2.0, y: -0.5, visible: true}``
    and the robot parked at ``x = 0.1705``. The owner-envelope clearance there
    is below the standoff, so the patrol must turn. C-1's harness commanded
    ``vx = 0.25`` into it 160 times instead, which is E2-D2.
    """

    snapshot = {
        "robot": {"x": 0.17049861836221136, "y": 0.0, "heading": 0.0},
        "owner": {"x": 2.0, "y": -0.5, "visible": True},
        "obstacle_distance_m": 1.3565957148044432,
        "nearest_person": {"distance_m": 5.556399515583327},
    }
    reading = sense_from_snapshot(snapshot, elapsed_s=0.0)
    assert reading is not None
    expected = math.hypot(2.0 - 0.17049861836221136, -0.5) - 0.55
    assert reading.person_clearance_m == pytest.approx(expected)
    assert reading.person_clearance_m < PatrolLimits().min_person_clearance_m

    command = PatrolPolicy().step(reading)
    assert command.reason == "turn_person"
    assert not command.translating


def test_sense_uses_the_nearer_of_owner_and_stranger():
    snapshot = {
        "robot": {"x": 0.0, "y": 0.0, "heading": 0.0},
        "owner": {"x": 10.0, "y": 0.0, "visible": True},
        "nearest_person": {"distance_m": 0.9},
    }
    reading = sense_from_snapshot(snapshot, elapsed_s=0.0)
    assert reading is not None
    assert reading.person_clearance_m == pytest.approx(0.9)


def test_invisible_owner_is_not_a_standoff():
    snapshot = {
        "robot": {"x": 0.0, "y": 0.0, "heading": 0.0},
        "owner": {"x": 1.0, "y": 0.0, "visible": False},
    }
    reading = sense_from_snapshot(snapshot, elapsed_s=0.0)
    assert reading is not None
    assert reading.person_clearance_m is None


# --------------------------------------------------------------------------
# The runner
# --------------------------------------------------------------------------


class FakeClock:
    def __init__(self, step: float = 0.25) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        return self.now

    def sleep(self, _seconds: float) -> None:
        self.now += self.step


def test_runner_records_path_map_growth_and_stops_on_budget():
    clock = FakeClock(step=0.5)
    poses = []

    def provider(elapsed: float) -> PatrolSense:
        # Straight line at 0.5 m per tick, always clear.
        reading = sense(elapsed_s=elapsed, x=elapsed, y=0.0)
        poses.append(reading)
        return reading

    entries = {"n": 0}

    def probe() -> MapGrowthSample:
        entries["n"] += 1
        return MapGrowthSample(
            t_s=0.0, entries=entries["n"], labels=("bench",), frames_seen=entries["n"],
            detections_seen=entries["n"] * 2,
        )

    runner = PatrolRunner(
        scene="city_block",
        sense_provider=provider,
        submit=lambda command: True,
        map_probe=probe,
        limits=PatrolLimits(budget_s=3.0),
        clock=clock,
        sleep=clock.sleep,
    )
    report = runner.run()

    assert report.stopped_reason == "budget_exhausted"
    assert report.elapsed_s >= 3.0
    assert report.path, "a patrol with a budget must leave a path trace"
    assert report.path_length_m == pytest.approx(report.path[-1].x - report.path[0].x)
    assert report.map_growth[-1].entries == len(report.map_growth)
    assert report.map_growth[-1].t_s == report.path[-1].t_s
    assert report.reasons["advance"] == len(report.path)
    assert report.refused == 0
    assert report.as_dict()["map_entries_final"] == report.map_growth[-1].entries


def test_runner_counts_refused_submissions_without_ending_the_mission():
    clock = FakeClock(step=0.5)
    runner = PatrolRunner(
        scene="city_block",
        sense_provider=lambda elapsed: sense(elapsed_s=elapsed),
        submit=lambda command: False,
        limits=PatrolLimits(budget_s=2.0),
        clock=clock,
        sleep=clock.sleep,
    )
    report = runner.run()
    assert report.submitted > 0
    assert report.refused == report.submitted
    assert report.stopped_reason == "budget_exhausted"


def test_runner_skips_ticks_without_a_pose_and_never_drives_blind():
    clock = FakeClock(step=0.5)
    submitted: list[PatrolCommand] = []
    runner = PatrolRunner(
        scene="city_block",
        sense_provider=lambda elapsed: None,
        submit=lambda command: submitted.append(command) or True,
        limits=PatrolLimits(budget_s=2.0),
        clock=clock,
        sleep=clock.sleep,
    )
    report = runner.run()
    assert submitted == [], "no pose must mean no command"
    assert report.reasons["no_sense"] > 0
    assert report.path == []


def test_runner_ends_early_when_boxed_in():
    clock = FakeClock(step=0.5)
    runner = PatrolRunner(
        scene="city_block",
        sense_provider=lambda elapsed: sense(elapsed_s=elapsed, forward_clearance_m=0.2),
        submit=lambda command: True,
        limits=PatrolLimits(budget_s=100.0, turn_flip_after_s=1.0, turn_giveup_after_s=1.0),
        clock=clock,
        sleep=clock.sleep,
    )
    report = runner.run()
    assert report.stopped_reason == "boxed_in"
    assert report.elapsed_s < 100.0


# --------------------------------------------------------------------------
# E2-D3 — the T1 query vocabulary
# --------------------------------------------------------------------------


def test_sweep_vocabulary_carries_no_volatile_class():
    """T1 has no sidecar; the batch must still never spend budget on people."""

    from parcel_robot.online_map import is_volatile_label

    assert DEFAULT_MAP_SWEEP_VOCABULARY
    volatile = [
        label for label in DEFAULT_MAP_SWEEP_VOCABULARY if is_volatile_label(label)
    ]
    assert volatile == []


def test_sweep_vocabulary_is_not_read_from_scene_truth():
    """The vocabulary is a static, auditable constant, not scene-derived.

    Checked over the AST rather than the raw text, so prose that *names* the
    sidecar it refuses to read cannot fail the test while a real read would.
    """

    import ast
    import inspect

    from parcel_robot.patrol import mission

    tree = ast.parse(inspect.getsource(mission))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    docstring_owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    docstrings = {
        ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, docstring_owners)
    }
    code_literals = [text for text in literals if text not in docstrings]
    for forbidden in ("scene_truth", "scenes/", "demo_pois", "semantic_map"):
        assert not any(forbidden in text for text in code_literals), forbidden

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not any("scene" in name or "semantic_map" in name for name in imported)


def test_ingress_batch_always_takes_the_person_safety_lease():
    """The camera channel REFUSES a batch without ``person`` (PG-1 lease).

    Measured, not assumed: ``CameraStreamConfig.from_section`` raises on a
    batch that omits it, which is how this constraint was found.
    """

    batch = ingress_queries()
    assert batch[0] == SAFETY_LEASE_QUERY
    assert SAFETY_LEASE_QUERY in batch


def test_ingress_batch_is_the_query_set_not_the_map_set():
    """Asking about people is safety; keeping them as places is not allowed."""

    from parcel_robot.online_map import is_volatile_label

    batch = ingress_queries()
    assert is_volatile_label(SAFETY_LEASE_QUERY), "the lease query IS volatile"
    assert SAFETY_LEASE_QUERY not in DEFAULT_MAP_SWEEP_VOCABULARY
    assert set(batch) - {SAFETY_LEASE_QUERY} <= set(DEFAULT_MAP_SWEEP_VOCABULARY)


def test_ingress_batch_respects_its_limit_and_rejects_a_useless_one():
    assert len(ingress_queries(4)) == 4
    assert len(ingress_queries(1)) == 1
    with pytest.raises(ValueError):
        ingress_queries(0)


def test_ingress_batch_is_accepted_by_the_real_camera_stream_config():
    """The product's own validator, not a restatement of it."""

    from parcel_robot.runtime import CameraStreamConfig

    config = CameraStreamConfig.from_section(
        {
            "camera_ingress": True,
            "camera_ingress_queries": list(ingress_queries()),
        }
    )
    assert SAFETY_LEASE_QUERY in tuple(config.queries)


def test_person_behind_does_not_block_the_lane_ahead():
    """The deadlock the first live patrol measured: distance alone is wrong.

    A stationary person 1.0 m astern never gets further away while the robot
    turns in place, so a distance-only standoff can never release.
    """

    command = PatrolPolicy().step(
        sense(person_clearance_m=1.0, person_bearing_rad=math.pi)
    )
    assert command.reason == "advance"


def test_person_ahead_still_blocks():
    command = PatrolPolicy().step(
        sense(person_clearance_m=1.0, person_bearing_rad=0.0)
    )
    assert command.reason == "turn_person"


def test_unknown_person_bearing_fails_closed():
    command = PatrolPolicy().step(
        sense(person_clearance_m=1.0, person_bearing_rad=None)
    )
    assert command.reason == "turn_person"


def test_turn_goes_away_from_the_person_not_whichever_way_the_counter_points():
    port = PatrolPolicy().step(sense(person_clearance_m=1.0, person_bearing_rad=0.4))
    starboard = PatrolPolicy().step(sense(person_clearance_m=1.0, person_bearing_rad=-0.4))
    assert port.vyaw < 0.0, "a person to port is cleared by turning to starboard"
    assert starboard.vyaw > 0.0


def test_turn_hold_releases_once_the_heading_is_off_the_person():
    """Regression for the 303 `turn_hold` ticks of the first live patrol."""

    policy = PatrolPolicy()
    assert policy.step(
        sense(person_clearance_m=1.0, person_bearing_rad=0.0)
    ).reason == "turn_person"
    # Same distance — the robot only rotated. It must now be free to advance.
    released = policy.step(
        sense(elapsed_s=0.5, person_clearance_m=1.0, person_bearing_rad=math.pi / 2)
    )
    assert released.reason == "advance"


def test_sense_from_snapshot_reports_owner_bearing_in_the_body_frame():
    snapshot = {
        "robot": {"x": 0.0, "y": 0.0, "heading": 180.0},
        "owner": {"x": 2.0, "y": 0.0, "visible": True},
    }
    reading = sense_from_snapshot(snapshot, elapsed_s=0.0)
    assert reading is not None
    # Owner is dead astern once the robot faces -x.
    wrapped = math.atan2(
        math.sin(reading.person_bearing_rad), math.cos(reading.person_bearing_rad)
    )
    assert abs(abs(wrapped) - math.pi) < 1e-9
    assert PatrolPolicy().step(reading).reason == "advance"


def test_snapshot_heading_is_read_as_degrees_not_radians():
    """``RobotRuntime.snapshot`` publishes degrees; reading radians corrupts
    every bearing. Pinned against the runtime's own conversion rather than a
    restatement of it."""

    import inspect

    from parcel_robot import runtime as runtime_module

    source = inspect.getsource(runtime_module.RobotRuntime.snapshot)
    assert '"heading": math.degrees(' in source, (
        "snapshot no longer publishes degrees; sense_from_snapshot must follow"
    )

    reading = sense_from_snapshot(
        {"robot": {"x": 0.0, "y": 0.0, "heading": 90.0}}, elapsed_s=0.0
    )
    assert reading is not None
    assert reading.yaw == pytest.approx(math.pi / 2)
