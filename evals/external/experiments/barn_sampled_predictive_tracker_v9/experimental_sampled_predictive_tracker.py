"""Deployment-disabled deterministic sampled local tracker for the BARN v9 trial.

This component is intentionally narrower than a complete navigator.  The
existing :class:`GridNavigator` remains responsible for mapping, A* routing,
arrival, and bounded recovery.  After that navigator has produced one nominal
body command, this tracker may choose a different forward/yaw primitive using
only the current route target and calibrated full-circle planner scan.

The implementation is a CPU NumPy research proxy, not Nav2 MPPI.  It uses a
fixed candidate cloud, constant-control unicycle rollouts, an observed-return
projected cap at the planner scan's native resolution, and a conservative
point-return rollout check.  The independent pipeline's raw 720-ray v8 shield
remains authoritative.
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
class _Candidate:
    vx_mps: float
    yaw_rate_rps: float
    source: str


@dataclass(frozen=True, slots=True)
class _SelectionDiagnostics:
    candidate_count: int
    feasible_count: int
    shield_reject_count: int
    rollout_reject_count: int


@dataclass(frozen=True, slots=True)
class _ProjectedDecision:
    output_vx_mps: float
    output_vy_mps: float
    applied_scale: float


class SampledPredictiveTracker:
    """Select one safe, forward-only primitive around GridNavigator's command.

    ``select`` returns ``None`` only for a terminal nominal command or a goal
    already coincident with the pose.  Missing routes use a short sensor-safe
    goal-bearing bootstrap. Invalid perception and infeasible primitives
    produce an explicit non-terminal zero-velocity hold.
    """

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
        escape_translation_ticks: int = 6,
        commitment_score_bonus: float = 0.18,
        bootstrap_vx_mps: float = 0.12,
        stop_distance_m: float = 0.8,
        reaction_horizon_s: float = 0.12,
        max_linear_accel: float = 0.9,
        max_yaw_accel: float = 1.8,
    ) -> None:
        positive = {
            "cruise_vx": cruise_vx,
            "max_yaw_rate": max_yaw_rate,
            "min_align_yaw_rate": min_align_yaw_rate,
            "yaw_gain": yaw_gain,
            "control_dt_s": control_dt_s,
            "minimum_translation_mps": minimum_translation_mps,
            "gap_probe_speed_mps": gap_probe_speed_mps,
            "gap_probe_distance_m": gap_probe_distance_m,
            "commitment_score_bonus": commitment_score_bonus,
            "bootstrap_vx_mps": bootstrap_vx_mps,
            "stop_distance_m": stop_distance_m,
            "reaction_horizon_s": reaction_horizon_s,
            "max_linear_accel": max_linear_accel,
            "max_yaw_accel": max_yaw_accel,
        }
        if any(
            not math.isfinite(float(value)) or float(value) <= 0.0 for value in positive.values()
        ):
            raise ValueError("v9 tracker rates, distances, and weights must be positive and finite")
        if not 0.0 < align_exit_deg < align_enter_deg < 180.0:
            raise ValueError("heading thresholds must satisfy 0 < exit < enter < 180")
        if not math.isclose(control_dt_s, 0.1, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("v9 uses the frozen v8 0.1 second control period")
        if not 4 <= rollout_steps <= 30:
            raise ValueError("rollout_steps must be in [4, 30]")
        if not 8 <= sample_count <= 512:
            raise ValueError("sample_count must be in [8, 512]")
        if isinstance(sample_seed, bool) or not isinstance(sample_seed, int):
            raise TypeError("sample_seed must be an integer")
        if not 16 <= gap_direction_samples <= 144:
            raise ValueError("gap_direction_samples must be in [16, 144]")
        if not 1 <= escape_translation_ticks <= 50:
            raise ValueError("escape_translation_ticks must be in [1, 50]")
        if minimum_translation_mps >= cruise_vx:
            raise ValueError("minimum_translation_mps must be below cruise_vx")

        self.cruise_vx = float(cruise_vx)
        self.align_enter_rad = math.radians(float(align_enter_deg))
        self.align_exit_rad = math.radians(float(align_exit_deg))
        self.max_yaw_rate = float(max_yaw_rate)
        self.min_align_yaw_rate = float(min_align_yaw_rate)
        self.yaw_gain = float(yaw_gain)
        self.control_dt_s = float(control_dt_s)
        self.rollout_steps = int(rollout_steps)
        self.minimum_translation_mps = float(minimum_translation_mps)
        self.gap_direction_samples = int(gap_direction_samples)
        self.gap_probe_speed_mps = float(gap_probe_speed_mps)
        self.gap_probe_distance_m = float(gap_probe_distance_m)
        self.escape_translation_ticks = int(escape_translation_ticks)
        self.commitment_score_bonus = float(commitment_score_bonus)
        self.bootstrap_vx_mps = min(float(bootstrap_vx_mps), self.cruise_vx)
        self.stop_distance_m = float(stop_distance_m)
        self.reaction_horizon_s = float(reaction_horizon_s)
        self.max_linear_delta_mps = float(max_linear_accel) * self.control_dt_s
        self.max_yaw_delta_rps = float(max_yaw_accel) * self.control_dt_s
        self._collision_tolerance_m = 1e-9
        self._closing_epsilon_mps = 1e-9

        # Fixed once at construction: no tick-order-dependent RNG state and no
        # stochastic difference between paired/replayed episodes.
        generator = np.random.default_rng(sample_seed)
        self._sample_noise = generator.standard_normal((int(sample_count), 2)).astype(np.float64)
        self._sample_noise.setflags(write=False)
        self._gap_bearings = np.linspace(
            -math.pi,
            math.pi,
            self.gap_direction_samples,
            endpoint=False,
            dtype=np.float64,
        )
        self._gap_bearings.setflags(write=False)
        self.reset()

    def reset(self) -> None:
        self._aligning = True
        self._settling = False
        self._last_vx_mps = 0.0
        self._last_yaw_rate_rps = 0.0
        self._committed_gap_heading_world_rad: float | None = None
        self._escape_ticks_remaining = 0

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
        """Return the selected V9 command, including sensor-safe route bootstrap."""

        if nominal.stop:
            self._clear_gap_commitment()
            return None

        bootstrap = not route_available or waypoint is None
        if waypoint is None:
            dx = float(goal_world[0]) - pose.x
            dy = float(goal_world[1]) - pose.y
            target_distance_m = math.hypot(dx, dy)
            if not math.isfinite(target_distance_m) or target_distance_m <= 1e-9:
                self._clear_gap_commitment()
                return None
            target_heading_error = _wrap_angle(math.atan2(dy, dx) - pose.heading_rad)
            target_left_m = math.sin(target_heading_error) * target_distance_m
        else:
            target_distance_m = float(waypoint.distance_m)
            target_heading_error = float(waypoint.heading_error_rad)
            target_left_m = float(waypoint.left_m)

        prepared, scan_reason = self._prepare_scan(scan)
        if prepared is None:
            self._last_vx_mps = 0.0
            self._last_yaw_rate_rps = 0.0
            self._clear_gap_commitment()
            return self._hold(f"scan_{scan_reason}", commitment="invalidated")
        ranges, angle_min, angle_increment, obstacle_xy = prepared

        commitment = "none"
        effective_heading_error = target_heading_error
        escape_active = False
        if self._committed_gap_heading_world_rad is not None:
            gap_error = _wrap_angle(self._committed_gap_heading_world_rad - pose.heading_rad)
            if self._direction_is_feasible(
                gap_error,
                ranges=ranges,
                angle_min=angle_min,
                angle_increment=angle_increment,
                obstacle_xy=obstacle_xy,
            ):
                commitment = "reused"
                effective_heading_error = gap_error
                escape_active = True
            else:
                self._clear_gap_commitment()
                commitment = "invalidated"

        if escape_active and abs(effective_heading_error) > self.align_exit_rad:
            return self._rotation_command(
                effective_heading_error,
                ranges=ranges,
                angle_min=angle_min,
                angle_increment=angle_increment,
                phase="gap_commit_rotate",
                commitment=commitment,
            )
        if escape_active and abs(self._last_yaw_rate_rps) > 1e-9:
            return self._rotation_command(
                0.0,
                ranges=ranges,
                angle_min=angle_min,
                angle_increment=angle_increment,
                phase="gap_commit_settle",
                commitment=commitment,
            )

        if not escape_active:
            absolute_error = abs(effective_heading_error)
            if self._aligning:
                if absolute_error <= self.align_exit_rad:
                    self._aligning = False
                    self._settling = abs(self._last_yaw_rate_rps) > 1e-9
            elif absolute_error >= self.align_enter_rad:
                self._aligning = True
                self._settling = False
            if self._aligning:
                return self._rotation_command(
                    effective_heading_error,
                    ranges=ranges,
                    angle_min=angle_min,
                    angle_increment=angle_increment,
                    phase="rotate_first",
                    commitment=commitment,
                )
            if self._settling:
                if abs(self._last_yaw_rate_rps) <= 1e-9:
                    self._settling = False
                else:
                    return self._rotation_command(
                        0.0,
                        ranges=ranges,
                        angle_min=angle_min,
                        angle_increment=angle_increment,
                        phase="rotate_first_settle",
                        commitment=commitment,
                    )

        candidates = self._candidate_controls(
            nominal=nominal,
            heading_error_rad=effective_heading_error,
            target_distance_m=target_distance_m,
            target_left_m=target_left_m,
            escape_active=escape_active,
            bootstrap=bootstrap,
        )
        route_body = self._route_points_in_body(pose, route_waypoints_world)
        selected, score, diagnostics = self._select_translation(
            candidates,
            heading_error_rad=effective_heading_error,
            route_body=route_body,
            ranges=ranges,
            angle_min=angle_min,
            angle_increment=angle_increment,
            obstacle_xy=obstacle_xy,
        )
        if selected is not None:
            self._last_vx_mps = selected.vx_mps
            self._last_yaw_rate_rps = selected.yaw_rate_rps
            if escape_active:
                self._escape_ticks_remaining -= 1
                if self._escape_ticks_remaining <= 0:
                    self._clear_gap_commitment()
            return MidLevelCommand(
                vx=selected.vx_mps,
                vy=0.0,
                vyaw=selected.yaw_rate_rps,
                stop=False,
                note=(
                    "v9_sampled_track "
                    f"source={selected.source} candidates={diagnostics.candidate_count} "
                    f"feasible={diagnostics.feasible_count} "
                    f"shield_reject={diagnostics.shield_reject_count} "
                    f"rollout_reject={diagnostics.rollout_reject_count} "
                    f"score={score:.4f} commitment={commitment}"
                ),
            )

        # A committed escape that became rollout-infeasible must not coast for
        # one more control tick.  Invalidate it before looking for fresh gaps.
        if escape_active:
            self._clear_gap_commitment()
            commitment = "invalidated"

        gap = self._select_gap_direction(
            target_heading_error_rad=target_heading_error,
            ranges=ranges,
            angle_min=angle_min,
            angle_increment=angle_increment,
            obstacle_xy=obstacle_xy,
        )
        if gap is None:
            self._last_vx_mps = 0.0
            self._last_yaw_rate_rps = 0.0
            return self._hold(
                "no_feasible_primitive",
                commitment=commitment,
                diagnostics=diagnostics,
            )

        self._committed_gap_heading_world_rad = _wrap_angle(pose.heading_rad + gap)
        self._escape_ticks_remaining = self.escape_translation_ticks
        return self._rotation_command(
            gap,
            ranges=ranges,
            angle_min=angle_min,
            angle_increment=angle_increment,
            phase="gap_seed_rotate",
            commitment="new" if commitment == "none" else commitment,
            extra_note=f"bearing_deg={math.degrees(gap):.1f}",
        )

    def _prepare_scan(
        self,
        scan: LidarScan,
    ) -> tuple[tuple[tuple[float, ...], float, float, np.ndarray] | None, str]:
        try:
            ranges = tuple(float(value) for value in scan.ranges_m)
            angle_min = float(scan.angle_min_rad)
            angle_increment = float(scan.angle_increment_rad)
        except (AttributeError, TypeError, ValueError):
            return None, "contract_invalid"
        if (
            len(ranges) < 16
            or not math.isfinite(angle_min)
            or not math.isfinite(angle_increment)
            or angle_increment <= 0.0
        ):
            return None, "contract_invalid"
        coverage = (len(ranges) - 1) * angle_increment
        # Accept both duplicated-seam scans and ordinary full-circle scans
        # whose final bin ends one increment before the seam.  This includes
        # GridNavigator's deterministic raw[::2] planner scan.
        coverage_tolerance = max(1e-5, 1.5 * angle_increment)
        if not math.isclose(coverage, _TWO_PI, rel_tol=0.0, abs_tol=coverage_tolerance):
            return None, "contract_invalid"

        array = np.asarray(ranges, dtype=np.float64)
        invalid = np.isneginf(array) | (np.isfinite(array) & (array < 0.0))
        if bool(np.any(invalid)):
            return None, "contract_invalid"
        observed = np.isfinite(array) | np.isposinf(array)
        if not bool(np.any(observed)):
            return None, "unavailable"

        finite = np.isfinite(array)
        bearings = angle_min + np.arange(array.size) * angle_increment
        obstacle_xy = np.column_stack(
            (array[finite] * np.cos(bearings[finite]), array[finite] * np.sin(bearings[finite]))
        )
        return (
            ranges,
            angle_min,
            angle_increment,
            obstacle_xy,
        ), "ok"

    def _projected_cap(
        self,
        vx_mps: float,
        vy_mps: float,
        yaw_rate_rps: float,
        ranges: tuple[float, ...],
        *,
        angle_min: float,
        angle_increment: float,
    ) -> _ProjectedDecision:
        """Cap translation against every observed finite return.

        This mirrors the v8 projected-closing invariant at the planner scan's
        native ray count.  It deliberately creates no certificate and makes no
        claim about NaN bins; the unchanged raw-scan pipeline shield performs
        final 720-ray certification.
        """

        speed = math.hypot(vx_mps, vy_mps)
        if speed <= self._closing_epsilon_mps:
            return _ProjectedDecision(float(vx_mps), float(vy_mps), 1.0)
        array = np.asarray(ranges, dtype=np.float64)
        finite_indices = np.flatnonzero(np.isfinite(array))
        if finite_indices.size == 0:
            return _ProjectedDecision(float(vx_mps), float(vy_mps), 1.0)

        bearings = angle_min + finite_indices * angle_increment
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
        available = np.maximum(0.0, array[finite_indices] - self.stop_distance_m)
        ray_scale = np.ones_like(closing_speed)
        ray_scale[closing] = np.minimum(
            1.0,
            available[closing] / (self.reaction_horizon_s * closing_speed[closing]),
        )
        scale = float(np.min(ray_scale))
        if scale <= 0.0:
            return _ProjectedDecision(0.0, 0.0, 0.0)
        return _ProjectedDecision(float(vx_mps) * scale, float(vy_mps) * scale, scale)

    def _rotation_command(
        self,
        heading_error_rad: float,
        *,
        ranges: tuple[float, ...],
        angle_min: float,
        angle_increment: float,
        phase: str,
        commitment: str,
        extra_note: str = "",
    ) -> MidLevelCommand:
        desired = max(
            -self.max_yaw_rate,
            min(self.max_yaw_rate, heading_error_rad * self.yaw_gain),
        )
        if abs(heading_error_rad) <= self.align_exit_rad:
            desired = 0.0
        elif abs(desired) < self.min_align_yaw_rate:
            desired = math.copysign(self.min_align_yaw_rate, heading_error_rad)
        desired = self._slew(
            self._last_yaw_rate_rps,
            desired,
            self.max_yaw_delta_rps,
        )
        # Smoothly shed a prior safe forward command before rotating.  The
        # projected cap may brake faster when current observed geometry makes
        # the slewed residual unsafe; safety takes precedence over smoothness.
        residual_vx = self._slew(self._last_vx_mps, 0.0, self.max_linear_delta_mps)
        decision = self._projected_cap(
            max(0.0, residual_vx),
            0.0,
            desired,
            ranges,
            angle_min=angle_min,
            angle_increment=angle_increment,
        )
        self._last_vx_mps = decision.output_vx_mps
        self._last_yaw_rate_rps = desired
        suffix = f" {extra_note}" if extra_note else ""
        return MidLevelCommand(
            vx=decision.output_vx_mps,
            vy=0.0,
            vyaw=desired,
            stop=False,
            note=(
                f"v9_{phase} err_deg={math.degrees(heading_error_rad):.1f} "
                f"commitment={commitment}{suffix}"
            ),
        )

    def _candidate_controls(
        self,
        *,
        nominal: MidLevelCommand,
        heading_error_rad: float,
        target_distance_m: float,
        target_left_m: float,
        escape_active: bool,
        bootstrap: bool,
    ) -> tuple[_Candidate, ...]:
        requested_ceiling = max(0.0, float(nominal.vx))
        if bootstrap:
            requested_ceiling = max(requested_ceiling, self.bootstrap_vx_mps)
        if escape_active:
            requested_ceiling = max(requested_ceiling, self.gap_probe_speed_mps)
        velocity_lower = max(0.0, self._last_vx_mps - self.max_linear_delta_mps)
        velocity_upper = min(
            self.cruise_vx,
            self._last_vx_mps + self.max_linear_delta_mps,
        )
        ceiling = min(velocity_upper, max(velocity_lower, requested_ceiling))
        if ceiling < self.minimum_translation_mps:
            return ()

        if escape_active:
            distance_proxy = max(0.05, self.gap_probe_distance_m)
            lateral_proxy = math.sin(heading_error_rad) * distance_proxy
        else:
            distance_proxy = max(0.05, float(target_distance_m))
            lateral_proxy = float(target_left_m)
        curvature = 2.0 * lateral_proxy / (distance_proxy * distance_proxy)
        rpp_yaw = max(
            -self.max_yaw_rate,
            min(self.max_yaw_rate, ceiling * curvature),
        )
        yaw_lower = max(-self.max_yaw_rate, self._last_yaw_rate_rps - self.max_yaw_delta_rps)
        yaw_upper = min(self.max_yaw_rate, self._last_yaw_rate_rps + self.max_yaw_delta_rps)
        rpp_yaw = max(yaw_lower, min(yaw_upper, rpp_yaw))
        values: list[_Candidate] = [
            _Candidate(
                ceiling,
                rpp_yaw,
                "bootstrap_rpp" if bootstrap else "rpp_warm_start",
            ),
            _Candidate(
                ceiling,
                max(yaw_lower, min(yaw_upper, float(nominal.vyaw))),
                "bootstrap_nominal" if bootstrap else "grid_nominal",
            ),
        ]
        if self._last_vx_mps >= self.minimum_translation_mps:
            values.append(
                _Candidate(
                    min(ceiling, self._last_vx_mps),
                    max(yaw_lower, min(yaw_upper, self._last_yaw_rate_rps)),
                    "committed_warm_start",
                )
            )

        speeds = np.clip(
            ceiling * (0.78 + 0.22 * self._sample_noise[:, 0]),
            max(self.minimum_translation_mps, velocity_lower),
            ceiling,
        )
        yaws = np.clip(
            rpp_yaw + 0.28 * self._sample_noise[:, 1],
            yaw_lower,
            yaw_upper,
        )
        values.extend(
            _Candidate(float(vx), float(yaw), "sample")
            for vx, yaw in zip(speeds, yaws, strict=True)
        )
        # Stable deduplication keeps diagnostics and ties reproducible.
        unique: dict[tuple[float, float], _Candidate] = {}
        for candidate in values:
            key = (round(candidate.vx_mps, 12), round(candidate.yaw_rate_rps, 12))
            unique.setdefault(key, candidate)
        return tuple(unique.values())

    def _select_translation(
        self,
        candidates: Sequence[_Candidate],
        *,
        heading_error_rad: float,
        route_body: np.ndarray,
        ranges: tuple[float, ...],
        angle_min: float,
        angle_increment: float,
        obstacle_xy: np.ndarray,
    ) -> tuple[_Candidate | None, float, _SelectionDiagnostics]:
        shielded: list[_Candidate] = []
        shield_rejects = 0
        if not self._bearing_is_observed(
            0.0,
            ranges=ranges,
            angle_min=angle_min,
            angle_increment=angle_increment,
        ):
            diagnostics = _SelectionDiagnostics(len(candidates), 0, len(candidates), 0)
            return None, -math.inf, diagnostics
        for candidate in candidates:
            decision = self._projected_cap(
                candidate.vx_mps,
                0.0,
                candidate.yaw_rate_rps,
                ranges,
                angle_min=angle_min,
                angle_increment=angle_increment,
            )
            if decision.output_vx_mps < self.minimum_translation_mps:
                shield_rejects += 1
                continue
            shielded.append(
                _Candidate(
                    min(self.cruise_vx, max(0.0, decision.output_vx_mps)),
                    max(
                        -self.max_yaw_rate,
                        min(self.max_yaw_rate, candidate.yaw_rate_rps),
                    ),
                    candidate.source,
                )
            )

        if not shielded:
            diagnostics = _SelectionDiagnostics(len(candidates), 0, shield_rejects, 0)
            return None, -math.inf, diagnostics

        vx = np.asarray([item.vx_mps for item in shielded], dtype=np.float64)
        yaw = np.asarray([item.yaw_rate_rps for item in shielded], dtype=np.float64)
        x, y, theta = self._rollouts(vx, yaw)
        if obstacle_xy.size:
            dx = x[:, :, None] - obstacle_xy[None, None, :, 0]
            dy = y[:, :, None] - obstacle_xy[None, None, :, 1]
            distances = np.sqrt(dx * dx + dy * dy)
            minimum_clearance = np.min(distances, axis=(1, 2))
        else:
            minimum_clearance = np.full(vx.shape, 25.0, dtype=np.float64)
        rollout_safe = minimum_clearance + self._collision_tolerance_m >= self.stop_distance_m
        safe_indices = np.flatnonzero(rollout_safe)
        rollout_rejects = len(shielded) - int(safe_indices.size)
        if safe_indices.size == 0:
            diagnostics = _SelectionDiagnostics(len(candidates), 0, shield_rejects, rollout_rejects)
            return None, -math.inf, diagnostics

        target_x = math.cos(heading_error_rad)
        target_y = math.sin(heading_error_rad)
        progress = x[:, -1] * target_x + y[:, -1] * target_y
        cross_track = np.abs(-target_y * x[:, -1] + target_x * y[:, -1])
        heading_error = np.abs(_wrap_angle_array(heading_error_rad - theta[:, -1]))
        if route_body.size:
            route_dx = x[:, -1, None] - route_body[None, :, 0]
            route_dy = y[:, -1, None] - route_body[None, :, 1]
            route_distance = np.min(np.sqrt(route_dx * route_dx + route_dy * route_dy), axis=1)
        else:
            route_distance = cross_track
        smoothness = 0.35 * np.abs(vx - self._last_vx_mps) + 0.12 * np.abs(
            yaw - self._last_yaw_rate_rps
        )
        scores = (
            4.0 * progress
            - 0.70 * heading_error
            - 0.55 * route_distance
            - 0.35 * cross_track
            - smoothness
            + 0.06 * np.minimum(minimum_clearance, 3.0)
        )
        for index, candidate in enumerate(shielded):
            if (
                self._last_vx_mps >= self.minimum_translation_mps
                and abs(candidate.vx_mps - self._last_vx_mps) <= 0.04
                and abs(candidate.yaw_rate_rps - self._last_yaw_rate_rps) <= 0.10
            ):
                scores[index] += self.commitment_score_bonus
            if candidate.source == "rpp_warm_start":
                scores[index] += 0.02

        best = int(
            max(
                safe_indices.tolist(),
                key=lambda index: (
                    float(scores[index]),
                    -abs(shielded[index].yaw_rate_rps),
                    shielded[index].vx_mps,
                    -index,
                ),
            )
        )
        diagnostics = _SelectionDiagnostics(
            len(candidates), int(safe_indices.size), shield_rejects, rollout_rejects
        )
        return shielded[best], float(scores[best]), diagnostics

    def _rollouts(
        self,
        vx: np.ndarray,
        yaw: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        step = np.arange(self.rollout_steps, dtype=np.float64) + 0.5
        midpoint_heading = yaw[:, None] * (step[None, :] * self.control_dt_s)
        x = np.cumsum(vx[:, None] * np.cos(midpoint_heading) * self.control_dt_s, axis=1)
        y = np.cumsum(vx[:, None] * np.sin(midpoint_heading) * self.control_dt_s, axis=1)
        end_step = np.arange(1, self.rollout_steps + 1, dtype=np.float64)
        theta = yaw[:, None] * (end_step[None, :] * self.control_dt_s)
        return x, y, theta

    def _select_gap_direction(
        self,
        *,
        target_heading_error_rad: float,
        ranges: tuple[float, ...],
        angle_min: float,
        angle_increment: float,
        obstacle_xy: np.ndarray,
    ) -> float | None:
        choices: list[tuple[float, float]] = []
        for raw in self._gap_bearings:
            bearing = float(raw)
            if abs(bearing) <= self.align_exit_rad:
                continue
            if not self._direction_is_feasible(
                bearing,
                ranges=ranges,
                angle_min=angle_min,
                angle_increment=angle_increment,
                obstacle_xy=obstacle_xy,
            ):
                continue
            deviation = abs(_wrap_angle(bearing - target_heading_error_rad))
            continuity = (
                0.0
                if abs(self._last_yaw_rate_rps) <= 1e-9
                or math.copysign(1.0, bearing) == math.copysign(1.0, self._last_yaw_rate_rps)
                else 0.25
            )
            score = -deviation - 0.08 * abs(bearing) - continuity
            choices.append((score, bearing))
        if not choices:
            return None
        return max(
            choices,
            key=lambda item: (item[0], -abs(item[1]), -item[1]),
        )[1]

    def _direction_is_feasible(
        self,
        bearing_rad: float,
        *,
        ranges: tuple[float, ...],
        angle_min: float,
        angle_increment: float,
        obstacle_xy: np.ndarray,
    ) -> bool:
        if not self._bearing_is_observed(
            bearing_rad,
            ranges=ranges,
            angle_min=angle_min,
            angle_increment=angle_increment,
        ):
            return False
        probe_vx = self.gap_probe_speed_mps * math.cos(bearing_rad)
        probe_vy = self.gap_probe_speed_mps * math.sin(bearing_rad)
        decision = self._projected_cap(
            probe_vx,
            probe_vy,
            0.0,
            ranges,
            angle_min=angle_min,
            angle_increment=angle_increment,
        )
        if (
            math.hypot(decision.output_vx_mps, decision.output_vy_mps)
            < 0.95 * self.gap_probe_speed_mps
        ):
            return False
        if not obstacle_xy.size:
            return True
        distances = np.linspace(
            0.05,
            self.gap_probe_distance_m,
            max(2, math.ceil(self.gap_probe_distance_m / 0.05)),
            dtype=np.float64,
        )
        x = distances * math.cos(bearing_rad)
        y = distances * math.sin(bearing_rad)
        dx = x[:, None] - obstacle_xy[None, :, 0]
        dy = y[:, None] - obstacle_xy[None, :, 1]
        minimum = float(np.min(np.sqrt(dx * dx + dy * dy)))
        return minimum + self._collision_tolerance_m >= self.stop_distance_m

    @staticmethod
    def _bearing_is_observed(
        bearing_rad: float,
        *,
        ranges: tuple[float, ...],
        angle_min: float,
        angle_increment: float,
    ) -> bool:
        bearings = angle_min + np.arange(len(ranges), dtype=np.float64) * angle_increment
        differences = np.abs(_wrap_angle_array(bearings - bearing_rad))
        nearest = int(np.argmin(differences))
        return not math.isnan(ranges[nearest])

    @staticmethod
    def _route_points_in_body(
        pose: Pose2D,
        route_waypoints_world: Sequence[WorldPoint],
    ) -> np.ndarray:
        points: list[tuple[float, float]] = []
        cosine = math.cos(pose.heading_rad)
        sine = math.sin(pose.heading_rad)
        for raw in route_waypoints_world:
            try:
                wx, wy = float(raw[0]), float(raw[1])
            except (IndexError, TypeError, ValueError):
                continue
            if not math.isfinite(wx) or not math.isfinite(wy):
                continue
            dx = wx - pose.x
            dy = wy - pose.y
            points.append((cosine * dx + sine * dy, -sine * dx + cosine * dy))
        if not points:
            return np.empty((0, 2), dtype=np.float64)
        return np.asarray(points, dtype=np.float64)

    def _hold(
        self,
        reason: str,
        *,
        commitment: str,
        diagnostics: _SelectionDiagnostics | None = None,
    ) -> MidLevelCommand:
        if diagnostics is None:
            details = "candidates=0 feasible=0 shield_reject=0 rollout_reject=0"
        else:
            details = (
                f"candidates={diagnostics.candidate_count} "
                f"feasible={diagnostics.feasible_count} "
                f"shield_reject={diagnostics.shield_reject_count} "
                f"rollout_reject={diagnostics.rollout_reject_count}"
            )
        return MidLevelCommand(
            vx=0.0,
            vy=0.0,
            vyaw=0.0,
            stop=False,
            note=f"v9_sampled_hold reason={reason} {details} commitment={commitment}",
        )

    def _clear_gap_commitment(self) -> None:
        self._committed_gap_heading_world_rad = None
        self._escape_ticks_remaining = 0

    @staticmethod
    def _slew(current: float, target: float, maximum_delta: float) -> float:
        return float(current) + max(-maximum_delta, min(maximum_delta, float(target) - current))


def _wrap_angle(value: float) -> float:
    return (float(value) + math.pi) % _TWO_PI - math.pi


def _wrap_angle_array(value: np.ndarray | float) -> np.ndarray:
    return (np.asarray(value, dtype=np.float64) + math.pi) % _TWO_PI - math.pi


__all__ = ["SampledPredictiveTracker"]
