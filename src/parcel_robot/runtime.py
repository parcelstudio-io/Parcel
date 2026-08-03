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
from parcel_robot.config import ConfigStore
from parcel_robot.core import (
    ActivityContext,
    ActivityCoordinator,
    CommandArbiter,
    MotionIntent,
    VelocitySmoother,
)
from parcel_robot.memory import ConversationMemory
from parcel_robot.models import ActionProposal, Pose, VelocityCommand
from parcel_robot.motion import build_motion_router
from parcel_robot.navigation.follow import FollowOwnerController
from parcel_robot.prompting import PromptLibrary
from parcel_robot.providers import LanguageModel
from parcel_robot.skills.api import Dog
from parcel_robot.voice_pipeline import DuplexVoiceSession, VoiceTurn


class RobotRuntime:
    """Own command arbitration, behavior loops, telemetry, and agent execution."""

    def __init__(
        self,
        config_path: str | Path,
        backend: SimulatorBackend,
        *,
        language_model: LanguageModel | None = None,
        audio_status: AudioDeviceStatus | None = None,
        loop_hz: float = 10.0,
    ):
        if loop_hz <= 0:
            raise ValueError("loop_hz must be positive")
        self.store = ConfigStore(config_path)
        self.backend = backend
        self.loop_period = 1.0 / loop_hz
        self.arbiter = CommandArbiter(self.store.safety_limits())
        smoother_config = self.store.motion_config().get("smoothing") or {}
        if not isinstance(smoother_config, dict):
            raise TypeError("motion.smoothing must be a mapping")
        self.velocity_smoother = VelocitySmoother(
            linear_accel=float(smoother_config.get("linear_accel", 0.9)),
            linear_decel=float(smoother_config.get("linear_decel", 1.4)),
            yaw_accel=float(smoother_config.get("yaw_accel", 1.8)),
        )
        self.follow = FollowOwnerController()
        self.audio_status = audio_status or detect_audio_devices()
        safety_config = self.store.section("safety")
        self.obstacle_stop_m = float(safety_config.get("obstacle_stop_m", 0.65))
        self.obstacle_slow_m = float(safety_config.get("obstacle_slow_m", 1.2))
        self.telemetry_stale_s = float(safety_config.get("telemetry_stale_s", 0.6))
        if not 0 < self.obstacle_stop_m < self.obstacle_slow_m:
            raise ValueError("safety obstacle distances must satisfy 0 < stop < slow")
        if not math.isfinite(self.telemetry_stale_s) or self.telemetry_stale_s <= 0:
            raise ValueError("safety telemetry_stale_s must be positive and finite")
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
        self._model_status = "configured" if language_model is not None else "deterministic"
        self._model_detail = type(language_model).__name__ if language_model else "LLM optional"
        model_base = getattr(language_model, "base_url", "") if language_model is not None else ""
        self._model_health_url = f"{str(model_base).rstrip('/')}/health" if model_base else ""
        self._next_model_probe = 0.0
        self._events: deque[dict[str, object]] = deque(maxlen=100)
        self._chat: deque[dict[str, object]] = deque(maxlen=80)
        self._event_id = 0
        self._lock = threading.RLock()
        self._agent_lock = threading.Lock()
        self._navigation_lock = threading.RLock()
        self._command_lock = threading.RLock()
        self._behavior_generation = 0
        self._closed = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sent = VelocityCommand()
        self._last_send_at = 0.0
        self._was_moving = False
        self._proximity_state = "clear"
        agent_config = self.store.agent_config()
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
            on_command=lambda command: self.submit_motion("voice", command, ttl=1.0),
            on_stop=self.stop_motion,
        )
        self.dog = Dog.from_config(
            config_path,
            motion=motion,
            on_pose=self._run_pose,
            on_trajectory=self._run_trajectory,
        )
        memory_cfg = self.store.section("memory")
        self.agent = VoiceAgent(
            self.dog.poses() or self.store.poses(),
            self.store.load_modules(),
            self._run_pose,
            language_model=language_model,
            stop_publisher=self.emergency_stop,
            memory=ConversationMemory(memory_cfg.get("path", ":memory:")),
            motion=motion,
            safety_limits=self.store.safety_limits(),
            behavior_publisher=self.set_behavior,
            navigation_publisher=self.start_navigation,
            action_proposal_publisher=self.propose_action,
            system_prompt_provider=self._render_system_prompt,
            affect_minimum_confidence=self._affect_minimum_confidence,
            affect_actions=personality.affect_actions,
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
        )
        self._emit("runtime", "Runtime initialized", "success")

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("runtime is closed")
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._control_loop,
            name="parcel-control-loop",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()
        with self._command_lock:
            self.follow.stop()
            self.stop_navigation()
            self.agent.safety.engage_emergency_stop()
            self.activities.clear("runtime_closed")
            self._activity_complete_at = 0.0
            self.arbiter.engage_emergency_stop()
            try:
                emergency = getattr(self.backend, "emergency_stop", None)
                if callable(emergency):
                    emergency()
                else:
                    self.backend.stop()
            except OSError:
                pass
            self._last_sent = VelocityCommand()
            self._was_moving = False
            self.velocity_smoother.reset()
        self.voice_session.close(timeout=2.0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

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
            self.stop_motion()
            return "Manual motion stopped"
        # Serialize ownership acquisition with activity dispatch. If an action
        # already crossed the dispatch boundary this waits for it, then manual
        # control becomes authoritative before returning to the operator.
        with self._command_lock:
            return self.submit_motion(
                "manual",
                VelocityCommand(vx=values[0], vy=values[1], vyaw=values[2]),
                ttl=0.45,
            )

    def stop_motion(self) -> None:
        with self._command_lock:
            self.arbiter.stop()
            try:
                self.backend.stop()
            except OSError as error:
                self._record_sim_error(error)
            self._last_sent = VelocityCommand()
            self._was_moving = False
            self.velocity_smoother.reset()

    def emergency_stop(self) -> None:
        with self._command_lock:
            self.follow.stop()
            self.stop_navigation()
            self.activities.clear("emergency_stop")
            self._activity_complete_at = 0.0
            self.arbiter.engage_emergency_stop()
            try:
                emergency = getattr(self.backend, "emergency_stop", None)
                if callable(emergency):
                    emergency()
                else:
                    self.backend.stop()
            except OSError as error:
                self._record_sim_error(error)
            self._last_sent = VelocityCommand()
            self._was_moving = False
            self.velocity_smoother.reset()
        self._emit("safety", "Emergency stop latched", "error")

    def clear_emergency_stop(self) -> str:
        if self._closed:
            raise RuntimeError("runtime is closed")
        with self._command_lock:
            clear_backend = getattr(self.backend, "clear_emergency_stop", None)
            if callable(clear_backend):
                try:
                    clear_backend()
                except OSError as error:
                    self._record_sim_error(error)
                    raise RuntimeError("simulator emergency stop could not be cleared") from error
            self.arbiter.clear_emergency_stop()
            self.agent.safety.clear_emergency_stop()
        self._emit("safety", "Emergency stop cleared by operator", "warning")
        return "Emergency stop cleared"

    def set_behavior(self, mode: str) -> str:
        if self._closed:
            raise RuntimeError("runtime is closed")
        if mode == "follow":
            with self._command_lock:
                if self._closed:
                    raise RuntimeError("runtime is closed")
                if self.arbiter.emergency_stopped:
                    raise RuntimeError("motion is disabled by emergency stop")
                self.stop_navigation()
                self.follow.start()
                with self._lock:
                    self._behavior_generation += 1
                    self._follow_detail = self.follow.snapshot()
            self._emit("behavior", "Owner-follow enabled", "success")
            return "Owner-follow enabled"
        if mode == "stay":
            with self._command_lock:
                self.follow.stop()
                with self._lock:
                    self._behavior_generation += 1
                self.stop_navigation()
                self.activities.clear("owner_requested_stay")
                self._activity_complete_at = 0.0
                self.stop_motion()
                with self._lock:
                    self._follow_detail = self.follow.snapshot()
            self._emit("behavior", "Holding position", "info")
            return "Holding position"
        raise ValueError(f"unknown behavior: {mode}")

    def start_navigation(self, directive: str) -> str:
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
        self.follow.stop()
        with self._lock:
            self._behavior_generation += 1
            generation = self._behavior_generation
            observation = self._observation
            self._follow_detail = self.follow.snapshot()
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
                extras=(
                    {"obstacle_bearing_rad": observation.nearest_obstacle_bearing_rad}
                    if observation is not None
                    else None
                ),
            )
        place = mission.goal.label or mission.goal.poi_id
        with self._lock:
            if generation != self._behavior_generation or self.arbiter.emergency_stopped:
                raise RuntimeError("navigation request was canceled")
            self._navigation_directive = clean
            self._navigation_detail = {
                "enabled": not command.stop,
                "state": "arrived" if command.stop else "navigating",
                "directive": clean,
                "goal": place,
                "reason": command.note,
            }
        if command.stop:
            with self._lock:
                self._navigation_directive = None
            message = f"Already at {place}."
        else:
            message = f"Navigating to {place}."
        self._emit("navigation", message, "success")
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

    def action(self, name: str) -> str:
        if name == "follow":
            return self.set_behavior("follow")
        if name == "stay":
            return self.set_behavior("stay")
        if name == "stop":
            with self._command_lock:
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
        return {
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
            "personality": personality,
        }

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
        with self._lock:
            self._behavior_generation += 1
        self.stop_navigation()
        with self._command_lock:
            if self.arbiter.emergency_stopped:
                raise RuntimeError("motion is disabled by emergency stop")
            self.arbiter.stop()
            self.backend.pose(pose)

    def _run_trajectory(self, skill: object) -> None:
        if self.arbiter.emergency_stopped:
            raise RuntimeError("motion is disabled by emergency stop")
        self.follow.stop()
        with self._lock:
            self._behavior_generation += 1
        self.stop_navigation()
        with self._command_lock:
            if self.arbiter.emergency_stopped:
                raise RuntimeError("motion is disabled by emergency stop")
            self.arbiter.stop()
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
            self.voice_session.barge_in()
            reply = self.handle_text(clean)
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
            "follow": follow,
            "navigation": navigation,
            "audio": self.audio_status.as_dict(),
            "voice": voice,
            "model": {"status": self._model_status, "detail": self._model_detail},
            "robot": robot,
            "owner": owner,
            "dynamic_agents": dynamic_agents,
            "nearest_person": nearest_person,
            "obstacle_distance_m": obstacle,
            "collision": collision,
            "emergency_stopped": arbitration["emergency_stopped"],
            "motion": arbitration,
            "activities": self.activities.snapshot(),
            "events": events,
            "chat": chat,
        }

    def _control_loop(self) -> None:
        last_follow_state = ""
        while not self._stop_event.is_set():
            started = time.monotonic()
            if self._model_health_url and started >= self._next_model_probe:
                ready = http_service_health(self._model_health_url)
                self._model_status = "ready" if ready else "offline"
                self._next_model_probe = started + 5.0
            try:
                observation = self.backend.observe()
                with self._lock:
                    self._observation = observation
                    self._sim_status = "connected"
                    self._sim_error = ""
                if observation.emergency_stopped and not self.arbiter.emergency_stopped:
                    with self._command_lock:
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
                        self._activity_complete_at = 0.0
                        self.agent.safety.engage_emergency_stop()
                        self.arbiter.engage_emergency_stop()
                    self._emit("safety", "Simulator emergency stop adopted", "error")
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                observation = None
                self._record_sim_error(error)

            with self._lock:
                follow_generation = self._behavior_generation
            if self.follow.enabled:
                decision = self.follow.step(observation, now=time.monotonic())
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
                    level = "warning" if decision.state in {"blocked", "lost", "stale"} else "info"
                    self._emit("follow", f"{decision.state}: {decision.reason}", level)
                    last_follow_state = decision.state
                elif not still_following:
                    self.arbiter.cancel("follow")
                    last_follow_state = "idle"
            else:
                with self._lock:
                    self._follow_detail = self.follow.snapshot()
                last_follow_state = "idle"

            self._step_navigation(observation)

            self._step_activities()

            self._dispatch_active()
            elapsed = time.monotonic() - started
            self._stop_event.wait(max(0.0, self.loop_period - elapsed))

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
                # A rotate-in-place target is a discrete nonholonomic mode
                # transition. Brake translation immediately while retaining
                # angular smoothing, otherwise residual forward velocity makes
                # the robot arc/slide during the first alignment ticks.
                command = VelocityCommand(vyaw=command.vyaw)
            with self._lock:
                observation = self._observation
            command, proximity_state = self._collision_safe(command, observation)
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
            if active is not None and (command != self._last_sent or should_refresh):
                try:
                    self.backend.move(command)
                    self._last_sent = command
                    self._last_send_at = now
                    self._was_moving = any(
                        abs(value) > 1e-6 for value in (command.vx, command.vy, command.vyaw)
                    )
                except OSError as error:
                    self._record_sim_error(error)
            elif active is None and self._was_moving:
                try:
                    self.backend.stop()
                except OSError as error:
                    self._record_sim_error(error)
                self._last_sent = VelocityCommand()
                self._was_moving = False
                self.velocity_smoother.reset(now=now)

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
                    extras={
                        "obstacle_bearing_rad": observation.nearest_obstacle_bearing_rad,
                        "obstacle_id": observation.nearest_obstacle_id,
                        "person_bearing_rad": observation.nearest_person_bearing_rad,
                        "person_id": observation.nearest_person_id,
                        "person_ttc_s": observation.nearest_person_ttc_s,
                    },
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
        place = mission.goal.label or mission.goal.poi_id
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
            if command.stop:
                self._navigation_directive = None
                self._navigation_detail = {
                    "enabled": False,
                    "state": "arrived",
                    "directive": directive,
                    "goal": place,
                    "reason": command.note or "arrived",
                }
                self.arbiter.cancel("navigation")
            else:
                state = "blocked" if "stop" in command.note else "navigating"
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
        if command.stop:
            self._emit("navigation", f"Arrived at {place}", "success")
            return

    def _collision_safe(
        self,
        command: VelocityCommand,
        observation: SimObservation | None,
    ) -> tuple[VelocityCommand, str]:
        """Final reactive brake shared by voice, manual, follow, and navigation."""
        if observation is None:
            if math.hypot(command.vx, command.vy) > 1e-6:
                return VelocityCommand(vyaw=command.vyaw), "stopped"
            return command, "clear"
        if time.monotonic() - observation.timestamp > self.telemetry_stale_s:
            if math.hypot(command.vx, command.vy) > 1e-6:
                return VelocityCommand(vyaw=command.vyaw), "stopped"
            return command, "clear"
        translating = math.hypot(command.vx, command.vy) > 1e-6
        person_ttc = observation.nearest_person_ttc_s
        predictive_state = "clear"
        if translating and person_ttc is not None:
            if person_ttc <= 0.8:
                return VelocityCommand(vyaw=command.vyaw), "stopped"
            if person_ttc < 1.8:
                scale = max(0.15, (person_ttc - 0.8) / 1.0)
                command = VelocityCommand(
                    vx=command.vx * scale,
                    vy=command.vy * scale,
                    vyaw=command.vyaw,
                )
                predictive_state = "slowing"
        distance = observation.nearest_obstacle_m
        if not translating:
            return command, "clear"
        bearing = observation.nearest_obstacle_bearing_rad
        if bearing is None:
            toward_obstacle = command.vx > 0.0 or abs(command.vy) > 1e-6
        else:
            travel_angle = math.atan2(command.vy, command.vx)
            angle_error = (bearing - travel_angle + math.pi) % (2.0 * math.pi) - math.pi
            toward_obstacle = abs(angle_error) < 1.15
        if observation.collision and toward_obstacle:
            return VelocityCommand(vyaw=command.vyaw), "stopped"
        if not toward_obstacle:
            return command, predictive_state
        if distance is None:
            return command, predictive_state
        if distance <= self.obstacle_stop_m:
            return VelocityCommand(vyaw=command.vyaw), "stopped"
        if distance < self.obstacle_slow_m:
            span = self.obstacle_slow_m - self.obstacle_stop_m
            scale = max(0.15, (distance - self.obstacle_stop_m) / span)
            return (
                VelocityCommand(
                    vx=command.vx * scale,
                    vy=command.vy * scale,
                    vyaw=command.vyaw,
                ),
                "slowing",
            )
        return command, predictive_state

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
