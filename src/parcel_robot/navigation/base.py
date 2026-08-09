from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

if TYPE_CHECKING:
    from .goals import SemanticGoal

# --- stratum-1 pose seam ---------------------------------------------------
# ``parcel_robot.pose`` is the single authority for "where is the robot".
# It postdates every frozen BARN bundle, so the import stays soft exactly like
# the other post-K7 modules: a bundle without it reads the observation directly,
# which is what it always did.
try:
    from parcel_robot.pose import Frame, legacy_position_yaw, observation_pose

    _HAS_POSE = True
except ImportError:  # pragma: no cover — frozen BARN bundle path
    Frame = None  # type: ignore[assignment, misc]
    legacy_position_yaw = None  # type: ignore[assignment]
    observation_pose = None  # type: ignore[assignment]
    _HAS_POSE = False

#: REP-105 frame roles, named once so every consumer call site can say which it
#: means. MAP: world-frame goals, semantic memory, K0 arrival. ODOM: reactive
#: gate, TTC, short-horizon control.
MAP_FRAME: Any = Frame.MAP if _HAS_POSE else "map"
ODOM_FRAME: Any = Frame.ODOM if _HAS_POSE else "odom"


class MissionStatus(str, Enum):
    """Navigator mission lifecycle; ``PAUSED`` is a status, not a terminal outcome."""

    IDLE = "idle"
    UNRESOLVED = "unresolved"
    SEARCHING = "searching"
    RUNNING = "running"
    VERIFYING = "verifying"
    PAUSED = "paused"
    ARRIVED = "arrived"
    FAILED = "failed"


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
    status: MissionStatus | str = MissionStatus.IDLE
    semantic_goal: SemanticGoal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def status_value(self) -> str:
        status = self.status
        return status.value if isinstance(status, MissionStatus) else str(status)


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


class _LegacyPose(NamedTuple):
    """Bundle-path stand-in carrying the PoseEstimate surface consumers use."""

    x: float
    y: float
    yaw: float

    @property
    def xy(self) -> tuple[float, float]:
        return (self.x, self.y)

    @property
    def is_healthy(self) -> bool:
        return True

    @property
    def is_exact(self) -> bool:
        return True


def pose_in(observation: NavObservation, frame: Any) -> Any:
    """The ONE sanctioned pose read for navigation — frame always explicit.

    With :class:`~parcel_robot.pose.TruthPoseProvider` (the shipping default)
    both frames return the identical sim-truth floats, so routing every
    consumer through here is behavior-preserving by construction.
    """

    if _HAS_POSE:
        return observation_pose(observation, frame)
    return _LegacyPose(
        float(observation.position[0]),
        float(observation.position[1]),
        math.radians(float(observation.heading_deg)),
    )


def legacy_yaw(observation: NavObservation, *, zero_default: bool = False) -> float:
    """Pre-seam ``position[2]``-as-yaw read; see ``pose.legacy_position_yaw``."""

    if _HAS_POSE:
        return legacy_position_yaw(observation, zero_default=zero_default)
    position = observation.position
    if len(position) > 2:
        return float(position[2])
    return 0.0 if zero_default else math.radians(float(observation.heading_deg))


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
