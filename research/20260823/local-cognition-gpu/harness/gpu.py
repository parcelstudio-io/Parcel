"""`nvidia-smi` snapshots, taken at every headline measurement.

The GPU is shared by several executors this session, so a latency number
without the device state beside it is not evidence. Every row this harness
writes carries one of these.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

_GPU_QUERY = "memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu"


def snapshot(label: str = "") -> dict[str, object]:
    device: dict[str, object] = {}
    processes: list[dict[str, object]] = []
    try:
        raw = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_GPU_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        ).stdout.strip()
        total, used, free, util, temp = (part.strip() for part in raw.split(","))
        device = {
            "memory_total_mib": int(total),
            "memory_used_mib": int(used),
            "memory_free_mib": int(free),
            "utilization_pct": int(util),
            "temperature_c": int(temp),
        }
        apps = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory,process_name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        ).stdout.strip()
        for line in apps.splitlines():
            if not line.strip():
                continue
            pid, memory, name = (part.strip() for part in line.split(",", 2))
            processes.append(
                {"pid": int(pid), "used_mib": int(memory), "process": name.split()[0][-60:]}
            )
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        device = {"error": f"{type(error).__name__}: {error}"}
    return {
        "label": label,
        "at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "device": device,
        "compute_apps": processes,
    }
