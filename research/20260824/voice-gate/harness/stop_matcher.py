#!/usr/bin/env python
"""STOP-LOCAL: the always-local spoken stop the product does not have yet.

``realtime/lane.py:47-53`` says it plainly — "A spoken 'stop' during a hosted
session is transcribed in the cloud. It is supplemental." Addendum A2 makes an
always-local stop a build gate; this module is the reference implementation that
gate's acceptance is measured against, and it lives in the research folder until
its bars pass.

THE SHAPE
---------
Silero decides *when* to listen hard; a small resident whisper decides *what*
was said. There is no dialogue, no identity check, no network and no runtime in
the path — by construction, because A2's point is that a stop that needs any of
those is not a stop.

```
frames -> Silero (32 ms) -> speech? -> every CADENCE_MS, transcribe the trailing
          WINDOW_S -> whole-word "stop"/"halt"/"freeze" -> LATCH
```

THE CLOCK, AND WHY IT IS HONEST
-------------------------------
Rows are scored off a tape, but the latency is not free-running: each ASR call's
REAL wall time is measured and added to the tape position of the window it
consumed, and a second call cannot start while the first is in flight. So a
transcriber too slow to keep up produces late latches here exactly as it would
in a room. What this does NOT include is the acoustic path and the audio
driver's own buffering (~1 frame), and it does not include the physical stop
that follows the latch — the A5 envelope owns that.

WHOLE WORD, ON PURPOSE
----------------------
"The driver stopped at the intersection" is in the television tape deliberately.
A substring match on ``stop`` latches on it; the matcher requires the whole word
and the false-STOP row reports both numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from parcel_robot.audio.endpointing import SileroVad

from .asr import RATE_HZ, WhisperClient

FRAME_SAMPLES = 512
FRAME_S = FRAME_SAMPLES / RATE_HZ
SILERO_MODEL = Path(__file__).resolve().parents[4] / "models" / "endpointing" / "silero_vad_v6.onnx"

#: Words that latch the stop. Kept tiny: every extra word is another false STOP.
STOP_WORDS = frozenset({"stop", "halt", "freeze"})


@dataclass(frozen=True)
class StopConfig:
    vad_threshold: float = 0.5
    open_frames: int = 2
    window_s: float = 1.0
    cadence_s: float = 0.30
    #: Speech must have been seen this recently for a check to be worth running.
    speech_hold_s: float = 0.6


@dataclass
class StopEvent:
    """One latch: when the tape said it, when the matcher had it, on what text."""

    latch_tape_s: float
    window_end_tape_s: float
    asr_latency_s: float
    text: str
    substring_only: bool = False


@dataclass
class StopRun:
    #: Latches the matcher actually made: whole word only.
    events: list[StopEvent] = field(default_factory=list)
    #: Latches a SUBSTRING matcher would have made and this one refused
    #: ("the driver stopped"). Reported so the rule's cost is visible.
    substring_events: list[StopEvent] = field(default_factory=list)
    checks: int = 0
    skipped_busy: int = 0
    asr_seconds: float = 0.0
    tape_seconds: float = 0.0


def _has_stop_word(words: list[str]) -> bool:
    return any(word in STOP_WORDS for word in words)


def _has_stop_substring(words: list[str]) -> bool:
    return any(word.startswith(("stop", "halt")) for word in words)


def run_stop_matcher(
    tape: np.ndarray,
    client: WhisperClient,
    *,
    config: StopConfig | None = None,
    model_path: Path = SILERO_MODEL,
    latch_once: bool = False,
) -> StopRun:
    """Stream ``tape`` (int16 mono 16 kHz) through STOP-LOCAL and report latches."""

    config = config or StopConfig()
    vad = SileroVad(str(model_path), threshold=config.vad_threshold)
    if not vad.available:  # pragma: no cover - a missing model is a loud failure
        raise RuntimeError(f"Silero model unavailable at {model_path}")
    run = StopRun(tape_seconds=tape.size / RATE_HZ)
    window_samples = int(config.window_s * RATE_HZ)
    above = 0
    last_speech_s = -1e9
    next_check_s = 0.0
    busy_until_s = -1e9
    total = tape.size // FRAME_SAMPLES
    for index in range(total):
        frame = tape[index * FRAME_SAMPLES : (index + 1) * FRAME_SAMPLES]
        now = (index + 1) * FRAME_S
        if vad.process(frame) >= config.vad_threshold:
            above += 1
        else:
            above = 0
        if above >= config.open_frames:
            last_speech_s = now
        if now - last_speech_s > config.speech_hold_s:
            continue
        if now < next_check_s:
            continue
        if now < busy_until_s:
            run.skipped_busy += 1
            continue
        end_sample = (index + 1) * FRAME_SAMPLES
        window = tape[max(0, end_sample - window_samples) : end_sample]
        transcript = client.transcribe(window.astype(np.float64) / 32768.0)
        run.checks += 1
        run.asr_seconds += transcript.latency_s
        busy_until_s = now + transcript.latency_s
        next_check_s = now + config.cadence_s
        words = transcript.words()
        whole_word = _has_stop_word(words)
        if whole_word or _has_stop_substring(words):
            event = StopEvent(
                latch_tape_s=now + transcript.latency_s,
                window_end_tape_s=now,
                asr_latency_s=transcript.latency_s,
                text=transcript.text,
                substring_only=not whole_word,
            )
            if whole_word:
                run.events.append(event)
            else:
                run.substring_events.append(event)
            if whole_word and latch_once:
                break
    return run


__all__ = [
    "FRAME_S",
    "SILERO_MODEL",
    "STOP_WORDS",
    "StopConfig",
    "StopEvent",
    "StopRun",
    "run_stop_matcher",
]
