#!/usr/bin/env python3
"""Card HY-1 — read-only census of every Parcel simulator alive on this host.

The executor contract for this tree says "your last act is returning your
report; stop and reap what you started". That is unenforceable without a way
to see what is running, and ``pgrep -af parcel_robot.sim`` answers with argv
alone: it does not say how old a process is, whether its socket still exists,
or — the question that actually matters before anyone reaches for ``kill`` —
whether it belongs to the **owner's live stack**.

So this prints the census with that column filled in, and it is *only* a
census. It sends no signals; there is no ``--kill`` flag and there should
never be one. A tool that both diagnoses and destroys gets run in a hurry.

Usage
-----
    .parcel/bin/python tools/list_parcel_procs.py
    .parcel/bin/python tools/list_parcel_procs.py --json

Reading the ``kind`` column:

``owner``
    On ``/tmp/parcel_sim.sock`` (or ``$PARCEL_SIM_SOCKET``) — the owner's own
    running stack, paired with the control deck on :8765. **Never kill this.**
``pytest-scratch``
    On a socket under a pytest basetemp. If no pytest run is in flight, this
    is a leak: some suite spawned it and died without tearing it down. Reap it
    deliberately, re-identifying the pid immediately before you signal it.
``other``
    A manually launched sim (``scripts/launch_sim.sh --socket ...``). Whoever
    started it owns it; if that was you, ``--pidfile`` gives you its pid.

Exit status is 0 whether or not anything is found: absence is an answer, not
an error.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
# The census predicate — what counts as a simulator, which argv holds the
# socket — is shared with the pytest guard on purpose. Two copies would drift,
# and a drifted predicate is a leak the operator cannot see. ``tests/_sim_guard``
# imports nothing but the standard library, so this stays a plain script.
#
# Loaded through ``import_module`` rather than an ``import`` statement because
# the path has to be set first, and the alternative spelling would need a
# ``noqa`` that this tree's ruff ratchet does not accept.
sys.path.insert(0, str(_REPO / "tests"))
_sim_guard = importlib.import_module("_sim_guard")


def _pytest_scratch(socket: str | None) -> bool:
    """True when the socket lives under a pytest ``basetemp``.

    Matched on the ``pytest-of-<user>`` directory name that pytest's tmp path
    factory creates, wherever ``TMPDIR`` puts it.
    """

    if socket is None:
        return False
    return any(part.startswith("pytest-of-") for part in Path(socket).parts)


def _parent_argv(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return "<gone>"
    argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    if not argv:
        try:
            return f"[{Path(f'/proc/{pid}/comm').read_text().strip()}]"
        except OSError:
            return "<gone>"
    return " ".join(argv)


def _rss_kb(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, IndexError, ValueError):
        return None
    return None


def _age(started_at: float) -> str:
    seconds = max(0.0, time.time() - started_at)
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def census() -> list[dict]:
    """Every live ``parcel_robot.sim``, oldest first."""

    rows = []
    for proc in sorted(_sim_guard.scan().values(), key=lambda p: p.started_at):
        socket = proc.socket
        if proc.is_owner_stack:
            kind = "owner"
        elif _pytest_scratch(socket):
            kind = "pytest-scratch"
        else:
            kind = "other"
        rows.append(
            {
                "pid": proc.pid,
                "kind": kind,
                "socket": socket,
                "socket_exists": bool(socket and Path(socket).exists()),
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(proc.started_at)),
                "age": _age(proc.started_at),
                "rss_kb": _rss_kb(proc.pid),
                "ppid": proc.ppid,
                "parent": _parent_argv(proc.ppid),
                "argv": list(proc.argv),
            }
        )
    return rows


def render(rows: list[dict]) -> str:
    if not rows:
        return "No parcel_robot.sim process is running on this host."
    lines = [f"{len(rows)} parcel_robot.sim process(es):", ""]
    total_rss = 0
    for row in rows:
        rss = row["rss_kb"]
        total_rss += rss or 0
        lines.append(f"  pid {row['pid']}  [{row['kind']}]  age {row['age']}")
        lines.append(f"      socket : {row['socket'] or '<none>'}" + (
            "" if row["socket_exists"] else "   (path is gone; the process still holds it)"
        ))
        lines.append(f"      started: {row['started_at']}")
        lines.append(f"      memory : {rss / 1024:.0f} MB" if rss else "      memory : unknown")
        lines.append(f"      parent : pid {row['ppid']}  {row['parent'][:100]}")
        if row["kind"] == "owner":
            lines.append("      NOTE   : this is the OWNER'S live stack. Do not kill it.")
        lines.append("")
    if total_rss:
        lines.append(f"Resident total: {total_rss / 1024 / 1024:.1f} GB")
    orphans = [row for row in rows if row["kind"] == "pytest-scratch" and not row["socket_exists"]]
    if orphans:
        lines.append(
            f"{len(orphans)} of these sit on a pytest socket whose directory has already been "
            "deleted — no live test can be using them."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only census of parcel_robot.sim processes (card HY-1).",
        epilog="This tool never signals a process. To stop a sim you launched, "
        "use scripts/launch_sim.sh --pidfile.",
    )
    parser.add_argument("--json", action="store_true", help="emit the census as JSON")
    args = parser.parse_args(argv)
    rows = census()
    print(json.dumps(rows, indent=2) if args.json else render(rows))
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
