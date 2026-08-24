"""Card R21: safety events don't evaporate.

THE INCIDENT THIS FILE EXISTS FOR
---------------------------------
``evals/20260820/voice_corpus_v1/live_run_1``, scoring section (a). The owner
latched the emergency stop at 14:28:19.438 by saying the phrase eight words deep
into a rambling sentence. The scorer could not PROVE that, because the retained
100-slot event ring began at **14:28:33.544** — fourteen seconds AFTER the latch.
Attribution was rebuilt from four inferences (a window bound, a grammar rule, a
silence signature and a truncation signature) and still could not exclude an
accidental Space-key latch from the browser panel. Section (b) is the other half:
the owner then spoke eighteen more turns over **84.0 seconds** to a robot that
had already stopped, and there is no sign they ever knew.

That is the exact failure class card R4-lite fixed for MISSION terminals
(``test_mission_log.py``), applied to the events that matter more. So this file
pins the same three properties that file pins, plus the two that are specific to
safety:

1. **The record survives.** A latch, a release and a refusal live in a ring the
   event deque cannot evict, and the chatty kind (refusals) can never push out
   the lifecycle kind (latches and releases).
2. **The record is attributable.** Every latch names the DOOR it came through,
   and a spoken one carries the owner's utterance verbatim — which is precisely
   what live_run_1 could not do.
3. **The latch is audible while it lasts.** Not only on the rising edge: a
   status question asked eighty seconds in is answered with the latch, its age
   and the fact that it has to be released.
4. **The substring property is deliberate** (section a, "two matcher
   observations worth pinning"): the spoken phrase latches at ANY position in an
   utterance while bare "stop" stays whole-utterance exact. That asymmetry is
   what made the live latch fire and it must not be "fixed" into an anchored
   match by someone who reads it as a bug.

WHAT THIS FILE DOES NOT DO
--------------------------
It does not change, widen, narrow or re-test the matcher. ``test_realtime_
ingress.py`` owns the grammar; the q34 widening question ("Dye. Stop.") is
owner-gated and untouched. Section 4 below READS the shipped matcher through its
own exported predicate and pins the POSITION property as a property, nothing more.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV, WhispererConfig
from parcel_robot.realtime.ingress import (
    SPOKEN_EMERGENCY_PHRASE,
    matches_spoken_emergency,
)
from parcel_robot.realtime.ingress import scan as scan_realtime_transcript
from parcel_robot.realtime.whisperer import (
    ESTOP_SOURCE_PHRASES,
    KIND_EMERGENCY_STOP,
    STATE_DIGEST_VERSION,
    StateDigest,
    Whisperer,
)
from parcel_robot.runtime import (
    SAFETY_LOG_LATCHED,
    SAFETY_LOG_MAX,
    SAFETY_LOG_REJECTED,
    SAFETY_LOG_REJECTED_MAX,
    SAFETY_LOG_RELEASED,
    SAFETY_REJECT_MIN_INTERVAL_S,
    SAFETY_RULE_SPOKEN,
    SAFETY_SOURCE_PANEL,
    SAFETY_SOURCE_SIMULATOR,
    SAFETY_SOURCE_VOICE,
    RobotRuntime,
)

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r21-safety-log"

#: The owner's real utterance, verbatim from ``live_run_1/ledger.json`` id=2803.
#: The stop phrase sits EIGHT WORDS DEEP in it, which is the whole point — but
#: the phrase itself is never spelled here. It is spliced in from the ingress's
#: single definition, because a test is as good a place as any to grow the
#: fourth copy of a stop grammar and U33 is what that costs.
LIVE_RUN_1_UTTERANCE = (
    "Alright, let's go home and find the oh "
    + " ".join([SPOKEN_EMERGENCY_PHRASE] * 4)
)


# ------------------------------------------------------------------ fixtures
class _Backend:
    name = BACKEND_NAME

    def __init__(self) -> None:
        self.moves: list[VelocityCommand] = []
        self.stops = 0
        self.emergencies = 0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        self.stops += 1

    def emergency_stop(self) -> None:
        self.emergencies += 1

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del transcript, tools, context
        return AgentDecision("Understood.")


class _Clock:
    """An injected monotonic seam for the refusal coalescer."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    path = tmp_path / "r21.yaml"
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
duplex:
  enabled: true
  logging: true
  log_dir: {tmp_path / "duplex-logs"}
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    built = RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r21 safety-log fixture",
        ),
    )
    try:
        yield built
    finally:
        built.close()


def _rows(runtime: RobotRuntime, kind: str = "") -> list[dict[str, object]]:
    return [row for row in runtime.safety_log if not kind or row["kind"] == kind]


# ======================================================= 1. the record survives
def test_the_latching_utterance_is_still_there_after_the_event_deque_has_rolled(
    runtime: RobotRuntime,
) -> None:
    """THE seed catcher for "the safety ring is evicted", and the live incident.

    This is live_run_1 section (a) reproduced end to end: latch by voice, then
    let the runtime be as chatty as it was that afternoon. The 100-slot event
    deque loses the latch — asserted here, so the test cannot pass by the deque
    quietly having grown — and the ring still names the utterance that did it.
    """

    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)
    for index in range(140):
        runtime._emit("perception", f"chatter {index}", "info")

    events = runtime.snapshot()["events"]
    assert not [
        event
        for event in events  # type: ignore[union-attr]
        if "Emergency stop latched" in str(event.get("text", ""))
    ], "the event deque kept the latch, so this test proves nothing about the ring"

    latches = _rows(runtime, SAFETY_LOG_LATCHED)
    assert len(latches) == 1
    assert latches[0]["phrase"] == LIVE_RUN_1_UTTERANCE
    assert latches[0]["source"] == SAFETY_SOURCE_VOICE


def test_a_flood_of_refusals_can_never_push_out_the_latch_that_causes_them(
    runtime: RobotRuntime,
) -> None:
    """THE seed catcher for "the ring is folded into one bucket".

    A latched robot whose model keeps calling motion tools generates refusals
    without limit. If those shared the ring evenly, the row explaining WHY
    everything is being refused would be the first thing to go — the original
    bug wearing a new hat.
    """

    clock = _Clock()
    runtime._safety_clock = clock
    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)
    for index in range(SAFETY_LOG_MAX * 4):
        clock.advance(SAFETY_REJECT_MIN_INTERVAL_S + 1.0)
        runtime._note_safety_rejection(f"door {index}", "motion is disabled")

    assert len(_rows(runtime, SAFETY_LOG_REJECTED)) <= SAFETY_LOG_REJECTED_MAX
    latches = _rows(runtime, SAFETY_LOG_LATCHED)
    assert len(latches) == 1, "the latch was evicted by its own consequences"
    assert latches[0]["phrase"] == LIVE_RUN_1_UTTERANCE


def test_the_safety_log_reaches_the_snapshot(runtime: RobotRuntime) -> None:
    """A ring the panel cannot read is a ring nobody reads.

    ``web_panel.py`` passes ``runtime.snapshot()`` through verbatim, so a
    top-level key is the whole of the wiring — and its absence is silent.
    """

    snapshot = runtime.snapshot()
    assert "safety_log" in snapshot
    assert snapshot["safety_log"] == []

    runtime.action("emergency_stop")
    rows = runtime.snapshot()["safety_log"]
    assert [row["kind"] for row in rows] == [SAFETY_LOG_LATCHED]  # type: ignore[union-attr]
    assert json.dumps(rows), "every row must survive the JSON the panel is served"


def test_the_ring_hands_out_copies_not_its_own_rows(runtime: RobotRuntime) -> None:
    """A reader that can mutate the record is not a record.

    The snapshot goes to a browser, an eval harness and a status doc; one of
    them editing a row in place would corrupt the evidence for the others.
    """

    runtime.action("emergency_stop")
    first = runtime.safety_log
    first[0]["text"] = "tampered"
    assert runtime.safety_log[0]["text"] != "tampered"


# ================================================== 2. the record is attributable
def test_a_spoken_latch_carries_the_owners_words_verbatim(runtime: RobotRuntime) -> None:
    """THE seed catcher for "the source is dropped".

    Not the normalized text and not a summary: the sentence as the ledger keeps
    it, so a ring row and a conversation row can be lined up word for word. This
    is the single line that would have made live_run_1 §a unnecessary.
    """

    runtime.submit_realtime_transcript("  Alright,   let's go home and " + SPOKEN_EMERGENCY_PHRASE + "! ")
    row = _rows(runtime, SAFETY_LOG_LATCHED)[0]
    assert row["source"] == SAFETY_SOURCE_VOICE
    assert row["rule"] == SAFETY_RULE_SPOKEN
    # Whitespace collapsed exactly as the ledger collapses it; punctuation kept.
    assert row["phrase"] == "Alright, let's go home and " + SPOKEN_EMERGENCY_PHRASE + "!"
    assert row["phrase"] in str(row["text"]), "the readable line must carry the words too"


def test_a_keyed_latch_and_a_spoken_latch_are_different_rows(runtime: RobotRuntime) -> None:
    """THE hypothesis live_run_1 could not exclude, excluded by construction.

    Section (a): "Nothing in the ledger, events or state distinguishes a spoken
    latch from a keyed one." Now the ring does, in one field, without inference.
    """

    runtime.action("emergency_stop")
    runtime.action("clear_emergency_stop")
    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)

    latches = _rows(runtime, SAFETY_LOG_LATCHED)
    assert [row["source"] for row in latches] == [SAFETY_SOURCE_PANEL, SAFETY_SOURCE_VOICE]
    assert latches[0]["phrase"] == "", "the panel door has no utterance to claim"
    assert latches[1]["phrase"] == LIVE_RUN_1_UTTERANCE


def test_an_adopted_simulator_latch_is_not_reported_as_the_owners(
    runtime: RobotRuntime,
) -> None:
    """The over-correction guard: not every latch is a person.

    A ring that labelled everything ``voice`` would answer live_run_1's question
    wrongly and confidently, which is worse than the silence it replaces.
    """

    runtime._log_safety_latch(source=SAFETY_SOURCE_SIMULATOR, already_latched=False)
    row = _rows(runtime, SAFETY_LOG_LATCHED)[0]
    assert row["source"] == SAFETY_SOURCE_SIMULATOR
    assert row["phrase"] == ""
    assert "simulator" in str(row["text"]).lower()


def test_one_breath_of_repeated_phrases_is_one_latch_with_its_first_words_kept(
    runtime: RobotRuntime,
) -> None:
    """Corpus queries 32 and 33, merged into a single breath by a real owner.

    A frightened person repeats themselves. The ring folds the repeat into a
    count rather than appending rows — and, critically, keeps the FIRST row's
    words, because those are the ones that actually latched the robot.
    """

    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)
    runtime.submit_realtime_transcript(SPOKEN_EMERGENCY_PHRASE.capitalize() + "!")
    runtime.submit_realtime_transcript(SPOKEN_EMERGENCY_PHRASE.capitalize() + "!")

    latches = _rows(runtime, SAFETY_LOG_LATCHED)
    assert len(latches) == 1, "three utterances, one latch"
    assert latches[0]["count"] == 3
    assert latches[0]["phrase"] == LIVE_RUN_1_UTTERANCE


def test_a_second_latch_after_a_release_is_its_own_row(runtime: RobotRuntime) -> None:
    """The folding above must not swallow a genuinely new latch.

    Latch, release, latch again is two incidents. Folding them would hide the
    second one behind the first one's timestamp.
    """

    runtime.submit_realtime_transcript(SPOKEN_EMERGENCY_PHRASE.capitalize() + ".")
    runtime.action("clear_emergency_stop")
    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)

    latches = _rows(runtime, SAFETY_LOG_LATCHED)
    assert len(latches) == 2
    assert latches[1]["phrase"] == LIVE_RUN_1_UTTERANCE


def test_the_release_is_recorded_with_how_long_the_robot_was_stopped(
    runtime: RobotRuntime,
) -> None:
    """live_run_1's latch was NEVER released — still engaged 350 s later.

    A ring that logs only latches cannot tell "still stopped" from "stopped and
    let go" once the rows scroll, which is the question an owner reading the
    panel afterwards actually has.
    """

    clock = _Clock()
    runtime._safety_clock = clock
    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)
    clock.advance(84.0)
    runtime.action("clear_emergency_stop")

    released = _rows(runtime, SAFETY_LOG_RELEASED)
    assert len(released) == 1
    assert released[0]["source"] == SAFETY_SOURCE_PANEL
    assert "84.0 s" in str(released[0]["text"])


# ============================================ 3. every refusal under the latch
def test_motion_refused_under_the_latch_is_recorded_not_only_raised(
    runtime: RobotRuntime,
) -> None:
    """Section (b): four motion calls were rejected and three were never mentioned.

    The owner's evidence lived only in ``session_slices.events`` — which they
    were not reading, and which had already rolled.
    """

    runtime.action("emergency_stop")
    with pytest.raises(RuntimeError, match="emergency stop"):
        runtime.manual_motion(0.2, 0.0, 0.0)

    rejected = _rows(runtime, SAFETY_LOG_REJECTED)
    assert len(rejected) == 1
    assert "manual" in str(rejected[0]["door"])
    assert rejected[0]["source"] == SAFETY_SOURCE_PANEL, "the row names the latch refusing it"


def test_repeats_from_one_door_coalesce_into_a_count(runtime: RobotRuntime) -> None:
    """THE seed catcher for "refusals are un-coalesced".

    A held arrow key refreshes at the motion cadence. Un-coalesced, one owner
    leaning on the pad fills the whole ring with the same sentence — the 2026-08-18
    mission-log flood, in a ring that has more to lose.
    """

    clock = _Clock()
    runtime._safety_clock = clock
    runtime.action("emergency_stop")
    for _ in range(25):
        clock.advance(0.18)
        with pytest.raises(RuntimeError):
            runtime.manual_motion(0.2, 0.0, 0.0)

    rejected = _rows(runtime, SAFETY_LOG_REJECTED)
    assert len(rejected) == 1, "one door, one row"
    assert rejected[0]["count"] == 25, "coalesced, never dropped"
    assert "x25" in str(rejected[0]["text"])


def test_every_behaviour_door_that_refuses_under_the_latch_records_it_too(
    runtime: RobotRuntime,
) -> None:
    """The OTHER refusal layer, and the seed that found this test missing.

    There are two of them and they are not the same code. ``manual_motion``
    is refused by the arbiter inside ``submit_motion``; ``follow``, navigation,
    search, poses, trajectories and spatial behaviours are refused by the
    runtime's own guard, which is now one helper (``_refuse_under_latch``).
    A seed that deleted the recording from that helper left every test above
    passing, because they all entered through the arbiter — so this one enters
    through the guard.
    """

    runtime.action("emergency_stop")
    with pytest.raises(RuntimeError, match="emergency stop"):
        runtime.set_behavior("follow")

    rejected = _rows(runtime, SAFETY_LOG_REJECTED)
    assert [row["door"] for row in rejected] == ["follow"]
    assert "emergency-stopped" in str(rejected[0]["text"])


def test_a_different_door_always_gets_its_own_row_immediately(
    runtime: RobotRuntime,
) -> None:
    """live_run_1 14:29:11.502: play_gesture AND navigate_to, same millisecond.

    Coalescing by time alone would have merged the compound query's two
    refusals into one row and lost the fact that the decomposition was correct.
    """

    clock = _Clock()
    runtime._safety_clock = clock
    runtime.action("emergency_stop")
    runtime._note_safety_rejection("tool play_gesture", "Motion is disabled")
    runtime._note_safety_rejection("tool navigate_to", "Motion is disabled")

    doors = [row["door"] for row in _rows(runtime, SAFETY_LOG_REJECTED)]
    assert doors == ["tool play_gesture", "tool navigate_to"]


def test_a_refusal_with_no_latch_up_is_never_recorded(runtime: RobotRuntime) -> None:
    """The over-correction guard on the refusal half.

    An unknown pose and a malformed argument are refusals too, and a ring that
    collected them would bury the latch under ordinary validation noise.
    """

    runtime._note_safety_rejection("tool set_pose", "Unknown pose: banana")
    assert _rows(runtime, SAFETY_LOG_REJECTED) == []


def test_a_hosted_tool_refused_under_a_panel_latch_is_still_recorded(
    runtime: RobotRuntime,
) -> None:
    """The coverage hole that ``validate``-watching alone would have left.

    ``SafetyLimits.validate`` reads ``agent.safety.emergency_stopped``, and the
    panel/Space door does not set it — so under a keyed latch the validator
    ADMITS and the refusal happens deeper, in the activity coordinator or in
    local plan admission. The ring has to be complete across latch origins, so
    the door itself is what is watched.
    """

    broker = runtime.realtime_broker
    assert broker is not None
    runtime.action("emergency_stop")
    result = json.loads(
        broker.handle(name="play_gesture", call_id="c1", arguments=json.dumps({"name": "paw_wave"}))
    )

    assert result["status"] != "ok"
    rejected = _rows(runtime, SAFETY_LOG_REJECTED)
    assert [row["door"] for row in rejected] == ["tool play_gesture"]
    # The refusing layer's OWN words, not a sentence this card invented for it.
    assert str(rejected[0]["detail"]["reason"]) in str(rejected[0]["text"])  # type: ignore[index]


def test_the_two_answering_tools_are_never_watched_and_never_refused(
    runtime: RobotRuntime,
) -> None:
    """A stopped robot must still be able to say that it is stopped.

    ``get_status`` and ``recall_memory`` are the tools the owner needs MOST
    while latched. Wrapping them in the refusal watcher would be harmless; a
    latch that made them fail would be the defect this whole card is about.
    """

    broker = runtime.realtime_broker
    assert broker is not None
    runtime.action("emergency_stop")
    result = json.loads(broker.handle(name="get_status", call_id="c1", arguments="{}"))
    assert result["status"] == "ok"
    assert _rows(runtime, SAFETY_LOG_REJECTED) == []


# ====================================== 4. the latch is audible while it lasts
def test_a_status_question_under_a_latch_is_answered_with_the_latch(
    runtime: RobotRuntime,
) -> None:
    """THE seed catcher for "status under latch is silent" — section (b).

    live_run_1's ONE disclosure came 66.6 s late and arrived as a mood report:
    "I'm feeling playful and ready to ruff things up a little. And right now, I
    can't move because motion is disabled, like the emergency stop is on."
    A boolean is what produced that sentence. The answer now carries the door,
    the age and the release condition, so the model has an answer to give.
    """

    clock = _Clock()
    runtime._safety_clock = clock
    broker = runtime.realtime_broker
    assert broker is not None

    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)
    clock.advance(84.0)
    answer = json.loads(broker.handle(name="get_status", call_id="c1", arguments="{}"))

    latch = answer["state"]["emergency_stop"]
    assert latch["latched"] is True
    assert latch["source"] == SAFETY_SOURCE_VOICE
    assert latch["seconds_latched"] == pytest.approx(84.0)
    assert "released" in str(latch["release"])


def test_the_status_answer_says_nothing_about_a_latch_that_is_not_there(
    runtime: RobotRuntime,
) -> None:
    """The other direction: a robot that is fine must not claim to be stopped."""

    broker = runtime.realtime_broker
    assert broker is not None
    answer = json.loads(broker.handle(name="get_status", call_id="c1", arguments="{}"))
    latch = answer["state"]["emergency_stop"]
    assert latch == {"latched": False}
    assert answer["state"]["emergency_stopped"] is False


def test_the_latch_fact_survives_a_release_and_does_not_stick(
    runtime: RobotRuntime,
) -> None:
    """R12's lesson on this card's surface: a cleared latch must clear its door.

    A stale source left behind would have the next latch — or the next status
    question — attributed to a door that had nothing to do with it.
    """

    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)
    runtime.action("clear_emergency_stop")

    assert runtime.snapshot()["safety_latch"] == {"latched": False}
    digest = runtime._whisperer_digest(None, 10.0)
    assert digest.emergency_stopped is False
    assert digest.emergency_stop_source == ""


def test_the_whisperer_digest_carries_the_door_that_latched(
    runtime: RobotRuntime,
) -> None:
    """THE seed catcher for "the digest field is removed".

    The whisperer is the only thing that turns robot state into something the
    companion may say unprompted. A latch it can see but cannot attribute
    produces the sentence live_run_1 got.
    """

    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)
    digest = runtime._whisperer_digest(None, 10.0)

    assert digest.emergency_stopped is True
    assert digest.emergency_stop_source == SAFETY_SOURCE_VOICE
    assert digest.as_dict()["emergency_stop_source"] == SAFETY_SOURCE_VOICE
    assert digest.schema_version == STATE_DIGEST_VERSION


def test_the_spoken_emergency_fact_names_the_door_and_the_way_out() -> None:
    """The FACT is the only thing a gate downstream may read, so it carries both.

    Two latches with the same boolean and different doors are different news,
    and "it cannot move until this is released" is the half live_run_1's owner
    never heard from any surface.
    """

    whisperer = Whisperer(config=WhispererConfig())
    whisperer.observe(StateDigest(at_s=0.0))
    decisions = whisperer.observe(
        StateDigest(at_s=1.0, emergency_stopped=True, emergency_stop_source=SAFETY_SOURCE_VOICE)
    )

    facts = [
        decision.text
        for decision in decisions
        if decision.kind == KIND_EMERGENCY_STOP and decision.forwarded
    ]
    assert facts, f"the latch was not forwarded at all: {decisions}"
    assert ESTOP_SOURCE_PHRASES[SAFETY_SOURCE_VOICE] in facts[0]
    assert "released" in facts[0]


def test_an_unknown_door_produces_no_clause_rather_than_a_guessed_one() -> None:
    """R11's discipline: a digest that cannot name the door says nothing about it.

    Inventing "from the panel" for a source this module has never heard of would
    be exactly the fabricated attribution live_run_1's scorer refused to make.
    """

    whisperer = Whisperer(config=WhispererConfig())
    whisperer.observe(StateDigest(at_s=0.0))
    decisions = whisperer.observe(
        StateDigest(at_s=1.0, emergency_stopped=True, emergency_stop_source="teleport")
    )

    facts = [
        decision.text
        for decision in decisions
        if decision.kind == KIND_EMERGENCY_STOP and decision.forwarded
    ]
    assert facts
    assert "teleport" not in facts[0]
    for clause in ESTOP_SOURCE_PHRASES.values():
        assert clause not in facts[0]


def test_the_digest_schema_version_moved_with_the_field() -> None:
    """A recorded whisperer log must never be re-read against a later schema.

    ``evals/20260820/voice_corpus_v1/live_run_1`` was recorded under version 2
    and it is the run where a latch could not be attributed. A reader that finds
    the field missing has to conclude "this recording could not name the door",
    never "the latch had no door".
    """

    assert STATE_DIGEST_VERSION >= 3
    assert "emergency_stop_source" in StateDigest().as_dict()


# ================================== 5. the substring property, pinned as one
def test_the_spoken_phrase_latches_from_anywhere_inside_an_utterance() -> None:
    """THE seed catcher for "the substring match is anchored".

    live_run_1 section (a): the phrase sat EIGHT WORDS DEEP in a rambling
    improvisation and latched, 100%. That is not an accident of the regex, it is
    the owner's own asymmetry — "a false latch is a stopped dog the panel
    releases in one click; a missed latch is the failure that matters" — and a
    later reader who mistakes it for sloppiness and anchors the match would
    silently delete the property this robot's e-stop is built on.

    Read through the ingress's exported predicate. Nothing here defines,
    widens or narrows a grammar.
    """

    assert matches_spoken_emergency(LIVE_RUN_1_UTTERANCE)
    words = LIVE_RUN_1_UTTERANCE.split()
    assert words.index(SPOKEN_EMERGENCY_PHRASE.split()[0]) >= 8, (
        "the fixture stopped being the deep-in-the-sentence case it exists to be"
    )
    # Head, middle and tail: the position must be irrelevant, not merely
    # tolerated at one offset.
    for utterance in (
        f"{SPOKEN_EMERGENCY_PHRASE} right now please",
        f"no wait {SPOKEN_EMERGENCY_PHRASE} we are too close",
        f"careful careful careful {SPOKEN_EMERGENCY_PHRASE}",
    ):
        assert matches_spoken_emergency(utterance), utterance
        assert scan_realtime_transcript(utterance).kind == "emergency"


def test_bare_stop_stays_whole_utterance_exact(runtime: RobotRuntime) -> None:
    """The other half of the asymmetry, and the reason it is safe.

    "Let's stop by the store" is a sentence people say. It reached the model in
    live_run_1 and came back paraphrased, which is the affirmative proof the
    matcher declined it. If the substring rule ever leaked onto bare "stop",
    this is the test that says so.
    """

    for sentence in (
        "Let's stop by the store.",
        "Don't stop believing.",
        "We can stop for coffee on the way home.",
    ):
        assert not matches_spoken_emergency(sentence), sentence
        outcome = runtime.submit_realtime_transcript(sentence)
        assert outcome.kind != "emergency", sentence

    assert runtime.snapshot()["emergency_stopped"] is False
    assert _rows(runtime, SAFETY_LOG_LATCHED) == []


def test_the_position_property_is_visible_in_the_record_it_produces(
    runtime: RobotRuntime,
) -> None:
    """The two halves joined: a deep match latches AND says it was a deep match.

    An auditor holding this row does not have to re-derive the grammar to know
    why an eight-word preamble stopped the robot.
    """

    runtime.submit_realtime_transcript(LIVE_RUN_1_UTTERANCE)
    row = _rows(runtime, SAFETY_LOG_LATCHED)[0]
    assert row["rule"] == SAFETY_RULE_SPOKEN
    assert str(row["phrase"]).startswith("Alright, let's go home")


# ======================================= 6. the panel, and the audio-mode check
# The panel is HTML with no test runner of its own, so these are SOURCE pins in
# the style ``test_prod_default_path.py`` established for R9's Space branch:
# they read `index.html` and assert on the exact strings the wiring is made of.
# Weaker than driving a browser, and honest about being weaker — but the defect
# class is a silent EDIT, and an edit shows up in the source.
PANEL = REPO / "src" / "parcel_robot" / "ui" / "index.html"

#: The render calls, whole and indented, in the order `renderSnapshot` makes
#: them. One block rather than three substrings, for the reason R9's
#: `_SPACE_BRANCH` is one block: a comment-out or a reorder has to fail the pin
#: rather than pass on independently-present fragments.
_RENDER_BLOCK = """      renderMissionStatus(snapshot);
      renderMissionLog(snapshot.mission_log);
      renderSafetyLog(snapshot.safety_log);
"""


def test_the_panel_renders_the_safety_ring_beside_the_mission_log() -> None:
    """THE seed catcher for "the ring never reaches the panel".

    A record only the runtime can see is the same record live_run_1 did not
    have. The list, its count and the render call all have to be there, wired to
    the snapshot key the runtime actually publishes.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert 'id="safety-log"' in source
    assert 'id="safety-log-count"' in source
    assert "function renderSafetyLog(items) {" in source
    # Pinned as a BLOCK, with its indentation, next to the mission-log call it
    # sits beside. A seed that merely commented the call out still contained the
    # substring `renderSafetyLog(snapshot.safety_log);` and slipped past the
    # first version of this test; a block with a leading newline and four spaces
    # of indent cannot be satisfied by a `// ` prefix or by a reorder.
    assert _RENDER_BLOCK in source, "the safety ring is no longer rendered on every poll"
    # Rendered next to the mission log, in the same panel and the same style.
    assert source.index('id="mission-log"') < source.index('id="safety-log"')


def test_the_panel_never_treats_an_owner_utterance_as_markup() -> None:
    """The verbatim phrase comes off a hosted transcriber and is shown as text.

    ``textContent`` on every field of every row. The one thing this card adds to
    the panel is an arbitrary remote string, so the pin is explicit rather than
    left to the reviewer of the next edit.
    """

    source = PANEL.read_text(encoding="utf-8")
    body = source.split("function renderSafetyLog(items) {", 1)[1].split("\n    }", 1)[0]
    # Comment lines are stripped so that a comment ABOUT the hazard cannot be
    # mistaken for the hazard (this test failed on its own explanation first).
    code = "\n".join(
        line for line in body.splitlines() if not line.strip().startswith("//")
    )
    assert "innerHTML" not in code
    assert "insertAdjacentHTML" not in code
    assert "said.textContent" in code


def test_the_banner_says_which_door_latched_it() -> None:
    """R9 built the banner; live_run_1 showed what it still could not answer.

    "Emergency stop latched" does not tell an owner whether they said it, keyed
    it, or whether the simulator did — and the panel is the surface where the
    release button lives, so it is where the question gets asked.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert 'id="estop-banner-source"' in source
    assert "renderEstopSource(snapshot.safety_latch);" in source
    assert "function renderEstopSource(latch) {" in source
    # R9's own pin, restated here so that adding the source line cannot be the
    # edit that quietly drops the banner it hangs off.
    assert 'el("estop-banner").hidden = !emergencyStopped;' in source


def test_the_banner_is_re_read_the_moment_the_owner_looks_back() -> None:
    """Card item 2, and the finding the audio-mode check actually produced.

    The banner renders from the state poll, and the poll is gated on
    ``!document.hidden`` — deliberately, so a backgrounded tab does not spin.
    Nothing about it is mode-dependent, so it renders in audio mode exactly as
    it does in text mode. What audio mode changes is the OWNER: they are talking,
    not looking, and very plausibly on another tab, and a hidden tab's banner is
    frozen at whatever it last saw. So visibility returning re-reads immediately
    instead of showing a stale safety state until the next interval tick.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert "if (!document.hidden) pollState();" in source, "the poll gate moved"
    handler = source.split('document.addEventListener("visibilitychange", () => {', 1)[1]
    handler = handler.split("});", 1)[0]
    assert "clearMotionInputs();" in handler, "R9's dead-man release must stay"
    assert "pollState();" in handler
    assert handler.index("clearMotionInputs();") < handler.index("pollState();")
