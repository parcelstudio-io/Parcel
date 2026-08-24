"""Half-scale-profile NAV_INSTRUCT smoke at constant Froude (stratum-5 probe).

Uses the existing NAV_INSTRUCT runner's programmatic API on two episodes — no
new harness (plan anti-goal). One run at the Go2 profile, one at a geometrically
half-size profile whose speed regimes are re-derived at the *same Froude
number*, so the two robots are dynamically similar rather than one being an
arbitrarily slowed copy.

**The scale-covariance assertion is expected to fail today**, and is marked
``xfail`` with attribution below. It is the pin that flips green when the
profile finally reaches the planner.
"""

from __future__ import annotations

import dataclasses

import pytest

from parcel_robot.authority import DEFAULT_SPEED_REGIME, SafetyEnvelope, SpeedRegime
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE, RobotProfile

pytest.importorskip("mujoco")

from evals.nav_instruct.generator import generate_minival
from evals.nav_instruct.runner import NavInstructRunner
from parcel_robot.simulation.headless_city import (
    DEFAULT_ROBOT_CONFIG,
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
)

#: Two episodes, two families, from the frozen minival. Deliberately small:
#: this is a smoke, not a measured run, and it must not add minutes to the gate.
SMOKE_FAMILIES = ("object_goal", "region_goal")


def half_scale_profile() -> RobotProfile:
    """Geometrically half-size Go2: embodiment bucket halved, nothing else."""

    base = DEFAULT_ROBOT_PROFILE
    return dataclasses.replace(
        base,
        name="half-go2",
        upper_link_m=base.upper_link_m / 2.0,
        lower_link_m=base.lower_link_m / 2.0,
        stance_z_m=base.stance_z_m / 2.0,
        footprint_radius_m=base.footprint_radius_m / 2.0,
        scan_height_m=base.scan_height_m / 2.0,
        obstacle_clearance_height_m=base.obstacle_clearance_height_m / 2.0,
    )


def smoke_episodes() -> tuple:
    matrix = generate_minival()
    picked = []
    for family in SMOKE_FAMILIES:
        for episode in matrix:
            if episode.family == family:
                picked.append(episode)
                break
    assert len(picked) == len(SMOKE_FAMILIES)
    return tuple(picked)


def _outcome(result) -> dict:
    """The outcome fields a scale change must be allowed to move."""

    return {
        "episode_id": result.episode_id,
        "mission_status": result.mission_status,
        "reason": result.reason,
        "scorer_arrival": result.scorer_arrival,
        "success": result.score.success,
        "failure": result.score.failure.value,
        "distance_to_goal_m": result.score.distance_to_goal_m,
        "collision_count": result.collision_count,
        "trace_len": len(result.trace),
    }


def _run(profile: RobotProfile | None) -> list[dict]:
    runner = NavInstructRunner(mode="candidate")
    if profile is not None:
        runner.world = HeadlessCityWorld(profile=profile)
        runner.harness = HeadlessCityQualityHarness(
            runner.world, robot_config=DEFAULT_ROBOT_CONFIG
        )
    return [_outcome(runner.run_episode(episode)) for episode in smoke_episodes()]


# ---------------------------------------------------------------------------
# Pure-derivation half of the probe (no sim) — these pass today
# ---------------------------------------------------------------------------


def test_half_scale_regimes_are_dynamically_similar_not_merely_slower() -> None:
    half = half_scale_profile()
    scaled = SpeedRegime.from_froude(half, DEFAULT_SPEED_REGIME.froude)
    assert scaled.froude == pytest.approx(DEFAULT_SPEED_REGIME.froude)
    assert scaled.cruise.vx_mps == pytest.approx(DEFAULT_SPEED_REGIME.cruise.vx_mps / 2**0.5)
    assert scaled.cruise.vx_mps > DEFAULT_SPEED_REGIME.cruise.vx_mps / 2.0


def test_half_scale_envelope_halves_the_body_and_keeps_the_person_zone() -> None:
    envelope = SafetyEnvelope.from_profile(half_scale_profile())
    assert envelope.footprint_radius_m == DEFAULT_ROBOT_PROFILE.footprint_radius_m / 2.0
    assert envelope.person_stop(0.0) == SafetyEnvelope().person_stop(0.0)


def test_the_planner_footprint_is_still_go2_pinned_regardless_of_profile() -> None:
    """Names the exact remaining gap. Flips when grid_planner reads a profile.

    ``GridPlannerConfig.robot_radius_m`` binds the retired geometry constant as
    a dataclass field default, in a file Lane A does not own. Until that is
    injected, the map inflation a half-size robot plans against is a Go2
    inflation, and the half-scale smoke below cannot pass.
    """

    from parcel_robot.navigation.grid_planner import GridPlannerConfig

    assert GridPlannerConfig().robot_radius_m == DEFAULT_ROBOT_PROFILE.footprint_radius_m
    assert GridPlannerConfig().robot_radius_m != half_scale_profile().footprint_radius_m


# ---------------------------------------------------------------------------
# The sim-level probe
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_half_scale_run_still_completes_every_smoke_episode() -> None:
    """Baseline honesty check: shrinking the robot does not crash the stack."""

    outcomes = _run(half_scale_profile())
    assert len(outcomes) == len(SMOKE_FAMILIES)
    for outcome in outcomes:
        assert outcome["trace_len"] > 0
        assert outcome["collision_count"] == 0


@pytest.mark.slow
@pytest.mark.xfail(
    reason=(
        "Scale covariance is not reachable yet. The embodiment profile stops at "
        "the world's clearance oracle and the LiDAR scan height; it does not "
        "reach (a) GridPlannerConfig.robot_radius_m — footprint inflation, "
        "(b) grid_resolution_m / grid_size_cells, which the plan wants pinned as "
        "cells-per-footprint, or (c) the K0 arrival bands, which are Go2-derived "
        "in instructnav/scoring.py by design and would need the goal regions "
        "re-derived per profile. All three live in files Lane A does not own this "
        "round (navigation/pipeline.py, navigation/grid_planner.py, "
        "navigation/grid_navigator.py, evals/**). Expected to flip green when "
        "the profile is injected through the planner."
    ),
    strict=False,
)
def test_half_scale_run_differs_from_the_go2_run() -> None:
    """If the profile reached the planner, halving the body could not be a no-op.

    Deliberately a *difference* assertion, not an equivalence one. Asserting
    that a half-size robot reproduces Go2 outcomes would pass today for the
    wrong reason — it passes precisely because the body change is being
    ignored. What scale covariance requires first is that the change be
    *observable at all*.
    """

    go2 = _run(None)
    half = _run(half_scale_profile())
    assert [row["episode_id"] for row in go2] == [row["episode_id"] for row in half]
    assert go2 != half, (
        "the half-scale run is bit-identical to the Go2 run — the profile is "
        "not reaching the planner"
    )
