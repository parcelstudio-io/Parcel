"""Deterministic owner reacquisition: last-observed → sweep → frontier search.

Card W7. Parcel's follow controller has always had one answer to losing the
owner: stand still and hope. This controller is the recovery behavior — three
bounded states, no model in the loop, and a hard give-up budget.

It produces velocity commands only. Every command still passes through the
runtime's arbiter, the reactive safety policy, and the final collision gate,
so this module can never widen the safety envelope; it can only propose motion
inside it.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from parcel_robot.backends.base import SimObservation
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.grid_planner import (
    CellState,
    GridPlannerConfig,
    LidarScan,
    Pose2D,
    RollingGridPlanner,
)
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)

logger = logging.getLogger(__name__)

SEARCH_STATES = (
    "idle",
    "go_to_last_observed",
    "sweep",
    "frontier_search",
    "reacquired",
    "gave_up",
)
TERMINAL_SEARCH_STATES = frozenset({"reacquired", "gave_up"})
_INTEGER_FIELDS = frozenset(
    {
        "frontier_bearings",
        "frontier_rings",
        "reacquire_min_frames",
        "grid_size_cells",
    }
)


@dataclass(frozen=True)
class SearchOwnerConfig:
    """Bounds for the reacquisition skill.

    ``lost_timeout_s`` belongs here rather than in the follow config because
    it is the trigger for *this* behavior: how long the follow controller may
    report a lost owner before the runtime proposes a search.
    """

    lost_timeout_s: float = 3.0
    max_search_s: float = 45.0
    arrival_radius_m: float = 0.5
    goto_timeout_s: float = 15.0
    # +/-120 deg is free on a quadruped and covers the corner the owner most
    # likely rounded without walking anywhere.
    sweep_amplitude_rad: float = 2.0943951023931953
    sweep_rate_rad_s: float = 0.6
    sweep_settle_rad: float = 0.12
    sweep_timeout_s: float = 14.0
    # Published RPF-search prune: the owner cannot be further from the loss
    # point than their maximum walking speed times the elapsed time.
    owner_max_speed_mps: float = 1.6
    max_search_radius_m: float = 12.0
    sensor_radius_m: float = 3.0
    frontier_bearings: int = 12
    frontier_rings: int = 3
    frontier_ring_step_m: float = 2.0
    frontier_travel_weight: float = 0.06
    frontier_min_gain: float = 0.05
    linear_speed_mps: float = 0.3
    distance_gain: float = 0.65
    max_yaw_rate: float = 0.7
    yaw_gain: float = 1.4
    turn_in_place_rad: float = 0.8
    owner_confidence_min: float = 0.65
    reacquire_min_frames: int = 1
    stale_after_s: float = 0.6
    grid_resolution_m: float = 0.2
    grid_size_cells: int = 161

    def __post_init__(self) -> None:
        positive = [
            getattr(self, item.name)
            for item in fields(self)
            if item.name not in _INTEGER_FIELDS
        ]
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("owner search values must be positive and finite")
        for name in _INTEGER_FIELDS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.grid_size_cells < 21 or self.grid_size_cells % 2 == 0:
            raise ValueError("grid_size_cells must be an odd integer of at least 21")
        if self.sweep_amplitude_rad > math.pi:
            raise ValueError("sweep amplitude must not exceed a half turn")
        if self.sweep_settle_rad >= self.sweep_amplitude_rad:
            raise ValueError("sweep settle tolerance must be below the amplitude")
        if not 0.0 < self.owner_confidence_min <= 1.0:
            raise ValueError("owner confidence threshold must be in (0, 1]")
        if self.goto_timeout_s >= self.max_search_s:
            raise ValueError("go-to-last-observed timeout must be below the search budget")
        if self.sweep_timeout_s >= self.max_search_s:
            raise ValueError("sweep timeout must be below the search budget")
        if self.frontier_ring_step_m * self.frontier_rings > self.max_search_radius_m + 1e-9:
            raise ValueError("frontier rings must fit inside the maximum search radius")
        if self.arrival_radius_m >= self.max_search_radius_m:
            raise ValueError("arrival radius must be below the maximum search radius")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SearchOwnerConfig:
        """Load the optional config section without silently accepting typos."""

        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown owner_search settings: {sorted(unknown)}")
        values: dict[str, float | int] = {}
        for key, value in raw.items():
            if key in _INTEGER_FIELDS:
                if isinstance(value, bool):
                    raise TypeError(f"{key} must be an integer")
                converted = int(value)
                if converted != value:
                    raise ValueError(f"{key} must be an integer")
                values[key] = converted
            else:
                values[key] = float(value)
        return cls(**values)


@dataclass(frozen=True)
class SearchDecision:
    state: str
    command: VelocityCommand
    reason: str
    done: bool = False
    outcome: str = ""
    elapsed_s: float = 0.0
    target_x_m: float | None = None
    target_y_m: float | None = None
    owner_confidence: float | None = None
    degraded: str = ""


class SearchOwnerController:
    """Three bounded states with one terminal answer each way.

    The owner reappearing in *any* state is immediate terminal success; the
    budget expiring anywhere is a clean give-up. Nothing else terminates, so
    the executive's own step timeout stays a backstop rather than the
    mechanism.
    """

    def __init__(
        self,
        config: SearchOwnerConfig | None = None,
        *,
        safety_policy: ReactiveSafetyPolicy | None = None,
    ):
        self.config = config or SearchOwnerConfig()
        self._safety_policy = safety_policy or ReactiveSafetyPolicy()
        self._enabled = False
        self._state = "idle"
        self._outcome = ""
        self._reason = "idle"
        self._started_at: float | None = None
        self._lost_at: float | None = None
        self._phase_started_at: float | None = None
        self._last_observed: tuple[float, float] = (0.0, 0.0)
        self._confident_frames = 0
        self._owner_confidence: float | None = None
        self._sweep_anchor_yaw: float | None = None
        self._sweep_offsets: tuple[float, ...] = ()
        self._sweep_index = 0
        self._frontier_target: tuple[float, float] | None = None
        self._viewpoints: list[tuple[float, float]] = []
        # Uses the same RollingGridPlanner / A* stack as grid_v1 navigation
        # (arbitration 2026-08-04): proportional steering alone was U16.
        self._planner: RollingGridPlanner | None = None
        self._active_plan_goal: tuple[float, float] | None = None
        self._degraded = ""
        self._paused = False
        self._paused_at: float | None = None
        self._frozen_elapsed_s = 0.0
        self._frozen_phase_elapsed_s = 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def state(self) -> str:
        return self._state

    @property
    def outcome(self) -> str:
        return self._outcome

    def start(
        self,
        *,
        last_x: float,
        last_y: float,
        lost_at_s: float,
        now: float,
    ) -> None:
        """Begin a search from the last confident owner position."""

        values = (last_x, last_y, lost_at_s, now)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("owner search must start from a finite pose and clock")
        if lost_at_s > now:
            raise ValueError("the owner cannot have been lost in the future")
        self._enabled = True
        self._state = "go_to_last_observed"
        self._outcome = ""
        self._reason = "search_started"
        self._started_at = now
        self._lost_at = lost_at_s
        self._phase_started_at = now
        self._last_observed = (float(last_x), float(last_y))
        self._confident_frames = 0
        self._owner_confidence = None
        self._sweep_anchor_yaw = None
        self._sweep_offsets = ()
        self._sweep_index = 0
        self._frontier_target = None
        self._viewpoints = []
        self._planner = None
        self._active_plan_goal = None
        self._degraded = ""
        self._paused = False
        self._paused_at = None
        self._frozen_elapsed_s = 0.0
        self._frozen_phase_elapsed_s = 0.0

    def stop(self) -> None:
        self._enabled = False
        self._state = "idle"
        self._reason = "search_stopped"
        self._started_at = None
        self._phase_started_at = None
        self._frontier_target = None
        self._planner = None
        self._active_plan_goal = None
        self._paused = False
        self._paused_at = None
        self._frozen_elapsed_s = 0.0
        self._frozen_phase_elapsed_s = 0.0

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self, *, now: float) -> None:
        """Freeze the wall-clock search budget (PAUSE_SEMANTICS.md)."""

        if not self._enabled or self._started_at is None or self._paused:
            return
        self._frozen_elapsed_s = max(0.0, now - self._started_at)
        phase_started = self._phase_started_at
        self._frozen_phase_elapsed_s = (
            0.0 if phase_started is None else max(0.0, now - phase_started)
        )
        self._paused_at = now
        self._paused = True
        self._reason = "search_paused"

    def resume(self, *, now: float) -> None:
        if not self._paused or self._started_at is None:
            return
        # Rewind clocks so elapsed on the next step excludes paused wall time.
        self._started_at = now - self._frozen_elapsed_s
        self._phase_started_at = now - self._frozen_phase_elapsed_s
        self._paused = False
        self._paused_at = None
        self._reason = "search_resumed"

    def step(self, observation: SimObservation | None, now: float) -> SearchDecision:
        zero = VelocityCommand()
        if not self._enabled or self._started_at is None:
            return self._decision(zero, "search_disabled")
        if self._paused:
            return self._decision(zero, "search_paused", elapsed=self._frozen_elapsed_s)
        elapsed = max(0.0, now - self._started_at)
        if observation is None:
            return self._decision(zero, "no_observation", elapsed=elapsed)
        if now - observation.timestamp > self.config.stale_after_s:
            # The same rule the compiled stop_on_stale_perception invariant
            # enforces one level up: no motion on evidence we cannot trust.
            return self._decision(zero, "stale_observation", elapsed=elapsed)
        if not _finite_pose(observation):
            return self._decision(zero, "invalid_pose", elapsed=elapsed)

        if self._reacquired(observation):
            self._enabled = False
            self._state = "reacquired"
            self._outcome = "owner_reacquired"
            self._reason = "owner_reacquired"
            return self._decision(zero, self._reason, elapsed=elapsed, done=True)

        if elapsed >= self.config.max_search_s:
            self._enabled = False
            self._state = "gave_up"
            self._outcome = "gave_up"
            self._reason = "search_budget_exhausted"
            return self._decision(zero, self._reason, elapsed=elapsed, done=True)

        self._record_viewpoint(observation)
        self._update_map(observation)

        if observation.collision:
            return self._decision(zero, "collision_contact", elapsed=elapsed)

        if self._state == "go_to_last_observed":
            return self._step_goto(observation, now, elapsed)
        if self._state == "sweep":
            return self._step_sweep(observation, now, elapsed)
        return self._step_frontier(observation, now, elapsed)

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self._enabled,
            "state": self._state,
            "reason": self._reason,
            "outcome": self._outcome,
            "paused": self._paused,
            "last_observed_x_m": self._last_observed[0],
            "last_observed_y_m": self._last_observed[1],
            "frontier_target_x_m": (
                self._frontier_target[0] if self._frontier_target is not None else None
            ),
            "frontier_target_y_m": (
                self._frontier_target[1] if self._frontier_target is not None else None
            ),
            "viewpoints": len(self._viewpoints),
            "map_available": self._planner is not None,
            "degraded": self._degraded,
            "owner_confidence": self._owner_confidence,
        }

    # --- states -------------------------------------------------------------

    def _phase_elapsed(self, now: float) -> float:
        started = self._phase_started_at
        return 0.0 if started is None else max(0.0, now - started)

    def _step_goto(
        self,
        observation: SimObservation,
        now: float,
        elapsed: float,
    ) -> SearchDecision:
        target_x, target_y = self._last_observed
        distance = math.hypot(
            target_x - observation.robot.x,
            target_y - observation.robot.y,
        )
        phase_elapsed = self._phase_elapsed(now)
        if distance <= self.config.arrival_radius_m:
            return self._enter_sweep(observation, now, elapsed, "reached_last_observed")
        if phase_elapsed >= self.config.goto_timeout_s:
            # A blocked or unreachable last-observed point must not consume the
            # whole budget; look around from wherever we got to.
            return self._enter_sweep(observation, now, elapsed, "last_observed_unreachable")
        command = self._command_toward(observation, target_x, target_y)
        safe, safety_state = apply_reactive_safety(
            command, observation, policy=self._safety_policy, now=now
        )
        reason = "approaching_last_observed"
        if safety_state == "stopped" and abs(command.vx) > 1e-6:
            reason = "approach_proximity_stop"
        elif safety_state == "slowing":
            reason = "approaching_last_observed_slowed"
        return self._decision(
            safe, reason, elapsed=elapsed, target=(target_x, target_y)
        )

    def _enter_sweep(
        self,
        observation: SimObservation,
        now: float,
        elapsed: float,
        reason: str,
    ) -> SearchDecision:
        amplitude = self.config.sweep_amplitude_rad
        self._state = "sweep"
        self._phase_started_at = now
        self._sweep_anchor_yaw = observation.robot.yaw
        self._sweep_offsets = (amplitude, -amplitude, 0.0)
        self._sweep_index = 0
        return self._decision(VelocityCommand(), reason, elapsed=elapsed)

    def _step_sweep(
        self,
        observation: SimObservation,
        now: float,
        elapsed: float,
    ) -> SearchDecision:
        phase_elapsed = self._phase_elapsed(now)
        anchor = self._sweep_anchor_yaw
        if anchor is None or self._sweep_index >= len(self._sweep_offsets):
            return self._enter_frontier(now, elapsed, "sweep_complete")
        if phase_elapsed >= self.config.sweep_timeout_s:
            return self._enter_frontier(now, elapsed, "sweep_timeout")
        target_yaw = _wrap_angle(anchor + self._sweep_offsets[self._sweep_index])
        error = _wrap_angle(target_yaw - observation.robot.yaw)
        if abs(error) <= self.config.sweep_settle_rad:
            self._sweep_index += 1
            if self._sweep_index >= len(self._sweep_offsets):
                return self._enter_frontier(now, elapsed, "sweep_complete")
            error = _wrap_angle(
                _wrap_angle(anchor + self._sweep_offsets[self._sweep_index])
                - observation.robot.yaw
            )
        vyaw = _clamp(error * self.config.yaw_gain, self.config.sweep_rate_rad_s)
        # Yaw only: an in-place sweep never translates, so the reactive brake
        # has nothing to slow and the collision gate downstream stays the
        # single authority on proximity.
        return self._decision(
            VelocityCommand(vyaw=vyaw), "sweeping_for_owner", elapsed=elapsed
        )

    def _enter_frontier(self, now: float, elapsed: float, reason: str) -> SearchDecision:
        self._state = "frontier_search"
        self._phase_started_at = now
        self._frontier_target = None
        return self._decision(VelocityCommand(), reason, elapsed=elapsed)

    def _step_frontier(
        self,
        observation: SimObservation,
        now: float,
        elapsed: float,
    ) -> SearchDecision:
        target = self._frontier_target
        if target is not None:
            reached = (
                math.hypot(
                    target[0] - observation.robot.x,
                    target[1] - observation.robot.y,
                )
                <= self.config.arrival_radius_m
            )
            if reached:
                self._viewpoints.append((observation.robot.x, observation.robot.y))
                target = None
        if target is None:
            target = self._select_frontier(observation, now)
            self._frontier_target = target
        if target is None:
            return self._decision(
                VelocityCommand(), "no_reachable_frontier", elapsed=elapsed
            )
        command = self._command_toward(observation, target[0], target[1])
        safe, safety_state = apply_reactive_safety(
            command, observation, policy=self._safety_policy, now=now
        )
        reason = "exploring_frontier"
        if safety_state == "stopped" and abs(command.vx) > 1e-6:
            # Abandon a candidate the reactive gate will not let us reach so
            # the next tick scores a different one instead of pushing.
            self._frontier_target = None
            self._active_plan_goal = None
            reason = "frontier_proximity_stop"
        elif safety_state == "slowing":
            reason = "exploring_frontier_slowed"
        return self._decision(safe, reason, elapsed=elapsed, target=target)

    # --- frontier selection -------------------------------------------------

    def _reachable_radius(self, now: float) -> float:
        """How far the owner could possibly have walked since we lost them."""

        since_loss = max(0.0, now - (self._lost_at if self._lost_at is not None else now))
        return min(
            self.config.max_search_radius_m,
            max(
                self.config.frontier_ring_step_m,
                self.config.owner_max_speed_mps * since_loss,
            ),
        )

    def _select_frontier(
        self,
        observation: SimObservation,
        now: float,
    ) -> tuple[float, float] | None:
        reach = self._reachable_radius(now)
        origin_x, origin_y = self._last_observed
        scored: list[tuple[float, int, tuple[float, float]]] = []
        index = 0
        for ring in range(1, self.config.frontier_rings + 1):
            radius = ring * self.config.frontier_ring_step_m
            if radius > reach + 1e-9:
                break
            for step in range(self.config.frontier_bearings):
                bearing = 2.0 * math.pi * step / self.config.frontier_bearings
                candidate = (
                    origin_x + math.cos(bearing) * radius,
                    origin_y + math.sin(bearing) * radius,
                )
                index += 1
                if self._already_covered(candidate):
                    continue
                if self._planner is not None and not self._planner.grid.is_traversable(
                    candidate
                ):
                    continue
                gain = self._information_gain(candidate)
                if gain < self.config.frontier_min_gain:
                    continue
                travel = math.hypot(
                    candidate[0] - observation.robot.x,
                    candidate[1] - observation.robot.y,
                )
                scored.append(
                    (gain - self.config.frontier_travel_weight * travel, index, candidate)
                )
        if not scored:
            return None
        # Deterministic: candidate order breaks every score tie.
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]

    def _already_covered(self, candidate: tuple[float, float]) -> bool:
        radius = self.config.sensor_radius_m * 0.6
        return any(
            math.hypot(candidate[0] - x, candidate[1] - y) <= radius
            for x, y in self._viewpoints
        )

    def _information_gain(self, candidate: tuple[float, float]) -> float:
        """Fraction of the candidate's sensor disk that is still unknown.

        With a map this is measured against the occupancy grid. Without one
        (no calibrated scan) every uncovered candidate scores 1.0, which
        degrades the ranking to nearest-uncovered-viewpoint — announced
        through ``degraded`` rather than silently pretended to be information.
        """

        grid = self._planner.grid if self._planner is not None else None
        if grid is None or not grid.initialized:
            return 1.0
        unknown = 0
        samples = 0
        radius = self.config.sensor_radius_m
        for ring_scale in (0.0, 0.5, 1.0):
            distance = radius * ring_scale
            bearings = 1 if ring_scale == 0.0 else 8
            for step in range(bearings):
                angle = 2.0 * math.pi * step / bearings
                point = (
                    candidate[0] + math.cos(angle) * distance,
                    candidate[1] + math.sin(angle) * distance,
                )
                samples += 1
                if grid.cell_state(point) is not CellState.FREE:
                    unknown += 1
        return unknown / samples if samples else 1.0

    # --- perception ---------------------------------------------------------

    def _reacquired(self, observation: SimObservation) -> bool:
        owner = observation.owner
        confident = (
            owner.visible
            and math.isfinite(owner.confidence)
            and owner.confidence >= self.config.owner_confidence_min
            and math.isfinite(owner.x)
            and math.isfinite(owner.y)
        )
        if not confident:
            self._confident_frames = 0
            self._owner_confidence = None
            return False
        self._confident_frames += 1
        self._owner_confidence = float(owner.confidence)
        self._last_observed = (float(owner.x), float(owner.y))
        return self._confident_frames >= self.config.reacquire_min_frames

    def _record_viewpoint(self, observation: SimObservation) -> None:
        position = (observation.robot.x, observation.robot.y)
        spacing = self.config.sensor_radius_m * 0.5
        if not self._viewpoints or all(
            math.hypot(position[0] - x, position[1] - y) > spacing
            for x, y in self._viewpoints[-4:]
        ):
            self._viewpoints.append(position)
        if len(self._viewpoints) > 256:
            del self._viewpoints[:128]

    def _update_map(self, observation: SimObservation) -> None:
        """Integrate the planar scan into the grid_v1 planner map."""

        scan = self._scan(observation)
        if scan is None:
            if self._planner is None and not self._degraded:
                self._degraded = "no_calibrated_scan: frontier gain is coverage-only"
                logger.warning(
                    "owner search has no calibrated LiDAR scan; "
                    "frontier candidates are ranked by coverage novelty only"
                )
            return
        try:
            if self._planner is None:
                self._planner = RollingGridPlanner(
                    GridPlannerConfig(
                        resolution_m=self.config.grid_resolution_m,
                        grid_size_cells=self.config.grid_size_cells,
                        # Card DOOR-1 / design DW-4: production construction site
                        # 2 of 2. This controller already holds the COMMISSIONED
                        # gate (``safety_policy`` is the runtime's own
                        # ``ReactiveSafetyPolicy``, injected at runtime.py:1809),
                        # so the ring the final gate will enforce is right here
                        # and there is no excuse for the planner to hold a second
                        # opinion about it. Never ``None``: a planner blind to the
                        # gate proposes frontier routes the gate then stands in
                        # and refuses, which reads as "the search stalled" rather
                        # than as a disagreement.
                        #
                        # ``planner_gate_ring_m``, card A2 — DOOR-1's HALTED
                        # item H-2, CLOSED under a recorded re-freeze. DOOR-1
                        # shipped ``planner_coupling_ring_m`` here, which capped
                        # the shipped 0.65 m ring back down to the ring the
                        # legacy 0.42 m inflation already covered, so this
                        # planner kept routing through corridors this very
                        # policy would then stand in and refuse. The commissioned
                        # ring now comes through whole and in the planner's own
                        # frame (centre-to-surface; the gate compares
                        # body-surface ranges), which raises the hard inflation
                        # 0.42 -> 0.8854 m on the shipped config and
                        # 0.42 -> 0.7028 m on the prototype's 0.45 m ring. That
                        # moves the follow-bench row ``evals/companion_nav/
                        # runner.py`` builds this controller for; the move is
                        # pre-registered and recorded in
                        # ``scrum/20260824/task_2/A2_STATUS.md``, not silent.
                        gate_clearance_m=self._safety_policy.planner_gate_ring_m,
                    )
                )
            self._planner.update(
                Pose2D(observation.robot.x, observation.robot.y, observation.robot.yaw),
                scan,
            )
        except (RuntimeError, TypeError, ValueError) as error:
            self._planner = None
            self._active_plan_goal = None
            self._degraded = f"map_unavailable: {error}"
            logger.warning("owner search map update failed: %s", error)
        else:
            self._degraded = ""

    @staticmethod
    def _scan(observation: SimObservation) -> LidarScan | None:
        if (
            not observation.lidar_ranges
            or observation.lidar_angle_min_rad is None
            or observation.lidar_angle_increment_rad is None
            or observation.lidar_range_max_m is None
        ):
            return None
        try:
            return LidarScan(
                ranges_m=observation.lidar_ranges,
                angle_min_rad=observation.lidar_angle_min_rad,
                angle_increment_rad=observation.lidar_angle_increment_rad,
                range_min_m=(
                    0.05
                    if observation.lidar_range_min_m is None
                    else observation.lidar_range_min_m
                ),
                range_max_m=observation.lidar_range_max_m,
            )
        except (TypeError, ValueError) as error:
            logger.warning("owner search rejected a malformed LiDAR scan: %s", error)
            return None

    # --- helpers ------------------------------------------------------------

    def _command_toward(
        self,
        observation: SimObservation,
        target_x: float,
        target_y: float,
    ) -> VelocityCommand:
        """Track a goal through the grid planner when a map is available.

        Falls back to direct proportional steering only when there is no usable
        map yet (coverage-only / no LiDAR) — the same loud degradation path.
        """

        planner = self._planner
        if planner is None or not planner.grid.initialized:
            return self._command_to(observation, target_x, target_y)
        pose = Pose2D(observation.robot.x, observation.robot.y, observation.robot.yaw)
        goal = (float(target_x), float(target_y))
        try:
            if self._active_plan_goal != goal:
                plan = planner.plan(
                    pose, goal, goal_tolerance_m=self.config.arrival_radius_m
                )
                self._active_plan_goal = goal
            else:
                plan = planner.plan(
                    pose, goal, goal_tolerance_m=self.config.arrival_radius_m
                )
            if plan.status == "at_goal":
                return VelocityCommand()
            waypoint = planner.next_waypoint(pose, plan)
            if waypoint is None:
                return self._command_to(observation, target_x, target_y)
            return self._command_to(
                observation, waypoint.world_xy[0], waypoint.world_xy[1]
            )
        except (RuntimeError, TypeError, ValueError) as error:
            logger.warning("owner search planner failed; falling back: %s", error)
            self._active_plan_goal = None
            return self._command_to(observation, target_x, target_y)

    def _command_to(
        self,
        observation: SimObservation,
        target_x: float,
        target_y: float,
    ) -> VelocityCommand:
        dx = target_x - observation.robot.x
        dy = target_y - observation.robot.y
        distance = math.hypot(dx, dy)
        yaw_error = _wrap_angle(math.atan2(dy, dx) - observation.robot.yaw)
        vyaw = _clamp(yaw_error * self.config.yaw_gain, self.config.max_yaw_rate)
        if distance <= self.config.arrival_radius_m:
            return VelocityCommand(vyaw=vyaw if abs(yaw_error) > 0.25 else 0.0)
        vx = min(self.config.linear_speed_mps, distance * self.config.distance_gain)
        if abs(yaw_error) >= self.config.turn_in_place_rad:
            vx = 0.0
        return VelocityCommand(vx=vx, vyaw=vyaw)

    def _decision(
        self,
        command: VelocityCommand,
        reason: str,
        *,
        elapsed: float = 0.0,
        done: bool = False,
        target: tuple[float, float] | None = None,
    ) -> SearchDecision:
        self._reason = reason
        return SearchDecision(
            state=self._state,
            command=command,
            reason=reason,
            done=done,
            outcome=self._outcome,
            elapsed_s=elapsed,
            target_x_m=target[0] if target is not None else None,
            target_y_m=target[1] if target is not None else None,
            owner_confidence=self._owner_confidence,
            degraded=self._degraded,
        )


def _finite_pose(observation: SimObservation) -> bool:
    return all(
        math.isfinite(value)
        for value in (
            observation.timestamp,
            observation.robot.x,
            observation.robot.y,
            observation.robot.yaw,
        )
    )


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


__all__ = [
    "SEARCH_STATES",
    "TERMINAL_SEARCH_STATES",
    "SearchDecision",
    "SearchOwnerConfig",
    "SearchOwnerController",
]
