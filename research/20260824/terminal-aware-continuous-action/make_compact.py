"""Extract the review-sized evidence table from the full experiment result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _run(row: dict[str, Any], *, proposed: bool) -> dict[str, Any]:
    result = {
        key: row[key]
        for key in (
            "seed",
            "expressive_initiations",
            "agent_contacts",
            "contacts_while_stationary",
            "contacts_while_translating",
            "contact_seconds",
            "max_radius_m",
            "command_sha",
            "translation_sha",
            "preemptions",
        )
    }
    if proposed:
        result.update(
            {
                "terminal_rows": row["terminal_rows"],
                "terminal_incomplete": row["terminal_incomplete"],
                "dynamic_gate_counts": row["dynamic_gate_counts"],
                "dynamic_gate_bearings": row["dynamic_gate_bearings"],
            }
        )
    return result


def main() -> int:
    source = HERE / "results.json"
    payload = json.loads(source.read_text())
    compact = {
        key: payload[key]
        for key in (
            "design_sha256",
            "parameters",
            "baseline_integrity",
            "baseline_valid",
            "geometry_table",
            "geometry_passed",
            "rows",
            "headline_confirmed",
        )
    }
    compact["baseline_runs"] = [_run(row, proposed=False) for row in payload["baseline_runs"]]
    compact["proposed_runs"] = [_run(row, proposed=True) for row in payload["proposed_runs"]]
    (HERE / "results.compact.json").write_text(
        json.dumps(compact, separators=(",", ":"), sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
