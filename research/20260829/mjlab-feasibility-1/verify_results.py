#!/usr/bin/env python3
"""Independent verifier for the bounded MJLAB-1 evidence bundle."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_COMMIT = "1425b15f73bd4095f0df53709d7c389c3eb9e790"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} does not contain a JSON object")
    return value


def verify_h2(run: dict[str, Any], probe_hash: str) -> dict[str, bool]:
    cfg = run["configuration"]
    measurements = run["measurements"]
    gates = run["gates"]
    return {
        "schema": run.get("schema_version") == 1 and run.get("hypothesis") == "MJF-H2",
        "commit": run["source"]["commit"] == EXPECTED_COMMIT,
        "probe_hash": run["source"]["probe_sha256"] == probe_hash,
        "compatible_versions": run["environment"]["packages"]["mujoco"] == "3.5.0"
        and run["environment"]["packages"]["mujoco-warp"] == "3.5.0"
        and run["environment"]["packages"]["warp-lang"] == "1.12.0"
        and run["environment"]["packages"]["torch"] == "2.13.0",
        "num_envs": cfg["num_envs"] == 64,
        "warmup_steps": cfg["warmup_steps"] == 64,
        "timed_steps": cfg["timed_steps"] == 256,
        "timed_sample_count": measurements["timed_environment_steps"] == 64 * 256,
        "all_checked_steps": measurements["checked_policy_steps_including_warmup"] == 320,
        "finite": measurements["checked_tensor_values_finite"] is True,
        "joint_count": cfg["joint_count"] == 12 and cfg["action_dim"] == 12,
        "throughput": measurements["environment_steps_per_second"] >= 3_200.0,
        "recorded_gate": all(
            gates[name]
            for name in ("num_envs_pass", "timed_steps_pass", "finite_pass", "throughput_pass")
        ),
        "recorded_result": run["h2_supported_this_run"] is True,
    }


def parse_time_rss(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    rss_line = next(
        line for line in text.splitlines() if "Maximum resident set size (kbytes)" in line
    )
    exit_line = next(line for line in text.splitlines() if "Exit status" in line)
    rss_kib = int(rss_line.rsplit(":", 1)[1].strip())
    status = int(exit_line.rsplit(":", 1)[1].strip())
    return {
        "path": str(path),
        "sha256": sha256(path),
        "maximum_resident_set_kib": rss_kib,
        "maximum_resident_set_gib": rss_kib / (1024 * 1024),
        "exit_status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    out = (args.out or (root / "verification.json")).resolve()

    paths = {
        "design": root / "DESIGN.md",
        "clean": root / "raw/clean-install.json",
        "registration": root / "registration.json",
        "run3": root / "physics-run-3.json",
        "run4": root / "physics-run-4.json",
        "run5": root / "physics-run-5-posthoc-rss.json",
        "training": root / "training-result.json",
        "applicability": root / "applicability.json",
        "probe_physics": root / "probe_physics.py",
        "probe_registration": root / "probe_registration.py",
        "collector": root / "collect_training_artifacts.py",
        "applicability_probe": root / "assess_applicability.py",
        "verifier": root / "verify_results.py",
        "constraints": root / "constraints.txt",
        "readme": root / "README.md",
        "results": root / "RESULTS.md",
        "verdict": root / "VERDICT.md",
        "pip_freeze": root / "raw/pip-freeze.txt",
        "mujoco_remediation": root / "raw/remediation-final.json",
        "scipy_remediation": root / "raw/scipy-remediation-final.json",
        "warp_remediation": root / "raw/warp-remediation-final.json",
        "wandb_remediation": root / "raw/wandb-remediation.json",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing evidence: {missing}")

    clean = load(paths["clean"])
    registration = load(paths["registration"])
    run3 = load(paths["run3"])
    run4 = load(paths["run4"])
    run5 = load(paths["run5"])
    training = load(paths["training"])
    applicability = load(paths["applicability"])
    remediation = {
        "mujoco": load(paths["mujoco_remediation"]),
        "scipy": load(paths["scipy_remediation"]),
        "warp": load(paths["warp_remediation"]),
        "wandb": load(paths["wandb_remediation"]),
    }

    clean_stderr = root / "raw" / clean["list_envs"]["stderr_file"]
    h1_clean_checks = {
        "expected_commit": clean["source"]["commit"] == EXPECTED_COMMIT,
        "upstream_source_clean_at_capture": clean["source"]["status_porcelain"] == "",
        "resolver_selected_mujoco_3_12": (
            clean["causal_diagnosis"]["resolver_selected_mujoco"] == "3.12.0"
        ),
        "paired_warp_3_5": clean["causal_diagnosis"]["paired_mujoco_warp"] == "3.5.0",
        "import_failed": clean["list_envs"]["returncode"] != 0,
        "expected_signature": (
            "mjENBL_MULTICCD" in clean_stderr.read_text(encoding="utf-8")
        ),
        "stderr_hash": sha256(clean_stderr) == clean["list_envs"]["stderr_sha256"],
        "recorded_clean_h1_false": clean["clean_install_h1_supported"] is False,
    }
    clean_h1_supported = False
    clean_h1_failure_verified = all(h1_clean_checks.values())

    registration_checks = {
        "commit": registration["source"]["commit"] == EXPECTED_COMMIT,
        "probe_hash": registration["source"]["probe_sha256"]
        == sha256(paths["probe_registration"]),
        "tasks_exact": registration["go2_tasks"]
        == ["Unitree-Go2-Flat", "Unitree-Go2-Rough"],
        "mujoco_pair": registration["packages"]["mujoco"] == "3.5.0"
        and registration["packages"]["mujoco-warp"] == "3.5.0",
        "scipy_present": registration["packages"]["scipy"] == "1.17.1",
        "recorded": registration["remediated_registration_supported"] is True,
    }
    remediated_registration_supported = all(registration_checks.values())
    remediation_checks = {
        "mujoco": remediation["mujoco"]["remediated_registration_supported"] is True,
        "scipy": remediation["scipy"]["remediated_registration_supported"] is True,
        "warp": remediation["warp"]["remediated_import_supported"] is True,
        "wandb": remediation["wandb"]["remediated_logger_api_supported"] is True,
        "constraints_hash_present": len(sha256(paths["constraints"])) == 64,
        "full_freeze_hash_present": len(sha256(paths["pip_freeze"])) == 64,
    }
    remediation_sequence_supported = all(remediation_checks.values())

    probe_hash = sha256(paths["probe_physics"])
    h2_checks = {
        "run3": verify_h2(run3, probe_hash),
        "run4": verify_h2(run4, probe_hash),
    }
    h2_supported = all(all(checks.values()) for checks in h2_checks.values())
    h2_aggregate = {
        "evidentiary_fresh_process_runs": 2,
        "timed_environment_steps": sum(
            run["measurements"]["timed_environment_steps"] for run in (run3, run4)
        ),
        "checked_environment_steps_including_warmup": sum(
            run["configuration"]["num_envs"]
            * run["measurements"]["checked_policy_steps_including_warmup"]
            for run in (run3, run4)
        ),
        "throughput_min": min(
            run["measurements"]["environment_steps_per_second"] for run in (run3, run4)
        ),
        "throughput_max": max(
            run["measurements"]["environment_steps_per_second"] for run in (run3, run4)
        ),
        "process_wall_seconds_total": sum(
            run["measurements"]["process_wall_seconds"] for run in (run3, run4)
        ),
    }

    # This run was explicitly added after H2 to capture RSS; it does not replace run 3/4.
    supplemental_rss = parse_time_rss(root / "raw/physics-run-5-posthoc-rss-time.txt")
    run5_checks = verify_h2(run5, probe_hash)
    supplemental_rss["labeled_post_hoc"] = True
    supplemental_rss["run_json_sha256"] = sha256(paths["run5"])
    supplemental_rss["run_pass"] = all(run5_checks.values()) and supplemental_rss["exit_status"] == 0
    supplemental_rss["environment_steps_per_second"] = run5["measurements"][
        "environment_steps_per_second"
    ]

    retained_checks = {}
    for name, entry in training["retained_artifacts"].items():
        retained_path = root / "artifacts" / name
        retained_checks[name] = (
            retained_path.is_file()
            and retained_path.stat().st_size == entry["retained"]["bytes"]
            and sha256(retained_path) == entry["retained"]["sha256"]
            and entry["hash_match"] is True
        )
    h3_checks = {
        "collector_hash": training["source"]["collector_sha256"] == sha256(paths["collector"]),
        "source_commit": training["source"]["commit"] == EXPECTED_COMMIT,
        "configuration": training["configuration"]
        == {
            "max_iterations": 3,
            "num_envs": 64,
            "num_steps_per_env": 24,
            "save_interval": 1,
            "seed": 42,
        },
        "iterations": training["observed_iteration_indices"] == [0, 1, 2],
        "sample_count": training["expected_environment_steps"] == 4_608
        and training["observed_total_steps_by_iteration"][-1] == 4_608,
        "checkpoint": training["checkpoint"]["checkpoint_iteration_index"] == 2
        and training["checkpoint"]["original"]["bytes"] > 0,
        "rss_recorded": training["resource_usage"]["maximum_resident_set_kib"] > 0,
        "command_exit": training["resource_usage"]["exit_status"] == 0,
        "retained": all(retained_checks.values()),
        "all_recorded_gates": all(training["gates"].values()),
        "recorded": training["h3_supported"] is True,
    }
    h3_supported = all(h3_checks.values())

    applicability_checks = {
        "probe_hash": applicability["source"]["probe_sha256"]
        == sha256(paths["applicability_probe"]),
        "source_commit": applicability["source"]["commit"] == EXPECTED_COMMIT,
        "joint_count": applicability["observed"]["go2_named_leg_joint_count"] == 12,
        "lower_hooks": applicability["lower_layer_hooks_pass"] is True,
        "strict_h4_false": applicability["strict_h4_gate_supported"] is False,
        "missing_scope_recorded": len(applicability["not_present_in_tested_task"]) >= 8,
    }
    pinned_lower_layer_hooks_supported = all(applicability_checks.values())

    strict_all_gates_supported = (
        clean_h1_supported
        and h2_supported
        and h3_supported
        and applicability["strict_h4_gate_supported"]
    )
    practical_pinned_environment_feasible = (
        clean_h1_failure_verified
        and remediated_registration_supported
        and remediation_sequence_supported
        and h2_supported
        and h3_supported
        and pinned_lower_layer_hooks_supported
    )

    tampered = copy.deepcopy(run3)
    tampered["source"]["probe_sha256"] = "0" * 64
    tamper_self_test = not all(verify_h2(tampered, probe_hash).values())
    record = {
        "schema_version": 1,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "MJLAB-1",
        "bundle_root": str(root),
        "bundle_files_sha256": {
            str(path.relative_to(root)): sha256(path)
            for path in paths.values()
            if path.is_file()
        },
        "h1_clean_install": {
            "checks": h1_clean_checks,
            "failure_verified": clean_h1_failure_verified,
            "supported": clean_h1_supported,
        },
        "h1_remediated_registration": {
            "checks": registration_checks,
            "remediation_checks": remediation_checks,
            "remediation_sequence_supported": remediation_sequence_supported,
            "supported": remediated_registration_supported,
        },
        "h2": {
            "checks": h2_checks,
            "aggregate": h2_aggregate,
            "supported_in_pinned_environment": h2_supported,
        },
        "h2_posthoc_rss_supplement": supplemental_rss,
        "h3": {
            "checks": h3_checks,
            "retained_artifact_checks": retained_checks,
            "supported_in_pinned_environment": h3_supported,
            "training_resource_usage": training["resource_usage"],
        },
        "h4": {
            "checks": applicability_checks,
            "pinned_lower_layer_hooks_supported": pinned_lower_layer_hooks_supported,
            "strict_supported": False,
        },
        "tamper_self_test_pass": tamper_self_test,
        "strict_all_preregistered_gates_supported": strict_all_gates_supported,
        "practical_pinned_environment_feasible": practical_pinned_environment_feasible,
        "physical_readiness_supported": False,
        "final_boundary": (
            "A reproducibly pinned official Go2 lower-layer simulator pipeline is feasible on "
            "this workstation. Clean install, locomotion quality, Parcel integration, Orin "
            "performance, and physical safety are not established."
        ),
    }
    verifier_pass = (
        clean_h1_failure_verified
        and remediated_registration_supported
        and remediation_sequence_supported
        and h2_supported
        and h3_supported
        and pinned_lower_layer_hooks_supported
        and tamper_self_test
        and strict_all_gates_supported is False
        and practical_pinned_environment_feasible
        and record["physical_readiness_supported"] is False
    )
    record["verifier_pass"] = verifier_pass
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "verifier_pass": verifier_pass,
        "strict_all_preregistered_gates_supported": strict_all_gates_supported,
        "practical_pinned_environment_feasible": practical_pinned_environment_feasible,
    }, sort_keys=True))
    return 0 if verifier_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
