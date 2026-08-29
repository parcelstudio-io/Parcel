"""Verify deterministic replay and frozen claims for sim-plan-1."""

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


def _file_digest(name: str) -> str:
    return hashlib.sha256((HERE / name).read_bytes()).hexdigest()


def _payload_digest(payload: dict[str, Any]) -> str:
    selected = {key: payload[key] for key in experiment.DETERMINISTIC_KEYS}
    return hashlib.sha256(experiment._canonical_bytes(selected)).hexdigest()


def verify(*, write_canonical: bool = False) -> dict[str, Any]:
    run1 = _load("results-run1.json")
    run2 = _load("results-run2.json")
    if write_canonical:
        (HERE / "results.json").write_text(
            json.dumps(run1, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    canonical = _load("results.json")
    replay = experiment.run_experiment()

    misclassified = [
        row["mission_id"]
        for row in run1["rows"]
        if not row["planner"]["disposition_correct"]
    ]
    checks = {
        "run1_digest_recomputed": (
            _payload_digest(run1) == run1["deterministic_payload_sha256"]
        ),
        "run2_digest_recomputed": (
            _payload_digest(run2) == run2["deterministic_payload_sha256"]
        ),
        "independent_runs_byte_equivalent_json": run1 == run2,
        "canonical_is_run1": canonical == run1,
        "fresh_in_process_replay_matches": replay == run1,
        "fixture_hash_recomputed": (
            run1["source_hashes"]["fixtures_sha256"]
            == hashlib.sha256(experiment.FIXTURE_PATH.read_bytes()).hexdigest()
        ),
        "planner_hash_recomputed": (
            run1["source_hashes"]["affordance_planner_sha256"]
            == hashlib.sha256(experiment.PLANNER_PATH.read_bytes()).hexdigest()
        ),
        "experiment_hash_recomputed": (
            run1["source_hashes"]["experiment_sha256"]
            == hashlib.sha256(Path(experiment.__file__).read_bytes()).hexdigest()
        ),
        "expected_matrix_size": run1["counts"]
        == {
            "held_out_missions": 29,
            "planned_missions": 18,
            "typed_nonplan_missions": 11,
            "planner_evaluations": 87,
            "fixed_template_evaluations": 29,
        },
        "hypothesis_verdicts_frozen": {
            key: value["verdict"] for key, value in run1["verdicts"].items()
        }
        == {"H1": "SUPPORTED_SHADOW", "H2": "REFUTED", "H3": "SUPPORTED_SHADOW"},
        "three_unreachable_cases_over_abstain": misclassified
        == [
            "greet-camera-false",
            "greet-scan-uncommissioned",
            "follow-consent-false",
        ],
        "evidence_scope_is_explicit": run1["evidence_class"]
        == "authored_symbolic_shadow_only_no_physics_no_hardware_no_motion",
    }
    assert all(checks.values()), json.dumps(checks, indent=2, sort_keys=True)
    return {
        "schema": "parcel.sim-plan-1.verification.v1",
        "verdict": "PASS",
        "checks": checks,
        "deterministic_payload_sha256": run1["deterministic_payload_sha256"],
        "file_sha256": {
            "results-run1.json": _file_digest("results-run1.json"),
            "results-run2.json": _file_digest("results-run2.json"),
            "results.json": _file_digest("results.json"),
            "fixtures.json": _file_digest("fixtures.json"),
            "experiment.py": _file_digest("experiment.py"),
        },
        "evidence_class": "authored_symbolic_shadow_only_no_physics_no_hardware_no_motion",
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
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
