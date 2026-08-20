"""Card R11: the situational whisperer — the policy, pinned rule by rule.

WHAT THIS FILE PINS, AND WHY EACH CLAIM IS HERE
----------------------------------------------
The drafted design had a local model decide the middle band. It was benched
against four alternatives on a 287-event gold-labelled stream and LOST
(``<scratchpad>/csbench/reports/bench_whisperer.md``): judge-everything delayed
an emergency stop by 9.8 s and lost the resume-clear, and the judge band
declined the real pace-mismatch fact while forwarding the jitter — differently
on identical input between runs. So v1 has no model in the forwarding path, and
what replaced it is a table plus three small state machines.

Every test below is therefore a claim about a RULE, and each one names the bench
finding that demands it. Two of them are bugs the bench found in the drafted
deterministic rules themselves — the min-gap swallowing a reroute, and a clear
forwarding for a block nobody was told about — and those two are the ones an
auditor should try hardest to break.

Time is injected everywhere. Nothing here sleeps, and nothing here constructs a
lane, a runtime, a socket or a model.
"""

from __future__ import annotations

import pytest

from parcel_robot.realtime.config import (
    RealtimeConfigError,
    WhispererConfig,
    realtime_config_from_mapping,
    whisperer_config_from_mapping,
)
from parcel_robot.realtime.whisperer import (
    ALWAYS_BAND,
    BAND_ALWAYS,
    BAND_MIDDLE,
    BAND_NEVER,
    BLOCK_DEBOUNCE_S,
    CRITICAL_KINDS,
    DEDUP_TTL_S,
    HINTS,
    KIND_BATTERY_PCT,
    KIND_BATTERY_STATE,
    KIND_EMERGENCY_CLEAR,
    KIND_EMERGENCY_STOP,
    KIND_FOLLOW_TICK,
    KIND_MISSION_ARRIVED,
    KIND_MISSION_BLOCK_CLEAR,
    KIND_MISSION_BLOCKED,
    KIND_MISSION_ENDED,
    KIND_NAV_TICK,
    KIND_OWNER_PACE_CHANGE,
    KIND_PACE_MISMATCH,
    KIND_PACE_UNKNOWN,
    KIND_POSITION,
    KIND_PROXIMITY_CHURN,
    KIND_REFUSAL,
    KIND_REROUTE,
    MIN_GAP_EXEMPT_KINDS,
    NEVER_BAND,
    PACE_MISMATCH_WINDOW_S,
    PACE_SKIP_REASONS,
    PACE_SKIP_UNKNOWN_HOLDING,
    RULE_ALWAYS_BAND,
    RULE_BLOCK_DEBOUNCE_ELAPSED,
    RULE_BLOCK_DEBOUNCE_HOLDING,
    RULE_BUDGET,
    RULE_CLEAR_AFTER_FORWARDED_BLOCK,
    RULE_CLEAR_WITHOUT_FORWARDED_BLOCK,
    RULE_CRITICAL_BYPASS,
    RULE_DEDUP,
    RULE_DISABLED,
    RULE_MIN_GAP,
    RULE_NARRATION_FLOOR_REFUSED,
    RULE_NEVER_BAND,
    RULE_PACE_KNOWN_RESUMED,
    RULE_PACE_UNKNOWN,
    RULE_UNKNOWN_KIND,
    STATE_DIGEST_VERSION,
    WALK_CEILING_MPS,
    StateDigest,
    StateEvent,
    Whisperer,
    WhispererError,
    # Private by name and imported anyway: the guard it carries is unreachable
    # through ``observe`` by construction — the watcher never composes an item
    # without a measurement — and a guard with no test is a comment.
    _pace_mismatch_fact,
    band_of,
    digest_from_mapping,
)


class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


def _whisperer(clock: _Clock | None = None, **config) -> tuple[Whisperer, _Clock]:
    clock = clock or _Clock()
    return Whisperer(config=WhispererConfig(**config), clock=clock), clock


def _digest(clock: _Clock, **fields) -> StateDigest:
    return StateDigest(at_s=clock.now, **fields)


def _forwards(whisperer: Whisperer) -> list[str]:
    return [row["text"] for row in whisperer.decision_rows() if row["forwarded"]]


# =============================================== band 1: nothing may delay it
def test_the_always_band_forwards_through_a_spent_budget_and_a_held_min_gap() -> None:
    """C's disqualifying counterexample: a judge delayed an e-stop by 9.8 s.

    Spend the whole minute's budget, forward something a second ago so the
    min-gap is holding, and then latch an emergency stop. It goes out NOW.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=1, min_gap_s=60.0)
    whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, fact="battery is low"))
    clock.advance(1.0)
    whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="b2", fact="battery is critical"))

    clock.advance(1.0)
    decision = whisperer.offer(StateEvent(kind=KIND_EMERGENCY_STOP, fact="e-stop latched"))

    assert decision.forwarded is True
    assert decision.rule == RULE_CRITICAL_BYPASS
    assert decision.at_s == clock.now, "an emergency stop is forwarded at the moment it happens"


@pytest.mark.parametrize("kind", sorted(CRITICAL_KINDS))
def test_every_critical_kind_bypasses_the_owners_budget(kind: str) -> None:
    """The card's bypass list, one test per member, with the budget at zero left."""

    whisperer, clock = _whisperer(max_updates_per_minute=1, min_gap_s=30.0)
    whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, fact="battery is low"))
    clock.advance(0.5)

    decision = whisperer.offer(StateEvent(kind=kind, fact="something terminal happened"))

    assert decision.forwarded is True, f"{kind} was delayed by the owner's cost knob"


def test_a_non_critical_always_band_fact_still_answers_to_the_knob() -> None:
    """The knob is the knob. Only the enumerated criticals may spend past it."""

    whisperer, clock = _whisperer(max_updates_per_minute=1, min_gap_s=0.0)
    assert whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, fact="low")).forwarded is True
    clock.advance(1.0)

    second = whisperer.offer(StateEvent(kind=KIND_PACE_MISMATCH, fact="mismatch"))

    assert second.forwarded is False
    assert second.rule == RULE_BUDGET


# ==================================================== band 2: it never arrives
@pytest.mark.parametrize("kind", sorted(NEVER_BAND))
def test_the_never_band_never_leaks_however_often_it_is_offered(kind: str) -> None:
    """realtime-mini babbled about injected nav state in 4/4 forced responses.

    The only defence that works is that the item never arrives, so this is
    asserted at 200 offers with the budget wide open — no rule other than the
    band itself is doing any work here.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=1000, min_gap_s=0.0)
    for index in range(200):
        clock.advance(0.5)
        decision = whisperer.offer(StateEvent(kind=kind, key=f"{kind}:{index}", fact="telemetry"))
        assert decision.forwarded is False
        assert decision.rule == RULE_NEVER_BAND

    assert whisperer.forwarded == 0
    assert whisperer.snapshot()["updates_this_minute"] == 0


def test_the_never_band_has_no_configuration_that_can_turn_it_on() -> None:
    """Stated as a property, because a config key here would be the whole bug."""

    assert not (ALWAYS_BAND & NEVER_BAND)
    assert KIND_OWNER_PACE_CHANGE in NEVER_BAND, (
        "the RAW pace change is what made policy B assert wrong pacing out loud"
    )
    for field in WhispererConfig().as_dict():
        assert "band" not in field, f"{field} looks like a band override"


def test_the_band_is_decided_by_the_class_and_never_by_the_text() -> None:
    """Card design 2: nothing downstream of the differ parses a note.

    The same alarming sentence in a telemetry class stays silent; the same
    boring sentence in a safety class is spoken.
    """

    whisperer, _ = _whisperer()
    alarming = "EMERGENCY STOP: cyclist at 0.4 seconds to collision"

    quiet = whisperer.offer(StateEvent(kind=KIND_NAV_TICK, fact=alarming))
    loud = whisperer.offer(StateEvent(kind=KIND_EMERGENCY_STOP, fact="ok"))

    assert quiet.forwarded is False
    assert loud.forwarded is True


# ============================== mechanism 1: the block-entry debounce (>= 8 s)
def _blocked(clock: _Clock, *, episode: int = 1, goal: str = "the sidewalk") -> StateDigest:
    return _digest(
        clock,
        navigating=True,
        nav_goal=goal,
        nav_state="blocked",
        mission_blocked=True,
        mission_block_class="person",
        mission_block_episode=episode,
    )


def _clear(clock: _Clock, *, goal: str = "the sidewalk") -> StateDigest:
    return _digest(clock, navigating=True, nav_goal=goal, nav_state="navigating")


def test_the_debounce_is_the_length_the_bench_measured() -> None:
    """The VALUE, pinned on its own.

    Every behavioural test below derives its timings from this constant, so a
    constant that moved would move the tests with it and nothing would notice.
    Eight seconds is B2's figure, and B2 is the arm that caught 11/12 gold facts
    with zero spam; a shorter debounce is a different policy and has to be
    re-benched rather than re-typed.
    """

    assert BLOCK_DEBOUNCE_S >= 8.0


def test_a_block_shorter_than_the_debounce_is_never_spoken() -> None:
    """B2's debounce. A flap is not a fact."""

    whisperer, clock = _whisperer()
    whisperer.observe(_clear(clock))
    clock.advance(1.0)
    whisperer.observe(_blocked(clock))
    for _ in range(max(1, int(BLOCK_DEBOUNCE_S) - 2)):
        clock.advance(1.0)
        whisperer.observe(_blocked(clock))
    clock.advance(1.0)
    whisperer.observe(_clear(clock))

    assert _forwards(whisperer) == []
    rules = {row["rule"] for row in whisperer.decision_rows()}
    assert RULE_BLOCK_DEBOUNCE_HOLDING in rules


def test_a_block_that_holds_is_spoken_exactly_once() -> None:
    whisperer, clock = _whisperer()
    whisperer.observe(_clear(clock))
    clock.advance(1.0)
    whisperer.observe(_blocked(clock))
    for _ in range(60):
        clock.advance(1.0)
        whisperer.observe(_blocked(clock))

    spoken = _forwards(whisperer)
    assert len(spoken) == 1, f"the block was announced {len(spoken)} times"
    assert "waiting" in spoken[0].lower()
    assert HINTS[KIND_MISSION_BLOCKED] in spoken[0]


def test_the_debounce_is_measured_in_seconds_of_held_block_not_in_ticks() -> None:
    """One tick, eight seconds later, is a block that held for eight seconds."""

    whisperer, clock = _whisperer()
    whisperer.observe(_clear(clock))
    clock.advance(1.0)
    whisperer.observe(_blocked(clock))
    clock.advance(BLOCK_DEBOUNCE_S - 0.01)
    assert _forwards(whisperer) == []
    whisperer.observe(_blocked(clock))
    assert _forwards(whisperer) == [], "forwarded one hundredth of a second early"
    clock.advance(0.02)
    whisperer.observe(_blocked(clock))
    assert len(_forwards(whisperer)) == 1


# =================== mechanism 2: a clear must prove its block was forwarded
def test_a_clear_is_silent_when_its_block_was_never_spoken() -> None:
    """The drafted rules' second bug, stated as the failure it produces.

    "The way is clear again" for a wait the owner was never told about is a
    non-sequitur — the owner has to reconstruct a block that was never
    mentioned. The debounce means most blocks are never mentioned, so without
    this rule that non-sequitur is the COMMON case.
    """

    whisperer, clock = _whisperer()
    whisperer.observe(_clear(clock))
    clock.advance(1.0)
    whisperer.observe(_blocked(clock))
    clock.advance(2.0)
    whisperer.observe(_clear(clock))

    assert _forwards(whisperer) == []
    rules = [row["rule"] for row in whisperer.decision_rows()]
    assert RULE_CLEAR_WITHOUT_FORWARDED_BLOCK in rules
    kinds = [row["kind"] for row in whisperer.decision_rows()]
    assert KIND_MISSION_BLOCK_CLEAR in kinds, "the suppression is still recorded"


def test_a_clear_IS_spoken_when_its_own_block_was_spoken() -> None:
    whisperer, clock = _whisperer()
    whisperer.observe(_clear(clock))
    clock.advance(1.0)
    whisperer.observe(_blocked(clock))
    clock.advance(BLOCK_DEBOUNCE_S + 1.0)
    whisperer.observe(_blocked(clock))
    assert len(_forwards(whisperer)) == 1

    clock.advance(1.0)
    whisperer.observe(_clear(clock))

    spoken = _forwards(whisperer)
    assert len(spoken) == 2
    assert "clear again" in spoken[1]
    rules = [row["rule"] for row in whisperer.decision_rows() if row["forwarded"]]
    assert rules == [RULE_BLOCK_DEBOUNCE_ELAPSED, RULE_CLEAR_AFTER_FORWARDED_BLOCK]


def test_a_second_episode_cannot_inherit_the_first_episodes_permission() -> None:
    """The rule is keyed on the EPISODE, not on "some block was once spoken"."""

    whisperer, clock = _whisperer(max_updates_per_minute=100, min_gap_s=0.0)
    whisperer.observe(_clear(clock))
    clock.advance(1.0)
    whisperer.observe(_blocked(clock, episode=1))
    clock.advance(BLOCK_DEBOUNCE_S + 1.0)
    whisperer.observe(_blocked(clock, episode=1))
    clock.advance(1.0)
    whisperer.observe(_clear(clock))
    spoken_after_first = len(_forwards(whisperer))

    # A second, SHORT block: entry, then clear well before the debounce.
    clock.advance(1.0)
    whisperer.observe(_blocked(clock, episode=2))
    clock.advance(2.0)
    whisperer.observe(_clear(clock))

    assert len(_forwards(whisperer)) == spoken_after_first, (
        "episode 2's clear rode in on episode 1's permission"
    )


def test_two_real_waits_in_one_minute_are_two_sentences_not_one() -> None:
    """The dedup key is scoped to the EPISODE, and it has to be.

    Two separate pedestrians in one minute are two different waits. A dedup key
    of "mission_blocked" would silence the second one for the whole 60 s TTL and
    the owner would watch the robot stand still with no explanation.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=100, min_gap_s=0.0)
    whisperer.observe(_clear(clock))
    for episode in (1, 2):
        clock.advance(1.0)
        whisperer.observe(_blocked(clock, episode=episode))
        clock.advance(BLOCK_DEBOUNCE_S + 1.0)
        whisperer.observe(_blocked(clock, episode=episode))
        clock.advance(1.0)
        whisperer.observe(_clear(clock))

    kinds = [row["kind"] for row in whisperer.decision_rows() if row["forwarded"]]
    assert kinds == [
        KIND_MISSION_BLOCKED,
        KIND_MISSION_BLOCK_CLEAR,
        KIND_MISSION_BLOCKED,
        KIND_MISSION_BLOCK_CLEAR,
    ], "the second wait was deduplicated away as though it were the first"


# ================================================ the shared min-gap bug, fixed
def test_a_reroute_is_not_swallowed_by_a_min_gap_a_clear_is_holding() -> None:
    """THE bench bug, reproduced and fixed.

    Verbatim from bench_whisperer.md: "reroute at t=96 was silently dropped
    because a mission_clear forwarded at t=90 held the 15 s min-gap — G3 missed
    by both deterministic arms." The reroute is a mini-terminal; it is exempt.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=15.0)
    whisperer.offer(StateEvent(kind=KIND_MISSION_BLOCK_CLEAR, key="clear:1", fact="clear again"))
    clock.advance(6.0)

    decision = whisperer.offer(StateEvent(kind=KIND_REROUTE, fact="going another way"))

    assert decision.forwarded is True, "the reroute was swallowed by the min-gap again"


def test_the_min_gap_still_holds_everything_that_is_not_terminal_like() -> None:
    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=15.0)
    whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="b1", fact="low"))
    clock.advance(6.0)

    decision = whisperer.offer(StateEvent(kind=KIND_PACE_MISMATCH, fact="mismatch"))

    assert decision.forwarded is False
    assert decision.rule == RULE_MIN_GAP


def test_the_exempt_set_is_exactly_the_terminal_like_events() -> None:
    assert MIN_GAP_EXEMPT_KINDS == CRITICAL_KINDS | {KIND_MISSION_BLOCK_CLEAR}
    for kind in (KIND_MISSION_ARRIVED, KIND_MISSION_ENDED, KIND_REROUTE, KIND_REFUSAL):
        assert kind in MIN_GAP_EXEMPT_KINDS


# ================================================= caps and dedup, and folding
def test_the_owners_per_minute_cap_is_a_hard_cap() -> None:
    whisperer, clock = _whisperer(max_updates_per_minute=2, min_gap_s=0.0)
    for index in range(6):
        clock.advance(1.0)
        whisperer.offer(StateEvent(kind=KIND_PACE_MISMATCH, key=f"pace:{index}", fact="mismatch"))

    assert len(_forwards(whisperer)) == 2
    assert whisperer.suppressed_by_rule[RULE_BUDGET] == 4


def test_the_budget_window_rolls_rather_than_resetting_on_the_minute() -> None:
    whisperer, clock = _whisperer(max_updates_per_minute=1, min_gap_s=0.0)
    assert whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="a", fact="x")).forwarded
    clock.advance(59.0)
    assert not whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="b", fact="x")).forwarded
    clock.advance(2.0)
    assert whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="c", fact="x")).forwarded


def test_what_the_budget_held_back_rides_on_the_next_thing_that_goes_out() -> None:
    """Suppressed is not discarded. The owner must be able to see the knob work."""

    whisperer, clock = _whisperer(max_updates_per_minute=1, min_gap_s=0.0)
    whisperer.offer(StateEvent(kind=KIND_PACE_MISMATCH, key="p0", fact="mismatch"))
    for index in range(3):
        clock.advance(1.0)
        whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key=f"b{index}", fact="battery"))
    assert whisperer.snapshot()["folded"] == 3

    clock.advance(1.0)
    terminal = whisperer.offer(StateEvent(kind=KIND_MISSION_ARRIVED, fact="Arrived."))

    assert terminal.forwarded is True
    assert terminal.folded == 3
    assert "3 more robot status updates were held back" in terminal.text
    assert whisperer.snapshot()["folded"] == 0


def test_the_same_fact_twice_inside_the_dedup_window_is_said_once() -> None:
    whisperer, clock = _whisperer(max_updates_per_minute=100, min_gap_s=0.0)
    first = whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="battery:low", fact="low"))
    clock.advance(DEDUP_TTL_S - 1.0)
    second = whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="battery:low", fact="low"))
    clock.advance(2.0)
    third = whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="battery:low", fact="low"))

    assert first.forwarded is True
    assert (second.forwarded, second.rule) == (False, RULE_DEDUP)
    assert third.forwarded is True


def test_a_safety_fact_re_arms_faster_than_an_ordinary_one() -> None:
    """A genuine second emergency stop 30 s later must not be deduplicated away."""

    whisperer, clock = _whisperer()
    whisperer.offer(StateEvent(kind=KIND_EMERGENCY_STOP, fact="stopped"))
    clock.advance(30.0)

    again = whisperer.offer(StateEvent(kind=KIND_EMERGENCY_STOP, fact="stopped"))

    assert again.forwarded is True


# ================================================= speech-act hints (design 4)
def test_the_pace_mismatch_item_asks_the_question_the_model_never_asks() -> None:
    """0/12 of the owner-required follow-up questions appeared without this."""

    whisperer, _ = _whisperer()
    decision = whisperer.offer(StateEvent(kind=KIND_PACE_MISMATCH, fact="the state fact"))

    assert decision.forwarded is True
    assert "ask the owner" in decision.text.lower()
    assert "walk" in decision.text.lower()
    assert decision.text.endswith(HINTS[KIND_PACE_MISMATCH])


@pytest.mark.parametrize("kind", sorted(ALWAYS_BAND | {KIND_MISSION_BLOCKED}))
def test_every_speakable_class_carries_a_speech_act(kind: str) -> None:
    assert HINTS.get(kind), f"{kind} would arrive as an inert telegram"


def test_a_fact_that_already_carries_its_own_ask_is_not_asked_twice() -> None:
    """R10's arrival table composes the ask from the row the planner used."""

    whisperer, _ = _whisperer()
    decision = whisperer.offer(
        StateEvent(
            kind=KIND_MISSION_ARRIVED,
            fact="You are at the door. Now ask the owner what they would like to do next.",
            hint_carried=True,
        )
    )

    assert decision.text.count("ask the owner") == 1


# ============================================== the honesty guard (design 7)
def _running_with_a_walking_owner(clock: _Clock, speed: float = 1.1) -> StateDigest:
    return _digest(
        clock,
        following=True,
        follow_pace_intent="run",
        owner_speed_mps=speed,
        robot_pace="its own steady follow pace",
        robot_speed_cap_mps=0.35,
    )


def test_the_pace_mismatch_fact_states_the_gait_the_body_is_actually_in() -> None:
    """The bench's repeatable honesty defect, closed by construction.

    Told only that the owner had slowed, the model announced an adaptation that
    had not happened — "I'm matching your slower pace" while the injected gait
    was still RUN (6/6 chat, 1/3 realtime). The item now says what the gait IS,
    says nothing changed, and gives the cap, so there is no room left for the
    claim.
    """

    whisperer, clock = _whisperer()
    whisperer.observe(_running_with_a_walking_owner(clock))  # baseline
    clock.advance(1.0)
    whisperer.observe(_running_with_a_walking_owner(clock))  # the window opens
    clock.advance(PACE_MISMATCH_WINDOW_S + 1.0)
    whisperer.observe(_running_with_a_walking_owner(clock))

    spoken = _forwards(whisperer)
    assert len(spoken) == 1
    text = spoken[0]
    assert "current gait is its own steady follow pace" in text
    assert "has NOT changed speed" in text
    assert "0.35 m/s" in text
    assert "1.1 m/s" in text


def test_the_sustained_window_is_long_enough_to_survive_a_kerb() -> None:
    """The VALUE, pinned on its own, for the same reason the debounce is.

    G12's window in the gold stream was 25 s wide. A window of a second or two
    would fire every time the owner stopped at a crossing, which is the D arm's
    failure mode (three questions in sixteen seconds, calm 3.0/10) arriving by a
    different route.
    """

    assert PACE_MISMATCH_WINDOW_S >= 5.0


def test_the_pace_watcher_waits_for_a_sustained_window() -> None:
    """A single slow sample is a pause at a kerb, not a change of plan.

    Two seconds is a hard number on purpose: deriving it from the constant would
    make this test move whenever the constant did, and then it would pin
    nothing.
    """

    whisperer, clock = _whisperer()
    whisperer.observe(_running_with_a_walking_owner(clock))
    clock.advance(1.0)
    whisperer.observe(_running_with_a_walking_owner(clock))
    clock.advance(2.0)
    whisperer.observe(_running_with_a_walking_owner(clock))

    assert _forwards(whisperer) == []


def test_an_owner_who_is_actually_running_produces_no_mismatch() -> None:
    whisperer, clock = _whisperer()
    fast = WALK_CEILING_MPS + 0.6
    whisperer.observe(_running_with_a_walking_owner(clock, speed=fast))
    clock.advance(PACE_MISMATCH_WINDOW_S + 2.0)
    whisperer.observe(_running_with_a_walking_owner(clock, speed=fast))

    assert _forwards(whisperer) == []


def test_the_mismatch_is_said_once_and_re_arms_only_when_it_resolves() -> None:
    """One episode, one sentence — and a recurrence still answers to dedup.

    Forty seconds of a walking owner in a run-follow is ONE question, not
    thirty-four. And an episode that resolves and comes back inside the dedup
    window is still the same question, so it is not asked again until the window
    has passed: the bench's D arm asked three battery questions in sixteen
    seconds and scored 3.0/10 on calm for exactly this shape of repetition.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=100, min_gap_s=0.0)
    for _ in range(40):
        clock.advance(1.0)
        whisperer.observe(_running_with_a_walking_owner(clock))
    assert len(_forwards(whisperer)) == 1

    # The owner speeds up (the mismatch resolves) and then slows again, all
    # inside the dedup window: the watcher re-arms, the dedup keeps it quiet.
    for _ in range(3):
        clock.advance(1.0)
        whisperer.observe(_running_with_a_walking_owner(clock, speed=WALK_CEILING_MPS + 1.0))
    for _ in range(int(PACE_MISMATCH_WINDOW_S) + 3):
        clock.advance(1.0)
        whisperer.observe(_running_with_a_walking_owner(clock))
    assert len(_forwards(whisperer)) == 1
    assert whisperer.suppressed_by_rule.get(RULE_DEDUP) == 1

    # Same again, well past the dedup window. Now it is a fresh question.
    for _ in range(3):
        clock.advance(1.0)
        whisperer.observe(_running_with_a_walking_owner(clock, speed=WALK_CEILING_MPS + 1.0))
    clock.advance(DEDUP_TTL_S)
    for _ in range(int(PACE_MISMATCH_WINDOW_S) + 3):
        clock.advance(1.0)
        whisperer.observe(_running_with_a_walking_owner(clock))

    assert len(_forwards(whisperer)) == 2


def test_a_follow_with_no_pace_declaration_never_trips_the_watcher() -> None:
    whisperer, clock = _whisperer()
    for _ in range(30):
        clock.advance(1.0)
        whisperer.observe(_digest(clock, following=True, owner_speed_mps=0.6))

    assert _forwards(whisperer) == []


# ======================================= card R13: the watcher never goes silent
def _unmeasurable_owner(clock: _Clock, status: str = "insufficient_motion") -> StateDigest:
    """A run-follow whose owner the heading estimator cannot measure at all.

    This is E1's recorded failure, reduced: ``run-with-me-flex`` ran 58.8 s with
    ``follow_pace_intent="run"`` and a verifiable 2.2 → 1.0 m/s owner in the path
    file, and ``owner_speed_mps`` was ``None`` for every digest of it.
    """

    return _digest(
        clock,
        following=True,
        follow_pace_intent="run",
        owner_speed_mps=None,
        owner_speed_status=status,
        robot_pace="its own steady follow pace",
        robot_speed_cap_mps=0.35,
    )


def _pace_rows(whisperer: Whisperer) -> list[dict[str, object]]:
    return [row for row in whisperer.decision_rows() if row["kind"] == KIND_PACE_UNKNOWN]


def test_an_unmeasurable_owner_is_a_row_and_not_a_silence() -> None:
    """The E1 defect, stated as the test that would have caught it.

    Before R13 this exact digest produced **nothing**: ``_pace_watch`` gated on
    ``owner_speed_mps is not None`` and returned an empty tuple, so the one
    artifact whose purpose is answering "why did the dog stay quiet" had no row
    at the moment it was being asked. The row also carries the follow
    controller's own word for what the owner track was doing, because an
    auditor holding only the log should not have to guess.
    """

    whisperer, clock = _whisperer()
    whisperer.observe(_unmeasurable_owner(clock))  # baseline
    clock.advance(1.0)
    whisperer.observe(_unmeasurable_owner(clock))

    rows = _pace_rows(whisperer)
    assert len(rows) == 1
    assert rows[0]["rule"] == RULE_PACE_UNKNOWN
    assert rows[0]["forwarded"] is False
    assert rows[0]["key"] == "pace_unknown:insufficient_motion"
    assert whisperer.suppressed_by_rule[RULE_PACE_UNKNOWN] == 1


def test_the_blind_interval_is_a_length_the_log_can_be_read_for() -> None:
    """Two rows bound the hole, so "how long was it blind" is a subtraction.

    E1's offline probe had to reconstruct a 10 s dropout from a sampler it wrote
    itself. The log now says it.
    """

    whisperer, clock = _whisperer()
    whisperer.observe(_running_with_a_walking_owner(clock))  # baseline, measured
    clock.advance(1.0)
    opening = whisperer.observe(_unmeasurable_owner(clock))
    opened_at = _pace_rows(whisperer)[0]["at_s"]
    for _ in range(10):
        clock.advance(1.0)
        whisperer.observe(_unmeasurable_owner(clock))
    clock.advance(1.0)
    closing = whisperer.observe(_running_with_a_walking_owner(clock))

    rows = _pace_rows(whisperer)
    assert [row["rule"] for row in rows] == [RULE_PACE_UNKNOWN, RULE_PACE_KNOWN_RESUMED]
    # Both rows are RETURNED, not merely recorded. The runtime iterates what
    # ``observe`` hands back — it is how a forward reaches the lane and how a
    # refusal gets undelivered — so a row the watcher writes into the ring and
    # keeps to itself is invisible to every consumer except an eval pack.
    # (each tick also returns the differ's own never-band ``owner_pace_change``
    # for the band crossing, which is why these look at the last row rather
    # than the whole tuple.)
    assert [row.rule for row in opening][-1] == RULE_PACE_UNKNOWN
    assert [row.rule for row in closing][-1] == RULE_PACE_KNOWN_RESUMED
    assert rows[1]["at_s"] - opened_at == pytest.approx(11.0)
    assert whisperer.snapshot(clock.now)["pace_watch"]["pace_unknown_seconds"] == pytest.approx(
        11.0
    )
    assert whisperer.snapshot(clock.now)["pace_watch"]["pace_unknown_episodes"] == 1


def test_the_window_pauses_across_a_hole_instead_of_starting_over() -> None:
    """The card's second half, and the reason a flaky estimator stops mattering.

    Four and a half seconds of a measurably walking owner are banked; the
    estimator then goes blind for twenty seconds. When it comes back the owner
    is still walking, and the ask is owed after the REMAINING 1.5 s — not after
    a fresh six. The assertion is deliberately on the gap since the measurement
    returned: reset-on-unknown passes every other assertion in this test.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=0.0)
    whisperer.observe(_running_with_a_walking_owner(clock))  # baseline
    clock.advance(1.0)
    whisperer.observe(_running_with_a_walking_owner(clock))  # the window opens
    clock.advance(4.5)
    whisperer.observe(_unmeasurable_owner(clock))  # 4.5 s banked, clock stops
    for _ in range(20):
        clock.advance(1.0)
        whisperer.observe(_unmeasurable_owner(clock))
        assert _forwards(whisperer) == [], "blind seconds are not mismatch seconds"

    returned_at = clock.advance(1.0)
    whisperer.observe(_running_with_a_walking_owner(clock))
    assert _forwards(whisperer) == [], "4.5 banked + 0 measured is not a sustained walk"
    clock.advance(1.6)
    whisperer.observe(_running_with_a_walking_owner(clock))

    spoken = _forwards(whisperer)
    assert len(spoken) == 1
    assert "rather just walk" in spoken[0].lower()
    assert clock.now - returned_at < PACE_MISMATCH_WINDOW_S, (
        "the ask waited a whole fresh window, so the banked seconds were thrown away"
    )


def test_a_hole_banks_nothing_towards_the_ask_by_itself() -> None:
    """Blindness is not evidence. It must never become the reason to speak.

    The complement of the test above, and the one that stops "pause the window"
    from quietly becoming "count the hole as a walk": a minute of unmeasurable
    owner buys zero seconds, and a two-second walk afterwards is still a pause
    at a kerb.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=0.0)
    whisperer.observe(_unmeasurable_owner(clock))  # baseline
    for _ in range(60):
        clock.advance(1.0)
        whisperer.observe(_unmeasurable_owner(clock))
    assert _forwards(whisperer) == []

    clock.advance(1.0)
    whisperer.observe(_running_with_a_walking_owner(clock))
    clock.advance(2.0)
    whisperer.observe(_running_with_a_walking_owner(clock))

    assert _forwards(whisperer) == []
    assert whisperer.snapshot(clock.now)["pace_watch"]["mismatch_banked_s"] == 0.0


def test_the_e1_scenario_ends_in_the_ask_it_was_supposed_to() -> None:
    """`run-with-me-flex`, replayed with the dropout that made it fail.

    Twelve seconds of a measurably running owner, ten blind seconds across the
    transition (the probe's measured shape), then a sustained walk. The recorded
    scenario produced 24 rows and none of them were about pace; this ends where
    the card says it should — with the robot asking whether to just walk.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=0.0)
    running = WALK_CEILING_MPS + 0.3
    whisperer.observe(_running_with_a_walking_owner(clock, speed=running))  # baseline
    for _ in range(12):
        clock.advance(1.0)
        whisperer.observe(_running_with_a_walking_owner(clock, speed=running))
    for _ in range(10):
        clock.advance(1.0)
        whisperer.observe(_unmeasurable_owner(clock))
    for _ in range(8):
        clock.advance(1.0)
        whisperer.observe(_running_with_a_walking_owner(clock, speed=1.0))

    spoken = _forwards(whisperer)
    assert len(spoken) == 1
    assert "1.0 m/s" in spoken[0]
    assert "has NOT changed speed" in spoken[0]
    assert spoken[0].endswith(HINTS[KIND_PACE_MISMATCH])
    assert [row["rule"] for row in _pace_rows(whisperer)] == [
        RULE_PACE_UNKNOWN,
        RULE_PACE_KNOWN_RESUMED,
    ]


def test_every_watcher_tick_writes_a_row_or_a_counted_skip() -> None:
    """The invariant the card asks to be pinned, over every state it has.

    Not "most ticks are accounted for". Every tick of every state, including the
    session's first digest, which produces no diff at all. The seven reasons are
    each reached at least once here, so a reason that becomes unreachable — the
    shape the None-hole had — fails this test rather than passing it quietly.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=0.0)
    ticks = 0

    def observe(digest: StateDigest) -> None:
        nonlocal ticks
        ticks += 1
        whisperer.observe(digest)

    observe(_digest(clock))  # baseline
    for _ in range(2):  # not following at all
        clock.advance(1.0)
        observe(_digest(clock))
    for _ in range(2):  # following, but nobody asked for a run
        clock.advance(1.0)
        observe(_digest(clock, following=True, follow_pace_intent="walk", owner_speed_mps=0.9))
    for _ in range(2):  # measurably running: the world agrees with the request
        clock.advance(1.0)
        observe(_running_with_a_walking_owner(clock, speed=WALK_CEILING_MPS + 0.5))
    for _ in range(3):  # blind
        clock.advance(1.0)
        observe(_unmeasurable_owner(clock))
    for _ in range(12):  # a sustained measured walk: accumulate, fire, then latch
        clock.advance(1.0)
        observe(_running_with_a_walking_owner(clock))

    watch = whisperer.snapshot(clock.now)["pace_watch"]
    assert watch["ticks"] == ticks
    assert watch["logged"] + sum(watch["skips"].values()) == ticks
    assert watch["accounted"] is True
    assert set(watch["skips"]) == set(PACE_SKIP_REASONS), (
        "a skip reason nobody can reach is a state nobody is counting"
    )
    assert len(_forwards(whisperer)) == 1


def test_a_skip_reason_is_always_one_of_the_declared_ones() -> None:
    """A typo'd reason key would count silently and read as a new state."""

    whisperer, clock = _whisperer()
    for speed in (None, 0.9, 3.0, None, 0.9):
        clock.advance(1.0)
        whisperer.observe(
            _unmeasurable_owner(clock)
            if speed is None
            else _running_with_a_walking_owner(clock, speed=speed)
        )

    assert set(whisperer.pace_watch_skips) <= set(PACE_SKIP_REASONS)


def test_a_follow_that_ends_mid_hole_does_not_claim_the_pace_came_back() -> None:
    """A subject that walked away is not a measurement that recovered.

    ``pace_known_resumed`` means the estimator answered again. Writing one when
    the follow simply stopped would put a recovery in the log that never
    happened, and the next follow would inherit a window it did not earn.
    """

    whisperer, clock = _whisperer()
    whisperer.observe(_unmeasurable_owner(clock))  # baseline
    clock.advance(1.0)
    whisperer.observe(_unmeasurable_owner(clock))
    clock.advance(4.0)
    whisperer.observe(_digest(clock))  # the follow ended

    assert [row["rule"] for row in _pace_rows(whisperer)] == [RULE_PACE_UNKNOWN]
    watch = whisperer.snapshot(clock.now)["pace_watch"]
    assert watch["pace_unknown"] is False
    assert watch["pace_unknown_seconds"] == pytest.approx(4.0)
    assert watch["mismatch_banked_s"] == 0.0


def test_the_watchers_ledger_outlives_the_decision_ring() -> None:
    """Why the skips are counters and not rows.

    The ring holds a few minutes; a walk does not. The owner-session capture
    that motivated this card had aggregates, one ``last`` row, and no way to
    answer the question. A counter cannot be evicted.
    """

    clock = _Clock()
    whisperer = Whisperer(config=WhispererConfig(), clock=clock, decision_log_max=4)
    whisperer.observe(_unmeasurable_owner(clock))  # baseline
    clock.advance(1.0)
    whisperer.observe(_unmeasurable_owner(clock))  # the pace_unknown row
    for index in range(10):
        clock.advance(1.0)
        whisperer.observe(
            _digest(clock, following=True, follow_pace_intent="run", position_dm=(index, 0))
        )

    assert _pace_rows(whisperer) == [], "the ring evicted it, which is the point"
    watch = whisperer.snapshot(clock.now)["pace_watch"]
    assert watch["pace_unknown_episodes"] == 1
    assert watch["pace_unknown"] is True
    assert watch["pace_unknown_for_s"] == pytest.approx(10.0)
    assert watch["skips"][PACE_SKIP_UNKNOWN_HOLDING] == 10


def test_the_unknown_class_is_banded_and_cannot_be_spoken() -> None:
    """It is instrumentation. The owner is never told about the instrument."""

    whisperer, _ = _whisperer()
    decision = whisperer.offer(StateEvent(kind=KIND_PACE_UNKNOWN, fact="?"))

    assert band_of(KIND_PACE_UNKNOWN) == BAND_NEVER
    assert decision.forwarded is False
    assert decision.rule == RULE_NEVER_BAND
    assert KIND_PACE_UNKNOWN not in HINTS


def test_the_pace_item_refuses_to_be_composed_without_a_measurement() -> None:
    """The old wording called an unmeasurable owner "below a walking pace".

    That sentence asserts a measurement in the one item whose entire job is not
    overstating what the robot knows. It was unreachable; it is now refused, so
    a future caller cannot make it reachable by accident.
    """

    clock = _Clock()
    with pytest.raises(WhispererError, match="no measured owner speed"):
        _pace_mismatch_fact(_unmeasurable_owner(clock), window_s=PACE_MISMATCH_WINDOW_S)


# ============================================================ the decision log
def test_every_forward_and_every_suppression_is_recorded_with_its_rule() -> None:
    """The auditability requirement, which OUTLIVED the judge's removal.

    A judge's "why" was a sampled token. A rule name is a constant in the
    module, so "why did the dog say that" is reproducible.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=2, min_gap_s=0.0)
    offered = [
        StateEvent(kind=KIND_NAV_TICK),
        # Critical: bypasses the budget, and is COUNTED against it, so the two
        # non-critical facts behind it see a budget with one slot left.
        StateEvent(kind=KIND_EMERGENCY_STOP, fact="stopped"),
        StateEvent(kind=KIND_BATTERY_STATE, key="b", fact="low"),
        StateEvent(kind=KIND_PACE_MISMATCH, fact="mismatch"),
        StateEvent(kind="a_class_nobody_declared", fact="?"),
    ]
    for event in offered:
        clock.advance(1.0)
        whisperer.offer(event)

    rows = whisperer.decision_rows()
    assert len(rows) == len(offered), "an offer went unrecorded"
    assert [row["rule"] for row in rows] == [
        RULE_NEVER_BAND,
        RULE_CRITICAL_BYPASS,
        RULE_ALWAYS_BAND,
        RULE_BUDGET,
        RULE_UNKNOWN_KIND,
    ]
    assert [row["seq"] for row in rows] == [1, 2, 3, 4, 5]
    for row in rows:
        assert row["rule"], "a decision with no rule is not an audit record"
        assert row["schema_version"] == STATE_DIGEST_VERSION


def test_the_log_is_a_bounded_ring_and_evicts_oldest_first() -> None:
    whisperer = Whisperer(config=WhispererConfig(), clock=_Clock(), decision_log_max=5)
    for index in range(20):
        whisperer.offer(StateEvent(kind=KIND_NAV_TICK, key=str(index)))

    rows = whisperer.decision_rows()
    assert len(rows) == 5
    assert [row["seq"] for row in rows] == [16, 17, 18, 19, 20]


def test_an_undeclared_class_fails_closed_and_says_so() -> None:
    whisperer, _ = _whisperer()
    decision = whisperer.offer(StateEvent(kind="mission_teleported", fact="!"))

    assert band_of("mission_teleported") == ""
    assert decision.forwarded is False
    assert decision.rule == RULE_UNKNOWN_KIND


def test_the_owners_off_switch_stops_state_updates_and_records_that_it_did() -> None:
    whisperer, _ = _whisperer(enabled=False)
    decision = whisperer.offer(StateEvent(kind=KIND_EMERGENCY_STOP, fact="stopped"))

    assert decision.forwarded is False
    assert decision.rule == RULE_DISABLED
    assert whisperer.snapshot()["enabled"] is False


def test_a_forward_the_lane_refused_gives_the_budget_slot_back() -> None:
    """Nothing was spoken and nothing was billed, so nothing was spent."""

    whisperer, clock = _whisperer(max_updates_per_minute=1, min_gap_s=0.0)
    first = whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="b", fact="low"))
    assert first.forwarded is True
    assert whisperer.snapshot()["updates_this_minute"] == 1

    whisperer.undeliver(first)

    assert whisperer.snapshot()["updates_this_minute"] == 0
    assert whisperer.decision_rows()[-1]["rule"] == RULE_NARRATION_FLOOR_REFUSED
    clock.advance(1.0)
    again = whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="b", fact="low"))
    assert again.forwarded is True, "a fact the model never heard was deduplicated away"


def test_undeliver_gives_back_its_own_dedup_entry_and_no_one_elses() -> None:
    """Two facts can share a tick; only the refused one is refunded.

    The digest tick can forward more than one item at the same instant, so
    "whatever was recorded at this timestamp" is not an identity. The decision
    carries its dedup KEY for exactly this.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=100, min_gap_s=0.0)
    kept = whisperer.offer(StateEvent(kind=KIND_EMERGENCY_STOP, key="estop", fact="stopped"))
    refused = whisperer.offer(StateEvent(kind=KIND_MISSION_ARRIVED, key="arrived", fact="here"))
    assert kept.at_s == refused.at_s

    whisperer.undeliver(refused)

    clock.advance(1.0)
    assert whisperer.offer(
        StateEvent(kind=KIND_MISSION_ARRIVED, key="arrived", fact="here")
    ).forwarded is True
    assert whisperer.offer(
        StateEvent(kind=KIND_EMERGENCY_STOP, key="estop", fact="stopped")
    ).rule == RULE_DEDUP


def test_every_decision_row_names_the_fact_it_was_about() -> None:
    whisperer, _ = _whisperer()
    whisperer.offer(StateEvent(kind=KIND_NAV_TICK))
    whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="battery:low", fact="low"))

    rows = whisperer.decision_rows()
    assert [row["key"] for row in rows] == [KIND_NAV_TICK, "battery:low"]


# ================================================= the digest and its version
def test_the_differ_turns_state_into_classes_and_never_into_prose() -> None:
    whisperer, clock = _whisperer(max_updates_per_minute=100, min_gap_s=0.0)
    whisperer.observe(_digest(clock, battery_percent=40.0, battery_state="normal"))
    clock.advance(1.0)
    whisperer.observe(
        _digest(
            clock,
            battery_percent=29.0,
            battery_state="low",
            proximity_state="slowing",
            navigating=True,
            nav_state="planned",
            position_dm=(12, 4),
        )
    )

    rows = whisperer.decision_rows()
    kinds = [row["kind"] for row in rows]
    assert KIND_BATTERY_STATE in kinds
    assert KIND_PROXIMITY_CHURN in kinds
    assert KIND_POSITION in kinds
    spoken = _forwards(whisperer)
    assert len(spoken) == 1
    assert "29 percent" in spoken[0]
    assert HINTS[KIND_BATTERY_STATE] in spoken[0]


def test_a_battery_that_only_moves_a_percent_is_telemetry() -> None:
    """D narrated the battery three times in sixteen seconds. Calm: 3.0/10."""

    whisperer, clock = _whisperer(max_updates_per_minute=100, min_gap_s=0.0)
    whisperer.observe(_digest(clock, battery_percent=60.0, battery_state="normal"))
    for percent in (55.0, 50.0, 45.0, 40.0, 35.0, 31.0):
        clock.advance(1.0)
        whisperer.observe(_digest(clock, battery_percent=percent, battery_state="normal"))

    assert _forwards(whisperer) == []
    assert whisperer.suppressed_by_rule[RULE_NEVER_BAND] == 6
    kinds = {row["kind"] for row in whisperer.decision_rows()}
    assert kinds == {KIND_BATTERY_PCT}


def test_the_first_digest_of_a_session_is_a_baseline_and_never_an_announcement() -> None:
    whisperer, clock = _whisperer()
    decisions = whisperer.observe(_digest(clock, battery_state="low", emergency_stopped=True))

    assert decisions == ()
    assert whisperer.decision_rows() == []


def test_a_digest_from_a_schema_this_build_cannot_read_is_refused() -> None:
    whisperer, clock = _whisperer()
    whisperer.observe(_digest(clock))

    with pytest.raises(WhispererError, match="schema"):
        whisperer.observe(StateDigest(schema_version=STATE_DIGEST_VERSION + 1, at_s=clock.now))


def test_a_recorded_digest_replays_without_the_runtime_and_refuses_typos() -> None:
    """The eval pack replays these; a silently-ignored key would be a lie."""

    row = _digest(_Clock(), battery_state="low", following=True).as_dict()
    assert digest_from_mapping(row).battery_state == "low"

    with pytest.raises(WhispererError, match="unknown state digest key"):
        digest_from_mapping({**row, "battery_stat": "low"})


def test_the_follow_tick_is_telemetry_and_the_emergency_edge_is_not() -> None:
    whisperer, clock = _whisperer(max_updates_per_minute=100, min_gap_s=0.0)
    whisperer.observe(_digest(clock, following=True, follow_distance_dm=18))
    clock.advance(1.0)
    whisperer.observe(_digest(clock, following=True, follow_distance_dm=21))
    clock.advance(1.0)
    whisperer.observe(_digest(clock, following=True, follow_distance_dm=21, emergency_stopped=True))
    clock.advance(1.0)
    whisperer.observe(_digest(clock, following=True, follow_distance_dm=21))

    rows = whisperer.decision_rows()
    ticks = [row for row in rows if row["kind"] == KIND_FOLLOW_TICK]
    assert ticks and not any(row["forwarded"] for row in ticks)
    spoken = [row["kind"] for row in rows if row["forwarded"]]
    assert spoken == [KIND_EMERGENCY_STOP, KIND_EMERGENCY_CLEAR]


def test_the_bands_are_disjoint_and_cover_every_declared_kind() -> None:
    for kind in ALWAYS_BAND:
        assert band_of(kind) == BAND_ALWAYS
    for kind in NEVER_BAND:
        assert band_of(kind) == BAND_NEVER
    for kind in (KIND_MISSION_BLOCKED, KIND_MISSION_BLOCK_CLEAR):
        assert band_of(kind) == BAND_MIDDLE
    assert CRITICAL_KINDS <= ALWAYS_BAND


# ==================================================== the owner's config knob
def test_the_absent_block_is_the_documented_default() -> None:
    config = realtime_config_from_mapping({"enabled": True})
    assert config.whisperer == WhispererConfig()
    assert config.whisperer.max_updates_per_minute == 2
    assert config.whisperer.min_gap_s == 15.0
    assert config.as_dict()["whisperer"] == config.whisperer.as_dict()


def test_the_knob_is_read_from_the_owners_yaml() -> None:
    config = realtime_config_from_mapping(
        {"enabled": True, "whisperer": {"enabled": False, "max_updates_per_minute": 1}}
    )
    assert config.whisperer.enabled is False
    assert config.whisperer.max_updates_per_minute == 1


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ({"max_updates_per_minuet": 4}, "unknown realtime.whisperer key"),
        ({"enabled": "ture"}, "must be a boolean"),
        ({"max_updates_per_minute": 0}, "at least 1"),
        ({"max_updates_per_minute": -3}, "at least 1"),
        ({"max_updates_per_minute": 2.5}, "whole number"),
        ({"max_updates_per_minute": True}, "whole number"),
        ({"min_gap_s": -1.0}, "must not be negative"),
        ({"min_gap_s": "soon"}, "must be a number"),
    ],
)
def test_a_malformed_knob_is_a_refusal_and_never_a_silent_default(
    body: dict, match: str
) -> None:
    """A mistyped cap that read as the default would bill at the default forever."""

    with pytest.raises(RealtimeConfigError, match=match):
        whisperer_config_from_mapping(body)


def test_the_knob_is_a_mapping_or_it_is_nothing() -> None:
    with pytest.raises(RealtimeConfigError, match="must be a mapping"):
        whisperer_config_from_mapping(["enabled"])  # type: ignore[arg-type]


def test_zero_spacing_is_allowed_because_the_budget_is_still_the_cap() -> None:
    config = whisperer_config_from_mapping({"min_gap_s": 0})
    assert config.min_gap_s == 0.0
    assert config.max_updates_per_minute == 2
