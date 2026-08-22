from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from parcel_robot.models import Pose, VelocityCommand


@dataclass(frozen=True)
class RobotPose:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0


@dataclass(frozen=True)
class OwnerTrack:
    owner_id: str = "owner-1"
    x: float = 0.0
    y: float = 0.0
    visible: bool = False
    confidence: float = 0.0
    # ---- CARD OT-2: WHERE THIS CONFIDENCE CAME FROM ---------------------
    # Three fields, all defaulted, so every construction that existed before
    # this card reads exactly as it did (``""``/``0.0`` = "the producer said
    # nothing", which is what every pre-OT-2 producer said).
    #
    # They exist because ``confidence`` alone is not answerable. 1.0 from a
    # mocap body and 0.97 from a SigLIP-2 cosine are not the same kind of
    # number, and the audit's "the robot believes the owner at 1.0" finding is
    # exactly a reader having no way to tell them apart. The reactive gate now
    # reads these three instead of thresholding the float.
    #: The producer's own verdict on this track: ``confirmed`` | ``tracking`` |
    #: ``ambiguous`` | ``searching`` | ``lost``, or ``""`` when the producer
    #: has no notion of one. This is the field the gate keys on for a MEASURED
    #: identity, because the producer is where the boundary was measured.
    state: str = ""
    #: How the identity was established. ``""`` (unstated, the legacy default),
    #: ``mocap_ground_truth`` (the simulator handing over the body it is
    #: drawing), ``channel_prior`` (a fusion stub's hard-coded trust in
    #: whichever channel carried pose), ``pixel_reid`` (a cosine measured
    #: against a gallery whose boundary was calibrated against a known
    #: non-owner) or ``pixel_reid_uncalibrated`` (measured against a boundary
    #: that was GUESSED — P1-C measured that guess admitting a stranger).
    identity_source: str = ""
    #: Headroom above the producer's measured operating point, in cosine
    #: units — but read the next paragraph before trusting the word "headroom".
    #:
    #: **WHAT IT ACTUALLY IS** (corrected under verification; Fable, OT-2 item
    #: 5). The runtime computes it as ``identity_score - gallery.threshold``,
    #: and ``PixelOwnerTrack.identity_score`` is a **time-decayed EMA** of the
    #: per-frame cosine, not the cosine the producer compared against its
    #: threshold. So this is the headroom of a SMOOTHED score, and on a frame
    #: the tracker genuinely confirmed it can be **negative** — the EMA still
    #: carries earlier weak frames while the current frame cleared the line.
    #:
    #: The consequence is one-directional and therefore tolerable: a lagging
    #: EMA makes the gate REFUSE the relaxed band on frames it could have
    #: granted (a re-acquired owner is treated as a stranger for a few frames),
    #: and it can never manufacture headroom that was not there. It is not
    #: fixed here because the per-compare similarity (``_Track.last_similarity``)
    #: is internal to ``owner_tracking``, which card OT-2 may consume and not
    #: touch. The handoff is in ``scrum/20260822/task_17/OT2_STATUS.md`` §10:
    #: publish ``identity_margin_above_threshold = last_similarity -
    #: gallery.threshold`` on ``PixelOwnerTrack`` and read that instead.
    #:
    #: **This is not** ``owner_tracking.PixelOwnerTrack.identity_margin``
    #: either, which is the discriminative gap between the best and second-best
    #: person in frame. Three different quantities, one word; the tracker
    #: already refuses an ambiguous frame with its own margin, and what the
    #: gate wants on top of that is distance above the line.
    identity_margin: float = 0.0
    # ---- END CARD OT-2 --------------------------------------------------


@dataclass(frozen=True)
class DynamicAgentTrack:
    agent_id: str
    kind: str
    x: float
    y: float
    vx: float
    vy: float
    radius_m: float
    yaw: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True)
class LidarObstacle:
    """One bounded polar obstacle return from the local LiDAR adapter."""

    distance_m: float
    bearing_rad: float
    obstacle_id: str | None = None


@dataclass(frozen=True)
class SemanticRegionTrack:
    region_id: str
    label: str
    polygon: tuple[tuple[float, float], ...]
    confidence: float
    source: str = "perception"
    reachable: bool = True
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SemanticObjectTrack:
    """Camera/depth-grounded object usable as a relational navigation goal."""

    object_id: str
    label: str
    position: tuple[float, float, float]
    confidence: float
    source: str = "perception"
    reachable: bool = True
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SimObservation:
    timestamp: float
    robot: RobotPose
    owner: OwnerTrack
    nearest_obstacle_m: float | None = None
    nearest_obstacle_bearing_rad: float | None = None
    nearest_obstacle_id: str | None = None
    lidar_obstacles: tuple[LidarObstacle, ...] = ()
    nearest_person_m: float | None = None
    nearest_person_bearing_rad: float | None = None
    nearest_person_id: str | None = None
    nearest_person_ttc_s: float | None = None
    dynamic_agents: tuple[DynamicAgentTrack, ...] = ()
    semantic_regions: tuple[SemanticRegionTrack, ...] = ()
    collision: bool = False
    emergency_stopped: bool = False
    backend: str = "unknown"
    semantic_objects: tuple[SemanticObjectTrack, ...] = ()
    # Occlusion-true planar scan (body-relative CCW rays), appended after the
    # legacy positional tail to preserve positional-argument compatibility.
    # NaN entries are ignored rays (dropout / self-return); range_max means no
    # return. When empty, no calibrated scan is available and mapped
    # navigation degrades loudly to the point-goal fallback.
    lidar_ranges: tuple[float, ...] = ()
    lidar_angle_min_rad: float | None = None
    lidar_angle_increment_rad: float | None = None
    lidar_range_min_m: float | None = None
    lidar_range_max_m: float | None = None


class SimulatorBackend(Protocol):
    name: str

    def observe(self) -> SimObservation: ...

    def move(self, command: VelocityCommand) -> None: ...

    def stop(self) -> None: ...

    def pose(self, pose: Pose) -> None: ...

    def trajectory(self, skill: object) -> None: ...

    def expression(self, joint_offsets: dict[str, float]) -> None:
        """Hold a decorative additive joint overlay (optional capability).

        Backends without an expression channel inherit this no-op: expressive
        liveness must degrade to snapshot-only rendering, never fail a run.
        """

    def move_owner(self, dx: float, dy: float) -> None: ...
