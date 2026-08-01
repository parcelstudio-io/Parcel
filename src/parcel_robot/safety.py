from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Pose, ToolCall, ToolResult


@dataclass(frozen=True)
class SafetyLimits:
    max_pose_duration: float = 10.0
    max_abs_joint_position: float = 3.2


class SafetySupervisor:
    """Fail-closed validation between probabilistic decisions and robot actions."""

    def __init__(self, poses: dict[str, Pose], limits: SafetyLimits | None = None):
        self.poses = poses
        self.limits = limits or SafetyLimits()
        self.emergency_stopped = False

    def validate(self, call: ToolCall) -> ToolResult:
        if call.name == "stop_motion":
            if call.arguments:
                return ToolResult(call.name, False, "stop_motion takes no arguments")
            return ToolResult(call.name, True, "Emergency stop requested")
        if call.name == "get_status":
            if call.arguments:
                return ToolResult(call.name, False, "get_status takes no arguments")
            return ToolResult(call.name, True, "Status request approved")
        if call.name != "run_pose":
            return ToolResult(call.name, False, f"Tool is not allowed: {call.name}")
        if self.emergency_stopped:
            return ToolResult(call.name, False, "Motion is disabled by emergency stop")
        if set(call.arguments) != {"name"} or not isinstance(call.arguments["name"], str):
            return ToolResult(call.name, False, "run_pose requires only a string name")
        pose = self.poses.get(call.arguments["name"])
        if pose is None:
            return ToolResult(call.name, False, f"Unknown pose: {call.arguments['name']}")
        if not 0 < pose.duration <= self.limits.max_pose_duration:
            return ToolResult(call.name, False, "Pose duration is outside the safe range")
        if not pose.joints:
            return ToolResult(call.name, False, "Pose contains no joints")
        for value in pose.joints.values():
            if not math.isfinite(value) or abs(value) > self.limits.max_abs_joint_position:
                return ToolResult(call.name, False, "Pose contains an unsafe joint position")
        return ToolResult(call.name, True, f"Pose approved: {pose.name}")

    def engage_emergency_stop(self) -> None:
        self.emergency_stopped = True

    def clear_emergency_stop(self) -> None:
        self.emergency_stopped = False
