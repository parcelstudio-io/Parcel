"""D0 system-composed duplex coordinator (frames + fillers + shadow + log)."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .act_codec import ActTokenCodec, default_twist_bins
from .config import DuplexConfig
from .consumer import DuplexFrameConsumer
from .filler_policy import FillerFire, FillerPolicy
from .fillers import FillerPool
from .frames import ACT_IDLE, TEXT_SILENCE, DuplexFrame, FrameInterleaver
from .session_log import DuplexSessionLog


class DuplexCoordinator:
    """Owns the D0 producer clock, filler policy, shadow consumer, and log."""

    def __init__(
        self,
        config: DuplexConfig,
        *,
        skills: Iterable[str] = (),
        emotes: Iterable[str] = (),
        session_id: str | None = None,
        log_root: Path | None = None,
    ) -> None:
        self.config = config
        self.enabled = bool(config.enabled)
        self._session_id = session_id or uuid.uuid4().hex[:12]
        self._lock = threading.RLock()
        self.interleaver = FrameInterleaver(frame_hz=config.frame_hz)
        self.codec = ActTokenCodec(
            twist=default_twist_bins(),
            skills=skills,
            emotes=emotes,
        )
        self.consumer = DuplexFrameConsumer(
            self.codec,
            shadow=bool(config.shadow_consumer),
        )
        self.filler = FillerPolicy(
            FillerPool.default(rng_seed=config.rng_seed),
            watchdog_s=config.filler_watchdog_s,
            ceiling_s=config.response_ceiling_s,
        )
        log_dir = Path(log_root) if log_root is not None else Path(config.log_dir)
        self.log = DuplexSessionLog(
            log_dir / f"{self._session_id}.jsonl",
            rotate_bytes=config.log_rotate_bytes,
            enabled=bool(config.logging and config.enabled),
        )
        self._last_frame: DuplexFrame | None = None
        self._missing_frames = 0
        self._frames_emitted = 0
        self._last_t: int | None = None
        self._epoch = 0
        self._last_act_token = ACT_IDLE
        self._turn_outcomes: list[dict[str, Any]] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def epoch(self) -> int:
        return self._epoch

    def set_epoch(self, epoch: int) -> None:
        with self._lock:
            self._epoch = int(epoch)
            self.interleaver.set_epoch(self._epoch)
            self.consumer.set_epoch(self._epoch)

    def on_turn_start(self, *, now_s: float | None = None) -> None:
        if not self.enabled:
            return
        self.filler.on_turn_start(now_s=time.monotonic() if now_s is None else now_s)

    def on_first_token(self, *, now_s: float | None = None) -> None:
        """First token reached the TTS queue (or text-only delivery path)."""

        if not self.enabled:
            return
        self.filler.on_first_token(now_s=time.monotonic() if now_s is None else now_s)

    def on_filler_audible(self, *, now_s: float | None = None) -> None:
        if not self.enabled:
            return
        self.filler.on_filler_audible(now_s=time.monotonic() if now_s is None else now_s)

    def predictive_filler(
        self,
        *,
        reason: str = "predictive",
        now_s: float | None = None,
        personality_gain: float = 1.0,
    ) -> FillerFire | None:
        if not self.enabled:
            return None
        return self.filler.predictive_fire(
            now_s=time.monotonic() if now_s is None else now_s,
            personality_gain=personality_gain,
            reason=reason,
        )

    def poll_watchdog(
        self,
        *,
        now_s: float | None = None,
        personality_gain: float = 1.0,
    ) -> FillerFire | None:
        if not self.enabled:
            return None
        now = time.monotonic() if now_s is None else now_s
        fire = self.filler.poll_watchdog(now_s=now, personality_gain=personality_gain)
        self.filler.poll_ceiling_breach(now_s=now)
        return fire

    def push_text_tokens(self, text: str, *, epoch: int | None = None) -> None:
        if not self.enabled:
            return
        with self._lock:
            epoch_i = self._epoch if epoch is None else int(epoch)
            for token in str(text).split():
                if token:
                    self.interleaver.push_text(token, epoch=epoch_i)

    def push_act(self, token: str, *, epoch: int | None = None) -> None:
        if not self.enabled:
            return
        with self._lock:
            epoch_i = self._epoch if epoch is None else int(epoch)
            self.interleaver.push_act(str(token), epoch=epoch_i)
            self._last_act_token = str(token)

    def push_twist(self, vx: float, vyaw: float, *, epoch: int | None = None) -> None:
        self.push_act(self.codec.encode_twist(vx, vyaw), epoch=epoch)

    def push_gaze_owner(self, *, epoch: int | None = None) -> None:
        self.push_act(self.codec.encode_gaze_owner(), epoch=epoch)

    def push_gaze_release(self, *, epoch: int | None = None) -> None:
        self.push_act(self.codec.encode_gaze_release(), epoch=epoch)

    def push_gaze_bearing(self, bearing_rad: float, *, epoch: int | None = None) -> None:
        self.push_act(self.codec.encode_gaze_bearing(bearing_rad), epoch=epoch)

    def push_skill(self, name: str, *, epoch: int | None = None) -> None:
        try:
            token = self.codec.encode_skill(name)
        except ValueError:
            return
        self.push_act(token, epoch=epoch)

    def push_emote(self, name: str, *, epoch: int | None = None) -> None:
        try:
            token = self.codec.encode_emote(name)
        except ValueError:
            return
        self.push_act(token, epoch=epoch)

    def push_filler_act(self, *, index: int = 0, epoch: int | None = None) -> None:
        try:
            token = self.codec.encode_filler_gesture(index)
        except ValueError:
            token = f"<filler_gesture_{int(index)}>"
        self.push_act(token, epoch=epoch)

    def tick(
        self,
        *,
        now_s: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> DuplexFrame | None:
        if not self.enabled:
            return None
        now = time.monotonic() if now_s is None else now_s
        with self._lock:
            frame = self.interleaver.tick(now_s=now)
            if self._last_t is not None and frame.t != self._last_t + 1:
                self._missing_frames += frame.t - self._last_t - 1
            self._last_t = frame.t
            self._frames_emitted += 1
            self._last_frame = frame
            self.consumer.consume(frame)
            self.log.write_frame(
                t=frame.t,
                epoch=frame.epoch,
                text=frame.text,
                act=frame.act,
                context=context,
            )
            return frame

    def record_turn_outcome(self, outcome: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self._turn_outcomes.append(dict(outcome))
        self.log.write_turn_outcome(outcome)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "session_id": self._session_id,
                "epoch": self._epoch,
                "frames_emitted": self._frames_emitted,
                "missing_frames": self._missing_frames,
                "last_frame": None
                if self._last_frame is None
                else {
                    "t": self._last_frame.t,
                    "epoch": self._last_frame.epoch,
                    "text": self._last_frame.text,
                    "act": self._last_frame.act,
                },
                "last_act_token": self._last_act_token,
                "filler": self.filler.snapshot(),
                "consumer": self.consumer.snapshot(),
                "logging": self.log.snapshot(),
                "interleaver": self.interleaver.snapshot(),
                "filler_latency_s": self.filler.filler_latency_s,
                "response_ceiling_breaches": self.filler.response_ceiling_breaches,
                "turn_outcomes": list(self._turn_outcomes[-16:]),
                "text_silence": TEXT_SILENCE,
                "act_idle": ACT_IDLE,
            }


__all__ = ["DuplexCoordinator"]
