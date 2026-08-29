"""Independent integrity and decision verifier for RL-ENV-READINESS-1."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

ARTIFACT_DIR = Path(__file__).resolve().parent
REPO = ARTIFACT_DIR.parents[2]
EXPECTED_GATES = tuple(f"G{index}" for index in range(9))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= 1e-6 + 0.01 * max(abs(actual), abs(expected))


def _expected_status(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _check(name: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def verify(first_path: Path, second_path: Path) -> dict[str, Any]:
    first_bytes = first_path.read_bytes()
    second_bytes = second_path.read_bytes()
    first = json.loads(first_bytes)
    second = json.loads(second_bytes)
    checks: list[dict[str, Any]] = []

    checks.append(
        _check(
            "deterministic_raw_json",
            first_bytes == second_bytes and first == second,
            {
                "byte_identical": first_bytes == second_bytes,
                "first_file_sha256": hashlib.sha256(first_bytes).hexdigest(),
                "second_file_sha256": hashlib.sha256(second_bytes).hexdigest(),
            },
        )
    )

    embedded_payload = first.get("payload_sha256")
    payload = dict(first)
    payload.pop("payload_sha256", None)
    computed_payload = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    checks.append(
        _check(
            "payload_digest",
            embedded_payload == computed_payload,
            {"embedded": embedded_payload, "computed": computed_payload},
        )
    )

    expected_sources = first["subject"]["expected_sha256"]
    current_sources = {relative: _sha256_file(REPO / relative) for relative in expected_sources}
    checks.append(
        _check(
            "frozen_subject",
            first["subject"]["matches_preregistration"]
            and expected_sources == first["subject"]["observed_sha256"] == current_sources,
            {
                "expected": expected_sources,
                "embedded_observed": first["subject"]["observed_sha256"],
                "current": current_sources,
            },
        )
    )

    gates = first["gates"]
    gate_ids_ok = tuple(sorted(gates, key=lambda item: int(item[1:]))) == EXPECTED_GATES
    statuses = {gate_id: gates[gate_id]["status"] for gate_id in EXPECTED_GATES}
    checks.append(_check("gate_set", gate_ids_ok, {"gate_ids": list(gates)}))

    offline = gates["G0"]["actual"]
    claims = offline["physics_claims"]
    g0_pass = (
        offline["labelled_nonphysics"]
        and offline["fall_detection_explicitly_invalid"]
        and all(
            claim.get("validity") == "absent_or_none" or claim.get("explicitly_invalid") is True
            for claim in claims.values()
        )
    )
    checks.append(
        _check(
            "G0_recomputed",
            gates["G0"]["status"] == _expected_status(g0_pass),
            {"recomputed_pass": g0_pass, "recorded_status": gates["G0"]["status"]},
        )
    )

    g1_checks = gates["G1"]["actual"]["dimension_checks"]
    g1_pass = all(g1_checks.values())
    checks.append(
        _check(
            "G1_recomputed",
            gates["G1"]["status"] == _expected_status(g1_pass),
            {"recomputed_pass": g1_pass, "checks": g1_checks},
        )
    )

    g2_checks = gates["G2"]["actual"]["checks"]
    g2_pass = all(g2_checks.values())
    checks.append(
        _check(
            "G2_recomputed",
            gates["G2"]["status"] == _expected_status(g2_pass),
            {"recomputed_pass": g2_pass, "checks": g2_checks},
        )
    )

    velocity_trials = gates["G3"]["actual"]["trials"]
    velocity_matches = [
        _close(row["reported_actual_vx_mps"], row["finite_difference_vx_mps"])
        for row in velocity_trials
    ]
    g3_pass = len(velocity_matches) == 3 and all(velocity_matches)
    checks.append(
        _check(
            "G3_recomputed",
            gates["G3"]["status"] == _expected_status(g3_pass),
            {"recomputed_pass": g3_pass, "matches": velocity_matches},
        )
    )

    posture_cases = gates["G4"]["actual"]["cases"]
    height_matches = [
        _close(case["reported_base_height"], case["root_height_m"])
        for case in posture_cases
    ]
    g4_pass = len(height_matches) == 2 and all(height_matches)
    checks.append(
        _check(
            "G4_recomputed",
            gates["G4"]["status"] == _expected_status(g4_pass),
            {"recomputed_pass": g4_pass, "matches": height_matches},
        )
    )

    upright_matches = []
    for case in gates["G5"]["actual"]["cases"]:
        quat = case["root_quat_wxyz"]
        norm = math.sqrt(sum(float(value) ** 2 for value in quat))
        x = float(quat[1]) / norm
        y = float(quat[2]) / norm
        projection = 1.0 - 2.0 * (x * x + y * y)
        derived = float(case["root_height_m"]) >= 0.18 and projection >= 0.5
        upright_matches.append(bool(case["reported_upright"]) == derived)
    g5_pass = len(upright_matches) == 2 and all(upright_matches)
    checks.append(
        _check(
            "G5_recomputed",
            gates["G5"]["status"] == _expected_status(g5_pass),
            {"recomputed_pass": g5_pass, "matches": upright_matches},
        )
    )

    forced_fall = gates["G6"]["actual"]["forced_fall"]
    g6_pass = forced_fall["case"] == "forced_fall" and forced_fall["terminated"] is True
    checks.append(
        _check(
            "G6_recomputed",
            gates["G6"]["status"] == _expected_status(g6_pass),
            {"recomputed_pass": g6_pass, "terminated": forced_fall["terminated"]},
        )
    )

    reset_actual = gates["G7"]["actual"]
    g7_pass = reset_actual["records_equal"] is True
    checks.append(
        _check(
            "G7_recomputed",
            gates["G7"]["status"] == _expected_status(g7_pass),
            {
                "recomputed_pass": g7_pass,
                "records_equal": reset_actual["records_equal"],
                "record_digests_differ": (
                    reset_actual["first_record_sha256"]
                    != reset_actual["second_record_sha256"]
                ),
            },
        )
    )

    action_actual = gates["G8"]["actual"]
    distance = float(action_actual["final_qpos_l2_distance"])
    g8_pass = math.isfinite(distance) and distance >= 1e-3
    checks.append(
        _check(
            "G8_recomputed",
            gates["G8"]["status"] == _expected_status(g8_pass),
            {"recomputed_pass": g8_pass, "final_qpos_l2_distance": distance},
        )
    )

    summary = first["summary"]
    expected_summary = {
        "pass": sum(status == "PASS" for status in statuses.values()),
        "fail": sum(status == "FAIL" for status in statuses.values()),
        "not_evaluated": sum(status == "NOT_EVALUATED" for status in statuses.values()),
        "total": len(statuses),
    }
    if not first["subject"]["matches_preregistration"]:
        expected_decision = "INVALIDATED_SUBJECT_DRIFT"
    elif expected_summary["fail"]:
        expected_decision = "REFUTED"
    elif expected_summary["not_evaluated"]:
        expected_decision = "INCONCLUSIVE"
    else:
        expected_decision = "SUPPORTED_LOCAL_SIM"
    checks.append(
        _check(
            "summary_and_decision",
            summary == expected_summary
            and first["hypothesis"]["decision"] == expected_decision,
            {
                "recorded_summary": summary,
                "expected_summary": expected_summary,
                "recorded_decision": first["hypothesis"]["decision"],
                "expected_decision": expected_decision,
            },
        )
    )

    return {
        "schema_version": 1,
        "experiment_id": first["experiment_id"],
        "artifact_integrity": "PASS" if all(row["status"] == "PASS" for row in checks) else "FAIL",
        "underlying_hypothesis_decision": first["hypothesis"]["decision"],
        "checks_passed": sum(row["status"] == "PASS" for row in checks),
        "checks_total": len(checks),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.first.resolve(), args.second.resolve())
    output = args.out.resolve()
    try:
        output.relative_to(ARTIFACT_DIR)
    except ValueError as error:
        raise SystemExit(f"refusing to write outside {ARTIFACT_DIR}: {output}") from error
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "artifact_integrity": result["artifact_integrity"],
                "checks": f"{result['checks_passed']}/{result['checks_total']}",
                "underlying_hypothesis_decision": result["underlying_hypothesis_decision"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["artifact_integrity"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

