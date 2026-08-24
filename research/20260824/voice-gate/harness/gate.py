#!/usr/bin/env python
"""The pre-cloud rail: what opens the socket, and what never reaches it.

HLD §7.1 draws the rail this module implements — VAD/endpoint, then a
speaker/engagement/privacy gate, then either admission or an erased ring. The
two properties the consolidated pass rule cares about are structural, not
statistical, so they are built in rather than measured after the fact:

* **nothing is uploaded before the decision.** Audio accumulates locally until
  the arm has had its ``decision_window_s``; only then is the pre-roll flushed.
  So "zero hosted bytes for television" is a fact about the transport's byte
  counter, which is exactly where the DESIGN says to measure it.
* **rejection erases.** A refused span's buffer is dropped, and the transport
  never sees a byte of it.

The transport is FAKE. It counts what a real one would have been sent and
charges nothing; this study spends $0 hosted.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from parcel_robot.audio.endpointing import SileroVad

RATE_HZ = 16_000
FRAME_SAMPLES = 512
FRAME_S = FRAME_SAMPLES / RATE_HZ
SILERO_MODEL = Path(__file__).resolve().parents[4] / "models" / "endpointing" / "silero_vad_v6.onnx"


@dataclass(frozen=True)
class GateConfig:
    """H1's measured gate, plus the decision window the arms need."""

    threshold: float = 0.5
    open_frames: int = 2
    hangover_ms: float = 500.0
    preroll_ms: float = 500.0
    #: How much speech an arm may look at before it must decide.
    decision_window_s: float = 1.0


@dataclass(frozen=True)
class Placement:
    """One stimulus on the tape, and what it truthfully is."""

    name: str
    role: str
    voice: str
    text: str
    start_s: float
    speech_start_s: float
    speech_end_s: float
    geometry: str
    replay: bool


@dataclass
class Tape:
    samples: np.ndarray
    placements: list[Placement] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return self.samples.size / RATE_HZ

    def role_at(self, when_s: float) -> Placement | None:
        for placement in self.placements:
            if placement.speech_start_s - 0.6 <= when_s <= placement.speech_end_s + 0.8:
                return placement
        return None


@dataclass
class Decision:
    admit: bool
    reason: str
    score: float | None = None
    detail: str = ""


@dataclass
class Admission:
    """One span the gate considered, and what the arm did with it."""

    open_s: float
    close_s: float
    upload_from_s: float
    decided_s: float
    admitted: bool
    reason: str
    score: float | None
    detail: str
    source_role: str
    source_name: str
    uploaded_seconds: float
    uploaded_bytes: int


@dataclass
class FakeTransport:
    """What a hosted socket would have received. It receives nothing real."""

    opens: int = 0
    uploaded_seconds: float = 0.0
    uploaded_bytes: int = 0
    by_role: dict[str, int] = field(default_factory=dict)

    def send(self, samples: np.ndarray, role: str) -> None:
        self.opens += 1
        self.uploaded_seconds += samples.size / RATE_HZ
        payload = samples.size * 2
        self.uploaded_bytes += payload
        self.by_role[role] = self.by_role.get(role, 0) + payload


#: An arm is a decision over the buffered window: (window_pcm16, span_open_s,
#: placement_or_None) -> Decision.
Arm = Callable[[np.ndarray, float, Placement | None], Decision]


def vad_only_arm(_window: np.ndarray, _open_s: float, _placement: Placement | None) -> Decision:
    return Decision(admit=True, reason="vad")


def push_to_talk_arm(gesture_windows: Sequence[tuple[float, float]]) -> Arm:
    """The reference floor: the socket opens only while the owner holds the button."""

    def arm(_window: np.ndarray, open_s: float, _placement: Placement | None) -> Decision:
        for start, end in gesture_windows:
            if start <= open_s <= end:
                return Decision(admit=True, reason="ptt_pressed")
        return Decision(admit=False, reason="ptt_not_pressed")

    return arm


def restricted_listening_arm(presence_windows: Sequence[tuple[float, float]]) -> Arm:
    """Mic open only inside a person-present window; VAD-only inside one."""

    def arm(_window: np.ndarray, open_s: float, _placement: Placement | None) -> Decision:
        for start, end in presence_windows:
            if start <= open_s <= end:
                return Decision(admit=True, reason="present_and_vad")
        return Decision(admit=False, reason="nobody_present")

    return arm


def run_gate(
    tape: Tape,
    arm: Arm,
    *,
    config: GateConfig | None = None,
    transport: FakeTransport | None = None,
    model_path: Path = SILERO_MODEL,
) -> tuple[list[Admission], FakeTransport]:
    """Stream the tape through Silero and let ``arm`` decide each span."""

    config = config or GateConfig()
    transport = transport or FakeTransport()
    vad = SileroVad(str(model_path), threshold=config.threshold)
    if not vad.available:  # pragma: no cover - a missing model is a loud failure
        raise RuntimeError(f"Silero model unavailable at {model_path}")
    hangover_frames = max(1, round(config.hangover_ms / 1000.0 / FRAME_S))
    decision_frames = max(1, round(config.decision_window_s / FRAME_S))
    preroll_samples = int(config.preroll_ms / 1000.0 * RATE_HZ)

    admissions: list[Admission] = []
    above = 0
    quiet = 0
    open_at: float | None = None
    open_index = 0
    decided = False
    decision: Decision | None = None
    total = tape.samples.size // FRAME_SAMPLES

    def close_span(index: int, now: float) -> None:
        nonlocal open_at, decided, decision
        assert open_at is not None
        placement = tape.role_at(open_at)
        role = placement.role if placement else "ambient"
        name = placement.name if placement else ""
        verdict = decision or Decision(admit=False, reason="span_too_short")
        upload_from = max(0, open_index * FRAME_SAMPLES - preroll_samples)
        payload = tape.samples[upload_from : index * FRAME_SAMPLES]
        uploaded_seconds = 0.0
        uploaded_bytes = 0
        if verdict.admit:
            transport.send(payload, role)
            uploaded_seconds = payload.size / RATE_HZ
            uploaded_bytes = payload.size * 2
        admissions.append(
            Admission(
                open_s=open_at,
                close_s=now,
                upload_from_s=upload_from / RATE_HZ,
                decided_s=open_at + config.decision_window_s,
                admitted=verdict.admit,
                reason=verdict.reason,
                score=verdict.score,
                detail=verdict.detail,
                source_role=role,
                source_name=name,
                uploaded_seconds=uploaded_seconds,
                uploaded_bytes=uploaded_bytes,
            )
        )
        open_at = None
        decided = False
        decision = None

    for index in range(total):
        frame = tape.samples[index * FRAME_SAMPLES : (index + 1) * FRAME_SAMPLES]
        probability = vad.process(frame)
        now = (index + 1) * FRAME_S
        if probability >= config.threshold:
            above += 1
            quiet = 0
        else:
            above = 0
            quiet += 1
        if open_at is None:
            if above >= config.open_frames:
                open_at = now
                open_index = index + 1 - config.open_frames
                decided = False
                decision = None
            continue
        if not decided and index + 1 - open_index >= decision_frames:
            window = tape.samples[open_index * FRAME_SAMPLES : (index + 1) * FRAME_SAMPLES]
            decision = arm(window, open_at, tape.role_at(open_at))
            decided = True
        if quiet >= hangover_frames:
            if not decided:
                window = tape.samples[open_index * FRAME_SAMPLES : (index + 1) * FRAME_SAMPLES]
                decision = arm(window, open_at, tape.role_at(open_at))
                decided = True
            close_span(index + 1, now)
    if open_at is not None:
        if not decided:
            window = tape.samples[open_index * FRAME_SAMPLES :]
            decision = arm(window, open_at, tape.role_at(open_at))
        close_span(total, tape.seconds)
    return admissions, transport


__all__ = [
    "FRAME_S",
    "RATE_HZ",
    "SILERO_MODEL",
    "Admission",
    "Arm",
    "Decision",
    "FakeTransport",
    "GateConfig",
    "Placement",
    "Tape",
    "push_to_talk_arm",
    "restricted_listening_arm",
    "run_gate",
    "vad_only_arm",
]
