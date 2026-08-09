"""System-authored PlanSketch builders for unambiguous final commands (K6/B1).

Trusted code only — never model-authored velocity or priority. Sketches compile
through ``compile_plan_sketch`` / ``materialize_planner_output`` into PlanIR.
"""

from __future__ import annotations

from parcel_robot.brain.contracts import FrozenDict
from parcel_robot.brain.plan_sketch import (
    PLAN_SKETCH_SCHEMA_VERSION,
    NavigationGrounding,
    PlanSketch,
    PlanSketchGoal,
    PlanSketchStep,
)
from parcel_robot.models import SpatialIntent
from parcel_robot.navigation.goals import (
    navigation_directive_from_text,
    owner_referent_from_directive,
    semantic_goal_from_directive,
)

#: Posture applied by the settle half of a "sit next to X" plan. Named here,
#: not inferred from the transcript: the pose catalog is the authority on what
#: the robot can physically do, and ``sit`` is the only settle posture the
#: grammar currently produces.
SETTLE_POSE_NAME = "sit"

#: Pose name → the verb phrase used when acknowledging a settle plan. Only
#: postures that exist in ``configs/skills/poses`` appear here; anything else
#: acknowledges with the neutral "settle" rather than describing a posture the
#: robot may not have. Prose only — nothing reads this to choose a pose.
SETTLE_POSE_PHRASES: dict[str, str] = {
    "sit": "sit down",
    "crouch": "crouch down",
    "lie_down": "lie down",
    "stand": "stand there",
}


def sketch_follow(*, behind: bool = False, distance_m: float = 1.9) -> PlanSketch:
    """Plain "follow me" vs explicit "follow behind me" are distinct relations.

    Arbiter ruling 2026-08-06: collapsing both onto ``behind`` made plain
    follow inherit the behind-formation ``owner_heading_available``
    precondition, so a stationary owner got a refusal for a request the
    controller has always been able to serve in direct mode.
    """

    relation = "behind" if behind else "follow"
    return PlanSketch(
        schema_version=PLAN_SKETCH_SCHEMA_VERSION,
        goal=PlanSketchGoal(relation=relation, kind="owner", query="owner"),
        steps=(
            PlanSketchStep(
                skill="FollowFormation",
                arguments=FrozenDict(
                    {
                        "relation": relation,
                        "distance_m": float(distance_m),
                    }
                ),
            ),
        ),
    )


def sketch_hold() -> PlanSketch:
    return PlanSketch(
        schema_version=PLAN_SKETCH_SCHEMA_VERSION,
        goal=PlanSketchGoal(relation="hold", kind="current_pose", query=""),
        steps=(
            PlanSketchStep(skill="Hold", arguments=FrozenDict({})),
        ),
    )


def sketch_come(*, distance_m: float = 1.9) -> PlanSketch:
    """Owner summons → approach (closed intent ``come``).

    "Come here" is an approach, not a formation: the canonical case is a
    *stationary* owner calling the dog, which is exactly when no owner motion
    heading exists. Compiling it to ``behind`` therefore refused the most
    common form of the command with ``owner_heading_unavailable`` — the same
    defect as plain "follow me" (arbitration OB-7).
    """

    return PlanSketch(
        schema_version=PLAN_SKETCH_SCHEMA_VERSION,
        goal=PlanSketchGoal(relation="follow", kind="owner", query="owner"),
        steps=(
            PlanSketchStep(
                skill="FollowFormation",
                arguments=FrozenDict(
                    {
                        "relation": "follow",
                        "distance_m": float(distance_m),
                    }
                ),
            ),
        ),
    )


def sketch_spatial(intent: SpatialIntent) -> PlanSketch:
    if intent.behavior == "orbit_owner":
        return PlanSketch(
            schema_version=PLAN_SKETCH_SCHEMA_VERSION,
            goal=PlanSketchGoal(relation="orbit", kind="owner", query="owner"),
            steps=(
                PlanSketchStep(
                    skill="OrbitOwner",
                    arguments=FrozenDict(
                        {
                            "direction": intent.direction,
                            "size": intent.size or "normal",
                            "revolutions": float(intent.revolutions or 1.0),
                        }
                    ),
                ),
            ),
        )
    if intent.behavior != "move_steps":
        raise ValueError(f"unsupported spatial behavior for PlanSketch: {intent.behavior}")
    return PlanSketch(
        schema_version=PLAN_SKETCH_SCHEMA_VERSION,
        goal=PlanSketchGoal(relation="relative", kind="current_pose", query=""),
        steps=(
            PlanSketchStep(
                skill="MoveRelative",
                arguments=FrozenDict(
                    {
                        "direction": intent.direction,
                        "steps": int(intent.steps or 1),
                    }
                ),
            ),
        ),
    )


def sketch_settle_next_to(
    directive: str,
    *,
    target: str,
    pose: str = SETTLE_POSE_NAME,
) -> PlanSketch:
    """"Sit next to X" — navigate **and then settle** (backlog N13).

    Two steps, because the command names two outcomes. Before this, the plan
    was a single ``NavigateTo`` and the "sit" verb survived only inside the
    directive string, where the navigator re-read it as the ``next_to``
    *placement relation*; ``terminal_behavior="hold"`` went to mission
    metadata with no consumer and ``runtime._last_posture`` stayed ``unknown``
    for the whole run. The posture gate of ``evaluate_sit_next_to`` therefore
    could not pass by construction.

    The plan goal is ``hold``/``current_pose`` because that is the shape the
    validator already reserves for a settle: ``_validate_goal_completion``
    admits a terminal ``Pose`` step proving ``skill_completed`` under a
    ``hold`` goal, and rejects it under any spatial goal relation. The
    *placement* half remains the ``NavigateTo`` step's own ``near``/``next_to``
    verification — this adds no second arrival authority.
    """

    clean = " ".join(str(directive).strip().split())
    label = " ".join(str(target).strip().split())
    if not clean:
        raise ValueError("settle directive must be non-empty")
    if not label:
        raise ValueError("settle directive must name a placement target")
    return PlanSketch(
        schema_version=PLAN_SKETCH_SCHEMA_VERSION,
        goal=PlanSketchGoal(relation="hold", kind="current_pose", query=""),
        steps=(
            PlanSketchStep(
                skill="NavigateTo",
                arguments=FrozenDict({"directive": clean}),
                navigation=NavigationGrounding(relation="near", target=label),
            ),
            PlanSketchStep(
                skill="Pose",
                arguments=FrozenDict({"name": str(pose)}),
            ),
        ),
    )


def sketch_navigate(directive: str) -> PlanSketch:
    clean = " ".join(str(directive).strip().split())
    if not clean:
        raise ValueError("navigation directive must be non-empty")
    normalized = navigation_directive_from_text(clean.lower()) or clean
    # N12 — the owner is never a semantic-map query. "Go to the owner" /
    # "go to me" resolve to the SAME approach lane "come here" uses, rather
    # than compiling to NavigateTo and asking the semantic map for a landmark
    # labelled "owner" (which does not and cannot exist). One authority for
    # "the owner": two phrasings that resolved differently is the D5 class.
    if owner_referent_from_directive(normalized) is not None:
        return sketch_come()
    goal = semantic_goal_from_directive(normalized)
    # N13 — a settle directive names a placement *and* a posture.
    if goal.terminal_relation == "next_to":
        return sketch_settle_next_to(clean, target=str(goal.query))
    # PlanSketch / NavigationGrounding only admit inside|near; map other
    # terminal relations to the nearest grounding predicate.
    if goal.terminal_relation == "inside":
        relation = "inside"
        kind = "semantic_region"
    else:
        relation = "near"
        kind = "semantic_object"
    target = str(goal.query)
    return PlanSketch(
        schema_version=PLAN_SKETCH_SCHEMA_VERSION,
        goal=PlanSketchGoal(relation=relation, kind=kind, query=target),
        steps=(
            PlanSketchStep(
                skill="NavigateTo",
                arguments=FrozenDict({"directive": clean}),
                navigation=NavigationGrounding(relation=relation, target=target),
            ),
        ),
    )


def try_local_physical_sketch(
    *,
    normalized_text: str,
    spatial_intent: SpatialIntent | None = None,
    nav_directive: str | None = None,
    follow_behind: bool = False,
) -> PlanSketch | None:
    """Build a local sketch for reviewed grammars, else None (caller falls back)."""

    text = normalized_text
    if text in {"follow", "follow me", "come with me", "heel"}:
        return sketch_follow(behind=False)
    if text in {
        "follow behind me",
        "walk behind me",
        "stay behind me",
        "heel behind me",
    } or follow_behind:
        return sketch_follow(behind=True)
    if text in {"stay", "wait", "wait here", "hold position"}:
        return sketch_hold()
    if spatial_intent is not None:
        return sketch_spatial(spatial_intent)
    if nav_directive is not None:
        return sketch_navigate(nav_directive)
    return None


__all__ = [
    "SETTLE_POSE_NAME",
    "SETTLE_POSE_PHRASES",
    "sketch_come",
    "sketch_follow",
    "sketch_hold",
    "sketch_navigate",
    "sketch_settle_next_to",
    "sketch_spatial",
    "try_local_physical_sketch",
]
