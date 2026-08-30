"""Goal-relevant uncertainty attribution for bounded semantic planning.

V1 remains the frozen implementation evaluated by ``SIM-PLAN-1``.  This
module is an additive proposal-only follow-up.  It reuses V1's confirmed-fact
search and contracts, then performs a second bounded reachability pass only
when the confirmed search cannot find a plan.  That pass may optimistically
assume the required value of an *explicitly bound, currently unknown,
externally observable* fact.  ``needs_observation`` is returned only if those
assumptions support a complete commissioned, reliability-admitted, invariant-
preserving, goal-reaching chain.

Neither an optimistic chain nor a returned proposal dispatches a skill or
authorizes motion.  Predicted effects remain search state, not observations.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import re
from dataclasses import dataclass, field, replace

from .affordance_planner import (
    AffordancePlannerV1,
    AffordancePlanningError,
    ConfirmedWorldStateV1,
    GroundedSkillV1,
    PlannerOutcomeV1,
    PlanningProblemV1,
    PlanProposalV1,
    SkillReliabilityV1,
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class PlanningProblemV2(PlanningProblemV1):
    """V1 planning inputs plus an exact externally-observable fact boundary."""

    externally_observable_facts: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        PlanningProblemV1.__post_init__(self)
        if not isinstance(self.externally_observable_facts, frozenset):
            raise AffordancePlanningError(
                "externally_observable_facts must be an immutable frozenset"
            )
        # Reuse the V1 fact grammar and cardinality validation rather than
        # creating a subtly different fact namespace in the follow-up.
        ConfirmedWorldStateV1(
            self.externally_observable_facts,
            frozenset(),
            observation_epoch=0,
        )
        vocabulary = (
            self.state.confirmed_true
            | self.state.confirmed_false
            | self.goal_true
            | self.goal_false
            | self.must_remain_true
            | self.forbidden_true
        )
        for operator in self.operators:
            vocabulary |= (
                operator.requires_true
                | operator.requires_false
                | operator.predicts_true
                | operator.predicts_false
            )
        unknown = self.externally_observable_facts - vocabulary
        if unknown:
            raise AffordancePlanningError(
                "externally_observable_facts contains a fact outside the problem vocabulary"
            )

    def as_v1(self) -> PlanningProblemV1:
        """Return the exact V1 search inputs, excluding only the V2 boundary."""

        return PlanningProblemV1(
            state=self.state,
            goal_true=self.goal_true,
            goal_false=self.goal_false,
            operators=self.operators,
            commissioned_skills=self.commissioned_skills,
            capability_manifest_digest=self.capability_manifest_digest,
            must_remain_true=self.must_remain_true,
            forbidden_true=self.forbidden_true,
            excluded_operator_ids=self.excluded_operator_ids,
            reliability=self.reliability,
            max_steps=self.max_steps,
            max_expansions=self.max_expansions,
            risk_weight=self.risk_weight,
            failure_weight=self.failure_weight,
            minimum_reliability=self.minimum_reliability,
        )

    @property
    def observable_facts_digest(self) -> str:
        return _canonical_digest(
            {
                "schema": "externally-observable-facts-v2",
                "facts": sorted(self.externally_observable_facts),
            }
        )

    @property
    def problem_digest(self) -> str:
        return _canonical_digest(
            {
                "schema": "planning-problem-v2",
                "planning_problem_v1_digest": self.as_v1().problem_digest,
                "observable_facts_digest": self.observable_facts_digest,
            }
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanProposalV2(PlanProposalV1):
    """A V1-safe proposal additionally bound to the observable-fact set."""

    observable_facts_digest: str

    def __post_init__(self) -> None:
        PlanProposalV1.__post_init__(self)
        if (
            not isinstance(self.observable_facts_digest, str)
            or _DIGEST.fullmatch(self.observable_facts_digest) is None
        ):
            raise AffordancePlanningError("observable_facts_digest must be SHA-256")

    def as_v1(self) -> PlanProposalV1:
        return PlanProposalV1(
            status=self.status,
            source_state_digest=self.source_state_digest,
            source_problem_digest=self.source_problem_digest,
            capability_manifest_digest=self.capability_manifest_digest,
            reliability_digest=self.reliability_digest,
            steps=self.steps,
            expected_true=self.expected_true,
            expected_false=self.expected_false,
            uncertain_facts=self.uncertain_facts,
            total_cost=self.total_cost,
            expansions=self.expansions,
            reason=self.reason,
            authorizes_motion=self.authorizes_motion,
        )

    @property
    def proposal_digest(self) -> str:
        return _canonical_digest(
            {
                "schema": "plan-proposal-v2",
                "plan_proposal_v1_digest": self.as_v1().proposal_digest,
                "observable_facts_digest": self.observable_facts_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class _OptimisticResult:
    status: str
    uncertain_facts: tuple[str, ...]
    expansions: int


class AffordancePlannerV2:
    """V1 confirmed search plus bounded goal-relevant observation proof."""

    def plan(self, problem: PlanningProblemV2) -> PlanProposalV2:
        if not isinstance(problem, PlanningProblemV2):
            raise TypeError("plan requires PlanningProblemV2")

        confirmed = AffordancePlannerV1().plan(problem.as_v1())
        if confirmed.status in {
            "planned",
            "goal_satisfied",
            "unsafe_state",
            "budget_exhausted",
        }:
            # A real plan contains only confirmed preconditions.  V1's
            # incidental unknown accumulator is not part of that plan proof.
            uncertain = () if confirmed.status == "planned" else confirmed.uncertain_facts
            return self._from_v1(problem, confirmed, uncertain_facts=uncertain)

        remaining_expansions = problem.max_expansions - confirmed.expansions
        if remaining_expansions <= 0:
            return self._empty(
                "budget_exhausted",
                problem,
                expansions=problem.max_expansions,
                reason="bounded searches exhausted the shared expansion budget",
            )

        optimistic = self._goal_relevant_observations(
            problem,
            max_expansions=remaining_expansions,
        )
        total_expansions = confirmed.expansions + optimistic.expansions
        if optimistic.status == "needs_observation":
            return self._empty(
                "needs_observation",
                problem,
                expansions=total_expansions,
                uncertain_facts=optimistic.uncertain_facts,
                reason=(
                    "an observable unknown enables a complete admitted safe goal chain"
                ),
            )
        if optimistic.status == "budget_exhausted":
            return self._empty(
                "budget_exhausted",
                problem,
                expansions=total_expansions,
                reason="goal-relevance proof exhausted the shared expansion budget",
            )
        return self._empty(
            "unreachable",
            problem,
            expansions=total_expansions,
            reason=(
                "no confirmed or observably enabled admitted safe chain reaches the goal"
            ),
        )

    def replan_after_outcome(
        self,
        problem: PlanningProblemV2,
        outcome: PlannerOutcomeV1,
    ) -> PlanProposalV2:
        """Replan only from a newer receipt bound to this exact V2 problem."""

        if not isinstance(problem, PlanningProblemV2):
            raise TypeError("replan requires PlanningProblemV2")
        if not isinstance(outcome, PlannerOutcomeV1):
            raise TypeError("replan requires PlannerOutcomeV1")
        if outcome.source_problem_digest != problem.problem_digest:
            raise AffordancePlanningError("outcome is not bound to this exact V2 problem")
        operator_ids = {item.operator_id for item in problem.operators}
        if outcome.operator_id not in operator_ids:
            raise AffordancePlanningError("outcome names an operator outside the problem")
        observed_state = problem.state.with_outcome(outcome)
        excluded = problem.excluded_operator_ids | frozenset({outcome.operator_id})
        return self.plan(replace(problem, state=observed_state, excluded_operator_ids=excluded))

    @staticmethod
    def _admitted_operators(
        problem: PlanningProblemV2,
    ) -> tuple[GroundedSkillV1, ...]:
        reliability = {item.reliability_key: item for item in problem.reliability}
        admitted = []
        for operator in sorted(problem.operators, key=lambda item: item.operator_id):
            if operator.skill not in problem.commissioned_skills:
                continue
            if operator.operator_id in problem.excluded_operator_ids:
                continue
            estimate = reliability.get(operator.reliability_key)
            if estimate is None:
                if problem.minimum_reliability > 0.0:
                    continue
            elif (
                estimate.safety_failures
                or estimate.posterior_success < problem.minimum_reliability
            ):
                continue
            admitted.append(operator)
        return tuple(admitted)

    @staticmethod
    def _operator_cost(
        operator: GroundedSkillV1,
        problem: PlanningProblemV2,
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
    def _observation_requirements(
        problem: PlanningProblemV2,
        state: ConfirmedWorldStateV1,
        required_true: frozenset[str],
        required_false: frozenset[str],
    ) -> frozenset[tuple[str, bool]] | None:
        """Return assumptions for unknown observables, or ``None`` if blocked."""

        missing_true = required_true - state.confirmed_true
        missing_false = required_false - state.confirmed_false
        if missing_true & state.confirmed_false:
            return None
        if missing_false & state.confirmed_true:
            return None
        unknown_true = missing_true - state.confirmed_false
        unknown_false = missing_false - state.confirmed_true
        if not (unknown_true | unknown_false) <= problem.externally_observable_facts:
            return None
        if unknown_true & problem.forbidden_true:
            return None
        return frozenset(
            [(fact, True) for fact in unknown_true]
            + [(fact, False) for fact in unknown_false]
        )

    @staticmethod
    def _apply_observations(
        state: ConfirmedWorldStateV1,
        requirements: frozenset[tuple[str, bool]],
    ) -> ConfirmedWorldStateV1:
        observed_true = frozenset(fact for fact, value in requirements if value)
        observed_false = frozenset(fact for fact, value in requirements if not value)
        return ConfirmedWorldStateV1(
            state.confirmed_true | observed_true,
            state.confirmed_false | observed_false,
            state.observation_epoch,
        )

    def _goal_relevant_observations(
        self,
        problem: PlanningProblemV2,
        *,
        max_expansions: int,
    ) -> _OptimisticResult:
        reliability = {item.reliability_key: item for item in problem.reliability}
        operators = self._admitted_operators(problem)
        observation_set = frozenset[tuple[str, bool]]
        score = tuple[int, float, int, tuple[str, ...], tuple[tuple[str, bool], ...]]
        frontier: list[
            tuple[
                score,
                int,
                ConfirmedWorldStateV1,
                observation_set,
            ]
        ] = []
        initial_observations: observation_set = frozenset()
        initial_score: score = (0, 0.0, 0, (), ())
        heapq.heappush(frontier, (initial_score, 0, problem.state, initial_observations))
        state_key = tuple[frozenset[str], frozenset[str]]
        best: dict[state_key, score] = {
            (problem.state.confirmed_true, problem.state.confirmed_false): initial_score
        }
        serial = 0
        expansions = 0

        while frontier and expansions < max_expansions:
            current_score, _serial, state, observations = heapq.heappop(frontier)
            key = (state.confirmed_true, state.confirmed_false)
            if current_score != best.get(key):
                continue
            expansions += 1
            _, cost, depth, path_ids, _observation_order = current_score

            goal_requirements = self._observation_requirements(
                problem,
                state,
                problem.goal_true,
                problem.goal_false,
            )
            if goal_requirements is not None:
                goal_observations = observations | goal_requirements
                if goal_observations:
                    return _OptimisticResult(
                        "needs_observation",
                        tuple(sorted(fact for fact, _value in goal_observations)),
                        expansions,
                    )

            if depth >= problem.max_steps:
                continue
            for operator in operators:
                requirements = self._observation_requirements(
                    problem,
                    state,
                    operator.requires_true,
                    operator.requires_false,
                )
                if requirements is None:
                    continue
                observed_state = self._apply_observations(state, requirements)
                if observed_state.confirmed_true & problem.forbidden_true:
                    continue
                next_state = observed_state.predicted_transition(operator)
                if next_state.confirmed_true & problem.forbidden_true:
                    continue
                if not problem.must_remain_true <= next_state.confirmed_true:
                    continue
                next_observations = observations | requirements
                next_cost = cost + self._operator_cost(operator, problem, reliability)
                next_ids = (*path_ids, operator.operator_id)
                ordered_observations = tuple(sorted(next_observations))
                next_score: score = (
                    len(next_observations),
                    next_cost,
                    depth + 1,
                    next_ids,
                    ordered_observations,
                )
                next_key = (next_state.confirmed_true, next_state.confirmed_false)
                previous = best.get(next_key)
                if previous is not None and previous <= next_score:
                    continue
                best[next_key] = next_score
                serial += 1
                heapq.heappush(
                    frontier,
                    (next_score, serial, next_state, next_observations),
                )

        if frontier:
            return _OptimisticResult("budget_exhausted", (), expansions)
        return _OptimisticResult("unreachable", (), expansions)

    @staticmethod
    def _from_v1(
        problem: PlanningProblemV2,
        proposal: PlanProposalV1,
        *,
        uncertain_facts: tuple[str, ...],
    ) -> PlanProposalV2:
        return PlanProposalV2(
            status=proposal.status,
            source_state_digest=problem.state.state_digest,
            source_problem_digest=problem.problem_digest,
            capability_manifest_digest=problem.capability_manifest_digest,
            reliability_digest=problem.reliability_digest,
            observable_facts_digest=problem.observable_facts_digest,
            steps=proposal.steps,
            expected_true=proposal.expected_true,
            expected_false=proposal.expected_false,
            uncertain_facts=uncertain_facts,
            total_cost=proposal.total_cost,
            expansions=proposal.expansions,
            reason=proposal.reason,
            authorizes_motion=False,
        )

    @staticmethod
    def _empty(
        status: str,
        problem: PlanningProblemV2,
        *,
        expansions: int,
        reason: str,
        uncertain_facts: tuple[str, ...] = (),
    ) -> PlanProposalV2:
        return PlanProposalV2(
            status=status,
            source_state_digest=problem.state.state_digest,
            source_problem_digest=problem.problem_digest,
            capability_manifest_digest=problem.capability_manifest_digest,
            reliability_digest=problem.reliability_digest,
            observable_facts_digest=problem.observable_facts_digest,
            steps=(),
            expected_true=problem.state.confirmed_true,
            expected_false=problem.state.confirmed_false,
            uncertain_facts=uncertain_facts,
            total_cost=0.0,
            expansions=expansions,
            reason=reason,
            authorizes_motion=False,
        )


__all__ = [
    "AffordancePlannerV2",
    "PlanProposalV2",
    "PlanningProblemV2",
]
