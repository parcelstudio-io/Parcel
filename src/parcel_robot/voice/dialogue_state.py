"""Dialogue-state 10 Hz channel + T2 gaze/pace mapper (Phase 2 / Sol pure).

Publishes ``DialogueStateMsg`` for the StimulusBus-shaped contract. T2 maps
phase × engagement → attention/gaze mode and a **bounded slowdown** factor.
This path never authors model velocity, never raises pace above the executive
``PaceCap``, and never touches safety / E-stop authority.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Literal

from parcel_robot.contracts.v1 import DIALOGUE_PHASES, SCHEMA_VERSION, DialogueStateMsg

# K1 RFC: dialogue-state TTL 500 ms.
DIALOGUE_STATE_TTL_NS = 500_000_000
DIALOGUE_CHANNEL = "dialogue_state"

GazeMode = Literal["mutual", "aversion", "soft", "idle"]
GaitHint = Literal["normal", "soft_cadence", "hold_cadence"]

# Engagement mid-sentence may defer non-urgent autonomy.
DEFER_ENGAGEMENT = 0.65
# Soft pace slowdown while engaged in dialogue (multiplicative, ≤ 1.0).
PACE_FACTOR_LISTENING = 0.92
PACE_FACTOR_SPEAKING = 0.88
PACE_FACTOR_THINKING = 0.95
PACE_FACTOR_IDLE = 1.0


@dataclass(frozen=True, slots=True)
class DialogueInfluence:
    """Deterministic T2 conditioning derived from a fresh DialogueStateMsg."""

    gaze_mode: GazeMode
    pace_scale_factor: float
    defer_nonurgent: bool
    gait_hint: GaitHint
    phase: str
    engagement: float

    def as_dict(self) -> dict[str, object]:
        return {
            "gaze_mode": self.gaze_mode,
            "pace_scale_factor": self.pace_scale_factor,
            "defer_nonurgent": self.defer_nonurgent,
            "gait_hint": self.gait_hint,
            "phase": self.phase,
            "engagement": self.engagement,
        }


def map_dialogue_to_t2(msg: DialogueStateMsg) -> DialogueInfluence:
    """Map dialogue-state → gaze / bounded pace / gait hint (fail-closed idle)."""

    if not isinstance(msg, DialogueStateMsg):
        raise TypeError("msg must be DialogueStateMsg")
    phase = msg.phase
    eng = float(msg.engagement)
    if phase == "listening":
        return DialogueInfluence(
            gaze_mode="mutual",
            pace_scale_factor=_pace_factor(PACE_FACTOR_LISTENING, eng),
            defer_nonurgent=eng >= DEFER_ENGAGEMENT,
            gait_hint="soft_cadence",
            phase=phase,
            engagement=eng,
        )
    if phase == "thinking":
        return DialogueInfluence(
            gaze_mode="aversion",
            pace_scale_factor=_pace_factor(PACE_FACTOR_THINKING, eng),
            defer_nonurgent=eng >= DEFER_ENGAGEMENT,
            gait_hint="hold_cadence",
            phase=phase,
            engagement=eng,
        )
    if phase == "speaking":
        return DialogueInfluence(
            gaze_mode="soft",
            pace_scale_factor=_pace_factor(PACE_FACTOR_SPEAKING, eng),
            defer_nonurgent=False,
            gait_hint="soft_cadence",
            phase=phase,
            engagement=eng,
        )
    return DialogueInfluence(
        gaze_mode="idle",
        pace_scale_factor=PACE_FACTOR_IDLE,
        defer_nonurgent=False,
        gait_hint="normal",
        phase=phase if phase in DIALOGUE_PHASES else "idle",
        engagement=eng,
    )


def idle_influence() -> DialogueInfluence:
    return DialogueInfluence(
        gaze_mode="idle",
        pace_scale_factor=PACE_FACTOR_IDLE,
        defer_nonurgent=False,
        gait_hint="normal",
        phase="idle",
        engagement=0.0,
    )


class DialogueStateChannel:
    """Publish/consume DialogueStateMsg at control rate (thread-safe)."""

    def __init__(self, *, ttl_ns: int = DIALOGUE_STATE_TTL_NS) -> None:
        if not isinstance(ttl_ns, int) or ttl_ns <= 0:
            raise ValueError("ttl_ns must be a positive int")
        self._ttl_ns = int(ttl_ns)
        self._lock = threading.RLock()
        self._phase = "idle"
        self._engagement = 0.0
        self._turn_id = ""
        self._sequence = 0
        self._latest: DialogueStateMsg | None = None

    @property
    def phase(self) -> str:
        with self._lock:
            return self._phase

    @property
    def engagement(self) -> float:
        with self._lock:
            return self._engagement

    def set_phase(
        self,
        phase: str,
        *,
        engagement: float | None = None,
        turn_id: str | None = None,
    ) -> None:
        """Update the live dialogue phase (does not publish until ``publish``)."""

        if phase not in DIALOGUE_PHASES:
            raise ValueError(f"dialogue phase must be one of {sorted(DIALOGUE_PHASES)}")
        with self._lock:
            self._phase = phase
            if engagement is not None:
                eng = float(engagement)
                if not 0.0 <= eng <= 1.0:
                    raise ValueError("engagement must be in [0, 1]")
                self._engagement = eng
            elif phase == "idle":
                self._engagement = 0.0
            elif self._engagement <= 0.0:
                self._engagement = 0.55 if phase == "listening" else 0.45
            if turn_id is not None:
                self._turn_id = str(turn_id)

    def publish(self, now_monotonic_ns: int) -> DialogueStateMsg:
        """Emit a fresh DialogueStateMsg (10 Hz hot-path call)."""

        if not isinstance(now_monotonic_ns, int) or now_monotonic_ns < 0:
            raise ValueError("now_monotonic_ns must be a non-negative int")
        with self._lock:
            self._sequence += 1
            msg = DialogueStateMsg(
                schema_version=SCHEMA_VERSION,
                channel=DIALOGUE_CHANNEL,
                phase=self._phase,
                engagement=self._engagement,
                turn_id=self._turn_id,
                published_monotonic_ns=now_monotonic_ns,
                expires_monotonic_ns=now_monotonic_ns + self._ttl_ns,
                sequence=self._sequence,
            )
            self._latest = msg
            return msg

    def latest(self, now_monotonic_ns: int) -> DialogueStateMsg | None:
        """Return the latest message if unexpired; else None (fail-closed)."""

        with self._lock:
            msg = self._latest
            if msg is None:
                return None
            if msg.expired(now_monotonic_ns):
                return None
            return msg

    def influence(self, now_monotonic_ns: int) -> DialogueInfluence:
        msg = self.latest(now_monotonic_ns)
        if msg is None:
            return idle_influence()
        return map_dialogue_to_t2(msg)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            latest = self._latest
            return {
                "phase": self._phase,
                "engagement": self._engagement,
                "turn_id": self._turn_id,
                "sequence": self._sequence,
                "latest": None if latest is None else latest.as_dict(),
            }


def _pace_factor(base: float, engagement: float) -> float:
    """Blend toward base slowdown as engagement rises; never exceed 1.0."""

    # engagement 0 → 1.0; engagement 1 → base
    factor = 1.0 - engagement * (1.0 - base)
    return max(0.35, min(1.0, factor))


__all__ = [
    "DIALOGUE_CHANNEL",
    "DIALOGUE_STATE_TTL_NS",
    "DEFER_ENGAGEMENT",
    "DialogueInfluence",
    "DialogueStateChannel",
    "GaitHint",
    "GazeMode",
    "idle_influence",
    "map_dialogue_to_t2",
]
