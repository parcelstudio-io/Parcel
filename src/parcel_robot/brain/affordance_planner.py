"""Bounded, outcome-driven planning over grounded semantic skills.

This module is deliberately on the proposal side of Parcel's authority
boundary.  It searches over *confirmed* world facts and commissioned semantic
skill names, but it cannot dispatch a skill, acquire a resource, or authorize
motion.  A caller must still compile/validate a proposal and submit it through
the normal task executive and motion gateway.

The planner is useful for compositional generalization because a new mission
can be solved by reusing grounded operators instead of matching one frozen
plan template.  It remains honest about uncertainty: an unobserved fact never
satisfies a precondition, predicted effects are not treated as observations,
and replanning consumes only a newer outcome receipt.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
from dataclasses import dataclass, field, replace

from .contracts import FrozenDict

PLAN_STATUSES = frozenset(
    {
        "planned",
        "goal_satisfied",
        "needs_observation",
        "unreachable",
        "budget_exhausted",
        "unsafe_state",
    }
)
TERMINAL_OUTCOME_STATUSES = frozenset({"succeeded", "blocked", "failed", "cancelled", "timed_out"})

_FACT = re.compile(r"^[a-z][a-z0-9_.:-]{0,95}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SKILL = re.compile(r"^[A-Z][A-Za-z0-9]{0,63}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class AffordancePlanningError(ValueError):
    """A planning contract is malformed or crosses an authority boundary."""


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise AffordancePlanningError(f"{name} must be a bounded identifier")
    return value


def _fact_set(value: object, name: str) -> frozenset[str]:
    if not isinstance(value, frozenset):
        raise AffordancePlanningError(f"{name} must be an immutable frozenset")
    if len(value) > 256:
        raise AffordancePlanningError(f"{name} exceeds 256 facts")
    for item in value:
        if not isinstance(item, str) or _FACT.fullmatch(item) is None:
            raise AffordancePlanningError(f"{name} contains an invalid fact")
    return value


def _integer(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AffordancePlanningError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise AffordancePlanningError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_number(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AffordancePlanningError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise AffordancePlanningError(f"{name} must be between {minimum} and {maximum}")
    return result


@dataclass(frozen=True, slots=True)
class ConfirmedWorldStateV1:
    """A three-valued state: facts are confirmed true, false, or unknown."""

    confirmed_true: frozenset[str]
    confirmed_false: frozenset[str]
    observation_epoch: int

    def __post_init__(self) -> None:
        _fact_set(self.confirmed_true, "confirmed_true")
        _fact_set(self.confirmed_false, "confirmed_false")
        if self.confirmed_true & self.confirmed_false:
            raise AffordancePlanningError("a fact cannot be confirmed true and false")
        _integer(self.observation_epoch, "observation_epoch", minimum=0, maximum=(1 << 63) - 1)

    @property
    def state_digest(self) -> str:
        return _canonical_digest(
            {
                "schema": "confirmed-world-state-v1",
                "confirmed_true": sorted(self.confirmed_true),
                "confirmed_false": sorted(self.confirmed_false),
                "observation_epoch": self.observation_epoch,
            }
        )

    def predicted_transition(self, operator: GroundedSkillV1) -> ConfirmedWorldStateV1:
        """Return a search-only state; this is never an observation receipt."""

        true_facts = (self.confirmed_true - operator.predicts_false) | operator.predicts_true
        false_facts = (self.confirmed_false - operator.predicts_true) | operator.predicts_false
        return ConfirmedWorldStateV1(true_facts, false_facts, self.observation_epoch)

    def with_outcome(self, outcome: PlannerOutcomeV1) -> ConfirmedWorldStateV1:
        """Merge only explicit receipt facts from a strictly newer epoch."""

        if outcome.observation_epoch <= self.observation_epoch:
            raise AffordancePlanningError("planner outcome observation epoch is stale")
        true_facts = (self.confirmed_true - outcome.observed_false) | outcome.observed_true
        false_facts = (self.confirmed_false - outcome.observed_true) | outcome.observed_false
        return ConfirmedWorldStateV1(true_facts, false_facts, outcome.observation_epoch)


@dataclass(frozen=True, slots=True)
class GroundedSkillV1:
    """One semantic skill instance with system-authored conditions/effects."""

    operator_id: str
    skill: str
    arguments: FrozenDict = field(default_factory=FrozenDict)
    requires_true: frozenset[str] = field(default_factory=frozenset)
    requires_false: frozenset[str] = field(default_factory=frozenset)
    predicts_true: frozenset[str] = field(default_factory=frozenset)
    predicts_false: frozenset[str] = field(default_factory=frozenset)
    base_cost: float = 1.0
    risk: float = 0.0
    reliability_key: str = "unscored"

    def __post_init__(self) -> None:
        _identifier(self.operator_id, "operator_id")
        if not isinstance(self.skill, str) or _SKILL.fullmatch(self.skill) is None:
            raise AffordancePlanningError("skill must be a bounded PascalCase identifier")
        if not isinstance(self.arguments, FrozenDict):
            object.__setattr__(self, "arguments", FrozenDict(self.arguments))
        _fact_set(self.requires_true, "requires_true")
        _fact_set(self.requires_false, "requires_false")
        _fact_set(self.predicts_true, "predicts_true")
        _fact_set(self.predicts_false, "predicts_false")
        if self.requires_true & self.requires_false:
            raise AffordancePlanningError("a skill cannot require a fact both true and false")
        if self.predicts_true & self.predicts_false:
            raise AffordancePlanningError("a skill cannot predict a fact both true and false")
        _bounded_number(self.base_cost, "base_cost", minimum=0.001, maximum=1_000_000.0)
        _bounded_number(self.risk, "risk", minimum=0.0, maximum=1.0)
        _identifier(self.reliability_key, "reliability_key")

    def applicable(self, state: ConfirmedWorldStateV1) -> bool:
        return self.requires_true <= state.confirmed_true and self.requires_false <= (
            state.confirmed_false
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "operator_id": self.operator_id,
            "skill": self.skill,
            "arguments": self.arguments.to_dict(),
            "requires_true": sorted(self.requires_true),
            "requires_false": sorted(self.requires_false),
            "predicts_true": sorted(self.predicts_true),
            "predicts_false": sorted(self.predicts_false),
            "base_cost": self.base_cost,
            "risk": self.risk,
            "reliability_key": self.reliability_key,
        }


@dataclass(frozen=True, slots=True)
class SkillReliabilityV1:
    """Frozen simulator evidence used only to rank or suppress proposals."""

    reliability_key: str
    successes: int
    failures: int
    safety_failures: int = 0

    def __post_init__(self) -> None:
        _identifier(self.reliability_key, "reliability_key")
        _integer(self.successes, "successes", minimum=0, maximum=1_000_000_000)
        _integer(self.failures, "failures", minimum=0, maximum=1_000_000_000)
        _integer(self.safety_failures, "safety_failures", minimum=0, maximum=1_000_000_000)
        if self.safety_failures > self.failures:
            raise AffordancePlanningError("safety_failures cannot exceed failures")

    @property
    def posterior_success(self) -> float:
        """Beta(1, 1) posterior mean; deterministic and deliberately modest."""

        return (self.successes + 1.0) / (self.successes + self.failures + 2.0)


@dataclass(frozen=True, slots=True)
class PlanningProblemV1:
    """One bounded search problem over a frozen grounded skill set."""

    state: ConfirmedWorldStateV1
    goal_true: frozenset[str]
    goal_false: frozenset[str]
    operators: tuple[GroundedSkillV1, ...]
    commissioned_skills: frozenset[str]
    capability_manifest_digest: str
    must_remain_true: frozenset[str] = field(default_factory=frozenset)
    forbidden_true: frozenset[str] = field(default_factory=frozenset)
    excluded_operator_ids: frozenset[str] = field(default_factory=frozenset)
    reliability: tuple[SkillReliabilityV1, ...] = ()
    max_steps: int = 12
    max_expansions: int = 4_096
    risk_weight: float = 10.0
    failure_weight: float = 2.0
    minimum_reliability: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.state, ConfirmedWorldStateV1):
            raise AffordancePlanningError("state must be ConfirmedWorldStateV1")
        _fact_set(self.goal_true, "goal_true")
        _fact_set(self.goal_false, "goal_false")
        _fact_set(self.must_remain_true, "must_remain_true")
        _fact_set(self.forbidden_true, "forbidden_true")
        if self.goal_true & self.goal_false:
            raise AffordancePlanningError("a goal fact cannot be both true and false")
        if self.goal_true & self.forbidden_true:
            raise AffordancePlanningError("a required goal fact cannot also be forbidden")
        if not self.must_remain_true <= self.state.confirmed_true:
            raise AffordancePlanningError("must_remain_true facts must be confirmed initially")
        if not isinstance(self.operators, tuple):
            raise AffordancePlanningError("operators must be an immutable tuple")
        if not 1 <= len(self.operators) <= 1_024:
            raise AffordancePlanningError("operators must contain between 1 and 1024 skills")
        if any(not isinstance(item, GroundedSkillV1) for item in self.operators):
            raise AffordancePlanningError("operators must contain GroundedSkillV1 values")
        operator_ids = tuple(item.operator_id for item in self.operators)
        if len(set(operator_ids)) != len(operator_ids):
            raise AffordancePlanningError("operator IDs must be unique")
        if not isinstance(self.commissioned_skills, frozenset):
            raise AffordancePlanningError("commissioned_skills must be an immutable frozenset")
        for skill in self.commissioned_skills:
            if not isinstance(skill, str) or _SKILL.fullmatch(skill) is None:
                raise AffordancePlanningError("commissioned_skills contains an invalid skill")
        if (
            not isinstance(self.capability_manifest_digest, str)
            or _DIGEST.fullmatch(self.capability_manifest_digest) is None
        ):
            raise AffordancePlanningError("capability_manifest_digest must be SHA-256")
        if not isinstance(self.excluded_operator_ids, frozenset):
            raise AffordancePlanningError("excluded_operator_ids must be an immutable frozenset")
        unknown_exclusions = self.excluded_operator_ids - set(operator_ids)
        if unknown_exclusions:
            raise AffordancePlanningError("excluded_operator_ids contains an unknown operator")
        if not isinstance(self.reliability, tuple):
            raise AffordancePlanningError("reliability must be an immutable tuple")
        if any(not isinstance(item, SkillReliabilityV1) for item in self.reliability):
            raise AffordancePlanningError("reliability must contain SkillReliabilityV1 values")
        reliability_keys = tuple(item.reliability_key for item in self.reliability)
        if len(set(reliability_keys)) != len(reliability_keys):
            raise AffordancePlanningError("reliability keys must be unique")
        known_keys = {item.reliability_key for item in self.operators}
        if not set(reliability_keys) <= known_keys:
            raise AffordancePlanningError("reliability contains a key with no grounded operator")
        _integer(self.max_steps, "max_steps", minimum=1, maximum=12)
        _integer(self.max_expansions, "max_expansions", minimum=1, maximum=100_000)
        _bounded_number(self.risk_weight, "risk_weight", minimum=0.0, maximum=1_000_000.0)
        _bounded_number(
            self.failure_weight,
            "failure_weight",
            minimum=0.0,
            maximum=1_000_000.0,
        )
        _bounded_number(
            self.minimum_reliability,
            "minimum_reliability",
            minimum=0.0,
            maximum=1.0,
        )

    @property
    def reliability_digest(self) -> str:
        return _canonical_digest(
            {
                "schema": "skill-reliability-table-v1",
                "rows": [
                    {
                        "reliability_key": item.reliability_key,
                        "successes": item.successes,
                        "failures": item.failures,
                        "safety_failures": item.safety_failures,
                    }
                    for item in sorted(self.reliability, key=lambda row: row.reliability_key)
                ],
            }
        )

    @property
    def problem_digest(self) -> str:
        return _canonical_digest(
            {
                "schema": "planning-problem-v1",
                "state_digest": self.state.state_digest,
                "goal_true": sorted(self.goal_true),
                "goal_false": sorted(self.goal_false),
                "operators": [
                    item.as_dict() for item in sorted(self.operators, key=lambda op: op.operator_id)
                ],
                "commissioned_skills": sorted(self.commissioned_skills),
                "capability_manifest_digest": self.capability_manifest_digest,
                "must_remain_true": sorted(self.must_remain_true),
                "forbidden_true": sorted(self.forbidden_true),
                "excluded_operator_ids": sorted(self.excluded_operator_ids),
                "reliability_digest": self.reliability_digest,
                "max_steps": self.max_steps,
                "max_expansions": self.max_expansions,
                "risk_weight": self.risk_weight,
                "failure_weight": self.failure_weight,
                "minimum_reliability": self.minimum_reliability,
            }
        )


@dataclass(frozen=True, slots=True)
class PlannedSkillV1:
    operator_id: str
    skill: str
    arguments: FrozenDict
    expected_true: frozenset[str]
    expected_false: frozenset[str]

    def __post_init__(self) -> None:
        _identifier(self.operator_id, "operator_id")
        if not isinstance(self.skill, str) or _SKILL.fullmatch(self.skill) is None:
            raise AffordancePlanningError("planned skill name is invalid")
        if not isinstance(self.arguments, FrozenDict):
            object.__setattr__(self, "arguments", FrozenDict(self.arguments))
        _fact_set(self.expected_true, "expected_true")
        _fact_set(self.expected_false, "expected_false")
        if self.expected_true & self.expected_false:
            raise AffordancePlanningError("a planned effect cannot be true and false")

    def as_dict(self) -> dict[str, object]:
        return {
            "operator_id": self.operator_id,
            "skill": self.skill,
            "arguments": self.arguments.to_dict(),
            "expected_true": sorted(self.expected_true),
            "expected_false": sorted(self.expected_false),
        }


@dataclass(frozen=True, slots=True)
class PlanProposalV1:
    status: str
    source_state_digest: str
    source_problem_digest: str
    capability_manifest_digest: str
    reliability_digest: str
    steps: tuple[PlannedSkillV1, ...]
    expected_true: frozenset[str]
    expected_false: frozenset[str]
    uncertain_facts: tuple[str, ...]
    total_cost: float
    expansions: int
    reason: str
    authorizes_motion: bool = False

    def __post_init__(self) -> None:
        if self.status not in PLAN_STATUSES:
            raise AffordancePlanningError("plan status is invalid")
        for field_name in (
            "source_state_digest",
            "source_problem_digest",
            "capability_manifest_digest",
            "reliability_digest",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
                raise AffordancePlanningError(f"{field_name} must be SHA-256")
        if not isinstance(self.steps, tuple) or any(
            not isinstance(item, PlannedSkillV1) for item in self.steps
        ):
            raise AffordancePlanningError("steps must be an immutable planned-skill tuple")
        if len(self.steps) > 12:
            raise AffordancePlanningError("a plan proposal cannot exceed 12 steps")
        if self.status == "planned" and not self.steps:
            raise AffordancePlanningError("a planned proposal must contain a step")
        if self.status != "planned" and self.steps:
            raise AffordancePlanningError("only a planned proposal may contain steps")
        _fact_set(self.expected_true, "expected_true")
        _fact_set(self.expected_false, "expected_false")
        if self.expected_true & self.expected_false:
            raise AffordancePlanningError("an expected fact cannot be true and false")
        if not isinstance(self.uncertain_facts, tuple):
            raise AffordancePlanningError("uncertain_facts must be an immutable tuple")
        if tuple(sorted(set(self.uncertain_facts))) != self.uncertain_facts:
            raise AffordancePlanningError("uncertain_facts must be unique and sorted")
        for fact in self.uncertain_facts:
            if _FACT.fullmatch(fact) is None:
                raise AffordancePlanningError("uncertain_facts contains an invalid fact")
        _bounded_number(self.total_cost, "total_cost", minimum=0.0, maximum=1.0e15)
        _integer(self.expansions, "expansions", minimum=0, maximum=100_000)
        if not isinstance(self.reason, str) or not self.reason or len(self.reason) > 256:
            raise AffordancePlanningError("reason must be bounded non-empty text")
        if type(self.authorizes_motion) is not bool:
            raise AffordancePlanningError("authorizes_motion must be a boolean")
        if self.authorizes_motion:
            raise AffordancePlanningError("an affordance plan never authorizes motion")

    @property
    def proposal_digest(self) -> str:
        return _canonical_digest(
            {
                "schema": "plan-proposal-v1",
                "status": self.status,
                "source_state_digest": self.source_state_digest,
                "source_problem_digest": self.source_problem_digest,
                "capability_manifest_digest": self.capability_manifest_digest,
                "reliability_digest": self.reliability_digest,
                "steps": [item.as_dict() for item in self.steps],
                "expected_true": sorted(self.expected_true),
                "expected_false": sorted(self.expected_false),
                "uncertain_facts": list(self.uncertain_facts),
                "total_cost": self.total_cost,
                "expansions": self.expansions,
                "reason": self.reason,
                "authorizes_motion": self.authorizes_motion,
            }
        )


@dataclass(frozen=True, slots=True)
class PlannerOutcomeV1:
    """Authenticated-executive-shaped evidence consumed by replanning.

    Authentication itself stays at the caller boundary.  This contract pins
    the exact receipt digest and a monotonically newer observation epoch.
    """

    operator_id: str
    status: str
    source_problem_digest: str
    observed_true: frozenset[str]
    observed_false: frozenset[str]
    observation_epoch: int
    receipt_digest: str

    def __post_init__(self) -> None:
        _identifier(self.operator_id, "operator_id")
        if self.status not in TERMINAL_OUTCOME_STATUSES:
            raise AffordancePlanningError("planner outcome must be terminal")
        if (
            not isinstance(self.source_problem_digest, str)
            or _DIGEST.fullmatch(self.source_problem_digest) is None
        ):
            raise AffordancePlanningError("source_problem_digest must be SHA-256")
        _fact_set(self.observed_true, "observed_true")
        _fact_set(self.observed_false, "observed_false")
        if self.observed_true & self.observed_false:
            raise AffordancePlanningError("an outcome fact cannot be true and false")
        _integer(self.observation_epoch, "observation_epoch", minimum=1, maximum=(1 << 63) - 1)
        if (
            not isinstance(self.receipt_digest, str)
            or _DIGEST.fullmatch(self.receipt_digest) is None
        ):
            raise AffordancePlanningError("receipt_digest must be a lowercase SHA-256 digest")


class AffordancePlannerV1:
    """Deterministic uniform-cost search with strict uncertainty handling."""

    def plan(self, problem: PlanningProblemV1) -> PlanProposalV1:
        if not isinstance(problem, PlanningProblemV1):
            raise TypeError("plan requires PlanningProblemV1")
        source_digest = problem.state.state_digest
        early_outcome = self._early_outcome(problem)
        if early_outcome is not None:
            return early_outcome

        reliability = {item.reliability_key: item for item in problem.reliability}
        operators = tuple(
            operator
            for operator in sorted(problem.operators, key=lambda item: item.operator_id)
            if self._operator_admitted(operator, problem, reliability)
        )
        if not operators:
            return self._empty(
                "unreachable",
                problem,
                reason="no commissioned, reliable, non-excluded operator is available",
            )

        initial_key = self._state_key(problem.state)
        frontier: list[
            tuple[
                float,
                int,
                tuple[str, ...],
                int,
                ConfirmedWorldStateV1,
                tuple[GroundedSkillV1, ...],
            ]
        ] = []
        serial = 0
        heapq.heappush(frontier, (0.0, 0, (), serial, problem.state, ()))
        best_cost: dict[tuple[frozenset[str], frozenset[str]], float] = {initial_key: 0.0}
        uncertain: set[str] = set()
        expansions = 0

        while frontier and expansions < problem.max_expansions:
            cost, depth, path_ids, _serial, state, path = heapq.heappop(frontier)
            state_key = self._state_key(state)
            if cost > best_cost.get(state_key, math.inf) + 1e-12:
                continue
            expansions += 1
            if self._goal_satisfied(problem, state):
                return PlanProposalV1(
                    status="planned",
                    source_state_digest=source_digest,
                    source_problem_digest=problem.problem_digest,
                    capability_manifest_digest=problem.capability_manifest_digest,
                    reliability_digest=problem.reliability_digest,
                    steps=tuple(self._planned_step(item) for item in path),
                    expected_true=state.confirmed_true,
                    expected_false=state.confirmed_false,
                    uncertain_facts=tuple(sorted(uncertain)),
                    total_cost=cost,
                    expansions=expansions,
                    reason="bounded search found a goal-satisfying semantic skill sequence",
                )
            if depth >= problem.max_steps:
                continue
            for operator in operators:
                if not operator.applicable(state):
                    uncertain.update(self._unknown_preconditions(operator, state))
                    continue
                next_state = state.predicted_transition(operator)
                if next_state.confirmed_true & problem.forbidden_true:
                    continue
                if not problem.must_remain_true <= next_state.confirmed_true:
                    continue
                step_cost = self._operator_cost(operator, problem, reliability)
                next_cost = cost + step_cost
                next_key = self._state_key(next_state)
                previous = best_cost.get(next_key)
                if previous is not None and next_cost >= previous - 1e-12:
                    continue
                best_cost[next_key] = next_cost
                serial += 1
                next_ids = (*path_ids, operator.operator_id)
                heapq.heappush(
                    frontier,
                    (
                        next_cost,
                        depth + 1,
                        next_ids,
                        serial,
                        next_state,
                        (*path, operator),
                    ),
                )

        return self._search_exhausted(problem, source_digest, bool(frontier), uncertain, expansions)

    def _early_outcome(self, problem: PlanningProblemV1) -> PlanProposalV1 | None:
        if problem.state.confirmed_true & problem.forbidden_true:
            return self._empty(
                "unsafe_state",
                problem,
                reason="confirmed world state violates a hard forbidden fact",
            )
        if self._goal_satisfied(problem, problem.state):
            return self._empty(
                "goal_satisfied",
                problem,
                reason="goal already satisfied by confirmed observations",
            )
        return None

    @staticmethod
    def _search_exhausted(
        problem: PlanningProblemV1,
        source_digest: str,
        frontier_remaining: bool,
        uncertain: set[str],
        expansions: int,
    ) -> PlanProposalV1:
        if frontier_remaining:
            status = "budget_exhausted"
            reason = "bounded search exhausted its expansion budget"
        elif uncertain:
            status = "needs_observation"
            reason = "goal depends on one or more unconfirmed preconditions"
        else:
            status = "unreachable"
            reason = "goal is unreachable under confirmed facts and admitted skills"
        return PlanProposalV1(
            status=status,
            source_state_digest=source_digest,
            source_problem_digest=problem.problem_digest,
            capability_manifest_digest=problem.capability_manifest_digest,
            reliability_digest=problem.reliability_digest,
            steps=(),
            expected_true=problem.state.confirmed_true,
            expected_false=problem.state.confirmed_false,
            uncertain_facts=tuple(sorted(uncertain)),
            total_cost=0.0,
            expansions=expansions,
            reason=reason,
        )

    def replan_after_outcome(
        self,
        problem: PlanningProblemV1,
        outcome: PlannerOutcomeV1,
    ) -> PlanProposalV1:
        """Replan from observed receipt facts without assuming predicted effects."""

        if not isinstance(problem, PlanningProblemV1):
            raise TypeError("replan requires PlanningProblemV1")
        if not isinstance(outcome, PlannerOutcomeV1):
            raise TypeError("replan requires PlannerOutcomeV1")
        operator_ids = {item.operator_id for item in problem.operators}
        if outcome.source_problem_digest != problem.problem_digest:
            raise AffordancePlanningError("outcome is not bound to this exact planning problem")
        if outcome.operator_id not in operator_ids:
            raise AffordancePlanningError("outcome names an operator outside the problem")
        observed_state = problem.state.with_outcome(outcome)
        # A terminal grounded instance must not be selected a second time in
        # the same revision.  Repeated semantic skills use distinct operator
        # IDs, which keeps retries explicit and bounded.
        excluded = problem.excluded_operator_ids | frozenset({outcome.operator_id})
        return self.plan(replace(problem, state=observed_state, excluded_operator_ids=excluded))

    @staticmethod
    def _goal_satisfied(problem: PlanningProblemV1, state: ConfirmedWorldStateV1) -> bool:
        return problem.goal_true <= state.confirmed_true and problem.goal_false <= (
            state.confirmed_false
        )

    @staticmethod
    def _state_key(
        state: ConfirmedWorldStateV1,
    ) -> tuple[frozenset[str], frozenset[str]]:
        return state.confirmed_true, state.confirmed_false

    @staticmethod
    def _unknown_preconditions(
        operator: GroundedSkillV1,
        state: ConfirmedWorldStateV1,
    ) -> frozenset[str]:
        missing_true = operator.requires_true - state.confirmed_true
        missing_false = operator.requires_false - state.confirmed_false
        contradicted_true = missing_true & state.confirmed_false
        contradicted_false = missing_false & state.confirmed_true
        return (missing_true - contradicted_true) | (missing_false - contradicted_false)

    @staticmethod
    def _operator_admitted(
        operator: GroundedSkillV1,
        problem: PlanningProblemV1,
        reliability: dict[str, SkillReliabilityV1],
    ) -> bool:
        if operator.skill not in problem.commissioned_skills:
            return False
        if operator.operator_id in problem.excluded_operator_ids:
            return False
        estimate = reliability.get(operator.reliability_key)
        if estimate is None:
            return problem.minimum_reliability <= 0.0
        if estimate.safety_failures:
            return False
        return estimate.posterior_success >= problem.minimum_reliability

    @staticmethod
    def _operator_cost(
        operator: GroundedSkillV1,
        problem: PlanningProblemV1,
        reliability: dict[str, SkillReliabilityV1],
    ) -> float:
        estimate = reliability.get(operator.reliability_key)
        success = 0.5 if estimate is None else estimate.posterior_success
        return (
            operator.base_cost
            + problem.risk_weight * operator.risk
            + problem.failure_weight * (1.0 - success)
        )

    @staticmethod
    def _planned_step(operator: GroundedSkillV1) -> PlannedSkillV1:
        return PlannedSkillV1(
            operator_id=operator.operator_id,
            skill=operator.skill,
            arguments=operator.arguments,
            expected_true=operator.predicts_true,
            expected_false=operator.predicts_false,
        )

    @staticmethod
    def _empty(
        status: str,
        problem: PlanningProblemV1,
        *,
        reason: str,
    ) -> PlanProposalV1:
        return PlanProposalV1(
            status=status,
            source_state_digest=problem.state.state_digest,
            source_problem_digest=problem.problem_digest,
            capability_manifest_digest=problem.capability_manifest_digest,
            reliability_digest=problem.reliability_digest,
            steps=(),
            expected_true=problem.state.confirmed_true,
            expected_false=problem.state.confirmed_false,
            uncertain_facts=(),
            total_cost=0.0,
            expansions=0,
            reason=reason,
        )


__all__ = [
    "PLAN_STATUSES",
    "TERMINAL_OUTCOME_STATUSES",
    "AffordancePlannerV1",
    "AffordancePlanningError",
    "ConfirmedWorldStateV1",
    "GroundedSkillV1",
    "PlanProposalV1",
    "PlannedSkillV1",
    "PlannerOutcomeV1",
    "PlanningProblemV1",
    "SkillReliabilityV1",
]
