"""Deterministic SIM-PLAN-1 regression replay for AffordancePlannerV2.

This harness imports the frozen SIM-PLAN-1 builders and shadow interpreter,
then adds the V2 observable-fact contract. It never invokes or authorizes a
skill and provides no physics, hardware, or learned-policy evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from parcel_robot.brain.affordance_planner_v2 import (
    AffordancePlannerV2,
    PlanningProblemV2,
)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SIM_PLAN_1 = HERE.parent / "sim-plan-1"
FIXTURE_PATH = SIM_PLAN_1 / "fixtures.json"
OBSERVABILITY_PATH = HERE / "observability.json"
V1_EXPERIMENT_PATH = SIM_PLAN_1 / "experiment.py"
V1_RESULTS_PATH = SIM_PLAN_1 / "results.json"
V1_PLANNER_PATH = REPO_ROOT / "src/parcel_robot/brain/affordance_planner.py"
V2_PLANNER_PATH = REPO_ROOT / "src/parcel_robot/brain/affordance_planner_v2.py"
REGRESSION_IDS = (
    "greet-camera-false",
    "greet-scan-uncommissioned",
    "follow-consent-false",
)

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


def _load_v1_experiment() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "parcel_frozen_sim_plan_1_experiment",
        V1_EXPERIMENT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the frozen SIM-PLAN-1 harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _as_v2(problem: Any, observable_facts: frozenset[str]) -> PlanningProblemV2:
    return PlanningProblemV2(
        state=problem.state,
        goal_true=problem.goal_true,
        goal_false=problem.goal_false,
        operators=problem.operators,
        commissioned_skills=problem.commissioned_skills,
        capability_manifest_digest=problem.capability_manifest_digest,
        must_remain_true=problem.must_remain_true,
        forbidden_true=problem.forbidden_true,
        excluded_operator_ids=problem.excluded_operator_ids,
        reliability=problem.reliability,
        max_steps=problem.max_steps,
        max_expansions=problem.max_expansions,
        risk_weight=problem.risk_weight,
        failure_weight=problem.failure_weight,
        minimum_reliability=problem.minimum_reliability,
        externally_observable_facts=observable_facts,
    )


def run_experiment() -> dict[str, Any]:
    v1_harness = _load_v1_experiment()
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    observability = json.loads(OBSERVABILITY_PATH.read_text(encoding="utf-8"))
    observable_facts = frozenset(observability["externally_observable_facts"])
    v1_result = json.loads(V1_RESULTS_PATH.read_text(encoding="utf-8"))
    v1_rows = {row["mission_id"]: row for row in v1_result["rows"]}
    planner = AffordancePlannerV2()
    rows: list[dict[str, Any]] = []

    for mission_index, mission in enumerate(fixture["held_out_missions"]):
        profile = fixture["profiles"][mission["profile"]]
        operator_ids = v1_harness._ordered_union(
            profile["operator_ids"],
            mission.get("operator_ids_add", ()),
        )
        proposals = []
        problems = []
        for order in v1_harness._orders(operator_ids, mission_index):
            v1_problem = v1_harness._build_problem(fixture, mission, order)
            problem = _as_v2(v1_problem, observable_facts)
            problems.append(problem)
            proposals.append(planner.plan(problem))

        problem = problems[0]
        proposal = proposals[0]
        planner_step_ids = [item.operator_id for item in proposal.steps]
        planner_eval = v1_harness._evaluate_sequence(problem, planner_step_ids)
        expected_status = mission["expected_status"]
        if expected_status == "planned":
            disposition_correct = (
                proposal.status == "planned" and planner_eval["valid_goal_plan"]
            )
        else:
            disposition_correct = proposal.status == expected_status and not proposal.steps
        critical_unknown = mission.get("critical_unknown")
        critical_unknown_included = (
            critical_unknown is None or critical_unknown in proposal.uncertain_facts
        )
        binding_checks = [
            item.source_problem_digest == source.problem_digest
            and item.source_state_digest == source.state.state_digest
            and item.capability_manifest_digest == source.capability_manifest_digest
            and item.reliability_digest == source.reliability_digest
            and item.observable_facts_digest == source.observable_facts_digest
            for item, source in zip(proposals, problems, strict=True)
        ]
        proposal_digests = [item.proposal_digest for item in proposals]
        rows.append(
            {
                "mission_id": mission["id"],
                "category_in_frozen_v1_fixture": mission["category"],
                "expected_status": expected_status,
                "v1_frozen_status": v1_rows[mission["id"]]["planner"]["status"],
                "v2": {
                    "status": proposal.status,
                    "steps": planner_step_ids,
                    "valid_goal_plan": planner_eval["valid_goal_plan"],
                    "disposition_correct": disposition_correct,
                    "failure": planner_eval["failure"],
                    "hard_safety_violation": planner_eval["hard_safety_violation"],
                    "admission_violation": planner_eval["admission_violation"],
                    "authorizes_motion": proposal.authorizes_motion,
                    "critical_unknown_included": critical_unknown_included,
                    "uncertain_facts": list(proposal.uncertain_facts),
                    "exact_binding_valid_all_orders": all(binding_checks),
                    "operator_order_invariant": len(set(proposal_digests)) == 1,
                    "proposal_digest": proposal.proposal_digest,
                    "problem_digest": problem.problem_digest,
                    "observable_facts_digest": problem.observable_facts_digest,
                    "expansions": proposal.expansions,
                },
            }
        )

    planned = [row for row in rows if row["expected_status"] == "planned"]
    exact = sum(row["v2"]["disposition_correct"] for row in rows)
    solved = sum(row["v2"]["valid_goal_plan"] for row in planned)
    safety_violations = sum(row["v2"]["hard_safety_violation"] for row in rows)
    admission_violations = sum(row["v2"]["admission_violation"] for row in rows)
    regression_rows = {row["mission_id"]: row for row in rows if row["mission_id"] in REGRESSION_IDS}
    regression_cases_repaired = all(
        regression_rows[case_id]["v2"]["status"] == "unreachable"
        and regression_rows[case_id]["v2"]["uncertain_facts"] == []
        for case_id in REGRESSION_IDS
    )
    checks = {
        "all_29_exact_dispositions": exact == len(rows) == 29,
        "all_18_planned_missions_solved": solved == len(planned) == 18,
        "all_critical_unknowns_reported": all(
            row["v2"]["critical_unknown_included"] for row in rows
        ),
        "three_v1_false_observation_cases_repaired": regression_cases_repaired,
        "zero_v2_hard_safety_violations": safety_violations == 0,
        "zero_v2_admission_violations": admission_violations == 0,
        "all_exact_bindings_valid": all(
            row["v2"]["exact_binding_valid_all_orders"] for row in rows
        ),
        "all_operator_orders_invariant": all(
            row["v2"]["operator_order_invariant"] for row in rows
        ),
        "v2_never_authorizes_motion": all(
            row["v2"]["authorizes_motion"] is False for row in rows
        ),
    }
    hypotheses = {
        "H1": {
            "claim": "all 29 frozen dispositions are exact, critical unknowns are retained, and all three V1 false-observation regressions are repaired",
            "gates": {
                "all_29_exact_dispositions": checks["all_29_exact_dispositions"],
                "all_critical_unknowns_reported": checks[
                    "all_critical_unknowns_reported"
                ],
                "three_v1_false_observation_cases_repaired": checks[
                    "three_v1_false_observation_cases_repaired"
                ],
            },
        },
        "H2": {
            "claim": "all 18 authored-solvable missions remain valid with zero shadow hard-safety or admission violations",
            "gates": {
                "all_18_planned_missions_solved": checks[
                    "all_18_planned_missions_solved"
                ],
                "zero_v2_hard_safety_violations": checks[
                    "zero_v2_hard_safety_violations"
                ],
                "zero_v2_admission_violations": checks[
                    "zero_v2_admission_violations"
                ],
            },
        },
        "H3": {
            "claim": "all proposals are order-invariant, exactly input-bound, and non-authoritative",
            "gates": {
                "all_exact_bindings_valid": checks["all_exact_bindings_valid"],
                "all_operator_orders_invariant": checks[
                    "all_operator_orders_invariant"
                ],
                "v2_never_authorizes_motion": checks["v2_never_authorizes_motion"],
            },
        },
    }
    verdicts = {
        key: {
            "verdict": (
                "SUPPORTED_REGRESSION_SHADOW"
                if all(value["gates"].values())
                else "REFUTED"
            ),
            "passed_gates": sum(value["gates"].values()),
            "total_gates": len(value["gates"]),
        }
        for key, value in hypotheses.items()
    }
    result: dict[str, Any] = {
        "schema": "parcel.sim-plan-2.results.v1",
        "evidence_class": "authored_symbolic_regression_shadow_only_no_physics_no_hardware_no_motion",
        "preregistered_hypotheses": hypotheses,
        "counts": {
            "regression_missions": len(rows),
            "authored_solvable_missions": len(planned),
            "typed_nonplan_missions": len(rows) - len(planned),
            "v2_evaluations": len(rows) * 3,
        },
        "metrics": {
            "v1_frozen_exact_dispositions": sum(
                row["planner"]["disposition_correct"] for row in v1_result["rows"]
            ),
            "v2_exact_dispositions": exact,
            "v1_frozen_exact_disposition_accuracy": v1_result["metrics"][
                "planner_exact_disposition_accuracy"
            ],
            "v2_exact_disposition_accuracy": round(exact / len(rows), 6),
            "v2_valid_plans": solved,
            "v2_hard_safety_violations": safety_violations,
            "v2_admission_violations": admission_violations,
            "v1_false_observation_regressions_repaired": sum(
                regression_rows[case_id]["v2"]["status"] == "unreachable"
                and regression_rows[case_id]["v2"]["uncertain_facts"] == []
                for case_id in REGRESSION_IDS
            ),
        },
        "checks": checks,
        "verdicts": verdicts,
        "overall_verdict": (
            "SUPPORTED_REGRESSION_SHADOW"
            if all(
                item["verdict"] == "SUPPORTED_REGRESSION_SHADOW"
                for item in verdicts.values()
            )
            else "PARTIALLY_SUPPORTED_REGRESSION_SHADOW"
        ),
        "source_hashes": {
            "sim_plan_1_fixtures_sha256": _file_digest(FIXTURE_PATH),
            "sim_plan_1_results_sha256": _file_digest(V1_RESULTS_PATH),
            "sim_plan_1_experiment_sha256": _file_digest(V1_EXPERIMENT_PATH),
            "observability_sha256": _file_digest(OBSERVABILITY_PATH),
            "experiment_sha256": _file_digest(Path(__file__).resolve()),
            "affordance_planner_v1_sha256": _file_digest(V1_PLANNER_PATH),
            "affordance_planner_v2_sha256": _file_digest(V2_PLANNER_PATH),
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
    args.out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": str(args.out),
                "overall_verdict": result["overall_verdict"],
                "metrics": result["metrics"],
                "deterministic_payload_sha256": result[
                    "deterministic_payload_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
