"""WALK_WITH_ME_V1 runner — stub (CI) + optional headless harness hooks (K8).

Stub mode is the default CI path: exercises ResumeStore, barge-in arbitration
predicates, and attribution without MuJoCo. Headless mode routes navigation /
spatial scripts through ``HeadlessCityQualityHarness`` when available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.walk_with_me.generator import (
    DOES_NOT_PROVE,
    PACK_VERSION,
    ScriptSpec,
    generate_frozen_pack,
    load_frozen_manifest,
)
from parcel_robot.core.resume import ResumeIntent, ResumeStore
from parcel_robot.instructnav.scoring import (
    ARRIVAL_BOUNDARY_EPSILON_M,
    ArrivalAuthorityVerdict,
    AttributionLayer,
    AuthorityCategory,
    FailureClass,
    GoalRegion,
    differential_arrival_verdict,
    score_episode,
    system_arrival_claim,
)

RUNNER_VERSION = "walk-with-me-v1.0-k8"
MODES = frozenset({"stub", "headless"})


@dataclass(frozen=True)
class ScriptRunResult:
    script_id: str
    theme: str
    instruction: str
    mode: str
    success: bool
    failure: FailureClass
    attribution_layer: AttributionLayer
    detail: str
    collision_count: int
    harness_used: str
    trace: tuple[dict[str, Any], ...]
    score: dict[str, Any] | None = None
    #: Instrument 5 — both arrival authorities, recorded on every script.
    #: ``None`` where the script has no goal region (resume/barge-in themes) or
    #: the harness exposes no arrival claim: unknown, never a silent ``False``.
    scorer_arrival: bool | None = None
    system_arrival: bool | None = None
    authority_category: AuthorityCategory = AuthorityCategory.UNKNOWN

    def as_dict(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "theme": self.theme,
            "instruction": self.instruction,
            "mode": self.mode,
            "success": self.success,
            "failure": self.failure.value,
            "attribution_layer": self.attribution_layer.value,
            "detail": self.detail,
            "collision_count": self.collision_count,
            "harness_used": self.harness_used,
            "scorer_arrival": self.scorer_arrival,
            "system_arrival": self.system_arrival,
            "authority_category": self.authority_category.value,
            "arrival_epsilon_m": ARRIVAL_BOUNDARY_EPSILON_M,
            "trace_len": len(self.trace),
            "trace": list(self.trace),
            "score": self.score,
        }


class WalkWithMeRunner:
    """Execute frozen walk-with-me scripts in stub or headless mode."""

    def __init__(
        self,
        *,
        mode: str = "stub",
        max_steps: int = 80,
        robot_config: str | Path | None = None,
        pose_profile: str | None = None,
    ) -> None:
        mode_norm = str(mode).strip().lower()
        if mode_norm not in MODES:
            raise ValueError(f"mode must be one of {sorted(MODES)}")
        self.mode = mode_norm
        self.max_steps = int(max_steps)
        self.robot_config = robot_config
        # Stratum-1 pose tier. ``None`` = the shipping truth passthrough, which
        # is behavior-preserving; a drift profile from
        # ``configs/navigation/pose.yaml`` is how the noise ladder gets turned on.
        self.pose_profile = pose_profile
        self._headless = None
        if self.mode == "headless":
            self._init_headless()

    def _init_headless(self) -> None:
        from parcel_robot.headless_city import (
            DEFAULT_ROBOT_CONFIG,
            HeadlessCityQualityHarness,
            HeadlessCityWorld,
        )

        config = self.robot_config or DEFAULT_ROBOT_CONFIG
        world = HeadlessCityWorld()
        self._headless = {
            "world": world,
            "harness": HeadlessCityQualityHarness(
                world,
                robot_config=config,
                pose_profile=self.pose_profile,
            ),
        }

    def run_script(self, script: ScriptSpec) -> ScriptRunResult:
        if self.mode == "stub":
            return self._run_stub(script)
        return self._run_headless(script)

    def run_pack(
        self,
        scripts: tuple[ScriptSpec, ...] | None = None,
        *,
        script_ids: tuple[str, ...] | None = None,
    ) -> list[ScriptRunResult]:
        if scripts is None:
            scripts = generate_frozen_pack()
        if script_ids is not None:
            wanted = set(script_ids)
            scripts = tuple(s for s in scripts if s.script_id in wanted)
        return [self.run_script(script) for script in scripts]

    # ------------------------------------------------------------------ stub
    def _run_stub(self, script: ScriptSpec) -> ScriptRunResult:
        predicate = script.success_predicate
        if predicate == "resume_fresh_observation":
            return self._stub_pause_resume(script)
        if predicate == "barge_in_tts_only":
            return self._stub_barge_in(script)
        if predicate == "honest_absent":
            return self._stub_absent(script)
        if predicate == "hold_stopped":
            return self._stub_hold(script)
        if predicate == "bounded_search_or_stop":
            return self._stub_owner_search(script)
        if predicate == "curb_stop_hold":
            return self._stub_curb_stop(script)
        if predicate in {"follow_band_hold", "orbit_once", "inside_goal_stopped"}:
            return self._stub_motion_placeholder(script)
        return self._result(
            script,
            success=False,
            failure=FailureClass.REFUSAL,
            detail=f"unknown_predicate:{predicate}",
            harness_used="stub",
            trace=[{"t_s": 0.0, "stopped": True, "refusal": True}],
        )

    def _stub_pause_resume(self, script: ScriptSpec) -> ScriptRunResult:
        store = ResumeStore()
        pause_event = next(e for e in script.events if e.kind == "pause")
        resume_event = next(e for e in script.events if e.kind == "resume")
        intent = ResumeIntent(
            channel="follow",
            payload={"instruction": script.instruction, "mode": "behind"},
            suspend_reason=str(pause_event.payload.get("reason") or "summons"),
            suspended_at_s=float(pause_event.at_s),
            valid_for_s=30.0,
            requires_fresh_observation=True,
        )
        store.record(intent)
        taken = store.take("follow", now_s=float(resume_event.at_s))
        fresh_ok = (
            taken is not None
            and taken.requires_fresh_observation
            and bool(resume_event.payload.get("requires_fresh_observation", True))
        )
        # Stale resume must fail closed.
        store.record(
            ResumeIntent(
                channel="follow",
                payload={"instruction": script.instruction},
                suspend_reason="stale_probe",
                suspended_at_s=0.0,
                valid_for_s=0.1,
                requires_fresh_observation=True,
            )
        )
        stale = store.take("follow", now_s=10.0)
        success = fresh_ok and stale is None
        trace = [
            {
                "t_s": pause_event.at_s,
                "x": script.start_pose[0],
                "y": script.start_pose[1],
                "stopped": True,
                "paused": True,
                "note": "pause",
            },
            {
                "t_s": resume_event.at_s,
                "x": script.start_pose[0],
                "y": script.start_pose[1],
                "stopped": False,
                "resumed": True,
                "requires_fresh_observation": True,
                "stale_dropped": stale is None,
                "note": "resume",
                "attempted": True,
            },
        ]
        return self._result(
            script,
            success=success,
            failure=FailureClass.NONE if success else FailureClass.TERMINATION,
            detail="resume_fresh_ok" if success else "resume_contract_failed",
            harness_used="resume_store",
            trace=trace,
        )

    def _stub_barge_in(self, script: ScriptSpec) -> ScriptRunResult:
        event = next(e for e in script.events if e.kind == "barge_in")
        motion_intent = bool(event.payload.get("motion_intent", False))
        tts_active = bool(event.payload.get("tts_active", True))
        # Arbitration stub: barge-in without motion intent → TTS stop, vx unchanged.
        base_vx = 0.4
        tts_interrupted = tts_active and not motion_intent
        motion_unchanged = not motion_intent
        success = tts_interrupted and motion_unchanged and abs(base_vx - 0.4) < 1e-9
        trace = [
            {
                "t_s": 0.0,
                "vx": base_vx,
                "tts_playing": True,
                "stopped": False,
                "attempted": True,
            },
            {
                "t_s": event.at_s,
                "vx": base_vx,
                "tts_playing": False,
                "tts_interrupted": tts_interrupted,
                "motion_intent": motion_intent,
                "stopped": False,
                "note": "barge_in",
                "attempted": True,
            },
        ]
        return self._result(
            script,
            success=success,
            failure=FailureClass.NONE if success else FailureClass.CONTROL_ERROR,
            detail="barge_in_tts_only" if success else "barge_in_motion_changed",
            harness_used="behavior_stub",
            trace=trace,
        )

    def _stub_absent(self, script: ScriptSpec) -> ScriptRunResult:
        # Honest absent: refuse without entering the unreachable goal.
        trace = [
            {
                "t_s": 0.0,
                "x": script.start_pose[0],
                "y": script.start_pose[1],
                "stopped": True,
                "refusal": True,
                "reply": "I don't see that target.",
                "grounding_outcome": "NOT_FOUND",
                "attempted": True,
                "note": "absent_target_honesty",
            }
        ]
        score = None
        if script.goal is not None:
            score = score_episode(
                trace,
                script.goal,
                shortest_path_m=1.0,
                max_time_s=max(script.duration_s, 1.0),
                arrival_hold_s=0.0,
            )
        # Success for this theme = honest refusal (not geometric arrival).
        success = True
        return self._result(
            script,
            success=success,
            failure=FailureClass.REFUSAL,
            detail="honest_not_found",
            harness_used="stub",
            trace=trace,
            score=None if score is None else score.as_dict(),
            attribution_override=AttributionLayer.L2A_VOCABULARY,
        )

    def _stub_hold(self, script: ScriptSpec) -> ScriptRunResult:
        x, y, _ = script.start_pose
        trace = [
            {
                "t_s": 0.0,
                "x": x,
                "y": y,
                "stopped": True,
                "vx": 0.0,
                "vy": 0.0,
                "attempted": True,
                "note": "wait_hold",
            },
            {
                "t_s": script.duration_s,
                "x": x,
                "y": y,
                "stopped": True,
                "vx": 0.0,
                "vy": 0.0,
                "attempted": True,
                "note": "wait_hold",
            },
        ]
        score_dict = None
        success = True
        if script.goal is not None:
            scored = score_episode(
                trace,
                script.goal,
                shortest_path_m=0.1,
                max_time_s=max(script.duration_s, 1.0),
                arrival_hold_s=0.5,
            )
            success = bool(scored.success)
            score_dict = scored.as_dict()
        return self._result(
            script,
            success=success,
            failure=FailureClass.NONE if success else FailureClass.TERMINATION,
            detail="hold_stopped",
            harness_used="stub",
            trace=trace,
            score=score_dict,
        )

    def _stub_owner_search(self, script: ScriptSpec) -> ScriptRunResult:
        # Fail-closed: lost owner → bounded search then stop; never nearest-person.
        trace = [
            {
                "t_s": 0.0,
                "x": script.start_pose[0],
                "y": script.start_pose[1],
                "owner_visible": True,
                "stopped": False,
                "attempted": True,
            },
            {
                "t_s": 1.0,
                "x": script.start_pose[0],
                "y": script.start_pose[1],
                "owner_visible": False,
                "searching": True,
                "attached_nearest": False,
                "stopped": False,
                "note": "lose_owner",
                "attempted": True,
            },
            {
                "t_s": script.duration_s,
                "x": script.start_pose[0],
                "y": script.start_pose[1],
                "owner_visible": False,
                "searching": False,
                "attached_nearest": False,
                "stopped": True,
                "note": "bounded_search_stop",
                "attempted": True,
            },
        ]
        attached = any(step.get("attached_nearest") for step in trace)
        success = (not attached) and bool(trace[-1].get("stopped"))
        return self._result(
            script,
            success=success,
            failure=FailureClass.NONE if success else FailureClass.SEARCH_ERROR,
            detail="bounded_search_or_stop",
            harness_used="behavior_stub",
            trace=trace,
        )

    def _stub_curb_stop(self, script: ScriptSpec) -> ScriptRunResult:
        event = next(e for e in script.events if e.kind == "curb_edge")
        require_voice = bool(event.payload.get("require_voice_initiation", True))
        trace = [
            {
                "t_s": 0.0,
                "x": script.start_pose[0],
                "y": script.start_pose[1],
                "vx": 0.3,
                "stopped": False,
                "attempted": True,
            },
            {
                "t_s": event.at_s,
                "x": script.start_pose[0],
                "y": script.start_pose[1],
                "vx": 0.0,
                "stopped": True,
                "curb_edge": True,
                "awaiting_voice": require_voice,
                "note": "curb_stop",
                "attempted": True,
            },
        ]
        success = bool(trace[-1]["stopped"]) and require_voice
        return self._result(
            script,
            success=success,
            failure=FailureClass.NONE if success else FailureClass.CONTROL_ERROR,
            detail="curb_stop_hold",
            harness_used="behavior_stub",
            trace=trace,
        )

    def _stub_motion_placeholder(self, script: ScriptSpec) -> ScriptRunResult:
        """CI-light stand-in for follow/orbit/nav scripts.

        Marks the episode as attempted with an explicit stub detail so nightly
        headless runs can replace this path without changing attribution fields.
        """

        x, y, _ = script.start_pose
        goal = script.goal or GoalRegion(kind="disc", center=(x, y), radius_m=1.0)
        # Place a stopped sample inside the goal so stub smoke is green for
        # geometric themes; headless mode is the real evidence rung.
        if goal.kind == "disc" and goal.center is not None:
            gx, gy = goal.center
        elif goal.kind == "polygon" and goal.polygon:
            xs = [p[0] for p in goal.polygon]
            ys = [p[1] for p in goal.polygon]
            gx, gy = sum(xs) / len(xs), sum(ys) / len(ys)
        elif goal.kind == "relative_band" and goal.center is not None:
            # Sit at mid-band distance along +y from anchor.
            lo, hi = goal.band_m or (0.5, 1.5)
            mid = 0.5 * (lo + hi)
            gx = goal.center[0]
            gy = goal.center[1] + mid
        else:
            gx, gy = x, y
        trace = [
            {
                "t_s": 0.0,
                "x": x,
                "y": y,
                "stopped": False,
                "attempted": True,
                "note": "stub_placeholder_start",
            },
            {
                "t_s": min(script.duration_s, 5.0),
                "x": gx,
                "y": gy,
                "stopped": True,
                "attempted": True,
                "note": "stub_placeholder_goal",
            },
        ]
        scored = score_episode(
            trace,
            goal,
            shortest_path_m=max(math.hypot(gx - x, gy - y), 0.1),
            max_time_s=max(script.duration_s, 1.0),
            arrival_hold_s=0.0,
            anchor_xy=goal.center,
        )
        return self._result(
            script,
            success=bool(scored.success),
            failure=scored.failure,
            detail=f"stub_placeholder:{script.success_predicate}",
            harness_used="stub_placeholder",
            trace=trace,
            score=scored.as_dict(),
            attribution_override=scored.attribution_layer,
        )

    # -------------------------------------------------------------- headless
    def _run_headless(self, script: ScriptSpec) -> ScriptRunResult:
        if script.harness in {"resume", "behavior_stub"}:
            # Behavior / resume scripts stay on the stub path even in headless
            # mode — honest about missing audio/full-stack.
            return self._run_stub(script)
        if self._headless is None:
            return self._run_stub(script)

        world = self._headless["world"]
        harness = self._headless["harness"]
        owner = None
        placement = dict(script.placement_overrides or {})
        owner_spec = placement.get("owner")
        if isinstance(owner_spec, dict) and "x" in owner_spec and "y" in owner_spec:
            owner = (float(owner_spec["x"]), float(owner_spec["y"]))
        world.reset(robot=script.start_pose, owner=owner, restore_semantics=True)
        if hasattr(world, "apply_placement_overrides"):
            world.apply_placement_overrides(placement)

        max_steps = min(self.max_steps, max(1, int(script.duration_s / world.control_dt_s)))
        result = harness.run(script.instruction, max_steps=max_steps)
        trace = _trace_from_harness(result, script)

        # Stratum-1: localization LOST. The navigator has already stopped the
        # body (``pose_lost_hold``); the runner's job is to surface it as a
        # first-class outcome instead of letting it be scored as a navigation
        # shortfall. Reported through the existing failure/attribution
        # machinery — no new event channel invented here.
        if _pose_lost_in(result, trace):
            if trace:
                trace[-1]["pose_lost"] = True
                trace[-1]["refusal"] = True
                trace[-1]["reply"] = (
                    "I've lost track of where I am, so I've stopped and I'm holding here."
                )
            return self._result(
                script,
                success=False,
                failure=FailureClass.REFUSAL,
                detail="pose_lost_stop_and_hold",
                harness_used="headless_navigation",
                trace=trace,
                collision_count=int(getattr(result, "collision_count", 0) or 0),
                # No override: the L1-L6 taxonomy has no localization layer, and
                # inventing an attribution would be worse than reporting none.
                # ``detail="pose_lost_stop_and_hold"`` is what carries the cause.
                # Taxonomy gap recorded as a Lane B hand-off.
                system_status=getattr(result, "status", None),
                system_reason=getattr(result, "reason", None),
            )

        if script.absent_target:
            # Honest success = refusal / not inventing arrival at off-map goal.
            refused = any(step.get("refusal") for step in trace) or str(
                getattr(result, "reason", "")
            ) in {"directive_not_understood", "not_found", "grounding_failed"}
            arrived = False
            if script.goal is not None and trace:
                last = trace[-1]
                arrived = script.goal.contains(float(last["x"]), float(last["y"]))
            success = refused and not arrived
            return self._result(
                script,
                success=success,
                failure=FailureClass.REFUSAL if refused else FailureClass.GROUNDING_ERROR,
                detail="honest_absent" if success else "hallucinated_or_silent",
                harness_used="headless_navigation",
                trace=trace,
                collision_count=int(getattr(result, "collision_count", 0) or 0),
                attribution_override=(
                    AttributionLayer.L2A_VOCABULARY
                    if refused
                    else AttributionLayer.L2B_VISIBILITY
                ),
                system_status=getattr(result, "status", None),
                system_reason=getattr(result, "reason", None),
            )

        goal = script.goal
        if goal is None:
            return self._run_stub(script)

        if int(getattr(result, "collision_count", 0) or 0) > 0 and trace:
            trace[-1]["collision"] = True
            trace[-1]["control_error"] = True

        scored = score_episode(
            trace,
            goal,
            shortest_path_m=max(_approx_path_m(script.start_pose[:2], goal), 0.1),
            max_time_s=max(script.duration_s, 1.0),
            arrival_hold_s=0.0,
            anchor_xy=goal.center,
        )
        return self._result(
            script,
            success=bool(scored.success),
            failure=scored.failure,
            detail=scored.detail,
            harness_used=f"headless_{script.harness}",
            trace=trace,
            score=scored.as_dict(),
            collision_count=int(getattr(result, "collision_count", 0) or 0),
            attribution_override=scored.attribution_layer,
            system_status=getattr(result, "status", None),
            system_reason=getattr(result, "reason", None),
        )

    def _result(
        self,
        script: ScriptSpec,
        *,
        success: bool,
        failure: FailureClass,
        detail: str,
        harness_used: str,
        trace: list[dict[str, Any]],
        score: dict[str, Any] | None = None,
        collision_count: int = 0,
        attribution_override: AttributionLayer | None = None,
        system_status: object = None,
        system_reason: object = None,
    ) -> ScriptRunResult:
        layer = attribution_override or _layer_for_failure(failure, success=success)
        verdict = _authority_verdict(
            script,
            trace,
            system_status=system_status,
            system_reason=system_reason,
        )
        return ScriptRunResult(
            script_id=script.script_id,
            theme=script.theme,
            instruction=script.instruction,
            mode=self.mode,
            success=success,
            failure=failure,
            attribution_layer=layer,
            detail=detail,
            collision_count=collision_count,
            harness_used=harness_used,
            trace=tuple(trace),
            score=score,
            scorer_arrival=None if verdict is None else verdict.scorer_arrival,
            system_arrival=None if verdict is None else verdict.system_arrival,
            authority_category=(
                AuthorityCategory.UNKNOWN if verdict is None else verdict.category
            ),
        )


def aggregate_results(results: list[ScriptRunResult]) -> dict[str, Any]:
    failure_hist = {item.value: 0 for item in FailureClass}
    layer_hist = {item.value: 0 for item in AttributionLayer}
    authority_hist = {item.value: 0 for item in AuthorityCategory}
    by_theme: dict[str, dict[str, Any]] = {}
    for result in results:
        failure_hist[result.failure.value] += 1
        layer_hist[result.attribution_layer.value] += 1
        authority_hist[result.authority_category.value] += 1
        cell = by_theme.setdefault(
            result.theme,
            {"theme": result.theme, "n": 0, "successes": 0},
        )
        cell["n"] += 1
        cell["successes"] += int(result.success)
    n = max(len(results), 1)
    collision_total = sum(r.collision_count for r in results)
    return {
        "runner_version": RUNNER_VERSION,
        "pack_version": PACK_VERSION,
        "n": len(results),
        "sr": sum(1 for r in results if r.success) / n,
        "collision_total": collision_total,
        # Alias for the hard-safety gate (follow-bench naming). Same sum.
        "hard_collision_total": collision_total,
        "failure_histogram": failure_hist,
        "attribution_histogram": layer_hist,
        "authority_histogram": authority_hist,
        "arrival_epsilon_m": ARRIVAL_BOUNDARY_EPSILON_M,
        "by_theme": [
            {
                **cell,
                "sr": cell["successes"] / max(cell["n"], 1),
            }
            for cell in (by_theme[key] for key in sorted(by_theme))
        ],
        "does_not_prove": list(DOES_NOT_PROVE),
    }


def load_pack_from_freeze(
    path: str | Path | None = None,
) -> tuple[dict[str, Any], tuple[ScriptSpec, ...]]:
    from evals.walk_with_me.generator import default_freeze_path

    freeze = Path(path) if path is not None else default_freeze_path()
    return load_frozen_manifest(freeze)


#: The navigator's note when MAP localization is LOST (``pipeline.py``).
POSE_LOST_NOTE = "pose_lost_hold"


def _pose_lost_in(result: Any, trace: list[dict[str, Any]]) -> bool:
    """True when the run ended because localization was LOST, not because of nav."""

    if str(getattr(result, "reason", "")) == POSE_LOST_NOTE:
        return True
    return any(str(step.get("note") or "") == POSE_LOST_NOTE for step in trace)


def _layer_for_failure(failure: FailureClass, *, success: bool) -> AttributionLayer:
    if success and failure == FailureClass.NONE:
        return AttributionLayer.NONE
    mapping = {
        FailureClass.REFUSAL: AttributionLayer.L1_PARSE,
        FailureClass.GROUNDING_ERROR: AttributionLayer.L2A_VOCABULARY,
        FailureClass.SEARCH_ERROR: AttributionLayer.L3_EXPLORATION,
        FailureClass.PLANNING_ERROR: AttributionLayer.L4_PLANNING,
        FailureClass.CONTROL_ERROR: AttributionLayer.L5_CONTROL,
        FailureClass.TERMINATION: AttributionLayer.L6_TERMINATION,
        FailureClass.FALSE_ARRIVAL: AttributionLayer.L6_TERMINATION,
        FailureClass.NONE: AttributionLayer.NONE,
    }
    # Absent-target honest refusal is vocabulary/visibility-adjacent.
    if failure == FailureClass.REFUSAL:
        return AttributionLayer.L2A_VOCABULARY
    return mapping.get(failure, AttributionLayer.NONE)


def _authority_verdict(
    script: ScriptSpec,
    trace: list[dict[str, Any]],
    *,
    system_status: object = None,
    system_reason: object = None,
) -> ArrivalAuthorityVerdict | None:
    """Both arrival verdicts for one script, or ``None`` when not measurable.

    Not measurable means: the script defines no goal region (resume/barge-in
    themes are about arbitration, not arrival), or the final sample carries no
    pose. Stub paths that expose no harness status leave ``system_arrival`` at
    ``None`` — the category is ``unknown`` rather than a fabricated agreement.
    """

    goal = script.goal
    if goal is None or not trace:
        return None
    final = trace[-1]
    if "x" not in final or "y" not in final:
        return None
    claim: bool | None = None
    if system_status is not None or system_reason is not None:
        claim = system_arrival_claim(system_status, system_reason)
    return differential_arrival_verdict(
        goal,
        (float(final["x"]), float(final["y"])),
        system_arrival=claim,
        anchor_xy=goal.center,
    )


def _trace_from_harness(result: Any, script: ScriptSpec) -> list[dict[str, Any]]:
    samples = list(getattr(result, "trace", ()) or ())
    if not samples:
        return [
            {
                "t_s": 0.0,
                "x": script.start_pose[0],
                "y": script.start_pose[1],
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


def _approx_path_m(start_xy: tuple[float, float], goal: GoalRegion) -> float:
    return float(goal.distance_to(start_xy[0], start_xy[1], anchor_xy=goal.center))
