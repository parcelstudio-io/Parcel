from __future__ import annotations

import logging
import math
import random
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
    FrozenDict,
    GoalSpec,
    GoalTarget,
    IntentFrame,
    InterruptRequest,
    ObservationSnapshot,
    PlanIR,
    PlanSketch,
    PlanStep,
    PlanValidationError,
    PlanValidator,
    SemanticRuntimeState,
    SemanticTaskRuntimeAdapter,
    SkillContractRegistry,
    SuccessCondition,
    TaskExecutive,
    admitted_plan_schema,
    admitted_plan_sketch_schema,
    compile_plan_contracts,
    materialize_planner_output,
)
from parcel_robot.brain.contracts import BatteryStateSnapshot
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
    MotionShapingConfig,
    VelocitySmoother,
)
from parcel_robot.core.channels import BehaviorChannelRegistry
from parcel_robot.core.details import (
    FollowDetail,
    NavigationDetail,
    SpatialDetail,
    VoiceDetail,
)
from parcel_robot.core.preemption import PreemptionTable
from parcel_robot.core.resume import GenerationTokens, ResumeIntent, ResumeStore
from parcel_robot.duplex import DuplexConfig, DuplexCoordinator
from parcel_robot.dynamic_prompting import (
    CallableContextSource,
    EmotePolicySource,
    RecentToolResultsSource,
    build_prompting_stack,
)
from parcel_robot.endpointing import SileroVad, TurnEndpointer
from parcel_robot.expression import (
    BeatLayer,
    ExpressionEngine,
    ExpressionGate,
    IdleLayer,
    ReactionHooks,
)
from parcel_robot.memory import ConversationMemory
from parcel_robot.models import ActionProposal, Pose, SpatialIntent, VelocityCommand
from parcel_robot.motion import build_motion_router
from parcel_robot.navigation.dynamic_layer import (
    TimeToCollisionConfig,
    time_to_collision_verdict,
    tracks_from_payload,
)
from parcel_robot.navigation.follow import (
    FollowConfig,
    FollowOwnerController,
    FollowPredictionConfig,
)
from parcel_robot.navigation.owner_prediction import OwnerMotionPredictor, PredictedPath
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)
from parcel_robot.navigation.search_owner import (
    SearchOwnerConfig,
    SearchOwnerController,
)
from parcel_robot.navigation.semantic_map import (
    lidar_payload_from_observation,
    semantic_candidates_from_observation,
)
from parcel_robot.navigation.spatial import SpatialBehaviorConfig, SpatialBehaviorController
from parcel_robot.navigation.velocity_shaping import SCurveVelocityShaper
from parcel_robot.observability import ComponentMetrics, LatencyTracker
from parcel_robot.perception import NullMapProvider, PerceptionContract
from parcel_robot.prompting import PromptLibrary
from parcel_robot.prosody import analyze_wav_chunk
from parcel_robot.providers import (
    LanguageModel,
    SentenceChunkedSynthesizer,
    build_speech_stack,
    strip_emote_tags,
)
from parcel_robot.robot_profile import RobotProfile
from parcel_robot.runtime_channels import (
    ActivitiesChannel,
    FollowChannel,
    LazyNavigator,
    NavigationChannel,
    SearchChannel,
    SpatialChannel,
)
from parcel_robot.skills.api import Dog
from parcel_robot.voice_audio import (
    MicrophoneVoiceLoop,
    SpeakerSink,
    resolve_audio_device,
)
from parcel_robot.voice_pipeline import DuplexVoiceSession, VoiceStage, VoiceTurn

logger = logging.getLogger(__name__)


def _dynamic_agent_payload(
    observation: SimObservation,
) -> tuple[dict[str, float], ...]:
    """Serialize non-owner dynamic tracks for the planner and the TTC gate."""

    return tuple(
        {
            "x": float(track.x),
            "y": float(track.y),
            "vx": float(track.vx),
            "vy": float(track.vy),
            "radius_m": float(track.radius_m),
        }
        for track in observation.dynamic_agents
    )


def _is_zero_command(command: VelocityCommand) -> bool:
    return all(abs(value) <= 1e-9 for value in (command.vx, command.vy, command.vyaw))


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
        # The robot: config section is live morphology, not a label: gait,
        # animation retargeting, and future consumers read this profile.
        self.robot_profile = RobotProfile.from_config(self.store.section("robot"))
        self.expression = self._build_expression_engine()
        self.expression_hz = float(
            (self.store.section("expression") or {}).get("rate_hz", 50.0)
        )
        if not 5.0 <= self.expression_hz <= 200.0:
            raise ValueError("expression.rate_hz must be between 5 and 200")
        self._expression_sent: dict[str, float] | None = None
        self._expression_publish_failing = False
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
        # Card W6. Jerk limiting for the actuator hand-off only. It sits after
        # the arbiter and the collision gate, so safety always sees the intent
        # and the smoothing can never delay a stop; every stop routes through
        # the shaper's emergency bypass instead.
        raw_shaping = self.store.motion_config().get("shaping", {})
        if not isinstance(raw_shaping, dict):
            raise TypeError("motion.shaping must be a mapping")
        self.motion_shaping = MotionShapingConfig.from_mapping(raw_shaping)
        self._nominal_shaper_limits = self.motion_shaping.limits()
        self._motion_shaper = SCurveVelocityShaper(*self._nominal_shaper_limits)
        self._shaper_profile = "nominal"
        self._last_shaped: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._shaped_at: float | None = None
        self._seen_watchdog_stops = 0
        self._vocal_arousal: float | None = None
        self._vocal_arousal_at: float | None = None
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
        # Card W4. Supplements the geometric gate; validated strictly so a
        # mistyped brake threshold cannot silently disable the gate.
        raw_ttc = safety_config.get("time_to_collision", {})
        if not isinstance(raw_ttc, dict):
            raise TypeError("safety.time_to_collision must be a mapping")
        self.time_to_collision = TimeToCollisionConfig.from_mapping(raw_ttc)
        self._min_time_to_collision_s = math.inf
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
        # Anticipatory following (card W2). The nested block is validated
        # separately so a typo inside it cannot ride through as an unknown
        # top-level follow key.
        raw_prediction = follow_config.pop("prediction", {})
        if not isinstance(raw_prediction, dict):
            raise TypeError("owner_follow.prediction must be a mapping")
        follow_prediction = FollowPredictionConfig.from_mapping(raw_prediction)
        self.follow = FollowOwnerController(
            FollowConfig.from_mapping(follow_config),
            safety_policy=self.reactive_safety_policy,
            prediction=follow_prediction,
        )
        # One predictor, owned here and fed from the same owner track the
        # follow controller consumes, so the prediction and the measurement can
        # never disagree about which observation they came from.
        self.owner_predictor = OwnerMotionPredictor()
        self._owner_predictor_id: str | None = None
        self._owner_prediction: PredictedPath | None = None
        # Owner reacquisition (card W7). The controller only proposes motion;
        # the shared reactive policy and the final collision gate still decide
        # what any of its three states is allowed to execute.
        self.search = SearchOwnerController(
            SearchOwnerConfig.from_mapping(self.store.section("owner_search")),
            safety_policy=self.reactive_safety_policy,
        )
        self._search_detail: dict[str, object] = self.search.snapshot()
        self._last_confident_owner: tuple[float, float, float] | None = None
        self._owner_lost_since: float | None = None
        self._resume_follow_after_search: tuple[str, float | None] | None = None
        self._owner_search_sequence = 0
        self._last_search_state = ""
        self._last_search_degradation = ""
        self._spatial_detail: dict[str, object] = self.spatial.snapshot()
        self._monitor_audio = audio_status is None
        self.audio_status = audio_status or detect_audio_devices()
        self._observation: SimObservation | None = None
        self._follow_detail: dict[str, object] = self.follow.snapshot()
        self._navigation_directive: str | None = None
        self._navigation_detail: dict[str, object] = NavigationDetail().as_dict()
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
        self._generation = GenerationTokens()
        self._resume_store = ResumeStore()
        self._preemption_table = PreemptionTable.default()
        self._channels = BehaviorChannelRegistry(
            table=self._preemption_table,
            resume_store=self._resume_store,
        )
        self._behavior_generation = 0  # legacy aggregate; prefer _generation
        self._closed = False
        self._close_complete = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._health_thread: threading.Thread | None = None
        self._expression_thread: threading.Thread | None = None
        self._last_sent = VelocityCommand()
        self._last_send_at = 0.0
        self._was_moving = False
        self._proximity_state = "clear"
        self._control_not_ready_reason: str | None = None
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
        self._voice_detail: dict[str, object] = VoiceDetail().as_dict()

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
        planner_skills = SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS
        configured_brain_skills = brain_config.get("skills", sorted(planner_skills))
        if not isinstance(configured_brain_skills, list) or not all(
            isinstance(item, str) for item in configured_brain_skills
        ):
            raise TypeError("agent.brain.skills must be a list of semantic skill names")
        system_only = set(configured_brain_skills) & SemanticTaskRuntimeAdapter.SYSTEM_SKILLS
        if system_only:
            raise ValueError(
                "agent.brain.skills cannot admit system-triggered recovery skills: "
                f"{sorted(system_only)}"
            )
        unsupported_brain_skills = set(configured_brain_skills) - planner_skills
        if unsupported_brain_skills:
            raise ValueError(
                "agent.brain contains skills without runtime adapters: "
                f"{sorted(unsupported_brain_skills)}"
            )
        # The validator and ReturnToSafePose dispatch must share one pose
        # vocabulary: an empty catalog here rejects every safe-pose plan.
        self._brain_pose_catalog = dict(self.dog.poses() or self.store.poses())
        self._emote_catalog = self._resolve_emote_catalog(brain_config)
        admitted_registry = SkillContractRegistry.default(
            owner_heading_supported=True,
            pose_names=tuple(sorted(self._brain_pose_catalog)),
            gesture_names=self._emote_catalog,
            include_system_skills=True,
        )
        self.brain_registry = admitted_registry.restricted(configured_brain_skills)
        # System recovery plans are authored by the runtime, never by a model,
        # so they validate against a registry the planner never sees.
        self.system_registry = admitted_registry.restricted(
            set(configured_brain_skills) | SemanticTaskRuntimeAdapter.SYSTEM_SKILLS
        )
        maximum_total_timeout_s = float(brain_config.get("maximum_total_timeout_s", 600.0))
        self.plan_validator = PlanValidator(
            self.brain_registry,
            maximum_total_timeout_s=maximum_total_timeout_s,
        )
        self.system_plan_validator = PlanValidator(
            self.system_registry,
            maximum_total_timeout_s=maximum_total_timeout_s,
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
            return_to_safe_pose=self._brain_return_to_safe_pose,
            gesture=self._brain_gesture,
            search_owner=self._start_brain_owner_search,
        )
        self._brain_snapshot_sequence = 0
        self._last_brain_plan: dict[str, object] | None = None
        # Battery telemetry (simulated until a hardware source exists) keeps
        # battery_critical procedures reachable instead of permanently dead.
        battery_config = self.store.section("battery")
        self._battery_percent = float(battery_config.get("simulated_percent", 90.0))
        self._battery_low_threshold = float(battery_config.get("low_threshold_percent", 20.0))
        self._battery_critical_threshold = float(
            battery_config.get("critical_threshold_percent", 8.0)
        )
        if not 0.0 <= self._battery_critical_threshold <= self._battery_low_threshold <= 100.0:
            raise ValueError("battery thresholds must satisfy 0 <= critical <= low <= 100")
        # Last posture applied through the pose path; verifies ReturnToSafePose.
        self._last_posture = "unknown"
        # System-compiled invariants of the currently active plan; enforced by
        # the control loop, not merely reported.
        self._active_invariants: tuple[str, ...] = ()
        self._active_invariants_owner: str | None = None
        self._stale_perception_invariant_engaged = False
        memory_cfg = self.store.section("memory")
        # Dynamic prompting: sectioned context assembly (owner profile,
        # information-tool policy, volatile turn context) + the read-only
        # tool registry the conversation model may call. Inspect and iterate
        # at /api/prompt.
        self.prompting = build_prompting_stack(self.store.section("prompting"))
        if self.prompting.composer is not None:
            self.prompting.composer.register(
                CallableContextSource(
                    source_id="current_situation",
                    provider=self._prompt_current_situation,
                    placement="turn",
                    priority=10,
                    budget_chars=400,
                )
            )
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
            info_tools=self.prompting.tools if self.prompting.tools.names() else None,
            slow_path_hook=self._duplex_slow_path,
        )
        self.duplex_config = DuplexConfig.from_mapping(self.store.section("duplex") or None)
        self.duplex = DuplexCoordinator(
            self.duplex_config,
            skills=tuple(self.brain_registry.names()) if self._brain_enabled else (),
            emotes=tuple(self._emote_catalog),
        )
        self._duplex_latest_turn_id = 0
        # Per-turn duplex outcome bookkeeping for the D1 session log.
        self._duplex_turn_meta: dict[int, dict[str, object]] = {}
        if self.prompting.composer is not None:
            # Fresh tool output stays visible to the next turn without
            # permanently bloating conversation history.
            self.prompting.composer.register(
                RecentToolResultsSource(lambda: self.agent.memory.recent(16))
            )
            if self._emote_catalog:
                self.prompting.composer.register(EmotePolicySource(self._emote_catalog))
        # Feed the duplex coordinator through ``handle_text`` so streamed ASR
        # finals and ordinary HTTP commands share logging, serialization, and
        # the same deterministic safety boundary. Speech services are resolved
        # from config and fail soft: an unavailable STT/TTS service leaves the
        # session in the historical text-only mode with an explicit status.
        speech_config = self.store.section("speech")
        self.speech_stack = build_speech_stack(speech_config)
        # Physical device selection. An unresolvable *requested* device is a
        # configuration error the operator must see, so it degrades the audio
        # path loudly instead of silently opening the wrong hardware.
        input_index, self._input_device_detail = self._resolve_speech_device(
            speech_config.get("input_device"), kind="input"
        )
        output_index, self._output_device_detail = self._resolve_speech_device(
            speech_config.get("output_device"), kind="output"
        )
        self._speaker_sink: SpeakerSink | None = None
        self._microphone_loop: MicrophoneVoiceLoop | None = None
        synthesizer = None
        audio_chunk_player = None
        audio_interrupt = None
        audio_turn_start = None
        if self.speech_stack.synthesizer is not None:
            self._speaker_sink = SpeakerSink(
                device=output_index, on_chunk_start=self._audio_chunk_started
            )
            synthesizer = SentenceChunkedSynthesizer(self.speech_stack.synthesizer)
            # Analyze each chunk before it is queued, then let the sink tell
            # us when it actually starts playing: prosody is known ahead of
            # playback, which is the lookahead a live-reactive system cannot
            # have.
            audio_chunk_player = self._enqueue_speech_chunk
            audio_interrupt = self._interrupt_speech_audio
            audio_turn_start = self._speaker_sink.begin_utterance
        self.voice_session = DuplexVoiceSession(
            self,
            synthesizer=synthesizer,
            audio_chunk_player=audio_chunk_player,
            audio_interrupt=audio_interrupt,
            audio_turn_start=audio_turn_start,
            on_turn=self._voice_turn_completed,
            on_partial=self._voice_partial_received,
            on_error=self._voice_error,
            on_stage=self._voice_stage,
            on_filler_audible=self._duplex_filler_audible,
        )
        neural_vad, endpointer, self._endpointing_detail = self._build_endpointing(
            speech_config
        )
        if self.speech_stack.recognizer is not None:
            self._microphone_loop = MicrophoneVoiceLoop(
                recognizer=self.speech_stack.recognizer,
                # The guarded entry point, not the raw session: spoken
                # emergency phrases must latch the E-stop synchronously
                # instead of queueing behind a committed slow action.
                submit_text=self.submit_voice_text,
                barge_in=self.voice_session.barge_in,
                playback_active=(
                    (lambda: self._speaker_sink.playback_active)
                    if self._speaker_sink is not None
                    else (lambda: False)
                ),
                echo_guard_scale=float(speech_config.get("echo_guard_scale", 2.5)),
                on_failure=self._microphone_failed,
                on_speech_start=self._owner_speech_started,
                on_speech_end=self._owner_speech_ended,
                device=input_index,
                neural_vad=neural_vad,
                endpointer=endpointer,
                on_turn_commit=self._record_turn_commit,
            )
        self._voice_query_end_by_turn: dict[int, float] = {}
        self._emit(
            "voice",
            f"Speech: stt={self.speech_stack.stt_detail}; tts={self.speech_stack.tts_detail}",
            "info",
        )
        self._register_behavior_channels()
        self._emit("runtime", "Runtime initialized", "success")

    def _register_behavior_channels(self) -> None:
        """Wire Sol's preemption table to concrete channel adapters.

        Navigation uses a lazy navigator accessor so configs with navigation
        disabled never construct ``DirectiveNavigator`` at init.
        """

        self._channels.register(
            FollowChannel(
                self.follow,
                on_stop=lambda _name: self.arbiter.cancel("follow"),
                on_snapshot=lambda: dict(self._follow_detail),
            ),
            pausable=True,
        )
        self._channels.register(
            NavigationChannel(
                LazyNavigator(self),
                is_enabled=lambda: self._navigation_directive is not None,
                stop_fn=self._stop_navigation_channel,
                detail_fn=lambda: dict(self._navigation_detail),
            ),
            pausable=True,
        )
        self._channels.register(
            SpatialChannel(
                self.spatial,
                stop_fn=self._stop_spatial_locked,
                detail_fn=lambda: dict(self._spatial_detail),
            ),
            pausable=False,
        )
        self._channels.register(
            SearchChannel(
                self.search,
                stop_fn=self._stop_search_channel,
                detail_fn=lambda: dict(self._search_detail),
                clock=time.monotonic,
            ),
            pausable=True,
        )
        self._channels.register(ActivitiesChannel(self.activities), pausable=False)

    def _stop_navigation_channel(self) -> None:
        """Channel-level navigation stop (no re-entrant preempt)."""

        with self._lock:
            self._generation.bump("navigation")
            self._behavior_generation += 1
            was_enabled = self._navigation_directive is not None
            self._navigation_directive = None
            if was_enabled:
                self._navigation_detail = NavigationDetail.from_dict(
                    {
                        **self._navigation_detail,
                        "enabled": False,
                        "state": "idle",
                        "reason": "navigation_disabled",
                    }
                ).as_dict()
        self.arbiter.cancel("navigation")
        if was_enabled:
            with self._navigation_lock:
                self.dog.stop()

    def _stop_search_channel(self) -> None:
        self.search.stop()
        self.arbiter.cancel("search")
        self._resume_follow_after_search = None
        with self._lock:
            self._generation.bump("search")
            self._behavior_generation += 1
            self._search_detail = {**self.search.snapshot(), "reason": "search_stopped"}

    def preempt(self, claimant: str, *, reason: str, targets: tuple[str, ...] | None = None) -> dict[str, str]:
        """Apply ``PreemptionTable.default()`` to active (or listed) channels."""

        now_s = time.monotonic()
        # Fill suspended_at_s on any pause intents the registry records.
        taken = self._channels.preempt(
            claimant, reason=reason, now_s=now_s, targets=targets
        )
        for channel_name, action in taken.items():
            if action in {"stop", "pause"}:
                with self._lock:
                    self._generation.bump(channel_name)
                    self._behavior_generation += 1
            if action == "pause":
                intent = self._resume_store.peek(channel_name, now_s=now_s)
                if intent is not None and intent.suspended_at_s == 0.0:
                    self._resume_store.record(
                        ResumeIntent(
                            channel=intent.channel,
                            payload=intent.payload,
                            suspend_reason=intent.suspend_reason,
                            suspended_at_s=now_s,
                            valid_for_s=intent.valid_for_s,
                            requires_fresh_observation=intent.requires_fresh_observation,
                        )
                    )
            if channel_name == "follow" and action in {"stop", "pause"}:
                with self._lock:
                    self._follow_detail = FollowDetail.from_dict(self.follow.snapshot()).as_dict()
            if channel_name == "search" and action == "stop":
                with self._lock:
                    self._search_detail = dict(self.search.snapshot())
            if channel_name == "navigation" and action in {"stop", "pause"}:
                with self._lock:
                    detail = dict(self._navigation_detail)
                    if action == "pause":
                        detail["state"] = "paused"
                        detail["enabled"] = True
                        detail["reason"] = reason
                    self._navigation_detail = NavigationDetail.from_dict(detail).as_dict()
            if channel_name == "activities" and action == "stop":
                self._activity_complete_at = 0.0
        return taken

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
            battery=self._battery_snapshot(),
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
            # Invariants become live enforcement state, not just a report line.
            self._active_invariants = validated.effective_invariants
            self._active_invariants_owner = plan.task_id
            self._stale_perception_invariant_engaged = False
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

    DEFAULT_EMOTES = (
        "bow",
        "hello_pose",
        "hop",
        "look_left",
        "look_right",
        "paw_wave",
        "play_bow",
        "shake",
        "stretch",
    )

    def _resolve_emote_catalog(self, brain_config: dict) -> tuple[str, ...]:
        """The curated allowlist of catalog skills admissible as emotes.

        Deliberately narrower than the full catalog: postural skills belong to
        ReturnToSafePose, and gaits/velocity skills are locomotion, not
        expression. Every entry must exist in the skill catalog and be a
        bounded pose/trajectory, so an unknown or unbounded name fails at
        startup instead of at dispatch.
        """

        configured = brain_config.get("emotes", self.DEFAULT_EMOTES)
        if not isinstance(configured, (list, tuple)) or not all(
            isinstance(item, str) for item in configured
        ):
            raise TypeError("agent.brain.emotes must be a list of skill names")
        catalog = self.dog.catalog
        admitted: list[str] = []
        for name in configured:
            try:
                skill = catalog.get(name)
            except KeyError:
                # A default entry simply may not exist in a trimmed catalog;
                # an explicitly configured one is an operator error.
                if "emotes" in brain_config:
                    raise ValueError(f"unknown emote skill: {name}") from None
                continue
            if skill.kind not in {"pose", "trajectory"}:
                raise ValueError(
                    f"emote {name!r} is a {skill.kind} skill; emotes must be bounded "
                    "pose or trajectory skills"
                )
            admitted.append(name)
        return tuple(sorted(admitted))

    def _brain_gesture(self, name: str, intensity: float = 1.0) -> str:
        """Expressive gesture dispatch: proposal → cooldown arbiter → skill.

        Routed through the same activity coordinator as social gestures so an
        emote can never preempt navigation, stack on another activity, or
        bypass the proposal cooldowns.
        """

        clean = name.strip()
        if clean not in self._emote_catalog:
            raise ValueError(f"unknown emote: {name!r}")
        if not math.isfinite(intensity) or not 0.5 <= intensity <= 1.5:
            raise ValueError("emote intensity must be between 0.5 and 1.5")
        detail = self.propose_action(
            ActionProposal(
                kind="skill",
                name=clean,
                trigger="explicit_command",
                timing_preference="now",
                interruption_request="safe_checkpoint",
                reason=f"conversation emote (intensity {intensity:.2f})",
            )
        )
        if detail.startswith("Rejected"):
            # Surface the rejection to the caller (executive dispatch_failed /
            # emote-tag warning) instead of leaving a step waiting for an
            # activity that will never run (sprint review finding).
            raise RuntimeError(detail)
        return detail

    def _enqueue_speech_chunk(self, chunk: bytes) -> None:
        """Analyze one synthesized chunk for beats, then queue it for playback."""

        track = None
        if self.expression.enabled:
            analyze_started = time.monotonic()
            try:
                track = analyze_wav_chunk(chunk)
            except (TypeError, ValueError) as error:
                # Prosody is decorative: a chunk we cannot analyze still gets
                # spoken, it just carries no nods.
                logger.warning("prosody analysis skipped: %s", error)
                track = None
            else:
                self.component_metrics.elapsed("ProsodyAnalysis", analyze_started)
        # Emotes authored in this sentence ride the same token as its beats so
        # both fire against the playback clock rather than the synthesis clock.
        emotes = tuple(getattr(chunk, "emotes", ()))
        token = (
            (track, self.expression.speech_epoch, emotes)
            if track is not None or emotes
            else None
        )
        assert self._speaker_sink is not None
        self._speaker_sink.enqueue(chunk, token)

    def _audio_chunk_started(self, token: object) -> None:
        """Playback of a chunk began: arm its nods and fire its emotes now."""

        if token is None:
            return
        track, epoch, emotes = token
        if epoch != self.expression.speech_epoch:
            return  # the audio this belonged to was superseded
        if track is not None:
            self.expression.beats.arm(
                track, playback_start_s=time.monotonic(), epoch=epoch
            )
            # Card W6. Vocal arousal is the only affect signal measured from
            # the robot's own behaviour rather than inferred from text, so it
            # is what the motion profile follows.
            self._note_vocal_arousal(float(getattr(track, "arousal", 0.0)))
        # Nods are armed first: a gesture the arbiter rejects must not cost the
        # sentence its beats.
        for name, intensity in emotes:
            self._speech_emote(name, intensity)

    def _interrupt_speech_audio(self) -> None:
        """Barge-in: cancel queued audio and every nod scheduled for it."""

        self.expression.supersede_speech()
        assert self._speaker_sink is not None
        self._speaker_sink.interrupt()

    def _speech_emote(self, name: str, intensity: float) -> None:
        """An inline ``[emote:...]`` tag reached the moment it belongs to.

        Unknown or currently-inadmissible emotes are reported and dropped:
        speech must never fail because a gesture could not run.
        """

        try:
            detail = self._brain_gesture(name, intensity)
        except (LookupError, RuntimeError, TypeError, ValueError) as error:
            self._emit("activity", f"Emote tag {name!r} ignored: {error}", "warning")
            return
        if self.duplex.enabled:
            self.duplex.push_emote(name)
        self._emit("activity", f"Emote {name}: {detail}", "info")

    def _brain_return_to_safe_pose(self, pose_name: str) -> str:
        """Battery-critical procedure: stop all motion, then assume the pose.

        On a physical controller without direct pose actuation the pose step
        raises and the executive's recovery policy takes over — the robot is
        still left stopped, which is the safe half of the contract.
        """

        clean = pose_name.strip().lower()
        poses = self._brain_pose_catalog
        # Stop first: a pose-vocabulary miss must still leave the robot
        # stationary (the safe half of the contract).
        self.stop_motion()
        if clean not in poses:
            raise ValueError(f"unknown safe pose: {pose_name!r}")
        self._run_pose(poses[clean])
        return f"safe pose {clean} requested"

    def _battery_snapshot(self) -> BatteryStateSnapshot:
        percent = self._battery_percent
        if percent <= self._battery_critical_threshold:
            state = "critical"
        elif percent <= self._battery_low_threshold:
            state = "low"
        else:
            state = "normal"
        return BatteryStateSnapshot(state=state, percent=percent, source="simulated")

    def set_battery_percent(self, percent: float) -> None:
        """Adjust the simulated battery level (testing / panel drain control)."""

        value = float(percent)
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise ValueError("battery percent must be between 0 and 100")
        with self._lock:
            self._battery_percent = value

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
            search = dict(self._search_detail)
            observation = self._observation
        control = self.control_manager.snapshot()
        owner_track_confidence = 0.0
        if (
            observation is not None
            and observation.owner.visible
            and self._observation_is_fresh(observation)
            and math.isfinite(observation.owner.confidence)
        ):
            owner_track_confidence = max(0.0, min(1.0, observation.owner.confidence))
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
            search_enabled=self.search.enabled,
            search_state=str(search.get("state", self.search.state)),
            search_reason=str(search.get("reason", "")),
            owner_track_confidence=owner_track_confidence,
            stop_confirmed=control.stop_confirmed,
            control_feedback_fresh=(
                control.feedback_age_ms is not None
                and control.feedback_age_ms <= self.control_manager.timing.state_timeout_s * 1000.0
            ),
            robot_moving=snapshot.robot.moving,
            posture=self._last_posture,
            **self._activity_verification_state(),
        )

    def _activity_verification_state(self) -> dict[str, str]:
        """Coordinator view a Gesture dispatch is verified against.

        A running activity reports its live status; otherwise the most recent
        terminal record is used, which is what lets a short gesture that both
        started and finished between two polls still be verified.
        """

        snapshot = self.activities.snapshot()
        running = snapshot.get("running")
        record = running if isinstance(running, dict) else None
        if record is None:
            recent = snapshot.get("recent")
            if isinstance(recent, list) and recent:
                candidate = recent[-1]
                record = candidate if isinstance(candidate, dict) else None
        if record is None:
            return {
                "activity_name": "",
                "activity_status": "idle",
                "activity_detail": "",
                "activity_created_at": 0.0,
            }
        try:
            created_at = float(record.get("created_at", 0.0))
        except (TypeError, ValueError):
            created_at = 0.0
        return {
            "activity_name": str(record.get("name", "")),
            "activity_status": str(record.get("status", "idle")),
            "activity_detail": str(record.get("detail", "") or ""),
            "activity_created_at": created_at,
        }

    def _enforce_perception_invariant(self, observation: SimObservation | None) -> None:
        """Enforce the compiled ``stop_on_stale_perception`` plan invariant.

        Plans that admitted perception-dependent steps compiled this invariant;
        it previously informed nothing. Now stale or missing perception while
        such a plan runs stops every active semantic dispatch immediately.
        """

        with self._lock:
            invariants = self._active_invariants
            engaged = self._stale_perception_invariant_engaged
        if "stop_on_stale_perception" not in invariants:
            return
        perception_ok = observation is not None and self._observation_is_fresh(observation)
        if perception_ok:
            if engaged:
                with self._lock:
                    self._stale_perception_invariant_engaged = False
                self._emit("brain", "Perception restored; invariant stop released", "info")
            return
        active = self.semantic_tasks.active()
        if not active:
            return
        self._stop_semantic_dispatches(active, "stop_on_stale_perception")
        with self._command_lock:
            self.arbiter.stop()
            self.control_manager.stop("stop_on_stale_perception")
            self._reset_motion_shaper()
        if not engaged:
            with self._lock:
                self._stale_perception_invariant_engaged = True
            self._emit(
                "safety",
                "stop_on_stale_perception invariant engaged: perception stale during plan",
                "warning",
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
        # Once the owning task is terminal, its compiled invariants stop
        # binding. The executive is re-read under self._lock: _accept_plan
        # submits the task before assigning _active_invariants under the same
        # lock, so a stale pre-submit snapshot can never wipe a newly
        # accepted plan's invariants (TOCTOU found in review).
        with self._lock:
            if self._active_invariants:
                owner = self._active_invariants_owner
                owner_active = any(
                    isinstance(row, dict)
                    and row.get("task_id") == owner
                    and row.get("state") not in {"succeeded", "failed", "cancelled"}
                    for row in self.task_executive.snapshot().get("tasks", [])
                )
                if not owner_active:
                    self._active_invariants = ()
                    self._active_invariants_owner = None
                    self._stale_perception_invariant_engaged = False
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
            if self.duplex.enabled:
                self.duplex.push_skill(request.skill)
            if immediate is not None:
                self.task_executive.report(immediate)
        self.component_metrics.elapsed("ExecutiveTick", started)

    def _reconcile_semantic_tasks(self) -> None:
        executive = self.task_executive.snapshot()
        suspended_ids: set[str] = set()
        valid = []
        for row in executive.get("tasks", []):
            if not isinstance(row, dict):
                continue
            state = row.get("state")
            task_id = row.get("task_id")
            if state == "suspended" and isinstance(task_id, str):
                suspended_ids.add(task_id)
                continue
            if state not in {"running", "waiting_checkpoint"}:
                continue
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
        if not removed:
            return
        to_pause = tuple(
            item for item in removed if item.request.task_id in suspended_ids
        )
        to_stop = tuple(
            item for item in removed if item.request.task_id not in suspended_ids
        )
        # Suspend ≠ STOP: pause channels + ResumeIntent; only non-suspended
        # removals take the destructive preempt path.
        if to_pause:
            self._pause_semantic_dispatches(to_pause, "task_suspended")
        if to_stop:
            self._stop_semantic_dispatches(to_stop, "task_no_longer_active")

    def _pause_semantic_dispatches(self, dispatches, reason: str) -> None:
        """Release leases via channel pause + ResumeIntent (≠ destructive stop)."""

        skills = {item.request.skill for item in dispatches}
        with self._command_lock:
            if "NavigateTo" in skills:
                self.pause_navigation(reason=reason)
            if "FollowFormation" in skills:
                self._pause_channel("follow", reason=reason)
            if "SearchOwner" in skills:
                self._pause_channel("search", reason=reason)

    def _pause_channel(self, name: str, *, reason: str) -> None:
        """Dedicated pause path: navigator/channel.pause + ResumeIntent, no STOP table."""

        channel = self._channels.get(name)
        if channel is None or not channel.active():
            return
        now_s = time.monotonic()
        intent = channel.pause(reason)
        if intent is not None:
            if intent.suspended_at_s == 0.0:
                intent = ResumeIntent(
                    channel=intent.channel,
                    payload=intent.payload,
                    suspend_reason=intent.suspend_reason,
                    suspended_at_s=now_s,
                    valid_for_s=intent.valid_for_s,
                    requires_fresh_observation=intent.requires_fresh_observation,
                )
            self._resume_store.record(intent)
        with self._lock:
            self._generation.bump(name)
            self._behavior_generation += 1
            if name == "navigation":
                detail = dict(self._navigation_detail)
                detail["state"] = "paused"
                detail["enabled"] = True
                detail["reason"] = reason
                self._navigation_detail = NavigationDetail.from_dict(detail).as_dict()
            elif name == "follow":
                self._follow_detail = FollowDetail.from_dict(self.follow.snapshot()).as_dict()
            elif name == "search":
                self._search_detail = {
                    **self.search.snapshot(),
                    "reason": reason,
                    "state": "paused",
                }
        if name in {"navigation", "follow", "search"}:
            self.arbiter.cancel(name)

    def _stop_semantic_dispatches(self, dispatches, reason: str) -> None:
        skills = {item.request.skill for item in dispatches}
        with self._command_lock:
            targets: list[str] = []
            if "NavigateTo" in skills:
                targets.append("navigation")
            if {"OrbitOwner", "MoveRelative"} & skills:
                targets.append("spatial")
            if "FollowFormation" in skills:
                targets.append("follow")
            if "SearchOwner" in skills:
                targets.append("search")
            if targets:
                self.preempt("manual", reason=reason, targets=tuple(targets))

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
            self._expression_thread = threading.Thread(
                target=self._expression_loop,
                name="parcel-expression",
                daemon=True,
            )
            self._expression_thread.start()
            if self._microphone_loop is not None:
                try:
                    self._microphone_loop.start()
                    self._emit("voice", "Microphone loop started (VAD-segmented)", "info")
                except (OSError, RuntimeError) as error:
                    # Missing capture hardware degrades to text mode; motion
                    # control must never depend on an audio device.
                    self._microphone_loop = None
                    self._emit("voice", f"Microphone unavailable: {error}", "warning")
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
                    self.preempt(
                        "safety",
                        reason="runtime_closed",
                        targets=("follow", "search", "navigation", "spatial", "activities"),
                    )
                    self.agent.safety.engage_emergency_stop()
                    self.arbiter.engage_emergency_stop()
                    try:
                        self.control_manager.emergency_stop()
                    except (OSError, RuntimeError):
                        pass
                    self._last_sent = VelocityCommand()
                    self._was_moving = False
                    self.velocity_smoother.reset()
                    self._reset_motion_shaper()
            auxiliary_error: BaseException | None = None
            if self._microphone_loop is not None:
                try:
                    self._microphone_loop.close()
                except BaseException as error:  # noqa: BLE001 - device teardown
                    auxiliary_error = error
            try:
                self.voice_session.close(timeout=2.0)
            except BaseException as error:  # noqa: BLE001 - hardware teardown must continue
                auxiliary_error = error
            if self._speaker_sink is not None:
                try:
                    self._speaker_sink.close()
                except BaseException as error:  # noqa: BLE001 - device teardown
                    auxiliary_error = auxiliary_error or error
            for thread, timeout in (
                (self._thread, 2.0),
                (self._health_thread, 3.0),
                (self._expression_thread, 2.0),
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
            self.preempt(
                "manual",
                reason="manual_control",
                targets=("spatial", "follow", "navigation", "search", "activities"),
            )
            return self.submit_motion(
                "manual",
                VelocityCommand(vx=values[0], vy=values[1], vyaw=values[2]),
                ttl=0.45,
            )

    def _voice_motion(self, command: VelocityCommand) -> None:
        """Give an explicit locomotion command clean ownership of the body."""

        with self._command_lock:
            self._interrupt_brain("correction", "owner issued a direct motion command")
            self.preempt(
                "voice",
                reason="voice_motion_started",
                targets=("follow", "navigation", "spatial", "activities"),
            )
            self.submit_motion("voice", command, ttl=1.0)

    def stop_motion(self) -> None:
        with self._command_lock:
            self.preempt("manual", reason="motion_stopped", targets=("spatial",))
            self.arbiter.stop()
            with self._lock:
                simulator_feedback_available = self._observation is not None
            if not self._synchronous_control_dispatch or simulator_feedback_available:
                try:
                    self._ensure_compatibility_control_started()
                    self.control_manager.stop("runtime_stop")
                except ControlNotReadyError as error:
                    self._record_control_not_ready(error)
                except (OSError, RuntimeError) as error:
                    self._record_sim_error(error)
            self._last_sent = VelocityCommand()
            self._was_moving = False
            self.velocity_smoother.reset()
            self._reset_motion_shaper()

    def emergency_stop(self) -> None:
        with self._command_lock:
            self._interrupt_brain("emergency", "emergency stop latched")
            self.preempt(
                "safety",
                reason="emergency_stop",
                targets=("follow", "search", "navigation", "spatial", "activities"),
            )
            self.arbiter.engage_emergency_stop()
            try:
                self.control_manager.emergency_stop()
            except (OSError, RuntimeError) as error:
                self._record_sim_error(error)
            self._last_sent = VelocityCommand()
            self._was_moving = False
            self.velocity_smoother.reset()
            self._reset_motion_shaper()
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
                self.preempt(
                    "manual",
                    reason="owner_requested_stay",
                    targets=("follow", "navigation", "spatial", "activities"),
                )
                self.stop_motion()
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
            self.preempt(
                "follow",
                reason="owner_follow_started",
                targets=("spatial", "navigation", "search"),
            )
            if follow_mode == "behind":
                self.follow.start_formation("behind", distance_m=distance_m)
            elif follow_mode == "direct" and distance_m is None:
                self.follow.start()
            else:
                raise ValueError(f"unknown follow mode: {follow_mode}")
            with self._lock:
                self._generation.bump("follow")
                self._behavior_generation += 1
                self._follow_detail = FollowDetail.from_dict(self.follow.snapshot()).as_dict()
        message = (
            "Behind-owner formation enabled; acquiring motion heading"
            if follow_mode == "behind"
            else "Owner-follow enabled"
        )
        self._emit("behavior", message, "success")
        return message

    # --- owner reacquisition (card W7) --------------------------------------

    def _maybe_trigger_owner_search(self, decision, now: float) -> None:
        """Propose a search once follow has reported a lost owner long enough.

        The trigger is deterministic and never consults a model, but it still
        travels as an ordinary plan through validation, the executive, and
        verified completion, so interruption and invariants apply unchanged.
        """

        if decision.state != "lost":
            self._owner_lost_since = None
            return
        if self.search.enabled:
            return
        if self._owner_lost_since is None:
            self._owner_lost_since = now
            return
        if now - self._owner_lost_since < self.search.config.lost_timeout_s:
            return
        self._owner_lost_since = None
        self._submit_owner_search_plan()

    def _submit_owner_search_plan(self) -> None:
        if not self._brain_enabled or self._closed:
            return
        with self._lock:
            last_seen = self._last_confident_owner
        if last_seen is None:
            self._emit(
                "search",
                "Owner lost with no confident last position; holding instead of searching",
                "warning",
            )
            return
        with self._lock:
            self._owner_search_sequence += 1
            sequence = self._owner_search_sequence
        plan = compile_plan_contracts(
            PlanIR(
                schema_version=1,
                task_id=f"parcel-owner-search-{sequence}",
                plan_revision=1,
                source_turn_id=f"owner-lost-{sequence}",
                goal=GoalSpec(relation="reacquire", target=GoalTarget(kind="owner")),
                invariants=(),
                steps=(
                    PlanStep(
                        step_id="step_1",
                        skill="SearchOwner",
                        arguments=FrozenDict({}),
                        success=SuccessCondition(fact="owner_reacquired", target="owner"),
                    ),
                ),
            ),
            self.system_registry,
        )
        try:
            validated = self.system_plan_validator.validate(plan, self._build_brain_snapshot())
        except PlanValidationError as error:
            # Stale perception or a latched E-stop: fail closed and keep
            # following, rather than searching on evidence we do not trust.
            self._emit("search", f"Owner search not admitted: {error}", "warning")
            return
        submission = self.task_executive.submit(validated, task_class="system")
        if not submission.accepted:
            self._emit("search", f"Owner search rejected: {submission.reason}", "warning")
            return
        # Release the base only once the task is queued: the follow step (when
        # a semantic task owns it) fails on its next poll, which is what frees
        # the resource lease the search step is about to request.
        with self._command_lock:
            if self.follow.enabled:
                active = self.follow.snapshot()
                self._resume_follow_after_search = (
                    self.follow.mode,
                    (
                        float(active["desired_distance_m"])
                        if self.follow.mode == "behind"
                        else None
                    ),
                )
            # Table says search→follow is PAUSE; also record legacy resume tuple.
            self.preempt("search", reason="owner_search_queued", targets=("follow",))
        self._emit(
            "search",
            f"Owner lost for {self.search.config.lost_timeout_s:g}s; searching",
            "warning",
        )

    def _start_brain_owner_search(self) -> str:
        """Adapter dispatch: begin the three-state search from the loss point."""

        if self._closed:
            raise RuntimeError("runtime is closed")
        if self.arbiter.emergency_stopped:
            raise RuntimeError("motion is disabled by emergency stop")
        with self._lock:
            last_seen = self._last_confident_owner
        if last_seen is None:
            raise RuntimeError("no confident owner position to search from")
        with self._command_lock:
            self.preempt(
                "search",
                reason="owner_search_started",
                targets=("spatial", "navigation", "follow"),
            )
            self.search.start(
                last_x=last_seen[0],
                last_y=last_seen[1],
                lost_at_s=last_seen[2],
                now=time.monotonic(),
            )
            with self._lock:
                self._generation.bump("search")
                self._behavior_generation += 1
                self._search_detail = dict(self.search.snapshot())
        return "searching for the owner"

    def _step_owner_prediction(
        self,
        observation: SimObservation | None,
    ) -> PredictedPath | None:
        """Feed the owner predictor and return this tick's path, if any.

        The predictor is fed on every perception tick, not only while follow
        owns the base: a filter that only converges after the behavior starts
        would spend its first second of every follow in fallback.
        """

        if not self.follow.prediction.enabled:
            return None
        now = time.monotonic()
        if observation is None:
            self._owner_prediction = None
            return None
        owner = observation.owner
        if owner.owner_id != self._owner_predictor_id:
            # A different person is not a teleport of the same one.
            self.owner_predictor.reset()
            self._owner_predictor_id = owner.owner_id
        visible = (
            owner.visible
            and owner.confidence >= self.follow.config.min_confidence
            and math.isfinite(owner.x)
            and math.isfinite(owner.y)
        )
        try:
            self.owner_predictor.observe(
                owner.x if visible else 0.0,
                owner.y if visible else 0.0,
                now_s=now,
                visible=visible,
            )
            prediction = self.owner_predictor.predict(now_s=now)
        except ValueError as error:
            # Loud, and fail closed to the unpredicted controller rather than
            # letting a bad track steer a lead point.
            logger.warning("owner prediction rejected an observation: %s", error)
            self.owner_predictor.reset()
            self._owner_prediction = None
            return None
        self._owner_prediction = prediction
        return prediction

    def _reset_owner_prediction(self) -> None:
        self.owner_predictor.reset()
        self._owner_predictor_id = None
        self._owner_prediction = None

    def _record_owner_sighting(self, observation: SimObservation | None) -> None:
        """Remember where the owner last was, confidently, and when.

        This is the seed for ``go_to_last_observed`` and the origin of the
        reachability disk that prunes frontier candidates.
        """

        if observation is None:
            return
        owner = observation.owner
        if not owner.visible or owner.confidence < self.follow.config.min_confidence:
            return
        if not all(math.isfinite(value) for value in (owner.x, owner.y)):
            return
        with self._lock:
            self._last_confident_owner = (owner.x, owner.y, time.monotonic())

    def _step_search(self, observation: SimObservation | None) -> None:
        if not self.search.enabled:
            return
        with self._lock:
            generation = self._generation.current("search")
        decision = self.search.step(observation, now=time.monotonic())
        with self._lock:
            still_searching = (
                self._generation.is_current("search", generation)
                and not self._closed
                and (self.search.enabled or decision.done)
            )
            if still_searching:
                self._search_detail = {
                    **self.search.snapshot(),
                    "state": decision.state,
                    "reason": decision.reason,
                    "elapsed_s": decision.elapsed_s,
                    "target_x_m": decision.target_x_m,
                    "target_y_m": decision.target_y_m,
                }
        if not still_searching:
            self._stop_search_channel()
            return
        if decision.degraded and decision.degraded != self._last_search_degradation:
            self._last_search_degradation = decision.degraded
            self._emit("search", f"Owner search degraded: {decision.degraded}", "warning")
        if not decision.done:
            if decision.state != self._last_search_state:
                self._last_search_state = decision.state
                self._emit("search", f"{decision.state}: {decision.reason}", "info")
            try:
                self.submit_motion("search", decision.command, ttl=self.loop_period * 3.0)
            except RuntimeError:
                pass
            return
        self._finish_owner_search(decision)

    def _finish_owner_search(self, decision) -> None:
        """Terminal search state: resume following, or say so and wait."""

        self.arbiter.cancel("search")
        self._last_search_state = decision.state
        if decision.outcome == "owner_reacquired":
            self._emit("search", "Owner reacquired; resuming follow", "success")
            resume = self._resume_follow_after_search
            self._resume_follow_after_search = None
            if resume is not None:
                try:
                    self._enable_owner_follow(resume[0], distance_m=resume[1])
                except (RuntimeError, ValueError) as error:
                    self._emit("search", f"Could not resume follow: {error}", "warning")
            return
        # Give up cleanly: say it out loud, then hold. The failed step is what
        # the executive sees; the robot is left stopped either way.
        self._resume_follow_after_search = None
        try:
            self._brain_vocalize("I lost you — I'll wait here.")
        except ValueError:  # pragma: no cover - the text is a constant
            pass
        self.stop_motion()
        self._emit("search", "Search budget exhausted; holding position", "warning")

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
        self.preempt(
            "navigation",
            reason="navigation_started",
            targets=("spatial", "follow"),
        )
        with self._lock:
            self._generation.bump("navigation")
            self._behavior_generation += 1
            generation = self._behavior_generation
            observation = self._observation
        if observation is not None and not self._observation_is_fresh(observation):
            observation = None
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
                # Same scan pass as _step_navigation: omitting it made every
                # mission's first tick a spurious degraded-mode fallback.
                lidar=(
                    (observation.lidar_ranges or None) if observation is not None else None
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
        self._stop_navigation_channel()

    def pause_navigation(self, *, reason: str = "suspended") -> None:
        """Non-destructive suspend (≠ ``stop_navigation``); see PAUSE_SEMANTICS.md.

        Dedicated pause path — does **not** use ``preempt("voice")`` (voice→nav
        is STOP in the mined table). Calls navigator.pause() + ResumeIntent.
        """

        self._pause_channel("navigation", reason=reason)

    def resume_navigation(self, *, now_s: float | None = None) -> None:
        now = time.monotonic() if now_s is None else float(now_s)
        intent = self._resume_store.take("navigation", now_s=now)
        channel = self._channels.get("navigation")
        if channel is None:
            return
        if intent is None:
            # Allow resume even without a stored intent when the navigator is paused.
            channel.resume(
                ResumeIntent(
                    channel="navigation",
                    payload={},
                    suspend_reason="manual_resume",
                    suspended_at_s=now,
                    valid_for_s=1.0,
                ),
                now_s=now,
            )
        else:
            channel.resume(intent, now_s=now)
        with self._lock:
            if self._navigation_detail.get("state") == "paused":
                self._navigation_detail = NavigationDetail.from_dict(
                    {
                        **self._navigation_detail,
                        "state": "running",
                        "reason": "navigation_resumed",
                    }
                ).as_dict()

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
            self.preempt(
                "spatial",
                reason="replaced_by_new_spatial_behavior",
                targets=("follow", "navigation", "spatial", "activities"),
            )
            with self._lock:
                self._generation.bump("spatial")
                self._behavior_generation += 1
            detail = self.spatial.start(intent, observation)
            with self._lock:
                self._spatial_detail = SpatialDetail.from_dict(detail).as_dict()

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
                self.preempt(
                    "manual",
                    reason="operator_stop",
                    targets=("follow", "navigation", "spatial", "activities"),
                )
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
        base = self.prompt_library.render_system(
            personality_id=personality,
            function_ids=functions,
            runtime_context=self._prompt_runtime_context(),
        )
        if self.prompting.composer is None:
            return base
        composed = self.prompting.composer.compose()
        if not composed.text:
            return base
        return f"{base}\n\n{composed.text}"

    def _build_expression_engine(self) -> ExpressionEngine:
        """Resolve the ``expression:`` config section into a live engine."""

        config = dict(self.store.section("expression") or {})
        enabled = bool(config.pop("enabled", True))
        seed = int(config.pop("seed", 20260804))
        config.pop("rate_hz", None)
        beat_config = config.pop("beats", {}) or {}
        if not isinstance(beat_config, dict):
            raise TypeError("expression.beats must be a mapping")
        allowed_beats = {"base_amplitude_rad", "rise_s", "fall_s", "lag_compensation_s"}
        unknown_beats = set(beat_config) - allowed_beats
        if unknown_beats:
            raise ValueError(f"unsupported expression.beats keys: {sorted(unknown_beats)}")
        idle_config = config.pop("idle", {}) or {}
        if not isinstance(idle_config, dict):
            raise TypeError("expression.idle must be a mapping")
        if config:
            raise ValueError(f"unsupported expression config keys: {sorted(config)}")
        allowed = {"breathing_hz", "breathing_amplitude_m", "gesture_duration_s"}
        unknown = set(idle_config) - allowed
        if unknown:
            raise ValueError(f"unsupported expression.idle keys: {sorted(unknown)}")
        idle = IdleLayer(
            rng=random.Random(seed),
            **{key: float(value) for key, value in idle_config.items()},
        )
        return ExpressionEngine(
            self.robot_profile,
            idle=idle,
            reactions=ReactionHooks(),
            beats=BeatLayer(**{key: float(value) for key, value in beat_config.items()}),
            enabled=enabled,
        )

    def _expression_gate(self) -> ExpressionGate:
        arbitration = self.arbiter.snapshot()
        with self._lock:
            navigation_active = self._navigation_directive is not None
            proximity_state = self._proximity_state
        battery = self._battery_snapshot()
        active_source = arbitration.get("active_source")
        return ExpressionGate(
            emergency_stopped=bool(arbitration["emergency_stopped"]),
            proximity_clear=proximity_state == "clear",
            battery_critical=battery.state == "critical",
            skill_active=self.activities.running() is not None,
            navigation_active=navigation_active,
            follow_active=self.follow.enabled,
            spatial_active=self.spatial.active,
            # Any direct velocity lease (manual teleop, voice walk) commits
            # the body to a gait exactly like navigation does.
            teleop_active=active_source in {"manual", "voice"},
        )

    def _owner_bearing_rad(self) -> float:
        """Bearing to the owner in the robot's body frame (0 when unknown)."""

        with self._lock:
            observation = self._observation
        if observation is None or not observation.owner.visible:
            return 0.0
        dx = observation.owner.x - observation.robot.x
        dy = observation.owner.y - observation.robot.y
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return 0.0
        bearing = math.atan2(dy, dx) - observation.robot.yaw
        return math.atan2(math.sin(bearing), math.cos(bearing))

    def _step_expression(self) -> None:
        """Advance the expressive layer and publish its additive overlay."""

        offsets = self.expression.step(time.monotonic(), self._expression_gate())
        joint_offsets = self.expression.joint_offsets() if not offsets.is_zero else {}
        if joint_offsets == self._expression_sent:
            return
        publish = getattr(self.backend, "expression", None)
        if publish is None:
            # Backend without an expression channel: snapshot-only rendering.
            self._expression_sent = joint_offsets
            return
        try:
            publish(joint_offsets)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            # Decorative motion must never disturb the control loop or latch
            # a simulator fault; retry naturally on the next changed frame.
            # But say so once per transition — a per-tick validation error
            # (e.g. a large-morphology profile exceeding the IPC offset
            # bound) previously killed the whole channel in silence.
            if not self._expression_publish_failing:
                self._expression_publish_failing = True
                logger.warning("expression overlay publish failing: %s", error)
            self._expression_sent = None
            return
        if self._expression_publish_failing:
            self._expression_publish_failing = False
            logger.info("expression overlay publish recovered")
        self._expression_sent = joint_offsets

    def _prompt_current_situation(self) -> str | None:
        """Compact volatile turn-context line (never blocks: reads state only)."""

        battery = self._battery_snapshot()
        with self._lock:
            sim_status = self._sim_status
            navigation = dict(self._navigation_detail)
        parts = [f"battery {battery.percent:.0f}% ({battery.state})", f"sim {sim_status}"]
        if navigation.get("enabled"):
            parts.append(f"navigating: {navigation.get('state', 'moving')}")
        elif self.follow.enabled:
            parts.append("following the owner")
        return "Current situation: " + "; ".join(parts) + "."

    def set_user_fact(self, key: str, value: str) -> None:
        """Add/update one owner-profile fact; live on the next composed prompt."""

        if self.prompting.profile is None:
            raise RuntimeError("dynamic prompting is disabled (prompting.enabled: false)")
        self.prompting.profile.set_fact(key, value)

    def prompt_inspection(self) -> dict[str, object]:
        """The hillclimb view: full prompt, section breakdown, tools, facts."""

        composer = self.prompting.composer
        if composer is None:
            return {"enabled": False, "detail": self.prompting.detail}
        composed = composer.compose()
        return {
            "enabled": True,
            "detail": self.prompting.detail,
            "system_prompt": self._render_system_prompt(),
            "composed": composed.as_dict(),
            "registered_sources": list(composer.sources()),
            "turn_budget_chars": composer.turn_budget_chars,
            "tools": self.prompting.tools.definitions(),
            "profile_facts": (
                self.prompting.profile.facts() if self.prompting.profile else {}
            ),
        }

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
        with self._command_lock:
            self.preempt(
                "pose",
                reason="pose_started",
                targets=("follow", "navigation", "spatial", "search", "activities"),
            )
        with self._command_lock:
            if self.arbiter.emergency_stopped:
                raise RuntimeError("motion is disabled by emergency stop")
            self.arbiter.stop()
            self.control_manager.stop("pose_started")
            self._reset_motion_shaper()
            if not self._synchronous_control_dispatch:
                raise RuntimeError(
                    "physical poses must be implemented by the selected locomotion "
                    "controller; direct backend actuation is disabled"
                )
            self.backend.pose(pose)
        with self._lock:
            self._last_posture = pose.name

    def _run_trajectory(self, skill: object) -> None:
        if self.arbiter.emergency_stopped:
            raise RuntimeError("motion is disabled by emergency stop")
        with self._command_lock:
            self.preempt(
                "trajectory",
                reason="trajectory_started",
                targets=("follow", "navigation", "spatial", "search", "activities"),
            )
        with self._command_lock:
            if self.arbiter.emergency_stopped:
                raise RuntimeError("motion is disabled by emergency stop")
            self.arbiter.stop()
            self.control_manager.stop("trajectory_started")
            self._reset_motion_shaper()
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
        self._duplex_sync_epoch()
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
            search = dict(self._search_detail)
            last_brain_plan = (
                dict(self._last_brain_plan) if self._last_brain_plan is not None else None
            )
        if not self.follow.enabled:
            follow = self.follow.snapshot()
        # Card W4. Both halves of the dynamic-obstacle work report here so the
        # HUD and evals can tell "planning around people" from "not".
        navigation["dynamic_cost_active"] = self._dynamic_cost_active()
        navigation["min_time_to_collision_s"] = (
            None
            if not math.isfinite(self._min_time_to_collision_s)
            else self._min_time_to_collision_s
        )
        navigation["time_to_collision_gate"] = self.time_to_collision.enabled
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
        lidar_scan: dict[str, object] | None = None
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
            if observation.lidar_ranges:
                lidar_scan = {
                    "ranges": [
                        None if math.isnan(value) else round(value, 3)
                        for value in observation.lidar_ranges
                    ],
                    "angle_min_rad": observation.lidar_angle_min_rad,
                    "angle_increment_rad": observation.lidar_angle_increment_rad,
                    "range_min_m": observation.lidar_range_min_m,
                    "range_max_m": observation.lidar_range_max_m,
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
                "active_invariants": list(self._active_invariants),
                "battery": self._battery_snapshot().as_dict(),
                **brain_tasks,
            },
            "follow": follow,
            "owner_search": search,
            "navigation": navigation,
            "spatial_behavior": spatial,
            "audio": self.audio_status.as_dict(),
            "speech": {
                "mode": self.speech_stack.mode,
                "stt": self.speech_stack.stt_detail,
                "tts": self.speech_stack.tts_detail,
                "input_device_detail": self._input_device_detail,
                "output_device_detail": self._output_device_detail,
                "endpointing": self._endpointing_detail,
                "turn_commits": (
                    self._microphone_loop.turn_commits
                    if self._microphone_loop is not None
                    else 0
                ),
                "barge_ins": (
                    self._microphone_loop.barge_ins_triggered
                    if self._microphone_loop is not None
                    else 0
                ),
                "microphone_active": (
                    self._microphone_loop is not None and self._microphone_loop.running
                ),
                "playback_active": (
                    self._speaker_sink.playback_active
                    if self._speaker_sink is not None
                    else False
                ),
            },
            "perception": self.perception.snapshot(self.maps),
            "voice": voice,
            "model": {
                "status": self._model_status,
                "detail": self._model_detail,
                "roles": dict(self._model_role_status),
            },
            "robot": robot,
            "robot_profile": {
                "name": self.robot_profile.name,
                "dof": self.robot_profile.dof,
                "footprint_radius_m": self.robot_profile.footprint_radius_m,
            },
            "expression": self.expression.snapshot(),
            "duplex": self.duplex.snapshot(),
            "owner": owner,
            "dynamic_agents": dynamic_agents,
            "nearest_person": nearest_person,
            "lidar_scan": lidar_scan,
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
                        self.preempt(
                            "safety",
                            reason="simulator_emergency_stop",
                            targets=("follow", "navigation", "spatial", "search", "activities"),
                        )
                        self.agent.safety.engage_emergency_stop()
                        self.arbiter.engage_emergency_stop()
                        self.control_manager.emergency_stop()
                        self._reset_motion_shaper()
                    self._emit("safety", "Simulator emergency stop adopted", "error")
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                if not observe_recorded:
                    self.component_metrics.elapsed("SimulatorObserve", observe_started)
                observation = None
                self._record_sim_error(error)

            owner_track_started = time.monotonic()
            self.follow.observe_owner(observation, now=time.monotonic())
            self.component_metrics.elapsed("OwnerTrackHeadingFilter", owner_track_started)
            self._record_owner_sighting(observation)
            prediction = self._step_owner_prediction(observation)
            with self._lock:
                follow_generation = self._generation.current("follow")
            if self.follow.enabled:
                follow_started = time.monotonic()
                decision = self.follow.step(
                    observation, now=time.monotonic(), prediction=prediction
                )
                self.component_metrics.elapsed("FollowController", follow_started)
                with self._lock:
                    still_following = (
                        self._generation.is_current("follow", follow_generation)
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
                            "speed_scale": decision.speed_scale,
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
                if still_following:
                    self._maybe_trigger_owner_search(decision, time.monotonic())
            else:
                with self._lock:
                    self._follow_detail = self.follow.snapshot()
                if last_follow_state != "idle":
                    # One place covers every follow-stop entry point: they all
                    # end with the controller disabled, and this is the tick
                    # that observes it. Idle ticks keep feeding the filter so a
                    # later follow starts warm instead of in fallback.
                    self._reset_owner_prediction()
                last_follow_state = "idle"
                self._owner_lost_since = None

            search_started = time.monotonic()
            self._step_search(observation)
            self.component_metrics.elapsed("OwnerSearchController", search_started)

            spatial_started = time.monotonic()
            self._step_spatial(observation)
            self.component_metrics.elapsed("SpatialController", spatial_started)

            navigation_started = time.monotonic()
            self._step_navigation(observation)
            self.component_metrics.elapsed("NavigationController", navigation_started)

            self._enforce_perception_invariant(observation)
            self._step_brain()

            activity_started = time.monotonic()
            self._step_activities()
            self.component_metrics.elapsed("ActivityCoordinator", activity_started)

            dispatch_started = time.monotonic()
            self._dispatch_active()
            self.component_metrics.elapsed("MotionDispatch", dispatch_started)
            duplex_started = time.monotonic()
            self._step_duplex(observation)
            self.component_metrics.elapsed("DuplexProducer", duplex_started)
            elapsed = time.monotonic() - started
            self.component_metrics.observe_ms("ControlLoopWork", elapsed * 1000.0)
            self.component_metrics.observe_ms(
                "ControlLoopOverrun",
                max(0.0, elapsed - self.loop_period) * 1000.0,
            )
            self._stop_event.wait(max(0.0, self.loop_period - elapsed))

    def _expression_loop(self) -> None:
        """Run expression on its own faster channel.

        Beat-synced nods are judged against the pitch accent they land on
        (target P50 < 30 ms), and a 10 Hz control tick can only ever resolve
        ~50 ms. Expression is a pure additive overlay that decides nothing,
        so giving it its own 50 Hz channel costs no arbitration risk.
        """

        period = 1.0 / self.expression_hz
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                self._step_expression()
            except Exception as error:  # noqa: BLE001 - decorative thread boundary
                logger.warning("expression loop error: %s", error)
            self.component_metrics.elapsed("ExpressionLayer", started)
            self._stop_event.wait(max(0.0, period - (time.monotonic() - started)))

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
            self._sync_shaper_with_control_watchdog()
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
            # Card W6. The last thing before the SE2 hand-off, and after every
            # authority above it has spoken. Stops route to the emergency
            # bypass so no stop decision is ever smoothed.
            command = self._shape_for_actuator(
                command,
                now=now,
                stopping=(
                    proximity_state == "stopped"
                    or self.arbiter.emergency_stopped
                    # The *intent* decides, not the pre-gate smoother's ramp:
                    # asking for zero is a stop even while the ramp is still
                    # emitting a non-zero value on its way down.
                    or active is None
                    or _is_zero_command(active.command)
                ),
            )
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
                    self._control_not_ready_reason = None
                except ControlNotReadyError as error:
                    self._record_control_not_ready(error)
                except (OSError, RuntimeError, ValueError) as error:
                    self._record_sim_error(error)
            elif controller_delivery_available and active is None and self._was_moving:
                try:
                    self.control_manager.stop("intent_expired")
                except ControlNotReadyError as error:
                    self._record_control_not_ready(error)
                except (OSError, RuntimeError) as error:
                    self._record_sim_error(error)
                self._last_sent = VelocityCommand()
                self._was_moving = False
                self.velocity_smoother.reset(now=now)
                self._reset_motion_shaper()
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
                    except ControlNotReadyError as error:
                        self._record_control_not_ready(error)
                    except (OSError, RuntimeError, TypeError, ValueError) as error:
                        self._record_sim_error(error)

    def _note_vocal_arousal(self, arousal: float) -> None:
        if not math.isfinite(arousal):
            return
        with self._lock:
            self._vocal_arousal = max(0.0, min(1.0, arousal))
            self._vocal_arousal_at = time.monotonic()

    def _motion_profile(self, now: float) -> str:
        """Pick the shaper profile from measured vocal arousal.

        With no recent evidence the nominal profile wins: "calm" has to be
        observed, not assumed, or the robot would spend its whole life at 60%
        of its acceleration budget.
        """

        config = self.motion_shaping
        with self._lock:
            arousal = self._vocal_arousal
            measured_at = self._vocal_arousal_at
        if arousal is None or measured_at is None:
            return "nominal"
        if now - measured_at > config.arousal_valid_s:
            return "nominal"
        return "calm" if arousal <= config.calm_below_arousal else "nominal"

    def _shape_for_actuator(
        self,
        command: VelocityCommand,
        *,
        now: float,
        stopping: bool,
    ) -> VelocityCommand:
        """Jerk-limit the outgoing command, bypassing for every stop."""

        config = self.motion_shaping
        if not config.enabled:
            return command
        profile = self._motion_profile(now)
        if profile != self._shaper_profile:
            limits = self._nominal_shaper_limits
            shaper = SCurveVelocityShaper(*limits)
            if profile == "calm":
                shaper = shaper.scaled(config.calm_scale)
            # Carry the velocity across the profile change so switching
            # profiles is not itself a step in the actuator command.
            shaper.reset(self._last_shaped)
            self._motion_shaper = shaper
            self._shaper_profile = profile

        last = self._shaped_at
        dt_s = 0.1 if last is None else max(1e-3, min(0.25, now - last))
        self._shaped_at = now
        vx, vy, vyaw = self._motion_shaper.step(
            (command.vx, command.vy, command.vyaw),
            dt_s=dt_s,
            emergency=stopping,
        )
        self._last_shaped = (vx, vy, vyaw)
        return VelocityCommand(vx=vx, vy=vy, vyaw=vyaw)

    def _reset_motion_shaper(self) -> None:
        """Drop shaper state so a hard stop cannot ramp out of stale velocity.

        Every stop entry point that bypasses ``_dispatch_active`` calls this:
        the actuator has been commanded to zero directly, so the shaper's idea
        of the current velocity is no longer true. The ControlManager command
        watchdog also reaches here via ``_sync_shaper_with_control_watchdog``.
        """

        self._motion_shaper.reset()
        self._last_shaped = (0.0, 0.0, 0.0)
        self._shaped_at = None

    def _sync_shaper_with_control_watchdog(self) -> None:
        """Reset the shaper when the manager watchdog stops hardware.

        The arbiter lease and the ControlManager command TTL are independent.
        A manager watchdog stop can fire while a longer arbiter lease is still
        live; without this sync the shaper would resume from a stale velocity
        on the next shaped tick (arbitration 2026-08-04).
        """

        status = self.control_manager.snapshot()
        if status.watchdog_stops <= self._seen_watchdog_stops:
            return
        self._seen_watchdog_stops = status.watchdog_stops
        if status.last_stop_reason in {
            "command_watchdog_expired",
            "command_expired_during_delivery",
        }:
            self._reset_motion_shaper()

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
            generation = self._generation.current("navigation")
        if directive is None or self.follow.enabled:
            return
        if observation is None:
            with self._lock:
                if (
                    self._generation.is_current("navigation", generation)
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
                    self._generation.is_current("navigation", generation)
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
                    lidar=observation.lidar_ranges or None,
                    publish=False,
                    extras=self._navigation_extras(observation),
                )
        except (LookupError, RuntimeError, TypeError, ValueError) as error:
            with self._lock:
                still_current = (
                    self._generation.is_current("navigation", generation)
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
                self._generation.is_current("navigation", generation)
                and directive == self._navigation_directive
                and not self.follow.enabled
                and not self._closed
                and not self.arbiter.emergency_stopped
            )
            if not still_current:
                return
            mission_status = (
                mission.status_value()
                if hasattr(mission, "status_value")
                else str(mission.status)
            )
            paused = bool(
                command.stop
                and (mission_status == "paused" or command.note == "mission_paused")
            )
            verifying = bool(command.stop and mission_status == "verifying")
            if paused:
                # Pause is not a destructive terminal — keep the directive.
                self._navigation_detail = {
                    "enabled": True,
                    "state": "paused",
                    "directive": directive,
                    "goal": place,
                    "reason": command.note or "mission_paused",
                }
                self.arbiter.cancel("navigation")
            elif command.stop and not verifying:
                self._navigation_directive = None
                self._navigation_detail = {
                    "enabled": False,
                    "state": mission_status,
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
                    if mission_status == "searching"
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
        if paused:
            return
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
            if mission_status == "arrived":
                self._emit("navigation", f"Arrived at {place}", "success")
            else:
                self._emit(
                    "navigation",
                    f"Navigation failed for {place}: {command.note or mission_status}",
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
            "lidar_angle_min_rad": observation.lidar_angle_min_rad,
            "lidar_angle_increment_rad": observation.lidar_angle_increment_rad,
            "lidar_range_min_m": observation.lidar_range_min_m,
            "lidar_range_max_m": observation.lidar_range_max_m,
            "obstacle_bearing_rad": observation.nearest_obstacle_bearing_rad,
            "obstacle_id": observation.nearest_obstacle_id,
            "person_bearing_rad": observation.nearest_person_bearing_rad,
            "person_id": observation.nearest_person_id,
            "person_ttc_s": observation.nearest_person_ttc_s,
            "lidar_obstacles": lidar_payload_from_observation(observation),
            "semantic_candidates": semantic_candidates_from_observation(observation),
            # Card W4. The planner separates these two so it can weight the
            # owner's social envelope differently from a stranger's.
            "dynamic_agents": _dynamic_agent_payload(observation),
            "owner_track": self._owner_track_payload(observation),
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

    def _dynamic_cost_active(self) -> bool:
        try:
            return bool(self.dog.nav_dynamic_cost_active())
        except (AttributeError, RuntimeError):
            return False

    def _owner_track_payload(
        self,
        observation: SimObservation,
    ) -> tuple[dict[str, float], ...]:
        """Return the owner as a velocity track, using the predictor when live.

        Without the predictor the owner is a stationary lobe, which is still
        the right shape: the planner should route around where the owner is,
        just without anticipating where they are going.
        """

        owner = observation.owner
        if not owner.visible or not (math.isfinite(owner.x) and math.isfinite(owner.y)):
            return ()
        prediction = self._owner_prediction
        if prediction is None:
            velocity = (0.0, 0.0)
        else:
            velocity = (
                prediction.speed_mps * math.cos(prediction.heading_rad),
                prediction.speed_mps * math.sin(prediction.heading_rad),
            )
        return (
            {
                "x": float(owner.x),
                "y": float(owner.y),
                "vx": float(velocity[0]),
                "vy": float(velocity[1]),
                "radius_m": 0.35,
            },
        )

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
            self._reset_motion_shaper()
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
                self.preempt(
                    "manual",
                    reason="perception_unavailable",
                    targets=("spatial",),
                )
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
        command, proximity_state = apply_reactive_safety(
            command,
            observation,
            policy=self.reactive_safety_policy,
            owner_orbit=owner_orbit,
            orbit_radius_m=float(spatial_detail.get("orbit_radius_m") or 0.0),
            now=time.monotonic(),
        )
        return self._time_to_collision_gate(command, observation, proximity_state)

    def _time_to_collision_gate(
        self,
        command: VelocityCommand,
        observation: SimObservation | None,
        proximity_state: str,
    ) -> tuple[VelocityCommand, str]:
        """Scale the outgoing command down when contact is predicted.

        This runs *after* the geometric gate and only ever multiplies by a
        factor in [0, 1], so it can brake a command the geometric gate allowed
        but can never release one the geometric gate stopped. That ordering is
        what keeps `collision.py` and `reactive_safety.py` the unconditional
        last line of defence, unmodified.
        """

        config = self.time_to_collision
        if not config.enabled or observation is None:
            self._min_time_to_collision_s = math.inf
            return command, proximity_state
        try:
            verdict = time_to_collision_verdict(
                config=config,
                tracks=tracks_from_payload(_dynamic_agent_payload(observation)),
                robot_xy=(observation.robot.x, observation.robot.y),
                robot_yaw_rad=observation.robot.yaw,
                command_vx=command.vx,
                command_vy=command.vy,
                proximity_state=proximity_state,
            )
        except (TypeError, ValueError) as error:
            logger.warning("time-to-collision gate skipped this tick: %s", error)
            self._min_time_to_collision_s = math.inf
            return command, proximity_state

        self._min_time_to_collision_s = verdict.time_to_collision_s
        if not verdict.intervened:
            return command, proximity_state
        gated = VelocityCommand(
            vx=command.vx * verdict.scale,
            vy=command.vy * verdict.scale,
            vyaw=command.vyaw * verdict.scale,
        )
        return gated, verdict.proximity_state

    def _record_control_not_ready(self, error: BaseException) -> None:
        """Controller readiness rejections are control conditions, not
        simulator transport failures: perception/telemetry stay valid, so the
        observation and sim status must not be touched. Logged once per
        transition to avoid loop-rate event spam."""

        message = str(error)
        if message != self._control_not_ready_reason:
            self._control_not_ready_reason = message
            self._emit("control", f"Command rejected: {message}", "warning")

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

    def _duplex_slow_path(self, reason: str) -> None:
        """Predictive filler before planner / info-tool slow work."""

        if not self.duplex.enabled:
            return
        fire = self.duplex.predictive_filler(reason="predictive")
        if fire is None:
            return
        self.duplex.push_filler_act(index=0)
        if fire.entry.gesture == "<thinking_pose>":
            self.expression.reactions.on_turn_pending(time.monotonic())
        meta = self._duplex_turn_meta.setdefault(self._duplex_latest_turn_id, {})
        meta["filler_used"] = fire.entry.text
        meta["filler_reason"] = fire.reason
        # FillerLatency is recorded only when the filler becomes audible.
        self.voice_session.play_filler(fire.entry.text, turn_id=self._duplex_latest_turn_id)
        self._emit("duplex", f"filler:{fire.reason}:{reason}", "info")

    def _duplex_filler_audible(self) -> None:
        self.duplex.on_filler_audible()
        latency = self.duplex.filler.filler_latency_s
        if latency is not None:
            self.component_metrics.observe_ms("FillerLatency", latency * 1000.0)
        meta = self._duplex_turn_meta.setdefault(self._duplex_latest_turn_id, {})
        meta["filler_audible"] = True
        if self.duplex.filler.last_filler_text:
            meta.setdefault("filler_used", self.duplex.filler.last_filler_text)

    def _duplex_sync_epoch(self) -> None:
        epoch = int(self.voice_session.speech_epoch)
        if epoch != self.duplex.epoch:
            self.duplex.set_epoch(epoch)

    def _duplex_has_tts_path(self) -> bool:
        return self._speaker_sink is not None

    def _duplex_record_turn_outcome(self, turn_id: int, *, barge_in: bool = False) -> None:
        if not self.duplex.enabled:
            return
        meta = self._duplex_turn_meta.pop(int(turn_id), {})
        if barge_in:
            meta["barge_in"] = True
        outcome = {
            "turn_id": int(turn_id),
            "ttft_s": meta.get("ttft_s"),
            "filler_used": meta.get("filler_used"),
            "filler_reason": meta.get("filler_reason"),
            "filler_audible": bool(meta.get("filler_audible", False)),
            "barge_in": bool(meta.get("barge_in", False)),
        }
        self.duplex.record_turn_outcome(outcome)

    def _duplex_on_voice_stage(self, stage: VoiceStage) -> None:
        if not self.duplex.enabled:
            return
        self._duplex_sync_epoch()
        if stage.name == "query_end":
            self._duplex_latest_turn_id = int(stage.turn_id)
            self.duplex.on_turn_start(now_s=stage.timestamp)
            self._duplex_turn_meta[int(stage.turn_id)] = {
                "query_end_s": float(stage.timestamp),
                "barge_in": False,
            }
        elif stage.name in {"tts_first_chunk", "audio_first_playback"}:
            # First token on the TTS / audible path cancels the watchdog.
            self.duplex.on_first_token(now_s=stage.timestamp)
            meta = self._duplex_turn_meta.setdefault(int(stage.turn_id), {})
            if meta.get("ttft_s") is None and isinstance(meta.get("query_end_s"), (int, float)):
                meta["ttft_s"] = float(stage.timestamp) - float(meta["query_end_s"])
        elif stage.name == "tts_text_chunk" and stage.reply:
            # Observe the same sentence/chunk tokens the spoken path is synthesizing.
            self.duplex.push_text_tokens(stage.reply)
        elif stage.name == "reasoning_response":
            # LLM text alone must NOT cancel the watchdog when a TTS path exists.
            # Text-only mode has no TTS queue; reply delivery is the audible path.
            if stage.reply and not self._duplex_has_tts_path():
                self.duplex.on_first_token(now_s=stage.timestamp)
                self.duplex.push_text_tokens(stage.reply)
                meta = self._duplex_turn_meta.setdefault(int(stage.turn_id), {})
                if meta.get("ttft_s") is None and isinstance(
                    meta.get("query_end_s"), (int, float)
                ):
                    meta["ttft_s"] = float(stage.timestamp) - float(meta["query_end_s"])
        elif stage.name == "filler_clause_boundary_wait" and stage.reply:
            # Mirror the voice-session clause-boundary queue into filler policy
            # so duplex snapshot / session log see the pending handoff.
            self.duplex.filler.note_clause_boundary_pending(stage.reply)
        elif stage.name == "filler_audible":
            self.duplex.on_filler_audible(now_s=stage.timestamp)
        elif stage.name == "superseded":
            self._duplex_sync_epoch()
            meta = self._duplex_turn_meta.setdefault(int(stage.turn_id), {})
            meta["barge_in"] = True
        elif stage.name in {"turn_complete", "error"}:
            if stage.name == "error":
                self._duplex_sync_epoch()
            self._duplex_record_turn_outcome(int(stage.turn_id))

    def _step_duplex(self, observation: SimObservation | None) -> None:
        if not self.duplex.enabled:
            return
        self._duplex_sync_epoch()
        fire = self.duplex.poll_watchdog()
        if fire is not None:
            self.duplex.push_filler_act(index=0)
            if fire.entry.gesture == "<thinking_pose>":
                self.expression.reactions.on_turn_pending(time.monotonic())
            meta = self._duplex_turn_meta.setdefault(self._duplex_latest_turn_id, {})
            meta["filler_used"] = fire.entry.text
            meta["filler_reason"] = fire.reason
            # Latency sample waits for audible confirmation (_duplex_filler_audible).
            self.voice_session.play_filler(fire.entry.text, turn_id=self._duplex_latest_turn_id)
        # ResponseCeilingBreach is a counter on the duplex snapshot only — do
        # not re-observe it as a rolling ms metric every control tick.
        # ACT feed: encode what was actually commanded post-gate.
        commanded = self._last_sent
        if any(abs(v) > 1e-9 for v in (commanded.vx, commanded.vyaw)):
            self.duplex.push_twist(commanded.vx, commanded.vyaw)
        context: dict[str, object] = {
            "activity": self.activities.snapshot().get("running"),
            "follow_enabled": self.follow.enabled,
            "expression": {
                "producer": self.expression.snapshot().get("producer"),
                "orients_triggered": self.expression.reactions.orients_triggered,
                "thinking_holds": self.expression.reactions.thinking_holds,
            },
        }
        if observation is not None:
            owner = observation.owner
            context["owner"] = {
                "x_m": float(owner.x) if math.isfinite(owner.x) else None,
                "y_m": float(owner.y) if math.isfinite(owner.y) else None,
                "visible": bool(owner.visible),
            }
        self.duplex.tick(context=context)

    def _voice_partial_received(self, transcript: str) -> None:
        with self._lock:
            self._voice_detail = {
                **self._voice_detail,
                "status": "listening",
                "partial": transcript,
            }

    def _fire_text_mode_emotes(self, reply: str) -> None:
        """Fire a reply's emote tags immediately when there is no audio path.

        With a synthesizer the tags ride their chunk to ``_audio_chunk_started``
        and land with the words. Text mode has no playback clock to wait for,
        so the reply reaching the chat log is the only moment available.
        """

        for name, intensity in strip_emote_tags(reply)[1]:
            self._speech_emote(name, intensity)

    def _voice_turn_completed(self, turn: VoiceTurn) -> None:
        if self._speaker_sink is None and not turn.superseded:
            self._fire_text_mode_emotes(turn.reply)
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
        # Expressive reactions ride the same stage events the latency ledger
        # uses: think visibly from end-of-query until the reply is audible.
        if stage.name == "query_end":
            self.expression.reactions.on_turn_pending(time.monotonic())
        elif stage.name in {"audio_first_playback", "turn_complete", "error"}:
            self.expression.reactions.on_reply_started(time.monotonic())
        self._duplex_on_voice_stage(stage)
        if stage.name == "query_end":
            with self._lock:
                self._voice_query_end_by_turn[stage.turn_id] = stage.timestamp
                if len(self._voice_query_end_by_turn) > 64:
                    oldest = min(self._voice_query_end_by_turn)
                    self._voice_query_end_by_turn.pop(oldest, None)
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
        if stage.name == "audio_first_playback":
            # The single most important companion-voice number: end of the
            # owner's speech to the first audible robot audio.
            with self._lock:
                query_end = self._voice_query_end_by_turn.get(stage.turn_id)
            if query_end is not None and stage.timestamp >= query_end:
                self.component_metrics.observe_ms(
                    "VoiceEndOfSpeechToFirstAudio",
                    (stage.timestamp - query_end) * 1000.0,
                )
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

    def _build_endpointing(
        self, speech_config: dict
    ) -> tuple[object | None, object | None, str]:
        """Resolve ``speech.endpointing`` into a VAD + turn endpointer.

        ``energy`` (default) keeps the historical hangover segmentation.
        ``semantic`` adds Silero v6 framing and Smart Turn commit decisions;
        both degrade loudly to the energy path when their weights or
        onnxruntime are missing, and the resolved detail is reported in the
        snapshot so nobody has to guess which path is live.
        """

        mode = str(speech_config.get("endpointing", "energy")).strip().lower()
        if mode not in {"energy", "semantic"}:
            raise ValueError("speech.endpointing must be 'energy' or 'semantic'")
        if mode == "energy":
            return None, None, "energy (VAD hangover)"

        vad_model = speech_config.get("vad_model")
        neural_vad = None
        vad_detail = "energy VAD"
        if vad_model:
            candidate = SileroVad(str(vad_model))
            if candidate.available:
                neural_vad = candidate
                vad_detail = f"silero ({vad_model})"
            else:
                vad_detail = f"silero unavailable ({vad_model})"
                self._emit(
                    "voice",
                    f"Silero VAD weights unusable at {vad_model}; using the energy VAD",
                    "warning",
                )
        endpointer = TurnEndpointer(
            str(speech_config["turn_model"]) if speech_config.get("turn_model") else None,
            complete_silence_s=float(speech_config.get("complete_silence_s", 0.20)),
            incomplete_silence_s=float(speech_config.get("incomplete_silence_s", 2.5)),
        )
        detail = f"semantic: {endpointer.detail} + {vad_detail}"
        self._emit("voice", f"Endpointing: {detail}", "info")
        return neural_vad, endpointer, detail

    def _record_turn_commit(self, latency_s: float) -> None:
        self.component_metrics.observe_ms("TurnCommitLatency", latency_s * 1000.0)

    def _resolve_speech_device(self, spec: object, *, kind: str) -> tuple[int | None, str]:
        """Resolve one configured audio device, degrading loudly on failure."""

        try:
            return resolve_audio_device(spec, kind=kind)
        except (OSError, TypeError, ValueError) as error:
            detail = f"unavailable ({error})"
            self._emit(
                "voice",
                f"Configured {kind} audio device {spec!r} is unusable: {error}; "
                "falling back to the system default",
                "warning",
            )
            return None, detail

    def _owner_speech_started(self) -> None:
        """Owner began speaking: look at them (expressive reaction only)."""

        bearing = self._owner_bearing_rad()
        self.expression.reactions.on_speech_start(time.monotonic(), bearing)
        if self.duplex.enabled:
            # Attention decision → gaze ACT token (owner look-at).
            if abs(bearing) < 1e-6:
                self.duplex.push_gaze_owner()
            else:
                self.duplex.push_gaze_bearing(bearing)

    def _owner_speech_ended(self) -> None:
        self.expression.reactions.on_speech_end(time.monotonic())
        if self.duplex.enabled:
            self.duplex.push_gaze_release()

    def _microphone_failed(self, error: Exception) -> None:
        """Mid-session capture death degrades loudly to text mode.

        Invoked from the microphone worker thread; without this the loop dies
        silently while status keeps reporting an active microphone.
        """

        self._microphone_loop = None
        self._emit(
            "voice",
            f"Microphone unavailable: {error}; degrading to text mode",
            "warning",
        )


def http_service_health(url: str, timeout: float = 0.5) -> bool:
    """Small reusable health probe for locally isolated model services."""
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        return False
