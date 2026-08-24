"""Card R20 — Narnia is not on the map. Unknown-place goal admission.

WHAT THIS FILE PINS, and the measurement behind each claim.

**The defect.** ``evals/20260820/voice_corpus_v1/live_run_1`` §d: "Go to Narnia."
and "Take me to the moon." were admitted as ``navigate_to`` goals and RAN —
4.25 s and 10.7 s of ``state=searching reason=scan_behavior_rotate``, the robot
turning on the spot hunting for places that cannot exist — each behind a
confident **"Okay—I'll go wait near narnia safely."** Nine seconds earlier
"let's go home" got a textbook ask, which is what made the contrast legible.

**The fork.** Two layers each deferred to the other. R10's ``validate_place``
refuses junk argument SHAPES ("with owner") and deliberately admits an
unheard-of noun, for authority parity with the typed panel. The deterministic
router then said ``navigation_directive`` and was right to: the grammar is
about shape, and ``go to <noun>`` is a navigation directive whatever the noun
is. Nobody asked whether anything could resolve the noun.

**The fix, and why it is in the grammar and not in the broker.** Refusing
"narnia" in the broker alone would give the hosted lane a private grammar
stricter than the panel's — precisely what R10 forbade. So the policy lives in
``navigation.goals.admit_navigation_place``, the layer both lanes compile
through, and BOTH admission paths ask it: the hosted ``navigate_to`` door and
the typed panel's navigation branch. Parity is preserved by refusing on both
sides rather than by refusing on neither.

**The boundary, stated once.** This is a gate on GOAL ADMISSION, not a ban on
exploration. "Look for a mailbox" is an explicit search and still searches,
unknown noun or not; only "go to X" / "take me to X" must name something the
robot can resolve. The boundary is ``_EXPLICIT_SEARCH_PATTERN`` — the grammar's
own locate-and-approach regex, used by the gate and by the destination parser,
so it cannot drift.

Every place vocabulary here is a fake list, so the corpus rows that failed live
are answered on every commit, for free, forever (card item 3).
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.navigation.goals import (
    _DESTINATION_PATTERNS,
    _EXPLICIT_SEARCH_PATTERN,
    PLACE_ADMITTED,
    PLACE_EXPLICIT_SEARCH,
    PLACE_NO_VOCABULARY,
    PLACE_NOT_A_DIRECTIVE,
    PLACE_OFFER_LIMIT,
    PLACE_OWNER_REFERENT,
    PLACE_UNKNOWN,
    admit_navigation_place,
    navigation_directive_from_text,
    place_query_from_directive,
    semantic_goal_from_directive,
)
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV
from parcel_robot.realtime.tool_broker import (
    STATUS_OK,
    STATUS_REJECTED,
    TENSE_NOT_STARTED,
    detail_tense_violation,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "evals" / "20260820" / "voice_corpus_v1" / "queries.tsv"

#: The fake resolver, card item 3. Shaped after the vocabulary the LIVE run was
#: actually holding: the city sidecar's classes and aliases, plus the two named
#: instances its mission log resolved routes to ("coffee shop at 42nd street"
#: with route=31, "crosswalk" with route=3).
KNOWN: tuple[str, ...] = (
    "sidewalk",
    "pavement",
    "bench",
    "park bench",
    "crosswalk",
    "zebra crossing",
    "lamppost",
    "street light",
    "tree",
    "door",
    "planter",
    "building",
    "grass",
    "coffee shop at 42nd street",
)

#: What a refusal OFFERS, nearest first. A different list from ``KNOWN`` on
#: purpose: a refusal that offers a place the owner cannot see is worse than one
#: that offers nothing, so the offer list is instances-nearest-first while the
#: resolution set is everything the grounder could match.
OFFER: tuple[str, ...] = ("coffee shop at 42nd street", "bench", "crosswalk", "sidewalk")


def _corpus() -> dict[str, str]:
    """``{id: query}`` from the corpus the live run was scored against."""

    with CORPUS.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return {str(row["id"]): str(row["query"]) for row in rows}


def _verdict(query: str):
    return admit_navigation_place(query, KNOWN, offer=OFFER)


# ==================================================== 1. the corpus rows that failed
@pytest.mark.parametrize(
    ("query_id", "noun"),
    [
        ("10", "narnia"),
        ("11", "my office"),
        ("12", "moon"),
    ],
)
def test_the_nav_invalid_corpus_rows_are_refused_with_real_alternatives(
    query_id: str, noun: str
) -> None:
    """live_run_1 rows 10 and 12 FAILED and row 11 was never spoken.

    Row 11 is in here deliberately: the scoring called it "the most costly miss"
    of the nav-invalid block because it is the sibling of the one refusal that
    worked. A regression test does not need the owner to say it out loud.
    """

    verdict = _verdict(_corpus()[query_id])

    assert verdict.admitted is False
    assert verdict.reason == PLACE_UNKNOWN
    assert verdict.query == noun
    assert verdict.alternatives, "a refusal that names nothing is just a no"
    assert noun in verdict.reply() and noun in verdict.fact()


def test_the_refusal_offers_places_the_robot_can_actually_reach() -> None:
    """The card's sentence, executable: nearest real places, and only those."""

    verdict = _verdict("Go to Narnia.")

    assert verdict.alternatives == OFFER[:PLACE_OFFER_LIMIT], "nearest-first, bounded"
    assert set(verdict.alternatives) <= set(OFFER)
    for place in verdict.alternatives:
        assert place in verdict.reply()
        assert place in verdict.fact()


def test_a_refusal_with_nothing_to_offer_says_that_instead_of_saying_less() -> None:
    """An empty offer list is a different sentence, not a truncated one."""

    verdict = admit_navigation_place("go to narnia", KNOWN, offer=())
    # ``offer`` falls back to ``known`` rather than going silent.
    assert verdict.alternatives == KNOWN[:PLACE_OFFER_LIMIT]

    verdict = admit_navigation_place("go to narnia", ("bench",), offer=("bench",))
    assert verdict.alternatives == ("bench",)
    assert "the bench" in verdict.reply()


def test_q13_home_never_reached_goal_admission_at_all() -> None:
    """The honest version of "the ask path exists".

    q13 PASSED live, and NOT because a refusal path caught it: "let's go home"
    carries no ``to``/``onto``/``into``, matches no destination pattern, and
    never becomes a directive — the hosted model wrote that ask itself. Pinning
    the real reason is what stops a future card from "restoring" a path that was
    never there.
    """

    assert navigation_directive_from_text(_corpus()["13"]) is None
    assert admit_navigation_place(_corpus()["13"], KNOWN).reason == PLACE_NOT_A_DIRECTIVE


def test_home_is_still_refused_when_the_model_does_render_it_as_a_goal() -> None:
    """…and if a future turn does say ``navigate_to({"place": "home"})``."""

    verdict = _verdict("go to home")
    assert verdict.admitted is False
    assert verdict.query == "home"


def test_q06_restaurant_is_the_same_defect_wearing_a_plausible_noun() -> None:
    """live_run_1 scored q06 PARTIAL with the identical rotate-scan signature.

    "restaurant" is not a fictional place — it is simply not on THIS map, which
    is the same fact from the robot's side, and the run's own note says the
    robot "had a real, resolved food place in hand and did not offer it."
    """

    verdict = _verdict("go to restaurant")

    assert verdict.admitted is False
    assert "coffee shop at 42nd street" in verdict.reply()


# ============================================ 2. the over-correction, guarded
@pytest.mark.parametrize(
    ("query_id", "place"),
    [
        ("01", "the sidewalk"),
        ("02", "the lamppost"),
        ("03", "the bench"),
        ("04", "the grass"),
        ("05", "the coffee shop"),
        ("08", "the crosswalk"),
        ("09", "the bench"),
    ],
)
def test_every_mapped_place_in_the_corpus_still_admits(query_id: str, place: str) -> None:
    """THE DANGEROUS DIRECTION. A gate that refuses real places costs the owner
    the robot; a gate that admits an unfindable one costs them one honest
    "I looked and couldn't find it". These rows are the ones that must not move.

    Both renderings are checked, because the two lanes hand this function
    different strings for the same request: the panel passes the owner's
    sentence, and the hosted tool passes ``go to <place>``. q08 ("Can you get to
    the crosswalk?") is the row that makes the difference visible — "get to" is
    not in the destination grammar's verb alternation, so the owner's own
    sentence is not a directive at all, while the tool's rendering is.
    """

    assert _verdict(_corpus()[query_id]).admitted is True
    hosted = _verdict(f"go to {place}")
    assert hosted.admitted is True
    assert hosted.reason == PLACE_ADMITTED


@pytest.mark.parametrize(
    "directive",
    [
        "go to the pavement",
        "go to the street light",
        "walk to the zebra crossing",
        "go to the park bench",
    ],
)
def test_an_alias_is_a_real_place(directive: str) -> None:
    """The resolution set carries class ALIASES, not just class names.

    A vocabulary of bare class labels would refuse "the pavement" and "street
    light" — both of which the grounder resolves — which is exactly the
    over-correction this card was told to guard against.
    """

    assert _verdict(directive).admitted is True


@pytest.mark.parametrize(
    "directive",
    [
        "go to the coffee shop",  # the query is INSIDE a longer mapped instance
        "go to the big oak bench",  # a mapped noun inside a longer query
        "go to the nearest bench",
        "head over to the coffee shop at 42nd street",
    ],
)
def test_a_place_matches_by_phrase_in_either_direction(directive: str) -> None:
    assert _verdict(directive).admitted is True


def test_the_owner_is_not_a_place_and_is_never_refused_as_one() -> None:
    """N12: the owner is a tracked entity on the owner channel, never a map
    label — so "go to me" is resolvable precisely BECAUSE it is absent from the
    place vocabulary. Refusing it here would break the approach lane over a list
    it was never meant to appear on."""

    for directive in ("go to me", "go to the owner", "go to my side"):
        verdict = _verdict(directive)
        assert verdict.admitted is True
        assert verdict.reason == PLACE_OWNER_REFERENT


def test_an_empty_vocabulary_admits_everything_and_says_which() -> None:
    """FAIL-OPEN, deliberately, and visibly.

    A robot whose map has not loaded knows no places at all. A gate that
    refused everything then would take the whole navigation surface down over a
    missing sidecar — so it admits, and the reason says ``no_vocabulary`` rather
    than pretending the place was recognized.
    """

    verdict = admit_navigation_place("go to narnia", ())
    assert verdict.admitted is True
    assert verdict.reason == PLACE_NO_VOCABULARY
    assert verdict.reason != PLACE_ADMITTED


def test_a_negated_or_hypothetical_sentence_is_not_this_gates_business() -> None:
    """"don't go to narnia" is refused as motion authority one layer up, and
    must not be answered here as though the owner had asked for a place."""

    assert admit_navigation_place("don't go to narnia", KNOWN).reason == PLACE_NOT_A_DIRECTIVE


@pytest.mark.parametrize("directive", ["go to here", "go to forward", "go to back"])
def test_the_gate_declines_jurisdiction_over_what_the_grammar_already_refuses(
    directive: str,
) -> None:
    """Deictic and directional destinations stay the ROUTER's refusal.

    ``navigation_directive_from_text`` already returns ``None`` for these, and
    the router names the rule that declined. "I don't know a place called
    'here'" would be a worse sentence AND a second layer refusing the same
    string for a different reason, which is how a refusal stops meaning
    anything.
    """

    assert navigation_directive_from_text(directive) is None
    assert admit_navigation_place(directive, KNOWN).reason == PLACE_NOT_A_DIRECTIVE


# =================================================== 3. exploration is not banned
@pytest.mark.parametrize(
    "directive",
    [
        "look for a mailbox",
        "find a mailbox",
        "search for a fire hydrant",
        "locate the postbox",
    ],
)
def test_an_explicit_search_still_searches_for_something_unmapped(directive: str) -> None:
    """The boundary the card asked to be documented, as a test.

    The owner who says "look for a mailbox" has asked the robot to LOOK. The
    scan that follows is the thing they requested, not a fabricated goal, and
    the honest ending ("I looked and couldn't find it") is the honest ending of
    a search rather than a lie about a place.
    """

    verdict = admit_navigation_place(directive, KNOWN, offer=OFFER)

    assert verdict.admitted is True
    assert verdict.reason == PLACE_EXPLICIT_SEARCH


def test_the_search_boundary_is_the_grammars_own_pattern() -> None:
    """ONE regex, used twice. If the locate-and-approach pattern is ever
    widened, the exploration boundary widens with it in the same commit — it
    cannot be edited in one place and forgotten in the other."""

    assert _EXPLICIT_SEARCH_PATTERN in _DESTINATION_PATTERNS


def test_goal_phrasing_for_the_same_unmapped_noun_is_still_refused() -> None:
    """The boundary has two sides and this is the other one."""

    assert admit_navigation_place("go to the mailbox", KNOWN, offer=OFFER).admitted is False


# ================================================ 4. the gate cannot drift from the compiler
@pytest.mark.parametrize(
    "directive",
    [
        "go to narnia",
        "go to the big oak bench",
        "walk towards the nearest tree",
        "sit next to the bench",
        "take me to the moon",
        "head over to the coffee shop at 42nd street",
        "find the nearest lamppost",
        "go to the sidewalk",
        "run to the crosswalk",
        "wait by the lamppost",
    ],
)
def test_the_gate_and_the_compiler_read_the_same_noun(directive: str) -> None:
    """The one invariant that makes this gate safe to have at all.

    A gate that judged one noun while the compiler searched for another would
    be the worst of both worlds — refusing real places AND still admitting
    fabricated ones. They share ``_destination_noun``; this is the pin that
    says so out loud.
    """

    assert place_query_from_directive(directive) == semantic_goal_from_directive(directive).query


# ============================================================== 5. the two lanes
class _Backend:
    name = "r20"

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend="r20",
        )

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context
        return AgentDecision(f"Understood: {transcript}")


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A runtime with the hosted lane enabled in text mode, and one observation."""

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV", raising=False)
    path = tmp_path / "r20.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
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
  logging: false
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    runtime = RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r20 fixture",
        ),
    )
    runtime._observation = runtime.backend.observe()
    try:
        yield runtime
    finally:
        runtime.close()


def _navigate_to(runtime: RobotRuntime, place: str) -> dict:
    return json.loads(
        runtime.realtime_broker.handle(
            name="navigate_to", call_id="c1", arguments=json.dumps({"place": place})
        )
    )


def test_the_hosted_tool_rejects_narnia_and_hands_the_model_real_alternatives(
    wired: RobotRuntime,
) -> None:
    """live_run_1 q10, offline. The result the model reads is the whole fix:
    R4-lite's Defect C says the model narrates whatever ``detail`` gives it, so
    ``detail`` is where the true sentence has to be."""

    result = _navigate_to(wired, "narnia")

    assert result["status"] == STATUS_REJECTED
    assert result["tense"] == TENSE_NOT_STARTED
    assert result["finished"] is False
    assert "narnia" in result["detail"]
    assert "bench" in result["detail"] or "sidewalk" in result["detail"]
    # R15's rule holds for a refusal too: the detail is a fact, never the
    # robot's own voice, or the model re-voices it as a decision it made.
    assert detail_tense_violation(result["detail"]) == "", result["detail"]


def test_the_refused_goal_never_becomes_a_mission_or_an_ack(wired: RobotRuntime) -> None:
    """The bench_eval_designs finding, closed one layer lower.

    ``bench_eval_designs.md`` flagged the whisperer ack "Okay—I'll go wait near
    narnia safely." as the same overclaim family one layer down. That sentence
    is written by ``_plan_acknowledgement`` AFTER ``_accept_plan`` admits a
    plan — so the fix is not to reword it. Nothing is admitted, so nothing
    writes it.
    """

    result = _navigate_to(wired, "narnia")

    assert result["status"] == STATUS_REJECTED
    assert "go wait near" not in result["detail"]
    assert wired.task_executive.snapshot()["tasks"] == []
    assert wired._last_brain_plan is None
    # The router was never asked: the noun is unresolvable whatever the grammar
    # says about the shape, so there is nothing for the router to decide.
    assert wired.realtime_snapshot()["last_route"] is None


def test_a_real_place_still_admits_through_the_hosted_tool(wired: RobotRuntime) -> None:
    """The over-correction guard, end to end rather than on the pure function."""

    result = _navigate_to(wired, "the sidewalk")

    assert result["status"] == STATUS_OK
    assert wired.realtime_snapshot()["last_route"]["rule"] == "navigation_directive"


def test_an_alias_still_admits_through_the_hosted_tool(wired: RobotRuntime) -> None:
    """The resolution set is alias-aware where it is actually assembled.

    ``_realtime_places`` — R10's nearest-first OFFER list — carries class names
    and no aliases; it is the right list to *offer* and the wrong list to
    *resolve against*. "The pavement" is a real, groundable request, and a gate
    built on the offer list alone would call it fiction. This is the test that
    keeps the two lists separate.
    """

    assert _navigate_to(wired, "the pavement")["status"] == STATUS_OK


def test_the_typed_panel_refuses_exactly_what_the_hosted_tool_refuses(
    wired: RobotRuntime,
) -> None:
    """R10's authority parity, preserved in the direction that keeps it honest.

    ``test_navigate_to_grants_exactly_what_a_typed_sentence_grants`` said the
    broker must not be stricter than the panel. It still is not: the panel
    refuses "narnia" too, because both lanes ask ``_place_admission``.
    """

    hosted = _navigate_to(wired, "narnia")
    typed = wired.handle_text("go to narnia")

    assert hosted["status"] == STATUS_REJECTED
    assert "narnia" in typed
    assert "don't know" in typed
    assert wired.task_executive.snapshot()["tasks"] == []


def test_a_goal_amendment_to_an_unmapped_place_is_asked_about_too(
    wired: RobotRuntime,
) -> None:
    """A retarget is a goal admission like any other.

    Without this arm, "actually, go to narnia" mid-mission takes the planner-less
    amendment's honest-but-useless reply ("give me the new command on its own")
    and the owner walks round the loop to be refused by the OTHER path. Same
    question, same answer, wherever it is asked.
    """

    wired.handle_text("go to the sidewalk")
    reply = wired.handle_text("actually, go to narnia")

    assert "narnia" in reply and "don't know" in reply
    assert wired.agent.last_brain_metrics["goal_amend_replan"] == "unknown_place_refused"


def test_the_typed_ask_names_real_places(wired: RobotRuntime) -> None:
    reply = wired.handle_text("take me to the moon")

    assert "moon" in reply
    assert "bench" in reply or "sidewalk" in reply
    assert "Okay" not in reply, "an ask is not an acknowledgement"


def test_the_typed_panel_still_admits_a_real_place(wired: RobotRuntime) -> None:
    reply = wired.handle_text("go to the sidewalk")

    assert "don't know a place" not in reply


def test_an_agent_with_no_place_provider_is_unchanged(wired: RobotRuntime) -> None:
    """Flag-off shape: no vocabulary reachable ⇒ the pre-R20 path, exactly."""

    wired.agent.place_admission = None
    assert wired.agent._unknown_place_reply("go to narnia") is None
