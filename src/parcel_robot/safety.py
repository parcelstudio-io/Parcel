from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Pose, ToolCall, ToolResult


@dataclass(frozen=True)
class SafetyLimits:
    max_pose_duration: float = 10.0
    max_abs_joint_position: float = 3.2
    max_vx: float = 0.6
    max_vy: float = 0.4
    max_vyaw: float = 1.0


ALLOWED_BACKENDS = frozenset({"sport", "rl"})


class SafetySupervisor:
    """Fail-closed validation between probabilistic decisions and robot actions."""

    def __init__(
        self,
        poses: dict[str, Pose],
        limits: SafetyLimits | None = None,
        skill_ids: list[str] | None = None,
    ):
        self.poses = poses
        self.limits = limits or SafetyLimits()
        self.skill_ids = set(skill_ids or poses)
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
        if call.name == "set_motion_backend":
            return self._validate_backend(call)
        if call.name == "set_velocity":
            return self._validate_velocity(call)
        if call.name == "run_skill":
            return self._validate_skill(call)
        if call.name == "navigate":
            return self._validate_navigate(call)
        if call.name == "set_behavior":
            return self._validate_behavior(call)
        if call.name != "run_pose":
            return ToolResult(call.name, False, f"Tool is not allowed: {call.name}")
        if self.emergency_stopped:
            return ToolResult(call.name, False, "Motion is disabled by emergency stop")
        if set(call.arguments) != {"name"} or not isinstance(call.arguments["name"], str):
            return ToolResult(call.name, False, "run_pose requires only a string name")
        pose = self.poses.get(call.arguments["name"])
        if pose is None and call.arguments["name"] not in self.skill_ids:
            return ToolResult(call.name, False, f"Unknown pose: {call.arguments['name']}")
        if pose is not None:
            if not 0 < pose.duration <= self.limits.max_pose_duration:
                return ToolResult(call.name, False, "Pose duration is outside the safe range")
            if not pose.joints:
                return ToolResult(call.name, False, "Pose contains no joints")
            for value in pose.joints.values():
                if not math.isfinite(value) or abs(value) > self.limits.max_abs_joint_position:
                    return ToolResult(call.name, False, "Pose contains an unsafe joint position")
            return ToolResult(call.name, True, f"Pose approved: {pose.name}")
        return ToolResult(call.name, True, f"Skill approved: {call.arguments['name']}")

    def _validate_skill(self, call: ToolCall) -> ToolResult:
        if self.emergency_stopped:
            return ToolResult(call.name, False, "Motion is disabled by emergency stop")
        if set(call.arguments) != {"name"} or not isinstance(call.arguments["name"], str):
            return ToolResult(call.name, False, "run_skill requires only a string name")
        name = call.arguments["name"]
        if name not in self.skill_ids:
            return ToolResult(call.name, False, f"Unknown skill: {name}")
        return ToolResult(call.name, True, f"Skill approved: {name}")

    def _validate_navigate(self, call: ToolCall) -> ToolResult:
        if self.emergency_stopped:
            return ToolResult(call.name, False, "Motion is disabled by emergency stop")
        if set(call.arguments) != {"directive"} or not isinstance(
            call.arguments.get("directive"), str
        ):
            return ToolResult(call.name, False, "navigate requires only a string directive")
        directive = call.arguments["directive"].strip()
        if not directive:
            return ToolResult(call.name, False, "navigate directive is empty")
        return ToolResult(call.name, True, f"Navigation approved: {directive}")

    def _validate_backend(self, call: ToolCall) -> ToolResult:
        if set(call.arguments) != {"name"} or not isinstance(call.arguments["name"], str):
            return ToolResult(call.name, False, "set_motion_backend requires only a string name")
        name = call.arguments["name"]
        if name not in ALLOWED_BACKENDS:
            return ToolResult(call.name, False, f"Unknown motion backend: {name}")
        return ToolResult(call.name, True, f"Motion backend approved: {name}")

    def _validate_behavior(self, call: ToolCall) -> ToolResult:
        if self.emergency_stopped:
            return ToolResult(call.name, False, "Motion is disabled by emergency stop")
        if set(call.arguments) != {"mode"} or not isinstance(
            call.arguments.get("mode"), str
        ):
            return ToolResult(call.name, False, "set_behavior requires only a string mode")
        mode = call.arguments["mode"]
        if mode not in {"follow", "stay"}:
            return ToolResult(call.name, False, f"Unknown behavior: {mode}")
        return ToolResult(call.name, True, f"Behavior approved: {mode}")

    def _validate_velocity(self, call: ToolCall) -> ToolResult:
        if self.emergency_stopped:
            return ToolResult(call.name, False, "Motion is disabled by emergency stop")
        allowed = {"vx", "vy", "vyaw"}
        if not set(call.arguments).issubset(allowed):
            return ToolResult(call.name, False, "set_velocity only accepts vx, vy, vyaw")
        values = {
            key: float(call.arguments.get(key, 0.0))
            for key in ("vx", "vy", "vyaw")
        }
        if any(not math.isfinite(value) for value in values.values()):
            return ToolResult(call.name, False, "set_velocity values must be finite")
        if abs(values["vx"]) > self.limits.max_vx:
            return ToolResult(call.name, False, "vx exceeds the configured safe limit")
        if abs(values["vy"]) > self.limits.max_vy:
            return ToolResult(call.name, False, "vy exceeds the configured safe limit")
        if abs(values["vyaw"]) > self.limits.max_vyaw:
            return ToolResult(call.name, False, "vyaw exceeds the configured safe limit")
        return ToolResult(
            call.name,
            True,
            f"Velocity approved: vx={values['vx']:.2f} vy={values['vy']:.2f} "
            f"vyaw={values['vyaw']:.2f}",
        )

    def engage_emergency_stop(self) -> None:
        self.emergency_stopped = True

    def clear_emergency_stop(self) -> None:
        self.emergency_stopped = False
