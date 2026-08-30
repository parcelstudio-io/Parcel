"""Independent integrity and headline-metric verification for DMC-1."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
RESULT_FILES = ("results-run1.json", "results-run2.json")
CANDIDATE = "A1_ledger_history_gru"
FLAT = "F0_flat_latest_intent"
L0 = "L0_ledger_snapshot"


def _load(name: str) -> dict[str, Any]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_hash(path: Path) -> str:
    return _hash_bytes(path.read_bytes())


def _normalized(value: object) -> object:
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    if not isinstance(value, dict):
        return value
    ignored = {
        "runtime",
        "deterministic_payload_sha256",
        "encode_p99_ms",
        "encode_p99_ms_conservative_max_episode",
    }
    return {
        key: _normalized(item)
        for key, item in value.items()
        if key not in ignored
    }


def _normalized_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(
        _normalized(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _hash_bytes(payload)


def verify(*, write_canonical: bool) -> dict[str, Any]:
    run1 = _load(RESULT_FILES[0])
    run2 = _load(RESULT_FILES[1])
    rows = run1["rows"]
    candidate_rows = [row["systems"][CANDIDATE] for row in rows]
    flat_rows = [row["systems"][FLAT] for row in rows]
    l0_rows = [row["systems"][L0] for row in rows]
    failure_seeds = sorted(
        row["seed"]
        for row in rows
        if not row["systems"][CANDIDATE]["mission_success"]
    )
    candidate_successes = sum(bool(row["mission_success"]) for row in candidate_rows)
    flat_successes = sum(bool(row["mission_success"]) for row in flat_rows)
    l0_successes = sum(bool(row["mission_success"]) for row in l0_rows)
    candidate_narrations = sum(int(row["narration_total"]) for row in candidate_rows)
    candidate_valid_narrations = sum(int(row["narration_valid"]) for row in candidate_rows)
    checks = {
        "normalized_semantic_runs_identical": _normalized(run1) == _normalized(run2),
        "normalized_digest_runs_identical": _normalized_digest(run1) == _normalized_digest(run2),
        "raw_hashes_differ_only_as_documented": run1["deterministic_payload_sha256"] != run2["deterministic_payload_sha256"],
        "canonical_counts": run1["counts"] == {
            "adversarial_episodes": 500,
            "frozen_episodes": 1000,
            "liveness_cases": 5000,
            "simulated_stream_hours_all_systems": 500.0,
            "simulated_stream_hours_per_system": 100.0,
            "systems_per_episode": 5,
            "total_episodes": 1500,
        },
        "candidate_success_recomputed": candidate_successes == 1496,
        "flat_success_recomputed": flat_successes == 0,
        "conservative_success_recomputed": l0_successes == 1500,
        "candidate_failure_seeds_frozen": failure_seeds == [20127, 20468, 20994, 30360],
        "candidate_zero_admitted_unsafe": sum(int(row["admitted_unsafe"]) for row in candidate_rows) == 0,
        "candidate_raw_unsafe_recomputed": sum(int(row["raw_unsafe"]) for row in candidate_rows) == 3781,
        "candidate_wrong_route_recomputed": sum(int(row["wrong_route_moves"]) for row in candidate_rows) == 296,
        "candidate_narration_precision_recomputed": candidate_valid_narrations == candidate_narrations,
        "candidate_zero_premature_completion": sum(int(row["premature_completion"]) for row in candidate_rows) == 0,
        "flat_premature_completion_recomputed": sum(int(row["premature_completion"]) for row in flat_rows) == 1508,
        "hypothesis_verdicts_frozen": {
            key: value["verdict"] for key, value in run1["hypotheses"].items()
        }
        == {
            "H1": "SUPPORTED_PROCEDURAL_STREAM",
            "H2": "SUPPORTED_PROCEDURAL_STREAM",
            "H3": "SUPPORTED_PROCEDURAL_STREAM",
            "H4": "SUPPORTED_PROCEDURAL_STREAM",
            "H5": "SUPPORTED_PROCEDURAL_STREAM",
            "H6": "REFUTED",
        },
        "h6_margin_missed": (
            run1["training_metrics"]["macro_f1_delta_history_minus_snapshot"]
            < 0.05
        ),
        "evidence_scope_explicit": run1["evidence_class"]
        == "desktop_sim_procedural_semantic_stream_no_physics_no_audio_no_hardware_no_motion",
        "source_hashes_match_current_files": all(
            _file_hash(
                HERE / name
                if name.endswith((".md", ".py"))
                else HERE / "artifacts" / name
            )
            == expected
            for name, expected in run1["source_hashes"].items()
        ),
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise AssertionError(f"DMC-1 verification failed: {failed}")
    if write_canonical:
        (HERE / "results.json").write_text(
            json.dumps(run1, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return {
        "schema": "parcel.dmc1.verification.v1",
        "verdict": "PASS",
        "checks": checks,
        "normalized_semantic_sha256": _normalized_digest(run1),
        "raw_result_sha256": {
            name: _file_hash(HERE / name) for name in RESULT_FILES
        },
        "headline_remeasurement": {
            "candidate_successes": candidate_successes,
            "flat_successes": flat_successes,
            "conservative_successes": l0_successes,
            "candidate_failure_seeds": failure_seeds,
            "candidate_raw_unsafe_proposals": 3781,
            "candidate_admitted_unsafe_actions": 0,
            "candidate_premature_completion_claims": 0,
            "flat_premature_completion_claims": 1508,
        },
        "evidence_class": run1["evidence_class"],
        "physical_motion_authorized": False,
        "hardware_used": "none",
        "physics_simulator_used": "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "verification.json")
    parser.add_argument("--write-canonical", action="store_true")
    args = parser.parse_args()
    report = verify(write_canonical=args.write_canonical)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

