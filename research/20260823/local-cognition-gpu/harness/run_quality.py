"""Rows G5 and G6: decision agreement with gold, and the false-remark rate.

Each of the 60 gold digests goes to each model once at temperature 0. Three
numbers come out, and they are kept apart on purpose:

* ``strict_agreement`` — the pre-registered G5 number. A reply that fails the
  fail-closed contract parse counts as a DISAGREEMENT, because a tick whose
  output the runtime would reject has not decided anything.
* ``kind_agreement_of_parsed`` — the same over parsed replies only. Diagnostic:
  the gap between the two is exactly the contract-compliance cost.
* ``false_remark_rate`` — G6, over the 24 gold-``ignore`` digests, counting a
  reply whose kind is ``remark``. ``remark_or_ask`` is reported beside it,
  because an unwanted question annoys an owner exactly as much as an unwanted
  statement and the pre-registered row names only ``remark``.

``kind_from_raw`` is recovered from the raw JSON even when the full contract
parse failed, so a reader can see WHICH field a model broke rather than only
that it broke one.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3] / "src"))

from gold_set import gold_cases
from gpu import snapshot
from tick import TickClient

MODELS = {
    "ministral-8b": ("http://127.0.0.1:8082", "ministral-8b"),
    "gemma-26b": ("http://127.0.0.1:8081", "gemma-4-26b-a4b"),
}


def _kind_from_raw(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.partition("\n")[2].rsplit("```", 1)[0]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("kind", ""))


def _score(rows: list[dict[str, object]]) -> dict[str, object]:
    total = len(rows)
    strict_hits = sum(1 for row in rows if row["parsed"] and row["kind"] == row["gold_kind"])
    parsed = [row for row in rows if row["parsed"]]
    parsed_hits = sum(1 for row in parsed if row["kind"] == row["gold_kind"])
    ignore_rows = [row for row in rows if row["gold_kind"] == "ignore"]
    remarks = sum(1 for row in ignore_rows if row["kind_from_raw"] == "remark")
    remark_or_ask = sum(1 for row in ignore_rows if row["kind_from_raw"] in ("remark", "ask"))
    confusion = Counter(
        (str(row["gold_kind"]), str(row["kind_from_raw"] or "UNPARSED")) for row in rows
    )
    arguable = [row for row in rows if row["arguable"]]
    non_arguable = [row for row in rows if not row["arguable"]]
    return {
        "cases": total,
        "parse_failures": total - len(parsed),
        "parse_failure_reasons": Counter(
            str(row["error"]).split(":", 1)[-1].strip()[:70]
            for row in rows
            if not row["parsed"]
        ),
        "strict_agreement": round(strict_hits / total, 3) if total else None,
        "kind_agreement_of_parsed": round(parsed_hits / len(parsed), 3) if parsed else None,
        "agreement_non_arguable": (
            round(
                sum(1 for row in non_arguable if row["parsed"] and row["kind"] == row["gold_kind"])
                / len(non_arguable),
                3,
            )
            if non_arguable
            else None
        ),
        "agreement_arguable": (
            round(
                sum(1 for row in arguable if row["parsed"] and row["kind"] == row["gold_kind"])
                / len(arguable),
                3,
            )
            if arguable
            else None
        ),
        "ignore_cases": len(ignore_rows),
        "false_remark_count": remarks,
        "false_remark_rate": round(remarks / len(ignore_rows), 3) if ignore_rows else None,
        "false_remark_or_ask_rate": (
            round(remark_or_ask / len(ignore_rows), 3) if ignore_rows else None
        ),
        "confusion": {f"{gold}->{got}": count for (gold, got), count in sorted(confusion.items())},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", default=str(HERE.parent / "results" / "quality.json"))
    args = parser.parse_args(argv)

    cases = gold_cases()
    report: dict[str, object] = {"repeats": args.repeats, "models": {}, "gpu": []}
    models: dict[str, object] = report["models"]  # type: ignore[assignment]
    gpu_rows: list[dict[str, object]] = report["gpu"]  # type: ignore[assignment]

    for name in (part.strip() for part in args.models.split(",") if part.strip()):
        base_url, model_id = MODELS[name]
        client = TickClient(base_url, model_id)
        gpu_rows.append(snapshot(f"quality:{name}:start"))
        rows: list[dict[str, object]] = []
        for _ in range(args.repeats):
            for case in cases:
                outcome = client.tick(case.digest, digest_id=case.case_id)
                rows.append(
                    {
                        "case_id": case.case_id,
                        "family": case.family,
                        "gold_kind": case.gold_kind,
                        "arguable": case.arguable,
                        "parsed": outcome.parsed,
                        "kind": outcome.decision.kind if outcome.decision else "",
                        "kind_from_raw": _kind_from_raw(outcome.raw),
                        "target": outcome.decision.target if outcome.decision else "",
                        "text": outcome.decision.text if outcome.decision else "",
                        "reason": outcome.decision.reason if outcome.decision else "",
                        "error": outcome.error,
                        "total_ms": round(outcome.total_ms, 1),
                        "raw": outcome.raw[:400],
                    }
                )
        gpu_rows.append(snapshot(f"quality:{name}:end"))
        summary = _score(rows)
        summary["parse_failure_reasons"] = dict(summary["parse_failure_reasons"])  # type: ignore
        models[name] = {"summary": summary, "rows": rows}
        print(name, json.dumps(summary, indent=1))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
