"""Post-start, read-only continuity monitor for DSOAK-1.

This monitor is intentionally outside the preregistered soak gate.  It never
imports the runner or simulator and never writes ``results.json``.  Its JSONL
history makes process replacement, source drift, and checkpoint replacement
visible from the time monitoring begins; it cannot attest the interval before
its first row.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _process_identity(pid: int) -> dict[str, Any] | None:
    proc = Path("/proc") / str(pid)
    try:
        stat_fields = (proc / "stat").read_text(encoding="utf-8").split()
        command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        ).strip()
    except (FileNotFoundError, ProcessLookupError):
        return None
    return {
        "pid": pid,
        "proc_start_ticks": int(stat_fields[21]),
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
    }


def _checkpoint(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"checkpoint_sha256": _sha256(path), "checkpoint_readable": False}
    if not isinstance(value, dict):
        return {"checkpoint_sha256": hashlib.sha256(raw).hexdigest(), "checkpoint_readable": False}
    counts = value.get("counts")
    return {
        "checkpoint_sha256": hashlib.sha256(raw).hexdigest(),
        "checkpoint_readable": True,
        "checkpoint_status": value.get("status"),
        "checkpoint_verdict": value.get("verdict"),
        "checkpoint_elapsed_monotonic_seconds": value.get("elapsed_monotonic_seconds"),
        "checkpoint_primary_episodes": (
            counts.get("primary_episodes") if isinstance(counts, dict) else None
        ),
        "checkpoint_pid": (
            value.get("configuration", {}).get("process_id")
            if isinstance(value.get("configuration"), dict)
            else None
        ),
    }


def _row(pid: int, result: Path) -> dict[str, Any]:
    return {
        "schema": "parcel.duplex_soak.external_monitor.v1",
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "observer_monotonic_ns": time.monotonic_ns(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip(),
        "process": _process_identity(pid),
        "runner_sha256": _sha256(HERE / "run_soak.py"),
        "design_sha256": _sha256(HERE / "DESIGN.md"),
        **_checkpoint(result),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--result", type=Path, default=HERE / "results.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if args.pid <= 0 or args.interval_seconds <= 0.0:
        raise SystemExit("pid and interval must be positive")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with args.out.open("x", encoding="utf-8") as stream:
        while True:
            row = _row(args.pid, args.result)
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            process = row["process"]
            if process is None or row.get("checkpoint_status") in {
                "complete",
                "error",
                "interrupted",
            }:
                return 0
            time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
