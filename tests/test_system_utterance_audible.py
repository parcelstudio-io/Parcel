"""U35 — the dog asks for help, and now something can actually hear it.

Before 2026-08-09 every *system-initiated* utterance — the ``Vocalize`` and
``AskClarification`` skills, the localization-health announcements, the search
give-up, and the whole blocked-by-a-person yield policy (ask / re-ask /
give-up, card P-1) — ended at ``RobotRuntime._brain_vocalize``, which wrote a
chat item and an event log line and returned. None of it ever reached a
synthesizer. "The dog asks for help" was a sentence in a transcript.

These cases pin the path that fixes it and, just as importantly, the two ways
it could do harm:

* **Concurrency.** Two output workers enqueuing into one ordered speaker sink
  interleave two sentences' chunks. ``speak_system`` therefore SKIPS rather
  than overlapping or queueing, and that skip is asserted from three
  directions (a live reply, a live filler, a live system utterance).
* **Metric pollution.** A request for help is not a duplex *filler*. It must
  not touch ``_filler_active``, ``on_filler_audible``, the ``filler_*`` stages,
  or the ≤2 s filler ceiling, and it must not cancel a turn's filler watchdog
  or write a ttft for a turn nobody started.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.contracts import FrozenDict, SuccessCondition
from parcel_robot.brain.executive import DispatchRequest
from parcel_robot.models import VelocityCommand
from parcel_robot.observability import STAGES, LatencyTracker
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice_pipeline import SYSTEM_UTTERANCE_KIND, DuplexVoiceSession, VoiceStage

REPO = Path(__file__).resolve().parents[1]

SYSTEM_STAGES = ("system_utterance_start", "system_utterance_complete")


# --------------------------------------------------------------- fake voice IO
class _Agent:
    """A voice agent that never speaks unless spoken to."""

    def __init__(self, reply: str = "reply text") -> None:
        self.reply = reply
        self.handled: list[str] = []

    def handle_text(self, text: str) -> str:
        self.handled.append(text)
        return self.reply


class _InstantSynth:
    """One chunk per call, tagged with the text so ownership is provable."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        return f"audio:{text}".encode()


class _BlockingSynth:
    """Streams one chunk, then holds the worker until released."""

    def __init__(self, release: threading.Event, started: threading.Event) -> None:
        self.release = release
        self.started = started
        self.texts: list[str] = []

    def synthesize(self, text: str) -> bytes:  # pragma: no cover - stream is used
        raise AssertionError("streaming synthesis should be used")

    def synthesize_stream(self, text: str, *, cancel_event=None, on_sentence=None):
        self.texts.append(text)
        outer = self

        class _Stream:
            def __init__(self) -> None:
                self.sent = False

            def __iter__(self):
                return self

            def __next__(self) -> bytes:
                if not self.sent:
                    self.sent = True
                    outer.started.set()
                    return f"audio:{text}".encode()
                outer.release.wait(3.0)
                if cancel_event is not None and cancel_event.is_set():
                    raise StopIteration
                raise StopIteration

            def cancel(self) -> None:
                outer.release.set()

            close = cancel

        return _Stream()


def _session(**kwargs) -> DuplexVoiceSession:
    return DuplexVoiceSession(_Agent(), **kwargs)


def _await_stage(stages: list[VoiceStage], name: str, timeout: float = 3.0) -> None:
    """Wait for a stage by name.

    ``wait_until_idle`` releases inside ``_run_output``'s cleanup, which is one
    frame before ``system_utterance_complete`` is emitted. Polling here keeps
    the ordering assertions deterministic instead of nearly-always-true.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(stage.name == name for stage in stages):
            return
        time.sleep(0.005)
    raise AssertionError(f"stage {name!r} never arrived: {[s.name for s in stages]}")


# ------------------------------------------------------- the audible happy path
def test_a_system_utterance_reaches_the_sink_through_the_ordinary_output_path() -> None:
    played: list[bytes] = []
    stages: list[VoiceStage] = []
    armed: list[float] = []

    with _session(
        synthesizer=_InstantSynth(),
        audio_chunk_player=played.append,
        audio_turn_start=lambda: armed.append(time.monotonic()),
        on_stage=stages.append,
    ) as session:
        assert session.speak_system("Could you help me get through?") is True
        assert session.wait_until_idle(2.0)
        _await_stage(stages, "system_utterance_complete")

    assert played == [b"audio:Could you help me get through?"]
    # The sink was re-armed exactly as it is for a reply; without this a
    # previous barge-in's interrupt latch would swallow the ask.
    assert len(armed) == 1

    names = [stage.name for stage in stages]
    assert names[0] == "system_utterance_start"
    assert names[-1] == "system_utterance_complete"
    for required in ("tts_start", "tts_first_chunk", "audio_first_playback", "tts_complete"):
        assert required in names, names


def test_a_system_utterance_never_closes_a_turn_and_never_looks_like_a_filler() -> None:
    stages: list[VoiceStage] = []
    filler_audible: list[int] = []

    with _session(
        synthesizer=_InstantSynth(),
        audio_chunk_player=lambda _chunk: None,
        on_stage=stages.append,
        on_filler_audible=lambda: filler_audible.append(1),
    ) as session:
        assert session.speak_system("I'm still waiting.") is True
        assert session.wait_until_idle(2.0)
        _await_stage(stages, "system_utterance_complete")

    names = [stage.name for stage in stages]
    # Not a turn: `turn_complete` would finalize a latency trace and flip the
    # dialogue phase for a turn that was never started.
    assert "turn_complete" not in names, names
    # Not a filler: none of the filler bookkeeping may move, or a request for
    # help silently becomes a data point in the <=2 s acknowledgement ceiling.
    assert not [name for name in names if name.startswith("filler_")], names
    assert filler_audible == []
    assert session._filler_active is False
    assert session._pending_reply_after_filler is None


def test_every_stage_a_system_utterance_emits_is_marked_system() -> None:
    """The marker is what lets observers tell an ask from an answer."""

    stages: list[VoiceStage] = []
    with _session(
        synthesizer=_InstantSynth(),
        audio_chunk_player=lambda _chunk: None,
        on_stage=stages.append,
    ) as session:
        assert session.speak_system("Someone is in my way.") is True
        assert session.wait_until_idle(2.0)
        _await_stage(stages, "system_utterance_complete")

    assert stages
    assert all(stage.kind == SYSTEM_UTTERANCE_KIND for stage in stages), [
        (stage.name, stage.kind) for stage in stages
    ]


def test_an_ordinary_reply_is_not_marked_system() -> None:
    stages: list[VoiceStage] = []
    with _session(
        synthesizer=_InstantSynth(),
        audio_chunk_player=lambda _chunk: None,
        on_stage=stages.append,
    ) as session:
        session.submit_text("hello")
        assert session.wait_until_idle(2.0)

    assert stages
    assert all(stage.kind == "" for stage in stages), [
        (stage.name, stage.kind) for stage in stages
    ]
    assert SYSTEM_STAGES[0] not in [stage.name for stage in stages]


# ------------------------------------------------------------- the skip policy
def test_a_system_utterance_is_skipped_while_a_reply_is_speaking() -> None:
    """The dog must not talk over itself, and one sink must carry one stream."""

    release = threading.Event()
    started = threading.Event()
    synth = _BlockingSynth(release, started)
    played: list[bytes] = []
    stages: list[VoiceStage] = []

    session = DuplexVoiceSession(
        _Agent("this is the reply"),
        synthesizer=synth,
        audio_chunk_player=played.append,
        on_stage=stages.append,
    )
    try:
        session.submit_text("say something")
        assert started.wait(2.0)
        # The reply's output worker owns the speaker right now.
        assert session.speak_system("could you move please") is False
        assert session.speak_system("could you move please") is False
    finally:
        release.set()
        session.close()

    # Nothing of the system utterance was synthesized, enqueued, or observed.
    assert synth.texts == ["this is the reply"]
    assert played == [b"audio:this is the reply"]
    assert [name for name in (stage.name for stage in stages) if name.startswith("system_")] == []


def test_a_system_utterance_is_skipped_while_a_filler_is_active() -> None:
    release = threading.Event()
    started = threading.Event()
    synth = _BlockingSynth(release, started)
    played: list[bytes] = []

    session = DuplexVoiceSession(
        _Agent(),
        synthesizer=synth,
        audio_chunk_player=played.append,
    )
    try:
        assert session.play_filler("Hmm, let me think", turn_id=1) is True
        assert started.wait(2.0)
        assert session.speak_system("could you move please") is False
    finally:
        release.set()
        session.close()

    assert synth.texts == ["Hmm, let me think"]
    assert played == [b"audio:Hmm, let me think"]


def test_two_system_utterances_never_run_at_once() -> None:
    release = threading.Event()
    started = threading.Event()
    synth = _BlockingSynth(release, started)
    played: list[bytes] = []

    session = DuplexVoiceSession(
        _Agent(),
        synthesizer=synth,
        audio_chunk_player=played.append,
    )
    try:
        assert session.speak_system("first ask") is True
        assert started.wait(2.0)
        assert session.speak_system("second ask") is False
        assert session._output_jobs == 1
    finally:
        release.set()
        session.close()

    assert synth.texts == ["first ask"]
    assert played == [b"audio:first ask"]


def test_the_speaker_is_released_and_a_later_ask_is_spoken() -> None:
    """Skipping must not latch: the re-ask a few seconds later is heard."""

    played: list[bytes] = []
    with _session(
        synthesizer=_InstantSynth(),
        audio_chunk_player=played.append,
    ) as session:
        assert session.speak_system("first ask") is True
        assert session.wait_until_idle(2.0)
        assert session.speak_system("second ask") is True
        assert session.wait_until_idle(2.0)

    assert played == [b"audio:first ask", b"audio:second ask"]


def test_a_reply_still_speaks_after_a_system_utterance() -> None:
    played: list[bytes] = []
    with _session(
        synthesizer=_InstantSynth(),
        audio_chunk_player=played.append,
    ) as session:
        assert session.speak_system("someone is in my way") is True
        assert session.wait_until_idle(2.0)
        session.submit_text("hello")
        assert session.wait_until_idle(2.0)

    assert played == [b"audio:someone is in my way", b"audio:reply text"]


# ------------------------------------------------------------------- barge-in
def test_barge_in_cancels_a_system_utterance_and_flushes_the_queue() -> None:
    """The atomicity contract, unchanged: an interrupt reaches the sink even
    when the output worker has already exited (the drain window), and the
    system utterance's cancel event is set like any other speech."""

    release = threading.Event()
    started = threading.Event()
    synth = _BlockingSynth(release, started)
    interrupts: list[int] = []
    stages: list[VoiceStage] = []

    session = DuplexVoiceSession(
        _Agent(),
        synthesizer=synth,
        audio_chunk_player=lambda _chunk: None,
        audio_interrupt=lambda: interrupts.append(1),
        on_stage=stages.append,
    )
    try:
        epoch_before = session.speech_epoch
        assert session.speak_system("could you move please") is True
        assert started.wait(2.0)
        session.barge_in()
        assert session.wait_until_idle(3.0)
        _await_stage(stages, "system_utterance_complete")

        assert interrupts, "barge-in never reached the audio sink"
        assert session.speech_epoch > epoch_before
        names = [stage.name for stage in stages]
        assert "superseded" in names, names
        # No token leakage: the worker unwound completely, the session is
        # idle, and nothing is still holding the speaker.
        assert session._active_output is None
        assert session._output_jobs == 0
        assert session._output_threads == set()
        assert names[-1] == "system_utterance_complete"
    finally:
        release.set()
        session.close()


def test_owner_speech_supersedes_a_system_utterance_the_same_way_it_supersedes_a_reply() -> None:
    release = threading.Event()
    started = threading.Event()
    synth = _BlockingSynth(release, started)
    interrupts: list[int] = []

    session = DuplexVoiceSession(
        _Agent("answering you"),
        synthesizer=synth,
        audio_chunk_player=lambda _chunk: None,
        audio_interrupt=lambda: interrupts.append(1),
    )
    try:
        assert session.speak_system("could you move please") is True
        assert started.wait(2.0)
        # A final transcript is a barge-in plus a command.
        session.submit_text("stop")
        release.set()
        assert session.wait_until_idle(3.0)
    finally:
        release.set()
        session.close()

    assert interrupts
    assert session._active_output is None


def test_a_system_utterance_started_in_a_stale_epoch_is_refused() -> None:
    """``close`` and barge-in bump the epoch; nothing may start behind them."""

    played: list[bytes] = []
    session = DuplexVoiceSession(
        _Agent(),
        synthesizer=_InstantSynth(),
        audio_chunk_player=played.append,
    )
    session.close()
    assert session.speak_system("could you move please") is False
    assert played == []


# ------------------------------------------------------------ text-only hosts
def test_text_only_mode_returns_false_and_never_raises() -> None:
    stages: list[VoiceStage] = []
    with _session(on_stage=stages.append) as session:
        assert session.speak_system("could you move please") is False
        assert session.wait_until_idle(1.0)
    # Not even a start stage: `system_utterance_start` promises a worker, and
    # in text mode there is none. An unpaired start would be a lie.
    assert stages == []


def test_empty_text_speaks_nothing() -> None:
    played: list[bytes] = []
    with _session(
        synthesizer=_InstantSynth(),
        audio_chunk_player=played.append,
    ) as session:
        assert session.speak_system("   ") is False
        assert session.speak_system("") is False
    assert played == []


# --------------------------------------------------- the closed stage vocabulary
def test_the_stage_vocabulary_accepts_the_system_utterance_names() -> None:
    """``LatencyTracker.mark`` RAISES on an unknown stage. Without this the
    first live ask would surface as a voice-session error instead of audio."""

    for name in SYSTEM_STAGES:
        assert name in STAGES

    tracker = LatencyTracker()
    tracker.start(1, "go to the sidewalk", now=0.0)
    for name in SYSTEM_STAGES:
        tracker.mark(1, name, now=1.0)
    with pytest.raises(ValueError):
        tracker.mark(1, "system_utterance_invented", now=1.0)


def test_every_stage_name_the_system_path_can_emit_is_in_the_vocabulary() -> None:
    """Collected from a real run rather than listed by hand, including the
    failure arm — a sink that rejects the chunk emits ``error``."""

    names: set[str] = set()

    def collect(stage: VoiceStage) -> None:
        names.add(stage.name)

    with _session(
        synthesizer=_InstantSynth(),
        audio_chunk_player=lambda _chunk: None,
        on_stage=collect,
    ) as session:
        assert session.speak_system("a spoken ask") is True
        assert session.wait_until_idle(2.0)

    def reject(_chunk: bytes) -> None:
        raise OSError("sink unavailable")

    with _session(
        synthesizer=_InstantSynth(),
        audio_chunk_player=reject,
        on_stage=collect,
        on_error=lambda _error: None,
    ) as session:
        assert session.speak_system("an ask nobody can play") is True
        assert session.wait_until_idle(2.0)

    assert "error" in names
    assert names <= STAGES, sorted(names - STAGES)


# ------------------------------------------------------------- runtime wiring
class _Backend:
    name = "system-utterance-test"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0),
            backend=self.name,
        )
        self.moves: list[VelocityCommand] = []

    def observe(self) -> SimObservation:
        from dataclasses import replace

        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill


@pytest.fixture()
def runtime(tmp_path: Path):
    path = tmp_path / "robot-system-utterance.yaml"
    # `speech.mode: text` on purpose. This host happens to have Piper
    # installed, so the default `auto` would build a real synthesizer and make
    # these cases depend on a subprocess. The audible half of the wiring is
    # asserted below by installing a session with fakes, which is the same
    # code path with a deterministic clock.
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
speech:
  mode: text
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
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    audio_status = AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )
    session = RobotRuntime(path, _Backend(), audio_status=audio_status)
    try:
        yield session
    finally:
        session.close()


class _RecordingSession:
    """Stands in for the duplex session at the runtime seam."""

    def __init__(self, *, audible: bool) -> None:
        self.audible = audible
        self.spoken: list[tuple[str, str]] = []

    def speak_system(self, text: str, *, turn_id: int = 0, kind: str = "system") -> bool:
        self.spoken.append((text, kind))
        return self.audible

    def close(self, **_kwargs: object) -> bool:
        return True

    def barge_in(self) -> None:
        return None

    @property
    def speech_epoch(self) -> int:
        return 0


class _FakeSink:
    """Enough of ``SpeakerSink`` for the runtime snapshot and teardown."""

    playback_active = False

    def close(self) -> None:
        return None

    def interrupt(self) -> None:
        return None

    def begin_utterance(self) -> None:
        return None


def _install_recording_voice(runtime: RobotRuntime, *, audible: bool) -> _RecordingSession:
    voice = _RecordingSession(audible=audible)
    runtime.voice_session = voice  # type: ignore[assignment]
    runtime._speaker_sink = _FakeSink()  # type: ignore[assignment]
    return voice


def _brain_events(runtime: RobotRuntime) -> list[dict]:
    return [
        dict(item)
        for item in (runtime.snapshot().get("events") or [])
        if item.get("role") == "brain"
    ]


def test_a_system_utterance_attempts_audio_and_still_writes_chat_and_event(
    runtime: RobotRuntime,
) -> None:
    voice = _install_recording_voice(runtime, audible=True)

    assert runtime._brain_vocalize("Could you help me get through to sidewalk?") is True

    assert voice.spoken == [("Could you help me get through to sidewalk?", "system")]
    chat = [str(item["text"]) for item in runtime.snapshot()["chat"]]
    assert chat == ["Could you help me get through to sidewalk?"]
    events = _brain_events(runtime)
    assert events[-1]["text"] == "Could you help me get through to sidewalk?"
    assert events[-1]["detail"] == {"audible": True, "audio_path": "voice_tts"}


def test_a_text_only_host_records_the_utterance_as_inaudible(runtime: RobotRuntime) -> None:
    """The chat item is still the record. The event must not imply sound."""

    assert runtime._speaker_sink is None  # this host has no synthesizer
    assert runtime._brain_vocalize("I lost you — I'll wait here.") is False

    chat = [str(item["text"]) for item in runtime.snapshot()["chat"]]
    assert chat == ["I lost you — I'll wait here."]
    events = _brain_events(runtime)
    assert events[-1]["detail"] == {"audible": False, "audio_path": "text_only"}


def test_a_busy_speaker_is_recorded_as_suppressed_not_as_spoken(
    runtime: RobotRuntime,
) -> None:
    _install_recording_voice(runtime, audible=False)

    assert runtime._brain_vocalize("I'm still waiting.") is False
    assert _brain_events(runtime)[-1]["detail"] == {
        "audible": False,
        "audio_path": "suppressed_output_busy",
    }


def test_a_voice_failure_never_takes_down_the_caller(runtime: RobotRuntime) -> None:
    class _Exploding:
        def speak_system(self, *_args: object, **_kwargs: object) -> bool:
            raise RuntimeError("synthesizer exploded")

        def close(self, **_kwargs: object) -> bool:
            return True

    runtime.voice_session = _Exploding()  # type: ignore[assignment]
    runtime._speaker_sink = _FakeSink()  # type: ignore[assignment]

    assert runtime._brain_vocalize("Someone is in my way.") is False
    chat = [str(item["text"]) for item in runtime.snapshot()["chat"]]
    assert chat == ["Someone is in my way."]


def test_an_empty_utterance_is_still_refused(runtime: RobotRuntime) -> None:
    with pytest.raises(ValueError):
        runtime._brain_vocalize("   ")


def test_a_vocalize_planned_step_attempts_to_speak(runtime: RobotRuntime) -> None:
    """The executive's Vocalize step, through the runtime's own adapter."""

    voice = _install_recording_voice(runtime, audible=True)

    request = DispatchRequest(
        task_id="task-vocalize",
        plan_revision=1,
        step_id="step-1",
        attempt=1,
        skill="Vocalize",
        arguments=FrozenDict({"text": "I can't get to the sidewalk."}),
        success=SuccessCondition("utterance_sent", None),
        resources=("base",),
        timeout_s=30.0,
    )
    result = runtime.semantic_tasks.dispatch(request, now=1.0)

    assert result is not None and result.status == "succeeded"
    assert result.verified_facts[0].source == "runtime_voice_log"
    assert voice.spoken == [("I can't get to the sidewalk.", "system")]


def test_an_ask_clarification_step_attempts_to_speak(runtime: RobotRuntime) -> None:
    voice = _install_recording_voice(runtime, audible=True)

    request = DispatchRequest(
        task_id="task-ask",
        plan_revision=1,
        step_id="step-1",
        attempt=1,
        skill="AskClarification",
        arguments=FrozenDict({"question": "Which store do you mean?"}),
        success=SuccessCondition("utterance_sent", None),
        resources=("base",),
        timeout_s=30.0,
    )
    runtime.semantic_tasks.dispatch(request, now=1.0)
    assert voice.spoken == [("Which store do you mean?", "system")]


def test_the_runtime_seam_carries_an_utterance_all_the_way_to_the_speaker(
    runtime: RobotRuntime,
) -> None:
    """End to end at the runtime seam, with the REAL session and the REAL
    ``SpeakerSink``: only the synthesizer and the device player are fakes.

    This is the case that would have failed before U35 was closed — the old
    ``_brain_vocalize`` wrote chat and returned, and ``played`` stayed empty.
    """

    from parcel_robot.voice_audio import SpeakerSink, pcm16_wav

    class _WavSynth:
        def synthesize(self, text: str) -> bytes:
            return pcm16_wav(b"\x01\x00" * 1600)  # 0.1 s at 16 kHz

    played: list[int] = []
    sink = SpeakerSink(player=lambda pcm, _rate: played.append(len(pcm)))
    runtime._speaker_sink = sink  # type: ignore[assignment]
    session = DuplexVoiceSession(
        runtime,
        synthesizer=_WavSynth(),
        audio_chunk_player=runtime._enqueue_speech_chunk,
        audio_interrupt=runtime._interrupt_speech_audio,
        audio_turn_start=sink.begin_utterance,
        on_stage=runtime._voice_stage,
    )
    runtime.voice_session = session  # type: ignore[assignment]
    try:
        assert runtime._brain_vocalize("Someone is standing right where I need to go.") is True
        assert session.wait_until_idle(5.0)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not played:
            time.sleep(0.01)
    finally:
        session.close()
        sink.close()

    assert played, "the utterance never reached the speaker"
    assert _brain_events(runtime)[-1]["detail"] == {
        "audible": True,
        "audio_path": "voice_tts",
    }
    assert [str(item["text"]) for item in runtime.snapshot()["chat"]] == [
        "Someone is standing right where I need to go."
    ]


def test_system_stages_do_not_move_the_duplex_turn_ledger(runtime: RobotRuntime) -> None:
    """A system utterance has no query end, so it must not become a turn's
    time-to-first-token nor cancel that turn's filler watchdog."""

    before = dict(runtime.duplex.snapshot())
    for name in SYSTEM_STAGES + ("tts_start", "tts_first_chunk", "audio_first_playback"):
        runtime._voice_stage(
            VoiceStage(0, name, time.monotonic(), kind=SYSTEM_UTTERANCE_KIND)
        )
    assert runtime.duplex.snapshot() == before
    assert runtime._duplex_turn_meta == {}
    # And the latency ledger accepted every one of them without raising.
    assert runtime.snapshot()["voice"]["status"] != "error"
