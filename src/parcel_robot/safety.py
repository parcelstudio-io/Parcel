from __future__ import annotations

import math
from dataclasses import dataclass, fields

from .models import Pose, ToolCall, ToolResult


class SafetyLimitError(ValueError):
    """A configured safety limit that cannot function as a clamp.

    Subclasses :class:`ValueError` so existing loaders and call sites that
    already treat a bad config as a ``ValueError`` keep working; the distinct
    type exists so the fail-closed doctrine test can name what it caught.
    """


def is_usable_limit(value: object) -> bool:
    """True when ``value`` can serve as a magnitude clamp.

    A clamp is a comparison, and a comparison against a non-number is not a
    *weaker* clamp — it is NO clamp. ``abs(v) > float("nan")`` is False for
    every v, so a NaN limit admits any velocity at all; ``inf`` admits any
    finite one; zero and negatives are typos, never intent. Everything that
    compares against a configured limit routes through here so that the
    answer is the same at every enforcement site.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and number > 0.0


def validated_limit(value: object, name: str) -> float:
    """Return ``value`` as a usable clamp, or refuse with a named error."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SafetyLimitError(
            f"safety limit {name} must be a number, got {value!r}. "
            f"A limit that is not a number is not a clamp."
        )
    number = float(value)
    if not math.isfinite(number):
        raise SafetyLimitError(
            f"safety limit {name} must be finite, got {number}. "
            f"A non-finite limit does not loosen the clamp, it removes it: "
            f"abs(v) > nan is False for every v, so the axis becomes unbounded."
        )
    if number <= 0.0:
        raise SafetyLimitError(
            f"safety limit {name} must be greater than zero, got {number}. "
            f"Use a small positive value to move slowly; a zero or negative "
            f"clamp reads as a typo, not as an intent to hold still."
        )
    return number


@dataclass(frozen=True)
class SafetyLimits:
    """The clamp thresholds both enforcement sites compare against.

    Every field is validated on construction (card R23). This is the boundary
    the operator ``--config`` path crosses, and it is the cheapest place in
    the system to refuse: past here a bad number is not a bad number any more,
    it is a missing safety check that nothing reports.
    """

    max_pose_duration: float = 10.0
    max_abs_joint_position: float = 3.2
    # 2026-08-04: raised from (0.6, 0.4, 1.0) — the dog read as sluggish in
    # the simulator. Go2 hardware trots 1.0-1.5 m/s; these remain clamps, not
    # commands, and every dispatch still passes the collision gate + TTC.
    max_vx: float = 1.0
    max_vy: float = 0.5
    max_vyaw: float = 1.5

    def __post_init__(self) -> None:
        for item in fields(self):
            validated_limit(getattr(self, item.name), item.name)


# Neutral backend names; "sport" is a deprecated vendor-branded alias for
# "vendor" kept so existing voice habits keep working.
ALLOWED_BACKENDS = frozenset({"vendor", "rl"})
_BACKEND_ALIASES = {"sport": "vendor"}


class SafetySupervisor:
    """Fail-closed validation between probabilistic decisions and robot actions."""

    def __init__(
        self,
        poses: dict[str, Pose],
        limits: SafetyLimits | None = None,
        skill_ids: list[str] | None = None,
        information_tools: tuple[str, ...] = (),
    ):
        self.poses = poses
        self.limits = limits or SafetyLimits()
        self.skill_ids = set(skill_ids or poses)
        # Read-only conversation tools admitted by exact name. They must
        # never produce motion; everything not listed stays fail-closed.
        self.information_tools = frozenset(information_tools)
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
        if call.name == "run_spatial_behavior":
            return self._validate_spatial_behavior(call)
        if call.name in self.information_tools:
            return ToolResult(call.name, True, f"Information tool approved: {call.name}")
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
            # Card R23: the same fail-closed comparison the velocity axes use.
            # ``0 < d <= nan`` already refuses, but ``abs(j) > nan`` does not,
            # so the joint bound needs the explicit usability check.
            for limit_name in ("max_pose_duration", "max_abs_joint_position"):
                limit = getattr(self.limits, limit_name, None)
                if not is_usable_limit(limit):
                    return ToolResult(
                        call.name,
                        False,
                        f"{limit_name} is not a usable clamp ({limit!r}); motion refused",
                    )
            if not 0 < pose.duration <= float(self.limits.max_pose_duration):
                return ToolResult(call.name, False, "Pose duration is outside the safe range")
            if not pose.joints:
                return ToolResult(call.name, False, "Pose contains no joints")
            for value in pose.joints.values():
                if not math.isfinite(value) or abs(value) > float(
                    self.limits.max_abs_joint_position
                ):
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
        name = _BACKEND_ALIASES.get(name, name)
        if name not in ALLOWED_BACKENDS:
            return ToolResult(call.name, False, f"Unknown motion backend: {name}")
        return ToolResult(call.name, True, f"Motion backend approved: {name}")

    def _validate_behavior(self, call: ToolCall) -> ToolResult:
        if self.emergency_stopped:
            return ToolResult(call.name, False, "Motion is disabled by emergency stop")
        if set(call.arguments) != {"mode"} or not isinstance(call.arguments.get("mode"), str):
            return ToolResult(call.name, False, "set_behavior requires only a string mode")
        mode = call.arguments["mode"]
        if mode not in {"follow", "follow_behind", "stay"}:
            return ToolResult(call.name, False, f"Unknown behavior: {mode}")
        return ToolResult(call.name, True, f"Behavior approved: {mode}")

    def _validate_velocity(self, call: ToolCall) -> ToolResult:
        if self.emergency_stopped:
            return ToolResult(call.name, False, "Motion is disabled by emergency stop")
        allowed = {"vx", "vy", "vyaw"}
        if not set(call.arguments).issubset(allowed):
            return ToolResult(call.name, False, "set_velocity only accepts vx, vy, vyaw")
        values = {key: float(call.arguments.get(key, 0.0)) for key in ("vx", "vy", "vyaw")}
        if any(not math.isfinite(value) for value in values.values()):
            return ToolResult(call.name, False, "set_velocity values must be finite")
        # Card R23, defense in depth. ``SafetyLimits`` refuses an unusable
        # clamp at construction, but ``self.limits`` is an injected attribute:
        # a caller can rebind it to any object after the fact. Re-check here so
        # that a bypassed loader cannot turn this comparison into a rubber
        # stamp — `abs(v) > nan` is False, which reads as "approved".
        # Every clamp is checked for usability BEFORE any magnitude test, so a
        # broken limit on one axis cannot hide behind an ordinary exceedance on
        # another.
        for limit_name in ("max_vx", "max_vy", "max_vyaw"):
            limit = getattr(self.limits, limit_name, None)
            if not is_usable_limit(limit):
                return ToolResult(
                    call.name,
                    False,
                    f"{limit_name} is not a usable clamp ({limit!r}); motion refused",
                )
        for axis in ("vx", "vy", "vyaw"):
            if abs(values[axis]) > float(getattr(self.limits, f"max_{axis}")):
                return ToolResult(call.name, False, f"{axis} exceeds the configured safe limit")
        return ToolResult(
            call.name,
            True,
            f"Velocity approved: vx={values['vx']:.2f} vy={values['vy']:.2f} "
            f"vyaw={values['vyaw']:.2f}",
        )

    def _validate_spatial_behavior(self, call: ToolCall) -> ToolResult:
        if self.emergency_stopped:
            return ToolResult(call.name, False, "Motion is disabled by emergency stop")
        behavior = call.arguments.get("behavior")
        if behavior == "move_steps":
            if set(call.arguments) != {"behavior", "direction", "steps"}:
                return ToolResult(
                    call.name,
                    False,
                    "move_steps requires only behavior, direction, and steps",
                )
            if call.arguments.get("direction") not in {
                "forward",
                "backward",
                "away_from_owner",
            }:
                return ToolResult(call.name, False, "move_steps direction is not allowed")
            steps = call.arguments.get("steps")
            if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 12:
                return ToolResult(call.name, False, "steps must be an integer between 1 and 12")
            return ToolResult(call.name, True, "Bounded step behavior approved")
        if behavior == "orbit_owner":
            allowed = {"behavior", "direction", "size", "revolutions"}
            if set(call.arguments) != allowed:
                return ToolResult(
                    call.name,
                    False,
                    "orbit_owner requires behavior, direction, size, and revolutions",
                )
            if call.arguments.get("direction") not in {"clockwise", "counterclockwise"}:
                return ToolResult(call.name, False, "orbit direction is not allowed")
            if call.arguments.get("size") not in {"small", "normal", "wide"}:
                return ToolResult(call.name, False, "orbit size is not allowed")
            revolutions = call.arguments.get("revolutions")
            if (
                isinstance(revolutions, bool)
                or not isinstance(revolutions, (int, float))
                or not math.isfinite(float(revolutions))
                or not 0.25 <= float(revolutions) <= 1.0
            ):
                return ToolResult(
                    call.name,
                    False,
                    "orbit revolutions must be between 0.25 and 1.0",
                )
            return ToolResult(call.name, True, "Bounded owner orbit approved")
        return ToolResult(call.name, False, "Unknown spatial behavior")

    def engage_emergency_stop(self) -> None:
        self.emergency_stopped = True

    def clear_emergency_stop(self) -> None:
        self.emergency_stopped = False
