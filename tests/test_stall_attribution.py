"""Card C3 (STALL-CLASS-1) — the stall taxonomy and the door it chooses.

The leaf's contract, and the one behavioural claim the card makes about
``DirectiveNavigator._progress_watchdog``: **on an armed navigator** a REPEATED
stall whose planner still has a route and whose body did not travel takes the
SINGLE release door (so the instance is remembered and the rescan cannot
re-commit it), and every other stall — including the first held one — keeps the
pre-C3 path byte-identically.

Card F1: the door is behind ``held_stall_release``, **default OFF and OFF on the
shipped profile**. The flag-OFF cells below are the ones that matter most: they
assert the watchdog reads and writes nothing at all, which is what makes the
frozen mutation panel and the v4 minival reproduce.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from parcel_robot.navigation import stall_attribution as stall
from parcel_robot.navigation.base import GoalPose, Mission, NavObservation
from parcel_robot.navigation.goals import SemanticGoal
from parcel_robot.navigation.pipeline import DirectiveNavigator

# ---------------------------------------------------------------- leaf module


def test_progress_hysteresis_is_the_only_progress_rule():
    assert stall.goal_progress_made(None, 12.0) is True  # first tick seeds
    assert stall.goal_progress_made(5.0, 5.0 - stall.PROGRESS_HYSTERESIS_M) is False
    assert stall.goal_progress_made(5.0, 5.0 - stall.PROGRESS_HYSTERESIS_M - 1e-9) is True
    assert stall.goal_progress_made(5.0, 6.0) is False


def test_person_yield_clause_is_unchanged_by_this_card():
    # Exactly the pre-C3 predicate: strictly inside the navigator's own person
    # stop ring, and never fired when the channel carries nothing.
    assert stall.person_yield_holds(None, 1.2) is False
    assert stall.person_yield_holds(1.19, 1.2) is True
    assert stall.person_yield_holds(1.2, 1.2) is False


@pytest.mark.parametrize(
    ("route_status", "body_is_still", "expected"),
    [
        ("planned", True, stall.HELD_WITH_ROUTE),
        ("partial", True, stall.HELD_WITH_ROUTE),
        ("planned", False, stall.DRIFTING),
        ("partial", False, stall.DRIFTING),
        # The planner's own proof of unroutability has its own authority
        # (``_unroutable_goal_recovery``); this taxonomy must not shadow it.
        ("no_path", True, stall.NO_ROUTE),
        ("goal_blocked", True, stall.NO_ROUTE),
        ("at_goal", True, stall.NO_ROUTE),
        (None, True, stall.NO_ROUTE),
    ],
)
def test_classify_stall_reads_only_route_and_odometer(route_status, body_is_still, expected):
    assert stall.classify_stall(route_status, body_is_still=body_is_still) == expected


def test_record_stall_writes_the_class_and_counts_only_held_stalls():
    meta: dict = {}
    assert stall.record_stall(meta, "planned", True) == 1
    assert meta[stall.STALL_CLASS_KEY] == stall.HELD_WITH_ROUTE
    assert meta[stall.HELD_STALLS_KEY] == 1
    assert stall.record_stall(meta, "planned", True) == 2
    assert meta[stall.HELD_STALLS_KEY] == 2
    # A non-held stall records its class and never advances the held counter.
    assert stall.record_stall(meta, "no_path", True) == 0
    assert meta[stall.STALL_CLASS_KEY] == stall.NO_ROUTE
    assert meta[stall.HELD_STALLS_KEY] == 2


def test_the_first_held_stall_never_reaches_the_release_threshold():
    """The grace re-ground is the measured floor, not a preference."""

    assert stall.HELD_RELEASE_AFTER >= 2
    assert stall.record_stall({}, "planned", True) < stall.HELD_RELEASE_AFTER


def test_routed_statuses_are_a_subset_of_the_planner_vocabulary():
    # ``grid_planner.RouteStatus`` — keep the leaf honest if that Literal moves.
    from parcel_robot.navigation.grid_planner import RouteStatus

    assert stall.ROUTED_STATUSES <= set(RouteStatus.__args__)


def test_the_leaf_holds_no_safety_value():
    """No floor, no ring, no policy number may live in this module."""

    source = (stall.__file__ or "").strip()
    assert source.endswith("stall_attribution.py")
    with open(source, encoding="utf-8") as handle:
        code = [line for line in handle if not line.lstrip().startswith("#")]
    body = "".join(code).split('"""', 2)[-1]
    for forbidden in ("obstacle_stop_m", "stop_distance_m", "0.65", "0.8", "1.02"):
        assert forbidden not in body, f"{forbidden!r} must not be a value in the stall leaf"


# ------------------------------------------------------- the watchdog's doors


class _RoutedNavigator:
    """Minimal planner stand-in: it only answers ``last_route_status``."""

    def __init__(self, status: str | None):
        self.last_route_status = status

    def close(self) -> None:  # pragma: no cover — never reached in these tests
        pass


def _navigator_at_stall(
    route_status: str | None,
    *,
    body_is_still: bool,
    replans: int = 0,
    held: int = 1,
    armed: bool = True,
):
    """A DirectiveNavigator parked exactly one tick before the watchdog fires.

    ``held`` is how many held stalls this mission has ALREADY had, so the
    default (1) puts the next held stall on the release threshold.
    """

    nav = DirectiveNavigator.__new__(DirectiveNavigator)
    nav.mission = Mission(
        directive="go to the bench",
        goal=GoalPose(x=3.0, y=0.0),
        status="running",
        semantic_goal=SemanticGoal(query="bench", terminal_relation="near"),
        metadata={
            "replan_count": replans,
            "candidate_id": "bench_1",
            stall.HELD_STALLS_KEY: held,
        },
    )
    nav.held_stall_release = armed
    nav.progress_timeout_steps = 200
    nav.max_semantic_replans = 2
    nav._best_goal_distance_m = 3.0
    nav._steps_without_progress = 199
    nav._body_is_still = body_is_still
    nav._navigator = _RoutedNavigator(route_status)
    nav.collision = type("_P", (), {"person_stop_m": 1.2})()
    nav.released: list[tuple[str, str]] = []
    nav.replanned: list[tuple[int, str]] = []
    nav._release_unreachable_candidate = lambda cid, *, note: (
        nav.released.append((cid, note)) or "released"
    )
    nav._begin_semantic_replan = lambda replans, *, note: (
        nav.replanned.append((replans, note)) or "replanned"
    )
    return nav


def _observation(x: float = 0.0, *, person_m: float | None = None) -> NavObservation:
    return NavObservation(
        position=(x, 0.0, 0.0),
        heading_deg=0.0,
        nearest_person_m=person_m,
        nearest_obstacle_m=None,
    )


def test_a_repeated_held_stall_takes_the_release_door_and_records_the_class():
    """17+9 of NAV-GEN-1's 26 non-POI stalls: route planned, body still."""

    nav = _navigator_at_stall("planned", body_is_still=True)
    assert nav._progress_watchdog(_observation()) == "released"
    assert nav.released == [("bench_1", stall.HELD_RELEASE_NOTE)]
    assert nav.replanned == []
    assert nav.mission.metadata[stall.STALL_CLASS_KEY] == stall.HELD_WITH_ROUTE
    assert nav.mission.metadata[stall.HELD_STALLS_KEY] == stall.HELD_RELEASE_AFTER


def test_the_first_held_stall_of_a_mission_keeps_the_pre_c3_replan_path():
    """The grace re-ground. Without it NAV-GEN-1 loses four episodes that
    reach their goal today — see ``HELD_RELEASE_AFTER``."""

    nav = _navigator_at_stall("planned", body_is_still=True, held=0)
    assert nav._progress_watchdog(_observation()) == "replanned"
    assert nav.replanned == [(0, "semantic_replan_after_no_progress")]
    assert nav.released == []
    assert nav.mission.metadata[stall.STALL_CLASS_KEY] == stall.HELD_WITH_ROUTE
    assert nav.mission.metadata[stall.HELD_STALLS_KEY] == 1


def test_a_moving_stall_keeps_the_pre_c3_replan_path():
    nav = _navigator_at_stall("planned", body_is_still=False)
    assert nav._progress_watchdog(_observation()) == "replanned"
    assert nav.replanned == [(0, "semantic_replan_after_no_progress")]
    assert nav.released == []
    assert nav.mission.metadata[stall.STALL_CLASS_KEY] == stall.DRIFTING


def test_an_unroutable_stall_keeps_the_pre_c3_replan_path():
    """``no_path`` belongs to ``_unroutable_goal_recovery``, not to this door."""

    nav = _navigator_at_stall("no_path", body_is_still=True)
    assert nav._progress_watchdog(_observation()) == "replanned"
    assert nav.replanned == [(0, "semantic_replan_after_no_progress")]
    assert nav.released == []


def test_a_poi_mission_is_untouched_and_still_fails_loudly():
    """No semantic goal (card C1's crosswalk arm): no release door at all."""

    nav = _navigator_at_stall("planned", body_is_still=True)
    nav.mission.semantic_goal = None
    command = nav._progress_watchdog(_observation())
    assert command.stop is True
    assert command.note == "navigation_no_progress"
    assert nav.mission.status == "failed"
    assert nav.mission.metadata["resolution_state"] == "stalled"
    assert nav.released == [] and nav.replanned == []


def test_a_spent_ladder_still_fails_loudly_even_when_held():
    """Amendment A1: the fix may not trade a loud failure for silence."""

    nav = _navigator_at_stall("planned", body_is_still=True, replans=2)
    command = nav._progress_watchdog(_observation())
    assert command.stop is True
    assert command.note == "navigation_no_progress"
    assert nav.mission.status == "failed"
    # The release door lives INSIDE the replan branch, so a spent ladder never
    # reaches it — armed or not, the terminal is the pre-C3 one, verbatim.
    assert stall.STALL_CLASS_KEY not in nav.mission.metadata
    assert nav.released == []


def test_progress_and_person_yield_short_circuit_before_any_classification():
    """Neither door is reachable while the mission converges or yields."""

    nav = _navigator_at_stall("planned", body_is_still=True)
    assert nav._progress_watchdog(_observation(x=1.0)) is None  # distance 2.0 < 3.0
    assert nav._steps_without_progress == 0
    assert stall.STALL_CLASS_KEY not in nav.mission.metadata

    nav = _navigator_at_stall("planned", body_is_still=True)
    assert nav._progress_watchdog(_observation(person_m=0.9)) is None
    assert nav._steps_without_progress == 199  # not advanced by a yield tick
    assert stall.STALL_CLASS_KEY not in nav.mission.metadata


def test_the_watchdog_still_measures_range_in_the_map_frame():
    """C3 moved the rule into the leaf; it did not move the frame."""

    nav = _navigator_at_stall("planned", body_is_still=True)
    nav._best_goal_distance_m = None
    assert nav._progress_watchdog(_observation(x=-1.0)) is None
    assert nav._best_goal_distance_m == pytest.approx(math.hypot(3.0 - (-1.0), 0.0))


# ------------------------------------------------------- card F1: the flag OFF


def test_the_flag_is_off_by_default_on_a_real_navigator():
    """The shipped profile must never arm the door by accident."""

    nav = DirectiveNavigator.from_config()
    try:
        assert nav.held_stall_release is False
    finally:
        nav.close()


def test_the_shipped_navigation_config_does_not_carry_the_key():
    import yaml

    repo = Path(__file__).resolve().parents[1]
    data = yaml.safe_load(
        (repo / "configs" / "navigation" / "default.yaml").read_text(encoding="utf-8")
    )
    assert stall.HELD_RELEASE_FLAG not in (data.get("progress_watchdog") or {})


def test_held_release_due_reads_and_writes_nothing_when_disabled():
    """The F1 contract, asserted on the mapping itself."""

    meta: dict = {}
    assert stall.held_release_due(meta, "planned", True, enabled=False) is False
    assert meta == {}, "flag-OFF must not touch the mission record"
    # ... and the ARMED call on the same mapping does record, so the assertion
    # above is not passing merely because nothing ever writes.
    assert stall.held_release_due(meta, "planned", True, enabled=True) is False
    assert meta[stall.HELD_STALLS_KEY] == 1


def test_flag_off_watchdog_is_byte_identical_to_the_pre_c3_path():
    """A repeated held stall on an UNARMED navigator takes the plain replan."""

    nav = _navigator_at_stall("planned", body_is_still=True, held=9, armed=False)
    before = dict(nav.mission.metadata)
    assert nav._progress_watchdog(_observation()) == "replanned"
    assert nav.replanned == [(0, "semantic_replan_after_no_progress")]
    assert nav.released == []
    # No classification, no counter, no stall_class — the mission record is
    # exactly what it was.
    assert nav.mission.metadata == before
    assert stall.STALL_CLASS_KEY not in nav.mission.metadata


def test_flag_off_still_fails_loudly_when_the_ladder_is_spent():
    nav = _navigator_at_stall("planned", body_is_still=True, held=9, replans=2, armed=False)
    command = nav._progress_watchdog(_observation())
    assert command.stop is True
    assert command.note == "navigation_no_progress"
    assert nav.mission.status == "failed"
    assert nav.mission.metadata["resolution_state"] == "stalled"
    assert stall.STALL_CLASS_KEY not in nav.mission.metadata


def test_the_flag_arrives_from_the_navigation_config_and_from_a_kwarg(tmp_path):
    import shutil

    import yaml

    repo = Path(__file__).resolve().parents[1]
    source = repo / "configs" / "navigation" / "default.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    models = repo / "configs" / "navigation" / "models"
    shutil.copytree(models, tmp_path / "models")
    data["models_root"] = str(tmp_path / "models")
    data["pois_path"] = str(repo / "configs/navigation/cities/demo_pois.yaml")
    data.setdefault("progress_watchdog", {})[stall.HELD_RELEASE_FLAG] = True
    path = tmp_path / "default.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    armed = DirectiveNavigator.from_config(path)
    try:
        assert armed.held_stall_release is True
    finally:
        armed.close()
    # The kwarg wins over the file, in both directions (the eval runner's
    # navigator_overrides idiom).
    off = DirectiveNavigator.from_config(path, held_stall_release=False)
    try:
        assert off.held_stall_release is False
    finally:
        off.close()
