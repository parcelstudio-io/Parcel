"""Independent stdlib-only verifier for retained MA-2-P0 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TOP_LEVEL = {
    "schema_version",
    "header",
    "freshness",
    "robot_estimate",
    "local_world",
    "mission",
    "path",
    "dialogue",
    "safety",
    "history",
    "semantic_map",
}
FORBIDDEN = (
    "truth",
    "oracle",
    "scorer",
    "actual_pose",
    "distance_to_goal",
    "inside_region",
    "collision_clearance",
    "future",
    "gold",
    "teacher_status",
)
ZERO_HASH = "0" * 64
ROLES = ("door", "sofa", "bench", "elevator", "keys")
FAMILIES = ("plain", "interrupt_now", "queue_resume")


class VerificationError(RuntimeError):
    pass


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


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(value) + b"\n")
    temporary.replace(path)


def zstd_rows(path: Path) -> Iterator[dict[str, Any]]:
    process = subprocess.run(
        ["zstd", "-q", "-dc", str(path)],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if process.returncode:
        raise VerificationError(f"zstd decode failed for {path}: {process.stderr.decode('utf-8')}")
    for line in process.stdout.splitlines():
        yield json.loads(line)


def walk_keys(value: object, prefix: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path
            yield from walk_keys(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_keys(child, f"{prefix}[{index}]")


def expected_transaction(family: str) -> list[str]:
    if family == "plain":
        return ["parent_submitted", "parent_dispatched", "parent_terminal_receipt"]
    common_tail = [
        "child_terminal_receipt",
        "resume_offer",
        "owner_resume_accepted",
        "resume_proposal_admitted",
        "parent_resumed",
        "parent_redispatched",
        "parent_terminal_receipt",
    ]
    if family == "interrupt_now":
        return [
            "parent_submitted",
            "parent_dispatched",
            "steering_accepted",
            "parent_suspended",
            "child_submitted",
            "child_dispatched",
            *common_tail,
        ]
    return [
        "parent_submitted",
        "parent_dispatched",
        "steering_accepted",
        "child_submitted",
        "child_waiting_resource",
        "interrupt_steering_accepted",
        "parent_suspended",
        "child_dispatched",
        *common_tail,
    ]


def verify_trace(path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if file_sha256(path) != metadata["sha256"]:
        raise VerificationError(f"trace file digest mismatch: {path.name}")
    previous = ZERO_HASH
    frames = 0
    contacts = 0
    unsafe = 0
    label_equal = 0
    claims = 0
    wrong_claims = 0
    transaction: list[str] = []
    last_terminal = False
    receipt_sequences: list[int] = []
    for expected_frame, row in enumerate(zstd_rows(path)):
        if row.get("episode_id") != metadata["episode_id"]:
            raise VerificationError(f"episode identity mismatch: {path.name}")
        if row.get("frame") != expected_frame:
            raise VerificationError(f"non-contiguous frame at {path.name}:{expected_frame}")
        row_hash = row.get("row_hash")
        if row.get("previous_row_hash") != previous:
            raise VerificationError(f"broken previous-row chain at {path.name}:{expected_frame}")
        unsigned = dict(row)
        unsigned.pop("row_hash", None)
        if digest(unsigned) != row_hash:
            raise VerificationError(f"row hash mismatch at {path.name}:{expected_frame}")
        previous = str(row_hash)
        payload = row["policy_input"]
        if set(payload) != TOP_LEVEL:
            raise VerificationError(f"policy allow-list mismatch at {path.name}:{expected_frame}")
        if digest(payload) != row["policy_input_sha256"]:
            raise VerificationError(f"policy digest mismatch at {path.name}:{expected_frame}")
        lowered = [key.lower() for key in walk_keys(payload)]
        if any(fragment in key for fragment in FORBIDDEN for key in lowered):
            raise VerificationError(f"forbidden causal field at {path.name}:{expected_frame}")
        if payload["freshness"]["observed_at_ns"] > payload["header"]["monotonic_ns"]:
            raise VerificationError(f"future sensor record at {path.name}:{expected_frame}")
        target_ref = payload["mission"]["target_ref"]
        candidates = payload["semantic_map"]["candidates"]
        if (
            len(candidates) != 15
            or sum(row["entity_uuid"] == target_ref for row in candidates) != 1
        ):
            raise VerificationError(
                f"target pointer not uniquely resolved at {path.name}:{expected_frame}"
            )
        applied = row["actions"]["actuator_applied"]
        if set(applied) != {"vx", "vy", "vyaw"}:
            raise VerificationError(
                f"applied action schema mismatch at {path.name}:{expected_frame}"
            )
        if (
            hashlib.sha256(canonical_bytes(applied)).hexdigest()
            != row["actions"]["world_apply_argument_sha256"]
        ):
            raise VerificationError(f"application digest mismatch at {path.name}:{expected_frame}")
        if row["actions"]["safety_admitted"] != applied or not row["actions"]["label_apply_equal"]:
            raise VerificationError(
                f"applied-label invariant failed at {path.name}:{expected_frame}"
            )
        label_equal += 1
        score = row["scorer_only"]
        if score["exact_target_entity_uuid"] != target_ref:
            raise VerificationError(
                f"scorer target differs from mission target at {path.name}:{expected_frame}"
            )
        receipt = row["narrative_receipt"]
        if receipt is not None:
            claims += 1
            tuple_pairs = (
                ("task_id", "task_id"),
                ("plan_revision", "revision"),
                ("step_id", "step_id"),
                ("attempt", "attempt"),
                ("target_entity_uuid", "target_ref"),
            )
            for receipt_key, mission_key in tuple_pairs:
                if receipt[receipt_key] != payload["mission"][mission_key]:
                    raise VerificationError(
                        f"receipt tuple mismatch {receipt_key} at {path.name}:{expected_frame}"
                    )
            if receipt["target_entity_uuid"] != score["exact_target_entity_uuid"]:
                wrong_claims += 1
            if not score["exact_success_rising_edge"]:
                raise VerificationError(
                    f"terminal receipt without exact success at {path.name}:{expected_frame}"
                )
            if len(receipt["evidence_refs"]) != 1:
                raise VerificationError(
                    f"receipt evidence cardinality at {path.name}:{expected_frame}"
                )
            receipt_sequences.append(int(receipt["sequence"]))
        contacts = max(contacts, int(score["contact_count"]))
        unsafe += int(score["unsafe_after_gate"])
        transaction.extend(row["transaction_events"])
        last_terminal = bool(row["episode_terminal"])
        if last_terminal and expected_frame + 1 != metadata["frames"]:
            raise VerificationError(
                f"early episode-terminal marker at {path.name}:{expected_frame}"
            )
        frames += 1
    if not frames or not last_terminal:
        raise VerificationError(f"trace is missing complete terminal row: {path.name}")
    if frames != metadata["frames"]:
        raise VerificationError(f"trace frame count mismatch: {path.name}")
    if previous != metadata["episode_root"]:
        raise VerificationError(f"episode root mismatch: {path.name}")
    family = row["task_family"]
    if transaction != expected_transaction(family):
        raise VerificationError(f"transaction order mismatch: {path.name}")
    wanted_receipts = 1 if family == "plain" else 2
    if claims != wanted_receipts or receipt_sequences != list(range(1, wanted_receipts + 1)):
        raise VerificationError(f"terminal receipt inventory mismatch: {path.name}")
    return {
        "episode_id": metadata["episode_id"],
        "scene_id": row["scene_id"],
        "target_role": row["target_role"],
        "task_family": family,
        "success": last_terminal,
        "frames": frames,
        "contacts": contacts,
        "unsafe": unsafe,
        "label_equal": label_equal,
        "claims": claims,
        "wrong_claims": wrong_claims,
        "transaction_exact": True,
        "episode_root": previous,
    }


def mutual_information(rows: list[dict[str, Any]], x: str, y: str) -> float:
    n = len(rows)
    cx = Counter(str(row[x]) for row in rows)
    cy = Counter(str(row[y]) for row in rows)
    joint = Counter((str(row[x]), str(row[y])) for row in rows)
    total = 0.0
    for (xv, yv), count in joint.items():
        pxy = count / n
        total += pxy * math.log2(pxy / ((cx[xv] / n) * (cy[yv] / n)))
    return total


def verify_all() -> dict[str, Any]:
    prerun_path = HERE / "manifest.prerun.json"
    manifest_path = HERE / "manifest.json"
    results_path = HERE / "results.json"
    inventory_path = HERE / "manifests/qualify.json"
    prerun = load(prerun_path)
    manifest = load(manifest_path)
    results = load(results_path)
    inventory = load(inventory_path)
    prerun_hash = file_sha256(prerun_path)
    if (
        manifest["prerun_manifest_sha256"] != prerun_hash
        or results["prerun_manifest_sha256"] != prerun_hash
    ):
        raise VerificationError("prerun manifest binding mismatch")
    if manifest["results_sha256"] != file_sha256(results_path):
        raise VerificationError("results digest mismatch")
    if (
        digest(inventory) != prerun["inventory_sha256"]
        or manifest["inventory_sha256"] != prerun["inventory_sha256"]
    ):
        raise VerificationError("qualification inventory digest mismatch")
    if len(inventory) != 300 or len({row["episode_id"] for row in inventory}) != 300:
        raise VerificationError("qualification inventory must have 300 unique episodes")
    cross = Counter((row["scene_id"], row["target_role"], row["task_family"]) for row in inventory)
    expected_cross = {
        (f"scene-{scene:02d}", role, family)
        for scene in range(10)
        for role in ROLES
        for family in FAMILIES
    }
    if set(cross) != expected_cross or set(cross.values()) != {2}:
        raise VerificationError("scene/role/task cross product is incomplete")
    mi_role = mutual_information(inventory, "scene_id", "target_role")
    mi_task = mutual_information(inventory, "scene_id", "task_family")
    if max(mi_role, mi_task) > 0.01:
        raise VerificationError("deconfounding mutual-information bound failed")
    for relative, expected in prerun["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or file_sha256(path) != expected:
            raise VerificationError(f"source provenance mismatch: {relative}")
    source_findings = []
    for name in ("p0_teacher.py", "p0_observation.py"):
        text = (HERE / name).read_text()
        for token in (
            "parcel_robot.sim",
            "HeadlessCityWorld",
            "WorldTruth",
            "target_truth",
            "scorer_only",
            "actual_pose",
        ):
            if token in text:
                source_findings.append(f"{name}:{token}")
    if source_findings:
        raise VerificationError(f"source firewall scan failed: {source_findings}")
    traces = manifest["episode_traces"]
    if len(traces) != 300 or len({row["episode_id"] for row in traces}) != 300:
        raise VerificationError("trace inventory must bind 300 unique episodes")
    verified = [verify_trace(HERE / row["path"], row) for row in traces]
    result_index = {row["episode_id"]: row for row in results["episodes"]}
    for row in verified:
        reported = result_index.get(row["episode_id"])
        if reported is None:
            raise VerificationError(f"results missing episode {row['episode_id']}")
        for key, reported_key in (
            ("frames", "frames"),
            ("contacts", "contacts"),
            ("unsafe", "unsafe_after_gate"),
            ("label_equal", "label_apply_equal"),
            ("claims", "terminal_claims"),
            ("wrong_claims", "wrong_target_claims"),
            ("transaction_exact", "transaction_exact"),
            ("episode_root", "episode_root"),
        ):
            if row[key] != reported[reported_key]:
                raise VerificationError(f"episode aggregate mismatch {row['episode_id']}:{key}")
    trace_root = digest(
        [
            {
                "episode_id": row["episode_id"],
                "episode_root": row["episode_root"],
                "trace_sha256": row["sha256"],
            }
            for row in traces
        ]
    )
    if (
        trace_root != manifest["trace_inventory_root"]
        or trace_root != results["trace_inventory_root"]
    ):
        raise VerificationError("trace inventory root mismatch")
    successes = sum(row["success"] for row in verified)
    frames = sum(row["frames"] for row in verified)
    claims = sum(row["claims"] for row in verified)
    wrong = sum(row["wrong_claims"] for row in verified)
    strata = Counter((row["target_role"], row["task_family"]) for row in verified if row["success"])
    stratum_total = Counter((row["target_role"], row["task_family"]) for row in verified)
    corruption = results["corruption_suite"]
    corruption_ok = all(
        row["accepted"] == row["expected_accept"]
        and (row["accepted"] or row["state_unchanged_on_reject"])
        for row in corruption["cases"]
    )
    replay_ok = (
        results["replay"]["episodes"] == 30
        and results["replay"]["identical"] == 30
        and all(
            row["persisted_root"] == row["replay_a_root"] == row["replay_b_root"]
            for row in results["replay"]["rows"]
        )
    )
    recomputed_gates = {
        "teacher_overall": successes / 300 >= 0.80,
        "teacher_each_stratum": all(
            strata[key] / stratum_total[key] >= 0.70 for key in stratum_total
        ),
        "terminal_precision": claims > 0 and (claims - wrong) / claims == 1.0,
        "zero_contacts": sum(row["contacts"] for row in verified) == 0,
        "zero_post_gate_unsafe": sum(row["unsafe"] for row in verified) == 0,
        "applied_label_exact": sum(row["label_equal"] for row in verified) == frames,
        "oracle_firewall": bool(results["oracle_firewall"]["pass"])
        and results["oracle_firewall"]["payload_sha256_before"]
        == results["oracle_firewall"]["payload_sha256_after_sentinel_truth_change"]
        and results["oracle_firewall"]["extra_private_field_rejected"],
        "exact_target_fixture": bool(results["exact_target_fixture"]["pass"])
        and results["exact_target_fixture"]["semantic_role_equal"]
        and results["exact_target_fixture"]["wrong_instance_rejected"],
        "transactions_exact": all(row["transaction_exact"] for row in verified),
        "zero_ineligible_resume": results["aggregates"]["transactions"][
            "ineligible_resume_admissions"
        ]
        == 0,
        "corruptions_rejected": corruption_ok,
        "deterministic_replay": replay_ok,
        "deconfounded": max(mi_role, mi_task) <= 0.01,
        "source_scan": not source_findings,
    }
    if recomputed_gates != results["gates"]:
        raise VerificationError("reported gates differ from independent recomputation")
    expected_status = (
        "PASS_TO_CORPUS_DESIGN" if all(recomputed_gates.values()) else "INVALID_PRECONDITION"
    )
    if results["status"] != expected_status:
        raise VerificationError("reported status differs from recomputed status")
    return {
        "verifier": "MA-2-P0 independent stdlib verifier v1",
        "status": "PASS" if all(recomputed_gates.values()) else "FAIL",
        "episodes_verified": len(verified),
        "frames_verified": frames,
        "trace_inventory_root": trace_root,
        "prerun_manifest_sha256": prerun_hash,
        "teacher_successes": successes,
        "teacher_episodes": 300,
        "terminal_claims": claims,
        "wrong_target_claims": wrong,
        "corruption_cases": len(corruption["cases"]),
        "replay_pairs": 30,
        "mutual_information_bits": {"scene_target": mi_role, "scene_task": mi_task},
        "gates": recomputed_gates,
    }


def tamper_test() -> dict[str, Any]:
    manifest = load(HERE / "manifest.json")
    first = manifest["episode_traces"][0]
    source = HERE / first["path"]
    with tempfile.TemporaryDirectory(prefix="ma2-p0-tamper-") as directory:
        root = Path(directory)
        raw = root / "mutated.jsonl"
        rows = list(zstd_rows(source))
        rows[0]["actions"]["actuator_applied"]["vx"] = (
            float(rows[0]["actions"]["actuator_applied"]["vx"]) + 0.001
        )
        with raw.open("wb") as handle:
            for row in rows:
                handle.write(canonical_bytes(row) + b"\n")
        compressed = root / "mutated.jsonl.zst"
        subprocess.run(["zstd", "-q", "-f", "-3", str(raw), "-o", str(compressed)], check=True)
        metadata = dict(first)
        metadata["sha256"] = file_sha256(compressed)
        rejected = False
        reason = ""
        try:
            verify_trace(compressed, metadata)
        except VerificationError as error:
            rejected = True
            reason = str(error)
    return {
        "mutation": "first actuator_applied.vx changed by +0.001; container hash updated only",
        "expected": "reject",
        "rejected": rejected,
        "reason": reason,
        "pass": rejected,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "verification.json")
    parser.add_argument("--tamper-output", type=Path, default=HERE / "tamper-test.json")
    parser.add_argument("--skip-tamper", action="store_true")
    args = parser.parse_args()
    try:
        report = verify_all()
    except Exception as error:  # noqa: BLE001 - verifier must emit a durable refusal
        report = {
            "verifier": "MA-2-P0 independent stdlib verifier v1",
            "status": "FAIL",
            "error": f"{type(error).__name__}: {error}",
        }
        write_json(args.output, report)
        print(json.dumps(report, indent=2))
        return 1
    write_json(args.output, report)
    if not args.skip_tamper:
        tamper = tamper_test()
        write_json(args.tamper_output, tamper)
        if not tamper["pass"]:
            print(json.dumps({"verification": report, "tamper": tamper}, indent=2))
            return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
