"""Card R16 — an idle lane hangs up.

THE INCIDENT THIS FILE EXISTS BECAUSE OF
----------------------------------------
Owner session 1 ended at 14:14 on 2026-08-20. Everybody went to bed. The lane
did not: `evals/20260820/owner_session_1/ledger.json` rows 2669-2682 are seven
`[session rollover]` pairs between 06:23 and 12:23 the next morning — a fresh
provider session every hour, each one re-sending the instructions and replaying
the memory tail, with **not one word of conversation between them**. Nothing in
the product had an opinion about a session nobody is talking to, because a
rollover renews whatever it finds.

WHAT IS PINNED HERE
-------------------
* **Idle is stated in conversation, not in packets.** Four things reset the
  clock — the owner types, the provider's VAD hears them start or stop speaking,
  the model takes a narration, a response completes — and a fifth thing
  deliberately does NOT: microphone frames. An armed mic in an empty room bills
  forever, so "the mic is on" must not read as "someone is talking to me".
* **A session with work in flight is never idle.** Playing, a `response.create`
  outstanding (R6), a spoken turn owed (R8) — each of those is a `None` from
  `_idle_seconds`, because hanging up there would throw away a turn the repay
  path can only rescue on a RECONNECT.
* **The rollover is checked second.** An idle session at its 60-minute cap hangs
  up instead of renewing. That ordering IS card item 2.
* **A hang-up stays hung up.** The deaf-lane arm of `tick` must not resurrect
  it, and the whisperer must not re-open it — a narration into a closed lane is
  a skip, counted twice, and the fact it carried still lives in the mission log
  and the local event ring, which are upstream of the lane entirely.
* **The next gesture re-opens exactly like a fresh session**: new session id,
  instructions, memory tail, a driver pumping again.

Every clock here is hand-advanced. Nothing sleeps, nothing bills, no socket
leaves the process.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.memory.conversation import ConversationMemory
from parcel_robot.models import VelocityCommand
from parcel_robot.realtime.audio_gateway import BrowserAudioGateway
from parcel_robot.realtime.browser_sink import DiscardSink
from parcel_robot.realtime.config import (
    ALLOWED_KEYS,
    REALTIME_CONFIG_ENV,
    RealtimeConfig,
    RealtimeConfigError,
    load_realtime_config,
    realtime_config_from_mapping,
)
from parcel_robot.realtime.driver import DEFAULT_STOP_REASONS, RealtimeDriver
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    audio_delta,
    audio_done,
    handshake,
    happy_turn,
    input_transcript,
    pcm_tone,
    response_done,
    silent_stall,
    speech_started,
    speech_stopped,
    transcript_done,
)
from parcel_robot.realtime.lane import (
    IDLE_LEDGER_PREFIX,
    REASON_IDLE_HANG_UP,
    RealtimeLane,
)
from parcel_robot.realtime.transport import transport_pair
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r16-idle"
TOKEN = "panel-token-r16"

#: Short enough to advance by hand, long enough that nothing in a scripted turn
#: trips it by accident.
IDLE_S = 600.0


class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Rig:
    """A lane, a hand-advanced clock, and a fresh fake server per connection."""

    def __init__(
        self,
        script: list[Step] | None = None,
        *,
        idle_close_after_s: float = IDLE_S,
        # Both default far out of the way: this file is about ONE timer, and a
        # test that failed because a different one fired first would be telling
        # the reader nothing. The two tests that DO want the rollover or the
        # watchdog name their own number.
        session_max_s: float = 1_000_000.0,
        stall_timeout_s: float = 1_000_000.0,
        ledger: ConversationMemory | None = None,
        memory_tail=None,
        on_idle_close=None,
    ) -> None:
        self.clock = _Clock()
        self.script = script if script is not None else handshake() + happy_turn()
        self.servers: list[FakeRealtimeServer] = []
        self.ledger = ledger
        counter = {"n": 0}

        def _session_id() -> str:
            counter["n"] += 1
            return f"rt_session_{counter['n']}"

        self.lane = RealtimeLane(
            config=RealtimeConfig(
                enabled=True,
                stall_timeout_s=stall_timeout_s,
                session_max_s=session_max_s,
                idle_close_after_s=idle_close_after_s,
                source="test",
            ),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=DiscardSink(),
            ledger=ledger,
            memory_tail=memory_tail,
            clock=self.clock,
            session_id_factory=_session_id,
            on_idle_close=on_idle_close,
        )

    def _factory(self):
        lane_end, server_end = transport_pair(clock=self.clock)
        self.servers.append(
            FakeRealtimeServer(transport=server_end, script=list(self.script), clock=self.clock)
        )
        return lane_end

    @property
    def server(self) -> FakeRealtimeServer:
        return self.servers[-1]

    def open(self) -> str:
        session = self.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
        self.step()
        return session

    def step(self) -> None:
        self.server.pump()
        self.lane.pump()

    def speak(self, ms: int = 100) -> None:
        self.lane.send_audio(pcm_tone(ms, seed=3))
        self.step()

    def system_rows(self) -> list[str]:
        assert self.ledger is not None
        return [
            str(row["content"])
            for row in self.ledger.realtime_turns()
            if row["speaker"] == "system"
        ]


def _text_turn(
    *, response_id: str = "resp_text", item_id: str = "item_text", reply: str = "Warm and quiet."
) -> list[Step]:
    """A typed turn answered in full: the ``response.create`` path, no audio."""

    return [
        Step(
            "response.create",
            (
                transcript_done(response_id, item_id, reply),
                audio_done(response_id, item_id),
                response_done(response_id),
            ),
            label="text_turn",
        )
    ]


def _emit(rig: _Rig, *frames) -> None:
    """Push server frames straight at the lane, with no script in the way.

    The scripted turns are keyed to client frames; several claims here are about
    what ONE server event does to the idle clock, so they are sent by hand.
    """

    for frame in frames:
        rig.server.transport.send(dict(frame))
    rig.lane.pump()


# ==================================================================== the key
def test_the_idle_window_is_a_config_key_with_a_generous_default() -> None:
    assert "idle_close_after_s" in ALLOWED_KEYS
    assert RealtimeConfig().idle_close_after_s == 600.0
    assert realtime_config_from_mapping({}).idle_close_after_s == 600.0
    assert realtime_config_from_mapping({"idle_close_after_s": 90}).idle_close_after_s == 90.0
    assert RealtimeConfig().as_dict()["idle_close_after_s"] == 600.0


@pytest.mark.parametrize(
    "value",
    [-1, -600.0, "ten minutes", True, None, [600]],
)
def test_an_unreadable_idle_window_is_a_refusal_not_a_default(value: object) -> None:
    """Fail-closed, and in the direction that matters.

    CARD P0-B MOVED ONE VALUE OUT OF THIS LIST. Zero used to be here, refused
    for the reason a whisperer cap of zero is refused: a silent off switch on a
    session that bills by the minute is worse than a loud number. The reasoning
    was right about silence and wrong about zero — a hand-written 0 that
    /api/state echoes and the shipped example documents is not silent, and the
    two bounds that keep an unattended session finite (``session_max_s``,
    ``monthly_budget_usd``) are untouched and still refuse it. See
    ``test_zero_means_never_and_the_lane_stays_open`` below.

    Everything else is still a refusal: negatives, non-numbers, ``.inf``.
    """

    with pytest.raises(RealtimeConfigError) as caught:
        realtime_config_from_mapping({"idle_close_after_s": value})
    assert "idle_close_after_s" in str(caught.value)


def test_zero_means_never_and_the_lane_stays_open() -> None:
    """Card P0-B, deliverable 3 — the prototype's "stay live while I'm around".

    End to end through the real lane rather than through the loader alone,
    because the interesting failure is arithmetic and not validation: the
    comparison this replaced is ``idle_for < idle_close_after_s``, and
    ``idle_for < 0.0`` is false for every duration there is — so a zero that
    fell through to it would hang the session up on its FIRST idle tick, the
    exact opposite of what the operator wrote.
    """

    assert realtime_config_from_mapping({"idle_close_after_s": 0}).idle_close_after_s == 0.0
    assert realtime_config_from_mapping({"idle_close_after_s": 0}).idle_close_enabled is False
    assert RealtimeConfig().idle_close_enabled is True, "the default still hangs up"

    rig = _Rig(idle_close_after_s=0.0, ledger=ConversationMemory(":memory:"))
    rig.open()
    rig.speak()

    # A whole day of silence, sampled the way the driver samples it.
    for _ in range(24):
        rig.clock.advance(3_600.0)
        assert rig.lane.tick() is None

    assert rig.lane.idle_hang_ups == 0
    assert rig.lane.active is True
    assert rig.lane.last_idle_seconds is None
    assert not [row for row in rig.system_rows() if row.startswith(IDLE_LEDGER_PREFIX)]

    # And the default is unchanged in the same rig, one line apart.
    ordinary = _Rig(idle_close_after_s=IDLE_S)
    ordinary.open()
    ordinary.speak()
    ordinary.clock.advance(IDLE_S + 1.0)
    assert ordinary.lane.tick() == REASON_IDLE_HANG_UP
    assert ordinary.lane.idle_hang_ups == 1


def test_the_key_loads_from_a_file_and_a_typo_of_it_still_refuses(tmp_path: Path) -> None:
    good = tmp_path / "realtime.yaml"
    good.write_text("enabled: true\nidle_close_after_s: 45\n", encoding="utf-8")
    assert load_realtime_config(good).idle_close_after_s == 45.0

    typo = tmp_path / "typo.yaml"
    typo.write_text("enabled: true\nidle_close_after_sec: 45\n", encoding="utf-8")
    with pytest.raises(RealtimeConfigError) as caught:
        load_realtime_config(typo)
    assert "idle_close_after_sec" in str(caught.value)
    assert "idle_close_after_s" in str(caught.value), "the refusal names the real key"


def test_the_shipped_example_documents_the_key_and_still_parses() -> None:
    example = REPO / "configs" / "realtime.yaml.example"
    body = example.read_text(encoding="utf-8")
    assert "idle_close_after_s: 600.0" in body
    assert "idle hang-up after" in body, "the example names the ledger row it produces"
    parsed = load_realtime_config(example)
    assert parsed.idle_close_after_s == 600.0
    assert parsed.enabled is True


# ============================================================== the hang-up
def test_a_lane_nobody_talks_to_hangs_up_and_says_so_in_the_ledger() -> None:
    memory = ConversationMemory(":memory:")
    rig = _Rig(ledger=memory)
    session = rig.open()
    rig.speak()  # one real turn, then silence
    assert rig.lane.usage_rows, "the turn must complete before the silence means anything"

    rig.clock.advance(IDLE_S - 1.0)
    assert rig.lane.tick() is None, "one second short of the window is not idle"
    assert rig.lane.active is True

    rig.clock.advance(2.0)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP

    assert rig.lane.active is False, "the socket is closed"
    assert rig.lane.transport is None
    assert rig.lane.idle_hang_ups == 1
    assert rig.lane.last_idle_seconds is not None
    assert rig.lane.last_idle_seconds >= IDLE_S
    assert rig.lane.reconnects == 0, "a hang-up opens nothing"
    assert rig.lane.rollovers == 0
    assert rig.lane.stalls == 0

    rows = rig.system_rows()
    hang_ups = [row for row in rows if row.startswith(IDLE_LEDGER_PREFIX)]
    assert len(hang_ups) == 1, rows
    assert hang_ups[0].startswith("[idle hang-up after 601s]")
    assert "closed rather than renewed" in hang_ups[0]
    # And the row belongs to the session that ended, not to a successor.
    ended = [
        row
        for row in memory.realtime_turns()
        if str(row["content"]).startswith(IDLE_LEDGER_PREFIX)
    ]
    assert ended[0]["session_id"] == session


def test_the_hang_up_stays_hung_up_rather_than_being_reconnected_next_tick() -> None:
    """The deaf-lane arm of ``tick`` must not undo this.

    ``_tick_locked`` reconnects an ARMED lane whose socket has gone (that is how
    a dropped transport is recovered). A hang-up that left ``_opened`` set would
    therefore be reversed 50 ms later by the driver's next step, and the lane
    would go on renewing itself forever with an extra reconnect per cycle —
    strictly worse than the defect this card is fixing.
    """

    rig = _Rig()
    rig.open()
    rig.clock.advance(IDLE_S + 1.0)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP

    for _ in range(5):
        rig.clock.advance(IDLE_S + 1.0)
        assert rig.lane.tick() is None
    assert rig.lane.reconnects == 0
    assert rig.lane.disconnects == 0
    assert rig.lane.idle_hang_ups == 1, "one hang-up per session, not one per tick"
    assert len(rig.servers) == 1, "no second socket was ever opened"


def test_the_runtime_is_told_the_lane_hung_up_and_how_long_it_was_quiet() -> None:
    told: list[float] = []
    rig = _Rig(on_idle_close=told.append)
    rig.open()
    rig.clock.advance(IDLE_S + 4.0)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP
    assert told and told[0] == pytest.approx(IDLE_S + 4.0)


def test_a_raising_idle_hook_cannot_leave_the_lane_half_closed() -> None:
    def _boom(_seconds: float) -> None:
        raise RuntimeError("the browser went away")

    rig = _Rig(on_idle_close=_boom)
    rig.open()
    rig.clock.advance(IDLE_S + 1.0)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP
    assert rig.lane.active is False
    assert any("idle-close hook failed" in note for note in rig.lane.events)


# ================================================== what counts as being used
def test_a_typed_turn_resets_the_idle_clock() -> None:
    rig = _Rig(script=handshake() + _text_turn())
    rig.open()
    rig.clock.advance(IDLE_S - 5.0)
    rig.lane.send_text("still here")
    assert rig.lane._last_activity_at == rig.clock.now, "typing IS being talked to"
    rig.step()
    assert rig.lane.usage_rows, "the turn completed; nothing is outstanding"

    rig.clock.advance(10.0)
    assert rig.lane.tick() is None, "the owner spoke 10s ago, not 600s ago"
    assert rig.lane.idle_hang_ups == 0

    rig.clock.advance(IDLE_S)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP, "and the window still runs out"


def test_the_provider_hearing_the_owner_speak_resets_the_idle_clock() -> None:
    """VAD, not audio frames, is the evidence that a person is there.

    ``speech_started`` alone is asserted because it is the FIRST moment in a
    spoken turn at which anything distinguishes a human from an open microphone.
    A lane that only reset on ``speech_stopped`` would hang up on somebody in the
    middle of a long sentence.
    """

    rig = _Rig(script=handshake() + silent_stall())
    rig.open()
    rig.clock.advance(IDLE_S - 1.0)
    _emit(rig, speech_started(0))
    assert rig.lane._last_activity_at == rig.clock.now, "the first syllable resets the clock"

    rig.clock.advance(IDLE_S - 1.0)
    assert rig.lane.tick() is None, "still mid-sentence, 599s after the last one"
    _emit(rig, speech_stopped(400), input_transcript("item_owner_9", "are you awake"))
    assert rig.lane._voice_turn_owed is True
    assert rig.lane._last_activity_at == rig.clock.now

    # The owed turn is answered, and the window starts again from THERE.
    rig.clock.advance(IDLE_S * 2)
    assert rig.lane.tick() is None, "a turn the provider owes an answer to is never idle"
    _emit(rig, response_done("resp_vad"))
    rig.clock.advance(IDLE_S - 1.0)
    assert rig.lane.tick() is None
    rig.clock.advance(2.0)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP


def test_microphone_frames_alone_do_not_hold_the_lane_open() -> None:
    """The hot-mic case, and the reason the browser's ear is closed on hang-up.

    A page left on "🔴 Listening" streams PCM16 at 24 kHz into a billed session
    for as long as the tab is open, whether or not anyone is in the room. If a
    frame counted as being talked to, this would be the one idle state the card
    could not close — and it is the most expensive one there is.
    """

    rig = _Rig(script=handshake() + silent_stall())
    rig.open()
    for _ in range(12):
        rig.clock.advance(50.0)
        rig.lane.send_audio(pcm_tone(20, seed=7))
        rig.step()
    assert rig.lane._audio_sent_this_session == 12

    assert rig.lane.tick() == REASON_IDLE_HANG_UP
    assert rig.lane.stalls == 0, "this is not a stall; the provider was never late"


def test_a_narration_the_model_took_holds_the_lane_open() -> None:
    """The card's own definition of idle: "no owner turn, no narration…"."""

    rig = _Rig(script=handshake() + _text_turn(reply="I just got back."))
    rig.open()
    rig.clock.advance(IDLE_S - 5.0)
    assert rig.lane.narrate_event("the walk to the sidewalk ended") is True
    assert rig.lane.narrations == 1
    assert rig.lane._last_activity_at == rig.clock.now, "a narration the model took is traffic"

    rig.step()  # the model says its sentence; nothing is outstanding
    rig.clock.advance(10.0)
    assert rig.lane.tick() is None
    assert rig.lane.idle_hang_ups == 0

    rig.clock.advance(IDLE_S)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP, "one narration buys one window, not immunity"


def test_a_narration_the_floor_gate_refused_does_not_hold_the_lane_open() -> None:
    """Nothing went on the wire, so nothing about the session changed."""

    rig = _Rig(script=handshake() + silent_stall(), stall_timeout_s=8.0)
    rig.open()
    rig.lane.send_text("what can you see")  # a response is now outstanding
    rig.step()
    before = rig.lane._last_activity_at
    rig.clock.advance(IDLE_S + 1.0)
    assert rig.lane.narrate_event("a person stepped in front of me") is False
    assert rig.lane.narrations == 0
    assert rig.lane.narrations_skipped == 1
    assert rig.lane._last_activity_at == before, "nothing went up, so nothing happened"

    assert rig.lane.tick() == "stall", "an unanswered turn is the WATCHDOG's business"
    assert rig.lane.idle_hang_ups == 0


# ====================================== a busy session is never an idle one
def test_an_outstanding_response_is_not_idle_however_long_it_takes() -> None:
    """R6's repay path only runs on a reconnect; a hang-up would eat the turn."""

    rig = _Rig(script=handshake() + silent_stall())
    rig.open()
    rig.lane.send_text("tell me about the willow")
    rig.step()
    assert rig.lane._responses_pending == 1

    rig.clock.advance(IDLE_S * 10)
    assert rig.lane.tick() is None
    assert rig.lane.idle_hang_ups == 0
    assert rig.lane.active is True


def test_a_spoken_turn_owed_an_answer_is_not_idle_either() -> None:
    """R8's ``_voice_turn_owed`` — the half ``_responses_pending`` cannot see."""

    rig = _Rig(script=handshake() + silent_stall())
    rig.open()
    _emit(rig, speech_stopped(400))
    assert rig.lane._voice_turn_owed is True
    assert rig.lane._responses_pending == 0, "server VAD creates the response, not us"

    rig.clock.advance(IDLE_S * 10)
    assert rig.lane.tick() is None
    assert rig.lane.idle_hang_ups == 0
    assert rig.lane.voice_turns_owed == 1
    assert rig.lane.voice_turn_repays == 0, "nothing was repaid, because nothing reconnected"


def test_a_reply_the_owner_is_listening_to_is_not_idle() -> None:
    rig = _Rig(
        script=handshake()
        + [
            Step(
                "input_audio_buffer.append",
                (audio_delta("resp_long", "item_long", pcm_tone(300)),),
                label="half_a_reply",
            )
        ]
    )
    rig.open()
    rig.speak()
    assert rig.lane.playback_owned is True

    rig.clock.advance(IDLE_S * 2)
    assert rig.lane.tick() is None, "the robot is speaking; that is not silence"
    assert rig.lane.idle_hang_ups == 0


# ================================================== item 2: the rollover
def test_an_idle_session_at_rollover_time_hangs_up_instead_of_renewing() -> None:
    """CARD ITEM 2, AND THE SEVEN ROWS THE OWNER WOKE UP TO.

    Both timers are due on the same tick. The rollover would close this socket
    and immediately open a paid one, re-send the instructions and replay the
    tail — which is what happened once an hour from 06:23 to 12:23 on
    2026-08-20. Whichever check runs first decides which of those two things the
    product does, and this test is the whole of that decision.
    """

    memory = ConversationMemory(":memory:")
    rig = _Rig(idle_close_after_s=600.0, session_max_s=600.0, ledger=memory)
    rig.open()
    rig.clock.advance(601.0)

    assert rig.lane.tick() == REASON_IDLE_HANG_UP
    assert rig.lane.rollovers == 0, "an idle session has nothing worth renewing"
    assert rig.lane.reconnects == 0
    assert len(rig.servers) == 1, "no second provider session was opened"

    rows = rig.system_rows()
    assert not any("[session rollover]" in row for row in rows), rows
    assert any(row.startswith(IDLE_LEDGER_PREFIX) for row in rows)


def test_a_session_still_being_used_rolls_over_at_the_cap_exactly_as_before() -> None:
    """The other half of item 2: R6/R8 keep their reconnect, and their repay.

    An hour-long conversation that is still going is renewed, not hung up, and
    the turn that was in flight when the cap arrived is still repaid — which is
    the behaviour cards R6 and R8 exist for and which this card must not cost.
    """

    memory = ConversationMemory(":memory:")
    rig = _Rig(
        script=handshake() + silent_stall(),
        idle_close_after_s=600.0,
        session_max_s=600.0,
        stall_timeout_s=10_000.0,
        ledger=memory,
    )
    rig.open()
    rig.clock.advance(599.0)
    _emit(rig, speech_stopped(400))  # the owner speaks just before the cap
    rig.clock.advance(2.0)

    assert rig.lane.tick() == "rollover"
    assert rig.lane.rollovers == 1
    assert rig.lane.idle_hang_ups == 0
    assert rig.lane.turn_repays == 1
    assert rig.lane.voice_turn_repays == 1, "R8's spoken-turn repay survives this card"
    rows = rig.system_rows()
    assert any("[session rollover]" in row for row in rows)
    assert any("[turn repaid]" in row for row in rows)
    assert not any(row.startswith(IDLE_LEDGER_PREFIX) for row in rows)


# ============================== item 3: the whisperer must not keep it alive
def test_a_narration_into_a_hung_up_lane_is_a_skip_and_is_counted_twice() -> None:
    """The whisperer may not re-open a paid session the owner is not part of.

    If it could, the hang-up would last exactly until the robot next noticed
    something about itself — a person walking past, a battery reading — and the
    eight-hour session this file exists for would have carried on renewing under
    a different name. The fact the narration carried is NOT lost: it reached the
    mission log and the event ring before the whisperer ever offered it here,
    and every always-band fact (an emergency stop, a mission terminal, a
    refusal) latches locally whatever the lane is doing.
    """

    rig = _Rig()
    rig.open()
    rig.clock.advance(IDLE_S + 1.0)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP

    for _ in range(3):
        assert rig.lane.narrate_event("a person stepped in front of me") is False

    assert rig.lane.narrations == 0, "nothing went up"
    assert rig.lane.narrations_skipped == 3
    assert rig.lane.narrations_skipped_closed == 3
    assert rig.lane.active is False, "the lane was NOT re-opened"
    assert rig.lane.reconnects == 0
    assert len(rig.servers) == 1
    assert any("closed lane" in note for note in rig.lane.events)
    assert rig.lane.snapshot()["narrations_skipped_closed"] == 3


def test_narrations_before_and_after_a_hang_up_are_told_apart_in_the_snapshot() -> None:
    """``narrations_skipped`` alone cannot answer "is anybody home"."""

    rig = _Rig(script=handshake() + silent_stall())
    rig.open()
    rig.lane.send_text("hello")  # a response is outstanding: the floor is busy
    rig.step()
    assert rig.lane.narrate_event("the battery is low") is False
    assert rig.lane.narrations_skipped == 1
    assert rig.lane.narrations_skipped_closed == 0, "the lane was open; the floor was busy"


# ================================== the re-open, which is the ordinary path
def test_the_next_owner_gesture_opens_a_fresh_session_with_the_same_memory() -> None:
    tail = [
        {"role": "user", "content": "I liked the bench by the water"},
        {"role": "assistant", "content": "The one under the willow."},
    ]
    memory = ConversationMemory(":memory:")
    rig = _Rig(memory_tail=lambda: tail, ledger=memory)
    first = rig.open()
    rig.clock.advance(IDLE_S + 1.0)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP

    second = rig.lane.ensure_session(handshake_token="csrf-token", mic_gesture=True)
    rig.step()

    assert second != first, "a fresh session, not the corpse of the old one"
    assert rig.lane.active is True
    assert len(rig.servers) == 2
    types = rig.servers[-1].received_types()
    assert types[0] == "session.update", "the instructions went up first"
    assert types.count("conversation.item.create") == 2, "the memory tail was replayed"
    assert rig.lane.tail_items_injected == 2
    assert rig.lane.reconnects == 0, "an owner gesture is not a recovery"

    # And the new session gets the whole window rather than inheriting silence.
    rig.clock.advance(IDLE_S - 1.0)
    assert rig.lane.tick() is None
    rig.clock.advance(2.0)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP
    assert rig.lane.idle_hang_ups == 2


def test_a_reconnect_gives_the_new_socket_a_full_idle_window() -> None:
    """A stall recovery must not be hung up on the DEAD session's silence.

    The lane had been quiet for nine seconds short of forever when the socket
    died. If the new one inherited that, a stall at the wrong moment would come
    back as a hang-up on the very next tick and the recovery R4-lite exists for
    would look like the owner being dropped.
    """

    rig = _Rig(script=handshake() + silent_stall(), stall_timeout_s=8.0)
    rig.open()
    rig.clock.advance(IDLE_S - 20.0)
    rig.lane.send_text("are you there")
    rig.step()
    rig.clock.advance(9.0)
    assert rig.lane.tick() == "stall"
    assert rig.lane.reconnects == 1
    assert rig.lane._last_activity_at == rig.clock.now, "the new socket starts its own clock"

    # The repay the reconnect fired is outstanding, so the lane is busy rather
    # than idle; answer it and the fresh window is what remains.
    _emit(rig, response_done("resp_repay"))
    rig.clock.advance(IDLE_S - 1.0)
    assert rig.lane.tick() is None, "the new socket has its own window"
    assert rig.lane.idle_hang_ups == 0
    rig.clock.advance(2.0)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP


def test_the_snapshot_shows_the_window_the_age_and_the_count() -> None:
    rig = _Rig()
    rig.open()
    rig.clock.advance(120.0)
    snapshot = rig.lane.snapshot()
    assert snapshot["idle_close_after_s"] == IDLE_S
    assert snapshot["idle_seconds"] == pytest.approx(120.0)
    assert snapshot["idle_hang_ups"] == 0
    assert snapshot["last_idle_seconds"] is None

    rig.clock.advance(IDLE_S)
    assert rig.lane.tick() == REASON_IDLE_HANG_UP
    closed = rig.lane.snapshot()
    assert closed["idle_hang_ups"] == 1
    assert closed["last_idle_seconds"] == pytest.approx(720.0)
    assert closed["idle_seconds"] is None, "a closed lane has no idle age"
    assert closed["active"] is False


# ================================================================ the driver
class _StubLane:
    """A lane-shaped recorder. The driver may touch exactly these members."""

    def __init__(self, reasons: list[str | None]) -> None:
        self.reasons = reasons
        self.pumps = 0
        self.ticks = 0
        self.active = True

    def pump(self) -> int:
        self.pumps += 1
        return 0

    def tick(self) -> str | None:
        self.ticks += 1
        return self.reasons.pop(0) if self.reasons else None


def test_the_driver_and_the_lane_agree_on_the_word() -> None:
    """One string joins two modules that deliberately do not import each other."""

    assert DEFAULT_STOP_REASONS == frozenset({REASON_IDLE_HANG_UP})


def test_the_driver_stops_pumping_a_lane_that_hung_up() -> None:
    notes: list[str] = []
    lane = _StubLane([None, REASON_IDLE_HANG_UP])
    driver = RealtimeDriver(lane, interval_s=0.001, sleep=time.sleep, on_event=notes.append)
    driver.start()
    try:
        deadline = time.monotonic() + 3.0
        while driver.running and time.monotonic() < deadline:
            time.sleep(0.005)
        assert driver.running is False, "the loop stopped itself"
        settled = driver.steps
        time.sleep(0.05)
        assert driver.steps == settled, "and it really did stop, rather than slowing down"
    finally:
        driver.stop()

    assert driver.stopped_reason == REASON_IDLE_HANG_UP
    assert driver.self_stops == 1
    assert driver.reconnect_reasons == [], "a hang-up is not a reconnect and is not counted as one"
    assert driver.snapshot()["stopped_reason"] == REASON_IDLE_HANG_UP
    assert any("next owner gesture" in note for note in notes)


def test_a_stopping_driver_reports_itself_stopped_so_the_gesture_restarts_it() -> None:
    """The re-open path, from the driver's side.

    ``runtime`` starts the pump with ``if not driver.running: driver.start()``.
    A driver that answered True between "told to stop" and "thread actually
    finished" would leave the freshly re-opened session with nobody pumping it —
    silent, and indistinguishable from a dead provider.
    """

    released = threading.Event()
    lane = _StubLane([REASON_IDLE_HANG_UP])
    # The injected sleep parks the loop until this test lets it go, so "still
    # winding down" is a state the test HOLDS rather than a window it races.
    driver = RealtimeDriver(lane, interval_s=0.001, sleep=lambda _s: released.wait(30.0))
    driver.start()
    try:
        deadline = time.monotonic() + 30.0
        while driver.self_stops < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert driver.self_stops == 1, "the loop never saw the hang-up"
        assert driver.running is False, "told to stop ⇒ not running, even mid-sleep"
        thread = driver._thread
        assert thread is not None and thread.is_alive(), "and it is still winding down"

        # The owner comes back while the old loop is still parked in its sleep.
        lane.reasons = []
        released.set()
        driver.start()
        assert driver.running is True
        assert driver.stopped_reason is None
        assert driver._thread is not thread, "a NEW pump, not the old one revived"
        before = driver.steps
        deadline = time.monotonic() + 30.0
        while driver.steps <= before and time.monotonic() < deadline:
            time.sleep(0.005)
        assert driver.steps > before, "the new pump is turning"
        assert thread.is_alive() is False, "and the old one really did end"
    finally:
        released.set()
        driver.stop()


def test_an_ordinary_reconnect_reason_still_only_gets_a_note() -> None:
    notes: list[str] = []
    lane = _StubLane(["rollover", "stall"])
    driver = RealtimeDriver(lane, on_event=notes.append)
    driver.step()
    driver.step()
    assert driver.reconnect_reasons == ["rollover", "stall"]
    assert driver.stopped_reason is None
    assert driver.self_stops == 0


# ================================================================ the gateway
def test_the_gateway_closes_the_ear_but_stays_armed() -> None:
    """Card item 3, on the object that owns the browser's microphone."""

    seen: list[bool] = []
    gateway = BrowserAudioGateway(on_audio=lambda _pcm: None, on_mic=seen.append)
    gateway.bind_token(TOKEN)
    gateway.start()
    conn = gateway.attach(TOKEN)
    assert gateway.set_mic(conn, True) is True
    assert seen == [True]

    assert gateway.close_mic("the session hung up") is True
    assert gateway.mic_open is False
    assert gateway.running is True, "the gateway stays armed; only the ear closed"
    assert gateway.snapshot()["token_bound"] is True
    assert gateway.snapshot()["mic_closes_by_runtime"] == 1
    assert seen == [True], "the runtime asked for this; it must not be told back"

    # The browser is TOLD, which is what makes its button re-open the session.
    control = [json.loads(f) for f in conn.outbox if isinstance(f, str)]
    off = [body for body in control if body["type"] == "mic" and body["on"] is False]
    assert off and "hung up" in off[-1]["reason"]

    # Idempotent, and the owner's own click still re-arms it.
    assert gateway.close_mic("again") is False
    assert gateway.snapshot()["mic_closes_by_runtime"] == 1
    assert gateway.set_mic(conn, True) is True
    assert seen == [True, True], "the re-arm is a fresh gesture the runtime must see"
    gateway.stop()


def test_closing_the_ear_stops_the_frames_a_hung_up_lane_would_have_dropped() -> None:
    heard: list[bytes] = []
    gateway = BrowserAudioGateway(on_audio=heard.append)
    gateway.bind_token(TOKEN)
    gateway.start()
    conn = gateway.attach(TOKEN)
    gateway.set_mic(conn, True)
    assert gateway.accept_audio(conn, b"\x01\x02" * 64) is True

    gateway.close_mic("idle hang-up")
    assert gateway.accept_audio(conn, b"\x01\x02" * 64) is False
    assert len(heard) == 1
    assert gateway.snapshot()["frames_refused_unarmed"] == 1
    gateway.stop()


# ================================================================ the runtime
class _Backend:
    name = BACKEND_NAME

    def reset(self) -> SimObservation:
        return self.observe()

    def observe(self) -> SimObservation:
        return SimObservation(
            time_s=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
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


def _runtime(tmp_path: Path) -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "r16-idle.yaml"
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
  logging: false
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r16 idle fixture",
        ),
    )


def _script() -> list[Step]:
    return handshake() + [
        Step(
            "response.create",
            (
                transcript_done("resp_1", "item_robot_1", "Warm and quiet."),
                audio_done("resp_1", "item_robot_1"),
                response_done("resp_1"),
            ),
            label="text_turn",
        )
    ]


def test_the_runtime_hangs_up_and_the_owners_next_message_re_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end in ``mode: text``: hang up, type again, keep talking.

    This is the shape the card asks for offline, with the clock injected in place
    of ten real minutes: the lane hangs up on its own, the driver stops, the
    panel's text box re-opens the session exactly as it opens the first one, and
    the pump comes back with it.
    """

    config = tmp_path / "realtime.yaml"
    config.write_text(
        "enabled: true\nmode: text\nidle_close_after_s: 600.0\n", encoding="utf-8"
    )
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        lane = runtime.realtime_lane
        assert lane is not None
        assert runtime.realtime_config.idle_close_after_s == 600.0
        clock = _Clock()
        lane._clock = clock  # the only injection; everything else is the product
        servers: list[FakeRealtimeServer] = []

        def _factory():
            lane_end, server_end = transport_pair(clock=clock)
            servers.append(
                FakeRealtimeServer(transport=server_end, script=_script(), clock=clock)
            )
            return lane_end

        lane._transport_factory = _factory
        runtime.bind_panel_token("csrf-abc")

        runtime.submit_realtime_text("how was your day")
        servers[-1].pump()
        lane.pump()
        first = lane.session_id
        driver = runtime.realtime_driver
        assert driver is not None and driver.running is True

        clock.advance(601.0)
        assert lane.tick() == REASON_IDLE_HANG_UP
        assert lane.active is False
        rows = [
            str(row["content"])
            for row in runtime.agent.memory.realtime_turns()
            if row["speaker"] == "system"
        ]
        assert any(row.startswith(IDLE_LEDGER_PREFIX) for row in rows), rows
        assert any("hung up after" in str(event["text"]) for event in runtime.snapshot()["events"])

        # The owner comes back. Same door as the very first message.
        runtime.submit_realtime_text("still there?")
        servers[-1].pump()
        lane.pump()
        assert lane.active is True
        assert lane.session_id != first
        assert len(servers) == 2
        assert driver.running is True, "the gesture restarted the pump"
        assert lane.snapshot()["idle_hang_ups"] == 1
    finally:
        runtime.close()


def test_the_whisperers_own_door_counts_what_a_hung_up_lane_turned_away(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_narrate_mission`` is the door every robot-initiated fact comes through.

    It refuses on a closed lane — as it must, or the whisperer would be what
    re-opens the session the owner walked away from — but the refusal has to be
    a NUMBER. Otherwise "the robot narrated into a dead session all night" looks
    exactly like "the robot had nothing to say".
    """

    config = tmp_path / "realtime.yaml"
    config.write_text(
        "enabled: true\nmode: text\nidle_close_after_s: 600.0\n", encoding="utf-8"
    )
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        lane = runtime.realtime_lane
        assert lane is not None
        clock = _Clock()
        lane._clock = clock
        servers: list[FakeRealtimeServer] = []

        def _factory():
            lane_end, server_end = transport_pair(clock=clock)
            servers.append(
                FakeRealtimeServer(transport=server_end, script=_script(), clock=clock)
            )
            return lane_end

        lane._transport_factory = _factory
        runtime.bind_panel_token("csrf-abc")
        runtime.submit_realtime_text("hello")
        servers[-1].pump()
        lane.pump()

        clock.advance(601.0)
        assert lane.tick() == REASON_IDLE_HANG_UP

        assert runtime._narrate_mission("a person stepped in front of me") is False
        assert runtime._narrate_mission("the way is clear again") is False
        assert lane.narrations == 0
        assert runtime.realtime_snapshot()["narrations_into_closed_lane"] == 2
        assert lane.active is False, "the whisperer did not re-open the session"
        assert len(servers) == 1
        # And the door does not count an OPEN lane's refusals as hang-ups: those
        # are the floor gate, which is a different question with its own counter.
        runtime.submit_realtime_text("hello again")
        servers[-1].pump()
        lane.pump()
        assert lane.active is True
        assert runtime._narrate_mission("the battery is low") is True
        assert runtime.realtime_snapshot()["narrations_into_closed_lane"] == 2
    finally:
        runtime.close()


def test_audio_mode_puts_the_microphone_button_back_when_the_lane_hangs_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gateway stays armed and idle; the browser's ear does not stay open."""

    config = tmp_path / "realtime.yaml"
    config.write_text(
        "enabled: true\nmode: audio\nidle_close_after_s: 600.0\n", encoding="utf-8"
    )
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        lane = runtime.realtime_lane
        gateway = runtime.realtime_gateway
        assert lane is not None and gateway is not None
        clock = _Clock()
        lane._clock = clock
        servers: list[FakeRealtimeServer] = []

        def _factory():
            lane_end, server_end = transport_pair(clock=clock)
            servers.append(
                FakeRealtimeServer(
                    transport=server_end, script=handshake() + silent_stall(), clock=clock
                )
            )
            return lane_end

        lane._transport_factory = _factory
        runtime.bind_panel_token(TOKEN)

        # The owner's click: the gateway asks the runtime, which opens the lane.
        conn = gateway.attach(TOKEN)
        assert gateway.set_mic(conn, True) is True
        assert lane.active is True
        servers[-1].pump()
        lane.pump()

        # They walk away with the microphone still armed and streaming.
        for _ in range(10):
            clock.advance(61.0)
            gateway.accept_audio(conn, pcm_tone(20, seed=5))
        assert lane.tick() == REASON_IDLE_HANG_UP

        assert gateway.mic_open is False, "the browser is not left saying 'Listening'"
        assert gateway.running is True, "the gateway stays armed for the next click"
        assert gateway.snapshot()["mic_closes_by_runtime"] == 1
        assert gateway.accept_audio(conn, pcm_tone(20, seed=5)) is False

        # One click re-opens, through the same door as the first one.
        assert gateway.set_mic(conn, True) is True
        assert lane.active is True
        assert len(servers) == 2
    finally:
        runtime.close()
