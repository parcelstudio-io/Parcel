"""Integrity and deterministic-replay verifier for independent completion."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import experiment

HERE = Path(__file__).resolve().parent
NONDETERMINISTIC_KEYS = frozenset(
    {"report_schema", "environment", "deterministic_payload_sha256"}
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deterministic_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in NONDETERMINISTIC_KEYS
    }


def _digest(report: dict[str, Any]) -> str:
    encoded = json.dumps(
        _deterministic_payload(report), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify(
    *,
    run1_path: Path,
    run2_path: Path,
    canonical_path: Path,
    write_canonical: bool,
) -> dict[str, Any]:
    run1 = _load(run1_path)
    run2 = _load(run2_path)
    regenerated_matrix = [case.matrix_row() for case in experiment.build_matrix()]
    current_sources = {
        relative: _file_sha256(experiment.ROOT / relative)
        for relative in experiment.SOURCE_PATHS
    }

    prechecks = {
        "run1_payload_digest_recomputed": (
            _digest(run1) == run1["deterministic_payload_sha256"]
        ),
        "run2_payload_digest_recomputed": (
            _digest(run2) == run2["deterministic_payload_sha256"]
        ),
        "deterministic_replay_digest_matches": (
            run1["deterministic_payload_sha256"]
            == run2["deterministic_payload_sha256"]
        ),
        "matrix_generator_replays_run1": regenerated_matrix == run1["matrix"],
        "matrix_generator_replays_run2": regenerated_matrix == run2["matrix"],
        "matrix_digest_recomputed": (
            experiment._canonical_digest(regenerated_matrix)
            == run1["matrix_sha256"]
            == run2["matrix_sha256"]
        ),
        "source_files_unchanged_since_run1": (
            current_sources == run1["source_integrity"]
        ),
        "source_files_unchanged_since_run2": (
            current_sources == run2["source_integrity"]
        ),
        "registered_parameters_match": (
            run1["registered_parameters"] == run2["registered_parameters"]
        ),
        "rows_match_byte_semantics": run1["rows"] == run2["rows"],
        "summaries_match": run1["summaries"] == run2["summaries"],
        "acceptance_checks_match": run1["checks"] == run2["checks"],
        "matrix_has_360_unique_cases": (
            len(run1["matrix"]) == 360
            and len({row["case_id"] for row in run1["matrix"]}) == 360
        ),
        "result_has_1080_rows": len(run1["rows"]) == 1_080,
        "policy_schema_excludes_scorer_fields": not (
            experiment.POLICY_EVIDENCE_FIELDS & experiment.SCORER_ONLY_FIELDS
        ),
    }
    if not all(prechecks.values()):
        raise AssertionError(json.dumps(prechecks, indent=2, sort_keys=True))

    if write_canonical:
        canonical_path.write_bytes(run1_path.read_bytes())
    canonical = _load(canonical_path)
    checks = {
        **prechecks,
        "canonical_is_exact_run1": canonical == run1,
        "canonical_sha256_matches_run1": (
            _file_sha256(canonical_path) == _file_sha256(run1_path)
        ),
    }
    if not all(checks.values()):
        raise AssertionError(json.dumps(checks, indent=2, sort_keys=True))

    acceptance_checks = dict(run1["checks"])
    return {
        "schema": "parcel.independent-completion-verification.v1",
        "verified_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run1": run1_path.name,
        "run2": run2_path.name,
        "canonical": canonical_path.name,
        "deterministic_payload_sha256": run1["deterministic_payload_sha256"],
        "artifact_sha256": {
            run1_path.name: _file_sha256(run1_path),
            run2_path.name: _file_sha256(run2_path),
            canonical_path.name: _file_sha256(canonical_path),
        },
        "integrity_checks": checks,
        "acceptance_checks": acceptance_checks,
        "all_integrity_checks_pass": all(checks.values()),
        "all_acceptance_checks_pass": all(acceptance_checks.values()),
        "verified_run_verdict": run1["run_verdict"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run1", type=Path, default=HERE / "results-run1.json")
    parser.add_argument("--run2", type=Path, default=HERE / "results-run2.json")
    parser.add_argument("--canonical", type=Path, default=HERE / "results.json")
    parser.add_argument("--out", type=Path, default=HERE / "verification.json")
    parser.add_argument("--write-canonical", action="store_true")
    args = parser.parse_args()
    verification = verify(
        run1_path=args.run1,
        run2_path=args.run2,
        canonical_path=args.canonical,
        write_canonical=args.write_canonical,
    )
    args.out.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verification, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
