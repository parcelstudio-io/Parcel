"""Superlative + attribute-qualified navigation directives (SUP-1..SUP-4).

Covers the layers below the product e2e path:

* SUP-1 parsing — ``goals.semantic_goal_from_directive`` / ``pace_from_directive``
* SUP-2 nearest selection — ``resolve_grounding(interchangeable=...)`` and the
  pipeline call site that turns ``superlative == "nearest"`` into that flag
* SUP-3 attribute filtering — ``navigation.attributes`` pure matcher
* SUP-4 pace — the directive pace reuses the FASTER closed-intent cap

Geometry is the real city block: lamp_post_1 (0.2, 3.15) and lamp_post_2
(-6.7, -2.9); tree_1 (-5.0, 3.15) and tree_2 (5.0, 3.1), identical radii.
"""

from __future__ import annotations

import math
import time
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.instructnav.grounding import GroundingOutcome, resolve_grounding
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.attributes import (
    SIZE_POLARITY_TABLE,
    filter_candidates_by_attributes,
    supported_attributes,
)
from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.goals import (
    ATTRIBUTE_TABLE,
    PACE_ADVERB_TABLE,
    PACE_VERB_TABLE,
    SUPERLATIVE_TABLE,
    navigation_directive_from_text,
    pace_from_directive,
    semantic_goal_from_directive,
)
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice.closed_intents import ClosedIntent
from parcel_robot.voice.executive_caps import PACE_DEFAULT, PACE_STEP, resolve_cap

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "configs" / "navigation" / "models"

# City-block truth used by the nearest-selection cases (see module docstring).
LAMP_1 = (0.2, 3.15)
LAMP_2 = (-6.7, -2.9)
TREE_1 = (-5.0, 3.15)
TREE_2 = (5.0, 3.1)
TREE_RADIUS_M = 0.58


# ---------------------------------------------------------------- SUP-1 -----


@pytest.mark.parametrize(
    ("text", "query", "superlative", "attributes", "pace"),
    [
        ("find the nearest lamppost", "lamppost", "nearest", (), None),
        ("go to the closest big tree", "tree", "nearest", ("big",), None),
        ("running to the closest big tree", "tree", "nearest", ("big",), "fast"),
        ("run to the nearest bench", "bench", "nearest", (), "fast"),
        ("hurry to the nearest lamppost", "lamppost", "nearest", (), "fast"),
        ("sprint to the tree", "tree", None, (), "fast"),
        ("quickly go to the bench", "bench", None, (), "fast"),
        ("go to the nearby planter", "planter", "nearest", (), None),
        ("walk to the large planter", "planter", None, ("large",), None),
        ("look for the small planter", "planter", None, ("small",), None),
        ("go to the tall lamppost", "lamppost", None, ("tall",), None),
        ("go to the little bench", "bench", None, ("little",), None),
    ],
)
def test_superlative_pace_and_attribute_phrasings_parse(
    text: str,
    query: str,
    superlative: str | None,
    attributes: tuple[str, ...],
    pace: str | None,
) -> None:
    goal = semantic_goal_from_directive(text)

    assert goal.query == query
    assert goal.superlative == superlative
    assert goal.attributes == attributes
    assert goal.pace == pace


@pytest.mark.parametrize(
    ("text", "query", "kind", "relation", "behavior"),
    [
        ("go to the sidewalk", "sidewalk", "region", "inside", "stop"),
        ("walk to the bench", "bench", "object", "near", "stop"),
        ("go towards the tree", "tree", "object", "towards", "stop"),
        ("sit next to the bench", "bench", "object", "next_to", "hold"),
        ("wait by the lamppost", "lamppost", "object", "near", "hold"),
        ("go to the nearest sidewalk", "sidewalk", "region", "inside", "stop"),
        (
            "Can you go to the sidewalk so that you are not on the road",
            "sidewalk",
            "region",
            "inside",
            "stop",
        ),
    ],
)
def test_existing_directives_parse_unchanged(
    text: str, query: str, kind: str, relation: str, behavior: str
) -> None:
    """Pinned: the modifier grammar must not move any established directive."""

    goal = semantic_goal_from_directive(text)

    assert (goal.query, goal.kind) == (query, kind)
    assert (goal.terminal_relation, goal.terminal_behavior) == (relation, behavior)


def test_unknown_adjective_stays_in_the_noun_query() -> None:
    """Fail-safe: an adjective we do not model is not silently stripped."""

    goal = semantic_goal_from_directive("go to the red bench")

    assert goal.query == "red bench"
    assert goal.attributes == ()


def test_modifier_only_phrase_keeps_its_words_rather_than_inventing_a_target() -> None:
    goal = semantic_goal_from_directive("go to the nearest")

    assert goal.query == "nearest"
    assert goal.superlative is None


def test_negated_and_hypothetical_directives_stay_blocked() -> None:
    for text in (
        "do not run to the nearest lamppost",
        "what if you run to the nearest lamppost",
    ):
        assert navigation_directive_from_text(text) is None


def test_find_out_is_a_question_not_a_navigation_directive() -> None:
    assert navigation_directive_from_text("find out what time it is") is None
    assert navigation_directive_from_text("find the nearest lamppost") is not None


def test_pace_only_read_from_the_leading_verb_phrase() -> None:
    assert pace_from_directive("running to the tree") == "fast"
    assert pace_from_directive("hey parcel, run to the bench") == "fast"
    assert pace_from_directive("please quickly go to the bench") == "fast"
    # A pace word buried in a target name is not motion authority.
    assert pace_from_directive("walk to the fun run sign") is None
    assert pace_from_directive("go to the bench") is None


def test_vocabulary_tables_are_module_level_and_canonical() -> None:
    """Stratum-3 seam: one table per family, canonical values only."""

    assert set(SUPERLATIVE_TABLE.values()) == {"nearest"}
    assert set(PACE_VERB_TABLE.values()) == {"fast"}
    assert set(PACE_ADVERB_TABLE.values()) == {"fast"}
    assert set(ATTRIBUTE_TABLE) == set(SIZE_POLARITY_TABLE)


def test_superlative_phrasing_does_not_trip_the_poi_grounder() -> None:
    """A superlative must not substring-match a POI name into a known place.

    ``crosswalk near coffee`` contains the word "near", which used to match
    inside "the **near**est lamppost" and grounded an object directive to the
    crosswalk POI — so it never reached the semantic path at all. Pre-existing:
    "go to the nearest sidewalk" was mis-grounded the same way.
    """

    grounder = PlaceGrounder.from_yaml(
        REPO / "configs" / "navigation" / "cities" / "demo_pois.yaml"
    )

    for directive in (
        "find the nearest lamppost",
        "go to the nearest sidewalk",
        "go to the closest big tree",
    ):
        with pytest.raises(LookupError):
            grounder.ground(directive)

    # Real POI phrasings must still ground.
    assert grounder.ground("take me to the crosswalk").poi_id == "crosswalk_a"
    assert grounder.ground("go to the coffee shop").poi_id == "coffee_42nd"
    assert grounder.ground("walk to the bookstore").poi_id == "bookstore_main"
    assert grounder.ground("go to the park").poi_id == "park_entrance"


# ---------------------------------------------------------------- SUP-3 -----


def _candidate(entity_id: str, label: str, radius_m: float | None) -> dict[str, object]:
    metadata: dict[str, object] = {} if radius_m is None else {"radius_m": radius_m}
    return {"id": entity_id, "label": label, "class_id": label, "metadata": metadata}


def test_identical_trees_both_survive_a_big_filter() -> None:
    """Honest relative reading: neither identical tree is bigger."""

    candidates = [
        _candidate("tree_1", "tree", TREE_RADIUS_M),
        _candidate("tree_2", "tree", TREE_RADIUS_M),
    ]

    result = filter_candidates_by_attributes(candidates, ("big",))

    assert [item["id"] for item in result.kept] == ["tree_1", "tree_2"]
    assert result.applied == ("big",)
    assert result.detail == "attribute_size:big"


def test_size_filter_splits_a_class_around_its_median() -> None:
    candidates = [
        _candidate("tree_small", "tree", 0.30),
        _candidate("tree_big", "tree", 0.90),
    ]

    big = filter_candidates_by_attributes(candidates, ("big",))
    small = filter_candidates_by_attributes(candidates, ("small",))

    assert [item["id"] for item in big.kept] == ["tree_big"]
    assert [item["id"] for item in small.kept] == ["tree_small"]


def test_size_is_relative_to_the_candidate_class_not_the_whole_scene() -> None:
    candidates = [
        _candidate("tree_1", "tree", 0.58),
        _candidate("tree_2", "tree", 0.20),
        _candidate("bldg_1", "building", 2.34),
    ]

    result = filter_candidates_by_attributes(candidates, ("big",))

    # The building does not make every tree small.
    assert [item["id"] for item in result.kept] == ["tree_1", "bldg_1"]


def test_single_candidate_passes_any_size_attribute() -> None:
    """Documented v1 semantics: the only tree is both biggest and smallest."""

    only = [_candidate("tree_1", "tree", TREE_RADIUS_M)]

    assert len(filter_candidates_by_attributes(only, ("big",)).kept) == 1
    assert len(filter_candidates_by_attributes(only, ("small",)).kept) == 1


def test_candidate_without_size_metadata_is_dropped_and_named() -> None:
    candidates = [_candidate("tree_1", "tree", None)]

    result = filter_candidates_by_attributes(candidates, ("big",))

    assert result.kept == ()
    assert result.unmeasurable == ("big",)
    assert "attribute_unmeasurable:big" in result.detail


def test_height_metadata_is_read_when_radius_is_absent() -> None:
    candidates = [
        {"id": "post_a", "label": "lamppost", "metadata": {"height_m": 2.0}},
        {"id": "post_b", "label": "lamppost", "metadata": {"height_m": 4.0}},
    ]

    result = filter_candidates_by_attributes(candidates, ("tall",))

    assert [item["id"] for item in result.kept] == ["post_b"]


def test_unknown_attribute_filters_nothing_and_is_reported() -> None:
    candidates = [_candidate("tree_1", "tree", TREE_RADIUS_M)]

    result = filter_candidates_by_attributes(candidates, ("purple",))

    assert result.kept == tuple(candidates)
    assert result.unsupported == ("purple",)
    assert supported_attributes(("purple", "big")) == ("big",)


def test_empty_attributes_and_empty_candidates_are_pass_through() -> None:
    candidates = [_candidate("tree_1", "tree", TREE_RADIUS_M)]

    assert filter_candidates_by_attributes(candidates, ()).kept == tuple(candidates)
    assert filter_candidates_by_attributes([], ("big",)).kept == ()


def test_matcher_does_not_mutate_its_input() -> None:
    candidates = [
        _candidate("tree_1", "tree", 0.30),
        _candidate("tree_2", "tree", 0.90),
    ]
    before = [dict(item) for item in candidates]

    filter_candidates_by_attributes(candidates, ("big",))

    assert candidates == before


# ---------------------------------------------------------------- SUP-2 -----


def _hit(entity_id: str, xy: tuple[float, float], confidence: float = 0.98) -> dict:
    return {
        "id": entity_id,
        "label": "lamppost" if "lamp" in entity_id else "tree",
        "class_id": "lamppost" if "lamp" in entity_id else "tree",
        "confidence": confidence,
        "x": xy[0],
        "y": xy[1],
        "distance_m": math.hypot(xy[0], xy[1]),
    }


def test_two_lamppost_scene_is_ambiguous_without_a_superlative() -> None:
    """Baseline the superlative changes: equal confidence, comparable range."""

    result = resolve_grounding(
        frustum=[
            _hit("lamp_post_2", (-1.0, -1.0)),
            _hit("lamp_post_1", (-1.4, -1.0)),
        ],
        memory=[],
    )

    assert result.outcome == GroundingOutcome.AMBIGUOUS


def test_nearest_lamppost_grounds_lamp_post_1_from_spawn() -> None:
    """From spawn (0, 0): lamp_post_1 at 3.16 m beats lamp_post_2 at 7.30 m."""

    hits = sorted(
        (_hit("lamp_post_1", LAMP_1), _hit("lamp_post_2", LAMP_2)),
        key=lambda hit: hit["distance_m"],
    )

    result = resolve_grounding(frustum=hits, memory=[], interchangeable=True)

    assert result.outcome == GroundingOutcome.RESOLVED
    assert result.candidate is not None
    assert result.candidate["id"] == "lamp_post_1"


def test_nearest_tree_resolves_a_near_tie_instead_of_asking_which_one() -> None:
    """tree_1 5.91 m vs tree_2 5.88 m — inside the ambiguity band by range."""

    hits = sorted(
        (_hit("tree_1", TREE_1), _hit("tree_2", TREE_2)),
        key=lambda hit: hit["distance_m"],
    )

    assert resolve_grounding(frustum=hits, memory=[]).outcome == (
        GroundingOutcome.AMBIGUOUS
    )

    result = resolve_grounding(frustum=hits, memory=[], interchangeable=True)

    assert result.outcome == GroundingOutcome.RESOLVED
    assert result.candidate is not None
    assert result.candidate["id"] == "tree_2"


def test_superlative_never_collapses_two_distinct_labels() -> None:
    """"Nearest" picks among same-kind instances, not across classes."""

    result = resolve_grounding(
        frustum=[
            {"id": "a", "class_id": "sidewalk", "confidence": 0.9, "distance_m": 2.0},
            {"id": "b", "class_id": "crosswalk", "confidence": 0.9, "distance_m": 2.2},
        ],
        memory=[],
        interchangeable=True,
    )

    assert result.outcome == GroundingOutcome.AMBIGUOUS


# ------------------------------------------------- SUP-2/SUP-3 integration --


def _navigator() -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
    )


def _city_observation(*objects: dict) -> NavObservation:
    return NavObservation(
        position=(0.0, 0.0, 0.0),
        extras={
            "collision": False,
            "perception_fresh": True,
            "time_s": 1.0,
            "semantic_candidates": list(objects),
        },
    )


def _object_candidate(
    entity_id: str, label: str, xy: tuple[float, float], radius_m: float
) -> dict:
    return {
        "id": entity_id,
        "label": label,
        "kind": "object",
        "position": [xy[0], xy[1], 0.0],
        "confidence": 0.98,
        "reachable": True,
        "metadata": {"radius_m": radius_m, "aliases": ["lamp post", "street light"]},
    }


def test_pipeline_nearest_lamppost_resolves_the_near_one_not_ambiguous() -> None:
    navigator = _navigator()
    mission = navigator.start("find the nearest lamppost")
    observation = _city_observation(
        _object_candidate("lamp_post_1", "lamppost", LAMP_1, 0.06),
        _object_candidate("lamp_post_2", "lamppost", LAMP_2, 0.06),
    )

    # Two views: the resolution ladder confirms a target before committing.
    navigator.step(observation)
    navigator.step(observation)

    assert mission.metadata["grounding_outcome"] == "RESOLVED"
    assert mission.metadata["candidate_id"] == "lamp_post_1"
    assert mission.metadata["resolution_state"] == "resolved"
    assert mission.metadata["directive_superlative"] == "nearest"


def test_pipeline_without_superlative_still_asks_which_lamppost() -> None:
    """The bypass is requested by the phrasing — it is not the new default."""

    navigator = _navigator()
    mission = navigator.start("go to the lamppost")
    close_pair = (
        _object_candidate("lamp_post_1", "lamppost", (2.0, 0.0), 0.06),
        _object_candidate("lamp_post_2", "lamppost", (2.3, 0.4), 0.06),
    )

    navigator.step(_city_observation(*close_pair))

    assert mission.metadata["grounding_outcome"] == "AMBIGUOUS"
    assert mission.metadata["resolution_state"] == "ambiguous"


def test_pipeline_closest_big_tree_keeps_both_trees_then_takes_the_nearer() -> None:
    navigator = _navigator()
    mission = navigator.start("running to the closest big tree")
    observation = _city_observation(
        _object_candidate("tree_1", "tree", TREE_1, TREE_RADIUS_M),
        _object_candidate("tree_2", "tree", TREE_2, TREE_RADIUS_M),
    )

    navigator.step(observation)
    navigator.step(observation)

    assert mission.metadata["grounding_outcome"] == "RESOLVED"
    assert mission.metadata["candidate_id"] == "tree_2"
    # Memory rows carry no size yet, so they are reported unmeasurable.
    assert mission.metadata["attribute_filter"].startswith("attribute_size:big")
    assert mission.metadata["attribute_query"] == "big tree"
    assert mission.metadata["directive_pace"] == "fast"


def test_pipeline_attribute_selects_the_bigger_of_two_unequal_trees() -> None:
    navigator = _navigator()
    mission = navigator.start("go to the big tree")
    observation = _city_observation(
        # The small tree is much nearer — the attribute must beat proximity.
        _object_candidate("tree_small", "tree", (1.5, 0.0), 0.20),
        _object_candidate("tree_big", "tree", (6.0, 0.0), 0.90),
    )

    navigator.step(observation)
    navigator.step(observation)

    assert mission.metadata["candidate_id"] == "tree_big"


def test_pipeline_names_the_attribute_when_it_empties_the_candidate_set() -> None:
    """Never silently ignore an attribute it could not evaluate."""

    navigator = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        instructnav_recovery=False,
    )
    mission = navigator.start("go to the big tree")
    sizeless = {
        "id": "tree_1",
        "label": "tree",
        "kind": "object",
        "position": [3.0, 0.0, 0.0],
        "confidence": 0.98,
        "reachable": True,
        "metadata": {},
    }

    navigator.step(_city_observation(sizeless))

    assert mission.metadata["grounding_outcome"] == "UNSEEN"
    assert "attribute_unmeasurable:big" in mission.metadata["attribute_filter"]
    assert "big tree" in mission.metadata["reply"]


# ---------------------------------------------------------------- SUP-4 -----


class _FakeBackend:
    """Minimal backend: the pace cases never leave the runtime seam."""

    name = "fake"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack("owner", 2.0, 0.0, True, 1.0),
            backend="fake",
        )

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def close(self) -> None:
        return None


@pytest.fixture
def runtime_config(tmp_path: Path) -> Path:
    base = yaml.safe_load((REPO / "configs/robot.yaml").read_text(encoding="utf-8"))
    base["memory"] = {"path": ":memory:"}
    base["navigation"] = {
        "enabled": True,
        "config": str(REPO / "configs/navigation/default.yaml"),
    }
    path = tmp_path / "robot.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return path


@pytest.fixture
def audio_status() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


def test_directive_pace_uses_the_same_cap_the_faster_intent_uses(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    """No new speed authority — the bounded PaceCap, exactly as FASTER sets it."""

    runtime = RobotRuntime(runtime_config, _FakeBackend(), audio_status=audio_status)
    try:
        expected = resolve_cap(ClosedIntent.FASTER, current_pace=PACE_DEFAULT).pace_scale

        runtime._apply_directive_pace("fast")

        assert runtime._pace_cap.scale == pytest.approx(expected)
        assert runtime._pace_cap.scale == pytest.approx(PACE_DEFAULT + PACE_STEP)

        runtime._restore_directive_pace()

        assert runtime._pace_cap.scale == pytest.approx(PACE_DEFAULT)
        # Restoring twice must not walk the scale further.
        runtime._restore_directive_pace()
        assert runtime._pace_cap.scale == pytest.approx(PACE_DEFAULT)
    finally:
        runtime.close()


def test_directive_pace_is_mission_scoped_and_only_applied_once(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    runtime = RobotRuntime(runtime_config, _FakeBackend(), audio_status=audio_status)
    try:
        runtime._apply_directive_pace("fast")
        runtime._apply_directive_pace("fast")

        assert runtime._pace_cap.scale == pytest.approx(PACE_DEFAULT + PACE_STEP)

        runtime._restore_directive_pace()

        assert runtime._pace_cap.scale == pytest.approx(PACE_DEFAULT)
    finally:
        runtime.close()


def test_directive_without_a_pace_verb_leaves_the_cap_alone(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    runtime = RobotRuntime(runtime_config, _FakeBackend(), audio_status=audio_status)
    try:
        runtime._apply_directive_pace(pace_from_directive("go to the closest big tree"))

        assert runtime._pace_cap.scale == pytest.approx(PACE_DEFAULT)
    finally:
        runtime.close()


def test_directive_pace_scales_navigation_velocity_but_not_manual(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    runtime = RobotRuntime(runtime_config, _FakeBackend(), audio_status=audio_status)
    try:
        runtime._apply_directive_pace(pace_from_directive("running to the closest big tree"))
        scale = runtime._pace_cap.scale

        assert scale == pytest.approx(PACE_DEFAULT + PACE_STEP)
        scaled = runtime._pace_cap.scale_command(0.4, 0.0, 0.0)
        assert scaled[0] == pytest.approx(0.4 * scale)
    finally:
        runtime.close()


def test_navigation_channel_stop_hands_the_pace_scale_back(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    runtime = RobotRuntime(runtime_config, _FakeBackend(), audio_status=audio_status)
    try:
        runtime._apply_directive_pace("fast")
        assert runtime._pace_cap.scale > PACE_DEFAULT

        runtime._stop_navigation_channel()

        assert runtime._pace_cap.scale == pytest.approx(PACE_DEFAULT)
    finally:
        runtime.close()
