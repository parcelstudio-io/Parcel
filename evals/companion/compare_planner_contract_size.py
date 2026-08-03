"""Compare PlanIR and PlanSketch serialization size without model inference.

This is a representation-only counterfactual. It projects model-owned
semantics out of an immutable PlanIR result and measures compact canonical JSON
bytes. It deliberately reports no tokenizer count, latency, or quality gain.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_RESULT = (
    REPO_ROOT / "evals/companion/planner_quality_v2/results/"
    "planner-v2-20260803-gemma4-cpu-run05.json"
)
SOURCE_RESULT_SHA256 = "e38fc6394fd6344fa3f223ecc753e40f9663951f0acafe8580f27656f064f3b4"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be an array")
    return value


def project_plan_sketch(raw_plan: Mapping[str, object]) -> dict[str, object]:
    """Project only model-owned PlanSketch semantics from one raw PlanIR."""

    goal = _object(raw_plan.get("goal"), "goal")
    target = _object(goal.get("target"), "goal target")
    sketch_steps: list[dict[str, object]] = []
    for index, raw_step in enumerate(_sequence(raw_plan.get("steps"), "steps")):
        step = _object(raw_step, f"step {index}")
        skill = step.get("skill")
        arguments = _object(step.get("arguments"), f"step {index} arguments")
        navigation: dict[str, object] | None = None
        if skill == "NavigateTo":
            success = _object(step.get("success"), f"step {index} success")
            relation = success.get("fact")
            navigation_target = success.get("target")
            if relation not in {"inside", "near"} or not isinstance(navigation_target, str):
                raise ValueError("NavigateTo lacks explicit model-authored grounding")
            navigation = {"relation": relation, "target": navigation_target}
        sketch_steps.append(
            {
                "skill": skill,
                "arguments": dict(arguments),
                "navigation": navigation,
            }
        )
    return {
        "schema_version": 1,
        "goal": {
            "relation": goal.get("relation"),
            "kind": target.get("kind"),
            "query": target.get("query"),
        },
        "steps": sketch_steps,
    }


def build_comparison(
    source_result: str | Path = SOURCE_RESULT,
) -> dict[str, object]:
    path = Path(source_result)
    payload = path.read_bytes()
    source_sha256 = hashlib.sha256(payload).hexdigest()
    if path.resolve() == SOURCE_RESULT.resolve() and source_sha256 != SOURCE_RESULT_SHA256:
        raise ValueError("immutable source planner result digest changed")
    report = json.loads(payload)
    if not isinstance(report, dict) or not isinstance(report.get("cases"), list):
        raise TypeError("source planner result is invalid")
    rows: list[dict[str, object]] = []
    for case in report["cases"]:
        case_data = _object(case, "case")
        raw_plan = _object(case_data.get("raw_plan"), "raw PlanIR")
        sketch = project_plan_sketch(raw_plan)
        plan_ir_bytes = len(_canonical_bytes(raw_plan))
        plan_sketch_bytes = len(_canonical_bytes(sketch))
        rows.append(
            {
                "case_id": case_data.get("case_id"),
                "plan_ir_v1_canonical_bytes": plan_ir_bytes,
                "plan_sketch_v1_canonical_bytes": plan_sketch_bytes,
                "byte_reduction_fraction": round(
                    1.0 - plan_sketch_bytes / plan_ir_bytes,
                    6,
                ),
            }
        )
    plan_ir_total = sum(int(row["plan_ir_v1_canonical_bytes"]) for row in rows)
    plan_sketch_total = sum(int(row["plan_sketch_v1_canonical_bytes"]) for row in rows)
    return {
        "schema_version": 1,
        "artifact_type": "offline_planner_contract_serialization_counterfactual",
        "source": {
            "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
            "sha256": source_sha256,
            "run_id": report.get("run_id"),
        },
        "method": {
            "encoding": "canonical_compact_sorted_ascii_json",
            "projection": "model_owned_goal_ordered_skills_arguments_and_explicit_navigation_grounding",
            "model_inference_performed": False,
            "tokenizer_used": None,
        },
        "aggregate": {
            "case_count": len(rows),
            "plan_ir_v1_canonical_bytes": plan_ir_total,
            "plan_sketch_v1_canonical_bytes": plan_sketch_total,
            "byte_reduction_fraction": round(
                1.0 - plan_sketch_total / plan_ir_total,
                6,
            ),
            "model_tokens": None,
            "model_latency_ms": None,
            "physical_navigation_episode_count": 0,
        },
        "cases": rows,
        "claims": {
            "proves": ["serialized contract size for equivalent recorded model-owned semantics"],
            "does_not_prove": [
                "model token reduction",
                "latency improvement",
                "PlanSketch generation quality",
                "semantic skill execution or physical navigation success",
            ],
        },
    }


def main() -> int:
    print(json.dumps(build_comparison(), indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
