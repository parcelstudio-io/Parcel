"""ROS 2 executable for the evaluator-only BARN transport.

The module imports ROS lazily so the core contract remains testable in Parcel's
normal Python environment.  In the official compatibility image run it with
the ROS 2 Jazzy interpreter and an explicit, immutable navigation config::

    python3 -m evals.external.barn_ros2_node \
      --navigation-config /opt/parcel/configs/navigation/experiments/barn_grid_v1.yaml

Only the organizer-documented ``launch_navigation_stack`` hook should launch
this process.  The evaluator itself remains unchanged.
"""

from __future__ import annotations

import argparse
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .barn_ros2_adapter import (
    BARN_ROS2_COMMAND_TOPIC,
    BARN_ROS2_CONTROL_PERIOD_S,
    BARN_ROS2_LIDAR_CALIBRATION,
    BARN_ROS2_LIDAR_TOPIC,
    BARN_ROS2_ODOMETRY_TOPIC,
    BARN_ROS2_STATIC_GOAL_ODOM_XY,
    BarnRos2AdapterCore,
    BarnRos2SensorFrame,
    quaternion_to_yaw,
)

STARTUP_LIVENESS_WINDOW_S = 10.0
STARTUP_LIVENESS_CHECK_PERIOD_S = 0.1
STARTUP_MIN_XY_RESPONSE_M = 0.02
STARTUP_MIN_FORWARD_OPPORTUNITY_M = 0.05
STARTUP_LIVENESS_EXIT_CODE = 3

StartupLivenessFault = Literal[
    "no_inputs",
    "policy_no_translation",
    "actuator_no_response",
]


@dataclass(frozen=True, slots=True)
class StartupLivenessSnapshot:
    """Policy-visible evidence collected before the evaluator starts its clock."""

    elapsed_s: float
    odometry_count: int
    scan_count: int
    policy_command_count: int
    cumulative_forward_opportunity_m: float
    cumulative_yaw_opportunity_rad: float
    max_xy_response_m: float
    max_yaw_response_rad: float


class StartupLivenessTracker:
    """Collect startup motion evidence without depending on ROS imports."""

    def __init__(self, *, started_s: float) -> None:
        if not math.isfinite(started_s) or started_s < 0.0:
            raise ValueError("started_s must be finite and non-negative")
        self.started_s = float(started_s)
        self.odometry_count = 0
        self.scan_count = 0
        self.policy_command_count = 0
        self.cumulative_forward_opportunity_m = 0.0
        self.cumulative_yaw_opportunity_rad = 0.0
        self.max_xy_response_m = 0.0
        self.max_yaw_response_rad = 0.0
        self._latest_xy: tuple[float, float] | None = None
        self._forward_response_origin_xy: tuple[float, float] | None = None
        self._forward_response_origin_pending = False
        self._initial_yaw_rad: float | None = None

    def observe_odometry(self, x: float, y: float, yaw_rad: float) -> None:
        values = (float(x), float(y), float(yaw_rad))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("odometry pose must be finite")
        self.odometry_count += 1
        xy = (values[0], values[1])
        self._latest_xy = xy
        if self._initial_yaw_rad is None:
            self._initial_yaw_rad = values[2]
        if self._forward_response_origin_pending:
            self._forward_response_origin_xy = xy
            self._forward_response_origin_pending = False
        if self._forward_response_origin_xy is not None:
            self.max_xy_response_m = max(
                self.max_xy_response_m,
                math.dist(self._forward_response_origin_xy, xy),
            )
        yaw_delta = abs(_wrap_angle(values[2] - self._initial_yaw_rad))
        self.max_yaw_response_rad = max(self.max_yaw_response_rad, yaw_delta)

    def observe_scan(self) -> None:
        self.scan_count += 1

    def observe_policy_command(
        self,
        forward_mps: float,
        yaw_rate_rps: float,
        *,
        opportunity_period_s: float,
    ) -> None:
        values = (float(forward_mps), float(yaw_rate_rps), float(opportunity_period_s))
        if not all(math.isfinite(value) for value in values) or values[2] <= 0.0:
            raise ValueError("policy command and opportunity period must be finite")
        self.policy_command_count += 1
        positive_forward_mps = max(0.0, values[0])
        if positive_forward_mps > 0.0 and self._forward_response_origin_xy is None:
            if self._latest_xy is None:
                self._forward_response_origin_pending = True
            else:
                self._forward_response_origin_xy = self._latest_xy
        self.cumulative_forward_opportunity_m += positive_forward_mps * values[2]
        self.cumulative_yaw_opportunity_rad += abs(values[1]) * values[2]

    def snapshot(self, *, now_s: float) -> StartupLivenessSnapshot:
        if not math.isfinite(now_s) or now_s < self.started_s:
            raise ValueError("now_s must be finite and not precede startup")
        return StartupLivenessSnapshot(
            elapsed_s=float(now_s) - self.started_s,
            odometry_count=self.odometry_count,
            scan_count=self.scan_count,
            policy_command_count=self.policy_command_count,
            cumulative_forward_opportunity_m=self.cumulative_forward_opportunity_m,
            cumulative_yaw_opportunity_rad=self.cumulative_yaw_opportunity_rad,
            max_xy_response_m=self.max_xy_response_m,
            max_yaw_response_rad=self.max_yaw_response_rad,
        )


class StartupLivenessFailure(RuntimeError):
    """Raised inside the ROS executor to terminate a stalled pre-trial run."""

    def __init__(self, reason: StartupLivenessFault) -> None:
        super().__init__(f"Parcel BARN startup liveness failed: {reason}")
        self.reason = reason


def classify_startup_liveness(
    snapshot: StartupLivenessSnapshot,
    *,
    startup_window_s: float = STARTUP_LIVENESS_WINDOW_S,
    min_xy_response_m: float = STARTUP_MIN_XY_RESPONSE_M,
    min_forward_opportunity_m: float = STARTUP_MIN_FORWARD_OPPORTUNITY_M,
) -> StartupLivenessFault | None:
    """Return a startup fault, or ``None`` while healthy/pending.

    The full bounded window is available for turn-first alignment and scan
    recovery. Any small measured translation proves the command path is live
    and permanently clears the startup gate in the ROS wrapper.
    """

    _validate_startup_limits(
        startup_window_s=startup_window_s,
        min_xy_response_m=min_xy_response_m,
        min_forward_opportunity_m=min_forward_opportunity_m,
    )
    if startup_translation_is_live(snapshot, min_xy_response_m=min_xy_response_m):
        return None
    if snapshot.elapsed_s + 1e-9 < startup_window_s:
        return None
    if (
        snapshot.odometry_count == 0
        or snapshot.scan_count == 0
        or snapshot.policy_command_count == 0
    ):
        return "no_inputs"
    if snapshot.cumulative_forward_opportunity_m < min_forward_opportunity_m:
        return "policy_no_translation"
    return "actuator_no_response"


def startup_translation_is_live(
    snapshot: StartupLivenessSnapshot,
    *,
    min_xy_response_m: float = STARTUP_MIN_XY_RESPONSE_M,
) -> bool:
    """Return whether forward policy output caused measurable odometry motion."""

    if not math.isfinite(min_xy_response_m) or not 0.001 <= min_xy_response_m <= 0.10:
        raise ValueError("--startup-min-xy-response must be in [0.001, 0.10] meters")
    return (
        snapshot.odometry_count > 0
        and snapshot.scan_count > 0
        and snapshot.policy_command_count > 0
        and snapshot.cumulative_forward_opportunity_m > 0.0
        and snapshot.max_xy_response_m >= min_xy_response_m
    )


def _validate_startup_limits(
    *,
    startup_window_s: float,
    min_xy_response_m: float,
    min_forward_opportunity_m: float,
) -> None:
    if not math.isfinite(startup_window_s) or not 2.0 <= startup_window_s <= 60.0:
        raise ValueError("--startup-window must be in [2, 60] seconds")
    if not math.isfinite(min_xy_response_m) or not 0.001 <= min_xy_response_m <= 0.10:
        raise ValueError("--startup-min-xy-response must be in [0.001, 0.10] meters")
    if (
        not math.isfinite(min_forward_opportunity_m)
        or not 0.005 <= min_forward_opportunity_m <= 2.0
    ):
        raise ValueError("--startup-min-forward-opportunity must be in [0.005, 2.0] meters")
    if min_forward_opportunity_m < min_xy_response_m:
        raise ValueError(
            "--startup-min-forward-opportunity must be at least --startup-min-xy-response"
        )


def _wrap_angle(value: float) -> float:
    return (float(value) + math.pi) % (2.0 * math.pi) - math.pi


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--navigation-config", type=Path, required=True)
    parser.add_argument("--goal-x", type=float, default=BARN_ROS2_STATIC_GOAL_ODOM_XY[0])
    parser.add_argument("--goal-y", type=float, default=BARN_ROS2_STATIC_GOAL_ODOM_XY[1])
    parser.add_argument("--arrival-radius", type=float, default=0.75)
    parser.add_argument("--lidar-range-cap", type=float, default=10.0)
    parser.add_argument("--control-period", type=float, default=BARN_ROS2_CONTROL_PERIOD_S)
    parser.add_argument("--startup-window", type=float, default=STARTUP_LIVENESS_WINDOW_S)
    parser.add_argument(
        "--startup-min-xy-response",
        type=float,
        default=STARTUP_MIN_XY_RESPONSE_M,
    )
    parser.add_argument(
        "--startup-min-forward-opportunity",
        type=float,
        default=STARTUP_MIN_FORWARD_OPPORTUNITY_M,
    )
    parser.add_argument("--lidar-topic", default=BARN_ROS2_LIDAR_TOPIC)
    parser.add_argument("--odometry-topic", default=BARN_ROS2_ODOMETRY_TOPIC)
    parser.add_argument("--command-topic", default=BARN_ROS2_COMMAND_TOPIC)
    return parser


def _message_stamp_s(message: Any, fallback_s: float) -> float:
    stamp = message.header.stamp
    value = float(stamp.sec) + float(stamp.nanosec) * 1e-9
    return value if value > 0.0 else fallback_s


def main(argv: Sequence[str] | None = None) -> int:
    args, ros_args = _parser().parse_known_args(argv)
    if not math.isfinite(args.control_period) or args.control_period <= 0.0:
        raise ValueError("--control-period must be positive")
    _validate_startup_limits(
        startup_window_s=args.startup_window,
        min_xy_response_m=args.startup_min_xy_response,
        min_forward_opportunity_m=args.startup_min_forward_opportunity,
    )

    try:
        import rclpy
        from geometry_msgs.msg import TwistStamped
        from nav_msgs.msg import Odometry
        from rclpy.clock import Clock, ClockType
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import LaserScan
    except ImportError as exc:  # pragma: no cover - exercised only in the ROS image
        raise RuntimeError(
            "ROS 2 Jazzy Python packages are required; run this node inside the "
            "pinned BARN compatibility container"
        ) from exc

    class ParcelBarnRos2Node(Node):
        def __init__(self) -> None:
            super().__init__("parcel_barn_ros2_adapter")
            self._core = BarnRos2AdapterCore.from_navigation_config(
                args.navigation_config,
                goal_xy=(args.goal_x, args.goal_y),
                arrival_radius_m=args.arrival_radius,
                lidar_max_range_m=args.lidar_range_cap,
                lidar_calibration=BARN_ROS2_LIDAR_CALIBRATION,
            )
            self._latest_odometry: Any | None = None
            self._last_control_stamp_s: float | None = None
            self._terminal = False
            self._startup_liveness_passed = False
            self._startup_liveness = StartupLivenessTracker(started_s=time.monotonic())
            self._odometry_observed = False
            self._scan_observed = False
            self._policy_command_observed = False
            self._normalization_observed = False
            self._publisher = self.create_publisher(TwistStamped, args.command_topic, 10)
            self.create_subscription(
                Odometry,
                args.odometry_topic,
                self._on_odometry,
                qos_profile_sensor_data,
            )
            self._startup_liveness_timer = self.create_timer(
                STARTUP_LIVENESS_CHECK_PERIOD_S,
                self._check_startup_liveness,
                clock=Clock(clock_type=ClockType.STEADY_TIME),
            )
            self.create_subscription(
                LaserScan,
                args.lidar_topic,
                self._on_scan,
                qos_profile_sensor_data,
            )
            self.get_logger().info(
                f"Parcel BARN ROS2 adapter ready: scan={args.lidar_topic} "
                f"odom={args.odometry_topic} cmd={args.command_topic}"
            )

        def _on_odometry(self, message: Any) -> None:
            try:
                pose = message.pose.pose
                self._startup_liveness.observe_odometry(
                    float(pose.position.x),
                    float(pose.position.y),
                    quaternion_to_yaw(
                        pose.orientation.x,
                        pose.orientation.y,
                        pose.orientation.z,
                        pose.orientation.w,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - unusable odometry is not an input
                self.get_logger().warning(
                    f"discarding invalid odometry: {type(exc).__name__}: {exc}"
                )
                return
            self._latest_odometry = message
            if not self._odometry_observed:
                self._odometry_observed = True
                self.get_logger().info("Parcel BARN first odometry received")

        def _on_scan(self, scan: Any) -> None:
            self._startup_liveness.observe_scan()
            if not self._scan_observed:
                self._scan_observed = True
                self.get_logger().info(
                    "Parcel BARN first scan received: "
                    f"odom_ready={str(self._latest_odometry is not None).lower()} "
                    f"frame={str(scan.header.frame_id)!r}"
                )
            if self._latest_odometry is None:
                return
            now_s = self.get_clock().now().nanoseconds * 1e-9
            stamp_s = _message_stamp_s(scan, now_s)
            if self._last_control_stamp_s is not None:
                elapsed = stamp_s - self._last_control_stamp_s
                if elapsed <= 0.0:
                    self.get_logger().warning("discarding non-monotonic LaserScan timestamp")
                    return
                if elapsed + 1e-9 < args.control_period:
                    return
            self._last_control_stamp_s = stamp_s

            if self._terminal:
                self._publish(0.0, 0.0, scan)
                return
            pose = self._latest_odometry.pose.pose
            try:
                odometry_stamp_s = _message_stamp_s(self._latest_odometry, now_s)
                frame = BarnRos2SensorFrame(
                    stamp_s=stamp_s,
                    position_xy=(float(pose.position.x), float(pose.position.y)),
                    heading_rad=quaternion_to_yaw(
                        pose.orientation.x,
                        pose.orientation.y,
                        pose.orientation.z,
                        pose.orientation.w,
                    ),
                    lidar_ranges_m=tuple(float(value) for value in scan.ranges),
                    lidar_angle_min_rad=float(scan.angle_min),
                    lidar_angle_increment_rad=float(scan.angle_increment),
                    lidar_range_min_m=float(scan.range_min),
                    lidar_range_max_m=float(scan.range_max),
                    odometry_stamp_s=odometry_stamp_s,
                    lidar_frame_id=str(scan.header.frame_id),
                    odometry_child_frame_id=str(self._latest_odometry.child_frame_id),
                )
                command = self._core.step(frame)
            except Exception as exc:  # noqa: BLE001 - transport must fail closed
                self.get_logger().error(f"adapter failed closed: {type(exc).__name__}: {exc}")
                self._terminal = True
                self._publish(0.0, 0.0, scan)
                return
            diagnostics = self._core.last_normalization_diagnostics
            if not self._normalization_observed and diagnostics is not None:
                self._normalization_observed = True
                self.get_logger().info(
                    "Parcel BARN calibrated scan: "
                    f"lidar_stamp={diagnostics.lidar_stamp_s:.6f} "
                    f"odom_stamp={diagnostics.odometry_stamp_s:.6f} "
                    f"frame={diagnostics.lidar_frame_id!r} "
                    f"base={diagnostics.base_frame_id!r} "
                    f"rays={diagnostics.input_ray_count} "
                    f"finite_hits={diagnostics.finite_hit_count} "
                    f"self_returns={diagnostics.self_return_count}"
                )
            self._startup_liveness.observe_policy_command(
                command.forward_mps,
                command.yaw_rate_rps,
                opportunity_period_s=args.control_period,
            )
            if not self._policy_command_observed:
                self._policy_command_observed = True
                self.get_logger().info(
                    "Parcel BARN first policy command: "
                    f"forward={command.forward_mps:.6f} "
                    f"yaw={command.yaw_rate_rps:.6f} "
                    f"stop={str(command.stop).lower()} note={command.note[:160]}"
                )
            self._publish(command.forward_mps, command.yaw_rate_rps, scan)
            self._terminal = command.stop

        def _check_startup_liveness(self) -> None:
            if self._startup_liveness_passed:
                return
            snapshot = self._startup_liveness.snapshot(now_s=time.monotonic())
            if startup_translation_is_live(
                snapshot,
                min_xy_response_m=args.startup_min_xy_response,
            ):
                self._startup_liveness_passed = True
                self._startup_liveness_timer.cancel()
                self.get_logger().info(
                    "Parcel BARN startup liveness passed: "
                    f"xy_response_m={snapshot.max_xy_response_m:.6f} "
                    f"yaw_response_rad={snapshot.max_yaw_response_rad:.6f} "
                    f"commands={snapshot.policy_command_count}"
                )
                return
            fault = classify_startup_liveness(
                snapshot,
                startup_window_s=args.startup_window,
                min_xy_response_m=args.startup_min_xy_response,
                min_forward_opportunity_m=args.startup_min_forward_opportunity,
            )
            if fault is None:
                return
            self._terminal = True
            self.stop()
            self.get_logger().error(
                "adapter failed closed: "
                f"startup_liveness={fault} elapsed_s={snapshot.elapsed_s:.3f} "
                f"odom={snapshot.odometry_count} scans={snapshot.scan_count} "
                f"commands={snapshot.policy_command_count} "
                "forward_opportunity_m="
                f"{snapshot.cumulative_forward_opportunity_m:.6f} "
                f"xy_response_m={snapshot.max_xy_response_m:.6f} "
                f"yaw_response_rad={snapshot.max_yaw_response_rad:.6f}"
            )
            raise StartupLivenessFailure(fault)

        def _publish(self, forward_mps: float, yaw_rate_rps: float, scan: Any) -> None:
            message = TwistStamped()
            message.header.stamp = scan.header.stamp
            message.header.frame_id = "base_link"
            message.twist.linear.x = float(forward_mps)
            message.twist.linear.y = 0.0
            message.twist.angular.z = float(yaw_rate_rps)
            self._publisher.publish(message)

        def stop(self) -> None:
            message = TwistStamped()
            message.header.stamp = self.get_clock().now().to_msg()
            message.header.frame_id = "base_link"
            self._publisher.publish(message)

        def close(self) -> None:
            # rclpy's SIGINT handler can invalidate the context before
            # ``spin()`` returns.  Publishing after that point raises RCLError
            # and obscures an otherwise valid evaluator terminal row.  Send a
            # final stop only while the publisher context is live; the regular
            # terminal and liveness paths already publish zero immediately.
            if self.context.ok():
                self.stop()
            self._core.close()

    rclpy.init(args=list(ros_args))
    node = ParcelBarnRos2Node()
    exit_code = 0
    try:
        rclpy.spin(node)
    except StartupLivenessFailure:
        exit_code = STARTUP_LIVENESS_EXIT_CODE
    except KeyboardInterrupt:  # pragma: no cover - interactive ROS shutdown
        pass
    finally:
        node.close()
        node.destroy_node()
        rclpy.shutdown()
    return exit_code


if __name__ == "__main__":  # pragma: no cover - ROS image entry point
    raise SystemExit(main())


__all__ = [
    "STARTUP_LIVENESS_EXIT_CODE",
    "STARTUP_LIVENESS_WINDOW_S",
    "StartupLivenessFailure",
    "StartupLivenessSnapshot",
    "StartupLivenessTracker",
    "classify_startup_liveness",
    "main",
    "startup_translation_is_live",
]
