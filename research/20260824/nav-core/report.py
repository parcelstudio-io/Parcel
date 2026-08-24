"""Turn ``results/*.json`` into the rows RESULTS.md quotes.  Nothing is typed."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def _load(name: str) -> dict[str, Any]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def corpus_table() -> str:
    payload = _load("corpus.json")
    lines = ["| row | bar | arm A | arm B |", "|---|---|---|---|"]
    a, b = payload["arms"]["A"], payload["arms"]["B"]

    def pct(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f}"

    rows = (
        ("N1 arrival <= 0.5 m", ">= 0.80 either arm",
         pct(a["N1_arrival_rate"]), pct(b["N1_arrival_rate"])),
        ("N1' arrival, object-class goals only", "(diagnostic)",
         pct(a["N1_arrival_rate_object_class_goals"]),
         pct(b["N1_arrival_rate_object_class_goals"])),
        ("N2 false arrivals", "0", a["N2_false_arrivals"], b["N2_false_arrivals"]),
        ("N3 contacts", "0", a["N3_contacts"], b["N3_contacts"]),
        ("N4 typed non-arrivals", "1.00",
         pct(a["N4_typed_failure_rate"]), pct(b["N4_typed_failure_rate"])),
        ("N5 median time-to-goal (s)", "reported",
         pct(a["N5_median_time_to_goal_s"]), pct(b["N5_median_time_to_goal_s"])),
        ("N5 median path/optimal", "reported",
         pct(a["N5_median_path_over_optimal"]), pct(b["N5_median_path_over_optimal"])),
        ("episodes", "60 each", a["episodes"], b["episodes"]),
    )
    lines += [f"| {row} | {bar} | {left} | {right} |" for row, bar, left, right in rows]
    return "\n".join(lines)


def failure_tables() -> str:
    payload = _load("corpus.json")
    out = []
    for arm in ("A", "B"):
        rows = payload["arms"][arm]["failure_histogram"]
        out.append(f"arm {arm}: " + ", ".join(f"{k} x{v}" for k, v in rows.items()))
    return "\n".join(out)


def refuter_table() -> str:
    payload = _load("refuters.json")
    rows = payload["rows"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row.get("refuter", "?"), row.get("arm", "?")), []).append(row)
    header = (
        "| refuter | arm | n | declared | false arrivals | contacts |"
        " translated during gap | latched | typed failures |"
    )
    lines = [header, "|---|---|---|---|---|---|---|---|---|"]
    for (refuter, arm), members in sorted(groups.items()):
        declared = sum(bool(m.get("declared_arrival")) for m in members)
        false = sum(bool(m.get("false_arrival")) for m in members)
        contacts = sum(int(m.get("contacts") or 0) for m in members)
        gap = sum(int(m.get("gap_translating_ticks") or 0) for m in members)
        latched = sum(bool(m.get("latched")) for m in members)
        types = Counter(str(m.get("failure_type") or "-") for m in members)
        lines.append(
            f"| {refuter} | {arm} | {len(members)} | {declared} | {false} | "
            f"{contacts} | {gap} | {latched} | "
            + ", ".join(f"{k} x{v}" for k, v in types.most_common())
            + " |"
        )
    return "\n".join(lines)


def kidnap_detail() -> str:
    payload = _load("refuters.json")
    header = (
        "| configuration | arm | post-kidnap path (m) |"
        " post-kidnap HEALTHY ticks | latched | declared | false arrival |"
    )
    lines = [header, "|---|---|---|---|---|---|---|"]
    for row in payload["rows"]:
        if not str(row.get("refuter", "")).startswith("R4b"):
            continue
        lines.append(
            f"| {row['refuter']} | {row['arm']} | "
            f"{float(row.get('post_kidnap_path_m') or 0.0):.2f} | "
            f"{row.get('post_kidnap_healthy_ticks')}/{row.get('post_kidnap_ticks')} | "
            f"{row.get('latched')} | {row.get('declared_arrival')} | "
            f"{row.get('false_arrival')} |"
        )
    return "\n".join(lines)


def environment() -> str:
    payload = _load("corpus.json")
    return json.dumps(payload["environment"], indent=1)


if __name__ == "__main__":
    print("## corpus\n")
    print(corpus_table())
    print("\n## failures\n")
    print(failure_tables())
    print("\n## refuters\n")
    print(refuter_table())
    print("\n## kidnap\n")
    print(kidnap_detail())
    print("\n## environment\n")
    print(environment())
