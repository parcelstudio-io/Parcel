"""Deployment-disabled supervisory local tracker for the V9 S4 scratch lane.

The frozen GridNavigator remains the global planner and nominal tracker.  This
component returns ``None`` when that nominal command has a fully observed,
locally feasible motion envelope.  It intervenes only for missing routes or
after repeated positive-translation requests fail the local gate.

Recovery is forward-only and deterministic: select the interior of a
contiguous observed gap, rotate to a world-frame commitment, settle once, and
advance until measured odometry reaches a bounded displacement.  Route-loss
recovery keeps a bounded detour-side latch so successive commitments do not
oscillate around the direct-goal bearing, regardless of which recovery trigger
started the episode.  Every frame is revalidated.  The
unchanged raw 720-ray V8 shield remains the final action authority; this
tracker neither replaces nor weakens it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .base import MidLevelCommand
from .grid_planner import BodyWaypoint, LidarScan, Pose2D, WorldPoint

_TWO_PI = 2.0 * math.pi


@dataclass(frozen=True, slots=True)
class _ProjectedDecision:
    output_vx_mps: float
    output_vy_mps: float
    applied_scale: float


@dataclass(frozen=True, slots=True)
class _PreparedScan:
    ranges: np.ndarray
    bearings: np.ndarray
    observed: np.ndarray
    obstacle_xy: np.ndarray
    angle_min: float
    angle_increment: float


@dataclass(frozen=True, slots=True)
class _GapChoice:
    bearing_rad: float
    width_samples: int
    minimum_clearance_m: float
    detour_side: int


class SampledPredictiveTracker:
    """Supervise nominal tracking and provide bounded, stable gap recovery."""

    def __init__(
        self,
        *,
        cruise_vx: float = 0.45,
        align_enter_deg: float = 28.0,
        align_exit_deg: float = 7.0,
        max_yaw_rate: float = 0.8,
        min_align_yaw_rate: float = 0.20,
        yaw_gain: float = 1.4,
        control_dt_s: float = 0.1,
        rollout_steps: int = 18,
        sample_count: int = 48,
        sample_seed: int = 907,
        minimum_translation_mps: float = 0.03,
        gap_direction_samples: int = 48,
        gap_probe_speed_mps: float = 0.20,
        gap_probe_distance_m: float = 0.45,
        escape_translation_ticks: int = 24,
        commitment_score_bonus: float = 0.18,
        bootstrap_vx_mps: float = 0.12,
        stop_distance_m: float = 0.8,
        reaction_horizon_s: float = 0.12,
        max_linear_accel: float = 0.9,
        max_yaw_accel: float = 1.8,
        blocked_translation_ticks: int = 3,
        minimum_gap_samples: int = 3,
        escape_distance_m: float = 0.30,
        escape_max_yaw_rate: float = 0.35,
        unknown_commitment_grace_ticks: int = 2,
        yaw_settled_rps: float = 0.05,
        detour_latch_progress_m: float = 0.45,
        gap_continuity_weight: float = 0.45,
        escape_progress_m: float = 0.025,
        active_search_ticks: int = 24,
        route_guidance_lookahead_m: float = 0.75,
    ) -> None:
        del align_enter_deg, sample_count, sample_seed, commitment_score_bonus
        positive = {
            "cruise_vx": cruise_vx,
            "max_yaw_rate": max_yaw_rate,
            "min_align_yaw_rate": min_align_yaw_rate,
            "yaw_gain": yaw_gain,
            "control_dt_s": control_dt_s,
            "minimum_translation_mps": minimum_translation_mps,
            "gap_probe_speed_mps": gap_probe_speed_mps,
            "gap_probe_distance_m": gap_probe_distance_m,
            "bootstrap_vx_mps": bootstrap_vx_mps,
            "stop_distance_m": stop_distance_m,
            "reaction_horizon_s": reaction_horizon_s,
            "max_linear_accel": max_linear_accel,
            "max_yaw_accel": max_yaw_accel,
            "escape_distance_m": escape_distance_m,
            "escape_max_yaw_rate": escape_max_yaw_rate,
            "yaw_settled_rps": yaw_settled_rps,
            "detour_latch_progress_m": detour_latch_progress_m,
            "gap_continuity_weight": gap_continuity_weight,
            "escape_progress_m": escape_progress_m,
            "route_guidance_lookahead_m": route_guidance_lookahead_m,
        }
        if any(
            not math.isfinite(float(value)) or float(value) <= 0.0 for value in positive.values()
        ):
            raise ValueError("supervisory tracker rates and distances must be positive and finite")
        if not 0.0 < align_exit_deg < 180.0:
            raise ValueError("align_exit_deg must be in (0, 180)")
        if not math.isclose(control_dt_s, 0.1, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("V9 uses the frozen V8 0.1 second control period")
        if not 4 <= rollout_steps <= 30:
            raise ValueError("rollout_steps must be in [4, 30]")
        integer_bounds = {
            "gap_direction_samples": (gap_direction_samples, 16, 144),
            "escape_translation_ticks": (escape_translation_ticks, 1, 100),
            "blocked_translation_ticks": (blocked_translation_ticks, 1, 20),
            "minimum_gap_samples": (minimum_gap_samples, 2, 12),
            "unknown_commitment_grace_ticks": (unknown_commitment_grace_ticks, 0, 20),
            "active_search_ticks": (active_search_ticks, 1, 49),
        }
        for name, (value, lower, upper) in integer_bounds.items():
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise ValueError(f"{name} must be an integer in [{lower}, {upper}]")
        if minimum_gap_samples > gap_direction_samples:
            raise ValueError("minimum_gap_samples cannot exceed gap_direction_samples")
        if minimum_translation_mps >= cruise_vx:
            raise ValueError("minimum_translation_mps must be below cruise_vx")
        if escape_distance_m > gap_probe_distance_m:
            raise ValueError("escape distance must stay within the observed gap probe")
        # The legacy constructor field remains accepted for hook compatibility,
        # but the successor uses odometry distance rather than a tick budget.
        ramp = self._maximum_ramp_distance(
            ticks=escape_translation_ticks,
            target_vx=gap_probe_speed_mps,
            maximum_delta=max_linear_accel * control_dt_s,
            dt_s=control_dt_s,
        )
        if ramp + 1e-12 < gap_probe_distance_m:
            raise ValueError("escape_translation_ticks must cover the certified probe distance")

        self.cruise_vx = float(cruise_vx)
        self.align_exit_rad = math.radians(float(align_exit_deg))
        self.max_yaw_rate = float(max_yaw_rate)
        self.min_align_yaw_rate = float(min_align_yaw_rate)
        self.yaw_gain = float(yaw_gain)
        self.control_dt_s = float(control_dt_s)
        self.rollout_steps = int(rollout_steps)
        self.minimum_translation_mps = float(minimum_translation_mps)
        self.gap_probe_speed_mps = min(float(gap_probe_speed_mps), self.cruise_vx)
        self.gap_probe_distance_m = float(gap_probe_distance_m)
        self.bootstrap_vx_mps = min(float(bootstrap_vx_mps), self.cruise_vx)
        self.stop_distance_m = float(stop_distance_m)
        self.reaction_horizon_s = float(reaction_horizon_s)
        self.max_linear_delta_mps = float(max_linear_accel) * self.control_dt_s
        self.max_yaw_delta_rps = float(max_yaw_accel) * self.control_dt_s
        self.blocked_translation_ticks = int(blocked_translation_ticks)
        self.minimum_gap_samples = int(minimum_gap_samples)
        self.escape_distance_m = float(escape_distance_m)
        self.escape_max_yaw_rate = min(float(escape_max_yaw_rate), self.max_yaw_rate)
        self.unknown_commitment_grace_ticks = int(unknown_commitment_grace_ticks)
        self.yaw_settled_rps = float(yaw_settled_rps)
        self.detour_latch_progress_m = float(detour_latch_progress_m)
        self.gap_continuity_weight = float(gap_continuity_weight)
        self.escape_progress_m = float(escape_progress_m)
        self.active_search_ticks = int(active_search_ticks)
        self.route_guidance_lookahead_m = float(route_guidance_lookahead_m)
        self._collision_tolerance_m = 1e-9
        self._closing_epsilon_mps = 1e-9
        self._gap_bearings = np.linspace(
            -math.pi,
            math.pi,
            int(gap_direction_samples),
            endpoint=False,
            dtype=np.float64,
        )
        self._gap_bearings.setflags(write=False)
        self.reset()

    def reset(self) -> None:
        self._blocked_positive_ticks = 0
        self._last_vx_mps = 0.0
        self._last_yaw_rate_rps = 0.0
        self._committed_heading_world_rad: float | None = None
        self._escape_start_xy: tuple[float, float] | None = None
        self._settling = False
        self._settled = False
        self._direction_unknown_ticks = 0
        self._sweep_unknown_ticks = 0
        self._previous_gap_heading_world_rad: float | None = None
        self._detour_side: int | None = None
        self._detour_latch_goal_distance_m: float | None = None
        self._detour_originated_from_route_loss: bool | None = None
        self._commitment_start_goal_distance_m: float | None = None
        self._searching_for_gap = False
        self._search_exhausted = False
        self._search_ticks = 0
        self._search_trigger: str | None = None
        self._search_start_goal_distance_m: float | None = None
        self._search_started_route_unavailable: bool | None = None
        self._nominal_release_start_xy: tuple[float, float] | None = None

    def close(self) -> None:
        self.reset()

    def select(
        self,
        *,
        pose: Pose2D,
        scan: LidarScan,
        goal_world: WorldPoint,
        route_waypoints_world: Sequence[WorldPoint],
        nominal: MidLevelCommand,
        waypoint: BodyWaypoint | None,
        route_available: bool,
    ) -> MidLevelCommand | None:
        """Return ``None`` for admitted nominal motion or one recovery command."""

        goal_distance_m = math.dist(pose.xy, goal_world)
        if nominal.stop:
            self._clear_all_recovery_memory()
            return None

        prepared, reason = self._prepare_scan(scan)
        if prepared is None:
            self._clear_all_recovery_memory()
            return self._hold(f"scan_{reason}")

        target_heading_error = self._target_heading_error(
            pose=pose,
            goal_world=goal_world,
            route_waypoints_world=route_waypoints_world,
            waypoint=waypoint,
        )

        if (
            self._searching_for_gap
            and self._search_exhausted
            and self._search_started_route_unavailable is True
            and route_available
            and waypoint is not None
        ):
            self._clear_gap_search()
        if self._searching_for_gap:
            self._nominal_release_start_xy = None
            return self._continue_gap_search(
                pose=pose,
                scan=prepared,
                target_heading_error=target_heading_error,
                route_unavailable=not route_available,
                goal_distance_m=goal_distance_m,
            )

        if self._committed_heading_world_rad is not None:
            self._nominal_release_start_xy = None
            return self._continue_escape(
                pose=pose,
                scan=prepared,
                goal_world=goal_world,
                target_heading_error=target_heading_error,
                route_unavailable=not route_available,
            )
        if waypoint is None or not route_available:
            self._nominal_release_start_xy = None
            self._blocked_positive_ticks = 0
            self._last_vx_mps = 0.0
            return self._start_escape(
                pose=pose,
                scan=prepared,
                target_heading_error=target_heading_error,
                trigger="route_unavailable",
                route_unavailable=True,
                goal_distance_m=goal_distance_m,
            )

        nominal_vx = float(nominal.vx)
        nominal_vy = float(nominal.vy)
        nominal_yaw = max(
            -self.max_yaw_rate,
            min(self.max_yaw_rate, float(nominal.vyaw)),
        )
        if nominal_vx < 0.0 or abs(nominal_vy) > 1e-12:
            self._nominal_release_start_xy = None
            self._blocked_positive_ticks = 0
            return self._braking_hold("nominal_outside_forward_only_contract")
        if nominal_vx < self.minimum_translation_mps:
            # GridNavigator already owns route alignment and settling.  A
            # deliberate zero nominal is not a failed translation request.
            self._blocked_positive_ticks = 0
            self._nominal_release_start_xy = None
            self._last_vx_mps = nominal_vx
            self._last_yaw_rate_rps = nominal_yaw
            return None

        admitted, decision = self._nominal_is_admitted(
            nominal_vx,
            nominal_yaw,
            prepared,
        )
        if admitted:
            self._blocked_positive_ticks = 0
            self._last_vx_mps = decision.output_vx_mps
            self._last_yaw_rate_rps = nominal_yaw
            self._record_admitted_nominal_progress(pose)
            return None

        self._nominal_release_start_xy = None
        self._blocked_positive_ticks += 1
        if self._blocked_positive_ticks < self.blocked_translation_ticks:
            return self._braking_hold(
                "nominal_translation_gate_failed",
                extra=f"blocked_ticks={self._blocked_positive_ticks}",
            )
        self._blocked_positive_ticks = 0
        return self._start_escape(
            pose=pose,
            scan=prepared,
            target_heading_error=target_heading_error,
            trigger="repeated_nominal_block",
            route_unavailable=False,
            goal_distance_m=goal_distance_m,
        )

    def _target_heading_error(
        self,
        *,
        pose: Pose2D,
        goal_world: WorldPoint,
        route_waypoints_world: Sequence[WorldPoint],
        waypoint: BodyWaypoint | None,
    ) -> float:
        if waypoint is not None:
            value = float(waypoint.heading_error_rad)
        else:
            route_target = self._route_guidance_target(
                pose=pose,
                route_waypoints_world=route_waypoints_world,
            )
            target = goal_world if route_target is None else route_target
            value = math.atan2(target[1] - pose.y, target[0] - pose.x) - pose.heading_rad
        return _wrap_angle(value)

    def _route_guidance_target(
        self,
        *,
        pose: Pose2D,
        route_waypoints_world: Sequence[WorldPoint],
    ) -> WorldPoint | None:
        valid: list[WorldPoint] = []
        for point in route_waypoints_world:
            try:
                x, y = float(point[0]), float(point[1])
            except (IndexError, TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                valid.append((x, y))
        if not valid:
            return None
        nearest_index = min(
            range(len(valid)),
            key=lambda index: (math.dist(pose.xy, valid[index]), index),
        )
        ahead_index = min(nearest_index + 1, len(valid) - 1)
        for point in valid[ahead_index:]:
            if math.dist(pose.xy, point) + 1e-12 >= self.route_guidance_lookahead_m:
                return point
        return valid[-1]

    def _nominal_is_admitted(
        self,
        vx_mps: float,
        yaw_rate_rps: float,
        scan: _PreparedScan,
    ) -> tuple[bool, _ProjectedDecision]:
        sweep_end = yaw_rate_rps * self.reaction_horizon_s
        observed = self._sweep_is_observed(0.0, sweep_end, scan)
        decision = self._projected_cap(vx_mps, 0.0, yaw_rate_rps, scan)
        return (
            observed and decision.output_vx_mps >= self.minimum_translation_mps,
            decision,
        )

    def _start_escape(
        self,
        *,
        pose: Pose2D,
        scan: _PreparedScan,
        target_heading_error: float,
        trigger: str,
        route_unavailable: bool,
        goal_distance_m: float,
    ) -> MidLevelCommand:
        choice = self._select_gap_direction(
            target_heading_error_rad=target_heading_error,
            pose=pose,
            scan=scan,
        )
        if choice is None:
            self._clear_commitment(keep_previous=True)
            return self._start_gap_search(
                target_heading_error=target_heading_error,
                trigger=trigger,
                route_unavailable=route_unavailable,
                goal_distance_m=goal_distance_m,
            )
        return self._commit_gap_choice(
            pose=pose,
            scan=scan,
            choice=choice,
            trigger=trigger,
            route_unavailable=route_unavailable,
            goal_distance_m=goal_distance_m,
        )

    def _commit_gap_choice(
        self,
        *,
        pose: Pose2D,
        scan: _PreparedScan,
        choice: _GapChoice,
        trigger: str,
        route_unavailable: bool,
        goal_distance_m: float,
    ) -> MidLevelCommand:
        self._clear_gap_search()
        if self._detour_side is None:
            self._detour_side = choice.detour_side
            self._detour_latch_goal_distance_m = float(goal_distance_m)
            self._detour_originated_from_route_loss = bool(route_unavailable)
        elif choice.detour_side != self._detour_side:
            self._detour_side = choice.detour_side
            self._detour_latch_goal_distance_m = float(goal_distance_m)
        if self._detour_originated_from_route_loss is None:
            self._detour_originated_from_route_loss = bool(route_unavailable)
        heading_world = _wrap_angle(pose.heading_rad + choice.bearing_rad)
        self._committed_heading_world_rad = heading_world
        self._previous_gap_heading_world_rad = heading_world
        self._commitment_start_goal_distance_m = float(goal_distance_m)
        self._escape_start_xy = None
        self._settling = True
        self._settled = False
        self._direction_unknown_ticks = 0
        self._sweep_unknown_ticks = 0
        return self._rotate_toward_commitment(
            pose=pose,
            scan=scan,
            choice=choice,
            trigger=trigger,
        )

    def _continue_escape(
        self,
        *,
        pose: Pose2D,
        scan: _PreparedScan,
        goal_world: WorldPoint,
        target_heading_error: float,
        route_unavailable: bool,
    ) -> MidLevelCommand | None:
        assert self._committed_heading_world_rad is not None
        heading_error = _wrap_angle(self._committed_heading_world_rad - pose.heading_rad)
        state, clearance = self._direction_state(heading_error, scan)
        if state == "unknown":
            self._direction_unknown_ticks += 1
            if self._direction_unknown_ticks <= self.unknown_commitment_grace_ticks:
                return self._braking_hold(
                    "committed_gap_temporarily_unobserved",
                    extra=f"direction_unknown_ticks={self._direction_unknown_ticks}",
                )
            return self._reselect_after_escape(
                pose=pose,
                scan=scan,
                target_heading_error=target_heading_error,
                trigger="commitment_observation_expired",
                route_unavailable=route_unavailable,
                goal_distance_m=math.dist(pose.xy, goal_world),
            )
        self._direction_unknown_ticks = 0
        if state == "blocked":
            return self._reselect_after_escape(
                pose=pose,
                scan=scan,
                target_heading_error=target_heading_error,
                trigger="committed_gap_obstructed",
                route_unavailable=route_unavailable,
                goal_distance_m=math.dist(pose.xy, goal_world),
            )

        if not self._settled:
            residual_sweep_observed = self._settle_sweep_is_observed(
                heading_error,
                scan,
            )
            if abs(heading_error) > self.align_exit_rad or not residual_sweep_observed:
                return self._rotate_toward_commitment(
                    pose=pose,
                    scan=scan,
                    choice=_GapChoice(heading_error, 0, clearance, 0),
                    trigger=(
                        "commitment_reused"
                        if residual_sweep_observed
                        else "final_sweep_unobserved"
                    ),
                )
            self._settling = True
            next_yaw = self._slew(self._last_yaw_rate_rps, 0.0, self.max_yaw_delta_rps)
            self._last_vx_mps = 0.0
            if abs(next_yaw) <= self.yaw_settled_rps:
                self._settled = True
                self._settling = False
            self._last_yaw_rate_rps = next_yaw
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=next_yaw,
                stop=False,
                note=(
                    "v9s4_escape_settle "
                    f"err_deg={math.degrees(heading_error):.1f} "
                    f"clearance={clearance:.3f} settled={str(self._settled).lower()}"
                ),
            )

        if self._escape_start_xy is None:
            self._escape_start_xy = pose.xy
        displacement = math.dist(self._escape_start_xy, pose.xy)
        if displacement + 1e-12 >= self.escape_distance_m:
            current_goal_distance_m = math.dist(pose.xy, goal_world)
            productive = self._escape_made_goal_progress(current_goal_distance_m)
            self._clear_commitment(keep_previous=productive)
            self._blocked_positive_ticks = 0
            if productive:
                return None
            self._flip_detour_side(
                target_heading_error=target_heading_error,
                goal_distance_m=current_goal_distance_m,
                route_unavailable=route_unavailable,
            )
            return self._start_escape(
                pose=pose,
                scan=scan,
                target_heading_error=target_heading_error,
                trigger="escape_completed_without_goal_progress",
                route_unavailable=route_unavailable,
                goal_distance_m=current_goal_distance_m,
            )

        desired_yaw = self._escape_yaw_target(heading_error)
        yaw = self._slew(self._last_yaw_rate_rps, desired_yaw, self.max_yaw_delta_rps)
        desired_vx = min(self.gap_probe_speed_mps, self.cruise_vx)
        vx = self._slew(self._last_vx_mps, desired_vx, self.max_linear_delta_mps)
        if not self._sweep_is_observed(0.0, yaw * self.reaction_horizon_s, scan):
            self._sweep_unknown_ticks += 1
            if self._sweep_unknown_ticks <= self.unknown_commitment_grace_ticks:
                return self._braking_hold(
                    "escape_forward_sweep_unobserved",
                    extra=f"sweep_unknown_ticks={self._sweep_unknown_ticks}",
                )
            return self._reselect_after_escape(
                pose=pose,
                scan=scan,
                target_heading_error=target_heading_error,
                trigger="escape_sweep_observation_expired",
                route_unavailable=route_unavailable,
                goal_distance_m=math.dist(pose.xy, goal_world),
            )
        self._sweep_unknown_ticks = 0
        decision = self._projected_cap(max(0.0, vx), 0.0, yaw, scan)
        if decision.output_vx_mps < self.minimum_translation_mps or not self._rollout_is_safe(
            decision.output_vx_mps, yaw, scan.obstacle_xy
        ):
            return self._reselect_after_escape(
                pose=pose,
                scan=scan,
                target_heading_error=target_heading_error,
                trigger="escape_translation_became_obstructed",
                route_unavailable=route_unavailable,
                goal_distance_m=math.dist(pose.xy, goal_world),
            )
        self._last_vx_mps = decision.output_vx_mps
        self._last_yaw_rate_rps = yaw
        return MidLevelCommand(
            vx=decision.output_vx_mps,
            vy=0.0,
            vyaw=yaw,
            stop=False,
            note=(
                "v9s4_escape_advance "
                f"traveled={displacement:.3f} target={self.escape_distance_m:.3f} "
                f"err_deg={math.degrees(heading_error):.1f} clearance={clearance:.3f}"
            ),
        )

    def _start_gap_search(
        self,
        *,
        target_heading_error: float,
        trigger: str,
        route_unavailable: bool,
        goal_distance_m: float,
    ) -> MidLevelCommand:
        if self._detour_side is None:
            self._detour_side = 1 if target_heading_error >= 0.0 else -1
            self._detour_latch_goal_distance_m = float(goal_distance_m)
            self._detour_originated_from_route_loss = bool(route_unavailable)
        self._searching_for_gap = True
        self._search_exhausted = False
        self._search_ticks = 0
        self._search_trigger = str(trigger)
        self._search_start_goal_distance_m = float(goal_distance_m)
        self._search_started_route_unavailable = bool(route_unavailable)
        return self._gap_search_command()

    def _continue_gap_search(
        self,
        *,
        pose: Pose2D,
        scan: _PreparedScan,
        target_heading_error: float,
        route_unavailable: bool,
        goal_distance_m: float,
    ) -> MidLevelCommand:
        # Exhaustion disables further exploratory yaw and side flips, but a
        # dynamic scene may passively reveal a newly certified strict-side gap.
        # Accepting that gap is a perception wake-up, not a search restart.
        choice = self._select_gap_direction(
            target_heading_error_rad=target_heading_error,
            pose=pose,
            scan=scan,
        )
        if choice is not None:
            original_trigger = self._search_trigger or "unknown"
            return self._commit_gap_choice(
                pose=pose,
                scan=scan,
                choice=choice,
                trigger=f"active_perception_after_{original_trigger}",
                route_unavailable=route_unavailable,
                goal_distance_m=goal_distance_m,
            )
        if self._search_exhausted:
            return self._braking_hold(
                "active_gap_search_exhausted",
                extra=f"trigger={self._search_trigger or 'unknown'}",
            )
        if self._search_ticks < self.active_search_ticks:
            return self._gap_search_command()

        search_start = self._search_start_goal_distance_m
        productive = (
            search_start is not None
            and search_start - goal_distance_m + 1e-12 >= self.escape_progress_m
        )
        exhausted_trigger = self._search_trigger or "unknown"
        if not productive:
            self._flip_detour_side(
                target_heading_error=target_heading_error,
                goal_distance_m=goal_distance_m,
                route_unavailable=route_unavailable,
            )
        self._search_exhausted = True
        next_yaw = self._slew(self._last_yaw_rate_rps, 0.0, self.max_yaw_delta_rps)
        self._last_vx_mps = 0.0
        self._last_yaw_rate_rps = next_yaw
        return MidLevelCommand(
            vx=0.0,
            vy=0.0,
            vyaw=next_yaw,
            stop=False,
            note=(
                "v9s4_active_gap_search_exhausted "
                f"trigger={exhausted_trigger} productive={str(productive).lower()}"
            ),
        )

    def _gap_search_command(self) -> MidLevelCommand:
        side = 1 if self._detour_side is None else self._detour_side
        desired_yaw = float(side) * self.escape_max_yaw_rate
        yaw = self._slew(self._last_yaw_rate_rps, desired_yaw, self.max_yaw_delta_rps)
        self._search_ticks += 1
        self._last_vx_mps = 0.0
        self._last_yaw_rate_rps = yaw
        return MidLevelCommand(
            vx=0.0,
            vy=0.0,
            vyaw=yaw,
            stop=False,
            note=(
                "v9s4_active_gap_search "
                f"tick={self._search_ticks}/{self.active_search_ticks} side={side} "
                f"trigger={self._search_trigger or 'unknown'}"
            ),
        )

    def _reselect_after_escape(
        self,
        *,
        pose: Pose2D,
        scan: _PreparedScan,
        target_heading_error: float,
        trigger: str,
        route_unavailable: bool,
        goal_distance_m: float,
    ) -> MidLevelCommand:
        productive = self._escape_made_goal_progress(goal_distance_m)
        self._clear_commitment(keep_previous=productive)
        self._last_vx_mps = 0.0
        if not productive:
            self._flip_detour_side(
                target_heading_error=target_heading_error,
                goal_distance_m=goal_distance_m,
                route_unavailable=route_unavailable,
            )
        return self._start_escape(
            pose=pose,
            scan=scan,
            target_heading_error=target_heading_error,
            trigger=f"{trigger}_productive_{str(productive).lower()}",
            route_unavailable=route_unavailable,
            goal_distance_m=goal_distance_m,
        )

    def _escape_made_goal_progress(self, goal_distance_m: float) -> bool:
        start = self._commitment_start_goal_distance_m
        return (
            start is not None
            and start - float(goal_distance_m) + 1e-12 >= self.escape_progress_m
        )

    def _flip_detour_side(
        self,
        *,
        target_heading_error: float,
        goal_distance_m: float,
        route_unavailable: bool,
    ) -> None:
        if self._detour_side is None:
            initial = 1 if target_heading_error >= 0.0 else -1
            self._detour_side = -initial
        else:
            self._detour_side = -self._detour_side
        self._detour_latch_goal_distance_m = float(goal_distance_m)
        if self._detour_originated_from_route_loss is None:
            self._detour_originated_from_route_loss = bool(route_unavailable)
        self._previous_gap_heading_world_rad = None

    def _record_admitted_nominal_progress(self, pose: Pose2D) -> None:
        if self._detour_side is None:
            self._nominal_release_start_xy = None
            return
        if self._nominal_release_start_xy is None:
            self._nominal_release_start_xy = pose.xy
            return
        if (
            math.dist(self._nominal_release_start_xy, pose.xy) + 1e-12
            >= self.detour_latch_progress_m
        ):
            self._clear_detour_latch()

    def _rotate_toward_commitment(
        self,
        *,
        pose: Pose2D,
        scan: _PreparedScan,
        choice: _GapChoice,
        trigger: str,
    ) -> MidLevelCommand:
        assert self._committed_heading_world_rad is not None
        heading_error = _wrap_angle(self._committed_heading_world_rad - pose.heading_rad)
        residual_sweep_observed = self._settle_sweep_is_observed(heading_error, scan)
        desired = self._alignment_yaw_target(heading_error)
        if abs(heading_error) <= self.align_exit_rad and residual_sweep_observed:
            desired = 0.0
        yaw = self._slew(self._last_yaw_rate_rps, desired, self.max_yaw_delta_rps)
        self._last_vx_mps = 0.0
        self._last_yaw_rate_rps = yaw
        self._settling = True
        return MidLevelCommand(
            vx=0.0,
            vy=0.0,
            vyaw=yaw,
            stop=False,
            note=(
                "v9s4_escape_rotate "
                f"err_deg={math.degrees(heading_error):.1f} trigger={trigger} "
                f"gap_width={choice.width_samples} clearance={choice.minimum_clearance_m:.3f}"
            ),
        )

    def _prepare_scan(self, scan: LidarScan) -> tuple[_PreparedScan | None, str]:
        try:
            ranges = np.asarray(tuple(float(value) for value in scan.ranges_m), dtype=np.float64)
            angle_min = float(scan.angle_min_rad)
            angle_increment = float(scan.angle_increment_rad)
        except (AttributeError, TypeError, ValueError):
            return None, "contract_invalid"
        if (
            ranges.size < 16
            or not math.isfinite(angle_min)
            or not math.isfinite(angle_increment)
            or angle_increment <= 0.0
        ):
            return None, "contract_invalid"
        coverage = (ranges.size - 1) * angle_increment
        tolerance = max(1e-5, 1.5 * angle_increment)
        if not math.isclose(coverage, _TWO_PI, rel_tol=0.0, abs_tol=tolerance):
            return None, "contract_invalid"
        invalid = np.isneginf(ranges) | (np.isfinite(ranges) & (ranges < 0.0))
        if bool(np.any(invalid)):
            return None, "contract_invalid"
        observed = np.isfinite(ranges) | np.isposinf(ranges)
        if not bool(np.any(observed)):
            return None, "unavailable"
        bearings = angle_min + np.arange(ranges.size, dtype=np.float64) * angle_increment
        finite = np.isfinite(ranges)
        obstacle_xy = np.column_stack(
            (ranges[finite] * np.cos(bearings[finite]), ranges[finite] * np.sin(bearings[finite]))
        )
        return (
            _PreparedScan(
                ranges=ranges,
                bearings=bearings,
                observed=observed,
                obstacle_xy=obstacle_xy,
                angle_min=angle_min,
                angle_increment=angle_increment,
            ),
            "ok",
        )

    def _projected_cap(
        self,
        vx_mps: float,
        vy_mps: float,
        yaw_rate_rps: float,
        scan: _PreparedScan,
    ) -> _ProjectedDecision:
        speed = math.hypot(vx_mps, vy_mps)
        if speed <= self._closing_epsilon_mps:
            return _ProjectedDecision(float(vx_mps), float(vy_mps), 1.0)
        finite_indices = np.flatnonzero(np.isfinite(scan.ranges))
        if finite_indices.size == 0:
            return _ProjectedDecision(float(vx_mps), float(vy_mps), 1.0)
        bearings = scan.bearings[finite_indices]
        start_heading = math.atan2(vy_mps, vx_mps)
        end_heading = start_heading + yaw_rate_rps * self.reaction_horizon_s
        lower = min(start_heading, end_heading)
        upper = max(start_heading, end_heading)
        first_alignment = bearings + np.ceil((lower - bearings) / _TWO_PI) * _TWO_PI
        aligned = first_alignment <= upper + 1e-15
        maximum_cosine = np.maximum.reduce(
            (
                np.cos(start_heading - bearings),
                np.cos(end_heading - bearings),
                np.zeros_like(bearings),
            )
        )
        maximum_cosine = np.where(aligned, 1.0, maximum_cosine)
        closing_speed = speed * maximum_cosine
        closing = closing_speed > self._closing_epsilon_mps
        if not bool(np.any(closing)):
            return _ProjectedDecision(float(vx_mps), float(vy_mps), 1.0)
        available = np.maximum(0.0, scan.ranges[finite_indices] - self.stop_distance_m)
        scale_by_ray = np.ones_like(closing_speed)
        scale_by_ray[closing] = np.minimum(
            1.0,
            available[closing] / (self.reaction_horizon_s * closing_speed[closing]),
        )
        scale = float(np.min(scale_by_ray))
        if scale <= 0.0:
            return _ProjectedDecision(0.0, 0.0, 0.0)
        return _ProjectedDecision(float(vx_mps) * scale, float(vy_mps) * scale, scale)

    def _bearing_is_observed(self, bearing_rad: float, scan: _PreparedScan) -> bool:
        differences = _wrap_angle_array(scan.bearings - bearing_rad)
        left = np.abs(differences[(differences < 0.0) & scan.observed])
        right = np.abs(differences[(differences > 0.0) & scan.observed])
        if not left.size or not right.size:
            return False
        left_distance = float(np.min(left))
        right_distance = float(np.min(right))
        return (
            left_distance <= 4.0 * scan.angle_increment + 1e-12
            and right_distance <= 4.0 * scan.angle_increment + 1e-12
            and left_distance + right_distance <= 5.0 * scan.angle_increment + 1e-12
        )

    def _sweep_is_observed(
        self,
        start_heading_rad: float,
        end_heading_rad: float,
        scan: _PreparedScan,
    ) -> bool:
        span = float(end_heading_rad) - float(start_heading_rad)
        samples = max(1, math.ceil(abs(span) / scan.angle_increment))
        return all(
            self._bearing_is_observed(
                float(start_heading_rad) + span * index / samples,
                scan,
            )
            for index in range(samples + 1)
        )

    def _alignment_yaw_target(self, heading_error_rad: float) -> float:
        desired = max(
            -self.max_yaw_rate,
            min(self.max_yaw_rate, float(heading_error_rad) * self.yaw_gain),
        )
        if abs(heading_error_rad) > 1e-12 and abs(desired) < self.min_align_yaw_rate:
            desired = math.copysign(self.min_align_yaw_rate, heading_error_rad)
        return desired

    def _escape_yaw_target(self, heading_error_rad: float) -> float:
        return max(
            -self.escape_max_yaw_rate,
            min(self.escape_max_yaw_rate, float(heading_error_rad) * self.yaw_gain),
        )

    def _settle_sweep_is_observed(
        self,
        heading_error_rad: float,
        scan: _PreparedScan,
    ) -> bool:
        # Settle admission must validate the curved ADVANCE command.  The
        # minimum alignment rate applies only to an in-place rotation and can
        # span a wider unknown wedge than the smaller forward command.
        commanded_yaw = self._escape_yaw_target(heading_error_rad)
        return self._sweep_is_observed(
            0.0,
            commanded_yaw * self.reaction_horizon_s,
            scan,
        )

    def _rollout_is_safe(
        self,
        vx_mps: float,
        yaw_rate_rps: float,
        obstacle_xy: np.ndarray,
    ) -> bool:
        if not obstacle_xy.size:
            return True
        steps = np.arange(self.rollout_steps, dtype=np.float64) + 0.5
        midpoint = yaw_rate_rps * steps * self.control_dt_s
        x = np.cumsum(vx_mps * np.cos(midpoint) * self.control_dt_s)
        y = np.cumsum(vx_mps * np.sin(midpoint) * self.control_dt_s)
        dx = x[:, None] - obstacle_xy[None, :, 0]
        dy = y[:, None] - obstacle_xy[None, :, 1]
        minimum = float(np.min(np.sqrt(dx * dx + dy * dy)))
        return minimum + self._collision_tolerance_m >= self.stop_distance_m

    def _direction_state(
        self,
        bearing_rad: float,
        scan: _PreparedScan,
    ) -> tuple[str, float]:
        if not self._bearing_is_observed(bearing_rad, scan):
            return "unknown", 0.0
        probe_vx = self.gap_probe_speed_mps * math.cos(bearing_rad)
        probe_vy = self.gap_probe_speed_mps * math.sin(bearing_rad)
        decision = self._projected_cap(probe_vx, probe_vy, 0.0, scan)
        if (
            math.hypot(decision.output_vx_mps, decision.output_vy_mps)
            < 0.95 * self.gap_probe_speed_mps
        ):
            return "blocked", 0.0
        if not scan.obstacle_xy.size:
            return "clear", 25.0
        distances = np.linspace(
            0.05,
            self.gap_probe_distance_m,
            max(2, math.ceil(self.gap_probe_distance_m / 0.05)),
            dtype=np.float64,
        )
        x = distances * math.cos(bearing_rad)
        y = distances * math.sin(bearing_rad)
        dx = x[:, None] - scan.obstacle_xy[None, :, 0]
        dy = y[:, None] - scan.obstacle_xy[None, :, 1]
        minimum = float(np.min(np.sqrt(dx * dx + dy * dy)))
        if minimum + self._collision_tolerance_m < self.stop_distance_m:
            return "blocked", minimum
        return "clear", minimum

    def _select_gap_direction(
        self,
        *,
        target_heading_error_rad: float,
        pose: Pose2D,
        scan: _PreparedScan,
    ) -> _GapChoice | None:
        states = tuple(
            self._direction_state(float(bearing), scan) for bearing in self._gap_bearings
        )
        feasible = tuple(state == "clear" for state, _clearance in states)
        runs = self._cyclic_true_runs(feasible)
        choices: list[tuple[float, _GapChoice]] = []
        count = len(self._gap_bearings)
        for run in runs:
            if len(run) < self.minimum_gap_samples:
                continue
            interior = run[1:-1] if len(run) > 2 else run
            center_index = run[len(run) // 2]
            center_bearing = float(self._gap_bearings[center_index])
            # Represent both sides of a gap that straddles the direct-goal
            # bearing.  Otherwise a goal-clamped sample at zero could hide a
            # fully observed same-side interior from the detour latch.
            for detour_side in (-1, 1):
                side_interior = tuple(
                    index
                    for index in interior
                    if (
                        1
                        if _wrap_angle(
                            float(self._gap_bearings[index]) - target_heading_error_rad
                        )
                        >= 0.0
                        else -1
                    )
                    == detour_side
                )
                if not side_interior:
                    continue
                target_index = min(
                    side_interior,
                    key=lambda index: (
                        abs(
                            _wrap_angle(
                                float(self._gap_bearings[index]) - target_heading_error_rad
                            )
                        ),
                        abs(float(self._gap_bearings[index])),
                        index,
                    ),
                )
                # Prefer the goal-clamped interior sample, while a weak center
                # term and width bonus prevent commitment to a gap edge.
                bearing = float(self._gap_bearings[target_index])
                clearance = float(states[target_index][1])
                goal_error = abs(_wrap_angle(bearing - target_heading_error_rad))
                center_error = abs(_wrap_angle(bearing - center_bearing))
                world_heading = _wrap_angle(pose.heading_rad + bearing)
                continuity = (
                    0.0
                    if self._previous_gap_heading_world_rad is None
                    else abs(_wrap_angle(world_heading - self._previous_gap_heading_world_rad))
                )
                score = (
                    -goal_error
                    - 0.12 * center_error
                    - self.gap_continuity_weight * continuity
                    + 0.025 * min(len(run), count)
                    + 0.06 * min(clearance, 3.0)
                )
                choices.append(
                    (
                        score,
                        _GapChoice(
                            bearing_rad=bearing,
                            width_samples=len(run),
                            minimum_clearance_m=clearance,
                            detour_side=detour_side,
                        ),
                    )
                )
        if not choices:
            return None
        if self._detour_side is not None:
            same_side = tuple(
                item for item in choices if item[1].detour_side == self._detour_side
            )
            if not same_side:
                return None
            choices = list(same_side)
        return max(
            choices,
            key=lambda item: (
                item[0],
                -abs(item[1].bearing_rad),
                item[1].minimum_clearance_m,
                -item[1].bearing_rad,
            ),
        )[1]

    @staticmethod
    def _cyclic_true_runs(values: Sequence[bool]) -> tuple[tuple[int, ...], ...]:
        flags = tuple(bool(value) for value in values)
        if not flags or not any(flags):
            return ()
        if all(flags):
            return (tuple(range(len(flags))),)
        start = next(index for index, value in enumerate(flags) if not value)
        runs: list[tuple[int, ...]] = []
        current: list[int] = []
        for offset in range(1, len(flags) + 1):
            index = (start + offset) % len(flags)
            if flags[index]:
                current.append(index)
            elif current:
                runs.append(tuple(current))
                current = []
        if current:
            runs.append(tuple(current))
        return tuple(runs)

    def _hold(self, reason: str, *, extra: str = "") -> MidLevelCommand:
        suffix = f" {extra}" if extra else ""
        return MidLevelCommand(
            vx=0.0,
            vy=0.0,
            vyaw=0.0,
            stop=False,
            note=f"v9s4_supervisor_hold reason={reason}{suffix}",
        )

    def _braking_hold(self, reason: str, *, extra: str = "") -> MidLevelCommand:
        yaw = self._slew(self._last_yaw_rate_rps, 0.0, self.max_yaw_delta_rps)
        self._last_vx_mps = 0.0
        self._last_yaw_rate_rps = yaw
        suffix = f" {extra}" if extra else ""
        return MidLevelCommand(
            vx=0.0,
            vy=0.0,
            vyaw=yaw,
            stop=False,
            note=f"v9s4_supervisor_hold reason={reason} braking=true{suffix}",
        )

    def _clear_commitment(self, *, keep_previous: bool) -> None:
        if not keep_previous:
            self._previous_gap_heading_world_rad = None
        self._committed_heading_world_rad = None
        self._escape_start_xy = None
        self._settling = False
        self._settled = False
        self._direction_unknown_ticks = 0
        self._sweep_unknown_ticks = 0
        self._commitment_start_goal_distance_m = None

    def _clear_gap_search(self) -> None:
        self._searching_for_gap = False
        self._search_exhausted = False
        self._search_ticks = 0
        self._search_trigger = None
        self._search_start_goal_distance_m = None
        self._search_started_route_unavailable = None

    def _clear_detour_latch(self) -> None:
        self._detour_side = None
        self._detour_latch_goal_distance_m = None
        self._detour_originated_from_route_loss = None
        self._previous_gap_heading_world_rad = None
        self._nominal_release_start_xy = None

    def _clear_all_recovery_memory(self) -> None:
        self._clear_commitment(keep_previous=False)
        self._clear_gap_search()
        self._clear_detour_latch()
        self._blocked_positive_ticks = 0
        self._last_vx_mps = 0.0
        self._last_yaw_rate_rps = 0.0

    @staticmethod
    def _maximum_ramp_distance(
        *,
        ticks: int,
        target_vx: float,
        maximum_delta: float,
        dt_s: float,
    ) -> float:
        velocity = 0.0
        distance = 0.0
        for _ in range(ticks):
            velocity = min(target_vx, velocity + maximum_delta)
            distance += velocity * dt_s
        return distance

    @staticmethod
    def _slew(current: float, target: float, maximum_delta: float) -> float:
        return float(current) + max(-maximum_delta, min(maximum_delta, float(target) - current))


def _wrap_angle(value: float) -> float:
    return (float(value) + math.pi) % _TWO_PI - math.pi


def _wrap_angle_array(value: np.ndarray | float) -> np.ndarray:
    return (np.asarray(value, dtype=np.float64) + math.pi) % _TWO_PI - math.pi


__all__ = ["SampledPredictiveTracker"]
