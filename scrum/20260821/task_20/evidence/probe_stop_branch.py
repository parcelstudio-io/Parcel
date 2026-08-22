"""MOVE-1 attribution probe — WHICH branch of the reactive gate stops the dog?

Addendum A1b left 94 % of the static arm's ticks in a bucket named "other":
the geometric gate returned ``stopped`` while no person, no collision, and no
obstacle inside the stop band was recorded. "Other" is not an attribution, and
this card's D4 says so.

This probe names the branch exactly, without guessing: it wraps
``reactive_safety._stop_translation`` and reads ``sys._getframe(1).f_lineno``.
The gate calls that helper from one line per refusal reason, so the line number
IS the reason, read out of the running product rather than inferred from it.

Read-only with respect to the repo: no source file is edited, and the wrapper
returns the real helper's value untouched.
"""

from __future__ import annotations

import os

os.environ.setdefault("MUJOCO_GL", "egl")

import collections
import json
import linecache
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

sys.path.insert(0, str(Path(__file__).parent))
from run_move1_diagnosis import (
    BASE_CONFIG,
    start_simulator,
    stop_simulator,
)


def main() -> None:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(__file__).parent / f"stop_branch_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = REPO / "src" / "parcel_robot" / "scenes" / "city_block.xml"
    config_path = out_dir / "probe.yaml"
    config_path.write_text(
        BASE_CONFIG.format(skills=REPO / "configs" / "skills", scene=scene),
        encoding="utf-8",
    )

    import parcel_robot.navigation.reactive_safety as rs
    from parcel_robot.models import VelocityCommand
    from parcel_robot.web_panel import build_runtime

    reactive_path = rs.__file__
    stop_lines: collections.Counter = collections.Counter()
    scan_calls = {"allowed": 0, "refused": 0}
    refusals: list[str] = []

    real_stop = rs._stop_translation
    real_scan_health = rs._scan_health_allows_translation

    def stop_translation(command):
        stop_lines[sys._getframe(1).f_lineno] += 1
        return real_stop(command)

    def scan_health(observation, *, now):
        allowed = real_scan_health(observation, now=now)
        scan_calls["allowed" if allowed else "refused"] += 1
        return allowed

    rs._stop_translation = stop_translation
    rs._scan_health_allows_translation = scan_health

    socket_path = Path(f"/tmp/parcel-move1-probe-{os.getpid()}.sock")
    process, handle = start_simulator(
        config_path=config_path,
        socket_path=socket_path,
        log_path=out_dir / "simulator.log",
        static_city=True,
    )
    try:
        runtime = build_runtime(config_path, socket_path, use_llm=False)
        runtime.start()
        try:
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                try:
                    runtime.submit_motion(
                        "voice", VelocityCommand(vx=0.25, vy=0.0, vyaw=0.0)
                    )
                except Exception as error:  # noqa: BLE001
                    # A refusal here is a datum, not noise: C-1 recorded
                    # 0/160 rejected, so any rejection in this probe would
                    # change what the run means.
                    refusals.append(str(error))
                time.sleep(0.25)
            final_x = runtime._observation.robot.x if runtime._observation else None
        finally:
            runtime.close()
    finally:
        stop_simulator(process, handle, socket_path)

    branches = [
        {
            "line": line,
            "count": count,
            "source": linecache.getline(reactive_path, line).strip(),
            "context": [
                linecache.getline(reactive_path, n).rstrip()
                for n in range(max(1, line - 4), line + 1)
            ],
        }
        for line, count in stop_lines.most_common()
    ]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "repo_head": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "arm": "held_static",
        "duration_s": duration,
        "final_robot_x_m": final_x,
        "reactive_safety_file": reactive_path,
        "scan_health_calls": scan_calls,
        "motion_refusals": refusals[:10],
        "motion_refusal_count": len(refusals),
        "stop_translation_call_sites": branches,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nwrote {out_dir}/summary.json")


if __name__ == "__main__":
    main()
