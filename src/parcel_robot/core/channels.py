"""BehaviorChannel protocol + registry (Opus; consumes Sol preemption/resume)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from parcel_robot.core.preemption import PreemptionAction, PreemptionTable
from parcel_robot.core.resume import ResumeIntent, ResumeStore


@runtime_checkable
class BehaviorChannel(Protocol):
    name: str
    arbiter_source: str
    priority: int

    def stop(self, reason: str) -> None: ...

    def snapshot(self) -> dict[str, object]: ...

    def pause(self, reason: str) -> ResumeIntent | None: ...

    def resume(self, intent: ResumeIntent, *, now_s: float) -> None: ...

    def active(self) -> bool: ...


@dataclass
class ChannelRegistration:
    channel: BehaviorChannel
    pausable: bool = False


class BehaviorChannelRegistry:
    """Named channel wrappers consulted by ``runtime.preempt()``."""

    def __init__(
        self,
        *,
        table: PreemptionTable | None = None,
        resume_store: ResumeStore | None = None,
    ) -> None:
        self.table = table or PreemptionTable.default()
        self.resume_store = resume_store or ResumeStore()
        self._channels: dict[str, ChannelRegistration] = {}

    def register(self, channel: BehaviorChannel, *, pausable: bool | None = None) -> None:
        spec = next((c for c in self.table.channels() if c.name == channel.name), None)
        self._channels[channel.name] = ChannelRegistration(
            channel=channel,
            pausable=spec.pausable if pausable is None and spec is not None else bool(pausable),
        )

    def get(self, name: str) -> BehaviorChannel | None:
        row = self._channels.get(name)
        return None if row is None else row.channel

    def active_names(self) -> tuple[str, ...]:
        return tuple(name for name, row in self._channels.items() if row.channel.active())

    def snapshot(self) -> dict[str, object]:
        return {
            name: dict(row.channel.snapshot())
            for name, row in self._channels.items()
        }

    def preempt(
        self,
        claimant: str,
        *,
        reason: str,
        now_s: float,
        targets: tuple[str, ...] | None = None,
    ) -> dict[str, str]:
        """Apply the table to each active (or listed) channel; return actions taken."""

        names = targets if targets is not None else self.active_names()
        taken: dict[str, str] = {}
        for active in names:
            if active == claimant:
                continue
            decision = self.table.decide(claimant, active)
            row = self._channels.get(active)
            if row is None:
                taken[active] = f"missing:{decision.action.value}"
                continue
            if decision.action is PreemptionAction.NONE:
                taken[active] = "none"
                continue
            if decision.action is PreemptionAction.DEFER:
                taken[active] = "defer"
                continue
            if decision.action is PreemptionAction.PAUSE and row.pausable:
                intent = row.channel.pause(reason)
                if intent is not None:
                    # Channels may leave suspended_at_s=0 as a fill-me sentinel.
                    # Record with the preempt clock immediately — peek(now_s) would
                    # otherwise treat 0+TTL as already expired on monotonic clocks.
                    if intent.suspended_at_s == 0.0:
                        intent = ResumeIntent(
                            channel=intent.channel,
                            payload=intent.payload,
                            suspend_reason=intent.suspend_reason,
                            suspended_at_s=now_s,
                            valid_for_s=intent.valid_for_s,
                            requires_fresh_observation=intent.requires_fresh_observation,
                        )
                    self.resume_store.record(intent)
                else:
                    # Pausable channel declined — fall back to stop.
                    row.channel.stop(reason)
                taken[active] = "pause"
                continue
            # STOP, or PAUSE on a non-pausable channel.
            row.channel.stop(reason)
            taken[active] = "stop"
        return taken


__all__ = [
    "BehaviorChannel",
    "BehaviorChannelRegistry",
    "ChannelRegistration",
]
