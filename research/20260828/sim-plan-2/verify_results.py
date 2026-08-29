"""Verify deterministic replay and frozen claims for SIM-PLAN-2."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import experiment


def _load(name: str) -> dict[str, Any]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_digest(payload: dict[str, Any]) -> str:
    selected = {key: payload[key] for key in experiment.DETERMINISTIC_KEYS}
    return hashlib.sha256(experiment._canonical_bytes(selected)).hexdigest()


def verify(*, write_canonical: bool = False) -> dict[str, Any]:
    run1 = _load("results-run1.json")
    run2 = _load("results-run2.json")
    if write_canonical:
        (HERE / "results.json").write_text(
            json.dumps(run1, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    canonical = _load("results.json")
    replay = experiment.run_experiment()
    repaired = {
        row["mission_id"]: row["v2"]
        for row in run1["rows"]
        if row["mission_id"] in experiment.REGRESSION_IDS
    }
    checks = {
        "run1_digest_recomputed": (
            _payload_digest(run1) == run1["deterministic_payload_sha256"]
        ),
        "run2_digest_recomputed": (
            _payload_digest(run2) == run2["deterministic_payload_sha256"]
        ),
        "independent_runs_json_equivalent": run1 == run2,
        "canonical_is_run1": canonical == run1,
        "fresh_in_process_replay_matches": replay == run1,
        "all_source_hashes_recomputed": run1["source_hashes"]
        == {
            "sim_plan_1_fixtures_sha256": _file_digest(experiment.FIXTURE_PATH),
            "sim_plan_1_results_sha256": _file_digest(experiment.V1_RESULTS_PATH),
            "sim_plan_1_experiment_sha256": _file_digest(
                experiment.V1_EXPERIMENT_PATH
            ),
            "observability_sha256": _file_digest(experiment.OBSERVABILITY_PATH),
            "experiment_sha256": _file_digest(Path(experiment.__file__)),
            "affordance_planner_v1_sha256": _file_digest(
                experiment.V1_PLANNER_PATH
            ),
            "affordance_planner_v2_sha256": _file_digest(
                experiment.V2_PLANNER_PATH
            ),
        },
        "expected_matrix_size": run1["counts"]
        == {
            "regression_missions": 29,
            "authored_solvable_missions": 18,
            "typed_nonplan_missions": 11,
            "v2_evaluations": 87,
        },
        "all_hypotheses_supported_at_regression_shadow_tier": all(
            item["verdict"] == "SUPPORTED_REGRESSION_SHADOW"
            for item in run1["verdicts"].values()
        ),
        "three_named_regressions_are_unreachable_without_unknowns": all(
            repaired[case_id]["status"] == "unreachable"
            and repaired[case_id]["uncertain_facts"] == []
            for case_id in experiment.REGRESSION_IDS
        ),
        "all_29_dispositions_exact": run1["metrics"][
            "v2_exact_dispositions"
        ]
        == 29,
        "all_18_symbolic_plans_retained": run1["metrics"]["v2_valid_plans"]
        == 18,
        "evidence_scope_is_explicit": run1["evidence_class"]
        == "authored_symbolic_regression_shadow_only_no_physics_no_hardware_no_motion",
    }
    assert all(checks.values()), json.dumps(checks, indent=2, sort_keys=True)
    return {
        "schema": "parcel.sim-plan-2.verification.v1",
        "verdict": "PASS",
        "checks": checks,
        "deterministic_payload_sha256": run1["deterministic_payload_sha256"],
        "file_sha256": {
            name: _file_digest(HERE / name)
            for name in (
                "results-run1.json",
                "results-run2.json",
                "results.json",
                "observability.json",
                "experiment.py",
            )
        },
        "evidence_class": "authored_symbolic_regression_shadow_only_no_physics_no_hardware_no_motion",
        "hardware_used": "none",
        "physics_simulator_used": "none",
        "physical_motion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-canonical", action="store_true")
    parser.add_argument("--out", type=Path, default=HERE / "verification.json")
    args = parser.parse_args()
    report = verify(write_canonical=args.write_canonical)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
