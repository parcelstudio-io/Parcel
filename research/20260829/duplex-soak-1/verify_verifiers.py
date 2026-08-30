"""Post-completion mutation checks for the two independent DSOAK verifiers.

This is a verifier-of-verifiers, not part of the preregistered scientific
gate.  It clones the final artifacts into a temporary directory, applies one
tamper at a time, and requires the hardened acceptance booleans to go red.  It
also proves that the narrowly allowed terminal /proc handoff remains green.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from verify_monitor import verify as verify_monitor
from verify_results import Audit

HERE = Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _result_report(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    _write_json(path, payload)
    return Audit(payload, path).run()


def _result_cases(base: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    mutations: list[
        tuple[str, bool, Callable[[dict[str, Any]], None]]
    ] = []

    def interim(payload: dict[str, Any]) -> None:
        payload["status"] = "running"
        payload["verdict"] = "RUNNING_NOT_A_VERDICT"
        payload["gates"]["normal_uninterrupted_completion"] = False

    mutations.append(("interim_status", False, interim))
    mutations.append(
        (
            "terminal_verdict_flip",
            False,
            lambda payload: payload.__setitem__(
                "verdict", "REFUTED_OR_INCOMPLETE_PROCEDURAL_SOAK"
            ),
        )
    )
    mutations.append(
        (
            "serialized_gate_flip",
            False,
            lambda payload: payload["gates"].__setitem__("zero_post_stop_motion", False),
        )
    )
    mutations.append(
        (
            "aggregate_episode_tamper",
            False,
            lambda payload: payload["aggregates"]["A1_ledger_history_gru"]["all"].__setitem__(
                "episodes",
                payload["aggregates"]["A1_ledger_history_gru"]["all"]["episodes"] + 1,
            ),
        )
    )

    def shorten(payload: dict[str, Any]) -> None:
        payload["elapsed_monotonic_seconds"] = payload["target_wall_hours"] * 3600.0 - 1.0

    mutations.append(("complete_before_configured_target", False, shorten))

    def alter_hash(payload: dict[str, Any]) -> None:
        key = min(payload["integrity"]["dmc_hashes_at_start"])
        payload["integrity"]["dmc_hashes_at_start"][key] = "0" * 64

    mutations.append(("source_hash_tamper", False, alter_hash))

    def remove_exercise(payload: dict[str, Any]) -> None:
        rows = payload["aggregates"]["A1_ledger_history_gru"]
        for split in ("all", "frozen", "adversarial"):
            rows[split]["raw_unsafe"] = 0

    mutations.append(("raw_unsafe_exercise_removed", False, remove_exercise))

    def fail_scientific_gate(payload: dict[str, Any]) -> None:
        payload["counts"]["deterministic_replay_mismatches"] = 1
        payload["replay_mismatch_details"] = [{"mutation_probe": True}]
        payload["gates"]["zero_deterministic_replay_mismatches"] = False
        payload["verdict"] = "REFUTED_OR_INCOMPLETE_PROCEDURAL_SOAK"

    mutations.append(("internally_consistent_failed_gate", False, fail_scientific_gate))
    mutations.append(
        (
            "boolean_episode_count",
            False,
            lambda payload: payload["counts"].__setitem__("primary_episodes", True),
        )
    )
    mutations.append(
        (
            "nonfinite_candidate_rate",
            False,
            lambda payload: payload["aggregates"]["A1_ledger_history_gru"]["all"].__setitem__(
                "mission_success_rate", float("nan")
            ),
        )
    )

    def omit_failure_detail(payload: dict[str, Any]) -> None:
        if payload["candidate_failure_details"]:
            payload["candidate_failure_details"].pop()

    mutations.append(("failure_detail_omitted", False, omit_failure_detail))

    def duplicate_failure_detail(payload: dict[str, Any]) -> None:
        if len(payload["candidate_failure_details"]) >= 2:
            payload["candidate_failure_details"][1] = copy.deepcopy(
                payload["candidate_failure_details"][0]
            )

    mutations.append(("failure_detail_duplicate", False, duplicate_failure_detail))

    def move_failure_seed(payload: dict[str, Any]) -> None:
        if payload["candidate_failure_details"]:
            payload["candidate_failure_details"][0]["seed"] = -1

    mutations.append(("failure_seed_out_of_range", False, move_failure_seed))

    reports: list[dict[str, Any]] = []
    base_report = _result_report(copy.deepcopy(base), root / "result-base.json")
    reports.append(
        {
            "case": "untampered_final",
            "expected_acceptance": True,
            "actual_acceptance": base_report["completion_acceptance_pass"],
            "structural_pass": base_report["structural_and_integrity_pass"],
            "errors": base_report["errors"],
        }
    )
    for name, expected, mutate in mutations:
        payload = copy.deepcopy(base)
        mutate(payload)
        report = _result_report(payload, root / f"result-{name}.json")
        reports.append(
            {
                "case": name,
                "expected_acceptance": expected,
                "actual_acceptance": report["completion_acceptance_pass"],
                "structural_pass": report["structural_and_integrity_pass"],
                "errors": report["errors"],
                "warnings": report["warnings"],
            }
        )
    return reports


def _monitor_cases(
    base_rows: list[dict[str, Any]],
    *,
    result_path: Path,
    root: Path,
) -> list[dict[str, Any]]:
    def run_case(name: str, rows: list[dict[str, Any]], expected: bool) -> dict[str, Any]:
        path = root / f"monitor-{name}.jsonl"
        _write_jsonl(path, rows)
        report = verify_monitor(path, result_path=result_path)
        return {
            "case": name,
            "expected_continuity": expected,
            "actual_continuity": report["continuity_observed_to_completion"],
            "integrity_pass": report["integrity_pass"],
            "errors": report["errors"],
        }

    reports = [run_case("untampered_final", copy.deepcopy(base_rows), True)]

    terminal_handoff = copy.deepcopy(base_rows)
    terminal_handoff[-1]["process"] = None
    reports.append(run_case("terminal_process_absent", terminal_handoff, True))

    deleted = copy.deepcopy(base_rows)
    del deleted[len(deleted) // 2]
    reports.append(run_case("interior_row_deleted", deleted, False))

    duplicated = copy.deepcopy(base_rows)
    middle = len(duplicated) // 2
    duplicated.insert(middle, copy.deepcopy(duplicated[middle]))
    reports.append(run_case("interior_row_duplicated", duplicated, False))

    reordered = copy.deepcopy(base_rows)
    middle = len(reordered) // 2
    reordered[middle - 1], reordered[middle] = reordered[middle], reordered[middle - 1]
    reports.append(run_case("interior_rows_reordered", reordered, False))

    frozen = copy.deepcopy(base_rows)
    middle = len(frozen) // 2
    checkpoint_fields = (
        "checkpoint_sha256",
        "checkpoint_elapsed_monotonic_seconds",
        "checkpoint_primary_episodes",
    )
    for offset in (1, 2):
        for field in checkpoint_fields:
            frozen[middle + offset][field] = frozen[middle][field]
    reports.append(run_case("three_row_checkpoint_freeze", frozen, False))

    final_hash = copy.deepcopy(base_rows)
    final_hash[-1]["checkpoint_sha256"] = "0" * 64
    reports.append(run_case("final_checkpoint_hash_tamper", final_hash, False))

    interior_process = copy.deepcopy(base_rows)
    interior_process[len(interior_process) // 2]["process"] = None
    reports.append(run_case("interior_process_absent", interior_process, False))

    boot = copy.deepcopy(base_rows)
    boot[len(boot) // 2]["boot_id"] = "different-boot"
    reports.append(run_case("boot_identity_tamper", boot, False))

    identity = copy.deepcopy(base_rows)
    identity[len(identity) // 2]["process"]["command_sha256"] = "0" * 64
    reports.append(run_case("process_identity_tamper", identity, False))

    zombie_identity = copy.deepcopy(base_rows)
    zombie_identity[-1]["process"] = copy.deepcopy(base_rows[0]["process"])
    zombie_identity[-1]["process"]["pid"] += 1
    zombie_identity[-1]["process"]["command_sha256"] = hashlib.sha256(b"").hexdigest()
    reports.append(run_case("terminal_zombie_identity_tamper", zombie_identity, False))

    unreadable = copy.deepcopy(base_rows)
    unreadable[len(unreadable) // 2]["checkpoint_readable"] = False
    reports.append(run_case("checkpoint_unreadable", unreadable, False))

    nonfinite = copy.deepcopy(base_rows)
    nonfinite[len(nonfinite) // 2]["checkpoint_elapsed_monotonic_seconds"] = float("nan")
    reports.append(run_case("checkpoint_nonfinite", nonfinite, False))

    bool_count = copy.deepcopy(base_rows)
    bool_count[len(bool_count) // 2]["checkpoint_primary_episodes"] = True
    reports.append(run_case("checkpoint_boolean_count", bool_count, False))

    regressed = copy.deepcopy(base_rows)
    middle = len(regressed) // 2
    regressed[middle]["checkpoint_elapsed_monotonic_seconds"] = (
        regressed[middle - 1]["checkpoint_elapsed_monotonic_seconds"] - 1.0
    )
    reports.append(run_case("checkpoint_elapsed_regression", regressed, False))

    count = copy.deepcopy(base_rows)
    count[-1]["checkpoint_primary_episodes"] += 1
    reports.append(run_case("final_episode_count_tamper", count, False))

    terminal_status = copy.deepcopy(base_rows)
    terminal_status[-1]["checkpoint_status"] = "running"
    reports.append(run_case("terminal_status_tamper", terminal_status, False))

    truncated = copy.deepcopy(base_rows[:-1])
    reports.append(run_case("terminal_row_truncated", truncated, False))
    return reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=HERE / "results.json")
    parser.add_argument("--monitor", type=Path, default=HERE / "external-monitor.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    result = json.loads(args.result.read_text(encoding="utf-8"))
    monitor_rows = [
        json.loads(line)
        for line in args.monitor.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with tempfile.TemporaryDirectory(prefix="parcel-dsoak-verifier-") as temporary:
        root = Path(temporary)
        frozen_result = root / "final-results.json"
        shutil.copyfile(args.result, frozen_result)
        result_cases = _result_cases(result, root)
        monitor_cases = _monitor_cases(
            monitor_rows,
            result_path=frozen_result,
            root=root,
        )

    cases = [*result_cases, *monitor_cases]
    passed = all(
        row.get("actual_acceptance", row.get("actual_continuity"))
        is row.get("expected_acceptance", row.get("expected_continuity"))
        for row in cases
    )
    report = {
        "schema": "parcel.duplex_soak.verifier_mutation.v1",
        "result_sha256": _sha256(args.result),
        "monitor_sha256": _sha256(args.monitor),
        "verify_results_sha256": _sha256(HERE / "verify_results.py"),
        "verify_monitor_sha256": _sha256(HERE / "verify_monitor.py"),
        "case_count": len(cases),
        "all_expectations_met": passed,
        "result_cases": result_cases,
        "monitor_cases": monitor_cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_json(args.out, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
