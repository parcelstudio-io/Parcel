from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .memory import ConversationMemory
from .models import AgentDecision, Pose, ToolCall
from .providers import LanguageModel
from .safety import SafetySupervisor


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
    ):
        self.poses = poses
        self.modules = modules
        self.pose_publisher = pose_publisher
        self.language_model = language_model
        self.stop_publisher = stop_publisher or (lambda: None)
        self.memory = memory or ConversationMemory()
        self.safety = SafetySupervisor(poses)

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

        pose_match = re.fullmatch(r"(?:do|pose|show) (?:the )?(.+?)(?: pose)?", text)
        if pose_match:
            pose_name = pose_match.group(1).replace(" ", "_")
            pose = self.poses.get(pose_name)
            if pose is None:
                return f"Unknown pose: {pose_name}"
            self.pose_publisher(pose)
            return f"Running {pose.name} pose"

        command, _, argument = text.partition(" ")
        for module in self.modules:
            if command in module.commands():
                response = module.handle(command, argument)
                if response is not None:
                    return response
        return "I did not understand that command"

    def _execute(self, decision: AgentDecision, transcript: str | None = None) -> str:
        if transcript:
            self.memory.add("user", transcript)
        failures = []
        for call in decision.tool_calls:
            result = self.safety.validate(call)
            self.memory.add("tool", result.message)
            if not result.accepted:
                failures.append(result.message)
                continue
            if call.name == "run_pose":
                self.pose_publisher(self.poses[call.arguments["name"]])
            elif call.name == "stop_motion":
                self.safety.engage_emergency_stop()
                self.stop_publisher()
            elif call.name == "get_status":
                status = self._module_command("status", "")
                if status:
                    self.memory.add("tool", status)
        reply = decision.reply or "Done."
        if failures:
            reply = f"I couldn't do that safely. {failures[0]}"
        self.memory.add("assistant", reply)
        return reply

    def _module_command(self, command: str, argument: str) -> str | None:
        for module in self.modules:
            if command in module.commands():
                return module.handle(command, argument)
        return None

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [
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
