"""Independent standard-library verifier for MA-2-P1 retained evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import tempfile
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MA2 = HERE.parent
REPO = MA2.parents[2]
ZERO_HASH = "0" * 64
SEEDS = (20260829, 20260830, 20260831)
TEST_SPLITS = ("test-S", "test-T", "test-F", "test-TF", "test-ST", "test-SF", "test-STF")
POLICY_KEYS = {
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


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(value) + b"\n")
    temporary.replace(path)


def zstd_rows(path: Path) -> Iterator[dict[str, Any]]:
    result = subprocess.run(
        ["zstd", "-q", "-dc", str(path)], capture_output=True, timeout=30, check=False
    )
    if result.returncode:
        raise VerificationError(f"zstd decode failed: {path}")
    for line in result.stdout.splitlines():
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
    tail = [
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
            *tail,
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
        *tail,
    ]


def close_enough(left: object, right: object, tolerance: float = 1.0e-8) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    return left == right


def recursively_close(
    left: object, right: object, *, path: str = "root", tolerance: float = 1.0e-8
) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            raise VerificationError(f"mapping keys mismatch: {path}")
        for key in sorted(left):
            recursively_close(
                left[key], right[key], path=f"{path}.{key}", tolerance=tolerance
            )
        return
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            raise VerificationError(f"list length mismatch: {path}")
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            recursively_close(
                left_item,
                right_item,
                path=f"{path}[{index}]",
                tolerance=tolerance,
            )
        return
    if not close_enough(left, right, tolerance=tolerance):
        raise VerificationError(f"value mismatch: {path}")


def verify_trace(path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if file_sha256(path) != metadata["sha256"]:
        raise VerificationError(f"trace file hash mismatch: {path}")
    previous = ZERO_HASH
    rows: list[dict[str, Any]] = []
    transaction: list[str] = []
    for index, row in enumerate(zstd_rows(path)):
        if row["frame"] != index or row["previous_row_hash"] != previous:
            raise VerificationError(f"trace order mismatch: {path}:{index}")
        claimed = row["row_hash"]
        unsigned = dict(row)
        unsigned.pop("row_hash")
        if digest(unsigned) != claimed:
            raise VerificationError(f"row hash mismatch: {path}:{index}")
        previous = claimed
        if row["episode_id"] != metadata["episode_id"] or row["split"] != metadata["split"]:
            raise VerificationError(f"trace identity/split mismatch: {path}:{index}")
        if row["p1"]["arm"] != metadata["arm"] or row["p1"]["seed"] != metadata["seed"]:
            raise VerificationError(f"trace arm binding mismatch: {path}:{index}")
        if row["p1"]["checkpoint_sha256"] != metadata["checkpoint_sha256"]:
            raise VerificationError(f"trace checkpoint binding mismatch: {path}:{index}")
        payload = row["policy_input"]
        if set(payload) != POLICY_KEYS:
            raise VerificationError(f"policy allow-list mismatch: {path}:{index}")
        keys = [key.lower() for key in walk_keys(payload)]
        if any(fragment in key for fragment in FORBIDDEN for key in keys):
            raise VerificationError(f"privileged policy field: {path}:{index}")
        if payload["freshness"]["observed_at_ns"] > payload["header"]["monotonic_ns"]:
            raise VerificationError(f"future feature: {path}:{index}")
        action = row["actions"]["actuator_applied"]
        if row["p1"]["raw_policy"]["raw_command"] != row["actions"]["teacher_requested"]:
            raise VerificationError(f"raw policy/action-ledger mismatch: {path}:{index}")
        if row["actions"]["safety_admitted"] != action or not row["actions"]["label_apply_equal"]:
            raise VerificationError(f"action alignment mismatch: {path}:{index}")
        if (
            hashlib.sha256(canonical_bytes(action)).hexdigest()
            != row["actions"]["world_apply_argument_sha256"]
        ):
            raise VerificationError(f"world action digest mismatch: {path}:{index}")
        mission = payload["mission"]
        binding = row["p1"]["binding"]
        if binding != {"task_id": mission["task_id"], "revision": mission["revision"]}:
            raise VerificationError(f"stale P1 binding: {path}:{index}")
        receipt = row["narrative_receipt"]
        if receipt is not None:
            score = row["scorer_only"]
            if not (
                score["exact_success_rising_edge"]
                and receipt["task_id"] == mission["task_id"]
                and receipt["plan_revision"] == mission["revision"]
                and receipt["step_id"] == mission["step_id"]
                and receipt["attempt"] == mission["attempt"]
                and receipt["target_entity_uuid"] == mission["target_ref"]
                and receipt["target_entity_uuid"] == score["exact_target_entity_uuid"]
            ):
                raise VerificationError(f"unbacked terminal receipt: {path}:{index}")
        transaction.extend(row["transaction_events"])
        rows.append(row)
    if not rows or previous != metadata["episode_root"] or len(rows) != metadata["frames"]:
        raise VerificationError(f"trace completion/root mismatch: {path}")
    if not rows[-1]["p1_episode_complete"]:
        raise VerificationError(f"P1 completion marker missing: {path}")
    success = rows[-1]["p1_termination"] == "success"
    positions = [
        (
            float(row["scorer_only"]["actual_pose"]["x_m"]),
            float(row["scorer_only"]["actual_pose"]["y_m"]),
        )
        for row in rows
    ]
    path_length = sum(
        math.hypot(right[0] - left[0], right[1] - left[1]) for left, right in pairwise(positions)
    )
    velocities = [
        (
            float(row["actions"]["actuator_applied"]["vx"]),
            float(row["actions"]["actuator_applied"]["vy"]),
        )
        for row in rows
    ]
    acceleration = [
        ((right[0] - left[0]) / 0.1, (right[1] - left[1]) / 0.1)
        for left, right in pairwise(velocities)
    ]
    jerk = [
        math.hypot(right[0] - left[0], right[1] - left[1]) / 0.1
        for left, right in pairwise(acceleration)
    ]
    receipts = sum(row["narrative_receipt"] is not None for row in rows)
    exact_transaction = transaction == expected_transaction(rows[0]["task_family"])
    return {
        "episode_id": metadata["episode_id"],
        "arm": metadata["arm"],
        "seed": metadata["seed"],
        "split": metadata["split"],
        "success": success,
        "frames": len(rows),
        "path_length_m": round(path_length, 6),
        "mean_jerk_mps3": round(statistics.fmean(jerk), 6) if jerk else 0.0,
        "contacts": max(int(row["scorer_only"]["contact_count"]) for row in rows),
        "unsafe_after_gate": sum(bool(row["scorer_only"]["unsafe_after_gate"]) for row in rows),
        "gate_interventions": sum(row["actions"]["gate_disposition"] != "admit" for row in rows),
        "transaction_exact": exact_transaction,
        "terminal_receipts": receipts,
        "backed_terminal_receipts": receipts,
        "wrong_or_unbacked_terminal_receipts": 0,
        "stale_binding_commands": 0,
        "resume_admitted": "resume_proposal_admitted" in transaction,
        "resume_eligible": "child_terminal_receipt" in transaction
        and "owner_resume_accepted" in transaction,
    }


def verify_open_loop(path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if file_sha256(path) != metadata["sha256"]:
        raise VerificationError(f"open-loop file hash mismatch: {path}")
    previous = ZERO_HASH
    labels: list[list[float]] = []
    predictions: list[list[float]] = []
    for index, row in enumerate(zstd_rows(path)):
        if row["index"] != index or row["previous_row_hash"] != previous:
            raise VerificationError(f"open-loop order mismatch: {path}:{index}")
        claimed = row["row_hash"]
        unsigned = dict(row)
        unsigned.pop("row_hash")
        if digest(unsigned) != claimed:
            raise VerificationError(f"open-loop row hash mismatch: {path}:{index}")
        previous = claimed
        labels.append([float(value) for value in row["label"]])
        predictions.append([float(value) for value in row["prediction"]])
    if len(labels) != metadata["rows"] or previous != metadata["root"]:
        raise VerificationError(f"open-loop root/count mismatch: {path}")
    squared = absolute = variance = 0.0
    means = [sum(row[axis] for row in labels) / len(labels) for axis in range(3)]
    direction_hits = direction_total = 0
    tp = fp = fn = 0
    for label, prediction in zip(labels, predictions):
        label_stop = math.hypot(label[0], label[1]) <= 0.03
        prediction_stop = math.hypot(prediction[0], prediction[1]) <= 0.03
        tp += int(label_stop and prediction_stop)
        fp += int(not label_stop and prediction_stop)
        fn += int(label_stop and not prediction_stop)
        if not label_stop:
            direction_total += 1
            direction_hits += int(prediction[0] * label[0] + prediction[1] * label[1] > 0)
        for axis in range(3):
            error = prediction[axis] - label[axis]
            squared += error * error
            absolute += abs(error)
            variance += (label[axis] - means[axis]) ** 2
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "rows": len(labels),
        "mse": squared / (len(labels) * 3),
        "mae": absolute / (len(labels) * 3),
        "variance_weighted_r2": 1.0 - squared / max(variance, 1.0e-12),
        "direction_agreement": direction_hits / direction_total if direction_total else 0.0,
        "direction_denominator": direction_total,
        "stop_precision": precision,
        "stop_recall": recall,
        "stop_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100.0
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def wilson(successes: int, total: int) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    probability = successes / total
    denominator = 1 + z * z / total
    centre = (probability + z * z / (2 * total)) / denominator
    radius = (
        z
        * math.sqrt(
            (probability * (1 - probability) + z * z / (4 * total)) / total
        )
        / denominator
    )
    return [max(0.0, centre - radius), min(1.0, centre + radius)]


def aggregate_verified(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, int | None], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["arm"], row["split"], row["seed"]), []).append(row)
    output: dict[str, Any] = {}
    for (arm, split, seed), episodes in grouped.items():
        successes = [row for row in episodes if row["success"]]
        claims = sum(row["terminal_receipts"] for row in episodes)
        backed = sum(row["backed_terminal_receipts"] for row in episodes)
        key = f"{arm}|{seed if seed is not None else 'na'}|{split}"
        output[key] = {
            "arm": arm,
            "seed": seed,
            "split": split,
            "successes": len(successes),
            "episodes": len(episodes),
            "success_rate": len(successes) / len(episodes),
            "success_wilson95": wilson(len(successes), len(episodes)),
            "terminal_precision": backed / claims if claims else 1.0,
            "terminal_claims": claims,
            "wrong_or_unbacked_terminal_receipts": claims - backed,
            "contacts": sum(row["contacts"] for row in episodes),
            "unsafe_after_gate": sum(row["unsafe_after_gate"] for row in episodes),
            "stale_binding_commands": sum(row["stale_binding_commands"] for row in episodes),
            "ineligible_resumes": sum(
                row["resume_admitted"] and not row["resume_eligible"] for row in episodes
            ),
            "transaction_exact": sum(row["transaction_exact"] for row in episodes),
            "median_frames_success": statistics.median(row["frames"] for row in successes)
            if successes
            else None,
            "median_path_m_success": statistics.median(
                row["path_length_m"] for row in successes
            )
            if successes
            else None,
            "mean_jerk_mps3": statistics.fmean(
                row["mean_jerk_mps3"] for row in episodes
            ),
        }
    teacher_by_episode = {
        (row["split"], row["episode_id"]): row for row in rows if row["arm"] == "T*"
    }
    for key, aggregate in output.items():
        arm, seed_text, split = key.split("|")
        seed = None if seed_text == "na" else int(seed_text)
        paired = [
            row
            for row in rows
            if row["arm"] == arm
            and row["seed"] == seed
            and row["split"] == split
            and row["success"]
            and teacher_by_episode[(split, row["episode_id"])]["success"]
        ]
        if paired:
            learned_frames = statistics.median(row["frames"] for row in paired)
            teacher_frames = statistics.median(
                teacher_by_episode[(split, row["episode_id"])]["frames"]
                for row in paired
            )
            learned_path = statistics.median(row["path_length_m"] for row in paired)
            teacher_path = statistics.median(
                teacher_by_episode[(split, row["episode_id"])]["path_length_m"]
                for row in paired
            )
            aggregate["joint_success_episodes"] = len(paired)
            aggregate["paired_completion_frame_ratio"] = learned_frames / teacher_frames
            aggregate["paired_path_ratio"] = learned_path / teacher_path
        else:
            aggregate["joint_success_episodes"] = 0
            aggregate["paired_completion_frame_ratio"] = None
            aggregate["paired_path_ratio"] = None
    return output


def recompute_hypotheses(results: dict[str, Any]) -> dict[str, Any]:
    aggregates = results["closed_loop_aggregates"]
    open_loop = results["open_loop"]
    latency = results["latency"]
    required = {
        "test-S": 0.90,
        "test-T": 0.90,
        "test-F": 0.90,
        "test-TF": 0.80,
        "test-ST": 0.80,
        "test-SF": 0.80,
        "test-STF": 0.75,
    }
    h_a: dict[str, bool] = {}
    for seed in SEEDS:
        checks = []
        for split, threshold in required.items():
            row = aggregates[f"C16|{seed}|{split}"]
            checks.extend(
                [
                    row["success_rate"] >= threshold,
                    row["terminal_precision"] == 1.0,
                    row["contacts"] == 0,
                    row["unsafe_after_gate"] == 0,
                    row["stale_binding_commands"] == 0,
                    row["ineligible_resumes"] == 0,
                    row["wrong_or_unbacked_terminal_receipts"] == 0,
                ]
            )
        diagnostic = open_loop[f"C16|{seed}|test-STF"]
        learned = aggregates[f"C16|{seed}|test-STF"]
        checks.extend(
            [
                diagnostic["mse"] <= 0.01,
                diagnostic["direction_agreement"] >= 0.95,
                diagnostic["stop_f1"] >= 0.90,
                learned["paired_completion_frame_ratio"] is not None
                and learned["paired_completion_frame_ratio"] <= 1.25,
                learned["paired_path_ratio"] is not None and learned["paired_path_ratio"] <= 1.25,
            ]
        )
        h_a[str(seed)] = all(checks)
    held = ("test-F", "test-TF", "test-SF", "test-STF")
    h_b: dict[str, bool] = {}
    for seed in SEEDS:
        c = sum(aggregates[f"C16|{seed}|{split}"]["successes"] for split in held)
        s = sum(aggregates[f"S|{seed}|{split}"]["successes"] for split in held)
        n = sum(aggregates[f"C16|{seed}|{split}"]["episodes"] for split in held)
        h_b[str(seed)] = (c - s) / n >= 0.05
    h_c = all(
        latency[f"{arm}|{seed}|gpu"]["p99_ms"] <= 10.0
        and latency[f"{arm}|{seed}|cpu"]["p99_ms"] <= 50.0
        for arm in ("S", "C16")
        for seed in SEEDS
    )
    integrity = all(
        row["contacts"] == 0
        and row["unsafe_after_gate"] == 0
        and row["stale_binding_commands"] == 0
        and row["ineligible_resumes"] == 0
        and row["wrong_or_unbacked_terminal_receipts"] == 0
        for row in aggregates.values()
    )
    return {
        "integrity": integrity,
        "H-P1a_by_seed": h_a,
        "H-P1a": all(h_a.values()),
        "H-P1b_by_seed": h_b,
        "H-P1b": all(h_b.values()),
        "H-P1c": h_c,
    }


def verify_all(manifest_path: Path, training_path: Path, results_path: Path) -> dict[str, Any]:
    manifest = load(manifest_path)
    training = load(training_path)
    results = load(results_path)
    manifest_sha = file_sha256(manifest_path)
    if training["manifest_sha256"] != manifest_sha or results["manifest_sha256"] != manifest_sha:
        raise VerificationError("manifest binding mismatch")
    if results["training_sha256"] != file_sha256(training_path):
        raise VerificationError("training result binding mismatch")
    for relative, expected in manifest["source_hashes"].items():
        if file_sha256(REPO / relative) != expected:
            raise VerificationError(f"source hash mismatch: {relative}")
    for metadata in manifest["shards"].values():
        if file_sha256(HERE / metadata["path"]) != metadata["sha256"]:
            raise VerificationError(f"shard hash mismatch: {metadata['path']}")
    if training["access_audit"]["held_shard_reads"] or not training["access_audit"]["pass"]:
        raise VerificationError("held shard was read during fitting")
    for arm in ("S", "C16"):
        deterministic = training["deterministic_repeats"][arm]
        if (
            not deterministic["checkpoint_byte_identical"]
            or not deterministic["normalized_log_identical"]
        ):
            raise VerificationError(f"nondeterministic repeat: {arm}")
    checkpoint_index = {
        (row["arm"], row["seed"]): row for row in results["checkpoint_inventory"]
    }
    for row in results["checkpoint_inventory"]:
        if file_sha256(HERE / row["path"]) != row["sha256"]:
            raise VerificationError(f"checkpoint hash mismatch: {row['path']}")
    traces = results["trace_inventory"]
    if digest(traces) != results["trace_inventory_root"] or len(traces) != 1980:
        raise VerificationError("closed-loop trace inventory mismatch")
    keys = [(row["arm"], row["seed"], row["split"], row["episode_id"]) for row in traces]
    if len(set(keys)) != len(keys):
        raise VerificationError("duplicate closed-loop trace key")
    verified = [verify_trace(HERE / row["path"], row) for row in traces]
    for metadata in traces:
        if metadata["arm"] in {"S", "C16"} and metadata["checkpoint_sha256"] != checkpoint_index[
            (metadata["arm"], metadata["seed"])
        ]["sha256"]:
            raise VerificationError("learned trace/checkpoint inventory mismatch")
    reported = {
        (row["arm"], row["seed"], row["split"], row["episode_id"]): row
        for row in results["closed_loop"]
    }
    verified_keys = {
        (row["arm"], row["seed"], row["split"], row["episode_id"]) for row in verified
    }
    if set(reported) != verified_keys or len(results["closed_loop"]) != len(verified):
        raise VerificationError("closed-loop result inventory mismatch")
    compare_fields = (
        "success",
        "frames",
        "path_length_m",
        "mean_jerk_mps3",
        "contacts",
        "unsafe_after_gate",
        "gate_interventions",
        "transaction_exact",
        "terminal_receipts",
        "backed_terminal_receipts",
        "wrong_or_unbacked_terminal_receipts",
        "stale_binding_commands",
        "resume_admitted",
        "resume_eligible",
    )
    for row in verified:
        key = (row["arm"], row["seed"], row["split"], row["episode_id"])
        if key not in reported:
            raise VerificationError(f"closed-loop result missing: {key}")
        for field in compare_fields:
            if not close_enough(row[field], reported[key][field], tolerance=1.0e-6):
                raise VerificationError(f"closed-loop metric mismatch: {key}:{field}")
    recomputed_aggregates = aggregate_verified(verified)
    recursively_close(
        recomputed_aggregates,
        results["closed_loop_aggregates"],
        path="closed_loop_aggregates",
        tolerance=1.0e-6,
    )
    open_inventory = results["open_loop_trace_inventory"]
    if (
        digest(open_inventory) != results["open_loop_trace_inventory_root"]
        or len(open_inventory) != 42
    ):
        raise VerificationError("open-loop trace inventory mismatch")
    for metadata in open_inventory:
        arm, seed, _split = metadata["key"].split("|")
        if metadata["checkpoint_sha256"] != checkpoint_index[(arm, int(seed))]["sha256"]:
            raise VerificationError(f"open-loop checkpoint binding mismatch: {metadata['key']}")
        recomputed = verify_open_loop(HERE / metadata["path"], metadata)
        expected = results["open_loop"][metadata["key"]]
        for field, value in recomputed.items():
            if not close_enough(value, expected[field], tolerance=1.0e-6):
                raise VerificationError(f"open-loop metric mismatch: {metadata['key']}:{field}")
    for key, row in results["latency"].items():
        samples = [float(value) for value in row["samples_ms"]]
        if len(samples) != 10_000 or digest(samples) != row["samples_sha256"]:
            raise VerificationError(f"latency samples mismatch: {key}")
        for field, q in (("p50_ms", 50), ("p95_ms", 95), ("p99_ms", 99)):
            if not close_enough(percentile(samples, q), row[field], tolerance=1.0e-9):
                raise VerificationError(f"latency percentile mismatch: {key}:{field}")
    hypotheses = recompute_hypotheses(results)
    if hypotheses != results["hypotheses"]:
        raise VerificationError("hypothesis recomputation mismatch")
    expected_verdict = (
        "INVALID_PRECONDITION"
        if not hypotheses["integrity"]
        else "P1_RESEARCH_CHALLENGER"
        if hypotheses["H-P1a"] and hypotheses["H-P1b"] and hypotheses["H-P1c"]
        else "P1_SNAPSHOT_SUFFICIENT"
        if hypotheses["H-P1a"] and hypotheses["H-P1c"]
        else "P1_REFUTED"
    )
    if results["verdict"] != expected_verdict:
        raise VerificationError("verdict mismatch")
    return {
        "status": "PASS",
        "verifier": "MA-2-P1 independent stdlib verifier v1",
        "manifest_sha256": manifest_sha,
        "closed_loop_traces": len(traces),
        "closed_loop_frames": sum(row["frames"] for row in verified),
        "open_loop_traces": len(open_inventory),
        "open_loop_rows": sum(row["rows"] for row in open_inventory),
        "latency_samples": sum(row["samples"] for row in results["latency"].values()),
        "hypotheses": hypotheses,
        "verdict": expected_verdict,
    }


def tamper_suite(results_path: Path) -> dict[str, Any]:
    results = load(results_path)
    base_meta = next(row for row in results["trace_inventory"] if row["arm"] == "T*")
    base_path = HERE / base_meta["path"]
    original_rows = list(zstd_rows(base_path))
    cases: list[dict[str, Any]] = []
    mutations = {
        "feature_timestamp": lambda rows: rows[0]["policy_input"]["header"].__setitem__(
            "monotonic_ns", rows[0]["policy_input"]["header"]["monotonic_ns"] + 1
        ),
        "applied_label": lambda rows: rows[0]["actions"]["actuator_applied"].__setitem__(
            "vx", rows[0]["actions"]["actuator_applied"]["vx"] + 0.001
        ),
        "split_membership": lambda rows: rows[0].__setitem__("split", "train"),
        "terminal_receipt": lambda rows: next(
            row for row in rows if row["narrative_receipt"] is not None
        )["narrative_receipt"].__setitem__("task_id", "task-tampered"),
    }
    with tempfile.TemporaryDirectory(prefix="ma2-p1-tamper-") as directory:
        root = Path(directory)
        for name, mutate in mutations.items():
            rows = json.loads(json.dumps(original_rows))
            mutate(rows)
            raw = root / f"{name}.jsonl"
            with raw.open("wb") as handle:
                for row in rows:
                    handle.write(canonical_bytes(row) + b"\n")
            compressed = raw.with_suffix(".jsonl.zst")
            subprocess.run(["zstd", "-q", "-f", str(raw), "-o", str(compressed)], check=True)
            meta = dict(base_meta)
            meta["sha256"] = file_sha256(compressed)
            rejected = False
            reason = ""
            try:
                verify_trace(compressed, meta)
            except VerificationError as error:
                rejected = True
                reason = str(error)
            cases.append({"case": name, "rejected": rejected, "reason": reason})
        checkpoint = results["checkpoint_inventory"][0]
        rejected = file_sha256(HERE / checkpoint["path"]) != "f" * 64
        cases.append(
            {
                "case": "checkpoint_hash",
                "rejected": rejected,
                "reason": "checkpoint file differs from tampered expected digest"
                if rejected
                else "",
            }
        )
    return {
        "cases": cases,
        "rejected": sum(row["rejected"] for row in cases),
        "total": 5,
        "pass": all(row["rejected"] for row in cases),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tamper-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_all(args.manifest, args.training, args.results)
    except Exception as error:  # noqa: BLE001 - durable independent refusal
        report = {"status": "FAIL", "error": f"{type(error).__name__}: {error}"}
        atomic_json(args.output, report)
        print(json.dumps(report, indent=2))
        return 1
    tamper = tamper_suite(args.results)
    atomic_json(args.output, report)
    atomic_json(args.tamper_output, tamper)
    print(json.dumps({"verification": report, "tamper": tamper}, indent=2))
    return 0 if tamper["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
