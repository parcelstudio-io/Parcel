"""Strict independent verifier for SOS-1 lifecycle-oracle maintenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
GATE_NAMES = ("SOS-H1", "SOS-H2", "SOS-H3", "SOS-H4", "SOS-H5")
EXPECTED_MANIFEST_FILES = {
    "research/20260829/stop-only-safety-1/DESIGN.md",
    "research/20260829/stop-only-safety-1/POST_EVIDENCE_MAINTENANCE_2.md",
    "research/20260829/stop-only-safety-1/POST_EVIDENCE_MAINTENANCE_3.md",
    "research/20260829/stop-only-safety-1/freeze.py",
    "research/20260829/stop-only-safety-1/freeze_maintenance.py",
    "research/20260829/stop-only-safety-1/run.py",
    "research/20260829/stop-only-safety-1/verify.py",
    "research/20260829/stop-only-safety-1/verify_maintenance_strict.py",
    "src/parcel_robot/bridge/stop_only_gateway.py",
    "src/parcel_robot/safety_supervisor.py",
    "gateway/credentials.py",
    "gateway/core.py",
    "gateway/seam/cli.py",
    "deploy/orin/services/parcel-gateway.service",
    "deploy/orin/services/parcel-runtime.service",
    "deploy/orin/services/parcel-safety.service",
    "pyproject.toml",
    "tests/test_stop_only_safety.py",
    "tests/test_gateway_socket_credentials.py",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: expected a JSON object")
    return value


def _recompute_gates(body: dict[str, Any]) -> dict[str, bool]:
    trials = body["trials"]
    api = body["api"]
    lifecycle = body["lifecycle"]
    composition = body["composition"]
    if not all(isinstance(item, dict) for item in (trials, api, lifecycle, composition)):
        raise TypeError("trials, api, lifecycle, and composition must be objects")

    h1 = all(
        trials[key] == 256
        for key in (
            "stop_uid_acquire_refused",
            "stop_uid_command_refused",
            "runtime_acquire_admitted",
            "runtime_command_admitted",
        )
    )
    h2 = all(
        trials[key] == 256
        for key in (
            "safety_stop_reached",
            "latched",
            "lease_invalidated",
            "exact_zero",
            "stationary_confirmed",
        )
    )
    h3 = api["pass"] is True and api["forbidden_methods"] == [] and api["forbidden_imports"] == []
    signals = [lifecycle[name] for name in ("sigusr1", "sigterm", "sigint")]
    h4 = all(
        item["ready"] is True
        and item["fresh_start_no_stop"] is True
        and item["latched"] is True
        and item["exact_zero"] is True
        and item["stationary"] is True
        and item["lease_invalidated"] is True
        and item["return_code_zero"] is True
        and item["kept_running_after_signal"] == item["expected_keep_running"]
        for item in signals
    ) and all(
        (
            lifecycle["sigusr1"]["post_signal_watchdog"] is True,
            lifecycle["sigusr1"]["liveness_dwell_completed"] is True,
            lifecycle["sigterm"]["exited_within_timeout"] is True,
            lifecycle["sigint"]["exited_within_timeout"] is True,
            lifecycle["gateway_failure"]["ready"] is True,
            lifecycle["gateway_failure"]["watchdog_before_failure"] is True,
            lifecycle["gateway_failure"]["watchdog_after_failure"] is False,
            lifecycle["gateway_failure"]["nonzero_when_stop_unconfirmed"] is True,
        )
    )
    h5 = composition["pass"] is True and all(
        check is True for check in composition["checks"].values()
    )
    return dict(zip(GATE_NAMES, (h1, h2, h3, h4, h5), strict=True))


def _verify_one(value: dict[str, Any], manifest_sha256: str, expected_label: str) -> dict[str, Any]:
    body = {key: item for key, item in value.items() if key != "run_label"}
    claimed_digest = body.pop("normalized_digest", None)
    digest_ok = claimed_digest == _sha256(_canonical(body))
    recomputed = _recompute_gates(body)
    functional_pass = all(recomputed.values())
    trials = body.get("trials")
    result_structure_ok = all(
        (
            body.get("schema_version") == 1,
            body.get("study") == "SOS-1",
            isinstance(trials, dict),
            isinstance(trials, dict) and trials.get("cases") == 256,
            value.get("run_label") == expected_label,
        )
    )
    return {
        "run_label": value.get("run_label"),
        "manifest_ok": body.get("manifest_sha256") == manifest_sha256,
        "digest_ok": digest_ok,
        "gates_match_recomputation": body.get("gates") == recomputed,
        "all_functional_claim_matches": (body.get("all_functional_gates_pass") is functional_pass),
        "functional_pass": functional_pass,
        "recomputed_gates": recomputed,
        "physical_no_go": body.get("physical_readiness") is False,
        "result_structure_ok": result_structure_ok,
        "normalized_digest": claimed_digest,
    }


def _cohort(values: list[dict[str, Any]]) -> dict[str, Any]:
    digests = [item["normalized_digest"] for item in values]
    integrity_fields = (
        "manifest_ok",
        "digest_ok",
        "gates_match_recomputation",
        "all_functional_claim_matches",
        "physical_no_go",
        "result_structure_ok",
    )
    return {
        "runs": values,
        "normalized_runs_equal": len(set(digests)) == 1,
        "integrity_pass": all(item[field] is True for item in values for field in integrity_fields),
        "functional_pass": all(item["functional_pass"] is True for item in values),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--parallel-run-a", required=True)
    parser.add_argument("--parallel-run-b", required=True)
    parser.add_argument("--sequential-run-c", required=True)
    parser.add_argument("--sequential-run-d", required=True)
    parser.add_argument("--label-prefix", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = _load(manifest_path)
    manifest_sha256 = _sha256(manifest_path.read_bytes())
    manifest_files = manifest.get("files")
    manifest_structure_ok = all(
        (
            manifest.get("schema_version") == 3,
            manifest.get("study") == "SOS-1-lifecycle-oracle-maintenance",
            isinstance(manifest_files, dict),
            isinstance(manifest_files, dict) and set(manifest_files) == EXPECTED_MANIFEST_FILES,
        )
    )
    source_hashes_ok = manifest_structure_ok and all(
        _sha256((REPO / name).read_bytes()) == digest for name, digest in manifest_files.items()
    )

    def verified(path: str, suffix: str) -> dict[str, Any]:
        return _verify_one(_load(Path(path)), manifest_sha256, f"{args.label_prefix}-{suffix}")

    parallel = _cohort(
        [
            verified(args.parallel_run_a, "parallel-a"),
            verified(args.parallel_run_b, "parallel-b"),
        ]
    )
    sequential = _cohort(
        [
            verified(args.sequential_run_c, "sequential-c"),
            verified(args.sequential_run_d, "sequential-d"),
        ]
    )
    all_runs = parallel["runs"] + sequential["runs"]
    all_normalized_runs_equal = len({item["normalized_digest"] for item in all_runs}) == 1
    labels_unique = len({item["run_label"] for item in all_runs}) == 4

    tampered_digest = _load(Path(args.parallel_run_a))
    tampered_digest["trials"]["latched"] = 255
    tampered_digest_rejected = not _verify_one(
        tampered_digest, manifest_sha256, f"{args.label_prefix}-parallel-a"
    )["digest_ok"]

    tampered_claim = _load(Path(args.parallel_run_a))
    tampered_claim["trials"]["latched"] = 255
    tampered_body = {
        key: item
        for key, item in tampered_claim.items()
        if key not in {"run_label", "normalized_digest"}
    }
    tampered_claim["normalized_digest"] = _sha256(_canonical(tampered_body))
    tampered_claim_check = _verify_one(
        tampered_claim, manifest_sha256, f"{args.label_prefix}-parallel-a"
    )
    recomputed_claim_rejected = all(
        (
            tampered_claim_check["digest_ok"] is True,
            tampered_claim_check["gates_match_recomputation"] is False,
            tampered_claim_check["recomputed_gates"]["SOS-H2"] is False,
            tampered_claim_check["functional_pass"] is False,
        )
    )

    output = {
        "schema_version": 3,
        "study": "SOS-1-lifecycle-oracle-maintenance-strict",
        "manifest_sha256": manifest_sha256,
        "manifest_structure_ok": manifest_structure_ok,
        "source_hashes_ok": source_hashes_ok,
        "parallel": parallel,
        "sequential": sequential,
        "all_normalized_runs_equal": all_normalized_runs_equal,
        "labels_unique": labels_unique,
        "tampered_digest_rejected": tampered_digest_rejected,
        "recomputed_malicious_claim_rejected": recomputed_claim_rejected,
    }
    output["pass"] = all(
        (
            manifest_structure_ok,
            source_hashes_ok,
            parallel["integrity_pass"],
            parallel["functional_pass"],
            sequential["integrity_pass"],
            sequential["functional_pass"],
            all_normalized_runs_equal,
            labels_unique,
            tampered_digest_rejected,
            recomputed_claim_rejected,
        )
    )
    Path(args.output).write_text(
        json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0 if output["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
