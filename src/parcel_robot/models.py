from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Pose:
    name: str
    joints: dict[str, float]
    duration: float = 1.0


@dataclass(frozen=True)
class VelocityCommand:
    """Body-frame velocity request for locomotion backends."""

    vx: float = 0.0
    vy: float = 0.0
    vyaw: float = 0.0


@dataclass(frozen=True)
class WifiCard:
    name: str
    interface: str
    ros_domain_id: int
    purpose: str = "robot"


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    class_path: str
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentDecision:
    reply: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    name: str
    accepted: bool
    message: str
