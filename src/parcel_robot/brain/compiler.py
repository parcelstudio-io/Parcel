"""Deterministically compile model semantics into executable PlanIR contracts."""

from __future__ import annotations

from dataclasses import replace

from .contracts import IntentFrame, ObservationSnapshot, PlanIR, PlanStep, SuccessCondition
from .plan_sketch import PlanSketch
from .runtime_adapter import bind_plan_context
from .validator import SkillContractRegistry

_CANONICAL_SUCCESS = {
    "FollowFormation": ("behind", "owner"),
    "OrbitOwner": ("orbit_complete", "owner"),
    "MoveRelative": ("distance_travelled", None),
    "SearchOwner": ("owner_reacquired", "owner"),
    "Hold": ("motion_stopped", None),
    "Pose": ("skill_completed", None),
    "Gesture": ("skill_completed", None),
    "Vocalize": ("utterance_sent", None),
    "AskClarification": ("utterance_sent", None),
    "ReturnToSafePose": ("safe_pose", None),
}


def compile_plan_contracts(
    plan: PlanIR,
    registry: SkillContractRegistry,
) -> PlanIR:
    """Compile system-owned step boilerplate without repairing semantics.

    Skill order and arguments remain model-owned and are still validated.  The
    compiler owns identifiers, declared resources/preconditions, success
    verification policy, retry/time limits, and interrupt defaults so an LLM
    omission cannot weaken admission and a verbose model need not reason about
    controller bookkeeping.
    """

    if not isinstance(plan, PlanIR):
        raise TypeError("contract compilation requires a PlanIR")
    if not isinstance(registry, SkillContractRegistry):
        raise TypeError("contract compilation requires a SkillContractRegistry")

    steps: list[PlanStep] = []
    for index, proposed in enumerate(plan.steps, start=1):
        contract = registry.get(proposed.skill)
        preconditions = set(contract.required_preconditions)
        if (
            proposed.skill == "MoveRelative"
            and proposed.arguments.get("direction") == "away_from_owner"
        ):
            preconditions.add("owner_visible")
        if proposed.skill == "NavigateTo":
            success = SuccessCondition(
                proposed.success.fact,
                proposed.success.target,
                None,
                None,
            )
        else:
            fact, target = _CANONICAL_SUCCESS[proposed.skill]
            success = SuccessCondition(fact, target, None, None)
        recovery = (
            ("safe_stop",)
            if "safe_stop" in contract.recovery_actions
            else (("wait",) if "wait" in contract.recovery_actions else ())
        )
        steps.append(
            replace(
                proposed,
                step_id=f"step_{index}",
                preconditions=tuple(sorted(preconditions)),
                success=success,
                timeout_s=contract.max_timeout_s,
                max_attempts=1,
                recovery=recovery,
                resources=contract.resources,
                interruptibility=contract.minimum_interruptibility,
            )
        )
    return replace(
        plan,
        goal=replace(plan.goal, tolerance_m=0.0),
        invariants=(),
        steps=tuple(steps),
        requested_interrupt="at_checkpoint",
    )


def compile_plan_sketch(
    sketch: PlanSketch,
    intent_frame: IntentFrame,
    observation: ObservationSnapshot,
    registry: SkillContractRegistry,
) -> PlanIR:
    """Materialize compact model semantics under the trusted PlanIR envelope.

    Navigation success is copied only from each explicit model-authored
    ``NavigationGrounding``. It is never inferred from the directive, terminal
    goal, or observed scene. All argument values remain untouched so ordinary
    PlanIR validation rejects invalid or raw-control content fail closed.
    """

    if not isinstance(sketch, PlanSketch):
        raise TypeError("PlanSketch compilation requires a PlanSketch")
    if not isinstance(intent_frame, IntentFrame):
        raise TypeError("PlanSketch compilation requires an IntentFrame")
    if not isinstance(observation, ObservationSnapshot):
        raise TypeError("PlanSketch compilation requires an ObservationSnapshot")
    if not isinstance(registry, SkillContractRegistry):
        raise TypeError("PlanSketch compilation requires a SkillContractRegistry")

    proposed_steps: list[PlanStep] = []
    for index, step in enumerate(sketch.steps, start=1):
        if step.skill == "NavigateTo":
            grounding = step.navigation
            if grounding is None:  # defensive; PlanSketch already enforces this
                raise ValueError("NavigateTo requires explicit navigation grounding")
            success = SuccessCondition(grounding.relation, grounding.target)
        else:
            # compile_plan_contracts replaces this sentinel from the admitted
            # skill contract. It is never validated or dispatched as authored.
            success = SuccessCondition("system_compile_pending")
        proposed_steps.append(
            PlanStep(
                step_id=f"sketch_{index}",
                skill=step.skill,
                arguments=step.arguments,
                success=success,
                timeout_s=0.1,
            )
        )
    unbound = PlanIR(
        schema_version=1,
        task_id="unbound-plan-sketch",
        plan_revision=1,
        source_turn_id="unbound-plan-sketch",
        goal=sketch.goal.as_goal_spec(),
        invariants=(),
        steps=tuple(proposed_steps),
        requested_interrupt="at_checkpoint",
    )
    trusted = bind_plan_context(unbound, intent_frame, observation)
    return compile_plan_contracts(trusted, registry)


def materialize_planner_output(
    output: PlanIR | PlanSketch,
    intent_frame: IntentFrame,
    observation: ObservationSnapshot,
    registry: SkillContractRegistry,
) -> PlanIR:
    """Adapt either supported planner contract to trusted PlanIR.

    Legacy PlanIR remains unchanged apart from the existing trusted-envelope
    binding. PlanSketch is deterministically expanded before entering the same
    runtime validation and executive path.
    """

    if isinstance(output, PlanIR):
        return bind_plan_context(output, intent_frame, observation)
    if isinstance(output, PlanSketch):
        return compile_plan_sketch(output, intent_frame, observation, registry)
    raise TypeError("planner returned neither PlanIR nor PlanSketch")
