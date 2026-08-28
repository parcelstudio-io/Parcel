from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..brain.contracts import IntentFrame, ObservationSnapshot, PlanIR
from ..brain.plan_sketch import PlanSketch
from ..brain.router import (
    DeterministicIntentRouter,
    explicit_affect_from_text,
    physical_cue_present,
    split_compound_clauses,
)
from ..brain.runtime_adapter import bind_plan_context, contextual_planner_schema
from ..brain.validator import PlanValidationError
from ..capabilities.commissioning_lifecycle import (
    CommissioningStateProviderV1,
    validate_commissioning_lifecycle,
)
from ..capabilities.manifest import (
    CapabilityManifestV1,
    DeploymentTargetV1,
    TrustedCommissioningAuthenticatorV1,
)
from ..memory.conversation import ConversationMemory
from ..models import (
    ActionProposal,
    AffectEstimate,
    AgentDecision,
    Pose,
    SpatialIntent,
    ToolCall,
    VelocityCommand,
)
from ..motion.router import MotionRouter
from ..navigation.goals import PlaceAdmission, navigation_directive_from_text
from ..navigation.spatial import parse_spatial_intent, spatial_intent_from_arguments
from ..providers import LanguageModel
from ..safety import SafetyLimits, SafetySupervisor
from ..skills.capability_manifest import validate_motion_manifest
from .amendment import strip_amend_prefix
from .closed_intents import ClosedIntent, closed_intent_phrases, parse_closed_intent
from .dialogue_lane import conversation_tool_definitions, dialogue_act_from_text
from .executive_caps import CapDirective, resolve_cap
from .local_plans import (
    sketch_come,
    sketch_follow,
    sketch_hold,
    sketch_navigate,
    sketch_spatial,
)
from .scene_reference import (
    clarification_for,
    dangling_reference,
    resolve_pending_reference,
    scene_class_mentioned,
)

#: Phrases that stop the robot on the fastest available path. Derived from the
#: closed-intent parser so there is exactly ONE stop grammar: this set used to
#: be a literal that omitted "halt", which the parser *did* recognize as STOP —
#: and because `_handle_text` deliberately skips STOP in the closed-intent
#: handler, `handle_text("halt")` answered "I did not understand that command"
#: and stopped nothing (U33, measured 2026-08-07 on the product path).
EMERGENCY_STOP_PHRASES = closed_intent_phrases(ClosedIntent.STOP)
MOTION_TOOLS = frozenset(
    {
        "run_pose",
        "run_skill",
        "set_velocity",
        "set_motion_backend",
        "navigate",
        "set_behavior",
        "run_spatial_behavior",
        "stop_motion",
    }
)
MODEL_FORBIDDEN_TOOLS = frozenset({"set_velocity", "set_motion_backend"})
CommitGuard = Callable[[Callable[[], str]], str]
PlanPublisher = Callable[[PlanIR, IntentFrame, str], str]
PlannerOutputAdapter = Callable[[object, IntentFrame, ObservationSnapshot], PlanIR]
ClosedIntentHandler = Callable[[ClosedIntent, CapDirective], str]

# Exact conversation route -> commissioned navigation-mode bindings. These are
# semantic declarations, not actuator permissions: successful admission still
# crosses the existing planner/runtime/safety boundaries.
_BEHAVIOR_CAPABILITY = {
    "follow": "follow_owner",
    "follow_behind": "follow_owner",
}
_SPATIAL_CAPABILITY = {
    "move_steps": "move_steps",
    "orbit_owner": "orbit_owner",
}
_NAVIGATION_CAPABILITY = "navigate"


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
        planner_model: LanguageModel | None = None,
        stop_publisher: Callable[[], None] | None = None,
        memory: ConversationMemory | None = None,
        motion: MotionRouter | None = None,
        safety_limits: SafetyLimits | None = None,
        behavior_publisher: Callable[[str], str] | None = None,
        navigation_publisher: Callable[[str], str] | None = None,
        spatial_behavior_publisher: Callable[[SpatialIntent], str] | None = None,
        action_proposal_publisher: Callable[[ActionProposal], str] | None = None,
        system_prompt_provider: Callable[[], str] | None = None,
        affect_minimum_confidence: float = 0.75,
        affect_actions: dict[str, str] | None = None,
        conversation_history_messages: int = 16,
        intent_router: DeterministicIntentRouter | None = None,
        planning_context_provider: Callable[[], ObservationSnapshot] | None = None,
        plan_publisher: PlanPublisher | None = None,
        planner_system_prompt_provider: Callable[[], str] | None = None,
        planner_schema_provider: Callable[[], dict[str, Any]] | None = None,
        planner_skill_contracts_provider: Callable[[], dict[str, object]] | None = None,
        planner_output_adapter: PlannerOutputAdapter | None = None,
        dog=None,
        capability_manifest: CapabilityManifestV1 | None = None,
        deployment_target: DeploymentTargetV1 | None = None,
        conversation_motion_authorized: bool = False,
        commissioning_authenticator: TrustedCommissioningAuthenticatorV1 | None = None,
        commissioning_state_provider: CommissioningStateProviderV1 | None = None,
        commissioning_clock_ns: Callable[[], int] = time.monotonic_ns,
        info_tools=None,
        slow_path_hook: Callable[[str], None] | None = None,
        closed_intent_handler: ClosedIntentHandler | None = None,
        pace_scale_provider: Callable[[], float] | None = None,
        place_admission: Callable[[str], PlaceAdmission] | None = None,
    ):
        if not 1 <= conversation_history_messages <= 64:
            raise ValueError("conversation history messages must be between 1 and 64")
        self.poses = poses
        self.modules = modules
        self.pose_publisher = pose_publisher
        self.language_model = language_model
        # Keep independent provider boundaries without forcing a two-model
        # deployment. The default shares the proven resident model; a
        # challenger can replace only planning while both lanes still receive
        # the exact transcript rather than another model's paraphrase.
        self.planner_model = planner_model if planner_model is not None else language_model
        self.stop_publisher = stop_publisher or (lambda: None)
        self.memory = memory or ConversationMemory()
        self.motion = motion
        self.behavior_publisher = behavior_publisher
        self.navigation_publisher = navigation_publisher
        self.spatial_behavior_publisher = spatial_behavior_publisher
        self.action_proposal_publisher = action_proposal_publisher
        self.system_prompt_provider = system_prompt_provider
        self.affect_minimum_confidence = affect_minimum_confidence
        self.affect_actions = dict(
            affect_actions
            or {
                "sad": "comfort_bow",
                "happy": "happy_wiggle",
                "excited": "excited_paw_taps",
            }
        )
        self.conversation_history_messages = conversation_history_messages
        self.dog = dog
        self.capability_manifest = capability_manifest
        self.deployment_target = deployment_target
        if type(conversation_motion_authorized) is not bool:
            raise TypeError("conversation_motion_authorized must be a boolean")
        self.conversation_motion_authorized = conversation_motion_authorized
        self.commissioning_authenticator = commissioning_authenticator
        self.commissioning_state_provider = commissioning_state_provider
        self.commissioning_clock_ns = commissioning_clock_ns
        if self.conversation_motion_authorized and (
            deployment_target is None or deployment_target.environment != "simulation"
        ):
            raise ValueError(
                "conversation_motion_authorized is restricted to an attested simulation"
            )
        if capability_manifest is not None:
            capability_manifest.assert_authenticated_commissioning(
                commissioning_authenticator
            )
            if deployment_target is None or deployment_target != capability_manifest.deployment_target:
                raise ValueError(
                    "capability manifest deployment target does not match this adapter"
                )
            validate_commissioning_lifecycle(
                capability_manifest.commissioning_lifecycle,
                state_provider=commissioning_state_provider,
                now_monotonic_ns=commissioning_clock_ns(),
            )
            if dog is None and (capability_manifest.gestures or capability_manifest.poses):
                raise ValueError(
                    "an embodied capability manifest requires a live skill catalog"
                )
            if dog is not None:
                validate_motion_manifest(capability_manifest, dog.catalog)
        self.intent_router = intent_router or DeterministicIntentRouter(self._skill_ids())
        self.planning_context_provider = planning_context_provider
        self.plan_publisher = plan_publisher
        self.planner_system_prompt_provider = planner_system_prompt_provider
        self.planner_schema_provider = planner_schema_provider
        self.planner_skill_contracts_provider = planner_skill_contracts_provider
        self.planner_output_adapter = planner_output_adapter
        self.closed_intent_handler = closed_intent_handler
        self.pace_scale_provider = pace_scale_provider
        #: Card R20. "May this directive become a goal?", answered by the host
        #: against the live place vocabulary. ``None`` — the default, and what
        #: every agent built without a runtime gets — means no vocabulary is
        #: reachable, and the pre-R20 behaviour stands: the router decides and
        #: an unresolvable place fails honestly at grounding.
        self.place_admission = place_admission
        self._turn_sequence = 0
        self.last_intent_frame: IntentFrame | None = None
        self.last_brain_metrics: dict[str, object] = {}
        self.last_reasoning_source = "deterministic"
        self.last_reasoning_error: str | None = None
        self.last_reasoning_guard: str | None = None
        self.last_dialogue_act = None
        self.last_closed_intent: ClosedIntent | None = None
        #: Scene class the last clarification asked about, for exactly one
        #: turn. A clarification that offers "go to it" must be able to hear
        #: "go to it"; a referent that outlived its turn would bind a pronoun
        #: to something said minutes ago.
        self._pending_scene_referent: str | None = None
        #: ``(as spoken, as acted on)`` when a pronoun was bound this turn.
        self.last_resolved_reference: tuple[str, str] | None = None
        # Read-only information tools (dynamic_prompting.ConversationToolRegistry).
        # The safety supervisor admits them by exact name; anything else
        # stays fail-closed.
        self.info_tools = info_tools
        # D0 duplex: emit a filler *before* slow work (planner / info tools).
        self.slow_path_hook = slow_path_hook
        info_tool_names = tuple(info_tools.names()) if info_tools is not None else ()
        self.safety = SafetySupervisor(
            poses,
            safety_limits,
            skill_ids=self._skill_ids(),
            information_tools=info_tool_names,
        )

    def _skill_ids(self) -> list[str]:
        if self.dog is None:
            return sorted(self.poses)
        return self.dog.catalog.ids()

    def _bounded_action_skill_ids(self) -> list[str]:
        """Skills that may be scheduled by the semantic activity coordinator."""

        try:
            return list(self._validated_capability_manifest().available_embodied_names())
        except ValueError:
            return []

    def _available_pose_skill_ids(self) -> list[str]:
        try:
            return [
                entry.name
                for entry in self._validated_capability_manifest().available_poses()
            ]
        except ValueError:
            return []

    def _available_social_skill_ids(self) -> list[str]:
        """Runtime-equivalent allowlist for model-authored ``next_action`` values.

        ``RobotRuntime._prompt_runtime_context`` exposes exactly tagged social
        poses and trajectories to the model.  Repeating that mechanical filter
        at the local admission boundary makes the prompt's allowlist a checked
        capability rather than a request that a model can bypass by changing
        ``next_action.trigger``.  A pose-only agent has no tag metadata and
        therefore cannot safely infer this allowlist.
        """

        try:
            return list(
                self._validated_capability_manifest().available_embodied_names(
                    required_tags=("social",)
                )
            )
        except ValueError:
            return []

    def _transcript_explicitly_requests_skill(self, transcript: str | None, skill: str) -> bool:
        """Return whether the deterministic router names ``skill`` exactly.

        The proposal's model-authored trigger is evidence about neither owner
        intent nor authority.  Re-route the original final transcript through
        the same closed grammar used by the product's direct-skill path and
        require its exact catalog result.  In ordinary operation such a turn
        has already short-circuited through ``_execute_named_skill``; this
        check keeps directly injected/provider-returned decisions fail closed.
        """

        if not transcript:
            return False
        try:
            frame = self.intent_router.route(
                transcript,
                turn_id="action-validation",
                original_transcript_ref="voice-agent:action-validation:final",
            )
        except (TypeError, ValueError):
            return False
        return frame.route == "direct_skill" and frame.matched_rule == f"catalog_skill:{skill}"

    def _is_social_trajectory(self, skill_name: str) -> bool:
        try:
            return self._validated_capability_manifest().gesture_available(
                skill_name,
                required_tags=("social",),
            )
        except ValueError:
            return False

    def _validated_capability_manifest(self) -> CapabilityManifestV1:
        if not self.conversation_motion_authorized:
            raise ValueError("Conversation motion authority is unavailable")
        manifest = self.capability_manifest
        if manifest is None:
            raise ValueError("Capability manifest is unavailable; motion is disarmed")
        manifest.assert_authenticated_commissioning(self.commissioning_authenticator)
        if self.deployment_target is None or self.deployment_target != manifest.deployment_target:
            raise ValueError("Capability manifest deployment target does not match this adapter")
        validate_commissioning_lifecycle(
            manifest.commissioning_lifecycle,
            state_provider=self.commissioning_state_provider,
            now_monotonic_ns=self.commissioning_clock_ns(),
        )
        if self.dog is not None:
            validate_motion_manifest(manifest, self.dog.catalog)
        return manifest

    def _navigation_capability_error(self, capability_name: str) -> str | None:
        """Validate one exact positive-motion capability immediately before use."""

        if self.capability_manifest is None:
            return "Capability manifest is unavailable; motion is disarmed"
        try:
            manifest = self._validated_capability_manifest()
        except ValueError as error:
            return f"Commissioned capability manifest is stale: {error}"
        if not manifest.navigation_mode_available(capability_name):
            return f"Navigation mode {capability_name!r} is not commissioned"
        return None

    def _embodied_capability_error(self, skill_name: str) -> str | None:
        if self.capability_manifest is None:
            return "Capability manifest is unavailable; motion is disarmed"
        try:
            manifest = self._validated_capability_manifest()
        except ValueError as error:
            return f"Commissioned capability manifest is stale: {error}"
        if skill_name not in manifest.available_embodied_names():
            return f"Skill {skill_name!r} is not commissioned"
        return None

    def _motion_refusal(self, capability_name: str) -> str | None:
        error = self._navigation_capability_error(capability_name)
        return None if error is None else f"I couldn't do that safely. {error}"

    def handle_text(self, transcript: str) -> str:
        return self._handle_text(transcript, None)

    def handle_text_guarded(self, transcript: str, commit: CommitGuard) -> str:
        """Plan freely, then atomically commit only if the voice turn is current."""

        return self._handle_text(transcript, commit)

    def cancel_reasoning(self) -> None:
        """Cooperatively stop an optional provider stream after barge-in."""

        cancelled: set[int] = set()
        for model in (self.language_model, self.planner_model):
            if model is None or id(model) in cancelled:
                continue
            cancelled.add(id(model))
            cancel = getattr(model, "cancel_current", None)
            if callable(cancel):
                cancel()

    def _emit_slow_path(self, reason: str) -> None:
        hook = self.slow_path_hook
        if callable(hook):
            try:
                hook(str(reason))
            except Exception as error:  # noqa: BLE001 - filler must never fail the turn
                self.last_reasoning_error = f"slow_path_hook:{error}"[:500]

    def _handle_text(self, transcript: str, commit: CommitGuard | None) -> str:
        original = re.sub(r"\s+", " ", transcript.strip())
        text = original.lower()
        self.last_reasoning_source = "deterministic"
        self.last_reasoning_error = None
        self.last_reasoning_guard = None
        self.last_brain_metrics = {}
        # Bind a pronoun to the class the previous turn's clarification asked
        # about, before routing, so the whole downstream path (route, grammar,
        # grounding, reply) sees one resolved utterance. The pending referent
        # is consumed unconditionally: whatever the owner says next ends the
        # offer, answered or not.
        pending_referent = self._pending_scene_referent
        self._pending_scene_referent = None
        self.last_resolved_reference = None
        if pending_referent is not None:
            resolved = resolve_pending_reference(original, pending_referent)
            if resolved is not None:
                self.last_resolved_reference = (original, resolved)
                original = resolved
                text = resolved.lower()
        self._turn_sequence += 1
        route_started = time.monotonic()
        frame = self.intent_router.route(
            original,
            turn_id=f"turn-local-{self._turn_sequence}",
            original_transcript_ref=f"voice-agent:{self._turn_sequence}:final",
        )
        routed_at = time.monotonic()
        self.last_intent_frame = frame
        self.last_brain_metrics = {
            "intent_route": frame.route,
            "intent_rule": frame.matched_rule,
            "intent_confidence": frame.confidence,
            "intent_router_ms": round((routed_at - route_started) * 1000.0, 3),
            "_intent_routed_monotonic": routed_at,
        }
        if self.last_resolved_reference is not None:
            # A substitution the robot made on the owner's behalf is reported,
            # never silent: the acted-on utterance is not the spoken one.
            self.last_brain_metrics["resolved_reference"] = list(self.last_resolved_reference)
        if text in EMERGENCY_STOP_PHRASES:
            self.last_closed_intent = ClosedIntent.STOP
            return self._execute(AgentDecision("Stopping.", (ToolCall("stop_motion"),)))

        # Closed companion intents (pause/resume/pace/come/goal-amend).
        # Goal-amend: fail-closed pause/snapshot, then deliberative replan.
        closed = parse_closed_intent(text)
        self.last_closed_intent = closed
        if closed is ClosedIntent.GOAL_AMEND:
            return self._handle_goal_amend(original, frame, commit)
        # STOP is deliberately excluded: it is handled above on the fast path,
        # whose phrase set is now derived from this same parser, so a STOP
        # phrase can no longer fall past both branches (U33 / "halt").
        if closed is not None and closed is not ClosedIntent.STOP:
            return self._handle_closed_intent(closed, original, frame, commit)

        # Compound/correction turns must not be truncated by a permissive
        # single-skill grammar (for example, treating "sidewalk and then sit"
        # as a destination label). The router remains metadata-only; this
        # branch merely selects the separate constrained PlanIR call.
        if frame.route == "deliberative_plan" and self._planning_ready():
            self._emit_slow_path("deliberative_plan")
            return self._handle_plan(original, frame, commit)

        if text in {"follow", "follow me", "come with me", "heel"}:
            if self._local_plan_ready():
                return self._admit_local_sketch(
                    sketch_follow(behind=False),
                    frame,
                    original,
                    commit,
                    capability_name="follow_owner",
                    reply="Okay—I'll follow you safely.",
                )
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(
                        "I will follow you.",
                        (ToolCall("set_behavior", {"mode": "follow"}),),
                    ),
                    transcript=original,
                ),
            )
        if text in {
            "follow behind me",
            "walk behind me",
            "stay behind me",
            "heel behind me",
        }:
            if self._local_plan_ready():
                return self._admit_local_sketch(
                    sketch_follow(behind=True),
                    frame,
                    original,
                    commit,
                    capability_name="follow_owner",
                    reply="Okay—I'll follow behind you once I can estimate your direction.",
                )
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(
                        "I will follow behind you once I can estimate your direction.",
                        (ToolCall("set_behavior", {"mode": "follow_behind"}),),
                    ),
                    transcript=original,
                ),
            )
        if text in {"stay", "wait", "wait here", "hold position"}:
            if self._local_plan_ready():
                return self._admit_local_sketch(
                    sketch_hold(),
                    frame,
                    original,
                    commit,
                    capability_name=None,
                    reply="Okay—I'll stay here.",
                )
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(
                        "I will stay here.",
                        (ToolCall("set_behavior", {"mode": "stay"}),),
                    ),
                    transcript=original,
                ),
            )

        spatial_intent = parse_spatial_intent(text)
        if spatial_intent is not None:
            if self._local_plan_ready():
                return self._admit_local_sketch(
                    sketch_spatial(spatial_intent),
                    frame,
                    original,
                    commit,
                    capability_name=_SPATIAL_CAPABILITY[spatial_intent.behavior],
                    reply="Okay—I'll make that bounded move safely.",
                )
            if self.spatial_behavior_publisher is not None:
                return self._commit(
                    commit,
                    lambda: self._remember(
                        original,
                        lambda: self._execute_spatial_behavior(spatial_intent),
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
                    lambda: self._remember(original, lambda: self._execute_walk_skill(skill, walk)),
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
                    transcript=original,
                ),
            )

        nav_directive = self._parse_navigate(text)
        if nav_directive is not None and self.dog is not None:
            # A compound physical request the router sent to the planner, WITHOUT
            # a planner, has reached the single-skill navigation parser — which
            # would compile the whole conjunction as ONE literal destination
            # label ("go to the sidewalk and then sit"), sending the dog to
            # search for a nonexistent "sidewalk and then sit" entity behind a
            # confident acknowledgment. Detect the router's compound signal and
            # clarify which part comes first, rather than compile the literal.
            # (Non-navigation compounds — "sit then sprint" — do not parse as a
            # directive and never reach here; they stay with the conversation
            # lane.)
            if frame.matched_rule == "compound_physical_request":
                return self._handle_compound_without_planner(original, frame, commit)
            # A destination that is only a pronoun reached here because the
            # referent expired (or never existed): the clarification offer is
            # one turn long by design. Ask rather than admit a mission whose
            # target is the word "it".
            dangling = dangling_reference(nav_directive)
            if dangling is not None:
                return self._commit(
                    commit,
                    lambda: self._remember(
                        original,
                        lambda: (
                            f'I\'m not sure what "{dangling}" refers to — '
                            f"could you name the place?"
                        ),
                    ),
                )
            # Card R20 — the unknown-place ask, in the same place and the same
            # shape as the dangling-pronoun ask above it. "go to narnia" used to
            # compile a mission whose target was a place that cannot exist,
            # behind the confident "Okay—I'll go wait near narnia safely."
            # Asking which real place they meant is honest; accepting the
            # command and rotating on the spot until something preempts it is
            # not. Only GOAL phrasing is gated: "look for a mailbox" is an
            # explicit search and still searches (``admit_navigation_place``).
            unknown_place = self._unknown_place_reply(nav_directive)
            if unknown_place is not None:
                return self._commit(
                    commit,
                    lambda: self._remember(original, lambda: unknown_place),
                )
            if self._local_plan_ready():
                return self._admit_local_sketch(
                    sketch_navigate(nav_directive),
                    frame,
                    original,
                    commit,
                    capability_name=_NAVIGATION_CAPABILITY,
                    reply=f"Okay—I'll navigate toward {nav_directive} safely.",
                )
            return self._commit(
                commit,
                lambda: self._remember(original, lambda: self._execute_navigation(nav_directive)),
            )

        # Direct catalog/status/backend commands are bound deterministically.
        # They must not queue behind conversation inference or let a language
        # model author raw velocity/backend-control arguments.
        backend_match = re.fullmatch(r"use (vendor|sport|rl)(?: backend)?", text)
        if backend_match and self.motion is not None:
            name = backend_match.group(1)
            if name == "sport":  # deprecated vendor-branded alias
                name = "vendor"
            call = ToolCall("set_motion_backend", {"name": name})
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(f"Switching to the {name} backend.", (call,)),
                    transcript=original,
                ),
            )

        catalog_rule = frame.matched_rule or ""
        if catalog_rule.startswith("catalog_skill:"):
            skill_name = catalog_rule.partition(":")[2]
            return self._commit(
                commit,
                lambda: self._remember(original, lambda: self._execute_named_skill(skill_name)),
            )

        has_status_source = self.motion is not None or any(
            "status" in module.commands() for module in self.modules
        )
        if frame.matched_rule == "status_query" and has_status_source:
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision("Done.", (ToolCall("get_status"),)),
                    transcript=original,
                ),
            )

        if self.language_model is not None:
            try:
                set_prompt = getattr(self.language_model, "set_system_prompt", None)
                if callable(set_prompt) and self.system_prompt_provider is not None:
                    set_prompt(self.system_prompt_provider())
                # Conversation lane: never expose physical tool schemas (K6/B1).
                decision = self.language_model.decide(
                    original,
                    self.conversation_tool_definitions(),
                    self.memory.recent(self.conversation_history_messages),
                )
                self.last_reasoning_source = "model"
                # Belt-and-suspenders: strip any physical tool calls even if a
                # provider ignores the schema filter.
                if any(call.name in MOTION_TOOLS for call in decision.tool_calls):
                    self.last_reasoning_guard = (
                        "stripped physical tools from conversation-lane decision"
                    )
                    decision = AgentDecision(
                        reply=decision.reply,
                        tool_calls=tuple(
                            call
                            for call in decision.tool_calls
                            if call.name not in MOTION_TOOLS
                        ),
                        intent="conversation",
                        affect=decision.affect,
                        next_action=None,
                    )
                decision = self._guard_model_motion(text, decision)
                self.last_dialogue_act = dialogue_act_from_text(
                    turn_id=frame.turn_id,
                    text=decision.reply,
                    acknowledgement_kind="model_reply",
                )
                return self._commit(
                    commit,
                    lambda: self._execute(decision, transcript=original),
                )
            except (RuntimeError, TypeError, ValueError) as error:
                self.last_reasoning_source = "fallback"
                self.last_reasoning_error = str(error)[:500]

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
                    transcript=original,
                ),
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
                lambda: self._remember(original, lambda: self._execute_named_skill(skill_name)),
            )

        if self.dog is not None:
            bare = text.replace(" ", "_")
            if bare in self.dog.catalog.ids():
                return self._commit(
                    commit,
                    lambda: self._remember(original, lambda: self._execute_named_skill(bare)),
                )

        command, _, argument = text.partition(" ")
        for module in self.modules:
            if command in module.commands():
                return self._commit(
                    commit,
                    lambda module=module: self._remember(
                        original,
                        lambda: (
                            module.handle(command, argument) or "I did not understand that command"
                        ),
                    ),
                )

        # Novel-verb clarify fallback (stratum 3, language lanes). No grammar
        # rule matched and no reviewed physical-cue verb is present, but the
        # utterance may still *name* something the robot knows. Saying what was
        # understood and what can be done with it is honest; the flat
        # "I did not understand that command" below throws that away.
        #
        # Gated on `not physical_cue_present`: an utterance that DOES carry a
        # motion verb but matched no rule is deliberately left to the existing
        # deliberative/refusal path, because inviting a retry there would be a
        # motion suggestion, not a clarification.
        if not physical_cue_present(text):
            clarification = clarification_for(text)
            if clarification is not None:
                # Offering "I can go to it" obliges the next turn to be able to
                # hear "go to it". Without this the offer compiled a mission
                # whose target was the literal word "it".
                self._pending_scene_referent = scene_class_mentioned(text)
                return self._commit(
                    commit,
                    lambda: self._remember(original, lambda: clarification),
                )
        return "I did not understand that command"

    def _planning_ready(self) -> bool:
        return bool(
            self.planner_model is not None
            and callable(getattr(self.planner_model, "plan", None))
            and self.planning_context_provider is not None
            and self.plan_publisher is not None
            and self.planner_system_prompt_provider is not None
            and self.planner_schema_provider is not None
            and self.planner_skill_contracts_provider is not None
        )

    def _local_plan_ready(self) -> bool:
        """PlanSketch → PlanIR admission without calling a planner model."""

        return bool(
            self.planning_context_provider is not None
            and self.plan_publisher is not None
            and self.planner_output_adapter is not None
        )

    def _unknown_place_reply(self, directive: str) -> str | None:
        """Card R20 — the ask for a place nothing can resolve, else ``None``.

        ``None`` is the important half twice over. With no ``place_admission``
        provider there is no vocabulary to judge against and the pre-R20 path
        stands untouched; and a provider that raises is treated as no answer
        rather than as a refusal, because an honesty gate that fails closed
        would take navigation down over a map that failed to load.
        """

        if self.place_admission is None:
            return None
        try:
            verdict = self.place_admission(directive)
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as error:
            self.last_brain_metrics["place_admission_error"] = str(error)[:120]
            return None
        if verdict.admitted:
            return None
        self.last_brain_metrics["unknown_place"] = verdict.query
        return verdict.reply()

    def conversation_tool_definitions(self) -> list[dict[str, Any]]:
        """Schemas for the conversation lane — physical tools stripped."""

        return conversation_tool_definitions(self.tool_definitions())

    def _handle_compound_without_planner(
        self,
        transcript: str,
        frame: IntentFrame,
        commit: CommitGuard | None,
    ) -> str:
        """Clarify a multi-action request when there is no planner to sequence it.

        Reached only for a ``compound_physical_request`` on the deliberative
        route while :meth:`_planning_ready` is False. Splitting is for the WORDS
        of the clarification only — it grounds nothing and compiles no plan, so
        the literal-conjunction entity search this replaces can never fire. One
        turn long by design: the owner names the first step and the ordinary
        single-skill lane serves it.
        """

        self.last_reasoning_source = "compound_clarify_no_planner"
        self.last_brain_metrics["compound_without_planner"] = "clarify"
        clauses = split_compound_clauses(transcript)
        self.last_brain_metrics["compound_clauses"] = list(clauses)
        if len(clauses) >= 2:
            reply = (
                "I can only do one thing at a time without my full planner — "
                f'which first: "{clauses[0]}", or "{clauses[1]}"?'
            )
        else:
            reply = (
                "That sounds like more than one step and I can't sequence them "
                "without my full planner — tell me just the first thing to do."
            )
        return self._commit(commit, lambda: self._remember(transcript, lambda: reply))

    def _goal_amend_without_planner(
        self,
        transcript: str,
        remainder: str,
        frame: IntentFrame,
        commit: CommitGuard | None,
        *,
        pause_reply: str,
    ) -> str:
        """Honestly resolve a goal amendment when there is no planner.

        The old behaviour returned the pause line and left the mission paused
        forever behind "I'll revise the current goal" — an indefinite stall.
        Instead: if the replacement is itself a groundable single navigation
        directive naming a place, apply a DETERMINISTIC retarget through the
        local-sketch lane (no planner needed to head somewhere new); otherwise
        reply honestly that a general amendment needs the planner and tell the
        owner to give the new command on its own. Never a silent hold.
        """

        nav_directive = self._parse_navigate(remainder)
        if nav_directive is None:
            # The amend prefix strips the verb ("actually, go to the lamppost" →
            # "the lamppost"), so re-attach a neutral one; a bare place still
            # retargets, a non-place remainder still yields None.
            nav_directive = self._parse_navigate(f"go to {remainder}")
        # An anaphoric replacement ("the other one", "the same") names a prior
        # referent this route has no context to resolve — that is precisely what
        # the planner is for, so it takes the honest reply, not a guess.
        anaphoric = re.search(r"\b(?:other|another|same)\b", remainder.lower()) is not None
        # Card R20. A retarget is a goal admission like any other: "actually, go
        # to narnia" must not become a mission either, and it gets the same ask
        # rather than the generic "give me the new command on its own", which
        # would send the owner round the loop to be refused again.
        if nav_directive is not None and not anaphoric:
            unknown_place = self._unknown_place_reply(nav_directive)
            if unknown_place is not None:
                self.last_brain_metrics["goal_amend_replan"] = "unknown_place_refused"
                return self._commit(
                    commit,
                    lambda: self._remember(transcript, lambda: unknown_place),
                )
        if (
            nav_directive is not None
            and self.dog is not None
            and not anaphoric
            and dangling_reference(nav_directive) is None
            and self._local_plan_ready()
        ):
            retarget = replace(
                frame,
                route="deliberative_plan",
                speech_act="correction",
                matched_rule="goal_amend",
                requires_fresh_scene=True,
                original_transcript_ref=remainder[:200],
            )
            self.last_intent_frame = retarget
            self.last_brain_metrics["goal_amend_replan"] = "local_retarget_no_planner"
            self.last_brain_metrics["goal_amend_remainder"] = remainder
            return self._admit_local_sketch(
                sketch_navigate(nav_directive),
                retarget,
                transcript,
                commit,
                capability_name=_NAVIGATION_CAPABILITY,
                reply=f"Okay — revising the goal: {nav_directive}.",
            )

        self.last_brain_metrics["goal_amend_replan"] = "no_planner_honest"
        reply = (
            "I've paused what I was doing, but I can't revise the goal on the fly "
            "without my full planner — give me the new command on its own and "
            "I'll start it fresh."
        )
        return self._commit(commit, lambda: self._remember(transcript, lambda: reply))

    def _handle_goal_amend(
        self,
        transcript: str,
        frame: IntentFrame,
        commit: CommitGuard | None,
    ) -> str:
        """Mid-task amendment: pause/snapshot via executive, then replan remainder."""

        from .executive_caps import resolve_cap

        directive = resolve_cap(ClosedIntent.GOAL_AMEND)
        self.last_brain_metrics["closed_intent"] = ClosedIntent.GOAL_AMEND.value
        self.last_brain_metrics["closed_intent_kind"] = directive.kind
        self.last_brain_metrics.pop("goal_amend_ok", None)

        if self.closed_intent_handler is not None:
            pause_reply = self.closed_intent_handler(ClosedIntent.GOAL_AMEND, directive)
        else:
            # Without a runtime handler we cannot snapshot/pause — fail closed.
            self.last_brain_metrics["goal_amend_ok"] = False
            pause_reply = "There's nothing active to revise right now."

        amend_ok = self.last_brain_metrics.get("goal_amend_ok")
        if amend_ok is False:
            return self._commit(
                commit,
                lambda: self._remember(transcript, lambda: pause_reply),
            )

        remainder = strip_amend_prefix(transcript)
        if not remainder:
            # An amend cue with no replacement yet ("actually…"): the mission is
            # paused and we wait for the owner to name the new goal. This is a
            # bounded, self-explaining hold (the pause line names the state), not
            # the indefinite "I'll revise the current goal" stall.
            self.last_brain_metrics["goal_amend_replan"] = "waiting_for_goal"
            return self._commit(
                commit,
                lambda: self._remember(transcript, lambda: pause_reply),
            )
        if not self._planning_ready():
            # No planner to sequence a general amendment: retarget deterministically
            # when the replacement names a place, else reply honestly — never the
            # old ``deferred_no_planner`` indefinite pause.
            return self._goal_amend_without_planner(
                transcript, remainder, frame, commit, pause_reply=pause_reply
            )

        correction = replace(
            frame,
            route="deliberative_plan",
            speech_act="correction",
            matched_rule="goal_amend",
            requires_fresh_scene=True,
            original_transcript_ref=remainder[:200],
        )
        self.last_intent_frame = correction
        self.last_brain_metrics["goal_amend_replan"] = "deliberative"
        self.last_brain_metrics["goal_amend_remainder"] = remainder
        # Record the amend cue once, then admit the residual replan.
        self.memory.add("user", transcript)
        self.memory.add("assistant", pause_reply)
        self._emit_slow_path("deliberative_plan")
        return self._handle_plan(remainder, correction, commit)

    def _handle_closed_intent(
        self,
        intent: ClosedIntent,
        transcript: str,
        frame: IntentFrame,
        commit: CommitGuard | None,
    ) -> str:
        pace = 1.0
        if self.pace_scale_provider is not None:
            try:
                pace = float(self.pace_scale_provider())
            except (TypeError, ValueError):
                pace = 1.0
        directive = resolve_cap(intent, current_pace=pace)
        self.last_brain_metrics["closed_intent"] = intent.value
        self.last_brain_metrics["closed_intent_kind"] = directive.kind

        if intent is ClosedIntent.COME:
            if self._local_plan_ready():
                return self._admit_local_sketch(
                    directive.sketch or sketch_come(),
                    frame,
                    transcript,
                    commit,
                    capability_name="follow_owner",
                    reply=directive.reply,
                )
            return self._commit(
                commit,
                lambda: self._execute(
                    AgentDecision(
                        directive.reply,
                        (ToolCall("set_behavior", {"mode": "follow"}),),
                    ),
                    transcript=transcript,
                ),
            )

        if self.closed_intent_handler is not None:

            def apply_cap() -> str:
                return self.closed_intent_handler(intent, directive)

            return self._commit(commit, lambda: self._remember(transcript, apply_cap))

        # No runtime handler: acknowledge without inventing motion authority.
        return self._commit(
            commit,
            lambda: self._remember(transcript, lambda: directive.reply),
        )

    def _admit_local_sketch(
        self,
        sketch: PlanSketch,
        frame: IntentFrame,
        transcript: str,
        commit: CommitGuard | None,
        *,
        capability_name: str | None,
        reply: str,
    ) -> str:
        """Compile a system-authored PlanSketch and publish via PlanIR admission."""

        assert self.planning_context_provider is not None
        assert self.plan_publisher is not None
        assert self.planner_output_adapter is not None
        if capability_name is not None:
            refusal = self._motion_refusal(capability_name)
            if refusal is not None:
                return self._commit(
                    commit,
                    lambda: self._remember(transcript, lambda: refusal),
                )
        try:
            snapshot = self.planning_context_provider()
            plan = self.planner_output_adapter(sketch, frame, snapshot)
            if plan.source_turn_id != frame.turn_id:
                raise ValueError("local PlanIR source_turn_id does not match routed turn")
            self.last_reasoning_source = "local_plan_sketch"
            self.last_brain_metrics["local_plan_skills"] = [step.skill for step in plan.steps]

            def accept() -> str:
                published = self.plan_publisher(plan, frame, transcript)
                return published or reply

            return self._commit(commit, lambda: self._remember(transcript, accept))
        except (RuntimeError, TypeError, ValueError) as error:
            self.last_reasoning_source = "local_plan_fallback"
            self.last_reasoning_error = str(error)[:500]
            reply = self._admission_failure_reply(error)
            return self._commit(
                commit,
                lambda: self._remember(transcript, lambda: reply),
            )

    @staticmethod
    def _admission_failure_reply(error: Exception) -> str:
        """A refusal must say why; the generic reply is a last resort."""

        code = error.code if isinstance(error, PlanValidationError) else None
        replies = {
            "emergency_stopped": (
                "Emergency stop is latched, so I can't take new movement "
                "commands until it's released."
            ),
            "camera_stale": (
                "My camera feed is stale right now, so I'm holding still. "
                "Give me a moment and try again."
            ),
            "lidar_stale": (
                "My LiDAR feed is stale right now, so I'm holding still. "
                "Give me a moment and try again."
            ),
            "owner_not_grounded": (
                "I can't see you clearly enough to do that yet — step where "
                "I can see you and ask again."
            ),
            "owner_heading_unavailable": (
                "I can't tell which way you're moving yet — take a step or "
                "two and ask again."
            ),
        }
        if code in replies:
            return replies[code]
        return (
            "I couldn't admit that command as a safe plan yet. "
            "Please clarify or let me inspect the scene again."
        )

    def _handle_plan(
        self,
        transcript: str,
        frame: IntentFrame,
        commit: CommitGuard | None,
    ) -> str:
        assert self.planner_model is not None
        assert self.planning_context_provider is not None
        assert self.plan_publisher is not None
        assert self.planner_system_prompt_provider is not None
        assert self.planner_schema_provider is not None
        assert self.planner_skill_contracts_provider is not None
        try:
            snapshot_started = time.monotonic()
            snapshot = self.planning_context_provider()
            snapshot_at = time.monotonic()
            self.last_brain_metrics["observation_snapshot_ms"] = round(
                (snapshot_at - snapshot_started) * 1000.0,
                3,
            )
            self.last_brain_metrics["_observation_snapshot_monotonic"] = snapshot_at
            plan_started = time.monotonic()
            response_schema = contextual_planner_schema(
                self.planner_schema_provider(),
                frame,
                snapshot,
            )
            proposed_output = self.planner_model.plan(
                transcript,
                intent_frame=frame,
                observation=snapshot,
                skill_contracts=self.planner_skill_contracts_provider(),
                response_schema=response_schema,
                system_prompt=self.planner_system_prompt_provider(),
            )
            if self.planner_output_adapter is not None:
                plan = self.planner_output_adapter(proposed_output, frame, snapshot)
            else:
                if not isinstance(proposed_output, PlanIR):
                    raise TypeError("PlanSketch requires a runtime planner-output adapter")
                plan = bind_plan_context(proposed_output, frame, snapshot)
            plan_response_at = time.monotonic()
            self.last_brain_metrics["plan_decode_ms"] = round(
                (plan_response_at - plan_started) * 1000.0,
                3,
            )
            self.last_brain_metrics["_plan_response_monotonic"] = plan_response_at
            if plan.source_turn_id != frame.turn_id:
                raise ValueError("PlanIR source_turn_id does not match its routed turn")
            self.last_reasoning_source = "plan_model"

            def accept_plan() -> str:
                accepted_started = time.monotonic()
                reply = self.plan_publisher(plan, frame, transcript)
                accepted_at = time.monotonic()
                self.last_brain_metrics["plan_accept_ms"] = round(
                    (accepted_at - accepted_started) * 1000.0,
                    3,
                )
                self.last_brain_metrics.setdefault("_plan_accepted_monotonic", accepted_at)
                return self._remember(transcript, lambda: reply)

            return self._commit(commit, accept_plan)
        except (RuntimeError, TypeError, ValueError) as error:
            self.last_reasoning_source = "plan_fallback"
            self.last_reasoning_error = str(error)[:500]
            return self._commit(
                commit,
                lambda: self._remember(
                    transcript,
                    lambda: (
                        "I couldn't form a safe, grounded plan yet. "
                        "Please clarify the task or let me inspect the scene again."
                    ),
                ),
            )

    @staticmethod
    def _commit(commit: CommitGuard | None, action: Callable[[], str]) -> str:
        return action() if commit is None else commit(action)

    def _remember(self, transcript: str, action: Callable[[], str]) -> str:
        """Record every deterministic committed path with the same semantics."""

        self.memory.add("user", transcript)
        reply = action()
        self.memory.add("assistant", reply)
        return reply

    def _guard_model_motion(self, transcript: str, decision: AgentDecision) -> AgentDecision:
        """Fail closed when a non-command utterance elicits a physical model action."""

        forbidden = tuple(
            call.name for call in decision.tool_calls if call.name in MODEL_FORBIDDEN_TOOLS
        )
        if forbidden:
            self.last_reasoning_guard = (
                "suppressed raw motion or backend authority requested by the conversation model: "
                + ", ".join(sorted(set(forbidden)))
            )
            return AgentDecision(
                reply=(
                    "I couldn't do that safely. Please use a reviewed movement command "
                    "or manual control."
                ),
                intent=decision.intent,
                affect=decision.affect,
            )

        has_motion = any(call.name in MOTION_TOOLS for call in decision.tool_calls)
        has_motion = has_motion or decision.next_action is not None
        if not has_motion or _model_motion_is_explicit(transcript):
            return decision
        self.last_reasoning_guard = (
            "suppressed physical model output for a negated, hypothetical, or "
            "information-seeking utterance"
        )
        return AgentDecision(
            reply="I won't move from that request, but I can explain what I would do.",
            tool_calls=tuple(call for call in decision.tool_calls if call.name not in MOTION_TOOLS),
            intent=decision.intent,
            affect=decision.affect,
            next_action=None,
        )

    def _execute_walk_skill(self, skill: str, walk: VelocityCommand) -> str:
        assert self.dog is not None
        refusal = self._motion_refusal(skill)
        if refusal is not None:
            return refusal
        result = self.dog.execute(skill, vx=walk.vx, vy=walk.vy, vyaw=walk.vyaw)
        return self._walk_reply(walk) if result.accepted else result.message

    def _execute_navigation(self, directive: str) -> str:
        assert self.dog is not None
        refusal = self._motion_refusal(_NAVIGATION_CAPABILITY)
        if refusal is not None:
            return refusal
        if self.navigation_publisher is not None:
            try:
                return self.navigation_publisher(directive)
            except (LookupError, RuntimeError, ValueError) as error:
                return f"I couldn't navigate there. {error}"
        try:
            mission, cmd = self.dog.navigate(directive)
        except (LookupError, RuntimeError, ValueError) as error:
            return f"I couldn't navigate there. {error}"
        place = _mission_place(mission, directive)
        if cmd.stop:
            if mission.status == "arrived":
                return f"Arrived at {place}."
            if mission.status == "verifying":
                return f"Stopping at {place} and verifying that I am safely settled."
            return f"I couldn't navigate to {place}. {cmd.note or mission.status}"
        return f"Navigating to {place} (vx={cmd.vx:.2f}, vyaw={cmd.vyaw:.2f}; {cmd.note})."

    def _execute_spatial_behavior(self, intent: SpatialIntent) -> str:
        assert self.spatial_behavior_publisher is not None
        capability_name = _SPATIAL_CAPABILITY.get(intent.behavior)
        if capability_name is None:
            return "I couldn't do that safely. Spatial behavior has no capability binding"
        refusal = self._motion_refusal(capability_name)
        if refusal is not None:
            return refusal
        return self.spatial_behavior_publisher(intent)

    def _execute_named_skill(self, skill_name: str) -> str:
        live_skill = None
        if self.dog is not None:
            try:
                live_skill = self.dog.catalog.get(skill_name)
            except KeyError:
                pass
        capability_error = (
            self._embodied_capability_error(skill_name)
            if live_skill is None or live_skill.kind in {"pose", "trajectory"}
            else self._navigation_capability_error(skill_name)
        )
        if capability_error is not None:
            return f"I couldn't do that safely. {capability_error}"
        if self.dog is None:
            return "I couldn't do that safely. No live commissioned skill catalog"
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
        """Extract explicit destination and relational navigation requests."""

        return navigation_directive_from_text(text)

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
        evidence = explicit_affect_from_text(text)
        if evidence is None:
            return None
        reply = {
            "sad": "I'm here with you.",
            "happy": "I'm happy with you!",
            "excited": "I'm excited with you!",
        }.get(evidence.label)
        return (evidence.label, reply) if reply is not None else None

    def _execute(self, decision: AgentDecision, transcript: str | None = None) -> str:
        if transcript:
            self.memory.add("user", transcript)
        validations = [(call, self.safety.validate(call)) for call in decision.tool_calls]
        for _, result in validations:
            self.memory.add("tool", result.message)
        failures = [result.message for _, result in validations if not result.accepted]
        failures.extend(self._motion_capability_failures(decision.tool_calls))
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
        physical_count = sum(call.name in MOTION_TOOLS for call in decision.tool_calls)
        physical_count += decision.next_action is not None
        if physical_count > 1:
            failures.append("A decision can contain only one motion-producing action")
        if decision.next_action is not None:
            proposal_error = self._validate_action_proposal(decision, transcript=transcript)
            if proposal_error:
                if proposal_error.startswith("Unknown proposed skill"):
                    # An INTERNAL validator string — the conversation model
                    # reached for a physical tool its schema does not carry
                    # ("navigate"). It must never reach the owner verbatim
                    # (card llm-lane-dead-ends): translate it to a clarify.
                    self.last_reasoning_guard = (
                        f"suppressed unknown-skill validator string: {proposal_error}"
                    )
                    reply = (
                        "I think you're asking me to move or act, but I couldn't "
                        "turn that into a safe command — could you say it as a "
                        'direct request, like "go to the lamppost"?'
                    )
                    self.memory.add("assistant", reply)
                    return reply
                failures.append(proposal_error)
        if failures:
            reply = f"I couldn't do that safely. {failures[0]}"
            self.memory.add("assistant", reply)
            return reply

        detail = None
        info_result: str | None = None
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
                    place = _mission_place(mission, directive)
                    if cmd.stop and mission.status == "arrived":
                        detail = f"Arrived at {place}."
                    elif cmd.stop and mission.status == "verifying":
                        detail = f"Stopping at {place} and verifying that I am safely settled."
                    elif cmd.stop:
                        detail = f"Navigation failed for {place}: {cmd.note or mission.status}."
                    else:
                        detail = f"Navigating to {place} (vx={cmd.vx:.2f})."
            elif call.name == "set_behavior":
                if self.behavior_publisher is None:
                    failures.append("Behavior control is not configured")
                    continue
                detail = self.behavior_publisher(str(call.arguments["mode"]))
            elif call.name == "run_spatial_behavior":
                if self.spatial_behavior_publisher is None:
                    failures.append("Spatial behavior control is not configured")
                    continue
                try:
                    detail = self._execute_spatial_behavior(
                        spatial_intent_from_arguments(call.arguments)
                    )
                except (RuntimeError, TypeError, ValueError) as error:
                    failures.append(str(error))
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
            elif self.info_tools is not None and self.info_tools.has(call.name):
                self._emit_slow_path(f"info_tool:{call.name}")
                try:
                    result = self.info_tools.invoke(call.name, dict(call.arguments))
                except (LookupError, RuntimeError, TypeError, ValueError) as error:
                    failures.append(str(error))
                    continue
                self.memory.add("tool", f"{call.name}: {result}")
                detail = result
                info_result = result
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
        elif info_result is not None:
            # The model narrated ("let me check...") AND fetched: speak both.
            reply = f"{reply} {info_result}"
        self.memory.add("assistant", reply)
        return reply

    def _motion_capability_failures(
        self,
        calls: tuple[ToolCall, ...],
    ) -> list[str]:
        """Return manifest failures for tool calls that can produce translation."""

        failures: list[str] = []
        for call in calls:
            if call.name in {"run_pose", "run_skill"}:
                name = call.arguments.get("name")
                if isinstance(name, str):
                    error = self._embodied_capability_error(name)
                    if error is not None:
                        failures.append(error)
                continue
            capability_name = self._tool_motion_capability(call)
            if capability_name is None:
                continue
            error = self._navigation_capability_error(capability_name)
            if error is not None:
                failures.append(error)
        return failures

    @staticmethod
    def _tool_motion_capability(call: ToolCall) -> str | None:
        if call.name == "navigate":
            return _NAVIGATION_CAPABILITY
        if call.name == "set_behavior":
            mode = call.arguments.get("mode")
            return _BEHAVIOR_CAPABILITY.get(mode) if isinstance(mode, str) else None
        if call.name == "run_spatial_behavior":
            behavior = call.arguments.get("behavior")
            return _SPATIAL_CAPABILITY.get(behavior) if isinstance(behavior, str) else None
        if call.name != "set_velocity":
            return None
        try:
            vx = float(call.arguments.get("vx", 0.0))
            vy = float(call.arguments.get("vy", 0.0))
            vyaw = float(call.arguments.get("vyaw", 0.0))
        except (TypeError, ValueError):
            return None
        if max(abs(vx), abs(vy), abs(vyaw)) == 0.0:
            return None
        if abs(vyaw) >= max(abs(vx), abs(vy)):
            return "turn_left" if vyaw > 0.0 else "turn_right"
        if abs(vy) > abs(vx):
            return "strafe_left" if vy > 0.0 else "strafe_right"
        return "walk_forward" if vx > 0.0 else "walk_backward"

    def _validate_action_proposal(
        self,
        decision: AgentDecision,
        *,
        transcript: str | None,
    ) -> str | None:
        proposal = decision.next_action
        if proposal is None:
            return None
        if self.capability_manifest is not None and self.dog is not None:
            try:
                validate_motion_manifest(self.capability_manifest, self.dog.catalog)
            except ValueError:
                return "Live motion content no longer matches commissioned capabilities"
        if self.action_proposal_publisher is None:
            return "Semantic action proposals are not configured"
        if proposal.kind != "skill" or proposal.name not in self._skill_ids():
            return f"Unknown proposed skill: {proposal.name}"
        if proposal.name not in self._available_social_skill_ids():
            return "Proposed action is not in the runtime social-skill allowlist"
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
        elif proposal.trigger == "conversation_reaction":
            if not self._is_social_trajectory(proposal.name):
                return "Conversation reactions require a social trajectory skill"
            if (
                proposal.timing_preference != "when_safe"
                or proposal.interruption_request != "none"
            ):
                return "Conversation reactions cannot request interruption"
        else:
            if not self._transcript_explicitly_requests_skill(transcript, proposal.name):
                return "Explicit action authority was not present in the owner transcript"
            if proposal.name not in self._bounded_action_skill_ids():
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
        skill_enum = self._bounded_action_skill_ids()
        pose_enum = self._available_pose_skill_ids()
        run_skill_description = (
            "Run one bounded configured pose or trajectory through the activity coordinator."
            if coordinated
            else "Run one commissioned bounded pose or trajectory."
        )
        tools: list[dict[str, Any]] = [
            {
                "name": "run_pose",
                "description": "Run one configured pose skill.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": pose_enum}
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
                "name": "navigate",
                "description": (
                    "Navigate to or hold near a perceived place/object from a natural-language "
                    "directive (for example: go onto the sidewalk, wait by the lamppost, or "
                    "go to the coffee shop). Runtime verifies the spatial relationship."
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
                "description": (
                    "Start direct owner following, explicitly form behind a moving owner "
                    "from camera tracks, or hold the current position."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["follow", "follow_behind", "stay"],
                        },
                    },
                    "required": ["mode"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "run_spatial_behavior",
                "description": (
                    "Run one bounded local movement. Use move_steps for a small number of "
                    "body/owner-relative steps, or orbit_owner for one small local circle. "
                    "Never use this for destination navigation."
                ),
                "parameters": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "behavior": {"const": "move_steps"},
                                "direction": {
                                    "type": "string",
                                    "enum": ["forward", "backward", "away_from_owner"],
                                },
                                "steps": {"type": "integer", "minimum": 1, "maximum": 12},
                            },
                            "required": ["behavior", "direction", "steps"],
                            "additionalProperties": False,
                        },
                        {
                            "type": "object",
                            "properties": {
                                "behavior": {"const": "orbit_owner"},
                                "direction": {
                                    "type": "string",
                                    "enum": ["clockwise", "counterclockwise"],
                                },
                                "size": {
                                    "type": "string",
                                    "enum": ["small", "normal", "wide"],
                                },
                                "revolutions": {
                                    "type": "number",
                                    "minimum": 0.25,
                                    "maximum": 1.0,
                                },
                            },
                            "required": ["behavior", "direction", "size", "revolutions"],
                            "additionalProperties": False,
                        },
                    ]
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
        if not pose_enum:
            tools = [tool for tool in tools if tool["name"] != "run_pose"]
        if not skill_enum:
            tools = [tool for tool in tools if tool["name"] != "run_skill"]
        if self.info_tools is not None:
            tools.extend(self.info_tools.definitions())
        return tools


def _model_motion_is_explicit(text: str) -> bool:
    raw = " ".join(
        str(text)
        .translate(
            str.maketrans(
                {
                    "\N{LEFT SINGLE QUOTATION MARK}": "'",
                    "\N{RIGHT SINGLE QUOTATION MARK}": "'",
                    "\N{MODIFIER LETTER APOSTROPHE}": "'",
                    "`": "'",
                }
            )
        )
        .lower()
        .split()
    )
    if re.search(
        r"\b(?:do\s+not|don[' ]?t|never|not|should\s+not|shouldn[' ]?t|"
        r"must\s+not|mustn[' ]?t|cannot|can[' ]?t)\b",
        raw,
    ):
        return False
    clean = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    return not bool(
        re.match(
            r"^(?:what|why|how|when|where|if|suppose|imagine|pretend|describe|"
            r"tell me)\b",
            clean,
        )
    )


def _mission_place(mission: object, fallback: str) -> str:
    goal = getattr(mission, "goal", None)
    if goal is not None:
        return str(getattr(goal, "label", "") or getattr(goal, "poi_id", "") or fallback)
    semantic_goal = getattr(mission, "semantic_goal", None)
    return str(getattr(semantic_goal, "query", "") or fallback)
