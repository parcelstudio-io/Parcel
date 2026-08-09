"""An interchangeable goal must not be won by whichever instance confirmed first.

The 2026-08-07 region-instance arbitration (ruling 2) outlawed first-seen-wins
for interchangeable goals: with two or more qualified instances in one view,
commit the boundary-nearest; with one, complete the bounded look-around first.

``REGION_INSTANCE_STATUS.md`` residual 1 recorded that the in-view branch still
had a hole, and named the one-line fix. The branch minimised over the
*confirmed* subset while gating on ``len(qualified) >= 2``, so an instance that
entered the frustum earlier — and therefore reached ``required_observations``
earlier — was committed even when a **nearer** instance was already visible and
merely one sighting short. That is first-confirmed-wins in the exact case the
ruling forbids. It cannot fire when both instances enter on the same tick,
because then their sighting counts advance together, which is why the existing
suite never caught it: every case in it shows both instances from tick one.

These cases show the instances at *different* times, which is what a real sweep
does, and pin both halves — the hole, and the rule that closed it.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from parcel_robot.navigation.base import MidLevelCommand, NavObservation
from parcel_robot.navigation.goals import SemanticGoal
from parcel_robot.navigation.search import ActiveSemanticSearch
from parcel_robot.navigation.semantic_map import SemanticCandidate

#: Deliberately far apart so no rounding decides anything: the early one is
#: 6.0 m away, the late one 2.0 m.
EARLY_XY = (6.0, 0.0)
LATE_XY = (2.0, 0.0)


def _candidate(entity_id: str, xy: tuple[float, float]) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=entity_id,
        label="lamppost",
        kind="object",
        x=xy[0],
        y=xy[1],
        z=0.0,
        confidence=0.98,
        source="test",
        reachable=True,
        metadata={"radius_m": 0.06},
    )


class _ScriptedMap:
    """Returns a different view per tick — a sweep, not a static frustum."""

    def __init__(self, *views: tuple[SemanticCandidate, ...]) -> None:
        self._views = list(views)
        self._tick = 0

    def query(self, goal, observation) -> list[SemanticCandidate]:
        view = self._views[min(self._tick, len(self._views) - 1)]
        self._tick += 1
        return list(view)


def _goal() -> SemanticGoal:
    return SemanticGoal(
        query="lamppost",
        kind="object",
        superlative="nearest",  # interchangeable, without being a region
        required_observations=2,
    )


def _observation() -> NavObservation:
    return NavObservation(position=(0.0, 0.0, 0.0), heading_deg=0.0, extras={})


def test_a_confirmed_far_instance_does_not_beat_a_visible_nearer_unconfirmed_one():
    early = _candidate("early", EARLY_XY)
    late = _candidate("late", LATE_XY)
    search = ActiveSemanticSearch(max_steps=80, yaw_rate=0.35)
    observation = _observation()
    # tick 1: only `early`. tick 2: both — `early` now confirmed, `late` not.
    semantic_map = _ScriptedMap((early,), (early, late), (early, late))
    goal = _goal()

    first = search.observe(goal, semantic_map, observation)
    assert isinstance(first, MidLevelCommand), "committed on a single sighting"

    second = search.observe(goal, semantic_map, observation)
    assert isinstance(second, MidLevelCommand), (
        "committed the earlier-confirmed instance while a nearer one was "
        "visible but one sighting short — first-confirmed-wins"
    )

    third = search.observe(goal, semantic_map, observation)
    assert isinstance(third, SemanticCandidate)
    assert third.candidate_id == "late", "the nearest visible instance must win"


def test_two_instances_confirmed_together_still_commit_in_view_without_a_sweep():
    """The branch keeps its whole point: a comparison inside one view commits.

    This is the case the existing suite covers, and it must not have become
    slower — an 8 s look-around for a choice that is already well defined would
    be a regression on every region goal.
    """

    early = _candidate("early", EARLY_XY)
    late = _candidate("late", LATE_XY)
    search = ActiveSemanticSearch(max_steps=80, yaw_rate=0.35)
    both = (early, late)
    semantic_map = _ScriptedMap(both, both)
    goal = _goal()

    assert isinstance(search.observe(goal, semantic_map, _observation()), MidLevelCommand)
    committed = search.observe(goal, semantic_map, _observation())

    assert isinstance(committed, SemanticCandidate)
    assert committed.candidate_id == "late"
    assert search._steps == 2, "the in-view comparison must not spend the sweep"


def test_a_lone_visible_instance_still_completes_the_look_around():
    """Ruling 2's other half, unchanged: one visible instance is not a choice."""

    early = _candidate("early", EARLY_XY)
    search = ActiveSemanticSearch(max_steps=6, yaw_rate=0.35)
    semantic_map = _ScriptedMap((early,))
    goal = _goal()

    for tick in range(5):
        step = search.observe(goal, semantic_map, _observation())
        assert isinstance(step, MidLevelCommand), f"committed early on tick {tick}"
    committed = search.observe(goal, semantic_map, _observation())
    assert isinstance(committed, SemanticCandidate)
    assert committed.candidate_id == "early"


def test_a_non_interchangeable_goal_keeps_first_confirmed_wins():
    """Unchanged by design: without a superlative an object goal is not a set.

    "go to the lamppost" names one thing; which one is a grounding/ambiguity
    question, not a ranking one, and the arbitration deliberately left that
    path alone.
    """

    early = _candidate("early", EARLY_XY)
    late = _candidate("late", LATE_XY)
    search = ActiveSemanticSearch(max_steps=80, yaw_rate=0.35)
    semantic_map = _ScriptedMap((early,), (early, late))
    goal = SemanticGoal(query="lamppost", kind="object", required_observations=2)

    assert isinstance(search.observe(goal, semantic_map, _observation()), MidLevelCommand)
    committed = search.observe(goal, semantic_map, _observation())

    assert isinstance(committed, SemanticCandidate)
    assert committed.candidate_id == "early"
