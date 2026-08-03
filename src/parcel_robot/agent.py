from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .memory import ConversationMemory
from .models import (
    ActionProposal,
    AffectEstimate,
    AgentDecision,
    Pose,
    ToolCall,
    VelocityCommand,
)
from .motion import MotionRouter
from .providers import LanguageModel
from .safety import SafetyLimits, SafetySupervisor

EMERGENCY_STOP_PHRASES = frozenset({"stop", "emergency stop", "stop now"})
CommitGuard = Callable[[Callable[[], str]], str]


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
        behavior_publisher: Callable[[str], str] | None = None,
        navigation_publisher: Callable[[str], str] | None = None,
        action_proposal_publisher: Callable[[ActionProposal], str] | None = None,
        system_prompt_provider: Callable[[], str] | None = None,
        affect_minimum_confidence: float = 0.75,
        affect_actions: dict[str, str] | None = None,
        dog=None,
    ):
        self.poses = poses
        self.modules = modules
        self.pose_publisher = pose_publisher
        self.language_model = language_model
        self.stop_publisher = stop_publisher or (lambda: None)
        self.memory = memory or ConversationMemory()
        self.motion = motion
        self.behavior_publisher = behavior_publisher
        self.navigation_publisher = navigation_publisher
        self.action_proposal_publisher = action_proposal_publisher
        self.system_prompt_provider = system_prompt_provider
        self.affect_minimum_confidence = affect_minimum_confidence
        self.affect_actions = dict(affect_actions or {"sad": "play_bow", "happy": "paw_wave"})
        self.dog = dog
        self.safety = SafetySupervisor(poses, safety_limits, skill_ids=self._skill_ids())

    def _skill_ids(self) -> list[str]:
        if self.dog is None:
            return sorted(self.poses)
        return self.dog.catalog.ids()

    def _bounded_action_skill_ids(self) -> list[str]:
        """Skills that may be scheduled by the semantic activity coordinator."""

        if self.dog is None:
            return sorted(self.poses)
        return [
            skill.id for skill in self.dog.catalog.list() if skill.kind in {"pose", "trajectory"}
        ]

    def _is_social_trajectory(self, skill_name: str) -> bool:
        if self.dog is None:
            return False
        try:
            skill = self.dog.catalog.get(skill_name)
        except KeyError:
            return False
        return skill.kind == "trajectory" and "social" in skill.tags

    def handle_text(self, transcript: str) -> str:
        return self._handle_text(transcript, None)

    def handle_text_guarded(self, transcript: str, commit: CommitGuard) -> str:
        """Plan freely, then atomically commit only if the voice turn is current."""

        return self._handle_text(transcript, commit)

    def _handle_text(self, transcript: str, commit: CommitGuard | None) -> str:
        text = re.sub(r"\s+", " ", transcript.strip().lower())
        if text in EMERGENCY_STOP_PHRASES:
            return self._execute(AgentDecision("Stopping.", (ToolCall("stop_motion"),)))

        if text in {"follow", "follow me", "come with me", "heel"}:
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(
                        "I will follow you.",
                        (ToolCall("set_behavior", {"mode": "follow"}),),
                    ),
                    transcript=text,
                ),
            )
        if text in {"stay", "wait", "wait here", "hold position"}:
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(
                        "I will stay here.",
                        (ToolCall("set_behavior", {"mode": "stay"}),),
                    ),
                    transcript=text,
                ),
            )

        if self.language_model is not None:
            try:
                set_prompt = getattr(self.language_model, "set_system_prompt", None)
                if callable(set_prompt) and self.system_prompt_provider is not None:
                    set_prompt(self.system_prompt_provider())
                decision = self.language_model.decide(
                    text, self.tool_definitions(), self.memory.recent()
                )
                return self._commit(
                    commit,
                    lambda: self._execute(decision, transcript=text),
                )
            except (RuntimeError, TypeError, ValueError):
                pass

        affect = self._detect_explicit_affect(text)
        if affect is not None:
            label, reply = affect
            skill_name = self.affect_actions.get(label)
            proposal = (
                ActionProposal(
                    kind="skill",
                    name=skill_name,
                    trigger="inferred_affect",
                    timing_preference="when_safe",
                    interruption_request="none",
                    reason=f"deterministic {label} transcript cue",
                )
                if skill_name is not None
                and skill_name == self.affect_actions.get(label)
                and self._is_social_trajectory(skill_name)
                else None
            )
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(
                        reply,
                        intent="conversation",
                        affect=AffectEstimate(label, 1.0),
                        next_action=proposal,
                    ),
                    transcript=text,
                ),
            )

        backend_match = re.fullmatch(r"use (sport|rl)(?: backend)?", text)
        if backend_match and self.motion is not None:
            name = backend_match.group(1)
            call = ToolCall("set_motion_backend", {"name": name})
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(f"Switching to the {name} backend.", (call,)),
                    transcript=text,
                ),
            )

        walk = self._parse_walk(text)
        if walk is not None:
            if self.dog is not None:
                skill = "walk_forward"
                if walk.vx < 0:
                    skill = "walk_backward"
                elif abs(walk.vyaw) > abs(walk.vx):
                    skill = "turn_left" if walk.vyaw > 0 else "turn_right"
                return self._commit(
                    commit,
                    lambda: self._execute_walk_skill(skill, walk),
                )
            if self.motion is None:
                return "Locomotion is not configured"
            call = ToolCall(
                "set_velocity",
                {"vx": walk.vx, "vy": walk.vy, "vyaw": walk.vyaw},
            )
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(self._walk_reply(walk), (call,)),
                    transcript=text,
                ),
            )

        nav_directive = self._parse_navigate(text)
        if nav_directive is not None and self.dog is not None:
            return self._commit(
                commit,
                lambda: self._execute_navigation(nav_directive),
            )

        skill_match = re.fullmatch(
            r"(?:do|pose|show|run|perform) (?:the )?(.+?)(?: pose| skill| action)?",
            text,
        )
        if skill_match:
            skill_name = skill_match.group(1).replace(" ", "_")
            if skill_name not in self._skill_ids() and skill_name not in self.poses:
                return f"Unknown pose: {skill_name}"
            return self._commit(
                commit,
                lambda: self._execute_named_skill(skill_name),
            )

        if self.dog is not None:
            bare = text.replace(" ", "_")
            if bare in self.dog.catalog.ids():
                return self._commit(
                    commit,
                    lambda: self._execute_named_skill(bare),
                )

        command, _, argument = text.partition(" ")
        for module in self.modules:
            if command in module.commands():
                return self._commit(
                    commit,
                    lambda module=module: (
                        module.handle(command, argument) or "I did not understand that command"
                    ),
                )
        return "I did not understand that command"

    @staticmethod
    def _commit(commit: CommitGuard | None, action: Callable[[], str]) -> str:
        return action() if commit is None else commit(action)

    def _execute_walk_skill(self, skill: str, walk: VelocityCommand) -> str:
        assert self.dog is not None
        result = self.dog.execute(skill, vx=walk.vx, vy=walk.vy, vyaw=walk.vyaw)
        return self._walk_reply(walk) if result.accepted else result.message

    def _execute_navigation(self, directive: str) -> str:
        assert self.dog is not None
        if self.navigation_publisher is not None:
            try:
                return self.navigation_publisher(directive)
            except (LookupError, RuntimeError, ValueError) as error:
                return f"I couldn't navigate there. {error}"
        try:
            mission, cmd = self.dog.navigate(directive)
        except (LookupError, RuntimeError, ValueError) as error:
            return f"I couldn't navigate there. {error}"
        place = mission.goal.label or mission.goal.poi_id
        if cmd.stop:
            return f"Arrived at {place}."
        return f"Navigating to {place} (vx={cmd.vx:.2f}, vyaw={cmd.vyaw:.2f}; {cmd.note})."

    def _execute_named_skill(self, skill_name: str) -> str:
        if (
            self.action_proposal_publisher is not None
            and skill_name in self._bounded_action_skill_ids()
        ):
            return self.action_proposal_publisher(
                ActionProposal(
                    kind="skill",
                    name=skill_name,
                    trigger="explicit_command",
                    timing_preference="now",
                    interruption_request="safe_checkpoint",
                    reason="explicit owner skill request",
                )
            )
        if self.dog is not None and skill_name in self.dog.catalog.ids():
            result = self.dog.execute(skill_name)
            return (
                f"Running {skill_name}"
                if result.accepted
                else f"I couldn't do that safely. {result.message}"
            )
        pose = self.poses[skill_name]
        if self.motion is not None:
            self.motion.stop()
        self.pose_publisher(pose)
        return f"Running {pose.name} pose"

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
    def _parse_navigate(text: str) -> str | None:
        """Extract destination phrases like 'go to the coffee shop at 42nd street'."""
        patterns = [
            r"(?:i want you to |please )?(?:go|navigate|walk|take me) to (.+)",
            r"(?:head|drive) to (.+)",
        ]
        for pattern in patterns:
            match = re.fullmatch(pattern, text)
            if match:
                dest = match.group(1).strip(" .!")
                if dest and dest not in {"forward", "backward", "back", "left", "right"}:
                    return dest
        return None

    @staticmethod
    def _walk_reply(command: VelocityCommand) -> str:
        if abs(command.vyaw) > abs(command.vx) and abs(command.vyaw) > abs(command.vy):
            direction = "left" if command.vyaw > 0 else "right"
            return f"Turning {direction}."
        if command.vx < 0:
            return "Walking backward."
        return "Walking forward."

    @staticmethod
    def _detect_explicit_affect(text: str) -> tuple[str, str] | None:
        sad = re.search(
            r"\b(?:i am|i'm|i feel|i'm feeling|i am feeling)\s+"
            r"(?:really\s+|very\s+)?(?:sad|down|upset|unhappy)\b",
            text,
        )
        if sad:
            return "sad", "I'm here with you."
        happy = re.search(
            r"\b(?:i am|i'm|i feel|i'm feeling|i am feeling)\s+"
            r"(?:really\s+|very\s+)?(?:happy|great|excited|joyful)\b",
            text,
        )
        if happy:
            return "happy", "I'm happy with you!"
        return None

    def _execute(self, decision: AgentDecision, transcript: str | None = None) -> str:
        if transcript:
            self.memory.add("user", transcript)
        validations = [(call, self.safety.validate(call)) for call in decision.tool_calls]
        for _, result in validations:
            self.memory.add("tool", result.message)
        failures = [result.message for _, result in validations if not result.accepted]
        if self.action_proposal_publisher is not None:
            bounded_skills = set(self._bounded_action_skill_ids())
            for call in decision.tool_calls:
                name = call.arguments.get("name")
                if call.name == "run_pose" and (
                    not isinstance(name, str) or name not in self.poses
                ):
                    failures.append("run_pose requires a configured pose skill")
                elif call.name == "run_skill" and (
                    not isinstance(name, str) or name not in bounded_skills
                ):
                    failures.append(
                        "Activity-coordinated skills require a bounded pose or trajectory"
                    )
        physical_tools = {
            "run_pose",
            "run_skill",
            "set_velocity",
            "navigate",
            "set_behavior",
            "stop_motion",
        }
        physical_count = sum(call.name in physical_tools for call in decision.tool_calls)
        physical_count += decision.next_action is not None
        if physical_count > 1:
            failures.append("A decision can contain only one motion-producing action")
        if decision.next_action is not None:
            proposal_error = self._validate_action_proposal(decision)
            if proposal_error:
                failures.append(proposal_error)
        if failures:
            reply = f"I couldn't do that safely. {failures[0]}"
            self.memory.add("assistant", reply)
            return reply

        detail = None
        for call, _ in validations:
            if call.name == "run_pose":
                name = call.arguments["name"]
                if self.action_proposal_publisher is not None:
                    detail = self.action_proposal_publisher(
                        ActionProposal(
                            kind="skill",
                            name=str(name),
                            trigger="explicit_command",
                            timing_preference="now",
                            interruption_request="safe_checkpoint",
                            reason="model-recognized explicit pose request",
                        )
                    )
                elif self.dog is not None and name in self.dog.catalog.ids():
                    detail = self.dog.execute(name).message
                else:
                    if self.motion is not None:
                        self.motion.stop()
                    self.pose_publisher(self.poses[name])
            elif call.name == "run_skill":
                if self.dog is None:
                    failures.append("Skill catalog is not configured")
                    continue
                name = str(call.arguments["name"])
                if self.action_proposal_publisher is not None:
                    detail = self.action_proposal_publisher(
                        ActionProposal(
                            kind="skill",
                            name=name,
                            trigger="explicit_command",
                            timing_preference="now",
                            interruption_request="safe_checkpoint",
                            reason="model-recognized explicit skill request",
                        )
                    )
                else:
                    detail = self.dog.execute(name).message
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
            elif call.name == "navigate":
                if self.dog is None:
                    failures.append("Navigation requires the Dog API")
                    continue
                directive = str(call.arguments.get("directive", "")).strip()
                if not directive:
                    failures.append("navigate requires a directive")
                    continue
                if self.navigation_publisher is not None:
                    try:
                        detail = self.navigation_publisher(directive)
                    except (LookupError, RuntimeError, ValueError) as error:
                        failures.append(str(error))
                else:
                    try:
                        mission, cmd = self.dog.navigate(directive)
                    except (LookupError, RuntimeError, ValueError) as error:
                        failures.append(str(error))
                        continue
                    place = mission.goal.label or mission.goal.poi_id
                    detail = (
                        f"Arrived at {place}."
                        if cmd.stop
                        else f"Navigating to {place} (vx={cmd.vx:.2f})."
                    )
            elif call.name == "set_behavior":
                if self.behavior_publisher is None:
                    failures.append("Behavior control is not configured")
                    continue
                detail = self.behavior_publisher(str(call.arguments["mode"]))
            elif call.name == "stop_motion":
                self.safety.engage_emergency_stop()
                if self.dog is not None:
                    self.dog.stop()
                elif self.motion is not None:
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
        if decision.next_action is not None and not failures:
            assert self.action_proposal_publisher is not None
            detail = self.action_proposal_publisher(decision.next_action)
        reply = decision.reply or "Done."
        if failures:
            reply = f"I couldn't do that safely. {failures[0]}"
        elif detail and detail.startswith("Deferred:"):
            reply = f"{reply} I'll wait until the current task is finished before moving."
        elif detail and detail.startswith("Rejected:"):
            reply = f"{reply} I won't perform that gesture right now."
        elif detail and decision.reply in {None, "", "Done."}:
            reply = detail
        self.memory.add("assistant", reply)
        return reply

    def _validate_action_proposal(self, decision: AgentDecision) -> str | None:
        proposal = decision.next_action
        if proposal is None:
            return None
        if self.action_proposal_publisher is None:
            return "Semantic action proposals are not configured"
        if proposal.kind != "skill" or proposal.name not in self._skill_ids():
            return f"Unknown proposed skill: {proposal.name}"
        if proposal.trigger == "inferred_affect":
            if decision.affect is None:
                return "An inferred-affect action requires an affect estimate"
            if decision.affect.confidence < self.affect_minimum_confidence:
                return "Affect confidence is below the configured threshold"
            expected = self.affect_actions.get(decision.affect.label)
            if expected is None or proposal.name != expected:
                return "Inferred-affect action does not match the active personality"
            if not self._is_social_trajectory(proposal.name):
                return "Inferred-affect actions require a social trajectory skill"
        elif proposal.name not in self._bounded_action_skill_ids():
            return "Explicit action proposals require a bounded pose or trajectory skill"
        return None

    def configure_personality(self, affect_actions: dict[str, str]) -> None:
        self.affect_actions = dict(affect_actions)

    def _module_command(self, command: str, argument: str) -> str | None:
        for module in self.modules:
            if command in module.commands():
                return module.handle(command, argument)
        return None

    def tool_definitions(self) -> list[dict[str, Any]]:
        coordinated = self.action_proposal_publisher is not None
        skill_enum = self._bounded_action_skill_ids() if coordinated else self._skill_ids()
        run_skill_description = (
            "Run one bounded configured pose or trajectory through the activity coordinator."
            if coordinated
            else "Run any catalog skill (pose, trajectory, gait, velocity)."
        )
        tools: list[dict[str, Any]] = [
            {
                "name": "run_pose",
                "description": "Run one configured pose skill.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": sorted(self.poses) or skill_enum}
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "run_skill",
                "description": run_skill_description,
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "enum": skill_enum}},
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
                "name": "navigate",
                "description": (
                    "Navigate to a place from a natural-language directive "
                    "(e.g. coffee shop at 42nd street)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"directive": {"type": "string"}},
                    "required": ["directive"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "set_behavior",
                "description": "Start owner following or hold the current position.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["follow", "stay"]},
                    },
                    "required": ["mode"],
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
