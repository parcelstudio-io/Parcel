"""STOP-LOCAL: the always-local spoken stop (card A6, scrum/20260824/task_2).

WHY THIS MODULE EXISTS
----------------------
``realtime/lane.py:47-53`` says it plainly — "A spoken 'stop' during a hosted
session is transcribed in the cloud. It is supplemental." Addendum A2 turned
that into a build gate: today's cloud-independent stops are the panel button,
the operator remote and the local watchdogs, and a spoken stop that needs the
network is not a stop. This module is the local path, and it is deliberately
the thinnest thing that can work: Silero decides WHEN to listen hard, a small
local transcriber decides WHAT was said, a whole-word grammar decides whether
that was a stop, and the latch is the SAME one the panel button engages.

WHAT IT MUST NOT DO
-------------------
It gates nothing. The physical remote, the panel STOP, ``core/hard_stop.py``
and every watchdog are untouched by this file and keep working when it is off,
mis-configured, or dead — it is an ADDITIVE door onto the existing latch, never
a stage anything else passes through. It also never reaches the dialogue, the
identity gate, the wake gating or the hosted lane: A2's point is that a stop
which depends on any of those is not a stop, and :class:`StopHotwordWatch`
therefore owns its own thread and its own transcriber.

THE GRAMMAR POLICY, AND THE MEASUREMENT THAT SET IT
---------------------------------------------------
VOICE-GATE v2 (``research/20260824/voice-gate/``) measured a bare "stop"
spotter on ordinary television audio: **six false latches in ten minutes of
tape — ≈ 864 per 24 h**, against A9's bar of ≤ 1 per 24 h. The transcripts are
the argument: ``stop talking to me``, ``stop at the intersection``,
``I'm not going to stop the tattoo``. "Stop" is an ordinary English word, and a
matcher that may not consult identity cannot also be rare. **None of the six
false triggers contained the dog's name.** Hence three modes behind one knob:

``name_prefixed`` (DEFAULT)
    "<name>, stop". Scored **0** false triggers on the same tape. The cost is
    real and stated: a bare shouted "Stop!" no longer latches this path (the
    panel, the remote and the watchdogs still do).
``hybrid``
    name-prefixed always, plus bare "stop" ONLY while ``bare_window`` is open —
    the dog is speaking or executing an owner-commanded motion, the context in
    which the prior shifts and in which a bare stop is most likely to be aimed
    at the robot. The window logic is unit-proven; its false rate through air is
    NOT measured (box-day, mounted acoustics).
``bare``
    available and **failing the bar**: ≈ 864 false STOPs/24 h as measured. It is
    kept because an operator may knowingly want it on a quiet rig, and because
    the honest number belongs beside the option, not in a footnote.

Whole-word matching throughout: the VOICE-GATE rule correctly refused
``stopped at the meeting`` and ``stopping to tell me``, which a substring
matcher latches on. The stop vocabulary is NOT copied here — it is read from
:func:`~parcel_robot.voice.closed_intents.closed_intent_phrases`, because U33
was two copies of a stop grammar that disagreed. (``freeze`` is in the harness
reference and is NOT a stop here: this product maps it to PAUSE, and the
product's own grammar wins.)

THE CLOCK
---------
:class:`StopHotwordSpotter` stamps every latch with the position of the audio
window that produced it plus the REAL wall time its transcriber and matcher
spent. Fed monotonic stamps it reports the true latch instant; fed tape
positions it reports the harness's honest replay clock. What neither includes
is the acoustic path, the driver's own buffering, and the physical stop that
follows the latch — the A5 envelope owns that last one.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

import numpy as np

from parcel_robot.audio.voice_loop import MicrophoneVoiceLoop
from parcel_robot.voice.closed_intents import ClosedIntent, closed_intent_phrases

#: Silero v6 wants exactly this many samples at 16 kHz; capture frames are 480.
SILERO_FRAME_SAMPLES = 512
SAMPLE_RATE_HZ = 16_000
SILERO_FRAME_S = SILERO_FRAME_SAMPLES / SAMPLE_RATE_HZ

MODE_NAME_PREFIXED = "name_prefixed"
MODE_HYBRID = "hybrid"
MODE_BARE = "bare"
MODE_OFF = "off"
#: Every mode this knob accepts. ``off`` builds no matcher and starts no thread.
STOP_HOTWORD_MODES = (MODE_NAME_PREFIXED, MODE_HYBRID, MODE_BARE, MODE_OFF)
#: The modes whose grammar requires a configured name.
NAMED_MODES = frozenset({MODE_NAME_PREFIXED, MODE_HYBRID})

#: The product's own stop grammar, tokenized. Read from the closed-intent set
#: rather than re-typed: U33 (2026-08-07) was exactly this list existing twice.
STOP_PHRASES: tuple[tuple[str, ...], ...] = tuple(
    sorted(
        (tuple(phrase.split()) for phrase in closed_intent_phrases(ClosedIntent.STOP)),
        key=lambda words: (-len(words), words),
    )
)

#: The dog's name. No other product surface carries one today (grepped: the
#: personality files name a POLICY, not the animal), so the name lives with the
#: grammar that needs it and is validated non-empty for the named modes.
DEFAULT_STOP_NAME = "parcel"

_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyz")


def normalize_words(text: object) -> tuple[str, ...]:
    """Lowercase a transcript to bare alphabetic words.

    The same normalization the VOICE-GATE matcher used, and the reason
    ``"Stop."`` from a transcriber matches while ``"stopped"`` does not.
    """

    folded = str(text).lower()
    kept = "".join(character if character in _LETTERS else " " for character in folded)
    return tuple(word for word in kept.split() if word)


@dataclass(frozen=True)
class StopHotwordConfig:
    """The ``stop_hotword:`` knob. Fail-closed; unknown keys are refused."""

    mode: str = MODE_NAME_PREFIXED
    name: str = DEFAULT_STOP_NAME
    #: Silero speech probability that counts as speech.
    vad_threshold: float = 0.5
    #: Consecutive Silero frames above threshold that open a span.
    open_frames: int = 2
    #: Consecutive frames below threshold that CLOSE a span. The close edge is
    #: the trigger that made this path meet A9's tail bar where the free-running
    #: cadence of the research reference did not: an utterance's end is exactly
    #: when its hotword ended, so the transcriber is asked THERE instead of at
    #: the next 300 ms tick.
    close_frames: int = 3
    #: Trailing audio handed to the transcriber. Long enough for "<name>, stop".
    window_s: float = 1.6
    #: Mid-utterance sweep, so a stop inside a long sentence is not held until
    #: the sentence ends. It is a FLOOR: the spotter paces itself by whatever
    #: its transcriber actually costs, because a cadence faster than the
    #: transcriber does not buy checks, it buys a backlog (measured: with a
    #: fixed 300 ms cadence and a 370 ms transcriber, a sustained talker put the
    #: spotter a check further behind every check, and the latch arrived after
    #: the sentence it was about had ended).
    cadence_s: float = 0.30
    #: How many words may sit between the name and the stop word.
    name_gap_words: int = 3
    #: One utterance may only latch once; a second latch inside this window is
    #: the same words arriving in two overlapping transcription windows.
    relatch_holdoff_s: float = 2.0
    #: Capture-thread queue depth (frames). 256 x 30 ms = 7.7 s of slack.
    queue_frames: int = 256

    def __post_init__(self) -> None:
        if self.mode not in STOP_HOTWORD_MODES:
            raise ValueError(
                f"stop_hotword.mode must be one of {', '.join(STOP_HOTWORD_MODES)}, "
                f"got {self.mode!r}"
            )
        if self.mode in NAMED_MODES and not normalize_words(self.name):
            raise ValueError(
                f"stop_hotword.mode={self.mode} needs stop_hotword.name: the grammar "
                "IS the name, and an empty one silently degrades to the bare spotter "
                "that measured 864 false stops per 24 h"
            )
        _require_range("vad_threshold", self.vad_threshold, 0.0, 1.0)
        _require_range("window_s", self.window_s, 0.3, 5.0)
        _require_range("cadence_s", self.cadence_s, 0.05, 2.0)
        _require_range("relatch_holdoff_s", self.relatch_holdoff_s, 0.0, 30.0)
        _require_whole("open_frames", self.open_frames, 1, 20)
        _require_whole("close_frames", self.close_frames, 1, 40)
        _require_whole("name_gap_words", self.name_gap_words, 0, 12)
        _require_whole("queue_frames", self.queue_frames, 8, 4096)

    @property
    def name_words(self) -> tuple[str, ...]:
        return normalize_words(self.name)

    @property
    def window_samples(self) -> int:
        return int(self.window_s * SAMPLE_RATE_HZ)

    @classmethod
    def from_mapping(cls, section: Mapping[str, object] | None) -> StopHotwordConfig:
        """Build from a config section, refusing an unknown key by name.

        The spelling guard has to live here. ``configs/robot.yaml`` is
        SHA-locked, so the section arrives through the profile-overlay escape
        hatch (``config.OVERLAY_INTRODUCIBLE_KEYS``), and that hatch exempts the
        whole subtree — without this check ``stop_hotword: {moode: bare}`` would
        merge cleanly and boot the shipped default while the file said otherwise.
        """

        if section is None:
            return cls()
        if not isinstance(section, Mapping):
            raise TypeError("stop_hotword config section must be a mapping")
        allowed = {field for field in cls.__dataclass_fields__}
        unknown = sorted(str(key) for key in section if str(key) not in allowed)
        if unknown:
            raise ValueError(
                f"unknown stop_hotword config key(s): {', '.join(unknown)}; "
                f"allowed: {', '.join(sorted(allowed))}"
            )
        config = cls()
        for key, value in section.items():
            config = replace(
                config, **{str(key): _coerce(str(key), value, getattr(config, str(key)))}
            )
        return config


def _coerce(key: str, value: object, current: object) -> object:
    if isinstance(current, str):
        return str(value)
    if isinstance(current, bool):
        raise TypeError(f"stop_hotword.{key} is not a flag")
    if isinstance(current, int):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"stop_hotword.{key} must be a whole number, got {value!r}")
        if value != int(value):
            raise ValueError(f"stop_hotword.{key} must be a whole number, got {value!r}")
        return int(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"stop_hotword.{key} must be a number, got {value!r}")
    return float(value)


def _require_range(key: str, value: float, low: float, high: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"stop_hotword.{key} must be a number, got {value!r}")
    if not math.isfinite(float(value)) or not low <= float(value) <= high:
        raise ValueError(f"stop_hotword.{key} must be within [{low}, {high}], got {value!r}")


def _require_whole(key: str, value: int, low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"stop_hotword.{key} must be a whole number, got {value!r}")
    if not low <= value <= high:
        raise ValueError(f"stop_hotword.{key} must be within [{low}, {high}], got {value}")


@dataclass(frozen=True)
class StopSpot:
    """One transcript the grammar accepted, and what authorized it."""

    text: str
    phrase: str
    mode: str
    #: True when the dog's name authorized this latch; False when the bare
    #: window did (``hybrid``) or when the mode is ``bare``.
    named: bool
    bare_window_open: bool = False


def _phrase_span(words: tuple[str, ...]) -> tuple[int, int, str] | None:
    """Earliest whole-word stop phrase in ``words`` as ``(start, end, phrase)``."""

    for index in range(len(words)):
        for phrase in STOP_PHRASES:
            end = index + len(phrase)
            if words[index:end] == phrase:
                return index, end, " ".join(phrase)
    return None


def _name_near(words: tuple[str, ...], span: tuple[int, int], config: StopHotwordConfig) -> bool:
    """Is the dog's name within ``name_gap_words`` of the stop phrase?

    Either side. The MEASURED claim is about the prefix form ("Parcel, stop"),
    and the widening to a trailing name ("stop, Parcel") is deliberate: the
    false-trigger evidence is that none of the television transcripts contained
    the name ANYWHERE, so accepting it on either side costs nothing measured and
    buys the phrasing a person actually uses. ``tests/test_a6_stop_local.py``
    re-scores the recorded tape under this exact rule.
    """

    name = config.name_words
    if not name:
        return False
    start, end = span
    low = max(0, start - config.name_gap_words - len(name) + 1)
    high = min(len(words), end + config.name_gap_words + len(name) - 1)
    window = words[low:high]
    return any(window[index : index + len(name)] == name for index in range(len(window)))


def spot_stop(
    text: object,
    config: StopHotwordConfig,
    *,
    bare_window_open: bool = False,
) -> StopSpot | None:
    """Decide whether one transcript is a local STOP under ``config``.

    Pure: no clock, no audio, no I/O. This is the function the false-trigger
    rows are re-scored through, which is why it takes text rather than samples.
    """

    if config.mode == MODE_OFF:
        return None
    words = normalize_words(text)
    span = _phrase_span(words)
    if span is None:
        return None
    start, end, phrase = span
    named = _name_near(words, (start, end), config)
    if config.mode == MODE_NAME_PREFIXED and not named:
        return None
    if config.mode == MODE_HYBRID and not named and not bare_window_open:
        return None
    return StopSpot(
        text=str(text),
        phrase=phrase,
        mode=config.mode,
        named=named,
        bare_window_open=bool(bare_window_open),
    )


@dataclass(frozen=True)
class StopLatch:
    """A latch decision with the clock that produced it."""

    spot: StopSpot
    #: Position (tape seconds, or monotonic) of the last sample in the window.
    window_end_s: float
    #: Real wall time the transcriber and the matcher spent on that window.
    compute_s: float
    #: ``window_end_s + compute_s`` — the instant the latch call is made.
    latch_s: float
    #: ``close_edge`` (speech ended) or ``cadence`` (mid-utterance sweep).
    trigger: str


class StopHotwordSpotter:
    """Streaming Silero span -> transcribe the trailing window -> grammar.

    Single-threaded and synchronous by construction: ``submit`` blocks for the
    transcription it decides to run, and :class:`StopHotwordWatch` is what keeps
    that off the capture thread. Fed a tape it is a deterministic replay of the
    VOICE-GATE reference; fed the live rail it is the product path.
    """

    def __init__(
        self,
        config: StopHotwordConfig,
        *,
        vad: object,
        transcribe: Callable[[np.ndarray], str],
        bare_window: Callable[[], bool] | None = None,
    ) -> None:
        if config.mode == MODE_OFF:
            raise ValueError("stop_hotword.mode=off builds no spotter")
        if not getattr(vad, "available", False):
            raise ValueError("stop hotword needs an available VAD (Silero model + onnxruntime)")
        self.config = config
        self.vad = vad
        self.transcribe = transcribe
        self.bare_window = bare_window
        self.checks = 0
        self.spans = 0
        self._tail = np.zeros(0, dtype=np.int16)
        self._ring = np.zeros(0, dtype=np.int16)
        self._above = 0
        self._below = 0
        self._speaking = False
        self._next_check_s = 0.0
        self._last_latch_s = -1e9
        #: What the transcriber cost last time, which is what paces the sweep.
        self._last_compute_s = 0.0

    def submit(self, frame: np.ndarray, now_s: float) -> StopLatch | None:
        """Consume one capture frame; return a latch when the grammar accepts."""

        samples = np.asarray(frame, dtype=np.int16).reshape(-1)
        self._ring = np.concatenate([self._ring, samples])[-self.config.window_samples :]
        trigger = self._vad_trigger(samples, now_s)
        if trigger is None:
            return None
        return self._check(now_s, trigger)

    def _vad_trigger(self, samples: np.ndarray, now_s: float) -> str | None:
        """Run Silero over the new audio and name the trigger, if any."""

        self._tail = np.concatenate([self._tail, samples])
        trigger: str | None = None
        while self._tail.size >= SILERO_FRAME_SAMPLES:
            window = self._tail[:SILERO_FRAME_SAMPLES]
            self._tail = self._tail[SILERO_FRAME_SAMPLES:]
            if float(self.vad.process(window)) >= self.config.vad_threshold:
                self._above += 1
                self._below = 0
            else:
                self._below += 1
                self._above = 0
            if not self._speaking and self._above >= self.config.open_frames:
                self._speaking = True
                self.spans += 1
                self._next_check_s = now_s + max(self.config.cadence_s, self._last_compute_s)
            elif self._speaking and self._below >= self.config.close_frames:
                self._speaking = False
                trigger = "close_edge"
        if trigger is not None:
            return trigger
        # A sweep is for audio that is still arriving. Once the talker has gone
        # quiet the close edge is at most ``close_frames`` away and covers the
        # same window, so a sweep here can only push the close-edge check behind
        # one more transcription. (It does not remove that risk: under a
        # backlog this decision is made on a frame that was quiet-free when it
        # ARRIVED, which is the single-in-flight cost the thread-tier row in
        # tests/test_a6_stop_local.py measures at ~780 ms worst case.)
        if self._speaking and self._below == 0 and now_s >= self._next_check_s:
            self._next_check_s = now_s + max(self.config.cadence_s, self._last_compute_s)
            return "cadence"
        return None

    def _check(self, now_s: float, trigger: str) -> StopLatch | None:
        started = time.monotonic()
        text = self.transcribe(self._ring.copy())
        self.checks += 1
        spot = spot_stop(text, self.config, bare_window_open=self._bare_window_open())
        compute_s = time.monotonic() - started
        self._last_compute_s = compute_s
        if spot is None:
            return None
        latch_s = now_s + compute_s
        if latch_s - self._last_latch_s < self.config.relatch_holdoff_s:
            return None
        self._last_latch_s = latch_s
        return StopLatch(
            spot=spot,
            window_end_s=now_s,
            compute_s=compute_s,
            latch_s=latch_s,
            trigger=trigger,
        )

    def _bare_window_open(self) -> bool:
        if self.config.mode != MODE_HYBRID or self.bare_window is None:
            return False
        try:
            return bool(self.bare_window())
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            # A window that cannot be read is CLOSED: the fail-closed direction
            # here is the strict grammar, not the noisy one.
            return False


class StopHotwordWatch:
    """The dedicated thread: frames in from capture, latch out to the runtime.

    ``submit_frame`` is called from the audio capture thread and never blocks —
    it is one bounded ``put_nowait``. Everything expensive (Silero, the
    transcriber, the grammar) happens on this thread, which shares no lock with
    the dialogue, the hosted lane or the voice session. That is the bypass
    property: a conversational pipeline that hangs cannot delay a stop, because
    a stop never touches it.
    """

    def __init__(
        self,
        spotter: StopHotwordSpotter,
        on_stop: Callable[[StopLatch], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self.spotter = spotter
        self.on_stop = on_stop
        self.clock = clock
        self.on_error = on_error
        self.frames_submitted = 0
        self.frames_dropped = 0
        self.latches = 0
        self.errors = 0
        self.last_latch: StopLatch | None = None
        self._queue: queue.Queue[tuple[np.ndarray, float]] = queue.Queue(
            maxsize=spotter.config.queue_frames
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def submit_frame(self, frame: np.ndarray) -> None:
        """Capture-thread entry point. Bounded, non-blocking, drop-oldest.

        The frame is stamped HERE, when the audio arrived, not when this
        thread gets to it. The spotter's clock has to be the audio's, or a
        transcription in flight (during which frames queue) makes every
        queued frame look simultaneous and fires a sweep per dequeue.
        """

        self.frames_submitted += 1
        stamped = (frame, self.clock())
        try:
            self._queue.put_nowait(stamped)
        except queue.Full:
            self.frames_dropped += 1
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(stamped)
            except (queue.Empty, queue.Full):
                pass

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("stop hotword watch is already running")
        self._thread = threading.Thread(
            target=self._run,
            name="parcel-stop-hotword",
            daemon=True,
        )
        self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frame, stamp = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._consume(frame, stamp)

    def _consume(self, frame: np.ndarray, stamp: float) -> None:
        """One frame, and the failure policy: never die, never mask, never stop."""

        try:
            latch = self.spotter.submit(frame, stamp)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.errors += 1
            self._report(error)
            return
        if latch is None:
            return
        self.latches += 1
        self.last_latch = latch
        try:
            self.on_stop(latch)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.errors += 1
            self._report(error)

    def _report(self, error: Exception) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(error)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass


class StopTappedVoiceLoop(MicrophoneVoiceLoop):
    """The capture rail with a one-way tee onto the stop path.

    A SUBCLASS rather than an edit to ``voice_loop.py`` for a stated reason:
    that module sits one line under the DEC-0 structural ceiling, and the
    decomposition program's whole point is that a card adds its code to its own
    module instead of growing a god-file (``scrum/20260823/DECOMP_PROGRAM_FABLE.md``).
    The seam is ``_handle_frame``, which is where every capture path — the
    device thread, ``run_once``, a replay — converges.

    The tee runs FIRST, on the RAW frame: the stop path may not inherit a
    failing AEC, an echo guard tuned for barge-in, or any decision the
    conversational stack makes about this audio. It is bounded and
    non-blocking by contract (:meth:`StopHotwordWatch.submit_frame` is one
    ``put_nowait``); a tap that misbehaves anyway is counted, dropped and
    logged, because a capture loop that dies is worse than a stop path that is
    missing.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        #: Set by the runtime once the watch exists. ``None`` makes this class
        #: byte-for-byte its parent.
        self.stop_hotword_tap: Callable[[np.ndarray], None] | None = None
        self.stop_hotword_tap_failures = 0

    def _handle_frame(self, frame: np.ndarray) -> None:
        tap = self.stop_hotword_tap
        if tap is not None:
            try:
                tap(frame)
            except (OSError, RuntimeError, TypeError, ValueError):
                self.stop_hotword_tap_failures += 1
                self.stop_hotword_tap = None
        super()._handle_frame(frame)


__all__ = [
    "DEFAULT_STOP_NAME",
    "MODE_BARE",
    "MODE_HYBRID",
    "MODE_NAME_PREFIXED",
    "MODE_OFF",
    "NAMED_MODES",
    "STOP_HOTWORD_MODES",
    "STOP_PHRASES",
    "StopHotwordConfig",
    "StopHotwordSpotter",
    "StopHotwordWatch",
    "StopLatch",
    "StopSpot",
    "StopTappedVoiceLoop",
    "normalize_words",
    "spot_stop",
]
