"""Card CURIO-1 — the dog talks about what it sees.

WHAT THIS FILE IS FOR
---------------------
Four claims, and the file is arranged as four sections around them:

1. **A remark can only ever name a place the map has ADMITTED.** In
   ``known_places()`` at the moment of speaking, and never a ``vlm_proposed``
   guess. The card calls a violation a hallucinated place and makes it a hard
   row; seed A attacks it.
2. **A remark can never land on top of the owner.** The lane's own busy state is
   read before the budget is spent, and the lane's floor gate refuses it again
   after; seed B attacks it.
3. **A remark can never spend past the owner's cap.** No curiosity class is
   critical, so the per-minute knob binds it exactly like a battery fact; seed C
   attacks it.
4. **A remark can only reach the model through the scheduler.** The curiosity
   classes are MIDDLE band, so bare ``Whisperer.offer`` refuses them; seed D
   attacks it.

Sections 1-3 are the policy against a frozen clock with no robot. Section 5 is
the PRODUCT PATH: a real ``RobotRuntime``, a real ``OnlineSemanticMap``, and
``_step_whisperer`` driven the way the control loop drives it — because a guard
proved only against a hand-built rig is a guard nobody has shown is wired in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.online_map.entries import (
    NAME_PROMOTED,
    NAME_VLM_PROPOSED,
    MapObservation,
    ProposedName,
    WriterProvenance,
)
from parcel_robot.online_map.online_map import OnlineSemanticMap
from parcel_robot.realtime.config import (
    CURIOSITY_ALLOWED_KEYS,
    REALTIME_CONFIG_ENV,
    CuriosityConfig,
    OwnerEventsConfig,
    RealtimeConfigError,
    WhispererConfig,
    curiosity_config_from_mapping,
    whisperer_config_from_mapping,
)
from parcel_robot.realtime.whisperer import (
    ALWAYS_BAND,
    BAND_ALWAYS,
    BAND_MIDDLE,
    CHATTER_SKIP_ACTIVITY_BUSY,
    CHATTER_SKIP_CONVERSATION,
    CHATTER_SKIP_DISABLED,
    CHATTER_SKIP_GAP_HOLDING,
    CHATTER_SKIP_LANE_BUSY,
    CHATTER_SKIP_NO_OWNER,
    CHATTER_SKIP_QUIET_HOURS,
    CHATTER_SKIP_REASONS,
    CHATTER_SKIP_STIMULUS_GAP,
    CRITICAL_KINDS,
    CURIOSITY_KINDS,
    HINTS,
    KIND_ASK_ABOUT,
    KIND_IDLE_REMARK,
    KIND_NOVEL_OBJECT,
    KIND_OWNER_LEFT,
    KIND_PLACE_LEARNED,
    KIND_SCENE_CHANGE,
    MIDDLE_BAND,
    RULE_BUDGET,
    RULE_CHATTER_SCHEDULED,
    RULE_CURIOSITY_DOOR_WRONG_CLASS,
    RULE_DEDUP,
    RULE_MIDDLE_BAND_NEEDS_MECHANISM,
    RULE_MIN_GAP,
    STIMULUS_KINDS,
    TIME_BAND_AFTERNOON,
    TIME_BAND_EVENING,
    TIME_BAND_MORNING,
    TIME_BAND_NIGHT,
    ChatterScheduler,
    ChatterState,
    FarewellWatcher,
    OwnerPresence,
    StateEvent,
    Whisperer,
    WhispererError,
    band_of,
    curiosity_event,
    time_band_of,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "curio1"

PROV = WriterProvenance(
    session_id="curio1-test",
    seat="in_loop_query",
    detector_name="owlv2-b16-int8",
    scene_id="city_block",
)


class _Clock:
    def __init__(self, start: float = 5_000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


class _Gaps:
    """A deterministic stand-in for ``random.Random``. One number, always."""

    def __init__(self, gap: float) -> None:
        self.gap = float(gap)
        self.draws = 0

    def expovariate(self, lambd: float) -> float:
        del lambd
        self.draws += 1
        return self.gap


def _scheduler(
    *, clock: _Clock, gap: float = 60.0, **overrides
) -> ChatterScheduler:
    settings = {"enabled": True, "mean_gap_s": 300.0, "min_gap_floor_s": 0.0}
    settings.update(overrides)
    return ChatterScheduler(
        config=CuriosityConfig(**settings),
        clock=clock,
        rng=_Gaps(gap),
        time_band=lambda: TIME_BAND_AFTERNOON,
    )


def _state(clock: _Clock, **overrides) -> ChatterState:
    settings: dict[str, object] = {
        "at_s": clock.now,
        "owner_present": True,
        "lane_busy": False,
        "activity_running": False,
    }
    settings.update(overrides)
    return ChatterState(**settings)  # type: ignore[arg-type]


# ===========================================================================
# 1. the vocabulary: kinds, bands, hints
# ===========================================================================


def test_the_four_curiosity_classes_are_middle_band() -> None:
    """MIDDLE, which in this module means "a mechanism decides, not a band"."""

    assert CURIOSITY_KINDS == {
        KIND_PLACE_LEARNED,
        KIND_NOVEL_OBJECT,
        KIND_SCENE_CHANGE,
        KIND_ASK_ABOUT,
        KIND_IDLE_REMARK,
    }
    for kind in CURIOSITY_KINDS:
        assert kind in MIDDLE_BAND
        assert band_of(kind) == BAND_MIDDLE


def test_the_stimulus_split_is_exactly_the_event_driven_classes() -> None:
    """Correction pass, ruling 6: two cadences over two kinds of remark."""

    assert STIMULUS_KINDS == CURIOSITY_KINDS - {KIND_IDLE_REMARK}
    assert KIND_IDLE_REMARK not in STIMULUS_KINDS


def test_the_farewell_is_an_always_band_owner_fact() -> None:
    assert KIND_OWNER_LEFT in ALWAYS_BAND
    assert band_of(KIND_OWNER_LEFT) == BAND_ALWAYS


def test_no_curiosity_class_is_critical() -> None:
    """SEED C. The cap is the owner's knob and a lamppost may not outrank it."""

    assert not (CURIOSITY_KINDS & CRITICAL_KINDS)
    assert KIND_OWNER_LEFT not in CRITICAL_KINDS


def test_every_new_class_carries_a_speech_act_hint() -> None:
    """A fact with no speech act is what makes the model narrate the instrument."""

    for kind in (*CURIOSITY_KINDS, KIND_OWNER_LEFT):
        hint = HINTS.get(kind, "")
        assert hint, kind
        assert "NOT" in hint, f"{kind}'s hint names no prohibition"


def test_band_of_is_still_total_over_every_declared_class() -> None:
    for kind in (*CURIOSITY_KINDS, KIND_OWNER_LEFT):
        assert band_of(kind) in {BAND_ALWAYS, BAND_MIDDLE}


# ===========================================================================
# 2. the door: only the mechanism may speak for the middle band
# ===========================================================================


def _whisperer(clock: _Clock, **overrides) -> Whisperer:
    settings: dict[str, object] = {"min_gap_s": 0.0, "max_updates_per_minute": 6}
    settings.update(overrides)
    return Whisperer(config=WhispererConfig(**settings), clock=clock)  # type: ignore[arg-type]


def test_a_curiosity_event_handed_to_bare_offer_is_refused() -> None:
    """SEED D. The middle band's whole claim, stated as a test."""

    clock = _Clock()
    whisperer = _whisperer(clock)
    decision = whisperer.offer(curiosity_event(KIND_NOVEL_OBJECT, "bench"))
    assert decision.forwarded is False
    assert decision.rule == RULE_MIDDLE_BAND_NEEDS_MECHANISM


def test_the_curiosity_door_forwards_and_names_its_rule() -> None:
    clock = _Clock()
    whisperer = _whisperer(clock)
    decision = whisperer.offer_curiosity(curiosity_event(KIND_NOVEL_OBJECT, "bench"))
    assert decision.forwarded is True
    assert decision.rule == RULE_CHATTER_SCHEDULED
    assert decision.band == BAND_MIDDLE
    assert "bench" in decision.text


def test_the_curiosity_door_refuses_a_class_it_is_not_the_mechanism_for() -> None:
    """A mechanism that speaks for any class it is handed is not a mechanism."""

    clock = _Clock()
    whisperer = _whisperer(clock)
    decision = whisperer.offer_curiosity(StateEvent(kind="battery_state", fact="x"))
    assert decision.forwarded is False
    assert decision.rule == RULE_CURIOSITY_DOOR_WRONG_CLASS


def test_a_remark_obeys_the_dedup_window_like_every_other_fact() -> None:
    clock = _Clock()
    whisperer = _whisperer(clock)
    first = whisperer.offer_curiosity(curiosity_event(KIND_NOVEL_OBJECT, "bench"))
    second = whisperer.offer_curiosity(curiosity_event(KIND_NOVEL_OBJECT, "bench"))
    assert first.forwarded is True
    assert second.forwarded is False
    assert second.rule == RULE_DEDUP


def test_a_remark_obeys_the_min_gap_like_every_other_fact() -> None:
    clock = _Clock()
    whisperer = _whisperer(clock, min_gap_s=15.0)
    assert whisperer.offer_curiosity(curiosity_event(KIND_NOVEL_OBJECT, "bench")).forwarded
    clock.advance(2.0)
    second = whisperer.offer_curiosity(curiosity_event(KIND_NOVEL_OBJECT, "kerb"))
    assert second.forwarded is False
    assert second.rule == RULE_MIN_GAP


def test_remarks_can_never_spend_past_the_owners_cap() -> None:
    """SEED C, measured. One candidate a second for ten minutes."""

    clock = _Clock()
    whisperer = _whisperer(clock, max_updates_per_minute=6, min_gap_s=0.0)
    forwards: list[float] = []
    for index in range(600):
        clock.advance(1.0)
        decision = whisperer.offer_curiosity(
            curiosity_event(KIND_NOVEL_OBJECT, f"thing-{index}")
        )
        if decision.forwarded:
            forwards.append(clock.now)
    assert forwards, "the cap must not be a mute button"
    worst = max(
        sum(1 for stamp in forwards if start <= stamp < start + 60.0)
        for start in forwards
    )
    assert worst <= 6, f"{worst} remarks inside one minute against a cap of 6"
    budget_rows = [
        row for row in whisperer.decision_rows() if row["rule"] == RULE_BUDGET
    ]
    assert budget_rows, "nothing was ever held back, so the cap proved nothing"


# ===========================================================================
# 3. the fact: a sentence with no hole in it
# ===========================================================================


def test_a_remark_refuses_to_compose_without_a_place() -> None:
    """An empty name is a sentence the model would finish for us."""

    with pytest.raises(WhispererError):
        curiosity_event(KIND_NOVEL_OBJECT, "   ")


def test_a_remark_refuses_an_unknown_class() -> None:
    with pytest.raises(WhispererError):
        curiosity_event("weather_report", "bench")


def test_the_place_is_recoverable_from_the_decision_row() -> None:
    """The audit path: a decision row must name what the robot talked about."""

    event = curiosity_event(KIND_PLACE_LEARNED, "the front step")
    assert event.key == "place_learned:the front step"
    assert event.detail["place"] == "the front step"
    assert "the front step" in event.fact


def test_the_time_of_day_rides_the_fact_as_a_clause_not_a_timestamp() -> None:
    event = curiosity_event(KIND_NOVEL_OBJECT, "bench", time_band=TIME_BAND_EVENING)
    assert "It is the evening." in event.fact
    assert event.detail["time_band"] == TIME_BAND_EVENING


def test_the_time_bands_partition_the_day() -> None:
    seen = {time_band_of(hour) for hour in range(24)}
    assert seen == {
        TIME_BAND_MORNING,
        TIME_BAND_AFTERNOON,
        TIME_BAND_EVENING,
        TIME_BAND_NIGHT,
    }
    assert time_band_of(3) == TIME_BAND_NIGHT
    assert time_band_of(23) == TIME_BAND_NIGHT
    assert time_band_of(9) == TIME_BAND_MORNING


# ===========================================================================
# 4. the scheduler
# ===========================================================================


def test_every_tick_is_admitted_or_named(scheduler_ticks: int = 50) -> None:
    """R13's invariant, applied to a second watcher: ticks == admitted + skips."""

    clock = _Clock()
    scheduler = _scheduler(clock=clock, gap=10.0)
    for _ in range(scheduler_ticks):
        clock.advance(1.0)
        scheduler.due(_state(clock))
        scheduler.note_remark(clock.now)
    assert scheduler.ticks == scheduler_ticks
    assert scheduler.admitted + sum(scheduler.skips.values()) == scheduler.ticks
    assert set(scheduler.skips) <= CHATTER_SKIP_REASONS


def test_a_disabled_block_never_admits_anything() -> None:
    clock = _Clock()
    scheduler = _scheduler(clock=clock, enabled=False, gap=0.0)
    clock.advance(10_000.0)
    assert scheduler.due(_state(clock)) is False
    assert scheduler.skips == {CHATTER_SKIP_DISABLED: 1}


def test_a_busy_lane_is_a_refusal_and_it_is_named() -> None:
    """SEED B. The owner is mid-turn; the dog does not get the mouth."""

    clock = _Clock()
    scheduler = _scheduler(clock=clock, gap=0.0)
    clock.advance(10_000.0)
    assert scheduler.due(_state(clock, lane_busy=True)) is False
    assert scheduler.skips == {CHATTER_SKIP_LANE_BUSY: 1}


def test_an_absent_owner_is_a_refusal() -> None:
    clock = _Clock()
    scheduler = _scheduler(clock=clock, gap=0.0)
    clock.advance(10_000.0)
    assert scheduler.due(_state(clock, owner_present=False)) is False
    assert scheduler.skips == {CHATTER_SKIP_NO_OWNER: 1}


def test_a_running_activity_defers_the_remark_to_an_idle_checkpoint() -> None:
    """``prompts/functions/patrol.yaml``: social actions can wait."""

    clock = _Clock()
    scheduler = _scheduler(clock=clock, gap=0.0)
    clock.advance(10_000.0)
    assert scheduler.due(_state(clock, activity_running=True)) is False
    assert scheduler.skips == {CHATTER_SKIP_ACTIVITY_BUSY: 1}
    assert scheduler.due(_state(clock, activity_running=False)) is True


def test_the_night_band_silences_the_dog_and_the_knob_turns_that_off() -> None:
    clock = _Clock()
    quiet = ChatterScheduler(
        config=CuriosityConfig(enabled=True, min_gap_floor_s=0.0),
        clock=clock,
        rng=_Gaps(0.0),
        time_band=lambda: TIME_BAND_NIGHT,
    )
    clock.advance(10_000.0)
    assert quiet.due(_state(clock)) is False
    assert quiet.skips == {CHATTER_SKIP_QUIET_HOURS: 1}

    loud = ChatterScheduler(
        config=CuriosityConfig(enabled=True, night_quiet=False, min_gap_floor_s=0.0),
        clock=clock,
        rng=_Gaps(0.0),
        time_band=lambda: TIME_BAND_NIGHT,
    )
    assert loud.due(_state(clock)) is True


def test_an_owner_exchange_starts_the_quiet_window_over() -> None:
    clock = _Clock()
    scheduler = _scheduler(clock=clock, gap=0.0, quiet_s=90.0)
    clock.advance(10_000.0)
    scheduler.note_turn(clock.now)
    clock.advance(30.0)
    assert scheduler.due(_state(clock)) is False
    assert scheduler.skips == {CHATTER_SKIP_CONVERSATION: 1}
    clock.advance(61.0)
    assert scheduler.due(_state(clock)) is True


def test_a_session_nobody_has_spoken_on_has_no_conversation_to_protect() -> None:
    """The difference between a companion that goes first and one that waits."""

    clock = _Clock()
    scheduler = _scheduler(clock=clock, gap=0.0, quiet_s=90.0)
    clock.advance(1.0)
    assert scheduler.due(_state(clock)) is True


def test_the_robots_own_remarks_do_not_reset_the_quiet_window() -> None:
    """The two clocks stay separate, or the faster of them means nothing."""

    clock = _Clock()
    scheduler = _scheduler(clock=clock, gap=10.0, quiet_s=90.0)
    clock.advance(1.0)
    assert scheduler.due(_state(clock)) is False  # the anchor tick
    clock.advance(11.0)
    assert scheduler.due(_state(clock)) is True
    scheduler.note_remark(clock.now)
    clock.advance(11.0)
    # The gap has elapsed again and no OWNER turn happened, so the quiet window
    # is not what is being measured here.
    assert scheduler.due(_state(clock)) is True


def test_the_gap_paces_the_monologue() -> None:
    clock = _Clock()
    scheduler = _scheduler(clock=clock, gap=30.0)
    clock.advance(10.0)
    assert scheduler.due(_state(clock)) is False
    assert scheduler.skips == {CHATTER_SKIP_GAP_HOLDING: 1}
    clock.advance(31.0)
    assert scheduler.due(_state(clock)) is True
    scheduler.note_remark(clock.now)
    clock.advance(5.0)
    assert scheduler.due(_state(clock)) is False


def test_the_gap_is_clamped_by_its_floor() -> None:
    clock = _Clock()
    scheduler = ChatterScheduler(
        config=CuriosityConfig(enabled=True, min_gap_floor_s=20.0),
        clock=clock,
        rng=_Gaps(0.2),
        time_band=lambda: TIME_BAND_AFTERNOON,
    )
    clock.advance(5.0)
    assert scheduler.due(_state(clock)) is False
    clock.advance(21.0)
    assert scheduler.due(_state(clock)) is True


def test_the_scheduler_publishes_what_it_did() -> None:
    clock = _Clock()
    scheduler = _scheduler(clock=clock, gap=0.0)
    clock.advance(5.0)
    scheduler.due(_state(clock))
    snapshot = scheduler.snapshot()
    assert snapshot["ticks"] == 1
    assert snapshot["admitted"] == 1
    assert snapshot["config"]["enabled"] is True


# ===========================================================================
# 4b. the farewell
# ===========================================================================


def _farewell(clock: _Clock, **overrides) -> FarewellWatcher:
    settings: dict[str, object] = {"enabled": True, "farewell_after_s": 45.0}
    settings.update(overrides)
    return FarewellWatcher(
        config=CuriosityConfig(**settings),  # type: ignore[arg-type]
        min_confidence=0.3,
        clock=clock,
    )


def test_a_robot_that_has_never_seen_anyone_never_says_goodbye() -> None:
    clock = _Clock()
    watcher = _farewell(clock)
    for _ in range(600):
        clock.advance(1.0)
        assert watcher.observe(OwnerPresence(present=False, at_s=clock.now)) == ()
    assert watcher.farewells == 0


def test_the_farewell_is_the_falling_edge_after_the_absence() -> None:
    clock = _Clock()
    watcher = _farewell(clock, farewell_after_s=45.0)
    assert watcher.observe(OwnerPresence(present=True, at_s=clock.now)) == ()
    clock.advance(10.0)
    assert watcher.observe(OwnerPresence(present=False, at_s=clock.now)) == ()
    clock.advance(44.0)
    assert watcher.observe(OwnerPresence(present=False, at_s=clock.now)) == ()
    clock.advance(2.0)
    events = watcher.observe(OwnerPresence(present=False, at_s=clock.now))
    assert [event.kind for event in events] == [KIND_OWNER_LEFT]
    assert events[0].detail["gone_for_s"] >= 45.0


def test_a_farewell_fires_once_per_departure_and_re_arms_on_a_return() -> None:
    clock = _Clock()
    watcher = _farewell(clock, farewell_after_s=5.0)
    watcher.observe(OwnerPresence(present=True, at_s=clock.now))
    clock.advance(1.0)
    watcher.observe(OwnerPresence(present=False, at_s=clock.now))
    clock.advance(10.0)
    assert len(watcher.observe(OwnerPresence(present=False, at_s=clock.now))) == 1
    for _ in range(20):
        clock.advance(1.0)
        assert watcher.observe(OwnerPresence(present=False, at_s=clock.now)) == ()
    # Back, and gone again: a second departure is a second goodbye.
    clock.advance(1.0)
    watcher.observe(OwnerPresence(present=True, at_s=clock.now))
    clock.advance(1.0)
    watcher.observe(OwnerPresence(present=False, at_s=clock.now))
    clock.advance(10.0)
    assert len(watcher.observe(OwnerPresence(present=False, at_s=clock.now))) == 1
    assert watcher.farewells == 2


def test_a_low_confidence_sighting_is_not_a_presence() -> None:
    clock = _Clock()
    watcher = _farewell(clock, farewell_after_s=5.0)
    watcher.observe(OwnerPresence(present=True, at_s=clock.now, confidence=0.1))
    clock.advance(30.0)
    assert watcher.observe(OwnerPresence(present=False, at_s=clock.now)) == ()
    assert watcher.farewells == 0


def test_the_farewell_can_be_turned_off_on_its_own() -> None:
    clock = _Clock()
    watcher = _farewell(clock, farewell=False, farewell_after_s=1.0)
    watcher.observe(OwnerPresence(present=True, at_s=clock.now))
    clock.advance(1.0)
    watcher.observe(OwnerPresence(present=False, at_s=clock.now))
    clock.advance(30.0)
    assert watcher.observe(OwnerPresence(present=False, at_s=clock.now)) == ()


# ===========================================================================
# 4c. the config block
# ===========================================================================


def test_a_config_written_before_this_card_is_unchanged_by_it() -> None:
    """No ``curiosity:`` key ⇒ off, and every other value at its default."""

    whisperer = whisperer_config_from_mapping({"max_updates_per_minute": 3})
    assert whisperer.curiosity == CuriosityConfig()
    assert whisperer.curiosity.enabled is False
    assert whisperer.max_updates_per_minute == 3


def test_an_unknown_curiosity_key_is_a_refusal() -> None:
    with pytest.raises(RealtimeConfigError) as error:
        curiosity_config_from_mapping({"mean_gap_seconds": 60})
    assert "mean_gap_seconds" in str(error.value)


def test_a_zero_mean_gap_is_refused_and_points_at_the_visible_off_switch() -> None:
    with pytest.raises(RealtimeConfigError) as error:
        curiosity_config_from_mapping({"mean_gap_s": 0.0})
    assert "enabled: false" in str(error.value)


def test_a_non_finite_number_is_refused() -> None:
    with pytest.raises(RealtimeConfigError):
        curiosity_config_from_mapping({"mean_gap_s": float("inf")})


def test_the_allowed_key_set_and_the_dataclass_agree() -> None:
    """A key nothing reads looks exactly like a switch nobody flipped."""

    assert CURIOSITY_ALLOWED_KEYS == set(CuriosityConfig().as_dict())


def test_the_prototype_overlay_turns_curiosity_on() -> None:
    import yaml

    from parcel_robot.realtime.config import realtime_config_from_mapping

    raw = yaml.safe_load(
        (REPO / "configs" / "realtime.prototype.yaml.example").read_text(
            encoding="utf-8"
        )
    )
    assert realtime_config_from_mapping(raw).whisperer.curiosity.enabled is True

    shipped = yaml.safe_load(
        (REPO / "configs" / "realtime.yaml.example").read_text(encoding="utf-8")
    )
    assert realtime_config_from_mapping(shipped).whisperer.curiosity.enabled is False


# ===========================================================================
# 5. the product path: a real runtime, a real map
# ===========================================================================


class _Backend:
    """One clock for the backend and the runtime.

    ``owner_presence_sample`` refuses a STALE observation, which is right and is
    P2-B's confidence-1.0 guard doing its job — so a rig whose backend stamps
    ``time.monotonic()`` while the runtime is driven on a frozen clock would
    report the owner permanently absent and prove nothing about presence.
    """

    name = BACKEND_NAME

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self.owner_visible = True

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=self._clock.now,
            robot=RobotPose(x=0.0),
            owner=OwnerTrack(
                x=2.0,
                y=0.0,
                visible=self.owner_visible,
                confidence=0.95 if self.owner_visible else 0.0,
            ),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
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
        del tools, context, transcript
        return AgentDecision("Understood.")


class _FakeLane:
    """The lane members the curiosity feed reads, plus a call log.

    ``idle_seconds`` is the lane's own answer to "can you take a narration" —
    ``None`` for exactly the four states ``narrate_event`` refuses — so this
    double carries it rather than re-implementing the rule.
    """

    def __init__(self) -> None:
        self.active = True
        self.recovering = False
        self.playback_owned = False
        self.busy = False
        #: The monthly-ceiling arm: the real lane's floor gate refuses a
        #: non-critical narration once ``monthly_budget_usd`` is reached.
        self.refuse_narration = False
        self.text_turns = 0
        self.narrated: list[str] = []
        self.narrated_while_busy: list[str] = []
        usage_rows: tuple = ()
        self.usage_rows = usage_rows

    def narrate_event(self, text: str, *, critical: bool = False) -> bool:
        del critical
        if self.refuse_narration:
            return False
        if self.busy:
            # The REAL lane's floor gate refuses here; this double records the
            # attempt so a test can assert it never happens rather than merely
            # that it was refused.
            self.narrated_while_busy.append(text)
            return False
        self.narrated.append(text)
        return True

    def snapshot(self) -> dict[str, object]:
        return {
            "active": self.active,
            "narrations": len(self.narrated),
            "idle_seconds": None if self.busy else 30.0,
            "voice_turn_owed": self.busy,
            "text_turns": self.text_turns,
            "voice_turns_owed": 0,
        }

    def close(self) -> None:
        return None


def _obs(
    label: str,
    *,
    x: float,
    y: float = 0.0,
    frame_id: str = "f1",
    visit_id: str = "v1",
    wall_s: float = 100.0,
    score: float = 0.6,
) -> MapObservation:
    """A lamppost-shaped detection. The extents matter: C-2's hygiene gate
    refuses a class-implausible size, and an observation it refuses never
    becomes an entry, so a rig with decorative dimensions measures nothing."""
    return MapObservation(
        label=label,
        score=score,
        surface_x=x,
        surface_y=y,
        surface_z=1.2,
        range_m=4.0,
        bearing_rad=0.0,
        depth_m=4.0,
        extent_w_m=0.2,
        extent_h_m=3.0,
        inlier_pixels=900,
        frame_id=frame_id,
        visit_id=visit_id,
        observed_wall_s=wall_s,
        robot_x=0.0,
        robot_y=0.0,
        provenance=PROV,
    )


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    monkeypatch.delenv("PARCEL_CURIOSITY_SEED", raising=False)
    path = tmp_path / "curio1.yaml"
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
    session = RobotRuntime(
        path,
        _Backend(_Clock()),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="curio1 fixture",
        ),
    )
    session._observation = session.backend.observe()
    try:
        yield session
    finally:
        session.close()


def _wire(
    runtime: RobotRuntime, *, curiosity: dict | None = None, **whisperer
) -> tuple[_FakeLane, _Clock, OnlineSemanticMap]:
    """A lane, a frozen clock, a real map, and the curiosity block turned on."""

    settings: dict[str, object] = {
        "enabled": True,
        "min_gap_floor_s": 0.0,
        # The stimulus floor is off in the rig unless a test is ABOUT it: these
        # tests measure what the dog says, and a 25 s wall in front of every
        # assertion would measure the clock instead.
        "stimulus_min_gap_s": 0.0,
    }
    settings.update(curiosity or {})
    block = CuriosityConfig(**settings)  # type: ignore[arg-type]
    whisperer_settings: dict[str, object] = {
        "min_gap_s": 0.0,
        "max_updates_per_minute": 6,
    }
    whisperer_settings.update(whisperer)
    config = WhispererConfig(
        curiosity=block,
        owner_events=OwnerEventsConfig(enabled=False, min_confidence=0.3),
        **whisperer_settings,  # type: ignore[arg-type]
    )
    import dataclasses

    runtime.realtime_config = dataclasses.replace(
        runtime.realtime_config, whisperer=config
    )
    clock = _Clock(start=runtime._observation.timestamp)
    runtime.backend._clock = clock
    lane = _FakeLane()
    runtime.realtime_lane = lane  # type: ignore[assignment]
    runtime.realtime_whisperer = Whisperer(config=config, clock=clock)
    learned = OnlineSemanticMap(provenance=PROV)
    runtime._p1b_learned_map = learned
    return lane, clock, learned


def _tick(runtime: RobotRuntime, clock: _Clock, seconds: float = 1.0) -> None:
    clock.advance(seconds)
    runtime._observation = runtime.backend.observe()
    runtime._step_curiosity(runtime._observation, clock.now)


def _pin_gap(runtime: RobotRuntime, gap: float = 10_000.0) -> None:
    """Pin the IDLE (Poisson) gap and the time band. Deterministic, no sleeping.

    The default is "never": most tests here are about stimulus remarks, and idle
    chatter arriving in the middle of one would be a second sentence nobody
    asked the rig for. Tests that are about idle chatter pass a small number.
    """

    runtime._curiosity_layer()
    runtime._curio_scheduler._rng = _Gaps(gap)
    runtime._curio_scheduler._next_gap_s = gap
    runtime._curio_scheduler._time_band = lambda: TIME_BAND_AFTERNOON


def test_the_feed_is_inert_until_the_block_is_enabled(runtime: RobotRuntime) -> None:
    """Flag off is "nothing new exists", not "something inert"."""

    lane, clock, learned = _wire(runtime, curiosity={"enabled": False})
    learned.observe(_obs("lamppost", x=3.0))
    for _ in range(10):
        _tick(runtime, clock)
    assert lane.narrated == []
    assert runtime.curiosity_snapshot() is None


def test_the_runtime_remarks_on_a_thing_it_has_just_seen(
    runtime: RobotRuntime,
) -> None:
    """The product path, end to end: map grows, dog speaks, once."""

    lane, clock, learned = _wire(runtime)
    _pin_gap(runtime)
    _tick(runtime, clock)  # baseline: the map is empty
    learned.observe(_obs("lamppost", x=3.0))
    _tick(runtime, clock)
    assert len(lane.narrated) == 1
    assert "lamppost" in lane.narrated[0]
    assert "lamppost" in learned.known_places()
    # And it does not say it again.
    for _ in range(10):
        _tick(runtime, clock)
    assert len(lane.narrated) == 1


def test_the_first_scan_is_a_baseline_not_a_discovery(runtime: RobotRuntime) -> None:
    """A map reloaded from yesterday is not news; announcing it would be."""

    lane, clock, learned = _wire(runtime)
    for index in range(6):
        learned.observe(_obs(f"thing-{index}", x=3.0 + index * 4.0))
    _pin_gap(runtime)
    for _ in range(20):
        _tick(runtime, clock)
    assert lane.narrated == []
    assert runtime._curio_counts.get("baseline_entries") == 6


def test_the_runtime_never_names_a_place_the_map_has_not_admitted(
    runtime: RobotRuntime,
) -> None:
    """SEED A — the card's hard row, on the product path.

    The map is given an entry whose only extra name is a ``vlm_proposed``
    hypothesis. The DETECTOR label may be spoken; the guess may not, ever.
    """

    lane, clock, learned = _wire(runtime)
    _pin_gap(runtime)
    _tick(runtime, clock)
    learned.observe(_obs("bollard", x=3.0))
    entry = learned.active_entries()[0]
    entry.names = (
        *entry.names,
        ProposedName(text="yellow cylinder", provenance=NAME_VLM_PROPOSED, visits=2),
    )
    for _ in range(20):
        _tick(runtime, clock)
    assert lane.narrated, "the detector label is sayable and was not said"
    spoken = " ".join(lane.narrated)
    assert "yellow cylinder" not in spoken
    admitted = runtime._curiosity_admitted_names()
    assert "yellow cylinder" not in admitted
    assert "bollard" in admitted


def test_an_admissible_vlm_name_is_still_refused_by_this_card(
    runtime: RobotRuntime,
) -> None:
    """SEED A's second half: the gate does not lean on another module's filter.

    ``known_places()`` already drops un-promoted guesses. If some future change
    makes one admissible, the dog must go quiet about it rather than start
    naming it — so the provenance test is asserted directly, against a name
    that IS in ``known_places()``.
    """

    _lane, _clock, learned = _wire(runtime)
    learned.observe(_obs("bollard", x=3.0))
    entry = learned.active_entries()[0]

    class _AdmissibleGuess(ProposedName):
        @property
        def admissible(self) -> bool:
            return True

    entry.names = (
        *entry.names,
        _AdmissibleGuess(
            text="yellow cylinder", provenance=NAME_VLM_PROPOSED, visits=1
        ),
    )
    assert "yellow cylinder" in learned.known_places()
    assert "yellow cylinder" not in runtime._curiosity_admitted_names()


def test_a_remark_never_lands_while_the_owner_is_owed_an_answer(
    runtime: RobotRuntime,
) -> None:
    """SEED B, on the product path. Nothing is even attempted."""

    lane, clock, learned = _wire(runtime)
    _pin_gap(runtime)
    _tick(runtime, clock)
    lane.busy = True
    for index in range(30):
        learned.observe(_obs(f"thing-{index}", x=3.0 + index * 4.0))
        _tick(runtime, clock)
    assert lane.narrated == []
    assert lane.narrated_while_busy == [], "a remark reached a busy lane"
    assert runtime._curio_scheduler.skips.get(CHATTER_SKIP_LANE_BUSY, 0) > 0
    # And when the owner is done, the queued observation is still there.
    lane.busy = False
    _tick(runtime, clock)
    assert len(lane.narrated) == 1


def test_a_remark_the_cap_refused_becomes_a_free_gesture(
    runtime: RobotRuntime,
) -> None:
    """Work item 3. The budget is a knob, not a mute button."""

    lane, clock, learned = _wire(runtime, max_updates_per_minute=1)
    _pin_gap(runtime)
    _tick(runtime, clock)
    for index in range(8):
        learned.observe(_obs(f"thing-{index}", x=3.0 + index * 4.0))
        _tick(runtime, clock)
    assert len(lane.narrated) == 1, "the cap did not bind"
    counts = runtime._curio_counts
    assert counts.get(f"suppressed_{RULE_BUDGET}", 0) > 0
    assert counts.get("gestures", 0) > 0, "the free variant never ran"


def test_the_owner_leaving_is_narrated_once(runtime: RobotRuntime) -> None:
    lane, clock, _learned = _wire(runtime, curiosity={"farewell_after_s": 5.0})
    _pin_gap(runtime)  # no idle chatter; the map is empty anyway
    _tick(runtime, clock)
    runtime.backend.owner_visible = False
    for _ in range(20):
        _tick(runtime, clock)
    farewells = [text for text in lane.narrated if "gone out of view" in text]
    assert len(farewells) == 1


def test_a_curiosity_tick_can_never_stop_the_control_loop(
    runtime: RobotRuntime,
) -> None:
    """A dog with nothing to say must not be able to take the robot with it."""

    lane, clock, _learned = _wire(runtime)
    _pin_gap(runtime)

    class _Exploding:
        store = None

        def known_places(self):
            raise RuntimeError("the map is on fire")

        def active_entries(self):
            raise RuntimeError("the map is on fire")

        def entries(self):
            return ()

        def __len__(self) -> int:
            return 0

        def close(self) -> None:
            return None

    runtime._p1b_learned_map = _Exploding()
    for _ in range(5):
        _tick(runtime, clock)
    assert runtime._curio_counts.get("tick_failed", 0) == 5
    assert lane.narrated == []


def test_the_snapshot_publishes_what_the_dog_did_and_did_not_say(
    runtime: RobotRuntime,
) -> None:
    lane, clock, learned = _wire(runtime)
    _pin_gap(runtime)
    _tick(runtime, clock)
    learned.observe(_obs("lamppost", x=3.0))
    _tick(runtime, clock)
    snapshot = runtime.curiosity_snapshot()
    assert snapshot is not None
    assert snapshot["counts"].get("narrated") == 1
    assert snapshot["scheduler"]["remarks"] == 1
    assert snapshot["farewell"]["farewells"] == 0
    assert len(lane.narrated) == 1


def test_an_ask_verdict_from_the_map_becomes_an_ask_about_remark(
    runtime: RobotRuntime,
) -> None:
    """Card P1-D's ASK outcome, consumed through the map's PUBLIC verdict.

    Not a re-implementation of the abstention gate and deliberately not a second
    copy of its thresholds: whatever ``OnlineSemanticMap.resolve`` returns is
    what this reads. The stub here supplies the verdict rather than tuning a
    policy into producing one, so the test is about the CONSUMPTION and stays
    true when P1-D's thresholds move.
    """

    from parcel_robot.perception_abstention import OUTCOME_ASK

    lane, clock, _learned = _wire(runtime)

    class _Verdict:
        outcome = OUTCOME_ASK
        # THE REAL FIELD. ``AbstentionVerdict.candidate`` — card P1-D's "the
        # place an ASK is asking ABOUT". The first pass stubbed a field called
        # ``ask_place`` that the dataclass does not have, so the stub agreed
        # with the code and both disagreed with the product.
        #
        # It deliberately DIFFERS from the label the resolve was asked about
        # ("bench" sorts first), so a build that spoke the query instead of the
        # verdict's own candidate is visible here rather than hidden behind two
        # strings that happen to match.
        candidate = "lamppost"

    class _Result:
        verdict = _Verdict()

    class _AskingMap:
        store = None

        def known_places(self):
            return ("bench", "lamppost")

        def active_entries(self):
            return ()

        def entries(self):
            return ()

        def resolve(self, query, **kwargs):
            del query, kwargs
            return _Result()

        def __len__(self) -> int:
            return 0

        def close(self) -> None:
            return None

    runtime._p1b_learned_map = _AskingMap()
    _pin_gap(runtime)
    _tick(runtime, clock)
    _tick(runtime, clock)
    assert len(lane.narrated) == 1
    assert "lamppost" in lane.narrated[0]
    assert "bench" not in lane.narrated[0], "it spoke the query, not the candidate"
    assert "NOT sure" in lane.narrated[0]
    rows = [
        row
        for row in runtime.realtime_whisperer.decision_rows()
        if row["kind"] == KIND_ASK_ABOUT
    ]
    assert rows and rows[0]["forwarded"] is True


def test_an_ask_verdict_naming_an_unadmitted_place_is_dropped(
    runtime: RobotRuntime,
) -> None:
    """The hard row again, at the one seam that does not come from the scan."""

    from parcel_robot.perception_abstention import OUTCOME_ASK

    lane, clock, _learned = _wire(runtime)

    class _Verdict:
        outcome = OUTCOME_ASK
        candidate = "a thing nobody admitted"  # ...and the query is admitted

    class _Result:
        verdict = _Verdict()

    class _AskingMap:
        store = None

        def known_places(self):
            return ("lamppost",)

        def active_entries(self):
            return ()

        def entries(self):
            return ()

        def resolve(self, query, **kwargs):
            del query, kwargs
            return _Result()

        def __len__(self) -> int:
            return 0

        def close(self) -> None:
            return None

    runtime._p1b_learned_map = _AskingMap()
    _pin_gap(runtime)
    for _ in range(5):
        _tick(runtime, clock)
    assert lane.narrated == []
    assert runtime._curio_counts.get("dropped_unadmitted", 0) > 0


# ---------------------------------------------------------------------------
# 5b. correction pass: the two feed branches that had no product-path test
# ---------------------------------------------------------------------------


def test_a_place_that_decays_out_of_the_map_is_a_scene_change(
    runtime: RobotRuntime,
) -> None:
    """The world moved. Driven through the REAL map, not a stub.

    The scan's `scene_change` branch had zero coverage in the first pass — the
    verifier drove it by hand and it behaved, which is not the same as a test.
    Two entries share the label so the LABEL survives the decay of one of them,
    which is the only case this card may speak about (see the sibling below).
    """

    lane, clock, learned = _wire(runtime)
    _pin_gap(runtime)
    learned.observe(_obs("lamppost", x=3.0, frame_id="f1"))
    learned.observe(_obs("lamppost", x=40.0, frame_id="f2"))
    assert len({e.entry_id for e in learned.active_entries()}) == 2
    _tick(runtime, clock)  # baseline: both entries are already known
    assert lane.narrated == []

    learned.active_entries()[0].mark_decayed(200.0, "test")
    assert "lamppost" in learned.known_places()  # the sibling still carries it
    _tick(runtime, clock)

    assert len(lane.narrated) == 1
    assert "lamppost" in lane.narrated[0]
    rows = [
        row
        for row in runtime.realtime_whisperer.decision_rows()
        if row["kind"] == KIND_SCENE_CHANGE and row["forwarded"]
    ]
    assert [row["key"] for row in rows] == ["scene_change:lamppost"]


def test_a_place_whose_label_leaves_the_vocabulary_is_dropped_not_guessed_at(
    runtime: RobotRuntime,
) -> None:
    """SEED E. The hard row, on the branch where it is easiest to get wrong.

    When the LAST entry carrying a label decays, the label leaves
    ``known_places()`` with it — so there is no admitted name for the thing that
    changed, and the honest move is silence. Saying "something I used to know
    about is gone" without being able to name it would be a sentence the model
    fills in.
    """

    lane, clock, learned = _wire(runtime)
    _pin_gap(runtime)
    learned.observe(_obs("lamppost", x=3.0))
    _tick(runtime, clock)
    assert lane.narrated == []

    learned.active_entries()[0].mark_decayed(200.0, "test")
    assert "lamppost" not in learned.known_places()
    for _ in range(5):
        _tick(runtime, clock)

    assert lane.narrated == []
    assert runtime._curio_counts.get("dropped_unadmitted", 0) >= 1


def test_a_promoted_name_entering_the_vocabulary_is_a_place_learned(
    runtime: RobotRuntime,
) -> None:
    """The dog works out what a thing is CALLED. Also driven through the map."""

    lane, clock, learned = _wire(runtime)
    _pin_gap(runtime)
    learned.observe(_obs("lamppost", x=3.0))
    _tick(runtime, clock)  # baseline: the lamppost is already known
    assert lane.narrated == []

    entry = learned.active_entries()[0]
    entry.names = (
        *entry.names,
        ProposedName(text="the front step", provenance=NAME_PROMOTED, visits=3),
    )
    assert "the front step" in learned.known_places()
    _tick(runtime, clock)

    assert len(lane.narrated) == 1
    assert "the front step" in lane.narrated[0]
    # And the article is not doubled — the map's vocabulary is free to contain a
    # name that already starts with one.
    assert "the the front step" not in lane.narrated[0]
    rows = [
        row
        for row in runtime.realtime_whisperer.decision_rows()
        if row["kind"] == KIND_PLACE_LEARNED and row["forwarded"]
    ]
    assert [row["key"] for row in rows] == ["place_learned:the front step"]


def test_a_vlm_proposed_name_is_never_a_place_learned(
    runtime: RobotRuntime,
) -> None:
    """SEED F. The same branch, attacked from the naming side."""

    lane, clock, learned = _wire(runtime)
    _pin_gap(runtime)
    learned.observe(_obs("lamppost", x=3.0))
    _tick(runtime, clock)

    entry = learned.active_entries()[0]
    entry.names = (
        *entry.names,
        ProposedName(text="yellow cylinder", provenance=NAME_VLM_PROPOSED, visits=2),
    )
    for _ in range(5):
        _tick(runtime, clock)

    assert lane.narrated == []
    assert "yellow cylinder" not in runtime._curiosity_admitted_names()


def test_an_owner_turn_starts_the_quiet_window_over_on_the_product_path(
    runtime: RobotRuntime,
) -> None:
    """SEED G. The POLLED conversation clock, which no roam exercised.

    ``_curiosity_note_owner_turn`` reads the lane's own owner-turn counters
    rather than being wired into P2-B's ``note_realtime_turn`` (which counts
    both sides). Incrementing ``text_turns`` between two ticks is what an owner
    typing looks like from here.
    """

    lane, clock, learned = _wire(runtime, curiosity={"quiet_s": 90.0})
    _pin_gap(runtime)
    _tick(runtime, clock)
    learned.observe(_obs("lamppost", x=3.0))

    lane.text_turns += 1  # the owner said something
    _tick(runtime, clock)
    assert lane.narrated == []
    assert runtime._curio_scheduler.skips.get(CHATTER_SKIP_CONVERSATION, 0) >= 1

    # ...and the dog waits out the quiet window rather than forgetting about it.
    for _ in range(80):
        _tick(runtime, clock)
    assert lane.narrated == []
    for _ in range(20):
        _tick(runtime, clock)
    assert len(lane.narrated) == 1


def test_the_stimulus_floor_paces_event_driven_remarks(
    runtime: RobotRuntime,
) -> None:
    """SEED H. Ruling 6's fast cadence, on the product path."""

    lane, clock, learned = _wire(
        runtime, curiosity={"stimulus_min_gap_s": 25.0, "mean_gap_s": 3600.0}
    )
    _pin_gap(runtime)
    _tick(runtime, clock)
    for index in range(8):
        learned.observe(_obs(f"thing-{index}", x=6.0 + index * 6.0))

    for _ in range(24):
        _tick(runtime, clock)
    assert lane.narrated == [], "the stimulus floor did not hold"
    assert runtime._curio_scheduler.skips.get(CHATTER_SKIP_STIMULUS_GAP, 0) >= 20

    _tick(runtime, clock)
    assert len(lane.narrated) == 1
    for _ in range(24):
        _tick(runtime, clock)
    assert len(lane.narrated) == 1
    _tick(runtime, clock)
    assert len(lane.narrated) == 2


def test_idle_chatter_runs_on_the_slow_clock_and_names_an_admitted_place(
    runtime: RobotRuntime,
) -> None:
    """Ruling 6's slow cadence: something to say when nothing has happened."""

    lane, clock, learned = _wire(runtime, curiosity={"stimulus_min_gap_s": 0.0})
    learned.observe(_obs("lamppost", x=3.0))
    _pin_gap(runtime, 40.0)
    _tick(runtime, clock)  # baseline; nothing is new from here on

    for _ in range(38):
        _tick(runtime, clock)
    assert lane.narrated == [], "idle chatter fired inside its own gap"
    assert runtime._curio_scheduler.skips.get(CHATTER_SKIP_GAP_HOLDING, 0) >= 30

    for _ in range(3):
        _tick(runtime, clock)
    assert len(lane.narrated) == 1
    assert "lamppost" in lane.narrated[0]
    rows = [
        row
        for row in runtime.realtime_whisperer.decision_rows()
        if row["kind"] == KIND_IDLE_REMARK and row["forwarded"]
    ]
    assert rows and rows[0]["key"] == "idle_remark:lamppost"


def test_a_refused_offer_is_not_retried_every_second(
    runtime: RobotRuntime,
) -> None:
    """Correction-pass note: the decision log is not a per-tick log.

    With the monthly ceiling closed the lane refuses every narration. The dog
    must stop asking rather than fill the decision ring with one suppression a
    second.
    """

    lane, clock, learned = _wire(
        runtime, curiosity={"stimulus_min_gap_s": 10.0, "mean_gap_s": 3600.0}
    )
    _pin_gap(runtime)
    _tick(runtime, clock)
    learned.observe(_obs("lamppost", x=3.0))
    lane.refuse_narration = True

    for _ in range(40):
        _tick(runtime, clock)

    attempts = [
        row
        for row in runtime.realtime_whisperer.decision_rows()
        if row["kind"] in CURIOSITY_KINDS
    ]
    assert lane.narrated == []
    assert runtime._curio_scheduler.refusals >= 1
    assert len(attempts) <= 12, f"{len(attempts)} offers in 40 ticks is a retry storm"
