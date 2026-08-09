"""Fail-closed validation for model-proposed :class:`~.contracts.PlanIR` values."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache

from .contracts import (
    RESOURCES,
    ObservationSnapshot,
    PlanIR,
    PlanStep,
)

ALLOWED_PRECONDITIONS = frozenset(
    {
        "camera_fresh",
        "lidar_fresh",
        "base_available",
        "posture_available",
        "voice_available",
        "attention_available",
        "owner_visible",
        "owner_heading_available",
        "robot_stopped",
        "target_grounded",
        "battery_critical",
        "safe_region_grounded",
    }
)
ALLOWED_INVARIANTS = frozenset(
    {
        "keep_collision_margin",
        "avoid_road_when_not_crossing",
        "stay_within_local_orbit",
        "stop_on_stale_perception",
        "yield_to_people",
        "preserve_owner_visibility",
        "do_not_interrupt_critical_task",
    }
)
ALLOWED_RECOVERY = frozenset(
    {
        "replan",
        "alternate_candidate",
        "rescan",
        "ask_user",
        "wait",
        "reacquire_owner",
        "safe_stop",
    }
)
_INVARIANT_ORDER = (
    "keep_collision_margin",
    "avoid_road_when_not_crossing",
    "stay_within_local_orbit",
    "stop_on_stale_perception",
    "yield_to_people",
    "preserve_owner_visibility",
    "do_not_interrupt_critical_task",
)
_FORBIDDEN_ARGUMENT_KEYS = frozenset(
    {
        "vx",
        "vy",
        "vyaw",
        "yaw",
        "yawrate",
        "x",
        "y",
        "z",
        "coordinate",
        "coordinates",
        "waypoint",
        "waypoints",
        "joint",
        "joints",
        "jointpositions",
        "torque",
        "torques",
        "priority",
    }
)
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
# Skills the runtime proposes deterministically. They are validated, dispatched,
# and verified exactly like any other semantic skill, but they never appear in a
# planner prompt or response schema, so no model can author one.
SYSTEM_SKILL_NAMES = frozenset({"SearchOwner", "ScanBehavior", "SearchEntity"})

#: Skills the **runtime's own deterministic sketches** may author even when the
#: deployment's ``agent.brain.skills`` list does not name them. A registry built
#: with ``system_authored=True`` always admits these; a model-facing registry
#: never does, so this widens nothing a language model can reach.
#:
#: ``Pose`` is here for backlog N13's settle step ("sit next to X" = navigate +
#: sit). It is deliberately NOT added to ``configs/robot.yaml``: that file is a
#: **locked input of the frozen embodied-plan manifest**
#: (``evals/companion/embodied_plan_v1/manifest.json`` pins its SHA-256), so
#: editing it fails the manifest verification and invalidates a frozen
#: baseline. It is also deliberately NOT moved into
#: :data:`SYSTEM_SKILL_NAMES`, because that set is what
#: ``SkillContractRegistry.default()`` filters on, and the frozen live-planner
#: probe asserts ``Pose`` is present in the full default registry and raw plan
#: schema.
RUNTIME_AUTHORED_SKILLS = frozenset({"Pose"})


class PlanValidationError(ValueError):
    """A PlanIR failed one named, machine-testable validation rule."""

    def __init__(self, code: str, message: str, *, path: str = "$"):
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True, slots=True)
class SkillContract:
    name: str
    contract_version: int
    argument_profile: str
    required_arguments: frozenset[str]
    optional_arguments: frozenset[str]
    resources: tuple[str, ...]
    required_preconditions: frozenset[str]
    success_facts: frozenset[str]
    recovery_actions: frozenset[str]
    max_timeout_s: float
    minimum_interruptibility: str

    @property
    def allowed_arguments(self) -> frozenset[str]:
        return self.required_arguments | self.optional_arguments


class SkillContractRegistry:
    """Immutable lookup of semantic skills and their system-owned policies."""

    def __init__(
        self,
        contracts: Iterable[SkillContract],
        *,
        pose_names: Iterable[str] = (),
        gesture_names: Iterable[str] = (),
        owner_heading_supported: bool = False,
        system_authored: bool = False,
    ):
        values = tuple(contracts)
        self._contracts = {item.name: item for item in values}
        if len(self._contracts) != len(values):
            raise ValueError("skill contract names must be unique")
        self.pose_names = frozenset(str(item) for item in pose_names)
        self.gesture_names = frozenset(str(item) for item in gesture_names)
        if not isinstance(owner_heading_supported, bool):
            raise TypeError("owner_heading_supported must be a boolean")
        self.owner_heading_supported = owner_heading_supported
        if not isinstance(system_authored, bool):
            raise TypeError("system_authored must be a boolean")
        # True only for the registry the *runtime's own* deterministic plans
        # validate against. Arguments a model may never author — today the
        # plain-follow relation — are admitted off this flag, so a loose-decode
        # provider cannot reach them through the model-facing validator
        # (arbitration OB-2). The JSON-schema ``const`` is a hint to the model;
        # this is the enforcement.
        self.system_authored = system_authored

    @classmethod
    def default(
        cls,
        *,
        pose_names: Iterable[str] = (),
        gesture_names: Iterable[str] = (),
        owner_heading_supported: bool = False,
        include_system_skills: bool = False,
    ) -> SkillContractRegistry:
        """Build the admitted registry.

        System skills are withheld unless asked for: the planner's response
        schema is derived from these names, and a skill only the runtime may
        propose must not widen the surface a model can author into.
        """

        def contract(
            name: str,
            profile: str,
            required_arguments: Iterable[str],
            optional_arguments: Iterable[str],
            resources: tuple[str, ...],
            preconditions: Iterable[str],
            success: Iterable[str],
            recovery: Iterable[str],
            timeout: float,
            interruptibility: str,
        ) -> SkillContract:
            return SkillContract(
                name=name,
                contract_version=1,
                argument_profile=profile,
                required_arguments=frozenset(required_arguments),
                optional_arguments=frozenset(optional_arguments),
                resources=resources,
                required_preconditions=frozenset(preconditions),
                success_facts=frozenset(success),
                recovery_actions=frozenset(recovery),
                max_timeout_s=timeout,
                minimum_interruptibility=interruptibility,
            )

        contracts = (
            contract(
                "NavigateTo",
                "navigate",
                ("directive",),
                (),
                ("base", "attention"),
                # Admission requires a searchable target, not a visible one:
                # grounding-with-recovery is NavigateTo's own job via the
                # resolution ladder (frustum -> memory -> scan -> frontier ->
                # honest report). Requiring "target_grounded" here rejected
                # every out-of-frustum target at admission and dead-ended
                # "go to the sidewalk" before the ladder could run.
                (
                    "camera_fresh",
                    "lidar_fresh",
                    "base_available",
                ),
                ("inside", "near"),
                ("replan", "alternate_candidate", "rescan", "ask_user", "safe_stop"),
                # 120->240 (2026-08-05): the contract timeout is a safety net
                # for a hung controller and must sit ABOVE the navigator's own
                # bounded give-up (~220 s worst case: stall windows + scans +
                # frontier + travel), so failures arrive with navigator
                # attribution instead of a blunt step_timeout. Same rule
                # SearchOwner already applies below.
                240.0,
                "checkpoint",
            ),
            contract(
                "FollowFormation",
                "follow",
                ("relation", "distance_m"),
                (),
                ("base", "attention"),
                # owner_heading_available is deliberately NOT a blanket
                # requirement (arbiter ruling 2026-08-06). It is a property of
                # the *behind* relation — you cannot stage behind someone
                # whose direction of travel you cannot estimate — not of the
                # skill. Plain follow tracks the owner directly and needs
                # owner_visible only. The compiler adds the heading
                # precondition per relation, exactly as it does for
                # MoveRelative(direction=away_from_owner) + owner_visible.
                ("camera_fresh", "lidar_fresh", "base_available", "owner_visible"),
                ("behind", "following"),
                ("reacquire_owner", "replan", "wait", "safe_stop"),
                300.0,
                "checkpoint",
            ),
            contract(
                "OrbitOwner",
                "orbit",
                ("direction", "size", "revolutions"),
                (),
                ("base", "attention"),
                ("camera_fresh", "lidar_fresh", "base_available", "owner_visible"),
                ("orbit_complete",),
                ("reacquire_owner", "replan", "safe_stop"),
                180.0,
                "checkpoint",
            ),
            contract(
                "MoveRelative",
                "relative",
                ("direction", "steps"),
                (),
                ("base",),
                ("lidar_fresh", "base_available"),
                ("distance_travelled",),
                ("wait", "safe_stop"),
                60.0,
                "checkpoint",
            ),
            contract(
                "Hold",
                "empty",
                (),
                (),
                ("base",),
                ("base_available",),
                ("motion_stopped",),
                ("safe_stop",),
                10.0,
                "immediate",
            ),
            contract(
                "Pose",
                "pose",
                ("name",),
                (),
                ("base", "posture"),
                ("base_available", "posture_available", "robot_stopped"),
                ("skill_completed",),
                ("wait", "safe_stop"),
                30.0,
                "checkpoint",
            ),
            contract(
                "Gesture",
                "gesture",
                ("name",),
                ("intensity",),
                ("base", "posture"),
                ("base_available", "posture_available", "robot_stopped"),
                ("skill_completed",),
                ("wait", "safe_stop"),
                30.0,
                "checkpoint",
            ),
            contract(
                "Vocalize",
                "utterance",
                ("text",),
                (),
                ("voice",),
                ("voice_available",),
                ("utterance_sent",),
                ("wait",),
                30.0,
                "immediate",
            ),
            contract(
                "AskClarification",
                "question",
                ("question",),
                (),
                ("voice",),
                ("voice_available",),
                ("utterance_sent",),
                ("wait",),
                30.0,
                "immediate",
            ),
            contract(
                "SearchOwner",
                "empty",
                (),
                (),
                ("base", "attention"),
                # Deliberately no owner_visible: this skill exists precisely
                # because the owner is not visible.
                ("camera_fresh", "lidar_fresh", "base_available"),
                ("owner_reacquired",),
                ("replan", "alternate_candidate", "safe_stop"),
                # Comfortably above the controller's own 45 s give-up so the
                # skill's Vocalize+Hold path is what fires, not the
                # executive's blunt step timeout.
                60.0,
                "checkpoint",
            ),
            contract(
                "ScanBehavior",
                "empty",
                (),
                (),
                ("base", "attention"),
                ("camera_fresh", "base_available"),
                ("skill_completed",),
                ("rescan", "safe_stop"),
                30.0,
                "checkpoint",
            ),
            contract(
                "SearchEntity",
                "search_entity",
                ("query",),
                (),
                ("base", "attention"),
                ("camera_fresh", "lidar_fresh", "base_available"),
                ("skill_completed",),
                ("replan", "alternate_candidate", "rescan", "safe_stop"),
                90.0,
                "checkpoint",
            ),
            contract(
                "ReturnToSafePose",
                "safe_pose",
                ("pose",),
                (),
                ("base", "posture", "attention"),
                (
                    "camera_fresh",
                    "lidar_fresh",
                    "base_available",
                    "posture_available",
                    "battery_critical",
                ),
                ("safe_pose",),
                ("replan", "alternate_candidate", "safe_stop"),
                120.0,
                "never",
            ),
        )
        return cls(
            (
                item
                for item in contracts
                if include_system_skills or item.name not in SYSTEM_SKILL_NAMES
            ),
            pose_names=pose_names,
            gesture_names=gesture_names,
            owner_heading_supported=owner_heading_supported,
            # Asking for the system skills is asking for the system registry.
            system_authored=include_system_skills,
        )

    def get(self, name: str) -> SkillContract:
        try:
            return self._contracts[name]
        except KeyError as error:
            # A *system-authored* registry also admits the skills only the
            # runtime's own deterministic sketches emit, so a deployment's
            # ``agent.brain.skills`` list does not have to name them. This is
            # deliberately in ``get`` and NOT in ``names``: schemas, prompt
            # contracts, and the duplex skill list all derive from ``names``,
            # so the model-facing surface is provably unchanged — a model
            # cannot even see ``Pose`` in its response schema, and the
            # model-facing registry (system_authored=False) still refuses it
            # here with ``unknown_skill``.
            if self.system_authored and name in RUNTIME_AUTHORED_SKILLS:
                fallback = _runtime_authored_contracts().get(name)
                if fallback is not None:
                    return fallback
            raise PlanValidationError(
                "unknown_skill",
                f"skill is not present in the admitted registry: {name}",
            ) from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._contracts))

    def prompt_description(self) -> dict[str, object]:
        """Return a compact, deterministic skill catalog safe for model prompts."""

        return {
            "schema_version": 1,
            "capabilities": {
                "owner_heading_supported": self.owner_heading_supported,
            },
            "skills": [
                {
                    "name": contract.name,
                    # Model-facing admission only. The plan_ir/plan_sketch
                    # schemas pin a model-authored FollowFormation to
                    # relation="behind", so for a model this skill really does
                    # require heading support. The system-authored plain
                    # follow relation is not exposed here and is not gated by
                    # this flag (arbiter ruling 2026-08-06).
                    "admitted": (
                        contract.name != "FollowFormation" or self.owner_heading_supported
                    ),
                    "contract_version": contract.contract_version,
                    "argument_profile": contract.argument_profile,
                    "arguments": {
                        "required": sorted(contract.required_arguments),
                        "optional": sorted(contract.optional_arguments),
                    },
                    "resources": list(contract.resources),
                    "required_preconditions": sorted(contract.required_preconditions),
                    "success_facts": sorted(contract.success_facts),
                    "recovery_actions": sorted(contract.recovery_actions),
                    "max_timeout_s": contract.max_timeout_s,
                    "minimum_interruptibility": contract.minimum_interruptibility,
                }
                for contract in (self._contracts[name] for name in sorted(self._contracts))
            ],
        }

    def restricted(
        self,
        enabled: Iterable[str],
        *,
        system_authored: bool | None = None,
    ) -> SkillContractRegistry:
        names = frozenset(enabled)
        unknown = names - self._contracts.keys()
        if unknown:
            raise ValueError(f"cannot enable unknown skill contracts: {sorted(unknown)}")
        return SkillContractRegistry(
            (self._contracts[name] for name in sorted(names)),
            pose_names=self.pose_names,
            gesture_names=self.gesture_names,
            owner_heading_supported=self.owner_heading_supported,
            # Narrowing defaults to model-facing: a restricted registry must
            # opt in to system authority, never inherit it by accident.
            system_authored=(
                self.system_authored if system_authored is None else bool(system_authored)
            ),
        )


@dataclass(frozen=True, slots=True)
class ValidatedStep:
    step: PlanStep
    contract_version: int
    effective_resources: tuple[str, ...]
    effective_interruptibility: str


@dataclass(frozen=True, slots=True)
class ValidatedPlan:
    plan: PlanIR
    steps: tuple[ValidatedStep, ...]
    effective_invariants: tuple[str, ...]
    plan_sha256: str
    validated_against_snapshot_id: str | None


class PlanValidator:
    """Validate structure, affordances, and safety without executing anything."""

    def __init__(
        self,
        registry: SkillContractRegistry | None = None,
        *,
        maximum_total_timeout_s: float = 600.0,
    ):
        if not math.isfinite(maximum_total_timeout_s) or maximum_total_timeout_s <= 0:
            raise ValueError("maximum_total_timeout_s must be positive and finite")
        self.registry = registry or SkillContractRegistry.default()
        self.maximum_total_timeout_s = maximum_total_timeout_s

    def prompt_contract(self) -> dict[str, object]:
        """Describe the bounded planner output surface without runtime state."""

        return {
            "contract": "parcel_plan_ir_v1",
            "schema_version": 1,
            "maximum_total_timeout_s": self.maximum_total_timeout_s,
            "allowed_invariants": sorted(ALLOWED_INVARIANTS),
            "policy": {
                "raw_controls_allowed": False,
                "priority_owner": "system_executive",
                "success_requires_verified_fact": True,
                "safety_invariants_system_compiled": True,
                "model_invariants_are_advisory": True,
            },
            "skill_registry": self.registry.prompt_description(),
        }

    def validate(
        self,
        plan: PlanIR,
        snapshot: ObservationSnapshot | None = None,
    ) -> ValidatedPlan:
        if not isinstance(plan, PlanIR):
            raise TypeError("PlanValidator requires a parsed PlanIR")
        self._validate_plan_level(plan)
        validated_steps: list[ValidatedStep] = []
        step_ids: set[str] = set()
        total_timeout = 0.0
        for index, step in enumerate(plan.steps):
            path = f"$.steps[{index}]"
            if step.step_id in step_ids:
                raise PlanValidationError(
                    "duplicate_step_id", "step IDs must be unique", path=f"{path}.id"
                )
            step_ids.add(step.step_id)
            contract = self.registry.get(step.skill)
            total_timeout += step.timeout_s * step.max_attempts
            validated_steps.append(self._validate_step(step, contract, path=path))
        if total_timeout > self.maximum_total_timeout_s:
            raise PlanValidationError(
                "timeout_budget_exceeded",
                f"worst-case step time {total_timeout:g}s exceeds "
                f"{self.maximum_total_timeout_s:g}s",
            )
        self._validate_goal_completion(plan)
        if snapshot is not None:
            self._validate_snapshot_admission(plan, snapshot)
        effective_invariants = self._effective_invariants(plan)
        canonical = json.dumps(
            {
                "compiler_policy": "parcel-system-invariants-v1",
                "plan": plan.as_dict(),
                "effective_invariants": list(effective_invariants),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return ValidatedPlan(
            plan=plan,
            steps=tuple(validated_steps),
            effective_invariants=effective_invariants,
            plan_sha256=hashlib.sha256(canonical).hexdigest(),
            validated_against_snapshot_id=snapshot.snapshot_id if snapshot is not None else None,
        )

    def _validate_plan_level(self, plan: PlanIR) -> None:
        invariants = frozenset(plan.invariants)
        unknown = invariants - ALLOWED_INVARIANTS
        if unknown:
            raise PlanValidationError(
                "unknown_invariant",
                f"unsupported invariants: {sorted(unknown)}",
                path="$.invariants",
            )
        allowed_goal_relations = {
            "semantic_region": {"inside"},
            "semantic_object": {"near"},
            "owner": {"behind", "follow", "orbit", "relative", "reacquire"},
            "current_pose": {"hold", "relative"},
            "safe_region": {"safe_pose"},
        }
        if plan.goal.relation not in allowed_goal_relations[plan.goal.target.kind]:
            raise PlanValidationError(
                "invalid_goal_relation",
                f"{plan.goal.target.kind} cannot use relation {plan.goal.relation!r}",
                path="$.goal",
            )

    @staticmethod
    def _effective_invariants(plan: PlanIR) -> tuple[str, ...]:
        """Compile non-negotiable runtime policy independently of model text."""

        skills = {step.skill for step in plan.steps}
        uses_base = any("base" in step.resources for step in plan.steps)
        translational_motion = bool(
            skills
            & {
                "NavigateTo",
                "FollowFormation",
                "OrbitOwner",
                "MoveRelative",
                "ReturnToSafePose",
                "SearchOwner",
                "ScanBehavior",
                "SearchEntity",
            }
        )
        perception = any(
            {"camera_fresh", "lidar_fresh"} & set(step.preconditions) for step in plan.steps
        )
        effective = {"do_not_interrupt_critical_task"}
        if uses_base:
            effective.update({"keep_collision_margin", "yield_to_people"})
        if translational_motion:
            # Parcel has no admitted road-crossing skill yet. Every
            # translational plan therefore retains the pedestrian-companion default of
            # avoiding road regions; a future explicit crossing contract can
            # compile a different, separately verified policy.
            effective.add("avoid_road_when_not_crossing")
        if perception:
            effective.add("stop_on_stale_perception")
        if "OrbitOwner" in skills:
            effective.update({"stay_within_local_orbit", "preserve_owner_visibility"})
        if "FollowFormation" in skills or any(
            step.skill == "MoveRelative" and step.arguments.get("direction") == "away_from_owner"
            for step in plan.steps
        ):
            effective.add("preserve_owner_visibility")
        return tuple(item for item in _INVARIANT_ORDER if item in effective)

    def _validate_step(
        self,
        step: PlanStep,
        contract: SkillContract,
        *,
        path: str,
    ) -> ValidatedStep:
        keys = frozenset(step.arguments)
        _reject_forbidden_argument_keys(step.arguments, path=f"{path}.arguments")
        missing = contract.required_arguments - keys
        unknown = keys - contract.allowed_arguments
        if missing or unknown:
            raise PlanValidationError(
                "invalid_arguments",
                f"missing={sorted(missing)}, unknown={sorted(unknown)}",
                path=f"{path}.arguments",
            )
        self._validate_argument_profile(step, contract, path=f"{path}.arguments")

        preconditions = frozenset(step.preconditions)
        unknown_preconditions = preconditions - ALLOWED_PRECONDITIONS
        missing_preconditions = contract.required_preconditions - preconditions
        if unknown_preconditions or missing_preconditions:
            raise PlanValidationError(
                "invalid_preconditions",
                f"missing={sorted(missing_preconditions)}, unknown={sorted(unknown_preconditions)}",
                path=f"{path}.preconditions",
            )
        if step.success.fact not in contract.success_facts:
            raise PlanValidationError(
                "invalid_success_condition",
                f"{step.skill} cannot prove {step.success.fact!r}",
                path=f"{path}.success.fact",
            )
        self._validate_success_condition(step, path=f"{path}.success")
        recovery = frozenset(step.recovery)
        invalid_recovery = recovery - contract.recovery_actions
        if invalid_recovery or recovery - ALLOWED_RECOVERY:
            raise PlanValidationError(
                "invalid_recovery",
                f"unsupported recovery for {step.skill}: {sorted(invalid_recovery)}",
                path=f"{path}.recovery",
            )
        if step.timeout_s > contract.max_timeout_s:
            raise PlanValidationError(
                "step_timeout_exceeded",
                f"{step.skill} timeout exceeds {contract.max_timeout_s:g}s",
                path=f"{path}.timeout_s",
            )
        if frozenset(step.resources) != frozenset(contract.resources):
            raise PlanValidationError(
                "resource_mismatch",
                f"{step.skill} requires exactly {list(contract.resources)}",
                path=f"{path}.resources",
            )
        resources = tuple(item for item in RESOURCES if item in contract.resources)
        return ValidatedStep(
            step=step,
            contract_version=contract.contract_version,
            effective_resources=resources,
            effective_interruptibility=_effective_interruptibility(
                step.interruptibility, contract.minimum_interruptibility
            ),
        )

    @staticmethod
    def _validate_success_condition(step: PlanStep, *, path: str) -> None:
        """Reject success claims the current runtime verifier cannot prove."""

        success = step.success
        if success.tolerance_m is not None:
            raise PlanValidationError(
                "unverifiable_success_tolerance",
                "numeric success tolerance is system-owned and not present in VerifiedFact v1",
                path=f"{path}.tolerance_m",
            )
        if step.skill == "NavigateTo":
            if success.target is None:
                raise PlanValidationError(
                    "invalid_success_target",
                    "NavigateTo requires the grounded semantic label as success target",
                    path=f"{path}.target",
                )
            directive = str(step.arguments["directive"])
            if ":" in directive or _normalize(success.target) not in _normalize(directive):
                raise PlanValidationError(
                    "navigation_directive_mismatch",
                    "every NavigateTo directive must contain its explicit grounded label",
                    path=f"{path}.target",
                )
            return
        expected_target = {
            "FollowFormation": "owner",
            "OrbitOwner": "owner",
            "SearchOwner": "owner",
        }.get(step.skill)
        if expected_target is not None:
            if _normalize(success.target) != expected_target:
                raise PlanValidationError(
                    "invalid_success_target",
                    f"{step.skill} success target must be {expected_target!r}",
                    path=f"{path}.target",
                )
            return
        if success.target is not None:
            raise PlanValidationError(
                "invalid_success_target",
                f"{step.skill} success does not admit a model-authored target",
                path=f"{path}.target",
            )

    def _validate_argument_profile(
        self,
        step: PlanStep,
        contract: SkillContract,
        *,
        path: str,
    ) -> None:
        args = step.arguments
        profile = contract.argument_profile
        try:
            if profile == "empty":
                return
            if profile == "navigate":
                _text(args["directive"], minimum=1, maximum=500)
            elif profile == "follow":
                # Plain follow is a system-authored relation: the model-facing
                # schema pins `behind`, and this registry check is what makes
                # that pin enforceable against a loose-decode provider
                # (arbitration OB-2 — the plan_ir `const` is only a hint).
                _one_of(
                    args["relation"],
                    {"follow", "behind"} if self.registry.system_authored else {"behind"},
                )
                if args["relation"] == "behind":
                    # Behind staging is the only relation that consumes an
                    # owner motion heading; plain follow must not inherit its
                    # capability gate (arbiter ruling 2026-08-06).
                    if not self.registry.owner_heading_supported:
                        raise ValueError(
                            "owner heading support is unavailable; behind formation "
                            "cannot be admitted"
                        )
                    if "owner_heading_available" not in step.preconditions:
                        raise ValueError("behind formation requires owner_heading_available")
                _numeric(args["distance_m"], minimum=0.8, maximum=3.0)
            elif profile == "orbit":
                _one_of(args["direction"], {"clockwise", "counterclockwise"})
                _one_of(args["size"], {"small", "normal", "wide"})
                _numeric(args["revolutions"], minimum=0.25, maximum=1.0)
            elif profile == "relative":
                _one_of(args["direction"], {"forward", "backward", "away_from_owner"})
                _integer_range(args["steps"], minimum=1, maximum=12)
                if (
                    args["direction"] == "away_from_owner"
                    and "owner_visible" not in step.preconditions
                ):
                    raise ValueError("away_from_owner requires owner_visible")
            elif profile in {"pose", "gesture"}:
                name = _text(args["name"], minimum=1, maximum=80)
                admitted = (
                    self.registry.pose_names if profile == "pose" else self.registry.gesture_names
                )
                if not admitted:
                    raise ValueError(f"no {profile} catalog was supplied to the validator")
                if name not in admitted:
                    raise ValueError(f"{name!r} is not in the admitted {profile} catalog")
                if profile == "gesture" and "intensity" in args:
                    # Expressive scale only; the clip's own joint limits still
                    # bound the motion, so this can never widen a gesture past
                    # what the catalog authorized.
                    _numeric(args["intensity"], minimum=0.5, maximum=1.5)
            elif profile == "utterance":
                _text(args["text"], minimum=1, maximum=500)
            elif profile == "question":
                _text(args["question"], minimum=1, maximum=300)
            elif profile == "safe_pose":
                pose = _text(args["pose"], minimum=1, maximum=80)
                if pose not in self.registry.pose_names:
                    raise ValueError(f"{pose!r} is not in the admitted pose catalog")
            elif profile == "search_entity":
                _text(args["query"], minimum=1, maximum=120)
            else:
                raise RuntimeError(f"unsupported internal argument profile: {profile}")
        except (TypeError, ValueError) as error:
            raise PlanValidationError("invalid_argument_value", str(error), path=path) from error

    @staticmethod
    def _validate_goal_completion(plan: PlanIR) -> None:
        voice_or_meta = {"AskClarification", "Vocalize"}
        goal_steps = tuple(
            (index, step)
            for index, step in enumerate(plan.steps)
            if step.skill not in voice_or_meta
        )
        # A terminal Hold is a postcondition-preserving settle/wait action, not
        # a new spatial objective. Permit it after an inside/near/orbit/etc.
        # achiever while still rejecting any later motion that contradicts the
        # declared terminal goal.
        if plan.goal.relation != "hold":
            while goal_steps and goal_steps[-1][1].skill == "Hold":
                goal_steps = goal_steps[:-1]
        if not goal_steps:
            if plan.goal.relation == "hold" and plan.goal.target.kind == "current_pose":
                return
            raise PlanValidationError(
                "goal_not_achievable",
                "speech-only plans cannot claim a physical goal",
                path="$.steps",
            )
        final_index, final = goal_steps[-1]
        if (
            final.skill in {"Pose", "Gesture", "ScanBehavior", "SearchEntity"}
            and plan.goal.relation == "hold"
            and final.success.fact == "skill_completed"
        ):
            return
        expected = {
            "inside": "inside",
            "near": "near",
            "behind": "behind",
            "follow": "following",
            "orbit": "orbit_complete",
            "hold": "motion_stopped",
            "safe_pose": "safe_pose",
            "relative": "distance_travelled",
            "reacquire": "owner_reacquired",
        }[plan.goal.relation]
        if final.success.fact != expected:
            raise PlanValidationError(
                "goal_success_mismatch",
                f"goal relation {plan.goal.relation!r} requires final fact {expected!r}",
                path=f"$.steps[{final_index}].success.fact",
            )
        if (
            final.success.target is not None
            and plan.goal.target.query
            and _normalize(final.success.target) != _normalize(plan.goal.target.query)
        ):
            raise PlanValidationError(
                "goal_target_mismatch",
                "final success target does not match the plan goal",
                path=f"$.steps[{final_index}].success.target",
            )
        if final.skill == "NavigateTo":
            directive = str(final.arguments["directive"])
            query = plan.goal.target.query
            if ":" in directive or _normalize(query) not in _normalize(directive):
                raise PlanValidationError(
                    "navigation_directive_mismatch",
                    "NavigateTo directive must use the grounded target label, not an entity ID",
                    path=f"$.steps[{final_index}].arguments.directive",
                )

    @staticmethod
    def _validate_snapshot_admission(
        plan: PlanIR,
        snapshot: ObservationSnapshot,
    ) -> None:
        if snapshot.safety.emergency_stopped:
            raise PlanValidationError(
                "emergency_stopped",
                "new model-authored plans are not admitted during emergency stop",
                path="$.snapshot.safety.emergency_stopped",
            )
        first = plan.steps[0]
        preconditions = frozenset(first.preconditions)
        if "camera_fresh" in preconditions and not snapshot.camera.fresh:
            raise PlanValidationError(
                "camera_stale", "first step requires a fresh camera", path="$.snapshot.camera"
            )
        if "lidar_fresh" in preconditions and not snapshot.lidar.fresh:
            raise PlanValidationError(
                "lidar_stale", "first step requires fresh LiDAR", path="$.snapshot.lidar"
            )
        if "owner_visible" in preconditions and not any(
            entity.kind == "owner" and entity.confidence >= 0.6 for entity in snapshot.entities
        ):
            raise PlanValidationError(
                "owner_not_grounded",
                "first step requires a camera-grounded owner",
                path="$.snapshot.entities",
            )
        if "owner_heading_available" in preconditions and not any(
            entity.kind == "owner"
            and entity.confidence >= 0.6
            and entity.attributes.get("motion_heading_available") is True
            for entity in snapshot.entities
        ):
            raise PlanValidationError(
                "owner_heading_unavailable",
                "behind formation requires a current owner motion heading",
                path="$.snapshot.entities",
            )
        if "target_grounded" in preconditions:
            target = first.success.target or plan.goal.target.query
            if not target or not snapshot.matching_entities(target):
                raise PlanValidationError(
                    "target_not_grounded",
                    f"first step requires grounded target {target!r}",
                    path="$.snapshot.entities",
                )
        if "battery_critical" in preconditions and snapshot.battery.state != "critical":
            raise PlanValidationError(
                "battery_not_critical",
                "battery-critical procedure requires trusted critical telemetry",
                path="$.snapshot.battery",
            )


_INTERRUPT_RANK = {"immediate": 0, "checkpoint": 1, "when_idle": 2, "never": 3}


def _effective_interruptibility(requested: str, minimum: str) -> str:
    return max((requested, minimum), key=lambda item: _INTERRUPT_RANK[item])


def _reject_forbidden_argument_keys(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalize_key(key)
            if normalized in _FORBIDDEN_ARGUMENT_KEYS:
                raise PlanValidationError(
                    "raw_control_argument",
                    f"model plans cannot contain raw control field {key!r}",
                    path=f"{path}.{key}",
                )
            _reject_forbidden_argument_keys(item, path=f"{path}.{key}")
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            _reject_forbidden_argument_keys(item, path=f"{path}[{index}]")


def _normalize_key(value: object) -> str:
    return "".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def _normalize(value: object) -> str:
    return "".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def _text(value: object, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f"value must be text with length {minimum}..{maximum}")
    return value.strip()


def _numeric(value: object, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("value must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"numeric value must be between {minimum} and {maximum}")
    return result


def _integer_range(value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"value must be an integer between {minimum} and {maximum}")
    return value


def _one_of(value: object, allowed: set[str]) -> str:
    if value not in allowed:
        raise ValueError(f"value must be one of {sorted(allowed)}")
    return str(value)


@lru_cache(maxsize=1)
def _runtime_authored_contracts() -> dict[str, SkillContract]:
    """Contracts for :data:`RUNTIME_AUTHORED_SKILLS`, built once."""

    full = SkillContractRegistry.default(include_system_skills=True)
    return {name: full._contracts[name] for name in RUNTIME_AUTHORED_SKILLS}
