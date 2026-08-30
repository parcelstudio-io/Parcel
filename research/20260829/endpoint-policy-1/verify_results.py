"""Fail-closed verifier for the retained endpoint-policy sensitivity runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUN1 = HERE / "results-run1.json"
RUN2 = HERE / "results-run2.json"
PARITY1 = HERE / "production-parity-run1.json"
PARITY2 = HERE / "production-parity-run2.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} is not a JSON object")
    return value


def main() -> int:
    run1 = load(RUN1)
    load(RUN2)
    parity = load(PARITY1)
    load(PARITY2)
    checks = {
        "retained_runs_byte_identical": RUN1.read_bytes() == RUN2.read_bytes(),
        "schema_exact": run1.get("schema") == "parcel-endpoint-policy-sensitivity-2",
        "source_pin_current": run1["inputs"]["run_source_sha256"]
        == sha256(HERE / "run.py"),
        "endpointing_pin_current": run1["inputs"]["endpointing_source_sha256"]
        == sha256(ROOT / "src/parcel_robot/audio/endpointing.py"),
        "voice_loop_pin_current": run1["inputs"]["voice_loop_source_sha256"]
        == sha256(ROOT / "src/parcel_robot/audio/voice_loop.py"),
        "corrected_v2_pin_current": run1["inputs"]["corrected_v2_results_sha256"]
        == sha256(ROOT / "research/20260829/acoustic-eval-v2/results.json"),
        "baseline_parity_red": run1["baseline_parity"]["parity_pass"] is False,
        "all_declared_grid_points_red": run1["declared_grid_pass_count"] == 0,
        "no_nomination": run1["nomination"] is None,
        "onnxruntime_provenance_present": run1["environment"]["onnxruntime_module"]
        != "unavailable",
        "resumed_speech_outcomes_partitioned": all(
            diagnostic["provisional_pre_commit_cancellation_count"]
            + diagnostic["provisional_commit_before_resume_contradiction_count"]
            == 12
            for diagnostic in run1["two_stage_diagnostics"].values()
        ),
        "production_parity_runs_byte_identical": PARITY1.read_bytes()
        == PARITY2.read_bytes(),
        "production_loop_sample_clock_parity": parity["pass"] is True
        and parity["cell_count"] == 52
        and parity["sample_clock_match_count"] == 52
        and parity["mismatch_count"] == 0,
        "production_parity_sources_current": parity["source_hashes"]["parity_script"]
        == sha256(HERE / "verify_production_loop_parity.py")
        and parity["source_hashes"]["sensitivity_runner"] == sha256(HERE / "run.py")
        and parity["source_hashes"]["voice_loop"]
        == sha256(ROOT / "src/parcel_robot/audio/voice_loop.py")
        and parity["source_hashes"]["endpointing"]
        == sha256(ROOT / "src/parcel_robot/audio/endpointing.py"),
    }
    result = {
        "schema": "parcel-endpoint-policy-verification-1",
        "pass": all(checks.values()),
        "checks": checks,
        "run_sha256": sha256(RUN1),
        "production_parity_sha256": sha256(PARITY1),
    }
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
