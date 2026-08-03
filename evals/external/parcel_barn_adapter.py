"""Sensor-only adapter from BARN observations to Parcel's unchanged navigator.

This module is intentionally outside ``src/parcel_robot``.  It translates the
benchmark's odometry, goal and LaserScan-shaped frame into Parcel's existing
``NavObservation``/``Mission`` contracts; it does not alter or subclass the dog
controller.  Evaluator-owned world geometry and reference paths never cross
this boundary.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Protocol

from parcel_robot.navigation.base import GoalPose, MidLevelCommand, Mission, NavObservation
from parcel_robot.navigation.pipeline import DirectiveNavigator

from .barn_native import BarnAction, BarnObservation

PARCEL_BARN_ADAPTER_ID = "parcel-directive-navigator-barn-sensor-adapter-v1"


class _DirectiveController(Protocol):
    mission: Mission | None

    def start(self, directive: str | Mission) -> Mission: ...

    def step(self, observation: NavObservation) -> MidLevelCommand: ...

    def done(self) -> bool: ...

    def close(self) -> None: ...


@dataclass
class _ScanTrack:
    track_id: str
    x: float
    y: float
    last_frame: int


@dataclass(frozen=True)
class _ScanCluster:
    distance_m: float
    bearing_rad: float
    x: float
    y: float


class ParcelBarnAdapter:
    """Run the production ``DirectiveNavigator`` behind the BARN policy API.

    Lateral velocity is discarded because the standard BARN Jackal action is
    differential-drive.  Parcel's current point-goal controller emits ``vy=0``;
    the conversion is nevertheless explicit in the action note for provenance.
    """

    def __init__(
        self,
        controller: _DirectiveController | None = None,
        *,
        navigation_config: str | Path | None = None,
        arrival_radius_m: float = 0.75,
        lidar_max_range_m: float = 10.0,
        cluster_jump_m: float = 0.18,
        track_gate_m: float = 0.60,
        track_ttl_frames: int = 8,
    ) -> None:
        if not 0.0 < arrival_radius_m < 1.0:
            raise ValueError("arrival_radius_m must be inside BARN's 1m success region")
        if not math.isfinite(lidar_max_range_m) or lidar_max_range_m <= 0.0:
            raise ValueError("lidar_max_range_m must be finite and positive")
        if not math.isfinite(cluster_jump_m) or cluster_jump_m <= 0.0:
            raise ValueError("cluster_jump_m must be finite and positive")
        if not math.isfinite(track_gate_m) or track_gate_m <= 0.0:
            raise ValueError("track_gate_m must be finite and positive")
        if not 1 <= track_ttl_frames <= 1_000:
            raise ValueError("track_ttl_frames must be in [1, 1000]")
        self._controller = controller or DirectiveNavigator.from_config(
            navigation_config,
            arrive_radius_m=arrival_radius_m,
        )
        self.arrival_radius_m = arrival_radius_m
        self.lidar_max_range_m = lidar_max_range_m
        self.cluster_jump_m = cluster_jump_m
        self.track_gate_m = track_gate_m
        self.track_ttl_frames = track_ttl_frames
        self._tracks: dict[str, _ScanTrack] = {}
        self._next_track = 1
        self._frame = 0
        self._goal_xy: tuple[float, float] | None = None
        self._act_latency_ms: list[float] = []
        self._controller_latency_ms: list[float] = []
        self._controller_phase_counts: Counter[str] = Counter()
        self._safety_phase_counts: Counter[str] = Counter()

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        for name, pair in (("start_xy", start_xy), ("goal_xy", goal_xy)):
            if len(pair) != 2 or not all(math.isfinite(float(value)) for value in pair):
                raise ValueError(f"{name} must contain two finite values")
        if not math.isfinite(heading_rad):
            raise ValueError("heading_rad must be finite")
        self._tracks.clear()
        self._next_track = 1
        self._frame = 0
        self._goal_xy = (float(goal_xy[0]), float(goal_xy[1]))
        self._act_latency_ms = []
        self._controller_latency_ms = []
        self._controller_phase_counts.clear()
        self._safety_phase_counts.clear()
        self._controller.start(
            Mission(
                directive="BARN metric goal",
                goal=GoalPose(
                    x=self._goal_xy[0],
                    y=self._goal_xy[1],
                    heading_deg=0.0,
                    label="BARN goal",
                    arrival_radius_m=self.arrival_radius_m,
                ),
                status="idle",
                metadata={
                    "goal_source": "external_benchmark_metric_goal",
                    "adapter_id": PARCEL_BARN_ADAPTER_ID,
                    "initial_pose": (float(start_xy[0]), float(start_xy[1]), heading_rad),
                },
            )
        )

    def act(self, observation: BarnObservation) -> BarnAction:
        act_started_ns = time.perf_counter_ns()
        if self._goal_xy is None:
            raise RuntimeError("ParcelBarnAdapter.reset() must be called before act()")
        if self._controller.done():
            action = BarnAction(0.0, 0.0, stop=True, note="parcel_navigation_done")
            self._act_latency_ms.append((time.perf_counter_ns() - act_started_ns) / 1e6)
            return action

        lidar_obstacles = self._tracked_scan_clusters(observation)
        nearest = min(lidar_obstacles, key=lambda item: item["distance_m"], default=None)
        extras = {
            "lidar_obstacles": lidar_obstacles,
            "lidar_angle_min_rad": observation.lidar_angle_min_rad,
            "lidar_angle_increment_rad": observation.lidar_angle_increment_rad,
            "lidar_range_min_m": 0.05,
            "lidar_range_max_m": self.lidar_max_range_m,
            "obstacle_id": None if nearest is None else nearest["id"],
            "obstacle_bearing_rad": None if nearest is None else nearest["bearing_rad"],
            "collision": False,
            "perception_fresh": True,
            # The native runner publishes odometry and LaserScan from the same
            # deterministic sensor tick.  Keep these as policy-visible sensor
            # metadata; they are neither evaluator geometry nor wall-clock
            # truth.  Experimental recovery policies can therefore fail
            # closed on stale or unsynchronised frames just as the Go2 bridge
            # must do.
            "lidar_timestamp_s": observation.time_s,
            "odometry_timestamp_s": observation.time_s,
            "lidar_fresh": True,
            "odometry_fresh": True,
            "benchmark_time_s": observation.time_s,
            "benchmark_adapter_id": PARCEL_BARN_ADAPTER_ID,
        }
        controller_started_ns = time.perf_counter_ns()
        command = self._controller.step(
            NavObservation(
                position=(observation.position_xy[0], observation.position_xy[1], 0.0),
                heading_deg=math.degrees(observation.heading_rad),
                lidar=observation.lidar_ranges_m,
                nearest_obstacle_m=(None if nearest is None else float(nearest["distance_m"])),
                extras=extras,
            )
        )
        self._controller_latency_ms.append((time.perf_counter_ns() - controller_started_ns) / 1e6)
        note_parts = command.note.split("|") if command.note else ["<none>"]
        controller_phase = note_parts[0].split(maxsplit=1)[0]
        safety_phase = note_parts[-1].strip() if len(note_parts) > 1 else "<none>"
        self._controller_phase_counts[controller_phase] += 1
        self._safety_phase_counts[safety_phase] += 1
        lateral_note = "" if abs(command.vy) <= 1e-9 else f"|vy_discarded={command.vy:.3f}"
        action = BarnAction(
            vx_mps=command.vx,
            yaw_rate_rps=command.vyaw,
            stop=command.stop,
            note=f"{command.note}{lateral_note}",
        )
        self._act_latency_ms.append((time.perf_counter_ns() - act_started_ns) / 1e6)
        return action

    def latency_metrics(self) -> dict[str, float]:
        """Return wall-clock adapter/controller inference latency for the episode."""

        metrics: dict[str, float] = {}
        for prefix, samples in (
            ("adapter_act", self._act_latency_ms),
            ("controller_step", self._controller_latency_ms),
        ):
            if not samples:
                continue
            ordered = sorted(samples)
            metrics[f"{prefix}_count"] = float(len(ordered))
            metrics[f"{prefix}_mean_ms"] = fmean(ordered)
            metrics[f"{prefix}_p50_ms"] = _nearest_rank(ordered, 0.50)
            metrics[f"{prefix}_p95_ms"] = _nearest_rank(ordered, 0.95)
            metrics[f"{prefix}_p99_ms"] = _nearest_rank(ordered, 0.99)
            metrics[f"{prefix}_max_ms"] = ordered[-1]
        return metrics

    def latency_samples_ms(self) -> dict[str, tuple[float, ...]]:
        return {
            "adapter_act": tuple(self._act_latency_ms),
            "controller_step": tuple(self._controller_latency_ms),
        }

    def policy_diagnostics(self) -> dict[str, object]:
        """Return policy-owned phase counters without evaluator-private state."""

        total = sum(self._controller_phase_counts.values())
        recovery = sum(
            count
            for phase, count in self._controller_phase_counts.items()
            if phase.startswith("grid_recover")
        )
        return {
            "controller_phase_counts": dict(sorted(self._controller_phase_counts.items())),
            "safety_phase_counts": dict(sorted(self._safety_phase_counts.items())),
            "recovery_fraction": recovery / total if total else 0.0,
            "policy_owned_only": True,
        }

    def close(self) -> None:
        self._controller.close()

    def _tracked_scan_clusters(self, observation: BarnObservation) -> list[dict[str, object]]:
        self._frame += 1
        clusters = self._scan_clusters(observation)
        available = {
            track_id
            for track_id, track in self._tracks.items()
            if self._frame - track.last_frame <= self.track_ttl_frames
        }
        results: list[dict[str, object]] = []
        for cluster in sorted(clusters, key=lambda item: item.distance_m):
            candidates = [
                (
                    math.hypot(
                        cluster.x - self._tracks[track_id].x, cluster.y - self._tracks[track_id].y
                    ),
                    track_id,
                )
                for track_id in available
            ]
            distance, track_id = min(candidates, default=(math.inf, ""))
            if distance > self.track_gate_m:
                track_id = f"scan-cluster-{self._next_track:05d}"
                self._next_track += 1
            else:
                available.remove(track_id)
            self._tracks[track_id] = _ScanTrack(
                track_id=track_id,
                x=cluster.x,
                y=cluster.y,
                last_frame=self._frame,
            )
            results.append(
                {
                    "id": track_id,
                    "distance_m": cluster.distance_m,
                    "bearing_rad": cluster.bearing_rad,
                }
            )
        self._tracks = {
            track_id: track
            for track_id, track in self._tracks.items()
            if self._frame - track.last_frame <= self.track_ttl_frames
        }
        return results[:64]

    def _scan_clusters(self, observation: BarnObservation) -> tuple[_ScanCluster, ...]:
        segments: list[list[tuple[int, float]]] = []
        active: list[tuple[int, float]] = []
        for index, raw_range in enumerate(observation.lidar_ranges_m):
            distance = float(raw_range)
            valid = math.isfinite(distance) and 0.0 <= distance < self.lidar_max_range_m - 1e-6
            if not valid:
                if active:
                    segments.append(active)
                    active = []
                continue
            if active:
                previous = active[-1][1]
                adaptive_jump = self.cluster_jump_m + 0.04 * min(previous, distance)
                if abs(distance - previous) > adaptive_jump:
                    segments.append(active)
                    active = []
            active.append((index, distance))
        if active:
            segments.append(active)

        clusters: list[_ScanCluster] = []
        for segment in segments:
            index, distance = min(segment, key=lambda item: item[1])
            bearing = (
                observation.lidar_angle_min_rad + index * observation.lidar_angle_increment_rad
            )
            world_angle = observation.heading_rad + bearing
            clusters.append(
                _ScanCluster(
                    distance_m=distance,
                    bearing_rad=bearing,
                    x=observation.position_xy[0] + distance * math.cos(world_angle),
                    y=observation.position_xy[1] + distance * math.sin(world_angle),
                )
            )
        return tuple(clusters)


def _nearest_rank(ordered: list[float], quantile: float) -> float:
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


__all__ = ["PARCEL_BARN_ADAPTER_ID", "ParcelBarnAdapter"]
