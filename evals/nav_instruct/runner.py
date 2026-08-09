"""NAV_INSTRUCT headless episode runner over HeadlessCityWorld.

Drives directive → grounder → planner → control, records the trace fields
N-S1's scorer needs, and attributes failures. Baseline mode intentionally
uses today's frustum-gated grounding (no SemanticMemory / ScanForTarget).

Arrival rules (re-freeze correction (c))
----------------------------------------
The runner ends an episode one 0.1 s control tick after the mission's own
``arrived_verified``, while ``score_episode`` wants the robot inside the goal
and stopped for ``arrival_hold_s = 1.0 s``. Under the v1 rule those two facts
are incompatible and the hold can never accumulate — U31. The v2 default is
``hold-or-trace-end-v1``, the rule ``evals/nav_instruct/rescore.py`` documents
and applied to the persisted v1 traces: arrived iff the frozen hold accumulates
**or** the trace ends inside-and-stopped without being cut off by the step
limit. Both numbers are recorded on every episode
(``score`` under the active rule, ``frozen_rule_success`` under the v1 rule), so
switching the rule can never hide what the old rule would have said.

The rule lives here and **not** in ``instructnav/scoring.py``: the scorer is the
shared K0 authority used by the runtime and by two other harnesses, and a rule
that reasons about *how the recording ended* is a property of this harness, not
of arrival.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import (
    DEFAULT_EPISODE_SET_VERSION,
    EpisodeSpec,
    episode_set_spec,
    generate_episode_matrix,
    generate_minival,
)
from evals.nav_instruct.rescore import (
    DERIVED_RULE_ID,
    derived_arrival,
    promoted_derived_score,
)
from parcel_robot.headless_city import (
    DEFAULT_ROBOT_CONFIG,
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
    _nav_observation,
)
from parcel_robot.instructnav.scoring import (
    ARRIVAL_BOUNDARY_EPSILON_M,
    AuthorityCategory,
    EpisodeScore,
    FailureClass,
    score_episode,
    system_arrival_claim,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.goals import navigation_directive_from_text
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import apply_reactive_safety
from parcel_robot.navigation.spatial import parse_follow_intent, parse_spatial_intent

RUNNER_VERSION = "nav-instruct-v1.1-k0-arrival"

#: The v1 arrival rule: ``score_episode``'s hold, exactly as frozen.
FROZEN_ARRIVAL_RULE = "frozen-hold-v1"
#: The v2 arrival rule (re-freeze correction (c)).
DERIVED_ARRIVAL_RULE = DERIVED_RULE_ID
ARRIVAL_RULES: tuple[str, ...] = (FROZEN_ARRIVAL_RULE, DERIVED_ARRIVAL_RULE)

#: The rule a fresh run uses unless told otherwise. Changing this default does
#: not and cannot move a frozen row — frozen rows are persisted artifacts.
DEFAULT_ARRIVAL_RULE = DERIVED_ARRIVAL_RULE

#: Which arrival rule each episode-set version was frozen under.
ARRIVAL_RULE_FOR_VERSION: dict[str, str] = {
    "v1": FROZEN_ARRIVAL_RULE,
    "v1a-scene-truth-only": FROZEN_ARRIVAL_RULE,
    "v2": DERIVED_ARRIVAL_RULE,
    # v3 changes the next_to band only; the arrival rule is v2's, unchanged, so
    # a v2 -> v3 difference cannot contain a rule change.
    "v3": DERIVED_ARRIVAL_RULE,
}
DOES_NOT_PROVE = (
    "sim ground-truth semantics ≠ camera perception — closes with hardware perception",
    "absent-target honesty under open-vocab detectors (tier E guards the class only)",
    "downloaded VLM/VLA policies (rungs 6–7)",
)

# --- step-budget policies (card budget-honest-minival, 2026-08-09) ------------
#: "fixed" is the frozen behaviour every persisted row was run under: one flat
#: ``max_steps`` for every episode, regardless of how far its start pose sits
#: from the goal. That conflates capability with distance — the audit's
#: "candidate SR 0.12 -> 0.48 by raising --max-steps alone" artifact, where a
#: 56 m tier-E reach and a 3 m tier-A reach are scored under the identical clock.
#: "scaled-path-v1" derives a per-episode budget from the episode's OWN
#: ``shortest_path_m`` so a tier-E truncation is attributable to a genuine miss,
#: not to budget starvation. It is a NEW policy version: the default stays
#: "fixed", so every frozen row and every existing test is byte-identical.
FIXED_BUDGET_POLICY = "fixed"
SCALED_BUDGET_POLICY = "scaled-path-v1"
BUDGET_POLICIES: tuple[str, ...] = (FIXED_BUDGET_POLICY, SCALED_BUDGET_POLICY)
DEFAULT_BUDGET_POLICY = FIXED_BUDGET_POLICY

#: Only the point-goal families scale with a path. The spatial families
#: (follow/circle) are continuous behaviours whose budget is a duration, not a
#: distance, so they keep the flat base budget under every policy.
_PATH_SCALED_FAMILIES = frozenset({"region_goal", "object_goal", "object_relative"})
#: Fixed overhead a navigation episode pays regardless of path length: the
#: opening look-around/scan to acquire the target (~80 steps for a revolution at
#: the search yaw-rate) plus the terminal align + settle + verification hold
#: (~40). Measured from the pacing traces.
_BUDGET_OVERHEAD_STEPS = 120
#: Effective net planning progress along the path (m/s). Deliberately well below
#: the 0.85 m/s cruise: it amortises slowdown, alignment, detours and the
#: reactive gate over the whole path. A SMALLER number is a MORE generous
#: budget, which is the safe direction for "not budget starvation".
_BUDGET_PLANNING_SPEED_MPS = 0.30
#: The sim control tick the runner's world advances at.
_BUDGET_CONTROL_DT_S = 0.1
#: Upper bound so a phantom tier-E path (absent target ~56 m away) cannot demand
#: an unbounded run: an absent target completes its bounded scan+frontier search
#: and reports NOT_FOUND well inside this, and a present far target is reachable
#: within it. Keeps the honest-failure claim without an open-ended compute cost.
_BUDGET_CAP_STEPS = 1200


def scaled_step_budget(episode: EpisodeSpec, base_steps: int, policy: str) -> int:
    """Per-episode step budget under ``policy`` (see :data:`BUDGET_POLICIES`).

    ``fixed`` returns ``base_steps`` unchanged for every episode — byte-identical
    to every frozen row. ``scaled-path-v1`` derives a budget from the episode's
    own ``shortest_path_m`` for the point-goal families, floored at ``base_steps``
    (a scaled budget only ever ADDS room, never removes it) and capped at
    ``_BUDGET_CAP_STEPS``.
    """

    if policy == FIXED_BUDGET_POLICY:
        return int(base_steps)
    if policy != SCALED_BUDGET_POLICY:
        raise ValueError(f"budget_policy must be one of {BUDGET_POLICIES}")
    if episode.family not in _PATH_SCALED_FAMILIES:
        return int(base_steps)
    travel_steps = math.ceil(
        max(0.0, float(episode.shortest_path_m))
        / (_BUDGET_PLANNING_SPEED_MPS * _BUDGET_CONTROL_DT_S)
    )
    return int(max(base_steps, min(_BUDGET_CAP_STEPS, _BUDGET_OVERHEAD_STEPS + travel_steps)))


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
    #: Which arrival rule produced ``score.success``.
    arrival_rule: str = FROZEN_ARRIVAL_RULE
    #: What the frozen v1 hold rule would have said about this same trace.
    #: Equal to ``score.success`` when ``arrival_rule`` is the frozen one.
    frozen_rule_success: bool = False
    #: Which half of ``hold-or-trace-end-v1`` fired: ``frozen_hold`` /
    #: ``trace_end_hold`` / ``none``.
    arrival_branch: str = "frozen_hold"
    #: The effective step budget this episode ran under (card
    #: budget-honest-minival). Under the "fixed" policy every episode carries the
    #: same base; under "scaled-path-v1" it is the per-episode scaled budget, so
    #: a truncation can be read against the room the episode actually had.
    max_steps: int = 0

    @property
    def scorer_arrival(self) -> bool:
        """K0 GoalRegion predicate on the final pose (no settle hold)."""

        return bool(self.score.scorer_arrival)

    @property
    def system_arrival(self) -> bool | None:
        """The navigator's own arrival claim for this episode."""

        return self.score.system_arrival

    @property
    def authority_category(self) -> str:
        """Differential-authority verdict category (eval instrument 5)."""

        return self.score.authority_category.value

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
            # Correction (c) — both rules, always, so neither can hide the other.
            "arrival_rule": self.arrival_rule,
            "frozen_rule_success": self.frozen_rule_success,
            "arrival_branch": self.arrival_branch,
            # Instrument 5 — both arrival authorities, logged every episode.
            "scorer_arrival": self.scorer_arrival,
            "system_arrival": self.system_arrival,
            "authority_category": self.authority_category,
            "arrival_epsilon_m": ARRIVAL_BOUNDARY_EPSILON_M,
            "max_steps": self.max_steps,
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
        arrival_rule: str = DEFAULT_ARRIVAL_RULE,
        scene: str | Path | None = None,
        budget_policy: str = DEFAULT_BUDGET_POLICY,
    ) -> None:
        self.robot_config = robot_config
        self.max_steps = int(max_steps)
        mode_norm = str(mode).strip().lower()
        if mode_norm not in {"baseline", "candidate"}:
            raise ValueError("mode must be 'baseline' or 'candidate'")
        self.mode = mode_norm
        policy = str(budget_policy).strip()
        if policy not in BUDGET_POLICIES:
            raise ValueError(f"budget_policy must be one of {BUDGET_POLICIES}")
        self.budget_policy = policy
        rule = str(arrival_rule).strip()
        if rule not in ARRIVAL_RULES:
            raise ValueError(f"arrival_rule must be one of {ARRIVAL_RULES}")
        self.arrival_rule = rule
        self.world = (
            HeadlessCityWorld() if scene is None else HeadlessCityWorld(scene)
        )
        self.scene = str(self.world.scene)
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

    def _apply_arrival_rule(
        self,
        score: EpisodeScore,
        trace: list[dict[str, Any]],
        episode: EpisodeSpec,
        *,
        anchor_xy: tuple[float, float] | None,
    ) -> tuple[EpisodeScore, bool, str]:
        """Return ``(score under the active rule, frozen verdict, branch)``.

        Only the navigation families reach this: the spatial families are scored
        with ``arrival_hold_s = 0.0``, where the derived rule is a no-op by
        construction, and the refusal paths never claim arrival at all.
        """

        frozen_success = bool(score.success)
        if self.arrival_rule == FROZEN_ARRIVAL_RULE:
            return score, frozen_success, "frozen_hold" if frozen_success else "none"
        derived_success, branch = derived_arrival(
            trace, episode.goal, frozen_success=frozen_success, anchor_xy=anchor_xy
        )
        if derived_success == frozen_success:
            return score, frozen_success, branch
        promoted = promoted_derived_score(
            score, trace, shortest_path_m=episode.shortest_path_m
        )
        return promoted, frozen_success, branch

    def _navigator(self) -> DirectiveNavigator:
        """Baseline disables N-O2 memory/scan/frontier; candidate enables them."""

        return DirectiveNavigator.from_config(
            self.harness.navigation_config,
            instructnav_recovery=(self.mode == "candidate"),
        )

    def _episode_max_steps(self, episode: EpisodeSpec) -> int:
        """The effective step budget for ``episode`` under the active policy."""

        return scaled_step_budget(episode, self.max_steps, self.budget_policy)

    def run_matrix(
        self,
        episodes: tuple[EpisodeSpec, ...] | None = None,
        *,
        seed: int = 20260804,
        minival: bool = False,
        version: str = DEFAULT_EPISODE_SET_VERSION,
    ) -> list[EpisodeRunResult]:
        if episodes is None:
            episodes = (
                generate_minival(seed=seed, version=version)
                if minival
                else generate_episode_matrix(seed=seed, per_family=25, version=version)
            )
        return [self.run_episode(ep) for ep in episodes]

    def _run_navigation(self, episode: EpisodeSpec) -> EpisodeRunResult:
        text = episode.instruction
        budget = self._episode_max_steps(episode)
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
                max_time_s=budget * self.world.control_dt_s,
                system_arrival=system_arrival_claim("failed", "directive_not_understood"),
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
                arrival_rule=self.arrival_rule,
                frozen_rule_success=bool(score.success),
                arrival_branch="frozen_hold" if score.success else "none",
                max_steps=budget,
            )

        navigator = self._navigator()
        mission = navigator.start(directive)
        trace: list[dict[str, Any]] = []
        scan_steps = 0
        grounding_outcome = "UNSEEN"
        reason = "navigation_step_limit"
        terminal_status = mission.status
        try:
            for _ in range(budget):
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
                if trace and episode.goal.contains(
                    float(trace[-1]["x"]),
                    float(trace[-1]["y"]),
                    anchor_xy=episode.goal.center,
                ):
                    reason = "navigation_step_limit_inside_goal"
                    trace[-1]["termination_error"] = True
                    trace[-1]["step_limit"] = True
                    trace[-1]["note"] = reason
                elif trace:
                    trace[-1]["step_limit"] = True
                    trace[-1]["note"] = reason
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

        # Instrument 5: the navigator's own arrival claim, recorded next to the
        # scorer's K0 predicate on every episode — never merged into it.
        claimed_arrival = system_arrival_claim(terminal_status, reason)
        if trace:
            trace[-1]["system_arrival"] = claimed_arrival
        score = score_episode(
            trace,
            episode.goal,
            shortest_path_m=max(episode.shortest_path_m, 1e-3),
            max_time_s=budget * self.world.control_dt_s,
            arrival_hold_s=1.0,
            anchor_xy=episode.goal.center,
            system_arrival=claimed_arrival,
        )
        score, frozen_success, branch = self._apply_arrival_rule(
            score, trace, episode, anchor_xy=episode.goal.center
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
            arrival_rule=self.arrival_rule,
            frozen_rule_success=frozen_success,
            arrival_branch=branch,
            max_steps=budget,
        )

    def _run_spatial(self, episode: EpisodeSpec) -> EpisodeRunResult:
        """Follow/circle regression lane via the existing spatial/follow harness."""

        text = episode.instruction
        budget = self._episode_max_steps(episode)
        understood = parse_follow_intent(text) or parse_spatial_intent(text) is not None
        result = self.harness.run(text, max_steps=budget)
        trace = _trace_from_harness(result, episode)
        if not understood or result.reason == "directive_not_understood":
            if trace:
                trace[-1]["refusal"] = True
                trace[-1]["reply"] = "I couldn't form a safe, grounded plan yet."
            score = score_episode(
                trace,
                episode.goal,
                shortest_path_m=max(episode.shortest_path_m, 1e-3),
                max_time_s=budget * self.world.control_dt_s,
                system_arrival=system_arrival_claim(result.status, result.reason),
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
                arrival_rule=self.arrival_rule,
                frozen_rule_success=bool(score.success),
                arrival_branch="frozen_hold" if score.success else "none",
                max_steps=budget,
            )

        if result.collision_count > 0:
            trace[-1]["collision"] = True
            trace[-1]["control_error"] = True
        claimed_arrival = system_arrival_claim(result.status, result.reason)
        if trace:
            trace[-1]["system_arrival"] = claimed_arrival
        # Score real poses only — never teleport into the goal disc.
        score = score_episode(
            trace,
            episode.goal,
            shortest_path_m=max(episode.shortest_path_m, 1e-3),
            max_time_s=budget * self.world.control_dt_s,
            arrival_hold_s=0.0,
            system_arrival=claimed_arrival,
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
            # arrival_hold_s is 0.0 for the spatial families, so the derived
            # rule is a no-op here by construction (see rescore.SPATIAL_FAMILIES).
            arrival_rule=self.arrival_rule,
            frozen_rule_success=bool(score.success),
            arrival_branch="frozen_hold" if score.success else "none",
            max_steps=budget,
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


def aggregate_results(
    results: list[EpisodeRunResult],
    *,
    episode_set_version: str | None = None,
    scene: str | None = None,
) -> dict[str, Any]:
    """Family × tier dashboard: SR, SPL, DTG, failure histogram.

    ``sr`` is the headline under whichever arrival rule the run used;
    ``sr_frozen_rule`` is always what the v1 hold rule would have said about the
    same traces, so correction (c) is isolated inside every single report.
    """

    cells: dict[str, dict[str, Any]] = {}
    failure_hist: dict[str, int] = {item.value: 0 for item in FailureClass}
    authority_hist: dict[str, int] = {item.value: 0 for item in AuthorityCategory}
    collisions = 0
    for result in results:
        authority_hist[result.authority_category] += 1
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
    rules = sorted({r.arrival_rule for r in results}) or [DEFAULT_ARRIVAL_RULE]
    mean_dtg = sum(
        0.0 if not math.isfinite(r.score.distance_to_goal_m) else r.score.distance_to_goal_m
        for r in results
    ) / n_all
    aggregate: dict[str, Any] = {
        "runner_version": RUNNER_VERSION,
        "n": len(results),
        "sr": sum(1 for r in results if r.score.success) / n_all,
        "spl": sum(r.score.spl for r in results) / n_all,
        "mean_dtg_m": mean_dtg,
        "collision_total": collisions,
        "failure_histogram": failure_hist,
        "authority_histogram": authority_hist,
        "arrival_epsilon_m": ARRIVAL_BOUNDARY_EPSILON_M,
        # Correction (c), isolated inside the run itself.
        "arrival_rule": rules[0] if len(rules) == 1 else "|".join(rules),
        "sr_frozen_rule": sum(1 for r in results if r.frozen_rule_success) / n_all,
        "arrival_branch_histogram": _histogram(r.arrival_branch for r in results),
        "by_family_tier": dashboard,
        "does_not_prove": list(DOES_NOT_PROVE),
    }
    if episode_set_version is not None:
        aggregate["episode_set_version"] = episode_set_version
        aggregate["episode_set_provenance"] = episode_set_spec(
            episode_set_version
        ).provenance
    if scene is not None:
        aggregate["scene"] = scene
    return aggregate


def _histogram(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
