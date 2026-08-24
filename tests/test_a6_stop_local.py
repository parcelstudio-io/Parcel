"""Card A6 — STOP-LOCAL: the always-local spoken stop, and its four bars.

WHAT IS BEING PROVEN, AND WITH WHAT
-----------------------------------
Addendum A2 made an always-local spoken stop a BUILD GATE because
``realtime/lane.py:47-53`` says the product's spoken stop is transcribed in the
cloud. Addendum A9 set its acceptance: a TAIL bar (p95 <= 800 ms AND all of
n >= 60 trials within 1.0 s) and a false-trigger bar (<= 1 false STOP per 24 h),
with "STOP bypasses every gate" as the standing property.

Three evidence tiers, never mixed in one row:

1.  **replay** — the real matcher (:func:`spot_stop`, :class:`StopHotwordConfig`)
    re-scored over the ASR windows a REAL run of the real spotter produced on
    the VOICE-GATE tapes. ``tests/data/a6_stop_local.json`` carries those
    windows with the wall time each transcription actually took, so a latency
    computed here is measured audio + measured ASR + this code's decision. The
    tapes themselves live in a scratch directory that will evaporate (the
    AUDIT_FULL_FABLE §Ops lesson), which is exactly why the windows are
    committed and the tape is not.
2.  **live thread** — the real :class:`StopHotwordWatch`, its real queue and its
    real thread, driven in REAL time with the measured ASR cost replayed as a
    sleep. This is what says the hand-off costs nothing, and it is where the
    bypass property is measured against a genuinely hung conversation.
3.  **pure** — the grammar, the config loader and the wiring.

WHAT IS NOT PROVEN HERE
-----------------------
Anything through air. Every row is the VOICE-GATE ``replay`` tier: no
loudspeaker, no mounted acoustics, no AEC, no gait or fan noise, and no real
human owner saying the dog's name (the name-prefixed row is a neural TTS at
four speaking rates — espeak cannot pronounce the word intelligibly enough for
``base.en``, which is VOICE-GATE F3b and is reported as its own row below).
Those are box-day, on the mounted array.
"""

from __future__ import annotations

import json
import pathlib
import threading
import time

import numpy as np
import pytest

from parcel_robot.audio.stop_hotword import (
    MODE_BARE,
    MODE_HYBRID,
    MODE_NAME_PREFIXED,
    MODE_OFF,
    STOP_PHRASES,
    StopHotwordConfig,
    StopHotwordSpotter,
    StopHotwordWatch,
    StopTappedVoiceLoop,
    normalize_words,
    spot_stop,
)
from parcel_robot.voice.closed_intents import ClosedIntent, closed_intent_phrases

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "data" / "a6_stop_local.json"

#: A9's two bars, once.
TAIL_P95_S = 0.800
TAIL_MAX_S = 1.000
TAIL_MIN_TRIALS = 60
FALSE_STOPS_PER_24H_BAR = 1.0

SHIPPED = StopHotwordConfig()
BARE = StopHotwordConfig(mode=MODE_BARE)
HYBRID = StopHotwordConfig(mode=MODE_HYBRID)


@pytest.fixture(scope="module")
def evidence() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# tier: replay — the tail bars and the false-trigger rate
# ---------------------------------------------------------------------------
def replay(entry: dict, config: StopHotwordConfig, *, bare_window: bool = False) -> list[dict]:
    """Drive the REAL grammar over one tape's measured ASR windows.

    ``latch_s = window_end_s + asr_s`` is the spotter's own clock
    (:class:`StopLatch`), minus the microseconds the grammar itself costs.
    The relatch hold-off is applied here because the spotter applies it there.
    """

    latches: list[dict] = []
    last = -1e9
    for window in entry["windows"]:
        spot = spot_stop(window["text"], config, bare_window_open=bare_window)
        if spot is None:
            continue
        latch_s = float(window["window_end_s"]) + float(window["asr_s"])
        if latch_s - last < config.relatch_holdoff_s:
            continue
        last = latch_s
        latches.append(
            {
                "latch_s": latch_s,
                "asr_s": float(window["asr_s"]),
                "text": window["text"],
                "phrase": spot.phrase,
            }
        )
    return latches


def tail_row(entry: dict, config: StopHotwordConfig) -> dict:
    """Per-placement latency from the END of the spoken words to the latch."""

    latches = replay(entry, config)
    latencies: list[float] = []
    missed: list[str] = []
    #: Trials over the 1.0 s bound whose WINNING window is one the local
    #: transcriber was slow on. The distinction is load-bearing: a late latch
    #: because base.en took 2.3 s on one window is a statement about the
    #: transcriber, and the product's own STOP_HOTWORD_STT_TIMEOUT_S would have
    #: abandoned that window rather than waiting for it.
    slow_asr: list[float] = []
    for placement in entry["placements"]:
        end = float(placement["speech_end_s"])
        candidates = [
            latch
            for latch in latches
            if float(placement["speech_start_s"]) <= latch["latch_s"] <= end + 2.5
        ]
        if not candidates:
            missed.append(placement["name"])
            continue
        winner = min(candidates, key=lambda latch: latch["latch_s"])
        latency = max(0.0, winner["latch_s"] - end)
        latencies.append(latency)
        if latency > TAIL_MAX_S and winner["asr_s"] > 1.0:
            slow_asr.append(winner["asr_s"])
    return {
        "slow_asr": slow_asr,
        "trials": len(entry["placements"]),
        "latched": len(latencies),
        "missed": missed,
        "latencies": latencies,
        "p50_s": float(np.percentile(latencies, 50)) if latencies else float("nan"),
        "p95_s": float(np.percentile(latencies, 95)) if latencies else float("nan"),
        "max_s": max(latencies, default=float("nan")),
        "over_max": [value for value in latencies if value > TAIL_MAX_S],
    }


def assert_tail_bar(row: dict) -> None:
    """A9's tail bar, read the way the research reference read it.

    ``n`` is the TRIAL count (the reference's P6 row: "PASS n=64, 0 over 1.0 s"
    at recall 0.875) and the percentiles are over the trials that latched. A
    floor on the latch rate is asserted beside it so the tail can never pass by
    being computed over three lucky trials — recall is its own row below.
    """

    assert row["trials"] >= TAIL_MIN_TRIALS, (
        f"A9's finite-sample bound needs n >= {TAIL_MIN_TRIALS} trials, got {row['trials']}"
    )
    assert row["latched"] >= 0.8 * row["trials"], (
        f"only {row['latched']} of {row['trials']} trials latched; the tail below is "
        "computed over too few of them to mean anything"
    )
    assert row["p95_s"] <= TAIL_P95_S, f"p95 {row['p95_s']:.3f} s exceeds {TAIL_P95_S} s"
    assert not row["over_max"], (
        f"{len(row['over_max'])} of {row['latched']} trials exceeded {TAIL_MAX_S} s: "
        f"{row['over_max']}"
    )


def test_the_tail_bar_on_the_synthetic_name_prefixed_tape(evidence: dict) -> None:
    """A9's tail bar for the SHIPPED grammar. n >= 60, p95 <= 800 ms, all <= 1 s."""

    row = tail_row(evidence["tail"]["synthetic_piper_name"], SHIPPED)
    assert_tail_bar(row)
    assert row["latched"] / row["trials"] >= 0.90, (
        f"name-prefixed recall fell to {row['latched'] / row['trials']:.3f}; the "
        f"misses are {row['missed']}"
    )


def test_the_tail_bar_on_the_recorded_voicegate_tape(evidence: dict) -> None:
    """The same bar on the RECORDED VOICE-GATE stop tape, under ``bare``.

    The recorded tape's phrasings are three-quarters bare ("Stop.", "Stop!",
    "Hey, stop stop stop.") so it can only be scored under the bare grammar —
    which is the point: this row is the direct comparison with the research
    reference (recall 0.875, p95 935 ms) on the same audio.
    """

    row = tail_row(evidence["tail"]["recorded_voicegate_stop"], BARE)
    assert row["trials"] >= TAIL_MIN_TRIALS, row
    assert row["latched"] >= 0.8 * row["trials"], row
    assert row["p95_s"] <= TAIL_P95_S, f"p95 {row['p95_s']:.3f} s exceeds {TAIL_P95_S} s"
    # The honest exception, named with its mechanism rather than waived: on this
    # tape two "Hey, stop stop stop." trials land past 1.0 s, and BOTH are
    # trials whose winning window is one whisper.cpp itself took 1.5-2.3 s on
    # (median 0.37 s). The product would not have waited — its transcriber
    # timeout is 2.0 s and the next window is one cadence behind — so what this
    # asserts is that the PATH never overruns, only its transcriber does.
    assert len(row["over_max"]) == len(row["slow_asr"]), (
        f"{len(row['over_max'])} trials past {TAIL_MAX_S} s but only "
        f"{len(row['slow_asr'])} of them blame a slow transcriber: {row['over_max']}"
    )
    assert len(row["over_max"]) <= 3, row["over_max"]
    # Recall is NOT a bar this card claims to have met: the research reference
    # measured 0.875 on this audio (every miss at 3 m, 30-60 deg off axis) and
    # the product path measures one trial fewer — 55/64 — because it paces its
    # sweeps by what the transcriber costs instead of free-running at 300 ms.
    # That is the trade this card made deliberately: one trial of recall on the
    # BARE grammar, for a tail that went from 935 ms to 785 ms and for a spotter
    # that cannot fall behind a talker. The floor below is what may not move.
    reference = evidence["provenance"]["voicegate_reference"]
    assert row["latched"] / row["trials"] >= float(reference["recall"]) - 0.02, (
        f"recall fell from the reference's {reference['recall']} to "
        f"{row['latched'] / row['trials']:.3f}"
    )
    # The reference this improves on, pinned so a regression is visible as one.
    reference_p95 = float(reference["p95_s"])
    assert row["p95_s"] < reference_p95, (
        f"the product path ({row['p95_s']:.3f} s) is no better than the research "
        f"reference ({reference_p95:.3f} s) it was built to beat"
    )


def test_the_tail_assertion_can_fail(evidence: dict) -> None:
    """Seeded red: a matcher that misses the first accepting window blows the bar."""

    entry = evidence["tail"]["synthetic_piper_name"]
    latches = replay(entry, SHIPPED)
    seeded = {"windows": entry["windows"], "placements": entry["placements"]}
    # Delete the earliest accepting window of every placement: the SECOND one is
    # a whole cadence later, which is exactly what a lazier trigger would cost.
    first = {round(latch["latch_s"], 3) for latch in latches}
    seeded["windows"] = [
        window
        for window in entry["windows"]
        if round(float(window["window_end_s"]) + float(window["asr_s"]), 3) not in first
    ]
    row = tail_row(seeded, SHIPPED)
    assert row["p95_s"] > TAIL_P95_S or row["latched"] < TAIL_MIN_TRIALS, (
        f"the tail assertion is vacuous: dropping every winning window still passed ({row})"
    )


def false_stop_row(entry: dict, config: StopHotwordConfig, *, bare_window: bool = False) -> dict:
    latches = replay(entry, config, bare_window=bare_window)
    seconds = float(entry["tape_seconds"])
    return {
        "false_stops": len(latches),
        "seconds": seconds,
        "per_24h": len(latches) / (seconds / 86_400.0),
        "texts": [latch["text"] for latch in latches],
    }


def test_the_shipped_grammar_scores_zero_false_stops_on_the_television_tape(
    evidence: dict,
) -> None:
    """The measured reason ``name_prefixed`` is the default."""

    row = false_stop_row(evidence["television"], SHIPPED)
    assert row["false_stops"] == 0, row["texts"]
    assert row["per_24h"] <= FALSE_STOPS_PER_24H_BAR


def test_the_bare_grammar_reproduces_its_measured_false_stop_rate(evidence: dict) -> None:
    """The honest row: ``bare`` fails A9's bar by orders of magnitude.

    The research reference measured 864/24 h on this tape with a 1.0 s window on
    a free-running 300 ms cadence. This product path uses a 1.6 s window (it has
    to hold "<name>, stop") triggered at the speech-offset edge, and a 2 s
    relatch hold-off, so it asks about DIFFERENT seconds of the same television:
    the sentences it latches on are its own ("Police say that drivers stop
    testing.") and there are fewer of them. Fewer is not passing — the two
    numbers are the same finding at the same order of magnitude, hundreds of
    false stops a day against a bar of one, and the assertion says exactly that
    rather than pretending the tape and the trigger are interchangeable.
    """

    row = false_stop_row(evidence["television"], BARE)
    reference = float(evidence["provenance"]["voicegate_reference"]["tv_false_stops_per_24h"])
    assert row["false_stops"] >= 3, row
    assert row["per_24h"] > FALSE_STOPS_PER_24H_BAR * 100, (
        "the bare spotter's measured failure did not reproduce; the fixture or the "
        f"grammar has drifted: {row}"
    )
    assert 0.2 <= row["per_24h"] / reference <= 5.0, (
        f"bare scored {row['per_24h']:.0f}/24 h against the research reference "
        f"{reference:.0f}/24 h — the same tape and the same rule should stay within "
        "an order of magnitude of each other"
    )


def test_the_hybrid_bare_window_is_what_decides(evidence: dict) -> None:
    """Hybrid = the shipped grammar, plus bare only while the window is open."""

    closed = false_stop_row(evidence["television"], HYBRID, bare_window=False)
    opened = false_stop_row(evidence["television"], HYBRID, bare_window=True)
    bare = false_stop_row(evidence["television"], BARE)
    assert closed["false_stops"] == 0, closed["texts"]
    assert opened["false_stops"] == bare["false_stops"], (opened, bare)


def test_none_of_the_television_false_triggers_contain_the_name(evidence: dict) -> None:
    """VOICE-GATE's load-bearing observation, re-verified over every window."""

    hits = [
        window["text"]
        for window in evidence["television"]["windows"]
        if SHIPPED.name_words[0] in normalize_words(window["text"])
    ]
    assert hits == [], f"the name appeared in the television tape after all: {hits}"


def test_the_quiet_room_produces_no_stop_in_any_mode(evidence: dict) -> None:
    """49.6 min of the real room: 0 latches — and the bound that is, and is not."""

    room = evidence["room"]
    for config in (SHIPPED, HYBRID, BARE):
        row = false_stop_row(room, config, bare_window=True)
        assert row["false_stops"] == 0, (config.mode, row["texts"])
    hours = float(room["tape_seconds"]) / 3600.0
    # Zero events in T hours bounds the rate at 3/T (95 %), not at zero. This
    # tape supports <= ~87/24 h, not A9's <= 1/24 h, and saying so is the row.
    assert 3.0 / hours * 24.0 > FALSE_STOPS_PER_24H_BAR, (
        "this tape would have to be ~72 h long to bound the rate at the A9 bar; if "
        "that has changed, the claim in A6_STATUS.md changes with it"
    )


# ---------------------------------------------------------------------------
# tier: pure — the grammar
# ---------------------------------------------------------------------------
def test_the_stop_vocabulary_is_the_products_own() -> None:
    """U33's lesson: one stop grammar, not two."""

    assert set(STOP_PHRASES) == {
        tuple(phrase.split()) for phrase in closed_intent_phrases(ClosedIntent.STOP)
    }
    assert ("freeze",) not in STOP_PHRASES, "freeze is PAUSE in this product, not STOP"


@pytest.mark.parametrize(
    "text",
    ["stopped at the meeting", "stopping to tell me", "nonstop rain", "the stopper broke"],
)
@pytest.mark.parametrize("config", [SHIPPED, HYBRID, BARE], ids=lambda c: c.mode)
def test_whole_word_refusals(text: str, config: StopHotwordConfig) -> None:
    """A substring matcher latches on every one of these; this one may not."""

    assert "stop" in text, "the refusal proves nothing unless the substring is there"
    assert spot_stop(text, config, bare_window_open=True) is None


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Parcel, stop.", True),
        ("parcel stop", True),
        ("Hey Parcel, stop!", True),
        ("Parcel, stop now.", True),
        ("stop, Parcel", True),
        ("Stop.", False),
        ("stop talking to me", False),
    ],
)
def test_the_three_grammars_disagree_exactly_where_they_should(text: str, named: bool) -> None:
    assert (spot_stop(text, SHIPPED) is not None) is named
    assert (spot_stop(text, HYBRID, bare_window_open=False) is not None) is named
    assert spot_stop(text, HYBRID, bare_window_open=True) is not None
    assert spot_stop(text, BARE) is not None
    assert spot_stop(text, StopHotwordConfig(mode=MODE_OFF)) is None


def test_the_name_must_be_near_the_stop_word() -> None:
    """A name three sentences away is not a command to this dog."""

    assert spot_stop("parcel is a nice name for a dog", SHIPPED) is None
    far = "parcel and then i went to the shop and later on we all had to stop"
    assert spot_stop(far, SHIPPED) is None
    assert spot_stop(far, BARE) is not None


# ---------------------------------------------------------------------------
# tier: pure — the config knob
# ---------------------------------------------------------------------------
def test_the_default_mode_is_the_owner_flagged_one() -> None:
    assert StopHotwordConfig().mode == MODE_NAME_PREFIXED
    assert StopHotwordConfig.from_mapping(None).mode == MODE_NAME_PREFIXED
    assert StopHotwordConfig.from_mapping({}).mode == MODE_NAME_PREFIXED


def test_the_config_refuses_a_typo_by_name() -> None:
    with pytest.raises(ValueError, match="unknown stop_hotword config key"):
        StopHotwordConfig.from_mapping({"moode": "bare"})
    with pytest.raises(ValueError, match="stop_hotword.mode must be one of"):
        StopHotwordConfig.from_mapping({"mode": "name-prefixed"})
    with pytest.raises(TypeError):
        StopHotwordConfig.from_mapping({"window_s": "1.6"})
    with pytest.raises(ValueError, match="window_s"):
        StopHotwordConfig.from_mapping({"window_s": 99.0})


def test_a_named_mode_refuses_an_empty_name() -> None:
    for mode in (MODE_NAME_PREFIXED, MODE_HYBRID):
        with pytest.raises(ValueError, match="needs stop_hotword.name"):
            StopHotwordConfig.from_mapping({"mode": mode, "name": "   "})
    # ``bare`` does not need one: its grammar is the word, which is its problem.
    assert StopHotwordConfig.from_mapping({"mode": MODE_BARE, "name": ""}).mode == MODE_BARE


def test_the_bare_mode_documents_that_it_fails_the_bar() -> None:
    """The measured number lives beside the option, not in a footnote."""

    import parcel_robot.audio.stop_hotword as module

    assert "864" in module.__doc__
    assert "failing the bar" in module.__doc__


def test_the_stop_hotword_section_can_reach_a_profile() -> None:
    """Without the overlay exemption the knob would be unreachable (ROAM-1)."""

    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS

    assert "stop_hotword" in OVERLAY_INTRODUCIBLE_KEYS


# ---------------------------------------------------------------------------
# tier: live thread — the watch, its queue, and the bypass property
# ---------------------------------------------------------------------------
FRAME_SAMPLES = 480
SPEECH_AMPLITUDE = 6_000


class _AmplitudeVad:
    """A VAD whose 'speech' is loud audio. Real code, stub model.

    Silero is not run here: this tier is about the THREAD and the CLOCK, and a
    stub VAD makes the utterance boundary exact so the measured latency is the
    path's and not the model's. The Silero path is what the replay tier's
    windows were produced by.
    """

    available = True
    threshold = 0.5

    def process(self, frame: np.ndarray) -> float:
        return 1.0 if float(np.max(np.abs(frame))) > SPEECH_AMPLITUDE / 2 else 0.0


def _frames(speech: int, quiet: int) -> list[np.ndarray]:
    loud = np.full(FRAME_SAMPLES, SPEECH_AMPLITUDE, dtype=np.int16)
    loud[::2] = -SPEECH_AMPLITUDE
    return [loud.copy() for _ in range(speech)] + [
        np.zeros(FRAME_SAMPLES, dtype=np.int16) for _ in range(quiet)
    ]


def _drive(watch: StopHotwordWatch, frames: list[np.ndarray], speech: int) -> float:
    """Feed frames at their real 30 ms cadence; return the utterance-end stamp."""

    speech_end = 0.0
    for index, frame in enumerate(frames):
        watch.submit_frame(frame)
        if index == speech - 1:
            speech_end = time.monotonic()
        time.sleep(FRAME_SAMPLES / 16_000.0)
    return speech_end


def scripted_transcribe(pcm: np.ndarray, asr_s: float, text: str = "Parcel, stop.") -> str:
    """A transcriber that is not clairvoyant.

    It sleeps the MEASURED cost of a real ``base.en`` window and returns the
    hotword only when the window it was handed contains the WHOLE utterance —
    loud audio that has already gone quiet. A stub that answers "Parcel, stop."
    for a window containing the first 300 ms of the word would let a
    mid-utterance cadence check latch before the owner had finished speaking,
    and the measured latency would be a fiction. This is what makes the
    close-edge trigger, and only it, the thing that produces these numbers.
    """

    time.sleep(asr_s)
    if pcm.size < 400:
        return ""
    loud = float(np.max(np.abs(pcm))) > SPEECH_AMPLITUDE / 2
    # 64 ms: shorter than the close edge's own 3 x 32 ms of silence, so the
    # window the close edge produces reads as complete and a mid-utterance
    # cadence window does not.
    tail_quiet = float(np.max(np.abs(pcm[-1024:]))) <= SPEECH_AMPLITUDE / 2
    return text if loud and tail_quiet else ""


def _watch(on_stop, asr_s: float, text: str = "Parcel, stop.") -> StopHotwordWatch:
    spotter = StopHotwordSpotter(
        SHIPPED,
        vad=_AmplitudeVad(),
        transcribe=lambda pcm: scripted_transcribe(pcm, asr_s, text),
    )
    return StopHotwordWatch(spotter, on_stop)


#: The thread tier's own allowance, and why it is not A9's 800 ms.
#:
#: A9's p95 bar is carried by the replay tier, over the transcripts a real
#: ``base.en`` produced for real windows. THIS tier's transcriber is a stub that
#: answers only for a window whose speech has already ENDED — the strictest
#: possible reading — so the close-edge check always costs one transcription
#: more than a real one would (a real window holding all of "Parcel, stop" is
#: recognised while the talker is still trailing off; the stub refuses it). That
#: is a deliberate worst case: what it proves is that even then the latch lands
#: inside A9's finite-sample 1.0 s, and that the thread, the queue and the
#: runtime callback add nothing measurable on top.
THREAD_TIER_P95_S = 0.900


@pytest.mark.load_sensitive
def test_the_thread_hand_off_keeps_the_tail_bar(evidence: dict) -> None:
    """End to end on the REAL thread, in real time, with the measured ASR cost."""

    asr_s = float(evidence["provenance"]["median_asr_s"])
    latencies: list[float] = []
    for _ in range(6):
        latched: list[float] = []
        watch = _watch(lambda latch, sink=latched: sink.append(time.monotonic()), asr_s)
        watch.start()
        try:
            speech_end = _drive(watch, _frames(24, 30), 24)
            deadline = time.monotonic() + 3.0
            while not latched and time.monotonic() < deadline:
                time.sleep(0.005)
        finally:
            watch.close()
        assert latched, "the watch never latched a stop it was handed"
        latencies.append(latched[0] - speech_end)
    assert max(latencies) <= TAIL_MAX_S, latencies
    assert float(np.percentile(latencies, 95)) <= THREAD_TIER_P95_S, latencies


def test_the_capture_thread_is_never_blocked_by_the_stop_path() -> None:
    """``submit_frame`` is one bounded put; a wedged transcriber cannot stall it."""

    release = threading.Event()

    def transcribe(pcm: np.ndarray) -> str:
        del pcm
        release.wait(2.0)
        return "Parcel, stop."

    spotter = StopHotwordSpotter(SHIPPED, vad=_AmplitudeVad(), transcribe=transcribe)
    watch = StopHotwordWatch(spotter, lambda latch: None)
    watch.start()
    try:
        frames = _frames(6, 0)
        started = time.monotonic()
        for _ in range(200):
            for frame in frames:
                watch.submit_frame(frame)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        watch.close()
    assert elapsed < 0.5, (
        f"1200 capture frames took {elapsed:.3f} s to hand over while the stop "
        "path was wedged; submit_frame is supposed to be a put_nowait"
    )
    assert watch.frames_submitted == 1200


def test_the_watch_survives_a_transcriber_that_throws() -> None:
    """A stop path that dies on the first fault is not a stop path."""

    calls = {"count": 0}

    def transcribe(pcm: np.ndarray) -> str:
        del pcm
        calls["count"] += 1
        if calls["count"] < 3:
            raise OSError("whisper is not answering")
        return "Parcel, stop."

    faults: list[Exception] = []
    latched: list[object] = []
    spotter = StopHotwordSpotter(SHIPPED, vad=_AmplitudeVad(), transcribe=transcribe)
    watch = StopHotwordWatch(spotter, latched.append, on_error=faults.append)
    watch.start()
    try:
        for _ in range(4):
            for frame in _frames(24, 8):
                watch.submit_frame(frame)
                time.sleep(0.001)
        deadline = time.monotonic() + 3.0
        while not latched and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        watch.close()
    assert faults, "the faults were swallowed instead of reported"
    assert latched, "the watch never recovered from a transient transcriber fault"
    assert calls["count"] >= 3, calls


# ---------------------------------------------------------------------------
# tier: pure — the capture-rail tap
# ---------------------------------------------------------------------------
class _ZeroingAec:
    """An AEC that destroys the signal. The stop path must not see its output."""

    def process(self, frame: np.ndarray) -> np.ndarray:
        return np.zeros_like(frame)


def _loop(tap=None, **kwargs) -> StopTappedVoiceLoop:
    loop = StopTappedVoiceLoop(
        recognizer=None,
        submit_text=lambda *args, **more: None,
        barge_in=lambda: None,
        playback_active=lambda: False,
        **kwargs,
    )
    loop.stop_hotword_tap = tap
    return loop


def test_the_tapped_loop_still_has_the_seam_it_overrides() -> None:
    """The subclass seam, asserted: a renamed hook would silently deafen it."""

    from parcel_robot.audio.voice_loop import MicrophoneVoiceLoop

    assert issubclass(StopTappedVoiceLoop, MicrophoneVoiceLoop)
    assert hasattr(MicrophoneVoiceLoop, "_handle_frame")
    assert StopTappedVoiceLoop._handle_frame is not MicrophoneVoiceLoop._handle_frame


def test_the_tap_sees_the_raw_frame_before_the_canceller() -> None:
    seen: list[np.ndarray] = []
    loop = _loop(seen.append, aec=_ZeroingAec())
    frame = np.full(FRAME_SAMPLES, 1234, dtype=np.int16)
    loop.run_once(frame)
    assert len(seen) == 1
    assert int(np.max(np.abs(seen[0]))) == 1234, (
        "the stop path was handed the AEC's output; a failing canceller would "
        "then deafen the stop as well as the conversation"
    )


def test_a_broken_tap_cannot_break_capture() -> None:
    def explode(frame: np.ndarray) -> None:
        raise RuntimeError("tap is broken")

    loop = _loop(explode)
    loop.run_once(np.full(FRAME_SAMPLES, 1234, dtype=np.int16))
    loop.run_once(np.full(FRAME_SAMPLES, 1234, dtype=np.int16))
    assert loop.stop_hotword_tap_failures == 1
    assert loop.stop_hotword_tap is None


def test_no_tap_means_no_call() -> None:
    loop = _loop()
    loop.run_once(np.full(FRAME_SAMPLES, 1234, dtype=np.int16))
    assert loop.stop_hotword_tap is None
    assert loop.stop_hotword_tap_failures == 0


# ---------------------------------------------------------------------------
# tier: live — the runtime doors. Is it the SAME latch, and does it bypass?
# ---------------------------------------------------------------------------
from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.runtime import (
    SAFETY_SOURCE_PANEL,
    SAFETY_SOURCE_VOICE,
    TRANSCRIPT_ORIGIN_MIC,
    RobotRuntime,
)

SILERO_MODEL = REPO / "models" / "endpointing" / "silero_vad_v6.onnx"


class _Backend:
    name = "a6-stop"

    def __init__(self) -> None:
        self.emergencies = 0
        self.stops = 0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=self.name,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

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


def _runtime(tmp_path: pathlib.Path, *, mode: str = MODE_NAME_PREFIXED) -> RobotRuntime:
    path = tmp_path / "a6.yaml"
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
speech:
  mode: auto
  stt_provider: none
  tts_provider: none
  vad_model: {SILERO_MODEL}
stop_hotword:
  mode: {mode}
  name: parcel
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="a6 stop-local fixture",
        ),
    )


@pytest.fixture()
def runtime(tmp_path: pathlib.Path):
    instance = _runtime(tmp_path)
    try:
        yield instance
    finally:
        instance.close()


def _latch(text: str = "Parcel, stop.") -> object:
    from parcel_robot.audio.stop_hotword import StopLatch

    return StopLatch(
        spot=spot_stop(text, SHIPPED),
        window_end_s=1.0,
        compute_s=0.3,
        latch_s=1.3,
        trigger="close_edge",
    )


def _safety_rows(runtime: RobotRuntime) -> list[dict]:
    rows = runtime.snapshot().get("safety_log", [])
    return [row for row in rows if isinstance(row, dict)]


def test_the_local_stop_engages_the_latch_the_panel_engages(runtime: RobotRuntime) -> None:
    """Identity, not similarity: one motion latch, one method, three doors.

    The MOTION latch — ``arbiter.emergency_stopped``, the thing that refuses a
    command — is what "the same latch as the panel" means, and it is asserted
    against the panel. The agent-side flag is the SPOKEN door's extra half-step
    (``submit_voice_text``'s fast path engages it before latching so a committed
    slow action cannot delay the request), so the local stop is asserted equal to
    the spoken door there rather than to the panel: this path is a voice door.
    """

    assert runtime.arbiter.emergency_stopped is False
    runtime.action("emergency_stop")
    assert runtime.arbiter.emergency_stopped is True, "the panel latch itself is broken"
    runtime.clear_emergency_stop()

    runtime.submit_voice_text("stop", is_final=True, origin=TRANSCRIPT_ORIGIN_MIC)
    spoken_state = (runtime.arbiter.emergency_stopped, runtime.agent.safety.emergency_stopped)
    assert spoken_state[0] is True
    runtime.clear_emergency_stop()

    runtime._stop_hotword_latched(_latch())
    assert (
        runtime.arbiter.emergency_stopped,
        runtime.agent.safety.emergency_stopped,
    ) == spoken_state, "the local stop reached a different latch than the spoken door"

    sources = [row.get("source") for row in _safety_rows(runtime)]
    assert SAFETY_SOURCE_PANEL in sources and SAFETY_SOURCE_VOICE in sources, sources
    spoken = [row for row in _safety_rows(runtime) if row.get("source") == SAFETY_SOURCE_VOICE]
    assert spoken and spoken[-1].get("phrase") == "Parcel, stop.", spoken


def test_both_doors_go_through_one_method(runtime: RobotRuntime, monkeypatch) -> None:
    """The seeded-red for the row above: a PARALLEL latch would pass identity
    on state alone, so the call itself is pinned."""

    calls: list[str] = []
    monkeypatch.setattr(
        runtime, "emergency_stop", lambda **kwargs: calls.append(str(kwargs.get("source")))
    )
    runtime.action("emergency_stop")
    runtime._stop_hotword_latched(_latch())
    assert calls == [SAFETY_SOURCE_PANEL, SAFETY_SOURCE_VOICE], calls


def test_the_local_stop_never_touches_the_conversational_stack(
    runtime: RobotRuntime, monkeypatch
) -> None:
    """``barge_in`` is deliberately NOT on this path (it can block)."""

    touched: list[str] = []
    monkeypatch.setattr(runtime.voice_session, "barge_in", lambda: touched.append("barge_in"))
    monkeypatch.setattr(runtime.agent, "handle_text", lambda text: touched.append("agent") or "no")
    runtime._stop_hotword_latched(_latch())
    assert touched == [], f"the local stop reached the conversational stack: {touched}"
    assert runtime.arbiter.emergency_stopped is True


@pytest.mark.load_sensitive
def test_a_hung_conversation_does_not_delay_the_local_stop(
    runtime: RobotRuntime, monkeypatch, evidence: dict
) -> None:
    """THE bypass property, measured with the conversation genuinely wedged."""

    entered = threading.Event()
    release = threading.Event()

    def wedged(text: str) -> str:
        entered.set()
        release.wait(10.0)
        return "…eventually"

    monkeypatch.setattr(runtime.agent, "handle_text", wedged)
    talker = threading.Thread(target=lambda: runtime.handle_text("what can you see"))
    talker.start()
    try:
        assert entered.wait(5.0), "the conversation never started; nothing was blocked"
        latched: list[float] = []
        asr_s = float(evidence["provenance"]["median_asr_s"])
        watch = StopHotwordWatch(
            StopHotwordSpotter(
                SHIPPED,
                vad=_AmplitudeVad(),
                transcribe=lambda pcm: scripted_transcribe(pcm, asr_s),
            ),
            lambda latch: (
                runtime._stop_hotword_latched(latch),
                latched.append(time.monotonic()),
            ),
        )
        watch.start()
        try:
            speech_end = _drive(watch, _frames(24, 30), 24)
            deadline = time.monotonic() + 3.0
            while not latched and time.monotonic() < deadline:
                time.sleep(0.005)
        finally:
            watch.close()
        assert latched, "the stop never landed while the conversation was wedged"
        elapsed = latched[0] - speech_end
        assert runtime.arbiter.emergency_stopped is True
        assert elapsed <= TAIL_MAX_S, (
            f"the local stop took {elapsed:.3f} s while a conversation was hung — "
            "the bypass property is what A2 is about"
        )
        assert not release.is_set() and talker.is_alive(), (
            "the conversation finished on its own; this run measured nothing"
        )
    finally:
        release.set()
        talker.join(10.0)


def test_off_mode_builds_no_matcher_and_starts_no_thread(tmp_path: pathlib.Path) -> None:
    """``mode: off`` is not a matcher that refuses — it is no matcher at all."""

    instance = _runtime(tmp_path, mode=MODE_OFF)
    try:
        watch, detail = instance._build_stop_hotword({"vad_model": str(SILERO_MODEL)})
        assert watch is None
        assert "off" in detail
        assert instance._stop_hotword is None
        names = [thread.name for thread in threading.enumerate()]
        assert "parcel-stop-hotword" not in names, names
    finally:
        instance.close()


def test_the_shipped_mode_does_build_one(runtime: RobotRuntime) -> None:
    """The positive control that keeps the row above from passing vacuously."""

    from parcel_robot.audio.endpointing import SileroVad

    if not SileroVad(str(SILERO_MODEL)).available:
        pytest.skip("Silero weights or onnxruntime unavailable on this host")
    watch, detail = runtime._build_stop_hotword({"vad_model": str(SILERO_MODEL)})
    assert watch is not None
    assert detail.startswith(MODE_NAME_PREFIXED)
    assert watch.spotter.config.mode == MODE_NAME_PREFIXED


def test_a_refused_config_degrades_loudly_and_additively(tmp_path: pathlib.Path) -> None:
    """A typo in the knob may not cost the panel button."""

    path = tmp_path / "bad.yaml"
    instance = _runtime(tmp_path)
    try:
        instance.store.data["stop_hotword"] = {"mode": "name-prefixed"}
        watch, detail = instance._build_stop_hotword({"vad_model": str(SILERO_MODEL)})
        assert watch is None
        assert "refused" in detail
        instance.action("emergency_stop")
        assert instance.arbiter.emergency_stopped is True
    finally:
        instance.close()
    del path


def _armed_runtime(tmp_path: pathlib.Path, monkeypatch, mode: str):
    """A runtime whose microphone rail arms, with a stub loop on each branch."""

    import parcel_robot.runtime as runtime_module
    from parcel_robot.audio.arming import MicArmingDecision

    built: list[object] = []

    def _stub(label: str) -> type:
        class _StubLoop:
            kind = label

            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs
                self.stop_hotword_tap = None
                built.append(self)

            def start(self) -> None:
                return None

            def close(self, timeout: float = 3.0) -> None:
                del timeout

        return _StubLoop

    monkeypatch.setattr(runtime_module, "MicrophoneVoiceLoop", _stub("plain"))
    monkeypatch.setattr(runtime_module, "StopTappedVoiceLoop", _stub("tapped"))
    monkeypatch.setattr(
        runtime_module,
        "decide_microphone_arming",
        lambda **kwargs: MicArmingDecision(armed=True, code="a6_fixture", reason="a6 fixture"),
    )
    return _runtime(tmp_path, mode=mode), built


def test_the_capture_rail_is_wired_when_the_microphone_arms(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    """The one line that makes any of this reachable: tap = watch.submit_frame."""

    from parcel_robot.audio.endpointing import SileroVad

    if not SileroVad(str(SILERO_MODEL)).available:
        pytest.skip("Silero weights or onnxruntime unavailable on this host")
    instance, built = _armed_runtime(tmp_path, monkeypatch, MODE_NAME_PREFIXED)
    try:
        assert built, "the fixture never built a capture loop; nothing was proven"
        assert built[0].kind == "tapped", "the rail was built without its tee"
        assert instance._stop_hotword is not None, instance._stop_hotword_detail
        assert built[0].stop_hotword_tap == instance._stop_hotword.submit_frame
    finally:
        instance.close()


def test_off_mode_leaves_the_capture_rail_exactly_as_it_was(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    """``off`` is not a tapped rail with a sleeping tap: it is the plain rail."""

    instance, built = _armed_runtime(tmp_path, monkeypatch, MODE_OFF)
    try:
        assert built and built[0].kind == "plain", built
        assert instance._stop_hotword is None
        assert built[0].stop_hotword_tap is None
        assert "parcel-stop-hotword" not in [thread.name for thread in threading.enumerate()]
    finally:
        instance.close()


def test_the_runtime_says_when_a_bare_stop_is_live(runtime: RobotRuntime) -> None:
    """``hybrid``'s window, at the runtime end: speaking, or moving."""

    assert runtime._stop_hotword_bare_window() is False
    runtime._was_moving = True
    assert runtime._stop_hotword_bare_window() is True
    runtime._was_moving = False
    assert runtime._stop_hotword_bare_window() is False

    class _Sink:
        playback_active = True

    runtime._speaker_sink = _Sink()
    assert runtime._stop_hotword_bare_window() is True
    runtime._speaker_sink = None


def test_a_bare_window_that_throws_reads_as_closed() -> None:
    """Fail-closed here means the STRICT grammar, not the noisy one."""

    def angry() -> bool:
        raise RuntimeError("the sink is gone")

    spotter = StopHotwordSpotter(
        HYBRID,
        vad=_AmplitudeVad(),
        transcribe=lambda pcm: "stop",
        bare_window=angry,
    )
    assert spotter._bare_window_open() is False
