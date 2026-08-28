"""Card R18 — a dog that knows what it knows. Scene answerability + memory.

WHY THIS FILE EXISTS, in the two failures it pins shut.

**F3, twice, in two different directions.** On 2026-08-20 owner session 1 the
robot said *"I can't actually see anything around me without a camera feed"* —
a lie, from a robot holding a 360-ray LiDAR scan, semantic regions and eight
person tracks. Four hours later, in ``voice_corpus_v1/live_run_1``, the same
question produced no lie and no answer either: two filler beats **3 ms apart**
and then silence, with ``state.realtime.broker.tools`` showing why —

    ["get_status", "recall_memory", "play_gesture", "set_pose",
     "navigate_to", "circle_owner", "follow_owner"]

**not one of which could answer a question about the world.** The scoring
re-cut F3 as a missing-tool defect. This file pins the answer path that closes
it, and pins BOTH honesty directions around it: the robot is never blind, and
the robot never describes anything it would need eyes to know.

**F4, root cause moved.** owner_session_1: *"there's no memory of what I know
about you yet"*, no tool call, against days of ledgered conversation.
live_run_1: ``recall_memory`` fired and the answer was eaten downstream — R19's
defect, fixed there. What R19's own live proof then exposed (its §5.3, scene C)
is that the retrieval underneath was broken too: an exact-substring match over
``realtime_turns()``, which is filtered ``speaker IS NOT NULL`` and therefore
could not see **2,618 of the owner's 2,882 conversation rows**. This file pins
the read that replaces it, and pins the provenance that makes a recalled fact
something the owner can check.

Every store here is a fake — an in-memory :class:`ConversationMemory` the test
fills by hand — so the corpus rows that failed live are answered on every
commit, for free, forever (card item 3).
"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import (
    DynamicAgentTrack,
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SemanticRegionTrack,
    SimObservation,
)
from parcel_robot.memory.conversation import (
    RECALL_MIN_CHARS,
    RECALL_SELF_MARKERS,
    ConversationMemory,
    provenance_phrase,
    recall_named_day,
    recall_tokens,
)
from parcel_robot.models import ToolResult, VelocityCommand
from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.lane import RealtimeLane
from parcel_robot.realtime.prompting import (
    MAX_SCENE_LINES,
    SCENE_BLOCK_HEADER,
    DeveloperContext,
    DeveloperFlags,
    render_developer_instruction,
)
from parcel_robot.realtime.tool_broker import (
    ANSWER_RESULT_KEY,
    STATUS_OK,
    TOOL_GET_STATUS,
    TOOL_RECALL_MEMORY,
    RealtimeToolBroker,
    ToolDoors,
    build_tool_specs,
)
from parcel_robot.runtime import (
    SCENE_HONESTY_NOTE,
    SCENE_NO_OBSERVATION,
    SCENE_PERSON,
    SCENE_SENSORS,
    SCENE_UNLABELLED,
    RobotRuntime,
    scene_bearing_words,
    scene_fact_lines,
    scene_report,
)

REPO = Path(__file__).resolve().parents[1]

#: The corpus rows this card is measured against. Card item 3: scene (27–29)
#: and memory (30–31) flip from expected-FAIL to expected-PASS.
CORPUS_TSV = REPO / "evals" / "20260820" / "voice_corpus_v1" / "queries.tsv"
SCENE_IDS = ("27", "28", "29")
MEMORY_IDS = ("30", "31")

#: Vocabulary a robot without eyes may never use about its surroundings. The
#: list is short and every entry is a word owner_session_1's F3 either used or
#: implied — this is the sentence that has to stay impossible:
#: "I can't actually see anything around me without a camera feed."
VISION_WORDS = (
    "camera", "see ", "seeing", "look ", "looks", "looking", "colour", "color",
    "red", "blue", "green ", "bright", "dark ", "image", "photo", "picture",
    "visible", "eyes",
)


# ============================================================== the corpus pin
def _corpus_rows() -> dict[str, dict[str, str]]:
    with CORPUS_TSV.open(encoding="utf-8") as handle:
        return {row["id"]: row for row in csv.DictReader(handle, delimiter="\t")}


def test_the_corpus_rows_this_card_answers_are_the_rows_it_says_they_are() -> None:
    """The offline pins quote the corpus; this stops the two drifting apart.

    Without it, a corpus edit could retire the very question this file claims to
    have fixed and every test below would stay green while answering nothing
    anybody asks.
    """

    rows = _corpus_rows()
    assert [rows[i]["category"] for i in SCENE_IDS] == ["scene"] * 3
    assert [rows[i]["category"] for i in MEMORY_IDS] == ["memory"] * 2
    assert rows["27"]["query"] == "What do you see around you?"
    assert rows["28"]["query"] == "Is anyone near you?"
    assert rows["29"]["query"] == "What's the closest thing to you?"
    assert rows["30"]["query"] == "What do you remember about me?"
    assert rows["31"]["query"] == "What did we talk about yesterday?"
    assert "REGRESSION F3" in rows["27"]["expected"]
    assert "REGRESSION F4" in rows["30"]["expected"]


# ==================================================================== the scene
def _observation(**overrides: object) -> SimObservation:
    """The live_run_1 snapshot, rebuilt: this is what the robot was holding.

    ``nearest_person`` is the run's own row verbatim
    (``{"id": "ped-6", "distance_m": 1.7268, "bearing_rad": 0.5547}``) and
    ``obstacle_distance_m`` is its ``1.4276`` — the fields that were live in
    state at the moment the robot answered "Is anyone near you?" with silence.
    """

    base: dict[str, object] = {
        "timestamp": 1.0,
        "robot": RobotPose(x=0.0, y=0.0, yaw=0.0),
        "owner": OwnerTrack(visible=True, confidence=0.9),
        "nearest_obstacle_m": 1.4276,
        "nearest_person_m": 1.7268,
        "nearest_person_bearing_rad": 0.5547,
        "nearest_person_id": "ped-6",
        "dynamic_agents": (
            DynamicAgentTrack("ped-6", "person", 1.5, 0.9, 0.0, 0.0, 0.3),
            DynamicAgentTrack("ped-7", "person", -3.0, 1.0, 0.0, 0.0, 0.3),
            DynamicAgentTrack("car-1", "vehicle", 8.0, 0.0, 0.0, 0.0, 1.0),
        ),
        "semantic_regions": (
            SemanticRegionTrack(
                "r1", "sidewalk", ((1.0, -1.0), (3.0, -1.0), (3.0, 1.0), (1.0, 1.0)), 0.9
            ),
            SemanticRegionTrack(
                "r2", "grass", ((-6.0, 2.0), (-4.0, 2.0), (-4.0, 4.0), (-6.0, 4.0)), 0.8
            ),
        ),
        "semantic_objects": (SemanticObjectTrack("o1", "bench", (0.5, 3.0, 0.0), 0.7),),
        "backend": "mujoco",
    }
    base.update(overrides)
    return SimObservation(**base)  # type: ignore[arg-type]


def test_q27_what_do_you_see_around_you_has_an_answer_at_all() -> None:
    """F3's root cause, inverted: the facts exist, so a fact block exists.

    The claim is deliberately weak and deliberately load-bearing — live_run_1
    produced NO answer, not a wrong one, so the first thing to pin is that an
    answer is now constructible from the state the robot already holds.
    """

    report = scene_report(_observation())
    assert report["observed"] is True
    summary = str(report["summary"])
    assert summary and summary != SCENE_NO_OBSERVATION
    labels = [str(thing["label"]) for thing in report["things"]]
    assert "sidewalk" in labels and "bench" in labels


def test_q28_is_anyone_near_you_is_answered_from_the_person_tracks() -> None:
    """The sharpest illustration in the scoring, made into a test.

    The robot had told this owner three times that somebody was in the way
    (mission log ids 4, 9, 14) and then could not answer "is anyone near you"
    sixty seconds later: person data reached the mission-log narrator and never
    the conversation lane. It reaches it here.
    """

    people = scene_report(_observation())["people"]
    assert people["count"] == 2
    assert people["nearest"]["distance_m"] == pytest.approx(1.7, abs=0.01)
    assert people["nearest"]["direction"] == "ahead on my left"


def test_q29_what_is_the_closest_thing_to_you_gets_one_field_not_three() -> None:
    """SEED: leaving q29 to be inferred from ``things``/``people``/``clearance``.

    The live proof is the reason this is a field. Given the three separately,
    ``gpt-realtime-2.1-mini`` answered "the closest thing is zero meters behind
    me" off the person track while the LiDAR clearance was 1.1 m. Three numbers
    to choose between is a choice; one field is an answer.
    """

    report = scene_report(_observation())
    assert report["clearance_m"] == pytest.approx(1.4, abs=0.01)
    assert "nearest obstacle 1.4 m" in scene_fact_lines(report)
    closest = report["closest"]
    assert closest["distance_m"] == pytest.approx(1.4, abs=0.01)
    assert closest["what"] == SCENE_UNLABELLED
    assert "closest of all" in " ".join(scene_fact_lines(report))


def test_the_closest_thing_is_named_by_its_kind_and_never_given_a_class() -> None:
    """A LiDAR return with no semantic label is said to have no semantic label."""

    labelled = scene_report(
        _observation(nearest_obstacle_m=None, nearest_person_m=None,
                     nearest_person_bearing_rad=None, nearest_person_id=None)
    )
    assert labelled["closest"]["what"] == "sidewalk"

    person = scene_report(_observation(nearest_obstacle_m=None))
    assert person["closest"]["what"] == SCENE_PERSON

    unlabelled = scene_report(_observation(nearest_obstacle_m=0.4))
    assert unlabelled["closest"]["what"] == SCENE_UNLABELLED
    assert "object" not in SCENE_UNLABELLED


def test_a_distance_is_rounded_before_the_model_ever_sees_it() -> None:
    """SEED: two-decimal distances, which the live tier renders as "zero meters".

    Handed ``"distance_m": 0.48`` the mini tier said **"zero meters straight
    ahead"**. One decimal is also exactly what the fact lines render, so the
    structured field and the sentence cannot disagree.
    """

    report = scene_report(_observation(nearest_person_m=0.48))
    assert report["people"]["nearest"]["distance_m"] == 0.5
    assert "nearest 0.5 m" in " ".join(scene_fact_lines(report))


def test_only_a_track_perception_calls_a_person_is_counted_as_one() -> None:
    """A seed for counting bodies. The vehicle in the fixture is not a person."""

    report = scene_report(_observation(nearest_person_m=None, nearest_person_bearing_rad=None))
    assert report["people"]["count"] == 2
    assert report["people"]["nearest"] is None


def test_the_scene_block_names_only_labels_perception_is_holding() -> None:
    """SEED: the class-vocabulary fallback.

    ``_realtime_places`` deliberately unions the visible instances with the
    scene's declared CLASS vocabulary, so that "the door" is admitted as a
    navigation goal and allowed to fail honestly at grounding. That union is
    right there and is a fabrication here: "what is around you" answered from a
    class list names things that are not there. Wire that fallback into
    :func:`scene_report` and this test reddens.
    """

    report = scene_report(_observation())
    named = {str(thing["label"]) for thing in report["things"]}
    assert named <= {"sidewalk", "grass", "bench"}
    assert "door" not in named and "crosswalk" not in named


def test_an_empty_world_is_reported_empty_and_not_reported_blind() -> None:
    report = scene_report(
        _observation(
            semantic_regions=(),
            semantic_objects=(),
            dynamic_agents=(),
            nearest_person_m=None,
            nearest_person_bearing_rad=None,
            nearest_person_id=None,
            nearest_obstacle_m=None,
        )
    )
    assert report["observed"] is True
    assert scene_fact_lines(report) == ("nothing labelled within range", "no people tracked")


def test_no_observation_at_all_is_no_reading_and_never_a_blindness_claim() -> None:
    """The other half of F3, and the half owner_session_1 actually got wrong.

    "The robot has no reading yet" and "the robot cannot see" are different
    sentences about different worlds, and only the first one is ever true.
    """

    report = scene_report(None)
    assert report["observed"] is False
    assert report["summary"] == SCENE_NO_OBSERVATION
    assert "cannot" not in SCENE_NO_OBSERVATION and "can't" not in SCENE_NO_OBSERVATION
    assert "camera" not in SCENE_NO_OBSERVATION


def test_no_part_of_the_scene_answer_claims_eyesight() -> None:
    """SEED: any wording drift toward vision, anywhere in the block.

    Checked over the whole rendered result rather than over one field, because
    the model reads the whole result and will narrate whatever is in it.
    """

    blob = json.dumps(scene_report(_observation())).lower()
    # The honesty note names the forbidden words in order to forbid them; the
    # rest of the block may not contain any of them.
    body = blob.replace(SCENE_HONESTY_NOTE.lower(), "")
    for word in VISION_WORDS:
        assert word.strip() not in body, word


def test_both_arms_of_the_report_return_the_same_keys() -> None:
    """SEED: a no-observation result that is a different SHAPE, not just emptier.

    A reader that has checked ``observed`` and a reader that has not must both
    get an answer rather than one of them getting a ``KeyError``.
    """

    assert set(scene_report(None)) == set(scene_report(_observation()))
    assert scene_report(None)["closest"] is None


def test_the_result_says_what_produced_it_every_time() -> None:
    for report in (scene_report(_observation()), scene_report(None)):
        assert report["sensors"] == list(SCENE_SENSORS)
        assert report["note"] == SCENE_HONESTY_NOTE
        assert "not from a camera" in str(report["note"])
        assert "no eyes" in str(report["note"])


@pytest.mark.parametrize(
    ("degrees", "words"),
    [
        (0, "straight ahead"),
        (20, "straight ahead"),
        (45, "ahead on my left"),
        (-45, "ahead on my right"),
        (90, "on my left"),
        (-90, "on my right"),
        (140, "behind me on my left"),
        (-140, "behind me on my right"),
        (180, "behind me"),
        (-180, "behind me"),
        # Wrapping: 250° is -110°, i.e. the robot's right, and -250° is +110°.
        (250, "on my right"),
        (-250, "on my left"),
    ],
)
def test_the_bearing_table_is_a_stated_table(degrees: float, words: str) -> None:
    assert scene_bearing_words(math.radians(degrees)) == words


def test_the_bearing_words_are_the_robots_frame_and_not_the_owners() -> None:
    """A companion that says "on your left" while meaning its own has misled."""

    for degrees in (30, 90, 150, -30, -90, -150):
        assert "your" not in scene_bearing_words(math.radians(degrees))
        assert "my" in scene_bearing_words(math.radians(degrees))


def test_a_repeated_label_is_named_once_at_its_nearest_instance() -> None:
    report = scene_report(
        _observation(
            semantic_regions=(
                SemanticRegionTrack("a", "sidewalk", ((5.0, 0.0), (6.0, 0.0), (6.0, 1.0)), 0.9),
                SemanticRegionTrack("b", "sidewalk", ((1.0, 0.0), (2.0, 0.0), (2.0, 1.0)), 0.9),
            ),
            semantic_objects=(),
        )
    )
    labels = [str(thing["label"]) for thing in report["things"]]
    assert labels.count("sidewalk") == 1
    assert float(report["things"][0]["distance_m"]) < 3.0


def test_a_bearingless_person_gets_a_distance_and_no_direction() -> None:
    report = scene_report(_observation(nearest_person_bearing_rad=None))
    assert report["people"]["nearest"]["direction"] == ""
    assert "nearest 1.7 m" in " ".join(scene_fact_lines(report))


# ============================================ the scene reaches the tool answer
class _Doors:
    """Fake runtime doors. Only the two read-only tools are wired."""

    def __init__(self, status: dict[str, object], recall: str = "") -> None:
        self._status = status
        self._recall = recall
        self.notes: list[str] = []

    def build(self) -> ToolDoors:
        return ToolDoors(
            validate=lambda call: ToolResult(name=call.name, accepted=True, message="ok"),
            status=lambda: self._status,
            recall=lambda query: self._recall,
            gesture=lambda name, intensity: "Accepted",
            pose=lambda name: "Accepted",
            navigate=lambda place, relation: "Accepted",
            note=self.notes.append,
        )


def _status_with_scene() -> dict[str, object]:
    return {"battery_percent": 90.0, "scene": scene_report(_observation())}


def test_get_status_carries_the_scene_so_the_question_has_a_tool_answer() -> None:
    """Card item 1(a). The answer travels on the tool the model already has.

    Deliberately NOT an eighth tool: "how are you" and "what is around you" are
    the same read of the same runtime, and one tool that answers both is one
    fewer thing for the model to choose wrong.
    """

    broker = RealtimeToolBroker(_Doors(_status_with_scene()).build())
    result = json.loads(broker.handle(name=TOOL_GET_STATUS, call_id="c1", arguments="{}"))
    assert result["status"] == STATUS_OK
    assert result["state"]["scene"]["observed"] is True
    assert result["state"]["scene"]["people"]["count"] == 2


def test_the_scene_answer_is_stamped_unsuppressible_by_the_broker() -> None:
    """R19's ``{"answer": true}`` is what keeps this from being eaten again.

    live_run_1's dominant defect was silence, not error: ``get_status`` fetched
    90% battery and the figure was never spoken. A scene block riding the same
    tool would have been eaten the same way, so the stamp is asserted here as a
    property of THIS card's answer and not only of R19's.
    """

    broker = RealtimeToolBroker(_Doors(_status_with_scene()).build())
    result = json.loads(broker.handle(name=TOOL_GET_STATUS, call_id="c1", arguments="{}"))
    assert result[ANSWER_RESULT_KEY] is True


def _lane() -> RealtimeLane:
    return RealtimeLane(
        config=RealtimeConfig(enabled=True, source="test"),
        instructions="be a good dog",
        transport_factory=lambda: None,
        sink=None,
        # The scene answer rides ``get_status``. Naming it a RECEIPT tool is the
        # strongest possible adversary for the claim below.
        receipt_tools=(TOOL_GET_STATUS, TOOL_RECALL_MEMORY, "navigate_to"),
    )


def test_a_scene_answer_is_never_suppressed_even_named_as_a_receipt_tool() -> None:
    """SEED: the blindness/silence path, pinned at the lane.

    Card DoD: *"blindness claim returns with tool present ⇒ at minimum the
    tool-answer path pinned"*. This is that pin. The lane is constructed with
    ``get_status`` deliberately listed as a receipt tool and the model given a
    fully substantive announcement — the exact configuration under which R6's
    rule would buy silence — and the beat is still owed.
    """

    lane = _lane()
    lane._spoke_this_response = True
    lane._response_speech = ["Okay, let's head over to the sidewalk."]
    output = json.dumps(
        {"status": STATUS_OK, "tool": TOOL_GET_STATUS, ANSWER_RESULT_KEY: True,
         "state": {"scene": scene_report(_observation())}}
    )
    assert lane._beat_reason(name=TOOL_GET_STATUS, output=output) is not None


def test_the_get_status_description_is_what_routes_a_scene_question_to_it() -> None:
    """SEED: the description reverting to "battery, emergency stop".

    F3 is a routing failure before it is anything else — the model never called
    a tool because nothing in the surface said a tool could answer. The two
    honesty directions are asserted in the same text: never blind, never eyes.
    """

    spec = next(s for s in build_tool_specs() if s["name"] == TOOL_GET_STATUS)
    description = str(spec["description"]).lower()
    # The routing half — one clause per corpus question that failed.
    for phrase in ("what is around you", "whether anyone is nearby", "the closest thing"):
        assert phrase in description, phrase
    # The honesty halves, in both directions, in the text the model reads when
    # it decides whether it is able to answer at all.
    assert "must never say you cannot sense anything" in description
    assert "no camera" in description
    assert "never describe colours" in description


def test_the_recall_description_asks_for_the_provenance_back() -> None:
    spec = next(s for s in build_tool_specs() if s["name"] == TOOL_RECALL_MEMORY)
    description = str(spec["description"]).lower()
    assert "when it was said" in description
    assert "never say you have" in description


# ======================================================== the scene reaches DI
def test_the_di_carries_the_scene_block_after_the_history_block() -> None:
    flags = DeveloperFlags(
        location="sidewalk",
        local_time="2026-08-20 14:27",
        part_of_day="afternoon",
        owner_name="Jae",
        history_digest=("they said: go to the bench",),
        scene=("sidewalk 2.0 m straight ahead", "2 people tracked, nearest 1.7 m ahead on my left"),
    )
    text = render_developer_instruction(flags).text
    assert SCENE_BLOCK_HEADER in text
    assert text.index("What you last talked about:") < text.index(SCENE_BLOCK_HEADER)
    assert '- "sidewalk 2.0 m straight ahead"' in text


def test_the_di_scene_header_admits_that_it_is_a_snapshot() -> None:
    """The staleness caveat is the price of putting perception in the DI at all.

    The DI is rendered at session boundaries and never mid-session, so without
    this sentence a model could report a ten-minute-old world as the present.
    """

    assert "when this session opened" in SCENE_BLOCK_HEADER
    assert "get_status" in SCENE_BLOCK_HEADER
    assert "no camera" in SCENE_BLOCK_HEADER.lower()


def test_an_empty_scene_renders_the_di_exactly_as_it_rendered_before_this_card() -> None:
    """SEED: a block that renders when there is nothing to say.

    This is also the whole justification for not bumping ``DI_VERSION``: every
    flag set that existed before R18 has an empty ``scene``, so every one of
    them renders the same bytes it always did — which is what keeps the 25
    sealed corpus fixtures verifiable.
    """

    base = DeveloperFlags(location="sidewalk", local_time="2026-08-20 14:27", owner_name="Jae")
    with_empty = DeveloperFlags(
        location="sidewalk", local_time="2026-08-20 14:27", owner_name="Jae", scene=()
    )
    assert render_developer_instruction(base).text == render_developer_instruction(with_empty).text
    assert SCENE_BLOCK_HEADER not in render_developer_instruction(base).text


def test_a_scene_provider_that_fails_renders_no_block_rather_than_a_guess() -> None:
    def _broken() -> list[str]:
        raise RuntimeError("perception unavailable")

    flags = DeveloperContext(
        clock=lambda: datetime(2026, 8, 20, 14, 27),  # noqa: DTZ001 - naive, like the DI's own clock
        scene=_broken,
    ).flags()
    assert flags.scene == ()
    assert SCENE_BLOCK_HEADER not in render_developer_instruction(flags).text


def test_the_scene_block_is_bounded() -> None:
    lines = [f"thing-{n} 1.0 m straight ahead" for n in range(20)]
    flags = DeveloperContext(
        clock=lambda: datetime(2026, 8, 20, 14, 27),  # noqa: DTZ001 - naive, like the DI's own clock
        scene=lambda: lines,
    ).flags()
    assert len(flags.scene) == MAX_SCENE_LINES


def test_the_flags_round_trip_through_a_fixture_with_the_scene_intact() -> None:
    flags = DeveloperFlags(scene=("sidewalk 2.0 m straight ahead",))
    assert DeveloperFlags.from_mapping(flags.as_dict()) == flags


# ============================================================ the runtime wiring
class _Backend:
    name = "test"

    def __init__(self) -> None:
        self.observation = _observation()

    def observe(self) -> SimObservation:
        return self.observation

    def move(self, command: VelocityCommand) -> None:
        del command

    def send_velocity(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def close(self) -> None:
        return None


@pytest.fixture()
def runtime(tmp_path: Path):
    config = tmp_path / "robot-r18.yaml"
    config.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: {tmp_path / "r18-memory.sqlite3"}
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    backend = _Backend()
    session = RobotRuntime(
        config,
        backend,
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="deterministic test status",
        ),
    )
    session._observation = backend.observation
    try:
        yield session
    finally:
        session.close()


def test_the_runtime_status_digest_carries_the_scene(runtime: RobotRuntime) -> None:
    digest = runtime._realtime_status_digest()
    assert "scene" in digest, "get_status is the tool that answers a scene question"
    assert digest["scene"]["observed"] is True
    labels = {str(thing["label"]) for thing in digest["scene"]["things"]}
    assert "sidewalk" in labels


def test_the_di_lines_and_the_tool_answer_describe_one_world(runtime: RobotRuntime) -> None:
    """SEED: two renderers drifting apart.

    The DI block and the ``get_status`` answer must not be able to describe the
    surroundings in two vocabularies; they are the same function twice.
    """

    lines = runtime._realtime_scene_lines()
    assert lines == scene_fact_lines(runtime._realtime_status_digest()["scene"])


def test_a_runtime_with_no_observation_yet_offers_no_di_block(runtime: RobotRuntime) -> None:
    runtime._observation = None
    assert runtime._realtime_scene_lines() == ()
    assert runtime._realtime_status_digest()["scene"]["observed"] is False


# ==================================================================== the memory
#: Naive local, deliberately: recall's provenance words are claims about the
#: owner's day, and the rows they are compared against are naive local too.
PINNED_NOW = datetime(2026, 8, 20, 17, 30)  # noqa: DTZ001


def _store(rows: list[tuple[str, str, str | None, str | None, str]]) -> ConversationMemory:
    """An in-memory ledger filled by hand. ``(role, content, speaker, origin, when)``.

    Written through raw SQL on purpose: the point of most of these tests is what
    the LEGACY rows look like — ``speaker`` and ``origin`` NULL, because
    ``ConversationMemory.add`` never set them — and no writer in this repo can
    still produce that shape.
    """

    memory = ConversationMemory(":memory:")
    for role, content, speaker, origin, when in rows:
        memory.connection.execute(
            "INSERT INTO messages(role, content, created_at, speaker, origin) "
            "VALUES (?, ?, ?, ?, ?)",
            (role, content, when, speaker, origin),
        )
    memory.connection.commit()
    return memory


def _utc(local: datetime) -> str:
    """A local instant as the UTC string SQLite would have stamped for it."""

    return (
        local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if local.tzinfo
        else datetime.fromtimestamp(local.timestamp(), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )


def test_recall_reads_both_origins_and_not_just_the_hosted_one() -> None:
    """SEED: the ``speaker IS NOT NULL`` filter, which is THE F4 root cause.

    Measured on the owner's real store on 2026-08-20: 2,618 of 2,882 rows are
    legacy local-origin rows with ``speaker`` NULL. ``realtime_turns()`` — what
    ``_realtime_recall`` used to read — cannot see any of them. Point ``recall``
    back at it and this test reddens on the local row.
    """

    memory = _store(
        [
            ("user", "I always walk by the river on Sundays", None, None,
             _utc(PINNED_NOW - timedelta(days=3))),
            ("user", "the river path is my favourite", "owner", "realtime",
             _utc(PINNED_NOW - timedelta(days=1))),
        ]
    )
    found = [item.text for item in memory.recall("river", now=PINNED_NOW)]
    assert "I always walk by the river on Sundays" in found
    assert "the river path is my favourite" in found


def test_session_bookkeeping_is_never_offered_as_a_memory() -> None:
    memory = _store(
        [
            ("tool", "[session rollover] rt_a -> rt_b", "system", "realtime", _utc(PINNED_NOW)),
            ("user", "the rollover of the year was great", "owner", "realtime", _utc(PINNED_NOW)),
        ]
    )
    found = [item.text for item in memory.recall("rollover", now=PINNED_NOW)]
    assert found == ["the rollover of the year was great"]


def test_every_recalled_memory_carries_when_it_was_said() -> None:
    """SEED: provenance dropped. Card item 2's "from our chat on Tuesday…"."""

    memory = _store(
        [
            ("user", "my favourite spot is the willow by the river", None, None,
             _utc(PINNED_NOW - timedelta(days=1))),
        ]
    )
    (item,) = memory.recall("willow", now=PINNED_NOW)
    assert item.when_phrase == "yesterday"
    assert item.as_sentence() == (
        "yesterday you said: my favourite spot is the willow by the river"
    )


def test_a_row_with_no_usable_instant_is_said_without_a_date_not_with_a_guess() -> None:
    memory = _store([("user", "the willow by the river", None, None, "not a timestamp")])
    (item,) = memory.recall("willow", now=PINNED_NOW)
    assert item.when is None
    assert item.when_phrase == ""
    assert item.as_sentence() == "you said: the willow by the river"


@pytest.mark.parametrize(
    ("days", "phrase"),
    [(0, "earlier today"), (1, "yesterday"), (2, "on Tuesday"), (5, "on Saturday")],
)
def test_the_provenance_phrases_are_a_stated_table(days: int, phrase: str) -> None:
    assert provenance_phrase(PINNED_NOW - timedelta(days=days), PINNED_NOW) == phrase


def test_a_memory_older_than_a_week_is_dated_rather_than_named_by_weekday() -> None:
    assert provenance_phrase(PINNED_NOW - timedelta(days=14), PINNED_NOW) == "on 6 August"


def test_a_row_stamped_in_the_future_gets_no_phrase_rather_than_a_backwards_one() -> None:
    assert provenance_phrase(PINNED_NOW + timedelta(days=2), PINNED_NOW) == ""


def test_q30_what_do_you_remember_about_me_returns_what_the_owner_said() -> None:
    """The F4 regression, offline. Corpus query 30.

    The old read matched the WHOLE question as a substring, so this returned
    nothing for any store that did not literally contain the sentence "what do
    you remember about me". It now returns the turns in which the owner talked
    about themselves, oldest first, each one dated.
    """

    memory = _store(
        [
            ("user", "I'm hungry, take me somewhere I can get food", "owner", "realtime",
             _utc(PINNED_NOW - timedelta(days=2))),
            ("assistant", "I love New York, there's always something happening", "robot",
             "realtime", _utc(PINNED_NOW - timedelta(days=2))),
            ("user", "go to the lamppost", None, None, _utc(PINNED_NOW - timedelta(minutes=5))),
        ]
    )
    found = memory.recall("what do you remember about me", now=PINNED_NOW)
    assert [item.text for item in found] == [
        "I'm hungry, take me somewhere I can get food",
        "go to the lamppost",
    ]
    assert found[0].when_phrase == "on Tuesday"
    assert found[0].score > found[1].score, (
        "a turn where the owner is the subject outranks an order they gave"
    )
    assert all(item.speaker == "owner" for item in found), (
        "the robot's own sentences are not memories OF THE OWNER"
    )


def test_q31_what_did_we_talk_about_yesterday_reads_the_day_not_the_word() -> None:
    """Corpus query 31, and the reason a time word is not a search term.

    Searching the ledger for the literal string "yesterday" is what returned
    nothing for a day with 38 rows in it.
    """

    memory = _store(
        [
            ("user", "we should find the fountain tomorrow", "owner", "realtime",
             _utc(PINNED_NOW - timedelta(days=1, hours=2))),
            ("assistant", "the fountain is a nice walk", "robot", "realtime",
             _utc(PINNED_NOW - timedelta(days=1, hours=2))),
            ("user", "go to the bench right now", "owner", "realtime", _utc(PINNED_NOW)),
        ]
    )
    found = memory.recall("What did we talk about yesterday?", now=PINNED_NOW)
    assert [item.text for item in found] == [
        "we should find the fountain tomorrow",
        "the fountain is a nice walk",
    ]
    assert all(item.when_phrase == "yesterday" for item in found)


def test_a_named_day_bounds_a_keyword_search_too() -> None:
    memory = _store(
        [
            ("user", "the bench was crowded", "owner", "realtime",
             _utc(PINNED_NOW - timedelta(days=1))),
            ("user", "the bench is free now", "owner", "realtime", _utc(PINNED_NOW)),
        ]
    )
    found = memory.recall("bench yesterday", now=PINNED_NOW)
    assert [item.text for item in found] == ["the bench was crowded"]


def test_a_named_day_survives_a_sentence_repeated_on_a_later_day() -> None:
    """SEED: de-duplicating before applying the day window.

    The newest copy of a repeated sentence claims the text, the window then
    discards that copy, and the in-window copy stays suppressed as a duplicate —
    which emptied whole days against the owner's real store, where "go to the
    lamppost" appears fourteen times across three weeks.
    """

    memory = _store(
        [
            ("user", "go to the lamppost please", "owner", "realtime",
             _utc(PINNED_NOW - timedelta(days=1))),
            ("user", "go to the lamppost please", "owner", "realtime", _utc(PINNED_NOW)),
        ]
    )
    found = memory.recall("what did we talk about yesterday", now=PINNED_NOW)
    assert [item.when_phrase for item in found] == ["yesterday"]


@pytest.mark.parametrize(
    ("query", "offset"),
    [("yesterday", 1), ("today", 0), ("what did we do on Wednesday", 1), ("on Sunday", 4)],
)
def test_the_named_day_table_is_a_stated_table(query: str, offset: int) -> None:
    assert recall_named_day(recall_tokens(query), PINNED_NOW) == (
        PINNED_NOW - timedelta(days=offset)
    ).date()


def test_a_query_that_names_no_day_leaves_the_search_unbounded() -> None:
    assert recall_named_day(recall_tokens("the willow by the river"), PINNED_NOW) is None


def test_a_partial_match_is_only_offered_when_nothing_matched_better() -> None:
    """SEED: one shared word dressed as a memory.

    Against the owner's real store "New York" otherwise returns "Emergency stop
    is latched, so I can't take NEW movement commands until it's released."
    """

    memory = _store(
        [
            ("user", "what's your favourite thing about New York", "owner", "realtime",
             _utc(PINNED_NOW - timedelta(hours=1))),
            ("assistant", "I can't take new movement commands while it's latched", "robot",
             "realtime", _utc(PINNED_NOW - timedelta(hours=2))),
        ]
    )
    found = [item.text for item in memory.recall("New York", now=PINNED_NOW)]
    assert found == ["what's your favourite thing about New York"]


def test_the_same_sentence_said_fourteen_times_is_recalled_once() -> None:
    memory = _store(
        [
            ("user", "go to the lamppost", "owner", "realtime",
             _utc(PINNED_NOW - timedelta(minutes=n)))
            for n in range(14)
        ]
    )
    assert len(memory.recall("lamppost", now=PINNED_NOW)) == 1


def test_an_empty_store_recalls_nothing_and_says_so_through_the_broker() -> None:
    memory = _store([])
    assert memory.recall("the willow", now=PINNED_NOW) == []
    broker = RealtimeToolBroker(_Doors({}, recall="").build())
    result = json.loads(
        broker.handle(
            name=TOOL_RECALL_MEMORY, call_id="c1", arguments='{"query": "the willow"}'
        )
    )
    assert result["detail"] == "nothing recorded about that yet"
    assert result[ANSWER_RESULT_KEY] is True


def test_the_stopwords_leave_a_real_search_term_alone() -> None:
    assert recall_tokens("what do you remember about the willow") == ("willow",)
    assert recall_tokens("what do you remember about me") == ()


def test_the_query_the_model_invents_for_a_question_about_the_owner() -> None:
    """SEED: "owner" as a topic word, straight out of the live proof.

    THE MODEL CHOOSES THE QUERY STRING. Asked "What do you remember about me?"
    ``gpt-realtime-2.1-mini`` sent ``recall_memory({"query": "owner"})`` and, on
    the owner's real store, keyword-matched five typed test commands and the
    robot's OWN owner_session_1 sentence — "there's no memory of what I know
    about you yet" — which it then read back out loud as a memory. There is one
    owner and they are the person asking, so that query is self-reference.
    """

    memory = _store(
        [
            ("user", "I love that tie-dye top", "owner", "realtime",
             _utc(PINNED_NOW - timedelta(days=1))),
            ("user", "walk around the owner", None, None, _utc(PINNED_NOW)),
            ("assistant", "there's no memory of what I know about you yet", "robot",
             "realtime", _utc(PINNED_NOW)),
        ]
    )
    for query in ("owner", "user", "what do you remember about me"):
        found = [item.text for item in memory.recall(query, now=PINNED_NOW)]
        assert "there's no memory of what I know about you yet" not in found, query
        assert "I love that tie-dye top" in found, query


def test_me_is_not_a_self_marker_because_it_is_how_orders_are_given() -> None:
    """SEED: "order me a pizza" promoted into "what do you remember about me"."""

    assert "me" not in RECALL_SELF_MARKERS
    assert {"i", "my", "i'm"} <= RECALL_SELF_MARKERS


def test_an_interjection_is_not_offered_as_a_memory() -> None:
    memory = _store(
        [
            ("user", "Thank you.", "owner", "realtime", _utc(PINNED_NOW)),
            ("user", "I like the river path a lot", "owner", "realtime", _utc(PINNED_NOW)),
        ]
    )
    found = [item.text for item in memory.recall("what do you remember about me", now=PINNED_NOW)]
    assert found == ["I like the river path a lot"]
    assert len("Thank you.") < RECALL_MIN_CHARS


# =============================================== reading the owner's own store
def test_a_read_only_store_refuses_every_write_at_the_engine(tmp_path: Path) -> None:
    """SEED: the ``read_only`` flag ignored.

    Card R18's live proof reads the OWNER's conversation database. "Never open
    it for writing" is a promise a script can break silently — this class's own
    constructor creates a table and runs an ``ALTER TABLE`` on the way in — so
    the promise is made executable and then tested. Delete the ``read_only``
    branch and the write below succeeds.
    """

    path = tmp_path / "owner.sqlite3"
    writable = ConversationMemory(path)
    writable.add("user", "I walk by the river most evenings")
    writable.connection.close()

    reader = ConversationMemory(path, read_only=True)
    assert reader.read_only is True
    with pytest.raises(sqlite3.OperationalError):
        reader.add("user", "this must never be written")
    with pytest.raises(sqlite3.OperationalError):
        reader.connection.execute("ALTER TABLE messages ADD COLUMN whatever TEXT")


def test_a_read_only_store_still_answers_the_owners_question(tmp_path: Path) -> None:
    path = tmp_path / "owner.sqlite3"
    writable = ConversationMemory(path)
    writable.add("user", "I walk by the river most evenings")
    writable.connection.close()

    reader = ConversationMemory(path, read_only=True)
    # The only test here that writes through the REAL add() path, so its row
    # carries SQLite's own CURRENT_TIMESTAMP and its recall must be dated by the
    # real clock too. Recalling it against the fixed PINNED_NOW made the row look
    # future-stamped the instant the calendar passed that pin — and
    # provenance_phrase rightly refuses to date a future row — so this assertion
    # began failing every run after 2026-08-20 and would have failed forever.
    found = reader.recall("river", now=datetime.now())  # noqa: DTZ005
    assert [item.text for item in found] == ["I walk by the river most evenings"]
    assert found[0].when_phrase, "a real store's rows are dated"


def test_the_read_only_store_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    import hashlib

    path = tmp_path / "owner.sqlite3"
    writable = ConversationMemory(path)
    writable.add("user", "I walk by the river most evenings")
    writable.connection.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    reader = ConversationMemory(path, read_only=True)
    reader.recall("river", now=PINNED_NOW)
    reader.conversation_turns()
    reader.connection.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
