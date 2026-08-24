from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

SOCIAL_AGENT_KINDS = frozenset({"pedestrian", "cyclist"})


@dataclass(frozen=True)
class RoutePoint:
    x: float
    y: float
    pause_s: float = 0.0


@dataclass(frozen=True)
class DynamicAgentSpec:
    """A deterministic route for one city actor rendered as a mocap body."""

    agent_id: str
    body_name: str
    kind: str
    route: tuple[RoutePoint, ...]
    speed_mps: float
    radius_m: float = 0.24

    def __post_init__(self) -> None:
        if len(self.route) < 2:
            raise ValueError("a dynamic-agent route requires at least two points")
        if self.speed_mps <= 0.0 or self.radius_m <= 0.0:
            raise ValueError("dynamic-agent speed and radius must be positive")


@dataclass
class DynamicAgent:
    spec: DynamicAgentSpec
    x: float = field(init=False)
    y: float = field(init=False)
    yaw: float = field(init=False, default=0.0)
    speed_mps: float = field(init=False, default=0.0)
    waypoint_index: int = field(init=False, default=1)
    wait_remaining_s: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.x = self.spec.route[0].x
        self.y = self.spec.route[0].y
        target = self.spec.route[1]
        self.yaw = math.atan2(target.y - self.y, target.x - self.x)

    def step(self, dt: float, speed_scale: float) -> None:
        if dt <= 0.0:
            return
        if self.wait_remaining_s > 0.0:
            self.wait_remaining_s = max(0.0, self.wait_remaining_s - dt)
            self.speed_mps = 0.0
            return

        remaining = self.spec.speed_mps * speed_scale * dt
        self.speed_mps = self.spec.speed_mps * speed_scale
        # A large simulation step may cross more than one waypoint.
        for _ in range(len(self.spec.route) + 1):
            target = self.spec.route[self.waypoint_index]
            dx, dy = target.x - self.x, target.y - self.y
            distance = math.hypot(dx, dy)
            if distance > 1e-9:
                self.yaw = math.atan2(dy, dx)
            if distance > remaining:
                self.x += math.cos(self.yaw) * remaining
                self.y += math.sin(self.yaw) * remaining
                return
            self.x, self.y = target.x, target.y
            remaining -= distance
            self.waypoint_index = (self.waypoint_index + 1) % len(self.spec.route)
            if target.pause_s > 0.0:
                self.wait_remaining_s = target.pause_s
                self.speed_mps = 0.0
                return
            if remaining <= 1e-9:
                return

    def snapshot(self) -> dict[str, object]:
        return {
            "id": self.spec.agent_id,
            "body": self.spec.body_name,
            "kind": self.spec.kind,
            "x": self.x,
            "y": self.y,
            "yaw": self.yaw,
            "vx": math.cos(self.yaw) * self.speed_mps,
            "vy": math.sin(self.yaw) * self.speed_mps,
            "radius_m": self.spec.radius_m,
        }


class DynamicCity:
    """Repeatable moving actors for the lightweight MuJoCo city backend.

    This is intentionally engine-neutral. The MuJoCo process copies each
    actor pose to a mocap body, while tests can exercise route and proximity
    behavior without loading a renderer.
    """

    def __init__(
        self,
        specs: tuple[DynamicAgentSpec, ...],
        *,
        enabled: bool = True,
        speed_scale: float = 1.0,
        seed: int = 7,
    ):
        if speed_scale < 0.0 or not math.isfinite(speed_scale):
            raise ValueError("dynamic-city speed_scale must be finite and non-negative")
        self.enabled = enabled
        self.speed_scale = speed_scale
        self.seed = seed
        self.agents = [DynamicAgent(spec) for spec in specs]
        # Small deterministic phase offsets avoid a synchronized-looking crowd.
        rng = random.Random(seed)
        for actor in self.agents:
            actor.step(rng.uniform(0.0, 2.5), speed_scale)

    @classmethod
    def default(
        cls,
        *,
        enabled: bool = True,
        speed_scale: float = 1.0,
        seed: int = 7,
    ) -> DynamicCity:
        return cls(
            default_dynamic_agent_specs(),
            enabled=enabled,
            speed_scale=speed_scale,
            seed=seed,
        )

    def step(self, dt: float) -> None:
        if not self.enabled:
            return
        for actor in self.agents:
            actor.step(dt, self.speed_scale)

    def snapshots(self, agent_ids: Iterable[str] | None = None) -> list[dict[str, object]]:
        if not self.enabled:
            return []
        selected = None if agent_ids is None else frozenset(agent_ids)
        return [
            actor.snapshot()
            for actor in self.agents
            if selected is None or actor.spec.agent_id in selected
        ]

    def nearest_person(
        self,
        x: float,
        y: float,
        heading_rad: float = 0.0,
        *,
        robot_radius_m: float = 0.32,
    ) -> dict[str, object] | None:
        candidates: list[dict[str, object]] = []
        for actor in self.agents:
            if not self.enabled or actor.spec.kind not in SOCIAL_AGENT_KINDS:
                continue
            center_distance = math.hypot(actor.x - x, actor.y - y)
            clearance = max(
                0.0,
                center_distance - actor.spec.radius_m - robot_radius_m,
            )
            bearing = (math.atan2(actor.y - y, actor.x - x) - heading_rad + math.pi) % (
                2.0 * math.pi
            ) - math.pi
            item = actor.snapshot()
            item.update({"distance_m": clearance, "bearing_rad": bearing})
            candidates.append(item)
        return min(candidates, key=lambda item: float(item["distance_m"])) if candidates else None


def circle_contact_ttc(
    relative_x: float,
    relative_y: float,
    relative_vx: float,
    relative_vy: float,
    combined_radius_m: float,
    *,
    horizon_s: float = 10.0,
) -> float | None:
    """Return the earliest circle-contact time for constant relative velocity."""

    values = (
        relative_x,
        relative_y,
        relative_vx,
        relative_vy,
        combined_radius_m,
        horizon_s,
    )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("circle-contact inputs must be finite")
    if combined_radius_m <= 0.0 or horizon_s <= 0.0:
        raise ValueError("circle-contact radius and horizon must be positive")

    c = relative_x * relative_x + relative_y * relative_y - combined_radius_m**2
    if c <= 0.0:
        return 0.0
    a = relative_vx * relative_vx + relative_vy * relative_vy
    if a <= 1e-12:
        return None
    b = 2.0 * (relative_x * relative_vx + relative_y * relative_vy)
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0.0:
        return None
    entry = (-b - math.sqrt(max(0.0, discriminant))) / (2.0 * a)
    if entry < 0.0 or entry > horizon_s:
        return None
    return entry


def select_social_collision_candidate(
    tracks: Iterable[Mapping[str, object]],
    *,
    robot_x: float,
    robot_y: float,
    robot_heading_rad: float,
    robot_vx: float,
    robot_vy: float,
    robot_radius_m: float = 0.32,
    horizon_s: float = 10.0,
) -> dict[str, object] | None:
    """Select earliest collision risk, falling back to nearest clearance.

    ``robot_vx`` and ``robot_vy`` are world-frame velocities. Each input track
    must provide world-frame position/velocity and a circle radius.
    """

    candidates: list[dict[str, object]] = []
    for track in tracks:
        kind = str(track.get("kind", ""))
        if kind not in SOCIAL_AGENT_KINDS | {"owner"}:
            continue
        x = float(track["x"])
        y = float(track["y"])
        radius = float(track["radius_m"])
        relative_x = x - robot_x
        relative_y = y - robot_y
        combined_radius = robot_radius_m + radius
        center_distance = math.hypot(relative_x, relative_y)
        bearing = (math.atan2(relative_y, relative_x) - robot_heading_rad + math.pi) % (
            2.0 * math.pi
        ) - math.pi
        ttc = circle_contact_ttc(
            relative_x,
            relative_y,
            float(track.get("vx", 0.0)) - robot_vx,
            float(track.get("vy", 0.0)) - robot_vy,
            combined_radius,
            horizon_s=horizon_s,
        )
        item = dict(track)
        item.update(
            {
                "distance_m": max(0.0, center_distance - combined_radius),
                "bearing_rad": bearing,
                "time_to_collision_s": ttc,
            }
        )
        candidates.append(item)

    if not candidates:
        return None
    risks = [item for item in candidates if item["time_to_collision_s"] is not None]
    if risks:
        selected = min(
            risks,
            key=lambda item: (
                float(item["time_to_collision_s"]),
                float(item["distance_m"]),
                str(item.get("id", "")),
            ),
        )
        selected["selection"] = "earliest_collision"
        return selected
    selected = min(
        candidates,
        key=lambda item: (float(item["distance_m"]), str(item.get("id", ""))),
    )
    selected["selection"] = "nearest_clearance"
    return selected


def default_dynamic_agent_specs() -> tuple[DynamicAgentSpec, ...]:
    """City-block routes: opposing sidewalks, a crosswalk, and a plaza loop."""

    point = RoutePoint
    return (
        DynamicAgentSpec(
            "ped-1",
            "pedestrian_1",
            "pedestrian",
            (point(0.8, 2.85), point(4.15, 2.85, 0.7), point(0.8, 2.85, 0.4)),
            0.78,
        ),
        DynamicAgentSpec(
            "ped-2",
            "pedestrian_2",
            "pedestrian",
            (point(4.05, 3.55), point(0.8, 3.55, 1.0), point(4.05, 3.55, 0.3)),
            0.62,
        ),
        DynamicAgentSpec(
            "ped-3",
            "pedestrian_3",
            "pedestrian",
            (point(3.15, -3.0), point(3.15, 3.75, 0.8), point(3.15, -3.0, 0.5)),
            0.72,
        ),
        DynamicAgentSpec(
            "ped-4",
            "pedestrian_4",
            "pedestrian",
            (point(-5.5, -2.7), point(5.5, -2.7, 0.4), point(-5.5, -2.7, 0.9)),
            0.88,
        ),
        DynamicAgentSpec(
            "ped-5",
            "pedestrian_5",
            "pedestrian",
            (
                point(-1.4, 1.6),
                point(-0.4, 1.6),
                point(-0.4, 3.8, 0.6),
                point(-1.4, 3.8),
            ),
            0.55,
        ),
        DynamicAgentSpec(
            "ped-6",
            "pedestrian_6",
            "pedestrian",
            (point(4.8, -1.5), point(2.3, -1.5), point(2.3, 1.6), point(4.8, 1.6)),
            0.68,
        ),
        DynamicAgentSpec(
            "ped-7",
            "pedestrian_7",
            "pedestrian",
            (point(-3.8, 1.4), point(-3.8, -2.0, 0.5), point(-3.8, 1.4, 0.5)),
            0.58,
        ),
        DynamicAgentSpec(
            "cyclist-1",
            "cyclist_1",
            "cyclist",
            (point(-7.0, 0.0), point(7.0, 0.0), point(-7.0, 0.0)),
            1.7,
            radius_m=0.38,
        ),
    )
