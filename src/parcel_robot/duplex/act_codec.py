"""Discrete ACT-token codec over SafetyLimits-bounded twist bins (pure)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class TwistBins:
    vx_bins: tuple[float, ...]  # e.g. (-0.3, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    vyaw_bins: tuple[float, ...]  # e.g. (-1.5, -0.7, 0.0, 0.7, 1.5)

    def __post_init__(self) -> None:
        if len(self.vx_bins) < 1 or len(self.vyaw_bins) < 1:
            raise ValueError("twist bins must be non-empty")
        for name, bins in (("vx_bins", self.vx_bins), ("vyaw_bins", self.vyaw_bins)):
            if any(not math.isfinite(float(value)) for value in bins):
                raise ValueError(f"{name} must be finite")
            if tuple(bins) != tuple(sorted(bins)):
                raise ValueError(f"{name} must be sorted ascending")


@dataclass(frozen=True)
class ActCommand:
    kind: str  # "idle" | "twist" | "gaze" | "skill" | "emote" | "filler_gesture"
    vx: float = 0.0
    vyaw: float = 0.0
    bearing_rad: float | None = None
    name: str | None = None


def default_twist_bins() -> TwistBins:
    """Bins spanning the post-speed-raise SafetyLimits envelope."""

    return TwistBins(
        vx_bins=(-0.3, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        vyaw_bins=(-1.5, -0.7, 0.0, 0.7, 1.5),
    )


class ActTokenCodec:
    def __init__(
        self,
        *,
        twist: TwistBins,
        gaze_bins: int = 8,
        skills: Iterable[str] = (),
        emotes: Iterable[str] = (),
        filler_gestures: int = 4,
    ) -> None:
        if not isinstance(twist, TwistBins):
            raise TypeError("twist must be a TwistBins")
        if not isinstance(gaze_bins, int) or gaze_bins < 1:
            raise ValueError("gaze_bins must be a positive int")
        if not isinstance(filler_gestures, int) or filler_gestures < 0:
            raise ValueError("filler_gestures must be a non-negative int")
        self._twist = twist
        self._gaze_bins = int(gaze_bins)
        self._skills = tuple(sorted({str(name) for name in skills if str(name)}))
        self._emotes = tuple(sorted({str(name) for name in emotes if str(name)}))
        self._filler_gestures = int(filler_gestures)
        self._vocab = self._build_vocabulary()
        self._vocab_set = frozenset(self._vocab)

    def vocabulary(self) -> tuple[str, ...]:
        return self._vocab

    def encode_twist(self, vx: float, vyaw: float) -> str:
        vx_i = _nearest_bin_index(float(vx), self._twist.vx_bins)
        vyaw_i = _nearest_bin_index(float(vyaw), self._twist.vyaw_bins)
        return f"<twist:{vx_i}:{vyaw_i}>"

    def encode_gaze_owner(self) -> str:
        return "<gaze_owner>"

    def encode_gaze_release(self) -> str:
        return "<gaze_release>"

    def encode_gaze_bearing(self, bearing_rad: float) -> str:
        if not math.isfinite(float(bearing_rad)):
            bearing_rad = 0.0
        # Wrap to [0, 2π) then nearest bin.
        tau = 2.0 * math.pi
        wrapped = float(bearing_rad) % tau
        if wrapped < 0.0:
            wrapped += tau
        index = round((wrapped / tau) * self._gaze_bins) % self._gaze_bins
        return f"<gaze_bearing_{index}>"

    def encode_skill(self, name: str) -> str:
        token = f"<skill:{name!s}>"
        if token not in self._vocab_set:
            raise ValueError(f"unknown skill act token: {token!r}")
        return token

    def encode_emote(self, name: str) -> str:
        token = f"<emote:{name!s}>"
        if token not in self._vocab_set:
            raise ValueError(f"unknown emote act token: {token!r}")
        return token

    def encode_filler_gesture(self, index: int = 0) -> str:
        token = f"<filler_gesture_{int(index)}>"
        if token not in self._vocab_set:
            raise ValueError(f"unknown filler gesture token: {token!r}")
        return token

    def decode(self, token: str) -> ActCommand:
        raw = str(token)
        if raw not in self._vocab_set:
            raise ValueError(f"unknown act token: {raw!r}")
        if raw == "<idle>":
            return ActCommand(kind="idle")
        if raw.startswith("<twist:"):
            body = raw[len("<twist:") : -1]
            left, _, right = body.partition(":")
            vx_i = int(left)
            vyaw_i = int(right)
            return ActCommand(
                kind="twist",
                vx=float(self._twist.vx_bins[vx_i]),
                vyaw=float(self._twist.vyaw_bins[vyaw_i]),
            )
        if raw == "<gaze_owner>":
            return ActCommand(kind="gaze", name="owner")
        if raw == "<gaze_release>":
            return ActCommand(kind="gaze", name="release")
        if raw.startswith("<gaze_bearing_"):
            index = int(raw[len("<gaze_bearing_") : -1])
            bearing = (2.0 * math.pi * index) / self._gaze_bins
            return ActCommand(kind="gaze", bearing_rad=bearing, name=f"bearing_{index}")
        if raw.startswith("<skill:"):
            return ActCommand(kind="skill", name=raw[len("<skill:") : -1])
        if raw.startswith("<emote:"):
            return ActCommand(kind="emote", name=raw[len("<emote:") : -1])
        if raw.startswith("<filler_gesture_"):
            return ActCommand(
                kind="filler_gesture",
                name=raw[len("<filler_gesture_") : -1],
            )
        if raw.startswith("<filler_speech_"):
            return ActCommand(
                kind="filler_gesture",
                name=f"speech_{raw[len('<filler_speech_') : -1]}",
            )
        raise ValueError(f"unknown act token: {raw!r}")

    def is_idle(self, token: str) -> bool:
        return str(token) == "<idle>"

    def _build_vocabulary(self) -> tuple[str, ...]:
        tokens: list[str] = ["<idle>", "<gaze_owner>", "<gaze_release>"]
        tokens.extend(f"<gaze_bearing_{index}>" for index in range(self._gaze_bins))
        for vx_i in range(len(self._twist.vx_bins)):
            for vyaw_i in range(len(self._twist.vyaw_bins)):
                tokens.append(f"<twist:{vx_i}:{vyaw_i}>")
        tokens.extend(f"<skill:{name}>" for name in self._skills)
        tokens.extend(f"<emote:{name}>" for name in self._emotes)
        for index in range(self._filler_gestures):
            tokens.append(f"<filler_gesture_{index}>")
            tokens.append(f"<filler_speech_{index}>")
        return tuple(sorted(tokens))


def _nearest_bin_index(value: float, bins: tuple[float, ...]) -> int:
    if not math.isfinite(value):
        value = 0.0
    # Clamp to edge bins — codec never raises on out-of-range twists.
    if value <= bins[0]:
        return 0
    if value >= bins[-1]:
        return len(bins) - 1
    best_i = 0
    best_dist = abs(value - bins[0])
    for index, center in enumerate(bins[1:], start=1):
        dist = abs(value - center)
        if dist < best_dist:
            best_i = index
            best_dist = dist
    return best_i


__all__ = [
    "ActCommand",
    "ActTokenCodec",
    "TwistBins",
    "default_twist_bins",
]
