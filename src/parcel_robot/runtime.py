from __future__ import annotations

import dataclasses
import logging
import math
import os
import random
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from parcel_robot.agent import EMERGENCY_STOP_PHRASES, VoiceAgent
from parcel_robot.attention.stimuli import StimulusKind
from parcel_robot.audio_arming import (
    CODE_ARMED,
    MicArmingDecision,
    capture_identity,
    decide_microphone_arming,
    resolve_allow_monitor_capture,
)
from parcel_robot.audio_io import AudioDeviceStatus, detect_audio_devices
from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.backends.base import (
    DynamicAgentTrack,
    OwnerTrack,  # card OT-2: the overlay rebuilds this track
    SimObservation,
    SimulatorBackend,
)
from parcel_robot.brain.compiler import compile_plan_contracts, materialize_planner_output
from parcel_robot.brain.contracts import (
    BatteryStateSnapshot,
    FrozenDict,
    GoalSpec,
    GoalTarget,
    IntentFrame,
    ObservationSnapshot,
    PlanIR,
    PlanStep,
    SuccessCondition,
)
from parcel_robot.brain.executive import (
    CLOSED_INTENT_PAUSE_REASON,
    CLOSED_INTENT_RESUME_REASON,
    InterruptRequest,
    TaskExecutive,
)
from parcel_robot.brain.observations import (
    build_observation_snapshot,
    task_state_from_executive,
)
from parcel_robot.brain.plan_sketch import PlanSketch

# Card P0-B. The SAME reviewed explicit-affect grammar the legacy voice agent
# uses (``agent._detect_explicit_affect``), imported rather than re-expressed so
# the two lanes cannot drift onto different regexes for "I'm feeling sad".
from parcel_robot.brain.router import explicit_affect_from_text, lane_affect_from_evidence
from parcel_robot.brain.runtime_adapter import (
    PAUSABLE_SKILL_CHANNELS,
    SemanticRuntimeState,
    SemanticTaskRuntimeAdapter,
    admitted_plan_schema,
    admitted_plan_sketch_schema,
)
from parcel_robot.brain.validator import PlanValidationError, PlanValidator, SkillContractRegistry

# Card C-1. Pure-python types only: ``ingress`` defers numpy/mujoco/onnxruntime
# to call time, so importing it here costs nothing and pulls in no render or
# inference dependency on the flag-off path.
from parcel_robot.camera_channel.ingress import (
    DEFAULT_DETECTION_TTL_NS,
    MAX_RETAINED_DETECTIONS,
    CameraDetectionFrame,
)
from parcel_robot.config import ConfigStore
from parcel_robot.context.builder import ContextBuilder
from parcel_robot.context.models import ContextBuildConfig, ContextField
from parcel_robot.context.providers import CallableContextProvider, ClockContextProvider
from parcel_robot.contracts.v1 import DialogueActV1
from parcel_robot.control.base import (
    ObservationSink,
    RobotStateSource,
    as_observation_sink,
    declared_origin,
    is_robot_state_source,
)
from parcel_robot.control.factory import build_backend_control_manager
from parcel_robot.control.manager import ControlManager, ControlNotReadyError
from parcel_robot.control.models import FaultReason
from parcel_robot.core.activities import ActivityContext, ActivityCoordinator, ActivityRecord
from parcel_robot.core.arbiter import CommandArbiter
from parcel_robot.core.channels import BehaviorChannelRegistry
from parcel_robot.core.commands import MotionIntent
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
    SYNTHETIC_ORIGINS,
    EvidenceOrigin,
    HealthAction,
    InputEvidence,
    RequiredInput,
    evaluate_input_health,
    evidence_origin,
    requirements_allowing_sim_fixtures,
    requirements_requiring_physical_inputs,
)
from parcel_robot.core.motion_shaping import MotionShapingConfig
from parcel_robot.core.preemption import PreemptionTable
from parcel_robot.core.resume import (
    GenerationTokens,
    ResumeIntent,
    ResumeStore,
    resume_rejection_reason,
)
from parcel_robot.core.stop_ramp import nominal_stop_step
from parcel_robot.core.velocity_smoother import VelocitySmoother
from parcel_robot.core.yield_policy import (
    YIELD_ACTION_ASK,
    YIELD_ACTION_GIVE_UP,
    PersonalityPolicyConfig,
    YieldDecision,
    YieldTracker,
    load_personality_policy_config,
    person_blocked_from_note,
)
from parcel_robot.duplex.config import DuplexConfig
from parcel_robot.duplex.coordinator import DuplexCoordinator
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
from parcel_robot.memory import FACT_OWNER_STATED, ConversationMemory
from parcel_robot.models import (
    ActionProposal,
    Pose,
    SpatialIntent,
    ToolCall,
    ToolResult,
    VelocityCommand,
)
from parcel_robot.motion import build_motion_router
from parcel_robot.navigation.arrival_semantics import (
    arrival_fact,
    arrival_policy,
    classify_place,
)

# ---- CARD AWARE-1 (scrum/20260823/task_4) — the head-turn proposer and the
# executable half of the R28 axis table. -------------------------------------
from parcel_robot.navigation.awareness_sweep import (
    AwarenessLimits,
    AwarenessSweep,
    awareness_limits_from_config,
    awareness_yaw_permitted,
)

# ---- END CARD AWARE-1 ------------------------------------------------------
from parcel_robot.navigation.dynamic_layer import (
    TimeToCollisionConfig,
    time_to_collision_verdict,
    tracks_from_payload,
)
from parcel_robot.navigation.follow import (
    FollowConfig,
    FollowOwnerController,
    FollowPredictionConfig,
    FollowYieldConfig,
)
from parcel_robot.navigation.goals import (
    PLACE_NO_VOCABULARY,
    PLACE_UNKNOWN,
    PlaceAdmission,
    admit_navigation_place,
    navigation_directive_from_text,
    pace_from_directive,
)
from parcel_robot.navigation.owner_prediction import OwnerMotionPredictor, PredictedPath

# ---- CARD AWARE-1 (scrum/20260823/task_4) — card PROX-1's context seam, which
# this card is the wave's designated wire-in for. -----------------------------
from parcel_robot.navigation.proximity_profiles import (
    ProximityContext,
    ProximityContextOwner,
    load_proximity_profiles,
    proximity_context_for_venue,
)

# ---- END CARD AWARE-1 ------------------------------------------------------
from parcel_robot.navigation.reactive_safety import (
    # ---- CARD OT-2: the published identity seam (DOOR-1 reads it too) ----
    IDENTITY_SOURCE_PIXEL_REID_UNCALIBRATED,
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
from parcel_robot.navigation.spatial import (
    SpatialBehaviorConfig,
    SpatialBehaviorController,
    parse_spatial_intent,
)
from parcel_robot.navigation.velocity_shaping import SCurveVelocityShaper
from parcel_robot.observability import (
    ComponentMetrics,
    LatencyTracker,
    append_latency_ledger_row,
    latency_ledger_row,
    resolve_latency_ledger_path,
)
from parcel_robot.owner_model.notes import known_facts_answer, owner_notes_from_facts
from parcel_robot.owner_model.policy import CONSENT_GRANTED, CONSENT_PENDING
from parcel_robot.patrol.mission import (
    DEFAULT_ROAM_TETHER_M,
    PatrolCommand,
    PatrolLimits,
    PatrolPolicy,
    PatrolSense,
    limits_from_safety,
    sense_from_snapshot,
)
from parcel_robot.perception import NullMapProvider, PerceptionContract
from parcel_robot.pose import (
    POSE_PROVIDER_KEY,
    TruthPoseProvider,
    update_provider_from_sim,
)
from parcel_robot.prompting.loader import PromptLibrary
from parcel_robot.prosody import analyze_wav_chunk
from parcel_robot.providers import (
    LanguageModel,
    SentenceChunkedSynthesizer,
    build_speech_stack,
    strip_emote_tags,
)
from parcel_robot.realtime.browser_sink import BrowserSink, DiscardSink
from parcel_robot.realtime.config import RealtimeConfig, default_realtime_config
from parcel_robot.realtime.cost import realtime_spend_usd
from parcel_robot.realtime.driver import ALARM_REVIVED as DRIVER_ALARM_REVIVED
from parcel_robot.realtime.driver import RealtimeDriver
from parcel_robot.realtime.evidence_log import (
    STREAM_EVENT,
    STREAM_MISSION,
    STREAM_SAFETY,
    SessionEventLog,
)
from parcel_robot.realtime.ingress import (
    KIND_CLOSED_INTENT,
    KIND_EMERGENCY,
    KIND_FOLLOW,
    KIND_HOLD,
    KIND_NONE,
    # Card ROAM-1. The two kinds the ingress appended; the five above are
    # unchanged and this import does not reorder them.
    KIND_ROAM,
    KIND_ROAM_STOP,
    RealtimeTranscriptOutcome,
    matches_spoken_emergency,
)
from parcel_robot.realtime.ingress import scan as scan_realtime_transcript
from parcel_robot.realtime.lane import MAX_TAIL_ITEMS, RealtimeLane, RealtimeLaneError
from parcel_robot.realtime.prompting import (
    MAX_HISTORY_LINES,
    MAX_OWNER_NOTES,
    UNKNOWN_OWNER,
    DeveloperContext,
    InstructionSource,
    history_digest_from_turns,
)
from parcel_robot.realtime.spend_ledger import (
    SpendLedger,
    resolve_spend_ledger_path,
)
from parcel_robot.realtime.tool_broker import (
    NAVIGATE_DIRECTIVE_TEMPLATE,
    TOOL_RECALL_MEMORY,
    TOOL_REMEMBER_FACT,
    RealtimeToolBroker,
    ToolDoors,
)
from parcel_robot.realtime.voice_identity import (
    VOICE_LABEL_KIND,
    SpeakerLabel,
    VoiceArmingDecision,
    VoiceIdentityGate,
    speaker_label,
    unenrolled_label,
)
from parcel_robot.realtime.voice_identity import gate_decision as voice_gate_decision
from parcel_robot.realtime.voice_identity import rejection_fact as voice_rejection_fact
from parcel_robot.realtime.whisperer import (
    CRITICAL_KINDS,
    KIND_ASK_ABOUT,  # card CURIO-1
    KIND_IDLE_REMARK,  # card CURIO-1
    KIND_MISSION_ARRIVED,
    KIND_MISSION_ENDED,
    KIND_NOVEL_OBJECT,  # card CURIO-1
    KIND_PLACE_LEARNED,  # card CURIO-1
    KIND_REFUSAL,
    KIND_SCENE_CHANGE,  # card CURIO-1
    KIND_VOICE_REJECTED,
    OWNER_SOURCE_MOCAP,
    OWNER_SOURCE_PIXELS,
    RULE_BUDGET,  # card CURIO-1
    ChatterScheduler,  # card CURIO-1
    ChatterState,  # card CURIO-1
    FarewellWatcher,  # card CURIO-1
    OwnerEventWatcher,
    OwnerPresence,
    StateDigest,
    StateEvent,
    Whisperer,
    curiosity_event,  # card CURIO-1
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
from parcel_robot.voice.local_plans import (
    SETTLE_POSE_PHRASES,
    sketch_follow,
    sketch_navigate,
    sketch_spatial,
)
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

# ---- CARD HW-1 py310-clean (scrum/20260822/task_35) ----
# ``datetime.UTC`` is 3.11+ and this module is the one whose import failure
# means nothing runs at all: the dog's Orin NX ships JetPack's system CPython
# 3.10 (WAVE3_HW_DESIGN_FABLE.md §5.1, seam S22). CPython defines
# ``datetime.UTC`` as an alias *of this exact object* — ``datetime.UTC is
# timezone.utc`` — so re-exporting the name leaves all nine call sites below
# untouched and every stamp's ``tzinfo`` identity, ``repr`` and ``isoformat``
# byte-for-byte what they were. ``tests/test_hw1_py310_clean.py`` holds the
# floor for the whole package.
UTC = timezone.utc
# ---- END CARD HW-1 py310-clean ----

logger = logging.getLogger(__name__)

#: FIX-A/F3 transcript provenance. A turn's text either came off the capture
#: loop's recognizer or was typed into the panel; the duplex log could not tell
#: them apart, which is exactly what made the 2026-08-11 self-talk storm
#: unreconstructable after the fact.
TRANSCRIPT_ORIGIN_MIC = "mic"
TRANSCRIPT_ORIGIN_PANEL = "panel_text"
#: Card R1. A hosted Realtime session's transcripts are a THIRD provenance:
#: transcribed in the cloud by a separate ASR pass, so approximate, and never
#: routed through ``submit_voice_text`` — see ``submit_realtime_transcript``.
TRANSCRIPT_ORIGIN_REALTIME = "realtime"
TRANSCRIPT_ORIGINS = frozenset(
    {TRANSCRIPT_ORIGIN_MIC, TRANSCRIPT_ORIGIN_PANEL, TRANSCRIPT_ORIGIN_REALTIME}
)
#: Live turns only: entries are consumed when the turn's outcome is recorded.
#: The cap bounds a leak if a turn never reaches ``turn_complete``/``error``.
_TRANSCRIPT_MEMORY_TURNS = 64

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

#: Card R4-lite, task_1 — Defect B. How many mission lifecycle rows the runtime
#: keeps. Small on purpose: this ring answers "what happened to my missions?",
#: and a ring that also tried to hold telemetry would have the same eviction
#: problem the event deque has.
MISSION_LOG_MAX = 20
#: Mission lifecycle kinds. ``blocked`` is an ENTRY row (edge-triggered, one per
#: episode of being blocked), never a per-tick sample.
MISSION_LOG_STARTED = "started"
MISSION_LOG_BLOCKED = "blocked"
MISSION_LOG_ENDED = "ended"
#: What a blocked EPISODE is keyed on. Deliberately NOT the navigation note:
#: the note carries live telemetry (``grid_track err=9.6 goal=0.8 route=2 …``)
#: whose numbers change on every 10 Hz tick, so keying an "edge" on the note
#: makes every tick an edge. That is not a hypothetical — the 2026-08-18 live
#: proof filled the whole ring with 20 blocked rows in two seconds and drove 69
#: model narrations from a single owner turn. The CLASS is what changes when
#: the situation changes.
MISSION_BLOCK_PERSON = "person"
MISSION_BLOCK_OBSTACLE = "obstacle"
#: Minimum spacing between blocked/clear rows, seconds. Even keyed on the class,
#: a pedestrian stream flips person → clear → obstacle → person for real, and the
#: 2026-08-18 live proof still spent 18 of 20 slots on it. The log is the mission
#: HISTORY; "blocked right now" is the panel's live status line, which reads
#: navigation.state directly and is never stale. Suppressed transitions are
#: counted and folded into the next row that is written.
MISSION_BLOCK_MIN_INTERVAL_S = 10.0
#: Hard ceiling on how much of the ring blocked rows may occupy. Whatever else
#: happens, half the ring stays available for starts and terminals — the facts
#: this whole card exists to keep visible. Without it a long enough block still
#: pushes the terminal out, which is the original bug wearing a new hat.
MISSION_LOG_BLOCKED_MAX = MISSION_LOG_MAX // 2

#: Card R11. How often the control loop hands the whisperer a state digest.
#: Conversational cadence, not motion cadence — the fastest rule inside the
#: whisperer is the 8 s block debounce, so a second of resolution is ample and a
#: 10 Hz digest would only fill its decision ring with duplicates.
WHISPERER_TICK_INTERVAL_S = 1.0
# ---- CARD AWARE-1 (scrum/20260823/task_4) ----------------------------------
#: How often the control loop consults the awareness sweep. The sweep's own
#: cadence is its ``idle_period_s`` (tens of seconds); this is only the rate at
#: which the loop ASKS, and it is deliberately the patrol's own sub-rate rather
#: than the full 10 Hz: a look is not a control loop, and re-joining input
#: health ten times a second to decide whether to turn later is work nobody
#: needs. The proposal TTL below is sized off this, not off ``loop_period``.
AWARENESS_TICK_S = 0.25
# ---- END CARD AWARE-1 ------------------------------------------------------
#: Card P2-B. How many affect observations the in-process history keeps. The
#: ledger is the durable record; this ring is the index P2-A's distiller reads
#: through :meth:`RobotRuntime.affect_history`, and it is bounded because a
#: companion that runs for a month must not grow a list for a month.
AFFECT_HISTORY_MAX = 200
#: Card P2-B. How many identity labels the in-process history keeps. The
#: COUNTERS beside it (`_ledger_rows_written` / `_ledger_rows_labelled`) are
#: cumulative and un-evictable, so "every row carried a verdict" stays provable
#: after the ring has rolled.
SPEAKER_LABEL_HISTORY_MAX = 400
#: Card P2-B. The two ledger speakers that are a CONVERSATION. ``system`` rows
#: are the product's own bookkeeping and do not count as company — the same
#: distinction ``mirror_realtime_chat`` already draws for the chat pane, named
#: once here so the two cannot drift.
REALTIME_CONVERSATIONAL_SPEAKERS: frozenset[str] = frozenset({"owner", "robot"})
#: Card R19, mechanism D. The status
#: :meth:`~parcel_robot.core.activities.ActivityCoordinator._expire` stamps on a
#: proposal that sat in the queue past its TTL. Named here rather than in
#: ``core/activities.py`` because that module is not this card's to touch; the
#: string is pinned against the coordinator's own behaviour by test, so a rename
#: there fails loudly instead of silently switching this narration off.
ACTIVITY_STATUS_EXPIRED = "expired"
#: Terminal states that mean the robot got where it was going.
MISSION_ARRIVED_STATES = frozenset({"arrived"})
#: Card R12. The terminal reasons that mean an EMERGENCY STOP ended the mission
#: — the owner's (Space, the spoken phrase ``realtime/ingress.py`` owns, the
#: panel button, ``/api/action emergency_stop``, all of which land on
#: :meth:`RobotRuntime.emergency_stop`; the phrase is deliberately not spelled
#: here, because it has exactly one definition and U33 was three)
#: and the simulator's, adopted by the observe loop. Both reach the navigation
#: channel as a ``preempt("safety", …)`` reason, so this set is matched against
#: the reason the channel was handed, never against a substring of a navigator
#: telemetry note. It exists ONLY to choose the narrated wording: the mission
#: log row and the panel event carry the raw reason either way, and a reason
#: outside this set is narrated with its own words rather than being rounded up
#: to an e-stop.
EMERGENCY_STOP_TERMINAL_REASONS = frozenset({"emergency_stop", "simulator_emergency_stop"})

# --------------------------------------------------------------- card R21
# THE SAFETY LOG RING — why safety events get the mission-log treatment.
#
# 2026-08-20 live_run_1 scoring (a): the auditor could not PROVE which utterance
# latched the emergency stop, because the latch event itself had been EVICTED
# from the 100-slot ``_events`` deque within fourteen seconds. The retained ring
# began at 14:28:33.544; the latch was at 14:28:19.438. Attribution rested on
# four inferences (a window bound, a grammar rule, a silence signature and a
# truncation signature) and STILL could not exclude an accidental Space-key
# latch from the browser panel. That is the exact failure class R4-lite fixed
# for mission terminals — applied here to the events that matter more.
#
#: How many safety lifecycle rows the runtime keeps. Larger than
#: :data:`MISSION_LOG_MAX` because this ring holds three kinds (latch, release,
#: refusal) and because the refusals are the chatty one; the split below is what
#: keeps them from eating the latch that explains them.
SAFETY_LOG_MAX = 24
#: Safety lifecycle kinds.
SAFETY_LOG_LATCHED = "latched"
SAFETY_LOG_RELEASED = "released"
SAFETY_LOG_REJECTED = "rejected"
#: Card R22, work item 2. The realtime pump stopped and nobody asked it to, and
#: the bounded restart that follows. These are SAFETY rows and not "realtime"
#: notes because of what stops with the pump: the spoken e-stop relay, the stall
#: watchdog, the rollover and the idle close. AUDIT_FULL_FABLE §Safety-1 is a
#: finding about SILENCE — "a driver.failures entry is not enough" — and the
#: 100-slot event ring is where a warning goes to be evicted in fourteen
#: seconds. This ring is never evicted by chatter and the panel renders it
#: beside the emergency-stop history.
SAFETY_LOG_PUMP_DIED = "pump_died"
SAFETY_LOG_PUMP_REVIVED = "pump_revived"
#: Hard ceiling on how much of the ring refusal rows may occupy. Whatever else
#: happens, half the ring stays available for latches and releases — the facts
#: this ring exists to keep. Without it, a model that keeps calling motion tools
#: under a latch pushes out the row that says WHY it is latched, which is the
#: original bug wearing a new hat. (`MISSION_LOG_BLOCKED_MAX` is the same idea
#: for the same reason; the two rings are deliberately independent so a future
#: resize of one cannot silently resize the other.)
SAFETY_LOG_REJECTED_MAX = SAFETY_LOG_MAX // 2
#: Minimum spacing between two refusal rows FOR THE SAME DOOR, seconds.
#: Coalesced, never dropped: a repeat inside the window folds a count into the
#: row that is already there. A DIFFERENT door always writes its own row
#: immediately — live_run_1 had ``play_gesture`` and ``navigate_to`` refused in
#: the same millisecond, and an auditor needs to see both.
SAFETY_REJECT_MIN_INTERVAL_S = 10.0

# WHERE A LATCH CAME FROM. A closed vocabulary, not free text: it rides on the
# ring row, on the panel event detail, and (as a class name) on the whisperer
# digest, and every one of those consumers is entitled to switch on it.
#: The owner's spoken words, latched locally by the restricted realtime ingress
#: or by the local microphone path. The row carries the utterance VERBATIM.
SAFETY_SOURCE_VOICE = "voice"
#: Text the owner typed, matched against the exact typed stop grammar.
SAFETY_SOURCE_TYPED = "typed"
#: ``POST /api/action {"action": "emergency_stop"}`` — the panel's red button,
#: the Space bar, or anything else driving that endpoint. The runtime CANNOT
#: separate Space from the button: both post the identical body from the same
#: page, and ``web_panel.py`` (outside card R21's OWNS) forwards only the action
#: string. Splitting them means adding an origin field to that endpoint and is
#: filed owner-gated rather than guessed at here. What live_run_1 actually
#: needed — telling a keyed latch from a spoken one — is what this value gives.
SAFETY_SOURCE_PANEL = "panel"
#: :meth:`RobotRuntime.emergency_stop` called in-process with no origin
#: declared: an embedder, a test, a future subsystem. Honest "nobody said".
SAFETY_SOURCE_API = "api"
#: The observe loop adopting a latch the simulator raised on its own.
SAFETY_SOURCE_SIMULATOR = "simulator"
#: Runtime teardown latches the arbiter on its way out. Recorded because "every
#: latch" means every latch, and a snapshot taken during close should not show
#: an unexplained one.
SAFETY_SOURCE_RUNTIME_CLOSE = "runtime_close"
#: Card R22. The realtime pump reporting on its own liveness. Not a latch origin
#: — no row with this source ever engages or releases anything — but it shares
#: the ring because it answers the same operator question the ring exists for:
#: what is the state of the thing that stops the robot when I say so.
SAFETY_SOURCE_REALTIME_PUMP = "realtime_pump"
SAFETY_SOURCES = frozenset(
    {
        SAFETY_SOURCE_VOICE,
        SAFETY_SOURCE_TYPED,
        SAFETY_SOURCE_PANEL,
        SAFETY_SOURCE_API,
        SAFETY_SOURCE_SIMULATOR,
        SAFETY_SOURCE_RUNTIME_CLOSE,
        SAFETY_SOURCE_REALTIME_PUMP,
    }
)
#: Card R22. How many pump death/revival rows the runtime keeps beside the
#: safety ring. One start's revival ladder is at most ``max_revivals + 1`` rows;
#: this holds several sessions of them.
REALTIME_PUMP_ALARM_MAX = 32
#: Which RULE read the owner's words. Both live in the one emergency branch of
#: ``realtime/ingress.py`` and this card changes neither of them — it only
#: records which one fired, by asking the ingress's own exported predicate.
SAFETY_RULE_SPOKEN = "spoken_phrase"
SAFETY_RULE_TYPED = "typed_phrase"
#: How each source reads in the one sentence a person actually looks at. The
#: panel entry names both controls because the runtime genuinely cannot tell
#: them apart (see :data:`SAFETY_SOURCE_PANEL`) and a row that picked one would
#: be inventing evidence — which is the whole defect this ring exists to end.
#: The message this class raises when a motion door is asked for something
#: while the latch is up. Named ONCE here and raised from one helper, replacing
#: ten copies of the same literal — the U33 lesson applied to a refusal instead
#: of a grammar. It is deliberately NOT shared with ``safety.py`` or
#: ``core/arbiter.py``: those are different layers with their own wording, and
#: importing one into the other would couple two failure vocabularies that are
#: allowed to disagree.
MOTION_DISABLED_BY_LATCH = "motion is disabled by emergency stop"
SAFETY_LATCH_SOURCE_WORDS = {
    SAFETY_SOURCE_VOICE: "voice",
    SAFETY_SOURCE_TYPED: "typed command",
    SAFETY_SOURCE_PANEL: "the panel (Space bar or the emergency-stop button)",
    SAFETY_SOURCE_API: "an in-process call",
    SAFETY_SOURCE_SIMULATOR: "the simulator",
    SAFETY_SOURCE_RUNTIME_CLOSE: "runtime shutdown",
    SAFETY_SOURCE_REALTIME_PUMP: "the hosted-lane pump",
}
#: Card R4-lite, task_1 — Defect C. The proximity slow/clear pair is edge
#: triggered, but the edge itself can flap at the 10 Hz control rate when the
#: robot hovers on the threshold — ~10 events/s, which flushes the 100-slot
#: event deque in ten seconds and takes every other source's history with it.
#: Transitions inside this window are COUNTED and folded into the next line
#: rather than dropped: the information survives, the flood does not.
PROXIMITY_EVENT_MIN_INTERVAL_S = 5.0
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


def _polygon_centre(
    polygon: tuple[tuple[float, float], ...],
) -> tuple[float, float] | None:
    """Vertex mean of a semantic region, used only for nearest-first ORDERING."""

    points = [
        (float(point[0]), float(point[1]))
        for point in polygon or ()
        if len(point) >= 2 and math.isfinite(float(point[0])) and math.isfinite(float(point[1]))
    ]
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


# ===================================================================== card R18
# SCENE ANSWERABILITY — what the robot may say about its surroundings.
#
# live_run_1 (2026-08-20) re-cut F3 from a prompt defect into a MISSING-TOOL
# defect: `state.realtime.broker.tools` held seven tools and not one of them
# could answer "what do you see around you". In the same snapshot the robot was
# holding a 360-ray LiDAR scan, eight `dynamic_agents`, a `nearest_person` at
# 1.73 m and a live `obstacle_distance_m` of 1.4276 — and it had already told
# this owner three times that someone was in the way. Person data reached the
# mission-log narrator and never the conversation lane.
#
# Everything below is deterministic and reads ONLY what perception already
# holds. There is no model here, no clock, and above all no other source: the
# scene block is built from `observation.semantic_regions`,
# `observation.semantic_objects`, `observation.dynamic_agents` and the nearest
# obstacle, and from nothing else. In particular it must NEVER fall back to the
# scene CLASS VOCABULARY the way `_realtime_places` deliberately does — that
# fallback is right for "is this a place I could be asked to walk to" and is a
# fabrication for "what is around me right now".

#: The eight-point body-relative direction table, stated rather than computed
#: from a locale or a compass. Bearings are body-relative and CCW-positive
#: (``_wrap(atan2(dy, dx) - robot_heading)``, mujoco_lidar.py:251/362), so
#: positive is the robot's LEFT.
#:
#: The wording is the robot's own frame ("on my left"), never the owner's: the
#: two disagree whenever they are not facing the same way, and a companion that
#: says "on your left" while meaning its own left has told the owner to look at
#: the wrong thing.
SCENE_BEARING_WORDS: tuple[tuple[float, str], ...] = (
    (22.5, "straight ahead"),
    (67.5, "ahead on my left"),
    (112.5, "on my left"),
    (157.5, "behind me on my left"),
    (180.0, "behind me"),
)

#: How many nearby labelled things the scene block names. Enough to describe a
#: place, few enough to stay one spoken sentence.
SCENE_MAX_REGIONS = 4

#: What the robot's perception actually is, named in the result so the model
#: cannot narrate it as eyesight. owner_session_1's F3 was the model inventing a
#: camera it does not have ("I can't actually see anything around me without a
#: camera feed"); this is the same fact stated the true way round.
SCENE_SENSORS: tuple[str, ...] = ("lidar", "semantic_map", "person_tracks")

#: Said in the result itself, every time. The bench's standing finding is that
#: the model narrates whatever it is given, so the honesty rule has to be IN the
#: thing it reads rather than only in a prompt it may or may not still be
#: carrying twenty turns later.
SCENE_HONESTY_NOTE = (
    "these came from LiDAR ranges and a semantic map, not from a camera: the "
    "robot has no eyes, so say what its SENSORS detect and never describe "
    "colours, faces, text, or how anything looks"
)

#: Card C-3 (research finding F12 / recon GT-14). Under
#: ``perception.semantic_source: learned_map`` the note above is **actively
#: false** — the robot IS looking through a camera, and a note that tells the
#: hosted model to deny a real capability makes it lie in the safe-sounding
#: direction. This is what it says instead. "Detected" and "recognised" are
#: deliberately different words: the detector proposes a label, and the map
#: records how often that proposal was repeated, which is not the same as
#: knowing.
SCENE_HONESTY_NOTE_LEARNED_MAP = (
    "these came from the robot's own camera and the map it has built from what "
    "it detected, not from a list of what exists: say what it has actually "
    "seen, keep the uncertainty that each thing carries, and never describe "
    "colours, faces or text the detector did not report"
)

#: The honest answer when perception has produced nothing at all yet. NOT a
#: blindness claim — the robot is not blind, it has no reading — and the
#: difference is the whole of F3.
SCENE_NO_OBSERVATION = "the robot's perception has no reading yet"

#: Card C-3. What the robot may say about how sure it is, keyed on the number of
#: independent frames the map fused into a place. The bands are the abstention
#: gate's own ``min_evidence_frames`` and half of it, so "I've only seen it
#: once" and "the gate would refuse this" mean the same thing rather than two
#: nearby things.
SCENE_EVIDENCE_PHRASES: tuple[tuple[int, str], ...] = (
    (1, "I've only seen it once"),
    (3, "I've only seen it a couple of times"),
    (7, "I've seen it a few times"),
)


def scene_evidence_phrase(evidence_frames: int) -> str:
    """The hedge a place has earned. Empty once it is well observed.

    An empty string is not "no information" — it is "this place does not need a
    hedge", and the caller renders nothing. A place at one frame gets a sentence
    that says so, because "I think that's a bench — I've only seen it once" is
    the honest form of a one-frame detection and "there is a bench" is not.
    """

    frames = max(0, int(evidence_frames))
    for threshold, phrase in SCENE_EVIDENCE_PHRASES:
        if frames <= threshold:
            return phrase
    return ""


def scene_bearing_words(bearing_rad: float) -> str:
    """Body-relative bearing → the words the robot may use for it.

    Symmetric by construction: the table is written for the left half and the
    right half is its mirror, so "on my left" and "on my right" can never drift
    apart into two separately-maintained lists.
    """

    if not math.isfinite(float(bearing_rad)):
        return ""
    wrapped = math.degrees(float(bearing_rad))
    wrapped = (wrapped + 180.0) % 360.0 - 180.0
    magnitude = abs(wrapped)
    words = SCENE_BEARING_WORDS[-1][1]
    for bound, name in SCENE_BEARING_WORDS:
        if magnitude <= bound:
            words = name
            break
    if wrapped < 0 and "left" in words:
        return words.replace("left", "right")
    return words


#: Card R18. Distances are rounded to ONE decimal before the model ever sees
#: them, and the live proof is why. Handed ``"distance_m": 0.48`` the mini tier
#: said **"zero meters straight ahead"** — a number the owner cannot act on and
#: does not believe, from a reading that was perfectly good. One decimal is also
#: exactly what :func:`scene_fact_lines` renders, so the structured field and
#: the sentence can no longer disagree in the third character.
SCENE_DISTANCE_DECIMALS = 1

#: What the nearest LiDAR return is, said honestly. It is a range with a bearing
#: and no name — the semantic map did not label it — and calling it "an object"
#: would be inventing a class for it.
SCENE_UNLABELLED = "something my LiDAR ranged but the map has no label for"

#: A person, said as a person. Never a description of one: the tracks carry a
#: position and a radius, and nothing about who anybody is.
SCENE_PERSON = "a person"


def _scene_distance(value: float) -> float:
    return round(float(value), SCENE_DISTANCE_DECIMALS)


def _scene_thing(label: str, distance_m: float, bearing_rad: float) -> dict[str, object]:
    return {
        "label": " ".join(str(label).split()),
        "distance_m": _scene_distance(distance_m),
        "direction": scene_bearing_words(bearing_rad),
    }


def _learned_map_scene_rows(learned_map: object, robot: object) -> list[dict[str, object]]:
    """Card C-3 — the map's own places, as scene rows. Never raises.

    A map that cannot answer produces no rows, which ``scene_report`` renders as
    "no reading yet" — the honest answer, and the one that keeps this function
    pure with respect to everything except the object it was handed.
    """

    try:
        rows = learned_map.around_me(  # type: ignore[attr-defined]
            float(robot.x),  # type: ignore[attr-defined]
            float(robot.y),  # type: ignore[attr-defined]
            float(robot.yaw),  # type: ignore[attr-defined]
            radius_m=15.0,
            limit=16,
        )
        entries = {
            str(getattr(entry, "entry_id", "")): entry
            for entry in learned_map.active_entries()  # type: ignore[attr-defined]
        }
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensive
        return []
    out: list[dict[str, object]] = []
    for row in rows:
        entry = entries.get(str(row.get("entry_id", "")))
        if entry is None:
            continue
        out.append(
            {
                "label": str(row.get("label") or ""),
                "x": float(getattr(entry, "surface_x", 0.0)),
                "y": float(getattr(entry, "surface_y", 0.0)),
                "evidence_frames": int(row.get("evidence_frames", 0) or 0),
            }
        )
    return out


def scene_report(
    observation: SimObservation | None,
    *,
    max_regions: int = SCENE_MAX_REGIONS,
    learned_map: object | None = None,
) -> dict[str, object]:
    """A deterministic fact block about the robot's surroundings.

    PURE. Takes the observation, returns JSON-shaped facts; no runtime, no lock,
    no clock, no catalog. That is what lets the whole of card R18's scene half be
    tested against hand-built observations, which is what card item 3 asks for.

    ``things`` names only labels perception is actually holding this instant.
    ``people`` counts only tracks whose ``kind`` is a person. ``clearance_m`` is
    the nearest obstacle the LiDAR returned. Any of them may be absent, and an
    absent fact is stated as absent rather than filled in.
    """

    if observation is None:
        return {
            "sensors": list(SCENE_SENSORS),
            "observed": False,
            "summary": SCENE_NO_OBSERVATION,
            "things": [],
            "people": {"count": 0, "nearest": None},
            "clearance_m": None,
            # Present and null, not absent. Both arms of this function return
            # the SAME KEYS, so a reader that has checked ``observed`` and a
            # reader that has not both get an answer instead of a KeyError.
            "closest": None,
            "note": (
                SCENE_HONESTY_NOTE
                if learned_map is None
                else SCENE_HONESTY_NOTE_LEARNED_MAP
            ),
            "semantic_source": "oracle" if learned_map is None else "learned_map",
        }

    robot = observation.robot
    candidates: list[tuple[float, dict[str, object]]] = []

    def _offer(label: object, x: float, y: float, evidence_frames: int | None = None) -> None:
        clean = " ".join(str(label or "").split())
        if not clean:
            return
        dx, dy = float(x) - robot.x, float(y) - robot.y
        if not (math.isfinite(dx) and math.isfinite(dy)):
            return
        distance = math.hypot(dx, dy)
        bearing = math.atan2(dy, dx) - float(robot.yaw)
        thing = _scene_thing(clean, distance, bearing)
        if evidence_frames is not None:
            # Card C-3. The oracle's things carried no evidence because there
            # was nothing to be uncertain about. A detected thing does, and the
            # hedge travels with the fact rather than being reconstructed by
            # whoever renders it.
            thing["evidence_frames"] = int(evidence_frames)
            hedge = scene_evidence_phrase(int(evidence_frames))
            if hedge:
                thing["uncertainty"] = hedge
        candidates.append((distance, thing))

    if learned_map is not None:
        # Card C-3 item 4 — "what do you see" describes what the dog has
        # actually detected. The oracle's semantic tracks are NOT read here:
        # mixing them in would let the sidecar answer a question about
        # perception, which is the substitution this card exists to end.
        for row in _learned_map_scene_rows(learned_map, robot):
            _offer(row["label"], row["x"], row["y"], row["evidence_frames"])
    else:
        for region in observation.semantic_regions:
            centre = _polygon_centre(region.polygon)
            if centre is not None:
                _offer(region.label, centre[0], centre[1])
        for item in observation.semantic_objects:
            position = item.position
            if len(position) >= 2:
                _offer(item.label, float(position[0]), float(position[1]))

    things: list[dict[str, object]] = []
    seen: set[str] = set()
    for _distance, thing in sorted(candidates, key=lambda row: (row[0], str(row[1]["label"]))):
        key = str(thing["label"]).lower()
        if key in seen:
            # Nearest instance of a label wins; a second "sidewalk" four metres
            # further on is the same answer said twice.
            continue
        seen.add(key)
        things.append(thing)
        if len(things) >= max(1, int(max_regions)):
            break

    people = [track for track in observation.dynamic_agents if _is_person_track(track)]
    nearest_person: dict[str, object] | None = None
    if observation.nearest_person_m is not None:
        nearest_person = _scene_thing(
            SCENE_PERSON,
            observation.nearest_person_m,
            observation.nearest_person_bearing_rad or 0.0,
        )
        nearest_person.pop("label", None)
        if observation.nearest_person_bearing_rad is None:
            # A distance with no bearing is a distance, not a direction.
            nearest_person["direction"] = ""

    clearance = observation.nearest_obstacle_m
    report: dict[str, object] = {
        "sensors": list(SCENE_SENSORS),
        "observed": True,
        "things": things,
        "people": {
            # A person the LiDAR ranged but that produced no track still counts:
            # `nearest_person_m` is itself evidence that somebody is there.
            "count": max(len(people), 1 if nearest_person is not None else 0),
            "nearest": nearest_person,
        },
        "clearance_m": None if clearance is None else _scene_distance(clearance),
        "closest": _scene_closest(observation, things, nearest_person),
        # Card C-3 / F12. "The robot has no eyes" is true on the oracle path and
        # FALSE once the map is built from pixels; a note that denies a real
        # capability instructs the hosted model to lie.
        "note": (
            SCENE_HONESTY_NOTE if learned_map is None else SCENE_HONESTY_NOTE_LEARNED_MAP
        ),
        "semantic_source": "oracle" if learned_map is None else "learned_map",
    }
    report["summary"] = "; ".join(scene_fact_lines(report)) or SCENE_NO_OBSERVATION
    return report


def _scene_closest(
    observation: SimObservation,
    things: Sequence[Mapping[str, object]],
    nearest_person: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Card R18 — the single nearest thing, whatever KIND of thing it is.

    Corpus query 29 is "What's the closest thing to you?", and the live proof is
    why it gets a field of its own rather than being left as an inference over
    three others: handed ``things``, ``people`` and ``clearance_m`` separately,
    the mini tier answered it from the person track and said "the closest thing
    is zero meters behind me" while the LiDAR clearance was 1.1 m. Three numbers
    to choose between is a choice; one field is an answer.

    The three candidates are the three things perception can be nearest to — a
    labelled place, a tracked person, and an unlabelled LiDAR return — and the
    unlabelled one is NAMED as unlabelled rather than given a class it does not
    have.
    """

    candidates: list[tuple[float, dict[str, object]]] = []
    if things:
        first = dict(things[0])
        candidates.append((float(first["distance_m"]), {"what": first["label"], **first}))
    if nearest_person is not None and nearest_person.get("distance_m") is not None:
        candidates.append(
            (float(nearest_person["distance_m"]), {"what": SCENE_PERSON, **dict(nearest_person)})
        )
    if observation.nearest_obstacle_m is not None:
        bearing = observation.nearest_obstacle_bearing_rad
        candidates.append(
            (
                float(observation.nearest_obstacle_m),
                {
                    "what": SCENE_UNLABELLED,
                    "distance_m": _scene_distance(observation.nearest_obstacle_m),
                    "direction": "" if bearing is None else scene_bearing_words(bearing),
                },
            )
        )
    if not candidates:
        return None
    closest = min(candidates, key=lambda row: row[0])[1]
    closest.pop("label", None)
    return closest


def _is_person_track(track: DynamicAgentTrack) -> bool:
    """Only a track the perception stack itself called a person counts as one."""

    return str(getattr(track, "kind", "")).strip().lower() in {"person", "pedestrian", "human"}


def scene_fact_lines(report: Mapping[str, object]) -> tuple[str, ...]:
    """The fact block as short lines — for the DI, and for ``summary``.

    Deliberately the SAME renderer for both, so the sentence the model reads at
    a session boundary and the sentence it reads out of ``get_status`` cannot
    describe the world in two different vocabularies.
    """

    if not report.get("observed"):
        return (SCENE_NO_OBSERVATION,)
    lines: list[str] = []
    for thing in report.get("things") or ():
        if not isinstance(thing, Mapping):
            continue
        where = str(thing.get("direction") or "").strip()
        distance = thing.get("distance_m")
        label = str(thing.get("label") or "").strip()
        if not label or distance is None:
            continue
        lines.append(f"{label} {float(distance):.1f} m {where}".rstrip())
    if not lines:
        # Perception ran and labelled nothing. That is a real answer and it is
        # NOT the same sentence as "no reading yet" — stated here rather than
        # only at the end, so that a scan holding people but no labelled places
        # still says both halves.
        lines.append("nothing labelled within range")
    people = report.get("people")
    if isinstance(people, Mapping):
        count = int(people.get("count") or 0)
        nearest = people.get("nearest")
        if count and isinstance(nearest, Mapping) and nearest.get("distance_m") is not None:
            where = str(nearest.get("direction") or "").strip()
            noun = "person" if count == 1 else "people"
            lines.append(
                f"{count} {noun} tracked, nearest "
                f"{float(nearest['distance_m']):.1f} m {where}".rstrip()
            )
        elif count:
            noun = "person" if count == 1 else "people"
            lines.append(f"{count} {noun} tracked")
        else:
            lines.append("no people tracked")
    closest = report.get("closest")
    if isinstance(closest, Mapping) and closest.get("distance_m") is not None:
        where = str(closest.get("direction") or "").strip()
        lines.append(
            f"closest of all: {closest.get('what')} at "
            f"{float(closest['distance_m']):.1f} m {where}".rstrip()
        )
    clearance = report.get("clearance_m")
    if clearance is not None:
        lines.append(f"nearest obstacle {float(clearance):.1f} m")
    return tuple(lines)


def _place_matches(place: str, labels: tuple[str, ...]) -> bool:
    """Is ``place`` one of ``labels`` (head noun or whole phrase)?

    Card R10: this is the LOCAL EVIDENCE that gates a model relation hint's
    refinement. ``inside`` is only ever admitted for an unknown class when the
    place matches something the map actually holds as a region — otherwise a
    sentence would have manufactured a region goal, which is the LM-Nav
    failure mode ``res_semnav.md`` §1 describes.
    """

    phrase = " ".join(str(place).split()).lower()
    if not phrase:
        return False
    known = {" ".join(str(label).split()).lower() for label in labels}
    if phrase in known:
        return True
    words = phrase.split()
    return bool(words) and words[-1] in known


def _is_zero_command(command: VelocityCommand) -> bool:
    return all(abs(value) <= 1e-9 for value in (command.vx, command.vy, command.vyaw))


def _finite_command_values(command: VelocityCommand) -> bool:
    """Card J-B: a re-gated ramp candidate must be finite before it is trusted."""

    return all(math.isfinite(value) for value in (command.vx, command.vy, command.vyaw))


def _command_translates(command: VelocityCommand) -> bool:
    """Mirror of the reactive gate's own translation test (1e-6, by value)."""

    return math.hypot(command.vx, command.vy) > 1e-6


class _RealtimeLedgerMirror:
    """The lane's ledger, plus the panel chat (card R1.6 §C).

    The lane writes the robot's half of every hosted turn through its
    ``LedgerLike``. In ``mode: text`` the owner is looking at the panel, not
    listening to a speaker, so that half has to appear in the chat pane too or
    the manual test is a conversation with a silent database. This wrapper adds
    exactly that mirror and forwards everything else untouched — the ledger
    write happens first and its return value is the one the lane sees, so a
    failing mirror can never change what was recorded.

    CARD R22 — THE SENTENCE ABOVE IS NOW ENFORCED RATHER THAN INTENDED
    ------------------------------------------------------------------
    "A failing mirror can never change what was recorded" was a claim about
    ORDER, and order alone does not make it true: a ``mirror_realtime_chat``
    that raised propagated out of this method, out of ``lane._write_ledger``'s
    three-type catch (``AttributeError`` and the whole ``sqlite3.Error`` family
    were both outside it), out of ``pump()`` and up the pump thread — losing a
    session's spoken e-stop relay over a chat pane. This object sits directly on
    the AUDIT_FULL_FABLE §Safety-1 path, so both halves are firewalled here at
    the source rather than trusting the caller:

    * the ledger write is guarded, counted, and degrades to row id ``0``
      (the id is a correlation aid — no caller in this tree branches on it);
    * the chat mirror is guarded SEPARATELY, so a panel-display failure cannot
      reach the lane and a ledger failure cannot cost the owner the chat line.
    """

    def __init__(self, runtime: RobotRuntime) -> None:
        self._runtime = runtime
        #: Card R22. Failures at each half, counted for ``/api/state``.
        self.ledger_failures = 0
        self.mirror_failures = 0
        self.last_failure: str | None = None

    def write_realtime_turn(
        self,
        *,
        session_id: str | None,
        speaker: str,
        text: str,
        origin: str,
        provider_item_id: str | None = None,
    ) -> int:
        row = 0
        # Card P2-B, deliverable 1. The ROBOT's half of every hosted turn is
        # written here and not through ``RobotRuntime._write_realtime_ledger``,
        # so "every ledger row carries an identity label" needs the stamp at
        # both doors or it is a claim about half the conversation. Guarded by
        # the same rule as everything else in this class: bookkeeping may never
        # cost a turn.
        try:
            self._runtime._stamp_speaker_label(
                speaker, session_id=session_id, item_id=provider_item_id
            )
            if str(speaker) in REALTIME_CONVERSATIONAL_SPEAKERS:
                self._runtime.note_realtime_turn()
        except Exception:  # noqa: BLE001,S110 - a label may never end a turn
            pass
        try:
            row = self._runtime.agent.memory.write_realtime_turn(
                session_id=session_id,
                speaker=speaker,
                text=text,
                origin=origin,
                provider_item_id=provider_item_id,
            )
        except Exception as error:  # noqa: BLE001 - card R22; see the docstring
            self.ledger_failures += 1
            self.last_failure = f"ledger {type(error).__name__}: {error}"
            self._runtime._emit(
                "realtime",
                f"hosted ledger write failed ({type(error).__name__}: {error}); "
                "the turn continues and the row is lost",
                "warning",
            )
        try:
            self._runtime.mirror_realtime_chat(speaker, text)
        except Exception as error:  # noqa: BLE001 - a chat pane never kills a turn
            self.mirror_failures += 1
            self.last_failure = f"chat mirror {type(error).__name__}: {error}"
        return row

    def snapshot(self) -> dict[str, object]:
        return {
            "ledger_failures": self.ledger_failures,
            "mirror_failures": self.mirror_failures,
            "last_failure": self.last_failure,
        }


class _LockedNavigationChannel(NavigationChannel):
    """Card R24 — the navigator's remaining entry points, taken under the lock.

    Fable's full audit (2026-08-20, §Arch) found ``_navigation_lock`` protecting
    only three of the navigator's mutating entry points — the two
    ``dog.navigate``/``dog.set_nav_pose`` sections and ``dog.stop()`` in
    ``_stop_navigation_channel``. ``navigator.pause()`` and ``navigator.resume()``
    ran lock-free against ``_step_navigation``, which drives the SAME navigator
    object from the control thread under the lock.

    The gap is closed HERE rather than at each call site because there are four
    of them and two are outside this file: ``_pause_channel`` and
    ``_resume_from_store`` call the channel directly, and
    ``BehaviorChannelRegistry.preempt`` calls ``channel.pause(reason)`` from
    inside ``core/channels.py`` on every preemption. Wrapping the four callers
    would have left the fifth one someone adds tomorrow open; wrapping the
    ADAPTER means every path to the navigator's pause/resume is covered by
    construction, and it keeps the whole change inside ``runtime.py`` — no
    signature, no ``core/channels.py`` edit, no behaviour change for any other
    channel.

    ``stop()`` is deliberately NOT overridden. It delegates to
    ``_stop_navigation_channel``, which already takes ``_navigation_lock``
    around its ``dog.stop()`` and takes ``_lock`` on the way there; wrapping it
    here would put ``_lock`` under ``_navigation_lock`` and add a lock-order
    edge for no defect. ``pause``/``resume`` take no other runtime lock, so this
    override adds no edge at all.

    ``_navigation_lock`` is an ``RLock``, so a caller that already holds it
    (none does today) re-enters rather than deadlocks.
    """

    def __init__(self, *args: Any, lock: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._nav_lock = lock

    def pause(self, reason: str) -> ResumeIntent | None:
        # The whole check-then-act, not just ``navigator.pause()``: the base
        # implementation reads ``active()`` and ``navigator.mission`` and builds
        # the ResumeIntent from ``mission.directive``. A ``_step_navigation``
        # tick landing between the read and the pause would have the intent
        # describe a mission the navigator had already moved past.
        with self._nav_lock:
            return super().pause(reason)

    def resume(self, intent: ResumeIntent, *, now_s: float) -> None:
        with self._nav_lock:
            super().resume(intent, now_s=now_s)


#: Card C-1. Public config keys under ``perception:``. Anything else starting
#: with ``camera_ingress`` is REFUSED rather than ignored: a typo'd
#: ``camera_ingress_rate`` that silently kept the default would be an operator
#: who believes they set a rate and a robot that did not.
CAMERA_STREAM_CONFIG_KEYS = frozenset(
    {
        "camera_ingress",
        "camera_ingress_rate_hz",
        "camera_ingress_queue_capacity",
        "camera_ingress_max_detections_per_frame",
        "camera_ingress_queries",
    }
)

#: EV-1 row kind for one published detection frame. Typed by ``kind`` inside
#: the existing ``event`` stream rather than by adding a fifth stream: the
#: evidence schema's four-stream set is pinned by ``verify_event_log`` and read
#: by ``evals/assertions``, and C-1 is not the card that gets to re-version a
#: shared record format. See C1_STATUS.md §"declared deviations avoided".
EVIDENCE_KIND_CAMERA_FRAME = "camera_detection_frame"


@dataclass(frozen=True, slots=True)
class CameraStreamConfig:
    """Validated ``perception.camera_ingress*`` block. Absent == OFF.

    Card C-1, work item 1. Fail-closed by construction: every numeric is
    range-checked at the boundary, booleans are booleans (not 0/1), and the
    query batch must name ``person`` so the PG-1 lease that person-relevant
    inference rides is actually present rather than nominally configured.
    """

    enabled: bool
    rate_hz: float
    queue_capacity: int
    max_detections_per_frame: int
    queries: tuple[str, ...]

    @classmethod
    def from_section(cls, section: Mapping[str, Any] | None) -> CameraStreamConfig | None:
        """Parse the block, or ``None`` when the operator did not ask for it.

        ``None`` and ``enabled=False`` are deliberately different returns from
        the same refusal to run: ``None`` means the block is absent (the
        canonical shipped state, which must leave the wire untouched), while an
        explicit ``camera_ingress: false`` is an operator saying so out loud.
        Both are OFF; both must produce the identical snapshot.
        """

        data = dict(section or {})
        present = {key for key in data if key.startswith("camera_ingress")}
        unknown = present - CAMERA_STREAM_CONFIG_KEYS
        if unknown:
            raise ValueError(
                f"unknown perception camera-ingress keys: {sorted(unknown)}"
            )
        if not present:
            return None
        raw_enabled = data.get("camera_ingress", False)
        if not isinstance(raw_enabled, bool):
            raise TypeError("perception.camera_ingress must be a boolean")
        rate = cls._finite(data.get("camera_ingress_rate_hz", 2.0), "camera_ingress_rate_hz")
        if not 0.0 < rate <= 10.0:
            raise ValueError(
                "perception.camera_ingress_rate_hz must be within (0, 10]; this is "
                "semantic perception, not the control loop"
            )
        capacity = cls._integer(
            data.get("camera_ingress_queue_capacity", 32),
            "camera_ingress_queue_capacity",
            low=1,
            high=4096,
        )
        max_detections = cls._integer(
            data.get("camera_ingress_max_detections_per_frame", 16),
            "camera_ingress_max_detections_per_frame",
            low=1,
            high=MAX_RETAINED_DETECTIONS,
        )
        raw_queries = data.get("camera_ingress_queries", ["person", "lamppost"])
        if not isinstance(raw_queries, list) or not raw_queries:
            raise TypeError("perception.camera_ingress_queries must be a non-empty list")
        queries: list[str] = []
        for item in raw_queries:
            if not isinstance(item, str):
                raise TypeError("perception.camera_ingress_queries entries must be strings")
            phrase = " ".join(item.split()).lower()
            if not 1 <= len(phrase) <= 64:
                raise ValueError("camera-ingress query phrases must be 1..64 characters")
            if phrase not in queries:
                queries.append(phrase)
        if len(queries) > 16:
            raise ValueError("camera-ingress accepts at most 16 unique query phrases")
        if not any("person" in phrase.split() for phrase in queries):
            raise ValueError(
                "camera-ingress queries must include the whole word 'person' so the "
                "PG-1 safety lease is actually taken; a camera that never asks about "
                "people must not claim the person-relevant admission path"
            )
        return cls(
            enabled=bool(raw_enabled),
            rate_hz=rate,
            queue_capacity=capacity,
            max_detections_per_frame=max_detections,
            queries=tuple(queries),
        )

    @staticmethod
    def _finite(value: object, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"perception.{name} must be a number")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"perception.{name} must be finite")
        return result

    @staticmethod
    def _integer(value: object, name: str, *, low: int, high: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"perception.{name} must be an integer")
        if not low <= value <= high:
            raise ValueError(f"perception.{name} must be within [{low}, {high}]")
        return value

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rate_hz": self.rate_hz,
            "queue_capacity": self.queue_capacity,
            "max_detections_per_frame": self.max_detections_per_frame,
            "queries": list(self.queries),
        }


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
            source: object = state_source
        else:
            source = getattr(control_manager, "state_source", None)
        # Card W0-A (P0-1). The retired retention was
        # ``isinstance(BufferedRobotStateSource)``, which discarded a
        # ``UnitreeSportStateSource`` outright — so the input-health feedback
        # reads below saw NOTHING from the physical path — and conflated two
        # different capabilities behind one predicate. Split them:
        #   READ  any read-only RobotStateSource, whatever its class;
        #   WRITE only through the simulator-only ObservationSink seam, which
        #         a physical vendor source does not implement.
        self._control_state_source: RobotStateSource | None = (
            source if is_robot_state_source(source) else None
        )
        self._observation_sink: ObservationSink | None = as_observation_sink(source)
        # Provenance is DECLARED, never inferred from a name (P0-2 / D-1).
        # Feedback the runtime itself synthesizes from a SimObservation is
        # SIMULATION *by construction* — that is a structural fact about this
        # wiring, not a guess about a string. Anything else carries what its
        # source declared, and an undeclared source stays UNKNOWN, which never
        # reaches physical authority.
        self._control_state_origin: EvidenceOrigin = (
            EvidenceOrigin.SIMULATION
            if self._observation_sink is not None
            else declared_origin(source)
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
        # Card J-B. Nominal-stop ramp bookkeeping. All three counters stay 0
        # and the flag stays False while ``motion_shaping.nominal_stop_ramp``
        # is off, which is the default; they exist so the "every ramp candidate
        # was disposed by the gate" property is measurable rather than asserted.
        self._nominal_stop_ramping = False
        self._nominal_stop_ramp_ticks = 0
        self._nominal_stop_regate_ticks = 0
        self._nominal_stop_preempt_ticks = 0
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
        # ---- CARD P1-B state: the camera -> online-map writer ----------
        # All ``None``/zero here; ``_p1b_install_learned_map`` (own region,
        # near ``_attach_configured_camera_ingress``) is the only thing that
        # populates them, and only off-oracle. Declared in __init__ so every
        # accessor is safe on a runtime whose start() never ran.
        self._p1b_learned_map: Any = None
        self._p1b_map_lock = threading.Lock()
        self._p1b_map_settings_cache: dict[str, Any] = {}
        self._p1b_map_store_note = ""
        self._p1b_visit_id = "runtime"
        self._p1b_frames_ingested = 0
        self._p1b_observations = 0
        self._p1b_refused = 0
        self._p1b_errors = 0
        self._p1b_last_error: str | None = None
        self._p1b_map_reloaded = 0
        self._p1b_persisted = 0
        self._p1b_store_closed = False
        # ---- END CARD P1-B state ---------------------------------------
        # Card C-1 — attach the eye. Card P0-A — ONE CAMERA FLAG.
        #
        # These were two switches that REFUSED EACH OTHER at startup: the legacy
        # B4 flag re-points the navigator's `semantic_candidates` at pixels (a
        # grounding-authority change) while `perception.camera_ingress` starts an
        # observation stream that proposes nothing, and enabling both raised
        # rather than resolving, on the reasoning that "which of the two camera
        # switches is authoritative" should not be answered from a snapshot.
        #
        # The prototype answer is that it is one question with one answer:
        # switching the camera on switches the camera on. `perception.
        # camera_ingress` is the key; `camera_ingress.enabled` and
        # PARCEL_CAMERA_INGRESS are ALIASES for the same intent, resolved
        # together in `_camera_ingress_enabled`. Nothing about the authority
        # changed — pixels still only ground the map once a B4 ingress is
        # actually attached — what changed is that the operator no longer has to
        # pick which spelling of "on" they meant.
        #
        # The FLAG-OFF path is untouched by construction: an absent perception
        # block, an absent legacy key and an unset env still resolve to False at
        # every site below, and `_camera_stream_enabled` still requires the C-1
        # block to be present AND true, because the stream reads its rate, queue
        # and query batch out of that block and has nowhere else to get them.
        self._camera_stream_config = CameraStreamConfig.from_section(
            self.store.section("perception")
        )
        self._camera_stream_enabled = bool(
            self._camera_stream_config is not None and self._camera_stream_config.enabled
        )
        # The runtime OWNS the stream; the producer only hands frames to it.
        # Keep-newest with an explicit eviction count: a queue that silently
        # forgets is indistinguishable from a camera that never saw anything.
        capacity = (
            self._camera_stream_config.queue_capacity
            if self._camera_stream_config is not None
            else 32
        )
        self._camera_stream_lock = threading.Lock()
        self._camera_frames: deque[CameraDetectionFrame] = deque(maxlen=capacity)
        self._camera_frames_published = 0
        self._camera_frames_dropped = 0
        self._camera_detections_dropped = 0
        self._camera_detections_total = 0
        self._camera_stream_errors = 0
        self._camera_stream_last_error = ""
        self._camera_stream_started_monotonic: float | None = None
        self._camera_evidence_offered = 0
        self._camera_evidence_refused = 0
        self._camera_attach_note = ""
        self._camera_scene_path = ""
        # Single-overwrite pose mailbox, guarded by the SAME lock as the frame
        # queue. Deliberately one lock and not two: the control loop writes the
        # slot, the camera worker reads it, and neither ever holds it across
        # anything slower than three float assignments — so a second lock would
        # buy no concurrency and would cost R24's roster another ordering
        # constraint. The control loop never calls a producer method.
        self._camera_pose_slot: tuple[float, float, float] | None = None
        self._camera_pose_at_monotonic: float | None = None
        self._camera_poses_offered = 0
        self._camera_poses_consumed = 0
        #: PG-1's admission mechanism, built only when the eye is attached.
        self.perception_contention: Any = None
        safety_config = self.store.section("safety")
        self.obstacle_stop_m = float(safety_config.get("obstacle_stop_m", 0.65))
        self.obstacle_slow_m = float(safety_config.get("obstacle_slow_m", 1.2))
        # Person clearance derives from the one authority, never from a literal:
        # a hardcoded 1.0 here silently reintroduced the retired value whenever
        # the key was absent, while the authority model claimed 1.2.
        self.person_stop_m = float(
            safety_config.get("person_stop_m", DEFAULT_SAFETY_ENVELOPE.person_stop(0.0))
        )
        self.person_slow_m = float(
            safety_config.get(
                "person_slow_m", DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m
            )
        )
        self.telemetry_stale_s = float(safety_config.get("telemetry_stale_s", 0.6))
        if not 0 < self.obstacle_stop_m < self.obstacle_slow_m:
            raise ValueError("safety obstacle distances must satisfy 0 < stop < slow")
        if not 0 < self.person_stop_m < self.person_slow_m:
            raise ValueError("safety person distances must satisfy 0 < stop < slow")
        if not math.isfinite(self.telemetry_stale_s) or self.telemetry_stale_s <= 0:
            raise ValueError("safety telemetry_stale_s must be positive and finite")
        # P0-B sim-fixture commissioning. Under a physical requirements table a
        # SIMULATION/REPLAY pose or controller-feedback sample is a
        # LATCHED_STOP — that is the check that catches stub geometry silently
        # satisfying a physical-sensor requirement. A deployment explicitly
        # commissioned against a simulator accepts those samples ONLY through
        # the labeled fixture path (a synthetic origin + non-empty
        # fixture_label); an unlabeled fixture still latches.
        # ``safety.require_physical_inputs: true`` is the hardware-readiness
        # switch that withdraws the allowance everywhere — and after card W0-A
        # it also withdraws SCAN's, which the simulator default still grants.
        self._require_physical_inputs = bool(
            safety_config.get("require_physical_inputs", False)
        )
        # ``_synchronous_control_dispatch`` is True exactly when the control
        # manager came from config, where ``control.controller`` is required to
        # be "simulator" (hardware needs an explicitly injected manager).
        #
        # Card W0-A replaced ``is_simulated_source(backend.name)`` here. That
        # test read a NAME, and its whitelist meant a backend called "unknown",
        # "physical", or nothing at all was treated as hardware. The structural
        # question is the one that actually matters and cannot be spelled
        # wrong: is the runtime itself synthesizing this feedback from
        # simulator observations? It is exactly when it holds the sink.
        self._sim_fixture_inputs_allowed = not self._require_physical_inputs and (
            self._synchronous_control_dispatch or self._observation_sink is not None
        )
        self._input_health_requirements = (
            requirements_allowing_sim_fixtures()
            if self._sim_fixture_inputs_allowed
            # Board D-2: NOT ``DEFAULT_REQUIRED_INPUTS`` — that table is the
            # simulator default and still admits fixture SCAN geometry.
            else requirements_requiring_physical_inputs()
        )
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
        # ---- CARD AWARE-1 (scrum/20260823/task_4) — the PROX-1 wire-in -----
        #
        # Card PROX-1 (scrum/20260823/task_2) built the context -> profile seam
        # and handed the wire-in to this card, at this one construction site.
        # Two rules decide its shape, and the first is measured rather than
        # assumed:
        #
        # 1. THE COMMISSIONED GATE IS THE BASE, AND AN UNKNOWN VENUE MOVES
        #    NOTHING. PROX-1's `default` rung is derived from the shipped
        #    envelope (1.2 / 2.5), so applying it unconditionally would
        #    OVERWRITE a deliberately retuned deployment rather than preserve
        #    it: `configs/robot.prototype.yaml:197` commissions
        #    `person_stop_m: 0.7` under the owner authorisation recorded there,
        #    and `tests/test_prototype_profile.py:886` pins that the runtime
        #    reports it. Applying `default` over that would leave
        #    `self.person_stop_m` reading 0.7 while the gate enforced 1.2 —
        #    the reported and the enforced distance silently disagreeing, which
        #    is a worse failure than either number on its own. So a profile is
        #    applied at build ONLY when the venue actually names a context;
        #    every other deployment keeps the policy constructed above, byte
        #    for byte.
        # 2. The owner is held either way, so `set_proximity_context` stays
        #    reachable for the later reasoning-model tool, and any switch it
        #    makes is applied to the base policy THIS deployment commissioned.
        self._proximity_context_owner = ProximityContextOwner(
            base_policy=self.reactive_safety_policy,
            profiles=load_proximity_profiles(
                safety_config, base_policy=self.reactive_safety_policy
            ),
            context=ProximityContext.DEFAULT,
        )
        raw_venue = self.store.data.get("venue")
        venue_context = proximity_context_for_venue(
            raw_venue if isinstance(raw_venue, str) else None
        )
        if venue_context is not ProximityContext.DEFAULT:
            self.reactive_safety_policy = (
                self._proximity_context_owner.set_proximity_context(
                    venue_context, source="venue"
                )
            )
        # ---- END CARD AWARE-1 ----------------------------------------------
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
        # Yield-aside (card Y-2), same nested-block treatment as prediction: a
        # typo inside it must not ride through as an unknown top-level follow
        # key. Absent section == code default OFF; no yaml ships the flag.
        raw_yield = follow_config.pop("yield_aside", {})
        if not isinstance(raw_yield, dict):
            raise TypeError("owner_follow.yield_aside must be a mapping")
        follow_yield = FollowYieldConfig.from_mapping(raw_yield)
        self.follow = FollowOwnerController(
            FollowConfig.from_mapping(follow_config),
            safety_policy=self.reactive_safety_policy,
            prediction=follow_prediction,
            yield_aside=follow_yield,
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
        # Card R4-lite, task_1 — Defect B. Mission lifecycle gets its OWN ring.
        # `_events` is 100 slots shared with every chatty source in the runtime,
        # and the live incident is what that costs: a mission ended and the
        # terminal was nowhere to be found. Lifecycle facts are rare — a handful
        # per mission — so 20 slots hold several complete missions no matter how
        # loud proximity, perception or the model get.
        self._mission_log: deque[dict[str, object]] = deque(maxlen=MISSION_LOG_MAX)
        self._mission_log_id = 0
        #: Edge-detection for blocked-entry rows. A mission that sits blocked
        #: behind a person for a minute is ONE entry, not 600.
        self._mission_block_note: str | None = None
        #: Rate limit for blocked/clear rows. Its own monotonic seam rather
        #: than the yield tracker's: these are two unrelated clocks and a test
        #: that drives one must not be able to move the other.
        self._mission_clock: Callable[[], float] = time.monotonic
        self._mission_block_emit_at_s: float | None = None
        self._mission_block_coalesced = 0
        # Card R21. Safety lifecycle gets its own ring for the same reason
        # mission lifecycle did, one class of event more important: live_run_1's
        # latch was evicted from `_events` in fourteen seconds and the run could
        # not be attributed afterwards.
        self._safety_log: deque[dict[str, object]] = deque(maxlen=SAFETY_LOG_MAX)
        self._safety_log_id = 0
        # Card EV-1. The three rings above are WINDOWS — 100, 20 and 24 slots of
        # the most recent facts, in memory, gone at process exit. The eval model
        # needs the STREAM: every one of those rows, uncapped, on disk, beside
        # the R17 audio recordings' layout. `_session_evidence` is that writer;
        # it is armed once, next to the lane, and every `_emit` / `_log_mission`
        # / `_log_safety` offers its row to it. `None` means "not armed", which
        # is what every non-realtime runtime and every test gets by default.
        self._session_evidence: SessionEventLog | None = None
        self._session_evidence_note = ""
        self._session_evidence_id = ""
        # Card R25. The DURABLE month-to-date hosted spend the arming gate
        # refuses on. A sibling of the evidence log in every way that matters:
        # same root, armed in the same place, never load-bearing on the
        # conversation, and `None` for every runtime that has no hosted lane.
        # The difference is lifetime — one file per SESSION there, one file per
        # capture root here, because "this month" spans sessions by
        # construction and the ceiling has to survive a restart.
        self._realtime_spend_ledger: SpendLedger | None = None
        self._realtime_spend_note = ""
        # Card R22, work item 4. Hosted ledger writes (and chat mirrors) that
        # were degraded to a note rather than allowed to end a turn — or, before
        # this card, the pump thread. Counted here as well as on the lane
        # because this runtime has its own write path (`_write_realtime_ledger`)
        # that the lane never sees.
        self._realtime_ledger_failures = 0
        # Card R22, work item 2. Every pump death and revival this process has
        # seen, newest last, kept OUT of the 100-slot event ring so a session
        # that lost its pump can still prove it an hour later. Bounded, because
        # the revival ladder is bounded and a runtime that restarts the driver
        # on every gesture must not grow a list forever.
        self._realtime_pump_alarms: deque[dict[str, object]] = deque(
            maxlen=REALTIME_PUMP_ALARM_MAX
        )
        #: Its own monotonic seam, like `_mission_clock`: a test that drives the
        #: refusal coalescer must not be able to move mission-log timing.
        self._safety_clock: Callable[[], float] = time.monotonic
        #: Wall-clock start of the CURRENT latch, so a status question can say
        #: how long the robot has been stopped rather than only that it is.
        #: `None` whenever the arbiter is not latched.
        self._safety_latched_at_s: float | None = None
        self._safety_latch_source = ""
        #: Proximity chatter throttle (Defect C). Monotonic, like all control
        #: timing here; `None` means "nothing emitted yet this process".
        self._proximity_emit_at_s: float | None = None
        self._proximity_coalesced = 0
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
        #: P0-B: this is a LATCH, not a mirror of the current verdict — once a
        #: ``LATCHED_STOP`` verdict is seen, translation stays forbidden even
        #: after the input recovers, until an explicit operator acknowledgement
        #: (:meth:`clear_input_health_latch` / :meth:`clear_emergency_stop`).
        self._input_health_latched = False
        #: Faults that set the latch, kept for the operator/telemetry surface.
        self._input_health_latch_faults: tuple[str, ...] = ()
        self._control_not_ready_reason: str | None = None
        # ---- CARD ROAM-1 state: the bounded exploration behavior ----------
        # ``_roam_policy is not None`` IS the "am I roaming" flag — one field,
        # not a bool beside an object that can disagree with it. Everything else
        # here is a record for the panel and the status doc.
        # ---- CARD AWARE-1 (scrum/20260823/task_4) — the head-turn state ----
        # Owned entirely by the control thread (`_step_awareness` is its only
        # mutator, and it runs nowhere else), so it takes no runtime lock and
        # adds no edge to R24's lock-order roster.
        # The section name is the string literal, not AWARENESS_CONFIG_KEY:
        # CAP-1's G2 cross-check resolves only literal `store.section(...)`
        # names, and an unresolvable name is an UNCHECKED overlay key. The
        # literal is pinned equal to the constant in test_aware1_head_turn.
        self._awareness_limits: AwarenessLimits = awareness_limits_from_config(
            self.store.section("awareness")
            if "awareness" in self.store.data
            else None
        )
        self._awareness_sweep = AwarenessSweep(self._awareness_limits)
        self._awareness_last_tick_at = 0.0
        self._awareness_refused = 0
        self._awareness_suppressed_reason: str | None = None
        # ---- END CARD AWARE-1 ----------------------------------------------
        self._roam_policy: PatrolPolicy | None = None
        self._roam_started_at = 0.0
        self._roam_last_tick_at = 0.0
        self._roam_budget_s = float(self.DEFAULT_ROAM_BUDGET_S)
        self._roam_reason = "idle"
        self._roam_ticks = 0
        self._roam_refused = 0
        #: The patrol prompt's "social actions can wait until an idle
        #: checkpoint", as a readable predicate. True when not roaming, because
        #: a robot standing still is nothing but a checkpoint.
        self._roam_idle_checkpoint = True
        # ---- CARD ROAM-2 state: the coverage objective ---------------------
        # A RECORD, never an authority. The objective itself is recomputed from
        # the learned map every tick and is handed to the policy as one bearing
        # and one age; what is kept here is only what the panel, the status doc
        # and the harness need to say WHICH place the last leg was aimed at.
        self._roam_coverage: dict[str, object] = {}
        self._roam_coverage_legs = 0
        # ---- END CARD ROAM-2 state ----------------------------------------
        # ---- END CARD ROAM-1 state ----------------------------------------
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
            # Card R20. The typed lane asks the SAME question the hosted
            # ``navigate_to`` tool asks, through the same method, against the
            # same vocabulary — which is what keeps R10's authority parity true
            # while both lanes stop admitting places that cannot exist.
            place_admission=self._place_admission,
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
        # FIX-A/F3. The session log recorded what the ROBOT said and never what
        # it heard, so the transcripts that triggered the 2026-08-11 self-talk
        # storm were unrecoverable (the chat deque aged out and the log
        # rotated). Keep the final transcript and its origin per live turn;
        # they are written into the turn_outcome record under the existing
        # ``duplex.logging`` kill switch and dropped as soon as the turn ends.
        self._turn_transcripts: OrderedDict[int, tuple[str, str]] = OrderedDict()
        self._transcript_lock = threading.Lock()
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
            raw_first_clause = speech_config.get("first_clause_chars")
            synthesizer = SentenceChunkedSynthesizer(
                self.speech_stack.synthesizer,
                first_clause_chars=(
                    None if raw_first_clause is None else int(raw_first_clause)
                ),
            )
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
        # FIX-A/F1. Arming used to be gated on STT reachability alone, which is
        # why a host with a Dummy Output sink and ZERO sources still opened a
        # capture stream — onto the monitor of its own speaker — and answered
        # its own fillers for 669 turns. The runtime's audio probe knew; nobody
        # asked it. Ask it here, fail closed, and say why in one line.
        self._mic_arming: MicArmingDecision = decide_microphone_arming(
            recognizer_available=self.speech_stack.recognizer is not None,
            audio_status=self.audio_status,
            identity=capture_identity(
                audio_status=self.audio_status,
                device_detail=self._input_device_detail,
                device_index=input_index,
            ),
            allow_monitor_capture=resolve_allow_monitor_capture(speech_config),
        )
        if self._mic_arming.armed:
            self._microphone_loop = MicrophoneVoiceLoop(
                recognizer=self.speech_stack.recognizer,
                # The guarded entry point, not the raw session: spoken
                # emergency phrases must latch the E-stop synchronously
                # instead of queueing behind a committed slow action.
                # Wrapped so the transcript's ORIGIN reaches the duplex log
                # (FIX-A/F3): a mic final and a typed command are otherwise
                # indistinguishable once they are inside the voice session.
                submit_text=self._submit_microphone_text,
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
        # FIX-A/F2: one startup summary of what the speech stack ACTUALLY
        # resolved to. A missing --config silently swapped the tuned semantic
        # endpointer for the energy default and nothing said so.
        self._speech_stack_detail = self._report_speech_stack(speech_config)
        # Card R1. The hosted Realtime lane is flag-gated on a NEW optional
        # file, ``configs/realtime.yaml``. With that file absent — the shipped
        # default — the config reads disabled, the lane is never constructed,
        # and this constructor does exactly what it did before. Nothing was
        # added to configs/robot.yaml, which is hash-locked.
        self.realtime_config: RealtimeConfig = default_realtime_config()
        self.realtime_lane: RealtimeLane | None = None
        #: Card R2-C. The SI+DI prompt plane, re-renderable. ``None`` whenever
        #: the lane is not constructed, so it is never a half-built object.
        self.realtime_instructions: InstructionSource | None = None
        #: Card R3 / R1.6. All four stay ``None`` when the lane is not built,
        #: so "flag off" remains "nothing new exists", not "something inert".
        self.realtime_broker: RealtimeToolBroker | None = None
        self.realtime_driver: RealtimeDriver | None = None
        self.realtime_gateway: object | None = None
        #: Card F1-SI. The speaker-identity gate the audio gateway feeds and
        #: ``submit_realtime_transcript`` reads. ``None`` in ``mode: text`` and
        #: on any build that never constructs a gateway — and a gate that exists
        #: with no enrolled profile is still exactly the pre-card behaviour, the
        #: difference being that it SAYS so in the snapshot.
        self.realtime_voice_identity: VoiceIdentityGate | None = None
        self._realtime_panel_token: str | None = None
        #: Card R16. Facts the robot wanted to narrate while the lane was HUNG
        #: UP. Counted at ``_narrate_mission``'s door rather than in the lane,
        #: because that is where the refusal happens: ``_narratable`` turns a
        #: closed lane away before the lane is asked, and it must, or the
        #: whisperer would be what re-opens a session the owner walked away
        #: from. The number is what stops that refusal being invisible; the
        #: facts themselves still reach the mission log and the event ring,
        #: which are upstream of the lane entirely.
        self._narrations_into_closed_lane = 0
        #: Fresh turn ids for router calls made on the broker's behalf. Never
        #: reused: ``_accept_plan`` matches ``PlanIR.source_turn_id`` against
        #: the frame's, so a recycled id would let one admission answer another.
        self._realtime_turn_sequence = 0
        #: Card R10. The pace ``follow_owner`` was last asked for. RECORDED, not
        #: applied — R11's pace_intent is the consumer. Kept here so the value
        #: exists for it, and so ``/api/state`` can show that the robot heard
        #: "run" even though nothing has changed speed yet.
        self._realtime_last_pace = ""
        #: Card R11 — THE CONSUMER R10 was waiting for. The pace the owner asked
        #: for, and when. It is read by the whisperer's pace watcher and by
        #: nothing else; it never reaches a controller, and the follow safety
        #: caps are not a function of it (see ``_whisperer_digest``).
        self._realtime_pace_intent = ""
        self._realtime_pace_intent_at_s: float | None = None
        #: Was the follow controller running on the previous digest? The pace
        #: declaration is cleared on the falling edge of this, never on "not
        #: following" — see ``_whisperer_digest``.
        self._whisperer_was_following = False
        #: Card R11. One counter per block EPISODE, so a clear can prove which
        #: block it closes and the whisperer's clear-only-after-a-forwarded-block
        #: rule has an identity to key on.
        self._mission_block_episode = 0
        #: Card R11. The whisperer runs on the control loop; this throttles it to
        #: a conversational cadence rather than the 10 Hz motion cadence.
        self._whisperer_tick_at_s: float | None = None
        #: The last route the deterministic router returned for a hosted tool
        #: call. Its own record, never ``agent.last_intent_frame``.
        self._realtime_last_route: dict[str, object] | None = None
        #: Card R15 — WHO IS OWED AN ENDING.
        #:
        #: "Done" may only be said from a terminal event, so the terminals have
        #: to reach the model. They must NOT all reach it: ``_speech_emote``
        #: runs ``_brain_gesture`` for every inline ``[emote:...]`` tag the
        #: robot authors in its own sentences, and narrating those endings would
        #: have the dog interrupting itself to announce a nod it never mentioned
        #: starting — a billed response per tag.
        #:
        #: So a terminal is narratable only when the OWNER asked for the
        #: activity through the conversation surface. These two fields are that
        #: mark, set on the hosted doors and claimed once by the terminal.
        #: ``str``/``bool`` rather than an activity id because the coordinator's
        #: id is not returned through ``propose_action`` — the name is what both
        #: ends can see, and a mismatch fails toward silence.
        self._narratable_activity = ""
        self._narratable_orbit = False
        #: Card R19, mechanism D. Coordinator activity ids whose ending has
        #: already been looked at. ``ActivityCoordinator._expire`` retires a
        #: TTL'd proposal straight into ``_recent`` from inside ``submit`` /
        #: ``start_ready`` / ``snapshot`` — it returns nothing and calls nobody,
        #: so an expiry is the ONE terminal R15 could not wire, because it never
        #: passes through ``_step_activities``. live_run_1 q20/q21: the owner
        #: said "Sit down" and "Take a bow", the broker answered ``executed``,
        #: and both proposals died on their 20 s TTL — ``status: expired,
        #: detail: proposal_ttl_elapsed`` — without one word to the owner.
        #: Polled here rather than fixed in the coordinator because
        #: ``core/activities.py`` is not this card's to touch, and polling is
        #: read-only: the set only ever grows by ids the coordinator has already
        #: retired.
        self._seen_activity_endings: set[int] = set()
        #: Card R11. Built UNCONDITIONALLY, and deliberately so: the whisperer is
        #: a pure decision object with no thread, no socket and no cost, and the
        #: alternative — constructing it only inside the ``realtime_config.enabled``
        #: branch — would leave a state where a lane exists and nothing gates what
        #: reaches it. Every robot-initiated fact goes through this object, so a
        #: build in which it can be missing is a build in which the owner's cost
        #: knob has a hole.
        self.realtime_whisperer = Whisperer(
            config=self.realtime_config.whisperer,
            clock=time.monotonic,
        )
        #: Card P2-B. WHEN THE DOG SHOULD NOTICE YOU. Built unconditionally for
        #: the same reason the whisperer above is: it is a pure state machine
        #: with no thread and no cost, and a build where it can be missing is a
        #: build where "did the robot decide not to greet me, or was there
        #: nothing there to decide" has no answer. Its config defaults to
        #: ``enabled: false``, so a tree that does not ask for owner events
        #: produces none — not suppressed ones, none.
        self.realtime_owner_events = OwnerEventWatcher(
            config=self.realtime_config.whisperer.owner_events,
            clock=time.monotonic,
        )
        #: Card P2-B. The rolling affect history P2-A's distiller may read
        #: through :meth:`affect_history`. A bounded deque, not a table: the
        #: LEDGER is the durable record (every affect writes an ``[affect …]``
        #: row through the lane's own writer) and this is the in-process index
        #: over it, so nothing here is the only copy of anything.
        self._affect_history: deque[dict[str, object]] = deque(maxlen=AFFECT_HISTORY_MAX)
        #: Card P2-B. The identity LABEL of every realtime ledger row this
        #: process has written, and the two counters that make "100 % of rows
        #: carry a verdict" a measurement rather than a claim.
        self._speaker_labels: deque[dict[str, object]] = deque(maxlen=SPEAKER_LABEL_HISTORY_MAX)
        self._ledger_rows_written = 0
        self._ledger_rows_labelled = 0
        # ---- CARD OT-2 state: who the robot thinks the owner is -----------
        # Built unconditionally and inert by default: with ``_ot2_owner_tracker``
        # None every method in the OT-2 region returns immediately and the
        # observation is passed through as the SAME OBJECT. Installed by
        # :meth:`install_owner_tracker` once a camera venue has resolved an
        # encoder and a gallery. No lock of its own — everything below is
        # published under ``_lock``, which is why R24's roster is unchanged.
        self._ot2_owner_tracker: Any = None
        self._ot2_owner_fusion: Any = None
        self._ot2_owner_track: Any = None
        self._ot2_owner_track_at: float = 0.0
        #: The enrollment's measured operating point. The overlay subtracts it
        #: from the cosine to get the HEADROOM the reactive gate reads.
        self._ot2_gallery_threshold: float = 0.0
        self._ot2_identity_source: str = ""
        self._ot2_identity_margin: float = 0.0
        self._ot2_identity_state: str = ""
        self._ot2_identity_reason: str = ""
        self._ot2_frames_seen = 0
        self._ot2_owner_claims = 0
        self._ot2_errors = 0
        #: Card OT-2's memory-principal half (DW-3). Counters only; the rule
        #: itself lives in ``owner_model.principal`` and the doors are in the
        #: OT-2 memory region beside P2-A's.
        self._ot2_facts_downgraded = 0
        self._ot2_facts_confirmed = 0
        self._ot2_facts_confirm_refused = 0
        # ---- END CARD OT-2 state ------------------------------------------
        if self.realtime_config.enabled:
            # Card EV-1. Armed BEFORE the lane is built so the session's own
            # construction events are in the record, and only when there IS a
            # session to record: a runtime with no hosted lane has no session
            # boundary to rotate on, and every unit test would otherwise leave a
            # folder behind. `_arm_session_evidence` never raises.
            self._arm_session_evidence()
            # Card R25. The owner's monthly ceiling, made real. Armed before
            # the lane for the same reason the evidence log is: the lane takes
            # it as a constructor argument, and the ARMING decision consults it
            # on the very first `open_session`. Never raises.
            self._arm_spend_ledger()
            # SI is the personality + companion guardrails, versioned and
            # digest-pinned in ``realtime/prompting.py``. DI is a deterministic
            # render of injected runtime flags. ``current().text`` is the
            # session-OPEN render; the lane re-sends ``self.instructions`` at
            # every rollover and reconnect, so a driver that calls
            # ``realtime_instructions.refresh(lane)`` before ``lane.tick()``
            # gets fresh DI at each session boundary and never mid-session
            # (a mid-session rewrite would bust the provider's prompt cache).
            self.realtime_instructions = InstructionSource(
                # Owner directive 2026-08-18: personality is authorable as plain
                # prose. ``persona_text`` (from configs/realtime.yaml) replaces
                # the profile block verbatim; ``None`` — the shipped default —
                # takes the preset-profile path byte-for-byte, which is why the
                # SI_DIGESTS pins still hold. ``si_profile`` overrides which
                # preset is used, and falls back to the runtime's personality.
                persona_text=self.realtime_config.persona_text,
                profile_id=self.realtime_config.si_profile or self._personality,
                context=DeveloperContext(
                    # Injected, not read inside the renderer: a corpus fixture
                    # replays byte-identically only if the clock is a seam.
                    clock=datetime.now,
                    # No location provider yet. Nothing in this runtime names a
                    # ROOM: ``_location_context`` is map coordinates and
                    # ``_scene_context`` is visible semantic regions, and
                    # neither is a place a companion can talk about. DI reads
                    # "unknown" rather than inventing one; wiring a real place
                    # source is an R3 handoff.
                    owner_name=str(agent_config.get("owner_name", UNKNOWN_OWNER)),
                    # Card P2-A. The ``owner_notes`` block has been rendered by
                    # the prompt plane since it was built and NEVER provided —
                    # the 25 sealed corpus fixtures are the only things that
                    # ever filled it. This is the provider, and it is the whole
                    # reason the owner-fact table exists: what the robot has
                    # been told it may keep about its owner, in the model's
                    # instruction, at every session open. Consented rows only,
                    # and an empty store renders nothing at all — which is what
                    # keeps the pinned DI digest and those fixtures valid.
                    owner_notes=self._realtime_owner_notes,
                    history=lambda: history_digest_from_turns(
                        self.agent.memory.realtime_turns(limit=MAX_HISTORY_LINES * 2)
                    ),
                    # Card R18, work item 1(b). The scene block the DI carries
                    # at every session boundary, from the same
                    # ``scene_report`` the ``get_status`` answer is built
                    # from. It is a SNAPSHOT and the DI header says so: the
                    # tool is what answers "right now".
                    scene=self._realtime_scene_lines,
                ),
                library=self.prompt_library,
            )
            # Card R3. The broker replaces R1's refuse-every-call stub. It is
            # built BEFORE the lane so the lane can declare its tool surface in
            # the same breath as its instructions, and its two read-only tools
            # join the supervisor's exact-name allowlist — the documented
            # mechanism for read-only conversation tools (safety.py:40-42),
            # which is why ``recall_memory`` validates instead of falling into
            # the fail-closed "Tool is not allowed" arm.
            # Card P2-A joins ``remember_fact`` to the same exact-name
            # allowlist, for the same documented reason (safety.py:40-42): it
            # is a read/write of a TEXT STORE and touches no door that can move
            # the body, so it must validate rather than fall into the
            # fail-closed "Tool is not allowed" arm. The supervisor still sees
            # every call.
            self.agent.safety.information_tools = frozenset(
                self.agent.safety.information_tools | {TOOL_RECALL_MEMORY, TOOL_REMEMBER_FACT}
            )
            self.realtime_broker = RealtimeToolBroker(
                ToolDoors(
                    # Card R21. A pass-through that WATCHES: the validator still
                    # decides, and a refusal taken while the latch is up is
                    # written to the safety ring on its way past. This is the
                    # exact seam live_run_1 measured four silent refusals at.
                    validate=self._realtime_validate,
                    status=self._realtime_status_digest,
                    recall=self._realtime_recall,
                    # Card R15. The SAME door, with the terminal marked as one
                    # the owner is owed an ending for. ``_brain_gesture`` is
                    # still what runs; the wrapper adds nothing to the
                    # admission chain and cannot refuse anything.
                    # Card R21 wraps each MOTION door — and only the motion
                    # doors — so that a refusal taken under a latch is recorded
                    # whichever layer refused it. ``get_status``/``recall_memory``
                    # are deliberately NOT wrapped: they are the two tools that
                    # must keep answering while the robot is stopped.
                    # Card F1-SI wraps the SAME five motion doors again, one
                    # layer further out, with the speaker-identity gate. This is
                    # the half of the card that actually closes F1: the local
                    # ingress reads "go to the bench" as chit-chat (it is not a
                    # closed intent), so the sentence that moved the robot for a
                    # television moved it through ``navigate_to`` — the model's
                    # tool call, not the latch path. Gating only the ingress
                    # would have produced a card that refused "follow me" from a
                    # stranger and walked the dog on "go to the bench".
                    #
                    # ``get_status`` / ``recall_memory`` are NOT wrapped, for
                    # exactly R21's reason one line down: answering a question is
                    # not arming, and a robot that stops talking to visitors is a
                    # different and worse product.
                    gesture=self._gate_by_voice(
                        "play_gesture",
                        self._watch_under_latch("tool play_gesture", self._realtime_gesture),
                    ),
                    pose=self._gate_by_voice(
                        "set_pose",
                        self._watch_under_latch("tool set_pose", self._realtime_pose),
                    ),
                    navigate=self._gate_by_voice(
                        "navigate_to",
                        self._watch_under_latch("tool navigate_to", self._realtime_navigate),
                    ),
                    # Card R10 — the two doors that close the tool-surface hole,
                    # plus the place vocabulary the junk-place refusal names.
                    places=self._realtime_places,
                    # ---- CARD ASK-1 (task_18) --------------------------------
                    # NOT wrapped in ``_gate_by_voice`` or ``_watch_under_latch``
                    # and that is deliberate, not an omission. Those two wrappers
                    # exist for doors that COMMIT THE BODY — an unverified voice
                    # must not be able to send the dog off, and a motion refused
                    # under a latch must be written to the safety ring. This door
                    # starts nothing, claims nothing and can refuse nothing: it
                    # reads the map and returns a question. Gating it would mean
                    # the robot went silent about its own uncertainty to a
                    # stranger, or while stopped — and a stopped robot that will
                    # not say what it is unsure of is a worse robot, not a safer
                    # one. The MOTION that a confirmed answer eventually starts
                    # still goes through ``navigate`` below, wrapped in both.
                    ask_place=self._realtime_ask_place,
                    # ---- END CARD ASK-1 (task_18) ----------------------------
                    orbit=self._gate_by_voice(
                        "circle_owner",
                        self._watch_under_latch("tool circle_owner", self._realtime_orbit),
                    ),
                    follow=self._gate_by_voice(
                        "follow_owner",
                        self._watch_under_latch("tool follow_owner", self._realtime_follow),
                    ),
                    # Card ROAM-1. Wrapped in BOTH wrappers for the same reason
                    # every other motion door is: an unverified voice must not
                    # be able to send the dog off on its own, and a roam refused
                    # under a latch must be written down. Roam is the longest
                    # motion on the surface, so it is the one where "who asked
                    # for this" matters most minutes later.
                    roam=self._gate_by_voice(
                        "roam",
                        self._watch_under_latch("tool roam", self._realtime_roam),
                    ),
                    gesture_names=lambda: tuple(self._emote_catalog),
                    pose_names=self._realtime_pose_names,
                    on_dispatch=self._realtime_thinking_pose,
                    note=lambda message: self._emit("realtime", message, "info"),
                    # Card P2-A. The owner-model doors. NOT wrapped in
                    # ``_gate_by_voice`` or ``_watch_under_latch``, for R21's
                    # own reason one screen up: these touch no door that can
                    # move the body, and a robot that stops being able to say
                    # what it knows — or to be told to forget something — while
                    # it is stopped is a different and worse product. The
                    # gating that matters here is the privacy policy, and it
                    # runs inside the broker before any of these is called.
                    # ---- CARD OT-2 seam 3 of 3: WHO may write a fact ----
                    # The write door is P2-A's, wrapped: the wrapper applies
                    # the memory principal at the last point before the store
                    # and hands the downgrade back in the result. ``confirm``
                    # is the new fourth door — the product caller
                    # ``memory.set_owner_fact_consent`` never had.
                    remember_fact=self._ot2_remember_fact,
                    confirm_fact=self._ot2_confirm_fact,
                    # ---- END CARD OT-2 seam 3 --------------------------
                    forget_fact=self._realtime_forget_fact,
                    known_facts=self._realtime_known_facts,
                ),
                # Card P0-B. Two validated keys the loader has already checked:
                # the proactive-motion allowlist (empty by default, and it can
                # only ever hold ``play_gesture``/``set_pose``) and the
                # ``navigate_to`` unknown-place mode (``refuse`` by default,
                # which is the pre-card behaviour). Passed at construction so
                # the broker's gates are decided once, from the owner's file,
                # rather than re-read per call.
                proactive_motion_tools=self.realtime_config.proactive_motion_tools,
                unknown_place=self.realtime_config.unknown_place,
            )
            self.realtime_lane = RealtimeLane(
                config=self.realtime_config,
                instructions=self.realtime_instructions.current().text,
                sink=self._build_realtime_sink(),
                # NEVER submit_voice_text: that is the local agent's front door.
                ingress=self.submit_realtime_transcript,
                ledger=_RealtimeLedgerMirror(self),
                # Card P2-A, work item 4. WAS ``realtime_turns(limit=20)``:
                # twenty rows, hosted lane only. The owner's 2,618 legacy
                # panel/voice rows — everything they ever typed or said to the
                # local agent — had never once been replayed into a hosted
                # session, because ``realtime_turns`` filters ``speaker IS NOT
                # NULL`` (which is right for its own job and wrong for this
                # one). ``ledger_tail`` is both lanes, oldest last; the LANE
                # dedupes and applies ``MAX_TAIL_ITEMS``, because the cap
                # belongs at the last point before the wire and not in the row
                # source. The read is bounded here as well so a store that grew
                # overnight is never fully materialised in memory.
                memory_tail=lambda: self.agent.memory.ledger_tail(limit=MAX_TAIL_ITEMS * 4),
                # Card R7. R1.5's sink-ownership law is "two speakers must not
                # share one ordered queue", and this callable is how the lane is
                # told the local half is busy. It used to report the local
                # duplex session's state unconditionally — which is only the
                # right answer when the lane and the duplex session are writing
                # to the SAME SpeakerSink. They never are here:
                # ``_build_realtime_sink`` returns a DiscardSink or a BrowserSink
                # and deliberately never a local SpeakerSink, so the lane's audio
                # goes to /dev/null or to the browser while local speech goes to
                # PortAudio. Reporting "busy" for those was a false positive that
                # raised SinkOwnershipError out of ``_on_audio`` into ``pump()``
                # — R4L open risk 6, the three `pump failed: … DuplexVoiceSession
                # output is live` lines in live session 1, in TEXT mode where
                # there is no contention at all. In audio mode the same false
                # positive would drop hosted speech mid-utterance whenever the
                # robot happened to be talking locally. The law is unchanged and
                # still asserted: this now says "busy" exactly when the two
                # really do share a queue.
                duplex_output_active=self._realtime_shares_local_speaker,
                transcript_origin=TRANSCRIPT_ORIGIN_REALTIME,
                tool_handler=self.realtime_broker,
                transport_factory=self._realtime_transport_factory(),
                # Card R16. The lane hangs itself up when nobody is talking to
                # it; this is how the browser's microphone button learns about
                # it, because the lane is not allowed to know what a microphone
                # is. See ``_realtime_idle_closed``.
                on_idle_close=self._realtime_idle_closed,
                # Card R25, audit §Ops-2. THE NUMBER THE ARMING GATE NEVER HAD.
                # `decide_realtime_arming` has compared spend against
                # `monthly_budget_usd` since R1; `lane.arm` never passed one, so
                # the owner's documented ceiling compared 0.0 against 25.0 every
                # time. This is the durable, restart-surviving figure it now
                # compares instead.
                spend_ledger=self._realtime_spend_ledger,
                # Card R22, work item 5 — EV-1 open risk §10.3, closed. The
                # retained ASR/boundary frames go to the EVIDENCE LOG's sink,
                # never through `_note`/`_emit`: 44 deltas a session through the
                # 100-slot ring is the exact flood EV-1 exists to relieve.
                retention_sink=self._retain_realtime_frame,
            )
            # The crank. Nothing in R1/R1.5/R2 ever called ``pump()``/``tick()``;
            # without this the session hears nothing and never rolls over.
            self.realtime_driver = RealtimeDriver(
                self.realtime_lane,
                instructions=self.realtime_instructions,
                on_event=lambda message: self._emit("realtime", message, "info"),
                # Card R22, work item 2. A pump that dies must be LOUD, and the
                # event ring is not loud enough — it evicts. This is the wire to
                # the safety ring and the session evidence log.
                on_alarm=self._realtime_pump_alarm,
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
            # Card R24 — see ``_LockedNavigationChannel``. Same adapter, with
            # pause/resume taken under ``_navigation_lock`` so every entry to
            # the navigator's mutating surface holds the lock the control
            # thread's ``_step_navigation`` holds.
            _LockedNavigationChannel(
                LazyNavigator(self),
                is_enabled=lambda: self._navigation_directive is not None,
                stop_fn=self._stop_navigation_channel,
                detail_fn=lambda: dict(self._navigation_detail),
                lock=self._navigation_lock,
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
        self, reason: str = "navigation_disabled", *, state: str = "idle"
    ) -> None:
        """Channel-level navigation stop (no re-entrant preempt).

        ``reason``/``state`` exist so a caller that knows *why* it is stopping
        can say so in one write. Without them the yield policy's honest give-up
        would have to stop first and overwrite the detail afterwards, and the
        executive polls between those two writes — it would read
        ``navigation_disabled`` and attribute the failure to nothing.

        Card R12: ``reason`` is positional-or-keyword so this method IS the
        ``BehaviorChannel.stop(reason)`` shape and ``NavigationChannel`` can
        hand its reason straight through. Every existing caller passes it by
        keyword and is unaffected. ``navigation_disabled`` survives as the
        default for the callers that genuinely do not know why (and as the
        floor for a caller that passes an empty one) — it is an honest "no
        reason given", which is a different claim from a wrong reason.
        """

        reason = reason or "navigation_disabled"
        with self._lock:
            self._generation.bump("navigation")
            self._behavior_generation += 1
            was_enabled = self._navigation_directive is not None
            self._navigation_directive = None
            self._yield_tracker.reset()
            goal = ""
            if was_enabled:
                goal = str(self._navigation_detail.get("goal", ""))
                self._navigation_detail = NavigationDetail.from_dict(
                    {
                        **self._navigation_detail,
                        "enabled": False,
                        "state": state,
                        "reason": reason,
                    }
                ).as_dict()
        if was_enabled:
            # Card R4-lite, task_1 — Defect B, root cause. This is the ONE place
            # every non-arrival mission terminal passes through: preempt, the
            # executive's task teardown, a behavior switch, an owner stop, the
            # yield policy's honest give-up. It wrote `enabled: False` into the
            # detail and told NOBODY — which is exactly how the owner's mission
            # ended with `goal: sidewalk, reason: navigation_disabled` and not a
            # single event to explain it.
            self._log_mission_terminal(state=state, goal=goal, reason=reason)
            self._emit(
                "navigation",
                (
                    f"Mission to {goal} ended ({state}): {reason}"
                    if goal
                    else f"Navigation stopped ({state}): {reason}"
                ),
                "info" if state in MISSION_ARRIVED_STATES else "warning",
            )
            self._narrate_mission_terminal(state=state, goal=goal, reason=reason)
        self.arbiter.cancel("navigation")
        self._restore_directive_pace()
        if was_enabled:
            # CARD R24 — THE ORDER EDGE THE AUDIT'S SCAN COULD NOT SEE.
            # ================================================================
            # This was `with self._navigation_lock: self.dog.stop()`, and it is
            # the back-edge that made the runtime lock order CYCLIC rather than
            # the DAG AUDIT_FULL_FABLE's healthy list states. `dog.stop()` is
            # not a leaf: `skills/api.py::stop` → `skills/executor.py::stop` →
            # `motion.py::stop` → the `on_stop` hook, which `__init__` wires to
            # `self.stop_motion` (runtime.py, `on_stop=self.stop_motion`) —
            # and `stop_motion` takes `_command_lock`. So this site stated
            # `_navigation_lock → _command_lock` while `_start_navigation_locked`
            # and `_step_navigation` both state `_command_lock →
            # _navigation_lock`. A static scan that only follows `self.foo()`
            # cannot see it, because the inversion travels out through the dog,
            # the executor and the motion controller and comes back in through
            # a callback.
            #
            # Reproduced, not theorised (R24_STATUS.md §4.1): thread A in
            # `start_navigation` holding `_command_lock` and waiting on
            # `_navigation_lock`, thread B in `stop_navigation` holding
            # `_navigation_lock` and waiting on `_command_lock` — both blocked
            # permanently. Real paths, real threads: B is reachable from the
            # control loop's `_step_navigation` failure arm, from the yield
            # policy's give-up (`_act_on_yield_decision`), and from a panel
            # `stop_navigation()`; A from any voice or panel navigation start.
            #
            # The fix takes the two locks in the ONE order the rest of the file
            # already uses. `_command_lock` is an `RLock`, so the nested
            # acquisition inside `stop_motion` is now a free re-entry by the
            # same thread rather than a wait, and the callers that already hold
            # `_command_lock` (every `preempt`-driven stop) re-enter it here at
            # no cost. Nothing about WHAT is protected changes.
            with self._command_lock, self._navigation_lock:
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

    def _apply_closed_intent(
        self,
        intent: ClosedIntent,
        directive: CapDirective,
        *,
        source: str = SAFETY_SOURCE_TYPED,
        phrase: str = "",
    ) -> str:
        """Executive / CommandArbiter caps for the closed companion intent enum.

        Card R21: ``source``/``phrase`` are carried, not decided, here. The
        default is the local typed lane — the handler the agent is constructed
        with — and the hosted lane declares ``voice`` at its own call site.
        """

        if directive.emergency_stop or intent is ClosedIntent.STOP:
            self.emergency_stop(
                source=source, phrase=phrase, rule=SAFETY_RULE_TYPED if phrase else ""
            )
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

    def _reconcile_semantic_tasks(self, *, stop_reason: str = "task_no_longer_active") -> None:
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
            # Card R12, from the live proof. ``task_no_longer_active`` is the
            # right word when a plan step genuinely ended on its own — the tick
            # callers keep it. It is the WRONG word when this reconciliation is
            # running because the owner just latched the emergency stop: the
            # interrupting caller tears the task down here and preempts its own
            # channels one line later, so the teardown wins the race, writes the
            # mission terminal, and the caller's ``preempt("safety",
            # reason="emergency_stop")`` then finds nothing left to stop. That
            # is why a live e-stop still read ``ended (idle):
            # task_no_longer_active`` with the channel propagation already in
            # place. The cause travels WITH the interrupt.
            self._stop_semantic_dispatches(to_stop, stop_reason)

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

    def _interrupt_brain(
        self, source: str, reason: str, *, stop_reason: str = "task_no_longer_active"
    ) -> None:
        """Interrupt the executive, and tell it what it is being interrupted FOR.

        Card R12: ``stop_reason`` is the word the resulting channel teardown
        records — the mission-log row, the panel event and the narrated fact all
        come from it. Callers pass the reason their own following ``preempt``
        uses, so the two cannot disagree about why the same mission ended;
        callers with no such preempt (and the executive's own tick-side
        reconciliation) keep the default, which is the executive's honest word
        for a plan step that is simply gone.
        """

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
        self._reconcile_semantic_tasks(stop_reason=stop_reason)

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("runtime is closed")
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        try:
            self.control_manager.start(threaded=not self._synchronous_control_dispatch)
            # Card C-1. Attached BEFORE the control loop exists, and the
            # ordering was chosen from a measurement rather than taste: with
            # the attach after the loop start, compiling the MuJoCo scene and
            # creating the ONNX session contended with an already-running 10 Hz
            # loop and produced a single 305 ms ControlLoopWork sample — one
            # startup tick, but three times the 100 ms deadline. Doing the
            # expensive construction while no loop is turning removes it.
            # The worker simply finds an empty pose mailbox until the loop
            # starts filling it, which costs nothing.
            #
            # ---- CARD P1-B seam 1 of 3: install the map BEFORE the eye. ----
            # Ordering is load-bearing in both directions. The map must exist
            # before the camera worker publishes its first frame or that frame
            # is silently dropped; and it must exist before
            # ``_attach_configured_camera_ingress`` builds the query batch,
            # because under ``learned_map`` that batch is
            # ``known_places()`` — the places the RELOADED map already knows —
            # plus the curiosity list. Off-oracle only; inert by default.
            self._p1b_install_learned_map()
            # ---- CARD CAP-1: required capabilities are startup-fatal --------
            # ORDERING IS THE WHOLE CORRECTNESS OF THIS CHECK, and it took two
            # goes to get right.
            #
            # It first sat here on the belief that P1-B's installer, one line
            # up, was the last word on the process-global candidate source.
            # VENUE-1 then took CAP-1's one-directional-binding finding into its
            # own region and put ``_venue1_bind_semantic_source()`` at the TOP of
            # ``_attach_configured_camera_ingress`` (seam 1a, above C-1's early
            # return, so it runs on every started runtime — camera on or off).
            # From that moment this check read the STALE global that the very
            # next line corrected: a profile that DECLARED a capability could be
            # refused for a disagreement the composition root was about to
            # resolve. A false refusal, in the one path this card exists to make
            # honest. VENUE-1 pinned it and handed it back (their handoff 9).
            #
            # The rule is therefore "after the LAST binder", not "after P1-B" —
            # and the last binder is asserted HERE, by calling it, rather than by
            # moving this block below the attach. This is the first of the two
            # remedies VENUE-1 offered.
            #
            # Card XD-1 (scrum/20260822/task_14): the SECOND reason this comment
            # used to give — that P1-B's seam test pinned the literal source text
            # ``_attach_configured_camera_ingress()`` immediately followed by
            # ``self._thread``, so nothing could sit between them — is GONE. That
            # test now compares the two call offsets and pins only the ordering
            # it means (install before attach), so the composition root is
            # extensible again. The placement above is kept on its own merits.
            #
            # Calling it twice is free and deliberate: VENUE-1 documents the
            # binder as idempotent ("re-asserts the same policy when the
            # installer already bound it, so the two cannot disagree") and as
            # never raising. ``getattr`` because a VENUE-1 region that is
            # reverted must degrade to the previous behaviour, not to an
            # AttributeError at boot.
            bind_semantic_source = getattr(self, "_venue1_bind_semantic_source", None)
            if callable(bind_semantic_source):
                bind_semantic_source()
            # INERT BY DEFAULT, and that is the whole design. A profile that
            # declares no ``required_capabilities:`` requires nothing, this
            # returns after one already-performed YAML read, and no tree in the
            # repository today changes behaviour. It adds NO runtime refusal —
            # ask-over-refuse still governs every tick; this is a
            # configuration-truth check at the door, once.
            #
            # A raise here lands in the ``except BaseException`` below, which
            # closes the runtime and re-raises, and no thread has started yet.
            from parcel_robot.admission import check_required_capabilities

            check_required_capabilities(self)
            # ---- END CARD CAP-1 (startup check) -----------------------------
            self._attach_configured_camera_ingress()
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
                    self._interrupt_brain(
                        "system_recovery", "runtime_closed", stop_reason="runtime_closed"
                    )
                    self.preempt(
                        "safety",
                        reason="runtime_closed",
                        targets=("follow", "search", "navigation", "spatial", "activities"),
                    )
                    already_latched = bool(self.arbiter.emergency_stopped)
                    self.agent.safety.engage_emergency_stop()
                    self.arbiter.engage_emergency_stop()
                    # Card R21. Teardown latches the arbiter too, and a snapshot
                    # taken while closing should not show an unexplained latch.
                    self._log_safety_latch(
                        source=SAFETY_SOURCE_RUNTIME_CLOSE, already_latched=already_latched
                    )
                    try:
                        self.control_manager.emergency_stop()
                    except (OSError, RuntimeError):
                        pass
                    self._last_sent = VelocityCommand()
                    self._was_moving = False
                    self.velocity_smoother.reset()
                    self._reset_motion_shaper()
            auxiliary_error: BaseException | None = None
            # Card R1.6: stop pumping before anything else is torn down, so a
            # driver thread can never touch a half-closed lane, then hang up the
            # hosted session (a live socket left open keeps billing).
            if self.realtime_driver is not None:
                try:
                    self.realtime_driver.stop()
                except BaseException as error:  # noqa: BLE001 - teardown must continue
                    auxiliary_error = error
            if self.realtime_gateway is not None:
                try:
                    self.realtime_gateway.stop()
                except BaseException as error:  # noqa: BLE001 - teardown must continue
                    auxiliary_error = error
            if self.realtime_lane is not None:
                try:
                    self.realtime_lane.close()
                except BaseException as error:  # noqa: BLE001 - teardown must continue
                    auxiliary_error = error
            # Card C-1. The camera stops BEFORE the evidence log closes, and
            # the order matters: the worker's last in-flight frame offers an
            # EV-1 row on its way out, and closing the log first would drop
            # exactly the final observation an incident review would want.
            # (This is a reordering of the pre-C-1 teardown, which stopped the
            # camera after the log — harmless when nothing published, wrong the
            # moment something did.)
            if self._camera_ingress is not None:
                try:
                    self._camera_ingress.stop()
                except BaseException as error:  # noqa: BLE001 - render teardown must continue
                    auxiliary_error = error
                self._camera_ingress = None
            # ---- CARD P1-B seam 3 of 3: persist what the robot learned. ----
            # AFTER the camera worker is stopped, so no frame can land between
            # the last ingest and the write, and BEFORE the evidence log closes
            # so the persist decision is in the record. Never raises; returns 0
            # when there is no store, and says so in the log rather than
            # letting a run look like it saved something.
            try:
                self._p1b_persist_learned_map()
            except BaseException as error:  # noqa: BLE001 - teardown must continue
                auxiliary_error = error
            # Card EV-1. Closed AFTER the lane so the lane's own teardown rows
            # are in the record, and before the rest of teardown so a later
            # failure cannot cost the flush.
            if self._session_evidence is not None:
                try:
                    self._session_evidence.close("runtime closed")
                except BaseException as error:  # noqa: BLE001 - teardown must continue
                    auxiliary_error = error
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
            # Card R21. The arbiter is the other refusal layer, and it is the
            # one the OWNER hits: an arrow key or the mobile pad under a latch
            # comes through here, not through `_refuse_under_latch`. Coalesced
            # by door, so a held key at the motion-refresh rate is one row with
            # a count rather than a ring full of the same sentence.
            self._note_safety_rejection(f"{source} motion", result.reason)
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
            self._interrupt_brain(
                "manual", "manual control acquired the base", stop_reason="manual_control"
            )
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
            self._interrupt_brain(
                "correction",
                "owner issued a direct motion command",
                stop_reason="voice_motion_started",
            )
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

    def emergency_stop(
        self,
        *,
        source: str = SAFETY_SOURCE_API,
        phrase: str = "",
        rule: str = "",
    ) -> None:
        """Latch every motion channel. ``source`` says WHICH DOOR did it.

        Card R21. The keyword is how attribution survives: live_run_1 could not
        exclude an accidental Space-key latch from a spoken one because nothing
        anywhere recorded which door fired, and the panel event that came
        closest had been evicted before anyone looked. Every caller in this
        class declares its own origin; ``SAFETY_SOURCE_API`` is the honest
        default for an in-process call that did not say (see the constant).

        ``phrase`` is the owner's utterance VERBATIM, for the voice doors only.
        It is recorded, never matched against — the matcher is
        ``realtime/ingress.py``'s and this card does not touch it.
        """

        already_latched = bool(self.arbiter.emergency_stopped)
        with self._command_lock:
            self._interrupt_brain(
                "emergency", "emergency stop latched", stop_reason="emergency_stop"
            )
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
        # The ring FIRST: the panel event is a notification into a deque that
        # anything chatty can flush, and the record has to exist even if the
        # emit below is the thing that goes wrong.
        self._log_safety_latch(
            source=source, phrase=phrase, rule=rule, already_latched=already_latched
        )
        self._emit(
            "safety",
            "Emergency stop latched",
            "error",
            detail={"source": source, "phrase": phrase, "rule": rule},
        )

    def clear_emergency_stop(self, *, source: str = SAFETY_SOURCE_API) -> str:
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
        # The operator acknowledgement that clears an emergency stop is also the
        # acknowledgement that clears a latched input-health stop (P0-B). It is
        # refused while the inputs are still faulted, so the clear can never
        # re-authorize translation into a broken sensor.
        self.clear_input_health_latch()
        # Card R21. The release is half of the record: live_run_1's latch was
        # NEVER released, and a ring that logs only latches cannot tell "still
        # stopped" from "stopped and let go" once the rows scroll.
        self._log_safety_release(source=source)
        self._emit(
            "safety",
            "Emergency stop cleared by operator",
            "warning",
            detail={"source": source},
        )
        return "Emergency stop cleared"

    def input_health_latch(self) -> dict[str, object]:
        """Inspect the P0-B input-health latch (state + the faults that set it)."""

        return {
            "latched": bool(self._input_health_latched),
            "faults": list(self._input_health_latch_faults),
            "sim_fixture_inputs_allowed": bool(self._sim_fixture_inputs_allowed),
            "require_physical_inputs": bool(self._require_physical_inputs),
            # Card W0-A: the DECLARED provenance of the retained feedback
            # source, so an operator can see whether this deployment is reading
            # a physical stream or a synthesized one.
            "state_source_origin": EvidenceOrigin(self._control_state_origin).value,
            # ---- CARD HW-2 go2-backend (scrum/20260822/task_40) ------------
            # The same question for the SCAN channel, and it is a different
            # channel with a different producer. `state_source_origin` above
            # answers it for pose/feedback; until this card there was nothing
            # to read for the scan, so an operator could not tell whether the
            # geometry authorizing (or refusing) motion came from a robot, a
            # recording, or nothing at all.
            #
            # It is also the visible half of a deliberate acceptance: code CAN
            # declare PHYSICAL untruthfully (`LiveGo2Sources` IS such a
            # declaration, and no typed check can distinguish an honest one
            # from a liar). What the product owes is not a check it cannot
            # write but a RECORD of what was declared and by whom — hence the
            # name too, which is the SOURCE's (`go2_live` /
            # `go2_stage0_replay`), never the bare backend kind.
            **self._scan_source_record(),
            # ---- END CARD HW-2 ---------------------------------------------
        }

    # ---- CARD HW-2 go2-backend (scrum/20260822/task_40) --------------------
    def _scan_source_record(self) -> dict[str, object]:
        """`scan_source_origin` / `scan_source_name` for the latch record."""

        source = getattr(self.backend, "scan_evidence_source", None)
        if source is None:
            return {"scan_source_origin": None, "scan_source_name": None}
        return {
            "scan_source_origin": declared_origin(source).value,
            "scan_source_name": str(getattr(source, "name", "") or ""),
        }

    # ---- END CARD HW-2 -----------------------------------------------------

    def clear_input_health_latch(self, *, now: float | None = None) -> str:
        """Operator acknowledgement for a latched input-health stop (P0-B).

        The latch is what makes ``LATCHED_STOP`` a latch: input recovery alone
        never clears it. This refuses to clear while the current evidence still
        latches, so acknowledging a fault that is still live cannot re-authorize
        motion.
        """

        if not self._input_health_latched:
            return "input health not latched"
        with self._lock:
            observation = self._observation
        verdict = self._evaluate_dispatch_input_health(
            observation,
            now=time.monotonic() if now is None else now,
        )
        if verdict.stop_latched:
            return "input health still latched: " + ", ".join(
                f"{fault.required_input.value}:{fault.reason}"
                for fault in verdict.faults
                if fault.action is HealthAction.LATCHED_STOP
            )
        self._input_health_latched = False
        self._input_health_latch_faults = ()
        self._emit("safety", "Input-health stop cleared by operator", "warning")
        return "Input health latch cleared"

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

    # ======================================================================
    # CARD ROAM-1 — "GO EXPLORE" IS A RUNTIME BEHAVIOR
    #
    # A NEW region. P1-B's camera->map writer, P2-A's owner-model doors, P2-B's
    # affect helpers and the camera attach site are all elsewhere in this file
    # and none of them is touched. CURIO-1 owns the whisperer feed and it is
    # not touched either — what this region offers CURIO-1 is
    # :meth:`roam_idle_checkpoint`, which is the patrol prompt's own rule
    # ("social actions can wait until an idle checkpoint") made readable.
    #
    # WHAT THIS IS. ``patrol/mission.py``'s ``PatrolPolicy`` — MOVE-1's, and
    # never once constructed on the product path — driven from the control loop
    # beside follow/search/spatial/navigation, on a fixed time budget.
    #
    # WHAT IT IS NOT, and this is the whole safety argument:
    #
    #   * It is not an authority. Every command it proposes is submitted
    #     through ``submit_motion`` and therefore crosses the arbiter, the pace
    #     cap, ``apply_reactive_safety`` and the e-stop exactly like a typed
    #     arrow key. The policy's job is to stop PROPOSING headings the gate
    #     would refuse (E2-D2's measured failure), not to be trusted with any.
    #   * It is not a planner. It never names a goal, never grounds a place and
    #     never touches PlanIR admission. It is a proposer with a clock.
    #   * It does not survive anything. A latch, an owner command, a lost pose,
    #     a closed runtime or an exhausted budget all end it, and the check
    #     that ends it runs FIRST in the step, before any sensing.
    #
    # THE ARBITER SOURCE IS ``voice``. Roam is owner-commanded by construction
    # (the broker tool is in ``MOTION_TOOLS`` and out of the proactive ceiling;
    # the ingress kind only exists for an owner utterance), so it travels the
    # channel an owner's direct motion command travels — the same one MOVE-1's
    # harness used to measure the patrol. It is NOT given a new
    # ``SOURCE_PRIORITIES`` entry: adding a priority row is a change to the
    # arbitration contract for every subsystem, and this behavior does not need
    # one because it yields by STOPPING rather than by losing a bid.

    #: Every key the ``roam:`` config section may carry. Read by
    #: :meth:`roam_config`, which refuses anything else BY NAME. The two
    #: clearance thresholds are deliberately absent: they are derived from
    #: ``safety.person_stop_m`` / ``safety.obstacle_stop_m`` so the patrol can
    #: never be tuned inside the gate that refuses it.
    ROAM_CONFIG_KEYS: ClassVar[frozenset[str]] = frozenset(
        # ---- CARD ROAM-2 -----------------------------------------------
        # ``coverage`` is card ROAM-2's: the learned-map objective, **OFF by
        # default** and turn-on-able by name. It is a key rather than a
        # constant because the two arms of that card's measurement have to
        # differ by a CONFIG line and nothing else, or they are not two arms of
        # the same product path.
        {"budget_s", "cruise_vx", "turn_vyaw", "alternate_turns", "tether_m", "coverage"}
        # ---- END CARD ROAM-2 config key ---------------------------------
    )

    #: The roam budget when the owner does not say how long. Two minutes is
    #: MOVE-1's own measurement window, which is what makes the card's three
    #: 120 s runs comparable with its 0.134 m baseline.
    DEFAULT_ROAM_BUDGET_S: ClassVar[float] = 120.0
    #: Bounds on a requested budget. The broker clamps in minutes on the model's
    #: side; this clamps in seconds on the runtime's, because the runtime is the
    #: side that must still be right when the caller is a panel or a test.
    MIN_ROAM_BUDGET_S: ClassVar[float] = 15.0
    MAX_ROAM_BUDGET_S: ClassVar[float] = 600.0
    #: How often the policy is asked for a heading. The control loop runs at
    #: ``loop_hz``; asking a turn-or-cruise policy at 10 Hz buys nothing over
    #: asking it at 4 Hz and costs a proposal that changes sign mid-turn.
    ROAM_TICK_S: ClassVar[float] = 0.25

    def start_roam(self, budget_s: float | None = None) -> str:
        """Begin a bounded roam. Refuses rather than queueing behind anything.

        Every refusal here is a ``ValueError`` because the broker maps that to
        ``rejected`` with the sentence intact — the model then says the true
        reason ("I'm already exploring", "I'm stopped") instead of a guess.
        """

        if self._closed:
            raise RuntimeError("runtime is closed")
        budget = self._clamped_roam_budget(budget_s)
        with self._command_lock:
            if self.arbiter.emergency_stopped or self.agent.safety.emergency_stopped:
                # Same refusal every other positive-motion door gives under a
                # latch, and it is recorded the same way.
                self._refuse_under_latch("roam")
            if self._roam_active:
                raise ValueError("the robot is already out roaming")
            if self.follow.enabled:
                raise ValueError(
                    "the robot is following its owner right now; ask it to stay first"
                )
            with self._lock:
                navigating = self._navigation_directive is not None
            if navigating:
                raise ValueError("the robot is already on its way somewhere")
            self._interrupt_brain("correction", "owner sent the robot out to roam")
            self.preempt(
                "voice",
                reason="roam_started",
                targets=("spatial", "search", "activities"),
            )
            policy = PatrolPolicy(self._roam_limits(budget))
            with self._lock:
                self._roam_policy = policy
                self._roam_budget_s = budget
                self._roam_started_at = time.monotonic()
                self._roam_last_tick_at = 0.0
                self._roam_reason = "starting"
                self._roam_idle_checkpoint = True
                self._roam_ticks = 0
                self._roam_refused = 0
                # ---- CARD ROAM-2: a new roam has covered nothing yet, and
                # the previous roam's objective is not this one's.
                self._roam_coverage = {}
                self._roam_coverage_legs = 0
                # ---- END CARD ROAM-2 start reset --------------------------
                self._behavior_generation += 1
        message = f"Roaming for the next {budget:g} seconds"
        self._emit("roam", message, "success")
        return message

    def stop_roam(self, reason: str = "owner_stopped") -> str:
        """End a roam in ONE tick. Idempotent, and never raises on an idle dog.

        Idempotent on purpose: "stop roaming" said to a robot that is already
        standing still must be a calm confirmation, not an error the model has
        to narrate as a failure.
        """

        with self._lock:
            was_active = self._roam_policy is not None
            self._roam_policy = None
            self._roam_started_at = 0.0
            self._roam_last_tick_at = 0.0
            self._roam_reason = str(reason)
            self._roam_idle_checkpoint = True
            # ---- CARD ROAM-2: the LEG COUNT SURVIVES the stop on purpose —
            # it is what the run just did, and a caller reading the snapshot
            # after a budget-exhausted roam wants the total, not a zero. The
            # live objective does not survive: nothing is being aimed at.
            self._roam_coverage = {}
            # ---- END CARD ROAM-2 stop reset -------------------------------
            if was_active:
                self._behavior_generation += 1
        if not was_active:
            return "The robot is not roaming"
        # ---- HOW A ROAM LETS GO OF THE BODY, and it is THREE cases ---------
        #
        # Corrected under verification. This used to call ``stop_motion()`` for
        # every reason except the latch, and ``stop_motion`` does
        # ``preempt("manual", targets=("spatial",))`` on the way through — so a
        # roam "yielding" to an owner who had just said "walk a circle around
        # me" cancelled that circle one tick later. Reproduced in-process
        # through ``start_spatial_behavior``. The dog obeyed the command and
        # then stopped obeying it, and the roam looked like the polite one.
        #
        # The distinction the three arms encode is WHO ALREADY OWNS THE BODY:
        #
        #   * ``emergency_stop`` / ``runtime_closed`` — the latch or the
        #     shutdown has already stopped the body. A second stop here would
        #     only race with it.
        #   * ``owner_command`` — a NEW owner behavior owns the body as of this
        #     tick. The roam must release its own channel and touch nothing
        #     else: ``arbiter.cancel("voice")`` retires the roam's intent and
        #     stops there. Settling the body would be this behavior overruling
        #     the owner on its way out the door.
        #   * everything else (``owner_stopped``, ``budget_exhausted``,
        #     ``boxed_in``, ``input_health_latched``) — nobody else asked for
        #     anything, so the roam owes the owner a body that is standing
        #     still, and ``stop_motion`` is how it settles.
        if reason == "owner_command":
            with self._command_lock:
                self.arbiter.cancel("voice")
        elif reason not in {"emergency_stop", "runtime_closed"}:
            with self._command_lock:
                self.arbiter.cancel("voice")
                self.stop_motion()
        message = f"Stopped roaming ({reason})"
        self._emit("roam", message, "info")
        return message

    @property
    def _roam_active(self) -> bool:
        with self._lock:
            return self._roam_policy is not None

    def roam_idle_checkpoint(self) -> bool:
        """Is the roam between legs — i.e. may a social action run right now?

        ``prompts/functions/patrol.yaml``'s rule, made readable rather than
        re-worded: "social actions can wait until an idle checkpoint". A roam
        that is TURNING is negotiating a blocked lane and is the worst moment to
        interrupt; a roam that is cruising, or not roaming at all, is a
        checkpoint. CURIO-1's remarks ride this predicate — it is published for
        that card and this region does not call it.
        """

        with self._lock:
            return bool(self._roam_idle_checkpoint)

    def roam_snapshot(self) -> dict[str, object]:
        """What the panel and the hosted model may know about the roam."""

        with self._lock:
            policy = self._roam_policy
            started = self._roam_started_at
            budget = self._roam_budget_s
            reason = self._roam_reason
            ticks = self._roam_ticks
            refused = self._roam_refused
            checkpoint = self._roam_idle_checkpoint
            # ---- CARD ROAM-2: read under the same lock as the rest --------
            coverage = dict(self._roam_coverage)
            coverage_legs = self._roam_coverage_legs
            # ---- END CARD ROAM-2 snapshot read ----------------------------
        active = policy is not None
        elapsed = max(0.0, time.monotonic() - started) if active and started else 0.0
        return {
            "active": active,
            "budget_s": round(float(budget), 3),
            "elapsed_s": round(elapsed, 3),
            "remaining_s": round(max(0.0, budget - elapsed), 3) if active else 0.0,
            "reason": reason,
            "ticks": ticks,
            "refused": refused,
            "idle_checkpoint": checkpoint,
            # ---- CARD ROAM-2: what the coverage objective is doing ---------
            # ``enabled`` is the LIMITS' own flag rather than a copy of the
            # config, so a snapshot can never say the objective is on while the
            # running policy has it off. ``target``/``age_s`` are ``None`` on
            # every tick the map had nothing to offer, which is the honest
            # rendering of a degrade to ROAM-1's wander.
            "coverage": {
                "enabled": bool(policy.limits.coverage_bias) if policy is not None else False,
                "legs": int(coverage_legs),
                "target": coverage.get("entry_id"),
                "label": coverage.get("label"),
                "bearing_rad": coverage.get("bearing_rad"),
                "age_s": coverage.get("age_s"),
                "distance_m": coverage.get("distance_m"),
                "candidates": int(coverage.get("candidates") or 0),
            },
            # ---- END CARD ROAM-2 status block -----------------------------
            "min_person_clearance_m": (
                round(policy.limits.min_person_clearance_m, 3) if policy is not None else None
            ),
            "min_forward_clearance_m": (
                round(policy.limits.min_forward_clearance_m, 3) if policy is not None else None
            ),
        }

    def _clamped_roam_budget(self, budget_s: float | None) -> float:
        if budget_s is None:
            # Card ROAM-1, corrected under verification: the OWNER'S default,
            # from their profile, not the class constant. The constant is the
            # fallback for a config that does not mention roam at all, which is
            # every config today except the prototype profile.
            configured = self.roam_config.get("budget_s")
            if configured is None:
                return float(self.DEFAULT_ROAM_BUDGET_S)
            try:
                value = float(configured)
            except (TypeError, ValueError):
                raise ValueError(
                    f"roam.budget_s must be a number, not {configured!r}"
                ) from None
            if not math.isfinite(value):
                raise ValueError("roam.budget_s must be finite")
            return min(self.MAX_ROAM_BUDGET_S, max(self.MIN_ROAM_BUDGET_S, value))
        try:
            value = float(budget_s)
        except (TypeError, ValueError):
            raise ValueError("roam budget must be a number") from None
        if not math.isfinite(value):
            raise ValueError("roam budget must be finite")
        return min(self.MAX_ROAM_BUDGET_S, max(self.MIN_ROAM_BUDGET_S, value))

    def _roam_limits(self, budget_s: float) -> PatrolLimits:
        """The proposer's thresholds, DERIVED from this runtime's own gate.

        ``patrol.limits_from_safety`` is the pure half and is unit-tested
        without a runtime; this is the two-line adapter that hands it the
        numbers the reactive gate was actually built with, so a prototype
        profile that commissions ``safety.person_stop_m: 0.7`` (card P1-E) gets
        a patrol that keeps 0.85 m rather than one still turning away at 1.35 m.
        """

        overrides = self.roam_config
        shipped = PatrolLimits()
        tether = overrides.get("tether_m", DEFAULT_ROAM_TETHER_M)
        return limits_from_safety(
            person_stop_m=self.person_stop_m,
            obstacle_stop_m=self.obstacle_stop_m,
            budget_s=budget_s,
            cruise_vx=float(overrides.get("cruise_vx", shipped.cruise_vx)),
            turn_vyaw=float(overrides.get("turn_vyaw", shipped.turn_vyaw)),
            alternate_turns=bool(overrides.get("alternate_turns", True)),
            # ``None`` is a legitimate value here and means unbounded, so it is
            # read through a sentinel rather than through ``or``: ``tether_m:
            # null`` in the profile must mean "no tether", not "use the
            # default".
            tether_m=None if tether is None else float(tether),
            # ---- CARD ROAM-2: the coverage objective, OFF unless asked -----
            # CORRECTED at the third attempt: the 17:38 draft read this key
            # with a default of ``True``, which made the learned-map objective
            # the shipped roam behaviour without anybody writing it in a
            # profile. The standing rule for this wave is defaults OFF for
            # behaviour (``scrum/20260822/TASK_BOARD.md`` rule 1), so the
            # default is ``False`` and the objective exists only where a
            # profile says ``roam: {coverage: true}``.
            #
            # Flag-off, the roam is ROAM-1's byte for byte: ``PatrolLimits``
            # defaults it off, ``limits_from_safety`` defaults it off, and
            # ``PatrolPolicy._cruise_or_cover`` returns the same ``advance``
            # command it always did. That identity is what makes ROAM-2's
            # baseline arm a real baseline rather than a different robot
            # (``scrum/20260822/task_33/PREREGISTRATION.md`` §2).
            #
            # ``bool()`` of a YAML value is deliberate and matches
            # ``alternate_turns`` above: the section's spelling is guarded by
            # name in ``roam_config``, and a well-spelled key with a nonsense
            # value reads as truthy exactly as it does for every other flag.
            coverage_bias=bool(overrides.get("coverage", False)),
            # ---- END CARD ROAM-2 limits key --------------------------------
        )

    @property
    def roam_config(self) -> dict[str, object]:
        """The optional ``roam:`` section, read once per call, never cached.

        Card ROAM-1, corrected under verification. This used to be read
        straight from ``store.section("roam")`` and it was DEAD: the base
        configuration is SHA-locked and omits the section, so the profile
        overlay loader refused any ``roam:`` block an operator wrote
        (``config.check_overlay_keys``). The five key paths are now on
        :data:`~parcel_robot.config.OVERLAY_INTRODUCIBLE_KEYS` with a reason,
        so ``configs/robot.prototype.yaml`` can carry them and they arrive
        here. Absent, every reader below falls to a code default.
        """

        section = self.store.section("roam")
        if not isinstance(section, dict):
            return {}
        # THE SPELLING GUARD, and it has to be here. ``config.py`` exempts the
        # whole ``roam`` subtree from the overlay key check (the exemption
        # cannot be narrower — the loader stops descending at an exempt
        # parent), so this is the roam family's equivalent of
        # ``CameraStreamConfig.from_section``: without it, ``budget_st: 300``
        # would merge cleanly, read as nothing, and leave the owner with a
        # 120 s roam while the file on disk said five minutes. That is the
        # ``minimum_confidenc`` failure verbatim.
        unknown = sorted(str(key) for key in section if str(key) not in self.ROAM_CONFIG_KEYS)
        if unknown:
            raise ValueError(
                f"unknown roam config key(s): {', '.join(unknown)}; "
                f"allowed: {', '.join(sorted(self.ROAM_CONFIG_KEYS))}"
            )
        return dict(section)

    # ---- CARD ROAM-2: the coverage objective, read from P1-B's map --------
    #
    # THE LOCK, first, because it is the only structural risk this card adds.
    # ``_p1b_map_lock`` is a LEAF in R24's roster: the only two places that
    # take it call nothing that takes another runtime lock, and its single
    # pinned edge is ``_close_lock -> _p1b_map_lock``. This method keeps it a
    # leaf — it is called from ``_step_roam`` OUTSIDE ``_lock`` and OUTSIDE
    # ``_command_lock``, it holds the map lock across one pure query, and it
    # calls nothing back into the runtime. ``PINNED_LOCK_ORDER`` is unchanged
    # and ``test_the_lock_order_is_the_pinned_one`` is the proof.
    #
    # It is also a READER of the map and never a writer: ``coverage_candidates``
    # derives everything from fields the camera worker already maintains.

    def _roam_coverage_objective(self, observation: SimObservation) -> dict[str, object]:
        """Where has the map not looked lately? ``{}`` when it cannot say.

        Every failure — no learned map installed (the shipping ``oracle``
        source, and every run before P1-B), an empty map, a map whose entries
        are all in view, a query that raises — returns ``{}``, which the policy
        reads as "no objective" and answers with ROAM-1's wander. There is no
        path through this method that can end a roam, and that is the whole
        contract: a coverage objective is a preference, and a preference that
        can stop a dog is a bug.
        """

        learned = getattr(self, "_p1b_learned_map", None)
        if learned is None:
            return {}
        try:
            with self._p1b_map_lock:
                rows = learned.coverage_candidates(
                    float(observation.robot.x),
                    float(observation.robot.y),
                    float(observation.robot.yaw),
                    # The map stamps entries on the WALL clock
                    # (``MapObservation.observed_wall_s``), so the age has to be
                    # asked on the wall clock too. ``time.monotonic()`` here
                    # would produce an age of "-1.7e9 seconds" and the query
                    # would answer ``None`` for every entry — correct, and
                    # useless.
                    now_wall_s=time.time(),
                    limit=self.ROAM_COVERAGE_CANDIDATES,
                )
        except (
            # CARD ROAM-2, F2 of the verifier's correction pass: this handler
            # used to be a blind ``except Exception`` carrying a lint-suppression
            # directive. The COMMON brief forbids suppression directives, so the
            # handler now NAMES every exception it catches instead.
            #
            # WHY A WIDE TUPLE IS STILL RIGHT HERE. ``_step_roam`` is called from
            # ``_control_loop_body`` at :10347, which is OUTSIDE that method's
            # only ``except`` (:10254, which guards ``backend.observe()`` alone),
            # and ``_control_loop`` wraps the body in ``try/finally`` — no
            # ``except``. So an exception raised here does not degrade a
            # behaviour, it KILLS THE 10 Hz CONTROL THREAD. A coverage objective
            # is a preference; a preference that can stop a dog is a bug.
            #
            # The shape is the one this file already uses for exactly that job
            # and carries no suppression directive: the thread-boundary tuple at
            # ``runtime.py:10254`` — ``(OSError, RuntimeError, TypeError,
            # ValueError)``. Extended here by what the query path adds:
            #
            #   AttributeError  ``self._visibility_range_m`` / ``entry.surface_x``
            #                   / ``.last_seen_wall_s`` on an object that is not
            #                   a real map (``_p1b_learned_map`` is typed ``Any``)
            #   TypeError       non-numeric ``surface_x/y`` into ``math.hypot``,
            #                   ``round``, or the ``rows.sort`` key
            #   ValueError      the ``float()`` conversions in the query
            #   ArithmeticError ``math.hypot``/``atan2`` overflow on absurd coords
            #   LookupError     a mapping-shaped entry row missing a key
            #   OSError         a future store-backed ``active_entries()``
            #   RuntimeError    a map implementation declaring itself broken
            #
            # ``online_map.py``'s own query (:1112-1200) already swallows the
            # conversion errors it can see and answers ``()``; this tuple is for
            # the map objects it cannot vouch for.
            ArithmeticError,
            AttributeError,
            LookupError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            logger.debug("the learned map could not offer a coverage objective")
            return {}
        for row in rows:
            if row.get("age_s") is None:
                # Rows are ordered ages-first, unknown-last, so the first
                # unknown means there are no known ages left to consider.
                break
            return {
                "entry_id": row.get("entry_id"),
                "label": row.get("label"),
                "bearing_rad": float(row["bearing_rad"]),
                "age_s": float(row["age_s"]),
                "distance_m": float(row.get("distance_m") or 0.0),
                "candidates": len(rows),
            }
        return {"candidates": len(rows)}

    #: How many map entries the objective query is allowed to rank per tick.
    #: Small on purpose: this runs inside the control loop's period and the
    #: only row that is ever used is the first one with a known age.
    ROAM_COVERAGE_CANDIDATES: ClassVar[int] = 8

    # ---- END CARD ROAM-2 coverage-objective reader ------------------------

    def _roam_sense(
        self,
        observation: SimObservation,
        elapsed_s: float,
        # ---- CARD ROAM-2: the objective arrives as ONE optional mapping.
        # Defaulting to ``None`` keeps every existing caller byte-identical.
        coverage: Mapping[str, object] | None = None,
        # ---- END CARD ROAM-2 sense argument -------------------------------
    ) -> PatrolSense | None:
        """This tick's sensing, through the patrol package's TESTED adapter.

        ``sense_from_snapshot`` is fed a compact mapping shaped exactly like the
        public snapshot's relevant keys rather than the whole of
        :meth:`snapshot` — which takes ``_lock``, walks the event ring and
        renders half the panel. Same adapter, same units (heading in DEGREES,
        which is the bug MOVE-1 measured as a -81.9 rad bearing), no second
        implementation of the sensing anywhere.
        """

        payload: dict[str, object] = {
            "robot": {
                "x": observation.robot.x,
                "y": observation.robot.y,
                "heading": math.degrees(observation.robot.yaw),
            },
            "owner": {
                "x": observation.owner.x,
                "y": observation.owner.y,
                "visible": observation.owner.visible,
            },
            "collision": bool(observation.collision),
            "obstacle_distance_m": observation.nearest_obstacle_m,
        }
        if observation.nearest_person_id is not None:
            payload["nearest_person"] = {
                "distance_m": observation.nearest_person_m,
                "bearing_rad": observation.nearest_person_bearing_rad,
            }
        if observation.lidar_ranges:
            payload["lidar_scan"] = {
                "ranges": list(observation.lidar_ranges),
                "angle_min_rad": observation.lidar_angle_min_rad,
                "angle_increment_rad": observation.lidar_angle_increment_rad,
                "range_max_m": observation.lidar_range_max_m,
            }
        return sense_from_snapshot(
            payload,
            elapsed_s=elapsed_s,
            # The SAME envelope the spatial behaviors and the owner-keepout
            # minimum are built from, read from the controller's own config
            # rather than re-stated: an owner is a person for standoff purposes
            # and carries this extra radius, and forgetting it is what parked
            # C-1's robot 0.31 m from the origin.
            owner_envelope_m=self.spatial.config.owner_collision_envelope_m,
            # ---- CARD ROAM-2: two scalars, and they are the WHOLE coupling
            # between the learned map and the patrol: the policy stays a pure
            # function of numbers and never learns that a map exists.
            coverage_bearing_rad=(
                None if not coverage else coverage.get("bearing_rad")  # type: ignore[arg-type]
            ),
            coverage_age_s=(
                None if not coverage else coverage.get("age_s")  # type: ignore[arg-type]
            ),
            # ---- END CARD ROAM-2 sense wiring -----------------------------
        )

    def _step_roam(self, observation: SimObservation | None) -> None:
        """One roam tick. Yields before it senses; senses before it proposes."""

        with self._lock:
            policy = self._roam_policy
            started = self._roam_started_at
            budget = self._roam_budget_s
            last_tick = self._roam_last_tick_at
        if policy is None:
            return

        # ---- the ladder that ENDS a roam, ahead of everything else --------
        if self._closed:
            self.stop_roam("runtime_closed")
            return
        if self.arbiter.emergency_stopped or self.agent.safety.emergency_stopped:
            # A latch has already stopped the body. All this does is make sure
            # nothing proposes another heading on the next tick — a roam that
            # merely had its commands refused would resume the instant the latch
            # cleared, which is a dog that remembers an errand nobody re-issued.
            self.stop_roam("emergency_stop")
            return
        if self._input_health_latched:
            self.stop_roam("input_health_latched")
            return
        with self._lock:
            navigating = self._navigation_directive is not None
        if navigating or self.follow.enabled or self.search.enabled or self.spatial.active:
            # ANY owner command wins, and it wins by ending the roam rather than
            # outbidding it: the owner asked for something specific and a roam
            # that resumed underneath it would be the robot ignoring them.
            self.stop_roam("owner_command")
            return
        now = time.monotonic()
        elapsed = now - started
        if elapsed >= budget:
            self.stop_roam("budget_exhausted")
            return
        if observation is None or not self._observation_is_fresh(observation):
            # No pose, or a stale one. Do not drive blind and do not end the
            # mission on one gap — MOVE-1's runner rule, kept.
            return
        if now - last_tick < self.ROAM_TICK_S:
            return

        # ---- CARD ROAM-2: LAST of the inputs and OUTSIDE every runtime lock — the
        # ladder above has already decided this tick is allowed to propose
        # something, so the map is asked only once nothing else objects. That
        # is the card's yield order made structural rather than commented:
        # safety gates, e-stop, owner command, budget, freshness, then (inside
        # the policy) tether, then coverage.
        coverage = (
            self._roam_coverage_objective(observation)
            if policy.limits.coverage_bias
            else {}
        )
        # ---- END CARD ROAM-2 objective call -------------------------------
        sense = self._roam_sense(observation, elapsed, coverage)
        if sense is None:
            return
        command = policy.step(sense)
        if command.reason == "boxed_in":
            # The policy gave up rather than spinning out the budget. That is a
            # BLOCKER, and the patrol prompt's rule is to report one.
            self.stop_roam("boxed_in")
            return
        if command.reason == "budget_exhausted":
            self.stop_roam("budget_exhausted")
            return
        # ---- THE STOP/TICK RACE, closed under the command lock -------------
        #
        # Corrected under verification. The submit and the "am I still
        # roaming?" post-check used to be two separate critical sections, so a
        # ``stop_roam`` landing between them left ONE roam command already
        # accepted by the arbiter with up to ``loop_period * 3`` of TTL still
        # to run: the owner said "stop roaming" and the dog took one more step.
        #
        # Both halves now happen inside ``_command_lock`` — the same lock
        # ``stop_roam`` takes to cancel the channel — and the membership test
        # is re-read INSIDE it rather than trusted from the top of the tick. A
        # stop that wins the lock first is seen here and nothing is submitted;
        # a stop that loses it finds the intent already cancelled on the line
        # below. There is no interleaving that leaves a live roam command
        # behind a stopped roam.
        with self._command_lock:
            with self._lock:
                still_roaming = self._roam_policy is policy
            if not still_roaming:
                # Stopped while this tick was deciding. Belt and braces: the
                # channel is retired again in case this tick's submit had
                # already landed before the stop took the lock.
                self.arbiter.cancel("voice")
                return
            accepted = self._submit_roam_command(command)
            with self._lock:
                if self._roam_policy is not policy:
                    self.arbiter.cancel("voice")
                    return
                self._roam_last_tick_at = now
                self._roam_reason = command.reason
                self._roam_ticks += 1
                if not accepted:
                    self._roam_refused += 1
                # The patrol prompt's idle checkpoint: cruising or idle is a
                # moment a social action may take; a turn is the robot
                # negotiating a lane.
                #
                # ---- CARD ROAM-2 adds ``advance_coverage`` — walking a coverage
                # leg — and deliberately does NOT add ``turn_coverage``: the
                # alignment onto a new objective is the robot deciding where to
                # go next, which is the same kind of moment as negotiating a
                # blocked lane. So the checkpoint OPENS the instant a coverage
                # leg starts being walked, which is the "idle checkpoint after
                # each coverage leg" the card asks for, and CURIO-1's
                # ``roam_idle_checkpoint()`` consumer needs no change at all.
                self._roam_idle_checkpoint = command.reason in {
                    "advance",
                    "advance_coverage",
                    "idle",
                }
                # Card ROAM-2's record for the panel and the harness.
                self._roam_coverage = dict(coverage)
                self._roam_coverage_legs = int(policy.coverage_legs)
                # ---- END CARD ROAM-2 checkpoint + record ------------------

    def _submit_roam_command(self, command: PatrolCommand) -> bool:
        """Hand one proposal to the arbiter. A refusal is data, never an error."""

        try:
            self.submit_motion(
                "voice",
                VelocityCommand(vx=command.vx, vy=command.vy, vyaw=command.vyaw),
                ttl=self.loop_period * 3.0,
            )
        except (RuntimeError, ValueError):
            return False
        return True

    # ---- CARD AWARE-1 (scrum/20260823/task_4) — the head turn --------------
    #
    # "The robot should periodically turn its head to stay aware of its
    # surroundings — there may be people around." (owner, 2026-08-23)
    #
    # This proposes a bounded yaw and nothing else. It creates no authority: it
    # goes through `submit_motion` -> the arbiter -> `_collision_safe` like
    # every other producer, it rides the channel roam already rides, and it is
    # the LOWEST thing in the loop — every named behaviour above it suppresses
    # it by simply existing. People seen during a sweep reach perception by the
    # ordinary path; nothing here touches detection, the owner track or the
    # semantic map.

    def _awareness_idle(
        self, observation: SimObservation | None, now: float
    ) -> tuple[bool, str | None]:
        """Is the body free for a discretionary look? The reason, if not.

        Deliberately NOT "the arbiter has no active intent": while a sweep is
        running the sweep itself is that intent, and a predicate that read the
        arbiter would end every sweep one tick after it began. Idle here means
        no NAMED behaviour wants the body. An owner who grabs it anyway —
        manual teleop at priority 80 — outbids the sweep at the arbiter, which
        is the refusal path below and needs no predicate of its own.
        """

        if self._closed:
            return False, "runtime_closed"
        if self.arbiter.emergency_stopped or self.agent.safety.emergency_stopped:
            return False, "emergency_stop"
        if self._input_health_latched:
            return False, "input_health_latched"
        with self._lock:
            navigating = self._navigation_directive is not None
            roaming = self._roam_policy is not None
        if navigating or self.follow.enabled or self.search.enabled or self.spatial.active:
            return False, "owner_command"
        if roaming:
            # Roam is already turning the body and already looking; a second
            # proposer nudging the same yaw would be two behaviours arguing.
            return False, "roaming"
        if observation is None or not self._observation_is_fresh(observation):
            return False, "no_observation"
        return True, None

    def _step_awareness(self, observation: SimObservation | None) -> None:
        """One awareness tick. Proposes nothing on the overwhelming majority."""

        if not self._awareness_limits.enabled:
            return
        now = time.monotonic()
        if now - self._awareness_last_tick_at < AWARENESS_TICK_S:
            return
        self._awareness_last_tick_at = now

        idle, reason = self._awareness_idle(observation, now)
        permitted = False
        if idle:
            # THE R28 TABLE, consulted before anything is proposed. This is a
            # READ of the join, not a second gate: `_evaluate_dispatch_input_health`
            # sets nothing (only `_collision_safe` latches), and re-joining the
            # same observation is already a supported call — `clear_input_health_latch`
            # does exactly it, and both commissioned sources exempt a re-read
            # of the same datum from their ordering check for that reason.
            verdict = self._evaluate_dispatch_input_health(observation, now=now)
            permitted = awareness_yaw_permitted(
                verdict, latched=self._input_health_latched
            )
            if not permitted:
                reason = "r28_axis_table"
        self._awareness_suppressed_reason = None if (idle and permitted) else reason

        proposal = self._awareness_sweep.step(now, idle=idle, yaw_permitted=permitted)
        if proposal is None:
            return
        try:
            self.submit_motion(
                "voice",
                VelocityCommand(vyaw=proposal.vyaw),
                # Long enough to bridge the gap to the next ask, whichever of
                # the two rates is slower. Taking the max rather than
                # AWARENESS_TICK_S alone keeps this a positive duration even if
                # the ask rate is turned all the way down — an intent with a
                # non-positive TTL is refused at construction, which would have
                # made the whole behaviour look like a permanent refusal.
                ttl=max(AWARENESS_TICK_S, self.loop_period) * 3.0,
            )
        except (RuntimeError, ValueError):
            # A refusal is DATA, never an error — `_submit_roam_command`'s rule,
            # and the one that matters most here: on the hardware that exists
            # today the body refuses motion, so this is the path the feature
            # actually takes. Abandon the sweep rather than retry into a wall;
            # the cadence brings it back.
            self._awareness_refused += 1
            self._awareness_sweep.reset()

    def awareness_snapshot(self) -> dict[str, object]:
        """What the head turn is doing, for the panel and the status doc."""

        limits = self._awareness_limits
        return {
            "enabled": bool(limits.enabled),
            "sweeping": bool(self._awareness_sweep.sweeping),
            "swept_rad": round(float(self._awareness_sweep.swept_rad), 6),
            "sweeps_started": int(self._awareness_sweep.sweeps_started),
            "sweeps_completed": int(self._awareness_sweep.sweeps_completed),
            "refused": int(self._awareness_refused),
            "suppressed_reason": self._awareness_suppressed_reason,
            "idle_period_s": float(limits.idle_period_s),
            "sweep_arc_rad": float(limits.sweep_arc_rad),
            "sweep_vyaw": float(limits.sweep_vyaw),
        }

    def set_proximity_context(self, context: object, *, source: str = "tool") -> str:
        """PROPOSE a proxemics context; returns the context now in force.

        Card PROX-1's seam, kept reachable for the reasoning-model tool that
        will call it. It takes a preregistered CONTEXT NAME and nothing else —
        `ProximityContext.parse` refuses anything number-shaped — so a model
        may choose among operator-preregistered distances and may never mint
        one. The rebind is a single atomic attribute write of a frozen
        dataclass, which is what makes it safe from the 10 Hz tick without a
        lock; it must stay that way.
        """

        policy = self._proximity_context_owner.set_proximity_context(
            context, source=source
        )
        self.reactive_safety_policy = policy
        return self._proximity_context_owner.context.value

    def proximity_snapshot(self) -> dict[str, object]:
        """The proxemics context in force, and where it came from."""

        owner = self._proximity_context_owner
        return {
            "context": owner.context.value,
            "source": owner.last_source,
            "person_stop_m": float(self.reactive_safety_policy.person_stop_m),
            "person_slow_m": float(self.reactive_safety_policy.person_slow_m),
        }

    # ---- END CARD AWARE-1 --------------------------------------------------

    def _realtime_roam(self, action: str, budget_s: float = 0.0) -> str:
        """The hosted ``roam`` tool's door. One door, both actions.

        Wrapped in ``_gate_by_voice`` and ``_watch_under_latch`` at the
        construction site like every other motion door, so an unverified voice
        cannot send the dog off and a refusal under a latch is written down.
        """

        clean = " ".join(str(action).split()).lower() or "start"
        if clean == "stop":
            return self.stop_roam("owner_stopped")
        if clean != "start":
            raise ValueError(f"unknown roam action: {action!r}")
        return self.start_roam(budget_s if budget_s else None)

    # ====================== END CARD ROAM-1 region ========================

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
                self._refuse_under_latch("follow")
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
            self._refuse_under_latch("owner search")
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
            self._refuse_under_latch("navigation")

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
                # Card R24 — the stop-on-resume. This is a navigator MUTATION
                # and the audit found it outside ``_navigation_lock`` while the
                # control thread's ``_step_navigation`` drives the same object
                # under it: a tick landing here could navigate a navigator that
                # was half torn down. ``_command_lock`` (held by our caller) is
                # a different lock protecting a different thing — motion
                # ownership — and ``_step_navigation`` does not take it.
                with self._navigation_lock:
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
            self._refuse_under_latch("navigation")
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
        # Card R4-lite, task_1 — Defect B. Every one of these four branches is a
        # mission lifecycle fact, and three of them are TERMINALS taken before
        # the mission ever moved. "Already at the sidewalk" is an arrival and
        # must say so; "I couldn't reach it" is a failure and must say so.
        if command.stop and mission.status == "arrived":
            with self._lock:
                self._navigation_directive = None
            self._restore_directive_pace()
            message = f"Already at {place}."
            self._log_mission_terminal(
                state="arrived", goal=place, reason=command.note or "already_there"
            )
        elif command.stop and mission.status == "verifying":
            self._request_navigation_terminal_stop()
            message = f"Stopping at {place} and verifying the final position."
        elif command.stop:
            with self._lock:
                self._navigation_directive = None
                self._navigation_detail["enabled"] = False
            self._restore_directive_pace()
            message = f"I couldn't find or safely reach {place}."
            self._log_mission_terminal(
                state="failed", goal=place, reason=command.note or "unreachable"
            )
        else:
            message = f"Navigating to {place}."
            self._mission_block_note = None
            self._mission_block_emit_at_s = None
            self._mission_block_coalesced = 0
            self._log_mission(
                MISSION_LOG_STARTED,
                goal=place,
                state=str(mission.status),
                reason=command.note or "accepted",
                level="info",
                text=message,
            )
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
                self._refuse_under_latch("spatial behavior")
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
                self._refuse_under_latch("spatial behavior")
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
        # Card R15. An orbit cancelled from OUTSIDE — an e-stop, a new command,
        # a manual preempt — is dropped from the narration mark rather than
        # narrated: every one of those paths already reaches the owner through
        # its own channel (the e-stop's own critical fact, or the sentence they
        # just spoke), and a stale mark would otherwise be claimed by whatever
        # spatial behaviour ended next. Clearing it fails toward silence.
        #
        # Card R24: cleared under ``_lock``, the same lock the pump-thread
        # setter and the control-thread claimer take. Folded into the
        # ``_spatial_detail`` section below so the mark and the detail that
        # explains it cannot be observed disagreeing.
        with self._lock:
            self._narratable_orbit = False
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
                self._interrupt_brain(
                    "explicit_stop",
                    "owner explicitly stopped motion",
                    stop_reason="operator_stop",
                )
                self.preempt(
                    "manual",
                    reason="operator_stop",
                    targets=("follow", "navigation", "spatial", "activities"),
                )
                self.stop_motion()
            self._emit("operator", "Motion stopped", "warning")
            return "Stopped"
        if name == "emergency_stop":
            # Card R21. Space and the red button post the identical body to
            # ``/api/action``; ``web_panel.py`` forwards only the action string
            # and is outside this card's OWNS, so both record ``panel``. That
            # still answers live_run_1's open question, which was whether the
            # latch was KEYED or SPOKEN.
            self.emergency_stop(source=SAFETY_SOURCE_PANEL)
            return "Emergency stop latched"
        if name == "clear_emergency_stop":
            return self.clear_emergency_stop(source=SAFETY_SOURCE_PANEL)
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
        # Card R19, mechanism D. FIRST, and outside every early return below: an
        # activity can expire while a different one is running, which is exactly
        # what live_run_1 recorded when "Sit down" and "Take a bow" arrived 54 ms
        # apart. No lock is held here and none is taken until the narration
        # itself, which is the same rule R15's terminals follow.
        self._narrate_expired_activities()
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
                    self._narrate_finished_activity(
                        finished, completed=False, reason=f"{preemptor} took over"
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
                    # Card R15. THE moment "I waved" becomes a true sentence.
                    # The broker answered "started: the paw_wave gesture is
                    # running on the robot's body" seconds ago; this is the
                    # movement actually being over.
                    self._narrate_finished_activity(
                        finished, completed=True, reason="duration_elapsed"
                    )
            return

        record = self.activities.start_ready(self._activity_context(), now=now)
        if record is None:
            return
        #: Card R15. Same rule as ``_step_spatial``: collect the terminal under
        #: the command lock, narrate it after the lock is released.
        aborted: tuple[ActivityRecord, str] | None = None
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
                    cancelled = self.activities.finish(
                        success=False,
                        detail=f"dispatch_cancelled_by_{context.busy_reason or 'runtime'}",
                        now=now,
                    )
                    if cancelled is not None:
                        aborted = (
                            cancelled,
                            (
                                f"{context.busy_reason or 'the runtime'} cancelled "
                                "it before it could start"
                            ),
                        )
                self._activity_complete_at = 0.0
                # Card R15 turned this arm's ``return`` into an ``else``. Same
                # control flow to the byte — the dispatch below is skipped
                # exactly when it was skipped before — but the method now has
                # one exit, which is what lets the narration happen after the
                # command lock is released instead of inside it.
            else:
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
                    failed = self.activities.finish(success=False, detail=str(error), now=now)
                    self._activity_complete_at = 0.0
                    self._emit("activity", f"Action failed: {error}", "error")
                    if failed is not None:
                        aborted = (failed, f"the robot could not run it: {error}")
        if aborted is not None:
            self._narrate_finished_activity(aborted[0], completed=False, reason=aborted[1])

    def _narrate_finished_activity(
        self,
        record: ActivityRecord,
        *,
        completed: bool,
        reason: str,
    ) -> bool:
        """Card R15. Narrate an activity terminal, but only if it was ASKED FOR.

        The claim is one-shot and keyed on the proposal name, so the inline
        ``[emote:...]`` tags the robot authors in its own speech — dozens per
        conversation, none of them announced — end in silence, while the wave
        the owner asked for out loud gets its ending said.

        The label reads ``"paw wave movement"`` rather than the bare skill id:
        the fact template already says the robot started it for the owner, and
        a catalog name on its own ("the sit has now FINISHED") is not a phrase
        anyone would say out loud.
        """

        name = str(record.proposal.name)
        if not self._claim_narratable_activity(name):
            return False
        return self._narrate_activity_terminal(
            activity=f"{name.replace('_', ' ')} movement",
            completed=completed,
            reason=reason,
        )

    def _narrate_expired_activities(self) -> bool:
        """Card R19, mechanism D. An activity that TIMED OUT never gets a tick.

        `broker.executed` does not mean "the robot did it" — live_run_1 headline
        6, and the sharpest single instance in the whole run:

            owner   14:27:38  "Sit down"
            broker  set_pose  →  executed  →  "started: the robot is settling
                                               into the sit pose"
            state.activities.recent id=2  →  {"status": "expired",
                                              "detail": "proposal_ttl_elapsed"}

        The dog said nothing, sat down never, and the owner was told the pose
        had started. R15 gave every activity a second half, but only for the
        endings that pass through :meth:`_step_activities`;
        :meth:`ActivityCoordinator._expire` retires a proposal from inside
        whichever method happened to call it and returns nothing, so an expiry
        is invisible to the runtime's control flow. This polls for it instead.

        Two properties inherited deliberately from R15 rather than reinvented:
        only an activity the OWNER asked for through the hosted surface is
        narrated (``_claim_narratable_activity``, one-shot), and the claim fails
        toward silence. So the bow of q20 — which never produced a broker call
        at all and therefore never carried a mark — stays silent here; its own
        defect is upstream of this one and is named in the status doc.

        Returns whether anything was said, for the tests and for symmetry with
        :meth:`_narrate_activity_terminal`.
        """

        try:
            recent = self.activities.snapshot().get("recent") or ()
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            return False
        spoke = False
        visible: set[int] = set()
        endings: list[tuple[str, str]] = []
        for row in recent:
            try:
                activity_id = int(row["id"])
            except (KeyError, TypeError, ValueError):
                continue
            visible.add(activity_id)
            if activity_id in self._seen_activity_endings:
                continue
            self._seen_activity_endings.add(activity_id)
            if str(row.get("status", "")) != ACTIVITY_STATUS_EXPIRED:
                # Every other ending already has a reporter: R15 wired the
                # completed, preempted and dispatch-cancelled arms through
                # ``_step_activities``. Marking it seen is all this loop owes it.
                continue
            endings.append((str(row.get("name", "")), str(row.get("detail", "")) or "it timed out"))
        # Bounded by construction: ids are unique and monotonic, so one the
        # coordinator's 20-deep ``recent`` window has already evicted can never
        # come back and asking about it again is not a risk worth the memory.
        self._seen_activity_endings &= visible
        for name, detail in endings:
            if not self._claim_narratable_activity(name):
                continue
            spoke = (
                self._narrate_activity_terminal(
                    activity=f"{name.replace('_', ' ')} movement",
                    completed=False,
                    started=False,
                    reason=(
                        f"it waited in the queue until the request timed out ({detail})"
                    ),
                )
                or spoke
            )
        return spoke

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
            self._refuse_under_latch("pose")
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
                self._refuse_under_latch("pose")
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
            self._refuse_under_latch("trajectory")
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
                self._refuse_under_latch("trajectory")
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

    def _submit_microphone_text(self, text: str, *, is_final: bool = True) -> int | None:
        """Microphone entry point: identical policy, but a labelled origin.

        The capture loop and the panel both land in ``submit_voice_text``; once
        inside the voice session the two are indistinguishable. FIX-A/F3 needs
        that distinction in the log, so the mic gets its own thin wrapper
        rather than a mutable "who called last" flag.
        """

        return self.submit_voice_text(text, is_final=is_final, origin=TRANSCRIPT_ORIGIN_MIC)

    def submit_voice_text(
        self,
        text: str,
        *,
        is_final: bool = True,
        origin: str = TRANSCRIPT_ORIGIN_PANEL,
    ) -> int | None:
        """Accept a partial/final transcript without ever executing partial text."""

        if origin not in TRANSCRIPT_ORIGINS:
            raise ValueError(f"unknown transcript origin: {origin!r}")
        if origin == TRANSCRIPT_ORIGIN_REALTIME:
            # Card R1, binding constraint 1. This method is not a thin latch —
            # it is the front door to the entire local agent (planner,
            # conversation model) and to DuplexVoiceSession.submit_text, whose
            # unconditional barge-in interrupt-latches the speaker sink. A
            # hosted transcript arriving here would produce a second reply over
            # the hosted audio, execute grammar-matched commands twice, and mute
            # hosted playback. The hosted lane has its own restricted ingress.
            raise ValueError(
                "hosted realtime transcripts must use submit_realtime_transcript(); "
                "submit_voice_text is the local agent's front door"
            )
        clean = " ".join(str(text).split())
        if not clean:
            raise ValueError("voice text is empty")
        if len(clean) > 2000:
            raise ValueError("voice text is too long")
        # Card R5 (owner directive, 2026-08-18): the hosted lane is the
        # production path and the legacy voice agent is the E2E TEST baseline.
        # VISIBILITY, NOT PROHIBITION — this deliberately does not refuse:
        #   * the microphone/STT capture loop still lands here until the browser
        #     audio gateway (§A) exists, so refusing would mute the only voice
        #     input that works today;
        #   * the e2e suites ARE the legacy path's remaining customer, and their
        #     whole value is that they exercise the unchanged baseline.
        # What was missing was any way to notice. A stack that looks live in the
        # panel while every sentence goes to the local agent is the failure this
        # event exists to make loud, and it is the shape of the incident this
        # card was written for.
        #
        # ``is_final`` only: partial hypotheses arrive per keystroke from the
        # panel's input handler, and one warning per keystroke would flush the
        # 100-slot event deque and bury the very line it is trying to show.
        if is_final and self.realtime_lane is not None:
            lane_active = bool(getattr(self.realtime_lane, "active", False))
            self._emit(
                "realtime",
                "legacy voice path handled a turn while the live lane is up — "
                f"e2e testing only (origin={origin}, "
                f"live session {'active' if lane_active else 'idle'}). "
                "Typed turns should go to the hosted lane; untick nothing in the "
                "panel unless you are running an e2e test.",
                "warning",
                detail={
                    "path": "legacy_voice",
                    "origin": origin,
                    "lane_constructed": True,
                    "lane_active": lane_active,
                },
            )
        if is_final and clean.lower() in EMERGENCY_STOP_PHRASES:
            # Latch the safety boundary before touching the voice coordinator;
            # a committed slow action must not delay an emergency request on
            # the voice session lock.
            self.agent.safety.engage_emergency_stop()
            # Card R21. The microphone origin IS the owner's voice; the panel
            # origin is the text box. Same door, two honest labels — and either
            # way the sentence that latched is recorded verbatim.
            self.emergency_stop(
                source=(
                    SAFETY_SOURCE_VOICE
                    if origin == TRANSCRIPT_ORIGIN_MIC
                    else SAFETY_SOURCE_TYPED
                ),
                phrase=clean,
                rule=SAFETY_RULE_TYPED,
            )
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
            self._remember_turn_transcript(turn_id, clean, origin)
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

    def submit_realtime_transcript(
        self,
        text: str,
        *,
        item_id: str | None = None,
        session_id: str | None = None,
    ) -> RealtimeTranscriptOutcome:
        """The hosted lane's ingress: a safety scan, not a second agent.

        Card R1, binding constraints 1 and 2. Exactly four things happen, in
        this order, and nothing else:

        1. **Normalize punctuation.** A hosted transcriber writes ``"Stop."``
           and every phrase set in this repo is exact-match and unpunctuated.
           Without this line the emergency latch, the closed intents and the
           follow/hold sets all silently stop matching on hosted audio.
        2. **Emergency latch**, the same synchronous actions FIX-A wired at the
           ``submit_voice_text`` fast path: ``engage_emergency_stop`` →
           ``emergency_stop`` → ``barge_in``.
        3. **Closed intents + follow/hold only**, through the SAME runtime
           handlers the router path uses (``_apply_closed_intent`` for the
           executive caps, ``set_behavior`` for follow/hold/come). No planner,
           no grammars, no conversation model, no ``DuplexVoiceSession``, and
           therefore no speech-epoch bump and no barge-in side effects.
        4. **Ledger the owner's side** through the lane's dedicated writer.

        Honest scope note: a spoken stop reaching this method has already
        travelled through the cloud to become text. The panel STOP button, the
        operator stop and the local watchdogs are the cloud-independent
        guarantees, and this card does not touch them.
        """

        found = scan_realtime_transcript(text)
        clean = found.normalized
        # The ledger keeps the owner's sentence as spoken — punctuation and all.
        # Normalization exists to make MATCHING work, not to rewrite the record.
        ledger_text = " ".join(str(text).split())
        if not clean:
            raise ValueError("realtime transcript is empty")
        if len(clean) > 2000:
            raise ValueError("realtime transcript is too long")

        # Card F1-SI — THE SAFETY ASYMMETRY, APPLIED, AND THE ONLY PLACE IT IS.
        #
        # ``voice_gate_decision`` answers the emergency class BEFORE it looks at
        # a verdict, so this call cannot delay, refuse or fail a latch: for
        # ``KIND_EMERGENCY`` it does not compute an embedding, does not consult
        # the profile and does not read the microphone array. Everything else
        # asks the gate whose voice this turn was, and an unverified voice does
        # not get to move the robot.
        #
        # Deliberately placed AFTER the ingress scan and BEFORE the action
        # branches: the scan is what decides whether this is an emergency at
        # all, and it is ingress's alone (R9/R21 law — this card does not touch
        # it, and gating ARMING is how the asymmetry is enforced instead).
        arming = self._voice_arming_for(found.kind)
        if not arming.armed:
            return self._refuse_unverified_voice(found, arming, ledger_text, item_id, session_id)

        reply = ""
        executed = False
        error = ""
        try:
            if found.kind == KIND_EMERGENCY:
                # Latch before anything else can queue: identical actions to
                # runtime.py's voice fast path, on the NORMALIZED text.
                self.agent.safety.engage_emergency_stop()
                # Card R21. The words that latched, verbatim — the SAME string
                # the ledger row keeps, so the ring and the conversation record
                # can be lined up word for word. live_run_1 could not do that:
                # the latch had been evicted and attribution rested on four
                # inferences that still could not rule out a Space-key latch.
                #
                # WHICH RULE fired is read from the ingress's own exported
                # predicate. Nothing here matches anything: the phrase set, the
                # variants and the bounded-gap regex are ingress's alone and
                # this card changes none of them (owner-gated, q34).
                self.emergency_stop(
                    source=SAFETY_SOURCE_VOICE,
                    phrase=ledger_text,
                    rule=(
                        SAFETY_RULE_SPOKEN
                        if matches_spoken_emergency(clean)
                        else SAFETY_RULE_TYPED
                    ),
                )
                self.voice_session.barge_in()
                reply = "Stopping."
                executed = True
            elif found.kind == KIND_CLOSED_INTENT and found.intent is ClosedIntent.COME:
                # COME's cap is a system PlanSketch the agent admits; the hosted
                # lane may not reach PlanIR admission in R1 (that is R4), so it
                # takes the same behaviour door the agent uses without a local
                # planner: set_behavior("follow").
                reply = self.set_behavior("follow")
                executed = True
            elif found.kind == KIND_CLOSED_INTENT and found.intent is not None:
                directive = resolve_cap(found.intent, current_pace=self._pace_cap.scale)
                reply = self._apply_closed_intent(
                    found.intent,
                    directive,
                    source=SAFETY_SOURCE_VOICE,
                    phrase=ledger_text,
                )
                executed = True
            elif found.kind == KIND_FOLLOW:
                reply = self.set_behavior("follow")
                executed = True
            elif found.kind == KIND_HOLD:
                reply = self.set_behavior("stay")
                executed = True
            # ---- CARD ROAM-1: "go explore" is executed LOCALLY ------------
            #
            # APPENDED to the ladder; nothing above moves. These two branches
            # are what make the card's claim true — "roam" is executed by the
            # runtime before the model speaks, exactly like follow and hold,
            # rather than waiting for a hosted function call to come back over
            # the wire. The hosted ``roam`` tool still exists for the sentences
            # the phrase table does not cover, and ``note_ingress`` below is
            # what stops the two becoming a second authority for one utterance.
            #
            # The stop branch is deliberately UNCONDITIONAL on there being a
            # roam to stop: ``stop_roam`` is idempotent, so "stop roaming" said
            # to a robot standing still is a calm confirmation and not an error
            # the model has to narrate as a failure.
            elif found.kind == KIND_ROAM:
                reply = self.start_roam()
                executed = True
            elif found.kind == KIND_ROAM_STOP:
                reply = self.stop_roam("owner_stopped")
                executed = True
            # ---- END CARD ROAM-1 ingress branches -------------------------
        except (RuntimeError, TypeError, ValueError) as failure:
            error = str(failure)
            executed = False
            self._emit("realtime", f"{found.name} refused: {failure}", "warning")

        self._write_realtime_ledger(
            "owner",
            ledger_text,
            item_id=item_id,
            session_id=session_id,
            # Card P2-B. The row is labelled with the class it actually was, so
            # an emergency turn reads ``ungated`` in the record instead of
            # borrowing whatever verdict the last command turn happened to have.
            kind=found.kind,
        )
        # Card P0-B, deliverable 5 — AFFECT ON THE HOSTED LANE.
        #
        # Strictly the ``KIND_NONE`` path: an utterance the deterministic
        # ingress did not claim. Everything above this line is a command the
        # robot has already acted on, and an affect gesture stapled onto a
        # closed intent would be a second authority for one sentence — the exact
        # thing ``note_ingress`` exists to prevent one line below.
        if found.kind == KIND_NONE:
            self._hosted_affect(clean, item_id=item_id, session_id=session_id)
        if executed:
            if found.kind == KIND_EMERGENCY:
                # Card R9. An emergency latch has to be findable in the panel
                # log by someone who does not know which lane latched it, and it
                # has to name the words that did it. ``realtime | stop: Die
                # stop`` at INFO level was neither: it reads as a routing note,
                # and it sits next to a generic ``safety | Emergency stop
                # latched`` that says nothing about where the stop came from.
                self._emit("safety", f"Emergency stop latched by voice: {clean!r}", "error")
            else:
                self._emit("realtime", f"{found.name}: {clean}", "info")
            self._emit_voice_provenance(found.name, arming)
        outcome = RealtimeTranscriptOutcome(
            kind=found.kind,
            name=found.name,
            transcript=clean,
            reply=reply,
            executed=executed,
            item_id=item_id,
            session_id=session_id,
            error=error,
        )
        # Card R3, one authority per utterance: the broker must know that this
        # sentence has already been acted on before the model's tool call for
        # the same sentence arrives.
        broker = self.realtime_broker
        if broker is not None:
            broker.note_ingress(outcome)
        return outcome

    #: Card P0-B. The machine-readable prefix of the affect meta row, so an
    #: auditor (and the owner-model work in phase 2) can find every affect the
    #: hosted lane recorded without matching prose.
    HOSTED_AFFECT_PREFIX = "affect"

    def _hosted_affect(
        self,
        transcript: str,
        *,
        item_id: str | None,
        session_id: str | None,
    ) -> str:
        """Card P0-B, deliverable 5. "I'm feeling sad" on the HOSTED lane.

        THE DEFECT THIS CLOSES. ``agent._detect_explicit_affect`` turns an
        explicit first-person feeling into the persona's ``affect_actions``
        gesture — a comfort bow for sad, a paw wave for happy — and it is
        reachable only from ``submit_voice_text``, the LEGACY lane. Everything
        the owner says to the production companion arrives here instead, so on
        the lane that is actually shipped the sentence has always done nothing
        at all: the model says something kind and the body stays still.

        WHAT IT DOES, AND THE FOUR THINGS IT DOES NOT
        ---------------------------------------------
        On a hosted utterance the ingress did not claim, and only with
        ``hosted_affect: true``:

        1. the SAME reviewed grammar the legacy lane uses decides whether there
           is an explicit affect at all (imported, never re-expressed);
        2. the label must clear ``agent.affect.minimum_confidence`` from
           ``configs/robot.yaml`` — the identical bar
           ``agent._admit_proposal`` applies to a model-proposed one;
        3. an ``affect`` meta row goes into the conversation ledger through the
           lane's own writer, as ``system`` — the role that does not appear in
           the chat pane, because this is a note about the turn and not a thing
           the robot said;
        4. the persona's gesture for that label is PROPOSED to the activity
           coordinator, which owns the timing, the cooldown, the ttl and the
           arbitration, and which refuses under a latched e-stop.

        And it does NOT: reply, speak, set ``executed`` on the outcome (that
        would make the broker drop the model's own tool call for the same
        sentence, and would make ``narration()`` claim a local command ran),
        touch ``_brain_return_to_safe_pose`` (postural recovery is not a social
        gesture and the two must never share a door), or raise. It runs on the
        realtime pump thread; nothing it can hit is worth a dead pump.

        Returns the coordinator's disposition string, or ``""`` when nothing
        happened — for tests and for the caller's benefit, never for the model.

        **Card P2-B extends this helper** (it does not add a second one, per the
        card's binding "Build on P0"): the reading now comes back through
        ``brain.router.lane_affect_from_evidence`` so the bar has one expression
        for every lane, the row carries the speaker's identity LABEL, and the
        admitted reading is appended to the rolling history
        :meth:`affect_history` publishes for P2-A's distiller.
        """

        if not getattr(self.realtime_config, "hosted_affect", False):
            return ""
        try:
            # The grammar call stays at THIS module's boundary deliberately: it
            # is the seam P0-B's tests reach through, and moving it would trade a
            # testable door for a tidier import.
            reading = lane_affect_from_evidence(
                explicit_affect_from_text(transcript),
                minimum_confidence=self._affect_minimum_confidence,
            )
            evidence = reading.evidence
            if evidence is None:
                return ""
            confidence = float(evidence.confidence)
            if not reading.admitted:
                self._emit(
                    "realtime",
                    (
                        f"{self.HOSTED_AFFECT_PREFIX} {evidence.label!r} at "
                        f"{confidence:.2f} is below the configured "
                        f"{self._affect_minimum_confidence:.2f} "
                        f"({reading.verdict}); recorded nothing"
                    ),
                    "info",
                )
                return ""
            skill = str(self.agent.affect_actions.get(evidence.label, "") or "")
            # Card P2-B. WHOSE feeling this was, on the row itself. The label is
            # computed before the row is written so the two cannot disagree, and
            # it is a label: an ``unenrolled`` or ``not_owner`` affect row is
            # still written, still remembered and still answered with a gesture.
            # Identity says who; it does not say whether.
            label = self._speaker_label_for(KIND_NONE)
            # The row goes in BEFORE the proposal, and it goes in whether or not
            # a gesture exists for this persona: what the owner felt is the fact
            # worth keeping, and a personality with no action for "sad" must not
            # also mean no memory of the owner being sad.
            self._write_realtime_ledger(
                "system",
                (
                    f"[{self.HOSTED_AFFECT_PREFIX} {evidence.label}] "
                    f"confidence={confidence:.2f} action={skill or 'none'} "
                    f"transcript={transcript!r} speaker={label.label}"
                ),
                item_id=item_id,
                session_id=session_id,
                kind=KIND_NONE,
            )
            # Card P2-B. The rolling history P2-A's distiller reads. Recorded
            # whether or not a gesture exists, for the same reason the row is.
            self._record_affect(
                label=str(evidence.label),
                confidence=confidence,
                skill=skill,
                transcript=transcript,
                speaker=label,
                session_id=session_id,
                item_id=item_id,
            )
            if not skill:
                return ""
            detail = self.propose_action(
                ActionProposal(
                    kind="skill",
                    name=skill,
                    trigger="inferred_affect",
                    # ``when_safe``, never ``now``: the owner said how they feel,
                    # which is never a reason to interrupt something the body is
                    # already doing for them.
                    timing_preference="when_safe",
                    interruption_request="none",
                    reason=f"hosted transcript affect cue: {evidence.label}",
                )
            )
            self._emit(
                "realtime",
                f"{self.HOSTED_AFFECT_PREFIX} {evidence.label}: {detail}",
                "info",
            )
            return detail
        except Exception as failure:  # noqa: BLE001 - card R22; never kill the pump
            self._emit(
                "realtime",
                (
                    f"{self.HOSTED_AFFECT_PREFIX} handling failed: "
                    f"{type(failure).__name__}: {failure}"
                ),
                "warning",
            )
            return ""

    # ================================================ card P2-B: notice the owner
    #
    # Three surfaces, one region, and the order below is the order they matter
    # in: what a row is CALLED, what the owner FELT, and when the dog should say
    # something first. None of them can refuse anything — that is the card's
    # absolute, and it is why every method here returns a label, a record or an
    # event and not a decision.

    def _speaker_label_for(self, kind: str = VOICE_LABEL_KIND) -> SpeakerLabel:
        """Name the speaker of the turn in progress. Total, and never a gate.

        The reading twin of :meth:`_voice_arming_for`, and deliberately built
        the same way: with no gate object at all — ``mode: text``, a build with
        no audio gateway — it returns the ``unenrolled`` label rather than
        nothing, because a row with no label is exactly the hole this card
        exists to close. A gate that raises is also ``unenrolled``: the label
        may never be the reason a turn fails.
        """

        gate = self.realtime_voice_identity
        if gate is None:
            return unenrolled_label(kind)
        try:
            return gate.label(kind)
        except Exception as error:  # noqa: BLE001 - a label may never end a turn
            self._emit("realtime", f"speaker label unavailable: {error}", "info")
            return speaker_label(kind, None, enrolled=False)

    def _stamp_speaker_label(
        self,
        speaker: str,
        *,
        kind: str = VOICE_LABEL_KIND,
        session_id: str | None = None,
        item_id: str | None = None,
    ) -> SpeakerLabel:
        """Record the identity label of ONE ledger row. Card P2-B, deliverable 1.

        Called from both ledger doors — this class's ``_write_realtime_ledger``
        (the owner's and the system's rows) and ``_RealtimeLedgerMirror`` (the
        robot's) — because "every row" has to mean every row, and the two halves
        of a hosted conversation are written by two different objects.

        The label is stamped on the row's RECORD rather than inside the row's
        TEXT. The transcript is what was said; a verdict spliced into it would
        be the product editing the owner's own words, and the memory tail
        replays those words to the model verbatim on every reconnect. The one
        exception is the affect row, which is the product's own sentence to
        begin with.

        Never raises. A counter that failed to move must not cost a turn.
        """

        label = self._speaker_label_for(kind)
        try:
            row = {
                "at_s": time.monotonic(),
                "speaker": str(speaker),
                "session_id": session_id,
                "item_id": item_id,
                **label.as_dict(),
            }
            with self._lock:
                self._ledger_rows_written += 1
                self._ledger_rows_labelled += 1
                self._speaker_labels.append(row)
        except Exception as error:  # noqa: BLE001 - bookkeeping may never raise
            self._emit("realtime", f"speaker label not recorded: {error}", "info")
        return label

    def speaker_label_rows(self, limit: int = 0) -> list[dict[str, object]]:
        """The identity label of each recent ledger row. Public, read-only."""

        with self._lock:
            rows = list(self._speaker_labels)
        return rows[-limit:] if limit > 0 else rows

    def identity_label_coverage(self) -> dict[str, object]:
        """Rows written vs rows labelled, cumulative. The card's row 3, measured.

        Cumulative counters rather than a scan of the ring: the ring rolls at
        400 rows and "every row carried a verdict" has to stay provable for a
        session that ran all day.
        """

        with self._lock:
            written = self._ledger_rows_written
            labelled = self._ledger_rows_labelled
        return {
            "rows_written": written,
            "rows_labelled": labelled,
            "coverage": 1.0 if written == 0 else labelled / written,
            # Stated, not implied: nothing in this build lets a label refuse.
            "blocking": False,
        }

    # ============ CARD DUPLEX-1 (task_26) — RT-TURNS-1 · MARKED REGION ======
    # AIR-1's handoff, verbatim: "Expose per-turn identity with a WALL stamp …
    # one JSONL row per ledger row … The data already exists in
    # ``_stamp_speaker_label``; what is needed is a wall clock instead of
    # ``time.monotonic()`` and a sink other than a 400-row in-memory ring."
    #
    # Both halves are here, and neither one edits P2-B's stamp: the ring keeps
    # its monotonic ``at_s`` (which is what the rest of the runtime compares
    # against), and the WALL stamp is derived at export time from one paired
    # read of the two clocks. That pairing is exact to the precision of the
    # read and drifts only across a suspend — which is why every row also
    # carries its raw ``monotonic_s``, so a reader who distrusts the join can
    # redo it. Editing the stamp would have been the second region this card
    # opened in a file three other cards are writing to today.
    #
    # WHAT THIS DOES NOT ANSWER, SAID HERE AND NOT ONLY IN THE STATUS DOC.
    # AIR-1's ``score_turns`` reads ``was_robot`` to count "turns credited to
    # the owner that were really the robot coming back through the mic". The
    # runtime cannot decide that: an owner turn overlapping robot playback is
    # what a barge-in IS, so "the robot was speaking" is not evidence, and the
    # only thing that separates the two is acoustic. So ``was_robot`` is
    # ``None`` — never ``False`` — and the row says why. A ``False`` here would
    # make AIR-1's 0/20 row pass for the same vacuous reason its verification
    # caught in ``hosted_spend_usd``.
    def realtime_turn_rows(self, limit: int = 0) -> list[dict[str, object]]:
        """Per-turn identity with a wall stamp. Card DUPLEX-1 / RT-TURNS-1.

        Read-only, never raises, and derived entirely from
        :meth:`speaker_label_rows` — one row in, one row out, in order.
        """

        try:
            rows = self.speaker_label_rows(limit=limit)
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            self._emit("realtime", f"turn export unavailable: {error}", "info")
            return []
        wall_now = time.time()
        monotonic_now = time.monotonic()
        out: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            at_s = row.get("at_s")
            monotonic_s = float(at_s) if isinstance(at_s, (int, float)) else None
            wall = None if monotonic_s is None else wall_now - (monotonic_now - monotonic_s)
            out.append(
                {
                    "wall": None if wall is None else datetime.fromtimestamp(wall, UTC).isoformat(),
                    "monotonic_s": monotonic_s,
                    "session_id": row.get("session_id"),
                    "item_id": row.get("item_id"),
                    "speaker": row.get("speaker"),
                    # Every row in this ring is written by the hosted lane's two
                    # ledger doors. There is no second producer, so the origin is
                    # a fact about the door and not a guess.
                    "origin": TRANSCRIPT_ORIGIN_REALTIME,
                    # See the region header. ``None`` means undecidable here.
                    "was_robot": None,
                    "was_robot_reason": (
                        "undecidable from the runtime: an owner turn during robot "
                        "playback is what a barge-in is; separating self-echo from "
                        "the owner is acoustic (AIR-1 session)"
                    ),
                    "identity": {
                        "verdict": row.get("label"),
                        "code": row.get("code"),
                        "cosine": row.get("score"),
                        "threshold": row.get("threshold"),
                        "enrolled": row.get("enrolled"),
                        "gated": row.get("gated"),
                        "kind": row.get("kind"),
                        # ``doa_deg`` is in AIR-1's schema and this build has no
                        # producer for it (the XVF3800 udev rule is an owner
                        # action). Present and null beats absent: the tool can
                        # then tell "no DoA" from "old file".
                        "doa_deg": None,
                    },
                }
            )
        return out

    def export_realtime_turns(self, path: str | Path | None = None) -> dict[str, object]:
        """Write ``turns.jsonl`` beside the capture. Card DUPLEX-1 / RT-TURNS-1.

        **It has no product caller yet**, and the correction pass says so here
        rather than describing one it does not have: nothing in the panel, the
        driver or the shutdown path invokes it. Today it is called by a human
        at the end of an owner session (``DUPLEX1_STATUS.md`` row OG-4) and by
        ``tests/test_duplex1_rt_turns.py``. It returns what happened rather
        than raising because the eventual caller is a runbook step or an HTTP
        handler, and neither is a place for an exception about a directory.

        With no ``path`` the file lands in the capture session directory — the
        same folder as ``owner.wav`` / ``robot.wav`` / ``index.json``, which is
        what makes an index byte range and a turn row joinable at all.
        """

        import json  # local: the module import block belongs to no one card today

        rows = self.realtime_turn_rows()
        target = None if path is None else Path(path)
        if target is None:
            target = self._realtime_capture_dir()
            if target is not None:
                target = target / "turns.jsonl"
        if target is None:
            return {
                "written": 0,
                "path": None,
                "reason": (
                    "no capture directory: realtime.capture is disabled, so there is "
                    "nowhere beside the WAVs to put this. Pass an explicit path."
                ),
            }
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        except OSError as error:
            self._emit("realtime", f"turn export failed: {error}", "warning")
            return {"written": 0, "path": str(target), "reason": f"{type(error).__name__}: {error}"}
        return {"written": len(rows), "path": str(target), "reason": ""}

    def _realtime_capture_dir(self) -> Path | None:
        """Where the tee is writing this session, from public config only."""

        capture_config = getattr(self.realtime_config, "capture", None)
        if capture_config is None or not getattr(capture_config, "enabled", False):
            return None
        session = self._session_evidence_id
        if not session:
            return None
        try:
            from parcel_robot.realtime.config import resolve_capture_dir

            return Path(resolve_capture_dir(capture_config.dir)) / str(session)
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            return None

    # ============ END CARD DUPLEX-1 region (RT-TURNS-1) =====================

    def _record_affect(
        self,
        *,
        label: str,
        confidence: float,
        skill: str,
        transcript: str,
        speaker: SpeakerLabel,
        session_id: str | None,
        item_id: str | None,
    ) -> None:
        """Append one affect observation to the rolling history. Never raises."""

        try:
            row = {
                "at_s": time.monotonic(),
                "at_iso": datetime.now(UTC).isoformat(timespec="seconds"),
                "label": str(label),
                "confidence": round(float(confidence), 4),
                "action": str(skill),
                "transcript": " ".join(str(transcript).split())[:400],
                "speaker": speaker.label,
                "speaker_code": speaker.code,
                "session_id": session_id,
                "item_id": item_id,
                "lane": "hosted",
            }
            with self._lock:
                self._affect_history.append(row)
        except Exception as error:  # noqa: BLE001 - history may never end a turn
            self._emit("realtime", f"affect history not recorded: {error}", "info")

    def affect_history(self, limit: int = 0) -> list[dict[str, object]]:
        """Every affect this process has observed, newest last. THE PUBLIC API.

        Card P2-B deliverable 2's last clause, and the seam card P2-A's
        distiller consumes: a plain list of plain dicts, copied on the way out,
        with no lock held by the caller and no object from this module in it. A
        distiller that reads this cannot reach the runtime, cannot reach the
        ledger and cannot be broken by a change to either.

        The rows are an INDEX, not the record. The durable copy of every one of
        them is the ``[affect …]`` row in the conversation ledger; if these two
        ever disagree, the ledger is right.
        """

        with self._lock:
            rows = [dict(row) for row in self._affect_history]
        return rows[-limit:] if limit > 0 else rows

    def note_realtime_turn(self, at: float | None = None) -> None:
        """A hosted turn happened. Feeds the owner-event watcher's silence timer.

        Both sides of the conversation call this, which is the point: a greeting
        is due after SILENCE, and a robot that answered a question thirty seconds
        ago has not been silent. Wired at the ledger doors so it cannot drift
        from what was actually said.
        """

        watcher = self.realtime_owner_events
        if watcher is None:
            return
        try:
            watcher.note_turn(at)
        except Exception as error:  # noqa: BLE001 - never end a turn over a timer
            self._emit("realtime", f"owner-event turn note skipped: {error}", "info")

    def owner_presence_sample(
        self, observation: SimObservation | None, now: float
    ) -> OwnerPresence:
        """Adapt WHATEVER owner track this build has into one presence sample.

        THE DROP-IN SEAM (card P1-C). Today the track is the simulator's owner
        body — mocap-grade, confidence 1.0, and honest about being that. When
        P1-C lands ``OwnerTrackV1`` from pixels, the only change here is which
        object is read and which ``source`` the sample carries: the watcher
        downstream takes a boolean, a confidence and a name, and has no opinion
        about where they came from. That is deliberate, and it is why the
        watcher's tests do not need a camera.

        Freshness is part of presence: a stale observation is not a sighting. An
        owner the robot last saw ten seconds ago is an owner it cannot currently
        see, and greeting one would be the confidence-1.0 defect (audit §1) in a
        new place.
        """

        track = getattr(self, "owner_track", None)
        if track is not None:
            # P1-C's OwnerTrackV1, when a later card wires one in. Read
            # defensively: this method is a seam, not a contract consumer.
            confidence = float(getattr(track, "identity_score", 0.0) or 0.0)
            state = str(getattr(track, "state", ""))
            return OwnerPresence(
                present=state in ("confirmed", "tracking") and confidence > 0.0,
                at_s=now,
                confidence=confidence,
                source=OWNER_SOURCE_PIXELS,
            )
        if observation is None or not self._observation_is_fresh(observation, now=now):
            return OwnerPresence(present=False, at_s=now, confidence=0.0, source=OWNER_SOURCE_MOCAP)
        owner = observation.owner
        visible = bool(owner.visible)
        confidence = float(owner.confidence) if math.isfinite(owner.confidence) else 0.0
        return OwnerPresence(
            present=visible,
            at_s=now,
            confidence=max(0.0, min(1.0, confidence)) if visible else 0.0,
            source=OWNER_SOURCE_MOCAP,
        )

    def _step_owner_events(
        self, observation: SimObservation | None, now: float
    ) -> tuple[StateEvent, ...]:
        """One owner-presence tick. Offers at most one event to the whisperer.

        Runs on the whisperer's own 1 Hz tick, from ``_step_whisperer``, so the
        greeting cadence and the state cadence cannot drift apart. Every event
        it produces goes out through ``_whisper`` — the SAME door every other
        robot-initiated fact uses, with the same band, the same dedup, the same
        min-gap and the same per-window cap. There is no second path to the
        model in this card and there was never going to be one: a companion that
        could greet you past the owner's cost knob is a companion the owner
        turns off.

        Returns the events it offered, for the tests and for the panel; the
        whisperer's own decision log holds what actually happened to them.
        """

        watcher = self.realtime_owner_events
        if watcher is None or not watcher.config.enabled:
            return ()
        try:
            events = watcher.observe(self.owner_presence_sample(observation, now))
        except Exception as error:  # noqa: BLE001 - a greeting may never stop the loop
            self._emit("realtime", f"owner-event tick skipped: {error}", "info")
            return ()
        for event in events:
            self._whisper(event)
        return events

    #: Card F1-SI. The one line an armed turn writes about WHOSE VOICE armed it.
    #: Machine-readable on purpose: ``evals/assertions``' ``voice_provenance``
    #: check parses it, and EV-1's whole lesson is that a fact nobody persisted
    #: is a fact no eval can score. The format is pinned by
    #: ``test_every_armed_turn_carries_its_verify_score``.
    VOICE_PROVENANCE_PREFIX = "voice identity armed"

    def _emit_voice_provenance(self, name: str, arming: VoiceArmingDecision) -> None:
        """Record the identity provenance of one turn that actually acted.

        Written for EVERY armed turn, including the emergency latch — where it
        says ``code=safety_never_gated score=none``, which is not a gap in the
        record but the single most important row in it: proof, in the artifact,
        that the stop ran without an identity check standing in front of it.

        Silent when no gate object exists at all (``mode: text``, or a build
        with no audio gateway), so a text-mode session's event stream stays
        byte-identical to what it was before this card.
        """

        if self.realtime_voice_identity is None:
            return
        verdict = arming.verdict
        score = "none" if verdict is None or verdict.score is None else f"{verdict.score:.4f}"
        threshold = (
            f"{self.realtime_voice_identity.threshold:.2f}"
            if verdict is None
            else f"{verdict.threshold:.2f}"
        )
        turn = 0 if verdict is None else verdict.turn
        self._emit(
            "realtime",
            (
                f"{self.VOICE_PROVENANCE_PREFIX} {name!r}: score={score} "
                f"threshold={threshold} code={arming.code} turn={turn}"
            ),
            "info",
        )

    def _voice_arming_for(self, kind: str) -> VoiceArmingDecision:
        """May a turn of class ``kind`` act, given whose voice it was? Card F1-SI.

        Total and never raises. With no gate constructed — ``mode: text``, a
        build with no gateway, a lane that was never built — it returns the
        ``verify_disabled`` decision, which arms: this method may not become a
        second way for a text-mode session to stop working.
        """

        gate = self.realtime_voice_identity
        if gate is None:
            return voice_gate_decision(kind, None)
        try:
            return gate.decide(kind)
        except Exception as error:  # noqa: BLE001 - a broken gate may not eat a stop
            # The emergency class never reaches the gate at all, so a failure
            # here can only be about a command — and a command whose identity
            # check exploded is exactly the one that must not run.
            self._emit("realtime", f"voice identity gate failed: {error}", "warning")
            return VoiceArmingDecision(
                armed=False,
                code="verify_error",
                reason=f"the speaker-identity gate failed and therefore refused to arm: {error}",
                kind=str(kind),
            )

    def _refuse_unverified_voice(
        self,
        found: object,
        arming: VoiceArmingDecision,
        ledger_text: str,
        item_id: str | None,
        session_id: str | None,
    ) -> RealtimeTranscriptOutcome:
        """One turn refused because the voice was not the owner's. Never silent.

        Three things happen and all three are load-bearing:

        1. **The owner's ledger still gets the row.** What was said IS what was
           said; a transcript the product hid because it distrusted the speaker
           would be a record that lies by omission, and the whole F1 story is
           about a record that could not tell two speakers apart.
        2. **The panel gets an event and a counter moves.** Rule 4 of the module
           docstring: a refusal a human cannot see is indistinguishable from a
           robot that has stopped working.
        3. **The first refusal per minute becomes a SPOKEN sentence**, through
           the whisperer's always band — with a hint that explicitly forbids the
           model from claiming other people cannot stop it, because they can.

        The robot does not act, and the hosted model still answers
        conversationally: this card gates the LOCAL command path and does not
        (and from ``audio_gateway`` cannot) stop the provider from replying. See
        ``does_not_prove`` in F1SI_STATUS.md.
        """

        kind = getattr(found, "kind", "")
        name = getattr(found, "name", kind)
        clean = getattr(found, "normalized", ledger_text)
        gate = self.realtime_voice_identity
        speak = True
        if gate is not None:
            speak = gate.note_rejection()
        self._emit(
            "realtime",
            f"voice identity REFUSED to arm {name!r}: {arming.reason}",
            "warning",
        )
        self._write_realtime_ledger(
            "owner",
            ledger_text,
            item_id=item_id,
            session_id=session_id,
            kind=str(kind),
        )
        if speak:
            self._whisper(
                StateEvent(
                    kind=KIND_VOICE_REJECTED,
                    key=f"voice_rejected:{arming.code}",
                    fact=voice_rejection_fact(name, ledger_text),
                    detail={"code": arming.code, "ingress_kind": str(kind)},
                )
            )
        outcome = RealtimeTranscriptOutcome(
            kind=str(kind),
            name=str(name),
            transcript=clean,
            reply="",
            executed=False,
            item_id=item_id,
            session_id=session_id,
            error=arming.reason,
        )
        # The broker still has to learn that this sentence is spoken for. R3's
        # one-authority-per-utterance rule is about the SENTENCE, not about
        # whether it succeeded: without this, the model's tool call for the same
        # words would arrive at a broker that thought nobody had handled them,
        # and the identity gate would have refused the local path while the
        # hosted path walked the dog anyway.
        broker = self.realtime_broker
        if broker is not None:
            broker.note_ingress(outcome)
        return outcome

    def _write_realtime_ledger(
        self,
        speaker: str,
        text: str,
        *,
        item_id: str | None,
        session_id: str | None,
        kind: str = VOICE_LABEL_KIND,
    ) -> None:
        """Both-sides ledger write; never allowed to take down a turn.

        Card R22. The four-type catch this used to carry
        (``AttributeError``/``RuntimeError``/``TypeError``/``ValueError``) is
        the same shape as the driver's and had the same hole: this is called
        from the hosted ingress, which runs on the pump thread, and the whole
        ``sqlite3.Error`` family fell straight through it. Broad now, counted,
        and the chat mirror is inside the firewall too — the mirror is a panel
        convenience and may not be able to end a turn either.

        Card P2-B. ``kind`` is the ingress class the row belongs to, and it is
        here for ONE reason: the emergency class must be labelled ``ungated``
        rather than labelled with a verdict nobody computed. It changes nothing
        else — the stamp happens before the write, cannot fail the write, and
        the row's TEXT is untouched by it.
        """

        self._stamp_speaker_label(
            speaker, kind=kind, session_id=session_id, item_id=item_id
        )
        if str(speaker) in REALTIME_CONVERSATIONAL_SPEAKERS:
            # Only the two CONVERSATIONAL speakers reset the silence timer. A
            # ``[session rollover]`` note is the product talking to itself, and
            # letting it count as company would be a companion whose greeting is
            # postponed by its own bookkeeping.
            self.note_realtime_turn()
        try:
            self.agent.memory.write_realtime_turn(
                session_id=session_id,
                speaker=speaker,
                text=text,
                origin=TRANSCRIPT_ORIGIN_REALTIME,
                provider_item_id=item_id,
            )
        except Exception as error:  # noqa: BLE001 - card R22; a row is never a turn
            self._realtime_ledger_failures += 1
            self._emit(
                "realtime",
                f"ledger write failed: {type(error).__name__}: {error}",
                "warning",
            )
        try:
            self.mirror_realtime_chat(speaker, text)
        except Exception as error:  # noqa: BLE001
            self._realtime_ledger_failures += 1
            self._emit(
                "realtime",
                f"chat mirror failed: {type(error).__name__}: {error}",
                "warning",
            )

    def mirror_realtime_chat(self, speaker: str, text: str) -> None:
        """Show a hosted turn in the panel's chat pane (card R1.6, section C).

        The ledger is the product memory; the chat pane is what the owner sees
        while testing. Only the two conversational speakers are mirrored —
        ``system`` rows are session bookkeeping ("[session rollover] …") and
        putting them in the chat would read as the robot talking. A no-op when
        the lane was never constructed, so flag-off panels are unchanged.
        """

        if self.realtime_lane is None:
            return
        role = {"owner": "user", "robot": "assistant"}.get(str(speaker), "")
        if not role or not str(text).strip():
            return
        self._chat_item(role, str(text))

    def submit_realtime_text(self, text: str) -> dict[str, object]:
        """Panel text box → the LIVE hosted session (card R1.6, section C).

        This is the manual-test path the owner asked for: with
        ``mode: text`` a bare ``./scripts/launch_stack.sh --realtime`` plus a
        browser is a real end-to-end conversation with the hosted model and no
        audio hardware anywhere. The lane opens on the first message, because
        opening a paid session at boot for a panel nobody has typed into yet is
        exactly the cost bug the arming gate exists to prevent.
        """

        lane = self.realtime_lane
        if lane is None:
            raise RuntimeError(
                "the realtime lane is not constructed: configs/realtime.yaml is "
                "absent or realtime.enabled is false"
            )
        clean = " ".join(str(text).split())
        if not clean:
            raise ValueError("realtime text is empty")
        if len(clean) > 2000:
            raise ValueError("realtime text is too long")
        token = self._realtime_panel_token
        if not token and not lane.active:
            raise RuntimeError(
                "the realtime lane has no panel handshake token; the panel "
                "server binds one at startup (fail-closed arming)"
            )
        # Card R4-lite, task_1 — Defect A. This used to be `if not lane.active:
        # lane.open_session(...)`, and reading `active` from this thread is
        # exactly the race that lost a turn: a reconnect makes `active` False
        # for the length of its backoff, so the panel concluded there was no
        # session and opened a competing one. The lane then finished its
        # reconnect, swapped the transport, and the socket holding this turn was
        # orphaned. `ensure_session` takes that decision while holding the lane.
        # The owner typing into the live box IS the per-connection gesture:
        # deliberate, local, and not "the service was reachable".
        before = lane.session_id
        session_id = lane.ensure_session(handshake_token=token, mic_gesture=True)
        if session_id != before:
            self._emit("realtime", f"hosted session opened: {session_id}", "success")
        lane.send_text(clean)
        driver = self.realtime_driver
        if driver is not None and not driver.running:
            driver.start()
        return {
            "accepted": True,
            "session_id": lane.session_id,
            "mode": self.realtime_config.mode,
        }

    def bind_panel_token(self, token: str) -> None:
        """Hand the lane the panel's per-process CSRF token.

        The panel HTTP server mints the token in its own constructor, after the
        runtime exists, so the runtime cannot read it and the arming gate must
        not invent one. This is the one wire between them; without it the lane
        refuses to arm (``no_handshake_token``), which is the correct
        fail-closed answer for a runtime with no panel.
        """

        clean = str(token).strip()
        self._realtime_panel_token = clean or None
        gateway = self.realtime_gateway
        if gateway is not None and clean:
            gateway.bind_token(clean)

    # -------------------------------------------------- realtime tool doors
    def _realtime_transport_factory(self) -> Callable[[], object] | None:
        """The live WebSocket factory, or ``None`` when there is no credential.

        Resolved once at construction and deliberately not retried: a lane
        built without a key must refuse to arm (``no_transport``) rather than
        appear armed and fail at the socket. ``ws_transport`` is imported here
        rather than at module scope because it imports ``websockets``, which is
        an optional dependency — a build without it must still boot a runtime.
        """

        try:
            from parcel_robot.realtime.ws_transport import (
                DEFAULT_API_KEY_ENV,
                websocket_transport_factory,
            )
        except ImportError as error:
            self._emit("realtime", f"live transport unavailable: {error}", "warning")
            return None
        env_name = os.environ.get("PARCEL_REALTIME_KEY_ENV", "").strip() or DEFAULT_API_KEY_ENV
        if not os.environ.get(env_name, "").strip():
            self._emit(
                "realtime",
                f"no realtime credential in ${env_name}; the lane will not arm",
                "warning",
            )
            return None
        return websocket_transport_factory(model=self.realtime_config.model, api_key_env=env_name)

    def _build_realtime_sink(self) -> object | None:
        """The mouth. ``text`` mode discards audio; ``audio`` mode uses the browser.

        A local ``SpeakerSink`` is never chosen here even when one exists: this
        host has no PortAudio output, and R1's playback bridge would raise into
        the pump on the first audio delta. Text mode therefore takes a sink that
        drops bytes and counts them, which is honest — the transcript is the
        product in text mode, and the discarded byte count says so out loud.

        Card R7: ``mode: audio`` no longer raises here. The gateway it builds is
        ARMED BUT IDLE — a websocket endpoint that will authenticate a panel and
        deliver hosted audio to it, with the microphone shut until the owner's
        own per-connection gesture opens it. Constructing it never opens a paid
        session and never touches audio hardware, which is why it is safe to do
        at boot on a host with neither.
        """

        if not self.realtime_config.audio:
            return DiscardSink()
        try:
            from parcel_robot.realtime.audio_gateway import BrowserAudioGateway
        except ImportError as error:
            # ``mode: audio`` names a capability this build does not have. Fail
            # LOUDLY at construction rather than silently downgrading to text:
            # an operator who asked for a microphone and got a text box with no
            # message would discover it mid-conversation. Reachable again only
            # in a build without the optional ``websockets`` dependency.
            raise RuntimeError(
                "realtime.mode is 'audio' but the browser audio gateway is not "
                "available in this build; set mode: text in "
                f"{self.realtime_config.source} to use the panel text path ({error})"
            ) from None
        # Card R17. The one wiring line the config-gated audio tee needs: the
        # loader owns the schema and the gateway owns the tee, and neither can
        # reach the other without this. Default OFF — an absent or disabled
        # ``capture:`` block passes ``None`` and every audio path below is
        # byte-for-byte what R7 shipped.
        capture = None
        capture_config = getattr(self.realtime_config, "capture", None)
        if capture_config is not None and getattr(capture_config, "enabled", False):
            from parcel_robot.realtime.audio_gateway import SessionAudioCapture
            from parcel_robot.realtime.config import resolve_capture_dir

            capture = SessionAudioCapture(
                root=resolve_capture_dir(capture_config.dir),
                # Card EV-1. The evidence log was armed first and already minted
                # this session's id; handing it over is what puts `events.jsonl`
                # in the SAME folder as `owner.wav`, so an index byte range and
                # an event row cannot be about two different sessions. Empty
                # (evidence disabled) falls back to the tee minting its own.
                session_id=self._session_evidence_id or None,
                max_minutes=capture_config.max_minutes,
                owner_gap_s=capture_config.owner_gap_s,
                on_event=lambda message: self._emit("realtime", message, "info"),
            )
        identity = self._build_voice_identity_gate()
        self.realtime_voice_identity = identity
        # ---- CARD HW-4 (task_37) — WHICH EAR: A CHROME TAB, OR THE XVF3800? -
        # The ONE branch this card adds to the runtime. `audio.gateway` is
        # absent from the SHA-locked base and resolves to `browser`, so with no
        # profile the `else` arm below constructs byte-for-byte what this method
        # constructed before this card existed — same class, same five keyword
        # arguments, same order. That identity is asserted through THIS method
        # in `tests/test_hw4_array_gateway.py`, not through a stub.
        #
        # A typo or an unknown value RAISES here, at boot, with the key named:
        # the `audio` subtree is exempt from `config.check_overlay_keys` (the
        # loader stops descending at an exempt parent), so this call is the only
        # thing between `gatewayy: array` and a robot that silently kept the
        # browser ear while the file on disk said otherwise.
        from parcel_robot.realtime.audio_gateway import (
            AUDIO_GATEWAY_ARRAY,
            resolve_audio_gateway_selection,
        )

        gateway_kind, gateway_device = resolve_audio_gateway_selection(self.store.section("audio"))
        if gateway_kind == AUDIO_GATEWAY_ARRAY:
            # Constructing this opens NO audio device and starting it opens no
            # audio device either: the capture stream opens on the owner's mic
            # gesture and the playback stream on the first hosted chunk. A host
            # with no array therefore still boots, says so loudly through
            # `on_event`, and refuses — with a typed `ArrayDeviceError` naming
            # the udev rule — the moment anything asks it to listen. It never
            # falls back to the browser.
            from parcel_robot.realtime.audio_gateway import ArrayAudioGateway

            gateway: object = ArrayAudioGateway(
                on_audio=self._realtime_owner_audio,
                on_mic=self._realtime_mic_gesture,
                on_event=lambda message: self._emit("realtime", message, "info"),
                device=gateway_device,
                capture=capture,
                voice_identity=identity,
            )
        else:
            gateway = BrowserAudioGateway(
                on_audio=self._realtime_owner_audio,
                on_mic=self._realtime_mic_gesture,
                on_event=lambda message: self._emit("realtime", message, "info"),
                capture=capture,
                voice_identity=identity,
            )
        # ---- END CARD HW-4 --------------------------------------------------
        self.realtime_gateway = gateway
        if self._realtime_panel_token:
            gateway.bind_token(self._realtime_panel_token)
        gateway.start()
        return BrowserSink(gateway)

    def _build_voice_identity_gate(self) -> VoiceIdentityGate | None:
        """Card F1-SI. The speaker-identity gate, or ``None``, and why.

        THE THREE OUTCOMES, AND WHY NONE OF THEM IS AN EXCEPTION THE OWNER EATS
        ----------------------------------------------------------------------
        1. **The block is off** (``voice_identity.enabled: false``) ⇒ ``None``.
           An operator who wrote that down gets exactly what they asked for.
        2. **No enrolled profile** ⇒ a gate with no profile. It reports
           ``verify_disabled`` in the snapshot, in a boot event, and in every
           arming decision, and the runtime behaves exactly as it did before
           this card. This is the common case today: no owner audio exists on
           this host yet (``bench_doa.md``'s material caveat), so the shipped
           default state of the feature is on-and-inert-and-loud.
        3. **A profile that exists and cannot be trusted, or a model that
           cannot be loaded** ⇒ the reason is emitted at WARNING and the gate is
           built WITHOUT an embedder, which refuses nothing and arms nothing —
           i.e. it degrades to (2) *with the failure printed*, rather than
           taking a household's robot down at boot because a 40 MB model file
           moved. The one thing it must never do is degrade SILENTLY, and the
           snapshot's ``reason`` is what stops that.
        """

        from parcel_robot.paths import resolve_asset
        from parcel_robot.realtime.protocol import PCM16_SAMPLE_RATE_HZ
        from parcel_robot.realtime.voice_identity import (
            DEFAULT_MODEL_RELATIVE,
            SherpaSpeakerEmbedder,
            UsbDoaReader,
            VoiceIdentityError,
            default_profile_path,
            load_owner_profile,
        )

        settings = getattr(self.realtime_config, "voice_identity", None)
        if settings is None or not getattr(settings, "enabled", False):
            return None

        profile_path = settings.profile or default_profile_path(
            self.realtime_config.source if self.realtime_config.present else None
        )
        profile = None
        embedder = None
        try:
            profile = load_owner_profile(profile_path)
        except VoiceIdentityError as error:
            self._emit("realtime", f"voice identity: {error}", "warning")
        if profile is not None:
            model_path = Path(settings.model) if settings.model else None
            if model_path is None:
                try:
                    model_path = resolve_asset(*DEFAULT_MODEL_RELATIVE, kind="file")
                except FileNotFoundError:
                    model_path = Path(*DEFAULT_MODEL_RELATIVE)
            try:
                embedder = SherpaSpeakerEmbedder(model_path)
            except VoiceIdentityError as error:
                self._emit(
                    "realtime",
                    "voice identity: an owner profile is enrolled but the embedding "
                    f"model could not be loaded, so speaker verification is OFF ({error})",
                    "warning",
                )
                profile = None
        doa = UsbDoaReader() if getattr(settings, "doa", False) else None
        gate = VoiceIdentityGate(
            embedder=embedder,
            profile=profile,
            threshold=settings.threshold,
            sample_rate_hz=PCM16_SAMPLE_RATE_HZ,
            # The SAME gap the R17 tee cuts owner segments on, read from the
            # capture block so one number describes both segmentations even when
            # an operator has tuned it.
            turn_gap_s=getattr(self.realtime_config.capture, "owner_gap_s", 0.75),
            min_utterance_s=settings.min_utterance_s,
            budget_ms=settings.budget_ms,
            narration_interval_s=settings.narration_interval_s,
            doa=doa,
            rejected_sector=settings.rejected_sector,
            on_event=lambda message: self._emit("realtime", message, "info"),
        )
        self._emit(
            "realtime",
            (
                "voice identity: speaker verification ARMED at threshold "
                f"{settings.threshold:.2f} against {profile.utterances} enrolled "
                "utterance(s); the emergency latch is NOT identity-gated"
            )
            if gate.enabled
            else (
                "voice identity: NO ENROLLED OWNER VOICE PROFILE — speaker "
                "verification is OFF and any voice can arm a command, exactly as "
                f"before card F1-SI. Expected profile at {profile_path}."
            ),
            "info" if gate.enabled else "warning",
        )
        return gate

    def _realtime_shares_local_speaker(self) -> bool:
        """Does the lane's sink write to the SAME queue local speech does?

        R1.5's sink-ownership law, evaluated instead of assumed. ``BrowserSink``
        writes to the browser and ``DiscardSink`` writes nowhere; neither can
        interleave with ``DuplexVoiceSession``'s PortAudio queue, so neither is
        a reason for the lane to refuse to speak. Only a lane holding the local
        speaker contends, and then the local session's own busy flag is the
        answer. See the comment at the ``duplex_output_active=`` wiring.

        Fail-closed in the direction the law points: anything this method does
        not RECOGNISE as a non-speaker sink (a future build's own sink, or a
        lane still resolving one through ``sink_factory``) falls through to the
        pre-R7 behaviour and reports the duplex session's state, so a new sink
        has to be added here deliberately rather than inheriting a free pass.
        """

        lane = self.realtime_lane
        sink = None if lane is None else getattr(lane, "_sink", None)
        if isinstance(sink, (BrowserSink, DiscardSink)):
            return False
        return getattr(self.voice_session, "_active_output", None) is not None

    def _realtime_mic_gesture(self, open_: bool) -> None:
        """The owner pressed (or released) the microphone in their browser.

        Opening the microphone is what opens the hosted session in ``mode:
        audio`` — exactly as typing into the live box is what opens it in
        ``mode: text``. Nothing here is allowed to succeed quietly: if the lane
        refuses to arm (no panel token, no credential, budget spent) the
        exception propagates back through the gateway, the microphone stays
        shut, and the browser is told the reason.

        Closing the microphone deliberately does NOT close the session. The
        session is the conversation; the microphone is whether the owner is
        talking into it, and hanging up the provider on a released button would
        throw away the context the next sentence is about to need.
        """

        lane = self.realtime_lane
        if lane is None:
            raise RuntimeError(
                "the realtime lane is not constructed: configs/realtime.yaml is "
                "absent or realtime.enabled is false"
            )
        if not open_:
            self._emit("realtime", "microphone closed; the session stays open", "info")
            return
        token = self._realtime_panel_token
        if not token and not lane.active:
            raise RuntimeError(
                "the realtime lane has no panel handshake token; the panel "
                "server binds one at startup (fail-closed arming)"
            )
        before = lane.session_id
        session_id = lane.ensure_session(handshake_token=token, mic_gesture=True)
        if session_id != before:
            self._emit("realtime", f"hosted session opened: {session_id}", "success")
        driver = self.realtime_driver
        if driver is not None and not driver.running:
            driver.start()

    # ------------------------------------------------- card R22: the pump alarm
    def _realtime_pump_alarm(
        self, alarm: str, message: str, detail: Mapping[str, object]
    ) -> None:
        """The pump died, or restarted itself. Card R22, work item 2.

        THE FINDING THIS ANSWERS
        ------------------------
        AUDIT_FULL_FABLE §Safety-1: the pump thread died silently, "while the
        mic stays open and nothing alarms". The card is explicit that a
        ``driver.failures`` entry is not enough, and it is right — that list is
        read by nobody, and the 100-slot event ring it echoes into is the ring
        R21 already proved evicts a latch in fourteen seconds.

        So a death lands in all four places a person or a script might look:

        * **the safety ring** (``_log_safety``) — the same list the panel
          renders under "Safety log", never evicted by chatter, and from EV-1
          also written to the session evidence log on disk;
        * **its own bounded list** here, so ``/api/state`` can show the history
          without competing for the 24 safety slots;
        * **the event ring**, via ``_log_safety``'s own emit below, which is
          what makes it visible in the panel's ordinary event stream too;
        * **the driver's snapshot**, which is where ``alive`` and the heartbeat
          age live.

        Nothing here restarts anything. Revival is the driver's own, bounded,
        and this hook is told about it after the fact — a runtime that reached
        into the driver from the alarm handler would race the very thread that
        is calling it.

        Never raises. It is called from inside the dying pump thread.
        """

        try:
            kind = (
                SAFETY_LOG_PUMP_REVIVED
                if str(alarm) == DRIVER_ALARM_REVIVED
                else SAFETY_LOG_PUMP_DIED
            )
            row = {
                "kind": kind,
                "alarm": str(alarm),
                "text": str(message),
                "detail": dict(detail),
                "timestamp": datetime.now(UTC).isoformat(),
            }
            with self._lock:
                self._realtime_pump_alarms.append(row)
            self._log_safety(
                kind,
                source=SAFETY_SOURCE_REALTIME_PUMP,
                level="error" if kind == SAFETY_LOG_PUMP_DIED else "warning",
                text=str(message),
                detail=dict(detail),
            )
            self._emit(
                "realtime",
                str(message),
                "error" if kind == SAFETY_LOG_PUMP_DIED else "warning",
                detail=dict(detail),
            )
        except Exception:  # noqa: BLE001 - an alarm that raises is a second death
            return

    def _realtime_pump_snapshot(self) -> dict[str, object]:
        """The one block the panel reads to answer "is the pump alive?".

        Card R22, work item 2. Deliberately a flat, driver-shape-free block: the
        browser must be able to raise this alarm without knowing what a
        ``RealtimeDriver`` is, and a future replacement for the driver must be
        able to fill the same four fields.

        ``armed`` is the honest third state. A pump that was never started is
        not dead — before the owner's first gesture there is no session to pump
        — and a panel that shouted about that would be the boy who cried wolf
        for the whole of every session's first minute.
        """

        driver = self.realtime_driver
        if driver is None:
            return {
                "armed": False,
                "alive": False,
                "running": False,
                "heartbeat_age_s": None,
                "deaths": 0,
                "death_reason": None,
                "revivals": 0,
                "revivals_exhausted": False,
                "alarms": [],
            }
        with self._lock:
            alarms = [dict(row) for row in self._realtime_pump_alarms]
        return {
            # "Somebody started this pump and never stopped it" — the only state
            # in which `alive is False` is an incident rather than a fact.
            "armed": driver.started_at is not None and driver.stopped_reason is None,
            "alive": driver.alive,
            "running": driver.running,
            "heartbeat_age_s": driver.heartbeat_age_s(),
            "deaths": driver.deaths,
            "death_reason": driver.death_reason,
            "revivals": driver.revivals,
            "revivals_exhausted": driver.revivals_exhausted,
            "alarms": alarms,
        }

    def _watch_realtime_pump(self) -> None:
        """One liveness question per health period. Card R22, work item 2.

        ``RealtimeDriver._die`` fires from inside the dying thread and covers
        every death this process can observe from the inside. This covers the
        ones it cannot — a thread the interpreter took down, an alarm hook that
        itself killed the thread, a ``_die`` that never ran. ``ensure_alive()``
        alarms at most once per undetected death, so calling it on a loop is
        safe.

        It deliberately does NOT restart the driver. Bounded revival belongs to
        the driver (which knows how many attempts it has spent); a supervisor
        that restarted it here would have no budget and would hot-loop against
        a genuinely broken lane, which is the failure mode work item 3's bound
        exists to prevent.
        """

        driver = self.realtime_driver
        if driver is None:
            return
        try:
            driver.ensure_alive()
        except Exception as error:  # noqa: BLE001 - a health probe never raises
            self._emit("realtime", f"pump liveness probe failed: {error}", "warning")

    def _retain_realtime_frame(self, type_name: str, fields: Mapping[str, object]) -> None:
        """One retained provider frame → the session evidence log. Card R22 #5.

        EV-1's open risk §10.3, closed. That card taught the codec to KEEP these
        payloads — the 88 ASR frames of ``live_run_1``, the only surviving trace
        of how the owner's words were transcribed, and the run whose two most
        expensive findings are both about transcription — and then had nowhere
        to put them, because its card scoped it to ``protocol.py`` and listed
        ``lane.py`` under MUST NOT TOUCH.

        The sink is ``_offer_evidence`` and explicitly NOT ``_emit``: EV-1 wrote
        down the reason and it still holds. 44 deltas per session through the
        panel's 100-slot ring would evict, in under a minute, exactly the rows
        the ring exists to keep — which is the resource EV-1 was built to
        relieve. ``_offer_evidence`` is non-blocking, drops rather than waits,
        and is a no-op when the log is not armed.

        Never raises; the lane counts a failure and carries on.
        """

        self._offer_evidence(
            STREAM_EVENT,
            {
                "kind": "retained_event",
                "type": str(type_name),
                "fields": dict(fields),
                "session_id": (
                    None if self.realtime_lane is None else self.realtime_lane.session_id
                ),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def _realtime_idle_closed(self, idle_for: float) -> None:
        """The lane hung up on an idle session. Card R16, work item 3.

        Two things have to happen here and neither of them is "re-open it".

        **The panel says so** — one event in the ring that ``/api/state``
        renders, because a session ending is a fact about the product the owner
        is entitled to find later. (The ledger row is the lane's own; this is
        the line a person watching the panel sees.)

        **The browser's microphone goes back to un-armed**, when there is one.
        The gateway keeps running, keeps its token and keeps accepting
        connections; only the ear closes. That is the whole of "the gateway stays
        armed but idle": a page that kept saying "🔴 Listening" would be streaming
        PCM into a session that no longer exists and the owner would be talking
        to nobody, whereas an un-armed button re-opens the session on ONE click
        through exactly the path a first-ever gesture takes
        (``_realtime_mic_gesture`` → ``ensure_session``).

        Nothing here touches the driver: the driver stopped itself when ``tick``
        told it the lane had closed, and the same gesture that re-opens the
        session restarts it.
        """

        self._emit(
            "realtime",
            f"hosted session hung up after {idle_for:.0f}s with nobody talking; "
            "the next thing you say opens a fresh one with the same memory",
            "info",
        )
        gateway = self.realtime_gateway
        if gateway is None:
            return
        try:
            gateway.close_mic("the session hung up after a long silence; click to start again")
        except (OSError, RuntimeError, TypeError, ValueError) as error:  # pragma: no cover
            # A gateway that will not close its microphone must not undo the
            # hang-up: the session is already gone either way.
            self._emit("realtime", f"microphone not closed after hang-up: {error}", "warning")

    def _realtime_owner_audio(self, pcm: bytes) -> None:
        """Owner microphone frames arriving from the browser, going up."""

        lane = self.realtime_lane
        if lane is None or not lane.active:
            return
        try:
            lane.send_audio(pcm)
        except (RealtimeLaneError, RuntimeError) as error:
            self._emit("realtime", f"microphone frame dropped: {error}", "warning")

    def _realtime_status_digest(self) -> dict[str, object]:
        """What ``get_status`` tells the model. Small, factual, no free text.

        Card R18 adds ``scene``. live_run_1 root-caused F3 as a missing tool —
        the model had no route from "what do you see around you" to anything the
        robot could sense — and the card's answer is deliberately NOT an eighth
        tool: the robot's own current state and the robot's own surroundings are
        the same question asked twice, and one tool that answers both is one
        fewer thing for the model to choose wrong. The tool DESCRIPTION says so
        (``build_tool_specs``), which is the half that makes the model reach for
        it, and the result carries the sensor list and the no-camera note, which
        is the half that keeps the answer honest.
        """

        arbitration = self.arbiter.snapshot()
        battery = self._battery_snapshot()
        with self._lock:
            navigation = dict(self._navigation_detail)
        running = self.activities.running()
        return {
            "emergency_stopped": bool(arbitration["emergency_stopped"]),
            # Card R21. ``emergency_stopped: true`` is a flag, and live_run_1 is
            # what a flag buys: the model held that flag for 84 seconds and
            # mentioned it once, by accident, as a mood ("I'm feeling playful …
            # and right now, I can't move"). This block says the same thing in
            # words the answer can be built out of — how long, from which door,
            # and what has to happen before the robot moves again — so a status
            # question asked under a latch cannot be answered without it.
            "emergency_stop": self._safety_latch_state(),
            "active_source": arbitration["active_source"],
            "battery_percent": round(float(battery.percent), 1),
            "battery_state": battery.state,
            "navigating": bool(navigation.get("enabled")),
            "navigation_state": str(navigation.get("state", "idle")),
            "following": bool(self.follow.enabled),
            "gesture_running": None if running is None else running.proposal.name,
            "personality": self._personality,
            "scene": self._realtime_scene_report(),
        }

    def _realtime_scene_report(self) -> dict[str, object]:
        """Card R18 — the surroundings, from perception only, right now.

        Card C-3 item 4: under ``learned_map`` the answer describes what the dog
        has actually detected, with the uncertainty each place has earned. The
        map is passed IN rather than looked up inside ``scene_report``, which
        stays pure and therefore stays testable against hand-built inputs.
        """

        with self._lock:
            observation = self._observation
        return scene_report(observation, learned_map=self._scene_learned_map())

    def _scene_learned_map(self) -> object | None:
        """The map ``scene_report`` should describe, or ``None`` for the oracle."""

        try:
            from parcel_robot.perception_source.selection import (
                active_learned_map,
                active_semantic_source,
            )
        except ImportError:  # pragma: no cover — frozen bundle path
            return None
        if not active_semantic_source().drives_from_learned_map:
            return None
        return active_learned_map()

    def _realtime_scene_lines(self) -> tuple[str, ...]:
        """The same facts as DI lines, for the session boundary.

        Read through the SAME :func:`scene_report` the tool answer uses, so the
        boundary block and the tool answer can never describe two different
        worlds. Never raises: :class:`DeveloperContext` treats this as a sensor,
        and a sensor that fails must render no block rather than a made-up one.
        """

        report = self._realtime_scene_report()
        if not report.get("observed"):
            return ()
        return scene_fact_lines(report)

    def _realtime_recall(self, query: str) -> str:
        """A deterministic read of what was actually said. No model, no clock.

        CARD R18, WORK ITEM 2 — and the three things that were wrong with the
        version this replaces are stated in R18_STATUS §0.2, measured against the
        owner's real 2,882-row store:

        1. it read ``realtime_turns()``, whose ``speaker IS NOT NULL`` filter is
           load-bearing for history injection and catastrophic for recall —
           2,618 of the owner's 2,882 conversation rows are local-origin and
           were invisible to it;
        2. it matched the WHOLE query as a substring, so "what do you remember
           about the willow?" could not find the row that says "willow" (R19
           scene C, live);
        3. it returned ``"speaker: content"`` with no instant attached, so even
           a hit could not be said with provenance.

        The retrieval and the provenance rendering live in
        :mod:`parcel_robot.memory`, beside the rows, and are unit-tested against
        an in-memory store. This method is the wiring plus the sentence.
        """

        # Naive local, deliberately: the DI's clock on this same runtime is
        # ``datetime.now`` and recall's provenance words have to agree with it,
        # or the robot says "yesterday" about two different days in one turn.
        recalled = self.agent.memory.recall(query, now=datetime.now())  # noqa: DTZ005
        if recalled:
            return " | ".join(item.as_sentence() for item in recalled)
        # Fall back to the tiered store's own deterministic retrieval, which is
        # where turns go once they age out of the verbatim window. Unchanged
        # from before this card, including having no instant to attach: these
        # are distilled summaries, not turns, and dating a summary would be an
        # invented provenance rather than a recovered one.
        memory = self.prompting.memory
        if memory is not None:
            retrieval = memory.retrieve(query)
            hits = [str(summary.text) for summary in getattr(retrieval, "summaries", ())]
            if hits:
                return " | ".join(f"from an earlier summary: {text}" for text in hits[-5:])
        return ""

    # ------------------------------------------------- card P2-A: owner facts
    #
    # Four methods, all of them wiring. Every decision they could make is made
    # somewhere else on purpose: the privacy verdict arrives already decided
    # (the broker calls ``owner_model.policy``), the consent filter lives in
    # ``owner_model.notes``, and the store lives in ``memory.ConversationMemory``
    # behind card R27's isolation guard. This class supplies the seam and
    # nothing else — which is what keeps "what may the robot keep about me"
    # answerable without reading ``runtime.py``.
    def _realtime_remember_fact(
        self, key: str, fact: str, decision: object
    ) -> dict[str, object]:
        """Write one owner-stated fact with the policy's verdict attached.

        ``owner_stated`` and not ``model_proposed``: this path only ever runs
        because the owner said something and the model relayed it. The
        distiller's inferences come through
        :func:`~parcel_robot.owner_model.distiller.distil_session` and are
        stamped the other way, so the table can always answer "did I say this,
        or did you work it out?".

        Never raises into the broker: a failed write comes back as
        ``{"id": 0}``, the broker reports the fact was not stored, and the model
        says so. A robot that says it remembered something it did not is the
        precise failure this whole card is arranged against.
        """

        consent = str(getattr(decision, "consent", CONSENT_PENDING))
        row_id = self.agent.memory.add_owner_fact(
            key=str(key),
            value=str(fact),
            provenance=FACT_OWNER_STATED,
            consent=consent,
            category=str(getattr(decision, "category", "")) or None,
            reason=str(getattr(decision, "reason", "")) or None,
            session_id=getattr(self.realtime_lane, "session_id", None),
        )
        return {"id": row_id, "consent": consent}

    def _realtime_forget_fact(self, key: str) -> dict[str, object]:
        """"Don't remember that." Soft-deletes; reports how many rows moved."""

        return {"forgotten": self.agent.memory.forget_owner_fact(str(key))}

    def _realtime_known_facts(self) -> tuple[str, ...]:
        """The consented, live facts as sentences — the answer, already rendered.

        The broker never sees a row, only these lines, so the consent filter
        cannot be skipped on the way out. Applied twice deliberately:
        ``consent=CONSENT_GRANTED`` in the query and again inside
        :func:`~parcel_robot.owner_model.notes.known_facts_answer`, because a
        boundary with one enforcement point is one refactor away from none.
        """

        try:
            rows = self.agent.memory.owner_facts(consent=CONSENT_GRANTED)
        except (RuntimeError, TypeError, ValueError):
            return ()
        return known_facts_answer(rows)

    def _realtime_owner_notes(self) -> tuple[str, ...]:
        """The DI's ``owner_notes`` block, which has never had anything in it.

        ``realtime/prompting.py`` has rendered this block since the prompt plane
        was built and ``runtime.py`` has never passed a provider, so the only
        thing that ever filled it was the 25 sealed corpus fixtures. This is the
        provider.

        Returning ``()`` renders NOTHING — not a header, not "no notes" — which
        is what keeps ``PINNED_DI_DIGEST`` and those fixtures valid: a store with
        no consented facts produces byte-identical DI text to before this card.
        ``DeveloperContext`` treats a provider that raises as absent, so a
        broken store costs the block and never the session.
        """

        try:
            rows = self.agent.memory.owner_facts(consent=CONSENT_GRANTED)
        except (RuntimeError, TypeError, ValueError):
            return ()
        return owner_notes_from_facts(rows, limit=MAX_OWNER_NOTES)

    # =====================================================================
    # CARD OT-2 — WHO MAY WRITE A DURABLE OWNER FACT.  (NEW REGION, DW-3)
    #
    # Sits immediately after P2-A's four doors because it is the missing half
    # of them, and it touches none of their bodies: this region WRAPS
    # ``_realtime_remember_fact`` rather than editing it, so P2-A's write path
    # is still one readable method and the authorization rule is still one
    # readable module (``owner_model.principal``).
    #
    # THE HOLE. P2-A asked what the robot may keep. It never asked who is
    # asking. ``remember_fact`` arrives from the hosted lane, the deterministic
    # policy rules on the TEXT, and a row lands ``granted`` — whether the
    # sentence came from the enrolled owner, from a house guest, from a voice
    # the verifier ran on and could not identify, or from a television. P2-B
    # made that distinction visible and deliberately gave it no authority
    # ("identity is a LABEL, not a gate"), which is right about ARMING: a robot
    # that will not stop for a stranger is a worse robot.
    #
    # Here, and only here, the label acquires exactly one power: an unverified
    # voice may talk, may interrupt, may STOP the dog — and may not silently
    # create a durable consented belief about its owner. Nothing is refused.
    # The fact still lands, as ``pending``, and the model is told it landed
    # pending and why. Ask-over-refuse, applied to memory.
    #
    # AND THE OTHER HALF: ``memory.set_owner_fact_consent`` had NO product
    # caller before this card — the "yes, remember that" the ``pending`` row
    # exists for was reachable from one test and nothing else. ``confirm_fact``
    # below is that caller, and it is a SEPARATE door on purpose: repeating
    # ``remember_fact`` is a repetition, not a confirmation, and a product that
    # treats the second attempt as consent has no consent step at all.
    # =====================================================================

    def _ot2_memory_principal(self) -> Any:
        """WHO is asking, as a typed value. Total; never raises; never a gate.

        Reads P2-B's ``_speaker_label_for`` — the same label the ledger row for
        this turn will carry — so "the robot wrote it down as unconfirmed" and
        "the row says the voice was unverified" can never disagree. A build
        with no gate at all resolves to ``unenrolled``, which is the truth
        about this host today and which DOES grant: see
        ``owner_model.principal.GRANTING_LABELS`` for why that is a decision
        rather than an oversight.
        """

        from parcel_robot.owner_model.principal import (
            CHANNEL_VOICE,
            principal_from_speaker_label,
        )

        try:
            stamp = self._speaker_label_for()
            return principal_from_speaker_label(
                str(getattr(stamp, "label", "") or ""),
                channel=CHANNEL_VOICE,
                confidence=float(getattr(stamp, "score", 0.0) or 0.0),
            )
        except Exception as error:  # noqa: BLE001 - a principal may never end a turn
            self._emit("realtime", f"memory principal unavailable: {error}", "info")
            return principal_from_speaker_label("unverified", channel=CHANNEL_VOICE)

    def _ot2_remember_fact(self, key: str, fact: str, decision: object) -> dict[str, object]:
        """P2-A's write door, with the principal applied at the last moment.

        THE LAST POINT BEFORE THE STORE, deliberately. The alternative — asking
        the broker to consult the principal before calling the door — puts the
        rule where a future second caller can route around it. Here, every path
        that reaches ``add_owner_fact`` through ``ToolDoors`` has already been
        through :func:`~parcel_robot.owner_model.principal.admit_consent`, and
        that function can only ever move a verdict toward "not yet".

        The downgrade is never silent. It goes back to the model in the result
        (``consent_downgraded``, the principal, and a sentence saying what
        happened), it is counted, and it is emitted on the ``realtime`` channel
        — three places, because a memory quietly not kept is as bad a product
        as a memory quietly kept.
        """

        from parcel_robot.owner_model.principal import admit_consent

        principal = self._ot2_memory_principal()
        requested = str(getattr(decision, "consent", CONSENT_PENDING))
        admission = admit_consent(principal, requested)
        changes: dict[str, object] = {}
        if admission.downgraded:
            changes["consent"] = admission.consent
        if not principal.may_grant_consent:
            # WHO SPOKE, ON THE DURABLE ROW (Fable, OT-2 item 6). The principal
            # decides the row's consent and, before this, left no trace on the
            # row itself: ``provenance`` stayed ``owner_stated`` even for a
            # voice the verifier said was NOT the owner, so the table asserted
            # something nobody had established. ``provenance`` is a two-value
            # column owned by P2-A and widening it is a schema change outside
            # this card, so the fact travels in ``reason``, which
            # ``add_owner_fact`` already persists verbatim.
            #
            # Stamped only for principals that may not grant: for ``owner`` and
            # ``unenrolled``, ``owner_stated`` is already true and appending to
            # every reason would churn P2-A's committed result text for no gain.
            existing = str(getattr(decision, "reason", "") or "")
            changes["reason"] = f"{existing} [heard from: {principal.label}]".strip()
        if changes:
            decision = dataclasses.replace(decision, **changes)  # type: ignore[type-var]
        if admission.downgraded:
            with self._lock:
                self._ot2_facts_downgraded += 1
            self._emit(
                "realtime",
                f"owner fact parked as {admission.consent}: {admission.reason}",
                "info",
            )
        written = dict(self._realtime_remember_fact(key, fact, decision))
        written.update(admission.as_dict())
        written["principal"] = principal.as_dict()
        written["requested_consent"] = requested
        return written

    def _ot2_confirm_fact(self, key: str, consent: str = CONSENT_GRANTED) -> dict[str, object]:
        """"Yes, remember that." THE product caller for ``set_owner_fact_consent``.

        Before this card that store method had exactly one caller in the whole
        tree and it was a test — the ``pending`` row P2-A's consent arm creates
        had nothing that could ever move it. This is the door, and it is gated
        on the same principal as a direct grant: a voice that could not create a
        granted fact in one step must not be able to create one in two.

        A refusal here is a refusal to CHANGE A CONSENT STATE, which is the one
        thing consent must be refusable about; the fact itself is untouched and
        still on the table for the owner to confirm later.
        """

        principal = self._ot2_memory_principal()
        if not principal.may_confirm_consent:
            with self._lock:
                self._ot2_facts_confirm_refused += 1
            return {
                "confirmed": 0,
                "refused": True,
                "reason": (
                    "I need to be sure it is my owner asking before I keep "
                    "something about them"
                ),
                "principal": principal.as_dict(),
            }
        verdict = str(consent or CONSENT_GRANTED)
        try:
            moved = int(self.agent.memory.set_owner_fact_consent(str(key), verdict))
        except (RuntimeError, TypeError, ValueError) as error:
            return {
                "confirmed": 0,
                "refused": False,
                "reason": f"the fact store is unavailable: {error}",
                "principal": principal.as_dict(),
            }
        with self._lock:
            self._ot2_facts_confirmed += moved
        return {
            "confirmed": moved,
            "refused": False,
            "consent": verdict,
            "principal": principal.as_dict(),
        }

    def memory_principal_snapshot(self) -> dict[str, object]:
        """What the principal rule has done this run. Public, read-only."""

        with self._lock:
            downgraded = self._ot2_facts_downgraded
            confirmed = self._ot2_facts_confirmed
            refused = self._ot2_facts_confirm_refused
        return {
            "principal": self._ot2_memory_principal().as_dict(),
            "facts_consent_downgraded": downgraded,
            "facts_confirmed": confirmed,
            "confirmations_refused": refused,
        }

    # ================= END CARD OT-2 memory-principal region =============

    def _realtime_pose_names(self) -> tuple[str, ...]:
        """Catalog skills whose kind is literally ``pose``. Nothing else."""

        try:
            return tuple(sorted(skill.id for skill in self.dog.catalog.list() if skill.kind == "pose"))
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            return ()

    def _realtime_pose(self, name: str) -> str:
        """``set_pose`` — the ACTIVITY door, never the recovery door.

        Card wording is ``propose_action(kind="pose")``; ``propose_action``
        refuses any ``kind`` but ``"skill"`` (runtime.py:3763), so calling it
        literally that way would raise on every hosted pose. The card's intent —
        *the pose door, and never ``ReturnToSafePose``* — is honoured exactly:
        the name must be a catalog skill whose own ``kind`` is ``pose``, and it
        goes through ``propose_action``, so navigation, follow and e-stop
        outrank it by the coordinator's existing arbitration rather than by
        anything written here.
        """

        clean = str(name).strip()
        if clean not in self._realtime_pose_names():
            raise ValueError(f"unknown pose: {clean!r}")
        detail = self.propose_action(
            ActionProposal(
                kind="skill",
                name=clean,
                trigger="explicit_command",
                timing_preference="now",
                interruption_request="safe_checkpoint",
                reason="hosted voice pose request",
            )
        )
        self._mark_narratable_activity(clean, detail)
        return detail

    def _realtime_gesture(self, name: str, intensity: float = 1.0) -> str:
        """``play_gesture`` — card R15's marking wrapper around the same door.

        ``_brain_gesture`` is unchanged and still does all the work; every
        refusal it raises still propagates untouched. The only thing added is
        the note that THIS gesture is one the owner asked for out loud, which is
        what makes its ending worth a sentence. An inline ``[emote:...]`` the
        robot authored in its own speech goes through ``_brain_gesture``
        directly and is therefore never marked, so it ends in silence — which is
        the whole point of the mark.
        """

        detail = self._brain_gesture(name, intensity)
        self._mark_narratable_activity(str(name).strip(), detail)
        return detail

    def _mark_narratable_activity(self, name: str, detail: str) -> None:
        """Remember that the owner is owed the ending of ``name``.

        Only for a request the coordinator actually took: a rejected or skipped
        proposal has no ending to report, and leaving the mark set would hand
        the next unrelated activity's terminal to the model.

        Card R24: written under ``_lock``. Same family as
        ``_narratable_orbit`` — set from the hosted ``set_pose``/``play_gesture``
        doors on the PUMP thread, claimed on the CONTROL thread.
        """

        clean = " ".join(str(name).split())
        if clean and str(detail).strip().startswith(("Accepted", "Deferred")):
            with self._lock:
                self._narratable_activity = clean

    def _claim_narratable_activity(self, name: str) -> bool:
        """One-shot: was THIS ending asked for out loud? Clears the mark.

        Card R24: compare-and-clear is ONE critical section under ``_lock``.
        ``_step_activities`` and ``_narrate_expired_activities`` both claim, and
        two claimers that both read the mark before either cleared it would say
        the same ending twice.
        """

        clean = " ".join(str(name).split())
        if not clean:
            return False
        with self._lock:
            if clean == self._narratable_activity:
                self._narratable_activity = ""
                return True
        return False

    def _learned_map_offer_places(self) -> tuple[str, ...] | None:
        """Card C-3 — what a refusal NAMES when the dog reads its own map.

        ``None`` ⇒ oracle ⇒ the R10 union below is unchanged. Otherwise the
        offers are the map's own active entries, nearest first from the robot's
        last pose, so the refusal sentence names places the robot has actually
        stood near rather than classes a sidecar declared.
        """

        try:
            from parcel_robot.perception_source.selection import (
                active_learned_map,
                active_semantic_source,
            )
        except ImportError:  # pragma: no cover — frozen bundle path
            return None
        if not active_semantic_source().drives_from_learned_map:
            return None
        learned = active_learned_map()
        if learned is None:
            return ()
        with self._lock:
            observation = self._observation
        if observation is None:
            # No pose, so no "nearest": fall back to the map's own vocabulary,
            # unordered but honest, rather than inventing a distance.
            try:
                return tuple(learned.known_places())
            except (AttributeError, TypeError, ValueError):
                return ()
        robot = observation.robot
        try:
            rows = learned.around_me(
                float(robot.x), float(robot.y), float(robot.yaw), radius_m=25.0, limit=16
            )
        except (AttributeError, TypeError, ValueError):
            return ()
        names: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for label in (row.get("label"), *(row.get("names") or ())):
                clean = " ".join(str(label or "").split())
                key = clean.lower()
                if clean and key not in seen:
                    seen.add(key)
                    names.append(clean)
        return tuple(names)

    # ---- CARD ASK-1 (task_18) — THE ROBOT ASKS INSTEAD OF SETTING OFF -------

    def _realtime_ask_place(self, place: str) -> dict[str, object]:
        """The abstention gate's ASK for ``place``, or ``{}`` when it does not ask.

        Card P1-D built ``AbstentionVerdict.as_ask()`` and left it unwired — the
        broker was MUST-NOT-TOUCH for that card, so the payload existed and
        nothing in the product ever spoke it (``P1D_STATUS.md`` handoff 1). This
        is the door.

        **It compiles the verdict fresh on every call, and that is the point.**
        The ``revision`` it returns identifies *what is being confirmed*, so the
        owner's "yes" cannot be transplanted onto a different question. If the
        subject changes between the question and the answer the digest moves,
        the broker's token comparison fails, and the robot asks again rather
        than acting on a confirmation the owner gave about something else. No
        pending state is stored anywhere — the recomputation IS the mechanism.

        **Correction pass.** The first version digested the whole verdict,
        ``signals`` included. Those signals are evidence counters and a
        similarity — they move on **every camera frame that sees the place** —
        so the token churned continuously and the owner's "yes" could never
        arrive in time to match one. A confirmation gate that cannot be
        satisfied while the robot can see the place is not a gate, it is a
        refusal with extra steps. :meth:`_ask_revision` now binds the token to
        the IDENTITY of the subject and not to the numbers behind it.

        Nothing here grants anything: no lease, no door, no motion. It reads the
        map under the same lock ``_curiosity_ask_candidate`` uses and returns a
        dict.

        Returns ``{}`` — never raises — when there is no learned map, when the
        map has nothing to say, or when the verdict is an ADMIT or a REFUSE.
        Both of those are already handled: an admit walks, a refusal is the
        broker's existing refusal path, and inventing a question for either
        would be a new refusal wearing a question mark.
        """

        learned = getattr(self, "_p1b_learned_map", None)
        name = " ".join(str(place).split())
        if learned is None or not name:
            return {}
        from parcel_robot.perception_abstention import OUTCOME_ASK

        try:
            with self._p1b_map_lock:
                result = learned.resolve(name)
        except Exception:  # noqa: BLE001 - a query is never worth a tool error
            return {}
        verdict = getattr(result, "verdict", None)
        if verdict is None or str(getattr(verdict, "outcome", "")) != OUTCOME_ASK:
            return {}
        try:
            ask = dict(verdict.as_ask())
        except Exception:  # noqa: BLE001
            return {}
        if not ask:
            return {}
        ask["revision"] = self._ask_revision(verdict, self._ask_subject(learned, verdict))
        return ask

    def _ask_subject(self, learned: Any, verdict: Any) -> Any:
        """The map entry the ASK is about, or ``None``. Read-only, under the lock."""

        place_id = str(getattr(verdict, "place_id", "") or "")
        if not place_id:
            return None
        try:
            with self._p1b_map_lock:
                for entry in learned.active_entries():
                    if str(entry.entry_id) == place_id:
                        return entry
        except Exception:  # noqa: BLE001 - no subject is a token-less question
            return None
        return None

    @staticmethod
    def _ask_revision(verdict: Any, entry: Any = None) -> str:
        """A digest of WHAT is being confirmed — never of how sure the robot is.

        Three identity fields and three evidence fields, and the choice of which
        is the whole correction:

          query      what the owner said
          candidate  what the robot thinks it is — the sentence it just spoke
          place_id   which entry it means
          label      the entry's own label
          position   rounded to 0.1 m: the fused surface median jitters by
                     millimetres on every new observation, and a confirmation
                     must survive the robot looking at the thing again
          crop       sha256 of the best-view thumbnail — the pixels the question
                     was asked about

        **Deliberately excluded: every number in ``verdict.signals``.**
        ``evidence_frames``, ``label_support``, ``detection_count`` and the
        similarity all change the moment the camera sees the place once more.
        Digesting them made the token change faster than a person can answer,
        which is a confirmation gate nobody can pass — the defect the verifier
        found. The token now moves when the *subject* moves (a different
        candidate, a different place, a new best view, a place that has been
        re-fused 10 cm away) and not when the evidence for it merely grows.
        """

        import hashlib

        def _f(value: Any) -> str:
            try:
                return f"{float(value):.1f}"
            except (TypeError, ValueError):
                return "?"

        crop = getattr(entry, "thumbnail", None) if entry is not None else None
        parts = (
            " ".join(str(getattr(verdict, "query", "")).split()),
            " ".join(str(getattr(verdict, "candidate", "")).split()),
            str(getattr(verdict, "place_id", "") or ""),
            str(getattr(entry, "label", "") or "") if entry is not None else "",
            _f(getattr(entry, "surface_x", 0.0)) if entry is not None else "?",
            _f(getattr(entry, "surface_y", 0.0)) if entry is not None else "?",
            _f(getattr(entry, "surface_z", 0.0)) if entry is not None else "?",
            hashlib.sha256(bytes(crop)).hexdigest() if crop else "no-crop",
        )
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]

    # ---- END CARD ASK-1 (task_18) -------------------------------------------

    def _realtime_places(self) -> tuple[str, ...]:
        """The place vocabulary ``navigate_to`` is validated against — card R10.

        Nearest-first, and deliberately a UNION of two sources:

        * every semantic instance the robot can currently see, by label — so a
          real thing in front of the dog is never refused as junk;
        * the scene's declared class vocabulary — so a place the robot knows how
          to look for but cannot see yet ("the door") is admitted and then fails
          honestly at grounding ("I looked and couldn't find it"), which is a
          true sentence, rather than being refused as a fabrication, which is
          not.

        Never raises: an empty list makes the broker defer to the router, which
        is the layer that decided this before R10 and still runs next.

        Card C-3: under ``learned_map`` the offer set is what the robot has
        actually seen, nearest first, from the map's own entries. A refusal that
        offers a place the owner cannot see is a worse answer than one that
        offers nothing — and after the cutover, "cannot see" means the map does
        not have it, not that the sidecar failed to declare it.
        """

        learned_map_places = self._learned_map_offer_places()
        if learned_map_places is not None:
            return learned_map_places

        with self._lock:
            observation = self._observation
        names: list[str] = []
        seen: set[str] = set()

        def _add(label: object) -> None:
            clean = " ".join(str(label or "").split())
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                names.append(clean)

        if observation is not None:
            robot = observation.robot
            visible: list[tuple[float, str]] = []
            for region in observation.semantic_regions:
                centre = _polygon_centre(region.polygon)
                if centre is None:
                    continue
                visible.append((math.dist((robot.x, robot.y), centre), str(region.label)))
            for item in observation.semantic_objects:
                position = item.position
                visible.append(
                    (
                        math.dist((robot.x, robot.y), (float(position[0]), float(position[1]))),
                        str(item.label),
                    )
                )
            for _distance, label in sorted(visible, key=lambda row: (row[0], row[1])):
                _add(label)
        try:
            from parcel_robot.city_semantics import CLASS_ALIASES

            for class_label in sorted(CLASS_ALIASES):
                _add(class_label)
        except (ImportError, RuntimeError, ValueError):
            pass
        return tuple(names)

    def _place_admission(self, directive: str) -> PlaceAdmission:
        """Card R20 — may this directive become a goal? ONE answer for both lanes.

        The typed panel and the hosted ``navigate_to`` tool both ask this method,
        which is the whole point: R10 established that the hosted lane must not
        grow a grammar the panel does not have, and the only way to fix
        "go to narnia" without breaking that rule is to assemble the vocabulary
        once, here, and let both admission paths read it.

        Two vocabularies, because the question has two halves:

        * ``known`` — the RESOLUTION set. Every region label, object label,
          scene class and class ALIAS the grounder could match, from
          ``_realtime_scene_vocabulary``. Aliases matter: "the pavement" and
          "street light" are real, resolvable requests, and a resolution set
          built from class names alone would refuse them.
        * ``offer`` — what the refusal NAMES, nearest first, from
          ``_realtime_places``. A refusal that offers a place the owner cannot
          see is a worse answer than one that offers nothing.

        Never raises: both sources swallow their own failures, and a vocabulary
        that comes back empty admits everything (``no_vocabulary``), which is
        the pre-R20 behaviour and the honest answer for a robot whose map has
        not loaded.
        """

        regions, objects = self._realtime_scene_vocabulary()
        known = tuple(regions) + tuple(objects)
        offer = self._realtime_places()
        # Card C-3. ``admit_navigation_place`` FAILS OPEN on an empty
        # vocabulary and says ``no_vocabulary`` — the right call when the
        # vocabulary comes from a sidecar, because a missing scene file must not
        # take the navigation surface down. Under ``learned_map`` the same
        # emptiness means something else entirely: the robot has looked and
        # learned nothing, and admitting every directive there would resurrect
        # "go to Narnia" at exactly the moment this card claims to have killed
        # it. So off-oracle an empty vocabulary REFUSES, and says which of the
        # two emptinesses it is.
        admission = admit_navigation_place(directive, known, offer=offer)
        if (
            admission.reason == PLACE_NO_VOCABULARY
            and self._learned_map_vocabulary() is not None
        ):
            # Only the fail-open verdict is converted. Running the gate first
            # keeps its JURISDICTION exactly as it was: "let's go back home" is
            # ``not_a_navigation_directive`` on both sources because the
            # destination grammar does not call it a directive, and a blanket
            # refusal here would have this gate start answering questions that
            # belong to another layer.
            return PlaceAdmission(
                False,
                "I haven't seen anywhere I could take you yet — I've been "
                "building my own map and it's still empty.",
                PLACE_UNKNOWN,
            )
        return admission

    def _realtime_orbit(self, direction: str, size: str, revolutions: float) -> str:
        """``circle_owner`` — the ROUTER still decides, exactly as navigate does.

        The broker renders the model's arguments into the plainest phrasing the
        deterministic spatial grammar already accepts, routes THAT, and proceeds
        only when the router itself returns ``direct_skill`` on its own
        ``orbit_owner`` rule. No ``SpatialIntent`` and no ``PlanSketch`` is
        fabricated here — the intent comes back out of ``parse_spatial_intent``,
        the same parser a typed sentence goes through.

        Feasibility is checked BEFORE admission and its refusal is raised as a
        ``ValueError`` carrying the validator's own sentence, so what the model
        says out loud is what the geometry found.

        Card R24 — ``_agent_lock``, held across the WHOLE body. See
        ``_realtime_navigate`` for the full reasoning; the orbit door has the
        same three agent-state hazards (router mutation, the
        ``_admit_local_sketch`` → ``last_reasoning_source`` read-after-write,
        and the ``_realtime_turn_sequence`` read-modify-write inside
        ``_realtime_spatial_intent``) and takes the same lock at the same
        granularity.
        """

        with self._agent_lock:
            intent, frame, directive_text = self._realtime_spatial_intent(
                direction=direction, size=size, revolutions=revolutions
            )
            observation = self._fresh_observation_for_owner_relative()
            verdict = self.spatial.assess_orbit(
                intent, observation, obstacle_stop_m=self.obstacle_stop_m
            )
            if not verdict.feasible:
                self._emit("spatial", f"orbit refused: {verdict.cause}", "warning")
                raise ValueError(
                    self.spatial.last_refusal_sentence
                    or "I can't walk around you here — there isn't room."
                )
            if not self.agent._local_plan_ready():
                raise RuntimeError(
                    "the robot's plan admission is not available right now"
                )
            reply = self.agent._admit_local_sketch(
                sketch_spatial(intent),
                frame,
                directive_text,
                None,
                reply="Okay—I'll walk a circle around you.",
            )
            if self.agent.last_reasoning_source != "local_plan_sketch":
                raise RuntimeError(reply)
            # Card R15. The lap is now the owner's, and its ending is theirs to
            # hear: a circle takes tens of seconds and the broker answer says
            # only that it started. Set AFTER admission, so a refused orbit
            # leaves no mark behind for the next spatial behaviour's terminal
            # to claim.
            #
            # Card R24. The mark is written on the PUMP thread and claimed on
            # the CONTROL thread (``_claim_orbit_terminal``), so it takes the
            # lock its claimer takes.
            with self._lock:
                self._narratable_orbit = True
            return reply

    def _realtime_spatial_intent(
        self,
        *,
        direction: str,
        size: str,
        revolutions: float,
    ) -> tuple[SpatialIntent, Any, str]:
        """Render → route → parse. Raises ValueError if the router declines."""

        # The spatial grammar's size alternation is ``small|tight|wide`` — there
        # is no literal "normal", because a circle with no adjective IS the
        # normal one. Rendering "walk in a normal counterclockwise circle around
        # me" therefore matched nothing and the router answered
        # ``ambiguous_physical_request``, which the broker correctly turned into
        # a refusal — i.e. the brand-new circle_owner tool refused every default
        # request. Caught by the live proof, not by a unit test, because the
        # broker and the grammar were each individually right.
        adjective = f"{size} " if size and size != "normal" else ""
        directive_text = f"walk in a {adjective}{direction} circle around me"
        sequence = self._next_realtime_turn_sequence()
        frame = self.agent.intent_router.route(
            directive_text,
            turn_id=f"turn-realtime-{sequence}",
            original_transcript_ref=f"realtime-tool:{sequence}:final",
        )
        self._record_realtime_route(frame, directive_text)
        if frame.route != "direct_skill" or frame.matched_rule != "orbit_owner":
            raise ValueError(
                "the robot's spatial grammar does not recognize that circle "
                f"(router rule: {frame.matched_rule})"
            )
        intent = parse_spatial_intent(directive_text)
        if intent is None:  # pragma: no cover - the router just matched it
            raise ValueError("the robot cannot compile that circle")
        # ``revolutions`` is the model's only numeric argument; the supervisor has
        # already clamped it to [0.25, 1.0] and the controller clamps again.
        return (
            dataclasses.replace(intent, revolutions=float(revolutions)),
            frame,
            directive_text,
        )

    def _fresh_observation_for_owner_relative(self) -> SimObservation:
        """A fresh observation for an owner-relative admission check.

        Same contract ``_start_brain_spatial_behavior`` uses for owner-relative
        behaviours: device I/O, outside any command lock, and a stale or missing
        read is a refusal rather than a guess about where the owner is.
        """

        started = time.monotonic()
        try:
            observation = self.backend.observe()
        except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise RuntimeError(f"fresh camera/LiDAR perception is unavailable: {error}") from error
        finally:
            self.component_metrics.elapsed("SpatialCommandObserve", started)
        if time.monotonic() - observation.timestamp > self.telemetry_stale_s:
            raise RuntimeError("camera/LiDAR perception is stale")
        return observation

    def _realtime_follow(self, pace: str) -> str:
        """``follow_owner(pace)`` — routed through the router's own follow rule.

        ``pace`` is recorded and reported; it does NOT change a commanded speed
        here. R11 owns pace_intent, and a pace this layer pretended to apply
        would be the B2 over-claim the bench measured. The recorded value is
        what R11 will consume.

        Card R24 — ``_agent_lock``, held across the WHOLE body. See
        ``_realtime_navigate`` for the reasoning.
        """

        with self._agent_lock:
            clean = " ".join(str(pace).split()).lower() or "walk"
            directive_text = "follow me"
            sequence = self._next_realtime_turn_sequence()
            frame = self.agent.intent_router.route(
                directive_text,
                turn_id=f"turn-realtime-{sequence}",
                original_transcript_ref=f"realtime-tool:{sequence}:final",
            )
            self._record_realtime_route(frame, directive_text)
            if frame.route != "direct_skill" or frame.matched_rule != "follow_owner":
                raise ValueError(
                    "the robot's follow grammar did not recognize that "
                    f"(router rule: {frame.matched_rule})"
                )
            if not self.agent._local_plan_ready():
                raise RuntimeError(
                    "the robot's plan admission is not available right now"
                )
            # Card R11 — pace_intent. THE ONLY THING THIS VALUE DOES. It is
            # recorded as a declaration the owner made, read by the whisperer's
            # pace watcher, and never written to a controller: no follow speed,
            # no clearance, no cap anywhere is a function of it. "Run with me"
            # therefore still gets an honest follow at the robot's own pace
            # (R10's ``pace_applied: false``), and what R11 adds is that the
            # robot NOTICES the mismatch and asks about it instead of
            # pretending it adapted.
            #
            # Card R24. ``_realtime_pace_intent`` and its ``_at_s`` stamp are a
            # COMPOUND: the whisperer reads the pair under ``_lock`` and clears
            # the pair under ``_lock`` on the follow falling edge. The write is
            # therefore one critical section under the same lock, and
            # ``_realtime_last_pace`` (the panel's copy of the same fact) joins
            # it so ``/api/state`` can never show a pace the whisperer has
            # already cleared.
            with self._lock:
                self._realtime_last_pace = clean
                self._realtime_pace_intent = clean
                self._realtime_pace_intent_at_s = time.monotonic()
            reply = self.agent._admit_local_sketch(
                sketch_follow(behind=False),
                frame,
                directive_text,
                None,
                reply="Okay—I'll come along with you.",
            )
            if self.agent.last_reasoning_source != "local_plan_sketch":
                raise RuntimeError(reply)
            return reply

    def _realtime_navigate(self, place: str, relation: str = "") -> str:
        """``navigate_to`` — R4-lite: the ROUTER decides, the broker only renders.

        The ``_accept_plan`` invariant is that routes come from the versioned
        deterministic router and never from a model. So this method renders the
        model's place name into plain directive text, routes THAT through the
        same ``DeterministicIntentRouter`` a typed sentence takes (fresh turn
        id, final transcript), and proceeds only when the router itself returns
        ``direct_skill`` on its ``navigation_directive`` rule. Anything else —
        an unrecognized place, a compound, a blocked mention — comes back as a
        refusal with the router's own rule name in it, which the model then says
        out loud. No ``IntentFrame`` is ever constructed here.

        Card R24 — WHY ``_agent_lock`` IS HELD ACROSS THE WHOLE BODY.
        ==========================================================
        Fable's full audit (2026-08-20, §Arch) confirmed this door and its two
        siblings mutate ``VoiceAgent`` state from the realtime PUMP thread
        without the lock that exists to serialize exactly that state against
        the panel/typed thread. Three distinct hazards, all inside this body:

        1. ``self.agent.intent_router.route(...)`` advances router state.
        2. ``agent._admit_local_sketch`` WRITES ``agent.last_reasoning_source``
           and ``agent.last_brain_metrics``; the next statement READS
           ``last_reasoning_source`` back to decide accept-vs-refuse. A typed
           turn landing between those two lines makes this door either raise a
           refusal over a plan that WAS admitted, or return an "Okay—" over a
           plan that was not. That read-after-write is the whole reason the
           section cannot be narrowed to the mutation alone.
        3. ``_realtime_turn_sequence`` is a read-modify-write feeding
           ``PlanIR.source_turn_id``; ``_accept_plan`` matches that id against
           the frame's, so two doors racing to the same id would let one
           admission answer the other.

        FULL BODY, not narrowed. The card allowed narrowing only if the lock
        could not be held across the body without inverting the verified lock
        DAG. It can: the only runtime locks reachable from this body are
        ``_lock`` (via ``_place_admission`` / ``_realtime_scene_vocabulary`` /
        ``_emit``) and — through ``_admit_local_sketch``'s ``plan_publisher``
        callback into ``self._accept_plan`` — ``_command_lock`` and ``_lock``.
        Both ``_agent_lock → _lock`` and ``_agent_lock → _command_lock`` are
        pre-existing edges: ``set_personality`` takes ``_lock`` under
        ``_agent_lock``, and ``handle_text`` already reaches ``_accept_plan``
        under ``_agent_lock`` by the identical callback. Nothing anywhere takes
        ``_agent_lock`` while holding ``_lock``, ``_command_lock`` or
        ``_navigation_lock``, so no back-edge exists and the graph stays a DAG
        (re-verified by ``tests/test_r24_lock_discipline.py``, statically and
        under live contention).

        ``_agent_lock`` is a non-reentrant ``threading.Lock``, so a door that
        re-entered ``handle_text`` / ``handle_text_guarded`` /
        ``set_personality`` would self-deadlock. Nothing reachable from these
        bodies does; that is asserted, not assumed, by the same test.

        The cost is honest and accepted: a hosted tool call now waits behind an
        in-flight typed turn (worst case, one model round-trip) instead of
        corrupting it. Serializing is what the lock is FOR.
        """

        with self._agent_lock:
            clean = " ".join(str(place).split())
            if not clean:
                raise ValueError("navigate_to needs a place")
            directive_text = NAVIGATE_DIRECTIVE_TEMPLATE.format(place=clean)
            # Card R20 — the unknown-place gate, BEFORE the router. live_run_1
            # §d: the router said ``navigation_directive`` for "go to Narnia"
            # and meant it — the grammar is about SHAPE, and "go to <noun>" is
            # a navigation directive whatever the noun is. Asking the router
            # harder was never going to help; the missing question is whether
            # anything can resolve the noun, and it is asked here so the
            # refusal arrives as a ``rejected`` tool result carrying real
            # alternatives instead of as a mission that rotates on the spot for
            # 4.25 s.
            admission = self._place_admission(directive_text)
            if not admission.admitted:
                self._emit(
                    "navigation",
                    f"unknown place refused: {admission.query!r} ({admission.reason})",
                    "warning",
                )
                raise ValueError(admission.fact())
            sequence = self._next_realtime_turn_sequence()
            frame = self.agent.intent_router.route(
                directive_text,
                turn_id=f"turn-realtime-{sequence}",
                original_transcript_ref=f"realtime-tool:{sequence}:final",
            )
            # Recorded on the runtime rather than written onto
            # ``agent.last_intent_frame``: that field means "what the local
            # agent last routed for a TYPED turn" and half the panel reads it.
            # A hosted tool call is a different provenance and gets its own
            # visible record.
            self._record_realtime_route(frame, directive_text)
            if (
                frame.route != "direct_skill"
                or frame.matched_rule != "navigation_directive"
            ):
                raise ValueError(
                    f"the robot's navigation does not recognize {clean!r} as a place "
                    f"(router rule: {frame.matched_rule})"
                )
            nav_directive = navigation_directive_from_text(directive_text.lower())
            if nav_directive is None:  # pragma: no cover - the router just matched it
                raise ValueError(f"the robot cannot compile a route to {clean!r}")
            if not self.agent._local_plan_ready():
                raise RuntimeError(
                    "the robot's plan admission is not available right now"
                )
            # Card R10 — the hybrid relation. The hint travels as a HINT: the
            # local arrival table validates it inside
            # ``semantic_goal_from_directive`` and overrides it on any
            # conflict, and ``region_support``/``person_support`` are read off
            # the live scene here (the only layer that can see it), so a
            # refinement is impossible unless the map actually backs it.
            region_labels, object_labels = self._realtime_scene_vocabulary()
            reply = self.agent._admit_local_sketch(
                sketch_navigate(
                    nav_directive,
                    relation_hint=str(relation or "") or None,
                    region_labels=region_labels,
                    object_labels=object_labels,
                    region_support=_place_matches(clean, region_labels),
                    person_support=False,
                ),
                frame,
                directive_text,
                None,
                reply=f"Okay—I'll navigate toward {nav_directive} safely.",
            )
            if self.agent.last_reasoning_source != "local_plan_sketch":
                # ``_admit_local_sketch`` swallows admission failures into an
                # honest refusal sentence; surface it as a refusal rather than
                # an "ok".
                raise RuntimeError(reply)
            return reply

    def _next_realtime_turn_sequence(self) -> int:
        """Card R24. The hosted turn counter's read-modify-write, made atomic.

        ``_realtime_turn_sequence`` feeds ``turn-realtime-<n>``, which becomes
        ``PlanIR.source_turn_id``, which ``_accept_plan`` matches against the
        frame's id. Two doors racing this ``+= 1`` on the pump thread — or a
        door racing the panel thread reading it — could hand two admissions the
        same id, and one admission would answer the other. It is an increment,
        not an emergent invariant, so it takes ``_lock``: the same lock
        ``realtime_snapshot`` now takes to read the compound record beside it.
        """

        with self._lock:
            self._realtime_turn_sequence += 1
            return self._realtime_turn_sequence

    def _record_realtime_route(self, frame: IntentFrame, directive_text: str) -> None:
        """Card R24. The five-field route record written as ONE update.

        ``_realtime_last_route`` is a COMPOUND — turn id, route, rule,
        directive and router version have to describe the same routing decision
        or the panel shows one door's rule against another door's directive.
        Written on the pump thread, read by ``realtime_snapshot`` on the panel
        thread; both ends take ``_lock``, and the reader copies the dict inside
        the section so it cannot observe a half-replaced mapping.
        """

        with self._lock:
            self._realtime_last_route = {
                "turn_id": frame.turn_id,
                "route": frame.route,
                "rule": frame.matched_rule,
                "directive": directive_text,
                "router_version": frame.router_version,
            }

    def _learned_map_vocabulary(self) -> tuple[str, ...] | None:
        """Card C-3 — the R20 vocabulary when the dog reads its own map.

        ``None`` means "the source is the oracle", and every caller then takes
        the sidecar path it always took. Under ``learned_map`` this is the whole
        vocabulary: names the map earned from detections and from VLM proposals
        promoted after k consistent visits. The scene sidecar is not consulted.

        **This is where the Narnia property stops being a list.** Before the
        cutover, "go to Narnia" was refused because Narnia is absent from a
        vocabulary the world file declared — honest, but a property of the
        simulator rather than of perception. After it, the vocabulary is what
        the robot has actually seen, so the refusal is earned. A map that has
        learned nothing returns an EMPTY tuple, not ``None``: an empty
        vocabulary refuses everything, which is the correct answer for a robot
        that has not looked yet, and it must not be confused with "no map axis
        is installed", which admits everything.
        """

        try:
            from parcel_robot.perception_source.selection import (
                active_learned_map,
                active_semantic_source,
            )
        except ImportError:  # pragma: no cover — frozen bundle path
            return None
        if not active_semantic_source().drives_from_learned_map:
            return None
        learned = active_learned_map()
        if learned is None:
            return ()
        try:
            return tuple(learned.known_places())
        except (AttributeError, TypeError, ValueError):
            return ()

    def _realtime_scene_vocabulary(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """(region labels, object labels) the arrival table may classify against.

        Live instances first, then the scene's declared classes and aliases.
        This is what lets the local table classify a place whose noun is not in
        any hard-coded word list — the sidecar is the scene's vocabulary and this
        reads it rather than transcribing any of it.

        Card C-3: under ``perception.semantic_source: learned_map`` the sidecar
        is NOT read and the map's own learned names are the whole resolution
        set. Regions come back empty because C-2's map is object-centric — a
        place is a thing the robot saw, not a polygon the world file declared —
        and claiming region vocabulary it does not have would be the sidecar
        creeping back in under a different name.
        """

        learned = self._learned_map_vocabulary()
        if learned is not None:
            return (), learned

        with self._lock:
            observation = self._observation
        regions: list[str] = []
        objects: list[str] = []
        if observation is not None:
            regions.extend(str(region.label) for region in observation.semantic_regions)
            objects.extend(str(item.label) for item in observation.semantic_objects)
        try:
            from parcel_robot.scene_semantics import scene_semantics

            for scene_class in scene_semantics().classes:
                bucket = regions if scene_class.kind == "region" else objects
                bucket.append(str(scene_class.name))
                bucket.extend(str(alias) for alias in scene_class.aliases)
        except (AttributeError, ImportError, RuntimeError, ValueError):
            pass
        return tuple(dict.fromkeys(regions)), tuple(dict.fromkeys(objects))

    def _realtime_thinking_pose(self) -> None:
        """Visible "I heard you" the moment a tool is dispatched, not after."""

        self.expression.reactions.on_turn_pending(time.monotonic())

    def realtime_snapshot(self) -> dict[str, object]:
        """Lane + arming + broker + driver state for ``/api/state``."""

        lane = self.realtime_lane
        whisperer = self.realtime_whisperer
        # Card R11. The knob has to be visible whether or not a lane exists —
        # "how often may the robot start a billed exchange with me" is a fact
        # about the configuration, not about the socket.
        whisperer_snapshot = None if whisperer is None else whisperer.snapshot()
        # Card P2-B. Published in the CONSTRUCTED branch only, deliberately.
        # Both are facts about a session — how many rows were labelled, how many
        # appearances the watcher has seen — and with no lane both are zero. The
        # owner-event CONFIGURATION is already visible in the flag-off branch
        # through ``config.whisperer.owner_events``, which is where "when may the
        # robot greet me" belongs, so nothing is hidden by keeping the counters
        # out of a snapshot that has no session to count.
        owner_events = self.realtime_owner_events
        owner_events_snapshot = None if owner_events is None else owner_events.snapshot()
        identity_coverage = self.identity_label_coverage()
        if lane is None:
            return {
                "enabled": False,
                "constructed": False,
                "mode": self.realtime_config.mode,
                "config": self.realtime_config.as_dict(),
                "whisperer": whisperer_snapshot,
            }
        broker = self.realtime_broker
        driver = self.realtime_driver
        gateway = self.realtime_gateway
        lane_ledger = getattr(lane, "_ledger", None)
        # Card R24. The compound realtime record is written on the PUMP thread
        # and cleared on the CONTROL thread; this is the PANEL thread. Read the
        # pair under the same ``_lock`` both of those take, and copy the route
        # mapping inside the section — the old code read both fields bare, so
        # ``/api/state`` could show a pace the whisperer had already cleared,
        # or a route dict caught mid-replacement.
        with self._lock:
            pace_intent = self._realtime_pace_intent
            last_route = (
                None if self._realtime_last_route is None else dict(self._realtime_last_route)
            )
        return {
            "enabled": True,
            "constructed": True,
            "mode": self.realtime_config.mode,
            "config": self.realtime_config.as_dict(),
            "lane": lane.snapshot(),
            "broker": None if broker is None else broker.snapshot(),
            "driver": None if driver is None else driver.snapshot(),
            "gateway": None if gateway is None else gateway.snapshot(),
            "whisperer": whisperer_snapshot,
            "owner_events": owner_events_snapshot,
            "identity_labels": identity_coverage,
            # Card EV-1. The persisted stream the eval model reads, beside the
            # rings it is the uncapped version of.
            "session_evidence": self.session_evidence_snapshot(),
            # Card R22, work item 2. The pump's own liveness, promoted out of
            # the driver blob so the panel does not have to know the driver's
            # shape to raise an alarm, plus the death/revival history. `alive`
            # is the field that answers §Safety-1's question: is anything still
            # turning the crank on the hosted lane.
            "pump": self._realtime_pump_snapshot(),
            # Card R22, work item 4. Ledger writes this runtime degraded to a
            # note rather than letting them end a turn (or a thread).
            "ledger_failures": self._realtime_ledger_failures,
            "ledger_mirror": (
                lane_ledger.snapshot() if isinstance(lane_ledger, _RealtimeLedgerMirror) else None
            ),
            "spend_usd": round(realtime_spend_usd(lane.usage_rows), 6),
            # Card R25, work item 3. "How close am I?" without reading files.
            # `spend_usd` above is THIS PROCESS's sessions and resets on
            # restart; this is the durable month-to-date figure the ceiling is
            # actually enforced on, with the ceiling beside it. `None` means no
            # ledger was armed — which is a different claim from "$0.00 spent"
            # and the panel renders it differently.
            "month_to_date": self._realtime_month_to_date(),
            # Card R16. Robot-initiated facts this door refused because the lane
            # had hung up. Beside the lane's own ``narrations_skipped_closed``,
            # which counts the same thing for anyone who asks the lane directly.
            "narrations_into_closed_lane": self._narrations_into_closed_lane,
            "panel_token_bound": self._realtime_panel_token is not None,
            "pace_intent": pace_intent,
            "last_route": last_route,
        }

    def _realtime_month_to_date(self) -> dict[str, object] | None:
        """The durable month-to-date spend block for ``/api/state``. Never raises.

        Card R25, work item 3. Carries the ceiling and the derived
        ``remaining_usd`` / ``fraction_of_budget`` / ``over_budget`` alongside
        the measurement, so the panel does no arithmetic and cannot disagree
        with the gate about whether the ceiling has been reached. ``readable:
        false`` is the fail-open state and is rendered as a WARNING rather than
        as a small number: it means "the ceiling is not being enforced", not
        "you have spent nothing".
        """

        ledger = self._realtime_spend_ledger
        if ledger is None:
            return None
        try:
            return ledger.snapshot(budget_usd=self.realtime_config.monthly_budget_usd)
        except Exception as error:  # noqa: BLE001 - a snapshot may never raise
            return {
                "readable": False,
                "note": f"spend ledger snapshot failed ({type(error).__name__}: {error})",
                "budget_usd": self.realtime_config.monthly_budget_usd,
            }

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
            mission_log = [dict(row) for row in self._mission_log]
            safety_log = [dict(row) for row in self._safety_log]
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
        state: dict[str, object] = {
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
            # Card ROAM-1. "Is the dog out exploring, how much budget is left,
            # and what is it doing right now" is a question an owner reading the
            # panel is entitled to answer without opening a log.
            "roam": self.roam_snapshot(),
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
                # FIX-A/F1+F2. Why the mic is (not) armed, and what the speech
                # stack actually resolved to at startup.
                "mic_arming": self._mic_arming.as_dict(),
                "stack": dict(self._speech_stack_detail),
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
            "realtime": self.realtime_snapshot(),
            "events": events,
            "mission_log": mission_log,
            # Card R21. Its own top-level key beside the mission log, for the
            # same reason the mission log has one: `web_panel.py` passes the
            # snapshot through verbatim, so the panel reaches it with no
            # registration anywhere.
            "safety_log": safety_log,
            "safety_latch": self._safety_latch_state(),
            "chat": chat,
        }
        # Card C-1. APPENDED, and only when the eye is on. With the flag off
        # the key is absent and this dict is byte-identical to the pre-C-1
        # wire — which is the whole R1 discipline, and is asserted rather than
        # asserted-by-docstring in tests/test_c1_camera_stream.py.
        camera_stream = self.camera_stream_snapshot()
        if camera_stream is not None:
            state["camera_ingress"] = camera_stream
        # ---- CARD CAP-1: what the product admits, on the panel ---------------
        # Two keys, both APPENDED, neither replacing anything.
        #
        # ``admission`` is the answer to "why can't it do that": every behavior
        # the supervisor knows, every hosted tool, every motion tool's proactive
        # verdict, every config section a runtime region reads against what an
        # overlay may set, and the capability rows — each with a reason and the
        # door it was read from. It is a VIEW; nothing here refuses anything.
        #
        # ``curiosity`` is CURIO-1's ``curiosity_snapshot()``, which shipped
        # with no product surface at all — the card said so in its own
        # docstring. Absent (not ``null``) when chatter is off, the same
        # discipline C-1's ``camera_ingress`` key follows two lines up.
        #
        # Best-effort by construction: a panel refresh must never be the thing
        # that takes the runtime down, so a broken view degrades to a stated
        # error instead of an exception on the wire.
        try:
            from parcel_robot.admission import admission_snapshot

            state["admission"] = admission_snapshot(self)
        except Exception as error:  # noqa: BLE001 - the panel is never load-bearing
            state["admission"] = {"error": f"{type(error).__name__}: {error}"}
        curiosity = self.curiosity_snapshot()
        if curiosity is not None:
            state["curiosity"] = curiosity
        # ---- END CARD CAP-1 (/api/state keys) -------------------------------
        return state

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
        # ---- CARD NM-1 (task_18) — THIS THREAD IS THE 10 Hz LOOP -----------
        #
        # Card P1-D built a tripwire that refuses to run a VLM on the control
        # thread, and then nothing in the product ever told it which thread that
        # was: ``mark_control_thread`` had zero callers outside the tests. The
        # AST check can only see the call sites that exist today; the tripwire is
        # the one that sees the call site somebody adds tomorrow — and an unarmed
        # tripwire sees nothing at all.
        #
        # The registry lives in ``perception_abstention`` and NOT in
        # ``parcel_robot.vlm_veto``, because
        # ``test_p1d_vlm_veto.py::test_the_runtime_imports_no_veto_module``
        # forbids this module from importing that package at any scope, and that
        # rule is correct and stays. The import is function-scope for the same
        # reason every other perception import in this file is.
        #
        # Marked here rather than in ``start()`` because what must be marked is
        # the THREAD, and this is the function that runs on it.
        from parcel_robot.perception_abstention import (
            clear_control_thread,
            mark_control_thread,
        )

        mark_control_thread()
        try:
            self._control_loop_body()
        finally:
            # A loop that exits and leaves its id marked would make the next
            # thread to reuse that id look like a control loop, and the tripwire
            # would then refuse work that is perfectly legal.
            clear_control_thread()

    def _control_loop_body(self) -> None:
        # ---- END CARD NM-1 (task_18) ---------------------------------------
        last_follow_state = ""
        while not self._stop_event.is_set():
            started = time.monotonic()
            observe_recorded = False
            try:
                observe_started = time.monotonic()
                observation = self.backend.observe()
                # ---- CARD OT-2 seam 2 of 3: WHO the owner track is. -------
                # Immediately after the backend answers and BEFORE anything
                # reads the observation, so the reactive gate, the follow
                # controller and P2-B's greeting watcher all read one identity
                # rather than each reaching for its own. Returns the SAME
                # object when no OwnerTracker is installed.
                observation = self._ot2_apply_owner_identity(observation)
                # ---- END CARD OT-2 seam 2 --------------------------------
                if self._observation_sink is not None:
                    self._observation_sink.update_observation(observation)
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
                        self._interrupt_brain(
                            "emergency",
                            "simulator emergency stop adopted",
                            stop_reason="simulator_emergency_stop",
                        )
                        self.preempt(
                            "safety",
                            reason="simulator_emergency_stop",
                            targets=("follow", "navigation", "spatial", "search", "activities"),
                        )
                        self.agent.safety.engage_emergency_stop()
                        self.arbiter.engage_emergency_stop()
                        self.control_manager.emergency_stop()
                        self._reset_motion_shaper()
                    # Card R21. Adopted from the simulator, not from an owner —
                    # the ring says which, so nobody has to guess later.
                    self._log_safety_latch(
                        source=SAFETY_SOURCE_SIMULATOR, already_latched=False
                    )
                    self._emit(
                        "safety",
                        "Simulator emergency stop adopted",
                        "error",
                        detail={"source": SAFETY_SOURCE_SIMULATOR},
                    )
                # Card C-1. Strictly AFTER emergency-stop adoption: the camera
                # mailbox must never sit between the simulator declaring a stop
                # and this runtime adopting it. No-op unless the eye is on.
                self._offer_camera_pose(observation)
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

            # Card ROAM-1. LAST of the motion producers, and last on purpose:
            # every step above it is a behavior the owner named, and roam's
            # first act each tick is to end itself if any of them is running.
            # Placing it here means it observes their state AFTER they have
            # published it for this tick rather than one tick stale.
            roam_started = time.monotonic()
            self._step_roam(observation)
            self.component_metrics.elapsed("RoamBehavior", roam_started)

            # ---- CARD AWARE-1 (scrum/20260823/task_4) ----------------------
            # BELOW roam, which is already the last motion producer, because
            # awareness is the only behaviour here that nobody asked for: it
            # yields to roam the way roam yields to an owner command, and it
            # observes roam's state for this tick rather than one tick stale.
            awareness_started = time.monotonic()
            self._step_awareness(observation)
            self.component_metrics.elapsed("AwarenessSweep", awareness_started)
            # ---- END CARD AWARE-1 ------------------------------------------

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
            # Card R11. Last in the loop, after every subsystem has published its
            # state for this tick, so the digest is a snapshot of a settled tick
            # rather than of one halfway through.
            self._step_whisperer(observation)
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
            # Card R22, work item 2. The belt to the driver's braces: a pump
            # that vanished without running its own `_die` is named within one
            # health period instead of never. Cheap (one `is_alive()`), silent
            # when healthy, and alarms at most once per undetected death.
            self._watch_realtime_pump()
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
                # Card W0-A: this ONE write site deliberately keeps the read
                # handle instead of ``_observation_sink``, and is byte-identical
                # to its pre-W0-A form. ``_synchronous_control_dispatch`` is
                # True only on the config-built simulator path, where
                # ``control.controller`` is required to be "simulator"; there
                # the source and the sink are the same BufferedRobotStateSource,
                # and a physical source cannot reach here at all (hardware needs
                # an explicitly injected manager, which sets this False). Every
                # write site that a physical source CAN reach — the control loop
                # and ``_collision_safe`` — goes through the sink.
                #
                # Keeping it identical keeps ``_dispatch_active`` inside
                # ``STOPPING_PREDICATE_PIN`` (tests/test_nominal_stop_wiring.py)
                # unmoved. This card has no business moving a stopping-predicate
                # ratchet: it changes nothing about how stops are classified.
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
            # Card P0-D, defect MOVE1-D1 (scrum/20260821/task_20/MOVE1_STATUS.md
            # §5). This was ``force(command)`` — the POST-gate command — which
            # put the acceleration ramp back at the value the gate had already
            # scaled, so the same scale was applied to its own output on the
            # next tick and the one after. Measured on the product path: 0.0279
            # m/s delivered where one application of the same gate to the same
            # 0.25 m/s policy gives 0.0591 m/s, on 100 % of 255 slowing ticks.
            #
            # ``sync_after_gate`` keeps the pre-gate ramp on an axis the gate
            # merely SCALED and collapses it on an axis the gate ZEROED, so a
            # stop is byte-identically a stop and a slow band finally means what
            # it says. No threshold moved and the gate order is unchanged: this
            # line records the gate's decision, it does not make one.
            self.velocity_smoother.sync_after_gate(command, now=now)
            # Card W6. The last thing before the SE2 hand-off, and after every
            # authority above it has spoken. Stops route to the emergency
            # bypass so no stop decision is ever smoothed.
            #
            # Card J-B splits that predicate by SEVERITY without moving a
            # single member out of the emergency set: every arm below is still
            # an emergency (instant zero + HARD finalize + resets), and the
            # only thing the flag can reclassify is a zero INTENT with no
            # emergency arm asserted.
            emergency_stopping = (
                proximity_state == "stopped"
                or self.arbiter.emergency_stopped
                or self._input_health_latched
                # An expired/absent intent stays fail-closed: no ramp.
                or active is None
            )
            # The *intent* decides, not the pre-gate smoother's ramp:
            # asking for zero is a stop even while the ramp is still
            # emitting a non-zero value on its way down.
            zero_intent = active is not None and _is_zero_command(active.command)
            stopping = emergency_stopping or zero_intent
            nominal_ramp = (
                self.motion_shaping.nominal_stop_ramp
                and self.motion_shaping.enabled
                and zero_intent
                and not emergency_stopping
            )
            previous_shaped = self._last_shaped
            if nominal_ramp:
                command, nominal_ramp = self._nominal_stop_ramp_tick(
                    command,
                    observation,
                    now=now,
                )
            if not nominal_ramp:
                self._resume_reset_after_nominal_ramp()
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
                nominal_stop=nominal_ramp,
                previous_command=(
                    VelocityCommand(
                        vx=previous_shaped[0],
                        vy=previous_shaped[1],
                        vyaw=previous_shaped[2],
                    )
                    if nominal_ramp
                    else None
                ),
            )
            if proximity_state != self._proximity_state:
                self._emit_proximity_change(proximity_state, now)
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

    def _nominal_stop_ramp_tick(
        self,
        command: VelocityCommand,
        observation: SimObservation | None,
        *,
        now: float,
    ) -> tuple[VelocityCommand, bool]:
        """One flag-ON nominal-stop tick: ramp, RE-GATE, then dispose.

        Card J-B, per skeptic 1's blocking finding. A decaying stop is only
        admissible if the safety layer sees the speed that is actually going to
        be actuated, so the ramp candidate is fed back through the UNTOUCHED
        ``apply_reactive_safety`` (plus the TTC verdict) as this tick's command.
        Three outcomes:

        * the gate clears it — the gate's own disposition is actuated and the
          shaper is re-synced to it, so the next ramp tick starts from the
          executed velocity and can never exceed what was approved;
        * the gate brakes it — the braked value is actuated (still monotone,
          the gate only ever scales translation down);
        * the gate stops it, or anything is malformed — ``(command, False)`` is
          returned, and the caller takes the untouched emergency path THIS tick
          (exact zero + every reset obligation).
        """

        self._nominal_stop_ramp_ticks += 1
        candidate = self._shape_for_actuator(
            command,
            now=now,
            stopping=False,
            nominal_stop=True,
        )
        disposed, verdict = self._regate_nominal_stop(candidate, observation, now=now)
        if verdict == "stopped" or not _finite_command_values(disposed):
            self._nominal_stop_preempt_ticks += 1
            return command, False
        if _command_translates(candidate) and not _command_translates(disposed):
            # The gate zeroed translation without naming the state 'stopped'
            # (input-health mask, stale telemetry, missing scan). Treat a
            # zeroed translation as the stop verdict it is.
            self._nominal_stop_preempt_ticks += 1
            return command, False
        self._motion_shaper.reset((disposed.vx, disposed.vy, disposed.vyaw))
        self._last_shaped = (disposed.vx, disposed.vy, disposed.vyaw)
        self._nominal_stop_ramping = True
        return disposed, True

    def _regate_nominal_stop(
        self,
        candidate: VelocityCommand,
        observation: SimObservation | None,
        *,
        now: float,
    ) -> tuple[VelocityCommand, str]:
        """Re-dispose one ramp candidate through the untouched reactive gate.

        ``owner_orbit`` is deliberately False here: it is the gate's *exemption*
        path (it drops the owner from the people list), so declining it makes
        the re-gate at least as strict as the tick's first pass, never weaker.
        """

        self._nominal_stop_regate_ticks += 1
        gated, proximity_state = apply_reactive_safety(
            candidate,
            observation,
            policy=self.reactive_safety_policy,
            owner_orbit=False,
            orbit_radius_m=0.0,
            now=now,
        )
        return self._time_to_collision_gate(gated, observation, proximity_state)

    def _resume_reset_after_nominal_ramp(self) -> None:
        """Zero the shaper on the first tick after a nominal ramp.

        Card J-B's resume-reset: a resume must not inherit the ramp's residual
        velocity, so the shaper starts the resume tick from exactly the state a
        flag-off resume would have started from (the emergency bypass zeroes it
        on every stop tick), making resume dynamics byte-equal across the flag.
        """

        if not self._nominal_stop_ramping:
            return
        self._reset_motion_shaper()

    def _shape_for_actuator(
        self,
        command: VelocityCommand,
        *,
        now: float,
        stopping: bool,
        nominal_stop: bool = False,
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

        self._apply_yield_advance_seed(command, stopping=stopping or nominal_stop)
        last = self._shaped_at
        dt_s = 0.1 if last is None else max(1e-3, min(0.25, now - last))
        self._shaped_at = now
        if nominal_stop:
            # Only the flag-ON nominal branch passes ``stop=``; the flag-off
            # call below stays byte-identical, keyword for keyword (an existing
            # W6 test wraps ``step`` with the historical signature and would
            # red on a new keyword appearing unconditionally — which is exactly
            # the identity property the standing rule asks for).
            vx, vy, vyaw = self._motion_shaper.step(
                (command.vx, command.vy, command.vyaw),
                dt_s=dt_s,
                emergency=stopping,
                stop=nominal_stop_step,
            )
        else:
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
        nominal_stop: bool = False,
        previous_command: VelocityCommand | None = None,
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
            # Card J-B. Only a live intent asking for zero, with the flag on and
            # the ramp already re-gated this tick, is NOMINAL; the expired-intent
            # arm above it stays fail-closed HARD. finalize_command still holds
            # the monotone boundary and falls closed to HARD with these resets.
            severity = (
                InterventionSeverity.NOMINAL_STOP
                if nominal_stop and active is not None
                else InterventionSeverity.HARD_STOP
            )
            candidate = shaped
        else:
            severity = InterventionSeverity.CLEAR
            candidate = shaped

        stages: tuple[ResetObligation, ...] = ()
        if (
            severity is InterventionSeverity.HARD_STOP
            or severity is InterventionSeverity.NOMINAL_STOP
        ):
            stages = (
                ResetObligation(
                    "velocity_smoother",
                    lambda: self.velocity_smoother.reset(now=now),
                ),
                ResetObligation("actuator_shaper", self._reset_motion_shaper),
            )
        if severity is InterventionSeverity.NOMINAL_STOP:
            decision = finalize_command(
                candidate,
                severity,
                downstream_stages=stages,
                previous_command=previous_command,
            )
        else:
            # Byte-identical to the pre-J-B call, keyword for keyword: the
            # mutation-oracle tests wrap ``finalize_command`` with the historical
            # signature, and flag-off dispatch must not notice this card.
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
        # Card J-B: the shaper is now at zero, so any nominal ramp in flight is
        # over. Every hard-stop reset obligation reaches here, which is what
        # makes the resume-reset unconditional rather than best-effort.
        self._nominal_stop_ramping = False

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
                # Card R4-lite, task_1 — Defect B.2. ENTRY into a blocked
                # episode, edge-triggered on the note: a dog that waits a full
                # minute for someone to pass records one row, not six hundred.
                # This is a visibility row only — it changes no gate, no
                # patience, and no command (owner-gated B22).
                self._note_mission_block(goal=place, note=command.note, blocked=state == "blocked")
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
            reason = command.note or mission_status
            self._log_mission_terminal(state=mission_status, goal=place, reason=reason)
            if mission_status == "arrived":
                self._emit("navigation", f"Arrived at {place}", "success")
            else:
                self._emit(
                    "navigation",
                    f"Navigation failed for {place}: {reason}",
                    "error",
                )
            self._narrate_mission_terminal(state=mission_status, goal=place, reason=reason)
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
            # ---- CARD ROAM-1: THE NAVIGATOR'S CLOCK -----------------------
            #
            # ONE LINE, and its absence was a buried Phase-5 defect. The
            # navigator reads ``extras["time_s"]`` in nine places — the
            # multi-object tracker's dt, the memory TTLs, the goal TTLs, the
            # recovery timers — and nothing on the PRODUCT path has ever
            # supplied it. ``pipeline.py:1949`` therefore fell to its
            # ``dt = 0.1`` literal on every tick regardless of ``loop_hz``, and
            # every ``float(extras.get("time_s") or 0.0)`` read zero, so no TTL
            # ever advanced: an entry written at t=0 was still "0 s old" ten
            # minutes later. The evals never caught it because
            # ``headless_city`` did not supply it either (fixed on the same
            # card, one line, same source).
            #
            # THE SOURCE IS THE SIM CLOCK, not ``time.monotonic()``. The
            # observation's own timestamp is what every other consumer of this
            # tick already agrees on (``_step_spatial`` measures staleness
            # against it, ``headless_city`` traces against it), and reading a
            # second clock here would make tracker dt disagree with the
            # freshness test applied to the same frame. The MuJoCo backend
            # already validates it into the monotonic range on the way in
            # (``backends/mujoco.py:123``), so it IS the runtime's monotonic
            # clock, sampled where the frame was.
            "time_s": float(observation.timestamp),
            # ---- END CARD ROAM-1 clock line -------------------------------
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
        """THE GROUNDING GATE ONLY. Not the whole camera. Read the scope note.

        Resolves whether ``_semantic_candidates`` may ground on pixels, in
        precedence order:

        1. ``PARCEL_CAMERA_INGRESS`` — an explicit on/off for THIS run, in both
           directions (unchanged from B4).
        2. ``camera_ingress.enabled`` — the legacy config section (unchanged).
        3. ``perception.camera_ingress`` — the C-1 block. Card P0-A added this
           term: the two spellings used to REFUSE each other at startup and now
           resolve, so an operator who turned on the C-1 block also gets pixel
           grounding instead of a ValueError.

        SCOPE, AND IT IS NARROWER THAN "ONE FLAG" (card P0-A, corrected under
        verification). This method is one of TWO consumers and the other one
        does not read it. ``_attach_configured_camera_ingress`` starts the C-1
        stream from ``self._camera_stream_config.enabled`` alone, so:

        * ``PARCEL_CAMERA_INGRESS=1`` with no ``perception.camera_ingress``
          gates grounding ON and the stream stays OFF.
        * ``PARCEL_CAMERA_INGRESS=0`` with ``perception.camera_ingress: true``
          gates grounding OFF and the stream still attaches.

        The env var is therefore an alias for the GROUNDING gate, not for the
        config key, and the stream follows the config key. Collapsing the last
        of it means editing the attach site, which is outside card P0-A's
        region; see scrum/20260822/task_1/P0A_STATUS.md "Handoffs".

        Default OFF, and off from all three ⇒ the oracle path is byte-identical.
        Grounding additionally requires an ATTACHED ingress: consenting to the
        camera is not the same as having one.
        """

        env = os.environ.get("PARCEL_CAMERA_INGRESS", "").strip().lower()
        if env in {"1", "true", "yes", "on"}:
            return True
        if env in {"0", "false", "no", "off"}:
            return False
        return self._camera_ingress_config_enabled or self._camera_stream_enabled

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

    # ---------------------------------------------------- Card C-1: the stream
    def _offer_camera_pose(self, observation: SimObservation) -> None:
        """Control-loop half of the pose mailbox. Cheap, bounded, non-foreign.

        Card C-1. Called from the 10 Hz loop AFTER emergency-stop adoption, so
        nothing here can sit between the simulator declaring a stop and the
        runtime adopting it. It takes one uncontended lock and writes three
        floats; it calls no producer method, so "the safety loop waits behind
        the camera" has no code path to happen through.
        """

        if not self._camera_stream_enabled:
            return
        robot = observation.robot
        x, y, yaw = float(robot.x), float(robot.y), float(robot.yaw)
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(yaw)):
            return
        with self._camera_stream_lock:
            self._camera_pose_slot = (x, y, yaw)
            self._camera_pose_at_monotonic = observation.timestamp
            self._camera_poses_offered += 1

    def _take_camera_pose(self) -> tuple[float, float, float] | None:
        """Worker half of the mailbox: ONE fresh pose permits ONE capture.

        Consuming the slot is what stops a stalled or disconnected simulator
        from being rendered forever at its last known pose — a camera that
        keeps producing confident frames of a world it can no longer see is
        worse than a camera that stops.
        """

        now = time.monotonic()
        with self._camera_stream_lock:
            pose = self._camera_pose_slot
            stamped = self._camera_pose_at_monotonic
            self._camera_pose_slot = None
            if pose is None or stamped is None:
                return None
            if not -0.05 <= now - stamped <= self.telemetry_stale_s:
                return None
            self._camera_poses_consumed += 1
            return pose

    def _publish_camera_frame(self, frame: CameraDetectionFrame) -> None:
        """Producer → runtime handoff. Bounded, counted, never blocking.

        Card C-1, work item 2. Runs on the camera worker thread. Takes ONLY
        ``_camera_stream_lock`` and never calls back into the producer, so it
        adds no edge to R24's lock roster and cannot deadlock against the
        control loop. Eviction is explicit: the newest frame wins and the loss
        is counted in both frames and detections, because "the queue was full"
        and "the camera saw nothing" must never look the same downstream.
        """

        if not isinstance(frame, CameraDetectionFrame):
            with self._camera_stream_lock:
                self._camera_stream_errors += 1
                self._camera_stream_last_error = "publish rejected a non-frame payload"
            return
        with self._camera_stream_lock:
            if len(self._camera_frames) == self._camera_frames.maxlen:
                evicted = self._camera_frames[0]
                self._camera_frames_dropped += 1
                self._camera_detections_dropped += len(evicted.detections)
            self._camera_frames.append(frame)
            self._camera_frames_published += 1
            self._camera_detections_total += len(frame.detections)
            if self._camera_stream_started_monotonic is None:
                self._camera_stream_started_monotonic = time.monotonic()
        self._offer_camera_frame_evidence(frame)
        # ---- CARD P1-B seam 2 of 3: the frame reaches the map. ----------
        # After the queue and after EV-1, outside ``_camera_stream_lock``, on
        # the camera worker thread. Takes only the map's own lock and never
        # calls back into the producer, so R24's lock roster is unchanged. A
        # no-op unless a learned map is installed (off-oracle only).
        self._p1b_feed_learned_map(frame)
        # ---- CARD OT-2 seam 1 of 3: the frame reaches the owner tracker. --
        # Last, outside ``_camera_stream_lock``, on the camera worker thread,
        # for P1-B's own reason one line up. A no-op unless an OwnerTracker is
        # installed; never raises.
        self._ot2_note_camera_frame(frame)
        # ---- END CARD OT-2 seam 1 ----------------------------------------

    def _offer_camera_frame_evidence(self, frame: CameraDetectionFrame) -> None:
        """Card C-1, work item 4. One bounded typed row per frame into EV-1.

        Non-blocking by construction (``_offer_evidence`` drops rather than
        waits). Raw arrays and embeddings never reach JSONL — only the typed
        frame dict, whose detection count is already capped by the producer's
        per-frame retention limit.
        """

        if self._session_evidence is None:
            return
        try:
            row = frame.as_dict()
            row["kind"] = EVIDENCE_KIND_CAMERA_FRAME
            self._offer_evidence(STREAM_EVENT, row)
        except Exception as error:  # noqa: BLE001 - evidence must not break the stream
            with self._camera_stream_lock:
                self._camera_evidence_refused += 1
                self._camera_stream_last_error = f"evidence: {type(error).__name__}"
            return
        with self._camera_stream_lock:
            self._camera_evidence_offered += 1

    def camera_detection_frame_slice(
        self, limit: int = 16
    ) -> tuple[CameraDetectionFrame, ...]:
        """Non-destructive newest-last view of the stream (panel / tests)."""

        count = max(0, min(int(limit), MAX_RETAINED_DETECTIONS * 16))
        with self._camera_stream_lock:
            if count == 0:
                return ()
            return tuple(self._camera_frames)[-count:]

    def drain_camera_detection_frames(
        self, limit: int = 64
    ) -> tuple[CameraDetectionFrame, ...]:
        """Bounded consumer handoff. THE seam C-2 will read; C-1 never grounds.

        Destructive: a drained frame leaves the queue. Returns oldest-first so a
        consumer sees the observation order the camera produced.
        """

        count = max(0, int(limit))
        drained: list[CameraDetectionFrame] = []
        with self._camera_stream_lock:
            while self._camera_frames and len(drained) < count:
                drained.append(self._camera_frames.popleft())
        return tuple(drained)

    def _attach_configured_camera_ingress(self) -> None:
        """Card C-1, work item 1. THE call site that was missing.

        Until this card, ``attach_camera_ingress`` had zero non-test callers:
        the whole pixel path was built and test-proven and had never once run
        inside the live robot. This is the composition root that changes that,
        and every hazard it has to clear is handled here rather than deferred:

        **EGL binding.** ``MUJOCO_GL`` binds the offscreen GL backend at the
        FIRST ``import mujoco`` in a process and cannot change afterwards. So
        this either sets it before that import, or — if something already
        imported MuJoCo under a different backend — REFUSES to start. It does
        not proceed hoping the binding is compatible; a silently software-
        rendered camera would be a perception stream that quietly is not one.

        **Whose MjData.** The panel process talks to the simulator over a
        socket and does NOT own the live ``MjModel``/``MjData``. So the camera
        renders a STATIC, once-forwarded copy of the same scene, with the free
        camera placed from the live robot pose. That is a real limitation and
        the snapshot says so out loud (``mode``, ``dynamic_actors_synced``)
        rather than letting an operator infer that the tile shows live people.

        Raises on any failure. ``start()`` treats that as a startup failure and
        tears the runtime down — asking for the eye and silently not getting it
        is the one outcome that must not be possible.
        """

        # ---- CARD VENUE-1 seam 1a of 2: what this run ADMITTED, both venues.
        # Correction pass, routed by the verifier. Two things that must happen
        # on EVERY started runtime — including one whose camera is off, which
        # is why this block sits above C-1's early return and not below it.
        #
        # 1. CAP-1's finding, taken here. The semantic-source binding is
        #    ONE-DIRECTIONAL: ``_p1b_install_learned_map`` returns before it
        #    calls ``use_semantic_source`` when the policy is ``oracle``, so a
        #    process that already bound ``learned_map`` — a harness, an earlier
        #    runtime, an eval driver — starts a runtime whose YAML says
        #    ``oracle`` and keeps reading the learned map. The composition root
        #    is where "what the file says" becomes "what the process does", so
        #    the binding is asserted here, in both directions.
        # 2. ``perception.detector`` is validated for BOTH venues. It is read
        #    only on a physical venue, so without this a typo on the simulator
        #    venue would be silently ignored — the exact class of defect CAP-1
        #    exists for.
        self._venue1_bind_semantic_source()
        detector_choice = self._venue1_detector_choice()
        # ---- END CARD VENUE-1 seam 1a of 2 ----------------------------------

        config = self._camera_stream_config
        if config is None or not config.enabled:
            return

        # ---- CARD VENUE-1 seam 1b of 2: which VENUE, before any GL decision. -
        # Card VENUE-1 (P1-A's declared HALT). Everything below this block is
        # C-1's MuJoCo venue and is reached only when no physical venue was
        # selected, so the flag-off path is unchanged by construction. The
        # ordering is load-bearing: `MUJOCO_GL` is written, and `mujoco` is
        # imported, a dozen lines further down, and a USB webcam has no GL
        # binding to get wrong — refusing to start because `MUJOCO_GL` is
        # unset would be a nonsense refusal for a camera that renders nothing.
        # See the VENUE-1 region below `_attach_configured_camera_ingress`.
        venue = self._venue1_resolve_venue()
        if venue is not None:
            self._venue1_attach_physical_ingress(venue, detector_choice)
            return
        self._venue1_state = None
        self._venue1_sim_detector_choice = detector_choice
        # ---- END CARD VENUE-1 seam 1b of 2 ----------------------------------

        import sys

        if "mujoco" in sys.modules:
            bound = os.environ.get("MUJOCO_GL", "").strip().lower()
            if bound != "egl":
                raise RuntimeError(
                    "perception.camera_ingress requires MUJOCO_GL=egl, but MuJoCo "
                    f"was already imported with MUJOCO_GL={bound or '<unset>'!r}; "
                    "the GL backend binds at first import and cannot be changed"
                )
        else:
            os.environ["MUJOCO_GL"] = "egl"

        from parcel_robot.camera_channel.channel import CameraChannelSpec
        from parcel_robot.camera_channel.ingress import (  # card P1-B: + the encoder seam
            CameraIngress,
            load_siglip2_embed_fn,
        )
        from parcel_robot.detection_adapter.owlv2_onnx import load_owlv2_detector
        from parcel_robot.perception_contention import default_guard
        from parcel_robot.sim import resolve_scene

        # `require_env=False` is correct here and is not a loosened gate: the
        # env switch exists so that merely having weights on disk never flips a
        # mission onto a heavy model by accident. An operator who wrote
        # `perception.camera_ingress: true` has already made that decision
        # explicitly, in the config, with the default being OFF.
        detector = load_owlv2_detector(require_env=False)
        if detector is None:
            raise RuntimeError(
                "perception.camera_ingress is enabled but the OWLv2 detector is "
                "unavailable (weights, onnxruntime or tokenizers missing); refusing "
                "to start a camera stream that cannot see"
            )

        scene = resolve_scene(self.store.path, None)
        import mujoco

        model = mujoco.MjModel.from_xml_path(str(scene))
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)

        spec = CameraChannelSpec.d455_go2_nominal()
        # ================= CARD P1-B: the encoders, at the attach site ======
        # Work item 1. Until this card the composition root passed no
        # ``embed_fn``, so every crop fell back to ``label_embedding`` — an
        # 8-dim hash of the WORD, which is a fingerprint of the detector's
        # label and contains nothing about the pixels. A map built on it can
        # only ever re-discover what the detector already said.
        #
        # Unavailable encoder => ``None`` => no embeddings, frames as before.
        # It is not a startup failure: the eye is worth having without it.
        embed_space = load_siglip2_embed_fn()
        ingress = CameraIngress.from_model_data(
            model,
            data,
            spec=spec,
            detector=detector,
            embed_fn=None if embed_space is None else embed_space[0],
            embedding_model_id="" if embed_space is None else embed_space[1],
            embedding_revision="" if embed_space is None else embed_space[2],
            embedding_preprocessing="" if embed_space is None else embed_space[3],
            # This ingress renders MuJoCo through EGL. There is no reading of
            # these pixels under which they are physical, and the map refuses a
            # store that mixes the two, so the venue is declared here.
            origin=EvidenceOrigin.SIMULATION.value,
            min_poll_interval_s=1.0 / config.rate_hz,
        )
        ingress.on_frame = self._publish_camera_frame
        ingress.contention_guard = default_guard()
        ingress.pose_source = self._take_camera_pose
        ingress.max_detections_per_frame = config.max_detections_per_frame
        # Refutation D-R1 (Fable, P0 verification). P0-D added
        # ``CameraIngress.pinned_queries`` and nothing ever set it, so the
        # operator's configured batch was dead code inside the ingress: it
        # survived a directive only because ``_set_camera_query_from_directive``
        # happened to re-supply ``config.queries`` by hand. Anything else that
        # calls ``set_query`` — the patrol driver, a curiosity refresh, a future
        # caller — silently narrowed the batch to its own phrase plus
        # ``person``. One line, and the pin is real.
        ingress.pinned_queries = tuple(config.queries)
        ingress.set_query(self._p1b_query_batch(tuple(config.queries)))
        # ================= END CARD P1-B ====================================
        self.perception_contention = ingress.contention_guard
        self._camera_scene_path = str(scene)
        self.attach_camera_ingress(ingress)

    # =====================================================================
    # CARD VENUE-1 — the runtime opens the PHYSICAL eye.  (ONE new region.
    # P1-B's three seams, P0-A's camera-flag regions, P0-D's dispatch and
    # CAP-1's startup-admission region are all elsewhere in this file.
    # Everything this card put in ``runtime.py`` carries the string
    # ``VENUE-1``, so one grep finds all of it: this region, **seam 1 of 2**
    # at the top of ``_attach_configured_camera_ingress`` above, and
    # **seam 2 of 2** inside ``camera_stream_snapshot`` below.)
    #
    # Why the region exists. P1-A built three physical ``CameraBackend``s
    # (``uvc``, ``realsense``, ``recorded``), a GPU detector daemon behind an
    # AF_UNIX socket, and the ``--camera`` launcher switch that exports
    # ``PARCEL_CAMERA_BACKEND`` — and then declared a HALT, because
    # ``_attach_configured_camera_ingress`` built the MuJoCo/EGL ingress
    # UNCONDITIONALLY. Every piece of the physical path existed and nothing
    # selected it, so a plugged-in camera fed nothing. This is the
    # composition root that selects the venue.
    #
    # Three properties this region holds, each of them a thing that was
    # silently wrong before it:
    #
    #   1. **A physical venue never imports or initializes MuJoCo.** Seam 1
    #      returns before the ``MUJOCO_GL`` preamble and before
    #      ``import mujoco``. A USB webcam has no GL binding to get wrong, and
    #      refusing to start because ``MUJOCO_GL`` is unset would be a
    #      nonsense refusal for a camera that renders nothing.
    #   2. **The published frame's origin comes from the backend that made
    #      the pixels.** ``CameraIngress.origin`` defaults to ``"unknown"``
    #      and the ingress never reads ``PhysicalCaptureBuffers.origin``
    #      (P1-B owns that file and the default is deliberate there: a
    #      renderer that could mint ``physical`` by default is the W0-A
    #      defect). So an ingress built without ``origin=`` publishes honest
    #      buffers and dishonest records — the defect Fable caught in P1-A's
    #      handoff snippet. Every construction here goes through P1-A's
    #      ``camera_ingress_kwargs``, which derives the declaration from the
    #      backend, and :meth:`_venue1_declared_origin` refuses to attach if
    #      the declaration is ever missing.
    #   3. **The map's writer says which world it is, and it is not inferred
    #      from "the camera stream is enabled".** See
    #      :meth:`_venue1_reconcile_map_origin`.
    #
    # What it deliberately does NOT do: it does not touch
    # ``camera_channel/ingress.py`` (P1-B) or the backends/daemon (P1-A), and
    # it adds no third camera-presence probe — ENV-1's
    # ``RealSenseIngestAdapter.device_report()`` and P1-A's
    # ``realsense.connected_devices()`` are the two that exist and the two
    # the refusal messages below point at.
    # =====================================================================

    #: Config spellings that mean "the simulator", i.e. no physical venue.
    #: The physical kinds themselves are P1-A's ``PHYSICAL_BACKEND_KINDS`` and
    #: are deliberately not re-spelled here — one list, one owner.
    _VENUE1_SIM_ALIASES: ClassVar[frozenset[str]] = frozenset(
        {"", "mujoco", "mujoco_egl", "sim", "simulation", "none", "off"}
    )

    #: The ingress the venue state describes. Compared BY IDENTITY in
    #: :meth:`_venue1_composition` so the operator surface stops claiming a
    #: physical camera the moment that ingress is detached or replaced —
    #: without it, ``detach_camera_ingress()`` leaves the wire saying
    #: ``real_camera: true`` with nothing attached (Fable, correction item 6).
    _venue1_ingress: Any = None

    #: ``perception.detector`` as the SIMULATOR venue saw it. The simulator
    #: does not honour the key; this is what makes that visible instead of
    #: silent.
    _venue1_sim_detector_choice: str = ""

    #: What venue this run is on, once one is attached. A class-level DEFAULT
    #: (never mutated in place; the attach rebinds it on the instance) so every
    #: runtime has it without this card editing ``__init__``, which belongs to
    #: another region. ``None`` on every simulator run — which is exactly what
    #: keeps the flag-off snapshot byte-identical to the build that never had
    #: this card.
    _venue1_state: dict[str, Any] | None = None

    def _venue1_resolve_venue(self) -> str | None:
        """Which venue this run's camera is, or ``None`` for the simulator.

        Precedence: ``PARCEL_CAMERA_BACKEND`` — the ONE spelling
        ``scripts/launch_stack.sh --camera`` exports, per P1-A's rule that the
        flag sets this and every consumer reads this — and then
        ``perception.camera_backend`` in the robot config, so a profile can
        state a venue without an env var (the key is listed in
        ``config.OVERLAY_INTRODUCIBLE_KEYS`` because ``configs/robot.yaml`` is
        SHA-locked and cannot grow it).

        A typo refuses BY NAME through P1-A's ``resolve_backend_kind`` rather
        than coming up on a different venue than the operator asked for.
        """

        from parcel_robot.camera_channel.backends.physical import (
            CAMERA_BACKEND_ENV,
            resolve_backend_kind,
        )

        raw = os.environ.get(CAMERA_BACKEND_ENV, "").strip()
        source = CAMERA_BACKEND_ENV
        if not raw:
            source = "perception.camera_backend"
            raw = str(self.store.section("perception").get("camera_backend", "") or "")
        raw = raw.strip()
        if raw.lower() in self._VENUE1_SIM_ALIASES:
            return None
        try:
            return resolve_backend_kind(raw)
        except ValueError as error:
            raise ValueError(f"{source}: {error}") from error

    def _venue1_bind_semantic_source(self) -> None:
        """Make the process-global semantic source equal the one the YAML names.

        CAP-1's finding, taken in this card's region on the verifier's routing.
        ``_p1b_install_learned_map`` binds the source only when the policy READS
        the learned map; under ``oracle`` it returns first, so the global is
        never RESET. In a process that has already bound ``learned_map`` the
        next runtime inherits it and reads a map its own configuration does not
        describe — the same defect CAP-1's G4 row guards, in the other
        direction.

        Binding the SOURCE is the whole fix: ``oracle`` means
        ``reads_learned_map`` is False, so a stale process-global map object is
        never consulted. The map object itself is deliberately left alone —
        clearing it here would tear down a map another runtime in the same
        process may still own.

        Runs after P1-B's installer (which is one line earlier in ``start()``)
        and re-asserts the same policy when the installer already bound it, so
        the two cannot disagree. Never raises: a malformed source has already
        raised inside the installer by the time this runs.
        """

        try:
            from parcel_robot.perception_source.selection import use_semantic_source
        except ImportError:  # pragma: no cover - frozen bundle path
            return
        policy = self._p1b_semantic_source()
        if policy is None:
            return
        try:
            use_semantic_source(policy)
        except Exception as error:  # noqa: BLE001 - a binding must not fail a boot
            logger.warning("could not bind the semantic source: %s", error)

    def _venue1_detector_choice(self) -> str:
        """``perception.detector``, validated. ``""`` means "decide from the env".

        Validated for EVERY venue, not just a physical one. The simulator venue
        does not honour the key at all — C-1's path always loads in-process
        OWLv2 — so without this a typo, or a deliberate ``daemon``, would be
        read by nothing and refuse nowhere. It is reported honestly on the
        simulator's composition block (``honoured: false``) rather than being
        quietly dropped.
        """

        choice = str(self.store.section("perception").get("detector", "") or "")
        choice = choice.strip().lower()
        if choice not in {"", "daemon", "in_process", "owlv2"}:
            raise ValueError(
                f"perception.detector must be 'daemon' or 'in_process' "
                f"(got {choice!r})"
            )
        return choice

    def _venue1_sim_detector_note(self) -> dict[str, Any]:
        """What the SIMULATOR venue does about ``perception.detector``: nothing.

        C-1's path always loads in-process OWLv2, so ``detector: daemon`` on
        the simulator is a knob the operator set and the product never read.
        Reported rather than dropped. Never raises — a snapshot is a surface,
        and an unstarted runtime may hold a value seam 1a has not validated
        yet, so a bad one is reported as ``invalid`` here and refuses there.
        """

        choice = self._venue1_sim_detector_choice
        if not choice:
            try:
                choice = self._venue1_detector_choice()
            except ValueError:
                choice = "invalid"
        return {
            "kind": "in_process",
            "configured": choice or None,
            # The simulator honours exactly the choices that MEAN in-process.
            "honoured": choice in {"", "in_process", "owlv2"},
        }

    def _venue1_attach_physical_ingress(
        self, kind: str, detector_choice: str = ""
    ) -> None:
        """Build and attach the ingress for a PHYSICAL venue. No MuJoCo.

        This is P1-A's handoff-1 change, landed. It runs the same six wiring
        lines the MuJoCo path runs — ``on_frame``, ``contention_guard``,
        ``pose_source``, ``max_detections_per_frame``, ``pinned_queries``,
        ``set_query`` — so a physical venue is the same runtime with a
        different eye, not a second code path with its own semantics.

        Raises on any failure, exactly as the MuJoCo path does: ``start()``
        treats that as a startup failure. Asking for the eye and silently not
        getting it is the one outcome that must not be possible.
        """

        config = self._camera_stream_config
        if config is None or not config.enabled:  # pragma: no cover - seam 1 guards
            return

        from parcel_robot.camera_channel.backends.physical import (
            PhysicalCameraUnavailable,
            camera_ingress_kwargs,
            open_physical_backend,
        )
        from parcel_robot.camera_channel.ingress import (
            CameraIngress,
            load_siglip2_embed_fn,
        )
        from parcel_robot.perception_contention import default_guard

        try:
            backend, resolved = open_physical_backend(kind)
            # OPENED HERE, not lazily on the first poll. Constructing a
            # `RealSenseCameraBackend` succeeds on a host with no camera —
            # `PhysicalCameraBackendBase.capture` opens on demand — so without
            # this line an absent D455 becomes a counted poll error minutes
            # into a mission instead of a refusal at startup with the device
            # census in the message. It also means a missing camera refuses
            # BEFORE 200 MB of onnxruntime is loaded for it.
            backend.open()
        except (
            PhysicalCameraUnavailable,
            FileNotFoundError,
            TypeError,
            ValueError,
        ) as error:
            raise RuntimeError(self._venue1_open_failure(kind, error)) from error

        kwargs = camera_ingress_kwargs(backend)
        origin = self._venue1_declared_origin(kwargs, resolved)
        detector, detector_note = self._venue1_detector(resolved, detector_choice)
        depth_available = self._venue1_depth_available(backend, resolved)
        # An encoder is the same decision on both venues, so it is made the
        # same way: unavailable => None => no embeddings and frames as before.
        # P1-A's `DaemonEmbedder` would avoid a second in-process copy of
        # SigLIP-2 next to the daemon's (3.4 ms warm over the socket) but it
        # RAISES when the daemon is away, and `CameraIngress` catches an
        # encoder failure and falls back to the label hash while still
        # stamping the SigLIP space — so switching to it needs P1-B's stamp
        # path looked at first. Handed off rather than guessed.
        embed_space = load_siglip2_embed_fn()
        ingress = CameraIngress(
            **kwargs,
            detector=detector,
            embed_fn=None if embed_space is None else embed_space[0],
            embedding_model_id="" if embed_space is None else embed_space[1],
            embedding_revision="" if embed_space is None else embed_space[2],
            embedding_preprocessing="" if embed_space is None else embed_space[3],
            min_poll_interval_s=1.0 / config.rate_hz,
        )
        ingress.on_frame = self._publish_camera_frame
        ingress.contention_guard = default_guard()
        ingress.pose_source = self._take_camera_pose
        ingress.max_detections_per_frame = config.max_detections_per_frame
        ingress.pinned_queries = tuple(config.queries)
        # ---- OT-2's §9.1 handoff, taken here on the verifier's routing -------
        # OT-2's ``_ot2_latest_rgb`` duck-types ``latest_rgb()`` on the attached
        # ingress and degrades to ``no_pixels`` without it, so on a live camera
        # the owner tracker keeps position tracks and asserts no identity — on
        # the ONE venue where identity from real pixels is the point. The
        # accessor OT-2 asks for belongs in ``CameraIngress`` (P1-B's file,
        # MUST NOT TOUCH), but a PHYSICAL backend already keeps the buffers it
        # just produced, so the composition root can supply it.
        #
        # The synchrony argument OT-2 records holds here for the same reason it
        # holds there, and it is a property of the caller: ``last_buffers`` is
        # written inside ``backend.capture()``, in the same ``poll_once`` that
        # builds and publishes the frame, and ``_ot2_note_camera_frame`` runs
        # synchronously inside that publish. No later capture can have swapped
        # the buffer in between. Any consumer that moves behind a queue would
        # desynchronize silently, which is why OT-2's handoff asks for the
        # pixels to be carried WITH the frame; this is the stop-gap, not that.
        ingress.latest_rgb = lambda: getattr(
            getattr(backend, "last_buffers", None), "color_rgb8", None
        )
        # ---- END OT-2 handoff ------------------------------------------------
        # There is no MuJoCo scene behind these pixels, and `composition.scene`
        # must not name one. It also makes `_p1b_scene_id()` name the VENUE
        # rather than resolving a scene file, on the re-derivation below.
        self._camera_scene_path = f"venue:{resolved}"
        # The venue is known now, so the runtime's own map can be stamped from
        # it BEFORE a single frame flows. `_p1b_install_learned_map` reads
        # `self._camera_ingress`, which is why this assignment is here and not
        # only inside `attach_camera_ingress` below.
        self._camera_ingress = ingress
        try:
            map_note = self._venue1_reconcile_map_origin(ingress, resolved)
        except Exception:
            self._camera_ingress = None
            self._camera_scene_path = ""
            try:
                backend.close()
            except Exception:  # noqa: BLE001, S110 - teardown best-effort
                pass
            raise
        self._venue1_ingress = ingress
        self._venue1_state = {
            "venue": resolved,
            "origin": origin,
            "origin_label": str(getattr(backend, "origin_label", "") or ""),
            "depth_available": depth_available,
            "detector": detector_note,
            "map": map_note,
        }
        ingress.set_query(self._p1b_query_batch(tuple(config.queries)))
        self.perception_contention = ingress.contention_guard
        self._camera_attach_note = ""
        logger.info(
            "camera venue=%s origin=%s depth=%s detector=%s map=%s",
            resolved,
            origin,
            depth_available,
            detector_note.get("kind"),
            map_note.get("state"),
        )
        if not depth_available:
            # P1-A measured this at the seam: `CameraIngress` needs metric
            # depth to place a box, so an RGB-only capture is a counted poll
            # error and NOTHING is published. That is the correct failure — a
            # constant assumed-depth plane would produce world coordinates
            # that look like measurements and are not — but it must be said
            # out loud at startup and on the operator's surface, not
            # discovered as a stream that never produces a frame.
            logger.warning(
                "camera venue=%s is RGB-only: depth_unavailable. The detector "
                "and the daemon run end to end, and CameraIngress publishes "
                "NOTHING without metric depth, so the map learns nothing on "
                "this venue. The D455 is the day-one device; no synthetic "
                "depth is substituted.",
                resolved,
            )
        self.attach_camera_ingress(ingress)

    def _venue1_declared_origin(self, kwargs: Mapping[str, Any], kind: str) -> str:
        """The venue's declared ``EvidenceOrigin``, or refuse to attach.

        The one line this whole card turns on. ``camera_ingress_kwargs``
        derives it from the backend producing the pixels; if it is ever
        absent or ``unknown`` the ingress would stamp every published frame
        ``unknown`` while the buffers behind it said ``physical`` — honest
        buffers and every derived record downstream dishonest, which is worse
        than no camera at all because it is invisible.
        """

        origin = str(kwargs.get("origin", "") or "").strip()
        if not origin or origin == EvidenceOrigin.UNKNOWN.value:
            raise RuntimeError(
                f"the {kind!r} camera venue produced no declared EvidenceOrigin "
                f"(got {origin or '<missing>'!r}). A published frame stamped "
                "'unknown' would let physical pixels enter the map, the evidence "
                "log and the store with no world attached to them; refusing to "
                "attach an eye that cannot say where it is looking from."
            )
        return origin

    def _venue1_depth_available(self, backend: Any, kind: str) -> bool:
        """Does this venue produce metric depth? Declared by the backend."""

        declared = getattr(backend, "has_depth", None)
        if isinstance(declared, bool):
            return declared
        spec = getattr(backend, "spec", None)
        band = getattr(spec, "depth_max_m", None)
        return kind != "uvc" and band is not None

    def _venue1_detector(
        self, kind: str, detector_choice: str = ""
    ) -> tuple[Any, dict[str, Any]]:
        """The detector for a physical venue: the daemon, or in-process OWLv2.

        The daemon is selected by ``perception.detector: daemon`` or, with no
        key, by the presence of ``PARCEL_PERCEPTION_SOCKET`` —
        ``scripts/launch_stack.sh --camera`` starts the daemon and exports
        exactly that variable, so the launcher's intent carries through
        without a second spelling.

        **A daemon that is not answering is NOT a startup refusal.** It is a
        typed degraded state: ``DaemonDetector`` returns no detections and
        reports ``stale``, the camera worker keeps its cadence, the 10 Hz
        control loop never touches the socket at all, and the state is on the
        operator's surface. That is the whole reason the detector was moved
        out of process — the worst case is a socket read that fails.
        """

        choice = detector_choice or self._venue1_detector_choice()
        socket_path = os.environ.get("PARCEL_PERCEPTION_SOCKET", "").strip()
        if choice == "daemon" or (not choice and socket_path):
            from parcel_robot.perception_daemon.client import DaemonDetector

            detector = DaemonDetector(socket_path or None)
            health = detector.health()
            note: dict[str, Any] = {
                "kind": "daemon",
                "socket": detector.socket_path,
                "reachable_at_attach": health is not None,
                "state": "live" if health is not None else "absent",
            }
            if health is None:
                logger.warning(
                    "camera venue=%s selected the detector daemon at %s and it "
                    "did not answer a health probe. Detections degrade to "
                    "empty+stale and the loop keeps running; start it with "
                    "scripts/launch_detector_daemon.sh --preload",
                    kind,
                    detector.socket_path,
                )
            else:
                note["provider_profile"] = health.get("provider_profile")
                note["detector"] = health.get("detector")
            return detector, note

        from parcel_robot.detection_adapter.owlv2_onnx import load_owlv2_detector

        detector = load_owlv2_detector(require_env=False)
        if detector is None:
            raise RuntimeError(
                f"the {kind!r} camera venue has no detector: in-process OWLv2 is "
                "unavailable (weights, onnxruntime or tokenizers missing) and no "
                "daemon was selected. Either start the daemon "
                "(scripts/launch_detector_daemon.sh --preload, which exports "
                "PARCEL_PERCEPTION_SOCKET) or set perception.detector: daemon; "
                "refusing to start a camera stream that cannot see."
            )
        return detector, {"kind": "in_process", "detector": str(getattr(detector, "name", ""))}

    def _venue1_reconcile_map_origin(self, ingress: Any, kind: str) -> dict[str, Any]:
        """The map's world is the FRAME's world — and a mismatch is refused.

        Two defects, one method.

        **1. The writer's origin was inferred from "camera streaming
        enabled".** ``_p1b_install_learned_map`` stamps the map's
        ``WriterProvenance`` ``simulation`` whenever ``_camera_stream_enabled``
        is true, and prefers ``self._camera_ingress.origin`` when an ingress
        exists — but seam 1 installs the map immediately BEFORE the attach
        (deliberately: off-oracle the query batch is ``known_places()`` of the
        reloaded map), so the ingress never existed yet and the guess always
        won. On a physical venue that guess is simply false: every place the
        dog saw with its own eyes would persist stamped ``simulation``.
        The caller sets ``self._camera_ingress`` before this runs, so
        re-running the installer takes P1-B's own declared branch and the
        writer is derived from the pixels.

        **2. The in-process mixing refusal could never fire.**
        ``OnlineSemanticMap._refuse_foreign_origin`` compares the writer's
        origin with the OBSERVATION's — and ``_p1b_feed_learned_map`` passes
        ``provenance=learned.provenance`` into ``observations_from_frame``, so
        the two sides of that comparison are the same object and it is
        vacuous. The mismatch that actually happens is a store of places from
        one world being reopened by a run whose frames come from another; the
        store's own refusal only fires on the NEXT load, after the file is
        already mixed. So it is checked here, at the composition root, before
        one frame flows: the venue's declared origin against the writer's and
        against every entry the map just reloaded.

        Returns a note for the operator's surface. Off-oracle only: under the
        shipping ``oracle`` source there is no learned map and this is inert.
        """

        learned = self._p1b_learned_map
        frame_origin = str(getattr(ingress, "origin", "") or "")
        if learned is None:
            return {"state": "no_learned_map", "frame_origin": frame_origin}

        from parcel_robot.online_map.entries import origins_conflict

        rederived = False
        writer_origin = str(learned.provenance.origin)
        if writer_origin != frame_origin:
            store_closed = self._p1b_store_closed
            self._p1b_close_learned_map(learned)
            try:
                self._p1b_install_learned_map()
            except Exception:
                # The old map's store is CLOSED and the new map never arrived,
                # so the runtime would otherwise carry a map whose store is
                # shut while ``_p1b_store_closed`` still read False — teardown
                # would then try to persist through a closed connection and
                # report a store it had not written. Say what is true and let
                # the venue refuse. (Fable, correction item 2.)
                self._p1b_store_closed = True
                self._venue1_drop_learned_map()
                raise
            self._p1b_store_closed = store_closed
            learned = self._p1b_learned_map
            rederived = True
            writer_origin = "" if learned is None else str(learned.provenance.origin)

        note: dict[str, Any] = {
            "state": "reconciled" if rederived else "agreed",
            "frame_origin": frame_origin,
            "writer_origin": writer_origin,
            "rederived_from_frame": rederived,
        }
        if learned is None:  # pragma: no cover - the installer kept the policy
            note["state"] = "no_learned_map"
            return note

        store = learned.store
        store_path = None if store is None else str(store.path)
        note["store"] = store_path
        note["reloaded_entries"] = len(learned)
        # The WRITER's declaration is a post-condition, not a guard: after the
        # re-derivation above it equals the frame's by construction. It is
        # checked anyway because "by construction" is exactly the kind of claim
        # that stops being true when someone edits the installer, and the cost
        # of being wrong here is a mixed store nothing can ever load again.
        if origins_conflict({writer_origin, frame_origin}):  # pragma: no cover
            self._venue1_drop_learned_map()
            raise RuntimeError(
                f"camera venue {kind!r} publishes {frame_origin!r} frames but this "
                f"run's online map writer is stamped {writer_origin!r}, and the "
                "re-derivation did not take. One map is one world; refusing to "
                "start rather than fuse two."
            )
        # What the STORE says it is. This fires on a file that declared a world
        # and holds no rows yet — the case the entry census below cannot see,
        # and the one a fresh venue is most likely to hit.
        declared = ""
        if store is not None:
            try:
                declared = str(store.get_meta("origin") or "")
            except Exception as error:  # noqa: BLE001 - a v1 store has no meta
                logger.debug("online map store has no origin meta: %s", error)
        note["store_origin"] = declared or None
        # What the ROWS say they are. A store can carry rows from a world its
        # meta never named (a run that never persisted its meta, a v1 file).
        foreign = sorted(
            {
                str(getattr(entry.provenance, "origin", EvidenceOrigin.UNKNOWN.value))
                for entry in learned.entries()
            }
            - {frame_origin}
        )
        mixed = [
            value
            for value in dict.fromkeys([declared, *foreign])
            if value and value != frame_origin and origins_conflict({value, frame_origin})
        ]
        if mixed:
            self._venue1_drop_learned_map()
            raise RuntimeError(
                f"camera venue {kind!r} publishes {frame_origin!r} frames, but the "
                f"online map at {store_path} is stamped {mixed} "
                f"({len(learned)} place(s) reloaded). One store is one world: a "
                "physical row and a simulated row are indistinguishable downstream, "
                "so this run would silently lend one world's places the other's "
                "credibility — and would leave a mixed file that nothing can load "
                "at all. Point PARCEL_ONLINE_MAP_PATH at a separate file per venue."
            )
        note["foreign_but_compatible"] = foreign
        return note

    def _venue1_drop_learned_map(self) -> None:
        """Release the map on a refused venue, so teardown cannot persist it.

        Without this, ``close()``'s seam 3 would write a physical-writer map
        into the very store the refusal was protecting.
        """

        learned = self._p1b_learned_map
        if learned is not None:
            self._p1b_close_learned_map(learned)
        self._p1b_learned_map = None
        try:
            from parcel_robot.perception_source.selection import use_learned_map

            use_learned_map(None)
        except Exception:  # noqa: BLE001, S110 - teardown best-effort
            pass

    def _venue1_open_failure(self, kind: str, error: Exception) -> str:
        """Why the venue would not open, with the remedy for THIS kind.

        The presence answer comes from the two probes that already exist —
        ENV-1's ``RealSenseIngestAdapter.device_report()`` (a ``/dev`` census
        with no vendor import) and P1-A's ``connected_devices()`` (serials off
        the bus). This card adds no third one.
        """

        detail = f"{type(error).__name__}: {error}"
        if kind == "recorded":
            remedy = (
                "name the clip in the camera config: PARCEL_CAMERA_CONFIG=/path/"
                "camera.json holding a 'clip' key with the .npz path (see "
                "camera_channel.backends.recorded.write_clip)."
            )
        elif kind == "realsense":
            serials: list[str] = []
            try:
                from parcel_robot.camera_channel.backends.realsense import (
                    connected_devices,
                )

                serials = connected_devices()
            except ImportError:
                # `connected_devices` already swallows a missing bus and an
                # unhappy SDK and answers `[]`; the only thing left that can
                # raise is the module not being importable at all.
                serials = []
            remedy = (
                f"RealSense devices on the bus: {serials or 'none'}. "
                "Attach the D455 and re-run; "
                "`.parcel/bin/python -m parcel_capture record --check` prints the "
                "device census and the attach remedy."
            )
        else:
            nodes = sorted(str(node) for node in Path("/dev").glob("video*"))
            remedy = (
                f"/dev/video* on this host: {nodes or 'none'}. Attach a UVC camera "
                "(and note that an RGB-only webcam cannot feed the depth-dependent "
                "ingress; the D455 is the day-one device)."
            )
        return (
            f"camera venue {kind!r} was selected (PARCEL_CAMERA_BACKEND or "
            f"perception.camera_backend) and could not be opened. {detail}. {remedy}"
        )

    def _venue1_composition(self) -> dict[str, object] | None:
        """``camera_stream_snapshot``'s ``composition`` block for a real venue.

        ``None`` on every simulator run, which is what keeps the flag-off
        snapshot byte-identical to the build that never had this card.

        Why it exists: C-1's literal describes the MuJoCo tile — a static
        scene copy posed from telemetry, ``real_camera: False``. On a physical
        venue every line of that is false, and an operator surface that says
        ``real_camera: false`` while a D455 is streaming is the same class of
        lie as a frame stamped ``unknown``. ``depth_available`` is here for
        the same reason: an RGB-only venue publishes nothing, and a
        depth-dependent gate must read ``depth_unavailable`` rather than an
        empty stream that looks like an empty room.
        """

        state = self._venue1_state
        if state is None:
            return None
        # Correction item 6. ``_venue1_state`` outlives the ingress it
        # describes, so this is compared BY IDENTITY rather than trusted:
        # after ``detach_camera_ingress()`` — or after something attaches a
        # DIFFERENT ingress — the venue is still the venue this run selected,
        # and there is no longer a camera behind it. Saying ``real_camera:
        # true`` with nothing attached is the same shape of lie as a frame
        # stamped ``unknown``.
        attached = (
            self._camera_ingress is not None
            and self._camera_ingress is self._venue1_ingress
        )
        depth_available = bool(state.get("depth_available", True))
        return {
            "mode": "physical_camera",
            "venue": state.get("venue"),
            "scene": None,
            "camera_pose_synced": True,
            # The pixels ARE the world: whatever moved in front of the lens is
            # in the frame. The static-scene caveat does not apply here.
            "dynamic_actors_synced": True,
            "robot_joint_state_synced": False,
            "attached": attached,
            "real_camera": attached
            and state.get("origin") == EvidenceOrigin.PHYSICAL.value,
            "evidence_origin": state.get("origin"),
            "origin_label": state.get("origin_label"),
            "depth_available": depth_available,
            "depth_note": (
                ""
                if depth_available
                else (
                    "depth_unavailable: this venue is RGB-only, so CameraIngress "
                    "publishes no frames and no depth-dependent gate can pass. No "
                    "synthetic depth is substituted."
                )
            ),
            "detector": dict(state.get("detector") or {}),
            "map": dict(state.get("map") or {}),
        }

    def venue_snapshot(self) -> dict[str, object] | None:
        """What venue this run's eye is on, or ``None`` for the simulator.

        The daemon's typed degraded state is read LIVE here rather than cached
        from attach time: "the daemon answered at startup" and "the daemon is
        answering now" are different facts and an operator needs the second.
        """

        composition = self._venue1_composition()
        if composition is None:
            return None
        ingress = self._camera_ingress
        snapshot = getattr(getattr(ingress, "detector", None), "snapshot", None)
        if callable(snapshot):
            try:
                composition["detector"] = {
                    **dict(composition.get("detector") or {}),
                    **dict(snapshot()),
                }
            except Exception as error:  # noqa: BLE001 - a surface must not raise
                logger.debug("venue detector snapshot failed: %s", error)
        return composition

    # ================= END CARD VENUE-1 region ===========================

    # =====================================================================
    # CARD P1-B — the camera -> online-map writer.  (NEW REGION; P0-A's
    # camera-flag regions, P0-B's transcript region and P0-D's dispatch /
    # directive-query regions are all elsewhere in this file.)
    #
    # Why this region exists at all: before it, the online semantic map had
    # ZERO product writers. It was constructed only inside its own test file,
    # so a map "the robot builds as it patrols" was, on the real robot, an
    # object that never existed. Everything below is the wiring that makes the
    # dog's own experience a thing that survives the process that had it —
    # observed, embedded, measured for relief, persisted on close, reloaded
    # next time.
    #
    # Three seams outside this region call in, each one line and each marked
    # with this card's name: ``_attach_configured_camera_ingress`` (the
    # encoder + the query batch), ``_publish_camera_frame`` (the feed) and
    # ``close()`` (the persist).
    # =====================================================================

    def _p1b_semantic_source(self) -> Any:
        """The ``SemanticSourcePolicy`` this runtime is operating under.

        C-3 put the axis in the NAVIGATION config's ``perception:`` block, next
        to ``tier``, and ``_install_perception_chain`` above reads that same
        block for the same reason. This resolves the file the robot config
        actually selects (``navigation.config``) rather than hardcoding
        ``default.yaml`` the way the tier reader does — otherwise a profile
        that points at ``configs/navigation/prototype.yaml`` would silently get
        the shipped source, which is precisely the "a cutover that never
        happened looks like the default" failure C-3 exists to prevent.

        Degrades to ``oracle`` — the shipping default, in which this whole
        region is inert — on any read failure. A malformed SOURCE is NOT
        swallowed, matching ``pipeline._semantic_source_policy``: a typo'd
        source that read as the default is the one failure worth crashing for.
        """

        try:
            from parcel_robot.perception_source.selection import SemanticSourcePolicy
        except ImportError:  # pragma: no cover - frozen bundle path
            return None
        section: Any = {}
        try:
            import yaml

            from parcel_robot.paths import resolve_navigation_config

            nav = self.store.section("navigation") or {}
            configured = str(nav.get("config") or "configs/navigation/default.yaml")
            raw = yaml.safe_load(
                resolve_navigation_config(configured).read_text(encoding="utf-8")
            )
            section = (raw or {}).get("perception") or {}
        except (OSError, ValueError, TypeError, KeyError, ImportError):
            return SemanticSourcePolicy()
        return SemanticSourcePolicy.from_mapping(section)

    def _p1b_map_settings(self) -> dict[str, Any]:
        """The ``perception.online_map`` block from the navigation config.

        Card P1-B's own keys live beside C-3's source axis because they are the
        same decision: a run that reads the learned map is a run that has to
        say where the map lives and what it is curious about. Absent block =>
        every default below, which is what an unmodified tree gets.
        """

        defaults: dict[str, Any] = {
            "persist_on_close": True,
            "reload_on_start": True,
            "curiosity_queries": [],
            "query_batch_from_known_places": True,
            "oracle_query_batch_from_scene": False,
            "visit_id_prefix": "runtime",
        }
        try:
            import yaml

            from parcel_robot.paths import resolve_navigation_config

            nav = self.store.section("navigation") or {}
            configured = str(nav.get("config") or "configs/navigation/default.yaml")
            raw = yaml.safe_load(
                resolve_navigation_config(configured).read_text(encoding="utf-8")
            )
            block = ((raw or {}).get("perception") or {}).get("online_map") or {}
        except (OSError, ValueError, TypeError, KeyError, ImportError):
            return defaults
        if not isinstance(block, Mapping):
            raise TypeError("perception.online_map must be a mapping")
        unknown = sorted(set(block) - set(defaults))
        if unknown:
            # Fail closed on spelling, exactly as the abstention and
            # semantic_source blocks do: a key nothing reads looks identical to
            # a switch that was never flipped.
            raise ValueError(
                f"unknown perception.online_map key(s): {', '.join(unknown)}; "
                f"known keys are {sorted(defaults)}"
            )
        merged = dict(defaults)
        merged.update(block)
        for flag in (
            "persist_on_close",
            "reload_on_start",
            "query_batch_from_known_places",
            "oracle_query_batch_from_scene",
        ):
            if not isinstance(merged[flag], bool):
                raise TypeError(f"perception.online_map.{flag} must be a boolean")
        curiosity = merged["curiosity_queries"]
        if not isinstance(curiosity, list) or not all(
            isinstance(item, str) for item in curiosity
        ):
            raise TypeError(
                "perception.online_map.curiosity_queries must be a list of strings"
            )
        merged["curiosity_queries"] = [c.strip() for c in curiosity if c.strip()]
        merged["visit_id_prefix"] = str(merged["visit_id_prefix"]).strip() or "runtime"
        return merged

    def _p1b_scene_id(self) -> str:
        """WHICH WORLD, by name — resolved, not inferred from a filename.

        Verification correction, 2026-08-22. This used to read
        ``Path(self._camera_scene_path or self.store.path).stem``, and
        ``_camera_scene_path`` is set by ``_attach_configured_camera_ingress``,
        which runs AFTER this card's install (deliberately — the query batch is
        built from the reloaded map). So the fallback always won and every
        entry in every run was stamped with the stem of the ROBOT CONFIG file:
        the dev-scene packs say ``scene_id: "p1b"``, the name of a throwaway
        YAML, where they meant ``city_block``. Not a safety defect —
        ``origin`` is what the store's mixing refusal reads — but a map
        outlives the run that wrote it, and an entry that cannot say which
        world it is from is a rumour with coordinates.

        Resolved through ``sim.resolve_scene``, the SAME function the camera
        attach uses, so the two cannot name different worlds. Degrades to
        ``unknown`` rather than to a misleading filename: not knowing is a
        legitimate answer and a wrong name is not.
        """

        try:
            from parcel_robot.sim import resolve_scene

            configured = self._camera_scene_path
            scene = (
                Path(configured)
                if configured
                else resolve_scene(Path(self.store.path), None)
            )
            return Path(scene).stem or "unknown"
        except Exception:  # noqa: BLE001 - a name must not fail a boot
            logger.debug("could not resolve a scene id for the map")
            return "unknown"

    def _p1b_install_learned_map(self) -> None:
        """Build the runtime's OWN map and install it on the mission path.

        Runs under ``semantic_source: shadow`` or ``learned_map`` only. Under
        the shipping ``oracle`` this returns immediately and nothing in this
        card exists as far as the process is concerned.

        The store comes from ``PARCEL_ONLINE_MAP_PATH`` through C-2's own
        resolver, whose R27 refusals are untouched and are the point: with no
        env var there is NO STORE, and a run therefore gets an in-process map
        that forgets everything — loudly, in the snapshot — rather than a
        silent temp file nobody audited. The owner's conversation store is
        refused by identity there, not here, so the two cannot drift.
        """

        policy = self._p1b_semantic_source()
        if policy is None or not policy.reads_learned_map:
            return

        from parcel_robot.online_map.entries import WriterProvenance
        from parcel_robot.online_map.online_map import OnlineSemanticMap
        from parcel_robot.online_map.store import OnlineMapStore
        from parcel_robot.perception_source.selection import use_learned_map, use_semantic_source

        settings = self._p1b_map_settings()
        origin = (
            EvidenceOrigin.SIMULATION.value
            if self._camera_stream_enabled
            else EvidenceOrigin.UNKNOWN.value
        )
        ingress = self._camera_ingress
        if ingress is not None:
            # The frames' own declaration wins over the runtime's guess: the
            # ingress knows whether it is rendering or looking.
            origin = str(getattr(ingress, "origin", origin) or origin)
        # The EV-1 session id when there is one, so a map entry and the
        # evidence log that recorded the frames behind it JOIN on one string.
        # Evidence can be disabled (``PARCEL_SESSION_EVIDENCE=0``), and a map
        # written under an empty session id would be a row nobody can trace, so
        # the fallback is still unique per process.
        session_id = self._session_evidence_id or f"runtime-{os.getpid()}-{int(time.time())}"
        provenance = WriterProvenance(
            session_id=session_id,
            seat="runtime_camera",
            detector_name=str(
                getattr(getattr(ingress, "detector", None), "name", None)
                or "camera_ingress"
            ),
            scene_id=self._p1b_scene_id(),
            origin=origin,
        )
        store: Any = None
        store_note = ""
        try:
            store = OnlineMapStore()
        except Exception as error:  # noqa: BLE001 - a refused store is a real answer
            store_note = f"{type(error).__name__}: {error}"
            logger.warning(
                "online map has no store this run (%s); the map will not "
                "persist. Set PARCEL_ONLINE_MAP_PATH to an absolute path or "
                "':memory:' to choose deliberately.",
                store_note,
            )
        self._p1b_learned_map = OnlineSemanticMap(
            store,
            provenance=provenance,
            reload=bool(settings["reload_on_start"]) and store is not None,
        )
        self._p1b_map_settings_cache = settings
        self._p1b_map_store_note = store_note
        self._p1b_map_reloaded = len(self._p1b_learned_map)
        self._p1b_visit_id = f"{settings['visit_id_prefix']}-{session_id}"
        use_semantic_source(policy)
        use_learned_map(self._p1b_learned_map)
        logger.info(
            "online map installed: source=%s store=%s reloaded=%d origin=%s",
            policy.source,
            None if store is None else store.path,
            self._p1b_map_reloaded,
            origin,
        )

    def _p1b_query_batch(self, configured: tuple[str, ...]) -> tuple[str, ...]:
        """The detector batch: configured + curiosity + what the map knows.

        Card P1-B work item 4, the half P0-D did not land. P0-D made
        ``set_query`` UNION rather than replace, which stopped a directive from
        taking the ``person`` safety lease away. This decides what goes INTO
        that union at attach time:

        * under ``learned_map`` — the places the map already knows
          (``known_places()``) plus the configured ``curiosity_queries``, so a
          robot that has learned "bench" keeps confirming benches and still
          asks about things it has never seen;
        * under ``oracle`` — the scene sidecar's own
          ``detector_query_set()``, which is the vocabulary that scene admits
          to having, rather than a list somebody typed twice.

        ``CameraIngress._with_pinned`` then caps the result at
        ``MAX_QUERY_PHRASES`` with ``person`` first and counts what it dropped,
        so a long curiosity list degrades visibly instead of blinding the eye
        (refutation D-R2).
        """

        batch: list[str] = [str(q).strip() for q in configured if str(q).strip()]

        def _extend(items: Any) -> None:
            for item in items or ():
                text = " ".join(str(item).split())
                if text and text not in batch:
                    batch.append(text)

        policy = self._p1b_semantic_source()
        reads_map = policy is not None and policy.reads_learned_map
        if reads_map:
            settings = self._p1b_map_settings_cache or self._p1b_map_settings()
            learned = self._p1b_learned_map
            if learned is not None and settings.get("query_batch_from_known_places"):
                try:
                    _extend(learned.known_places())
                except Exception:  # noqa: BLE001 - a query batch must not fail a boot
                    logger.warning("could not read known places for the query batch")
            _extend(settings.get("curiosity_queries"))
        elif self._p1b_map_settings().get("oracle_query_batch_from_scene"):
            # Available, and OFF by default — measured, then deliberately not
            # switched on. The sidecar's vocabulary for ``city_block`` is 34
            # phrases; the cap keeps 16 and drops 18, and the resulting frames
            # then hit ``camera_ingress_max_detections_per_frame`` hard. Two
            # 25 s oracle runs, same scene, same budget, one key apart
            # (evidence packs ``p1b_oracle_sidecar_batch`` vs ``p1b_flag_off``):
            #
            #   sidecar batch ON  : 632 of 1,016 detections TRUNCATED (62.2 %)
            #   operator's batch  :  57 of   404 detections truncated (14.1 %)
            #
            # Under ``oracle`` the camera grounds nothing — the GT oracle
            # supplies the candidates — so that cost buys a longer diagnostic
            # stream and no product behaviour. Off keeps the shipped default's
            # batch exactly ``perception.camera_ingress_queries``, as before
            # this card. Raise the per-frame cap before turning it on.
            try:
                from parcel_robot.scene_semantics import load_scene_semantics

                _extend(load_scene_semantics().detector_query_set())
            except Exception:  # noqa: BLE001 - the sidecar is optional
                logger.debug("no scene sidecar for the oracle query batch")
        return tuple(batch)

    def _p1b_feed_learned_map(self, frame: CameraDetectionFrame) -> None:
        """One published camera frame into the runtime's map. Card P1-B.

        Called from ``_publish_camera_frame`` on the CAMERA WORKER THREAD,
        after the frame is queued and outside ``_camera_stream_lock``. It takes
        one lock of its own and calls nothing back into the producer, so it
        adds no edge to R24's lock roster.

        Never raises. A map that cannot ingest must not be able to stop the
        camera publishing, exactly as a raising evidence sink must not — the
        failure is counted and the stream continues.
        """

        learned = self._p1b_learned_map
        if learned is None:
            return
        from parcel_robot.online_map.ingest import observations_from_frame
        from parcel_robot.online_map.online_map import MapRefused

        try:
            with self._p1b_map_lock:
                # ``note_frame`` FIRST and unconditionally, including for a
                # frame that found nothing: "looked and saw nothing" is the
                # denominator that makes detector support honest, and PG-3
                # refuses a term nobody asked about.
                learned.note_frame(queries=tuple(frame.queries or ()))
                learned.note_pose(float(frame.robot_x), float(frame.robot_y))
                observed = 0
                refused = 0
                for observation in observations_from_frame(
                    frame,
                    visit_id=self._p1b_visit_id,
                    provenance=learned.provenance,
                    # C-1 measured every frame expired at publish (562 ms p50
                    # against a 300 ms TTL). That is fatal to a REACTIVE claim
                    # and largely harmless to a CUMULATIVE one — a lamppost
                    # that was there 600 ms ago is still there — so the map
                    # ingests stale pixels and says so rather than pretending.
                    require_fresh=False,
                ):
                    outcome = learned.observe(observation)
                    observed += 1
                    if not outcome.persisted:
                        refused += 1
                self._p1b_frames_ingested += 1
                self._p1b_observations += observed
                self._p1b_refused += refused
        except MapRefused as error:
            with self._p1b_map_lock:
                self._p1b_errors += 1
                self._p1b_last_error = f"MapRefused: {error}"
            logger.warning("online map refused a frame: %s", error)
        except Exception as error:  # noqa: BLE001 - the map must not kill the eye
            with self._p1b_map_lock:
                self._p1b_errors += 1
                self._p1b_last_error = f"{type(error).__name__}: {error}"
            logger.warning("online map ingest failed: %s", error)

    def _p1b_persist_learned_map(self) -> int:
        """Write the map to its store on the way out. Card P1-B, work item 2.

        **This is the first parameter in this system that persists from the
        robot's own experience.** Everything else the runtime keeps across a
        restart was written by a person: a config, a pose table, a POI file.
        This is a thing the dog saw.

        Called from ``close()``. Never raises — teardown continues past every
        other subsystem's failure and must continue past this one — and returns
        the row count so a caller (and the snapshot) can tell "wrote nothing"
        apart from "did not try".
        """

        learned = self._p1b_learned_map
        if learned is None:
            return 0
        settings = self._p1b_map_settings_cache or {}
        if not settings.get("persist_on_close", True):
            logger.info("online map: persist_on_close is off; not writing")
            self._p1b_close_learned_map(learned)
            return 0
        if learned.store is None:
            logger.info(
                "online map: nothing to persist to (%s). %d entries are being "
                "dropped with the process.",
                self._p1b_map_store_note or "no store declared",
                len(learned),
            )
            return 0
        store_path = learned.store.path
        try:
            with self._p1b_map_lock:
                written = int(learned.persist())
                # Verification correction, 2026-08-22. The store opens
                # ``journal_mode=WAL``, so ``persist`` COMMITS the rows but
                # leaves them in ``<store>-wal`` until something checkpoints.
                # Nothing did: the map object was dropped with the runtime and
                # SQLite only checkpoints when the last connection closes, i.e.
                # at interpreter exit. Anything reading the store file during
                # or right after a run — an operator, a copy, an evidence pack
                # hashing it — saw fewer places than the robot had learned.
                # Closing INSIDE the lock, immediately after the write, is what
                # makes "it persisted" mean the bytes are in the file that has
                # the name.
                learned.close()
            self._p1b_persisted = written
            self._p1b_store_closed = True
            logger.info(
                "online map persisted %d entries to %s (WAL checkpointed)",
                written, store_path,
            )
            return written
        except Exception as error:  # noqa: BLE001 - teardown must continue
            self._p1b_last_error = f"persist {type(error).__name__}: {error}"
            logger.warning("online map persist failed: %s", error)
            # A failed persist must still release the file: leaving the
            # connection open would keep the WAL uncheckpointed on top of
            # having written nothing.
            self._p1b_close_learned_map(learned)
            return 0

    def _p1b_close_learned_map(self, learned: Any) -> None:
        """Release the map's store without persisting. Never raises."""

        try:
            with self._p1b_map_lock:
                learned.close()
            self._p1b_store_closed = True
        except Exception as error:  # noqa: BLE001 - teardown must continue
            logger.warning("online map store close failed: %s", error)

    def learned_map_snapshot(self) -> dict[str, object] | None:
        """What the robot has learned this run, or ``None`` when off.

        ``None`` — not a disabled block — for the same R1 reason
        ``camera_stream_snapshot`` returns ``None``: under the shipping
        ``oracle`` source the key is ABSENT from the wire, so a flag-off
        snapshot is byte-identical to a build that never had this card.
        """

        learned = self._p1b_learned_map
        if learned is None:
            return None
        with self._p1b_map_lock:
            stats = learned.stats()
            payload: dict[str, object] = {
                "frames_ingested": self._p1b_frames_ingested,
                "observations": self._p1b_observations,
                "refused": self._p1b_refused,
                "errors": self._p1b_errors,
                "last_error": self._p1b_last_error,
                "reloaded_entries": self._p1b_map_reloaded,
                "persisted_entries": self._p1b_persisted,
                # Whether the store file is self-contained yet. Until the
                # connection closes the newest rows live in ``<store>-wal``, so
                # a reader that copies the ``.sqlite3`` alone gets a stale map.
                "store_closed": self._p1b_store_closed,
                "visit_id": self._p1b_visit_id,
                # Honest about the store even — especially — when there is not
                # one: a run with no PARCEL_ONLINE_MAP_PATH looks exactly like
                # a run with one until close(), and then it is too late.
                "store_note": self._p1b_map_store_note,
            }
        payload.update(stats)
        return payload

    # ================= END CARD P1-B region ==============================

    # =====================================================================
    # CARD OT-2 — THE ROBOT STOPS BELIEVING THE OWNER AT 1.0.  (NEW REGION)
    #
    # P0-A's camera-flag regions, P0-B's transcript region, P0-D's dispatch
    # regions, P1-B's map region above, P2-A's owner-fact doors and P2-B's
    # affect/owner-event region are all elsewhere in this file. Three seams
    # outside this region call in, each ONE line and each marked with this
    # card's name: ``_publish_camera_frame`` (the frame), ``_control_loop``
    # (the overlay) and ``__init__`` (the state).
    #
    # WHY THIS REGION EXISTS. P1-C built an ``OwnerTracker`` that turns person
    # pixels into an identity confidence somebody measured, proved its failure
    # modes on a two-person clip, and wired NOTHING: no code in this file ever
    # constructed one, ``headless_city`` handed the control loop a mocap body
    # at confidence 1.0, and ``reactive_safety`` read that 1.0 through a floor
    # of 0.65. The running robot's answer to "is that your owner?" was a
    # literal, and the 08-22 audit said so.
    #
    # WHAT IT DOES. It owns an ``OwnerTracker`` and an ``OwnerFusionStub``,
    # feeds the tracker the camera's own detection frames on the camera worker
    # thread, fuses the result through P1-C's pixel seam, and overlays the
    # answer onto the observation the control loop is about to hand to
    # ``apply_reactive_safety``, the follow controller and P2-B's presence
    # watcher. With no tracker installed — the default, and every MuJoCo run —
    # every method here is a no-op and the observation passes through
    # untouched (row R5: 648 reactive-safety cases, byte-identical sha256).
    #
    # WHAT IT DELIBERATELY DOES NOT DO. It never writes an identity it did not
    # get from the producer, it never coasts a claim (a track the tracker has
    # lost degrades to ``searching`` with confidence 0.0 rather than repeating
    # the last good number), and it takes no lock of its own: the tracker runs
    # OUTSIDE every lock and only the finished answer is published under the
    # runtime's own ``_lock``, so R24's roster is unchanged and the camera
    # worker can never be found holding anything the control loop wants.
    # =====================================================================

    #: The producer states this runtime will publish. Mirrors
    #: ``owner_tracking.tracker``'s vocabulary; a test pins them equal.
    OT2_STATE_CONFIRMED: ClassVar[str] = "confirmed"
    OT2_STATE_AMBIGUOUS: ClassVar[str] = "ambiguous"
    OT2_STATE_SEARCHING: ClassVar[str] = "searching"

    #: How long a fused owner track stays usable. Deliberately the telemetry
    #: staleness the rest of the runtime already uses rather than a new knob:
    #: an identity older than the observation it would be attached to is not an
    #: identity, and inventing a second freshness budget is how two answers to
    #: "is this current" start disagreeing.
    def _ot2_track_ttl_s(self) -> float:
        return float(self.telemetry_stale_s)

    def install_owner_tracker(
        self,
        tracker: Any,
        *,
        gallery_threshold: float | None = None,
        fusion: Any = None,
    ) -> None:
        """Install P1-C's ``OwnerTracker`` as THE answer to "who is that".

        The composition root for the identity path, and it is a method rather
        than a constructor argument for the same reason
        ``attach_camera_ingress`` is: the tracker needs an encoder and a
        gallery that only exist once a camera venue has been resolved, which
        happens after this object is built.

        ``gallery_threshold`` is the operating point the ENROLLMENT measured.
        It is taken from the tracker's own gallery when not supplied, and it is
        needed here for one purpose: turning the tracker's absolute cosine into
        the HEADROOM the reactive gate reads (``score - threshold``). A tracker
        with no gallery can be installed — it will simply never claim anybody,
        which is P1-C's "zero owner claims without an enrolled gallery" row
        holding at runtime rather than only in a unit test.
        """

        threshold = gallery_threshold
        if threshold is None:
            gallery = getattr(tracker, "gallery", None)
            threshold = float(getattr(gallery, "threshold", 0.0) or 0.0)
        if fusion is None:
            from parcel_robot.uwb.fusion import OwnerFusionConfig, OwnerFusionStub

            fusion = OwnerFusionStub(OwnerFusionConfig(primary="vision"))
        with self._lock:
            self._ot2_owner_tracker = tracker
            self._ot2_owner_fusion = fusion
            self._ot2_gallery_threshold = float(threshold)
            self._ot2_owner_track = None
            self._ot2_owner_track_at = 0.0
            self._ot2_identity_state = self.OT2_STATE_SEARCHING
            self._ot2_identity_reason = "installed"

    @property
    def owner_track(self) -> Any:
        """P1-C's ``OwnerTrackV1`` for this tick, or ``None``.

        THE attribute P2-B's ``owner_presence_sample`` already reaches for with
        ``getattr(self, "owner_track", None)`` — that method was written as a
        drop-in seam for exactly this card and needs no edit: the moment this
        property starts returning a track, the greeting stops running on the
        mocap body's flat 1.0 and starts running on a measured identity.

        Returns ``None`` once the track is stale, which is what makes
        "I greeted you because I saw you" true rather than "I greeted you
        because I saw you eleven seconds ago".
        """

        with self._lock:
            track = self._ot2_owner_track
            stamped = self._ot2_owner_track_at
        if track is None:
            return None
        if time.monotonic() - stamped > self._ot2_track_ttl_s():
            return None
        return track

    def _ot2_latest_rgb(self) -> Any | None:
        """The pixels the boxes index, IF the attached ingress can hand them over.

        Duck-typed, and the reason is worth stating because it is the one gap
        in this card's chain. ``CameraDetectionFrame`` carries boxes and world
        coordinates and NO IMAGE (P1-C handoff 3), and ``ingress.py`` is P1-B's
        file, which every wave-2 card is told not to touch — so this card
        cannot add the frame-buffer handle the tracker wants. It asks for one
        instead: any ingress exposing ``latest_rgb()`` is used, anything else
        yields ``None``.

        ``None`` is a DEGRADE and not a failure: the tracker keeps position
        tracks, asserts no identity, and says ``no_pixels`` when asked why. The
        identity gate then withholds the relaxed band — the owner keeps a
        person's clearance, which is the correct answer to "can you see that
        this is your owner?" when the answer is no.

        **WHY A BARE ACCESSOR IS SAFE HERE, AND ONLY HERE** (Fable, OT-2 item
        6). ``latest_rgb()`` is a side channel: nothing in its signature ties
        the pixels to the frame whose boxes are about to index them. It is
        sound in this caller for one reason, and it is a property of the CALLER
        rather than of the accessor — ``_ot2_note_camera_frame`` runs
        synchronously on the camera worker thread, inside the same
        ``_publish_frame`` call that produced ``frame``, so no later capture can
        have replaced the buffer in between. Any OTHER consumer, or this one
        moved onto a queue, would need the pixels carried WITH the frame. That
        is the shape the handoff in ``OT2_STATUS.md`` §9.1 asks for, and it is
        why the handoff is not the one-liner the first draft called it.
        """

        ingress = self._camera_ingress
        source = getattr(ingress, "latest_rgb", None)
        if not callable(source):
            return None
        try:
            return source()
        except Exception as error:  # noqa: BLE001 - the eye may never end a frame
            logger.warning("owner tracker rgb source failed: %s", error)
            return None

    def _ot2_note_camera_frame(self, frame: Any) -> None:
        """Feed ONE published detection frame to the owner tracker.

        Runs on the camera worker thread, after ``_camera_stream_lock`` has
        been released and after P1-B's map feed, for P1-B's own stated reason:
        nothing that can take time may be reached while the camera's lock is
        held. The tracker itself runs under NO lock — it is single-threaded by
        construction and driven from exactly this one place — and only the
        finished ``OwnerTrackV1`` is published under ``_lock``.

        Never raises. A tracker that throws must degrade the identity, not kill
        the eye.
        """

        # Snapshotted under ``_lock`` (Fable, OT-2 item 6): this runs on the
        # camera worker while ``install_owner_tracker`` may be replacing the
        # tracker from another thread. The tracker is then driven OUTSIDE the
        # lock — it is the only expensive call here and holding ``_lock``
        # across it would put the control loop behind an encoder.
        with self._lock:
            tracker = self._ot2_owner_tracker
        if tracker is None:
            return
        try:
            update = tracker.update(frame, rgb=self._ot2_latest_rgb())
        except Exception as error:  # noqa: BLE001 - never break the camera worker
            logger.warning("owner tracker update failed: %s", error)
            with self._lock:
                self._ot2_errors += 1
                self._ot2_identity_state = self.OT2_STATE_SEARCHING
                self._ot2_identity_reason = f"tracker_error:{type(error).__name__}"
                self._ot2_owner_track = None
            return
        self._ot2_publish_update(update, frame)

    def _ot2_publish_update(self, update: Any, frame: Any) -> None:
        """Fuse one tracker update and publish it. The pixel seam, at runtime.

        The fusion call is P1-C's seam used exactly as its docstring describes:
        the ``vision`` argument carries POSE (bearing/range from the detection)
        and the ``pixel`` argument carries IDENTITY, and neither can be
        substituted for the other. Passing both is what makes the resulting
        ``OwnerTrackV1.identity_score`` a cosine somebody measured rather than
        ``OwnerFusionStub``'s 0.7 vision channel prior.

        A frame with no owner claim publishes the ABSENCE, not the last answer.
        """

        owner = getattr(update, "owner_track", None)
        state = str(getattr(update, "state", "") or self.OT2_STATE_SEARCHING)
        reason = str(getattr(update, "reason", "") or "")
        now = time.monotonic()
        if owner is None or not getattr(owner, "is_owner", False):
            with self._lock:
                self._ot2_frames_seen += 1
                self._ot2_owner_track = None
                self._ot2_owner_track_at = now
                self._ot2_identity_state = (
                    state if state in {self.OT2_STATE_AMBIGUOUS} else self.OT2_STATE_SEARCHING
                )
                self._ot2_identity_reason = reason or "no_owner_claim"
            return
        with self._lock:
            fusion = self._ot2_owner_fusion
            threshold = self._ot2_gallery_threshold
        if fusion is None:
            return
        try:
            now_ns = int(now * 1e9)
            source_ts = int(getattr(frame, "source_timestamp_ns", 0) or 0)
            sequence = int(getattr(frame, "sequence", 0) or 0)
            detection = owner.as_detection_msg(
                now_monotonic_ns=now_ns,
                source_timestamp_ns=source_ts,
                sequence=sequence,
            )
            pixel = owner.as_fusion_input(source_timestamp_ns=source_ts)
            result = fusion.fuse(
                robot_x=float(getattr(frame, "robot_x", 0.0) or 0.0),
                robot_y=float(getattr(frame, "robot_y", 0.0) or 0.0),
                robot_yaw_rad=float(getattr(frame, "robot_yaw_rad", 0.0) or 0.0),
                now_monotonic_ns=now_ns,
                vision=detection,
                pixel=pixel,
            )
        except Exception as error:  # noqa: BLE001 - never break the camera worker
            logger.warning("owner fusion failed: %s", error)
            with self._lock:
                self._ot2_frames_seen += 1
                self._ot2_errors += 1
                self._ot2_owner_track = None
                self._ot2_owner_track_at = now
                self._ot2_identity_state = self.OT2_STATE_SEARCHING
                self._ot2_identity_reason = f"fusion_error:{type(error).__name__}"
            return
        track = getattr(result, "track", None)
        # NOTE (Fable, OT-2 item 5): ``identity_score`` is a time-decayed EMA,
        # not the cosine the tracker compared against its threshold, so this is
        # the headroom of a SMOOTHED score and can go negative on a frame the
        # tracker confirmed. The error is one-directional — a lagging EMA can
        # only withhold the relaxed band, never invent headroom — and the fix
        # needs a field ``owner_tracking`` does not publish. See
        # ``OwnerTrack.identity_margin`` and OT2_STATUS.md §10.
        headroom = float(getattr(owner, "identity_score", 0.0) or 0.0) - float(threshold)
        with self._lock:
            self._ot2_frames_seen += 1
            self._ot2_owner_track = track
            self._ot2_owner_track_at = now
            self._ot2_identity_source = str(getattr(result, "identity_source", "") or "")
            self._ot2_identity_margin = headroom
            self._ot2_identity_state = str(
                getattr(track, "state", "") or self.OT2_STATE_SEARCHING
            )
            self._ot2_identity_reason = reason or str(getattr(result, "reason", ""))
            if track is not None and self._ot2_identity_state == self.OT2_STATE_CONFIRMED:
                self._ot2_owner_claims += 1

    def _ot2_apply_owner_identity(self, observation: Any) -> Any:
        """Overlay the MEASURED owner identity onto this tick's observation.

        The seam in the control loop, called immediately after
        ``backend.observe()`` so that everything downstream — the reactive
        gate, the follow controller, the orbit gate, P2-B's greeting watcher —
        reads one answer rather than each reaching for its own.

        With no tracker installed this returns the argument object itself, not
        a copy: the MuJoCo venue's path is not merely equivalent, it is the
        same object it always was.

        With a tracker installed and no fresh claim, the IDENTITY is replaced
        and the PERCEPTION is not: ``confidence=0.0``, ``state="searching"``,
        and ``visible`` carried through from whatever the backend reported.
        That is the card's rule 3 — after a loss the robot degrades to
        searching and never guesses — applied to the right field.

        **The split is a safety property and it was wrong in the first version
        of this method** (Fable, OT-2 verification, item 1). Overwriting
        ``visible`` with ``False`` does not "treat the owner as a stranger": in
        ``apply_reactive_safety`` the owner entry is appended only ``if
        observation.owner.visible``, so a False there **deletes the person from
        the gate's people list entirely** and costs them their CLEARANCE, not
        merely the relaxed band. A dog that cannot tell who you are must still
        not walk into you. So: identity is this method's to overwrite, and
        presence belongs to the channel that senses bodies. A degraded track at
        0.7 m still stops
        (``test_ot2_a_degraded_owner_still_gets_a_persons_clearance``).
        """

        if observation is None:
            return observation
        with self._lock:
            installed = self._ot2_owner_tracker is not None
            track = self._ot2_owner_track
            stamped = self._ot2_owner_track_at
            source = self._ot2_identity_source
            margin = self._ot2_identity_margin
            state = self._ot2_identity_state
        if not installed:
            return observation
        fresh = track is not None and (time.monotonic() - stamped) <= self._ot2_track_ttl_s()
        previous = observation.owner
        if not fresh:
            owner = OwnerTrack(
                owner_id=previous.owner_id,
                x=previous.x,
                y=previous.y,
                # PRESENCE, not identity: carried from the backend untouched.
                # See the docstring — a False here removes the owner from the
                # reactive gate's people list, which is a clearance change and
                # not a band change. This method may only ever answer "who".
                visible=previous.visible,
                confidence=0.0,
                state=self.OT2_STATE_SEARCHING,
                identity_source=source or IDENTITY_SOURCE_PIXEL_REID_UNCALIBRATED,
                identity_margin=0.0,
            )
            return dataclasses.replace(observation, owner=owner)
        pose = getattr(track, "pose", None)
        owner = OwnerTrack(
            owner_id=str(getattr(track, "enrolled_owner_id", previous.owner_id)),
            x=float(getattr(pose, "x", previous.x)),
            y=float(getattr(pose, "y", previous.y)),
            # True because a FRESH FUSED TRACK EXISTS — the camera localized a
            # body at this pose. Not ``state == confirmed``: that was the same
            # confusion the degrade branch had (Fable, item 1), and it would
            # have deleted an ``ambiguous`` person from the gate's people list
            # instead of costing them the relaxed band. Whether the gate
            # RELAXES around them is ``_owner_identity_trusted``'s question and
            # it reads ``state`` for itself.
            visible=True,
            confidence=float(getattr(track, "identity_score", 0.0) or 0.0),
            state=state,
            identity_source=source,
            identity_margin=float(margin),
        )
        return dataclasses.replace(observation, owner=owner)

    def owner_identity_snapshot(self) -> dict[str, object] | None:
        """What the identity path has done this run, or ``None`` when it is off.

        ``None`` rather than a disabled block, for the same R1 reason
        ``learned_map_snapshot`` and ``camera_stream_snapshot`` return it: a
        run with no tracker must produce a snapshot byte-identical to a build
        that never had this card.
        """

        with self._lock:
            if self._ot2_owner_tracker is None:
                return None
            return {
                "frames_seen": self._ot2_frames_seen,
                "owner_claims": self._ot2_owner_claims,
                "errors": self._ot2_errors,
                "state": self._ot2_identity_state,
                "reason": self._ot2_identity_reason,
                "identity_source": self._ot2_identity_source,
                "identity_margin": round(float(self._ot2_identity_margin), 6),
                "gallery_threshold": round(float(self._ot2_gallery_threshold), 6),
                # The one number the audit asked for: what the robot currently
                # believes, and it is never 1.0 unless a producer measured it.
                "identity_confidence": round(
                    float(getattr(self._ot2_owner_track, "identity_score", 0.0) or 0.0), 6
                ),
            }

    # ================= END CARD OT-2 owner-track region ==================

    def camera_stream_snapshot(self) -> dict[str, object] | None:
        """The operator's truth about the eye, or ``None`` when it is off.

        Returning ``None`` — not an ``{"enabled": false}`` block — is the R1
        discipline: with the feature off the key is ABSENT from the wire, so a
        flag-off snapshot is byte-identical to a build that never had C-1.
        """

        if not self._camera_stream_enabled:
            return None
        config = self._camera_stream_config
        now_monotonic_ns = time.monotonic_ns()
        with self._camera_stream_lock:
            frames = tuple(self._camera_frames)
            published = self._camera_frames_published
            frames_dropped = self._camera_frames_dropped
            detections_dropped = self._camera_detections_dropped
            detections_total = self._camera_detections_total
            errors = self._camera_stream_errors
            last_error = self._camera_stream_last_error
            started = self._camera_stream_started_monotonic
            evidence_offered = self._camera_evidence_offered
            evidence_refused = self._camera_evidence_refused
            attach_note = self._camera_attach_note
            poses_offered = self._camera_poses_offered
            poses_consumed = self._camera_poses_consumed
        ingress = self._camera_ingress
        newest = frames[-1] if frames else None
        # The age of the newest frame's PIXELS, not of its arrival.
        frame_age_s = None if newest is None else newest.age_ns(now_monotonic_ns) / 1e9
        # A separate clock for the newest frame that actually FOUND something:
        # an empty observation must advance liveness without inventing a
        # detection age it does not have.
        newest_with_detections = None
        for candidate in reversed(frames):
            if candidate.detections:
                newest_with_detections = candidate
                break
        detection_age_s = (
            None
            if newest_with_detections is None
            else newest_with_detections.age_ns(now_monotonic_ns) / 1e9
        )
        producer_stats = None if ingress is None else dict(ingress.stats.as_dict())
        callback_errors = int((producer_stats or {}).get("frame_callback_errors", 0))
        # `fault` means the STREAM is broken, not that one detect failed: a
        # transient render/detect error is counted and survived, but a publish
        # seam that raises means frames are being produced and lost, and an
        # operator must not read that as merely "stale".
        if errors or callback_errors:
            state = "fault"
        elif newest is None:
            state = "starting"
        elif newest.is_expired(now_monotonic_ns):
            state = "stale"
        else:
            state = "fresh"
        elapsed = None if started is None else max(1e-9, time.monotonic() - started)
        achieved_hz = None if elapsed is None else round(published / elapsed, 4)
        return {
            "enabled": True,
            "state": state,
            "fresh": state == "fresh",
            "config": None if config is None else config.as_dict(),
            "queue_capacity": self._camera_frames.maxlen,
            "queue_depth": len(frames),
            "frames_published": published,
            "frames_dropped": frames_dropped,
            "detections_retained_total": detections_total,
            "detections_dropped_with_frames": detections_dropped,
            "achieved_rate_hz": achieved_hz,
            "frame_age_s": None if frame_age_s is None else round(frame_age_s, 4),
            "last_detection_age_s": (
                None if detection_age_s is None else round(detection_age_s, 4)
            ),
            "detection_ttl_ms": DEFAULT_DETECTION_TTL_NS / 1e6,
            "newest_expired_at_publish": (
                None if newest is None else newest.expired_at_publish
            ),
            # Query-conditioned counts: this is what the dog was ASKED about and
            # found, never "everything the dog sees".
            "latest_class_counts": {} if newest is None else newest.class_counts(),
            "stream_errors": errors,
            "last_error": last_error or None,
            "attach_error": attach_note or None,
            "evidence_rows_offered": evidence_offered,
            "evidence_rows_refused": evidence_refused,
            "poses_offered": poses_offered,
            "poses_consumed": poses_consumed,
            # What this camera actually is, stated rather than implied. The
            # panel process talks to the simulator over a socket and does not
            # own its MjData, so the render is a STATIC copy of the same scene
            # posed from live telemetry. Moving actors and the robot's own
            # joint state are NOT in the render. An operator reading the tile
            # deserves to know that before trusting an empty person count.
            #
            # ---- CARD VENUE-1 seam 2 of 2 ------------------------------
            # ...and when the venue is a real camera, none of the paragraph
            # above is true. `venue_snapshot()` returns None on every simulator
            # run, so the literal below is what a flag-off snapshot still gets,
            # byte for byte. See the VENUE-1 region.
            #
            # It is `venue_snapshot()` and NOT `_venue1_composition()`, and the
            # difference is the whole point of the key: the former merges the
            # detector's LIVE state, the latter is frozen at attach time. A
            # daemon that died after startup must not still read `live` here
            # (Fable, correction item 1 — `venue_snapshot()` had no product
            # caller at all, so `/api/state` was frozen).
            # ---- END CARD VENUE-1 seam 2 of 2 --------------------------
            "composition": self.venue_snapshot() or {
                "mode": "static_scene_copy_pose_synced",
                "scene": self._camera_scene_path or None,
                "camera_pose_synced": True,
                "dynamic_actors_synced": False,
                "robot_joint_state_synced": False,
                "real_camera": False,
                # ---- CARD VENUE-1: the key this venue does NOT honour ------
                # `perception.detector` selects the out-of-process daemon on a
                # physical venue and is read by nothing here — C-1's path
                # always loads in-process OWLv2. An operator who set it
                # deserves to see that, rather than to infer it from a latency
                # number. Validated in seam 1a either way, so a typo refuses on
                # both venues.
                "detector": self._venue1_sim_detector_note(),
            },
            "producer": producer_stats,
            # PG-1's process-wide guard, which BOTH halves must share. The
            # counters make the registration falsifiable: `active_leases` rises
            # while a frame is inferring, and `refused` is the only place a
            # blocked generation would ever show up.
            "contention_guard": (
                None
                if self.perception_contention is None
                else dict(self.perception_contention.stats())
            ),
        }

    def _set_camera_query_from_directive(self, directive: str) -> None:
        """Tell the attached ingress to search for the directive's goal noun TOO.

        Cheap + best-effort: the open-vocab detector is queried for the goal noun
        phrase extracted from the raw navigation directive (``go to the lamppost``
        → ``lamppost``). A no-op when no ingress is attached.

        Card P0-D. This used to pass the bare noun, and ``set_query`` REPLACED
        the batch with it — so ``go to the bench`` deleted the operator's
        ``perception.camera_ingress_queries`` and, with them, the ``person``
        query the PG-1 safety lease rides on and ``patrol/mission.py`` requires.
        The configured batch is therefore re-supplied on every directive and the
        noun is appended to it. ``CameraIngress.set_query`` de-duplicates and
        pins ``person`` independently, so this holds even for an ingress that
        was attached without a config block.
        """

        ingress = self._camera_ingress
        if ingress is None:
            return
        phrase = _camera_query_from_directive(directive)
        if not phrase:
            return
        config = self._camera_stream_config
        configured = tuple(config.queries) if config is not None else ()
        ingress.set_query((*configured, phrase))

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
        #: Card R15. (activity label, completed, reason) for the ONE terminal
        #: this pass produced, or ``None``. Collected under the command lock and
        #: narrated after it is released: the narration path takes the lane's
        #: lock, and a control-loop step must never hold the command lock across
        #: another subsystem's.
        terminal: tuple[str, bool, str] | None = None
        with self._command_lock:
            if not self.spatial.active:
                return
            if (
                observation is None
                or time.monotonic() - observation.timestamp > self.telemetry_stale_s
            ):
                terminal = self._claim_orbit_terminal(
                    self.spatial.snapshot(), completed=False, reason="perception_unavailable"
                )
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
                    # Card R15 — the orbit terminal, claimed BEFORE the
                    # controller is stopped, because ``snapshot()`` is what says
                    # which behaviour this was and ``stop()`` clears the intent.
                    terminal = self._claim_orbit_terminal(
                        previous,
                        completed=decision.state == "completed",
                        reason=str(decision.reason),
                    )
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
        if terminal is not None:
            label, completed, reason = terminal
            self._narrate_activity_terminal(
                activity=label, completed=completed, reason=reason
            )

    def _claim_orbit_terminal(
        self,
        snapshot: Mapping[str, object],
        *,
        completed: bool,
        reason: str,
    ) -> tuple[str, bool, str] | None:
        """Card R15. Is THIS spatial terminal one the owner is owed a word about?

        Two noes, either of which means stay quiet: the behaviour that just
        ended is not the orbit the hosted lane started (a relative move, a
        typed circle), or the mark was never set / has already been claimed.
        One-shot, so a second terminal cannot re-narrate the first.

        One-shot means CHECK-THEN-CLEAR, so card R24 makes it one critical
        section under ``_lock``: the mark is set on the pump thread
        (``_realtime_orbit``) and cleared from two other places — here, on the
        control thread, and ``_stop_spatial_locked`` on whichever thread
        preempted the behaviour. Two claimers reading ``True`` before either
        wrote ``False`` would narrate one ending twice.
        """

        intent = snapshot.get("intent")
        behavior = str(intent.get("behavior", "")) if isinstance(intent, Mapping) else ""
        with self._lock:
            if not self._narratable_orbit:
                return None
            if behavior != "orbit_owner":
                return None
            self._narratable_orbit = False
        return ("circle around you", bool(completed), " ".join(str(reason).split()))

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
        if observation is not None and self._observation_sink is not None:
            # Fable audit item 2: the two seams are independent, so a source
            # that implements the sink but not the reader is protocol-violating
            # but reachable — and reading it unconditionally turned that into an
            # AttributeError here rather than a refresh. Absent reader == no
            # prior sample, which is exactly the "refresh it" case.
            state = (
                self._control_state_source.latest()
                if self._control_state_source is not None
                else None
            )
            if state is None or state.received_at < observation.timestamp:
                self._observation_sink.update_observation(observation)
        health = self._evaluate_dispatch_input_health(observation, now=decision_now)
        if health.stop_latched:
            # P0-B: LATCHED_STOP means latched. A single recovered tick must not
            # silently re-authorize motion, so this only ever sets the flag;
            # ``clear_input_health_latch`` (operator ack) is the only clear.
            self._input_health_latched = True
            self._input_health_latch_faults = tuple(
                f"{fault.required_input.value}:{fault.reason}"
                for fault in health.faults
                if fault.action is HealthAction.LATCHED_STOP
            )
        translation_allowed = health.translation_allowed and not self._input_health_latched
        if not translation_allowed and math.hypot(command.vx, command.vy) > 1e-6:
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
            not translation_allowed
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
            # Every authority-bearing sample is stamped from its PRODUCER, the
            # same way SCAN already was. Hard-coding PHYSICAL here let a
            # simulated pose sail through the ``sim_fixture_allowed=False``
            # check that exists to catch exactly that.
            pose_origin, pose_label = evidence_origin(observation.backend)
            pose = InputEvidence(
                captured_at=observation.timestamp,
                frame_id="odom",
                payload_valid=True,
                origin=pose_origin,
                fixture_label=pose_label,
            )
            scan = scan_evidence_from_observation(observation)
            # ---- CARD HW-2 go2-backend (scrum/20260822/task_40) ------------
            #
            # The line above stamps the scan from the OBSERVATION, and
            # ``evidence_origin`` returns SIMULATION for every observation by
            # construction (board D-1: the carrier type is the authority).
            # That is right for a simulated scan and it is why HW-3's verifier
            # measured a real Mid-360 band latching ``SCAN:
            # sim_fixture_forbidden`` under
            # ``requirements_requiring_physical_inputs()`` — the correct
            # fail-closed answer to "a physical sensor with no typed seam".
            #
            # This is the typed seam. A backend may carry a scan-evidence
            # source that DECLARES its origin
            # (``core/input_health.py:CommissionedScanSource``); when — and
            # only when — that declaration is PHYSICAL, the join reads the
            # source instead of the observation stamp.
            #
            # THREE THINGS MAKE THIS SAFE TO ADD HERE:
            #  1. ``declared_origin`` is a TYPED lookup (``control/base.py``):
            #     the string ``"physical"`` is not a declaration and reads back
            #     as UNKNOWN, so no name and no config value can reach this
            #     branch. The producer declares the origin by construction —
            #     ``backends/go2.py``'s recorded-fixture source declares
            #     REPLAY *because it reads a file* and still latches here.
            #  2. ``MujocoSocketBackend`` has no such attribute, so every
            #     pre-HW-2 path takes ``source is None`` and is byte-identical.
            #     The flag-off identity is structural, not a config read.
            #  3. ``evidence()`` returns None for NO SCAN, which the join reads
            #     as *missing* -> recoverable HOLD. It can only ever replace
            #     the stamp with a stricter or equal verdict, never manufacture
            #     a sample the sensor did not produce.
            #
            # ...AND ONLY AS A RE-STAMP. Corrected under verification (finding
            # H2, reproduced through a real runtime). `observe()` also runs on
            # HTTP handler threads (:6210, :9551) while the loop joins on an
            # observation it may have taken several ticks ago, so a source that
            # answered "what is the LATEST sweep?" let this join grade
            # observation N against sweep N+1 — and in one direction that
            # REMOVED a fault: a scan-less observation drew no SCAN fault at
            # all, where `scan_evidence_from_observation` says `missing ->
            # HOLD`. Two rules make claim #3 above true instead of hopeful:
            #
            #   1. `scan is None` (the observation carries no scan) short-
            #      circuits — the source may RE-STAMP the origin of a scan the
            #      observation HAS, and may never supply presence it lacks;
            #   2. `evidence(observation)` is KEYED: the source returns the
            #      datum built from the frames that produced THIS observation's
            #      ranges, or None, which leaves the observation's own stamp.
            source = getattr(self.backend, "scan_evidence_source", None)
            if (
                scan is not None
                and source is not None
                and declared_origin(source) is EvidenceOrigin.PHYSICAL
            ):
                restamped = source.evidence(observation)
                if restamped is not None:
                    scan = restamped
            # ---- END CARD HW-2 ---------------------------------------------
            # ---- CARD AWARE-1 (scrum/20260823/task_4) — SENSE-1 pose seam --
            #
            # The scan's twin, deliberately written as its own region rather
            # than folded into HW-2's: card SENSE-1 (scrum/20260823/task_3)
            # built `CommissionedPoseSource` (core/input_health.py:568) as the
            # parallel of `CommissionedScanSource` and proved its three rows AT
            # THE SEAM, but could not read it here — `runtime.py` was that
            # card's MUST-NOT-TOUCH, so its own STATUS names this join as the
            # one line it did not land. This is that line.
            #
            # ONE DELIBERATE DIFFERENCE FROM THE SCAN, and it is not an
            # oversight. HW-2 above may only ever RE-STAMP a scan the
            # observation HAS (`scan is not None`), because a source must never
            # supply presence the observation lacks. A pose is the other way
            # round: the block above stamps one UNCONDITIONALLY from the
            # observation, so there is no absence for the source to invent —
            # and if a commissioned PHYSICAL pose source has no datum for this
            # tick, the truth is "no physical pose", not "a simulated one".
            # Keeping the observation's SIMULATION stamp there would latch
            # `pose:sim_fixture_forbidden` on a real dog whose DDS stream
            # merely skipped a sample. So a declared-PHYSICAL source is
            # AUTHORITATIVE for pose: its answer replaces the stamp, and its
            # `None` becomes `pose:missing` -> recoverable HOLD, which is
            # exactly the row SENSE-1 measured
            # (`test_a_pose_the_source_has_no_datum_for_holds_and_never_stubs`).
            #
            # The same three things that make HW-2 safe make this safe:
            # `declared_origin` is a TYPED lookup so no string or config value
            # reaches this branch; `MujocoSocketBackend` has no such attribute
            # so every simulator path is byte-identical; and a REPLAY source
            # never satisfies the PHYSICAL test, so a replayed pose keeps the
            # observation's synthetic stamp and still latches.
            pose_source = getattr(self.backend, "pose_evidence_source", None)
            if (
                pose_source is not None
                and declared_origin(pose_source) is EvidenceOrigin.PHYSICAL
            ):
                pose = pose_source.evidence(observation)
            # ---- END CARD AWARE-1 ------------------------------------------

        feedback: InputEvidence | None = None
        state = (
            self._control_state_source.latest()
            if self._control_state_source is not None
            else None
        )
        if state is not None:
            # Card W0-A: provenance rides ON the datum. A source that declared
            # an origin keeps it; otherwise this wiring's structural
            # declaration applies (SIMULATION iff the runtime synthesized the
            # feedback itself, else whatever the source declared, else
            # UNKNOWN). ``RobotMotionState.source`` is now only a LABEL — it
            # names the fixture and can no longer decide authority.
            feedback_origin = (
                state.origin
                if state.origin is not EvidenceOrigin.UNKNOWN
                else self._control_state_origin
            )
            feedback = InputEvidence(
                captured_at=state.received_at,
                frame_id="base_link",
                payload_valid=state.fault_reason is FaultReason.NONE,
                origin=feedback_origin,
                fixture_label=(
                    state.source if feedback_origin in SYNTHETIC_ORIGINS else None
                ),
            )

        return evaluate_input_health(
            {
                RequiredInput.POSE: pose,
                RequiredInput.SCAN: scan,
                RequiredInput.CONTROLLER_FEEDBACK: feedback,
            },
            now=now,
            requirements=self._input_health_requirements,
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
        # Card EV-1. The ring keeps 100; the log keeps all of them. Offered
        # OUTSIDE the lock and after the append, because the log must never be
        # able to slow down or break the thing it is recording.
        self._offer_evidence(STREAM_EVENT, event)

    # --------------------------------------------------- session evidence log
    def _arm_session_evidence(self) -> None:
        """Open this session's JSONL evidence log (card EV-1, work item 1).

        Root and refusals are R17's, deliberately: the log lands in the SAME
        per-session folder as that session's ``owner.wav`` / ``robot.wav`` /
        ``index.json`` whenever audio capture is on, so an index byte range and
        an event row are the same session by construction rather than by a
        naming convention somebody has to keep. ``resolve_capture_dir`` also
        brings R17's two refusals with it — never inside ``evals/`` (a live
        writer must not append into the fixtures a run is scored against) and
        never resolved against the cwd.

        Default ON, and that is not the same decision R17's ``capture:`` made.
        Audio is the owner's household sound and is asked for in writing;
        these rows are the facts the panel already displays and the store
        already keeps, written down instead of evicted. ``PARCEL_SESSION_
        EVIDENCE=0`` turns it off for a run, which is the escape hatch an
        operator needs and not a thing a config file has to grow a key for.

        Never raises: an unusable evidence root degrades to "no log, and a
        panel event saying why". Losing the record is bad; refusing to start
        the robot because a directory is read-only would be worse.
        """

        if os.environ.get("PARCEL_SESSION_EVIDENCE", "1").strip().lower() in {
            "0",
            "false",
            "off",
            "no",
        }:
            self._session_evidence_note = "disabled by PARCEL_SESSION_EVIDENCE"
            return
        try:
            from parcel_robot.realtime.audio_gateway import new_capture_session_id
            from parcel_robot.realtime.config import resolve_capture_dir

            override = os.environ.get("PARCEL_SESSION_EVIDENCE_DIR", "").strip()
            capture_config = getattr(self.realtime_config, "capture", None)
            configured = getattr(capture_config, "dir", "recordings")
            root = resolve_capture_dir(override or configured)
            # One session id for BOTH artifacts. When capture is enabled the tee
            # mints its own id in `_build_realtime_sink`; the log is armed first,
            # so this id is the one the folder is named after and the tee is
            # handed it rather than minting a second one.
            self._session_evidence_id = new_capture_session_id()
            log = SessionEventLog(
                root=root,
                session_id=self._session_evidence_id,
                on_event=lambda message: self._emit("evidence", message, "info"),
            )
            # Assigned BEFORE start() so the log's own arming note is the first
            # thing IN the log rather than the one event it misses.
            self._session_evidence = log
            log.start()
        except Exception as error:  # noqa: BLE001 - evidence is never load-bearing
            self._session_evidence = None
            self._session_evidence_note = f"{type(error).__name__}: {error}"
            self._emit(
                "evidence",
                f"session evidence log unavailable ({error}); this session's "
                "events will only exist in the in-memory rings",
                "warning",
            )

    def _arm_spend_ledger(self) -> None:
        """Open the durable month-to-date spend ledger. Never raises.

        Card R25, work item 2. The file lives at ``<capture root>/spend.jsonl``
        — the SAME root the R17 recordings and the EV-1 evidence log use, and
        resolved by the same ``resolve_capture_dir``, which means it inherits
        that function's two guarantees for free: repo-relative paths resolve
        against the repo root rather than the cwd (the doubled-prefix incident
        of 2026-08-20), and a root inside ``evals/`` is refused outright, so a
        live spend ledger can never append into the frozen fixture tree a run is
        scored against.

        ``PARCEL_REALTIME_SPEND_LEDGER`` names an explicit file (a test's
        tmp_path, or an operator moving the ledger to a bigger disk) and
        ``PARCEL_SESSION_EVIDENCE_DIR`` moves the whole root. Both are read
        here rather than added to ``realtime.yaml``: this is an operator escape
        hatch, and a config key would be one more surface to typo on the one
        file whose typos this package refuses at load.

        A ledger that cannot be constructed is a WARNING and a ``None``, not a
        refusal to boot — the same fail-open direction the ledger itself takes
        when it cannot be read, for the same reason: a broken spend file must
        never brick the robot. With ``None``, ``RealtimeLane`` consults no
        ceiling at all and the pre-R25 behaviour is what ships.
        """

        try:
            from parcel_robot.realtime.config import resolve_capture_dir

            explicit = os.environ.get("PARCEL_REALTIME_SPEND_LEDGER", "").strip()
            if explicit:
                path = Path(explicit).expanduser()
            else:
                override = os.environ.get("PARCEL_SESSION_EVIDENCE_DIR", "").strip()
                capture_config = getattr(self.realtime_config, "capture", None)
                configured = getattr(capture_config, "dir", "recordings")
                path = resolve_spend_ledger_path(resolve_capture_dir(override or configured))
            self._realtime_spend_ledger = SpendLedger(
                path,
                # The ledger's warnings are the ONLY way a fail-open degradation
                # is heard, so they go to the panel's event ring (and through
                # `_emit`, to the evidence log) rather than to a logger.
                on_note=lambda message: self._emit("realtime", message, "warning"),
            )
            self._realtime_spend_note = str(path)
        except Exception as error:  # noqa: BLE001 - a ceiling may never block boot
            self._realtime_spend_ledger = None
            self._realtime_spend_note = f"{type(error).__name__}: {error}"
            self._emit(
                "realtime",
                f"monthly spend ledger unavailable ({error}); realtime."
                "monthly_budget_usd is NOT being enforced this run",
                "warning",
            )

    def _offer_evidence(self, stream: str, row: Mapping[str, object]) -> None:
        """Hand one ring row to the evidence log. Never raises, never waits."""

        log = self._session_evidence
        if log is None:
            return
        try:
            log.offer(stream, row)
        except Exception:  # noqa: BLE001 - the log may never break the runtime
            self._session_evidence = None

    def session_evidence_snapshot(self) -> dict[str, object]:
        """What ``/api/state`` says about the log. Off is a stated fact.

        Reported in the CONSTRUCTED arm of ``realtime_snapshot()`` only. R3's
        ``test_the_runtime_builds_a_broker_only_when_the_lane_is_enabled`` pins
        the flag-off snapshot key-for-key with the words "flag-off ⇒ the runtime
        boots identically; nothing new exists", and that is right: with no lane
        there is no session, so there is no session evidence to report and this
        card must not add a key there. Callers who want the fact regardless call
        this method.
        """

        log = self._session_evidence
        if log is None:
            return {"enabled": False, "reason": self._session_evidence_note or "not armed"}
        return log.snapshot()

    # ------------------------------------------------------------ mission log
    def _log_mission(
        self,
        kind: str,
        *,
        goal: str = "",
        state: str = "",
        reason: str = "",
        level: str = "info",
        text: str = "",
    ) -> dict[str, object]:
        """Record one mission lifecycle FACT and return the row.

        Card R4-lite, task_1 — Defect B. Separate from ``_emit`` on purpose,
        and additive to it: a terminal still emits a panel event, but the fact
        that a mission ENDED, when, and why now also lives somewhere the event
        deque cannot evict it. The owner's incident was a mission that started,
        ran, and finished with nothing to show for it anywhere.

        The caller may already hold ``self._lock`` (``_stop_navigation_channel``
        does); it is an RLock, so this is safe from inside or outside.
        """

        row: dict[str, object] = {
            "kind": str(kind),
            "goal": str(goal),
            "state": str(state),
            "reason": str(reason),
            "level": str(level),
            "text": str(text),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            self._mission_log_id += 1
            row["id"] = self._mission_log_id
            if kind == MISSION_LOG_BLOCKED:
                # Blocked rows are the chatty kind, so they evict each other
                # before they evict anything else. A mission that spends a
                # minute behind a pedestrian stream must still be able to show
                # that it started and how it ended.
                blocked = [
                    existing
                    for existing in self._mission_log
                    if existing["kind"] == MISSION_LOG_BLOCKED
                ]
                if len(blocked) >= MISSION_LOG_BLOCKED_MAX:
                    self._mission_log.remove(blocked[0])
            self._mission_log.append(row)
        # Card EV-1. Offered after the ring append and outside the lock, for the
        # same reason as `_emit`: the record may never slow the runtime down.
        self._offer_evidence(STREAM_MISSION, row)
        return row

    def _log_mission_terminal(self, *, state: str, goal: str, reason: str) -> None:
        """The one call every mission terminal makes, whatever ended it.

        Also closes the blocked-entry edge, so the next mission that gets
        blocked records its own entry rather than being swallowed by the last
        one's note.
        """

        arrived = str(state) in MISSION_ARRIVED_STATES
        # A new mission starts with a clean slate: its first block is a fact
        # about IT, and must not be swallowed by the previous mission's rate
        # limit or attributed to the previous mission's block class.
        self._mission_block_note = None
        self._mission_block_emit_at_s = None
        self._mission_block_coalesced = 0
        self._log_mission(
            MISSION_LOG_ENDED,
            goal=goal,
            state=state,
            reason=reason,
            level="success" if arrived else "warning",
            text=(
                f"Arrived at {goal}."
                if arrived
                else f"Mission to {goal} ended ({state}): {reason or 'no reason given'}."
            ),
        )

    # ------------------------------------------------------------- safety log
    def _log_safety(
        self,
        kind: str,
        *,
        source: str = "",
        phrase: str = "",
        rule: str = "",
        door: str = "",
        level: str = "warning",
        text: str = "",
        detail: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Record one safety lifecycle FACT and return the row (card R21).

        The same separation ``_log_mission`` makes, for the same reason: a panel
        event is a NOTIFICATION and lives in a 100-slot deque every chatty source
        in the runtime shares; this is the RECORD, and nothing but another safety
        event can push it out. live_run_1 is what the notification-only design
        costs — the single most important state change of a six-minute session,
        gone from the artifacts fourteen seconds after it happened.

        The caller may already hold ``self._lock`` or ``self._command_lock``;
        ``_lock`` is an RLock and ``_command_lock`` → ``_lock`` is the ordering
        every other write on this path already uses.
        """

        row: dict[str, object] = {
            "kind": str(kind),
            "source": str(source),
            "phrase": str(phrase),
            "rule": str(rule),
            "door": str(door),
            "level": str(level),
            "text": str(text),
            "count": 1,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if detail is not None:
            row["detail"] = dict(detail)
        with self._lock:
            self._safety_log_id += 1
            row["id"] = self._safety_log_id
            if kind == SAFETY_LOG_REJECTED:
                # Refusals evict each other before they evict anything else. A
                # robot that spends two minutes refusing tool calls must still
                # be able to show the latch that is refusing them.
                rejected = [
                    existing
                    for existing in self._safety_log
                    if existing["kind"] == SAFETY_LOG_REJECTED
                ]
                if len(rejected) >= SAFETY_LOG_REJECTED_MAX:
                    self._safety_log.remove(rejected[0])
            self._safety_log.append(row)
        # Card EV-1. R21 gave this ring 24 slots and capped refusals at half so
        # the cause could never be evicted by its consequences. The log removes
        # the arithmetic: nothing is evicted at all, and a session with a
        # hundred refusals still shows its latch.
        self._offer_evidence(STREAM_SAFETY, row)
        return row

    def _log_safety_latch(
        self,
        *,
        source: str,
        phrase: str = "",
        rule: str = "",
        already_latched: bool,
    ) -> None:
        """The one call every emergency latch makes, whatever latched it.

        A REPEAT of the same source while already latched is folded into the row
        that is already there rather than appended. An owner shouting the stop
        phrase four times in one breath (2026-08-20 live_run_1, corpus queries
        32 and 33 merged) is ONE latch; the first row is the one that carries the
        words that did it and it is never overwritten by a later one.

        The phrase itself is deliberately not spelled anywhere in this file —
        ``realtime/ingress.py`` holds its only definition, and U33 is what the
        fourth copy of a stop grammar costs.
        """

        now = self._safety_clock()
        with self._lock:
            if already_latched:
                newest = self._newest_locked(SAFETY_LOG_LATCHED)
                if newest is not None and newest["source"] == source:
                    newest["count"] = int(newest.get("count", 1)) + 1
                    newest["detail"] = {
                        **dict(newest.get("detail", {})),  # type: ignore[dict-item]
                        "repeat_latches": int(newest.get("count", 1)),
                    }
                    return
            else:
                self._safety_latched_at_s = now
                self._safety_latch_source = source
        described = SAFETY_LATCH_SOURCE_WORDS.get(source, source or "an undeclared source")
        text = f"Emergency stop latched by {described}."
        if phrase:
            text = f"{text} Owner said: {phrase!r}"
        self._log_safety(
            SAFETY_LOG_LATCHED,
            source=source,
            phrase=phrase,
            rule=rule,
            level="error",
            text=text,
            detail={"already_latched": bool(already_latched)},
        )

    def _log_safety_release(self, *, source: str) -> None:
        """The release, with how long the latch had been up."""

        now = self._safety_clock()
        with self._lock:
            since = self._safety_latched_at_s
            self._safety_latched_at_s = None
            self._safety_latch_source = ""
        held = "" if since is None else f" after {max(0.0, now - since):.1f} s"
        described = SAFETY_LATCH_SOURCE_WORDS.get(source, source or "an undeclared source")
        self._log_safety(
            SAFETY_LOG_RELEASED,
            source=source,
            level="success",
            text=f"Emergency stop released by {described}{held}.",
        )

    def _note_safety_rejection(self, door: str, reason: str) -> None:
        """One thing the robot refused to do because the latch is up.

        Coalesced by DOOR on this ring's own monotonic clock. Never dropped: a
        repeat inside the window increments the count on the row already there,
        so the log undercounts nothing it does not also say it is folding.

        Only recorded while the arbiter is actually latched, so an ordinary
        refusal (unknown pose, malformed arguments) never lands here.
        """

        if not self.arbiter.emergency_stopped:
            return
        clean_door = " ".join(str(door).split()) or "motion"
        clean_reason = " ".join(str(reason).split())
        now = self._safety_clock()
        with self._lock:
            newest = self._newest_locked(SAFETY_LOG_REJECTED)
            if newest is not None and newest["door"] == clean_door:
                stamped = newest.get("detail", {})
                last_s = float(stamped.get("at_s", 0.0)) if isinstance(stamped, dict) else 0.0
                if now - last_s < SAFETY_REJECT_MIN_INTERVAL_S:
                    count = int(newest.get("count", 1)) + 1
                    newest["count"] = count
                    newest["text"] = (
                        f"Refused {clean_door} while emergency-stopped "
                        f"(x{count}): {clean_reason}"
                    )
                    return
        self._log_safety(
            SAFETY_LOG_REJECTED,
            source=self._safety_latch_source,
            door=clean_door,
            level="warning",
            text=f"Refused {clean_door} while emergency-stopped: {clean_reason}",
            detail={"at_s": now, "reason": clean_reason},
        )

    def _refuse_under_latch(self, door: str) -> NoReturn:
        """Refuse one motion door because the emergency stop is latched.

        Card R21. Every ``if self.arbiter.emergency_stopped: raise`` in this
        class funnels here so the refusal is RECORDED as well as raised. The
        exception message is byte-identical to the one these sites raised
        before — ``core/arbiter.py`` and ``safety.py`` produce their own
        wording for their own layers, and nothing here reaches for theirs.
        """

        self._note_safety_rejection(door, MOTION_DISABLED_BY_LATCH)
        raise RuntimeError(MOTION_DISABLED_BY_LATCH)

    #: Card F1-SI. The ingress class every hosted MOTION TOOL is gated as. Not
    #: an ingress kind the scanner can produce — it is the class of "the model
    #: asked to move the robot" — and it is deliberately not
    #: :data:`~parcel_robot.realtime.ingress.KIND_EMERGENCY`, so ``gates_kind``
    #: returns True for it and no tool call can ever borrow the latch's exemption.
    VOICE_KIND_TOOL = "tool"

    #: How each gated tool reads inside the refusal the OWNER (or a visitor)
    #: hears. Written out rather than derived from the tool name because
    #: ``tool.replace("_", " ")`` produced *"I am not going to navigate to."* in
    #: this card's own live proof — a sentence that stops mid-thought. An unknown
    #: tool falls through to "do that", which is always grammatical.
    VOICE_TOOL_PHRASES: ClassVar[dict[str, str]] = {
        "navigate_to": "go there",
        "follow_owner": "follow you",
        "circle_owner": "walk around you",
        "play_gesture": "do that",
        "set_pose": "move like that",
        # Card ROAM-1. Written out like the five above it, for the reason the
        # comment above gives: "I am not going to roam." stops mid-thought.
        "roam": "go off exploring",
    }

    def _gate_by_voice(self, tool: str, call: Callable[..., str]) -> Callable[..., str]:
        """Wrap one hosted motion door with the speaker-identity gate (card F1-SI).

        WHY THE DOOR AND NOT THE BROKER
        -------------------------------
        The broker is the model's side of the wire and this card may not touch
        it; the DOOR is the runtime's own callable, which is precisely where R21
        put its latch watcher for the same reason. Wrapping here means the gate
        applies whatever the model calls the tool, in whatever order, through
        whichever disposition — and the broker's refusal mapping is unchanged
        because a refusal still arrives the way every other refusal does, as an
        exception the door raised.

        WHAT IT REFUSES, AND WHAT IT CANNOT
        -----------------------------------
        It refuses MOTION. It does not touch ``get_status`` or
        ``recall_memory``, it does not touch the latch (there is no stop tool —
        stopping is the ingress's own path, and this wrapper is not on it), and
        it does not stop the hosted model from ANSWERING an unverified voice.
        A visitor can still have a conversation with the robot and still stop
        it; what they cannot do is make it walk.
        """

        def _gated(*args: object, **kwargs: object) -> str:
            arming = self._voice_arming_for(self.VOICE_KIND_TOOL)
            if not arming.armed:
                gate = self.realtime_voice_identity
                speak = gate.note_rejection() if gate is not None else True
                self._emit(
                    "realtime",
                    f"voice identity REFUSED to arm {tool!r}: {arming.reason}",
                    "warning",
                )
                if speak:
                    self._whisper(
                        StateEvent(
                            kind=KIND_VOICE_REJECTED,
                            key=f"voice_rejected:{arming.code}",
                            fact=voice_rejection_fact(tool, "a spoken command"),
                            detail={"code": arming.code, "tool": tool},
                        )
                    )
                # A RuntimeError is what every other refusing layer raises here,
                # so the broker maps it to its ordinary refusal disposition and
                # the model narrates the refusal in its own words. Inventing a
                # new exception type would have been a change to the broker's
                # contract, which this card may not make.
                raise RuntimeError(
                    "I did not recognise the voice that asked for that, so I am not "
                    f"going to {self.VOICE_TOOL_PHRASES.get(tool, 'do that')}. "
                    "Anyone can still stop me."
                )
            result = call(*args, **kwargs)
            self._emit_voice_provenance(tool, arming)
            return result

        return _gated

    def _watch_under_latch(self, door: str, call: Callable[..., str]) -> Callable[..., str]:
        """Wrap one hosted motion door so its refusals are written down.

        Card R21, and it exists because ``_realtime_validate`` alone is NOT
        enough. ``SafetyLimits.validate`` reads ``agent.safety.emergency_stopped``,
        and that flag is set by the voice doors but NOT by
        ``action("emergency_stop")`` — so under a Space/panel latch the
        validator admits and the refusal happens deeper, in the activity
        coordinator or in local plan admission, both outside this card. Watching
        the door itself covers every latch origin and every refusing layer with
        one rule, and it records the refusing layer's OWN words.

        Refusals arrive here as exceptions: ``_realtime_gesture`` re-raises the
        coordinator's ``Rejected …`` disposition and ``_realtime_navigate``
        re-raises an admission refusal. Nothing is swallowed — the exception is
        always re-raised untouched, so the broker's own disposition mapping is
        exactly what it was.
        """

        def _watched(*args: object, **kwargs: object) -> str:
            try:
                return call(*args, **kwargs)
            except (RuntimeError, TypeError, ValueError) as error:
                # Gated inside `_note_safety_rejection`: a refusal with no latch
                # up is somebody else's business and records nothing.
                self._note_safety_rejection(door, str(error))
                raise

        return _watched

    def _realtime_validate(self, call: ToolCall) -> ToolResult:
        """The hosted broker's admission door, with the refusal written down.

        Card R21. ``SafetyLimits.validate`` is unchanged and still decides;
        this only notices. It is the seam live_run_1 measured — four
        ``Motion is disabled by emergency stop`` refusals of hosted tool calls,
        three of which were never mentioned to the owner and all four of which
        lived only in a 100-slot deque.

        The predicate is the validator's OWN latch flag, not a copy of its
        refusal string: a seventh copy of that sentence is exactly the U33 class
        of defect. The reason the validator gave is recorded verbatim, so a
        refusal that happened to be about something else says so.
        """

        result = self.agent.safety.validate(call)
        if not result.accepted and self.agent.safety.emergency_stopped:
            self._note_safety_rejection(f"tool {call.name}", result.message)
        return result

    def _newest_locked(self, kind: str) -> dict[str, object] | None:
        """The most recent row of ``kind``, or None. Caller holds ``_lock``."""

        for row in reversed(self._safety_log):
            if row["kind"] == kind:
                return row
        return None

    @property
    def safety_log(self) -> list[dict[str, object]]:
        """The safety lifecycle ring, oldest first (card R21)."""

        with self._lock:
            return [dict(row) for row in self._safety_log]

    def _safety_latch_state(self) -> dict[str, object]:
        """The standing latch fact, for anything that has to report it.

        Read from the arbiter, never from a cached flag, so a latch this runtime
        did not itself record (an adopted simulator stop, a future watchdog) is
        still reported as latched.
        """

        latched = bool(self.arbiter.emergency_stopped)
        with self._lock:
            since = self._safety_latched_at_s
            source = self._safety_latch_source
        state: dict[str, object] = {"latched": latched}
        if not latched:
            return state
        state["source"] = source or SAFETY_SOURCE_API
        if since is not None:
            state["seconds_latched"] = round(max(0.0, self._safety_clock() - since), 1)
        # Not an instruction to the model — a fact about the world it is being
        # asked to describe. live_run_1 spent 84 seconds with an owner giving
        # orders to a latched robot because nothing on any surface said this.
        state["release"] = (
            "the emergency stop must be released before the robot can move; "
            "the owner releases it with the panel's release button"
        )
        return state

    def _emit_proximity_change(self, proximity_state: str, now: float) -> None:
        """One proximity transition, coalesced (card R4-lite, task_1 — Defect C).

        The transition is still edge-triggered and the state still advances on
        every edge — nothing here changes a gate, a stop, or a speed. What
        changes is the EVENT: a robot hovering on the slow/clear threshold used
        to flip at the 10 Hz control rate and push ~10 events a second into a
        100-slot deque, flushing every other source's history — including a
        mission terminal — in about ten seconds.

        Transitions inside the window are counted, not discarded, and the count
        rides on the next line that does go out. A transition INTO ``stopped``
        is a hard safety fact and is never withheld; it flushes the window so
        the count it carries is honest.
        """

        previous = self._proximity_state
        self._proximity_state = proximity_state
        if proximity_state == "stopped":
            message = "Proximity stop: obstacle too close"
            level = "warning"
        elif proximity_state == "slowing":
            message = "Slowing near an obstacle"
            level = "info"
        elif previous != "clear":
            message = "Obstacle clearance restored"
            level = "success"
        else:
            return
        last = self._proximity_emit_at_s
        quiet = last is not None and (now - last) < PROXIMITY_EVENT_MIN_INTERVAL_S
        if quiet and proximity_state != "stopped":
            self._proximity_coalesced += 1
            return
        folded = self._proximity_coalesced
        self._proximity_coalesced = 0
        self._proximity_emit_at_s = now
        if folded:
            message = f"{message} (+{folded} more proximity changes in the last few seconds)"
        self._emit("safety", message, level)

    # ------------------------------------------------- model-side narration
    def _narratable(self) -> RealtimeLane | None:
        """The lane, only if it is genuinely free to be told something.

        Card R4-lite, task_1 — Defect B.3, and the floor gate the card names.
        Four independent noes, any one of which means stay quiet:

        * no lane, or no open session — nothing to tell;
        * the lane is mid-reconnect — a system item posted into a session that
          is being replaced is a system item nobody will ever read;
        * a hosted response is in flight — the model is SPEAKING, and pushing a
          new item under it is how you get two voices in one mouth;
        * the owner has the floor (a response is outstanding) — the robot does
          not interrupt the person who just asked it something.
        """

        lane = self.realtime_lane
        if lane is None or not lane.active or lane.recovering:
            return None
        if lane.playback_owned:
            return None
        return lane

    def _narrate_mission(self, text: str, *, critical: bool = False) -> bool:
        """Hand ONE sentence of fact to the model to say in its own words.

        Never a command and never speech: this posts a system item and asks for
        a response. The model narrates what the robot's own systems reported —
        it does not decide anything, which is the lane's standing guardrail.

        ``critical`` is card R25's cost-ceiling asymmetry, carried from the
        whisperer class that produced the sentence: exactly
        ``whisperer.CRITICAL_KINDS`` — the emergency latch and its clear, a
        refusal of the owner's own command, a mission terminal — may spend past
        this month's ``monthly_budget_usd``. It is the same set that already
        bypasses the whisperer's per-minute cap, deliberately, so that "which
        facts outrank the owner's cost knob" has ONE answer in this codebase
        rather than two lists that can drift apart. The lane enforces it; this
        method only carries the flag, because the lane is where the ledger is.
        """

        lane = self._narratable()
        if lane is None:
            # Card R16, work item 3. ``_narratable`` turns a HUNG-UP lane away
            # before the lane is ever asked, which is the right answer — the
            # whisperer must never be what re-opens a paid session the owner
            # walked away from — but a silent refusal would leave "the robot
            # spent the night narrating into a session that had ended" looking
            # exactly like "the robot had nothing to say". So the refusal is
            # COUNTED here, at the door where it actually happens, rather than
            # by handing the sentence to a lane this method has just decided
            # must not receive it.
            existing = self.realtime_lane
            if existing is not None and not existing.active:
                self._narrations_into_closed_lane += 1
            return False
        try:
            # Card R11: the lane's own answer is the answer. It says False when
            # its floor gate refused (the model has the mouth, a turn is owed),
            # and the whisperer needs to know that so it does not spend the
            # owner's per-minute budget on a sentence nobody heard.
            return bool(lane.narrate_event(text, critical=critical))
        except (RuntimeError, TypeError, ValueError) as error:
            # Narration is a nicety. It must never take down a mission
            # terminal, which is the fact this whole card exists to preserve.
            self._emit("realtime", f"mission narration skipped: {error}", "info")
            return False

    def _whisper(self, event: StateEvent) -> bool:
        """Offer ONE classified fact to the whisperer; narrate only if it says so.

        Card R11. This is the only way a robot-initiated fact reaches the hosted
        session from here on. Every offer is recorded in the whisperer's decision
        log — forward AND suppression, with the rule that fired — so "why did the
        dog say that" and "why did it stay quiet" both have exact answers.

        With no whisperer (no lane, or the realtime feature off) there is nothing
        to say anything to, and this is a no-op rather than a fallback to the
        ungated narration path: a fallback would mean the owner's cost knob had
        an off-by-configuration hole in it.
        """

        whisperer = self.realtime_whisperer
        if whisperer is None:
            return False
        decision = whisperer.offer(event)
        if not decision.forwarded:
            return False
        # Card R25. The class the whisperer already used to decide "may this
        # bypass the per-minute cap" is the same class that decides "may this
        # bypass the monthly ceiling". Read from CRITICAL_KINDS directly rather
        # than re-listing the kinds here: one list, one answer.
        if self._narrate_mission(decision.text, critical=event.kind in CRITICAL_KINDS):
            return True
        # The lane's floor gate refused it (no session, mid-reconnect, the model
        # already has the mouth). Nothing was said and nothing was billed, so the
        # owner's budget slot goes back; the attempt stays in the decision log.
        whisperer.undeliver(decision)
        return False

    def _narrate_mission_terminal(self, *, state: str, goal: str, reason: str) -> None:
        arrived = str(state) in MISSION_ARRIVED_STATES
        if arrived:
            # The arrival fact composes its own ask from R10's arrival table —
            # the SAME row the planner used to choose the terminal — so the
            # whisperer must not append a second speech-act hint on top of it.
            self._whisper(
                StateEvent(
                    kind=KIND_MISSION_ARRIVED,
                    key=f"mission_arrived:{goal}",
                    fact=self._arrival_fact_for(goal),
                    hint_carried=True,
                    detail={"goal": str(goal), "state": str(state)},
                )
            )
            return
        if str(reason) in EMERGENCY_STOP_TERMINAL_REASONS:
            # Card R12. Before the reason was propagated this branch could not
            # exist: every e-stop terminal arrived here as
            # ``navigation_disabled`` and was narrated as a mission that ended
            # "because of: navigation_disabled" — true of nothing the owner did.
            # The wording names the latch because the latch is the fact, and it
            # is deliberately not "the robot stopped": the trip ended.
            fact = (
                f"The robot's navigation system reports the trip to {goal} ended "
                "because the emergency stop was latched."
            )
        elif person_blocked_from_note(reason):
            fact = (
                f"The robot's navigation system reports it gave up on {goal} "
                "because a person stayed in the way."
            )
        else:
            fact = (
                f"The robot's navigation system reports the trip to {goal} ended "
                f"({state}) because of: {reason}."
            )
        self._whisper(
            StateEvent(
                kind=KIND_MISSION_ENDED,
                key=f"mission_ended:{goal}:{state}",
                fact=fact,
                detail={"goal": str(goal), "state": str(state), "reason": str(reason)},
            )
        )

    def _narrate_activity_terminal(
        self,
        *,
        activity: str,
        completed: bool,
        reason: str,
        started: bool = True,
    ) -> bool:
        """Card R15. The ONE place a completed physical action may be reported.

        THE ASYMMETRY THIS CLOSES. Navigation has always had both halves: the
        broker says "the robot is walking to the sidewalk", and tens of seconds
        later ``_narrate_mission_terminal`` says how the trip ended. Orbits and
        gestures had only the first half. So the model had a sentence saying the
        circle had been asked for, no sentence saying it was over, and an owner
        waiting — and on 2026-08-20 it filled the gap itself, one second in:
        "Done—I made a small circle around you, and it was okay."

        Both outcomes go through the whisperer's existing critical band, which
        is what makes them audible without spending the owner's per-minute
        budget on them. NO NEW EVENT CLASS: the whisperer's band table is not
        this card's to touch, and an activity terminal is exactly the "terminal"
        class that table already declares critical. A completed activity is a
        :data:`~parcel_robot.realtime.whisperer.KIND_MISSION_ENDED` carrying its
        own speech act (``hint_carried``) because the generic mission-ended hint
        — "tell the owner you stopped and why" — is the wrong sentence for a lap
        that went perfectly. One that stopped short is a refusal, which is what
        it is from the owner's side: they asked for a whole circle.

        Returns whether anything was said, so a caller can tell "narrated" from
        "the floor was taken" without reading the whisperer's log.
        """

        label = " ".join(str(activity).split()) or "activity"
        if not started:
            # Card R19. R15's two arms both say "it STOPPED before it finished",
            # which is a sentence about a body that moved. An expired proposal
            # is a body that never moved at all, and R15's own tense discipline
            # is the reason this is a third fact rather than a reused one: the
            # broker already told the model the pose had STARTED, so the only
            # correction that helps the owner is the one that says it did not.
            return self._whisper_refusal(
                f"The robot's own systems report that the {label} you asked for NEVER "
                f"RAN: {reason}. Nothing moved. Tell the owner it did not happen — and "
                "do not say it is done.",
                subject=label,
            )
        if completed:
            return self._whisper(
                StateEvent(
                    kind=KIND_MISSION_ENDED,
                    key=f"activity_finished:{label}",
                    fact=(
                        f"The robot's own systems report that the {label} it started "
                        "for you has now FINISHED. This is the moment it is true to "
                        "say it is done — tell the owner it is done."
                    ),
                    hint_carried=True,
                    detail={"activity": label, "state": "completed", "reason": str(reason)},
                )
            )
        return self._whisper_refusal(
            f"The robot's own systems report that the {label} it started for you "
            f"STOPPED before it finished: {reason}. It is not done.",
            subject=label,
        )

    def _whisperer_digest(self, observation: SimObservation | None, now: float) -> StateDigest:
        """One versioned snapshot of the robot for the whisperer. READS ONLY.

        Every value here is read from a subsystem's own snapshot; nothing in
        this method or anywhere downstream of it writes a controller parameter.
        In particular ``follow.config.max_vx`` is READ — it is the number the
        pace-mismatch item quotes so the model cannot claim a gait change that
        did not happen — and the follow safety caps are not a function of the
        pace the owner asked for. That is the whole of R11's relationship with
        the follow controller and it is pinned by test.
        """

        with self._lock:
            navigation = dict(self._navigation_detail)
            proximity = self._proximity_state
            block_class = self._mission_block_note or ""
            block_episode = self._mission_block_episode
            pace_intent = self._realtime_pace_intent
        battery = self._battery_snapshot()
        follow = self.follow
        following = bool(follow.enabled)
        if self._whisperer_was_following and not following and pace_intent:
            # A follow that ENDED takes its pace declaration with it. Otherwise
            # a later "follow me" spoken with no pace at all would inherit the
            # last "run" and the watcher would ask about a run nobody requested.
            #
            # Keyed on the falling EDGE, not on "not following": the tool call
            # records the intent and the controller starts a beat later on the
            # behaviour channel, and clearing it in that window would throw away
            # the declaration between the owner making it and the body acting.
            with self._lock:
                self._realtime_pace_intent = ""
                self._realtime_pace_intent_at_s = None
            pace_intent = ""
        self._whisperer_was_following = following
        follow_snapshot = follow.snapshot()
        distance = follow_snapshot.get("distance_m")
        owner_speed = follow_snapshot.get("owner_speed_mps")
        # Card R13. ``owner_speed_mps`` is ``None`` whenever the follow
        # controller's passive owner-heading estimator has not accumulated
        # enough fresh updates — E1 measured a continuous 10 s of that across a
        # run→walk transition, and a whole 58.8 s window in the recorded run.
        # The status is the controller's own last word on the owner track and is
        # carried READ-ONLY so the whisperer's ``pace_unknown`` row can name it.
        # Nothing here changes an estimator parameter or a follow cap; this
        # method reads, and R11 seed S21 attacks that from the other side.
        owner_speed_status = follow_snapshot.get("heading_track_status")
        if observation is None:
            position = (0, 0)
        else:
            robot = observation.robot
            position = (round(robot.x * 10.0), round(robot.y * 10.0))
        latched = bool(self.arbiter.emergency_stopped)
        return StateDigest(
            at_s=float(now),
            emergency_stopped=latched,
            # Card R21. Cleared to "" the moment the latch drops, so a released
            # e-stop cannot leave a stale door behind for the next latch to
            # inherit — the same falling-edge discipline `pace_intent` uses
            # above, and for the same reason.
            emergency_stop_source=(self._safety_latch_source if latched else ""),
            proximity_state=str(proximity),
            navigating=bool(navigation.get("enabled")),
            nav_state=str(navigation.get("state", "idle")),
            nav_goal=str(navigation.get("goal", "")),
            mission_blocked=bool(block_class),
            mission_block_class=str(block_class),
            mission_block_episode=int(block_episode),
            position_dm=position,
            battery_percent=round(float(battery.percent), 1),
            battery_state=str(battery.state),
            following=following,
            follow_pace_intent=str(pace_intent),
            follow_distance_dm=0 if distance is None else round(float(distance) * 10.0),
            owner_speed_mps=None if owner_speed is None else float(owner_speed),
            owner_speed_status="" if owner_speed_status is None else str(owner_speed_status),
            # The gait the BODY is in. R10 records the requested pace and R11
            # reads it, but NOTHING applies it: the follow controller runs at its
            # own cap, and saying so in the item is the honesty guard the bench
            # demanded after the model claimed "I'm matching your slower pace"
            # while the injected gait was still RUN.
            robot_pace="its own steady follow pace",
            robot_speed_cap_mps=float(follow.config.max_vx),
        )

    def _step_whisperer(
        self, observation: SimObservation | None, now: float | None = None
    ) -> None:
        """Offer the robot's own state to the whisperer, once a second.

        Throttled off the 10 Hz motion cadence on purpose: the whisperer's
        subject is a conversation, and a 10 Hz digest would fill its decision
        ring with ten identical never-band rows a second for no extra fidelity.
        One second is still far faster than any rule in it — the shortest is the
        8 s block debounce.

        ``now`` is injectable so a test can drive an eight-second debounce in
        eight function calls instead of eight seconds.
        """

        whisperer = self.realtime_whisperer
        if whisperer is None:
            return
        now = time.monotonic() if now is None else float(now)
        last = self._whisperer_tick_at_s
        if last is not None and (now - last) < WHISPERER_TICK_INTERVAL_S:
            return
        self._whisperer_tick_at_s = now
        # Card P2-B. The owner-presence tick rides the SAME 1 Hz beat as the
        # state digest, before it: the two watchers must not drift apart, and an
        # appearance is the more urgent of the two facts. It offers through
        # ``_whisper`` (its own budget accounting) and returns, so a failure in
        # it cannot cost the digest below — the try/except inside it is what
        # makes that true, and this call is deliberately not inside the digest's.
        self._step_owner_events(observation, now)
        # Card CURIO-1. THE CHATTER TICK, on the same 1 Hz beat and for P2-B's
        # reason: the three initiative layers must not drift apart, and a remark
        # about the world must be able to see the same owner sample the greeting
        # saw. Ordered AFTER the owner events on purpose — you walking in is
        # news and a lamppost is not, and the min-gap gives the first offer of a
        # tick the better claim on the minute. Like the call above it, this one
        # carries its own try/except and is deliberately outside the digest's.
        self._step_curiosity(observation, now)
        try:
            decisions = whisperer.observe(self._whisperer_digest(observation, now))
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as error:
            # A digest that cannot be built is a companion problem, never a
            # motion problem. It must not take the control loop with it.
            self._emit("realtime", f"whisperer tick skipped: {error}", "info")
            return
        for decision in decisions:
            if not decision.forwarded:
                continue
            # Card R25. Same rule as `_whisper`, read off the decision's own
            # class: the emergency latch reaches the model through THIS loop
            # (the digest path), not through `_whisper`, so the ceiling
            # exemption has to be here too or the one fact that most needs it
            # would be the one fact that lacked it.
            if not self._narrate_mission(
                decision.text, critical=decision.kind in CRITICAL_KINDS
            ):
                whisperer.undeliver(decision)

    # ==================== card CURIO-1: the chatter feed (ONE region) ========
    #
    # WHAT THIS REGION IS, AND WHAT IT DELIBERATELY IS NOT
    # ----------------------------------------------------
    # It is the FEED: it reads the learned map through its public API, decides
    # which single fact is worth a sentence right now, and hands it to the
    # whisperer's curiosity door. It is not a scheduler (that is
    # ``whisperer.ChatterScheduler``), it is not a band table, and it is not a
    # narrator — every sentence still leaves through ``_narrate_mission``, the
    # same door every other robot-initiated fact uses, with the same cap.
    #
    # THE ONE ABSOLUTE
    # ----------------
    # **A remark may only name a place the map has ADMITTED.** Admitted means:
    # in ``known_places()`` at the moment of speaking, AND not carried by a
    # ``vlm_proposed`` name. That is the card's "0 hallucinated places" row and
    # it is a hard row, so it is enforced in exactly one function
    # (``_curiosity_admitted_names``) that every candidate passes through, and
    # seeded RED there.
    #
    # NM-1 HANDOFF. When card NM-1 lands its detector-agreement judge, the
    # provenance test in ``_curiosity_admitted_names`` is the ONE line that
    # changes: ``promoted`` stops being sufficient and NM-1's admission flag
    # becomes the test. Nothing else in this region knows how a name is judged.
    #
    # LOCKS: this region takes no lock of its own (R24's roster is unchanged by
    # this card) and reads the map under the EXISTING ``_p1b_map_lock``, never
    # nested inside another lock, so ``PINNED_LOCK_ORDER`` is unchanged too.
    # Everything else here is touched only from the control loop's 1 Hz tick.

    #: How many un-remarked observations may queue up. A bound, because the map
    #: grows for the length of a walk and a queue that does not forget is a
    #: memory leak with a story. Oldest out first: the dog that has been walking
    #: for an hour should remark on what it just saw, not on the third lamppost.
    CURIOSITY_PENDING_MAX = 64
    #: How many "already said that" keys are remembered. Bounded for the same
    #: reason; overflowing it can only ever make the dog repeat itself, never
    #: make it hallucinate.
    CURIOSITY_SAID_MAX = 512

    def _curiosity_layer(self) -> tuple[Any, Any] | None:
        """The scheduler and the farewell watcher, built on first use.

        Lazily rather than in ``__init__`` for one honest reason: ``__init__``
        is edited by several cards at once and this needs two lines there and
        nothing else. Construction is deterministic, takes no lock and happens
        on the control loop's thread only — ``_step_curiosity`` is the sole
        caller and the control loop is the sole caller of that.

        ``PARCEL_CURIOSITY_SEED`` seeds the gap draw. It exists so a measured
        claim about a rate ("3 to 6 remarks in 120 seconds") can be re-run by
        somebody else and get the same answer; unset, the gaps are ordinary
        random draws.
        """

        existing = getattr(self, "_curio_scheduler", None)
        if existing is not None:
            return (existing, self._curio_farewell)
        config = self.realtime_config.whisperer.curiosity
        seed = os.environ.get("PARCEL_CURIOSITY_SEED", "").strip()
        rng = random.Random(int(seed)) if seed.lstrip("-").isdigit() else None
        scheduler = ChatterScheduler(config=config, clock=time.monotonic, rng=rng)
        farewell = FarewellWatcher(
            config=config,
            min_confidence=self.realtime_config.whisperer.owner_events.min_confidence,
            clock=time.monotonic,
        )
        # ORDER MATTERS. ``curiosity_snapshot`` is called from the PANEL thread
        # and uses ``_curio_scheduler is None`` as "the layer does not exist
        # yet", so the scheduler is bound LAST: a non-None scheduler now means
        # every field below it is already there, and a half-built layer can
        # never be read.
        self._curio_farewell = farewell
        #: entry ids the map held at the last scan, and the admitted vocabulary
        #: at the last scan. The FIRST scan is a baseline and produces no
        #: candidates — R11's rule for the first digest of a session, applied
        #: here for the same reason: a map reloaded from yesterday's store is
        #: not a discovery, and announcing all of it would be the dog telling
        #: you about your own living room.
        self._curio_seen_ids: dict[str, str] = {}
        self._curio_vocabulary: set[str] = set()
        self._curio_baselined = False
        #: Candidates waiting for a moment to be said, oldest first.
        self._curio_pending: dict[str, tuple[str, str]] = {}
        #: Keys already spoken this session.
        self._curio_said: set[str] = set()
        #: The counters the status doc and ``/api/state`` read.
        #: The counters the status doc and the panel read. COPY-ON-WRITE: it is
        #: written on the control loop and read from the panel thread, and
        #: ``dict(...)`` over a dict another thread is mutating raises. Rebinding
        #: is atomic, so a reader either sees the old dict or the new one and
        #: never a torn one — which buys thread-safety with no new lock and
        #: therefore no new edge in R24's ``PINNED_LOCK_ORDER``.
        self._curio_counts: dict[str, int] = {}
        self._curio_last_turn_marker = -1
        self._curio_scheduler = scheduler
        return (scheduler, farewell)

    def _curio_count(self, name: str, delta: int = 1) -> None:
        """Bump one counter, copy-on-write (see ``_curio_counts``)."""

        counts = getattr(self, "_curio_counts", None)
        if counts is None:
            return
        self._curio_counts = {**counts, name: counts.get(name, 0) + int(delta)}

    def _curiosity_admitted_names(self) -> frozenset[str]:
        """THE ADMISSION GATE. Names this robot is allowed to say out loud.

        Two tests, and both of them have to pass:

        1. the name is in ``known_places()`` — the map's own vocabulary, which
           already excludes decayed entries and inadmissible names;
        2. no ACTIVE entry carries that name with ``vlm_proposed`` provenance.

        Test 2 is belt and braces today and the whole point tomorrow.
        ``known_places()`` already filters on ``ProposedName.admissible``, so on
        today's ``entries.py`` an un-promoted guess cannot get through test 1
        either. It is written out anyway because this is the card's hard row:
        the day somebody makes a hypothesis admissible for some good reason of
        their own, the dog must go quiet about it rather than start naming it,
        and a gate that depends on a filter in another module for its safety is
        a gate that will be surprised.

        **Card NM-1 replaces test 2**, not test 1: a k-promoted name is
        *consistent*, which P1-D measured is not the same as *correct* (45 %
        naming accuracy; 2 of 2 false promotions at full resolution). Until
        NM-1's independent judge exists, ``promoted`` is the strongest signal
        this system has and the status doc says exactly that.
        """

        learned = getattr(self, "_p1b_learned_map", None)
        if learned is None:
            return frozenset()
        from parcel_robot.online_map.entries import NAME_VLM_PROPOSED

        with self._p1b_map_lock:
            vocabulary = set(learned.known_places())
            proposed: set[str] = set()
            for entry in learned.active_entries():
                for name in entry.names:
                    if str(name.provenance) == NAME_VLM_PROPOSED:
                        proposed.add(str(name.text))
        return frozenset(vocabulary - proposed)

    def _curiosity_scan(self, admitted: frozenset[str]) -> None:
        """Diff the map against the last scan; queue what is worth saying.

        Runs on EVERY tick, not only on the ticks a remark is due, so that
        "new since last time" means new since the robot last looked and not new
        since it last spoke. Everything queued here has already passed the
        admission gate; nothing downstream may add a name.
        """

        learned = getattr(self, "_p1b_learned_map", None)
        if learned is None:
            return
        with self._p1b_map_lock:
            active = {
                str(entry.entry_id): str(entry.label)
                for entry in learned.active_entries()
            }
        previous = self._curio_seen_ids
        vocabulary_before = self._curio_vocabulary
        self._curio_seen_ids = active
        self._curio_vocabulary = set(admitted)
        if not self._curio_baselined:
            self._curio_baselined = True
            self._curio_count("baseline_entries", len(active))
            return

        # 1. Things that are no longer there. Only sayable while the LABEL is
        #    still admitted — a decayed entry whose label left the vocabulary
        #    with it cannot be named at all under this card's absolute, so it is
        #    dropped and counted rather than spoken about approximately.
        for entry_id, label in previous.items():
            if entry_id in active:
                continue
            if label in admitted:
                self._curio_queue(KIND_SCENE_CHANGE, label)
            else:
                self._curio_count("dropped_unadmitted")

        # 2. Things that are there now and were not before.
        for entry_id, label in active.items():
            if entry_id in previous:
                continue
            if label in admitted:
                self._curio_queue(KIND_NOVEL_OBJECT, label)
            else:
                self._curio_count("dropped_unadmitted")

        # 3. The vocabulary itself grew: a NAME was admitted for something the
        #    robot already had a row for. This is the dog learning what a thing
        #    is CALLED, which is a different sentence from having seen it.
        for name in sorted(set(admitted) - set(vocabulary_before)):
            if name in {label for label in active.values()}:
                # It arrived with the entry; ``novel_object`` above already has
                # it and two sentences about one lamppost is one too many.
                continue
            self._curio_queue(KIND_PLACE_LEARNED, name)

    def _curio_queue(self, kind: str, place: str) -> None:
        key = f"{kind}:{place}"
        if key in self._curio_said or key in self._curio_pending:
            return
        self._curio_pending[key] = (kind, place)
        while len(self._curio_pending) > self.CURIOSITY_PENDING_MAX:
            self._curio_pending.pop(next(iter(self._curio_pending)))
            self._curio_count("pending_evicted")

    def _curiosity_ask_candidate(self, admitted: frozenset[str]) -> tuple[str, str] | None:
        """Card P1-D's ASK outcome, as a remark. The map's own public verdict.

        Not a re-implementation of the abstention gate and deliberately not a
        second copy of its thresholds: ``OnlineSemanticMap.resolve`` returns the
        verdict ``perception_abstention.assess_place_query`` produced, and an
        ASK there is an ASK here. Called only on a tick where the scheduler has
        already said a remark is due, so the cost is one resolve per remark and
        not one per tick.
        """

        learned = getattr(self, "_p1b_learned_map", None)
        if learned is None or not admitted:
            return None
        from parcel_robot.perception_abstention import OUTCOME_ASK

        for label in sorted(admitted):
            key = f"{KIND_ASK_ABOUT}:{label}"
            if key in self._curio_said:
                continue
            try:
                with self._p1b_map_lock:
                    result = learned.resolve(label)
            except Exception:  # noqa: BLE001 - a query is never worth the loop
                self._curio_count("ask_query_failed")
                return None
            if str(getattr(result.verdict, "outcome", "")) != OUTCOME_ASK:
                continue
            # THE VERDICT'S OWN SUBJECT. ``AbstentionVerdict.candidate`` is the
            # field card P1-D named for it ("the place an ASK is asking ABOUT —
            # the best candidate's label"); the first pass read a field called
            # ``ask_place`` that does not exist on that dataclass, so ``place``
            # always fell back to the queried label, the verdict's real
            # candidate was never spoken, and the re-check below was
            # unreachable. It is reachable now and it has to be: the candidate
            # is the map's best guess, and the map's best guess is exactly the
            # thing that can be a name this card may not say.
            place = str(getattr(result.verdict, "candidate", "") or "").strip() or label
            if place not in admitted:
                self._curio_count("dropped_unadmitted")
                continue
            return (KIND_ASK_ABOUT, place)
        return None

    def _curiosity_candidate(self, admitted: frozenset[str]) -> tuple[str, str] | None:
        """The ONE thing to say now, or nothing. Oldest queued first.

        Re-checks admission at the point of speaking rather than trusting what
        was queued: a name that has decayed out of ``known_places()`` in the
        four minutes since it was noticed is a name this robot may no longer
        say, and "it was true when we queued it" is exactly the reasoning the
        card's hard row exists to refuse.
        """

        for key, (kind, place) in list(self._curio_pending.items()):
            self._curio_pending.pop(key, None)
            if key in self._curio_said:
                continue
            if place not in admitted:
                self._curio_count("dropped_unadmitted")
                continue
            return (kind, place)
        return self._curiosity_ask_candidate(admitted)

    def _curiosity_idle_candidate(
        self, admitted: frozenset[str]
    ) -> tuple[str, str] | None:
        """Something to say when NOTHING has happened. The slow cadence's subject.

        Correction pass, ruling 6. An idle remark still names an ADMITTED place
        — it is the dog thinking out loud about something it already knows, not
        a sentence about nothing — so the card's hard row is unchanged and this
        function adds no new way for a name to reach the model. What it adds is
        a subject for the four-to-eight-minute clock, which otherwise had a
        cadence and nothing to say on it.

        Round-robins rather than repeating: an idle remark is marked said like
        any other, so a quiet afternoon walks the vocabulary instead of
        returning to the first lamppost every six minutes.
        """

        for name in sorted(admitted):
            if f"{KIND_IDLE_REMARK}:{name}" in self._curio_said:
                continue
            return (KIND_IDLE_REMARK, name)
        return None

    def _curiosity_activity_busy(self) -> bool:
        """Is this a bad moment for a social action?

        ``prompts/functions/patrol.yaml`` (not edited): *social actions can wait
        until an idle checkpoint*. Two producers of "not a checkpoint", and
        neither is re-derived here:

        * the activity coordinator is running something — a skill, a pose, a
          gesture — which is the general case;
        * card ROAM-1's ``roam_idle_checkpoint()``, which it published for this
          card and does not itself call. A roam that is TURNING is negotiating a
          blocked lane and is the worst moment to interrupt; a roam that is
          cruising, or not roaming at all, reports ``True``.

        Written as a read of ROAM-1's predicate rather than a copy of its rule,
        and defensively so this card still works on a tree where that card has
        not landed.
        """

        if self.activities.running() is not None:
            return True
        checkpoint = getattr(self, "roam_idle_checkpoint", None)
        if checkpoint is None:
            return False
        try:
            return not bool(checkpoint())
        except Exception:  # noqa: BLE001 - a predicate is never worth the loop
            return False

    def _curiosity_lane_busy(self) -> bool:
        """Can the lane take a narration at all right now.

        The lane's OWN answer, not a copy of its rule: ``idle_seconds`` is
        ``None`` for exactly the four states in which ``narrate_event`` refuses
        — no session, a hosted response playing, a response outstanding, or the
        owner owed an answer. Reading it here means a remark the floor gate
        would drop is never drawn from the owner's budget in the first place,
        and it means this card cannot drift from ``lane.py`` (which it does not
        touch) if that rule ever changes.
        """

        lane = self.realtime_lane
        if lane is None:
            return True
        try:
            snapshot = lane.snapshot()
        except Exception:  # noqa: BLE001 - a snapshot is never worth the loop
            return True
        if snapshot.get("idle_seconds") is None:
            return True
        return bool(snapshot.get("voice_turn_owed"))

    def _curiosity_note_owner_turn(self, at: float) -> None:
        """Start the quiet window over when the OWNER has been in the exchange.

        Polled off the lane's own counters rather than wired into P2-B's
        ``note_realtime_turn``, which counts BOTH sides and is another card's
        region. The distinction is load-bearing here and is not there: this
        clock exists so the dog does not talk over a conversation, and the
        robot's own unprompted remarks are not a conversation. ``text_turns``
        and ``voice_turns_owed`` both count owner turns and neither counts a
        narration, so their sum moving is an owner exchange and nothing else.
        """

        lane = self.realtime_lane
        if lane is None:
            return
        try:
            snapshot = lane.snapshot()
            marker = int(snapshot.get("text_turns", 0) or 0) + int(
                snapshot.get("voice_turns_owed", 0) or 0
            )
        except Exception:  # noqa: BLE001
            return
        previous = self._curio_last_turn_marker
        self._curio_last_turn_marker = marker
        if previous >= 0 and marker > previous:
            self._curio_scheduler.note_turn(at)

    def _curiosity_free_gesture(self) -> bool:
        """The NON-BILLED variant, when the owner's cap has already been spent.

        Card work item 3. The remark the budget refused becomes a gesture: a
        look, not a sentence. Nothing goes on the wire and nothing is billed, so
        this is deliberately NOT gated on the whisperer's cap — the cap is a
        money and politeness knob for hosted responses, and this costs neither.
        It IS gated on the activity coordinator, through ``_brain_gesture``'s
        own proposal path, so a gesture can no more preempt navigation than any
        other emote can.

        **THE GESTURE IS THE REMARK.** Returning ``True`` means the fact was
        EXPRESSED: it is marked said, and the cadence clock is re-armed exactly
        as a spoken sentence would re-arm it. One noticing produces one
        expression, billed or free. The other live option was "gesture now,
        sentence when the cap frees up", and it was rejected because it hands
        the owner two of everything for one lamppost — the gesture would become
        a trailer for a sentence rather than a substitute for it. The choice is
        recorded in ``ChatterScheduler.note_remark``'s docstring as well, since
        that is the method whose contract it settles.

        **WHICH DOOR.** ``_brain_gesture`` — the emote catalog plus the activity
        coordinator's proposal path. NOT ``realtime.proactive_motion_tools``,
        which is P0-B's allowlist for motion the hosted MODEL proposes on a
        system-initiated response. This is not a model proposal: no model is
        consulted, nothing is billed, and the card's own wording ("a yip/whine
        sound effect **or** a ``play_gesture``") left the door open. The
        catalog check makes an unknown name a counted skip rather than a raise.
        """

        name = str(self.realtime_config.whisperer.curiosity.gesture_when_capped)
        if not name or name not in self._emote_catalog:
            self._curio_count("gesture_unavailable")
            return False
        try:
            self._brain_gesture(name)
        except Exception as error:  # noqa: BLE001 - a shrug may not stop the loop
            self._curio_count("gesture_refused")
            self._emit("realtime", f"curiosity gesture skipped: {error}", "info")
            return False
        self._curio_count("gestures")
        return True

    def _whisper_curiosity(self, event: StateEvent) -> bool:
        """Offer ONE curiosity fact through the middle band's fourth mechanism.

        The sibling of ``_whisper``, and different from it in exactly one place:
        the door. ``offer_curiosity`` is the mechanism entry the middle band
        requires, so a curiosity class that reached ``offer`` instead would be
        refused with ``middle_band_requires_a_mechanism`` — which is the guard
        that keeps a 2 Hz map from becoming a 2 Hz robot, and it is seeded RED.

        ``critical=False`` is not a parameter here and never will be: no
        curiosity class is in ``CRITICAL_KINDS``, so a remark can neither spend
        past the owner's per-minute cap nor past the month's ceiling.
        """

        whisperer = self.realtime_whisperer
        if whisperer is None:
            return False
        decision = whisperer.offer_curiosity(event)
        if not decision.forwarded:
            self._curio_count(f"suppressed_{decision.rule}")
            if decision.rule == RULE_BUDGET:
                # The cap is spent. The free variant still lets the dog show it
                # noticed something, which is the difference between a budget
                # and a mute button.
                return self._curiosity_free_gesture()
            return False
        if self._narrate_mission(decision.text, critical=False):
            self._curio_count("narrated")
            return True
        whisperer.undeliver(decision)
        self._curio_count("floor_refused")
        return False

    def _step_curiosity(
        self, observation: SimObservation | None, now: float
    ) -> tuple[StateEvent, ...]:
        """One chatter tick. At most one remark, at most one farewell.

        Never raises. A dog that cannot think of anything to say must not be
        able to stop the control loop, and neither must a map that is mid-write
        or a lane that is mid-reconnect.

        Returns what it offered, for the tests and the harness; the whisperer's
        decision log holds what actually happened to each one.
        """

        if not self.realtime_config.whisperer.curiosity.enabled:
            return ()
        try:
            layer = self._curiosity_layer()
            if layer is None:
                return ()
            scheduler, farewell = layer
            offered: list[StateEvent] = []

            # 1. The farewell — the falling edge P2-B's watcher does not carry.
            #    An ALWAYS-band class, so it goes through the ordinary door.
            sample = self.owner_presence_sample(observation, now)
            for event in farewell.observe(sample):
                offered.append(event)
                self._whisper(event)

            # 2. The world. Scan every tick; speak only when the scheduler says.
            admitted = self._curiosity_admitted_names()
            self._curiosity_scan(admitted)
            self._curiosity_note_owner_turn(now)
            state = ChatterState(
                at_s=now,
                owner_present=sample.credible(
                    self.realtime_config.whisperer.owner_events.min_confidence
                ),
                lane_busy=self._curiosity_lane_busy(),
                activity_running=self._curiosity_activity_busy(),
            )
            # THE TWO CADENCES (correction pass, ruling 6). Which candidate
            # exists decides which clock is asked, not the other way round: if
            # something happened, the fast stimulus floor governs; if nothing
            # did, the slow Poisson mean governs. One ``due`` call per tick
            # either way, so the scheduler's ``ticks == admitted + skips``
            # invariant is untouched.
            candidate = self._curiosity_candidate(admitted)
            stimulus = candidate is not None
            if not scheduler.due(state, stimulus=stimulus):
                if stimulus:
                    # Put it back. It was never offered, so it is not spent —
                    # and this is the ordinary case, not an error: the stimulus
                    # floor is doing its job.
                    self._curio_queue(*candidate)
                return tuple(offered)
            if candidate is None:
                candidate = self._curiosity_idle_candidate(admitted)
            if candidate is None:
                # The moment was right and there was nothing at all to say —
                # the map has not admitted a single name yet.
                self._curio_count("nothing_to_say")
                return tuple(offered)
            kind, place = candidate
            event = curiosity_event(kind, place, time_band=scheduler.band())
            offered.append(event)
            if self._whisper_curiosity(event):
                self._curio_said.add(f"{kind}:{place}")
                while len(self._curio_said) > self.CURIOSITY_SAID_MAX:
                    self._curio_said.pop()
                scheduler.note_remark(now)
            else:
                # Nothing was heard, so nothing was said: the candidate goes
                # back on the queue and the Poisson draw is NOT re-armed. A
                # refusal must not cost the dog a four-minute silence it never
                # spent. ``note_refusal`` moves the ANCHOR only, which stops the
                # feed re-offering the same candidate on every 1 Hz tick and
                # filling the decision log with a suppression row a second.
                if kind != KIND_IDLE_REMARK:
                    self._curio_queue(kind, place)
                scheduler.note_refusal(now)
            return tuple(offered)
        except Exception as error:  # noqa: BLE001 - a remark may never stop the loop
            self._curio_count("tick_failed")
            self._emit("realtime", f"curiosity tick skipped: {error}", "info")
            return ()

    def curiosity_snapshot(self) -> dict[str, object] | None:
        """What the robot has been curious about, or ``None`` when it is off.

        ``None`` rather than a disabled block, which is this repo's R1
        discipline: with the feature off the key is ABSENT, so a snapshot is
        byte-identical to a build that never had this card.

        **Not yet on the wire.** ``realtime_snapshot`` is P2-B's/R3's region and
        this card's OWNS is one feed region, so nothing publishes this yet. It
        is the accessor a panel key would read, it is what the roam harness
        reads, and adding ``"curiosity": self.curiosity_snapshot()`` beside
        ``"owner_events"`` is the whole of the follow-up.
        """

        scheduler = getattr(self, "_curio_scheduler", None)
        if scheduler is None:
            return None
        # Called from the PANEL thread while the control loop is writing. Each
        # read below is a single atomic operation on the CPython object — a
        # reference read for the copy-on-write counters, ``len()`` for the
        # containers — so nothing here can catch a container mid-mutation and
        # nothing here needs a lock. The two collaborators take their own.
        return {
            "scheduler": scheduler.snapshot(),
            "farewell": self._curio_farewell.snapshot(),
            "counts": dict(self._curio_counts),
            "pending": len(self._curio_pending),
            "said": len(self._curio_said),
            "admitted_names": len(self._curio_vocabulary),
        }

    # ================== END card CURIO-1 (the chatter feed) ==================

    def _whisper_refusal(self, fact: str, *, subject: str = "") -> bool:
        """A refusal of the OWNER's own request, forwarded as a critical fact.

        Critical band: it bypasses the owner's per-minute budget, because a
        refusal the owner never hears looks exactly like a robot that ignored
        them. Kept as its own door rather than folded into the mission terminals
        so that a refusal which is not a mission (a pose, an orbit) has a home.

        R11 BUILT THIS WITH NO CALLER, on purpose, and named the caller it was
        waiting for: "the refusals that have no tool call in flight — a
        mid-behaviour safety abort is the obvious next one". Card R15 is that
        caller. :meth:`_narrate_activity_terminal` routes every activity that
        STOPPED short of finishing through here — the mid-orbit annulus abort
        R10 built the detection for, a gesture preempted by navigation, a pose
        the dispatch cancelled. The tool call that started them answered
        seconds ago and said only "started"; without this the owner would be
        left with a promise and silence.

        Refusals that DO have a tool call in flight still do not come through
        here: a ``rejected`` broker result is the case ``lane._beat_reason``
        refuses to go quiet on, so the model already says it in the same turn,
        and saying it twice was never the fix.
        """

        return self._whisper(
            StateEvent(
                kind=KIND_REFUSAL,
                key=f"refusal:{subject}" if subject else "",
                fact=" ".join(str(fact).split()),
                detail={"subject": str(subject)},
            )
        )

    def _arrival_fact_for(self, goal: str) -> str:
        """The arrival item, carrying the table's ask-hint INLINE — card R10 item 4.

        The bench is unambiguous that "reach the door → turn back → ask what's
        next" does not emerge from the model: 0/12 on the chat probe, 0/6 on the
        injected-arrival probe, both tiers. So the ask has to travel WITH the
        fact. R11 owns the structured hint mechanism; the card's instruction if
        R11 has not landed is to put the hint text inline, which is what this
        does — the channel (R8's wire fix) exists either way, and this is the
        one seam every non-arrival and arrival terminal already passes through.

        The policy is read from the arrival table by the goal's own class, so
        the sentence the model hears is generated from the SAME row the planner
        used to choose the terminal — not a second opinion about the same door.
        """

        label = " ".join(str(goal).split())
        region_labels, object_labels = self._realtime_scene_vocabulary()
        place_class = classify_place(
            label, region_labels=region_labels, object_labels=object_labels
        )
        policy = arrival_policy(place_class)
        try:
            owner_name = str(self.store.agent_config().get("owner_name", "") or "")
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            owner_name = ""
        if owner_name == UNKNOWN_OWNER:
            owner_name = ""
        body = arrival_fact(place=label, policy=policy, owner_name=owner_name)
        return f"The robot's navigation system reports: {body}"

    def _note_mission_block(self, *, goal: str, note: str, blocked: bool) -> None:
        """One row per blocked EPISODE, and one when the way clears again.

        Called from the 10 Hz navigation step, so the edge is everything: the
        row is written when the block CLASS changes, never while it holds. A
        mission blocked behind a person for a minute is two rows — "blocked"
        and "clear" — not six hundred.

        Two guards, both learned the hard way from the 2026-08-18 live proof:
        the class key (not the raw note, which carries per-tick telemetry), and
        a minimum interval, because a real pedestrian stream flips the class
        for real. Suppressed transitions are counted, never silently dropped.

        CARD R11 — WHAT MOVED OUT OF HERE. Until this card, a person-block edge
        called ``_narrate_mission_block`` and went straight to the model. It no
        longer does: a block is a MIDDLE-band fact and has to survive an 8 s
        debounce first (bench B2), and its clear is only spoken if the block
        itself was. Both machines live in the whisperer and are driven by the
        digest, which is why all this method now does is advance the episode
        counter that pairs a block with its closure. The MISSION LOG is
        untouched — this is about what the robot SAYS, never about what it
        records.
        """

        previous = self._mission_block_note
        person = person_blocked_from_note(note)
        current = (MISSION_BLOCK_PERSON if person else MISSION_BLOCK_OBSTACLE) if blocked else None
        if current == previous:
            return
        if current is not None and previous is None:
            # A new blocked EPISODE begins. Numbered so the whisperer's
            # clear-only-after-a-forwarded-block rule has an identity to key on;
            # a class change inside one episode (person -> obstacle) is the same
            # wait and keeps the same number.
            self._mission_block_episode += 1
        self._mission_block_note = current
        now = self._mission_clock()
        last = self._mission_block_emit_at_s
        if last is not None and (now - last) < MISSION_BLOCK_MIN_INTERVAL_S:
            self._mission_block_coalesced += 1
            return
        folded = self._mission_block_coalesced
        self._mission_block_coalesced = 0
        self._mission_block_emit_at_s = now
        suffix = f" (+{folded} more changes in the last few seconds)" if folded else ""
        if current is None:
            self._log_mission(
                MISSION_LOG_BLOCKED,
                goal=goal,
                state="navigating",
                reason="clear",
                level="success",
                text=f"The way to {goal} is clear again; carrying on.{suffix}",
            )
            return
        self._log_mission(
            MISSION_LOG_BLOCKED,
            goal=goal,
            state="blocked",
            # The row keeps the FULL note from the tick the episode began on —
            # that is the diagnostic value — while the edge is keyed on the
            # class above, which is the only part that means anything stable.
            reason=str(note),
            level="warning",
            text=(
                f"Waiting: someone is in the way near {goal}.{suffix}"
                if person
                else f"Waiting: something is blocking the way to {goal}.{suffix}"
            ),
        )

    def mission_log(self) -> list[dict[str, object]]:
        """The lifecycle ring, oldest first. What ``/api/state`` publishes."""

        with self._lock:
            return [dict(row) for row in self._mission_log]

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

    def _remember_turn_transcript(self, turn_id: int, transcript: str, origin: str) -> None:
        """Hold one turn's final transcript until its outcome is written."""

        with self._transcript_lock:
            self._turn_transcripts[int(turn_id)] = (transcript, origin)
            while len(self._turn_transcripts) > _TRANSCRIPT_MEMORY_TURNS:
                self._turn_transcripts.popitem(last=False)

    def _take_turn_transcript(self, turn_id: int) -> tuple[str, str] | None:
        with self._transcript_lock:
            return self._turn_transcripts.pop(int(turn_id), None)

    def _duplex_record_turn_outcome(self, turn_id: int, *, barge_in: bool = False) -> None:
        if not self.duplex.enabled:
            return
        meta = self._duplex_turn_meta.pop(int(turn_id), {})
        # Always release the held transcript, even when logging is off, so the
        # kill switch cannot turn a bounded buffer into a slow leak.
        remembered = self._take_turn_transcript(turn_id)
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
        # FIX-A/F3, additive and governed by the SAME switch as the rest of the
        # session log: with ``duplex.logging: false`` the fields are not
        # produced at all, so they cannot reach the JSONL or the snapshot.
        if self.duplex.log.enabled:
            transcript, origin = remembered or (
                # Fallback source: the query_end stage, which carries the same
                # committed text. Reached when a turn's text never passed
                # through submit_voice_text (test harnesses, future producers),
                # and in the vanishingly small window where a turn completes on
                # the voice worker before the submitting thread has recorded
                # its origin. The lock is deliberately NOT held across
                # ``voice_session.submit_text`` to close that window: the
                # worker takes session locks and then this one, so holding this
                # one across a call that waits on a session lock would invert
                # the order and deadlock. The TRANSCRIPT is preserved either
                # way; only the origin label degrades, and it degrades to an
                # honest "unknown" rather than to a guess.
                str(meta.get("transcript", "")),
                str(meta.get("transcript_origin", "unknown")),
            )
            outcome["transcript"] = transcript
            outcome["transcript_origin"] = origin
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
                # Fallback copy of what was heard/typed: the stage carries the
                # committed text even for turns injected without going through
                # submit_voice_text.
                "transcript": stage.transcript,
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

    def _report_speech_stack(self, speech_config: dict) -> dict[str, object]:
        """FIX-A/F2: say out loud what the speech stack actually resolved to.

        The 2026-08-11 storm ran under ``configs/robot.yaml`` because the panel
        was launched without ``--config``: energy endpointing, no AEC, none of
        the semantic models B2 tuned. Every one of those facts was knowable at
        startup and none of them was reported. This emits them once and parks
        them in ``/api/state`` so "which stack am I actually running" is never
        again a question you answer by reading YAML after the fact.
        """

        requested_endpointing = str(speech_config.get("endpointing", "energy")).strip().lower()
        vad_model = speech_config.get("vad_model")
        turn_model = speech_config.get("turn_model")
        semantic_loaded = requested_endpointing == "semantic" and self._endpointing_detail.startswith(
            "semantic"
        )
        # "Present on disk" is checked at the paths the config names when it
        # names them, and at the conventional directory otherwise, so a config
        # that simply omits the keys still trips the warning below.
        model_dir = Path("models/endpointing")
        candidates = {
            "vad_model": Path(str(vad_model)) if vad_model else model_dir / "silero_vad_v6.onnx",
            "turn_model": Path(str(turn_model))
            if turn_model
            else model_dir / "smart_turn_v3.onnx",
        }
        present = {name: path.is_file() for name, path in candidates.items()}
        detail: dict[str, object] = {
            "config_path": str(self.store.path),
            "mode": self.speech_stack.mode,
            "stt": self.speech_stack.stt_detail,
            "tts": self.speech_stack.tts_detail,
            "endpointing": {
                "requested": requested_endpointing,
                "resolved": self._endpointing_detail,
                "semantic_loaded": semantic_loaded,
                "models": {name: str(path) for name, path in candidates.items()},
                "models_present": present,
            },
            "aec": {
                "constructed": False,
                # Stated rather than inferred: the runtime never passes an
                # AecStage to MicrophoneVoiceLoop, so the capture path is the
                # raw frame path on every config that exists today.
                "detail": "no AEC stage is wired into the capture loop on any config path",
            },
            "capture_device": self._mic_arming.identity.as_dict(),
            "mic_arming": self._mic_arming.as_dict(),
        }
        self._emit(
            "voice",
            (
                f"Speech stack: config={self.store.path}; mode={self.speech_stack.mode}; "
                f"endpointing={self._endpointing_detail}; aec=absent; "
                f"capture={self._mic_arming.identity.name} "
                f"(monitor={self._mic_arming.identity.is_monitor})"
            ),
            "info",
        )
        self._emit(
            "voice",
            self._mic_arming.reason,
            "info" if self._mic_arming.code == CODE_ARMED else "warning",
        )
        if self._mic_arming.override or not self._mic_arming.armed:
            # Both are operator-facing: a refusal explains a dead microphone,
            # an override explains a microphone that is deliberately unsafe.
            logger.warning("%s", self._mic_arming.reason)
        # One WARNING when the tuned semantic stack exists on disk but is not
        # the stack that loaded, and audio capture is demanded or live.
        audio_path_live = self.speech_stack.mode == "audio" or self._mic_arming.armed
        if audio_path_live and any(present.values()) and not semantic_loaded:
            message = (
                "Semantic endpointing models are present on disk "
                f"({', '.join(str(candidates[name]) for name, ok in present.items() if ok)}) "
                f"but the loaded endpointing stack is '{self._endpointing_detail}' "
                f"(speech.endpointing={requested_endpointing}, config={self.store.path}). "
                "The tuned turn-taking stack is NOT running."
            )
            logger.warning("%s", message)
            self._emit("voice", message, "warning")
        return detail

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
