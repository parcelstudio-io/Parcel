"""Independent standard-library checks for the post-start DSOAK monitor."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MIN_OBSERVER_GAP_SECONDS = 55.0
MAX_OBSERVER_GAP_SECONDS = 65.0
MAX_STAGNANT_ROWS = 2
MAX_CLOCK_SPAN_DRIFT_SECONDS = 65.0
MAX_UTC_OBSERVER_DRIFT_SECONDS = 5.0
EMPTY_COMMAND_SHA256 = hashlib.sha256(b"").hexdigest()
EXPECTED_ROW_KEYS = {
    "schema",
    "observed_utc",
    "observer_monotonic_ns",
    "boot_id",
    "process",
    "runner_sha256",
    "design_sha256",
    "checkpoint_sha256",
    "checkpoint_readable",
    "checkpoint_status",
    "checkpoint_verdict",
    "checkpoint_elapsed_monotonic_seconds",
    "checkpoint_primary_episodes",
    "checkpoint_pid",
}
EXPECTED_PROCESS_KEYS = {"pid", "proc_start_ticks", "command_sha256"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def _load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line, parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError) as error:
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


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _sha256_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def verify(path: Path, *, result_path: Path = HERE / "results.json") -> dict[str, Any]:
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
    last = rows[-1]
    first_process = first.get("process")
    if not isinstance(first_process, dict):
        errors.append("first row has no monitored process identity")
        first_process = {}
    elif set(first_process) != EXPECTED_PROCESS_KEYS:
        errors.append("first row process identity has unexpected fields")
    if not _positive_int(first_process.get("pid")):
        errors.append("first row process PID is invalid")
    if not _positive_int(first_process.get("proc_start_ticks")):
        errors.append("first row process start ticks are invalid")
    if not _sha256_text(first_process.get("command_sha256")):
        errors.append("first row process command hash is invalid")
    expected_pid = first_process.get("pid")
    terminal_statuses = {"complete", "error", "interrupted"}
    constant_fields = ("boot_id", "runner_sha256", "design_sha256")
    for index, row in enumerate(rows, 1):
        if set(row) != EXPECTED_ROW_KEYS:
            errors.append(f"row {index}: field inventory differs from monitor schema")
        if row.get("schema") != "parcel.duplex_soak.external_monitor.v1":
            errors.append(f"row {index}: unexpected schema")
        if not isinstance(row.get("boot_id"), str) or not row.get("boot_id"):
            errors.append(f"row {index}: invalid boot ID")
        if not _sha256_text(row.get("runner_sha256")):
            errors.append(f"row {index}: invalid runner hash")
        if not _sha256_text(row.get("design_sha256")):
            errors.append(f"row {index}: invalid design hash")
        if _utc(row.get("observed_utc")) is None:
            errors.append(f"row {index}: invalid observed UTC timestamp")
        for field in constant_fields:
            if row.get(field) != first.get(field):
                errors.append(f"row {index}: {field} changed")
        process = row.get("process")
        is_last = index == len(rows)
        terminal = row.get("checkpoint_status") in terminal_statuses
        if not isinstance(process, dict):
            # The runner atomically writes its terminal checkpoint and exits.
            # A monitor sample can therefore bind the completed file after
            # /proc has disappeared.  Permit this only for the final terminal
            # row; every earlier absence is a continuity break.
            if not (is_last and terminal and process is None):
                errors.append(f"row {index}: monitored process is absent")
        elif set(process) != EXPECTED_PROCESS_KEYS:
            errors.append(f"row {index}: process identity has unexpected fields")
        elif not (
            _positive_int(process.get("pid"))
            and _positive_int(process.get("proc_start_ticks"))
            and _sha256_text(process.get("command_sha256"))
        ):
            errors.append(f"row {index}: process identity has invalid values")
        elif process != first_process:
            final_zombie = (
                is_last
                and terminal
                and process.get("pid") == first_process.get("pid")
                and process.get("proc_start_ticks") == first_process.get("proc_start_ticks")
                and process.get("command_sha256") == EMPTY_COMMAND_SHA256
            )
            if not final_zombie:
                errors.append(f"row {index}: monitored process identity changed")
        if not _positive_int(row.get("checkpoint_pid")):
            errors.append(f"row {index}: invalid checkpoint PID")
        if row.get("checkpoint_pid") != expected_pid:
            errors.append(f"row {index}: checkpoint PID differs from initial monitored PID")
        if row.get("checkpoint_readable") is not True:
            errors.append(f"row {index}: checkpoint is not readable")
        checkpoint_hash = row.get("checkpoint_sha256")
        if not _sha256_text(checkpoint_hash):
            errors.append(f"row {index}: invalid checkpoint hash")
        if not _positive_int(row.get("observer_monotonic_ns")):
            errors.append(f"row {index}: invalid observer_monotonic_ns")
        if not (
            _finite_number(row.get("checkpoint_elapsed_monotonic_seconds"))
            and float(row["checkpoint_elapsed_monotonic_seconds"]) >= 0.0
        ):
            errors.append(f"row {index}: invalid checkpoint_elapsed_monotonic_seconds")
        if not _nonnegative_int(row.get("checkpoint_primary_episodes")):
            errors.append(f"row {index}: invalid checkpoint_primary_episodes")

        status = row.get("checkpoint_status")
        if is_last:
            if status != "complete":
                errors.append(f"row {index}: final checkpoint is not complete")
            if row.get("checkpoint_verdict") != "SUPPORTED_PROCEDURAL_SOAK":
                errors.append(f"row {index}: final checkpoint verdict is not supported")
        elif status != "running":
            errors.append(f"row {index}: non-final checkpoint is not running")
        elif row.get("checkpoint_verdict") != "RUNNING_NOT_A_VERDICT":
            errors.append(f"row {index}: non-final checkpoint has a terminal verdict")

    observer_times = [
        int(row["observer_monotonic_ns"])
        if _finite_number(row.get("observer_monotonic_ns"))
        else -1
        for row in rows
    ]
    elapsed = [
        float(row["checkpoint_elapsed_monotonic_seconds"])
        if _finite_number(row.get("checkpoint_elapsed_monotonic_seconds"))
        else -1.0
        for row in rows
    ]
    episodes = [
        int(row["checkpoint_primary_episodes"])
        if _finite_number(row.get("checkpoint_primary_episodes"))
        else -1
        for row in rows
    ]
    if any(right <= left for left, right in pairwise(observer_times)):
        errors.append("observer monotonic time did not strictly increase")
    if any(right < left for left, right in pairwise(elapsed)):
        errors.append("checkpoint elapsed time regressed")
    if any(right < left for left, right in pairwise(episodes)):
        errors.append("checkpoint episode count regressed")
    observer_gaps = [
        (right - left) / 1_000_000_000.0 for left, right in pairwise(observer_times)
    ]
    checkpoint_gaps = [right - left for left, right in pairwise(elapsed)]
    positive_checkpoint_gaps = [gap for gap in checkpoint_gaps if gap > 0.0]
    for index, gap in enumerate(checkpoint_gaps, 2):
        if gap == 0.0:
            continue
        # A terminal result is written at the configured duration rather than
        # on the runner's minute phase.  Preserve strict 55--65 s cadence for
        # every interior update, but allow the last independently bound update
        # up to two monitor intervals.
        upper = 2.0 * MAX_OBSERVER_GAP_SECONDS if index == len(rows) else 65.0
        if gap < 55.0 or gap > upper:
            errors.append(f"row {index}: checkpoint update cadence {gap:.3f}s is invalid")
    if any(gap < MIN_OBSERVER_GAP_SECONDS for gap in observer_gaps):
        errors.append(
            f"observer gap is below {MIN_OBSERVER_GAP_SECONDS:.1f}s (duplicate/reordered row)"
        )
    max_observer_gap = max(observer_gaps, default=0.0)
    if max_observer_gap > MAX_OBSERVER_GAP_SECONDS:
        errors.append(
            f"observer gap {max_observer_gap:.3f}s exceeds {MAX_OBSERVER_GAP_SECONDS:.1f}s"
        )
    stagnant_run = 1
    max_stagnant_rows = 1
    for left, right in pairwise(episodes):
        stagnant_run = stagnant_run + 1 if right == left else 1
        max_stagnant_rows = max(max_stagnant_rows, stagnant_run)
    if max_stagnant_rows > MAX_STAGNANT_ROWS:
        errors.append(
            f"episode progress was unchanged for {max_stagnant_rows} monitor rows"
        )
    for index in range(2, len(rows)):
        if elapsed[index] <= elapsed[index - 2]:
            errors.append(f"row {index + 1}: elapsed time did not advance over two rows")
        if episodes[index] <= episodes[index - 2]:
            errors.append(f"row {index + 1}: episode count did not advance over two rows")
        if rows[index].get("checkpoint_sha256") == rows[index - 2].get(
            "checkpoint_sha256"
        ):
            errors.append(f"row {index + 1}: checkpoint hash did not advance over two rows")
    observer_span = (
        (observer_times[-1] - observer_times[0]) / 1_000_000_000.0
        if len(observer_times) > 1
        else 0.0
    )
    checkpoint_span = elapsed[-1] - elapsed[0] if len(elapsed) > 1 else 0.0
    clock_span_drift = abs(observer_span - checkpoint_span)
    if clock_span_drift > MAX_CLOCK_SPAN_DRIFT_SECONDS:
        errors.append(
            "observer/checkpoint clock-span drift "
            f"{clock_span_drift:.3f}s exceeds {MAX_CLOCK_SPAN_DRIFT_SECONDS:.1f}s"
        )
    for index, (observer_ns, checkpoint_elapsed) in enumerate(
        zip(observer_times, elapsed), 1
    ):
        relative_observer = (observer_ns - observer_times[0]) / 1_000_000_000.0
        relative_checkpoint = checkpoint_elapsed - elapsed[0]
        if abs(relative_observer - relative_checkpoint) > MAX_CLOCK_SPAN_DRIFT_SECONDS:
            errors.append(f"row {index}: observer/checkpoint relative clock drift is excessive")
    utc_values = [_utc(row.get("observed_utc")) for row in rows]
    if all(value is not None for value in utc_values):
        utc_seconds = [value.timestamp() for value in utc_values if value is not None]
        if any(right <= left for left, right in pairwise(utc_seconds)):
            errors.append("observed UTC time did not strictly increase")
        for index, ((left_utc, right_utc), observer_gap) in enumerate(
            zip(pairwise(utc_seconds), observer_gaps), 2
        ):
            if abs((right_utc - left_utc) - observer_gap) > MAX_UTC_OBSERVER_DRIFT_SECONDS:
                errors.append(f"row {index}: UTC/monotonic observer delta drift is excessive")
    if first.get("runner_sha256") != _digest(HERE / "run_soak.py"):
        errors.append("runner differs from monitored hash")
    if first.get("design_sha256") != _digest(HERE / "DESIGN.md"):
        errors.append("design differs from monitored hash")

    final_result: dict[str, Any] | None = None
    final_result_hash: str | None = None
    try:
        raw_result = result_path.read_bytes()
        loaded = json.loads(raw_result, parse_constant=_reject_constant)
        if not isinstance(loaded, dict):
            raise TypeError("final result is not an object")
        final_result = loaded
        final_result_hash = hashlib.sha256(raw_result).hexdigest()
    except (OSError, TypeError, json.JSONDecodeError) as error:
        errors.append(f"final result cannot be bound: {error}")
    if final_result is not None:
        result_counts = final_result.get("counts") or {}
        result_config = final_result.get("configuration") or {}
        if last.get("checkpoint_sha256") != final_result_hash:
            errors.append("final monitor checkpoint hash differs from final result")
        if last.get("checkpoint_status") != final_result.get("status"):
            errors.append("final monitor status differs from final result")
        if last.get("checkpoint_verdict") != final_result.get("verdict"):
            errors.append("final monitor verdict differs from final result")
        if last.get("checkpoint_pid") != result_config.get("process_id"):
            errors.append("final monitor PID differs from final result")
        if last.get("checkpoint_primary_episodes") != result_counts.get("primary_episodes"):
            errors.append("final monitor episode count differs from final result")
        if not math.isclose(
            float(last.get("checkpoint_elapsed_monotonic_seconds", -1.0)),
            float(final_result.get("elapsed_monotonic_seconds", -2.0)),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            errors.append("final monitor elapsed time differs from final result")
        result_updated = _utc(final_result.get("updated_utc"))
        final_observed = _utc(last.get("observed_utc"))
        if result_updated is None:
            errors.append("final result updated_utc is invalid")
        elif final_observed is not None:
            final_age = (final_observed - result_updated).total_seconds()
            if not 0.0 <= final_age <= MAX_OBSERVER_GAP_SECONDS:
                errors.append("final monitor observation is not timely after result update")

    final_status = last.get("checkpoint_status")
    final_elapsed = (
        float(final_result.get("elapsed_monotonic_seconds", 0.0))
        if final_result is not None
        else 0.0
    )
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
        "final_result": str(result_path),
        "final_result_sha256": final_result_hash,
        "max_observer_gap_seconds": max_observer_gap,
        "minimum_positive_checkpoint_gap_seconds": min(
            positive_checkpoint_gaps, default=0.0
        ),
        "maximum_positive_checkpoint_gap_seconds": max(
            positive_checkpoint_gaps, default=0.0
        ),
        "max_stagnant_monitor_rows": max_stagnant_rows,
        "observer_span_seconds": observer_span,
        "checkpoint_span_seconds": checkpoint_span,
        "clock_span_drift_seconds": clock_span_drift,
        "observed_fraction_of_final_elapsed": (
            checkpoint_span / final_elapsed if final_elapsed > 0.0 else 0.0
        ),
        "integrity_pass": not errors,
        "continuity_observed_to_completion": not errors and final_status == "complete",
        "errors": errors,
        "scope_warning": (
            "Monitoring began after the soak started and cannot attest the earlier interval; "
            "it verifies continuity only from its first row. Cadence, clock, and two-row "
            "progress checks are supplemental post-start audit rules, not preregistered gates."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=HERE / "external-monitor.jsonl")
    parser.add_argument("--result", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    report = verify(args.path, result_path=args.result)
    print(json.dumps(report, indent=2, sort_keys=True))
    # Integrity without observed completion is not command success.  This
    # makes an interim monitor log fail closed for automation.
    return 0 if report["continuity_observed_to_completion"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
