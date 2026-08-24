"""A local Silero gate in front of the socket, and the tape it is measured on.

This is the P1 mechanism: the thing that decides when audio is worth paying to
upload. It is deliberately NOT wired into ``lane.send_audio`` — H1 measures the
gate, and the milestone card wires it.

THE GATE
--------
Streaming Silero v6 at 16 kHz in 512-sample (32 ms) frames, with the three
parameters that matter and nothing else:

``open_frames``
    consecutive frames above threshold before the socket opens. Debounce.
``hangover_ms``
    silence tolerated before it closes. This is the endpoint latency (C4) and
    the reason a gate cannot be arbitrarily tight: it is also what keeps a
    mid-sentence breath from cutting the owner off.
``preroll_ms``
    a ring buffer of audio kept BEHIND the open moment and uploaded with it.
    Without one, every first word is lost — the gate cannot know speech started
    until after it has started. C3 measures exactly this.

THE TAPE
--------
Real fixture audio placed on a synthetic timeline, because there is no
12-hour recording of this owner's living room and there will not be one before
the array campaign. Two tapes:

``owner``
    the 22 frozen ``acoustic_loop_v1`` utterances, at the corpus day's measured
    speech duty cycle, separated by digital silence with a small dither floor.
``ambient``
    the same hour with no owner in it: the two non-speech noise fixtures on
    repeat (C5's "TV noise"), and — separately — attenuated speech, which is
    what a television across the room actually is.

The silence is SYNTHETIC and that is the headline caveat of every P1 number:
a real room has a noise floor, and a VAD's false-open rate is a function of that
floor. The ambient tape's dither is a stand-in, not a measurement.
"""

from __future__ import annotations

import wave
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from parcel_robot.audio.endpointing import SileroVad
from parcel_robot.realtime.audio_gateway import RationalResampler

SAMPLE_RATE_HZ = 16_000
FRAME_SAMPLES = 512
FRAME_MS = FRAME_SAMPLES / SAMPLE_RATE_HZ * 1000.0
SILERO_MODEL = Path(__file__).resolve().parents[3] / "models" / "endpointing" / "silero_vad_v6.onnx"


def read_wav_16k(path: Path) -> np.ndarray:
    """One mono fixture as int16 PCM at 16 kHz, through the product's resampler.

    int16 and not float, because that is what ``SileroVad.process`` takes and
    what a microphone hands the gateway. Nothing is converted twice.
    """

    with wave.open(str(path)) as handle:
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    if rate != SAMPLE_RATE_HZ:
        samples = RationalResampler(from_hz=rate, to_hz=SAMPLE_RATE_HZ).process(samples)
    return to_pcm16(samples)


def to_pcm16(samples: np.ndarray) -> np.ndarray:
    """Float in [-1, 1] to int16, clipped rather than wrapped."""

    scaled = np.rint(np.asarray(samples, dtype=np.float64) * 32768.0)
    return np.clip(scaled, -32768.0, 32767.0).astype(np.int16)


@dataclass
class Placement:
    """Where one utterance ended up on the tape, in tape seconds."""

    name: str
    kind: str
    start_s: float
    speech_start_s: float
    speech_end_s: float
    energy_onset_s: float


@dataclass
class Tape:
    """A synthetic listening period with real audio in it."""

    samples: np.ndarray
    placements: list[Placement] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return self.samples.size / SAMPLE_RATE_HZ


def energy_onset_s(clip: np.ndarray, *, floor_db: float = 30.0) -> float:
    """First sample more than ``floor_db`` above the clip's quietest window.

    An onset ground truth that does NOT come from Silero. The corpus's own
    ``speech_start_s`` is the last/first Silero frame of an offline pass, so
    measuring a Silero gate against it would be partly circular; this is an
    independent, dumb, energy-only witness, and C3 is reported against the
    EARLIER of the two.
    """

    window = 256
    usable = clip.size - clip.size % window
    if usable <= 0:
        return 0.0
    blocks = clip[:usable].astype(np.float64).reshape(-1, window)
    rms = np.sqrt(np.maximum(1e-12, (blocks**2).mean(axis=1)))
    floor = float(np.percentile(rms, 5.0))
    threshold = floor * (10.0 ** (floor_db / 20.0))
    hits = np.flatnonzero(rms >= threshold)
    if hits.size == 0:
        return 0.0
    return float(hits[0] * window / SAMPLE_RATE_HZ)


def build_tape(
    clips: Sequence[tuple[str, str, np.ndarray, float, float]],
    *,
    gap_s: float,
    dither: float,
    seed: int,
    lead_s: float = 2.0,
) -> Tape:
    """Lay clips on a silent timeline separated by ``gap_s`` of dithered silence."""

    rng = np.random.default_rng(seed)

    def silence(seconds: float) -> np.ndarray:
        count = round(seconds * SAMPLE_RATE_HZ)
        if count <= 0:
            return np.zeros(0, dtype=np.int16)
        return to_pcm16(rng.standard_normal(count) * dither)

    pieces: list[np.ndarray] = [silence(lead_s)]
    placements: list[Placement] = []
    cursor = lead_s
    for name, kind, clip, speech_start, speech_end in clips:
        placements.append(
            Placement(
                name=name,
                kind=kind,
                start_s=cursor,
                speech_start_s=cursor + speech_start,
                speech_end_s=cursor + speech_end,
                energy_onset_s=cursor + energy_onset_s(clip),
            )
        )
        pieces.append(clip)
        cursor += clip.size / SAMPLE_RATE_HZ
        pieces.append(silence(gap_s))
        cursor += gap_s
    return Tape(samples=np.concatenate(pieces), placements=placements)


@dataclass(frozen=True)
class GateConfig:
    threshold: float = 0.5
    open_frames: int = 2
    hangover_ms: float = 500.0
    preroll_ms: float = 500.0


@dataclass(frozen=True)
class GateSpan:
    """One interval the gate decided to pay for."""

    open_s: float
    close_s: float
    #: Where the uploaded audio actually begins once the pre-roll is flushed.
    upload_from_s: float

    @property
    def uploaded_s(self) -> float:
        return max(0.0, self.close_s - self.upload_from_s)


def run_gate(tape: Tape, config: GateConfig, *, model_path: Path = SILERO_MODEL) -> list[GateSpan]:
    """Stream the tape through Silero and return the intervals the gate opened.

    One VAD instance for the whole tape: the model is stateful and restarting it
    per utterance would hand the gate a warm start it will not have in a room.
    """

    vad = SileroVad(str(model_path), threshold=config.threshold)
    if not vad.available:  # pragma: no cover - a missing model is a loud failure
        raise RuntimeError(f"Silero model unavailable at {model_path}")
    hangover_frames = max(1, round(config.hangover_ms / FRAME_MS))
    spans: list[GateSpan] = []
    above = 0
    quiet = 0
    open_at: float | None = None
    total = tape.samples.size // FRAME_SAMPLES
    for index in range(total):
        frame = tape.samples[index * FRAME_SAMPLES : (index + 1) * FRAME_SAMPLES]
        probability = vad.process(frame)
        now = (index + 1) * FRAME_SAMPLES / SAMPLE_RATE_HZ
        speech = probability >= config.threshold
        if speech:
            above += 1
            quiet = 0
        else:
            above = 0
            quiet += 1
        if open_at is None:
            if above >= config.open_frames:
                open_at = now
                spans.append(
                    GateSpan(
                        open_s=now,
                        close_s=now,
                        upload_from_s=max(0.0, now - config.preroll_ms / 1000.0),
                    )
                )
        elif quiet >= hangover_frames:
            last = spans[-1]
            spans[-1] = GateSpan(last.open_s, now, last.upload_from_s)
            open_at = None
    if open_at is not None:
        last = spans[-1]
        spans[-1] = GateSpan(last.open_s, tape.seconds, last.upload_from_s)
    return spans


__all__ = [
    "FRAME_MS",
    "FRAME_SAMPLES",
    "SAMPLE_RATE_HZ",
    "SILERO_MODEL",
    "GateConfig",
    "GateSpan",
    "Placement",
    "Tape",
    "build_tape",
    "energy_onset_s",
    "read_wav_16k",
    "run_gate",
    "to_pcm16",
]
