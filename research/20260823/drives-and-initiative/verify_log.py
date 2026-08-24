"""Re-derive rows D5, D6 and D8 from the per-tick JSONL, not from the summary.

The run summaries count what the arena thought it did. This reads the log the
arena wrote — the same file a Stage-B trainer would consume — and re-derives:

* **D8** every admitted initiation carries exactly one drive name, and that
  drive really is at or above the threshold in the same tick's DECISION-TIME
  drive vector (``d0``; ``d`` is the end-of-tick vector, after the admitted
  proposal has discharged the drive that justified it);
* **D6** no admitted initiation is inside a quiet window or the night band;
* **D5** the tick an owner turn or an e-stop lands, and the first tick after
  it on which the dispatched command is exact zero with no initiative active.

    .parcel/bin/python research/20260823/drives-and-initiative/verify_log.py \
        /path/to/ticks_*.jsonl.gz
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

THRESHOLD = 0.70


def verify(path: Path) -> dict[str, object]:
    initiations = 0
    attributed = 0
    over_threshold = 0
    in_quiet = 0
    in_night = 0
    latencies: list[dict[str, object]] = []
    pending: dict[str, object] | None = None
    ticks = 0

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            row = json.loads(line)
            ticks += 1
            proposal = row.get("p")
            if proposal is not None and row.get("v") == "admitted":
                initiations += 1
                drive = proposal.get("drive")
                if isinstance(drive, str) and drive:
                    attributed += 1
                    features = row.get("d0") or row["d"]
                    if float(features.get(drive, 0.0)) >= THRESHOLD:
                        over_threshold += 1
                if row.get("quiet"):
                    in_quiet += 1
                if row.get("band") == "night":
                    in_night += 1
            events = row.get("ev") or []
            if row.get("pre") in {"owner_turn", "estop"}:
                pending = {
                    "trigger": row["pre"],
                    "at_tick": index,
                    "at_s": row["t"],
                    "events": list(events),
                }
            if pending is not None:
                moving = any(abs(float(value)) > 0.0 for value in row["cmd"])
                if not moving and row.get("a") is None:
                    pending["ticks_to_yield"] = index - int(pending["at_tick"])
                    pending["command"] = row["cmd"]
                    latencies.append(pending)
                    pending = None

    return {
        "file": path.name,
        "ticks": ticks,
        "initiations": initiations,
        "attributed_to_one_drive": attributed,
        "drive_at_or_over_threshold": over_threshold,
        "admitted_inside_quiet": in_quiet,
        "admitted_inside_night": in_night,
        "preemptions": latencies,
    }


def main(argv: list[str]) -> int:
    paths = [Path(item) for item in argv[1:]]
    if not paths:
        print(__doc__)
        return 2
    totals = {
        "initiations": 0,
        "attributed_to_one_drive": 0,
        "drive_at_or_over_threshold": 0,
        "admitted_inside_quiet": 0,
        "admitted_inside_night": 0,
    }
    worst_latency = 0
    events = 0
    per_file = []
    for path in sorted(paths):
        row = verify(path)
        per_file.append(row)
        for key in totals:
            totals[key] += int(row[key])  # type: ignore[arg-type]
        for item in row["preemptions"]:  # type: ignore[index]
            events += 1
            worst_latency = max(worst_latency, int(item["ticks_to_yield"]))
    print(
        json.dumps(
            {
                "files": len(paths),
                "totals": totals,
                "preemption_events": events,
                "worst_ticks_to_yield": worst_latency,
                "per_file": per_file,
            },
            indent=1,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
