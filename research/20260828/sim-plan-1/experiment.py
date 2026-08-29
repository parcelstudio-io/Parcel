"""Deterministic authored-symbolic shadow evaluation for AffordancePlannerV1.

This is not a physics simulator, learned policy evaluation, perception test,
commissioning record, or motion authorization.  It measures only whether the
proposal-only planner can compose system-authored symbolic operators on a
frozen held-out fixture set more effectively than fixed plan templates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from parcel_robot.brain.affordance_planner import (
    AffordancePlannerV1,
    ConfirmedWorldStateV1,
    GroundedSkillV1,
    PlanningProblemV1,
    SkillReliabilityV1,
)
from parcel_robot.brain.contracts import FrozenDict

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
FIXTURE_PATH = HERE / "fixtures.json"
PLANNER_PATH = REPO_ROOT / "src/parcel_robot/brain/affordance_planner.py"

DETERMINISTIC_KEYS = (
    "schema",
    "evidence_class",
    "preregistered_hypotheses",
    "counts",
    "metrics",
    "checks",
    "verdicts",
    "overall_verdict",
    "source_hashes",
    "rows",
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ordered_union(first: Iterable[str], second: Iterable[str]) -> list[str]:
    result: list[str] = []
    for item in (*first, *second):
        if item not in result:
            result.append(item)
    return result


def _mutated_set(
    base: Iterable[str],
    *,
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
) -> frozenset[str]:
    return frozenset((set(base) | set(add)) - set(remove))


def _operator(operator_id: str, row: dict[str, Any]) -> GroundedSkillV1:
    return GroundedSkillV1(
        operator_id=operator_id,
        skill=row["skill"],
        arguments=FrozenDict({"shadow_fixture": operator_id}),
        requires_true=frozenset(row.get("requires_true", ())),
        requires_false=frozenset(row.get("requires_false", ())),
        predicts_true=frozenset(row.get("predicts_true", ())),
        predicts_false=frozenset(row.get("predicts_false", ())),
        base_cost=row.get("base_cost", 1.0),
        risk=row.get("risk", 0.0),
        reliability_key=row.get("reliability_key", operator_id),
    )


def _build_problem(
    fixture: dict[str, Any],
    mission: dict[str, Any],
    operator_order: tuple[str, ...],
) -> PlanningProblemV1:
    profile = fixture["profiles"][mission["profile"]]
    base_state = fixture["base_state"]
    confirmed_true = _mutated_set(
        base_state["confirmed_true"],
        add=mission.get("confirmed_true_add", ()),
        remove=mission.get("confirmed_true_remove", ()),
    )
    confirmed_false = _mutated_set(
        base_state["confirmed_false"],
        add=mission.get("confirmed_false_add", ()),
        remove=mission.get("confirmed_false_remove", ()),
    )
    if confirmed_true & confirmed_false:
        raise AssertionError(f"{mission['id']} fixture has contradictory facts")

    catalog = fixture["operator_catalog"]
    operators = tuple(_operator(operator_id, catalog[operator_id]) for operator_id in operator_order)
    commissioned = {operator.skill for operator in operators}
    commissioned -= set(mission.get("commissioned_skills_remove", ()))
    commissioned |= set(mission.get("commissioned_skills_add", ()))
    shadow_manifest_digest = _digest(
        {
            "schema": "authored-shadow-capability-set-v1",
            "commissioned_skills": sorted(commissioned),
            "warning": "not_an_authenticated_commissioning_record",
        }
    )
    reliability = tuple(
        SkillReliabilityV1(
            reliability_key=row["reliability_key"],
            successes=row["successes"],
            failures=row["failures"],
            safety_failures=row.get("safety_failures", 0),
        )
        for row in mission.get("reliability", ())
    )
    return PlanningProblemV1(
        state=ConfirmedWorldStateV1(confirmed_true, confirmed_false, observation_epoch=1),
        goal_true=_mutated_set(
            profile["goal_true"], add=mission.get("goal_true_add", ())
        ),
        goal_false=frozenset(mission.get("goal_false", ())),
        operators=operators,
        commissioned_skills=frozenset(commissioned),
        capability_manifest_digest=shadow_manifest_digest,
        must_remain_true=frozenset(mission.get("must_remain_true", ())),
        forbidden_true=frozenset(mission.get("forbidden_true", ())),
        excluded_operator_ids=frozenset(mission.get("excluded_operator_ids", ())),
        reliability=reliability,
        max_steps=mission.get("max_steps", 12),
        max_expansions=mission.get("max_expansions", 4_096),
        risk_weight=mission.get("risk_weight", 10.0),
        failure_weight=mission.get("failure_weight", 2.0),
        minimum_reliability=mission.get("minimum_reliability", 0.0),
    )


def _evaluate_sequence(problem: PlanningProblemV1, step_ids: Iterable[str]) -> dict[str, Any]:
    """Shadow-interpret predicted effects; never execute or authorize a skill."""

    proposed_steps = list(step_ids)
    operators = {item.operator_id: item for item in problem.operators}
    reliability = {item.reliability_key: item for item in problem.reliability}
    state = problem.state
    failure: str | None = None
    initial_unsafe_state = bool(state.confirmed_true & problem.forbidden_true)
    # An unsafe observation belongs to the fixture, not to a planner that
    # returns no steps.  A baseline that still proposes a template in that
    # state does incur a shadow proposal violation.
    hard_safety_violation = initial_unsafe_state and bool(proposed_steps)
    admission_violation = False
    precondition_violation = False
    applied: list[str] = []

    if initial_unsafe_state:
        failure = "initial_forbidden_fact"
    for operator_id in proposed_steps:
        if failure is not None:
            break
        operator = operators.get(operator_id)
        if operator is None:
            failure = "operator_not_grounded"
            admission_violation = True
            break
        estimate = reliability.get(operator.reliability_key)
        reliability_blocked = bool(
            estimate
            and (
                estimate.safety_failures
                or estimate.posterior_success < problem.minimum_reliability
            )
        )
        if (
            operator.skill not in problem.commissioned_skills
            or operator_id in problem.excluded_operator_ids
            or reliability_blocked
        ):
            failure = "operator_not_admitted"
            admission_violation = True
            break
        if not operator.applicable(state):
            failure = "precondition_not_confirmed"
            precondition_violation = True
            break
        next_state = state.predicted_transition(operator)
        if next_state.confirmed_true & problem.forbidden_true:
            failure = "predicted_forbidden_fact"
            hard_safety_violation = True
            break
        if not problem.must_remain_true <= next_state.confirmed_true:
            failure = "preserved_fact_removed"
            hard_safety_violation = True
            break
        state = next_state
        applied.append(operator_id)

    goal_satisfied = (
        problem.goal_true <= state.confirmed_true
        and problem.goal_false <= state.confirmed_false
    )
    valid_goal_plan = failure is None and goal_satisfied
    if failure is None and not goal_satisfied:
        failure = "goal_not_satisfied"
    return {
        "valid_goal_plan": valid_goal_plan,
        "goal_satisfied": goal_satisfied,
        "failure": failure,
        "hard_safety_violation": hard_safety_violation,
        "initial_unsafe_state": initial_unsafe_state,
        "admission_violation": admission_violation,
        "precondition_violation": precondition_violation,
        "applied_steps": applied,
    }


def _orders(operator_ids: list[str], mission_index: int) -> tuple[tuple[str, ...], ...]:
    canonical = tuple(operator_ids)
    reverse = tuple(reversed(operator_ids))
    offset = 1 + (mission_index % len(operator_ids))
    offset %= len(operator_ids)
    rotated_list = operator_ids[offset:] + operator_ids[:offset]
    rotated = tuple(rotated_list)
    return canonical, reverse, rotated


def run_experiment() -> dict[str, Any]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    planner = AffordancePlannerV1()
    rows: list[dict[str, Any]] = []

    for mission_index, mission in enumerate(fixture["held_out_missions"]):
        profile = fixture["profiles"][mission["profile"]]
        operator_ids = _ordered_union(
            profile["operator_ids"], mission.get("operator_ids_add", ())
        )
        proposals = []
        problems = []
        for order in _orders(operator_ids, mission_index):
            problem = _build_problem(fixture, mission, order)
            problems.append(problem)
            proposals.append(planner.plan(problem))

        problem = problems[0]
        proposal = proposals[0]
        planner_step_ids = [item.operator_id for item in proposal.steps]
        planner_eval = _evaluate_sequence(problem, planner_step_ids)
        expected_status = mission["expected_status"]
        if expected_status == "planned":
            disposition_correct = proposal.status == "planned" and planner_eval["valid_goal_plan"]
        else:
            disposition_correct = proposal.status == expected_status and not proposal.steps

        profile_template = fixture["development_templates"][profile["template_key"]]
        baseline_eval = _evaluate_sequence(problem, profile_template)
        baseline_disposition_correct = expected_status == "planned" and baseline_eval[
            "valid_goal_plan"
        ]
        critical_unknown = mission.get("critical_unknown")
        unknown_check = critical_unknown is None or critical_unknown in proposal.uncertain_facts
        binding_checks = [
            item.source_problem_digest == source_problem.problem_digest
            and item.capability_manifest_digest
            == source_problem.capability_manifest_digest
            and item.reliability_digest == source_problem.reliability_digest
            and item.source_state_digest == source_problem.state.state_digest
            for item, source_problem in zip(proposals, problems, strict=True)
        ]
        proposal_digests = [item.proposal_digest for item in proposals]
        rows.append(
            {
                "mission_id": mission["id"],
                "category": mission["category"],
                "template_key": profile["template_key"],
                "expected_status": expected_status,
                "planner": {
                    "status": proposal.status,
                    "steps": planner_step_ids,
                    "valid_goal_plan": planner_eval["valid_goal_plan"],
                    "disposition_correct": disposition_correct,
                    "failure": planner_eval["failure"],
                    "hard_safety_violation": planner_eval["hard_safety_violation"],
                    "admission_violation": planner_eval["admission_violation"],
                    "authorizes_motion": proposal.authorizes_motion,
                    "critical_unknown_included": unknown_check,
                    "uncertain_facts": list(proposal.uncertain_facts),
                    "problem_binding_valid_all_orders": all(binding_checks),
                    "operator_order_invariant": len(set(proposal_digests)) == 1,
                    "proposal_digest": proposal.proposal_digest,
                    "expansions": proposal.expansions,
                },
                "fixed_template_baseline": {
                    "steps": profile_template,
                    "valid_goal_plan": baseline_eval["valid_goal_plan"],
                    "disposition_correct": baseline_disposition_correct,
                    "failure": baseline_eval["failure"],
                    "hard_safety_violation": baseline_eval["hard_safety_violation"],
                    "admission_violation": baseline_eval["admission_violation"],
                    "precondition_violation": baseline_eval["precondition_violation"],
                    "authorizes_motion": False,
                },
            }
        )

    planned = [row for row in rows if row["expected_status"] == "planned"]
    negative = [row for row in rows if row["expected_status"] != "planned"]
    total = len(rows)
    planner_solved = sum(row["planner"]["valid_goal_plan"] for row in planned)
    baseline_solved = sum(
        row["fixed_template_baseline"]["valid_goal_plan"] for row in planned
    )
    planner_correct = sum(row["planner"]["disposition_correct"] for row in rows)
    baseline_correct = sum(
        row["fixed_template_baseline"]["disposition_correct"] for row in rows
    )
    planner_solve_rate = planner_solved / len(planned)
    baseline_solve_rate = baseline_solved / len(planned)
    planner_disposition_accuracy = planner_correct / total
    baseline_disposition_accuracy = baseline_correct / total
    planner_safety_violations = sum(
        row["planner"]["hard_safety_violation"] for row in rows
    )
    planner_admission_violations = sum(
        row["planner"]["admission_violation"] for row in rows
    )
    baseline_safety_violations = sum(
        row["fixed_template_baseline"]["hard_safety_violation"] for row in rows
    )
    baseline_admission_violations = sum(
        row["fixed_template_baseline"]["admission_violation"] for row in rows
    )

    metrics = {
        "planner_planned_mission_solve_rate": round(planner_solve_rate, 6),
        "fixed_template_planned_mission_solve_rate": round(baseline_solve_rate, 6),
        "planned_mission_solve_rate_delta": round(
            planner_solve_rate - baseline_solve_rate, 6
        ),
        "planner_exact_disposition_accuracy": round(planner_disposition_accuracy, 6),
        "fixed_template_exact_disposition_accuracy": round(
            baseline_disposition_accuracy, 6
        ),
        "exact_disposition_accuracy_delta": round(
            planner_disposition_accuracy - baseline_disposition_accuracy, 6
        ),
        "planner_hard_safety_violations": planner_safety_violations,
        "planner_admission_violations": planner_admission_violations,
        "fixed_template_hard_safety_violations": baseline_safety_violations,
        "fixed_template_admission_violations": baseline_admission_violations,
    }
    checks = {
        "all_fixtures_marked_held_out": all(
            row["category"].startswith("heldout_") for row in rows
        ),
        "planner_never_authorizes_motion": all(
            row["planner"]["authorizes_motion"] is False for row in rows
        ),
        "baseline_never_authorizes_motion": all(
            row["fixed_template_baseline"]["authorizes_motion"] is False
            for row in rows
        ),
        "planner_problem_bindings_valid": all(
            row["planner"]["problem_binding_valid_all_orders"] for row in rows
        ),
        "planner_operator_order_invariant": all(
            row["planner"]["operator_order_invariant"] for row in rows
        ),
        "critical_unknowns_reported": all(
            row["planner"]["critical_unknown_included"] for row in rows
        ),
    }
    hypotheses = {
        "H1": {
            "claim": "bounded composition solves >=90% of planned held-out missions, improves by >=40 percentage points over fixed templates, and creates no hard-safety or admission violation",
            "gates": {
                "planner_solve_rate_gte_0_90": planner_solve_rate >= 0.90,
                "solve_rate_delta_gte_0_40": planner_solve_rate - baseline_solve_rate >= 0.40,
                "zero_planner_hard_safety_violations": planner_safety_violations == 0,
                "zero_planner_admission_violations": planner_admission_violations == 0,
            },
        },
        "H2": {
            "claim": "typed disposition accuracy is >=90% and improves by >=50 percentage points over a fixed-template baseline",
            "gates": {
                "planner_disposition_accuracy_gte_0_90": planner_disposition_accuracy >= 0.90,
                "disposition_accuracy_delta_gte_0_50": (
                    planner_disposition_accuracy - baseline_disposition_accuracy >= 0.50
                ),
                "all_critical_unknowns_reported": checks["critical_unknowns_reported"],
            },
        },
        "H3": {
            "claim": "all proposals are order-invariant, bound to the exact shadow problem inputs, and non-authoritative",
            "gates": {
                "operator_order_invariant": checks["planner_operator_order_invariant"],
                "exact_problem_bindings": checks["planner_problem_bindings_valid"],
                "never_authorizes_motion": checks["planner_never_authorizes_motion"],
            },
        },
    }
    verdicts = {
        key: {
            "verdict": "SUPPORTED_SHADOW" if all(value["gates"].values()) else "REFUTED",
            "passed_gates": sum(value["gates"].values()),
            "total_gates": len(value["gates"]),
        }
        for key, value in hypotheses.items()
    }
    result: dict[str, Any] = {
        "schema": "parcel.sim-plan-1.results.v1",
        "evidence_class": "authored_symbolic_shadow_only_no_physics_no_hardware_no_motion",
        "preregistered_hypotheses": hypotheses,
        "counts": {
            "held_out_missions": total,
            "planned_missions": len(planned),
            "typed_nonplan_missions": len(negative),
            "planner_evaluations": total * 3,
            "fixed_template_evaluations": total,
        },
        "metrics": metrics,
        "checks": checks,
        "verdicts": verdicts,
        "overall_verdict": (
            "SUPPORTED_SHADOW"
            if all(item["verdict"] == "SUPPORTED_SHADOW" for item in verdicts.values())
            else "PARTIALLY_SUPPORTED_SHADOW"
        ),
        "source_hashes": {
            "fixtures_sha256": _file_digest(FIXTURE_PATH),
            "experiment_sha256": _file_digest(Path(__file__).resolve()),
            "affordance_planner_sha256": _file_digest(PLANNER_PATH),
        },
        "rows": rows,
    }
    result["deterministic_payload_sha256"] = _digest(
        {key: result[key] for key in DETERMINISTIC_KEYS}
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    result = run_experiment()
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(args.out),
        "overall_verdict": result["overall_verdict"],
        "metrics": result["metrics"],
        "deterministic_payload_sha256": result["deterministic_payload_sha256"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
