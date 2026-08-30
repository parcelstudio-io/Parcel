"""Independent DMC-4 maintenance equivalence verifier."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_original_verifier():
    path = HERE / "verify_results.py"
    spec = importlib.util.spec_from_file_location("dmc4_frozen_verifier", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen DMC-4 verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SOURCE_MANIFEST_PATH = HERE / "maintenance_source_manifest_v2.json"
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-c", type=Path, required=True)
    parser.add_argument("--run-d", type=Path, required=True)
    parser.add_argument("--original-a", type=Path, default=HERE / "run_a.json")
    parser.add_argument("--original-b", type=Path, default=HERE / "run_b.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    verifier = _load_original_verifier()
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    current = [
        json.loads(args.run_c.read_text(encoding="utf-8")),
        json.loads(args.run_d.read_text(encoding="utf-8")),
    ]
    original = [
        json.loads(args.original_a.read_text(encoding="utf-8")),
        json.loads(args.original_b.read_text(encoding="utf-8")),
    ]
    checks = [verifier.verify_one(value, manifest) for value in current]
    current_roots = {
        (value["normalized_trace_sha256"], value["trace_chain_root_sha256"])
        for value in current
    }
    original_roots = {
        (value["normalized_trace_sha256"], value["trace_chain_root_sha256"])
        for value in original
    }
    source_manifest = json.loads(
        (HERE / "maintenance_source_manifest_v2.json").read_text(encoding="utf-8")
    )
    source_errors = verifier.verify_source_manifest(source_manifest)
    equivalent = (
        len(current_roots) == 1
        and len(original_roots) == 1
        and current_roots == original_roots
    )
    passed = not source_errors and equivalent and all(item["passed"] for item in checks)
    output = {
        "schema_version": 1,
        "study": "DMC-4-post-evidence-maintenance-1",
        "checks": checks,
        "maintenance_source_errors": source_errors,
        "maintenance_runs_identical": len(current_roots) == 1,
        "original_runs_identical": len(original_roots) == 1,
        "maintenance_roots_equal_original": equivalent,
        "normalized_trace_sha256": next(iter(current_roots))[0] if current_roots else None,
        "trace_chain_root_sha256": next(iter(current_roots))[1] if current_roots else None,
        "verdict": (
            "DMC4_MAINTENANCE_EQUIVALENCE_PASS"
            if passed
            else "DMC4_MAINTENANCE_EQUIVALENCE_REFUTED"
        ),
    }
    output["verification_sha256"] = verifier.digest(output)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
