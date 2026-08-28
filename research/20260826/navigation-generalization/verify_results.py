"""Verify deterministic repeats and acceptance facts for research artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load(name: str) -> dict[str, Any]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _digest(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    deterministic = {key: payload[key] for key in keys}
    encoded = json.dumps(
        deterministic, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify() -> dict[str, Any]:
    run1 = _load("results-run1.json")
    run2 = _load("results-run2.json")
    canonical = _load("results.json")
    h1b_run1 = _load("results-h1b-run1.json")
    h1b_run2 = _load("results-h1b-run2.json")
    h1b_canonical = _load("results-h1b.json")
    sources = _load("SOURCES.json")

    primary_keys = ("schema", "experiments", "summaries", "verdicts")
    h1b_keys = (
        "schema",
        "status_set",
        "bound_ticks",
        "bound_s",
        "provenance",
        "summaries",
        "paired_changes",
        "checks",
        "verdict",
        "rows",
    )

    primary_digest = _digest(run1, primary_keys)
    h1b_digest = _digest(h1b_run1, h1b_keys)
    source_rows = sources["sources"]
    source_ids = [row["id"] for row in source_rows]

    checks = {
        "primary_digest_recomputed": (
            primary_digest == run1["deterministic_payload_sha256"]
        ),
        "primary_repeat_matches": (
            run1["deterministic_payload_sha256"]
            == run2["deterministic_payload_sha256"]
        ),
        "primary_canonical_is_run1": canonical == run1,
        "h1b_digest_recomputed": (
            h1b_digest == h1b_run1["deterministic_payload_sha256"]
        ),
        "h1b_repeat_matches": (
            h1b_run1["deterministic_payload_sha256"]
            == h1b_run2["deterministic_payload_sha256"]
        ),
        "h1b_canonical_is_run1": h1b_canonical == h1b_run1,
        "h1_preregistered_refuted": run1["verdicts"]["H1"]["verdict"]
        == "REFUTED",
        "h2_negative_hypothesis_supported": run1["verdicts"]["H2"]["verdict"]
        == "SUPPORTED",
        "h1b_explicitly_exploratory": h1b_run1["verdict"]
        == "SUPPORTED_EXPLORATORY",
        "h1b_all_checks_pass": all(h1b_run1["checks"].values()),
        "source_ids_unique": len(source_ids) == len(set(source_ids)),
        "source_manifest_has_access_date": sources["accessed"] == "2026-08-26",
        "source_rows_have_version_and_https_url": all(
            row.get("version")
            and str(row.get("url", "")).startswith("https://")
            for row in source_rows
        ),
    }
    assert all(checks.values()), json.dumps(checks, indent=2)

    return {
        "schema": "parcel.navigation-generalization.verification.v1",
        "verdict": "PASS",
        "checks": checks,
        "deterministic_payload_sha256": {
            "primary": primary_digest,
            "h1b": h1b_digest,
        },
        "episode_executions_per_repeat": {
            "primary": 174,
            "h1b": 84,
        },
        "total_episode_executions": 516,
        "primary_source_count": len(source_rows),
        "source_manifest_sha256": hashlib.sha256(
            (HERE / "SOURCES.json").read_bytes()
        ).hexdigest(),
        "hardware_used": "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "verification.json")
    args = parser.parse_args()
    report = verify()
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
