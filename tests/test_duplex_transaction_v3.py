"""Capability and tamper tests for the DMC-3 runner/verifier separation."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "research" / "20260829" / "duplex-transaction-3"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dmc3_runner_is_deterministic_and_does_not_self_adjudicate() -> None:
    runner = _load("parcel_dmc3_runner", PACK / "run.py")
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))

    first = runner.run_suite(manifest, trial_limits={"h1": 1, "h2": 16, "h3": 1})
    second = runner.run_suite(manifest, trial_limits={"h1": 1, "h2": 16, "h3": 1})

    assert len(first["traces"]) == 18
    assert first["normalized_trace_sha256"] == second["normalized_trace_sha256"]
    assert first["trace_chain_root_sha256"] == second["trace_chain_root_sha256"]
    assert first["architecture_gate"]["status"] == "PARTIAL_RED"
    assert all("passed" not in row and "oracle_pass" not in row for row in first["traces"])


def test_dmc3_independent_oracle_catches_fact_tamper() -> None:
    runner = _load("parcel_dmc3_runner_tamper", PACK / "run.py")
    verifier = _load("parcel_dmc3_verifier_tamper", PACK / "verify_results.py")
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))

    h1 = runner.run_h1_trial(manifest, 0)
    h2 = [
        runner.run_h2_trial(manifest, index, corruption)
        for index, corruption in enumerate(manifest["h2_corruptions"])
    ]
    h3 = runner.run_h3_trial(manifest, 0)
    assert verifier._verify_h1(h1)
    assert all(verifier._verify_h2(row) for row in h2)
    assert verifier._verify_h3(h3)

    tampered = copy.deepcopy(h1)
    tampered["events"][-1]["event"]["verified_facts"] = []
    assert verifier._verify_h1(tampered) is False

    missing = copy.deepcopy(
        next(row for row in h2 if row["corruption"] == "missing_success_fact")
    )
    missing["consumer"]["state_after"]["last_event_sequence"] -= 1
    assert verifier._verify_h2(missing) is False

    corrupt = copy.deepcopy(
        next(row for row in h2 if row["corruption"] == "wrong_source_epoch")
    )
    corrupt["consumer"]["state_after"]["speech_generation"] += 1
    assert verifier._verify_h2(corrupt) is False


def test_dmc3_verifier_has_no_parcel_or_bridge_import() -> None:
    tree = ast.parse((PACK / "verify_results.py").read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith("parcel_robot") for name in imports)
