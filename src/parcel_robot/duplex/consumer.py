"""D0 shadow consumer: decode frames without re-executing behavior."""

from __future__ import annotations

from dataclasses import dataclass, field

from .act_codec import ActCommand, ActTokenCodec
from .frames import ACT_IDLE, DuplexFrame


@dataclass
class DuplexFrameConsumer:
    """Route decoded ``ActCommand``s — shadow mode for D0.

    D0 frames are derived FROM executed behavior, so consuming them would
    double-execute. Shadow mode records decode round-trips for the eval and
    is the seam D1's model plugs into.
    """

    codec: ActTokenCodec
    shadow: bool = True
    _last_command: ActCommand | None = field(default=None, init=False, repr=False)
    _accepted: int = field(default=0, init=False, repr=False)
    _shadow_decoded: int = field(default=0, init=False, repr=False)
    _epoch: int = field(default=0, init=False, repr=False)
    _dropped_stale: int = field(default=0, init=False, repr=False)
    _executed: list[ActCommand] = field(default_factory=list, init=False, repr=False)

    def set_epoch(self, epoch: int) -> None:
        self._epoch = int(epoch)

    def consume(self, frame: DuplexFrame) -> ActCommand | None:
        if int(frame.epoch) != self._epoch:
            self._dropped_stale += 1
            return None
        command = self.codec.decode(frame.act)
        self._last_command = command
        if self.shadow:
            self._shadow_decoded += 1
            return command
        # Live mode (D1): only non-idle commands would enter admissibility.
        self._accepted += 1
        if command.kind != "idle":
            self._executed.append(command)
        return command

    def shadow_matches(self, token: str, *, vx: float = 0.0, vyaw: float = 0.0) -> bool:
        """Assert shadow decode round-trips a commanded twist/emote token."""

        command = self.codec.decode(token)
        if command.kind == "twist":
            encoded = self.codec.encode_twist(vx, vyaw)
            again = self.codec.decode(encoded)
            return again.vx == command.vx and again.vyaw == command.vyaw
        if token == ACT_IDLE:
            return self.codec.is_idle(token)
        return command.kind in {
            "gaze",
            "skill",
            "emote",
            "filler_gesture",
            "idle",
        }

    def snapshot(self) -> dict[str, object]:
        return {
            "shadow": self.shadow,
            "epoch": self._epoch,
            "shadow_decoded": self._shadow_decoded,
            "accepted": self._accepted,
            "dropped_stale": self._dropped_stale,
            "last_kind": None if self._last_command is None else self._last_command.kind,
            "executed_live": len(self._executed),
        }


__all__ = ["DuplexFrameConsumer"]
