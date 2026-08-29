#!/usr/bin/env python
"""Poll nvidia-smi until >= N MiB of GPU memory is free, logging every poll.

DS-1 house rule: do not start the Moshi timing run while another parcel-0e job
holds the card. Polls every 60 s for up to 3 h, appending each observation to
~/.cache/parcel-0e/ds1/gpu_wait.log. Exit 0 = clear to run, 3 = timed out.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def probe() -> tuple[int, int, str]:
    """(free_mib, used_mib, compute_process_summary)"""
    q = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.free,memory.used", "--format=csv,noheader,nounits"],
        text=True, timeout=30,
    )
    free_s, used_s = q.strip().splitlines()[0].split(",")
    try:
        procs = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            text=True, timeout=30,
        ).strip()
        procs = "; ".join(procs.splitlines()) if procs else "none"
    except Exception:  # noqa: BLE001
        procs = "?"
    return int(free_s), int(used_s), procs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--need-mib", type=int, default=26 * 1024)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--max-hours", type=float, default=3.0)
    ap.add_argument(
        "--log", default=str(Path.home() / ".cache/parcel-0e/ds1/gpu_wait.log")
    )
    args = ap.parse_args()

    log = Path(args.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.max_hours * 3600
    poll = 0
    while time.time() < deadline:
        poll += 1
        try:
            free, used, procs = probe()
        except Exception as exc:  # nvidia-smi hiccup: log and keep polling  # noqa: BLE001
            line = f"{time.strftime('%H:%M:%S')} poll={poll} PROBE_ERROR {exc}"
            print(line, flush=True)
            log.open("a").write(line + "\n")
            time.sleep(args.interval)
            continue
        ok = free >= args.need_mib
        line = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} poll={poll} free={free} MiB "
            f"used={used} MiB need={args.need_mib} MiB "
            f"{'CLEAR' if ok else 'WAIT'} compute_apps=[{procs}]"
        )
        print(line, flush=True)
        with log.open("a") as fh:
            fh.write(line + "\n")
        if ok:
            return 0
        time.sleep(args.interval)

    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} TIMEOUT after {args.max_hours} h"
    print(line, file=sys.stderr, flush=True)
    log.open("a").write(line + "\n")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
