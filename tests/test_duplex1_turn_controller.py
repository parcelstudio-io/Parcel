"""Card DUPLEX-1: the turn state machine itself, and the seams it hangs on.

The rows the card is judged by are in ``test_duplex1_rows.py`` (they run on the
product lane). This file is the unit half: the pure controller, the
interrupt-onset stamp travelling from the lane to the capture index, and the
sinks that must not notice any of it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from parcel_robot.duplex.turn_controller import (
    ACTION_COMMIT,
    ACTION_DUCK,
    ACTION_NONE,
    ACTION_RESUME,
    DEFAULT_DUCK_GAIN,
    STATE_LISTEN,
    STATE_OVERLAP,
    STATE_SPEAK,
    STATE_THINK,
    STATE_YIELD,
    TurnController,
    TurnControllerError,
)
from parcel_robot.realtime.audio_gateway import (
    CAPTURE_INDEX_NAME,
    BrowserAudioGateway,
    SessionAudioCapture,
)
from parcel_robot.realtime.browser_sink import BrowserSink, DiscardSink

FLOOR = 700.0
TOKEN = "panel-token-duplex1-unit"


def _speaking(floor_ms: float = FLOOR) -> TurnController:
    controller = TurnController(floor_ms=floor_ms)
    controller.note_robot_started(0.0)
    return controller


# ================================================================ construction
def test_a_controller_refuses_a_floor_that_cannot_mean_anything() -> None:
    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(TurnControllerError):
            TurnController(floor_ms=bad)
    for bad_gain in (-0.1, 1.5, float("nan")):
        with pytest.raises(TurnControllerError):
            TurnController(duck_gain=bad_gain)


def test_the_default_duck_is_quiet_but_not_silent() -> None:
    """Silence is indistinguishable from a dropped connection.

    A backchannel that resolves inside the floor has to bring the reply back
    without a click and without the owner having wondered whether the socket
    died. The value itself is taste until AIR-1's double-talk leg measures
    ``signal_to_echo_db`` — its handoff says so in as many words.
    """

    assert 0.0 < DEFAULT_DUCK_GAIN < 0.5
    assert TurnController().duck_gain == DEFAULT_DUCK_GAIN


# ============================================================== the transitions
def test_the_five_states_are_reachable_in_the_order_a_conversation_takes() -> None:
    controller = TurnController(floor_ms=FLOOR)
    assert controller.state == STATE_LISTEN

    controller.note_response_requested(0.0)
    assert controller.state == STATE_THINK

    controller.note_robot_started(0.1)
    assert controller.state == STATE_SPEAK

    action = controller.note_owner_started(1.0)
    assert controller.state == STATE_OVERLAP
    assert action.kind == ACTION_DUCK

    assert controller.tick(1.0 + FLOOR / 1000.0).kind == ACTION_COMMIT
    assert controller.state == STATE_YIELD


def test_a_burst_that_ends_inside_the_floor_resumes_and_gives_the_floor_back() -> None:
    controller = _speaking()
    assert controller.note_owner_started(1.0).kind == ACTION_DUCK
    assert controller.ducked is True

    action = controller.note_owner_stopped(1.15)
    assert action.kind == ACTION_RESUME
    assert action.gain == 1.0
    assert controller.state == STATE_SPEAK
    assert controller.ducked is False
    assert controller.backchannels == 1
    assert controller.commits == 0


def test_a_burst_that_outlasts_the_floor_commits_at_the_offset_too() -> None:
    """Not only on the tick: the offset itself can be past the deadline."""

    controller = _speaking()
    controller.note_owner_started(1.0)
    action = controller.note_owner_stopped(1.0 + FLOOR / 1000.0 + 0.2)
    assert action.kind == ACTION_COMMIT
    assert controller.state == STATE_YIELD
    assert controller.backchannels == 0
    assert controller.commits == 1


def test_a_second_vad_start_inside_one_burst_does_not_rearm_the_deadline() -> None:
    """Seed: drop the ``already overlapping`` guard and the floor never expires.

    Server VAD can report a second ``speech_started`` inside one utterance. If
    that reset the deadline, a continuously-talking owner would postpone their
    own interruption forever — the reply would run to the end while they spoke
    over it, which is the failure this whole card exists to remove.
    """

    controller = _speaking()
    controller.note_owner_started(1.0)
    again = controller.note_owner_started(1.4)
    assert again.kind == ACTION_NONE
    assert controller.ducks == 1
    assert controller.tick(1.0 + FLOOR / 1000.0 + 0.01).kind == ACTION_COMMIT


def test_with_the_floor_off_the_barge_in_commits_on_the_frame_and_never_ducks() -> None:
    """R16's behaviour, which is what ships. A duck here would be pure latency."""

    controller = _speaking(floor_ms=0.0)
    action = controller.note_owner_started(1.0)
    assert action.kind == ACTION_COMMIT
    assert controller.ducks == 0
    assert controller.state == STATE_YIELD


def test_a_provider_cancel_during_an_overlap_is_a_commit_not_a_backchannel() -> None:
    """MARK-1's correction pass §2, in the state machine.

    Under the hosted default ``interrupt_response: true`` a genuine
    interruption is resolved by the PROVIDER killing its own reply. Counted as
    "the reply finished", that is a survived backchannel and the owner gets
    talked over by seconds of already-scheduled audio.
    """

    controller = _speaking()
    controller.note_owner_started(1.0)
    action = controller.note_robot_ended(1.2, cancelled=True)
    assert action.kind == ACTION_COMMIT
    assert controller.commits == 1
    assert controller.backchannels == 0
    assert controller.state == STATE_YIELD


def test_a_reply_that_simply_ends_while_ducked_asks_for_the_gain_back() -> None:
    controller = _speaking()
    controller.note_owner_started(1.0)
    action = controller.note_robot_ended(1.2, cancelled=False)
    assert action.kind == ACTION_RESUME
    assert controller.state == STATE_LISTEN
    assert controller.ducked is False


def test_a_new_reply_always_starts_at_unity() -> None:
    """The panel resets its gain on the utterance frame; so must the model of it."""

    controller = _speaking()
    controller.note_owner_started(1.0)
    assert controller.ducked is True
    controller.note_robot_started(2.0)
    assert controller.ducked is False
    assert controller.state == STATE_SPEAK


def test_noise_while_nobody_is_speaking_is_not_an_overlap() -> None:
    controller = TurnController(floor_ms=FLOOR)
    action = controller.note_owner_started(1.0)
    assert action.kind == ACTION_NONE
    assert controller.state == STATE_LISTEN
    assert controller.overlaps == 0
    assert controller.ducks == 0


def test_a_content_word_ends_the_argument_early_when_one_ever_arrives() -> None:
    """The seam with no producer, tested so the answer is defined when there is.

    Nothing in this tree delivers a PARTIAL owner transcript — the hosted lane
    hands over the owner's words after the turn — so this path has no product
    caller today and DUPLEX1_STATUS.md says so rather than counting it as
    wiring.
    """

    controller = _speaking()
    controller.note_owner_started(1.0)
    assert controller.note_owner_words(1.05, "mm hmm yeah").kind == ACTION_NONE
    assert controller.state == STATE_OVERLAP
    action = controller.note_owner_words(1.1, "wait, stop")
    assert action.kind == ACTION_COMMIT
    assert controller.state == STATE_YIELD


# ================================================================= initiative
def test_initiative_is_allowed_only_from_an_idle_listen() -> None:
    controller = TurnController(floor_ms=FLOOR)
    assert controller.initiative_allowed is True

    controller.note_response_requested(0.0)
    assert controller.initiative_allowed is False  # THINK: the answer is coming

    controller.note_robot_started(0.1)
    assert controller.initiative_allowed is False  # SPEAK

    controller.note_owner_started(1.0)
    assert controller.initiative_allowed is False  # OVERLAP

    controller.tick(1.0 + FLOOR / 1000.0)
    assert controller.initiative_allowed is False  # YIELD: the floor is theirs

    controller.note_robot_ended(3.0)
    assert controller.initiative_allowed is True


def test_an_owed_turn_refuses_initiative_even_from_listen() -> None:
    """A remark about the weather while the owner waits for an answer."""

    controller = TurnController(floor_ms=FLOOR)
    controller.note_turn_owed(1.0)
    assert controller.state == STATE_LISTEN
    assert controller.initiative_allowed is False
    controller.note_turn_answered(2.0)
    assert controller.initiative_allowed is True


def test_the_gate_counts_both_answers_so_never_asked_is_visible() -> None:
    """A gate nobody consults and a gate that always says yes look the same."""

    controller = TurnController(floor_ms=FLOOR)
    assert controller.snapshot()["initiative_grants"] == 0
    assert controller.snapshot()["initiative_refusals"] == 0

    # Correction pass: the PURE read must move nothing, however often it is
    # sampled — the counters D-4 is scored from used to be evidence about how
    # many times a test looked at them.
    for _ in range(5):
        assert controller.initiative_allowed is True
    assert controller.snapshot()["initiative_grants"] == 0
    assert controller.snapshot()["initiative_refusals"] == 0

    assert controller.consult_initiative() is True
    controller.note_robot_started(0.0)
    assert controller.consult_initiative() is False
    assert controller.snapshot()["initiative_grants"] == 1
    assert controller.snapshot()["initiative_refusals"] == 1


# ================================================================ the owed turn
def test_an_owed_turn_survives_every_state_transition() -> None:
    """D-5's mechanism. Only an ANSWER clears a debt.

    Seed: clear ``_owed`` in ``_enter`` and this goes RED at the first
    transition — which is exactly the bug the card names ("an owed turn dropped
    on a state transition").
    """

    controller = TurnController(floor_ms=FLOOR)
    controller.note_turn_owed(0.0)
    for step in (
        lambda: controller.note_response_requested(0.1),
        lambda: controller.note_robot_started(0.2),
        lambda: controller.note_owner_started(1.0),
        lambda: controller.tick(1.0 + FLOOR / 1000.0),
        lambda: controller.note_robot_ended(3.0),
        lambda: controller.reset(),
    ):
        step()
        assert controller.owner_turn_owed is True, controller.state
    assert controller.owed_turns_abandoned == 0
    controller.note_turn_answered(4.0)
    assert controller.owner_turn_owed is False
    assert controller.owed_turns_answered == 1


def test_a_reset_that_is_told_to_forget_counts_the_debt_as_abandoned() -> None:
    controller = TurnController(floor_ms=FLOOR)
    controller.note_turn_owed(0.0)
    controller.reset(keep_owed=False)
    assert controller.owner_turn_owed is False
    assert controller.owed_turns_abandoned == 1
    assert controller.owed_turns_answered == 0


def test_owed_for_reports_how_long_the_owner_has_been_waiting() -> None:
    controller = TurnController(floor_ms=FLOOR)
    assert controller.owed_for_s(1.0) is None
    controller.note_turn_owed(1.0)
    assert controller.owed_for_s(3.5) == pytest.approx(2.5)
    controller.note_turn_answered(4.0)
    assert controller.owed_for_s(5.0) is None


def test_the_snapshot_is_json_serialisable_and_names_the_state() -> None:
    controller = _speaking()
    controller.note_owner_started(1.0)
    payload = json.loads(json.dumps(controller.snapshot()))
    assert payload["state"] == STATE_OVERLAP
    assert payload["ducked"] is True
    assert payload["floor_ms"] == FLOOR
    assert math.isclose(payload["duck_gain"], DEFAULT_DUCK_GAIN)


# ============================== the interrupt onset stamp (MARK-1 handoff H-7)
def _capture(tmp_path: Path) -> SessionAudioCapture:
    capture = SessionAudioCapture(root=tmp_path, session_id="sess_duplex1")
    capture.start()
    return capture


def _index(capture: SessionAudioCapture) -> dict:
    return json.loads((capture.directory / CAPTURE_INDEX_NAME).read_text(encoding="utf-8"))


def _robot_segments(index: dict) -> list[dict]:
    return list(index["streams"]["robot"]["segments"])


def test_the_cut_now_carries_the_onset_and_not_only_the_commit(tmp_path: Path) -> None:
    """MARK-1's H-7 / AIR-1's second missing half.

    ``interrupted_at`` is when ``interrupt()`` ran. With MARK-1's floor at 0
    that WAS the onset; with a floor it is a whole floor later, and AIR-1's
    latency row (owner's voice hits the array → this WAV stops) starts at the
    onset. Seed: drop the ``onset_ago_s`` branch in ``mark_interrupted`` and
    ``interrupted_onset_at`` is absent.
    """

    capture = _capture(tmp_path)
    gateway = BrowserAudioGateway(on_audio=lambda _f: None, on_mic=lambda _on: None, capture=capture)
    gateway.bind_token(TOKEN)
    gateway.start()
    gateway.attach(TOKEN)
    sink = BrowserSink(gateway)
    sink.begin_utterance()
    sink.enqueue(b"\x00" * 4800)
    sink.interrupt(onset_ago_s=0.700)
    gateway.stop()
    capture.close("test")

    segments = _robot_segments(_index(capture))
    cut = [segment for segment in segments if segment.get("interrupted")]
    assert cut, "the robot segment was never marked interrupted"
    segment = cut[-1]
    assert "interrupted_at" in segment
    assert "interrupted_onset_at" in segment
    assert segment["interrupt_hold_ms"] == pytest.approx(700.0)
    assert segment["interrupted_onset_at"] < segment["interrupted_at"]


def test_without_an_onset_the_index_is_exactly_what_mark1_shipped(tmp_path: Path) -> None:
    """The old caller records the old thing. No key appears out of nowhere."""

    capture = _capture(tmp_path)
    gateway = BrowserAudioGateway(on_audio=lambda _f: None, on_mic=lambda _on: None, capture=capture)
    gateway.bind_token(TOKEN)
    gateway.start()
    gateway.attach(TOKEN)
    sink = BrowserSink(gateway)
    sink.begin_utterance()
    sink.enqueue(b"\x00" * 4800)
    sink.interrupt()
    gateway.stop()
    capture.close("test")

    segment = [s for s in _robot_segments(_index(capture)) if s.get("interrupted")][-1]
    assert "interrupted_at" in segment
    assert "interrupted_onset_at" not in segment
    assert "interrupt_hold_ms" not in segment


def test_a_sink_that_takes_no_onset_is_called_the_old_way(tmp_path: Path) -> None:
    """``DiscardSink`` and ``voice_audio.SpeakerSink`` must not need widening.

    A swallowed ``TypeError`` around a barge-in would be the same defect with a
    longer stack trace, so the lane advertises rather than probes.
    """

    del tmp_path
    discard = DiscardSink()
    assert getattr(discard, "accepts_interrupt_onset", False) is False
    discard.interrupt()
    assert discard.interrupts == 1
    with pytest.raises(TypeError):
        discard.interrupt(onset_ago_s=0.7)  # type: ignore[call-arg]


def test_a_sink_whose_gateway_cannot_duck_counts_instead_of_raising() -> None:
    """The local speaker path has no gain. It must still be usable."""

    class _Plain:
        accepts_interrupt_onset = False

        def __init__(self) -> None:
            self.interrupts = 0

        def begin_utterance(self) -> None: ...

        def send_audio(self, chunk: bytes) -> None: ...

        def interrupt(self) -> None:
            self.interrupts += 1

        @property
        def played_started_monotonic(self) -> float | None:
            return None

    sink = BrowserSink(_Plain())
    sink.duck(0.18)
    assert sink.ducks == 0
    assert sink.ducks_unsupported == 1
    sink.interrupt(onset_ago_s=0.7)
    assert sink.interrupts == 1
    assert sink.snapshot()["ducks_unsupported"] == 1


def test_the_lane_never_hands_a_linear_gain_to_a_decibel_duck() -> None:
    """Correction pass, finding 3. The scale, not the method name.

    ``voice_audio.SpeakerSink`` has a ``duck`` whose argument is attenuation in
    DECIBELS. Handed this card's 0.18 it does not raise — 0.18 dB is inside its
    accepted range — it sets the gain to 0.979, an inaudible "duck", on the one
    path with no browser to reveal it. The lane must gate on the capability
    FLAG and refuse to call such a sink at all.

    Seed: change the gate back to ``getattr(sink, "duck", None)`` and the
    ``recorded`` list below is ``[0.18]`` instead of empty.
    """

    from parcel_robot.realtime.config import MODE_AUDIO, RealtimeConfig
    from parcel_robot.realtime.lane import RealtimeLane

    recorded: list[float] = []

    class _DecibelSink:
        """The shape of ``voice_audio.SpeakerSink``: a dB duck, no flag."""

        first_chunk_started_monotonic: float | None = None

        def begin_utterance(self) -> None: ...

        def enqueue(self, chunk: bytes, token: object = None) -> None: ...

        def interrupt(self) -> None: ...

        def duck(self, attenuation_db: float = 10.0) -> None:
            recorded.append(float(attenuation_db))

        def restore(self) -> None: ...

    sink = _DecibelSink()
    assert hasattr(sink, "duck"), "the pre-correction gate would have found this"
    assert getattr(sink, "accepts_gain_duck", False) is False

    lane = RealtimeLane(
        config=RealtimeConfig(enabled=True, source="duplex1", mode=MODE_AUDIO),
        instructions="be a good dog",
        sink=sink,
        backchannel_floor_ms=FLOOR,
    )
    lane._apply_turn_action(
        lane.turn_controller.note_owner_started(0.0)
    )  # not overlapping: a no-op action
    lane.turn_controller.note_robot_started(0.0)
    lane._apply_turn_action(lane.turn_controller.note_owner_started(1.0))

    assert recorded == [], "a linear gain must never reach a decibel duck"
    assert lane.ducks_requested == 0
    assert lane.ducks_unsupported == 1
