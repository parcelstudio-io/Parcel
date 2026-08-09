"""Closed-loop navigator backed by Parcel's sensor-built occupancy grid.

The language/semantic layer still chooses the metric goal.  This controller
only consumes pose and a calibrated planar LiDAR scan, plans a collision-aware
route, and tracks its next waypoint with bounded body velocities.  Missing or
uncalibrated scans fall back to the deterministic point-goal controller so the
feature can be deployed incrementally across simulator and Go2 sensor bridges.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .base import ODOM_FRAME, MidLevelCommand, Mission, ModelSpec, NavObservation
from .base import pose_in as _pose_in

logger = logging.getLogger(__name__)
from .dynamic_layer import (
    DynamicAgentCostConfig,
    merged_cost_mask,
    tracks_from_payload,
)
from .grid_planner import (
    GridPlannerConfig,
    LidarScan,
    Pose2D,
    RollingGridPlanner,
    RoutePlan,
)


@dataclass(slots=True)
class _SafeValleyManeuver:
    """One sensor-bounded rotate-then-advance recovery commitment."""

    heading_world_rad: float
    selected_distance_m: float
    started_xy: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class _SafeValleyChoice:
    """A policy-visible LiDAR valley that passed the swept-corridor gate."""

    bearing_rad: float
    distance_m: float
    local_clearance_m: float


class GridNavigator:
    """Incremental LiDAR mapping, A* routing, and smooth waypoint tracking.

    Translation toward a route is forward-preferred: the controller first
    aligns the body, then moves along the path.  The returned command still
    uses Parcel's full holonomic body contract, including ``vy``; this version
    deliberately emits zero lateral velocity during nominal route tracking.
    """

    #: Terminal creep floor (card seamless-pacing seam 2, 2026-08-09). Near the
    #: goal ``distance_scale`` (floor 0.15) and ``waypoint_scale`` (floor 0.25)
    #: multiply down to ~0.032 m/s at cruise 0.85, so the last ~0.5 m crawled for
    #: >15 s and step-limited missions that were already essentially arrived. The
    #: *approaching* forward request is floored at the same 0.12 m/s recovery
    #: creep the yield policy already trusts for the final metre
    #: (``DirectiveNavigator.FINAL_APPROACH_CREEP_MPS``) — one value, both paths.
    #: This is neither a gate nor a stop override: it only raises a forward
    #: request that ``apply_collision_brake``, the TTC gate and the all-ray
    #: shield still bound on the same tick, it applies only while
    #: ``goal_distance > arrival_radius`` (inside the radius the point-goal
    #: fallback owns decelerate-to-stop), and it is gated off while the body is
    #: turning hard (``curvature_scale`` small) so it never fights a sharp corner.
    TERMINAL_APPROACH_FLOOR_MPS: float = 0.12
    #: Only floor the creep when the heading is roughly on-route: below this
    #: cos^2(heading_error) the controller is effectively turning, and forcing a
    #: forward creep through a hard corner would widen the turn radius.
    _TERMINAL_FLOOR_MIN_CURVATURE: float = 0.75

    def __init__(
        self,
        spec: ModelSpec,
        *,
        arrive_radius_m: float = 1.5,
        cruise_vx: float = 0.6,
        align_enter_deg: float = 28.0,
        align_exit_deg: float = 7.0,
        max_yaw_rate: float = 0.9,
        min_align_yaw_rate: float = 0.20,
        yaw_gain: float = 1.4,
        slowdown_radius_m: float = 2.0,
        control_dt_s: float = 0.1,
        max_linear_accel: float = 0.9,
        max_yaw_accel: float = 1.8,
        grid_resolution_m: float = 0.10,
        grid_size_cells: int = 161,
        map_safety_margin_m: float = 0.10,
        map_hard_safety_margin_m: float | None = None,
        map_comfort_safety_margin_m: float | None = None,
        comfort_cost_weight: float = 0.0,
        lidar_range_cap_m: float = 12.0,
        unknown_cost: float = 2.5,
        lookahead_m: float = 0.90,
        reachable_frontier_fallback: bool = False,
        frontier_search_mode: str = "post_astar",
        frontier_band_m: float = 0.60,
        frontier_min_progress_m: float = 0.10,
        bounded_detour_frontier_fallback: bool = False,
        frontier_max_goal_regression_m: float = 1.50,
        frontier_detour_min_travel_m: float = 0.60,
        detour_commitment_reached_m: float = 0.20,
        recovery_yaw_rate: float = 0.35,
        recovery_reverse_vx: float = -0.12,
        recovery_scan_steps: int = 30,
        recovery_reverse_steps: int = 0,
        safe_valley_micro_advance: bool = False,
        safe_valley_advance_m: float = 0.40,
        safe_valley_min_advance_m: float = 0.10,
        safe_valley_advance_vx: float = 0.18,
        safe_valley_max_attempts: int = 4,
        safe_valley_timestamp_slop_s: float = 0.02,
        safe_valley_clearance_weight: float = 0.08,
        safe_valley_hysteresis_weight: float = 0.20,
        safe_valley_discretization_guard_m: float = 0.0,
        replan_interval_steps: int = 5,
        lidar_stride: int = 2,
        dynamic_agents: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> None:
        if not 0.0 < arrive_radius_m < slowdown_radius_m:
            raise ValueError("arrival radius must be positive and below slowdown radius")
        if not 0.0 < align_exit_deg < align_enter_deg < 180.0:
            raise ValueError("heading thresholds must satisfy 0 < exit < enter < 180")
        finite_positive = {
            "cruise_vx": cruise_vx,
            "max_yaw_rate": max_yaw_rate,
            "min_align_yaw_rate": min_align_yaw_rate,
            "yaw_gain": yaw_gain,
            "control_dt_s": control_dt_s,
            "max_linear_accel": max_linear_accel,
            "max_yaw_accel": max_yaw_accel,
            "recovery_yaw_rate": recovery_yaw_rate,
        }
        if any(not math.isfinite(value) or value <= 0.0 for value in finite_positive.values()):
            raise ValueError("grid navigator rates and gains must be finite and positive")
        if (
            not math.isfinite(recovery_reverse_vx)
            or recovery_reverse_vx >= 0.0
            or not 1 <= recovery_scan_steps <= 1_000
            or not 0 <= recovery_reverse_steps < recovery_scan_steps
        ):
            raise ValueError("invalid bounded recovery configuration")
        if not isinstance(safe_valley_micro_advance, bool):
            raise TypeError("safe_valley_micro_advance must be boolean")
        if not math.isfinite(safe_valley_advance_m) or not 0.30 <= safe_valley_advance_m <= 0.50:
            raise ValueError("safe_valley_advance_m must be in [0.30, 0.50]")
        if (
            not math.isfinite(safe_valley_min_advance_m)
            or not 0.05 <= safe_valley_min_advance_m <= safe_valley_advance_m
        ):
            raise ValueError("safe_valley_min_advance_m must be in [0.05, safe_valley_advance_m]")
        if (
            not math.isfinite(safe_valley_advance_vx)
            or not 0.0 < safe_valley_advance_vx <= cruise_vx
        ):
            raise ValueError("safe_valley_advance_vx must be positive and no faster than cruise_vx")
        if not 1 <= safe_valley_max_attempts <= 20:
            raise ValueError("safe_valley_max_attempts must be in [1, 20]")
        if (
            not math.isfinite(safe_valley_timestamp_slop_s)
            or not 0.0 <= safe_valley_timestamp_slop_s <= 0.20
        ):
            raise ValueError("safe_valley_timestamp_slop_s must be in [0, 0.20]")
        if (
            not math.isfinite(safe_valley_clearance_weight)
            or safe_valley_clearance_weight < 0.0
            or not math.isfinite(safe_valley_hysteresis_weight)
            or safe_valley_hysteresis_weight < 0.0
        ):
            raise ValueError("safe-valley ranking weights must be finite and non-negative")
        if (
            not math.isfinite(safe_valley_discretization_guard_m)
            or not 0.0 <= safe_valley_discretization_guard_m <= 0.20
        ):
            raise ValueError("safe_valley_discretization_guard_m must be in [0, 0.20]")
        if not 1 <= replan_interval_steps <= 100:
            raise ValueError("replan_interval_steps must be in [1, 100]")
        if not 1 <= lidar_stride <= 16:
            raise ValueError("lidar_stride must be in [1, 16]")
        if not math.isfinite(detour_commitment_reached_m) or detour_commitment_reached_m <= 0.0:
            raise ValueError("detour_commitment_reached_m must be finite and positive")

        # Imported lazily here avoids an import cycle: StubNavigator lives in
        # the package module whose factory imports this controller.
        from .models import StubNavigator

        self.spec = spec
        self.arrive_radius_m = float(arrive_radius_m)
        self.cruise_vx = float(cruise_vx)
        self.align_enter_deg = float(align_enter_deg)
        self.align_exit_deg = float(align_exit_deg)
        self.max_yaw_rate = float(max_yaw_rate)
        self.min_align_yaw_rate = float(min_align_yaw_rate)
        self.yaw_gain = float(yaw_gain)
        self.slowdown_radius_m = float(slowdown_radius_m)
        self.control_dt_s = float(control_dt_s)
        self.max_linear_accel = float(max_linear_accel)
        self.max_yaw_accel = float(max_yaw_accel)
        self.recovery_yaw_rate = float(recovery_yaw_rate)
        self.recovery_reverse_vx = float(recovery_reverse_vx)
        self.recovery_scan_steps = int(recovery_scan_steps)
        self.recovery_reverse_steps = int(recovery_reverse_steps)
        self.safe_valley_micro_advance = safe_valley_micro_advance
        self.safe_valley_advance_m = float(safe_valley_advance_m)
        self.safe_valley_min_advance_m = float(safe_valley_min_advance_m)
        self.safe_valley_advance_vx = float(safe_valley_advance_vx)
        self.safe_valley_max_attempts = int(safe_valley_max_attempts)
        self.safe_valley_timestamp_slop_s = float(safe_valley_timestamp_slop_s)
        self.safe_valley_clearance_weight = float(safe_valley_clearance_weight)
        self.safe_valley_hysteresis_weight = float(safe_valley_hysteresis_weight)
        self.safe_valley_discretization_guard_m = float(safe_valley_discretization_guard_m)
        self.replan_interval_steps = int(replan_interval_steps)
        self.lidar_stride = int(lidar_stride)
        self.detour_commitment_reached_m = float(detour_commitment_reached_m)
        self._planner = RollingGridPlanner(
            GridPlannerConfig(
                resolution_m=float(grid_resolution_m),
                grid_size_cells=int(grid_size_cells),
                safety_margin_m=float(map_safety_margin_m),
                hard_safety_margin_m=(
                    None if map_hard_safety_margin_m is None else float(map_hard_safety_margin_m)
                ),
                comfort_safety_margin_m=(
                    None
                    if map_comfort_safety_margin_m is None
                    else float(map_comfort_safety_margin_m)
                ),
                comfort_cost_weight=float(comfort_cost_weight),
                lidar_range_cap_m=float(lidar_range_cap_m),
                unknown_cost=float(unknown_cost),
                goal_tolerance_m=min(0.95, self.arrive_radius_m),
                lookahead_m=float(lookahead_m),
                reachable_frontier_fallback=reachable_frontier_fallback,
                frontier_search_mode=frontier_search_mode,
                frontier_band_m=float(frontier_band_m),
                frontier_min_progress_m=float(frontier_min_progress_m),
                bounded_detour_frontier_fallback=bounded_detour_frontier_fallback,
                frontier_max_goal_regression_m=float(frontier_max_goal_regression_m),
                frontier_detour_min_travel_m=float(frontier_detour_min_travel_m),
            )
        )
        # Card W4. Unlike the rest of this constructor's tolerant `**_`
        # signature, the dynamic-agent block is validated strictly: a typo in a
        # safety-relevant weight must not be silently ignored.
        if dynamic_agents is not None and not isinstance(dynamic_agents, Mapping):
            raise TypeError("grid_v1 dynamic_agents must be a mapping")
        self.dynamic_agents = DynamicAgentCostConfig.from_mapping(dynamic_agents or {})
        self.dynamic_cost_active = False
        self._fallback = StubNavigator(
            spec,
            arrive_radius_m=self.arrive_radius_m,
            cruise_vx=self.cruise_vx,
            align_enter_deg=self.align_enter_deg,
            align_exit_deg=self.align_exit_deg,
            max_yaw_rate=self.max_yaw_rate,
            min_align_yaw_rate=self.min_align_yaw_rate,
            yaw_gain=self.yaw_gain,
            slowdown_radius_m=self.slowdown_radius_m,
            control_dt_s=self.control_dt_s,
            max_linear_accel=self.max_linear_accel,
            max_yaw_accel=self.max_yaw_accel,
        )
        self._aligning = True
        self._last_vx = 0.0
        self._last_vyaw = 0.0
        self._recovery_step = 0
        self._recovery_direction = 1.0
        self._control_step = 0
        self._last_plan: RoutePlan | None = None
        self._committed_detour_target: tuple[float, float] | None = None
        self._safe_valley_maneuver: _SafeValleyManeuver | None = None
        self._safe_valley_previous_heading_rad: float | None = None
        self._safe_valley_attempts = 0
        self._last_sensor_timestamp_s: float | None = None
        # Loud degraded-mode telemetry: silently substituting the mapless
        # point-goal controller previously hid a broken sensor contract.
        self.scan_fallback_count = 0
        self._scan_fallback_active = False

    @property
    def last_route_status(self) -> str | None:
        """Status of the most recent global plan; ``None`` before the first.

        Exposed because ``goal_blocked``/``no_path`` is the planner's *proof*
        that the commanded goal has no traversable cell, not a slow-progress
        heuristic — and the only response this controller has is
        :meth:`_recovery_command`, which with the shipping
        ``recovery_reverse_steps=0`` is pure in-place yaw. A caller that owns
        the goal (the semantic mission) has to be able to see that proof, or an
        unroutable goal turns into an indefinite spin.
        """

        plan = self._last_plan
        return None if plan is None else str(plan.status)

    def seed_ramp(self, vx: float) -> None:
        """Raise slew state after a brief person-stop release (never a command).

        ``RampMemory.release`` is the caller's assertion that the person-stop
        gate already opened. This only lifts ``_last_vx`` for the next
        ``_slew``; every downstream brake / reactive / TTC authority still
        bounds the emitted command every tick.
        """

        value = float(vx)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("seed_ramp vx must be finite and non-negative")
        self._last_vx = min(max(self._last_vx, value), self.cruise_vx)

    def reset(self, mission: Mission) -> None:
        self._planner.reset()
        self.dynamic_cost_active = False
        self._fallback.reset(mission)
        self._aligning = True
        self._last_vx = 0.0
        self._last_vyaw = 0.0
        self._recovery_step = 0
        self._recovery_direction = 1.0
        self._control_step = 0
        self._last_plan = None
        self._committed_detour_target = None
        self._safe_valley_maneuver = None
        self._safe_valley_previous_heading_rad = None
        self._safe_valley_attempts = 0
        self._last_sensor_timestamp_s = None
        mission.status = "running"

    def act(self, observation: NavObservation, mission: Mission) -> MidLevelCommand:
        if mission.goal is None:
            mission.status = "failed"
            return MidLevelCommand(stop=True, note="grid_goal_missing")

        goal = (mission.goal.x, mission.goal.y)
        # ODOM: this is the short-horizon controller. The rolling occupancy grid
        # is built from live LiDAR and re-centred every tick, so what it needs
        # is a pose that is *continuous* -- a MAP correction jump would smear
        # obstacles across the grid. Global consistency is not its job.
        #
        # Known gap, deliberately not closed here: ``mission.goal`` is a MAP
        # quantity and there is no map->odom transform to bring it into this
        # frame. With TruthPoseProvider the two frames are identical so nothing
        # moves; once a real localizer occupies the MAP role, this call site is
        # the one that needs the transform. Recorded as the stratum-1 hand-off.
        robot = _pose_in(observation, ODOM_FRAME)
        pose = Pose2D(robot.x, robot.y, robot.yaw)
        goal_distance = math.dist(pose.xy, goal)
        arrival_radius = (
            self.arrive_radius_m
            if mission.goal.arrival_radius_m is None
            else float(mission.goal.arrival_radius_m)
        )
        if goal_distance <= arrival_radius:
            # Reuse the established terminal-heading/arrival contract.  This
            # also ensures semantic terminal verification in the pipeline sees
            # exactly the same stop transition as the previous navigator.
            return self._fallback.act(observation, mission)

        scan = self._scan_from_observation(observation)
        if scan is None:
            if self.safe_valley_micro_advance:
                # The experiment promises calibrated LiDAR-only local safety;
                # never substitute the open-loop point-goal fallback when that
                # sensor contract is missing or malformed.
                return self._safe_valley_hold("calibrated_lidar_unavailable")
            # Degraded mode must be loud: count every degraded tick, log once
            # per transition, and stamp the command note so telemetry and the
            # panel can surface that the mapped planner is NOT running.
            self.scan_fallback_count += 1
            if not self._scan_fallback_active:
                self._scan_fallback_active = True
                logger.warning(
                    "grid navigator degraded to point-goal fallback: observation "
                    "carries no calibrated lidar scan (ranges/angle_min/"
                    "angle_increment/range_max). Occupancy mapping is OFF."
                )
            command = self._fallback.act(observation, mission)
            fallback_note = "scan_missing_fallback"
            if command.note:
                fallback_note = f"{fallback_note};{command.note}"
            return replace(command, note=fallback_note)
        if self._scan_fallback_active:
            self._scan_fallback_active = False
            logger.info("grid navigator scan restored; occupancy mapping resumed")

        sensor_frame_fresh = self._sensor_frame_is_fresh(observation)
        if self.safe_valley_micro_advance and not sensor_frame_fresh:
            # Do not let a replayed scan update the rolling map at a newer or
            # mismatched odometry pose. The opt-in challenger fails closed
            # before any planner state changes; disabled v3/v4 behavior keeps
            # the exact pre-existing update path below.
            return self._safe_valley_hold("sensor_frame_stale_or_unsynchronised")

        self._planner.update(pose, scan)
        self._refresh_dynamic_costs(observation, pose)
        if self._safe_valley_maneuver is not None:
            return self._safe_valley_command(
                observation=observation,
                pose=pose,
                scan=scan,
                goal=goal,
                frame_is_fresh=sensor_frame_fresh,
            )
        if (
            self._committed_detour_target is not None
            and math.dist(pose.xy, self._committed_detour_target)
            <= self.detour_commitment_reached_m
        ):
            self._committed_detour_target = None
            self._last_plan = None
        # Dynamic costs rebuild every tick; a cached route would otherwise be
        # up to replan_interval_steps stale while pedestrians move. When the
        # layer is active, replan every tick (arbitration 2026-08-04).
        should_replan = self._last_plan is None or self.dynamic_cost_active or (
            self._committed_detour_target is None
            and self._control_step % self.replan_interval_steps == 0
        )
        self._control_step += 1
        if should_replan:
            self._last_plan = self._planner.plan(pose, goal, goal_tolerance_m=arrival_radius)
            self._remember_detour_target(self._last_plan)
        assert self._last_plan is not None
        plan = self._last_plan
        waypoint = self._planner.next_waypoint(pose, plan)
        if waypoint is None and plan.status != "at_goal" and not should_replan:
            # A fresh scan can invalidate a cached segment between scheduled
            # global replans. Replan immediately rather than tracking stale
            # geometry or waiting for the recovery timer.
            self._committed_detour_target = None
            plan = self._planner.plan(pose, goal, goal_tolerance_m=arrival_radius)
            self._last_plan = plan
            self._remember_detour_target(plan)
            waypoint = self._planner.next_waypoint(pose, plan)
        if waypoint is None:
            if plan.status == "at_goal":
                return self._fallback.act(observation, mission)
            if self.safe_valley_micro_advance:
                return self._safe_valley_command(
                    observation=observation,
                    pose=pose,
                    scan=scan,
                    goal=goal,
                    frame_is_fresh=sensor_frame_fresh,
                    plan_status=plan.status,
                )
            return self._recovery_command(plan.status)

        self._recovery_step = 0
        self._safe_valley_attempts = 0
        error_deg = math.degrees(waypoint.heading_error_rad)
        absolute_error = abs(error_deg)
        if self._aligning:
            if absolute_error <= self.align_exit_deg:
                self._aligning = False
        elif absolute_error >= self.align_enter_deg:
            self._aligning = True

        desired_yaw = max(
            -self.max_yaw_rate,
            min(self.max_yaw_rate, waypoint.heading_error_rad * self.yaw_gain),
        )
        if self._aligning and abs(desired_yaw) < self.min_align_yaw_rate:
            desired_yaw = math.copysign(self.min_align_yaw_rate, error_deg or 1.0)
        vyaw = self._slew(
            self._last_vyaw,
            desired_yaw,
            self.max_yaw_accel * self.control_dt_s,
        )
        detour = self._committed_detour_target is not None

        if self._aligning:
            vx = 0.0
            note = (
                f"{'grid_detour_align' if detour else 'grid_align'} "
                f"err={error_deg:.1f} route={len(plan.waypoints_world)} "
                f"status={plan.status}"
            )
        else:
            distance_scale = min(
                1.0,
                max(
                    0.15,
                    (goal_distance - arrival_radius) / (self.slowdown_radius_m - arrival_radius),
                ),
            )
            curvature_scale = max(0.15, math.cos(waypoint.heading_error_rad) ** 2)
            waypoint_scale = min(1.0, max(0.25, waypoint.distance_m / 0.60))
            desired_vx = self.cruise_vx * distance_scale * curvature_scale * waypoint_scale
            # Terminal creep floor: keep the final approach from crawling at
            # ~0.032 m/s once the multiplicative slowdown bottoms out, but only
            # when the body is tracking (not turning hard) — see the class
            # constant for the full safety argument. goal_distance is already
            # > arrival_radius here (the <= branch returned above).
            if curvature_scale >= self._TERMINAL_FLOOR_MIN_CURVATURE:
                desired_vx = max(desired_vx, self.TERMINAL_APPROACH_FLOOR_MPS)
            vx = self._slew(
                self._last_vx,
                desired_vx,
                self.max_linear_accel * self.control_dt_s,
            )
            note = (
                f"{'grid_detour_track' if detour else 'grid_track'} "
                f"err={error_deg:.1f} goal={goal_distance:.1f} "
                f"route={len(plan.waypoints_world)} status={plan.status}"
            )

        self._last_vx = vx
        self._last_vyaw = vyaw
        # Nominal point-to-point progress is forward preferred.  Keeping the
        # full MidLevelCommand (including vy) preserves the Unitree-compatible
        # interface for a later holonomic recovery/local planner.
        return MidLevelCommand(vx=vx, vy=0.0, vyaw=vyaw, note=note)

    def _refresh_dynamic_costs(self, observation: NavObservation, pose: Pose2D) -> None:
        """Install this tick's predicted-agent penalty on the planner.

        The layer is rebuilt every tick rather than cached: the whole point is
        that the tracks moved. Repeated A* at 10 Hz is what makes that
        affordable, which is why this stayed a cost layer instead of becoming
        an incremental D* Lite.
        """

        if not self.dynamic_agents.enabled:
            self.dynamic_cost_active = False
            self._planner.set_dynamic_cost_layer(None)
            return
        try:
            agent_tracks = tracks_from_payload(observation.extras.get("dynamic_agents") or ())
            owner_tracks = tracks_from_payload(observation.extras.get("owner_track") or ())
        except (TypeError, ValueError) as error:
            # Loud, then plan on the static map: a malformed track list must not
            # take the navigator down mid-mission.
            logger.warning("dynamic agent costs disabled this tick: %s", error)
            self.dynamic_cost_active = False
            self._planner.set_dynamic_cost_layer(None)
            return
        if not agent_tracks and not owner_tracks:
            self.dynamic_cost_active = False
            self._planner.set_dynamic_cost_layer(None)
            return

        costs = merged_cost_mask(
            config=self.dynamic_agents,
            agent_tracks=agent_tracks,
            owner_tracks=owner_tracks,
            cell_centers_xy=self._planner.grid.cell_centers_xy(),
            robot_xy=pose.xy,
        )
        size = self._planner.config.grid_size_cells
        self._planner.set_dynamic_cost_layer(costs.reshape(size, size))
        self.dynamic_cost_active = True

    def _recovery_command(self, status: str) -> MidLevelCommand:
        phase = self._recovery_step % self.recovery_scan_steps
        if phase == 0 and self._recovery_step > 0:
            self._recovery_direction *= -1.0
        self._recovery_step += 1
        self._last_vx = 0.0
        if phase < self.recovery_reverse_steps:
            self._last_vyaw = 0.0
            return MidLevelCommand(
                vx=self.recovery_reverse_vx,
                note=f"grid_recover_reverse status={status}",
            )
        target_yaw = self._recovery_direction * self.recovery_yaw_rate
        self._last_vyaw = self._slew(
            self._last_vyaw,
            target_yaw,
            self.max_yaw_accel * self.control_dt_s,
        )
        return MidLevelCommand(
            vyaw=self._last_vyaw,
            note=f"grid_recover_scan status={status}",
        )

    def _safe_valley_command(
        self,
        *,
        observation: NavObservation,
        pose: Pose2D,
        scan: LidarScan,
        goal: tuple[float, float],
        frame_is_fresh: bool,
        plan_status: str = "committed",
    ) -> MidLevelCommand:
        """Execute one fresh-sensor, observed-corridor micro-advance.

        This branch is deliberately narrower than nominal route tracking.  It
        never commands reverse or lateral motion, rotates before translating,
        revalidates the newly swept body envelope on every fresh sensor frame,
        and gives the global planner a new scan after a bounded advance.
        """

        del observation  # all admitted metadata was consumed by the freshness gate
        if not frame_is_fresh:
            return self._safe_valley_hold("sensor_frame_stale_or_unsynchronised")

        maneuver = self._safe_valley_maneuver
        selected_this_frame = False
        if maneuver is None:
            if self._safe_valley_attempts >= self.safe_valley_max_attempts:
                return self._safe_valley_hold("attempts_exhausted")
            choice = self._select_safe_valley(pose=pose, scan=scan, goal=goal)
            if choice is None:
                return self._safe_valley_hold("no_fully_observed_swept_corridor")
            maneuver = _SafeValleyManeuver(
                heading_world_rad=_wrap_angle(pose.heading_rad + choice.bearing_rad),
                selected_distance_m=choice.distance_m,
            )
            self._safe_valley_maneuver = maneuver
            self._safe_valley_previous_heading_rad = maneuver.heading_world_rad
            self._safe_valley_attempts += 1
            selected_this_frame = True

        heading_error = _wrap_angle(maneuver.heading_world_rad - pose.heading_rad)
        align_tolerance_rad = math.radians(self.align_exit_deg)
        if maneuver.started_xy is None and abs(heading_error) > align_tolerance_rad:
            desired_yaw = max(
                -self.max_yaw_rate,
                min(self.max_yaw_rate, heading_error * self.yaw_gain),
            )
            if abs(desired_yaw) < self.min_align_yaw_rate:
                desired_yaw = math.copysign(self.min_align_yaw_rate, heading_error)
            self._last_vx = 0.0
            self._last_vyaw = self._slew(
                self._last_vyaw,
                desired_yaw,
                self.max_yaw_accel * self.control_dt_s,
            )
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=self._last_vyaw,
                note=(
                    "grid_safe_valley_align "
                    f"err={math.degrees(heading_error):.1f} "
                    f"distance={maneuver.selected_distance_m:.2f} status={plan_status}"
                ),
            )

        if selected_this_frame:
            # Even an already aligned selection may not translate on its
            # selection frame. Hold zero and demand a newer scan/odometry pair
            # for the corridor revalidation below.
            self._last_vx = 0.0
            self._last_vyaw = 0.0
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=0.0,
                note=(
                    "grid_safe_valley_align "
                    f"err={math.degrees(heading_error):.1f} "
                    f"distance={maneuver.selected_distance_m:.2f} "
                    "status=await_fresh_revalidation"
                ),
            )

        if maneuver.started_xy is None:
            # Rotation can expose different geometry.  Recompute the allowed
            # distance from this newer scan and refuse to coast on the frame
            # that originally selected the valley.
            distance = self._safe_valley_distance(
                pose=pose,
                scan=scan,
                bearing_rad=heading_error,
                requested_m=maneuver.selected_distance_m,
            )
            if distance is None:
                self._safe_valley_maneuver = None
                return self._safe_valley_hold("corridor_revalidation_failed")
            maneuver.selected_distance_m = distance
            maneuver.started_xy = pose.xy

        traveled = math.dist(maneuver.started_xy, pose.xy)
        remaining = maneuver.selected_distance_m - traveled
        if remaining <= max(0.015, self.control_dt_s * self.safe_valley_advance_vx * 0.5):
            self._safe_valley_maneuver = None
            self._last_plan = None
            self._last_vx = 0.0
            self._last_vyaw = 0.0
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=0.0,
                note=(
                    "grid_safe_valley_complete "
                    f"traveled={traveled:.2f} target={maneuver.selected_distance_m:.2f}"
                ),
            )

        if abs(heading_error) > 2.0 * align_tolerance_rad:
            self._safe_valley_maneuver = None
            return self._safe_valley_hold("odometry_heading_drift")
        if (
            self._safe_valley_distance(
                pose=pose,
                scan=scan,
                bearing_rad=heading_error,
                requested_m=max(remaining, self.safe_valley_min_advance_m),
            )
            is None
        ):
            self._safe_valley_maneuver = None
            return self._safe_valley_hold("corridor_became_unknown_or_blocked")

        desired_vx = min(
            self.safe_valley_advance_vx,
            max(0.0, remaining / self.control_dt_s),
        )
        vx = self._slew(
            self._last_vx,
            desired_vx,
            self.max_linear_accel * self.control_dt_s,
        )
        self._last_vx = max(0.0, vx)
        self._last_vyaw = 0.0
        return MidLevelCommand(
            vx=self._last_vx,
            vy=0.0,
            vyaw=0.0,
            note=(
                "grid_safe_valley_advance "
                f"traveled={traveled:.2f} remaining={remaining:.2f} "
                f"target={maneuver.selected_distance_m:.2f}"
            ),
        )

    def _safe_valley_hold(self, reason: str) -> MidLevelCommand:
        """Return a physical stop without falsely terminating the mission."""

        self._last_vx = 0.0
        self._last_vyaw = 0.0
        return MidLevelCommand(
            vx=0.0,
            vy=0.0,
            vyaw=0.0,
            stop=False,
            note=f"grid_safe_valley_hold reason={reason}",
        )

    def _select_safe_valley(
        self,
        *,
        pose: Pose2D,
        scan: LidarScan,
        goal: tuple[float, float],
    ) -> _SafeValleyChoice | None:
        """Extract passable polar valleys and rank sensor-safe headings."""

        # V5 used the exact continuous footprint/margin radius.  An opt-in
        # half-cell-diagonal guard lets a later experiment account for the
        # worst center-to-corner error of rasterized occupancy cells without
        # changing the planner, production defaults, or nominal route tracker.
        envelope_m = (
            self._planner.config.inflation_radius_m + self.safe_valley_discretization_guard_m
        )
        passable: list[bool] = []
        clearances: list[float] = []
        for raw in scan.ranges_m:
            value = float(raw)
            if value == math.inf:
                clearance = scan.range_max_m
            elif not math.isfinite(value) or value < scan.range_min_m:
                clearance = 0.0
            else:
                clearance = min(value, scan.range_max_m)
            clearances.append(clearance)
            passable.append(clearance >= envelope_m + self.safe_valley_min_advance_m)

        valleys: list[tuple[int, int]] = []
        start: int | None = None
        for index, is_passable in enumerate((*passable, False)):
            if is_passable and start is None:
                start = index
            elif not is_passable and start is not None:
                valleys.append((start, index - 1))
                start = None

        goal_bearing = _wrap_angle(
            math.atan2(goal[1] - pose.y, goal[0] - pose.x) - pose.heading_rad
        )
        previous_bearing = (
            None
            if self._safe_valley_previous_heading_rad is None
            else _wrap_angle(self._safe_valley_previous_heading_rad - pose.heading_rad)
        )
        candidates: list[_SafeValleyChoice] = []
        for first, last in valleys:
            first_angle = scan.angle_min_rad + first * scan.angle_increment_rad
            last_angle = scan.angle_min_rad + last * scan.angle_increment_rad
            low, high = sorted((first_angle, last_angle))
            # The interval must observe the whole body width at the minimum
            # nominal commitment, rather than accepting one isolated clear
            # ray. The per-distance swept-corridor check below remains the
            # authoritative gate for a clearance-limited shorter advance.
            required_half_width = math.atan2(
                envelope_m,
                self.safe_valley_advance_m,
            )
            if high - low + abs(scan.angle_increment_rad) < 2.0 * required_half_width:
                continue
            margin = required_half_width
            interior_low = low + margin
            interior_high = high - margin
            if interior_low > interior_high:
                continue
            proposed = [
                0.5 * (interior_low + interior_high),
                min(max(goal_bearing, interior_low), interior_high),
            ]
            if previous_bearing is not None:
                proposed.append(min(max(previous_bearing, interior_low), interior_high))
            for bearing in proposed:
                distance = self._safe_valley_distance(
                    pose=pose,
                    scan=scan,
                    bearing_rad=bearing,
                    requested_m=self.safe_valley_advance_m,
                )
                if distance is None:
                    continue
                center_index = round((bearing - scan.angle_min_rad) / scan.angle_increment_rad)
                center_index = max(first, min(last, center_index))
                neighborhood = max(
                    1, math.ceil(required_half_width / abs(scan.angle_increment_rad))
                )
                local = clearances[
                    max(first, center_index - neighborhood) : min(
                        last + 1, center_index + neighborhood + 1
                    )
                ]
                candidates.append(
                    _SafeValleyChoice(
                        bearing_rad=bearing,
                        distance_m=distance,
                        local_clearance_m=min(local) if local else 0.0,
                    )
                )
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (
                abs(_wrap_angle(item.bearing_rad - goal_bearing))
                + (
                    0.0
                    if previous_bearing is None
                    else self.safe_valley_hysteresis_weight
                    * abs(_wrap_angle(item.bearing_rad - previous_bearing))
                )
                - self.safe_valley_clearance_weight * item.local_clearance_m,
                -item.distance_m,
                abs(item.bearing_rad),
                item.bearing_rad,
            ),
        )

    def _safe_valley_distance(
        self,
        *,
        pose: Pose2D,
        scan: LidarScan,
        bearing_rad: float,
        requested_m: float,
    ) -> float | None:
        """Return the longest fully observed, hard-safe distance at 5 cm granularity."""

        upper = min(self.safe_valley_advance_m, max(0.0, float(requested_m)))
        steps = math.floor((upper + 1e-12) / 0.05)
        for step in range(steps, 0, -1):
            distance = step * 0.05
            if distance + 1e-12 < self.safe_valley_min_advance_m:
                break
            if self._swept_corridor_is_fully_observed(
                pose=pose,
                scan=scan,
                heading_rad=pose.heading_rad + bearing_rad,
                distance_m=distance,
            ):
                return distance
        return None

    def _swept_corridor_is_fully_observed(
        self,
        *,
        pose: Pose2D,
        scan: LidarScan,
        heading_rad: float,
        distance_m: float,
    ) -> bool:
        """Certify every grid cell newly occupied by a forward body sweep."""

        if distance_m <= 0.0 or not self._planner.grid.initialized:
            return False
        grid = self._planner.grid
        radius = self._planner.config.inflation_radius_m + self.safe_valley_discretization_guard_m
        resolution = self._planner.config.resolution_m
        maximum = distance_m + radius + resolution
        cell_radius = math.ceil(maximum / resolution)
        center = grid.world_to_local_cell(pose.xy)
        if center is None:
            return False
        cosine = math.cos(heading_rad)
        sine = math.sin(heading_rad)
        checked = 0
        for dy in range(-cell_radius, cell_radius + 1):
            for dx in range(-cell_radius, cell_radius + 1):
                cell = (center[0] + dx, center[1] + dy)
                try:
                    point = grid.local_cell_center(cell)
                except ValueError:
                    return False
                delta_x = point[0] - pose.x
                delta_y = point[1] - pose.y
                forward = cosine * delta_x + sine * delta_y
                lateral = -sine * delta_x + cosine * delta_y
                in_rectangle = 0.0 <= forward <= distance_m and abs(lateral) <= radius
                in_front_cap = (
                    forward > distance_m and math.hypot(forward - distance_m, lateral) <= radius
                )
                if not (in_rectangle or in_front_cap):
                    continue
                # The current body footprint is already occupied by the robot;
                # only newly swept space needs a forward-looking observation.
                if math.hypot(delta_x, delta_y) <= radius:
                    continue
                checked += 1
                if grid.cell_state(point).value == "occupied":
                    return False
                # A dense planar scan observes a continuous angular sweep, but
                # Bresenham integration intentionally marks only ray cells and
                # can leave raster gaps close to the sensor.  Certify every
                # swept cell against both bracketing raw beams rather than
                # treating those discretisation gaps as unobserved free space.
                bearing = _wrap_angle(math.atan2(delta_y, delta_x) - pose.heading_rad)
                ray_position = (bearing - scan.angle_min_rad) / scan.angle_increment_rad
                lower = math.floor(ray_position)
                upper = math.ceil(ray_position)
                if lower < 0 or upper >= len(scan.ranges_m):
                    return False
                required_range = math.hypot(delta_x, delta_y) + resolution / math.sqrt(2.0)
                for index in {lower, upper}:
                    measured = float(scan.ranges_m[index])
                    if measured == math.inf:
                        measured = scan.range_max_m
                    if (
                        not math.isfinite(measured)
                        or measured < scan.range_min_m
                        or min(measured, scan.range_max_m) + 1e-9 < required_range
                    ):
                        return False
        return checked > 0

    def _sensor_frame_is_fresh(self, observation: NavObservation) -> bool:
        """Validate synchronized, strictly increasing policy-visible timestamps."""

        if not self.safe_valley_micro_advance:
            return True
        extras = observation.extras
        lidar_stamp = extras.get("lidar_timestamp_s")
        odometry_stamp = extras.get("odometry_timestamp_s")
        if (
            extras.get("lidar_fresh") is not True
            or extras.get("odometry_fresh") is not True
            or isinstance(lidar_stamp, bool)
            or not isinstance(lidar_stamp, (int, float))
            or isinstance(odometry_stamp, bool)
            or not isinstance(odometry_stamp, (int, float))
        ):
            return False
        lidar_value = float(lidar_stamp)
        odometry_value = float(odometry_stamp)
        if (
            not math.isfinite(lidar_value)
            or not math.isfinite(odometry_value)
            or abs(lidar_value - odometry_value) > self.safe_valley_timestamp_slop_s
        ):
            return False
        timestamp = max(lidar_value, odometry_value)
        if self._last_sensor_timestamp_s is not None and timestamp <= self._last_sensor_timestamp_s:
            return False
        self._last_sensor_timestamp_s = timestamp
        return True

    def _remember_detour_target(self, plan: RoutePlan) -> None:
        if (
            plan.note == "reachable_bounded_detour_frontier"
            and plan.planning_target_world is not None
        ):
            self._committed_detour_target = plan.planning_target_world
        else:
            self._committed_detour_target = None

    def _scan_from_observation(self, observation: NavObservation) -> LidarScan | None:
        ranges = observation.lidar
        if (
            not isinstance(ranges, Sequence)
            or isinstance(ranges, (str, bytes, bytearray))
            or not 2 <= len(ranges) <= 16_384
        ):
            return None
        extras = observation.extras
        angle_min = extras.get("lidar_angle_min_rad")
        angle_increment = extras.get("lidar_angle_increment_rad")
        range_min = extras.get("lidar_range_min_m", 0.05)
        range_max = extras.get("lidar_range_max_m")
        values = (angle_min, angle_increment, range_min, range_max)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            return None
        try:
            scan_ranges = tuple(float(value) for value in ranges[:: self.lidar_stride])
            return LidarScan(
                ranges_m=scan_ranges,
                angle_min_rad=float(angle_min),
                angle_increment_rad=float(angle_increment) * self.lidar_stride,
                range_min_m=float(range_min),
                range_max_m=float(range_max),
            )
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _slew(current: float, target: float, maximum_delta: float) -> float:
        return current + max(-maximum_delta, min(maximum_delta, target - current))

    def close(self) -> None:
        self._fallback.close()
        self._planner.reset()
        self._last_vx = 0.0
        self._last_vyaw = 0.0
        self._last_plan = None
        self._committed_detour_target = None
        self._safe_valley_maneuver = None
        self._safe_valley_previous_heading_rad = None
        self._safe_valley_attempts = 0
        self._last_sensor_timestamp_s = None


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


__all__ = ["GridNavigator"]
