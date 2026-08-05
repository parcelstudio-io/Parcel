"""NAV_INSTRUCT_V1 headless episode runner over HeadlessCityWorld.

Drives directive → grounder → planner → control, records the trace fields
N-S1's scorer needs, and attributes failures. Baseline mode intentionally
uses today's frustum-gated grounding (no SemanticMemory / ScanForTarget).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import EpisodeSpec, generate_episode_matrix, generate_minival
from parcel_robot.headless_city import (
    DEFAULT_ROBOT_CONFIG,
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
    _nav_observation,
)
from parcel_robot.instructnav.scoring import (
    EpisodeScore,
    FailureClass,
    score_episode,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.goals import navigation_directive_from_text
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import apply_reactive_safety
from parcel_robot.navigation.spatial import parse_follow_intent, parse_spatial_intent

RUNNER_VERSION = "nav-instruct-v1.0"
DOES_NOT_PROVE = (
    "sim ground-truth semantics ≠ camera perception — closes with hardware perception",
    "absent-target honesty under open-vocab detectors (tier E guards the class only)",
    "downloaded VLM/VLA policies (rungs 6–7)",
)


@dataclass(frozen=True)
class EpisodeRunResult:
    episode_id: str
    family: str
    tier: str
    instruction: str
    score: EpisodeScore
    collision_count: int
    semantic_scan_steps: int
    mission_status: str
    reason: str
    grounding_outcome: str
    trace: tuple[dict[str, Any], ...]
    mode: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "family": self.family,
            "tier": self.tier,
            "instruction": self.instruction,
            "score": self.score.as_dict(),
            "collision_count": self.collision_count,
            "semantic_scan_steps": self.semantic_scan_steps,
            "mission_status": self.mission_status,
            "reason": self.reason,
            "grounding_outcome": self.grounding_outcome,
            "mode": self.mode,
            "trace_len": len(self.trace),
            "trace": list(self.trace),
        }


class NavInstructRunner:
    """Deterministic NAV_INSTRUCT_V1 executor."""

    def __init__(
        self,
        *,
        robot_config: str | Path = DEFAULT_ROBOT_CONFIG,
        max_steps: int = 400,
        mode: str = "baseline",
    ) -> None:
        self.robot_config = robot_config
        self.max_steps = int(max_steps)
        mode_norm = str(mode).strip().lower()
        if mode_norm not in {"baseline", "candidate"}:
            raise ValueError("mode must be 'baseline' or 'candidate'")
        self.mode = mode_norm
        self.world = HeadlessCityWorld()
        self.harness = HeadlessCityQualityHarness(
            self.world, robot_config=robot_config
        )

    def run_episode(self, episode: EpisodeSpec) -> EpisodeRunResult:
        owner = None
        placement = dict(episode.placement_overrides or {})
        owner_spec = placement.get("owner")
        if isinstance(owner_spec, dict) and "x" in owner_spec and "y" in owner_spec:
            owner = (float(owner_spec["x"]), float(owner_spec["y"]))
        self.world.reset(robot=episode.start_pose, owner=owner, restore_semantics=True)
        self.world.apply_placement_overrides(placement)
        family = episode.family
        if family in {"follow_owner", "circle_owner"}:
            return self._run_spatial(episode)
        return self._run_navigation(episode)

    def _navigator(self) -> DirectiveNavigator:
        """Baseline disables N-O2 memory/scan/frontier; candidate enables them."""

        return DirectiveNavigator.from_config(
            self.harness.navigation_config,
            instructnav_recovery=(self.mode == "candidate"),
        )

    def run_matrix(
        self,
        episodes: tuple[EpisodeSpec, ...] | None = None,
        *,
        seed: int = 20260804,
        minival: bool = False,
    ) -> list[EpisodeRunResult]:
        if episodes is None:
            episodes = (
                generate_minival(seed=seed)
                if minival
                else generate_episode_matrix(seed=seed, per_family=25)
            )
        return [self.run_episode(ep) for ep in episodes]

    def _run_navigation(self, episode: EpisodeSpec) -> EpisodeRunResult:
        text = episode.instruction
        directive = navigation_directive_from_text(text)
        if directive is None:
            # Honest baseline refusal path when the parser rejects the utterance.
            trace = [
                {
                    "t_s": 0.0,
                    "x": episode.start_pose[0],
                    "y": episode.start_pose[1],
                    "stopped": True,
                    "refusal": True,
                    "reply": "I couldn't form a safe, grounded plan yet.",
                    "grounding_outcome": "REFUSAL",
                    "note": "directive_not_understood",
                }
            ]
            score = score_episode(
                trace,
                episode.goal,
                shortest_path_m=episode.shortest_path_m,
                max_time_s=self.max_steps * self.world.control_dt_s,
            )
            return EpisodeRunResult(
                episode_id=episode.episode_id,
                family=episode.family,
                tier=episode.tier,
                instruction=text,
                score=score,
                collision_count=0,
                semantic_scan_steps=0,
                mission_status="failed",
                reason="directive_not_understood",
                grounding_outcome="REFUSAL",
                trace=tuple(trace),
                mode=self.mode,
            )

        navigator = self._navigator()
        mission = navigator.start(directive)
        trace: list[dict[str, Any]] = []
        scan_steps = 0
        grounding_outcome = "UNSEEN"
        reason = "navigation_step_limit"
        terminal_status = mission.status
        try:
            for _ in range(self.max_steps):
                observation = self.world.observe()
                command = navigator.step(
                    _nav_observation(
                        observation,
                        measured_velocity=self.world.command,
                        stop_confirmed=self.world.stopped,
                        settled_linear_speed_mps=self.harness._settled_linear_speed_mps,
                        settled_yaw_speed_rad_s=self.harness._settled_yaw_speed_rad_s,
                    )
                )
                note = command.note or ""
                if note.startswith("semantic_search_scan"):
                    scan_steps += 1
                resolution = str(mission.metadata.get("resolution_state") or "")
                if resolution == "resolved":
                    grounding_outcome = "RESOLVED"
                elif resolution == "searching" or resolution == "not_found":
                    grounding_outcome = "UNSEEN"
                elif resolution == "unreachable":
                    grounding_outcome = "RESOLVED"

                requested = (
                    VelocityCommand()
                    if command.stop
                    else VelocityCommand(command.vx, command.vy, command.vyaw)
                )
                velocity, _ = apply_reactive_safety(
                    requested,
                    observation,
                    policy=self.harness.reactive_safety,
                    owner_orbit=False,
                    orbit_radius_m=0.0,
                    now=observation.timestamp,
                    require_fresh_telemetry=False,
                )
                stopped = (
                    abs(velocity.vx) <= 1e-9
                    and abs(velocity.vy) <= 1e-9
                    and abs(velocity.vyaw) <= 1e-9
                )
                robot = observation.robot
                step_rec: dict[str, Any] = {
                    "t_s": float(observation.timestamp),
                    "x": float(robot.x),
                    "y": float(robot.y),
                    "stopped": stopped,
                    "vx": float(velocity.vx),
                    "vy": float(velocity.vy),
                    "note": note,
                    "resolution_state": resolution,
                    "grounding_outcome": grounding_outcome,
                    "collision": self.world.collision_count > 0,
                    "attempted": True,
                }
                if resolution == "not_found":
                    step_rec["not_found"] = True
                    if scan_steps > 0 or "frontier" in note:
                        step_rec["search_error"] = True
                    else:
                        step_rec["grounding_error"] = True
                if resolution == "unseen" and mission.status == "failed":
                    step_rec["not_found"] = True
                    step_rec["grounding_error"] = True
                if "semantic_target_not_found" in note:
                    reply = str(mission.metadata.get("reply") or "")
                    if scan_steps > 0 or self._frontier_attempted(trace, note):
                        step_rec["search_error"] = True
                        step_rec["not_found"] = True
                        step_rec["reply"] = reply or (
                            "I looked around and couldn't find the target nearby"
                        )
                    else:
                        step_rec["grounding_error"] = True
                        step_rec["not_found"] = True
                        step_rec["reply"] = reply or (
                            "I couldn't form a safe, grounded plan yet."
                        )
                        if self.mode == "baseline":
                            step_rec["refusal"] = True
                if mission.status == "failed" and resolution in {"", "unresolved"}:
                    step_rec["refusal"] = True
                    step_rec["reply"] = "I couldn't form a safe, grounded plan yet."
                trace.append(step_rec)
                self.world.apply(velocity)
                if (command.stop and mission.status != "verifying") or navigator.done():
                    reason = note
                    terminal_status = mission.status
                    break
                self.world.step()
            else:
                mission.status = "failed"
                terminal_status = "timed_out"
                reason = "navigation_step_limit"
        finally:
            self.world.stop()
            navigator.close()

        if not trace:
            trace = [
                {
                    "t_s": 0.0,
                    "x": episode.start_pose[0],
                    "y": episode.start_pose[1],
                    "stopped": True,
                    "refusal": True,
                    "reply": "I couldn't form a safe, grounded plan yet.",
                }
            ]

        if (
            terminal_status == "failed"
            and grounding_outcome == "UNSEEN"
            and scan_steps > 0
            and not any(step.get("search_error") or step.get("grounding_error") for step in trace)
        ):
            trace[-1]["search_error"] = True
            trace[-1]["not_found"] = True

        if episode.absent_target and terminal_status == "failed":
            # Tier E: bounded miss then report — search only if recovery ran.
            if scan_steps > 0 or any(
                "frontier" in str(step.get("note") or "")
                or "scan" in str(step.get("note") or "")
                for step in trace
            ):
                trace[-1]["search_error"] = True
            else:
                trace[-1]["grounding_error"] = True
            trace[-1]["not_found"] = True

        score = score_episode(
            trace,
            episode.goal,
            shortest_path_m=max(episode.shortest_path_m, 1e-3),
            max_time_s=self.max_steps * self.world.control_dt_s,
            arrival_hold_s=1.0,
            anchor_xy=episode.goal.center,
        )
        return EpisodeRunResult(
            episode_id=episode.episode_id,
            family=episode.family,
            tier=episode.tier,
            instruction=text,
            score=score,
            collision_count=int(self.world.collision_count),
            semantic_scan_steps=scan_steps,
            mission_status=str(terminal_status),
            reason=reason,
            grounding_outcome=grounding_outcome,
            trace=tuple(trace),
            mode=self.mode,
        )

    def _run_spatial(self, episode: EpisodeSpec) -> EpisodeRunResult:
        """Follow/circle regression lane via the existing spatial/follow harness."""

        text = episode.instruction
        understood = parse_follow_intent(text) or parse_spatial_intent(text) is not None
        result = self.harness.run(text, max_steps=self.max_steps)
        trace = _trace_from_harness(result, episode)
        if not understood or result.reason == "directive_not_understood":
            if trace:
                trace[-1]["refusal"] = True
                trace[-1]["reply"] = "I couldn't form a safe, grounded plan yet."
            score = score_episode(
                trace,
                episode.goal,
                shortest_path_m=max(episode.shortest_path_m, 1e-3),
                max_time_s=self.max_steps * self.world.control_dt_s,
            )
            return EpisodeRunResult(
                episode_id=episode.episode_id,
                family=episode.family,
                tier=episode.tier,
                instruction=text,
                score=score,
                collision_count=int(result.collision_count),
                semantic_scan_steps=int(result.semantic_scan_steps),
                mission_status=str(result.status),
                reason=str(result.reason),
                grounding_outcome="REFUSAL",
                trace=tuple(trace),
                mode=self.mode,
            )

        if result.collision_count > 0:
            trace[-1]["collision"] = True
            trace[-1]["control_error"] = True
        # Score real poses only — never teleport into the goal disc.
        score = score_episode(
            trace,
            episode.goal,
            shortest_path_m=max(episode.shortest_path_m, 1e-3),
            max_time_s=self.max_steps * self.world.control_dt_s,
            arrival_hold_s=0.0,
        )
        return EpisodeRunResult(
            episode_id=episode.episode_id,
            family=episode.family,
            tier=episode.tier,
            instruction=text,
            score=score,
            collision_count=int(result.collision_count),
            semantic_scan_steps=int(result.semantic_scan_steps),
            mission_status=str(result.status),
            reason=str(result.reason),
            grounding_outcome="RESOLVED",
            trace=tuple(trace),
            mode=self.mode,
        )

    @staticmethod
    def _frontier_attempted(trace: list[dict[str, Any]], note: str) -> bool:
        if "frontier" in note or "scan_for_target" in note:
            return True
        return any(
            "frontier" in str(step.get("note") or "")
            or "scan_for_target" in str(step.get("note") or "")
            for step in trace
        )


def _trace_from_harness(result: Any, episode: EpisodeSpec) -> list[dict[str, Any]]:
    samples = list(getattr(result, "trace", ()) or ())
    if not samples:
        return [
            {
                "t_s": 0.0,
                "x": episode.start_pose[0],
                "y": episode.start_pose[1],
                "stopped": True,
                "attempted": True,
                "note": str(getattr(result, "reason", "")),
            }
        ]
    out: list[dict[str, Any]] = []
    for sample in samples:
        robot = sample.robot
        cmd = sample.command
        stopped = abs(cmd.vx) <= 1e-9 and abs(cmd.vy) <= 1e-9 and abs(cmd.vyaw) <= 1e-9
        if hasattr(robot, "x"):
            rx, ry = float(robot.x), float(robot.y)
        else:
            rx, ry = float(robot[0]), float(robot[1])
        out.append(
            {
                "t_s": float(sample.time_s),
                "x": rx,
                "y": ry,
                "stopped": stopped,
                "vx": float(cmd.vx),
                "vy": float(cmd.vy),
                "note": str(sample.note),
                "attempted": True,
            }
        )
    return out


def aggregate_results(results: list[EpisodeRunResult]) -> dict[str, Any]:
    """Family × tier dashboard: SR, SPL, DTG, failure histogram."""

    cells: dict[str, dict[str, Any]] = {}
    failure_hist: dict[str, int] = {item.value: 0 for item in FailureClass}
    collisions = 0
    for result in results:
        key = f"{result.family}|{result.tier}"
        cell = cells.setdefault(
            key,
            {
                "family": result.family,
                "tier": result.tier,
                "n": 0,
                "successes": 0,
                "spl_sum": 0.0,
                "dtg_sum": 0.0,
                "failures": {item.value: 0 for item in FailureClass},
            },
        )
        cell["n"] += 1
        cell["successes"] += int(result.score.success)
        cell["spl_sum"] += float(result.score.spl)
        dtg = result.score.distance_to_goal_m
        cell["dtg_sum"] += 0.0 if not math.isfinite(dtg) else float(dtg)
        cell["failures"][result.score.failure.value] += 1
        failure_hist[result.score.failure.value] += 1
        collisions += int(result.collision_count)

    dashboard = []
    for key in sorted(cells):
        cell = cells[key]
        n = max(cell["n"], 1)
        dashboard.append(
            {
                "family": cell["family"],
                "tier": cell["tier"],
                "n": cell["n"],
                "sr": cell["successes"] / n,
                "spl": cell["spl_sum"] / n,
                "dtg_m": cell["dtg_sum"] / n,
                "failures": cell["failures"],
            }
        )
    n_all = max(len(results), 1)
    return {
        "runner_version": RUNNER_VERSION,
        "n": len(results),
        "sr": sum(1 for r in results if r.score.success) / n_all,
        "spl": sum(r.score.spl for r in results) / n_all,
        "collision_total": collisions,
        "failure_histogram": failure_hist,
        "by_family_tier": dashboard,
        "does_not_prove": list(DOES_NOT_PROVE),
    }
