#!/usr/bin/env python
"""Independent, stdlib-only verifier for retained DMC-2 traces.

This module intentionally does not import Parcel's executive, receipt reducer,
or claim license. It checks their serialized observations against the frozen
case oracle and validates all state digests directly from the trace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
MANIFEST_PATH = HERE / "manifest.json"

EXPECTED: dict[str, dict[str, dict[str, object]]] = {
    "executive": {
        "valid_succeeded": {
            "accepted": True,
            "action": "task_succeeded",
            "state": "succeeded",
        },
        "wrong_task": {
            "accepted": False,
            "action": "ignored_unknown_task",
            "state": "running",
        },
        "wrong_revision": {
            "accepted": False,
            "action": "ignored_stale_result",
            "state": "running",
        },
        "wrong_step": {
            "accepted": False,
            "action": "ignored_stale_result",
            "state": "running",
        },
        "wrong_attempt": {
            "accepted": False,
            "action": "ignored_stale_result",
            "state": "running",
        },
        "not_running": {
            "accepted": False,
            "action": "ignored_stale_result",
            "state": "queued",
        },
        "unverified_success": {
            "accepted": True,
            "action": "task_failed",
            "state": "failed",
        },
        "post_terminal": {
            "accepted": False,
            "action": "ignored_stale_result",
            "state": "succeeded",
        },
    },
    "receipt": {
        "valid_succeeded": {
            "accepted": True,
            "disposition": "terminal",
            "reason": "matching_local_receipt",
            "pending_state": None,
            "completed": True,
        },
        "raw_untrusted": {
            "accepted": False,
            "disposition": "ignored",
            "reason": "receipt_authentication_failed",
            "pending_state": "admitted",
            "completed": False,
        },
        "wrong_channel": {
            "accepted": False,
            "disposition": "ignored",
            "reason": "receipt_authentication_failed",
            "pending_state": "admitted",
            "completed": False,
        },
        "wrong_action": {
            "accepted": False,
            "disposition": "ignored",
            "reason": "receipt_action_mismatch",
            "pending_state": "admitted",
            "completed": False,
        },
        "premature_terminal": {
            "accepted": False,
            "disposition": "ignored",
            "reason": "invalid_receipt_transition",
            "pending_state": "admitted",
            "completed": False,
        },
        "duplicate": {
            "accepted": False,
            "disposition": "duplicate",
            "reason": "receipt_already_recorded",
            "pending_state": "started",
            "completed": False,
        },
        "sequence_regression": {
            "accepted": False,
            "disposition": "ignored",
            "reason": "receipt_sequence_regression",
            "pending_state": "started",
            "completed": False,
        },
        "timestamp_regression": {
            "accepted": False,
            "disposition": "ignored",
            "reason": "receipt_timestamp_regression",
            "pending_state": "started",
            "completed": False,
        },
        "future": {
            "accepted": False,
            "disposition": "ignored",
            "reason": "receipt_from_future",
            "pending_state": "started",
            "completed": False,
        },
        "expired": {
            "accepted": False,
            "disposition": "ignored",
            "reason": "receipt_expired",
            "pending_state": "started",
            "completed": False,
        },
        "post_terminal": {
            "accepted": False,
            "disposition": "ignored",
            "reason": "no_pending_action",
            "pending_state": None,
            "completed": True,
        },
    },
    "claim": {
        "valid_terminal": {"licensed": True, "reason": "matching_local_terminal_receipt"},
        "start_receipt": {"licensed": False, "reason": "receipt_not_terminal"},
        "wrong_channel": {"licensed": False, "reason": "receipt_authentication_failed"},
        "wrong_receipt_id": {
            "licensed": False,
            "reason": "authenticated_receipt_identity_mismatch",
        },
        "wrong_mission": {
            "licensed": False,
            "reason": "terminal_receipt_identity_mismatch",
        },
        "wrong_action": {
            "licensed": False,
            "reason": "terminal_receipt_identity_mismatch",
        },
        "wrong_name": {
            "licensed": False,
            "reason": "terminal_receipt_identity_mismatch",
        },
        "wrong_manifest": {
            "licensed": False,
            "reason": "terminal_receipt_identity_mismatch",
        },
        "wrong_status": {"licensed": False, "reason": "terminal_status_mismatch"},
        "unretained": {"licensed": False, "reason": "receipt_not_retained"},
        "future_proposal": {"licensed": False, "reason": "claim_proposal_from_future"},
        "stale_proposal": {
            "licensed": False,
            "reason": "claim_proposal_ttl_exceeds_limit",
        },
        "expired_receipt": {
            "licensed": False,
            "reason": "terminal_receipt_stale_or_future",
        },
        "unrelated_receipt": {
            "licensed": False,
            "reason": "terminal_receipt_identity_mismatch",
        },
    },
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def _contains_forbidden_secret(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"auth_tag", "key", "secret"}
            or _contains_forbidden_secret(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_secret(item) for item in value)
    return False


def _task_state(state: dict[str, object]) -> str:
    tasks = state.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], dict):
        raise ValueError("executive trace must contain exactly one task")
    value = tasks[0].get("state")
    if not isinstance(value, str):
        raise ValueError("executive task state missing")
    return value


def _row_state_ok(row: dict[str, object]) -> bool:
    seam = row["seam"]
    corruption = row["corruption"]
    pre = row["pre_state"]
    post = row["post_state"]
    if not isinstance(pre, dict) or not isinstance(post, dict):
        return False
    unchanged = digest(pre) == digest(post)
    if seam == "executive":
        post_task_state = _task_state(post)
        if corruption == "valid_succeeded":
            return post_task_state == "succeeded"
        if corruption == "unverified_success":
            return post_task_state == "failed"
        return unchanged
    if seam == "receipt":
        if corruption == "valid_succeeded":
            return post.get("pending_action") is None and post.get("last_completed_action") is not None
        return unchanged
    if seam == "claim":
        return unchanged and row.get("verified_claim") is (
            corruption == "valid_terminal"
        )
    return False


def expected_case_ids(manifest: dict[str, object]) -> set[str]:
    count = int(manifest["trials_per_seam"])
    seams = manifest["seams"]
    if not isinstance(seams, dict):
        raise ValueError("manifest seams missing")
    return {
        f"{seam}-{trial:04d}-{corruption}"
        for trial in range(count)
        for seam, corruptions in seams.items()
        for corruption in corruptions
    }


def _raw_aggregates(traces: list[dict[str, object]]) -> dict[str, object]:
    aggregate: dict[str, object] = {}
    for seam in EXPECTED:
        rows = [row for row in traces if row.get("seam") == seam]
        controls = [
            row for row in rows if str(row.get("corruption", "")).startswith("valid_")
        ]
        corruptions = [row for row in rows if row not in controls]
        reasons: dict[str, int] = {}
        actions: dict[str, int] = {}
        for row in rows:
            observed = row.get("observed")
            if not isinstance(observed, dict):
                continue
            reason = observed.get("reason")
            action = observed.get("action")
            if reason is not None:
                reasons[str(reason)] = reasons.get(str(reason), 0) + 1
            if action is not None:
                actions[str(action)] = actions.get(str(action), 0) + 1
        aggregate[seam] = {
            "cases": len(rows),
            "controls": len(controls),
            "corruptions": len(corruptions),
            "accepted": sum(
                bool(row["observed"].get("accepted"))
                for row in rows
                if isinstance(row.get("observed"), dict)
            ),
            "licensed": sum(
                bool(row["observed"].get("licensed"))
                for row in rows
                if isinstance(row.get("observed"), dict)
            ),
            "verified_claims": sum(bool(row.get("verified_claim")) for row in rows),
            "state_changed": sum(
                row.get("state_digest_before") != row.get("state_digest_after")
                for row in rows
            ),
            "reason_histogram": dict(sorted(reasons.items())),
            "action_histogram": dict(sorted(actions.items())),
        }
    return aggregate


def verify_one(result: dict[str, object], manifest: dict[str, object]) -> dict[str, object]:
    errors: list[str] = []
    traces = result.get("traces")
    if not isinstance(traces, list):
        return {"passed": False, "errors": ["traces missing"]}
    expected_ids = expected_case_ids(manifest)
    actual_ids = [row.get("case_id") for row in traces if isinstance(row, dict)]
    counts = Counter(actual_ids)
    duplicate_ids = sorted(str(key) for key, count in counts.items() if count != 1)
    if set(actual_ids) != expected_ids:
        errors.append("case inventory mismatch")
    if duplicate_ids:
        errors.append(f"duplicate case IDs: {duplicate_ids[:5]}")
    if result.get("frozen_population_complete") is not True:
        errors.append("result is not the complete frozen population")
    if result.get("trials_per_seam") != manifest.get("trials_per_seam"):
        errors.append("trial count mismatch")
    if result.get("manifest_sha256") != file_sha256(MANIFEST_PATH):
        errors.append("manifest hash mismatch")
    if result.get("normalized_trace_sha256") != digest(traces):
        errors.append("normalized trace digest mismatch")
    recorded_result_sha = result.get("result_sha256")
    if recorded_result_sha != digest(
        {key: value for key, value in result.items() if key != "result_sha256"}
    ):
        errors.append("result payload hash mismatch")
    if _contains_forbidden_secret(traces):
        errors.append("trace contains authentication secret material")

    failed_rows: list[str] = []
    passed_by_seam = {seam: 0 for seam in EXPECTED}
    previous = "0" * 64
    for raw in traces:
        if not isinstance(raw, dict):
            errors.append("non-object trace row")
            continue
        seam = raw.get("seam")
        corruption = raw.get("corruption")
        expected = EXPECTED.get(str(seam), {}).get(str(corruption))
        recorded_event_hash = raw.get("event_sha256")
        hash_payload = {key: value for key, value in raw.items() if key != "event_sha256"}
        chain_ok = (
            raw.get("previous_event_sha256") == previous
            and recorded_event_hash == digest(hash_payload)
        )
        if isinstance(recorded_event_hash, str):
            previous = recorded_event_hash
        checks = [
            expected is not None,
            raw.get("observed") == expected,
            raw.get("state_digest_before") == digest(raw.get("pre_state")),
            raw.get("state_digest_after") == digest(raw.get("post_state")),
            _row_state_ok(raw),
            "expected" not in raw,
            "oracle_pass" not in raw,
            chain_ok,
        ]
        if not all(checks):
            failed_rows.append(str(raw.get("case_id")))
        elif seam in passed_by_seam:
            passed_by_seam[str(seam)] += 1
    if failed_rows:
        errors.append(f"trace oracle failures: {failed_rows[:10]}")
    if result.get("trace_chain_root_sha256") != previous:
        errors.append("trace chain root mismatch")

    oracle_aggregates: dict[str, dict[str, int]] = {}
    for seam in EXPECTED:
        rows = [row for row in traces if isinstance(row, dict) and row.get("seam") == seam]
        controls = [
            row for row in rows if str(row.get("corruption", "")).startswith("valid_")
        ]
        corruptions = [row for row in rows if row not in controls]
        oracle_aggregates[seam] = {
            "cases": len(rows),
            "controls": len(controls),
            "corruptions": len(corruptions),
            "oracle_passed": passed_by_seam[seam],
        }
    recomputed_raw = _raw_aggregates(
        [row for row in traces if isinstance(row, dict)]
    )
    if result.get("aggregates") != recomputed_raw:
        errors.append("aggregate mismatch")
    hypotheses = result.get("hypotheses")
    if not isinstance(hypotheses, dict):
        errors.append("hypotheses missing")
    else:
        for name in ("H1", "H2", "H3", "H4"):
            value = hypotheses.get(name)
            if not isinstance(value, dict) or value.get("passed") is not None:
                errors.append(f"runner improperly adjudicated {name}")

    architecture_gate = result.get("architecture_gate")
    if (
        not isinstance(architecture_gate, dict)
        or architecture_gate.get("status") != "NOT_EVALUABLE_RED"
    ):
        errors.append("architecture gap was not held red")

    required_sources = {
        "research/20260829/duplex-transaction-2/manifest.json",
        "research/20260829/duplex-transaction-2/DESIGN.md",
        "research/20260829/duplex-transaction-2/AMENDMENTS.md",
        "research/20260829/duplex-transaction-2/run.py",
        "src/parcel_robot/brain/executive.py",
        "src/parcel_robot/voice/companion_state.py",
        "src/parcel_robot/voice/companion_auth.py",
    }
    source_hashes = result.get("source_hashes")
    if not isinstance(source_hashes, dict) or set(source_hashes) != required_sources:
        errors.append("source hash inventory mismatch")
    else:
        for relative, expected_hash in source_hashes.items():
            path = REPO_ROOT / relative
            if not path.is_file() or file_sha256(path) != expected_hash:
                errors.append(f"source hash mismatch: {relative}")

    return {
        "passed": not errors,
        "errors": errors,
        "case_count": len(traces),
        "normalized_trace_sha256": result.get("normalized_trace_sha256"),
        "trace_chain_root_sha256": result.get("trace_chain_root_sha256"),
        "oracle_aggregates": oracle_aggregates,
        "recomputed_raw_aggregates": recomputed_raw,
        "H1_passed": oracle_aggregates["executive"]["oracle_passed"]
        == oracle_aggregates["executive"]["cases"],
        "H2_passed": oracle_aggregates["receipt"]["oracle_passed"]
        == oracle_aggregates["receipt"]["cases"],
        "H3_passed": oracle_aggregates["claim"]["oracle_passed"]
        == oracle_aggregates["claim"]["cases"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run1", type=Path)
    parser.add_argument("run2", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    run1 = json.loads(args.run1.read_text(encoding="utf-8"))
    run2 = json.loads(args.run2.read_text(encoding="utf-8"))
    first = verify_one(run1, manifest)
    second = verify_one(run2, manifest)
    same_digest = (
        first.get("normalized_trace_sha256")
        == second.get("normalized_trace_sha256")
    )
    seam_hypotheses = {
        name: bool(first[f"{name}_passed"] and second[f"{name}_passed"])
        for name in ("H1", "H2", "H3")
    }
    h4_passed = bool(first["passed"] and second["passed"] and same_digest)
    passed = bool(all(seam_hypotheses.values()) and h4_passed)
    report = {
        "schema_version": 1,
        "suite_id": manifest["suite_id"],
        "passed": passed,
        "hypotheses": {**seam_hypotheses, "H4": h4_passed},
        "seam_gate_passed": all(seam_hypotheses.values()) and h4_passed,
        "architecture_gate": "NOT_EVALUABLE_RED",
        "run1": first,
        "run2": second,
        "normalized_trace_digests_equal": same_digest,
        "manifest_sha256": file_sha256(MANIFEST_PATH),
        "verifier_sha256": file_sha256(Path(__file__)),
        "verifier_imports_product_reducers": False,
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
