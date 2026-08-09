"""Metamorphic relations over NAV_INSTRUCT — nightly tier (eval instrument 3).

Two relations, both label-free:

* **rigid-transform equivariance** — mirror or rotate the scene *and* the
  episode; the trajectory must be the same trajectory, transformed;
* **detector-dropout monotonicity** — raise the miss probability and
  performance must not improve.

Nightly, not PR: each case boots a MuJoCo world per run and the equivariance
half runs the same episode up to ``REPEAT_N`` times to measure this harness's
own variability. Set ``PARCEL_NIGHTLY=1`` to run:

    PARCEL_NIGHTLY=1 .parcel/bin/python -m pytest tests/test_nav_metamorphic.py -q

The pure half — the transforms themselves — runs in the default suite, because
a transform that is wrong makes every nightly verdict meaningless and costs
nothing to check.
"""

from __future__ import annotations

import itertools
import math
import os
import statistics

import pytest

from evals.nav_instruct.generator import EPISODE_SET_V2, generate_minival
from evals.nav_instruct.metamorphic import (
    EQUIVARIANCE_FLOOR_M,
    REPEAT_N,
    TRANSFORMS,
    dropout_tier,
    equivariance_verdict,
    final_pose,
    transform_episode,
    transform_goal,
    transform_scene_xml,
    transform_xy,
    transform_yaw,
    write_transformed_scene,
)
from evals.nav_instruct.runner import ARRIVAL_RULE_FOR_VERSION, NavInstructRunner
from evals.nav_instruct.scene_truth import SCENE_PATH

NIGHTLY = pytest.mark.skipif(
    not os.environ.get("PARCEL_NIGHTLY"),
    reason="nightly tier: set PARCEL_NIGHTLY=1 (boots a MuJoCo world per run)",
)

#: The 2–3 episodes the nightly half runs. One per scene-dependent family, all
#: tier A so the relation is tested on episodes that actually move the robot.
MR_EPISODE_IDS: tuple[str, ...] = (
    "nav-region_goal-A-00-1c735162",
    "nav-object_goal-A-00-4caa923b",
    "nav-object_relative-A-00-3efbba45",
)

#: Dropout rungs. Single-variable by construction (see ``metamorphic.dropout_tier``).
DROPOUT_LADDER: tuple[float, ...] = (0.0, 0.2, 0.5)


def _episodes():
    by_id = {ep.episode_id: ep for ep in generate_minival(version=EPISODE_SET_V2)}
    return [by_id[episode_id] for episode_id in MR_EPISODE_IDS]


# ---------------------------------------------------------------------------
# pure half — the transforms themselves (default suite)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", TRANSFORMS)
def test_transform_is_an_isometry(name: str) -> None:
    """A rigid transform preserves every distance a band or radius encodes."""

    points = [(0.0, 0.0), (1.0, 0.5), (-5.0, 3.15), (5.0, 3.1), (7.0, -6.0)]
    for i, a in enumerate(points):
        for b in points[i + 1 :]:
            before = math.dist(a, b)
            after = math.dist(transform_xy(name, *a), transform_xy(name, *b))
            assert math.isclose(before, after, abs_tol=1e-9)


def test_identity_transform_changes_nothing() -> None:
    """The machinery must be a provable no-op before it is trusted to detect."""

    episode = _episodes()[0]
    assert transform_episode(episode, "identity").goal.as_dict() == episode.goal.as_dict()
    assert transform_episode(episode, "identity").start_pose == episode.start_pose
    text = SCENE_PATH.read_text(encoding="utf-8")
    once = transform_scene_xml(text, "identity")
    assert transform_scene_xml(once, "identity") == once


@pytest.mark.parametrize("name", ("mirror_y", "rotate_90"))
def test_transform_moves_every_landmark_and_keeps_every_name(name: str, tmp_path) -> None:
    """Identity is preserved, geometry is not — the whole point of the relation."""

    from evals.nav_instruct.scene_truth import derive_scene_truth

    original = derive_scene_truth(SCENE_PATH)
    moved_path = write_transformed_scene(SCENE_PATH, name, tmp_path)
    moved = derive_scene_truth(moved_path)
    assert set(moved) == set(original), "a transform must not rename or drop an entity"
    changed = 0
    for entity_id, entry in original.items():
        after = moved[entity_id]
        assert after["label"] == entry["label"]
        if "position" in entry:
            expected = transform_xy(name, *entry["position"])
            assert math.isclose(after["position"][0], expected[0], abs_tol=1e-4)
            assert math.isclose(after["position"][1], expected[1], abs_tol=1e-4)
            assert math.isclose(after["radius_m"], entry["radius_m"], abs_tol=1e-4)
            changed += int(entry["position"] != after["position"])
    assert changed > 0, "the transform did not move anything"


@pytest.mark.parametrize("name", ("mirror_y", "rotate_90"))
def test_transformed_goal_contains_the_transformed_point(name: str) -> None:
    """Membership is equivariant: the predicate cannot be axis-dependent."""

    for episode in _episodes():
        goal = episode.goal
        moved = transform_goal(goal, name)
        for probe in ((0.0, 0.0), (0.2, 3.0), (-2.5, 3.045), (5.0, 3.1), (8.0, -8.0)):
            before = goal.contains(probe[0], probe[1], anchor_xy=goal.center)
            after_xy = transform_xy(name, *probe)
            after = moved.contains(after_xy[0], after_xy[1], anchor_xy=moved.center)
            assert before == after, f"{name}: membership flipped at {probe}"


def test_yaw_transform_is_consistent_with_the_position_transform() -> None:
    """A heading and the point it points at must move together."""

    for name in ("mirror_y", "rotate_90"):
        for yaw in (0.0, 0.7, 1.5708, -2.4):
            ahead = (math.cos(yaw), math.sin(yaw))
            moved_ahead = transform_xy(name, *ahead)
            moved_yaw = transform_yaw(name, yaw)
            assert math.isclose(math.cos(moved_yaw), moved_ahead[0], abs_tol=1e-9)
            assert math.isclose(math.sin(moved_yaw), moved_ahead[1], abs_tol=1e-9)


def test_the_verdict_reports_the_degenerate_z_test_rather_than_hiding_it() -> None:
    """A deterministic harness has no z scale; the verdict must say so."""

    verdict = equivariance_verdict(
        episode_id="probe",
        transform="mirror_y",
        discrepancy_m=0.01,
        repeats_m=[0.0] * REPEAT_N,
        success_matches=True,
    )
    assert not verdict.violated
    assert verdict.repeat_sd_m == 0.0
    assert "no scale" in verdict.detail
    loud = equivariance_verdict(
        episode_id="probe",
        transform="mirror_y",
        discrepancy_m=EQUIVARIANCE_FLOOR_M + 1.0,
        repeats_m=[0.0] * REPEAT_N,
        success_matches=True,
    )
    assert loud.violated


def test_a_success_mismatch_is_a_violation_at_any_distance() -> None:
    """Same trajectory, different verdict, is a violation regardless of metres."""

    verdict = equivariance_verdict(
        episode_id="probe",
        transform="rotate_90",
        discrepancy_m=0.0,
        repeats_m=[0.0],
        success_matches=False,
    )
    assert verdict.violated


# ---------------------------------------------------------------------------
# nightly half — the relations against the real sim
# ---------------------------------------------------------------------------


#: Measured 2026-08-07 with this module. ``go to the sidewalk`` is the one
#: episode that fails the relation, and it fails **identically under both
#: transforms** — 3.0196 m, ``arrived_verified`` -> ``semantic_target_unreachable``,
#: the robot never leaving its start pose in the transformed scene. The identity
#: transform through the same ET round-trip arrives normally (184 ticks, dtg
#: 0.0), so the machinery is not the cause. The other two episodes are exactly
#: equivariant (discrepancy 0.0000 m under both transforms).
#:
#: The region family is also the only family with two same-label instances
#: (``sidewalk`` / ``sidewalk_south``), which a mirror swaps sides. That points
#: at the region-instance-selection question Lane D left open — "does 'the
#: sidewalk' mean a specific polygon, or any sidewalk?" — but pointing is not
#: attributing, and this module does not attribute it.
_EQUIVARIANCE_XFAIL = pytest.mark.xfail(
    reason=(
        "MEASURED VIOLATION 2026-08-07, not a flake: 'go to the sidewalk' "
        "arrives (dtg 0.0) in the frozen block and reports "
        "semantic_target_unreachable without moving in both the mirrored and "
        "the 90deg-rotated scene, discrepancy 3.0196 m under each, "
        "success True -> False. Repeat spread of the untransformed episode is "
        "2.9e-5 m, so this is 5 orders of magnitude outside variability. The "
        "identity transform through the same code path arrives normally, so "
        "the transform machinery is not the cause. Region goals are the only "
        "family with two same-label instances; the open region-instance "
        "selection question (Lane D / stratum 3) is the first place to look. "
        "This pin flips to a hard gate when that lands."
    ),
    strict=False,
)


def _equivariance_case(episode_id: str, transform: str):
    marks = [_EQUIVARIANCE_XFAIL] if episode_id.startswith("nav-region_goal") else []
    return pytest.param(episode_id, transform, marks=marks, id=f"{episode_id}-{transform}")


@NIGHTLY
@pytest.mark.slow
@pytest.mark.parametrize(
    ("episode_id", "name"),
    [
        _equivariance_case(episode_id, transform)
        for episode_id in MR_EPISODE_IDS
        for transform in ("mirror_y", "rotate_90")
    ],
)
def test_rigid_transform_equivariance(episode_id: str, name: str, tmp_path) -> None:
    """Mirror/rotate scene + episode; the trajectory must transform with them.

    One case per (episode, transform) so a violation names the episode instead
    of reddening the whole relation — the difference between an instrument and
    an alarm.
    """

    moved_scene = write_transformed_scene(SCENE_PATH, name, tmp_path)
    rule = ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V2]
    base_runner = NavInstructRunner(max_steps=200, mode="baseline", arrival_rule=rule)
    moved_runner = NavInstructRunner(
        max_steps=200, mode="baseline", arrival_rule=rule, scene=moved_scene
    )
    episode = {item.episode_id: item for item in _episodes()}[episode_id]

    repeats = [final_pose(base_runner.run_episode(episode)) for _ in range(REPEAT_N)]
    spread = [
        math.dist(repeats[i], repeats[j])
        for i in range(len(repeats))
        for j in range(i + 1, len(repeats))
    ]
    base = base_runner.run_episode(episode)
    moved = moved_runner.run_episode(transform_episode(episode, name))
    expected = transform_xy(name, *final_pose(base))
    verdict = equivariance_verdict(
        episode_id=episode_id,
        transform=name,
        discrepancy_m=math.dist(expected, final_pose(moved)),
        repeats_m=spread,
        success_matches=bool(base.score.success) == bool(moved.score.success),
    )
    assert not verdict.violated, f"equivariance violated: {verdict.as_dict()}"


#: Perception seeds per dropout rung. Dropout is a *stochastic* intervention, so
#: a single seed cannot support a monotonicity claim: at n=3 episodes one seed
#: moves the success count by a whole episode. Three seeds is still small and is
#: reported as such.
PERCEPTION_SEEDS: tuple[int, ...] = (11, 23, 41)


@NIGHTLY
@pytest.mark.slow
def test_detector_dropout_is_monotone() -> None:
    """More missed detections must never make the robot do better.

    Judged on the **mean over seeds** with a tolerance of one episode: the
    ladder is 3 episodes wide, so a strict integer comparison would be a claim
    about a single coin flip. What this catches is the class of bug where noise
    systematically *helps* — a sign error, or an oracle leak that a dropout mask
    exposes — not a one-episode wobble.
    """

    from parcel_robot.detection_adapter.perception_chain import (
        PerceptionChain,
        use_perception_chain,
    )

    episodes = _episodes()
    rule = ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V2]
    # One episode out of the ladder's width. Anything smaller is noise at n=3.
    tolerance = 1.0 / len(episodes)
    rungs: list[dict[str, float]] = []
    try:
        for probability in DROPOUT_LADDER:
            per_seed: list[float] = []
            for seed in PERCEPTION_SEEDS:
                use_perception_chain(PerceptionChain(dropout_tier(probability), seed=seed))
                runner = NavInstructRunner(max_steps=200, mode="baseline", arrival_rule=rule)
                results = [runner.run_episode(episode) for episode in episodes]
                per_seed.append(
                    sum(1 for item in results if item.score.success) / len(episodes)
                )
            rungs.append(
                {
                    "dropout": probability,
                    "sr_mean": statistics.fmean(per_seed),
                    "sr_min": min(per_seed),
                    "sr_max": max(per_seed),
                }
            )
    finally:
        use_perception_chain(None)

    for low, high in itertools.pairwise(rungs):
        assert high["sr_mean"] <= low["sr_mean"] + tolerance, (
            f"dropout {high['dropout']} scored SR {high['sr_mean']:.3f} against "
            f"{low['sr_mean']:.3f} at {low['dropout']}, beyond the "
            f"{tolerance:.3f} one-episode tolerance: more missed detections made "
            f"the robot systematically better, which is a bug in the noise model "
            f"or an oracle leak. ladder={rungs}"
        )
