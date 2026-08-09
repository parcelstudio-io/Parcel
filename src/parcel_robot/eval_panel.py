"""In-process NAV_INSTRUCT eval panel state for the web UI."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from evals.nav_instruct.generator import EpisodeSpec, generate_minival
from evals.nav_instruct.runner import NavInstructRunner, aggregate_results
from parcel_robot.instructnav.scoring import GoalRegion, score_episode

#: Terminal task states in the executive snapshot.
TERMINAL_TASK_STATES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})

#: Voice-mode budget. Must dominate the NavigateTo contract timeout (240 s) so
#: the panel observes the system's own terminal verdict instead of racing it —
#: the same budget-ordering rule the voice→nav e2e gate uses.
VOICE_DEADLINE_S: float = 270.0
VOICE_POLL_S: float = 0.5

#: Speed below which a sample counts as stopped (matches the scorer default).
STOPPED_SPEED_MPS: float = 0.05


@dataclass
class EvalPanelState:
    scenarios: tuple[EpisodeSpec, ...] = field(default_factory=tuple)
    active_episode_id: str | None = None
    active_goal: GoalRegion | None = None
    active_instruction: str | None = None
    status: str = "idle"  # idle|running|done|error
    mode: str = "headless"
    progress: float = 0.0
    last_result: dict[str, Any] | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    search_state: str | None = None
    error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def ensure_scenarios(self, *, seed: int = 20260804) -> None:
        with self._lock:
            if not self.scenarios:
                self.scenarios = generate_minival(seed=seed)

    def list_scenarios(self) -> list[dict[str, Any]]:
        self.ensure_scenarios()
        with self._lock:
            out = []
            for ep in self.scenarios:
                payload = ep.as_dict()
                # Attach last result if any.
                match = next(
                    (r for r in self.results if r.get("episode_id") == ep.episode_id),
                    None,
                )
                payload["last_result"] = match
                out.append(payload)
            return out

    def select(self, episode_id: str) -> dict[str, Any]:
        self.ensure_scenarios()
        with self._lock:
            ep = next((e for e in self.scenarios if e.episode_id == episode_id), None)
            if ep is None:
                raise KeyError(f"unknown episode_id: {episode_id}")
            self.active_episode_id = ep.episode_id
            self.active_goal = ep.goal
            self.active_instruction = ep.instruction
            self.search_state = None
            return {
                "episode_id": ep.episode_id,
                "instruction": ep.instruction,
                "goal_region": ep.goal.as_dict(),
                "family": ep.family,
                "tier": ep.tier,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "mode": self.mode,
                "progress": self.progress,
                "active_episode_id": self.active_episode_id,
                "active_instruction": self.active_instruction,
                "goal_region": (
                    self.active_goal.as_dict() if self.active_goal is not None else None
                ),
                "search_state": self.search_state,
                "last_result": self.last_result,
                "error": self.error,
                "scenario_count": len(self.scenarios),
                "result_count": len(self.results),
            }

    def start_headless(self, episode_id: str) -> dict[str, Any]:
        selected = self.select(episode_id)
        with self._lock:
            if self.status == "running":
                raise RuntimeError("eval already running")
            self.status = "running"
            self.mode = "headless"
            self.progress = 0.05
            self.error = None
            self.last_result = None
        thread = threading.Thread(
            target=self._run_headless,
            args=(episode_id,),
            daemon=True,
            name="nav-instruct-eval",
        )
        thread.start()
        return selected

    def _run_headless(self, episode_id: str) -> None:
        try:
            self.ensure_scenarios()
            ep = next(e for e in self.scenarios if e.episode_id == episode_id)
            runner = NavInstructRunner(max_steps=200, mode="candidate")
            with self._lock:
                self.search_state = "scanning"
                self.progress = 0.2
            result = runner.run_episode(ep)
            payload = result.as_dict()
            # Drop bulky trace from panel payload.
            payload.pop("trace", None)
            with self._lock:
                self.results.append(payload)
                self.last_result = {
                    "episode_id": result.episode_id,
                    "success": result.score.success,
                    "failure": result.score.failure.value,
                    "spl": result.score.spl,
                    "distance_to_goal_m": result.score.distance_to_goal_m,
                    "reason": result.reason,
                    "grounding_outcome": result.grounding_outcome,
                    "collision_count": result.collision_count,
                }
                self.search_state = result.grounding_outcome
                self.progress = 1.0
                self.status = "done"
        except Exception as error:  # noqa: BLE001 — surface to panel
            with self._lock:
                self.status = "error"
                self.error = str(error)[:500]
                self.progress = 1.0

    def start_voice(
        self,
        episode_id: str,
        runtime: Any,
        *,
        deadline_s: float = VOICE_DEADLINE_S,
    ) -> dict[str, Any]:
        """Run one scenario through the **product path** on the live runtime.

        Default (headless) mode drives ``DirectiveNavigator`` directly — fast,
        but blind to everything above the navigator, which is exactly where the
        2026-08-05 admission regression lived. Voice mode instead types the
        scenario's instruction into ``runtime.handle_text``: intent route →
        local PlanSketch → PlanIR admission → TaskExecutive → navigation. The
        goal region is published by :meth:`select` *before* the run starts, so
        the ``/viewer`` overlay marks the region pre-run and the verdict lands
        on the same region at the end (the task_6 gate).

        Sequential by construction: this reuses the existing ``status ==
        "running"`` guard that headless/batch runs already share, so a second
        request is refused rather than queued. There is one live runtime and
        one city; concurrency here would be a lie about isolation.
        """

        selected = self.select(episode_id)
        with self._lock:
            if self.status == "running":
                raise RuntimeError("eval already running")
            self.status = "running"
            self.mode = "voice"
            self.progress = 0.05
            self.error = None
            self.last_result = None
        thread = threading.Thread(
            target=self._run_voice,
            args=(episode_id, runtime, float(deadline_s)),
            daemon=True,
            name="nav-voice-eval",
        )
        thread.start()
        return {**selected, "mode": "voice"}

    def _run_voice(self, episode_id: str, runtime: Any, deadline_s: float) -> None:
        try:
            self.ensure_scenarios()
            ep = next(e for e in self.scenarios if e.episode_id == episode_id)
            reply = str(runtime.handle_text(ep.instruction))
            with self._lock:
                self.search_state = "dispatched"
                self.progress = 0.15
            trace: list[dict[str, Any]] = []
            states: list[str] = []
            started = time.monotonic()
            while True:
                elapsed = time.monotonic() - started
                snapshot = runtime.snapshot()
                sample = _pose_sample(snapshot, elapsed, trace[-1] if trace else None)
                if sample is not None:
                    trace.append(sample)
                states = _task_states(snapshot)
                with self._lock:
                    self.progress = min(0.95, 0.15 + 0.8 * (elapsed / max(deadline_s, 1e-6)))
                if states and all(state in TERMINAL_TASK_STATES for state in states):
                    break
                if elapsed >= deadline_s:
                    break
                time.sleep(VOICE_POLL_S)

            system_verified = bool(states) and all(state == "succeeded" for state in states)
            score = (
                score_episode(
                    trace,
                    ep.goal,
                    shortest_path_m=max(ep.shortest_path_m, 1e-6),
                    max_time_s=deadline_s,
                )
                if trace
                else None
            )
            predicate_success = bool(score is not None and score.success)
            payload = {
                "episode_id": ep.episode_id,
                "mode": "voice",
                "instruction": ep.instruction,
                "reply": reply,
                # A claim without the predicate is a failure, and so is the
                # reverse — the same rule as the voice→nav e2e gate.
                "success": bool(system_verified and predicate_success),
                "system_verified": system_verified,
                "predicate_success": predicate_success,
                "task_states": states,
                "failure": (score.failure.value if score is not None else "refusal"),
                "distance_to_goal_m": (
                    score.distance_to_goal_m if score is not None else float("inf")
                ),
                "spl": (score.spl if score is not None else 0.0),
                "sample_count": len(trace),
            }
            with self._lock:
                self.results.append(payload)
                self.last_result = payload
                self.search_state = "voice_done"
                self.progress = 1.0
                self.status = "done"
        except Exception as error:  # noqa: BLE001 — surface to panel
            with self._lock:
                self.status = "error"
                self.error = str(error)[:500]
                self.progress = 1.0

    def start_batch(self, *, mode: str = "candidate") -> dict[str, Any]:
        """Kick a threaded minival batch (all scenarios)."""

        self.ensure_scenarios()
        with self._lock:
            if self.status == "running":
                raise RuntimeError("eval already running")
            self.status = "running"
            self.mode = "headless"
            self.progress = 0.0
            self.error = None
            self.last_result = None
            count = len(self.scenarios)
        thread = threading.Thread(
            target=self._run_batch,
            args=(mode,),
            daemon=True,
            name="nav-instruct-batch",
        )
        thread.start()
        return {"accepted": True, "mode": "batch", "scenario_count": count}

    def run_batch_summary(self, *, mode: str = "candidate") -> dict[str, Any]:
        """Synchronous batch helper (CLI/tests). Prefer :meth:`start_batch` for UI."""

        return self._run_batch(mode)

    def _run_batch(self, mode: str = "candidate") -> dict[str, Any]:
        self.ensure_scenarios()
        runner = NavInstructRunner(max_steps=120, mode=mode)
        with self._lock:
            self.status = "running"
            self.mode = "headless"
            episodes = list(self.scenarios)
        results = []
        try:
            for index, ep in enumerate(episodes):
                with self._lock:
                    self.active_episode_id = ep.episode_id
                    self.active_goal = ep.goal
                    self.active_instruction = ep.instruction
                    self.progress = (index + 0.5) / max(len(episodes), 1)
                    self.search_state = "running"
                result = runner.run_episode(ep)
                payload = result.as_dict()
                payload.pop("trace", None)
                results.append(result)
                with self._lock:
                    self.results.append(payload)
            summary = aggregate_results(results)
            with self._lock:
                self.status = "done"
                self.progress = 1.0
                self.search_state = "batch_done"
                self.last_result = {"batch": True, **summary}
            return summary
        except Exception as error:
            with self._lock:
                self.status = "error"
                self.error = str(error)[:500]
                self.progress = 1.0
            raise


def _task_states(snapshot: Any) -> list[str]:
    brain = snapshot.get("brain") if isinstance(snapshot, dict) else None
    rows = brain.get("tasks") if isinstance(brain, dict) else None
    if not isinstance(rows, list):
        return []
    return [str(row.get("state")) for row in rows if isinstance(row, dict)]


def _pose_sample(
    snapshot: Any,
    elapsed_s: float,
    previous: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """One scorer-shaped trace row from the panel's own ``/api/state`` payload.

    Speed is differentiated from consecutive poses rather than read from a
    telemetry field, so the settle gate stays true to what the robot actually
    did instead of what a controller reported.
    """

    robot = snapshot.get("robot") if isinstance(snapshot, dict) else None
    if not isinstance(robot, dict):
        return None
    try:
        x = float(robot["x"])
        y = float(robot["y"])
    except (KeyError, TypeError, ValueError):
        return None
    speed = 0.0
    if previous is not None:
        dt = max(float(elapsed_s) - float(previous["t_s"]), 1e-6)
        speed = math.hypot(x - float(previous["x"]), y - float(previous["y"])) / dt
    return {
        "t_s": float(elapsed_s),
        "x": x,
        "y": y,
        "speed_mps": speed,
        "stopped": speed <= STOPPED_SPEED_MPS,
    }


EVAL_PANEL = EvalPanelState()


def live_goal_overlay() -> dict[str, Any] | None:
    """Goal region for the viewer — same GoalRegion the scorer uses."""

    snap = EVAL_PANEL.snapshot()
    region = snap.get("goal_region")
    if region is None:
        return None
    return {
        "goal_region": region,
        "instruction": snap.get("active_instruction"),
        "search_state": snap.get("search_state"),
        "eval_status": snap.get("status"),
        "last_result": snap.get("last_result"),
        "updated_s": time.time(),
    }
