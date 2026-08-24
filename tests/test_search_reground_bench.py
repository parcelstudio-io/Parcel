"""Search-reground regression: a frustum-visible bench must become a grounded
arrival, not get banished as unreachable.

Root cause (2026-08-09, tick-level probe): a bench 3.9 m from spawn but behind
the robot enters the 70 deg / 12 m frustum during the recovery scan, grounds
RESOLVED, and is confirmed — but the ``near`` approach solver plans stand poses
on the object's SUPPORT SURFACE (the 2 m sidewalk it sits on, flanked by a
lamppost and a tree), finds none admissible from any pose, and returns ``None``.
``_commit_semantic_candidate`` then released the instance to
``_release_unreachable_candidate``, which added it to the per-mission excluding
map, so the dog spun out its whole scan+frontier budget never seeing the bench
again → "couldn't find a bench". A second defect: the multi-view confirmation
rotated at a fixed +yaw_rate that pushed a trailing-edge target back out of the
frustum before the second sighting, so it never reached ``required_observations``.

Fix (Sol lane): :func:`~parcel_robot.instructnav.near_arrival.near_band_fallback_point`
supplies a collision-clear pose inside the SAME K0 vicinity band the mission
verifies against when the support-gated solver finds none; the confirmation
rotation steers toward the grounded target to keep it in view. Honest not-found
is preserved: a genuinely absent target never enters the frustum, so it never
commits.

These live probes drive the real headless sim + DirectiveNavigator + K0 scorer
end to end. This file is owned by the search-reground card (NOT
tests/test_voice_nav_e2e.py).
"""

from __future__ import annotations

import math

import pytest

from evals.nav_instruct.generator import generate_episode_matrix
from evals.nav_instruct.runner import NavInstructRunner
from parcel_robot.instructnav.near_arrival import (
    DEFAULT_BEARING_SAMPLES,
    near_band_fallback_point,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.goals import navigation_directive_from_text
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.simulation.headless_city import (
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
    _nav_observation,
)

# A budget wide enough that the ~7 s opening full-turn scan + the slow terminal
# approach (both the seamless-pacing card's problem, not this one) do not
# truncate a grounded arrival. The frozen minival's 200-step budget leaves the
# bench inside the goal but cut off by the step limit; grounding + reaching the
# goal band is the search-reground invariant and holds well below this.
_ARRIVAL_BUDGET_STEPS = 450


def _episode(episode_id: str):
    return {e.episode_id: e for e in generate_episode_matrix(version="v3")}[episode_id]


def _drive(episode, *, max_steps: int):
    """Run one episode through the real navigator; return (navigator, world, trace).

    Mirrors the NAV_INSTRUCT runner's control loop (zero-velocity on stop, so a
    terminal stop can actually settle) without importing its scoring, so the
    tests can inspect commitment/exclusion directly.
    """

    world = HeadlessCityWorld()
    harness = HeadlessCityQualityHarness(world)
    world.reset(robot=episode.start_pose, owner=None, restore_semantics=True)
    world.apply_placement_overrides(dict(episode.placement_overrides or {}))
    directive = navigation_directive_from_text(episode.instruction)
    assert directive is not None
    nav = DirectiveNavigator.from_config(
        harness.navigation_config, instructnav_recovery=True
    )
    mission = nav.start(directive)
    committed = False
    trace: list[tuple[float, float, str]] = []
    for _ in range(max_steps):
        obs = world.observe()
        nobs = _nav_observation(
            obs,
            measured_velocity=world.command,
            stop_confirmed=world.stopped,
            settled_linear_speed_mps=harness._settled_linear_speed_mps,
            settled_yaw_speed_rad_s=harness._settled_yaw_speed_rad_s,
        )
        goal_before = mission.goal
        cmd = nav.step(nobs)
        if goal_before is None and mission.goal is not None:
            committed = True
        velocity = (
            VelocityCommand()
            if cmd.stop
            else VelocityCommand(cmd.vx, cmd.vy, cmd.vyaw)
        )
        world.apply(velocity)
        trace.append((obs.robot.x, obs.robot.y, cmd.note or ""))
        if (cmd.stop and mission.status != "verifying") or nav.done():
            break
        world.step()
    obs = world.observe()
    trace.append((obs.robot.x, obs.robot.y, mission.status))
    nav.close()
    return nav, mission, committed, trace


# --------------------------------------------------------------------------- #
# Pure module contract (Sol lane, frozen).                                    #
# --------------------------------------------------------------------------- #


def test_fallback_point_lands_inside_the_band_and_clear():
    # Bench near band [1.854, 2.054] m around (-2.5, 3.045); no obstacles.
    point = near_band_fallback_point(
        center=(-2.5, 3.045),
        band_m=(1.854, 2.054),
        robot_xy=(-0.05, 0.03),
        blocked_points=(),
        clearance_m=0.92,
    )
    assert point is not None
    d = math.hypot(point[0] + 2.5, point[1] - 3.045)
    assert 1.854 - 1e-6 <= d <= 2.054 + 1e-6


def test_fallback_prefers_the_robots_own_side():
    # With no obstacles, index 0 is the bearing straight from object to robot.
    center = (0.0, 0.0)
    robot = (5.0, 0.0)
    point = near_band_fallback_point(
        center=center, band_m=(1.8, 2.0), robot_xy=robot, clearance_m=0.0
    )
    assert point is not None
    # Straight toward the robot (+x): mid-band radius on the robot's side.
    assert point[0] == pytest.approx(1.9, abs=1e-6)
    assert point[1] == pytest.approx(0.0, abs=1e-6)


def test_fallback_returns_none_when_every_bearing_is_boxed_in():
    # A ring of obstacle surfaces at the band radius blocks every sample.
    center = (0.0, 0.0)
    ring = tuple(
        (f"o{k}", 1.9 * math.cos(t), 1.9 * math.sin(t))
        for k, t in enumerate(
            2.0 * math.pi * i / 64 for i in range(64)
        )
    )
    point = near_band_fallback_point(
        center=center,
        band_m=(1.8, 2.0),
        robot_xy=(5.0, 0.0),
        blocked_points=ring,
        clearance_m=0.5,
    )
    assert point is None


def test_fallback_skips_a_blocked_side_for_a_clear_one():
    # Obstacle straight toward the robot forces the pick to another bearing,
    # still on the band, still clear.
    center = (0.0, 0.0)
    point = near_band_fallback_point(
        center=center,
        band_m=(1.8, 2.0),
        robot_xy=(5.0, 0.0),
        blocked_points=(("wall", 1.9, 0.0),),
        clearance_m=0.6,
    )
    assert point is not None
    d = math.hypot(point[0], point[1])
    assert 1.8 - 1e-6 <= d <= 2.0 + 1e-6
    assert math.hypot(point[0] - 1.9, point[1]) >= 0.6


@pytest.mark.parametrize(
    "kwargs",
    [
        {"band_m": (2.0, 1.8)},  # inner > outer
        {"band_m": (0.0, 2.0)},  # inner not > 0
        {"bearings": 4},  # below the floor
    ],
)
def test_fallback_validates_its_contract(kwargs):
    base = {
        "center": (0.0, 0.0),
        "band_m": (1.8, 2.0),
        "robot_xy": (5.0, 0.0),
        "clearance_m": 0.0,
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        near_band_fallback_point(**base)


def test_default_bearing_samples_is_dense_enough():
    assert DEFAULT_BEARING_SAMPLES >= 36


# --------------------------------------------------------------------------- #
# Live e2e probes: the real navigator over the real sim.                      #
# --------------------------------------------------------------------------- #


def test_wait_by_the_bench_from_behind_is_committed_not_banished():
    """The reported defect: bench in range, behind the robot, 'wait by the bench'.

    Before the fix the bench was grounded then released as unreachable and
    excluded from the map, so the mission ended semantic_target_not_found with
    the bench never committed. After the fix it must commit the real bench.
    """

    episode = _episode("nav-object_relative-B-09-0811098d")
    nav, mission, committed, _trace = _drive(episode, max_steps=_ARRIVAL_BUDGET_STEPS)
    assert committed, "bench was never committed — search-reground loop still banishes it"
    assert "bench_1" not in nav._unreachable_candidates, (
        "bench_1 was banished to the excluding map — the defect is back"
    )
    assert mission.metadata.get("grounding_outcome") == "RESOLVED"


def test_go_to_the_bench_from_behind_reaches_the_goal_band():
    """End to end: from a bench-not-in-frustum start the dog arrives in the K0
    ``near`` band the directive is scored against."""

    episode = _episode("nav-object_relative-B-09-0811098d")
    runner = NavInstructRunner(mode="candidate", max_steps=_ARRIVAL_BUDGET_STEPS)
    result = runner.run_episode(episode)
    assert result.grounding_outcome == "RESOLVED", (
        f"never grounded the bench: {result.reason}"
    )
    final = result.trace[-1]
    assert episode.goal.contains(
        float(final["x"]), float(final["y"]), anchor_xy=episode.goal.center
    ), "robot did not reach the bench's arrival band"
    assert result.score.success, (
        f"grounded and inside the goal but not scored arrived: {result.reason}"
    )


def test_flickering_target_reaches_two_sightings_and_commits():
    """B-05 style: the bench enters on the frustum's trailing edge for a single
    tick. The confirmation must steer toward it and confirm, not spin it out."""

    episode = _episode("nav-object_relative-B-05-7d441aee")
    _nav, mission, committed, _trace = _drive(
        episode, max_steps=_ARRIVAL_BUDGET_STEPS
    )
    assert committed, "flickering bench never reached the two-sighting commit gate"
    assert mission.metadata.get("grounding_outcome") == "RESOLVED"


def test_absent_bench_still_honestly_fails_no_hallucinated_commit():
    """A bench that is never in the scene must still fail honestly — the fix
    must not manufacture a commit for a target the frustum never emits."""

    episode = _episode("nav-object_relative-E-20-0c739ea2")
    assert episode.absent_target
    _nav, _mission, committed, _trace = _drive(episode, max_steps=_ARRIVAL_BUDGET_STEPS)
    assert not committed, "committed to an absent target — a hallucinated arrival"
    runner = NavInstructRunner(mode="candidate", max_steps=_ARRIVAL_BUDGET_STEPS)
    result = runner.run_episode(episode)
    assert not result.score.success
    assert not result.score.scorer_arrival, "false arrival on an absent target"
