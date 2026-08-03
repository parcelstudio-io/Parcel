"""Modern-Python Parcel side of the Habitat 2020 JSON-lines bridge."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Protocol, TextIO

from parcel_robot.navigation.base import GoalPose, MidLevelCommand, Mission, NavObservation
from parcel_robot.navigation.pipeline import DirectiveNavigator

from .habitat2020_py36_bridge import PROTOCOL_VERSION, BridgeProtocolError, decode_message


class _Controller(Protocol):
    mission: Mission | None

    def start(self, directive: str | Mission) -> Mission: ...

    def step(self, observation: NavObservation) -> MidLevelCommand: ...

    def close(self) -> None: ...


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeProtocolError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise BridgeProtocolError(f"{name} must be finite")
    return result


class ParcelPointNavSidecar:
    """Validate evaluator messages and call the unchanged Parcel controller."""

    def __init__(
        self,
        *,
        controller: _Controller | None = None,
        navigation_config: str | Path | None = None,
    ) -> None:
        if controller is None and navigation_config is None:
            raise ValueError("an explicit navigation_config is required outside tests")
        self._controller = controller or DirectiveNavigator.from_config(navigation_config)
        self._episode_id: int | None = None
        self._next_step_id = 0

    def handle(self, request: dict[str, object]) -> dict[str, object]:
        if request.get("schema_version") != PROTOCOL_VERSION:
            raise BridgeProtocolError("unsupported protocol schema_version")
        operation = request.get("op")
        if operation == "start":
            return self._start(request)
        if operation == "act":
            return self._act(request)
        if operation == "close":
            self.close()
            return {"schema_version": PROTOCOL_VERSION, "op": "closed"}
        raise BridgeProtocolError("unsupported sidecar operation")

    def _start(self, request: dict[str, object]) -> dict[str, object]:
        self._require_exact_keys(
            request,
            {"schema_version", "op", "episode_id", "goal", "arrival_radius_m"},
            "start",
        )
        episode_id = request.get("episode_id")
        if isinstance(episode_id, bool) or not isinstance(episode_id, int) or episode_id < 1:
            raise BridgeProtocolError("episode_id must be a positive integer")
        goal = request.get("goal")
        if not isinstance(goal, dict):
            raise BridgeProtocolError("start request is missing goal")
        self._require_exact_keys(goal, {"x_m", "y_m"}, "goal")
        goal_x = _finite(goal.get("x_m"), "goal.x_m")
        goal_y = _finite(goal.get("y_m"), "goal.y_m")
        arrival_radius = _finite(request.get("arrival_radius_m"), "arrival_radius_m")
        if not 0.0 < arrival_radius < 0.36:
            raise BridgeProtocolError("arrival_radius_m must be inside the official success region")
        mission = Mission(
            directive="habitat2020_pointnav",
            goal=GoalPose(
                x=goal_x,
                y=goal_y,
                arrival_radius_m=arrival_radius,
                label="Habitat 2020 static PointGoal",
            ),
            metadata={
                "external_evaluator": "habitat20-pointnav-public-validation",
                "goal_source": "official_static_pointgoal_sensor",
                "official_rank_eligible": False,
            },
        )
        self._controller.start(mission)
        self._episode_id = episode_id
        self._next_step_id = 0
        return {
            "schema_version": PROTOCOL_VERSION,
            "op": "started",
            "episode_id": episode_id,
        }

    def _act(self, request: dict[str, object]) -> dict[str, object]:
        self._require_exact_keys(
            request,
            {
                "schema_version",
                "op",
                "episode_id",
                "step_id",
                "pose",
                "scan",
                "sensor_contract",
            },
            "act",
        )
        if self._episode_id is None:
            raise BridgeProtocolError("act received before start")
        if request.get("episode_id") != self._episode_id:
            raise BridgeProtocolError("act episode_id does not match active episode")
        step_id = request.get("step_id")
        if step_id != self._next_step_id:
            raise BridgeProtocolError("act step_id is not the next monotonic step")
        sensor_contract = request.get("sensor_contract")
        if not isinstance(sensor_contract, dict):
            raise BridgeProtocolError("act requires a sensor_contract object")
        self._require_exact_keys(
            sensor_contract,
            {"depth_present", "rgb_present", "gps_compass_present"},
            "sensor_contract",
        )
        if (
            sensor_contract.get("depth_present") is not True
            or not isinstance(sensor_contract.get("rgb_present"), bool)
            or sensor_contract.get("gps_compass_present") is not False
        ):
            raise BridgeProtocolError("sensor contract must explicitly deny GPS/compass")
        pose = request.get("pose")
        scan = request.get("scan")
        if not isinstance(pose, dict) or not isinstance(scan, dict):
            raise BridgeProtocolError("act requires pose and scan objects")
        self._require_exact_keys(pose, {"x_m", "y_m", "heading_rad"}, "pose")
        self._require_exact_keys(
            scan,
            {
                "ranges_m",
                "angle_min_rad",
                "angle_increment_rad",
                "range_min_m",
                "range_max_m",
                "source",
            },
            "scan",
        )
        x_m = _finite(pose.get("x_m"), "pose.x_m")
        y_m = _finite(pose.get("y_m"), "pose.y_m")
        heading_rad = _finite(pose.get("heading_rad"), "pose.heading_rad")
        angle_min = _finite(scan.get("angle_min_rad"), "scan.angle_min_rad")
        angle_increment = _finite(
            scan.get("angle_increment_rad"), "scan.angle_increment_rad"
        )
        range_min = _finite(scan.get("range_min_m"), "scan.range_min_m")
        range_max = _finite(scan.get("range_max_m"), "scan.range_max_m")
        raw_ranges = scan.get("ranges_m")
        if (
            not isinstance(raw_ranges, list)
            or not 3 <= len(raw_ranges) <= 4096
            or angle_increment <= 0.0
            or range_min < 0.0
            or range_max <= range_min
        ):
            raise BridgeProtocolError("scan geometry or ranges are invalid")
        ranges: list[float] = []
        nearest_distance = math.inf
        nearest_index = 0
        for index, value in enumerate(raw_ranges):
            if value is None:
                ranges.append(math.inf)
                continue
            distance = _finite(value, f"scan.ranges_m[{index}]")
            if distance < range_min or distance > range_max + 1e-6:
                raise BridgeProtocolError("finite scan range lies outside calibration")
            ranges.append(distance)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_index = index
        nearest = None if not math.isfinite(nearest_distance) else nearest_distance
        extras: dict[str, object] = {
            "lidar_angle_min_rad": angle_min,
            "lidar_angle_increment_rad": angle_increment,
            "lidar_range_min_m": range_min,
            "lidar_range_max_m": range_max,
            "perception_fresh": True,
            "collision": False,
            "external_evaluator": "habitat20-pointnav-public-validation",
            "pose_source": "nominal_commanded_action_dead_reckoning",
            "scan_source": scan.get("source"),
        }
        if nearest is not None:
            bearing = angle_min + nearest_index * angle_increment
            extras.update(
                {
                    "obstacle_id": "depth_nearest",
                    "obstacle_bearing_rad": bearing,
                    "lidar_obstacles": [
                        {
                            "id": "depth_nearest",
                            "distance_m": nearest,
                            "bearing_rad": bearing,
                        }
                    ],
                }
            )
        command = self._controller.step(
            NavObservation(
                position=(x_m, y_m, 0.0),
                heading_deg=math.degrees(heading_rad),
                lidar=tuple(ranges),
                nearest_obstacle_m=nearest,
                extras=extras,
            )
        )
        response = {
            "schema_version": PROTOCOL_VERSION,
            "op": "command",
            "episode_id": self._episode_id,
            "step_id": step_id,
            "vx": float(command.vx),
            "vy": float(command.vy),
            "vyaw": float(command.vyaw),
            "stop": bool(command.stop),
            "mission_status": (
                None if self._controller.mission is None else self._controller.mission.status
            ),
            "note": command.note,
        }
        self._next_step_id += 1
        return response

    @staticmethod
    def _require_exact_keys(
        value: dict[str, object],
        expected: set[str],
        name: str,
    ) -> None:
        actual = set(value)
        if actual != expected:
            extra = sorted(actual - expected)
            missing = sorted(expected - actual)
            raise BridgeProtocolError(
                f"{name} keys do not match contract; extra={extra}, missing={missing}"
            )

    def close(self) -> None:
        self._controller.close()
        self._episode_id = None


def serve(sidecar: ParcelPointNavSidecar, input_stream: TextIO, output_stream: TextIO) -> int:
    """Serve strict JSON lines until close or fail closed on malformed input."""

    for line in input_stream:
        try:
            request = decode_message(line)
            response = sidecar.handle(request)
        except (BridgeProtocolError, TypeError, ValueError) as exc:
            response = {
                "schema_version": PROTOCOL_VERSION,
                "op": "error",
                "error": str(exc),
            }
            output_stream.write(json.dumps(response, allow_nan=False, sort_keys=True) + "\n")
            output_stream.flush()
            sidecar.close()
            return 2
        output_stream.write(json.dumps(response, allow_nan=False, sort_keys=True) + "\n")
        output_stream.flush()
        if response.get("op") == "closed":
            return 0
    sidecar.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--navigation-config", required=True, type=Path)
    args = parser.parse_args(argv)
    sidecar = ParcelPointNavSidecar(navigation_config=args.navigation_config)
    return serve(sidecar, sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
