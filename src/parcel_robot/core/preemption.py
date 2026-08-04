"""Declarative preemption policy table (pure; numpy/stdlib only).

Mines today's hand-enumerated stop semantics into one fail-closed matrix so
runtime ``preempt()`` is behavior-preserving by construction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum


class PreemptionAction(str, Enum):
    NONE = "none"  # channels coexist
    PAUSE = "pause"  # suspend, record ResumeIntent, resume later
    STOP = "stop"  # destructive cancel (today's only behavior)
    DEFER = "defer"  # new claimant queues until current releases


@dataclass(frozen=True)
class ChannelSpec:
    name: str  # "navigation" | "follow" | "spatial" | ...
    source: str  # CommandArbiter source name
    priority: int  # mirrors SOURCE_PRIORITIES
    pausable: bool = False


@dataclass(frozen=True)
class PreemptionDecision:
    action: PreemptionAction
    reason: str


# Mirrors parcel_robot.core.commands.SOURCE_PRIORITIES without importing it
# (Sol modules stay free of parcel_robot runtime dependencies).
_SOURCE_PRIORITIES: Mapping[str, int] = {
    "navigation": 30,
    "search": 35,
    "follow": 40,
    "spatial": 50,
    "voice": 60,
    "manual": 80,
    "safety": 100,
}


def _channel(
    name: str,
    *,
    source: str | None = None,
    priority: int | None = None,
    pausable: bool = False,
) -> ChannelSpec:
    src = source if source is not None else name
    pri = priority if priority is not None else int(_SOURCE_PRIORITIES[src])
    return ChannelSpec(name=name, source=src, priority=pri, pausable=pausable)


class PreemptionTable:
    """Single source of truth for who preempts whom."""

    def __init__(
        self,
        channels: Iterable[ChannelSpec],
        rules: Mapping[tuple[str, str], PreemptionAction],
    ) -> None:
        channel_list = tuple(channels)
        names = [channel.name for channel in channel_list]
        if len(names) != len(set(names)):
            raise ValueError("channel names must be unique")
        self._channels = channel_list
        self._by_name = {channel.name: channel for channel in channel_list}
        self._rules = dict(rules)

    def decide(self, claimant: str, active: str) -> PreemptionDecision:
        if claimant == active:
            return PreemptionDecision(PreemptionAction.NONE, "same_channel")
        action = self._rules.get((claimant, active))
        if action is None:
            return PreemptionDecision(PreemptionAction.STOP, "undeclared_pair")
        return PreemptionDecision(action, f"{claimant}->{active}")

    def channels(self) -> tuple[ChannelSpec, ...]:
        return self._channels

    def declared_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset(self._rules)

    def rules(self) -> dict[tuple[str, str], PreemptionAction]:
        return dict(self._rules)

    def missing_pairs(self) -> frozenset[tuple[str, str]]:
        """Ordered pairs among registered channels that lack an explicit rule."""

        names = [channel.name for channel in self._channels]
        expected = {(a, b) for a in names for b in names if a != b}
        return frozenset(expected - set(self._rules))

    @classmethod
    def default(cls) -> PreemptionTable:
        """Encode today's mined stop-site semantics.

        Highlights from the runtime audit:
        - manual / safety stop everything they touch
        - voice-motion / pose / trajectory stop follow, navigation, spatial
        - navigation cancels follow (and spatial)
        - search **pauses** follow with resume — the one existing resume path
        - follow / spatial mutually cancel navigation and each other
        """

        channels = (
            _channel("navigation", pausable=True),
            _channel("search", pausable=True),
            _channel("follow", pausable=True),
            _channel("spatial", pausable=False),
            _channel("activities", source="voice", priority=55, pausable=False),
            _channel("voice", pausable=False),
            _channel("pose", source="manual", priority=70, pausable=False),
            _channel("trajectory", source="manual", priority=70, pausable=False),
            _channel("manual", pausable=False),
            _channel("safety", pausable=False),
        )
        names = [channel.name for channel in channels]
        rules: dict[tuple[str, str], PreemptionAction] = {}

        def set_rule(claimant: str, active: str, action: PreemptionAction) -> None:
            rules[(claimant, active)] = action

        # Default: higher-or-equal priority claimant STOPs lower; otherwise DEFER.
        # Explicit overrides below encode the mined exceptions (PAUSE, NONE, …).
        priority = {channel.name: channel.priority for channel in channels}
        for claimant in names:
            for active in names:
                if claimant == active:
                    continue
                if priority[claimant] >= priority[active]:
                    set_rule(claimant, active, PreemptionAction.STOP)
                else:
                    set_rule(claimant, active, PreemptionAction.DEFER)

        # Search pauses follow (the one resume precedent) instead of destroying it.
        set_rule("search", "follow", PreemptionAction.PAUSE)

        # Same-priority locomotion peers still cancel each other today.
        for a, b in (
            ("follow", "spatial"),
            ("spatial", "follow"),
            ("navigation", "follow"),
            ("follow", "navigation"),
            ("navigation", "spatial"),
            ("spatial", "navigation"),
            ("search", "navigation"),
            ("navigation", "search"),
            ("search", "spatial"),
            ("spatial", "search"),
            ("follow", "search"),
        ):
            set_rule(a, b, PreemptionAction.STOP)

        # Voice / pose / trajectory destroy locomotion + activities (today).
        for claimant in ("voice", "pose", "trajectory"):
            for active in ("follow", "navigation", "spatial", "search", "activities"):
                set_rule(claimant, active, PreemptionAction.STOP)

        # Manual acquires the base: spatial is stopped; voice lease can coexist
        # until TTL ends, but activities are cleared.
        set_rule("manual", "spatial", PreemptionAction.STOP)
        set_rule("manual", "follow", PreemptionAction.STOP)
        set_rule("manual", "navigation", PreemptionAction.STOP)
        set_rule("manual", "search", PreemptionAction.STOP)
        set_rule("manual", "activities", PreemptionAction.STOP)
        set_rule("manual", "voice", PreemptionAction.STOP)

        # Safety / E-stop is absolute.
        for active in names:
            if active == "safety":
                continue
            set_rule("safety", active, PreemptionAction.STOP)

        # Activities never claim the base lease against locomotion today.
        for active in (
            "navigation",
            "follow",
            "spatial",
            "search",
            "voice",
            "manual",
            "safety",
            "pose",
            "trajectory",
        ):
            set_rule("activities", active, PreemptionAction.NONE)

        # Voice does not cancel pose/trajectory/manual/safety.
        for active in ("pose", "trajectory", "manual", "safety"):
            set_rule("voice", active, PreemptionAction.DEFER)

        return cls(channels, rules)


__all__ = [
    "ChannelSpec",
    "PreemptionAction",
    "PreemptionDecision",
    "PreemptionTable",
]
