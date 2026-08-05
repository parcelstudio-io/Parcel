"""Duplex frame contract and fixed-clock interleaver (pure; numpy/stdlib only)."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

TEXT_SILENCE = "<silence>"
ACT_IDLE = "<idle>"


@dataclass(frozen=True)
class DuplexFrame:
    t: int  # frame index on the shared clock
    epoch: int
    text: str  # token text | TEXT_SILENCE
    act: str  # act token   | ACT_IDLE


class FrameInterleaver:
    """Merge asynchronous text/act event feeds onto the fixed frame clock."""

    def __init__(self, *, frame_hz: float = 10.0) -> None:
        hz = float(frame_hz)
        if not math.isfinite(hz) or hz <= 0.0:
            raise ValueError("frame_hz must be finite and positive")
        self._frame_hz = hz
        self._period_s = 1.0 / hz
        self._t = 0
        self._epoch = 0
        self._text_q: deque[tuple[int, str]] = deque()
        self._pending_act: str | None = None
        self._pending_act_epoch = 0
        self._anchor_s: float | None = None
        self._last_now_s: float | None = None

    def push_text(self, token: str, *, epoch: int) -> None:
        text = str(token)
        if not text:
            raise ValueError("text token must be non-empty")
        epoch_i = int(epoch)
        if epoch_i != self._epoch:
            return
        self._text_q.append((epoch_i, text))

    def push_act(self, token: str, *, epoch: int) -> None:
        act = str(token)
        if not act:
            raise ValueError("act token must be non-empty")
        epoch_i = int(epoch)
        if epoch_i != self._epoch:
            return
        # Acts are states for the current frame window — last write wins.
        self._pending_act = act
        self._pending_act_epoch = epoch_i

    def set_epoch(self, epoch: int) -> None:
        epoch_i = int(epoch)
        self._epoch = epoch_i
        if self._text_q:
            self._text_q = deque(
                (item_epoch, token)
                for item_epoch, token in self._text_q
                if item_epoch >= epoch_i
            )
        if self._pending_act is not None and self._pending_act_epoch < epoch_i:
            self._pending_act = None

    def tick(self, *, now_s: float) -> DuplexFrame:
        now = float(now_s)
        if not math.isfinite(now):
            raise ValueError("now_s must be finite")
        if self._anchor_s is None:
            self._anchor_s = now
        self._last_now_s = now

        text = TEXT_SILENCE
        while self._text_q:
            item_epoch, token = self._text_q.popleft()
            if item_epoch != self._epoch:
                continue
            text = token
            break

        act = ACT_IDLE
        if (
            self._pending_act is not None
            and self._pending_act_epoch == self._epoch
        ):
            act = self._pending_act
        # Consumed for this frame window; next window idles unless re-pushed.
        self._pending_act = None

        frame = DuplexFrame(t=self._t, epoch=self._epoch, text=text, act=act)
        self._t += 1
        return frame

    def snapshot(self) -> dict[str, object]:
        expected_t = self._t
        if self._anchor_s is not None and self._last_now_s is not None:
            # Drift-free index from injected time (no cumulative += period).
            elapsed = self._last_now_s - self._anchor_s
            if elapsed >= 0.0:
                expected_t = math.floor(elapsed * self._frame_hz + 1e-12) + 1
        return {
            "frame_hz": self._frame_hz,
            "period_s": self._period_s,
            "t": self._t,
            "epoch": self._epoch,
            "text_queue_len": len(self._text_q),
            "pending_act": self._pending_act,
            "anchor_s": self._anchor_s,
            "last_now_s": self._last_now_s,
            "expected_t_from_clock": expected_t,
        }


__all__ = ["ACT_IDLE", "TEXT_SILENCE", "DuplexFrame", "FrameInterleaver"]
