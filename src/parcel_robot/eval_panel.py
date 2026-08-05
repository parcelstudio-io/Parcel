"""In-process NAV_INSTRUCT eval panel state for the web UI."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from evals.nav_instruct.generator import EpisodeSpec, generate_minival
from evals.nav_instruct.runner import NavInstructRunner, aggregate_results
from parcel_robot.instructnav.scoring import GoalRegion


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
