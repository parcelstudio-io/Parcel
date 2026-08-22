"""Incremental LiDAR occupancy mapping and deterministic global routing.

The planner in this module has a deliberately narrow sensor boundary: robot
pose, heading, a planar LiDAR scan, and a metric goal.  It never consumes a
simulator map, evaluator path, semantic ground truth, or privileged collision
geometry.  That makes the same component usable behind a simulator adapter and
on a Unitree robot once pose and LaserScan data are available.

This module does not command locomotion.  :class:`RollingGridPlanner` produces
a world-frame route, and :meth:`RollingGridPlanner.next_waypoint` expresses the
next target in Parcel's body convention (positive x forward, positive y left).
The existing controller and safety shield remain responsible for converting
that target to bounded ``vx``, ``vy``, and yaw-rate requests.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import count, pairwise
from typing import Literal

import numpy as np

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE, gate_lateral_clearance_m

GridCell = tuple[int, int]
WorldPoint = tuple[float, float]


class CellState(str, Enum):
    """Observable state of one grid cell before footprint inflation."""

    UNKNOWN = "unknown"
    FREE = "free"
    OCCUPIED = "occupied"
    OUT_OF_BOUNDS = "out_of_bounds"


@dataclass(frozen=True)
class Pose2D:
    """World-frame planar pose; heading is counter-clockwise from world +x."""

    x: float
    y: float
    heading_rad: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.heading_rad)):
            raise ValueError("pose values must be finite")

    @property
    def xy(self) -> WorldPoint:
        return (self.x, self.y)


@dataclass(frozen=True)
class LidarScan:
    """One planar scan with body-relative, counter-clockwise ray angles.

    Positive infinity is a valid no-return measurement and clears free space
    through ``range_max_m``.  NaN, negative infinity, and below-minimum returns
    are ignored.  A finite value at the sensor maximum is also a no-return, so
    maximum-range rays never create a ring of phantom obstacles.
    """

    ranges_m: Sequence[float]
    angle_min_rad: float
    angle_increment_rad: float
    range_min_m: float = 0.05
    range_max_m: float = 30.0

    def __post_init__(self) -> None:
        try:
            immutable_ranges = tuple(float(value) for value in self.ranges_m)
        except (TypeError, ValueError) as exc:
            raise ValueError("LiDAR ranges must be numeric") from exc
        object.__setattr__(self, "ranges_m", immutable_ranges)
        if len(self.ranges_m) == 0:
            raise ValueError("LiDAR scan must contain at least one range")
        if not math.isfinite(self.angle_min_rad):
            raise ValueError("LiDAR angle_min_rad must be finite")
        if not math.isfinite(self.angle_increment_rad) or self.angle_increment_rad == 0.0:
            raise ValueError("LiDAR angle_increment_rad must be finite and non-zero")
        if not math.isfinite(self.range_min_m) or self.range_min_m < 0.0:
            raise ValueError("LiDAR range_min_m must be finite and non-negative")
        if not math.isfinite(self.range_max_m) or self.range_max_m <= self.range_min_m:
            raise ValueError("LiDAR range_max_m must exceed range_min_m")

    @classmethod
    def from_extras(
        cls,
        ranges_m: Sequence[float],
        extras: Mapping[str, object],
    ) -> LidarScan:
        """Build a scan from ``NavObservation.lidar`` and geometry in extras.

        Geometry may be flat or under ``extras["lidar_geometry"]``.  Requiring
        the angular increment and maximum range avoids silently assuming a
        simulator-specific scan layout.
        """

        nested = extras.get("lidar_geometry")
        geometry = nested if isinstance(nested, Mapping) else extras

        def required(name: str) -> float:
            value = geometry.get(name)
            if not isinstance(value, (int, float)):
                raise TypeError(f"missing numeric LiDAR geometry field: {name}")
            return float(value)

        minimum = geometry.get("range_min_m", 0.05)
        if not isinstance(minimum, (int, float)):
            raise TypeError("LiDAR geometry range_min_m must be numeric")
        return cls(
            ranges_m=ranges_m,
            angle_min_rad=required("angle_min_rad"),
            angle_increment_rad=required("angle_increment_rad"),
            range_min_m=float(minimum),
            range_max_m=required("range_max_m"),
        )


@dataclass(frozen=True)
class GridPlannerConfig:
    """Map, uncertainty, footprint, and route-selection policy.

    Unknown cells are traversable by default but more expensive than observed
    free cells.  Blocking unknown space would deadlock a robot with a partial
    field of view; treating it as free would encourage unsafe shortcuts.  The
    default penalty is the middle ground appropriate for incremental mapping,
    while ``allow_unknown=False`` remains available for fully explored areas.
    """

    resolution_m: float = 0.10
    grid_size_cells: int = 161
    # Card P1-E: read off the authority instead of ``geometry``'s deprecation
    # shim. Same body, same number (0.32 m) — ``SafetyEnvelope`` is where the
    # footprint has lived since 2026-08-07, and the reactive gate the planner
    # now has to agree with reads it from there too.
    robot_radius_m: float = DEFAULT_SAFETY_ENVELOPE.footprint_radius_m
    # ``safety_margin_m`` is the legacy hard margin.  Optional explicit hard
    # and comfort margins let an experimental profile prefer extra clearance
    # without declaring that entire comfort zone impassable.  Leaving the new
    # fields unset preserves the original binary-inflation behavior exactly.
    safety_margin_m: float = 0.10
    hard_safety_margin_m: float | None = None
    comfort_safety_margin_m: float | None = None
    # ``gate_clearance_m`` is the STOP RING the final reactive gate enforces
    # against whatever this map's occupied cells represent — card P1-E, audit
    # §6 ("the planner and the gate disagree on the envelope"). Set it from
    # ``ReactiveSafetyPolicy.obstacle_stop_m`` (lidar map) or ``person_stop_m``
    # (a map of people) and the planner will not route through gaps the gate
    # refuses to drive down; the conversion from a forward ring to a lateral
    # radius is the gate's own directional cone and lives in the authority
    # (:func:`~parcel_robot.authority.gate_lateral_clearance_m`).
    #
    # ``None`` is the legacy footprint-only inflation, byte-for-byte. It is the
    # DEFAULT deliberately: at the shipped obstacle ring the derived radius is
    # 0.593 m, which closes every corridor narrower than 1.19 m — including a
    # standard 0.8-0.9 m interior doorway. Switching it on by default would
    # make the indoor companion refuse to plan through its own front door and
    # would move every frozen navigation baseline at once. Turning it on is a
    # navigation-profile decision (see the P1-E status doc's handoff), not a
    # planner default.
    gate_clearance_m: float | None = None
    comfort_cost_weight: float = 0.0
    lidar_range_cap_m: float = 12.0
    hit_log_odds: float = 0.90
    miss_log_odds: float = 0.45
    min_log_odds: float = -4.0
    max_log_odds: float = 4.0
    occupied_log_odds: float = 0.65
    allow_unknown: bool = True
    unknown_cost: float = 2.5
    goal_tolerance_m: float = 0.25
    partial_goal_search_m: float = 0.50
    lookahead_m: float = 0.90
    # Experimental rolling-horizon recovery. When the clipped point-goal
    # target is in a different connected component, a reachable map-edge cell
    # can move the robot far enough to reveal a route around the obstruction.
    # This is disabled by default so existing/production planning semantics are
    # bit-for-bit unchanged unless a model profile explicitly opts in.
    reachable_frontier_fallback: bool = False
    # The v2 experiment first runs unknown-admitting A* and then, when that
    # route cannot be executed, performs a second observed-connectivity
    # search.  ``observed_first`` is a separate, opt-in v3 experiment that
    # obtains the reachable goal/frontier/window continuation from one
    # hard-safe observed-component traversal.  The default preserves v2 and
    # production behavior exactly.
    frontier_search_mode: Literal["post_astar", "observed_first"] = "post_astar"
    frontier_band_m: float = 0.60
    frontier_min_progress_m: float = 0.10
    # Experimental v4 escape hatch. Goal-progress-only frontiers cannot leave
    # a U-shaped trap or pass the end of a wall when every safe first move is
    # temporarily lateral/away from the Euclidean goal. When explicitly
    # enabled, the same observed-only component search may choose a sufficiently
    # distant frontier within a bounded goal-distance regression. Defaults keep
    # v3 and production behavior unchanged.
    bounded_detour_frontier_fallback: bool = False
    frontier_max_goal_regression_m: float = 1.50
    frontier_detour_min_travel_m: float = 0.60
    max_expansions: int = 100_000

    def __post_init__(self) -> None:
        finite_positive = {
            "resolution_m": self.resolution_m,
            "robot_radius_m": self.robot_radius_m,
            "lidar_range_cap_m": self.lidar_range_cap_m,
            "hit_log_odds": self.hit_log_odds,
            "miss_log_odds": self.miss_log_odds,
            "max_log_odds": self.max_log_odds,
            "unknown_cost": self.unknown_cost,
            "goal_tolerance_m": self.goal_tolerance_m,
            "partial_goal_search_m": self.partial_goal_search_m,
            "lookahead_m": self.lookahead_m,
            "frontier_band_m": self.frontier_band_m,
        }
        for name, value in finite_positive.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(self.safety_margin_m) or self.safety_margin_m < 0.0:
            raise ValueError("safety_margin_m must be finite and non-negative")
        for name, value in (
            ("hard_safety_margin_m", self.hard_safety_margin_m),
            ("comfort_safety_margin_m", self.comfort_safety_margin_m),
            ("gate_clearance_m", self.gate_clearance_m),
        ):
            if value is not None and (not math.isfinite(value) or value < 0.0):
                raise ValueError(f"{name} must be finite and non-negative when set")
        if (
            self.comfort_safety_margin_m is not None
            and self.comfort_safety_margin_m + 1e-12 < self.effective_hard_margin_m
        ):
            raise ValueError("comfort_safety_margin_m must not be below the hard margin")
        if not math.isfinite(self.comfort_cost_weight) or self.comfort_cost_weight < 0.0:
            raise ValueError("comfort_cost_weight must be finite and non-negative")
        if not math.isfinite(self.min_log_odds) or self.min_log_odds >= 0.0:
            raise ValueError("min_log_odds must be finite and negative")
        if self.max_log_odds <= self.occupied_log_odds:
            raise ValueError("max_log_odds must exceed occupied_log_odds")
        if not self.min_log_odds < self.occupied_log_odds < self.max_log_odds:
            raise ValueError("occupied_log_odds must be inside the log-odds bounds")
        if self.unknown_cost < 1.0:
            raise ValueError("unknown_cost must not be cheaper than observed free space")
        if not isinstance(self.reachable_frontier_fallback, bool):
            raise TypeError("reachable_frontier_fallback must be boolean")
        if self.frontier_search_mode not in {"post_astar", "observed_first"}:
            raise ValueError("frontier_search_mode must be 'post_astar' or 'observed_first'")
        if self.frontier_search_mode == "observed_first" and not self.reachable_frontier_fallback:
            raise ValueError("observed_first frontier search requires reachable_frontier_fallback")
        if not math.isfinite(self.frontier_min_progress_m) or self.frontier_min_progress_m < 0.0:
            raise ValueError("frontier_min_progress_m must be finite and non-negative")
        if not isinstance(self.bounded_detour_frontier_fallback, bool):
            raise TypeError("bounded_detour_frontier_fallback must be boolean")
        if self.bounded_detour_frontier_fallback and self.frontier_search_mode != "observed_first":
            raise ValueError(
                "bounded detour frontier fallback requires observed_first frontier search"
            )
        if (
            not math.isfinite(self.frontier_max_goal_regression_m)
            or self.frontier_max_goal_regression_m < 0.0
        ):
            raise ValueError("frontier_max_goal_regression_m must be finite and non-negative")
        if (
            not math.isfinite(self.frontier_detour_min_travel_m)
            or self.frontier_detour_min_travel_m <= 0.0
        ):
            raise ValueError("frontier_detour_min_travel_m must be finite and positive")
        if self.grid_size_cells < 11 or self.grid_size_cells % 2 == 0:
            raise ValueError("grid_size_cells must be an odd integer of at least 11")
        if not 1 <= self.max_expansions <= 10_000_000:
            raise ValueError("max_expansions must be in [1, 10000000]")
        if self.inflation_radius_m >= self.window_span_m / 2.0:
            raise ValueError("inflated footprint must fit inside half the rolling window")
        if self.comfort_radius_m >= self.window_span_m / 2.0:
            raise ValueError("comfort zone must fit inside half the rolling window")

    @property
    def effective_hard_margin_m(self) -> float:
        return (
            self.safety_margin_m if self.hard_safety_margin_m is None else self.hard_safety_margin_m
        )

    @property
    def effective_comfort_margin_m(self) -> float:
        return (
            self.effective_hard_margin_m
            if self.comfort_safety_margin_m is None
            else self.comfort_safety_margin_m
        )

    @property
    def gate_lateral_clearance_m(self) -> float:
        """Lateral radius the reactive gate's stop ring implies (0.0 if unset)."""

        if self.gate_clearance_m is None:
            return 0.0
        return gate_lateral_clearance_m(self.gate_clearance_m)

    @property
    def inflation_radius_m(self) -> float:
        """Hard, non-traversable radius: footprint inflation, never inside the gate.

        Card P1-E. The first term is the historical footprint + hard margin.
        The second is the lateral clearance the FINAL safety gate will demand
        of the same cells (``gate_clearance_m``); taking the max is what makes
        "the planner does not choose corridors the gate refuses" true, and
        leaving ``gate_clearance_m`` unset reproduces the old value exactly.
        """

        return max(
            self.robot_radius_m + self.effective_hard_margin_m,
            self.gate_lateral_clearance_m,
        )

    @property
    def comfort_radius_m(self) -> float:
        """Preferred-clearance radius; cells in this zone remain traversable."""

        return self.robot_radius_m + self.effective_comfort_margin_m

    @property
    def comfort_cost_enabled(self) -> bool:
        return (
            self.comfort_cost_weight > 0.0
            and self.comfort_radius_m > self.inflation_radius_m + 1e-12
        )

    @property
    def window_span_m(self) -> float:
        return self.grid_size_cells * self.resolution_m


@dataclass(frozen=True)
class GridBounds:
    """Half-open rolling-map bounds in global cell and world coordinates."""

    origin_global_cell: GridCell
    size_cells: int
    resolution_m: float

    @property
    def min_world_xy(self) -> WorldPoint:
        return (
            self.origin_global_cell[0] * self.resolution_m,
            self.origin_global_cell[1] * self.resolution_m,
        )

    @property
    def max_world_xy(self) -> WorldPoint:
        return (
            (self.origin_global_cell[0] + self.size_cells) * self.resolution_m,
            (self.origin_global_cell[1] + self.size_cells) * self.resolution_m,
        )

    def contains(self, point: WorldPoint) -> bool:
        minimum = self.min_world_xy
        maximum = self.max_world_xy
        return minimum[0] <= point[0] < maximum[0] and minimum[1] <= point[1] < maximum[1]


@dataclass(frozen=True)
class MappingUpdate:
    """Deterministic diagnostics for a scan integration."""

    generation: int
    valid_rays: int
    hit_cells: int
    free_cells: int
    shifted_cells_xy: GridCell


RouteStatus = Literal["at_goal", "planned", "partial", "goal_blocked", "no_path"]


@dataclass(frozen=True)
class RoutePlan:
    """A smoothed route backed only by the current sensor-built grid."""

    status: RouteStatus
    waypoints_world: tuple[WorldPoint, ...]
    requested_goal_world: WorldPoint
    planning_target_world: WorldPoint | None
    reaches_goal_region: bool
    expanded_nodes: int
    path_length_m: float
    unknown_cells_on_grid_path: int
    map_generation: int
    note: str = ""

    @property
    def usable(self) -> bool:
        return self.status in {"at_goal", "planned", "partial"} and bool(self.waypoints_world)


@dataclass(frozen=True)
class BodyWaypoint:
    """A route target in the Unitree/Parcel body-frame convention."""

    world_xy: WorldPoint
    forward_m: float
    left_m: float
    distance_m: float
    heading_error_rad: float
    route_index: int
    is_final: bool


class RollingOccupancyGrid:
    """A robot-centered log-odds grid whose overlap survives integer shifts."""

    def __init__(self, config: GridPlannerConfig | None = None) -> None:
        self.config = config or GridPlannerConfig()
        shape = (self.config.grid_size_cells, self.config.grid_size_cells)
        self._log_odds = np.zeros(shape, dtype=np.float32)
        self._observed = np.zeros(shape, dtype=np.bool_)
        self._origin_global_cell: GridCell | None = None
        self._generation = 0
        self._inflated_cache_generation = -1
        self._inflated_cache: np.ndarray | None = None
        self._comfort_cache_generation = -1
        self._comfort_cache: np.ndarray | None = None

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def initialized(self) -> bool:
        return self._origin_global_cell is not None

    @property
    def bounds(self) -> GridBounds:
        if self._origin_global_cell is None:
            raise RuntimeError("grid has not received a pose")
        return GridBounds(
            origin_global_cell=self._origin_global_cell,
            size_cells=self.config.grid_size_cells,
            resolution_m=self.config.resolution_m,
        )

    def reset(self) -> None:
        self._log_odds.fill(0.0)
        self._observed.fill(False)
        self._origin_global_cell = None
        self._generation += 1
        self._invalidate_inflation()

    def update(self, pose: Pose2D, scan: LidarScan) -> MappingUpdate:
        """Recenter and integrate one scan using inverse sensor evidence."""

        shift = self._recenter(pose.xy)
        start = self.world_to_local_cell(pose.xy)
        assert start is not None  # recentering always places the robot in the window
        free_mask = np.zeros_like(self._observed)
        hit_mask = np.zeros_like(self._observed)
        free_mask[start[1], start[0]] = True
        valid_rays = 0
        effective_max = min(scan.range_max_m, self.config.lidar_range_cap_m)
        start_global = self.world_to_global_cell(pose.xy)
        endpoint_x: list[int] = []
        endpoint_y: list[int] = []
        ray_is_hit: list[bool] = []

        for index, raw_value in enumerate(scan.ranges_m):
            raw_range = float(raw_value)
            if math.isnan(raw_range) or raw_range == -math.inf or raw_range < scan.range_min_m:
                continue
            if raw_range == math.inf:
                distance = effective_max
                is_hit = False
            elif not math.isfinite(raw_range):
                continue
            else:
                distance = min(raw_range, effective_max)
                is_hit = raw_range < effective_max - 1e-6 and raw_range < scan.range_max_m - 1e-6
            if distance < scan.range_min_m:
                continue

            valid_rays += 1
            angle = pose.heading_rad + scan.angle_min_rad + index * scan.angle_increment_rad
            endpoint = (
                pose.x + math.cos(angle) * distance,
                pose.y + math.sin(angle) * distance,
            )
            endpoint_global = self.world_to_global_cell(endpoint)
            endpoint_x.append(endpoint_global[0])
            endpoint_y.append(endpoint_global[1])
            ray_is_hit.append(is_hit)

        if valid_rays:
            self._accumulate_scan_masks(
                start_global=start_global,
                endpoint_x=np.asarray(endpoint_x, dtype=np.int64),
                endpoint_y=np.asarray(endpoint_y, dtype=np.int64),
                ray_is_hit=np.asarray(ray_is_hit, dtype=np.bool_),
                free_mask=free_mask,
                hit_mask=hit_mask,
            )

        # A hit wins over free evidence from another ray in the same frame.
        free_mask &= ~hit_mask
        self._apply_log_odds_masks(free_mask=free_mask, hit_mask=hit_mask)

        self._generation += 1
        self._invalidate_inflation()
        return MappingUpdate(
            generation=self._generation,
            valid_rays=valid_rays,
            hit_cells=int(np.count_nonzero(hit_mask)),
            free_cells=int(np.count_nonzero(free_mask)),
            shifted_cells_xy=shift,
        )

    def _accumulate_scan_masks(
        self,
        *,
        start_global: GridCell,
        endpoint_x: np.ndarray,
        endpoint_y: np.ndarray,
        ray_is_hit: np.ndarray,
        free_mask: np.ndarray,
        hit_mask: np.ndarray,
    ) -> None:
        """Rasterize a scan into unique per-frame evidence masks.

        This is a batched form of :func:`_bresenham_cells`.  Every loop
        iteration advances all unfinished rays by one cell, avoiding Python
        set insertion and scalar NumPy writes for every traversed cell.  Hit
        endpoints are excluded from free evidence exactly as they are in the
        scalar inverse sensor model.
        """

        assert self._origin_global_cell is not None
        ray_count = endpoint_x.size
        x = np.full(ray_count, start_global[0], dtype=np.int64)
        y = np.full(ray_count, start_global[1], dtype=np.int64)
        dx = np.abs(endpoint_x - x)
        dy = np.abs(endpoint_y - y)
        step_x = np.where(x < endpoint_x, 1, -1)
        step_y = np.where(y < endpoint_y, 1, -1)
        error = dx - dy
        active = (x != endpoint_x) | (y != endpoint_y)

        origin_x, origin_y = self._origin_global_cell
        size = self.config.grid_size_cells
        hit_in_bounds = (
            ray_is_hit
            & (endpoint_x >= origin_x)
            & (endpoint_x < origin_x + size)
            & (endpoint_y >= origin_y)
            & (endpoint_y < origin_y + size)
        )
        hit_mask[endpoint_y[hit_in_bounds] - origin_y, endpoint_x[hit_in_bounds] - origin_x] = True

        while np.any(active):
            twice_error = 2 * error
            move_x = active & (twice_error > -dy)
            move_y = active & (twice_error < dx)
            error[move_x] -= dy[move_x]
            x[move_x] += step_x[move_x]
            error[move_y] += dx[move_y]
            y[move_y] += step_y[move_y]

            reached_endpoint = (x == endpoint_x) & (y == endpoint_y)
            free = active & ~(ray_is_hit & reached_endpoint)
            local_x = x - origin_x
            local_y = y - origin_y
            free_in_bounds = (
                free & (local_x >= 0) & (local_x < size) & (local_y >= 0) & (local_y < size)
            )
            free_mask[local_y[free_in_bounds], local_x[free_in_bounds]] = True
            active &= ~reached_endpoint

    def _apply_log_odds_masks(self, *, free_mask: np.ndarray, hit_mask: np.ndarray) -> None:
        """Apply one unique miss or hit update per observed cell."""

        # Converting to float64 reproduces the previous scalar calculation:
        # float(np.float32_value) +/- Python float, then assignment to float32.
        free_values = self._log_odds[free_mask].astype(np.float64)
        self._log_odds[free_mask] = np.maximum(
            self.config.min_log_odds,
            free_values - self.config.miss_log_odds,
        ).astype(np.float32)
        hit_values = self._log_odds[hit_mask].astype(np.float64)
        self._log_odds[hit_mask] = np.minimum(
            self.config.max_log_odds,
            hit_values + self.config.hit_log_odds,
        ).astype(np.float32)
        self._observed[free_mask | hit_mask] = True

    def cell_state(self, point: WorldPoint) -> CellState:
        local = self.world_to_local_cell(_finite_point(point, "point"))
        if local is None:
            return CellState.OUT_OF_BOUNDS
        x, y = local
        if not bool(self._observed[y, x]):
            return CellState.UNKNOWN
        if float(self._log_odds[y, x]) >= self.config.occupied_log_odds:
            return CellState.OCCUPIED
        return CellState.FREE

    def is_traversable(self, point: WorldPoint, *, inflated: bool = True) -> bool:
        local = self.world_to_local_cell(_finite_point(point, "point"))
        if local is None:
            return False
        x, y = local
        if inflated and bool(self.inflated_occupied_mask()[y, x]):
            return False
        if not inflated and self.cell_state(point) is CellState.OCCUPIED:
            return False
        return self.config.allow_unknown or bool(self._observed[y, x])

    def world_to_global_cell(self, point: WorldPoint) -> GridCell:
        x, y = _finite_point(point, "point")
        resolution = self.config.resolution_m
        return (math.floor(x / resolution), math.floor(y / resolution))

    def world_to_local_cell(self, point: WorldPoint) -> GridCell | None:
        return self.global_to_local_cell(self.world_to_global_cell(point))

    def global_to_local_cell(self, cell: GridCell) -> GridCell | None:
        if self._origin_global_cell is None:
            return None
        x = int(cell[0]) - self._origin_global_cell[0]
        y = int(cell[1]) - self._origin_global_cell[1]
        size = self.config.grid_size_cells
        return (x, y) if 0 <= x < size and 0 <= y < size else None

    def local_cell_center(self, cell: GridCell) -> WorldPoint:
        if self._origin_global_cell is None:
            raise RuntimeError("grid has not received a pose")
        x, y = cell
        size = self.config.grid_size_cells
        if not 0 <= x < size or not 0 <= y < size:
            raise ValueError("local grid cell is outside map bounds")
        resolution = self.config.resolution_m
        return (
            (self._origin_global_cell[0] + x + 0.5) * resolution,
            (self._origin_global_cell[1] + y + 0.5) * resolution,
        )

    def cell_centers_xy(self) -> np.ndarray:
        """Return every local cell centre as ``(size*size, 2)`` in row-major order.

        The ordering matches ``ndarray.ravel()`` on any grid-shaped mask, so a
        cost vector computed here can be reshaped straight back onto the map.
        """

        if self._origin_global_cell is None:
            raise RuntimeError("grid has not received a pose")
        size = self.config.grid_size_cells
        resolution = self.config.resolution_m
        xs = (self._origin_global_cell[0] + np.arange(size) + 0.5) * resolution
        ys = (self._origin_global_cell[1] + np.arange(size) + 0.5) * resolution
        grid_x, grid_y = np.meshgrid(xs, ys, indexing="xy")
        return np.column_stack((grid_x.ravel(), grid_y.ravel()))

    def inflated_occupied_mask(self) -> np.ndarray:
        """Return the read-only hard footprint-inflated obstacle mask."""

        if self._inflated_cache is None or self._inflated_cache_generation != self._generation:
            occupied = self._observed & (self._log_odds >= self.config.occupied_log_odds)
            inflated = np.zeros_like(occupied)
            radius = self.config.inflation_radius_m
            cell_radius = math.ceil(radius / self.config.resolution_m)
            for dy in range(-cell_radius, cell_radius + 1):
                for dx in range(-cell_radius, cell_radius + 1):
                    if math.hypot(dx, dy) * self.config.resolution_m > radius + 1e-12:
                        continue
                    _or_shifted(inflated, occupied, dx=dx, dy=dy)
            inflated.setflags(write=False)
            self._inflated_cache = inflated
            self._inflated_cache_generation = self._generation
        return self._inflated_cache

    def comfort_cost_mask(self) -> np.ndarray:
        """Return additive A* cost near obstacles outside the hard mask.

        The comfort band is deliberately non-lethal.  Its normalized cost is
        highest immediately outside hard inflation and falls to zero at the
        comfort radius.  With the default zero weight this is an all-zero map,
        preserving the original planner's costs and routes.
        """

        if self._comfort_cache is None or self._comfort_cache_generation != self._generation:
            costs = np.zeros_like(self._log_odds, dtype=np.float32)
            if self.config.comfort_cost_enabled:
                occupied = self._observed & (self._log_odds >= self.config.occupied_log_odds)
                hard_radius = self.config.inflation_radius_m
                comfort_radius = self.config.comfort_radius_m
                band_width = comfort_radius - hard_radius
                cell_radius = math.ceil(comfort_radius / self.config.resolution_m)
                for dy in range(-cell_radius, cell_radius + 1):
                    for dx in range(-cell_radius, cell_radius + 1):
                        distance = math.hypot(dx, dy) * self.config.resolution_m
                        if distance <= hard_radius + 1e-12 or distance >= comfort_radius:
                            continue
                        normalized = (comfort_radius - distance) / band_width
                        _maximum_shifted(
                            costs,
                            occupied,
                            dx=dx,
                            dy=dy,
                            value=self.config.comfort_cost_weight * normalized,
                        )
            costs.setflags(write=False)
            self._comfort_cache = costs
            self._comfort_cache_generation = self._generation
        return self._comfort_cache

    def observed_mask(self) -> np.ndarray:
        """Return an immutable copy useful for diagnostics and visualization."""

        result = self._observed.copy()
        result.setflags(write=False)
        return result

    def _recenter(self, robot_xy: WorldPoint) -> GridCell:
        robot_global = self.world_to_global_cell(robot_xy)
        half = self.config.grid_size_cells // 2
        new_origin = (robot_global[0] - half, robot_global[1] - half)
        if self._origin_global_cell is None:
            self._origin_global_cell = new_origin
            return (0, 0)
        old_origin = self._origin_global_cell
        if new_origin == old_origin:
            return (0, 0)

        size = self.config.grid_size_cells
        new_log_odds = np.zeros_like(self._log_odds)
        new_observed = np.zeros_like(self._observed)
        overlap_min_x = max(old_origin[0], new_origin[0])
        overlap_min_y = max(old_origin[1], new_origin[1])
        overlap_max_x = min(old_origin[0] + size, new_origin[0] + size)
        overlap_max_y = min(old_origin[1] + size, new_origin[1] + size)
        if overlap_min_x < overlap_max_x and overlap_min_y < overlap_max_y:
            old_x = slice(overlap_min_x - old_origin[0], overlap_max_x - old_origin[0])
            old_y = slice(overlap_min_y - old_origin[1], overlap_max_y - old_origin[1])
            new_x = slice(overlap_min_x - new_origin[0], overlap_max_x - new_origin[0])
            new_y = slice(overlap_min_y - new_origin[1], overlap_max_y - new_origin[1])
            new_log_odds[new_y, new_x] = self._log_odds[old_y, old_x]
            new_observed[new_y, new_x] = self._observed[old_y, old_x]
        self._log_odds = new_log_odds
        self._observed = new_observed
        self._origin_global_cell = new_origin
        self._invalidate_inflation()
        return (new_origin[0] - old_origin[0], new_origin[1] - old_origin[1])

    def _invalidate_inflation(self) -> None:
        self._inflated_cache = None
        self._inflated_cache_generation = -1
        self._comfort_cache = None
        self._comfort_cache_generation = -1


class RollingGridPlanner:
    """Sensor-only rolling mapper, A* router, and body-waypoint selector."""

    _NEIGHBORS: tuple[tuple[int, int, float], ...] = (
        (1, 0, 1.0),
        (0, 1, 1.0),
        (-1, 0, 1.0),
        (0, -1, 1.0),
        (1, 1, math.sqrt(2.0)),
        (-1, 1, math.sqrt(2.0)),
        (-1, -1, math.sqrt(2.0)),
        (1, -1, math.sqrt(2.0)),
    )

    def __init__(self, config: GridPlannerConfig | None = None) -> None:
        self.config = config or GridPlannerConfig()
        self.grid = RollingOccupancyGrid(self.config)
        # Card W4. An additive, caller-supplied per-cell penalty for where
        # tracked agents are predicted to be. It is a *cost*, never a mask:
        # it can only make a cell more expensive, so it cannot open a route
        # that hard inflation closed.
        self._dynamic_cost: np.ndarray | None = None

    def set_dynamic_cost_layer(self, costs: np.ndarray | None) -> None:
        """Install this tick's dynamic-agent penalty, or clear it."""

        if costs is None:
            self._dynamic_cost = None
            return
        expected = (self.config.grid_size_cells, self.config.grid_size_cells)
        if costs.shape != expected:
            raise ValueError(f"dynamic cost layer must have shape {expected}")
        if not np.all(np.isfinite(costs)):
            raise ValueError("dynamic cost layer must be finite")
        if np.any(costs < 0.0):
            raise ValueError("dynamic cost layer must be non-negative")
        layer = np.asarray(costs, dtype=np.float32).copy()
        layer.setflags(write=False)
        self._dynamic_cost = layer

    @property
    def dynamic_cost_layer(self) -> np.ndarray | None:
        return self._dynamic_cost

    def _dynamic_penalty(self, cell: GridCell) -> float:
        layer = self._dynamic_cost
        return 0.0 if layer is None else float(layer[cell[1], cell[0]])

    def reset(self) -> None:
        self.grid.reset()
        self._dynamic_cost = None

    def update(self, pose: Pose2D, scan: LidarScan) -> MappingUpdate:
        return self.grid.update(pose, scan)

    def observe_and_plan(
        self,
        pose: Pose2D,
        scan: LidarScan,
        goal_world: WorldPoint,
    ) -> RoutePlan:
        self.update(pose, scan)
        return self.plan(pose, goal_world)

    def plan(
        self,
        pose: Pose2D,
        goal_world: WorldPoint,
        *,
        goal_tolerance_m: float | None = None,
    ) -> RoutePlan:
        """Plan to a goal region or a deterministic rolling-horizon subgoal.

        ``goal_tolerance_m`` overrides the configured goal tolerance for this
        call. Missions carry per-goal arrival radii (semantic targets are much
        tighter than mapped landmarks); planning must agree with the caller's
        arrival contract or a start cell inside a stale, wider goal region is
        misread as unreachable. The override is clamped to one grid cell.
        """

        goal = _finite_point(goal_world, "goal_world")
        if goal_tolerance_m is None:
            tolerance_m = self.config.goal_tolerance_m
        else:
            if not math.isfinite(goal_tolerance_m) or goal_tolerance_m <= 0.0:
                raise ValueError("goal_tolerance_m override must be positive and finite")
            tolerance_m = max(self.config.resolution_m, float(goal_tolerance_m))
        if not self.grid.initialized:
            raise RuntimeError("planner needs at least one LiDAR update before planning")
        if math.dist(pose.xy, goal) <= tolerance_m:
            return RoutePlan(
                status="at_goal",
                waypoints_world=(pose.xy,),
                requested_goal_world=goal,
                planning_target_world=goal,
                reaches_goal_region=True,
                expanded_nodes=0,
                path_length_m=0.0,
                unknown_cells_on_grid_path=0,
                map_generation=self.grid.generation,
                note="inside_goal_tolerance",
            )

        start = self.grid.world_to_local_cell(pose.xy)
        if start is None:  # defensive: rolling recentering should make this impossible
            raise RuntimeError("robot pose lies outside its rolling map")
        goal_is_inside = self.grid.bounds.contains(goal)
        target_world = goal if goal_is_inside else self._clip_goal_to_window(pose.xy, goal)
        tolerance = tolerance_m if goal_is_inside else self.config.partial_goal_search_m
        goal_cells = self._candidate_goal_cells(target_world, tolerance)
        if not goal_cells:
            return self._failed_plan(
                "goal_blocked",
                goal,
                target_world,
                note="no_traversable_cell_in_goal_region",
            )

        used_observed_frontier = False
        if self.config.frontier_search_mode == "observed_first":
            raw_path, expanded, selected_kind = self._observed_goal_or_frontier_path(
                start=start,
                goals=goal_cells,
                goal_world=goal,
            )
            used_observed_frontier = selected_kind in {
                "observed_frontier",
                "observed_detour_frontier",
            }
            used_window_frontier = selected_kind in {
                "window_frontier",
                "window_detour_frontier",
            }
            used_detour_frontier = selected_kind in {
                "observed_detour_frontier",
                "window_detour_frontier",
            }
        else:
            raw_path, expanded, used_window_frontier = self._astar(
                start,
                goal_cells,
                fallback_goal_world=(goal if self.config.reachable_frontier_fallback else None),
            )
            used_detour_frontier = False
        if not raw_path:
            return self._failed_plan(
                "no_path",
                goal,
                target_world,
                expanded_nodes=expanded,
                note="astar_exhausted_or_expansion_limit",
            )
        if len(raw_path) == 1 and raw_path[0] in goal_cells:
            # The start cell itself satisfies the goal region: this is arrival,
            # not an unreachable goal. Reporting it as no_path deadlocked the
            # navigator in a permanent recovery scan one cell from the target.
            return RoutePlan(
                status="at_goal",
                waypoints_world=(pose.xy,),
                requested_goal_world=goal,
                planning_target_world=target_world,
                reaches_goal_region=True,
                expanded_nodes=expanded,
                path_length_m=0.0,
                unknown_cells_on_grid_path=0,
                map_generation=self.grid.generation,
                note="start_cell_inside_goal_region",
            )

        clipped_to_observed_frontier = False
        if self.config.frontier_search_mode == "post_astar":
            raw_path, clipped_to_observed_frontier = self._clip_to_observed_frontier(raw_path)
        if clipped_to_observed_frontier:
            # The goal-directed unknown-admitting path may enter unknown space
            # on its first diagonal even when another observed route reaches a
            # useful sensor frontier. Search the whole connected known-free
            # component instead of treating that one hypothesis as binding.
            raw_path, frontier_expanded = self._observed_frontier_path(
                start=start,
                goal_world=goal,
            )
            expanded += frontier_expanded
            used_observed_frontier = True
        used_frontier = used_window_frontier or used_observed_frontier
        if len(raw_path) < 2:
            return self._failed_plan(
                "no_path",
                goal,
                target_world,
                expanded_nodes=expanded,
                note="no_observed_safe_egress_to_frontier",
            )

        # The generic collinearity pass is geometry-only and may collapse a
        # diagonal staircase across unobserved side cells. For an observed
        # frontier route, retain the cellwise path until the known-free LOS
        # smoother proves a shortcut executable.
        compressed = raw_path if used_observed_frontier else _compress_collinear(raw_path)
        smoothed = self._smooth_known_free_segments(compressed)
        route = [pose.xy]
        route.extend(self.grid.local_cell_center(cell) for cell in smoothed[1:])
        chosen_target = self.grid.local_cell_center(raw_path[-1])
        if (
            not used_frontier
            and goal_is_inside
            # Classify against the same per-call tolerance that built the goal
            # region: the caller's arrival contract, not the config default.
            and math.dist(chosen_target, goal) <= tolerance_m
        ):
            # The exact metric goal is safe when it occupies the selected cell;
            # otherwise the cell-center endpoint remains the safe goal-region pose.
            goal_local = self.grid.world_to_local_cell(goal)
            if goal_local == raw_path[-1]:
                route[-1] = goal
            reaches_goal = True
            status: RouteStatus = "planned"
        else:
            reaches_goal = False
            status = "partial"
        deduplicated = _deduplicate_points(route)
        unknown_count = sum(not bool(self.grid._observed[cell[1], cell[0]]) for cell in raw_path)
        return RoutePlan(
            status=status,
            waypoints_world=deduplicated,
            requested_goal_world=goal,
            planning_target_world=chosen_target,
            reaches_goal_region=reaches_goal,
            expanded_nodes=expanded,
            path_length_m=_polyline_length(deduplicated),
            unknown_cells_on_grid_path=unknown_count,
            map_generation=self.grid.generation,
            note=(
                "reachable_bounded_detour_frontier"
                if used_detour_frontier
                else "reachable_observed_frontier"
                if used_observed_frontier
                else "reachable_window_frontier_fallback"
                if used_window_frontier
                else "astar_cost_aware_unknowns_and_known_free_los_smoothing"
            ),
        )

    def _clip_to_observed_frontier(
        self,
        path: tuple[GridCell, ...],
    ) -> tuple[tuple[GridCell, ...], bool]:
        """Stop an opt-in route at its current known-free frontier.

        A* deliberately admits penalized unknown cells, but the closed-loop
        waypoint follower correctly refuses to drive a compressed segment that
        has not been observed. Retaining an unknown suffix therefore creates a
        rotate-only deadlock. The experimental frontier profile clips that
        suffix, drives through the longest observed hard-safe prefix, then
        replans from the next LiDAR frame. Default profiles preserve the former
        route representation exactly.
        """

        if not self.config.reachable_frontier_fallback or len(path) < 2:
            return path, False
        observed = self.grid._observed
        blocked = self.grid.inflated_occupied_mask()
        end = 1
        for index, (previous, cell) in enumerate(pairwise(path), start=1):
            if blocked[cell[1], cell[0]] or not observed[cell[1], cell[0]]:
                break
            dx = cell[0] - previous[0]
            dy = cell[1] - previous[1]
            if dx and dy:
                side_x = (previous[0] + dx, previous[1])
                side_y = (previous[0], previous[1] + dy)
                if (
                    blocked[side_x[1], side_x[0]]
                    or blocked[side_y[1], side_y[0]]
                    or not observed[side_x[1], side_x[0]]
                    or not observed[side_y[1], side_y[0]]
                ):
                    break
            end = index + 1
        if end == len(path):
            return path, False
        return path[:end], True

    def _observed_frontier_path(
        self,
        *,
        start: GridCell,
        goal_world: WorldPoint,
    ) -> tuple[tuple[GridCell, ...], int]:
        """Route through known-free cells to a goal-progressing scan frontier."""

        blocked = self.grid.inflated_occupied_mask().copy()
        blocked[start[1], start[0]] = False
        observed = self.grid._observed
        comfort_cost = self.grid.comfort_cost_mask()
        start_goal_distance = math.dist(self.grid.local_cell_center(start), goal_world)
        g_cost: dict[GridCell, float] = {start: 0.0}
        parent: dict[GridCell, GridCell] = {}
        tie_breaker = count()
        queue: list[tuple[float, int, GridCell]] = [(0.0, next(tie_breaker), start)]
        closed: set[GridCell] = set()
        frontiers: list[GridCell] = []
        expanded = 0

        while queue and expanded < self.config.max_expansions:
            queued_g, _, current = heapq.heappop(queue)
            if current in closed or queued_g > g_cost.get(current, math.inf) + 1e-12:
                continue
            closed.add(current)
            expanded += 1
            if current != start and self._is_observed_frontier(current, observed):
                goal_distance = math.dist(
                    self.grid.local_cell_center(current),
                    goal_world,
                )
                if (
                    start_goal_distance - goal_distance
                    >= self.config.frontier_min_progress_m - 1e-12
                ):
                    frontiers.append(current)

            for dx, dy, geometric_cost in self._NEIGHBORS:
                neighbor = (current[0] + dx, current[1] + dy)
                if (
                    not self._inside(neighbor)
                    or neighbor in closed
                    or blocked[neighbor[1], neighbor[0]]
                    or not observed[neighbor[1], neighbor[0]]
                ):
                    continue
                if dx and dy:
                    side_x = (current[0] + dx, current[1])
                    side_y = (current[0], current[1] + dy)
                    if (
                        blocked[side_x[1], side_x[0]]
                        or blocked[side_y[1], side_y[0]]
                        or not observed[side_x[1], side_x[0]]
                        or not observed[side_y[1], side_y[0]]
                    ):
                        continue
                tentative = queued_g + geometric_cost * (
                    1.0
                    + float(comfort_cost[neighbor[1], neighbor[0]])
                    + self._dynamic_penalty(neighbor)
                )
                if tentative + 1e-12 >= g_cost.get(neighbor, math.inf):
                    continue
                parent[neighbor] = current
                g_cost[neighbor] = tentative
                heapq.heappush(
                    queue,
                    (tentative, next(tie_breaker), neighbor),
                )

        if not frontiers:
            return (), expanded
        selected = min(
            frontiers,
            key=lambda cell: (
                math.dist(self.grid.local_cell_center(cell), goal_world),
                g_cost[cell],
                cell[1],
                cell[0],
            ),
        )
        return _reconstruct_path(parent, selected), expanded

    def _observed_goal_or_frontier_path(
        self,
        *,
        start: GridCell,
        goals: set[GridCell],
        goal_world: WorldPoint,
    ) -> tuple[
        tuple[GridCell, ...],
        int,
        Literal[
            "goal",
            "observed_frontier",
            "window_frontier",
            "observed_detour_frontier",
            "window_detour_frontier",
            "none",
        ],
    ]:
        """Resolve a v3 continuation with one observed-component search.

        The v2 experiment searches unknown-admitting A* first and then repeats
        most of the grid work to discover a route the observed-only waypoint
        follower can execute.  This opt-in search instead expands the current
        observed, hard-inflated connected component once.  The resulting
        parent and path-cost state is reused to choose, in order, a reachable
        goal cell, a goal-progressing scan frontier, or a reachable rolling-map
        edge.  It cannot cross an unknown cell or diagonal corner and consumes
        no evaluator geometry.
        """

        blocked = self.grid.inflated_occupied_mask().copy()
        blocked[start[1], start[0]] = False
        observed = self.grid._observed
        comfort_cost = self.grid.comfort_cost_mask()
        observed_goals = {cell for cell in goals if bool(observed[cell[1], cell[0]])}
        start_goal_distance = math.dist(self.grid.local_cell_center(start), goal_world)
        size = self.config.grid_size_cells
        band_cells = max(
            1,
            math.ceil(self.config.frontier_band_m / self.config.resolution_m),
        )

        g_cost: dict[GridCell, float] = {start: 0.0}
        parent: dict[GridCell, GridCell] = {}
        tie_breaker = count()
        queue: list[tuple[float, int, GridCell]] = [(0.0, next(tie_breaker), start)]
        closed: set[GridCell] = set()
        reached_goals: list[GridCell] = []
        observed_frontiers: list[GridCell] = []
        window_frontiers: list[GridCell] = []
        observed_detour_frontiers: list[GridCell] = []
        window_detour_frontiers: list[GridCell] = []
        expanded = 0

        while queue and expanded < self.config.max_expansions:
            queued_g, _, current = heapq.heappop(queue)
            if current in closed or queued_g > g_cost.get(current, math.inf) + 1e-12:
                continue
            closed.add(current)
            expanded += 1
            if current in observed_goals:
                reached_goals.append(current)
            if current != start:
                goal_distance = math.dist(
                    self.grid.local_cell_center(current),
                    goal_world,
                )
                makes_progress = (
                    start_goal_distance - goal_distance
                    >= self.config.frontier_min_progress_m - 1e-12
                )
                is_observed_frontier = self._is_observed_frontier(current, observed)
                traveled_m = queued_g * self.config.resolution_m
                bounded_detour = (
                    self.config.bounded_detour_frontier_fallback
                    and not makes_progress
                    and traveled_m >= self.config.frontier_detour_min_travel_m - 1e-12
                    and goal_distance - start_goal_distance
                    <= self.config.frontier_max_goal_regression_m + 1e-12
                )
                if is_observed_frontier:
                    if makes_progress:
                        observed_frontiers.append(current)
                    elif bounded_detour:
                        observed_detour_frontiers.append(current)
                x, y = current
                is_window_frontier = (
                    x < band_cells
                    or y < band_cells
                    or x >= size - band_cells
                    or y >= size - band_cells
                )
                if is_window_frontier:
                    if makes_progress:
                        window_frontiers.append(current)
                    elif bounded_detour:
                        window_detour_frontiers.append(current)

            for dx, dy, geometric_cost in self._NEIGHBORS:
                neighbor = (current[0] + dx, current[1] + dy)
                if (
                    not self._inside(neighbor)
                    or neighbor in closed
                    or blocked[neighbor[1], neighbor[0]]
                    or not observed[neighbor[1], neighbor[0]]
                ):
                    continue
                if dx and dy:
                    side_x = (current[0] + dx, current[1])
                    side_y = (current[0], current[1] + dy)
                    if (
                        blocked[side_x[1], side_x[0]]
                        or blocked[side_y[1], side_y[0]]
                        or not observed[side_x[1], side_x[0]]
                        or not observed[side_y[1], side_y[0]]
                    ):
                        continue
                tentative = queued_g + geometric_cost * (
                    1.0
                    + float(comfort_cost[neighbor[1], neighbor[0]])
                    + self._dynamic_penalty(neighbor)
                )
                if tentative + 1e-12 >= g_cost.get(neighbor, math.inf):
                    continue
                parent[neighbor] = current
                g_cost[neighbor] = tentative
                heapq.heappush(queue, (tentative, next(tie_breaker), neighbor))

        if reached_goals:
            selected = min(
                reached_goals,
                key=lambda cell: (g_cost[cell], cell[1], cell[0]),
            )
            return _reconstruct_path(parent, selected), expanded, "goal"
        if observed_frontiers:
            selected = min(
                observed_frontiers,
                key=lambda cell: (
                    math.dist(self.grid.local_cell_center(cell), goal_world),
                    g_cost[cell],
                    cell[1],
                    cell[0],
                ),
            )
            return _reconstruct_path(parent, selected), expanded, "observed_frontier"
        if window_frontiers:
            selected = min(
                window_frontiers,
                key=lambda cell: (
                    math.dist(self.grid.local_cell_center(cell), goal_world),
                    g_cost[cell],
                    cell[1],
                    cell[0],
                ),
            )
            return _reconstruct_path(parent, selected), expanded, "window_frontier"
        # Goal progress remains the first choice. The opt-in detour is used only
        # when that policy has no executable continuation, and it is bounded in
        # both travel and temporary goal regression. Selecting the closest-goal
        # member preserves deterministic goal bias while allowing a safe move
        # around a local minimum instead of scan-only deadlock.
        if observed_detour_frontiers:
            selected = min(
                observed_detour_frontiers,
                key=lambda cell: (
                    math.dist(self.grid.local_cell_center(cell), goal_world),
                    g_cost[cell],
                    cell[1],
                    cell[0],
                ),
            )
            return _reconstruct_path(parent, selected), expanded, "observed_detour_frontier"
        if window_detour_frontiers:
            selected = min(
                window_detour_frontiers,
                key=lambda cell: (
                    math.dist(self.grid.local_cell_center(cell), goal_world),
                    g_cost[cell],
                    cell[1],
                    cell[0],
                ),
            )
            return _reconstruct_path(parent, selected), expanded, "window_detour_frontier"
        return (), expanded, "none"

    def _is_observed_frontier(
        self,
        cell: GridCell,
        observed: np.ndarray,
    ) -> bool:
        return any(
            self._inside((cell[0] + dx, cell[1] + dy)) and not observed[cell[1] + dy, cell[0] + dx]
            for dx, dy, _ in self._NEIGHBORS
        )

    def next_waypoint(
        self,
        pose: Pose2D,
        plan: RoutePlan,
        *,
        lookahead_m: float | None = None,
    ) -> BodyWaypoint | None:
        """Select the farthest visible route vertex within a bounded lookahead.

        A later vertex is selected only when the current inflated map has clear
        line of sight.  This keeps lookahead from cutting an obstacle corner.
        The returned lateral coordinate is positive to the robot's left, which
        matches Parcel and Unitree Sport ``vy`` semantics.
        """

        if not plan.usable or plan.status == "at_goal" or len(plan.waypoints_world) < 2:
            return None
        lookahead = self.config.lookahead_m if lookahead_m is None else float(lookahead_m)
        if not math.isfinite(lookahead) or lookahead <= 0.0:
            raise ValueError("lookahead_m must be finite and positive")

        points = plan.waypoints_world
        nearest_index = min(
            range(len(points)),
            key=lambda index: (math.dist(pose.xy, points[index]), index),
        )
        first_ahead = min(nearest_index + 1, len(points) - 1)
        selected: int | None = None
        for index in range(first_ahead, len(points)):
            distance = math.dist(pose.xy, points[index])
            if index > first_ahead and distance > lookahead:
                break
            if self._world_segment_is_clear(pose.xy, points[index]) and (
                index == first_ahead
                or self._world_shortcut_preserves_comfort(
                    pose.xy,
                    points,
                    first_ahead,
                    index,
                )
            ):
                selected = index

        # A cached route may have become invalid after a new LiDAR frame.  Do
        # not return its first vertex merely because it was once traversable;
        # the caller must replan or enter a bounded recovery scan.
        if selected is None:
            return None

        target = points[selected]
        dx = target[0] - pose.x
        dy = target[1] - pose.y
        cosine = math.cos(pose.heading_rad)
        sine = math.sin(pose.heading_rad)
        forward = cosine * dx + sine * dy
        left = -sine * dx + cosine * dy
        return BodyWaypoint(
            world_xy=target,
            forward_m=forward,
            left_m=left,
            distance_m=math.hypot(dx, dy),
            heading_error_rad=_wrap_angle(math.atan2(dy, dx) - pose.heading_rad),
            route_index=selected,
            is_final=selected == len(points) - 1,
        )

    def _candidate_goal_cells(self, target_world: WorldPoint, tolerance_m: float) -> set[GridCell]:
        center = self.grid.world_to_local_cell(target_world)
        if center is None:
            return set()
        radius_cells = max(1, math.ceil(tolerance_m / self.config.resolution_m))
        center_tolerance = max(
            tolerance_m,
            self.config.resolution_m / math.sqrt(2.0) + 1e-12,
        )
        inflated = self.grid.inflated_occupied_mask()
        candidates: set[GridCell] = set()
        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):
                cell = (center[0] + dx, center[1] + dy)
                if not self._inside(cell) or inflated[cell[1], cell[0]]:
                    continue
                world = self.grid.local_cell_center(cell)
                if math.dist(world, target_world) > center_tolerance:
                    continue
                if self.config.allow_unknown or bool(self.grid._observed[cell[1], cell[0]]):
                    candidates.add(cell)
        return candidates

    def _astar(
        self,
        start: GridCell,
        goals: set[GridCell],
        *,
        fallback_goal_world: WorldPoint | None = None,
    ) -> tuple[tuple[GridCell, ...], int, bool]:
        blocked = self.grid.inflated_occupied_mask().copy()
        blocked[start[1], start[0]] = False
        goals = {cell for cell in goals if not blocked[cell[1], cell[0]]}
        if not goals:
            return (), 0, False

        observed = self.grid._observed
        comfort_cost = self.grid.comfort_cost_mask()
        g_cost: dict[GridCell, float] = {start: 0.0}
        parent: dict[GridCell, GridCell] = {}
        tie_breaker = count()
        queue: list[tuple[float, float, int, GridCell]] = [
            (self._heuristic(start, goals), 0.0, next(tie_breaker), start)
        ]
        expanded = 0
        closed: set[GridCell] = set()
        while queue and expanded < self.config.max_expansions:
            _, queued_g, _, current = heapq.heappop(queue)
            if current in closed or queued_g > g_cost.get(current, math.inf) + 1e-12:
                continue
            if current in goals:
                return _reconstruct_path(parent, current), expanded, False
            closed.add(current)
            expanded += 1
            for dx, dy, geometric_cost in self._NEIGHBORS:
                neighbor = (current[0] + dx, current[1] + dy)
                if not self._inside(neighbor) or blocked[neighbor[1], neighbor[0]]:
                    continue
                if dx and dy:
                    side_x = (current[0] + dx, current[1])
                    side_y = (current[0], current[1] + dy)
                    if blocked[side_x[1], side_x[0]] or blocked[side_y[1], side_y[0]]:
                        continue
                    if not self.config.allow_unknown and (
                        not observed[side_x[1], side_x[0]] or not observed[side_y[1], side_y[0]]
                    ):
                        continue
                is_observed = bool(observed[neighbor[1], neighbor[0]])
                if not self.config.allow_unknown and not is_observed:
                    continue
                terrain_cost = (
                    (1.0 if is_observed else self.config.unknown_cost)
                    + float(comfort_cost[neighbor[1], neighbor[0]])
                    + self._dynamic_penalty(neighbor)
                )
                tentative = g_cost[current] + geometric_cost * terrain_cost
                if tentative + 1e-12 >= g_cost.get(neighbor, math.inf):
                    continue
                parent[neighbor] = current
                g_cost[neighbor] = tentative
                priority = tentative + self._heuristic(neighbor, goals)
                heapq.heappush(
                    queue,
                    (priority, tentative, next(tie_breaker), neighbor),
                )
        if fallback_goal_world is not None:
            frontier = self._best_reachable_window_frontier(
                start=start,
                reachable=closed,
                path_costs=g_cost,
                goal_world=fallback_goal_world,
            )
            if frontier is not None:
                return _reconstruct_path(parent, frontier), expanded, True
        return (), expanded, False

    def _best_reachable_window_frontier(
        self,
        *,
        start: GridCell,
        reachable: set[GridCell],
        path_costs: Mapping[GridCell, float],
        goal_world: WorldPoint,
    ) -> GridCell | None:
        """Choose a reachable map-edge subgoal using only policy-visible state.

        A clipped rolling-window target can sit beyond a wall that joins two
        map edges even though the global goal is reachable around that wall.
        Rotating in place cannot change the connected component. This fallback
        instead chooses the reachable edge cell closest to the metric goal,
        moves there through the same hard-inflated A* graph, and lets normal
        replanning reveal the continuation. It consumes neither evaluator maps
        nor reference paths and never weakens obstacle inflation.
        """

        size = self.config.grid_size_cells
        band_cells = max(
            1,
            math.ceil(self.config.frontier_band_m / self.config.resolution_m),
        )
        start_goal_distance = math.dist(self.grid.local_cell_center(start), goal_world)

        candidates: list[GridCell] = []
        for cell in reachable:
            if cell == start:
                continue
            x, y = cell
            near_edge = (
                x < band_cells or y < band_cells or x >= size - band_cells or y >= size - band_cells
            )
            if not near_edge:
                continue
            goal_distance = math.dist(self.grid.local_cell_center(cell), goal_world)
            if start_goal_distance - goal_distance < self.config.frontier_min_progress_m - 1e-12:
                continue
            candidates.append(cell)

        if not candidates:
            return None
        return min(
            candidates,
            key=lambda cell: (
                math.dist(self.grid.local_cell_center(cell), goal_world),
                path_costs[cell],
                cell[1],
                cell[0],
            ),
        )

    @staticmethod
    def _heuristic(cell: GridCell, goals: set[GridCell]) -> float:
        return min(math.hypot(cell[0] - goal[0], cell[1] - goal[1]) for goal in goals)

    def _smooth_known_free_segments(self, path: tuple[GridCell, ...]) -> tuple[GridCell, ...]:
        if len(path) <= 2:
            return path
        observed = self.grid._observed
        blocked = self.grid.inflated_occupied_mask()
        comfort = self.grid.comfort_cost_mask()
        dynamic = self._dynamic_cost
        result = [path[0]]
        anchor = 0
        while anchor < len(path) - 1:
            selected = anchor + 1
            for candidate in range(len(path) - 1, anchor + 1, -1):
                line = tuple(_supercover_cells(path[anchor], path[candidate]))
                if not all(
                    self._inside(cell)
                    and observed[cell[1], cell[0]]
                    and not blocked[cell[1], cell[0]]
                    for cell in line
                ):
                    continue
                if self.config.comfort_cost_enabled:
                    shortcut_peak = _cells_maximum(comfort, line)
                    route_peak = max(
                        _cells_maximum(
                            comfort,
                            _supercover_cells(first, second),
                        )
                        for first, second in pairwise(path[anchor : candidate + 1])
                    )
                    if shortcut_peak > route_peak + 1e-6:
                        continue
                # Preserve dynamic-agent exposure the same way comfort is
                # preserved: a shortcut that re-enters a predicted corridor
                # must not erase an A* detour (arbitration 2026-08-04).
                if dynamic is not None:
                    shortcut_peak = _cells_maximum(dynamic, line)
                    route_peak = max(
                        _cells_maximum(
                            dynamic,
                            _supercover_cells(first, second),
                        )
                        for first, second in pairwise(path[anchor : candidate + 1])
                    )
                    if shortcut_peak > route_peak + 1e-6:
                        continue
                selected = candidate
                break
            result.append(path[selected])
            anchor = selected
        return tuple(result)

    def _world_shortcut_preserves_comfort(
        self,
        start: WorldPoint,
        route: tuple[WorldPoint, ...],
        first_ahead: int,
        candidate: int,
    ) -> bool:
        start_cell = self.grid.world_to_local_cell(start)
        route_cells = tuple(
            self.grid.world_to_local_cell(route[index])
            for index in range(first_ahead, candidate + 1)
        )
        if start_cell is None or any(cell is None for cell in route_cells):
            return False
        cells = tuple(cell for cell in route_cells if cell is not None)
        if self.config.comfort_cost_enabled:
            comfort = self.grid.comfort_cost_mask()
            shortcut_peak = _cells_maximum(
                comfort,
                _supercover_cells(start_cell, cells[-1]),
            )
            existing_peak = _cells_maximum(
                comfort,
                _supercover_cells(start_cell, cells[0]),
            )
            for first, second in pairwise(cells):
                existing_peak = max(
                    existing_peak,
                    _cells_maximum(comfort, _supercover_cells(first, second)),
                )
            if shortcut_peak > existing_peak + 1e-6:
                return False
        dynamic = self._dynamic_cost
        if dynamic is not None:
            shortcut_peak = _cells_maximum(
                dynamic,
                _supercover_cells(start_cell, cells[-1]),
            )
            existing_peak = _cells_maximum(
                dynamic,
                _supercover_cells(start_cell, cells[0]),
            )
            for first, second in pairwise(cells):
                existing_peak = max(
                    existing_peak,
                    _cells_maximum(dynamic, _supercover_cells(first, second)),
                )
            if shortcut_peak > existing_peak + 1e-6:
                return False
        return True

    def _world_segment_is_clear(self, start: WorldPoint, end: WorldPoint) -> bool:
        start_cell = self.grid.world_to_local_cell(start)
        end_cell = self.grid.world_to_local_cell(end)
        if start_cell is None or end_cell is None:
            return False
        blocked = self.grid.inflated_occupied_mask()
        observed = self.grid._observed
        return all(
            self._inside(cell)
            # Inflation is a conservative raster approximation.  The robot
            # can therefore already occupy the inflated start cell while its
            # next A* cell is safe.  A* makes exactly this one-cell carve-out;
            # mirror it here so the controller can leave the halo instead of
            # scanning forever.  Every cell after the start remains subject
            # to the strict observed-and-unblocked contract.
            and (index == 0 or not blocked[cell[1], cell[0]])
            and (index == 0 or observed[cell[1], cell[0]])
            for index, cell in enumerate(_supercover_cells(start_cell, end_cell))
        )

    def _clip_goal_to_window(self, start: WorldPoint, goal: WorldPoint) -> WorldPoint:
        bounds = self.grid.bounds
        minimum = bounds.min_world_xy
        maximum = bounds.max_world_xy
        margin = self.config.resolution_m * 1.5
        low_x, low_y = minimum[0] + margin, minimum[1] + margin
        high_x, high_y = maximum[0] - margin, maximum[1] - margin
        dx, dy = goal[0] - start[0], goal[1] - start[1]
        factors = [1.0]
        if dx > 0.0:
            factors.append((high_x - start[0]) / dx)
        elif dx < 0.0:
            factors.append((low_x - start[0]) / dx)
        if dy > 0.0:
            factors.append((high_y - start[1]) / dy)
        elif dy < 0.0:
            factors.append((low_y - start[1]) / dy)
        factor = max(0.0, min(factors))
        return (start[0] + factor * dx, start[1] + factor * dy)

    def _failed_plan(
        self,
        status: Literal["goal_blocked", "no_path"],
        goal: WorldPoint,
        target: WorldPoint,
        *,
        expanded_nodes: int = 0,
        note: str,
    ) -> RoutePlan:
        return RoutePlan(
            status=status,
            waypoints_world=(),
            requested_goal_world=goal,
            planning_target_world=target,
            reaches_goal_region=False,
            expanded_nodes=expanded_nodes,
            path_length_m=0.0,
            unknown_cells_on_grid_path=0,
            map_generation=self.grid.generation,
            note=note,
        )

    def _inside(self, cell: GridCell) -> bool:
        size = self.config.grid_size_cells
        return 0 <= cell[0] < size and 0 <= cell[1] < size


def _finite_point(point: WorldPoint, name: str) -> WorldPoint:
    if len(point) != 2:
        raise ValueError(f"{name} must contain exactly two coordinates")
    result = (float(point[0]), float(point[1]))
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{name} coordinates must be finite")
    return result


def _or_shifted(destination: np.ndarray, source: np.ndarray, *, dx: int, dy: int) -> None:
    height, width = source.shape
    source_x = slice(max(0, -dx), min(width, width - dx))
    source_y = slice(max(0, -dy), min(height, height - dy))
    destination_x = slice(max(0, dx), min(width, width + dx))
    destination_y = slice(max(0, dy), min(height, height + dy))
    destination[destination_y, destination_x] |= source[source_y, source_x]


def _maximum_shifted(
    destination: np.ndarray,
    source: np.ndarray,
    *,
    dx: int,
    dy: int,
    value: float,
) -> None:
    """Maximum-blend ``value`` where a shifted boolean source is true."""

    height, width = source.shape
    source_x = slice(max(0, -dx), min(width, width - dx))
    source_y = slice(max(0, -dy), min(height, height - dy))
    destination_x = slice(max(0, dx), min(width, width + dx))
    destination_y = slice(max(0, dy), min(height, height + dy))
    source_view = source[source_y, source_x]
    destination_view = destination[destination_y, destination_x]
    destination_view[source_view] = np.maximum(destination_view[source_view], value)


def _cells_maximum(values: np.ndarray, cells: Iterator[GridCell] | Sequence[GridCell]) -> float:
    return max((float(values[y, x]) for x, y in cells), default=0.0)


def _bresenham_cells(start: GridCell, end: GridCell) -> Iterator[GridCell]:
    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    step_x = 1 if x0 < x1 else -1
    step_y = 1 if y0 < y1 else -1
    error = dx - dy
    while True:
        yield (x0, y0)
        if x0 == x1 and y0 == y1:
            break
        twice_error = 2 * error
        if twice_error > -dy:
            error -= dy
            x0 += step_x
        if twice_error < dx:
            error += dx
            y0 += step_y


def _supercover_cells(start: GridCell, end: GridCell) -> Iterator[GridCell]:
    """Yield every cell touched by a center-to-center segment.

    At an exact grid corner both side-adjacent cells are included.  Therefore a
    visibility shortcut cannot squeeze diagonally between two inflated cells.
    """

    x, y = start
    end_x, end_y = end
    yield (x, y)
    nx = abs(end_x - x)
    ny = abs(end_y - y)
    step_x = 1 if end_x > x else -1
    step_y = 1 if end_y > y else -1
    ix = 0
    iy = 0
    while ix < nx or iy < ny:
        x_decision = (1 + 2 * ix) * ny
        y_decision = (1 + 2 * iy) * nx
        if x_decision == y_decision:
            side_x = (x + step_x, y)
            side_y = (x, y + step_y)
            yield side_x
            yield side_y
            x += step_x
            y += step_y
            ix += 1
            iy += 1
            yield (x, y)
        elif x_decision < y_decision:
            x += step_x
            ix += 1
            yield (x, y)
        else:
            y += step_y
            iy += 1
            yield (x, y)


def _compress_collinear(path: tuple[GridCell, ...]) -> tuple[GridCell, ...]:
    if len(path) <= 2:
        return path
    result = [path[0]]
    previous_direction = (
        path[1][0] - path[0][0],
        path[1][1] - path[0][1],
    )
    for index in range(1, len(path) - 1):
        direction = (
            path[index + 1][0] - path[index][0],
            path[index + 1][1] - path[index][1],
        )
        if direction != previous_direction:
            result.append(path[index])
        previous_direction = direction
    result.append(path[-1])
    return tuple(result)


def _reconstruct_path(parent: dict[GridCell, GridCell], goal: GridCell) -> tuple[GridCell, ...]:
    path = [goal]
    while path[-1] in parent:
        path.append(parent[path[-1]])
    path.reverse()
    return tuple(path)


def _deduplicate_points(points: Sequence[WorldPoint]) -> tuple[WorldPoint, ...]:
    result: list[WorldPoint] = []
    for point in points:
        if not result or math.dist(result[-1], point) > 1e-9:
            result.append(point)
    return tuple(result)


def _polyline_length(points: Sequence[WorldPoint]) -> float:
    return sum(math.dist(first, second) for first, second in pairwise(points))


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
