from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .goals import SemanticGoal


@dataclass(frozen=True)
class MidLevelCommand:
    """Body-frame velocity command for short-horizon execution."""

    vx: float = 0.0
    vy: float = 0.0
    vyaw: float = 0.0
    stop: bool = False
    note: str = ""


@dataclass(frozen=True)
class GoalPose:
    x: float
    y: float
    z: float = 0.0
    heading_deg: float = 0.0
    poi_id: str = ""
    label: str = ""
    # Semantic regions/objects need a much tighter terminal tolerance than a
    # mapped landmark. ``None`` preserves the navigator's configured default.
    arrival_radius_m: float | None = None


@dataclass
class Mission:
    directive: str
    goal: GoalPose | None
    status: str = "idle"  # idle | unresolved | searching | running | verifying | arrived | failed
    semantic_goal: SemanticGoal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NavObservation:
    """Minimal observation bag passed to navigator models."""

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    heading_deg: float = 0.0
    rgb: Any = None
    lidar: Any = None
    nearest_person_m: float | None = None
    nearest_obstacle_m: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelSpec:
    id: str
    type: str
    version: str
    description: str = ""
    homepage: str = ""
    checkpoint: str = ""
    device: str = "cpu"
    controller: dict[str, Any] = field(default_factory=dict)
    rl: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""


class Navigator(Protocol):
    spec: ModelSpec

    def reset(self, mission: Mission) -> None: ...

    def act(self, observation: NavObservation, mission: Mission) -> MidLevelCommand: ...

    def close(self) -> None: ...
