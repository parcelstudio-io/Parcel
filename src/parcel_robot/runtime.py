from __future__ import annotations

import logging
import math
import os
import random
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from parcel_robot.agent import EMERGENCY_STOP_PHRASES, VoiceAgent
from parcel_robot.attention.stimuli import StimulusKind
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
from parcel_robot.brain.executive import (
    CLOSED_INTENT_PAUSE_REASON,
    CLOSED_INTENT_RESUME_REASON,
)
from parcel_robot.brain.observations import (
    build_observation_snapshot,
    task_state_from_executive,
)
from parcel_robot.brain.runtime_adapter import PAUSABLE_SKILL_CHANNELS
from parcel_robot.config import ConfigStore
from parcel_robot.context import (
    CallableContextProvider,
    ClockContextProvider,
    ContextBuildConfig,
    ContextBuilder,
    ContextField,
)
from parcel_robot.contracts.v1 import DialogueActV1
from parcel_robot.control import (
    BufferedRobotStateSource,
    ControlManager,
    ControlNotReadyError,
    FaultReason,
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
from parcel_robot.core.hard_stop import (
    InterventionSeverity,
    ResetObligation,
    finalize_command,
)
from parcel_robot.core.input_health import (
    InputEvidence,
    InputOrigin,
    RequiredInput,
    evaluate_input_health,
)
from parcel_robot.core.preemption import PreemptionTable
from parcel_robot.core.resume import (
    GenerationTokens,
    ResumeIntent,
    ResumeStore,
    resume_rejection_reason,
)
from parcel_robot.core.yield_policy import (
    YIELD_ACTION_ASK,
    YIELD_ACTION_GIVE_UP,
    PersonalityPolicyConfig,
    YieldDecision,
    YieldTracker,
    load_personality_policy_config,
    person_blocked_from_note,
)
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
from parcel_robot.navigation.goals import pace_from_directive
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
from parcel_robot.observability import (
    ComponentMetrics,
    LatencyTracker,
    append_latency_ledger_row,
    latency_ledger_row,
    resolve_latency_ledger_path,
)
from parcel_robot.perception import NullMapProvider, PerceptionContract
from parcel_robot.pose import (
    POSE_PROVIDER_KEY,
    TruthPoseProvider,
    update_provider_from_sim,
)
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
from parcel_robot.skills.executor import ExecutionResult
from parcel_robot.tiered_memory import ConcatSummarizer
from parcel_robot.voice.amendment import AMEND_SUSPEND_REASON, begin_goal_amend
from parcel_robot.voice.closed_intents import ClosedIntent
from parcel_robot.voice.dialogue_state import DialogueStateChannel
from parcel_robot.voice.executive_caps import CapDirective, PaceCap, resolve_cap
from parcel_robot.voice.local_plans import SETTLE_POSE_PHRASES
from parcel_robot.voice.reaction_bridge import SocialReactionBridge
from parcel_robot.voice.yield_speech import yield_dialogue_act
from parcel_robot.voice_audio import (
    MicrophoneVoiceLoop,
    SpeakerSink,
    resolve_audio_device,
)
from parcel_robot.voice_pipeline import (
    SYSTEM_UTTERANCE_KIND,
    DuplexVoiceSession,
    VoiceStage,
    VoiceTurn,
)

logger = logging.getLogger(__name__)

#: The ``last_detail`` the executive writes when the closed-intent PAUSE cap
#: parks a task. RESUME reads it to tell its own paused work apart from work an
#: owner summons or a goal amendment parked.
CLOSED_INTENT_SUSPEND_DETAIL = f"suspended:{CLOSED_INTENT_PAUSE_REASON}"

#: The note ``DirectiveNavigator._pose_lost_hold`` puts on its stop command
#: while MAP localization is ``LOST`` (Lane B, B-3). It is a **hold**, not an
#: outcome: the navigator leaves the mission running because the goal is still
#: valid and health can return. The literal is duplicated from
#: ``navigation/pipeline.py`` (and ``evals/walk_with_me/runner.py``) because
#: both live in trees this lane does not own; the shared home is a hand-off.
POSE_LOST_HOLD_NOTE = "pose_lost_hold"
#: What the robot says when it loses localization. Same sentence the
#: walk_with_me trace has carried, unspoken, since Lane B: it states what
#: happened and what the robot did, and claims nothing about recovery.
POSE_LOST_UTTERANCE = "I've lost track of where I am, so I've stopped and I'm holding here."
#: Said only from a tick on which the navigator is driving again, which it can
#: only do once MAP health has returned — so the claim cannot outrun the fact.
POSE_REGAINED_UTTERANCE = "I know where I am again — carrying on."


#: Leading verbs a navigation directive uses before the goal noun; stripped so the
#: open-vocab camera detector is queried for the object, not the phrasing (Card B4).
_CAMERA_QUERY_PREFIXES = (
    "go to the ", "go to ", "walk to the ", "walk to ", "navigate to the ",
    "navigate to ", "move to the ", "move to ", "head to the ", "head to ",
    "go towards the ", "go toward the ", "walk towards the ", "walk toward the ",
    "go over to the ", "go over to ", "find the ", "find ", "go to my ", "the ",
)


def _camera_query_from_directive(directive: str) -> str:
    """Extract the goal noun phrase a navigation directive points at (best-effort).

    ``go to the lamppost`` → ``lamppost``. Purely lexical: it strips a leading
    navigation verb and trailing punctuation so the open-vocab detector is asked
    for the object. Returns the cleaned directive unchanged when no prefix matches
    (the detector still gets a reasonable phrase).
    """

    text = " ".join(str(directive).split()).strip().lower().rstrip(".!?,")
    if not text:
        return ""
    for prefix in _CAMERA_QUERY_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    return text


class LLMSummarizer:
    """A real tiered-memory summarizer over the existing ``LanguageModel`` seam.

    Card memory-write-path: replaces the deterministic :class:`ConcatSummarizer`
    stand-in when a conversation model is wired, so aged-out turns are *abstracted*
    into a rolling summary instead of concatenated. Called only on the write path
    (``TieredMemory.append``), never on a read, so its latency is off the retrieval
    path. Degrades to the deterministic fixture on ANY failure or empty reply —
    memory must never break a turn, and offline runs must stay deterministic.
    """

    def __init__(self, model: LanguageModel, *, max_chars: int = 1200) -> None:
        self._model = model
        self._max_chars = int(max_chars)
        self._fallback = ConcatSummarizer(max_chars=int(max_chars))

    def __call__(self, previous_summary: str, aged_turns: Any) -> str:
        turns = [
            f"{turn.role}: {turn.content}"
            for turn in aged_turns
            if getattr(turn, "content", "").strip()
        ]
        if not turns:
            return previous_summary
        prompt = (
            "You keep a concise running summary of a conversation between an owner "
            "and their robot dog. Update the summary with the new turns below, "
            "preserving durable facts (names, preferences, plans, feelings, "
            "commitments) and dropping small talk. Reply with ONLY the updated "
            f"summary, at most {self._max_chars} characters.\n\n"
            f"Current summary:\n{previous_summary or '(none yet)'}\n\n"
            "New turns:\n" + "\n".join(turns)
        )
        try:
            decision = self._model.decide(prompt, [], [])
            summary = " ".join(str(decision.reply).split()).strip()
        except Exception as error:  # noqa: BLE001 - degrade, never break the write path
            logger.warning("LLM summarizer failed; using deterministic fallback: %s", error)
            return self._fallback(previous_summary, aged_turns)
        if not summary:
            return self._fallback(previous_summary, aged_turns)
        if len(summary) > self._max_chars:
            summary = summary[: self._max_chars - 1].rstrip() + "…"
        return summary


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
        # Card B4 — camera on the mission path. When enabled AND an in-process
        # camera ingress is attached (``attach_camera_ingress``), the reactive
        # navigation view derives ``semantic_candidates`` from RENDERED PIXELS via
        # an async open-vocab detector instead of the GT-frustum oracle. Default
        # OFF (env ``PARCEL_CAMERA_INGRESS`` or ``camera_ingress.enabled: true``),
        # so the shipped oracle path stays byte-identical until a caller opts in
        # AND supplies the model/data the EGL backend needs (the socket backend
        # runs the sim out-of-process, so ingress is a same-process opt-in).
        self._camera_ingress: Any = None
        camera_ingress_cfg = self.store.section("camera_ingress")
        self._camera_ingress_config_enabled = bool(camera_ingress_cfg.get("enabled", False))
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
        # P0-C proposal-buffer flush (product-path activation): the executive's
        # committed (task_id, plan_revision) for the live mission. Stamped onto the
        # navigator's SE2Goal proposals so a correction's revision bump — flushed
        # into the navigator's proposer_bus / goal_arbiter revision sinks — rejects
        # a straggler proposal authored under the corrected-away revision. Default
        # ("", 0) is the backward-compatible no-op key an unwired channel used.
        self._active_nav_revision: tuple[str, int] = ("", 0)
        #: Edge state for the owner-facing localization announcement.
        self._pose_lost_announced = False
        #: Blocked-by-a-person yield policy (card P-1). Installed from the
        #: personality config below; the tracker is fed one navigation note per
        #: control tick and never sees a velocity.
        self._yield_clock: Callable[[], float] = time.monotonic
        self._yield_tracker = YieldTracker()
        self._yield_profile = PersonalityPolicyConfig.builtin().for_personality(
            "gentle_companion"
        )
        self._last_yield_act: DialogueActV1 | None = None
        # Whether the last yield utterance actually reached the speaker.
        # U35: the ask used to be text-only, and a snapshot that showed the
        # sentence without this field implied audio that never existed.
        self._last_yield_act_audible: bool = False
        self._yield_asks_spoken = 0
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
        # K6/P2: closed-intent pace caps + dialogue-state × T2 + social reactions.
        self._pace_cap = PaceCap()
        # Pace asked for by the directive itself ("running to the tree"); the
        # pre-mission scale so it can be handed back when the mission ends.
        self._directive_pace_restore: float | None = None
        self._dialogue_state = DialogueStateChannel()
        self._dialogue_pace_factor = 1.0
        self._dialogue_last: dict[str, object] = {}
        self._dialogue_gaze_mode = "idle"
        self._amendment_pending = False
        self._reaction_bridge = SocialReactionBridge(rng_seed=11)
        self._reaction_last: dict[str, object] = {}
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
        #: Latched by the dispatch input-health join (malformed / frame faults).
        self._input_health_latched = False
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
        self._personality_policy = self._load_personality_policy(agent_config)
        self._install_yield_profile(self._personality)
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
        # Activity-owned pose/trajectory callbacks re-enter the command lock.
        # Mark that narrow dispatch window so they do not preempt the
        # coordinator record that launched them.
        self._activity_dispatch_active = False
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
        # Stratum-1 pose authority (see ``parcel_robot.pose``). The runtime owns
        # exactly one provider and feeds it sim truth every observation; every
        # navigation consumer reads it by REP-105 frame name. TruthPoseProvider
        # is the shipping default and returns the same floats the observation
        # already carried, so installing it changes no behavior. Swapping in a
        # real localizer is a one-line change here and nowhere else.
        self._pose_provider = TruthPoseProvider()
        # Stratum-2 perception authority. The detection_adapter chain is the one
        # semantic-candidate ingress; the runtime installs the tier the
        # navigation config names. T0 (the shipping default) is pass-through and
        # byte-identical to the oracle read it replaces.
        self._install_perception_chain()
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
        # Model-facing: explicitly NOT system-authored (arbitration OB-2).
        self.brain_registry = admitted_registry.restricted(
            configured_brain_skills,
            system_authored=False,
        )
        # System recovery plans are authored by the runtime, never by a model,
        # so they validate against a registry the planner never sees.
        self.system_registry = admitted_registry.restricted(
            set(configured_brain_skills) | SemanticTaskRuntimeAdapter.SYSTEM_SKILLS,
            system_authored=True,
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
            hold=self._brain_hold,
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
        # Card memory-write-path: when tiered memory is enabled AND a conversation
        # model is wired, replace the deterministic offline summarizer with a real
        # LLM ``summarize()`` over the existing provider seam. No model → keep the
        # deterministic ConcatSummarizer fixture (offline-deterministic). Guarded so
        # a future contract rename degrades loudly instead of crashing startup.
        if self.prompting.memory is not None and language_model is not None:
            if hasattr(self.prompting.memory, "_summarizer"):
                self.prompting.memory._summarizer = LLMSummarizer(language_model)
            else:  # pragma: no cover - tiered-memory contract changed under us
                logger.warning(
                    "tiered memory has no summarizer seam; keeping deterministic default"
                )
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
            closed_intent_handler=self._apply_closed_intent,
            pace_scale_provider=lambda: self._pace_cap.scale,
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
        # Acoustic-ack fan-in (N19). The capture loop, the STT provider and the
        # speaker sink each already measure their own clock; nothing joined
        # them to a turn. These three fields are that join: the turn whose
        # audio the sink is currently writing, and the last capture/STT clocks
        # already consumed, so a typed turn can never inherit the previous
        # spoken turn's timings.
        self._audio_output_turn_id = 0
        self._acoustic_commit_consumed: float | None = None
        self._stt_request_consumed: float | None = None
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

    def _stop_navigation_channel(
        self, *, reason: str = "navigation_disabled", state: str = "idle"
    ) -> None:
        """Channel-level navigation stop (no re-entrant preempt).

        ``reason``/``state`` exist so a caller that knows *why* it is stopping
        can say so in one write. Without them the yield policy's honest give-up
        would have to stop first and overwrite the detail afterwards, and the
        executive polls between those two writes — it would read
        ``navigation_disabled`` and attribute the failure to nothing.
        """

        with self._lock:
            self._generation.bump("navigation")
            self._behavior_generation += 1
            was_enabled = self._navigation_directive is not None
            self._navigation_directive = None
            self._yield_tracker.reset()
            if was_enabled:
                self._navigation_detail = NavigationDetail.from_dict(
                    {
                        **self._navigation_detail,
                        "enabled": False,
                        "state": state,
                        "reason": reason,
                    }
                ).as_dict()
        self.arbiter.cancel("navigation")
        self._restore_directive_pace()
        if was_enabled:
            with self._navigation_lock:
                self.dog.stop()

    def _stop_search_channel(self) -> None:
        self.search.stop()
        self.arbiter.cancel("search")
        # Abandoned search must not later resurrect follow via a leftover intent.
        self._resume_store.clear("follow")
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
        """Adapt the configured model contract to the existing PlanIR runtime.

        The registry is selected by *route*, the same way ``_accept_plan``
        selects it: ``direct_skill`` output is a PlanSketch the runtime itself
        authored and gets the system registry; ``deliberative_plan`` output is
        model-authored and gets the model-facing one. Compiling everything
        against ``brain_registry`` made the runtime's own settle step
        (``Pose``) fail contract lookup on a plan no model had touched, which
        is what the compiler's system-contract fallback existed to paper over
        (H7). Widening nothing: ``_accept_plan`` re-compiles and re-validates
        against the same route-selected registry immediately after.
        """

        registry = (
            self.system_registry if frame.route == "direct_skill" else self.brain_registry
        )
        return materialize_planner_output(
            output,
            frame,
            snapshot,
            registry,
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
        # K6/B1: system-authored local PlanSketch also enters via direct_skill.
        if frame.route not in {"deliberative_plan", "direct_skill"}:
            raise ValueError(
                "only deliberative or direct_skill IntentFrames may publish PlanIR"
            )
        if plan.source_turn_id != frame.turn_id:
            raise ValueError("PlanIR source turn does not match IntentFrame")

        # Route decides the authority, and the route comes from the
        # versioned deterministic router (``brain.router.ROUTER_VERSION``), never
        # from a model: ``deliberative_plan`` carries model output and gets the
        # model-facing registry; ``direct_skill`` carries the runtime's own
        # closed-intent PlanSketches and gets the system registry, which is the
        # only one that admits system-authored arguments (arbitration OB-2).
        system_authored = frame.route == "direct_skill"
        registry = self.system_registry if system_authored else self.brain_registry
        validator = self.system_plan_validator if system_authored else self.plan_validator
        plan = compile_plan_contracts(plan, registry)

        snapshot = self._build_brain_snapshot()
        validation_started = time.monotonic()
        validated = validator.validate(plan, snapshot)
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
        # P0-C: this plan is now the committed steering revision for its task. A
        # correction reached here via ``replace()``, which already flushed the
        # navigator's proposer sinks in the executive's locked transaction; stamp
        # the navigator so its *next* proposals carry the new revision (an
        # already-running navigator is stamped now, a cold-starting one at nav
        # start). Non-nav plans harmlessly re-point the key at their own task.
        self._active_nav_revision = (plan.task_id, plan.plan_revision)
        existing_navigator = getattr(self.dog, "_navigator", None)
        if existing_navigator is not None:
            self._apply_active_nav_revision(existing_navigator)
        accepted_at = time.monotonic()
        self.component_metrics.observe_ms(
            "PlanAcceptance", (accepted_at - acceptance_started) * 1000.0
        )
        self.agent.last_brain_metrics["_plan_accepted_monotonic"] = accepted_at
        if self._amendment_pending:
            self._amendment_pending = False
            self.agent.last_brain_metrics["goal_amend_committed"] = True
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
        if goal.relation == "follow":
            return "Okay—I'll follow you safely."
        if goal.relation == "relative":
            return "Okay—I'll make that bounded move and verify the distance."
        if goal.relation == "safe_pose":
            return "Okay—I'll move to a safe place and settle there."
        if goal.relation == "hold":
            # `hold`/`current_pose` is the only goal shape the validator admits
            # for a terminal Pose step, so a compound *settle* plan wears it
            # too. Keying on the goal relation alone answered "Okay—I'll stay
            # here." to a command that walks to a bench and sits down (H2), so
            # read the plan instead of only its goal.
            settle = RobotRuntime._settle_acknowledgement(plan)
            return settle if settle is not None else "Okay—I'll stay here."
        return "Okay—I accepted the task and will carry it out safely."

    @staticmethod
    def _settle_acknowledgement(plan: PlanIR) -> str | None:
        """Acknowledge a `hold` plan that travels first; ``None`` if it does not.

        Nothing here claims arrival: the sentence describes what the robot will
        *do*, in the order the plan does it, which is the same honesty rule the
        rest of this table follows.
        """

        navigate = next((step for step in plan.steps if step.skill == "NavigateTo"), None)
        if navigate is None:
            return None
        place = str(navigate.success.target or "").strip()
        where = f" to {place}" if place else " there"
        posture = next(
            (step for step in plan.steps if step.skill in {"Pose", "ReturnToSafePose"}),
            None,
        )
        if posture is None:
            return f"Okay—I'll head over{where} and hold there."
        pose = str(
            posture.arguments.get("name") or posture.arguments.get("pose") or ""
        ).strip()
        return f"Okay—I'll head over{where} and {SETTLE_POSE_PHRASES.get(pose, 'settle')}."

    DEFAULT_EMOTES = (
        "attentive_nod",
        "bow",
        "chuckle",
        "comfort_bow",
        "confused_head_tilt",
        "curious_look",
        "excited_paw_taps",
        "happy_wiggle",
        "head_nod",
        "head_shake",
        "hello_pose",
        "hop",
        "look_left",
        "look_right",
        "observing_head_tilt",
        "paw_wave",
        "play_bow",
        "shake",
        "shrug",
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

        # Fourth acoustic-ack clock (N19), taken before the token guard: an
        # un-analyzable chunk carries no token but is still the moment the
        # speaker worker started writing audio, which is what the ack budget
        # is measured against. ``mark`` is first-wins, so later chunks of the
        # same reply do not move it.
        self._mark_audio_first_sample()
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

    @staticmethod
    def _load_personality_policy(agent_config: Mapping[str, Any]) -> PersonalityPolicyConfig:
        """Resolve ``configs/personality.yaml`` (or an explicitly named file).

        Absence and corruption are answered differently on purpose. A checkout
        or wheel that does not ship the file gets the documented built-in
        defaults — the policy only decides how long to wait and what to say, so
        a missing file must not take the runtime down. A file that *is* present
        but malformed raises: silently adopting half a policy is the failure
        mode the repo's fail-closed config rule exists to prevent. An
        explicitly configured path that is missing also raises, because
        somebody asked for it by name.
        """

        configured = agent_config.get("personality_policy")
        if configured:
            return load_personality_policy_config(str(configured))
        from parcel_robot.paths import resolve_asset

        try:
            path = resolve_asset("configs", "personality.yaml", kind="file")
        except FileNotFoundError:
            return PersonalityPolicyConfig.builtin()
        return load_personality_policy_config(path)

    def _install_yield_profile(self, personality_id: str) -> None:
        """Point the yield tracker at one personality's policy (clears state)."""

        profile = self._personality_policy.for_personality(personality_id)
        self._yield_profile = profile
        self._yield_tracker.configure(profile.policy)
        self._yield_asks_spoken = 0
        self._last_yield_act = None
        self._last_yield_act_audible = False

    def yield_policy_snapshot(self) -> dict[str, Any]:
        """Inspection surface for the blocked-by-a-person policy.

        Deliberately a method rather than a ``snapshot()`` key: the panel
        snapshot shape is pinned by tests, and this is diagnostic state, not a
        channel detail.
        """

        with self._lock:
            profile = self._yield_profile
            act = self._last_yield_act
            act_audible = self._last_yield_act_audible
            asks = self._yield_asks_spoken
        payload = profile.as_dict()
        payload["asks_spoken"] = int(asks)
        payload["tracker"] = self._yield_tracker.snapshot()
        payload["last_utterance"] = None if act is None else act.as_dict()
        payload["last_utterance_audible"] = None if act is None else bool(act_audible)
        return payload

    def _speak_system_utterance(self, text: str) -> bool:
        """Attempt to make one system-initiated line audible; never raise.

        A voice failure must not take down the caller — navigation, the
        executive, and the search give-up all speak from paths where an
        exception would abandon a mission. Returns whether an output worker
        was started.
        """

        try:
            return bool(self.voice_session.speak_system(text, kind=SYSTEM_UTTERANCE_KIND))
        except Exception as error:  # noqa: BLE001 - speech must never break a mission
            logger.warning("system utterance could not be spoken: %s", error)
            return False

    def _brain_vocalize(self, text: str) -> bool:
        """Say one system-initiated line: chat, event, AND audio.

        Every utterance the robot starts by itself comes through here — the
        ``Vocalize`` and ``AskClarification`` skills, the localization-health
        announcements, the search give-up, and the yield policy's ask /
        re-ask / give-up lines. Until 2026-08-09 this method wrote the chat
        item and the event and returned, so all of them were *visible in the
        panel and inaudible in the room* (backlog U35). It now also attempts
        the speaker through :meth:`DuplexVoiceSession.speak_system`.

        The chat item and the event are still written unconditionally, and
        first-class: they are the record, and they must not depend on whether
        this host has a synthesizer. What the audio attempt buys is that the
        event no longer *implies* sound that never happened — the outcome
        rides the event's ``detail`` and the return value.

        ``True`` means an output worker was started (synthesis + sink handoff
        attempted), which is exactly what ``audio_first_playback`` means for
        an ordinary reply. It is not an acoustic guarantee.
        """

        clean = " ".join(str(text).split())
        if not clean:
            raise ValueError("brain utterance is empty")
        # Speak first, record second: the sentence reaches the speaker without
        # waiting on the panel bookkeeping, and the event can then state the
        # truth about whether it was audible instead of guessing.
        audible = self._speak_system_utterance(clean)
        if self._speaker_sink is None:
            audio_path = "text_only"
        elif audible:
            audio_path = "voice_tts"
        else:
            # The speaker was busy with a reply/filler, or the session is
            # closing. speak_system skips rather than overlapping; the yield
            # policy's re-ask timer is the retry.
            audio_path = "suppressed_output_busy"
        self._chat_item("assistant", clean)
        self._emit(
            "brain",
            clean,
            "info",
            detail={"audible": audible, "audio_path": audio_path},
        )
        return audible

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

    def _apply_directive_pace(self, pace: str | None) -> None:
        """Mission-scoped pace from directive phrasing, via the FASTER cap.

        No new speed authority: this reuses exactly the bounded ``PaceCap``
        scale the spoken "go faster" intent sets, and restores the previous
        scale when the mission ends (SpeedRegime consolidation is Lane A's).
        """

        if pace != "fast" or self._directive_pace_restore is not None:
            return
        directive = resolve_cap(ClosedIntent.FASTER, current_pace=self._pace_cap.scale)
        if directive.pace_scale is None:
            return
        self._directive_pace_restore = self._pace_cap.scale
        self._pace_cap.set_scale(directive.pace_scale)
        self._emit(
            "navigation",
            f"pace scale set to {self._pace_cap.scale:.2f} (directive pace)",
            "info",
        )

    def _restore_directive_pace(self) -> None:
        """Hand the pace scale back at mission end (idempotent)."""

        scale = self._directive_pace_restore
        if scale is None:
            return
        self._directive_pace_restore = None
        self._pace_cap.set_scale(scale)

    def _apply_closed_intent(self, intent: ClosedIntent, directive: CapDirective) -> str:
        """Executive / CommandArbiter caps for the closed companion intent enum."""

        if directive.emergency_stop or intent is ClosedIntent.STOP:
            self.emergency_stop()
            return directive.reply
        if directive.pace_scale is not None:
            self._pace_cap.set_scale(directive.pace_scale)
            self._emit(
                "voice",
                f"pace scale set to {self._pace_cap.scale:.2f} ({intent.value})",
                "info",
            )
            return directive.reply
        if directive.suspend:
            # True PAUSE on pausable channels (same path as pause_navigation).
            # Do NOT preempt("voice") for navigation/follow/search — voice→nav
            # is STOP in the mined table and would destroy ResumeIntent.
            with self._command_lock:
                for channel_name in ("navigation", "follow", "search"):
                    self._pause_channel(channel_name, reason=CLOSED_INTENT_PAUSE_REASON)
                # Non-pausable channels: STOP / clear is correct.
                self.preempt(
                    "voice",
                    reason=CLOSED_INTENT_PAUSE_REASON,
                    targets=("spatial", "activities"),
                )
                for row in self.task_executive.snapshot().get("tasks", []):
                    if not isinstance(row, dict):
                        continue
                    if row.get("state") not in {
                        "running",
                        "waiting_checkpoint",
                        "waiting_resource",
                        "waiting_precondition",
                        "queued",
                    }:
                        continue
                    task_id = row.get("task_id")
                    if isinstance(task_id, str):
                        self.task_executive.request_interrupt(
                            InterruptRequest(
                                source="voice",
                                reason=CLOSED_INTENT_PAUSE_REASON,
                                requested="interrupt_now",
                                target_task_id=task_id,
                            )
                        )
            return directive.reply
        if directive.resume:
            # Fresh-scene resume is owned by channel ResumeIntent / K3 path.
            # Fail closed: do not claim success when nothing resumes.
            now_s = time.monotonic()
            resumed: list[str] = []
            failed: list[str] = []
            refused: list[str] = []
            parked = self._suspended_tasks_by_channel()
            for channel_name in ("navigation", "follow", "search"):
                if self._resume_store.peek(channel_name, now_s=now_s) is None:
                    continue
                # N14: the channel and the plan step that authorized it resume
                # together or not at all. A channel driving under a suspended
                # task has no running verification, timeout, or recovery policy;
                # a channel whose task is parked by someone *else* (an owner
                # summons, a goal amendment) is not this command's to release.
                owners = parked.get(channel_name, ())
                foreign = tuple(
                    task_id
                    for task_id, detail in owners
                    if detail != CLOSED_INTENT_SUSPEND_DETAIL
                )
                if foreign:
                    refused.append(channel_name)
                    self._emit(
                        "voice",
                        f"resume {channel_name} refused: suspended by {foreign}",
                        "warning",
                    )
                    continue
                try:
                    with self._command_lock:
                        self._resume_from_store(channel_name, now_s=now_s)
                        blocked = self._resume_parked_tasks(owners, now_s=now_s)
                        if blocked:
                            self._pause_channel(
                                channel_name, reason=CLOSED_INTENT_PAUSE_REASON
                            )
                            raise RuntimeError(f"executive task blocked: {blocked}")
                    resumed.append(channel_name)
                except (RuntimeError, ValueError, AttributeError) as error:
                    failed.append(channel_name)
                    self._emit(
                        "voice",
                        f"resume {channel_name} failed: {error}",
                        "warning",
                    )
            # Steps whose controller is stopped rather than paused by a suspend
            # (spatial behaviors, postures, gestures) carry no ResumeIntent, so
            # they are re-queued for a fresh dispatch instead of re-bound.
            requeued = self._requeue_parked_tasks(parked.get(None, ()))
            # Two different refusals, said differently. Reporting a
            # someone-else-holds-this refusal as a freshness problem would send
            # the owner to fix the wrong thing.
            if not resumed and not requeued:
                if refused:
                    return (
                        "I can't resume that yet — it's paused by something "
                        "else right now."
                    )
                if failed:
                    return (
                        "I couldn't resume yet — the observation isn't fresh "
                        "enough, or the paused task expired."
                    )
                return "There's nothing paused to resume right now."
            if failed or refused:
                return (
                    f"Resumed {', '.join(resumed) or 'the paused task'}, but "
                    f"couldn't resume {', '.join(failed + refused)}."
                )
            return directive.reply
        if directive.goal_amend:
            return self._apply_goal_amend(directive)
        return directive.reply

    def _suspended_tasks_by_channel(self) -> dict[str | None, tuple[tuple[str, str], ...]]:
        """Channel → the suspended executive tasks that own it, with their reason.

        Keyed by the channel the suspended step drives, with ``None`` for steps
        whose controller has no pausable channel. Both halves of the key matter
        to RESUME: the channel says which stored intent a task authorizes, and
        the detail says *who* parked it — an owner summons and a goal amendment
        park tasks too, and a spoken RESUME must neither restart that work nor
        release its channel behind its back.
        """

        parked: dict[str | None, list[tuple[str, str]]] = {}
        for row in self.task_executive.snapshot().get("tasks", []):
            if not isinstance(row, dict):
                continue
            if row.get("state") != "suspended":
                continue
            task_id = row.get("task_id")
            if not isinstance(task_id, str):
                continue
            skill = row.get("skill")
            channel = PAUSABLE_SKILL_CHANNELS.get(skill) if isinstance(skill, str) else None
            parked.setdefault(channel, []).append((task_id, str(row.get("last_detail") or "")))
        return {key: tuple(value) for key, value in parked.items()}

    def _resume_parked_tasks(
        self,
        parked: tuple[tuple[str, str], ...],
        *,
        now_s: float,
    ) -> tuple[str, ...]:
        """Re-bind suspended tasks to their already-restored controllers.

        Returns the tasks that could **not** be returned to ``running`` (the
        caller re-pauses the channel on any of them, so the channel never drives
        without its plan step).
        """

        blocked: list[str] = []
        for task_id, _detail in parked:
            disposition, request = self.task_executive.resume_task_running(
                task_id, reason=CLOSED_INTENT_RESUME_REASON, now=now_s
            )
            if not disposition.accepted or request is None:
                blocked.append(f"{task_id}:{disposition.action}")
                continue
            # The controller kept its state across the pause and has just been
            # restored from the stored intent, so the step is already executing:
            # re-bind tracking rather than dispatching it again (a second
            # dispatch would cold-start the mission).
            self.semantic_tasks.adopt(request, now=now_s)
        return tuple(blocked)

    def _requeue_parked_tasks(self, parked: tuple[tuple[str, str], ...]) -> int:
        """Re-queue suspended tasks whose controller was stopped, not paused."""

        requeued = 0
        for task_id, detail in parked:
            if detail != CLOSED_INTENT_SUSPEND_DETAIL:
                continue
            # Drop any stale dispatch record first: the executive will emit a
            # fresh DispatchRequest with the same key, and the adapter refuses a
            # dispatch whose key is already active.
            self.semantic_tasks.cancel((task_id,))
            disposition = self.task_executive.resume_task(
                task_id, reason=CLOSED_INTENT_RESUME_REASON
            )
            if disposition.accepted:
                requeued += 1
        return requeued

    def _apply_goal_amend(self, directive: CapDirective) -> str:
        """Pause/snapshot active work for mid-task amendment (fail-closed)."""

        now_s = time.monotonic()
        active: list[str] = []
        paused: list[str] = []
        with self._command_lock:
            for channel_name in ("navigation", "follow", "search"):
                channel = self._channels.get(channel_name)
                if channel is not None and channel.active():
                    active.append(channel_name)
                elif self._resume_store.peek(channel_name, now_s=now_s) is not None:
                    paused.append(channel_name)
            # Executive tasks still count as amendable work.
            for row in self.task_executive.snapshot().get("tasks", []):
                if not isinstance(row, dict):
                    continue
                if row.get("state") in {
                    "running",
                    "waiting_checkpoint",
                    "waiting_resource",
                    "waiting_precondition",
                    "queued",
                    "suspended",
                }:
                    if "executive" not in active and "executive" not in paused:
                        active.append("executive")
                    break

            gate = begin_goal_amend(active_channels=active, paused_channels=paused)
            self.agent.last_brain_metrics["goal_amend_ok"] = gate.ok
            self.agent.last_brain_metrics["goal_amend_reason"] = gate.reason
            if not gate.ok:
                self._amendment_pending = False
                return gate.reply

            paused_now: list[str] = []
            for channel_name in ("navigation", "follow", "search"):
                channel = self._channels.get(channel_name)
                if channel is not None and channel.active():
                    self._pause_channel(channel_name, reason=AMEND_SUSPEND_REASON)
                    paused_now.append(channel_name)
            for row in self.task_executive.snapshot().get("tasks", []):
                if not isinstance(row, dict):
                    continue
                if row.get("state") not in {
                    "running",
                    "waiting_checkpoint",
                    "waiting_resource",
                    "waiting_precondition",
                    "queued",
                }:
                    continue
                task_id = row.get("task_id")
                if isinstance(task_id, str):
                    self.task_executive.request_interrupt(
                        InterruptRequest(
                            source="voice",
                            reason=AMEND_SUSPEND_REASON,
                            requested="interrupt_now",
                            target_task_id=task_id,
                        )
                    )
            self._amendment_pending = True
            self._emit(
                "voice",
                f"goal amend snapshot: paused={paused_now or list(gate.paused_channels)}",
                "info",
            )
            return directive.reply if directive.reply else gate.reply

    def _step_reaction_bridge(self, observation: SimObservation | None) -> None:
        """Tick StimulusBus/ReactionArbiter; never preempt base (K6/B2)."""

        del observation  # reserved for future affect/prosody fusion
        now_s = time.monotonic()
        with self._lock:
            base_busy = bool(
                self.follow.enabled
                or self._navigation_directive is not None
                or self.arbiter.current(now=now_s) is not None
            )
            nav_detail = dict(self._navigation_detail)
            dialogue_phase = self._dialogue_state.phase
            dialogue_engagement = self._dialogue_state.engagement
        critical = str(nav_detail.get("state", "")) in {
            "crossing",
            "collision_recovery",
            "verifying",
        }
        # Feed dialogue-state into the bus as a T2 stimulus (white-space join).
        if dialogue_phase in {"listening", "thinking", "speaking"}:
            self._reaction_bridge.add_stimulus(
                StimulusKind.DIALOGUE_STATE,
                at_s=now_s,
                confidence=max(0.05, min(1.0, float(dialogue_engagement))),
                payload={"phase": dialogue_phase, "engagement": dialogue_engagement},
                commit=True,
            )
        result = self._reaction_bridge.tick(
            now_s=now_s,
            base_busy=base_busy,
            critical_phase=critical,
            factors={"sociability": 0.7, "playfulness": 0.5},
        )
        self._reaction_last = {
            "reaction": result.decision.reaction,
            "vetoed": result.vetoed,
            "reason": result.reason,
            "false_base_preempt_attempts": self._reaction_bridge.false_base_preempt_attempts,
            "drained": len(result.drained),
        }

    def _step_dialogue_state(self, observation: SimObservation | None) -> None:
        """Publish DialogueStateMsg @ 10 Hz and apply T2 gaze/pace influence."""

        now_s = time.monotonic()
        now_ns = time.monotonic_ns()
        msg = self._dialogue_state.publish(now_ns)
        influence = self._dialogue_state.influence(now_ns)
        # Soft pace overlay only — never raises above PaceCap, never authors vx.
        self._dialogue_pace_factor = float(influence.pace_scale_factor)
        prev_gaze = self._dialogue_gaze_mode
        self._dialogue_gaze_mode = influence.gaze_mode
        self._dialogue_last = {
            "msg": msg.as_dict(),
            "influence": influence.as_dict(),
            "amendment_pending": self._amendment_pending,
        }
        # Gaze conditioning (attention track only — no base / safety).
        if influence.gaze_mode != prev_gaze:
            bearing = 0.0
            if observation is not None:
                bearing = self._owner_bearing_rad()
            if influence.gaze_mode == "mutual":
                self.expression.reactions.on_speech_start(now_s, bearing)
                if self.duplex.enabled:
                    if abs(bearing) < 1e-6:
                        self.duplex.push_gaze_owner()
                    else:
                        self.duplex.push_gaze_bearing(bearing)
            elif influence.gaze_mode == "aversion":
                self.expression.reactions.on_turn_pending(now_s)
                if self.duplex.enabled:
                    self.duplex.push_gaze_release()
            elif influence.gaze_mode == "soft":
                self.expression.reactions.on_reply_started(now_s)
            else:
                self.expression.reactions.on_speech_end(now_s)
                if self.duplex.enabled:
                    self.duplex.push_gaze_release()

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

        # One table for "which skill owns which pausable channel", shared with
        # the RESUME join: a disagreement here is a channel that resumes with no
        # running plan step behind it (N14).
        channels = {
            PAUSABLE_SKILL_CHANNELS[item.request.skill]
            for item in dispatches
            if item.request.skill in PAUSABLE_SKILL_CHANNELS
        }
        with self._command_lock:
            for channel_name in ("navigation", "follow", "search"):
                if channel_name in channels:
                    self._pause_channel(channel_name, reason=reason)

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
            if self._camera_ingress is not None:
                try:
                    self._camera_ingress.stop()
                except BaseException as error:  # noqa: BLE001 - render teardown must continue
                    auxiliary_error = error
                self._camera_ingress = None
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
            # One latency row per run, once the voice path is quiesced so the
            # snapshot covers every completed turn. Opt-in and best-effort: an
            # unconfigured ledger writes nothing, and a failed write must never
            # turn a clean shutdown into an exception.
            try:
                self.write_latency_ledger_row(source="runtime_close")
            except BaseException as error:  # noqa: BLE001 - observability must not block teardown
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
        # Closed-intent pace caps scale commanded velocity before arbitration.
        # Dialogue-state may only apply a further slowdown (≤1.0) — never raise
        # speed, never author model velocity. Manual/emergency/safety untouched.
        if source not in {"manual", "safety", "emergency"}:
            vx, vy, vyaw = self._pace_cap.scale_command(
                command.vx, command.vy, command.vyaw
            )
            factor = float(self._dialogue_pace_factor)
            if factor < 1.0:
                factor = max(0.35, min(1.0, factor))
                vx, vy, vyaw = vx * factor, vy * factor, vyaw * factor
            command = VelocityCommand(vx=vx, vy=vy, vyaw=vyaw)
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

    def _brain_hold(self) -> None:
        """PlanIR Hold: settle in place and release follow/nav ownership."""

        with self._command_lock:
            self.preempt(
                "manual",
                reason="hold_skill",
                targets=("follow", "navigation", "spatial", "search", "activities"),
            )
            # Destructive settle: STOP leaves ResumeIntent untouched; clear so a
            # prior pause cannot resurrect follow/nav/search after "I'll stay".
            self._resume_store.clear("follow")
            self._resume_store.clear("navigation")
            self._resume_store.clear("search")
            self.arbiter.stop()
            with self._lock:
                simulator_feedback_available = self._observation is not None
            if not self._synchronous_control_dispatch or simulator_feedback_available:
                try:
                    self._ensure_compatibility_control_started()
                    self.control_manager.stop("runtime_hold")
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
                # Same destructive settle as PlanIR Hold: clear leftover intents.
                self._resume_store.clear("follow")
                self._resume_store.clear("navigation")
                self._resume_store.clear("search")
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
        if clean not in FollowOwnerController.FORMATION_MODES:
            raise ValueError(f"unsupported owner formation relation: {relation}")
        self._interrupt_brain("correction", "owner requested a new follow formation")
        return self._start_brain_follow_formation(clean, distance_m)

    def _start_brain_follow_formation(
        self,
        relation: str,
        distance_m: float,
    ) -> str:
        follow_mode = FollowOwnerController.FORMATION_MODES.get(relation)
        if follow_mode is None:
            raise ValueError(f"unsupported owner formation relation: {relation}")
        now = time.monotonic()
        intent = self._resume_store.peek("follow", now_s=now)
        if intent is not None:
            # Default matches the channel that writes the payload
            # (runtime_channels: `snap.get("mode", "direct")`) — the two
            # disagreed, so a payload without a mode read as behind here and
            # direct there (arbitration OB-5).
            stored = str(intent.payload.get("mode", "direct"))
            if stored == follow_mode:
                # Semantic redispatch after pause: consume stored intent (not cold start).
                with self._command_lock:
                    self._resume_from_store("follow", now_s=now)
                return (
                    "Behind-owner formation resumed"
                    if follow_mode == "behind"
                    else "Owner-follow resumed"
                )
            # Incompatible stored mode — drop and cold-start the requested formation.
            self._resume_store.clear("follow")
        return self._enable_owner_follow(
            follow_mode,
            distance_m=distance_m if follow_mode == "behind" else None,
        )

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
            # Cold start replaces any pending resume; do not leave a stale intent.
            self._resume_store.clear("follow")
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
            # Table says search→follow is PAUSE; ResumeIntent is the sole resume path.
            self.preempt("search", reason="owner_search_queued", targets=("follow",))
        self._emit(
            "search",
            f"Owner lost for {self.search.config.lost_timeout_s:g}s; searching",
            "warning",
        )

    def _start_brain_owner_search(self) -> str:
        """Adapter dispatch: begin or resume the three-state search from the loss point."""

        if self._closed:
            raise RuntimeError("runtime is closed")
        if self.arbiter.emergency_stopped:
            raise RuntimeError("motion is disabled by emergency stop")
        now = time.monotonic()
        with self._command_lock:
            if self.search.paused:
                self._resume_from_store("search", now_s=now)
                return "resuming owner search"
            with self._lock:
                last_seen = self._last_confident_owner
            if last_seen is None:
                raise RuntimeError("no confident owner position to search from")
            self.preempt(
                "search",
                reason="owner_search_started",
                targets=("spatial", "navigation", "follow"),
            )
            self.search.start(
                last_x=last_seen[0],
                last_y=last_seen[1],
                lost_at_s=last_seen[2],
                now=now,
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
        self._finish_owner_search(decision, observation)

    def _finish_owner_search(
        self,
        decision,
        observation: SimObservation | None = None,
    ) -> None:
        """Terminal search state: resume following via stored intent, or hold."""

        self.arbiter.cancel("search")
        self._last_search_state = decision.state
        if decision.outcome == "owner_reacquired":
            self._emit("search", "Owner reacquired; resuming follow", "success")
            try:
                with self._command_lock:
                    self._resume_from_store(
                        "follow",
                        now_s=time.monotonic(),
                        observation=observation,
                    )
            except RuntimeError as error:
                self._emit("search", f"Could not resume follow: {error}", "warning")
            return
        # Give up cleanly: say it out loud, then hold. The failed step is what
        # the executive sees; the robot is left stopped either way.
        self._resume_store.clear("follow")
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

        # Card B4: point the camera detector at the goal noun so it searches for
        # THIS object. Cheap + best-effort; a no-op without an attached ingress.
        self._set_camera_query_from_directive(clean)
        with self._command_lock:
            return self._start_or_resume_navigation_locked(clean)

    def _apply_active_nav_revision(self, navigator: Any) -> None:
        """Stamp ``navigator`` with the executive's committed mission revision.

        P0-C: the navigator's SE2Goal proposals must carry the same
        ``(task_id, plan_revision)`` the executive flushes into the proposer
        sinks, or a corrected-away straggler would keep the default ``("", 0)``
        key and never be rejected. Guarded so navigators from historical bundles
        (no ``set_active_revision``) stay compatible.
        """

        stamp = getattr(navigator, "set_active_revision", None)
        if callable(stamp):
            task_id, plan_revision = self._active_nav_revision
            stamp(task_id, plan_revision)

    def _start_or_resume_navigation_locked(self, clean: str) -> str:
        """Resume a paused mission via ResumeIntent, or cold-start a new one.

        Callers must hold ``_command_lock``. A paused navigator without a valid
        matching intent fails closed — never silently restarts as if resumed.
        """

        now = time.monotonic()
        intent = self._resume_store.peek("navigation", now_s=now)
        navigator = self.dog.navigator
        # P0-C: bind the executive's committed plan_revision to this channel's
        # learned-goal buffers so a correction atomically flushes stale proposals,
        # and stamp the navigator with the mission's active revision (a nav that
        # cold-starts after the plan was accepted picks up the committed key here).
        for _sink in (navigator.proposer_bus, navigator.goal_arbiter):
            if _sink is not None:
                self.task_executive.register_revision_sink(_sink)
        self._apply_active_nav_revision(navigator)
        if navigator.paused:
            if intent is None:
                raise RuntimeError(
                    "resume rejected: navigation intent missing or expired"
                )
            payload_dir = " ".join(str(intent.payload.get("directive", "")).split())
            if payload_dir and payload_dir != clean:
                # Different directive replaces the paused mission intentionally.
                self._resume_store.clear("navigation")
                navigator.stop()
                return self._start_navigation_locked(clean)
            self._resume_from_store("navigation", now_s=now)
            place = clean
            mission = navigator.mission
            if mission is not None and mission.goal is not None:
                place = mission.goal.label or mission.goal.poi_id or clean
            with self._lock:
                self._navigation_directive = clean
            self._emit("navigation", f"Resuming navigation to {place}.", "success")
            return f"Resuming navigation to {place}."
        if intent is not None:
            # Stale stored intent with no paused mission: drop it.
            self._resume_store.clear("navigation")
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
        # A new mission owns the pace: drop any previous directive pace first.
        self._restore_directive_pace()
        self._apply_directive_pace(pace_from_directive(clean))
        with self._lock:
            self._generation.bump("navigation")
            self._behavior_generation += 1
            generation = self._behavior_generation
            observation = self._observation
            # Patience is per-mission: a new directive never inherits the
            # previous one's blocked time or its spent asks.
            self._yield_tracker.reset()
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
            self._restore_directive_pace()
            message = f"Already at {place}."
        elif command.stop and mission.status == "verifying":
            self._request_navigation_terminal_stop()
            message = f"Stopping at {place} and verifying the final position."
        elif command.stop:
            with self._lock:
                self._navigation_directive = None
                self._navigation_detail["enabled"] = False
            self._restore_directive_pace()
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
        """Consume the stored navigation ResumeIntent and restore the mission.

        Fail-closed: missing/expired intent or a required-but-stale observation
        raises ``RuntimeError`` instead of inventing a synthetic resume.
        """

        with self._command_lock:
            self._resume_from_store("navigation", now_s=now_s)

    def _resume_from_store(
        self,
        channel: str,
        *,
        now_s: float | None = None,
        observation: SimObservation | None = None,
    ) -> ResumeIntent:
        """Central resume coordinator: take intent, enforce freshness, resume.

        Callers that mutate motion ownership should hold ``_command_lock``.
        """

        now = time.monotonic() if now_s is None else float(now_s)
        intent = self._resume_store.peek(channel, now_s=now)
        obs = observation
        if obs is None:
            with self._lock:
                obs = self._observation
        observation_fresh: bool | None = None
        if intent is not None and intent.requires_fresh_observation:
            observation_fresh = (
                obs is not None and self._observation_is_fresh(obs, now=now)
            )
        reason = resume_rejection_reason(
            intent,
            now_s=now,
            observation_fresh=observation_fresh,
        )
        if reason is not None:
            raise RuntimeError(f"resume rejected: {reason}")
        assert intent is not None  # narrowed by rejection gate
        taken = self._resume_store.take(channel, now_s=now)
        if taken is None:
            raise RuntimeError("resume rejected: missing_intent")
        channel_obj = self._channels.get(channel)
        if channel_obj is None:
            # Intent already consumed; do not silently succeed.
            raise RuntimeError(f"resume rejected: unknown channel {channel}")
        # Reacquire authority before restoring the paused controller.
        if channel == "navigation":
            self.preempt(
                "navigation",
                reason="navigation_resumed",
                targets=("spatial", "follow"),
            )
        elif channel == "follow":
            self.preempt(
                "follow",
                reason="follow_resumed",
                targets=("spatial", "navigation", "search"),
            )
        elif channel == "search":
            self.preempt(
                "search",
                reason="search_resumed",
                targets=("spatial", "navigation", "follow"),
            )
        channel_obj.resume(taken, now_s=now)
        self._apply_channel_resume_bookkeeping(channel, taken)
        return taken

    def _apply_channel_resume_bookkeeping(
        self,
        channel: str,
        intent: ResumeIntent,
    ) -> None:
        """Update runtime detail/generation after a successful channel resume."""

        with self._lock:
            if channel == "navigation":
                mission = None
                try:
                    mission = self.dog.navigator.mission
                except RuntimeError:
                    mission = None
                state = (
                    mission.status_value()
                    if mission is not None
                    else "running"
                )
                directive = intent.payload.get("directive")
                if self._navigation_directive is None and directive is not None:
                    self._navigation_directive = str(directive)
                self._navigation_detail = NavigationDetail.from_dict(
                    {
                        **self._navigation_detail,
                        "enabled": True,
                        "state": state,
                        "directive": self._navigation_directive
                        or self._navigation_detail.get("directive"),
                        "reason": "navigation_resumed",
                    }
                ).as_dict()
            elif channel == "follow":
                self._generation.bump("follow")
                self._behavior_generation += 1
                self._follow_detail = FollowDetail.from_dict(
                    self.follow.snapshot()
                ).as_dict()
            elif channel == "search":
                self._generation.bump("search")
                self._behavior_generation += 1
                self._search_detail = {
                    **self.search.snapshot(),
                    "reason": "search_resumed",
                }

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

    def pose_review_skills(self) -> list[dict[str, object]]:
        """Describe the bounded catalog actions available to the simulator gallery."""

        skills: list[dict[str, object]] = []
        for skill in self.dog.list_skills():
            if skill.kind not in {"pose", "trajectory"}:
                continue
            duration_s = (
                float(skill.keyframes[-1].t)
                if skill.kind == "trajectory" and skill.keyframes
                else float(skill.duration)
            )
            skills.append(
                {
                    "id": skill.id,
                    "name": skill.name,
                    "kind": skill.kind,
                    "duration_s": duration_s,
                    "speed": skill.speed,
                    "tags": list(skill.tags),
                }
            )
        return skills

    def execute_pose_review(
        self,
        name: str,
        *,
        speed: float | None = None,
    ) -> ExecutionResult:
        """Run one bounded skill for visual inspection in the simulator.

        This operator-only path deliberately refuses every backend except the
        MuJoCo socket backend. It uses the same validated skill executor and
        pose/trajectory dispatch seams as the runtime, including command-lock,
        E-stop, stop, and locomotion-preemption behavior. It does not use the
        social-action cooldown because a commissioning operator must be able
        to replay the same motion immediately.
        """

        if self._closed:
            raise RuntimeError("runtime is closed")
        if not self._synchronous_control_dispatch or self.backend.name != "mujoco":
            raise RuntimeError("pose review is available only in the simulator")
        clean = str(name).strip()
        try:
            skill = self.dog.catalog.get(clean)
        except KeyError as error:
            raise ValueError(f"unknown pose-review skill: {clean!r}") from error
        if skill.kind not in {"pose", "trajectory"}:
            raise ValueError("pose review accepts only bounded pose or trajectory skills")
        result = self.dog.execute(clean) if speed is None else self.dog.execute(clean, speed=speed)
        if not result.accepted:
            raise RuntimeError(result.message)
        return result

    def run_pose_review(self, name: str, *, speed: float | None = None) -> str:
        """Compatibility wrapper returning the pose-review status message."""

        return self.execute_pose_review(name, speed=speed).message

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
                # Temperament follows the profile: the yield policy and its
                # words are part of "who this dog is", not global runtime state.
                self._install_yield_profile(profile.id)
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
            "skip": "Skipped",
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
                self._activity_dispatch_active = True
                try:
                    result = self.dog.execute(record.proposal.name)
                finally:
                    self._activity_dispatch_active = False
                if not result.accepted:
                    raise RuntimeError(result.message)
                duration = result.effective_duration_s
                self._activity_complete_at = now + max(0.1, min(30.15, duration + 0.15))
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
            targets = ("follow", "navigation", "spatial", "search")
            if not self._activity_dispatch_active:
                targets += ("activities",)
            self.preempt(
                "pose",
                reason="pose_started",
                targets=targets,
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
            targets = ("follow", "navigation", "spatial", "search")
            if not self._activity_dispatch_active:
                targets += ("activities",)
            self.preempt(
                "trajectory",
                reason="trajectory_started",
                targets=targets,
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
            "dialogue_state": {
                **self._dialogue_state.snapshot(),
                "influence": dict(self._dialogue_last.get("influence") or {}),
                "pace_factor": self._dialogue_pace_factor,
                "gaze_mode": self._dialogue_gaze_mode,
                "amendment_pending": self._amendment_pending,
                "reaction": dict(self._reaction_last),
            },
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
            "capture endpoint connected; endpointer + STT clocks are wired "
            "(EndpointDecision / SttTranscribe), continuous per-frame ASR "
            "timing is still not exposed"
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
            self._step_dialogue_state(observation)
            self._step_reaction_bridge(observation)

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
                now=now,
            )
            gated_command = command
            self.component_metrics.elapsed("CollisionGate", collision_started)
            self.velocity_smoother.force(command, now=now)
            # Card W6. The last thing before the SE2 hand-off, and after every
            # authority above it has spoken. Stops route to the emergency
            # bypass so no stop decision is ever smoothed.
            stopping = (
                proximity_state == "stopped"
                or self.arbiter.emergency_stopped
                or self._input_health_latched
                # The *intent* decides, not the pre-gate smoother's ramp:
                # asking for zero is a stop even while the ramp is still
                # emitting a non-zero value on its way down.
                or active is None
                or _is_zero_command(active.command)
            )
            command = self._shape_for_actuator(
                command,
                now=now,
                stopping=stopping,
            )
            # P0-A: final-stop monitor immediately before set_target. HARD_STOP
            # emits exact (0,0,0) and resets stateful stages; PROXIMITY_STOP
            # zeroes translation while preserving the gated yaw.
            command = self._finalize_for_actuator(
                command,
                gated_command=gated_command,
                proximity_state=proximity_state,
                active=active,
                now=now,
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

        self._apply_yield_advance_seed(command, stopping=stopping)
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

    def _finalize_for_actuator(
        self,
        shaped: VelocityCommand,
        *,
        gated_command: VelocityCommand,
        proximity_state: str,
        active: MotionIntent | None,
        now: float,
    ) -> VelocityCommand:
        """Apply the core hard-stop monitor at the set_target boundary."""

        if self.arbiter.emergency_stopped or self._input_health_latched:
            severity = InterventionSeverity.HARD_STOP
            candidate = shaped
        elif proximity_state == "stopped":
            severity = InterventionSeverity.PROXIMITY_STOP
            # Preserve gated yaw; shaping emergency zeroes all axes.
            candidate = VelocityCommand(
                vx=shaped.vx,
                vy=shaped.vy,
                vyaw=gated_command.vyaw,
            )
        elif active is None or _is_zero_command(active.command):
            severity = InterventionSeverity.HARD_STOP
            candidate = shaped
        else:
            severity = InterventionSeverity.CLEAR
            candidate = shaped

        stages: tuple[ResetObligation, ...] = ()
        if severity is InterventionSeverity.HARD_STOP:
            stages = (
                ResetObligation(
                    "velocity_smoother",
                    lambda: self.velocity_smoother.reset(now=now),
                ),
                ResetObligation("actuator_shaper", self._reset_motion_shaper),
            )
        decision = finalize_command(
            candidate,
            severity,
            downstream_stages=stages,
        )
        return decision.command

    def _apply_yield_advance_seed(
        self,
        command: VelocityCommand,
        *,
        stopping: bool,
    ) -> None:
        """N11 yield-advance: catch the shaper up after a brief person-stop.

        The shaper is the ramp that actually binds recovery — seeding only the
        navigator's slew was measured at +6.4% because this stage re-ramps from
        zero regardless (arbitration OB-3). Three properties keep it safe:

        1. The seed is **clamped to ``command.vx``** — the value that already
           passed the arbiter, the collision gate, and the smoother — so the
           shaper can never emit above the authorised command, and it still
           approaches that command from below (no overshoot).
        2. It is dropped entirely on any stopping tick; the emergency bypass is
           untouched.
        3. It only ever raises the ramp, never lowers one already higher.

        Applied here and nowhere else: ``RampMemory`` in the navigation
        pipeline is the single source, this is the single reader.
        """

        seed = self.dog.take_pending_ramp_seed()
        if seed is None or stopping or self.arbiter.emergency_stopped:
            return
        target = min(float(seed), float(command.vx))
        if target <= self._last_shaped[0]:
            return
        self._motion_shaper.reset((target, self._last_shaped[1], self._last_shaped[2]))
        self._last_shaped = (target, self._last_shaped[1], self._last_shaped[2])

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
        yield_decision = None
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
            # A localization hold is not a terminal outcome. Measured before
            # this branch existed: `pose_lost_hold` fell into the generic
            # `command.stop` arm, which cleared `_navigation_directive`,
            # published `enabled=False`, restored the directive pace and
            # emitted "Navigation failed for <place>: pose_lost_hold" — so the
            # runtime tore down a mission the navigator had deliberately kept
            # alive to resume when health returned.
            holding = bool(command.stop and command.note == POSE_LOST_HOLD_NOTE)
            if holding:
                self._navigation_detail = {
                    "enabled": True,
                    "state": "waiting",
                    "directive": directive,
                    "goal": place,
                    "reason": command.note,
                }
                self.arbiter.cancel("navigation")
            elif paused:
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
                self._restore_directive_pace()
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
                # Card P-1, the yield policy. A person-gate tick is the ONLY
                # thing routed here (exact `person_stop` segment); the decision
                # is taken under the lock and acted on outside it, exactly like
                # `_announce_pose_health`. Nothing below alters the command —
                # the submit two statements down is the navigator's own,
                # already zeroed by the gate.
                yield_decision = self._yield_tracker.observe(
                    person_blocked=person_blocked_from_note(command.note),
                    now_s=self._yield_clock(),
                )
                try:
                    self.submit_motion(
                        "navigation",
                        VelocityCommand(vx=command.vx, vy=command.vy, vyaw=command.vyaw),
                        ttl=self.loop_period * 3.0,
                    )
                except RuntimeError as error:
                    # A rejection storm (latched E-stop, higher-priority
                    # lease, limit violation) was previously invisible: the
                    # lease lapsed and target_source went None with no
                    # attributable cause. Record it; do not raise — the
                    # arbiter's refusal is authoritative.
                    self._navigation_detail = {
                        **self._navigation_detail,
                        "submit_rejected": str(error)[:160],
                    }
        if holding:
            # Lane B hand-off 2: the navigator stopped the body and
            # walk_with_me recorded it, but nothing ever told the owner. Said
            # once per episode, through the same utterance door the Vocalize
            # skill uses — no second announcement channel.
            self._announce_pose_health(lost=True)
            return
        if yield_decision is not None and yield_decision.speaks:
            self._act_on_yield_decision(yield_decision, place=place)
            if yield_decision.action == YIELD_ACTION_GIVE_UP:
                return
        if not command.stop:
            self._announce_pose_health(lost=False)
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

    def _announce_pose_health(self, *, lost: bool) -> None:
        """Speak a localization transition to the owner, once per transition.

        Edge-triggered on purpose: ``_pose_lost_hold`` fires on **every**
        control tick while MAP health is ``LOST``, and repeating the sentence
        at control rate would be noise, not honesty. The recovery line is only
        reachable from a tick on which the navigator issued a non-stop command,
        which requires health to have returned — so neither sentence can be
        said before the thing it describes is true.
        """

        with self._lock:
            if lost == self._pose_lost_announced:
                return
            self._pose_lost_announced = lost
        self._brain_vocalize(POSE_LOST_UTTERANCE if lost else POSE_REGAINED_UTTERANCE)

    def _act_on_yield_decision(self, decision: YieldDecision, *, place: str) -> None:
        """Speak (and, on give-up, end the mission) for one yield edge.

        Called only from ``_step_navigation`` and only on a tick where
        :class:`YieldTracker` returned ``ask`` or ``give_up`` — the tracker's
        rate limiting is what keeps this off the control-rate path, exactly as
        ``_announce_pose_health``'s edge does.

        The words come from the active personality's ``yield_speech``; this
        method holds none. Every line was checked against the DialogueAct
        truthfulness rules when the config loaded, and the act built here
        carries only the two claims the person gate actually proves.
        """

        with self._lock:
            speech = self._yield_profile.speech
            personality = self._personality
        if decision.action == YIELD_ACTION_GIVE_UP and self._yield_release_and_replan(
            place=place, reason=decision.reason
        ):
            # N20: the navigation lane released the person-blocked commitment and
            # a replan may now find an alternative approach. The mission
            # CONTINUES, so the give-up line is never spoken and the channel is
            # never stopped — saying "I couldn't get there" and then continuing
            # would be exactly the arrival/finality lie the yield speech rules
            # forbid.
            return
        kind = "give_up"
        if decision.action == YIELD_ACTION_ASK:
            kind = "ask" if decision.ask_index <= 1 else "reask"
        text = speech.render(kind, place=place)
        act = yield_dialogue_act(
            turn_id=f"yield-{personality}-{kind}-{max(1, decision.ask_index)}",
            text=text,
            kind=kind,
            speech_style=personality,
        )
        with self._lock:
            self._last_yield_act = act
            self._last_yield_act_audible = False
            if decision.action == YIELD_ACTION_ASK:
                self._yield_asks_spoken += 1
        # U35: the ask is now attempted on the speaker as well as the panel.
        # Whether it was audible is recorded, not assumed — the yield snapshot
        # must not let an inaudible ask read like a spoken one.
        audible = self._brain_vocalize(act.text)
        with self._lock:
            if self._last_yield_act is act:
                self._last_yield_act_audible = audible
        if decision.action != YIELD_ACTION_GIVE_UP:
            return
        # The honest end. The mission is torn down through the normal channel
        # stop so nothing is left half-owned, but with an ATTRIBUTABLE reason:
        # the executive's navigation verifier reads `state` + `reason` straight
        # into the failed step's detail, so the plan record says
        # `blocked_by_person...` instead of the blunt `step_timeout` the 240 s
        # contract ceiling would otherwise produce ~4 minutes later.
        self._stop_navigation_channel(reason=decision.reason, state="failed")
        self._emit(
            "navigation",
            f"Navigation failed for {place}: {decision.reason}",
            "error",
        )

    def _yield_release_and_replan(self, *, place: str, reason: str) -> bool:
        """Offer the navigation lane its single release door on a yield give-up.

        N20: instead of ending the mission the instant yield patience is spent,
        ask the navigator to release the person-blocked commitment and replan.
        The navigator owns the one release authority
        (:meth:`DirectiveNavigator.release_current_candidate`, the same door A*
        and the obstacle gate use); the runtime only asks. This never touches a
        velocity or the person gate — the gated tick that got us here was
        already zeroed by the collision gate and stays zeroed.

        Returns ``True`` when the mission CONTINUES (an alternative may be found,
        so the yield accounting restarts and nothing is spoken), ``False`` when
        no release happened and the honest give-up must proceed.
        """

        # The underlying field, never the ``navigator`` property: the property
        # constructs (and can raise) when none exists, but a yield give-up only
        # reaches here from an active navigation mission, so the navigator is
        # already live. Absence is reported as "no release", never a crash.
        navigator = getattr(self.dog, "_navigator", None)
        release = getattr(navigator, "release_current_candidate", None)
        if not callable(release):
            return False
        try:
            released = bool(release(reason))
        except (RuntimeError, ValueError, AttributeError):
            # A navigation-side failure must not strand the yield path: fall
            # through to the honest give-up rather than crash the mission.
            released = False
        if not released:
            return False
        # The new approach gets its own patience and ask budget; the old
        # episode's accounting does not carry over onto a different pose.
        self._yield_tracker.reset()
        self._emit(
            "navigation",
            f"Someone stayed in my way to {place}; releasing that approach and "
            f"looking for another way there.",
            "info",
        )
        return True

    def _install_perception_chain(self) -> None:
        """Install the configured perception tier as the process-default chain.

        Reads ``perception:`` from the navigation config — the same file
        ``DirectiveNavigator.from_config`` reads — and degrades to T0 (which is
        the pre-stratum-2 behaviour exactly) if anything about that read fails.
        A misconfigured tier must not take the runtime down.
        """

        from parcel_robot.detection_adapter.perception_chain import (
            PerceptionChain,
            use_perception_chain,
        )

        tier = "T0"
        seed = 0
        temperature = 1.0
        try:
            import yaml

            from parcel_robot.paths import resolve_navigation_config

            raw = yaml.safe_load(
                resolve_navigation_config("configs/navigation/default.yaml").read_text(
                    encoding="utf-8"
                )
            )
            section = (raw or {}).get("perception") or {}
            tier = str(section.get("tier", "T0"))
            seed = int(section.get("seed", 0))
            temperature = float(section.get("confidence_temperature", 1.0))
        except (OSError, ValueError, TypeError, KeyError, ImportError):
            tier = "T0"
        try:
            chain = (
                PerceptionChain.from_tier(tier, seed=seed, temperature=temperature)
                if tier.strip().upper() != "T0"
                else PerceptionChain.from_tier("T0", seed=seed)
            )
        except (ValueError, TypeError):
            chain = PerceptionChain.from_tier("T0", seed=seed)
        use_perception_chain(chain)
        self._perception_chain = chain

    def _navigation_extras(self, observation: SimObservation) -> dict[str, object]:
        """Build the sensor-limited navigation view used by runtime and tests."""

        status = self.control_manager.snapshot()
        feedback_age_ms = status.feedback_age_ms
        measured_linear = math.hypot(status.measured.vx, status.measured.vy)
        # Stratum-1 pose seam: one long-lived TruthPoseProvider per runtime, fed
        # this tick's sim truth. Navigation reads it by frame name through
        # ``parcel_robot.pose`` and never touches ``position`` again. Both frames
        # return the same floats the observation already carried, so this is
        # behavior-preserving; a real localizer replaces the provider, not any
        # consumer.
        update_provider_from_sim(self._pose_provider, observation)
        return {
            POSE_PROVIDER_KEY: self._pose_provider,
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
            "semantic_candidates": self._semantic_candidates(observation),
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

    def _camera_ingress_enabled(self) -> bool:
        """True when camera pixel-ingress is opted in (env or config).

        Env ``PARCEL_CAMERA_INGRESS`` wins so a run can flip it without editing
        config; otherwise the ``camera_ingress.enabled`` config knob. Default OFF
        keeps the oracle path byte-identical.
        """

        env = os.environ.get("PARCEL_CAMERA_INGRESS", "").strip().lower()
        if env in {"1", "true", "yes", "on"}:
            return True
        if env in {"0", "false", "no", "off"}:
            return False
        return self._camera_ingress_config_enabled

    def _semantic_candidates(self, observation: SimObservation) -> list[dict[str, Any]]:
        """The one semantic ingress: pixel detections when armed, else the oracle.

        Card B4: when camera ingress is enabled AND attached AND has published a
        detection frame, the reactive view sees candidates FROM PIXELS (the async
        detector proposes; this read never blocks on it). Otherwise — the default,
        and whenever the detector has not produced a frame yet — this returns the
        exact oracle read (``semantic_candidates_from_observation``), so the
        flag-off path is byte-identical to the shipped behavior.
        """

        ingress = self._camera_ingress
        if ingress is not None and self._camera_ingress_enabled():
            try:
                robot = observation.robot
                ingress.set_pose(float(robot.x), float(robot.y), float(robot.yaw))
                pixel = ingress.latest_candidates()
            except Exception as error:  # noqa: BLE001 - never let ingress break a tick
                logger.warning("camera ingress read failed: %s", error)
                pixel = None
            if pixel is not None:
                return pixel
        return semantic_candidates_from_observation(observation)

    def attach_camera_ingress(self, ingress: Any, *, start: bool = True) -> None:
        """Attach an async :class:`CameraIngress` (Card B4) and start its worker.

        The caller owns the model/data + must have set ``MUJOCO_GL=egl`` before the
        first ``import mujoco`` (the runtime never imports MuJoCo). This only stores
        + starts the ingress; ``_semantic_candidates`` consults it once the ingress
        flag is on. Replacing a prior ingress stops the old one first.
        """

        previous = self._camera_ingress
        if previous is not None and previous is not ingress:
            try:
                previous.stop()
            except Exception:  # noqa: BLE001, S110 - teardown best-effort
                pass
        self._camera_ingress = ingress
        if ingress is not None and start:
            ingress.start()

    def detach_camera_ingress(self) -> None:
        ingress = self._camera_ingress
        self._camera_ingress = None
        if ingress is not None:
            try:
                ingress.stop()
            except Exception:  # noqa: BLE001, S110 - teardown best-effort
                pass

    def _set_camera_query_from_directive(self, directive: str) -> None:
        """Tell the attached ingress WHICH object to search for from the directive.

        Cheap + best-effort: the open-vocab detector is queried for the goal noun
        phrase extracted from the raw navigation directive (``go to the lamppost``
        → ``lamppost``). A no-op when no ingress is attached.
        """

        ingress = self._camera_ingress
        if ingress is None:
            return
        phrase = _camera_query_from_directive(directive)
        if phrase:
            ingress.set_query(phrase)

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
        now: float | None = None,
    ) -> tuple[VelocityCommand, str]:
        """Final reactive brake shared by voice, manual, follow, and navigation."""
        decision_now = time.monotonic() if now is None else now
        # Mirror the dispatch tick: refresh sim feedback from the observation
        # before the health join so direct _collision_safe callers share the
        # same pose/scan/feedback contract as _dispatch_active.
        if observation is not None and self._control_state_source is not None:
            state = self._control_state_source.latest()
            if state is None or state.received_at < observation.timestamp:
                self._control_state_source.update_observation(observation)
        health = self._evaluate_dispatch_input_health(observation, now=decision_now)
        self._input_health_latched = bool(health.stop_latched)
        if not health.translation_allowed and math.hypot(command.vx, command.vy) > 1e-6:
            command = VelocityCommand(vyaw=command.vyaw)
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
            now=decision_now,
        )
        if (
            not health.translation_allowed
            and proximity_state == "clear"
            and math.hypot(command.vx, command.vy) <= 1e-6
        ):
            proximity_state = "stopped"
        return self._time_to_collision_gate(command, observation, proximity_state)

    def _evaluate_dispatch_input_health(
        self,
        observation: SimObservation | None,
        *,
        now: float,
    ):
        """Join pose/scan/feedback health before translation-authorizing gates."""

        from parcel_robot.navigation.reactive_safety import scan_evidence_from_observation

        pose: InputEvidence | None = None
        scan: InputEvidence | None = None
        if observation is not None:
            pose = InputEvidence(
                captured_at=observation.timestamp,
                frame_id="odom",
                payload_valid=True,
                origin=InputOrigin.PHYSICAL,
            )
            scan = scan_evidence_from_observation(observation)

        feedback: InputEvidence | None = None
        state = (
            self._control_state_source.latest()
            if self._control_state_source is not None
            else None
        )
        if state is not None:
            feedback = InputEvidence(
                captured_at=state.received_at,
                frame_id="base_link",
                payload_valid=state.fault_reason is FaultReason.NONE,
                origin=InputOrigin.PHYSICAL,
            )

        return evaluate_input_health(
            {
                RequiredInput.POSE: pose,
                RequiredInput.SCAN: scan,
                RequiredInput.CONTROLLER_FEEDBACK: feedback,
            },
            now=now,
        )

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

    def _emit(
        self,
        source: str,
        text: str,
        level: str = "info",
        *,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        """Append one panel event.

        ``detail`` is an optional structured rider for events whose text alone
        would over-claim. The key is absent unless a caller supplies one, so
        the historical event shape is unchanged for every existing call site.
        """

        with self._lock:
            self._event_id += 1
            event: dict[str, object] = {
                "id": self._event_id,
                "role": source,
                "text": text,
                "level": level,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            if detail is not None:
                event["detail"] = dict(detail)
            self._events.append(event)

    def _chat_item(self, role: str, text: str) -> None:
        with self._lock:
            self._chat.append(
                {
                    "role": role,
                    "text": text,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        self._remember_turn(role, text)

    def _remember_turn(self, role: str, content: str) -> None:
        """Card memory-write-path: commit a live turn into tiered memory.

        The single write feed: each committed user/assistant/tool turn flows into
        :class:`TieredMemory` so aged-out turns roll into Tier-2 summaries / Tier-3
        profile and later ``retrieve()`` surfaces them. A no-op when memory is
        disabled (``prompting.memory is None``) — the default, keeping prompts
        byte-identical. Guarded: a memory write must never break a turn.
        """

        memory = self.prompting.memory
        if memory is None:
            return
        if role not in {"user", "assistant", "tool"} or not str(content).strip():
            return
        try:
            memory.append(role, content)
        except Exception as error:  # noqa: BLE001 - memory must never break a turn
            logger.warning("tiered memory append failed: %s", error)

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
        self._dialogue_state.set_phase("listening", engagement=0.7)
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
        if stage.kind:
            # A marked stage is system-initiated speech (``kind="system"`` is
            # the only producer today, hence the assertion below): not a
            # dialogue turn, no query, no trace, nobody waiting on a reply.
            # The test is "is it marked at all" rather than an equality on one
            # label so a future system stream cannot silently fall back into
            # the turn machinery by naming itself something else.
            #
            # Its stages are still marked in the latency ledger so the closed
            # stage vocabulary stays honest (turn 0 has no trace, so that is a
            # no-op today), but it deliberately drives neither the dialogue
            # phase machine nor the duplex per-turn ledger: letting it through
            # would cancel the in-flight turn's filler watchdog and write a
            # ttft for a turn nobody started.
            if stage.kind != SYSTEM_UTTERANCE_KIND:  # pragma: no cover - future stream
                logger.warning("unrecognized voice stage kind %r; not a turn", stage.kind)
            if stage.name == "tts_start":
                # System speech owns the sink from here, so its first sample
                # belongs to nobody's turn: park the attribution rather than
                # crediting the previous dialogue turn with this audio.
                self._audio_output_turn_id = 0
            self.latency.mark(stage.turn_id, stage.name, now=stage.timestamp)
            return
        # Expressive reactions ride the same stage events the latency ledger
        # uses: think visibly from end-of-query until the reply is audible.
        if stage.name == "query_end":
            self._dialogue_state.set_phase(
                "thinking",
                engagement=0.7,
                turn_id=str(stage.turn_id),
            )
            self.expression.reactions.on_turn_pending(time.monotonic())
        elif stage.name in {"audio_first_playback", "tts_first_chunk"}:
            self._dialogue_state.set_phase(
                "speaking",
                engagement=0.55,
                turn_id=str(stage.turn_id),
            )
            self.expression.reactions.on_reply_started(time.monotonic())
        elif stage.name in {"turn_complete", "error"}:
            self._dialogue_state.set_phase("idle", engagement=0.0)
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
            self._mark_acoustic_capture_clocks(stage.turn_id, stage.timestamp)
            return
        if stage.name == "tts_start":
            # The turn that owns the speaker sink from here until the next
            # tts_start. Set before any chunk is enqueued, so the sink worker's
            # first-sample callback always has a turn to attribute to.
            self._audio_output_turn_id = int(stage.turn_id)
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

    def _mark_acoustic_capture_clocks(self, turn_id: int, query_end: float) -> None:
        """Fan the capture + STT clocks of the utterance into this turn's trace.

        The four spans between "the owner stopped talking" and "the turn was
        admitted" are each measured somewhere already — the microphone loop's
        ``last_turn_clocks`` and the recognizer's ``last_metrics`` — but until
        now nothing joined them to a turn id, so the ledger's first observable
        instant was query_end and the whole capture/STT budget was invisible.

        Every clock is admitted only if it is *this* turn's: it must not be one
        already consumed by an earlier turn, and it must precede the query-end
        anchor. A typed turn therefore records nothing, which is correct — it
        had no acoustic capture at all.
        """

        clocks = getattr(self._microphone_loop, "last_turn_clocks", None)
        if isinstance(clocks, dict):
            commit = _finite(clocks.get("semantic_commit_monotonic"))
            speech_end = _finite(clocks.get("speech_end_monotonic"))
            if (
                commit is not None
                and commit != self._acoustic_commit_consumed
                and commit <= query_end
            ):
                self._acoustic_commit_consumed = commit
                if speech_end is not None and speech_end <= commit:
                    self.latency.mark(turn_id, "capture_speech_end", now=speech_end)
                self.latency.mark(turn_id, "semantic_commit", now=commit)

        metrics = getattr(self.speech_stack.recognizer, "last_metrics", None)
        if isinstance(metrics, dict) and metrics.get("status") == "ok":
            request_start = _finite(metrics.get("request_start_monotonic"))
            final = _finite(metrics.get("final_monotonic"))
            if (
                request_start is not None
                and final is not None
                and request_start != self._stt_request_consumed
                and final <= query_end
            ):
                self._stt_request_consumed = request_start
                self.latency.mark(turn_id, "stt_request_start", now=request_start)
                self.latency.mark(turn_id, "stt_final", now=final)

    def _mark_audio_first_sample(self) -> None:
        """Record when the speaker worker actually began writing this reply.

        ``audio_first_playback`` is the enqueue instant; the acoustic rig
        measured 0.54-0.64 s between that and the first sample leaving the
        worker, so an ack claim resting on the enqueue stamp alone is not
        honest. This is the partner clock (still a lower bound on *audible*,
        which needs PipeWire presentation timestamps).
        """

        turn_id = self._audio_output_turn_id
        if turn_id <= 0:
            return
        self.latency.mark(turn_id, "audio_first_sample", now=time.monotonic())

    def write_latency_ledger_row(
        self,
        *,
        path: str | Path | None = None,
        source: str = "runtime",
        run_id: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> Path | None:
        """Append this run's latency snapshot to the persisted ledger.

        Returns the ledger path, or ``None`` when no ledger is configured —
        the CI runner's ratchet needs a persisted series, but an ordinary
        robot session must not litter the tree, so this is opt-in through
        ``PARCEL_LATENCY_LEDGER`` or an explicit path.
        """

        target = resolve_latency_ledger_path(path)
        if target is None:
            return None
        row = latency_ledger_row(
            self.latency_snapshot(), source=source, run_id=run_id, extra=extra
        )
        try:
            return append_latency_ledger_row(row, target)
        except OSError as error:
            logger.warning("latency ledger write failed at %s: %s", target, error)
            return None

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

        self._dialogue_state.set_phase("listening", engagement=0.75)
        bearing = self._owner_bearing_rad()
        self.expression.reactions.on_speech_start(time.monotonic(), bearing)
        if self.duplex.enabled:
            # Attention decision → gaze ACT token (owner look-at).
            if abs(bearing) < 1e-6:
                self.duplex.push_gaze_owner()
            else:
                self.duplex.push_gaze_bearing(bearing)

    def _owner_speech_ended(self) -> None:
        self._dialogue_state.set_phase("thinking", engagement=0.6)
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


def _finite(value: object) -> float | None:
    """A finite float, or ``None`` — a clock we cannot trust is not a clock."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def http_service_health(url: str, timeout: float = 0.5) -> bool:
    """Small reusable health probe for locally isolated model services."""
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        return False
