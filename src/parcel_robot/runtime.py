from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from parcel_robot.agent import EMERGENCY_STOP_PHRASES, VoiceAgent
from parcel_robot.audio_io import AudioDeviceStatus, detect_audio_devices
from parcel_robot.backends.base import SimObservation, SimulatorBackend
from parcel_robot.brain import (
    IntentFrame,
    InterruptRequest,
    ObservationSnapshot,
    PlanIR,
    PlanSketch,
    PlanValidationError,
    PlanValidator,
    SemanticRuntimeState,
    SemanticTaskRuntimeAdapter,
    SkillContractRegistry,
    TaskExecutive,
    admitted_plan_schema,
    admitted_plan_sketch_schema,
    compile_plan_contracts,
    materialize_planner_output,
)
from parcel_robot.brain.observations import (
    build_observation_snapshot,
    task_state_from_executive,
)
from parcel_robot.config import ConfigStore
from parcel_robot.context import (
    CallableContextProvider,
    ClockContextProvider,
    ContextBuildConfig,
    ContextBuilder,
    ContextField,
)
from parcel_robot.control import (
    BufferedRobotStateSource,
    ControlManager,
    ControlNotReadyError,
    build_backend_control_manager,
)
from parcel_robot.core import (
    ActivityContext,
    ActivityCoordinator,
    CommandArbiter,
    MotionIntent,
    VelocitySmoother,
)
from parcel_robot.memory import ConversationMemory
from parcel_robot.models import ActionProposal, Pose, SpatialIntent, VelocityCommand
from parcel_robot.motion import build_motion_router
from parcel_robot.navigation.follow import FollowConfig, FollowOwnerController
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)
from parcel_robot.navigation.semantic_map import (
    lidar_payload_from_observation,
    semantic_candidates_from_observation,
)
from parcel_robot.navigation.spatial import SpatialBehaviorConfig, SpatialBehaviorController
from parcel_robot.observability import ComponentMetrics, LatencyTracker
from parcel_robot.perception import NullMapProvider, PerceptionContract
from parcel_robot.prompting import PromptLibrary
from parcel_robot.providers import LanguageModel
from parcel_robot.skills.api import Dog
from parcel_robot.voice_pipeline import DuplexVoiceSession, VoiceStage, VoiceTurn


class RobotRuntime:
    """Own command arbitration, behavior loops, telemetry, and agent execution."""

    def __init__(
        self,
        config_path: str | Path,
        backend: SimulatorBackend,
        *,
        language_model: LanguageModel | None = None,
        planner_model: LanguageModel | None = None,
        audio_status: AudioDeviceStatus | None = None,
        loop_hz: float = 10.0,
        control_manager: ControlManager | None = None,
    ):
        if loop_hz <= 0:
            raise ValueError("loop_hz must be positive")
        self.store = ConfigStore(config_path)
        self.backend = backend
        self.loop_period = 1.0 / loop_hz
        self.arbiter = CommandArbiter(self.store.safety_limits())
        self._synchronous_control_dispatch = control_manager is None
        if control_manager is None:
            control_config = self.store.section("control")
            configured_controller = str(control_config.get("controller", "simulator"))
            if configured_controller != "simulator":
                raise ValueError(
                    "RobotRuntime requires an explicit control_manager for physical "
                    "controllers; configuration alone cannot arm hardware"
                )
            control_manager, state_source = build_backend_control_manager(
                backend,
                control_config,
                self.store.safety_limits(),
            )
            self._control_state_source: BufferedRobotStateSource | None = state_source
        else:
            self._control_state_source = (
                control_manager.state_source
                if isinstance(control_manager.state_source, BufferedRobotStateSource)
                else None
            )
        self.control_manager = control_manager
        smoother_config = self.store.motion_config().get("smoothing") or {}
        if not isinstance(smoother_config, dict):
            raise TypeError("motion.smoothing must be a mapping")
        self.velocity_smoother = VelocitySmoother(
            linear_accel=float(smoother_config.get("linear_accel", 0.9)),
            linear_decel=float(smoother_config.get("linear_decel", 1.4)),
            yaw_accel=float(smoother_config.get("yaw_accel", 1.8)),
        )
        self.perception = PerceptionContract.from_config(self.store.section("perception"))
        self.maps = NullMapProvider()
        safety_config = self.store.section("safety")
        self.obstacle_stop_m = float(safety_config.get("obstacle_stop_m", 0.65))
        self.obstacle_slow_m = float(safety_config.get("obstacle_slow_m", 1.2))
        self.person_stop_m = float(safety_config.get("person_stop_m", 1.0))
        self.person_slow_m = float(safety_config.get("person_slow_m", 2.0))
        self.telemetry_stale_s = float(safety_config.get("telemetry_stale_s", 0.6))
        if not 0 < self.obstacle_stop_m < self.obstacle_slow_m:
            raise ValueError("safety obstacle distances must satisfy 0 < stop < slow")
        if not 0 < self.person_stop_m < self.person_slow_m:
            raise ValueError("safety person distances must satisfy 0 < stop < slow")
        if not math.isfinite(self.telemetry_stale_s) or self.telemetry_stale_s <= 0:
            raise ValueError("safety telemetry_stale_s must be positive and finite")
        spatial_config = self.store.section("spatial_behaviors")
        spatial_limits = SpatialBehaviorConfig(
            step_length_m=float(spatial_config.get("step_length_m", 0.25)),
            max_steps=int(spatial_config.get("max_steps", 12)),
            default_orbit_radius_m=float(spatial_config.get("default_orbit_radius_m", 1.6)),
            min_orbit_radius_m=float(spatial_config.get("min_orbit_radius_m", 1.3)),
            max_orbit_radius_m=float(spatial_config.get("max_orbit_radius_m", 2.0)),
            max_revolutions=float(spatial_config.get("max_revolutions", 1.0)),
            owner_collision_envelope_m=float(
                spatial_config.get("owner_collision_envelope_m", 0.55)
            ),
            orbit_clearance_margin_m=float(spatial_config.get("orbit_clearance_margin_m", 0.10)),
            owner_anchor_tolerance_m=float(spatial_config.get("owner_anchor_tolerance_m", 0.60)),
            stall_timeout_s=float(spatial_config.get("stall_timeout_s", 20.0)),
            timeout_s=float(spatial_config.get("timeout_s", 120.0)),
        )
        minimum_safe_orbit = spatial_limits.minimum_safe_orbit_radius(self.obstacle_stop_m)
        if spatial_limits.min_orbit_radius_m + 1e-9 < minimum_safe_orbit:
            raise ValueError(
                "spatial min_orbit_radius_m must clear the owner collision envelope "
                f"and safety stop distance (minimum {minimum_safe_orbit:.2f} m)"
            )
        self.spatial = SpatialBehaviorController(spatial_limits)
        self.reactive_safety_policy = ReactiveSafetyPolicy(
            obstacle_stop_m=self.obstacle_stop_m,
            obstacle_slow_m=self.obstacle_slow_m,
            person_stop_m=self.person_stop_m,
            person_slow_m=self.person_slow_m,
            telemetry_stale_s=self.telemetry_stale_s,
            owner_collision_envelope_m=spatial_limits.owner_collision_envelope_m,
            orbit_clearance_margin_m=spatial_limits.orbit_clearance_margin_m,
            orbit_waypoint_tolerance_m=spatial_limits.waypoint_tolerance_m,
        )
        follow_config = self.store.section("owner_follow")
        # The shared runtime safety envelope is authoritative. A formation
        # cannot configure itself to pass closer to a person/owner than the
        # final actuator gate permits.
        follow_config.update(
            {
                "person_stop_m": self.person_stop_m,
                "person_slow_m": self.person_slow_m,
                "owner_collision_envelope_m": spatial_limits.owner_collision_envelope_m,
            }
        )
        minimum_owner_keepout = self.person_stop_m + spatial_limits.owner_collision_envelope_m
        configured_keepout = float(follow_config.get("owner_keepout_m", minimum_owner_keepout))
        if configured_keepout + 1e-9 < minimum_owner_keepout:
            raise ValueError(
                "owner_follow.owner_keepout_m must include the runtime person stop "
                "distance and owner collision envelope"
            )
        follow_config["owner_keepout_m"] = configured_keepout
        self.follow = FollowOwnerController(
            FollowConfig.from_mapping(follow_config),
            safety_policy=self.reactive_safety_policy,
        )
        self._spatial_detail: dict[str, object] = self.spatial.snapshot()
        self._monitor_audio = audio_status is None
        self.audio_status = audio_status or detect_audio_devices()
        self._observation: SimObservation | None = None
        self._follow_detail: dict[str, object] = self.follow.snapshot()
        self._navigation_directive: str | None = None
        self._navigation_detail: dict[str, object] = {
            "enabled": False,
            "state": "idle",
            "directive": None,
            "goal": None,
            "reason": "navigation_disabled",
        }
        self._sim_status = "starting"
        self._sim_error = ""
        resolved_planner_model = planner_model if planner_model is not None else language_model
        model_providers = {
            role: provider
            for role, provider in (
                ("conversation", language_model),
                ("planner", resolved_planner_model),
            )
            if provider is not None
        }
        self._model_role_status = {role: "configured" for role in model_providers}
        self._model_health_urls = {
            role: f"{str(base_url).rstrip('/')}/health"
            for role, provider in model_providers.items()
            if (base_url := getattr(provider, "base_url", ""))
        }
        self._model_status = "configured" if model_providers else "deterministic"
        if not model_providers:
            self._model_detail = "LLM optional"
        elif language_model is not None and resolved_planner_model is language_model:
            self._model_detail = f"shared {type(language_model).__name__}"
        else:
            self._model_detail = ", ".join(
                f"{role}={type(provider).__name__}" for role, provider in model_providers.items()
            )
        self._events: deque[dict[str, object]] = deque(maxlen=100)
        self._chat: deque[dict[str, object]] = deque(maxlen=80)
        self._event_id = 0
        metrics_config = self.store.section("metrics")
        self.latency = LatencyTracker(max_turns=int(metrics_config.get("max_turns", 200)))
        self.component_metrics = ComponentMetrics(
            samples_per_component=int(metrics_config.get("component_samples", 512))
        )
        self._lock = threading.RLock()
        self._agent_lock = threading.Lock()
        self._navigation_lock = threading.RLock()
        self._command_lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._behavior_generation = 0
        self._closed = False
        self._close_complete = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._health_thread: threading.Thread | None = None
        self._last_sent = VelocityCommand()
        self._last_send_at = 0.0
        self._was_moving = False
        self._proximity_state = "clear"
        agent_config = self.store.agent_config()
        context_config = ContextBuildConfig.from_mapping(self.store.section("query_context"))
        self.context_builder = ContextBuilder(
            context_config,
            {
                "time": ClockContextProvider(
                    str(self.store.section("query_context").get("timezone", "America/New_York"))
                ),
                "location": CallableContextProvider("location", self._location_context),
                "scene": CallableContextProvider("scene", self._scene_context),
            },
        )
        self.prompt_library = PromptLibrary(self.store.prompts_root())
        self._personality = str(agent_config.get("personality", "gentle_companion"))
        self._function_profiles = agent_config.get(
            "functions", ["companion", "navigator", "manual_assistant"]
        )
        if not isinstance(self._function_profiles, list) or not all(
            isinstance(item, str) for item in self._function_profiles
        ):
            raise TypeError("agent.functions must be a list of profile IDs")
        personality = self.prompt_library.personality(self._personality)
        for function_id in self._function_profiles:
            self.prompt_library.function(function_id)
        affect_config = agent_config.get("affect") or {}
        if not isinstance(affect_config, dict):
            raise TypeError("agent.affect must be a mapping")
        self._affect_minimum_confidence = float(affect_config.get("minimum_confidence", 0.75))
        if not 0.0 <= self._affect_minimum_confidence <= 1.0:
            raise ValueError("agent affect minimum_confidence must be between zero and one")
        self.activities = ActivityCoordinator(
            proposal_ttl_s=float(affect_config.get("proposal_ttl_s", 20.0)),
            cooldown_s=float(affect_config.get("social_action_cooldown_s", 8.0)),
        )
        self._activity_complete_at = 0.0
        self._voice_detail: dict[str, object] = {
            "mode": "text",
            "status": "idle",
            "partial": "",
            "last_turn_id": None,
            "last_transcript": "",
            "last_reply": "",
            "superseded": False,
        }

        motion = build_motion_router(
            self.store.motion_config(),
            on_command=self._voice_motion,
            on_stop=self.stop_motion,
        )
        self.dog = Dog.from_config(
            config_path,
            motion=motion,
            on_pose=self._run_pose,
            on_trajectory=self._run_trajectory,
        )
        brain_config = agent_config.get("brain") or {}
        if not isinstance(brain_config, dict):
            raise TypeError("agent.brain must be a mapping")
        self._brain_enabled = bool(brain_config.get("enabled", True))
        self._planner_output_contract = str(
            brain_config.get("planner_output_contract", "plan_ir_v1")
        )
        if self._planner_output_contract not in {"plan_ir_v1", "plan_sketch_v1"}:
            raise ValueError(
                "agent.brain.planner_output_contract must be plan_ir_v1 or plan_sketch_v1"
            )
        configured_brain_skills = brain_config.get(
            "skills", sorted(SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS)
        )
        if not isinstance(configured_brain_skills, list) or not all(
            isinstance(item, str) for item in configured_brain_skills
        ):
            raise TypeError("agent.brain.skills must be a list of semantic skill names")
        unsupported_brain_skills = set(configured_brain_skills) - (
            SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS
        )
        if unsupported_brain_skills:
            raise ValueError(
                "agent.brain contains skills without runtime adapters: "
                f"{sorted(unsupported_brain_skills)}"
            )
        self.brain_registry = SkillContractRegistry.default(
            owner_heading_supported=True,
        ).restricted(configured_brain_skills)
        self.plan_validator = PlanValidator(
            self.brain_registry,
            maximum_total_timeout_s=float(brain_config.get("maximum_total_timeout_s", 600.0)),
        )
        self.task_executive = TaskExecutive(
            max_records=int(brain_config.get("max_task_records", 256))
        )
        self.semantic_tasks = SemanticTaskRuntimeAdapter(
            navigate=self._start_brain_navigation,
            follow_formation=self._start_brain_follow_formation,
            spatial_behavior=self._start_brain_spatial_behavior,
            hold=self.stop_motion,
            vocalize=self._brain_vocalize,
        )
        self._brain_snapshot_sequence = 0
        self._last_brain_plan: dict[str, object] | None = None
        memory_cfg = self.store.section("memory")
        self.agent = VoiceAgent(
            self.dog.poses() or self.store.poses(),
            self.store.load_modules(),
            self._run_pose,
            language_model=language_model,
            planner_model=planner_model,
            stop_publisher=self.emergency_stop,
            memory=ConversationMemory(memory_cfg.get("path", ":memory:")),
            motion=motion,
            safety_limits=self.store.safety_limits(),
            behavior_publisher=self.set_behavior,
            navigation_publisher=self.start_navigation,
            spatial_behavior_publisher=self.start_spatial_behavior,
            action_proposal_publisher=self.propose_action,
            system_prompt_provider=self._render_system_prompt,
            affect_minimum_confidence=self._affect_minimum_confidence,
            affect_actions=personality.affect_actions,
            conversation_history_messages=int(
                agent_config.get("conversation_history_messages", 16)
            ),
            planning_context_provider=(self._build_brain_snapshot if self._brain_enabled else None),
            plan_publisher=self._accept_plan if self._brain_enabled else None,
            planner_system_prompt_provider=(
                (lambda: self.prompt_library.planner_system(self._planner_output_contract))
                if self._brain_enabled
                else None
            ),
            planner_schema_provider=(self._brain_plan_schema if self._brain_enabled else None),
            planner_skill_contracts_provider=(
                self.plan_validator.prompt_contract if self._brain_enabled else None
            ),
            planner_output_adapter=(
                self._materialize_brain_planner_output if self._brain_enabled else None
            ),
            dog=self.dog,
        )
        # Feed the duplex coordinator through ``handle_text`` so streamed ASR
        # finals and ordinary HTTP commands share logging, serialization, and
        # the same deterministic safety boundary. Audio output is intentionally
        # absent while this host has no connected playback endpoint.
        self.voice_session = DuplexVoiceSession(
            self,
            on_turn=self._voice_turn_completed,
            on_partial=self._voice_partial_received,
            on_error=self._voice_error,
            on_stage=self._voice_stage,
        )
        self._emit("runtime", "Runtime initialized", "success")

    def _brain_plan_schema(self) -> dict[str, object]:
        if self._planner_output_contract == "plan_sketch_v1":
            return admitted_plan_sketch_schema(
                self.prompt_library.schema("plan_sketch_v1.schema.json"),
                self.brain_registry.names(),
            )
        return admitted_plan_schema(
            self.prompt_library.schema("plan_ir_v1.schema.json"),
            self.brain_registry.names(),
        )

    def _materialize_brain_planner_output(
        self,
        output: PlanIR | PlanSketch,
        frame: IntentFrame,
        snapshot: ObservationSnapshot,
    ) -> PlanIR:
        """Adapt the configured model contract to the existing PlanIR runtime."""

        return materialize_planner_output(
            output,
            frame,
            snapshot,
            self.brain_registry,
        )

    def _build_brain_snapshot(self, *, now: float | None = None):
        """Build the planner's camera/LiDAR-only view from captured state."""

        timestamp = time.monotonic() if now is None else float(now)
        executive = self.task_executive.snapshot()
        rows = executive.get("tasks", [])
        active_row = next(
            (
                row
                for row in rows
                if isinstance(row, dict)
                and row.get("state") not in {"succeeded", "failed", "cancelled"}
            ),
            None,
        )
        control = self.control_manager.snapshot(now=timestamp)
        with self._lock:
            observation = self._observation
            self._brain_snapshot_sequence += 1
            sequence = self._brain_snapshot_sequence
        return build_observation_snapshot(
            observation,
            snapshot_id=f"runtime-snapshot-{sequence}",
            now=timestamp,
            sensor_stale_s=self.telemetry_stale_s,
            camera_enabled="camera" in self.perception.spatial_sensors,
            lidar_enabled="lidar" in self.perception.spatial_sensors,
            controller_state=f"{control.controller}:{control.lifecycle.value}",
            measured_velocity=control.measured,
            emergency_stopped=(self.arbiter.emergency_stopped or control.emergency_stopped),
            obstacle_stop_m=self.obstacle_stop_m,
            person_stop_m=self.person_stop_m,
            task=task_state_from_executive(active_row),
            resource_leases=self.task_executive.resources.leases(),
            owner_heading_available=self.owner_heading_available(now=timestamp),
        )

    def _accept_plan(
        self,
        plan: PlanIR,
        frame: IntentFrame,
        transcript: str,
    ) -> str:
        """Revalidate fresh state, apply system interruption policy, and queue."""

        del transcript  # IntentFrame owns the immutable transcript reference/hash.
        if not self._brain_enabled:
            raise RuntimeError("deliberative planning is disabled")
        if self._closed:
            raise RuntimeError("runtime is closed")
        if frame.route != "deliberative_plan":
            raise ValueError("only deliberative IntentFrames may publish PlanIR")
        if plan.source_turn_id != frame.turn_id:
            raise ValueError("PlanIR source turn does not match IntentFrame")

        plan = compile_plan_contracts(plan, self.brain_registry)

        snapshot = self._build_brain_snapshot()
        validation_started = time.monotonic()
        validated = self.plan_validator.validate(plan, snapshot)
        validated_at = time.monotonic()
        self.component_metrics.observe_ms(
            "PlanValidation", (validated_at - validation_started) * 1000.0
        )
        self.agent.last_brain_metrics["_plan_validated_monotonic"] = validated_at

        executive_before = self.task_executive.snapshot()
        active_rows = [
            row
            for row in executive_before.get("tasks", [])
            if isinstance(row, dict)
            and row.get("state") not in {"succeeded", "failed", "cancelled"}
        ]
        acceptance_started = time.monotonic()
        if frame.speech_act == "correction" and active_rows:
            current = active_rows[0]
            if plan.task_id != current.get("task_id"):
                raise PlanValidationError(
                    "correction_task_mismatch",
                    "a correction must revise the currently identified task",
                    path="$.task_id",
                )
            submission = self.task_executive.replace(validated)
        else:
            task_class = (
                "voice"
                if all(step.effective_resources == ("voice",) for step in validated.steps)
                else "explicit_action"
            )
            submission = self.task_executive.submit(
                validated,
                task_class=task_class,
            )
            if submission.accepted:
                for row in active_rows:
                    task_id = row.get("task_id")
                    if not isinstance(task_id, str) or task_id == plan.task_id:
                        continue
                    self.task_executive.request_interrupt(
                        InterruptRequest(
                            source="correction",
                            reason="new explicit owner plan accepted",
                            requested="at_checkpoint",
                            target_task_id=task_id,
                        )
                    )
        if not submission.accepted:
            raise RuntimeError(f"task executive rejected plan: {submission.reason}")
        accepted_at = time.monotonic()
        self.component_metrics.observe_ms(
            "PlanAcceptance", (accepted_at - acceptance_started) * 1000.0
        )
        self.agent.last_brain_metrics["_plan_accepted_monotonic"] = accepted_at
        with self._lock:
            self._last_brain_plan = {
                "task_id": plan.task_id,
                "plan_revision": plan.plan_revision,
                "source_turn_id": plan.source_turn_id,
                "goal": plan.goal.as_dict(),
                "steps": [step.skill for step in plan.steps],
                "effective_invariants": list(validated.effective_invariants),
                "disposition": submission.disposition,
                "validated_snapshot_id": snapshot.snapshot_id,
            }
        self._reconcile_semantic_tasks()
        self._emit(
            "brain",
            f"Accepted plan {plan.task_id} revision {plan.plan_revision}",
            "success",
        )
        return self._plan_acknowledgement(plan)

    @staticmethod
    def _plan_acknowledgement(plan: PlanIR) -> str:
        goal = plan.goal
        target = goal.target.query.strip()
        if goal.relation == "inside":
            return f"Okay—I'll move onto {target or 'the requested area'} and verify it."
        if goal.relation == "near":
            return f"Okay—I'll go wait near {target or 'that landmark'} safely."
        if goal.relation == "orbit":
            return "Okay—I'll make the requested local circle around you safely."
        if goal.relation == "behind":
            return "Okay—I'll take up a safe position behind you."
        if goal.relation == "relative":
            return "Okay—I'll make that bounded move and verify the distance."
        if goal.relation == "safe_pose":
            return "Okay—I'll move to a safe place and settle there."
        return "Okay—I accepted the task and will carry it out safely."

    def _brain_vocalize(self, text: str) -> None:
        clean = " ".join(str(text).split())
        if not clean:
            raise ValueError("brain utterance is empty")
        self._chat_item("assistant", clean)
        self._emit("brain", clean, "info")

    def _brain_runtime_state(self, snapshot) -> SemanticRuntimeState:
        with self._lock:
            navigation = dict(self._navigation_detail)
            spatial = dict(self._spatial_detail)
            follow = dict(self._follow_detail)
        control = self.control_manager.snapshot()
        return SemanticRuntimeState(
            snapshot_id=snapshot.snapshot_id,
            navigation_enabled=bool(navigation.get("enabled", False)),
            navigation_state=str(navigation.get("state", "idle")),
            navigation_goal=(
                str(navigation["goal"]) if navigation.get("goal") is not None else None
            ),
            navigation_reason=str(navigation.get("reason", "")),
            spatial_enabled=bool(spatial.get("enabled", False)),
            spatial_state=str(spatial.get("state", "idle")),
            spatial_reason=str(spatial.get("reason", "")),
            follow_enabled=self.follow.enabled,
            follow_state=str(follow.get("state", self.follow.state)),
            follow_mode=str(follow.get("mode", self.follow.mode)),
            stop_confirmed=control.stop_confirmed,
            control_feedback_fresh=(
                control.feedback_age_ms is not None
                and control.feedback_age_ms <= self.control_manager.timing.state_timeout_s * 1000.0
            ),
            robot_moving=snapshot.robot.moving,
        )

    def _step_brain(self) -> None:
        """Advance the bounded executive at control rate; never call an LLM."""

        if not self._brain_enabled:
            return
        started = time.monotonic()
        snapshot = self._build_brain_snapshot(now=started)
        state = self._brain_runtime_state(snapshot)
        for result in self.semantic_tasks.poll(state, now=started):
            disposition = self.task_executive.report(result)
            if disposition.action in {"task_succeeded", "task_failed", "task_cancelled"}:
                level = "success" if disposition.action == "task_succeeded" else "warning"
                self._emit(
                    "brain",
                    f"{result.task_id}: {disposition.action}",
                    level,
                )

        requests = self.task_executive.tick(snapshot, now=started)
        self._reconcile_semantic_tasks()
        for request in requests:
            try:
                immediate = self.semantic_tasks.dispatch(request, now=started)
            except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
                self.task_executive.dispatch_failed(request, str(error))
                self._emit(
                    "brain",
                    f"{request.skill} dispatch failed: {error}",
                    "error",
                )
                continue
            if immediate is not None:
                self.task_executive.report(immediate)
        self.component_metrics.elapsed("ExecutiveTick", started)

    def _reconcile_semantic_tasks(self) -> None:
        executive = self.task_executive.snapshot()
        valid = []
        for row in executive.get("tasks", []):
            if not isinstance(row, dict) or row.get("state") not in {
                "running",
                "waiting_checkpoint",
            }:
                continue
            task_id = row.get("task_id")
            revision = row.get("plan_revision")
            step_id = row.get("step_id")
            attempt = row.get("attempt")
            if (
                isinstance(task_id, str)
                and isinstance(revision, int)
                and isinstance(step_id, str)
                and isinstance(attempt, int)
            ):
                valid.append((task_id, revision, step_id, attempt))
        removed = self.semantic_tasks.reconcile(valid)
        if removed:
            self._stop_semantic_dispatches(removed, "task_no_longer_active")

    def _stop_semantic_dispatches(self, dispatches, reason: str) -> None:
        skills = {item.request.skill for item in dispatches}
        with self._command_lock:
            if "NavigateTo" in skills:
                self.stop_navigation()
            if {"OrbitOwner", "MoveRelative"} & skills:
                self._stop_spatial_locked(reason)
            if "FollowFormation" in skills:
                self.follow.stop()
                self.arbiter.cancel("follow")
                with self._lock:
                    self._follow_detail = self.follow.snapshot()

    def _interrupt_brain(self, source: str, reason: str) -> None:
        if not self._brain_enabled:
            return
        self.task_executive.request_interrupt(
            InterruptRequest(
                source=source,
                reason=reason,
                requested="interrupt_now",
            )
        )
        # The executive, not the caller, decides whether this source may stop
        # immediately or must wait for a checkpoint. Reconciliation removes
        # only work whose executive record is actually no longer active.
        self._reconcile_semantic_tasks()

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("runtime is closed")
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        try:
            self.control_manager.start(threaded=not self._synchronous_control_dispatch)
            self._thread = threading.Thread(
                target=self._control_loop,
                name="parcel-control-loop",
                daemon=True,
            )
            self._thread.start()
            self._health_thread = threading.Thread(
                target=self._service_health_loop,
                name="parcel-service-health",
                daemon=True,
            )
            self._health_thread.start()
        except BaseException as start_error:
            # A reported startup failure must never leave a physical manager or
            # a successfully started sibling thread alive. close() also knows
            # how to skip Thread objects whose start() never assigned an ident.
            self._stop_event.set()
            try:
                self.close()
            except BaseException as cleanup_error:
                raise RuntimeError(
                    f"runtime startup failed ({start_error!r}) and cleanup did not complete"
                ) from cleanup_error
            raise

    def close(self) -> None:
        with self._close_lock:
            if self._close_complete:
                return
            if not self._closed:
                # `_closed` is the irreversible command/API latch. Teardown is
                # tracked separately so a bounded controller close that asks
                # for a retry remains reachable on the next close() call.
                self._closed = True
                self._stop_event.set()
                with self._command_lock:
                    self._interrupt_brain("system_recovery", "runtime_closed")
                    self.follow.stop()
                    self.stop_navigation()
                    self._stop_spatial_locked("runtime_closed")
                    self.agent.safety.engage_emergency_stop()
                    self.activities.clear("runtime_closed")
                    self._activity_complete_at = 0.0
                    self.arbiter.engage_emergency_stop()
                    try:
                        self.control_manager.emergency_stop()
                    except (OSError, RuntimeError):
                        pass
                    self._last_sent = VelocityCommand()
                    self._was_moving = False
                    self.velocity_smoother.reset()
            auxiliary_error: BaseException | None = None
            try:
                self.voice_session.close(timeout=2.0)
            except BaseException as error:  # noqa: BLE001 - hardware teardown must continue
                auxiliary_error = error
            for thread, timeout in (
                (self._thread, 2.0),
                (self._health_thread, 3.0),
            ):
                if thread is None or thread is threading.current_thread() or thread.ident is None:
                    continue
                try:
                    thread.join(timeout=timeout)
                except RuntimeError as error:
                    auxiliary_error = auxiliary_error or error
            # A bounded manager close can intentionally raise and require a
            # retry; assignment below is deliberately after the call.
            self.control_manager.close()
            self._close_complete = True
            if auxiliary_error is not None:
                raise auxiliary_error

    def submit_motion(
        self,
        source: str,
        command: VelocityCommand,
        *,
        ttl: float = 0.35,
    ) -> str:
        if self._closed:
            raise RuntimeError("runtime is closed")
        intent = MotionIntent(command=command, source=source, ttl=ttl)
        result = self.arbiter.submit(intent)
        if not result.accepted:
            if source not in {"follow", "navigation"}:
                self._emit("safety", result.reason, "warning")
            raise RuntimeError(result.reason)
        return result.reason

    def manual_motion(self, vx: float, vy: float, vyaw: float) -> str:
        values = (float(vx), float(vy), float(vyaw))
        if any(not math.isfinite(value) for value in values):
            raise ValueError("manual velocity must be finite")
        if all(abs(value) < 1e-9 for value in values):
            self._interrupt_brain("manual", "manual stop acquired the base")
            self.stop_motion()
            return "Manual motion stopped"
        # Serialize ownership acquisition with activity dispatch. If an action
        # already crossed the dispatch boundary this waits for it, then manual
        # control becomes authoritative before returning to the operator.
        with self._command_lock:
            self._interrupt_brain("manual", "manual control acquired the base")
            with self._lock:
                self._behavior_generation += 1
            self._stop_spatial_locked("manual_control")
            return self.submit_motion(
                "manual",
                VelocityCommand(vx=values[0], vy=values[1], vyaw=values[2]),
                ttl=0.45,
            )

    def _voice_motion(self, command: VelocityCommand) -> None:
        """Give an explicit locomotion command clean ownership of the body."""

        with self._command_lock:
            self._interrupt_brain("correction", "owner issued a direct motion command")
            self.follow.stop()
            self.stop_navigation()
            with self._lock:
                self._behavior_generation += 1
            self._stop_spatial_locked("voice_motion_started")
            self.activities.clear("voice_motion_started")
            self._activity_complete_at = 0.0
            self.submit_motion("voice", command, ttl=1.0)

    def stop_motion(self) -> None:
        with self._command_lock:
            with self._lock:
                self._behavior_generation += 1
            self._stop_spatial_locked("motion_stopped")
            self.arbiter.stop()
            with self._lock:
                simulator_feedback_available = self._observation is not None
            if not self._synchronous_control_dispatch or simulator_feedback_available:
                try:
                    self._ensure_compatibility_control_started()
                    self.control_manager.stop("runtime_stop")
                except (OSError, RuntimeError) as error:
                    self._record_sim_error(error)
            self._last_sent = VelocityCommand()
            self._was_moving = False
            self.velocity_smoother.reset()

    def emergency_stop(self) -> None:
        with self._command_lock:
            self._interrupt_brain("emergency", "emergency stop latched")
            self.follow.stop()
            self.stop_navigation()
            self._stop_spatial_locked("emergency_stop")
            self.activities.clear("emergency_stop")
            self._activity_complete_at = 0.0
            self.arbiter.engage_emergency_stop()
            try:
                self.control_manager.emergency_stop()
            except (OSError, RuntimeError) as error:
                self._record_sim_error(error)
            self._last_sent = VelocityCommand()
            self._was_moving = False
            self.velocity_smoother.reset()
        self._emit("safety", "Emergency stop latched", "error")

    def clear_emergency_stop(self) -> str:
        if self._closed:
            raise RuntimeError("runtime is closed")
        with self._command_lock:
            deadline = time.monotonic() + self.control_manager.timing.stop_timeout_s
            while True:
                try:
                    self.control_manager.clear_emergency_stop()
                    break
                except ControlNotReadyError as error:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        self._record_sim_error(error)
                        raise RuntimeError(
                            "controller emergency stop could not be cleared"
                        ) from error
                    time.sleep(min(0.01, remaining))
                except (OSError, RuntimeError) as error:
                    self._record_sim_error(error)
                    raise RuntimeError("controller emergency stop could not be cleared") from error
            self.arbiter.clear_emergency_stop()
            self.agent.safety.clear_emergency_stop()
        self._emit("safety", "Emergency stop cleared by operator", "warning")
        return "Emergency stop cleared"

    def set_behavior(self, mode: str) -> str:
        if self._closed:
            raise RuntimeError("runtime is closed")
        self._interrupt_brain("correction", f"owner selected {mode} behavior")
        if mode in {"follow", "follow_behind"}:
            follow_mode = "behind" if mode == "follow_behind" else "direct"
            return self._enable_owner_follow(follow_mode)
        if mode == "stay":
            with self._command_lock:
                self.follow.stop()
                with self._lock:
                    self._behavior_generation += 1
                self.stop_navigation()
                self._stop_spatial_locked("owner_requested_stay")
                self.activities.clear("owner_requested_stay")
                self._activity_complete_at = 0.0
                self.stop_motion()
                with self._lock:
                    self._follow_detail = self.follow.snapshot()
            self._emit("behavior", "Holding position", "info")
            return "Holding position"
        raise ValueError(f"unknown behavior: {mode}")

    def start_follow_formation(
        self,
        relation: str = "behind",
        distance_m: float | None = None,
    ) -> str:
        """Start a semantic owner-relative formation without planner internals.

        This is the stable runtime boundary for a future ``FollowFormation``
        PlanIR skill. The controller, not the LLM, owns heading confidence,
        collision clearance, side staging, and stale-track failure behavior.
        """

        clean = str(relation).strip().lower()
        if clean != "behind":
            raise ValueError(f"unsupported owner formation relation: {relation}")
        self._interrupt_brain("correction", "owner requested a new follow formation")
        return self._start_brain_follow_formation(clean, distance_m)

    def _start_brain_follow_formation(
        self,
        relation: str,
        distance_m: float,
    ) -> str:
        if relation != "behind":
            raise ValueError(f"unsupported owner formation relation: {relation}")
        return self._enable_owner_follow("behind", distance_m=distance_m)

    def owner_heading_available(self, now: float | None = None) -> bool:
        """Passive camera-track gate for ``FollowFormation`` plan admission."""

        return self.follow.heading_available(now=now)

    def owner_heading_snapshot(self, now: float | None = None) -> dict[str, object]:
        return self.follow.heading_snapshot(now=now)

    def _enable_owner_follow(
        self,
        follow_mode: str,
        *,
        distance_m: float | None = None,
    ) -> str:
        if self._closed:
            raise RuntimeError("runtime is closed")
        with self._command_lock:
            if self._closed:
                raise RuntimeError("runtime is closed")
            if self.arbiter.emergency_stopped:
                raise RuntimeError("motion is disabled by emergency stop")
            self._stop_spatial_locked("owner_follow_started")
            self.stop_navigation()
            if follow_mode == "behind":
                self.follow.start_formation("behind", distance_m=distance_m)
            elif follow_mode == "direct" and distance_m is None:
                self.follow.start()
            else:
                raise ValueError(f"unknown follow mode: {follow_mode}")
            with self._lock:
                self._behavior_generation += 1
                self._follow_detail = self.follow.snapshot()
        message = (
            "Behind-owner formation enabled; acquiring motion heading"
            if follow_mode == "behind"
            else "Owner-follow enabled"
        )
        self._emit("behavior", message, "success")
        return message

    def start_navigation(self, directive: str) -> str:
        self._interrupt_brain("correction", "owner requested a new navigation task")
        return self._start_brain_navigation(directive)

    def _start_brain_navigation(self, directive: str) -> str:
        clean = " ".join(str(directive).split())
        if not clean:
            raise ValueError("navigation directive is empty")
        if len(clean) > 500:
            raise ValueError("navigation directive is too long")
        if self._closed:
            raise RuntimeError("runtime is closed")
        if self.arbiter.emergency_stopped:
            raise RuntimeError("motion is disabled by emergency stop")

        with self._command_lock:
            return self._start_navigation_locked(clean)

    def _start_navigation_locked(self, clean: str) -> str:
        """Start a mission while serialized against social-action dispatch."""

        if self._closed:
            raise RuntimeError("runtime is closed")
        if self.arbiter.emergency_stopped:
            raise RuntimeError("motion is disabled by emergency stop")
        self._stop_spatial_locked("navigation_started")
        self.follow.stop()
        with self._lock:
            self._behavior_generation += 1
            generation = self._behavior_generation
            observation = self._observation
            self._follow_detail = self.follow.snapshot()
        if observation is not None and not self._observation_is_fresh(observation):
            observation = None
        self.arbiter.cancel("follow")
        with self._navigation_lock:
            if observation is not None:
                self.dog.set_nav_pose(
                    (observation.robot.x, observation.robot.y, observation.robot.z),
                    math.degrees(observation.robot.yaw),
                )
            mission, command = self.dog.navigate(
                clean,
                nearest_person_m=(
                    observation.nearest_person_m if observation is not None else None
                ),
                nearest_obstacle_m=(
                    observation.nearest_obstacle_m if observation is not None else None
                ),
                publish=False,
                extras=self._navigation_extras(observation) if observation is not None else None,
            )
        place = (
            mission.goal.label or mission.goal.poi_id
            if mission.goal is not None
            else str(mission.metadata.get("semantic_query", clean))
        )
        with self._lock:
            if generation != self._behavior_generation or self.arbiter.emergency_stopped:
                raise RuntimeError("navigation request was canceled")
            self._navigation_directive = clean
            self._navigation_detail = {
                "enabled": not command.stop or mission.status == "verifying",
                "state": mission.status,
                "directive": clean,
                "goal": place,
                "reason": command.note,
            }
        if command.stop and mission.status == "arrived":
            with self._lock:
                self._navigation_directive = None
            message = f"Already at {place}."
        elif command.stop and mission.status == "verifying":
            self._request_navigation_terminal_stop()
            message = f"Stopping at {place} and verifying the final position."
        elif command.stop:
            with self._lock:
                self._navigation_directive = None
                self._navigation_detail["enabled"] = False
            message = f"I couldn't find or safely reach {place}."
        else:
            message = f"Navigating to {place}."
        self._emit(
            "navigation",
            message,
            (
                "info"
                if mission.status == "verifying"
                else "error"
                if command.stop and mission.status != "arrived"
                else "success"
            ),
        )
        return message

    def stop_navigation(self) -> None:
        with self._lock:
            self._behavior_generation += 1
            was_enabled = self._navigation_directive is not None
            self._navigation_directive = None
            if was_enabled:
                self._navigation_detail = {
                    **self._navigation_detail,
                    "enabled": False,
                    "state": "idle",
                    "reason": "navigation_disabled",
                }
        self.arbiter.cancel("navigation")
        if was_enabled:
            with self._navigation_lock:
                self.dog.stop()

    def start_spatial_behavior(self, intent: SpatialIntent) -> str:
        self._interrupt_brain("correction", "owner requested a new spatial behavior")
        return self._start_brain_spatial_behavior(intent)

    def _start_brain_spatial_behavior(self, intent: SpatialIntent) -> str:
        """Start one bounded local trajectory under the normal motion arbiter."""

        if self._closed:
            raise RuntimeError("runtime is closed")
        owner_relative = intent.direction == "away_from_owner" or intent.behavior == "orbit_owner"
        observation: SimObservation | None = None
        with self._command_lock:
            if self.arbiter.emergency_stopped:
                raise RuntimeError("motion is disabled by emergency stop")
            with self._lock:
                observed_generation = self._behavior_generation
                if not owner_relative:
                    observation = self._observation

        if owner_relative:
            # Device I/O stays outside the command lock so Stop/E-stop and
            # barge-in never wait for a simulator/network timeout. The captured
            # generation is revalidated atomically below before any action starts.
            observe_started = time.monotonic()
            try:
                observation = self.backend.observe()
            except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as error:
                raise RuntimeError(
                    f"fresh camera/LiDAR perception is unavailable: {error}"
                ) from error
            finally:
                self.component_metrics.elapsed("SpatialCommandObserve", observe_started)

        with self._command_lock:
            if self._closed:
                raise RuntimeError("runtime is closed")
            if self.arbiter.emergency_stopped:
                raise RuntimeError("motion is disabled by emergency stop")
            with self._lock:
                if observed_generation != self._behavior_generation:
                    raise RuntimeError("spatial request was canceled by a newer operator action")
            active = self.arbiter.current()
            if active is not None and active.source == "manual":
                raise RuntimeError("manual control currently owns motion")
            if owner_relative:
                with self._lock:
                    self._observation = observation
            if observation is None:
                raise RuntimeError("fresh camera/LiDAR perception is unavailable")
            if time.monotonic() - observation.timestamp > self.telemetry_stale_s:
                raise RuntimeError("camera/LiDAR perception is stale")
            self.follow.stop()
            self.stop_navigation()
            self._stop_spatial_locked("replaced_by_new_spatial_behavior")
            self.activities.clear("spatial_behavior_started")
            with self._lock:
                self._behavior_generation += 1
            detail = self.spatial.start(intent, observation)
            with self._lock:
                self._spatial_detail = detail

        if intent.behavior == "move_steps":
            if intent.direction == "away_from_owner":
                message = f"I'll back away {intent.steps} small steps while keeping you in view."
            else:
                message = f"I'll move {intent.direction} {intent.steps} small steps."
        else:
            if math.isclose(intent.revolutions, 1.0):
                amount = "one"
            elif math.isclose(intent.revolutions, 0.5):
                amount = "a half"
            elif math.isclose(intent.revolutions, 0.25):
                amount = "a quarter"
            else:
                amount = f"{intent.revolutions:g} of a"
            message = f"I'll make {amount} {intent.size} {intent.direction} circle around you."
        self._emit("spatial", message, "success")
        return message

    def _stop_spatial_locked(self, reason: str) -> None:
        if not self.spatial.active:
            return
        previous = self.spatial.snapshot()
        self.spatial.stop()
        self.arbiter.cancel("spatial")
        with self._lock:
            self._spatial_detail = {
                **previous,
                "enabled": False,
                "state": "cancelled",
                "reason": reason,
            }

    def action(self, name: str) -> str:
        if name == "follow":
            return self.set_behavior("follow")
        if name == "follow_behind":
            return self.start_follow_formation("behind")
        if name == "stay":
            return self.set_behavior("stay")
        if name == "stop":
            with self._command_lock:
                self._interrupt_brain("explicit_stop", "owner explicitly stopped motion")
                self.follow.stop()
                self.stop_navigation()
                self.activities.clear("operator_stop")
                self._activity_complete_at = 0.0
                self.stop_motion()
            self._emit("operator", "Motion stopped", "warning")
            return "Stopped"
        if name == "emergency_stop":
            self.emergency_stop()
            return "Emergency stop latched"
        if name == "clear_emergency_stop":
            return self.clear_emergency_stop()
        raise ValueError(f"unknown action: {name}")

    def list_personalities(self) -> list[dict[str, str]]:
        return [
            {"id": profile.id, "name": profile.name}
            for profile in self.prompt_library.list_personalities()
        ]

    def set_personality(self, profile_id: str) -> str:
        profile = self.prompt_library.personality(profile_id)
        # Voice turns acquire the locks in this order while composing a prompt;
        # keep the displayed profile and affect mapping as one coherent update.
        with self._agent_lock:
            with self._lock:
                self._personality = profile.id
            self.agent.configure_personality(profile.affect_actions)
        self._emit("agent", f"Personality changed to {profile.name}", "success")
        return f"Personality set to {profile.name}"

    def propose_action(self, proposal: ActionProposal) -> str:
        if proposal.kind != "skill":
            raise ValueError("only semantic skill proposals are supported")
        try:
            skill = self.dog.catalog.get(proposal.name)
        except KeyError as error:
            raise ValueError(f"unknown proposed skill: {proposal.name}") from error
        if skill.kind not in {"pose", "trajectory"}:
            raise ValueError("action proposals are limited to bounded pose/trajectory skills")
        context = self._activity_context()
        result = self.activities.submit(proposal, context)
        level = "info" if result.accepted else "warning"
        self._emit("activity", result.message, level)
        status = {
            "execute": "Accepted",
            "defer": "Deferred",
            "reject": "Rejected",
        }.get(result.disposition, "Rejected")
        return f"{status}: {result.message}"

    def _activity_context(self) -> ActivityContext:
        arbitration = self.arbiter.snapshot()
        with self._lock:
            navigation_active = self._navigation_directive is not None
        return ActivityContext(
            emergency_stopped=bool(arbitration["emergency_stopped"]),
            active_source=(
                str(arbitration["active_source"])
                if arbitration["active_source"] is not None
                else None
            ),
            navigation_active=navigation_active,
            follow_active=self.follow.enabled,
            physical_activity_active=self.activities.running() is not None,
        )

    def _step_activities(self) -> None:
        now = time.monotonic()
        running = self.activities.running()
        if running is not None:
            context = self._activity_context()
            preemptor = context.busy_reason
            if preemptor not in {None, "physical_activity"}:
                finished = self.activities.finish(
                    success=False,
                    detail=f"preempted_by_{preemptor}",
                    now=now,
                )
                self._activity_complete_at = 0.0
                if finished is not None:
                    self._emit(
                        "activity",
                        f"{finished.proposal.name} preempted by {preemptor}",
                        "warning",
                    )
                return
            if now >= self._activity_complete_at:
                finished = self.activities.finish(
                    success=True,
                    detail="duration_elapsed",
                    now=now,
                )
                self._activity_complete_at = 0.0
                if finished is not None:
                    self._emit(
                        "activity",
                        f"Completed {finished.proposal.name}",
                        "success",
                    )
            return

        record = self.activities.start_ready(self._activity_context(), now=now)
        if record is None:
            return
        # ``start_ready`` and physical dispatch are separate operations so that
        # coordinator callbacks never run while its lock is held. Revalidate
        # under the command lock: Stop/Stay/E-stop/manual/navigation use this
        # same boundary, preventing a cleared record from executing afterward.
        with self._command_lock:
            current = self.activities.running()
            context = self._activity_context()
            if (
                current is None
                or current.activity_id != record.activity_id
                or context.busy_reason not in {None, "physical_activity"}
                or self._closed
            ):
                if current is not None and current.activity_id == record.activity_id:
                    self.activities.finish(
                        success=False,
                        detail=f"dispatch_cancelled_by_{context.busy_reason or 'runtime'}",
                        now=now,
                    )
                self._activity_complete_at = 0.0
                return
            try:
                skill = self.dog.catalog.get(record.proposal.name)
                result = self.dog.execute(record.proposal.name)
                if not result.accepted:
                    raise RuntimeError(result.message)
                if skill.kind == "trajectory" and skill.keyframes:
                    duration = float(skill.keyframes[-1].t)
                else:
                    duration = float(skill.duration)
                self._activity_complete_at = now + max(0.1, min(30.0, duration + 0.15))
                self._emit("activity", f"Executing {record.proposal.name}", "success")
            except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
                self.activities.finish(success=False, detail=str(error), now=now)
                self._activity_complete_at = 0.0
                self._emit("activity", f"Action failed: {error}", "error")

    def _render_system_prompt(self) -> str:
        with self._lock:
            personality = self._personality
            functions = list(self._function_profiles)
        return self.prompt_library.render_system(
            personality_id=personality,
            function_ids=functions,
            runtime_context=self._prompt_runtime_context(),
        )

    def _prompt_runtime_context(self) -> dict[str, object]:
        arbitration = self.arbiter.snapshot()
        with self._lock:
            observation = self._observation
            navigation = dict(self._navigation_detail)
            personality = self._personality
        running = self.activities.running()
        if running is not None:
            active_kind = "skill"
            active_phase = running.proposal.name
            interruptibility = "immediate"
        elif navigation.get("enabled"):
            active_kind = "navigate"
            active_phase = str(navigation.get("state", "navigating"))
            interruptibility = "never"
        elif self.spatial.active:
            active_kind = "spatial_behavior"
            active_phase = str(self._spatial_detail.get("state", "moving"))
            interruptibility = "immediate"
        elif self.follow.enabled:
            active_kind = "follow"
            active_phase = self.follow.state
            interruptibility = "safe_checkpoint"
        elif arbitration["active_source"] is not None:
            active_kind = str(arbitration["active_source"])
            active_phase = "moving"
            interruptibility = "never"
        else:
            active_kind = "idle"
            active_phase = "idle"
            interruptibility = "safe_checkpoint"
        command = arbitration["command"]
        assert isinstance(command, dict)
        available_social = [
            skill.id
            for skill in self.dog.list_skills(tag="social")
            if skill.kind in {"pose", "trajectory"}
        ]
        result: dict[str, object] = {
            "active_activity": {
                "kind": active_kind,
                "phase": active_phase,
                "interruptibility": interruptibility,
            },
            "motion": {
                "source": arbitration["active_source"],
                "moving": any(abs(float(value)) > 1e-6 for value in command.values()),
            },
            "safety": {
                "emergency_stopped": arbitration["emergency_stopped"],
                "telemetry_fresh": (
                    observation is not None
                    and time.monotonic() - observation.timestamp <= self.telemetry_stale_s
                ),
                "nearest_obstacle_m": (
                    observation.nearest_obstacle_m if observation is not None else None
                ),
                "nearest_person_ttc_s": (
                    observation.nearest_person_ttc_s if observation is not None else None
                ),
            },
            "available_social_skills": available_social,
            "perception": self.perception.snapshot(self.maps),
            "personality": personality,
        }
        context = self.context_builder.build()
        if context.fields or context.errors:
            result["query_context"] = context.prompt_data(
                include_precise_coordinates=(
                    self.context_builder.config.include_precise_coordinates_in_prompt
                )
            )
        return result

    def _location_context(self, now: datetime) -> ContextField:
        with self._lock:
            observation = self._observation
        if observation is None:
            raise RuntimeError("localization unavailable")
        return ContextField(
            kind="location",
            source=f"{observation.backend}_localization",
            observed_at=now,
            value={
                "frame": "map",
                "area": "local robot operating area",
                "x": observation.robot.x,
                "y": observation.robot.y,
                "z": observation.robot.z,
                "heading_deg": math.degrees(observation.robot.yaw),
            },
            accuracy_m=0.05 if observation.backend == "mujoco" else None,
        )

    def _scene_context(self, now: datetime) -> ContextField:
        with self._lock:
            observation = self._observation
        if observation is None:
            raise RuntimeError("scene perception unavailable")
        labels = sorted({region.label for region in observation.semantic_regions})
        return ContextField(
            kind="scene",
            source=f"{observation.backend}_semantic_perception",
            observed_at=now,
            value={
                "visible_semantic_labels": labels,
                "candidate_count": len(observation.semantic_regions),
            },
        )

    def move_owner(self, dx: float, dy: float) -> str:
        if self._closed:
            raise RuntimeError("runtime is closed")
        dx, dy = float(dx), float(dy)
        if not math.isfinite(dx) or not math.isfinite(dy):
            raise ValueError("owner movement must be finite")
        if abs(dx) > 1.0 or abs(dy) > 1.0:
            raise ValueError("owner movement is limited to one meter per request")
        self.backend.move_owner(dx, dy)
        return f"Owner moved by ({dx:.2f}, {dy:.2f}) m"

    def _run_pose(self, pose: Pose) -> None:
        if self.arbiter.emergency_stopped:
            raise RuntimeError("motion is disabled by emergency stop")
        self.follow.stop()
        with self._command_lock:
            self._stop_spatial_locked("pose_started")
        with self._lock:
            self._behavior_generation += 1
        self.stop_navigation()
        with self._command_lock:
            if self.arbiter.emergency_stopped:
                raise RuntimeError("motion is disabled by emergency stop")
            self.arbiter.stop()
            self.control_manager.stop("pose_started")
            if not self._synchronous_control_dispatch:
                raise RuntimeError(
                    "physical poses must be implemented by the selected locomotion "
                    "controller; direct backend actuation is disabled"
                )
            self.backend.pose(pose)

    def _run_trajectory(self, skill: object) -> None:
        if self.arbiter.emergency_stopped:
            raise RuntimeError("motion is disabled by emergency stop")
        self.follow.stop()
        with self._command_lock:
            self._stop_spatial_locked("trajectory_started")
        with self._lock:
            self._behavior_generation += 1
        self.stop_navigation()
        with self._command_lock:
            if self.arbiter.emergency_stopped:
                raise RuntimeError("motion is disabled by emergency stop")
            self.arbiter.stop()
            self.control_manager.stop("trajectory_started")
            if not self._synchronous_control_dispatch:
                raise RuntimeError(
                    "physical trajectories must be implemented by the selected locomotion "
                    "controller; direct backend actuation is disabled"
                )
            self.backend.trajectory(skill)

    def handle_text(self, text: str) -> str:
        clean = " ".join(str(text).split())
        if not clean:
            raise ValueError("text command is empty")
        if len(clean) > 2000:
            raise ValueError("text command is too long")
        if self._closed and clean.lower() not in EMERGENCY_STOP_PHRASES:
            raise RuntimeError("runtime is closed")
        self._chat_item("user", clean)
        if clean.lower() in EMERGENCY_STOP_PHRASES:
            # Never queue a stop behind a slow model generation. The stop path
            # is deterministic, latches both safety supervisors, and causes a
            # concurrent model action to fail validation when it resumes.
            try:
                reply = self.agent.handle_text(clean)
            except (RuntimeError, TypeError, ValueError) as error:
                reply = f"I couldn't do that safely. {error}"
                self._emit("agent", str(error), "error")
        else:
            with self._agent_lock:
                try:
                    reply = self.agent.handle_text(clean)
                except (RuntimeError, TypeError, ValueError) as error:
                    reply = f"I couldn't do that safely. {error}"
                    self._emit("agent", str(error), "error")
        self._chat_item("assistant", reply)
        return reply

    def handle_text_guarded(
        self,
        text: str,
        commit: Callable[[Callable[[], str]], str],
    ) -> str:
        """Run model planning now but linearize its actions with the voice turn."""

        clean = " ".join(str(text).split())
        if not clean:
            raise ValueError("text command is empty")
        if len(clean) > 2000:
            raise ValueError("text command is too long")
        if clean.lower() in EMERGENCY_STOP_PHRASES:
            return self.handle_text(clean)
        if self._closed:
            raise RuntimeError("runtime is closed")
        self._chat_item("user", clean)
        with self._agent_lock:
            try:
                reply = self.agent.handle_text_guarded(clean, commit)
            except (RuntimeError, TypeError, ValueError) as error:
                reply = f"I couldn't do that safely. {error}"
                self._emit("agent", str(error), "error")
        self._chat_item("assistant", reply)
        return reply

    def submit_voice_text(self, text: str, *, is_final: bool = True) -> int | None:
        """Accept a partial/final transcript without ever executing partial text."""

        clean = " ".join(str(text).split())
        if not clean:
            raise ValueError("voice text is empty")
        if len(clean) > 2000:
            raise ValueError("voice text is too long")
        if is_final and clean.lower() in EMERGENCY_STOP_PHRASES:
            # Latch the safety boundary before touching the voice coordinator;
            # a committed slow action must not delay an emergency request on
            # the voice session lock.
            self.agent.safety.engage_emergency_stop()
            self.emergency_stop()
            self.voice_session.barge_in()
            self._chat_item("user", clean)
            reply = "Stopping."
            self._chat_item("assistant", reply)
            with self._lock:
                self._voice_detail = {
                    **self._voice_detail,
                    "status": "emergency_stop",
                    "partial": "",
                    "last_transcript": clean,
                    "last_reply": reply,
                    "superseded": False,
                }
            return None
        turn_id = self.voice_session.submit_text(clean, is_final=is_final)
        if turn_id is not None:
            with self._lock:
                # The worker can complete before this thread reacquires the
                # lock. Preserve that terminal state rather than regressing it.
                if self._voice_detail.get("last_turn_id") != turn_id:
                    self._voice_detail = {
                        **self._voice_detail,
                        "status": "processing",
                        "partial": "",
                    }
        return turn_id

    def cancel_reasoning(self) -> None:
        self.agent.cancel_reasoning()

    def interrupt_voice(self) -> str:
        self.voice_session.barge_in()
        with self._lock:
            self._voice_detail = {
                **self._voice_detail,
                "status": "interrupted",
                "partial": "",
            }
        return "Voice output interrupted"

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            observation = self._observation
            events = list(self._events)
            chat = list(self._chat)
            follow = dict(self._follow_detail)
            navigation = dict(self._navigation_detail)
            voice = dict(self._voice_detail)
            sim_status = self._sim_status
            sim_error = self._sim_error
            personality = self._personality
            spatial = dict(self._spatial_detail)
            last_brain_plan = (
                dict(self._last_brain_plan) if self._last_brain_plan is not None else None
            )
        if not self.follow.enabled:
            follow = self.follow.snapshot()
        robot: dict[str, object] = {"x": 0.0, "y": 0.0, "z": 0.0, "heading": 0.0}
        owner: dict[str, object] = {
            "id": "owner-1",
            "x": 0.0,
            "y": 0.0,
            "visible": False,
            "confidence": 0.0,
        }
        obstacle = None
        collision = False
        dynamic_agents: list[dict[str, object]] = []
        nearest_person: dict[str, object] | None = None
        if observation is not None:
            robot = {
                "x": observation.robot.x,
                "y": observation.robot.y,
                "z": observation.robot.z,
                "heading": math.degrees(observation.robot.yaw),
            }
            owner = {
                "id": observation.owner.owner_id,
                "x": observation.owner.x,
                "y": observation.owner.y,
                "visible": observation.owner.visible,
                "confidence": observation.owner.confidence,
            }
            obstacle = observation.nearest_obstacle_m
            collision = observation.collision
            dynamic_agents = [
                {
                    "id": track.agent_id,
                    "kind": track.kind,
                    "x": track.x,
                    "y": track.y,
                    "vx": track.vx,
                    "vy": track.vy,
                    "yaw": track.yaw,
                    "radius_m": track.radius_m,
                }
                for track in observation.dynamic_agents
            ]
            if observation.nearest_person_id is not None:
                nearest_person = {
                    "id": observation.nearest_person_id,
                    "distance_m": observation.nearest_person_m,
                    "bearing_rad": observation.nearest_person_bearing_rad,
                    "time_to_collision_s": observation.nearest_person_ttc_s,
                }
        arbitration = self.arbiter.snapshot()
        brain_tasks = self.task_executive.snapshot()
        return {
            "simulator": {
                "status": sim_status,
                "name": getattr(self.backend, "name", "simulator"),
                "detail": sim_error,
            },
            "agent": {
                "status": "ready",
                "active_source": arbitration["active_source"],
                "personality": personality,
                "personalities": self.list_personalities(),
            },
            "brain": {
                "enabled": self._brain_enabled,
                "architecture": "deterministic_router_shared_backbone_semantic_planner",
                "planner_output_contract": self._planner_output_contract,
                "admitted_skills": list(self.brain_registry.names()),
                "last_plan": last_brain_plan,
                **brain_tasks,
            },
            "follow": follow,
            "navigation": navigation,
            "spatial_behavior": spatial,
            "audio": self.audio_status.as_dict(),
            "perception": self.perception.snapshot(self.maps),
            "voice": voice,
            "model": {
                "status": self._model_status,
                "detail": self._model_detail,
                "roles": dict(self._model_role_status),
            },
            "robot": robot,
            "owner": owner,
            "dynamic_agents": dynamic_agents,
            "nearest_person": nearest_person,
            "obstacle_distance_m": obstacle,
            "collision": collision,
            "emergency_stopped": arbitration["emergency_stopped"],
            "motion": arbitration,
            "control": self.control_manager.snapshot().as_dict(),
            "activities": self.activities.snapshot(),
            "events": events,
            "chat": chat,
        }

    def latency_snapshot(self) -> dict[str, object]:
        snapshot = self.latency.snapshot()
        snapshot["components"] = self.component_metrics.snapshot()
        snapshot["audio"] = self.audio_status.as_dict()
        asr_detail = (
            "capture endpoint connected, but continuous VAD/ASR endpointer timing is not wired"
            if self.audio_status.connected_input
            else "text input mode; no connected capture endpoint"
        )
        acoustic_detail = (
            "headset connected; exact presentation still requires PipeWire timing feedback"
            if self.audio_status.bluetooth_connected
            else "requires a connected headset and PipeWire presentation timestamps"
        )
        snapshot["unavailable"] = {
            "ASREndpointer": asr_detail,
            "BluetoothAcousticPresentation": acoustic_detail,
        }
        return snapshot

    @property
    def last_reasoning_source(self) -> str:
        return str(getattr(self.agent, "last_reasoning_source", "unknown"))

    def _control_loop(self) -> None:
        last_follow_state = ""
        while not self._stop_event.is_set():
            started = time.monotonic()
            observe_recorded = False
            try:
                observe_started = time.monotonic()
                observation = self.backend.observe()
                if self._control_state_source is not None:
                    self._control_state_source.update_observation(observation)
                self.component_metrics.elapsed("SimulatorObserve", observe_started)
                observe_recorded = True
                self.component_metrics.observe_ms(
                    "PerceptionAge",
                    max(0.0, (time.monotonic() - observation.timestamp) * 1000.0),
                )
                with self._lock:
                    self._observation = observation
                    self._sim_status = "connected"
                    self._sim_error = ""
                if observation.emergency_stopped and not self.arbiter.emergency_stopped:
                    with self._command_lock:
                        self._interrupt_brain("emergency", "simulator emergency stop adopted")
                        self.follow.stop()
                        with self._lock:
                            self._behavior_generation += 1
                            self._navigation_directive = None
                            self._navigation_detail = {
                                **self._navigation_detail,
                                "enabled": False,
                                "state": "idle",
                                "reason": "simulator_emergency_stop",
                            }
                        self.activities.clear("simulator_emergency_stop")
                        self._stop_spatial_locked("simulator_emergency_stop")
                        self._activity_complete_at = 0.0
                        self.agent.safety.engage_emergency_stop()
                        self.arbiter.engage_emergency_stop()
                        self.control_manager.emergency_stop()
                    self._emit("safety", "Simulator emergency stop adopted", "error")
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                if not observe_recorded:
                    self.component_metrics.elapsed("SimulatorObserve", observe_started)
                observation = None
                self._record_sim_error(error)

            owner_track_started = time.monotonic()
            self.follow.observe_owner(observation, now=time.monotonic())
            self.component_metrics.elapsed("OwnerTrackHeadingFilter", owner_track_started)
            with self._lock:
                follow_generation = self._behavior_generation
            if self.follow.enabled:
                follow_started = time.monotonic()
                decision = self.follow.step(observation, now=time.monotonic())
                self.component_metrics.elapsed("FollowController", follow_started)
                with self._lock:
                    still_following = (
                        follow_generation == self._behavior_generation
                        and self.follow.enabled
                        and not self._closed
                    )
                    if still_following:
                        self._follow_detail = {
                            **self.follow.snapshot(),
                            "state": decision.state,
                            "reason": decision.reason,
                            "distance_m": decision.distance_m,
                            "owner_id": decision.owner_id,
                            "mode": decision.mode,
                            "owner_heading_rad": decision.owner_heading_rad,
                            "target_x_m": decision.target_x_m,
                            "target_y_m": decision.target_y_m,
                            "stage_side": decision.stage_side,
                        }
                        try:
                            self.submit_motion(
                                "follow",
                                decision.command,
                                ttl=self.loop_period * 3.0,
                            )
                        except RuntimeError:
                            pass
                if still_following and decision.state != last_follow_state:
                    level = (
                        "warning"
                        if decision.state
                        in {"acquiring_heading", "blocked", "invalid", "lost", "stale"}
                        else "info"
                    )
                    self._emit("follow", f"{decision.state}: {decision.reason}", level)
                    last_follow_state = decision.state
                elif not still_following:
                    self.arbiter.cancel("follow")
                    last_follow_state = "idle"
            else:
                with self._lock:
                    self._follow_detail = self.follow.snapshot()
                last_follow_state = "idle"

            spatial_started = time.monotonic()
            self._step_spatial(observation)
            self.component_metrics.elapsed("SpatialController", spatial_started)

            navigation_started = time.monotonic()
            self._step_navigation(observation)
            self.component_metrics.elapsed("NavigationController", navigation_started)

            self._step_brain()

            activity_started = time.monotonic()
            self._step_activities()
            self.component_metrics.elapsed("ActivityCoordinator", activity_started)

            dispatch_started = time.monotonic()
            self._dispatch_active()
            self.component_metrics.elapsed("MotionDispatch", dispatch_started)
            elapsed = time.monotonic() - started
            self.component_metrics.observe_ms("ControlLoopWork", elapsed * 1000.0)
            self.component_metrics.observe_ms(
                "ControlLoopOverrun",
                max(0.0, elapsed - self.loop_period) * 1000.0,
            )
            self._stop_event.wait(max(0.0, self.loop_period - elapsed))

    def _service_health_loop(self) -> None:
        """Keep slow service/device probes off the 10 Hz motion loop."""

        while not self._stop_event.is_set():
            self._refresh_model_health()
            if self._monitor_audio:
                self.audio_status = detect_audio_devices()
            self._stop_event.wait(10.0)

    def _refresh_model_health(self) -> None:
        """Probe each configured inference lane without conflating their health."""

        if not self._model_role_status:
            return
        readiness = {url: http_service_health(url) for url in set(self._model_health_urls.values())}
        role_status = {
            role: ("ready" if readiness.get(url, False) else "offline")
            for role, url in self._model_health_urls.items()
        }
        for role in self._model_role_status:
            role_status.setdefault(role, "configured")
        self._model_role_status = role_status
        if any(status == "offline" for status in role_status.values()):
            self._model_status = "offline"
        elif all(status == "ready" for status in role_status.values()):
            self._model_status = "ready"
        else:
            self._model_status = "configured"

    def _dispatch_active(self) -> None:
        with self._command_lock:
            now = time.monotonic()
            active = self.arbiter.current(now)
            command = (
                self.velocity_smoother.step(active.command, now=now)
                if active is not None
                else VelocityCommand()
            )
            if (
                active is not None
                and math.hypot(active.command.vx, active.command.vy) <= 1e-9
                and abs(active.command.vyaw) > 1e-9
            ):
                # A rotate-in-place target is a discrete forward-preferred mode
                # transition. Brake translation immediately while retaining
                # angular smoothing, otherwise residual forward velocity makes
                # the robot arc/slide during the first alignment ticks.
                command = VelocityCommand(vyaw=command.vyaw)
            with self._lock:
                observation = self._observation
            if self._synchronous_control_dispatch:
                self._ensure_compatibility_control_started()
                if observation is not None and self._control_state_source is not None:
                    state = self._control_state_source.latest()
                    if state is None or state.received_at < observation.timestamp:
                        self._control_state_source.update_observation(observation)
            collision_started = time.monotonic()
            command, proximity_state = self._collision_safe(
                command,
                observation,
                source=active.source if active is not None else None,
            )
            self.component_metrics.elapsed("CollisionGate", collision_started)
            self.velocity_smoother.force(command, now=now)
            if proximity_state != self._proximity_state:
                if proximity_state == "stopped":
                    self._emit("safety", "Proximity stop: obstacle too close", "warning")
                elif proximity_state == "slowing":
                    self._emit("safety", "Slowing near an obstacle", "info")
                elif self._proximity_state != "clear":
                    self._emit("safety", "Obstacle clearance restored", "success")
                self._proximity_state = proximity_state
            should_refresh = now - self._last_send_at >= 0.2
            # The optional simulator socket may not exist at UI startup. Until
            # one observation proves that transport is present, retain intent
            # locally and perform no actuator I/O. Physical managers use their
            # own feedback thread and are never gated by simulator telemetry.
            controller_delivery_available = (
                not self._synchronous_control_dispatch or observation is not None
            )
            if (
                controller_delivery_available
                and active is not None
                and (command != self._last_sent or should_refresh)
            ):
                try:
                    send_started = time.monotonic()
                    self.control_manager.set_target(
                        command,
                        source=active.source,
                        ttl=self.control_manager.timing.command_timeout_s,
                        now=now,
                    )
                    self.component_metrics.elapsed("BackendCommandSend", send_started)
                    self._last_sent = command
                    self._last_send_at = now
                    self._was_moving = any(
                        abs(value) > 1e-6 for value in (command.vx, command.vy, command.vyaw)
                    )
                except (ControlNotReadyError, OSError, RuntimeError, ValueError) as error:
                    self._record_sim_error(error)
            elif controller_delivery_available and active is None and self._was_moving:
                try:
                    self.control_manager.stop("intent_expired")
                except (OSError, RuntimeError) as error:
                    self._record_sim_error(error)
                self._last_sent = VelocityCommand()
                self._was_moving = False
                self.velocity_smoother.reset(now=now)
            if self._synchronous_control_dispatch:
                # The simulator socket is optional at process startup. Do not
                # turn "no sample has ever arrived" into a latched controller
                # fault; once any sample exists, idle ticks continue so later
                # telemetry loss and physical motion are still supervised.
                state_available = (
                    self._control_state_source is not None
                    and self._control_state_source.latest() is not None
                )
                if observation is not None or state_available:
                    try:
                        self.control_manager.tick(now=now)
                    except (OSError, RuntimeError, TypeError, ValueError) as error:
                        self._record_sim_error(error)

    def _ensure_compatibility_control_started(self) -> None:
        """Lazily activate only the local backend adapter used by tests/sim."""

        if (
            self._synchronous_control_dispatch
            and self.control_manager.snapshot().lifecycle.value == "disarmed"
        ):
            self.control_manager.start(threaded=False)

    def _step_navigation(self, observation: SimObservation | None) -> None:
        with self._lock:
            directive = self._navigation_directive
            generation = self._behavior_generation
        if directive is None or self.follow.enabled:
            return
        if observation is None:
            with self._lock:
                if (
                    generation == self._behavior_generation
                    and directive == self._navigation_directive
                ):
                    self._navigation_detail = {
                        **self._navigation_detail,
                        "state": "waiting",
                        "reason": "no_observation",
                    }
                    self.arbiter.cancel("navigation")
            return
        if not self._observation_is_fresh(observation):
            with self._lock:
                if (
                    generation == self._behavior_generation
                    and directive == self._navigation_directive
                ):
                    self._navigation_detail = {
                        **self._navigation_detail,
                        "state": "waiting",
                        "reason": "stale_perception",
                    }
                    self.arbiter.cancel("navigation")
            return
        try:
            with self._navigation_lock:
                self.dog.set_nav_pose(
                    (observation.robot.x, observation.robot.y, observation.robot.z),
                    math.degrees(observation.robot.yaw),
                )
                mission, command = self.dog.navigate(
                    directive,
                    nearest_person_m=observation.nearest_person_m,
                    nearest_obstacle_m=observation.nearest_obstacle_m,
                    publish=False,
                    extras=self._navigation_extras(observation),
                )
        except (LookupError, RuntimeError, TypeError, ValueError) as error:
            with self._lock:
                still_current = (
                    generation == self._behavior_generation
                    and directive == self._navigation_directive
                )
            if still_current:
                self.stop_navigation()
                self._emit("navigation", f"Navigation failed: {error}", "error")
            return
        place = (
            mission.goal.label or mission.goal.poi_id
            if mission.goal is not None
            else str(mission.metadata.get("semantic_query", directive))
        )
        with self._lock:
            still_current = (
                generation == self._behavior_generation
                and directive == self._navigation_directive
                and not self.follow.enabled
                and not self._closed
                and not self.arbiter.emergency_stopped
            )
            if not still_current:
                return
            verifying = command.stop and mission.status == "verifying"
            if command.stop and not verifying:
                self._navigation_directive = None
                self._navigation_detail = {
                    "enabled": False,
                    "state": mission.status,
                    "directive": directive,
                    "goal": place,
                    "reason": command.note or "arrived",
                }
                self.arbiter.cancel("navigation")
            elif verifying:
                self._navigation_detail = {
                    "enabled": True,
                    "state": "verifying",
                    "directive": directive,
                    "goal": place,
                    "reason": command.note,
                }
                self.arbiter.cancel("navigation")
            else:
                state = (
                    "searching"
                    if mission.status == "searching"
                    else ("blocked" if "stop" in command.note else "navigating")
                )
                self._navigation_detail = {
                    "enabled": True,
                    "state": state,
                    "directive": directive,
                    "goal": place,
                    "reason": command.note,
                }
                try:
                    self.submit_motion(
                        "navigation",
                        VelocityCommand(vx=command.vx, vy=command.vy, vyaw=command.vyaw),
                        ttl=self.loop_period * 3.0,
                    )
                except RuntimeError:
                    pass
        if verifying:
            if command.note == "semantic_stop_requested":
                self._request_navigation_terminal_stop()
                self._emit(
                    "navigation",
                    f"Stopping at {place}; checking position and motion feedback",
                    "info",
                )
            return
        if command.stop:
            if mission.status == "arrived":
                self._emit("navigation", f"Arrived at {place}", "success")
            else:
                self._emit(
                    "navigation",
                    f"Navigation failed for {place}: {command.note or mission.status}",
                    "error",
                )
            return

    def _navigation_extras(self, observation: SimObservation) -> dict[str, object]:
        """Build the sensor-limited navigation view used by runtime and tests."""

        status = self.control_manager.snapshot()
        feedback_age_ms = status.feedback_age_ms
        measured_linear = math.hypot(status.measured.vx, status.measured.vy)
        return {
            "collision": observation.collision,
            "perception_fresh": self._observation_is_fresh(observation),
            "obstacle_bearing_rad": observation.nearest_obstacle_bearing_rad,
            "obstacle_id": observation.nearest_obstacle_id,
            "person_bearing_rad": observation.nearest_person_bearing_rad,
            "person_id": observation.nearest_person_id,
            "person_ttc_s": observation.nearest_person_ttc_s,
            "lidar_obstacles": lidar_payload_from_observation(observation),
            "semantic_candidates": semantic_candidates_from_observation(observation),
            "motion_feedback": {
                "fresh": feedback_age_ms is not None
                and feedback_age_ms <= self.control_manager.timing.state_timeout_s * 1000.0,
                "stop_confirmed": status.stop_confirmed,
                "linear_speed_mps": measured_linear,
                "yaw_speed_rad_s": abs(status.measured.vyaw),
                "settled_linear_speed_mps": (self.control_manager.timing.settled_linear_speed_mps),
                "settled_yaw_speed_rad_s": (self.control_manager.timing.settled_yaw_speed_rad_s),
            },
            "query_context": self.context_builder.build().navigation_data(),
        }

    def _observation_is_fresh(
        self,
        observation: SimObservation,
        *,
        now: float | None = None,
    ) -> bool:
        age = (time.monotonic() if now is None else now) - observation.timestamp
        return -0.05 <= age <= self.telemetry_stale_s

    def _request_navigation_terminal_stop(self) -> None:
        """Issue one explicit stop; controller feedback completes the mission."""

        with self._command_lock:
            self.arbiter.cancel("navigation")
            self.velocity_smoother.reset(now=time.monotonic())
            try:
                self.control_manager.stop("navigation_terminal_verification")
            except (OSError, RuntimeError) as error:
                self._record_sim_error(error)
            self._last_sent = VelocityCommand()
            self._was_moving = False

    def _step_spatial(self, observation: SimObservation | None) -> None:
        event: tuple[str, str] | None = None
        with self._command_lock:
            if not self.spatial.active:
                return
            if (
                observation is None
                or time.monotonic() - observation.timestamp > self.telemetry_stale_s
            ):
                self._stop_spatial_locked("perception_unavailable")
                event = ("Spatial behavior stopped: perception unavailable", "warning")
            else:
                decision = self.spatial.step(observation)
                if decision.done:
                    previous = self.spatial.snapshot()
                    self.spatial.stop()
                    self.arbiter.cancel("spatial")
                    with self._lock:
                        self._spatial_detail = {
                            **previous,
                            "enabled": False,
                            "state": decision.state,
                            "reason": decision.reason,
                            "progress": decision.progress,
                        }
                    level = "success" if decision.state == "completed" else "warning"
                    event = (decision.reason.replace("_", " "), level)
                else:
                    with self._lock:
                        self._spatial_detail = {
                            **self.spatial.snapshot(),
                            "state": decision.state,
                            "reason": decision.reason,
                            "progress": decision.progress,
                        }
                    try:
                        self.submit_motion(
                            "spatial",
                            decision.command,
                            ttl=self.loop_period * 3.0,
                        )
                    except RuntimeError:
                        pass
        if event is not None:
            self._emit("spatial", event[0], event[1])

    def _collision_safe(
        self,
        command: VelocityCommand,
        observation: SimObservation | None,
        *,
        source: str | None = None,
    ) -> tuple[VelocityCommand, str]:
        """Final reactive brake shared by voice, manual, follow, and navigation."""
        spatial_detail = self.spatial.snapshot() if source == "spatial" else {}
        spatial_intent = spatial_detail.get("intent")
        owner_orbit = (
            isinstance(spatial_intent, dict) and spatial_intent.get("behavior") == "orbit_owner"
        )
        return apply_reactive_safety(
            command,
            observation,
            policy=self.reactive_safety_policy,
            owner_orbit=owner_orbit,
            orbit_radius_m=float(spatial_detail.get("orbit_radius_m") or 0.0),
            now=time.monotonic(),
        )

    def _record_sim_error(self, error: BaseException) -> None:
        message = str(error)
        with self._lock:
            changed = self._sim_status != "disconnected" or self._sim_error != message
            self._observation = None
            self._sim_status = "disconnected"
            self._sim_error = message
        if changed:
            self._emit("simulator", message, "error")

    def _emit(self, source: str, text: str, level: str = "info") -> None:
        with self._lock:
            self._event_id += 1
            self._events.append(
                {
                    "id": self._event_id,
                    "role": source,
                    "text": text,
                    "level": level,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    def _chat_item(self, role: str, text: str) -> None:
        with self._lock:
            self._chat.append(
                {
                    "role": role,
                    "text": text,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    def _voice_partial_received(self, transcript: str) -> None:
        with self._lock:
            self._voice_detail = {
                **self._voice_detail,
                "status": "listening",
                "partial": transcript,
            }

    def _voice_turn_completed(self, turn: VoiceTurn) -> None:
        with self._lock:
            if turn.superseded and self._voice_detail.get("status") == "emergency_stop":
                return
            self._voice_detail = {
                "mode": "text",
                "status": "superseded" if turn.superseded else "completed",
                "partial": "",
                "last_turn_id": turn.turn_id,
                "last_transcript": turn.transcript,
                "last_reply": turn.reply,
                "superseded": turn.superseded,
            }

    def _voice_stage(self, stage: VoiceStage) -> None:
        if stage.name == "query_end":
            self.latency.start(
                stage.turn_id,
                stage.transcript,
                source="text",
                now=stage.timestamp,
            )
            self.latency.mark(
                stage.turn_id,
                "query_end",
                now=stage.timestamp,
                details={
                    "input_source": "text",
                    "audio_transport": self.audio_status.transport,
                    "bluetooth_duplex_ready": self.audio_status.bluetooth_duplex_ready,
                },
            )
            return
        details: dict[str, object] | None = None
        if stage.name == "reasoning_response":
            reasoning_source = self.last_reasoning_source
            provider = (
                self.agent.planner_model
                if reasoning_source in {"plan_model", "plan_fallback"}
                else self.agent.language_model
            )
            provider_metrics = getattr(provider, "last_metrics", None)
            provider_details = (
                dict(provider_metrics)
                if reasoning_source in {"model", "fallback", "plan_model", "plan_fallback"}
                and isinstance(provider_metrics, dict)
                else {}
            )
            brain_metrics = getattr(self.agent, "last_brain_metrics", None)
            brain_details = dict(brain_metrics) if isinstance(brain_metrics, dict) else {}
            details = {**provider_details, **brain_details} or None
            reasoning_error = getattr(self.agent, "last_reasoning_error", None)
            if reasoning_error:
                details = {**(details or {}), "reasoning_error": str(reasoning_error)[:500]}
            reasoning_guard = getattr(self.agent, "last_reasoning_guard", None)
            if reasoning_guard:
                details = {**(details or {}), "reasoning_guard": str(reasoning_guard)[:500]}
            first_output = details.pop("_first_output_monotonic", None) if details else None
            if isinstance(first_output, (int, float)) and math.isfinite(float(first_output)):
                self.latency.mark(
                    stage.turn_id,
                    "reasoning_first_output",
                    now=float(first_output),
                )
            planning_timestamps = {
                "intent_routed": "_intent_routed_monotonic",
                "observation_snapshot": "_observation_snapshot_monotonic",
                "plan_response": "_plan_response_monotonic",
                "plan_validated": "_plan_validated_monotonic",
                "plan_accepted": "_plan_accepted_monotonic",
            }
            for planning_stage, metric_key in planning_timestamps.items():
                value = details.pop(metric_key, None) if details else None
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    self.latency.mark(
                        stage.turn_id,
                        planning_stage,
                        now=float(value),
                    )
            if (
                provider_details.get("model_mode") == "plan"
                and isinstance(first_output, (int, float))
                and math.isfinite(float(first_output))
            ):
                self.latency.mark(
                    stage.turn_id,
                    "plan_first_output",
                    now=float(first_output),
                )
            for metric_key, component in (
                ("intent_router_ms", "IntentRouter"),
                ("observation_snapshot_ms", "ObservationSnapshotBuild"),
            ):
                value = brain_details.get(metric_key)
                if isinstance(value, (int, float)):
                    self.component_metrics.observe_ms(component, float(value))
            if provider_details.get("model_mode") == "plan":
                model_ms = provider_details.get("model_http_ms")
                if isinstance(model_ms, (int, float)):
                    self.component_metrics.observe_ms("PlanModel", float(model_ms))
            self.latency.set_result(
                stage.turn_id,
                stage.reply,
                reasoning_source=self.last_reasoning_source,
                details=details,
            )
        self.latency.mark(
            stage.turn_id,
            stage.name,
            now=stage.timestamp,
            details=details,
        )
        if stage.name == "turn_complete":
            self.latency.finalize(stage.turn_id, now=stage.timestamp)

    def _voice_error(self, error: Exception) -> None:
        with self._lock:
            self._voice_detail = {
                **self._voice_detail,
                "status": "error",
                "partial": "",
                "error": str(error),
            }
        self._emit("voice", str(error), "error")


def http_service_health(url: str, timeout: float = 0.5) -> bool:
    """Small reusable health probe for locally isolated model services."""
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        return False
