"""Independent standard-library checks for the post-start DSOAK monitor."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from itertools import pairwise
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {number} is not JSON: {error}") from error
        if not isinstance(value, dict):
            raise TypeError(f"line {number} is not an object")
        rows.append(value)
    if not rows:
        raise ValueError("monitor contains no rows")
    return rows


def _finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def verify(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        rows = _load(path)
    except (OSError, TypeError, ValueError) as error:
        return {
            "schema": "parcel.duplex_soak.external_monitor.verification.v1",
            "source": str(path),
            "integrity_pass": False,
            "continuity_observed_to_completion": False,
            "errors": [str(error)],
        }

    first = rows[0]
    constant_fields = ("boot_id", "runner_sha256", "design_sha256", "process")
    for index, row in enumerate(rows, 1):
        if row.get("schema") != "parcel.duplex_soak.external_monitor.v1":
            errors.append(f"row {index}: unexpected schema")
        for field in constant_fields:
            if row.get(field) != first.get(field):
                errors.append(f"row {index}: {field} changed")
        process = row.get("process")
        if not isinstance(process, dict):
            errors.append(f"row {index}: monitored process is absent")
        elif row.get("checkpoint_pid") != process.get("pid"):
            errors.append(f"row {index}: checkpoint PID differs from monitored PID")
        for field in (
            "observer_monotonic_ns",
            "checkpoint_elapsed_monotonic_seconds",
            "checkpoint_primary_episodes",
        ):
            if not _finite_number(row.get(field)):
                errors.append(f"row {index}: invalid {field}")

    observer_times = [int(row["observer_monotonic_ns"]) for row in rows]
    elapsed = [float(row["checkpoint_elapsed_monotonic_seconds"]) for row in rows]
    episodes = [int(row["checkpoint_primary_episodes"]) for row in rows]
    if any(right <= left for left, right in pairwise(observer_times)):
        errors.append("observer monotonic time did not strictly increase")
    if any(right < left for left, right in pairwise(elapsed)):
        errors.append("checkpoint elapsed time regressed")
    if any(right < left for left, right in pairwise(episodes)):
        errors.append("checkpoint episode count regressed")
    if first.get("runner_sha256") != _digest(HERE / "run_soak.py"):
        errors.append("runner differs from monitored hash")
    if first.get("design_sha256") != _digest(HERE / "DESIGN.md"):
        errors.append("design differs from monitored hash")

    final_status = rows[-1].get("checkpoint_status")
    return {
        "schema": "parcel.duplex_soak.external_monitor.verification.v1",
        "source": str(path),
        "source_sha256": _digest(path),
        "row_count": len(rows),
        "first_checkpoint_elapsed_seconds": elapsed[0],
        "last_checkpoint_elapsed_seconds": elapsed[-1],
        "first_episode_count": episodes[0],
        "last_episode_count": episodes[-1],
        "final_checkpoint_status": final_status,
        "integrity_pass": not errors,
        "continuity_observed_to_completion": not errors and final_status == "complete",
        "errors": errors,
        "scope_warning": (
            "Monitoring began after the soak started and cannot attest the earlier interval; "
            "it verifies continuity only from its first row."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=HERE / "external-monitor.jsonl")
    args = parser.parse_args()
    report = verify(args.path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["integrity_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
