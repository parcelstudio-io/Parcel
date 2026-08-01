from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .memory import ConversationMemory
from .models import AgentDecision, Pose, ToolCall, VelocityCommand
from .motion import MotionRouter
from .providers import LanguageModel
from .safety import SafetyLimits, SafetySupervisor


class VoiceAgent:
    """Maps a transcript to safe robot actions.

    Speech-to-text and text-to-speech are deliberately adapters: a local or cloud
    provider can be added without coupling it to motor control.
    """

    def __init__(
        self,
        poses: dict[str, Pose],
        modules: list[Any],
        pose_publisher: Callable[[Pose], None],
        *,
        language_model: LanguageModel | None = None,
        stop_publisher: Callable[[], None] | None = None,
        memory: ConversationMemory | None = None,
        motion: MotionRouter | None = None,
        safety_limits: SafetyLimits | None = None,
    ):
        self.poses = poses
        self.modules = modules
        self.pose_publisher = pose_publisher
        self.language_model = language_model
        self.stop_publisher = stop_publisher or (lambda: None)
        self.memory = memory or ConversationMemory()
        self.motion = motion
        self.safety = SafetySupervisor(poses, safety_limits)

    def handle_text(self, transcript: str) -> str:
        text = re.sub(r"\s+", " ", transcript.strip().lower())
        if text in {"stop", "emergency stop", "stop now"}:
            return self._execute(AgentDecision("Stopping.", (ToolCall("stop_motion"),)))

        if self.language_model is not None:
            try:
                decision = self.language_model.decide(
                    text, self.tool_definitions(), self.memory.recent()
                )
                return self._execute(decision, transcript=text)
            except (RuntimeError, TypeError, ValueError):
                # A model outage or malformed output must not remove basic commands.
                pass

        backend_match = re.fullmatch(r"use (sport|rl)(?: backend)?", text)
        if backend_match and self.motion is not None:
            name = backend_match.group(1)
            call = ToolCall("set_motion_backend", {"name": name})
            return self._execute(
                AgentDecision(f"Switching to the {name} backend.", (call,)),
                transcript=text,
            )

        walk = self._parse_walk(text)
        if walk is not None:
            if self.motion is None:
                return "Locomotion is not configured"
            call = ToolCall(
                "set_velocity",
                {"vx": walk.vx, "vy": walk.vy, "vyaw": walk.vyaw},
            )
            return self._execute(
                AgentDecision(self._walk_reply(walk), (call,)),
                transcript=text,
            )

        pose_match = re.fullmatch(r"(?:do|pose|show) (?:the )?(.+?)(?: pose)?", text)
        if pose_match:
            pose_name = pose_match.group(1).replace(" ", "_")
            pose = self.poses.get(pose_name)
            if pose is None:
                return f"Unknown pose: {pose_name}"
            if self.motion is not None:
                self.motion.stop()
            self.pose_publisher(pose)
            return f"Running {pose.name} pose"

        command, _, argument = text.partition(" ")
        for module in self.modules:
            if command in module.commands():
                response = module.handle(command, argument)
                if response is not None:
                    return response
        return "I did not understand that command"

    def _parse_walk(self, text: str) -> VelocityCommand | None:
        limits = self.safety.limits
        default_vx = min(0.3, limits.max_vx)
        default_yaw = min(0.4, limits.max_vyaw)
        patterns: list[tuple[str, VelocityCommand]] = [
            (r"(?:walk|go|move) forward", VelocityCommand(vx=default_vx)),
            (r"(?:walk|go|move)(?: backward| back)", VelocityCommand(vx=-default_vx)),
            (r"turn left", VelocityCommand(vyaw=default_yaw)),
            (r"turn right", VelocityCommand(vyaw=-default_yaw)),
            (r"^walk$", VelocityCommand(vx=default_vx)),
        ]
        for pattern, command in patterns:
            if re.fullmatch(pattern, text):
                return command
        return None

    @staticmethod
    def _walk_reply(command: VelocityCommand) -> str:
        if abs(command.vyaw) > abs(command.vx) and abs(command.vyaw) > abs(command.vy):
            direction = "left" if command.vyaw > 0 else "right"
            return f"Turning {direction}."
        if command.vx < 0:
            return "Walking backward."
        return "Walking forward."

    def _execute(self, decision: AgentDecision, transcript: str | None = None) -> str:
        if transcript:
            self.memory.add("user", transcript)
        failures = []
        detail = None
        for call in decision.tool_calls:
            result = self.safety.validate(call)
            self.memory.add("tool", result.message)
            if not result.accepted:
                failures.append(result.message)
                continue
            if call.name == "run_pose":
                if self.motion is not None:
                    self.motion.stop()
                self.pose_publisher(self.poses[call.arguments["name"]])
            elif call.name == "set_velocity":
                if self.motion is None:
                    failures.append("Locomotion is not configured")
                    continue
                command = VelocityCommand(
                    vx=float(call.arguments.get("vx", 0.0)),
                    vy=float(call.arguments.get("vy", 0.0)),
                    vyaw=float(call.arguments.get("vyaw", 0.0)),
                )
                detail = self.motion.walk(command)
            elif call.name == "set_motion_backend":
                if self.motion is None:
                    failures.append("Locomotion is not configured")
                    continue
                detail = self.motion.set_backend(str(call.arguments["name"]))
            elif call.name == "stop_motion":
                self.safety.engage_emergency_stop()
                if self.motion is not None:
                    self.motion.stop()
                self.stop_publisher()
            elif call.name == "get_status":
                status = self._module_command("status", "")
                if self.motion is not None:
                    motion_status = self.motion.status()
                    status = f"{status}; {motion_status}" if status else motion_status
                if status:
                    self.memory.add("tool", status)
                    detail = status
        reply = decision.reply or "Done."
        if failures:
            reply = f"I couldn't do that safely. {failures[0]}"
        elif detail and decision.reply in {None, "", "Done."}:
            reply = detail
        self.memory.add("assistant", reply)
        return reply

    def _module_command(self, command: str, argument: str) -> str | None:
        for module in self.modules:
            if command in module.commands():
                return module.handle(command, argument)
        return None

    def tool_definitions(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = [
            {
                "name": "run_pose",
                "description": "Run one configured pose.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "enum": sorted(self.poses)}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "set_velocity",
                "description": "Request body-frame walking velocity via the active motion backend.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "vx": {"type": "number"},
                        "vy": {"type": "number"},
                        "vyaw": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "set_motion_backend",
                "description": "Switch the exclusive locomotion backend.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": ["sport", "rl"]},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "stop_motion",
                "description": "Immediately request that robot motion stop.",
                "parameters": {"type": "object", "additionalProperties": False},
            },
            {
                "name": "get_status",
                "description": "Read the current robot status.",
                "parameters": {"type": "object", "additionalProperties": False},
            },
        ]
        return tools
