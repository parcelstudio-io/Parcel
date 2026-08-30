#!/usr/bin/env python
"""Five-part DMC-4 tamper capability check against retained evidence."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
MANIFEST_PATH = HERE / "manifest.json"
SOURCE_MANIFEST_PATH = HERE / "source_manifest.json"


def _load_verifier():
    path = HERE / "verify_results.py"
    spec = importlib.util.spec_from_file_location("dmc4_independent_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reseal(result: dict[str, object], verifier: object) -> None:
    normalized = {
        "schema_version": result.get("schema_version"),
        "experiment_id": result.get("experiment_id"),
        "seed": result.get("seed"),
        "population": result.get("population"),
        "not_constructible": result.get("not_constructible"),
        "transition_rows": result.get("transition_rows"),
        "parent_child_rows": result.get("parent_child_rows"),
        "corruption_rows": result.get("corruption_rows"),
        "concurrency_rows": result.get("concurrency_rows"),
        "non_actuation": result.get("non_actuation"),
    }
    result["normalized_trace_sha256"] = verifier.digest(normalized)
    rows = [
        *result["transition_rows"],
        *result["parent_child_rows"],
        *result["corruption_rows"],
        *result["concurrency_rows"],
    ]
    result["trace_chain_root_sha256"] = verifier._chain(rows)
    result.pop("result_sha256", None)
    result["result_sha256"] = verifier.digest(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verifier = _load_verifier()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    original = json.loads(args.input.read_text(encoding="utf-8"))
    cases: list[dict[str, object]] = []

    scalar = copy.deepcopy(original)
    scalar["population"]["producer_threads"] -= 1
    _reseal(scalar, verifier)
    checked = verifier.verify_one(scalar, manifest)
    cases.append(
        {"tamper": "result_scalar", "detected": not checked["passed"], "errors": checked["errors"]}
    )

    journal = copy.deepcopy(original)
    journal["transition_rows"][0]["journal_read"]["transitions"][0][
        "resulting_state"
    ] = "succeeded"
    _reseal(journal, verifier)
    checked = verifier.verify_one(journal, manifest)
    cases.append(
        {"tamper": "raw_journal_row", "detected": not checked["passed"], "errors": checked["errors"]}
    )

    event = copy.deepcopy(original)
    event["transition_rows"][0]["events"][0]["event"]["status"] = "succeeded"
    _reseal(event, verifier)
    checked = verifier.verify_one(event, manifest)
    cases.append(
        {"tamper": "authenticated_event", "detected": not checked["passed"], "errors": checked["errors"]}
    )

    manifest_hash = copy.deepcopy(original)
    manifest_hash["manifest_sha256"] = "0" * 64
    _reseal(manifest_hash, verifier)
    checked = verifier.verify_one(manifest_hash, manifest)
    cases.append(
        {"tamper": "manifest_hash", "detected": not checked["passed"], "errors": checked["errors"]}
    )

    source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="parcel-dmc4-tamper-") as directory:
        root = Path(directory)
        for relative in source_manifest["files"]:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPO_ROOT / relative).read_bytes())
        first = sorted(source_manifest["files"])[0]
        target = root / first
        target.write_bytes(target.read_bytes() + b"\n# tampered copy\n")
        source_errors = verifier.verify_source_manifest(source_manifest, root=root)
    cases.append(
        {
            "tamper": "source_file",
            "detected": bool(source_errors),
            "errors": source_errors,
        }
    )

    output = {
        "schema_version": 1,
        "input": str(args.input),
        "cases": cases,
        "all_five_detected": len(cases) == 5
        and all(item["detected"] is True for item in cases),
    }
    output["tamper_check_sha256"] = verifier.digest(output)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
