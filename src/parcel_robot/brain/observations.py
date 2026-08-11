"""Build a bounded planning snapshot from already-captured runtime state."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Iterable, Mapping

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.backends.base import SimObservation
from parcel_robot.models import VelocityCommand

from .contracts import (
    SCHEMA_VERSION,
    BatteryStateSnapshot,
    FrozenDict,
    ObservationSnapshot,
    ObservedEntity,
    ResourceLease,
    RobotStateSnapshot,
    SafetyStateSnapshot,
    SensorSnapshot,
    TaskStateSnapshot,
)


def build_observation_snapshot(
    observation: SimObservation | None,
    *,
    snapshot_id: str,
    now: float | None = None,
    sensor_stale_s: float = 0.6,
    camera_enabled: bool = True,
    lidar_enabled: bool = True,
    controller_state: str = "unknown",
    measured_velocity: VelocityCommand | None = None,
    emergency_stopped: bool = False,
    obstacle_stop_m: float = 0.65,
    # Derived, not restated: the last 1.0 m person literal on any construction
    # path (owner-authorized person-clearance retune, 2026-08-10). The runtime
    # always passes ``self.person_stop_m`` explicitly, so this default never
    # fires there; it existed only to let an un-wired caller report
    # ``collision_imminent`` against the retired 1.0 m clearance.
    person_stop_m: float = DEFAULT_SAFETY_ENVELOPE.person_stop(0.0),
    task: TaskStateSnapshot | None = None,
    resource_leases: Iterable[ResourceLease] = (),
    battery: BatteryStateSnapshot | None = None,
    owner_heading_available: bool = False,
) -> ObservationSnapshot:
    """Create the sole LLM-facing scene view without querying a provider.

    Semantic entities retain source/confidence and useful affordance flags, but
    their simulator/world coordinates and region polygons are intentionally not
    copied into the language-model snapshot. Metric navigation continues to
    consume those camera/depth products outside the language plane.
    """

    timestamp = time.monotonic() if now is None else float(now)
    if not math.isfinite(timestamp) or timestamp < 0.0:
        raise ValueError("snapshot time must be finite and non-negative")
    if not math.isfinite(sensor_stale_s) or sensor_stale_s <= 0.0:
        raise ValueError("sensor_stale_s must be positive and finite")
    if any(not math.isfinite(value) or value <= 0.0 for value in (obstacle_stop_m, person_stop_m)):
        raise ValueError("safety stop distances must be positive and finite")

    observed_at = observation.timestamp if observation is not None else None
    age_s = None if observed_at is None else max(0.0, timestamp - observed_at)
    transport_fresh = (
        observation is not None
        and observed_at is not None
        and -0.05 <= timestamp - observed_at <= sensor_stale_s
    )
    source = _bounded_source(observation.backend if observation is not None else "unavailable")
    camera = _sensor(
        "camera",
        enabled=camera_enabled,
        connected=observation is not None,
        fresh=transport_fresh,
        source=f"{source}:camera",
        observed_at=observed_at,
        age_s=age_s,
    )
    lidar = _sensor(
        "lidar",
        enabled=lidar_enabled,
        connected=observation is not None,
        fresh=transport_fresh,
        source=f"{source}:lidar",
        observed_at=observed_at,
        age_s=age_s,
    )

    velocity = measured_velocity or VelocityCommand()
    moving = math.hypot(velocity.vx, velocity.vy) > 0.03 or abs(velocity.vyaw) > 0.05
    robot = RobotStateSnapshot(
        moving=moving,
        controller_state=str(controller_state)[:80] or "unknown",
        # Metric odometry remains available to the deterministic navigation
        # controller outside this contract. The LLM does not need world-frame
        # coordinates or yaw to select a semantic skill, so do not expose
        # simulator truth (or future localization details) here.
        x=None,
        y=None,
        z=None,
        yaw_rad=None,
    )

    obstacle = observation.nearest_obstacle_m if observation is not None else None
    person = observation.nearest_person_m if observation is not None else None
    collision_imminent = bool(
        observation is not None
        and (
            observation.collision
            or obstacle is not None
            and obstacle <= obstacle_stop_m
            or person is not None
            and person <= person_stop_m
        )
    )
    safety = SafetyStateSnapshot(
        emergency_stopped=bool(
            emergency_stopped or observation is not None and observation.emergency_stopped
        ),
        collision_imminent=collision_imminent,
        telemetry_fresh=transport_fresh,
        nearest_obstacle_m=obstacle,
        nearest_person_m=person,
    )
    entities = _entities(
        observation,
        owner_heading_available=owner_heading_available,
    )
    return ObservationSnapshot(
        schema_version=SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        captured_at_monotonic_s=timestamp,
        camera=camera,
        lidar=lidar,
        robot=robot,
        safety=safety,
        battery=battery or BatteryStateSnapshot(),
        task=task or TaskStateSnapshot(),
        resource_leases=tuple(resource_leases),
        entities=entities,
    )


def task_state_from_executive(value: Mapping[str, object] | None) -> TaskStateSnapshot:
    """Translate one executive task row without treating it as world state."""

    if not value:
        return TaskStateSnapshot()
    state = str(value.get("state", "idle"))
    if state in {"succeeded", "failed", "cancelled"}:
        return TaskStateSnapshot()
    return TaskStateSnapshot(
        state=state,
        task_id=_optional_text(value.get("task_id")),
        plan_revision=_optional_int(value.get("plan_revision")),
        step_id=_optional_text(value.get("step_id")),
        at_checkpoint=bool(value.get("at_checkpoint", False)),
    )


def _sensor(
    name: str,
    *,
    enabled: bool,
    connected: bool,
    fresh: bool,
    source: str,
    observed_at: float | None,
    age_s: float | None,
) -> SensorSnapshot:
    available = bool(enabled and connected)
    return SensorSnapshot(
        name=name,
        available=available,
        fresh=bool(available and fresh),
        source=source,
        observed_at_monotonic_s=observed_at if available else None,
        age_ms=age_s * 1000.0 if available and age_s is not None else None,
    )


def _entities(
    observation: SimObservation | None,
    *,
    owner_heading_available: bool,
) -> tuple[ObservedEntity, ...]:
    if observation is None:
        return ()
    entities: list[ObservedEntity] = []
    owner = observation.owner
    if owner.visible:
        entities.append(
            ObservedEntity(
                entity_id=_safe_id("owner", owner.owner_id),
                kind="owner",
                label="owner",
                confidence=owner.confidence,
                source=f"{_bounded_source(observation.backend)}:camera_track",
                observed_at_monotonic_s=observation.timestamp,
                attributes=FrozenDict({"motion_heading_available": bool(owner_heading_available)}),
            )
        )
    for region in observation.semantic_regions:
        entities.append(
            ObservedEntity(
                entity_id=_safe_id("region", region.region_id),
                kind="semantic_region",
                label=region.label,
                confidence=region.confidence,
                source=_bounded_source(region.source),
                observed_at_monotonic_s=observation.timestamp,
                attributes=FrozenDict({"reachable": bool(region.reachable)}),
            )
        )
    for item in observation.semantic_objects:
        entities.append(
            ObservedEntity(
                entity_id=_safe_id("object", item.object_id),
                kind="semantic_object",
                label=item.label,
                confidence=item.confidence,
                source=_bounded_source(item.source),
                observed_at_monotonic_s=observation.timestamp,
                attributes=FrozenDict({"reachable": bool(item.reachable)}),
            )
        )
    return tuple(entities[:64])


def _safe_id(prefix: str, value: object) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value)).strip("-.")[:96]
    return f"{prefix}:{clean or 'unknown'}"


def _bounded_source(value: object) -> str:
    return (str(value).strip() or "unknown")[:64]


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = ["build_observation_snapshot", "task_state_from_executive"]
